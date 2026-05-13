"""R47 运行时计数器回归契约。

覆盖三个新指标族 + 一个新 API：

1. ``_SSEBus`` 三个累计计数器（``_emit_total`` / ``_gap_warnings_emitted`` /
   ``_backpressure_discards``）+ ``stats_snapshot()`` 公开接口，让 web UI /
   状态栏 / 监控面板能不订阅 SSE 流就拿到健康度指标。
2. ``server_feedback._FEEDBACK_COUNTERS`` 三个生命周期计数（``created_total`` /
   ``completed_total`` / ``failed_total``）+ ``get_feedback_counters()`` 公开接口；
   通过直接调 ``_bump_feedback_counter`` 验证（``interactive_feedback`` 整体
   是 async + 跨进程，不在单测里跑全套）。
3. ``server.server_info_resource`` 在 R44 已有的 4 个子块基础上新增
   ``interactive_feedback`` 子块，内容来自 ``get_feedback_counters()``。
4. 新增 ``/api/system/sse-stats`` 接口的 schema / 来源契约。

设计原则：
- 单元测试粒度，不依赖 web_ui 子进程或 MCP client；
- 计数器测完一个用例必须复位，避免 pytest 跨用例顺序污染（测试用本地
  ``_SSEBus()`` 实例 + 在 ``setUp`` / ``tearDown`` 里手动复位
  ``_FEEDBACK_COUNTERS``）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.server as server
import ai_intervention_agent.server_feedback as server_feedback
from ai_intervention_agent.web_ui_routes.task import _sse_bus, _SSEBus

# ============================================================================
# 1. _SSEBus 计数器
# ============================================================================


class TestSSEBusCountersInitialState(unittest.TestCase):
    """新建 ``_SSEBus`` 实例时，所有 R47 计数器初值必须是 0。"""

    def test_emit_total_starts_at_zero(self) -> None:
        bus = _SSEBus()
        self.assertEqual(bus._emit_total, 0)

    def test_gap_warnings_starts_at_zero(self) -> None:
        bus = _SSEBus()
        self.assertEqual(bus._gap_warnings_emitted, 0)

    def test_backpressure_discards_starts_at_zero(self) -> None:
        bus = _SSEBus()
        self.assertEqual(bus._backpressure_discards, 0)


class TestSSEBusEmitTotalIncrements(unittest.TestCase):
    """``emit()`` 每被调用一次，``_emit_total`` 必须 +1（无论有无订阅者）。"""

    def test_emit_with_no_subscribers_still_counts(self) -> None:
        bus = _SSEBus()
        bus.emit("task_changed", {"task_id": "t1"})
        bus.emit("task_changed", {"task_id": "t2"})
        bus.emit("task_changed", {"task_id": "t3"})
        # 没人订阅时也要计数，让运维能判断"emit 了但没人收"的死流量场景
        self.assertEqual(bus._emit_total, 3)

    def test_emit_with_subscribers_counts_once_per_call(self) -> None:
        bus = _SSEBus()
        bus.subscribe()
        bus.subscribe()
        bus.subscribe()  # 3 个订阅者
        bus.emit("task_changed", {"task_id": "t1"})
        # 一次 emit() 不管 fan-out 几份 put_nowait，只算 1 次 emit
        self.assertEqual(bus._emit_total, 1)


class TestSSEBusGapWarningCounter(unittest.TestCase):
    """``subscribe(after_id=...)`` 命中 evict 分支时 ``_gap_warnings_emitted`` +1。"""

    def test_subscribe_with_evicted_after_id_increments_counter(self) -> None:
        bus = _SSEBus()
        # 灌满 + 溢出 history，强制 evict
        evict_count = bus._HISTORY_MAXLEN + 5
        for i in range(evict_count):
            bus.emit("task_changed", {"task_id": f"t{i}"})

        self.assertEqual(bus._gap_warnings_emitted, 0)
        bus.subscribe(after_id=1)  # after_id=1 一定已被 evict
        self.assertEqual(bus._gap_warnings_emitted, 1)

    def test_subscribe_within_history_does_not_increment(self) -> None:
        bus = _SSEBus()
        for i in range(5):
            bus.emit("task_changed", {"task_id": f"t{i}"})
        # after_id=2 < latest_id=5 且 history 充足，不该走 gap 分支
        bus.subscribe(after_id=2)
        self.assertEqual(bus._gap_warnings_emitted, 0)

    def test_subscribe_with_none_after_id_never_increments(self) -> None:
        bus = _SSEBus()
        for i in range(3):
            bus.emit("task_changed", {"task_id": f"t{i}"})
        bus.subscribe()  # 默认 None
        self.assertEqual(bus._gap_warnings_emitted, 0)


class TestSSEBusBackpressureCounter(unittest.TestCase):
    """``emit()`` 触发 backpressure / Full discard 时 ``_backpressure_discards`` +1。"""

    def test_full_queue_increments_backpressure_discards(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        # 灌满 queue
        for i in range(_SSEBus._QUEUE_MAXSIZE):
            q.put_nowait({"type": "filler", "data": {"i": i}})

        self.assertEqual(bus._backpressure_discards, 0)
        bus.emit("overflow", {"task_id": "drop"})
        self.assertEqual(bus._backpressure_discards, 1)

    def test_threshold_increments_backpressure_discards(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        for i in range(_SSEBus._BACKPRESSURE_THRESHOLD - 1):
            q.put_nowait({"type": "filler", "data": {"i": i}})

        self.assertEqual(bus._backpressure_discards, 0)
        bus.emit("threshold", {"task_id": "discard"})
        self.assertEqual(bus._backpressure_discards, 1)

    def test_normal_emit_does_not_increment_backpressure(self) -> None:
        bus = _SSEBus()
        bus.subscribe()
        for i in range(5):
            bus.emit("task_changed", {"task_id": f"t{i}"})
        self.assertEqual(bus._backpressure_discards, 0)


class TestSSEBusStatsSnapshotShape(unittest.TestCase):
    """``stats_snapshot()`` 必须返回稳定 schema 的 dict[str, int]。"""

    def test_snapshot_returns_dict_with_required_keys(self) -> None:
        bus = _SSEBus()
        snapshot = bus.stats_snapshot()
        self.assertIsInstance(snapshot, dict)
        for key in (
            "emit_total",
            "latest_event_id",
            "gap_warnings_emitted",
            "backpressure_discards",
            "subscriber_count",
            "history_size",
        ):
            self.assertIn(key, snapshot, f"stats_snapshot 缺字段 {key!r}")
            self.assertIsInstance(
                snapshot[key],
                int,
                f"{key} 必须是 int，实际 {type(snapshot[key]).__name__}",
            )

    def test_snapshot_is_a_copy_not_a_reference(self) -> None:
        """``stats_snapshot()`` 必须是值快照，外部修改不影响内部状态。"""
        bus = _SSEBus()
        snap = bus.stats_snapshot()
        snap["emit_total"] = 999
        # 内部状态不应被外部 mutate 影响
        self.assertEqual(bus._emit_total, 0)
        self.assertEqual(bus.stats_snapshot()["emit_total"], 0)

    def test_snapshot_reflects_recent_changes(self) -> None:
        bus = _SSEBus()
        bus.emit("a", {"k": 1})
        bus.emit("b", {"k": 2})
        snap = bus.stats_snapshot()
        self.assertEqual(snap["emit_total"], 2)
        self.assertEqual(snap["latest_event_id"], 2)
        self.assertEqual(snap["history_size"], 2)


class TestModuleLevelSSEBus(unittest.TestCase):
    """模块级 ``_sse_bus`` 单例必须暴露 ``stats_snapshot()`` 接口。"""

    def test_module_level_singleton_has_method(self) -> None:
        self.assertTrue(hasattr(_sse_bus, "stats_snapshot"))
        snap = _sse_bus.stats_snapshot()
        self.assertIsInstance(snap, dict)
        # 模块级单例可能被 import 阶段的其它测试改过，所以只锁字段存在
        # 而不锁具体值
        self.assertIn("emit_total", snap)


# ============================================================================
# 2. server_feedback._FEEDBACK_COUNTERS + get_feedback_counters
# ============================================================================


class TestFeedbackCountersInitialAndPublicAPI(unittest.TestCase):
    """``_FEEDBACK_COUNTERS`` schema + ``get_feedback_counters`` 是只读快照。"""

    def setUp(self) -> None:
        # 测试隔离：保存当前值，测完恢复（避免污染其它测试）
        self._saved = dict(server_feedback._FEEDBACK_COUNTERS)

    def tearDown(self) -> None:
        with server_feedback._FEEDBACK_COUNTERS_LOCK:
            server_feedback._FEEDBACK_COUNTERS.clear()
            server_feedback._FEEDBACK_COUNTERS.update(self._saved)

    def test_required_keys_present(self) -> None:
        for key in ("created_total", "completed_total", "failed_total"):
            self.assertIn(
                key,
                server_feedback._FEEDBACK_COUNTERS,
                f"_FEEDBACK_COUNTERS 缺字段 {key!r}",
            )
            self.assertIsInstance(server_feedback._FEEDBACK_COUNTERS[key], int)

    def test_get_feedback_counters_returns_copy(self) -> None:
        snap = server_feedback.get_feedback_counters()
        self.assertIsInstance(snap, dict)
        snap["created_total"] = 99999
        self.assertNotEqual(
            server_feedback._FEEDBACK_COUNTERS["created_total"],
            99999,
            "get_feedback_counters 必须返回拷贝",
        )

    def test_bump_increments_counter(self) -> None:
        before = server_feedback._FEEDBACK_COUNTERS["created_total"]
        server_feedback._bump_feedback_counter("created_total")
        after = server_feedback._FEEDBACK_COUNTERS["created_total"]
        self.assertEqual(after - before, 1)

    def test_bump_unknown_key_does_not_raise(self) -> None:
        before = dict(server_feedback._FEEDBACK_COUNTERS)
        # 未知 key 应当被忽略 + 写 warning 日志，绝不抛异常 / 也不创建新 key
        server_feedback._bump_feedback_counter("totally_made_up_metric")
        after = dict(server_feedback._FEEDBACK_COUNTERS)
        self.assertEqual(before, after, "未知 counter 不应被静默创建")

    def test_bump_with_custom_amount(self) -> None:
        before = server_feedback._FEEDBACK_COUNTERS["completed_total"]
        server_feedback._bump_feedback_counter("completed_total", by=5)
        after = server_feedback._FEEDBACK_COUNTERS["completed_total"]
        self.assertEqual(after - before, 5)


class TestFeedbackCountersThreadSafety(unittest.TestCase):
    """并发 ``_bump_feedback_counter`` 不应丢更新（lock 必须真的生效）。"""

    def setUp(self) -> None:
        self._saved = dict(server_feedback._FEEDBACK_COUNTERS)
        with server_feedback._FEEDBACK_COUNTERS_LOCK:
            for k in server_feedback._FEEDBACK_COUNTERS:
                server_feedback._FEEDBACK_COUNTERS[k] = 0

    def tearDown(self) -> None:
        with server_feedback._FEEDBACK_COUNTERS_LOCK:
            server_feedback._FEEDBACK_COUNTERS.clear()
            server_feedback._FEEDBACK_COUNTERS.update(self._saved)

    def test_concurrent_bump_does_not_lose_updates(self) -> None:
        import threading

        n_threads = 10
        n_iters = 200

        def hammer() -> None:
            for _ in range(n_iters):
                server_feedback._bump_feedback_counter("created_total")

        threads = [threading.Thread(target=hammer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(
            server_feedback._FEEDBACK_COUNTERS["created_total"],
            n_threads * n_iters,
            f"并发 bump 丢更新：期望 {n_threads * n_iters}，"
            f"实际 {server_feedback._FEEDBACK_COUNTERS['created_total']}",
        )


# ============================================================================
# 3. server.server_info_resource 暴露 interactive_feedback 子块
# ============================================================================


class TestServerInfoExposesFeedbackCounters(unittest.TestCase):
    """``aiia://server/info`` 必须暴露 ``interactive_feedback`` 子块。"""

    def setUp(self) -> None:
        self._saved = dict(server_feedback._FEEDBACK_COUNTERS)

    def tearDown(self) -> None:
        with server_feedback._FEEDBACK_COUNTERS_LOCK:
            server_feedback._FEEDBACK_COUNTERS.clear()
            server_feedback._FEEDBACK_COUNTERS.update(self._saved)

    def test_interactive_feedback_block_present(self) -> None:
        info = server.server_info_resource()
        self.assertIn(
            "interactive_feedback",
            info,
            "server_info_resource 应当暴露 interactive_feedback 子块",
        )
        block = info["interactive_feedback"]
        self.assertIsInstance(block, dict)

    def test_block_contains_three_lifecycle_counters(self) -> None:
        info = server.server_info_resource()
        block = cast(dict[str, Any], info["interactive_feedback"])
        for key in ("created_total", "completed_total", "failed_total"):
            self.assertIn(key, block, f"interactive_feedback 子块缺 {key!r}")
            self.assertIsInstance(block[key], int)

    def test_block_reflects_recent_bumps(self) -> None:
        before = server.server_info_resource()
        before_block = cast(dict[str, Any], before["interactive_feedback"])
        before_created = before_block["created_total"]

        server_feedback._bump_feedback_counter("created_total")
        server_feedback._bump_feedback_counter("created_total")

        after = server.server_info_resource()
        after_block = cast(dict[str, Any], after["interactive_feedback"])
        self.assertEqual(after_block["created_total"] - before_created, 2)

    def test_block_isolates_failure(self) -> None:
        """如果 ``get_feedback_counters`` 抛异常，子块应当 fallback 到 ``error`` 字段。"""
        with patch.object(
            server_feedback,
            "get_feedback_counters",
            side_effect=RuntimeError("simulated counter access failure"),
        ):
            info = server.server_info_resource()
        block = cast(dict[str, Any], info["interactive_feedback"])
        self.assertIn("error", block)
        self.assertIn("RuntimeError", str(block["error"]))


