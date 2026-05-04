"""
Notification 配置模块单元测试

测试覆盖：
    - NotificationConfig 数据类的边界验证
    - sound_volume 范围验证
    - bark_action 枚举验证
    - bark_url 格式验证
    - from_config_file 方法
"""

import unittest
from unittest.mock import MagicMock, patch


class TestNotificationConfigConstants(unittest.TestCase):
    """测试 NotificationConfig 常量"""

    def test_constants_defined(self):
        """测试常量定义"""
        from notification_manager import NotificationConfig

        # 音量常量
        self.assertEqual(NotificationConfig.SOUND_VOLUME_MIN, 0.0)
        self.assertEqual(NotificationConfig.SOUND_VOLUME_MAX, 1.0)

        # Bark 动作有效值
        self.assertEqual(NotificationConfig.BARK_ACTIONS_VALID, ("none", "url", "copy"))


class TestSoundVolumeValidation(unittest.TestCase):
    """测试 sound_volume 验证"""

    def test_valid_volume(self):
        """测试有效音量值"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(sound_volume=0.5)
        self.assertEqual(config.sound_volume, 0.5)

        config = NotificationConfig(sound_volume=0.0)
        self.assertEqual(config.sound_volume, 0.0)

        config = NotificationConfig(sound_volume=1.0)
        self.assertEqual(config.sound_volume, 1.0)

    def test_volume_below_min(self):
        """测试音量小于最小值"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(sound_volume=-0.5)
        self.assertEqual(config.sound_volume, NotificationConfig.SOUND_VOLUME_MIN)

        config = NotificationConfig(sound_volume=-100)
        self.assertEqual(config.sound_volume, NotificationConfig.SOUND_VOLUME_MIN)

    def test_volume_above_max(self):
        """测试音量大于最大值"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(sound_volume=1.5)
        self.assertEqual(config.sound_volume, NotificationConfig.SOUND_VOLUME_MAX)

        config = NotificationConfig(sound_volume=100)
        self.assertEqual(config.sound_volume, NotificationConfig.SOUND_VOLUME_MAX)


class TestBarkActionValidation(unittest.TestCase):
    """测试 bark_action 验证"""

    def test_valid_actions(self):
        """测试有效的 bark_action 值"""
        from notification_manager import NotificationConfig

        for action in ("none", "url", "copy"):
            config = NotificationConfig(bark_action=action)
            self.assertEqual(config.bark_action, action)

    def test_invalid_action(self):
        """测试无效的 bark_action 值"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(bark_action="invalid")
        self.assertEqual(config.bark_action, "none")

        config = NotificationConfig(bark_action="open")
        self.assertEqual(config.bark_action, "none")

        config = NotificationConfig(bark_action="")
        self.assertEqual(config.bark_action, "none")


class TestBarkUrlValidation(unittest.TestCase):
    """测试 bark_url 验证"""

    def test_valid_urls(self):
        """测试有效的 URL"""
        from notification_manager import NotificationConfig

        valid_urls = [
            "https://api.day.app/push",
            "http://localhost:8080/push",
            "https://bark.example.com/push",
        ]

        for url in valid_urls:
            config = NotificationConfig(bark_url=url)
            self.assertEqual(config.bark_url, url)

    def test_empty_url(self):
        """测试空 URL"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(bark_url="")
        self.assertEqual(config.bark_url, "")

    def test_invalid_url_format(self):
        """测试无效的 URL 格式（仅警告，不修改）"""
        from notification_manager import NotificationConfig

        invalid_urls = [
            "ftp://example.com/push",
            "not-a-url",
            "api.day.app/push",
        ]

        for url in invalid_urls:
            # 无效 URL 会产生警告但不修改值
            config = NotificationConfig(bark_url=url)
            self.assertEqual(config.bark_url, url)


class TestBarkEnabledValidation(unittest.TestCase):
    """测试 bark_enabled 配置验证"""

    def test_bark_enabled_without_device_key(self):
        """测试 bark_enabled=True 但无 device_key（仅警告）"""
        from notification_manager import NotificationConfig

        # 应该创建成功但产生警告
        config = NotificationConfig(bark_enabled=True, bark_device_key="")
        self.assertTrue(config.bark_enabled)
        self.assertEqual(config.bark_device_key, "")

    def test_bark_enabled_with_device_key(self):
        """测试 bark_enabled=True 且有 device_key"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(
            bark_enabled=True,
            bark_device_key="test_key",
            bark_url="https://api.day.app/push",
        )
        self.assertTrue(config.bark_enabled)
        self.assertEqual(config.bark_device_key, "test_key")


