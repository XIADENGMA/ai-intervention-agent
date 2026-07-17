"""R589 regression coverage for app strikethrough text-node processing."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


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


def test_process_strikethrough_uses_indexed_loop_without_foreach() -> None:
    body = _extract_function(_source(), "function processStrikethrough(")

    assert "textNodes.forEach" not in body
    assert "for (let textNodeIndex = 0;" in body
    assert "textNodeIndex < textNodes.length" in body
    assert "const textNode = textNodes[textNodeIndex]" in body
    assert "continue;" in body
    assert "document.createTreeWalker" in body
    assert "NodeFilter.SHOW_TEXT" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_process_strikethrough_preserves_dom_replacement_without_foreach() -> None:
    function_source = _extract_function(_source(), "function processStrikethrough(")
    script = textwrap.dedent(
        f"""
        const vm = require('vm');
        const replacements = [];
        const accepted = [];
        const rejected = [];

        function makeElement(tagName) {{
          return {{
            tagName,
            textContent: '',
            children: [],
            appendChild(child) {{
              this.children.push(child);
              return child;
            }},
          }};
        }}

        function makeParent(tagName, closestResult) {{
          return {{
            tagName,
            closest(selector) {{
              return selector === 'pre, code, script, style' ? closestResult : null;
            }},
            replaceChild(fragment, textNode) {{
              replacements.push({{
                oldText: textNode.textContent,
                children: fragment.children.map((child) => ({{
                  tagName: child.tagName || '#text',
                  textContent: child.textContent,
                }})),
              }});
            }},
          }};
        }}

        const normalParent = makeParent('P', null);
        const codeParent = makeParent('CODE', null);
        const nestedCodeParent = makeParent('SPAN', {{}});
        const nodes = [
          {{ textContent: 'plain text', parentElement: normalParent, parentNode: normalParent }},
          {{ textContent: 'A ~~deleted~~ B', parentElement: normalParent, parentNode: normalParent }},
          {{ textContent: 'skip ~~code~~', parentElement: codeParent, parentNode: codeParent }},
          {{
            textContent: 'skip ~~nested~~',
            parentElement: nestedCodeParent,
            parentNode: nestedCodeParent,
          }},
          {{
            textContent: 'X ~~one~~ Y ~~two~~ Z',
            parentElement: normalParent,
            parentNode: normalParent,
          }},
        ];

        const sandbox = {{
          Array,
          NodeFilter: {{
            SHOW_TEXT: 4,
            FILTER_ACCEPT: 1,
            FILTER_REJECT: 2,
          }},
          document: {{
            createDocumentFragment() {{ return makeElement('#fragment'); }},
            createElement(tagName) {{ return makeElement(tagName.toUpperCase()); }},
            createTextNode(text) {{
              return {{ tagName: '#text', textContent: text }};
            }},
            createTreeWalker(root, whatToShow, filter) {{
              let index = 0;
              return {{
                nextNode() {{
                  while (index < nodes.length) {{
                    const node = nodes[index];
                    index += 1;
                    if (filter.acceptNode(node) === 1) {{
                      accepted.push(node.textContent);
                      return node;
                    }}
                    rejected.push(node.textContent);
                  }}
                  return null;
                }},
              }};
            }},
          }},
        }};
        sandbox.window = sandbox;

        vm.createContext(sandbox);
        vm.runInContext({json.dumps(function_source)}, sandbox);

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {{
          throw new Error('Array.prototype.forEach must not be used');
        }};
        try {{
          sandbox.processStrikethrough({{}});
        }} finally {{
          Array.prototype.forEach = originalForEach;
        }}

        process.stdout.write(JSON.stringify({{ accepted, rejected, replacements }}));
        """
    )

    result = json.loads(_run_node(script))

    assert result["accepted"] == [
        "plain text",
        "A ~~deleted~~ B",
        "X ~~one~~ Y ~~two~~ Z",
    ]
    assert result["rejected"] == ["skip ~~code~~", "skip ~~nested~~"]
    assert result["replacements"] == [
        {
            "oldText": "A ~~deleted~~ B",
            "children": [
                {"tagName": "#text", "textContent": "A "},
                {"tagName": "DEL", "textContent": "deleted"},
                {"tagName": "#text", "textContent": " B"},
            ],
        },
        {
            "oldText": "X ~~one~~ Y ~~two~~ Z",
            "children": [
                {"tagName": "#text", "textContent": "X "},
                {"tagName": "DEL", "textContent": "one"},
                {"tagName": "#text", "textContent": " Y "},
                {"tagName": "DEL", "textContent": "two"},
                {"tagName": "#text", "textContent": " Z"},
            ],
        },
    ]
