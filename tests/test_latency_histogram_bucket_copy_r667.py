"""R667 - latency histogram snapshot bucket copies use dict.copy()."""

from __future__ import annotations

import inspect

from ai_intervention_agent import mcp_tool_call_metrics as mtcm
from ai_intervention_agent.notification_manager import (
    _NOTIFICATION_LATENCY_INF_BUCKET,
    NotificationManager,
)


def teardown_function() -> None:
    mtcm.reset_mcp_tool_call_stats()


def test_mcp_latency_snapshot_uses_bucket_copy_method() -> None:
    source = inspect.getsource(mtcm.get_mcp_tool_call_latency_snapshot)

    assert 'buckets_copy = state["buckets"].copy()' in source
    assert 'buckets_copy = dict(state["buckets"])' not in source


def test_notification_latency_snapshot_uses_bucket_copy_method() -> None:
    source = inspect.getsource(
        NotificationManager.get_provider_latency_histograms_snapshot
    )

    assert 'buckets_copy = state["buckets"].copy()' in source
    assert 'buckets_copy = dict(state["buckets"])' not in source


def test_mcp_latency_snapshot_bucket_copy_remains_isolated() -> None:
    with mtcm._counter_lock:
        mtcm._record_latency("interactive_feedback", "success", 0.5)

    snapshot = mtcm.get_mcp_tool_call_latency_snapshot()
    state = snapshot[("interactive_feedback", "success")]
    finite_bucket = mtcm._DEFAULT_LATENCY_BUCKETS[1]
    state["buckets"][finite_bucket] = 999
    state["buckets"][mtcm._MCP_LATENCY_INF_BUCKET] = 999

    fresh_state = mtcm.get_mcp_tool_call_latency_snapshot()[
        ("interactive_feedback", "success")
    ]
    assert fresh_state["buckets"][finite_bucket] == 1
    assert fresh_state["buckets"][mtcm._MCP_LATENCY_INF_BUCKET] == 1


def test_notification_latency_snapshot_bucket_copy_remains_isolated() -> None:
    manager = NotificationManager._create_test_instance()
    with manager._stats_lock:
        manager._record_provider_latency_bucket("web", 0.5)

    snapshot = manager.get_provider_latency_histograms_snapshot()
    state = snapshot["web"]
    finite_bucket = manager._DEFAULT_LATENCY_BUCKETS_SECONDS[3]
    state["buckets"][finite_bucket] = 999
    state["buckets"][_NOTIFICATION_LATENCY_INF_BUCKET] = 999

    fresh_state = manager.get_provider_latency_histograms_snapshot()["web"]
    assert fresh_state["buckets"][finite_bucket] == 1
    assert fresh_state["buckets"][_NOTIFICATION_LATENCY_INF_BUCKET] == 1
