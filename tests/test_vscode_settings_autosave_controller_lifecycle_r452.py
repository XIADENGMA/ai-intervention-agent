"""Runtime checks for VS Code settings autosave AbortController ownership."""

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


def _settings_harness(case_js: str) -> str:
    source = SETTINGS_UI_JS.read_text(encoding="utf-8")
    case_source = "(async () => {\n" + textwrap.indent(case_js, "  ") + "\n})()"
    return textwrap.dedent(
        f"""
        const vm = require("vm");
        const source = {json.dumps(source)};
        const saveRequests = [];
        const timers = [];
        const intervals = [];

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
          hasAttribute(name) {{
            return Object.prototype.hasOwnProperty.call(this.attributes, name);
          }}
          querySelectorAll() {{
            return [];
          }}
        }}

        function response(payload, status) {{
          return {{
            ok: !status || status < 400,
            status: status || 200,
            json: async () => payload,
          }};
        }}

        let nextControllerId = 0;
        class FakeAbortController {{
          constructor() {{
            this.id = ++nextControllerId;
            this.abortCount = 0;
            this.signal = {{
              aborted: false,
              __controller: this,
            }};
          }}
          abort() {{
            this.abortCount += 1;
            this.signal.aborted = true;
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
        element("settingsClose");
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

        const context = {{
          AbortController: FakeAbortController,
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
          process: {{
            stdout: {{
              write(text) {{
                process.stdout.write(String(text));
              }},
            }},
          }},
          setTimeout(fn, ms, ...args) {{
            const id = "timer-" + (timers.length + 1);
            timers.push({{ id, fn, ms, args, cleared: false, ran: false }});
            return id;
          }},
          clearTimeout(id) {{
            const timer = timers.find((entry) => entry.id === id);
            if (timer) timer.cleared = true;
          }},
          setInterval(fn, ms, ...args) {{
            const id = "interval-" + (intervals.length + 1);
            intervals.push({{ id, fn, ms, args, cleared: false }});
            return id;
          }},
          clearInterval(id) {{
            const timer = intervals.find((entry) => entry.id === id);
            if (timer) timer.cleared = true;
          }},
          fetch(url, options) {{
            const body = options && options.body ? JSON.parse(options.body) : null;
            if (String(url).endsWith("/api/update-notification-config")) {{
              const request = {{
                url: String(url),
                body,
                signal: options && options.signal,
              }};
              saveRequests.push(request);
              return new Promise(() => {{}});
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
          __saveRequests: saveRequests,
          __timers: timers,
        }};
        context.globalThis = context;
        context.window = context;

        function runNextTimer(ms) {{
          const timer = timers.find(
            (entry) => entry.ms === ms && !entry.cleared && !entry.ran,
          );
          if (!timer) throw new Error("Missing active timer for " + ms);
          timer.ran = true;
          timer.fn(...timer.args);
          return timer;
        }}
        context.__runNextTimer = runNextTimer;

        vm.runInNewContext(source, context, {{ filename: "webview-settings-ui.js" }});

        (async () => {{
          await vm.runInNewContext({case_source!r}, context);
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_disposed_save_timeout_does_not_abort_reopened_save() -> None:
    script = _settings_harness(
        """
        const api = AIIAWebviewSettingsUi;
        const panel = document.getElementById("settingsPanel");

        await api.openSettings();
        document.getElementById("notifyEnabled").checked = true;
        panel.dispatch("input", { target: document.getElementById("notifyEnabled") });
        __runNextTimer(500);

        const firstController = __saveRequests[0].signal.__controller;
        const firstSaveTimeout = __timers.find(
          (entry) => entry.ms === 3500 && !entry.cleared,
        );
        if (!firstSaveTimeout) throw new Error("missing first save timeout");

        api.dispose();

        await api.openSettings();
        document.getElementById("notifyBarkEnabled").checked = true;
        panel.dispatch("input", { target: document.getElementById("notifyBarkEnabled") });
        __runNextTimer(500);

        const secondController = __saveRequests[1].signal.__controller;
        firstSaveTimeout.fn();

        process.stdout.write(JSON.stringify({
          saveCount: __saveRequests.length,
          firstAbortCount: firstController.abortCount,
          secondAbortCount: secondController.abortCount,
          secondAborted: secondController.signal.aborted,
          firstTimeoutCleared: firstSaveTimeout.cleared,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "saveCount": 2,
        "firstAbortCount": 2,
        "secondAbortCount": 0,
        "secondAborted": False,
        "firstTimeoutCleared": False,
    }
