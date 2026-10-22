"""R818: the options of the VS Code panel are pinned above the composer, scroll, and can be resized.

TODO.md asked for the multi-select options to "allow adjusting the height, be pinned above
the input box and have a scroll bar, so that with a long feedback I can pick them one by one".
In the panel the options lived at the end of the message, inside the scroller that also holds
the message, so a long message with many options meant scrolling back and forth between the
text and the list (twelve options were 624 to 816 px tall at 300 to 480 px wide, more than the
whole message area of a 700 px high panel), and the panel hides every scroll bar
(``* { scrollbar-width: none }``), so even a list that did scroll gave no hint that it did.

The options now sit in a dock between the message scroller and the composer:

* the dock is a flex item that is as tall as its options up to 40 % of the viewport height
  (``max-height: min(var(--aiia-options-height, 40vh), 70vh)``), the options scroll inside it
  with a scroll bar of their own (``scrollbar-width: auto`` and ``scrollbar-color: auto`` so
  that the 8 px ``::-webkit-scrollbar`` is honoured; an inherited ``scrollbar-color`` would turn
  it into an overlay bar that only shows while scrolling);
* a grip on the top edge (a keyboard-operable ``role="separator"``) sets that height: drag it,
  press Up / Down (24 px, 96 px with Shift or Page Up / Page Down), Home / End, Enter or
  double-click to go back to the default; the height is kept in the webview state;
* while the dock is visible the message scroller keeps at least 96 px, so a tall dock cannot
  starve the message, and the form scrolls as a whole when the panel is too short for all
  three parts; a task without options has no dock and lays out exactly as before.

The tests read the template, the stylesheet, ``webview-helpers.js`` and ``webview-ui.js`` (no
browser in CI): where the dock sits in the template and what the grip declares, what the
stylesheet says about the dock, its list, the grip and the scroller, the pure helpers
(clamp, stored value, key map) run in Node, and ``initOptionsResize`` runs in Node against a
small DOM stand-in whose dock height follows the same ``max-height`` model.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
WEBVIEW_CSS = VSCODE_DIR / "webview.css"
WEBVIEW_TS = VSCODE_DIR / "webview.ts"
WEBVIEW_UI_JS = VSCODE_DIR / "webview-ui.js"
WEBVIEW_HELPERS_JS = VSCODE_DIR / "webview-helpers.js"
LOCALES = VSCODE_DIR / "locales"
MIN_HEIGHT_PX = 96

Rule = tuple[str, dict[str, str]]


def _rules() -> list[Rule]:
    css = re.sub(r"/\*.*?\*/", "", WEBVIEW_CSS.read_text(encoding="utf-8"), flags=re.S)
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


RULES = _rules()


def _merged(selector: str) -> dict[str, str]:
    """Every declaration of the rules whose selector is exactly ``selector``, later wins."""
    merged: dict[str, str] = {}
    for rule_selector, declarations in RULES:
        if rule_selector == selector:
            merged.update(declarations)
    assert merged, f"no rule for {selector}"
    return merged


def _has_rule(selector: str) -> bool:
    return any(rule_selector == selector for rule_selector, _ in RULES)


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract {name}()")


def _closing_div(template: str, start: int) -> int:
    """Index just past the ``</div>`` that closes the ``<div`` found at ``start``."""
    depth = 0
    for match in re.finditer(r"<div\b|</div>", template[start:]):
        depth += 1 if match.group(0).startswith("<div") else -1
        if depth == 0:
            return start + match.end()
    raise AssertionError("unbalanced <div> in the template")


def _run_node(script: str) -> str:
    assert shutil.which("node") is not None, "node runtime unavailable"
    completed = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    return completed.stdout


def _template() -> str:
    return WEBVIEW_TS.read_text(encoding="utf-8")


class TestTemplate:
    def test_the_dock_sits_between_the_message_scroller_and_the_composer(self) -> None:
        template = _template()

        scroller = template.index('<div class="scrollable-content">')
        scroller_end = _closing_div(template, scroller)
        dock_id = template.index('id="optionsSection"')
        composer = template.index('<div class="fixed-input-area">')

        assert scroller_end <= dock_id < composer
        assert template.count('id="optionsSection"') == 1
        assert 'class="form-section' not in template

    def test_the_dock_holds_the_grip_the_label_and_the_list(self) -> None:
        template = _template()

        dock_start = template.rindex("<div", 0, template.index('id="optionsSection"'))
        dock = template[dock_start : _closing_div(template, dock_start)]

        assert dock.startswith('<div class="options-dock hidden" id="optionsSection">')
        assert dock.count('id="optionsResizeHandle"') == 1
        assert 'data-i18n="ui.form.optionsLabel"' in dock
        assert '<div class="options-container" id="optionsContainer"></div>' in dock
        assert dock.index("options-resize-handle") < dock.index('id="optionsContainer"')

    def test_the_grip_is_a_keyboard_operable_separator(self) -> None:
        template = _template()
        start = template.index('<div class="options-resize-handle"')
        grip = template[start : template.index("</div>", start)]

        for attribute in (
            'role="separator"',
            'aria-orientation="horizontal"',
            'aria-controls="optionsContainer"',
            'tabindex="0"',
            'data-i18n-aria-label="ui.form.optionsResize"',
            'data-i18n-title="ui.form.optionsResizeHint"',
            'aria-label="${tl("ui.form.optionsResize")}"',
            'title="${tl("ui.form.optionsResizeHint")}"',
        ):
            assert attribute in grip, attribute
        assert " style=" not in grip

    def test_the_grip_texts_exist_in_every_locale_of_the_panel(self) -> None:
        for locale in ("en", "zh-CN", "zh-TW"):
            form = json.loads((LOCALES / f"{locale}.json").read_text("utf-8"))["ui"][
                "form"
            ]
            assert form["optionsResize"].strip(), locale
            assert form["optionsResizeHint"].strip(), locale


class TestStylesheet:
    def test_the_dock_is_as_tall_as_its_options_up_to_a_cap(self) -> None:
        dock = _merged(".options-dock")

        assert dock["flex"] == "0 1 auto"
        assert dock["display"] == "flex"
        assert dock["flex-direction"] == "column"
        assert dock["overflow"] == "hidden"
        assert dock["position"] == "relative"
        assert dock["max-height"] == "min(var(--aiia-options-height, 40vh), 70vh)"
        assert dock["min-height"] == f"{MIN_HEIGHT_PX}px"

    def test_the_dock_keeps_the_chrome_of_the_card_it_replaces(self) -> None:
        dock = _merged(".options-dock")

        assert dock["padding"] == "14px 12px"
        assert dock["background"] == "rgba(255, 255, 255, 0.035)"
        assert dock["border"] == "1px solid rgba(127, 127, 127, 0.15)"
        assert dock["border-radius"] == "6px"
        assert not _has_rule(".form-section")

    def test_the_options_scroll_inside_the_dock_with_a_scroll_bar(self) -> None:
        options = _merged(".options-container")

        assert options["overflow-y"] == "auto"
        assert options["min-height"] == "0"
        assert options["flex"] == "1 1 auto"
        assert options["overscroll-behavior"] == "contain"

        bar = _merged(".options-container::-webkit-scrollbar")
        assert int(bar["width"].removesuffix("px")) >= 6
        assert _merged(".options-container::-webkit-scrollbar-thumb")["background"]

    def test_the_scroll_bar_beats_the_global_one_that_is_switched_off(self) -> None:
        """``* { scrollbar-width: none }`` and an inherited ``scrollbar-color`` both hide it."""
        options = _merged(".options-container")

        assert options["scrollbar-width"] == "auto"
        assert options["scrollbar-color"] == "auto"
        assert _merged("*")["scrollbar-width"] == "none"

    def test_the_grip_is_a_resize_target(self) -> None:
        grip = _merged(".options-resize-handle")

        assert grip["cursor"] == "ns-resize"
        assert grip["touch-action"] == "none"
        assert grip["position"] == "absolute"
        assert grip["top"] == "0"
        assert int(grip["height"].removesuffix("px")) >= 12
        assert _merged(".options-resize-handle:focus-visible")[
            "outline-offset"
        ].startswith("-")

    def test_a_tall_dock_cannot_starve_the_message(self) -> None:
        starved = _merged(
            ".feedback-form:has(> .options-dock:not(.hidden)) > .scrollable-content"
        )

        assert starved["min-height"] == f"{MIN_HEIGHT_PX}px"
        assert "min-height" not in _merged(".scrollable-content")

    def test_the_form_scrolls_when_the_panel_is_too_short_for_everything(self) -> None:
        form = _merged(".feedback-form")

        assert form["overflow-y"] == "auto"
        assert form["overflow-x"] == "hidden"
        assert "overflow" not in form

    def test_the_minimum_matches_the_one_the_script_enforces(self) -> None:
        script = (
            f"const h = require({json.dumps(str(WEBVIEW_HELPERS_JS))});"
            "process.stdout.write(String(h.OPTIONS_HEIGHT_MIN_PX));"
        )

        assert int(_run_node(script)) == MIN_HEIGHT_PX


class TestHelpers:
    @staticmethod
    def _eval(expression: str) -> object:
        script = (
            f"const h = require({json.dumps(str(WEBVIEW_HELPERS_JS))});"
            f"process.stdout.write(JSON.stringify({expression}));"
        )
        return json.loads(_run_node(script))

    def test_clamp_keeps_the_value_inside_the_bounds(self) -> None:
        assert self._eval("h.clampOptionsHeight(200, 96, 400)") == 200
        assert self._eval("h.clampOptionsHeight(10, 96, 400)") == 96
        assert self._eval("h.clampOptionsHeight(900, 96, 400)") == 400
        assert self._eval("h.clampOptionsHeight(200.6, 96, 400)") == 201

    def test_clamp_never_returns_less_than_the_minimum(self) -> None:
        assert self._eval("h.clampOptionsHeight(500, 96, 50)") == 96
        assert self._eval("h.clampOptionsHeight(50, undefined, undefined)") == 96

    def test_clamp_rejects_what_is_not_a_finite_number(self) -> None:
        for value in ("NaN", "Infinity", "'200'", "null", "undefined", "{}"):
            assert self._eval(f"h.clampOptionsHeight({value}, 96, 400)") is None, value

    def test_a_stored_height_is_taken_only_when_it_is_a_sane_number(self) -> None:
        assert self._eval("h.normalizeStoredOptionsHeight(250)") == 250
        assert self._eval("h.normalizeStoredOptionsHeight(250.4)") == 250
        assert self._eval("h.normalizeStoredOptionsHeight(96)") == 96
        assert self._eval("h.normalizeStoredOptionsHeight(1e9)") == 4000
        for value in ("95", "0", "-5", "NaN", "Infinity", "'250'", "null", "undefined"):
            assert self._eval(f"h.normalizeStoredOptionsHeight({value})") is None, value

    def test_the_keys_move_the_height_the_way_a_horizontal_splitter_does(self) -> None:
        def key(name: str, current: int = 200, shift: str = "false") -> object:
            return self._eval(
                f"h.resolveOptionsHeightKey('{name}', {shift}, {current}, 96, 400)"
            )

        assert key("ArrowUp") == {"handled": True, "height": 224}
        assert key("ArrowDown") == {"handled": True, "height": 176}
        assert key("ArrowUp", shift="true") == {"handled": True, "height": 296}
        assert key("ArrowDown", shift="true") == {"handled": True, "height": 104}
        assert key("PageUp") == {"handled": True, "height": 296}
        assert key("PageDown") == {"handled": True, "height": 104}
        assert key("Home") == {"handled": True, "height": 96}
        assert key("End") == {"handled": True, "height": 400}
        assert key("Enter") == {"handled": True, "height": None}

    def test_the_keys_stop_at_the_bounds(self) -> None:
        up = self._eval("h.resolveOptionsHeightKey('ArrowUp', false, 390, 96, 400)")
        down = self._eval("h.resolveOptionsHeightKey('ArrowDown', false, 100, 96, 400)")

        assert up == {"handled": True, "height": 400}
        assert down == {"handled": True, "height": 96}

    def test_other_keys_are_left_alone(self) -> None:
        for name in ("a", "Tab", "Escape", " ", "ArrowLeft", "ArrowRight"):
            result = self._eval(
                f"h.resolveOptionsHeightKey({json.dumps(name)}, false, 200, 96, 400)"
            )
            assert result == {"handled": False, "height": None}, name
        unknown_height = self._eval(
            "h.resolveOptionsHeightKey('ArrowUp', false, NaN, 96, 400)"
        )
        assert unknown_height == {"handled": False, "height": None}


class TestPersistence:
    def test_the_height_is_saved_with_the_rest_of_the_panel_state(self) -> None:
        source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        save = _extract_function(source, "schedulePersistUiState")

        saved = re.search(
            r"optionsManualHeight:\s*typeof optionsManualHeight === 'number'", save
        )
        assert saved is not None, (
            "schedulePersistUiState does not save optionsManualHeight"
        )

    def test_the_saved_height_is_validated_before_it_is_used(self) -> None:
        source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        restore = _extract_function(source, "restorePersistedUiState")

        validated = (
            "optionsManualHeight = WEBVIEW_HELPERS.normalizeStoredOptionsHeight("
            "s.optionsManualHeight)" in restore
        )
        assert validated, "restorePersistedUiState uses the stored height unvalidated"

    def test_the_grip_is_wired_up_with_the_other_listeners(self) -> None:
        source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        setup = _extract_function(source, "setupEventListeners")

        wired = "initOptionsResize()" in setup
        assert wired, "setupEventListeners never calls initOptionsResize()"


def _grip_script(
    body: str, *, initial: str = "null", content: int = 600, observer: bool = True
) -> str:
    source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
    function = _extract_function(source, "initOptionsResize")
    return textwrap.dedent(
        f"""
        const WEBVIEW_HELPERS = require({json.dumps(str(WEBVIEW_HELPERS_JS))});
        let optionsManualHeight = {initial};
        let saves = 0;
        function schedulePersistUiState() {{ saves += 1; }}

        const CHROME = 70, CONTENT = {content}, VIEWPORT = 700;
        const vars = {{}};
        function makeElement() {{
          const listeners = {{}}, attributes = {{}}, classes = new Set();
          const element = {{
            addEventListener(type, handler) {{ (listeners[type] = listeners[type] || []).push(handler); }},
            setAttribute(name, value) {{ attributes[name] = String(value); }},
            getAttribute(name) {{ return name in attributes ? attributes[name] : null; }},
            classList: {{
              add(name) {{ classes.add(name); }},
              remove(name) {{ classes.delete(name); }},
              contains(name) {{ return classes.has(name); }},
            }},
            captured: null,
            setPointerCapture(id) {{ element.captured = id; }},
            releasePointerCapture(id) {{ if (element.captured === id) element.captured = null; }},
            fire(type, event) {{
              const e = Object.assign({{ defaultPrevented: false, preventDefault() {{ e.defaultPrevented = true; }} }}, event);
              for (const handler of listeners[type] || []) handler(e);
              return e;
            }},
            attributes, listeners, classes,
          }};
          return element;
        }}
        function dockHeight() {{
          const wanted = 'aiia' in vars ? vars.aiia : 280;
          const natural = CHROME + CONTENT;
          return Math.max(96, Math.min(natural, wanted, Math.floor(window.innerHeight * 70 / 100)));
        }}
        const dock = makeElement(), handle = makeElement(), list = makeElement();
        dock.style = {{
          setProperty(name, value) {{ if (name === '--aiia-options-height') vars.aiia = parseFloat(value); vars.raw = value; }},
          removeProperty(name) {{ if (name === '--aiia-options-height') {{ delete vars.aiia; vars.raw = ''; }} }},
        }};
        dock.getBoundingClientRect = () => ({{ height: dockHeight() }});
        Object.defineProperty(dock, 'offsetHeight', {{ get: dockHeight }});
        Object.defineProperty(list, 'clientHeight', {{ get: () => Math.max(0, dockHeight() - CHROME) }});
        Object.defineProperty(list, 'scrollHeight', {{ get: () => CONTENT }});
        const elements = {{ optionsSection: dock, optionsResizeHandle: handle, optionsContainer: list }};
        const document = {{ getElementById: id => elements[id] || null }};
        const window = {{ innerHeight: VIEWPORT }};
        const resizeCallbacks = [], observed = [];
        if ({"true" if observer else "false"}) {{
          globalThis.ResizeObserver = class {{
            constructor(callback) {{ resizeCallbacks.push(callback); }}
            observe(element) {{ observed.push(element); }}
          }};
        }}

        {function}

        initOptionsResize();
        const snapshot = () => ({{
          state: optionsManualHeight, raw: vars.raw === undefined ? null : vars.raw, height: dockHeight(), saves,
          now: handle.getAttribute('aria-valuenow'), min: handle.getAttribute('aria-valuemin'), max: handle.getAttribute('aria-valuemax'),
          dragging: handle.classList.contains('is-dragging'), captured: handle.captured,
        }});
        const out = [];
        {textwrap.indent(textwrap.dedent(body), "        ").strip()}
        process.stdout.write(JSON.stringify(out));
        """
    )


class TestGrip:
    def test_dragging_up_makes_the_dock_taller_and_keeps_the_height(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    const down = handle.fire('pointerdown', { button: 0, pointerId: 7, clientY: 400 });
                    out.push({ ...snapshot(), prevented: down.defaultPrevented });
                    handle.fire('pointermove', { pointerId: 7, clientY: 300 });
                    out.push(snapshot());
                    handle.fire('pointerup', { pointerId: 7, clientY: 300 });
                    out.push(snapshot());
                    """
                )
            )
        )

        started, moved, finished = out
        assert started["dragging"] is True and started["captured"] == 7
        assert started["prevented"] is True
        assert (moved["raw"], moved["height"], moved["state"]) == ("380px", 380, 380)
        assert finished["dragging"] is False and finished["captured"] is None
        assert (finished["state"], finished["raw"], finished["now"]) == (
            380,
            "380px",
            "380",
        )
        assert finished["saves"] == 1

    def test_dragging_is_limited_by_the_content_the_viewport_and_the_minimum(
        self,
    ) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 400 });
                    handle.fire('pointermove', { pointerId: 1, clientY: -3000 });
                    out.push(snapshot());
                    handle.fire('pointermove', { pointerId: 1, clientY: 9000 });
                    out.push(snapshot());
                    handle.fire('pointerup', { pointerId: 1, clientY: 9000 });
                    """
                )
            )
        )

        assert (
            out[0]["state"] == 490
        )  # 70 % of a 700 px viewport, below the 670 px of content
        assert out[1]["state"] == MIN_HEIGHT_PX

    def test_the_dock_is_never_taller_than_its_content(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 400 });
                    handle.fire('pointermove', { pointerId: 1, clientY: -3000 });
                    out.push(snapshot());
                    handle.fire('pointerup', { pointerId: 1, clientY: -3000 });
                    """,
                    content=60,
                )
            )
        )

        assert out[0]["state"] == 130  # 70 px of chrome plus 60 px of options

    def test_a_drag_that_changes_nothing_leaves_the_setting_alone(self) -> None:
        """Pushing against the limit, or a plain click, must not store a height."""
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 400 });
                    handle.fire('pointermove', { pointerId: 1, clientY: 100 });
                    handle.fire('pointerup', { pointerId: 1, clientY: 100 });
                    out.push(snapshot());
                    handle.fire('pointerdown', { button: 0, pointerId: 2, clientY: 400 });
                    handle.fire('pointerup', { pointerId: 2, clientY: 400 });
                    out.push(snapshot());
                    """,
                    content=60,
                )
            )
        )

        for snap in out:
            assert snap["state"] is None and snap["raw"] in (None, "")

    def test_a_click_keeps_the_height_that_was_set_before(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 400 });
                    handle.fire('pointerup', { pointerId: 1, clientY: 400 });
                    out.push(snapshot());
                    """,
                    initial="200",
                )
            )
        )

        assert (out[0]["state"], out[0]["raw"], out[0]["height"]) == (200, "200px", 200)

    def test_only_the_primary_button_and_the_capturing_pointer_count(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('pointerdown', { button: 2, pointerId: 1, clientY: 400 });
                    out.push(snapshot());
                    handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 400 });
                    handle.fire('pointermove', { pointerId: 99, clientY: 300 });
                    out.push(snapshot());
                    handle.fire('pointerup', { pointerId: 99, clientY: 300 });
                    out.push(snapshot());
                    handle.fire('pointercancel', { pointerId: 1, clientY: 400 });
                    out.push(snapshot());
                    handle.fire('pointerdown', { button: 0, pointerId: 2, clientY: 400 });
                    handle.fire('lostpointercapture', { pointerId: 2 });
                    out.push(snapshot());
                    """
                )
            )
        )

        assert out[0]["dragging"] is False
        assert out[1]["dragging"] is True and out[1]["state"] is None
        assert out[2]["dragging"] is True
        assert out[3]["dragging"] is False and out[3]["captured"] is None
        assert out[4]["dragging"] is False and out[4]["captured"] is None

    def test_the_keys_resize_reset_and_ignore_what_they_do_not_own(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    const press = (key, shiftKey = false) => handle.fire('keydown', { key, shiftKey });
                    press('ArrowUp'); out.push(snapshot());
                    press('ArrowDown', true); out.push(snapshot());
                    press('Home'); out.push(snapshot());
                    press('End'); out.push(snapshot());
                    const reset = press('Enter'); out.push({ ...snapshot(), prevented: reset.defaultPrevented });
                    const other = press('a'); out.push({ ...snapshot(), prevented: other.defaultPrevented });
                    """
                )
            )
        )

        assert [snap["state"] for snap in out[:4]] == [304, 208, 96, 490]
        assert [snap["now"] for snap in out[:4]] == ["304", "208", "96", "490"]
        assert [snap["saves"] for snap in out[:5]] == [1, 2, 3, 4, 5]
        assert out[4]["state"] is None and out[4]["raw"] == "" and out[4]["prevented"]
        assert out[4]["now"] == "280"
        assert out[5]["prevented"] is False and out[5]["saves"] == 5

    def test_a_key_that_would_not_change_the_height_stores_nothing(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('keydown', { key: 'ArrowUp', shiftKey: false });
                    handle.fire('keydown', { key: 'End', shiftKey: false });
                    out.push(snapshot());
                    """,
                    content=60,
                )
            )
        )

        assert out[0]["state"] is None and out[0]["saves"] == 0

    def test_a_double_click_goes_back_to_the_default(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('keydown', { key: 'ArrowUp', shiftKey: true });
                    out.push(snapshot());
                    const click = handle.fire('dblclick', {});
                    out.push({ ...snapshot(), prevented: click.defaultPrevented });
                    """
                )
            )
        )

        assert out[0]["state"] == 376
        assert out[1]["state"] is None and out[1]["raw"] == "" and out[1]["prevented"]
        assert out[1]["height"] == 280 and out[1]["now"] == "280"
        assert out[1]["saves"] == 2

    def test_the_saved_height_is_applied_when_the_panel_starts(self) -> None:
        out = json.loads(
            _run_node(_grip_script("out.push(snapshot());", initial="200"))
        )

        assert (out[0]["raw"], out[0]["height"], out[0]["state"]) == ("200px", 200, 200)
        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "200", "490")
        assert out[0]["saves"] == 0

    def test_the_separator_reports_its_range_and_value_when_it_gets_focus(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('focus', {});
                    out.push(snapshot());
                    window.innerHeight = 500;
                    handle.fire('focus', {});
                    out.push(snapshot());
                    """
                )
            )
        )

        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "280", "490")
        assert (out[1]["min"], out[1]["now"], out[1]["max"]) == ("96", "280", "350")

    def test_the_range_follows_the_dock_when_its_size_changes(self) -> None:
        """Options appear after the script started, and the panel can be resized."""
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    out.push({ ...snapshot(), observed: observed.length, isDock: observed[0] === dock });
                    window.innerHeight = 500;
                    for (const callback of resizeCallbacks) callback([]);
                    out.push(snapshot());
                    """
                )
            )
        )

        assert out[0]["observed"] == 1 and out[0]["isDock"] is True
        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "280", "490")
        assert (out[1]["min"], out[1]["now"], out[1]["max"]) == ("96", "280", "350")

    def test_a_page_without_resize_observer_still_works(self) -> None:
        out = json.loads(
            _run_node(
                _grip_script(
                    """
                    handle.fire('focus', {});
                    handle.fire('keydown', { key: 'ArrowUp', shiftKey: false });
                    out.push({ ...snapshot(), hasObserver: typeof ResizeObserver !== 'undefined' });
                    """,
                    observer=False,
                )
            )
        )

        assert out[0]["hasObserver"] is False
        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "304", "490")

    def test_a_page_without_the_helpers_or_the_dock_is_left_alone(self) -> None:
        source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
        function = _extract_function(source, "initOptionsResize")
        script = textwrap.dedent(
            f"""
            let optionsManualHeight = null;
            function schedulePersistUiState() {{}}
            const present = {{ optionsSection: {{}}, optionsResizeHandle: {{}}, optionsContainer: {{}} }};
            let elements = present;
            const document = {{ getElementById: id => elements[id] || null }};
            const window = {{ innerHeight: 700 }};
            let WEBVIEW_HELPERS = null;
            {function}
            const results = [];
            initOptionsResize(); results.push('no helpers');
            WEBVIEW_HELPERS = require({json.dumps(str(WEBVIEW_HELPERS_JS))});
            for (const missing of Object.keys(present)) {{
              elements = {{ ...present }};
              delete elements[missing];
              initOptionsResize(); results.push('no ' + missing);
            }}
            WEBVIEW_HELPERS = {{}};
            elements = present;
            initOptionsResize(); results.push('incomplete helpers');
            process.stdout.write(JSON.stringify(results));
            """
        )

        assert json.loads(_run_node(script)) == [
            "no helpers",
            "no optionsSection",
            "no optionsResizeHandle",
            "no optionsContainer",
            "incomplete helpers",
        ]
