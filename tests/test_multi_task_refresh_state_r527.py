"""R527 regression tests for one-pass task refresh state."""

from __future__ import annotations

import json
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


class TestTaskRefreshStateSourceR527(unittest.TestCase):
    def setUp(self) -> None:
        source = _read_source()
        self.helper_body = _extract_function_body(source, "_buildTaskRefreshState")
        self.update_body = _extract_function_body(source, "updateTasksList")

    def test_refresh_state_helper_is_single_pass_without_array_iterative_scans(
        self,
    ) -> None:
        self.assertEqual(self.helper_body.count("for (const task of tasks)"), 1)
        for forbidden in (".filter(", ".some(", ".find(", ".map("):
            self.assertNotIn(forbidden, self.helper_body)
        self.assertIn("completedTaskIds", self.helper_body)
        self.assertIn("serverActiveTask", self.helper_body)
        self.assertIn("preferredOpenTask", self.helper_body)
        self.assertIn("firstOpenTask", self.helper_body)

    def test_update_tasks_list_uses_refresh_state_not_repeated_readonly_scans(
        self,
    ) -> None:
        self.assertIn(
            "const taskRefreshState = _buildTaskRefreshState(tasks, activeTaskId)",
            self.update_body,
        )
        self.assertIn(
            "const completedTaskIds = taskRefreshState.completedTaskIds",
            self.update_body,
        )
        self.assertNotIn("taskRefreshState.completedTaskIds.forEach", self.update_body)
        self.assertIn("taskRefreshState.hasActiveTasks", self.update_body)
        self.assertIn("taskRefreshState.serverActiveTask", self.update_body)
        self.assertIn("taskRefreshState.nextActiveTaskId", self.update_body)
        self.assertIn("taskRefreshState.activeTaskForControls", self.update_body)
        self.assertNotIn(
            '.filter((task) => task && task.status === "completed")', self.update_body
        )
        self.assertNotIn('.some((t) => t.status !== "completed")', self.update_body)
        self.assertNotIn('tasks.find((t) => t.status === "active")', self.update_body)
        self.assertNotIn("pickOpenTaskId(", self.update_body)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestTaskRefreshStateRuntimeR527(unittest.TestCase):
    def test_refresh_state_preserves_server_active_priority_and_completed_cleanup(
        self,
    ) -> None:
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

            const state = context._buildTaskRefreshState(
              [
                {{ task_id: 'done-1', status: 'completed' }},
                {{ task_id: 'preferred', status: 'pending' }},
                {{ task_id: 'server', status: 'active' }},
                {{ task_id: 'done-2', status: 'completed' }},
              ],
              'preferred',
            );

            process.stdout.write(JSON.stringify({{
              completedTaskIds: state.completedTaskIds,
              hasActiveTasks: state.hasActiveTasks,
              serverActiveTaskId: state.serverActiveTask && state.serverActiveTask.task_id,
              nextActiveTaskId: state.nextActiveTaskId,
              activeTaskForControlsId:
                state.activeTaskForControls && state.activeTaskForControls.task_id,
            }}));
            """
        )

        result = _run_node(script)

        self.assertEqual(result["completedTaskIds"], ["done-1", "done-2"])
        self.assertTrue(result["hasActiveTasks"])
        self.assertEqual(result["serverActiveTaskId"], "server")
        self.assertEqual(result["nextActiveTaskId"], "server")
        self.assertEqual(result["activeTaskForControlsId"], "server")

    def test_refresh_state_falls_back_from_unidentified_server_active(self) -> None:
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

            const state = context._buildTaskRefreshState(
              [
                {{ task_id: null, status: 'active' }},
                {{ task_id: 'preferred', status: 'pending' }},
                {{ task_id: 'first-after-preferred', status: 'pending' }},
              ],
              'preferred',
            );

            process.stdout.write(JSON.stringify({{
              hasActiveTasks: state.hasActiveTasks,
              nextActiveTaskId: state.nextActiveTaskId,
              activeTaskForControlsId:
                state.activeTaskForControls && state.activeTaskForControls.task_id,
            }}));
            """
        )

        result = _run_node(script)

        self.assertTrue(result["hasActiveTasks"])
        self.assertEqual(result["nextActiveTaskId"], "preferred")
        self.assertEqual(result["activeTaskForControlsId"], "preferred")

    def test_refresh_state_all_completed_has_no_active_task(self) -> None:
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

            const state = context._buildTaskRefreshState(
              [
                {{ task_id: 'done-1', status: 'completed' }},
                {{ task_id: 'done-2', status: 'completed' }},
              ],
              'done-1',
            );

            process.stdout.write(JSON.stringify({{
              completedTaskIds: state.completedTaskIds,
              hasActiveTasks: state.hasActiveTasks,
              nextActiveTaskId: state.nextActiveTaskId,
              activeTaskForControls: state.activeTaskForControls,
            }}));
            """
        )

        result = _run_node(script)

        self.assertEqual(result["completedTaskIds"], ["done-1", "done-2"])
        self.assertFalse(result["hasActiveTasks"])
        self.assertIsNone(result["nextActiveTaskId"])
        self.assertIsNone(result["activeTaskForControls"])


if __name__ == "__main__":
    unittest.main()
