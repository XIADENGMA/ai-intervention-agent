"""R531 regression coverage for VS Code webview task-tab render state."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


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


def _extract_function_body(source: str, marker: str) -> str:
    function_source = _extract_function(source, marker)
    open_brace = function_source.find("{")
    return function_source[open_brace + 1 : -1]


def test_render_task_tabs_uses_single_snapshot_state_builder() -> None:
    source = _source()
    helper = _extract_function(source, "function buildTaskTabsRenderState(")
    render_body = _extract_function_body(source, "function renderTaskTabs()")

    assert helper.count("for (const task of tasks)") == 1
    assert "currentHash += task.task_id + ':' + task.status" in helper
    assert "currentTaskIds.add(task.task_id)" in helper
    assert "newTaskData.push({ id: task.task_id, prompt: task.prompt || '' })" in helper
    assert "activeTasks.push(task)" in helper
    assert "activeTaskIdSet.add(taskId)" in helper

    assert "buildTaskTabsRenderState(" in render_body
    assert "taskTabsState.newTaskData" in render_body
    assert "lastTaskIds = taskTabsState.currentTaskIds" in render_body
    assert "const activeTasks = taskTabsState.activeTasks" in render_body
    assert "const activeTaskIdSet = taskTabsState.activeTaskIdSet" in render_body
    assert "allTasks.map" not in render_body
    assert "allTasks.filter" not in render_body
    assert "activeTasks.map" not in render_body
    assert ".filter(Boolean)" not in render_body


def test_task_tabs_state_builder_preserves_hash_order_and_payloads() -> None:
    helper = _extract_function(_source(), "function buildTaskTabsRenderState(")
    script = f"""
function getTaskIdString(task) {{
  return task && task.task_id ? String(task.task_id) : ''
}}
{helper}
const tasks = [
  {{ task_id: 'a', status: 'pending', prompt: 'one' }},
  {{ task_id: 'b', status: 'completed', prompt: 'two' }},
  {{ task_id: 'c', status: 'active', prompt: '' }}
]
const collected = buildTaskTabsRenderState(tasks, new Set(['a']), true)
const skipped = buildTaskTabsRenderState(tasks, new Set(['a']), false)
console.log(JSON.stringify({{
  currentHash: collected.currentHash,
  currentTaskIds: Array.from(collected.currentTaskIds),
  newTaskData: collected.newTaskData,
  activeTaskIds: collected.activeTasks.map((task) => task.task_id),
  activeTaskIdSet: Array.from(collected.activeTaskIdSet),
  skippedNewTaskData: skipped.newTaskData
}}))
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload == {
        "currentHash": "a:pending|b:completed|c:active",
        "currentTaskIds": ["a", "b", "c"],
        "newTaskData": [{"id": "b", "prompt": "two"}, {"id": "c", "prompt": ""}],
        "activeTaskIds": ["a", "c"],
        "activeTaskIdSet": ["a", "c"],
        "skippedNewTaskData": [],
    }
