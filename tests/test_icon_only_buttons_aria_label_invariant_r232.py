"""R232 / Cycle 14 · F-cycle13-4: icon-only buttons must carry aria-label.

Why this invariant
------------------

R230 hid every decorative ``<svg>`` from assistive technology by adding
``aria-hidden="true"`` + ``focusable="false"``. That fix is correct for
button icons that sit next to a text label (e.g. ``[icon] Submit
feedback``) — AT reads the text and ignores the icon.

But for **icon-only** buttons (no text sibling), R230's change means AT
sees only an empty button. Without explicit ``aria-label``, screen
readers announce simply ``"button"`` with no description, leaving users
stranded — they can't tell submit from settings from theme-toggle.

Per WCAG 2.1 SC 4.1.2 (Name, Role, Value), every interactive control
must expose its accessible name to AT. For icon-only buttons that
means ``aria-label`` (or ``aria-labelledby``) on the button element
itself.

R232 audit (executed at CR#26 archival time):

* 28 ``<button>`` elements in ``web_ui.html``
* 0 icon-only buttons missing ``aria-label`` — discipline was already
  perfect because R125b / R230 contributors knew the rule
* 1 ``<a role="button">`` (export-tasks-btn) — has ``aria-label``

R232 commits the audit result as a permanent guard so a future
contributor adding an icon-only button without ``aria-label`` gets a
test failure immediately, not 6 months later when a screen-reader user
files an issue.

How "icon-only" is detected
----------------------------

A button (or ``<a role="button">``) is considered **icon-only** iff its
inner HTML, after stripping every ``<svg>...</svg>`` block and HTML
comments, contains no non-whitespace text. Decorative spans like
``<span class="sr-only">x</span>`` would count as text and thus
disqualify the element from icon-only classification (which is correct
— ``sr-only`` IS a screen-reader name source).

The discipline this enforces
-----------------------------

Two failure modes prevented:

1. **Bare button**: ``<button><svg .../></button>`` with no
   ``aria-label`` → fail. Adding ``aria-label="Save"`` (or
   ``aria-labelledby="..."`` pointing at a hidden span) fixes.
2. **Bare anchor with role=button**: same logic applied to
   ``<a role="button">``.

What we DON'T enforce (intentional non-scope)
---------------------------------------------

* Text-labeled buttons (have visible text) — already have an
  accessible name from the text node.
* Icon-only ``<a>`` without ``role="button"`` — those are links, not
  buttons; covered by a separate ``aria-label``-on-link discipline (
  no invariant yet — F-cycle14-X candidate).
* Form inputs (``<input type="button">``) — none in ``web_ui.html``
  currently; F-cycle14-X if any appear.
* The QUALITY of the aria-label string (e.g. "btn" is a bad label).
  Static check can't tell; relies on i18n review.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"


def _strip_svg_and_comments(inner_html: str) -> str:
    no_svg = re.sub(r"<svg\b.*?</svg>", "", inner_html, flags=re.DOTALL)
    no_comments = re.sub(r"<!--.*?-->", "", no_svg, flags=re.DOTALL)
    return no_comments


def _visible_text_only(stripped_inner: str) -> str:
    text = re.sub(r"<[^>]+>", "", stripped_inner)
    return text.strip()


def _enumerate_buttons(
    html: str,
) -> list[tuple[int, str, str, str]]:
    """Return (line_no, opening_attrs, raw_inner, element_kind) for every <button> and <a role="button">."""
    results: list[tuple[int, str, str, str]] = []

    for match in re.finditer(r"<button\b([^>]*)>(.*?)</button>", html, re.DOTALL):
        line_no = html[: match.start()].count("\n") + 1
        results.append((line_no, match.group(1), match.group(2), "button"))

    for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html, re.DOTALL):
        opening = match.group(1)
        if 'role="button"' not in opening:
            continue
        line_no = html[: match.start()].count("\n") + 1
        results.append((line_no, opening, match.group(2), "a"))

    return results


def _has_accessible_name(opening_attrs: str) -> bool:
    has_label = re.search(r"\baria-label\s*=", opening_attrs) is not None
    has_labelledby = re.search(r"\baria-labelledby\s*=", opening_attrs) is not None
    return has_label or has_labelledby


class TestEveryIconOnlyButtonHasAriaLabel(unittest.TestCase):
    def test_no_button_icon_only_lacks_aria_label(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        buttons = _enumerate_buttons(html)
        offenders: list[tuple[int, str, str]] = []
        for line_no, opening_attrs, inner_html, kind in buttons:
            visible_text = _visible_text_only(_strip_svg_and_comments(inner_html))
            if visible_text:
                continue
            if _has_accessible_name(opening_attrs):
                continue
            id_match = re.search(r'id="([^"]+)"', opening_attrs)
            ident = id_match.group(1) if id_match else "(no id)"
            offenders.append((line_no, kind, ident))

        self.assertEqual(
            offenders,
            [],
            (
                "R232 invariant: 每个 icon-only button / a[role=button] 必须有 "
                "aria-label (或 aria-labelledby)，否则 R230 把 SVG 都 aria-hidden 之后, "
                "屏幕阅读器只能宣读裸 'button' 没有任何描述。失败列表 "
                f"(line, kind, id): {offenders}。修复：给该元素加 "
                'aria-label="<语义化标签>" + data-i18n-aria-label="<i18n key>" '
                "实现 i18n。范例参考 web_ui.html 中 #theme-toggle-btn / "
                "#settings-btn 等 icon-only 按钮的已有写法。"
            ),
        )


class TestAuditCoverageSanityCheck(unittest.TestCase):
    """确保扫描枚举到了至少 20 个 button——否则测试本身可能被静默 break。"""

    EXPECTED_MIN_BUTTON_COUNT = 20

    def test_button_count_above_min_baseline(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        buttons = _enumerate_buttons(html)
        self.assertGreaterEqual(
            len(buttons),
            self.EXPECTED_MIN_BUTTON_COUNT,
            (
                f"R232 invariant: web_ui.html 中 <button> + <a role=button> "
                f"数量 ({len(buttons)}) 低于 baseline "
                f"({self.EXPECTED_MIN_BUTTON_COUNT})。如果是有意删模板部分，"
                "请同步更新 EXPECTED_MIN_BUTTON_COUNT。如果是意外回滚，请检查 "
                "git history。"
            ),
        )


class TestKnownIconOnlyButtonsAriaLabelPresent(unittest.TestCase):
    """显式锁定已知 icon-only 按钮的 aria-label 存在 (regression anchor)。"""

    KNOWN_ICON_ONLY_BUTTON_IDS = (
        "theme-toggle-btn",
        "settings-btn",
        # ``export-tasks-btn`` 在 feat-remove-download 中按用户要求从前端
        # 移除（``/api/tasks/export`` 后端 API 保留供 CI / 备份脚本调用）。
        # 历史 R125b/R232 invariant 锚点已转移到剩余两个按钮。
    )

    def test_each_known_icon_only_button_has_aria_label(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        for btn_id in self.KNOWN_ICON_ONLY_BUTTON_IDS:
            with self.subTest(button_id=btn_id):
                pattern = rf'id="{re.escape(btn_id)}"[^>]*'
                match = re.search(pattern, html, re.DOTALL)
                assert match is not None, (
                    f"R232 invariant: 找不到 known icon-only button #{btn_id}; "
                    "如果按钮被改名，请同步更新 KNOWN_ICON_ONLY_BUTTON_IDS。"
                )
                start = html.rfind("<", 0, match.start())
                end = html.find(">", match.end())
                opening_block = html[start : end + 1]
                self.assertTrue(
                    _has_accessible_name(opening_block),
                    f"R232 invariant: known icon-only button #{btn_id} 必须有 "
                    "aria-label / aria-labelledby。已知它历史上有这两个属性之一，"
                    "如果被无意删除，请回滚或加回。",
                )


if __name__ == "__main__":
    unittest.main()
