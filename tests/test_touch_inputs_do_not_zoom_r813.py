"""R813: tapping a text field on a phone must not zoom the page.

iOS Safari zooms the page when a text field with a ``font-size`` below 16 px
gets the focus, and does not zoom back out by itself.  The Web UI knows this:
``.feedback-textarea`` is ``1rem`` (16 px) everywhere and carries an explicit
``font-size: 16px`` in both mobile blocks.  Three other controls were missed,
and a real-Chrome measurement at 375 px (``getComputedStyle``) found them:

* the settings panel's text, URL and number fields and its selects
  (``.setting-input`` / ``.setting-select``): ``0.95rem`` = 15.2 px;
* the code-paste dialog's textarea (``.code-paste-textarea``): 13 px.

Both are reached on a phone: the settings panel holds the Bark URL and device
key (the setup that makes the notification open this very page on the phone),
and the code-paste dialog is the "insert code" button next to the feedback box.
So the first tap on the Bark URL field zoomed the settings panel in.

Raising them everywhere would change the desktop look (a 13 px monospace code
area becomes 16 px), so the rule is scoped to where it matters: narrow windows
(``max-width: 768px``, the breakpoint the stylesheet already uses for phones) and
every touch-first device whatever its width (``hover: none`` and ``pointer:
coarse``: an iPad is 1 024 px wide and zooms just the same).

The tests parse ``main.css`` and the page template (no browser in CI):

* a media block with both conditions sets 16 px on the three selectors;
* every text-like control in the template - ``input`` of a text-like type (or
  none), ``textarea`` and ``select`` - carries a class that is covered, so a new
  field cannot be added without its 16 px;
* the control that was already right stays right, and the controls that do
  not zoom (checkbox, range, file, hidden) are not a reason to fail.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
MAIN_CSS = PACKAGE / "static" / "css" / "main.css"
TEMPLATE = PACKAGE / "templates" / "web_ui.html"

ZOOM_FREE_INPUT_TYPES = {
    "checkbox",
    "radio",
    "range",
    "file",
    "hidden",
    "button",
    "submit",
    "reset",
    "image",
    "color",
}


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css: str) -> list[tuple[str, dict[str, str]]]:
    rules: list[tuple[str, dict[str, str]]] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css)):
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


def _media_blocks(css: str) -> list[tuple[str, str]]:
    """``(query, body)`` of every ``@media`` block, nested braces balanced."""
    css = _strip_comments(css)
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(r"@media([^{]*)\{", css):
        depth = 1
        index = match.end()
        while index < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[index], 0)
            index += 1
        blocks.append((" ".join(match.group(1).split()), css[match.end() : index - 1]))
    return blocks


def _px(value: str) -> float:
    value = value.replace("!important", "").strip()
    match = re.match(r"[\d.]+", value)
    assert match is not None, value
    number = float(match.group(0))
    if value.endswith(("rem", "em")):
        return number * 16
    assert value.endswith("px"), value
    return number


def _touch_blocks() -> list[tuple[str, str]]:
    return [
        (query, body)
        for query, body in _media_blocks(MAIN_CSS.read_text(encoding="utf-8"))
        if "max-width: 768px" in query and "pointer: coarse" in query
    ]


def _covered_font_sizes() -> dict[str, float]:
    """Class -> font-size in px that a phone or a touch device gets."""
    covered: dict[str, float] = {}
    for _query, body in _touch_blocks():
        for selector, declarations in _rules(body):
            match = re.fullmatch(r"\.([\w-]+)", selector)
            if match and "font-size" in declarations:
                covered[match.group(1)] = _px(declarations["font-size"])
    return covered


def _text_like_controls() -> list[tuple[str, str, list[str]]]:
    """``(tag, id, classes)`` of every control that makes iOS zoom on focus."""
    html = TEMPLATE.read_text(encoding="utf-8")
    found: list[tuple[str, str, list[str]]] = []
    for match in re.finditer(r"<(input|textarea|select)\b([^>]*)>", html):
        tag, attributes = match.group(1), match.group(2)

        def attribute(name: str, attributes: str = attributes) -> str:
            hit = re.search(rf'\b{name}\s*=\s*"([^"]*)"', attributes)
            return hit.group(1) if hit else ""

        if tag == "input" and attribute("type").lower() in ZOOM_FREE_INPUT_TYPES:
            continue
        found.append((tag, attribute("id"), attribute("class").split()))
    return found


class TestTheTouchBlock:
    def test_a_block_for_narrow_and_for_touch_devices_exists(self) -> None:
        assert _touch_blocks(), (
            "no `@media (max-width: 768px), (hover: none) and (pointer: coarse)` "
            "block: an iPad is wider than 768 px and zooms all the same"
        )

    def test_it_also_asks_for_hover_none(self) -> None:
        # `pointer: coarse` alone is true for some laptops with a touch screen
        # next to a trackpad; `hover: none` makes it "touch is the primary input".
        for query, _body in _touch_blocks():
            assert "hover: none" in query, query

    def test_it_sets_16_px_on_the_three_controls_that_zoomed(self) -> None:
        covered = _covered_font_sizes()

        for name in ("setting-input", "setting-select", "code-paste-textarea"):
            assert covered.get(name, 0) >= 16, (name, covered)


class TestEveryTextFieldIsCovered:
    def test_the_template_has_text_like_controls_to_check(self) -> None:
        # Guards the guard: a template scan that finds nothing passes vacuously.
        controls = _text_like_controls()
        assert len(controls) >= 8
        ids = {identifier for _tag, identifier, _classes in controls}
        assert {"feedback-text", "code-paste-textarea", "bark-url"} <= ids

    def test_each_one_has_a_class_that_is_16_px_on_a_phone(self) -> None:
        covered = _covered_font_sizes()
        # Already 16 px at every width (`font-size: 1rem`) and again in both
        # mobile blocks.
        already_right = {"feedback-textarea"}
        offenders = [
            f"<{tag} id={identifier!r} class={classes!r}>"
            for tag, identifier, classes in _text_like_controls()
            if not any(
                name in already_right or covered.get(name, 0) >= 16 for name in classes
            )
        ]

        assert offenders == [], (
            "these fields would zoom the page on iOS when tapped; add their class "
            f"to the touch block: {offenders}"
        )

    def test_the_control_that_was_already_right_stays_right(self) -> None:
        # Every `.feedback-textarea` rule that sets a size - the base rule and
        # the two mobile overrides - keeps it at 16 px or more.
        css = MAIN_CSS.read_text(encoding="utf-8")
        sizes = [
            _px(declarations["font-size"])
            for selector, declarations in _rules(css)
            if selector == ".feedback-textarea" and "font-size" in declarations
        ]

        assert len(sizes) >= 3
        assert min(sizes) >= 16, sizes

    def test_controls_that_do_not_zoom_are_not_asked_to_be_covered(self) -> None:
        # A checkbox, a range slider or a file picker never opens a text caret.
        listed = [
            identifier
            for _tag, identifier, _classes in _text_like_controls()
            if identifier
            in {"sound-volume", "file-upload-input", "notification-enabled"}
        ]
        assert listed == []
