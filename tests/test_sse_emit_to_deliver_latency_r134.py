"""R134 — SSE bus emit→deliver 延迟分布（P50 / P95）回归契约。

R47 的 ``_emit_total`` / ``_gap_warnings_emitted`` / ``_backpressure_discards`` /
``_heartbeat_total`` 给运维 dashboard 提供"事件量"维度，但缺一个最关键的
**延迟分布** 维度——「emit 到客户端真正收到」之间的延迟，是在线服务质量
（QoS）的核心指标。R134 用 ``deque(maxlen=512)`` 环形缓冲在 ``_SSEBus``
内累积近 512 个样本，``stats_snapshot()`` 算 P50 / P95（ms float, 2 位小
数）+ count 暴露给 ``/api/system/sse-stats`` 端点。

设计契约（覆盖以下 5 个 invariant class）：

1. **常量与 init** —
   - ``_LATENCY_SAMPLES_MAXLEN`` = 512；deque 初始 empty；类型 ``deque[int]``。

2. **采样 API** —
   - ``record_emit_to_deliver_latency_ns(ns: int)`` 持锁 append；
   - 负数静默丢弃（防御 ``monotonic_ns`` mock / 极端 race）；
   - deque 自动 evict（超 512 时最旧出队）。

3. **percentile 计算** —
   - ``count == 0`` → p50_ms / p95_ms 都是 None；
   - ``count == 1`` → 唯一样本同时是 p50 = p95；
   - 已知 100 样本 [1ms..100ms] → P50 = ms(samples[50]) = 51.0，
     P95 = ms(samples[95]) = 96.0（nearest-rank）；
   - **单调**：``record(small) -> snap_a``，``record(big) -> snap_b``
     则 ``snap_b['p95_ms'] >= snap_a['p95_ms']``。

4. **emit 路径注入与 generator 消费** —
   - ``emit()`` 把 ``time.monotonic_ns()`` 写进 payload ``"_emit_ts_ns"``
     字段；history snapshot 里的 payload 也含该字段（这是 emit 路径同
     步写入的事实）；
   - generator 在 yield 前调 ``record_emit_to_deliver_latency_ns(ns)``，
     ``_emit_ts_ns`` 缺失时静默跳过；
   - source 内出现 ``record_emit_to_deliver_latency_ns(`` 调用至少 1 次
     在 ``def generate(`` 函数体里。

5. **stats_snapshot 与 TypedDict 契约** —
   - 返回值含 ``"latency_ms"`` 键；其值是 dict 含 ``p50_ms`` / ``p95_ms`` /
     ``count``；
   - ``SSELatencySnapshot`` TypedDict 在 module 顶部定义，含 3 个字段；
   - ``SSEBusStatsSnapshot`` TypedDict 已含 ``latency_ms`` 字段（保护
     R47 / R51-B / R58 / R61 既有字段不被新加项打破——R47 那张表的契约
     测试不应当因 R134 加字段就 fail，所以本测试把"扩张"当合法的；R47
     测试本身仅断言「关键字段在场 + 类型正确」，不锁全字段）。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes.task import (
    SSEBusStatsSnapshot,
    SSELatencySnapshot,
    _SSEBus,
)

# ----------------------------------------------------------------------------
# 1. 常量与 init
# ----------------------------------------------------------------------------


class TestConstantAndInit(unittest.TestCase):
    def test_latency_maxlen_constant_is_512(self) -> None:
        self.assertEqual(_SSEBus._LATENCY_SAMPLES_MAXLEN, 512)

    def test_latency_samples_initial_empty(self) -> None:
        bus = _SSEBus()
        self.assertEqual(len(bus._latency_samples_ns), 0)

    def test_latency_samples_is_bounded_deque(self) -> None:
        bus = _SSEBus()
        # deque(maxlen=...) 的 maxlen 属性必须 = 512，保证环形 evict 生效
        self.assertEqual(bus._latency_samples_ns.maxlen, 512)


# ----------------------------------------------------------------------------
# 2. 采样 API
# ----------------------------------------------------------------------------


class TestRecordLatencyApi(unittest.TestCase):
    def test_record_appends_sample(self) -> None:
        bus = _SSEBus()
        bus.record_emit_to_deliver_latency_ns(1_000_000)  # 1ms
        self.assertEqual(len(bus._latency_samples_ns), 1)
        self.assertEqual(bus._latency_samples_ns[0], 1_000_000)

    def test_record_negative_silently_ignored(self) -> None:
        bus = _SSEBus()
        bus.record_emit_to_deliver_latency_ns(-1)
        bus.record_emit_to_deliver_latency_ns(-1_000_000)
        self.assertEqual(len(bus._latency_samples_ns), 0)

    def test_record_zero_is_accepted(self) -> None:
        # 0ns 是合法值（虽然实战中几乎不可能出现，但 monotonic_ns 同一刻
        # 拿两次的差值理论上可以是 0 - 不应被丢弃）
        bus = _SSEBus()
        bus.record_emit_to_deliver_latency_ns(0)
        self.assertEqual(len(bus._latency_samples_ns), 1)

    def test_record_evicts_when_full(self) -> None:
        bus = _SSEBus()
        for i in range(_SSEBus._LATENCY_SAMPLES_MAXLEN + 50):
            bus.record_emit_to_deliver_latency_ns(i + 1)
        # 不超 maxlen
        self.assertEqual(len(bus._latency_samples_ns), _SSEBus._LATENCY_SAMPLES_MAXLEN)
        # 最旧 50 个被 evict 掉，第一个剩下来的应该是 51
        self.assertEqual(bus._latency_samples_ns[0], 51)
        self.assertEqual(
            bus._latency_samples_ns[-1], _SSEBus._LATENCY_SAMPLES_MAXLEN + 50
        )


# ----------------------------------------------------------------------------
# 3. percentile 计算
# ----------------------------------------------------------------------------


class TestPercentileCompute(unittest.TestCase):
    def test_empty_returns_none_p50_p95_count_zero(self) -> None:
        bus = _SSEBus()
        snap = bus._compute_latency_snapshot()
        self.assertEqual(snap["count"], 0)
        self.assertIsNone(snap["p50_ms"])
        self.assertIsNone(snap["p95_ms"])

    def test_single_sample_p50_equals_p95(self) -> None:
        bus = _SSEBus()
        bus.record_emit_to_deliver_latency_ns(5_000_000)  # 5ms
        snap = bus._compute_latency_snapshot()
        self.assertEqual(snap["count"], 1)
        self.assertEqual(snap["p50_ms"], 5.0)
        self.assertEqual(snap["p95_ms"], 5.0)

    def test_known_distribution_1_to_100_ms(self) -> None:
        # 构造 100 个样本：1ms, 2ms, ..., 100ms（已排序）
        # nearest-rank: P50 idx = int(100 * 0.50) = 50 → 51ms
        # P95 idx = int(100 * 0.95) = 95 → 96ms
        bus = _SSEBus()
        for ms in range(1, 101):
            bus.record_emit_to_deliver_latency_ns(ms * 1_000_000)
        snap = bus._compute_latency_snapshot()
        self.assertEqual(snap["count"], 100)
        self.assertEqual(snap["p50_ms"], 51.0)
        self.assertEqual(snap["p95_ms"], 96.0)

    def test_p95_monotonic_when_appending_larger_sample(self) -> None:
        # 加完小样本后再加一个超大样本，P95 不能下降
        bus = _SSEBus()
        for ms in range(1, 21):  # 1..20ms
            bus.record_emit_to_deliver_latency_ns(ms * 1_000_000)
        snap_before = bus._compute_latency_snapshot()
        bus.record_emit_to_deliver_latency_ns(500_000_000)  # 500ms 大尾
        snap_after = bus._compute_latency_snapshot()
        p95_before = snap_before["p95_ms"]
        p95_after = snap_after["p95_ms"]
        assert p95_before is not None and p95_after is not None
        self.assertGreaterEqual(p95_after, p95_before)

    def test_p50_p95_are_rounded_to_two_decimals(self) -> None:
        # 5.123 ms 的样本应该 round 到 5.12
        bus = _SSEBus()
        bus.record_emit_to_deliver_latency_ns(5_123_456)  # 5.123456ms
        snap = bus._compute_latency_snapshot()
        self.assertEqual(snap["p50_ms"], 5.12)
        self.assertEqual(snap["p95_ms"], 5.12)


# ----------------------------------------------------------------------------
# 4. emit 注入 + generator 消费
# ----------------------------------------------------------------------------


class TestEmitPayloadInjection(unittest.TestCase):
    def test_emit_writes_emit_ts_ns_into_history_payload(self) -> None:
        # ``emit()`` 在锁内把 ``time.monotonic_ns()`` 写进 payload；
        # ``history_snapshot()`` 是 history 的副本，能直接读
        bus = _SSEBus()
        bus.emit("task_changed", {"task_id": "t-r134"})
        history = bus.history_snapshot()
        self.assertEqual(len(history), 1)
        _evt_id, payload = history[0]
        self.assertIn("_emit_ts_ns", payload)
        self.assertIsInstance(payload["_emit_ts_ns"], int)
        self.assertGreater(payload["_emit_ts_ns"], 0)

    def test_generator_calls_record_latency_in_source(self) -> None:
        # 源码层断言：generator 内部出现 ``record_emit_to_deliver_latency_ns(``
        # 调用，验证我们没有忘记接进去。这是「单元测试不依赖 Flask app
        # 启动」的成本——精确的 generator 行为还是要 e2e 测，这里至少
        # 锁定 source 不被回滚。
        src = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
        ).read_text(encoding="utf-8")
        # generator 函数定义出现在 sse_events handler 内部
        self.assertIn("def generate(", src)
        # 调用点出现
        self.assertIn("record_emit_to_deliver_latency_ns(", src)
        # 进一步：generate 函数体内（从 ``def generate(`` 起到下一个 ``return Response``
        # 之间的范围）必须含 record 调用
        gen_match = re.search(r"def generate\(\):.*?return Response\(", src, re.DOTALL)
        self.assertIsNotNone(gen_match)
        gen_body = gen_match.group(0) if gen_match else ""
        self.assertIn("record_emit_to_deliver_latency_ns(", gen_body)


# ----------------------------------------------------------------------------
# 5. stats_snapshot + TypedDict 契约
# ----------------------------------------------------------------------------


class TestStatsSnapshotShape(unittest.TestCase):
    def test_snapshot_contains_latency_ms_key(self) -> None:
        bus = _SSEBus()
        snap = bus.stats_snapshot()
        self.assertIn("latency_ms", snap)

    def test_snapshot_latency_ms_has_three_fields(self) -> None:
        bus = _SSEBus()
        snap = bus.stats_snapshot()
        latency = cast(dict[str, Any], snap["latency_ms"])
        self.assertIn("p50_ms", latency)
        self.assertIn("p95_ms", latency)
        self.assertIn("count", latency)
        self.assertEqual(latency["count"], 0)

    def test_existing_r47_keys_still_present(self) -> None:
        # R134 加 latency_ms 不应当打破 R47 / R51-B / R58 / R61 既有字段
        bus = _SSEBus()
        snap = bus.stats_snapshot()
        for key in (
            "emit_total",
            "latest_event_id",
            "gap_warnings_emitted",
            "backpressure_discards",
            "subscriber_count",
            "history_size",
            "heartbeat_total",
            "oversize_drops",
            "emit_by_type",
        ):
            self.assertIn(key, snap)

    def test_typed_dict_sse_latency_snapshot_has_three_keys(self) -> None:
        # 防御未来误删字段：TypedDict 注解必须保 3 个键
        annotations = SSELatencySnapshot.__annotations__
        self.assertIn("p50_ms", annotations)
        self.assertIn("p95_ms", annotations)
        self.assertIn("count", annotations)

    def test_typed_dict_sse_bus_stats_snapshot_has_latency_ms(self) -> None:
        annotations = SSEBusStatsSnapshot.__annotations__
        self.assertIn("latency_ms", annotations)


# ----------------------------------------------------------------------------
# 6. /api/system/sse-stats Swagger 字段引用
# ----------------------------------------------------------------------------


class TestSseStatsEndpointDoc(unittest.TestCase):
    def test_endpoint_swagger_doc_mentions_latency_ms(self) -> None:
        # ``/api/system/sse-stats`` 的 Swagger 文档应当至少把 latency_ms 字段
        # 描述加上，让 /apidocs 用户能看到。这是 caller-facing 契约。
        src = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
        ).read_text(encoding="utf-8")
        # 至少有 R134 标记 + latency_ms 字段名
        self.assertIn("R134", src)
        self.assertIn("latency_ms:", src)
        self.assertIn("p50_ms:", src)
        self.assertIn("p95_ms:", src)


if __name__ == "__main__":
    unittest.main()
