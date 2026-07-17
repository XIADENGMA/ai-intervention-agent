"""R635 - SSE latency snapshot caches the sample deque locally."""

from __future__ import annotations

import inspect

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _LatencyAttrCountingSSEBus(_SSEBus):
    def __init__(self) -> None:
        super().__init__()
        self.latency_attr_reads = 0

    def __getattribute__(self, name: str) -> object:
        if name == "_latency_samples_ns":
            reads = object.__getattribute__(self, "latency_attr_reads")
            object.__setattr__(self, "latency_attr_reads", reads + 1)
        return super().__getattribute__(name)


def test_small_latency_snapshot_reads_samples_attr_once() -> None:
    bus = _LatencyAttrCountingSSEBus()
    bus.record_emit_to_deliver_latency_ns(4_000_000)
    bus.record_emit_to_deliver_latency_ns(1_000_000)
    bus.record_emit_to_deliver_latency_ns(3_000_000)
    bus.record_emit_to_deliver_latency_ns(2_000_000)
    bus.latency_attr_reads = 0

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 3.0,
        "p95_ms": 4.0,
        "count": 4,
    }
    assert bus.latency_attr_reads == 1


def test_larger_latency_snapshot_reads_samples_attr_once() -> None:
    bus = _LatencyAttrCountingSSEBus()
    bus.record_emit_to_deliver_latency_ns(5_000_000)
    bus.record_emit_to_deliver_latency_ns(1_000_000)
    bus.record_emit_to_deliver_latency_ns(4_000_000)
    bus.record_emit_to_deliver_latency_ns(2_000_000)
    bus.record_emit_to_deliver_latency_ns(3_000_000)
    bus.latency_attr_reads = 0

    assert bus._compute_latency_snapshot() == {
        "p50_ms": 3.0,
        "p95_ms": 5.0,
        "count": 5,
    }
    assert bus.latency_attr_reads == 1


def test_latency_snapshot_source_binds_samples_attr_once() -> None:
    source = inspect.getsource(_SSEBus._compute_latency_snapshot)

    local_idx = source.index("samples_ns = self._latency_samples_ns")
    count_idx = source.index("count = len(samples_ns)")
    list_idx = source.index("samples = list(samples_ns)")

    assert local_idx < count_idx < list_idx
    assert source.count("self._latency_samples_ns") == 1
