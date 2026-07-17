"""R532 regression coverage for task-tab snapshot active-id reconciliation."""

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


def test_render_task_tabs_reconciles_from_snapshot_state() -> None:
    source = _source()
    helper = _extract_function(source, "function buildTaskTabsRenderState(")
    reconcile = _extract_function(source, "function reconcileActiveTaskId(")
    render_body = _extract_function_body(source, "function renderTaskTabs()")

    assert "let serverActiveTaskId = ''" in helper
    assert "let firstOpenTaskId = ''" in helper
    assert "if (!firstOpenTaskId) firstOpenTaskId = taskId" in helper
    assert (
        "if (!serverActiveTaskId && task.status === 'active') serverActiveTaskId = taskId"
        in helper
    )
    assert "serverActiveTaskId," in helper
    assert "firstOpenTaskId" in helper

    assert "function reconcileActiveTaskId(taskTabsState)" in reconcile
    assert "taskTabsState.activeTaskIdSet.has(previous)" in reconcile
    assert (
        "taskTabsState.serverActiveTaskId || taskTabsState.firstOpenTaskId || ''"
        in reconcile
    )
    assert "const next = pickOpenTaskId(previous)" in reconcile
    assert "reconcileActiveTaskId(taskTabsState)" in render_body
    assert "pickOpenTaskId(" not in render_body


def test_snapshot_reconcile_preserves_priority_without_find_scans() -> None:
    source = _source()
    helper = _extract_function(source, "function buildTaskTabsRenderState(")
    reconcile = _extract_function(source, "function reconcileActiveTaskId(")
    script = f"""
function getTaskIdString(task) {{
  return task && task.task_id ? String(task.task_id) : ''
}}
function pickOpenTaskId() {{
  throw new Error('render snapshot reconcile should not call pickOpenTaskId')
}}
{helper}
{reconcile}
let activeTaskId = 'pending-a'
const tasks = [
  {{ task_id: 'server-active', status: 'active', prompt: '' }},
  {{ task_id: 'pending-a', status: 'pending', prompt: '' }}
]
const state = buildTaskTabsRenderState(tasks, new Set(), true)
const keepLocal = reconcileActiveTaskId(state)
const kept = activeTaskId
activeTaskId = 'missing'
const chooseServer = reconcileActiveTaskId(state)
const server = activeTaskId
const noServerState = buildTaskTabsRenderState([
  {{ task_id: 'done', status: 'completed', prompt: '' }},
  {{ task_id: 'pending-b', status: 'pending', prompt: '' }}
], new Set(), true)
activeTaskId = 'done'
const chooseFirstOpen = reconcileActiveTaskId(noServerState)
const firstOpen = activeTaskId
const emptyState = buildTaskTabsRenderState([
  {{ task_id: 'done', status: 'completed', prompt: '' }}
], new Set(), true)
activeTaskId = 'done'
const clearDone = reconcileActiveTaskId(emptyState)
const cleared = activeTaskId
console.log(JSON.stringify({{
  keepLocal,
  kept,
  chooseServer,
  server,
  chooseFirstOpen,
  firstOpen,
  clearDone,
  cleared
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
        "keepLocal": False,
        "kept": "pending-a",
        "chooseServer": True,
        "server": "server-active",
        "chooseFirstOpen": True,
        "firstOpen": "pending-b",
        "clearDone": True,
        "cleared": None,
    }
