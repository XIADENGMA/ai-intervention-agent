"""R814: a keyboard user can see where the focus is on a code block and on the volume slider.

The page draws its keyboard focus ring in one place: ``:focus-visible`` inside
``@layer a11y`` (``outline: 2px solid var(--focus-ring-color)``).  A layered
rule loses to any unlayered rule, so a control that sets its own ``outline``
has to bring its own ring.  A real-Chrome pass over the page with trusted Tab
presses (every focus stop's computed ``outline`` / ``box-shadow``, 5 states, two
themes, desktop and 375 px) found two stops with none:

* **a fenced code block.**  Prism gives every ``<pre>`` ``tabindex="0"`` so that
  its scrolled content can be reached with the arrow keys, which is what makes it
  a focus stop, and ``.markdown-content pre { outline: none !important; box-shadow:
  none !important }`` (the rule that keeps the block clean) took the ring away:
  Tab landed there and nothing showed where;
* **the volume slider** of the settings panel: ``.volume-slider { outline: none }``
  with no ``:focus-visible`` counterpart, in both themes.

Two details decide whether a fix works:

* the code block's rule is ``!important``, and between two ``!important``
  declarations the more specific selector wins, so the ring rule needs to be
  ``!important`` *and* more specific than every rule that removes the outline of
  a ``pre``;
* the block sits in ``.code-block-container`` which is ``overflow: hidden`` with
  rounded corners, so an *outset* ring would be cut off; the ring is drawn
  *inside* the block (a negative ``outline-offset``).

The tests parse ``main.css`` (no browser in CI).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"


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


def _specificity(selector: str) -> tuple[int, int, int]:
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+", selector))
    types = len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", selector))
    return ids, classes, types


def _declarations_of(selector: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for rule_selector, declarations in _rules(MAIN_CSS.read_text(encoding="utf-8")):
        if rule_selector == selector:
            merged.update(declarations)
    return merged


def _px(value: str) -> float:
    number = re.match(r"-?[\d.]+", value.replace("!important", "").strip())
    assert number is not None, value
    return float(number.group(0))


def _is_visible_ring(value: str) -> bool:
    return (
        re.match(r"(?:[2-9]|\d{2,})px\s+(?:solid|dashed|double)\b", value) is not None
    )


def _removes_outline(declarations: dict[str, str]) -> bool:
    outline = declarations.get("outline", "")
    return outline.startswith(("none", "0")) and "!important" in outline


def _rules_that_remove_the_outline_of_a_pre() -> list[tuple[str, dict[str, str]]]:
    return [
        (selector, declarations)
        for selector, declarations in _rules(MAIN_CSS.read_text(encoding="utf-8"))
        if _removes_outline(declarations) and re.search(r"(?:^|\s)pre$", selector)
    ]


class TestACodeBlockShowsWhereTheKeyboardFocusIs:
    def test_premise_a_rule_removes_the_outline_of_a_pre_with_important(self) -> None:
        # Guards the guard: this is the rule the ring has to beat.  If it is
        # ever removed the next tests are still right, but they are no longer
        # needed and this one says so.
        assert _rules_that_remove_the_outline_of_a_pre()

    def test_premise_the_block_is_a_focus_stop_that_the_container_clips(self) -> None:
        prism = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "prism.js"
        ).read_text(encoding="utf-8")
        assert "tabindex" in prism
        container = _declarations_of(".code-block-container")
        assert container.get("overflow") == "hidden"

    def test_a_focused_pre_has_a_visible_ring(self) -> None:
        declarations = _declarations_of(".markdown-content pre:focus-visible")

        outline = declarations.get("outline", "<missing>")
        assert _is_visible_ring(outline), outline
        assert "!important" in outline

    def test_the_ring_is_drawn_inside_the_block(self) -> None:
        # `.code-block-container` is `overflow: hidden`: an outset ring is cut off.
        declarations = _declarations_of(".markdown-content pre:focus-visible")

        offset = declarations.get("outline-offset", "<missing>").replace(
            "!important", ""
        )
        assert offset.strip().startswith("-"), offset

    def test_the_ring_beats_every_rule_that_removes_the_outline_of_a_pre(self) -> None:
        ring = ".markdown-content pre:focus-visible"
        assert "!important" in _declarations_of(ring).get("outline", "")
        for selector, _declarations in _rules_that_remove_the_outline_of_a_pre():
            assert _specificity(ring) > _specificity(selector), (ring, selector)

    def test_the_ring_uses_the_colour_of_every_other_focus_ring(self) -> None:
        outline = _declarations_of(".markdown-content pre:focus-visible")["outline"]

        assert "var(--focus-ring-color" in outline


class TestTheVolumeSliderShowsWhereTheKeyboardFocusIs:
    def test_premise_the_slider_removes_its_own_outline(self) -> None:
        assert _declarations_of(".volume-slider").get("outline") == "none"

    def test_a_focused_slider_has_a_visible_ring(self) -> None:
        declarations = _declarations_of(".volume-slider:focus-visible")

        assert _is_visible_ring(declarations.get("outline", "<missing>")), declarations

    def test_the_slider_ring_clears_the_thumb(self) -> None:
        # The slider's box is 6 px high and its thumb 16 px: the thumb sticks
        # out 5 px above and below the box, and a ring closer than that would
        # run through the thumb instead of around it.
        track = _px(_declarations_of(".volume-slider")["height"])
        thumb = _px(_declarations_of(".volume-slider::-webkit-slider-thumb")["height"])
        offset = _px(_declarations_of(".volume-slider:focus-visible")["outline-offset"])

        assert offset >= (thumb - track) / 2, (offset, thumb, track)

    def test_the_slider_ring_outranks_the_slider_rule_and_uses_the_common_colour(
        self,
    ) -> None:
        # The layered `:focus-visible` rule loses to the unlayered
        # `.volume-slider { outline: none }`; this rule is unlayered and has one
        # more pseudo-class than that.
        ring = ".volume-slider:focus-visible"
        assert _specificity(ring) > _specificity(".volume-slider")
        assert "var(--focus-ring-color" in _declarations_of(ring)["outline"]
