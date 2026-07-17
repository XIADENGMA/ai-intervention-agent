"""R649 - Notification latency snapshot reuses the +Inf bucket key."""

from __future__ import annotations

import inspect

from ai_intervention_agent.notification_manager import (
    _NOTIFICATION_LATENCY_INF_BUCKET,
    NotificationManager,
)


def test_provider_latency_snapshot_uses_module_inf_bucket_constant() -> None:
    source = inspect.getsource(
        NotificationManager.get_provider_latency_histograms_snapshot
    )

    assert 'buckets_copy[_NOTIFICATION_LATENCY_INF_BUCKET] = state["count"]' in source
    assert 'buckets_copy[float("inf")]' not in source


def test_provider_latency_snapshot_reuses_inf_bucket_key_object() -> None:
    manager = NotificationManager._create_test_instance()
    with manager._stats_lock:
        manager._record_provider_latency_bucket("web", 0.5)

    snapshot = manager.get_provider_latency_histograms_snapshot()
    buckets = snapshot["web"]["buckets"]

    assert buckets[float("inf")] == snapshot["web"]["count"] == 1
    assert any(key is _NOTIFICATION_LATENCY_INF_BUCKET for key in buckets)


def test_provider_latency_snapshot_remains_deep_copy() -> None:
    manager = NotificationManager._create_test_instance()
    with manager._stats_lock:
        manager._record_provider_latency_bucket("web", 0.5)

    snapshot = manager.get_provider_latency_histograms_snapshot()
    snapshot["web"]["count"] = 999
    snapshot["web"]["buckets"][_NOTIFICATION_LATENCY_INF_BUCKET] = 999

    fresh_snapshot = manager.get_provider_latency_histograms_snapshot()
    assert fresh_snapshot["web"]["count"] == 1
    assert fresh_snapshot["web"]["buckets"][float("inf")] == 1
