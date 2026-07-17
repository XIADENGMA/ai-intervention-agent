"""R575 regression coverage for submit image FormData indexed loop."""

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

        const requests = [];
        const sandbox = {{
          Date,
          Error,
          FormData: function FormData() {{
            this.entries = [];
            this.append = (key, value) => {{
              this.entries.push([key, value]);
            }};
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
          document: {{
            hidden: false,
            readyState: 'complete',
            addEventListener() {{}},
            createElement() {{ return {{ classList: {{ add() {{}}, remove() {{}} }} }}; }},
            getElementById() {{ return null; }},
          }},
          fetchWithTimeout: async (url, options, timeout) => {{
            requests.push({{
              url: String(url),
              method: options && options.method,
              timeout,
              entries: options && options.body && options.body.entries,
            }});
            return {{
              ok: false,
              json: async () => ({{ success: false, error: 'stop-after-formdata' }}),
            }};
          }},
          setTimeout() {{ return 'timeout-id'; }},
          clearTimeout() {{}},
          setInterval() {{ return 'interval-id'; }},
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
          AIIA_I18N: {{ t: (key) => key }},
          __requests: requests,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox, {{ filename: 'multi_task.js' }});

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


def test_submit_task_feedback_uses_indexed_image_loop() -> None:
    submit_body = _extract_function(_source(), "async function submitTaskFeedback(")

    assert "selectedImages.forEach((img, index)" not in submit_body
    assert "const selectedImageCount =" in submit_body
    assert "for (let imageIndex = 0; imageIndex < selectedImageCount;" in submit_body
    assert "if (!(imageIndex in selectedImages)) continue" in submit_body
    assert "formData.append(`image_${imageIndex}`, img.file)" in submit_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_submit_task_feedback_appends_sparse_images_without_array_foreach() -> None:
    script = _multi_task_harness(
        """
        selectedImages = [];
        selectedImages[0] = { file: { name: 'first.png' } };
        selectedImages[2] = { name: 'metadata-only' };
        selectedImages[3] = { file: { name: 'third.png' } };

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {
          throw new Error('Array.prototype.forEach must not be used for submit images');
        };
        try {
          await submitTaskFeedback('task-1', 'approved', ['yes', 'fast']);
        } finally {
          Array.prototype.forEach = originalForEach;
        }

        process.stdout.write(JSON.stringify({
          requests: window.__requests.map((request) => ({
            url: request.url,
            method: request.method,
            timeout: request.timeout,
            entries: request.entries.map((entry) => [
              entry[0],
              entry[1] && entry[1].name ? entry[1].name : entry[1],
            ]),
          })),
        }));
        """
    )

    assert _run_node(script) == {
        "requests": [
            {
                "url": "/api/tasks/task-1/submit",
                "method": "POST",
                "timeout": 30000,
                "entries": [
                    ["feedback_text", "approved"],
                    ["selected_options", '["yes","fast"]'],
                    ["image_0", "first.png"],
                    ["image_3", "third.png"],
                ],
            }
        ]
    }
