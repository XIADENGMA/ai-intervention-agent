"""R601 regression coverage for task-poll response task loops."""

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
    marker = f"async function {name}("
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


def test_poll_task_deadline_loop_uses_sparse_safe_indexed_scan() -> None:
    body = _extract_function_body(_source(), "fetchAndApplyTasks")

    assert "data.tasks.forEach" not in body
    assert "const taskCount = data.tasks.length;" in body
    assert "for (let index = 0; index < taskCount; index += 1)" in body
    assert "if (!(index in data.tasks)) continue;" in body
    assert "const task = data.tasks[index];" in body
    assert re.search(
        r"task\.auto_resubmit_timeout <= 0[\s\S]*?_clearTaskCountdown"
        r"\(task\.task_id\);[\s\S]*?delete window\.taskDeadlines"
        r"\[task\.task_id\];",
        body,
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_poll_task_deadline_loop_skips_sparse_slots_without_array_foreach() -> None:
    script = _poll_harness(
        """
        const updateTasksListCalls = [];
        const updateTasksStatsCalls = [];
        const clearedTaskIds = [];

        updateTasksList = function stubUpdateTasksList(tasksArg) {
          updateTasksListCalls.push(tasksArg);
        };
        updateTasksStats = function stubUpdateTasksStats(statsArg) {
          updateTasksStatsCalls.push(statsArg);
        };
        _clearTaskCountdown = function stubClearTaskCountdown(taskId) {
          clearedTaskIds.push(taskId);
          delete taskCountdowns[taskId];
        };

        taskCountdowns.a = { timeout: 1, remaining: 1 };
        taskCountdowns.b = { timeout: 2, remaining: 2 };
        taskCountdowns.c = { timeout: 3, remaining: 3 };

        const tasks = [
          {
            task_id: 'a',
            deadline: 100,
            status: 'pending',
            auto_resubmit_timeout: 50,
            remaining_time: 40,
          },
          { task_id: 'hole', deadline: 999 },
          {
            task_id: 'b',
            deadline: 200,
            status: 'pending',
            auto_resubmit_timeout: 0,
            remaining_time: 10,
          },
          {
            task_id: 'c',
            deadline: 300,
            status: 'completed',
            auto_resubmit_timeout: 60,
            remaining_time: 20,
          },
        ];
        delete tasks[1];

        const originalForEach = Array.prototype.forEach;
        Array.prototype.forEach = function disabledForEach() {
          throw new Error('Array.prototype.forEach must not be used here');
        };

        try {
          const pollPromise = fetchAndApplyTasks('r601');
          const timeoutId = __timeouts[0].id;
          __fetchRequests[0].resolve({
            ok: true,
            json: async () => ({
              success: true,
              server_time: Date.now() / 1000 + 5,
              tasks,
              stats: { pending: 3 },
            }),
          });
          const result = await pollPromise;
          await Promise.resolve();

          process.stdout.write(JSON.stringify({
            result,
            timeoutId,
            timeoutCleared: __timeouts[0].cleared,
            taskDeadlines: window.taskDeadlines,
            hasHoleDeadline: Object.prototype.hasOwnProperty.call(
              window.taskDeadlines,
              'hole',
            ),
            countdowns: taskCountdowns,
            clearedTaskIds,
            updateTasksListCallCount: updateTasksListCalls.length,
            updateTasksListGotOriginalTasks: updateTasksListCalls[0] === tasks,
            updateTasksStatsCallCount: updateTasksStatsCalls.length,
            updateTasksStatsValue: updateTasksStatsCalls[0],
          }));
        } finally {
          Array.prototype.forEach = originalForEach;
        }
        """
    )

    assert json.loads(_run_node(script)) == {
        "result": True,
        "timeoutId": "timeout-1",
        "timeoutCleared": True,
        "taskDeadlines": {"a": 100, "c": 300},
        "hasHoleDeadline": False,
        "countdowns": {
            "a": {"timeout": 50, "remaining": 40},
            "c": {"timeout": 3, "remaining": 3},
        },
        "clearedTaskIds": ["b"],
        "updateTasksListCallCount": 1,
        "updateTasksListGotOriginalTasks": True,
        "updateTasksStatsCallCount": 1,
        "updateTasksStatsValue": {"pending": 3},
    }
