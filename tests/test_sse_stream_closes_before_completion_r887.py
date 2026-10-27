"""R887：SSE 收到“已完成”之后，流先关干净，等待才结束；否则每次调用漏一条 SSE 连接。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

每完成一次 ``interactive_feedback``，MCP 进程的文件描述符 +1，Web UI 进程的线程 +1、
文件描述符 +1、SSE 订阅者 +1，空闲多久都不回收（30 轮之后 MCP 8 → 39 个 FD，Web UI
5 → 36 个线程）。``ulimit -n 64`` 下一次调用卡了 261.8 s，之后日志里全是
``Too many open files``；部署文档推荐的 Waitress ``--threads=8`` 下，第 8 次调用就挂起。

原因在 ``_sse_listener``：收到完成事件后，是在 ``async with client.stream(...)`` 里面
``completion.set(); return``。``completion.set()`` 唤醒主流程，主流程在 ``finally`` 里立刻
``sse_task.cancel()``，而此时 SSE 任务正跑在 ``return`` 触发的 ``response.aclose()`` 中途。
httpx / httpcore 的关闭挡不住 asyncio 自己的取消（上游 encode/httpx#3782，至今未修），
取消落在关闭中途，连接留在池里，既不归还也不关闭。配置热重载会把整个池重建，所以
现网实例上看不出来。

契约
====

1. 等待返回时，每条打开过的 SSE 流都已完整关闭，没有一条是被取消在关闭中途的；
2. 结果仍然来自完成之后的那次 ``GET /api/tasks/<id>``，并且在流关闭之后才去取；
3. 连续多次调用不累积未关闭的流。

测试矩阵
========

A. 一次调用：流关闭完整、没有被取消在中途、结果正确；
B. 连续 5 次调用：打开数 == 关闭数，没有一条被取消在中途；
C. 结果是在流关闭之后才取的（事件顺序）。

三项在旧代码上都失败：流被取消在关闭中途，关闭数为 0，取结果发生在关闭之前。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import ai_intervention_agent.server_feedback as server
from ai_intervention_agent.server_config import WebUIConfig

TASK_ID = "t-sse"
ANSWER = {"user_input": "from-sse"}


class _Ledger:
    """一次 ``wait_for_task_completion`` 里发生的事，按先后顺序记下来。"""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.opened = 0
        self.closed = 0
        self.cancelled_mid_close = 0
        self.first_poll_seen = asyncio.Event()
        self.event_delivered = False


class _Stream:
    """假的 ``client.stream(...)``。

    ``__aexit__`` 要让出事件循环几次——真实的 ``response.aclose()`` 就是这样，``AsyncMock`` 不挂起，
    取消就没有机会落在关闭中途，旧代码的缺陷会被它藏住。被取消在中途就记下来：那就是连接没关干净。
    """

    def __init__(self, ledger: _Ledger) -> None:
        self._ledger = ledger

    async def __aenter__(self) -> MagicMock:
        self._ledger.opened += 1
        self._ledger.events.append("open")
        response = MagicMock()
        response.aiter_lines = self._lines
        return response

    async def _lines(self) -> AsyncIterator[str]:
        # 真实情况里 SSE 事件总比任务开头的那次轮询晚，所以等第一次轮询发出去再推完成事件。
        await self._ledger.first_poll_seen.wait()
        self._ledger.event_delivered = True
        yield f'data: {{"task_id": "{TASK_ID}", "new_status": "completed"}}'
        await asyncio.Event().wait()  # 之后没有事件，也不结束：真实的 SSE 就是这样挂着

    async def __aexit__(self, *_exc: Any) -> bool:
        try:
            for _ in range(3):
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            self._ledger.cancelled_mid_close += 1
            self._ledger.events.append("close-cancelled")
            raise
        self._ledger.closed += 1
        self._ledger.events.append("close")
        return False


def _client(ledger: _Ledger) -> MagicMock:
    async def get(*_args: Any, **_kwargs: Any) -> MagicMock:
        await asyncio.sleep(0)
        ledger.first_poll_seen.set()
        done = ledger.event_delivered
        ledger.events.append("get-completed" if done else "get-active")
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "success": True,
            "task": {
                "status": "completed" if done else "active",
                "result": ANSWER if done else None,
            },
        }
        return response

    client = MagicMock()
    client.get = AsyncMock(side_effect=get)
    client.post = AsyncMock(side_effect=AssertionError("the task was not abandoned"))
    client.stream = MagicMock(side_effect=lambda *_a, **_k: _Stream(ledger))
    return client


async def _one_call() -> tuple[_Ledger, dict[str, Any]]:
    ledger = _Ledger()
    with (
        patch(
            "ai_intervention_agent.service_manager.get_web_ui_config",
            return_value=(WebUIConfig(host="127.0.0.1", port=18999), 120),
        ),
        patch(
            "ai_intervention_agent.service_manager.get_async_client",
            return_value=_client(ledger),
        ),
        patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
        patch.object(server, "_FETCH_RETRY_BACKOFF_S", (0.0,)),
    ):
        result = await asyncio.wait_for(
            server.wait_for_task_completion(TASK_ID, timeout=20), 15
        )
    return ledger, result


class TestTheStreamIsClosedBeforeTheWaitEnds:
    def test_one_call_closes_its_stream_completely(self) -> None:
        ledger, result = asyncio.run(_one_call())

        assert result == ANSWER
        assert ledger.opened == 1
        assert ledger.cancelled_mid_close == 0, (
            "the SSE stream was cancelled in the middle of closing: its connection "
            f"stays open in the pool (events: {ledger.events})"
        )
        assert ledger.closed == 1

    def test_calls_in_a_row_leave_no_stream_behind(self) -> None:
        async def five() -> list[_Ledger]:
            return [(await _one_call())[0] for _ in range(5)]

        ledgers = asyncio.run(five())

        assert sum(ledger.opened for ledger in ledgers) == 5
        assert sum(ledger.closed for ledger in ledgers) == 5
        assert sum(ledger.cancelled_mid_close for ledger in ledgers) == 0

    def test_the_result_is_fetched_after_the_stream_has_closed(self) -> None:
        ledger, _ = asyncio.run(_one_call())

        assert ledger.events.index("close") < ledger.events.index("get-completed"), (
            f"the result was fetched while the stream was still open: {ledger.events}"
        )
