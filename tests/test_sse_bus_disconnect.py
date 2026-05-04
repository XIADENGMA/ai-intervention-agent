"""锁住 ``_SSEBus`` 的 backpressure 主动断开 contract。

历史 bug：``_SSEBus.emit`` 在订阅者 queue 积压超过 3/4 容量时，会把那个
订阅者从 ``_subscribers`` 集合里 ``discard`` 掉——但**没有通知 generator
端**。Generator 在 ``q.get(timeout=25)`` 上继续 wait/yield，旧消息消费完
后开始无限发心跳，浏览器 EventSource 看着心跳跳，认为连接活着，但 emit
已经不再往这个 queue 写新事件 → silent disconnection。

修复：
- 引入 module-level sentinel ``_SSE_DISCONNECT_SENTINEL``。
- ``emit`` discard 订阅者时尝试 ``put_nowait(sentinel)``。
- ``generate`` generator 看到 sentinel 后 ``return``，触发 SSE EOF →
  浏览器自动 reconnect → 重新 ``subscribe()`` 拿全新 queue。

本文件 6 个测试覆盖：
1. 正常 emit 不触发 backpressure，sentinel 不出现。
2. 队列 Full（满 64）时订阅者被 discard 且 sentinel 被塞入。
3. 队列积压到 BACKPRESSURE_THRESHOLD（48） 时订阅者被 discard 且 sentinel 被塞入。
4. Subscribe 后 unsubscribe 不会向 queue 塞 sentinel（正常断开路径）。
5. ``subscriber_count`` 反映 discard 后的实际数。
6. 反向锁：sentinel 必须是 ``object()`` 单例（不能改成 ``None`` 之类的，
   否则 ``q.get`` 拿到合法 ``None`` payload 会被误识别）。
"""

from __future__ import annotations

import unittest

from web_ui_routes.task import _SSE_DISCONNECT_SENTINEL, _SSEBus


class TestSSEBusBackpressureDisconnect(unittest.TestCase):
    """``_SSEBus`` backpressure 路径必须主动通知 generator 退出。"""

    def test_normal_emit_does_not_inject_sentinel(self):
        bus = _SSEBus()
        q = bus.subscribe()
        bus.emit("task_changed", {"task_id": "t1"})
        bus.emit("task_changed", {"task_id": "t2"})
        bus.emit("task_changed", {"task_id": "t3"})

        seen: list[object] = []
        while not q.empty():
            seen.append(q.get_nowait())

        self.assertEqual(len(seen), 3)
        for evt in seen:
            self.assertIsNot(
                evt,
                _SSE_DISCONNECT_SENTINEL,
                "正常吞吐路径不应出现 sentinel；只有 backpressure / Full discard 才应出现",
            )

    def test_queue_full_discards_subscriber_and_signals_generator(self):
        """灌满 queue 触发 ``queue.Full`` 路径：订阅者被 discard + sentinel 塞入。"""
        bus = _SSEBus()
        q = bus.subscribe()

        for i in range(_SSEBus._QUEUE_MAXSIZE):
            q.put_nowait({"type": "filler", "data": {"i": i}})

        bus.emit("overflow_event", {"task_id": "should-be-dropped"})

        self.assertEqual(bus.subscriber_count, 0)
        seen: list[object] = []
        while not q.empty():
            seen.append(q.get_nowait())
        self.assertIn(
            _SSE_DISCONNECT_SENTINEL,
            seen,
            "Full 触发时 emit 必须给被 discard 的 queue 塞 sentinel "
            "（即使 queue 已满，也应尝试 put_nowait 让 generator 优雅退出）",
        )

    def test_backpressure_threshold_discards_and_signals(self):
        """达到 ``_BACKPRESSURE_THRESHOLD`` 时订阅者被 discard + sentinel 塞入。"""
        bus = _SSEBus()
        q = bus.subscribe()

        threshold = _SSEBus._BACKPRESSURE_THRESHOLD
        for i in range(threshold - 1):
            q.put_nowait({"type": "filler", "data": {"i": i}})

        self.assertEqual(bus.subscriber_count, 1)
        bus.emit("threshold_trigger", {"task_id": "trips-discard"})

        self.assertEqual(bus.subscriber_count, 0)
        seen: list[object] = []
        while not q.empty():
            seen.append(q.get_nowait())
        self.assertIn(
            _SSE_DISCONNECT_SENTINEL,
            seen,
            "积压到 BACKPRESSURE_THRESHOLD 时必须塞 sentinel；"
            "否则 generator 会继续 yield heartbeat 但永远收不到新事件",
        )

    def test_unsubscribe_does_not_inject_sentinel(self):
        """正常 ``unsubscribe`` 不应往 queue 塞 sentinel（generator 自己 GeneratorExit 走 finally）。"""
        bus = _SSEBus()
        q = bus.subscribe()
        bus.unsubscribe(q)

        self.assertTrue(
            q.empty(),
            "unsubscribe 是优雅断开路径；不应主动塞 sentinel "
            "（client 已断开，generator 已通过 GeneratorExit 退出，无需再触发 EOF）",
        )
        self.assertEqual(bus.subscriber_count, 0)

    def test_subscriber_count_reflects_discards(self):
        """``subscriber_count`` 必须等于实际 ``_subscribers`` 集合大小。"""
        bus = _SSEBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        self.assertEqual(bus.subscriber_count, 2)

        for i in range(_SSEBus._QUEUE_MAXSIZE):
            q1.put_nowait({"type": "filler", "data": {"i": i}})

        bus.emit("force_discard_q1", {})

        self.assertEqual(bus.subscriber_count, 1)
        bus.emit("only_q2_should_get_this", {})
        self.assertFalse(
            q2.empty(),
            "未被 discard 的订阅者必须继续收到事件（q2 不应被 q1 的 backpressure 影响）",
        )

    def test_sentinel_is_unique_object_identity(self):
        """反向锁：``_SSE_DISCONNECT_SENTINEL`` 必须是 ``object()`` 单例。

        如果未来有人改成 ``None`` / ``False`` / ``""`` 等"看起来 falsy 的值"，
        那就和合法的 SSE 事件 payload 撞了——比如 ``q.get`` 拿到 ``{"type":
        "...", "data": {}}`` 时 ``data`` 是空字典，generator 用 ``is`` 比较
        sentinel 也会匹配 → 误以为该退出。``object()`` 实例的 ``id()`` 全局
        唯一，``is`` 比较绝对安全。
        """
        from queue import Queue

        q: Queue = Queue()
        q.put({"type": "task_changed", "data": {}})
        q.put(None)
        q.put(False)
        q.put({})
        q.put(_SSE_DISCONNECT_SENTINEL)

        seen: list[object] = []
        while not q.empty():
            seen.append(q.get_nowait())

        for item in seen[:-1]:
            self.assertIsNot(
                item,
                _SSE_DISCONNECT_SENTINEL,
                "Sentinel 不能与任何合法 SSE 事件 payload 共享 identity",
            )
        self.assertIs(seen[-1], _SSE_DISCONNECT_SENTINEL)


if __name__ == "__main__":
    unittest.main()
