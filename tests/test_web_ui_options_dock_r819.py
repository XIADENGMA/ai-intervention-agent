"""R819: the options of the Web UI are pinned to the bottom of the window while you read, scroll, and can be resized.

TODO.md asked for the multi-select options to "allow adjusting the height, be pinned above
the input box and have a scroll bar, so that with a long feedback I can pick them one by one".
The Web UI rendered the options at the end of the message, in the normal flow of one long
page: twelve options were 816 to 996 px tall, so picking them one by one while reading a long
message meant scrolling back and forth between the text and the list (and the options of a
long message started thousands of pixels below the text that explains them).

The options now sit in a tray:

* the tray (``#options-dock``) is ``position: sticky; bottom: 0``, so while the message is on
  screen the options stay at the bottom of the window and when the page reaches their natural
  place they simply sit there, above the separator and the feedback box; sticky positioning
  only works when no ancestor is a scroll container, so ``.container`` clips instead of hides
  (``overflow: clip``, with ``overflow: hidden`` before it for browsers that lack ``clip``) and
  the phone layout's ``.content`` no longer declares ``overflow-y: auto`` (it never scrolled:
  its height followed its content);
* the list is as tall as its options up to 40 % of the window height
  (``max-height: min(var(--aiia-options-height, 40vh), 70vh)``) and scrolls inside the tray with
  a scroll bar of its own, and it needs a frame (background, border, radius) because it now
  overlaps the message;
* a grip on the top edge (a keyboard-operable ``role="separator"``) sets that height: drag it,
  press Up / Down (24 px, 96 px with Shift or Page Up / Page Down), Home / End, Enter or
  double-click to go back to the default; the height is kept in ``localStorage``;
* resizing keeps the top edge of the tray under the pointer: while the tray is pinned it grows
  upwards by itself, in its natural place the page is scrolled by the same amount;
* the focusable elements of the message get ``scroll-margin-bottom`` so that tabbing to a link
  never leaves it hidden behind the tray (a page-wide ``scroll-padding-bottom`` would scroll
  the page whenever the focus moved into the tray itself);
* a task without options has an empty tray: the layout is the one it had before (measured in a
  real browser at ten window sizes and both themes).

The tests read the template, the stylesheet and the script (no browser in CI): where the tray
sits in the template and what the grip declares, what the stylesheet says about the tray, the
list, the grip and the ancestors that must not scroll, and the script runs in Node against a
small DOM stand-in whose list height follows the same ``max-height`` model (pinned or in its
natural place).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src" / "ai_intervention_agent"
STATIC_DIR = PACKAGE_DIR / "static"
MAIN_CSS = STATIC_DIR / "css" / "main.css"
MODULE_JS = STATIC_DIR / "js" / "feedback_options_dock.js"
TEMPLATE = PACKAGE_DIR / "templates" / "web_ui.html"
WEB_UI_PY = PACKAGE_DIR / "web_ui.py"
LOCALES = STATIC_DIR / "locales"
PANEL_HELPERS_JS = REPO_ROOT / "packages" / "vscode" / "webview-helpers.js"

MIN_HEIGHT_PX = 96
STORAGE_KEY = "aiia.feedbackOptionsHeight.v1"
PHONE = "@media (max-width: 768px)"
SMALL_PHONE = "@media (max-width: 480px)"

Rule = tuple[str, str, dict[str, str]]


def _split_selectors(prelude: str) -> list[str]:
    """Split a selector list on the commas that are not inside ``(...)`` or ``[...]``."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in prelude:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [" ".join(part.split()) for part in parts if part.strip()]


