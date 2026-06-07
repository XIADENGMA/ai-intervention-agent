"""R440 (cycle-51 #A1) — v3.10.3 OpenAPI error response schema parity
ratchet 4th uplift (52.94% → 70.59%, ratchet 0.50 → 0.70).

血脉关系 (Lineage):
- R422 (cycle-48 #B1) — baseline 5%
- R428 (cycle-49 #A1) — 1st uplift, +8 schemas, coverage → 21.57%, ratchet → 0.15
- R432 (cycle-49 #C1) — 2nd uplift, +8 schemas, coverage → 37.25%, ratchet → 0.30
- R436 (cycle-50 #A1) — 3rd uplift, +8 schemas, coverage → 52.94%, ratchet → 0.50
- **R440 (cycle-51 #A1) — 4th uplift, +9 schemas, coverage → 70.59%, ratchet → 0.70**
- meta-invariant 累计应用 10 (R414/R418/R424/R426/R428/R430/R432/R436/R438/**R440**)

战略 (Strategy):
- v3.10.3 OpenAPI error schema 是 v3.10 系列第 3 sub-pattern, 推动 OpenAPI
  contract 完整性从 happy path 扩展到 error path
- R440 推到 70.59% 是 *决胜 threshold* — 客户端能 *默认假设* error 响应
  有 schema (因为 7 成都有), 剩余 30% 多是 special cases 或还在 audit
- ratchet pattern 累计应用 8 (R412/R418/R422/R426/R428/R432/R436/R440)
  → 巩固期持续深化, "实施 + ratchet up 三位一体" 累计 6 应用 (R418/R426/
  R428/R432/R436/R440)

实施 (R440 cycle 增加 9 个 schema):
- task.py POST /api/tasks/<id>/extend: 400 / 404 / 422 / 500 (4 个)
- task.py POST /api/tasks/<id>/freeze: 400 / 404 / 409 / 500 (4 个)
- feedback.py POST /api/submit: 429 (1 个 with retry_after hint)

业务价值 (Business value):
- task.py 是 user-facing 倒计时操作的关键端点 (extend / freeze), 客户端
  需要根据 error code 区分 UI 状态 (按钮 disabled / 提示文案)
- feedback.py 429 的 retry_after schema 让客户端能正确 backoff 重试
- 总计 9 个新 schema 都带 error_code 字段, 帮助客户端实现 enum-based
  错误分类逻辑

设计 (Design, 4 layers):
- Layer 1 (coverage actual): 实际 coverage ≥ 0.70 (含 buffer)
- Layer 2 (ratchet threshold): MIN_ERROR_RESPONSE_SCHEMA_COVERAGE ≥ 0.70
- Layer 3 (lineage marker): 引用 R422/R428/R432/R436 血脉
- Layer 4 (milestone marker): 记录 v3.10.3 ratchet 4th 与 7 成决胜 threshold
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_feat_openapi_error_response_schema_parity_r422 import (
    MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
    _collect_all_error_responses,
)


class TestR440CoverageUpliftTo70Plus(unittest.TestCase):
    """Layer 1: 实际 coverage ≥ 0.70 (含 buffer)。"""

    def test_actual_coverage_above_70_percent(self) -> None:
        items = _collect_all_error_responses()
        with_schema = sum(1 for _, _, _, hs in items if hs)
        coverage = with_schema / len(items) if items else 0.0
        self.assertGreaterEqual(
            coverage,
            0.70,
            f"R440 cycle-51 #A1: 期望 OpenAPI 4xx/5xx response schema "
            f"coverage ≥ 70% (含 buffer), 实际 {with_schema}/{len(items)} = "
            f"{coverage:.2%}。如果回归至 < 70%, 检查是否有 endpoint 的 "
            f"schema 被移除, 或新增了 endpoint 但忘记加 schema。",
        )


class TestR440RatchetThresholdUplift(unittest.TestCase):
    """Layer 2: ratchet 阈值已升至 0.70。"""

    def test_ratchet_threshold_at_least_70_percent(self) -> None:
        self.assertGreaterEqual(
            MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
            0.70,
            f"R440 cycle-51 #A1: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE 应 "
            f"≥ 0.70 (ratchet 4th uplift), 实际 = "
            f"{MIN_ERROR_RESPONSE_SCHEMA_COVERAGE}. 如果阈值被回退至 "
            f"< 0.70, 这违反 ratchet 单调递增设计 — ratchet baseline 不允许"
            f"下调, 只能向上 uplift。",
        )

    def test_ratchet_threshold_not_above_one(self) -> None:
        """物理上限校验。"""
        self.assertLessEqual(MIN_ERROR_RESPONSE_SCHEMA_COVERAGE, 1.0)


class TestR440MetaInvariantLineage(unittest.TestCase):
    """Layer 3 + 4: lineage marker + milestone marker。"""

    def test_this_file_references_r422_r428_r432_r436_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R422", "R428", "R432", "R436"):
            self.assertIn(
                prior,
                text,
                f"R440 must reference v3.10.3 ratchet lineage: {prior}",
            )

    def test_this_file_references_meta_invariant_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in (
            "R414",
            "R418",
            "R424",
            "R426",
            "R428",
            "R430",
            "R432",
            "R436",
            "R438",
        ):
            self.assertIn(
                prior,
                text,
                f"R440 must reference meta-invariant lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_10th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "meta-invariant 累计应用 10",
            text,
            "R440 应该明确记录是 meta-invariant 第 10 应用",
        )

    def test_this_file_marks_ratchet_4th_uplift(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "ratchet 4th uplift",
            text.lower().replace("ratchet 4th", "ratchet 4th"),
            "R440 应该明确记录是 ratchet 第 4 次 uplift",
        )

    def test_this_file_documents_implementation(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "task.py POST /api/tasks/<id>/extend",
            "task.py POST /api/tasks/<id>/freeze",
            "feedback.py POST /api/submit",
        ):
            self.assertIn(kw, text, f"R440 应该记录实施的端点: {kw}")


if __name__ == "__main__":
    unittest.main()
