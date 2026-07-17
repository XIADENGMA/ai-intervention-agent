"""R629 - cached sorted SSE event type tuple."""

from __future__ import annotations

import inspect
from pathlib import Path

from ai_intervention_agent import sse_event_schemas
from ai_intervention_agent.sse_event_schemas import EVENT_SCHEMAS, get_known_event_types

MODULE_PATH = Path(sse_event_schemas.__file__).resolve()


def test_known_event_types_are_sorted_tuple_and_reused() -> None:
    known_types = get_known_event_types()

    assert isinstance(known_types, tuple)
    assert known_types == tuple(sorted(EVENT_SCHEMAS))
    assert get_known_event_types() is known_types


def test_known_event_types_accessor_uses_cached_tuple() -> None:
    module_source = MODULE_PATH.read_text(encoding="utf-8")
    accessor_source = inspect.getsource(get_known_event_types)

    assert "_KNOWN_EVENT_TYPES: tuple[str, ...] = tuple(sorted(EVENT_SCHEMAS))" in (
        module_source
    )
    assert "return _KNOWN_EVENT_TYPES" in accessor_source
    assert "sorted(EVENT_SCHEMAS)" not in accessor_source