def _parse_css(text: str) -> list[Rule]:
    """``(enclosing at-rules, selector, declarations)`` of every style rule, nested ones included."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules: list[Rule] = []
    stack: list[str] = []
    buffer: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "{":
            prelude = " ".join("".join(buffer).split())
            buffer = []
            if prelude.startswith("@"):
                stack.append(prelude)
                index += 1
                continue
            end = text.index("}", index)
            declarations: dict[str, str] = {}
            for declaration in text[index + 1 : end].split(";"):
                name, separator, value = declaration.partition(":")
                if separator:
                    declarations[name.strip().lower()] = " ".join(value.split())
            for selector in _split_selectors(prelude):
                rules.append((" ".join(stack), selector, declarations))
            index = end + 1
            continue
        if char == "}":
            if stack:
                stack.pop()
            buffer = []
        else:
            buffer.append(char)
        index += 1
    return rules


RULES = _parse_css(MAIN_CSS.read_text(encoding="utf-8"))


def _merged(selector: str, context: str = "") -> dict[str, str]:
    """Every declaration of the rules with exactly this selector inside this at-rule, later wins."""
    merged: dict[str, str] = {}
    found = False
    for rule_context, rule_selector, declarations in RULES:
        if rule_selector == selector and rule_context == context:
            merged.update(declarations)
            found = True
    assert found, f"no rule for {selector!r} in {context or 'the top level'}"
    return merged


def _declared_anywhere(selector: str, prefix: str) -> list[tuple[str, str, str]]:
    """``(context, property, value)`` for every declaration of ``selector`` that starts with ``prefix``."""
    return [
        (context, name, value)
        for context, rule_selector, declarations in RULES
        if rule_selector == selector
        for name, value in declarations.items()
        if name.startswith(prefix)
    ]


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
    return TEMPLATE.read_text(encoding="utf-8")


class TestTemplate:
    def test_the_tray_wraps_the_list_and_the_grip_and_precedes_the_separator(
        self,
    ) -> None:
        template = _template()
        start = template.index('<div class="options-dock" id="options-dock">')
        end = _closing_div(template, start)
        dock = template[start:end]

        assert template.count('id="options-dock"') == 1
        assert template.count('id="options-container"') == 1
        assert '<div class="options-container hidden" id="options-container">' in dock
        assert dock.count('id="options-resize-handle"') == 1
        assert dock.index('id="options-container"') < dock.index(
            'id="options-resize-handle"'
        )
        assert end <= template.index('id="separator"')
        assert template.index("skeleton-block") < start

    def test_the_grip_is_a_keyboard_operable_separator(self) -> None:
        template = _template()
        match = re.search(
            r'<div\s+class="options-resize-handle"(?P<attributes>[^>]*)></div>',
            template,
            re.S,
        )
        assert match is not None, "the grip is missing from the template"
        attributes = dict(re.findall(r'([\w-]+)="([^"]*)"', match.group("attributes")))

        assert attributes["role"] == "separator"
        assert attributes["aria-orientation"] == "horizontal"
        assert attributes["aria-controls"] == "options-container"
        assert attributes["tabindex"] == "0"
        assert attributes["id"] == "options-resize-handle"
        assert attributes["data-i18n-aria-label"] == "page.optionsResize"
        assert attributes["data-i18n-title"] == "page.optionsResizeHint"
        assert attributes["aria-label"].strip() and attributes["title"].strip()
        assert "style" not in attributes

    def test_the_script_is_loaded_once_with_a_version_and_the_page_nonce(self) -> None:
        template = _template()
        tags = re.findall(
            r'<script\s+defer\s+src="/static/js/feedback_options_dock\.js\?v=\{\{ feedback_options_dock_version \}\}"\s+nonce="\{\{ csp_nonce \}\}"\s*></script>',
            template,
        )

        assert len(tags) == 1
        assert template.count("feedback_options_dock.js") == 1
        assert "feedback_options_dock_version" in WEB_UI_PY.read_text(encoding="utf-8")
        assert MODULE_JS.is_file()

    def test_the_grip_texts_exist_in_every_locale_of_the_page(self) -> None:
        for locale in ("en", "zh-CN", "zh-TW", "_pseudo/pseudo"):
            page = json.loads((LOCALES / f"{locale}.json").read_text("utf-8"))["page"]
            assert page["optionsResize"].strip(), locale
            assert page["optionsResizeHint"].strip(), locale


class TestStylesheet:
    def test_the_tray_is_pinned_to_the_bottom_of_the_window(self) -> None:
        dock = _merged(".options-dock")

        assert dock["position"] == "sticky"
        assert dock["bottom"] == "0"
        assert 10 < int(dock["z-index"]) < 900  # over the message, under the pop-ups
        assert "display" not in dock, "a flex tray would shrink the list to its content"

    def test_a_flex_layout_does_not_lift_the_tray_by_the_margin_of_the_list(
        self,
    ) -> None:
        """In a flex column the margin of the list stays inside the tray (in block layout it
        collapses through it), so the sticky edge moves down by that margin to keep the list
        itself flush with the window."""
        gap = _merged(".options-container")["margin-bottom"]

        assert gap == "1.25rem"
        assert _merged(".feedback-group", PHONE)["display"] == "flex"
        assert _merged(".options-dock", PHONE)["bottom"] == f"-{gap}"
        assert "display" not in _merged(".feedback-group")

    def test_the_list_is_as_tall_as_its_options_up_to_a_cap_and_scrolls(self) -> None:
        options = _merged(".options-container")

        assert options["max-height"] == "min(var(--aiia-options-height, 40vh), 70vh)"
        assert options["overflow-y"] == "auto"
        assert options["overscroll-behavior"] == "contain"
        assert options["display"] == "flex"
        assert options["flex-direction"] == "column"

    def test_the_list_is_a_framed_card_because_it_overlaps_the_message(self) -> None:
        options = _merged(".options-container")

        assert options["background"] == "var(--bg-secondary)"
        assert options["border"] == "1px solid var(--border-secondary)"
        assert options["border-radius"] == "24px"
        assert options["box-shadow"] == "var(--shadow-md)"
        assert options["padding-bottom"].startswith("calc(0.5rem + env(safe-area-")

    def test_the_list_has_a_scroll_bar_in_both_themes(self) -> None:
        bar = _merged(".options-container::-webkit-scrollbar")
        assert int(bar["width"].removesuffix("px")) >= 6

        dark = _merged(".options-container::-webkit-scrollbar-thumb")["background"]
        light = _merged(
            '[data-theme="light"] .options-container::-webkit-scrollbar-thumb'
        )["background"]
        assert dark and light and dark != light
        assert _merged(".options-container::-webkit-scrollbar-track")["background"] in (
            "transparent",
            "none",
        )

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
        assert _merged(".options-container.hidden + .options-resize-handle") == {
            "display": "none"
        }

    def test_the_tray_works_without_has_and_without_a_script(self) -> None:
        selectors = [
            selector
            for _, selector, _ in RULES
            if "options-dock" in selector
            or "options-resize-handle" in selector
            or "options-container" in selector
        ]

        assert selectors
        assert all(":has(" not in selector for selector in selectors)

    def test_container_clips_instead_of_hiding_so_that_sticky_works(self) -> None:
        css = MAIN_CSS.read_text(encoding="utf-8")

        fallback_then_clip = re.search(
            r"\n\.container \{[^}]*?overflow: hidden;\s*overflow: clip;", css
        )
        assert fallback_then_clip is not None, (
            ".container needs `overflow: hidden; overflow: clip;` in this order"
        )
        for context, name, value in _declared_anywhere(".container", "overflow"):
            assert value in ("hidden", "clip", "visible"), (context, name, value)

    def test_no_ancestor_of_the_tray_is_a_scroll_container(self) -> None:
        """Sticky is relative to the nearest scrolling ancestor: the page has to be it."""
        for selector in (".feedback-group", ".content", "#content-container"):
            for context, name, value in _declared_anywhere(selector, "overflow"):
                assert value in ("visible", "clip"), (selector, context, name, value)
        for context in ("", PHONE, SMALL_PHONE):
            assert "overflow-y" not in _merged(".content", context)
            assert "overflow" not in _merged(".content", context)

    def test_focusable_message_elements_stay_clear_of_the_tray(self) -> None:
        margin = _merged(".description :is(a[href], button, summary, [tabindex])")

        assert margin["scroll-margin-bottom"] == "var(--aiia-options-reserve, 0px)"
        assert not [
            rule
            for rule in RULES
            if "scroll-padding-bottom" in rule[2] or "scroll-padding" in rule[2]
        ], "a page-wide scroll-padding scrolls the page whenever the tray gets focus"

    def test_the_variable_names_match_the_script(self) -> None:
        source = MODULE_JS.read_text(encoding="utf-8")
        css = MAIN_CSS.read_text(encoding="utf-8")

        assert '"--aiia-options-height"' in source
        assert '"--aiia-options-reserve"' in source
        assert css.count("var(--aiia-options-height, 40vh)") == 1
        assert css.count("var(--aiia-options-reserve, 0px)") == 1

    def test_the_stylesheet_declares_the_defaults_of_the_variables_the_script_writes(
        self,
    ) -> None:
        """A custom property that only a script sets is a typo waiting to happen (see
        ``TestCSSVariableReferenceIntegrity``): ``:root`` declares both, with the value the
        ``var()`` fallbacks use, so a page the script has not touched looks the same."""
        defaults = _merged(":root")
        css = MAIN_CSS.read_text(encoding="utf-8")

        assert defaults["--aiia-options-height"] == "40vh"
        assert defaults["--aiia-options-reserve"] == "0px"
        for name in ("--aiia-options-height", "--aiia-options-reserve"):
            assert f"var({name}, {defaults[name]})" in css

    def test_the_minimum_matches_the_one_the_panel_enforces(self) -> None:
        script = (
            f"const h = require({json.dumps(str(PANEL_HELPERS_JS))});"
            "process.stdout.write(String(h.OPTIONS_HEIGHT_MIN_PX));"
        )

        assert int(_run_node(script)) == MIN_HEIGHT_PX
        assert f"const MIN_HEIGHT_PX = {MIN_HEIGHT_PX};" in MODULE_JS.read_text(
            encoding="utf-8"
        )


HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const config = __CONFIG__;
const STORAGE_KEY = __STORAGE_KEY__;
const out = [];
const rootProps = new Map();
const storage = new Map();
if (config.stored !== null) storage.set(STORAGE_KEY, config.stored);
const scrollCalls = [];
const winListeners = {};
const win = {
  innerHeight: config.innerHeight,
  scrollY: config.scrollY,
  addEventListener(type, fn) { (winListeners[type] = winListeners[type] || []).push(fn); },
  removeEventListener(type, fn) { winListeners[type] = (winListeners[type] || []).filter((f) => f !== fn); },
  scrollBy(x, y) { scrollCalls.push([x, y]); win.scrollY += y; },
};
if (config.noScrollBy) delete win.scrollBy;
const state = { hidden: config.listHidden, content: config.content };
const NATURAL_TOP = 1500;
const cap = () => {
  const raw = rootProps.get('--aiia-options-height');
  const px = raw === undefined ? 0.4 * win.innerHeight : parseFloat(raw);
  return Math.min(px, 0.7 * win.innerHeight);
};
const renderedHeight = () => (state.hidden ? 0 : Math.min(state.content + 2, cap()));
const list = {
  id: 'options-container',
  get offsetHeight() { return Math.round(renderedHeight()); },
  get clientHeight() { return state.hidden ? 0 : Math.round(renderedHeight()) - 2; },
  get scrollHeight() { return state.hidden ? 0 : state.content; },
  getBoundingClientRect() {
    const height = renderedHeight();
    const top = config.mode === 'stuck' ? win.innerHeight - height : NATURAL_TOP - win.scrollY;
    return { top, height, bottom: top + height };
  },
};
const handleListeners = {};
const handleAttrs = {};
const handleClasses = new Set();
let captured = null;
const handle = {
  id: 'options-resize-handle',
  addEventListener(type, fn) { (handleListeners[type] = handleListeners[type] || []).push(fn); },
  removeEventListener(type, fn) { handleListeners[type] = (handleListeners[type] || []).filter((f) => f !== fn); },
  setAttribute(name, value) { handleAttrs[name] = String(value); },
  getAttribute(name) { return name in handleAttrs ? handleAttrs[name] : null; },
  classList: {
    add(name) { handleClasses.add(name); },
    remove(name) { handleClasses.delete(name); },
    contains(name) { return handleClasses.has(name); },
  },
  setPointerCapture(id) { captured = id; },
  releasePointerCapture(id) { if (captured !== id) throw new Error('not captured'); captured = null; },
  fire(type, event) {
    const e = { type, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...event };
    for (const fn of [...(handleListeners[type] || [])]) fn(e);
    return e;
  },
};
const root = {
  style: {
    setProperty(name, value) { rootProps.set(name, value); },
    removeProperty(name) { rootProps.delete(name); },
    getPropertyValue(name) { return rootProps.has(name) ? rootProps.get(name) : ''; },
  },
};
const present = { 'options-container': list, 'options-resize-handle': handle };
const doc = {
  readyState: config.readyState,
  documentElement: root,
  getElementById(id) { return present[id] || null; },
  addEventListener(type, fn) { (doc.listeners[type] = doc.listeners[type] || []).push(fn); },
  listeners: {},
};
const observers = [];
class FakeResizeObserver {
  constructor(callback) { this.callback = callback; this.targets = []; this.disconnected = false; observers.push(this); }
  observe(target) { this.targets.push(target); }
  disconnect() { this.disconnected = true; }
}
const localStorage = {
  getItem(key) { if (config.throwsOnGet) throw new Error('denied'); return storage.has(key) ? storage.get(key) : null; },
  setItem(key, value) { if (config.throwsOnSet) throw new Error('quota'); storage.set(key, String(value)); },
  removeItem(key) { if (config.throwsOnSet) throw new Error('denied'); storage.delete(key); },
};
const sandbox = { window: win, document: doc, localStorage, Date, Math, JSON, Number, Object, String, Array, Error };
if (config.observer) sandbox.ResizeObserver = FakeResizeObserver;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__MODULE__, 'utf8'), sandbox, { filename: 'feedback_options_dock.js' });
const dock = win.AIIA_FEEDBACK_OPTIONS_DOCK;
const snapshot = () => {
  const raw = storage.has(STORAGE_KEY) ? storage.get(STORAGE_KEY) : null;
  let stored = null;
  try { stored = raw === null ? null : JSON.parse(raw).height_px; } catch (e) { stored = 'unparseable'; }
  const rect = list.getBoundingClientRect();
  return {
    raw: rootProps.has('--aiia-options-height') ? rootProps.get('--aiia-options-height') : null,
    height: Math.round(rect.height),
    top: rect.top,
    scrollY: win.scrollY,
    min: handle.getAttribute('aria-valuemin'),
    now: handle.getAttribute('aria-valuenow'),
    max: handle.getAttribute('aria-valuemax'),
    reserve: rootProps.has('--aiia-options-reserve') ? rootProps.get('--aiia-options-reserve') : null,
    stored,
    storedRaw: raw,
    dragging: handle.classList.contains('is-dragging'),
    captured,
    scrolls: scrollCalls.length,
  };
};
const press = (key, shiftKey = false) => handle.fire('keydown', { key, shiftKey });
__BODY__
process.stdout.write(JSON.stringify(out));
"""

