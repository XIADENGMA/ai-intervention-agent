"""R630 - SSE latency empty snapshot avoids list materialization."""

from __future__ import annotations

import inspect
from typing import Any, cast

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _EmptyLatencySamples:
    def __len__(self) -> int:
        return 0

    def __iter__(self) -> Any:
        raise AssertionError("empty latency snapshot must not iterate samples")


def test_empty_latency_snapshot_uses_len_without_iterating() -> None:
    bus = _SSEBus()
    cast(Any, bus)._latency_samples_ns = _EmptyLatencySamples()

    assert bus._compute_latency_snapshot() == {
        "p50_ms": None,
        "p95_ms": None,
        "count": 0,
    }


def test_non_empty_latency_snapshot_behavior_is_unchanged() -> None:
    bus = _SSEBus()
    bus.record_emit_to_deliver_latency_ns(3_000_000)
    bus.record_emit_to_deliver_latency_ns(1_000_000)

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 3.0,
        "p95_ms": 3.0,
        "count": 2,
    }


def test_latency_snapshot_source_checks_len_before_list_snapshot() -> None:
    source = inspect.getsource(_SSEBus._compute_latency_snapshot)

    local_idx = source.index("samples_ns = self._latency_samples_ns")
    count_idx = source.index("count = len(samples_ns)")
    empty_return_idx = source.index(
        'return {"p50_ms": None, "p95_ms": None, "count": 0}'
    )
    list_idx = source.index("samples = list(samples_ns)")

    assert local_idx < count_idx < empty_return_idx < list_idx
    assert "count = len(samples)" not in source
