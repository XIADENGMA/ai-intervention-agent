"""R901: the options tray can be unpinned, so the list goes back to the end of the message.

TODO "界面优化 1".  R818 (the VS Code panel) and R819 (the Web UI) pinned the multi-select options above the
input box so that a long message and its options could be read and answered without scrolling back and forth.
That is the default, and it is the right one for a long message, but a reader of a short message with a few
options, or someone who simply does not want a tray covering part of the text, wants the options where they were
before: at the end of the message.

Both surfaces now have a pin button in the top strip of the tray (the Web UI) or in the head row of the dock
(the panel), a toggle with ``aria-pressed``.  Pinned is the default and the layout of R818 / R819, unchanged.
Unpinned:

* the Web UI tray stops being sticky and sits in the page flow after the message, unframed, as tall as its
  options, with no grip (``.options-dock.is-unpinned``); the page no longer keeps anything clear of it;
* the panel moves the dock into the message scroller, after the message (``.options-dock.is-unpinned`` as well),
  as tall as its options, with no grip, and the toggle moves it back to its place between the scroller and the
  input box; focus stays on the button across the move (a moved node loses focus);
* the choice is remembered: ``localStorage`` in the Web UI (only "unpinned" is stored, pinned is the default),
  the webview state in the panel; unpinning never touches the height the reader set with the grip, so pinning
  again gives the same tray back;
* a task without options shows neither the button nor an empty strip, pinned or not.

The checks: the template and stylesheet of both surfaces (what the button declares, how much room it has, that the
unpinned rules outrank the pinned ones they undo, including the phone layout that lowers the sticky edge), the
real ``feedback_options_dock.js`` in Node against a small DOM, the real ``initOptionsPin`` /
``restorePersistedUiState`` / ``schedulePersistUiState`` of the panel in Node against a DOM that models moving a node
and losing focus, and the strings.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
STATIC = PACKAGE / "static"
WEB_TEMPLATE = PACKAGE / "templates" / "web_ui.html"
WEB_CSS = STATIC / "css" / "main.css"
WEB_JS = STATIC / "js" / "feedback_options_dock.js"
WEB_LOCALES = STATIC / "locales"
VSCODE = REPO_ROOT / "packages" / "vscode"
PANEL_TS = VSCODE / "webview.ts"
PANEL_CSS = VSCODE / "webview.css"
PANEL_UI_JS = VSCODE / "webview-ui.js"
PANEL_HELPERS_JS = VSCODE / "webview-helpers.js"
PANEL_LOCALES = VSCODE / "locales"
PANEL_KEYS = VSCODE / "i18n-keys.d.ts"

HEIGHT_KEY = "aiia.feedbackOptionsHeight.v1"
PIN_KEY = "aiia.feedbackOptionsPinned.v1"
PHONE = "@media (max-width: 768px)"
LOCALES = ["en", "zh-CN", "zh-TW", "_pseudo/pseudo"]
CJK = re.compile(r"[\u4e00-\u9fff]")
# The pin of the two buttons is one drawing; if one surface is edited the other has to follow.
PIN_PATH = (
    "M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 "
    "4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"
)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

Rule = tuple[str, str, dict[str, str]]


# --------------------------------------------------------------------------------------------- CSS helpers
def _split_selectors(prelude: str) -> list[str]:
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
    """``(enclosing at-rules, selector, declarations)`` for every style rule, nested ones included."""
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


WEB_RULES = _parse_css(WEB_CSS.read_text(encoding="utf-8"))
PANEL_RULES = _parse_css(PANEL_CSS.read_text(encoding="utf-8"))


def _merged(rules: list[Rule], selector: str, context: str = "") -> dict[str, str]:
    """Every declaration of the rules with exactly this selector inside this at-rule, later wins."""
    merged: dict[str, str] = {}
    found = False
    for rule_context, rule_selector, declarations in rules:
        if rule_selector == selector and rule_context == context:
            merged.update(declarations)
            found = True
    assert found, f"no rule for {selector!r} in {context or 'the top level'}"
    return merged


def _specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes + attributes + pseudo-classes, elements) of a compound selector without ``:is()`` & co."""
    bare = re.sub(r"\[[^\]]*\]", "[]", selector)
    ids = len(re.findall(r"#[\w-]+", bare))
    classes = len(re.findall(r"\.[\w-]+|\[\]|(?<!:):(?!:)[\w-]+", bare))
    elements = len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", bare))
    return ids, classes, elements


# A shorthand in an unpinned rule undoes the longhands of the rule it overrides.
LONGHANDS = {
    "overflow": ("overflow", "overflow-x", "overflow-y"),
    "margin": ("margin", "margin-top", "margin-right", "margin-bottom", "margin-left"),
    "padding": (
        "padding",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
    ),
    "flex": ("flex", "flex-grow", "flex-shrink", "flex-basis"),
    "border": ("border", "border-width", "border-style", "border-color"),
    "background": ("background", "background-color", "background-image"),
}


