"""R452: VS Code submit fallback must not reuse a stale timeout signal."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _read_source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _extract_async_function(source: str, name: str) -> str:
    marker = f"async function {name}("
    start = source.index(marker)
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
    raise AssertionError(f"Could not extract {name}()")


def _submit_with_data_source() -> str:
    return _extract_async_function(_read_source(), "submitWithData")


def _run_node(script: str) -> dict[str, object]:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_submit_fallback_gets_fresh_timeout_controller() -> None:
    script = textwrap.dedent(
        f"""
        const SERVER_URL = '';
        const SUBMIT_TIMEOUT_MS = 20000;
        const SUBMIT_BTN_SPINNER_HTML = '<span>Submitting</span>';
        const SUBMIT_BTN_FALLBACK_HTML = '<span>Submit</span>';

        const timers = [];
        function setTimeout(fn, ms) {{
          const timer = {{ fn, ms, cleared: false }};
          timers.push(timer);
          return timer;
        }}
        function clearTimeout(timer) {{
          if (timer) timer.cleared = true;
        }}

        let nextControllerId = 0;
        class AbortController {{
          constructor() {{
            this.id = ++nextControllerId;
            this.abortCount = 0;
            this.signal = {{ controller: this, aborted: false }};
          }}
          abort() {{
            this.abortCount += 1;
            this.signal.aborted = true;
          }}
        }}

        class FormData {{
          constructor() {{
            this.entries = [];
          }}
          append(key, value) {{
            this.entries.push([key, String(value)]);
          }}
        }}

        const messages = [];
        const fetchCalls = [];
        const submitButton = {{ disabled: false, innerHTML: 'Submit', title: '' }};
        const textarea = {{ value: 'draft' }};
        const document = {{
          getElementById(id) {{
            if (id === 'submitBtn') return submitButton;
            if (id === 'feedbackText') return textarea;
            return null;
          }},
          querySelectorAll() {{
            return [];
          }},
        }};
        const vscode = {{
          postMessage(message) {{
            messages.push(message);
          }},
        }};

        let submitInFlight = false;
        let submitBackoffUntilMs = 0;
        let submitBackoffTimer = null;
        let submitBtnDefaultHtml = 'Submit';
        let currentConfig = null;
        let activeTaskId = null;
        let uploadedImages = [];
        let taskTextareaContents = {{ 'task-a': 'draft' }};
        let taskOptionsStates = {{ 'task-a': ['A'] }};
        let taskImages = {{ 'task-a': ['image'] }};
        const toasts = [];
        const logs = [];

        function stopCountdown() {{}}
        function appendUploadedImagesToFormData() {{
          return {{ appended: 0, dropped: 0 }};
        }}
        function renderUploadedImages() {{}}
        function syncImagesToTaskCache() {{}}
        function autoResizeFeedbackTextarea() {{}}
        function showToast(message, options) {{
          toasts.push({{ message, options }});
        }}
        function t(key, params) {{
          return params ? key + JSON.stringify(params) : key;
        }}
        function requestImmediateRefresh() {{}}
        function log(message) {{
          logs.push({{ level: 'log', message }});
        }}
        function logError(message) {{
          logs.push({{ level: 'error', message }});
        }}
        function applySubmitBackoffUi() {{
          if (submitBackoffTimer) {{
            clearTimeout(submitBackoffTimer);
            submitBackoffTimer = null;
          }}
          submitButton.title = t('ui.submit.label');
        }}

        function fetch(url, options) {{
          return new Promise((resolve, reject) => {{
            fetchCalls.push({{
              url,
              controller: options && options.signal ? options.signal.controller : null,
              bodyEntries: options && options.body ? options.body.entries : [],
              resolve,
              reject,
            }});
          }});
        }}

        {_submit_with_data_source()}

        (async () => {{
          const submitPromise = submitWithData('Answer', ['A'], 'task-a');
          if (fetchCalls.length !== 1) throw new Error('first submit request was not started');

          fetchCalls[0].resolve({{ ok: false, status: 404, headers: {{ get() {{ return ''; }} }} }});
          for (let i = 0; i < 10 && fetchCalls.length < 2; i += 1) {{
            await Promise.resolve();
          }}
          if (fetchCalls.length !== 2) throw new Error('fallback submit request was not started');

          const submitTimers = timers.filter(timer => timer.ms === SUBMIT_TIMEOUT_MS);
          const firstTimerClearedBeforeStaleFire = submitTimers[0] && submitTimers[0].cleared;
          const fallbackAbortBeforeStaleFire = fetchCalls[1].controller.abortCount;
          submitTimers[0].fn();
          const fallbackAbortAfterStaleFire = fetchCalls[1].controller.abortCount;

          fetchCalls[1].resolve({{ ok: true, status: 200, headers: {{ get() {{ return ''; }} }} }});
          const result = await submitPromise;

          process.stdout.write(JSON.stringify({{
            result,
            urls: fetchCalls.map(call => call.url),
            bodyEntries: fetchCalls[1].bodyEntries,
            submitTimerCount: submitTimers.length,
            firstTimerClearedBeforeStaleFire,
            secondTimerClearedAfterSuccess: submitTimers[1] && submitTimers[1].cleared,
            distinctControllers: fetchCalls[0].controller !== fetchCalls[1].controller,
            fallbackAbortBeforeStaleFire,
            fallbackAbortAfterStaleFire,
            submitInFlight,
            successLog: messages.find(message => (
              message.type === 'log' &&
              message.level === 'info' &&
              String(message.message || '').startsWith('[submit] ok')
            )),
            taskCacheCleared: (
              taskTextareaContents['task-a'] === undefined &&
              taskOptionsStates['task-a'] === undefined &&
              taskImages['task-a'] === undefined
            ),
          }}));
        }})().catch(error => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
    )

    assert _run_node(script) == {
        "result": True,
        "urls": ["/api/tasks/task-a/submit", "/api/submit"],
        "bodyEntries": [
            ["feedback_text", "Answer"],
            ["selected_options", '["A"]'],
            ["task_id", "task-a"],
        ],
        "submitTimerCount": 2,
        "firstTimerClearedBeforeStaleFire": True,
        "secondTimerClearedAfterSuccess": True,
        "distinctControllers": True,
        "fallbackAbortBeforeStaleFire": 0,
        "fallbackAbortAfterStaleFire": 0,
        "submitInFlight": False,
        "successLog": {
            "type": "log",
            "level": "info",
            "message": "[submit] ok taskId=task-a path=/api/submit",
        },
        "taskCacheCleared": True,
    }
