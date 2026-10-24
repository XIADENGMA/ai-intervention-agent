"""R781：Web UI 绑定在 IPv6 字面量地址上时，MCP 服务也得能找到它。

现象（真实 stdio MCP 服务 + 真实 Web UI 子进程，端到端复现）
============================================================

``network_security.bind_interface = "::1"``（或别的 IPv6 地址）是被接受的配置：
``validate_bind_interface`` 明确放行 IPv4/IPv6 地址，``_is_port_available`` 按 ``:`` 选
IPv6 套接字，Web UI 一侧还专门给方括号形式的 IPv6 受信主机做了兼容（R729）；Web UI
子进程也确实起来了（``Running on http://[::1]:18792``）。

但 MCP 服务这一侧所有访问 Web UI 的 URL 都写成 ``http://{host}:{port}/...``。IPv6
字面量放进 URL 必须加方括号，``http://::1:18792/api/health`` 不是合法 URL：httpx 报
``InvalidURL: Invalid port: ':1:18792'``，日志里是"健康检查时出现未知错误"，
``interactive_feedback`` 等满 15 秒后报"Web 服务启动超时，请检查端口 18792 是否被占用"——
端口一点问题都没有。也就是说这个配置值被接受，却永远用不起来，错误信息还把人引向别处。

同一个缺口还让 ``resolve_external_base_url`` 在 mDNS 关闭、绑定非回环 IPv6 地址时返回
``http://2001:db8::1:8080``（Bark 点击链接是乱的），绑定 ``::1`` 时返回的
``http://::1:8080`` 不被识别为回环地址，没有被过滤掉。

修复
====

``server_config`` 新增两个小函数：

* ``format_url_host(host)``：IPv6 字面量加方括号（``::1`` → ``[::1]``），已经带方括号的、
  IPv4 和主机名原样返回；
* ``get_target_base_url(host, port)``：``http://<可直连主机>:<port>``，可直连主机沿用
  ``get_target_host``（``0.0.0.0`` / ``::`` → ``localhost``），再过 ``format_url_host``。

MCP 一侧所有拼 Web UI 基地址的地方（任务轮询、SSE、关闭任务、建任务、健康检查、更新内容、
``aiia://server/info`` 的诊断请求、外部基地址）都改走它们；``get_target_host`` 本身不变
（``is_web_service_running`` 要把它交给 ``getaddrinfo``，不能带方括号）。

契约
====

1. IPv4、主机名、通配地址（``0.0.0.0`` / ``::`` → ``localhost``）得到的 URL 和以前一字不差；
2. IPv6 字面量得到带方括号的、httpx 能解析的 URL；
3. 已经带方括号的输入不会被再包一层；
4. 上面列出的每一个 URL 构造点都满足 1–3。

测试矩阵
========

A. ``format_url_host`` / ``get_target_base_url`` 的输入输出表（含 httpx 能解析）；
B. 十一处构造点：任务轮询、SSE、关闭任务、建任务（含已弃用的 ``launch_feedback_ui``）、
   同步和异步健康检查、更新内容、``server`` 的两个诊断请求、外部基地址（及其回环过滤）。

B 中 IPv6 的用例在旧代码上失败，IPv4 的对照用例在新旧代码上都通过。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

import ai_intervention_agent.server as server_module
import ai_intervention_agent.server_feedback as server
import ai_intervention_agent.service_manager as sm
from ai_intervention_agent.server_config import (
    WebUIConfig,
    format_url_host,
    get_target_base_url,
    resolve_external_base_url,
)
from tests.test_notification_off_event_loop_r776 import TASK_ID, _Harness
from tests.test_task_id_url_safe_r780 import _UrlClient

PORT = 18998


class TestTheHelpers:
    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("127.0.0.1", "127.0.0.1"),
            ("localhost", "localhost"),
            ("example.com", "example.com"),
            ("192.168.1.50", "192.168.1.50"),
            ("::1", "[::1]"),
            ("2001:db8::1", "[2001:db8::1]"),
            ("fe80::1", "[fe80::1]"),
            ("[::1]", "[::1]"),
            ("[2001:db8::1]", "[2001:db8::1]"),
        ],
    )
    def test_format_url_host(self, host: str, expected: str) -> None:
        assert format_url_host(host) == expected

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("127.0.0.1", f"http://127.0.0.1:{PORT}"),
            ("localhost", f"http://localhost:{PORT}"),
            ("0.0.0.0", f"http://localhost:{PORT}"),
            ("::", f"http://localhost:{PORT}"),
            ("192.168.1.50", f"http://192.168.1.50:{PORT}"),
            ("example.com", f"http://example.com:{PORT}"),
            ("::1", f"http://[::1]:{PORT}"),
            ("2001:db8::1", f"http://[2001:db8::1]:{PORT}"),
            ("[::1]", f"http://[::1]:{PORT}"),
        ],
    )
    def test_get_target_base_url(self, host: str, expected: str) -> None:
        assert get_target_base_url(host, PORT) == expected

    @pytest.mark.parametrize("host", ["::1", "2001:db8::1", "fe80::1", "[::1]"])
    def test_an_ipv6_base_url_is_a_valid_url(self, host: str) -> None:
        url = httpx.URL(get_target_base_url(host, PORT))

        assert url.port == PORT
        assert url.host == host.strip("[]")


def _config(host: str) -> WebUIConfig:
    return WebUIConfig(host=host, port=PORT)


class _RecordingClient(_UrlClient):
    """在 ``_UrlClient`` 之上再记下 SSE 的请求（随后让它失败，只走轮询）。

    ``wait_for_task_completion`` 先建 SSE 任务再建轮询任务，主协程一让出控制权，SSE 任务
    就先跑到 ``stream(...)``，所以这条记录是确定的，不依赖时序。
    """

    def __init__(self) -> None:
        super().__init__()
        self.streams: list[str] = []

    def stream(self, method: str, url: str, **_kwargs: Any) -> Any:
        self.streams.append(f"{method} {url}")
        raise RuntimeError("SSE is not part of this test")


class TestTaskUrls:
    @pytest.mark.parametrize(
        ("host", "base"),
        [("127.0.0.1", f"http://127.0.0.1:{PORT}"), ("::1", f"http://[::1]:{PORT}")],
    )
    def test_the_poll_url_and_the_sse_url(
        self, monkeypatch: pytest.MonkeyPatch, host: str, base: str
    ) -> None:
        client = _RecordingClient()
        monkeypatch.setattr(sm, "get_web_ui_config", lambda: (_config(host), 30))
        monkeypatch.setattr(sm, "get_async_client", lambda _config: client)

        async def main() -> Any:
            return await server.wait_for_task_completion(TASK_ID, timeout=30)

        assert asyncio.run(main()) == {"interactive_feedback": "ok"}

        assert client.gets[0] == f"{base}/api/tasks/{TASK_ID}"
        assert client.streams == [f"GET {base}/api/events"]

    @pytest.mark.parametrize(
        ("host", "base"),
        [("127.0.0.1", f"http://127.0.0.1:{PORT}"), ("::1", f"http://[::1]:{PORT}")],
    )
    def test_the_close_url(self, host: str, base: str) -> None:
        client = _UrlClient()

        async def main() -> None:
            await server._close_orphan_task_best_effort(
                TASK_ID, host, PORT, client=client
            )

        asyncio.run(main())

        assert client.posts == [f"{base}/api/tasks/{TASK_ID}/close"]

    @pytest.mark.parametrize(
        ("host", "base"),
        [("127.0.0.1", f"http://127.0.0.1:{PORT}"), ("::1", f"http://[::1]:{PORT}")],
    )
    def test_the_create_url(
        self, monkeypatch: pytest.MonkeyPatch, host: str, base: str
    ) -> None:
        harness = _Harness(monkeypatch, _config(host))

        async def main() -> list[Any]:
            return await harness.call()

        asyncio.run(main())

        assert harness.waited == [TASK_ID]
        assert harness.client.posts[0] == f"{base}/api/tasks"


class _SyncClient:
    def __init__(self, post_status: int = 200) -> None:
        self.gets: list[str] = []
        self.posts: list[str] = []
        self._post_status = post_status

    def get(self, url: str, **_kwargs: Any) -> MagicMock:
        self.gets.append(url)
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "ok"}
        return response

    def post(self, url: str, **_kwargs: Any) -> MagicMock:
        self.posts.append(url)
        response = MagicMock(status_code=self._post_status)
        response.json.return_value = {"status": "success"}
        return response


class TestServiceManagerUrls:
    @pytest.mark.parametrize(
        ("host", "base"),
        [("127.0.0.1", f"http://127.0.0.1:{PORT}"), ("::1", f"http://[::1]:{PORT}")],
    )
    def test_the_sync_health_check(
        self, monkeypatch: pytest.MonkeyPatch, host: str, base: str
    ) -> None:
        client = _SyncClient()
        monkeypatch.setattr(sm, "is_web_service_running", lambda *_a, **_k: True)
        monkeypatch.setattr(sm, "create_http_session", lambda _config: client)

        assert sm.health_check_service(_config(host)) is True

        assert client.gets == [f"{base}/api/health"]

    @pytest.mark.parametrize(
        ("host", "base"),
        [("127.0.0.1", f"http://127.0.0.1:{PORT}"), ("::1", f"http://[::1]:{PORT}")],
    )
    def test_the_async_health_check(self, host: str, base: str) -> None:
        asked: list[str] = []

        class Client:
            is_closed = False

            async def get(self, url: str, **_kwargs: Any) -> MagicMock:
                asked.append(url)
                response = MagicMock(status_code=200)
                response.json.return_value = {"status": "ok"}
                return response

        async def main() -> None:
            await sm.ensure_web_ui_running(_config(host), client=Client())

        asyncio.run(main())

        assert asked == [f"{base}/api/health"]

    @pytest.mark.parametrize(
        ("host", "base"),
        [("127.0.0.1", f"http://127.0.0.1:{PORT}"), ("::1", f"http://[::1]:{PORT}")],
    )
    def test_the_content_update(
        self, monkeypatch: pytest.MonkeyPatch, host: str, base: str
    ) -> None:
        client = _SyncClient()
        monkeypatch.setattr(sm, "create_http_session", lambda _config: client)

        sm.update_web_content("hello", None, TASK_ID, 0, _config(host))

        assert client.posts == [f"{base}/api/update"]


class TestTheDeprecatedLauncher:
    @pytest.mark.parametrize(
        ("host", "base"),
        [("127.0.0.1", f"http://127.0.0.1:{PORT}"), ("::1", f"http://[::1]:{PORT}")],
    )
    def test_the_create_url(
        self, monkeypatch: pytest.MonkeyPatch, host: str, base: str
    ) -> None:
        client = _SyncClient(post_status=500)
        monkeypatch.setattr(sm, "get_web_ui_config", lambda: (_config(host), 120))
        monkeypatch.setattr(sm, "get_sync_client", lambda _config: client)
        monkeypatch.setattr(server.asyncio, "run", lambda coroutine: coroutine.close())
        monkeypatch.setattr(server.server_config, "_generate_task_id", lambda: TASK_ID)

        assert "error" in server.launch_feedback_ui("hello")

        assert client.posts == [f"{base}/api/tasks"]


class TestDiagnosticRequests:
    @pytest.mark.parametrize(
        ("host", "base"),
        [("127.0.0.1", f"http://127.0.0.1:{PORT}"), ("::1", f"http://[::1]:{PORT}")],
    )
    def test_sse_stats_and_recent_logs(
        self, monkeypatch: pytest.MonkeyPatch, host: str, base: str
    ) -> None:
        asked: list[str] = []

        def fake_get(url: str, **_kwargs: Any) -> MagicMock:
            asked.append(url)
            response = MagicMock(status_code=200)
            response.json.return_value = {}
            return response

        monkeypatch.setattr(httpx, "get", fake_get)
        server_module.reset_sse_stats_cache_for_testing()
        server_module.reset_recent_logs_cache_for_testing()

        server_module._fetch_sse_stats_cached(host, PORT)
        server_module._fetch_recent_logs_cached(host, PORT, limit=5)

        assert asked == [
            f"{base}/api/system/sse-stats",
            f"{base}/api/system/recent-logs?limit=5",
        ]


class TestTheExternalBaseUrl:
    @staticmethod
    def _without_mdns() -> Any:
        sections: dict[str, dict[str, Any]] = {
            "web_ui": {},
            "mdns": {"enabled": False, "hostname": "ai.local"},
            "network_security": {},
        }
        config = MagicMock()
        config.get_section.side_effect = lambda name: sections.get(name, {})
        return patch(
            "ai_intervention_agent.server_config.get_config", return_value=config
        )

    def test_a_routable_ipv6_address_is_bracketed(self) -> None:
        with self._without_mdns():
            assert (
                resolve_external_base_url(_config("2001:db8::1"))
                == f"http://[2001:db8::1]:{PORT}"
            )

    def test_the_ipv6_loopback_is_recognised_and_filtered_for_external_use(
        self,
    ) -> None:
        with self._without_mdns():
            assert resolve_external_base_url(_config("::1")) == f"http://[::1]:{PORT}"
            assert (
                resolve_external_base_url(_config("::1"), for_external_use=True) == ""
            )

    def test_ipv4_is_unchanged(self) -> None:
        with self._without_mdns():
            assert (
                resolve_external_base_url(_config("192.168.1.50"))
                == f"http://192.168.1.50:{PORT}"
            )
