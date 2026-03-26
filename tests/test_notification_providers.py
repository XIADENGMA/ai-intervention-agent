#!/usr/bin/env python3
"""
AI Intervention Agent - 通知提供者单元测试

测试覆盖：
1. WebNotificationProvider - Web 浏览器通知
2. SoundNotificationProvider - 声音通知
3. BarkNotificationProvider - Bark 推送通知
4. SystemNotificationProvider - 系统通知
"""

import sys
import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch

from notification_manager import (
    NotificationConfig,
    NotificationEvent,
    NotificationTrigger,
)


def create_event(title="测试", message="消息", metadata=None):
    """创建测试用通知事件"""
    return NotificationEvent(
        id=f"test-{id(title)}",
        title=title,
        message=message,
        trigger=NotificationTrigger.IMMEDIATE,
        metadata=metadata or {},
    )


class TestWebNotificationProvider(unittest.TestCase):
    """测试 Web 通知提供者"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_providers import WebNotificationProvider

        self.config = NotificationConfig()
        self.config.web_enabled = True
        self.config.web_icon = "/icons/icon.svg"
        self.config.web_timeout = 5000
        self.config.web_permission_auto_request = True
        self.config.mobile_optimized = True
        self.config.mobile_vibrate = True

        self.provider = WebNotificationProvider(self.config)

    def test_send_success(self):
        """测试成功发送通知"""
        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        self.assertIn("web_notification_data", event.metadata)

        data = event.metadata["web_notification_data"]
        self.assertEqual(data["title"], "测试标题")
        self.assertEqual(data["message"], "测试消息")
        self.assertEqual(data["type"], "notification")

    def test_send_empty_title(self):
        """测试空标题"""
        event = create_event(title="", message="测试消息")

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_send_empty_message(self):
        """测试空消息"""
        event = create_event(title="测试标题", message="")

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_register_client(self):
        """测试客户端注册"""
        self.provider.register_client("client-1", {"user_agent": "test"})

        self.assertIn("client-1", self.provider.web_clients)

    def test_unregister_client(self):
        """测试客户端注销"""
        self.provider.register_client("client-1", {"user_agent": "test"})
        self.provider.unregister_client("client-1")

        self.assertNotIn("client-1", self.provider.web_clients)


class TestSoundNotificationProvider(unittest.TestCase):
    """测试声音通知提供者"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_providers import SoundNotificationProvider

        self.config = NotificationConfig()
        self.config.sound_enabled = True
        self.config.sound_mute = False
        self.config.sound_volume = 0.8
        self.config.sound_file = "default"

        self.provider = SoundNotificationProvider(self.config)

    def test_send_success(self):
        """测试成功发送声音通知"""
        event = create_event()

        result = self.provider.send(event)

        self.assertTrue(result)
        self.assertIn("sound_notification_data", event.metadata)

        data = event.metadata["sound_notification_data"]
        self.assertEqual(data["type"], "sound")
        self.assertEqual(data["file"], "deng[噔].mp3")
        self.assertEqual(data["volume"], 0.8)

    def test_send_muted(self):
        """测试静音模式"""
        self.config.sound_mute = True

        event = create_event()

        result = self.provider.send(event)

        # 静音模式返回 True，但不准备数据
        self.assertTrue(result)
        self.assertNotIn("sound_notification_data", event.metadata)

    def test_volume_boundary(self):
        """测试音量边界值"""
        # 测试超出边界的音量值
        self.config.sound_volume = 1.5

        event = create_event()

        result = self.provider.send(event)

        self.assertTrue(result)
        data = event.metadata["sound_notification_data"]
        self.assertLessEqual(data["volume"], 1.0)