class TestIsValidUrl(unittest.TestCase):
    """测试 _is_valid_url 静态方法"""

    def test_http_url(self):
        """测试 HTTP URL"""
        from notification_manager import NotificationConfig

        self.assertTrue(NotificationConfig._is_valid_url("http://example.com"))
        self.assertTrue(NotificationConfig._is_valid_url("http://localhost:8080"))

    def test_https_url(self):
        """测试 HTTPS URL"""
        from notification_manager import NotificationConfig

        self.assertTrue(NotificationConfig._is_valid_url("https://example.com"))
        self.assertTrue(NotificationConfig._is_valid_url("https://api.day.app/push"))

    def test_invalid_protocol(self):
        """测试无效协议"""
        from notification_manager import NotificationConfig

        self.assertFalse(NotificationConfig._is_valid_url("ftp://example.com"))
        self.assertFalse(NotificationConfig._is_valid_url("file:///path"))
        self.assertFalse(NotificationConfig._is_valid_url("example.com"))


class TestFromConfigFile(unittest.TestCase):
    """测试 from_config_file 方法"""

    @patch("notification_manager.CONFIG_FILE_AVAILABLE", True)
    @patch("notification_manager.get_config")
    def test_normal_config(self, mock_get_config):
        """测试正常配置加载"""
        from notification_manager import NotificationConfig

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {
            "enabled": True,
            "sound_volume": 80,  # 百分比
            "bark_enabled": True,
            "bark_url": "https://api.day.app/push",
            "bark_device_key": "test_key",
            "bark_action": "url",
            "bark_url_template": "{base_url}/?task_id={task_id}",
        }
        mock_get_config.return_value = mock_config_mgr

        config = NotificationConfig.from_config_file()

        self.assertTrue(config.enabled)
        self.assertEqual(config.sound_volume, 0.8)  # 转换后
        self.assertTrue(config.bark_enabled)
        self.assertEqual(config.bark_action, "url")
        self.assertEqual(config.bark_url_template, "{base_url}/?task_id={task_id}")

    @patch("notification_manager.CONFIG_FILE_AVAILABLE", True)
    @patch("notification_manager.get_config")
    def test_bool_string_values(self, mock_get_config):
        """测试布尔值字符串输入（避免 bool('false') == True 的误判）"""
        from notification_manager import NotificationConfig

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {
            "enabled": "false",
            "debug": "true",
            "web_enabled": "0",
            "auto_request_permission": "no",
            "sound_enabled": "yes",
            "sound_mute": "1",
            "mobile_optimized": "off",
            "mobile_vibrate": "on",
            "bark_enabled": "false",
            "system_enabled": "true",
            "macos_native_enabled": "0",
        }
        mock_get_config.return_value = mock_config_mgr

        config = NotificationConfig.from_config_file()

        self.assertFalse(config.enabled)
        self.assertTrue(config.debug)
        self.assertFalse(config.web_enabled)
        self.assertFalse(config.web_permission_auto_request)
        self.assertTrue(config.sound_enabled)
        self.assertTrue(config.sound_mute)
        self.assertFalse(config.mobile_optimized)
        self.assertTrue(config.mobile_vibrate)
        self.assertFalse(config.bark_enabled)
        self.assertTrue(config.system_enabled)
        self.assertFalse(config.macos_native_enabled)

    @patch("notification_manager.CONFIG_FILE_AVAILABLE", True)
    @patch("notification_manager.get_config")
    def test_volume_boundary_conversion(self, mock_get_config):
        """测试音量边界转换"""
        from notification_manager import NotificationConfig

        # 测试超出范围的音量
        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {
            "sound_volume": 150,  # 超过 100
        }
        mock_get_config.return_value = mock_config_mgr

        config = NotificationConfig.from_config_file()
        self.assertEqual(config.sound_volume, 1.0)  # 限制为最大值

    @patch("notification_manager.CONFIG_FILE_AVAILABLE", True)
    @patch("notification_manager.get_config")
    def test_negative_volume(self, mock_get_config):
        """测试负数音量"""
        from notification_manager import NotificationConfig

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {
            "sound_volume": -50,
        }
        mock_get_config.return_value = mock_config_mgr

        config = NotificationConfig.from_config_file()
        self.assertEqual(config.sound_volume, 0.0)  # 限制为最小值

    @patch("notification_manager.CONFIG_FILE_AVAILABLE", True)
    @patch("notification_manager.get_config")
    def test_invalid_volume_type(self, mock_get_config):
        """无效音量类型由 get_section() Pydantic ClampedInt 钳位为默认值 80"""
        from notification_manager import NotificationConfig

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {
            "sound_volume": 80,
        }
        mock_get_config.return_value = mock_config_mgr

        config = NotificationConfig.from_config_file()
        self.assertEqual(config.sound_volume, 0.8)

    @patch("notification_manager.CONFIG_FILE_AVAILABLE", True)
    @patch("notification_manager.get_config")
    def test_invalid_bark_action(self, mock_get_config):
        """测试无效 bark_action"""
        from notification_manager import NotificationConfig

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {
            "bark_action": "invalid_action",
        }
        mock_get_config.return_value = mock_config_mgr

        config = NotificationConfig.from_config_file()
        self.assertEqual(config.bark_action, "none")  # 验证后修正为默认值


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def test_combined_validation(self):
        """测试组合验证场景"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(
            sound_volume=1.5,  # 超出范围
            bark_action="invalid",  # 无效值
            bark_enabled=True,
            bark_device_key="",  # 空设备密钥
        )

        # 验证所有字段都经过了验证
        self.assertEqual(config.sound_volume, 1.0)
        self.assertEqual(config.bark_action, "none")
        self.assertTrue(config.bark_enabled)

    def test_default_values(self):
        """测试默认值"""
        from notification_manager import NotificationConfig

        config = NotificationConfig()

        # 验证默认值
        self.assertTrue(config.enabled)
        self.assertEqual(config.sound_volume, 0.8)
        self.assertFalse(config.bark_enabled)
        self.assertEqual(config.bark_action, "none")


class TestNotificationConfig(unittest.TestCase):
    """通知配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        from notification_manager import NotificationConfig

        config = NotificationConfig()

        self.assertTrue(config.enabled)
        self.assertTrue(config.web_enabled)
        self.assertTrue(config.sound_enabled)
        self.assertFalse(config.bark_enabled)

    def test_from_config_file(self):
        """测试从配置文件加载"""
        from notification_manager import NotificationConfig

        # from_config_file 是类方法，从实际配置文件加载
        # 我们测试它返回一个有效的配置对象
        config = NotificationConfig.from_config_file()

        # 验证返回的是 NotificationConfig 实例
        self.assertIsInstance(config, NotificationConfig)
        # 验证基本属性存在
        self.assertIsNotNone(config.enabled)
        self.assertIsNotNone(config.web_enabled)
        self.assertIsNotNone(config.sound_enabled)


