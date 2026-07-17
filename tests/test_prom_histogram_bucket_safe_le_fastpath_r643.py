"""R643 - generated Prometheus histogram le labels skip no-op escaping."""

from __future__ import annotations

import inspect

from pytest import MonkeyPatch

from ai_intervention_agent.web_ui_routes import system as system_module


def test_histogram_family_skips_generated_le_label_escaping(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_escape = system_module._escape_prom_label_value

    def spy_escape(value: str) -> str:
        calls.append(value)
        return original_escape(value)

    monkeypatch.setattr(system_module, "_escape_prom_label_value", spy_escape)

    out = system_module._format_prom_histogram_family(
        "aiia_test_duration_seconds",
        help_text="A test histogram.",
        observations=(
            (
                {"provider": "bark"},
                {0.1: 1, system_module._PROM_INF: 1},
                1,
                0.1,
            ),
        ),
    )

    assert 'aiia_test_duration_seconds_bucket{le="0.1",provider="bark"} 1\n' in out
    assert 'aiia_test_duration_seconds_bucket{le="+Inf",provider="bark"} 1\n' in out
    assert "0.1" not in calls
    assert "+Inf" not in calls
    assert "bark" in calls


def test_histogram_family_without_base_labels_does_not_call_escape(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []

    def spy_escape(value: str) -> str:
        calls.append(value)
        return value

    monkeypatch.setattr(system_module, "_escape_prom_label_value", spy_escape)

    out = system_module._format_prom_histogram_family(
        "aiia_test_duration_seconds",
        help_text="A test histogram.",
        observations=((None, {0.1: 1, system_module._PROM_INF: 1}, 1, 0.1),),
    )

    assert 'aiia_test_duration_seconds_bucket{le="0.1"} 1\n' in out
    assert 'aiia_test_duration_seconds_bucket{le="+Inf"} 1\n' in out
    assert calls == []


def test_direct_bucket_label_helper_still_escapes_arbitrary_le_values() -> None:
    assert (
        system_module._format_prom_histogram_bucket_labels('bad"value\n', None)
        == r'{le="bad\"value\n"}'
    )
    assert (
        system_module._format_prom_histogram_bucket_labels(
            'bad"value\n',
            {"provider": "bark"},
        )
        == r'{le="bad\"value\n",provider="bark"}'
    )


def test_histogram_family_opts_into_safe_le_label_fast_path() -> None:
    family_source = inspect.getsource(system_module._format_prom_histogram_family)
    helper_source = inspect.getsource(
        system_module._format_prom_histogram_bucket_labels
    )

    assert "le_label_value_is_safe=True" in family_source
    assert "le_label_value_is_safe: bool = False" in helper_source
    non_empty_branch = helper_source[helper_source.index('if "le" in base_labels:') :]
    assert non_empty_branch.index('if "le" in base_labels:') < non_empty_branch.index(
        "escaped_le_label_value = ("
    )
