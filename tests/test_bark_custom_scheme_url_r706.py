"""R706 回归护栏：Bark 点击 URL 支持自定义 scheme（shortcuts:// 深链）。

背景（TODO#14/32「bark 通知带 url 功能修复 / URL 模板不适配 shortcuts://」）：

iOS Bark 客户端的 ``url`` 字段支持任意 URL scheme 跳转——推荐用法是
``shortcuts://run-shortcut?name=ai%20intervention%20agent``：点击 Bark
通知直接启动快捷指令（内嵌"显示网页"动作打开 Web UI），比 http 链接
多一层免地址栏、免横幅的原生体验。

旧实现要求 ``bark_url_template`` 渲染结果 ``startswith(("http://",
"https://"))``，``shortcuts://`` 模板被整个丢弃（warning「渲染结果不是
合法 URL」），推荐用法完全不可用。

R706 契约：

1. **模板路径**：渲染结果接受任意合法 ``scheme://`` 形式
   （``_is_acceptable_bark_click_url``，RFC 3986 §3.1 scheme 语法 +
   强制 ``://``）；``javascript:`` / ``data:`` 等无 authority 形态
   天然不匹配，不会被误放行。
2. **metadata 路径**：显式提供的候选 URL 同样按此校验（非法值跳过并
   warn，让模板兜底），自定义 scheme 可直接透传。
3. **loopback 抑制仅对 http(s) 生效**：``shortcuts://localhost`` 这类
   值是 App 深链、不涉及网络 host 解析，不得被误杀；
   ``http://localhost:8080`` 的既有抑制行为保持不变。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationTrigger,
    NotificationType,
)
from ai_intervention_agent.notification_providers import (
    BarkNotificationProvider,
    _bark_url_is_loopback,
    _is_acceptable_bark_click_url,
)

SHORTCUTS_URL = "shortcuts://run-shortcut?name=ai%20intervention%20agent"


def _make_bark_config(
    *,
    bark_action: str = "url",
    bark_url_template: str = "{base_url}/?task_id={task_id}",
) -> MagicMock:
    cfg = MagicMock()
    cfg.bark_url = "https://api.day.app/push"
    cfg.bark_device_key = "device-key-stub"
    cfg.bark_icon = ""
    cfg.bark_action = bark_action
    cfg.bark_url_template = bark_url_template
    cfg.bark_timeout = 10
    return cfg


def _make_event(event_id: str, metadata: dict) -> NotificationEvent:
    return NotificationEvent(
        id=event_id,
        title="t",
        message="m",
        trigger=NotificationTrigger.IMMEDIATE,
        types=[NotificationType.BARK],
        metadata=metadata,
    )


def _send_and_capture_body(
    provider: BarkNotificationProvider, event: NotificationEvent
) -> dict:
    provider.session = MagicMock()
    provider.session.post.return_value = MagicMock(
        status_code=200, json=MagicMock(return_value={"code": 200})
    )
    assert provider.send(event) is True
    return provider.session.post.call_args.kwargs["json"]


class TestAcceptableClickUrlHelper(unittest.TestCase):
    """_is_acceptable_bark_click_url：scheme:// 白形态判定。"""

    def test_http_and_https_accepted(self) -> None:
        self.assertTrue(_is_acceptable_bark_click_url("http://ai.local:8081/"))
        self.assertTrue(_is_acceptable_bark_click_url("https://example.com/x"))

    def test_custom_schemes_accepted(self) -> None:
        self.assertTrue(_is_acceptable_bark_click_url(SHORTCUTS_URL))
        self.assertTrue(_is_acceptable_bark_click_url("bark://x"))
        self.assertTrue(_is_acceptable_bark_click_url("my-app+v2://open/page"))

    def test_no_authority_schemes_rejected(self) -> None:
        # javascript: / data: / mailto: 没有 ``://``，天然拒绝
        self.assertFalse(_is_acceptable_bark_click_url("javascript:alert(1)"))
        self.assertFalse(_is_acceptable_bark_click_url("data:text/html,hi"))
        self.assertFalse(_is_acceptable_bark_click_url("mailto:a@b.c"))

    def test_garbage_rejected(self) -> None:
        self.assertFalse(_is_acceptable_bark_click_url(""))
        self.assertFalse(_is_acceptable_bark_click_url("not-a-url"))
        self.assertFalse(_is_acceptable_bark_click_url("://no-scheme"))
        self.assertFalse(_is_acceptable_bark_click_url("1abc://digit-first"))
        self.assertFalse(_is_acceptable_bark_click_url("scheme:// space"))