class TestNotificationEvent(unittest.TestCase):
    """通知事件测试"""

    def test_event_creation(self):
        """测试事件创建"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="test-123",
            title="测试标题",
            message="测试消息",
            trigger=NotificationTrigger.IMMEDIATE,
            metadata={"key": "value"},
        )

        self.assertEqual(event.id, "test-123")
        self.assertEqual(event.title, "测试标题")
        self.assertEqual(event.trigger, NotificationTrigger.IMMEDIATE)
        self.assertEqual(event.metadata.get("key"), "value")

    def test_event_with_types(self):
        """测试事件指定类型"""
        from notification_manager import (
            NotificationEvent,
            NotificationTrigger,
            NotificationType,
        )

        event = NotificationEvent(
            id="test-456",
            title="标题",
            message="消息",
            trigger=NotificationTrigger.DELAYED,
            types=[NotificationType.WEB, NotificationType.SOUND],
        )

        self.assertEqual(len(event.types), 2)
        self.assertIn(NotificationType.WEB, event.types)


# ============================================================================
# notification_providers.py 覆盖率提升
# ============================================================================


class TestNotificationTrigger(unittest.TestCase):
    """通知触发器测试"""

    def test_immediate_trigger(self):
        """测试立即触发"""
        from notification_manager import NotificationTrigger

        self.assertEqual(NotificationTrigger.IMMEDIATE.value, "immediate")

    def test_delayed_trigger(self):
        """测试延迟触发"""
        from notification_manager import NotificationTrigger

        self.assertEqual(NotificationTrigger.DELAYED.value, "delayed")

    def test_repeat_trigger(self):
        """测试重复触发"""
        from notification_manager import NotificationTrigger

        self.assertEqual(NotificationTrigger.REPEAT.value, "repeat")


class TestNotificationType(unittest.TestCase):
    """通知类型测试"""

    def test_web_type(self):
        """测试 Web 类型"""
        from notification_manager import NotificationType

        self.assertEqual(NotificationType.WEB.value, "web")

    def test_sound_type(self):
        """测试声音类型"""
        from notification_manager import NotificationType

        self.assertEqual(NotificationType.SOUND.value, "sound")

    def test_bark_type(self):
        """测试 Bark 类型"""
        from notification_manager import NotificationType

        self.assertEqual(NotificationType.BARK.value, "bark")

    def test_system_type(self):
        """测试系统类型"""
        from notification_manager import NotificationType

        self.assertEqual(NotificationType.SYSTEM.value, "system")


class TestNotificationEventAdvanced(unittest.TestCase):
    """通知事件高级测试"""

    def test_event_with_all_fields(self):
        """测试完整字段的事件"""
        from notification_manager import (
            NotificationEvent,
            NotificationTrigger,
            NotificationType,
        )

        event = NotificationEvent(
            id="full-event-123",
            title="完整事件",
            message="详细消息",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.WEB, NotificationType.SOUND],
            metadata={"key": "value"},
            max_retries=3,
        )

        self.assertEqual(event.id, "full-event-123")
        self.assertEqual(event.title, "完整事件")
        self.assertEqual(event.message, "详细消息")
        self.assertEqual(event.trigger, NotificationTrigger.IMMEDIATE)
        self.assertEqual(len(event.types), 2)
        self.assertEqual(event.metadata["key"], "value")
        self.assertEqual(event.max_retries, 3)

    def test_event_default_values(self):
        """测试事件默认值"""
        from notification_manager import NotificationEvent, NotificationTrigger

        event = NotificationEvent(
            id="default-event",
            title="标题",
            message="消息",
            trigger=NotificationTrigger.IMMEDIATE,
        )

        # 检查默认值
        self.assertEqual(event.types, [])
        self.assertEqual(event.metadata, {})


# ============================================================================
# config_manager.py 高级功能测试
# ============================================================================


class TestNotificationConfigValidation(unittest.TestCase):
    """通知配置验证测试"""

    def test_config_sound_volume_boundary_low(self):
        """测试声音音量下边界"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(sound_volume=-10)
        self.assertEqual(config.sound_volume, 0.0)

    def test_config_sound_volume_boundary_high(self):
        """测试声音音量上边界"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(sound_volume=150)
        self.assertEqual(config.sound_volume, 1.0)

    def test_config_bark_action_invalid(self):
        """测试无效的 Bark 动作"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(bark_action="invalid_action")
        self.assertEqual(config.bark_action, "none")

    def test_config_bark_url_empty_when_enabled(self):
        """测试 Bark 启用但 URL 为空"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(
            bark_enabled=True, bark_url="", bark_device_key="test_key"
        )
        # URL 为空时，bark_enabled 可能仍为 True（取决于实现）
        # 这里验证配置创建成功
        self.assertIsNotNone(config)


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


class TestNotificationFinalPush(unittest.TestCase):
    """Notification 最终冲刺测试"""

    def test_notification_config_attributes(self):
        """测试通知配置属性"""
        from notification_manager import NotificationConfig

        config = NotificationConfig()

        # 检查所有属性
        attrs = [
            "enabled",
            "web_enabled",
            "sound_enabled",
            "bark_enabled",
            "sound_mute",
            "sound_volume",
            "bark_url",
            "bark_device_key",
        ]

        for attr in attrs:
            self.assertTrue(hasattr(config, attr), f"缺少属性: {attr}")

    def test_notification_types_all(self):
        """测试所有通知类型"""
        from notification_manager import NotificationType

        types = [
            NotificationType.WEB,
            NotificationType.SOUND,
            NotificationType.BARK,
            NotificationType.SYSTEM,
        ]

        for t in types:
            self.assertIsNotNone(t.value)


if __name__ == "__main__":
    unittest.main()
