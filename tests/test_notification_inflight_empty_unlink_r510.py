"""R510 - notification inflight empty persistence unlinks without pre-stat."""

from __future__ import annotations

import inspect
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent.notification_manager import (
    _INFLIGHT_FILE_NAME,
    NotificationManager,
)


class TestInflightEmptyUnlinkFastPath(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="r510_"))
        self._patcher = patch(
            "ai_intervention_agent.notification_manager._get_inflight_file_dir",
            return_value=self._tmp_dir,
        )
        self._patcher.start()
        self._manager = NotificationManager._create_test_instance()

    def tearDown(self) -> None:
        self._patcher.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    @property
    def _file_path(self) -> Path:
        return self._tmp_dir / _INFLIGHT_FILE_NAME

    def test_empty_inflight_unlinks_with_missing_ok_before_return(self) -> None:
        source = inspect.getsource(NotificationManager._persist_inflight_unlocked)
        empty_branch = source.split("if not ids:", 1)[1].split("return", 1)[0]

        self.assertIn("path.unlink(missing_ok=True)", empty_branch)
        self.assertNotIn("path.exists()", source)

    def test_empty_inflight_removes_existing_file(self) -> None:
        self._file_path.write_text("{}", encoding="utf-8")

        with self._manager._queue_lock:
            self._manager._inflight_persisted_ids = set()
            self._manager._persist_inflight_unlocked()

        self.assertFalse(self._file_path.exists())

    def test_empty_inflight_missing_file_does_not_probe_exists(self) -> None:
        path_type = type(self._file_path)

        with self._manager._queue_lock:
            self._manager._inflight_persisted_ids = set()
            with patch.object(
                path_type,
                "exists",
                side_effect=AssertionError("empty unlink path called exists()"),
            ):
                self._manager._persist_inflight_unlocked()

        self.assertFalse(self._file_path.exists())


if __name__ == "__main__":
    unittest.main()
