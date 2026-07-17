"""R515 - SSE gap_warning payload bypasses generic JSON serialization."""

from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import patch

from ai_intervention_agent.web_ui_routes.task import (
    _format_sse_gap_warning_payload,
    _SSEBus,
)


class TestSSEGapWarningFastPath(unittest.TestCase):
    def test_gap_warning_formatter_returns_parseable_fixed_schema_json(self) -> None:
        payload = _format_sse_gap_warning_payload(41)

        self.assertEqual(payload, '{"reason":"history_evicted","after_id":41}')
        self.assertEqual(
            json.loads(payload),
            {"reason": "history_evicted", "after_id": 41},
        )

    def test_subscribe_gap_warning_uses_dedicated_formatter(self) -> None:
        source = inspect.getsource(_SSEBus.subscribe)

        self.assertIn("_format_sse_gap_warning_payload(after_id)", source)
        gap_branch = source.split("if inject_gap_warning:", 1)[1].split(
            "for payload in replay_items:",
            1,
        )[0]
        self.assertNotIn("json.dumps", gap_branch)

    def test_evicted_gap_warning_does_not_call_json_dumps_during_subscribe(
        self,
    ) -> None:
        bus = _SSEBus()
        for i in range(bus._HISTORY_MAXLEN + 5):
            bus.emit("task_changed", {"task_id": f"task-{i}"})

        with patch(
            "ai_intervention_agent.web_ui_routes.task.json.dumps",
            side_effect=AssertionError("gap_warning should not use json.dumps"),
        ):
            q = bus.subscribe(after_id=1)

        first = q.get_nowait()
        self.assertEqual(first["id"], -1)
        self.assertEqual(first["type"], "gap_warning")
        self.assertEqual(first["data"], {"reason": "history_evicted", "after_id": 1})
        self.assertEqual(
            first["_serialized"],
            '{"reason":"history_evicted","after_id":1}',
        )
        self.assertEqual(json.loads(first["_serialized"]), first["data"])

    def test_non_evicted_replay_payloads_still_keep_pre_serialized_data(self) -> None:
        bus = _SSEBus()
        bus.emit("task_changed", {"task_id": "t1"})
        bus.emit("task_changed", {"task_id": "t2"})

        q = bus.subscribe(after_id=1)
        replayed = q.get_nowait()

        self.assertEqual(replayed["id"], 2)
        self.assertEqual(replayed["type"], "task_changed")
        self.assertEqual(replayed["_serialized"], '{"task_id": "t2"}')


if __name__ == "__main__":
    unittest.main()
