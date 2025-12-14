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
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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
