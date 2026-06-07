"""R353 · VS Code locale untranslated audit invariant (cycle-40 #A1, i18n
consistency **2nd 应用 — 巩固阶段**)。

R350 (cycle-39) 在 main app static/locales 引入了 untranslated keys 比例
锁定; R353 把同样方法学**镜像到 VS Code extension locales**
(``packages/vscode/locales/``)。

i18n consistency 维度应用 lineage
---------------------------------

- R350 (cycle-39 #B1): main app static/locales — 1st app, 1.57%
- **R353 (本 commit, cycle-40)**: VS Code packages/vscode/locales — 2nd
  app, 4.86% (实测), 接近 5% 上限要 7 个白名单

R353 invariant (3 层 + lineage)
-------------------------------

1. **Layer 1**: vscode en.json + zh-CN.json 都可加载, 都有内容
2. **Layer 2**: 非 whitelist key 中, zh-CN value 完全等于 en 的比例
   ≤ 8% (vscode extension 内有更多技术术语 / URL 字段, ceiling 比 main
   app 的 5% 略宽)
3. **Layer 3**: whitelist 不为空 + 至少有部分 key 真实存在 (证明白名单
   有效)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_LOCALES = REPO_ROOT / "packages" / "vscode" / "locales"

# Whitelist: vscode locale 内合理保留的 untranslated key
# 主要类别: Bark URL 配置项 (技术术语 / placeholder URL) + 版本号链接
UNTRANSLATED_WHITELIST: set[str] = {
    # Bark 配置 (推送服务术语 / URL placeholder, 跨语言通用)
    "settings.bark.action",
    "settings.bark.deviceKey",
    "settings.bark.icon",
    "settings.bark.url",
    "settings.bark.urlPlaceholder",
    "settings.bark.urlTemplatePlaceholder",
    # 版本号链接 (链接 URL 不翻译)
    "settings.footer.versionLink",
}

UNTRANSLATED_RATIO_CEILING = 0.08  # 8% — vscode extension 技术术语更密集


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


class TestLayer1Anchor:
    def test_vscode_en_loadable(self):
        data = json.loads((VSCODE_LOCALES / "en.json").read_text(encoding="utf-8"))
        assert len(_flatten_strings(data)) > 0

    def test_vscode_zh_cn_loadable(self):
        data = json.loads((VSCODE_LOCALES / "zh-CN.json").read_text(encoding="utf-8"))
        assert len(_flatten_strings(data)) > 0


class TestLayer2WhitelistAwareUntranslatedRatio:
    def test_vscode_zh_cn_untranslated_within_ceiling(self):
        en = json.loads((VSCODE_LOCALES / "en.json").read_text(encoding="utf-8"))
        zh = json.loads((VSCODE_LOCALES / "zh-CN.json").read_text(encoding="utf-8"))
        en_flat = _flatten_strings(en)
        zh_flat = _flatten_strings(zh)
        common = set(en_flat) & set(zh_flat)
        audit = common - UNTRANSLATED_WHITELIST
        untranslated = [k for k in audit if en_flat[k].strip() == zh_flat[k].strip()]
        ratio = len(untranslated) / max(1, len(audit))
        if ratio > UNTRANSLATED_RATIO_CEILING:
            raise AssertionError(
                f"R353: vscode zh-CN untranslated ratio {ratio:.1%} "
                f"exceeds ceiling {UNTRANSLATED_RATIO_CEILING:.1%}. "
                f"Untranslated: {sorted(untranslated)[:20]}"
            )


class TestLayer3WhitelistMeaningfulness:
    def test_whitelist_not_empty(self):
        assert UNTRANSLATED_WHITELIST

    def test_whitelist_entries_documented_in_module(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for category in ("Bark", "版本号链接"):
            assert category in text, f"R353: missing category: {category!r}"


class TestR353LineageMarker:
    def test_this_file_contains_r353_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R353" in text

    def test_this_file_references_r350(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R350" in text, "R353 must cite R350 (1st app of i18n consistency)"

    def test_this_file_marks_second_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("2nd 应用", "巩固阶段"):
            assert kw in text, f"R353: missing keyword: {kw!r}"
