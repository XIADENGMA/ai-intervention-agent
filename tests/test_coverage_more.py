#!/usr/bin/env python3
"""
AI Intervention Agent - 进一步覆盖率提升测试

针对未覆盖代码路径的补充测试：
1. notification_manager.py - send_notification, _process_event
2. config_manager.py - 高级功能
"""

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# notification_manager.py 未覆盖路径测试
# ============================================================================


class TestNotificationManagerSend(unittest.TestCase):
    """通知发送功能测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_send_notification_disabled(self):
        """测试通知禁用时不发送"""
        # 暂时禁用通知
        original_enabled = self.manager.config.enabled
        self.manager.config.enabled = False

        try:
            from notification_manager import NotificationTrigger

            result = self.manager.send_notification(
                title="测试", message="消息", trigger=NotificationTrigger.IMMEDIATE
            )

            # 应该返回空字符串
            self.assertEqual(result, "")
        finally:
            self.manager.config.enabled = original_enabled

    def test_send_notification_immediate(self):
        """测试立即发送通知"""
        from notification_manager import NotificationTrigger, NotificationType

        # 确保通知启用
        original_enabled = self.manager.config.enabled
        self.manager.config.enabled = True

        try:
            result = self.manager.send_notification(
                title="立即通知",
                message="测试消息",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            # 应该返回事件 ID
            self.assertTrue(result.startswith("notification_"))
        finally:
            self.manager.config.enabled = original_enabled

    def test_send_notification_with_metadata(self):
        """测试带元数据的通知"""
        from notification_manager import NotificationTrigger, NotificationType

        original_enabled = self.manager.config.enabled
        self.manager.config.enabled = True

        try:
            result = self.manager.send_notification(
                title="元数据通知",
                message="测试消息",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
                metadata={"extra": "data", "number": 42},
            )

            self.assertTrue(result.startswith("notification_"))
        finally:
            self.manager.config.enabled = original_enabled


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


class TestConfigManagerDelayedSave(unittest.TestCase):
    """配置管理器延迟保存测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_delayed_save(self):
        """测试延迟保存"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "delayed_save.json"
        with open(config_file, "w") as f:
            json.dump({"test": 1}, f)

        mgr = ConfigManager(str(config_file))

        # 设置值，启用延迟保存
        mgr.set("test", 2, save=True)

        # 强制保存
        mgr.force_save()

        # 验证保存成功
        with open(config_file, "r") as f:
            saved = json.load(f)

        self.assertEqual(saved.get("test"), 2)


class TestConfigManagerNestedConfig(unittest.TestCase):
    """嵌套配置测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_nested_get(self):
        """测试嵌套获取"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "nested.json"
        with open(config_file, "w") as f:
            json.dump({"level1": {"level2": {"level3": "deep_value"}}}, f)

        mgr = ConfigManager(str(config_file))

        # 获取嵌套值
        section = mgr.get_section("level1")
        self.assertIsNotNone(section)
        self.assertIn("level2", section)

    def test_nested_update(self):
        """测试嵌套更新"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "nested_update.json"
        with open(config_file, "w") as f:
            json.dump({"section": {"key1": "value1"}}, f)

        mgr = ConfigManager(str(config_file))

        # 更新嵌套配置段
        mgr.update_section("section", {"key2": "value2"}, save=False)

        section = mgr.get_section("section")
        self.assertEqual(section.get("key1"), "value1")
        self.assertEqual(section.get("key2"), "value2")


