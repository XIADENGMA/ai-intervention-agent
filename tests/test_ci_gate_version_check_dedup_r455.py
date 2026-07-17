"""R455 · avoid duplicate version-check work in CI workflows."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI_GATE = ROOT / "scripts" / "ci_gate.py"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "test.yml",
    ROOT / ".github" / "workflows" / "release.yml",
)


def _workflow_steps(path: Path) -> list[dict[str, object]]:
    doc_obj: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc_obj, dict)
    doc = cast("dict[str, object]", doc_obj)
    jobs = doc.get("jobs", {})
    assert isinstance(jobs, dict)
    jobs_dict = cast("dict[str, object]", jobs)
    first_job_obj = next(iter(jobs_dict.values()))
    assert isinstance(first_job_obj, dict)
    first_job = cast("dict[str, object]", first_job_obj)
    steps = first_job.get("steps", [])
    assert isinstance(steps, list)
    return [cast("dict[str, object]", step) for step in steps if isinstance(step, dict)]


def _step_run(step: dict[str, object]) -> str:
    run = step.get("run", "")
    return run if isinstance(run, str) else ""


def test_ci_gate_exposes_explicit_skip_version_check_flag() -> None:
    src = CI_GATE.read_text(encoding="utf-8")

    assert "--skip-version-check" in src
    assert "if not args.skip_version_check" in src
    assert 'scripts/bump_version.py", "--check"' in src


def test_workflows_skip_internal_version_check_only_after_fast_fail_step() -> None:
    for workflow in WORKFLOWS:
        steps = _workflow_steps(workflow)
        bump_indexes = [
            i
            for i, step in enumerate(steps)
            if "scripts/bump_version.py --check" in _step_run(step)
        ]
        ci_gate_indexes = [
            i
            for i, step in enumerate(steps)
            if "scripts/ci_gate.py --ci" in _step_run(step)
        ]

        assert bump_indexes, f"{workflow.name} must keep a fast version-check step"
        assert ci_gate_indexes, f"{workflow.name} must run ci_gate.py --ci"
        assert min(bump_indexes) < min(ci_gate_indexes), (
            f"{workflow.name} must run the fast version check before ci_gate"
        )

        for i in ci_gate_indexes:
            run = _step_run(steps[i])
            assert "--skip-version-check" in run, (
                f"{workflow.name} already ran bump_version.py --check; "
                "ci_gate should skip the duplicate internal version check"
            )
