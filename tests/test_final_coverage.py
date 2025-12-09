#!/usr/bin/env python3
"""
AI Intervention Agent - 最终覆盖率提升测试

针对剩余未覆盖代码路径的补充测试
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# notification_manager.py 剩余路径测试
# ============================================================================


class TestNotificationManagerProvider(unittest.TestCase):
    """提供者管理测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_get_provider(self):
        """测试获取提供者"""
        from notification_manager import NotificationType

        # 尝试获取提供者
        provider = self.manager._providers.get(NotificationType.WEB)
        # 可能存在或不存在，但不应该抛异常


class TestNotificationManagerQueue(unittest.TestCase):
    """事件队列测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_get_pending_events(self):
        """测试获取待处理事件"""
        # 获取待处理事件数量
        with self.manager._queue_lock:
            pending_count = len(self.manager._event_queue)

        # 不应该抛异常
        self.assertIsInstance(pending_count, int)


class TestNotificationConfigAdvanced(unittest.TestCase):
    """通知配置高级测试"""

    def test_config_all_fields(self):
        """测试所有配置字段"""
        from notification_manager import NotificationConfig

        config = NotificationConfig()

        # 验证所有字段存在
        self.assertIsNotNone(config.enabled)
        self.assertIsNotNone(config.web_enabled)
        self.assertIsNotNone(config.sound_enabled)
        self.assertIsNotNone(config.bark_enabled)
        self.assertIsNotNone(config.sound_mute)

    def test_config_bark_fields(self):
        """测试 Bark 配置字段"""
        from notification_manager import NotificationConfig

        config = NotificationConfig()

        # 验证 Bark 相关字段
        self.assertIsNotNone(config.bark_url)
        self.assertIsNotNone(config.bark_device_key)


# ============================================================================
# config_manager.py 剩余路径测试
# ============================================================================


class TestConfigManagerNetworkSecurity(unittest.TestCase):
    """网络安全配置测试"""

    def test_get_network_security_config(self):
        """测试获取网络安全配置"""
        from config_manager import config_manager

        security_config = config_manager.get_network_security_config()

        self.assertIsNotNone(security_config)
        self.assertIsInstance(security_config, dict)

    def test_network_security_has_bind_interface(self):
        """测试网络安全配置包含绑定接口"""
        from config_manager import config_manager

        security_config = config_manager.get_network_security_config()

        # 应该有 bind_interface 字段
        self.assertIn("bind_interface", security_config)


class TestConfigManagerWebUI(unittest.TestCase):
    """Web UI 配置测试"""

    def test_get_web_ui_config(self):
        """测试获取 Web UI 配置"""
        from config_manager import config_manager

        web_ui_config = config_manager.get_section("web_ui")

        self.assertIsNotNone(web_ui_config)


class TestConfigManagerNotificationSection(unittest.TestCase):
    """通知配置段测试"""

    def test_get_notification_section(self):
        """测试获取通知配置段"""
        from config_manager import config_manager

        notification = config_manager.get_section("notification")

        self.assertIsNotNone(notification)
        self.assertIsInstance(notification, dict)


class TestConfigManagerDefaults(unittest.TestCase):
    """默认值测试"""

    def test_get_with_default(self):
        """测试获取不存在的键返回默认值"""
        from config_manager import config_manager

        result = config_manager.get("nonexistent_key_12345", "default_value")

        self.assertEqual(result, "default_value")

    def test_get_section_default(self):
        """测试获取不存在的配置段返回默认值"""
        from config_manager import config_manager

        result = config_manager.get_section("nonexistent_section_12345")

        # 应该返回空字典或 None
        self.assertTrue(result is None or result == {})


# ============================================================================
# notification_providers.py 剩余路径测试
# ============================================================================


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


def run_tests():
    """运行所有最终覆盖率测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # notification_manager 测试
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerProvider))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerQueue))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationConfigAdvanced))

    # config_manager 测试
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerNetworkSecurity))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerWebUI))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerNotificationSection))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerDefaults))

    # notification_providers 测试
    suite.addTests(loader.loadTestsFromTestCase(TestBarkProviderEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestWebProviderEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestSoundProviderEdgeCases))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
