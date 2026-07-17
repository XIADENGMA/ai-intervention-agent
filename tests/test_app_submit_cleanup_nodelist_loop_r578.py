"""R578 regression coverage for app.js submit success checkbox cleanup loop."""

from __future__ import annotations

import importlib.util
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"
APP_SUBMIT_HARNESS = REPO_ROOT / "tests" / "test_app_submit_feedback_stale_task_r452.py"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


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


def _load_submit_harness() -> tuple[Callable[[str], str], Callable[[str], str]]:
    spec = importlib.util.spec_from_file_location(
        "app_submit_feedback_stale_task_harness",
        APP_SUBMIT_HARNESS,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module_any = module  # avoid Any leaking into the public helper signature
    return module_any._submit_harness, module_any._run_node


def test_app_submit_success_cleanup_uses_indexed_checkbox_loop() -> None:
    submit_body = _extract_function(_source(), "async function submitFeedback(")

    assert ".forEach((cb) => (cb.checked = false))" not in submit_body
    assert "const allCheckboxes =" in submit_body
    assert "const allCheckboxCount =" in submit_body
    assert "checkboxIndex < allCheckboxCount" in submit_body
    assert "const checkbox = allCheckboxes[checkboxIndex]" in submit_body
    assert "checkbox.checked = false" in submit_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_app_submit_success_cleanup_unchecks_without_nodelist_foreach() -> None:
    submit_harness, run_node = _load_submit_harness()
    script = submit_harness(
        """
        const textarea = makeTextarea('Done');
        const submitButton = makeSubmitButton('Submit', false);
        const optionA = makeCheckbox('option-a', true, 'A');
        const optionB = makeCheckbox('option-b', true, 'B');
        const optionC = makeCheckbox('option-c', false, 'C');
        const allCheckboxes = {
          0: optionA,
          1: optionB,
          2: optionC,
          length: 3,
          forEach() {
            throw new Error('NodeList.forEach must not be used for submit cleanup');
          },
        };

        window.activeTaskId = 'task-a';
        selectedImages = [{ id: 'image-a', file: 'file-a' }];
        taskTextareaContents = { 'task-a': 'cached' };
        taskOptionsStates = { 'task-a': ['A', 'B'] };
        taskImages = { 'task-a': ['image-a'] };
        currentCheckboxes = [optionA, optionB, optionC];
        elements['feedback-text'] = textarea;
        elements['submit-btn'] = submitButton;
        elements['options-container'] = makeOptionsContainer(currentCheckboxes);
        document.querySelectorAll = function querySelectorAll(selector) {
          if (selector === 'input[type="checkbox"]') return allCheckboxes;
          return [];
        };

        fetchWithTimeout = async function fetchWithTimeout(url, options, timeoutMs) {
          fetchCalls.push({
            url,
            timeoutMs,
            entries: options.body.entries,
          });
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
          checked: [optionA.checked, optionB.checked, optionC.checked],
          selectedImages,
          taskTextareaContents,
          taskOptionsStates,
          taskImages,
          translations,
        }));
        """
    )

    assert json.loads(run_node(script)) == {
        "fetchCalls": [
            {
                "url": "/api/tasks/task-a/submit",
                "timeoutMs": 30000,
                "entries": [
                    ["feedback_text", "Done"],
                    ["selected_options", '["A","B"]'],
                    ["image_0", "file-a"],
                ],
            }
        ],
        "statuses": [{"message": "submitted", "type": "success"}],
        "refreshCalls": ["task-a"],
        "clearAllImagesCalls": 1,
        "text": "",
        "checked": [False, False, False],
        "selectedImages": [],
        "taskTextareaContents": {},
        "taskOptionsStates": {},
        "taskImages": {},
        "translations": ["Submit"],
    }
