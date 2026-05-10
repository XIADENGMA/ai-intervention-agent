"""R141 · `POST /api/system/notifications/test` 系统级通知 self-test 端点契约测试。

背景
----

R141 之前，要验证「线上 NotificationManager 配的 Bark / Web / Sound / System
provider 是否真的能投得出去」只能：

1. 等真实任务触发 —— 慢、不可控；
2. 在设置面板里点「测试 Bark」—— 但 ``/api/test-bark`` 是 **配置阶段**
   验证（参数从 form 传），不能验证「当前生效的 NotificationManager 配置」
   能不能 dispatch 到既有 provider；
3. 直接 SSH 上服务器手动 ``curl`` notification_manager —— 运维不友好。

R141 落地一个 **运行阶段** 的 self-test endpoint：

- POST /api/system/notifications/test
- body 可选 ``{"provider": "all"|"bark"|"web"|"sound"|"system",
  "title": "...", "message": "..."}``
- 默认 ``provider="all"``，触发所有已 enable 的 provider
- 返回 ``{success, event_id, providers_dispatched, message}``，前端 / 运维
  可结合 ``GET /api/system/health`` 的 ``checks.notification.stats`` 字段
  查看真实投递结果

设计契约（共 ~22 cases）：

1. **路由注册** — 路由可达；HTTP 方法限定 POST；rate-limit 6/min。

2. **缺省体行为** — 不带 body / body 为空 → ``provider="all"``；触发所有
   ``cfg.{bark|web|sound|system}_enabled`` 为 True 的 provider；types
   传给 ``send_notification`` 是对应 NotificationType 的 list；返回
   ``providers_dispatched`` 是这些 provider 的 ``.value`` 列表。

3. **指定单 provider** — body ``{"provider": "bark"}`` → 只传
   ``[NotificationType.BARK]``；其他 provider 即使 enable 也不被触发。

4. **provider 参数 case-insensitive + trim** — ``"  Bark  "`` /
   ``"BARK"`` 都按 bark 处理。

5. **非法 provider** — body ``{"provider": "weibo"}`` → 400 +
   ``error="invalid_provider"`` + 带回合法值列表的 message。

6. **config.enabled=False** — 200 + ``success=False`` +
   ``providers_dispatched=[]`` + message 解释「config 中被禁用」。
   不调 ``send_notification``。

7. **provider enable 但单一未启用** — ``provider="bark"`` 而
   ``bark_enabled=False`` → 200 + ``success=False`` +
   ``providers_dispatched=[]``；不调 ``send_notification``。

8. **all 模式但所有 provider 都关闭** — 200 + ``success=False`` +
   ``providers_dispatched=[]``。

9. **声音 provider 受 sound_mute 影响** — ``sound_enabled=True`` +
   ``sound_mute=True`` → sound 不在 dispatched 列表里。

10. **send_notification 抛异常** — 路由捕获 → 500 +
    ``error="dispatch_failed"``，不外泄堆栈。

11. **notification_manager 不可用** — 500 +
    ``error="notification_unavailable"``。

12. **自定义 title / message 透传** — body 里的 title / message 被
    ``send_notification`` 接收（不被默认值覆盖）。

13. **Swagger doc 字段** — Swagger 注释里出现 ``/api/system/notifications/test``
    enum 列出 5 个合法 provider；标记 tag "System"。

这一层只锁路由表面契约，不锁 provider 真实送达——后者由
``test_notification_manager*`` 系列其他测试负责。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _RouteTestBase(unittest.TestCase):
    """共享：起一个 WebFeedbackUI + Flask test client。

    对齐 ``tests/test_test_bark_aiia_test_sentinel_r63a.py::_RouteTestBase``
    避免反复多端起 server 引入额外副作用。
    """

    _port: int = 19111
    _ui: Any = None
    _client: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        from ai_intervention_agent.web_ui import WebFeedbackUI

        cls._ui = WebFeedbackUI(
            prompt="r141 self-test", task_id="rt-r141", port=cls._port
        )
        cls._ui.app.config["TESTING"] = True
        cls._ui.limiter.enabled = False
        cls._client = cls._ui.app.test_client()


def _make_mock_manager(
    enabled: bool = True,
    bark_enabled: bool = True,
    web_enabled: bool = True,
    sound_enabled: bool = True,
    sound_mute: bool = False,
    system_enabled: bool = True,
    send_returns: str = "notification_test_evid_123",
    send_raises: Exception | None = None,
) -> MagicMock:
    """造一个 mock notification_manager，``config.{bark,web,sound,system}_enabled``
    可独立控制；``send_notification`` 默认返回固定 evid，传 ``send_raises``
    可让它抛异常以测试 500 路径。
    """
    manager = MagicMock()
    manager.config.enabled = enabled
    manager.config.bark_enabled = bark_enabled
    manager.config.web_enabled = web_enabled
    manager.config.sound_enabled = sound_enabled
    manager.config.sound_mute = sound_mute
    manager.config.system_enabled = system_enabled

    if send_raises is not None:
        manager.send_notification.side_effect = send_raises
    else:
        manager.send_notification.return_value = send_returns

    return manager


def _patch_manager(mock_manager: MagicMock) -> Any:
    """同时 patch ``notification_manager`` + ``NotificationType``，
    避免 ``_ensure_notification_loaded`` 在 mock 已注入后再次覆盖。
    """
    from ai_intervention_agent.notification_models import NotificationType

    return patch.multiple(
        "ai_intervention_agent.web_ui_routes.notification",
        notification_manager=mock_manager,
        NotificationType=NotificationType,
    )


class TestRouteRegistered(_RouteTestBase):
    """路由表注册契约。"""

    def test_route_responds_to_post(self):
        # 起一个最小 mock 让 endpoint 不至于 500——只关心 routing
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post("/api/system/notifications/test", json={})
        self.assertEqual(resp.status_code, 200)

    def test_get_method_not_allowed(self):
        resp = self._client.get("/api/system/notifications/test")
        self.assertEqual(resp.status_code, 405)


class TestDefaultAllProviders(_RouteTestBase):
    """缺省 body / ``provider=all`` → 所有已 enable 的 provider 被触发。"""

    def test_no_body_dispatches_all_enabled(self):
        from ai_intervention_agent.notification_models import NotificationType

        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post("/api/system/notifications/test")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["event_id"], "notification_test_evid_123")
        self.assertEqual(
            sorted(body["providers_dispatched"]),
            sorted(
                [
                    NotificationType.BARK.value,
                    NotificationType.WEB.value,
                    NotificationType.SOUND.value,
                    NotificationType.SYSTEM.value,
                ]
            ),
        )
        mock_manager.send_notification.assert_called_once()
        kwargs = mock_manager.send_notification.call_args.kwargs
        self.assertEqual(
            sorted([t.value for t in kwargs["types"]]),
            sorted(
                [
                    NotificationType.BARK.value,
                    NotificationType.WEB.value,
                    NotificationType.SOUND.value,
                    NotificationType.SYSTEM.value,
                ]
            ),
        )

    def test_explicit_all_param_dispatches_all_enabled(self):
        from ai_intervention_agent.notification_models import NotificationType

        mock_manager = _make_mock_manager(bark_enabled=False, sound_enabled=False)
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "all"}
            )

        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(
            sorted(body["providers_dispatched"]),
            sorted([NotificationType.WEB.value, NotificationType.SYSTEM.value]),
        )

    def test_metadata_marker_set_for_self_test(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            self._client.post("/api/system/notifications/test", json={})

        kwargs = mock_manager.send_notification.call_args.kwargs
        meta = kwargs.get("metadata") or {}
        self.assertTrue(meta.get("r141_self_test"))
        self.assertEqual(meta.get("provider_param"), "all")


class TestSingleProvider(_RouteTestBase):
    """``provider=bark`` 等 → 只触发对应单一 provider。"""

    def test_provider_bark_only(self):
        from ai_intervention_agent.notification_models import NotificationType

        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "bark"}
            )

        body = resp.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["providers_dispatched"], [NotificationType.BARK.value])
        kwargs = mock_manager.send_notification.call_args.kwargs
        self.assertEqual([t.value for t in kwargs["types"]], ["bark"])

    def test_provider_web_only(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "web"}
            )

        body = resp.get_json()
        self.assertEqual(body["providers_dispatched"], ["web"])

    def test_provider_sound_only(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "sound"}
            )

        body = resp.get_json()
        self.assertEqual(body["providers_dispatched"], ["sound"])

    def test_provider_system_only(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "system"}
            )

        body = resp.get_json()
        self.assertEqual(body["providers_dispatched"], ["system"])


class TestProviderNormalization(_RouteTestBase):
    """provider 大小写 / 前后空白都被正规化。"""

    def test_uppercase_provider(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "BARK"}
            )

        body = resp.get_json()
        self.assertEqual(body["providers_dispatched"], ["bark"])

    def test_provider_trim_whitespace(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "  Web  "}
            )

        body = resp.get_json()
        self.assertEqual(body["providers_dispatched"], ["web"])


class TestInvalidProvider(_RouteTestBase):
    """非法 provider → 400。"""

    def test_unknown_provider_returns_400(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "weibo"}
            )

        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "invalid_provider")
        self.assertIn("weibo", body["message"])
        mock_manager.send_notification.assert_not_called()

    def test_empty_provider_falls_back_to_all(self):
        # 空字符串 / None 都按 "all" 处理（最大化兼容前端少传）
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": ""}
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["success"])


class TestConfigDisabledOrAllOff(_RouteTestBase):
    """config.enabled=False / 全部 provider 关 / 单一 provider 未 enable。"""

    def test_global_disabled_returns_success_false_no_dispatch(self):
        mock_manager = _make_mock_manager(enabled=False)
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "all"}
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["event_id"], "")
        self.assertEqual(body["providers_dispatched"], [])
        self.assertIn("禁用", body["message"])
        mock_manager.send_notification.assert_not_called()

    def test_specific_provider_not_enabled(self):
        mock_manager = _make_mock_manager(bark_enabled=False)
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "bark"}
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["providers_dispatched"], [])
        mock_manager.send_notification.assert_not_called()

    def test_all_providers_disabled(self):
        mock_manager = _make_mock_manager(
            bark_enabled=False,
            web_enabled=False,
            sound_enabled=False,
            system_enabled=False,
        )
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "all"}
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["providers_dispatched"], [])
        mock_manager.send_notification.assert_not_called()

    def test_sound_mute_excludes_sound_provider(self):
        mock_manager = _make_mock_manager(sound_mute=True)
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "all"}
            )

        body = resp.get_json()
        self.assertNotIn("sound", body["providers_dispatched"])
        # 其他三家仍被触发
        self.assertIn("bark", body["providers_dispatched"])
        self.assertIn("web", body["providers_dispatched"])
        self.assertIn("system", body["providers_dispatched"])


class TestSendFailureGracefulDegradation(_RouteTestBase):
    """send_notification 抛异常 / notification_manager 不可用 → 500。"""

    def test_send_raises_returns_500(self):
        mock_manager = _make_mock_manager(send_raises=RuntimeError("boom"))
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test", json={"provider": "bark"}
            )

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "dispatch_failed")
        # 不外泄异常细节（只用 i18n message）
        self.assertNotIn("boom", body["message"])

    def test_notification_manager_unavailable_returns_500(self):
        with patch(
            "ai_intervention_agent.web_ui_routes.notification.notification_manager",
            None,
        ):
            # 确保 _ensure_notification_loaded 不再 hoist 真实 manager 进来
            with patch(
                "ai_intervention_agent.web_ui_routes.notification._ensure_notification_loaded",
                lambda: None,
            ):
                resp = self._client.post(
                    "/api/system/notifications/test", json={"provider": "all"}
                )

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "notification_unavailable")


class TestCustomTitleAndMessage(_RouteTestBase):
    """自定义 title / message → 透传给 send_notification。"""

    def test_custom_title_and_message_passed_through(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            resp = self._client.post(
                "/api/system/notifications/test",
                json={
                    "provider": "bark",
                    "title": "Custom Title",
                    "message": "Custom Body",
                },
            )

        self.assertEqual(resp.status_code, 200)
        kwargs = mock_manager.send_notification.call_args.kwargs
        self.assertEqual(kwargs["title"], "Custom Title")
        self.assertEqual(kwargs["message"], "Custom Body")

    def test_default_title_when_omitted(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            self._client.post(
                "/api/system/notifications/test", json={"provider": "bark"}
            )

        kwargs = mock_manager.send_notification.call_args.kwargs
        self.assertEqual(kwargs["title"], "System self-test")
        # 默认 message 包含时间戳前缀
        self.assertIn("R141 self-test", kwargs["message"])

    def test_blank_title_falls_back_to_default(self):
        mock_manager = _make_mock_manager()
        with _patch_manager(mock_manager):
            self._client.post(
                "/api/system/notifications/test",
                json={"provider": "bark", "title": "   "},
            )

        kwargs = mock_manager.send_notification.call_args.kwargs
        self.assertEqual(kwargs["title"], "System self-test")


class TestSwaggerDocAndSourceInvariants(unittest.TestCase):
    """端点源码内 Swagger doc + 关键字段不漂移。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            REPO_ROOT
            / "src"
            / "ai_intervention_agent"
            / "web_ui_routes"
            / "notification.py"
        ).read_text(encoding="utf-8")

    def test_route_registered_in_source(self):
        self.assertIn(
            '@self.app.route("/api/system/notifications/test", methods=["POST"])',
            self.source,
        )

    def test_rate_limit_present(self):
        # 至少 6/min 限流 —— 防滥用 push spam
        self.assertIn('@self.limiter.limit("6 per minute")', self.source)

    def test_swagger_enum_lists_all_providers(self):
        # 5 个合法 provider 全在 swagger enum 字段里
        for value in ("all", "bark", "web", "sound", "system"):
            self.assertIn(value, self.source)

    def test_swagger_tag_is_system(self):
        self.assertIn("- System", self.source)

    def test_self_test_metadata_marker_is_set(self):
        self.assertIn('"r141_self_test": True', self.source)


if __name__ == "__main__":
    unittest.main()
