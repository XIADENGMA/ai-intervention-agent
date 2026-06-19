"""Runtime checks for image upload file-selection initialization."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_UPLOAD_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "image-upload.js"
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


def _image_upload_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(IMAGE_UPLOAD_JS)!r}, 'utf8')
          + '\\nglobalThis.__initializeFileSelection = initializeFileSelection;'
          + '\\nglobalThis.__setHandleFileUpload = function (fn) {{ handleFileUpload = fn; }};';

        const documentListeners = [];
        const elementListeners = [];
        const windowListeners = [];
        const elements = new Map();
        const debugMessages = [];

        function makeElement(id) {{
          return {{
            id,
            classList: {{ add() {{}}, remove() {{}} }},
            clickCalls: 0,
            dataset: {{}},
            files: [],
            style: {{}},
            value: '',
            addEventListener(type, handler) {{
              elementListeners.push({{ id, type, handler }});
            }},
            click() {{
              this.clickCalls += 1;
            }},
            getContext() {{ return {{}}; }},
            querySelector() {{ return null; }},
            removeAttribute() {{}},
            setAttribute() {{}},
          }};
        }}

        const sandbox = {{
          Array,
          Blob: function Blob() {{}},
          Date,
          Error,
          File: function File() {{}},
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
          WeakMap,
          URL: {{
            createObjectURL() {{ return 'blob:test'; }},
            revokeObjectURL() {{}},
          }},
          console: {{
            debug(...args) {{ debugMessages.push(args.join(' ')); }},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            activeElement: null,
            hidden: false,
            readyState: 'loading',
            addEventListener(type, handler) {{
              documentListeners.push({{ type, handler }});
            }},
            contains() {{ return false; }},
            createDocumentFragment() {{
              return {{ appendChild() {{}} }};
            }},
            createElement() {{
              return makeElement('created');
            }},
            getElementById(id) {{
              return elements.get(id) || null;
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
          showStatus() {{}},
          t(key) {{ return key; }},
          addEventListener(type, handler) {{
            windowListeners.push({{ type, handler }});
          }},
          window: null,
          __debugMessages: debugMessages,
          __documentListeners: documentListeners,
          __elementListeners: elementListeners,
          __elements: elements,
          __makeElement: makeElement,
          __windowListeners: windowListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

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


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_initialize_file_selection_skips_missing_controls() -> None:
    script = _image_upload_harness(
        """
        const result = sandbox.__initializeFileSelection();
        process.stdout.write(JSON.stringify({
          result,
          listenerCount: sandbox.__elementListeners.length,
          debugMessages: sandbox.__debugMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": False,
        "listenerCount": 0,
        "debugMessages": [
            "Image file selection skipped: upload controls unavailable",
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_initialize_file_selection_wires_controls_when_present() -> None:
    script = _image_upload_harness(
        """
        const fileInput = sandbox.__makeElement('file-upload-input');
        const uploadBtn = sandbox.__makeElement('upload-image-btn');
        sandbox.__elements.set('file-upload-input', fileInput);
        sandbox.__elements.set('upload-image-btn', uploadBtn);

        const uploadCalls = [];
        sandbox.__setHandleFileUpload((files) => {
          uploadCalls.push(Array.from(files).map((file) => file.name));
        });

        const result = sandbox.__initializeFileSelection();
        const clickHandler = sandbox.__elementListeners.find(
          (entry) => entry.id === 'upload-image-btn' && entry.type === 'click',
        ).handler;
        const changeHandler = sandbox.__elementListeners.find(
          (entry) => entry.id === 'file-upload-input' && entry.type === 'change',
        ).handler;

        clickHandler();
        fileInput.files = [{ name: 'a.png' }];
        fileInput.value = '/fake/path/a.png';
        changeHandler({ target: fileInput });

        process.stdout.write(JSON.stringify({
          result,
          clickCalls: fileInput.clickCalls,
          listenerTypes: sandbox.__elementListeners.map((entry) => `${entry.id}:${entry.type}`),
          uploadCalls,
          inputValue: fileInput.value,
          debugMessages: sandbox.__debugMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": True,
        "clickCalls": 1,
        "listenerTypes": [
            "upload-image-btn:click",
            "file-upload-input:change",
        ],
        "uploadCalls": [["a.png"]],
        "inputValue": "",
        "debugMessages": [],
    }
