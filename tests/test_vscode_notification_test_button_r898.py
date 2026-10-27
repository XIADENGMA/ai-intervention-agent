"""R898: "Enable Notifications" on its own must give a notification the user can see.

TODO "界面优化 7": the settings panel of the VS Code extension has "Enable Notifications" and
"macOS Native Notification". With only the first one on, a new task showed a three-second status-bar
message and nothing else -- to the user "no notification".  The extension host now decides what the
in-editor part looks like (the host tests in ``packages/vscode/test/host-notification-delivery.test.js``
run that against a real VS Code); this file pins the half that lives in the panel, which Node can run
without VS Code:

* the panel's new-task event and its test event ask for ``presentation: "auto"`` (they no longer pin the
  status bar), and the test button sends the user's *real* channels, not only the macOS one;
* the hint after the test click says where to look, using the platform the host reports;
* every successful save tells the host to forget its cached notification config.

It also pins the strings and ids that go with the rename (test button, test event, locale keys).
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
VSCODE = REPO_ROOT / "packages" / "vscode"
SETTINGS_UI_JS = VSCODE / "webview-settings-ui.js"
NOTIFY_CORE_JS = VSCODE / "webview-notify-core.js"
WEBVIEW_TS = VSCODE / "webview.ts"
LOCALES = ["en", "zh-CN", "zh-TW"]

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

HARNESS = r"""
const vm = require("vm");
const source = __SOURCE__;
const options = __OPTIONS__;
const posted = [];
const toasts = [];
const timers = [];
const saveRequests = [];

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
class TestElement {
  constructor(id) {
    this.id = id; this.checked = false; this.value = ""; this.textContent = ""; this.title = "";
    this.hidden = false; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.classList = new ClassList();
  }
  addEventListener(type, handler) { (this.listeners[type] = this.listeners[type] || []).push(handler); }
  dispatch(type, event) {
    const payload = Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, event || {});
    for (const handler of this.listeners[type] || []) handler(payload);
  }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : ""; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
  querySelectorAll() { return []; }
}
const elements = {};
function element(id) { return (elements[id] = elements[id] || new TestElement(id)); }
function response(payload, status) { return { ok: !status || status < 400, status: status || 200, json: async () => payload }; }

element("aiia-config").setAttribute("data-server-url", "http://server");
if (options.platform) element("aiia-config").setAttribute("data-host-platform", options.platform);
element("settingsOverlay").classList.add("hidden");
for (const id of ["settingsPanel", "settingsHint", "settingsClose", "settingsTestNotifyBtn", "settingsTestBarkBtn",
  "notifyEnabled", "notifyMacOSNativeEnabled", "notifyBarkEnabled", "notifyBarkUrl", "notifyBarkDeviceKey",
  "notifyBarkIcon", "notifyBarkAction", "notifyBarkUrlTemplate"]) element(id);

let cachedSettings = { enabled: false, macosNativeEnabled: false, barkEnabled: false, barkUrl: "https://api.day.app/push",
  barkDeviceKey: "", barkIcon: "", barkAction: "none", barkUrlTemplate: "{base_url}/?task_id={task_id}" };

const context = {
  AbortController,
  console: { debug() {}, warn() {}, error() {} },
  document: {
    getElementById: (id) => (Object.prototype.hasOwnProperty.call(elements, id) ? elements[id] : null),
    querySelectorAll: () => [],
    createElement: (tag) => new TestElement(tag),
    body: { appendChild() {}, removeChild() {} },
  },
  navigator: {},
  setTimeout(fn, ms, ...args) { const id = "timer-" + (timers.length + 1); timers.push({ id, fn, ms, args, cleared: false, ran: false }); return id; },
  clearTimeout(id) { const t = timers.find((e) => e.id === id); if (t) t.cleared = true; },
  setInterval() { return "interval"; },
  clearInterval() {},
  fetch(url, opts) {
    const u = String(url);
    if (u.endsWith("/api/update-notification-config")) {
      saveRequests.push({ url: u, body: JSON.parse(opts.body) });
      return Promise.resolve(response({ status: options.saveStatus === 200 ? "success" : "error", message: "boom" }, options.saveStatus));
    }
    if (u.endsWith("/api/get-feedback-prompts")) return Promise.resolve(response({ status: "success", config: {} }));
    return Promise.resolve(response({ status: "success" }));
  },
  __AIIA_showToast(text, opts) { toasts.push({ text: String(text), kind: opts && opts.kind }); },
  AIIA_I18N: { t: (key) => key },
  AIIAWebviewNotifyCore: {
    refreshNotificationSettingsFromServer: async () => ({ ok: true, settings: cachedSettings }),
    getCachedNotificationSettings: () => cachedSettings,
    setCachedNotificationSettings(next) { cachedSettings = Object.assign({}, next || {}); },
  },
};
if (options.vscodeApi) context.__AIIA_VSCODE_API = { postMessage(m) { posted.push(m); } };
context.globalThis = context;
context.window = context;
context.__posted = posted;
context.__toasts = toasts;
context.__timers = timers;
context.__saveRequests = saveRequests;
context.__element = element;
vm.runInNewContext(source, context, { filename: "webview-settings-ui.js" });
(async () => { process.stdout.write(String(await vm.runInNewContext(__CASE__, context))); })().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""


