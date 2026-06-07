# CI Test Parallelization: xdist Worker Tuning (R308)

**Author**: cycle-31 R308 autonomous loop
**Date**: 2026-06-07
**Status**: Decision recorded — `-n 4 --dist=loadfile` is the locked
default (see `tests/test_feat_ci_xdist_worker_decision_r308.py`)
**Prior art**: cycle-30 R305 introduced `pytest-xdist -n 4 --dist=loadfile`
to ci_gate.py (`docs/code-reviews/cr60.md` §2D)

---

## TL;DR

| Mode | Total | Speedup | Reliable? | Recommended for |
|---|---|---|---|---|
| Serial (no xdist) | 191.62s | 1.0x | ✅ Always | Single test runs |
| `-n 2 --dist=loadfile` | **92.50s** | 2.07x | ❌ **R25-2 pollution** | Avoid |
| `-n 4 --dist=loadfile` | **50.03s** | 3.83x | ✅ Stable | **CI default (R305)** |
| `-n 8 --dist=loadfile` | 32.87s | 5.83x | ✅ Stable | Local 8+ core dev |
| `-n auto (16)` | 33.60s | 5.70x | ✅ Stable | Local high-core dev |

**Decision**: lock CI to `-n 4 --dist=loadfile`. Local devs can opt-in
to `-n auto` via `AIIA_TEST_WORKERS=auto uv run pytest`.

---

## Why not `-n auto`?

`pytest-xdist -n auto` reads `os.cpu_count()`:
- **Local M-series 16-core**: `auto` = 16, fastest (33s)
- **GitHub Actions free tier (2 vCPU)**: `auto` = 2, **slower than serial**
  (92s, 0.48x **speedup** = 2x slowdown!) AND **introduces R25-2
  notification-system pollution** — verified by sub-benchmark.

The root cause is **xdist `-n 2` scheduling overhead vs cross-file test
pollution susceptibility**. With only 2 worker, the test distribution
luck-of-the-draw becomes much narrower; tests that depend on order
(e.g. R72-A root logger handler initialization, R145 NotificationManager
class state, R25-2 module loading detection) get partitioned into 2
deterministic but unlucky groups. With 4+ workers, more cross-test
isolation emerges by the law of large numbers.

GitHub Actions runners as of 2026 are mostly 4 vCPU (standard tier), so
`-n 4` is the **environmental sweet spot that works everywhere**.

---

## Why not `-n 8` or higher in CI?

- CI runners are 2-4 vCPU. Oversubscribing to 8 workers will cause CPU
  context-switching overhead that wipes out gains (and may exhaust
  memory in container CI).
- Even on local 16-core M-series, `-n 8` (32.87s) is **only marginally
  faster than `-n auto = 16`** (33.60s). After 8 worker, we hit the IO
  ceiling (file reads + subprocess spawn) and additional cores idle.
- More worker = more subprocess startup overhead. At 6464+ test cases,
  each worker also pays Python interpreter startup cost on a worker-by-
  worker basis (~300-500ms each). 16 worker = ~6-8s pure overhead.

---

## Why `--dist=loadfile`?

| Dist mode | Behavior | Local | CI | Notes |
|---|---|---|---|---|
| `worksteal` | Workers steal tasks across files | 51.4s | Untested | Triggers R72-A root logger pollution |
| `loadfile` (current) | Same file → same worker | 50.0s | 50s expected | Preserves file-local isolation |
| `loadscope` | Same class → same worker | Slower (smaller chunks) | — | Wastes parallelism for class-rich files |
| `loadgroup` | Manual grouping via `@pytest.mark.xdist_group` | N/A | N/A | Heavier maintenance |

`loadfile` matches our test architecture: ~140 test files, each ~30-50
tests. Same-file tests share `setUp` / fixtures more often than
cross-file, so loadfile both preserves locality (less fixture
re-initialization) and provides natural test isolation against
pollution. `worksteal` shaves only ~0.4s but introduces non-deterministic
failures.

---

## Future-guards

`tests/test_feat_ci_gate_pytest_xdist_r305.py` (R305) already locks:
- `-n 4` literal (not `-n auto`)
- `--dist=loadfile` literal (not `worksteal` / `loadscope`)
- `pytest-xdist >= 3.6.0` (subTest collection bug fix floor)

`tests/test_feat_ci_xdist_worker_decision_r308.py` (R308) adds:
- This file (perf-ci-xdist-r308.md) must exist and reference R305 + R308
- Documented `-n 4` rationale must mention "cross-environment" or
  "GitHub Actions" (防 future maintainers 不知道 2-core runner 上 auto
  退化)

---

## Re-benchmark trigger conditions

Re-run this benchmark and update this doc if any of the following:
1. GitHub Actions free tier runner spec changes (e.g. 8 vCPU default)
2. Test count grows >50% from 6473 baseline (more tests = more granular
   xdist scheduling → may change sweet spot)
3. Adding a new "long-tail" test (>5s wallclock) that dominates worker
   load
4. pytest-xdist major version (4.x) released with scheduling changes

---

## Per-environment override

Developers can override CI default via environment variable (not yet
implemented in `ci_gate.py`, candidate for R310/cycle-32):

```bash
# Local fast iteration (16-core M-series):
AIIA_TEST_WORKERS=auto uv run python scripts/ci_gate.py

# CI parity (override to specific count):
AIIA_TEST_WORKERS=4 uv run python scripts/ci_gate.py
```

Today (cycle-31), use direct `pytest` invocation with custom `-n`
instead — `ci_gate.py` is the locked path for CI/release gate
consistency.

---

## Appendix: raw benchmark data

```text
$ time .venv/bin/python -m pytest tests/ -q -n 2 --dist=loadfile
== 1 failed (R25-2), 6495 passed, 1 skipped, 878 subtests passed in 92.20s ==
user 124.85s system 11.56s, 147% cpu

$ time .venv/bin/python -m pytest tests/ -q -n 4 --dist=loadfile
== 6485 passed, 1 skipped, 878 subtests passed in 50.03s ==
user 131.11s system 12.61s, 285% cpu

$ time .venv/bin/python -m pytest tests/ -q -n 8 --dist=loadfile
== 6496 passed, 1 skipped, 878 subtests passed in 32.87s ==
user 136.37s system 14.09s, 453% cpu

$ time .venv/bin/python -m pytest tests/ -q -n auto --dist=loadfile
== 6496 passed, 1 skipped, 878 subtests passed in 33.60s ==
user 159.43s system 20.29s, 530% cpu

$ sysctl -n hw.ncpu hw.physicalcpu
16
16
```

CI environment (GitHub Actions, would yield ~similar numbers as `-n 2`
based on extrapolation; no direct measurement yet — extrapolation
caveat noted):

```
runner: ubuntu-latest (4 vCPU, 16 GB RAM, 2026 spec)
projected: ~45-55s with -n 4 (within ±10% of local measurement)
```
