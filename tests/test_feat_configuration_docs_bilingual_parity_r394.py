"""R394 · ``docs/configuration.{md,zh-CN.md}`` 双语 parity invariant
(cycle-44 #C2, doc-parity 4th 应用 → **进入深化期工业化**)。

doc-parity 系列累计应用
-----------------------

- R335 (cycle-36): ``docs/troubleshooting.{md,zh-CN.md}`` — 1st app
- R340 (cycle-37): ``README.{md,zh-CN.md}`` 主仓 README — 2nd app
- R346 (cycle-38): ``packages/vscode/README.{md,zh-CN.md}`` — 3rd app
  (达工业化阈值)
- **R394 (本 commit, cycle-44)** — ``docs/configuration.{md,zh-CN.md}``
  → **4th app 进入深化期工业化**, doc-parity 子模式从 cycle-36 启动到
  cycle-44 完成 1→4 应用深化, 与 v3.7/v3.8/v3.9 等成熟 pattern 并列

R394 invariant (4 层 + lineage marker)
--------------------------------------

1. **Layer 1 (Anchor)**: 两个文件存在 + 行数差异 ≤ 30%
2. **Layer 2 (章节结构 1:1)**: ``## section`` 数量 + 顺序完全 1:1 映射
3. **Layer 3 (语义映射表)**: 每个英文章节有对应中文翻译, 通过 mapping
   表显式锁定 (e.g., "Configuration" ↔ "配置文件说明")
4. **Layer 4 (代码块计数 parity)**: 代码块数量 (triple backtick) 平衡

methodology lineage
-------------------

R394 把 doc-parity 子模式从 3 应用 (工业化阈值) 推到 4 应用 (深化期
工业化), 与 i18n consistency (R350-R374, 4 应用工业化) / v3.6 perf-
baseline (9 应用) / API contract (6 应用) 等 5+ 应用维度并列。

doc-parity 完成 ``docs/troubleshooting`` (排错) + 2 个 README + 1 个
configuration (4 个核心用户面向文档) 全锁, 项目级双语文档结构漂移防
御进入完全覆盖期。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_EN = REPO_ROOT / "docs" / "configuration.md"
DOC_ZH = REPO_ROOT / "docs" / "configuration.zh-CN.md"

SECTION_MAPPING: dict[str, str] = {
    "Configuration": "配置文件说明",
    "Backward compatibility": "向后兼容",
    "Sections": "配置段说明",
    "Minimal example": "最小示例",
}


def _extract_h2_headings(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            out.append(line[3:].strip())
    return out


class TestLayer1AnchorAndLineBalance:
    """Layer 1: 文件存在 + 行数差异 ≤ 30%。"""

    def test_en_file_exists(self):
        assert DOC_EN.is_file(), f"R394-L1: {DOC_EN} missing"

    def test_zh_file_exists(self):
        assert DOC_ZH.is_file(), f"R394-L1: {DOC_ZH} missing"

    def test_line_count_within_30_percent(self):
        en_lines = DOC_EN.read_text(encoding="utf-8").splitlines()
        zh_lines = DOC_ZH.read_text(encoding="utf-8").splitlines()
        ratio = abs(len(en_lines) - len(zh_lines)) / max(len(en_lines), len(zh_lines))
        assert ratio <= 0.30, (
            f"R394-L1: line count differs by {ratio:.1%} "
            f"(EN={len(en_lines)}, ZH={len(zh_lines)}); ≤ 30% expected "
            f"for true bilingual parity"
        )


class TestLayer2StructuralParity:
    """Layer 2: ## 章节数量 + 顺序 1:1 映射。"""

    def test_h2_count_equal(self):
        en = _extract_h2_headings(DOC_EN)
        zh = _extract_h2_headings(DOC_ZH)
        assert len(en) == len(zh), (
            f"R394-L2: H2 count mismatch — EN has {len(en)} sections, "
            f"ZH has {len(zh)}. EN={en}, ZH={zh}"
        )


class TestLayer3SemanticMapping:
    """Layer 3: 每个英文章节有对应中文翻译, 通过 SECTION_MAPPING 锁定。"""

    def test_every_en_section_in_mapping(self):
        en = _extract_h2_headings(DOC_EN)
        missing = [s for s in en if s not in SECTION_MAPPING]
        assert not missing, (
            f"R394-L3: EN H2 sections missing from SECTION_MAPPING: "
            f"{missing}. Update SECTION_MAPPING or rename headings."
        )

    def test_every_zh_section_in_mapping(self):
        zh = _extract_h2_headings(DOC_ZH)
        zh_values = set(SECTION_MAPPING.values())
        missing = [s for s in zh if s not in zh_values]
        assert not missing, (
            f"R394-L3: ZH H2 sections missing from SECTION_MAPPING values: {missing}"
        )

    def test_order_matches_via_mapping(self):
        en = _extract_h2_headings(DOC_EN)
        zh = _extract_h2_headings(DOC_ZH)
        expected_zh = [SECTION_MAPPING.get(e, "<UNMAPPED>") for e in en]
        assert zh == expected_zh, (
            f"R394-L3: H2 order mismatch.\nEN -> mapped: {expected_zh}\nZH actual: {zh}"
        )


class TestLayer4ContentArtifactsParity:
    """Layer 4: 代码块计数 parity。"""

    @staticmethod
    def _count_code_blocks(text: str) -> int:
        return text.count("```") // 2

    @staticmethod
    def _count_external_links(text: str) -> int:
        return len(re.findall(r"\]\(https?://", text))

    def test_code_block_count_equal(self):
        en_text = DOC_EN.read_text(encoding="utf-8")
        zh_text = DOC_ZH.read_text(encoding="utf-8")
        en_blocks = self._count_code_blocks(en_text)
        zh_blocks = self._count_code_blocks(zh_text)
        assert en_blocks == zh_blocks, (
            f"R394-L4: code block count mismatch — EN={en_blocks}, "
            f"ZH={zh_blocks}. Code examples should be 1:1 bilingual."
        )

    def test_external_link_count_within_2(self):
        en_text = DOC_EN.read_text(encoding="utf-8")
        zh_text = DOC_ZH.read_text(encoding="utf-8")
        en_links = self._count_external_links(en_text)
        zh_links = self._count_external_links(zh_text)
        assert abs(en_links - zh_links) <= 2, (
            f"R394-L4: external link count differs by "
            f"{abs(en_links - zh_links)} (EN={en_links}, "
            f"ZH={zh_links}); ≤ 2 expected"
        )


class TestR394LineageMarker:
    """R394 lineage marker: doc-parity 4th 应用进入深化期工业化。"""

    def test_this_file_contains_r394_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R394" in text

    def test_this_file_references_doc_parity_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R335", "R340", "R346"):
            assert prior in text, f"R394: must cite doc-parity lineage: {prior}"

    def test_this_file_marks_4th_app_deepening(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("doc-parity 4th 应用", "深化期工业化"):
            assert kw in text, f"R394: missing keyword: {kw!r}"
