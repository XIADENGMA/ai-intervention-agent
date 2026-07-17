"""R648 - Notification status stats snapshot uses copy/pop."""

from __future__ import annotations

import inspect

from ai_intervention_agent.notification_manager import NotificationManager


def test_status_stats_snapshot_uses_copy_pop_before_provider_copy() -> None:
    source = inspect.getsource(NotificationManager.get_status)

    copy_idx = source.index("stats_snapshot = self._stats.copy()")
    pop_idx = source.index(
        'providers_stats_raw = stats_snapshot.pop("providers", None)'
    )
    provider_copy_idx = source.index('stats_snapshot["providers"] = providers_stats')

    assert copy_idx < pop_idx < provider_copy_idx
    assert 'if k != "providers"' not in source


def test_status_provider_stats_remain_defensive_copy() -> None:
    manager = NotificationManager._create_test_instance()
    with manager._stats_lock:
        manager._stats["providers"] = {
            "web": {
                "attempts": 10,
                "success": 8,
                "failure": 2,
                "latency_ms_total": 500,
                "latency_ms_count": 10,
            }
        }

    status = manager.get_status()
    web_stats = status["stats"]["providers"]["web"]
    web_stats["success"] = 0
    web_stats["injected"] = True

    with manager._stats_lock:
        internal_web_stats = manager._stats["providers"]["web"]
        assert internal_web_stats["success"] == 8
        assert "injected" not in internal_web_stats


def test_status_missing_provider_stats_still_returns_empty_provider_snapshot() -> None:
    manager = NotificationManager._create_test_instance()
    with manager._stats_lock:
        manager._stats.pop("providers", None)

    status = manager.get_status()

    assert status["stats"]["providers"] == {}
    assert "events_total" in status["stats"]
