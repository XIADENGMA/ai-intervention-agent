"""R611 regression coverage for existing active-tab sync loops."""

from __future__ import annotations

import json
import unittest

from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _node_available,
    _poll_harness,
    _run_node,
)
from tests.test_multi_task_tab_active_sync_loop_r610 import _extract_function_body


def _source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def test_existing_active_tabs_use_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "renderTaskTabs")

    assert "tabState.existingTabs.forEach" not in body
    assert "const syncedTabCount = tabState.existingTabs.length;" in body
    assert "for (let index = 0; index < syncedTabCount; index += 1)" in body
    assert "if (!(index in tabState.existingTabs)) continue;" in body
    assert "const tab = tabState.existingTabs[index];" in body
    assert 'tab.classList.toggle("active", isActive);' in body
    assert 'tab.setAttribute("aria-selected", isActive ? "true" : "false");' in body
    assert 'tab.setAttribute("tabindex", isActive ? "0" : "-1");' in body


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_existing_active_tabs_sync_without_nodelist_foreach() -> None:
    script = _poll_harness(
        """
        const operations = [];

        function makeTab(taskId) {
          return {
            dataset: { taskId },
            classList: {
              toggle(cls, value) {
                operations.push([taskId, 'toggle', cls, value]);
              },
            },
            setAttribute(attr, value) {
              operations.push([taskId, 'attr', attr, value]);
            },
          };
        }

        const existingTabs = {
          0: makeTab('first'),
          2: makeTab('third'),
          length: 3,
          forEach() {
            throw new Error('existingTabs.forEach must not be used');
          },
        };
        const tabsContainer = {
          querySelector() {
            return null;
          },
          querySelectorAll() {
            return existingTabs;
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
            incompleteTasks: [
              { task_id: 'first', status: 'pending' },
              { task_id: 'third', status: 'active' },
            ],
            existingTaskIds: ['first', 'third'],
            existingTabs,
            needsRebuild: false,
            removedIds: [],
            addedTasks: [],
          };
        };
        activeTaskId = 'third';
        window.activeTaskId = 'third';

        renderTaskTabs();

        process.stdout.write(JSON.stringify({
          operations,
          hasSparseSlot: Object.prototype.hasOwnProperty.call(existingTabs, '1'),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["hasSparseSlot"] is False
    assert ["container", "remove", "hidden"] in result["operations"]
    assert ["first", "toggle", "active", False] in result["operations"]
    assert ["first", "attr", "aria-selected", "false"] in result["operations"]
    assert ["first", "attr", "tabindex", "-1"] in result["operations"]
    assert ["third", "toggle", "active", True] in result["operations"]
    assert ["third", "attr", "aria-selected", "true"] in result["operations"]
    assert ["third", "attr", "tabindex", "0"] in result["operations"]
