"""R588 regression coverage for app code-block processing loops."""

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


def test_process_code_blocks_uses_indexed_loop_without_nodelist_foreach() -> None:
    body = _extract_function(_source(), "function processCodeBlocks(")

    assert "codeBlocks.forEach" not in body
    assert "for (let codeBlockIndex = 0;" in body
    assert "codeBlockIndex < codeBlockCount" in body
    assert "const pre = codeBlocks[codeBlockIndex]" in body
    assert "if (!pre) continue" in body
    assert "continue;" in body
    assert 'DOMSecurity.createCopyButton(pre.textContent || "")' in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_process_code_blocks_wraps_unprocessed_pres_without_nodelist_foreach() -> None:
    function_source = _extract_function(_source(), "function processCodeBlocks(")
    script = textwrap.dedent(
        f"""
        const vm = require('vm');
        const operations = [];

        function makeClassList(classes) {{
          const values = new Set(classes || []);
          return {{
            contains(name) {{ return values.has(name); }},
          }};
        }}

        function makeElement(tagName) {{
          const element = {{
            tagName: String(tagName).toUpperCase(),
            className: '',
            textContent: '',
            children: [],
            parentNode: null,
            parentElement: null,
            classList: makeClassList([]),
            appendChild(child) {{
              child.parentNode = this;
              child.parentElement = this;
              this.children.push(child);
              operations.push(['appendChild', this.className || this.tagName, child.className || child.tagName]);
              return child;
            }},
            querySelector() {{ return null; }},
          }};
          return element;
        }}

        const skippedPre = makeElement('pre');
        skippedPre.parentElement = {{ classList: makeClassList(['code-block-container']) }};
        skippedPre.parentNode = {{
          insertBefore() {{ throw new Error('already wrapped pre must not be moved'); }},
        }};

        const code = makeElement('code');
        code.className = 'language-js';
        const activePre = makeElement('pre');
        activePre.textContent = 'console.log(1);';
        activePre.querySelector = function querySelector(selector) {{
          return selector === 'code' ? code : null;
        }};
        const originalParent = {{
          classList: makeClassList([]),
          insertBefore(newNode, referenceNode) {{
            operations.push(['insertBefore', newNode.className, referenceNode === activePre]);
            newNode.parentNode = this;
            newNode.parentElement = this;
          }},
        }};
        activePre.parentNode = originalParent;
        activePre.parentElement = originalParent;

        const nodeList = {{
          0: skippedPre,
          1: activePre,
          length: 2,
          forEach() {{ throw new Error('NodeList.forEach must not be used'); }},
        }};
        const container = {{
          querySelectorAll(selector) {{
            operations.push(['querySelectorAll', selector]);
            return nodeList;
          }},
        }};
        const copyButtons = [];
        const sandbox = {{
          Number,
          document: {{
            createElement(tagName) {{
              return makeElement(tagName);
            }},
          }},
          DOMSecurity: {{
            createCopyButton(text) {{
              const button = makeElement('button');
              button.className = 'copy-code-btn';
              button.textContent = text;
              copyButtons.push(text);
              return button;
            }},
          }},
        }};

        vm.createContext(sandbox);
        vm.runInContext({json.dumps(function_source)}, sandbox);
        sandbox.processCodeBlocks(container);

        const codeContainer = activePre.parentElement;
        const toolbar = codeContainer.children[1];
        const langLabel = toolbar.children[0];
        const copyButton = toolbar.children[1];

        process.stdout.write(JSON.stringify({{
          operations,
          activeParentClass: codeContainer.className,
          activeParentChildTags: codeContainer.children.map((child) => child.tagName),
          toolbarClass: toolbar.className,
          langLabelClass: langLabel.className,
          langLabelText: langLabel.textContent,
          copyButtonClass: copyButton.className,
          copyButtons,
        }}));
        """
    )

    result = json.loads(_run_node(script))

    assert result["operations"][0] == ["querySelectorAll", "pre"]
    assert result["operations"][1] == ["insertBefore", "code-block-container", True]
    assert result["activeParentClass"] == "code-block-container"
    assert result["activeParentChildTags"] == ["PRE", "DIV"]
    assert result["toolbarClass"] == "code-toolbar"
    assert result["langLabelClass"] == "language-label"
    assert result["langLabelText"] == "JS"
    assert result["copyButtonClass"] == "copy-code-btn"
    assert result["copyButtons"] == ["console.log(1);"]
