"""Runtime checks for VS Code settings autosave pending edits."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-settings-ui.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_save_settings_source_preserves_dirty_state_for_pending_save() -> None:
    source = SETTINGS_UI_JS.read_text(encoding="utf-8")

    assert "const hasPendingSave = settingsAutoSavePending" in source
    assert "settingsDirty = hasPendingSave" in source
    assert "if (!hasPendingSave)" in source
    assert "let settingsEditEpoch = 0" in source
    assert "let settingsAutoSaveFlushWhenClosed = false" in source
    assert "function flushSettingsAutoSaveBeforeClose()" in source
    assert "stopSettingsAutoRefresh({ preserveAutoSave: true })" in source
    assert (
        "const editedDuringRefresh = refreshEditEpoch !== settingsEditEpoch" in source
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_pending_autosave_after_inflight_response_sends_newer_form_state() -> None:
    source = SETTINGS_UI_JS.read_text(encoding="utf-8")
    script_body = textwrap.dedent(
        f"""
        const vm = require("vm");
        const source = {json.dumps(source)};
        const saveRequests = [];
        const hints = [];
        const cacheWrites = [];

        function sleep(ms) {{
          return new Promise((resolve) => setTimeout(resolve, ms));
        }}

        async function waitFor(predicate, label) {{
          const started = Date.now();
          while (Date.now() - started < 2000) {{
            if (predicate()) return;
            await sleep(5);
          }}
          throw new Error("Timed out waiting for " + label);
        }}

        class ClassList {{
          constructor(values) {{
            this.values = new Set(values || []);
          }}
          add(value) {{
            this.values.add(value);
          }}
          remove(value) {{
            this.values.delete(value);
          }}
          contains(value) {{
            return this.values.has(value);
          }}
          toggle(value, force) {{
            if (force === undefined ? !this.values.has(value) : force) {{
              this.values.add(value);
              return true;
            }}
            this.values.delete(value);
            return false;
          }}
        }}

        class TestElement {{
          constructor(id) {{
            this.id = id;
            this.checked = false;
            this.value = "";
            this.hidden = false;
            this.textContent = "";
            this.title = "";
            this.dataset = {{}};
            this.attributes = {{}};
            this.listeners = {{}};
            this.classList = new ClassList();
          }}
          addEventListener(type, handler) {{
            if (!this.listeners[type]) this.listeners[type] = [];
            this.listeners[type].push(handler);
          }}
          dispatch(type, event) {{
            const handlers = this.listeners[type] || [];
            const payload = Object.assign(
              {{
                target: this,
                preventDefault() {{}},
                stopPropagation() {{}},
              }},
              event || {{}},
            );
            for (const handler of handlers) handler(payload);
          }}
          getAttribute(name) {{
            return Object.prototype.hasOwnProperty.call(this.attributes, name)
              ? this.attributes[name]
              : "";
          }}
          setAttribute(name, value) {{
            this.attributes[name] = String(value);
          }}
          querySelectorAll() {{
            return [];
          }}
        }}

        const elements = {{}};
        function element(id) {{
          if (!elements[id]) elements[id] = new TestElement(id);
          return elements[id];
        }}

        element("aiia-config").setAttribute("data-server-url", "http://server");
        element("settingsOverlay").classList.add("hidden");
        element("settingsPanel");
        element("settingsHint");
        for (const id of [
          "notifyEnabled",
          "notifyMacOSNativeEnabled",
          "notifyBarkEnabled",
          "notifyBarkUrl",
          "notifyBarkDeviceKey",
          "notifyBarkIcon",
          "notifyBarkAction",
          "notifyBarkUrlTemplate",
        ]) {{
          element(id);
        }}

        let cachedSettings = {{
          enabled: false,
          macosNativeEnabled: false,
          barkEnabled: false,
          barkUrl: "https://api.day.app/push",
          barkDeviceKey: "",
          barkIcon: "",
          barkAction: "none",
          barkUrlTemplate: "{{base_url}}/?task_id={{task_id}}",
        }};

        let resolveFirstSave = null;
        function response(payload, status) {{
          return {{
            ok: !status || status < 400,
            status: status || 200,
            json: async () => payload,
          }};
        }}

        const context = {{
          console: {{
            debug() {{}},
            warn() {{}},
            error() {{}},
          }},
          document: {{
            getElementById(id) {{
              return Object.prototype.hasOwnProperty.call(elements, id)
                ? elements[id]
                : null;
            }},
            querySelectorAll() {{
              return [];
            }},
            createElement(tag) {{
              return new TestElement(tag);
            }},
            body: {{
              appendChild() {{}},
              removeChild() {{}},
            }},
            execCommand() {{
              return true;
            }},
          }},
          navigator: {{}},
          setTimeout(fn, ms, ...args) {{
            const scaled = ms === 500 ? 20 : ms === 1200 ? 1 : ms;
            return setTimeout(fn, scaled, ...args);
          }},
          clearTimeout,
          setInterval,
          clearInterval,
          fetch(url, options) {{
            const body = options && options.body ? JSON.parse(options.body) : null;
            if (String(url).endsWith("/api/update-notification-config")) {{
              saveRequests.push({{ url: String(url), body }});
              if (saveRequests.length === 1) {{
                return new Promise((resolve) => {{
                  resolveFirstSave = () =>
                    resolve(response({{ status: "success" }}));
                }});
              }}
              return Promise.resolve(response({{ status: "success" }}));
            }}
            if (String(url).endsWith("/api/get-feedback-prompts")) {{
              return Promise.resolve(response({{ status: "success", config: {{}} }}));
            }}
            return Promise.resolve(response({{ status: "success" }}));
          }},
          __AIIA_showToast(message, options) {{
            hints.push({{ message: String(message), kind: options && options.kind }});
          }},
          AIIA_I18N: {{
            t(key) {{
              return key;
            }},
          }},
          AIIAWebviewNotifyCore: {{
            refreshNotificationSettingsFromServer: async () => ({{
              ok: true,
              settings: cachedSettings,
            }}),
            getCachedNotificationSettings: () => cachedSettings,
            setCachedNotificationSettings(next) {{
              cachedSettings = Object.assign({{}}, next || {{}});
              cacheWrites.push(cachedSettings);
            }},
          }},
        }};
        context.globalThis = context;
        context.window = context;

        vm.runInNewContext(source, context, {{ filename: "webview-settings-ui.js" }});

        const api = context.AIIAWebviewSettingsUi;
        await api.openSettings();

        const panel = element("settingsPanel");
        element("notifyEnabled").checked = true;
        panel.dispatch("input", {{ target: element("notifyEnabled") }});

        await waitFor(() => saveRequests.length === 1, "first autosave POST");

        element("notifyBarkEnabled").checked = true;
        panel.dispatch("input", {{ target: element("notifyBarkEnabled") }});

        await sleep(60);
        if (saveRequests.length !== 1) {{
          throw new Error("second edit should be pending while first save is in flight");
        }}
        resolveFirstSave();

        await waitFor(() => saveRequests.length === 2, "queued autosave POST");
        api.dispose();

        process.stdout.write(JSON.stringify({{
          saveRequests,
          cacheWrites,
          hints,
          overlayHidden: element("settingsOverlay").classList.contains("hidden"),
        }}));
        """
    )
    script = (
        "(async () => {\n"
        + script_body
        + "\n})().catch((err) => {\n"
        + (
            "  console.error(err && err.stack ? err.stack : err);\n"
            "  process.exit(1);\n"
            "});\n"
        )
    )

    assert json.loads(_run_node(script)) == {
        "saveRequests": [
            {
                "url": "http://server/api/update-notification-config",
                "body": {
                    "enabled": True,
                    "macosNativeEnabled": False,
                    "barkEnabled": False,
                    "barkUrl": "https://api.day.app/push",
                    "barkDeviceKey": "",
                    "barkIcon": "",
                    "barkAction": "none",
                    "barkUrlTemplate": "{base_url}/?task_id={task_id}",
                },
            },
            {
                "url": "http://server/api/update-notification-config",
                "body": {
                    "enabled": True,
                    "macosNativeEnabled": False,
                    "barkEnabled": True,
                    "barkUrl": "https://api.day.app/push",
                    "barkDeviceKey": "",
                    "barkIcon": "",
                    "barkAction": "none",
                    "barkUrlTemplate": "{base_url}/?task_id={task_id}",
                },
            },
        ],
        "cacheWrites": [
            {
                "enabled": True,
                "macosNativeEnabled": False,
                "barkEnabled": False,
                "barkUrl": "https://api.day.app/push",
                "barkDeviceKey": "",
                "barkIcon": "",
                "barkAction": "none",
                "barkUrlTemplate": "{base_url}/?task_id={task_id}",
            },
            {
                "enabled": True,
                "macosNativeEnabled": False,
                "barkEnabled": True,
                "barkUrl": "https://api.day.app/push",
                "barkDeviceKey": "",
                "barkIcon": "",
                "barkAction": "none",
                "barkUrlTemplate": "{base_url}/?task_id={task_id}",
            },
        ],
        "hints": [
            {"message": "settings.hint.loading", "kind": "success"},
            {"message": "settings.hint.synced", "kind": "success"},
            {"message": "settings.hint.synced", "kind": "success"},
            {"message": "settings.hint.synced", "kind": "success"},
        ],
        "overlayHidden": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_open_refresh_does_not_overwrite_edit_made_during_load() -> None:
    source = SETTINGS_UI_JS.read_text(encoding="utf-8")
    script_body = textwrap.dedent(
        f"""
        const vm = require("vm");
        const source = {json.dumps(source)};
        const saveRequests = [];

        function sleep(ms) {{
          return new Promise((resolve) => setTimeout(resolve, ms));
        }}

        async function waitFor(predicate, label) {{
          const started = Date.now();
          while (Date.now() - started < 2000) {{
            if (predicate()) return;
            await sleep(5);
          }}
          throw new Error("Timed out waiting for " + label);
        }}

        class ClassList {{
          constructor(values) {{
            this.values = new Set(values || []);
          }}
          add(value) {{
            this.values.add(value);
          }}
          remove(value) {{
            this.values.delete(value);
          }}
          contains(value) {{
            return this.values.has(value);
          }}
          toggle(value, force) {{
            if (force === undefined ? !this.values.has(value) : force) {{
              this.values.add(value);
              return true;
            }}
            this.values.delete(value);
            return false;
          }}
        }}

        class TestElement {{
          constructor(id) {{
            this.id = id;
            this.checked = false;
            this.value = "";
            this.textContent = "";
            this.dataset = {{}};
            this.attributes = {{}};
            this.listeners = {{}};
            this.classList = new ClassList();
          }}
          addEventListener(type, handler) {{
            if (!this.listeners[type]) this.listeners[type] = [];
            this.listeners[type].push(handler);
          }}
          dispatch(type, event) {{
            const handlers = this.listeners[type] || [];
            const payload = Object.assign(
              {{
                target: this,
                preventDefault() {{}},
                stopPropagation() {{}},
              }},
              event || {{}},
            );
            for (const handler of handlers) handler(payload);
          }}
          getAttribute(name) {{
            return Object.prototype.hasOwnProperty.call(this.attributes, name)
              ? this.attributes[name]
              : "";
          }}
          setAttribute(name, value) {{
            this.attributes[name] = String(value);
          }}
          querySelectorAll() {{
            return [];
          }}
        }}

        const elements = {{}};
        function element(id) {{
          if (!elements[id]) elements[id] = new TestElement(id);
          return elements[id];
        }}

        element("aiia-config").setAttribute("data-server-url", "http://server");
        element("settingsOverlay").classList.add("hidden");
        element("settingsPanel");
        element("settingsHint");
        for (const id of [
          "notifyEnabled",
          "notifyMacOSNativeEnabled",
          "notifyBarkEnabled",
          "notifyBarkUrl",
          "notifyBarkDeviceKey",
          "notifyBarkIcon",
          "notifyBarkAction",
          "notifyBarkUrlTemplate",
        ]) {{
          element(id);
        }}

        let cachedSettings = {{
          enabled: false,
          macosNativeEnabled: false,
          barkEnabled: false,
          barkUrl: "https://api.day.app/push",
          barkDeviceKey: "",
          barkIcon: "",
          barkAction: "none",
          barkUrlTemplate: "{{base_url}}/?task_id={{task_id}}",
        }};
        let resolveRefresh = null;

        function response(payload, status) {{
          return {{
            ok: !status || status < 400,
            status: status || 200,
            json: async () => payload,
          }};
        }}

        const context = {{
          console: {{
            debug() {{}},
            warn() {{}},
            error() {{}},
          }},
          document: {{
            getElementById(id) {{
              return Object.prototype.hasOwnProperty.call(elements, id)
                ? elements[id]
                : null;
            }},
            querySelectorAll() {{
              return [];
            }},
            createElement(tag) {{
              return new TestElement(tag);
            }},
            body: {{
              appendChild() {{}},
              removeChild() {{}},
            }},
            execCommand() {{
              return true;
            }},
          }},
          navigator: {{}},
          setTimeout(fn, ms, ...args) {{
            const scaled = ms === 500 ? 20 : ms === 1200 ? 1 : ms;
            return setTimeout(fn, scaled, ...args);
          }},
          clearTimeout,
          setInterval,
          clearInterval,
          fetch(url, options) {{
            const body = options && options.body ? JSON.parse(options.body) : null;
            if (String(url).endsWith("/api/update-notification-config")) {{
              saveRequests.push({{ url: String(url), body }});
              return Promise.resolve(response({{ status: "success" }}));
            }}
            if (String(url).endsWith("/api/get-feedback-prompts")) {{
              return Promise.resolve(response({{ status: "success", config: {{}} }}));
            }}
            return Promise.resolve(response({{ status: "success" }}));
          }},
          __AIIA_showToast() {{}},
          AIIA_I18N: {{
            t(key) {{
              return key;
            }},
          }},
          AIIAWebviewNotifyCore: {{
            refreshNotificationSettingsFromServer: () =>
              new Promise((resolve) => {{
                resolveRefresh = (settings) => {{
                  cachedSettings = Object.assign({{}}, settings || {{}});
                  resolve({{ ok: true, settings: cachedSettings }});
                }};
              }}),
            getCachedNotificationSettings: () => cachedSettings,
            setCachedNotificationSettings(next) {{
              cachedSettings = Object.assign({{}}, next || {{}});
            }},
          }},
        }};
        context.globalThis = context;
        context.window = context;

        vm.runInNewContext(source, context, {{ filename: "webview-settings-ui.js" }});

        const api = context.AIIAWebviewSettingsUi;
        const openPromise = api.openSettings();
        await waitFor(() => typeof resolveRefresh === "function", "forced refresh");

        const panel = element("settingsPanel");
        element("notifyEnabled").checked = true;
        panel.dispatch("input", {{ target: element("notifyEnabled") }});

        resolveRefresh(Object.assign({{}}, cachedSettings, {{ enabled: false }}));
        await openPromise;

        await waitFor(() => saveRequests.length === 1, "autosave POST");
        api.dispose();

        process.stdout.write(JSON.stringify({{
          notifyChecked: element("notifyEnabled").checked,
          saveRequests,
          overlayHidden: element("settingsOverlay").classList.contains("hidden"),
        }}));
        """
    )
    script = (
        "(async () => {\n"
        + script_body
        + "\n})().catch((err) => {\n"
        + (
            "  console.error(err && err.stack ? err.stack : err);\n"
            "  process.exit(1);\n"
            "});\n"
        )
    )

    assert json.loads(_run_node(script)) == {
        "notifyChecked": True,
        "saveRequests": [
            {
                "url": "http://server/api/update-notification-config",
                "body": {
                    "enabled": True,
                    "macosNativeEnabled": False,
                    "barkEnabled": False,
                    "barkUrl": "https://api.day.app/push",
                    "barkDeviceKey": "",
                    "barkIcon": "",
                    "barkAction": "none",
                    "barkUrlTemplate": "{base_url}/?task_id={task_id}",
                },
            }
        ],
        "overlayHidden": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_close_flushes_debounced_autosave_before_timer_fires() -> None:
    source = SETTINGS_UI_JS.read_text(encoding="utf-8")
    script_body = textwrap.dedent(
        f"""
        const vm = require("vm");
        const source = {json.dumps(source)};
        const saveRequests = [];

        function sleep(ms) {{
          return new Promise((resolve) => setTimeout(resolve, ms));
        }}

        async function waitFor(predicate, label) {{
          const started = Date.now();
          while (Date.now() - started < 2000) {{
            if (predicate()) return;
            await sleep(5);
          }}
          throw new Error("Timed out waiting for " + label);
        }}

        class ClassList {{
          constructor(values) {{
            this.values = new Set(values || []);
          }}
          add(value) {{
            this.values.add(value);
          }}
          remove(value) {{
            this.values.delete(value);
          }}
          contains(value) {{
            return this.values.has(value);
          }}
          toggle(value, force) {{
            if (force === undefined ? !this.values.has(value) : force) {{
              this.values.add(value);
              return true;
            }}
            this.values.delete(value);
            return false;
          }}
        }}

        class TestElement {{
          constructor(id) {{
            this.id = id;
            this.checked = false;
            this.value = "";
            this.textContent = "";
            this.dataset = {{}};
            this.attributes = {{}};
            this.listeners = {{}};
            this.classList = new ClassList();
          }}
          addEventListener(type, handler) {{
            if (!this.listeners[type]) this.listeners[type] = [];
            this.listeners[type].push(handler);
          }}
          dispatch(type, event) {{
            const handlers = this.listeners[type] || [];
            const payload = Object.assign(
              {{
                target: this,
                preventDefault() {{}},
                stopPropagation() {{}},
              }},
              event || {{}},
            );
            for (const handler of handlers) handler(payload);
          }}
          getAttribute(name) {{
            return Object.prototype.hasOwnProperty.call(this.attributes, name)
              ? this.attributes[name]
              : "";
          }}
          setAttribute(name, value) {{
            this.attributes[name] = String(value);
          }}
          querySelectorAll() {{
            return [];
          }}
        }}

        const elements = {{}};
        function element(id) {{
          if (!elements[id]) elements[id] = new TestElement(id);
          return elements[id];
        }}

        element("aiia-config").setAttribute("data-server-url", "http://server");
        element("settingsOverlay").classList.add("hidden");
        element("settingsPanel");
        element("settingsHint");
        for (const id of [
          "notifyEnabled",
          "notifyMacOSNativeEnabled",
          "notifyBarkEnabled",
          "notifyBarkUrl",
          "notifyBarkDeviceKey",
          "notifyBarkIcon",
          "notifyBarkAction",
          "notifyBarkUrlTemplate",
        ]) {{
          element(id);
        }}

        let cachedSettings = {{
          enabled: false,
          macosNativeEnabled: false,
          barkEnabled: false,
          barkUrl: "https://api.day.app/push",
          barkDeviceKey: "",
          barkIcon: "",
          barkAction: "none",
          barkUrlTemplate: "{{base_url}}/?task_id={{task_id}}",
        }};

        function response(payload, status) {{
          return {{
            ok: !status || status < 400,
            status: status || 200,
            json: async () => payload,
          }};
        }}

        const context = {{
          console: {{
            debug() {{}},
            warn() {{}},
            error() {{}},
          }},
          document: {{
            getElementById(id) {{
              return Object.prototype.hasOwnProperty.call(elements, id)
                ? elements[id]
                : null;
            }},
            querySelectorAll() {{
              return [];
            }},
            createElement(tag) {{
              return new TestElement(tag);
            }},
            body: {{
              appendChild() {{}},
              removeChild() {{}},
            }},
            execCommand() {{
              return true;
            }},
          }},
          navigator: {{}},
          setTimeout(fn, ms, ...args) {{
            const scaled = ms === 500 ? 1000 : ms === 1200 ? 1 : ms;
            return setTimeout(fn, scaled, ...args);
          }},
          clearTimeout,
          setInterval,
          clearInterval,
          fetch(url, options) {{
            const body = options && options.body ? JSON.parse(options.body) : null;
            if (String(url).endsWith("/api/update-notification-config")) {{
              saveRequests.push({{ url: String(url), body }});
              return Promise.resolve(response({{ status: "success" }}));
            }}
            if (String(url).endsWith("/api/get-feedback-prompts")) {{
              return Promise.resolve(response({{ status: "success", config: {{}} }}));
            }}
            return Promise.resolve(response({{ status: "success" }}));
          }},
          __AIIA_showToast() {{}},
          AIIA_I18N: {{
            t(key) {{
              return key;
            }},
          }},
          AIIAWebviewNotifyCore: {{
            refreshNotificationSettingsFromServer: async () => ({{
              ok: true,
              settings: cachedSettings,
            }}),
            getCachedNotificationSettings: () => cachedSettings,
            setCachedNotificationSettings(next) {{
              cachedSettings = Object.assign({{}}, next || {{}});
            }},
          }},
        }};
        context.globalThis = context;
        context.window = context;

        vm.runInNewContext(source, context, {{ filename: "webview-settings-ui.js" }});

        const api = context.AIIAWebviewSettingsUi;
        await api.openSettings();

        const panel = element("settingsPanel");
        element("notifyEnabled").checked = true;
        panel.dispatch("input", {{ target: element("notifyEnabled") }});
        api.closeSettingsOverlay();

        await waitFor(() => saveRequests.length === 1, "close-flush save");
        await sleep(40);
        api.dispose();

        process.stdout.write(JSON.stringify({{
          saveRequests,
          overlayHidden: element("settingsOverlay").classList.contains("hidden"),
        }}));
        """
    )
    script = (
        "(async () => {\n"
        + script_body
        + "\n})().catch((err) => {\n"
        + (
            "  console.error(err && err.stack ? err.stack : err);\n"
            "  process.exit(1);\n"
            "});\n"
        )
    )

    assert json.loads(_run_node(script)) == {
        "saveRequests": [
            {
                "url": "http://server/api/update-notification-config",
                "body": {
                    "enabled": True,
                    "macosNativeEnabled": False,
                    "barkEnabled": False,
                    "barkUrl": "https://api.day.app/push",
                    "barkDeviceKey": "",
                    "barkIcon": "",
                    "barkAction": "none",
                    "barkUrlTemplate": "{base_url}/?task_id={task_id}",
                },
            }
        ],
        "overlayHidden": True,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_close_preserves_pending_autosave_after_inflight_response() -> None:
    source = SETTINGS_UI_JS.read_text(encoding="utf-8")
    script_body = textwrap.dedent(
        f"""
        const vm = require("vm");
        const source = {json.dumps(source)};
        const saveRequests = [];

        function sleep(ms) {{
          return new Promise((resolve) => setTimeout(resolve, ms));
        }}

        async function waitFor(predicate, label) {{
          const started = Date.now();
          while (Date.now() - started < 2000) {{
            if (predicate()) return;
            await sleep(5);
          }}
          throw new Error("Timed out waiting for " + label);
        }}

        class ClassList {{
          constructor(values) {{
            this.values = new Set(values || []);
          }}
          add(value) {{
            this.values.add(value);
          }}
          remove(value) {{
            this.values.delete(value);
          }}
          contains(value) {{
            return this.values.has(value);
          }}
          toggle(value, force) {{
            if (force === undefined ? !this.values.has(value) : force) {{
              this.values.add(value);
              return true;
            }}
            this.values.delete(value);
            return false;
          }}
        }}

        class TestElement {{
          constructor(id) {{
            this.id = id;
            this.checked = false;
            this.value = "";
            this.textContent = "";
            this.dataset = {{}};
            this.attributes = {{}};
            this.listeners = {{}};
            this.classList = new ClassList();
          }}
          addEventListener(type, handler) {{
            if (!this.listeners[type]) this.listeners[type] = [];
            this.listeners[type].push(handler);
          }}
          dispatch(type, event) {{
            const handlers = this.listeners[type] || [];
            const payload = Object.assign(
              {{
                target: this,
                preventDefault() {{}},
                stopPropagation() {{}},
              }},
              event || {{}},
            );
            for (const handler of handlers) handler(payload);
          }}
          getAttribute(name) {{
            return Object.prototype.hasOwnProperty.call(this.attributes, name)
              ? this.attributes[name]
              : "";
          }}
          setAttribute(name, value) {{
            this.attributes[name] = String(value);
          }}
          querySelectorAll() {{
            return [];
          }}
        }}

        const elements = {{}};
        function element(id) {{
          if (!elements[id]) elements[id] = new TestElement(id);
          return elements[id];
        }}

        element("aiia-config").setAttribute("data-server-url", "http://server");
        element("settingsOverlay").classList.add("hidden");
        element("settingsPanel");
        element("settingsHint");
        for (const id of [
          "notifyEnabled",
          "notifyMacOSNativeEnabled",
          "notifyBarkEnabled",
          "notifyBarkUrl",
          "notifyBarkDeviceKey",
          "notifyBarkIcon",
          "notifyBarkAction",
          "notifyBarkUrlTemplate",
        ]) {{
          element(id);
        }}

        let cachedSettings = {{
          enabled: false,
          macosNativeEnabled: false,
          barkEnabled: false,
          barkUrl: "https://api.day.app/push",
          barkDeviceKey: "",
          barkIcon: "",
          barkAction: "none",
          barkUrlTemplate: "{{base_url}}/?task_id={{task_id}}",
        }};
        let resolveFirstSave = null;

        function response(payload, status) {{
          return {{
            ok: !status || status < 400,
            status: status || 200,
            json: async () => payload,
          }};
        }}

        const context = {{
          console: {{
            debug() {{}},
            warn() {{}},
            error() {{}},
          }},
          document: {{
            getElementById(id) {{
              return Object.prototype.hasOwnProperty.call(elements, id)
                ? elements[id]
                : null;
            }},
            querySelectorAll() {{
              return [];
            }},
            createElement(tag) {{
              return new TestElement(tag);
            }},
            body: {{
              appendChild() {{}},
              removeChild() {{}},
            }},
            execCommand() {{
              return true;
            }},
          }},
          navigator: {{}},
          setTimeout(fn, ms, ...args) {{
            const scaled = ms === 500 ? 20 : ms === 1200 ? 1 : ms;
            return setTimeout(fn, scaled, ...args);
          }},
          clearTimeout,
          setInterval,
          clearInterval,
          fetch(url, options) {{
            const body = options && options.body ? JSON.parse(options.body) : null;
            if (String(url).endsWith("/api/update-notification-config")) {{
              saveRequests.push({{ url: String(url), body }});
              if (saveRequests.length === 1) {{
                return new Promise((resolve) => {{
                  resolveFirstSave = () =>
                    resolve(response({{ status: "success" }}));
                }});
              }}
              return Promise.resolve(response({{ status: "success" }}));
            }}
            if (String(url).endsWith("/api/get-feedback-prompts")) {{
              return Promise.resolve(response({{ status: "success", config: {{}} }}));
            }}
            return Promise.resolve(response({{ status: "success" }}));
          }},
          __AIIA_showToast() {{}},
          AIIA_I18N: {{
            t(key) {{
              return key;
            }},
          }},
          AIIAWebviewNotifyCore: {{
            refreshNotificationSettingsFromServer: async () => ({{
              ok: true,
              settings: cachedSettings,
            }}),
            getCachedNotificationSettings: () => cachedSettings,
            setCachedNotificationSettings(next) {{
              cachedSettings = Object.assign({{}}, next || {{}});
            }},
          }},
        }};
        context.globalThis = context;
        context.window = context;

        vm.runInNewContext(source, context, {{ filename: "webview-settings-ui.js" }});

        const api = context.AIIAWebviewSettingsUi;
        await api.openSettings();

        const panel = element("settingsPanel");
        element("notifyEnabled").checked = true;
        panel.dispatch("input", {{ target: element("notifyEnabled") }});
        await waitFor(() => saveRequests.length === 1, "first save");

        element("notifyBarkEnabled").checked = true;
        panel.dispatch("input", {{ target: element("notifyBarkEnabled") }});
        api.closeSettingsOverlay();

        await sleep(40);
        if (saveRequests.length !== 1) {{
          throw new Error("queued save should wait for the in-flight request");
        }}
        resolveFirstSave();
        await waitFor(() => saveRequests.length === 2, "post-close queued save");
        api.dispose();

        process.stdout.write(JSON.stringify({{
          saveRequests,
          overlayHidden: element("settingsOverlay").classList.contains("hidden"),
        }}));
        """
    )
    script = (
        "(async () => {\n"
        + script_body
        + "\n})().catch((err) => {\n"
        + (
            "  console.error(err && err.stack ? err.stack : err);\n"
            "  process.exit(1);\n"
            "});\n"
        )
    )

    assert json.loads(_run_node(script)) == {
        "saveRequests": [
            {
                "url": "http://server/api/update-notification-config",
                "body": {
                    "enabled": True,
                    "macosNativeEnabled": False,
                    "barkEnabled": False,
                    "barkUrl": "https://api.day.app/push",
                    "barkDeviceKey": "",
                    "barkIcon": "",
                    "barkAction": "none",
                    "barkUrlTemplate": "{base_url}/?task_id={task_id}",
                },
            },
            {
                "url": "http://server/api/update-notification-config",
                "body": {
                    "enabled": True,
                    "macosNativeEnabled": False,
                    "barkEnabled": True,
                    "barkUrl": "https://api.day.app/push",
                    "barkDeviceKey": "",
                    "barkIcon": "",
                    "barkAction": "none",
                    "barkUrlTemplate": "{base_url}/?task_id={task_id}",
                },
            },
        ],
        "overlayHidden": True,
    }
