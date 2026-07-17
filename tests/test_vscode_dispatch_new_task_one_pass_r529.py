"""R529 regression coverage for VS Code new-task notification dispatch."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"


def _source() -> str:
    return WEBVIEW_TS.read_text(encoding="utf-8")


def _extract_dispatch_new_task_notification_body(source: str) -> str:
    match = re.search(
        r"async\s+dispatchNewTaskNotification\s*"
        r"\(\s*taskData\s*:\s*TaskData\[\]\s*\)\s*:\s*Promise<[^>]+>\s*\{",
        source,
    )
    assert match, "Cannot find dispatchNewTaskNotification body"
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
    raise AssertionError("Unbalanced dispatchNewTaskNotification body")


def test_dispatch_new_task_collects_items_and_ids_in_one_pass() -> None:
    body = _extract_dispatch_new_task_notification_body(_source())

    assert "const items: TaskData[] = [];" in body
    assert "const ids: string[] = [];" in body
    assert "for (const item of taskData)" in body
    assert "items.push(item);" in body
    assert 'const taskId = item.id || "";' in body
    assert "ids.push(taskId);" in body


def test_dispatch_new_task_avoids_chained_filter_map_filter() -> None:
    body = _extract_dispatch_new_task_notification_body(_source())

    assert "taskData.filter(Boolean)" not in body
    assert "items.map(" not in body
    assert ".filter(Boolean)" not in body
    assert 'const firstPrompt = (items[0] && items[0].prompt) || "";' in body
