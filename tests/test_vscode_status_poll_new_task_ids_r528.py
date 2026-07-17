"""R528 regression coverage for VS Code status-poll new-task logging."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_TS = REPO_ROOT / "packages" / "vscode" / "extension.ts"


def _source() -> str:
    return EXTENSION_TS.read_text(encoding="utf-8")


def _extract_update_status_bar_body(source: str) -> str:
    match = re.search(
        r"const\s+updateStatusBar\s*=\s*async\s*\(\s*\)\s*:\s*Promise<[^>]+>\s*=>\s*\{",
        source,
    )
    assert match, "Cannot find updateStatusBar body"
    start = match.end()
    depth = 1
    i = start
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:i]
        i += 1
    raise AssertionError("Unbalanced updateStatusBar body")


def test_status_poll_builds_new_task_ids_during_detection() -> None:
    body = _extract_update_status_bar_body(_source())

    assert "const newTaskData: TaskData[] = [];" in body
    assert "const newTaskIds: string[] = [];" in body
    assert 'newTaskData.push({ id: taskId, prompt: String(t.prompt || "") });' in body
    assert "newTaskIds.push(taskId);" in body


def test_status_poll_reuses_new_task_ids_for_both_log_events() -> None:
    body = _extract_update_status_bar_body(_source())

    assert "{ ids: newTaskIds }" in body
    assert "{ ids: newTaskIds, viewVisible: false }" in body
    assert "newTaskData.map((t) => t.id)" not in body
    assert "newTaskData.map" not in body
