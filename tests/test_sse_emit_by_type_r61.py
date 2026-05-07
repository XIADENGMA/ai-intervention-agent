"""R61 — _SSEBus per-event-type emit histogram.

设计：

* 在已有 ``_emit_total`` 单一计数器之上，按 ``event_type`` 分桶累加，让
  dashboard / observability 体面看清楚 SSE 流量中哪种事件最频繁；
* ``emit_by_type`` 暴露在 ``stats_snapshot`` 返回值里，作为 ``dict``，调用
  方拿到的是浅拷贝，外部修改不影响内部 ``Counter``；
* ``oversize_drop`` 替换路径自然走 ``"oversize_drop"`` 键，不污染原 type 桶
  ——但替换事件的 ``data["original_event_type"]`` 仍保留原 type，方便追溯。

覆盖目标：

* 初始 ``Counter`` 为空；
* emit 后对应桶 +1；
* 不同 event_type 各自累加，互不影响；
* ``stats_snapshot`` 返回浅拷贝，外部修改不污染 bus 的内部 Counter；
* 与 ``oversize_drop`` 替换路径互不冲突；
* server.py cache 路径透传 ``emit_by_type``。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import server
from web_ui_routes.task import _SSEBus


class TestEmitByTypeBasics(unittest.TestCase):
    def test_initial_emit_by_type_is_empty(self) -> None:
        bus = _SSEBus()
        snap = bus.stats_snapshot()
        self.assertIn("emit_by_type", snap)
        self.assertEqual(snap["emit_by_type"], {})

    def test_single_emit_increments_bucket(self) -> None:
        bus = _SSEBus()
        bus.emit("task_changed", {"task_id": "t1"})
        snap = bus.stats_snapshot()
        self.assertEqual(snap["emit_by_type"]["task_changed"], 1)

    def test_multiple_emits_same_type_accumulate(self) -> None:
        bus = _SSEBus()
        for i in range(5):
            bus.emit("task_changed", {"task_id": f"t{i}"})
        snap = bus.stats_snapshot()
        self.assertEqual(snap["emit_by_type"]["task_changed"], 5)

    def test_different_types_track_independently(self) -> None:
        bus = _SSEBus()
        bus.emit("task_changed", {})
        bus.emit("task_changed", {})
        bus.emit("config_changed", {})
        bus.emit("oversize_drop", {})
        snap = bus.stats_snapshot()
        self.assertEqual(snap["emit_by_type"]["task_changed"], 2)
        self.assertEqual(snap["emit_by_type"]["config_changed"], 1)
        self.assertEqual(snap["emit_by_type"]["oversize_drop"], 1)

    def test_emit_total_matches_sum_of_buckets(self) -> None:
        bus = _SSEBus()
        bus.emit("task_changed", {})
        bus.emit("task_changed", {})
        bus.emit("config_changed", {})
        snap = bus.stats_snapshot()
        self.assertEqual(snap["emit_total"], sum(snap["emit_by_type"].values()))


class TestSnapshotShallowCopyIsolation(unittest.TestCase):
    def test_external_mutation_does_not_affect_bus(self) -> None:
        bus = _SSEBus()
        bus.emit("task_changed", {})
        snap = bus.stats_snapshot()
        snap["emit_by_type"]["task_changed"] = 999
        # 内部 Counter 不应被外部修改污染
        snap2 = bus.stats_snapshot()
        self.assertEqual(snap2["emit_by_type"]["task_changed"], 1)


class TestOversizeDropPathConsistency(unittest.TestCase):
    """oversize 替换后，桶记账走的是替换后的 type（``oversize_drop``），不污染原 type。"""

    def test_oversize_replacement_counts_under_oversize_drop(self) -> None:
        bus = _SSEBus()
        big_msg = "x" * (300 * 1024)
        bus.emit("task_changed", {"b": big_msg})
        snap = bus.stats_snapshot()
        self.assertEqual(snap["emit_by_type"].get("oversize_drop", 0), 1)
        # 原 task_changed 桶不被错误地 +1
        self.assertEqual(snap["emit_by_type"].get("task_changed", 0), 0)


class TestServerInfoCacheTransparentlyForwardsEmitByType(unittest.TestCase):
    """server.py 的 sse-stats 跨进程 cache 必须透传 emit_by_type 字段。"""

    def setUp(self) -> None:
        with server._sse_stats_cache_lock:
            server._sse_stats_cache.clear()
            server._sse_stats_cache_ts = 0.0

    def test_cache_includes_emit_by_type_when_present(self) -> None:
        fake_resp = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "success": True,
                    "emit_total": 7,
                    "latest_event_id": 7,
                    "gap_warnings_emitted": 0,
                    "backpressure_discards": 0,
                    "subscriber_count": 0,
                    "history_size": 7,
                    "heartbeat_total": 1,
                    "oversize_drops": 0,
                    "emit_by_type": {"task_changed": 5, "config_changed": 2},
                }
            ),
        )
        with patch("httpx.get", return_value=fake_resp):
            r = server._fetch_sse_stats_cached("127.0.0.1", 41111)
        self.assertIn("emit_by_type", r)
        self.assertEqual(r["emit_by_type"], {"task_changed": 5, "config_changed": 2})

    def test_cache_omits_emit_by_type_when_endpoint_returns_none(self) -> None:
        """端点未来如果有理由不发该字段（比如降级），cache 不应硬编码空 dict。"""
        fake_resp = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "success": True,
                    "emit_total": 1,
                    # 故意缺 emit_by_type
                }
            ),
        )
        with patch("httpx.get", return_value=fake_resp):
            r = server._fetch_sse_stats_cached("127.0.0.1", 41111)
        self.assertNotIn("emit_by_type", r)
        self.assertEqual(r["emit_total"], 1)


if __name__ == "__main__":
    unittest.main()
