"""R533 regression coverage for task-tab countdown active-task refreshes."""

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


def test_same_hash_tab_refresh_passes_active_task_snapshot() -> None:
    source = _source()
    render_body = _extract_function_body(source, "function renderTaskTabs()")
    update_countdowns = _extract_function(source, "function updateTabCountdowns(")

    assert "updateTabCountdowns(taskTabsState.activeTasks)" in render_body
    assert "function updateTabCountdowns(tasks = allTasks)" in update_countdowns
    assert (
        "const tasksForCountdown = Array.isArray(tasks) ? tasks : allTasks"
        in update_countdowns
    )
    assert "tasksForCountdown.forEach(task => {" in update_countdowns
    assert "allTasks.forEach(" not in update_countdowns


def test_update_tab_countdowns_uses_explicit_active_tasks_and_preserves_fallback() -> (
    None
):
    update_countdowns = _extract_function(_source(), "function updateTabCountdowns(")
    script = f"""
let allTasks = [
  {{ task_id: 'active', status: 'active', auto_resubmit_timeout: 10 }},
  {{ task_id: 'completed', status: 'completed', auto_resubmit_timeout: 20 }}
]
let tabCountdownTimers = {{}}
const lookedUp = []
const started = []
const document = {{
  getElementById(id) {{
    lookedUp.push(id)
    return {{ id }}
  }}
}}
function startTabCountdown(taskId, timeout, remaining) {{
  started.push({{ taskId, timeout, remaining }})
}}
function computeRemainingForTask(task) {{
  return 'remaining:' + task.task_id
}}
{update_countdowns}
updateTabCountdowns([
  {{ task_id: 'active', status: 'active', auto_resubmit_timeout: 10 }}
])
const explicitLookedUp = lookedUp.slice()
const explicitStarted = started.slice()
lookedUp.length = 0
started.length = 0
updateTabCountdowns()
console.log(JSON.stringify({{
  explicitLookedUp,
  explicitStarted,
  fallbackLookedUp: lookedUp,
  fallbackStarted: started
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
        "explicitLookedUp": ["tab-countdown-progress-active"],
        "explicitStarted": [
            {"taskId": "active", "timeout": 10, "remaining": "remaining:active"}
        ],
        "fallbackLookedUp": [
            "tab-countdown-progress-active",
            "tab-countdown-progress-completed",
        ],
        "fallbackStarted": [
            {"taskId": "active", "timeout": 10, "remaining": "remaining:active"},
            {"taskId": "completed", "timeout": 20, "remaining": "remaining:completed"},
        ],
    }
