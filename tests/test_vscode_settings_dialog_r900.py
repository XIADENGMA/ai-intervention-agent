"""R900: the settings page of the VS Code panel behaves like the dialog it is.

TODO "界面优化 8", part 2 (R899 is the structure of the page).  The page is a modal dialog -
``role="dialog" aria-modal="true"`` and a backdrop over the whole panel - but it only looked like one.
Driven by real key events in a real VS Code 1.110.0 (the panel opened through its command):

* focus stayed on the settings button behind the backdrop, so a keyboard user was "inside" a dialog they
  could not reach with Tab, and a screen reader read the page behind it;
* Tab from the last control left the dialog (to the document, then out of the panel), Shift+Tab from the
  first control landed on the settings button behind the backdrop;
* Escape reached the page and did nothing;
* closing the dialog (the X, the backdrop) left focus nowhere, on the page body;
* the messages the dialog raises ("Synced", "Test notification sent", a failed save) are toasts, and the toast
  host was *below* the dialog (z-index 999 against 2000): the real hit-test at the toast's centre returned the
  backdrop;
* the countdown field kept whatever was typed: ``5`` was shown and the server held 10, ``5000`` was shown and
  silently not saved (the server kept the old value), an emptied field stayed empty, and ``1e2`` - 100 in a
  number field - was read as 1 by ``parseInt`` and saved as 10.

Now opening the dialog moves focus into it (the dialog itself, ``tabindex="-1"``) and makes the rest of the page
inert, except the toast host; Tab and Shift+Tab wrap inside; Escape closes (not while an input method is
composing, and not when something else already handled the key); closing gives focus back to what opened the
dialog, or else to the settings button that is on screen (the toolbar has one, the page without a task has its own);
the toast host is above the dialog; the countdown field shows what the server will keep (0 stays 0, anything else is
held to 10..3600 as the server does) and puts back what is not a number, with a message.

The checks: the real ``webview-settings-ui.js`` in Node against a small DOM that models focus, ``inert`` and
document-level key events; the markup the behaviour depends on; the two style rules; the strings; and the
constants the field shares with the server.
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

from ai_intervention_agent.runtime_constants import (
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
)
from tests.test_bark_settings_display_r852 import Dom, Node, _plugin_dom

REPO_ROOT = Path(__file__).resolve().parents[1]
VSCODE = REPO_ROOT / "packages" / "vscode"
SETTINGS_UI_JS = VSCODE / "webview-settings-ui.js"
WEBVIEW_TS = VSCODE / "webview.ts"
WEBVIEW_CSS = VSCODE / "webview.css"
LOCALES = ["en", "zh-CN", "zh-TW"]
CJK = re.compile(r"[\u4e00-\u9fff]")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

HARNESS = r"""
const vm = require("vm");
const source = __SOURCE__;
const options = __OPTIONS__;
const toasts = [];
const timers = [];
const feedbackSaves = [];

class ClassList {
  constructor(values) { this.values = new Set(values || []); }
  add(v) { this.values.add(v); }
  remove(v) { this.values.delete(v); }
  contains(v) { return this.values.has(v); }
  toggle(v, force) {
    if (force === undefined ? !this.values.has(v) : force) { this.values.add(v); return true; }
    this.values.delete(v);
    return false;
  }
}

let activeElement = null;
const docListeners = {};
const elements = {};

class TestElement {
  constructor(id, tagName) {
    this.id = id || "";
    this.tagName = String(tagName || "div").toUpperCase();
    this.checked = false; this._value = ""; this.textContent = ""; this.title = "";
    this.hidden = false; this.disabled = false; this.dataset = {}; this.attributes = {};
    this.listeners = {}; this.classList = new ClassList(); this.style = {};
    this.parent = null; this.children = [];
    this.rendered = true;   // false: display:none, no client rects
    this.attached = true;   // false: removed from the document
    this.tabStops = [];     // what querySelectorAll hands back (the dialog panel only)
    if (id) elements[id] = this;
  }
  get value() { return this._value; }
  set value(v) { this._value = v === null || v === undefined ? "" : String(v); }
  addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); }
  dispatch(type, event) {
    const payload = Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, event || {});
    for (const handler of this.listeners[type] || []) handler(payload);
  }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : ""; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
  querySelectorAll() { return this.tabStops.slice(); }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  isInert() { for (let n = this; n; n = n.parent) if (n.hasAttribute("inert")) return true; return false; }
  contains(other) { for (let n = other; n; n = n.parent) if (n === this) return true; return false; }
  getClientRects() { return this.rendered && this.attached ? [{ width: 1, height: 1 }] : []; }
  focus() {
    // what a browser refuses to focus
    if (!this.attached || !this.rendered || this.disabled || this.isInert()) return;
    activeElement = this;
  }
  blur() { if (activeElement === this) activeElement = null; }
}

