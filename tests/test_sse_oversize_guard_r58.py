"""R58 — _SSEBus.emit 超大 payload 主动丢弃。

设计：

* 阈值 ``_OVERSIZE_LIMIT_BYTES = 256 KB``。超过的 emit 不发原 payload，
  改发一条 ``oversize_drop`` 元事件（含原 event_type、size_bytes、limit_bytes）；
* 每次触发计数器 ``_oversize_drops += 1``，并暴露在 ``stats_snapshot()`` /
  ``/api/system/sse-stats`` / ``aiia://server/info -> sse_bus`` 三层。

覆盖目标：

* 阈值边界：略小于阈值的 payload 正常发；超过阈值的被替换；
* 原 event_type 被保留在 ``data["original_event_type"]``，便于 dashboard 排查；
* 计数器 ``_oversize_drops`` 单调累加；
* ``stats_snapshot()`` 暴露 ``oversize_drops`` 字段；
* server.py cache 路径透传该字段；
* fan-out 行为：oversize event 仍然 fan-out 给所有订阅者（所以客户端能感知"我错过了一条大事件"），但 fan-out 的内容是替换后的元事件，不是原 payload；
* 序列化失败的 payload 不会被错误地当成 oversize（因为没字节数可量）。
"""

from __future__ import annotations

import json
import unittest

from web_ui_routes.task import _SSE_DISCONNECT_SENTINEL, _SSEBus


class TestOversizeThreshold(unittest.TestCase):
    """阈值边界 + 替换语义。"""

    def setUp(self) -> None:
        self.bus = _SSEBus()

    def test_below_threshold_emits_normally(self) -> None:
        """略小于阈值的 payload 应该正常发。"""
        # 序列化后大约 1 KB，远小于 256 KB。
        data = {"task_id": "t1", "msg": "x" * 500}
        q = self.bus.subscribe()
        self.bus.emit("task_changed", data)
        evt = q.get_nowait()
        self.assertEqual(evt["type"], "task_changed")
        self.assertEqual(evt["data"]["task_id"], "t1")
        self.assertEqual(self.bus._oversize_drops, 0)

    def test_above_threshold_replaced_with_oversize_drop(self) -> None:
        """大于阈值的 payload 应被替换成 oversize_drop 元事件。"""
        # 256 KB + buffer：用一个明显超阈值的 payload。
        big_msg = "x" * (300 * 1024)
        q = self.bus.subscribe()
        self.bus.emit("task_changed", {"big": big_msg})

        evt = q.get_nowait()
        self.assertEqual(evt["type"], "oversize_drop")
        self.assertEqual(evt["data"]["original_event_type"], "task_changed")
        self.assertGreater(evt["data"]["size_bytes"], _SSEBus._OVERSIZE_LIMIT_BYTES)
        self.assertEqual(evt["data"]["limit_bytes"], _SSEBus._OVERSIZE_LIMIT_BYTES)
        # 原 big_msg 不应再出现在 payload 里 —— 这是节流的关键。
        self.assertNotIn("big", evt["data"])
        self.assertEqual(self.bus._oversize_drops, 1)

    def test_oversize_drop_counter_accumulates(self) -> None:
        """连续多次 oversize emit，counter 单调累加。"""
        big_msg = "x" * (300 * 1024)
        for _ in range(3):
            self.bus.emit("task_changed", {"b": big_msg})
        self.assertEqual(self.bus._oversize_drops, 3)

    def test_oversize_drop_does_not_increment_counter_for_normal_emit(self) -> None:
        self.bus.emit("task_changed", {"task_id": "t1"})
        self.bus.emit("task_changed", {"task_id": "t2"})
        self.assertEqual(self.bus._oversize_drops, 0)


class TestStatsSnapshotIncludesOversize(unittest.TestCase):
    """``stats_snapshot()`` 必须暴露 ``oversize_drops`` 字段。"""

    def test_snapshot_has_oversize_key_with_zero_default(self) -> None:
        bus = _SSEBus()
        snap = bus.stats_snapshot()
        self.assertIn("oversize_drops", snap)
        self.assertEqual(snap["oversize_drops"], 0)
        self.assertIsInstance(snap["oversize_drops"], int)

    def test_snapshot_reflects_counter_after_drops(self) -> None:
        bus = _SSEBus()
        big_msg = "x" * (300 * 1024)
        bus.emit("task_changed", {"b": big_msg})
        snap = bus.stats_snapshot()
        self.assertEqual(snap["oversize_drops"], 1)


