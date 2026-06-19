"""R452: VS Code webview task poll failures must not discard local drafts."""

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


def _run_node(script: str) -> str:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_success_false_tasks_payload_preserves_visible_task_drafts() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in ("handleTasksPollFailure", "pollAllData")
    )
    script = textwrap.dedent(
        f"""
        const calls = [];
        const document = {{ hidden: false }};
        const SERVER_URL = '';
        const POLL_TASKS_TIMEOUT_MS = 10;
        const POLL_CONFIG_TIMEOUT_MS = 10;
        const POLL_IDLE_MS = 1000;
        const AbortController = undefined;
        let pollingInFlight = false;
        let pollAbortController = null;
        let pollingRunId = 0;
        let activePollingRunId = 0;
        let tasksTimeoutId = null;
        let configTimeoutId = null;
        let currentConfig = {{ task_id: 'task-1' }};
        let allTasks = [{{ task_id: 'task-1', status: 'active' }}];
        let activeTaskId = 'task-1';
        let taskDeadlines = {{ 'task-1': 123 }};
        let tabCountdownRemaining = {{ 'task-1': 45 }};
        let taskTextareaContents = {{ 'task-1': 'draft text' }};
        let taskOptionsStates = {{ 'task-1': {{ 0: true }} }};
        let taskImages = {{ 'task-1': [{{ name: 'shot.png', data: 'data:image/png;base64,AA==' }}] }};
        let pendingImageUploadCounts = {{ 'task:task-1': 1 }};
        let lastTasksHash = 'task-1:active';
        let lastTaskIds = new Set(['task-1']);
        let hasInitializedTaskIdTracking = true;
        let serverTimeOffset = 0;
        let pollSuggestedDelayMs = null;

        async function fetch(url, options) {{
          calls.push('fetch:' + url + ':cache=' + options.cache);
          return {{
            ok: true,
            async json() {{
              return {{ success: false, error: 'temporary failure' }};
            }},
          }};
        }}
        function updateServerStatus(connected) {{ calls.push('status:' + connected); }}
        function hideTabs() {{ calls.push('hideTabs'); }}
        function showNoContent() {{ calls.push('showNoContent'); }}
        function clearAllTabCountdowns() {{ calls.push('clearCountdowns'); }}
        function schedulePersistUiState() {{ calls.push('persist'); }}
        function renderTaskTabs() {{ calls.push('renderTabs'); }}
        async function pollConfig() {{
          calls.push('pollConfig');
          return true;
        }}
        function log(message) {{ calls.push('log:' + String(message)); }}

        {parts}

        pollAllData('poll').then(result => {{
          process.stdout.write(JSON.stringify({{
            result,
            pollingInFlight,
            allTasks,
            activeTaskId,
            taskDeadlines,
            tabCountdownRemaining,
            taskTextareaContents,
            taskOptionsStates,
            taskImages,
            pendingImageUploadCounts,
            lastTasksHash,
            lastTaskIds: Array.from(lastTaskIds),
            hasInitializedTaskIdTracking,
            pollSuggestedDelayMs,
            calls,
          }}));
        }});
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": False,
        "pollingInFlight": False,
        "allTasks": [{"task_id": "task-1", "status": "active"}],
        "activeTaskId": "task-1",
        "taskDeadlines": {"task-1": 123},
        "tabCountdownRemaining": {"task-1": 45},
        "taskTextareaContents": {"task-1": "draft text"},
        "taskOptionsStates": {"task-1": {"0": True}},
        "taskImages": {
            "task-1": [{"name": "shot.png", "data": "data:image/png;base64,AA=="}]
        },
        "pendingImageUploadCounts": {"task:task-1": 1},
        "lastTasksHash": "task-1:active",
        "lastTaskIds": ["task-1"],
        "hasInitializedTaskIdTracking": True,
        "pollSuggestedDelayMs": None,
        "calls": [
            "fetch:/api/tasks:cache=no-store",
            "status:true",
            "status:false",
        ],
    }


def test_empty_successful_tasks_payload_still_clears_task_drafts() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in ("handleTasksPollFailure", "pollAllData")
    )
    script = textwrap.dedent(
        f"""
        const calls = [];
        const document = {{ hidden: false }};
        const SERVER_URL = '';
        const POLL_TASKS_TIMEOUT_MS = 10;
        const POLL_CONFIG_TIMEOUT_MS = 10;
        const POLL_IDLE_MS = 1000;
        const AbortController = undefined;
        Math.random = () => 0;
        let pollingInFlight = false;
        let pollAbortController = null;
        let pollingRunId = 0;
        let activePollingRunId = 0;
        let currentConfig = {{ task_id: 'task-1' }};
        let allTasks = [{{ task_id: 'task-1', status: 'active' }}];
        let activeTaskId = 'task-1';
        let taskDeadlines = {{ 'task-1': 123 }};
        let tabCountdownRemaining = {{ 'task-1': 45 }};
        let taskTextareaContents = {{ 'task-1': 'draft text' }};
        let taskOptionsStates = {{ 'task-1': {{ 0: true }} }};
        let taskImages = {{ 'task-1': [{{ name: 'shot.png', data: 'data:image/png;base64,AA==' }}] }};
        let pendingImageUploadCounts = {{ 'task:task-1': 1, current: 1 }};
        let lastTasksHash = 'task-1:active';
        let lastTaskIds = new Set(['task-1']);
        let hasInitializedTaskIdTracking = false;
        let serverTimeOffset = 0;
        let pollSuggestedDelayMs = null;

        async function fetch(url, options) {{
          calls.push('fetch:' + url + ':cache=' + options.cache);
          return {{
            ok: true,
            async json() {{
              return {{ success: true, tasks: [] }};
            }},
          }};
        }}
        function updateServerStatus(connected) {{ calls.push('status:' + connected); }}
        function hideTabs() {{ calls.push('hideTabs'); }}
        function showNoContent() {{ calls.push('showNoContent'); }}
        function clearAllTabCountdowns() {{ calls.push('clearCountdowns'); }}
        function schedulePersistUiState() {{ calls.push('persist'); }}
        function renderTaskTabs() {{ calls.push('renderTabs'); }}
        async function pollConfig() {{
          calls.push('pollConfig');
          return true;
        }}
        function log(message) {{ calls.push('log:' + String(message)); }}

        {parts}

        pollAllData('poll').then(result => {{
          process.stdout.write(JSON.stringify({{
            result,
            pollingInFlight,
            allTasks,
            activeTaskId,
            taskDeadlines,
            taskTextareaContents,
            taskOptionsStates,
            taskImages,
            pendingImageUploadCounts,
            lastTasksHash,
            lastTaskIds: Array.from(lastTaskIds),
            hasInitializedTaskIdTracking,
            pollSuggestedDelayMs,
            calls,
          }}));
        }});
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": True,
        "pollingInFlight": False,
        "allTasks": [],
        "activeTaskId": None,
        "taskDeadlines": {},
        "taskTextareaContents": {},
        "taskOptionsStates": {},
        "taskImages": {},
        "pendingImageUploadCounts": {},
        "lastTasksHash": "",
        "lastTaskIds": [],
        "hasInitializedTaskIdTracking": True,
        "pollSuggestedDelayMs": 1000,
        "calls": [
            "fetch:/api/tasks:cache=no-store",
            "status:true",
            "clearCountdowns",
            "persist",
            "hideTabs",
            "showNoContent",
        ],
    }
