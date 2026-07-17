"""R634 - SSE latency four-sample snapshot avoids list materialization."""

from __future__ import annotations

import inspect
from typing import Any, cast

import pytest

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _QuadLatencySamples:
    def __len__(self) -> int:
        return 4

    def __getitem__(self, index: int) -> int:
        if index == 0:
            return 2_000_000
        if index == 1:
            return 9_000_000
        if index == 2:
            return 1_000_000
        if index == 3:
            return 5_123_456
        raise IndexError(index)

    def __iter__(self) -> Any:
        raise AssertionError("four-sample latency snapshot must not iterate samples")


def test_quad_latency_snapshot_uses_direct_indices_without_iterating() -> None:
    bus = _SSEBus()
    cast(Any, bus)._latency_samples_ns = _QuadLatencySamples()

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 5.12,
        "p95_ms": 9.0,
        "count": 4,
    }


@pytest.mark.parametrize(
    ("samples", "expected_p50_ms", "expected_p95_ms"),
    [
        ([1_000_000, 2_000_000, 3_000_000, 4_000_000], 3.0, 4.0),
        ([4_000_000, 3_000_000, 2_000_000, 1_000_000], 3.0, 4.0),
        ([2_000_000, 4_000_000, 1_000_000, 3_000_000], 3.0, 4.0),
        ([4_000_000, 1_000_000, 4_000_000, 2_000_000], 4.0, 4.0),
        ([2_000_000, 2_000_000, 1_000_000, 3_000_000], 2.0, 3.0),
    ],
)
def test_quad_latency_snapshot_matches_sorted_behavior_for_edges(
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
        "count": 4,
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


def test_latency_snapshot_source_checks_quad_before_list_snapshot() -> None:
    source = inspect.getsource(_SSEBus._compute_latency_snapshot)

    quad_idx = source.index("if count == 4:")
    first_idx = source.index("first_sample = samples_ns[0]", quad_idx)
    second_idx = source.index("second_sample = samples_ns[1]", quad_idx)
    third_idx = source.index("third_sample = samples_ns[2]", quad_idx)
    fourth_idx = source.index("fourth_sample = samples_ns[3]")
    pair_idx = source.index("if first_sample >= second_sample:")
    branch_idx = source.index("if pair_a_high >= pair_b_high:")
    quad_return_idx = source.index(
        'return {"p50_ms": p50_ms, "p95_ms": p95_ms, "count": 4}'
    )
    list_idx = source.index("samples = list(samples_ns)")

    assert (
        quad_idx
        < first_idx
        < second_idx
        < third_idx
        < fourth_idx
        < pair_idx
        < branch_idx
        < quad_return_idx
        < list_idx
    )
