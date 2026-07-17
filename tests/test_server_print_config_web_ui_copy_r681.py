from __future__ import annotations

import inspect
import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from ai_intervention_agent import server


def test_print_config_web_ui_snapshot_uses_dict_copy() -> None:
    source = inspect.getsource(server._print_effective_config)

    assert "web_ui_section = web_ui_raw.copy()" in source
    assert "web_ui_section = dict(web_ui_raw)" not in source


def test_print_config_web_ui_overlay_does_not_mutate_get_all_snapshot() -> None:
    web_ui_raw: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 8080,
        "language": "zh-CN",
    }
    all_config: dict[str, Any] = {
        "web_ui": web_ui_raw,
        "feedback": {"frontend_countdown": 30},
    }
    fake_config = SimpleNamespace(
        config_file="/tmp/config.toml", get_all=lambda: all_config
    )
    merged = SimpleNamespace(host="0.0.0.0", port=8181, language="en")

    with (
        patch(
            "ai_intervention_agent.config_manager.get_config", return_value=fake_config
        ),
        patch(
            "ai_intervention_agent.service_manager.get_web_ui_config",
            return_value=(merged, 30),
        ),
        redirect_stdout(io.StringIO()) as captured,
    ):
        assert server._print_effective_config() == 0

    payload = json.loads(captured.getvalue())

    assert payload["web_ui"]["host"] == "0.0.0.0"
    assert payload["web_ui"]["port"] == 8181
    assert payload["web_ui"]["language"] == "en"
    assert web_ui_raw == {
        "host": "127.0.0.1",
        "port": 8080,
        "language": "zh-CN",
    }