def _undone(rules: list[Rule]) -> list[tuple[str, str, str]]:
    """``(unpinned selector, the selector of the rule it undoes, property)`` read out of the stylesheet.

    An unpinned rule undoes a rule of the same element (``.options-dock.is-unpinned`` -> ``.options-dock``, ``... .options-container``
    -> ``.options-container``) in any at-rule, wherever the two declare the property with different values.
    """
    pairs: list[tuple[str, str, str]] = []
    for _, selector, declarations in rules:
        if ".is-unpinned" not in selector:
            continue
        subject = selector.split()[-1].replace(".is-unpinned", "")
        for _, other, other_declarations in rules:
            if other != subject:
                continue
            for name, value in declarations.items():
                for covered in LONGHANDS.get(name, (name,)):
                    if (
                        covered in other_declarations
                        and other_declarations[covered] != value
                    ):
                        pairs.append((selector, other, covered))
    return pairs


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    """WCAG 2.1 contrast ratio of two ``#rrggbb`` colours."""
    lighter, darker = sorted(
        (_luminance(foreground), _luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def _rem(value: str) -> float:
    match = re.fullmatch(r"(-?[\d.]+)rem", value.strip())
    assert match, f"not a rem length: {value!r}"
    return float(match.group(1))


def _first_padding(declarations: dict[str, str]) -> str:
    return declarations["padding"].split()[0]


# ---------------------------------------------------------------------------------------- template helpers
def _closing(template: str, start: int, tag: str = "div") -> int:
    depth = 0
    for match in re.finditer(rf"<{tag}\b|</{tag}>", template[start:]):
        depth += -1 if match.group(0).startswith("</") else 1
        if depth == 0:
            return start + match.end()
    raise AssertionError(f"unbalanced <{tag}> in the template")


def _attributes(tag_source: str) -> dict[str, str]:
    return dict(re.findall(r'([\w:-]+)="([^"]*)"', tag_source))


def _web_dock() -> str:
    template = WEB_TEMPLATE.read_text(encoding="utf-8")
    start = template.index('<div class="options-dock" id="options-dock">')
    return template[start : _closing(template, start)]


def _web_button() -> tuple[dict[str, str], str]:
    dock = _web_dock()
    start = dock.index("<button")
    end = dock.index("</button>", start) + len("</button>")
    source = dock[start:end]
    return _attributes(source[: source.index(">")]), source


def _panel_dock() -> str:
    template = PANEL_TS.read_text(encoding="utf-8")
    start = template.rindex("<div", 0, template.index('id="optionsSection"'))
    return template[start : _closing(template, start)]


def _panel_button() -> tuple[dict[str, str], str]:
    """The template literal has ``${tl("key")}`` inside attribute values: read it as ``TL(key)``."""
    dock = _panel_dock()
    start = dock.index("<button")
    end = dock.index("</button>", start) + len("</button>")
    source = re.sub(r'\$\{tl\("([^"]+)"\)\}', r"TL(\1)", dock[start:end])
    return _attributes(source[: source.index(">")]), source


def _locale(path: Path, *keys: str) -> dict[str, str]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    for key in keys:
        data = data[key]
    return data


def _run_node(script: str) -> str:
    completed = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    return completed.stdout


# ============================================================================================ the Web UI
class TestWebTemplate:
    def test_the_button_is_the_last_child_of_the_tray_after_the_list_and_the_grip(
        self,
    ) -> None:
        dock = _web_dock()

        assert dock.count("<button") == 1
        assert dock.count('id="options-pin-btn"') == 1
        assert (
            dock.index('id="options-container"')
            < dock.index('id="options-resize-handle"')
            < dock.index('id="options-pin-btn"')
        ), (
            "the stylesheet hides the grip with `+` and the button with `~`, both need the list first"
        )
        template = WEB_TEMPLATE.read_text(encoding="utf-8")
        assert template.count('id="options-pin-btn"') == 1
        assert template.count('class="options-pin-btn"') == 1

    def test_the_button_is_a_labelled_toggle_that_starts_pinned(self) -> None:
        attributes, source = _web_button()

        assert attributes["type"] == "button", "a bare <button> would submit a form"
        assert attributes["aria-pressed"] == "true"
        assert attributes["class"] == "options-pin-btn"
        assert attributes["data-i18n-aria-label"] == "page.optionsPin"
        assert attributes["data-i18n-title"] == "page.optionsPinHint"
        assert attributes["aria-label"].strip() and attributes["title"].strip()
        assert "style" not in attributes and "onclick" not in attributes
        assert 'aria-hidden="true"' in source and 'focusable="false"' in source, (
            "the icon must stay out of the accessible name"
        )
        assert PIN_PATH in source

    def test_the_english_fallbacks_are_the_english_texts(self) -> None:
        attributes, _ = _web_button()
        page = _locale(WEB_LOCALES / "en.json", "page")

        assert attributes["aria-label"] == page["optionsPin"]
        assert attributes["title"] == page["optionsPinHint"]

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_texts_exist_in_every_locale_of_the_page(self, locale: str) -> None:
        page = _locale(WEB_LOCALES / f"{locale}.json", "page")

        assert page["optionsPin"].strip(), locale
        assert page["optionsPinHint"].strip(), locale
        assert page["optionsPin"] != page["optionsPinHint"]

    def test_the_label_stays_the_same_in_both_states(self) -> None:
        """A toggle is named for what it does, the state is ``aria-pressed``: the script must not rename it."""
        source = WEB_JS.read_text(encoding="utf-8")

        assert "aria-label" not in source
        assert '"title"' not in source


class TestWebStylesheet:
    def test_the_button_sits_in_a_strip_the_list_pads_for_it(self) -> None:
        button = _merged(WEB_RULES, ".options-pin-btn")
        pinned = _merged(WEB_RULES, ".options-container")
        unpinned = _merged(WEB_RULES, ".options-dock.is-unpinned .options-container")

        bottom_of_button = _rem(button["top"]) + _rem(button["height"])
        assert button["position"] == "absolute"
        assert _rem(_first_padding(pinned)) >= bottom_of_button, (
            "the first option would start under the button"
        )
        assert _first_padding(unpinned) == _first_padding(pinned), (
            "the strip must be the same height pinned and unpinned"
        )
        assert _rem(_first_padding(unpinned)) >= bottom_of_button

    def test_the_button_and_its_hit_area_stay_clear_of_the_scroll_bar(self) -> None:
        button = _merged(WEB_RULES, ".options-pin-btn")
        bar = _merged(WEB_RULES, ".options-container::-webkit-scrollbar")
        hit_area = _merged(WEB_RULES, ".options-pin-btn::after")

        # the bar is 8 px wide and sits inside the 1 px border of the framed list
        bar_reach_rem = (int(bar["width"].removesuffix("px")) + 1) / 16
        hit_area_reach_rem = _rem(button["right"]) + _rem(
            hit_area["inset"]
        )  # inset is negative
        assert _rem(hit_area["inset"]) < 0
        assert hit_area_reach_rem >= bar_reach_rem, (
            "the enlarged hit area of the button would overlap the scroll bar"
        )

    def test_the_button_is_a_big_enough_target(self) -> None:
        button = _merged(WEB_RULES, ".options-pin-btn")

        assert _rem(button["width"]) >= 1.5 and _rem(button["height"]) >= 1.5
        assert button["cursor"] == "pointer"
        assert button["z-index"] and int(button["z-index"]) > 1, (
            "it has to be above the grip (z-index 1) that spans the strip"
        )

    def test_the_button_is_hidden_with_the_list_so_no_empty_tray_shows_it(self) -> None:
        hidden = _merged(WEB_RULES, ".options-container.hidden ~ .options-pin-btn")

        assert hidden == {"display": "none"}

    def test_a_pressed_button_is_filled_and_an_unpressed_one_is_tilted(self) -> None:
        pressed = _merged(
            WEB_RULES, '.options-pin-btn[aria-pressed="true"] .options-pin-icon'
        )
        unpressed = _merged(
            WEB_RULES, '.options-pin-btn[aria-pressed="false"] .options-pin-icon'
        )

        assert pressed == {"fill": "currentColor"}
        assert unpressed == {"transform": "rotate(45deg)"}
        assert _merged(WEB_RULES, '.options-pin-btn[aria-pressed="true"]')["color"]

    def test_the_unpinned_tray_is_part_of_the_page_flow_after_the_message(self) -> None:
        tray = _merged(WEB_RULES, ".options-dock.is-unpinned")

        assert tray["position"] == "relative"
        assert tray["bottom"] == "auto"
        assert tray["z-index"] == "auto"
        assert "top" not in tray and "display" not in tray

    def test_the_unpinned_rules_outrank_every_rule_they_undo_including_the_phone_one(
        self,
    ) -> None:
        """The phone layout lowers the sticky edge (``bottom: -1.25rem``) inside a media query; the unpinned tray must
        reset it, so its selector has to be heavier than the one of every rule it undoes, not just come later."""
        pairs = _undone(WEB_RULES)

        assert {(other, name) for _, other, name in pairs} >= {
            (".options-dock", "position"),
            (".options-dock", "bottom"),
            (".options-dock", "z-index"),
            (".options-container", "max-height"),
            (".options-container", "overflow-y"),
            (".options-container", "padding"),
            (".options-container", "padding-bottom"),
            (".options-container", "background"),
            (".options-container", "border"),
            (".options-container", "border-radius"),
            (".options-container", "box-shadow"),
            (".options-resize-handle", "display"),
        }, "the unpinned rules no longer undo what the pinned tray sets"
        assert _merged(WEB_RULES, ".options-dock", PHONE)["bottom"].startswith("-"), (
            "the phone rule that lowers the sticky edge is gone: this test is about it"
        )
        for selector, other, name in pairs:
            assert _specificity(selector) > _specificity(other), (selector, other, name)

    def test_the_button_is_as_visible_as_a_control_must_be_in_every_theme_and_state(
        self,
    ) -> None:
        """WCAG 1.4.11: 3:1 against what is behind it. ``--text-tertiary`` is reserved for struck-through text (R257),
        and the brand orange (``--primary-500``) is 2.96:1 on the light tray, so the pressed pin is ``--primary-600``."""
        rest = _merged(WEB_RULES, ".options-pin-btn")["color"]
        pressed = _merged(WEB_RULES, '.options-pin-btn[aria-pressed="true"]')["color"]
        hover = _merged(WEB_RULES, '.options-pin-btn[aria-pressed="false"]:hover')[
            "color"
        ]
        assert (rest, pressed, hover) == (
            "var(--text-secondary)",
            "var(--primary-600)",
            "var(--text-primary)",
        )

        themes = {
            "dark": (":root", ""),
            "light": ('[data-theme="light"]', ""),
            "light by preference": (
                ":root:not([data-theme])",
                "@media (prefers-color-scheme: light)",
            ),
        }
        for theme, (selector, context) in themes.items():
            tokens = _merged(WEB_RULES, selector, context)

            def colour(declaration: str, tokens: dict[str, str] = tokens) -> str:
                return tokens[declaration.removeprefix("var(").removesuffix(")")]

            # pinned, the button is inside the tray (--bg-secondary); unpinned it is on the page (--bg-primary)
            assert _contrast(colour(pressed), tokens["--bg-secondary"]) >= 3, theme
            assert _contrast(colour(rest), tokens["--bg-primary"]) >= 3, theme
            assert _contrast(colour(rest), tokens["--bg-secondary"]) >= 3, theme
            assert _contrast(colour(hover), tokens["--bg-primary"]) >= 4.5, theme

    def test_the_unpinned_list_is_the_list_of_before_the_tray_existed(self) -> None:
        """Unframed, as tall as its options, nothing scrolls inside it, and the layout properties of the base rule
        (a column with a gap and a bottom margin) are not touched, so the options keep their spacing."""
        unpinned = _merged(WEB_RULES, ".options-dock.is-unpinned .options-container")

        assert unpinned["max-height"] == "none"
        assert unpinned["overflow"] == "visible"
        assert unpinned["background"] == "none"
        assert unpinned["border"] == "0"
        assert unpinned["border-radius"] == "0"
        assert unpinned["box-shadow"] == "none"
        assert unpinned["padding"].split()[1:] == ["0", "0"]
        for kept in ("display", "flex-direction", "gap", "margin-bottom", "margin"):
            assert kept not in unpinned, kept

        base = _merged(WEB_RULES, ".options-container")
        assert base["margin-bottom"] == "1.25rem"
        assert base["gap"] == "1rem"

    def test_there_is_no_grip_in_an_unpinned_tray(self) -> None:
        assert _merged(
            WEB_RULES, ".options-dock.is-unpinned .options-resize-handle"
        ) == {"display": "none"}

    def test_the_pin_rules_work_without_has_and_without_a_script(self) -> None:
        selectors = [
            selector
            for _, selector, _ in WEB_RULES
            if "options-pin" in selector or "is-unpinned" in selector
        ]

        assert selectors
        assert all(":has(" not in selector for selector in selectors)

    def test_the_unpinned_tray_adds_no_stacking_context_or_clip_to_the_page(
        self,
    ) -> None:
        for selector in (
            ".options-dock.is-unpinned",
            ".options-dock.is-unpinned .options-container",
        ):
            declarations = _merged(WEB_RULES, selector)
            for forbidden in (
                "transform",
                "filter",
                "contain",
                "isolation",
                "will-change",
            ):
                assert forbidden not in declarations, (selector, forbidden)


# ------------------------------------------------------------------------------- the Web UI script, in Node
WEB_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const config = __CONFIG__;
const PIN_KEY = __PIN_KEY__;
const HEIGHT_KEY = __HEIGHT_KEY__;
const out = [];
const storage = new Map();
if (config.pinStored !== null) storage.set(PIN_KEY, config.pinStored);
if (config.heightStored !== null) storage.set(HEIGHT_KEY, config.heightStored);
const rootProps = new Map();
const writes = [];

function makeElement(id) {
  const listeners = {};
  const attributes = {};
  const classes = new Set();
  return {
    id,
    focusCalls: 0,
    focus() { this.focusCalls += 1; },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener(type, fn) { listeners[type] = (listeners[type] || []).filter((f) => f !== fn); },
    listenerCount(type) { return (listeners[type] || []).length; },
    setAttribute(name, value) { attributes[name] = String(value); },
    getAttribute(name) { return name in attributes ? attributes[name] : null; },
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
      toggle(name, force) {
        const on = force === undefined ? !classes.has(name) : !!force;
        if (on) classes.add(name); else classes.delete(name);
        return on;
      },
    },
    fire(type, event) {
      const e = { type, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...event };
      for (const fn of [...(listeners[type] || [])]) fn(e);
      return e;
    },
  };
}

const dock = makeElement('options-dock');
const list = makeElement('options-container');
const handle = makeElement('options-resize-handle');
const pin = makeElement('options-pin-btn');
const isUnpinned = () => dock.classList.contains('is-unpinned');
const hiddenList = () => config.listHidden;
// A pinned list is capped, an unpinned one is as tall as its options.
const capNow = () => (rootProps.has('--aiia-options-height') ? parseFloat(rootProps.get('--aiia-options-height')) : config.cap);
const listHeight = () => (hiddenList() ? 0 : isUnpinned() ? config.content : Math.min(config.content, capNow()));
Object.defineProperty(list, 'offsetHeight', { get: () => listHeight() });
Object.defineProperty(list, 'clientHeight', { get: () => Math.max(0, listHeight() - 2) });
Object.defineProperty(list, 'scrollHeight', { get: () => (hiddenList() ? 0 : config.content) });
list.getBoundingClientRect = () => ({ top: 100, height: listHeight(), bottom: 100 + listHeight() });
handle.releasePointerCapture = () => {};
handle.setPointerCapture = () => {};

const present = { 'options-container': list, 'options-resize-handle': handle };
if (config.hasDock) present['options-dock'] = dock;
if (config.hasPin) present['options-pin-btn'] = pin;
const root = {
  style: {
    setProperty(name, value) { rootProps.set(name, value); },
    removeProperty(name) { rootProps.delete(name); },
    getPropertyValue(name) { return rootProps.has(name) ? rootProps.get(name) : ''; },
  },
};
const doc = {
  readyState: 'complete',
  documentElement: root,
  getElementById(id) { return present[id] || null; },
  addEventListener() {},
};
const winListeners = {};
const win = {
  innerHeight: 800,
  scrollY: 0,
  addEventListener(type, fn) { (winListeners[type] = winListeners[type] || []).push(fn); },
  removeEventListener(type, fn) { winListeners[type] = (winListeners[type] || []).filter((f) => f !== fn); },
  scrollBy() {},
};
const observers = [];
class FakeResizeObserver {
  constructor(callback) { this.callback = callback; this.disconnected = false; observers.push(this); }
  observe() {}
  disconnect() { this.disconnected = true; }
}
const localStorage = {
  getItem(key) { if (config.throwsOnGet) throw new Error('denied'); return storage.has(key) ? storage.get(key) : null; },
  setItem(key, value) { if (config.throwsOnSet) throw new Error('quota'); writes.push(['set', key]); storage.set(key, String(value)); },
  removeItem(key) { if (config.throwsOnSet) throw new Error('denied'); writes.push(['remove', key]); storage.delete(key); },
};
const sandbox = { window: win, document: doc, localStorage, Date, Math, JSON, Number, Object, String, Array, Error, ResizeObserver: FakeResizeObserver };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__MODULE__, 'utf8'), sandbox, { filename: 'feedback_options_dock.js' });
const api = win.AIIA_FEEDBACK_OPTIONS_DOCK;
const state = () => ({
  pressed: pin.getAttribute('aria-pressed'),
  unpinned: isUnpinned(),
  reserve: rootProps.has('--aiia-options-reserve') ? rootProps.get('--aiia-options-reserve') : null,
  height: rootProps.has('--aiia-options-height') ? rootProps.get('--aiia-options-height') : null,
  pinStored: storage.has(PIN_KEY) ? storage.get(PIN_KEY) : null,
  heightStored: storage.has(HEIGHT_KEY) ? storage.get(HEIGHT_KEY) : null,
});
const click = () => pin.fire('click');
const resizeEverything = () => {
  for (const fn of [...(winListeners.resize || [])]) fn({ type: 'resize' });
  for (const o of observers) if (!o.disconnected) o.callback([]);
};
__BODY__
process.stdout.write(JSON.stringify(out));
"""

WEB_DEFAULTS: dict[str, Any] = {
    "pinStored": None,
    "heightStored": None,
    "content": 1000,
    "cap": 320,
    "listHidden": False,
    "hasDock": True,
    "hasPin": True,
    "throwsOnGet": False,
    "throwsOnSet": False,
}


def _web(body: str, **overrides: Any) -> list[dict[str, Any]]:
    config = {**WEB_DEFAULTS, **overrides}
    script = (
        WEB_HARNESS.replace("__CONFIG__", json.dumps(config))
        .replace("__PIN_KEY__", json.dumps(PIN_KEY))
        .replace("__HEIGHT_KEY__", json.dumps(HEIGHT_KEY))
        .replace("__MODULE__", json.dumps(str(WEB_JS)))
        .replace("__BODY__", body)
    )
    return json.loads(_run_node(script))


@needs_node
class TestWebScript:
    def test_the_tray_starts_pinned_and_writes_nothing_when_nothing_is_stored(
        self,
    ) -> None:
        out = _web("out.push(state()); out.push({ writes });")

        assert out[0] == {
            "pressed": "true",
            "unpinned": False,
            "reserve": "336px",
            "height": None,
            "pinStored": None,
            "heightStored": None,
        }
        assert out[1]["writes"] == []

    def test_an_unpinned_choice_is_applied_when_the_page_starts(self) -> None:
        stored = json.dumps({"schema_version": 1, "pinned": False, "saved_at": 1})

        out = _web("out.push(state());", pinStored=stored)

        assert out[0]["pressed"] == "false"
        assert out[0]["unpinned"] is True
        assert out[0]["reserve"] == "0px", "an unpinned list is part of the message"

    @pytest.mark.parametrize(
        "raw",
        [
            "{not json",
            "",
            "null",
            "[]",
            '"false"',
            "false",
            "0",
            '{"pinned":false}',
            '{"schema_version":2,"pinned":false}',
            '{"schema_version":"1","pinned":false}',
            '{"schema_version":1,"pinned":"false"}',
            '{"schema_version":1,"pinned":0}',
            '{"schema_version":1,"pinned":null}',
            '{"schema_version":1}',
            '{"schema_version":1,"pinned":true}',
        ],
    )
    def test_anything_that_is_not_an_explicit_unpinned_means_pinned(
        self, raw: str
    ) -> None:
        out = _web("out.push(state());", pinStored=raw)

        assert out[0]["pressed"] == "true", raw
        assert out[0]["unpinned"] is False, raw
        assert out[0]["reserve"] == "336px", raw

    def test_a_click_unpins_then_pins_and_the_page_follows_at_once(self) -> None:
        out = _web(
            """
            click(); out.push(state());
            click(); out.push(state());
            click(); out.push(state());
            """
        )

        unpinned, pinned, unpinned_again = out
        assert (unpinned["pressed"], unpinned["unpinned"], unpinned["reserve"]) == (
            "false",
            True,
            "0px",
        )
        assert (pinned["pressed"], pinned["unpinned"], pinned["reserve"]) == (
            "true",
            False,
            "336px",
        ), "pinning must reserve room straight away, not on the next resize"
        assert unpinned_again["pressed"] == "false"

    def test_only_unpinned_is_stored_and_pinning_again_leaves_nothing_behind(
        self,
    ) -> None:
        out = _web(
            """
            click(); out.push({ ...state(), writes: writes.slice() });
            click(); out.push({ ...state(), writes: writes.slice() });
            """
        )

        stored = json.loads(out[0]["pinStored"])
        assert set(stored) == {"schema_version", "pinned", "saved_at"}
        assert stored["schema_version"] == 1 and stored["pinned"] is False
        assert isinstance(stored["saved_at"], (int, float)) and stored["saved_at"] > 0
        assert out[0]["writes"] == [["set", PIN_KEY]]
        assert out[1]["pinStored"] is None
        assert out[1]["writes"] == [["set", PIN_KEY], ["remove", PIN_KEY]]

    def test_the_key_is_its_own_and_not_the_one_of_the_height(self) -> None:
        out = _web("out.push({ pin: api.PIN_STORAGE_KEY, height: api.STORAGE_KEY });")

        assert out[0] == {"pin": PIN_KEY, "height": HEIGHT_KEY}
        assert PIN_KEY != HEIGHT_KEY

    def test_unpinning_never_touches_the_height_the_reader_set(self) -> None:
        height = json.dumps({"schema_version": 1, "height_px": 220, "saved_at": 1})

        out = _web(
            """
            out.push(state());
            click(); out.push(state());
            resizeEverything(); out.push(state());
            click(); out.push(state());
            """,
            heightStored=height,
        )

        assert [step["height"] for step in out] == ["220px"] * 4
        assert [step["heightStored"] for step in out] == [height] * 4
        assert out[1]["reserve"] == "0px" and out[3]["reserve"] == "236px"

    def test_a_resize_while_unpinned_does_not_bring_the_reserve_back(self) -> None:
        out = _web(
            """
            click();
            resizeEverything(); out.push(state());
            resizeEverything(); out.push(state());
            """
        )

        assert [step["reserve"] for step in out] == ["0px", "0px"]

    def test_a_hidden_list_reserves_nothing_in_either_state(self) -> None:
        out = _web(
            "out.push(state()); click(); out.push(state()); click(); out.push(state());",
            listHidden=True,
        )

        assert [step["reserve"] for step in out] == ["0px", "0px", "0px"]

    def test_storage_that_refuses_to_work_does_not_break_the_toggle(self) -> None:
        out = _web(
            """
            out.push(state());
            click(); out.push(state());
            click(); out.push(state());
            """,
            throwsOnGet=True,
            throwsOnSet=True,
        )

        assert [step["pressed"] for step in out] == ["true", "false", "true"]
        assert [step["unpinned"] for step in out] == [False, True, False]
        assert all(step["pinStored"] is None for step in out)

    def test_the_helpers_report_what_they_did(self) -> None:
        out = _web(
            """
            out.push({
              read: api.readPersistedPinned(),
              unpinned: api.persistPinned(false), afterUnpin: api.readPersistedPinned(),
              pinned: api.persistPinned(true), afterPin: api.readPersistedPinned(),
              nothing: api.persistPinned(undefined), afterNothing: api.readPersistedPinned(),
            });
            """
        )

        assert out[0]["read"] is True
        assert (out[0]["unpinned"], out[0]["afterUnpin"]) == (True, False)
        assert (out[0]["pinned"], out[0]["afterPin"]) == (True, True)
        assert (out[0]["nothing"], out[0]["afterNothing"]) == (True, True), (
            "only an explicit `false` may be written; anything else clears the key"
        )

    def test_the_helpers_say_so_when_the_write_failed(self) -> None:
        out = _web(
            "out.push({ unpinned: api.persistPinned(false), pinned: api.persistPinned(true), read: api.readPersistedPinned() });",
            throwsOnGet=True,
            throwsOnSet=True,
        )

        assert out[0] == {"unpinned": False, "pinned": False, "read": True}

    def test_calling_init_again_replaces_the_listener_instead_of_adding_to_it(
        self,
    ) -> None:
        out = _web(
            """
            const first = api.init();
            const second = api.init();
            out.push({ listeners: pin.listenerCount('click'), same: first === second, bound: second.pinButton === pin });
            click(); out.push(state());
            """
        )

        assert out[0] == {"listeners": 1, "same": False, "bound": True}
        assert out[1]["pressed"] == "false", "one click must toggle once, not twice"

    def test_destroying_the_binding_removes_the_listener(self) -> None:
        out = _web(
            """
            const binding = api.init();
            binding.destroy();
            out.push({ listeners: pin.listenerCount('click') });
            click(); out.push(state());
            """
        )

        assert out[0] == {"listeners": 0}
        assert out[1]["pressed"] == "true"

    @pytest.mark.parametrize(
        ("has_dock", "has_pin"), [(False, True), (True, False), (False, False)]
    )
    def test_a_page_without_the_tray_or_the_button_stays_pinned_and_still_works(
        self, has_dock: bool, has_pin: bool
    ) -> None:
        stored = json.dumps({"schema_version": 1, "pinned": False, "saved_at": 1})

        out = _web(
            """
            const binding = api.init();
            out.push({ bound: binding !== null, hasButton: binding.pinButton !== null });
            if (pin.listenerCount('click')) click();
            out.push(state());
            """,
            hasDock=has_dock,
            hasPin=has_pin,
            pinStored=stored,
        )

        assert out[0]["bound"] is True
        assert out[1]["reserve"] == "336px", (
            "without a button nobody can unpin, whatever is stored"
        )
        assert out[1]["pinStored"] == stored, (
            "a page that cannot show the choice must not overwrite it"
        )

    def test_the_script_never_moves_focus_or_disables_the_button(self) -> None:
        out = _web(
            """
            click(); click(); click();
            out.push({ focus: pin.focusCalls, disabled: pin.getAttribute('disabled'), hidden: pin.getAttribute('hidden'), tabindex: pin.getAttribute('tabindex') });
            """
        )

        assert out[0] == {
            "focus": 0,
            "disabled": None,
            "hidden": None,
            "tabindex": None,
        }

    def test_the_public_surface_gained_exactly_the_pin_names(self) -> None:
        out = _web("out.push(Object.keys(api).sort());")

        assert out[0] == sorted(
            [
                "HEIGHT_VAR",
                "MAX_STORED_HEIGHT_PX",
                "MIN_HEIGHT_PX",
                "PIN_STORAGE_KEY",
                "RESERVE_VAR",
                "SCHEMA_VERSION",
                "STORAGE_KEY",
                "clampHeight",
                "init",
                "normalizeStoredHeight",
                "persistHeight",
                "persistPinned",
                "readPersistedHeight",
                "readPersistedPinned",
                "resolveKey",
            ]
        )


# =========================================================================================== the VS Code panel
class TestPanelTemplate:
    def test_the_dock_starts_pinned_between_the_message_and_the_input_box(self) -> None:
        template = PANEL_TS.read_text(encoding="utf-8")

        scroller = template.index('<div class="scrollable-content">')
        scroller_end = _closing(template, scroller)
        dock = template.index('id="optionsSection"')
        composer = template.index('<div class="fixed-input-area">')

        assert scroller_end <= dock < composer
        assert 'class="options-dock hidden" id="optionsSection"' in template
        assert "is-unpinned" not in template, "the page starts in the pinned layout"

    def test_the_head_row_holds_the_label_and_the_button_above_the_list(self) -> None:
        dock = _panel_dock()
        head_start = dock.index('<div class="options-head">')
        head = dock[head_start : _closing(dock, head_start)]

        assert head.index("form-label") < head.index("<button")
        assert 'data-i18n="ui.form.optionsLabel"' in head
        assert head_start < dock.index('id="optionsContainer"')
        assert dock.index('id="optionsResizeHandle"') < head_start
        assert dock.count("<button") == 1

    def test_the_button_is_a_labelled_toggle_that_starts_pinned(self) -> None:
        attributes, source = _panel_button()

        assert attributes["type"] == "button"
        assert attributes["id"] == "optionsPinBtn"
        assert attributes["class"] == "options-pin-btn"
        assert attributes["aria-pressed"] == "true"
        assert attributes["data-i18n-aria-label"] == "ui.form.optionsPin"
        assert attributes["data-i18n-title"] == "ui.form.optionsPinHint"
        assert attributes["aria-label"] == "TL(ui.form.optionsPin)"
        assert attributes["title"] == "TL(ui.form.optionsPinHint)"
        assert 'aria-hidden="true"' in source and 'focusable="false"' in source
        assert "style" not in attributes and "onclick" not in attributes
        assert PIN_PATH in source

    def test_the_two_surfaces_draw_the_same_pin(self) -> None:
        assert PIN_PATH in _web_button()[1]
        assert PIN_PATH in _panel_button()[1]
        web_icon = re.search(r"<svg.*?</svg>", _web_button()[1], re.S)
        panel_icon = re.search(r"<svg.*?</svg>", _panel_button()[1], re.S)
        assert web_icon and panel_icon
        assert 'viewBox="0 0 24 24"' in web_icon.group(0)
        assert 'viewBox="0 0 24 24"' in panel_icon.group(0)

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_texts_exist_in_every_locale_of_the_panel(self, locale: str) -> None:
        form = _locale(PANEL_LOCALES / f"{locale}.json", "ui", "form")

        assert form["optionsPin"].strip(), locale
        assert form["optionsPinHint"].strip(), locale
        assert form["optionsPin"] != form["optionsPinHint"]

    def test_the_keys_are_known_to_the_typed_translator(self) -> None:
        keys = PANEL_KEYS.read_text(encoding="utf-8")

        # the generated file lists every key twice: as a member of the union type and in the array
        for key in ("ui.form.optionsPin", "ui.form.optionsPinHint"):
            assert re.search(rf'^  \| "{re.escape(key)}"$', keys, re.MULTILINE), key
            assert re.search(rf'^  "{re.escape(key)}",$', keys, re.MULTILINE), key

    def test_the_chinese_texts_use_the_script_of_their_locale(self) -> None:
        en = _locale(PANEL_LOCALES / "en.json", "ui", "form")
        zh_cn = _locale(PANEL_LOCALES / "zh-CN.json", "ui", "form")
        zh_tw = _locale(PANEL_LOCALES / "zh-TW.json", "ui", "form")

        assert en["optionsPin"] == "Pin options"
        assert not CJK.search(en["optionsPin"] + en["optionsPinHint"])
        assert "固定" in zh_cn["optionsPin"] and "固定" in zh_tw["optionsPin"]
        assert "选" in zh_cn["optionsPin"] and "選" in zh_tw["optionsPin"]
        assert "选" not in zh_tw["optionsPin"] + zh_tw["optionsPinHint"]


class TestPanelStylesheet:
    def test_the_label_and_the_button_share_one_row(self) -> None:
        head = _merged(PANEL_RULES, ".options-head")

        assert head["display"] == "flex"
        assert head["align-items"] == "center"
        assert head["justify-content"] == "space-between"
        assert head["margin-bottom"] == "2px", (
            "the gap to the list is what the label had"
        )
        assert _merged(PANEL_RULES, ".options-head .form-label")["margin-bottom"] == "0"

    def test_the_button_does_not_make_the_row_taller_than_the_label(self) -> None:
        button = _merged(PANEL_RULES, ".options-pin-btn")
        label = _merged(PANEL_RULES, ".form-label")

        size = int(button["width"].removesuffix("px"))
        assert button["height"] == button["width"] and size >= 22
        vertical = int(button["margin"].split()[0].removesuffix("px"))
        assert vertical < 0 and button["margin"] == f"{vertical}px 0"
        assert button["flex"] == "none"
        font = int(label["font-size"].removesuffix("px"))
        # a line of text is never shorter than its font size, so a margin box that is not taller adds nothing
        assert 0 < size + 2 * vertical <= font, (
            "the negative margins must absorb the button's extra height: the pinned dock keeps its size"
        )
        assert button["cursor"] == "pointer"

    def test_the_button_is_painted_above_the_grip_it_overlaps(self) -> None:
        """The grip is a full-width strip along the top of the dock; the button's top edge is inside it."""
        button = _merged(PANEL_RULES, ".options-pin-btn")
        grip = _merged(PANEL_RULES, ".options-resize-handle")

        assert grip["position"] == "absolute"
        assert button["position"] == "relative"
        assert int(button["z-index"]) > int(grip["z-index"])

    def test_a_pressed_button_is_filled_and_boxed_an_unpressed_one_is_tilted(
        self,
    ) -> None:
        pressed = _merged(PANEL_RULES, '.options-pin-btn[aria-pressed="true"]')

        assert "inputOption-activeBackground" in pressed["background"]
        assert "inputOption-activeBorder" in pressed["border-color"]
        assert _merged(
            PANEL_RULES, '.options-pin-btn[aria-pressed="true"] .options-pin-icon'
        ) == {"fill": "currentColor"}
        assert _merged(
            PANEL_RULES, '.options-pin-btn[aria-pressed="false"] .options-pin-icon'
        ) == {"transform": "rotate(45deg)"}

    def test_the_unpinned_dock_is_the_card_it_was_before_the_dock_existed(self) -> None:
        """As tall as its options, nothing scrolls or is clipped, and the margins are the scroller's."""
        dock = _merged(PANEL_RULES, ".options-dock.is-unpinned")
        options = _merged(PANEL_RULES, ".options-dock.is-unpinned .options-container")

        assert dock["max-height"] == "none"
        assert dock["min-height"] == "0"
        assert dock["overflow"] == "visible"
        assert dock["margin"] == "0"
        assert options["overflow"] == "visible"
        assert options["flex"] == "none"
        assert _merged(
            PANEL_RULES, ".options-dock.is-unpinned .options-resize-handle"
        ) == {"display": "none"}

    def test_the_unpinned_card_keeps_the_chrome_of_the_dock(self) -> None:
        """Padding, background, border and radius are not overridden: it is the same card, just in the flow."""
        dock = _merged(PANEL_RULES, ".options-dock.is-unpinned")

        for chrome in (
            "padding",
            "background",
            "border",
            "border-radius",
            "position",
            "display",
            "gap",
        ):
            assert chrome not in dock, chrome

    def test_the_unpinned_rules_outrank_every_rule_they_undo_and_the_scrollers_margin_rule(
        self,
    ) -> None:
        pairs = _undone(PANEL_RULES)

        assert {(other, name) for _, other, name in pairs} >= {
            (".options-dock", "margin"),
            (".options-dock", "max-height"),
            (".options-dock", "min-height"),
            (".options-dock", "overflow"),
            (".options-container", "flex"),
            (".options-container", "overflow-y"),
            (".options-resize-handle", "display"),
        }, "the unpinned rules no longer undo what the pinned dock sets"
        for selector, other, name in pairs:
            assert _specificity(selector) > _specificity(other), (selector, other, name)

        # In the scroller the dock is also matched by ``.scrollable-content > *`` (8 px under every block).
        scroller_margin = [
            selector
            for _, selector, declarations in PANEL_RULES
            if selector.startswith(".scrollable-content >")
            and selector.endswith(" *")
            and "margin" in declarations
        ]
        assert scroller_margin, "the rule that spaces the blocks of the message is gone"
        for selector in scroller_margin:
            assert _specificity(".options-dock.is-unpinned") > _specificity(selector)

    def test_a_dock_in_the_scroller_does_not_trigger_the_rule_that_protects_the_message(
        self,
    ) -> None:
        """The reservation for a pinned dock only matches a *direct child* of the form; the moved dock is not one."""
        selectors = [
            selector for _, selector, _ in PANEL_RULES if "options-dock" in selector
        ]

        assert (
            ".feedback-form:has(> .options-dock:not(.hidden)) > .scrollable-content"
            in selectors
        )
        assert all("is-unpinned" not in s for s in selectors if ":has(" in s)

    def test_the_hidden_class_still_wins_so_a_task_without_options_shows_no_card(
        self,
    ) -> None:
        hidden = _merged(PANEL_RULES, ".hidden")

        assert hidden["display"] == "none !important"


