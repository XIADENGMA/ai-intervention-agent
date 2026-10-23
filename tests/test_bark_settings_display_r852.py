"""R852: the Bark settings show only what is needed and keep the Device Key out of sight.

Opening the settings of the Web UI or of the VS Code panel put six Bark fields on the page
whether or not Bark was in use, and the one that matters most - the Device Key, which is
what lets anyone push to the owner's phone - sat there as readable text.  The labels did not
help: the panel's were English in every language ("Bark URL", "Bark Device Key", "Bark Icon",
"Bark Action": the repeated word was the only thing that told the fields apart from the
neighbouring ones), the Web UI's placeholder on a Chinese page read "请输入 Bark Device Key",
and the two surfaces worded the same field differently.

Now, on both surfaces:

* the fields live in one group that is collapsed until "Enable Bark notification" is ticked
  (``aria-controls`` ties the checkbox to the group; the checkbox itself stays outside it);
* the Device Key is a ``type="password"`` field with a show/hide button - a real ``<button>``
  with a state attribute, an accessible name that says what a press will do, and an eye /
  eye-off icon - and a line under it saying where the key is found; the key is masked again
  when the group collapses and when the panel closes, and revealing it saves nothing;
* the labels drop the repeated product name ("Push URL", "Device Key", "Icon URL",
  "Click action"), are written in all three languages, and are the same strings on both surfaces.

The checks are of three kinds: the markup (parsed, not grepped), the locale files, and the
real scripts run in Node against a small fake DOM - so a rename of the ids, a lost
``hidden`` default, a dropped re-mask or a label that creeps back into English each fail here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "ai_intervention_agent"
PLUGIN = ROOT / "packages" / "vscode"

WEB_HTML = WEB / "templates" / "web_ui.html"
WEB_JS = WEB / "static" / "js" / "settings-manager.js"
WEB_CSS = WEB / "static" / "css" / "main.css"
WEB_LOCALES = WEB / "static" / "locales"
PLUGIN_TS = PLUGIN / "webview.ts"
PLUGIN_JS = PLUGIN / "webview-settings-ui.js"
PLUGIN_CSS = PLUGIN / "webview.css"
PLUGIN_LOCALES = PLUGIN / "locales"

LANGUAGES = ("en", "zh-CN", "zh-TW")
CJK = re.compile(r"[\u4e00-\u9fff]")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")


# --------------------------------------------------------------------------- a tiny DOM

VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}
    | {"source", "track", "wbr"}
)


class Node:
    def __init__(
        self, tag: str, attrs: dict[str, str | None], parent: Node | None
    ) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Node] = []

    def has(self, name: str) -> bool:
        return name in self.attrs

    def attr(self, name: str) -> str:
        return self.attrs.get(name) or ""

    def inside(self, ancestor: Node) -> bool:
        node = self.parent
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent
        return False

    def descendants(self) -> Iterator[Node]:
        for child in self.children:
            yield child
            yield from child.descendants()


class Dom(HTMLParser):
    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.by_id: dict[str, Node] = {}
        self._open = self.root
        self.feed(markup)
        self.close()

    def _add(self, tag: str, attrs: list[tuple[str, str | None]]) -> Node:
        node = Node(tag, dict(attrs), self._open)
        self._open.children.append(node)
        element_id = node.attrs.get("id")
        if element_id:
            self.by_id[element_id] = node
        return node

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._add(tag, attrs)
        if tag not in VOID_TAGS:
            self._open = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._add(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        node: Node | None = self._open
        while node is not None and node is not self.root and node.tag != tag:
            node = node.parent
        if node is not None and node is not self.root and node.parent is not None:
            self._open = node.parent

    def get(self, element_id: str) -> Node:
        assert element_id in self.by_id, f"#{element_id} is not in the markup"
        return self.by_id[element_id]


def _web_dom() -> Dom:
    return Dom(WEB_HTML.read_text(encoding="utf-8"))


def _plugin_dom() -> Dom:
    """The panel's markup lives in a template literal; read it as the panel would render.

    ``${tl("some.key")}`` renders to the translated text, and the key stands in for it here
    (the locale files are checked on their own); any other ``${...}`` becomes a placeholder.
    """
    text = PLUGIN_TS.read_text(encoding="utf-8")
    start = text.index('<div class="settings-overlay hidden" id="settingsOverlay">')
    end = text.index("<script nonce=", start)
    fragment = text[start:end]
    fragment = re.sub(r'\$\{tl\("([^"]+)"\)\}', r"\1", fragment)
    fragment = re.sub(r"\$\{[^}]*\}", "X", fragment)
    return Dom(fragment)


@dataclass(frozen=True)
class Surface:
    name: str
    dom: Dom
    enable: str
    group: str
    key: str
    toggle: str
    hint: str
    members: tuple[str, ...]


SURFACES = {
    "web": Surface(
        name="web",
        dom=_web_dom(),
        enable="bark-notification-enabled",
        group="bark-settings-fields",
        key="bark-device-key",
        toggle="bark-device-key-toggle",
        hint="bark-device-key-hint",
        members=(
            "bark-url",
            "bark-device-key",
            "bark-icon",
            "bark-action",
            "bark-url-template",
            "test-bark-notification-btn",
        ),
    ),
    "plugin": Surface(
        name="plugin",
        dom=_plugin_dom(),
        enable="notifyBarkEnabled",
        group="settingsBarkFields",
        key="notifyBarkDeviceKey",
        toggle="settingsBarkDeviceKeyToggleBtn",
        hint="settingsBarkDeviceKeyHint",
        members=(
            "notifyBarkUrl",
            "notifyBarkDeviceKey",
            "notifyBarkIcon",
            "notifyBarkAction",
            "notifyBarkUrlTemplate",
            "settingsBarkBaseUrlStatus",
        ),
    ),
}


@pytest.fixture(params=sorted(SURFACES))
def surface(request: pytest.FixtureRequest) -> Surface:
    return SURFACES[request.param]


# --------------------------------------------------------------------------- the markup


class TestMarkup:
    def test_the_checkbox_controls_a_group_that_starts_collapsed(
        self, surface: Surface
    ) -> None:
        box = surface.dom.get(surface.enable)
        group = surface.dom.get(surface.group)
        assert box.tag == "input" and box.attr("type") == "checkbox"
        assert box.attr("aria-controls") == surface.group
        # A group that only JavaScript collapses would flash open on every page load.
        assert group.has("hidden")

    def test_the_checkbox_stays_outside_the_group_it_controls(
        self, surface: Surface
    ) -> None:
        # Inside the group, unticking it would hide the only thing that can tick it again.
        box = surface.dom.get(surface.enable)
        assert not box.inside(surface.dom.get(surface.group))

    def test_every_bark_field_is_inside_the_group(self, surface: Surface) -> None:
        group = surface.dom.get(surface.group)
        for member in surface.members:
            assert surface.dom.get(member).inside(group), f"#{member} is outside"

    def test_the_device_key_is_masked_and_left_alone_by_password_managers(
        self, surface: Surface
    ) -> None:
        key = surface.dom.get(surface.key)
        assert key.tag == "input"
        assert key.attr("type") == "password"
        assert key.attr("autocomplete") == "off"
        assert key.attr("autocapitalize") == "off"
        assert key.attr("spellcheck") == "false"
        assert key.has("data-1p-ignore")
        assert key.attr("data-lpignore") == "true"
        assert key.attr("data-bwignore") == "true"
        # A saved credential never travels in the markup.
        assert key.attr("value") == ""

    def test_the_toggle_is_a_named_button_beside_the_key_with_both_icons(
        self, surface: Surface
    ) -> None:
        key = surface.dom.get(surface.key)
        toggle = surface.dom.get(surface.toggle)
        assert toggle.tag == "button"
        assert toggle.attr("type") == "button"
        assert toggle.attr("aria-controls") == surface.key
        assert toggle.attr("data-state") == "hidden"
        assert toggle.parent is key.parent
        # Its name says what a press does, in the language of the page.
        assert toggle.attr("aria-label")
        assert toggle.attr("title") == toggle.attr("aria-label")
        assert toggle.attr("data-i18n-title")
        icons = [n for n in toggle.descendants() if n.tag == "svg"]
        assert [i.attr("class").split()[-1] for i in icons] == [
            "secret-icon-show",
            "secret-icon-hide",
        ]
        assert all(i.attr("aria-hidden") == "true" for i in icons)

    def test_a_line_under_the_key_says_where_to_copy_it_from(
        self, surface: Surface
    ) -> None:
        key = surface.dom.get(surface.key)
        hint = surface.dom.get(surface.hint)
        assert key.attr("aria-describedby") == surface.hint
        assert hint.attr("data-i18n").lower().endswith("devicekeyhint")

    def test_the_web_key_has_an_accessible_name_of_its_own(self) -> None:
        # The key's label also holds the toggle button, so its name is given explicitly.
        web = SURFACES["web"]
        key = web.dom.get("bark-device-key")
        label = web.dom.get(key.attr("aria-labelledby"))
        assert label.attr("data-i18n") == "settings.barkDeviceKey"

    def test_the_plugin_key_is_labelled_by_a_for_attribute(self) -> None:
        plugin = SURFACES["plugin"]
        labels = [
            n
            for n in plugin.dom.root.descendants()
            if n.tag == "label" and n.attr("for") == "notifyBarkDeviceKey"
        ]
        assert [n.attr("data-i18n") for n in labels] == ["settings.bark.deviceKey"]

    def test_the_plugin_test_button_follows_the_checkbox_not_the_group(self) -> None:
        # It sits in the bottom action row; the script hides it with the group.
        plugin = SURFACES["plugin"]
        button = plugin.dom.get("settingsTestBarkBtn")
        assert not button.inside(plugin.dom.get(plugin.group))


# --------------------------------------------------------------------------- the strings


def _web_strings(language: str) -> dict[str, str]:
    path = WEB_LOCALES / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))["settings"]


def _plugin_strings(language: str) -> dict[str, str]:
    path = PLUGIN_LOCALES / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))["settings"]["bark"]


# (web key, plugin key): the same field on both surfaces
PAIRS = (
    ("barkUrl", "url"),
    ("barkDeviceKey", "deviceKey"),
    ("barkDeviceKeyPlaceholder", "deviceKeyPlaceholder"),
    ("barkDeviceKeyHint", "deviceKeyHint"),
    ("barkDeviceKeyShow", "deviceKeyShow"),
    ("barkDeviceKeyHide", "deviceKeyHide"),
    ("barkIconUrl", "icon"),
    ("barkAction", "action"),
    ("barkActionNone", "actionNone"),
    ("barkActionUrl", "actionUrl"),
    ("barkActionCopy", "actionCopy"),
    ("barkUrlTemplate", "urlTemplate"),
)
FIELD_LABELS = (
    ("barkUrl", "url"),
    ("barkDeviceKey", "deviceKey"),
    ("barkIconUrl", "icon"),
    ("barkAction", "action"),
    ("barkUrlTemplate", "urlTemplate"),
)


class TestStrings:
    @pytest.mark.parametrize("language", LANGUAGES)
    def test_field_labels_do_not_repeat_the_product_name(self, language: str) -> None:
        web, plugin = _web_strings(language), _plugin_strings(language)
        for web_key, plugin_key in FIELD_LABELS:
            assert "bark" not in web[web_key].lower(), web_key
            assert "bark" not in plugin[plugin_key].lower(), plugin_key

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_both_surfaces_use_the_same_words(self, language: str) -> None:
        web, plugin = _web_strings(language), _plugin_strings(language)
        for web_key, plugin_key in PAIRS:
            assert web[web_key] == plugin[plugin_key], (web_key, plugin_key)

    @pytest.mark.parametrize("language", ("zh-CN", "zh-TW"))
    def test_the_chinese_pages_are_not_left_in_english(self, language: str) -> None:
        plugin = _plugin_strings(language)
        for key in (
            "url",
            "deviceKey",
            "deviceKeyPlaceholder",
            "deviceKeyHint",
            "deviceKeyShow",
            "deviceKeyHide",
            "icon",
            "action",
            "actionNone",
            "actionUrl",
            "urlTemplate",
        ):
            assert CJK.search(plugin[key]), f"settings.bark.{key} is {plugin[key]!r}"
            assert plugin[key] != _plugin_strings("en")[key]

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_show_and_hide_name_the_key_and_differ(self, language: str) -> None:
        plugin = _plugin_strings(language)
        show, hide = plugin["deviceKeyShow"], plugin["deviceKeyHide"]
        assert show and hide and show != hide
        assert "Key" in show and "Key" in hide

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_the_hint_names_the_app_and_the_address_the_key_sits_in(
        self, language: str
    ) -> None:
        for hint in (
            _web_strings(language)["barkDeviceKeyHint"],
            _plugin_strings(language)["deviceKeyHint"],
        ):
            assert "Bark" in hint and "https://api.day.app/" in hint

    def test_the_web_wiring_passes_the_label_keys_through_the_translation_layer(
        self,
    ) -> None:
        html = WEB_HTML.read_text(encoding="utf-8")
        for key in (
            "settings.barkDeviceKey",
            "settings.barkDeviceKeyHint",
            "settings.barkDeviceKeyPlaceholder",
            "settings.barkDeviceKeyShow",
        ):
            assert f'"{key}"' in html, key


# --------------------------------------------------------------------------- the styles


def _has(pattern: str, css: str) -> bool:
    return re.search(pattern, css) is not None


class TestStyles:
    @pytest.mark.parametrize("sheet", [WEB_CSS, PLUGIN_CSS], ids=["web", "plugin"])
    def test_hidden_beats_any_display_the_group_is_given(self, sheet: Path) -> None:
        # The plugin's group is a flex column; only an !important [hidden] collapses it.
        css = sheet.read_text(encoding="utf-8")
        assert _has(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", css)

    @pytest.mark.parametrize(
        ("sheet", "toggle"),
        [(WEB_CSS, ".secret-field-toggle"), (PLUGIN_CSS, ".settings-secret-toggle")],
        ids=["web", "plugin"],
    )
    def test_the_eye_icon_follows_the_state_attribute(
        self, sheet: Path, toggle: str
    ) -> None:
        css = sheet.read_text(encoding="utf-8")
        name = re.escape(toggle)
        # Eye-off is hidden, and so is the eye once the key is shown ...
        assert _has(
            rf"{name}\s+\.secret-icon-hide,\s*"
            rf'{name}\[data-state="shown"\]\s+\.secret-icon-show\s*\{{'
            r"\s*display:\s*none",
            css,
        )
        # ... and then the eye-off takes its place.
        assert _has(
            rf'{name}\[data-state="shown"\]\s+\.secret-icon-hide\s*\{{'
            r"\s*display:\s*(?!none)\w+",
            css,
        )

    def test_the_web_toggle_keeps_its_size_on_a_narrow_screen(self) -> None:
        # ``.btn`` is 100% wide below 768px; a single-class rule lost to it and the
        # toggle swallowed the row (the key field shrank to 34px at 390px).
        css = WEB_CSS.read_text(encoding="utf-8")
        assert _has(
            r"\.secret-field-row\s+\.secret-field-toggle\.btn\s*\{[^}]*\bwidth:\s*auto",
            css,
        )

    @pytest.mark.parametrize(
        ("sheet", "row", "field"),
        [
            (WEB_CSS, r"\.secret-field-row", r"\.setting-input"),
            (PLUGIN_CSS, r"\.settings-secret-row", r'input\[type="password"\]'),
        ],
        ids=["web", "plugin"],
    )
    def test_the_key_field_takes_the_rest_of_the_row(
        self, sheet: Path, row: str, field: str
    ) -> None:
        css = sheet.read_text(encoding="utf-8")
        assert _has(rf"{row}\s*\{{[^}}]*display:\s*flex", css)
        assert _has(rf"{row}\s+{field}\s*\{{[^}}]*flex:\s*1[^}}]*min-width:\s*0", css)


# --------------------------------------------------------------------------- the web script

WEB_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(__PATH__, "utf8");
const absent = new Set(__ABSENT__);
const translate = __TRANSLATE__;
const elements = new Map();
const documentListeners = [];
const elementListeners = [];
const updates = [];

class FakeElement {
  constructor(id) {
    this.id = id;
    this.hidden = false;
    this.type = "";
    this.checked = false;
    this.value = "";
    this.textContent = "";
    this.innerHTML = "";
    this.disabled = false;
    this.inert = false;
    this.files = [];
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.offsetParent = {};
    this.classList = { add() {}, remove() {}, contains() { return false; }, toggle() {} };
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name] : null;
  }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, handler) { elementListeners.push({ id: this.id, type, handler }); }
  appendChild() {}
  blur() {}
  focus() {}
  contains(other) { return other === this; }
  querySelector() { return { textContent: "" }; }
  querySelectorAll() { return []; }
}

function getElement(id) {
  if (!elements.has(id)) elements.set(id, new FakeElement(id));
  return elements.get(id);
}

const sandbox = {
  Array, Boolean, Error, JSON, Map, Math, Number, Object, Promise, RegExp, Set, String,
  console: { debug() {}, error() {}, info() {}, log() {}, warn() {} },
  document: {
    activeElement: null,
    body: { appendChild() {}, removeChild() {} },
    addEventListener(type, handler) { documentListeners.push({ type, handler }); },
    removeEventListener() {},
    contains() { return false; },
    createElement() { return new FakeElement("created"); },
    execCommand() { return true; },
    getElementById(id) { return absent.has(id) ? null : getElement(id); },
    querySelector(selector) { return getElement(selector); },
    querySelectorAll() { return []; },
  },
  fetch() {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: "success", config: {} }) });
  },
  localStorage: { getItem() { return null; }, setItem() {} },
  module: { exports: {} },
  exports: {},
  notificationManager: {
    clearCustomSound() { return Promise.resolve({ success: true }); },
    getCustomSoundMeta() { return null; },
    playSound() { return Promise.resolve(); },
    saveCustomSoundFromFile() { return Promise.resolve({ success: true }); },
  },
  setTimeout(fn) { return { fn }; },
  clearTimeout() {},
  showStatus() {},
  t(key) { return key; },
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.addEventListener = () => {};
if (translate) {
  sandbox.AIIA_I18N = {
    t: (key) => "T:" + key,
    getLang: () => "en",
  };
}
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const { SettingsManager } = sandbox.module.exports;

const fire = (type, target) => {
  for (const l of documentListeners.filter((x) => x.type === type)) l.handler({ target });
};
const press = (id) => {
  const handlers = elementListeners.filter((x) => x.id === id && x.type === "click");
  for (const l of handlers) l.handler({ target: getElement(id), preventDefault() {}, stopPropagation() {} });
  return handlers.length;
};
const tick = () => {
  const fields = getElement("bark-settings-fields");
  const key = getElement("bark-device-key");
  const toggle = getElement("bark-device-key-toggle");
  return {
    fieldsHidden: fields.hidden,
    keyType: key.type,
    state: toggle.getAttribute("data-state"),
    label: toggle.getAttribute("aria-label"),
    title: toggle.getAttribute("title"),
    i18nTitle: toggle.getAttribute("data-i18n-title"),
    i18nLabel: toggle.getAttribute("data-i18n-aria-label"),
  };
};
const fresh = (barkEnabled) => {
  // The markup's defaults: a masked key and a toggle that offers to show it.
  getElement("bark-device-key").type = "password";
  getElement("bark-device-key-toggle").setAttribute("data-state", "hidden");
  const manager = new SettingsManager();
  manager.updateSetting = (name, value) => { updates.push([name, value]); };
  manager.settings = Object.assign({}, manager.defaultSettings, { barkEnabled });
  manager.initEventListeners();
  return manager;
};

(async () => {
__CASE__
})().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""

PLUGIN_HARNESS = r"""
const vm = require("vm");
const source = __SOURCE__;
const absent = new Set(__ABSENT__);
const translate = __TRANSLATE__;
const saves = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class ClassList {
  constructor() { this.values = new Set(); }
  add(value) { this.values.add(value); }
  remove(value) { this.values.delete(value); }
  contains(value) { return this.values.has(value); }
  toggle(value, force) {
    const on = force === undefined ? !this.values.has(value) : force;
    if (on) this.values.add(value); else this.values.delete(value);
    return on;
  }
}

