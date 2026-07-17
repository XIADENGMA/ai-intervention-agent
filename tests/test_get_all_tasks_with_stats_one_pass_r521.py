"""R521 regression coverage for one-pass task snapshot + stats."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.task_queue import TaskQueue, TaskStatus


class TestGetAllTasksWithStatsOnePassRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = TaskQueue(max_tasks=10)
        self.addCleanup(self.queue.stop_cleanup)

    def test_preserves_snapshot_order_counts_and_copy_semantics(self) -> None:
        self.queue.add_task("r521-a", "alpha")
        self.queue.add_task("r521-b", "bravo")
        self.queue.add_task("r521-c", "charlie")
        self.queue.complete_task("r521-a", {"feedback": "ok"})

        tasks, stats = self.queue.get_all_tasks_with_stats()

        self.assertEqual(
            [task.task_id for task in tasks], ["r521-a", "r521-b", "r521-c"]
        )
        self.assertEqual(
            stats,
            {
                "total": 3,
                "pending": 1,
                "active": 1,
                "completed": 1,
                "max": 10,
            },
        )

        tasks.clear()
        fresh_tasks, fresh_stats = self.queue.get_all_tasks_with_stats()
        self.assertEqual(
            [task.task_id for task in fresh_tasks], ["r521-a", "r521-b", "r521-c"]
        )
        self.assertEqual(fresh_stats["total"], 3)


class TestGetAllTasksWithStatsOnePassSource(unittest.TestCase):
    def test_method_builds_list_and_counts_in_one_values_loop(self) -> None:
        method_src = inspect.getsource(TaskQueue.get_all_tasks_with_stats)

        self.assertNotIn(
            "tasks_view = list(self._tasks.values())",
            method_src,
            "R521: do not build a task list and then scan it again for counts",
        )
        self.assertIn("tasks_view: list[Task] = []", method_src)
        self.assertIn("for t in self._tasks.values():", method_src)
        self.assertIn("tasks_view.append(t)", method_src)
        self.assertIn("if t.status == TaskStatus.PENDING:", method_src)
        self.assertIn("R521", TaskQueue.get_all_tasks_with_stats.__doc__ or "")

    def test_status_keys_still_match_task_status_constants(self) -> None:
        method_src = inspect.getsource(TaskQueue.get_all_tasks_with_stats)

        for status in (TaskStatus.PENDING, TaskStatus.ACTIVE, TaskStatus.COMPLETED):
            self.assertIn(status, method_src)


if __name__ == "__main__":
    unittest.main()
