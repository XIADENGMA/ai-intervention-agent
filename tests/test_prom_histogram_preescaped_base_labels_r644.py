"""R644 - histogram buckets reuse preescaped base labels per observation."""

from __future__ import annotations

import inspect

from pytest import MonkeyPatch

from ai_intervention_agent.web_ui_routes import system as system_module


def test_histogram_family_escapes_single_base_label_once_per_observation(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_escape = system_module._escape_prom_label_value
    provider = 'read\\file "x"\none'

    def spy_escape(value: str) -> str:
        calls.append(value)
        return original_escape(value)

    monkeypatch.setattr(system_module, "_escape_prom_label_value", spy_escape)

    out = system_module._format_prom_histogram_family(
        "aiia_test_duration_seconds",
        help_text="A test histogram.",
        observations=(
            (
                {"provider": provider},
                {0.1: 1, 0.5: 2, system_module._PROM_INF: 2},
                2,
                0.6,
            ),
        ),
    )

    escaped_provider = r'provider="read\\file \"x\"\none"'
    assert (
        f'aiia_test_duration_seconds_bucket{{le="0.1",{escaped_provider}}} 1\n' in out
    )
    assert (
        f'aiia_test_duration_seconds_bucket{{le="0.5",{escaped_provider}}} 2\n' in out
    )
    assert (
        f'aiia_test_duration_seconds_bucket{{le="+Inf",{escaped_provider}}} 2\n' in out
    )
    assert f"aiia_test_duration_seconds_sum{{{escaped_provider}}} 0.6\n" in out
    assert f"aiia_test_duration_seconds_count{{{escaped_provider}}} 2\n" in out
    assert calls.count(provider) == 1
    assert "0.1" not in calls
    assert "0.5" not in calls
    assert "+Inf" not in calls


def test_histogram_family_escapes_multi_base_labels_once_per_observation(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_escape = system_module._escape_prom_label_value
    tool = 'read\\file "x"'
    status = "one\ntwo"

    def spy_escape(value: str) -> str:
        calls.append(value)
        return original_escape(value)

    monkeypatch.setattr(system_module, "_escape_prom_label_value", spy_escape)

    out = system_module._format_prom_histogram_family(
        "aiia_test_duration_seconds",
        help_text="A test histogram.",
        observations=(
            (
                {"tool": tool, "status": status},
                {0.1: 1, 0.5: 2, system_module._PROM_INF: 2},
                2,
                0.6,
            ),
        ),
    )

    escaped_labels = r'tool="read\\file \"x\"",status="one\ntwo"'
    assert f'aiia_test_duration_seconds_bucket{{le="0.1",{escaped_labels}}} 1\n' in out
    assert f'aiia_test_duration_seconds_bucket{{le="0.5",{escaped_labels}}} 2\n' in out
    assert f'aiia_test_duration_seconds_bucket{{le="+Inf",{escaped_labels}}} 2\n' in out
    assert f"aiia_test_duration_seconds_sum{{{escaped_labels}}} 0.6\n" in out
    assert f"aiia_test_duration_seconds_count{{{escaped_labels}}} 2\n" in out
    assert calls.count(tool) == 1
    assert calls.count(status) == 1
    assert "0.1" not in calls
    assert "0.5" not in calls
    assert "+Inf" not in calls


def test_legacy_le_override_does_not_use_preescaped_base_label_suffix() -> None:
    out = system_module._format_prom_histogram_family(
        "aiia_test_duration_seconds",
        help_text="A test histogram.",
        observations=(
            (
                {"tool": "read_file", "le": "caller"},
                {0.1: 1, system_module._PROM_INF: 1},
                1,
                0.1,
            ),
        ),
    )

    assert 'aiia_test_duration_seconds_bucket{le="caller",tool="read_file"} 1\n' in out
    assert 'aiia_test_duration_seconds_sum{tool="read_file",le="caller"} 0.1\n' in out
    assert 'aiia_test_duration_seconds_count{tool="read_file",le="caller"} 1\n' in out


def test_histogram_family_passes_preescaped_base_label_suffix() -> None:
    family_source = inspect.getsource(system_module._format_prom_histogram_family)
    helper_source = inspect.getsource(
        system_module._format_prom_histogram_bucket_labels
    )

    assert "base_label_str = _format_prom_labels(base_labels)" in family_source
    assert "preescaped_base_label_suffix = (" in family_source
    assert "preescaped_base_label_suffix=preescaped_base_label_suffix" in family_source
    assert "preescaped_base_label_suffix: str | None = None" in helper_source
    assert helper_source.index("if preescaped_base_label_suffix is not None:") < (
        helper_source.index("if len(base_labels) == 1:")
    )