class TestElement {
  constructor(id) {
    this.id = id;
    this.checked = false;
    this.hidden = false;
    this.type = "";
    this.value = "";
    this.textContent = "";
    this.title = "";
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.classList = new ClassList();
  }
  addEventListener(type, handler) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(handler);
  }
  dispatch(type, event) {
    const payload = Object.assign(
      { target: this, preventDefault() {}, stopPropagation() {} }, event || {},
    );
    for (const handler of this.listeners[type] || []) handler(payload);
  }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name] : null;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
  removeAttribute(name) { delete this.attributes[name]; }
  querySelectorAll() { return []; }
}

const elements = {};
function element(id) {
  if (!elements[id]) elements[id] = new TestElement(id);
  return elements[id];
}
element("aiia-config").setAttribute("data-server-url", "http://server");
element("settingsOverlay").classList.add("hidden");
for (const id of [
  "settingsPanel", "settingsHint", "notifyEnabled", "notifyMacOSNativeEnabled",
  "notifyBarkEnabled", "notifyBarkUrl", "notifyBarkDeviceKey", "notifyBarkIcon",
  "notifyBarkAction", "notifyBarkUrlTemplate", "settingsBarkFields",
  "settingsTestBarkBtn", "settingsBarkDeviceKeyToggleBtn",
]) element(id);
// The markup as the host renders it.
element("notifyBarkDeviceKey").type = "password";
element("settingsBarkDeviceKeyToggleBtn").setAttribute("data-state", "hidden");
element("settingsBarkDeviceKeyToggleBtn").setAttribute("aria-label", "Show Device Key");
element("settingsBarkDeviceKeyToggleBtn").setAttribute("title", "Show Device Key");

