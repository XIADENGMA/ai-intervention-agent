"""R418 · OpenAPI property description ratchet uplift invariant
(cycle-47 #D1, **real improvement + R412 ratchet up + self-validation 2nd app**)。

R412 (cycle-47 #A1) 启动了 v3.10.2 OpenAPI property description completeness
invariant, 锁初始 baseline 45% (略低于当时实际 50% 留 5% 缓冲)。R418 在
同 cycle 实施 **real improvement**:

1. **加 ~25 个 description** 到 web_ui_routes/task.py + feedback.py 高频字段
   (task_id / created_at / auto_resubmit_timeout / remaining_time / server_time /
   prompt / predefined_options / 等);
2. **ratchet up** ``MIN_NON_ENVELOPE_DESC_COVERAGE``: 0.45 → 0.70 (实际
   coverage 从 50% → 75%);

R418 是 R412 的 **self-validation + improvement** 配对应用, 实施模式:

- R412 = 防止退化 (lock current state minus buffer);
- R418 = 主动改进 (raise the bar);

R412 + R418 = "ratchet" 完整模式 — invariant 不仅锁现状, 还驱动持续改进。

R418 invariant (3 层)
---------------------

1. **Layer 1 (Coverage 新阈值生效)**: 验证 R412 的
   ``MIN_NON_ENVELOPE_DESC_COVERAGE`` 已 ratchet 至 ≥ 0.70 (不允许回退);
2. **Layer 2 (实际 coverage 满足新阈值)**: 当前 codebase 实际 coverage
   ≥ 0.70;
3. **Layer 3 (lineage marker)**: ratchet 操作 + R412 lineage 引用。

methodology lineage
-------------------

- R412 (cycle-47 #A1): v3.10.2 第二个 sub-pattern, 锁 baseline 45%
- **R418 (cycle-47 #D1)**: **ratchet up 至 70%, 实施 + lock 配对**

R418 与 R414 (R406 negative self-validation) 一起, 形成 **invariant 自我验
证 / 自我改进** 两类元模式:

| Pass | R#   | 类型                                  | 价值                         |
| ---- | ---- | ------------------------------------- | ---------------------------- |
| 1st  | R414 | negative self-validation (R406 的)    | 保证 invariant fire when broken |
| 2nd  | R418 | ratchet improvement (R412 的)         | 驱动持续改进而非锁现状        |

self-improvement 模式可扩展到其他 ratchet 型 invariant:
- doc-parity coverage ratchet
- i18n key coverage ratchet
- security header strict 程度 ratchet

如果 self-improvement / self-validation 累计 3+ 应用, 可考虑提升为 **第 15
个方法学维度: invariant 元层级保护 (meta-invariants)**, 涵盖 negative test
+ ratchet + drift detection 等 self-protecting 模式。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

sys.path.insert(0, str(TESTS_DIR))


def _import_r412_module():
    """Import R412 module to read the ratcheted MIN_NON_ENVELOPE_DESC_COVERAGE."""
    return importlib.import_module(
        "test_feat_openapi_property_description_completeness_r412"
    )


class TestLayer1RatchetThresholdUplifted:
    """Layer 1: R412 的 MIN_NON_ENVELOPE_DESC_COVERAGE 已 ratchet 至 ≥ 0.70。"""

    def test_min_coverage_ratcheted_to_70_percent(self):
        r412 = _import_r412_module()
        actual = r412.MIN_NON_ENVELOPE_DESC_COVERAGE
        assert actual >= 0.70, (
            f"R418-L1: R412's MIN_NON_ENVELOPE_DESC_COVERAGE is {actual:.2f}, "
            f"expected >= 0.70. ratchet operation must NOT regress — if you "
            f"intentionally need to lower this, document the rationale in a "
            f"new R# commit (and consider whether R418 is still valid)."
        )


class TestLayer2ActualCoverageMeetsNewThreshold:
    """Layer 2: 当前 codebase 实际 coverage ≥ 0.70。"""

    def test_actual_coverage_above_70_percent(self):
        r412 = _import_r412_module()
        props = r412._collect_all_properties()
        envelope = r412.ENVELOPE_FIELD_NAMES
        non_env = [(f, p, n, pd) for f, p, n, pd in props if n not in envelope]
        if not non_env:
            return
        with_desc = sum(1 for _, _, _, pd in non_env if "description" in pd)
        ratio = with_desc / len(non_env)
        assert ratio >= 0.70, (
            f"R418-L2: actual non-envelope description coverage is "
            f"{ratio:.1%} ({with_desc}/{len(non_env)}), expected >= 70%. "
            f"R418 ratchet is incompatible with current state — either "
            f"add more descriptions, or roll back R418 ratchet."
        )


class TestLayer3LineageMarker:
    """Layer 3: methodology lineage + ratchet 操作记录。"""

    def test_this_file_contains_r418_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R418" in text

    def test_this_file_references_r412_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R412" in text, "R418: must cite R412 (the ratchet target)"

    def test_this_file_marks_ratchet_pattern(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("ratchet up", "real improvement", "self-improvement"):
            assert kw in text, f"R418: missing keyword: {kw!r}"

    def test_this_file_references_r414_meta_invariant_pattern(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R414" in text, "R418: must cite R414 (sister self-validation pattern)"


def teardown_module(_module):
    if str(TESTS_DIR) in sys.path:
        sys.path.remove(str(TESTS_DIR))
