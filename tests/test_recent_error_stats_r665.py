from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch

from ai_intervention_agent import enhanced_logging
from ai_intervention_agent.web_ui_routes import system


def _populate_ring() -> None:
    enhanced_logging.clear_recent_logs()
    with enhanced_logging._log_ring_lock:
        enhanced_logging._log_ring.extend(
            [
                {
                    "ts_unix": 100,
                    "level_no": 40,
                    "level_name": "ERROR",
                    "logger_name": "test",
                    "message": "old error",
                },
                {
                    "ts_unix": 370,
                    "level_no": 30,
                    "level_name": "WARNING",
                    "logger_name": "test",
                    "message": "recent warning",
                },
                {
                    "ts_unix": 390,
                    "level_no": 40,
                    "level_name": "ERROR",
                    "logger_name": "test",
                    "message": "recent error",
                },
                {
                    "ts_unix": 395,
                    "level_no": 50,
                    "level_name": "CRITICAL",
                    "logger_name": "test",
                    "message": "recent critical",
                },
            ]
        )


def test_recent_error_stats_counts_errors_without_recent_log_snapshot(
    monkeypatch: Any,
) -> None:
    _populate_ring()

    def fail_get_recent_logs(limit: int | None = None) -> list[dict[str, Any]]:
        raise AssertionError(f"unexpected get_recent_logs({limit!r})")

    monkeypatch.setattr(enhanced_logging, "get_recent_logs", fail_get_recent_logs)

    assert enhanced_logging.get_recent_error_stats(200) == (2, 4)


def test_recent_error_stats_source_scans_ring_directly() -> None:
    source = inspect.getsource(enhanced_logging.get_recent_error_stats)

    assert "with _log_ring_lock:" in source
    assert "for entry in _log_ring:" in source
    assert "get_recent_logs" not in source
    assert "return list" not in source


def test_metrics_recent_error_gauge_uses_aggregate_helper() -> None:
    with patch(
        "ai_intervention_agent.enhanced_logging.get_recent_error_stats",
        return_value=(7, 123),
    ) as stats_spy:
        payload = system._render_prometheus_metrics()

    stats_spy.assert_called_once()
    assert "aiia_recent_errors_5min 7\n" in payload


def test_system_health_recent_errors_uses_aggregate_helper() -> None:
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(prompt="r665 health", task_id="r665-health", port=19165)
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False

    with patch(
        "ai_intervention_agent.enhanced_logging.get_recent_error_stats",
        return_value=(3, 123),
    ) as stats_spy:
        resp = ui.app.test_client().get("/api/system/health")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["checks"]["recent_errors"] == {
        "ok": True,
        "count_last_5min": 3,
        "buffer_total": 123,
    }
    stats_spy.assert_called_once()


def test_recent_error_aggregate_call_sites_are_source_visible() -> None:
    metrics_source = inspect.getsource(system._render_prometheus_metrics)
    full_source = inspect.getsource(system.SystemRoutesMixin._setup_system_routes)

    assert "get_recent_error_stats" in metrics_source
    assert (
        "error_count, _buffer_total = get_recent_error_stats(cutoff)" in metrics_source
    )
    assert "get_recent_error_stats" in full_source
    assert "error_count, buffer_total = get_recent_error_stats(cutoff)" in full_source
