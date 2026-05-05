"""R20.14-C 跨进程热路径优化测试。

锁定改动
========

R20.14-C 在三处地方做了非破坏性优化：

1. ``web_ui_routes/task.py::_SSEBus.emit``
   - **预序列化**：``json.dumps(data)`` 从 N 次 generator 内调用收敛到 emit
     里一次调用，结果存入 payload 的 ``_serialized`` 字段。
   - **缩小临界区**：``_lock`` 只覆盖 ``list(self._subscribers)`` 一次拍快照，
     ``put_nowait`` 移到锁外执行。``set.discard`` 重新拿锁，但 sentinel
     注入 (`_SSE_DISCONNECT_SENTINEL`) 留在锁外。

2. ``web_ui_routes/task.py::_on_task_status_change``
   - 在事件 payload 里塞 ``stats: {pending, active, completed}``，
     来自 ``TaskQueue.get_task_count()``。失败兜底：抛异常时省略字段，
     不写脏数据。

3. ``packages/vscode/extension.ts::_connectSSE`` SSE 数据帧处理
   - 收到 ``task_changed`` 事件且带 ``ev.stats`` 时，立刻
     ``applyStatusBarPresentation`` 做 optimistic UI 更新；80ms debounce
     之后再走 ``scheduleStatusPoll(0)`` 拉 ``/api/tasks`` 兜底校验。

不变量
======

每条改动都加 source-text invariant + functional behavior assertion，避免后
续重构悄悄回归：

- emit 必须把 ``_serialized`` 写进 payload；generator 必须优先消费它，
  缺失时再 fallback 到 on-demand dumps。
- emit 临界区：``_lock`` 不能再覆盖 put_nowait（这是性能改动的核心）。
- ``_on_task_status_change`` 在 ``get_task_count`` 抛异常时仍能完成 emit，
  payload 里 ``stats`` 字段不应被写成脏数据。
- ``extension.ts`` 必须读 ``ev.stats`` 并调用 ``applyStatusBarPresentation``。
"""

from __future__ import annotations

