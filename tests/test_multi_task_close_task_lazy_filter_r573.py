"""R573 regression coverage for lazy close-task list removal."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def _multi_task_harness(case_js: str) -> str:
    case_source = "(async () => {\n" + textwrap.indent(case_js, "  ") + "\n})()"
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(MULTI_TASK_JS)!r}, 'utf8');

        const clearedIntervals = [];
        const requests = [];
        const sandbox = {{
          Date,
          Error,
          JSON,
          Math,
          Number,
          Object,
          Promise,
          String,
          URL,
          URLSearchParams,
          Array,
          console: {{ debug() {{}}, error() {{}}, info() {{}}, log() {{}}, warn() {{}} }},
          process: {{
            stdout: {{
              write(text) {{
                process.stdout.write(String(text));
              }},
            }},
          }},
          confirm() {{ return true; }},
          document: {{
            hidden: false,
            readyState: 'complete',
            addEventListener() {{}},
            createElement(tagName) {{
              return {{
                tagName: String(tagName || 'div').toUpperCase(),
                classList: {{ add() {{}}, remove() {{}}, toggle() {{}} }},
                appendChild(child) {{ return child; }},
                addEventListener() {{}},
                querySelectorAll() {{ return []; }},
              }};
            }},
            getElementById() {{ return null; }},
          }},
          fetchWithTimeout: async (url, options, timeout) => {{
            requests.push({{ url: String(url), method: options && options.method, timeout }});
            return {{
              ok: true,
              json: async () => ({{ success: true }}),
            }};
          }},
          setTimeout() {{ return 'timeout-id'; }},
          clearTimeout() {{}},
          setInterval() {{ return 'interval-id'; }},
          clearInterval(id) {{ clearedIntervals.push(String(id)); }},
          location: {{
            href: 'http://127.0.0.1/',
            search: '',
            origin: 'http://127.0.0.1',
            pathname: '/',
          }},
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent() {{}},
          CustomEvent: function CustomEvent(type, init) {{
            this.type = type;
            this.detail = init && init.detail;
          }},
          currentTasks: [],
          activeTaskId: null,
          taskCountdowns: {{}},
          tasksPollingTimer: null,
          taskTextareaContents: {{}},
          taskOptionsStates: {{}},
          taskImages: {{}},
          pendingNewTaskCount: 0,
          newTaskHintTimer: null,
          tasksHealthCheckTimer: null,
          hasLoadedTaskSnapshot: true,
          serverTimeOffset: 0,
          taskDeadlines: {{}},
          feedbackPrompts: {{}},
          autoSubmitAttempted: {{}},
          selectedImages: [],
          AIIA_DEBUG: false,
          AIIA_I18N: {{ t: (key) => key }},
          __clearedIntervals: clearedIntervals,
          __requests: requests,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox, {{ filename: 'multi_task.js' }});
        sandbox.api = sandbox.window.multiTaskModule;

        (async () => {{
          await vm.runInContext({case_source!r}, sandbox);
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


def _run_node(script: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


def test_close_task_uses_lazy_removal_helper() -> None:
    source = _source()
    close_task = _extract_function(source, "async function closeTask(")
    helper = _extract_function(source, "function removeTaskFromCurrentTasks(")

    assert (
        "currentTasks = removeTaskFromCurrentTasks(currentTasks, taskId)" in close_task
    )
    assert "currentTasks.filter" not in close_task
    assert ".filter(" not in helper
    assert "let keptTasks = null" in helper
    assert "keptTasks.push(task)" in helper
    assert "return keptTasks === null ? tasks : keptTasks" in helper


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_close_task_removes_matches_and_switches_without_array_filter() -> None:
    script = _multi_task_harness(
        """
        let renderCount = 0;
        let switchedTo = null;
        let noContentCount = 0;
        renderTaskTabs = () => { renderCount += 1; };
        switchTask = (taskId) => {
          switchedTo = taskId;
          setActiveTaskId(taskId);
        };
        showNoContentPage = () => { noContentCount += 1; };

        window.currentTasks = [
          { task_id: 'done-before', status: 'completed' },
          { task_id: 'remove-me', status: 'active' },
          { task_id: 'next-open', status: 'pending' },
          { task_id: 'remove-me', status: 'pending' },
          { task_id: 'after-open', status: 'pending' },
        ];
        currentTasks = window.currentTasks;
        const originalTasks = currentTasks;
        setActiveTaskId('remove-me');
        taskCountdowns['remove-me'] = { timer: 'timer-remove' };
        taskDeadlines['remove-me'] = 1700000000;
        taskTextareaContents['remove-me'] = 'draft';
        taskOptionsStates['remove-me'] = { 'option-0': true };
        taskImages['remove-me'] = [{ name: 'stale.png' }];
        autoSubmitAttempted['remove-me'] = 1700000001;

        const originalFilter = Array.prototype.filter;
        Array.prototype.filter = function disabledFilter() {
          throw new Error('Array.prototype.filter must not be used by closeTask');
        };
        try {
          await api.closeTask('remove-me');
        } finally {
          Array.prototype.filter = originalFilter;
        }

        process.stdout.write(JSON.stringify({
          ids: currentTasks.map((task) => task.task_id),
          statuses: currentTasks.map((task) => task.status),
          newArray: currentTasks !== originalTasks,
          windowSynced: window.currentTasks === currentTasks,
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          switchedTo,
          renderCount,
          noContentCount,
          requests: window.__requests,
          clearedIntervals: window.__clearedIntervals,
          hasCountdown: Object.prototype.hasOwnProperty.call(taskCountdowns, 'remove-me'),
          hasDeadline: Object.prototype.hasOwnProperty.call(taskDeadlines, 'remove-me'),
          hasDraft: Object.prototype.hasOwnProperty.call(taskTextareaContents, 'remove-me'),
          hasOptions: Object.prototype.hasOwnProperty.call(taskOptionsStates, 'remove-me'),
          hasImages: Object.prototype.hasOwnProperty.call(taskImages, 'remove-me'),
          hasAutoSubmit: Object.prototype.hasOwnProperty.call(autoSubmitAttempted, 'remove-me'),
        }));
        """
    )

    assert _run_node(script) == {
        "ids": ["done-before", "next-open", "after-open"],
        "statuses": ["completed", "pending", "pending"],
        "newArray": True,
        "windowSynced": True,
        "activeTaskId": "next-open",
        "windowActiveTaskId": "next-open",
        "switchedTo": "next-open",
        "renderCount": 1,
        "noContentCount": 0,
        "requests": [
            {
                "url": "/api/tasks/remove-me/close",
                "method": "POST",
                "timeout": 10000,
            }
        ],
        "clearedIntervals": ["timer-remove"],
        "hasCountdown": False,
        "hasDeadline": False,
        "hasDraft": False,
        "hasOptions": False,
        "hasImages": False,
        "hasAutoSubmit": False,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_close_task_missing_id_preserves_list_reference_without_array_filter() -> None:
    script = _multi_task_harness(
        """
        let renderCount = 0;
        let switchCount = 0;
        renderTaskTabs = () => { renderCount += 1; };
        switchTask = () => { switchCount += 1; };

        window.currentTasks = [
          { task_id: 'keep-a', status: 'pending' },
          { task_id: 'keep-b', status: 'pending' },
        ];
        currentTasks = window.currentTasks;
        const originalTasks = currentTasks;
        setActiveTaskId('keep-a');

        const originalFilter = Array.prototype.filter;
        Array.prototype.filter = function disabledFilter() {
          throw new Error('Array.prototype.filter must not be used by closeTask');
        };
        try {
          await api.closeTask('missing');
        } finally {
          Array.prototype.filter = originalFilter;
        }

        process.stdout.write(JSON.stringify({
          ids: currentTasks.map((task) => task.task_id),
          sameArray: currentTasks === originalTasks,
          windowSynced: window.currentTasks === originalTasks,
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          renderCount,
          switchCount,
          requests: window.__requests,
        }));
        """
    )

    assert _run_node(script) == {
        "ids": ["keep-a", "keep-b"],
        "sameArray": True,
        "windowSynced": True,
        "activeTaskId": "keep-a",
        "windowActiveTaskId": "keep-a",
        "renderCount": 1,
        "switchCount": 0,
        "requests": [
            {
                "url": "/api/tasks/missing/close",
                "method": "POST",
                "timeout": 10000,
            }
        ],
    }
