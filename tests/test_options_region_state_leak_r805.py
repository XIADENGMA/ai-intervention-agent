"""R805: the hairline that belongs to the options block must follow the block.

The Web UI keeps one page for every task. Between ``#content-container`` and
the textarea sit two elements that only make sense together:

* ``#options-container`` - the checkboxes of ``predefined_options``;
* ``#separator`` - the 0.5px rule with ``1.25rem`` margins above and below that
  divides the options from the text box.

Both start as ``class="hidden"`` in ``web_ui.html``.  ``updateOptionsDisplay``
(``multi_task.js``, the single source of truth for this region since R705)
shows them for a task that has options.  For a task *without* options it hid
only the container: ``#separator`` kept the ``visible`` class of the previous
task, so the same prompt looked different depending on what had been on the
page before - a stray hairline and 20.5 px of extra space above the text box
(real Chrome, same options-less task: the textarea started at y=315.5 after a
switch from a task with options and at y=295 on a fresh load).  A tab that
stays open for a whole working day goes through exactly this sequence every
time an agent asks a question with options and the next one without.

The contract tested here is "history independence" for the region: after any
sequence of calls, the separator is shown if and only if the options block is
shown, and a task without options leaves the region exactly as a fresh page
has it.  The Node tests drive the real ``updateOptionsDisplay`` against a DOM
whose ``hidden`` / ``visible`` classes are resolved the way ``main.css``
resolves them (anchored by the stylesheet tests below).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    _node_available,
    _poll_harness,
    _run_node,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "src" / "ai_intervention_agent"
MAIN_CSS = PACKAGE / "static" / "css" / "main.css"
TEMPLATE = PACKAGE / "templates" / "web_ui.html"


def _rule_declarations(css: str, selector: str) -> str:
    match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert match is not None, f"{selector} rule not found in main.css"
    return match.group(1)


class TestTheStateModelIsTheStylesheet:
    """The cascade model of the Node tests is only as good as these anchors."""

    def test_hidden_and_visible_are_equal_specificity_important_rules(self) -> None:
        css = MAIN_CSS.read_text(encoding="utf-8")
        hidden = _rule_declarations(css, ".hidden")
        visible = _rule_declarations(css, ".visible")
        assert re.search(r"display\s*:\s*none\s*!important", hidden)
        assert re.search(r"display\s*:\s*block\s*!important", visible)

    def test_visible_is_declared_after_hidden(self) -> None:
        # Both are single-class selectors and both are !important, so for an
        # element that carries both classes the later rule wins: ``visible``.
        css = MAIN_CSS.read_text(encoding="utf-8")
        hidden_at = re.search(r"(?m)^\.hidden\s*\{", css)
        visible_at = re.search(r"(?m)^\.visible\s*\{", css)
        assert hidden_at is not None and visible_at is not None
        assert hidden_at.start() < visible_at.start()

    def test_the_page_starts_with_both_elements_hidden(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        for element_id in ("options-container", "separator"):
            match = re.search(
                rf'<div\s+class="([^"]*)"\s+id="{element_id}"', template, re.S
            )
            assert match is not None, f"#{element_id} missing from web_ui.html"
            assert "hidden" in match.group(1).split(), (
                f"#{element_id} must start hidden: {match.group(1)!r}"
            )


_REGION_DOM = """
        // main.css: .hidden {display:none !important}; .visible {display:block
        // !important} comes later with the same specificity, so ``visible``
        // beats ``hidden`` on an element that carries both.
        function makeRegionElement(initialClasses) {
          const classes = new Set(initialClasses);
          return {
            classList: {
              add(name) { classes.add(name); },
              remove(name) { classes.delete(name); },
              contains(name) { return classes.has(name); },
              toggle(name, force) {
                const on = force === undefined ? !classes.has(name) : !!force;
                if (on) classes.add(name); else classes.delete(name);
                return on;
              },
            },
            get shown() { return classes.has('visible') || !classes.has('hidden'); },
            get classes() { return Array.from(classes).sort(); },
            children: [],
            set innerHTML(value) {
              if (value === '') this.children.length = 0;
            },
            get innerHTML() { return ''; },
            appendChild(child) { this.children.push(child); return child; },
            querySelectorAll() { return []; },
          };
        }

        const optionsContainer = makeRegionElement(['hidden']);
        const separator = makeRegionElement(['hidden']);
        document.getElementById = function getElementById(id) {
          if (id === 'options-container') return optionsContainer;
          if (id === 'separator') return separator;
          return null;
        };
        document.createElement = function createElement(tagName) {
          const element = makeRegionElement([]);
          element.tagName = String(tagName).toUpperCase();
          element.id = '';
          element.className = '';
          element.checked = false;
          element.value = '';
          return element;
        };
        activeTaskId = null;
        taskOptionsStates = {};

        const snapshot = (label) => ({
          label,
          options: optionsContainer.shown,
          separator: separator.shown,
          optionsClasses: optionsContainer.classes,
          separatorClasses: separator.classes,
          checkboxes: optionsContainer.children.length,
        });
