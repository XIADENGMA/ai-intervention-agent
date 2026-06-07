"""R436 (cycle-50 #A1) — R422 ratchet uplift 第 3 次 + 实施改进 + ratchet
up 三位一体 第 5 次 (meta-invariant 8th app)。

血脉关系 (Lineage):
- R422 (cycle-48 #B1): baseline 5% (实测 3/51 = 5.88%)
- R428 (cycle-49 #A1): 1st uplift — 5.88% → 21.57%, ratchet 0.05 → 0.15
  (实施 +8 schema, focus feedback.py + task.py POST)
- R432 (cycle-49 #C1): 2nd uplift — 21.57% → 37.25%, ratchet 0.15 → 0.30
  (实施 +8 schema, focus notification.py)
- **R436 (cycle-50 #A1)**: 3rd uplift — 37.25% → 52.94%, ratchet 0.30 →
  0.50 (实施 +8 schema, focus system.py admin endpoints + task.py extend)
- meta-invariant 累计应用 8 (R414/R418/R424/R426/R428/R430/R432/R436) →
  元方法学层 (维度 15) 进入第 8 应用稳定深化期
- ratchet 模式累计应用 7 (R412/R418/R422/R426/R428/R432/R436) → 巩固期
  完全成熟
- "实施改进 + ratchet up 三位一体" 累计 5 应用 (R418/R426/R428/R432/R436) →
  pattern 完全工业化

R436 战略 (Strategy):
- R432 完成 v3.10.3 2nd uplift 后, system.py admin endpoints 仍是 schema
  覆盖洼地 (rotate-api-token / get-token-age / open-config-file /
  healthz / set-log-level 等)
- system.py admin endpoints 多为 sensitive operations (rotation /
  log level 调整等), schema 不完整 = 客户端 (web settings + CLI) 无法
  正确处理错误分支
- R436 实施第 3 次 ratchet uplift, 重点覆盖 system.py admin endpoints +
  task.py 收尾:
  - system.py: POST /api/open-config-file 400/403/500
  - system.py: GET /api/healthz 503
  - system.py: POST /api/set-log-level 400/403
  - task.py: GET /api/tasks/<id> 404/500 (line 1822)
- 8 个 schema 推 coverage 37.25% → 52.94%, ratchet
  `MIN_ERROR_RESPONSE_SCHEMA_COVERAGE` 0.30 → 0.50

R436 实施 (Implementation):
1. `system.py` POST /api/open-config-file 400 / 403 / 500: extended envelope
   with error code (path_not_found / non_loopback / non_whitelisted)
2. `system.py` GET /api/healthz 503: unhealthy envelope with timestamp + checks
3. `system.py` POST /api/set-log-level 400 / 403: standard envelope
4. `task.py` GET /api/tasks/<id> 404 / 500: standard envelope

R436 invariant (3 层 + lineage marker):
- **Layer 1 (coverage 实测)**: 实测 coverage ≥ 0.52 (留 1% buffer 防抖动)
- **Layer 2 (ratchet 已上调)**: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE ≥ 0.50
- **Layer 3 (lineage marker)**: 引用 R422/R428/R432 + meta-invariant 8th
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_feat_openapi_error_response_schema_parity_r422 import (
    MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
    _collect_all_error_responses,
)


class TestR436CoverageUpliftToFiftyPlus(unittest.TestCase):
    """R436 Layer 1: 实测 coverage 应 ≥ 0.52 (留 1% buffer)。"""

    def test_actual_coverage_above_52_percent(self) -> None:
        all_r = _collect_all_error_responses()
        total = len(all_r)
        with_schema = sum(1 for _, _, _, hs in all_r if hs)
        coverage = with_schema / max(total, 1)
        self.assertGreaterEqual(
            coverage,
            0.52,
            f"R436 Layer 1: 实测 coverage = {coverage:.2%} "
            f"({with_schema}/{total}) < 0.52 sanity. "
            f"R436 cycle-50 #A1 ratchet uplift 期望实测 ≥ 0.52, 如果掉到此 "
            f"线下说明有人删了 schema 或加了大量无 schema 的新 error response。",
        )


class TestR436RatchetThresholdUplift(unittest.TestCase):
    """R436 Layer 2: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE 已 ratchet 上调到 0.50。"""

    def test_ratchet_threshold_at_least_50_percent(self) -> None:
        self.assertGreaterEqual(
            MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
            0.50,
            f"R436 Layer 2: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE = "
            f"{MIN_ERROR_RESPONSE_SCHEMA_COVERAGE} < 0.50, R436 cycle-50 #A1 "
            f"ratchet uplift 要求把 R422 阈值从 0.30 推到 0.50。此 invariant "
            f"防止 future cycle 误把它下调回 0.30。",
        )


class TestR436MetaInvariantLineage(unittest.TestCase):
    """R436 Layer 3: lineage marker 锁血脉。"""

    def test_this_file_references_r422_r428_r432_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R422", "R428", "R432"):
            self.assertIn(
                prior,
                text,
                f"R436: must cite prior ratchet lineage: {prior}",
            )

    def test_this_file_references_meta_invariant_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R414", "R418", "R424", "R426", "R430"):
            self.assertIn(
                prior,
                text,
                f"R436: must cite meta-invariant lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_8th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("meta-invariant 8th app", "ratchet uplift"):
            self.assertIn(kw, text, f"R436: missing milestone keyword: {kw!r}")

    def test_this_file_documents_implementation(self) -> None:
        """R436 doc 必须说明改了哪些 endpoint."""
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "system.py",
            "open-config-file",
            "healthz",
            "set-log-level",
            "task.py",
        ):
            self.assertIn(
                kw,
                text,
                f"R436: must document implementation: {kw}",
            )


if __name__ == "__main__":
    unittest.main()
