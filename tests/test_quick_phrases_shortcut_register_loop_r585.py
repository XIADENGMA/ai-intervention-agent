"""R585 regression coverage for Quick Phrases shortcut registration loop."""

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


def _quick_phrases_shortcut_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');
        const storage = new Map();
        const registerCalls = [];
        const dispatchedEvents = [];
        const focused = [];

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
            selectionStart: 0,
            selectionEnd: 0,
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
            dispatchEvent(event) {{
              dispatchedEvents.push(event.type);
              const handler = this.__listeners[event.type];
              if (handler) handler(event);
              return true;
            }},
            focus() {{
              focused.push(this.id || this.className || this.tagName);
            }},
            setSelectionRange(start, end) {{
              this.selectionStart = start;
              this.selectionEnd = end;
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
          KeyboardShortcuts: {{
            register(name, handler, options) {{
              registerCalls.push({{ name, handler, options }});
            }},
          }},
          setTimeout(fn) {{ fn(); return 1; }},
          __dispatchedEvents: dispatchedEvents,
          __elements: elements,
          __focused: focused,
          __registerCalls: registerCalls,
          __storage: storage,
        }};
        sandbox.window = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        {case_js}
        """
    )


def test_setup_keyboard_shortcuts_uses_indexed_loop_without_foreach() -> None:
    body = _extract_function(_source(), "function setupKeyboardShortcuts(")

    assert "SHORTCUT_INDICES.forEach" not in body
    assert "for (var shortcutIdx = 0;" in body
    assert "shortcutIdx < SHORTCUT_INDICES.length" in body
    assert "let shortcutIndex = SHORTCUT_INDICES[shortcutIdx]" in body
    assert "SHORTCUT_PREFIX + String(shortcutIndex)" in body
    assert "_activateShortcut(shortcutIndex)" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_registered_shortcut_handlers_keep_per_index_scope_without_foreach() -> None:
    script = _quick_phrases_shortcut_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        const phrases = [];
        for (let i = 1; i <= 9; i += 1) {
          phrases.push({
            id: 'p' + i,
            label: 'Phrase ' + i,
            text: i === 1 ? 'One' : (i === 9 ? 'Nine' : 'Phrase' + i),
            created_at: 10 - i,
            last_used_at: 0,
            use_count: 0,
          });
        }
        sandbox.__storage.set(api.STORAGE_KEY, JSON.stringify({
          schema_version: api.SCHEMA_VERSION,
          phrases,
        }));

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {
          throw new Error('Array.prototype.forEach must not be used by setupKeyboardShortcuts');
        };
        try {
          api.setupKeyboardShortcuts();
          sandbox.__registerCalls[0].handler();
          sandbox.__registerCalls[8].handler();
        } finally {
          Array.prototype.forEach = originalForEach;
        }

        const stored = JSON.parse(sandbox.__storage.get(api.STORAGE_KEY));
        process.stdout.write(JSON.stringify({
          bound: api.isKeyboardShortcutsBound(),
          names: sandbox.__registerCalls.map((call) => call.name),
          options: sandbox.__registerCalls.map((call) => call.options),
          feedback: sandbox.__elements['feedback-text'].value,
          p1UseCount: stored.phrases.find((phrase) => phrase.id === 'p1').use_count,
          p9UseCount: stored.phrases.find((phrase) => phrase.id === 'p9').use_count,
          dispatchedEvents: sandbox.__dispatchedEvents,
          focused: sandbox.__focused,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "bound": True,
        "names": [f"alt+{i}" for i in range(1, 10)],
        "options": [
            {"preventDefault": True, "allowInInputs": True} for _ in range(1, 10)
        ],
        "feedback": "OneNine",
        "p1UseCount": 1,
        "p9UseCount": 1,
        "dispatchedEvents": ["input", "input"],
        "focused": ["feedback-text", "feedback-text"],
    }