class TestOversizeFanOut(unittest.TestCase):
    """oversize event 替换后仍 fan-out 给所有订阅者。

    这个 contract 很关键：客户端**应该**看到"有一条大事件被丢了"，
    而不是 silently lose the emit slot 让 ``Last-Event-ID`` resume 时
    以为没事发生。
    """

    def test_oversize_drop_reaches_all_subscribers(self) -> None:
        bus = _SSEBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        big_msg = "x" * (300 * 1024)
        bus.emit("task_changed", {"b": big_msg})

        e1 = q1.get_nowait()
        e2 = q2.get_nowait()
        for evt in (e1, e2):
            self.assertEqual(evt["type"], "oversize_drop")
            self.assertEqual(evt["data"]["original_event_type"], "task_changed")

    def test_oversize_drop_increments_emit_total_and_id(self) -> None:
        """oversize 仍然消耗一个 event id 和 emit_total 计数 ——
        这样 client side ``last_event_id`` 不会因为 server 静默 drop 而错位。"""
        bus = _SSEBus()
        before = bus.stats_snapshot()
        big_msg = "x" * (300 * 1024)
        bus.emit("task_changed", {"b": big_msg})
        after = bus.stats_snapshot()
        self.assertEqual(after["emit_total"] - before["emit_total"], 1)
        self.assertEqual(after["latest_event_id"] - before["latest_event_id"], 1)


class TestSerializationFailureDoesNotMisclassify(unittest.TestCase):
    """如果原 payload 序列化失败（``serialized_data is None``），不应被
    当作 oversize_drop 处理。"""

    def test_unserializable_payload_falls_back_normally(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        # set 不能 json.dumps，触发 serialized_data=None 分支
        bus.emit("task_changed", {"weird": {1, 2, 3}})  # type: ignore[arg-type]
        evt = q.get_nowait()
        # 不应被替换为 oversize_drop
        self.assertNotEqual(evt["type"], "oversize_drop")
        self.assertEqual(bus._oversize_drops, 0)


class TestOversizeLimitBoundsAreReasonable(unittest.TestCase):
    def test_limit_is_at_least_64kb(self) -> None:
        self.assertGreaterEqual(_SSEBus._OVERSIZE_LIMIT_BYTES, 64 * 1024)

    def test_limit_is_at_most_2mb(self) -> None:
        # 不允许过宽：> 2 MB 已经远超合法 SSE 用例。
        self.assertLessEqual(_SSEBus._OVERSIZE_LIMIT_BYTES, 2 * 1024 * 1024)


class TestOversizeFanOutSerializedFieldIntegrity(unittest.TestCase):
    """fan-out 的 oversize_drop 自身也需要有合法 ``_serialized`` 字段
    （让 generator 不再回到 on-demand dumps 的兜底路径）。"""

    def test_serialized_field_present_and_valid(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()
        big_msg = "x" * (300 * 1024)
        bus.emit("task_changed", {"b": big_msg})
        evt = q.get_nowait()
        ser = evt.get("_serialized")
        self.assertIsInstance(ser, str)
        # 反序列化能拿回原 metadata
        decoded = json.loads(ser)
        self.assertEqual(decoded["original_event_type"], "task_changed")
        self.assertGreater(decoded["size_bytes"], _SSEBus._OVERSIZE_LIMIT_BYTES)


class TestNonOversizeEmitsKeepNormalShape(unittest.TestCase):
    """常规事件结构不应被 R58 触碰。"""

    def test_subscriber_sentinel_path_unaffected(self) -> None:
        """backpressure 路径仍然走 sentinel，不和 oversize 干扰。"""
        bus = _SSEBus()
        q = bus.subscribe()
        # 把 queue 灌满让下次 emit 走 backpressure 路径
        for i in range(_SSEBus._QUEUE_MAXSIZE):
            q.put_nowait({"type": "filler", "data": {"i": i}})
        bus.emit("task_changed", {"task_id": "t1"})
        # 走 backpressure：sentinel 应当被塞进 q
        seen: list[object] = []
        while not q.empty():
            seen.append(q.get_nowait())
        self.assertIn(_SSE_DISCONNECT_SENTINEL, seen)
        # oversize 没触发
        self.assertEqual(bus._oversize_drops, 0)


if __name__ == "__main__":
    unittest.main()
