"""R812: nothing in the message card may run past the card on a narrow screen.

The approval page is read on phones (the Bark notification opens it there) and
in the VS Code side panel, both of which are 300-400 px wide.  A real-Chrome
measurement of one Markdown kitchen sink at 375 px showed that the card itself
never overflowed the page, but its *content* did, because nothing told it to
wrap or to scroll:

* an unbroken token or a long URL ran on for 1 574 px inside a 301 px
  paragraph (``overflow-wrap: normal``), so most of it was clipped and could
  not be read at all - the very links this page exists to show;
* a ten-column table was 570 px wide in a 375 px viewport (``overflow-x:
  visible``); the VS Code webview already scrolled it, the Web UI did not;
* a display formula (``$$ ... $$``) was 714 px wide in a 301 px paragraph;
* an option with a long unbroken label squeezed its checkbox down to 13 px
  (flex items shrink) and pushed the label 690 px out of its row, in both
  surfaces.

The fix is four small declarations per surface, and each one has a way to go
wrong that the tests below pin down:

* text wraps with ``overflow-wrap: anywhere`` on ``.markdown-content`` - but
  tables reset it to ``normal``, otherwise their columns would shrink to a few
  characters and break words in half instead of scrolling;
* a table is ``display: block`` with ``overflow-x: auto`` (as GitHub does), so
  it scrolls inside the card;
* a *display* formula scrolls inside the card, and an *inline* formula must
  not: ``overflow`` on an inline-block moves its baseline to the bottom margin
  edge, which would drop every inline formula below the text line.  A scroll
  box also clips, and a pixel diff over a 15-formula corpus showed that glyph
  tips (integral tails, bracket ends, accents) reach 1-2 px past MathJax's box
  and were cut off, so the box gets ``0.1em`` of vertical padding, paid for
  with ``0.1em`` less margin: MathJax's own ``margin: 1em 0`` is the spacing
  the page already had.  Because the margin is overridden, the selector needs
  one more attribute than MathJax's (``[jax]``) to win whatever the order in
  which the stylesheets load;
* an option's checkbox cannot shrink (``flex: none``) and its label can
  (``min-width: 0``) and wraps.

No browser runs in CI, so the tests parse ``main.css`` and ``webview.css`` and
check the declarations that decide the outcome.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
WEBVIEW_CSS = REPO_ROOT / "packages" / "vscode" / "webview.css"

WRAPPING = {"anywhere", "break-word"}
SCROLLING = {"auto", "scroll"}


def _rules(css: str) -> list[tuple[str, dict[str, str]]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: list[tuple[str, dict[str, str]]] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = match.group(1).strip()
        if selectors.startswith("@"):
            continue
        declarations: dict[str, str] = {}
        for declaration in match.group(2).split(";"):
            name, separator, value = declaration.partition(":")
            if separator:
                declarations[name.strip().lower()] = " ".join(value.split())
        for selector in selectors.split(","):
            rules.append((" ".join(selector.split()), declarations))
    return rules


def _declarations_of(css: str, selector: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for rule_selector, declarations in _rules(css):
        if rule_selector == selector:
            merged.update(declarations)
    return merged


def _bare(value: str) -> str:
    return value.replace("!important", "").strip().lower()


def _em(value: str) -> float:
    """The vertical component of ``margin`` / ``padding`` in em (``0.8em 0`` -> 0.8)."""
    first = _bare(value).split()[0]
    assert first.endswith("em"), value
    return float(first[:-2])


def _specificity(selector: str) -> tuple[int, int, int]:
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+", selector))
    types = len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", selector))
    return ids, classes, types


def _display_formula_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    return [
        (selector, declarations)
        for selector, declarations in _rules(css)
        if "mjx-container" in selector and re.search(r"\[display=[\"']?true", selector)
    ]


SURFACES = [
    pytest.param(MAIN_CSS, id="web-ui"),
    pytest.param(WEBVIEW_CSS, id="vscode-webview"),
]


@pytest.mark.parametrize("path", SURFACES)
class TestTextWrapsInsteadOfRunningPastTheCard:
    def test_the_card_wraps_unbroken_text(self, path: Path) -> None:
        declarations = _declarations_of(
            path.read_text(encoding="utf-8"), ".markdown-content"
        )

        assert _bare(declarations.get("overflow-wrap", "<missing>")) in WRAPPING, (
            "`.markdown-content` must declare `overflow-wrap: anywhere` so a long "
            "token or URL wraps instead of running past the card"
        )

    def test_tables_do_not_inherit_the_wrapping(self, path: Path) -> None:
        # `anywhere` lowers min-content width, so an inheriting table would
        # shrink its columns and break words mid-word instead of scrolling.
        declarations = _declarations_of(
            path.read_text(encoding="utf-8"), ".markdown-content table"
        )

        assert _bare(declarations.get("overflow-wrap", "<missing>")) == "normal"

    def test_code_blocks_still_wrap_their_own_lines(self, path: Path) -> None:
        # Premise: the fix is not what makes code wrap, it already did.
        declarations = _declarations_of(
            path.read_text(encoding="utf-8"), ".markdown-content pre code"
        )

        assert _bare(declarations.get("overflow-wrap", "<missing>")) in WRAPPING


@pytest.mark.parametrize("path", SURFACES)
class TestWideContentScrollsInsideTheCard:
    def test_a_table_is_a_scroll_box_no_wider_than_the_card(self, path: Path) -> None:
        declarations = _declarations_of(
            path.read_text(encoding="utf-8"), ".markdown-content table"
        )

        assert _bare(declarations.get("display", "<missing>")) == "block", (
            "a `display: table` element ignores `overflow`; make it a block"
        )
        assert _bare(declarations.get("overflow-x", "<missing>")) in SCROLLING
        assert _bare(declarations.get("max-width", "<missing>")) == "100%"

    def test_a_display_formula_scrolls_inside_the_card(self, path: Path) -> None:
        css = path.read_text(encoding="utf-8")
        rules = _display_formula_rules(css)

        assert rules, 'no rule targets `mjx-container[display="true"]`'
        merged: dict[str, str] = {}
        for _selector, declarations in rules:
            merged.update(declarations)
        assert _bare(merged.get("overflow-x", "<missing>")) in SCROLLING
        assert _bare(merged.get("max-width", "<missing>")) == "100%"
        # With `overflow-x` set, `overflow-y: visible` would compute to `auto`
        # and a stray vertical scrollbar would appear for a taller formula.
        assert _bare(merged.get("overflow-y", "<missing>")) == "hidden"

    def test_the_formula_rule_outranks_mathjax_own_container_rule(
        self, path: Path
    ) -> None:
        # MathJax injects `mjx-container[jax="..."][display="true"] { margin:
        # 1em 0 }` (one type + two attributes).  Ours overrides that margin,
        # so it must be strictly more specific: it adds the card's class.
        mathjax = (0, 2, 1)
        rules = _display_formula_rules(path.read_text(encoding="utf-8"))
        assert rules
        for selector, _declarations in rules:
            assert selector.startswith(".markdown-content "), selector
            assert _specificity(selector) > mathjax, (selector, _specificity(selector))

    def test_the_padding_that_protects_glyph_tips_is_paid_for_by_the_margin(
        self, path: Path
    ) -> None:
        merged: dict[str, str] = {}
        for _selector, declarations in _display_formula_rules(
            path.read_text(encoding="utf-8")
        ):
            merged.update(declarations)

        padding = _em(merged.get("padding", "<missing>"))
        margin = _em(merged.get("margin", "<missing>"))
        assert padding >= 0.1, "glyph tips reach 1 px past MathJax's box"
        # MathJax: `margin: 1em 0`.  Same total spacing, so no formula moves.
        assert round(margin + padding, 6) == 1.0, (margin, padding)
        # Only vertical: a horizontal padding would shrink the scroll port.
        assert _bare(merged["padding"]).split()[1:] in (["0"], ["0px"]), merged[
            "padding"
        ]

    def test_an_inline_formula_is_never_a_scroll_box(self, path: Path) -> None:
        # `overflow` on an inline-block moves its baseline to the bottom margin
        # edge: every inline formula would sit below its text line.
        offenders = []
        for selector, declarations in _rules(path.read_text(encoding="utf-8")):
            if "mjx-container" not in selector:
                continue
            if re.search(r"\[display=[\"']?true", selector):
                continue
            for name in ("overflow", "overflow-x", "overflow-y"):
                if _bare(declarations.get(name, "visible")) not in {"visible", "clip"}:
                    offenders.append(f"{selector} {{ {name}: {declarations[name]} }}")
        assert offenders == []


class TestAnOptionKeepsItsCheckboxAndWrapsItsLabel:
    def test_web_ui_checkbox_cannot_shrink(self) -> None:
        declarations = _declarations_of(
            MAIN_CSS.read_text(encoding="utf-8"), '.option-item input[type="checkbox"]'
        )

        flex = _bare(declarations.get("flex", declarations.get("flex-shrink", "")))
        assert flex in {"none", "0", "0 0 auto"}, flex

    def test_web_ui_label_may_shrink_below_its_longest_word_and_wraps(self) -> None:
        declarations = _declarations_of(
            MAIN_CSS.read_text(encoding="utf-8"), ".option-item label"
        )

        assert _bare(declarations.get("min-width", "<missing>")) in {"0", "0px"}
        assert _bare(declarations.get("overflow-wrap", "<missing>")) in WRAPPING

    def test_webview_checkbox_cannot_shrink(self) -> None:
        declarations = _declarations_of(
            WEBVIEW_CSS.read_text(encoding="utf-8"), ".option-checkbox"
        )

        flex = _bare(declarations.get("flex", declarations.get("flex-shrink", "")))
        assert flex in {"none", "0", "0 0 auto"}, flex

    def test_webview_label_may_shrink_below_its_longest_word_and_wraps(self) -> None:
        declarations = _declarations_of(
            WEBVIEW_CSS.read_text(encoding="utf-8"), ".option-label"
        )

        assert _bare(declarations.get("min-width", "<missing>")) in {"0", "0px"}
        assert _bare(declarations.get("overflow-wrap", "<missing>")) in WRAPPING

    def test_premise_the_label_is_the_flexible_item(self) -> None:
        # The label takes the remaining space (`flex: 1`); that is why a long
        # token inside it needs `min-width: 0` to be allowed to shrink.
        assert (
            _bare(
                _declarations_of(
                    MAIN_CSS.read_text(encoding="utf-8"), ".option-item label"
                )["flex"]
            )
            == "1"
        )
        assert (
            _bare(
                _declarations_of(
                    WEBVIEW_CSS.read_text(encoding="utf-8"), ".option-label"
                )["flex"]
            )
            == "1"
        )
