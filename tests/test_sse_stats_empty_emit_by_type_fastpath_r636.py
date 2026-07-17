"""R636 - empty SSE emit_by_type snapshot avoids Counter copy."""

from __future__ import annotations

import inspect
from typing import Any, cast

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _EmptyEmitByTypeNoIter:
    def __bool__(self) -> bool:
        return False

    def __iter__(self) -> Any:
        raise AssertionError("empty emit_by_type snapshot must not iterate")

    def keys(self) -> Any:
        raise AssertionError("empty emit_by_type snapshot must not inspect keys")

    def items(self) -> Any:
        raise AssertionError("empty emit_by_type snapshot must not inspect items")


def test_empty_emit_by_type_snapshot_does_not_iterate_counter() -> None:
    bus = _SSEBus()
    cast(Any, bus)._emit_by_type = _EmptyEmitByTypeNoIter()

    snap = bus.stats_snapshot()

    assert snap["emit_by_type"] == {}


def test_empty_emit_by_type_snapshot_returns_fresh_dict() -> None:
    bus = _SSEBus()

    first = bus.stats_snapshot()["emit_by_type"]
    first["task_changed"] = 999
    second = bus.stats_snapshot()["emit_by_type"]

    assert second == {}


def test_non_empty_emit_by_type_snapshot_is_still_defensive_copy() -> None:
    bus = _SSEBus()
    bus.emit("task_changed", {"task_id": "r636"})

    first = bus.stats_snapshot()["emit_by_type"]
    first["task_changed"] = 999
    second = bus.stats_snapshot()["emit_by_type"]

    assert second["task_changed"] == 1


def test_stats_snapshot_source_checks_empty_emit_by_type_fastpath() -> None:
    source = inspect.getsource(_SSEBus.stats_snapshot)

    fastpath_idx = source.index(
        "emit_by_type = dict(self._emit_by_type) if self._emit_by_type else {}"
    )
    return_idx = source.index('"emit_by_type": emit_by_type')

    assert fastpath_idx < return_idx
    assert '"emit_by_type": dict(self._emit_by_type)' not in source
