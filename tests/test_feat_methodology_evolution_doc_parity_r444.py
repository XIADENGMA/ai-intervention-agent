"""R444 (cycle-51 #C1) — v3.11 series 正式启动 + methodology evolution
doc structure invariant + doc-parity 子模式第 7 应用。

血脉关系 (Lineage):
- doc-parity 子模式累计应用 7: R335 (cycle-36) → R340 (cycle-37) → R346
  (cycle-38) → R394 (cycle-44) → R400 (cycle-45) → R408 (cycle-46) →
  **R444 (cycle-51)** = 7 应用 → 完全工业化深化期
- v3.11 系列正式命名 — 元方法学层从 R414 (cycle-47 1st 应用) 到 R442
  (cycle-51 11th 应用) 历经 5 cycle, 现在通过 `docs/methodology-evolution.md`
  正式命名为 v3.11

战略 (Strategy):
- R444 锁定 `docs/methodology-evolution.{md,zh-CN.md}` 的结构, 保证 v3.11
  作为 *正式命名* 不会被未来 refactor 误删或回退
- doc 文件保留 v3.0 → v3.11 全部维度概览, 每个维度一行 table entry
- 4 layer 设计:
  * Layer 1: 两个文件都存在且非空 (bilingual)
  * Layer 2: 表头结构一致 (table 列数 / 标题层级)
  * Layer 3: v3.11 entry 正确 (anchor / 11+ 应用 / 完全工业化)
  * Layer 4: lineage + milestone

业务价值 (Business value):
- 任何新贡献者 (人 / agent) 想了解 invariant 测试方法学时, 有 *单一权威
  来源* (single source of truth) 可以快速理解 v3.0-v3.11 全部维度
- 防止历史维度信息散落在零散 CR 里被遗忘 (cycle-1 到 cycle-51 累积 51
  个 cycle, 知识管理是真问题)
- v3.11 系列正式命名意味着元方法学层 *作为方法学维度* 与 doc-parity
  (v3.5) / perf-baseline (v3.6) 等老牌维度同级, 不再是 "实验性扩展"

设计 (Design, 4 layers):
- Layer 1 (bilingual SSoT): 两个文件都存在且 ≥ 500 chars
- Layer 2 (structural parity): 表头 / table 列数 / heading 数量一致
- Layer 3 (v3.11 anchor): 两个文件都有 v3.11 entry 且关键信息正确
- Layer 4 (lineage marker): 文档引用 R414/R438/R442 等血脉
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
EN_DOC = DOCS_DIR / "methodology-evolution.md"
ZH_DOC = DOCS_DIR / "methodology-evolution.zh-CN.md"


def _heading_count(text: str, level: int) -> int:
    """Count markdown headings of given level."""
    prefix = "#" * level + " "
    return sum(1 for line in text.splitlines() if line.startswith(prefix))


def _table_row_count(text: str) -> int:
    """Count markdown table rows (lines starting with `|`)."""
    return sum(1 for line in text.splitlines() if line.strip().startswith("|"))


class TestLayer1BilingualSsotExists(unittest.TestCase):
    """Layer 1: 两个文件都存在且非空。"""

    def test_en_doc_exists_non_trivial(self) -> None:
        self.assertTrue(
            EN_DOC.exists(),
            f"R444 Layer 1: {EN_DOC.name} must exist (SSoT for v3.0-v3.11)",
        )
        size = EN_DOC.stat().st_size
        self.assertGreaterEqual(
            size,
            500,
            f"R444 Layer 1: {EN_DOC.name} too small ({size} bytes); "
            f"应至少 500 bytes 覆盖 v3.0-v3.11 全维度",
        )

    def test_zh_doc_exists_non_trivial(self) -> None:
        self.assertTrue(
            ZH_DOC.exists(),
            f"R444 Layer 1: {ZH_DOC.name} must exist (bilingual SSoT)",
        )
        size = ZH_DOC.stat().st_size
        self.assertGreaterEqual(
            size,
            500,
            f"R444 Layer 1: {ZH_DOC.name} too small ({size} bytes)",
        )


class TestLayer2StructuralParity(unittest.TestCase):
    """Layer 2: 两个文件结构 parity (heading 数 + table 行数 ±20%)。"""

    def setUp(self) -> None:
        self.en_text = EN_DOC.read_text(encoding="utf-8")
        self.zh_text = ZH_DOC.read_text(encoding="utf-8")

    def test_h1_count_parity(self) -> None:
        """Both have exactly 1 H1."""
        self.assertEqual(_heading_count(self.en_text, 1), 1)
        self.assertEqual(_heading_count(self.zh_text, 1), 1)

    def test_h2_count_parity(self) -> None:
        """H2 count must match (1 file = N H2, 另一个 file = N H2)."""
        en_h2 = _heading_count(self.en_text, 2)
        zh_h2 = _heading_count(self.zh_text, 2)
        self.assertEqual(
            en_h2,
            zh_h2,
            f"R444 Layer 2: H2 count drift — en={en_h2}, zh={zh_h2}. "
            f"双语文档结构必须 parity, 否则 翻译漏了一个 section",
        )
        self.assertGreaterEqual(
            en_h2, 3, "应至少 3 个 H2 (Overview / v3.11 / See also)"
        )

    def test_h3_count_parity(self) -> None:
        """H3 count must match (v3.11 内部子段落)."""
        en_h3 = _heading_count(self.en_text, 3)
        zh_h3 = _heading_count(self.zh_text, 3)
        self.assertEqual(
            en_h3,
            zh_h3,
            f"R444 Layer 2: H3 count drift — en={en_h3}, zh={zh_h3}",
        )

    def test_table_row_count_within_tolerance(self) -> None:
        """Table row count must be similar (±5 rows tolerance for
        formatting differences like trailing pipe)."""
        en_rows = _table_row_count(self.en_text)
        zh_rows = _table_row_count(self.zh_text)
        self.assertLessEqual(
            abs(en_rows - zh_rows),
            5,
            f"R444 Layer 2: table row count drift — en={en_rows}, "
            f"zh={zh_rows}, diff={abs(en_rows - zh_rows)}. 双语 table 应 parity",
        )


class TestLayer3V311AnchorCorrect(unittest.TestCase):
    """Layer 3: v3.11 entry 关键信息正确 (anchor / 11+ 应用 / 元方法学层)。"""

    def setUp(self) -> None:
        self.en_text = EN_DOC.read_text(encoding="utf-8")
        self.zh_text = ZH_DOC.read_text(encoding="utf-8")

    def test_v311_entry_in_both_docs(self) -> None:
        self.assertIn(
            "v3.11", self.en_text, "R444 Layer 3: en doc must have v3.11 entry"
        )
        self.assertIn(
            "v3.11", self.zh_text, "R444 Layer 3: zh doc must have v3.11 entry"
        )

    def test_v311_marks_meta_invariant_layer(self) -> None:
        """v3.11 必须明确说明是 meta-invariant / 元方法学层。"""
        self.assertTrue(
            "Meta-invariant" in self.en_text or "meta-invariant" in self.en_text,
            "R444 Layer 3: en doc v3.11 entry must mention 'Meta-invariant'",
        )
        self.assertIn(
            "元方法学层",
            self.zh_text,
            "R444 Layer 3: zh doc v3.11 entry must mention 元方法学层",
        )

    def test_v311_marks_minimum_11_applications(self) -> None:
        """v3.11 entry 必须标记应用数 ≥ 11 (cycle-51 milestone)。"""
        for text, name in ((self.en_text, "en"), (self.zh_text, "zh")):
            # 寻找 "11+" 或 "11 应用" 或 "11th" 字样
            patterns = [r"11\+", r"11 ", r"11th", r"11 应用"]
            matched = any(re.search(p, text) for p in patterns)
            self.assertTrue(
                matched,
                f"R444 Layer 3: {name} doc must reference ≥ 11 applications "
                f"(cycle-51 milestone) but found none of {patterns}",
            )

    def test_v311_sub_patterns_documented(self) -> None:
        """v3.11 必须列出 5 子模式: Ratchet/doc-parity/API contract/i18n/Mixin。"""
        for text, name in ((self.en_text, "en"), (self.zh_text, "zh")):
            for sub_pattern in (
                "Ratchet",
                "doc-parity",
                "API contract",
                "i18n",
                "Mixin",
            ):
                self.assertIn(
                    sub_pattern,
                    text,
                    f"R444 Layer 3: {name} doc v3.11 entry must list "
                    f"sub-pattern: {sub_pattern}",
                )


class TestLayer4LineageMarker(unittest.TestCase):
    """Layer 4: lineage marker — 文档与本 invariant 文件互引。"""

    def test_doc_references_anchor_r_numbers(self) -> None:
        """文档必须引用 v3.11 关键 R# (R414 1st app + R442 11th app)。"""
        for doc, name in ((EN_DOC, "en"), (ZH_DOC, "zh")):
            text = doc.read_text(encoding="utf-8")
            for anchor in ("R414", "R438", "R442"):
                self.assertIn(
                    anchor,
                    text,
                    f"R444 Layer 4: {name} doc must reference v3.11 anchor: {anchor}",
                )

    def test_this_file_references_doc_parity_lineage(self) -> None:
        """本 R444 文件必须引用 doc-parity 子模式血脉。"""
        text = Path(__file__).read_text(encoding="utf-8")
        for prior in ("R335", "R340", "R346", "R394", "R400", "R408"):
            self.assertIn(
                prior,
                text,
                f"R444: must cite doc-parity lineage: {prior}",
            )

    def test_this_file_marks_v311_formal_naming(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("v3.11", "正式命名"):
            self.assertIn(kw, text, f"R444: must mark v3.11 formal naming: {kw!r}")


if __name__ == "__main__":
    unittest.main()
