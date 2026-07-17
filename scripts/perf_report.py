#!/usr/bin/env python3
"""Machine-aware performance report wrapper.

This script composes the existing benchmark harness and regression gate into a
single JSON artifact suitable for local release review. By default it reports a
gate verdict but does not fail the process for numeric regressions, because the
committed baseline is machine-specific. Use ``--fail-on-regression`` only in a
known-comparable environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.perf_e2e_bench as perf_bench  # noqa: E402
import scripts.perf_gate as perf_gate  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} top-level must be a JSON object")
    return data


def _benchmark_errors(payload: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for name, info in payload.items():
        if name.startswith("_"):
            continue
        if isinstance(info, dict) and "error" in info:
            errors.append({"name": name, "error": str(info["error"])})
    return errors


def build_report(
    *,
    results_payload: dict[str, Any],
    baseline_payload: dict[str, Any] | None,
    command: list[str],
    fail_on_regression: bool,
) -> dict[str, Any]:
    """Build the report object without running benchmarks."""
    meta = results_payload.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    environment = meta.get("environment") if isinstance(meta, dict) else {}
    if not isinstance(environment, dict):
        environment = {}

    current = perf_gate._extract_benchmarks(results_payload)
    errors = _benchmark_errors(results_payload)

    gate: dict[str, Any]
    if baseline_payload is None:
        gate = {
            "status": "skipped",
            "reason": "no baseline comparison requested",
        }
    else:
        baseline = perf_gate._extract_benchmarks(baseline_payload)
        per_bench = perf_gate._extract_per_bench_thresholds(baseline_payload)
        verdict = perf_gate.evaluate(
            current=current,
            baseline=baseline,
            pct_threshold=perf_gate.DEFAULT_PCT_THRESHOLD,
            abs_floor_ms=perf_gate.DEFAULT_ABS_FLOOR_MS,
            per_bench_threshold=per_bench,
        )
        gate = {
            "status": "pass" if verdict["ok"] else "regression",
            "ok": verdict["ok"],
            "verdict": verdict,
            "baseline_benchmarks": sorted(baseline.keys()),
        }

    gate_ok = gate.get("ok", True) is True
    ok = not errors and gate_ok

    return {
        "ok": ok,
        "generated_at": datetime.now(UTC).isoformat(),
        "schema_version": 1,
        "command": command,
        "exit_policy": {
            "benchmark_errors_fail": True,
            "numeric_regressions_fail": fail_on_regression,
        },
        "environment": environment,
        "benchmark_meta": meta,
        "benchmarks": current,
        "benchmark_errors": errors,
        "gate": gate,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run or summarize AIIA performance benchmarks with machine context "
            "and an optional local baseline verdict."
        )
    )
    parser.add_argument(
        "--results",
        type=Path,
        help="Existing perf_e2e_bench.py JSON to summarize instead of running benchmarks.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON report to this path instead of stdout.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=perf_gate.DEFAULT_BASELINE,
        help="Baseline JSON for local comparison.",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="Skip baseline comparison and emit report-only JSON.",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help=(
            "Exit non-zero for numeric regressions. Use only when current and "
            "baseline were measured on comparable hardware."
        ),
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Pass quick=True to perf_e2e_bench.run_all when --results is omitted.",
    )
    parser.add_argument(
        "--select",
        action="append",
        choices=list(perf_bench.BENCHMARKS.keys()),
        help="Run only the selected benchmark when --results is omitted; repeatable.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress benchmark progress logs when running benchmarks.",
    )
    return parser


def _main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.results:
        results_payload = _load_json(args.results)
    else:
        results_payload = perf_bench.run_all(
            quick=args.quick,
            select=args.select,
            quiet=args.quiet,
        )

    baseline_payload: dict[str, Any] | None = None
    if not args.no_gate:
        baseline_payload = _load_json(args.baseline)

    command = [
        str(Path(sys.argv[0]).name),
        *(argv if argv is not None else sys.argv[1:]),
    ]
    report = build_report(
        results_payload=results_payload,
        baseline_payload=baseline_payload,
        command=command,
        fail_on_regression=args.fail_on_regression,
    )

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    if report["benchmark_errors"]:
        return 1
    if args.fail_on_regression and report["gate"].get("ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
