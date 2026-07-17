"""R658: backend i18n request-language detection keeps the hot path lean."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from ai_intervention_agent import i18n


def test_detect_request_lang_uses_module_request_proxy_and_partition() -> None:
    source = inspect.getsource(i18n.detect_request_lang)

    assert "from flask import request" not in source
    assert "_flask_request" in inspect.getsource(i18n)
    assert '.partition(",")[0].partition(";")[0].strip()' in source
    assert ".split(" not in source


def test_accept_language_request_header_still_wins_over_config() -> None:
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        headers={"Accept-Language": "zh-Hant-TW;q=0.9,en;q=0.8"},
    ):
        with patch(
            "ai_intervention_agent.config_manager.get_config",
            side_effect=AssertionError("request language should short-circuit config"),
        ):
            assert i18n.detect_request_lang() == "zh-TW"


def test_accept_language_secondary_values_keep_existing_primary_semantics() -> None:
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        headers={"Accept-Language": "fr-FR,zh-CN;q=0.9"},
    ):
        assert i18n.detect_request_lang() == "en"


def test_outside_request_context_still_falls_back_to_config_language() -> None:
    fake_config = SimpleNamespace(
        get_section=lambda section: {"language": "zh-CN"} if section == "web_ui" else {}
    )

    with patch(
        "ai_intervention_agent.config_manager.get_config", return_value=fake_config
    ):
        assert i18n.detect_request_lang() == "zh-CN"


def test_missing_flask_request_proxy_still_falls_back_to_config_language() -> None:
    fake_config = SimpleNamespace(
        get_section=lambda section: {"language": "zh-TW"} if section == "web_ui" else {}
    )

    with (
        patch.object(i18n, "_flask_request", None),
        patch(
            "ai_intervention_agent.config_manager.get_config", return_value=fake_config
        ),
    ):
        assert i18n.detect_request_lang() == "zh-TW"


def test_auto_or_failed_config_still_returns_default_lang() -> None:
    fake_config = SimpleNamespace(
        get_section=lambda section: {"language": "auto"} if section == "web_ui" else {}
    )

    with patch(
        "ai_intervention_agent.config_manager.get_config", return_value=fake_config
    ):
        assert i18n.detect_request_lang() == i18n.DEFAULT_LANG

    with patch(
        "ai_intervention_agent.config_manager.get_config",
        side_effect=RuntimeError("config unavailable"),
    ):
        assert i18n.detect_request_lang() == i18n.DEFAULT_LANG