class TestLoopbackOnlyAppliesToHttp(unittest.TestCase):
    """loopback 抑制仅 http(s)：自定义 scheme 不做 host 解析。"""

    def test_http_loopback_still_detected(self) -> None:
        self.assertTrue(_bark_url_is_loopback("http://localhost:8080"))
        self.assertTrue(_bark_url_is_loopback("http://127.0.0.1:8080/x"))

    def test_custom_scheme_never_loopback(self) -> None:
        self.assertFalse(_bark_url_is_loopback(SHORTCUTS_URL))
        # 奇异值：shortcuts://localhost 是 App 深链的 path 部分语义，
        # 不涉及网络解析，不得误杀
        self.assertFalse(_bark_url_is_loopback("shortcuts://localhost"))


class TestTemplateRendersCustomScheme(unittest.TestCase):
    """bark_url_template 配置为 shortcuts:// 深链时必须生效。"""

    def test_static_shortcuts_template_sent_as_url(self) -> None:
        provider = BarkNotificationProvider(
            _make_bark_config(bark_url_template=SHORTCUTS_URL)
        )
        body = _send_and_capture_body(
            provider,
            _make_event("evt-shortcuts", {"task_id": "abc"}),
        )
        self.assertEqual(body.get("url"), SHORTCUTS_URL)

    def test_custom_scheme_template_with_placeholder(self) -> None:
        provider = BarkNotificationProvider(
            _make_bark_config(bark_url_template="myapp://task/{task_id}")
        )
        body = _send_and_capture_body(
            provider,
            _make_event("evt-placeholder", {"task_id": "t-42"}),
        )
        self.assertEqual(body.get("url"), "myapp://task/t-42")

    def test_http_template_behavior_unchanged(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config())
        body = _send_and_capture_body(
            provider,
            _make_event(
                "evt-http",
                {"base_url": "http://192.168.1.42:8080", "task_id": "x1"},
            ),
        )
        self.assertEqual(body.get("url"), "http://192.168.1.42:8080/?task_id=x1")

    def test_http_loopback_template_still_suppressed(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config())
        body = _send_and_capture_body(
            provider,
            _make_event(
                "evt-loopback",
                {"base_url": "http://localhost:8080", "task_id": "x2"},
            ),
        )
        self.assertNotIn("url", body)

    def test_no_authority_template_rejected(self) -> None:
        provider = BarkNotificationProvider(
            _make_bark_config(bark_url_template="javascript:alert(1)")
        )
        body = _send_and_capture_body(
            provider,
            _make_event("evt-js", {"task_id": "x3"}),
        )
        self.assertNotIn("url", body)


class TestMetadataCustomSchemePassthrough(unittest.TestCase):
    """metadata 显式候选：自定义 scheme 透传，非法值跳过让模板兜底。"""

    def test_metadata_shortcuts_url_passthrough(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config())
        body = _send_and_capture_body(
            provider,
            _make_event("evt-meta-shortcuts", {"url": SHORTCUTS_URL}),
        )
        self.assertEqual(body.get("url"), SHORTCUTS_URL)

    def test_metadata_garbage_skipped_falls_back_to_template(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config())
        body = _send_and_capture_body(
            provider,
            _make_event(
                "evt-meta-garbage",
                {
                    "url": "not a url at all",
                    "base_url": "http://192.168.1.42:8080",
                    "task_id": "y1",
                },
            ),
        )
        self.assertEqual(body.get("url"), "http://192.168.1.42:8080/?task_id=y1")


if __name__ == "__main__":
    unittest.main()
