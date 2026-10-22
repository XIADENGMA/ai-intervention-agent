"""R810: the copy buttons of the Web UI and the VS Code panel copy through ONE helper.

R808 made the copy button of a fenced code block correct by routing it through
``DOMSecurity.writeTextToClipboard``: the Clipboard API when there is one, the
selection copy (``execCommand('copy')``) when it is missing *or refuses*, a
read-only / fixed / off-screen helper textarea that never stays in the page,
keyboard focus and the page's selection put back, and nothing awaited before the
selection copy (Safari honours ``execCommand('copy')`` only while the click is still
on the stack).  Three other copy buttons kept hand-written copies of that logic, and
the copies were wrong in ways the helper is not:

* ``multi_task.js`` ``_writeToClipboard`` (double-click on a task tab copies the task
  id, Shift+double-click the deep link) left its helper textarea in the page when
  ``execCommand`` threw, and never gave focus and selection back;
* the LAN-URL button of the Web UI settings panel (``settings-manager.js``) tried
  the selection copy *only* when the Clipboard API was missing - a refused API write
  (permission, document not focused) ended in silence - and it flashed "Copied" after
  a selection copy whose result it never looked at;
* the same button restored its label from the text it found at click time, so a
  second click inside the 1.5 s window "restored" the label to "Copied" for good, and
  a language switch in between brought back the old language;
* the LAN-URL button of the VS Code settings panel (``webview-settings-ui.js``) had
  the same stuck label and said nothing at all when the write failed.

The contract: the two Web UI buttons call ``DOMSecurity.writeTextToClipboard`` and
believe its answer - the label says "Copied" only when something was copied and the
failure label (``status.copyFailed``) otherwise.  The label is put back by
translation key, never from a captured string, and a click inside the feedback window
restarts the window instead of racing it.  The VS Code panel has no ``DOMSecurity``
and never lacks the Clipboard API (a webview is a secure context), so its button
writes through ``navigator.clipboard`` only - the same way the code-block button of
that panel does - with the same honest label.  Each bundle ends up with exactly one
selection copy (``dom-security.js``) and the extension with none.

The Node tests run the real ``dom-security.js``, ``multi_task.js`` /
``settings-manager.js`` / ``webview-settings-ui.js`` against a fake DOM.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
VSCODE_DIR = REPO_ROOT / "packages" / "vscode"
DOM_SECURITY_JS = STATIC_JS / "dom-security.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"
SETTINGS_MANAGER_JS = STATIC_JS / "settings-manager.js"
WEBVIEW_SETTINGS_UI_JS = VSCODE_DIR / "webview-settings-ui.js"

NODE_AVAILABLE = shutil.which("node") is not None

# Third-party bundles that legitimately mention clipboard APIs.
VENDORED_WEB_UI = {"tex-mml-chtml.js", "prism.js", "marked.js"}

TEXT = "http://127.0.0.1:8081/?task_id=任务-1&v=🙂"
LAN_URL = "http://192.168.1.23:8081"

SELECTION_COPY_RE = re.compile(r"""execCommand\(\s*['"]copy['"]""")
CLIPBOARD_WRITE_RE = re.compile(r"clipboard\s*\.\s*writeText\s*\(")


def _first_party_scripts(directory: Path, *, vendored: set[str]) -> list[Path]:
    return sorted(
        path
        for path in directory.glob("*.js")
        if not path.name.endswith(".min.js") and path.name not in vendored
    )


def _function_source(source: str, header: str) -> str:
    match = re.search(re.escape(header) + r"[\s\S]*?\n\}\n", source)
    assert match is not None, f"missing {header!r}"
    return match.group(0)


# --------------------------------------------------------------------------------------
# A fake browser shared by every Node case.
# --------------------------------------------------------------------------------------

FAKE_BROWSER = textwrap.dedent(
    """
    const calls = [];
    const execCalls = [];
    const written = [];
    const elements = new Map();
    let execResult = true;
    let execThrows = false;

    class ClassList {
      constructor() { this.values = new Set(); }
      add(...names) { names.forEach((name) => this.values.add(name)); }
      remove(...names) { names.forEach((name) => this.values.delete(name)); }
      contains(name) { return this.values.has(name); }
      toggle(name, force) {
        const on = force === undefined ? !this.values.has(name) : force;
        if (on) this.values.add(name); else this.values.delete(name);
        return on;
      }
    }

    function makeElement(tag) {
      const listeners = {};
      return {
        tagName: String(tag).toUpperCase(),
        value: '',
        textContent: '',
        innerHTML: '',
        title: '',
        hidden: false,
        disabled: false,
        checked: false,
        style: {},
        dataset: {},
        attrs: {},
        parentNode: null,
        span: null,
        classList: new ClassList(),
        setAttribute(name, value) { this.attrs[name] = String(value); },
        getAttribute(name) {
          return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
        },
        removeAttribute(name) { delete this.attrs[name]; },
        hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); },
        addEventListener(type, handler) { listeners[type] = handler; },
        click() { return listeners.click(); },
        querySelector(selector) { return selector === 'span' ? this.span : null; },
        querySelectorAll() { return []; },
        appendChild(child) { return child; },
        blur() {},
        select() {
          calls.push('select');
          document_.activeElement = this;
          fakeSelection.ranges = ['helper-selection'];
        },
        focus() {
          calls.push('focus:' + (this.attrs.id || this.tagName));
          document_.activeElement = this;
        },
      };
    }

    function element(id, tag) {
      if (!elements.has(id)) {
        const created = makeElement(tag || 'div');
        created.attrs.id = id;
        elements.set(id, created);
      }
      return elements.get(id);
    }

    const body = {
      children: [],
      appendChild(el) {
        el.parentNode = this;
        this.children.push(el);
        calls.push('append:' + el.tagName);
        return el;
      },
      removeChild(el) {
        const index = this.children.indexOf(el);
        if (index >= 0) this.children.splice(index, 1);
        el.parentNode = null;
        calls.push('remove:' + el.tagName);
        return el;
      },
    };

    const fakeSelection = {
      ranges: ['range-1', 'range-2'],
      get rangeCount() { return this.ranges.length; },
      getRangeAt(index) { return this.ranges[index]; },
      removeAllRanges() { this.ranges = []; calls.push('selection:clear'); },
      addRange(range) { this.ranges.push(range); calls.push('selection:add:' + range); },
    };

    // Only the 1.5 s feedback timers of the copy buttons are held back; everything
    // else keeps running on real timers.
    const feedbackTimers = [];
    let timerSeq = 0;
    function fakeSetTimeout(fn, delay, ...args) {
      if (delay !== 1500) return setTimeout(fn, delay, ...args);
      timerSeq += 1;
      feedbackTimers.push({ id: timerSeq, fn });
      return timerSeq;
    }
    function fakeClearTimeout(id) {
      const index = feedbackTimers.findIndex((timer) => timer.id === id);
      if (index >= 0) { feedbackTimers.splice(index, 1); return; }
      clearTimeout(id);
    }
    function runFeedbackTimers() {
      while (feedbackTimers.length) feedbackTimers.shift().fn();
    }

    const previous = makeElement('button');
    previous.attrs.id = 'previously-focused';
    const document_ = {
      activeElement: previous,
      body,
      createElement: (tag) => makeElement(tag),
      getElementById: (id) => elements.get(id) || null,
      getSelection: () => fakeSelection,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
      removeEventListener() {},
      contains: () => false,
      execCommand(command) {
        const helper = document_.activeElement;
        execCalls.push({
          command,
          value: helper && helper.tagName === 'TEXTAREA' ? helper.value : null,
          helperInBody: body.children.length,
          readonly: helper && helper.attrs ? helper.attrs.readonly : undefined,
          position: helper && helper.style ? helper.style.position : undefined,
          offscreen: helper && helper.style ? [helper.style.top, helper.style.left] : undefined,
        });
        if (execThrows) throw new Error('execCommand blew up');
        return execResult;
      },
    };

    const report = (extra) => process.stdout.write(JSON.stringify(Object.assign({
      calls, execCalls, written, helpers: body.children.length,
      activeId: document_.activeElement && document_.activeElement.attrs
        ? document_.activeElement.attrs.id : null,
      selection: fakeSelection.ranges,
    }, extra || {})));

    const fail = (error) => {
      console.error(error && error.stack || error);
      process.exit(1);
    };
    """
)

# Navigator expressions (evaluated inside the Node script).
NO_CLIPBOARD = "{}"
WORKING_CLIPBOARD = "{ clipboard: { async writeText(value) { written.push(value); } } }"
REFUSING_CLIPBOARD = (
    "{ clipboard: { async writeText(value) { written.push('refused:' + value);"
    " throw new Error('NotAllowedError'); } } }"
)
THROWING_CLIPBOARD = (
    "{ clipboard: { writeText(value) { written.push('threw:' + value);"
    " throw new Error('SecurityError'); } } }"
)
WRITE_TEXT_MISSING = "{ clipboard: {} }"

TRANSLATIONS = textwrap.dedent(
    """
    const texts = {
      'settings.baseUrlCopyLan': 'Copy LAN URL',
      'settings.baseUrlCopied': 'Copied',
      'status.copyFailed': 'Copy failed',
      'settings.bark.baseUrlCopyLan': 'Copy LAN URL',
      'settings.bark.baseUrlCopied': 'Copied',
      'ui.copy.failed': 'Copy failed',
    };
    const AIIA_I18N = {
      t(key) {
        return Object.prototype.hasOwnProperty.call(texts, key) ? texts[key] : key;
      },
    };
    """
)

STATUS_PAYLOAD = textwrap.dedent(
    """
    const statusPayload = {
      success: true,
      recommendation: 'set_external_base_url',
      is_loopback: true,
      effective_base_url: 'http://127.0.0.1:8081',
      suggested_lan_base_url: LAN_URL,
    };
    function jsonResponse(payload) {
      return { ok: true, status: 200, json: async () => payload };
    }
    """
)


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


def _assemble(template: str, *, navigator_js: str, case_js: str, **json_values) -> str:
    script = template
    for key, value in json_values.items():
        script = script.replace(f"__{key}__", json.dumps(value))
    return (
        script.replace("__FAKE_BROWSER__", FAKE_BROWSER)
        .replace("__TRANSLATIONS__", TRANSLATIONS)
        .replace("__STATUS_PAYLOAD__", STATUS_PAYLOAD)
        .replace("__NAVIGATOR__", navigator_js)
        .replace("__CASE__", textwrap.indent(textwrap.dedent(case_js), "  "))
    )


# --------------------------------------------------------------------------------------
# Runner 1: multi_task.js ``_writeToClipboard`` on top of the real DOMSecurity.
# --------------------------------------------------------------------------------------

WRITE_RUNNER = """
const fs = require('fs');
const vm = require('vm');
__FAKE_BROWSER__
const navigator_ = __NAVIGATOR__;
const TEXT = __TEXT__;
const sandbox = {
  console,
  window: {},
  navigator: navigator_,
  document: document_,
  setTimeout: fakeSetTimeout,
  clearTimeout: fakeClearTimeout,
};
vm.createContext(sandbox);
if (__LOAD_DOM_SECURITY__) {
  vm.runInContext(fs.readFileSync(__DOM_SECURITY_PATH__, 'utf8'), sandbox);
}
vm.runInContext(__WRITE_SOURCE__, sandbox);
const write = (text) => sandbox._writeToClipboard(text);
(async () => {
__CASE__
})().catch(fail);
"""


def _run_write(
    case_js: str, *, navigator_js: str, load_dom_security: bool = True
) -> dict:
    source = MULTI_TASK_JS.read_text(encoding="utf-8")
    return _run_node(
        _assemble(
            WRITE_RUNNER,
            navigator_js=navigator_js,
            case_js=case_js,
            TEXT=TEXT,
            LOAD_DOM_SECURITY=load_dom_security,
            DOM_SECURITY_PATH=str(DOM_SECURITY_JS),
            WRITE_SOURCE=_function_source(source, "async function _writeToClipboard("),
        )
    )


# --------------------------------------------------------------------------------------
# Runner 2: the LAN-URL button of the Web UI settings panel (settings-manager.js).
# --------------------------------------------------------------------------------------

WEB_UI_LAN_RUNNER = """
const fs = require('fs');
const vm = require('vm');
__FAKE_BROWSER__
const navigator_ = __NAVIGATOR__;
const LAN_URL = __LAN_URL__;
__TRANSLATIONS__
__STATUS_PAYLOAD__
const button = element('bark-base-url-copy-btn', 'button');
button.hidden = true;
button.span = makeElement('span');
button.span.textContent = texts['settings.baseUrlCopyLan'];
for (const id of [
  'bark-base-url-status-item',
  'bark-base-url-status-message',
  'bark-base-url-status-suggestion',
  'bark-base-url-recheck-btn',
]) {
  element(id);
}
const sandbox = {
  console: { debug() {}, error() {}, info() {}, log() {}, warn() {} },
  document: document_,
  navigator: navigator_,
  fetch(url) {
    return Promise.resolve(
      String(url).endsWith('/api/system/network-base-url-status')
        ? jsonResponse(statusPayload)
        : jsonResponse({ status: 'success', config: {} }),
    );
  },
  localStorage: { getItem() { return null; }, setItem() {} },
  location: { origin: 'http://127.0.0.1:8080' },
  module: { exports: {} },
  exports: {},
  notificationManager: {
    audioContext: null,
    isSupported: true,
    permission: 'default',
    getCustomSoundMeta() { return null; },
    updateConfig() {},
  },
  setTimeout: fakeSetTimeout,
  clearTimeout: fakeClearTimeout,
  showStatus() {},
  t(key) { return key; },
  AIIA_I18N,
  window: null,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.addEventListener = () => {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__DOM_SECURITY_PATH__, 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(__SETTINGS_PATH__, 'utf8'), sandbox);
const exported = sandbox.module.exports;
const label = () => button.span.textContent;
async function setup() {
  await new exported.SettingsManager().initBarkBaseUrlStatus();
  if (button.dataset.lanUrl !== LAN_URL) {
    throw new Error('the LAN url was not rendered: ' + button.dataset.lanUrl);
  }
}
(async () => {
__CASE__
})().catch(fail);
"""


def _run_web_ui_lan(case_js: str, *, navigator_js: str) -> dict:
    return _run_node(
        _assemble(
            WEB_UI_LAN_RUNNER,
            navigator_js=navigator_js,
            case_js=case_js,
            LAN_URL=LAN_URL,
            DOM_SECURITY_PATH=str(DOM_SECURITY_JS),
            SETTINGS_PATH=str(SETTINGS_MANAGER_JS),
        )
    )


# --------------------------------------------------------------------------------------
# Runner 3: the LAN-URL button of the VS Code settings panel (webview-settings-ui.js).
# --------------------------------------------------------------------------------------

VSCODE_LAN_RUNNER = """
const fs = require('fs');
const vm = require('vm');
__FAKE_BROWSER__
const navigator_ = __NAVIGATOR__;
const LAN_URL = __LAN_URL__;
__TRANSLATIONS__
__STATUS_PAYLOAD__
element('aiia-config').attrs['data-server-url'] = 'http://server';
element('settingsOverlay').classList.add('hidden');
for (const id of [
  'settingsPanel',
  'settingsHint',
  'notifyEnabled',
  'notifyMacOSNativeEnabled',
  'notifyBarkEnabled',
  'notifyBarkUrl',
  'notifyBarkDeviceKey',
  'notifyBarkIcon',
  'notifyBarkAction',
  'notifyBarkUrlTemplate',
  'feedbackCountdown',
  'feedbackResubmitPrompt',
  'feedbackPromptSuffix',
  'settingsConfigPath',
  'settingsBarkBaseUrlStatus',
  'settingsBarkBaseUrlMessage',
  'settingsBarkBaseUrlSuggestion',
  'settingsBarkBaseUrlRecheckBtn',
]) {
  element(id);
}
const button = element('settingsBarkBaseUrlCopyBtn', 'button');
button.hidden = true;
button.textContent = texts['settings.bark.baseUrlCopyLan'];
element('settingsBarkBaseUrlStatus').hidden = true;
let cachedSettings = {
  enabled: false,
  macosNativeEnabled: false,
  barkEnabled: false,
  barkUrl: 'https://api.day.app/push',
  barkDeviceKey: '',
  barkIcon: '',
  barkAction: 'none',
  barkUrlTemplate: '{base_url}/?task_id={task_id}',
};
const context = {
  console: { debug() {}, error() {}, info() {}, log() {}, warn() {} },
  document: document_,
  navigator: navigator_,
  setTimeout: fakeSetTimeout,
  clearTimeout: fakeClearTimeout,
  setInterval() { return 0; },
  clearInterval() {},
  fetch(url) {
    const target = String(url);
    if (target.endsWith('/api/system/network-base-url-status')) {
      return Promise.resolve(jsonResponse(statusPayload));
    }
    if (target.endsWith('/api/get-feedback-prompts')) {
      return Promise.resolve(jsonResponse({
        status: 'success',
        config: { frontend_countdown: 240, resubmit_prompt: '', prompt_suffix: '' },
        meta: { config_file: '/tmp/config.toml' },
      }));
    }
    return Promise.resolve(jsonResponse({ status: 'success' }));
  },
  __AIIA_showToast() {},
  AIIA_I18N,
  AIIAWebviewNotifyCore: {
    refreshNotificationSettingsFromServer: async () => ({ ok: true, settings: cachedSettings }),
    getCachedNotificationSettings: () => cachedSettings,
    setCachedNotificationSettings(next) { cachedSettings = Object.assign({}, next || {}); },
  },
};
context.globalThis = context;
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(__SETTINGS_UI_PATH__, 'utf8'), context, {
  filename: 'webview-settings-ui.js',
});
const api = context.AIIAWebviewSettingsUi;
const label = () => button.textContent;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function setup() {
  await api.openSettings();
  const started = Date.now();
  while (button.dataset.lanUrl !== LAN_URL) {
    if (Date.now() - started > 2000) throw new Error('the LAN url was not rendered');
    await sleep(5);
  }
}
(async () => {
__CASE__
  api.dispose();
})().catch(fail);
"""


def _run_vscode_lan(case_js: str, *, navigator_js: str) -> dict:
    return _run_node(
        _assemble(
            VSCODE_LAN_RUNNER,
            navigator_js=navigator_js,
            case_js=case_js,
            LAN_URL=LAN_URL,
            SETTINGS_UI_PATH=str(WEBVIEW_SETTINGS_UI_JS),
        )
    )


# --------------------------------------------------------------------------------------
# Source contracts (no Node needed).
# --------------------------------------------------------------------------------------


class TestEachBundleHasOneSelectionCopy(unittest.TestCase):
    def test_the_web_ui_selection_copy_lives_in_dom_security_only(self) -> None:
        owners = [
            path.name
            for path in _first_party_scripts(STATIC_JS, vendored=VENDORED_WEB_UI)
            if SELECTION_COPY_RE.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual(owners, ["dom-security.js"])

    def test_the_web_ui_clipboard_write_lives_in_dom_security_only(self) -> None:
        owners = [
            path.name
            for path in _first_party_scripts(STATIC_JS, vendored=VENDORED_WEB_UI)
            if CLIPBOARD_WRITE_RE.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual(owners, ["dom-security.js"])

    def test_the_extension_has_no_selection_copy(self) -> None:
        owners = [
            path.name
            for path in _first_party_scripts(VSCODE_DIR, vendored=set())
            if SELECTION_COPY_RE.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual(owners, [])

    def test_the_task_copy_helper_delegates_to_dom_security(self) -> None:
        body = _function_source(
            MULTI_TASK_JS.read_text(encoding="utf-8"),
            "async function _writeToClipboard(",
        )

        self.assertIn("DOMSecurity.writeTextToClipboard", body)
        self.assertNotIn("navigator", body)
        self.assertNotIn("execCommand", body)

    def test_the_lan_url_button_delegates_to_dom_security(self) -> None:
        source = SETTINGS_MANAGER_JS.read_text(encoding="utf-8")

        self.assertIn("DOMSecurity.writeTextToClipboard", source)
        self.assertNotIn("execCommand", source)
        self.assertNotIn("navigator.clipboard", source)
        # The labels keep their keys: R42 pins them, the restore uses them.
        for key in (
            "settings.baseUrlCopied",
            "settings.baseUrlCopyLan",
            "status.copyFailed",
        ):
            self.assertIn(key, source)

    def test_the_vscode_lan_button_keeps_no_second_clipboard_path(self) -> None:
        source = WEBVIEW_SETTINGS_UI_JS.read_text(encoding="utf-8")

        self.assertNotIn("execCommand", source)
        for key in (
            "settings.bark.baseUrlCopied",
            "settings.bark.baseUrlCopyLan",
            "ui.copy.failed",
        ):
            self.assertIn(key, source)


# --------------------------------------------------------------------------------------
# multi_task.js ``_writeToClipboard``.
# --------------------------------------------------------------------------------------


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestTaskCopyHelper(unittest.TestCase):
    def test_a_working_api_is_used_alone(self) -> None:
        result = _run_write(
            """
            const ok = await write(TEXT);
            report({ ok });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertIs(result["ok"], True)
        self.assertEqual(result["written"], [TEXT])
        self.assertEqual(result["execCalls"], [])
        self.assertEqual(result["helpers"], 0)

    def test_a_refused_api_write_falls_back_to_the_selection(self) -> None:
        result = _run_write(
            """
            const ok = await write(TEXT);
            report({ ok });
            """,
            navigator_js=REFUSING_CLIPBOARD,
        )

        self.assertIs(result["ok"], True)
        self.assertEqual(result["written"], ["refused:" + TEXT])
        self.assertEqual(len(result["execCalls"]), 1)
        self.assertEqual(result["execCalls"][0]["value"], TEXT)
        self.assertEqual(result["helpers"], 0)

    def test_a_clipboard_object_without_write_text_counts_as_missing(self) -> None:
        result = _run_write(
            """
            const ok = await write(TEXT);
            report({ ok });
            """,
            navigator_js=WRITE_TEXT_MISSING,
        )

        self.assertIs(result["ok"], True)
        self.assertEqual(len(result["execCalls"]), 1)

    def test_without_an_api_the_selection_copy_runs_before_anything_is_awaited(
        self,
    ) -> None:
        # Safari only honours execCommand('copy') while the user gesture is on the
        # stack; an `await` before it would lose it.
        result = _run_write(
            """
            const pending = write(TEXT);
            const syncCalls = execCalls.length;
            const ok = await pending;
            report({ ok, syncCalls });
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["syncCalls"], 1)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["execCalls"][0]["command"], "copy")
        self.assertEqual(result["execCalls"][0]["value"], TEXT)
        self.assertEqual(result["execCalls"][0]["helperInBody"], 1)

    def test_the_helper_textarea_is_read_only_fixed_and_off_screen(self) -> None:
        result = _run_write(
            """
            await write(TEXT);
            report();
            """,
            navigator_js=NO_CLIPBOARD,
        )

        call = result["execCalls"][0]
        self.assertEqual(call["readonly"], "")
        self.assertEqual(call["position"], "fixed")
        self.assertEqual(call["offscreen"], ["-1000px", "-1000px"])

    def test_a_failed_copy_answers_false_and_leaves_nothing_behind(self) -> None:
        for navigator_js in (NO_CLIPBOARD, REFUSING_CLIPBOARD, THROWING_CLIPBOARD):
            for exec_result, exec_throws in (("false", "false"), ("true", "true")):
                with self.subTest(
                    navigator=navigator_js, exec=(exec_result, exec_throws)
                ):
                    result = _run_write(
                        f"""
                        execResult = {exec_result};
                        execThrows = {exec_throws};
                        const ok = await write(TEXT);
                        report({{ ok }});
                        """,
                        navigator_js=navigator_js,
                    )

                    self.assertIs(result["ok"], False)
                    self.assertEqual(result["helpers"], 0)

    def test_focus_and_the_page_selection_are_put_back(self) -> None:
        for exec_throws in ("false", "true"):
            with self.subTest(exec_throws=exec_throws):
                result = _run_write(
                    f"""
                    execThrows = {exec_throws};
                    await write(TEXT);
                    report();
                    """,
                    navigator_js=NO_CLIPBOARD,
                )

                self.assertEqual(result["activeId"], "previously-focused")
                self.assertEqual(result["selection"], ["range-1", "range-2"])

    def test_empty_text_is_not_copied(self) -> None:
        result = _run_write(
            """
            const results = [await write(''), await write(null), await write(undefined)];
            report({ results });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["results"], [False, False, False])
        self.assertEqual(result["written"], [])
        self.assertEqual(result["execCalls"], [])

    def test_a_page_without_dom_security_answers_false_instead_of_throwing(
        self,
    ) -> None:
        result = _run_write(
            """
            const ok = await write(TEXT);
            report({ ok });
            """,
            navigator_js=WORKING_CLIPBOARD,
            load_dom_security=False,
        )

        self.assertIs(result["ok"], False)
        self.assertEqual(result["written"], [])


# --------------------------------------------------------------------------------------
# The LAN-URL button of the Web UI settings panel.
# --------------------------------------------------------------------------------------


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestWebUiLanUrlButton(unittest.TestCase):
    def test_a_click_copies_the_url_and_says_copied(self) -> None:
        result = _run_web_ui_lan(
            """
            await setup();
            const before = label();
            await button.click();
            report({ before, after: label() });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["before"], "Copy LAN URL")
        self.assertEqual(result["after"], "Copied")
        self.assertEqual(result["written"], [LAN_URL])
        self.assertEqual(result["execCalls"], [])

    def test_without_an_api_the_selection_copy_runs_inside_the_click(self) -> None:
        result = _run_web_ui_lan(
            """
            await setup();
            const pending = button.click();
            const syncCalls = execCalls.length;
            await pending;
            report({ syncCalls, after: label() });
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["syncCalls"], 1)
        self.assertEqual(result["execCalls"][0]["value"], LAN_URL)
        self.assertEqual(result["after"], "Copied")
        self.assertEqual(result["helpers"], 0)

    def test_a_refused_api_write_falls_back_to_the_selection(self) -> None:
        result = _run_web_ui_lan(
            """
            await setup();
            await button.click();
            report({ after: label() });
            """,
            navigator_js=REFUSING_CLIPBOARD,
        )

        self.assertEqual(result["written"], ["refused:" + LAN_URL])
        self.assertEqual(len(result["execCalls"]), 1)
        self.assertEqual(result["execCalls"][0]["value"], LAN_URL)
        self.assertEqual(result["after"], "Copied")

    def test_a_copy_that_did_not_happen_never_says_copied(self) -> None:
        for navigator_js in (NO_CLIPBOARD, REFUSING_CLIPBOARD, THROWING_CLIPBOARD):
            for exec_result, exec_throws in (("false", "false"), ("true", "true")):
                with self.subTest(
                    navigator=navigator_js, exec=(exec_result, exec_throws)
                ):
                    result = _run_web_ui_lan(
                        f"""
                        execResult = {exec_result};
                        execThrows = {exec_throws};
                        await setup();
                        await button.click();
                        const during = label();
                        runFeedbackTimers();
                        report({{ during, after: label() }});
                        """,
                        navigator_js=navigator_js,
                    )

                    self.assertEqual(result["during"], "Copy failed")
                    self.assertEqual(result["after"], "Copy LAN URL")
                    self.assertEqual(result["helpers"], 0)

    def test_focus_and_the_page_selection_are_put_back(self) -> None:
        result = _run_web_ui_lan(
            """
            await setup();
            await button.click();
            report();
            """,
            navigator_js=NO_CLIPBOARD,
        )

        self.assertEqual(result["activeId"], "previously-focused")
        self.assertEqual(result["selection"], ["range-1", "range-2"])

    def test_the_label_comes_back_after_the_feedback_window(self) -> None:
        result = _run_web_ui_lan(
            """
            await setup();
            await button.click();
            const during = label();
            runFeedbackTimers();
            report({ during, after: label() });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["during"], "Copied")
        self.assertEqual(result["after"], "Copy LAN URL")

    def test_clicks_inside_the_feedback_window_never_leave_the_label_stuck(
        self,
    ) -> None:
        # Old code restored the label from the text it found when it was clicked: the
        # second click captured "Copied" and put it back for good.
        for first, second in (
            ("true", "true"),
            ("true", "false"),
            ("false", "true"),
            ("false", "false"),
        ):
            with self.subTest(first=first, second=second):
                result = _run_web_ui_lan(
                    f"""
                    await setup();
                    execResult = {first};
                    await button.click();
                    execResult = {second};
                    await button.click();
                    const during = label();
                    const pending = feedbackTimers.length;
                    runFeedbackTimers();
                    report({{ during, pending, after: label() }});
                    """,
                    navigator_js=NO_CLIPBOARD,
                )

                self.assertEqual(
                    result["during"], "Copied" if second == "true" else "Copy failed"
                )
                # The second click restarts the window; it does not race the first.
                self.assertEqual(result["pending"], 1)
                self.assertEqual(result["after"], "Copy LAN URL")

    def test_the_label_is_restored_in_the_current_language(self) -> None:
        result = _run_web_ui_lan(
            """
            await setup();
            await button.click();
            texts['settings.baseUrlCopyLan'] = 'Copiar URL de LAN';
            runFeedbackTimers();
            report({ after: label() });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["after"], "Copiar URL de LAN")

    def test_a_button_without_a_url_does_nothing(self) -> None:
        result = _run_web_ui_lan(
            """
            await setup();
            button.dataset.lanUrl = '';
            await button.click();
            report({ after: label() });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["after"], "Copy LAN URL")
        self.assertEqual(result["written"], [])
        self.assertEqual(result["execCalls"], [])


# --------------------------------------------------------------------------------------
# The LAN-URL button of the VS Code settings panel.
# --------------------------------------------------------------------------------------


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestVsCodeLanUrlButton(unittest.TestCase):
    def test_a_click_copies_the_url_and_says_copied(self) -> None:
        result = _run_vscode_lan(
            """
            await setup();
            const before = label();
            await button.click();
            report({ before, after: label() });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["before"], "Copy LAN URL")
        self.assertEqual(result["after"], "Copied")
        self.assertEqual(result["written"], [LAN_URL])
        self.assertEqual(result["execCalls"], [])

    def test_a_copy_that_did_not_happen_never_says_copied(self) -> None:
        for navigator_js in (
            REFUSING_CLIPBOARD,
            THROWING_CLIPBOARD,
            WRITE_TEXT_MISSING,
            NO_CLIPBOARD,
        ):
            with self.subTest(navigator=navigator_js):
                result = _run_vscode_lan(
                    """
                    await setup();
                    await button.click();
                    const during = label();
                    runFeedbackTimers();
                    report({ during, after: label() });
                    """,
                    navigator_js=navigator_js,
                )

                self.assertEqual(result["during"], "Copy failed")
                self.assertEqual(result["after"], "Copy LAN URL")
                self.assertEqual(result["execCalls"], [])
                self.assertEqual(result["helpers"], 0)

    def test_clicks_inside_the_feedback_window_never_leave_the_label_stuck(
        self,
    ) -> None:
        for first, second in (
            (WORKING_CLIPBOARD, WORKING_CLIPBOARD),
            (WORKING_CLIPBOARD, REFUSING_CLIPBOARD),
            (REFUSING_CLIPBOARD, WORKING_CLIPBOARD),
            (REFUSING_CLIPBOARD, REFUSING_CLIPBOARD),
        ):
            with self.subTest(first=first, second=second):
                result = _run_vscode_lan(
                    f"""
                    await setup();
                    context.navigator = {first};
                    await button.click();
                    context.navigator = {second};
                    await button.click();
                    const during = label();
                    const pending = feedbackTimers.length;
                    runFeedbackTimers();
                    report({{ during, pending, after: label() }});
                    """,
                    navigator_js=NO_CLIPBOARD,
                )

                self.assertEqual(
                    result["during"],
                    "Copied" if second == WORKING_CLIPBOARD else "Copy failed",
                )
                # The second click restarts the window; it does not race the first.
                self.assertEqual(result["pending"], 1)
                self.assertEqual(result["after"], "Copy LAN URL")

    def test_the_label_is_restored_in_the_current_language(self) -> None:
        result = _run_vscode_lan(
            """
            await setup();
            await button.click();
            texts['settings.bark.baseUrlCopyLan'] = 'Copiar URL de LAN';
            runFeedbackTimers();
            report({ after: label() });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["after"], "Copiar URL de LAN")

    def test_a_button_without_a_url_does_nothing(self) -> None:
        result = _run_vscode_lan(
            """
            await setup();
            button.dataset.lanUrl = '';
            await button.click();
            report({ after: label() });
            """,
            navigator_js=WORKING_CLIPBOARD,
        )

        self.assertEqual(result["after"], "Copy LAN URL")
        self.assertEqual(result["written"], [])


if __name__ == "__main__":
    unittest.main()
