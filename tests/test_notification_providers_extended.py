"""notification_providers.py 扩展单元测试。

覆盖基础测试未触及的边界路径：
- BarkNotificationProvider.close() 异常（lines 200-201）
- Bark send: URL action 无可用链接（263->269）
- Bark send: copy action 从 metadata 取值（280->285）
- Bark send: debug/test metadata 写入异常（lines 355-357）
- SystemNotificationProvider: plyer 导入路径
- create_notification_providers: SystemNotificationProvider 创建异常（455-458）
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from notification_models import (
    NotificationEvent,
    NotificationTrigger,
    NotificationType,
)
from notification_providers import (
    BarkNotificationProvider,
    create_notification_providers,
)


def _make_config(**overrides) -> MagicMock:
    """创建 NotificationConfig 并覆盖默认值"""
    defaults = {
        "web_enabled": False,
        "sound_enabled": False,
        "bark_enabled": True,
        "bark_url": "https://api.day.app/push",
        "bark_device_key": "test_key",
        "bark_icon": "",
        "bark_action": "none",
        "bark_timeout": 10,
        "web_timeout": 5000,
        "web_icon": "",
        "web_permission_auto_request": True,
        "mobile_optimized": False,
        "mobile_vibrate": True,
        "sound_volume": 0.8,
        "sound_file": "default",
        "sound_mute": False,
        "debug": False,
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg  # type: ignore[return-value]


def _make_event(**overrides) -> NotificationEvent:
    defaults = {
        "id": "test-event-001",
        "title": "测试标题",
        "message": "测试消息",
        "trigger": NotificationTrigger.IMMEDIATE,
        "types": [NotificationType.BARK],
        "metadata": {},
    }
    defaults.update(overrides)
    return NotificationEvent(**defaults)  # type: ignore[arg-type]


class TestBarkCloseException(unittest.TestCase):
    """BarkNotificationProvider.close() 异常"""

    def test_close_session_error_swallowed(self):
        """session.close() 抛出异常时不传播（lines 200-201）"""
        cfg = _make_config()
        provider = BarkNotificationProvider(cfg)
        provider.session.close = MagicMock(side_effect=RuntimeError("close error"))  # type: ignore[assignment]
        provider.close()

    def test_close_success(self):
        """正常关闭不抛异常"""
        cfg = _make_config()
        provider = BarkNotificationProvider(cfg)
        provider.close()


class TestBarkUrlActionNoLink(unittest.TestCase):
    """Bark URL action 但无可用链接"""

    def test_url_action_no_link_in_metadata(self):
        """bark_action=url 但 metadata 无链接时仍能发送（263->269）"""
        cfg = _make_config(bark_action="url")
        provider = BarkNotificationProvider(cfg)
        event = _make_event(metadata={"custom_key": "no_url_here"})

        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            result = provider.send(event)

        self.assertTrue(result)


class TestBarkCopyAction(unittest.TestCase):
    """Bark copy action 路径"""

    def test_copy_action_from_metadata(self):
        """bark_action=copy 且 metadata 提供 copy_text（280->285）"""
        cfg = _make_config(bark_action="copy")
        provider = BarkNotificationProvider(cfg)
        event = _make_event(metadata={"copy_text": "要复制的内容"})

        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            result = provider.send(event)

        self.assertTrue(result)
        call_kwargs = mock_post.call_args
        bark_data = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        self.assertEqual(bark_data["copy"], "要复制的内容")

    def test_copy_action_fallback_to_message(self):
        """bark_action=copy 但 metadata 无 copy_text 时使用消息正文"""
        cfg = _make_config(bark_action="copy")
        provider = BarkNotificationProvider(cfg)
        event = _make_event(metadata={})

        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            result = provider.send(event)

        self.assertTrue(result)
        call_kwargs = mock_post.call_args
        bark_data = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        self.assertEqual(bark_data["copy"], "测试消息")


class TestBarkDebugMetadataWriteException(unittest.TestCase):
    """debug/test 元数据写入异常"""

    def test_metadata_write_error_swallowed(self):
        """写入 bark_error 到 metadata 失败时不影响主流程（lines 355-357）"""
        cfg = _make_config(debug=True)
        provider = BarkNotificationProvider(cfg)
        event = _make_event()

        frozen_metadata: dict = {}

        class FrozenDict(dict):
            def __setitem__(self, key, value):
                if key == "bark_error":
                    raise TypeError("immutable")
                super().__setitem__(key, value)

        event.metadata = FrozenDict(frozen_metadata)  # type: ignore[assignment]

        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.json.return_value = {"code": 400, "message": "bad"}
            mock_resp.text = "bad request"
            mock_post.return_value = mock_resp
            result = provider.send(event)

        self.assertFalse(result)


class TestSystemProviderCreationException(unittest.TestCase):
    """create_notification_providers 中 SystemNotificationProvider 创建异常"""

    def test_system_provider_exception_swallowed(self):
        """SystemNotificationProvider 构造失败时不阻塞其他 provider（lines 455-458）"""
        cfg = _make_config(web_enabled=True, sound_enabled=False, bark_enabled=False)
        with patch(
            "notification_providers.SystemNotificationProvider",
            side_effect=RuntimeError("init failed"),
        ):
            providers = create_notification_providers(cfg)
        self.assertIn(NotificationType.WEB, providers)
        self.assertNotIn(NotificationType.SYSTEM, providers)


class TestSystemProviderPlyerImportSuccess(unittest.TestCase):
    """lines 396-400: plyer 导入成功 → supported=True"""

    def test_plyer_available(self):
        """模拟 pyobjus 可用 + plyer 可导入"""
        from notification_providers import SystemNotificationProvider

        cfg = _make_config()
        mock_notify = MagicMock()
        mock_module = MagicMock()
        mock_module.notify = mock_notify
        with patch("notification_providers.find_spec", return_value=MagicMock()):
            with patch.dict(
                "sys.modules", {"plyer": MagicMock(), "plyer.notification": mock_module}
            ):
                provider = SystemNotificationProvider(cfg)
                self.assertTrue(provider.supported)
                self.assertIsNotNone(provider._notify)


class TestSystemProviderPlyerImportError(unittest.TestCase):
    """lines 401-404: plyer 不可用时 ImportError 被捕获"""

    def test_plyer_import_error_caught(self):
        from notification_providers import SystemNotificationProvider

        cfg = _make_config()
        with patch("notification_providers.find_spec", return_value=MagicMock()):
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "plyer" or name.startswith("plyer."):
                    raise ImportError("no plyer")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                provider = SystemNotificationProvider(cfg)
                self.assertFalse(provider.supported)
                self.assertIsNone(provider._notify)


class TestCreateProvidersSystemSupported(unittest.TestCase):
    """lines 455-456: system_provider.supported=True 时加入 providers"""

    def test_system_provider_added_when_supported(self):
        cfg = _make_config(web_enabled=False, sound_enabled=False, bark_enabled=False)
        mock_provider = MagicMock()
        mock_provider.supported = True
        with patch(
            "notification_providers.SystemNotificationProvider",
            return_value=mock_provider,
        ):
            providers = create_notification_providers(cfg)
        self.assertIn(NotificationType.SYSTEM, providers)


class TestBarkCopyActionWithMetadata(unittest.TestCase):
    """branch 280->285: bark_action=copy + 元数据含 copy 键"""

    def test_copy_action_with_copy_metadata(self):
        from notification_providers import BarkNotificationProvider

        cfg = _make_config(bark_enabled=True)
        cfg.bark_device_key = "test_key"
        cfg.bark_server_url = "https://bark.example.com"
        cfg.bark_action = "copy"
        cfg.bark_icon = ""

        provider = BarkNotificationProvider(cfg)

        from notification_models import NotificationTrigger

        event = NotificationEvent(
            id="test-copy",
            title="标题",
            message="内容",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={"copy": "  自定义复制内容  "},
        )

        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"code": 200}
            mock_post.return_value = mock_resp
            result = provider.send(event)

        self.assertTrue(result)
        call_json = mock_post.call_args[1].get("json") or mock_post.call_args[0][0]
        if isinstance(call_json, dict):
            self.assertEqual(call_json.get("copy"), "自定义复制内容")


class TestBarkCopyActionNoMetadata(unittest.TestCase):
    """branch 280->285: Bark copy 行为但 metadata 为空时回退到消息正文"""

    def test_copy_action_empty_metadata_uses_message(self):
        cfg = _make_config(bark_action="copy")
        provider = BarkNotificationProvider(cfg)
        event = _make_event(
            id="bark-copy-no-meta",
            message="fallback body",
            metadata={},
        )
        with patch.object(provider.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"code": 200}
            mock_post.return_value = mock_resp
            result = provider.send(event)

        self.assertTrue(result)
        call_json = mock_post.call_args[1].get("json") or mock_post.call_args[0][0]
        if isinstance(call_json, dict):
            self.assertEqual(call_json.get("copy"), "fallback body")


if __name__ == "__main__":
    unittest.main()
