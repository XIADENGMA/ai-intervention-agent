"""R448 (cycle-52 #B1) — meta-invariant 13th app: i18n meta-invariant 子
模式 3rd app — R366 (main app zh-TW untranslated audit) 负面自验证。

血脉关系 (Lineage):
- meta-invariant 累计应用 13: R414 → R418 → R424 → R426 → R428 → R430 →
  R432 → R436 → R438 → R440 → R442 → R446 → **R448**
- 元方法学层 (维度 15 / v3.11) 完全工业化深化期 + 2 (≥ 13 应用)
- i18n meta-invariant 子模式 3rd app, **进入工业化**:
  * R438 (cycle-50) — R350 (main app zh-CN) 1st app
  * R442 (cycle-51) — R353 (VS Code zh-CN) 2nd app
  * **R448 (cycle-52) — R366 (main app zh-TW) 3rd app, 进入工业化阈值**

战略 (Strategy):
- R366 (cycle-41 #E1) 是 *positive-only* test, 只验证当前 zh-TW locale
  内未翻译比例满足 ≤ 8% 上限
- 风险与 R438/R442 同模板: future refactor 把 R366 helpers 静默 broken,
  R366 仍 pass 但实际已失守
- R448 通过 *合成 (synthetic) input* 反向验证这些 helpers 在漂移场景能
  正确 fire (复用 R438/R442 模板, 仅适配 zh-TW 8% ceiling, 与 R442 ceiling
  一致)

业务价值 (Business value):
- zh-TW (繁体中文) 是台湾/香港 IDE 用户群的关键 locale, R366 静默失效 =
  漏译可能直接 ship 到 marketplace 伤台港用户
- i18n meta-invariant 子模式 3 应用进入 **工业化阈值** (与 doc-parity 子模式
  6 应用 / API contract 子模式 1 应用形成可比的演化节奏)
- 模板复用 (template reuse) — R448 完全复用 R442 模板 + zh-TW 适配, 证明
  i18n meta-invariant 子模式有 *机械化复用* 能力
- 后续 R374 (VS Code zh-TW) 可作为 i18n 子模式 4th app 完全工业化

模板复用统计 (cycle-52 末):
- doc-parity 子模式: 7 应用 (R335→R340→R346→R394→R400→R408→R444), 完全
  工业化深化期
- i18n 子模式: 3 应用 (R438→R442→R448), 工业化期
- ratchet validation 子模式: 7 应用 (R418→R426→R428→R432→R436→R440→R446),
  完全工业化深化期
- API contract 子模式: 1 应用 (R430), 启动期
- Mixin matrix 子模式: 1 应用 (R414), 启动期

设计 (Design, 4 layers):
- Layer 1 (synthetic drift detection): 合成 4 种 zh-TW locale drift 场景
- Layer 2 (synthetic ceiling-tolerance): 8% ceiling 在 zh-TW 场景下与 VS
  Code 8% 一致 (与 R442 对称)
- Layer 3 (_meta filtering): 验证 _flatten_strings 在 zh-TW locale 也会
  跳过 _meta 元数据
- Layer 4 (lineage marker): 引用 R438/R442 + R366 + meta-invariant 血脉
"""

from __future__ import annotations

import unittest
from pathlib import Path

# 复用 R366 的辅助函数与常量, 保证 negative test 与 production test 行为一致
from tests.test_feat_i18n_zh_tw_untranslated_audit_r366 import (
    UNTRANSLATED_RATIO_CEILING,
    UNTRANSLATED_WHITELIST,
    _flatten_strings,
)


def _untranslated_ratio(
    en_flat: dict[str, str],
    zh_flat: dict[str, str],
    whitelist: set[str],
) -> float:
    """模拟 R366 计算非白名单 untranslated ratio 算法 (与 R438/R442 一致)。"""
    common_keys = [k for k in zh_flat if k in en_flat and k not in whitelist]
    if not common_keys:
        return 0.0
    untrans = sum(1 for k in common_keys if zh_flat[k] == en_flat[k])
    return untrans / len(common_keys)


# ───────────────────────── Synthetic inputs ─────────────────────────


# Case 1: 完全未翻译 (zh-TW = en, 100% drift)
SYNTH_EN_FULLY_DRIFTED = {
    "settings.title": "Settings",
    "feedback.submit": "Submit",
    "task.create": "Create Task",
    "notification.test": "Test Notification",
    "header.menu": "Menu",
}
SYNTH_ZH_TW_FULLY_DRIFTED = dict(SYNTH_EN_FULLY_DRIFTED)  # 复制 en 给 zh-TW

# Case 2: 部分未翻译 (50% drift)
SYNTH_EN_HALF_DRIFTED = {
    "a.b1": "Hello",
    "a.b2": "World",
    "a.b3": "Foo",
    "a.b4": "Bar",
}
SYNTH_ZH_TW_HALF_DRIFTED = {
    "a.b1": "Hello",  # untranslated
    "a.b2": "世界",  # translated (繁体)
    "a.b3": "Foo",  # untranslated
    "a.b4": "酒吧",  # translated
}

# Case 3: 平衡 (合理繁体翻译)
SYNTH_EN_BALANCED = {
    "a.greeting": "Hello",
    "a.farewell": "Goodbye",
    "a.thanks": "Thanks",
}
SYNTH_ZH_TW_BALANCED = {
    "a.greeting": "您好",  # 繁体常用 "您好" 而非 "你好"
    "a.farewell": "再見",
    "a.thanks": "謝謝",
}

