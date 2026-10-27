"""R888：端口上没有 Web UI 时，``ensure_web_ui_running`` 不先在 HTTP 重试里白等 1.5 s。

现象（真实 stdio MCP 服务，端到端复现）
=======================================

Web UI 还没起来时的第一次 ``interactive_feedback``，任务要 2.0 s 才出现在页面上
（发布版 1.9.0 与工作区一致；``bind_interface = 0.0.0.0``、``http_max_retries = 3`` 复现）。
真正起 Web UI 子进程到端口能连只要约 0.23 s，多出来的约 1.5 s 全花在 ``ensure_web_ui_running``
的第一次 ``/api/health`` 探测上：``get_async_client`` 的传输层是
``AsyncHTTPTransport(retries=max_retries)``，对“连接被拒绝”httpcore 按固定退避
（0 / 0.5 / 1.0 s）重试 3 次，端口上本来就没有进程，重试再多也不会成功。

修复：探测前先做一次 TCP 预检（``health_check_service`` 同款）。端口上没人听就不发 HTTP 探测，
直接去启动；端口开着的路径与之前一样走 HTTP 健康检查，并且仍要认出是不是本服务（R856）。

契约
====

1. 端口上没有进程在听：不发任何 HTTP 请求，立刻走 ``start_web_service``，不付重试的退避；
2. 端口开着且 ``/api/health`` 是本服务：不启动；
3. 端口开着但 ``/api/health`` 不是本服务：仍然走启动流程（交给 ``start_web_service`` 判断冲突）；
4. 预检在线程里跑，不阻塞事件循环；它探测的正是 HTTP 探测要访问的主机和端口。

测试矩阵
========

A. 端口关着、探测一旦发出就失败的 client：不发请求，``start_web_service`` 恰好一次；
B. 端口关着、真实的带 ``retries=3`` 的传输层：整体远小于 1.5 s 的退避（测试环境禁了
   ``httpx.AsyncClient.send``，所以直接调传输层，它的重试与退避是真的）；
C. 端口开着（真实监听）且是本服务：不启动、只问一次 ``/api/health``；
D. 端口开着但不是本服务：照常启动；
E. 预检不在事件循环线程里跑，并且探测 ``config.host`` / ``config.port``。

A、B 在旧代码上失败（旧代码会先发 HTTP 请求并等满退避）。
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from ai_intervention_agent import service_manager as sm
from ai_intervention_agent.server_config import WebUIConfig


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _listening() -> Iterator[int]:
    """一个真的在监听的端口（不需要 accept：TCP 握手由内核完成）。"""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    try:
        yield int(server.getsockname()[1])
    finally:
        server.close()


def _config(port: int) -> WebUIConfig:
    return WebUIConfig(host="127.0.0.1", port=port, max_retries=3)


class _Client:
    """记录 HTTP 请求的假 client，``health`` 是 ``/api/health`` 的 JSON 回答。"""

    is_closed = False

    def __init__(self, health: dict[str, Any] | None = None) -> None:
        self.gets: list[str] = []
        self._health = health if health is not None else {"status": "ok"}

    async def get(self, url: str, **_kwargs: Any) -> MagicMock:
        self.gets.append(url)
        response = MagicMock(status_code=200)
        response.json.return_value = self._health
        return response


class _RetryingTransportClient:
    """``get_async_client`` 那种带重试的传输层，绕开测试环境对 ``AsyncClient.send`` 的封禁。

    ``tests/conftest.py`` 让任何走 ``httpx.AsyncClient.send`` 的请求直接抛错，用真的
    ``AsyncClient`` 就看不到重试的退避了（旧代码也会在 0 s 内失败，测试形同虚设）。
    这里直接调 ``AsyncHTTPTransport.handle_async_request``：重试次数、退避、连接被拒绝时
    抛出的 ``ConnectError`` 都是 httpx / httpcore 自己的。
    """

    is_closed = False

    def __init__(self, retries: int) -> None:
        self._transport = httpx.AsyncHTTPTransport(retries=retries)

    async def get(self, url: str, **_kwargs: Any) -> httpx.Response:
        return await self._transport.handle_async_request(httpx.Request("GET", url))

    async def aclose(self) -> None:
        await self._transport.aclose()


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """把 ``start_web_service`` 换成只记录端口：这里不能真的起子进程。"""
    ports: list[int] = []
    monkeypatch.setattr(
        sm, "start_web_service", lambda config, _script_dir: ports.append(config.port)
    )
    return ports


class TestNothingListens:
    def test_no_http_request_is_sent_and_the_start_is_attempted(
        self, started: list[int]
    ) -> None:
        port = _free_port()
        client = _Client()

        asyncio.run(sm.ensure_web_ui_running(_config(port), client=client))

        assert client.gets == [], "the probe went out over HTTP to a closed port"
        assert started == [port]

    def test_the_retrying_transport_does_not_make_it_wait(
        self, started: list[int]
    ) -> None:
        port = _free_port()

        async def main() -> float:
            client = _RetryingTransportClient(retries=3)
            try:
                began = time.monotonic()
                await sm.ensure_web_ui_running(_config(port), client=client)
                return time.monotonic() - began
            finally:
                await client.aclose()

        elapsed = asyncio.run(main())

        assert started == [port]
        assert elapsed < 1.0, (
            f"took {elapsed:.2f} s: the first health probe sat in the transport's "
            "retry backoff (0 / 0.5 / 1.0 s) on a port nobody listens on"
        )


class TestSomethingListens:
    def test_our_web_ui_is_left_alone(self, started: list[int]) -> None:
        client = _Client({"status": "ok"})
        with _listening() as port:
            asyncio.run(sm.ensure_web_ui_running(_config(port), client=client))

        assert started == []
        assert client.gets == [f"http://127.0.0.1:{port}/api/health"]

    def test_a_program_that_is_not_our_web_ui_still_goes_to_the_start(
        self, started: list[int]
    ) -> None:
        client = _Client({"hello": "not a web ui"})
        with _listening() as port:
            asyncio.run(sm.ensure_web_ui_running(_config(port), client=client))

        assert started == [port]
        assert client.gets == [f"http://127.0.0.1:{port}/api/health"]


class TestThePreCheck:
    def test_it_runs_off_the_event_loop_and_asks_about_the_probe_target(
        self, monkeypatch: pytest.MonkeyPatch, started: list[int]
    ) -> None:
        calls: list[tuple[int, str, int]] = []

        def fake(host: str, port: int, *_rest: Any) -> bool:
            calls.append((threading.get_ident(), host, port))
            return False

        monkeypatch.setattr(sm, "is_web_service_running", fake)
        config = _config(_free_port())

        async def main() -> int:
            await sm.ensure_web_ui_running(config, client=_Client())
            return threading.get_ident()

        loop_thread = asyncio.run(main())

        assert len(calls) == 1
        thread, host, port = calls[0]
        assert thread != loop_thread, "the TCP pre-check blocked the event loop"
        assert (host, port) == (config.host, config.port)
        assert started == [config.port]
