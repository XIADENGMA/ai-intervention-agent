"""R707 回归护栏：iOS A2HS 横幅 dismiss 的服务端持久化。

背景（TODO#14「在 shortcuts 里打开时不显示 / 关闭后永久不显示」）：

iOS A2HS 引导横幅的「永久 dismiss」此前只写 localStorage
（``aiia.iosA2hsDismissed.v1``）。但用户的主要打开路径是快捷指令的
「显示网页」动作（SFSafariViewController）——该环境的 localStorage 与
Safari **不共享**且**跨会话不持久**（iOS 11+ 隐私隔离），dismiss 状态
每次都丢，横幅反复出现；且该环境无法用 JS 可靠检测（Apple 有意为之），
「检测到 in-app browser 就不显示」的方案不可行。

R707 方案：dismiss 状态服务端持久化（单用户工具的全局语义）——

1. ``web_ui.ios_a2hs_hint_dismissed``（config.toml，默认 false）；
2. ``POST /api/system/ios-a2hs-dismiss`` 幂等写 true（任意来源可调：
   横幅只出现在远程 iOS 设备上，限 loopback 会让功能失效）；
3. ``_get_template_context`` 注入 ``ios_a2hs_dismissed``，模板输出
   ``window.AIIA_IOS_A2HS_DISMISSED``；
4. ``ios_a2hs_hint.js`` 的 ``_isDismissed`` 优先读注入值，
   ``_setDismissed`` fire-and-forget 回写服务端（localStorage 仍是
   本地兜底）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
A2HS_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "ios_a2hs_hint.js"
)
TEMPLATE = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
CONFIG_DEFAULT = REPO_ROOT / "config.toml.default"


class _SystemRouteBase(unittest.TestCase):
    """system 路由测试共享 fixture：限流关闭 + 测试客户端。"""

    _port: int = 19710
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="a2hs dismiss test", task_id="a2hs-rt", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


class TestDismissEndpoint(_SystemRouteBase):
    _port = 19711

    def _post_with_config(self, section: dict) -> tuple[Any, MagicMock]:
        cfg = MagicMock()
        cfg.get_section.return_value = section
        with patch(
            "ai_intervention_agent.web_ui_routes.system.get_config",
            return_value=cfg,
        ):
            resp = self._client.post("/api/system/ios-a2hs-dismiss")
        return resp, cfg

    def test_first_dismiss_persists_true(self) -> None:
        resp, cfg = self._post_with_config({"host": "0.0.0.0"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        cfg.update_section.assert_called_once()
        section_name, payload = cfg.update_section.call_args.args
        self.assertEqual(section_name, "web_ui")
        self.assertIs(payload["ios_a2hs_hint_dismissed"], True)

    def test_idempotent_when_already_dismissed(self) -> None:
        # 已是 true 时不再写 config（避免每次点击都触发磁盘写 + 热更新）
        resp, cfg = self._post_with_config({"ios_a2hs_hint_dismissed": True})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["success"])
        cfg.update_section.assert_not_called()

    def test_non_loopback_origin_allowed(self) -> None:
        # 横幅只出现在远程 iOS 设备上——远程来源必须能调用
        cfg = MagicMock()
        cfg.get_section.return_value = {}
        with patch(
            "ai_intervention_agent.web_ui_routes.system.get_config",
            return_value=cfg,
        ):
            resp = self._client.post(
                "/api/system/ios-a2hs-dismiss",
                environ_overrides={"REMOTE_ADDR": "192.168.1.23"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_config_failure_returns_500(self) -> None:
        cfg = MagicMock()
        cfg.get_section.side_effect = RuntimeError("boom")
        with patch(
            "ai_intervention_agent.web_ui_routes.system.get_config",
            return_value=cfg,
        ):
            resp = self._client.post("/api/system/ios-a2hs-dismiss")
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(resp.get_json()["success"])


class TestTemplateInjection(_SystemRouteBase):
    _port = 19712

    def test_template_context_contains_flag(self) -> None:
        ctx = self._ui._get_template_context()
        self.assertIn("ios_a2hs_dismissed", ctx)
        self.assertIsInstance(ctx["ios_a2hs_dismissed"], bool)

    def test_template_outputs_window_variable(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "window.AIIA_IOS_A2HS_DISMISSED = {{ ios_a2hs_dismissed|tojson }};",
            template,
        )


class TestConfigModelDefault(unittest.TestCase):
    def test_web_ui_section_field_defaults_false(self) -> None:
        from ai_intervention_agent.shared_types import WebUISectionConfig

        section = WebUISectionConfig()
        self.assertIs(section.ios_a2hs_hint_dismissed, False)

    def test_config_default_documents_field(self) -> None:
        content = CONFIG_DEFAULT.read_text(encoding="utf-8")
        self.assertIn("ios_a2hs_hint_dismissed = false", content)


class TestFrontendContract(unittest.TestCase):
    """ios_a2hs_hint.js：注入值优先 + dismiss 回写服务端。"""

    def setUp(self) -> None:
        self.source = A2HS_JS.read_text(encoding="utf-8")

    def test_is_dismissed_checks_injected_flag_first(self) -> None:
        body_match = re.search(
            r"function _isDismissed\(\)\s*\{(.*?)\n  \}",
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(body_match)
        assert body_match is not None
        body = body_match.group(1)
        injected_idx = body.find("window.AIIA_IOS_A2HS_DISMISSED === true")
        storage_idx = body.find("localStorage.getItem")
        self.assertGreater(injected_idx, -1, "必须检查服务端注入的 dismiss 状态")
        self.assertGreater(storage_idx, -1)
        self.assertLess(
            injected_idx,
            storage_idx,
            "服务端注入值必须优先于 localStorage（快捷指令 WebView 的"
            " localStorage 不持久）",
        )

    def test_set_dismissed_posts_to_server(self) -> None:
        self.assertIn('fetch("/api/system/ios-a2hs-dismiss"', self.source)
        self.assertIn('method: "POST"', self.source)
        # dismiss 后本地立即生效（不等下一次页面加载的注入）
        self.assertIn("window.AIIA_IOS_A2HS_DISMISSED = true", self.source)


if __name__ == "__main__":
    unittest.main()
