#!/usr/bin/env python3
"""
AI Intervention Agent - 集成测试

针对 server.py 和 web_ui.py 的基础集成测试
使用 mock 和 patch 来模拟服务器行为
"""

import base64
import io
import json
import sys
import unittest
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# web_ui.py 集成测试
# ============================================================================


class TestWebFeedbackUICreation(unittest.TestCase):
    """Web 反馈 UI 创建测试"""

    def test_create_web_ui(self):
        """测试创建 Web UI 实例"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(
            prompt="测试提示",
            predefined_options=["选项1", "选项2"],
            task_id="test-001",
            port=8999,
        )

        self.assertIsNotNone(ui)
        self.assertIsNotNone(ui.app)

    def test_web_ui_with_default_options(self):
        """测试默认选项的 Web UI"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="默认选项测试", port=8998)

        self.assertIsNotNone(ui)


class TestWebFeedbackUIFlaskApp(unittest.TestCase):
    """Flask 应用测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="Flask 测试",
            predefined_options=["确认", "取消"],
            task_id="flask-test",
            port=8997,
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_index_page(self):
        """测试首页"""
        response = self.client.get("/")

        # 应该返回 200
        self.assertEqual(response.status_code, 200)

    def test_index_contains_zero_host_redirect(self):
        """回归测试：0.0.0.0 场景应尽早重定向（避免 pending 请求/浏览器兼容问题）"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8", errors="ignore")
        self.assertIn("redirectZeroHostToLoopback", html)
        self.assertIn("0.0.0.0", html)

    def test_api_tasks(self):
        """测试任务 API"""
        response = self.client.get("/api/tasks")

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("tasks", data)

    def test_api_status(self):
        """测试状态 API"""
        response = self.client.get("/api/status")

        # 可能返回 200 或 404
        self.assertIn(response.status_code, [200, 404])

    def test_static_css(self):
        """测试 CSS 静态文件"""
        response = self.client.get("/static/css/style.css")

        # 可能存在或不存在
        self.assertIn(response.status_code, [200, 404])

    def test_static_js(self):
        """测试 JS 静态文件"""
        response = self.client.get("/static/js/multi_task.js")

        # 可能存在或不存在
        self.assertIn(response.status_code, [200, 404])

    def test_multi_task_polling_governance_present(self):
        """回归测试：任务轮询应具备治理能力（不可见暂停/退避/AbortController 防重叠）"""
        response = self.client.get("/static/js/multi_task.js")
        if response.status_code != 200:
            self.skipTest("multi_task.js 不存在，跳过轮询治理回归测试")

        js = response.data.decode("utf-8", errors="ignore")
        response.close()  # 避免 send_from_directory 返回的文件句柄在测试结束后仍未释放
        self.assertIn("AbortController", js)
        self.assertIn("visibilitychange", js)
        self.assertIn("no-store", js)

    def test_multi_task_mathjax_lazy_load_present(self):
        """回归测试：任务描述渲染应支持 MathJax 懒加载（避免首次出现公式不渲染）"""
        response = self.client.get("/static/js/multi_task.js")
        if response.status_code != 200:
            self.skipTest("multi_task.js 不存在，跳过 MathJax 懒加载回归测试")

        js = response.data.decode("utf-8", errors="ignore")
        response.close()  # 避免 send_from_directory 返回的文件句柄在测试结束后仍未释放
        # 关键点：multi_task.js 在更新描述后应调用 loadMathJaxIfNeeded 触发按需加载与渲染
        self.assertIn("loadMathJaxIfNeeded", js)

    def test_static_assets_not_rate_limited(self):
        """回归测试：静态资源不应被频率限制误伤（避免 429 导致白屏/MathJax 失效）"""
        # 连续快速请求静态资源，若静态路由未 exempt，可能触发全局 10/s 限流返回 429
        statuses = [
            self.client.get("/static/js/mathjax-loader.js").status_code
            for _ in range(20)
        ]
        self.assertNotIn(429, statuses)

        # 文件不存在时也应返回 404（而不是被限流拦截成 429）
        missing_statuses = [
            self.client.get("/static/js/__definitely_missing__.js").status_code
            for _ in range(5)
        ]
        self.assertNotIn(429, missing_statuses)


