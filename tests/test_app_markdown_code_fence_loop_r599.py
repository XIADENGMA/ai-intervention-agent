"""R599 regression coverage for app markdown code-fence run scanning."""

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


def test_build_markdown_code_fence_uses_indexed_backtick_run_loop() -> None:
    body = _extract_function(_source(), "function buildMarkdownCodeFence(")

    assert "backtickRuns.reduce" not in body
    assert "let longestRun = 0;" in body
    assert "const backtickRunCount = backtickRuns.length;" in body
    assert "for (let index = 0; index < backtickRunCount; index += 1)" in body
    assert "if (!(index in backtickRuns)) continue;" in body
    assert "const runLength = backtickRuns[index].length;" in body
    assert "if (runLength > longestRun) longestRun = runLength;" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_build_markdown_code_fence_preserves_output_without_array_reduce() -> None:
    function_source = _extract_function(_source(), "function buildMarkdownCodeFence(")
    script = textwrap.dedent(
        f"""
        const vm = require('vm');
        const sandbox = {{
          Math,
          String,
          JSON,
        }};
        vm.createContext(sandbox);
        vm.runInContext({json.dumps(function_source)}, sandbox);
        vm.runInContext(
          "Array.prototype.reduce = function disabledArrayReduce() " +
          "{{ throw new Error('Array.prototype.reduce must not be used'); }};",
          sandbox,
        );

        const outputs = [
          sandbox.buildMarkdownCodeFence('const a = 1;', 'js'),
          sandbox.buildMarkdownCodeFence('line with ``` fence'),
          sandbox.buildMarkdownCodeFence('alpha\\r\\nbeta\\r'),
          sandbox.buildMarkdownCodeFence('`````\\nbody'),
          sandbox.buildMarkdownCodeFence('   \\n\\t'),
        ];

        process.stdout.write(JSON.stringify(outputs));
        """
    )

    assert json.loads(_run_node(script)) == [
        "```js\nconst a = 1;\n```\n",
        "````\nline with ``` fence\n````\n",
        "```\nalpha\nbeta\n```\n",
        "``````\n`````\nbody\n``````\n",
        None,
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_build_markdown_code_fence_skips_sparse_match_holes_like_reduce() -> None:
    function_source = _extract_function(_source(), "function buildMarkdownCodeFence(")
    script = textwrap.dedent(
        f"""
        const vm = require('vm');
        const sandbox = {{
          Math,
          String,
          JSON,
        }};
        vm.createContext(sandbox);
        vm.runInContext({json.dumps(function_source)}, sandbox);

        vm.runInContext({
            json.dumps(
                '''
          const stringPrototype = Object.getPrototypeOf('sample');
          const originalMatch = stringPrototype.match;
          stringPrototype.match = function patchedMatch(regex) {
            if (String(regex) === '/`+/g') {
              const matches = ['`', 'hole', '````'];
              delete matches[1];
              return matches;
            }
            return originalMatch.call(this, regex);
          };
          Array.prototype.reduce = function disabledArrayReduce() {
            throw new Error('Array.prototype.reduce must not be used');
          };
        '''
            )
        }, sandbox);

        const output = sandbox.buildMarkdownCodeFence('synthetic match input');
        process.stdout.write(JSON.stringify(output));
        """
    )

    assert json.loads(_run_node(script)) == "`````\nsynthetic match input\n`````\n"
