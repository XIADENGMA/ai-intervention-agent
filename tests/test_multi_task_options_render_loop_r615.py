"""R615 regression coverage for option render loops."""

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


def test_options_render_uses_sparse_safe_indexed_loop() -> None:
    body = _extract_function_body(_source(), "updateOptionsDisplay")

    assert "options.forEach((option, index)" not in body
    assert "const optionCount = options.length;" in body
    assert "for (let index = 0; index < optionCount; index += 1)" in body
    assert "if (!(index in options)) continue;" in body
    assert "const option = options[index];" in body
    assert "checkbox.id = `option-${index}`;" in body
    assert "const checkboxId = `option-${index}`;" in body
    assert "defaults[index] === true" in body


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_options_render_skips_sparse_slots_without_array_foreach() -> None:
    script = _poll_harness(
        """
        const operations = [];

        function classListFor(id) {
          return {
            add(cls) {
              operations.push([id, 'add', cls]);
            },
            remove(cls) {
              operations.push([id, 'remove', cls]);
            },
            toggle(cls, value) {
              operations.push([id, 'toggle', cls, value]);
            },
          };
        }

        function makeElement(tagName) {
          return {
            tagName: String(tagName).toUpperCase(),
            id: '',
            className: '',
            type: '',
            value: '',
            checked: false,
            htmlFor: '',
            textContent: '',
            children: [],
            classList: classListFor(tagName),
            appendChild(child) {
              this.children.push(child);
              return child;
            },
          };
        }

        const appendedOptions = [];
        const optionsContainer = {
          _innerHTML: 'stale',
          classList: classListFor('options-container'),
          set innerHTML(value) {
            operations.push(['options-container', 'innerHTML', value]);
            this._innerHTML = value;
          },
          get innerHTML() {
            return this._innerHTML;
          },
          appendChild(child) {
            const checkbox = child.children[0];
            const label = child.children[1];
            appendedOptions.push({
              className: child.className,
              checkboxId: checkbox.id,
              checkboxValue: checkbox.value,
              checked: checkbox.checked,
              labelFor: label.htmlFor,
              labelText: label.textContent,
            });
            operations.push(['options-container', 'append', checkbox.id]);
            return child;
          },
          querySelectorAll(selector) {
            operations.push(['options-container', 'queryAll', selector]);
            return {
              length: 0,
              forEach() {
                throw new Error('existing checkboxes should not be iterated here');
              },
            };
          },
        };
        const separator = {
          classList: classListFor('separator'),
        };

        document.createElement = function createElement(tagName) {
          operations.push(['create', tagName]);
          return makeElement(tagName);
        };
        document.getElementById = function getElementById(id) {
          if (id === 'options-container') return optionsContainer;
          if (id === 'separator') return separator;
          return null;
        };

        const options = [];
        options[0] = 'A';
        options[2] = 'C';
        options.length = 3;
        options.forEach = function forbiddenForEach() {
          throw new Error('options.forEach must not be used');
        };

        activeTaskId = null;
        taskOptionsStates = {};

        updateOptionsDisplay(options, [false, true, true]);

        process.stdout.write(JSON.stringify({
          appendedOptions,
          hasSparseHole: !(1 in options),
          operations,
        }));
        """
    )

    result = json.loads(_run_node(script))

    assert result["hasSparseHole"] is True
    assert result["appendedOptions"] == [
        {
            "className": "option-item",
            "checkboxId": "option-0",
            "checkboxValue": "A",
            "checked": False,
            "labelFor": "option-0",
            "labelText": "A",
        },
        {
            "className": "option-item",
            "checkboxId": "option-2",
            "checkboxValue": "C",
            "checked": True,
            "labelFor": "option-2",
            "labelText": "C",
        },
    ]
    assert ["options-container", "innerHTML", ""] in result["operations"]
    assert ["options-container", "remove", "hidden"] in result["operations"]
    assert ["options-container", "add", "visible"] in result["operations"]
    assert ["separator", "remove", "hidden"] in result["operations"]
    assert ["separator", "add", "visible"] in result["operations"]
