"""R633 - SSE latency three-sample snapshot avoids list materialization."""

from __future__ import annotations

import inspect
from typing import Any, cast

import pytest

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _TripleLatencySamples:
    def __len__(self) -> int:
        return 3

    def __getitem__(self, index: int) -> int:
        if index == 0:
            return 9_000_000
        if index == 1:
            return 1_000_000
        if index == 2:
            return 5_123_456
        raise IndexError(index)

    def __iter__(self) -> Any:
        raise AssertionError("three-sample latency snapshot must not iterate samples")


def test_triple_latency_snapshot_uses_direct_indices_without_iterating() -> None:
    bus = _SSEBus()
    cast(Any, bus)._latency_samples_ns = _TripleLatencySamples()

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 5.12,
        "p95_ms": 9.0,
        "count": 3,
    }


@pytest.mark.parametrize(
    ("samples", "expected_p50_ms", "expected_p95_ms"),
    [
        ([1_000_000, 2_000_000, 3_000_000], 2.0, 3.0),
        ([3_000_000, 2_000_000, 1_000_000], 2.0, 3.0),
        ([2_000_000, 1_000_000, 2_000_000], 2.0, 2.0),
        ([3_000_000, 1_000_000, 3_000_000], 3.0, 3.0),
    ],
)
def test_triple_latency_snapshot_matches_sorted_behavior_for_edges(
    samples: list[int],
    expected_p50_ms: float,
    expected_p95_ms: float,
) -> None:
    bus = _SSEBus()
    for sample in samples:
        bus.record_emit_to_deliver_latency_ns(sample)

    assert bus._compute_latency_snapshot() == {
        "p50_ms": expected_p50_ms,
        "p95_ms": expected_p95_ms,
        "count": 3,
    }


def test_five_sample_latency_snapshot_still_sorts_snapshot() -> None:
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


def test_latency_snapshot_source_checks_triple_before_list_snapshot() -> None:
    source = inspect.getsource(_SSEBus._compute_latency_snapshot)

    triple_idx = source.index("if count == 3:")
    first_idx = source.index("first_sample = samples_ns[0]", triple_idx)
    second_idx = source.index("second_sample = samples_ns[1]", triple_idx)
    third_idx = source.index("third_sample = samples_ns[2]")
    compare_idx = source.index("if first_sample <= second_sample:")
    branch_idx = source.index("elif third_sample >= high_sample:")
    triple_return_idx = source.index(
        'return {"p50_ms": p50_ms, "p95_ms": p95_ms, "count": 3}'
    )
    list_idx = source.index("samples = list(samples_ns)")

    assert (
        triple_idx
        < first_idx
        < second_idx
        < third_idx
        < compare_idx
        < branch_idx
        < triple_return_idx
        < list_idx
    )
