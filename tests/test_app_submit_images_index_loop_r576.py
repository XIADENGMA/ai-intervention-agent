"""R576 regression coverage for app.js submit image FormData indexed loop."""

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


def test_app_submit_feedback_uses_indexed_image_loop() -> None:
    submit_body = _extract_function(_source(), "async function submitFeedback(")

    assert "selectedImages.forEach((img, index)" not in submit_body
    assert "const selectedImageCount =" in submit_body
    assert "for (let imageIndex = 0; imageIndex < selectedImageCount;" in submit_body
    assert "if (!(imageIndex in selectedImages)) continue" in submit_body
    assert "formData.append(`image_${imageIndex}`, img.file)" in submit_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_app_submit_feedback_appends_sparse_images_without_array_foreach() -> None:
    submit_harness, run_node = _load_submit_harness()
    script = submit_harness(
        """
        const textarea = makeTextarea('Single task answer');
        const submitButton = makeSubmitButton('Submit', false);

        window.activeTaskId = null;
        selectedImages = [];
        selectedImages[0] = { id: 'first', file: 'file-0' };
        selectedImages[2] = { id: 'metadata-only' };
        selectedImages[3] = { id: 'third', file: 'file-3' };
        currentCheckboxes = [];
        elements['feedback-text'] = textarea;
        elements['submit-btn'] = submitButton;

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

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {
          throw new Error('Array.prototype.forEach must not be used for app submit images');
        };
        try {
          await submitFeedback();
        } finally {
          Array.prototype.forEach = originalForEach;
        }

        process.stdout.write(JSON.stringify({ fetchCalls }));
        """
    )

    assert json.loads(run_node(script)) == {
        "fetchCalls": [
            {
                "url": "/api/submit",
                "timeoutMs": 30000,
                "entries": [
                    ["feedback_text", "Single task answer"],
                    ["selected_options", "[]"],
                    ["image_0", "file-0"],
                    ["image_3", "file-3"],
                ],
            }
        ]
    }
