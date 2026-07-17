"""R632 - SSE latency two-sample snapshot avoids list materialization."""

from __future__ import annotations

import inspect
from typing import Any, cast

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _PairLatencySamples:
    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> int:
        if index == 0:
            return 1_000_000
        if index == 1:
            return 5_123_456
        raise IndexError(index)

    def __iter__(self) -> Any:
        raise AssertionError("two-sample latency snapshot must not iterate samples")


def test_pair_latency_snapshot_uses_direct_indices_without_iterating() -> None:
    bus = _SSEBus()
    cast(Any, bus)._latency_samples_ns = _PairLatencySamples()

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 5.12,
        "p95_ms": 5.12,
        "count": 2,
    }


def test_pair_latency_snapshot_matches_sorted_behavior_when_reversed() -> None:
    bus = _SSEBus()
    bus.record_emit_to_deliver_latency_ns(5_123_456)
    bus.record_emit_to_deliver_latency_ns(1_000_000)

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 5.12,
        "p95_ms": 5.12,
        "count": 2,
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


def test_latency_snapshot_source_checks_pair_before_list_snapshot() -> None:
    source = inspect.getsource(_SSEBus._compute_latency_snapshot)

    pair_idx = source.index("if count == 2:")
    first_idx = source.index("first_sample = samples_ns[0]")
    second_idx = source.index("second_sample = samples_ns[1]")
    compare_idx = source.index("first_sample if first_sample >= second_sample")
    pair_return_idx = source.index(
        'return {"p50_ms": sample_ms, "p95_ms": sample_ms, "count": 2}'
    )
    list_idx = source.index("samples = list(samples_ns)")

    assert pair_idx < first_idx < second_idx < compare_idx < pair_return_idx < list_idx
