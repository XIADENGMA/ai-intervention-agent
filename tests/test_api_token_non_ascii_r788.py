"""R788 · 一个不是纯 ASCII 的 API token 不能让准入检查崩掉。

问题
----
``_is_api_token_authorized`` 用 ``secrets.compare_digest(configured, presented)`` 比较两个
``str``。``compare_digest`` 对含非 ASCII 字符的 ``str`` 直接抛
``TypeError: comparing strings with non-ASCII characters is not supported``，而这个函数的
文档写着“不引发异常”。后果有两个：

1. 局域网里任何一个能连上 Web UI 的对端，带一个非 ASCII 的 ``X-API-Token`` /
   ``Authorization: Bearer`` 头，就让需要准入的端点（``/api/system/log-level``、
   ``/api/system/open-config-file`` 等）返回 500 和一页 Werkzeug 的错误 HTML，日志里
   每次一整段 traceback，而不是 403。
2. 配置里的 token 含非 ASCII 字符（例如一句中文口令；校验器只要求 16~256 个字符、去掉
   空白）时，``compare_digest`` 无论对方发什么都抛异常：这个 token 永远认证不了，每个
   带 token 的请求都是 500。

修复
----
按字节比较：配置里的 token 取 UTF-8 字节；请求头的值取 latin-1 字节（WSGI 把头的原始
字节按 latin-1 交给应用，所以这就是对端实际发送的字节，``curl -H 'X-API-Token: 口令'``
发的是 UTF-8，两边就对得上）。头里出现 latin-1 之外的字符（真实服务器给不出来，测试
客户端可以）一律算不匹配，不抛异常。

这些测试锁什么
--------------
* 路由层：非本机对端带非 ASCII 头 → 403，不是 500。
* 函数层：非 ASCII 的配置 token 能用它自己的 UTF-8 字节认证通过，错的认证不过；头里有
  latin-1 之外的字符返回 False；``Authorization: Bearer`` 同样；ASCII 行为不变（匹配 /
  不匹配 / 太短 / 没配置）。
"""

from __future__ import annotations

import pytest

from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import system as system_routes

ASCII_TOKEN = "a-very-long-ascii-token-0123456789"
UNICODE_TOKEN = "口令口令口令口令-口令口令口令口令-口令口令"


def _as_wsgi_sends_it(token: str) -> str:
    """The value the application sees for a header the client wrote as UTF-8."""
    return token.encode("utf-8").decode("latin-1")


@pytest.fixture
def ui():
    return WebFeedbackUI(prompt="r788", task_id="r788-task", port=18786)


@pytest.fixture
def authorized(ui: WebFeedbackUI, monkeypatch: pytest.MonkeyPatch):
    """``check(configured, headers)``: does ``_is_api_token_authorized`` say yes?"""

    def check(configured: str, headers: dict[str, str]) -> bool:
        monkeypatch.setattr(
            system_routes, "_get_configured_api_token", lambda: configured
        )
        with ui.app.test_request_context("/", headers=headers):
            return system_routes._is_api_token_authorized()

    return check


class TestTheRouteAnswersAnOddHeaderWith403:
    @pytest.mark.parametrize(
        "headers",
        [
            {"X-API-Token": _as_wsgi_sends_it("tökén-ünïcode")},
            {"Authorization": "Bearer " + _as_wsgi_sends_it("tökén-ünïcode")},
            {"X-API-Token": "令牌"},
            {"Authorization": "Bearer 令牌"},
        ],
    )
    def test_a_peer_with_a_non_ascii_token_header_gets_403_not_500(
        self, ui, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
    ) -> None:
        ui.network_security_config = {
            **ui.network_security_config,
            "access_control_enabled": True,
            "allowed_networks": ["192.168.0.0/16", "127.0.0.0/8"],
        }
        monkeypatch.setattr(
            system_routes, "_get_configured_api_token", lambda: ASCII_TOKEN
        )
        response = ui.app.test_client().post(
            "/api/system/log-level",
            json={"level": "WARNING"},
            headers=headers,
            environ_base={"REMOTE_ADDR": "192.168.1.9"},
        )
        assert response.status_code == 403, response.get_data(as_text=True)[:200]
        assert response.get_json()["success"] is False


class TestTheComparison:
    def test_ascii_tokens_behave_as_before(self, authorized) -> None:
        assert authorized(ASCII_TOKEN, {"X-API-Token": ASCII_TOKEN})
        assert authorized(ASCII_TOKEN, {"Authorization": f"Bearer {ASCII_TOKEN}"})
        assert not authorized(ASCII_TOKEN, {"X-API-Token": ASCII_TOKEN + "x"})
        assert not authorized(ASCII_TOKEN, {"X-API-Token": ASCII_TOKEN[:-1]})
        assert not authorized(ASCII_TOKEN, {})
        assert not authorized("", {"X-API-Token": ""})
        assert not authorized("too-short", {"X-API-Token": "too-short"})

    def test_a_token_written_in_unicode_authenticates_with_its_utf8_bytes(
        self, authorized
    ) -> None:
        sent = _as_wsgi_sends_it(UNICODE_TOKEN)
        assert authorized(UNICODE_TOKEN, {"X-API-Token": sent})
        assert authorized(UNICODE_TOKEN, {"Authorization": f"Bearer {sent}"})

    def test_a_wrong_unicode_token_is_refused_without_raising(self, authorized) -> None:
        other = _as_wsgi_sends_it(UNICODE_TOKEN[:-1] + "码")
        assert not authorized(UNICODE_TOKEN, {"X-API-Token": other})
        assert not authorized(UNICODE_TOKEN, {"X-API-Token": ASCII_TOKEN})
        assert not authorized(
            ASCII_TOKEN, {"X-API-Token": _as_wsgi_sends_it(UNICODE_TOKEN)}
        )

    @pytest.mark.parametrize("value", ["令牌", "tok\u2603en", "\U0001f511" * 20])
    def test_characters_outside_latin1_never_match_and_never_raise(
        self, authorized, value: str
    ) -> None:
        assert not authorized(ASCII_TOKEN, {"X-API-Token": value})
        assert not authorized(UNICODE_TOKEN, {"X-API-Token": value})
        assert not authorized(UNICODE_TOKEN, {"Authorization": f"Bearer {value}"})

    def test_the_utf8_text_itself_is_not_what_a_wsgi_server_hands_over(
        self, authorized
    ) -> None:
        # a real server decodes the header bytes as latin-1, so a header carrying the
        # UTF-8 bytes of the token shows up as mojibake; the raw character string
        # (which only a test client can produce) does not authenticate
        assert not authorized(UNICODE_TOKEN, {"X-API-Token": UNICODE_TOKEN})
