"""R597 regression coverage for image-upload clear-all loops."""

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


def test_clear_all_images_uses_indexed_loop_without_array_foreach() -> None:
    body = _extract_function(_source(), "function clearAllImages(")

    assert "selectedImages.forEach" not in body
    assert "const selectedImageCount = selectedImages.length;" in body
    assert "for (let index = 0; index < selectedImageCount; index += 1)" in body
    assert "if (!(index in selectedImages)) continue;" in body
    assert "const img = selectedImages[index];" in body
    assert 'img.previewUrl.startsWith("blob:")' in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_clear_all_images_releases_blob_urls_and_resets_ui_without_foreach() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(IMAGE_UPLOAD_JS)!r}, 'utf8')
          + '\\nglobalThis.__setSelectedImages = function (items) {{ selectedImages = items; }};'
          + '\\nglobalThis.__getSelectedImages = function () {{ return selectedImages; }};'
          + '\\nglobalThis.__clearAllImages = clearAllImages;';

        const classChanges = [];
        const clearedContainers = [];
        const debugMessages = [];
        const revokedUrls = [];

        function makeClassList(id) {{
          const values = Object.create(null);
          return {{
            add(name) {{
              values[name] = true;
              classChanges.push([id, 'add', name]);
            }},
            contains(name) {{
              return values[name] === true;
            }},
            remove(name) {{
              delete values[name];
              classChanges.push([id, 'remove', name]);
            }},
            values,
          }};
        }}

        const elements = {{
          'image-previews': {{ id: 'image-previews' }},
          'image-count': {{ id: 'image-count', textContent: '3' }},
          'image-preview-container': {{
            id: 'image-preview-container',
            classList: makeClassList('image-preview-container'),
          }},
        }};

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
            createObjectURL(file) {{ return file.url; }},
            revokeObjectURL(url) {{
              revokedUrls.push(url);
            }},
          }},
          console: {{
            debug(message) {{
              debugMessages.push(String(message));
            }},
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
            contains() {{ return false; }},
            createDocumentFragment() {{ return {{ appendChild() {{}} }}; }},
            createElement() {{
              return {{
                classList: {{ add() {{}}, remove() {{}} }},
                dataset: {{}},
                getContext() {{ return {{}}; }},
                querySelector() {{ return null; }},
                removeAttribute() {{}},
                setAttribute() {{}},
                style: {{}},
              }};
            }},
            getElementById(id) {{
              return elements[id] || null;
            }},
            querySelector() {{ return null; }},
          }},
          DOMSecurity: {{
            clearContent(element) {{
              clearedContainers.push(element ? element.id : null);
            }},
            createImagePreview() {{ return {{ firstChild: null }}; }},
            replaceContent() {{}},
          }},
          navigator: {{ clipboard: {{ read() {{}} }} }},
          performance: {{ now() {{ return 0; }} }},
          addEventListener() {{}},
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
          module: {{ exports: {{}} }},
          exports: {{}},
          window: null,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const exported = sandbox.module.exports;
        const blobA = exported.createObjectURL({{ url: 'blob:a' }});
        const blobD = exported.createObjectURL({{ url: 'blob:d' }});

        vm.runInContext(
          "Array.prototype.forEach = function disabledArrayForEach() " +
          "{{ throw new Error('Array.prototype.forEach must not be used'); }};",
          sandbox,
        );

        const images = [
          {{ id: 'a', previewUrl: blobA }},
          {{ id: 'hole', previewUrl: 'blob:hole' }},
          {{ id: 'c', previewUrl: 'data:image/png;base64,aaaa' }},
          {{ id: 'd', previewUrl: blobD }},
        ];
        delete images[1];

        sandbox.__setSelectedImages(images);
        sandbox.__clearAllImages();

        process.stdout.write(JSON.stringify({{
          revokedUrls,
          clearedContainers,
          countText: elements['image-count'].textContent,
          selectedImages: sandbox.__getSelectedImages(),
          classChanges,
          isHidden: elements['image-preview-container'].classList.contains('hidden'),
          isVisible: elements['image-preview-container'].classList.contains('visible'),
          debugMessages,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "revokedUrls": ["blob:a", "blob:d"],
        "clearedContainers": ["image-previews"],
        "countText": 0,
        "selectedImages": [],
        "classChanges": [
            ["image-preview-container", "add", "hidden"],
            ["image-preview-container", "remove", "visible"],
        ],
        "isHidden": True,
        "isVisible": False,
        "debugMessages": [
            "Revoked object URL: blob:a",
            "Revoked object URL: blob:d",
            "All images cleared; memory released",
        ],
    }
