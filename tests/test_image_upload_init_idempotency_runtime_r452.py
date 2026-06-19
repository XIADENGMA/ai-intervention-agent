"""Runtime checks for image-upload initialization idempotency."""

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
          + '\\nglobalThis.__initializeDragAndDrop = initializeDragAndDrop;'
          + '\\nglobalThis.__initializeFileSelection = initializeFileSelection;'
          + '\\nglobalThis.__initializeImageFeatures = initializeImageFeatures;'
          + '\\nglobalThis.__setHandleFileUpload = function (fn) {{ handleFileUpload = fn; }};';

        const activeDocumentListeners = [];
        const addedDocumentListeners = [];
        const removedDocumentListeners = [];
        const debugMessages = [];
        const elementListeners = [];
        const elements = new Map();
        const statusCalls = [];
        const timeouts = [];
        const windowListeners = [];

        function removeListener(bucket, type, handler) {{
          const index = bucket.findIndex((entry) => (
            entry.type === type && entry.handler === handler
          ));
          if (index >= 0) bucket.splice(index, 1);
        }}

        function makeClassList() {{
          const classes = new Set();
          return {{
            add(name) {{ classes.add(name); }},
            contains(name) {{ return classes.has(name); }},
            remove(name) {{ classes.delete(name); }},
            toArray() {{ return Array.from(classes).sort(); }},
          }};
        }}

        function makeElement(id) {{
          return {{
            id,
            children: [],
            classList: makeClassList(),
            clickCalls: 0,
            dataset: {{}},
            files: [],
            style: {{}},
            value: '',
            addEventListener(type, handler, options) {{
              elementListeners.push({{ id, type, handler, options }});
            }},
            appendChild(child) {{
              this.children.push(child);
            }},
            click() {{
              this.clickCalls += 1;
            }},
            getContext() {{
              return {{}};
            }},
            querySelector() {{
              return null;
            }},
            removeAttribute() {{}},
            setAttribute() {{}},
          }};
        }}

        function dispatchDocument(type, event) {{
          for (const entry of activeDocumentListeners.slice()) {{
            if (entry.type === type) entry.handler(event);
          }}
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
          Uint8Array,
          WeakMap,
          Worker: function Worker() {{}},
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
            addEventListener(type, handler, options) {{
              const entry = {{ type, handler, options }};
              activeDocumentListeners.push(entry);
              addedDocumentListeners.push(entry);
            }},
            removeEventListener(type, handler, options) {{
              removedDocumentListeners.push({{ type, handler, options }});
              removeListener(activeDocumentListeners, type, handler);
            }},
            contains() {{ return false; }},
            createDocumentFragment() {{
              return {{ appendChild() {{}} }};
            }},
            createElement(tag) {{
              const element = makeElement(tag);
              if (tag === 'div') element.ondragstart = null;
              return element;
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
          navigator: {{ clipboard: {{ read() {{}} }} }},
          performance: {{ now: () => 0 }},
          requestAnimationFrame(fn) {{ return fn(); }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn, delay) {{
            const id = `timeout-${{timeouts.length + 1}}`;
            timeouts.push({{ id, fn, delay }});
            return id;
          }},
          clearTimeout() {{}},
          showStatus(message, type) {{
            statusCalls.push({{ message, type }});
          }},
          t(key, params) {{
            return params ? `${{key}}:${{JSON.stringify(params)}}` : key;
          }},
          addEventListener(type, handler) {{
            windowListeners.push({{ type, handler }});
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          window: null,
          __activeDocumentListeners: activeDocumentListeners,
          __addedDocumentListeners: addedDocumentListeners,
          __debugMessages: debugMessages,
          __dispatchDocument: dispatchDocument,
          __elementListeners: elementListeners,
          __elements: elements,
          __makeElement: makeElement,
          __removedDocumentListeners: removedDocumentListeners,
          __statusCalls: statusCalls,
          __timeouts: timeouts,
          __windowListeners: windowListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        function addUploadControls() {{
          const textarea = sandbox.__makeElement('feedback-text');
          const overlay = sandbox.__makeElement('drag-overlay');
          const fileInput = sandbox.__makeElement('file-upload-input');
          const uploadBtn = sandbox.__makeElement('upload-image-btn');
          const clearBtn = sandbox.__makeElement('clear-all-images-btn');
          sandbox.__elements.set('feedback-text', textarea);
          sandbox.__elements.set('drag-overlay', overlay);
          sandbox.__elements.set('file-upload-input', fileInput);
          sandbox.__elements.set('upload-image-btn', uploadBtn);
          sandbox.__elements.set('clear-all-images-btn', clearBtn);
          return {{ textarea, overlay, fileInput, uploadBtn, clearBtn }};
        }}

        function documentListenerCounts() {{
          const counts = {{}};
          for (const entry of sandbox.__activeDocumentListeners) {{
            counts[entry.type] = (counts[entry.type] || 0) + 1;
          }}
          return counts;
        }}

        function elementListenerTypes() {{
          return sandbox.__elementListeners.map(
            (entry) => `${{entry.id}}:${{entry.type}}`,
          );
        }}

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_drag_and_drop_missing_controls_cleans_existing_listeners() -> None:
    script = _image_upload_harness(
        """
        addUploadControls();
        const firstResult = sandbox.__initializeDragAndDrop();
        const dragListenersAfterFirst = sandbox.__activeDocumentListeners
          .filter((entry) => ['dragenter', 'dragover', 'dragleave', 'drop'].includes(entry.type))
          .length;

        sandbox.__elements.delete('feedback-text');
        sandbox.__elements.delete('drag-overlay');
        const secondResult = sandbox.__initializeDragAndDrop();
        const dragListenersAfterSecond = sandbox.__activeDocumentListeners
          .filter((entry) => ['dragenter', 'dragover', 'dragleave', 'drop'].includes(entry.type))
          .length;

        process.stdout.write(JSON.stringify({
          firstResult,
          secondResult,
          dragListenersAfterFirst,
          dragListenersAfterSecond,
          cleanupType: typeof sandbox.__aiInterventionAgentDragDropCleanup,
          removedCount: sandbox.__removedDocumentListeners.length,
          debugMessages: sandbox.__debugMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "firstResult": True,
        "secondResult": False,
        "dragListenersAfterFirst": 8,
        "dragListenersAfterSecond": 0,
        "cleanupType": "object",
        "removedCount": 8,
        "debugMessages": [
            "Image drag-and-drop skipped: #feedback-text, #drag-overlay unavailable",
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_repeated_drag_and_drop_init_replaces_old_handlers() -> None:
    script = _image_upload_harness(
        """
        addUploadControls();
        const uploadCalls = [];
        sandbox.__setHandleFileUpload((files) => {
          uploadCalls.push(Array.from(files).map((file) => file.name));
        });

        const firstResult = sandbox.__initializeDragAndDrop();
        const secondResult = sandbox.__initializeDragAndDrop();
        const counts = documentListenerCounts();

        let preventDefaultCalls = 0;
        let stopPropagationCalls = 0;
        sandbox.__dispatchDocument('drop', {
          dataTransfer: {
            types: ['Files'],
            files: [{ name: 'a.png' }],
          },
          preventDefault() { preventDefaultCalls += 1; },
          stopPropagation() { stopPropagationCalls += 1; },
        });

        process.stdout.write(JSON.stringify({
          firstResult,
          secondResult,
          dropListeners: counts.drop,
          dragenterListeners: counts.dragenter,
          removedCount: sandbox.__removedDocumentListeners.length,
          uploadCalls,
          preventDefaultCalls,
          stopPropagationCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "firstResult": True,
        "secondResult": True,
        "dropListeners": 2,
        "dragenterListeners": 2,
        "removedCount": 8,
        "uploadCalls": [["a.png"]],
        "preventDefaultCalls": 1,
        "stopPropagationCalls": 1,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_non_file_drag_events_are_not_suppressed() -> None:
    script = _image_upload_harness(
        """
        const controls = addUploadControls();
        sandbox.__initializeDragAndDrop();

        function makeDragEvent(types) {
          return {
            preventDefaultCalls: 0,
            stopPropagationCalls: 0,
            dataTransfer: {
              types,
              files: types.includes('Files') ? [{ name: 'a.png' }] : [],
              dropEffect: 'move',
            },
            preventDefault() { this.preventDefaultCalls += 1; },
            stopPropagation() { this.stopPropagationCalls += 1; },
          };
        }

        const nonFileOver = makeDragEvent(['text/plain']);
        sandbox.__dispatchDocument('dragover', nonFileOver);

        const fileOver = makeDragEvent(['Files']);
        sandbox.__dispatchDocument('dragover', fileOver);

        const nonFileEnter = makeDragEvent(['text/plain']);
        sandbox.__dispatchDocument('dragenter', nonFileEnter);

        const fileEnter = makeDragEvent(['Files']);
        sandbox.__dispatchDocument('dragenter', fileEnter);

        process.stdout.write(JSON.stringify({
          nonFileOverPreventDefaultCalls: nonFileOver.preventDefaultCalls,
          nonFileOverStopPropagationCalls: nonFileOver.stopPropagationCalls,
          nonFileOverDropEffect: nonFileOver.dataTransfer.dropEffect,
          fileOverPreventDefaultCalls: fileOver.preventDefaultCalls,
          fileOverStopPropagationCalls: fileOver.stopPropagationCalls,
          fileOverDropEffect: fileOver.dataTransfer.dropEffect,
          nonFileEnterPreventDefaultCalls: nonFileEnter.preventDefaultCalls,
          nonFileEnterStopPropagationCalls: nonFileEnter.stopPropagationCalls,
          fileEnterPreventDefaultCalls: fileEnter.preventDefaultCalls,
          fileEnterStopPropagationCalls: fileEnter.stopPropagationCalls,
          overlayDisplay: controls.overlay.style.display,
          textareaClasses: controls.textarea.classList.toArray(),
          dragoverListeners: documentListenerCounts().dragover,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "nonFileOverPreventDefaultCalls": 0,
        "nonFileOverStopPropagationCalls": 0,
        "nonFileOverDropEffect": "move",
        "fileOverPreventDefaultCalls": 1,
        "fileOverStopPropagationCalls": 1,
        "fileOverDropEffect": "copy",
        "nonFileEnterPreventDefaultCalls": 0,
        "nonFileEnterStopPropagationCalls": 0,
        "fileEnterPreventDefaultCalls": 1,
        "fileEnterStopPropagationCalls": 1,
        "overlayDisplay": "flex",
        "textareaClasses": ["textarea-drag-over"],
        "dragoverListeners": 2,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_repeated_file_selection_init_does_not_duplicate_handlers() -> None:
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

        const firstResult = sandbox.__initializeFileSelection();
        const secondResult = sandbox.__initializeFileSelection();
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
          firstResult,
          secondResult,
          listenerTypes: elementListenerTypes(),
          clickCalls: fileInput.clickCalls,
          uploadCalls,
          inputValue: fileInput.value,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "firstResult": True,
        "secondResult": True,
        "listenerTypes": [
            "upload-image-btn:click",
            "file-upload-input:change",
        ],
        "clickCalls": 1,
        "uploadCalls": [["a.png"]],
        "inputValue": "",
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_repeated_image_features_init_keeps_single_live_listener_set() -> None:
    script = _image_upload_harness(
        """
        addUploadControls();

        sandbox.__initializeImageFeatures();
        sandbox.__initializeImageFeatures();

        const clearListeners = sandbox.__elementListeners.filter(
          (entry) => entry.id === 'clear-all-images-btn' && entry.type === 'click',
        ).length;
        const uploadClickListeners = sandbox.__elementListeners.filter(
          (entry) => entry.id === 'upload-image-btn' && entry.type === 'click',
        ).length;
        const fileChangeListeners = sandbox.__elementListeners.filter(
          (entry) => entry.id === 'file-upload-input' && entry.type === 'change',
        ).length;
        const counts = documentListenerCounts();

        process.stdout.write(JSON.stringify({
          clearListeners,
          uploadClickListeners,
          fileChangeListeners,
          dragenterListeners: counts.dragenter,
          dragoverListeners: counts.dragover,
          dragleaveListeners: counts.dragleave,
          dropListeners: counts.drop,
          pasteListeners: counts.paste,
          removedDocumentListenerCount: sandbox.__removedDocumentListeners.length,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "clearListeners": 1,
        "uploadClickListeners": 1,
        "fileChangeListeners": 1,
        "dragenterListeners": 2,
        "dragoverListeners": 2,
        "dragleaveListeners": 2,
        "dropListeners": 2,
        "pasteListeners": 1,
        "removedDocumentListenerCount": 9,
    }
