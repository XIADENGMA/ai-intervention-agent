"""Runtime checks for image preview modal open/close ownership."""

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
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _image_modal_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(IMAGE_UPLOAD_JS)!r}, 'utf8')
          + '\\nglobalThis.__openImageModal = openImageModal;'
          + '\\nglobalThis.__closeImageModal = closeImageModal;';

        const documentListeners = [];
        const documentRemovedListeners = [];
        const debugMessages = [];
        const focusedIds = [];
        const elements = new Map();
        const missingIds = new Set();
        const windowListeners = [];

        function makeClassList(initial) {{
          const classes = new Set(initial || []);
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
            alt: '',
            classList: makeClassList(),
            dataset: {{}},
            hidden: false,
            parentNode: null,
            src: '',
            style: {{}},
            textContent: '',
            addEventListener() {{}},
            appendChild() {{}},
            focus() {{
              focusedIds.push(id);
              sandbox.document.activeElement = this;
            }},
            getContext() {{
              return null;
            }},
            querySelector(selector) {{
              if (selector === '.image-modal-close') return getElement('image-modal-close');
              return null;
            }},
            removeAttribute(name) {{
              if (name === 'hidden') this.hidden = false;
            }},
            setAttribute(name) {{
              if (name === 'hidden') this.hidden = true;
            }},
          }};
        }}

        function getElement(id) {{
          if (!elements.has(id)) {{
            elements.set(id, makeElement(id));
          }}
          return elements.get(id);
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
            addEventListener(type, handler) {{
              documentListeners.push({{ type, handler }});
            }},
            contains(el) {{
              return el && (el.id === 'opener' || el.id === 'image-modal-close');
            }},
            createElement(tag) {{
              return makeElement(tag);
            }},
            getElementById(id) {{
              if (missingIds.has(id)) return null;
              return getElement(id);
            }},
            querySelector(selector) {{
              if (selector === '.image-modal-close') return getElement('image-modal-close');
              return null;
            }},
            readyState: 'loading',
            removeEventListener(type, handler) {{
              documentRemovedListeners.push({{ type, handler }});
            }},
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          navigator: {{}},
          requestAnimationFrame(fn) {{
            return fn();
          }},
          setInterval() {{
            return 1;
          }},
          clearInterval() {{}},
          setTimeout(fn) {{
            return {{ fn }};
          }},
          clearTimeout() {{}},
          showStatus() {{}},
          t(key, params) {{
            if (key === 'status.sizeLabelKB') return `${{params.name}}:${{params.size}}`;
            return key;
          }},
          window: null,
          __documentListeners: documentListeners,
          __documentRemovedListeners: documentRemovedListeners,
          __debugMessages: debugMessages,
          __focusedIds: focusedIds,
          __getElement: getElement,
          __missingIds: missingIds,
          __windowListeners: windowListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.addEventListener = (type, handler) => {{
          windowListeners.push({{ type, handler }});
        }};

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
def test_reopening_image_modal_preserves_original_focus_origin_and_listener_pairing() -> (
    None
):
    script = _image_modal_harness(
        """
        const opener = sandbox.__getElement('opener');
        sandbox.document.activeElement = opener;

        sandbox.__openImageModal('data:first', 'first.png', 2048);
        sandbox.__openImageModal('data:second', 'second.png', 4096);

        const beforeClose = {
          keydownAdds: sandbox.__documentListeners.filter((entry) => entry.type === 'keydown').length,
          modalOpen: sandbox.__getElement('image-modal').classList.contains('show'),
          imageSrc: sandbox.__getElement('modal-image').src,
          imageAlt: sandbox.__getElement('modal-image').alt,
          info: sandbox.__getElement('modal-info').textContent,
        };

        sandbox.__closeImageModal();
        sandbox.__closeImageModal();

        process.stdout.write(
          JSON.stringify({
            beforeClose,
            keydownRemoves: sandbox.__documentRemovedListeners.filter((entry) => entry.type === 'keydown').length,
            focusedIds: sandbox.__focusedIds,
            modalHidden: sandbox.__getElement('image-modal').hidden,
            modalOpenAfterClose: sandbox.__getElement('image-modal').classList.contains('show'),
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "beforeClose": {
            "keydownAdds": 2,
            "modalOpen": True,
            "imageSrc": "data:second",
            "imageAlt": "second.png",
            "info": "second.png:4.00",
        },
        "keydownRemoves": 2,
        "focusedIds": ["image-modal-close", "opener"],
        "modalHidden": True,
        "modalOpenAfterClose": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_open_image_modal_returns_false_when_required_parts_are_missing() -> None:
    script = _image_modal_harness(
        """
        sandbox.__missingIds.add('image-modal');
        sandbox.__missingIds.add('modal-image');
        sandbox.__missingIds.add('modal-info');

        let threw = false;
        let result = null;
        try {
          result = sandbox.__openImageModal('data:first', 'first.png', 2048);
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          threw,
          result,
          keydownAdds: sandbox.__documentListeners.filter((entry) => entry.type === 'keydown').length,
          focusedIds: sandbox.__focusedIds,
          debugMessages: sandbox.__debugMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "result": False,
        "keydownAdds": 0,
        "focusedIds": [],
        "debugMessages": [
            "Image modal open skipped: #image-modal, #modal-image, #modal-info unavailable",
        ],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_close_image_modal_detaches_handlers_when_modal_was_removed() -> None:
    script = _image_modal_harness(
        """
        const opener = sandbox.__getElement('opener');
        sandbox.document.activeElement = opener;
        sandbox.__openImageModal('data:first', 'first.png', 2048);
        sandbox.__missingIds.add('image-modal');

        let threw = false;
        let result = null;
        try {
          result = sandbox.__closeImageModal();
        } catch (_err) {
          threw = true;
        }

        process.stdout.write(JSON.stringify({
          threw,
          result,
          keydownAdds: sandbox.__documentListeners.filter((entry) => entry.type === 'keydown').length,
          keydownRemoves: sandbox.__documentRemovedListeners.filter((entry) => entry.type === 'keydown').length,
          focusedIds: sandbox.__focusedIds,
          debugMessages: sandbox.__debugMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "threw": False,
        "result": False,
        "keydownAdds": 2,
        "keydownRemoves": 2,
        "focusedIds": ["image-modal-close", "opener"],
        "debugMessages": [
            "Image modal close skipped: #image-modal unavailable",
        ],
    }