def _run(case_js: str, **options: Any) -> dict[str, Any]:
    opts = {"platform": None, "vscodeApi": True, "saveStatus": 200}
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
        ["node", "-e", script], capture_output=True, check=False, text=True, timeout=20
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    return json.loads(proc.stdout)


CLICK_TEST = """
    await AIIAWebviewSettingsUi.openSettings();
    __element("notifyEnabled").checked = __ENABLED__;
    __element("notifyMacOSNativeEnabled").checked = __NATIVE__;
    __element("settingsTestNotifyBtn").dispatch("click");
    return JSON.stringify({
      posted: __posted.filter((m) => m.type === "notify"),
      toasts: __toasts.filter((t) => !t.text.startsWith("settings.hint.synced")),
    });
"""


def _click_test(*, enabled: bool, native: bool, **options: Any) -> dict[str, Any]:
    case = CLICK_TEST.replace("__ENABLED__", json.dumps(enabled)).replace(
        "__NATIVE__", json.dumps(native)
    )
    return _run(case, **options)


# --- the test button -------------------------------------------------------------------------


def test_banner_off_the_test_goes_to_vscode_and_says_where_to_look() -> None:
    out = _click_test(enabled=True, native=False, platform="darwin")
    (msg,) = out["posted"]
    event = msg["event"]
    assert event["types"] == ["vscode"]
    assert event["metadata"]["presentation"] == "auto"
    assert event["metadata"]["isTest"] is True
    assert event["metadata"]["kind"] == "test_notification"
    assert event["title"] == "settings.test.title"
    assert event["message"] == "settings.test.message"
    assert [t["text"] for t in out["toasts"]][-1] == "settings.hint.testInAppSent"


def test_banner_on_on_macos_the_test_includes_the_banner_and_points_at_system_notifications() -> (
    None
):
    out = _click_test(enabled=True, native=True, platform="darwin")
    (msg,) = out["posted"]
    assert msg["event"]["types"] == ["vscode", "macos_native"]
    assert msg["event"]["metadata"]["presentation"] == "auto"
    assert msg["event"]["metadata"]["diagnostic"] is True
    assert [t["text"] for t in out["toasts"]][-1] == "settings.hint.macosTestTriggered"


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_banner_on_but_the_host_is_not_macos_the_hint_points_at_vscode(
    platform: str,
) -> None:
    out = _click_test(enabled=True, native=True, platform=platform)
    (msg,) = out["posted"]
    # the host drops "macos_native" when it cannot show it; the panel only has to be honest in its hint
    assert msg["event"]["types"] == ["vscode", "macos_native"]
    assert [t["text"] for t in out["toasts"]][-1] == "settings.hint.testInAppSent"


def test_unknown_platform_is_treated_like_macos() -> None:
    out = _click_test(enabled=True, native=True, platform=None)
    assert [t["text"] for t in out["toasts"]][-1] == "settings.hint.macosTestTriggered"


def test_notifications_off_nothing_is_sent_and_the_hint_is_an_error() -> None:
    for native in (True, False):
        out = _click_test(enabled=False, native=native, platform="darwin")
        assert out["posted"] == []
        assert out["toasts"][-1] == {
            "text": "settings.hint.notifyDisabled",
            "kind": "error",
        }


