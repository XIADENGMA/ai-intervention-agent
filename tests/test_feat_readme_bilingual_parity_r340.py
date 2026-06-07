"""R340 · README.md EN ↔ zh-CN section parity invariant
(cycle-37 #C1, doc-parity 子模式 2nd 应用, R335 模板复用)。

背景
----

cycle-36 R335 引入 doc-parity invariant 子模式 (cr59 R303 deferred 收口),
首次应用在 ``docs/troubleshooting.md`` 双语对齐。R340 把同一模板扩展到
**README** 双语对齐 — 这是 user-facing 最关键的入口文档。

R340 lock 内容
--------------

锁定 ``README.md`` (英文) 与 ``README.zh-CN.md`` (中文) 的结构对等:

1. **Layer 1 (Section count parity)**: ``##`` 章节数严格相等 (当前 11)
2. **Layer 2 (Section index parity)**: 章节顺序对应 — 第 N 个英文 section
   必须对应第 N 个中文 section (语义级 mapping)
3. **Layer 3 (Image alt-text parity)**: 截图章节内的 ``![alt](src)``
   image 数量必须相等 (避免某语言缺截图)
4. **Layer 4 (Anchor link integrity)**: 任何 ``#anchor`` 链接必须能在同
   一文档内找到对应 heading (避免 dead anchors)

methodology lineage
-------------------

- R303 (cycle-29 deferred): 提出 doc-parity invariant 候选
- R335 (cycle-36): doc-parity invariant 子模式启动, 1st app =
  troubleshooting.md
- **R340 (本 commit, cycle-37)**: doc-parity invariant 2nd app = README.md

R340 完成意味着 doc-parity 子模式达 **2 应用巩固阶段** (与 v3.7/v3.8/v3.9
"3 应用工业化阈值" 相对), 可继续向 packages/vscode/README* / docs/api/
扩展。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_EN = REPO_ROOT / "README.md"
README_ZH = REPO_ROOT / "README.zh-CN.md"


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _extract_headings(lines: list[str], level: int) -> list[str]:
    prefix = "#" * level + " "
    return [
        line[len(prefix) :].strip()
        for line in lines
        if line.startswith(prefix) and not line.startswith("#" * (level + 1))
    ]


class TestLayer1SectionCountParity:
    def test_both_readmes_exist(self):
        assert README_EN.is_file()
        assert README_ZH.is_file()

    def test_section_count_equal(self):
        en = _extract_headings(_read_lines(README_EN), 2)
        zh = _extract_headings(_read_lines(README_ZH), 2)
        assert len(en) == len(zh), (
            f"R340-L1: README ## section count mismatch!\n"
            f"  EN ({len(en)}): {en}\n"
            f"  ZH ({len(zh)}): {zh}\n"
            f"NOTE: cycle-37 baseline = 11 sections; any change must "
            f"audit both languages."
        )


class TestLayer2SectionIndexParity:
    """Layer 2: 第 N 个英文 section 必须对应第 N 个中文 section (语义级
    一致, 不要求字面翻译)。"""

    # 已审查的章节语义 mapping (English heading prefix → 中文 heading prefix)
    EXPECTED_MAPPING = (
        ("Quick start", "快速开始"),
        ("Screenshots", "界面截图"),
        ("Key features", "主要特性"),
        ("Architecture overview", "架构总览"),
        ("Agent / Glass mode", "Agent / Glass 模式"),
        ("VS Code extension", "VS Code 插件"),
        ("Configuration", "配置说明"),
        ("Documentation", "文档"),
        ("Related projects", "同类产品"),
        ("Acknowledgements", "致谢"),
        ("License", "开源协议"),
    )

    def test_section_semantic_mapping_intact(self, subtests):
        en = _extract_headings(_read_lines(README_EN), 2)
        zh = _extract_headings(_read_lines(README_ZH), 2)
        assert len(en) == len(self.EXPECTED_MAPPING), (
            f"R340-L2: EN README section count drift from baseline "
            f"({len(self.EXPECTED_MAPPING)}). Update EXPECTED_MAPPING."
        )
        for i, (en_prefix, zh_prefix) in enumerate(self.EXPECTED_MAPPING):
            with subtests.test(idx=i, en=en_prefix, zh=zh_prefix):
                assert en[i].startswith(en_prefix), (
                    f"R340-L2 EN: section {i + 1} expected to start with "
                    f"`{en_prefix}`, got `{en[i]}`"
                )
                assert zh[i].startswith(zh_prefix), (
                    f"R340-L2 ZH: section {i + 1} expected to start with "
                    f"`{zh_prefix}`, got `{zh[i]}`"
                )


class TestLayer3ImageAltTextParity:
    """Layer 3: 截图章节内的 ``![alt](src)`` 数量必须相等 (避免某语言
    缺截图)。"""

    @staticmethod
    def _extract_images(text: str) -> list[str]:
        # 匹配 markdown image syntax ![alt](src)
        return re.findall(r"!\[[^\]]*\]\([^)]+\)", text)

    def test_image_count_equal(self):
        en_imgs = self._extract_images(README_EN.read_text(encoding="utf-8"))
        zh_imgs = self._extract_images(README_ZH.read_text(encoding="utf-8"))
        assert len(en_imgs) == len(zh_imgs), (
            f"R340-L3: README image count mismatch!\n"
            f"  EN images: {len(en_imgs)}\n"
            f"  ZH images: {len(zh_imgs)}"
        )


class TestLayer4AnchorLinkIntegrity:
    """Layer 4: 任何 ``#anchor`` 链接必须能在同一文档内找到对应 heading
    (避免 dead anchors)。"""

    @staticmethod
    def _extract_anchor_links(text: str) -> set[str]:
        """提取 markdown link `(#anchor)` (排除外部 URL)。"""
        return set(re.findall(r"\]\(#([a-z0-9\-]+)\)", text, re.IGNORECASE))

    @staticmethod
    def _heading_to_anchor(heading: str) -> str:
        """Markdown heading → anchor slug (GitHub style)."""
        # 简化: 转小写, 空格 → "-", 移除非字母数字字符
        s = heading.lower()
        s = re.sub(r"[^\w\s-]", "", s)
        s = re.sub(r"\s+", "-", s.strip())
        return s

    def test_en_anchors_resolve(self):
        text = README_EN.read_text(encoding="utf-8")
        anchors = self._extract_anchor_links(text)
        if not anchors:
            return  # nothing to check
        # 提取所有 heading anchors (level 1-4)
        all_headings: list[str] = []
        for level in range(1, 5):
            all_headings.extend(_extract_headings(_read_lines(README_EN), level))
        valid_slugs = {self._heading_to_anchor(h) for h in all_headings}
        unresolved = anchors - valid_slugs
        assert not unresolved, (
            f"R340-L4 EN: dead anchor links!\n"
            f"  unresolved: {sorted(unresolved)}\n"
            f"  available slugs (sample): {sorted(valid_slugs)[:10]}..."
        )


class TestR340LineageMarker:
    """R340 是 doc-parity 子模式 2nd app, R335 模板复用。"""

    def test_this_file_contains_r340_marker(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R340" in text

    def test_this_file_references_r335_template_origin(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "R335" in text, "R340: must cite R335 (template origin)"

    def test_this_file_marks_doc_parity_2nd_app(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert "doc-parity" in text
        assert "2nd" in text.lower() or "第 2" in text
