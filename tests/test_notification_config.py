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
        }
        mock_get_config.return_value = mock_config_mgr

        config = NotificationConfig.from_config_file()

        self.assertTrue(config.enabled)
        self.assertEqual(config.sound_volume, 0.8)  # 转换后
        self.assertTrue(config.bark_enabled)
        self.assertEqual(config.bark_action, "url")

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
        """测试无效音量类型"""
        from notification_manager import NotificationConfig

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {
            "sound_volume": "not a number",
        }
        mock_get_config.return_value = mock_config_mgr

        config = NotificationConfig.from_config_file()
        self.assertEqual(config.sound_volume, 0.8)  # 默认值 80/100

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


if __name__ == "__main__":
    unittest.main()
