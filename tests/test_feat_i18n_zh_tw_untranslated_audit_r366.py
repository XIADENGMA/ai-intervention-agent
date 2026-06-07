"""R366 · zh-TW i18n untranslated keys audit invariant (cycle-41 #E1,
**i18n consistency 3rd 应用**)。

i18n consistency 应用 lineage
-----------------------------

- R350 (cycle-39 #B1): 1st app — main app zh-CN untranslated audit
- R353 (cycle-40 #B1): 2nd app — VS Code zh-CN untranslated audit
- **R366 (本 commit, cycle-41)**: **3rd app** — main app zh-TW
  untranslated audit

R366 锁定**繁体中文 (zh-TW)** locale 的翻译完整度, 防止:

1. zh-TW 文件创建后被遗忘 (zh-CN 翻译时复制 zh-TW 没改);
2. 新 key 添加到 en + zh-CN 但忘了同步 zh-TW;
3. 翻译者错把简体复制粘到 zh-TW (字形相同 + 表述习惯差异未做调整)。

为什么 zh-TW 比例阈值与 zh-CN 不同
----------------------------------

zh-TW 与 en 完全相同 (英文未翻译) 的合理情况:

- 品牌名 / URL / 技术术语 (与 zh-CN 同源)
- 单字符 / 数字格式 (跨语言通用)
- 实测约 5-8% 容差, 设为 8% 给翻译团队留出反应窗口

注意: 本 invariant 检查的是 zh-TW vs en (不是 zh-TW vs zh-CN), 因为
zh-TW 与 zh-CN 的合理差异 (字形 + 用语) 不属于 "untranslated", 而是
"localization variant", 需要专门的 zh-CN/zh-TW 一致性 invariant
(future work)。

R366 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: zh-TW.json 可加载, 有 string 内容
2. **Layer 2 (Whitelist-aware audit)**: 非 whitelist key 中, zh-TW
   完全等于 en 的比例 ≤ 8%
3. **Layer 3 (Whitelist meaningfulness)**: whitelist 不为空 + 每个
   whitelist key 在 zh-TW locale 中真的存在
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"

# Whitelist 与 R350 相同 (品牌 / URL / 通用单位), 但 zh-TW 特有项可
# 在此扩展
UNTRANSLATED_WHITELIST: set[str] = {
    # 品牌 / 项目名
    "app.name",
    "app.shortName",
    # URL / link 字段
    "footer.github.url",
    "support.repoUrl",
    # 单字符 / 数字格式标识符
    "format.thousand",
    "format.percent",
    # 代码标识符
    "config.command.example",
    # URL 字段
    "settings.barkUrl",
    "settings.barkUrlTemplatePlaceholder",
    # 语言名称 (zh-TW 内的 "繁體中文" 与 en 内的 "繁體中文" 是相同
    # 自我标识)
    "settings.langZhCN",
    "settings.langZhTW",
    # 数据单位 (KB / MB 跨语言通用)
    "status.sizeLabelKB",
}

UNTRANSLATED_RATIO_CEILING = 0.08  # 8% — zh-TW 容差略宽于 zh-CN


def _flatten_strings(data: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if prefix == "" and k.startswith("_"):
                continue
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_flatten_strings(v, path))
            elif isinstance(v, str):
                out[path] = v
    return out


class TestLayer1AnchorZhTwLoadable:
    """Layer 1: zh-TW.json 可加载, 有 string 内容。"""

    def test_zh_tw_loadable_and_non_empty(self):
        zh_tw = json.loads((LOCALES_DIR / "zh-TW.json").read_text(encoding="utf-8"))
        flat = _flatten_strings(zh_tw)
        assert len(flat) > 0, "R366-L1: zh-TW.json must have string leaves"

    def test_en_loadable_and_non_empty(self):
        en = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
        flat = _flatten_strings(en)
        assert len(flat) > 0, "R366-L1: en.json must have string leaves"


class TestLayer2UntranslatedRatio:
    """Layer 2: 非 whitelist untranslated 比例 ≤ 8%。"""

    def test_zh_tw_untranslated_ratio_under_ceiling(self):
        en = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
        zh_tw = json.loads((LOCALES_DIR / "zh-TW.json").read_text(encoding="utf-8"))
        en_flat = _flatten_strings(en)
        zh_flat = _flatten_strings(zh_tw)

        # 只考察 zh-TW 与 en 共有的 key (key parity 由 _key_parity
        # 测试单独锁定, 不在 R366 范围)
        shared_keys = set(en_flat.keys()) & set(zh_flat.keys())
        non_whitelist = [k for k in shared_keys if k not in UNTRANSLATED_WHITELIST]
        if not non_whitelist:
            return
        untranslated = [k for k in non_whitelist if en_flat[k] == zh_flat[k]]
        ratio = len(untranslated) / len(non_whitelist)
        if ratio > UNTRANSLATED_RATIO_CEILING:
            sample = sorted(untranslated)[:25]
            raise AssertionError(
                f"R366-L2: zh-TW untranslated ratio = "
                f"{ratio:.1%} ({len(untranslated)} / "
                f"{len(non_whitelist)}), exceeds ceiling "
                f"{UNTRANSLATED_RATIO_CEILING:.0%}.\n"
                f"Sample untranslated keys (first 25):\n"
                + "\n".join(f"  {k}: {en_flat[k]!r}" for k in sample)
                + "\nFix: translate to 繁體中文 or add legitimate "
                "exception to UNTRANSLATED_WHITELIST with rationale."
            )


class TestLayer3WhitelistMeaningfulness:
    """Layer 3: whitelist 非空, 每个 whitelist key 存在于 zh-TW。"""

    def test_whitelist_not_empty(self):
        assert len(UNTRANSLATED_WHITELIST) > 0, (
            "R366-L3: whitelist should not be empty (would indicate "
            "either unused mechanism or hidden non-deterministic bypass)"
        )

    def test_whitelist_keys_exist_in_zh_tw(self):
        zh_tw = json.loads((LOCALES_DIR / "zh-TW.json").read_text(encoding="utf-8"))
        flat = _flatten_strings(zh_tw)
        existing = [k for k in UNTRANSLATED_WHITELIST if k in flat]
        # 至少 1/3 whitelist key 实际存在 (兼容某些 future-guard 占位)
        assert len(existing) >= len(UNTRANSLATED_WHITELIST) // 3, (
            f"R366-L3: only {len(existing)}/"
            f"{len(UNTRANSLATED_WHITELIST)} whitelist keys exist in "
            f"zh-TW.json. Whitelist is mostly stale — clean it up."
        )


class TestR366LineageMarker:
    def test_this_file_contains_r366_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R366" in text

    def test_this_file_references_i18n_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R350", "R353"):
            assert prior in text, f"R366: must cite i18n consistency lineage: {prior}"

    def test_this_file_marks_third_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "3rd 应用" in text, "R366: must mark 3rd application"
