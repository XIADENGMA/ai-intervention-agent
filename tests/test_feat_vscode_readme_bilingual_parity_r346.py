"""R346 · ``packages/vscode/README.{md,zh-CN.md}`` 双语 parity invariant
(cycle-38 #C1, doc-parity 3rd 应用 → **达工业化阈值**)。

doc-parity 系列累计应用
-----------------------

- R335 (cycle-36): ``docs/troubleshooting.{md,zh-CN.md}`` — 1st app
- R340 (cycle-37): ``README.{md,zh-CN.md}`` (主仓 README) — 2nd app
- **R346 (本 commit, cycle-38)** — ``packages/vscode/README.{md,zh-CN.md}``
  → 3rd app 达**工业化阈值** (≥3 apps), doc-parity 子模式正式确立为方
  法论工业化模式

R346 invariant (4 层 + lineage marker)
--------------------------------------

1. **Layer 1 (Anchor)**: 两个文件存在 + 行数差异 ≤ 30% (中文常比英文略
   短或长)
2. **Layer 2 (章节结构 1:1)**: ``## section`` 数量 + 顺序完全 1:1 映射
3. **Layer 3 (语义映射表)**: 每个英文章节有对应中文翻译, 通过 mapping
   表显式锁定 (例如 "Features" ↔ "功能特性")
4. **Layer 4 (代码块 / 链接计数 parity)**: 代码块数量 (triple backtick)
   平衡, 外部链接数量平衡 ±2

methodology lineage
-------------------

doc-parity 是 v3.6+ 后期演化的子模式, 主要解决 "双语文档结构漂移" 这个
真实痛点 — 翻译时容易遗漏新章节, 导致英文加了节但中文还是旧版。lock
住章节结构 + 语义映射后, 任何只改一边的 PR 会立即触发 CI 失败。

3rd 应用达成代表 doc-parity 已**工业化** (≥3 apps), 与 v3.7 三层一致性
(R317/R321/R323)、v3.8 idempotent (R313/R318/R322)、v3.9 async race
(R326-R342) 并列为可复用的项目级方法论。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_EN = REPO_ROOT / "packages" / "vscode" / "README.md"
README_ZH = REPO_ROOT / "packages" / "vscode" / "README.zh-CN.md"

SECTION_MAPPING: dict[str, str] = {
    "Features": "功能特性",
    "Requirements": "环境要求",
    "Installation": "安装",
    "Settings": "配置",
    "AppleScript executor (macOS only) · security model": (
        "AppleScript executor（仅 macOS）· 安全模型"
    ),
    "macOS native notifications": "macOS 原生通知",
    "Build a VSIX (.vsix)": "生成 VSIX（.vsix）",
    "Development & Tests": "开发与测试",
    "Troubleshooting": "排错",
    "Changelog": "更新日志",
    "Repository": "项目地址",
}


def _extract_h2_headings(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    headings: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            headings.append(line[3:].strip())
    return headings


class TestLayer1AnchorAndLineBalance:
    """Layer 1: 文件存在 + 行数差异 ≤ 30%。"""

    def test_en_file_exists(self):
        assert README_EN.is_file()

    def test_zh_file_exists(self):
        assert README_ZH.is_file()

    def test_line_count_within_30_percent(self):
        en_lines = README_EN.read_text(encoding="utf-8").splitlines()
        zh_lines = README_ZH.read_text(encoding="utf-8").splitlines()
        ratio = abs(len(en_lines) - len(zh_lines)) / max(len(en_lines), len(zh_lines))
        assert ratio <= 0.30, (
            f"R346-L1: line count differs by {ratio:.1%} "
            f"(EN={len(en_lines)}, ZH={len(zh_lines)}); ≤ 30% expected "
            f"for true bilingual parity"
        )


class TestLayer2StructuralParity:
    """Layer 2: ## 章节数量 + 顺序 1:1 映射。"""

    def test_h2_count_equal(self):
        en = _extract_h2_headings(README_EN)
        zh = _extract_h2_headings(README_ZH)
        assert len(en) == len(zh), (
            f"R346-L2: H2 count mismatch — EN has {len(en)} sections, "
            f"ZH has {len(zh)}. EN={en}, ZH={zh}"
        )


class TestLayer3SemanticMapping:
    """Layer 3: 每个英文章节有对应中文翻译, 通过 SECTION_MAPPING 锁定。"""

    def test_every_en_section_in_mapping(self):
        en = _extract_h2_headings(README_EN)
        missing = [s for s in en if s not in SECTION_MAPPING]
        assert not missing, (
            f"R346-L3: EN H2 sections missing from SECTION_MAPPING: "
            f"{missing}. Update R346 SECTION_MAPPING or rename headings."
        )

    def test_every_zh_section_in_mapping(self):
        zh = _extract_h2_headings(README_ZH)
        zh_values = set(SECTION_MAPPING.values())
        missing = [s for s in zh if s not in zh_values]
        assert not missing, (
            f"R346-L3: ZH H2 sections missing from SECTION_MAPPING values: {missing}"
        )

    def test_order_matches_via_mapping(self):
        en = _extract_h2_headings(README_EN)
        zh = _extract_h2_headings(README_ZH)
        expected_zh = [SECTION_MAPPING.get(e, "<UNMAPPED>") for e in en]
        assert zh == expected_zh, (
            f"R346-L3: H2 order mismatch.\nEN -> mapped: {expected_zh}\nZH actual: {zh}"
        )


class TestLayer4ContentArtifactsParity:
    """Layer 4: 代码块 + 外部链接计数 parity。"""

    @staticmethod
    def _count_code_blocks(text: str) -> int:
        # Triple backtick fences count: each pair = 1 block, so count // 2
        return text.count("```") // 2

    @staticmethod
    def _count_external_links(text: str) -> int:
        # Markdown [label](url) where url starts with http/https
        return len(re.findall(r"\]\(https?://", text))

    def test_code_block_count_equal(self):
        en_text = README_EN.read_text(encoding="utf-8")
        zh_text = README_ZH.read_text(encoding="utf-8")
        en_blocks = self._count_code_blocks(en_text)
        zh_blocks = self._count_code_blocks(zh_text)
        assert en_blocks == zh_blocks, (
            f"R346-L4: code block count mismatch — EN={en_blocks}, "
            f"ZH={zh_blocks}. Code examples should be 1:1 bilingual."
        )

    def test_external_link_count_within_2(self):
        en_text = README_EN.read_text(encoding="utf-8")
        zh_text = README_ZH.read_text(encoding="utf-8")
        en_links = self._count_external_links(en_text)
        zh_links = self._count_external_links(zh_text)
        assert abs(en_links - zh_links) <= 2, (
            f"R346-L4: external link count differs by "
            f"{abs(en_links - zh_links)} (EN={en_links}, ZH={zh_links}); "
            f"≤ 2 expected"
        )


class TestR346LineageMarker:
    """R346 lineage marker: 标志 doc-parity 3rd app 达工业化阈值。"""

    def test_this_file_contains_r346_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R346" in text

    def test_this_file_references_doc_parity_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R335", "R340"):
            assert prior in text, f"R346: must cite doc-parity lineage: {prior}"

    def test_this_file_documents_industrialization_threshold(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("工业化", "3rd", "≥3 apps"):
            assert kw in text, f"R346: missing keyword: {kw!r}"
