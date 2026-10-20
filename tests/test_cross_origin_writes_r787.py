"""R787 · 别的网站上的页面不能替用户向 Web UI 发写请求。

问题
----
任何网站上的页面都能让访问者的浏览器向 ``http://127.0.0.1:<端口>`` 发一个 ``POST``：
``enctype="multipart/form-data"`` 或 ``application/x-www-form-urlencoded`` 的表单不需要
CORS 预检。CORS 只决定页面读不读得到响应，不决定服务器照不照做。``/api/submit`` 恰好
接受这两种请求体，所以一个页面能在用户名下回答 agent 的问题，agent 会把它当成用户的
话照办。``/api/close`` 和 ``/api/tasks/<id>/close`` 之类不需要请求体的端点同理。

用真实的 headless Chrome 验证过：另一个来源（``http://localhost:18793``）上的页面自动
提交表单到 ``http://127.0.0.1:18792/api/submit``，修复前任务被完成，``user_input`` 是页面
写的那句话；修复后返回 403，任务不变。

规则（``web_ui_security.is_cross_origin_write``）
------------------------------------------------
安全方法（GET / HEAD / OPTIONS）不拦，唯一的例外是读后即清的 ``GET /api/feedback``（
``<img src=...>`` 就能触发，把单任务的结果清掉），它和写请求一样检查。其余方法按顺序：

1. ``Sec-Fetch-Site: same-origin`` / ``none``——浏览器自己的声明，页面改不了：放行（
   代理改写了 ``Host`` 也照样成立）。
2. ``Origin`` 和 ``Sec-Fetch-Site`` 都没有——不是浏览器（MCP 服务的 httpx、curl、VS Code
   扩展宿主里的 Node ``fetch``）：放行。
3. 有 ``Sec-Fetch-Site`` 没有 ``Origin``——浏览器说这是跨站请求，却没有身份可核对：拒绝。
4. 其余情况 ``Origin`` 必须是服务器自己的（和 ``Host`` 同一个主机:端口）或在白名单里
   （CORS 名单：本页的 ``localhost`` / ``127.0.0.1`` 来源、VS Code webview，加上
   ``external_base_url``）。``null`` 拒绝。

这些测试锁什么
--------------
* 规则本身：表驱动，含默认端口、IPv6、大小写、畸形 ``Origin``（不能抛异常）。
* 真实的 Flask 应用：从 ``url_map`` 枚举每一个改状态的路由（以后新增的也自动覆盖），
  把视图函数换成桩，证明外来页面的请求被拒绝、桩没被调用；自己来源 / 没有 ``Origin`` /
  VS Code webview / ``external_base_url`` 的请求到得了桩。桩的好处：这条测试即使失败
  也不会真的执行 ``/api/close``、``/api/system/rotate-api-token`` 之类有副作用的处理函数。
* 端到端的一条：``/api/submit`` 在外来页面下任务保持未完成，在自己的来源下完成。
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from ai_intervention_agent import web_ui_security
from ai_intervention_agent.feedback_types import FeedbackResult
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_security import is_cross_origin_write

VSCODE_WEBVIEW = re.compile(r"^vscode-webview://")
ALLOWED = ["http://localhost:8080", "http://127.0.0.1:8080", VSCODE_WEBVIEW]

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def _blocked(
    origin: str | None = None,
    fetch_site: str | None = None,
    *,
    method: str = "POST",
    host: str = "127.0.0.1:8080",
    allowed: list[Any] | None = None,
    path: str = "",
) -> bool:
    return is_cross_origin_write(
        method=method,
        origin=origin,
        fetch_site=fetch_site,
        host=host,
        allowed_origins=ALLOWED if allowed is None else allowed,
        path=path,
    )


class TestThePolicy:
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get"])
    def test_safe_methods_are_never_refused(self, method: str) -> None:
        assert not _blocked("https://evil.example", "cross-site", method=method)
        assert not _blocked("null", None, method=method)

    @pytest.mark.parametrize("method", [*WRITE_METHODS, "post"])
    def test_a_foreign_page_is_refused_on_every_write_method(self, method: str) -> None:
        assert _blocked("https://evil.example", "cross-site", method=method)

    def test_a_client_that_is_not_a_browser_sends_neither_header(self) -> None:
        # httpx / curl / Node fetch in the VS Code extension host
        assert not _blocked(None, None)
        assert not _blocked("", "")

    @pytest.mark.parametrize(
        "site", ["same-origin", "none", "SAME-ORIGIN", " same-origin "]
    )
    def test_the_browsers_own_same_origin_statement_is_enough(self, site: str) -> None:
        # a proxy rewrote Host, so the Origin does not match it; the browser says it is ours
        assert not _blocked("https://agent.example.com", site, host="127.0.0.1:8080")
        assert not _blocked(None, site)

    @pytest.mark.parametrize("site", ["cross-site", "same-site", "something-new"])
    def test_a_browser_calling_it_cross_site_without_an_origin_is_refused(
        self, site: str
    ) -> None:
        assert _blocked(None, site)
        assert _blocked("", site)

    @pytest.mark.parametrize("site", [None, "cross-site", "same-site"])
    def test_the_page_may_be_the_servers_own(self, site: str | None) -> None:
        # a plain-http LAN page sends no Sec-Fetch-Site at all; the Origin has to match Host
        assert _blocked("http://192.168.1.5:8080", site, host="127.0.0.1:8080")
        assert not _blocked("http://192.168.1.5:8080", site, host="192.168.1.5:8080")

    @pytest.mark.parametrize(
        ("origin", "host"),
        [
            ("http://example.com", "example.com"),
            ("http://example.com:80", "example.com"),
            ("http://example.com", "example.com:80"),
            ("https://example.com:443", "example.com"),
            ("http://EXAMPLE.com:8080", "example.COM:8080"),
            ("http://[::1]:8080", "[::1]:8080"),
            ("http://[::1]", "[::1]"),
            ("https://agent.example.com", "agent.example.com"),
        ],
    )
    def test_same_authority_spelled_differently_is_still_the_servers_own(
        self, origin: str, host: str
    ) -> None:
        assert not _blocked(origin, None, host=host, allowed=[])

    @pytest.mark.parametrize(
        ("origin", "host"),
        [
            ("http://example.com:8081", "example.com:8080"),
            ("http://example.com", "example.com:8080"),
            ("http://localhost:8080", "127.0.0.1:8080"),
            ("http://127.0.0.1:3000", "127.0.0.1:8080"),
            ("http://evil.example", "127.0.0.1:8080"),
            ("http://127.0.0.1:8080.evil.example", "127.0.0.1:8080"),
            ("http://[::1]:8081", "[::1]:8080"),
        ],
    )
    def test_a_different_host_or_port_is_a_different_origin(
        self, origin: str, host: str
    ) -> None:
        assert _blocked(origin, None, host=host, allowed=[])

    def test_the_allow_list_is_exact_for_strings_and_a_prefix_match_for_patterns(
        self,
    ) -> None:
        assert not _blocked("http://localhost:8080", "cross-site")
        assert not _blocked("http://127.0.0.1:8080", "cross-site")
        assert not _blocked("vscode-webview://abc-123", "cross-site")
        # a neighbouring port of an allowed host is not allowed
        assert _blocked("http://localhost:8081", "cross-site")
        assert _blocked("http://127.0.0.1:8081", "cross-site")
        # the VS Code pattern does not match a look-alike scheme
        assert _blocked("evil-vscode-webview://abc", "cross-site")
        assert _blocked("https://vscode-webview://abc", "cross-site")

    @pytest.mark.parametrize(
        "origin",
        [
            "null",
            "NULL",
            "file://",
            "chrome-extension://abcdefgh",
            "about:blank",
            "javascript:alert(1)",
            "ftp://127.0.0.1:8080",
            "//evil.example",
            "evil.example",
            "http://",
            "http://[::1",
            "http://host:99999",
            "http://host:notaport",
            "\x00",
        ],
    )
    def test_nothing_that_is_not_an_http_origin_is_accepted_and_nothing_raises(
        self, origin: str
    ) -> None:
        assert _blocked(origin, "cross-site", allowed=[])
        assert _blocked(origin, None, allowed=[])

    def test_an_empty_allow_list_still_lets_the_servers_own_origin_through(
        self,
    ) -> None:
        assert not _blocked("http://127.0.0.1:8080", None, allowed=[])


def _write_rules(ui: WebFeedbackUI) -> list[tuple[Any, str]]:
    """(rule, concrete URL) of every route that can change state."""
    found = []
    for rule in ui.app.url_map.iter_rules():
        methods = (rule.methods or set()) & set(WRITE_METHODS)
        if not methods or rule.endpoint == "static":
            continue
        url = re.sub(r"<[^>]+>", "t-1", rule.rule)
        for method in sorted(methods):
            found.append(((rule.endpoint, method), url))
    return found


def stub_write_views(ui: WebFeedbackUI) -> list[str]:
    """Replace every state-changing view by a recorder; returns the list it appends to."""
    calls: list[str] = []

    def make_stub(endpoint: str):
        def stub(**_kwargs: Any):
            calls.append(endpoint)
            return {"reached": endpoint}, 200

        return stub

    for (endpoint, _method), _url in _write_rules(ui):
        ui.app.view_functions[endpoint] = make_stub(endpoint)
    return calls


@pytest.fixture
def ui_with_stubs():
    """A real Web UI whose state-changing views are replaced by recording stubs."""
    ui = WebFeedbackUI(prompt="r787", task_id="r787-task", port=18787)
    return ui, stub_write_views(ui)


class TestEveryStateChangingRoute:
    def test_the_enumeration_sees_the_routes_that_matter(self, ui_with_stubs) -> None:
        ui, _calls = ui_with_stubs
        urls = {url for _key, url in _write_rules(ui)}
        for needed in (
            "/api/submit",
            "/api/close",
            "/api/tasks",
            "/api/tasks/t-1/close",
            "/api/tasks/t-1/submit",
            "/api/system/open-config-file",
            "/api/system/rotate-api-token",
            "/api/update-notification-config",
        ):
            assert needed in urls, f"{needed} is not enumerated: {sorted(urls)}"
        assert len(urls) >= 15

    def test_a_foreign_page_never_reaches_a_handler(self, ui_with_stubs) -> None:
        ui, calls = ui_with_stubs
        client = ui.app.test_client()
        for (_endpoint, method), url in _write_rules(ui):
            response = client.open(
                url,
                method=method,
                headers={
                    "Origin": "https://evil.example",
                    "Sec-Fetch-Site": "cross-site",
                },
            )
            assert response.status_code == 403, f"{method} {url}"
            body = response.get_json()
            assert body["success"] is False
            assert body["error"] == "cross_origin_write_blocked"
        assert calls == []

    @pytest.mark.parametrize(
        "headers",
        [
            {"Origin": "https://evil.example"},
            {"Origin": "null"},
            {"Origin": "null", "Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
            {"Origin": "http://localhost:3000", "Sec-Fetch-Site": "same-site"},
        ],
    )
    def test_every_way_a_browser_can_say_it_is_not_us_is_refused(
        self, ui_with_stubs, headers: dict[str, str]
    ) -> None:
        ui, calls = ui_with_stubs
        client = ui.app.test_client()
        response = client.post("/api/submit", headers=headers)
        assert response.status_code == 403
        assert calls == []

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Origin": "http://localhost"},
            {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"},
            {"Sec-Fetch-Site": "same-origin"},
            {"Origin": "vscode-webview://0123abcd", "Sec-Fetch-Site": "cross-site"},
            {"Origin": "http://localhost:18787", "Sec-Fetch-Site": "cross-site"},
            {"Origin": "http://127.0.0.1:18787", "Sec-Fetch-Site": "cross-site"},
        ],
    )
    def test_the_web_uis_own_pages_and_non_browser_clients_still_get_through(
        self, ui_with_stubs, headers: dict[str, str]
    ) -> None:
        ui, calls = ui_with_stubs
        client = ui.app.test_client()
        for (_endpoint, method), url in _write_rules(ui):
            response = client.open(url, method=method, headers=headers)
            assert response.status_code == 200, f"{method} {url} {headers}"
        assert len(calls) == len(_write_rules(ui))

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_reading_is_not_the_gates_business(self, method: str) -> None:
        ui = WebFeedbackUI(prompt="r787 read", port=18788)
        client = ui.app.test_client()
        response = client.open(
            "/api/health",
            method=method,
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code != 403

    def test_the_cors_allow_list_is_the_one_the_gate_uses(self) -> None:
        ui = WebFeedbackUI(prompt="r787 cors", port=18789)
        entries = ui._allowed_write_origins()
        strings = {entry for entry in entries if isinstance(entry, str)}
        patterns = [entry for entry in entries if isinstance(entry, re.Pattern)]
        assert {"http://localhost:18789", "http://127.0.0.1:18789"} <= strings
        assert any(pattern.match("vscode-webview://abc") for pattern in patterns)


class TestTheOneGetThatClearsState:
    """``GET /api/feedback`` hands out the single-task result once and forgets it."""

    PATH = "/api/feedback"

    @pytest.mark.parametrize("method", ["GET", "HEAD", "get"])
    def test_the_policy_treats_it_as_a_write(self, method: str) -> None:
        assert _blocked(
            "https://evil.example", "cross-site", method=method, path=self.PATH
        )
        # an <img src=...> or a no-cors fetch carries no Origin, only Sec-Fetch-Site
        assert _blocked(None, "cross-site", method=method, path=self.PATH)
        assert _blocked(None, "same-site", method=method, path=self.PATH)

    @pytest.mark.parametrize("method", ["GET", "HEAD"])
    def test_the_users_own_requests_and_scripts_still_read_it(
        self, method: str
    ) -> None:
        # typed into the address bar, fetched by the Web UI's own page, curl / httpx
        assert not _blocked(None, "none", method=method, path=self.PATH)
        assert not _blocked(None, "same-origin", method=method, path=self.PATH)
        assert not _blocked(None, None, method=method, path=self.PATH)
        assert not _blocked(
            "http://127.0.0.1:8080", "cross-site", method=method, path=self.PATH
        )

    def test_a_preflight_is_never_refused(self) -> None:
        assert not _blocked(
            "https://evil.example", "cross-site", method="OPTIONS", path=self.PATH
        )

    @pytest.mark.parametrize("path", ["/api/health", "/api/tasks", "/api/config", "/"])
    def test_every_other_get_stays_unrestricted(self, path: str) -> None:
        assert not _blocked(
            "https://evil.example", "cross-site", method="GET", path=path
        )

    def test_the_listed_paths_are_real_get_routes(self) -> None:
        # a renamed route would silently drop out of the protection
        ui = WebFeedbackUI(prompt="r787 paths", port=18794)
        get_rules = {
            rule.rule
            for rule in ui.app.url_map.iter_rules()
            if "GET" in (rule.methods or set())
        }
        assert get_rules >= web_ui_security._STATE_CONSUMING_GET_PATHS

    def test_a_foreign_page_cannot_throw_the_answer_away(self) -> None:
        ui = WebFeedbackUI(prompt="r787 feedback", port=18794)
        answer: FeedbackResult = {
            "user_input": "keep me",
            "selected_options": [],
            "images": [],
        }
        ui.feedback_result = answer.copy()
        client = ui.app.test_client()
        for method in ("get", "head"):
            response = getattr(client, method)(
                self.PATH, headers={"Sec-Fetch-Site": "cross-site"}
            )
            assert response.status_code == 403, method
        assert ui.feedback_result == answer

        # the same read from the Web UI's own page / a script still works, once
        response = client.get(self.PATH, headers={"Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 200
        assert response.get_json()["feedback"] == answer
        assert ui.feedback_result is None
        assert client.get(self.PATH).get_json()["status"] == "waiting"


class TestBehindAReverseProxy:
    def test_https_proxy_that_rewrites_host_needs_no_configuration(
        self, ui_with_stubs
    ) -> None:
        # nginx's default: Host becomes 127.0.0.1:<port>; the browser's own header says same-origin
        ui, calls = ui_with_stubs
        client = ui.app.test_client()
        response = client.post(
            "/api/submit",
            headers={
                "Origin": "https://agent.example.com",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        assert response.status_code == 200
        assert len(calls) == 1

    def test_plain_http_proxy_that_rewrites_host_needs_external_base_url(self) -> None:
        # a plain-http page gets no Sec-Fetch-Site, so only Origin can identify it
        origin = "http://agent.home:8080"
        without = WebFeedbackUI(prompt="r787 proxy", port=18790)
        with_url = WebFeedbackUI(
            prompt="r787 proxy", port=18790, external_base_url=origin
        )
        for ui, expected in ((without, 403), (with_url, 200)):
            stub_write_views(ui)
            response = ui.app.test_client().post(
                "/api/submit", headers={"Origin": origin}
            )
            assert response.status_code == expected

    def test_the_live_setting_counts_too_which_is_what_the_wsgi_factory_has(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeConfig:
            @staticmethod
            def get_section(name: str) -> dict[str, Any]:
                assert name == "web_ui"
                return {"external_base_url": "https://agent.example.com"}

        monkeypatch.setattr(web_ui_security, "get_config", lambda: FakeConfig())
        ui = WebFeedbackUI(prompt="r787 live", port=18791)
        entries = ui._allowed_write_origins()
        assert "https://agent.example.com" in entries

    def test_a_broken_config_does_not_make_the_gate_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom() -> Any:
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(web_ui_security, "get_config", boom)
        ui = WebFeedbackUI(prompt="r787 broken", port=18792)
        assert isinstance(ui._allowed_write_origins(), list)


class TestTheAnswerToTheAgent:
    """The thing the attack is after: who gets to answer a pending task."""

    @pytest.fixture
    def ui_and_task(self):
        from ai_intervention_agent.server import get_task_queue

        ui = WebFeedbackUI(prompt="r787 e2e", port=18793)
        queue = get_task_queue()
        queue.remove_task("r787-e2e")
        assert queue.add_task(
            task_id="r787-e2e",
            prompt="r787 e2e",
            predefined_options=[],
            auto_resubmit_timeout=0,
        )
        yield ui, queue
        queue.remove_task("r787-e2e")

    def _status(self, queue) -> tuple[str, object]:
        task = queue.get_task("r787-e2e")
        assert task is not None
        return task.status, task.result

    def test_a_foreign_form_post_does_not_answer_the_task(self, ui_and_task) -> None:
        ui, queue = ui_and_task
        client = ui.app.test_client()
        response = client.post(
            "/api/submit",
            data={"task_id": "r787-e2e", "feedback_text": "INJECTED-BY-EVIL-SITE"},
            headers={"Origin": "http://localhost:9999", "Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code == 403
        status, result = self._status(queue)
        assert status != "completed"
        assert result is None

    def test_the_users_own_page_does_answer_it(self, ui_and_task) -> None:
        ui, queue = ui_and_task
        client = ui.app.test_client()
        response = client.post(
            "/api/submit",
            data={"task_id": "r787-e2e", "feedback_text": "the user's own answer"},
            headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        status, result = self._status(queue)
        assert status == "completed"
        assert "the user's own answer" in str(result)

    def test_a_client_that_is_not_a_browser_does_answer_it(self, ui_and_task) -> None:
        ui, queue = ui_and_task
        client = ui.app.test_client()
        response = client.post(
            "/api/submit",
            data={"task_id": "r787-e2e", "feedback_text": "answer from a script"},
        )
        assert response.status_code == 200
        assert self._status(queue)[0] == "completed"
