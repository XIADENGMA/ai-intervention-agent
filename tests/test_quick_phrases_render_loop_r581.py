"""R581 regression coverage for Quick Phrases renderList indexed loop."""

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


def _quick_phrases_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');
        const storage = new Map();
        const confirmMessages = [];
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
              add(name) {{ element.className = (element.className ? element.className + ' ' : '') + name; }},
              contains(name) {{ return element.className.split(/\\s+/).includes(name); }},
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
            dispatchEvent(event) {{
              dispatchedEvents.push(event.type);
              const handler = this.__listeners[event.type];
              if (handler) handler(event);
            }},
            focus() {{ focused.push(this.id || this.tagName); }},
            setSelectionRange(start, end) {{
              this.selectionStart = start;
              this.selectionEnd = end;
            }},
            querySelector() {{ return null; }},
            get firstChild() {{ return this.children[0] || null; }},
          }};
          return element;
        }}

        function click(element) {{
          element.__listeners.click({{
            preventDefault() {{}},
            stopPropagation() {{}},
          }});
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
        elements['feedback-text'].value = '';

        const sandbox = {{
          Date: {{ now: () => 1700000000000 }},
          Event: function Event(type) {{ this.type = type; }},
          JSON,
          Math,
          Number,
          Object,
          String,
          console: {{ debug() {{}}, error() {{}}, info() {{}}, log() {{}}, warn() {{}} }},
          confirm(message) {{
            confirmMessages.push(message);
            return true;
          }},
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
          __click: click,
          __confirmMessages: confirmMessages,
          __dispatchedEvents: dispatchedEvents,
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


def test_render_list_uses_indexed_loop_without_phrase_foreach() -> None:
    body = _extract_function(_source(), "function renderList(")

    assert "phrases.forEach(function (p, idx)" not in body
    assert "var phraseCount =" in body
    assert "for (let idx = 0; idx < phraseCount;" in body
    assert "if (!(idx in phrases)) continue" in body
    assert "let p = phrases[idx]" in body
    assert "recordPhraseUsage(p.id)" in body
    assert "openEditForm(p.id)" in body
    assert "deletePhrase(p.id)" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_render_list_preserves_phrase_specific_click_handlers_without_foreach() -> None:
    script = _quick_phrases_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        sandbox.__storage.set(api.STORAGE_KEY, JSON.stringify({
          schema_version: api.SCHEMA_VERSION,
          phrases: [
            { id: 'first', label: 'First', text: 'Alpha', created_at: 1, last_used_at: 0, use_count: 0 },
            { id: 'second', label: 'Second', text: 'Beta', created_at: 2, last_used_at: 10, use_count: 2 },
          ],
        }));

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {
          throw new Error('Array.prototype.forEach must not be used by renderList');
        };
        try {
          api.renderList();
          const list = sandbox.__elements['quick-phrases-list'];
          const firstWrap = list.children[0];
          const secondWrap = list.children[1];
          sandbox.__click(firstWrap.children[0]);
          sandbox.__click(secondWrap.children[2]);
        } finally {
          Array.prototype.forEach = originalForEach;
        }

        const list = sandbox.__elements['quick-phrases-list'];
        const stored = JSON.parse(sandbox.__storage.get(api.STORAGE_KEY));
        process.stdout.write(JSON.stringify({
          initialLabels: ['Second', 'First'],
          firstChipText: list.children[0].children[0].textContent,
          feedbackText: sandbox.__elements['feedback-text'].value,
          confirmMessages: sandbox.__confirmMessages,
          remainingIds: stored.phrases.map((phrase) => phrase.id),
          secondUseCount: stored.phrases.find((phrase) => phrase.id === 'second').use_count,
          dispatchedEvents: sandbox.__dispatchedEvents,
          focused: sandbox.__focused,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "initialLabels": ["Second", "First"],
        "firstChipText": "Second",
        "feedbackText": "Beta",
        "confirmMessages": ["Delete 'First'?"],
        "remainingIds": ["second"],
        "secondUseCount": 3,
        "dispatchedEvents": ["input"],
        "focused": ["feedback-text"],
    }