"""


def _run_region(case_js: str) -> list[dict[str, object]]:
    script = _poll_harness(
        _REGION_DOM
        + case_js
        + "\n        process.stdout.write(JSON.stringify(steps));\n"
    )
    return json.loads(_run_node(script))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestTheSeparatorFollowsTheOptions(unittest.TestCase):
    def assertTogether(self, step: dict[str, object], shown: bool) -> None:
        self.assertEqual(
            (step["options"], step["separator"]),
            (shown, shown),
            f"options block and separator must be {'shown' if shown else 'hidden'} "
            f"together: {step}",
        )

    def test_a_plain_task_after_an_options_task_hides_the_separator(self) -> None:
        steps = _run_region(
            """
        const steps = [];
        updateOptionsDisplay(['alpha', 'beta'], [true, false]);
        steps.push(snapshot('options task'));
        updateOptionsDisplay([], []);
        steps.push(snapshot('plain task'));
        """
        )
        self.assertTogether(steps[0], True)
        self.assertEqual(steps[0]["checkboxes"], 2)
        self.assertTogether(steps[1], False)
        self.assertEqual(steps[1]["checkboxes"], 0)

    def test_the_plain_task_leaves_the_region_as_a_fresh_page_has_it(self) -> None:
        steps = _run_region(
            """
        const steps = [];
        steps.push(snapshot('fresh page'));
        updateOptionsDisplay(['alpha'], [false]);
        updateOptionsDisplay([], []);
        steps.push(snapshot('after options then plain'));
        """
        )
        fresh, later = steps
        self.assertEqual(later["options"], fresh["options"])
        self.assertEqual(later["separator"], fresh["separator"])

    def test_every_spelling_of_no_options_hides_the_whole_region(self) -> None:
        steps = _run_region(
            """
        const steps = [];
        for (const nothing of [[], null, undefined, '', 0, false]) {
          updateOptionsDisplay(['alpha', 'beta'], [false, false]);
          updateOptionsDisplay(nothing, []);
          steps.push(snapshot('after ' + JSON.stringify(nothing)));
        }
        """
        )
        self.assertEqual(len(steps), 6)
        for step in steps:
            self.assertTogether(step, False)

    def test_alternating_tasks_never_leave_the_two_out_of_step(self) -> None:
        steps = _run_region(
            """
        const steps = [];
        const sequence = [['a'], [], ['a', 'b', 'c'], [], [], ['x'], ['y', 'z'], []];
        sequence.forEach((options, index) => {
          updateOptionsDisplay(options, []);
          steps.push(Object.assign(snapshot('step ' + index), { expected: options.length > 0 }));
        });
        """
        )
        self.assertEqual(len(steps), 8)
        for step in steps:
            self.assertTogether(step, bool(step["expected"]))

    def test_options_after_a_plain_task_show_the_whole_region_again(self) -> None:
        steps = _run_region(
            """
        const steps = [];
        updateOptionsDisplay([], []);
        steps.push(snapshot('plain first'));
        updateOptionsDisplay(['alpha'], [true]);
        steps.push(snapshot('options second'));
        """
        )
        self.assertTogether(steps[0], False)
        self.assertTogether(steps[1], True)

    def test_a_missing_separator_element_does_not_break_the_options_block(
        self,
    ) -> None:
        steps = _run_region(
            """
        const steps = [];
        const original = document.getElementById;
        document.getElementById = (id) => (id === 'separator' ? null : original(id));
        updateOptionsDisplay(['alpha'], [false]);
        steps.push(snapshot('options without a separator element'));
        updateOptionsDisplay([], []);
        steps.push(snapshot('plain without a separator element'));
        """
        )
        self.assertEqual(steps[0]["options"], True)
        self.assertEqual(steps[1]["options"], False)
