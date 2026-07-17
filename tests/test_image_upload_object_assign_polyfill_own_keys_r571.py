"""R571: image-upload Object.assign fallback avoids Object.keys arrays."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_UPLOAD_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "image-upload.js"
)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> dict[str, object]:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _extract_function(source: str, marker: str) -> str:
    start = source.index(marker)
    body_start = source.index("{", start)
    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"function body not found for {marker}")


def test_object_assign_fallback_uses_guarded_for_in_copy() -> None:
    source = IMAGE_UPLOAD_JS.read_text(encoding="utf-8")
    body = _extract_function(source, "function setupFeatureFallbacks()")

    assert "Object.keys(source)" not in body
    assert "sources.forEach" not in body
    assert ".forEach((key)" not in body
    assert "for (let sourceIndex = 0; sourceIndex < sources.length;" in body
    assert "for (const key in source)" in body
    assert "Object.prototype.hasOwnProperty.call(source, key)" in body
    assert "target[key] = source[key];" in body


def test_object_assign_fallback_copies_only_own_enumerable_string_keys() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const path = {json.dumps(str(IMAGE_UPLOAD_JS))};
        const code = fs.readFileSync(path, 'utf8')
          + '\\nglobalThis.__setupFeatureFallbacks = setupFeatureFallbacks;';

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
          Symbol,
          URL: {{ createObjectURL() {{ return 'blob:test'; }}, revokeObjectURL() {{}} }},
          console: {{ debug() {{}}, error() {{}}, info() {{}}, log() {{}}, warn() {{}} }},
          document: {{
            addEventListener() {{}},
            removeEventListener() {{}},
            getElementById() {{ return null; }},
            querySelector() {{ return null; }},
          }},
          navigator: {{ clipboard: {{}} }},
          performance: {{ now: () => 0 }},
          requestAnimationFrame(callback) {{ return callback(); }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout() {{ return 1; }},
          clearTimeout() {{}},
          addEventListener() {{}},
          removeEventListener() {{}},
          showStatus() {{}},
          t(key) {{ return key; }},
          window: null,
          module: {{ exports: {{}} }},
          exports: {{}},
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        const originalAssign = Object.assign;
        const originalKeys = Object.keys;
        const originalForEach = Array.prototype.forEach;

        try {{
          Object.assign = undefined;
          Object.keys = function () {{ throw new Error('Object.keys must not be called'); }};
          Array.prototype.forEach = function () {{ throw new Error('forEach must not be called'); }};

          sandbox.__setupFeatureFallbacks();

          const symbolKey = Symbol('hidden');
          const inheritedSource = Object.create({{ inherited: 'skip' }});
          inheritedSource.own = 'copy';
          inheritedSource.hasOwnProperty = function () {{ return false; }};
          Object.defineProperty(inheritedSource, 'nonEnumerable', {{
            value: 'skip',
            enumerable: false,
          }});
          inheritedSource[symbolKey] = 'skip';

          const nullProtoSource = Object.create(null);
          nullProtoSource.plain = 'ok';

          const target = {{ start: 'keep' }};
          const returned = Object.assign(target, inheritedSource, null, undefined, '', 'xy', nullProtoSource);

          process.stdout.write(JSON.stringify({{
            sameTarget: returned === target,
            target,
            ownKeys: originalKeys(target),
            hasOwnPropertyCopied:
              typeof target.hasOwnProperty === 'function' &&
              target.hasOwnProperty('anything') === false,
            hasInherited: Object.prototype.hasOwnProperty.call(target, 'inherited'),
            hasNonEnumerable: Object.prototype.hasOwnProperty.call(target, 'nonEnumerable'),
            hasSymbol: Object.prototype.hasOwnProperty.call(target, symbolKey),
            assignType: typeof Object.assign,
          }}));
        }} finally {{
          Object.assign = originalAssign;
          Object.keys = originalKeys;
          Array.prototype.forEach = originalForEach;
        }}
        """
    )

    assert _run_node(script) == {
        "sameTarget": True,
        "target": {
            "start": "keep",
            "own": "copy",
            "0": "x",
            "1": "y",
            "plain": "ok",
        },
        "ownKeys": ["0", "1", "start", "own", "hasOwnProperty", "plain"],
        "hasOwnPropertyCopied": True,
        "hasInherited": False,
        "hasNonEnumerable": False,
        "hasSymbol": False,
        "assignType": "function",
    }
