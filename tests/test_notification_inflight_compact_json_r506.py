"""R506 - notification inflight persistence writes compact machine JSON."""

from __future__ import annotations

import inspect
import json
import shutil
import tempfile
import unittest
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


def _make_event(event_id: str, message: str = "world") -> NotificationEvent:
    return NotificationEvent(
        id=event_id,
        title="hello",
        message=message,
        trigger=NotificationTrigger.IMMEDIATE,
        types=[NotificationType.WEB],
        max_retries=3,
        priority=NotificationPriority.NORMAL,
    )


class TestInflightPersistCompactJson(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="r506_"))
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

    def test_persist_inflight_unlocked_uses_compact_json_separators(self) -> None:
        source = inspect.getsource(NotificationManager._persist_inflight_unlocked)

        self.assertIn("separators=_COMPACT_JSON_SEPARATORS", source)
        self.assertNotIn("indent=2", source)

    def test_persisted_inflight_json_is_compact_but_schema_compatible(self) -> None:
        evt_a = _make_event("evt-a", message="世界")
        evt_b = _make_event("evt-b")

        with self._manager._queue_lock:
            self._manager._event_queue.extend([evt_a, evt_b])
            self._manager._inflight_persisted_ids = {evt_a.id, evt_b.id}
            self._manager._persist_inflight_unlocked()

        raw = self._file_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

        self.assertEqual(raw, compact)
        self.assertLess(len(raw), len(pretty))
        self.assertNotIn("\n", raw)
        self.assertNotIn(": ", raw)
        self.assertIn("世界", raw)
        self.assertEqual([event["id"] for event in data["events"]], ["evt-a", "evt-b"])


if __name__ == "__main__":
    unittest.main()