// ---- the page: body children as in the panel (boot skeleton, container, toast host, dialog overlay, scripts)
const body = new TestElement("", "body");
const bootSkeleton = body.appendChild(new TestElement("aiiaBootSkeleton"));
const container = body.appendChild(new TestElement("mainContainer"));
const toastHost = body.appendChild(new TestElement("toastHost"));
const overlay = body.appendChild(new TestElement("settingsOverlay"));
const scriptTag = body.appendChild(new TestElement("", "script"));
const alreadyInert = body.appendChild(new TestElement("alreadyInert"));
alreadyInert.setAttribute("inert", "");
overlay.classList.add("hidden");

const toolbarGear = container.appendChild(new TestElement("settingsBtn", "button"));
toolbarGear.rendered = !!options.toolbarGear;
const emptyPageGear = container.appendChild(new TestElement("settingsBtnNoContent", "button"));
const otherControl = container.appendChild(new TestElement("someOtherControl", "button"));

const panel = overlay.appendChild(new TestElement("settingsPanel"));
const control = (id, tag) => panel.appendChild(new TestElement(id, tag || "input"));
// controls that cannot take focus before the first real stop (disabled, `hidden`) and after the last one
// (display:none), so the ends of the Tab loop are only right when what cannot take focus is left out
const disabledFirst = control("disabledFirst", "button"); disabledFirst.disabled = true;
const hiddenFirst = control("hiddenFirst"); hiddenFirst.hidden = true;
const closeBtn = control("settingsClose", "button");
const masterBox = control("notifyEnabled");
const collapsedMiddle = control("collapsedMiddle"); collapsedMiddle.rendered = false;
const countdown = control("feedbackCountdown");
const openConfig = control("settingsOpenConfigBtn", "button");
const footerLink = control("settingsFooterLink", "a");
const collapsedLast = control("collapsedLast", "button"); collapsedLast.rendered = false;
panel.tabStops = [disabledFirst, hiddenFirst, closeBtn, masterBox, collapsedMiddle, countdown, openConfig, footerLink, collapsedLast];
for (const id of ["settingsHint", "notifyMacOSNativeEnabled", "notifyBarkEnabled", "settingsTestNotifyBtn"]) new TestElement(id);

new TestElement("aiia-config").setAttribute("data-server-url", "http://server");

let cachedSettings = { enabled: true, macosNativeEnabled: false, barkEnabled: false, barkUrl: "https://api.day.app/push",
  barkDeviceKey: "", barkIcon: "", barkAction: "none", barkUrlTemplate: "{base_url}/?task_id={task_id}" };

let serverCountdown = options.serverCountdown;
function response(payload, status) { return { ok: !status || status < 400, status: status || 200, json: async () => payload }; }

