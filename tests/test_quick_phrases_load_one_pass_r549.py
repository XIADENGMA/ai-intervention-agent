"""R549 regression coverage for one-pass Quick Phrases loading."""

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


def _quick_phrases_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');
        const storage = new Map();
        function createElement(tagName, id) {{
          return {{
            id: id || '',
            tagName: String(tagName || 'div').toUpperCase(),
            children: [],
            dataset: {{}},
            classList: {{ add() {{}}, contains() {{ return false; }} }},
            appendChild(child) {{ this.children.push(child); return child; }},
            removeChild(child) {{
              this.children = this.children.filter((entry) => entry !== child);
              return child;
            }},
            setAttribute() {{}},
            addEventListener() {{}},
            querySelector() {{ return null; }},
            get firstChild() {{ return this.children[0] || null; }},
          }};
        }}
        const elements = {{
          'quick-phrases-container': createElement('div', 'quick-phrases-container'),
          'quick-phrases-list': createElement('div', 'quick-phrases-list'),
          'quick-phrases-form-host': createElement('div', 'quick-phrases-form-host'),
          'quick-phrases-add-btn': createElement('button', 'quick-phrases-add-btn'),
          'quick-phrases-export-btn': createElement('button', 'quick-phrases-export-btn'),
          'quick-phrases-import-btn': createElement('button', 'quick-phrases-import-btn'),
          'quick-phrases-import-file': createElement('input', 'quick-phrases-import-file'),
          'feedback-text': createElement('textarea', 'feedback-text'),
        }};
        const sandbox = {{
          Date: {{ now: () => 1700000000000 }},
          Event: function Event(type) {{ this.type = type; }},
          JSON,
          Math,
          Number,
          Object,
          String,
          console: {{ debug() {{}}, error() {{}}, info() {{}}, log() {{}}, warn() {{}} }},
          document: {{
            body: createElement('body', 'body'),
            readyState: 'loading',
            addEventListener() {{}},
            createElement(tagName) {{ return createElement(tagName); }},
            getElementById(id) {{ return elements[id] || null; }},
          }},
          localStorage: {{
            getItem(key) {{ return storage.has(key) ? storage.get(key) : null; }},
            setItem(key, value) {{ storage.set(key, String(value)); }},
            removeItem(key) {{ storage.delete(key); }},
          }},
          setTimeout(fn) {{ fn(); return 1; }},
          __storage: storage,
        }};
        sandbox.window = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        {case_js}
        """
    )


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_load_phrases_avoids_filter_map_intermediate_arrays() -> None:
    body = _extract_function(_source(), "function loadPhrases(")

    assert ".filter(function (p)" not in body
    assert ".map(function (p)" not in body
    assert "var result = []" in body
    assert "result.push({" in body
    assert "return result" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_load_phrases_filters_and_normalizes_in_order() -> None:
    script = _quick_phrases_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        sandbox.__storage.set(api.STORAGE_KEY, JSON.stringify({
          schema_version: api.SCHEMA_VERSION,
          phrases: [
            { id: 'a', label: 'A', text: 'Alpha', created_at: 5 },
            null,
            { id: 'bad-label', label: 1, text: 'skip' },
            {
              id: 'b',
              label: 'B',
              text: 'Beta',
              created_at: Infinity,
              last_used_at: NaN,
              use_count: 2,
              ignored: 'field',
            },
            { id: 'c', label: 'C', text: 'Gamma', created_at: 3, last_used_at: 4, use_count: 5 },
          ],
        }));
        process.stdout.write(JSON.stringify(api.loadPhrases()));
        """
    )

    assert json.loads(_run_node(script)) == [
        {
            "id": "a",
            "label": "A",
            "text": "Alpha",
            "created_at": 5,
            "last_used_at": 0,
            "use_count": 0,
        },
        {
            "id": "b",
            "label": "B",
            "text": "Beta",
            "created_at": 0,
            "last_used_at": 0,
            "use_count": 2,
        },
        {
            "id": "c",
            "label": "C",
            "text": "Gamma",
            "created_at": 3,
            "last_used_at": 4,
            "use_count": 5,
        },
    ]