class TestBarkNotificationProvider(unittest.TestCase):
    """测试 Bark 通知提供者"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_providers import BarkNotificationProvider

        self.config = NotificationConfig()
        self.config.bark_enabled = True
        self.config.bark_url = "https://api.day.app/push"
        self.config.bark_device_key = "test_device_key"
        self.config.bark_icon = ""
        self.config.bark_action = "none"

        self.provider = BarkNotificationProvider(self.config)

    def test_send_disabled(self):
        """测试禁用状态"""
        self.config.bark_enabled = False

        event = create_event()

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_send_incomplete_config(self):
        """测试配置不完整"""
        self.config.bark_device_key = ""

        event = create_event()

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_invalid_url_format(self):
        """测试无效 URL 格式"""
        self.config.bark_url = "invalid-url"

        event = create_event()

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_empty_title(self):
        """测试空标题"""
        event = create_event(title="", message="消息")

        result = self.provider.send(event)

        self.assertFalse(result)

    def test_empty_message(self):
        """测试空消息"""
        event = create_event(title="标题", message="")

        result = self.provider.send(event)

        self.assertFalse(result)

    @patch("notification_providers.requests.Session.post")
    def test_send_success(self, mock_post):
        """测试成功发送（模拟 HTTP）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch("notification_providers.requests.Session.post")
    def test_send_uses_configured_timeout(self, mock_post):
        """应使用配置中的 bark_timeout 作为 requests 超时参数"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_timeout = 3
        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs.get("timeout"), 3)

    @patch("notification_providers.requests.Session.post")
    def test_payload_no_action_field_when_none(self, mock_post):
        """bark_action=none 时不应发送 action/url/copy 字段（避免服务端 4xx）"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "none"
        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertNotIn("action", payload)
        self.assertNotIn("url", payload)
        self.assertNotIn("copy", payload)

    @patch("notification_providers.requests.Session.post")
    def test_payload_url_field_when_action_url(self, mock_post):
        """bark_action=url 时应使用 Bark 的 url 字段"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "url"
        event = create_event(
            title="测试标题",
            message="测试消息",
            metadata={"url": "https://example.com"},
        )

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("url"), "https://example.com")
        self.assertNotIn("action", payload)

    @patch("notification_providers.requests.Session.post")
    def test_payload_copy_field_when_action_copy(self, mock_post):
        """bark_action=copy 时应使用 Bark 的 copy 字段"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        self.config.bark_action = "copy"
        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertTrue(result)
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("copy"), "测试消息")
        self.assertNotIn("action", payload)

    @patch("notification_providers.requests.Session.post")
    def test_send_http_error(self, mock_post):
        """测试 HTTP 错误"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertFalse(result)

    @patch("notification_providers.requests.Session.post")
    def test_send_timeout(self, mock_post):
        """测试超时"""
        import requests

        mock_post.side_effect = requests.exceptions.Timeout()

        event = create_event(title="测试标题", message="测试消息")

        result = self.provider.send(event)

        self.assertFalse(result)


class TestSystemNotificationProvider(unittest.TestCase):
    """测试系统通知提供者"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_providers import SystemNotificationProvider

        self.config = NotificationConfig()
        self.config.web_timeout = 5000

        self.provider = SystemNotificationProvider(self.config)

    def test_check_support(self):
        """测试支持检查"""
        # 验证 supported 属性存在
        self.assertIsInstance(self.provider.supported, bool)

    def test_send_unsupported(self):
        """测试不支持时的行为"""
        # 如果不支持，应该返回 False
        if not self.provider.supported:
            event = create_event()

            result = self.provider.send(event)

            self.assertFalse(result)


class TestCreateNotificationProviders(unittest.TestCase):
    """通知提供者工厂函数测试"""

    def test_create_all_providers(self):
        """测试创建所有提供者"""
        from notification_manager import NotificationConfig, NotificationType
        from notification_providers import create_notification_providers

        config = NotificationConfig()
        config.web_enabled = True
        config.sound_enabled = True
        config.bark_enabled = True

        providers = create_notification_providers(config)

        self.assertIn(NotificationType.WEB, providers)
        self.assertIn(NotificationType.SOUND, providers)
        self.assertIn(NotificationType.BARK, providers)

    def test_create_disabled_providers(self):
        """测试创建禁用的提供者"""
        from notification_manager import NotificationConfig, NotificationType
        from notification_providers import create_notification_providers

        config = NotificationConfig()
        config.web_enabled = False
        config.sound_enabled = False
        config.bark_enabled = False

        providers = create_notification_providers(config)

        # 禁用的提供者不应该被创建
        self.assertNotIn(NotificationType.WEB, providers)
        self.assertNotIn(NotificationType.SOUND, providers)
        self.assertNotIn(NotificationType.BARK, providers)


