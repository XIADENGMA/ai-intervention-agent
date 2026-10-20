"""R766 — 配置热重载不得让等待中的反馈丢失。

事故链（修复前，由真实 wheel 的故障注入复现）
--------------------------------------------

1. ``interactive_feedback`` 在 ``wait_for_task_completion`` 里等用户回复：SSE 监听器
   阻塞在 ``/api/events`` 的读上，``sse_connected`` 已 set，轮询进入 30 s 的 safety net 睡眠。
2. 配置文件变化（包括用户在 Web UI 里改任何一个设置）→ 文件监听线程回调
   ``_invalidate_runtime_caches_on_config_change`` → 旧 client 在**监听线程**里
   ``asyncio.run(client.aclose())``。
3. 连接属于主事件循环。别的线程直接关掉 transport，主循环却没被唤醒，SSE 读一直
   不报错；R685 只修了轮询侧，没发现这一点。
4. 用户回复。任务 completed，Web UI 约 10 s 后清掉它；30 s 的轮询醒来拿到 404，
   返回 "请立即调用 interactive_feedback 工具"，用户的文字永久丢失。

即使 SSE 立刻报错，``_poll_fallback`` 的 interval 在睡眠前就定好了，睡眠中途 SSE 断开
并不会叫醒它，盲区同样存在。

本测试锁定两层修复：

1. 旧 client 在**创建它的事件循环**里关闭（真实回环 socket 上的 SSE 读立刻结束）；
2. SSE 退出会叫醒睡眠中的轮询，已完成的任务在被清理前就被取回。
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import unittest
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import ai_intervention_agent.server_feedback as server_feedback
from ai_intervention_agent import service_manager
from ai_intervention_agent.service_manager import WebUIConfig

_REAL_ASYNC_SEND = httpx.AsyncClient.send


def _config() -> WebUIConfig:
    return WebUIConfig(
        host="127.0.0.1",
        port=8090,
        language="auto",
        timeout=5,
        max_retries=0,
        retry_delay=0.1,
        external_base_url="",
    )


def _close(client: Any, owner_loop: Any = None) -> None:
    service_manager._close_async_client_best_effort(client, owner_loop)


class _LoopThread:
    """在后台线程里跑一条事件循环，充当 MCP 进程的主循环。"""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        started = threading.Event()

        def run() -> None:
            asyncio.set_event_loop(self.loop)
            self.loop.call_soon(started.set)
            self.loop.run_forever()
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert started.wait(5), "后台事件循环没有启动"

    def call(self, coro: Any, timeout: float = 5.0) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self) -> None:
        async def cancel_leftovers() -> None:
            leftovers = [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
            ]
            for task in leftovers:
                task.cancel()
            await asyncio.gather(*leftovers, return_exceptions=True)

        self.call(cancel_leftovers())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


class _FakeClient:
    def __init__(self) -> None:
        self.is_closed = False
        self.closed = threading.Event()
        self.closed_on: tuple[int | None, asyncio.AbstractEventLoop] | None = None

    async def aclose(self) -> None:
        self.closed_on = (threading.get_ident(), asyncio.get_running_loop())
        self.is_closed = True
        self.closed.set()


class TestCloseRunsOnOwnerLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = _LoopThread()
        self.addCleanup(self.owner.stop)

    def test_foreign_thread_close_runs_on_the_owner_loop(self) -> None:
        client = _FakeClient()
        _close(client, self.owner.loop)
        self.assertTrue(client.closed.wait(3), "旧 client 没有被关闭")
        self.assertEqual(client.closed_on, (self.owner.thread.ident, self.owner.loop))

    def test_close_from_inside_the_owner_loop_schedules_a_task(self) -> None:
        client = _FakeClient()

        async def scenario() -> None:
            _close(client, asyncio.get_running_loop())
            for _ in range(200):
                if client.is_closed:
                    return
                await asyncio.sleep(0.01)

        self.owner.call(scenario())
        self.assertEqual(client.closed_on, (self.owner.thread.ident, self.owner.loop))

    def test_owner_that_is_not_running_falls_back_to_closing_here(self) -> None:
        idle = asyncio.new_event_loop()
        self.addCleanup(idle.close)
        client = _FakeClient()
        _close(client, idle)
        self.assertTrue(client.is_closed)
        assert client.closed_on is not None
        self.assertEqual(client.closed_on[0], threading.get_ident())

    def test_unknown_owner_falls_back_to_closing_here(self) -> None:
        client = _FakeClient()
        _close(client)
        self.assertTrue(client.is_closed)
        assert client.closed_on is not None
        self.assertEqual(client.closed_on[0], threading.get_ident())

    def test_owner_gone_between_check_and_schedule_falls_back(self) -> None:
        client = _FakeClient()
        with patch.object(
            asyncio,
            "run_coroutine_threadsafe",
            side_effect=RuntimeError("Event loop is closed"),
        ):
            _close(client, self.owner.loop)
        self.assertTrue(client.is_closed)
        assert client.closed_on is not None
        self.assertEqual(client.closed_on[0], threading.get_ident())

    def test_closed_client_is_left_alone(self) -> None:
        client = _FakeClient()
        client.is_closed = True
        _close(client, self.owner.loop)
        self.assertFalse(client.closed.wait(0.2))


class _SilentSseServer:
    """发完响应头和一行注释后就保持沉默，像两次心跳之间的 SSE 连接。"""

    def __init__(self) -> None:
        self._listener = socket.socket()
        self._listener.settimeout(10)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self._connections: list[socket.socket] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
        except OSError:
            return
        self._connections.append(conn)
        try:
            conn.recv(65536)
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                b"Cache-Control: no-cache\r\n\r\n: connected\n\n"
            )
        except OSError:
            return

    def close(self) -> None:
        for conn in self._connections:
            conn.close()
        self._listener.close()
        self._thread.join(5)


@pytest.fixture
def _pooled_client_state() -> Iterator[None]:
    saved = (
        service_manager._async_client,
        service_manager._async_client_loop,
        service_manager._sync_client,
    )
    service_manager._async_client = None
    service_manager._async_client_loop = None
    service_manager._sync_client = None
    try:
        yield
    finally:
        (
            service_manager._async_client,
            service_manager._async_client_loop,
            service_manager._sync_client,
        ) = saved


@pytest.mark.usefixtures("_pooled_client_state")
def test_config_reload_ends_the_sse_read_promptly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实回环 socket：监听线程触发的失效必须立刻让阻塞中的 SSE 读结束。

    修复前读一直阻塞（本测试在 5 s 上限处失败）；服务端活在别的线程里，所以关闭
    连接时发出的 FIN 不会碰巧唤醒读取方的事件循环。
    """
    assert _REAL_ASYNC_SEND.__name__ == "send", "导入本模块时 httpx 的 send 已被替换"
    monkeypatch.setattr(httpx.AsyncClient, "send", _REAL_ASYNC_SEND)
    server = _SilentSseServer()
    owner = _LoopThread()
    streaming = threading.Event()
    ended = threading.Event()
    outcome: dict[str, str] = {}

    async def read_stream() -> None:
        client = service_manager.get_async_client(_config())
        try:
            async with client.stream(
                "GET",
                f"http://127.0.0.1:{server.port}/api/events",
                timeout=httpx.Timeout(None, connect=5.0),
            ) as response:
                streaming.set()
                async for _line in response.aiter_lines():
                    pass
            outcome["result"] = "stream finished"
        except Exception as exc:
            outcome["result"] = type(exc).__name__
        finally:
            ended.set()

    try:
        asyncio.run_coroutine_threadsafe(read_stream(), owner.loop)
        assert streaming.wait(5), "SSE 连接没有建立"
        time.sleep(0.2)

        started = time.monotonic()
        service_manager._invalidate_runtime_caches_on_config_change()

        assert ended.wait(5), (
            "旧 client 关闭后，SSE 读仍然阻塞（读取方的循环没有被唤醒）"
        )
        assert time.monotonic() - started < 2.0
        assert outcome["result"] != "stream finished"
    finally:
        owner.stop()
        server.close()


