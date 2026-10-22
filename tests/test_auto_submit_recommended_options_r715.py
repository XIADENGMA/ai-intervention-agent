"""R715 回归护栏：倒计时自动提交必须带上 AI 推荐的预勾选项（TODO 修复一）。

背景：

1. v1.8.10（``692170f``，移除 yesno 功能的提交）顺带引入了 ``taskUserOptionInteracted``
   守卫——自动提交只在「用户碰过选项」时才携带选项。AI 用 ``{"label", "default": true}``
   推荐的预勾选项在用户没点过的情况下被整个丢弃，AI 只收到 ``resubmit_prompt``。
   R689 的原始契约是「归零自动提交已输入文本 / 已勾选选项」。
2. Web 端 ``updateOptionsDisplay`` 把容器里任何已存在的复选框都当成「用户已操作过」，
   按序号继承——不管它们属于哪个任务。上一个任务提交后残留的（全未勾选的）DOM 会
   覆盖下一个任务的 AI 推荐，甚至把上一个任务的勾选泄漏进下一次提交。

契约：

- 自动提交 = 手动点「提交」此刻会发送的内容（输入的文本 + 当前勾选项，含预勾选的
  推荐项）；只有「没输入且一个选项都没勾」才回落到 ``resubmit_prompt``。
- 当前任务的选项在屏幕上（``#options-container`` 的 ``renderedTaskId`` 与任务一致）时，
  DOM 是唯一真源：用户取消全部勾选 → 空数组，不得回落到 AI 默认值。
- 选项不在屏幕上（后台任务 / 页面仍显示别的任务）时：任务保存的选择优先，其次 AI 推荐。
- 渲染选项时只有「同一个任务重渲染」才继承 DOM 的当前选择；换了任务必须从该任务自己的
  AI 推荐开始。
- ``taskUserOptionInteracted`` 已删除，两端都不得再出现。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _node_available,
    _poll_harness,
    _run_node,
)
from tests.test_multi_task_tab_active_sync_loop_r610 import _extract_function_body
from tests.test_vscode_task_local_cache_prune_r452 import _extract_function

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

WEB_PRELUDE = """
const submissions = [];
let promptsFetched = 0;
submitTaskFeedback = async (taskId, text, options) => {
  submissions.push({ taskId, text, options });
};
fetchFeedbackPromptsFresh = async () => {
  promptsFetched += 1;
  return { resubmit_prompt: 'RESUBMIT' };
};

function makeBoxes(spec) {
  return spec.map((entry, index) => ({
    id: 'option-' + index,
    value: entry[0],
    checked: entry[1],
  }));
}

function makeContainer(renderedTaskId, boxes) {
  const container = {
    dataset: renderedTaskId === null ? {} : { renderedTaskId },
    childNodes: { length: boxes.length },
    appended: [],
    classList: { add() {}, remove() {} },
    set innerHTML(value) {
      this._innerHTML = value;
    },
    get innerHTML() {
      return this._innerHTML || '';
    },
    appendChild(child) {
      this.appended.push([child.children[0].id, child.children[0].checked]);
    },
    querySelectorAll(selector) {
      if (selector !== 'input[type="checkbox"]') {
        throw new Error('unexpected selector: ' + selector);
      }
      return boxes;
    },
  };
  return container;
}

