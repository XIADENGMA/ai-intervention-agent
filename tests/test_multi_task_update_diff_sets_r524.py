"""R524 - Web task-list diff uses Set membership instead of nested includes."""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _read_source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _extract_function_body(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    assert start >= 0, f"missing function {name}"
    brace_open = source.find("{", start)
    assert brace_open >= 0, f"missing opening brace for {name}"

    depth = 0
    in_str: str | None = None
    in_template = False
    in_line_comment = False
    in_block_comment = False
    i = brace_open
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if in_template:
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                in_template = False
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace_open : i + 1]
        i += 1

    raise AssertionError(f"unterminated function {name}")


class TestMultiTaskUpdateDiffSourceR524(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _read_source()
        cls.diff_body = _extract_function_body(cls.source, "_buildTaskListDiff")
        cls.update_body = _extract_function_body(cls.source, "updateTasksList")

    def test_diff_helper_uses_set_membership(self) -> None:
        self.assertIn("const oldTaskIdSet = new Set()", self.diff_body)
        self.assertIn("const newTaskIdSet = new Set()", self.diff_body)
        self.assertIn("oldTaskIdSet.has(taskId)", self.diff_body)
        self.assertIn("newTaskIdSet.has(taskId)", self.diff_body)

    def test_update_tasks_list_no_longer_builds_parallel_id_arrays(self) -> None:
        forbidden = [
            "const oldTaskIds = currentTasks.map((t) => t.task_id)",
            "const newTaskIds = tasks.map((t) => t.task_id)",
            "newTaskIds.filter((id) => !oldTaskIds.includes(id))",
            "oldTaskIds.filter((id) => !newTaskIds.includes(id))",
            "tasks\n      .filter((t) => addedTasks.includes(t.task_id))",
        ]
        for snippet in forbidden:
            with self.subTest(snippet=snippet):
                self.assertNotIn(snippet, self.update_body)

        self.assertIn(
            "const taskDiff = _buildTaskListDiff(currentTasks, tasks)",
            self.update_body,
        )
        self.assertIn(
            "const addedTaskCount = taskDiff.addedTasks.length",
            self.update_body,
        )
        self.assertNotIn("taskDiff.addedTasks.forEach", self.update_body)
        self.assertIn("const removedTasks = taskDiff.removedTaskIds", self.update_body)

    def test_update_tasks_list_has_single_build_task_list_diff_call(self) -> None:
        self.assertEqual(
            len(re.findall(r"_buildTaskListDiff\(", self.update_body)),
            1,
        )


class TestMultiTaskUpdateDiffRuntimeR524(unittest.TestCase):
    def test_diff_helper_preserves_added_and_removed_order(self) -> None:
        node_code = textwrap.dedent(
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
            const result = context._buildTaskListDiff(
              [
                {{ task_id: 'old-1' }},
                {{ task_id: 'same' }},
                {{ task_id: 'old-2' }},
              ],
              [
                {{ task_id: 'new-1', status: 'pending' }},
                {{ task_id: 'same', status: 'active' }},
                {{ task_id: 'new-2', status: 'pending' }},
              ],
            );
            process.stdout.write(JSON.stringify({{
              addedTaskIds: result.addedTaskIds,
              addedTaskObjectIds: result.addedTasks.map((task) => task.task_id),
              removedTaskIds: result.removedTaskIds,
            }}));
            """
        )
        completed = subprocess.run(
            ["node", "-e", node_code],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["addedTaskIds"], ["new-1", "new-2"])
        self.assertEqual(payload["addedTaskObjectIds"], ["new-1", "new-2"])
        self.assertEqual(payload["removedTaskIds"], ["old-1", "old-2"])


if __name__ == "__main__":
    unittest.main()
