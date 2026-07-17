"""R608 regression coverage for incremental added-tab loops."""

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


def test_incremental_added_tabs_use_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "renderTaskTabs")

    assert "tabState.addedTasks.forEach" not in body
    assert "const addedTabCount = tabState.addedTasks.length;" in body
    assert "for (let index = 0; index < addedTabCount; index += 1)" in body
    assert "if (!(index in tabState.addedTasks)) continue;" in body
    assert "const task = tabState.addedTasks[index];" in body
    assert re.search(
        r"const tab = createTaskTab\(task\);[\s\S]*?"
        r"tab\.classList\.add\(\"task-tab-enter\"\);[\s\S]*?"
        r"tabsContainer\.appendChild\(tab\);",
        body,
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_incremental_added_tabs_skip_sparse_slots_without_instance_foreach() -> None:
    script = _poll_harness(
        """
        const operations = [];
        const addedTasks = [
          { task_id: 'new-a', status: 'pending' },
          { task_id: 'hole', status: 'pending' },
        ];
        delete addedTasks[1];
        addedTasks.forEach = function disabledAddedTasksForEach() {
          throw new Error('addedTasks.forEach must not be used');
        };

        function makeTab(taskId) {
          return {
            dataset: { taskId },
            style: {},
            classList: {
              add(cls) {
                operations.push([taskId, 'add', cls]);
              },
              remove(cls) {
                operations.push([taskId, 'remove', cls]);
              },
              toggle(cls, value) {
                operations.push([taskId, 'toggle', cls, value]);
              },
            },
            addEventListener(type, handler, options) {
              operations.push([taskId, 'listener', type, Boolean(options && options.once)]);
              this.animationHandler = handler;
            },
            setAttribute(attr, value) {
              operations.push([taskId, 'attr', attr, value]);
            },
          };
        }

        let createdCount = 0;
        const appendedTabs = [];
        createTaskTab = function stubCreateTaskTab(task) {
          createdCount += 1;
          operations.push(['create', task.task_id]);
          return makeTab(task.task_id);
        };

        const tabsContainer = {
          innerHTML: '',
          appendChild(tab) {
            operations.push(['append', tab.dataset.taskId]);
            appendedTabs.push(tab);
          },
          querySelector() {
            return null;
          },
          querySelectorAll(selector) {
            operations.push(['queryAll', selector]);
            return appendedTabs;
          },
        };
        const container = {
          classList: {
            add(cls) {
              operations.push(['container', 'add', cls]);
            },
            remove(cls) {
              operations.push(['container', 'remove', cls]);
            },
          },
        };

        document.getElementById = function getElementById(id) {
          if (id === 'task-tabs') return tabsContainer;
          if (id === 'task-tabs-container') return container;
          return null;
        };
        _buildTaskTabRenderState = function stubBuildTaskTabRenderState() {
          return {
            incompleteTasks: [{ task_id: 'new-a', status: 'pending' }],
            existingTaskIds: ['old'],
            existingTabs: [],
            needsRebuild: true,
            removedIds: [],
            addedTasks,
          };
        };
        activeTaskId = 'new-a';
        window.activeTaskId = 'new-a';

        renderTaskTabs();
        appendedTabs[0].animationHandler();

        process.stdout.write(JSON.stringify({
          operations,
          createdCount,
          appendedTaskIds: appendedTabs.map((tab) => tab.dataset.taskId),
          hasSparseSlot: Object.prototype.hasOwnProperty.call(addedTasks, '1'),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["createdCount"] == 1
    assert result["appendedTaskIds"] == ["new-a"]
    assert result["hasSparseSlot"] is False
    assert ["create", "new-a"] in result["operations"]
    assert ["new-a", "add", "task-tab-enter"] in result["operations"]
    assert ["new-a", "listener", "animationend", True] in result["operations"]
    assert ["append", "new-a"] in result["operations"]
    assert ["new-a", "remove", "task-tab-enter"] in result["operations"]
    assert ["new-a", "toggle", "active", True] in result["operations"]
    assert ["new-a", "attr", "aria-selected", "true"] in result["operations"]
    assert ["new-a", "attr", "tabindex", "0"] in result["operations"]