class TestBarkProviderAdvanced(unittest.TestCase):
    """Bark 提供者高级测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import BarkNotificationProvider

        self.config = NotificationConfig()
        self.config.bark_enabled = True
        self.config.bark_url = "https://api.day.app/push"
        self.config.bark_device_key = "test_device_key"
        self.config.bark_icon = "https://icon.url/icon.png"
        self.config.bark_action = "https://action.url"

        self.provider = BarkNotificationProvider(self.config)

    def test_metadata_serialization(self):
        """测试元数据序列化"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id="test-meta",
                title="标题",
                message="消息",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={
                    "string": "value",
                    "number": 42,
                    "list": [1, 2, 3],
                    "dict": {"nested": "value"},
                    "bool": True,
                    "none": None,
                },
            )

            result = self.provider.send(event)

            self.assertTrue(result)
            mock_post.assert_called_once()

    def test_reserved_keys_skipped(self):
        """测试保留键被跳过"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            # 尝试在元数据中覆盖保留键
            event = NotificationEvent(
                id="test-reserved",
                title="标题",
                message="消息",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={
                    "title": "覆盖的标题",  # 保留键，应被跳过
                    "body": "覆盖的内容",  # 保留键，应被跳过
                    "custom": "允许的值",
                },
            )

            result = self.provider.send(event)

            self.assertTrue(result)

            # 检查调用参数
            call_args = mock_post.call_args
            json_data = call_args.kwargs.get("json", {})

            # 原始标题应该保留
            self.assertEqual(json_data.get("title"), "标题")

    @patch("notification_providers.requests.Session.post")
    def test_all_2xx_success(self, mock_post):
        """测试所有 2xx 状态码都成功"""
        from notification_manager import NotificationEvent, NotificationTrigger

        for status_code in [200, 201, 202, 204]:
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id=f"test-{status_code}",
                title="标题",
                message="消息",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={},
            )

            result = self.provider.send(event)

            self.assertTrue(result, f"状态码 {status_code} 应该成功")


class TestWebProviderAdvanced(unittest.TestCase):
    """Web 提供者高级测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import WebNotificationProvider

        self.config = NotificationConfig()
        self.config.web_enabled = True
        self.config.web_icon = "/icons/custom.svg"
        self.config.web_timeout = 10000
        self.config.web_permission_auto_request = True
        self.config.mobile_optimized = True
        self.config.mobile_vibrate = True

        self.provider = WebNotificationProvider(self.config)

    def test_notification_data_structure(self):
        """测试通知数据结构"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-structure",
            title="测试标题",
            message="测试消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={"extra": "data"},
        )

        result = self.provider.send(event)

        self.assertTrue(result)

        data = event.metadata.get("web_notification_data")
        self.assertIsNotNone(data)
        data = cast(dict[str, Any], data)
        self.assertEqual(data["type"], "notification")
        self.assertIn("config", data)
        config = cast(dict[str, Any], data["config"])
        self.assertEqual(config["icon"], "/icons/custom.svg")
        self.assertEqual(config["timeout"], 10000)

    def test_whitespace_trimming(self):
        """测试空白字符修剪"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-trim",
            title="  带空格的标题  ",
            message="  带空格的消息  ",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = self.provider.send(event)

        self.assertTrue(result)

        data = event.metadata.get("web_notification_data")
        self.assertIsNotNone(data)
        data = cast(dict[str, Any], data)
        self.assertEqual(data["title"], "带空格的标题")
        self.assertEqual(data["message"], "带空格的消息")


class TestSoundProviderAdvanced(unittest.TestCase):
    """声音提供者高级测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import SoundNotificationProvider

        self.config = NotificationConfig()
        self.config.sound_enabled = True
        self.config.sound_mute = False
        self.config.sound_volume = 0.5
        self.config.sound_file = "deng"

        self.provider = SoundNotificationProvider(self.config)

    def test_sound_file_mapping(self):
        """测试声音文件映射"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-sound",
            title="测试",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = self.provider.send(event)

        self.assertTrue(result)

        data = event.metadata.get("sound_notification_data")
        self.assertIsNotNone(data)
        data = cast(dict[str, Any], data)
        self.assertEqual(data["file"], "deng[噔].mp3")

    def test_unknown_sound_file_fallback(self):
        """测试未知声音文件回退到默认"""
        from notification_manager import NotificationEvent, NotificationTrigger
        from notification_providers import SoundNotificationProvider

        self.config.sound_file = "unknown_sound"
        provider = SoundNotificationProvider(self.config)

        event = NotificationEvent(
            id="test-fallback",
            title="测试",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = provider.send(event)

        self.assertTrue(result)

        data = event.metadata.get("sound_notification_data")
        # 应该回退到默认声音文件
        self.assertIsNotNone(data)
        data = cast(dict[str, Any], data)
        self.assertEqual(data["file"], "deng[噔].mp3")


class TestBarkProviderEdgeCases(unittest.TestCase):
    """Bark 提供者边界测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import BarkNotificationProvider

        self.config = NotificationConfig()
        self.config.bark_enabled = True
        self.config.bark_url = "https://api.day.app/push"
        self.config.bark_device_key = "test_key"

        self.provider = BarkNotificationProvider(self.config)

    def test_send_with_special_characters(self):
        """测试发送带特殊字符的通知"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id="test-special",
                title="标题 <script>alert('xss')</script>",
                message="消息 & 特殊字符 \"引号\" '单引号'",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={},
            )

            result = self.provider.send(event)

            self.assertTrue(result)

    def test_send_with_unicode(self):
        """测试发送 Unicode 内容"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id="test-unicode",
                title="🎉 庆祝 🎊",
                message="日本語 한국어 العربية",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={},
            )

            result = self.provider.send(event)

            self.assertTrue(result)

    def test_send_with_empty_metadata(self):
        """测试发送空元数据"""
        from notification_manager import NotificationEvent, NotificationTrigger

        with patch.object(self.provider.session, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            event = NotificationEvent(
                id="test-empty-meta",
                title="标题",
                message="消息",
                trigger=NotificationTrigger.IMMEDIATE,
                metadata={},
            )

            result = self.provider.send(event)

            self.assertTrue(result)


class TestWebProviderEdgeCases(unittest.TestCase):
    """Web 提供者边界测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import WebNotificationProvider

        self.config = NotificationConfig()
        self.config.web_enabled = True

        self.provider = WebNotificationProvider(self.config)

    def test_send_with_long_title(self):
        """测试发送超长标题"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-long-title",
            title="长" * 1000,
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = self.provider.send(event)

        self.assertTrue(result)

    def test_send_with_long_message(self):
        """测试发送超长消息"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-long-message",
            title="标题",
            message="消" * 10000,
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        result = self.provider.send(event)

        self.assertTrue(result)


