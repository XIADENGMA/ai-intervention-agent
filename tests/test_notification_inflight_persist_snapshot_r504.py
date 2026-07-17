"""R504 - notification inflight persistence uses one timestamp snapshot."""

from __future__ import annotations

import inspect
import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent.notification_manager import (
    _INFLIGHT_FILE_NAME,
    NotificationManager,
)
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationPriority,
    NotificationTrigger,
    NotificationType,
)


def _make_event(event_id: str) -> NotificationEvent:
    return NotificationEvent(
        id=event_id,
        title="hello",
        message="world",
        trigger=NotificationTrigger.IMMEDIATE,
        types=[NotificationType.WEB],
        max_retries=3,
        priority=NotificationPriority.NORMAL,
    )


class TestInflightPersistTimestampSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="r504_"))
        self._patcher = patch(
            "ai_intervention_agent.notification_manager._get_inflight_file_dir",
            return_value=self._tmp_dir,
        )
        self._patcher.start()
        self._manager = NotificationManager()
        self._manager._inflight_persisted_ids = set()
        self._manager._inflight_seen_at_startup = []
        with self._manager._queue_lock:
            self._manager._event_queue = []

    def tearDown(self) -> None:
        self._patcher.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    @property
    def _file_path(self) -> Path:
        return self._tmp_dir / _INFLIGHT_FILE_NAME

    def test_persist_inflight_unlocked_captures_one_time_snapshot(self) -> None:
        source = inspect.getsource(NotificationManager._persist_inflight_unlocked)

        self.assertIn("saved_at_ts = time.time()", source)
        self.assertIn("datetime.fromtimestamp(saved_at_ts, UTC).isoformat()", source)
        self.assertNotIn("datetime.now(UTC).isoformat()", source)
        self.assertEqual(source.count("time.time()"), 1)

    def test_saved_at_and_event_timestamps_share_same_snapshot(self) -> None:
        evt_a = _make_event("evt-a")
        evt_b = _make_event("evt-b")
        saved_at_ts = 1_700_000_000.25

        with self._manager._queue_lock:
            self._manager._event_queue.extend([evt_a, evt_b])
            self._manager._inflight_persisted_ids = {evt_a.id, evt_b.id}
            with patch(
                "ai_intervention_agent.notification_manager.time.time",
                return_value=saved_at_ts,
            ) as fake_time:
                self._manager._persist_inflight_unlocked()

        self.assertEqual(fake_time.call_count, 1)
        data = json.loads(self._file_path.read_text(encoding="utf-8"))
        self.assertEqual(
            data["saved_at"],
            datetime.fromtimestamp(saved_at_ts, UTC).isoformat(),
        )
        self.assertEqual(
            {event["saved_at_ts"] for event in data["events"]},
            {saved_at_ts},
        )


if __name__ == "__main__":
    unittest.main()
