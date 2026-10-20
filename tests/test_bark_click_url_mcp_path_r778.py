"""R778：Bark 推送里的点击跳转链接，真实的 MCP 工具路径上从来没有带上。

现象（真实 stdio MCP 服务 + 真实 Web UI + 本地 Bark 替身，端到端复现）
======================================================================

配置 ``bark_action = "url"`` 和 ``web_ui.external_base_url = "http://192.168.1.50:18792"``
（文档里的标准用法），让 agent 调一次 ``interactive_feedback``：Bark 收到的 JSON 里
没有 ``url`` 字段，服务端日志里是

    WARNING bark_url_template 渲染结果不是合法 URL，已忽略: '/?task_id=e2e-...'

手机上点通知什么也不会发生。

原因：Bark 渠道渲染 ``bark_url_template``（默认 ``{base_url}/?task_id={task_id}``）时，
``{base_url}`` 取自事件的 ``metadata["base_url"]``。``launch_feedback_ui`` 会用
``server_config.resolve_external_base_url(config, for_external_use=True)`` 解析并放进
metadata，``interactive_feedback``（MCP 工具真正走的路径）只放了 ``task_id`` 和
``source``，``{base_url}`` 渲染成空串，``/?task_id=...`` 不是 http(s) 链接，被丢掉。
设置面板的"测试 Bark"按钮走的是另一条路由（它自己带 ``base_url``），所以面板里一切
正常，只有真实推送没有链接。含 ``{base_url}`` 的模板都受影响，包括默认模板；
``shortcuts://`` 这类不含 ``{base_url}`` 的深链不受影响。

修复：``_dispatch_new_task_notification`` 与 ``launch_feedback_ui`` 一样解析
``base_url`` 并放进 metadata。解析出来是回环地址（手机够不着）或解析失败时不带，
Bark 渠道照旧记下"没有可用链接"，通知本身照发。

测试矩阵
========

A. ``external_base_url`` 配了：metadata 带 ``base_url``；
B. 只有回环地址：metadata 不带 ``base_url``（其余字段不变）；
C. 解析抛异常：只丢链接，通知照发，调用照常拿到答复；
D. 线上形态：真实的 ``NotificationManager`` + ``BarkNotificationProvider``，只把最末端
   的 HTTP session 换成记录器（测试套件禁止任何真实 httpx 请求），发出去的 JSON 里
   ``url`` 是 ``<external_base_url>/?task_id=<任务 id>``；没配 ``external_base_url`` 时
   没有 ``url`` 字段，推送本身照发。

E. 模板里有 ``{base_url}`` 而 base_url 为空（回环地址又没配 ``external_base_url``）时，
   Bark 渠道的 WARNING 直接说出原因和该配什么，而不是只说"渲染结果不是合法 URL"；
   模板里没有 ``{base_url}`` 时不加这句。

A、D 在旧代码上失败；E 的第一条在旧代码上失败。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import ai_intervention_agent.server_feedback as server
from ai_intervention_agent.notification_manager import (
    NotificationEvent,
    NotificationManager,
)
from ai_intervention_agent.notification_models import NotificationType
from ai_intervention_agent.notification_providers import BarkNotificationProvider
from ai_intervention_agent.server_config import WebUIConfig
from tests.test_notification_off_event_loop_r776 import TASK_ID, _Harness
from tests.test_notification_providers import create_event

EXTERNAL = "http://192.168.1.50:18998"


def _run(harness: _Harness) -> list[Any]:
    async def main() -> list[Any]:
        return await harness.call()

    return asyncio.run(main())


def _metadata(harness: _Harness) -> dict[str, Any]:
    harness.notifier.send_notification.assert_called_once()
    return harness.notifier.send_notification.call_args.kwargs["metadata"]


class TestTheMetadataTheNotificationGets:
    def test_a_configured_external_base_url_is_passed_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = _Harness(
            monkeypatch,
            WebUIConfig(host="127.0.0.1", port=18998, external_base_url=EXTERNAL),
        )

        _run(harness)

        assert _metadata(harness) == {
            "task_id": TASK_ID,
            "source": "interactive_feedback",
            "base_url": EXTERNAL,
        }

    def test_a_loopback_only_setup_passes_no_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = _Harness(monkeypatch)

        _run(harness)

        assert _metadata(harness) == {
            "task_id": TASK_ID,
            "source": "interactive_feedback",
        }

    def test_a_failing_resolution_only_drops_the_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = _Harness(
            monkeypatch,
            WebUIConfig(host="127.0.0.1", port=18998, external_base_url=EXTERNAL),
        )

        def broken(*_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("cannot resolve")

        monkeypatch.setattr(server.server_config, "resolve_external_base_url", broken)

        result = _run(harness)

        assert "the answer" in result[0].text
        assert _metadata(harness) == {
            "task_id": TASK_ID,
            "source": "interactive_feedback",
        }


def _real_manager() -> tuple[NotificationManager, MagicMock]:
    """真实的 manager 和 Bark 渠道；渠道的 HTTP session 换成记录器。"""
    manager = NotificationManager._create_test_instance()
    manager._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="R778")
    manager.refresh_config_from_file = lambda force=False: None  # ty: ignore[invalid-assignment]
    manager.config.bark_enabled = True
    manager.config.bark_url = "https://bark.example.com/push"
    manager.config.bark_device_key = "ABCDEF1234567890abcdef"
    manager.config.bark_action = "url"
    manager.config.bark_timeout = 3
    manager.config.retry_count = 0
    provider = BarkNotificationProvider(manager.config)
    provider.session.close()
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=200)
    provider.session = session
    manager.register_provider(NotificationType.BARK, provider)
    return manager, session


def _pushed(session: MagicMock) -> dict[str, Any]:
    session.post.assert_called_once()
    return session.post.call_args.kwargs["json"]


class TestWhatBarkReceives:
    def test_the_push_carries_the_click_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = _Harness(
            monkeypatch,
            WebUIConfig(host="127.0.0.1", port=18998, external_base_url=EXTERNAL),
        )
        manager, session = _real_manager()
        monkeypatch.setattr(server, "notification_manager", manager)
        try:
            _run(harness)
        finally:
            manager.shutdown(wait=True)

        pushed = _pushed(session)
        assert pushed["url"] == f"{EXTERNAL}/?task_id={TASK_ID}"
        assert pushed["source"] == "interactive_feedback"

    def test_without_an_external_url_the_push_still_goes_out_without_a_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        harness = _Harness(monkeypatch)
        manager, session = _real_manager()
        monkeypatch.setattr(server, "notification_manager", manager)
        try:
            _run(harness)
        finally:
            manager.shutdown(wait=True)

        assert "url" not in _pushed(session)


def _bark_provider(template: str) -> tuple[BarkNotificationProvider, MagicMock]:
    manager = NotificationManager._create_test_instance()
    manager.config.bark_enabled = True
    manager.config.bark_url = "https://bark.example.com/push"
    manager.config.bark_device_key = "ABCDEF1234567890abcdef"
    manager.config.bark_action = "url"
    manager.config.bark_url_template = template
    provider = BarkNotificationProvider(manager.config)
    provider.session.close()
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=200)
    provider.session = session
    return provider, session


def _event(**metadata: Any) -> NotificationEvent:
    return create_event(
        title="title", message="message", metadata={"task_id": TASK_ID, **metadata}
    )


class TestTheWarningForAnEmptyBaseUrl:
    def test_it_names_the_cause_and_the_setting(self) -> None:
        provider, session = _bark_provider("{base_url}/?task_id={task_id}")

        with patch(
            "ai_intervention_agent.notification_providers.logger.warning"
        ) as warning:
            assert provider.send(_event()) is True

        assert "url" not in _pushed(session)
        warning.assert_called_once()
        text = warning.call_args.args[0]
        assert "/?task_id=" in text
        assert "external_base_url" in text

    def test_a_template_without_a_base_url_placeholder_gets_no_such_hint(self) -> None:
        provider, session = _bark_provider("ai.local/?task_id={task_id}")

        with patch(
            "ai_intervention_agent.notification_providers.logger.warning"
        ) as warning:
            assert provider.send(_event()) is True

        assert "url" not in _pushed(session)
        warning.assert_called_once()
        assert "external_base_url" not in warning.call_args.args[0]

    def test_a_known_base_url_still_renders_the_link(self) -> None:
        provider, session = _bark_provider("{base_url}/?task_id={task_id}")

        assert provider.send(_event(base_url=EXTERNAL)) is True

        assert _pushed(session)["url"] == f"{EXTERNAL}/?task_id={TASK_ID}"
