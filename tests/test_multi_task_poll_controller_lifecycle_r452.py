"""Runtime checks for ``multi_task.js`` task-poll AbortController ownership."""

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


def _poll_harness(case_js: str) -> str:
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

        function createAbortError() {{
          const error = new Error('aborted');
          error.name = 'AbortError';
          error.code = 20;
          return error;
        }}

        let nextControllerId = 0;
        class FakeAbortController {{
          constructor() {{
            this.id = ++nextControllerId;
            this.abortCount = 0;
            const listeners = [];
            this.signal = {{
              aborted: false,
              __controller: this,
              addEventListener(type, handler) {{
                if (type === 'abort') listeners.push(handler);
              }},
              removeEventListener(type, handler) {{
                if (type !== 'abort') return;
                const index = listeners.indexOf(handler);
                if (index >= 0) listeners.splice(index, 1);
              }},
              __dispatchAbort: () => {{
                for (const handler of [...listeners]) {{
                  handler({{ type: 'abort' }});
                }}
              }},
            }};
          }}

          abort() {{
            this.abortCount += 1;
            if (this.signal.aborted) return;
            this.signal.aborted = true;
            this.signal.__dispatchAbort();
          }}
        }}

        const fetchRequests = [];
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
          Array,
          AbortController: FakeAbortController,
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
            addEventListener() {{}},
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
          fetch(url, options) {{
            const request = {{
              url: String(url),
              signal: options && options.signal,
              resolve: null,
              reject: null,
              abortedBySignal: false,
            }};
            const promise = new Promise((resolve, reject) => {{
              request.resolve = resolve;
              request.reject = reject;
              if (request.signal) {{
                if (request.signal.aborted) {{
                  request.abortedBySignal = true;
                  reject(createAbortError());
                }} else if (typeof request.signal.addEventListener === 'function') {{
                  request.signal.addEventListener('abort', () => {{
                    request.abortedBySignal = true;
                    reject(createAbortError());
                  }});
                }}
              }}
            }});
            fetchRequests.push(request);
            return promise;
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
          __fetchRequests: fetchRequests,
          __timeouts: timeouts,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        (async () => {{
          await vm.runInContext({case_source!r}, sandbox);
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_stale_timeout_does_not_abort_newer_task_poll() -> None:
    script = _poll_harness(
        """
        const firstPromise = fetchAndApplyTasks('first');
        const firstController = __fetchRequests[0].signal.__controller;
        const firstTimeout = __timeouts[0];

        const secondPromise = fetchAndApplyTasks('second');
        const secondController = __fetchRequests[1].signal.__controller;

        firstTimeout.fn();

        process.stdout.write(JSON.stringify({
          firstAbortCount: firstController.abortCount,
          secondAbortCount: secondController.abortCount,
          secondAborted: secondController.signal.aborted,
          globalStillSecond: tasksPollAbortController === secondController,
        }));

        await firstPromise;
        await Promise.resolve();
        void secondPromise;
        """
    )

    assert json.loads(_run_node(script)) == {
        "firstAbortCount": 2,
        "secondAbortCount": 0,
        "secondAborted": False,
        "globalStillSecond": True,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_stale_finally_does_not_orphan_newer_task_poll_timeout() -> None:
    script = _poll_harness(
        """
        const firstPromise = fetchAndApplyTasks('first');
        const secondPromise = fetchAndApplyTasks('second');
        const secondController = __fetchRequests[1].signal.__controller;
        const secondTimeout = __timeouts[1];

        await firstPromise;
        await Promise.resolve();
        const globalAfterFirstFinally = tasksPollAbortController === secondController;

        secondTimeout.fn();

        process.stdout.write(JSON.stringify({
          globalAfterFirstFinally,
          secondAbortCount: secondController.abortCount,
          secondAborted: secondController.signal.aborted,
        }));

        await secondPromise;
        """
    )

    assert json.loads(_run_node(script)) == {
        "globalAfterFirstFinally": True,
        "secondAbortCount": 1,
        "secondAborted": True,
    }
