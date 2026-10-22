"""R815: the light theme of the Web UI's two dialogs lives in the stylesheet.

The settings panel and the code-paste dialog ("Insert code") are the same
component: both are a ``.settings-panel`` holding a ``.settings-content`` with
a ``.settings-header`` and a ``.settings-body``.  Their light theme was not in
``main.css`` but in a string of ``settings-manager.js``: ``applySettingsTheme()``
built a ``<style id="settings-light-theme-styles">`` with 18 rules and was called
from exactly one place, ``showSettings()``.  So the code-paste dialog was only
light after the settings panel had been opened once since the page loaded.

A real-Chrome pass (computed styles, WCAG contrast, light theme, a fresh page
and the "Insert code" button as the first thing tapped) found the dialog dark
with the dark title of the light theme on it:

======================  ============  ============
                         fresh page   settings opened first
======================  ============  ============
title on header, 1280   1.14 : 1      16.3 : 1
title on header, 375    1.22 : 1      16.3 : 1
hint on dialog, 1280    2.99 : 1      6.66 : 1
hint on dialog, 375     2.16 : 1      6.66 : 1
======================  ============  ============

(axe-core reported the 320 px case as a serious ``color-contrast`` violation.)
The Web UI opens on a phone from the Bark notification, and "Insert code" is
the button next to the feedback box, so this was the first thing many light
theme users saw.

Moving the rules into ``main.css`` is the fix for the cause, not for the
symptom: the dialog is themed from the first paint whichever dialog opens
first, nothing is built at run time, and a third dialog that reuses the classes
cannot repeat the mistake.  Two details keep it equivalent to what the settings
panel looked like (a full computed-style comparison of both dialogs, every
element and every property, old tree after opening the settings against the new
tree on a fresh page, found no difference):

* every declaration is ``!important`` (the base rules and the dark defaults are
  more specific in places) and the block sits at the end of the file, where the
  injected ``<style>`` used to sit in the cascade;
* the selectors are still keyed on ``[data-theme="light"]``, which ``theme.js``
  always sets to ``light`` or ``dark``.

The tests parse ``main.css`` and the scripts (no browser in CI).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "src" / "ai_intervention_agent" / "static"
MAIN_CSS = STATIC / "css" / "main.css"
SETTINGS_JS = STATIC / "js" / "settings-manager.js"

LIGHT = '[data-theme="light"]'

# The 18 selectors the script used to inject (the five-selector list counts five).
INJECTED_SELECTORS = [
    f"{LIGHT} .settings-panel",
    f"{LIGHT} .settings-content",
    f"{LIGHT} .settings-body",
    f"{LIGHT} .setting-group",
    f"{LIGHT} .setting-subgroup",
    f"{LIGHT} .settings-header",
    f"{LIGHT} .status-row",
    f"{LIGHT} .status-row span:first-child",
    f"{LIGHT} .status-row span:last-child",
    f"{LIGHT} .setting-description",
    f"{LIGHT} .setting-item:hover .setting-description",
    f"{LIGHT} .setting-label:hover .setting-title",
    f"{LIGHT} .setting-input::placeholder",
    f"{LIGHT} .setting-label",
    f"{LIGHT} .setting-title",
    f"{LIGHT} .setting-subgroup-title",
    f"{LIGHT} .settings-main-title",
    f"{LIGHT} #settings-title",
    f"{LIGHT} .setting-group::before",
    f"{LIGHT} .setting-input",
    f"{LIGHT} .setting-select",
]


def _rules() -> list[tuple[str, dict[str, str]]]:
    css = re.sub(r"/\*.*?\*/", "", MAIN_CSS.read_text(encoding="utf-8"), flags=re.S)
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


def _declarations_of(selector: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for rule_selector, declarations in _rules():
        if rule_selector == selector:
            merged.update(declarations)
    return merged


def _rgb(value: str) -> tuple[float, float, float]:
    value = value.replace("!important", "").strip().lower()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        red, green, blue = (int(digits[index : index + 2], 16) for index in (0, 2, 4))
        return float(red), float(green), float(blue)
    numbers = re.findall(r"[\d.]+", value)
    assert len(numbers) >= 3, value
    return float(numbers[0]), float(numbers[1]), float(numbers[2])


def _luminance(value: str) -> float:
    def channel(component: float) -> float:
        component /= 255
        if component <= 0.03928:
            return component / 12.92
        return ((component + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(component) for component in _rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


class TestTheLightDialogLivesInTheStylesheet:
    @pytest.mark.parametrize("selector", INJECTED_SELECTORS)
    def test_each_rule_the_script_used_to_inject_is_in_main_css(
        self, selector: str
    ) -> None:
        declarations = _declarations_of(selector)

        assert declarations, selector
        # The base rules are more specific in places; the dialog won with `!important`.
        for name, value in declarations.items():
            assert "!important" in value, (selector, name, value)

    def test_the_surfaces_of_a_dialog_are_light(self) -> None:
        for selector in (
            f"{LIGHT} .settings-content",
            f"{LIGHT} .settings-body",
            f"{LIGHT} .settings-header",
        ):
            background = _declarations_of(selector)["background"]
            assert _luminance(background) >= 0.85, (selector, background)

    def test_the_title_and_the_hint_are_readable_on_those_surfaces(self) -> None:
        # What the dialog's title and hint are painted with in the light theme.
        variables = _declarations_of(LIGHT)
        primary, secondary = variables["--text-primary"], variables["--text-secondary"]
        header = _declarations_of(f"{LIGHT} .settings-header")["background"]
        content = _declarations_of(f"{LIGHT} .settings-content")["background"]

        assert _contrast(primary, header) >= 4.5, (primary, header)
        assert _contrast(secondary, content) >= 4.5, (secondary, content)

    def test_no_later_rule_competes_with_the_block(self) -> None:
        # The injected <style> sat after every stylesheet; with `!important` on
        # both sides, equal specificity is decided by position, so a rule for the
        # same properties of the same components must not come after the block.
        rules = _rules()
        last_block_rule = max(
            index
            for index, (selector, _declarations) in enumerate(rules)
            if selector in INJECTED_SELECTORS
        )
        block_properties = {
            name
            for selector, declarations in rules
            if selector in INJECTED_SELECTORS
            for name in declarations
        }
        dialog_components = re.compile(
            r"\.settings?-[\w-]+|\.status-row|#settings-title"
        )

        competitors = [
            (selector, name)
            for selector, declarations in rules[last_block_rule + 1 :]
            if dialog_components.search(selector)
            for name, value in declarations.items()
            if name in block_properties and "!important" in value
        ]

        assert competitors == [], competitors


class TestNothingBuildsAStylesheetAtRunTime:
    def test_settings_manager_has_no_theme_injector(self) -> None:
        source = SETTINGS_JS.read_text(encoding="utf-8")

        assert "applySettingsTheme" not in source
        assert "settings-light-theme-styles" not in source

    def test_no_first_party_script_creates_a_style_element(self) -> None:
        vendor = re.compile(r"(\.min\.js$|^tex-|^mathjax|^marked\.|^prism)")
        offenders = []
        for script in sorted((STATIC / "js").glob("*.js")):
            if vendor.search(script.name):
                continue
            text = script.read_text(encoding="utf-8")
            if re.search(r"""createElement\(\s*['"]style['"]\s*\)""", text):
                offenders.append(script.name)

        assert offenders == [], (
            "CSS belongs in the stylesheet: a rule built by a script only exists "
            f"after that script ran: {offenders}"
        )