async def _make_client() -> None:
    service_manager.get_async_client(_config())


@pytest.mark.usefixtures("_pooled_client_state")
def test_pooled_client_remembers_the_loop_it_was_created_on() -> None:
    owner = _LoopThread()
    try:
        owner.call(_make_client())
        assert service_manager._async_client_loop is owner.loop
    finally:
        owner.stop()

    service_manager._async_client = None
    service_manager.get_async_client(_config())
    assert service_manager._async_client_loop is None


class _FakeSseStream:
    """连上后很快断开的 SSE 流；断开的同时任务进入 completed。"""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state

    async def __aenter__(self) -> _FakeSseStream:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def aiter_lines(self) -> Any:
        await asyncio.sleep(0.2)
        self._state["sse_dropped_at"] = time.monotonic()
        raise httpx.ReadError("connection reset")
        yield ""


class TestPollWakesWhenSseEnds(unittest.TestCase):
    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch("ai_intervention_agent.service_manager.get_async_client")
    def test_feedback_submitted_during_the_blind_window_is_delivered(
        self, mock_get_client: MagicMock, mock_get_cfg: MagicMock
    ) -> None:
        mock_get_cfg.return_value = (_config(), 60)
        state: dict[str, Any] = {}

        def reply(*_args: Any, **_kwargs: Any) -> MagicMock:
            response = MagicMock()
            response.status_code = 200
            if "sse_dropped_at" in state:
                response.json.return_value = {
                    "success": True,
                    "task": {
                        "status": "completed",
                        "result": {"user_input": "sent-after-sse-ended"},
                    },
                }
            else:
                response.json.return_value = {
                    "success": True,
                    "task": {"status": "active", "result": None},
                }
            return response

        client = MagicMock()
        client.get = AsyncMock(side_effect=reply)
        client.post = AsyncMock()
        client.stream = MagicMock(return_value=_FakeSseStream(state))
        client.is_closed = False
        mock_get_client.return_value = client

        started = time.monotonic()
        with (
            patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
            patch.object(server_feedback, "_POLL_INTERVAL_SAFETY_NET_S", 5.0),
            patch.object(server_feedback, "_POLL_INTERVAL_FAST_S", 0.05),
        ):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-r766", timeout=10)
            )
        elapsed = time.monotonic() - started

        self.assertEqual(result.get("user_input"), "sent-after-sse-ended")
        self.assertLess(
            elapsed,
            2.5,
            "SSE 断开后轮询应立刻补一次 fetch，而不是睡满 safety-net 间隔",
        )

    @patch("ai_intervention_agent.service_manager.get_web_ui_config")
    @patch("ai_intervention_agent.service_manager.get_async_client")
    def test_poll_goes_back_to_the_fast_cadence_instead_of_spinning(
        self, mock_get_client: MagicMock, mock_get_cfg: MagicMock
    ) -> None:
        """SSE 已经结束后，``sse_ended`` 必须在每个周期被清掉，轮询照常按 2 s 节奏睡。"""
        mock_get_cfg.return_value = (_config(), 60)
        calls = {"get": 0}
        finish_at = time.monotonic() + 1.0

        async def reply(*_args: Any, **_kwargs: Any) -> MagicMock:
            calls["get"] += 1
            await asyncio.sleep(0)
            finished = time.monotonic() >= finish_at or calls["get"] > 300
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {
                "success": True,
                "task": {
                    "status": "completed" if finished else "active",
                    "result": {"user_input": "done"} if finished else None,
                },
            }
            return response

        client = MagicMock()
        client.get = AsyncMock(side_effect=reply)
        client.post = AsyncMock()
        client.stream = MagicMock(return_value=_FakeSseStream({}))
        client.is_closed = False
        mock_get_client.return_value = client

        with (
            patch("ai_intervention_agent.server_config.BACKEND_MIN", 1),
            patch.object(server_feedback, "_POLL_INTERVAL_SAFETY_NET_S", 5.0),
            patch.object(server_feedback, "_POLL_INTERVAL_FAST_S", 0.1),
        ):
            result = asyncio.run(
                server_feedback.wait_for_task_completion("t-r766-spin", timeout=10)
            )

        self.assertEqual(result.get("user_input"), "done")
        self.assertLess(
            calls["get"], 40, "SSE 结束后轮询在空转（sse_ended 没有在每个周期清掉）"
        )


if __name__ == "__main__":
    unittest.main()
