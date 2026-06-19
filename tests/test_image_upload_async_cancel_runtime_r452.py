"""Runtime checks for stale async image-upload work after user cancellation."""

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
          + '\\nglobalThis.__addImageToList = addImageToList;'
          + '\\nglobalThis.__clearAllImages = clearAllImages;'
          + '\\nglobalThis.__removeImage = removeImage;'
          + '\\nglobalThis.__setCompressImage = function (fn) {{ compressImage = fn; }};'
          + '\\nglobalThis.__getSelectedImages = function () {{ return selectedImages; }};';

        const createdUrls = [];
        const debugMessages = [];
        const documentListeners = [];
        const elements = new Map();
        const errorMessages = [];
        const rafCallbacks = [];
        const replacedContents = [];
        const revokedUrls = [];
        const statusCalls = [];
        const windowListeners = [];
        let now = 1700000000000;
        let urlSeq = 0;

        function makeClassList() {{
          const classes = new Set();
          return {{
            add(name) {{ classes.add(name); }},
            contains(name) {{ return classes.has(name); }},
            remove(name) {{ classes.delete(name); }},
            toArray() {{ return Array.from(classes).sort(); }},
          }};
        }}

        function registerElement(el) {{
          if (el && el.id) elements.set(el.id, el);
        }}

        function makeElement(id) {{
          const el = {{
            id,
            alt: '',
            children: [],
            classList: makeClassList(),
            className: '',
            dataset: {{}},
            parentNode: null,
            src: '',
            style: {{}},
            textContent: '',
            appendChild(child) {{
              child.parentNode = this;
              this.children.push(child);
              registerElement(child);
            }},
            addEventListener() {{}},
            getContext() {{ return {{}}; }},
            querySelector() {{ return null; }},
            remove() {{
              if (this.parentNode) {{
                const siblings = this.parentNode.children;
                const index = siblings.indexOf(this);
                if (index >= 0) siblings.splice(index, 1);
              }}
              elements.delete(this.id);
              this.parentNode = null;
            }},
            removeAttribute() {{}},
            setAttribute() {{}},
          }};
          registerElement(el);
          return el;
        }}

        const previewContainer = makeElement('image-previews');
        const previewShell = makeElement('image-preview-container');
        const countEl = makeElement('image-count');

        const sandbox = {{
          Array,
          Blob: function Blob() {{}},
          Date: {{ now: () => now }},
          Error,
          File: function File(parts, name, options) {{
            this.parts = parts;
            this.name = name;
            this.type = options && options.type;
            this.lastModified = options && options.lastModified;
            this.size = parts && parts[0] && parts[0].length ? parts[0].length : 0;
          }},
          FileList: function FileList() {{}},
          FileReader: function FileReader() {{}},
          Image: function Image() {{
            this.onload = null;
            this.onerror = null;
            this.src = '';
          }},
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
          URL: {{
            createObjectURL(file) {{
              urlSeq += 1;
              const url = `blob:async-${{urlSeq}}`;
              createdUrls.push({{ url, name: file && file.name }});
              return url;
            }},
            revokeObjectURL(url) {{
              revokedUrls.push(url);
            }},
          }},
          console: {{
            debug(...args) {{ debugMessages.push(args.join(' ')); }},
            error(...args) {{ errorMessages.push(args.join(' ')); }},
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
              return {{ children: [], appendChild(child) {{ this.children.push(child); }} }};
            }},
            createElement(tag) {{
              return makeElement(tag);
            }},
            getElementById(id) {{
              return elements.get(id) || null;
            }},
            querySelector() {{ return null; }},
          }},
          DOMSecurity: {{
            clearContent(el) {{
              if (!el) return;
              for (const child of el.children.slice()) {{
                elements.delete(child.id);
                child.parentNode = null;
              }}
              el.children = [];
            }},
            createImagePreview(imageItem, isLoading) {{
              return {{
                firstChild: null,
                imageId: imageItem.id,
                isLoading,
              }};
            }},
            replaceContent(el, fragment) {{
              replacedContents.push({{ id: el.id, childCount: fragment.children.length }});
            }},
          }},
          navigator: {{ clipboard: {{ read() {{}} }} }},
          performance: {{ now: () => now }},
          requestAnimationFrame(fn) {{
            rafCallbacks.push(fn);
            return rafCallbacks.length;
          }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn) {{ return {{ fn }}; }},
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
          __createdUrls: createdUrls,
          __debugMessages: debugMessages,
          __elements: elements,
          __errorMessages: errorMessages,
          __flushRafs() {{
            while (rafCallbacks.length > 0) {{
              const callback = rafCallbacks.shift();
              callback();
            }}
          }},
          __previewContainer: previewContainer,
          __previewShell: previewShell,
          __replacedContents: replacedContents,
          __revokedUrls: revokedUrls,
          __statusCalls: statusCalls,
          __setNow(value) {{
            now = value;
          }},
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        function makeFile(name) {{
          return {{
            name,
            size: 1024,
            type: 'image/png',
            lastModified: 123,
          }};
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
def test_removed_pending_image_does_not_recreate_preview_or_blob_url() -> None:
    script = _image_upload_harness(
        """
        let resolveCompress;
        sandbox.__setCompressImage((file) => new Promise((resolve) => {
          resolveCompress = resolve;
        }));

        const pending = sandbox.__addImageToList(makeFile('slow.png'));
        sandbox.__flushRafs();

        const imageId = sandbox.__getSelectedImages()[0].id;
        const previewId = `preview-${imageId}`;
        const previewBeforeRemove = !!sandbox.__elements.get(previewId);
        sandbox.__removeImage(imageId);

        resolveCompress(makeFile('slow.png'));
        const result = await pending;
        sandbox.__flushRafs();

        process.stdout.write(JSON.stringify({
          result,
          previewBeforeRemove,
          previewAfterResolve: !!sandbox.__elements.get(previewId),
          selectedCount: sandbox.__getSelectedImages().length,
          createdUrls: sandbox.__createdUrls,
          statusCalls: sandbox.__statusCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": False,
        "previewBeforeRemove": True,
        "previewAfterResolve": False,
        "selectedCount": 0,
        "createdUrls": [],
        "statusCalls": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_cleared_pending_image_failure_is_quiet() -> None:
    script = _image_upload_harness(
        """
        let rejectCompress;
        sandbox.__setCompressImage(() => new Promise((_resolve, reject) => {
          rejectCompress = reject;
        }));

        const pending = sandbox.__addImageToList(makeFile('broken.png'));
        sandbox.__flushRafs();
        sandbox.__clearAllImages();

        rejectCompress(new Error('decode failed'));
        const result = await pending;
        sandbox.__flushRafs();

        process.stdout.write(JSON.stringify({
          result,
          selectedCount: sandbox.__getSelectedImages().length,
          previewChildren: sandbox.__previewContainer.children.length,
          errorMessages: sandbox.__errorMessages,
          statusCalls: sandbox.__statusCalls,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": False,
        "selectedCount": 0,
        "previewChildren": 0,
        "errorMessages": [],
        "statusCalls": [],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_queued_preview_render_does_not_resurrect_removed_image() -> None:
    script = _image_upload_harness(
        """
        sandbox.__setCompressImage(async (file) => file);

        const pending = sandbox.__addImageToList(makeFile('fast.png'));
        sandbox.__flushRafs();
        const result = await pending;

        const imageId = sandbox.__getSelectedImages()[0].id;
        const previewId = `preview-${imageId}`;
        sandbox.__removeImage(imageId);
        sandbox.__flushRafs();

        process.stdout.write(JSON.stringify({
          result,
          previewAfterQueuedRender: !!sandbox.__elements.get(previewId),
          selectedCount: sandbox.__getSelectedImages().length,
          createdUrls: sandbox.__createdUrls,
          revokedUrls: sandbox.__revokedUrls,
          replacedCount: sandbox.__replacedContents.length,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": True,
        "previewAfterQueuedRender": False,
        "selectedCount": 0,
        "createdUrls": [{"url": "blob:async-1", "name": "fast.png"}],
        "revokedUrls": ["blob:async-1"],
        "replacedCount": 1,
    }
