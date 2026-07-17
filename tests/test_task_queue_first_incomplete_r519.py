"""R519 - active-question fallback finds the first incomplete task lazily."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from ai_intervention_agent.task_queue import TaskQueue


class TestTaskQueueFirstIncomplete(unittest.TestCase):
    def _queue(self) -> TaskQueue:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return TaskQueue(max_tasks=10, persist_path=str(Path(tmp.name) / "tasks.json"))

    def test_returns_first_incomplete_in_insertion_order(self) -> None:
        q = self._queue()
        q.add_task("first", "first prompt")
        q.add_task("second", "second prompt")
        q.complete_task("first", {"ok": True})

        first_incomplete = q.get_first_incomplete_task()

        self.assertIsNotNone(first_incomplete)
        assert first_incomplete is not None
        self.assertEqual(first_incomplete.task_id, "second")

    def test_returns_none_when_empty_or_all_completed(self) -> None:
        q = self._queue()
        self.assertIsNone(q.get_first_incomplete_task())
        self.assertFalse(q.has_tasks())

        q.add_task("done", "done prompt")
        q.complete_task("done", {"ok": True})

        self.assertIsNone(q.get_first_incomplete_task())
        self.assertTrue(q.has_tasks())

    def test_helper_does_not_materialize_task_lists(self) -> None:
        source = inspect.getsource(TaskQueue.get_first_incomplete_task)

        self.assertIn("for task in self._tasks.values()", source)
        self.assertNotIn("list(", source)
        self.assertNotIn("[", source)

    def test_web_ui_auto_activate_uses_helper_not_filtered_list(self) -> None:
        import ai_intervention_agent.web_ui as web_ui

        source = Path(web_ui.__file__).read_text(encoding="utf-8")

        self.assertIn("task_queue.get_first_incomplete_task()", source)
        self.assertIn("task_queue.has_tasks()", source)
        self.assertNotIn("incomplete_tasks = [", source)
        self.assertNotIn("task_queue.get_all_tasks()", source)


if __name__ == "__main__":
    unittest.main()
