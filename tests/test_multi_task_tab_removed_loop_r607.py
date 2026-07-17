"""R607 regression coverage for incremental removed-tab loops."""

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


def test_incremental_removed_tabs_use_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "renderTaskTabs")

    assert "tabState.removedIds.forEach" not in body
    assert "const removedTabCount = tabState.removedIds.length;" in body
    assert "for (let index = 0; index < removedTabCount; index += 1)" in body
    assert "if (!(index in tabState.removedIds)) continue;" in body
    assert "const id = tabState.removedIds[index];" in body
    assert re.search(
        r"const el = tabsContainer\.querySelector"
        r"\(`\[data-task-id=\"\$\{id\}\"\]`\);[\s\S]*?"
        r"el\.classList\.add\(\"task-tab-exit\"\);",
        body,
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_incremental_removed_tabs_skip_sparse_slots_without_instance_foreach() -> None:
    script = _poll_harness(
        """
        const operations = [];
        const removedIds = ['old-a', 'hole'];
        delete removedIds[1];
        removedIds.forEach = function disabledRemovedIdsForEach() {
          throw new Error('removedIds.forEach must not be used');
        };

        function makeTab(name) {
          return {
            name,
            parentNode: { nodeType: 1 },
            dataset: { taskId: name },
            classList: {
              add(cls) {
                operations.push([name, 'add', cls]);
              },
              remove(cls) {
                operations.push([name, 'remove', cls]);
              },
              toggle(cls, value) {
                operations.push([name, 'toggle', cls, value]);
              },
            },
            addEventListener(type, handler, options) {
              operations.push([name, 'listener', type, Boolean(options && options.once)]);
              this.animationHandler = handler;
            },
            remove() {
              operations.push([name, 'remove-node']);
              this.parentNode = null;
            },
            setAttribute(attr, value) {
              operations.push([name, 'attr', attr, value]);
            },
          };
        }

        const oldA = makeTab('old-a');
        const active = makeTab('active');
        const tabsContainer = {
          innerHTML: '',
          appendChild() {},
          querySelector(selector) {
            operations.push(['query', selector]);
            if (selector === '[data-task-id=\"old-a\"]') return oldA;
            throw new Error('unexpected selector: ' + selector);
          },
          querySelectorAll(selector) {
            operations.push(['queryAll', selector]);
            return [active];
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
            incompleteTasks: [{ task_id: 'active', status: 'active' }],
            existingTaskIds: ['old-a', 'active'],
            existingTabs: [oldA, active],
            needsRebuild: true,
            removedIds,
            addedTasks: [],
          };
        };
        activeTaskId = 'active';
        window.activeTaskId = 'active';

        renderTaskTabs();
        __timeouts[0].fn();

        process.stdout.write(JSON.stringify({
          operations,
          oldAParentAfterTimeout: oldA.parentNode,
          hasSparseSlot: Object.prototype.hasOwnProperty.call(removedIds, '1'),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["oldAParentAfterTimeout"] is None
    assert result["hasSparseSlot"] is False
    assert ["query", '[data-task-id="old-a"]'] in result["operations"]
    assert ["old-a", "add", "task-tab-exit"] in result["operations"]
    assert ["old-a", "listener", "animationend", True] in result["operations"]
    assert ["old-a", "remove-node"] in result["operations"]
    assert ["active", "toggle", "active", True] in result["operations"]
    assert ["active", "attr", "aria-selected", "true"] in result["operations"]
    assert ["active", "attr", "tabindex", "0"] in result["operations"]
