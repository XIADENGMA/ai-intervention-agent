"""R400 · ``docs/contributor-guide-invariant-tests.{md,zh-CN.md}`` 双语
parity invariant (cycle-45 #B1, doc-parity 5th 应用 → **5 应用深化期
工业化里程碑**)。

doc-parity 系列累计应用
-----------------------

- R335 (cycle-36): ``docs/troubleshooting.{md,zh-CN.md}`` — 1st app
- R340 (cycle-37): ``README.{md,zh-CN.md}`` 主仓 README — 2nd app
- R346 (cycle-38): ``packages/vscode/README.{md,zh-CN.md}`` — 3rd app
- R394 (cycle-44): ``docs/configuration.{md,zh-CN.md}`` — 4th app
- **R400 (cycle-45)** — ``docs/contributor-guide-invariant-tests.{md,zh-CN.md}``
  → **5th app 5 应用深化期工业化里程碑**, doc-parity 子模式与
  API contract (7 应用) / v3.6 perf-baseline (9 应用) / v3.7 decision-
  three-layer (4 应用) 等成熟 pattern 进入同一深化期梯队

特殊价值
--------

``contributor-guide-invariant-tests`` 是项目方法学的入口文档, 是 290+
invariant 的 meta-doc。invariant pattern 演化时, 中英文文档必须同步,
否则:

- 英文 PR contributor 看的是 EN 最新版, 但 zh-CN 仍是旧版 → 中文母
  语开发者按旧 pattern 写新 invariant, 漏掉 ``Whitelist meaningful``
  等 layer 3 概念;
- 项目自我引用 (e.g., README link to contributor-guide) 出现"英文跳
  中文断链";

R400 锁定方法学入口文档的双语 parity, 是 doc-parity pattern 自我应
用到方法学元文档的 reflexive 应用。

R400 invariant (4 层 + lineage marker)
--------------------------------------

1. **Layer 1 (Anchor)**: 两个文件存在 + 行数差异 ≤ 30%
2. **Layer 2 (章节结构 1:1)**: ``## section`` 数量 + 顺序完全 1:1 映射
3. **Layer 3 (语义映射表)**: 每个英文 H2 有对应中文翻译, 通过
   ``SECTION_MAPPING`` 显式锁定
4. **Layer 4 (代码块计数 parity)**: triple backtick fence 数量平衡

methodology lineage
-------------------

doc-parity 从 cycle-36 启动到 cycle-45 完成 1→5 应用, 5 应用 = 深化
期里程碑, 与 i18n consistency (R350/R353/R366/R374, 4 应用) / API
contract (R355/R358/R364/R368/R378/R392/R398, 7 应用) / cross-language
schema (R285/R297/R302/R360, 4 应用) 等其他 4+/5+/7 应用维度并列,
形成 "用户/开发者面向产物完整性" 多维度协同。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_EN = REPO_ROOT / "docs" / "contributor-guide-invariant-tests.md"
DOC_ZH = REPO_ROOT / "docs" / "contributor-guide-invariant-tests.zh-CN.md"

SECTION_MAPPING: dict[str, str] = {
    "1. What is an invariant test?": "1. 什么是不变量测试",
    "2. When to write one — decision tree": ("2. 何时该写一个 —— 决策树"),
    "3. Five recurring patterns": "3. 五种常见模式",
    "4. Anti-patterns to avoid": "4. 应该回避的反模式",
    "5. Workflow": "5. 工作流",
    "6. Repository-wide invariant test catalogue": "6. 仓库不变量测试总览",
    "7. Further reading": "7. 进一步阅读",
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
        assert DOC_EN.is_file(), f"R400-L1: {DOC_EN} missing"

    def test_zh_file_exists(self):
        assert DOC_ZH.is_file(), f"R400-L1: {DOC_ZH} missing"

    def test_line_count_within_30_percent(self):
        en_lines = DOC_EN.read_text(encoding="utf-8").splitlines()
        zh_lines = DOC_ZH.read_text(encoding="utf-8").splitlines()
        ratio = abs(len(en_lines) - len(zh_lines)) / max(len(en_lines), len(zh_lines))
        assert ratio <= 0.30, (
            f"R400-L1: line count differs by {ratio:.1%} "
            f"(EN={len(en_lines)}, ZH={len(zh_lines)}); ≤ 30% expected"
        )


class TestLayer2StructuralParity:
    """Layer 2: ## 章节数量 + 顺序 1:1 映射。"""

    def test_h2_count_equal(self):
        en = _extract_h2_headings(DOC_EN)
        zh = _extract_h2_headings(DOC_ZH)
        assert len(en) == len(zh), (
            f"R400-L2: H2 count mismatch — EN has {len(en)} sections, "
            f"ZH has {len(zh)}. EN={en}, ZH={zh}"
        )


class TestLayer3SemanticMapping:
    """Layer 3: 每个 H2 必须在 SECTION_MAPPING 内有 1:1 mapping。"""

    def test_every_en_section_in_mapping(self):
        en = _extract_h2_headings(DOC_EN)
        missing = [s for s in en if s not in SECTION_MAPPING]
        assert not missing, (
            f"R400-L3: EN H2 missing from SECTION_MAPPING: "
            f"{missing}. Update SECTION_MAPPING or rename headings."
        )

    def test_every_zh_section_in_mapping(self):
        zh = _extract_h2_headings(DOC_ZH)
        zh_values = set(SECTION_MAPPING.values())
        missing = [s for s in zh if s not in zh_values]
        assert not missing, (
            f"R400-L3: ZH H2 missing from SECTION_MAPPING values: {missing}"
        )

    def test_order_matches_via_mapping(self):
        en = _extract_h2_headings(DOC_EN)
        zh = _extract_h2_headings(DOC_ZH)
        expected_zh = [SECTION_MAPPING.get(e, "<UNMAPPED>") for e in en]
        assert zh == expected_zh, (
            f"R400-L3: H2 order mismatch.\nEN -> mapped: {expected_zh}\nZH actual: {zh}"
        )


class TestLayer4ContentArtifactsParity:
    """Layer 4: 代码块计数 + 外链计数 parity。"""

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
            f"R400-L4: code block count mismatch — EN={en_blocks}, "
            f"ZH={zh_blocks}. Code examples should be 1:1 bilingual."
        )

    def test_external_link_count_within_3(self):
        en_text = DOC_EN.read_text(encoding="utf-8")
        zh_text = DOC_ZH.read_text(encoding="utf-8")
        en_links = self._count_external_links(en_text)
        zh_links = self._count_external_links(zh_text)
        assert abs(en_links - zh_links) <= 3, (
            f"R400-L4: external link count differs by "
            f"{abs(en_links - zh_links)} (EN={en_links}, "
            f"ZH={zh_links}); ≤ 3 expected"
        )


class TestR400LineageMarker:
    """R400 lineage marker: doc-parity 5 应用深化期工业化里程碑。"""

    def test_this_file_contains_r400_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R400" in text

    def test_this_file_references_doc_parity_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R335", "R340", "R346", "R394"):
            assert prior in text, f"R400: must cite doc-parity lineage: {prior}"

    def test_this_file_marks_5th_app_milestone(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("doc-parity 5th 应用", "5 应用深化期工业化里程碑"):
            assert kw in text, f"R400: missing keyword: {kw!r}"
