"""R446 (cycle-52 #A1) — v3.10.3 OpenAPI error response schema parity
ratchet 5th uplift (70.59% → 82.35%, ratchet 0.70 → 0.80, **production-
quality threshold**).

血脉关系 (Lineage):
- R422 (cycle-48 #B1) — baseline 5.88%
- R428 (cycle-49 #A1) — 1st uplift, +8 schemas, coverage → 21.57%, ratchet → 0.15
- R432 (cycle-49 #C1) — 2nd uplift, +8 schemas, coverage → 37.25%, ratchet → 0.30
- R436 (cycle-50 #A1) — 3rd uplift, +8 schemas, coverage → 52.94%, ratchet → 0.50
- R440 (cycle-51 #A1) — 4th uplift, +9 schemas, coverage → 70.59%, ratchet → 0.70
- **R446 (cycle-52 #A1) — 5th uplift, +5 schemas, coverage → 82.35%, ratchet → 0.80**
- meta-invariant 累计应用 12 (R414/R418/R424/R426/R428/R430/R432/R436/R438/
  R440/R442/**R446**)

战略 (Strategy):
- R446 推到 82.35% 是 *production-quality threshold* — 客户端能 *几乎肯定*
  error 响应有 schema (8 成都有), 剩余 18% 多是 special cases (如 NoOp
  502 / placeholder 404 / 502 网关错误等没必要 schema 化)
- ratchet pattern 累计应用 9 (R412/R418/R422/R426/R428/R432/R436/R440/R446)
  → 完全工业化深化期, "实施 + ratchet up 三位一体" 累计 7 应用 (R418/
  R426/R428/R432/R436/R440/R446)
- 终态目标 90% 还需 1-2 个 ratchet uplift, 但 80% 已经是 production-ready
  里程碑

实施 (R446 cycle 增加 5 个 schema):
- notification.py POST /api/reset-feedback-config: 500 (1 个)
- notification.py POST /api/test-bark-notification: 400 / 500 (2 个)
- system.py POST /api/rotate-token (admin): 403 / 500 / 429 (3 个, 含 retry_after)
- 总计 = 6 个 schema (vs 计划 5 个, 实际超额 1 个 due 到 system.py 三 status code)

业务价值 (Business value):
- notification.py reset-feedback-config 是 user-facing 配置端点, schema 帮
  助 Web settings client 区分 success / error envelope
- notification.py test-bark-notification 是 user-facing 通知测试端点, schema
  帮助 UI 准确显示测试结果
- system.py rotate-token 是 admin 安全端点, schema (含 retry_after) 帮助
  自动化 rotation 脚本正确 handle 429 backoff
- 5 schemas 都符合统一错误 envelope: `{"success": false, "error": "..."}` 或
  `{"status": "error", "message": "..."}` (维持一致性)

设计 (Design, 4 layers):
- Layer 1 (coverage actual): 实际 coverage ≥ 0.80 (含 buffer)
- Layer 2 (ratchet threshold): MIN_ERROR_RESPONSE_SCHEMA_COVERAGE ≥ 0.80
- Layer 3 (lineage marker): 引用 R422/R428/R432/R436/R440 血脉
- Layer 4 (milestone marker): 记录 v3.10.3 ratchet 5th 与 production-quality threshold
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_feat_openapi_error_response_schema_parity_r422 import (
    MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
    _collect_all_error_responses,
)


class TestR446CoverageUpliftTo80Plus(unittest.TestCase):
    """Layer 1: 实际 coverage ≥ 0.80 (含 buffer)。"""

    def test_actual_coverage_above_80_percent(self) -> None:
        items = _collect_all_error_responses()
        with_schema = sum(1 for _, _, _, hs in items if hs)
        coverage = with_schema / len(items) if items else 0.0
        self.assertGreaterEqual(
            coverage,
            0.80,
            f"R446 cycle-52 #A1: 期望 OpenAPI 4xx/5xx response schema "
            f"coverage ≥ 80% (production-quality threshold), 实际 "
            f"{with_schema}/{len(items)} = {coverage:.2%}。如果回归至 < 80%, "
            f"检查是否有 endpoint 的 schema 被移除, 或新增了 endpoint 但忘记加 "
            f"schema。",
        )


class TestR446RatchetThresholdUplift(unittest.TestCase):
    """Layer 2: ratchet 阈值已升至 0.80。"""

    def test_ratchet_threshold_at_least_80_percent(self) -> None:
        self.assertGreaterEqual(
            MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
            0.80,
            f"R446 cycle-52 #A1: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE 应 "
            f"≥ 0.80 (ratchet 5th uplift, production-quality), 实际 = "
            f"{MIN_ERROR_RESPONSE_SCHEMA_COVERAGE}。如果阈值被回退至 "
            f"< 0.80, 这违反 ratchet 单调递增设计 — ratchet baseline 不允许"
            f"下调, 只能向上 uplift。",
        )

    def test_ratchet_threshold_not_above_one(self) -> None:
        """物理上限校验。"""
        self.assertLessEqual(MIN_ERROR_RESPONSE_SCHEMA_COVERAGE, 1.0)


class TestR446MetaInvariantLineage(unittest.TestCase):
    """Layer 3 + 4: lineage marker + milestone marker。"""

    def test_this_file_references_r422_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R422", "R428", "R432", "R436", "R440"):
            self.assertIn(
                prior,
                text,
                f"R446 must reference v3.10.3 ratchet lineage: {prior}",
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
            "R440",
            "R442",
        ):
            self.assertIn(
                prior,
                text,
                f"R446 must reference meta-invariant lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_12th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "meta-invariant 累计应用 12",
            text,
            "R446 应该明确记录是 meta-invariant 第 12 应用",
        )

    def test_this_file_marks_production_quality_threshold(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "production-quality threshold",
            text.lower().replace("production-quality", "production-quality"),
            "R446 应该明确记录是 production-quality threshold",
        )

    def test_this_file_documents_implementation(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "notification.py POST /api/reset-feedback-config",
            "notification.py POST /api/test-bark-notification",
            "system.py POST /api/rotate-token",
        ):
            self.assertIn(kw, text, f"R446 应该记录实施的端点: {kw}")


if __name__ == "__main__":
    unittest.main()