# ----------------------------------------------------------------------------------- the panel logic, in Node
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
    raise AssertionError(f"could not extract {name}()")


PANEL_DOM = r"""
class FakeNode {
  constructor(id, className = '') {
    this.id = id;
    this.className = className;
    this.children = [];
    this.parentElement = null;
    this.attributes = {};
    this.classes = new Set(className.split(/\s+/).filter(Boolean));
    this.listeners = {};
    this.focusArgs = [];
    this.moves = 0;
    this.focusThrowsOnOptions = false;
    const node = this;
    this.classList = {
      toggle(name, force) {
        const on = force === undefined ? !node.classes.has(name) : !!force;
        if (on) node.classes.add(name); else node.classes.delete(name);
        return on;
      },
      contains(name) { return node.classes.has(name); },
      add(name) { node.classes.add(name); },
      remove(name) { node.classes.delete(name); },
    };
  }
  contains(node) {
    return node === this || this.children.some((c) => c.contains(node));
  }
  _detach(child) {
    if (child.parentElement) {
      const siblings = child.parentElement.children;
      siblings.splice(siblings.indexOf(child), 1);
      child.parentElement = null;
      // A node that is moved (removed and inserted) loses focus, and so does everything inside it.
      if (focused && child.contains(focused)) focused = null;
    }
  }
  appendChild(child) {
    this._detach(child);
    this.children.push(child);
    child.parentElement = this;
    child.moves += 1;
    return child;
  }
  insertBefore(child, reference) {
    if (!this.children.includes(reference)) throw new Error('the reference node is not a child of this node');
    this._detach(child);
    this.children.splice(this.children.indexOf(reference), 0, child);
    child.parentElement = this;
    child.moves += 1;
    return child;
  }
  querySelector(selector) {
    const wanted = selector.replace(/^\./, '');
    return this.children.find((c) => c.classes.has(wanted)) || null;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  fire(type) { for (const fn of this.listeners[type] || []) fn({ type }); }
  focus(options) {
    this.focusArgs.push(options === undefined ? 'none' : JSON.stringify(options));
    if (options !== undefined && this.focusThrowsOnOptions) throw new TypeError('focus() takes no arguments here');
    focused = this;
  }
}
let focused = null;
const form = new FakeNode('feedbackForm', 'feedback-form');
const scroller = new FakeNode('', 'scrollable-content');
const chip = new FakeNode('taskHeaderChip');
const message = new FakeNode('markdownContent');
const dock = new FakeNode('optionsSection', 'options-dock hidden');
const grip = new FakeNode('optionsResizeHandle', 'options-resize-handle');
const head = new FakeNode('', 'options-head');
const label = new FakeNode('', 'form-label');
const button = new FakeNode('optionsPinBtn', 'options-pin-btn');
const list = new FakeNode('optionsContainer', 'options-container');
const composer = new FakeNode('', 'fixed-input-area');
scroller.appendChild(chip); scroller.appendChild(message);
dock.appendChild(grip); dock.appendChild(head); head.appendChild(label); head.appendChild(button); dock.appendChild(list);
form.appendChild(scroller); form.appendChild(dock); form.appendChild(composer);
for (const n of [scroller, chip, message, dock, grip, head, label, button, list, composer]) n.moves = 0;
const ids = { feedbackForm: form, optionsSection: dock, optionsPinBtn: button, optionsContainer: list, optionsResizeHandle: grip };
if (config.drop) for (const id of config.drop) delete ids[id];
const document = { getElementById: (id) => ids[id] || null };
const layout = () => ({
  dockParent: dock.parentElement === form ? 'form' : dock.parentElement === scroller ? 'scroller' : String(dock.parentElement && dock.parentElement.id),
  formOrder: form.children.map((c) => c === scroller ? 'scroller' : c === dock ? 'dock' : c === composer ? 'composer' : '?'),
  scrollerOrder: scroller.children.map((c) => c === chip ? 'chip' : c === message ? 'message' : c === dock ? 'dock' : '?'),
  unpinnedClass: dock.classList.contains('is-unpinned'),
  hiddenClass: dock.classList.contains('hidden'),
  pressed: button.getAttribute('aria-pressed'),
  dockMoves: dock.moves,
  focusedIsButton: focused === button,
  focusArgs: button.focusArgs.slice(),
  headIntact: head.children.length === 2 && head.children[1] === button && dock.children.includes(head) && dock.children.includes(list) && dock.children.includes(grip),
});
"""

