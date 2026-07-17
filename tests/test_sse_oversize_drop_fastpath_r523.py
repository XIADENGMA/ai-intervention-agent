"""R523 - SSE oversize_drop fixed-schema payload formatting."""

from __future__ import annotations

import inspect
import json
import unittest
from typing import Any
from unittest.mock import patch

from ai_intervention_agent.web_ui_routes import task as task_module
from ai_intervention_agent.web_ui_routes.task import (
    _format_sse_oversize_drop_payload,
    _SSEBus,
)


class TestSSEOversizeDropFormatterR523(unittest.TestCase):
    def test_formatter_returns_parseable_fixed_schema_json(self) -> None:
        payload = _format_sse_oversize_drop_payload(
            'task_"changed"\n中文',
            300_000,
            262_144,
        )

        self.assertIsInstance(payload, str)
        assert payload is not None
        self.assertEqual(
            json.loads(payload),
            {
                "original_event_type": 'task_"changed"\n中文',
                "size_bytes": 300_000,
                "limit_bytes": 262_144,
            },
        )
        self.assertIn('"size_bytes":300000', payload)
        self.assertIn('"limit_bytes":262144', payload)

    def test_formatter_preserves_fail_soft_encoder_boundary(self) -> None:
        with patch.object(
            task_module.json,
            "dumps",
            side_effect=TypeError("encoder unavailable"),
        ):
            self.assertIsNone(
                _format_sse_oversize_drop_payload("task_changed", 300_000, 262_144)
            )


class TestSSEOversizeDropEmitFastPathR523(unittest.TestCase):
    def test_oversize_branch_uses_dedicated_formatter(self) -> None:
        source = inspect.getsource(_SSEBus.emit)
        oversize_branch = source.split("if exceeds_limit:", 1)[1].split(
            "# R134：emit 时间戳",
            1,
        )[0]

        self.assertIn("_format_sse_oversize_drop_payload(", oversize_branch)
        self.assertNotIn("json.dumps(data", oversize_branch)

    def test_emit_does_not_json_encode_metadata_dict(self) -> None:
        original_dumps = json.dumps
        dumped_types: list[type[object]] = []
        bus = _SSEBus()
        q = bus.subscribe()

        def dumps_spy(obj: Any, *args: Any, **kwargs: Any) -> str:
            dumped_types.append(type(obj))
            return original_dumps(obj, *args, **kwargs)

        with patch.object(task_module.json, "dumps", side_effect=dumps_spy):
            bus.emit('task_"changed"\n中文', {"b": "x" * (300 * 1024)})

        evt = q.get_nowait()
        self.assertEqual(evt["type"], "oversize_drop")
        self.assertEqual(evt["data"]["original_event_type"], 'task_"changed"\n中文')
        self.assertEqual(json.loads(evt["_serialized"]), evt["data"])
        self.assertEqual(dumped_types, [dict, str])


if __name__ == "__main__":
    unittest.main()
