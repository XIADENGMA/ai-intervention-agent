"""Runtime checks for ``settings-manager.js`` initialization ownership.

``SettingsManager.init()`` is started during app boot, while ``showSettings()``
also defensively calls it when a user opens the panel before boot completes.
That overlap must be single-flight: anonymous ``addEventListener`` handlers are
distinct function objects, so repeated wiring would duplicate document/window
listeners and debounce state.
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
SETTINGS_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)


def _read_source() -> str:
    return SETTINGS_MANAGER_JS.read_text(encoding="utf-8")


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _settings_manager_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(SETTINGS_MANAGER_JS)!r}, 'utf8');

        const elementListeners = [];
        const documentListeners = [];
        const documentRemovedListeners = [];
        const focusedIds = [];
        const timeoutCallbacks = [];
        const windowListeners = [];
        const elements = new Map();

        function makeElement(id) {{
          return {{
            id,
            checked: false,
            classList: {{ add() {{}}, remove() {{}} }},
            children: [],
            dataset: {{}},
            disabled: false,
            files: [],
            innerHTML: '',
            inert: false,
            offsetParent: {{}},
            style: {{}},
            textContent: '',
            value: '',
            addEventListener(type, handler) {{
              elementListeners.push({{ id, type, handler }});
            }},
            appendChild() {{}},
            blur() {{}},
            focus() {{
              focusedIds.push(id);
            }},
            hasAttribute() {{
              return false;
            }},
            querySelector() {{
              return {{ textContent: '' }};
            }},
            querySelectorAll() {{
              return [];
            }},
            removeAttribute() {{}},
            setAttribute() {{}},
          }};
        }}

        function getElement(id) {{
          if (!elements.has(id)) {{
            elements.set(id, makeElement(id));
          }}
          return elements.get(id);
        }}

        const sandbox = {{
          Array,
          Error,
          JSON,
          Map,
          Math,
          Number,
          Object,
          Promise,
          RegExp,
          Set,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            activeElement: null,
            addEventListener(type, handler) {{
              documentListeners.push({{ type, handler }});
            }},
            body: {{
              appendChild() {{}},
              removeChild() {{}},
            }},
            contains() {{
              return false;
            }},
            createElement() {{
              return makeElement('created');
            }},
            execCommand() {{
              return true;
            }},
            getElementById(id) {{
              return getElement(id);
            }},
            querySelector(selector) {{
              return getElement(selector);
            }},
            querySelectorAll() {{
              return [];
            }},
            removeEventListener(type, handler) {{
              documentRemovedListeners.push({{ type, handler }});
            }},
          }},
          fetch() {{
            return Promise.resolve({{
              ok: true,
              json: () => Promise.resolve({{ status: 'success', config: {{}} }}),
            }});
          }},
          localStorage: {{
            getItem() {{
              return null;
            }},
            setItem() {{}},
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          notificationManager: {{
            clearCustomSound() {{
              return Promise.resolve({{ success: true }});
            }},
            getCustomSoundMeta() {{
              return null;
            }},
            playSound() {{
              return Promise.resolve();
            }},
            saveCustomSoundFromFile() {{
              return Promise.resolve({{ success: true }});
            }},
          }},
          setTimeout(fn) {{
            timeoutCallbacks.push(fn);
            return {{ fn }};
          }},
          clearTimeout() {{}},
          showStatus() {{}},
          window: null,
          __documentRemovedListeners: documentRemovedListeners,
          __documentListeners: documentListeners,
          __elementListeners: elementListeners,
          __focusedIds: focusedIds,
          __getElement: getElement,
          __timeoutCallbacks: timeoutCallbacks,
          __windowListeners: windowListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.addEventListener = (type, handler) => {{
          windowListeners.push({{ type, handler }});
        }};

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const exported = sandbox.module.exports;

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


class TestSettingsManagerInitSourceContract(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read_source()

    def test_constructor_tracks_singleflight_and_listener_state(self) -> None:
        self.assertIn("this._initPromise = null;", self.src)
        self.assertIn("this._eventListenersInitialized = false;", self.src)
        self.assertIn("this._settingsEscHandler = null;", self.src)
        self.assertIn("this._previouslyFocusedElement = null;", self.src)

    def test_init_reuses_pending_promise_and_clears_after_failure(self) -> None:
        self.assertRegex(
            self.src,
            r"if\s*\(\s*this\._initPromise\s*\)\s*\{\s*"
            r"return\s+this\._initPromise;\s*\}",
        )
        self.assertRegex(
            self.src,
            r"finally\s*\{[\s\S]*?this\._initPromise\s*=\s*null;",
        )
        self.assertRegex(
            self.src,
            r"this\._initPromise\s*=\s*\(\s*async\s*\(\s*\)\s*=>",
        )

    def test_event_listener_wiring_is_idempotent(self) -> None:
        match = re.search(
            r"initEventListeners\(\)\s*\{(?P<body>[\s\S]*?)"
            r"\n    // 设置按钮点击事件",
            self.src,
        )
        self.assertIsNotNone(match)
        assert match is not None
        body = match.group("body")
        self.assertIn("if (this._eventListenersInitialized)", body)
        self.assertIn("this._eventListenersInitialized = true;", body)

    def test_settings_keydown_handler_has_attach_guard(self) -> None:
        self.assertRegex(
            self.src,
            r"_attachSettingsKeydownHandler\(panel\)\s*\{[\s\S]{0,120}?"
            r"if\s*\(\s*this\._settingsEscHandler\s*\)\s*return;",
        )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_concurrent_init_reuses_one_promise_and_binds_once() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        let loadSettingsCalls = 0;
        let loadFeedbackCalls = 0;
        let listenerCalls = 0;
        let openConfigCalls = 0;
        let barkStatusCalls = 0;
        let resolveSettings;

        const settingsPromise = new Promise((resolve) => {
          resolveSettings = resolve;
        });

        manager.loadSettings = () => {
          loadSettingsCalls += 1;
          return settingsPromise;
        };
        manager.loadFeedbackConfig = () => {
          loadFeedbackCalls += 1;
          return Promise.resolve({ frontend_countdown: 30 });
        };
        manager.initEventListeners = () => {
          listenerCalls += 1;
        };
        manager.initOpenConfigFileButton = () => {
          openConfigCalls += 1;
        };
        manager.initBarkBaseUrlStatus = () => {
          barkStatusCalls += 1;
        };

        const first = manager.init();
        const second = manager.init();
        const pendingState = {
          samePromise: first === second,
          heldPromise: manager._initPromise === first,
          loadSettingsCalls,
        };

        resolveSettings({ soundVolume: 80 });
        await first;

        process.stdout.write(
          JSON.stringify({
            pendingState,
            loadSettingsCalls,
            loadFeedbackCalls,
            listenerCalls,
            openConfigCalls,
            barkStatusCalls,
            initialized: manager.initialized,
            initPromise: manager._initPromise,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"pendingState":{"samePromise":true,"heldPromise":true,'
        '"loadSettingsCalls":1},"loadSettingsCalls":1,"loadFeedbackCalls":1,'
        '"listenerCalls":1,"openConfigCalls":1,"barkStatusCalls":1,'
        '"initialized":true,"initPromise":null}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_failed_init_clears_promise_and_allows_retry() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        let loadSettingsCalls = 0;
        let listenerCalls = 0;

        manager.loadSettings = () => {
          loadSettingsCalls += 1;
          if (loadSettingsCalls === 1) {
            return Promise.reject(new Error('boom'));
          }
          return Promise.resolve({ soundVolume: 80 });
        };
        manager.loadFeedbackConfig = () => Promise.resolve({ frontend_countdown: 30 });
        manager.initEventListeners = () => {
          listenerCalls += 1;
        };
        manager.initOpenConfigFileButton = () => {};
        manager.initBarkBaseUrlStatus = () => {};

        let firstError = '';
        try {
          await manager.init();
        } catch (err) {
          firstError = err.message;
        }

        const afterFailure = {
          firstError,
          initialized: manager.initialized,
          initPromise: manager._initPromise,
          loadSettingsCalls,
          listenerCalls,
        };

        await manager.init();

        process.stdout.write(
          JSON.stringify({
            afterFailure,
            initialized: manager.initialized,
            initPromise: manager._initPromise,
            loadSettingsCalls,
            listenerCalls,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"afterFailure":{"firstError":"boom","initialized":false,'
        '"initPromise":null,"loadSettingsCalls":1,"listenerCalls":0},'
        '"initialized":true,"initPromise":null,"loadSettingsCalls":2,'
        '"listenerCalls":1}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_init_event_listeners_is_directly_idempotent() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();

        manager.initEventListeners();
        const first = {
          element: sandbox.__elementListeners.length,
          document: sandbox.__documentListeners.length,
          window: sandbox.__windowListeners.length,
          wired: manager._eventListenersInitialized,
        };

        manager.initEventListeners();
        const second = {
          element: sandbox.__elementListeners.length,
          document: sandbox.__documentListeners.length,
          window: sandbox.__windowListeners.length,
          wired: manager._eventListenersInitialized,
        };

        process.stdout.write(JSON.stringify({ first, second }));
        """
    )

    result = json.loads(_run_node(script))
    assert result["first"]["element"] > 0
    assert result["first"]["document"] > 0
    assert result["first"]["window"] > 0
    assert result["first"] == result["second"]


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_reopening_settings_panel_does_not_leak_keydown_listener_or_focus_origin() -> (
    None
):
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.initialized = true;
        manager.loadSettings = () => Promise.resolve({});
        manager.loadFeedbackConfig = () => Promise.resolve({ frontend_countdown: 30 });
        manager.applySettingsTheme = () => {};
        manager.updateUI = () => {};
        manager.updateFeedbackUI = () => {};
        manager.updateStatus = () => {};

        const opener = sandbox.__getElement('opener');
        const inner = sandbox.__getElement('settings-inner');
        sandbox.document.activeElement = opener;
        sandbox.document.contains = (el) => el === opener || el === inner;

        await manager.showSettings();
        sandbox.document.activeElement = inner;
        await manager.showSettings();

        const beforeHide = {
          keydownAdds: sandbox.__documentListeners.filter((entry) => entry.type === 'keydown').length,
          handlerStillAttached: manager._settingsEscHandler !== null,
        };

        manager.hideSettings();

        process.stdout.write(
          JSON.stringify({
            beforeHide,
            keydownRemoves: sandbox.__documentRemovedListeners.filter((entry) => entry.type === 'keydown').length,
            handlerAfterHide: manager._settingsEscHandler,
            focusedIds: sandbox.__focusedIds,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeHide": {"keydownAdds": 1, "handlerStillAttached": True},
        "keydownRemoves": 1,
        "handlerAfterHide": None,
        "focusedIds": ["opener"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_hide_settings_restore_focus_uses_prevent_scroll_with_plain_fallback() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        const opener = sandbox.__getElement('opener');
        const focusCalls = [];
        opener.focus = (options) => {
          focusCalls.push(options && options.preventScroll ? 'options' : 'plain');
          if (options && options.preventScroll) {
            throw new Error('focus options unsupported');
          }
          sandbox.document.activeElement = opener;
        };
        manager._previouslyFocusedElement = opener;
        sandbox.document.contains = (el) => el === opener;

        let threw = false;
        try {
          manager.hideSettings();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          activeElementId: sandbox.document.activeElement
            ? sandbox.document.activeElement.id
            : null,
          focusCalls,
          threw,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeElementId": "opener",
        "focusCalls": ["options", "plain"],
        "threw": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_hide_settings_fallback_button_focuses_without_scroll() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        const opener = sandbox.__getElement('opener');
        const settingsButton = sandbox.__getElement('settings-btn');
        const focusCalls = [];
        settingsButton.focus = (options) => {
          focusCalls.push(options && options.preventScroll ? 'options' : 'plain');
          sandbox.document.activeElement = settingsButton;
        };
        manager._previouslyFocusedElement = opener;
        sandbox.document.contains = () => false;

        let threw = false;
        try {
          manager.hideSettings();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          activeElementId: sandbox.document.activeElement
            ? sandbox.document.activeElement.id
            : null,
          focusCalls,
          threw,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeElementId": "settings-btn",
        "focusCalls": ["options"],
        "threw": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_show_settings_deferred_focus_uses_prevent_scroll_with_plain_fallback() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.initialized = true;
        manager.loadSettings = () => Promise.resolve({});
        manager.loadFeedbackConfig = () => Promise.resolve({ frontend_countdown: 30 });
        manager.applySettingsTheme = () => {};
        manager.updateUI = () => {};
        manager.updateFeedbackUI = () => {};
        manager.updateStatus = () => {};

        const panel = sandbox.__getElement('settings-panel');
        const focusCalls = [];
        const firstFocusable = {
          focus(options) {
            focusCalls.push(options && options.preventScroll ? 'options' : 'plain');
            if (options && options.preventScroll) {
              throw new Error('focus options unsupported');
            }
          },
        };
        panel.querySelector = () => firstFocusable;
        panel.contains = (el) => el === firstFocusable;
        panel.classList.contains = () => false;
        sandbox.document.contains = (el) => el === panel || el === firstFocusable;

        await manager.showSettings();

        let threw = false;
        try {
          sandbox.__timeoutCallbacks[0]();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          timeoutCount: sandbox.__timeoutCallbacks.length,
          threw,
          focusCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "timeoutCount": 1,
        "threw": False,
        "focusCalls": ["options", "plain"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_show_settings_deferred_focus_skips_detached_control() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.initialized = true;
        manager.loadSettings = () => Promise.resolve({});
        manager.loadFeedbackConfig = () => Promise.resolve({ frontend_countdown: 30 });
        manager.applySettingsTheme = () => {};
        manager.updateUI = () => {};
        manager.updateFeedbackUI = () => {};
        manager.updateStatus = () => {};

        const panel = sandbox.__getElement('settings-panel');
        let focusCalls = 0;
        const firstFocusable = {
          focus() {
            focusCalls += 1;
            throw new Error('detached focus should not be attempted');
          },
        };
        panel.querySelector = () => firstFocusable;
        panel.contains = () => false;
        panel.classList.contains = () => false;
        sandbox.document.contains = (el) => el === panel;

        await manager.showSettings();

        let threw = false;
        try {
          sandbox.__timeoutCallbacks[0]();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          timeoutCount: sandbox.__timeoutCallbacks.length,
          threw,
          focusCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "timeoutCount": 1,
        "threw": False,
        "focusCalls": 0,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_show_settings_deferred_focus_skips_hidden_panel_after_quick_close() -> None:
    script = _settings_manager_harness(
        """
        const manager = new exported.SettingsManager();
        manager.initialized = true;
        manager.loadSettings = () => Promise.resolve({});
        manager.loadFeedbackConfig = () => Promise.resolve({ frontend_countdown: 30 });
        manager.applySettingsTheme = () => {};
        manager.updateUI = () => {};
        manager.updateFeedbackUI = () => {};
        manager.updateStatus = () => {};

        const panel = sandbox.__getElement('settings-panel');
        let focusCalls = 0;
        const firstFocusable = {
          focus() {
            focusCalls += 1;
            throw new Error('hidden panel focus should not be attempted');
          },
        };
        panel.querySelector = () => firstFocusable;
        panel.contains = (el) => el === firstFocusable;
        panel.classList.contains = (name) => name === 'hidden';
        sandbox.document.contains = (el) => el === panel || el === firstFocusable;

        await manager.showSettings();

        let threw = false;
        try {
          sandbox.__timeoutCallbacks[0]();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          timeoutCount: sandbox.__timeoutCallbacks.length,
          threw,
          focusCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "timeoutCount": 1,
        "threw": False,
        "focusCalls": 0,
    }
