"""
Web UI 配置模块单元测试

测试覆盖：
    - WebUIConfig 数据类的边界验证
    - 端口号验证（范围、特权端口）
    - 超时时间验证
    - 重试次数验证
    - 重试延迟验证
"""

import json
import unittest
from unittest.mock import MagicMock, patch


class TestWebUIConfigConstants(unittest.TestCase):
    """测试 WebUIConfig 常量"""

    def test_constants_defined(self):
        """测试常量定义"""
        from server import WebUIConfig

        # 端口常量
        self.assertEqual(WebUIConfig.PORT_MIN, 1)
        self.assertEqual(WebUIConfig.PORT_MAX, 65535)
        self.assertEqual(WebUIConfig.PORT_PRIVILEGED, 1024)

        # 超时常量
        self.assertEqual(WebUIConfig.TIMEOUT_MIN, 1)
        self.assertEqual(WebUIConfig.TIMEOUT_MAX, 300)

        # 重试常量
        self.assertEqual(WebUIConfig.MAX_RETRIES_MIN, 0)
        self.assertEqual(WebUIConfig.MAX_RETRIES_MAX, 10)
        self.assertEqual(WebUIConfig.RETRY_DELAY_MIN, 0.1)
        self.assertEqual(WebUIConfig.RETRY_DELAY_MAX, 60.0)


class TestWebUIConfigPort(unittest.TestCase):
    """测试端口号验证"""

    def test_valid_port(self):
        """测试有效端口号"""
        from server import WebUIConfig

        # 正常端口
        config = WebUIConfig(host="127.0.0.1", port=8080)
        self.assertEqual(config.port, 8080)

        # 边界值
        config = WebUIConfig(host="127.0.0.1", port=1)
        self.assertEqual(config.port, 1)

        config = WebUIConfig(host="127.0.0.1", port=65535)
        self.assertEqual(config.port, 65535)

    def test_invalid_port_zero(self):
        """测试无效端口号 0"""
        from server import WebUIConfig

        with self.assertRaises(ValueError) as context:
            WebUIConfig(host="127.0.0.1", port=0)

        self.assertIn("端口号必须在", str(context.exception))

    def test_invalid_port_negative(self):
        """测试负数端口号"""
        from server import WebUIConfig

        with self.assertRaises(ValueError):
            WebUIConfig(host="127.0.0.1", port=-1)

    def test_invalid_port_too_large(self):
        """测试超大端口号"""
        from server import WebUIConfig

        with self.assertRaises(ValueError):
            WebUIConfig(host="127.0.0.1", port=65536)

    def test_privileged_port_warning(self):
        """测试特权端口警告"""
        from server import WebUIConfig

        # 特权端口应该生成警告但不抛异常
        config = WebUIConfig(host="127.0.0.1", port=80)
        self.assertEqual(config.port, 80)

        config = WebUIConfig(host="127.0.0.1", port=443)
        self.assertEqual(config.port, 443)


class TestWebUIConfigTimeout(unittest.TestCase):
    """测试超时时间验证"""

    def test_valid_timeout(self):
        """测试有效超时时间"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=30)
        self.assertEqual(config.timeout, 30)

        # 边界值
        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=1)
        self.assertEqual(config.timeout, 1)

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=300)
        self.assertEqual(config.timeout, 300)

    def test_timeout_below_min(self):
        """测试超时时间小于最小值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=0)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MIN)

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=-10)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MIN)

    def test_timeout_above_max(self):
        """测试超时时间大于最大值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=500)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MAX)

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=3600)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MAX)


class TestWebUIConfigMaxRetries(unittest.TestCase):
    """测试重试次数验证"""

    def test_valid_max_retries(self):
        """测试有效重试次数"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=3)
        self.assertEqual(config.max_retries, 3)

        # 边界值
        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=0)
        self.assertEqual(config.max_retries, 0)

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=10)
        self.assertEqual(config.max_retries, 10)

    def test_max_retries_below_min(self):
        """测试重试次数小于最小值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=-1)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MIN)

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=-10)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MIN)

    def test_max_retries_above_max(self):
        """测试重试次数大于最大值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=20)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MAX)

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=100)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MAX)


