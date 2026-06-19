"""Runtime checks for the multi-task new-task hint DOM construction."""

from __future__ import annotations

import json
import re
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

        const innerHTMLAssignments = [];
        const appendedToBody = [];
        const timeouts = [];

        function createClassList() {{
          return {{
            add() {{}},
            remove() {{}},
            toggle() {{}},
            contains() {{ return false; }},
          }};
        }}

        function createElement(tagName, id) {{
          const element = {{
            tagName: String(tagName || 'div').toUpperCase(),
            id: id || '',
            value: '',
            checked: false,
            style: {{}},
            dataset: {{}},
            children: [],
            textContent: '',
            classList: createClassList(),
            attributes: {{}},
            addEventListener() {{}},
            removeEventListener() {{}},
            appendChild(child) {{
              child.parentNode = this;
              this.children.push(child);
              return child;
            }},
            removeChild(child) {{
              this.children = this.children.filter((entry) => entry !== child);
              child.parentNode = null;
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
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(this.attributes, name)
                ? this.attributes[name]
                : null;
            }},
            querySelector() {{
              return null;
            }},
            querySelectorAll() {{
              return [];
            }},
          }};
          let html = '';
          Object.defineProperty(element, 'innerHTML', {{
            get() {{
              return html;
            }},
            set(value) {{
              html = String(value);
              innerHTMLAssignments.push({{
                tagName: element.tagName,
                id: element.id,
                value: html,
              }});
              if (html.includes('<img')) {{
                element.children.push(createElement('img', 'parsed-img'));
              }}
              if (html.includes('<svg')) {{
                element.children.push(createElement('svg', 'parsed-svg'));
              }}
            }},
          }});
          return element;
        }}

        const taskTabsContainer = createElement('div', 'task-tabs-container');
        const body = createElement('body', 'body');
        body.appendChild = function appendChild(child) {{
          child.parentNode = this;
          this.children.push(child);
          appendedToBody.push(child);
          return child;
        }};

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
            body,
            documentElement: {{
              getAttribute(name) {{
                return name === 'data-theme' ? 'light' : null;
              }},
            }},
            addEventListener() {{}},
            createDocumentFragment() {{
              return createElement('fragment', 'fragment');
            }},
            createElement(tagName) {{
              return createElement(tagName, '');
            }},
            getElementById(id) {{
              if (id === 'task-tabs-container') return taskTabsContainer;
              if (id === 'new-task-hint') {{
                return body.children.find((entry) => entry.id === id) || null;
              }}
              return null;
            }},
          }},
          fetchWithTimeout: () => new Promise(() => {{}}),
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
          setInterval() {{
            return 'interval';
          }},
          clearInterval() {{}},
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
          AIIA_I18N: {{
            t(key, params) {{
              if (key === 'page.noContent.newTasks') {{
                return '<img src=x onerror=alert(1)> ' + params.count + ' new';
              }}
              return key;
            }},
          }},
          __innerHTMLAssignments: innerHTMLAssignments,
          __appendedToBody: appendedToBody,
          __body: body,
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
def test_new_task_hint_translation_is_text_not_html() -> None:
    script = _multi_task_harness(
        """
        showNewTaskVisualHint(3);
        const hint = window.__appendedToBody.find((entry) => entry.id === 'new-task-hint');
        const label = hint.children[1];
        const parsedImages = hint.children.filter((entry) => entry.tagName === 'IMG');
        const assignmentValues = window.__innerHTMLAssignments.map((entry) => entry.value);
        process.stdout.write(JSON.stringify({
          hintId: hint.id,
          childTags: hint.children.map((entry) => entry.tagName),
          role: hint.attributes.role,
          ariaAtomic: hint.attributes['aria-atomic'],
          hasExplicitAriaLive: Object.prototype.hasOwnProperty.call(hint.attributes, 'aria-live'),
          labelText: label.textContent,
          parsedImageCount: parsedImages.length,
          maliciousInnerHTMLWrites: assignmentValues.filter((value) => value.includes('<img')).length,
          svgInnerHTMLWrites: assignmentValues.filter((value) => value.includes('<svg')).length,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "hintId": "new-task-hint",
        "childTags": ["SPAN", "SPAN"],
        "role": "status",
        "ariaAtomic": "true",
        "hasExplicitAriaLive": False,
        "labelText": "<img src=x onerror=alert(1)> 3 new",
        "parsedImageCount": 0,
        "maliciousInnerHTMLWrites": 0,
        "svgInnerHTMLWrites": 1,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_new_task_hint_replaces_existing_hint_and_clears_old_timer() -> None:
    script = _multi_task_harness(
        """
        showNewTaskVisualHint(1);
        const firstHint = window.__body.children.find((entry) => entry.id === 'new-task-hint');

        showNewTaskVisualHint(2);
        const liveHints = window.__body.children.filter((entry) => entry.id === 'new-task-hint');
        const secondHint = liveHints[0];
        const secondLabel = secondHint.children[1];

        process.stdout.write(JSON.stringify({
          bodyHintCount: liveHints.length,
          firstDetached: firstHint.parentNode === null,
          firstTimerCleared: window.__timeouts[0].cleared,
          secondTimerCleared: window.__timeouts[1].cleared,
          secondLabelText: secondLabel.textContent,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "bodyHintCount": 1,
        "firstDetached": True,
        "firstTimerCleared": True,
        "secondTimerCleared": False,
        "secondLabelText": "<img src=x onerror=alert(1)> 2 new",
    }


def test_new_task_hint_source_does_not_pipe_i18n_through_innerhtml() -> None:
    source = MULTI_TASK_JS.read_text(encoding="utf-8")

    assert "label.textContent" in source
    assert 'hint.setAttribute("role", "status")' in source
    assert 'hint.setAttribute("aria-atomic", "true")' in source
    assert not re.search(
        r"\.innerHTML\s*=\s*[^;]*page\.noContent\.newTasks",
        source,
    )
