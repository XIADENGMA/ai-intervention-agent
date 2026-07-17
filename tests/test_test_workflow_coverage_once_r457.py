"""R457 · Tests workflow should generate coverage once per matrix run."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


def _steps() -> list[dict[str, object]]:
    doc_obj: object = yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(doc_obj, dict)
    doc = cast("dict[str, object]", doc_obj)
    jobs_obj = doc.get("jobs", {})
    assert isinstance(jobs_obj, dict)
    jobs = cast("dict[str, object]", jobs_obj)
    test_job_obj = jobs.get("test", {})
    assert isinstance(test_job_obj, dict)
    test_job = cast("dict[str, object]", test_job_obj)
    steps_obj = test_job.get("steps", [])
    assert isinstance(steps_obj, list)
    return [
        cast("dict[str, object]", step) for step in steps_obj if isinstance(step, dict)
    ]


def _run(step: dict[str, object]) -> str:
    run = step.get("run", "")
    return run if isinstance(run, str) else ""


def _if(step: dict[str, object]) -> str:
    condition = step.get("if", "")
    return condition if isinstance(condition, str) else ""


def test_coverage_ci_gate_runs_only_on_uploaded_coverage_axis() -> None:
    ci_gate_steps = [
        step for step in _steps() if "scripts/ci_gate.py --ci" in _run(step)
    ]
    coverage_steps = [step for step in ci_gate_steps if "--with-coverage" in _run(step)]
    plain_steps = [
        step for step in ci_gate_steps if "--with-coverage" not in _run(step)
    ]

    assert len(coverage_steps) == 1, (
        "test.yml should not run pytest-cov on every Python matrix axis when "
        "coverage.xml is uploaded from only one axis"
    )
    assert _if(coverage_steps[0]) == "matrix.python-version == '3.11'"
    assert len(plain_steps) == 1
    assert _if(plain_steps[0]) == "matrix.python-version != '3.11'"


def test_coverage_upload_stays_on_same_axis_as_coverage_gate() -> None:
    upload_steps = [
        step
        for step in _steps()
        if step.get("name") == "上传覆盖率报告（coverage.xml）"
    ]

    assert len(upload_steps) == 1
    assert "matrix.python-version == '3.11'" in _if(upload_steps[0])
    assert "--with-coverage" not in _run(upload_steps[0])
