"""Runtime checks for ``multi_task.js`` active task reconciliation."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


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


def _multi_task_harness(case_js: str) -> str:
    case_source = "(async () => {\n" + textwrap.indent(case_js, "  ") + "\n})()"
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(MULTI_TASK_JS)!r}, 'utf8');

        function createClassList() {{
          return {{
            add() {{}},
            remove() {{}},
            toggle() {{}},
            contains() {{ return false; }},
          }};
        }}

        function createElement(tagName, id) {{
          return {{
            tagName: String(tagName || 'div').toUpperCase(),
            id: id || '',
            value: '',
            checked: false,
            style: {{}},
            dataset: {{}},
            children: [],
            textContent: '',
            innerHTML: '',
            classList: createClassList(),
            attributes: {{}},
            addEventListener() {{}},
            removeEventListener() {{}},
            appendChild(child) {{
              this.children.push(child);
              return child;
            }},
            remove() {{
              this.removed = true;
            }},
            setAttribute(name, value) {{
              this.attributes[name] = String(value);
            }},
            removeAttribute(name) {{
              delete this.attributes[name];
            }},
            querySelector() {{
              return null;
            }},
            querySelectorAll() {{
              return [];
            }},
          }};
        }}

        const documentListeners = [];
        const timeouts = [];
        const intervals = [];
        const clearedIntervals = [];
        const loadRequests = [];

        const sandbox = {{
          Date,
          Error,
          JSON,
          Math,
          Object,
          Promise,
          String,
          URL,
          URLSearchParams,
          Array,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          process: {{
            stdout: {{
              write(text) {{
                process.stdout.write(String(text));
              }},
            }},
          }},
          document: {{
            hidden: false,
            readyState: 'complete',
            addEventListener(type, handler) {{
              documentListeners.push({{ type, handler }});
            }},
            createDocumentFragment() {{
              return createElement('fragment', 'fragment');
            }},
            createElement(tagName) {{
              return createElement(tagName, '');
            }},
            getElementById() {{
              return null;
            }},
          }},
          fetchWithTimeout: (url) => {{
            loadRequests.push(String(url));
            return new Promise(() => {{}});
          }},
          fetch: async () => ({{
            ok: true,
            json: async () => ({{ success: true }}),
          }}),
          setTimeout(fn, delay) {{
            const id = 'timeout-' + (timeouts.length + 1);
            timeouts.push({{ id, fn, delay, cleared: false }});
            return id;
          }},
          clearTimeout(id) {{
            const timer = timeouts.find((entry) => entry.id === id);
            if (timer) timer.cleared = true;
          }},
          setInterval(fn, delay) {{
            const id = 'interval-' + (intervals.length + 1);
            intervals.push({{ id, fn, delay, cleared: false }});
            return id;
          }},
          clearInterval(id) {{
            clearedIntervals.push(String(id));
            const timer = intervals.find((entry) => entry.id === id);
            if (timer) timer.cleared = true;
          }},
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
          showNewTaskNotification() {{}},
          __loadRequests: loadRequests,
          __clearedIntervals: clearedIntervals,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        sandbox.api = sandbox.window.multiTaskModule;

        (async () => {{
          await vm.runInContext({case_source!r}, sandbox);
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_completed_active_task_reconciles_to_next_open_task_and_cleans_state() -> None:
    script = _multi_task_harness(
        """
        window.currentTasks = [
          { task_id: 'done', status: 'active', auto_resubmit_timeout: 0 },
          { task_id: 'next', status: 'pending', auto_resubmit_timeout: 0 },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('done');
        taskCountdowns.done = { timer: 'done-timer', remaining: 12, timeout: 30 };
        taskDeadlines.done = 1700000000;
        taskTextareaContents.done = 'stale draft';
        taskOptionsStates.done = { 'option-0': true };
        taskImages.done = [{ name: 'stale.png' }];
        autoSubmitAttempted.done = 1700000001;

        updateTasksList([
          { task_id: 'done', status: 'completed', auto_resubmit_timeout: 0 },
          { task_id: 'next', status: 'pending', auto_resubmit_timeout: 0 },
        ]);

        process.stdout.write(JSON.stringify({
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          loadRequests: window.__loadRequests,
          hasDoneCountdown: Object.prototype.hasOwnProperty.call(taskCountdowns, 'done'),
          hasDoneDeadline: Object.prototype.hasOwnProperty.call(taskDeadlines, 'done'),
          hasDoneDraft: Object.prototype.hasOwnProperty.call(taskTextareaContents, 'done'),
          hasDoneOptions: Object.prototype.hasOwnProperty.call(taskOptionsStates, 'done'),
          hasDoneImages: Object.prototype.hasOwnProperty.call(taskImages, 'done'),
          hasDoneAutoSubmit: Object.prototype.hasOwnProperty.call(autoSubmitAttempted, 'done'),
          clearedIntervals: window.__clearedIntervals,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeTaskId": "next",
        "windowActiveTaskId": "next",
        "loadRequests": ["/api/tasks/next"],
        "hasDoneCountdown": False,
        "hasDoneDeadline": False,
        "hasDoneDraft": False,
        "hasDoneOptions": False,
        "hasDoneImages": False,
        "hasDoneAutoSubmit": False,
        "clearedIntervals": ["done-timer"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_missing_active_task_reconciles_to_first_open_task() -> None:
    script = _multi_task_harness(
        """
        window.currentTasks = [
          { task_id: 'next', status: 'pending', auto_resubmit_timeout: 0 },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('missing');

        updateTasksList([
          { task_id: 'next', status: 'pending', auto_resubmit_timeout: 0 },
        ]);

        process.stdout.write(JSON.stringify({
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          loadRequests: window.__loadRequests,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeTaskId": "next",
        "windowActiveTaskId": "next",
        "loadRequests": ["/api/tasks/next"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_valid_open_active_task_is_preserved_without_detail_reload() -> None:
    script = _multi_task_harness(
        """
        window.currentTasks = [
          { task_id: 'keep', status: 'pending', auto_resubmit_timeout: 0 },
          { task_id: 'next', status: 'pending', auto_resubmit_timeout: 0 },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('keep');

        updateTasksList([
          { task_id: 'keep', status: 'pending', auto_resubmit_timeout: 0 },
          { task_id: 'next', status: 'pending', auto_resubmit_timeout: 0 },
        ]);

        process.stdout.write(JSON.stringify({
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          loadRequests: window.__loadRequests,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeTaskId": "keep",
        "windowActiveTaskId": "keep",
        "loadRequests": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_server_active_task_wins_over_local_open_task() -> None:
    script = _multi_task_harness(
        """
        window.currentTasks = [
          { task_id: 'local', status: 'pending', auto_resubmit_timeout: 0 },
          { task_id: 'server', status: 'pending', auto_resubmit_timeout: 0 },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('local');

        updateTasksList([
          { task_id: 'local', status: 'pending', auto_resubmit_timeout: 0 },
          { task_id: 'server', status: 'active', auto_resubmit_timeout: 0 },
        ]);

        process.stdout.write(JSON.stringify({
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          loadRequests: window.__loadRequests,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeTaskId": "server",
        "windowActiveTaskId": "server",
        "loadRequests": ["/api/tasks/server"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_all_completed_tasks_clear_active_task() -> None:
    script = _multi_task_harness(
        """
        window.currentTasks = [
          { task_id: 'done', status: 'pending', auto_resubmit_timeout: 0 },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('done');

        updateTasksList([
          { task_id: 'done', status: 'completed', auto_resubmit_timeout: 0 },
        ]);

        process.stdout.write(JSON.stringify({
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          loadRequests: window.__loadRequests,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeTaskId": None,
        "windowActiveTaskId": None,
        "loadRequests": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_manual_switch_keeps_window_active_task_id_in_sync() -> None:
    script = _multi_task_harness(
        """
        const textarea = document.createElement('textarea');
        textarea.value = 'draft';
        const optionsContainer = {
          querySelectorAll(selector) {
            if (selector !== 'input[type="checkbox"]') return [];
            return [{ checked: true }, { checked: false }];
          },
        };
        document.getElementById = (id) => {
          if (id === 'feedback-text') return textarea;
          if (id === 'options-container') return optionsContainer;
          return null;
        };
        window.currentTasks = [
          {
            task_id: 'old',
            status: 'pending',
            prompt: 'Old prompt',
            auto_resubmit_timeout: 0,
          },
          {
            task_id: 'next',
            status: 'pending',
            prompt: 'Next prompt',
            auto_resubmit_timeout: 0,
          },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('old');

        await api.switchTask('next');

        process.stdout.write(JSON.stringify({
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          oldDraft: taskTextareaContents.old,
          oldOptions: taskOptionsStates.old,
          oldImages: taskImages.old,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "activeTaskId": "next",
        "windowActiveTaskId": "next",
        "oldDraft": "draft",
        "oldOptions": [True, False],
        "oldImages": [],
    }
