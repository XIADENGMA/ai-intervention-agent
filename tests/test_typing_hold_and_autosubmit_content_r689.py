"""R689 前端部分 — 输入保持倒计时 + 归零自动提交已输入内容（TODO#13）。

覆盖两端：

- web (``static/js/multi_task.js``)：源码契约 + node vm 运行时行为。
- 插件 (``packages/vscode/webview-ui.js``)：源码契约（webview 依赖
  acquireVsCodeApi / DOM 全家桶，运行时行为由 vscode-test 宿主覆盖）。

行为要求：

1. textarea input 事件刷新输入活跃时间戳；
2. 倒计时 tick 在剩余 ≤ 触发窗口且用户正在输入时调用 extend endpoint
   自动延长（受服务端 extends_max 配额约束）；
3. 倒计时归零时优先提交用户已输入文本 / 已勾选选项；无输入才回落到
   resubmit_prompt 原路径。
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

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _web_source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _vscode_source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


# ============================================================================
# Web：源码契约
# ============================================================================


class TestWebSourceContract(unittest.TestCase):
    def test_autosave_records_typing_timestamp(self) -> None:
        body = _extract_function_body(_web_source(), "handleRealtimeTextareaAutosave")
        self.assertIn(
            "lastFeedbackTypingAtMs",
            body,
            "R689: textarea input 自动保存路径必须刷新输入活跃时间戳",
        )

    def test_tick_invokes_typing_auto_extend(self) -> None:
        body = _extract_function_body(_web_source(), "tickTaskCountdown")
        self.assertIn(
            "maybeAutoExtendCountdownForTyping",
            body,
            "R689: 倒计时 tick 必须挂接 typing auto-extend",
        )

    def test_auto_submit_prefers_typed_content(self) -> None:
        body = _extract_function_body(_web_source(), "autoSubmitTask")
        self.assertIn(
            "collectTypedFeedbackForTask",
            body,
            "R689: 归零自动提交必须优先提交用户已输入内容",
        )
        self.assertIn(
            "collectSelectedOptionsForTask",
            body,
            "R689: 归零自动提交必须携带用户已勾选选项",
        )


# ============================================================================
# Web：node vm 运行时行为
# ============================================================================


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestWebRuntimeBehavior(unittest.TestCase):
    def test_auto_submit_sends_typed_content_not_resubmit_prompt(self) -> None:
        script = _poll_harness(
            """
            const submissions = [];
            submitTaskFeedback = async (taskId, text, options) => {
              submissions.push({ taskId, text, options });
            };
            let promptsFetched = 0;
            fetchFeedbackPromptsFresh = async () => {
              promptsFetched += 1;
              return { resubmit_prompt: 'RESUBMIT' };
            };
            document.getElementById = () => null;

            activeTaskId = 't-typed';
            taskTextareaContents['t-typed'] = 'user typed feedback';
            window.currentTasks = [
              { task_id: 't-typed', predefined_options: ['A', 'B'] },
            ];
            taskOptionsStates['t-typed'] = { 'option-1': true };

            await autoSubmitTask('t-typed');

            process.stdout.write(JSON.stringify({ submissions, promptsFetched }));
            """
        )
        result = json.loads(_run_node(script))

        self.assertEqual(len(result["submissions"]), 1)
        submission = result["submissions"][0]
        self.assertEqual(
            submission["text"],
            "user typed feedback",
            "归零自动提交必须发送用户输入的文本",
        )
        self.assertEqual(
            submission["options"],
            ["B"],
            "归零自动提交必须携带保存的已勾选选项（option-1 → 'B'）",
        )
        self.assertEqual(
            result["promptsFetched"],
            0,
            "有用户输入时不得回落到 resubmit_prompt 路径",
        )

    def test_auto_submit_falls_back_to_resubmit_prompt_when_empty(self) -> None:
        script = _poll_harness(
            """
            const submissions = [];
            submitTaskFeedback = async (taskId, text, options) => {
              submissions.push({ taskId, text, options });
            };
            fetchFeedbackPromptsFresh = async () => ({ resubmit_prompt: 'RESUBMIT' });
            document.getElementById = () => null;

            activeTaskId = 't-empty';
            window.currentTasks = [{ task_id: 't-empty' }];

            await autoSubmitTask('t-empty');

            process.stdout.write(JSON.stringify({ submissions }));
            """
        )
        result = json.loads(_run_node(script))

        self.assertEqual(len(result["submissions"]), 1)
        self.assertEqual(
            result["submissions"][0]["text"],
            "RESUBMIT",
            "无用户输入时必须保持原 resubmit_prompt 语义",
        )

    def test_typing_auto_extend_calls_extend_endpoint(self) -> None:
        script = _poll_harness(
            """
            const fetchCalls = [];
            fetch = (url, options) => {
              fetchCalls.push({ url, options });
              return Promise.resolve({
                ok: true,
                json: () =>
                  Promise.resolve({
                    success: true,
                    new_remaining_time: 70,
                    new_auto_resubmit_timeout: 300,
                    extends_used: 1,
                    extends_max: 3,
                  }),
              });
            };

            activeTaskId = 't-typing';
            window.currentTasks = [
              {
                task_id: 't-typing',
                auto_resubmit_timeout: 240,
                extends_used: 0,
                extends_max: 3,
              },
            ];
            window.lastFeedbackTypingAtMs = Date.now();

            maybeAutoExtendCountdownForTyping('t-typing', 10);
            // 沙箱的 setTimeout 是记录桩不会执行回调；fetch 桩链路全部是
            // microtask，flush 若干轮 Promise.resolve 即可等到 finally 完成。
            for (let i = 0; i < 10; i += 1) await Promise.resolve();

            const idleCallsBefore = fetchCalls.length;
            // 用户已停止输入（时间戳过期）→ 不得再触发 extend
            window.lastFeedbackTypingAtMs = Date.now() - 60 * 1000;
            maybeAutoExtendCountdownForTyping('t-typing', 10);
            for (let i = 0; i < 10; i += 1) await Promise.resolve();

            process.stdout.write(JSON.stringify({
              fetchCalls: fetchCalls.map(c => c.url),
              idleCallsBefore,
              totalCalls: fetchCalls.length,
            }));
            """
        )
        result = json.loads(_run_node(script))

        self.assertEqual(
            result["idleCallsBefore"], 1, "正在输入且剩余进入触发窗口 → 必须调用 extend"
        )
        self.assertIn("/api/tasks/t-typing/extend", result["fetchCalls"][0])
        self.assertEqual(
            result["totalCalls"],
            1,
            "用户停止输入后不得再触发 extend（typing-hold 只在输入活跃时生效）",
        )


# ============================================================================
# 插件：源码契约
# ============================================================================


class TestVscodeSourceContract(unittest.TestCase):
    def test_input_listener_records_typing_timestamp(self) -> None:
        source = _vscode_source()
        listener = re.search(
            r"textarea\.addEventListener\('input', \(\) => \{.*?\n        \}\)",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(listener, "未找到 textarea input 监听——测试需要更新")
        assert listener is not None
        self.assertIn(
            "lastFeedbackTypingAtMs",
            listener.group(0),
            "R689: 插件端 input 监听必须刷新输入活跃时间戳",
        )

    def test_countdown_tick_invokes_typing_auto_extend(self) -> None:
        source = _vscode_source()
        tick = re.search(r"function tick\(\) \{.*?\n    \}", source, re.DOTALL)
        self.assertIsNotNone(tick, "未找到倒计时 tick——测试需要更新")
        assert tick is not None
        self.assertIn(
            "maybeAutoExtendCountdownForTyping",
            tick.group(0),
            "R689: 插件端倒计时 tick 必须挂接 typing auto-extend",
        )

    def test_auto_submit_prefers_typed_content(self) -> None:
        source = _vscode_source()
        auto_submit = re.search(
            r"async function autoSubmit\(\) \{.*?\n  \}", source, re.DOTALL
        )
        self.assertIsNotNone(auto_submit, "未找到 autoSubmit——测试需要更新")
        assert auto_submit is not None
        body = auto_submit.group(0)
        self.assertIn(
            "collectTypedFeedbackForAutoSubmit",
            body,
            "R689: 插件端归零自动提交必须优先提交用户已输入内容",
        )
        self.assertIn(
            "collectSelectedOptionsForAutoSubmit",
            body,
            "R689: 插件端归零自动提交必须携带用户已勾选选项",
        )

    def test_auto_extend_helper_uses_server_extend_endpoint(self) -> None:
        source = _vscode_source()
        helper = re.search(
            r"function maybeAutoExtendCountdownForTyping\(.*?\n  \}",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(helper, "未找到插件端 auto-extend helper——测试需要更新")
        assert helper is not None
        self.assertIn(
            "/extend",
            helper.group(0),
            "R689: 插件端 typing-hold 必须复用服务端 extend endpoint（配额可见）",
        )


if __name__ == "__main__":
    unittest.main()