function mount(container, textarea) {
  document.getElementById = (id) => {
    if (id === 'options-container') return container;
    if (id === 'feedback-text') return textarea || null;
    return null;
  };
}
"""


def _run(case_js: str) -> dict:
    return json.loads(_run_node(_poll_harness(WEB_PRELUDE + case_js)))


def _web_source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _vscode_source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWebAutoSubmitOptions(unittest.TestCase):
    def test_untouched_ai_recommendation_is_auto_submitted(self) -> None:
        result = _run(
            """
            activeTaskId = 't1';
            window.currentTasks = [{
              task_id: 't1',
              predefined_options: ['A', 'B', 'C'],
              predefined_options_defaults: [false, true, false],
            }];
            mount(makeContainer('t1', makeBoxes([['A', false], ['B', true], ['C', false]])));
            await autoSubmitTask('t1');
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"], [{"taskId": "t1", "text": "", "options": ["B"]}]
        )
        self.assertEqual(result["promptsFetched"], 0)

    def test_unchecking_every_recommendation_falls_back_to_resubmit_prompt(
        self,
    ) -> None:
        result = _run(
            """
            activeTaskId = 't1';
            window.currentTasks = [{
              task_id: 't1',
              predefined_options: ['A', 'B', 'C'],
              predefined_options_defaults: [false, true, false],
            }];
            mount(makeContainer('t1', makeBoxes([['A', false], ['B', false], ['C', false]])));
            await autoSubmitTask('t1');
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"], [{"taskId": "t1", "text": "RESUBMIT", "options": []}]
        )
        self.assertEqual(result["promptsFetched"], 1)

    def test_typed_text_and_checked_options_are_sent_together(self) -> None:
        result = _run(
            """
            activeTaskId = 't1';
            window.currentTasks = [{
              task_id: 't1',
              predefined_options: ['A', 'B'],
              predefined_options_defaults: [false, true],
            }];
            mount(
              makeContainer('t1', makeBoxes([['A', false], ['B', true]])),
              { value: 'hello' },
            );
            await autoSubmitTask('t1');
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"],
            [{"taskId": "t1", "text": "hello", "options": ["B"]}],
        )
        self.assertEqual(result["promptsFetched"], 0)

    def test_checkboxes_rendered_for_another_task_are_not_trusted(self) -> None:
        result = _run(
            """
            activeTaskId = 'new';
            window.currentTasks = [{
              task_id: 'new',
              predefined_options: ['A', 'B'],
              predefined_options_defaults: [true, false],
            }];
            mount(makeContainer('old', makeBoxes([['A', false], ['B', true]])));
            await autoSubmitTask('new');
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"], [{"taskId": "new", "text": "", "options": ["A"]}]
        )

    def test_background_task_uses_saved_selection_then_ai_recommendation(self) -> None:
        result = _run(
            """
            activeTaskId = 'other';
            window.currentTasks = [
              { task_id: 'bg-saved', predefined_options: ['A', 'B'], predefined_options_defaults: [false, true] },
              { task_id: 'bg-fresh', predefined_options: ['A', 'B'], predefined_options_defaults: [false, true] },
            ];
            taskOptionsStates['bg-saved'] = { 'option-0': true, 'option-1': false };
            await autoSubmitTask('bg-saved');
            await autoSubmitTask('bg-fresh');
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"],
            [
                {"taskId": "bg-saved", "text": "", "options": ["A"]},
                {"taskId": "bg-fresh", "text": "", "options": ["B"]},
            ],
        )

    def test_saved_all_unchecked_selection_beats_ai_recommendation(self) -> None:
        result = _run(
            """
            activeTaskId = 'other';
            window.currentTasks = [
              { task_id: 'bg', predefined_options: ['A', 'B'], predefined_options_defaults: [false, true] },
            ];
            taskOptionsStates['bg'] = { 'option-0': false, 'option-1': false };
            await autoSubmitTask('bg');
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"], [{"taskId": "bg", "text": "RESUBMIT", "options": []}]
        )

    def test_task_without_options_still_falls_back_to_resubmit_prompt(self) -> None:
        result = _run(
            """
            activeTaskId = 'plain';
            window.currentTasks = [{ task_id: 'plain' }];
            mount(makeContainer('plain', []));
            await autoSubmitTask('plain');
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"],
            [{"taskId": "plain", "text": "RESUBMIT", "options": []}],
        )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWebOptionsRenderTaskIdentity(unittest.TestCase):
    def test_new_task_starts_from_its_own_recommendation(self) -> None:
        result = _run(
            """
            const container = makeContainer('old', makeBoxes([['A', false], ['B', true], ['C', false]]));
            mount(container);
            activeTaskId = 'new';
            taskOptionsStates = {};
            updateOptionsDisplay(['A', 'B', 'C'], [true, false, false]);
            process.stdout.write(JSON.stringify({
              appended: container.appended,
              renderedTaskId: container.dataset.renderedTaskId,
            }));
            """
        )
        self.assertEqual(
            result["appended"],
            [["option-0", True], ["option-1", False], ["option-2", False]],
        )
        self.assertEqual(result["renderedTaskId"], "new")

    def test_leftover_unchecked_checkboxes_do_not_wipe_the_next_recommendation(
        self,
    ) -> None:
        result = _run(
            """
            const container = makeContainer('old', makeBoxes([['A', false], ['B', false], ['C', false]]));
            mount(container);
            activeTaskId = 'new';
            taskOptionsStates = {};
            updateOptionsDisplay(['A', 'B', 'C'], [false, true, false]);
            process.stdout.write(JSON.stringify({ appended: container.appended }));
            """
        )
        self.assertEqual(
            result["appended"],
            [["option-0", False], ["option-1", True], ["option-2", False]],
        )

    def test_same_task_rerender_keeps_what_the_user_sees(self) -> None:
        result = _run(
            """
            const container = makeContainer('same', makeBoxes([['A', false], ['B', true], ['C', false]]));
            mount(container);
            activeTaskId = 'same';
            taskOptionsStates = {};
            updateOptionsDisplay(['A', 'B', 'C'], [true, false, false]);
            process.stdout.write(JSON.stringify({
              appended: container.appended,
              renderedTaskId: container.dataset.renderedTaskId,
            }));
            """
        )
        self.assertEqual(
            result["appended"],
            [["option-0", False], ["option-1", True], ["option-2", False]],
        )
        self.assertEqual(result["renderedTaskId"], "same")

    def test_saved_selection_still_wins_for_a_returning_task(self) -> None:
        result = _run(
            """
            const container = makeContainer('other', makeBoxes([['A', true], ['B', false], ['C', false]]));
            mount(container);
            activeTaskId = 'back';
            taskOptionsStates = { back: { 'option-2': true } };
            window.taskOptionsStates = taskOptionsStates;
            updateOptionsDisplay(['A', 'B', 'C'], [true, false, false]);
            process.stdout.write(JSON.stringify({ appended: container.appended }));
            """
        )
        self.assertEqual(
            result["appended"],
            [["option-0", False], ["option-1", False], ["option-2", True]],
        )

    def test_unknown_task_identity_never_inherits_leftover_checkboxes(self) -> None:
        result = _run(
            """
            const container = makeContainer(null, makeBoxes([['A', false], ['B', true]]));
            mount(container);
            activeTaskId = null;
            taskOptionsStates = {};
            updateOptionsDisplay(['A', 'B'], [true, false]);
            process.stdout.write(JSON.stringify({
              appended: container.appended,
              renderedTaskId: container.dataset.renderedTaskId,
            }));
            """
        )
        self.assertEqual(result["appended"], [["option-0", True], ["option-1", False]])
        self.assertEqual(result["renderedTaskId"], "")


