"""R807: code inside a fenced block does not wear the inline-code border.

``.markdown-content code`` styles *inline* code: a tinted background, a ``1px``
border and a ``6px`` radius.  ``.markdown-content pre code`` is meant to undo
that for fenced blocks, and it reset the background and the padding - but not
the border or the radius.  ``border-top`` / ``border-bottom`` are removed for
every ``code`` by a global ``!important`` rule, so what stayed was a ``1px``
border on the left and the right of every code line, with rounded ends: two
faint brackets inside the block in the dark theme (the light theme has its own
``pre code { border: none !important }``, which is why nobody saw it there).

A theme may only change colours.  A computed-geometry comparison of light and
dark over a Markdown kitchen sink, the tab bar and the settings panel (203 and
390 elements, real Chrome) found differences only in fenced code blocks: dark
drew ``border-left/right-width: 1px`` on ``code``, light drew them on ``pre``
instead.  This fix removes the ``code`` half; the light theme's ``pre`` border
is a separate design question and is not touched.  The VS Code webview already
resets ``pre code`` with ``border: none``.

The tests parse ``main.css`` and ``webview.css`` (no browser in CI), so they
check the declarations that decide the outcome:

* the base block-code rule resets the border and the radius;
* every other rule aimed at block code that mentions a border removes it;
* the premise still holds (inline code *has* a border, so the reset is needed);
* the VS Code webview resets it the same way.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
WEBVIEW_CSS = REPO_ROOT / "packages" / "vscode" / "webview.css"

_BLOCK_CODE_SELECTOR = re.compile(r"(?:\bpre\s+code|\.code-block-container\s+code)$")


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


def _is_no_border(value: str) -> bool:
    return re.fullmatch(r"(?:none|0|0px)(?:\s*!important)?", value.strip()) is not None


class TestBlockCodeResetsInlineCodeChrome:
    def test_the_base_rule_removes_the_border(self) -> None:
        declarations = _declarations_of(
            MAIN_CSS.read_text(encoding="utf-8"), ".markdown-content pre code"
        )

        assert "border" in declarations, (
            "`.markdown-content pre code` must reset the border that "
            "`.markdown-content code` gives inline code"
        )
        assert _is_no_border(declarations["border"]), declarations["border"]

    def test_the_base_rule_removes_the_radius(self) -> None:
        declarations = _declarations_of(
            MAIN_CSS.read_text(encoding="utf-8"), ".markdown-content pre code"
        )

        radius = declarations.get("border-radius", "<missing>")
        assert radius in {"0", "0px"}, (
            f"`.markdown-content pre code` must reset border-radius, got {radius}"
        )

    def test_the_base_rule_still_resets_what_it_always_reset(self) -> None:
        declarations = _declarations_of(
            MAIN_CSS.read_text(encoding="utf-8"), ".markdown-content pre code"
        )

        assert declarations.get("background") == "none"
        assert declarations.get("padding") == "0"

    def test_no_rule_aimed_at_block_code_puts_a_border_back(self) -> None:
        offenders = []
        for selector, declarations in _rules(MAIN_CSS.read_text(encoding="utf-8")):
            if not _BLOCK_CODE_SELECTOR.search(selector):
                continue
            for name, value in declarations.items():
                if (
                    name.startswith("border")
                    and "radius" not in name
                    and not _is_no_border(value)
                ):
                    offenders.append(f"{selector} {{ {name}: {value} }}")
        assert offenders == []

    def test_the_rules_this_test_inspects_exist(self) -> None:
        # Guards the guard: if the selectors are renamed the checks above would
        # pass vacuously.
        selectors = {s for s, _ in _rules(MAIN_CSS.read_text(encoding="utf-8"))}
        assert ".markdown-content pre code" in selectors
        assert ".markdown-content code" in selectors
        assert any(
            _BLOCK_CODE_SELECTOR.search(s)
            for s in selectors - {".markdown-content pre code"}
        )


class TestThePremiseHolds:
    def test_inline_code_has_a_border_and_a_radius(self) -> None:
        # The reset only makes sense because inline code has them.
        declarations = _declarations_of(
            MAIN_CSS.read_text(encoding="utf-8"), ".markdown-content code"
        )

        assert declarations["border"].startswith("1px solid")
        assert declarations["border-radius"] != "0"


class TestTheVsCodeWebviewAgrees:
    def test_the_webview_resets_the_border_of_block_code(self) -> None:
        declarations = _declarations_of(
            WEBVIEW_CSS.read_text(encoding="utf-8"), ".markdown-content pre code"
        )

        assert _is_no_border(declarations["border"])
