"""R816: links and inline code of the agent's message are readable and findable.

The message card is the one place of the Web UI (and of the VS Code panel) where text the
page does not control is drawn: the agent's Markdown.  A real-Chrome pass (axe-core 4.14 and
computed styles, composited backgrounds, both themes, 1 280 px and 375 px, a sample with a
link and an inline code span in a paragraph, a list item, a block quote, a table header, a
table cell and a heading) found two defects in it.

**Contrast** (WCAG 1.4.3, 4.5 : 1 for text of this size), on the plain card and on the worst
surface (a table header), measured in Chrome 153 on a desktop card:

====================  ========================  ========================
 text                  before (card / worst)     after (card / worst)
====================  ========================  ========================
 link, light           3.35 / 2.99               5.53 / 4.93
 link, dark            4.00 / 3.22               5.90 / 4.76
 inline code, light    2.76 / 2.76               5.53 / 5.53
 inline code, dark     2.52 / 2.06               5.90 / 4.82
====================  ========================  ========================

The light inline code colour was a trap: ``[data-theme="light"] code`` carries
``color: var(--accent-primary) !important`` (the brand orange, 2.76 : 1 on the card), so the
darker ``#c7442a`` that ``[data-theme="light"] .markdown-content code`` declares never won.
Both now say the same colour.  The dark link colour and the dark inline code colour are tints
of the brand orange and of the code red picked so that they pass on *every* surface a link or
a code span can sit on, measured, not only on the plain card: a table header is the lightest
dark surface (``#4a403b`` behind a link, ``#605753`` behind a code span on a desktop card), and
the first candidates, ``#e8957a`` and ``#ffb4ae``, reached only 4.32 : 1 and 4.15 : 1 there.
In the dark theme the phone layout paints the same chain on a darker card, so its ratios are
higher (5.7 : 1 and up) and the light theme is identical on both; the desktop card is the
case the tests composite.

**Colour alone** (WCAG 1.4.1): links had ``text-decoration: none`` and an underline only on
hover, so inside a sentence the only cue was the colour, 2.87 : 1 away from the text colour in
the dark theme (technique G183 asks for 3 : 1 when colour is the only cue).  Making a link
readable on its background moves it *towards* the text colour (light 4.86 -> 2.95 : 1, dark
2.87 -> 1.94 : 1), so an underline at rest stopped being optional; both stylesheets now draw
one.

The tests read the stylesheets (no browser in CI) and composite the surfaces from the
stylesheet's own values, in the order the page stacks them (``body``, ``.container``,
``.description``, ``table``, ``th`` / ``blockquote`` / ``code``), so a lighter tint or a new
surface fails here instead of silently eroding the contrast.  Code *blocks* keep their own
colours (their rules are more specific and ``!important``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
WEBVIEW_CSS = REPO_ROOT / "packages" / "vscode" / "webview.css"

LIGHT = '[data-theme="light"]'
AA = 4.5

Rule = tuple[str, dict[str, str]]
RGB = tuple[int, int, int]


def _rules(path: Path) -> list[Rule]:
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    rules: list[Rule] = []
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


MAIN = _rules(MAIN_CSS)
WEBVIEW = _rules(WEBVIEW_CSS)


def _value(rules: list[Rule], selector: str, prop: str) -> str:
    """The value the FIRST rule that declares ``prop`` for exactly ``selector`` gives it.

    First, not last: the later rules of a selector are the phone overrides.
    """
    for rule_selector, declarations in rules:
        if rule_selector == selector and prop in declarations:
            return declarations[prop]
    raise AssertionError(f"no rule declares {prop} for {selector}")


def _resolve(value: str, variables: dict[str, str]) -> str:
    value = value.replace("!important", "").strip()
    match = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)", value)
    if not match:
        return value
    name, fallback = match.groups()
    if name in variables:
        return _resolve(variables[name], variables)
    assert fallback is not None, f"{name} is not defined"
    return _resolve(fallback, variables)


def _variables(rules: list[Rule], selector: str) -> dict[str, str]:
    for rule_selector, declarations in rules:
        if rule_selector == selector:
            return {k: v for k, v in declarations.items() if k.startswith("--")}
    raise AssertionError(selector)


def _rgba(value: str) -> tuple[int, int, int, float]:
    value = value.strip().lower()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        red, green, blue = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
        return red, green, blue, 1.0
    numbers = [float(n) for n in re.findall(r"[\d.]+", value)]
    assert len(numbers) in (3, 4), value
    alpha = numbers[3] if len(numbers) == 4 else 1.0
    return int(numbers[0]), int(numbers[1]), int(numbers[2]), alpha


def _over(top: tuple[int, int, int, float], below: RGB) -> RGB:
    """Composite like the browser: one 8-bit rounding per layer."""
    red, green, blue, alpha = top
    return (
        round(red * alpha + below[0] * (1 - alpha)),
        round(green * alpha + below[1] * (1 - alpha)),
        round(blue * alpha + below[2] * (1 - alpha)),
    )


def _luminance(rgb: RGB) -> float:
    def channel(component: int) -> float:
        value = component / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(component) for component in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: RGB, background: RGB) -> float:
    first, second = _luminance(foreground), _luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def _opaque(value: str) -> RGB:
    red, green, blue, alpha = _rgba(value)
    assert alpha == 1.0, value
    return red, green, blue


def _dark_surfaces() -> tuple[dict[str, RGB], tuple[int, int, int, float]]:
    """The surfaces behind a link / a code span on a desktop card, and the code background."""
    root = _variables(MAIN, ":root")

    def layer(selector: str, prop: str = "background") -> tuple[int, int, int, float]:
        return _rgba(_resolve(_value(MAIN, selector, prop), root))

    page = _opaque(_resolve(_value(MAIN, "body", "background"), root))
    card = _over(layer(".description"), _over(layer(".container"), page))
    cell = _over(layer(".markdown-content table"), card)
    surfaces = {
        "paragraph": card,
        "block quote": _over(layer(".markdown-content blockquote"), card),
        "table cell": cell,
        "table header": _over(layer(".markdown-content th"), cell),
    }
    return surfaces, layer(".markdown-content code")


def _light_surfaces() -> tuple[dict[str, RGB], RGB]:
    root = _variables(MAIN, LIGHT)

    def resolved(selector: str, prop: str = "background") -> str:
        return _resolve(_value(MAIN, selector, prop), root)

    card = _opaque(resolved(f"{LIGHT} .markdown-content"))
    cell = _over(
        _rgba(_resolve(_value(MAIN, ".markdown-content table", "background"), {})), card
    )
    surfaces = {
        "paragraph": card,
        "block quote": _opaque(resolved(f"{LIGHT} .markdown-content blockquote")),
        "table cell": cell,
        "table header": _over(_rgba(resolved(f"{LIGHT} .markdown-content th")), cell),
    }
    return surfaces, _opaque(resolved(f"{LIGHT} code"))


DARK_SURFACES, DARK_CODE_BACKGROUND = _dark_surfaces()
LIGHT_SURFACES, LIGHT_CODE_BACKGROUND = _light_surfaces()

# The rules that colour an inline code span in the light theme (the first one is `!important`
# and wins; the second used to disagree with it, which is how the brand orange survived).
LIGHT_INLINE_CODE_SELECTORS = (f"{LIGHT} code", f"{LIGHT} .markdown-content code")


def _link_colour(theme: str) -> RGB:
    if theme == "dark":
        return _opaque(_value(MAIN, ".markdown-content a", "color"))
    root = _variables(MAIN, LIGHT)
    return _opaque(
        _resolve(_value(MAIN, f"{LIGHT} .markdown-content a", "color"), root)
    )


def _specificity(selector: str) -> tuple[int, int, int]:
    ids = selector.count("#")
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+", selector))
    elements = len(re.findall(r"(?:^|[\s>+~])[a-z][\w-]*", selector))
    return ids, classes, elements


class TestLinksAreNotToldApartByColourAlone:
    @pytest.mark.parametrize(
        ("name", "rules", "selector"),
        [
            ("web ui", MAIN, ".markdown-content a"),
            ("vs code panel", WEBVIEW, ".markdown-content a"),
        ],
    )
    def test_a_link_is_underlined_at_rest(
        self, name: str, rules: list[Rule], selector: str
    ) -> None:
        decoration = _value(rules, selector, "text-decoration")

        assert "underline" in decoration.split(), (name, decoration)

    @pytest.mark.parametrize(
        ("name", "rules"), [("web ui", MAIN), ("vs code panel", WEBVIEW)]
    )
    def test_no_rule_takes_the_underline_away_at_rest(
        self, name: str, rules: list[Rule]
    ) -> None:
        offenders = []
        for selector, declarations in rules:
            if not re.search(r"\.markdown-content[^,]*\sa(?![\w-])", selector):
                continue
            if re.search(r":(hover|focus|active)", selector):
                continue
            for prop in ("text-decoration", "text-decoration-line"):
                if (
                    declarations.get(prop, "").replace("!important", "").strip()
                    == "none"
                ):
                    offenders.append((selector, prop))

        assert offenders == [], (name, offenders)


class TestLinkColourIsReadableOnEverySurface:
    @pytest.mark.parametrize("surface", list(DARK_SURFACES))
    def test_dark_theme(self, surface: str) -> None:
        ratio = _contrast(_link_colour("dark"), DARK_SURFACES[surface])

        assert ratio >= AA, (surface, DARK_SURFACES[surface], round(ratio, 2))

    @pytest.mark.parametrize("surface", list(LIGHT_SURFACES))
    def test_light_theme(self, surface: str) -> None:
        ratio = _contrast(_link_colour("light"), LIGHT_SURFACES[surface])

        assert ratio >= AA, (surface, LIGHT_SURFACES[surface], round(ratio, 2))


class TestInlineCodeColourIsReadableOnItsOwnBackground:
    @pytest.mark.parametrize("surface", list(DARK_SURFACES))
    def test_dark_theme(self, surface: str) -> None:
        colour = _opaque(_value(MAIN, ".markdown-content code", "color"))
        background = _over(DARK_CODE_BACKGROUND, DARK_SURFACES[surface])

        ratio = _contrast(colour, background)

        assert ratio >= AA, (surface, background, round(ratio, 2))

    @pytest.mark.parametrize("selector", LIGHT_INLINE_CODE_SELECTORS)
    def test_light_theme_every_rule_that_colours_a_code_span(
        self, selector: str
    ) -> None:
        root = _variables(MAIN, LIGHT)
        colour = _opaque(_resolve(_value(MAIN, selector, "color"), root))

        ratio = _contrast(colour, LIGHT_CODE_BACKGROUND)

        assert ratio >= AA, (selector, colour, round(ratio, 2))

    def test_the_two_light_rules_agree(self) -> None:
        root = _variables(MAIN, LIGHT)
        colours = {
            selector: _resolve(_value(MAIN, selector, "color"), root).lower()
            for selector in LIGHT_INLINE_CODE_SELECTORS
        }

        assert len(set(colours.values())) == 1, colours


class TestCodeBlocksKeepTheirOwnColours:
    def test_the_light_block_rule_outranks_the_inline_rule(self) -> None:
        block = f"{LIGHT} .markdown-content pre code"
        inline = f"{LIGHT} code"

        assert "!important" in _value(MAIN, block, "color")
        assert "!important" in _value(MAIN, inline, "color")
        assert _specificity(block) > _specificity(inline)

    def test_block_colours_are_not_the_inline_ones(self) -> None:
        dark_block = _value(MAIN, ".markdown-content pre code", "color")
        light_block = _value(MAIN, f"{LIGHT} .markdown-content pre code", "color")

        assert dark_block.lower() == "#f5f5f7"
        assert light_block.replace("!important", "").strip().lower() == "#141413"
