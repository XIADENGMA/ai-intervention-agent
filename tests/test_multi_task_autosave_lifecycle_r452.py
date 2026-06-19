"""Runtime checks for ``multi_task.js`` realtime autosave listener lifecycle."""

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
          const listeners = {{}};
          return {{
            tagName: String(tagName || 'div').toUpperCase(),
            id: id || '',
            name: id || '',
            value: '',
            checked: false,
            type: '',
            style: {{}},
            dataset: {{}},
            children: [],
            textContent: '',
            innerHTML: '',
            classList: createClassList(),
            addCalls: [],
            removeCalls: [],
            attributes: {{}},
            addEventListener(type, handler) {{
              this.addCalls.push({{ type, handler }});
              listeners[type] = listeners[type] || [];
              listeners[type].push(handler);
            }},
            removeEventListener(type, handler) {{
              this.removeCalls.push({{ type, handler }});
              listeners[type] = (listeners[type] || []).filter((h) => h !== handler);
            }},
            dispatch(type, init) {{
              const event = Object.assign({{
                type,
                currentTarget: this,
                target: this,
              }}, init || {{}});
              for (const handler of [...(listeners[type] || [])]) {{
                handler(event);
              }}
              return event;
            }},
            listenerCount(type) {{
              return (listeners[type] || []).length;
            }},
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
            querySelectorAll(selector) {{
              if (selector === 'input[type="checkbox"]') return this.checkboxes || [];
              return [];
            }},
          }};
        }}

        function createCheckbox(id, checked) {{
          const checkbox = createElement('input', id);
          checkbox.type = 'checkbox';
          checkbox.checked = Boolean(checked);
          return checkbox;
        }}

        function createOptionsContainer(name) {{
          const container = createElement('div', name);
          container.checkboxes = [
            createCheckbox('option-0', true),
            createCheckbox('option-1', false),
          ];
          return container;
        }}

        let textarea = createElement('textarea', 'feedback-text');
        let optionsContainer = createOptionsContainer('options-container');
        let configPathInput = createElement('input', 'config-file-path');
        const documentListeners = [];
        const windowListeners = [];
        const timeouts = [];
        const intervals = [];

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
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
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
            getElementById(id) {{
              if (id === 'feedback-text') return textarea;
              if (id === 'options-container') return optionsContainer;
              if (id === 'config-file-path') return configPathInput;
              return null;
            }},
          }},
          fetchWithTimeout: async () => ({{
            ok: true,
            json: async () => ({{
              status: 'success',
              config: {{}},
              meta: {{ config_file: '/tmp/aiia-config.toml' }},
            }}),
          }}),
          fetch: async (url) => {{
            if (String(url) === '/api/tasks') {{
              return {{
                ok: true,
                json: async () => ({{
                  success: true,
                  server_time: 1700000000,
                  tasks: [{{ task_id: 'task-one', status: 'pending' }}],
                  stats: {{}},
                }}),
              }};
            }}
            return {{
              ok: true,
              json: async () => ({{ success: true }}),
            }};
          }},
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
            const timer = intervals.find((entry) => entry.id === id);
            if (timer) timer.cleared = true;
          }},
          location: {{
            href: 'http://127.0.0.1/',
            search: '',
            origin: 'http://127.0.0.1',
            pathname: '/',
          }},
          addEventListener(type, handler) {{
            windowListeners.push({{ type, handler }});
          }},
          removeEventListener() {{}},
          currentTasks: [],
          activeTaskId: 'task-one',
          taskCountdowns: {{}},
          tasksPollingTimer: null,
          taskTextareaContents: {{}},
          taskOptionsStates: {{}},
          taskImages: {{}},
          pendingNewTaskCount: 0,
          newTaskHintTimer: null,
          tasksHealthCheckTimer: null,
          hasLoadedTaskSnapshot: false,
          serverTimeOffset: 0,
          taskDeadlines: {{}},
          feedbackPrompts: {{}},
          autoSubmitAttempted: {{}},
          AIIA_DEBUG: false,
          AIIA_I18N: {{ t: (key) => key }},
          __createElement: createElement,
          __createOptionsContainer: createOptionsContainer,
          __getElements() {{
            return {{ textarea, optionsContainer, configPathInput }};
          }},
          __setElements(next) {{
            if (next.textarea) textarea = next.textarea;
            if (next.optionsContainer) optionsContainer = next.optionsContainer;
          }},
          __documentListeners: documentListeners,
          __windowListeners: windowListeners,
          __timeouts: timeouts,
          __intervals: intervals,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const api = sandbox.window.multiTaskModule;

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_repeated_init_keeps_one_realtime_autosave_listener_pair() -> None:
    script = _multi_task_harness(
        """
        await api.initMultiTaskSupport();
        await api.initMultiTaskSupport();

        const { textarea, optionsContainer } = sandbox.__getElements();
        textarea.value = 'draft from textarea';
        textarea.dispatch('input');
        optionsContainer.checkboxes[1].checked = true;
        optionsContainer.dispatch('change', { target: optionsContainer.checkboxes[1] });

        process.stdout.write(JSON.stringify({
          textareaAddCalls: textarea.addCalls.filter((entry) => entry.type === 'input').length,
          textareaListeners: textarea.listenerCount('input'),
          optionsAddCalls: optionsContainer.addCalls.filter((entry) => entry.type === 'change').length,
          optionsListeners: optionsContainer.listenerCount('change'),
          textareaDraft: sandbox.taskTextareaContents['task-one'],
          optionsState: sandbox.taskOptionsStates['task-one'],
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "textareaAddCalls": 1,
        "textareaListeners": 1,
        "optionsAddCalls": 1,
        "optionsListeners": 1,
        "textareaDraft": "draft from textarea",
        "optionsState": {"option-0": True, "option-1": True},
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_init_rebinds_realtime_autosave_after_dom_replacement() -> None:
    script = _multi_task_harness(
        """
        await api.initMultiTaskSupport();
        const oldElements = sandbox.__getElements();

        const nextTextarea = sandbox.__createElement('textarea', 'feedback-text-next');
        const nextOptions = sandbox.__createOptionsContainer('options-container-next');
        sandbox.__setElements({
          textarea: nextTextarea,
          optionsContainer: nextOptions,
        });

        await api.initMultiTaskSupport();

        oldElements.textarea.value = 'stale draft';
        oldElements.textarea.dispatch('input');
        nextTextarea.value = 'fresh draft';
        nextTextarea.dispatch('input');
        nextOptions.checkboxes[0].checked = false;
        nextOptions.dispatch('change', { target: nextOptions.checkboxes[0] });

        process.stdout.write(JSON.stringify({
          oldTextareaListeners: oldElements.textarea.listenerCount('input'),
          oldTextareaRemoveCalls: oldElements.textarea.removeCalls
            .filter((entry) => entry.type === 'input').length,
          nextTextareaListeners: nextTextarea.listenerCount('input'),
          oldOptionsListeners: oldElements.optionsContainer.listenerCount('change'),
          oldOptionsRemoveCalls: oldElements.optionsContainer.removeCalls
            .filter((entry) => entry.type === 'change').length,
          nextOptionsListeners: nextOptions.listenerCount('change'),
          textareaDraft: sandbox.taskTextareaContents['task-one'],
          optionsState: sandbox.taskOptionsStates['task-one'],
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "oldTextareaListeners": 0,
        "oldTextareaRemoveCalls": 1,
        "nextTextareaListeners": 1,
        "oldOptionsListeners": 0,
        "oldOptionsRemoveCalls": 1,
        "nextOptionsListeners": 1,
        "textareaDraft": "fresh draft",
        "optionsState": {"option-0": False, "option-1": False},
    }
