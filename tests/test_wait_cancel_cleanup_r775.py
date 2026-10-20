"""R775：MCP 客户端取消 ``interactive_feedback`` 时，Web UI 里的任务必须被关掉。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

MCP 客户端在用户点「停止」或工具调用超时时发 ``notifications/cancelled``。MCP SDK
用 anyio cancel scope 结束这个请求：scope 退出之前，handler 的每个 ``await`` 都会
被再取消一次（anyio 的取消是电平触发，``Task.cancel()`` 是边沿触发，只送达一次）。
``wait_for_task_completion`` 的清理写在 ``finally`` 里：先取消 SSE / 轮询两个子任务，
再 ``await`` 几次重试取回、最后 ``POST /api/tasks/<id>/close``。取消是 anyio 送来
的时候，第一个 ``await`` 就被打断，close 请求一次都没发出去：

* 日志里没有任何清理痕迹（``CancelledError`` 是 ``BaseException``，沿途的
  ``except Exception`` 都不会记录它）；
* AI 已经放弃的问题继续作为 active 任务显示在 Web UI 上，下一次调用建出来的新任务
  排在它后面，用户看到的是旧问题，提交的反馈也绑到旧任务上，没有人在等。

R13·B1 就是为这个场景写的，但它的测试用 ``Task.cancel()`` 取消，清理照常跑完，
所以一直没人发现取消路径其实没有清理。

契约
====

1. 取消送达时（无论 ``Task.cancel()`` 还是 anyio scope）都要把任务关掉；
2. 取消照常传给调用方：调用方不会因为清理还在跑而一直被留着；
3. 清理不会在 ``_DETACHED_CLEANUPS`` 里留下残余，清理出错也只记录、不丢失；
4. 清理走独立的 task（``_run_to_completion``），而不是在 ``finally`` 里直接 ``await``。

测试矩阵
========

A. anyio scope 取消（MCP runner 的做法）：close 恰好 POST 一次到正确 URL，取消仍传给调用方；
B. ``Task.cancel()`` 取消：同样 close 一次（对照，旧代码也通过）；
C. 清理完成后没有残余 task；清理自己抛异常时记 WARNING 并释放登记；
D. ``wait_for_task_completion`` 的 ``finally`` 经由 ``_run_to_completion``。

A 在旧代码上失败（close 次数为 0）。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

import ai_intervention_agent.server_feedback as server
from ai_intervention_agent.server_config import WebUIConfig

CLOSE_URL = "http://127.0.0.1:18999/api/tasks/t-cancelled/close"


class _WebUI:
    """一个永远不回答的 Web UI：任务一直 pending，记录 close 请求。

    请求里的 ``await asyncio.sleep(0)`` 模拟真实网络请求一定会挂起：``AsyncMock``
    本身不挂起，取消就没有机会被送达，旧代码的缺陷会被它藏住。
    """

    def __init__(self) -> None:
        self.posts: list[str] = []
        self.polled = asyncio.Event()
        self.closed = asyncio.Event()
        self.client = MagicMock()
        self.client.get = AsyncMock(side_effect=self._get)
        self.client.post = AsyncMock(side_effect=self._post)
        self.client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))

    async def _get(self, *_args: Any, **_kwargs: Any) -> MagicMock:
        await asyncio.sleep(0)
        self.polled.set()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "success": True,
            "task": {"status": "pending", "result": None},
        }
        return response

    async def _post(self, url: str, **_kwargs: Any) -> MagicMock:
        await asyncio.sleep(0)
        self.posts.append(url)
        self.closed.set()
        return MagicMock(status_code=200)


def _run(scenario: Callable[[_WebUI], Awaitable[None]]) -> _WebUI:
    async def main() -> _WebUI:
        web_ui = _WebUI()
        with (
            patch(
                "ai_intervention_agent.service_manager.get_web_ui_config",
                return_value=(WebUIConfig(host="127.0.0.1", port=18999), 120),
            ),
            patch(
                "ai_intervention_agent.service_manager.get_async_client",
                return_value=web_ui.client,
            ),
            patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
            patch.object(server, "_FETCH_RETRY_BACKOFF_S", (0.0,)),
        ):
            await scenario(web_ui)
        return web_ui

    return asyncio.run(main())


async def _until_idle() -> None:
    for _ in range(200):
        if not getattr(server, "_DETACHED_CLEANUPS", ()):
            return
        await asyncio.sleep(0.01)


async def _cancel_like_the_mcp_runner(web_ui: _WebUI, outcome: list[str]) -> None:
    async def handler() -> None:
        try:
            await server.wait_for_task_completion("t-cancelled", timeout=60)
        except asyncio.CancelledError:
            outcome.append("cancelled")
            raise

    async with anyio.create_task_group() as group:
        group.start_soon(handler)
        await asyncio.wait_for(web_ui.polled.wait(), 5)
        group.cancel_scope.cancel()
    await asyncio.wait_for(web_ui.closed.wait(), 5)
    await _until_idle()


class TestCancelledByTheMcpRunner:
    def test_the_abandoned_task_is_closed(self) -> None:
        outcome: list[str] = []

        async def scenario(web_ui: _WebUI) -> None:
            await _cancel_like_the_mcp_runner(web_ui, outcome)

        web_ui = _run(scenario)

        assert web_ui.posts == [CLOSE_URL]

    def test_the_cancellation_still_reaches_the_caller(self) -> None:
        outcome: list[str] = []

        async def scenario(web_ui: _WebUI) -> None:
            await _cancel_like_the_mcp_runner(web_ui, outcome)

        _run(scenario)

        assert outcome == ["cancelled"]


class TestCancelledWithPlainTaskCancel:
    def test_the_abandoned_task_is_closed(self) -> None:
        async def scenario(web_ui: _WebUI) -> None:
            task = asyncio.ensure_future(
                server.wait_for_task_completion("t-cancelled", timeout=60)
            )
            await asyncio.wait_for(web_ui.polled.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(web_ui.closed.wait(), 5)
            await _until_idle()

        web_ui = _run(scenario)

        assert web_ui.posts == [CLOSE_URL]


class TestDetachedCleanupBookkeeping:
    def test_nothing_is_left_registered_after_the_cleanup(self) -> None:
        leftovers: list[int] = []

        async def scenario(web_ui: _WebUI) -> None:
            await _cancel_like_the_mcp_runner(web_ui, [])
            leftovers.append(len(server._DETACHED_CLEANUPS))

        _run(scenario)

        assert leftovers == [0]

    def test_a_failing_cleanup_is_logged_and_released(self) -> None:
        warnings: list[str] = []

        async def explode(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("close blew up")

        async def scenario(web_ui: _WebUI) -> None:
            with (
                patch.object(server, "_close_orphan_task_best_effort", explode),
                patch.object(
                    server.logger,
                    "warning",
                    side_effect=lambda message, **_kwargs: warnings.append(message),
                ),
            ):

                async def handler() -> None:
                    await server.wait_for_task_completion("t-cancelled", timeout=60)

                async with anyio.create_task_group() as group:
                    group.start_soon(handler)
                    await asyncio.wait_for(web_ui.polled.wait(), 5)
                    group.cancel_scope.cancel()
                await _until_idle()

        _run(scenario)

        assert len(warnings) == 1
        assert "close blew up" in warnings[0]


class TestSourceContract:
    def test_the_finally_block_runs_its_cleanup_in_a_task_of_its_own(self) -> None:
        source = inspect.getsource(server.wait_for_task_completion)
        finally_block = source[source.rindex("    finally:") :]

        assert "_run_to_completion(_settle_unanswered_task())" in finally_block
        assert "_close_orphan_task_best_effort" not in finally_block
