"""R514 - TaskQueue quarantine renames directly without an exists probe."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent.task_queue import TaskQueue


class TestTaskQueueQuarantineNoExistsProbe(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.persist_path = Path(self._tmp.name) / "tasks.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _queue(self) -> TaskQueue:
        return TaskQueue(persist_path=str(self.persist_path))

    def test_quarantine_uses_os_replace_without_exists_probe(self) -> None:
        source = inspect.getsource(TaskQueue._quarantine_corrupt_persist_file)

        self.assertIn("os.replace(", source)
        self.assertIn("except FileNotFoundError:", source)
        self.assertNotIn(".exists()", source)

    def test_missing_file_is_silent_without_exists_probe(self) -> None:
        q = self._queue()
        path_type = type(self.persist_path)
        try:
            with patch.object(
                path_type,
                "exists",
                side_effect=AssertionError("quarantine called exists()"),
            ):
                with patch(
                    "ai_intervention_agent.task_queue.logger.warning",
                    side_effect=AssertionError(
                        "missing quarantine source should stay silent"
                    ),
                ):
                    q._quarantine_corrupt_persist_file(reason="missing")
        finally:
            q.stop_cleanup()

    def test_existing_file_is_quarantined_without_losing_bytes(self) -> None:
        q = self._queue()
        try:
            self.persist_path.write_text("not-json", encoding="utf-8")
            q._quarantine_corrupt_persist_file(reason="bad json")
        finally:
            q.stop_cleanup()

        self.assertFalse(self.persist_path.exists())
        corrupts = sorted(
            self.persist_path.parent.glob(f"{self.persist_path.name}.corrupt-*")
        )
        self.assertEqual(len(corrupts), 1)
        self.assertEqual(corrupts[0].read_text(encoding="utf-8"), "not-json")

    def test_non_missing_replace_error_still_warns_and_does_not_propagate(self) -> None:
        q = self._queue()
        try:
            self.persist_path.write_text("not-json", encoding="utf-8")
            with patch(
                "ai_intervention_agent.task_queue.os.replace",
                side_effect=PermissionError("permission denied"),
            ):
                with patch("ai_intervention_agent.task_queue.logger.warning") as warn:
                    q._quarantine_corrupt_persist_file(reason="bad json")
        finally:
            q.stop_cleanup()

        warn.assert_called_once()
        self.assertIn(
            "quarantine 损坏持久化文件失败",
            str(warn.call_args.args[0]),
        )
        self.assertTrue(self.persist_path.exists())


if __name__ == "__main__":
    unittest.main()
