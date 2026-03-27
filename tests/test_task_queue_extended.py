"""task_queue.py 覆盖率补充测试。

覆盖 Task 数据类边界（timeout<=0）、add_task timeout<=0、
remove_task 不存在任务、_cleanup_loop 异常、
stop_cleanup 超时、回调注册重复/取消、
update_auto_resubmit_timeout_for_all 边界等。
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from task_queue import Task, TaskQueue


class TestTaskDataclassEdges(unittest.TestCase):
    """Task 数据类 timeout<=0 边界"""

    def test_get_remaining_time_disabled(self):
        task = Task(task_id="t1", prompt="p", auto_resubmit_timeout=0)
        task.status = "active"
        self.assertEqual(task.get_remaining_time(), 0)

    def test_get_remaining_time_negative(self):
        task = Task(task_id="t2", prompt="p", auto_resubmit_timeout=-10)
        task.status = "active"
        self.assertEqual(task.get_remaining_time(), 0)

    def test_get_deadline_monotonic_disabled(self):
        task = Task(task_id="t3", prompt="p", auto_resubmit_timeout=0)
        self.assertEqual(task.get_deadline_monotonic(), float("inf"))

    def test_is_expired_completed(self):
        task = Task(task_id="t4", prompt="p", auto_resubmit_timeout=100)
        task.status = "completed"
        self.assertFalse(task.is_expired())

    def test_is_expired_disabled(self):
        task = Task(task_id="t5", prompt="p", auto_resubmit_timeout=0)
        task.status = "active"
        self.assertFalse(task.is_expired())

    def test_is_expired_negative(self):
        task = Task(task_id="t6", prompt="p", auto_resubmit_timeout=-5)
        task.status = "active"
        self.assertFalse(task.is_expired())

    def test_is_expired_true(self):
        task = Task(
            task_id="t7",
            prompt="p",
            auto_resubmit_timeout=1,
            created_at_monotonic=time.monotonic() - 10,
        )
        task.status = "active"
        self.assertTrue(task.is_expired())


class TestAddTaskTimeoutEdge(unittest.TestCase):
    """add_task timeout<=0 边界"""

    def test_timeout_zero(self):
        q = TaskQueue()
        q.add_task("t1", "p", auto_resubmit_timeout=0)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 0)
        q.stop_cleanup()

    def test_timeout_negative(self):
        q = TaskQueue()
        q.add_task("t1", "p", auto_resubmit_timeout=-5)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 0)
        q.stop_cleanup()

    def test_timeout_small_positive_clamped(self):
        q = TaskQueue()
        q.add_task("t1", "p", auto_resubmit_timeout=10)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 30)
        q.stop_cleanup()


class TestRemoveTaskEdges(unittest.TestCase):
    """remove_task 边界"""

    def test_remove_nonexistent(self):
        q = TaskQueue()
        result = q.remove_task("nonexistent")
        self.assertFalse(result)
        q.stop_cleanup()

    def test_remove_active_activates_next(self):
        q = TaskQueue()
        q.add_task("t1", "p1")
        q.add_task("t2", "p2")
        q.remove_task("t1")
        t2 = q.get_task("t2")
        assert t2 is not None
        self.assertEqual(t2.status, "active")
        q.stop_cleanup()


class TestUpdateAutoResubmitTimeoutForAll(unittest.TestCase):
    """update_auto_resubmit_timeout_for_all 边界"""

    def test_timeout_zero(self):
        q = TaskQueue()
        q.add_task("t1", "p")
        updated = q.update_auto_resubmit_timeout_for_all(0)
        self.assertGreater(updated, 0)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 0)
        q.stop_cleanup()

    def test_timeout_same_no_update(self):
        q = TaskQueue()
        q.add_task("t1", "p", auto_resubmit_timeout=60)
        updated = q.update_auto_resubmit_timeout_for_all(60)
        self.assertEqual(updated, 0)
        q.stop_cleanup()

    def test_skip_completed(self):
        q = TaskQueue()
        q.add_task("t1", "p")
        q.complete_task("t1", {"text": "answer"})
        updated = q.update_auto_resubmit_timeout_for_all(100)
        self.assertEqual(updated, 0)
        q.stop_cleanup()


class TestClearCompletedTasks(unittest.TestCase):
    """clear_completed_tasks 清理计数"""

    def test_clears_and_returns_count(self):
        q = TaskQueue()
        q.add_task("t1", "p")
        q.complete_task("t1", {"text": "a"})
        count = q.clear_completed_tasks()
        self.assertEqual(count, 1)
        q.stop_cleanup()

    def test_no_completed_returns_zero(self):
        q = TaskQueue()
        q.add_task("t1", "p")
        count = q.clear_completed_tasks()
        self.assertEqual(count, 0)
        q.stop_cleanup()


class TestCleanupLoopException(unittest.TestCase):
    """_cleanup_loop 异常处理"""

    def test_exception_doesnt_crash(self):
        q = TaskQueue()
        with patch.object(
            q, "cleanup_completed_tasks", side_effect=RuntimeError("boom")
        ):
            q._stop_cleanup.set()
            q._cleanup_loop()


class TestStopCleanupTimeout(unittest.TestCase):
    """stop_cleanup 线程超时"""

    def test_thread_still_alive_warning(self):
        q = TaskQueue()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        q._cleanup_thread = mock_thread
        q.stop_cleanup()
        mock_thread.join.assert_called_once_with(timeout=2)

    def test_thread_stops_normally(self):
        q = TaskQueue()
        q.stop_cleanup()


class TestCallbackRegistration(unittest.TestCase):
    """回调注册/取消注册"""

    def test_register_duplicate_ignored(self):
        q = TaskQueue()

        def cb(tid, old, new):
            pass

        q.register_status_change_callback(cb)
        q.register_status_change_callback(cb)
        self.assertEqual(q._status_change_callbacks.count(cb), 1)
        q.stop_cleanup()

    def test_unregister_nonexistent(self):
        q = TaskQueue()

        def cb(tid, old, new):
            pass

        q.unregister_status_change_callback(cb)
        q.stop_cleanup()

    def test_callback_triggered_on_add(self):
        q = TaskQueue()
        events: list[tuple] = []

        def cb(tid, old, new):
            events.append((tid, old, new))

        q.register_status_change_callback(cb)
        q.add_task("t1", "p")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], ("t1", None, "active"))
        q.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
