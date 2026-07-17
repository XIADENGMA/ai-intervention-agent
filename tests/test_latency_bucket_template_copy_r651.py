"""R651 - latency histogram state creation copies zeroed bucket templates."""

from __future__ import annotations

import inspect

from ai_intervention_agent import mcp_tool_call_metrics as mtcm
from ai_intervention_agent.notification_manager import NotificationManager


def teardown_function() -> None:
    mtcm.reset_mcp_tool_call_stats()


def test_mcp_latency_state_creation_copies_zero_bucket_template() -> None:
    source = inspect.getsource(mtcm._record_latency)

    assert '"buckets": _DEFAULT_LATENCY_BUCKET_COUNTS.copy()' in source
    assert "dict.fromkeys(_DEFAULT_LATENCY_BUCKETS, 0)" not in source


def test_mcp_latency_bucket_template_is_not_aliased_by_series_state() -> None:
    with mtcm._counter_lock:
        mtcm._record_latency("tool_a", "success", 0.5)
        first_buckets = mtcm._latency_state[("tool_a", "success")]["buckets"]
        first_buckets[mtcm._DEFAULT_LATENCY_BUCKETS[0]] = 999
        mtcm._record_latency("tool_b", "success", 99999.0)
        second_buckets = mtcm._latency_state[("tool_b", "success")]["buckets"]

    assert first_buckets is not mtcm._DEFAULT_LATENCY_BUCKET_COUNTS
    assert second_buckets is not mtcm._DEFAULT_LATENCY_BUCKET_COUNTS
    assert second_buckets[mtcm._DEFAULT_LATENCY_BUCKETS[0]] == 0


def test_notification_latency_state_creation_copies_zero_bucket_template() -> None:
    source = inspect.getsource(NotificationManager._record_provider_latency_bucket)

    assert '"buckets": self._DEFAULT_LATENCY_BUCKET_COUNTS.copy()' in source
    assert "dict.fromkeys(self._DEFAULT_LATENCY_BUCKETS_SECONDS, 0)" not in source


def test_notification_latency_bucket_template_is_not_aliased_by_provider_state() -> (
    None
):
    manager = NotificationManager._create_test_instance()
    with manager._stats_lock:
        manager._record_provider_latency_bucket("web", 0.5)
        first_buckets = manager._provider_latency_histograms["web"]["buckets"]
        first_buckets[manager._DEFAULT_LATENCY_BUCKETS_SECONDS[0]] = 999
        manager._record_provider_latency_bucket("bark", 99999.0)
        second_buckets = manager._provider_latency_histograms["bark"]["buckets"]

    assert first_buckets is not manager._DEFAULT_LATENCY_BUCKET_COUNTS
    assert second_buckets is not manager._DEFAULT_LATENCY_BUCKET_COUNTS
    assert second_buckets[manager._DEFAULT_LATENCY_BUCKETS_SECONDS[0]] == 0
