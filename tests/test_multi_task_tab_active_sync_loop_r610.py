"""R610 regression coverage for rebuilt active-tab sync loops."""

from __future__ import annotations

import json
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


def test_rebuilt_active_tabs_use_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "renderTaskTabs")

    assert (
        'querySelectorAll(".task-tab:not(.task-tab-exit)")\n      .forEach' not in body
    )
    assert (
        "const activeTabs = tabsContainer.querySelectorAll(\n"
        '      ".task-tab:not(.task-tab-exit)",\n'
        "    );"
    ) in body
    assert "const activeTabCount = activeTabs.length;" in body
    assert "for (let index = 0; index < activeTabCount; index += 1)" in body
    assert "if (!(index in activeTabs)) continue;" in body
    assert "const tab = activeTabs[index];" in body
    assert 'tab.classList.toggle("active", isActive);' in body
    assert 'tab.setAttribute("aria-selected", isActive ? "true" : "false");' in body
    assert 'tab.setAttribute("tabindex", isActive ? "0" : "-1");' in body


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_rebuilt_active_tabs_sync_without_nodelist_foreach() -> None:
    script = _poll_harness(
        """
        const operations = [];
        const incompleteTasks = [
          { task_id: 'first', status: 'pending' },
          { task_id: 'third', status: 'active' },
        ];

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

        const appendedTabs = [];
        createTaskTab = function stubCreateTaskTab(task) {
          operations.push(['create', task.task_id]);
          return makeTab(task.task_id);
        };

        const tabsContainer = {
          _innerHTML: 'stale',
          set innerHTML(value) {
            operations.push(['innerHTML', value]);
            this._innerHTML = value;
          },
          get innerHTML() {
            return this._innerHTML;
          },
          appendChild(tab) {
            operations.push(['append', tab.dataset.taskId, tab.style.animationDelay]);
            appendedTabs.push(tab);
          },
          querySelectorAll(selector) {
            operations.push(['queryAll', selector]);
            return {
              0: appendedTabs[0],
              2: appendedTabs[1],
              length: 3,
              forEach() {
                throw new Error('activeTabs.forEach must not be used');
              },
            };
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
            incompleteTasks,
            existingTaskIds: [],
            existingTabs: [],
            needsRebuild: true,
            removedIds: [],
            addedTasks: [],
          };
        };
        activeTaskId = 'third';
        window.activeTaskId = 'third';

        renderTaskTabs();

        process.stdout.write(JSON.stringify({
          operations,
          appendedTaskIds: appendedTabs.map((tab) => tab.dataset.taskId),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["appendedTaskIds"] == ["first", "third"]
    assert ["queryAll", ".task-tab:not(.task-tab-exit)"] in result["operations"]
    assert ["first", "toggle", "active", False] in result["operations"]
    assert ["first", "attr", "aria-selected", "false"] in result["operations"]
    assert ["first", "attr", "tabindex", "-1"] in result["operations"]
    assert ["third", "toggle", "active", True] in result["operations"]
    assert ["third", "attr", "aria-selected", "true"] in result["operations"]
    assert ["third", "attr", "tabindex", "0"] in result["operations"]
