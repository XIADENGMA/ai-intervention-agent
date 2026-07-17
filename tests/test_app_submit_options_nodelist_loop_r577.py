"""R577 regression coverage for app.js submit selected-options NodeList loop."""

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


def test_app_submit_feedback_uses_indexed_selected_options_loop() -> None:
    submit_body = _extract_function(_source(), "async function submitFeedback(")

    assert "checkboxes.forEach((checkbox)" not in submit_body
    assert "const checkboxCount =" in submit_body
    assert "for (let checkboxIndex = 0;" in submit_body
    assert "const checkbox = checkboxes[checkboxIndex]" in submit_body
    assert "if (!checkbox) continue" in submit_body
    assert "selectedOptions.push(checkbox.value)" in submit_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_app_submit_feedback_reads_selected_options_without_nodelist_foreach() -> None:
    submit_harness, run_node = _load_submit_harness()
    script = submit_harness(
        """
        const textarea = makeTextarea('Single task answer');
        const submitButton = makeSubmitButton('Submit', false);
        const checkedOptions = {
          0: { value: 'first' },
          1: { value: '' },
          2: { value: 'third' },
          length: 3,
          forEach() {
            throw new Error('NodeList.forEach must not be used for submit options');
          },
        };

        window.activeTaskId = null;
        selectedImages = [];
        currentCheckboxes = [];
        elements['feedback-text'] = textarea;
        elements['submit-btn'] = submitButton;
        elements['options-container'] = {
          querySelectorAll(selector) {
            if (selector === 'input[type="checkbox"]:checked') return checkedOptions;
            return [];
          },
        };

        fetchWithTimeout = async function fetchWithTimeout(url, options, timeoutMs) {
          fetchCalls.push({
            url,
            timeoutMs,
            entries: options.body.entries,
          });
          return {
            ok: false,
            status: 500,
            json: async () => ({ message: 'stop-after-formdata' }),
          };
        };

        await submitFeedback();

        process.stdout.write(JSON.stringify({ fetchCalls, statuses }));
        """
    )

    assert json.loads(run_node(script)) == {
        "fetchCalls": [
            {
                "url": "/api/submit",
                "timeoutMs": 30000,
                "entries": [
                    ["feedback_text", "Single task answer"],
                    ["selected_options", '["first","third"]'],
                ],
            }
        ],
        "statuses": [{"message": "stop-after-formdata", "type": "error"}],
    }
