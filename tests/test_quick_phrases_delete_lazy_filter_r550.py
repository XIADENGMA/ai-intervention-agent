"""R550 regression coverage for lazy Quick Phrases deletion."""

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
        let setItemCount = 0;
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
            setItem(key, value) {{
              if (key === 'aiia.quickPhrases.v1') setItemCount += 1;
              storage.set(key, String(value));
            }},
            removeItem(key) {{ storage.delete(key); }},
          }},
          setTimeout(fn) {{ fn(); return 1; }},
          __storage: storage,
          __getSetItemCount() {{ return setItemCount; }},
          __resetSetItemCount() {{ setItemCount = 0; }},
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


def test_delete_phrase_uses_lazy_result_array() -> None:
    body = _extract_function(_source(), "function deletePhrase(")

    assert ".filter(function (p)" not in body
    assert "var filtered = null" in body
    assert "phrases.slice(0, i)" in body
    assert "filtered.push(p)" in body
    assert "if (filtered === null) return false" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_delete_phrase_missing_id_does_not_save_or_rewrite_storage() -> None:
    script = _quick_phrases_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        const seeded = JSON.stringify({
          schema_version: api.SCHEMA_VERSION,
          phrases: [
            { id: 'a', label: 'A', text: 'Alpha', created_at: 1, last_used_at: 0, use_count: 0 },
            { id: 'b', label: 'B', text: 'Beta', created_at: 2, last_used_at: 0, use_count: 0 },
          ],
        });
        sandbox.__storage.set(api.STORAGE_KEY, seeded);
        sandbox.__resetSetItemCount();
        const ok = api.deletePhrase('missing');
        process.stdout.write(JSON.stringify({
          ok,
          setItemCount: sandbox.__getSetItemCount(),
          stored: sandbox.__storage.get(api.STORAGE_KEY),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["ok"] is False
    assert result["setItemCount"] == 0
    assert json.loads(result["stored"]) == {
        "schema_version": 1,
        "phrases": [
            {
                "id": "a",
                "label": "A",
                "text": "Alpha",
                "created_at": 1,
                "last_used_at": 0,
                "use_count": 0,
            },
            {
                "id": "b",
                "label": "B",
                "text": "Beta",
                "created_at": 2,
                "last_used_at": 0,
                "use_count": 0,
            },
        ],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_delete_phrase_removes_all_duplicate_ids_and_keeps_order() -> None:
    script = _quick_phrases_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        sandbox.__storage.set(api.STORAGE_KEY, JSON.stringify({
          schema_version: api.SCHEMA_VERSION,
          phrases: [
            { id: 'same', label: 'First', text: 'Remove 1', created_at: 1 },
            { id: 'keep', label: 'Keep', text: 'Keep me', created_at: 2, last_used_at: 3, use_count: 4 },
            { id: 'same', label: 'Second', text: 'Remove 2', created_at: 5 },
          ],
        }));
        sandbox.__resetSetItemCount();
        const ok = api.deletePhrase('same');
        process.stdout.write(JSON.stringify({
          ok,
          setItemCount: sandbox.__getSetItemCount(),
          stored: JSON.parse(sandbox.__storage.get(api.STORAGE_KEY)),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["ok"] is True
    assert result["setItemCount"] == 1
    assert result["stored"] == {
        "schema_version": 1,
        "phrases": [
            {
                "id": "keep",
                "label": "Keep",
                "text": "Keep me",
                "created_at": 2,
                "last_used_at": 3,
                "use_count": 4,
            }
        ],
    }
