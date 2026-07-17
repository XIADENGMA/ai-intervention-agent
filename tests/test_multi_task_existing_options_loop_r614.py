"""R614 regression coverage for existing option checkbox scans."""

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


def test_existing_option_scan_uses_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "updateOptionsDisplay")

    assert "existingCheckboxes.forEach((checkbox)" not in body
    assert "const existingCheckboxCount = existingCheckboxes.length;" in body
    assert "for (let index = 0; index < existingCheckboxCount; index += 1)" in body
    assert "if (!(index in existingCheckboxes)) continue;" in body
    assert "const checkbox = existingCheckboxes[index];" in body
    assert "selectedStates[checkbox.id] = checkbox.checked;" in body


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_existing_option_scan_preserves_dom_state_without_nodelist_foreach() -> None:
    script = _poll_harness(
        """
        const appended = [];
        const existingCheckboxes = {
          0: { id: 'option-0', checked: false },
          2: { id: 'option-2', checked: true },
          length: 3,
          forEach() {
            throw new Error('existingCheckboxes.forEach must not be used');
          },
        };
        const optionsContainer = {
          _innerHTML: 'stale',
          classList: {
            add(cls) {
              appended.push(['container-add', cls]);
            },
            remove(cls) {
              appended.push(['container-remove', cls]);
            },
          },
          set innerHTML(value) {
            appended.push(['innerHTML', value]);
            this._innerHTML = value;
          },
          get innerHTML() {
            return this._innerHTML;
          },
          querySelectorAll(selector) {
            if (selector !== 'input[type="checkbox"]') {
              throw new Error('unexpected selector: ' + selector);
            }
            return existingCheckboxes;
          },
          appendChild(child) {
            appended.push([
              'append',
              child.children[0].id,
              child.children[0].checked,
              child.children[1].textContent,
            ]);
          },
        };
        const separator = {
          classList: {
            add(cls) {
              appended.push(['separator-add', cls]);
            },
            remove(cls) {
              appended.push(['separator-remove', cls]);
            },
          },
        };

        document.getElementById = function getElementById(id) {
          if (id === 'options-container') return optionsContainer;
          if (id === 'separator') return separator;
          return null;
        };
        activeTaskId = 'task-a';
        window.activeTaskId = 'task-a';
        taskOptionsStates = {};
        window.taskOptionsStates = taskOptionsStates;

        updateOptionsDisplay(['A', 'B', 'C'], [true, true, true]);

        process.stdout.write(JSON.stringify({
          appended,
          hasSparseSlot: Object.prototype.hasOwnProperty.call(existingCheckboxes, '1'),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["hasSparseSlot"] is False
    assert ["innerHTML", ""] in result["appended"]
    assert ["append", "option-0", False, "A"] in result["appended"]
    assert ["append", "option-1", False, "B"] in result["appended"]
    assert ["append", "option-2", True, "C"] in result["appended"]
    assert ["container-remove", "hidden"] in result["appended"]
    assert ["container-add", "visible"] in result["appended"]
    assert ["separator-remove", "hidden"] in result["appended"]
    assert ["separator-add", "visible"] in result["appended"]
