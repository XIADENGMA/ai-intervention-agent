"""Runtime checks for app.js submitFeedback stale task cleanup."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _extract_function(source: str, name: str, *, async_function: bool = False) -> str:
    marker = f"{'async ' if async_function else ''}function {name}"
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


def _submit_feedback_runtime_source() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    return "\n".join(
        [
            _extract_function(source, "isSubmitTargetStillCurrent"),
            _extract_function(source, "clearSubmittedTaskLocalState"),
            _extract_function(source, "submitFeedback", async_function=True),
        ]
    )


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


def _submit_harness(case_js: str) -> str:
    runtime_source = _submit_feedback_runtime_source()
    return textwrap.dedent(
        f"""
        const debugMessages = [];
        const statuses = [];
        const refreshCalls = [];
        const fetchCalls = [];
        const translations = [];
        let clearAllImagesCalls = 0;
        let selectedImages = [];
        let taskTextareaContents = {{}};
        let taskOptionsStates = {{}};
        let taskImages = {{}};
        let SUBMIT_BTN_ORIGINAL_HTML = null;

        function makeTextarea(value) {{
          return {{ value }};
        }}

        function makeSubmitButton(innerHTML, disabled) {{
          return {{ innerHTML, disabled: Boolean(disabled) }};
        }}

        function makeCheckbox(id, checked, value) {{
          return {{
            id,
            type: 'checkbox',
            checked: Boolean(checked),
            value,
          }};
        }}

        function makeOptionsContainer(checkboxes) {{
          return {{
            querySelectorAll(selector) {{
              if (selector === 'input[type="checkbox"]:checked') {{
                return checkboxes.filter((checkbox) => checkbox.checked);
              }}
              if (selector === 'input[type="checkbox"]') {{
                return checkboxes;
              }}
              return [];
            }},
          }};
        }}

        let currentCheckboxes = [];
        const elements = {{}};
        const window = {{
          activeTaskId: null,
          AIIA_I18N: {{
            translateDOM(element) {{
              translations.push(element.innerHTML);
            }},
          }},
        }};
        const document = {{
          getElementById(id) {{
            return Object.prototype.hasOwnProperty.call(elements, id)
              ? elements[id]
              : null;
          }},
          querySelectorAll(selector) {{
            if (selector === 'input[type="checkbox"]') return currentCheckboxes;
            return [];
          }},
        }};
        const console = {{
          debug(...args) {{ debugMessages.push(args.join(' ')); }},
          error() {{}},
          warn() {{}},
        }};
        class FormData {{
          constructor() {{
            this.entries = [];
          }}
          append(name, value) {{
            this.entries.push([name, value]);
          }}
        }}
        const config = {{ has_content: true }};
        function captureSubmitBtnOriginalHTML() {{
          if (SUBMIT_BTN_ORIGINAL_HTML !== null) return;
          const btn = document.getElementById('submit-btn');
          if (btn) SUBMIT_BTN_ORIGINAL_HTML = btn.innerHTML;
        }}
        function showStatus(message, type) {{
          statuses.push({{ message, type }});
        }}
        function t(key) {{
          return key;
        }}
        function clearAllImages() {{
          clearAllImagesCalls += 1;
          selectedImages = [];
        }}
        async function refreshTasksList() {{
          refreshCalls.push(window.activeTaskId);
        }}
        function showNoContentPage() {{
          throw new Error('showNoContentPage should not be called in these tests');
        }}
        let fetchWithTimeout = async function fetchWithTimeout() {{
          throw new Error('fetchWithTimeout stub must be assigned by the test case');
        }};
        function _classifyFetchError(error) {{
          return error && error.name === 'AbortError'
            ? 'status.requestTimeout'
            : 'status.networkError';
        }}
        function _classifyHttpResponse() {{
          return null;
        }}

        {runtime_source}

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