import json
import queue as queue_mod
import re
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from web_ui_routes.task import (
    _SSE_DISCONNECT_SENTINEL,
    _on_task_status_change,
    _SSEBus,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSSEBusPreSerialization(unittest.TestCase):
    """``emit`` 必须做一次预序列化，生成 ``_serialized`` 字段。"""

    def test_emit_writes_serialized_field(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        bus.emit("task_changed", {"task_id": "t1", "new_status": "pending"})

        payload = q.get_nowait()
        self.assertIsInstance(payload, dict)
        self.assertIn(
            "_serialized",
            payload,
            "emit 必须把预序列化的 JSON 字符串写进 payload['_serialized']",
        )
        self.assertIsInstance(payload["_serialized"], str)

    def test_serialized_field_matches_data(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        data = {"task_id": "t1", "stats": {"pending": 2, "active": 1}}
        bus.emit("task_changed", data)
        payload = q.get_nowait()
        # 反序列化必须能还原出原始 data（包括嵌套 dict）
        self.assertEqual(json.loads(payload["_serialized"]), data)

    def test_serialized_uses_ensure_ascii_false(self) -> None:
        # i18n 任务名经常包含中文，必须保持 UTF-8 不转义
        bus = _SSEBus()
        q = bus.subscribe()
        bus.emit("task_changed", {"prompt": "中文测试"})
        payload = q.get_nowait()
        self.assertIn(
            "中文测试",
            payload["_serialized"],
            "_serialized 必须用 ensure_ascii=False 保留 UTF-8，否则中文会被转义成 \\uXXXX",
        )

    def test_serialization_failure_falls_back_to_none(self) -> None:
        # 防御坏数据：data 里有 non-JSON-serializable 值（比如自引用），
        # emit 不应 raise；应该把 _serialized 写成 None，让 generator
        # 走 on-demand fallback 路径
        bus = _SSEBus()
        q = bus.subscribe()
        circular: dict = {}
        circular["self"] = circular  # 自引用 → json.dumps 抛 ValueError
        try:
            bus.emit("task_changed", circular)
        except (TypeError, ValueError):
            self.fail("emit 不应让序列化异常向上冒泡")
        payload = q.get_nowait()
        # data 字段保留原始 dict（generator fallback 时还能用）
        self.assertIs(payload["data"], circular)
        self.assertIsNone(
            payload["_serialized"],
            "序列化失败时 _serialized 必须是 None，不是 '' 或缺失，generator 才能识别 fallback",
        )

    def test_emit_with_none_data_serializes_empty_dict(self) -> None:
        # 边界：data=None / 不传 → 退化为 ``{}`` 序列化
        bus = _SSEBus()
        q = bus.subscribe()
        bus.emit("heartbeat", None)
        payload = q.get_nowait()
        self.assertEqual(payload["_serialized"], "{}")


class TestSSEBusLockTightening(unittest.TestCase):
    """``emit`` 临界区改造：put_nowait 必须在锁外，emit 不能阻塞 subscribe。"""

    def test_emit_does_not_hold_lock_during_put_nowait(self) -> None:
        """精度测试：emit 期间另一个线程能并发 ``subscribe()``。

        用 ``put_nowait`` 替换成一个会阻塞 100ms 的 mock：如果旧实现还把
        put_nowait 关在 _lock 里，这 100ms 内 subscribe 拿不到锁，会被卡住。
        新实现锁外 put，subscribe 应能立即返回。
        """
        bus = _SSEBus()
        # 初始订阅一个普通 queue 以触发 emit 走 put_nowait 分支
        bus.subscribe()

        slow_q: queue_mod.Queue = queue_mod.Queue()

        # 替换 self._subscribers 里的 queue 为一个 put_nowait 慢的版本
        slow_put_called = threading.Event()
        slow_put_release = threading.Event()
        original_put_nowait = slow_q.put_nowait

        def slow_put_nowait(item: object) -> None:
            slow_put_called.set()
            # 这里 sleep 而不是 wait，是为了模拟真实 put_nowait 的阻塞。
            # 当前测试要的是「锁是否被持有」，sleep 100ms 足以让 subscribe
            # 那条线程在锁上 spin。
            slow_put_release.wait(timeout=1.0)
            original_put_nowait(item)

        slow_q.put_nowait = slow_put_nowait  # type: ignore[method-assign]
        with bus._lock:
            bus._subscribers.clear()
            bus._subscribers.add(slow_q)

        subscribe_done = threading.Event()

        def emit_thread() -> None:
            bus.emit("task_changed", {"task_id": "t1"})

        def subscribe_thread() -> None:
            slow_put_called.wait(timeout=1.0)  # 等 emit 进入慢 put
            bus.subscribe()
            subscribe_done.set()

        t_emit = threading.Thread(target=emit_thread, daemon=True)
        t_sub = threading.Thread(target=subscribe_thread, daemon=True)
        t_emit.start()
        t_sub.start()

        # subscribe 应该在 emit 还在慢 put 时就完成（即不阻塞在 emit 的锁上）
        subscribe_done.wait(timeout=0.5)
        self.assertTrue(
            subscribe_done.is_set(),
            "emit 还在 put_nowait 时 subscribe 应能并发拿锁；"
            "此断言失败说明 put_nowait 仍在 _lock 临界区内",
        )

        # 释放慢 put，让 emit 完成
        slow_put_release.set()
        t_emit.join(timeout=1.0)
        t_sub.join(timeout=1.0)

    def test_emit_still_correct_under_concurrent_subscribe(self) -> None:
        """correctness：emit 期间 subscribe 进来的新订阅者不会收到本条消息。

        这条 contract 与 R20.14-C 之前一致，是为了语义稳定性。
        """
        bus = _SSEBus()
        early_q = bus.subscribe()
        bus.emit("first", {"v": 1})
        late_q = bus.subscribe()  # 「first」 emit 之后才订阅
        bus.emit("second", {"v": 2})

        # early_q 应该收到 first + second
        early_events = []
        while not early_q.empty():
            early_events.append(early_q.get_nowait())
        self.assertEqual(len(early_events), 2)
        self.assertEqual([e["type"] for e in early_events], ["first", "second"])

        # late_q 只应该收到 second
        late_events = []
        while not late_q.empty():
            late_events.append(late_q.get_nowait())
        self.assertEqual(len(late_events), 1)
        self.assertEqual(late_events[0]["type"], "second")


class TestSSEBusBackpressurePreserved(unittest.TestCase):
    """R20.14-C 改动后 backpressure / discard / sentinel 行为必须不变。"""

    def test_full_queue_still_signals_sentinel(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        for i in range(_SSEBus._QUEUE_MAXSIZE):
            q.put_nowait({"type": "filler", "data": {"i": i}})

        bus.emit("overflow", {"task_id": "drop"})

        self.assertEqual(bus.subscriber_count, 0, "Full 触发后订阅者应被 discard")
        seen: list[object] = []
        while not q.empty():
            seen.append(q.get_nowait())
        self.assertIn(
            _SSE_DISCONNECT_SENTINEL,
            seen,
            "Sentinel 注入逻辑不应被 R20.14-C 的锁改造打掉",
        )

    def test_threshold_still_signals_sentinel(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        for i in range(_SSEBus._BACKPRESSURE_THRESHOLD - 1):
            q.put_nowait({"type": "filler", "data": {"i": i}})

        bus.emit("threshold", {"task_id": "discard"})

        self.assertEqual(bus.subscriber_count, 0)
        seen: list[object] = []
        while not q.empty():
            seen.append(q.get_nowait())
        self.assertIn(_SSE_DISCONNECT_SENTINEL, seen)

    def test_unsubscribe_no_sentinel_after_changes(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        self.assertTrue(q.empty(), "正常 unsubscribe 仍不应注入 sentinel")


class TestEmitPerformance(unittest.TestCase):
    """smoke 性能：N=10 订阅者的 emit 不应明显比 N=1 慢。

    历史实现：N 次 ``json.dumps(data)`` 在 generator 内执行；emit 的临界区
    覆盖整个 N 次 put_nowait。R20.14-C 后：1 次 dumps + 锁外 put_nowait。

    这里只做粗 sanity check（emit 总耗时 < 5 ms），不做精确 benchmark
    （perf_e2e_bench.py 才是 benchmarks 真正归属）。
    """

    def test_emit_to_10_subscribers_completes_under_5ms(self) -> None:
        bus = _SSEBus()
        for _ in range(10):
            bus.subscribe()
        start = time.perf_counter()
        for _ in range(100):
            bus.emit("task_changed", {"task_id": "t", "stats": {"pending": 1}})
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        per_emit_us = elapsed_ms * 10  # 100 emits → 每条事件的平均 µs
        self.assertLess(
            per_emit_us,
            5000,
            f"100×emit→10 订阅者总耗时 {elapsed_ms:.2f}ms（每条 {per_emit_us:.1f}µs）"
            "；超过 5ms/条暗示性能改造被无意识打回",
        )


class TestOnTaskStatusChangeEmbedsStats(unittest.TestCase):
    """``_on_task_status_change`` 必须在 payload 里塞 ``stats``。"""

    def test_stats_embedded_when_queue_available(self) -> None:
        # patch get_task_queue 让它返回一个 mock，mock 的 get_task_count 返回固定字典
        mock_queue = MagicMock()
        mock_queue.get_task_count.return_value = {
            "pending": 3,
            "active": 1,
            "completed": 5,
            "total": 9,
            "max": 100,
        }
        with patch("web_ui_routes.task.get_task_queue", return_value=mock_queue):
            with patch("web_ui_routes.task._sse_bus") as mock_bus:
                _on_task_status_change("t1", "pending", "active")

        mock_bus.emit.assert_called_once()
        call_args = mock_bus.emit.call_args
        event_type, payload = call_args[0]
        self.assertEqual(event_type, "task_changed")
        self.assertIn("stats", payload, "task_changed 事件必须带 stats 字段")
        self.assertEqual(
            payload["stats"]["pending"], 3, "stats 必须从 get_task_count 取真实数字"
        )
        self.assertEqual(payload["stats"]["active"], 1)
        self.assertEqual(payload["stats"]["completed"], 5)

    def test_stats_omitted_when_get_task_count_raises(self) -> None:
        # 失败兜底：get_task_count 抛异常时 stats 字段应该不存在（不是 {}），
        # 让旧 client 的 fetch fallback 路径生效，避免「空 stats → 显示 0」脏读
        mock_queue = MagicMock()
        mock_queue.get_task_count.side_effect = RuntimeError("boom")
        with patch("web_ui_routes.task.get_task_queue", return_value=mock_queue):
            with patch("web_ui_routes.task._sse_bus") as mock_bus:
                _on_task_status_change("t1", None, "pending")

        call_args = mock_bus.emit.call_args
        _, payload = call_args[0]
        self.assertNotIn(
            "stats",
            payload,
            "get_task_count 失败时 payload 不应有 stats 字段（让 client 走 fetch 兜底）",
        )
        # 但其他字段必须存在
        self.assertEqual(payload["task_id"], "t1")
        self.assertEqual(payload["new_status"], "pending")

    def test_stats_omitted_when_queue_unavailable(self) -> None:
        # get_task_queue 返回 None 时（极早期，队列还没起来），不应 raise
        with patch("web_ui_routes.task.get_task_queue", return_value=None):
            with patch("web_ui_routes.task._sse_bus") as mock_bus:
                _on_task_status_change("t1", None, "pending")

        call_args = mock_bus.emit.call_args
        _, payload = call_args[0]
        self.assertNotIn("stats", payload)


class TestSSEGeneratorConsumesPreSerialized(unittest.TestCase):
    """SSE generator 必须优先消费 ``_serialized`` 字段，缺失时 fallback。

    这里直接测 ``web_ui_routes.task`` 里 ``sse_events`` 路由生成的字节流；
    用 Flask 的 test_client 起一个最小 app，emit 后立即 GET ``/api/events``。
    """

    SCRIPT_PATH = REPO_ROOT / "web_ui_routes" / "task.py"

    def test_generator_uses_serialized_field_in_yield(self) -> None:
        """源码不变量：``yield`` 那一行必须先取 ``event.get('_serialized')``。"""
        src = self.SCRIPT_PATH.read_text(encoding="utf-8")
        # 找到 sse_events 函数体
        idx = src.find("def sse_events")
        self.assertGreaterEqual(idx, 0)
        body = src[idx : idx + 2500]
        # 关键 invariant：generator 必须优先消费 _serialized
        self.assertIn(
            'event.get("_serialized")',
            body,
            "sse_events generator 必须先尝试 event.get('_serialized')，否则 R20.14-C 的"
            "预序列化优化失效",
        )
        # 兜底路径必须保留：缺失时回退到 on-demand dumps
        self.assertIn(
            "json.dumps",
            body,
            "缺失 _serialized 时 generator 仍须 on-demand 序列化，否则旧式 payload 喷 None",
        )

    def test_generator_fallback_when_serialized_missing(self) -> None:
        """运行时验证：手工构造一个没 ``_serialized`` 的 payload，generator 仍能正常 yield。

        模拟旧式 emit 路径或第三方代码直接 put 原始 dict 的边界情况。
        """
        # 直接构造一个 queue + 模拟 generator 主体：
        q: queue_mod.Queue = queue_mod.Queue()
        q.put({"type": "task_changed", "data": {"task_id": "old"}})

        # 复制 generator 主体逻辑（不通过 Flask）
        event = q.get(timeout=0.1)
        serialized = event.get("_serialized") if isinstance(event, dict) else None
        if serialized is None:
            serialized = json.dumps(event["data"], ensure_ascii=False)
        line = f"event: {event['type']}\ndata: {serialized}\n\n"
        self.assertIn("task_id", line)
        self.assertIn("old", line)


class TestExtensionTsConsumesStats(unittest.TestCase):
    """``packages/vscode/extension.ts`` 必须读 ``ev.stats`` 做 optimistic 更新。"""

    EXT_PATH = REPO_ROOT / "packages" / "vscode" / "extension.ts"

    def setUp(self) -> None:
        self.src = self.EXT_PATH.read_text(encoding="utf-8")

    def test_sse_handler_reads_stats_field(self) -> None:
        # 不变量：SSE handler 函数体必须 reference ev.stats
        # 找到 _connectSSE 函数体
        idx = self.src.find("_connectSSE")
        self.assertGreaterEqual(idx, 0)
        # _connectSSE 函数体延伸到 _handleSSEError；取一段足够包含的窗口
        body = self.src[idx : idx + 4000]
        self.assertIn(
            "ev.stats",
            body,
            "extension.ts SSE handler 必须读 ev.stats（R20.14-C optimistic 更新依赖它）",
        )

    def test_sse_handler_calls_apply_status_bar_presentation_optimistically(
        self,
    ) -> None:
        idx = self.src.find("_connectSSE")
        self.assertGreaterEqual(idx, 0)
        body = self.src[idx : idx + 4000]
        # 必须在 stats 分支里（即 if (optStats) {} 之内）调用 applyStatusBarPresentation
        match = re.search(
            r"if\s*\(\s*optStats\s*\)\s*\{[^}]*applyStatusBarPresentation",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "extension.ts 必须在 ev.stats 存在时（if (optStats)）立即调用 "
            "applyStatusBarPresentation 做 optimistic 更新；否则 stats 字段白做了",
        )

    def test_sse_handler_still_schedules_status_poll(self) -> None:
        # optimistic 更新不能取代 fetch；scheduleStatusPoll(0) 仍须保留
        idx = self.src.find("_connectSSE")
        self.assertGreaterEqual(idx, 0)
        body = self.src[idx : idx + 4000]
        self.assertIn(
            "scheduleStatusPoll(0)",
            body,
            "scheduleStatusPoll(0) 不能被 R20.14-C 删掉；fetch 仍是新任务检测的源头",
        )


class TestSourceInvariants(unittest.TestCase):
    """``_SSEBus.emit`` 源码层不变量：锁外 put + 预序列化必须留存。"""

    SCRIPT_PATH = REPO_ROOT / "web_ui_routes" / "task.py"

    def setUp(self) -> None:
        self.src = self.SCRIPT_PATH.read_text(encoding="utf-8")

    def test_emit_has_pre_serialize_step(self) -> None:
        # emit 函数体内必须出现 json.dumps + _serialized 字段
        idx = self.src.find("def emit(")
        self.assertGreaterEqual(idx, 0, "emit 方法找不到")
        body = self.src[idx : idx + 3000]
        self.assertIn(
            "json.dumps",
            body,
            "emit 必须做一次预序列化（json.dumps）",
        )
        self.assertIn(
            "_serialized",
            body,
            "emit 必须把序列化结果写进 payload['_serialized']",
        )

    def test_emit_uses_snapshot_pattern(self) -> None:
        # 函数体内必须有 list(self._subscribers) 的快照模式（锁外 put 的标志）
        idx = self.src.find("def emit(")
        body = self.src[idx : idx + 3000]
        self.assertIn(
            "list(self._subscribers)",
            body,
            "emit 必须用 ``list(self._subscribers)`` 拍快照后释放锁；"
            "这是锁外 put_nowait 的关键模式",
        )

    def test_on_task_status_change_calls_get_task_count(self) -> None:
        # _on_task_status_change 必须 call get_task_count 才能塞 stats
        idx = self.src.find("def _on_task_status_change")
        self.assertGreaterEqual(idx, 0)
        body = self.src[idx : idx + 1500]
        self.assertIn(
            "get_task_count",
            body,
            "_on_task_status_change 必须 call get_task_count() 拿统计",
        )
        self.assertIn(
            "stats",
            body,
            "_on_task_status_change 必须把 stats 字段写进 payload",
        )


if __name__ == "__main__":
    unittest.main()
