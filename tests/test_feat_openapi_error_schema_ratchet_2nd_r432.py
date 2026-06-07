"""R432 (cycle-49 #C1) — R422 ratchet uplift 第 2 次 + 实施改进 + ratchet
up 三位一体 第 4 次 (meta-invariant 7th app, 元方法学层超巩固期 + 1)。

血脉关系 (Lineage):
- R422 (cycle-48 #B1): 启动 v3.10.3 OpenAPI error response schema parity,
  baseline 5% (实测 3/51 = 5.88%)
- R428 (cycle-49 #A1): 1st ratchet uplift — coverage 5.88% → 21.57%,
  baseline 0.05 → 0.15 (实施 +8 schema, 焦点 feedback.py + task.py)
- **R432 (cycle-49 #C1)**: 2nd ratchet uplift — coverage 21.57% → 37.25%,
  baseline 0.15 → 0.30 (实施 +8 schema, 焦点 notification.py)
- meta-invariant 累计应用: R414 → R418 → R424 → R426 → R428 → R430 →
  **R432 (7th app)** → 元方法学层 (维度 15) 进入超巩固期 + 1
- ratchet 模式累计应用: R412 → R418 → R422 → R426 → R428 → **R432 (6 应
  用)** → 进入巩固期深化
- "实施改进 + ratchet up 三位一体" 累计 4 应用: R418 (R412 1st) → R426
  (R412 2nd) → R428 (R422 1st) → **R432 (R422 2nd)** → "三位一体" 模式
  成熟稳定

R432 战略 (Strategy):
- R428 完成 v3.10.3 第 1 次 ratchet uplift (5% → 15%) 后, 关键 endpoint
  notification.py 的 500 responses 仍全部缺 schema
- notification.py 是 user-facing 配置接口, 客户端 (web settings page) 频
  繁查询, 缺 schema 直接伤接入体验
- R432 实施第 2 次 ratchet uplift, 重点覆盖 notification.py:
  - test-bark-notification 400 / 500
  - trigger-task-notification 500
  - notification config update 500
  - notification config GET 500 (config snapshot)
  - feedback config GET 500
  - feedback config update 400 / 500
- 8 个 schema 推 coverage 21.57% → 37.25%, ratchet
  `MIN_ERROR_RESPONSE_SCHEMA_COVERAGE` 0.15 → 0.30

R432 实施 (Implementation):
1. `notification.py` POST /api/test-bark-notification 400 / 500: standard envelope
2. `notification.py` POST /api/trigger-task-notification 500
3. `notification.py` POST /api/notification-config 500
4. `notification.py` GET /api/notification-config 500
5. `notification.py` GET /api/get-feedback-config 500
6. `notification.py` POST /api/update-feedback-config 400 / 500

R432 invariant (3 层 + lineage marker):
- **Layer 1 (coverage 实测)**: 实测 coverage ≥ 0.35 (留 2% buffer 防抖动)
- **Layer 2 (ratchet 已上调)**: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE ≥ 0.30
- **Layer 3 (lineage marker)**: 引用 R422 + R428 + meta-invariant 7th
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_feat_openapi_error_response_schema_parity_r422 import (
    MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
    _collect_all_error_responses,
)


class TestR432CoverageUpliftToThirtyFivePlus(unittest.TestCase):
    """R432 Layer 1: 实测 coverage 应 ≥ 0.35 (留 2% buffer)。"""

    def test_actual_coverage_above_35_percent(self) -> None:
        all_r = _collect_all_error_responses()
        total = len(all_r)
        with_schema = sum(1 for _, _, _, hs in all_r if hs)
        coverage = with_schema / max(total, 1)
        self.assertGreaterEqual(
            coverage,
            0.35,
            f"R432 Layer 1: 实测 coverage = {coverage:.2%} "
            f"({with_schema}/{total}) < 0.35 sanity. "
            f"R432 cycle-49 #C1 ratchet uplift 期望实测 ≥ 0.35, 如果掉到此 "
            f"线下说明有人删了 schema 或加了大量无 schema 的新 error response。",
        )


class TestR432RatchetThresholdUplift(unittest.TestCase):
    """R432 Layer 2: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE 已 ratchet 上调到 0.30。"""

    def test_ratchet_threshold_at_least_30_percent(self) -> None:
        self.assertGreaterEqual(
            MIN_ERROR_RESPONSE_SCHEMA_COVERAGE,
            0.30,
            f"R432 Layer 2: MIN_ERROR_RESPONSE_SCHEMA_COVERAGE = "
            f"{MIN_ERROR_RESPONSE_SCHEMA_COVERAGE} < 0.30, R432 cycle-49 #C1 "
            f"ratchet uplift 要求把 R422 阈值从 0.15 推到 0.30。此 invariant "
            f"防止 future cycle 误把它下调回 0.15。",
        )

    def test_ratchet_threshold_not_above_one(self) -> None:
        self.assertLessEqual(MIN_ERROR_RESPONSE_SCHEMA_COVERAGE, 1.0)


class TestR432MetaInvariantLineage(unittest.TestCase):
    """R432 Layer 3: lineage marker 锁血脉。"""

    def test_this_file_references_r422_r428_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R422", "R428"):
            self.assertIn(
                prior,
                text,
                f"R432: must cite prior lineage: {prior}",
            )

    def test_this_file_references_meta_invariant_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R414", "R418", "R424", "R426", "R430"):
            self.assertIn(
                prior,
                text,
                f"R432: must cite meta-invariant lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_7th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("meta-invariant 7th app", "ratchet uplift"):
            self.assertIn(kw, text, f"R432: missing milestone keyword: {kw!r}")

    def test_this_file_documents_implementation(self) -> None:
        """R432 doc 必须说明改了哪些 notification.py endpoint."""
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in (
            "notification.py",
            "test-bark-notification",
            "trigger-task-notification",
        ):
            self.assertIn(
                kw,
                text,
                f"R432: must document implementation: {kw}",
            )


if __name__ == "__main__":
    unittest.main()