class TestWebFeedbackUINotificationConfig(unittest.TestCase):
    """通知配置 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="通知配置测试", task_id="notification-test", port=8996
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_update_notification_config(self):
        """测试更新通知配置"""
        config_data = {"enabled": True, "bark_enabled": False, "sound_enabled": True}

        response = self.client.post(
            "/api/update-notification-config",
            data=json.dumps(config_data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

    def test_update_notification_config_bark(self):
        """测试更新 Bark 配置"""
        config_data = {
            "bark_enabled": True,
            "bark_url": "https://api.day.app/push",
            "bark_device_key": "test_key",
        }

        response = self.client.post(
            "/api/update-notification-config",
            data=json.dumps(config_data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)


# ============================================================================
# web_ui.py 图片上传集成测试（/api/submit）
# ============================================================================


class TestWebFeedbackUIImageUpload(unittest.TestCase):
    """图片上传 API 测试（multipart/form-data）"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="图片上传测试", task_id="image-upload-test", port=8995
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

        # 最小可用样例数据（不依赖 Pillow）
        cls._png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        cls._jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 128
        cls._webp_bytes = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32

    def setUp(self):
        # 避免跨测试污染
        self.web_ui.feedback_result = {
            "user_input": "",
            "selected_options": [],
            "images": [],
        }

    def _submit_image(self, content: bytes, filename: str, mime_type: str):
        data = {
            "feedback_text": "图片上传测试",
            "selected_options": "[]",
            "image_0": (io.BytesIO(content), filename, mime_type),
        }
        return self.client.post(
            "/api/submit", data=data, content_type="multipart/form-data"
        )

    def _assert_last_image(self, expected_mime: str):
        result = self.web_ui.feedback_result
        self.assertIsInstance(result, dict)
        assert isinstance(result, dict)
        images = result.get("images", [])
        self.assertIsInstance(images, list)
        self.assertEqual(len(images), 1)

        image0 = images[0]
        self.assertIsInstance(image0, dict)
        self.assertIn("data", image0)
        self.assertTrue(isinstance(image0["data"], str) and image0["data"].strip())
        self.assertFalse(image0["data"].startswith("data:"))

        # 后端统一保存为 content_type 字段
        self.assertEqual(image0.get("content_type"), expected_mime)

    def test_submit_png_image(self):
        resp = self._submit_image(self._png_bytes, "test.png", "image/png")
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.data)
        self.assertEqual(payload.get("status"), "success")
        self._assert_last_image("image/png")

    def test_submit_jpeg_image(self):
        resp = self._submit_image(self._jpeg_bytes, "test.jpg", "image/jpeg")
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.data)
        self.assertEqual(payload.get("status"), "success")
        self._assert_last_image("image/jpeg")

    def test_submit_webp_image(self):
        resp = self._submit_image(self._webp_bytes, "test.webp", "image/webp")
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.data)
        self.assertEqual(payload.get("status"), "success")
        self._assert_last_image("image/webp")


# ============================================================================
# server.py 集成测试
# ============================================================================


class TestServerImport(unittest.TestCase):
    """服务器模块导入测试"""

    def test_import_parse_structured_response(self):
        """测试导入 parse_structured_response"""
        try:
            from server import parse_structured_response

            self.assertTrue(callable(parse_structured_response))
        except ImportError:
            self.skipTest("无法导入 server 模块")

    def test_import_validate_input(self):
        """测试导入 validate_input"""
        try:
            from server import validate_input

            self.assertTrue(callable(validate_input))
        except ImportError:
            self.skipTest("无法导入 server 模块")


class TestParseStructuredResponse(unittest.TestCase):
    """解析结构化响应测试"""

    def test_parse_dict_response(self):
        """测试解析字典响应"""
        try:
            from server import parse_structured_response

            # 测试标准格式
            response = {
                "user_input": "用户输入",
                "selected_options": ["选项1"],
                "images": [],
            }

            result = parse_structured_response(response)

            self.assertIsInstance(result, list)
        except ImportError:
            self.skipTest("无法导入 server 模块")

    def test_parse_response_with_images(self):
        """测试带图片的响应"""
        try:
            from server import parse_structured_response

            response = {
                "user_input": "带图片",
                "selected_options": [],
                "images": [{"data": "base64data", "mimeType": "image/png"}],
            }

            result = parse_structured_response(response)

            self.assertIsInstance(result, list)
        except ImportError:
            self.skipTest("无法导入 server 模块")


class TestValidateInput(unittest.TestCase):
    """输入验证测试"""

    def test_validate_normal_input(self):
        """测试正常输入验证"""
        try:
            from server import validate_input

            # validate_input 返回元组 (message, options)
            result = validate_input("正常输入", [])

            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 2)
        except (ImportError, TypeError):
            self.skipTest("无法测试 validate_input")

    def test_validate_empty_input(self):
        """测试空输入验证"""
        try:
            from server import validate_input

            result = validate_input("", [])

            self.assertIsInstance(result, tuple)
        except (ImportError, TypeError):
            self.skipTest("无法测试 validate_input")


# ============================================================================
# 配置和环境测试
# ============================================================================


