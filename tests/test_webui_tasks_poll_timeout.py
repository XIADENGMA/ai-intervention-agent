"""
Web UI ``/api/tasks`` 轮询硬超时护栏的源码不变量测试（R20.4）

背景与缺陷复现路径
-------------------
``static/js/multi_task.js::fetchAndApplyTasks`` 历史上只设置了
``AbortController``（用于"防重叠"——下一次轮询启动时取消上一次的 in-flight
请求），**但没有 setTimeout 超时绑定**。这意味着当服务端出现"半开连接"
（TCP 黑洞、防火墙丢包、内核网络栈卡死）时，``fetch('/api/tasks')`` 会无限
hang，导致：

1. 当前轮询永远不会结束 → ``await fetchAndApplyTasks`` 永远不返回；
2. ``scheduleNextTasksPoll`` 因为在 await 之后才调用，不会被再次触发，于是
   整个 ``setTimeout`` 链中断，**轮询机制冻结**；
3. 30s 健康检查的 ``if (!tasksPollingTimer)`` 守卫不会成立——上一次
   ``setTimeout`` 返回的 timer ID 还在变量里（虽然已经 fired），变量值仍是
   非 null 数字 → 健康检查无法识别"轮询冻结"状态，无法 auto-restart；
4. 用户看到的现象是：任务列表永远不更新、且没有任何错误反馈。

而 ``packages/vscode/webview-ui.js::pollAllData`` 早已有
``setTimeout(() => abort(), POLL_TASKS_TIMEOUT_MS=6000)`` 护栏；本来 Web UI
应该对齐，但漂移了。

本文件锁住以下不变量
--------------------
1. ``static/js/multi_task.js`` 中存在常量 ``TASKS_POLL_TIMEOUT_MS = 6000``；
2. ``fetchAndApplyTasks`` 函数体内**实际调度** ``setTimeout`` 用于 abort；
3. ``finally`` 块清理 ``tasksTimeoutId``，避免 timer 泄漏；
4. Web UI 端的超时数值与 VSCode webview 端的 ``POLL_TASKS_TIMEOUT_MS`` 对齐
   （否则两端在网络抖动下表现不一致）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_MULTI_TASK_JS = REPO_ROOT / "static" / "js" / "multi_task.js"
VSCODE_WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_fetchAndApplyTasks_body(text: str) -> str:
    """提取 ``fetchAndApplyTasks`` 的函数体（含其内部代码块）。

    使用粗略策略：从 ``async function fetchAndApplyTasks`` 处起，按花括号
    平衡找到匹配的 ``}``。这对单一函数定义足够精确。
    """
    start_match = re.search(r"async\s+function\s+fetchAndApplyTasks\s*\(", text)
    if not start_match:
        return ""
    body_start = text.find("{", start_match.end())
    if body_start == -1:
        return ""
    depth = 1
    i = body_start + 1
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return text[body_start : i if depth == 0 else len(text)]


class TestWebUITasksPollTimeoutInvariants(unittest.TestCase):
    """R20.4: ``static/js/multi_task.js::fetchAndApplyTasks`` 必须有 6s 硬超时。"""

    def setUp(self) -> None:
        self.assertTrue(
            WEB_MULTI_TASK_JS.is_file(),
            f"测试前置：{WEB_MULTI_TASK_JS} 必须存在",
        )
        self.text = _read(WEB_MULTI_TASK_JS)

    def test_constant_declared_with_six_second_default(self) -> None:
        """顶层常量声明：``TASKS_POLL_TIMEOUT_MS`` 必须存在且 = 6000。"""
        match = re.search(
            r"\bvar\s+TASKS_POLL_TIMEOUT_MS\s*=\s*(\d+)\b",
            self.text,
        )
        self.assertIsNotNone(
            match,
            "multi_task.js 必须声明 ``var TASKS_POLL_TIMEOUT_MS = <ms>``，"
            "用于硬超时护栏（R20.4）。",
        )
        # mypy/ty: 类型守卫
        assert match is not None
        self.assertEqual(
            int(match.group(1)),
            6000,
            "TASKS_POLL_TIMEOUT_MS 必须 = 6000ms，与 VSCode webview-ui.js 的"
            " POLL_TASKS_TIMEOUT_MS 对齐（行为一致性）。",
        )

    def test_fetchAndApplyTasks_schedules_setTimeout_with_abort(self) -> None:
        """``fetchAndApplyTasks`` 函数体内必须实际调度 setTimeout 来 abort。

        仅声明常量是不够的——必须真的有 ``setTimeout(... abort ...)`` 调用。
        """
        body = _extract_fetchAndApplyTasks_body(self.text)
        self.assertNotEqual(
            body,
            "",
            "未能定位 fetchAndApplyTasks 函数体——是否被重命名？",
        )

        # 1) 函数体必须出现 setTimeout
        self.assertRegex(
            body,
            r"\bsetTimeout\s*\(",
            "fetchAndApplyTasks 函数体内必须调度 setTimeout 用于硬超时 abort。",
        )

        # 2) setTimeout 的回调里必须调用 abort()
        # 多行 dotall 匹配：从 setTimeout( 到对应 ms 之间的 callback 必须含 abort
        st_match = re.search(
            r"setTimeout\s*\(\s*\(\s*\)\s*=>\s*\{(?P<cb>.*?)\}\s*,\s*"
            r"TASKS_POLL_TIMEOUT_MS\s*\)",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(
            st_match,
            "fetchAndApplyTasks 必须用 ``setTimeout(() => {{ ... }}, "
            "TASKS_POLL_TIMEOUT_MS)`` 形式调度超时（不允许硬编码 ms 数字）。",
        )
        assert st_match is not None
        callback = st_match.group("cb")
        self.assertIn(
            "abort",
            callback,
            "setTimeout 的回调必须调用 ``abort()`` 来取消 in-flight fetch。",
        )

    def test_finally_clears_timeout(self) -> None:
        """``finally`` 块必须 clearTimeout 释放 timer，避免泄漏。"""
        body = _extract_fetchAndApplyTasks_body(self.text)
        # 用 finally 区段定位
        finally_match = re.search(r"\bfinally\s*\{(?P<f>.*?)\}\s*\}", body, re.DOTALL)
        self.assertIsNotNone(
            finally_match,
            "fetchAndApplyTasks 必须有 finally 块来清理资源",
        )
        assert finally_match is not None
        finally_body = finally_match.group("f")
        self.assertIn(
            "clearTimeout",
            finally_body,
            "finally 块必须调用 clearTimeout(tasksTimeoutId) 清理硬超时定时器；"
            "否则 fetch 成功完成后 timer 仍会触发 abort（虽然此时 controller "
            "已被释放，但仍是不必要的副作用 + 测试性能开销）。",
        )

    def test_aligned_with_vscode_webview(self) -> None:
        """Web UI 与 VSCode webview 的硬超时数值必须对齐——否则跨端行为漂移。"""
        if not VSCODE_WEBVIEW_UI_JS.is_file():
            self.skipTest("packages/vscode/webview-ui.js 不存在")

        vscode_text = _read(VSCODE_WEBVIEW_UI_JS)
        vscode_match = re.search(
            r"\bPOLL_TASKS_TIMEOUT_MS\s*=\s*(\d+)\b",
            vscode_text,
        )
        self.assertIsNotNone(
            vscode_match,
            "VSCode webview-ui.js 必须声明 POLL_TASKS_TIMEOUT_MS（双端对齐前提）",
        )
        assert vscode_match is not None
        vscode_ms = int(vscode_match.group(1))

        web_match = re.search(
            r"\bTASKS_POLL_TIMEOUT_MS\s*=\s*(\d+)\b",
            self.text,
        )
        self.assertIsNotNone(web_match)
        assert web_match is not None
        web_ms = int(web_match.group(1))

        self.assertEqual(
            web_ms,
            vscode_ms,
            "TASKS_POLL_TIMEOUT_MS（Web UI）必须 = POLL_TASKS_TIMEOUT_MS"
            "（VSCode webview）；任一端调整都需双向同步，否则同样的网络环境"
            "下两端表现不一致（Web UI 永久 hang，VSCode 6s 超时）。",
        )

    def test_abort_callback_guards_against_null_controller(self) -> None:
        """``setTimeout`` 回调中 abort 前必须先判 ``tasksPollAbortController``
        非 null——否则在 ``finally`` 已清空 controller 后 timer 触发会 NPE。"""
        body = _extract_fetchAndApplyTasks_body(self.text)
        st_match = re.search(
            r"setTimeout\s*\(\s*\(\s*\)\s*=>\s*\{(?P<cb>.*?)\}\s*,\s*"
            r"TASKS_POLL_TIMEOUT_MS\s*\)",
            body,
            re.DOTALL,
        )
        assert st_match is not None
        cb = st_match.group("cb")
        self.assertIn(
            "tasksPollAbortController",
            cb,
            "setTimeout 回调里必须引用 tasksPollAbortController 才能 abort",
        )
        # 必须有显式 if 判 null（防御性写法）或 try/catch（兜底）
        has_guard = ("if (tasksPollAbortController" in cb) or ("try" in cb)
        self.assertTrue(
            has_guard,
            "setTimeout 回调必须在 abort 前用 ``if (tasksPollAbortController)``"
            " 守卫或包在 try/catch 里——否则 finally 清空 controller 后 timer "
            "触发会抛 TypeError。",
        )


if __name__ == "__main__":
    unittest.main()
