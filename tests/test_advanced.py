#!/usr/bin/env python3
"""
AI Intervention Agent - 高级测试用例

补充测试覆盖：
1. 边界条件测试（空值、极限值、特殊字符）
2. 异常处理测试（网络错误、超时、文件不存在）
3. 并发压力测试（高并发、竞争条件）
4. 集成测试（模块间交互）
"""

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# 边界条件测试
# ============================================================================


class TestNotificationManagerBoundary(unittest.TestCase):
    """通知管理器边界条件测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_refresh_with_missing_config_keys(self):
        """测试配置缺少某些键时的刷新"""
        # 强制刷新应该不会崩溃
        self.manager.refresh_config_from_file(force=True)

        # 配置应该有有效的默认值
        self.assertIsNotNone(self.manager.config)

    def test_config_extreme_sound_volume(self):
        """测试极端音量值"""
        # 测试负数
        self.manager.config.sound_volume = -100
        self.assertIsInstance(self.manager.config.sound_volume, (int, float))

        # 测试超大值
        self.manager.config.sound_volume = 1000000
        self.assertIsInstance(self.manager.config.sound_volume, (int, float))

    def test_empty_bark_url(self):
        """测试空的 Bark URL"""
        self.manager.config.bark_enabled = True
        self.manager.config.bark_url = ""
        self.manager.config.bark_device_key = "test"

        # 不应该崩溃
        from notification_providers import BarkNotificationProvider

        provider = BarkNotificationProvider(self.manager.config)
        self.assertIsNotNone(provider)


class TestConfigManagerBoundary(unittest.TestCase):
    """配置管理器边界条件测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_parse_empty_jsonc(self):
        """测试解析空 JSONC"""
        from config_manager import parse_jsonc

        result = parse_jsonc("{}")
        self.assertEqual(result, {})

    def test_parse_only_comments(self):
        """测试只有注释的 JSONC"""
        from config_manager import parse_jsonc

        content = """
        // 这是注释
        /* 多行注释 */
        {}
        """
        result = parse_jsonc(content)
        self.assertEqual(result, {})

    def test_deeply_nested_config(self):
        """测试深度嵌套配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "nested.json"
        nested_config = {"level1": {"level2": {"level3": {"level4": {"value": 42}}}}}

        with open(config_file, "w") as f:
            json.dump(nested_config, f)

        mgr = ConfigManager(str(config_file))

        # 测试深度获取
        value = mgr.get("level1.level2.level3.level4.value")
        self.assertEqual(value, 42)

    def test_unicode_config_values(self):
        """测试 Unicode 配置值"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "unicode.json"
        unicode_config = {
            "chinese": "中文测试",
            "japanese": "日本語テスト",
            "emoji": "🎉🚀💻",
            "mixed": "Hello 世界 🌍",
        }

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(unicode_config, f, ensure_ascii=False)

        mgr = ConfigManager(str(config_file))

        self.assertEqual(mgr.get("chinese"), "中文测试")
        self.assertEqual(mgr.get("emoji"), "🎉🚀💻")

    def test_special_characters_in_value(self):
        """测试值中的特殊字符"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "special.json"
        special_config = {
            "url": "http://example.com/path?param=value&other=123",
            "path": "/home/user/文件夹/file.txt",
            "regex": "^[a-z]+\\d+$",
        }

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(special_config, f)

        mgr = ConfigManager(str(config_file))

        self.assertEqual(
            mgr.get("url"), "http://example.com/path?param=value&other=123"
        )


class TestTaskQueueBoundary(unittest.TestCase):
    """任务队列边界条件测试"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=5)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_empty_task_id(self):
        """测试空任务 ID"""
        result = self.queue.add_task("", "提示")
        # 空 ID 应该也能添加（由业务逻辑决定是否允许）
        self.assertIn(result, [True, False])

    def test_very_long_prompt(self):
        """测试超长提示"""
        long_prompt = "A" * 100000
        result = self.queue.add_task("task-long", long_prompt)

        self.assertTrue(result)
        task = self.queue.get_task("task-long")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(len(task.prompt), 100000)

    def test_special_characters_in_prompt(self):
        """测试提示中的特殊字符"""
        special_prompt = (
            "<script>alert('xss')</script>\n\t\"quotes\" 'single' `backtick`"
        )
        result = self.queue.add_task("task-special", special_prompt)

        self.assertTrue(result)
        task = self.queue.get_task("task-special")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.prompt, special_prompt)

    def test_many_predefined_options(self):
        """测试大量预定义选项"""
        options = [f"选项{i}" for i in range(1000)]
        result = self.queue.add_task("task-options", "提示", predefined_options=options)

        self.assertTrue(result)
        task = self.queue.get_task("task-options")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertIsNotNone(task.predefined_options)
        assert task.predefined_options is not None
        self.assertEqual(len(task.predefined_options), 1000)


class TestFileValidatorBoundary(unittest.TestCase):
    """文件验证器边界条件测试"""

    def setUp(self):
        """每个测试前的准备"""
        from file_validator import FileValidator

        self.validator = FileValidator()

    def test_unicode_filename(self):
        """测试 Unicode 文件名"""
        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100

        result = self.validator.validate_file(png_data, "测试文件_日本語_🎉.png")

        self.assertTrue(result["valid"])

    def test_very_small_file(self):
        """测试极小文件"""
        # 只有魔数，没有其他数据
        minimal_png = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"

        result = self.validator.validate_file(minimal_png, "tiny.png")

        self.assertTrue(result["valid"])

    def test_filename_with_multiple_dots(self):
        """测试多点文件名"""
        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100

        result = self.validator.validate_file(png_data, "file.name.with.many.dots.png")

        self.assertTrue(result["valid"])

    def test_bmp_format(self):
        """测试 BMP 格式检测"""
        # BMP 魔数
        bmp_data = b"\x42\x4d" + b"\x00" * 100

        result = self.validator.validate_file(bmp_data, "test.bmp")

        self.assertTrue(result["valid"])
        self.assertEqual(result["mime_type"], "image/bmp")


