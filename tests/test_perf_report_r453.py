"""R453 · machine-aware perf report wrapper tests."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.perf_report as perf_report


def _payload(median_ms: float = 100.0) -> dict[str, object]:
    return {
        "_meta": {
            "environment": {
                "python": "3.13.0",
                "platform": "test-platform",
                "cpu_count": 8,
            },
            "quick": True,
            "selected": ["import_web_ui"],
        },
        "import_web_ui": {
            "median_ms": median_ms,
            "p90_ms": median_ms,
            "min_ms": median_ms,
            "max_ms": median_ms,
            "iterations": 1,
            "samples_ms": [median_ms],
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_report_includes_environment_and_gate_verdict() -> None:
    report = perf_report.build_report(
        results_payload=_payload(100.0),
        baseline_payload={"benchmarks": {"import_web_ui": {"median_ms": 100.0}}},
        command=["perf_report.py", "--results", "current.json"],
        fail_on_regression=False,
    )

    assert report["ok"] is True
    assert report["schema_version"] == 1
    assert report["environment"]["platform"] == "test-platform"
    assert report["benchmark_meta"]["quick"] is True
    assert report["benchmarks"]["import_web_ui"]["median_ms"] == 100.0
    assert report["gate"]["status"] == "pass"
    assert report["exit_policy"]["numeric_regressions_fail"] is False


def test_default_cli_reports_regression_without_failing_process(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    baseline = tmp_path / "baseline.json"
    out = tmp_path / "report.json"
    _write_json(current, _payload(200.0))
    _write_json(baseline, {"benchmarks": {"import_web_ui": {"median_ms": 100.0}}})

    rc = perf_report._main(
        [
            "--results",
            str(current),
            "--baseline",
            str(baseline),
            "--output",
            str(out),
        ]
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 0
    assert data["ok"] is False
    assert data["gate"]["status"] == "regression"
    assert data["exit_policy"]["numeric_regressions_fail"] is False


def test_cli_can_fail_on_regression_when_environment_is_comparable(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.json"
    baseline = tmp_path / "baseline.json"
    _write_json(current, _payload(200.0))
    _write_json(baseline, {"benchmarks": {"import_web_ui": {"median_ms": 100.0}}})

    rc = perf_report._main(
        [
            "--results",
            str(current),
            "--baseline",
            str(baseline),
            "--fail-on-regression",
        ]
    )

    assert rc == 1


def test_no_gate_mode_records_skipped_gate(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    out = tmp_path / "report.json"
    _write_json(current, _payload(100.0))

    rc = perf_report._main(
        [
            "--results",
            str(current),
            "--no-gate",
            "--output",
            str(out),
        ]
    )
    data = json.loads(out.read_text(encoding="utf-8"))

    assert rc == 0
    assert data["ok"] is True
    assert data["gate"]["status"] == "skipped"


def test_benchmark_errors_fail_even_without_numeric_gate(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    _write_json(
        current,
        {
            "_meta": {"environment": {"platform": "test"}},
            "import_web_ui": {
                "error": "RuntimeError: boom",
                "iterations": 0,
                "samples_ms": [],
            },
        },
    )

    rc = perf_report._main(["--results", str(current), "--no-gate"])

    assert rc == 1
