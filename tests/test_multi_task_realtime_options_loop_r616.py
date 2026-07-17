"""R616 regression coverage for realtime option autosave loops."""

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


def test_realtime_options_autosave_uses_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "handleRealtimeOptionsAutosave")

    assert "checkboxes.forEach((cb)" not in body
    assert "const checkboxCount = checkboxes.length;" in body
    assert "for (let index = 0; index < checkboxCount; index += 1)" in body
    assert "if (!(index in checkboxes)) continue;" in body
    assert "const checkbox = checkboxes[index];" in body
    assert "states[checkbox.id] = checkbox.checked;" in body
    assert "taskOptionsStates[activeTaskId] = states;" in body


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_realtime_options_autosave_preserves_state_without_nodelist_foreach() -> None:
    script = _poll_harness(
        """
        const operations = [];
        const checkboxList = {
          0: { id: 'option-0', checked: true },
          2: { id: 'option-2', checked: false },
          length: 3,
          forEach() {
            throw new Error('checkboxes.forEach must not be used');
          },
        };
        const optionsContainer = {
          querySelectorAll(selector) {
            operations.push(['queryAll', selector]);
            return checkboxList;
          },
        };

        activeTaskId = 'task-a';
        window.activeTaskId = 'task-a';
        taskOptionsStates = {};
        window.taskOptionsStates = taskOptionsStates;

        handleRealtimeOptionsAutosave({
          target: { type: 'checkbox' },
          currentTarget: optionsContainer,
        });

        process.stdout.write(JSON.stringify({
          operations,
          states: taskOptionsStates['task-a'],
          hasSparseHole: !(1 in checkboxList),
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "operations": [["queryAll", 'input[type="checkbox"]']],
        "states": {
            "option-0": True,
            "option-2": False,
        },
        "hasSparseHole": True,
    }
