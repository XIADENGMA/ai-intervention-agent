"""R583 regression coverage for Quick Phrases import merge indexed loops."""

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


def _quick_phrases_merge_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');
        const storage = new Map();

        function createElement(tagName, id) {{
          const element = {{
            id: id || '',
            tagName: String(tagName || 'div').toUpperCase(),
            attributes: {{}},
            children: [],
            dataset: {{}},
            className: '',
            textContent: '',
            type: '',
            value: '',
            disabled: false,
            __listeners: {{}},
            classList: {{
              add(name) {{
                element.className = (element.className ? element.className + ' ' : '') + name;
              }},
              contains(name) {{
                return element.className.split(/\\s+/).includes(name);
              }},
            }},
            appendChild(child) {{
              child.parentNode = this;
              this.children.push(child);
              return child;
            }},
            removeChild(child) {{
              const index = this.children.indexOf(child);
              if (index >= 0) this.children.splice(index, 1);
              child.parentNode = null;
              return child;
            }},
            setAttribute(name, value) {{
              this.attributes[name] = String(value);
              if (name.indexOf('data-') === 0) {{
                const key = name
                  .slice(5)
                  .replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
                this.dataset[key] = String(value);
              }}
            }},
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(this.attributes, name)
                ? this.attributes[name]
                : null;
            }},
            addEventListener(type, handler) {{
              this.__listeners[type] = handler;
            }},
            querySelector() {{ return null; }},
            get firstChild() {{ return this.children[0] || null; }},
          }};
          return element;
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
          Array,
          Date: {{ now: () => 1700000000000 }},
          Event: function Event(type) {{ this.type = type; }},
          JSON,
          Math,
          Number,
          Object,
          String,
          isFinite,
          console: {{ debug() {{}}, error() {{}}, info() {{}}, log() {{}}, warn() {{}} }},
          document: {{
            body: createElement('body', 'body'),
            readyState: 'loading',
            addEventListener() {{}},
            createElement(tagName) {{ return createElement(tagName); }},
            createEvent(type) {{
              return {{
                type,
                initEvent(name) {{ this.type = name; }},
              }};
            }},
            getElementById(id) {{ return elements[id] || null; }},
          }},
          localStorage: {{
            getItem(key) {{ return storage.has(key) ? storage.get(key) : null; }},
            setItem(key, value) {{ storage.set(key, String(value)); }},
            removeItem(key) {{ storage.delete(key); }},
          }},
          setTimeout(fn) {{ fn(); return 1; }},
          __elements: elements,
          __storage: storage,
        }};
        sandbox.window = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        {case_js}
        """
    )


def test_import_merge_uses_indexed_loops_without_foreach_callbacks() -> None:
    body = _extract_function(_source(), "function importPhrasesFromJson(")

    assert "existing.forEach" not in body
    assert "incoming.forEach" not in body
    assert "var existingCount = existing.length" in body
    assert "for (var existingIdx = 0; existingIdx < existingCount;" in body
    assert "if (!(existingIdx in existing)) continue" in body
    assert "var incomingCount = incoming.length" in body
    assert "for (var incomingIdx = 0; incomingIdx < incomingCount;" in body
    assert "if (!(incomingIdx in incoming)) continue" in body
    assert "skipped += 1;" in body
    assert "continue;" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_import_merge_preserves_duplicate_and_capacity_skips_without_foreach() -> None:
    script = _quick_phrases_merge_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        const existing = [];
        for (let i = 0; i < api.MAX_PHRASES - 1; i += 1) {
          existing.push({
            id: 'existing-' + i,
            label: i === 0 ? 'Duplicate' : 'Existing ' + i,
            text: i === 0 ? 'Same body' : 'Body ' + i,
            created_at: i,
            last_used_at: 0,
            use_count: 0,
          });
        }
        sandbox.__storage.set(api.STORAGE_KEY, JSON.stringify({
          schema_version: api.SCHEMA_VERSION,
          phrases: existing,
        }));

        const payload = JSON.stringify({
          signature: api.EXPORT_SIGNATURE,
          phrases: [
            { id: 'incoming-duplicate', label: 'Duplicate', text: 'Same body', created_at: 100 },
            { id: 'incoming-fill', label: 'Fill Slot', text: 'New body', created_at: 101 },
            { id: 'incoming-overflow', label: 'Overflow', text: 'Too late', created_at: 102 },
          ],
        });

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {
          throw new Error('Array.prototype.forEach must not be used by importPhrasesFromJson');
        };
        let result;
        try {
          result = api.importPhrasesFromJson(payload, 'merge');
        } finally {
          Array.prototype.forEach = originalForEach;
        }

        const stored = JSON.parse(sandbox.__storage.get(api.STORAGE_KEY));
        process.stdout.write(JSON.stringify({
          result,
          totalStored: stored.phrases.length,
          labels: stored.phrases.map((phrase) => phrase.label),
          addedPhrase: stored.phrases.find((phrase) => phrase.label === 'Fill Slot'),
          overflowPresent: stored.phrases.some((phrase) => phrase.label === 'Overflow'),
          renderedCount: sandbox.__elements['quick-phrases-list'].children.length,
        }));
        """
    )

    data = json.loads(_run_node(script))

    assert data["result"] == {
        "ok": True,
        "added": 1,
        "skipped": 2,
        "total": 20,
    }
    assert data["totalStored"] == 20
    assert data["labels"].count("Duplicate") == 1
    assert "Fill Slot" in data["labels"]
    assert data["addedPhrase"]["last_used_at"] == 0
    assert data["addedPhrase"]["use_count"] == 0
    assert data["overflowPresent"] is False
    assert data["renderedCount"] == 20
