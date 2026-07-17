"""R501 - SSE oversize UTF-8 byte-size fast path.

The oversize guard must compare serialized SSE payloads by UTF-8 bytes, but the
common small-event path should not allocate ``serialized.encode("utf-8")`` just
to prove the payload is below a 256 KiB limit.
"""

from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import patch

from ai_intervention_agent.web_ui_routes.task import (
    _sse_serialized_utf8_exceeds_limit,
    _SSEBus,
)


class TestSseUtf8LimitFastPathSource(unittest.TestCase):
    def test_emit_uses_helper_instead_of_inline_encode_len(self) -> None:
        emit_src = inspect.getsource(_SSEBus.emit)

        self.assertIn("_sse_serialized_utf8_exceeds_limit(", emit_src)
        self.assertNotIn('serialized_data.encode("utf-8")', emit_src)

    def test_helper_keeps_utf8_four_byte_upper_bound(self) -> None:
        helper_src = inspect.getsource(_sse_serialized_utf8_exceeds_limit)

        self.assertIn("char_count * 4 <= limit", helper_src)
        self.assertIn('serialized.encode("utf-8")', helper_src)


class TestSseUtf8LimitFastPathBehavior(unittest.TestCase):
    def test_small_ascii_payload_is_proven_under_limit_without_exact_path(self) -> None:
        self.assertEqual(
            _sse_serialized_utf8_exceeds_limit("abc", 16),
            (False, 3),
        )

    def test_small_non_ascii_payload_can_use_upper_bound_fast_path(self) -> None:
        exceeds, size_hint = _sse_serialized_utf8_exceeds_limit("中", 4)

        self.assertFalse(exceeds)
        self.assertEqual(size_hint, 1)
        self.assertEqual(len("中".encode()), 3)

    def test_ascii_near_threshold_uses_exact_size(self) -> None:
        exceeds, exact_size = _sse_serialized_utf8_exceeds_limit("a" * 17, 16)

        self.assertTrue(exceeds)
        self.assertEqual(exact_size, 17)

    def test_non_ascii_boundary_uses_exact_utf8_size(self) -> None:
        serialized = json.dumps({"emoji": "😀" * 3}, ensure_ascii=False)
        exact_size = len(serialized.encode("utf-8"))

        self.assertEqual(
            _sse_serialized_utf8_exceeds_limit(serialized, exact_size),
            (False, exact_size),
        )
        self.assertEqual(
            _sse_serialized_utf8_exceeds_limit(serialized, exact_size - 1),
            (True, exact_size),
        )

    def test_emit_preserves_exact_oversize_metadata_for_non_ascii_payload(self) -> None:
        data = {"msg": "😀" * 6}
        serialized = json.dumps(data, ensure_ascii=False)
        exact_size = len(serialized.encode("utf-8"))
        bus = _SSEBus()
        q = bus.subscribe()

        with patch.object(_SSEBus, "_OVERSIZE_LIMIT_BYTES", exact_size - 1):
            bus.emit("task_changed", data)

        evt = q.get_nowait()
        self.assertEqual(evt["type"], "oversize_drop")
        self.assertEqual(evt["data"]["original_event_type"], "task_changed")
        self.assertEqual(evt["data"]["size_bytes"], exact_size)
        self.assertEqual(evt["data"]["limit_bytes"], exact_size - 1)


if __name__ == "__main__":
    unittest.main()
