"""R645 - missing +Inf histogram buckets reuse formatted count value."""

from __future__ import annotations

import inspect

from pytest import MonkeyPatch

from ai_intervention_agent.web_ui_routes import system as system_module


def test_missing_inf_bucket_formats_count_once(monkeypatch: MonkeyPatch) -> None:
    calls: list[int | float] = []
    original_format_value = system_module._format_prom_value

    def spy_format_value(value: int | float) -> str:
        calls.append(value)
        return original_format_value(value)

    monkeypatch.setattr(system_module, "_format_prom_value", spy_format_value)

    out = system_module._format_prom_histogram_family(
        "aiia_test_duration_seconds",
        help_text="A test histogram.",
        observations=(({"label": "missing"}, {0.1: 1, 0.5: 3}, 7, 2.5),),
    )

    assert 'aiia_test_duration_seconds_bucket{le="+Inf",label="missing"} 7\n' in out
    assert 'aiia_test_duration_seconds_count{label="missing"} 7\n' in out
    assert calls == [1, 3, 7, 2.5]


def test_existing_inf_bucket_still_formats_bucket_value_separately(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[int | float] = []
    original_format_value = system_module._format_prom_value

    def spy_format_value(value: int | float) -> str:
        calls.append(value)
        return original_format_value(value)

    monkeypatch.setattr(system_module, "_format_prom_value", spy_format_value)

    out = system_module._format_prom_histogram_family(
        "aiia_test_duration_seconds",
        help_text="A test histogram.",
        observations=(
            ({"label": "existing"}, {0.1: 1, system_module._PROM_INF: 5}, 7, 2.5),
        ),
    )

    assert 'aiia_test_duration_seconds_bucket{le="+Inf",label="existing"} 5\n' in out
    assert 'aiia_test_duration_seconds_count{label="existing"} 7\n' in out
    assert calls == [1, 5, 2.5, 7]


def test_histogram_family_reuses_count_value_string_for_missing_inf() -> None:
    source = inspect.getsource(system_module._format_prom_histogram_family)

    assert "count_value_str: str | None = None" in source
    assert "count_value_str = _format_prom_value(count)" in source
    assert "bucket_value_str = count_value_str" in source
    assert "if count_value_str is None:" in source
    assert (
        source.index("count_value_str: str | None = None")
        < source.index("for le in sorted_keys:")
        < source.index("if count_value_str is None:")
    )