class TestConfigIntegration(unittest.TestCase):
    """配置集成测试"""

    def test_config_manager_singleton(self):
        """测试配置管理器单例"""
        from config_manager import config_manager as cm1
        from config_manager import config_manager as cm2

        self.assertIs(cm1, cm2)

    def test_notification_manager_singleton(self):
        """测试通知管理器单例"""
        from notification_manager import notification_manager as nm1
        from notification_manager import notification_manager as nm2

        self.assertIs(nm1, nm2)

    def test_config_notification_integration(self):
        """测试配置与通知集成"""
        from config_manager import config_manager
        from notification_manager import notification_manager

        # 获取配置
        notification_config = config_manager.get_section("notification")

        # 刷新通知管理器
        notification_manager.refresh_config_from_file()

        # 验证配置已加载
        self.assertIsNotNone(notification_manager.config)


class TestTaskQueueIntegration(unittest.TestCase):
    """任务队列集成测试"""

    def test_task_queue_from_web_ui(self):
        """测试从 Web UI 使用任务队列"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="任务队列测试", task_id="queue-test-001", port=8995)

        # 验证 Web UI 已创建
        self.assertIsNotNone(ui)
        # 验证 Flask app 已创建
        self.assertIsNotNone(ui.app)


class TestMultiTaskAPI(unittest.TestCase):
    """多任务 API 测试 - 针对本次修复新增

    测试场景：
    1. 多任务列表 API 响应格式
    2. 任务状态过滤
    3. 任务完成后的列表更新
    """

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(
            prompt="多任务 API 测试", task_id="api-test-001", port=8993
        )
        cls.client = cls.ui.app.test_client()

    def test_tasks_api_response_format(self):
        """测试任务列表 API 响应格式"""
        response = self.client.get("/api/tasks")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        # 验证响应结构
        self.assertIn("success", data)
        self.assertIn("tasks", data)
        self.assertIn("stats", data)

        # 验证 stats 结构
        stats = data["stats"]
        self.assertIn("total", stats)
        self.assertIn("active", stats)
        self.assertIn("pending", stats)
        self.assertIn("completed", stats)
        self.assertIn("max", stats)

    def test_tasks_api_includes_active_task(self):
        """测试任务列表包含活动任务"""
        # 先添加一个任务
        from server import get_task_queue

        task_queue = get_task_queue()
        task_queue.add_task(
            task_id="test-task-001",
            prompt="测试任务",
            predefined_options=[],
            auto_resubmit_timeout=60,
        )

        response = self.client.get("/api/tasks")
        data = response.get_json()

        # 至少有一个任务
        self.assertGreaterEqual(len(data["tasks"]), 1)

        # 检查任务结构
        task = data["tasks"][0]
        self.assertIn("task_id", task)
        self.assertIn("prompt", task)
        self.assertIn("status", task)
        self.assertIn("remaining_time", task)

        # 清理
        task_queue.remove_task("test-task-001")

    def test_task_status_values(self):
        """测试任务状态值"""
        response = self.client.get("/api/tasks")
        data = response.get_json()

        valid_statuses = {"pending", "active", "completed"}

        for task in data["tasks"]:
            self.assertIn(task["status"], valid_statuses)

    def test_tasks_stats_consistency(self):
        """测试任务统计一致性"""
        response = self.client.get("/api/tasks")
        data = response.get_json()

        stats = data["stats"]
        tasks = data["tasks"]

        # 统计总数应该等于任务列表长度
        self.assertEqual(stats["total"], len(tasks))

        # 分类统计应该加起来等于总数
        calculated_total = stats["active"] + stats["pending"] + stats["completed"]
        self.assertEqual(calculated_total, stats["total"])

    def test_incomplete_tasks_have_remaining_time(self):
        """测试未完成任务有剩余时间"""
        response = self.client.get("/api/tasks")
        data = response.get_json()

        for task in data["tasks"]:
            if task["status"] != "completed":
                self.assertIn("remaining_time", task)
                self.assertIsInstance(task["remaining_time"], (int, float))


def run_tests():
    """运行所有集成测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Web UI 测试
    suite.addTests(loader.loadTestsFromTestCase(TestWebFeedbackUICreation))
    suite.addTests(loader.loadTestsFromTestCase(TestWebFeedbackUIFlaskApp))
    suite.addTests(loader.loadTestsFromTestCase(TestWebFeedbackUINotificationConfig))

    # Server 测试
    suite.addTests(loader.loadTestsFromTestCase(TestServerImport))
    suite.addTests(loader.loadTestsFromTestCase(TestParseStructuredResponse))
    suite.addTests(loader.loadTestsFromTestCase(TestValidateInput))

    # 配置集成测试
    suite.addTests(loader.loadTestsFromTestCase(TestConfigIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueIntegration))

    # 多任务 API 测试
    suite.addTests(loader.loadTestsFromTestCase(TestMultiTaskAPI))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
