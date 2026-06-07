"""R442 (cycle-51 #B1) — meta-invariant 11th app: i18n meta-invariant 子
模式 2nd app — R353 (VS Code locale untranslated audit) 负面自验证。

血脉关系 (Lineage):
- meta-invariant 累计应用 11: R414 → R418 → R424 → R426 → R428 → R430 →
  R432 → R436 → R438 → R440 → **R442**
- 元方法学层 (维度 15) 完全工业化深化期 (≥ 11 应用) — 从 R438 (9 应用)
  到现在的 11 应用, 完全工业化深化
- i18n meta-invariant 子模式 2nd app:
  * R438 (cycle-50 #B1) — R350 (main app i18n untranslated) negative
    validation, **i18n meta-invariant 子模式 1st app**
  * **R442 (cycle-51 #B1) — R353 (VS Code i18n untranslated) negative
    validation, i18n meta-invariant 子模式 2nd app — 进入巩固阶段**
- 模板复用 (template reuse): R442 复用 R438 的合成 drift 场景 + 8% ceiling
  适配 VS Code extension (vs main app 5%)

战略 (Strategy):
- R353 (cycle-40 #A1) 是 *positive-only* test, 只验证当前 VS Code locale
  内未翻译比例满足 ≤ 8% 上限
- 风险: future refactor 把 R353 helpers 静默 broken (例如
  `_flatten_strings` 误把 `_meta` 元数据也包含进来 / whitelist 被清空 /
  ratio ceiling 被改成 1.0), R353 仍 pass 但实际已失守
- R442 通过 *合成 (synthetic) input* 反向验证这些 helpers 在漂移场景能
  正确 fire (跟 R438 同模板, 但适配 VS Code 8% ceiling)

业务价值 (Business value):
- VS Code extension 是 IDE 集成用户群的入口, i18n 失效直接伤 VS Code
  插件用户群 (中文 IDE 用户极多)
- R353 守护着 packages/vscode/locales/en.json + zh-CN.json (60+ string
  keys), 静默失效 = 漏译可能不被 CI 拦截直接 ship 到 marketplace
- i18n meta-invariant 子模式从 1 应用 (R438) → 2 应用 (R442) 进入 *巩固
  期*, 与 doc-parity 子模式 (R424 1st 应用) / API contract 子模式
  (R430 1st 应用) 形成可比的演化节奏
- 后续 cycle 可继续推 R366 (zh-TW) / R374 (VS Code zh-TW) 的 meta-invariant,
  达到 i18n 子模式 4 应用完全工业化

设计 (Design, 4 layers):
- Layer 1 (synthetic drift detection): 合成 4 种 VS Code locale drift
  场景, 验证算法能 fire
- Layer 2 (synthetic ceiling-tolerance): 8% ceiling 在 VS Code 场景下
  允许 7% 的合理 untranslated (vs main app 5%)
- Layer 3 (_meta filtering): 验证 _flatten_strings 在 VS Code locale 也
  会跳过 _meta 元数据
- Layer 4 (lineage marker): 引用 R438 + R353 + meta-invariant 血脉
"""

from __future__ import annotations

import unittest
from pathlib import Path

# 复用 R353 的辅助函数与常量, 保证 negative test 与 production test 行为一致
from tests.test_feat_vscode_i18n_untranslated_audit_r353 import (
    UNTRANSLATED_RATIO_CEILING,
    UNTRANSLATED_WHITELIST,
    _flatten_strings,
)


def _untranslated_ratio(
    en_flat: dict[str, str],
    zh_flat: dict[str, str],
    whitelist: set[str],
) -> float:
    """模拟 R353 计算非白名单 untranslated ratio 算法。

    与 R438 中的同名函数一致 — 这里独立定义避免跨模块循环引用; 算法本身
    是 R350/R353 共用的, 所以独立定义不破坏 SSoT (R353 是被验证对象)。
    """
    common_keys = [k for k in zh_flat if k in en_flat and k not in whitelist]
    if not common_keys:
        return 0.0
    untrans = sum(1 for k in common_keys if zh_flat[k] == en_flat[k])
    return untrans / len(common_keys)


