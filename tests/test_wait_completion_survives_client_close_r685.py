"""R685 — 配置热更新关闭 httpx client 后，等待中的会话不得丢失反馈（TODO#3）。

事故链（修复前）
----------------

1. ``interactive_feedback`` → ``wait_for_task_completion`` 在函数开头一次性
   捕获 ``http_client = service_manager.get_async_client(config)``，闭包内
   ``_fetch_result`` / ``_sse_listener`` / ghost-task close 全部复用该引用。
2. 用户在等待期间编辑 ``config.toml`` → MCP 进程内 ``ConfigManager`` file
   watcher 触发 ``service_manager._invalidate_runtime_caches_on_config_change``
   → 旧 client 被 ``close()``。
3. 已关闭的 ``httpx.AsyncClient`` 上任何请求都抛
   ``RuntimeError("Cannot send a request, as the client has been closed.")``：
   - ``_sse_listener`` 的 stream 立即断开（SSE 通道死亡）；
   - ``_poll_fallback`` 的 ``_fetch_result`` 每轮抛错被 except 吞掉，
     永远拿不到结果。
4. 用户在 Web UI 提交反馈 → web_ui 子进程里任务 completed（页面显示已反馈），
   但 MCP 侧直到 backend_timeout 到期都拿不到 result → 返回 resubmit
   提示 → **用户反馈永久丢失**，且 Web/插件页面与 MCP 调用方状态矛盾。

修复
----

``wait_for_task_completion`` 内所有请求点改为**即时**调用
``service_manager.get_async_client(config)``（该访问器在 client 已关闭时
自动重建），不再复用函数开头捕获的引用。

本测试锁定：

1. **行为**：等待期间 pooled client 被关闭（模拟配置热更新），后续轮询
   自动拿到重建后的 client 并成功取回用户反馈——绝不返回 resubmit 文本。
2. **源码契约**：``wait_for_task_completion`` 不得再出现
   ``http_client = service_manager.get_async_client`` 的一次性捕获形态。
"""

from __future__ import annotations

import asyncio
import inspect
import re
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import ai_intervention_agent.server_feedback as server_feedback


def _make_config() -> Any:
    from ai_intervention_agent.service_manager import WebUIConfig

    return WebUIConfig(
        host="127.0.0.1",
        port=8090,
        language="auto",
        timeout=5,
        max_retries=0,
        retry_delay=0.1,
        external_base_url="",
    )


def _make_closed_client() -> MagicMock:
    """模拟已被配置热更新回调 close 掉的 client：任何请求都抛 RuntimeError。"""
    closed = MagicMock(name="closed_client")
    closed_error = RuntimeError("Cannot send a request, as the client has been closed.")
    closed.get = AsyncMock(side_effect=closed_error)
    closed.post = AsyncMock(side_effect=closed_error)
    closed.stream = MagicMock(side_effect=closed_error)
    closed.is_closed = True
    return closed


def _make_live_client(result_payload: dict[str, Any]) -> MagicMock:
    """模拟 get_async_client 重建后的可用 client：返回 completed 任务结果。"""
    live = MagicMock(name="live_client")
    completed_resp = MagicMock()
    completed_resp.status_code = 200
    completed_resp.json.return_value = {
        "success": True,
        "task": {"status": "completed", "result": result_payload},
    }
    live.get = AsyncMock(return_value=completed_resp)
    live.post = AsyncMock()
    # SSE 保持不可用（已在关闭事件中断开），迫使结果只能来自 poll 路径，
    # 从而精确验证 _fetch_result 的 client 重取逻辑。
    live.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
    live.is_closed = False
    return live


