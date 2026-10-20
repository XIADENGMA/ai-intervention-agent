"""R782：MCP 服务访问本机 Web UI 的请求不该读环境变量里的代理。

现象（真实进程，假代理实测）
============================

很多人的 shell 里长期 ``export HTTP_PROXY=http://127.0.0.1:7890``（macOS 上开着系统代理时，
httpx 也会从系统设置里读到它）。httpx 默认 ``trust_env=True``，会把环境代理挂到每个请求上，
而且**不会**自动绕过 ``localhost``，要靠用户另配 ``NO_PROXY``。

MCP 服务用的两个常驻客户端（``get_sync_client`` / ``get_async_client``）显式传了
``transport=``，httpx 在这种情况下不读环境代理，所以任务轮询、SSE、健康检查都是直连。但
``aiia://server/info`` 里两个诊断请求（``/api/system/sse-stats``、``/api/system/recent-logs``）
用的是模块级的 ``httpx.get(...)``，每次新建一个默认客户端，于是——

* 起一个假代理监听 18797，设 ``HTTP_PROXY=http://127.0.0.1:18797``，调
  ``_fetch_sse_stats_cached("127.0.0.1", 18792)``，假代理收到
  ``GET http://127.0.0.1:18792/api/system/sse-stats HTTP/1.1``，诊断里写进去的是代理回的内容，
  不是本机 Web UI 的；同一进程里常驻客户端的 ``/api/health`` 却直连、没经过代理；
* 代理在别的机器上（公司网络）时，请求里的 ``127.0.0.1`` 指的是代理那台机器，拿到的是别人的
  Web UI 或一个错误。

这条路径只在读 ``aiia://server/info`` 时才走，所以平时没人发现。

修复
====

两个诊断请求都显式传 ``trust_env=False``。两个常驻客户端和 Bark 客户端也显式写上
``trust_env=False``：它们现在靠"传了 transport 就不读环境代理"这条 httpx 的实现细节才直连，
写明以后不依赖它。规则统一为：包里每一处 httpx 请求或客户端都显式声明 ``trust_env=False``。

测试矩阵
========

A. 两个诊断请求发出时，客户端的 ``trust_env`` 是 ``False``（环境里设着代理）；
B. 两个常驻客户端的 ``trust_env`` 是 ``False``；
C. 源码扫描：包里每个 ``httpx.get/post/.../Client/AsyncClient`` 调用都带 ``trust_env=False``，
   并且扫描到的调用点不少于已知的 5 个（防止规则空转），再加一条规则自检。

A、B、C 在旧代码上失败。
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

import ai_intervention_agent.server as server
import ai_intervention_agent.service_manager as sm
from ai_intervention_agent.server_config import WebUIConfig

PACKAGE = Path(server.__file__).resolve().parent

REQUEST_FUNCTIONS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "request",
    "stream",
}
CLIENT_CLASSES = {"Client", "AsyncClient"}


@pytest.fixture
def proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:18797")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


class TestTheDiagnosticRequests:
    @pytest.mark.parametrize(
        ("fetch", "payload"),
        [
            (
                lambda: server._fetch_sse_stats_cached("127.0.0.1", 18792),
                {"success": True, "emit_total": 7},
            ),
            (
                lambda: server._fetch_recent_logs_cached("127.0.0.1", 18792, limit=3),
                {"success": True, "entries": []},
            ),
        ],
        ids=["sse-stats", "recent-logs"],
    )
    def test_they_do_not_read_the_proxy_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
        proxy_environment: None,
        fetch: Callable[[], dict[str, object]],
        payload: dict[str, Any],
    ) -> None:
        trusted: list[bool] = []

        def fake_send(
            self: httpx.Client, request: httpx.Request, *_a: Any, **_k: Any
        ) -> httpx.Response:
            trusted.append(self.trust_env)
            return httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx.Client, "send", fake_send)
        server.reset_sse_stats_cache_for_testing()
        server.reset_recent_logs_cache_for_testing()

        result = fetch()

        assert "error" not in result
        assert trusted == [False]


class TestThePooledClients:
    def test_the_sync_client(
        self, monkeypatch: pytest.MonkeyPatch, proxy_environment: None
    ) -> None:
        monkeypatch.setattr(sm, "_sync_client", None)

        client = sm.get_sync_client(WebUIConfig(host="127.0.0.1", port=18792))
        try:
            assert client.trust_env is False
        finally:
            client.close()

    def test_the_async_client(
        self, monkeypatch: pytest.MonkeyPatch, proxy_environment: None
    ) -> None:
        monkeypatch.setattr(sm, "_async_client", None)
        monkeypatch.setattr(sm, "_async_client_loop", None)

        async def main() -> bool:
            client = sm.get_async_client(WebUIConfig(host="127.0.0.1", port=18792))
            try:
                return client.trust_env
            finally:
                await client.aclose()

        assert asyncio.run(main()) is False


def _undeclared_http_sites(source: str) -> tuple[list[int], list[int]]:
    """返回 ``(所有 httpx 调用点的行号, 其中没显式写 trust_env=False 的行号)``。"""
    sites: list[int] = []
    undeclared: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "httpx"
            and func.attr in REQUEST_FUNCTIONS | CLIENT_CLASSES
        ):
            continue
        sites.append(node.lineno)
        declared = any(
            keyword.arg == "trust_env"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in node.keywords
        )
        if not declared:
            undeclared.append(node.lineno)
    return sites, undeclared


class TestEveryHttpxCallDeclaresItsTrust:
    def test_the_package(self) -> None:
        total = 0
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            sites, undeclared = _undeclared_http_sites(path.read_text(encoding="utf-8"))
            total += len(sites)
            offenders += [f"{path.relative_to(PACKAGE)}:{line}" for line in undeclared]

        assert total >= 5, "扫描规则没找到已知的 5 个 httpx 调用点，规则可能空转了"
        assert not offenders, (
            "这些 httpx 调用没有显式写 trust_env=False（本机 Web UI 的请求不该读环境代理）："
            f"{offenders}"
        )

    def test_the_scan_rule_catches_an_undeclared_call(self) -> None:
        source = (
            "import httpx\n"
            "httpx.get(url)\n"
            "httpx.Client(timeout=1)\n"
            "httpx.post(url, trust_env=True)\n"
            "httpx.get(url, trust_env=False)\n"
            "httpx.AsyncClient(trust_env=False)\n"
            "other.get(url)\n"
        )

        sites, undeclared = _undeclared_http_sites(source)

        assert sites == [2, 3, 4, 5, 6]
        assert undeclared == [2, 3, 4]
