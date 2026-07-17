"""R502 - SSE oversize ASCII exact-size fast path."""

from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import patch

from ai_intervention_agent.web_ui_routes.task import (
    _sse_serialized_utf8_exceeds_limit,
    _SSEBus,
)


class TestSseAsciiLimitFastPathSource(unittest.TestCase):
    def test_helper_uses_isascii_before_encoding_near_threshold(self) -> None:
        source = inspect.getsource(_sse_serialized_utf8_exceeds_limit)

        self.assertIn("serialized.isascii()", source)
        self.assertLess(
            source.index("serialized.isascii()"),
            source.index('serialized.encode("utf-8")'),
        )


class TestSseAsciiLimitFastPathBehavior(unittest.TestCase):
    def test_ascii_under_limit_returns_exact_character_count(self) -> None:
        payload = "a" * 60

        self.assertEqual(
            _sse_serialized_utf8_exceeds_limit(payload, 64),
            (False, 60),
        )

    def test_ascii_over_limit_returns_exact_character_count(self) -> None:
        payload = "a" * 65

        self.assertEqual(
            _sse_serialized_utf8_exceeds_limit(payload, 64),
            (True, 65),
        )

    def test_non_ascii_near_threshold_still_uses_exact_utf8_size(self) -> None:
        payload = "a" * 20 + "中" * 3
        exact_size = len(payload.encode("utf-8"))

        self.assertEqual(
            _sse_serialized_utf8_exceeds_limit(payload, exact_size - 1),
            (True, exact_size),
        )

    def test_emit_preserves_exact_ascii_oversize_metadata(self) -> None:
        data = {"msg": "x" * 80}
        serialized = json.dumps(data, ensure_ascii=False)
        exact_size = len(serialized)
        bus = _SSEBus()
        q = bus.subscribe()

        with patch.object(_SSEBus, "_OVERSIZE_LIMIT_BYTES", exact_size - 1):
            bus.emit("task_changed", data)

        evt = q.get_nowait()
        self.assertEqual(evt["type"], "oversize_drop")
        self.assertEqual(evt["data"]["size_bytes"], exact_size)
        self.assertEqual(evt["data"]["limit_bytes"], exact_size - 1)


if __name__ == "__main__":
    unittest.main()