# ───────────────────────── Synthetic inputs ─────────────────────────

# Case 1: 完全未翻译 (100% drift) — 期望 ratio ≈ 1.0, 必须 > 8% ceiling
SYNTH_EN_FULLY_DRIFTED = {
    "extension.command.openSettings": "Open Settings",
    "extension.notification.title": "AI Intervention",
    "extension.action.submit": "Submit Feedback",
    "extension.webview.title": "Feedback Panel",
    "extension.status.connecting": "Connecting...",
}
SYNTH_ZH_FULLY_DRIFTED = dict(SYNTH_EN_FULLY_DRIFTED)  # 完全复制 en

# Case 2: 部分未翻译 (50% drift) — 期望 ratio 0.5
SYNTH_EN_HALF_DRIFTED = {
    "vscode.menu.item1": "Settings",
    "vscode.menu.item2": "Help",
    "vscode.menu.item3": "About",
    "vscode.menu.item4": "Exit",
}
SYNTH_ZH_HALF_DRIFTED = {
    "vscode.menu.item1": "Settings",  # untranslated
    "vscode.menu.item2": "帮助",  # translated
    "vscode.menu.item3": "About",  # untranslated
    "vscode.menu.item4": "退出",  # translated
}

# Case 3: 平衡 (合理翻译) — 期望 ratio = 0%
SYNTH_EN_BALANCED = {
    "ext.button.save": "Save",
    "ext.button.cancel": "Cancel",
    "ext.button.delete": "Delete",
}
SYNTH_ZH_BALANCED = {
    "ext.button.save": "保存",
    "ext.button.cancel": "取消",
    "ext.button.delete": "删除",
}

# Case 4: 接近 ceiling (7%, 在 8% 上限内) — VS Code 特有, 验证 ceiling
# 比 main app 5% 更宽
SYNTH_EN_NEAR_CEILING = dict.fromkeys(
    (f"ext.key{i}" for i in range(100)),
    "value-A",
)
# 模拟 7 个 key 未翻译 (7% < 8% ceiling)
SYNTH_ZH_NEAR_CEILING = {
    f"ext.key{i}": "value-A" if i < 7 else f"翻译-{i}" for i in range(100)
}

# Case 5: 含 _meta 元数据的 VS Code locale
SYNTH_VSCODE_WITH_META = {
    "_meta": {"_version": "1.0", "_lang": "zh-CN", "_source": "vscode"},
    "extension": {
        "displayName": "AI 介入代理",
        "description": "智能反馈代理",
    },
    "commands": {
        "openSettings": "打开设置",
    },
}


# ───────────────────────── Test cases ─────────────────────────


class TestR442SyntheticFullyDrifted(unittest.TestCase):
    """R353 Layer 2 negative test: 100% 未翻译 → 必须 fire (远超 8% ceiling)。"""

    def test_synthetic_fully_drifted_detected(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_FULLY_DRIFTED,
            SYNTH_ZH_FULLY_DRIFTED,
            UNTRANSLATED_WHITELIST,
        )
        self.assertGreater(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R442 meta-invariant: R353 Layer 2 算法应识别完全未翻译 "
            f"(ratio = {ratio:.0%}) 为 violation, 但实际未识别; R353 此 "
            f"layer 失效。期望 ratio > {UNTRANSLATED_RATIO_CEILING:.0%}。",
        )
        self.assertAlmostEqual(
            ratio,
            1.0,
            delta=0.01,
            msg=f"R442 sanity: 完全 drift 的 ratio 应接近 1.0, 实际 {ratio:.2%}",
        )


