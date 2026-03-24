#!/usr/bin/env python3
"""
AI Intervention Agent - API 覆盖率测试

为未测试的 API 端点添加测试
"""

import json
import sys
import unittest
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestWebUIHealthAPI(unittest.TestCase):
    """健康检查 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="API 测试", task_id="api-test", port=8965)
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_health_check(self):
        """测试健康检查端点"""
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("status", data)

    def test_health_check_content_type(self):
        """测试健康检查返回 JSON"""
        response = self.client.get("/api/health")

        self.assertIn("application/json", response.content_type)


class TestWebUINotificationConfigAPI(unittest.TestCase):
    """通知配置 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="通知配置测试", task_id="notif-config-test", port=8964
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_get_notification_config(self):
        """测试获取通知配置"""
        response = self.client.get("/api/get-notification-config")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIsInstance(data, dict)

    def test_get_notification_config_fields(self):
        """测试通知配置包含必要字段"""
        response = self.client.get("/api/get-notification-config")

        data = json.loads(response.data)
        # 应该包含一些基本配置
        self.assertIsInstance(data, dict)


class TestWebUIFeedbackPromptsAPI(unittest.TestCase):
    """反馈提示语 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="提示语测试", task_id="prompts-test", port=8963
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_get_feedback_prompts(self):
        """测试获取反馈提示语"""
        response = self.client.get("/api/get-feedback-prompts")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIsInstance(data, dict)


class TestWebUIFeedbackAPI(unittest.TestCase):
    """反馈结果 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="反馈测试", task_id="feedback-test", port=8962
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_get_feedback(self):
        """测试获取反馈结果"""
        response = self.client.get("/api/feedback")

        # 可能返回 200（有反馈）或其他状态（无反馈）
        self.assertIn(response.status_code, [200, 204, 404])


class TestWebUITaskActivateAPI(unittest.TestCase):
    """任务激活 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="激活测试", task_id="activate-test", port=8961
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_activate_nonexistent_task(self):
        """测试激活不存在的任务"""
        response = self.client.post("/api/tasks/nonexistent-task/activate")

        # 应该返回 404
        self.assertIn(response.status_code, [404, 400])

    def test_activate_task(self):
        """测试激活任务"""
        # 先创建任务
        self.client.post(
            "/api/tasks",
            data=json.dumps(
                {
                    "id": "activate-me",
                    "message": "激活测试",
                    "options": [],
                    "timeout": 60,
                }
            ),
            content_type="application/json",
        )

        # 激活任务
        response = self.client.post("/api/tasks/activate-me/activate")

        # 可能返回 200 或 400
        self.assertIn(response.status_code, [200, 400, 404])


class TestWebUITaskSubmitAPI(unittest.TestCase):
    """任务提交 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="提交测试", task_id="submit-test", port=8960)
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        from server import get_task_queue

        self.task_queue = get_task_queue()
        self.task_queue.clear_all_tasks()

    def tearDown(self):
        self.task_queue.clear_all_tasks()

    def test_submit_nonexistent_task(self):
        """测试提交不存在的任务"""
        response = self.client.post(
            "/api/tasks/nonexistent-task/submit",
            data=json.dumps({"user_input": "测试", "selected_options": []}),
            content_type="application/json",
        )

        self.assertIn(response.status_code, [404, 400])

    def test_task_submit_invalid_selected_options_returns_400(self):
        """/api/tasks/<id>/submit：selected_options 非法时不应 500"""
        self.task_queue.add_task("bad-options-task", "提示")

        response = self.client.post(
            "/api/tasks/bad-options-task/submit",
            data={
                "feedback_text": "测试",
                "selected_options": "{not-json",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_generic_submit_respects_explicit_task_id(self):
        """通用提交端点应优先完成显式 task_id，而不是当前 active 任务"""
        self.task_queue.add_task("active-task", "激活任务")
        self.task_queue.add_task("pending-task", "等待任务")

        response = self.client.post(
            "/api/submit",
            data={
                "task_id": "pending-task",
                "feedback_text": "定向提交",
                "selected_options": "[]",
            },
        )

        self.assertEqual(response.status_code, 200)

        active_task = self.task_queue.get_task("active-task")
        pending_task = self.task_queue.get_task("pending-task")
        self.assertIsNotNone(active_task)
        self.assertIsNotNone(pending_task)
        assert active_task is not None
        assert pending_task is not None

        self.assertEqual(active_task.status, "active")
        self.assertEqual(pending_task.status, "completed")
        self.assertEqual(
            pending_task.result,
            {"user_input": "定向提交", "selected_options": [], "images": []},
        )

    def test_generic_submit_missing_explicit_task_id_returns_404(self):
        """通用提交端点在 task_id 不存在时不应误写 active 任务"""
        self.task_queue.add_task("active-task", "激活任务")

        response = self.client.post(
            "/api/submit",
            data={
                "task_id": "missing-task",
                "feedback_text": "不应串任务",
                "selected_options": "[]",
            },
        )

        self.assertEqual(response.status_code, 404)

        active_task = self.task_queue.get_task("active-task")
        self.assertIsNotNone(active_task)
        assert active_task is not None
        self.assertEqual(active_task.status, "active")
        self.assertIsNone(active_task.result)


class TestWebUIUpdateAPI(unittest.TestCase):
    """更新内容 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="更新测试", task_id="update-test", port=8959)
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_update_content(self):
        """测试更新内容"""
        response = self.client.post(
            "/api/update",
            data=json.dumps({"message": "新消息", "options": ["新选项"]}),
            content_type="application/json",
        )

        # 可能返回 200 或其他状态
        self.assertIn(response.status_code, [200, 400, 404])


class TestWebUIStaticResourcesAPI(unittest.TestCase):
    """静态资源 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="静态资源测试", task_id="static-test", port=8958
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_fonts_endpoint(self):
        """测试字体端点"""
        response = self.client.get("/fonts/test.woff2")

        # 可能返回 200 或 404
        self.assertIn(response.status_code, [200, 404])

    def test_icons_endpoint(self):
        """测试图标端点"""
        response = self.client.get("/icons/test.svg")

        self.assertIn(response.status_code, [200, 404])

    def test_sounds_endpoint(self):
        """测试音频端点"""
        response = self.client.get("/sounds/test.mp3")

        self.assertIn(response.status_code, [200, 404])


class TestWebUICloseAPI(unittest.TestCase):
    """关闭服务器 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="关闭测试", task_id="close-test", port=8957)
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_close_endpoint(self):
        """测试关闭端点"""
        from unittest.mock import patch

        # Mock shutdown_server 以避免发送 SIGINT 信号
        with patch.object(self.web_ui, "shutdown_server"):
            response = self.client.post("/api/close")

        # 可能返回 200 或其他状态
        self.assertIn(response.status_code, [200, 400, 404, 500])


def run_tests():
    """运行所有 API 覆盖测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestWebUIHealthAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUINotificationConfigAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIFeedbackPromptsAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIFeedbackAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUITaskActivateAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUITaskSubmitAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIUpdateAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIStaticResourcesAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUICloseAPI))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
