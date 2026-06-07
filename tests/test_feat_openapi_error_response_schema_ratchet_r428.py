"""R428 (cycle-49 #A1) — R422 ratchet uplift 第 1 次 + 实施改进 + ratchet up
三位一体 第 3 次 (meta-invariant 5th app, 元方法学层超稳定后第 1 应用)。

血脉关系 (Lineage):
- R422 (cycle-48 #B1): 启动 v3.10.3 OpenAPI error response schema parity,
  baseline 5% (实测 3/51 = 5.88%)
- **R428 (cycle-49 #A1)**: 1st ratchet uplift — coverage 5.88% → 21.57%,
  baseline ratchet 0.05 → 0.15 (实施 +8 个 schema)
- meta-invariant 累计应用: R414 (1st) → R418 (2nd) → R424 (3rd) → R426 (4th)
  → **R428 (5th)** → 元方法学层 (维度 15) 进入第 5 应用稳定期, 与 v3.6
  perf-baseline (9 应用) / API contract (11 应用) 等老牌方法学维度进入
  同一稳定梯队
- ratchet 模式累计应用: R412 → R418 → R422 → R426 → R428 (**5 应用**) →
  ratchet 模式 5 应用 = "工业化 + 巩固期"

R428 战略 (Strategy):
- R422 baseline 5% 启动后, 客户端集成痛点真实存在 (5xx 100% 无 schema
  → 全部靠 try-catch)
- R428 实施第一次 ratchet uplift, 选择高频 endpoint 添加 schema:
  - feedback.py POST /api/update-feedback: 400 / 500
  - task.py GET /api/tasks: 500
  - task.py GET /api/tasks/download: 400 / 500
  - task.py POST /api/tasks (create): 400 / 409 / 500
- 8 个 schema 推 coverage 5.88% → 21.57%, ratchet `MIN_ERROR_RESPONSE_SCHEMA_COVERAGE`
  0.05 → 0.15

R428 实施 (Implementation):
1. `feedback.py` POST /api/update-feedback 400 / 500: standard {status:
   "error", message} envelope
2. `task.py` GET /api/tasks (active) 500: standard {status: "error",
   message}
3. `task.py` GET /api/tasks/download 400 / 500: standard {status:
   "error", message}
4. `task.py` POST /api/tasks (create) 400 / 409 / 500: extended {success:
   false, error: <code>, message} envelope (与 200 OK {success: true,
   task_id} 对称, 用 error code 分类)

R428 invariant (3 层 + lineage marker):
- **Layer 1 (coverage 实测)**: 实测 coverage ≥ 0.20 (留 1% buffer 防抖动)
- **Layer 2 (ratchet 已上调)**: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE ≥ 0.15
- **Layer 3 (lineage marker)**: 引用 R422 + meta-invariant 5th
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_feat_openapi_error_response_schema_parity_r422 import (
    MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
    _collect_all_error_responses,
)


class TestR428CoverageUpliftToTwentyPlus(unittest.TestCase):
    """R428 Layer 1: 实测 coverage 应 ≥ 0.20 (留 1% buffer)。"""

    def test_actual_coverage_above_20_percent(self) -> None:
        all_r = _collect_all_error_responses()
        total = len(all_r)
        with_schema = sum(1 for _, _, _, hs in all_r if hs)
        coverage = with_schema / max(total, 1)
        self.assertGreaterEqual(
            coverage,
            0.20,
            f"R428 Layer 1: 实测 coverage = {coverage:.2%} "
            f"({with_schema}/{total}) < 0.20 sanity. "
            f"R428 cycle-49 #A1 ratchet uplift 期望实测 ≥ 0.20, 如果掉到此线下 "
            f"说明有人删了 schema 或加了大量无 schema 的新 error response。",
        )


class TestR428RatchetThresholdUplift(unittest.TestCase):
    """R428 Layer 2: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE 已 ratchet 上调到 0.15。"""

    def test_ratchet_threshold_at_least_15_percent(self) -> None:
        self.assertGreaterEqual(
            MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
            0.15,
            f"R428 Layer 2: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE = "
            f"{MIN_ERROR_RESPONSE_SCHEMA_COVERAGE} < 0.15, R428 cycle-49 #A1 "
            f"ratchet uplift 要求把 R422 阈值从 0.05 推到 0.15, 此 invariant "
            f"防止 future cycle 误把它下调回 0.05。",
        )

    def test_ratchet_threshold_not_above_one(self) -> None:
        self.assertLessEqual(MIN_ERROR_RESPONSE_SCHEMA_COVERAGE, 1.0)


class TestR428MetaInvariantLineage(unittest.TestCase):
    """R428 Layer 3: lineage marker 锁血脉。"""

    def test_this_file_references_r422_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R422",):
            self.assertIn(
                prior,
                text,
                f"R428: must cite prior lineage: {prior}",
            )

    def test_this_file_references_meta_invariant_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R414", "R418", "R424", "R426"):
            self.assertIn(
                prior,
                text,
                f"R428: must cite meta-invariant lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_5th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("meta-invariant 5th app", "ratchet uplift"):
            self.assertIn(kw, text, f"R428: missing milestone keyword: {kw!r}")

    def test_this_file_documents_implementation(self) -> None:
        """R428 doc 必须说明改了哪些 endpoint."""
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("feedback.py", "task.py", "/api/tasks"):
            self.assertIn(
                kw,
                text,
                f"R428: must document implementation: {kw}",
            )


if __name__ == "__main__":
    unittest.main()
