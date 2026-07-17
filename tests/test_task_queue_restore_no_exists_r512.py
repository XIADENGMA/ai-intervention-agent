"""R512 - TaskQueue restore reads persistence directly without exists probe."""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent.task_queue import TaskQueue


def _write_task_snapshot(path: Path, task_id: str = "task-r512") -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "saved_at": datetime.now(UTC).isoformat(),
                "active_task_id": task_id,
                "tasks": [
                    {
                        "task_id": task_id,
                        "prompt": "restore without exists probe",
                        "predefined_options": [],
                        "auto_resubmit_timeout": 120,
                        "created_at": datetime.now(UTC).isoformat(),
                        "status": "pending",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class TestTaskQueueRestoreNoExistsProbe(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.persist_path = Path(self._tmp.name) / "tasks.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _queue(self) -> TaskQueue:
        return TaskQueue(persist_path=str(self.persist_path))

    def test_restore_reads_directly_and_handles_missing_file(self) -> None:
        source = inspect.getsource(TaskQueue._restore)

        self.assertIn('raw = self._persist_path.read_text(encoding="utf-8")', source)
        self.assertIn("except FileNotFoundError:", source)
        restore_prefix = source.split("def _quarantine_corrupt_persist_file", 1)[0]
        self.assertNotIn(".exists()", restore_prefix)

    def test_missing_file_returns_empty_without_exists_probe_or_quarantine(
        self,
    ) -> None:
        path_type = type(self.persist_path)

        with patch.object(
            path_type,
            "exists",
            side_effect=AssertionError("TaskQueue._restore called exists()"),
        ):
            with patch.object(
                TaskQueue,
                "_quarantine_corrupt_persist_file",
                side_effect=AssertionError("missing file should not be quarantined"),
            ):
                q = self._queue()
        try:
            self.assertEqual(q.get_task_count()["total"], 0)
            self.assertIsNone(q.get_active_task())
        finally:
            q.stop_cleanup()

    def test_valid_file_still_restores_task(self) -> None:
        _write_task_snapshot(self.persist_path)

        q = self._queue()
        try:
            restored = q.get_task("task-r512")
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(restored.prompt, "restore without exists probe")
            active = q.get_active_task()
            self.assertIsNotNone(active)
            assert active is not None
            self.assertEqual(active.task_id, "task-r512")
        finally:
            q.stop_cleanup()

    def test_non_missing_read_error_still_quarantines(self) -> None:
        with patch.object(
            type(self.persist_path),
            "read_text",
            side_effect=PermissionError("permission denied"),
        ):
            with patch.object(
                TaskQueue,
                "_quarantine_corrupt_persist_file",
            ) as quarantine:
                q = self._queue()
        try:
            self.assertEqual(q.get_task_count()["total"], 0)
            quarantine.assert_called_once()
        finally:
            q.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
