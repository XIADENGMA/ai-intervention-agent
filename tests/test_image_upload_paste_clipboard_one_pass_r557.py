"""R557 regression coverage for allocation-light WebUI paste image collection."""

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
          + '\\nglobalThis.__initializePasteFunction = initializePasteFunction;'
          + '\\nglobalThis.__setAddImageToList = function (fn) {{ addImageToList = fn; }};'
          + '\\nglobalThis.__setUpdateImagePreviewVisibility = function (fn) {{ updateImagePreviewVisibility = fn; }};';

        const documentListeners = [];
        const removedListeners = [];
        const statusCalls = [];
        const textarea = {{
          id: 'feedback-text',
          classList: {{ add() {{}}, remove() {{}} }},
        }};

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
            activeElement: textarea,
            hidden: false,
            readyState: 'loading',
            addEventListener(type, handler) {{
              documentListeners.push({{ type, handler }});
            }},
            removeEventListener(type, handler) {{
              removedListeners.push({{ type, handler }});
            }},
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
            getElementById(id) {{
              return id === 'feedback-text' ? textarea : null;
            }},
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
          setTimeout(fn) {{ return {{ fn }}; }},
          clearTimeout() {{}},
          showStatus(message, kind) {{
            statusCalls.push({{ message, kind }});
          }},
          t(key, params) {{
            return `${{key}}:${{params && params.count || ''}}`;
          }},
          addEventListener() {{}},
          window: null,
          __documentListeners: documentListeners,
          __removedListeners: removedListeners,
          __statusCalls: statusCalls,
          __textarea: textarea,
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


def test_paste_handler_avoids_clipboard_array_from_materialization() -> None:
    source = _source()
    helper_body = _extract_function(source, "function forEachClipboardEntry(")
    paste_body = _extract_function(source, "function initializePasteFunction(")

    assert "Array.from(clipboardData.items" not in paste_body
    assert "Array.from(clipboardData.files" not in paste_body
    assert "forEachClipboardEntry(clipboardData.items" in paste_body
    assert "forEachClipboardEntry(clipboardData.files" in paste_body
    assert "Array.from(" not in helper_body
    assert "collection[Symbol.iterator]" in helper_body
    assert "for (const entry of collection)" in helper_body
    assert "for (let i = 0; i < length; i += 1)" in helper_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_paste_items_path_preserves_priority_without_reading_files_fallback() -> None:
    script = _image_upload_harness(
        """
        const added = [];
        let previewUpdates = 0;
        sandbox.__setAddImageToList(async (file) => {
          added.push(file.name);
          return true;
        });
        sandbox.__setUpdateImagePreviewVisibility(() => {
          previewUpdates += 1;
        });
        sandbox.__initializePasteFunction();
        const pasteHandler = sandbox.__documentListeners.find(
          (entry) => entry.type === 'paste',
        ).handler;

        let filesAccessed = false;
        const primary = { name: 'item.png', type: 'image/png' };
        const secondary = { name: 'item.webp', type: 'image/webp' };
        const event = {
          clipboardData: {
            items: {
              length: 4,
              0: { kind: 'string', type: 'text/plain' },
              1: { kind: 'file', type: 'text/plain', getAsFile() { return { name: 'note.txt', type: 'text/plain' }; } },
              2: { kind: 'file', type: 'image/png', getAsFile() { return primary; } },
              3: { kind: 'file', type: 'image/webp', getAsFile() { return secondary; } },
            },
            get files() {
              filesAccessed = true;
              return [{ name: 'fallback.png', type: 'image/png' }];
            },
            getData(type) {
              return type === 'text/plain' ? '' : '';
            },
          },
          defaultPrevented: false,
          preventDefault() {
            this.defaultPrevented = true;
          },
        };

        await pasteHandler(event);
        process.stdout.write(JSON.stringify({
          added,
          defaultPrevented: event.defaultPrevented,
          filesAccessed,
          previewUpdates,
          statusCalls: sandbox.__statusCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "added": ["item.png", "item.webp"],
        "defaultPrevented": True,
        "filesAccessed": False,
        "previewUpdates": 1,
        "statusCalls": [{"message": "status.clipboardAdded:2", "kind": "success"}],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_paste_files_fallback_and_iterable_items_preserve_text_paste() -> None:
    script = _image_upload_harness(
        """
        const added = [];
        let previewUpdates = 0;
        sandbox.__setAddImageToList(async (file) => {
          added.push(file.name);
          return true;
        });
        sandbox.__setUpdateImagePreviewVisibility(() => {
          previewUpdates += 1;
        });
        sandbox.__initializePasteFunction();
        const pasteHandler = sandbox.__documentListeners.find(
          (entry) => entry.type === 'paste',
        ).handler;

        const event = {
          clipboardData: {
            items: {
              [Symbol.iterator]: function* () {
                yield { kind: 'string', type: 'text/html' };
                yield { kind: 'file', type: 'image/png', getAsFile() { return null; } };
              },
            },
            files: {
              length: 4,
              0: undefined,
              1: { name: 'note.txt', type: 'text/plain' },
              2: { name: 'fallback.jpg', type: 'image/jpeg' },
              3: { name: 'fallback.gif', type: 'image/gif' },
            },
            getData(type) {
              return type === 'text/plain' ? 'keep text paste' : '';
            },
          },
          defaultPrevented: false,
          preventDefault() {
            this.defaultPrevented = true;
          },
        };

        await pasteHandler(event);
        process.stdout.write(JSON.stringify({
          added,
          defaultPrevented: event.defaultPrevented,
          previewUpdates,
          statusCalls: sandbox.__statusCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "added": ["fallback.jpg", "fallback.gif"],
        "defaultPrevented": False,
        "previewUpdates": 1,
        "statusCalls": [{"message": "status.clipboardAdded:2", "kind": "success"}],
    }
