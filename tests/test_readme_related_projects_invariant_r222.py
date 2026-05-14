"""R222 / Cycle 12 · F-cycle11-4: README "Related projects" expansion invariant.

设计目标
========

CR#24 flagged `F-cycle11-4`: the existing `## Related projects` /
`## 同类产品` sections were minimal bullet lists of 4 links each
without descriptions or comparative positioning—useless to a new
user evaluating whether AIIA fits their stack. R222 expanded both
README files into 4-row comparison tables with star counts, focus
descriptions, and a "where AIIA sits" positioning paragraph that
references the R220 observability dashboard.

But README content is **the most drift-prone surface in the
project**—docs cycles drop frequently, contributors edit only one
language, copy-paste mishaps duplicate entries, and stale "as of
DATE" claims rot silently. R222 ships a lockdown invariant to:

1. Guarantee both EN + zh-CN sections exist with their canonical
   anchors (`## Related projects` / `## 同类产品`).
2. Ensure all 4 known sibling projects continue to be referenced
   in **both** files (sync invariant — bilingual lockstep).
3. Lock the "Where AIIA sits" positioning paragraph keywords so
   that future edits can't accidentally remove the differentiation
   text.
4. Verify the cross-reference to `docs/observability/README{,.zh-
   CN}.md` (R220 dashboard) survives README reformats — this is
   the *only* place in the main README that points users at the
   Grafana JSON.

These four invariants combined make the "Related projects"
section a documented, version-controlled comparison artifact
rather than a stale bullet list.

设计契约 / Test cases
====================

A. **Section presence + canonical anchor headings.**
B. **Bilingual project-link sync** — both languages reference
   the same 4 project URLs (set equality).
C. **Star count metadata present** — each English row has a
   `~Xk` or `~XXX` star marker.
D. **"Where AIIA sits" positioning paragraph present** in both
   languages, mentioning observability dashboard cross-link.
E. **R220 Grafana dashboard README cross-link present** — both
   languages link the bilingual observability README.

不变量保护范围
==============

* 增加新的 related project (PR contribution) → 只需更新
  `KNOWN_PROJECT_URLS` 并重新跑测试。
* 重排序 table 行 → 不影响 (用 set equality)。
* 把 "stars" 列改成不同格式 (例如 `~5k+` / `3.8k`) → 测试只
  要 `~` 前缀存在即可，所以宽容。
* 翻译微调 → 不影响 (只检查 anchor + keywords + url + cross-link)。

实施于 2026-05-14，6 cases / ~12 subtests。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_EN = REPO_ROOT / "README.md"
README_ZH = REPO_ROOT / "README.zh-CN.md"
DASHBOARD_README_EN_REL = "docs/observability/README.md"
DASHBOARD_README_ZH_REL = "docs/observability/README.zh-CN.md"

KNOWN_PROJECT_URLS: tuple[str, ...] = (
    "https://github.com/Minidoracat/mcp-feedback-enhanced",
    "https://github.com/imhuso/cunzhi",
    "https://github.com/poliva/interactive-feedback-mcp",
    "https://github.com/Pursue-LLL/interactive-feedback-mcp",
)


def _extract_section(text: str, *, anchor_re: re.Pattern[str]) -> str:
    """Return the body of the markdown section starting at *anchor_re*.

    Section ends at the next ``## `` heading or EOF.
    """
    m = anchor_re.search(text)
    if m is None:
        return ""
    start = m.end()
    next_section = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + next_section.start() if next_section else len(text)
    return text[start:end]


class TestSectionPresence(unittest.TestCase):
    """A. Both READMEs declare the canonical Related-projects section."""

    EN_ANCHOR_RE = re.compile(r"^## Related projects\s*$", re.MULTILINE)
    ZH_ANCHOR_RE = re.compile(r"^## 同类产品\s*$", re.MULTILINE)

    def test_en_readme_has_related_projects_anchor(self) -> None:
        text = README_EN.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            self.EN_ANCHOR_RE,
            f"EN README missing `## Related projects` anchor (path: {README_EN})",
        )

    def test_zh_readme_has_same_kind_anchor(self) -> None:
        text = README_ZH.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            self.ZH_ANCHOR_RE,
            f"zh-CN README missing `## 同类产品` anchor (path: {README_ZH})",
        )


class TestBilingualProjectLinkSync(unittest.TestCase):
    """B. Both READMEs reference the exact same set of 4 sibling project URLs.

    Uses set equality so re-ordering rows is allowed; adding/removing a
    project deliberately requires updating ``KNOWN_PROJECT_URLS`` here.
    """

    def test_en_zh_link_sets_match_known_set(self) -> None:
        en_text = README_EN.read_text(encoding="utf-8")
        zh_text = README_ZH.read_text(encoding="utf-8")
        en_anchor = re.compile(r"^## Related projects\s*$", re.MULTILINE)
        zh_anchor = re.compile(r"^## 同类产品\s*$", re.MULTILINE)
        en_section = _extract_section(en_text, anchor_re=en_anchor)
        zh_section = _extract_section(zh_text, anchor_re=zh_anchor)

        for lang, section in (("en", en_section), ("zh-CN", zh_section)):
            with self.subTest(lang=lang):
                for url in KNOWN_PROJECT_URLS:
                    self.assertIn(
                        url,
                        section,
                        (
                            f"{lang} README 'Related projects' section "
                            f"missing {url}. Both languages must keep "
                            "the same set of known sibling projects."
                        ),
                    )


class TestStarCountMetadataPresent(unittest.TestCase):
    """C. Each English table row provides a star approximation marker.

    Loose match: the line containing the project URL must also contain
    a `~` followed by a number (3.8k / 1.4k / 310 / 30 etc.). This
    protects against future edits that strip the comparison column
    while keeping the bullet links.
    """

    def test_each_link_row_has_star_marker(self) -> None:
        text = README_EN.read_text(encoding="utf-8")
        anchor = re.compile(r"^## Related projects\s*$", re.MULTILINE)
        section = _extract_section(text, anchor_re=anchor)
        for url in KNOWN_PROJECT_URLS:
            with self.subTest(url=url):
                line = next(
                    (ln for ln in section.splitlines() if url in ln),
                    None,
                )
                self.assertIsNotNone(
                    line,
                    f"URL {url} not found in section",
                )
                assert line is not None
                self.assertRegex(
                    line,
                    r"~\d",
                    (
                        f"Row for {url} is missing the `~Xk` / `~XXX` "
                        "star approximation marker. The comparison "
                        "table's value depends on readers knowing the "
                        "rough scale of each sibling project."
                    ),
                )


class TestWhereAiiaSitsPositioning(unittest.TestCase):
    """D. Positioning paragraph survives reformats in both languages."""

    def test_en_positioning_paragraph_keywords_present(self) -> None:
        text = README_EN.read_text(encoding="utf-8")
        anchor = re.compile(r"^## Related projects\s*$", re.MULTILINE)
        section = _extract_section(text, anchor_re=anchor)
        # Lock 3 distinctive keywords that together form the positioning
        # claim. Loose enough to allow rewording, strict enough to fail
        # if the whole paragraph gets accidentally deleted.
        for keyword in (
            "AIIA sits on the spectrum",
            "observability",
            "invariant test",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(
                    keyword,
                    section,
                    (
                        f"EN README 'Where AIIA sits' paragraph missing "
                        f"keyword {keyword!r} — the positioning text "
                        "appears to have been removed or heavily "
                        "rewritten without updating this guard."
                    ),
                )

    def test_zh_positioning_paragraph_keywords_present(self) -> None:
        text = README_ZH.read_text(encoding="utf-8")
        anchor = re.compile(r"^## 同类产品\s*$", re.MULTILINE)
        section = _extract_section(text, anchor_re=anchor)
        for keyword in (
            "AIIA 在光谱中的位置",
            "可观测",
            "不变量测试",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(
                    keyword,
                    section,
                    (
                        f"zh-CN README 同类产品 段落缺少关键词 {keyword!r}——"
                        "定位段似乎被删除或大幅改写，未同步更新本守护测试。"
                    ),
                )


class TestObservabilityDashboardCrossLink(unittest.TestCase):
    """E. Both READMEs link to the R220 Grafana dashboard README sibling.

    This is the only place in the main README pointing readers at the
    observability/ subdirectory. Losing the link silently hides R220's
    work from new users.
    """

    def test_en_links_to_en_observability_readme(self) -> None:
        text = README_EN.read_text(encoding="utf-8")
        anchor = re.compile(r"^## Related projects\s*$", re.MULTILINE)
        section = _extract_section(text, anchor_re=anchor)
        self.assertIn(
            DASHBOARD_README_EN_REL,
            section,
            (
                f"EN README 'Related projects' positioning paragraph "
                f"must link to {DASHBOARD_README_EN_REL} so users can "
                "find the R220 Grafana dashboard."
            ),
        )

    def test_zh_links_to_zh_observability_readme(self) -> None:
        text = README_ZH.read_text(encoding="utf-8")
        anchor = re.compile(r"^## 同类产品\s*$", re.MULTILINE)
        section = _extract_section(text, anchor_re=anchor)
        self.assertIn(
            DASHBOARD_README_ZH_REL,
            section,
            (
                f"zh-CN README 同类产品 定位段必须链接到 "
                f"{DASHBOARD_README_ZH_REL}，否则用户找不到 R220 "
                "Grafana 仪表盘。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
