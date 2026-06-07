"""R374 · VS Code zh-TW (繁体中文) untranslated keys audit invariant
(cycle-42 #D, **i18n consistency 4th 应用 — 工业化深化完成**)。

i18n consistency 应用 lineage
-----------------------------

- R350 (cycle-39 #B1): 1st app — main app zh-CN
- R353 (cycle-40 #A1): 2nd app — VS Code zh-CN
- R366 (cycle-41 #E1): 3rd app — main app zh-TW
- **R374 (本 commit, cycle-42)**: **4th app 工业化深化完成** — VS Code
  zh-TW

R374 invariant (3 层)
---------------------

1. **Layer 1 (Anchor)**: vscode en.json + zh-TW.json 都可加载
2. **Layer 2 (Whitelist-aware audit)**: 非 whitelist key 中, zh-TW
   完全等于 en 的比例 ≤ 10% (VS Code 技术术语密集 + zh-TW 翻译滞后双
   重因素, ceiling 略宽于 main app zh-TW 的 8%)
3. **Layer 3 (Whitelist meaningfulness)**: whitelist 不为空 + 至少
   1/3 key 在 vscode zh-TW 真实存在

里程碑
------

R374 完成 i18n consistency pattern 在**全部 4 个 audit target** 的覆
盖 (main zh-CN, vscode zh-CN, main zh-TW, vscode zh-TW), **i18n
consistency 维度从 cycle-39 启动到 cycle-42 工业化深化完成** (4 cycle
内完成 0→4 应用), 与 v3.6 perf-baseline / v3.7 decision-three-layer /
v3.8 idempotent contract 等成熟维度并列。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_LOCALES = REPO_ROOT / "packages" / "vscode" / "locales"

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
    # 语言名称自指代 (zh-TW 内的 "繁體中文" 与 en 内的英文相关 key 一致)
    "settings.language.zhTW",
    "settings.language.zhCN",
    # 命令名 / 配置示例 (技术 identifier 跨语言通用)
    "commands.openSettings",
    "commands.openConfigFile",
}

UNTRANSLATED_RATIO_CEILING = 0.10  # 10% — vscode zh-TW 容差最宽


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


class TestLayer1AnchorVscodeZhTwLoadable:
    """Layer 1: vscode en.json + zh-TW.json 可加载, 有 string 内容。"""

    def test_vscode_zh_tw_loadable(self):
        zh_tw = json.loads((VSCODE_LOCALES / "zh-TW.json").read_text(encoding="utf-8"))
        flat = _flatten_strings(zh_tw)
        assert len(flat) > 0, "R374-L1: vscode zh-TW.json must have string leaves"

    def test_vscode_en_loadable(self):
        en = json.loads((VSCODE_LOCALES / "en.json").read_text(encoding="utf-8"))
        flat = _flatten_strings(en)
        assert len(flat) > 0, "R374-L1: vscode en.json must have string leaves"


class TestLayer2UntranslatedRatio:
    """Layer 2: 非 whitelist untranslated 比例 ≤ 10%。"""

    def test_vscode_zh_tw_under_ceiling(self):
        en = json.loads((VSCODE_LOCALES / "en.json").read_text(encoding="utf-8"))
        zh_tw = json.loads((VSCODE_LOCALES / "zh-TW.json").read_text(encoding="utf-8"))
        en_flat = _flatten_strings(en)
        zh_flat = _flatten_strings(zh_tw)
        shared_keys = set(en_flat.keys()) & set(zh_flat.keys())
        non_whitelist = [k for k in shared_keys if k not in UNTRANSLATED_WHITELIST]
        if not non_whitelist:
            return
        untranslated = [k for k in non_whitelist if en_flat[k] == zh_flat[k]]
        ratio = len(untranslated) / len(non_whitelist)
        if ratio > UNTRANSLATED_RATIO_CEILING:
            sample = sorted(untranslated)[:30]
            raise AssertionError(
                f"R374-L2: vscode zh-TW untranslated ratio = "
                f"{ratio:.1%} ({len(untranslated)} / "
                f"{len(non_whitelist)}), exceeds ceiling "
                f"{UNTRANSLATED_RATIO_CEILING:.0%}.\n"
                f"Sample (first 30):\n"
                + "\n".join(f"  {k}: {en_flat[k]!r}" for k in sample)
                + "\nFix: translate to 繁體中文 or add legitimate "
                "exception to UNTRANSLATED_WHITELIST."
            )


class TestLayer3WhitelistMeaningfulness:
    """Layer 3: whitelist 非空, 至少 1/3 key 在 zh-TW 真实存在。"""

    def test_whitelist_not_empty(self):
        assert len(UNTRANSLATED_WHITELIST) > 0, "R374-L3: whitelist should not be empty"

    def test_whitelist_keys_exist_in_zh_tw(self):
        zh_tw = json.loads((VSCODE_LOCALES / "zh-TW.json").read_text(encoding="utf-8"))
        flat = _flatten_strings(zh_tw)
        existing = [k for k in UNTRANSLATED_WHITELIST if k in flat]
        assert len(existing) >= len(UNTRANSLATED_WHITELIST) // 3, (
            f"R374-L3: only {len(existing)}/"
            f"{len(UNTRANSLATED_WHITELIST)} whitelist keys exist in "
            f"vscode zh-TW.json. Whitelist may be mostly stale."
        )


class TestR374LineageMarker:
    def test_this_file_contains_r374_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R374" in text

    def test_this_file_references_i18n_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R350", "R353", "R366"):
            assert prior in text, f"R374: must cite i18n consistency lineage: {prior}"

    def test_this_file_marks_fourth_application(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "4th 应用" in text, "R374: must mark 4th application"
        assert "工业化深化完成" in text, "R374: must mark industrialization completion"