class TestSoundProviderEdgeCases(unittest.TestCase):
    """声音提供者边界测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig
        from notification_providers import SoundNotificationProvider

        self.config = NotificationConfig()
        self.config.sound_enabled = True
        self.config.sound_mute = False
        self.config.sound_volume = 0.5

        self.provider = SoundNotificationProvider(self.config)

    def test_volume_zero(self):
        """测试音量为 0"""
        from notification_providers import SoundNotificationProvider

        self.config.sound_volume = 0.0
        provider = SoundNotificationProvider(self.config)

        # 音量为 0 时不应该抛异常
        self.assertIsNotNone(provider)

    def test_volume_max(self):
        """测试音量为最大"""
        from notification_providers import SoundNotificationProvider

        self.config.sound_volume = 1.0
        provider = SoundNotificationProvider(self.config)

        # 音量为最大时不应该抛异常
        self.assertIsNotNone(provider)


class TestNotificationProvidersExceptions(unittest.TestCase):
    """通知提供者异常处理测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationConfig

        self.config = NotificationConfig()

    def test_bark_network_unavailable(self):
        """测试 Bark 网络不可用"""
        import requests

        from notification_manager import NotificationEvent, NotificationTrigger
        from notification_providers import BarkNotificationProvider

        self.config.bark_enabled = True
        # 使用 mock 避免真实网络请求（确保离线可重复）
        self.config.bark_url = "https://example.invalid/push"
        self.config.bark_device_key = "test"

        provider = BarkNotificationProvider(self.config)

        event = NotificationEvent(
            id="test-1",
            title="测试",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={},
        )

        # 应该返回 False，不应该抛出异常
        with patch(
            "notification_providers.requests.Session.post",
            side_effect=requests.exceptions.RequestException("network down"),
        ):
            result = provider.send(event)
        self.assertFalse(result)

    def test_web_provider_with_none_metadata(self):
        """测试 Web 提供者处理 None metadata"""
        from notification_manager import NotificationEvent, NotificationTrigger
        from notification_providers import WebNotificationProvider

        provider = WebNotificationProvider(self.config)

        event = NotificationEvent(
            id="test-1",
            title="测试",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata=cast(Any, None),  # 测试 None（绕过类型检查器）
        )
        # 手动设置 metadata 为 None 来测试
        event.metadata = cast(Any, None)

        # 应该不崩溃
        try:
            result = provider.send(event)
            # 可能返回 True 或 False
        except Exception as e:
            self.fail(f"不应该抛出异常: {e}")


# ============================================================================
# 并发压力测试
# ============================================================================


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestWebNotificationProvider))
    suite.addTests(loader.loadTestsFromTestCase(TestSoundNotificationProvider))
    suite.addTests(loader.loadTestsFromTestCase(TestBarkNotificationProvider))
    suite.addTests(loader.loadTestsFromTestCase(TestSystemNotificationProvider))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
