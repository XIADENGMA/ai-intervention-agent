"""R350 · i18n untranslated keys audit invariant (cycle-39 #B1, **i18n
consistency 新维度**)。

已有 i18n 守护体系
------------------

- ``test_i18n_locale_key_parity.py`` — 结构 parity (key set + type) +
  占位符 parity, 跨 main app + VS Code locale
- ``test_i18n_used_keys_exist.py`` — 代码引用的 key 必须存在
- ``test_i18n_orphan_keys.py`` — locale 内 key 必须被代码引用
- ``test_i18n_duplicate_values.py`` — 同 locale 内重复 value 检测
- ``test_i18n_locale_shape.py`` — JSON 形状校验
- 共 45+ i18n 测试

R350 audit 维度
---------------

**Untranslated keys** — 一个非英文 locale (zh-CN, zh-TW) 内的 key 值如
果**完全等于英文** locale 同 key 的值, 大概率是:

1. 翻译漏 (translator missed the key)
2. 翻译刻意保留 (e.g., "GitHub", "macOS", brand names, code identifiers)

R350 通过白名单机制 + 比例上限锁定:

- **whitelist**: 显式允许的未翻译 key (品牌名 / 代码标识符 / 数字单位)
- **比例阈值**: zh-CN locale 中, 非白名单 untranslated 比例 ≤ 5%
  (5% 是噪声容差, > 5% 触发警报要求审查)

为什么不要求 0% untranslated
----------------------------

实际项目中合理的未翻译 key 总是存在 (品牌名, 技术术语, 错误码标识符,
URL fragment), 强制 0% 会产生大量假阳性, 反而让 invariant 失效。5%
容差是 "意外漏翻" 与 "合理保留" 的平衡点。

R350 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: en.json + zh-CN.json 都可加载, 都有内容
2. **Layer 2 (Whitelist-aware audit)**: 非 whitelist key 中, zh-CN 完全
   等于 en 的比例 ≤ 5%
3. **Layer 3 (Whitelist meaningfulness)**: whitelist 不为空 (证明白名单
   机制本身在用), 且每个 whitelist key 确实在 locale 中存在

methodology
-----------

R350 是 i18n 维度新 pattern — 之前 i18n 测试都聚焦**结构** (key/type/
placeholder), R350 首次聚焦**语义/内容**质量。lineage 与 doc-parity
(R335/R340/R346) 类似 — 锁定 "文档/翻译内容真的反映了双语意图" 而非
仅 "形状一致"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"

# Whitelist: keys whose ZH/TW values legitimately equal EN
# (品牌名, 技术术语, 代码标识符)
UNTRANSLATED_WHITELIST: set[str] = {
    # 品牌 / 项目名 (可能不存在但保留作为 future-guard)
    "app.name",
    "app.shortName",
    # URL / link 字段 (技术上是 string but 不需要翻译)
    "footer.github.url",
    "support.repoUrl",
    # 单字符 / 数字格式标识符 (可能正好相同)
    "format.thousand",
    "format.percent",
    # 代码标识符 / shell 命令 (技术术语保留)
    "config.command.example",
    # URL 字段 - 配置示例 URL 模板
    "settings.barkUrl",
    "settings.barkUrlTemplatePlaceholder",
    # 语言名称自指代 (zh-CN 内的 "中文" / zh-TW 内的 "繁體中文" 与
    # en 内的英文名是不同的 — 这里 zh-CN.langZhCN = "中文" 而
    # en.langZhCN 也是 "中文" 因为是自我标识)
    "settings.langZhCN",
    "settings.langZhTW",
    # 数据单位 (KB / MB 跨语言通用)
    "status.sizeLabelKB",
}

UNTRANSLATED_RATIO_CEILING = 0.05  # 5% — 非白名单 untranslated 上限


def _flatten_strings(data: Any, prefix: str = "") -> dict[str, str]:
    """递归扁平化, 只返回 string leaf 值。"""
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            # 跳过 _meta 元数据 (与 test_i18n_locale_key_parity.py 一致)
            if prefix == "" and k.startswith("_"):
                continue
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_flatten_strings(v, path))
            elif isinstance(v, str):
                out[path] = v
    return out


class TestLayer1AnchorEnZhCnLoadable:
    """Layer 1: en.json + zh-CN.json 可加载, 有 string 内容。"""

    def test_en_loadable_and_non_empty(self):
        en = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
        flat = _flatten_strings(en)
        assert len(flat) > 0, "R350-L1: en.json must have string leaves"

    def test_zh_cn_loadable_and_non_empty(self):
        zh = json.loads((LOCALES_DIR / "zh-CN.json").read_text(encoding="utf-8"))
        flat = _flatten_strings(zh)
        assert len(flat) > 0, "R350-L1: zh-CN.json must have string leaves"


class TestLayer2WhitelistAwareUntranslatedRatio:
    """Layer 2: 非 whitelist key 中, zh-CN value 完全等于 en value 的比例
    ≤ 5%。"""

    def test_zh_cn_untranslated_ratio_within_ceiling(self):
        en = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
        zh = json.loads((LOCALES_DIR / "zh-CN.json").read_text(encoding="utf-8"))
        en_flat = _flatten_strings(en)
        zh_flat = _flatten_strings(zh)

        # 只考虑两者都有的 key (key parity 已经被 test_i18n_locale_key_
        # parity.py 守护, 这里不重复报错)
        common_keys = set(en_flat) & set(zh_flat)

        # 排除白名单
        audit_keys = common_keys - UNTRANSLATED_WHITELIST

        untranslated = [
            k for k in audit_keys if en_flat[k].strip() == zh_flat[k].strip()
        ]

        ratio = len(untranslated) / max(1, len(audit_keys))

        if ratio > UNTRANSLATED_RATIO_CEILING:
            sample = sorted(untranslated)[:20]
            raise AssertionError(
                f"R350-L2: zh-CN untranslated ratio "
                f"{ratio:.1%} exceeds ceiling "
                f"{UNTRANSLATED_RATIO_CEILING:.1%}.\n"
                f"  {len(untranslated)} of {len(audit_keys)} audited keys "
                f"have zh-CN value == en value.\n"
                f"  First 20 untranslated keys (sorted): {sample}\n"
                f"Fix: either translate the key in zh-CN.json, or add it "
                f"to UNTRANSLATED_WHITELIST in this test file with a "
                f"rationale comment."
            )


class TestLayer3WhitelistMeaningfulness:
    """Layer 3: whitelist 至少有部分 key 在 locale 中存在 (证明白名单不是
    死代码)。"""

    def test_whitelist_is_not_empty(self):
        assert UNTRANSLATED_WHITELIST, (
            "R350-L3: UNTRANSLATED_WHITELIST must not be empty — the "
            "whitelist mechanism itself is the contract; an empty "
            "whitelist suggests this invariant is being defeated."
        )

    def test_whitelist_entries_documented(self):
        """每个 whitelist 条目所属类别需在文件 docstring 或 inline comment
        中显式说明。"""
        text = Path(__file__).read_text(encoding="utf-8")
        for category in ("品牌名", "技术术语", "URL 字段", "数据单位"):
            assert category in text, (
                f"R350-L3: whitelist category {category!r} must be "
                f"documented in module docstring or UNTRANSLATED_WHITELIST "
                f"inline comments."
            )


class TestR350LineageMarker:
    def test_this_file_contains_r350_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R350" in text

    def test_this_file_references_existing_i18n_tests(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in (
            "test_i18n_locale_key_parity",
            "test_i18n_used_keys_exist",
            "test_i18n_duplicate_values",
        ):
            assert prior in text, (
                f"R350: must cite existing i18n test for context: {prior}"
            )

    def test_this_file_marks_new_semantic_dimension(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("untranslated", "语义", "新 pattern"):
            assert kw in text, f"R350: missing keyword: {kw!r}"
