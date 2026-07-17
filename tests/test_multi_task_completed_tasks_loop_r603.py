"""R603 regression coverage for completed-task cleanup loops."""

from __future__ import annotations

import json
import re
import unittest

from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _node_available,
    _poll_harness,
    _run_node,
)


def _source() -> str:
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


def test_completed_tasks_cleanup_uses_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "updateTasksList")

    assert "taskRefreshState.completedTaskIds.forEach" not in body
    assert "const completedTaskIds = taskRefreshState.completedTaskIds;" in body
    assert "const completedTaskCount = completedTaskIds.length;" in body
    assert "for (let index = 0; index < completedTaskCount; index += 1)" in body
    assert "if (!(index in completedTaskIds)) continue;" in body
    assert "const taskId = completedTaskIds[index];" in body
    assert re.search(
        r"const taskId = completedTaskIds\[index\];\s+clearTaskLocalState\(taskId\);",
        body,
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_completed_tasks_cleanup_skips_sparse_slots_without_instance_foreach() -> None:
    script = _poll_harness(
        """
        const completedTaskIds = ['done-a', 'hole', 'done-b'];
        delete completedTaskIds[1];
        completedTaskIds.forEach = function disabledCompletedForEach() {
          throw new Error('completedTaskIds.forEach must not be used');
        };

        const clearedTaskIds = [];
        clearTaskLocalState = function stubClearTaskLocalState(taskId) {
          clearedTaskIds.push(taskId);
        };
        _buildTaskListDiff = function stubBuildTaskListDiff() {
          return {
            addedTaskIds: [],
            addedTasks: [],
            removedTaskIds: [],
          };
        };
        _buildTaskRefreshState = function stubBuildTaskRefreshState() {
          return {
            completedTaskIds,
            hasActiveTasks: false,
            serverActiveTask: null,
            nextActiveTaskId: null,
            activeTaskForControls: null,
          };
        };
        renderTaskTabs = function stubRenderTaskTabs() {};
        tryApplyDeepLinkedTask = function stubTryApplyDeepLinkedTask() {
          return false;
        };
        loadTaskDetails = function stubLoadTaskDetails() {};

        updateTasksList([]);

        process.stdout.write(JSON.stringify({
          clearedTaskIds,
          currentTasks,
          hasLoadedTaskSnapshot,
          completedTaskLength: completedTaskIds.length,
          hasSparseSlot: Object.prototype.hasOwnProperty.call(completedTaskIds, '1'),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "clearedTaskIds": ["done-a", "done-b"],
        "currentTasks": [],
        "hasLoadedTaskSnapshot": True,
        "completedTaskLength": 3,
        "hasSparseSlot": False,
    }
