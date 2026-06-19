"""Runtime checks for VS Code feedback-config save ordering."""

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
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _vscode_settings_harness(case_js: str) -> str:
    source = SETTINGS_UI_JS.read_text(encoding="utf-8")
    return (
        "(async () => {\n"
        + textwrap.dedent(
            f"""
            const vm = require("vm");
            const source = {json.dumps(source)};
            const feedbackRequests = [];
            const hints = [];
            let getFeedbackPromptsHandler = null;

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
              "feedbackCountdown",
              "feedbackResubmitPrompt",
              "feedbackPromptSuffix",
              "settingsConfigPath",
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

            let resolveFirstFeedback = null;
            let rejectFirstFeedback = null;
            let resolveSecondFeedback = null;
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
                const scaled = ms === 800 ? 20 : ms === 1200 ? 1 : ms;
                return setTimeout(fn, scaled, ...args);
              }},
              clearTimeout,
              setInterval(fn, ms, ...args) {{
                return setInterval(fn, ms, ...args);
              }},
              clearInterval,
              fetch(url, options) {{
                const body = options && options.body ? JSON.parse(options.body) : null;
                if (String(url).endsWith("/api/update-feedback-config")) {{
                  feedbackRequests.push({{ url: String(url), body }});
                  if (feedbackRequests.length === 1) {{
                    return new Promise((resolve, reject) => {{
                      resolveFirstFeedback = () =>
                        resolve(response({{ status: "success" }}));
                      rejectFirstFeedback = () => reject(new Error("network down"));
                    }});
                  }}
                  if (feedbackRequests.length === 2) {{
                    return new Promise((resolve) => {{
                      resolveSecondFeedback = () =>
                        resolve(response({{ status: "success" }}));
                    }});
                  }}
                  return Promise.resolve(response({{ status: "success" }}));
                }}
                if (String(url).endsWith("/api/get-feedback-prompts")) {{
                  if (getFeedbackPromptsHandler) {{
                    return getFeedbackPromptsHandler(String(url), body);
                  }}
                  return Promise.resolve(
                    response({{
                      status: "success",
                      config: {{
                        frontend_countdown: 240,
                        resubmit_prompt: "",
                        prompt_suffix: "",
                      }},
                      meta: {{ config_file: "/tmp/config.toml" }},
                    }}),
                  );
                }}
                return Promise.resolve(response({{ status: "success" }}));
              }},
              __AIIA_showToast(message, options) {{
                hints.push({{ message: String(message), kind: options && options.kind }});
              }},
              __setGetFeedbackPromptsHandler(handler) {{
                getFeedbackPromptsHandler = handler;
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
                }},
              }},
            }};
            context.globalThis = context;
            context.window = context;

            vm.runInNewContext(source, context, {{ filename: "webview-settings-ui.js" }});
            const api = context.AIIAWebviewSettingsUi;

            {textwrap.indent(case_js, "            ")}
            """
        )
        + "\n})().catch((err) => {\n"
        + "  console.error(err && err.stack ? err.stack : err);\n"
        + "  process.exit(1);\n"
        + "});\n"
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_vscode_feedback_config_save_sends_queued_latest_payload() -> None:
    script = _vscode_settings_harness(
        """
        await api.openSettings();

        element("feedbackCountdown").value = "60";
        element("feedbackCountdown").dispatch("change");
        await waitFor(() => feedbackRequests.length === 1, "first feedback save");

        element("feedbackCountdown").value = "61";
        element("feedbackResubmitPrompt").value = "new prompt";
        element("feedbackCountdown").dispatch("change");
        element("feedbackResubmitPrompt").dispatch("input");

        await sleep(60);
        const beforeResolve = {
          requestCount: feedbackRequests.length,
          firstBody: feedbackRequests[0].body,
          feedbackHints: hints.filter((hint) =>
            hint.message.indexOf("settings.feedback.") === 0,
          ),
        };

        resolveFirstFeedback();
        await waitFor(() => feedbackRequests.length === 2, "queued feedback save");

        const afterFirstResolve = {
          requestCount: feedbackRequests.length,
          secondBody: feedbackRequests[1].body,
          feedbackHints: hints.filter((hint) =>
            hint.message.indexOf("settings.feedback.") === 0,
          ),
        };

        resolveSecondFeedback();
        await sleep(10);
        api.dispose();

        process.stdout.write(JSON.stringify({
          beforeResolve,
          afterFirstResolve,
          finalFeedbackHints: hints.filter((hint) =>
            hint.message.indexOf("settings.feedback.") === 0,
          ),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeResolve": {
            "requestCount": 1,
            "firstBody": {"frontend_countdown": 60},
            "feedbackHints": [],
        },
        "afterFirstResolve": {
            "requestCount": 2,
            "secondBody": {
                "frontend_countdown": 61,
                "resubmit_prompt": "new prompt",
            },
            "feedbackHints": [],
        },
        "finalFeedbackHints": [
            {"message": "settings.feedback.saved", "kind": "success"}
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_vscode_feedback_config_debounce_flushes_on_dispose() -> None:
    script = _vscode_settings_harness(
        """
        await api.openSettings();

        element("feedbackPromptSuffix").value = "before dispose";
        element("feedbackPromptSuffix").dispatch("input");
        api.dispose();

        const afterDispose = {
          requestCount: feedbackRequests.length,
          firstBody: feedbackRequests[0] && feedbackRequests[0].body,
        };

        await sleep(60);
        const afterDebounceWindow = {
          requestCount: feedbackRequests.length,
          firstBody: feedbackRequests[0] && feedbackRequests[0].body,
        };

        resolveFirstFeedback();
        await sleep(10);

        process.stdout.write(JSON.stringify({
          afterDispose,
          afterDebounceWindow,
          finalFeedbackHints: hints.filter((hint) =>
            hint.message.indexOf("settings.feedback.") === 0,
          ),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterDispose": {
            "requestCount": 1,
            "firstBody": {"prompt_suffix": "before dispose"},
        },
        "afterDebounceWindow": {
            "requestCount": 1,
            "firstBody": {"prompt_suffix": "before dispose"},
        },
        "finalFeedbackHints": [
            {"message": "settings.feedback.saved", "kind": "success"}
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_vscode_feedback_config_save_suppresses_stale_failure_before_retry() -> None:
    script = _vscode_settings_harness(
        """
        await api.openSettings();

        element("feedbackPromptSuffix").value = "first";
        element("feedbackPromptSuffix").dispatch("input");
        await waitFor(() => feedbackRequests.length === 1, "first feedback save");

        element("feedbackPromptSuffix").value = "latest";
        element("feedbackPromptSuffix").dispatch("input");

        await sleep(60);
        rejectFirstFeedback();
        await waitFor(() => feedbackRequests.length === 2, "queued feedback save");

        const afterFailure = {
          requestCount: feedbackRequests.length,
          secondBody: feedbackRequests[1].body,
          feedbackHints: hints.filter((hint) =>
            hint.message.indexOf("settings.feedback.") === 0,
          ),
        };

        resolveSecondFeedback();
        await sleep(10);
        api.dispose();

        process.stdout.write(JSON.stringify({
          afterFailure,
          finalFeedbackHints: hints.filter((hint) =>
            hint.message.indexOf("settings.feedback.") === 0,
          ),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "afterFailure": {
            "requestCount": 2,
            "secondBody": {"prompt_suffix": "latest"},
            "feedbackHints": [],
        },
        "finalFeedbackHints": [
            {"message": "settings.feedback.saved", "kind": "success"}
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_vscode_feedback_config_load_preserves_edit_made_during_load() -> None:
    script = _vscode_settings_harness(
        """
        let resolveLoad = null;
        context.__setGetFeedbackPromptsHandler(() =>
          new Promise((resolve) => {
            resolveLoad = () =>
              resolve(
                response({
                  status: "success",
                  config: {
                    frontend_countdown: 10,
                    resubmit_prompt: "server prompt",
                    prompt_suffix: "server suffix",
                  },
                  meta: { config_file: "/tmp/server.toml" },
                }),
              );
          }),
        );

        await api.openSettings();
        if (typeof resolveLoad !== "function") {
          throw new Error("feedback config load did not start");
        }

        element("feedbackPromptSuffix").value = "typed";
        element("feedbackPromptSuffix").dispatch("input");
        resolveLoad();
        await sleep(10);
        api.dispose();

        process.stdout.write(JSON.stringify({
          suffix: element("feedbackPromptSuffix").value,
          prompt: element("feedbackResubmitPrompt").value,
          countdown: element("feedbackCountdown").value,
          configPath: element("settingsConfigPath").value,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "suffix": "typed",
        "prompt": "",
        "countdown": "",
        "configPath": "/tmp/server.toml",
    }