DEFAULTS: dict[str, object] = {
    "stored": None,
    "content": 1000,
    "mode": "stuck",
    "observer": True,
    "innerHeight": 800,
    "scrollY": 500,
    "listHidden": False,
    "throwsOnGet": False,
    "throwsOnSet": False,
    "readyState": "complete",
    "noScrollBy": False,
}


def _dock_script(body: str, **overrides: object) -> str:
    config = {**DEFAULTS, **overrides}
    return (
        HARNESS.replace("__CONFIG__", json.dumps(config))
        .replace("__STORAGE_KEY__", json.dumps(STORAGE_KEY))
        .replace("__MODULE__", json.dumps(str(MODULE_JS)))
        .replace("__BODY__", body)
    )


def _run_dock(body: str, **overrides: object) -> list[dict[str, Any]]:
    return json.loads(_run_node(_dock_script(body, **overrides)))


class TestHelpersMatchThePanel:
    """The panel (R818) and the page share one behaviour; only the glue differs."""

    def test_clamp_stored_value_and_key_map_agree_with_the_panel_helpers(self) -> None:
        body = f"""
        const panel = require({json.dumps(str(PANEL_HELPERS_JS))});
        const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
        const values = [NaN, Infinity, -Infinity, -5, 0, 1, 95, 96, 96.4, 200, 200.6, 4000, 4001, 1e9, '200', null, undefined, {{}}, [], true];
        const mismatches = [];
        let checked = 0;
        for (const a of values) {{
          if (!same(dock.normalizeStoredHeight(a), panel.normalizeStoredOptionsHeight(a))) mismatches.push(['stored', a]);
          for (const b of values) for (const c of values) {{
            checked += 1;
            if (!same(dock.clampHeight(a, b, c), panel.clampOptionsHeight(a, b, c))) mismatches.push(['clamp', a, b, c]);
          }}
        }}
        const keys = ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', 'Enter', 'a', 'Tab', ' ', 'ArrowLeft'];
        for (const key of keys) for (const shift of [true, false]) for (const current of [NaN, 96, 200, 560, 'x', null])
          for (const min of [96, undefined, NaN, 0]) for (const max of [400, undefined, 50, 560]) {{
            checked += 1;
            if (!same(dock.resolveKey(key, shift, current, min, max), panel.resolveOptionsHeightKey(key, shift, current, min, max))) mismatches.push(['key', key, shift, current, min, max]);
          }}
        out.push({{ mismatches: mismatches.slice(0, 5), checked, constants: [dock.MIN_HEIGHT_PX, panel.OPTIONS_HEIGHT_MIN_PX, dock.MAX_STORED_HEIGHT_PX] }});
        """

        result = _run_dock(body)[0]

        assert result["mismatches"] == []
        assert result["checked"] > 8000
        assert result["constants"] == [96, 96, 4000]


