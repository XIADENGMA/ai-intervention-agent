"""R596 regression coverage for image-upload object URL cleanup loops."""

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


def test_object_url_cleanup_paths_use_iterators_without_foreach_callbacks() -> None:
    source = _source()
    all_body = _extract_function(source, "function cleanupAllObjectURLs(")
    expired_body = _extract_function(source, "function cleanupExpiredObjectURLs(")

    assert "objectURLs.forEach" not in all_body
    assert "urlCreationTime.forEach" not in expired_body
    assert "expiredUrls.forEach" not in expired_body
    assert "for (const url of objectURLs)" in all_body
    assert "for (const [url, creationTime] of urlCreationTime)" in expired_body
    assert "const expiredUrlCount = expiredUrls.length;" in expired_body
    assert "for (let index = 0; index < expiredUrlCount; index += 1)" in expired_body
    assert "revokeObjectURL(expiredUrls[index]);" in expired_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_object_url_cleanup_preserves_lifecycle_without_collection_foreach() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(IMAGE_UPLOAD_JS)!r}, 'utf8');

        const clearedIntervals = [];
        const errors = [];
        const intervals = [];
        const revokedUrls = [];
        let now = 1000000;
        let urlSeq = 0;

        function snapshotState(exported) {{
          const state = exported._getObjectURLLifecycleState();
          return {{
            size: state.size,
            cleanupIntervalId: state.cleanupIntervalId,
            trackedUrls: state.trackedUrls,
            creationTimes: state.creationTimes,
          }};
        }}

        const sandbox = {{
          Array,
          Blob: function Blob() {{}},
          Date: {{ now: () => now }},
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
            createObjectURL() {{
              urlSeq += 1;
              return `blob:test-${{urlSeq}}`;
            }},
            revokeObjectURL(url) {{
              revokedUrls.push(url);
              if (url === 'blob:test-2') {{
                throw new Error('synthetic revoke failure');
              }}
            }},
          }},
          console: {{
            debug() {{}},
            error(...args) {{
              errors.push(String(args[0]));
            }},
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
            getElementById() {{ return null; }},
            querySelector() {{ return null; }},
          }},
          DOMSecurity: {{
            clearContent() {{}},
            createImagePreview() {{ return {{ firstChild: null }}; }},
            replaceContent() {{}},
          }},
          navigator: {{ clipboard: {{ read() {{}} }} }},
          performance: {{ now: () => now }},
          addEventListener() {{}},
          requestAnimationFrame(fn) {{ return fn(); }},
          setInterval(fn, delay) {{
            const id = `interval-${{intervals.length + 1}}`;
            intervals.push({{ id, fn, delay }});
            return id;
          }},
          clearInterval(id) {{
            clearedIntervals.push(id);
          }},
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

        vm.runInContext(
          "Set.prototype.forEach = function disabledSetForEach() " +
          "{{ throw new Error('Set.prototype.forEach must not be used'); }};" +
          "Map.prototype.forEach = function disabledMapForEach() " +
          "{{ throw new Error('Map.prototype.forEach must not be used'); }};" +
          "Array.prototype.forEach = function disabledArrayForEach() " +
          "{{ throw new Error('Array.prototype.forEach must not be used'); }};",
          sandbox,
        );

        const first = exported.createObjectURL({{ name: 'first.png' }});
        now += exported.OBJECT_URL_MAX_AGE_MS + 10;
        const second = exported.createObjectURL({{ name: 'second.png' }});
        now += 10;
        const third = exported.createObjectURL({{ name: 'third.png' }});

        const removed = exported.cleanupExpiredObjectURLs(
          now + exported.OBJECT_URL_MAX_AGE_MS + 1,
        );
        const afterExpired = snapshotState(exported);
        const afterExpiredRevokes = revokedUrls.slice();
        const afterExpiredErrors = errors.slice();

        const fourth = exported.createObjectURL({{ name: 'fourth.png' }});
        exported.cleanupAllObjectURLs();
        const afterAll = snapshotState(exported);

        process.stdout.write(JSON.stringify({{
          urls: [first, second, third, fourth],
          removed,
          afterExpired,
          afterExpiredRevokes,
          afterExpiredErrors,
          allRevokes: revokedUrls,
          allErrors: errors,
          clearedIntervals,
          afterAll,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "urls": [
            "blob:test-1",
            "blob:test-2",
            "blob:test-3",
            "blob:test-4",
        ],
        "removed": 3,
        "afterExpired": {
            "size": 1,
            "cleanupIntervalId": "interval-1",
            "trackedUrls": ["blob:test-2"],
            "creationTimes": [["blob:test-2", 2200010]],
        },
        "afterExpiredRevokes": ["blob:test-1", "blob:test-2", "blob:test-3"],
        "afterExpiredErrors": ["Revoke object URL failed:"],
        "allRevokes": [
            "blob:test-1",
            "blob:test-2",
            "blob:test-3",
            "blob:test-2",
            "blob:test-4",
        ],
        "allErrors": [
            "Revoke object URL failed:",
            "Revoke URL failed: blob:test-2",
        ],
        "clearedIntervals": ["interval-1"],
        "afterAll": {
            "size": 0,
            "cleanupIntervalId": None,
            "trackedUrls": [],
            "creationTimes": [],
        },
    }