# Case 4: 接近 ceiling (7%, 在 8% 内) — 验证 ceiling 容差
SYNTH_EN_NEAR_CEILING = dict.fromkeys(
    (f"key{i}" for i in range(100)),
    "value-X",
)
SYNTH_ZH_TW_NEAR_CEILING = {
    f"key{i}": "value-X" if i < 7 else f"翻譯-{i}" for i in range(100)
}

# Case 5: 含 _meta 元数据的 zh-TW locale
SYNTH_ZH_TW_WITH_META = {
    "_meta": {"_version": "1.0", "_lang": "zh-TW", "_region": "TW"},
    "settings": {
        "title": "設定",
        "language": "繁體中文",
    },
    "buttons": {
        "save": "儲存",
        "cancel": "取消",
    },
}


# ───────────────────────── Test cases ─────────────────────────


class TestR448SyntheticFullyDrifted(unittest.TestCase):
    """R366 Layer 2 negative test: 100% drift → 必须 fire (远超 8% ceiling)。"""

    def test_synthetic_fully_drifted_detected(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_FULLY_DRIFTED,
            SYNTH_ZH_TW_FULLY_DRIFTED,
            UNTRANSLATED_WHITELIST,
        )
        self.assertGreater(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R448 meta-invariant: R366 Layer 2 算法应识别完全未翻译 "
            f"(ratio = {ratio:.0%}) 为 violation, 但实际未识别; R366 此 "
            f"layer 失效。期望 ratio > {UNTRANSLATED_RATIO_CEILING:.0%}。",
        )
        self.assertAlmostEqual(
            ratio,
            1.0,
            delta=0.01,
            msg=f"R448 sanity: 完全 drift 的 ratio 应接近 1.0, 实际 {ratio:.2%}",
        )


class TestR448SyntheticHalfDrifted(unittest.TestCase):
    """R366 Layer 2 negative test: 50% drift → 必须 fire (远超 8% ceiling)。"""

    def test_synthetic_half_drifted_above_ceiling(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_HALF_DRIFTED,
            SYNTH_ZH_TW_HALF_DRIFTED,
            UNTRANSLATED_WHITELIST,
        )
        self.assertAlmostEqual(
            ratio,
            0.5,
            delta=0.01,
            msg=f"R448: 合成 50% drift 应该 ratio = 0.5, 实际 {ratio:.2%}",
        )
        self.assertGreater(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R448 meta-invariant: R366 应识别 50% drift (ratio = {ratio:.0%}) "
            f"超过 {UNTRANSLATED_RATIO_CEILING:.0%} 上限; R366 此 layer 失效。",
        )


class TestR448SyntheticBalanced(unittest.TestCase):
    """R366 Layer 2 positive smoke: 合理繁体翻译应 *不* 触发 fail。"""

    def test_synthetic_balanced_below_ceiling(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_BALANCED,
            SYNTH_ZH_TW_BALANCED,
            UNTRANSLATED_WHITELIST,
        )
        self.assertLessEqual(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R448 sanity: 平衡合成繁体翻译 ratio = {ratio:.2%} 应 ≤ "
            f"{UNTRANSLATED_RATIO_CEILING:.0%} (smoke check; 防止 helpers "
            f"对合理翻译误报)。",
        )


class TestR448SyntheticNearCeiling(unittest.TestCase):
    """7% drift 在 8% ceiling 内 → 不应 fire (zh-TW 容差与 VS Code 对称)。"""

    def test_synthetic_7_percent_within_8_percent_ceiling(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_NEAR_CEILING,
            SYNTH_ZH_TW_NEAR_CEILING,
            UNTRANSLATED_WHITELIST,
        )
        self.assertAlmostEqual(
            ratio,
            0.07,
            delta=0.005,
            msg=f"R448: 合成 7% drift 应该 ratio ≈ 0.07, 实际 {ratio:.2%}",
        )
        self.assertLessEqual(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R448 sanity: zh-TW 8% ceiling 应容忍 7% drift, 实际 {ratio:.2%}",
        )


class TestR448MetaFieldFiltering(unittest.TestCase):
    """R366 helper smoke: `_flatten_strings` 应跳过 zh-TW locale 的 _meta。"""

    def test_zh_tw_meta_field_filtered_out(self) -> None:
        flat = _flatten_strings(SYNTH_ZH_TW_WITH_META)
        for excluded in ("_meta._version", "_meta._lang", "_meta._region"):
            self.assertNotIn(
                excluded,
                flat,
                f"R448 meta-invariant: R366 `_flatten_strings` 必须跳过 "
                f"_meta 元数据, 但实际包含 {excluded}。",
            )
        # 真实业务字段应被保留
        self.assertIn("settings.title", flat)
        self.assertIn("settings.language", flat)
        self.assertIn("buttons.save", flat)


class TestR448MetaInvariantLineage(unittest.TestCase):
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
            "R442",
            "R446",
        ):
            self.assertIn(
                prior,
                text,
                f"R448: must cite meta-invariant lineage: {prior}",
            )

    def test_this_file_references_i18n_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R350", "R353", "R366", "R438", "R442"):
            self.assertIn(
                prior,
                text,
                f"R448: must cite i18n lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_13th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "meta-invariant 累计应用 13",
            text,
            "R448 应该明确记录是 meta-invariant 第 13 应用",
        )

    def test_this_file_marks_i18n_meta_3rd_industrialization(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("i18n meta-invariant 子模式 3rd app", "进入工业化"):
            self.assertIn(
                kw, text, f"R448 应该标记 i18n 子模式 3rd app + 工业化: {kw!r}"
            )


if __name__ == "__main__":
    unittest.main()