class TestKeysAndPersistence:
    def test_the_keys_resize_reset_and_ignore_what_they_do_not_own(self) -> None:
        out = _run_dock(
            """
            press('ArrowUp'); out.push(snapshot());
            press('ArrowDown', true); out.push(snapshot());
            press('Home'); out.push(snapshot());
            press('End'); out.push(snapshot());
            const reset = press('Enter'); out.push({ ...snapshot(), prevented: reset.defaultPrevented });
            const other = press('a'); out.push({ ...snapshot(), prevented: other.defaultPrevented });
            """
        )

        assert [snap["height"] for snap in out[:4]] == [344, 248, 96, 560]
        assert [snap["now"] for snap in out[:4]] == ["344", "248", "96", "560"]
        assert [snap["stored"] for snap in out[:4]] == [344, 248, 96, 560]
        assert out[4]["raw"] is None and out[4]["stored"] is None
        assert out[4]["storedRaw"] is None and out[4]["prevented"] is True
        assert out[4]["height"] == 320 and out[4]["now"] == "320"
        assert out[5]["prevented"] is False and out[5]["stored"] is None

    def test_a_key_that_would_not_change_the_height_stores_nothing(self) -> None:
        out = _run_dock(
            """
            press('ArrowUp');
            press('End');
            out.push(snapshot());
            """,
            content=60,
        )

        assert out[0]["raw"] is None and out[0]["stored"] is None

    def test_a_list_shorter_than_the_minimum_never_remembers_a_height_it_cannot_show(
        self,
    ) -> None:
        """One option on a phone is about 92 px tall: the keys ask for 96 and nothing moves."""
        stored = json.dumps({"schema_version": 1, "height_px": 300, "saved_at": 1})
        out = _run_dock(
            """
            for (const key of ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End']) {
              press(key);
              out.push({ key, ...snapshot() });
            }
            """,
            content=50,
            stored=stored,
        )

        for snap in out:
            assert snap["raw"] == "300px", snap["key"]
            assert snap["stored"] == 300, snap["key"]
            assert snap["height"] == 52, snap["key"]
            assert (snap["min"], snap["max"]) == ("96", "96"), snap["key"]

    def test_a_key_at_a_limit_stores_nothing(self) -> None:
        out = _run_dock(
            """
            press('End'); out.push(snapshot());
            press('ArrowUp'); out.push(snapshot());
            press('Home'); out.push(snapshot());
            press('ArrowDown'); out.push(snapshot());
            """
        )

        assert [snap["stored"] for snap in out] == [560, 560, 96, 96]
        assert [snap["height"] for snap in out] == [560, 560, 96, 96]

    def test_only_a_usable_height_is_written_to_storage(self) -> None:
        out = _run_dock(
            """
            const results = {};
            results.tiny = dock.persistHeight(50);
            results.tinyStored = storage.has(STORAGE_KEY);
            results.huge = dock.persistHeight(99999);
            results.hugeStored = JSON.parse(storage.get(STORAGE_KEY)).height_px;
            results.fraction = dock.persistHeight(200.4);
            results.fractionStored = JSON.parse(storage.get(STORAGE_KEY)).height_px;
            results.text = dock.persistHeight('200');
            results.textStored = JSON.parse(storage.get(STORAGE_KEY)).height_px;
            results.nothing = dock.persistHeight(null);
            results.nothingStored = storage.has(STORAGE_KEY);
            out.push(results);
            """
        )

        assert out[0] == {
            "tiny": False,
            "tinyStored": False,
            "huge": True,
            "hugeStored": 4000,
            "fraction": True,
            "fractionStored": 200,
            "text": False,
            "textStored": 200,
            "nothing": True,
            "nothingStored": False,
        }

    def test_a_double_click_goes_back_to_the_default_and_forgets_the_height(
        self,
    ) -> None:
        out = _run_dock(
            """
            press('ArrowUp', true);
            out.push(snapshot());
            const click = handle.fire('dblclick', {});
            out.push({ ...snapshot(), prevented: click.defaultPrevented });
            """
        )

        assert out[0]["height"] == 416 and out[0]["stored"] == 416
        assert out[1]["raw"] is None and out[1]["storedRaw"] is None
        assert out[1]["height"] == 320 and out[1]["now"] == "320"
        assert out[1]["prevented"] is True

    def test_the_stored_height_is_written_with_a_schema_version_and_a_time(
        self,
    ) -> None:
        out = _run_dock("press('ArrowUp'); out.push(snapshot());")

        saved = json.loads(str(out[0]["storedRaw"]))
        assert saved["schema_version"] == 1
        assert saved["height_px"] == 344
        assert isinstance(saved["saved_at"], int) and saved["saved_at"] > 1_600_000_000

    def test_the_saved_height_is_applied_when_the_page_starts(self) -> None:
        stored = json.dumps({"schema_version": 1, "height_px": 200, "saved_at": 1})
        out = _run_dock("out.push(snapshot());", stored=stored)

        assert (out[0]["raw"], out[0]["height"]) == ("200px", 200)
        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "200", "560")
        assert out[0]["scrolls"] == 0

    def test_a_saved_height_that_is_not_usable_is_ignored(self) -> None:
        unusable = [
            "{not json",
            "null",
            "[]",
            '"200"',
            json.dumps({"schema_version": 2, "height_px": 200}),
            json.dumps({"height_px": 200}),
            json.dumps({"schema_version": 1, "height_px": "200"}),
            json.dumps({"schema_version": 1, "height_px": 50}),
            json.dumps({"schema_version": 1, "height_px": None}),
            json.dumps({"schema_version": 1}),
            "",
        ]

        for stored in unusable:
            out = _run_dock("out.push(snapshot());", stored=stored)

            assert out[0]["raw"] is None, stored
            assert out[0]["height"] == 320, stored

    def test_an_absurd_saved_height_is_capped_by_the_window(self) -> None:
        stored = json.dumps({"schema_version": 1, "height_px": 99999})
        out = _run_dock("out.push(snapshot());", stored=stored)

        assert out[0]["raw"] == "4000px"
        assert (out[0]["height"], out[0]["now"], out[0]["max"]) == (560, "560", "560")

    def test_storage_that_refuses_to_work_does_not_break_the_tray(self) -> None:
        out = _run_dock(
            """
            press('ArrowUp');
            out.push(snapshot());
            handle.fire('dblclick', {});
            out.push(snapshot());
            """,
            throwsOnGet=True,
            throwsOnSet=True,
        )

        assert out[0]["height"] == 344 and out[0]["raw"] == "344px"
        assert out[1]["height"] == 320 and out[1]["raw"] is None


