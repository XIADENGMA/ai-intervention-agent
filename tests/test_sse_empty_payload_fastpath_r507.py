"""R507 - SSE empty payloads bypass generic JSON serialization."""

from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import patch

from ai_intervention_agent.web_ui_routes import task as task_module
from ai_intervention_agent.web_ui_routes.task import _serialize_sse_payload, _SSEBus


class TestSseEmptyPayloadFastPathSource(unittest.TestCase):
    def test_emit_uses_dedicated_payload_serializer(self) -> None:
        source = inspect.getsource(_SSEBus.emit)

        self.assertIn("data, serialized_data = _serialize_sse_payload(data)", source)
        self.assertNotIn("json.dumps(data or {}", source)

    def test_serializer_has_empty_json_fast_path_before_dumps(self) -> None:
        source = inspect.getsource(_serialize_sse_payload)

        self.assertIn("_SSE_EMPTY_JSON", source)
        self.assertLess(source.index("_SSE_EMPTY_JSON"), source.index("json.dumps("))


class TestSseEmptyPayloadFastPathBehavior(unittest.TestCase):
    def test_emit_none_payload_reuses_empty_json_without_dumps(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()

        with patch.object(
            task_module.json,
            "dumps",
            side_effect=AssertionError("empty payload should not use json.dumps"),
        ):
            bus.emit("heartbeat", None)

        payload = q.get_nowait()
        self.assertEqual(payload["data"], {})
        self.assertEqual(payload["_serialized"], "{}")

    def test_emit_empty_dict_payload_reuses_empty_json_without_dumps(self) -> None:
        bus = _SSEBus()
        q = bus.subscribe()

        with patch.object(
            task_module.json,
            "dumps",
            side_effect=AssertionError("empty payload should not use json.dumps"),
        ):
            bus.emit("task_changed", {})

        payload = q.get_nowait()
        self.assertEqual(payload["data"], {})
        self.assertEqual(payload["_serialized"], "{}")

    def test_non_empty_payload_still_uses_json_dumps_ensure_ascii_false(self) -> None:
        original_dumps = json.dumps
        bus = _SSEBus()
        q = bus.subscribe()

        with patch.object(
            task_module.json,
            "dumps",
            wraps=original_dumps,
        ) as dumps_spy:
            bus.emit("task_changed", {"prompt": "中文"})

        payload = q.get_nowait()
        self.assertEqual(payload["_serialized"], '{"prompt": "中文"}')
        dumps_spy.assert_called_once_with({"prompt": "中文"}, ensure_ascii=False)

    def test_non_serializable_non_empty_payload_still_falls_back_to_none(self) -> None:
        circular: dict[str, object] = {}
        circular["self"] = circular

        payload_data, serialized = _serialize_sse_payload(circular)

        self.assertIs(payload_data, circular)
        self.assertIsNone(serialized)


if __name__ == "__main__":
    unittest.main()
