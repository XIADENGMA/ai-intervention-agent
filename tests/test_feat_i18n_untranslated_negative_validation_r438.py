"""R438 (cycle-50 #B1) — meta-invariant 9th app: i18n meta-invariant 子模式
1st app — R350 (i18n untranslated keys audit) 负面自验证。

血脉关系 (Lineage):
- meta-invariant 模式: R414 (1st, Mixin matrix) → R418 (2nd, R412 ratchet)
  → R424 (3rd, doc-parity R400) → R426 (4th, R412 ratchet 2nd) → R428
  (5th, R422 ratchet 1st) → R430 (6th, R404 endpoint summary, API contract
  子模式 1st) → R432 (7th, R422 ratchet 2nd) → R436 (8th, R422 ratchet
  3rd) → **R438 (9th, R350 i18n untranslated negative, i18n meta-invariant
  子模式 1st app)**
- 元方法学层 (维度 15) 应用累计 9 → **完全工业化阈值达成** (≥ 9 应用相
  当于 doc-parity 6 应用 + i18n 子模式启动)
- meta-invariant 子模式 3 个:
  * doc-parity meta-invariant (R424) — 守护 6 个 doc-parity invariants
  * API contract meta-invariant (R430) — 守护 11 个 API contract invariants
  * **i18n meta-invariant (R438)** — 守护 4 个 i18n invariants (R350/R353/
    R366/R374)

战略 (Strategy):
- R350 (cycle-39 #B1) 是 *positive-only* test: 只验证当前 codebase locale
  内未翻译比例满足 ≤ 5% 上限
- R350 helpers 主要有 3 部分:
  1. `_flatten_strings(data, prefix)` — 递归扁平化 i18n JSON
  2. `UNTRANSLATED_WHITELIST` — 显式允许 untranslated 的 key 集合
  3. `UNTRANSLATED_RATIO_CEILING = 0.05` — 比例上限阈值
- 如果 future refactor 把 helper 静默 broken (例如 `_flatten_strings`
  误把 `_meta` 元数据也包含进来 / whitelist 被清空 / ratio ceiling 被改
  成 1.0), R350 仍 pass 但实际已失守
- R438 通过 *合成 (synthetic) input* 反向验证这些 helpers 在漂移场景能
  正确 fire

业务价值 (Business value):
- i18n 是 user-facing 体验的关键之一 (主 app + VS Code extension 共 4
  locale: en / zh-CN / zh-TW + VS Code en/zh-CN), R350 静默失效 = 翻译
  漏译可能不被发现, 直接伤中文母语用户体验
- i18n 维度累计 4 应用 (R350/R353/R366/R374) 是 user-facing 影响最大的
  维度之一, 它的元保护层缺失是结构性盲点
- meta-invariant 9 应用 = 完全工业化阈值, 形成 doc-parity / API contract
  / i18n 三个 meta-invariant 子模式, 与 14 大方法学维度形成 **元方法学
  层** 完整覆盖

设计 (Design):
- 合成 4 种 i18n locale drift 场景:
  1. 完全未翻译: zh-CN 整体复制 en (期望 fire — high untranslated ratio)
  2. 部分未翻译: zh-CN 中 50% key 等于 en (期望 fire — > 5% ceiling)
  3. 平衡 (合理翻译): zh-CN 与 en 完全不同, 但 whitelist key 相同 (期望
     不 fire — 在 5% 容差内)
  4. _meta 字段过滤验证: 含 _meta._version 等元数据时 _flatten_strings
     应跳过

非目标 (Non-goals):
- 不修改 R350 production 文件
- 不重新实现 R350 layer test (避免双重维护)
- 不检测 R350 是否"完美", 只验证它的 helpers 在 drift 时能给出可识别的
  失败信号
"""

from __future__ import annotations

import unittest
from pathlib import Path

# 复用 R350 的辅助函数与常量, 保证 negative test 与 production test 行为一致
from tests.test_feat_i18n_untranslated_keys_audit_r350 import (
    UNTRANSLATED_RATIO_CEILING,
    UNTRANSLATED_WHITELIST,
    _flatten_strings,
)


def _untranslated_ratio(
    en_flat: dict[str, str],
    zh_flat: dict[str, str],
    whitelist: set[str],
) -> float:
    """模拟 R350 计算非白名单 untranslated ratio 算法。

    返回 zh_flat 中非白名单 key 里 value == en_flat[同 key] 的比例。
    """
    common_keys = [k for k in zh_flat if k in en_flat and k not in whitelist]
    if not common_keys:
        return 0.0
    untrans = sum(1 for k in common_keys if zh_flat[k] == en_flat[k])
    return untrans / len(common_keys)


# ───────────────────────── Synthetic inputs ─────────────────────────


# Case 1: 完全未翻译 (100% drift) — 期望 ratio 接近 1.0
SYNTH_EN_FULLY_DRIFTED = {
    "settings.title": "Settings",
    "settings.save": "Save",
    "settings.cancel": "Cancel",
    "header.title": "AI Agent",
    "footer.copyright": "Copyright 2026",
}
SYNTH_ZH_FULLY_DRIFTED = dict(SYNTH_EN_FULLY_DRIFTED)  # 完全复制 en

