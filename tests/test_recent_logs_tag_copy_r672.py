from __future__ import annotations

import inspect
from typing import Any, cast
from unittest.mock import MagicMock, patch

import ai_intervention_agent.server as server


def test_server_info_recent_logs_uses_dict_copy_for_source_tagging() -> None:
    source = inspect.getsource(server.server_info_resource)

    assert "tagged = ent.copy()" in source
    assert "tagged = dict(ent)" not in source


def test_mcp_recent_log_source_tagging_does_not_mutate_original_entry() -> None:
    original_entry: dict[str, Any] = {
        "level": "ERROR",
        "message": "mcp boom",
        "ts_unix": 100.0,
    }

    with (
        patch(
            "ai_intervention_agent.server.is_web_service_running", return_value=False
        ),
        patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs",
            return_value=[original_entry],
        ),
    ):
        info = server.server_info_resource()

    recent_logs = cast(dict[str, Any], info["recent_logs"])
    entries = cast(list[dict[str, Any]], recent_logs["entries"])
    entries[0]["message"] = "polluted"
    entries[0]["injected"] = True

    assert entries[0]["source"] == "mcp"
    assert "source" not in original_entry
    assert original_entry["message"] == "mcp boom"
    assert "injected" not in original_entry


def test_web_ui_recent_log_source_tagging_does_not_mutate_fetched_entry() -> None:
    web_entry: dict[str, Any] = {
        "level": "WARNING",
        "message": "ui warning",
        "ts_unix": 50.0,
    }

    def fake_get(url: str, *_args: Any, **_kwargs: Any) -> MagicMock:
        if "recent-logs" in url:
            return MagicMock(
                status_code=200,
                json=MagicMock(
                    return_value={
                        "success": True,
                        "entries": [web_entry],
                    }
                ),
            )
        return MagicMock(
            status_code=200, json=MagicMock(return_value={"success": True})
        )

    server.reset_recent_logs_cache_for_testing()
    with (
        patch("ai_intervention_agent.server.is_web_service_running", return_value=True),
        patch(
            "ai_intervention_agent.enhanced_logging.get_recent_logs", return_value=[]
        ),
        patch("httpx.get", side_effect=fake_get),
    ):
        info = server.server_info_resource()

    recent_logs = cast(dict[str, Any], info["recent_logs"])
    entries = cast(list[dict[str, Any]], recent_logs["entries"])
    entries[0]["message"] = "polluted"
    entries[0]["injected"] = True

    assert entries[0]["source"] == "web_ui"
    assert "source" not in web_entry
    assert web_entry["message"] == "ui warning"
    assert "injected" not in web_entry
