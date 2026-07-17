"""R530 regression coverage for browser-side new-task notification normalization."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
NOTIFY_CORE_JS = REPO_ROOT / "packages" / "vscode" / "webview-notify-core.js"


def _extract_function_body(source: str, marker: str) -> str:
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
                return source[open_brace + 1 : i]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def test_webview_ui_notify_new_tasks_normalizes_in_one_pass() -> None:
    body = _extract_function_body(
        WEBVIEW_UI_JS.read_text(encoding="utf-8"),
        "function notifyNewTasks(taskData)",
    )

    assert "const sourceItems = Array.isArray(taskData) ? taskData : [taskData]" in body
    assert "const normalized = []" in body
    assert "const ids = []" in body
    assert "for (const item of sourceItems)" in body
    assert "normalized.push(normalizedItem)" in body
    assert "const id = normalizedItem.id || normalizedItem" in body
    assert "preloaded.showNewTaskNotification(normalized)" in body
    assert "mod.showNewTaskNotification(normalized)" in body
    assert "taskData.filter(Boolean)" not in body
    assert ".filter(Boolean)" not in body
    assert ".map(" not in body


def test_notify_core_show_new_task_notification_normalizes_in_one_pass() -> None:
    body = _extract_function_body(
        NOTIFY_CORE_JS.read_text(encoding="utf-8"),
        "async function showNewTaskNotification(taskData)",
    )

    assert "var sourceItems = Array.isArray(taskData) ? taskData : [taskData]" in body
    assert "var normalized = []" in body
    assert "var ids = []" in body
    assert "for (var i = 0; i < sourceItems.length; i += 1)" in body
    assert "normalized.push(normalizedItem)" in body
    assert "var id = normalizedItem.id || ''" in body
    assert "var firstPrompt = (normalized[0] && normalized[0].prompt) || ''" in body
    assert "taskData.filter(Boolean)" not in body
    assert ".filter(Boolean)" not in body
    assert ".map(" not in body
