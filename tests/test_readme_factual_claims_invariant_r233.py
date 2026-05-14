"""R233 / Cycle 14: README factual claims must not silently drift.

Why this invariant
------------------

Both ``README.md`` and ``README.zh-CN.md`` contain a positioning
paragraph ("Where AIIA sits on the spectrum") with three factual
claims about repository scale:

1. ``5,600+ tests`` — count of pytest-collected test items
2. ``~800 subtests`` — count of ``subTest`` blocks reported as
   "passed" in the pytest run output
3. ``5-job release pipeline`` — count of ``jobs:`` keys in
   ``.github/workflows/release.yml``

These numbers were correct at v1.7.6 (Cycle 14 R233). Without
guardrails, they silently rot:

- v1.7.0 README claimed "5,500+ tests + ~700 subtests" — by v1.7.5
  reality was 5,643 tests + 809 subtests, so the README understated
  by ~140 tests / ~110 subtests.
- v1.7.4 README claimed "6-job release pipeline" — actual was 5
  jobs after the matrix refactor in R??? collapsed two.

R233 lock:

- **Lower-bound check** (Pattern A · static check): README's claimed
  "+" floors must be ≤ reality. If new tests are added beyond what
  the README claims, that's fine — the "+" allows growth. But if
  someone deletes tests and reality drops below the claim, fail.
- **Lag check**: reality MUST NOT exceed claim by more than
  ``MAX_LAG_TESTS`` (or ``MAX_LAG_SUBTESTS``). If it does, fail and
  force a README refresh. The 10% / 100-unit tolerance allows
  in-cycle growth without daily README churn but flags every
  release-time review.
- **Exact-match check** for release-pipeline job count: this number
  is non-monotonic (jobs can be added OR consolidated), so exact
  equality is the right contract.

What we DON'T check
-------------------

- Star counts of related projects (different lifecycle; upstream
  counts change independently of this repo's commits; F-cycle12-1
  candidate for separate handling)
- Version numbers (already locked by other invariants)
- Feature claims in prose (too subjective for static check)
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
README_EN = REPO_ROOT / "README.md"
README_ZH = REPO_ROOT / "README.zh-CN.md"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

MAX_LAG_TESTS = 500
MAX_LAG_SUBTESTS = 200


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_test_count_claim(readme: str) -> int:
    match = re.search(
        r"([0-9],?[0-9]{3,})\+\s*(?:tests|测试)",
        readme,
    )
    assert match is not None, (
        "R233: cannot find '<NNNN>+ tests' / '<NNNN>+ 测试' claim in README; "
        "if positioning paragraph was rewritten, update this regex."
    )
    return int(match.group(1).replace(",", ""))


def _extract_subtest_count_claim(readme: str) -> int:
    match = re.search(r"~([0-9]+)\s*subtests", readme)
    assert match is not None, (
        "R233: cannot find '~NNN subtests' claim in README; if positioning "
        "paragraph was rewritten, update this regex."
    )
    return int(match.group(1))


def _extract_release_job_count_claim(readme: str) -> int:
    match = re.search(
        r"([0-9]+)[\s-]*(?:job|个 job)",
        readme,
    )
    assert match is not None, (
        "R233: cannot find '<N>-job release pipeline' / '<N> 个 job' claim in README."
    )
    return int(match.group(1))


def _count_release_workflow_jobs() -> int:
    raw = _read(RELEASE_WORKFLOW)
    data = yaml.safe_load(raw)
    jobs = data.get("jobs", {})
    return len(jobs)


def _collect_pytest_test_count() -> int:
    """Run ``pytest --collect-only -q`` to count tests."""
    result = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    match = re.search(r"^(\d+) tests collected", output, re.MULTILINE)
    if match is None:
        raise AssertionError(
            f"Failed to parse pytest collect output:\n{output[-2000:]}"
        )
    return int(match.group(1))


def _estimate_subtest_run_count() -> int:
    """Estimate runtime subTest() execution count via static loop+subTest scan.

    True count requires a full pytest run (~165s). For an invariant test
    that runs on every CI gate, we approximate by:
    1. Counting ``with self.subTest(...)`` blocks (static call sites)
    2. Multiplying each by the heuristic loop-iteration factor
       ``HEURISTIC_LOOP_FACTOR`` based on observed empirical ratio
       (89 call sites in v1.7.6 → 809 runtime executions = factor ~9.1).

    The factor is wide because some subTest blocks live inside small
    loops (2-5 iter) and others inside large generated suites (50+ iter).
    For staleness lint a coarse estimate is enough — refresh threshold is
    ``MAX_LAG_SUBTESTS`` = 200 so the heuristic doesn't have to be tight.
    """
    HEURISTIC_LOOP_FACTOR = 9
    tests_dir = REPO_ROOT / "tests"
    total = 0
    for entry in tests_dir.iterdir():
        if not entry.is_file() or not entry.name.endswith(".py"):
            continue
        text = entry.read_text(encoding="utf-8")
        total += len(re.findall(r"\bsubTest\s*\(", text))
    return total * HEURISTIC_LOOP_FACTOR


class TestReleaseJobCountMatches(unittest.TestCase):
    def test_en_readme_claim_matches_release_yml(self) -> None:
        claim = _extract_release_job_count_claim(_read(README_EN))
        actual = _count_release_workflow_jobs()
        self.assertEqual(
            claim,
            actual,
            (
                f"R233 invariant: README.md claims {claim}-job release pipeline "
                f"but .github/workflows/release.yml has {actual} jobs. Update the "
                "README positioning paragraph OR check whether a workflow job "
                "was added/removed accidentally."
            ),
        )

    def test_zh_readme_claim_matches_release_yml(self) -> None:
        claim = _extract_release_job_count_claim(_read(README_ZH))
        actual = _count_release_workflow_jobs()
        self.assertEqual(claim, actual)


class TestTestCountClaimLowerBound(unittest.TestCase):
    def test_en_readme_claim_not_above_reality(self) -> None:
        claim = _extract_test_count_claim(_read(README_EN))
        actual = _collect_pytest_test_count()
        self.assertLessEqual(
            claim,
            actual,
            (
                f"R233 invariant: README.md claims '{claim}+ tests' but only "
                f"{actual} tests collected. Either README is overstating "
                "(misleading) or tests were deleted. Investigate."
            ),
        )

    def test_zh_readme_claim_not_above_reality(self) -> None:
        claim = _extract_test_count_claim(_read(README_ZH))
        actual = _collect_pytest_test_count()
        self.assertLessEqual(claim, actual)


class TestTestCountClaimNotTooStale(unittest.TestCase):
    def test_en_readme_claim_within_lag_threshold(self) -> None:
        claim = _extract_test_count_claim(_read(README_EN))
        actual = _collect_pytest_test_count()
        lag = actual - claim
        self.assertLessEqual(
            lag,
            MAX_LAG_TESTS,
            (
                f"R233 invariant: README.md test-count claim ({claim}+) lags "
                f"actual ({actual}) by {lag}, exceeding MAX_LAG_TESTS = "
                f"{MAX_LAG_TESTS}. Bump the README's '{claim:,}+ tests' floor "
                f"to roughly '{(actual // 100) * 100:,}+ tests' in both EN + "
                "zh-CN."
            ),
        )

    def test_zh_readme_claim_within_lag_threshold(self) -> None:
        claim = _extract_test_count_claim(_read(README_ZH))
        actual = _collect_pytest_test_count()
        lag = actual - claim
        self.assertLessEqual(lag, MAX_LAG_TESTS)


class TestSubtestCountClaimNotTooStale(unittest.TestCase):
    def test_en_readme_subtest_claim_within_lag_threshold(self) -> None:
        claim = _extract_subtest_count_claim(_read(README_EN))
        actual_est = _estimate_subtest_run_count()
        diff = abs(actual_est - claim)
        self.assertLessEqual(
            diff,
            MAX_LAG_SUBTESTS,
            (
                f"R233 invariant: README subtest claim (~{claim}) differs "
                f"from heuristic-estimated runtime subTest count ({actual_est}) "
                f"by {diff}, exceeding MAX_LAG_SUBTESTS = {MAX_LAG_SUBTESTS}. "
                "Refresh the '~NNN subtests' string in both EN + zh-CN "
                "READMEs (run `uv run pytest tests/ -q` to read the "
                "'NNN subtests passed' line)."
            ),
        )

    def test_zh_readme_subtest_claim_within_lag_threshold(self) -> None:
        claim = _extract_subtest_count_claim(_read(README_ZH))
        actual_est = _estimate_subtest_run_count()
        diff = abs(actual_est - claim)
        self.assertLessEqual(diff, MAX_LAG_SUBTESTS)


class TestBilingualClaimParity(unittest.TestCase):
    def test_test_count_matches_across_locales(self) -> None:
        self.assertEqual(
            _extract_test_count_claim(_read(README_EN)),
            _extract_test_count_claim(_read(README_ZH)),
            (
                "R233 invariant: EN and zh-CN README must claim the same "
                "test count floor. Update both when refreshing."
            ),
        )

    def test_subtest_count_matches_across_locales(self) -> None:
        self.assertEqual(
            _extract_subtest_count_claim(_read(README_EN)),
            _extract_subtest_count_claim(_read(README_ZH)),
        )

    def test_release_job_count_matches_across_locales(self) -> None:
        self.assertEqual(
            _extract_release_job_count_claim(_read(README_EN)),
            _extract_release_job_count_claim(_read(README_ZH)),
        )


if __name__ == "__main__":
    unittest.main()