def test_without_a_host_connection_the_failure_is_reported() -> None:
    out = _click_test(enabled=True, native=False, vscodeApi=False)
    assert out["posted"] == []
    assert out["toasts"][-1] == {"text": "settings.hint.postFailed", "kind": "error"}


def test_the_test_event_has_a_stable_dedupe_key() -> None:
    out = _click_test(enabled=True, native=False, platform="darwin")
    assert out["posted"][0]["event"]["dedupeKey"] == "test:notification"


# --- saving tells the host ---------------------------------------------------------------------

SAVE = """
    await AIIAWebviewSettingsUi.openSettings();
    __element("notifyEnabled").checked = true;
    __element("settingsPanel").dispatch("change", { target: __element("notifyEnabled") });
    const timer = __timers.find((t) => t.ms === 500 && !t.cleared && !t.ran);
    timer.ran = true;
    timer.fn();
    for (let i = 0; i < 20; i++) await Promise.resolve();
    return JSON.stringify({
      saves: __saveRequests.length,
      posted: __posted.map((m) => m.type),
    });
"""


def test_a_successful_save_tells_the_host_to_forget_its_cached_config() -> None:
    out = _run(SAVE, saveStatus=200)
    assert out["saves"] == 1
    assert out["posted"] == ["notificationSettingsChanged"]


def test_a_failed_save_does_not() -> None:
    out = _run(SAVE, saveStatus=500)
    assert out["saves"] == 1
    assert "notificationSettingsChanged" not in out["posted"]


# --- sources and strings --------------------------------------------------------------------


def _locale(lang: str) -> dict[str, Any]:
    return json.loads((VSCODE / "locales" / f"{lang}.json").read_text(encoding="utf-8"))


def test_old_native_only_test_is_gone_from_the_sources() -> None:
    ui = SETTINGS_UI_JS.read_text(encoding="utf-8")
    ts = WEBVIEW_TS.read_text(encoding="utf-8")
    for needle in (
        "testMacOSNativeNotification",
        "test_macos_native",
        "settingsTestNativeBtn",
        "macosNotEnabled",
    ):
        assert needle not in ui, needle
        assert needle not in ts, needle
    assert 'id="settingsTestNotifyBtn"' in ts
    assert 'kind: "test_notification"' in ui


def test_new_task_events_ask_for_auto_presentation_everywhere() -> None:
    core = NOTIFY_CORE_JS.read_text(encoding="utf-8")
    block = core[
        core.index("kind: 'new_tasks'") - 200 : core.index("kind: 'new_tasks'")
    ]
    assert "presentation: 'auto'" in block
    ts = WEBVIEW_TS.read_text(encoding="utf-8")
    m = re.search(
        r'presentation: "(\w+)",\s+severity: "info",\s+timeoutMs: 3000,\s+isTest: false,\s+kind: "new_tasks"',
        ts,
    )
    assert m and m.group(1) == "auto"


def test_the_host_decides_and_remembers_for_five_seconds() -> None:
    ts = WEBVIEW_TS.read_text(encoding="utf-8")
    assert "const NOTIFICATION_CONFIG_TTL_MS = 5000;" in ts
    assert (
        "NOTIFICATION_CONFIG_TTL_MS" in ts[ts.index("async _fetchNotificationConfig") :]
    )
    assert 'case "notificationSettingsChanged":' in ts
    assert "_resolveNotificationDelivery(rawEvent)" in ts
    assert 'return process.platform === "darwin";' in ts
    assert 'data-host-platform="${hostPlatform}"' in ts


@pytest.mark.parametrize("lang", LOCALES)
def test_locale_keys_follow_the_rename(lang: str) -> None:
    s = _locale(lang)["settings"]
    assert s["testNotify"] and "testNative" not in s
    assert set(s["test"]) == {"title", "message"}
    assert s["hint"]["testInAppSent"] and "macosNotEnabled" not in s["hint"]
    assert s["hint"]["macosTestTriggered"]


def test_the_in_app_hint_differs_per_language_and_is_not_macos_specific() -> None:
    texts = {
        lang: _locale(lang)["settings"]["hint"]["testInAppSent"] for lang in LOCALES
    }
    assert len(set(texts.values())) == 3
    for lang, text in texts.items():
        assert "macOS" not in text, lang
