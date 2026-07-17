"""R595 regression coverage for image-upload drag/drop listener loops."""

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


def test_drag_drop_listener_paths_use_direct_calls_and_indexed_cleanup() -> None:
    body = _extract_function(_source(), "function initializeDragAndDrop(")

    assert '["dragenter", "dragover", "dragleave", "drop"].forEach' not in body
    assert "listenerEntries.forEach" not in body
    assert "const preventDefaultListenerOptions = { passive: false };" in body
    assert (
        'addDocumentListener("dragenter", preventDefaults, preventDefaultListenerOptions);'
        in body
    )
    assert (
        'addDocumentListener("dragover", preventDefaults, preventDefaultListenerOptions);'
        in body
    )
    assert (
        'addDocumentListener("dragleave", preventDefaults, preventDefaultListenerOptions);'
        in body
    )
    assert (
        'addDocumentListener("drop", preventDefaults, preventDefaultListenerOptions);'
        in body
    )
    assert "const listenerEntryCount = listenerEntries.length;" in body
    assert "for (let index = 0; index < listenerEntryCount; index += 1)" in body
    assert "if (!(index in listenerEntries)) continue;" in body
    assert "const entry = listenerEntries[index];" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_drag_drop_reinit_cleanup_and_file_events_do_not_need_array_foreach() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(IMAGE_UPLOAD_JS)!r}, 'utf8')
          + '\\nglobalThis.__initializeDragAndDrop = initializeDragAndDrop;'
          + '\\nglobalThis.__setHandleFileUpload = function (fn) {{ handleFileUpload = fn; }};';

        const activeListeners = [];
        const addedListeners = [];
        const removedListeners = [];
        const uploadCalls = [];
        const elements = {{}};

        function removeActiveListener(type, handler) {{
          for (let index = 0; index < activeListeners.length; index += 1) {{
            const entry = activeListeners[index];
            if (entry.type === type && entry.handler === handler) {{
              activeListeners.splice(index, 1);
              return;
            }}
          }}
        }}

        function makeClassList() {{
          const values = Object.create(null);
          return {{
            add(name) {{ values[name] = true; }},
            contains(name) {{ return values[name] === true; }},
            remove(name) {{ delete values[name]; }},
          }};
        }}

        function makeElement(id) {{
          return {{
            id,
            classList: makeClassList(),
            style: {{}},
          }};
        }}

        function addUploadControls() {{
          elements['feedback-text'] = makeElement('feedback-text');
          elements['drag-overlay'] = makeElement('drag-overlay');
          return {{
            textarea: elements['feedback-text'],
            overlay: elements['drag-overlay'],
          }};
        }}

        function countActive(type) {{
          let count = 0;
          for (let index = 0; index < activeListeners.length; index += 1) {{
            if (activeListeners[index].type === type) count += 1;
          }}
          return count;
        }}

        function listenerOptionsByType(type) {{
          const result = [];
          for (let index = 0; index < addedListeners.length; index += 1) {{
            const entry = addedListeners[index];
            if (entry.type === type) {{
              result.push(entry.options ? entry.options.passive : null);
            }}
          }}
          return result;
        }}

        function dispatchDocument(type, event) {{
          const listenerCount = activeListeners.length;
          for (let index = 0; index < listenerCount; index += 1) {{
            const entry = activeListeners[index];
            if (entry.type === type) entry.handler(event);
          }}
        }}

        function makeTypes(hasFiles) {{
          return {{
            includes(value) {{
              return hasFiles && value === 'Files';
            }},
          }};
        }}

        function makeDragEvent(hasFiles, fileName) {{
          return {{
            preventDefaultCalls: 0,
            stopPropagationCalls: 0,
            dataTransfer: {{
              types: makeTypes(hasFiles),
              files: hasFiles ? [{{ name: fileName || 'a.png' }}] : [],
              dropEffect: 'move',
            }},
            preventDefault() {{
              this.preventDefaultCalls += 1;
            }},
            stopPropagation() {{
              this.stopPropagationCalls += 1;
            }},
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
          Uint8Array,
          WeakMap,
          Worker: function Worker() {{}},
          URL: {{
            createObjectURL() {{ return 'blob:test'; }},
            revokeObjectURL() {{}},
          }},
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            hidden: false,
            addEventListener(type, handler, options) {{
              const entry = {{ type, handler, options }};
              activeListeners.push(entry);
              addedListeners.push(entry);
            }},
            createElement() {{
              return {{ getContext() {{ return {{}}; }} }};
            }},
            getElementById(id) {{
              return elements[id] || null;
            }},
            removeEventListener(type, handler, options) {{
              removedListeners.push({{
                type,
                sameOptionsAsAdded: true,
                passive: options ? options.passive : null,
              }});
              removeActiveListener(type, handler);
            }},
          }},
          navigator: {{ clipboard: {{ read() {{}} }} }},
          performance: {{ now() {{ return 0; }} }},
          requestAnimationFrame(fn) {{
            fn();
            return 1;
          }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout() {{ return 1; }},
          clearTimeout() {{}},
          showStatus() {{}},
          t(key) {{ return key; }},
          addEventListener() {{}},
          module: {{ exports: {{}} }},
          exports: {{}},
          window: null,
          __activeListeners: activeListeners,
          __addedListeners: addedListeners,
          __removedListeners: removedListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        vm.runInContext(
          "Array.prototype.forEach = function disabledForEach() " +
          "{{ throw new Error('Array.prototype.forEach must not be used'); }};",
          sandbox,
        );
        sandbox.__setHandleFileUpload((files) => {{
          const names = [];
          for (let index = 0; index < files.length; index += 1) {{
            names.push(files[index].name);
          }}
          uploadCalls.push(names);
        }});

        const controls = addUploadControls();
        const firstResult = sandbox.__initializeDragAndDrop();
        const countsAfterFirst = {{
          dragenter: countActive('dragenter'),
          dragover: countActive('dragover'),
          dragleave: countActive('dragleave'),
          drop: countActive('drop'),
        }};

        const secondResult = sandbox.__initializeDragAndDrop();
        const countsAfterSecond = {{
          dragenter: countActive('dragenter'),
          dragover: countActive('dragover'),
          dragleave: countActive('dragleave'),
          drop: countActive('drop'),
        }};
        const removedAfterSecondInit = removedListeners.length;
        const activeDragAfterSecond =
          countsAfterSecond.dragenter +
          countsAfterSecond.dragover +
          countsAfterSecond.dragleave +
          countsAfterSecond.drop;

        const nonFileOver = makeDragEvent(false);
        dispatchDocument('dragover', nonFileOver);
        const fileOver = makeDragEvent(true);
        dispatchDocument('dragover', fileOver);
        const fileEnter = makeDragEvent(true);
        dispatchDocument('dragenter', fileEnter);
        const fileDrop = makeDragEvent(true, 'dropped.png');
        dispatchDocument('drop', fileDrop);

        const cleanup = sandbox.__aiInterventionAgentDragDropCleanup;
        cleanup();
        const countsAfterCleanup = {{
          dragenter: countActive('dragenter'),
          dragover: countActive('dragover'),
          dragleave: countActive('dragleave'),
          drop: countActive('drop'),
        }};
        const activeDragAfterCleanup =
          countsAfterCleanup.dragenter +
          countsAfterCleanup.dragover +
          countsAfterCleanup.dragleave +
          countsAfterCleanup.drop;

        process.stdout.write(JSON.stringify({{
          firstResult,
          secondResult,
          countsAfterFirst,
          countsAfterSecond,
          removedAfterSecondInit,
          activeDragAfterSecond,
          dragenterOptions: listenerOptionsByType('dragenter'),
          dropOptions: listenerOptionsByType('drop'),
          nonFileOverPreventDefaultCalls: nonFileOver.preventDefaultCalls,
          fileOverPreventDefaultCalls: fileOver.preventDefaultCalls,
          fileOverStopPropagationCalls: fileOver.stopPropagationCalls,
          fileOverDropEffect: fileOver.dataTransfer.dropEffect,
          fileEnterPreventDefaultCalls: fileEnter.preventDefaultCalls,
          overlayDisplayAfterDrop: controls.overlay.style.display,
          textareaHasDragClassAfterDrop: controls.textarea.classList.contains('textarea-drag-over'),
          fileDropPreventDefaultCalls: fileDrop.preventDefaultCalls,
          uploadCalls,
          removedAfterFinalCleanup: removedListeners.length,
          activeDragAfterCleanup,
          countsAfterCleanup,
          cleanupCleared: sandbox.__aiInterventionAgentDragDropCleanup === null,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "firstResult": True,
        "secondResult": True,
        "countsAfterFirst": {
            "dragenter": 2,
            "dragover": 2,
            "dragleave": 2,
            "drop": 2,
        },
        "countsAfterSecond": {
            "dragenter": 2,
            "dragover": 2,
            "dragleave": 2,
            "drop": 2,
        },
        "removedAfterSecondInit": 8,
        "activeDragAfterSecond": 8,
        "dragenterOptions": [False, None, False, None],
        "dropOptions": [False, None, False, None],
        "nonFileOverPreventDefaultCalls": 0,
        "fileOverPreventDefaultCalls": 1,
        "fileOverStopPropagationCalls": 1,
        "fileOverDropEffect": "copy",
        "fileEnterPreventDefaultCalls": 1,
        "overlayDisplayAfterDrop": "none",
        "textareaHasDragClassAfterDrop": False,
        "fileDropPreventDefaultCalls": 1,
        "uploadCalls": [["dropped.png"]],
        "removedAfterFinalCleanup": 16,
        "activeDragAfterCleanup": 0,
        "countsAfterCleanup": {
            "dragenter": 0,
            "dragover": 0,
            "dragleave": 0,
            "drop": 0,
        },
        "cleanupCleared": True,
    }