class TestPointer:
    def test_a_pinned_tray_grows_upwards_without_scrolling_the_page(self) -> None:
        out = _run_dock(
            """
            const start = snapshot();
            const down = handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 700 });
            out.push({ ...snapshot(), prevented: down.defaultPrevented });
            handle.fire('pointermove', { pointerId: 1, clientY: 600 });
            out.push(snapshot());
            handle.fire('pointerup', { pointerId: 1, clientY: 600 });
            out.push(snapshot());
            out.push(start);
            """
        )
        during_start, moved, released, start = out

        assert during_start["dragging"] is True and during_start["captured"] == 1
        assert during_start["prevented"] is True, (
            "pressing the grip must not select text"
        )
        assert (moved["height"], moved["raw"], moved["scrolls"]) == (420, "420px", 0)
        assert moved["top"] == start["top"] - 100
        assert released["dragging"] is False and released["captured"] is None
        assert released["stored"] == 420
        assert (released["min"], released["now"], released["max"]) == (
            "96",
            "420",
            "560",
        )
        assert released["reserve"] == "436px"

    def test_a_tray_in_its_natural_place_scrolls_the_page_so_the_top_edge_follows(
        self,
    ) -> None:
        out = _run_dock(
            """
            const start = snapshot();
            handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 700 });
            handle.fire('pointermove', { pointerId: 1, clientY: 600 });
            out.push({ ...snapshot(), calls: scrollCalls.slice() });
            handle.fire('pointermove', { pointerId: 1, clientY: 660 });
            out.push({ ...snapshot(), calls: scrollCalls.slice() });
            handle.fire('pointerup', { pointerId: 1, clientY: 660 });
            out.push(start);
            """,
            mode="natural",
            scrollY=900,
        )
        grown, shrunk, start = out

        assert grown["calls"] == [[0, 100]]
        assert grown["top"] == start["top"] - 100 and grown["height"] == 420
        assert shrunk["calls"] == [[0, 100], [0, -60]]
        assert shrunk["top"] == start["top"] - 40 and shrunk["height"] == 360
        assert shrunk["scrollY"] == 940

    def test_the_page_is_scrolled_by_whole_pixels_when_the_default_is_fractional(
        self,
    ) -> None:
        """40vh of an 812 px window is 324.8 px; the page must not be asked to scroll by 100.2."""
        out = _run_dock(
            """
            handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 700 });
            handle.fire('pointermove', { pointerId: 1, clientY: 600 });
            out.push({ ...snapshot(), calls: scrollCalls.slice() });
            """,
            mode="natural",
            innerHeight=812,
            scrollY=900,
        )

        assert out[0]["calls"] == [[0, 100]]
        assert out[0]["height"] == 425

    def test_a_page_that_cannot_scroll_still_resizes(self) -> None:
        out = _run_dock(
            """
            handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 700 });
            handle.fire('pointermove', { pointerId: 1, clientY: 600 });
            handle.fire('pointerup', { pointerId: 1, clientY: 600 });
            out.push({ ...snapshot(), hasScrollBy: typeof win.scrollBy });
            """,
            mode="natural",
            noScrollBy=True,
        )

        assert out[0]["hasScrollBy"] == "undefined"
        assert out[0]["height"] == 420 and out[0]["stored"] == 420

    def test_the_height_stays_between_the_minimum_and_what_fits_the_window(
        self,
    ) -> None:
        out = _run_dock(
            """
            handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 700 });
            handle.fire('pointermove', { pointerId: 1, clientY: -3000 });
            out.push(snapshot());
            handle.fire('pointermove', { pointerId: 1, clientY: 9000 });
            out.push(snapshot());
            handle.fire('pointerup', { pointerId: 1, clientY: 9000 });
            out.push(snapshot());
            """
        )

        assert out[0]["height"] == 560 and out[0]["raw"] == "560px"
        assert out[1]["height"] == 96 and out[1]["raw"] == "96px"
        assert out[2]["stored"] == 96

    def test_the_tray_never_grows_beyond_what_its_options_need(self) -> None:
        out = _run_dock(
            """
            out.push(snapshot());
            handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 700 });
            handle.fire('pointermove', { pointerId: 1, clientY: 100 });
            handle.fire('pointerup', { pointerId: 1, clientY: 100 });
            out.push(snapshot());
            """,
            content=150,
        )

        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "152", "152")
        assert out[1]["raw"] is None and out[1]["stored"] is None
        assert out[1]["height"] == 152

    def test_a_drag_that_changes_nothing_leaves_the_setting_alone(self) -> None:
        out = _run_dock(
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

        for snap in out:
            assert snap["raw"] is None and snap["storedRaw"] is None

    def test_a_click_keeps_the_height_that_was_set_before(self) -> None:
        stored = json.dumps({"schema_version": 1, "height_px": 200, "saved_at": 1})
        out = _run_dock(
            """
            handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 400 });
            handle.fire('pointerup', { pointerId: 1, clientY: 400 });
            out.push(snapshot());
            """,
            stored=stored,
        )

        assert (out[0]["raw"], out[0]["height"], out[0]["stored"]) == (
            "200px",
            200,
            200,
        )

    def test_only_the_primary_button_and_the_capturing_pointer_count(self) -> None:
        out = _run_dock(
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

        assert out[0]["dragging"] is False
        assert out[1]["dragging"] is True and out[1]["raw"] is None
        assert out[2]["dragging"] is True
        assert out[3]["dragging"] is False and out[3]["captured"] is None
        assert out[4]["dragging"] is False and out[4]["captured"] is None

    def test_a_released_pointer_that_was_never_captured_does_not_throw(self) -> None:
        out = _run_dock(
            """
            handle.fire('pointerdown', { button: 0, pointerId: 1, clientY: 400 });
            const element = handle;
            element.releasePointerCapture = () => { throw new Error('gone'); };
            handle.fire('pointerup', { pointerId: 1, clientY: 400 });
            out.push(snapshot());
            """
        )

        assert out[0]["dragging"] is False


class TestRangeAndReserve:
    def test_the_separator_reports_its_range_and_value_when_it_gets_focus(self) -> None:
        out = _run_dock(
            """
            handle.fire('focus', {});
            out.push(snapshot());
            win.innerHeight = 500;
            handle.fire('focus', {});
            out.push(snapshot());
            """
        )

        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "320", "560")
        assert (out[1]["min"], out[1]["now"], out[1]["max"]) == ("96", "200", "350")

    def test_the_range_follows_the_window_and_the_list(self) -> None:
        out = _run_dock(
            """
            out.push({ ...snapshot(), observed: observers.length, target: observers[0].targets[0] === list });
            win.innerHeight = 500;
            for (const fn of winListeners.resize) fn();
            out.push(snapshot());
            win.innerHeight = 800;
            state.content = 150;
            observers[0].callback([]);
            out.push(snapshot());
            """
        )

        assert out[0]["observed"] == 1 and out[0]["target"] is True
        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "320", "560")
        assert (out[1]["min"], out[1]["now"], out[1]["max"]) == ("96", "200", "350")
        assert (out[2]["min"], out[2]["now"], out[2]["max"]) == ("96", "152", "152")

    def test_the_page_keeps_clear_of_the_tray_by_its_height_plus_a_margin(self) -> None:
        out = _run_dock(
            """
            out.push(snapshot());
            state.hidden = true;
            observers[0].callback([]);
            out.push(snapshot());
            state.hidden = false;
            state.content = 150;
            observers[0].callback([]);
            out.push(snapshot());
            """
        )

        assert [snap["reserve"] for snap in out] == ["336px", "0px", "168px"]

    def test_a_hidden_list_reserves_nothing(self) -> None:
        out = _run_dock("out.push(snapshot());", listHidden=True)

        assert out[0]["reserve"] == "0px"
        assert out[0]["min"] == "96"

    def test_a_page_without_resize_observer_still_works(self) -> None:
        out = _run_dock(
            """
            handle.fire('focus', {});
            press('ArrowUp');
            out.push({ ...snapshot(), hasObserver: typeof ResizeObserver !== 'undefined' });
            """,
            observer=False,
        )

        assert out[0]["hasObserver"] is False
        assert (out[0]["min"], out[0]["now"], out[0]["max"]) == ("96", "344", "560")


