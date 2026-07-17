"""R526 regression tests for task-tab render diff state."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _read_source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _extract_function_body(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    assert start >= 0, f"missing {name}"
    brace_open = source.find("{", start)
    assert brace_open >= 0, f"missing {name} body"
    depth = 0
    for idx in range(brace_open, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_open : idx + 1]
    raise AssertionError(f"unterminated {name} body")


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "node exited "
            f"{completed.returncode}\nstdout={completed.stdout!r}\n"
            f"stderr={completed.stderr!r}"
        )
    return json.loads(completed.stdout)


class TestTaskTabRenderStateSourceR526(unittest.TestCase):
    def setUp(self) -> None:
        source = _read_source()
        self.helper_body = _extract_function_body(source, "_buildTaskTabRenderState")
        self.render_body = _extract_function_body(source, "renderTaskTabs")

    def test_helper_uses_set_membership_not_nested_array_scans(self) -> None:
        self.assertIn("const incompleteTaskIdSet = new Set()", self.helper_body)
        self.assertIn("const existingTaskIdSet = new Set()", self.helper_body)
        self.assertIn("incompleteTaskIdSet.has(id)", self.helper_body)
        self.assertIn("existingTaskIdSet.has(task.task_id)", self.helper_body)
        for forbidden in (".includes(", ".find(", ".filter(", "Array.from("):
            self.assertNotIn(forbidden, self.helper_body)

    def test_render_task_tabs_consumes_precomputed_added_tasks(self) -> None:
        self.assertIn(
            "_buildTaskTabRenderState(currentTasks, tabsContainer)",
            self.render_body,
        )
        self.assertIn(
            "const addedTabCount = tabState.addedTasks.length",
            self.render_body,
        )
        self.assertNotIn("tabState.addedTasks.forEach", self.render_body)
        self.assertNotRegex(
            self.render_body,
            re.compile(r"addedIds\.forEach[\s\S]*?incompleteTasks\.find"),
        )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestTaskTabRenderStateRuntimeR526(unittest.TestCase):
    def test_render_state_preserves_order_and_skips_completed_tabs(self) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({json.dumps(str(MULTI_TASK_JS))}, 'utf8');
            const context = {{
              console: {{ log() {{}}, warn() {{}}, error() {{}}, debug() {{}} }},
              setTimeout() {{ return 1; }},
              clearTimeout() {{}},
              setInterval() {{ return 1; }},
              clearInterval() {{}},
              URL,
              URLSearchParams,
              Math,
              Date,
              window: {{
                location: {{ href: 'http://localhost/', search: '' }},
                addEventListener() {{}},
              }},
              document: {{
                addEventListener() {{}},
                getElementById() {{ return null; }},
                querySelectorAll() {{ return []; }},
                hidden: false,
                readyState: 'complete',
              }},
              navigator: {{}},
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            vm.runInContext(source, context, {{ filename: 'multi_task.js' }});

            let queryCount = 0;
            const tabsContainer = {{
              querySelectorAll(selector) {{
                queryCount += 1;
                if (selector !== '.task-tab:not(.task-tab-exit)') {{
                  throw new Error('unexpected selector: ' + selector);
                }}
                return [
                  {{ dataset: {{ taskId: 'old' }} }},
                  {{ dataset: {{ taskId: 'keep' }} }},
                ];
              }},
            }};
            const state = context._buildTaskTabRenderState(
              [
                {{ task_id: 'new-1', status: 'pending' }},
                {{ task_id: 'done', status: 'completed' }},
                {{ task_id: 'keep', status: 'active' }},
                {{ task_id: 'new-2', status: 'pending' }},
              ],
              tabsContainer,
            );

            process.stdout.write(JSON.stringify({{
              queryCount,
              incompleteTaskIds: state.incompleteTaskIds,
              existingTaskIds: state.existingTaskIds,
              needsRebuild: state.needsRebuild,
              removedIds: state.removedIds,
              addedTaskIds: state.addedTasks.map((task) => task.task_id),
            }}));
            """
        )

        result = _run_node(script)

        self.assertEqual(result["queryCount"], 1)
        self.assertEqual(result["incompleteTaskIds"], ["new-1", "keep", "new-2"])
        self.assertEqual(result["existingTaskIds"], ["old", "keep"])
        self.assertTrue(result["needsRebuild"])
        self.assertEqual(result["removedIds"], ["old"])
        self.assertEqual(result["addedTaskIds"], ["new-1", "new-2"])

    def test_render_state_keeps_no_open_task_path_dom_query_free(self) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({json.dumps(str(MULTI_TASK_JS))}, 'utf8');
            const context = {{
              console: {{ log() {{}}, warn() {{}}, error() {{}}, debug() {{}} }},
              setTimeout() {{ return 1; }},
              clearTimeout() {{}},
              setInterval() {{ return 1; }},
              clearInterval() {{}},
              URL,
              URLSearchParams,
              Math,
              Date,
              window: {{
                location: {{ href: 'http://localhost/', search: '' }},
                addEventListener() {{}},
              }},
              document: {{
                addEventListener() {{}},
                getElementById() {{ return null; }},
                querySelectorAll() {{ return []; }},
                hidden: false,
                readyState: 'complete',
              }},
              navigator: {{}},
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            vm.runInContext(source, context, {{ filename: 'multi_task.js' }});

            let queryCount = 0;
            const state = context._buildTaskTabRenderState(
              [
                {{ task_id: 'done-1', status: 'completed' }},
                {{ task_id: 'done-2', status: 'completed' }},
              ],
              {{
                querySelectorAll() {{
                  queryCount += 1;
                  return [];
                }},
              }},
            );

            process.stdout.write(JSON.stringify({{
              queryCount,
              incompleteLength: state.incompleteTasks.length,
              existingLength: state.existingTabs.length,
              needsRebuild: state.needsRebuild,
            }}));
            """
        )

        result = _run_node(script)

        self.assertEqual(result["queryCount"], 0)
        self.assertEqual(result["incompleteLength"], 0)
        self.assertEqual(result["existingLength"], 0)
        self.assertFalse(result["needsRebuild"])


if __name__ == "__main__":
    unittest.main()
