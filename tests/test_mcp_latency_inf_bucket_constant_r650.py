"""R650 - MCP latency snapshot reuses the +Inf bucket key."""

from __future__ import annotations

import inspect

from ai_intervention_agent import mcp_tool_call_metrics as mtcm


def teardown_function() -> None:
    mtcm.reset_mcp_tool_call_stats()


def test_mcp_latency_snapshot_uses_module_inf_bucket_constant() -> None:
    source = inspect.getsource(mtcm.get_mcp_tool_call_latency_snapshot)

    assert 'buckets_copy[_MCP_LATENCY_INF_BUCKET] = state["count"]' in source
    assert 'buckets_copy[float("inf")]' not in source


def test_mcp_latency_snapshot_reuses_inf_bucket_key_object() -> None:
    with mtcm._counter_lock:
        mtcm._record_latency("interactive_feedback", "success", 0.5)

    snapshot = mtcm.get_mcp_tool_call_latency_snapshot()
    buckets = snapshot[("interactive_feedback", "success")]["buckets"]

    assert buckets[float("inf")] == 1
    assert any(key is mtcm._MCP_LATENCY_INF_BUCKET for key in buckets)


def test_mcp_latency_snapshot_remains_deep_copy() -> None:
    with mtcm._counter_lock:
        mtcm._record_latency("interactive_feedback", "success", 0.5)

    snapshot = mtcm.get_mcp_tool_call_latency_snapshot()
    snapshot[("interactive_feedback", "success")]["count"] = 999
    snapshot[("interactive_feedback", "success")]["buckets"][
        mtcm._MCP_LATENCY_INF_BUCKET
    ] = 999

    fresh_snapshot = mtcm.get_mcp_tool_call_latency_snapshot()
    assert fresh_snapshot[("interactive_feedback", "success")]["count"] == 1
    assert (
        fresh_snapshot[("interactive_feedback", "success")]["buckets"][float("inf")]
        == 1
    )