let cachedSettings = Object.assign({
  enabled: false, macosNativeEnabled: false, barkEnabled: false,
  barkUrl: "https://api.day.app/push", barkDeviceKey: "", barkIcon: "",
  barkAction: "none", barkUrlTemplate: "{base_url}/?task_id={task_id}",
}, __SETTINGS__);

function response(payload) {
  return { ok: true, status: 200, json: async () => payload };
}

const context = {
  console: { debug() {}, warn() {}, error() {} },
  document: {
    getElementById(id) {
      if (absent.has(id)) return null;
      return Object.prototype.hasOwnProperty.call(elements, id) ? elements[id] : null;
    },
    querySelectorAll() { return []; },
    createElement(tag) { return new TestElement(tag); },
    body: { appendChild() {}, removeChild() {} },
    execCommand() { return true; },
  },
  navigator: {},
  setTimeout(fn, ms, ...args) { return setTimeout(fn, Math.min(ms || 0, 20), ...args); },
  clearTimeout,
  setInterval,
  clearInterval,
  fetch(url, options) {
    if (String(url).endsWith("/api/update-notification-config")) {
      saves.push(JSON.parse(options.body));
      return Promise.resolve(response({ status: "success" }));
    }
    return Promise.resolve(response({ status: "success", config: {} }));
  },
  __AIIA_showToast() {},
  AIIA_I18N: { t: (key) => (translate ? "T:" + key : key) },
  AIIAWebviewNotifyCore: {
    refreshNotificationSettingsFromServer: async () => ({ ok: true, settings: cachedSettings }),
    getCachedNotificationSettings: () => cachedSettings,
    setCachedNotificationSettings(next) { cachedSettings = Object.assign({}, next || {}); },
  },
};
context.globalThis = context;
context.window = context;
vm.runInNewContext(source, context, { filename: "webview-settings-ui.js" });
const api = context.AIIAWebviewSettingsUi;

