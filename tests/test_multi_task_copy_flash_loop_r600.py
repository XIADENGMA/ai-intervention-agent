"""R600 regression coverage for multi_task copy flash NodeList loops."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


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


def test_copy_flash_uses_indexed_nodelist_loop_without_foreach() -> None:
    body = _extract_function(_source(), "function _flashCopyOnSourceElement(")

    assert "elements.forEach" not in body
    assert "const elementCount = elements.length;" in body
    assert "for (let index = 0; index < elementCount; index += 1)" in body
    assert "const el = elements[index];" in body
    assert "if (!el) continue;" in body
    assert 'ok ? "copy-flash-ok" : "copy-flash-err"' in body
    assert "void el.offsetWidth;" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_copy_flash_resets_classes_and_cleans_up_without_nodelist_foreach() -> None:
    function_source = _extract_function(
        _source(),
        "function _flashCopyOnSourceElement(",
    )
    script = textwrap.dedent(
        f"""
        const vm = require('vm');

        const operations = [];
        const selectors = [];
        const timers = [];

        function makeClassList(name) {{
          return {{
            add(cls) {{
              operations.push([name, 'add', cls]);
            }},
            remove(...classes) {{
              operations.push([name, 'remove', classes]);
            }},
          }};
        }}

        function makeElement(name) {{
          return {{
            classList: makeClassList(name),
            get offsetWidth() {{
              operations.push([name, 'reflow']);
              return 1;
            }},
          }};
        }}

        const nodeA = makeElement('a');
        const nodeB = makeElement('b');
        const nodeList = {{
          0: nodeA,
          1: null,
          2: nodeB,
          length: 3,
          forEach() {{
            throw new Error('NodeList.forEach must not be used');
          }},
        }};

        const sandbox = {{
          CSS: {{
            escape(value) {{
              operations.push(['escape', value]);
              return `escaped-${{value}}`;
            }},
          }},
          String,
          document: {{
            querySelectorAll(selector) {{
              selectors.push(selector);
              return nodeList;
            }},
          }},
          setTimeout(fn, delay) {{
            timers.push({{ fn, delay }});
            return timers.length;
          }},
        }};
        vm.createContext(sandbox);
        vm.runInContext({json.dumps(function_source)}, sandbox);

        sandbox._flashCopyOnSourceElement('task/1', true);
        const beforeTimers = operations.slice();
        for (let index = 0; index < timers.length; index += 1) {{
          timers[index].fn();
        }}
        const afterOkTimers = operations.slice();

        timers.length = 0;
        sandbox._flashCopyOnSourceElement('', false);
        for (let index = 0; index < timers.length; index += 1) {{
          timers[index].fn();
        }}

        process.stdout.write(JSON.stringify({{
          selectors,
          timerDelays: timers.map((timer) => timer.delay),
          beforeTimers,
          afterOkTimers,
          allOperations: operations,
        }}));
        """
    )

    result = json.loads(_run_node(script))

    assert result["selectors"] == [
        '[data-copyable-task-id="escaped-task/1"]',
        '[data-copyable-task-id="escaped-"]',
    ]
    assert result["timerDelays"] == [600, 600]
    assert result["beforeTimers"] == [
        ["escape", "task/1"],
        ["a", "remove", ["copy-flash-ok", "copy-flash-err"]],
        ["a", "reflow"],
        ["a", "add", "copy-flash-ok"],
        ["b", "remove", ["copy-flash-ok", "copy-flash-err"]],
        ["b", "reflow"],
        ["b", "add", "copy-flash-ok"],
    ]
    assert result["afterOkTimers"] == [
        *result["beforeTimers"],
        ["a", "remove", ["copy-flash-ok"]],
        ["b", "remove", ["copy-flash-ok"]],
    ]
    assert result["allOperations"][-7:] == [
        ["a", "reflow"],
        ["a", "add", "copy-flash-err"],
        ["b", "remove", ["copy-flash-ok", "copy-flash-err"]],
        ["b", "reflow"],
        ["b", "add", "copy-flash-err"],
        ["a", "remove", ["copy-flash-err"]],
        ["b", "remove", ["copy-flash-err"]],
    ]