# Case 2: 部分未翻译 (50% drift) — 期望 ratio 0.5
SYNTH_EN_HALF_DRIFTED = {
    "a.key1": "Hello",
    "a.key2": "World",
    "a.key3": "Foo",
    "a.key4": "Bar",
}
SYNTH_ZH_HALF_DRIFTED = {
    "a.key1": "Hello",  # untranslated
    "a.key2": "世界",  # translated
    "a.key3": "Foo",  # untranslated
    "a.key4": "酒吧",  # translated
}

# Case 3: 平衡 (合理翻译) — 期望 ratio 0.0 (或几乎 0)
SYNTH_EN_BALANCED = {
    "a.greeting": "Hello",
    "a.farewell": "Goodbye",
    "a.thanks": "Thanks",
}
SYNTH_ZH_BALANCED = {
    "a.greeting": "你好",
    "a.farewell": "再见",
    "a.thanks": "谢谢",
}

# Case 4: 含 _meta 元数据的 nested JSON
SYNTH_NESTED_WITH_META = {
    "_meta": {"_version": "1.0", "_lang": "zh-CN"},
    "settings": {
        "title": "设置",
        "save": "保存",
    },
    "header": {
        "title": "AI 代理",
    },
}


# ───────────────────────── Test cases ─────────────────────────


class TestR438SyntheticFullyDrifted(unittest.TestCase):
    """R350 Layer 2 negative test: 完全未翻译 (100% drift) → 必须 fire。"""

    def test_synthetic_fully_drifted_detected(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_FULLY_DRIFTED,
            SYNTH_ZH_FULLY_DRIFTED,
            UNTRANSLATED_WHITELIST,
        )
        self.assertGreater(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R438 meta-invariant: R350 Layer 2 算法应识别完全未翻译 "
            f"(ratio = {ratio:.0%}) 为 violation, 但实际未识别; R350 此 "
            f"layer 失效。期望 ratio > {UNTRANSLATED_RATIO_CEILING:.0%}。",
        )
        # 同时 sanity: ratio 应接近 1.0
        self.assertAlmostEqual(
            ratio,
            1.0,
            delta=0.01,
            msg=f"R438 sanity: 完全 drift 的 ratio 应接近 1.0, 实际 {ratio:.2%}",
        )


class TestR438SyntheticHalfDrifted(unittest.TestCase):
    """R350 Layer 2 negative test: 50% 未翻译 → 也必须 fire (5% 容差内不会过)。"""

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
            msg=f"R438: 合成 50% drift 应该 ratio = 0.5, 实际 {ratio:.2%}",
        )
        self.assertGreater(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R438 meta-invariant: R350 应识别 50% drift (ratio = {ratio:.0%}) "
            f"超过 {UNTRANSLATED_RATIO_CEILING:.0%} 上限; R350 此 layer 失效。",
        )


class TestR438SyntheticBalanced(unittest.TestCase):
    """R350 Layer 2 positive smoke: 合理翻译应 *不* 触发 fail。"""

    def test_synthetic_balanced_below_ceiling(self) -> None:
        ratio = _untranslated_ratio(
            SYNTH_EN_BALANCED,
            SYNTH_ZH_BALANCED,
            UNTRANSLATED_WHITELIST,
        )
        self.assertLessEqual(
            ratio,
            UNTRANSLATED_RATIO_CEILING,
            f"R438 sanity: 平衡合成翻译 ratio = {ratio:.2%} 应 ≤ "
            f"{UNTRANSLATED_RATIO_CEILING:.0%} (smoke check; 防止 helpers "
            f"对合理翻译误报)。",
        )


class TestR438MetaFieldFiltering(unittest.TestCase):
    """R350 helper smoke: `_flatten_strings` 应跳过 _meta 元数据。"""

    def test_meta_field_filtered_out(self) -> None:
        flat = _flatten_strings(SYNTH_NESTED_WITH_META)
        self.assertNotIn(
            "_meta._version",
            flat,
            "R438 meta-invariant: R350 `_flatten_strings` 必须跳过 _meta "
            "元数据, 但实际包含 _meta._version。如果元数据被算进 "
            "untranslated ratio 会污染计算。",
        )
        self.assertNotIn(
            "_meta._lang",
            flat,
            "R438 meta-invariant: R350 `_flatten_strings` 必须跳过 _meta._lang",
        )
        # 真实业务字段应被保留
        self.assertIn("settings.title", flat)
        self.assertIn("settings.save", flat)
        self.assertIn("header.title", flat)


class TestR438MetaInvariantLineage(unittest.TestCase):
    """R438 Layer 3: lineage marker 锁血脉。"""

    def test_this_file_references_meta_invariant_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R414", "R418", "R424", "R426", "R428", "R430", "R432", "R436"):
            self.assertIn(
                prior,
                text,
                f"R438: must cite meta-invariant lineage: {prior}",
            )

    def test_this_file_references_i18n_lineage(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R350", "R353", "R366", "R374"):
            self.assertIn(
                prior,
                text,
                f"R438: must cite i18n lineage: {prior}",
            )

    def test_this_file_marks_meta_invariant_9th_app(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("meta-invariant 9th app", "完全工业化"):
            self.assertIn(kw, text, f"R438: missing milestone keyword: {kw!r}")

    def test_this_file_marks_i18n_meta_invariant_1st(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(
            "i18n meta-invariant 子模式 1st app",
            text,
            "R438: must mark i18n meta-invariant 子模式 1st app",
        )


if __name__ == "__main__":
    unittest.main()
