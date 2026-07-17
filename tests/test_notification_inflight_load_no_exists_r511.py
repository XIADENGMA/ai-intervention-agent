"""R511 - notification inflight restore reads directly without exists probe."""

from __future__ import annotations

import inspect
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent.notification_manager import (
    _INFLIGHT_FILE_NAME,
    _INFLIGHT_SCHEMA_VERSION,
    NotificationManager,
)


class TestInflightLoadNoExistsProbe(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="r511_"))
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

    def test_load_reads_directly_and_handles_missing_file(self) -> None:
        source = inspect.getsource(NotificationManager._load_persisted_inflight_events)

        self.assertIn('raw = path.read_text(encoding="utf-8")', source)
        self.assertIn("except FileNotFoundError:", source)
        self.assertNotIn("path.exists()", source)

    def test_missing_file_returns_empty_without_exists_probe_or_warning(self) -> None:
        path_type = type(self._file_path)

        with patch.object(
            path_type,
            "exists",
            side_effect=AssertionError("restore load path called exists()"),
        ):
            with patch(
                "ai_intervention_agent.notification_manager.logger.warning"
            ) as warning:
                result = self._manager._load_persisted_inflight_events()

        self.assertEqual(result, [])
        warning.assert_not_called()

    def test_valid_file_still_loads_fresh_event(self) -> None:
        event = {"id": "evt-r511", "saved_at_ts": time.time()}
        self._file_path.write_text(
            json.dumps(
                {
                    "schema_version": _INFLIGHT_SCHEMA_VERSION,
                    "events": [event],
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual(self._manager._load_persisted_inflight_events(), [event])

    def test_non_missing_oserror_still_warns_and_returns_empty(self) -> None:
        path_type = type(self._file_path)

        with patch.object(
            path_type,
            "read_text",
            side_effect=PermissionError("permission denied"),
        ):
            with patch(
                "ai_intervention_agent.notification_manager.logger.warning"
            ) as warning:
                result = self._manager._load_persisted_inflight_events()

        self.assertEqual(result, [])
        warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
