"""R509 - TaskQueue persistence removes empty recoverable snapshots."""

from __future__ import annotations

import inspect
import shutil
import tempfile
import unittest
from pathlib import Path

from ai_intervention_agent.task_queue import TaskQueue


class TestTaskQueuePersistEmptySnapshotUnlink(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="r509_"))
        self._persist_path = self._tmp_dir / "tasks.json"
        self._queues: list[TaskQueue] = []

    def tearDown(self) -> None:
        for queue in self._queues:
            queue.stop_cleanup()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _queue(self) -> TaskQueue:
        queue = TaskQueue(persist_path=str(self._persist_path))
        self._queues.append(queue)
        return queue

    def test_persist_unlinks_empty_snapshot_before_json_dump(self) -> None:
        source = inspect.getsource(TaskQueue._persist)

        self.assertIn("if not snapshot:", source)
        self.assertIn("self._persist_path.unlink(missing_ok=True)", source)
        self.assertLess(
            source.index("if not snapshot:"),
            source.index("json.dump("),
        )

    def test_completing_last_recoverable_task_removes_persist_file(self) -> None:
        queue = self._queue()
        self.assertTrue(queue.add_task("task-r509", "prompt"))
        self.assertTrue(self._persist_path.exists())

        self.assertTrue(queue.complete_task("task-r509", {"text": "done"}))

        self.assertFalse(self._persist_path.exists())
        restored_queue = self._queue()
        self.assertEqual(restored_queue.get_task_count()["total"], 0)

    def test_removing_last_task_removes_persist_file(self) -> None:
        queue = self._queue()
        self.assertTrue(queue.add_task("task-r509-remove", "prompt"))
        self.assertTrue(self._persist_path.exists())

        self.assertTrue(queue.remove_task("task-r509-remove"))

        self.assertFalse(self._persist_path.exists())
        restored_queue = self._queue()
        self.assertEqual(restored_queue.get_task_count()["total"], 0)


if __name__ == "__main__":
    unittest.main()