PANEL_SCRIPT = r"""
const config = __CONFIG__;
let optionsPinned = config.pinned;
let saves = 0;
function schedulePersistUiState() { saves += 1; }
__DOM__
__FUNCTION__
__BODY__
process.stdout.write(JSON.stringify(out));
"""


def _panel(body: str, **config: Any) -> list[dict[str, Any]]:
    source = PANEL_UI_JS.read_text(encoding="utf-8")
    script = (
        PANEL_SCRIPT.replace("__CONFIG__", json.dumps({"pinned": True, **config}))
        .replace("__DOM__", PANEL_DOM)
        .replace("__FUNCTION__", _extract_function(source, "initOptionsPin"))
        .replace("__BODY__", "const out = [];\n" + textwrap.dedent(body))
    )
    return json.loads(_run_node(script))


@needs_node
class TestPanelScript:
    def test_pinned_is_the_default_and_nothing_is_moved(self) -> None:
        out = _panel("initOptionsPin(); out.push(layout()); out.push({ saves });")

        assert out[0]["dockParent"] == "form"
        assert out[0]["formOrder"] == ["scroller", "dock", "composer"]
        assert out[0]["unpinnedClass"] is False
        assert out[0]["pressed"] == "true"
        assert out[0]["dockMoves"] == 0, (
            "re-parenting an already placed dock would drop the focus inside it"
        )
        assert out[0]["hiddenClass"] is True, (
            "the script must not show or hide the dock"
        )
        assert out[1]["saves"] == 0, "starting up is not a change worth saving"

    def test_an_unpinned_choice_moves_the_dock_to_the_end_of_the_message_at_start(
        self,
    ) -> None:
        out = _panel("initOptionsPin(); out.push(layout());", pinned=False)

        assert out[0]["dockParent"] == "scroller"
        assert out[0]["scrollerOrder"] == ["chip", "message", "dock"]
        assert out[0]["formOrder"] == ["scroller", "composer"]
        assert out[0]["unpinnedClass"] is True
        assert out[0]["pressed"] == "false"
        assert out[0]["hiddenClass"] is True, (
            "a task without options keeps the dock hidden"
        )
        assert out[0]["headIntact"] is True

    def test_a_click_moves_the_dock_there_and_back_to_exactly_where_it_was(
        self,
    ) -> None:
        out = _panel(
            """
            initOptionsPin();
            button.fire('click'); out.push(layout());
            button.fire('click'); out.push(layout());
            button.fire('click'); out.push(layout());
            """
        )

        unpinned, pinned, unpinned_again = out
        assert unpinned["scrollerOrder"] == ["chip", "message", "dock"]
        assert unpinned["formOrder"] == ["scroller", "composer"]
        assert (unpinned["unpinnedClass"], unpinned["pressed"]) == (True, "false")
        assert pinned["formOrder"] == ["scroller", "dock", "composer"]
        assert pinned["scrollerOrder"] == ["chip", "message"]
        assert (pinned["unpinnedClass"], pinned["pressed"]) == (False, "true")
        assert unpinned_again["scrollerOrder"] == ["chip", "message", "dock"]
        assert unpinned_again["dockMoves"] == 3
        assert all(step["headIntact"] for step in out)

    def test_every_click_is_saved_once_and_the_variable_follows(self) -> None:
        out = _panel(
            """
            initOptionsPin();
            button.fire('click'); out.push({ saves, optionsPinned });
            button.fire('click'); out.push({ saves, optionsPinned });
            """
        )

        assert out == [
            {"saves": 1, "optionsPinned": False},
            {"saves": 2, "optionsPinned": True},
        ]

    def test_focus_stays_on_the_button_across_the_move(self) -> None:
        out = _panel(
            """
            initOptionsPin();
            button.focus(); button.focusArgs.length = 0;
            button.fire('click'); out.push(layout());
            button.fire('click'); out.push(layout());
            """
        )

        for count, step in enumerate(out, start=1):
            assert step["focusedIsButton"] is True
            assert step["focusArgs"] == ['{"preventScroll":true}'] * count, (
                "focus() must not scroll the message away from where it is being read"
            )

    def test_an_engine_that_rejects_focus_options_still_gets_the_button_focused(
        self,
    ) -> None:
        out = _panel(
            """
            initOptionsPin();
            button.focusThrowsOnOptions = true;
            button.fire('click');
            out.push(layout());
            """
        )

        assert out[0]["focusedIsButton"] is True
        assert out[0]["focusArgs"] == ['{"preventScroll":true}', "none"]

    @pytest.mark.parametrize(
        "missing",
        [
            ["feedbackForm"],
            ["optionsSection"],
            ["optionsPinBtn"],
            ["feedbackForm", "optionsSection", "optionsPinBtn"],
        ],
    )
    def test_a_page_without_the_dock_the_button_or_the_form_is_left_alone(
        self, missing: list[str]
    ) -> None:
        out = _panel(
            """
            initOptionsPin();
            out.push({ clicks: button.listeners.click ? button.listeners.click.length : 0, saves, moves: [dock.moves, button.moves, scroller.moves] });
            """,
            drop=missing,
            pinned=False,
        )

        assert out[0] == {"clicks": 0, "saves": 0, "moves": [0, 0, 0]}

    def test_a_form_without_the_scroller_or_the_input_box_is_left_alone(self) -> None:
        out = _panel(
            """
            form.children.splice(form.children.indexOf(composer), 1);
            initOptionsPin();
            out.push({ clicks: button.listeners.click ? button.listeners.click.length : 0, parent: dock.parentElement === form });
            """,
            pinned=False,
        )

        assert out[0] == {"clicks": 0, "parent": True}

    def test_the_head_and_the_list_are_never_taken_out_of_the_dock(self) -> None:
        out = _panel(
            """
            initOptionsPin();
            for (let i = 0; i < 7; i++) button.fire('click');
            out.push({ ...layout(), headMoves: head.moves, listMoves: list.moves, gripMoves: grip.moves, buttonMoves: button.moves });
            """
        )

        assert out[0]["headIntact"] is True
        assert (
            out[0]["headMoves"],
            out[0]["listMoves"],
            out[0]["gripMoves"],
            out[0]["buttonMoves"],
        ) == (0, 0, 0, 0)
        assert out[0]["dockMoves"] == 7
        assert out[0]["unpinnedClass"] is True