def test_submit_feedback_source_uses_current_task_guard_for_visible_cleanup() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert "function isSubmitTargetStillCurrent(taskId)" in source
    assert "function clearSubmittedTaskLocalState(taskId)" in source
    assert "let submitTargetTaskId = null" in source
    assert "isSubmitTargetStillCurrent(submitTargetTaskId)" in source
    assert "clearSubmittedTaskLocalState(submitTargetTaskId)" in source


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_submit_success_after_task_switch_preserves_current_form_state() -> None:
    script = _submit_harness(
        """
        const taskATextarea = makeTextarea('Task A answer');
        const taskASubmit = makeSubmitButton('Task A submit', false);
        const taskACheckbox = makeCheckbox('task-a-option', true, 'A option');
        const taskBTextarea = makeTextarea('Task B draft');
        const taskBSubmit = makeSubmitButton('Task B submit', true);
        const taskBCheckbox = makeCheckbox('task-b-option', true, 'B option');

        window.activeTaskId = 'task-a';
        selectedImages = [{ id: 'image-a', file: 'file-a' }];
        taskTextareaContents = { 'task-a': 'Task A cached', 'task-b': 'Task B cached' };
        taskOptionsStates = { 'task-a': ['a'], 'task-b': ['b'] };
        taskImages = { 'task-a': ['image-a'], 'task-b': ['image-b'] };
        currentCheckboxes = [taskACheckbox];
        elements['feedback-text'] = taskATextarea;
        elements['submit-btn'] = taskASubmit;
        elements['options-container'] = makeOptionsContainer(currentCheckboxes);

        fetchWithTimeout = async function fetchWithTimeout(url, options, timeoutMs) {
          fetchCalls.push({
            url,
            timeoutMs,
            entries: options.body.entries,
          });
          window.activeTaskId = 'task-b';
          selectedImages = [{ id: 'image-b', file: 'file-b' }];
          currentCheckboxes = [taskBCheckbox];
          elements['feedback-text'] = taskBTextarea;
          elements['submit-btn'] = taskBSubmit;
          elements['options-container'] = makeOptionsContainer(currentCheckboxes);
          return {
            ok: true,
            json: async () => ({ message: 'submitted' }),
          };
        };

        await submitFeedback();

        process.stdout.write(JSON.stringify({
          fetchCalls,
          statuses,
          refreshCalls,
          debugMessages,
          clearAllImagesCalls,
          currentTaskId: window.activeTaskId,
          taskBText: taskBTextarea.value,
          taskBChecked: taskBCheckbox.checked,
          taskBSubmit,
          selectedImages,
          taskTextareaContents,
          taskOptionsStates,
          taskImages,
          translations,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "fetchCalls": [
            {
                "url": "/api/tasks/task-a/submit",
                "timeoutMs": 30000,
                "entries": [
                    ["feedback_text", "Task A answer"],
                    ["selected_options", '["A option"]'],
                    ["image_0", "file-a"],
                ],
            }
        ],
        "statuses": [{"message": "submitted", "type": "success"}],
        "refreshCalls": ["task-b"],
        "debugMessages": [
            "Using submit endpoint: /api/tasks/task-a/submit",
            "submitFeedback: submitted task changed before success cleanup; preserving current form state",
            "Invoking refreshTasksList to refresh task list...",
        ],
        "clearAllImagesCalls": 0,
        "currentTaskId": "task-b",
        "taskBText": "Task B draft",
        "taskBChecked": True,
        "taskBSubmit": {"innerHTML": "Task B submit", "disabled": True},
        "selectedImages": [{"id": "image-b", "file": "file-b"}],
        "taskTextareaContents": {"task-b": "Task B cached"},
        "taskOptionsStates": {"task-b": ["b"]},
        "taskImages": {"task-b": ["image-b"]},
        "translations": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_submit_success_for_current_task_clears_visible_form_state() -> None:
    script = _submit_harness(
        """
        const textarea = makeTextarea('Task A answer');
        const submitButton = makeSubmitButton('Task A submit', false);
        const checkbox = makeCheckbox('task-a-option', true, 'A option');

        window.activeTaskId = 'task-a';
        selectedImages = [{ id: 'image-a', file: 'file-a' }];
        taskTextareaContents = { 'task-a': 'Task A cached' };
        taskOptionsStates = { 'task-a': ['a'] };
        taskImages = { 'task-a': ['image-a'] };
        currentCheckboxes = [checkbox];
        elements['feedback-text'] = textarea;
        elements['submit-btn'] = submitButton;
        elements['options-container'] = makeOptionsContainer(currentCheckboxes);

        fetchWithTimeout = async function fetchWithTimeout(url, options, timeoutMs) {
          fetchCalls.push({ url, timeoutMs, entries: options.body.entries });
          return {
            ok: true,
            json: async () => ({ message: 'submitted' }),
          };
        };

        await submitFeedback();

        process.stdout.write(JSON.stringify({
          fetchCalls,
          statuses,
          refreshCalls,
          clearAllImagesCalls,
          text: textarea.value,
          checked: checkbox.checked,
          submitButton,
          selectedImages,
          taskTextareaContents,
          taskOptionsStates,
          taskImages,
          translations,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "fetchCalls": [
            {
                "url": "/api/tasks/task-a/submit",
                "timeoutMs": 30000,
                "entries": [
                    ["feedback_text", "Task A answer"],
                    ["selected_options", '["A option"]'],
                    ["image_0", "file-a"],
                ],
            }
        ],
        "statuses": [{"message": "submitted", "type": "success"}],
        "refreshCalls": ["task-a"],
        "clearAllImagesCalls": 1,
        "text": "",
        "checked": False,
        "submitButton": {"innerHTML": "Task A submit", "disabled": False},
        "selectedImages": [],
        "taskTextareaContents": {},
        "taskOptionsStates": {},
        "taskImages": {},
        "translations": ["Task A submit"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_no_task_submit_preserves_new_task_that_appears_before_success() -> None:
    script = _submit_harness(
        """
        const legacyTextarea = makeTextarea('Legacy answer');
        const legacySubmit = makeSubmitButton('Legacy submit', false);
        const newTaskTextarea = makeTextarea('New task draft');
        const newTaskSubmit = makeSubmitButton('New task submit', true);

        window.activeTaskId = null;
        selectedImages = [];
        currentCheckboxes = [];
        elements['feedback-text'] = legacyTextarea;
        elements['submit-btn'] = legacySubmit;
        elements['options-container'] = makeOptionsContainer(currentCheckboxes);

        fetchWithTimeout = async function fetchWithTimeout(url, options, timeoutMs) {
          fetchCalls.push({ url, timeoutMs, entries: options.body.entries });
          window.activeTaskId = 'new-task';
          elements['feedback-text'] = newTaskTextarea;
          elements['submit-btn'] = newTaskSubmit;
          return {
            ok: true,
            json: async () => ({ message: 'submitted' }),
          };
        };

        await submitFeedback();

        process.stdout.write(JSON.stringify({
          fetchCalls,
          clearAllImagesCalls,
          currentTaskId: window.activeTaskId,
          newTaskText: newTaskTextarea.value,
          newTaskSubmit,
          debugMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "fetchCalls": [
            {
                "url": "/api/submit",
                "timeoutMs": 30000,
                "entries": [
                    ["feedback_text", "Legacy answer"],
                    ["selected_options", "[]"],
                ],
            }
        ],
        "clearAllImagesCalls": 0,
        "currentTaskId": "new-task",
        "newTaskText": "New task draft",
        "newTaskSubmit": {"innerHTML": "New task submit", "disabled": True},
        "debugMessages": [
            "Using submit endpoint: /api/submit",
            "submitFeedback: submitted task changed before success cleanup; preserving current form state",
            "Invoking refreshTasksList to refresh task list...",
        ],
    }
