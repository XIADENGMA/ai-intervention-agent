from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_intervention_agent.config_utils import truncate_string
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import notification


def test_feedback_prompt_route_deps_cache_short_circuits_imports() -> None:
    original = notification._FEEDBACK_PROMPT_ROUTE_DEPS
    sentinel = (lambda value, *_args, **_kwargs: value, 123, 456)
    try:
        notification._FEEDBACK_PROMPT_ROUTE_DEPS = sentinel
        with patch("builtins.__import__") as import_mock:
            assert notification._get_feedback_prompt_route_deps() is sentinel
        import_mock.assert_not_called()
    finally:
        notification._FEEDBACK_PROMPT_ROUTE_DEPS = original


def test_get_feedback_prompts_uses_cached_deps_for_fallback_and_truncate() -> None:
    web_ui = WebFeedbackUI(prompt="r659", task_id="r659", port=19659)
    web_ui.app.config["TESTING"] = True
    client = web_ui.app.test_client()

    config_mgr = MagicMock()
    config_mgr.config_file = Path("config.toml")
    config_mgr.get_section.return_value = {
        "frontend_countdown": "not-an-int",
        "resubmit_prompt": "abcdef",
        "prompt_suffix": "uvwxyz",
    }

    cached_deps = (truncate_string, 240, 5)
    original = notification._FEEDBACK_PROMPT_ROUTE_DEPS
    try:
        notification._FEEDBACK_PROMPT_ROUTE_DEPS = cached_deps
        with patch(
            "ai_intervention_agent.web_ui_routes.notification.get_config",
            return_value=config_mgr,
        ):
            response = client.get("/api/get-feedback-prompts")
    finally:
        notification._FEEDBACK_PROMPT_ROUTE_DEPS = original

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["config"] == {
        "frontend_countdown": 240,
        "resubmit_prompt": "abcde",
        "prompt_suffix": "uvwxy",
    }
