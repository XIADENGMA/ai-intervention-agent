"""TODO#8-A — 页面 hidden 期间 SSE 保活 + 任务感知链路不变量。

## 背景

历史行为：``visibilitychange`` hidden 分支调用 ``stopTasksPolling()``
（内含 ``_disconnectSSE()``）+ ``fetchAndApplyTasks`` 对 hidden 无条件
拒绝——页面进入后台后整条"新任务感知链路"全停。当时合理（后台只有
页内 Visual Hint，没人看见），但引入"后台发系统桌面通知"
（``notifyNewTasks`` 的 pageAway 分支）后，后台根本感知不到新任务，
桌面通知形同虚设。

## 本测试锁定的不变量

1. ``stopTasksPolling`` 接受 options 且 ``keepSse`` 为真时不断开 SSE
   （``_disconnectSSE`` 必须在 ``!(options && options.keepSse)`` 守卫内）。
2. ``visibilitychange`` hidden 分支必须以 ``{ keepSse: true }`` 调用
   ``stopTasksPolling``——保住后台 SSE 连接。
3. ``beforeunload`` 仍然无参调用 ``stopTasksPolling()``——卸载路径必须
   全断（含 SSE），防连接泄漏。
4. ``fetchAndApplyTasks`` 对 SSE 驱动的 reason（sse / sse-gap）在
   hidden 时放行，其余 reason 维持拦截。
5. ``_scheduleSharedSseFetch`` 在 hidden 时跳过 debounce timer 直接
   拉取（规避后台 timer 节流，intensive throttling 下 timer 最长延迟
   1 分钟）。
6. 直连 SSE 的 ``task_changed`` / ``gap_warning`` handler 统一走
   ``_scheduleSharedSseFetch``（获得 hidden 直通语义，且不再有第二份
   debounce 实现漂移）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _extract_balanced(src: str, anchor: str) -> str:
    """从 anchor 起做括号平衡截取（anchor 之后第一个 ``{`` 到闭合）。"""
    start = src.find(anchor)
    assert start != -1, f"anchor not found: {anchor}"
    open_brace = src.find("{", start + len(anchor) - 1)
    assert open_brace != -1, f"opening brace not found after: {anchor}"
    depth = 1
    i = open_brace + 1
    while i < len(src) and depth > 0:
        char = src[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"unbalanced braces after: {anchor}"
    return src[start:i]


class TestStopTasksPollingKeepSse(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_stop_tasks_polling_accepts_keep_sse_option(self) -> None:
        body = _extract_balanced(self.src, "function stopTasksPolling(options)")
        self.assertIn(
            "options && options.keepSse",
            body,
            "stopTasksPolling 必须以 options.keepSse 守卫 _disconnectSSE——"
            "后台保活路径依赖它保留 SSE 连接",
        )
        self.assertIn(
            "_disconnectSSE()",
            body,
            "默认路径（无 keepSse）必须仍断开 SSE（unload / 显式停止语义）",
        )

    def test_visibilitychange_hidden_keeps_sse(self) -> None:
        start = self.src.find('"visibilitychange"')
        self.assertGreater(start, 0)
        body = _extract_balanced(self.src[start:], "function")
        hidden_branch = re.search(
            r"if\s*\(\s*document\.hidden\s*\)\s*\{(.*?)\n\s*\}\s*else",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(hidden_branch, "找不到 hidden 分支")
        assert hidden_branch is not None
        self.assertIn(
            "stopTasksPolling({ keepSse: true })",
            hidden_branch.group(1),
            "visibilitychange hidden 分支必须 keepSse——否则后台无法感知"
            "新任务，系统桌面通知（TODO#8-A）失效",
        )

    def test_beforeunload_fully_disconnects(self) -> None:
        start = self.src.find('"beforeunload"')
        self.assertGreater(start, 0)
        body = _extract_balanced(self.src[start:], "function")
        self.assertIn(
            "stopTasksPolling()",
            body,
            "beforeunload 必须无参调用 stopTasksPolling()（全断含 SSE），"
            "防跨页面连接泄漏",
        )
        self.assertNotIn("keepSse", body, "unload 路径绝不能保留 SSE")


class TestHiddenSseFetchPassthrough(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_fetch_and_apply_tasks_allows_sse_reasons_when_hidden(self) -> None:
        body = _extract_balanced(self.src, "async function fetchAndApplyTasks(reason)")
        self.assertIn(
            'reason === "sse"',
            body,
            "fetchAndApplyTasks 必须识别 SSE 驱动的 reason",
        )
        self.assertIn(
            'reason === "sse-gap"',
            body,
            "sse-gap（history evict 全量重拉）同样要在 hidden 时放行",
        )
        self.assertIn(
            "document.hidden && !sseDriven",
            body,
            "hidden 拦截必须带 !sseDriven 豁免——否则后台感知链路断裂",
        )

    def test_schedule_shared_sse_fetch_bypasses_timer_when_hidden(self) -> None:
        body = _extract_balanced(
            self.src, "function _scheduleSharedSseFetch(reason, delayMs)"
        )
        hidden_gate = re.search(
            r"if\s*\([^)]*document\.hidden[^)]*\)\s*\{(.*?)\n\s*\}",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(
            hidden_gate,
            "_scheduleSharedSseFetch 必须有 hidden 直通分支（跳过 debounce "
            "timer，规避后台 timer 节流）",
        )
        assert hidden_gate is not None
        self.assertIn(
            "fetchAndApplyTasks(reason)",
            hidden_gate.group(1),
            "hidden 分支必须直接调用 fetchAndApplyTasks（fetch/promise 不受"
            "后台节流影响）",
        )

    def test_direct_sse_handlers_use_shared_scheduler(self) -> None:
        # task_changed 直连 handler：统一走 _scheduleSharedSseFetch
        task_changed_start = self.src.find('source.addEventListener("task_changed"')
        self.assertGreater(task_changed_start, 0)
        task_changed_body = _extract_balanced(self.src[task_changed_start:], "function")
        self.assertIn(
            '_scheduleSharedSseFetch("sse", 80)',
            task_changed_body,
            "直连 task_changed handler 必须复用 _scheduleSharedSseFetch"
            "（获得 hidden 直通语义）",
        )

        gap_start = self.src.find('source.addEventListener("gap_warning"')
        self.assertGreater(gap_start, 0)
        gap_body = _extract_balanced(self.src[gap_start:], "function")
        self.assertIn(
            '_scheduleSharedSseFetch("sse-gap", 0)',
            gap_body,
            "直连 gap_warning handler 必须复用 _scheduleSharedSseFetch",
        )


class TestHiddenNewTaskNotificationImmediate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_update_tasks_list_skips_merge_timer_when_hidden(self) -> None:
        body = _extract_balanced(self.src, "function updateTasksList(tasks)")
        self.assertIn(
            "document.hidden === true",
            body,
            "updateTasksList 必须检测 hidden——后台跳过 150ms 合并 timer "
            "直接通知（timer 会被后台节流拖到分钟级）",
        )
        self.assertIn(
            "activeTaskId && !pageHidden",
            body,
            "合并 timer 只应在页面前台且有活动任务时使用",
        )


if __name__ == "__main__":
    unittest.main()