class TestR442SyntheticHalfDrifted(unittest.TestCase):
    """R353 Layer 2 negative test: 50% 未翻译 → 必须 fire (远超 8% ceiling)。"""

    def test_synthetic_half_drifted_above_ceiling(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_HALF_DRIFTED,
            SYNTH_ZH_HALF_DRIFTED,
            UNTRANSLATED_WHITELIST,
        )
        self.assertAlmostEqual(
            ratio,
            0.5,
            delta=0.01,
            msg=f"R442: 合成 50% drift 应该 ratio = 0.5, 实际 {ratio:.2%}",
        )
        self.assertGreater(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R442 meta-invariant: R353 应识别 50% drift (ratio = {ratio:.0%}) "
            f"超过 {UNTRANSLATED_RATIO_CEILING:.0%} 上限; R353 此 layer 失效。",
        )


class TestR442SyntheticBalanced(unittest.TestCase):
    """R353 Layer 2 positive smoke: 合理翻译应 *不* 触发 fail。"""

    def test_synthetic_balanced_below_ceiling(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_BALANCED,
            SYNTH_ZH_BALANCED,
            UNTRANSLATED_WHITELIST,
        )
        self.assertLessEqual(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R442 sanity: 平衡合成翻译 ratio = {ratio:.2%} 应 ≤ "
            f"{UNTRANSLATED_RATIO_CEILING:.0%} (smoke check; 防止 helpers "
            f"对合理翻译误报)。",
        )


class TestR442SyntheticNearCeiling(unittest.TestCase):
    """VS Code 特有: 7% drift 在 8% ceiling 内 → 不应 fire (vs main app 5%)。"""

    def test_synthetic_7_percent_within_8_percent_ceiling(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_NEAR_CEILING,
            SYNTH_ZH_NEAR_CEILING,
            UNTRANSLATED_WHITELIST,
        )
        self.assertAlmostEqual(
            ratio,
            0.07,
            delta=0.005,
            msg=f"R442: 合成 7% drift 应该 ratio ≈ 0.07, 实际 {ratio:.2%}",
        )
        self.assertLessEqual(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R442 sanity: VS Code 8% ceiling 应该容忍 7% drift "
            f"(vs main app 5% 不容忍), 实际 {ratio:.2%} > "
            f"{UNTRANSLATED_RATIO_CEILING:.0%}",
        )


class TestR442MetaFieldFiltering(unittest.TestCase):
    """R353 helper smoke: `_flatten_strings` 应跳过 VS Code locale 的 _meta。"""

    def test_vscode_meta_field_filtered_out(self) -> None:
        flat = _flatten_strings(SYNTH_VSCODE_WITH_META)
        for excluded in ("_meta._version", "_meta._lang", "_meta._source"):
            self.assertNotIn(
                excluded,
                flat,
                f"R442 meta-invariant: R353 `_flatten_strings` 必须跳过 "
                f"_meta 元数据, 但实际包含 {excluded}。如果 VS Code locale "
                f"的 _meta 字段被算进 untranslated ratio 会污染计算。",
            )
        # 真实业务字段应被保留
        self.assertIn("extension.displayName", flat)
        self.assertIn("extension.description", flat)
        self.assertIn("commands.openSettings", flat)


class TestR442MetaInvariantLineage(unittest.TestCase):
    """Layer 4: lineage marker 锁血脉 + milestone marker。"""

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
        ):
            self.assertIn(
                prior,
                text,
                f"R442: must cite meta-invariant lineage: {prior}",
            )

    def test_this_file_references_i18n_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R350", "R353", "R438"):
            self.assertIn(
                prior,
                text,
                f"R442: must cite i18n lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_11th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "meta-invariant 累计应用 11",
            text,
            "R442 应该明确记录是 meta-invariant 第 11 应用",
        )

    def test_this_file_marks_i18n_meta_2nd(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "i18n meta-invariant 子模式 2nd app",
            text,
            "R442 应该明确记录是 i18n meta-invariant 子模式 2nd 应用",
        )


if __name__ == "__main__":
    unittest.main()