class TestReadWriteLock(unittest.TestCase):
    """读写锁测试"""

    def test_read_lock_context_manager(self):
        """测试读锁上下文管理器"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()

        # 使用上下文管理器获取读锁
        with lock.read_lock():
            # 在读锁内部可以执行操作
            self.assertEqual(lock._readers, 1)

        # 离开上下文后读者计数应该为 0
        self.assertEqual(lock._readers, 0)

    def test_write_lock_context_manager(self):
        """测试写锁上下文管理器"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()

        # 使用上下文管理器获取写锁
        with lock.write_lock():
            # 在写锁内部可以执行操作
            pass

    def test_concurrent_read_context(self):
        """测试并发读（上下文管理器）"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        results = []

        def reader(id):
            with lock.read_lock():
                time.sleep(0.01)
                results.append(f"read_{id}")

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有读操作应该完成
        self.assertEqual(len(results), 5)


class TestParseJsonc(unittest.TestCase):
    """JSONC 解析测试"""

    def test_single_line_comment(self):
        """测试单行注释"""
        from config_manager import parse_jsonc

        content = """
{
    // 这是注释
    "key": "value"
}"""
        result = parse_jsonc(content)

        self.assertEqual(result["key"], "value")

    def test_multi_line_comment(self):
        """测试多行注释"""
        from config_manager import parse_jsonc

        content = """
{
    /* 这是
       多行注释 */
    "key": "value"
}"""
        result = parse_jsonc(content)

        self.assertEqual(result["key"], "value")

    def test_comment_in_string(self):
        """测试字符串中的注释符号"""
        from config_manager import parse_jsonc

        content = """
{
    "url": "http://example.com/path"
}"""
        result = parse_jsonc(content)

        self.assertEqual(result["url"], "http://example.com/path")


class TestConfigManagerBoolConversion(unittest.TestCase):
    """配置布尔值转换测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_bool_true_values(self):
        """测试各种真值"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "bool_true.json"
        with open(config_file, "w") as f:
            json.dump(
                {
                    "bool_true": True,
                    "string_true": "true",
                    "string_yes": "yes",
                    "number_one": 1,
                },
                f,
            )

        mgr = ConfigManager(str(config_file))

        self.assertTrue(mgr.get("bool_true"))
        self.assertEqual(mgr.get("string_true"), "true")

    def test_bool_false_values(self):
        """测试各种假值"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "bool_false.json"
        with open(config_file, "w") as f:
            json.dump(
                {"bool_false": False, "string_false": "false", "number_zero": 0}, f
            )

        mgr = ConfigManager(str(config_file))

        self.assertFalse(mgr.get("bool_false"))


# ============================================================================
# 边界条件测试
# ============================================================================


class TestBoundaryConditions(unittest.TestCase):
    """边界条件测试"""

    def test_empty_notification_title(self):
        """测试空标题通知"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        original_enabled = notification_manager.config.enabled
        notification_manager.config.enabled = True

        try:
            result = notification_manager.send_notification(
                title="",
                message="空标题测试",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            # 应该能处理空标题
            self.assertTrue(result.startswith("notification_"))
        finally:
            notification_manager.config.enabled = original_enabled

    def test_empty_notification_message(self):
        """测试空消息通知"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        original_enabled = notification_manager.config.enabled
        notification_manager.config.enabled = True

        try:
            result = notification_manager.send_notification(
                title="空消息测试",
                message="",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            # 应该能处理空消息
            self.assertTrue(result.startswith("notification_"))
        finally:
            notification_manager.config.enabled = original_enabled

    def test_very_long_notification(self):
        """测试超长通知"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        original_enabled = notification_manager.config.enabled
        notification_manager.config.enabled = True

        try:
            long_title = "标" * 1000
            long_message = "消息" * 5000

            result = notification_manager.send_notification(
                title=long_title,
                message=long_message,
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            # 应该能处理超长内容
            self.assertTrue(result.startswith("notification_"))
        finally:
            notification_manager.config.enabled = original_enabled


def run_tests():
    """运行所有覆盖率提升测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # notification_manager 测试
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerSend))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationTrigger))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationType))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationEventAdvanced))

    # config_manager 测试
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerDelayedSave))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerNestedConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestReadWriteLock))
    suite.addTests(loader.loadTestsFromTestCase(TestParseJsonc))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerBoolConversion))

    # 边界条件测试
    suite.addTests(loader.loadTestsFromTestCase(TestBoundaryConditions))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