class TestWaitCompletionSurvivesClientClose(unittest.TestCase):
    """等待期间 client 被关闭（配置热更新）后，反馈结果仍必须送达。"""

    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch("ai_intervention_agent.service_manager.get_async_client")
    def test_result_recovered_after_client_close(
        self, mock_get_client, mock_get_cfg
    ) -> None:
        mock_get_cfg.return_value = (_make_config(), 60)

        closed_client = _make_closed_client()
        live_client = _make_live_client({"user_input": "survived-r685"})

        # 前几次调用返回"已关闭"client（模拟配置变更后、访问器尚未被
        # 触发重建前的窗口）；随后访问器重建，返回可用 client。
        call_count = {"n": 0}

        def _get_async_client(_cfg: Any) -> MagicMock:
            call_count["n"] += 1
            return closed_client if call_count["n"] <= 2 else live_client

        mock_get_client.side_effect = _get_async_client

        with (
            patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
            patch.object(server_feedback, "_POLL_INTERVAL_FAST_S", 0.05),
        ):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-r685", timeout=5)
            )

        self.assertEqual(
            result.get("user_input"),
            "survived-r685",
            "client 被配置热更新关闭后，等待协程必须通过重建的 client 取回反馈",
        )
        self.assertGreaterEqual(
            mock_get_client.call_count,
            3,
            "每个请求点都应即时调用 get_async_client（而不是复用开头捕获的引用）",
        )

    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch("ai_intervention_agent.service_manager.get_async_client")
    def test_no_resubmit_when_result_available_after_close(
        self, mock_get_client, mock_get_cfg
    ) -> None:
        """timeout 后 retry-before-close 阶段也必须用重建后的 client。"""
        mock_get_cfg.return_value = (_make_config(), 60)

        closed_client = _make_closed_client()
        live_client = _make_live_client({"user_input": "late-but-alive-r685"})

        # 等待窗口内全部命中 closed client（模拟 close 后 poll 一直失败直到
        # backend timeout），timeout 后的 retry 阶段访问器返回重建 client。
        state = {"timed_out": False}

        def _get_async_client(_cfg: Any) -> MagicMock:
            return live_client if state["timed_out"] else closed_client

        mock_get_client.side_effect = _get_async_client

        async def _run() -> dict[str, Any]:
            waiter = asyncio.create_task(
                server_feedback.wait_for_task_completion("t-r685-late", timeout=1)
            )
            # 等到 backend timeout 生效后，标记 client 已重建
            await asyncio.sleep(0.5)
            state["timed_out"] = True
            return await waiter

        with (
            patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
            patch.object(server_feedback, "_POLL_INTERVAL_FAST_S", 0.05),
            patch.object(server_feedback, "_FETCH_RETRY_BACKOFF_S", (0.0, 0.6)),
        ):
            result = asyncio.run(_run())

        self.assertEqual(
            result.get("user_input"),
            "late-but-alive-r685",
            "retry-before-close 阶段必须使用重建后的 client 抢救用户反馈",
        )


class TestSourceContract(unittest.TestCase):
    """源码不变量：禁止回到"函数开头一次性捕获 client"的形态。"""

    def setUp(self) -> None:
        self.src = inspect.getsource(server_feedback.wait_for_task_completion)

    def test_no_top_level_client_capture(self) -> None:
        # 只匹配真实代码行（行首为缩进 + 赋值），不误伤 R685 说明注释里
        # 引用的历史写法（注释行以 ``#`` 开头，不会命中本正则）。
        self.assertNotRegex(
            self.src,
            r"(?m)^\s*http_client\s*=\s*service_manager\.get_async_client",
            "R685: wait_for_task_completion 不得在函数开头一次性捕获 client；"
            "必须在每个请求点即时调用 service_manager.get_async_client",
        )

    def test_fetch_result_uses_pooled_accessor(self) -> None:
        m = re.search(
            r"async def _fetch_result.*?(?=\n    async def )", self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "未找到 _fetch_result 函数体——测试需要更新")
        assert m is not None
        self.assertIn(
            "_pooled_client()",
            m.group(0),
            "_fetch_result 必须通过 _pooled_client() 即时获取 client",
        )

    def test_sse_listener_gets_client_inside_body(self) -> None:
        m = re.search(
            r"async def _sse_listener.*?(?=\n    async def _poll_fallback)",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "未找到 _sse_listener 函数体——测试需要更新")
        assert m is not None
        self.assertIn(
            "service_manager.get_async_client",
            m.group(0),
            "_sse_listener 必须在函数体内即时获取 pooled client（R685）",
        )


if __name__ == "__main__":
    unittest.main()
