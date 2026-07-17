"""R604 regression coverage for updateTasksList countdown fallback scan."""

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


def test_countdown_fallback_scan_uses_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "updateTasksList")

    assert "tasks.forEach((task)" not in body
    assert "const taskCount = tasks.length;" in body
    assert "for (let index = 0; index < taskCount; index += 1)" in body
    assert "if (!(index in tasks)) continue;" in body
    assert "const task = tasks[index];" in body
    assert 'if (task.status === "completed") continue;' in body
    assert re.search(
        r"if \(total <= 0\) \{[\s\S]*?_clearTaskCountdown\(task\.task_id\);"
        r"[\s\S]*?continue;",
        body,
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_countdown_fallback_scan_preserves_branches_without_instance_foreach() -> None:
    script = _poll_harness(
        """
        const tasks = [
          { task_id: 'completed', status: 'completed', auto_resubmit_timeout: 99 },
          { task_id: 'hole', status: 'pending', auto_resubmit_timeout: 99 },
          { task_id: 'disabled', status: 'pending', auto_resubmit_timeout: 0 },
          {
            task_id: 'active-overdue',
            status: 'active',
            auto_resubmit_timeout: 30,
            remaining_time: 0,
          },
          {
            task_id: 'pending-new',
            status: 'pending',
            auto_resubmit_timeout: 45,
            remaining_time: 12,
          },
          {
            task_id: 'pending-existing',
            status: 'pending',
            auto_resubmit_timeout: 60,
            remaining_time: 50,
          },
        ];
        delete tasks[1];
        tasks.forEach = function disabledTasksForEach() {
          throw new Error('tasks.forEach must not be used');
        };

        taskCountdowns.disabled = { timer: 'disabled-timer' };
        taskCountdowns['active-overdue'] = { timer: null };
        taskCountdowns['pending-existing'] = { timer: 'alive' };

        const clearedTaskIds = [];
        const autoSubmittedTaskIds = [];
        const startedCountdowns = [];

        clearTaskLocalState = function stubClearTaskLocalState() {};
        _clearTaskCountdown = function stubClearTaskCountdown(taskId) {
          clearedTaskIds.push(taskId);
          delete taskCountdowns[taskId];
        };
        autoSubmitTask = function stubAutoSubmitTask(taskId) {
          autoSubmittedTaskIds.push(taskId);
        };
        startTaskCountdown = function stubStartTaskCountdown(taskId, remaining, total) {
          startedCountdowns.push({ taskId, remaining, total });
          taskCountdowns[taskId] = { timer: 'started' };
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
            completedTaskIds: [],
            hasActiveTasks: true,
            serverActiveTask: null,
            nextActiveTaskId: null,
            activeTaskForControls: null,
          };
        };
        updateCountdownExtendButton = function stubExtendButton() {};
        updateFreezeCountdownButton = function stubFreezeButton() {};
        renderTaskTabs = function stubRenderTaskTabs() {};
        tryApplyDeepLinkedTask = function stubTryApplyDeepLinkedTask() {
          return false;
        };
        loadTaskDetails = function stubLoadTaskDetails() {};

        updateTasksList(tasks);

        process.stdout.write(JSON.stringify({
          clearedTaskIds,
          autoSubmittedTaskIds,
          startedCountdowns,
          hasDisabledCountdown: Object.prototype.hasOwnProperty.call(
            taskCountdowns,
            'disabled',
          ),
          pendingExistingCountdown: taskCountdowns['pending-existing'],
          currentTasksIsInput: currentTasks === tasks,
          hasSparseSlot: Object.prototype.hasOwnProperty.call(tasks, '1'),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "clearedTaskIds": ["disabled"],
        "autoSubmittedTaskIds": ["active-overdue"],
        "startedCountdowns": [
            {"taskId": "pending-new", "remaining": 12, "total": 45},
        ],
        "hasDisabledCountdown": False,
        "pendingExistingCountdown": {"timer": "alive"},
        "currentTasksIsInput": True,
        "hasSparseSlot": False,
    }
