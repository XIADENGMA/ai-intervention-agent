from __future__ import annotations

import inspect
from collections import UserDict
from typing import Any, cast

from ai_intervention_agent.notification_manager import NotificationManager


def test_status_provider_stats_uses_dict_copy_for_inner_snapshots() -> None:
    source = inspect.getsource(NotificationManager.get_status)

    assert "k: v.copy() if isinstance(v, dict) else dict(v)" in source
    assert "{k: dict(v) for k, v in providers_stats_raw.items()}" not in source


def test_status_provider_stats_copy_does_not_pollute_internal_state() -> None:
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
    web_stats = cast(dict[str, Any], status["stats"]["providers"]["web"])
    web_stats["success"] = 0
    web_stats["injected"] = True

    with manager._stats_lock:
        internal_web_stats = manager._stats["providers"]["web"]
        assert internal_web_stats["success"] == 8
        assert "injected" not in internal_web_stats


def test_status_provider_stats_still_accepts_non_dict_mapping() -> None:
    manager = NotificationManager._create_test_instance()
    with manager._stats_lock:
        manager._stats["providers"] = {
            "web": UserDict(
                {
                    "attempts": 4,
                    "success": 3,
                    "failure": 1,
                    "latency_ms_total": 80,
                    "latency_ms_count": 4,
                }
            )
        }

    status = manager.get_status()
    web_stats = cast(dict[str, Any], status["stats"]["providers"]["web"])

    assert isinstance(web_stats, dict)
    assert web_stats["attempts"] == 4
    assert web_stats["success_rate"] == 0.75
    assert web_stats["avg_latency_ms"] == 20.0
