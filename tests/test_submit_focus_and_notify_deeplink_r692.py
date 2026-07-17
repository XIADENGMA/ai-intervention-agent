"""R692 — 提交后自动聚焦下一任务输入框 + 插件通知直达任务（TODO#6）。

两个流程级体验优化（用户选定的候选 1+2）：

1. **提交后自动聚焦**（web + 插件）：提交成功登记一个带时间戳的聚焦请求，
   下一个任务渲染完成时消费——连续回复多任务省掉一次鼠标点击。
   时间窗过期自动作废，避免焦点被"迟到的请求"抢走；yesno 模式（textarea
   隐藏）跳过。
2. **插件通知直达任务**：webview 隐藏期间派发新任务通知时记录首个
   task_id；用户点状态栏/通知回到面板（webview 变为可见）时，在 120s
   时间窗内向前端发送 ``switchToTask`` 消息直接切换到该任务。

本测试锁定两端源码契约（webview 运行时行为由 vscode-test 宿主覆盖；
web 端 node 行为由既有 harness 的 focus 桩能力限制，采用源码契约锁定）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_multi_task_poll_controller_lifecycle_r452 import MULTI_TASK_JS
from tests.test_multi_task_tab_active_sync_loop_r610 import _extract_function_body

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _web_source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


class TestWebSubmitFocus(unittest.TestCase):
    """web 端：提交成功 → 登记聚焦请求 → 任务详情渲染后消费。"""

    def test_focus_helpers_defined(self) -> None:
        source = _web_source()
        self.assertIn("function requestFeedbackInputFocus(", source)
        self.assertIn("function maybeApplyPendingInputFocus(", source)

    def test_submit_success_requests_focus(self) -> None:
        body = _extract_function_body(_web_source(), "submitTaskFeedback")
        self.assertIn(
            "requestFeedbackInputFocus()",
            body,
            "R692: 提交成功路径必须登记聚焦请求",
        )

    def test_close_task_switch_requests_focus(self) -> None:
        body = _extract_function_body(_web_source(), "closeTask")
        self.assertIn(
            "requestFeedbackInputFocus()",
            body,
            "R692: 关闭任务切到下一个的路径必须登记聚焦请求",
        )

    def test_load_task_details_consumes_focus_request(self) -> None:
        body = _extract_function_body(_web_source(), "loadTaskDetails")
        self.assertIn(
            "maybeApplyPendingInputFocus()",
            body,
            "R692: 任务详情渲染完成后必须消费待处理的聚焦请求",
        )

    def test_focus_request_has_freshness_window(self) -> None:
        body = _extract_function_body(_web_source(), "maybeApplyPendingInputFocus")
        self.assertIn(
            "FOCUS_REQUEST_FRESH_MS",
            body,
            "R692: 聚焦请求必须有过期时间窗，防止迟到请求抢焦点",
        )

    def test_focus_skips_hidden_textarea(self) -> None:
        body = _extract_function_body(_web_source(), "maybeApplyPendingInputFocus")
        self.assertIn(
            'display === "none"',
            body,
            "R692: yesno 模式（textarea 隐藏）必须跳过聚焦",
        )


class TestVscodeSubmitFocus(unittest.TestCase):
    """插件端：手动提交成功 → 下一任务 updateUI 时聚焦。"""

    def setUp(self) -> None:
        self.source = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    def test_submit_feedback_sets_pending_focus(self) -> None:
        match = re.search(
            r"async function submitFeedback\(\) \{.*?\n  \}", self.source, re.DOTALL
        )
        self.assertIsNotNone(match, "未找到 submitFeedback")
        assert match is not None
        self.assertIn(
            "pendingInputFocusAtMs = Date.now()",
            match.group(0),
            "R692: 手动提交成功后必须登记聚焦请求",
        )

    def test_update_ui_consumes_pending_focus_on_task_change(self) -> None:
        self.assertIn("PENDING_FOCUS_FRESH_MS", self.source)
        match = re.search(
            r"if \(!isSameTask && config\.task_id\) \{.*?\n    \}",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "未找到 updateUI 任务切换分支")
        assert match is not None
        body = match.group(0)
        self.assertIn("pendingInputFocusAtMs", body)
        self.assertIn("focusTarget.focus()", body)
        self.assertIn(
            "question_type !== 'yesno'",
            body,
            "R692: yesno 任务不得抢按钮焦点",
        )


class TestVscodeNotifyDeepLink(unittest.TestCase):
    """插件端：隐藏期间的新任务通知 → 回到面板时直达该任务。"""

    def setUp(self) -> None:
        self.ts = WEBVIEW_TS.read_text(encoding="utf-8")
        self.js = WEBVIEW_UI_JS.read_text(encoding="utf-8")

    def test_dispatch_records_pending_task(self) -> None:
        match = re.search(
            r"async dispatchNewTaskNotification\(.*?\n  \}", self.ts, re.DOTALL
        )
        self.assertIsNotNone(match, "未找到 dispatchNewTaskNotification")
        assert match is not None
        self.assertIn(
            "_pendingNotifiedTaskId = ids[0]",
            match.group(0),
            "R692: 派发新任务通知时必须记录首个任务用于直达",
        )

    def test_visibility_handler_sends_switch_message_with_window(self) -> None:
        match = re.search(
            r"onDidChangeVisibility\(\(\) => \{.*?\n    \}\);", self.ts, re.DOTALL
        )
        self.assertIsNotNone(match, "未找到 onDidChangeVisibility 处理器")
        assert match is not None
        body = match.group(0)
        self.assertIn('type: "switchToTask"', body)
        self.assertIn(
            "PENDING_NOTIFY_DEEPLINK_FRESH_MS",
            body,
            "R692: 直达必须有时间窗（超时不抢用户当前操作）",
        )

    def test_webview_ui_handles_switch_to_task_message(self) -> None:
        self.assertIn("case 'switchToTask':", self.js)
        match = re.search(r"case 'switchToTask':.*?break", self.js, re.DOTALL)
        assert match is not None
        self.assertIn(
            "switchToTask(deepLinkTaskId)",
            match.group(0),
            "R692: 消息处理必须复用既有 switchToTask 切换逻辑",
        )


if __name__ == "__main__":
    unittest.main()
