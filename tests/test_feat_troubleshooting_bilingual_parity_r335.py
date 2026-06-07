"""R335 · docs/troubleshooting EN ↔ zh-CN 双语 parity invariant
(cycle-36 #R335, cr59 R303 deferred 收口)。

背景
----

cycle-29 cr59 §5 提出过 R303 候选 "docs/troubleshooting 双语 parity
invariant", 但因为 cycle-30+ 优先推进 methodology pattern 工业化, R303
被 deferred。cycle-36 在 v3.9 工业化完成后, 用 R335 收口此长期 debt。

R335 lock 内容
--------------

锁定 ``docs/troubleshooting.md`` (英文) 与 ``docs/troubleshooting.zh-CN.
md`` (中文) 的**结构对等**:

1. **Layer 1 (Section count parity)**: ``##`` 级章节数量必须严格相等
2. **Layer 2 (Subsection count parity)**: ``###`` 级子章节数量必须严格
   相等
3. **Layer 3 (Numbered section index parity)**: 编号章节 (如 ``## 1.``,
   ``## 2.``) 必须英中文都有, 且编号顺序一致
4. **Layer 4 (R-reference parity)**: 任何引用 R-series identifier
   (``R`` + 数字) 都必须双语都有, 不允许英文/中文版本独自引用某 R 编号

注意: R335 不锁住 section 文字翻译精度 (那需要人工评审), 只锁住"双语
都不缺章节" 这个最基本的 contract。

methodology lineage
-------------------

R335 是 **docs/parity invariant pattern 第 1 应用**, 可视为 v3.8
test-isolation pattern 的姊妹 — 都属于"一致性 invariant"家族, 但 R335
跨**自然语言文档** (非源代码)。未来扩展候选:

- README.md / README.zh-CN.md section parity
- packages/vscode/README* parity
- docs/api/index.md 双语 parity

methodology 命名: **v3.8 consistency pattern, doc-parity 子分支**。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_EN = REPO_ROOT / "docs" / "troubleshooting.md"
DOC_ZH = REPO_ROOT / "docs" / "troubleshooting.zh-CN.md"


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _extract_headings(lines: list[str], level: int) -> list[str]:
    """提取指定 ``##`` 级别的 heading 文本 (不含 ``#`` 前缀)。"""
    prefix = "#" * level + " "
    return [
        line[len(prefix) :].strip()
        for line in lines
        if line.startswith(prefix) and not line.startswith("#" * (level + 1))
    ]


class TestLayer1SectionCountParity:
    """Layer 1: ``##`` 级章节数量必须严格相等。"""

    def test_both_docs_exist(self):
        assert DOC_EN.is_file(), f"R335-L1: {DOC_EN} missing"
        assert DOC_ZH.is_file(), f"R335-L1: {DOC_ZH} missing"

    def test_section_count_equal(self):
        en = _extract_headings(_read_lines(DOC_EN), 2)
        zh = _extract_headings(_read_lines(DOC_ZH), 2)
        assert len(en) == len(zh), (
            f"R335-L1: ## section count mismatch!\n"
            f"  EN ({len(en)}): {en}\n"
            f"  ZH ({len(zh)}): {zh}\n"
            f"diff: EN-only={set(en) - set(zh)}, ZH-only={set(zh) - set(en)}"
        )


class TestLayer2SubsectionCountParity:
    """Layer 2: ``###`` 级子章节数量必须严格相等。"""

    def test_subsection_count_equal(self):
        en = _extract_headings(_read_lines(DOC_EN), 3)
        zh = _extract_headings(_read_lines(DOC_ZH), 3)
        assert len(en) == len(zh), (
            f"R335-L2: ### subsection count mismatch!\n"
            f"  EN ({len(en)}): {en}\n"
            f"  ZH ({len(zh)}): {zh}"
        )


class TestLayer3NumberedSectionIndexParity:
    """Layer 3: ``## 1.``, ``## 2.`` 等编号章节必须英中文都有, 编号顺序
    一致。"""

    @staticmethod
    def _extract_numbered_indices(headings: list[str]) -> list[int]:
        """提取章节编号 (例如 "1. Web UI does not start" → 1)。"""
        indices: list[int] = []
        for h in headings:
            m = re.match(r"(\d+)\.\s+", h)
            if m:
                indices.append(int(m.group(1)))
        return indices

    def test_numbered_indices_match(self):
        en_h = _extract_headings(_read_lines(DOC_EN), 2)
        zh_h = _extract_headings(_read_lines(DOC_ZH), 2)
        en_nums = self._extract_numbered_indices(en_h)
        zh_nums = self._extract_numbered_indices(zh_h)
        assert en_nums == zh_nums, (
            f"R335-L3: numbered section indices differ!\n"
            f"  EN: {en_nums}\n"
            f"  ZH: {zh_nums}"
        )

    def test_indices_are_sequential_from_1(self):
        """编号必须从 1 开始连续, 没有跳号。"""
        en_h = _extract_headings(_read_lines(DOC_EN), 2)
        en_nums = self._extract_numbered_indices(en_h)
        if en_nums:
            expected = list(range(1, len(en_nums) + 1))
            assert en_nums == expected, (
                f"R335-L3: EN numbered sections must be 1..N sequential, "
                f"got {en_nums} (expected {expected})"
            )


class TestLayer4RReferenceParity:
    r"""Layer 4: 任何引用的 R-series identifier (R\d+) 必须双语都引用 (或
    都不引用), 避免某语言独自引用某 R 而另一语言遗漏。"""

    @staticmethod
    def _extract_r_refs(text: str) -> set[str]:
        # 匹配 R 后跟 2-3 位数字, 且不在 URL / 路径中 (简单 negative lookbehind:
        # 前一个字符不是 '/' 或 alphanumeric)
        return set(re.findall(r"\bR\d{2,4}\b", text))

    def test_r_reference_sets_equal(self):
        en_refs = self._extract_r_refs(DOC_EN.read_text(encoding="utf-8"))
        zh_refs = self._extract_r_refs(DOC_ZH.read_text(encoding="utf-8"))
        only_en = en_refs - zh_refs
        only_zh = zh_refs - en_refs
        assert not only_en and not only_zh, (
            f"R335-L4: R-reference asymmetry!\n"
            f"  EN-only R refs: {sorted(only_en)}\n"
            f"  ZH-only R refs: {sorted(only_zh)}\n"
            f"Bilingual docs must reference the same R-series identifiers."
        )


class TestR335LineageMarker:
    """R335 引入 doc-parity invariant pattern, cycle-29 R303 deferred 收
    口。"""

    def test_this_file_contains_r335_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R335" in text

    def test_this_file_references_r303_lineage(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R303" in text, "R335: must cite R303 as prior deferred plan"

    def test_this_file_marks_pattern_subbranch(self):
        text = Path(__file__).read_text(encoding="utf-8")
        for kw in ("doc-parity", "consistency", "v3.8"):
            assert kw in text, f"R335: missing keyword: {kw!r}"
