"""R640 - singleton SSE emit-by-type Prometheus samples avoid sorting."""

from __future__ import annotations

import inspect
from typing import Any

from ai_intervention_agent.web_ui_routes import system as system_module


class _SingletonEmitByTypeNoKeyIter(dict[str, int]):
    def __iter__(self) -> Any:
        raise AssertionError("singleton emit_by_type path must not call sorted(dict)")


def test_singleton_emit_by_type_sample_does_not_sort_keys() -> None:
    samples = list(
        system_module._iter_sse_emit_by_type_samples(
            _SingletonEmitByTypeNoKeyIter({"task_changed": 7})
        )
    )

    assert samples == [({"event_type": "task_changed"}, 7)]


def test_singleton_emit_by_type_filters_non_numeric_count() -> None:
    samples = list(system_module._iter_sse_emit_by_type_samples({"task_changed": "7"}))

    assert samples == []


def test_multi_emit_by_type_sample_still_sorts_for_deterministic_output() -> None:
    samples = list(
        system_module._iter_sse_emit_by_type_samples(
            {"task_changed": 2, "config_changed": 1}
        )
    )

    assert samples == [
        ({"event_type": "config_changed"}, 1),
        ({"event_type": "task_changed"}, 2),
    ]


def test_singleton_fastpath_source_precedes_sorted_multi_key_path() -> None:
    source = inspect.getsource(system_module._iter_sse_emit_by_type_samples)

    singleton_idx = source.index("if len(emit_by_type) == 1:")
    item_iter_idx = source.index("event_type, count = next(iter(emit_by_type.items()))")
    return_idx = source.index("return")
    sorted_idx = source.index("for event_type in sorted(emit_by_type):")

    assert singleton_idx < item_iter_idx < return_idx < sorted_idx
    assert "sorted(emit_by_type.items())" not in source