const context = {
  AbortController,
  console: { debug() {}, warn() {}, error() {} },
  document: {
    getElementById: (id) => (Object.prototype.hasOwnProperty.call(elements, id) ? elements[id] : null),
    querySelectorAll: () => [],
    createElement: (tag) => new TestElement("", tag),
    body,
    get activeElement() { return activeElement || body; },
    contains: (el) => body.contains(el) && el.attached !== false,
    addEventListener(type, handler) { (docListeners[type] = docListeners[type] || []).push(handler); },
  },
  navigator: {},
  setTimeout(fn, ms, ...args) { const id = "timer-" + (timers.length + 1); timers.push({ id, fn, ms, args, cleared: false, fired: false }); return id; },
  clearTimeout(id) { const t = timers.find((e) => e.id === id); if (t) t.cleared = true; },
  setInterval() { return "interval"; },
  clearInterval() {},
  fetch(url, opts) {
    const u = String(url);
    if (u.endsWith("/api/update-feedback-config")) {
      const body = JSON.parse(opts.body);
      feedbackSaves.push(body);
      if (typeof body.frontend_countdown === "number") {
        serverCountdown = body.frontend_countdown === 0 ? 0 : Math.min(3600, Math.max(10, body.frontend_countdown));
      }
      return Promise.resolve(response({ status: "success" }));
    }
    if (u.endsWith("/api/get-feedback-prompts")) {
      return Promise.resolve(response({ status: "success", config: { frontend_countdown: serverCountdown, resubmit_prompt: "", prompt_suffix: "" } }));
    }
    return Promise.resolve(response({ status: "success" }));
  },
  __AIIA_showToast(text, opts) { toasts.push({ text: String(text), kind: opts && opts.kind }); },
  AIIA_I18N: { t: (key) => key },
  AIIAWebviewNotifyCore: {
    refreshNotificationSettingsFromServer: async () => ({ ok: true, settings: cachedSettings }),
    getCachedNotificationSettings: () => cachedSettings,
    setCachedNotificationSettings(next) { cachedSettings = Object.assign({}, next || {}); },
  },
  __AIIA_VSCODE_API: { postMessage() {} },
};
context.globalThis = context;
context.window = context;
context.__toasts = toasts;
context.__timers = timers;
context.__feedbackSaves = feedbackSaves;
context.__e = elements;
context.__body = body;
context.__setActive = (el) => { activeElement = el; };
context.__active = () => (activeElement ? (activeElement.id || activeElement.tagName) : "body");
context.__keydown = (props) => {
  const event = Object.assign({ key: "", shiftKey: false, isComposing: false, keyCode: 0, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; } }, props);
  for (const handler of docListeners.keydown || []) handler(event);
  return event;
};
context.__inert = () => body.children.filter((c) => c.hasAttribute("inert")).map((c) => c.id || c.tagName.toLowerCase());
// run the debounced saves now (the dialog stays open, as when a user types and moves on)
context.__flushSaves = () => {
  for (const t of timers) {
    if (t.cleared || t.fired || t.ms !== 800) continue;
    t.fired = true;
    t.fn(...t.args);
  }
};
context.__settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
vm.runInNewContext(source, context, { filename: "webview-settings-ui.js" });
(async () => { process.stdout.write(String(await vm.runInNewContext(__CASE__, context))); })().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""