class TestLifecycle:
    def test_calling_init_again_replaces_the_listeners_instead_of_adding_to_them(
        self,
    ) -> None:
        out = _run_dock(
            """
            const count = () => ({
              pointerdown: (handleListeners.pointerdown || []).length,
              keydown: (handleListeners.keydown || []).length,
              focus: (handleListeners.focus || []).length,
              resize: (winListeners.resize || []).length,
              live: observers.filter((o) => !o.disconnected).length,
              total: observers.length,
            });
            out.push(count());
            const second = dock.init();
            const third = dock.init();
            out.push({ ...count(), same: second === third, hasDestroy: typeof third.destroy === 'function' });
            third.destroy();
            out.push(count());
            press('ArrowUp');
            out.push(snapshot());
            """
        )

        assert out[0] == {
            "pointerdown": 1,
            "keydown": 1,
            "focus": 1,
            "resize": 1,
            "live": 1,
            "total": 1,
        }
        assert out[1]["pointerdown"] == out[1]["keydown"] == out[1]["resize"] == 1
        assert out[1]["live"] == 1 and out[1]["total"] == 3
        assert out[1]["same"] is False and out[1]["hasDestroy"] is True
        assert out[2]["pointerdown"] == out[2]["keydown"] == out[2]["focus"] == 0
        assert out[2]["resize"] == 0 and out[2]["live"] == 0
        assert out[3]["raw"] is None, "a destroyed binding must not react to keys"

    def test_a_page_without_the_list_or_the_grip_is_left_alone(self) -> None:
        out = _run_dock(
            """
            const results = [];
            for (const missing of ['options-container', 'options-resize-handle']) {
              const saved = present[missing];
              delete present[missing];
              results.push(dock.init());
              present[missing] = saved;
            }
            out.push({
              results,
              listeners: (handleListeners.pointerdown || []).length,
              resize: (winListeners.resize || []).length,
              live: observers.filter((o) => !o.disconnected).length,
            });
            """
        )

        assert out[0]["results"] == [None, None]
        assert out[0]["listeners"] == 0 and out[0]["resize"] == 0
        assert out[0]["live"] == 0

    def test_the_script_waits_for_the_document_when_it_is_still_loading(self) -> None:
        out = _run_dock(
            """
            out.push({
              ready: doc.listeners.DOMContentLoaded ? doc.listeners.DOMContentLoaded.length : 0,
              bound: (handleListeners.pointerdown || []).length,
              raw: rootProps.has('--aiia-options-height'),
            });
            doc.listeners.DOMContentLoaded[0]();
            out.push({ bound: (handleListeners.pointerdown || []).length });
            """,
            readyState="loading",
            stored=json.dumps({"schema_version": 1, "height_px": 200}),
        )

        assert out[0] == {"ready": 1, "bound": 0, "raw": False}
        assert out[1] == {"bound": 1}

    def test_the_public_surface_is_small_and_stable(self) -> None:
        out = _run_dock(
            "out.push({ keys: Object.keys(dock).sort(), key: dock.STORAGE_KEY, schema: dock.SCHEMA_VERSION });"
        )

        assert out[0]["keys"] == sorted(
            [
                "HEIGHT_VAR",
                "MAX_STORED_HEIGHT_PX",
                "MIN_HEIGHT_PX",
                "RESERVE_VAR",
                "SCHEMA_VERSION",
                "STORAGE_KEY",
                "clampHeight",
                "init",
                "normalizeStoredHeight",
                "persistHeight",
                "readPersistedHeight",
                "resolveKey",
            ]
        )
        assert out[0]["key"] == STORAGE_KEY and out[0]["schema"] == 1


class TestSource:
    def test_the_script_uses_none_of_the_observers_the_page_bans(self) -> None:
        source = MODULE_JS.read_text(encoding="utf-8")

        for banned in (
            "MutationObserver",
            "IntersectionObserver",
            "PerformanceObserver",
            "innerHTML",
            "eval(",
            "document.write",
            "console.",
        ):
            assert banned not in source, banned

    def test_the_script_leaves_no_global_but_its_own(self) -> None:
        source = MODULE_JS.read_text(encoding="utf-8")

        assert source.startswith("(function () {")
        assert source.rstrip().endswith("})();")
        assert re.findall(r"^window\.(\w+) =", source, re.M) == []
        assert re.findall(r"\n  window\.(AIIA_\w+) =", source) == [
            "AIIA_FEEDBACK_OPTIONS_DOCK"
        ]
