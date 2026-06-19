"""R452: VS Code webview active task ids must be revalidated against live tasks."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _read_source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    if source[max(0, start - 6) : start] == "async ":
        start -= 6
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract {name}()")


def _run_node(script: str) -> str:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _active_task_helpers() -> str:
    source = _read_source()
    return "\n\n".join(
        _extract_function(source, name)
        for name in (
            "getTaskIdString",
            "getOpenTaskId",
            "pickOpenTaskId",
            "reconcileActiveTaskId",
            "pickFallbackTaskId",
        )
    )


def test_pick_fallback_task_id_ignores_completed_or_missing_active_id() -> None:
    script = textwrap.dedent(
        f"""
        let hasInitializedTaskIdTracking = true;
        let activeTaskId = 'done';
        let allTasks = [
          {{ task_id: 'done', status: 'completed' }},
          {{ task_id: 'server-active', status: 'active' }},
          {{ task_id: 'pending-a', status: 'pending' }},
        ];

        {_active_task_helpers()}

        const completedPreferred = pickFallbackTaskId();
        activeTaskId = 'missing';
        allTasks = [
          {{ task_id: 'done', status: 'completed' }},
          {{ task_id: 'pending-a', status: 'pending' }},
        ];
        const missingPreferred = pickFallbackTaskId();
        hasInitializedTaskIdTracking = false;
        activeTaskId = '';
        const uninitializedWithoutPreferred = pickFallbackTaskId();

        process.stdout.write(JSON.stringify({{
          completedPreferred,
          missingPreferred,
          uninitializedWithoutPreferred,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "completedPreferred": "server-active",
        "missingPreferred": "pending-a",
        "uninitializedWithoutPreferred": "pending-a",
    }


def test_reconcile_active_task_id_preserves_valid_local_open_selection() -> None:
    script = textwrap.dedent(
        f"""
        let hasInitializedTaskIdTracking = true;
        let activeTaskId = 'pending-a';
        let allTasks = [
          {{ task_id: 'server-active', status: 'active' }},
          {{ task_id: 'pending-a', status: 'pending' }},
        ];

        {_active_task_helpers()}

        const changed = reconcileActiveTaskId();

        process.stdout.write(JSON.stringify({{
          changed,
          activeTaskId,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "changed": False,
        "activeTaskId": "pending-a",
    }


def test_reconcile_active_task_id_clears_when_no_open_tasks_remain() -> None:
    script = textwrap.dedent(
        f"""
        let hasInitializedTaskIdTracking = true;
        let activeTaskId = 'done';
        let allTasks = [
          {{ task_id: 'done', status: 'completed' }},
        ];

        {_active_task_helpers()}

        const changed = reconcileActiveTaskId();

        process.stdout.write(JSON.stringify({{
          changed,
          activeTaskId,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "changed": True,
        "activeTaskId": None,
    }
