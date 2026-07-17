"""R612 regression coverage for switchTask option-state loops."""

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


def test_switch_task_option_save_uses_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "switchTask")

    assert "checkboxes.forEach((checkbox, index)" not in body
    assert "const optionCheckboxCount = checkboxes.length;" in body
    assert "for (let index = 0; index < optionCheckboxCount; index += 1)" in body
    assert "if (!(index in checkboxes)) continue;" in body
    assert "const checkbox = checkboxes[index];" in body
    assert "optionsStates[index] = checkbox.checked;" in body
    assert "taskOptionsStates[activeTaskId] = optionsStates;" in body


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_switch_task_saves_options_without_nodelist_foreach() -> None:
    script = _poll_harness(
        """
        const textarea = { value: 'draft' };
        const checkboxList = {
          0: { checked: true },
          2: { checked: false },
          length: 3,
          forEach() {
            throw new Error('checkboxes.forEach must not be used');
          },
        };
        const optionsContainer = {
          querySelectorAll(selector) {
            if (selector !== 'input[type="checkbox"]') {
              throw new Error('unexpected selector: ' + selector);
            }
            return checkboxList;
          },
        };

        document.getElementById = function getElementById(id) {
          if (id === 'feedback-text') return textarea;
          if (id === 'options-container') return optionsContainer;
          return null;
        };
        window.currentTasks = [
          { task_id: 'old', status: 'pending' },
          { task_id: 'next', status: 'pending' },
        ];
        currentTasks = window.currentTasks;
        setActiveTaskId('old');

        await switchTask('next');

        process.stdout.write(JSON.stringify({
          activeTaskId,
          windowActiveTaskId: window.activeTaskId,
          oldDraft: taskTextareaContents.old,
          oldOptions: taskOptionsStates.old,
          oldOptionsLength: taskOptionsStates.old.length,
          oldOptionsOwnIndex1: Object.prototype.hasOwnProperty.call(
            taskOptionsStates.old,
            '1',
          ),
          oldImages: taskImages.old,
          checkboxOwnIndex1: Object.prototype.hasOwnProperty.call(checkboxList, '1'),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "activeTaskId": "next",
        "windowActiveTaskId": "next",
        "oldDraft": "draft",
        "oldOptions": [True, None, False],
        "oldOptionsLength": 3,
        "oldOptionsOwnIndex1": False,
        "oldImages": [],
        "checkboxOwnIndex1": False,
    }
