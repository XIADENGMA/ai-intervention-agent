"""R631 - SSE latency singleton snapshot avoids list materialization."""

from __future__ import annotations

import inspect
from typing import Any, cast

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _SingletonLatencySamples:
    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> int:
        if index != 0:
            raise IndexError(index)
        return 5_123_456

    def __iter__(self) -> Any:
        raise AssertionError("singleton latency snapshot must not iterate samples")


def test_singleton_latency_snapshot_uses_direct_index_without_iterating() -> None:
    bus = _SSEBus()
    cast(Any, bus)._latency_samples_ns = _SingletonLatencySamples()

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 5.12,
        "p95_ms": 5.12,
        "count": 1,
    }


def test_larger_latency_snapshot_still_sorts_snapshot() -> None:
    bus = _SSEBus()
    bus.record_emit_to_deliver_latency_ns(5_000_000)
    bus.record_emit_to_deliver_latency_ns(1_000_000)
    bus.record_emit_to_deliver_latency_ns(4_000_000)
    bus.record_emit_to_deliver_latency_ns(2_000_000)
    bus.record_emit_to_deliver_latency_ns(3_000_000)

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 3.0,
        "p95_ms": 5.0,
        "count": 5,
    }


def test_latency_snapshot_source_checks_singleton_before_list_snapshot() -> None:
    source = inspect.getsource(_SSEBus._compute_latency_snapshot)

    singleton_idx = source.index("if count == 1:")
    direct_index_idx = source.index("samples_ns[0]")
    singleton_return_idx = source.index(
        'return {"p50_ms": sample_ms, "p95_ms": sample_ms, "count": 1}'
    )
    list_idx = source.index("samples = list(samples_ns)")

    assert singleton_idx < direct_index_idx < singleton_return_idx < list_idx
