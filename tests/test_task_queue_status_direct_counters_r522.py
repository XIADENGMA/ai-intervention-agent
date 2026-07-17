"""R522 regression coverage for direct task status counters."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.task_queue import TaskQueue


class TestTaskQueueStatusDirectCountersRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = TaskQueue(max_tasks=10)
        self.addCleanup(self.queue.stop_cleanup)

    def _seed_queue_with_unknown_status(self) -> None:
        self.queue.add_task("r522-active", "active")
        self.queue.add_task("r522-pending", "pending")
        self.queue.add_task("r522-weird", "unknown")
        weird = self.queue.get_task("r522-weird")
        assert weird is not None
        weird.status = "paused"

    def test_get_task_count_ignores_unknown_status_in_breakdown(self) -> None:
        self._seed_queue_with_unknown_status()

        stats = self.queue.get_task_count()

        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["active"], 1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["completed"], 0)
        self.assertLess(
            stats["pending"] + stats["active"] + stats["completed"],
            stats["total"],
        )

    def test_get_all_tasks_with_stats_ignores_unknown_status_in_breakdown(self) -> None:
        self._seed_queue_with_unknown_status()

        tasks, stats = self.queue.get_all_tasks_with_stats()

        self.assertEqual(
            [task.task_id for task in tasks],
            ["r522-active", "r522-pending", "r522-weird"],
        )
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["active"], 1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["completed"], 0)


class TestTaskQueueStatusDirectCountersSource(unittest.TestCase):
    def test_counting_methods_do_not_allocate_counts_dict(self) -> None:
        for method in (
            TaskQueue.get_all_tasks_with_stats,
            TaskQueue.get_task_count,
        ):
            method_src = inspect.getsource(method)
            self.assertNotIn("counts: dict", method_src)
            self.assertNotIn("if t.status in counts:", method_src)
            self.assertNotIn("counts[t.status]", method_src)
            self.assertIn("pending = active = completed = 0", method_src)
            self.assertIn("if t.status == TaskStatus.PENDING:", method_src)
            self.assertIn("elif t.status == TaskStatus.ACTIVE:", method_src)
            self.assertIn("elif t.status == TaskStatus.COMPLETED:", method_src)
            self.assertIn('"pending": pending', method_src)
            self.assertIn('"active": active', method_src)
            self.assertIn('"completed": completed', method_src)

    def test_docstrings_record_r522_reason(self) -> None:
        self.assertIn("R522", TaskQueue.get_all_tasks_with_stats.__doc__ or "")
        self.assertIn("R522", TaskQueue.get_task_count.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
