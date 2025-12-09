#!/usr/bin/env python3
"""
AI Intervention Agent - 突破 50% 覆盖率测试

最后的冲刺测试
"""

import json
import sys
import unittest
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestWebUIFinalPush(unittest.TestCase):
    """Web UI 最终冲刺测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="最终冲刺",
            predefined_options=["是", "否"],
            task_id="final-push",
            port=8970,
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_index_content_type(self):
        """测试首页内容类型"""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.content_type)

    def test_api_tasks_json(self):
        """测试任务 API 返回 JSON"""
        response = self.client.get("/api/tasks")

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.content_type)

    def test_notification_config_update_sound(self):
        """测试更新声音配置"""
        response = self.client.post(
            "/api/update-notification-config",
            data=json.dumps(
                {"sound_enabled": True, "sound_volume": 75, "sound_mute": False}
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

    def test_notification_config_update_web(self):
        """测试更新 Web 配置"""
        response = self.client.post(
            "/api/update-notification-config",
            data=json.dumps({"web_enabled": True, "web_timeout": 5000}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)


class TestServerFinalPush(unittest.TestCase):
    """Server 最终冲刺测试"""

    def test_parse_response_only_options(self):
        """测试仅选项的响应"""
        from server import parse_structured_response

        response = {
            "user_input": "",
            "selected_options": ["选项1", "选项2", "选项3"],
            "images": [],
        }

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_validate_input_unicode(self):
        """测试 Unicode 输入验证"""
        from server import validate_input

        message = "中文 日本語 한국어 العربية"
        options = ["选项 🎉", "オプション 💡"]

        result_msg, result_opts = validate_input(message, options)

        self.assertIn("中文", result_msg)


class TestConfigManagerFinalPush(unittest.TestCase):
    """Config Manager 最终冲刺测试"""

    def test_get_all_sections(self):
        """测试获取所有配置段"""
        from config_manager import config_manager

        all_config = config_manager.get_all()

        self.assertIsInstance(all_config, dict)
        self.assertGreater(len(all_config), 0)

    def test_get_multiple_sections(self):
        """测试获取多个配置段"""
        from config_manager import config_manager

        # 获取多个配置段
        notification = config_manager.get_section("notification")
        web_ui = config_manager.get_section("web_ui")

        self.assertIsNotNone(notification)
        self.assertIsNotNone(web_ui)


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


class TestTaskQueueFinalPush(unittest.TestCase):
    """Task Queue 最终冲刺测试"""

    def test_task_queue_stats(self):
        """测试任务队列统计"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 获取统计
        stats = queue.get_task_count()

        self.assertIn("pending", stats)
        self.assertIn("active", stats)
        self.assertIn("completed", stats)

        queue.clear_all_tasks()

    def test_task_queue_clear(self):
        """测试清空任务队列"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 添加任务
        queue.add_task("clear-test-1", "测试1")
        queue.add_task("clear-test-2", "测试2")

        # 清空
        queue.clear_all_tasks()

        # 验证已清空
        stats = queue.get_task_count()
        self.assertEqual(stats["pending"] + stats["active"] + stats["completed"], 0)


def run_tests():
    """运行所有最终冲刺测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestWebUIFinalPush))
    suite.addTests(loader.loadTestsFromTestCase(TestServerFinalPush))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerFinalPush))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationFinalPush))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueFinalPush))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
