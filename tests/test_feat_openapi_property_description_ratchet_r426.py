"""R426 (cycle-48 #D1) — R412 ratchet uplift 第 2 次 + 实施改进 + ratchet up
三位一体 commit (meta-invariant 4th app)。

血脉关系 (Lineage):
- R412 (cycle-47 #A1): 启动 v3.10.2 OpenAPI property description completeness
  ratchet, baseline 45%
- R418 (cycle-47 #D1): 1st ratchet uplift — coverage 50% → 75%, baseline
  ratchet 45% → 70% (meta-invariant 2nd app)
- **R426 (cycle-48 #D1)**: 2nd ratchet uplift — coverage 70% → 85%, baseline
  ratchet 70% → 80% (meta-invariant 4th app)
- meta-invariant 累计应用: R414 (1st) → R418 (2nd) → R424 (3rd) → R426 (4th)
  → 元方法学层 (维度 15) 进入 4 应用稳定阶段

R426 战略 (Strategy):
- cycle-47 R418 实现 R412 第一次 ratchet uplift 后, 还有 ~20 个非
  envelope property 缺 description, 主要集中在 `notification.py`
  (bark_* / *Enabled / *Volume 等通知配置字段) 和 `feedback.py` / `system.py`
- 这些字段是 OpenAPI consumer 频繁查询的配置接口, 缺 description 直接
  伤客户端集成体验
- R426 加 ~14 个 description 推 coverage 70% → 85%, 然后 ratchet 上调
  `MIN_NON_ENVELOPE_DESC_COVERAGE` 0.70 → 0.80

R426 实施 (Implementation):
1. `notification.py`:
   - bark_url / bark_icon / bark_action (POST /api/test-bark-notification)
   - enabled / webEnabled / soundEnabled / soundVolume (POST 配置更新)
   - barkEnabled / barkUrl / barkDeviceKey / barkIcon / barkAction
   - macosNativeEnabled
2. `feedback.py`:
   - predefined_options / task_id (POST /api/update-feedback)
3. `system.py`:
   - token_length / has_token / token_length / rotated_at / age_seconds
     (rotation + status endpoints)

R426 invariant (3 层 + lineage marker):
- **Layer 1 (coverage 实测)**: 实测 coverage ≥ 0.83 (留 2% buffer 防抖动)
- **Layer 2 (ratchet 已上调)**: MIN_NON_ENVELOPE_DESC_COVERAGE ≥ 0.80
- **Layer 3 (lineage marker)**: 引用 R412/R418/R424 + meta-invariant 4th
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_feat_openapi_property_description_completeness_r412 import (
    ENVELOPE_FIELD_NAMES,
    MIN_NON_ENVELOPE_DESC_COVERAGE,
    _collect_all_properties,
)


class TestR426CoverageUpliftToEightyPlus(unittest.TestCase):
    """R426 Layer 1: 实测 coverage 应 ≥ 0.83 (留 2% buffer)。"""

    def test_actual_coverage_above_83_percent(self) -> None:
        props = _collect_all_properties()
        non_envelope = [
            (f, p, n, pd) for f, p, n, pd in props if n not in ENVELOPE_FIELD_NAMES
        ]
        with_desc = sum(1 for _, _, _, pd in non_envelope if "description" in pd)
        coverage = with_desc / max(len(non_envelope), 1)
        self.assertGreaterEqual(
            coverage,
            0.83,
            f"R426 Layer 1: 实测 coverage = {coverage:.2%} "
            f"({with_desc}/{len(non_envelope)}) < 0.83 sanity. "
            f"R426 cycle-48 ratchet uplift 期望实测 ≥ 0.83, 如果掉到此线下 "
            f"说明有人删了 description 或加了大量无 description 的新字段。",
        )


class TestR426RatchetThresholdUplift(unittest.TestCase):
    """R426 Layer 2: MIN_NON_ENVELOPE_DESC_COVERAGE 已 ratchet 上调到 0.80。"""

    def test_ratchet_threshold_at_least_80_percent(self) -> None:
        self.assertGreaterEqual(
            MIN_NON_ENVELOPE_DESC_COVERAGE,
            0.80,
            f"R426 Layer 2: MIN_NON_ENVELOPE_DESC_COVERAGE = "
            f"{MIN_NON_ENVELOPE_DESC_COVERAGE} < 0.80, R426 cycle-48 #D1 "
            f"ratchet uplift 要求把 R412 阈值从 0.70 推到 0.80, 此 invariant "
            f"防止 future cycle 误把它下调回 0.70。",
        )

    def test_ratchet_threshold_not_above_one(self) -> None:
        self.assertLessEqual(MIN_NON_ENVELOPE_DESC_COVERAGE, 1.0)


class TestR426MetaInvariantLineage(unittest.TestCase):
    """R426 Layer 3: lineage marker 锁血脉。"""

    def test_this_file_references_r412_r418_r424(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R412", "R418", "R424"):
            self.assertIn(
                prior,
                text,
                f"R426: must cite prior lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_4th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("meta-invariant 4th app", "ratchet uplift"):
            self.assertIn(kw, text, f"R426: missing milestone keyword: {kw!r}")

    def test_this_file_documents_implementation(self) -> None:
        """R426 doc 必须说明改了什么 (which files / which properties)。"""
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("notification.py", "feedback.py", "system.py"):
            self.assertIn(
                kw,
                text,
                f"R426: must document implementation file: {kw}",
            )


if __name__ == "__main__":
    unittest.main()