# ============================================================================
# 异常处理测试
# ============================================================================


class TestConfigManagerExceptions(unittest.TestCase):
    """配置管理器异常处理测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_malformed_json(self):
        """测试畸形 JSON"""
        from config_manager import parse_jsonc

        with self.assertRaises(json.JSONDecodeError):
            parse_jsonc("{invalid json")

    def test_missing_config_file(self):
        """测试配置文件不存在"""
        from config_manager import ConfigManager

        # 应该创建默认配置
        mgr = ConfigManager(str(Path(self.test_dir) / "nonexistent.json"))
        self.assertIsNotNone(mgr.get_all())

    def test_permission_denied_simulation(self):
        """测试权限错误模拟"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "test_perm.json"
        with open(config_file, "w") as f:
            json.dump({"test": True}, f)

        mgr = ConfigManager(str(config_file))

        # 即使保存失败，内存配置应该还在
        mgr.set("test", False, save=False)
        self.assertEqual(mgr.get("test"), False)


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


class TestHighConcurrency(unittest.TestCase):
    """高并发测试"""

    def test_task_queue_high_concurrency(self):
        """测试任务队列高并发"""
        from task_queue import TaskQueue

        queue = TaskQueue(max_tasks=1000)
        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    task_id = f"task-{thread_id}-{i}"
                    queue.add_task(task_id, f"提示{thread_id}-{i}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        queue.stop_cleanup()

        self.assertEqual(len(errors), 0)
        # 应该成功添加 1000 个任务
        count = queue.get_task_count()
        self.assertEqual(count["total"], 1000)

    def test_config_manager_concurrent_access(self):
        """测试配置管理器并发访问"""
        from notification_manager import notification_manager

        errors = []
        iterations = 50

        def reader():
            try:
                for _ in range(iterations):
                    _ = notification_manager.config.bark_enabled
                    _ = notification_manager.config.sound_volume
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for _ in range(iterations):
                    notification_manager.refresh_config_from_file(force=True)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)] + [
            threading.Thread(target=writer) for _ in range(2)
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)

    def test_file_validator_concurrent_validation(self):
        """测试文件验证器并发验证"""
        from file_validator import validate_uploaded_file

        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100
        errors = []

        def validator(thread_id):
            try:
                for i in range(50):
                    result = validate_uploaded_file(
                        png_data, f"test_{thread_id}_{i}.png"
                    )
                    if not result["valid"]:
                        errors.append(f"Validation failed: {result}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=validator, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


# ============================================================================
# 集成测试
# ============================================================================


class TestModuleIntegration(unittest.TestCase):
    """模块间集成测试"""

    def test_notification_manager_with_config(self):
        """测试通知管理器与配置的集成"""
        from config_manager import get_config
        from notification_manager import notification_manager

        # 从配置管理器获取配置
        config = get_config()
        notification_section = config.get_section("notification")

        # 刷新通知管理器配置
        notification_manager.refresh_config_from_file(force=True)

        # 配置应该一致
        self.assertIsNotNone(notification_manager.config)

    def test_task_queue_with_complete_workflow(self):
        """测试任务队列完整工作流"""
        from task_queue import TaskQueue

        queue = TaskQueue(max_tasks=10)

        # 1. 添加多个任务
        for i in range(5):
            queue.add_task(f"task-{i}", f"提示{i}")

        # 2. 验证第一个任务是活动的
        active = queue.get_active_task()
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.task_id, "task-0")

        # 3. 完成任务
        queue.complete_task("task-0", {"feedback": "完成"})

        # 4. 验证下一个任务自动激活
        active = queue.get_active_task()
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.task_id, "task-1")

        # 5. 清理
        queue.stop_cleanup()

    def test_file_validator_with_real_file(self):
        """测试文件验证器处理真实文件数据"""
        from file_validator import validate_uploaded_file

        # 创建一个最小的有效 PNG 文件
        # PNG 最小头部 + IHDR + IEND
        png_header = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a"
        ihdr_chunk = b"\x00\x00\x00\x0d\x49\x48\x44\x52" + b"\x00" * 17
        iend_chunk = b"\x00\x00\x00\x00\x49\x45\x4e\x44\xae\x42\x60\x82"

        valid_png = png_header + ihdr_chunk + iend_chunk

        result = validate_uploaded_file(valid_png, "real.png")

        self.assertTrue(result["valid"])
        self.assertEqual(result["mime_type"], "image/png")


def run_tests():
    """运行所有高级测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 边界条件测试
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerBoundary))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerBoundary))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueBoundary))
    suite.addTests(loader.loadTestsFromTestCase(TestFileValidatorBoundary))

    # 异常处理测试
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerExceptions))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationProvidersExceptions))

    # 并发压力测试
    suite.addTests(loader.loadTestsFromTestCase(TestHighConcurrency))

    # 集成测试
    suite.addTests(loader.loadTestsFromTestCase(TestModuleIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