def _run(case_js: str, **options: Any) -> Any:
    opts: dict[str, Any] = {"toolbarGear": False, "serverCountdown": 240}
    opts.update(options)
    script = (
        HARNESS.replace(
            "__SOURCE__", json.dumps(SETTINGS_UI_JS.read_text(encoding="utf-8"))
        )
        .replace("__OPTIONS__", json.dumps(opts))
        .replace(
            "__CASE__",
            json.dumps(
                "(async () => {\n"
                + textwrap.indent(textwrap.dedent(case_js), "  ")
                + "\n})()"
            ),
        )
    )
    proc = subprocess.run(
        ["node", "-e", script], capture_output=True, check=False, text=True, timeout=30
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    return json.loads(proc.stdout)


OPEN = """
    __setActive(__e.settingsBtnNoContent);
    await AIIAWebviewSettingsUi.openSettings();
    await __settle();
"""


# --- opening ---------------------------------------------------------------------------------------


@needs_node
def test_opening_moves_focus_into_the_dialog_and_makes_the_page_behind_inert() -> None:
    out = _run(
        OPEN
        + """
        return JSON.stringify({ active: __active(), inert: __inert(),
          overlayHidden: __e.settingsOverlay.classList.contains("hidden") });
    """
    )
    assert out["overlayHidden"] is False
    assert out["active"] == "settingsPanel"
    # the boot skeleton and the container; not the toast host, not the dialog, not scripts, not what was inert before
    assert sorted(out["inert"]) == ["aiiaBootSkeleton", "alreadyInert", "mainContainer"]


@needs_node
def test_the_toast_host_and_the_dialog_stay_live_while_it_is_open() -> None:
    out = _run(
        OPEN
        + """
        return JSON.stringify({
          toastHost: __e.toastHost.hasAttribute("inert"),
          overlay: __e.settingsOverlay.hasAttribute("inert"),
          panel: __e.settingsPanel.hasAttribute("inert"),
          script: __body.children.find((c) => c.tagName === "SCRIPT").hasAttribute("inert"),
        });
    """
    )
    assert out == {
        "toastHost": False,
        "overlay": False,
        "panel": False,
        "script": False,
    }


@needs_node
def test_a_part_of_the_page_that_was_inert_before_stays_inert_after_closing() -> None:
    out = _run(
        OPEN
        + """
        AIIAWebviewSettingsUi.closeSettingsOverlay();
        return JSON.stringify({ inert: __inert() });
    """
    )
    assert out["inert"] == ["alreadyInert"]


@needs_node
def test_opening_twice_keeps_the_first_opener() -> None:
    out = _run(
        OPEN
        + """
        await AIIAWebviewSettingsUi.openSettings();   // already open: focus is in the dialog now
        await __settle();
        AIIAWebviewSettingsUi.closeSettingsOverlay();
        return JSON.stringify({ active: __active(), inert: __inert() });
    """
    )
    assert out == {"active": "settingsBtnNoContent", "inert": ["alreadyInert"]}


# --- closing ----------------------------------------------------------------------------------------


@needs_node
def test_closing_gives_focus_back_to_what_opened_the_dialog() -> None:
    out = _run(
        """
        __setActive(__e.someOtherControl);
        await AIIAWebviewSettingsUi.openSettings();
        await __settle();
        const inside = __active();
        AIIAWebviewSettingsUi.closeSettingsOverlay();
        return JSON.stringify({ inside, after: __active() });
    """
    )
    assert out == {"inside": "settingsPanel", "after": "someOtherControl"}


@needs_node
@pytest.mark.parametrize(
    ("toolbar_gear", "expected"),
    [(False, "settingsBtnNoContent"), (True, "settingsBtn")],
)
def test_without_an_opener_focus_goes_to_the_settings_button_that_is_on_screen(
    toolbar_gear: bool, expected: str
) -> None:
    out = _run(
        """
        __setActive(null);            // opened by a message from the host: nothing had focus
        await AIIAWebviewSettingsUi.openSettings();
        await __settle();
        AIIAWebviewSettingsUi.closeSettingsOverlay();
        return JSON.stringify({ after: __active() });
    """,
        toolbarGear=toolbar_gear,
    )
    assert out == {"after": expected}


@needs_node
def test_an_opener_that_is_gone_falls_back_to_the_settings_button() -> None:
    out = _run(
        """
        __setActive(__e.someOtherControl);
        await AIIAWebviewSettingsUi.openSettings();
        await __settle();
        __e.someOtherControl.attached = false;      // the page was re-rendered while the dialog was open
        AIIAWebviewSettingsUi.closeSettingsOverlay();
        return JSON.stringify({ after: __active() });
    """
    )
    assert out == {"after": "settingsBtnNoContent"}


@needs_node
def test_closing_a_closed_dialog_does_not_take_the_focus() -> None:
    out = _run(
        """
        __setActive(__e.someOtherControl);
        AIIAWebviewSettingsUi.closeSettingsOverlay();
        return JSON.stringify({ after: __active(), inert: __inert() });
    """
    )
    assert out == {"after": "someOtherControl", "inert": ["alreadyInert"]}


# --- Escape -----------------------------------------------------------------------------------------


@needs_node
def test_escape_closes_the_dialog_and_hands_focus_back() -> None:
    out = _run(
        OPEN
        + """
        const event = __keydown({ key: "Escape" });
        return JSON.stringify({ prevented: event.defaultPrevented, after: __active(), inert: __inert(),
          hidden: __e.settingsOverlay.classList.contains("hidden") });
    """
    )
    assert out == {
        "prevented": True,
        "after": "settingsBtnNoContent",
        "inert": ["alreadyInert"],
        "hidden": True,
    }


@needs_node
def test_escape_does_nothing_while_the_dialog_is_closed() -> None:
    out = _run(
        """
        await AIIAWebviewSettingsUi.openSettings();
        await __settle();
        AIIAWebviewSettingsUi.closeSettingsOverlay();
        __setActive(__e.someOtherControl);
        const event = __keydown({ key: "Escape" });
        return JSON.stringify({ prevented: event.defaultPrevented, after: __active() });
    """
    )
    assert out == {"prevented": False, "after": "someOtherControl"}


@needs_node
@pytest.mark.parametrize(
    "props",
    [
        {"isComposing": True},
        {"keyCode": 229},
        {"defaultPrevented": True},
    ],
)
def test_escape_that_belongs_to_something_else_leaves_the_dialog_open(
    props: dict[str, Any],
) -> None:
    out = _run(
        OPEN
        + f"""
        __keydown(Object.assign({{ key: "Escape" }}, {json.dumps(props)}));
        return JSON.stringify({{ hidden: __e.settingsOverlay.classList.contains("hidden"), active: __active() }});
    """
    )
    assert out == {"hidden": False, "active": "settingsPanel"}


@needs_node
@pytest.mark.parametrize("key", ["Enter", " ", "a", "ArrowDown", "Esc"])
def test_other_keys_leave_the_dialog_alone(key: str) -> None:
    out = _run(
        OPEN
        + f"""
        const event = __keydown({{ key: {json.dumps(key)} }});
        return JSON.stringify({{ prevented: event.defaultPrevented,
          hidden: __e.settingsOverlay.classList.contains("hidden") }});
    """
    )
    assert out == {"prevented": False, "hidden": False}


# --- Tab stays inside -------------------------------------------------------------------------------

TAB = """
    await AIIAWebviewSettingsUi.openSettings();
    await __settle();
    __setActive(__FROM__);
    const event = __keydown({ key: "Tab", shiftKey: __SHIFT__ });
    return JSON.stringify({ prevented: event.defaultPrevented, active: __active() });
"""


def _tab(start: str | None, shift: bool) -> dict[str, Any]:
    """Press Tab (or Shift+Tab) with focus on ``start`` (an element id; None: the document body)."""
    target = "null" if start is None else f"__e.{start}"
    return _run(TAB.replace("__FROM__", target).replace("__SHIFT__", json.dumps(shift)))


@needs_node
def test_tab_from_the_last_control_wraps_to_the_first() -> None:
    # not to the disabled or `hidden` controls before the close button: the loop skips what cannot take focus
    assert _tab("settingsFooterLink", False) == {
        "prevented": True,
        "active": "settingsClose",
    }


@needs_node
def test_shift_tab_from_the_first_control_wraps_to_the_last() -> None:
    # not to the collapsed Test Bark button after the footer link
    assert _tab("settingsClose", True) == {
        "prevented": True,
        "active": "settingsFooterLink",
    }


@needs_node
def test_shift_tab_from_the_dialog_itself_goes_to_the_last_control() -> None:
    assert _tab("settingsPanel", True) == {
        "prevented": True,
        "active": "settingsFooterLink",
    }


@needs_node
@pytest.mark.parametrize(
    ("start", "shift"),
    [
        ("settingsPanel", False),
        ("settingsClose", False),
        ("notifyEnabled", False),
        ("notifyEnabled", True),
        ("feedbackCountdown", True),
        ("settingsFooterLink", True),
    ],
)
def test_tab_inside_the_dialog_is_left_to_the_browser(start: str, shift: bool) -> None:
    out = _tab(start, shift)
    assert out["prevented"] is False
    assert out["active"] == start  # the harness does not move focus by itself


@needs_node
@pytest.mark.parametrize("start", [None, "someOtherControl"])
@pytest.mark.parametrize("shift", [False, True])
def test_tab_from_outside_the_dialog_is_pulled_back_in(
    start: str | None, shift: bool
) -> None:
    # the document body is where focus is when it has left the dialog (a click on the backdrop, say); the
    # control of the page behind cannot hold focus in a browser (it is inert) but the handler must not depend on that
    out = _tab(start, shift)
    assert out["prevented"] is True
    assert out["active"] == ("settingsFooterLink" if shift else "settingsClose")


@needs_node
def test_a_dialog_without_tab_stops_keeps_focus_on_itself() -> None:
    out = _run(
        """
        await AIIAWebviewSettingsUi.openSettings();
        await __settle();
        __e.settingsPanel.tabStops = [];
        const event = __keydown({ key: "Tab" });
        return JSON.stringify({ prevented: event.defaultPrevented, active: __active() });
    """
    )
    assert out == {"prevented": True, "active": "settingsPanel"}


# --- the countdown ----------------------------------------------------------------------------------

COUNTDOWN = """
    await AIIAWebviewSettingsUi.openSettings();
    await __settle();
    const field = __e.feedbackCountdown;
    const rows = [];
    for (const typed of __TYPED__) {
      field.value = typed;
      const before = __feedbackSaves.length;
      const toastsBefore = __toasts.length;
      field.dispatch("change");
      __flushSaves();
      await __settle();
      rows.push({ typed, field: field.value,
        saved: __feedbackSaves.length > before ? __feedbackSaves[__feedbackSaves.length - 1].frontend_countdown : null,
        toasts: __toasts.slice(toastsBefore).filter((t) => t.text.startsWith("settings.hint.countdown")).map((t) => t.kind) });
    }
    return JSON.stringify(rows);
"""


def _countdown(typed: list[str], **options: Any) -> list[dict[str, Any]]:
    return _run(COUNTDOWN.replace("__TYPED__", json.dumps(typed)), **options)


@needs_node
@pytest.mark.parametrize(
    ("typed", "field", "saved"),
    [
        ("240", "240", 240),
        ("0", "0", 0),
        ("10", "10", 10),
        ("3600", "3600", 3600),
        ("15", "15", 15),
        ("9", "10", 10),
        ("5", "10", 10),
        ("1", "10", 10),
        ("3601", "3600", 3600),
        ("5000", "3600", 3600),
        ("-5", "10", 10),
        ("-0", "0", 0),
        ("15.4", "15", 15),
        ("15.5", "16", 16),
        ("0.4", "10", 10),
        ("1e2", "100", 100),
        ("  42  ", "42", 42),
    ],
)
def test_the_field_shows_what_the_server_will_keep(
    typed: str, field: str, saved: int
) -> None:
    (row,) = _countdown([typed])
    assert row["field"] == field
    assert row["saved"] == saved
    assert row["toasts"] == []


@needs_node
@pytest.mark.parametrize("typed", ["", "   ", "abc", "Infinity", "NaN", "1e999", "--5"])
def test_what_is_not_a_number_is_put_back_and_the_user_is_told(typed: str) -> None:
    (row,) = _countdown([typed], serverCountdown=240)
    assert row["field"] == "240"
    assert row["saved"] is None
    assert row["toasts"] == ["error"]


@needs_node
def test_put_back_means_the_last_value_the_server_took_not_the_first_one() -> None:
    rows = _countdown(["5", "", "300", "abc"], serverCountdown=240)
    assert [(r["field"], r["saved"]) for r in rows] == [
        ("10", 10),
        ("10", None),
        ("300", 300),
        ("300", None),
    ]


@needs_node
def test_the_value_the_server_holds_is_what_gets_put_back_after_a_reload() -> None:
    (row,) = _countdown([""], serverCountdown=0)
    assert row["field"] == "0"
    (row,) = _countdown([""], serverCountdown=1800)
    assert row["field"] == "1800"


@needs_node
def test_after_a_reload_the_value_put_back_is_the_one_saved_before() -> None:
    out = _run(
        OPEN
        + """
        __e.feedbackCountdown.value = "5";
        __e.feedbackCountdown.dispatch("change");
        __flushSaves();
        await __settle();
        AIIAWebviewSettingsUi.closeSettingsOverlay();
        __setActive(__e.settingsBtnNoContent);
        await AIIAWebviewSettingsUi.openSettings();      // loads from the server, which took 10
        await __settle();
        const reloaded = __e.feedbackCountdown.value;
        __e.feedbackCountdown.value = "";
        __e.feedbackCountdown.dispatch("change");
        return JSON.stringify({ reloaded, putBack: __e.feedbackCountdown.value });
    """
    )
    assert out == {"reloaded": "10", "putBack": "10"}


@needs_node
def test_the_field_limits_are_the_servers_limits() -> None:
    source = SETTINGS_UI_JS.read_text(encoding="utf-8")
    low = re.search(r"const FEEDBACK_COUNTDOWN_MIN = (\d+);", source)
    high = re.search(r"const FEEDBACK_COUNTDOWN_MAX = (\d+);", source)
    assert low and high
    assert int(low.group(1)) == AUTO_RESUBMIT_TIMEOUT_MIN
    assert int(high.group(1)) == AUTO_RESUBMIT_TIMEOUT_MAX
    ts = WEBVIEW_TS.read_text(encoding="utf-8")
    m = re.search(
        r'<input type="number" id="feedbackCountdown" min="(\d+)" max="(\d+)"', ts
    )
    assert m
    assert (int(m.group(1)), int(m.group(2))) == (0, AUTO_RESUBMIT_TIMEOUT_MAX)


# --- markup the behaviour depends on ------------------------------------------------------------------


def _body_children() -> list[Node]:
    """Top-level children of ``<body>`` of the panel template, as the panel would render it."""
    text = WEBVIEW_TS.read_text(encoding="utf-8")
    start = text.index("<body")
    end = text.index("<script nonce=", start)
    fragment = text[start:end]
    fragment = re.sub(r'\$\{tl\("([^"]+)"\)\}', r"\1", fragment)
    fragment = re.sub(r"\$\{[^}]*\}", "X", fragment)
    root = Dom(fragment + "</body>").root
    (body,) = [n for n in root.children if n.tag == "body"]
    return body.children


def test_the_dialog_takes_focus_through_tabindex_minus_one(dom: Dom) -> None:
    panel = dom.get("settingsPanel")
    assert panel.attr("tabindex") == "-1"
    assert panel.attr("role") == "dialog" and panel.attr("aria-modal") == "true"


def test_the_page_is_inerted_by_body_children_and_these_are_the_children() -> None:
    children = [c for c in _body_children() if c.tag != "script"]
    ids = [c.attr("id") for c in children]
    # what the inert code relies on: the toast host and the dialog are body-level siblings of the rest of the page
    assert "toastHost" in ids and "settingsOverlay" in ids
    assert any("container" in c.attr("class").split() for c in children)
    assert ids.index("toastHost") < ids.index("settingsOverlay")


def test_both_settings_buttons_exist_for_the_focus_fallback(dom: Dom) -> None:
    text = WEBVIEW_TS.read_text(encoding="utf-8")
    for element_id in ("settingsBtn", "settingsBtnNoContent"):
        assert f'id="{element_id}"' in text
    ui = SETTINGS_UI_JS.read_text(encoding="utf-8")
    assert '["settingsBtn", "settingsBtnNoContent"]' in ui


@pytest.fixture(scope="module")
def dom() -> Dom:
    return _plugin_dom()


# --- styles -------------------------------------------------------------------------------------------


def _z_index(css: str, selector: str) -> int:
    values = [
        int(m.group(1))
        for rule in re.finditer(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
        for m in [re.search(r"z-index:\s*(\d+)", rule.group(1))]
        if m
    ]
    assert values, f"no z-index for {selector}"
    return values[-1]


def test_the_toast_host_is_above_the_settings_dialog() -> None:
    css = WEBVIEW_CSS.read_text(encoding="utf-8")
    assert _z_index(css, ".toast-host") > _z_index(css, ".settings-overlay")


def test_the_dialog_container_shows_no_focus_ring_of_its_own() -> None:
    css = WEBVIEW_CSS.read_text(encoding="utf-8")
    m = re.search(r"(?m)^\.settings-panel:focus\s*\{([^}]*)\}", css)
    assert m and re.search(r"outline:\s*none", m.group(1))


# --- strings ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LOCALES)
def test_the_countdown_message_exists_and_names_the_range(lang: str) -> None:
    loc = json.loads((VSCODE / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    text = loc["settings"]["hint"]["countdownInvalid"]
    assert isinstance(text, str)
    for number in ("10", "3600", "0"):
        assert re.search(rf"(?<!\d){number}(?!\d)", text), (lang, number)
    assert (lang == "en") == (not CJK.search(text))


def test_the_countdown_message_differs_per_language() -> None:
    texts = {
        lang: json.loads(
            (VSCODE / "locales" / f"{lang}.json").read_text(encoding="utf-8")
        )["settings"]["hint"]["countdownInvalid"]
        for lang in LOCALES
    }
    assert len(set(texts.values())) == 3