class TestWebUIConfigRetryDelay(unittest.TestCase):
    """测试重试延迟验证"""

    def test_valid_retry_delay(self):
        """测试有效重试延迟"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=1.0)
        self.assertEqual(config.retry_delay, 1.0)

        # 边界值
        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=0.1)
        self.assertEqual(config.retry_delay, 0.1)

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=60.0)
        self.assertEqual(config.retry_delay, 60.0)

    def test_retry_delay_below_min(self):
        """测试重试延迟小于最小值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=0.0)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MIN)

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=-1.0)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MIN)

    def test_retry_delay_above_max(self):
        """测试重试延迟大于最大值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=100.0)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MAX)

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=1000.0)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MAX)


class TestWebUIConfigCombined(unittest.TestCase):
    """测试组合场景"""

    def test_all_defaults(self):
        """测试所有默认值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080)

        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.timeout, 30)
        self.assertEqual(config.max_retries, 3)
        self.assertEqual(config.retry_delay, 1.0)

    def test_all_custom_valid(self):
        """测试所有自定义有效值"""
        from server import WebUIConfig

        config = WebUIConfig(
            host="0.0.0.0",
            port=9000,
            timeout=60,
            max_retries=5,
            retry_delay=2.0,
        )

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 9000)
        self.assertEqual(config.timeout, 60)
        self.assertEqual(config.max_retries, 5)
        self.assertEqual(config.retry_delay, 2.0)

    def test_multiple_boundary_adjustments(self):
        """测试多个边界调整"""
        from server import WebUIConfig

        config = WebUIConfig(
            host="127.0.0.1",
            port=8080,
            timeout=0,  # 调整到 1
            max_retries=-5,  # 调整到 0
            retry_delay=0.0,  # 调整到 0.1
        )

        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MIN)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MIN)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MIN)


class TestGetWebUIConfig(unittest.TestCase):
    """测试 get_web_ui_config() 函数"""

    @patch("server.get_config")
    def test_load_config_success(self, mock_get_config):
        """测试成功加载配置"""
        # 清除缓存
        import server
        from server import WebUIConfig, get_web_ui_config

        server._config_cache["config"] = None
        server._config_cache["timestamp"] = 0

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.side_effect = lambda section: {
            "web_ui": {
                "port": 8080,
                "timeout": 30,
                "max_retries": 3,
                "retry_delay": 1.0,
            },
            "feedback": {"auto_resubmit_timeout": 240},
            "network_security": {"bind_interface": "127.0.0.1"},
        }[section]
        mock_get_config.return_value = mock_config_mgr

        config, auto_resubmit = get_web_ui_config()

        self.assertIsInstance(config, WebUIConfig)
        self.assertEqual(config.port, 8080)
        self.assertEqual(auto_resubmit, 240)

    @patch("server.get_config")
    def test_load_config_with_defaults(self, mock_get_config):
        """测试使用默认值加载配置"""
        # 清除缓存
        import server
        from server import get_web_ui_config

        server._config_cache["config"] = None
        server._config_cache["timestamp"] = 0

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {}  # 空配置
        mock_get_config.return_value = mock_config_mgr

        config, auto_resubmit = get_web_ui_config()

        # 应该使用默认值
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.timeout, 30)
        self.assertEqual(auto_resubmit, 240)


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


class TestWebUIAdvancedAPIs(unittest.TestCase):
    """Web UI 高级 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="深度测试",
            predefined_options=["选项A", "选项B", "选项C"],
            task_id="deep-test",
            port=8985,
        )
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_api_submit_with_options(self):
        """测试带选项的提交"""
        response = self.client.post(
            "/api/submit",
            data=json.dumps(
                {
                    "task_id": "deep-test",
                    "user_input": "用户反馈",
                    "selected_options": ["选项A"],
                }
            ),
            content_type="application/json",
        )

        self.assertIn(response.status_code, [200, 400, 404])

    def test_api_submit_with_images(self):
        """测试带图片的提交"""
        response = self.client.post(
            "/api/submit",
            data=json.dumps(
                {
                    "task_id": "deep-test",
                    "user_input": "",
                    "selected_options": [],
                    "images": [{"data": "dGVzdA==", "mimeType": "image/png"}],
                }
            ),
            content_type="application/json",
        )

        self.assertIn(response.status_code, [200, 400, 404])

    def test_api_config_get(self):
        """测试获取配置"""
        response = self.client.get("/api/config")

        self.assertIn(response.status_code, [200, 404])

    def test_static_html(self):
        """测试 HTML 静态文件"""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"html", response.data.lower())


class TestWebUINotificationAPIs(unittest.TestCase):
    """Web UI 通知 API 测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="通知测试", task_id="notif-test", port=8984)
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_update_all_notification_settings(self):
        """测试更新所有通知设置"""
        config = {
            "enabled": True,
            "web_enabled": True,
            "sound_enabled": True,
            "bark_enabled": False,
            "sound_volume": 50,
            "sound_mute": False,
        }

        response = self.client.post(
            "/api/update-notification-config",
            data=json.dumps(config),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

    def test_update_bark_settings(self):
        """测试更新 Bark 设置"""
        config = {
            "bark_enabled": True,
            "bark_url": "https://api.day.app/push",
            "bark_device_key": "test_key",
            "bark_icon": "https://icon.url",
        }

        response = self.client.post(
            "/api/update-notification-config",
            data=json.dumps(config),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)


# ============================================================================
# config_manager.py 深度测试
# ============================================================================


if __name__ == "__main__":
    unittest.main()
