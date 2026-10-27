"""R893：只请求 ``http://`` 本机回环的 httpx 客户端不再装载 CA 证书包。

现象（MCP 主进程里首次创建两个连接池客户端，Python 3.13.15，M3 Max）
================================================================

``service_manager.get_async_client`` / ``get_sync_client`` 建的是模块级连接池客户端，
只访问 ``server_config.get_target_base_url`` 给出的 Web UI 地址，那个地址是写死的
``http://<主机>:<端口>``，用不到 TLS。httpx 的传输层默认 ``verify=True``，创建时就为它建一个
SSL 上下文并装载 certifi 的 CA 证书包，两个客户端各一份：

- 常驻内存约 +3.2 MiB（每个 MCP 进程，一个 IDE 窗口一个）；
- 首次创建：异步客户端 11.9 ms，同步客户端 2.9 ms（6 个全新进程的中位数）。

传输层改成 ``verify=False`` 之后：约 +1.5 MiB，异步 7.9 ms，同步 0.13 ms。这个客户端只发明文
HTTP 的回环请求，``verify`` 对它没有任何作用。

契约
====

1. 两个客户端的传输层都以 ``verify=False`` 创建；创建它们不会触发 SSL 上下文装载 CA 证书包
   （对照：``httpx.Client()`` 默认会，测试靠它确认探针还看得见装载）；
2. ``service_manager.py`` 里每一处 ``HTTPTransport`` / ``AsyncHTTPTransport`` 都是
   ``verify=False``；
3. 前提：``get_target_base_url`` 永远给 ``http://``，用到连接池客户端的两个模块
   （``service_manager.py``、``server_feedback.py``）的代码里没有 ``https://`` 字面量。哪天要让
   客户端去请求 ``https://``，这两条会先失败，提醒去掉 ``verify=False``；
4. 这两个传输层照样能请求本机的 ``http://`` 服务。（``tests/conftest.py`` 禁了 ``Client.send`` 和
   ``AsyncClient.send``，所以直接用客户端手里的传输层发请求。）
"""

from __future__ import annotations

import ast
import asyncio
import http.server
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from ai_intervention_agent import service_manager
from ai_intervention_agent.server_config import get_target_base_url

SRC = Path(__file__).resolve().parents[1] / "src" / "ai_intervention_agent"
CONFIG: Any = SimpleNamespace(max_retries=0, timeout=5.0)


@pytest.fixture
def ca_loads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """记下每一次 ``SSLContext.load_verify_locations``（httpx 装载 CA 证书包走的就是它）。"""
    calls: list[tuple[Any, ...]] = []
    original = ssl.SSLContext.load_verify_locations

    def spy(self: ssl.SSLContext, *args: Any, **kwargs: Any) -> Any:
        calls.append((args, tuple(kwargs)))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", spy)
    return calls


@pytest.fixture
def pooled(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """新建两个连接池客户端，并记下它们的传输层是怎么建的。"""
    monkeypatch.setattr(service_manager, "_async_client", None)
    monkeypatch.setattr(service_manager, "_sync_client", None)
    monkeypatch.setattr(service_manager, "_async_client_loop", None)

    kwargs: dict[str, dict[str, Any]] = {}
    transports: dict[str, Any] = {}

    def spy_on(name: str) -> None:
        original = getattr(httpx, name)

        def factory(*args: Any, **kw: Any) -> Any:
            kwargs[name] = kw
            transports[name] = original(*args, **kw)
            return transports[name]

        monkeypatch.setattr(httpx, name, factory)

    spy_on("HTTPTransport")
    spy_on("AsyncHTTPTransport")

    sync_client = service_manager.get_sync_client(CONFIG)
    async_client = service_manager.get_async_client(CONFIG)
    try:
        yield SimpleNamespace(kwargs=kwargs, transports=transports)
    finally:
        sync_client.close()
        asyncio.run(async_client.aclose())


class TestTheClientsDoNotLoadTheCaBundle:
    def test_the_probe_sees_a_default_client_load_it(
        self, ca_loads: list[tuple[Any, ...]]
    ) -> None:
        httpx.Client().close()

        assert ca_loads, "探针看不到 httpx 装载 CA 证书包了：httpx 变了，先更新这个测试"

    def test_creating_the_pooled_clients_does_not(
        self, ca_loads: list[tuple[Any, ...]], pooled: SimpleNamespace
    ) -> None:
        assert set(pooled.transports) == {"HTTPTransport", "AsyncHTTPTransport"}
        assert ca_loads == []

    def test_both_transports_are_created_with_verify_false(
        self, pooled: SimpleNamespace
    ) -> None:
        assert set(pooled.kwargs) == {"HTTPTransport", "AsyncHTTPTransport"}
        for name, kwargs in pooled.kwargs.items():
            assert kwargs.get("verify") is False, name
            assert kwargs.get("retries") == CONFIG.max_retries, name

    def test_every_transport_in_service_manager_is_verify_false(self) -> None:
        tree = ast.parse((SRC / "service_manager.py").read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"HTTPTransport", "AsyncHTTPTransport"}
        ]

        assert len(calls) == 2
        for call in calls:
            verify = {k.arg: k.value for k in call.keywords}.get("verify")
            assert isinstance(verify, ast.Constant) and verify.value is False, (
                f"line {call.lineno}: a transport of the pooled loopback clients must be "
                "created with verify=False (R893)"
            )


def _string_literals_outside_docstrings(tree: ast.AST) -> list[str]:
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


class TestTheClientsOnlyGoToPlainHttp:
    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1", "localhost", "0.0.0.0", "::", "::1", "example.internal"],
    )
    def test_the_target_base_url_is_always_http(self, host: str) -> None:
        assert get_target_base_url(host, 8080).startswith("http://")

    @pytest.mark.parametrize("name", ["service_manager.py", "server_feedback.py"])
    def test_no_https_literal_in_the_modules_that_use_the_pooled_clients(
        self, name: str
    ) -> None:
        tree = ast.parse((SRC / name).read_text(encoding="utf-8"))

        offenders = [
            s for s in _string_literals_outside_docstrings(tree) if "https://" in s
        ]

        assert offenders == [], (
            "连接池客户端的传输层是 verify=False；要请求 https:// 先去掉它（R893）"
        )


@pytest.fixture
def loopback_server() -> Iterator[str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestTheTransportsStillWork:
    def test_the_sync_transport_gets_from_a_loopback_http_server(
        self, loopback_server: str, pooled: SimpleNamespace
    ) -> None:
        transport = pooled.transports["HTTPTransport"]

        response = transport.handle_request(
            httpx.Request("GET", loopback_server + "/api/health")
        )
        response.read()
        response.close()

        assert (response.status_code, response.text) == (200, "ok")

    def test_the_async_transport_gets_from_a_loopback_http_server(
        self, loopback_server: str, pooled: SimpleNamespace
    ) -> None:
        transport = pooled.transports["AsyncHTTPTransport"]

        async def fetch() -> tuple[int, str]:
            response = await transport.handle_async_request(
                httpx.Request("GET", loopback_server + "/api/health")
            )
            await response.aread()
            await response.aclose()
            return response.status_code, response.text

        assert asyncio.run(fetch()) == (200, "ok")