class TestSourceContract(unittest.TestCase):
    def test_interaction_flag_is_gone_from_both_frontends(self) -> None:
        self.assertNotIn("taskUserOptionInteracted", _web_source())
        self.assertNotIn("taskUserOptionInteracted", _vscode_source())

    def test_web_auto_submit_has_no_interaction_guard(self) -> None:
        body = _extract_function_body(_web_source(), "autoSubmitTask")
        self.assertNotIn("nteract", body)
        self.assertIn("collectSelectedOptionsForTask(taskId)", body)

    def test_web_collect_trusts_dom_only_when_rendered_for_the_task(self) -> None:
        body = _extract_function_body(_web_source(), "collectSelectedOptionsForTask")
        self.assertIn("renderedTaskId", body)
        self.assertIn("predefined_options_defaults", body)

    def test_web_render_records_which_task_the_checkboxes_belong_to(self) -> None:
        body = _extract_function_body(_web_source(), "updateOptionsDisplay")
        self.assertIn("renderedTaskId", body)

    def test_vscode_auto_submit_has_no_interaction_guard(self) -> None:
        match = re.search(
            r"async function autoSubmit\(\) \{.*?\n  \}", _vscode_source(), re.DOTALL
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertNotIn("nteract", match.group(0))
        self.assertIn("collectSelectedOptionsForAutoSubmit()", match.group(0))


VSCODE_PRELUDE = """
const submissions = [];
let promptsFetched = 0;
let lastCountdownTaskId = 't1';
let activeTaskId = 't1';
let autoSubmitAttempted = {};
let submitInFlight = false;
let submitBackoffUntilMs = 0;
let taskTextareaContents = {};
let currentConfig = { task_id: 't1', predefined_options: ['A', 'B', 'C'] };
const boxes = {
  'option-0': { checked: false },
  'option-1': { checked: false },
  'option-2': { checked: false },
};
const textarea = { value: '' };
const document = {
  getElementById(id) {
    if (id === 'feedbackText') return textarea;
    return boxes[id] || null;
  },
};
const vscode = { postMessage() {} };
globalThis.setTimeout = () => 0;
function log() {}
function stopCountdown() {}
function requestImmediateRefresh() {}
async function submitWithData(text, options, taskId) {
  submissions.push({ text, options, taskId });
  return true;
}
async function fetchFeedbackPrompts() {
  promptsFetched += 1;
  return { resubmit_prompt: 'RESUBMIT' };
}
"""


def _run_vscode(case_js: str) -> dict:
    source = _vscode_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "collectTypedFeedbackForAutoSubmit",
            "collectSelectedOptionsForAutoSubmit",
            "autoSubmit",
        )
    )
    script = (
        "(async () => {\n"
        + VSCODE_PRELUDE
        + "\n"
        + parts
        + "\n"
        + case_js
        + "\n})().catch((err) => { console.error(err && err.stack ? err.stack : err); process.exit(1); });"
    )
    return json.loads(_run_node(script))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestVscodeAutoSubmitOptions(unittest.TestCase):
    def test_untouched_ai_recommendation_is_auto_submitted(self) -> None:
        result = _run_vscode(
            """
            boxes['option-1'].checked = true;
            await autoSubmit();
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"], [{"text": "", "options": ["B"], "taskId": "t1"}]
        )
        self.assertEqual(result["promptsFetched"], 0)

    def test_nothing_typed_and_nothing_checked_falls_back_to_resubmit_prompt(
        self,
    ) -> None:
        result = _run_vscode(
            """
            await autoSubmit();
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"],
            [{"text": "RESUBMIT", "options": [], "taskId": "t1"}],
        )
        self.assertEqual(result["promptsFetched"], 1)

    def test_typed_text_and_checked_options_are_sent_together(self) -> None:
        result = _run_vscode(
            """
            textarea.value = 'hello';
            boxes['option-1'].checked = true;
            await autoSubmit();
            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        self.assertEqual(
            result["submissions"],
            [{"text": "hello", "options": ["B"], "taskId": "t1"}],
        )
        self.assertEqual(result["promptsFetched"], 0)


if __name__ == "__main__":
    unittest.main()
