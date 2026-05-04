"""P6R-2 回归：set_active_task 对 already-active 的任务必须幂等。

背景：
    历史实现里，调用 set_active_task(current_active_id) 会：
      1. 先把自己从 ACTIVE 降级为 PENDING（产生事件 ACTIVE→PENDING）；
      2. 再升级回 ACTIVE（产生事件 PENDING→ACTIVE）。
    结果：
      - 单次幂等调用触发两个虚假状态变更事件；
      - SSE 推送闪烁、回调被重复触发、持久化快照多写一次；
      - 日志里每次都会出现"切换到任务: <self>"噪音。

这里用 register_status_change_callback 捕捉事件做断言。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from task_queue import TaskQueue


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, str]] = []

    def __call__(self, task_id: str, old: str | None, new: str) -> None:
        self.events.append((task_id, old, new))


class TestSetActiveIdempotent(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = TaskQueue()
        self.rec = _Recorder()
        self.queue.register_status_change_callback(self.rec)

    def tearDown(self) -> None:
        self.queue.stop_cleanup()

    def test_set_active_to_already_active_emits_no_events(self) -> None:
        self.queue.add_task("t1", "p1")
        active = self.queue.get_active_task()
        assert active is not None
        self.assertEqual(active.task_id, "t1")

        events_before = list(self.rec.events)
        ok = self.queue.set_active_task("t1")
        self.assertTrue(ok, "幂等调用应返回 True（而不是假装切换失败）")

        events_after = list(self.rec.events)
        self.assertEqual(
            events_before,
            events_after,
            "对 already-active 的任务再次 set_active_task 不应产生任何状态事件",
        )

        task = self.queue.get_task("t1")
        assert task is not None
        self.assertEqual(task.status, "active")

    def test_set_active_to_already_active_skips_persist(self) -> None:
        """幂等调用不应触发 _persist()。"""
        with tempfile.TemporaryDirectory() as tmp:
            persist = Path(tmp) / "tasks.json"
            q = TaskQueue(persist_path=str(persist))
            try:
                q.add_task("t1", "p1")
                self.assertTrue(persist.exists())
                mtime_before = persist.stat().st_mtime_ns

                ok = q.set_active_task("t1")
                self.assertTrue(ok)

                mtime_after = persist.stat().st_mtime_ns
                self.assertEqual(
                    mtime_before,
                    mtime_after,
                    "幂等 set_active_task 不应触发 _persist() 额外写盘",
                )
            finally:
                q.stop_cleanup()

    def test_set_active_real_switch_still_emits_events(self) -> None:
        """真正切换活动任务时，事件仍然必须正确发出。"""
        self.queue.add_task("t1", "p1")
        self.queue.add_task("t2", "p2")

        active = self.queue.get_active_task()
        assert active is not None
        active_id = active.task_id
        other_id = "t2" if active_id == "t1" else "t1"

        self.rec.events.clear()
        ok = self.queue.set_active_task(other_id)
        self.assertTrue(ok)

        self.assertGreaterEqual(
            len(self.rec.events),
            2,
            "真实切换应同时发出 old ACTIVE→PENDING 与 new PENDING→ACTIVE 两个事件",
        )

        downgrade = any(
            ev[0] == active_id and ev[1] == "active" and ev[2] == "pending"
            for ev in self.rec.events
        )
        upgrade = any(ev[0] == other_id and ev[2] == "active" for ev in self.rec.events)
        self.assertTrue(downgrade, "旧活动任务应发出 ACTIVE→PENDING 事件")
        self.assertTrue(upgrade, "新活动任务应发出 *→ACTIVE 事件")

    def test_set_active_to_nonexistent_returns_false(self) -> None:
        """不存在任务返回 False；不应产生事件。"""
        self.rec.events.clear()
        self.assertFalse(self.queue.set_active_task("nope"))
        self.assertEqual(self.rec.events, [])

    def test_set_active_to_completed_returns_false(self) -> None:
        """已完成任务不能被激活；不应产生事件。"""
        self.queue.add_task("t1", "p1")
        self.queue.complete_task("t1", {"text": "x"})
        self.rec.events.clear()
        self.assertFalse(self.queue.set_active_task("t1"))
        self.assertEqual(self.rec.events, [])


if __name__ == "__main__":
    unittest.main()
