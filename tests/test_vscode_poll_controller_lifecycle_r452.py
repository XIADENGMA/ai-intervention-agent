"""R452: VS Code webview polling abort controllers must be run-owned."""

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


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    if source[max(0, start - 6) : start] == "async ":
        start -= 6
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


def _polling_functions() -> str:
    source = _read_source()
    return "\n\n".join(
        _extract_function(source, name)
        for name in ("stopPolling", "handleTasksPollFailure", "pollAllData")
    )


def test_stale_tasks_timeout_and_finally_do_not_touch_new_poll_controller() -> None:
    script = textwrap.dedent(
        f"""
        const document = {{ hidden: false }};
        const SERVER_URL = '';
        const POLL_TASKS_TIMEOUT_MS = 10;
        const POLL_CONFIG_TIMEOUT_MS = 20;
        const POLL_IDLE_MS = 1000;

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

        let pollingEnabled = true;
        let pollingToken = 1;
        let pollingTimer = null;
        let pollingInFlight = false;
        let pollAbortController = null;
        let pollingRunId = 0;
        let activePollingRunId = 0;
        let currentConfig = {{ task_id: 'task-1' }};
        let allTasks = [];
        let activeTaskId = null;
        let taskDeadlines = {{}};
        let tabCountdownRemaining = {{}};
        let taskTextareaContents = {{}};
        let taskOptionsStates = {{}};
        let taskImages = {{}};
        let pendingImageUploadCounts = {{}};
        let lastTasksHash = '';
        let lastTaskIds = new Set();
        let hasInitializedTaskIdTracking = false;
        let pollSuggestedDelayMs = null;
        let serverTimeOffset = 0;
        const fetches = [];

        function _disconnectSSE() {{}}
        function updateServerStatus() {{}}
        function hideTabs() {{}}
        function showNoContent() {{}}
        function clearAllTabCountdowns() {{}}
        function schedulePersistUiState() {{}}
        function renderTaskTabs() {{}}
        function log() {{}}
        async function pollConfig() {{ return true; }}
        function fetch(url, options) {{
          return new Promise((resolve, reject) => {{
            fetches.push({{
              url,
              controller: options && options.signal ? options.signal.controller : null,
              resolve,
              reject,
            }});
          }});
        }}

        {_polling_functions()}

        (async () => {{
          const firstPoll = pollAllData('poll');
          const firstController = pollAbortController;
          stopPolling();

          const secondPoll = pollAllData('poll');
          const secondController = pollAbortController;
          const staleTasksTimer = timers.find(timer => timer.ms === POLL_TASKS_TIMEOUT_MS && !timer.cleared);
          if (!staleTasksTimer) throw new Error('missing first tasks timeout');
          staleTasksTimer.fn();

          const abortError = new Error('aborted');
          abortError.name = 'AbortError';
          fetches[0].reject(abortError);
          const firstResult = await firstPoll;
          await Promise.resolve();

          process.stdout.write(JSON.stringify({{
            firstResult,
            firstControllerAbortCount: firstController.abortCount,
            secondControllerAbortCount: secondController.abortCount,
            currentControllerId: pollAbortController && pollAbortController.id,
            secondControllerId: secondController.id,
            pollingInFlight,
            activePollingRunId,
            fetchCount: fetches.length,
            secondPollPending: secondPoll instanceof Promise,
          }}));
        }})().catch(error => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
    )

    assert _run_node(script) == {
        "firstResult": False,
        "firstControllerAbortCount": 2,
        "secondControllerAbortCount": 0,
        "currentControllerId": 2,
        "secondControllerId": 2,
        "pollingInFlight": True,
        "activePollingRunId": 2,
        "fetchCount": 2,
        "secondPollPending": True,
    }


def test_stale_config_timeout_does_not_abort_new_poll_controller() -> None:
    script = textwrap.dedent(
        f"""
        const document = {{ hidden: false }};
        const SERVER_URL = '';
        const POLL_TASKS_TIMEOUT_MS = 10;
        const POLL_CONFIG_TIMEOUT_MS = 20;
        const POLL_IDLE_MS = 1000;

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

        let pollingEnabled = true;
        let pollingToken = 1;
        let pollingTimer = null;
        let pollingInFlight = false;
        let pollAbortController = null;
        let pollingRunId = 0;
        let activePollingRunId = 0;
        let currentConfig = {{ task_id: 'task-1' }};
        let allTasks = [];
        let activeTaskId = null;
        let taskDeadlines = {{}};
        let tabCountdownRemaining = {{}};
        let taskTextareaContents = {{}};
        let taskOptionsStates = {{}};
        let taskImages = {{}};
        let pendingImageUploadCounts = {{}};
        let lastTasksHash = '';
        let lastTaskIds = new Set();
        let hasInitializedTaskIdTracking = false;
        let pollSuggestedDelayMs = null;
        let serverTimeOffset = 0;
        const fetches = [];
        const pollConfigCalls = [];

        function _disconnectSSE() {{}}
        function updateServerStatus() {{}}
        function hideTabs() {{}}
        function showNoContent() {{}}
        function clearAllTabCountdowns() {{}}
        function schedulePersistUiState() {{}}
        function renderTaskTabs() {{}}
        function log() {{}}
        function fetch(url, options) {{
          const entry = {{
            url,
            controller: options && options.signal ? options.signal.controller : null,
          }};
          fetches.push(entry);
          if (fetches.length === 1) {{
            return Promise.resolve({{
              ok: true,
              async json() {{
                return {{ success: true, tasks: [{{ task_id: 'task-1', status: 'active' }}] }};
              }},
            }});
          }}
          return new Promise((resolve, reject) => {{
            entry.resolve = resolve;
            entry.reject = reject;
          }});
        }}
        async function pollConfig(fetchOptions) {{
          return new Promise((resolve, reject) => {{
            pollConfigCalls.push({{
              controller: fetchOptions && fetchOptions.signal ? fetchOptions.signal.controller : null,
              resolve,
              reject,
            }});
          }});
        }}

        {_polling_functions()}

        (async () => {{
          const firstPoll = pollAllData('poll');
          for (let i = 0; i < 10 && pollConfigCalls.length === 0; i += 1) {{
            await Promise.resolve();
          }}
          if (pollConfigCalls.length !== 1) throw new Error('pollConfig was not reached');
          const configController = pollAbortController;
          const staleConfigTimer = timers.find(timer => timer.ms === POLL_CONFIG_TIMEOUT_MS && !timer.cleared);
          if (!staleConfigTimer) throw new Error('missing config timeout');

          stopPolling();
          const secondPoll = pollAllData('poll');
          const secondController = pollAbortController;
          staleConfigTimer.fn();

          const abortError = new Error('aborted');
          abortError.name = 'AbortError';
          pollConfigCalls[0].reject(abortError);
          const firstResult = await firstPoll;
          await Promise.resolve();

          process.stdout.write(JSON.stringify({{
            firstResult,
            configControllerAbortCount: configController.abortCount,
            secondControllerAbortCount: secondController.abortCount,
            currentControllerId: pollAbortController && pollAbortController.id,
            secondControllerId: secondController.id,
            pollingInFlight,
            activePollingRunId,
            fetchCount: fetches.length,
            secondPollPending: secondPoll instanceof Promise,
          }}));
        }})().catch(error => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
    )

    assert _run_node(script) == {
        "firstResult": False,
        "configControllerAbortCount": 2,
        "secondControllerAbortCount": 0,
        "currentControllerId": 3,
        "secondControllerId": 3,
        "pollingInFlight": True,
        "activePollingRunId": 2,
        "fetchCount": 2,
        "secondPollPending": True,
    }
