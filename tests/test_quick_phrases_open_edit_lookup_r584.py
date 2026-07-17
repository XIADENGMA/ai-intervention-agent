"""R584 regression coverage for Quick Phrases edit lookup direct loop."""

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


def _quick_phrases_edit_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');
        const storage = new Map();
        const focused = [];

        function findDescendantByClass(root, className) {{
          const stack = root.children ? root.children.slice() : [];
          for (let i = 0; i < stack.length; i += 1) {{
            const node = stack[i];
            if (node.className === className) return node;
            const children = node.children || [];
            for (let childIdx = 0; childIdx < children.length; childIdx += 1) {{
              stack.push(children[childIdx]);
            }}
          }}
          return null;
        }}

        function findFirstInputOrTextarea(root) {{
          const stack = root.children ? root.children.slice() : [];
          for (let i = 0; i < stack.length; i += 1) {{
            const node = stack[i];
            if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') return node;
            const children = node.children || [];
            for (let childIdx = 0; childIdx < children.length; childIdx += 1) {{
              stack.push(children[childIdx]);
            }}
          }}
          return null;
        }}

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
            rows: 0,
            maxLength: 0,
            disabled: false,
            selectionStart: 0,
            selectionEnd: 0,
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
              for (let i = 0; i < this.children.length; i += 1) {{
                if (this.children[i] === child) {{
                  this.children.splice(i, 1);
                  child.parentNode = null;
                  return child;
                }}
              }}
              return child;
            }},
            setAttribute(name, value) {{
              this.attributes[name] = String(value);
            }},
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(this.attributes, name)
                ? this.attributes[name]
                : null;
            }},
            addEventListener(type, handler) {{
              this.__listeners[type] = handler;
            }},
            focus() {{
              focused.push(this.id || this.className || this.tagName);
            }},
            setSelectionRange(start, end) {{
              this.selectionStart = start;
              this.selectionEnd = end;
            }},
            querySelector(selector) {{
              if (selector === '.quick-phrases-form') {{
                return findDescendantByClass(this, 'quick-phrases-form');
              }}
              if (selector === 'input, textarea') {{
                return findFirstInputOrTextarea(this);
              }}
              return null;
            }},
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
          __focused: focused,
          __storage: storage,
        }};
        sandbox.window = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        {case_js}
        """
    )


def test_open_edit_form_uses_direct_loop_without_array_find() -> None:
    body = _extract_function(_source(), "function openEditForm(")

    assert ".find(" not in body
    assert "var phrases = loadPhrases()" in body
    assert "var phrase = null" in body
    assert "for (var i = 0; i < phrases.length;" in body
    assert "if (p.id === id)" in body
    assert "break;" in body
    assert '_openForm("edit", phrase)' in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_open_edit_form_preserves_first_match_without_array_find() -> None:
    script = _quick_phrases_edit_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        sandbox.__storage.set(api.STORAGE_KEY, JSON.stringify({
          schema_version: api.SCHEMA_VERSION,
          phrases: [
            { id: 'same', label: 'First label', text: 'First text', created_at: 1, last_used_at: 0, use_count: 0 },
            { id: 'other', label: 'Other label', text: 'Other text', created_at: 2, last_used_at: 0, use_count: 0 },
            { id: 'same', label: 'Second label', text: 'Second text', created_at: 3, last_used_at: 0, use_count: 0 },
          ],
        }));

        const originalFind = Array.prototype.find;
        Array.prototype.find = function disabledFind() {
          throw new Error('Array.prototype.find must not be used by openEditForm');
        };
        try {
          api.openEditForm('same');
        } finally {
          Array.prototype.find = originalFind;
        }

        const host = sandbox.__elements['quick-phrases-form-host'];
        const form = host.children[0];
        const labelInput = form.children[0];
        const textInput = form.children[1];
        api.closeAddForm();
        api.openEditForm('missing');

        process.stdout.write(JSON.stringify({
          formMode: form.dataset.qpMode,
          editId: form.dataset.qpEditId,
          labelValue: labelInput.value,
          textValue: textInput.value,
          textSelection: [textInput.selectionStart, textInput.selectionEnd],
          focused: sandbox.__focused,
          childrenAfterMissing: host.children.length,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "formMode": "edit",
        "editId": "same",
        "labelValue": "First label",
        "textValue": "First text",
        "textSelection": [10, 10],
        "focused": ["quick-phrases-form-label"],
        "childrenAfterMissing": 0,
    }
