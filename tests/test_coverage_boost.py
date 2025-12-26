#!/usr/bin/env python3
"""
AI Intervention Agent - 覆盖率提升测试

针对低覆盖率模块的补充测试用例：
1. config_manager.py (30.34% → 目标 50%+)
2. notification_manager.py (46.40% → 目标 60%+)
3. notification_providers.py (62.74% → 目标 75%+)
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# config_manager.py 覆盖率提升
# ============================================================================


class TestConfigManagerAdvanced(unittest.TestCase):
    """配置管理器高级测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_jsonc_with_trailing_comma(self):
        """测试带尾随逗号的 JSONC"""
        from config_manager import parse_jsonc

        # JSONC 应该能处理尾随逗号（虽然标准 JSON 不允许）
        content = '{"key": "value",}'
        # 这可能会抛出异常，因为 parse_jsonc 只移除注释
        with self.assertRaises(json.JSONDecodeError):
            parse_jsonc(content)

    def test_update_method(self):
        """测试批量更新方法"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "update_test.json"
        with open(config_file, "w") as f:
            json.dump({"a": 1, "b": 2}, f)

        mgr = ConfigManager(str(config_file))

        # 批量更新
        mgr.update({"a": 10, "c": 30}, save=False)

        self.assertEqual(mgr.get("a"), 10)
        self.assertEqual(mgr.get("c"), 30)

    def test_force_save(self):
        """测试强制保存"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "force_save_test.json"
        with open(config_file, "w") as f:
            json.dump({"test": True}, f)

        mgr = ConfigManager(str(config_file))
        mgr.set("test", False, save=False)
        mgr.force_save()

        # 重新加载验证
        with open(config_file, "r") as f:
            saved = json.load(f)

        self.assertEqual(saved.get("test"), False)

    def test_reload_config(self):
        """测试配置重载"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "reload_test.json"
        with open(config_file, "w") as f:
            json.dump({"value": 1}, f)

        mgr = ConfigManager(str(config_file))
        self.assertEqual(mgr.get("value"), 1)

        # 外部修改文件
        with open(config_file, "w") as f:
            json.dump({"value": 2}, f)

        # 重载
        mgr.reload()

        self.assertEqual(mgr.get("value"), 2)

    def test_get_all_config(self):
        """测试获取所有配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "getall_test.json"
        with open(config_file, "w") as f:
            json.dump({"a": 1, "b": {"c": 2}}, f)

        mgr = ConfigManager(str(config_file))
        all_config = mgr.get_all()

        self.assertIn("a", all_config)
        self.assertIn("b", all_config)

    def test_update_section(self):
        """测试更新配置段"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "section_test.json"
        with open(config_file, "w") as f:
            json.dump({"notification": {"enabled": True}}, f)

        mgr = ConfigManager(str(config_file))

        # 更新配置段
        mgr.update_section(
            "notification", {"enabled": False, "new_key": "value"}, save=False
        )

        section = mgr.get_section("notification")
        self.assertEqual(section.get("enabled"), False)
        self.assertEqual(section.get("new_key"), "value")


class TestConfigManagerJsoncSave(unittest.TestCase):
    """JSONC 保存功能测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_save_preserves_content(self):
        """测试保存保留内容"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "preserve_test.jsonc"
        initial_content = """{
    // 配置注释
    "key": "value",
    "number": 42
}"""

        with open(config_file, "w") as f:
            f.write(initial_content)

        mgr = ConfigManager(str(config_file))
        mgr.set("number", 100, save=True)

        # 等待延迟保存
        time.sleep(0.01)  # 减少等待时间
        mgr.force_save()

        # 读取保存后的内容
        with open(config_file, "r") as f:
            saved_content = f.read()

        # 验证值已更新
        from config_manager import parse_jsonc

        saved_config = parse_jsonc(saved_content)
        self.assertEqual(saved_config.get("number"), 100)


# ============================================================================
# notification_manager.py 覆盖率提升
# ============================================================================


class TestNotificationManagerSendNotification(unittest.TestCase):
    """通知发送功能测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_get_config(self):
        """测试获取配置"""
        config = self.manager.get_config()
        self.assertIsNotNone(config)

    def test_register_provider(self):
        """测试注册提供者"""
        from notification_manager import NotificationType

        # 创建模拟提供者
        mock_provider = MagicMock()
        mock_provider.send = MagicMock(return_value=True)

        self.manager.register_provider(NotificationType.WEB, mock_provider)

        # 验证已注册
        self.assertIn(NotificationType.WEB, self.manager._providers)

    def test_update_config_without_save(self):
        """测试更新配置不保存"""
        # update_config_without_save 接受关键字参数
        self.manager.update_config_without_save(bark_enabled=True)

        self.assertEqual(self.manager.config.bark_enabled, True)


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


def run_tests():
    """运行所有覆盖率提升测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # config_manager 测试
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerAdvanced))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerJsoncSave))

    # notification_manager 测试
    suite.addTests(
        loader.loadTestsFromTestCase(TestNotificationManagerSendNotification)
    )
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationEvent))

    # notification_providers 测试
    suite.addTests(loader.loadTestsFromTestCase(TestCreateNotificationProviders))
    suite.addTests(loader.loadTestsFromTestCase(TestBarkProviderAdvanced))
    suite.addTests(loader.loadTestsFromTestCase(TestWebProviderAdvanced))
    suite.addTests(loader.loadTestsFromTestCase(TestSoundProviderAdvanced))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