const panel = () => element("settingsPanel");
const box = () => element("notifyBarkEnabled");
const choose = (checked, type) => {
  box().checked = checked;
  panel().dispatch(type || "change", { target: box() });
};
const press = () => element("settingsBarkDeviceKeyToggleBtn").dispatch("click");
const tick = () => {
  const toggle = element("settingsBarkDeviceKeyToggleBtn");
  return {
    fieldsHidden: element("settingsBarkFields").hidden,
    testHidden: element("settingsTestBarkBtn").hidden,
    keyType: element("notifyBarkDeviceKey").type,
    state: toggle.getAttribute("data-state"),
    label: toggle.getAttribute("aria-label"),
    title: toggle.getAttribute("title"),
    i18nTitle: toggle.getAttribute("data-i18n-title"),
  };
};

(async () => {
__CASE__
  api.dispose();
})().then(
  // Let stdout drain; the unref'd timer only fires if something else keeps the loop alive.
  () => { setTimeout(() => process.exit(0), 300).unref(); },
  (err) => {
    console.error(err && err.stack ? err.stack : err);
    process.exit(1);
  },
);
"""


def _run_node(script: str) -> Any:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


def _web(case: str, *, absent: tuple[str, ...] = (), translate: bool = False) -> Any:
    script = (
        WEB_HARNESS.replace("__PATH__", json.dumps(str(WEB_JS)))
        .replace("__ABSENT__", json.dumps(list(absent)))
        .replace("__TRANSLATE__", json.dumps(translate))
        .replace("__CASE__", textwrap.indent(textwrap.dedent(case), "  "))
    )
    return _run_node(script)


def _plugin(
    case: str,
    *,
    settings: dict[str, Any] | None = None,
    absent: tuple[str, ...] = (),
    translate: bool = False,
) -> Any:
    script = (
        PLUGIN_HARNESS.replace(
            "__SOURCE__", json.dumps(PLUGIN_JS.read_text(encoding="utf-8"))
        )
        .replace("__ABSENT__", json.dumps(list(absent)))
        .replace("__TRANSLATE__", json.dumps(translate))
        .replace("__SETTINGS__", json.dumps(settings or {}))
        .replace("__CASE__", textwrap.indent(textwrap.dedent(case), "  "))
    )
    return _run_node(script)


def _frame(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fieldsHidden": True,
        "keyType": "password",
        "state": "hidden",
    }
    base.update(kwargs)
    return base


@needs_node
class TestWebScript:
    def test_the_saved_setting_decides_whether_the_group_is_open(self) -> None:
        out = _web(
            """
            const off = fresh(false);
            getElement("bark-settings-fields").hidden = false;
            off.updateUI();
            const closed = tick().fieldsHidden;
            const on = fresh(true);
            getElement("bark-settings-fields").hidden = true;
            on.updateUI();
            console.log(JSON.stringify({ closed, open: !tick().fieldsHidden }));
            """
        )
        assert out == {"closed": True, "open": True}

    def test_ticking_the_box_opens_the_group_and_unticking_closes_and_masks_it(
        self,
    ) -> None:
        out = _web(
            """
            fresh(false).updateUI();
            const frames = [tick()];
            fire("change", { id: "bark-notification-enabled", checked: true });
            frames.push(tick());
            press("bark-device-key-toggle");
            frames.push(tick());
            fire("change", { id: "bark-notification-enabled", checked: false });
            frames.push(tick());
            console.log(JSON.stringify({ frames, updates }));
            """
        )
        frames = [
            {k: f[k] for k in ("fieldsHidden", "keyType", "state")}
            for f in out["frames"]
        ]
        assert frames == [
            _frame(),
            _frame(fieldsHidden=False),
            _frame(fieldsHidden=False, keyType="text", state="shown"),
            _frame(),
        ]
        # The box is still saved as before: once per change, in this order.
        assert out["updates"] == [["barkEnabled", True], ["barkEnabled", False]]

    def test_the_toggle_reveals_and_masks_and_saves_nothing(self) -> None:
        out = _web(
            """
            fresh(true).updateUI();
            const wired = press("bark-device-key-toggle") > 0;
            const shown = tick();
            press("bark-device-key-toggle");
            const masked = tick();
            console.log(JSON.stringify({ wired, shown, masked, updates }));
            """
        )
        assert out["shown"]["keyType"] == "text"
        assert out["shown"]["state"] == "shown"
        assert out["shown"]["label"] == "Hide Device Key"
        assert out["shown"]["title"] == "Hide Device Key"
        assert out["shown"]["i18nTitle"] == "settings.barkDeviceKeyHide"
        assert out["shown"]["i18nLabel"] == "settings.barkDeviceKeyHide"
        assert out["masked"]["keyType"] == "password"
        assert out["masked"]["state"] == "hidden"
        assert out["masked"]["label"] == "Show Device Key"
        assert out["masked"]["i18nTitle"] == "settings.barkDeviceKeyShow"
        assert out["updates"] == []

    def test_the_toggle_label_is_translated_when_a_translation_exists(self) -> None:
        out = _web(
            """
            fresh(true).updateUI();
            press("bark-device-key-toggle");
            console.log(JSON.stringify(tick()));
            """,
            translate=True,
        )
        assert out["label"] == "T:settings.barkDeviceKeyHide"
        assert out["title"] == "T:settings.barkDeviceKeyHide"

    def test_a_revealed_key_is_masked_again_when_the_panel_closes(self) -> None:
        out = _web(
            """
            const manager = fresh(true);
            manager.updateUI();
            press("bark-device-key-toggle");
            const open = tick().keyType;
            manager.hideSettings();
            console.log(JSON.stringify({ open, closed: tick() }));
            """
        )
        assert out["open"] == "text"
        assert out["closed"]["keyType"] == "password"
        assert out["closed"]["state"] == "hidden"
        assert out["closed"]["fieldsHidden"] is False

    def test_a_page_without_the_group_still_works(self) -> None:
        out = _web(
            """
            const manager = fresh(true);
            manager.updateUI();
            fire("change", { id: "bark-notification-enabled", checked: false });
            manager.hideSettings();
            console.log(JSON.stringify({ ok: true, updates }));
            """,
            absent=(
                "bark-settings-fields",
                "bark-device-key",
                "bark-device-key-toggle",
            ),
        )
        assert out == {"ok": True, "updates": [["barkEnabled", False]]}


# ------------------------------------------------------------------------- the plugin script


@needs_node
class TestPluginScript:
    def test_the_saved_setting_decides_whether_the_group_is_open(self) -> None:
        closed = _plugin(
            """
            element("settingsBarkFields").hidden = false;
            element("settingsTestBarkBtn").hidden = false;
            await api.openSettings();
            console.log(JSON.stringify(tick()));
            """
        )
        opened = _plugin(
            """
            element("settingsBarkFields").hidden = true;
            element("settingsTestBarkBtn").hidden = true;
            await api.openSettings();
            console.log(JSON.stringify(tick()));
            """,
            settings={"barkEnabled": True},
        )
        assert (closed["fieldsHidden"], closed["testHidden"]) == (True, True)
        assert (opened["fieldsHidden"], opened["testHidden"]) == (False, False)

    def test_ticking_the_box_opens_the_group_and_unticking_closes_and_masks_it(
        self,
    ) -> None:
        out = _plugin(
            """
            await api.openSettings();
            const frames = [tick()];
            choose(true);
            frames.push(tick());
            press();
            frames.push(tick());
            choose(false);
            frames.push(tick());
            choose(true, "input");
            frames.push(tick());
            console.log(JSON.stringify(frames));
            """
        )
        assert [(f["fieldsHidden"], f["testHidden"], f["keyType"]) for f in out] == [
            (True, True, "password"),
            (False, False, "password"),
            (False, False, "text"),
            (True, True, "password"),
            (False, False, "password"),
        ]
        assert out[3]["state"] == "hidden"

    def test_the_toggle_reveals_and_masks_and_saves_nothing(self) -> None:
        out = _plugin(
            """
            await api.openSettings();
            choose(true);
            await sleep(80);
            // The form now differs from what was saved, and nothing announced it: a press
            // that reached the autosave would POST it (an unchanged form is never sent).
            element("notifyBarkDeviceKey").value = "typed-without-an-event";
            const before = saves.length;
            press();
            const shown = tick();
            press();
            const masked = tick();
            await sleep(80);
            console.log(JSON.stringify({ shown, masked, extraSaves: saves.length - before }));
            """,
            translate=True,
        )
        assert out["shown"]["keyType"] == "text"
        assert out["shown"]["state"] == "shown"
        assert out["shown"]["label"] == "T:settings.bark.deviceKeyHide"
        assert out["shown"]["title"] == "T:settings.bark.deviceKeyHide"
        assert out["shown"]["i18nTitle"] == "settings.bark.deviceKeyHide"
        assert out["masked"]["keyType"] == "password"
        assert out["masked"]["label"] == "T:settings.bark.deviceKeyShow"
        assert out["masked"]["i18nTitle"] == "settings.bark.deviceKeyShow"
        assert out["extraSaves"] == 0

    def test_an_untranslated_label_is_never_replaced_by_its_key(self) -> None:
        out = _plugin(
            """
            await api.openSettings();
            press();
            console.log(JSON.stringify(tick()));
            """,
        )
        assert out["keyType"] == "text" and out["state"] == "shown"
        assert out["label"] == "Show Device Key"
        assert out["i18nTitle"] == "settings.bark.deviceKeyHide"

    def test_a_revealed_key_is_masked_again_when_the_panel_closes(self) -> None:
        out = _plugin(
            """
            await api.openSettings();
            choose(true);
            press();
            const open = tick().keyType;
            api.closeSettingsOverlay();
            console.log(JSON.stringify({ open, closed: tick() }));
            """
        )
        assert out["open"] == "text"
        assert out["closed"]["keyType"] == "password"
        assert out["closed"]["state"] == "hidden"

    def test_a_refresh_from_the_server_opens_the_group_too(self) -> None:
        out = _plugin(
            """
            await api.openSettings();
            const before = tick().fieldsHidden;
            cachedSettings = Object.assign({}, cachedSettings, { barkEnabled: true });
            await api.refreshNotificationSettingsFromServer();
            console.log(JSON.stringify({ before, after: tick().fieldsHidden }));
            """
        )
        assert out == {"before": True, "after": False}

    def test_a_panel_without_the_group_still_works(self) -> None:
        out = _plugin(
            """
            await api.openSettings();
            choose(true);
            choose(false);
            api.closeSettingsOverlay();
            console.log(JSON.stringify({ ok: true }));
            """,
            absent=(
                "settingsBarkFields",
                "settingsTestBarkBtn",
                "settingsBarkDeviceKeyToggleBtn",
                "notifyBarkDeviceKey",
            ),
        )
        assert out == {"ok": True}
