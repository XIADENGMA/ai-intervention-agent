"""TODO #3 / r42 — Bark→PWA 跳转 loopback 抑制 + LAN 推荐端到端契约测试。

历史：默认 ``web_ui.host=127.0.0.1``，``server_config.resolve_external_base_url``
返回 ``http://localhost:8080``，写进 Bark 通知 metadata 的 ``base_url`` 经
``bark_url_template`` 渲染成 ``http://localhost:8080/?task_id=...`` 推到手机
Bark 上——手机点击通知后浏览器把 loopback 解析成手机自身（RFC 6762 §11），打不开
Web UI，用户体验是"点了通知没反应/掉回 Bark App"。

r42 引入：

* ``server_config.is_loopback_url`` —— 暴露公共 helper，覆盖 IPv4/IPv6/
  ``localhost`` 三类 loopback。
* ``resolve_external_base_url(for_external_use=True)`` —— 跨设备推送场景下
  loopback 直接返回 ``""``，让上游不写 ``metadata['base_url']``。
* ``suggest_lan_base_url(port)`` —— 复用 ``web_ui_mdns_utils.detect_best_publish_ipv4``
  的 LAN 探测，给 UI 推荐具体的 ``http://<lan-ip>:<port>``。
* ``server_feedback.launch_feedback_ui`` —— 走 ``for_external_use=True``，空
  base_url 时记 info 日志说明原因。
* ``notification_providers.BarkNotificationProvider`` —— 三处兜底：metadata 显式
  url、模板渲染结果、``bark_action`` 直接当 URL 时都过滤 loopback 并 warn。
* ``/api/system/network-base-url-status`` —— GET 返回诊断 JSON 给设置面板渲染。
* PWA / VS Code 设置面板 —— 字面量级别锁定关键 ID、API URL、i18n key。

本文件以 *behaviour* 为单位组织 11 个测试，覆盖：单元、集成、端到端字面量。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationTrigger,
    NotificationType,
)
from ai_intervention_agent.notification_providers import BarkNotificationProvider
from ai_intervention_agent.server_config import (
    WebUIConfig,
    is_loopback_url,
    resolve_external_base_url,
    suggest_lan_base_url,
)

# ---------------------------------------------------------------------------
# Section 1 — is_loopback_url 单元
# ---------------------------------------------------------------------------


class TestIsLoopbackUrl(unittest.TestCase):
    """覆盖三类常见 loopback 写法 + 健壮性边界。"""

    def test_localhost_literal(self) -> None:
        self.assertTrue(is_loopback_url("http://localhost:8080"))
        self.assertTrue(is_loopback_url("http://LOCALHOST:8080"))
        self.assertTrue(is_loopback_url("https://localhost/"))

    def test_ipv4_127_0_0_1(self) -> None:
        self.assertTrue(is_loopback_url("http://127.0.0.1:8080"))
        self.assertTrue(is_loopback_url("http://127.0.0.1"))

    def test_ipv4_127_loopback_block(self) -> None:
        # 整个 127.0.0.0/8 段都是 loopback，常见的 mock host 也要被识别
        self.assertTrue(is_loopback_url("http://127.123.45.67:1234"))

    def test_ipv6_loopback(self) -> None:
        self.assertTrue(is_loopback_url("http://[::1]:8080"))
        self.assertTrue(is_loopback_url("http://[::1]/"))

    def test_lan_ipv4_is_not_loopback(self) -> None:
        self.assertFalse(is_loopback_url("http://192.168.1.10:8080"))
        self.assertFalse(is_loopback_url("http://10.0.0.5:8080"))
        self.assertFalse(is_loopback_url("http://172.16.20.30/"))

    def test_public_dns_is_not_loopback(self) -> None:
        self.assertFalse(is_loopback_url("https://ai.example.com"))
        self.assertFalse(is_loopback_url("http://ai.local:8080"))

    def test_invalid_inputs(self) -> None:
        # 空 / None / 非 string / 无 host 均放行（"未识别即不阻断"）。
        # ``cast(Any, ...)`` 显式让 ty 接受非 str 输入——本函数运行时
        # 用 ``isinstance`` 判断类型，刻意保留对错误类型的容忍。
        self.assertFalse(is_loopback_url(""))
        self.assertFalse(is_loopback_url("not-a-url"))
        self.assertFalse(is_loopback_url("://no-scheme"))
        self.assertFalse(is_loopback_url(cast(Any, None)))
        self.assertFalse(is_loopback_url(cast(Any, 12345)))


# ---------------------------------------------------------------------------
# Section 2 — resolve_external_base_url for_external_use 行为
# ---------------------------------------------------------------------------


class TestResolveExternalBaseUrlForExternalUse(unittest.TestCase):
    """``for_external_use=True`` 时 loopback 必须返回空串。"""

    @staticmethod
    def _make_section_side_effect(sections: dict) -> object:
        """构造 ``mock_get_config.return_value.get_section.side_effect``：调用
        ``get_section('web_ui')`` 返回 ``sections['web_ui']``，未命中返回 ``{}``。
        """

        def _side_effect(section: str) -> dict:
            return sections.get(section, {})

        return _side_effect

    @patch("ai_intervention_agent.server_config.get_config")
    def test_loopback_explicit_external_base_url_returned_to_ui(
        self, mock_get_config: MagicMock
    ) -> None:
        # 用户显式配置的 loopback URL，``for_external_use=False`` 仍尊重原意
        # （否则会破坏现有的 UI 文本 / 测试发送场景）。
        mock_get_config.return_value.get_section.side_effect = (
            self._make_section_side_effect(
                {
                    "web_ui": {"external_base_url": "http://127.0.0.1:9090"},
                    "mdns": {"enabled": False},
                    "network_security": {},
                }
            )
        )
        cfg = WebUIConfig(host="127.0.0.1", port=9090)
        self.assertEqual(resolve_external_base_url(cfg), "http://127.0.0.1:9090")

    @patch("ai_intervention_agent.server_config.get_config")
    def test_loopback_explicit_external_base_url_filtered_for_external_use(
        self, mock_get_config: MagicMock
    ) -> None:
        # 同样的 loopback URL 在跨设备推送场景下必须被过滤——名字承诺了"外部"。
        mock_get_config.return_value.get_section.side_effect = (
            self._make_section_side_effect(
                {
                    "web_ui": {"external_base_url": "http://127.0.0.1:9090"},
                    "mdns": {"enabled": False},
                    "network_security": {},
                }
            )
        )
        cfg = WebUIConfig(host="127.0.0.1", port=9090)
        self.assertEqual(resolve_external_base_url(cfg, for_external_use=True), "")

    @patch("ai_intervention_agent.server_config.get_config")
    def test_default_loopback_filtered_for_external_use(
        self, mock_get_config: MagicMock
    ) -> None:
        # 默认配置（127.0.0.1 + mDNS 关 + 无 external_base_url）—— 这是问题的
        # 默认场景，必须返回空串。
        mock_get_config.return_value.get_section.side_effect = (
            self._make_section_side_effect(
                {
                    "web_ui": {"host": "127.0.0.1", "port": 8080},
                    "mdns": {"enabled": False},
                    "network_security": {},
                }
            )
        )
        self.assertEqual(resolve_external_base_url(for_external_use=True), "")

    @patch("ai_intervention_agent.server_config.get_config")
    def test_zero_bind_no_mdns_filtered_for_external_use(
        self, mock_get_config: MagicMock
    ) -> None:
        # 关键 case：``host=0.0.0.0 + mDNS off + 无 external_base_url``。
        # ``get_target_host`` 把 ``0.0.0.0`` 翻译成 ``localhost``——
        # 这对**同机浏览器**有用（``http://localhost:8080`` 可访问 Web UI），
        # 但 ``for_external_use=True`` 必须把它过滤为空，否则手机端 Bark
        # 仍会拿到 ``http://localhost:8080``、解析到自身、打不开。
        mock_get_config.return_value.get_section.side_effect = (
            self._make_section_side_effect(
                {
                    "web_ui": {},
                    "mdns": {"enabled": False},
                    "network_security": {"bind_interface": "0.0.0.0"},
                }
            )
        )
        cfg = WebUIConfig(host="0.0.0.0", port=8080)
        # 老语义保留：UI 显示文本仍能拿到一个"对本机有效"的 URL。
        self.assertEqual(resolve_external_base_url(cfg), "http://localhost:8080")
        # 新语义：跨设备推送场景必须空串降级。
        self.assertEqual(resolve_external_base_url(cfg, for_external_use=True), "")

    @patch("ai_intervention_agent.server_config.get_config")
    def test_lan_ip_bind_keeps_for_external_use(
        self, mock_get_config: MagicMock
    ) -> None:
        # 真正的 LAN IPv4 bind（``192.168.x.y``）：``for_external_use=True``
        # 必须原样返回，不能被错误过滤。
        mock_get_config.return_value.get_section.side_effect = (
            self._make_section_side_effect(
                {
                    "web_ui": {},
                    "mdns": {"enabled": False},
                    "network_security": {"bind_interface": "192.168.1.10"},
                }
            )
        )
        cfg = WebUIConfig(host="192.168.1.10", port=8080)
        baseline = resolve_external_base_url(cfg)
        self.assertEqual(baseline, "http://192.168.1.10:8080")
        self.assertEqual(
            resolve_external_base_url(cfg, for_external_use=True), baseline
        )

    @patch("ai_intervention_agent.server_config.get_config")
    def test_zero_zero_zero_zero_bind_with_mdns_returns_mdns(
        self, mock_get_config: MagicMock
    ) -> None:
        # 0.0.0.0 bind + mDNS 启用 → 返回 mDNS 域名（不是 loopback）。
        mock_get_config.return_value.get_section.side_effect = (
            self._make_section_side_effect(
                {
                    "web_ui": {},
                    "mdns": {"enabled": "auto", "hostname": "ai.local"},
                    "network_security": {"bind_interface": "0.0.0.0"},
                }
            )
        )
        cfg = WebUIConfig(host="0.0.0.0", port=8080)
        url = resolve_external_base_url(cfg, for_external_use=True)
        self.assertEqual(url, "http://ai.local:8080")

    @patch("ai_intervention_agent.server_config.get_config")
    def test_mdns_url_is_not_filtered(self, mock_get_config: MagicMock) -> None:
        # mDNS hostname 在 ``ipaddress`` 解析中不算 loopback，必须放行。
        mock_get_config.return_value.get_section.side_effect = (
            self._make_section_side_effect(
                {
                    "web_ui": {},
                    "mdns": {"enabled": True, "hostname": "ai.local"},
                    "network_security": {"bind_interface": "192.168.1.10"},
                }
            )
        )
        cfg = WebUIConfig(host="192.168.1.10", port=8080)
        self.assertEqual(
            resolve_external_base_url(cfg, for_external_use=True),
            "http://ai.local:8080",
        )


# ---------------------------------------------------------------------------
# Section 3 — suggest_lan_base_url 探测行为
# ---------------------------------------------------------------------------


class TestSuggestLanBaseUrl(unittest.TestCase):
    """LAN URL 推荐：复用 mDNS 探测，端口非法 / 探测失败时返回 None。"""

    def test_invalid_port_returns_none(self) -> None:
        self.assertIsNone(suggest_lan_base_url(0))
        self.assertIsNone(suggest_lan_base_url(-1))
        self.assertIsNone(suggest_lan_base_url(70000))
        # 运行时用 ``int(port)`` 强转捕获 TypeError，这里显式 cast(Any)
        # 让 ty 不在静态阶段拒绝调用。
        self.assertIsNone(suggest_lan_base_url(cast(Any, "not-an-int")))

    @patch("ai_intervention_agent.web_ui_mdns_utils.detect_best_publish_ipv4")
    def test_lazy_imported_detection_returns_lan_url(
        self, mock_detect: MagicMock
    ) -> None:
        mock_detect.return_value = "192.168.1.42"
        url = suggest_lan_base_url(8080)
        self.assertEqual(url, "http://192.168.1.42:8080")
        mock_detect.assert_called_once()

    @patch("ai_intervention_agent.web_ui_mdns_utils.detect_best_publish_ipv4")
    def test_detection_returns_none_returns_none(self, mock_detect: MagicMock) -> None:
        mock_detect.return_value = None
        self.assertIsNone(suggest_lan_base_url(8080))

    @patch("ai_intervention_agent.web_ui_mdns_utils.detect_best_publish_ipv4")
    def test_detection_raises_returns_none(self, mock_detect: MagicMock) -> None:
        mock_detect.side_effect = OSError("network unreachable")
        self.assertIsNone(suggest_lan_base_url(8080))


# ---------------------------------------------------------------------------
# Section 4 — BarkNotificationProvider 三处 loopback 兜底
# ---------------------------------------------------------------------------


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


class TestBarkProviderLoopbackSuppression(unittest.TestCase):
    """覆盖 metadata['url'] / 模板渲染 / bark_action 三种 url 来源的 loopback 兜底。"""

    def _capture_send(
        self, provider: BarkNotificationProvider, event: NotificationEvent
    ) -> dict:
        """触发 ``provider.send(event)`` 并返回最终发出的 ``bark_data``。"""
        captured: dict = {}

        def fake_post(url: str, json: dict, timeout: int) -> MagicMock:
            captured["url"] = url
            captured["body"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"code": 200}
            return resp

        provider.session = MagicMock()
        provider.session.post.side_effect = fake_post
        result = provider.send(event)
        self.assertTrue(result, "Bark send 应当成功（loopback 仅影响 url 字段）")
        return captured.get("body") or {}

    def test_metadata_url_loopback_is_skipped(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config())
        event = NotificationEvent(
            id="evt-1",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={"url": "http://127.0.0.1:8080/page"},
        )
        body = self._capture_send(provider, event)
        # metadata['url'] 直接是 loopback —— 不应作为 bark_data['url'] 发出
        self.assertNotIn(
            "url",
            body,
            "metadata 提供的 loopback url 必须被丢弃而不是发给手机端",
        )

    def test_metadata_url_loopback_falls_back_to_template(self) -> None:
        # metadata 提供 loopback url 时丢弃 → 触发 fallback 模板渲染。
        # 模板里 base_url 是合法 LAN，最终应该用 LAN url。
        provider = BarkNotificationProvider(_make_bark_config())
        event = NotificationEvent(
            id="evt-2",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={
                "url": "http://localhost:8080/page",
                "base_url": "http://192.168.1.42:8080",
                "task_id": "task-xyz",
            },
        )
        body = self._capture_send(provider, event)
        self.assertEqual(body.get("url"), "http://192.168.1.42:8080/?task_id=task-xyz")

    def test_template_renders_loopback_is_suppressed(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config())
        event = NotificationEvent(
            id="evt-3",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={
                "base_url": "http://localhost:8080",
                "task_id": "task-abc",
            },
        )
        body = self._capture_send(provider, event)
        self.assertNotIn(
            "url",
            body,
            "模板渲染出的 loopback URL 必须被抑制",
        )

    def test_bark_action_direct_loopback_url_is_suppressed(self) -> None:
        provider = BarkNotificationProvider(
            _make_bark_config(
                bark_action="http://127.0.0.1:8080/dashboard",
                bark_url_template="",
            )
        )
        event = NotificationEvent(
            id="evt-4",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={"task_id": "task-direct"},
        )
        body = self._capture_send(provider, event)
        self.assertNotIn(
            "url",
            body,
            "bark_action 直接当 URL 时仍需过滤 loopback",
        )

    def test_lan_url_passes_through(self) -> None:
        # 反向断言：LAN URL 不会被错误地拦截。
        provider = BarkNotificationProvider(_make_bark_config())
        event = NotificationEvent(
            id="evt-5",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={
                "base_url": "http://192.168.1.42:8080",
                "task_id": "task-lan",
            },
        )
        body = self._capture_send(provider, event)
        self.assertEqual(body.get("url"), "http://192.168.1.42:8080/?task_id=task-lan")


# ---------------------------------------------------------------------------
# Section 5 — /api/system/network-base-url-status route literal contract
# ---------------------------------------------------------------------------


class TestNetworkBaseUrlStatusRouteContract(unittest.TestCase):
    """字面量锁定 endpoint 的 route 注册 + 关键字段拼装逻辑。"""

    def test_route_is_registered_and_returns_diagnostics(self) -> None:
        source = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"/api/system/network-base-url-status"',
            source,
            "诊断 endpoint 必须挂在 SystemRoutesMixin",
        )
        self.assertIn(
            "resolve_external_base_url(for_external_use=True)",
            source,
            "诊断必须使用 for_external_use=True 的语义来反映 Bark 实际行为",
        )
        self.assertIn(
            "is_loopback_url",
            source,
            "诊断必须使用 is_loopback_url helper 而不是手撕字符串",
        )
        self.assertIn(
            "suggest_lan_base_url",
            source,
            "诊断必须能给 UI 推荐 LAN URL",
        )
        self.assertIn(
            '"recommendation"',
            source,
            "诊断响应必须暴露 recommendation 字段供前端国际化",
        )


# ---------------------------------------------------------------------------
# Section 6 — server_feedback for_external_use=True 上游切换
# ---------------------------------------------------------------------------


class TestServerFeedbackUsesForExternalUse(unittest.TestCase):
    """``launch_feedback_ui`` 推 Bark 通知时必须走 ``for_external_use=True``。"""

    def test_resolve_external_base_url_called_with_for_external_use_true(
        self,
    ) -> None:
        source = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "server_feedback.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "resolve_external_base_url(\n                            config, for_external_use=True\n                        )",
            source,
            "server_feedback 必须用 for_external_use=True 调用，否则 loopback 漏出去",
        )


# ---------------------------------------------------------------------------
# Section 7 — 前端字面量契约（PWA + VS Code webview）
# ---------------------------------------------------------------------------


class TestFrontendDiagnosticsLiteralContract(unittest.TestCase):
    """前端字面量级别锁定 ID + API URL + i18n key，避免重构静默丢失。"""

    def test_pwa_settings_manager_calls_status_endpoint(self) -> None:
        source = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "static"
            / "js"
            / "settings-manager.js"
        ).read_text(encoding="utf-8")
        self.assertIn("/api/system/network-base-url-status", source)
        self.assertIn("initBarkBaseUrlStatus", source)
        self.assertIn("bark-base-url-status-item", source)
        self.assertIn("bark-base-url-copy-btn", source)
        self.assertIn("bark-base-url-recheck-btn", source)
        self.assertIn("settings.baseUrlStatusLoopback", source)
        self.assertIn("settings.baseUrlSuggestLan", source)
        self.assertIn("settings.baseUrlCopied", source)

    def test_pwa_template_has_status_block(self) -> None:
        source = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="bark-base-url-status-item"', source)
        self.assertIn('id="bark-base-url-status-message"', source)
        self.assertIn('id="bark-base-url-copy-btn"', source)
        self.assertIn('id="bark-base-url-recheck-btn"', source)
        self.assertIn(
            "settings.baseUrlStatusTitle",
            source,
            "模板必须暴露 i18n key 供 retranslate 使用",
        )

    def test_vscode_webview_settings_ui_calls_status_endpoint(self) -> None:
        source = (
            REPO_ROOT / "packages" / "vscode" / "webview-settings-ui.js"
        ).read_text(encoding="utf-8")
        self.assertIn("/api/system/network-base-url-status", source)
        self.assertIn("initBarkBaseUrlStatus", source)
        self.assertIn("settingsBarkBaseUrlStatus", source)
        self.assertIn("settingsBarkBaseUrlCopyBtn", source)
        self.assertIn("settingsBarkBaseUrlRecheckBtn", source)
        self.assertIn("settings.bark.baseUrlStatusLoopback", source)
        self.assertIn("settings.bark.baseUrlSuggestLan", source)
        self.assertIn("settings.bark.baseUrlCopied", source)

    def test_vscode_webview_html_has_status_block(self) -> None:
        source = (REPO_ROOT / "packages" / "vscode" / "webview.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="settingsBarkBaseUrlStatus"', source)
        self.assertIn('id="settingsBarkBaseUrlMessage"', source)
        self.assertIn('id="settingsBarkBaseUrlCopyBtn"', source)
        self.assertIn('id="settingsBarkBaseUrlRecheckBtn"', source)

    def test_locale_keys_present_in_zh_cn_and_en(self) -> None:
        # PWA locales：static/locales/{en,zh-CN}.json
        for lang in ("en", "zh-CN"):
            data = json.loads(
                (
                    REPO_ROOT
                    / "src"
                    / "ai_intervention_agent"
                    / "static"
                    / "locales"
                    / f"{lang}.json"
                ).read_text(encoding="utf-8")
            )
            settings_section = data.get("settings", {})
            for key in (
                "baseUrlStatusTitle",
                "baseUrlStatusOk",
                "baseUrlStatusLoopback",
                "baseUrlStatusUnreachable",
                "baseUrlSuggestLan",
                "baseUrlSuggestNoLan",
                "baseUrlCopyLan",
                "baseUrlCopied",
                "baseUrlRecheck",
            ):
                self.assertIn(
                    key,
                    settings_section,
                    f"PWA {lang}.json settings.{key} 缺失",
                )

        # VS Code locales：packages/vscode/locales/{en,zh-CN}.json
        for lang in ("en", "zh-CN"):
            data = json.loads(
                (
                    REPO_ROOT / "packages" / "vscode" / "locales" / f"{lang}.json"
                ).read_text(encoding="utf-8")
            )
            bark_section = data.get("settings", {}).get("bark", {})
            for key in (
                "baseUrlStatusTitle",
                "baseUrlStatusOk",
                "baseUrlStatusLoopback",
                "baseUrlStatusUnreachable",
                "baseUrlSuggestLan",
                "baseUrlSuggestNoLan",
                "baseUrlCopyLan",
                "baseUrlCopied",
                "baseUrlRecheck",
            ):
                self.assertIn(
                    key,
                    bark_section,
                    f"VS Code {lang}.json settings.bark.{key} 缺失",
                )

    def test_recommendation_enum_alignment(self) -> None:
        # 后端发的 recommendation 枚举（"ok" / "configure_external_base_url" /
        # "bind_lan_interface"）必须与前端 if-else 分支一致——只有两侧都改才会
        # 让所有三种状态展示正确文案。
        backend = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
        ).read_text(encoding="utf-8")
        for value in (
            '"ok"',
            '"configure_external_base_url"',
            '"bind_lan_interface"',
        ):
            self.assertIn(value, backend)

        pwa_js = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "static"
            / "js"
            / "settings-manager.js"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            pwa_js,
            r'recommendation\s*===\s*["\']ok["\']',
            "PWA 必须把 recommendation === 'ok' 与其他状态分开处理",
        )

        vscode_js = (
            REPO_ROOT / "packages" / "vscode" / "webview-settings-ui.js"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            vscode_js,
            r'recommendation\s*===\s*["\']ok["\']',
            "VS Code webview 必须把 recommendation === 'ok' 与其他状态分开处理",
        )


# ---------------------------------------------------------------------------
# Section 8 — Bark provider 现有行为 regression（确保 loopback 兜底没破老路径）
# ---------------------------------------------------------------------------


class TestBarkProviderExistingBehaviorIntact(unittest.TestCase):
    """老的 happy path 不应被 r42 破坏。"""

    def test_action_none_does_not_set_url(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config(bark_action="none"))
        provider.session = MagicMock()
        provider.session.post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"code": 200})
        )
        event = NotificationEvent(
            id="evt-none",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={"base_url": "http://192.168.1.42:8080", "task_id": "x"},
        )
        self.assertTrue(provider.send(event))
        body = provider.session.post.call_args.kwargs["json"]
        self.assertNotIn("url", body)

    def test_unknown_action_string_dropped(self) -> None:
        provider = BarkNotificationProvider(
            _make_bark_config(bark_action="???invalid???", bark_url_template="")
        )
        provider.session = MagicMock()
        provider.session.post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"code": 200})
        )
        event = NotificationEvent(
            id="evt-bad",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={},
        )
        self.assertTrue(provider.send(event))
        body = provider.session.post.call_args.kwargs["json"]
        self.assertNotIn("url", body)


# ---------------------------------------------------------------------------
# Section 9 — server_config.py 公共 helper 的导入面（防止误删）
# ---------------------------------------------------------------------------


class TestServerConfigPublicSurface(unittest.TestCase):
    """三个 helper 必须从 server_config 顶层 import 得到。"""

    def test_three_helpers_callable(self) -> None:
        # 直接验证已经在文件顶部 import 的三个 helper 是 callable，避免触发
        # ruff 的 PLC0415（重复 import）/ E402（local import）噪音。
        self.assertTrue(callable(is_loopback_url))
        self.assertTrue(callable(resolve_external_base_url))
        self.assertTrue(callable(suggest_lan_base_url))

    def test_resolve_kwarg_signature(self) -> None:
        # ``for_external_use`` 必须保持 keyword-only，避免位置参数误传。
        import inspect

        sig = inspect.signature(resolve_external_base_url)
        self.assertIn("for_external_use", sig.parameters)
        self.assertEqual(
            sig.parameters["for_external_use"].kind,
            inspect.Parameter.KEYWORD_ONLY,
            "for_external_use 必须 keyword-only，防止旧调用方位置传 True",
        )
        self.assertIs(sig.parameters["for_external_use"].default, False)


# ---------------------------------------------------------------------------
# Section 10 — 端到端 string scan：loopback 兜底必须 warn 一次
# ---------------------------------------------------------------------------


class TestLoopbackSuppressionLogsWarning(unittest.TestCase):
    """落到 BarkProvider 的 loopback 抑制必须留下排查痕迹。

    项目用 ``EnhancedLogger``（基于 Loguru），不走 ``logging.getLogger``
    命名空间——所以这里直接 patch ``notification_providers.logger`` 对象
    断言 ``logger.warning`` 被调用并匹配特定关键字。
    """

    def test_provider_warns_when_metadata_url_is_loopback(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config())
        event = NotificationEvent(
            id="evt-warn",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={"url": "http://127.0.0.1:8080/page"},
        )
        provider.session = MagicMock()
        provider.session.post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"code": 200})
        )
        with patch(
            "ai_intervention_agent.notification_providers.logger"
        ) as mock_logger:
            provider.send(event)
        warn_messages = [
            call.args[0] for call in mock_logger.warning.call_args_list if call.args
        ]
        joined = "\n".join(str(m) for m in warn_messages)
        self.assertRegex(
            joined,
            r"event\.metadata\['url'\]=.*127\.0\.0\.1.*回环地址",
        )

    def test_provider_warns_when_template_renders_loopback(self) -> None:
        provider = BarkNotificationProvider(_make_bark_config())
        event = NotificationEvent(
            id="evt-warn-tpl",
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.BARK],
            metadata={
                "base_url": "http://localhost:8080",
                "task_id": "abc",
            },
        )
        provider.session = MagicMock()
        provider.session.post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"code": 200})
        )
        with patch(
            "ai_intervention_agent.notification_providers.logger"
        ) as mock_logger:
            provider.send(event)
        warn_messages = [
            call.args[0] for call in mock_logger.warning.call_args_list if call.args
        ]
        joined = "\n".join(str(m) for m in warn_messages)
        self.assertRegex(
            joined,
            r"bark_url_template.*回环地址",
        )


# ---------------------------------------------------------------------------
# Section 11 — sanity：r42 改动不应误伤现有 i18n 替换流程
# ---------------------------------------------------------------------------


class TestI18nKeysMatchTemplatePlaceholders(unittest.TestCase):
    """``{url}`` 占位符必须在所有 PWA / VS Code locale 的对应文案里都出现。"""

    def test_pwa_locale_url_placeholder(self) -> None:
        for lang in ("en", "zh-CN"):
            data = json.loads(
                (
                    REPO_ROOT
                    / "src"
                    / "ai_intervention_agent"
                    / "static"
                    / "locales"
                    / f"{lang}.json"
                ).read_text(encoding="utf-8")
            )
            for key in ("baseUrlStatusOk", "baseUrlStatusLoopback"):
                value = data["settings"][key]
                self.assertIn(
                    "{url}",
                    value,
                    f"static/locales/{lang}.json settings.{key} 缺少 {{url}} 占位符",
                )

    def test_vscode_locale_url_placeholder(self) -> None:
        for lang in ("en", "zh-CN"):
            data = json.loads(
                (
                    REPO_ROOT / "packages" / "vscode" / "locales" / f"{lang}.json"
                ).read_text(encoding="utf-8")
            )
            bark = data["settings"]["bark"]
            for key in ("baseUrlStatusOk", "baseUrlStatusLoopback"):
                value = bark[key]
                self.assertIn(
                    "{url}",
                    value,
                    f"packages/vscode/locales/{lang}.json settings.bark.{key} 缺少 {{url}} 占位符",
                )


# ---------------------------------------------------------------------------
# Section 12 — i18n key naming alignment
# ---------------------------------------------------------------------------


class TestVSCodeUiUsesScopedI18nKeys(unittest.TestCase):
    """VS Code webview 的 i18n key 必须使用 ``settings.bark.`` 命名空间。"""

    def test_vscode_settings_ui_keys_align_with_locales(self) -> None:
        ui = (REPO_ROOT / "packages" / "vscode" / "webview-settings-ui.js").read_text(
            encoding="utf-8"
        )
        # 不可漏掉关键事件
        for key in (
            "settings.bark.baseUrlStatusOk",
            "settings.bark.baseUrlStatusLoopback",
            "settings.bark.baseUrlStatusUnreachable",
            "settings.bark.baseUrlSuggestLan",
            "settings.bark.baseUrlSuggestNoLan",
            "settings.bark.baseUrlCopied",
        ):
            self.assertIn(key, ui)
        # 防御误用 PWA 的不带 bark.* 子命名空间的 key
        self.assertNotRegex(
            ui,
            r"['\"]settings\.baseUrl(Status|Suggest|Copy|Recheck)",
            "VS Code webview 不应直接复用 PWA 的 settings.baseUrl* key",
        )


if __name__ == "__main__":
    # 让测试运行器忽略 ``re`` 导入未使用的 lint：留作未来扩展（例如 future
    # locale 占位符 regex 校验）。
    _ = re
    unittest.main()