def _restore(state_js: str) -> dict[str, Any]:
    source = PANEL_UI_JS.read_text(encoding="utf-8")
    script = textwrap.dedent(
        f"""
        const UI_STATE_VERSION = 1;
        let taskTextareaContents = {{}}, taskOptionsStates = {{}}, activeTaskId = null;
        let textareaManualRows = null, optionsManualHeight = null, optionsPinned = true;
        const WEBVIEW_HELPERS = require({json.dumps(str(PANEL_HELPERS_JS))});
        const safeGetUiState = () => {state_js};
        {_extract_function(source, "restorePersistedUiState")}
        restorePersistedUiState();
        process.stdout.write(JSON.stringify({{ optionsPinned, optionsManualHeight }}));
        """
    )
    return json.loads(_run_node(script))


@needs_node
class TestPanelPersistence:
    def test_only_an_explicit_false_unpins(self) -> None:
        assert _restore("({ v: 1, optionsPinned: false })")["optionsPinned"] is False
        for stored in ("true", "undefined", "null", "'false'", "0", "''", "[]", "{}"):
            result = _restore(f"({{ v: 1, optionsPinned: {stored} }})")
            assert result["optionsPinned"] is True, stored

    def test_no_state_or_a_state_of_another_version_means_pinned(self) -> None:
        assert _restore("null")["optionsPinned"] is True
        assert _restore("({ v: 2, optionsPinned: false })")["optionsPinned"] is True
        assert _restore("({ optionsPinned: false })")["optionsPinned"] is True

    def test_the_pin_and_the_height_are_restored_independently(self) -> None:
        result = _restore("({ v: 1, optionsPinned: false, optionsManualHeight: 210 })")

        assert result == {"optionsPinned": False, "optionsManualHeight": 210}

    def test_the_choice_is_saved_with_the_rest_of_the_panel_state(self) -> None:
        source = PANEL_UI_JS.read_text(encoding="utf-8")
        script = textwrap.dedent(
            f"""
            const UI_STATE_VERSION = 1, UI_STATE_SAVE_DEBOUNCE_MS = 250;
            const vscode = {{ setState() {{}} }};
            let uiStateSaveTimer = null, activeTaskId = 'a', taskTextareaContents = {{}}, taskOptionsStates = {{}};
            let textareaManualRows = null, optionsManualHeight = 180, optionsPinned = __PINNED__;
            const saved = [];
            const safeSetUiState = (state) => saved.push(state);
            const trimTextareaContents = (x) => x;
            const setTimeout = (fn) => {{ fn(); return 1; }};
            {_extract_function(source, "schedulePersistUiState")}
            schedulePersistUiState();
            process.stdout.write(JSON.stringify(saved));
            """
        )

        for pinned in ("true", "false"):
            saved = json.loads(_run_node(script.replace("__PINNED__", pinned)))
            assert len(saved) == 1
            assert saved[0]["optionsPinned"] is (pinned == "true")
            assert saved[0]["optionsManualHeight"] == 180

    def test_the_button_is_wired_up_with_the_other_listeners_after_the_grip(
        self,
    ) -> None:
        source = PANEL_UI_JS.read_text(encoding="utf-8")
        setup = _extract_function(source, "setupEventListeners")

        assert setup.index("initOptionsResize()") < setup.index("initOptionsPin()")
        assert setup.count("initOptionsPin()") == 1

    def test_the_variable_starts_pinned_and_is_declared_before_it_is_restored(
        self,
    ) -> None:
        source = PANEL_UI_JS.read_text(encoding="utf-8")

        assert re.search(r"^\s*let optionsPinned = true$", source, re.M)
        assert source.index("let optionsPinned = true") < source.index(
            "function restorePersistedUiState"
        )
