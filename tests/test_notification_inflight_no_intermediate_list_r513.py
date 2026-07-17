"""R513 - notification inflight persistence avoids an intermediate event list."""

from __future__ import annotations

import inspect
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_intervention_agent.notification_manager import (
    _COMPACT_JSON_SEPARATORS,
    _INFLIGHT_FILE_NAME,
    _INFLIGHT_SCHEMA_VERSION,
    NotificationManager,
)
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationPriority,
    NotificationTrigger,
    NotificationType,
)


def _make_event(event_id: str, message: str = "world") -> NotificationEvent:
    return NotificationEvent(
        id=event_id,
        title=f"title-{event_id}",
        message=message,
        trigger=NotificationTrigger.IMMEDIATE,
        types=[NotificationType.WEB],
        max_retries=3,
        priority=NotificationPriority.NORMAL,
    )


class TestInflightPersistNoIntermediateList(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="r513_"))
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

    def test_persist_inflight_unlocked_filters_without_events_to_save_list(
        self,
    ) -> None:
        source = inspect.getsource(NotificationManager._persist_inflight_unlocked)

        self.assertNotIn("events_to_save", source)
        self.assertIn("for e in self._event_queue", source)
        self.assertIn("if e.id in ids", source)
        self.assertEqual(source.count("self._event_queue"), 1)

    def test_persisted_events_are_filtered_in_queue_order(self) -> None:
        stale = _make_event("stale", message="ignore")
        evt_a = _make_event("evt-a", message="世界")
        evt_b = _make_event("evt-b")

        with self._manager._queue_lock:
            self._manager._event_queue.extend([stale, evt_a, evt_b])
            self._manager._inflight_persisted_ids = {
                evt_a.id,
                "missing-from-queue",
                evt_b.id,
            }
            self._manager._persist_inflight_unlocked()

        raw = self._file_path.read_text(encoding="utf-8")
        data = json.loads(raw)

        self.assertEqual(data["schema_version"], _INFLIGHT_SCHEMA_VERSION)
        self.assertEqual([event["id"] for event in data["events"]], ["evt-a", "evt-b"])
        self.assertNotIn("stale", raw)
        self.assertNotIn("missing-from-queue", raw)
        self.assertEqual(
            raw,
            json.dumps(data, ensure_ascii=False, separators=_COMPACT_JSON_SEPARATORS),
        )

    def test_each_persisted_event_uses_single_saved_at_snapshot(self) -> None:
        evt_a = _make_event("evt-a")
        evt_b = _make_event("evt-b")
        saved_at_ts = 1_700_000_001.5

        with self._manager._queue_lock:
            self._manager._event_queue.extend([evt_a, evt_b])
            self._manager._inflight_persisted_ids = {evt_a.id, evt_b.id}
            with patch(
                "ai_intervention_agent.notification_manager.time.time",
                return_value=saved_at_ts,
            ) as fake_time:
                self._manager._persist_inflight_unlocked()

        data = json.loads(self._file_path.read_text(encoding="utf-8"))
        self.assertEqual(fake_time.call_count, 1)
        self.assertEqual(
            [event["saved_at_ts"] for event in data["events"]],
            [saved_at_ts, saved_at_ts],
        )


if __name__ == "__main__":
    unittest.main()
