"""R452: VS Code webview task-local caches should prune by active task set."""

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


def test_prune_task_local_state_uses_all_task_local_cache_keys() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in ("getPendingImageUploadKey", "pruneTaskLocalState")
    )
    script = textwrap.dedent(
        f"""
        const cleared = [];
        let tabCountdownTimers = {{
          active: 101,
          done: 202,
        }};
        let tabCountdownRemaining = {{
          active: 10,
          noTimer: 20,
        }};
        let taskDeadlines = {{
          active: 111,
          orphan: 222,
        }};
        let taskTextareaContents = {{
          active: 'keep',
          noTimer: 'draft',
        }};
        let taskOptionsStates = {{
          active: {{ 0: true }},
          done: {{ 1: true }},
        }};
        let taskImages = {{
          active: [{{ name: 'keep.png', data: 'data:image/png;base64,AAEC' }}],
          noTimer: [{{ name: 'stale.png', data: 'data:image/png;base64,BBBB' }}],
        }};
        let pendingImageUploadCounts = {{
          'task:active': 1,
          'task:noTimer': 1,
          current: 1,
        }};

        function clearInterval(id) {{
          cleared.push(id);
        }}

        {parts}

        const removed = pruneTaskLocalState(new Set(['active']));

        process.stdout.write(JSON.stringify({{
          removed,
          cleared,
          tabCountdownTimers,
          tabCountdownRemaining,
          taskDeadlines,
          taskTextareaContents,
          taskOptionsStates,
          taskImages,
          pendingImageUploadCounts,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "removed": True,
        "cleared": [202],
        "tabCountdownTimers": {"active": 101},
        "tabCountdownRemaining": {"active": 10},
        "taskDeadlines": {"active": 111},
        "taskTextareaContents": {"active": "keep"},
        "taskOptionsStates": {"active": {"0": True}},
        "taskImages": {
            "active": [{"name": "keep.png", "data": "data:image/png;base64,AAEC"}]
        },
        "pendingImageUploadCounts": {"task:active": 1, "current": 1},
    }


def test_prune_task_local_state_returns_false_when_nothing_changed() -> None:
    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in ("getPendingImageUploadKey", "pruneTaskLocalState")
    )
    script = textwrap.dedent(
        f"""
        const cleared = [];
        let tabCountdownTimers = {{ active: 101 }};
        let tabCountdownRemaining = {{ active: 10 }};
        let taskDeadlines = {{ active: 111 }};
        let taskTextareaContents = {{ active: 'keep' }};
        let taskOptionsStates = {{ active: {{ 0: true }} }};
        let taskImages = {{
          active: [{{ name: 'keep.png', data: 'data:image/png;base64,AAEC' }}],
        }};
        let pendingImageUploadCounts = {{
          'task:active': 1,
          current: 1,
        }};

        function clearInterval(id) {{
          cleared.push(id);
        }}

        {parts}

        const removed = pruneTaskLocalState(new Set(['active']));

        process.stdout.write(JSON.stringify({{
          removed,
          cleared,
          tabCountdownTimers,
          tabCountdownRemaining,
          taskDeadlines,
          taskTextareaContents,
          taskOptionsStates,
          taskImages,
          pendingImageUploadCounts,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "removed": False,
        "cleared": [],
        "tabCountdownTimers": {"active": 101},
        "tabCountdownRemaining": {"active": 10},
        "taskDeadlines": {"active": 111},
        "taskTextareaContents": {"active": "keep"},
        "taskOptionsStates": {"active": {"0": True}},
        "taskImages": {
            "active": [{"name": "keep.png", "data": "data:image/png;base64,AAEC"}]
        },
        "pendingImageUploadCounts": {"task:active": 1, "current": 1},
    }
