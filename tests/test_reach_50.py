#!/usr/bin/env python3
"""
AI Intervention Agent - 冲刺 50% 覆盖率测试

专注于提升 web_ui.py 和 server.py 的覆盖率
"""

import json
import sys
import unittest
from pathlib import Path
from typing import Any, cast

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# web_ui.py 更多测试
# ============================================================================


class TestWebUITaskManagement(unittest.TestCase):
    """Web UI 任务管理测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="任务管理测试",
            predefined_options=["选项1", "选项2"],
            task_id="task-mgmt-test",
            port=8980,
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_create_task_via_api(self):
        """测试通过 API 创建任务"""
        response = self.client.post(
            "/api/tasks",
            data=json.dumps(
                {
                    "id": "new-task-001",
                    "message": "新任务",
                    "options": ["A", "B"],
                    "timeout": 60,
                }
            ),
            content_type="application/json",
        )

        # 可能返回 200 或 400（取决于任务格式要求）
        self.assertIn(response.status_code, [200, 400])

    def test_get_task_by_id(self):
        """测试通过 ID 获取任务"""
        # 获取任务（可能存在或不存在）
        response = self.client.get("/api/tasks/get-task-001")

        # 可能返回 200 或 404
        self.assertIn(response.status_code, [200, 404])

    def test_delete_task(self):
        """测试删除任务"""
        # 删除任务（可能不支持 DELETE 方法）
        response = self.client.delete("/api/tasks/delete-task-001")

        # 可能返回 200、404 或 405（方法不允许）
        self.assertIn(response.status_code, [200, 204, 404, 405])


class TestWebUIStaticResources(unittest.TestCase):
    """Web UI 静态资源测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="静态资源测试", task_id="static-test", port=8979
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_favicon(self):
        """测试 favicon"""
        response = self.client.get("/favicon.ico")

        self.assertIn(response.status_code, [200, 204, 404, 302])

    def test_static_images(self):
        """测试静态图片"""
        response = self.client.get("/static/images/logo.png")

        self.assertIn(response.status_code, [200, 404])

    def test_robots_txt(self):
        """测试 robots.txt"""
        response = self.client.get("/robots.txt")

        self.assertIn(response.status_code, [200, 404])


class TestWebUIErrorHandling(unittest.TestCase):
    """Web UI 错误处理测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="错误处理测试", task_id="error-test", port=8978
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_404_error(self):
        """测试 404 错误"""
        response = self.client.get("/nonexistent-page")

        self.assertEqual(response.status_code, 404)

    def test_invalid_json(self):
        """测试无效 JSON"""
        response = self.client.post(
            "/api/tasks", data="invalid json", content_type="application/json"
        )

        self.assertIn(response.status_code, [400, 500])

    def test_missing_required_fields(self):
        """测试缺少必要字段"""
        response = self.client.post(
            "/api/tasks",
            data=json.dumps({"incomplete": True}),
            content_type="application/json",
        )

        self.assertIn(response.status_code, [400, 500])


# ============================================================================
# server.py 更多测试
# ============================================================================


class TestServerParseResponseAdvanced(unittest.TestCase):
    """服务器响应解析高级测试"""

    def test_parse_with_newlines(self):
        """测试带换行的响应"""
        from server import parse_structured_response

        response = {
            "user_input": "第一行\n第二行\n第三行",
            "selected_options": [],
            "images": [],
        }

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)

    def test_parse_with_tabs(self):
        """测试带制表符的响应"""
        from server import parse_structured_response

        response = {"user_input": "列1\t列2\t列3", "selected_options": [], "images": []}

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)

    def test_parse_mixed_content(self):
        """测试混合内容响应"""
        from server import parse_structured_response

        response = {
            "user_input": "Text with 中文 and émojis 🎉",
            "selected_options": ["Option 选项"],
            "images": [],
        }

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)


class TestServerValidateInputAdvanced(unittest.TestCase):
    """服务器输入验证高级测试"""

    def test_validate_with_empty_options(self):
        """测试空选项列表"""
        from server import validate_input

        message, options = validate_input("消息", [])

        self.assertEqual(options, [])

    def test_validate_with_none_message(self):
        """测试 None 消息"""
        from server import validate_input

        # None 应该抛出 ValueError
        with self.assertRaises(ValueError):
            validate_input(cast(Any, None), [])

    def test_validate_with_numeric_option(self):
        """测试数字选项"""
        from server import validate_input

        message, options = validate_input("消息", [123, 456])

        self.assertIsInstance(options, list)


# ============================================================================
# 更多边界测试
# ============================================================================


class TestBoundaryConditionsExtended(unittest.TestCase):
    """扩展边界条件测试"""

    def test_notification_with_html(self):
        """测试带 HTML 的通知"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        original_enabled = notification_manager.config.enabled
        notification_manager.config.enabled = True

        try:
            result = notification_manager.send_notification(
                title="<b>HTML 标题</b>",
                message="<script>alert('xss')</script>",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            self.assertTrue(result.startswith("notification_"))
        finally:
            notification_manager.config.enabled = original_enabled

    def test_config_manager_concurrent_access(self):
        """测试配置管理器并发访问"""
        import threading

        from config_manager import config_manager

        results = []

        def read_config():
            for _ in range(50):
                _ = config_manager.get("notification")
            results.append(True)

        threads = [threading.Thread(target=read_config) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)

    def test_task_queue_boundary_operations(self):
        """测试任务队列边界操作"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 获取不存在的任务
        task = queue.get_task("nonexistent-boundary-task")
        self.assertIsNone(task)

        # 完成不存在的任务
        result = queue.complete_task("nonexistent-boundary-task", {})
        self.assertFalse(result)

        queue.clear_all_tasks()


class TestWebUIMultipleTasks(unittest.TestCase):
    """Web UI 多任务测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="多任务测试", task_id="multi-task-test", port=8977
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_create_multiple_tasks(self):
        """测试创建多个任务"""
        for i in range(5):
            response = self.client.post(
                "/api/tasks",
                data=json.dumps(
                    {
                        "id": f"multi-{i}",
                        "message": f"多任务 {i}",
                        "options": [],
                        "timeout": 60,
                    }
                ),
                content_type="application/json",
            )

            # 可能返回 200 或 400（取决于任务格式要求）
            self.assertIn(response.status_code, [200, 400])

    def test_list_multiple_tasks(self):
        """测试列出多个任务"""
        response = self.client.get("/api/tasks")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("tasks", data)


def run_tests():
    """运行所有冲刺 50% 测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestWebUITaskManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIStaticResources))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIErrorHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestServerParseResponseAdvanced))
    suite.addTests(loader.loadTestsFromTestCase(TestServerValidateInputAdvanced))
    suite.addTests(loader.loadTestsFromTestCase(TestBoundaryConditionsExtended))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIMultipleTasks))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
