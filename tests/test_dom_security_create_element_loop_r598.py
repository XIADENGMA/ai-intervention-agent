"""R598 regression coverage for DOMSecurity.createElement attribute loops."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOM_SECURITY_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "dom-security.js"
)


def _source() -> str:
    return DOM_SECURITY_JS.read_text(encoding="utf-8")


def _extract_method(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find method marker: {marker}"
    signature_end = source.find(")", start)
    assert signature_end != -1, f"Cannot find signature end for: {marker}"
    open_brace = source.find("{", signature_end)
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
    raise AssertionError(f"Unbalanced method body for: {marker}")


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


def test_create_element_attribute_loop_uses_indexed_entries_snapshot() -> None:
    body = _extract_method(_source(), "static createElement(")

    assert "Object.entries(attributes).forEach" not in body
    assert "const attributeEntries = Object.entries(attributes)" in body
    assert "const attributeEntryCount = attributeEntries.length" in body
    assert "for (let index = 0; index < attributeEntryCount; index += 1)" in body
    assert "if (!(index in attributeEntries)) continue" in body
    assert "const [key, value] = attributeEntries[index]" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_create_element_preserves_attribute_filtering_and_snapshot_without_foreach() -> (
    None
):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(DOM_SECURITY_JS)!r}, 'utf8');

        const createdElements = [];
        let currentAttributes = null;

        function makeElement(tagName) {{
          const calls = [];
          return {{
            tagName,
            calls,
            textContent: '',
            setAttribute(key, value) {{
              calls.push([key, value]);
              if (key === 'data-a' && currentAttributes) {{
                currentAttributes['data-b'] = 'mutated-during-setAttribute';
                currentAttributes['data-added'] = 'added-during-setAttribute';
              }}
            }},
          }};
        }}

        const sandbox = {{
          Array,
          Error,
          JSON,
          Number,
          Object,
          String,
          URL,
          console: {{
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            createElement(tagName) {{
              const element = makeElement(tagName);
              createdElements.push(element);
              return element;
            }},
          }},
          window: null,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        vm.runInContext(
          "Array.prototype.forEach = function disabledArrayForEach() " +
          "{{ throw new Error('Array.prototype.forEach must not be used'); }};",
          sandbox,
        );

        const inherited = {{ inherited: 'skip-me' }};
        const attributes = Object.create(inherited);
        Object.defineProperties(attributes, {{
          'data-a': {{ enumerable: true, value: 'a' }},
          'data-b': {{ enumerable: true, value: 'b', writable: true }},
          tabindex: {{ enumerable: true, value: 0 }},
          title: {{ enumerable: true, value: '<unsafe>' }},
          disabled: {{ enumerable: true, value: false }},
          onclick: {{ enumerable: true, value: function onclick() {{}} }},
          payload: {{ enumerable: true, value: {{ nested: true }} }},
          hiddenValue: {{ enumerable: false, value: 'hidden' }},
        }});
        currentAttributes = attributes;

        const element = sandbox.DOMSecurity.createElement(
          'button',
          '<script>alert(1)</script>',
          attributes,
        );

        process.stdout.write(JSON.stringify({{
          tagName: element.tagName,
          textContent: element.textContent,
          calls: element.calls,
          finalDataB: attributes['data-b'],
          hasAdded: Object.prototype.hasOwnProperty.call(attributes, 'data-added'),
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "tagName": "button",
        "textContent": "<script>alert(1)</script>",
        "calls": [
            ["data-a", "a"],
            ["data-b", "b"],
            ["tabindex", "0"],
            ["title", "<unsafe>"],
        ],
        "finalDataB": "mutated-during-setAttribute",
        "hasAdded": True,
    }