# ============================================================================
# 4. /api/system/sse-stats 接口契约（源码静态扫描 + 单元级行为验证）
#
# 不直接起 Flask app：``web_ui.WebFeedbackUI.__init__`` 会触发 mDNS / 子进程 /
# Swagger 等启动副作用，对单测来说成本高 + 不稳定。``test_bark_loopback_pwa_redirect_r42``
# 已经确立"用源码静态扫描验证路由注册"的项目惯例，我们沿用这个套路：
#
#   - 静态扫描 ``web_ui_routes/system.py`` 确认 endpoint 挂在 SystemRoutesMixin；
#   - 用 ``_SSEBus().stats_snapshot()`` 直接验证 schema（数据契约）；
#   - 端到端验证已经被本文件 1/2/3 节的单元测试覆盖（_SSEBus 计数器 +
#     server_info_resource 子块）。
# ============================================================================


class TestSSEStatsRouteRegistered(unittest.TestCase):
    """``/api/system/sse-stats`` 必须挂在 SystemRoutesMixin 上。"""

    def setUp(self) -> None:
        self.source = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
        ).read_text(encoding="utf-8")

    def test_route_path_present(self) -> None:
        self.assertIn(
            '"/api/system/sse-stats"',
            self.source,
            "sse-stats endpoint 必须挂在 SystemRoutesMixin._setup_system_routes",
        )

    def test_route_uses_get_method(self) -> None:
        # 只读诊断接口必须是 GET，让 PWA / 状态栏可以普通 fetch
        self.assertRegex(
            self.source,
            r'"/api/system/sse-stats",\s*methods=\["GET"\]',
            "sse-stats 必须是 GET（只读诊断）",
        )

    def test_route_calls_stats_snapshot(self) -> None:
        self.assertIn(
            "stats_snapshot()",
            self.source,
            "sse-stats endpoint 必须调用 _sse_bus.stats_snapshot() 而不是手写计数",
        )

    def test_route_does_not_gate_on_loopback(self) -> None:
        """sse-stats 不应包含 ``_is_loopback_request`` 调用——LAN 上的 PWA 也要能查。

        通过验证 endpoint 函数体里没有出现 loopback 判断字符串来锁定行为。
        如果未来真的要加 loopback gate，必须先开协商：这是设计约定，不是 bug。
        """
        # 找出 sse_stats 函数体的范围（到 sse_stats **紧邻**的下一个端点
        # ``/api/system/health`` 为止——R188 起 sse_stats 之后陆续插入了
        # ``log-level`` 等含 loopback gate 的端点，end_marker 不能跨越它们，
        # 否则 regex 会把不相关端点的 ``_is_loopback_request()`` 误匹配）。
        start_marker = '"/api/system/sse-stats"'
        end_marker = '"/api/system/health"'
        start = self.source.index(start_marker)
        end = self.source.index(end_marker)
        body = self.source[start:end]
        self.assertNotIn(
            "_is_loopback_request()",
            body,
            "sse-stats 不应限制为 loopback——这是只读诊断，LAN PWA 也要查",
        )


class TestSSEStatsRateLimited(unittest.TestCase):
    """``/api/system/sse-stats`` 走 ``self.limiter.limit("60 per minute")``。"""

    def test_endpoint_has_explicit_rate_limit(self) -> None:
        source = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
        ).read_text(encoding="utf-8")
        # 锁住"60 per minute"这个具体值，避免被改成 limiter.exempt
        # （exempt 会让恶意客户端无限刷接口拉取计数器流量）
        start = source.index('"/api/system/sse-stats"')
        end = source.index('"/api/system/open-config-file/info"')
        body = source[start:end]
        self.assertIn(
            '@self.limiter.limit("60 per minute")',
            body,
            "sse-stats 应当显式 rate-limit；exempt 会让计数器接口被滥用",
        )


if __name__ == "__main__":
    unittest.main()
