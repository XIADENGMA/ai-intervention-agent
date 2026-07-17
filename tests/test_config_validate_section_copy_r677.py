from __future__ import annotations

import inspect
from typing import Any, cast

from ai_intervention_agent import config_manager as config_manager_module
from ai_intervention_agent.config_manager import ConfigManager


def test_validate_section_fallbacks_use_dict_copy() -> None:
    source = inspect.getsource(ConfigManager._validate_section)

    assert source.count("return raw.copy()") == 2
    assert "return dict(raw)" not in source


def test_validate_section_unknown_section_returns_independent_copy() -> None:
    raw: dict[str, Any] = {"value": 1, "nested": ["a"]}

    result = ConfigManager._validate_section("unknown_r677", raw)
    result["value"] = 2

    assert result == {"value": 2, "nested": ["a"]}
    assert raw == {"value": 1, "nested": ["a"]}
    assert result is not raw


def test_validate_section_invalid_raw_still_normalizes_to_empty_dict() -> None:
    result = ConfigManager._validate_section("unknown_r677", "not a dict")

    assert result == {}


def test_validate_section_model_failure_returns_independent_copy(
    monkeypatch: Any,
) -> None:
    class RaisingModel:
        @classmethod
        def model_validate(cls, raw: Any) -> Any:
            raise ValueError("boom")

    monkeypatch.setitem(
        config_manager_module.SECTION_MODELS,
        "broken_r677",
        cast(Any, RaisingModel),
    )

    raw: dict[str, Any] = {"enabled": True}
    result = ConfigManager._validate_section("broken_r677", raw)
    result["enabled"] = False

    assert result == {"enabled": False}
    assert raw == {"enabled": True}
    assert result is not raw
