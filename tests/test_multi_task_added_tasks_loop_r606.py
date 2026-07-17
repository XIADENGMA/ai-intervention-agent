"""R606 regression coverage for added-task countdown bootstrap loops."""

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


def test_added_tasks_countdown_bootstrap_uses_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "updateTasksList")

    assert "taskDiff.addedTasks.forEach" not in body
    assert "const addedTaskCount = taskDiff.addedTasks.length;" in body
    assert "for (let index = 0; index < addedTaskCount; index += 1)" in body
    assert "if (!(index in taskDiff.addedTasks)) continue;" in body
    assert "const task = taskDiff.addedTasks[index];" in body
    assert re.search(
        r"const timeout = task\.remaining_time \?\? task\.auto_resubmit_timeout"
        r" \?\? 240;[\s\S]*?startTaskCountdown\("
        r"\s*task\.task_id,\s*timeout,\s*task\.auto_resubmit_timeout \|\| 240,",
        body,
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_added_tasks_countdown_bootstrap_skips_sparse_slots_without_foreach() -> None:
    script = _poll_harness(
        """
        const addedTasks = [
          {
            task_id: 'new-a',
            status: 'pending',
            remaining_time: 12,
            auto_resubmit_timeout: 45,
          },
          { task_id: 'hole', status: 'pending', auto_resubmit_timeout: 99 },
          {
            task_id: 'done',
            status: 'completed',
            remaining_time: 7,
            auto_resubmit_timeout: 30,
          },
          {
            task_id: 'existing',
            status: 'pending',
            remaining_time: 20,
            auto_resubmit_timeout: 60,
          },
          { task_id: 'fallback', status: 'pending' },
        ];
        delete addedTasks[1];
        addedTasks.forEach = function disabledAddedForEach() {
          throw new Error('addedTasks.forEach must not be used');
        };

        taskCountdowns.existing = { timer: 'alive' };

        const notifications = [];
        const startedCountdowns = [];
        showNewTaskNotification = function stubNewTaskNotification(count) {
          notifications.push(count);
        };
        startTaskCountdown = function stubStartTaskCountdown(taskId, remaining, total) {
          startedCountdowns.push({ taskId, remaining, total });
          taskCountdowns[taskId] = { timer: 'started' };
        };
        clearTaskLocalState = function stubClearTaskLocalState() {};
        _buildTaskListDiff = function stubBuildTaskListDiff() {
          return {
            addedTaskIds: ['new-a', 'done', 'existing', 'fallback'],
            addedTasks,
            removedTaskIds: [],
          };
        };
        _buildTaskRefreshState = function stubBuildTaskRefreshState() {
          return {
            completedTaskIds: [],
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
          notifications,
          startedCountdowns,
          existingCountdown: taskCountdowns.existing,
          hasDoneCountdown: Object.prototype.hasOwnProperty.call(
            taskCountdowns,
            'done',
          ),
          hasSparseSlot: Object.prototype.hasOwnProperty.call(addedTasks, '1'),
          currentTasks,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "notifications": [4],
        "startedCountdowns": [
            {"taskId": "new-a", "remaining": 12, "total": 45},
            {"taskId": "fallback", "remaining": 240, "total": 240},
        ],
        "existingCountdown": {"timer": "alive"},
        "hasDoneCountdown": False,
        "hasSparseSlot": False,
        "currentTasks": [],
    }
