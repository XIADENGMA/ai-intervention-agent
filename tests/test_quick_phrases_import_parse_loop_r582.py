"""R582 regression coverage for Quick Phrases import parser indexed loop."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
QUICK_PHRASES_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "quick_phrases.js"
)


def _source() -> str:
    return QUICK_PHRASES_JS.read_text(encoding="utf-8")


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


def _quick_phrases_parser_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');

        const sandbox = {{
          Date: {{ now: () => 1700000000000 }},
          Event: function Event(type) {{ this.type = type; }},
          JSON: {{
            parse: JSON.parse,
            stringify: JSON.stringify,
          }},
          Math,
          Number,
          Object,
          String,
          console: {{ debug() {{}}, error() {{}}, info() {{}}, log() {{}}, warn() {{}} }},
          document: {{
            readyState: 'loading',
            addEventListener() {{}},
            createElement() {{ return {{}}; }},
            getElementById() {{ return null; }},
          }},
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
            removeItem() {{}},
          }},
          setTimeout(fn) {{ fn(); return 1; }},
        }};
        sandbox.window = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        {case_js}
        """
    )


def test_parse_import_payload_uses_indexed_loop_without_phrase_foreach() -> None:
    body = _extract_function(_source(), "function parseImportPayload(")

    assert "parsed.phrases.forEach" not in body
    assert "var phraseCount = parsed.phrases.length" in body
    assert "for (var idx = 0; idx < phraseCount;" in body
    assert "if (!(idx in parsed.phrases)) continue" in body
    assert "var p = parsed.phrases[idx]" in body
    assert 'typeof p.id !== "string" || !p.id) continue' in body
    assert "clean.push" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_parse_import_payload_skips_sparse_and_invalid_entries_without_foreach() -> (
    None
):
    script = _quick_phrases_parser_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        const sparse = [];
        sparse.length = 6;
        sparse[0] = { id: 'blank-label', label: '   ', text: 'skip me', created_at: 1 };
        sparse[2] = { id: 'valid-one', label: '  First  ', text: '  Alpha  ' };
        sparse[4] = { id: 'missing-text', label: 'No text' };
        sparse[5] = { id: 'valid-two', label: 'Second', text: 'Beta', created_at: 44 };

        sandbox.JSON.parse = function parseSparsePayload(rawText) {
          if (rawText !== 'payload') throw new Error('unexpected raw text');
          return {
            signature: api.EXPORT_SIGNATURE,
            phrases: sparse,
          };
        };

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {
          throw new Error('Array.prototype.forEach must not be used by parseImportPayload');
        };
        let result;
        try {
          result = api.parseImportPayload('payload');
        } finally {
          Array.prototype.forEach = originalForEach;
        }

        process.stdout.write(JSON.stringify(result));
        """
    )

    assert json.loads(_run_node(script)) == {
        "ok": True,
        "phrases": [
            {
                "id": "valid-one",
                "label": "First",
                "text": "Alpha",
                "created_at": 1700000000000,
            },
            {
                "id": "valid-two",
                "label": "Second",
                "text": "Beta",
                "created_at": 44,
            },
        ],
    }
