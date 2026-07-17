"""R561 regression coverage for one-pass WebUI file upload batching."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_UPLOAD_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "image-upload.js"
)


def _source() -> str:
    return IMAGE_UPLOAD_JS.read_text(encoding="utf-8")


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


def _run_node(script: str) -> str:
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
    return proc.stdout


def _image_upload_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(IMAGE_UPLOAD_JS)!r}, 'utf8')
          + '\\nglobalThis.__handleFileUpload = handleFileUpload;'
          + '\\nglobalThis.__setAddImageToList = function (fn) {{ addImageToList = fn; }};'
          + '\\nglobalThis.__setUpdateImagePreviewVisibility = function (fn) {{ updateImagePreviewVisibility = fn; }};';

        const statusCalls = [];
        const timers = [];

        const sandbox = {{
          Array,
          Blob: function Blob() {{}},
          Date,
          Error,
          File: function File(parts, name, options) {{
            this.parts = parts;
            this.name = name;
            this.type = options && options.type || '';
            this.lastModified = options && options.lastModified || 0;
          }},
          FileList: function FileList() {{}},
          FileReader: function FileReader() {{}},
          JSON,
          Map,
          Math,
          Number,
          Object,
          Promise,
          RegExp,
          Set,
          String,
          Symbol,
          Uint8Array,
          URL: {{
            createObjectURL() {{ return 'blob:test'; }},
            revokeObjectURL() {{}},
          }},
          atob(value) {{ return Buffer.from(value, 'base64').toString('binary'); }},
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            activeElement: null,
            hidden: false,
            readyState: 'loading',
            addEventListener() {{}},
            removeEventListener() {{}},
            contains() {{ return false; }},
            createDocumentFragment() {{
              return {{ appendChild() {{}} }};
            }},
            createElement() {{
              return {{
                classList: {{ add() {{}}, remove() {{}} }},
                dataset: {{}},
                style: {{}},
                addEventListener() {{}},
                appendChild() {{}},
                querySelector() {{ return null; }},
                remove() {{}},
                removeAttribute() {{}},
                setAttribute() {{}},
              }};
            }},
            getElementById() {{ return null; }},
            querySelector() {{ return null; }},
          }},
          DOMSecurity: {{
            clearContent() {{}},
            createImagePreview() {{ return {{ firstChild: null }}; }},
            replaceContent() {{}},
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          navigator: {{ clipboard: {{ read() {{}} }} }},
          performance: {{ now: () => 0 }},
          requestAnimationFrame(fn) {{ return fn(); }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn, delay) {{
            const timer = {{ fn, delay, cleared: false }};
            timers.push(timer);
            return timer;
          }},
          clearTimeout(timer) {{
            if (timer) timer.cleared = true;
          }},
          showStatus(message, kind) {{
            statusCalls.push({{ message, kind }});
          }},
          t(key, params) {{
            return JSON.stringify({{ key, params: params || null }});
          }},
          addEventListener() {{}},
          window: null,
          __statusCalls: statusCalls,
          __timers: timers,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.Buffer = Buffer;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


def test_handle_file_upload_batches_filelist_without_array_materialization() -> None:
    body = _extract_function(_source(), "async function handleFileUpload(")

    assert "Array.from(files)" not in body
    assert "const fileArray" not in body
    assert ".slice(i, i + maxConcurrent)" not in body
    assert ".map(async (file)" not in body
    assert "const fileCount = files.length" in body
    assert "const batchEnd = Math.min(i + maxConcurrent, fileCount)" in body
    assert "for (let j = i; j < batchEnd; j += 1)" in body
    assert "const file = files[j]" in body
    assert "await Promise.all(batchPromises)" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_handle_file_upload_preserves_three_at_a_time_filelist_batches() -> None:
    script = """
        const files = {
          length: 5,
          0: { name: 'a.png' },
          1: { name: 'b.png' },
          2: { name: 'c.png' },
          3: { name: 'd.png' },
          4: { name: 'e.png' },
        };
        const started = [];
        let previewUpdates = 0;

        sandbox.__setAddImageToList(async (file) => {
          started.push(file.name);
          return file.name !== 'd.png';
        });
        sandbox.__setUpdateImagePreviewVisibility(() => {
          previewUpdates += 1;
        });

        const uploadPromise = sandbox.__handleFileUpload(files);
        for (let i = 0; i < 10 && sandbox.__timers.length === 0; i += 1) {
          await Promise.resolve();
        }
        const firstBatchStarted = started.slice();
        const delayTimer = sandbox.__timers.find(timer => timer.delay === 50);
        delayTimer.fn();
        for (let i = 0; i < 5; i += 1) {
          await Promise.resolve();
        }
        await uploadPromise;

        process.stdout.write(JSON.stringify({
          firstBatchStarted,
          started,
          previewUpdates,
          timerDelays: sandbox.__timers.map(timer => timer.delay),
          statusCalls: sandbox.__statusCalls,
        }));
    """

    assert json.loads(_run_node(_image_upload_harness(script))) == {
        "firstBatchStarted": ["a.png", "b.png", "c.png"],
        "started": ["a.png", "b.png", "c.png", "d.png", "e.png"],
        "previewUpdates": 1,
        "timerDelays": [50],
        "statusCalls": [
            {
                "message": '{"key":"status.processingBatch","params":{"count":5}}',
                "kind": "info",
            },
            {
                "message": (
                    '{"key":"status.processProgress","params":{"done":1,"total":5}}'
                ),
                "kind": "info",
            },
            {
                "message": (
                    '{"key":"status.processProgress","params":{"done":2,"total":5}}'
                ),
                "kind": "info",
            },
            {
                "message": (
                    '{"key":"status.processProgress","params":{"done":3,"total":5}}'
                ),
                "kind": "info",
            },
            {
                "message": (
                    '{"key":"status.processProgress","params":{"done":4,"total":5}}'
                ),
                "kind": "info",
            },
            {
                "message": (
                    '{"key":"status.processProgress","params":{"done":5,"total":5}}'
                ),
                "kind": "info",
            },
            {
                "message": (
                    '{"key":"status.batchComplete","params":{"successful":4,"total":5}}'
                ),
                "kind": "success",
            },
        ],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_handle_file_upload_single_file_status_uses_direct_index() -> None:
    script = """
        const files = {
          length: 1,
          0: { name: 'only.png' },
        };
        sandbox.__setAddImageToList(async (file) => file.name === 'only.png');
        sandbox.__setUpdateImagePreviewVisibility(() => {});

        await sandbox.__handleFileUpload(files);

        process.stdout.write(JSON.stringify({
          timerDelays: sandbox.__timers.map(timer => timer.delay),
          statusCalls: sandbox.__statusCalls,
        }));
    """

    assert json.loads(_run_node(_image_upload_harness(script))) == {
        "timerDelays": [],
        "statusCalls": [
            {
                "message": (
                    '{"key":"status.fileProcessSuccess",'
                    '"params":{"filename":"only.png"}}'
                ),
                "kind": "success",
            }
        ],
    }
