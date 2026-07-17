"""R574 regression coverage for direct task-list lookup helpers."""

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
        const elements = new Map();
        function createClassList() {{
          return {{ add() {{}}, remove() {{}}, toggle() {{}}, contains() {{ return false; }} }};
        }}
        function createElement(tagName, id) {{
          return {{
            tagName: String(tagName || 'div').toUpperCase(),
            id: id || '',
            value: '',
            textContent: '',
            checked: false,
            classList: createClassList(),
            dataset: {{}},
            style: {{}},
            children: [],
            appendChild(child) {{ this.children.push(child); return child; }},
            addEventListener() {{}},
            removeEventListener() {{}},
            querySelector() {{ return null; }},
            querySelectorAll() {{ return []; }},
            setAttribute() {{}},
            removeAttribute() {{}},
          }};
        }}
        const sandbox = {{
          Date,
          Error,
          FormData: function FormData() {{
            this.entries = [];
            this.append = (key, value) => {{ this.entries.push([key, value]); }};
          }},
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
            createElement(tagName) {{ return createElement(tagName); }},
            createDocumentFragment() {{ return createElement('fragment'); }},
            getElementById(id) {{
              if (!elements.has(id)) elements.set(id, createElement('div', id));
              return elements.get(id);
            }},
          }},
          fetchWithTimeout: async (url, options, timeout) => {{
            requests.push({{ url: String(url), method: options && options.method, timeout }});
            return {{
              ok: true,
              json: async () => ({{ success: true }}),
            }};
          }},
          setTimeout(fn) {{ fn(); return 'timeout-id'; }},
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
          __elements: elements,
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


def test_task_list_lookups_use_direct_helpers() -> None:
    source = _source()
    lookup_helpers = [
        _extract_function(source, "function findTaskById("),
        _extract_function(source, "function findOpenTaskById("),
        _extract_function(source, "function findFirstOpenTask("),
    ]

    assert ".find(" not in source
    assert "findTaskById(window.currentTasks || [], taskId)" in source
    assert "const cachedTask = findTaskById(currentTasks, taskId)" in source
    assert "const target = findOpenTaskById(tasks, pendingDeepLinkedTaskId)" in source
    assert "const nextTask = findFirstOpenTask(currentTasks)" in source
    assert "const nextTask = findFirstOpenTask(currentTasks, taskId)" in source
    for helper in lookup_helpers:
        assert ".find(" not in helper
        assert (
            "for (let taskIndex = 0; taskIndex < taskCount; taskIndex += 1)" in helper
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_lookup_helpers_preserve_predicates_without_array_find() -> None:
    script = _multi_task_harness(
        """
        const originalFind = Array.prototype.find;
        Array.prototype.find = function disabledFind() {
          throw new Error('Array.prototype.find must not be used by task lookups');
        };
        try {
          const tasks = [
            { task_id: 'done', status: 'completed' },
            null,
            { task_id: 'target', status: 'completed', prompt: 'completed duplicate' },
            { task_id: 'target', status: 'pending', prompt: 'open duplicate' },
            { task_id: 42, status: 'pending', prompt: 'numeric id' },
            { task_id: 'other', status: 'active', prompt: 'other open' },
          ];
          const firstTarget = findTaskById(tasks, 'target');
          const openTarget = findOpenTaskById(tasks, 'target');
          const strictMiss = findTaskById(tasks, '42');
          const numericHit = findTaskById(tasks, 42);
          const firstOpen = findFirstOpenTask(tasks);
          const firstOpenExcludingTarget = findFirstOpenTask(tasks, 'target');
          process.stdout.write(JSON.stringify({
            firstTargetPrompt: firstTarget && firstTarget.prompt,
            openTargetPrompt: openTarget && openTarget.prompt,
            strictMiss,
            numericHitPrompt: numericHit && numericHit.prompt,
            firstOpenId: firstOpen && firstOpen.task_id,
            firstOpenExcludingTargetId: firstOpenExcludingTarget && firstOpenExcludingTarget.task_id,
          }));
        } finally {
          Array.prototype.find = originalFind;
        }
        """
    )

    assert _run_node(script) == {
        "firstTargetPrompt": "completed duplicate",
        "openTargetPrompt": "open duplicate",
        "strictMiss": None,
        "numericHitPrompt": "numeric id",
        "firstOpenId": "target",
        "firstOpenExcludingTargetId": 42,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_close_task_switches_to_first_open_task_without_array_find() -> None:
    script = _multi_task_harness(
        """
        let switchedTo = null;
        renderTaskTabs = () => {};
        switchTask = (taskId) => {
          switchedTo = taskId;
          setActiveTaskId(taskId);
        };

        window.currentTasks = [
          { task_id: 'done-before', status: 'completed' },
          { task_id: 'closing', status: 'active' },
          { task_id: 'next-open', status: 'pending' },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('closing');

        const originalFind = Array.prototype.find;
        Array.prototype.find = function disabledFind() {
          throw new Error('Array.prototype.find must not be used by closeTask');
        };
        try {
          await api.closeTask('closing');
        } finally {
          Array.prototype.find = originalFind;
        }

        process.stdout.write(JSON.stringify({
          ids: currentTasks.map((task) => task.task_id),
          switchedTo,
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
        }));
        """
    )

    assert _run_node(script) == {
        "ids": ["done-before", "next-open"],
        "switchedTo": "next-open",
        "activeTaskId": "next-open",
        "windowActiveTaskId": "next-open",
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_switch_task_uses_cached_task_without_array_find() -> None:
    script = _multi_task_harness(
        """
        let renderedTabs = 0;
        let updatedPrompt = null;
        let updatedOptions = null;
        let loadedTask = null;
        renderTaskTabs = () => { renderedTabs += 1; };
        updateCountdownRingColors = () => {};
        updateDescriptionDisplay = (prompt) => { updatedPrompt = prompt; };
        updateOptionsDisplay = (options) => { updatedOptions = options; };
        updateFeedbackPlaceholder = () => {};
        updateYesnoButtonGroup = () => {};
        updateHeaderChip = () => {};
        loadTaskDetails = async (taskId) => { loadedTask = taskId; };

        window.currentTasks = [
          { task_id: 'old', status: 'pending', prompt: 'Old prompt' },
          {
            task_id: 'next',
            status: 'pending',
            prompt: 'Next prompt',
            predefined_options: ['a', 'b'],
            predefined_options_defaults: [true, false],
          },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('old');

        const originalFind = Array.prototype.find;
        Array.prototype.find = function disabledFind() {
          throw new Error('Array.prototype.find must not be used by switchTask');
        };
        try {
          await api.switchTask('next');
        } finally {
          Array.prototype.find = originalFind;
        }

        process.stdout.write(JSON.stringify({
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          renderedTabs,
          updatedPrompt,
          updatedOptions,
          loadedTask,
        }));
        """
    )

    assert _run_node(script) == {
        "activeTaskId": "next",
        "windowActiveTaskId": "next",
        "renderedTabs": 1,
        "updatedPrompt": "Next prompt",
        "updatedOptions": ["a", "b"],
        "loadedTask": "next",
    }
