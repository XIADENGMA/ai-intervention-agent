"""R537 regression coverage for allocation-free task-local cache pruning."""

from __future__ import annotations

import json
import subprocess
import textwrap
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


def test_prune_task_local_state_walks_own_keys_without_key_arrays() -> None:
    body = _extract_function(_source(), "function pruneTaskLocalState(")

    assert "for (const taskId in source)" in body
    assert "Object.prototype.hasOwnProperty.call(source, taskId)" in body
    assert "for (const key in pendingImageUploadCounts)" in body
    assert "Object.prototype.hasOwnProperty.call(pendingImageUploadCounts, key)" in body
    assert "Object.keys(source || {}).forEach" not in body
    assert "Object.keys(pendingImageUploadCounts || {}).forEach" not in body


def test_prune_task_local_state_ignores_inherited_cache_keys() -> None:
    source = _source()
    parts = "\n\n".join(
        (
            _extract_function(source, "function getPendingImageUploadKey("),
            _extract_function(source, "function pruneTaskLocalState("),
        )
    )
    script = textwrap.dedent(
        f"""
        const cleared = [];
        const timerProto = {{ inheritedDone: 101 }};
        const pendingProto = {{ 'task:inheritedDone': 1 }};
        let tabCountdownTimers = Object.create(timerProto);
        tabCountdownTimers.ownDone = 202;
        let tabCountdownRemaining = Object.create({{ inheritedOnly: 3 }});
        let taskDeadlines = {{}};
        let taskTextareaContents = {{}};
        let taskOptionsStates = {{}};
        let taskImages = {{}};
        let pendingImageUploadCounts = Object.create(pendingProto);
        pendingImageUploadCounts['task:ownDone'] = 1;
        pendingImageUploadCounts.current = 1;

        function clearInterval(id) {{
          cleared.push(id);
        }}

        {parts}

        const removed = pruneTaskLocalState(new Set(['active']));

        process.stdout.write(JSON.stringify({{
          removed,
          cleared,
          timerOwnKeys: Object.keys(tabCountdownTimers),
          inheritedTimerStillReadable: tabCountdownTimers.inheritedDone,
          pendingOwnKeys: Object.keys(pendingImageUploadCounts),
          inheritedPendingStillReadable: pendingImageUploadCounts['task:inheritedDone'],
        }}));
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "removed": True,
        "cleared": [202],
        "timerOwnKeys": [],
        "inheritedTimerStillReadable": 101,
        "pendingOwnKeys": ["current"],
        "inheritedPendingStillReadable": 1,
    }
