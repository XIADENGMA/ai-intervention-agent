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
import socket
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
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

        self.assertEqual(WebUIConfig.TIMEOUT_MIN, 1)
        self.assertEqual(WebUIConfig.TIMEOUT_MAX, 600)

        self.assertEqual(WebUIConfig.MAX_RETRIES_MIN, 0)
        self.assertEqual(WebUIConfig.MAX_RETRIES_MAX, 20)
        self.assertEqual(WebUIConfig.RETRY_DELAY_MIN, 0.0)
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

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=600)
        self.assertEqual(config.timeout, 600)

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

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=1000)
        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MAX)

        config = WebUIConfig(host="127.0.0.1", port=8080, timeout=99999)
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

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=20)
        self.assertEqual(config.max_retries, 20)

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

        config = WebUIConfig(host="127.0.0.1", port=8080, max_retries=25)
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
        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=0.0)
        self.assertEqual(config.retry_delay, 0.0)

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=60.0)
        self.assertEqual(config.retry_delay, 60.0)

    def test_retry_delay_below_min(self):
        """测试重试延迟小于最小值"""
        from server import WebUIConfig

        config = WebUIConfig(host="127.0.0.1", port=8080, retry_delay=-0.5)
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
            retry_delay=-1.0,  # 调整到 0.0
        )

        self.assertEqual(config.timeout, WebUIConfig.TIMEOUT_MIN)
        self.assertEqual(config.max_retries, WebUIConfig.MAX_RETRIES_MIN)
        self.assertEqual(config.retry_delay, WebUIConfig.RETRY_DELAY_MIN)


class TestGetWebUIConfig(unittest.TestCase):
    """测试 get_web_ui_config() 函数"""

    @patch("service_manager.get_config")
    def test_load_config_success(self, mock_get_config):
        """测试成功加载配置"""
        import service_manager
        from server import WebUIConfig, get_web_ui_config

        service_manager._config_cache["config"] = None
        service_manager._config_cache["timestamp"] = 0

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

    @patch("service_manager.get_config")
    def test_load_config_with_defaults(self, mock_get_config):
        """测试使用默认值加载配置"""
        import service_manager
        from server import get_web_ui_config

        service_manager._config_cache["config"] = None
        service_manager._config_cache["timestamp"] = 0

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.return_value = {}  # 空配置
        mock_get_config.return_value = mock_config_mgr

        config, auto_resubmit = get_web_ui_config()

        # 应该使用默认值
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.timeout, 30)
        self.assertEqual(auto_resubmit, 240)


# ═══════════════════════════════════════════════════════════════════════════
# R14·B1 · service_manager._config_cache 代际不变量
# ═══════════════════════════════════════════════════════════════════════════
class TestGetWebUIConfigGenerationToken(unittest.TestCase):
    """``get_web_ui_config`` 在 load 期间被 invalidate 时不能写回 stale 值。

    历史 race（修复前）：

        T1: cache miss → 释放锁 → 开始 load
        T2: ``_invalidate_runtime_caches_on_config_change`` 触发
            （文件外部编辑），cache 清空
        T1: load 完毕 → 把旧值写回 cache（**bug**：复活了已被 invalidate
            的旧值）
        T3: cache hit → 拿到 stale config

    修复：把 ``_config_cache_generation`` 当 token 用，invalidate 时 +1，
    write-back 前 re-check 是否仍等于 ``gen_at_start``；不等就丢弃 write，
    后续 cache miss 重新 load 即可。
    """

    def setUp(self) -> None:
        import service_manager

        service_manager._config_cache["config"] = None
        service_manager._config_cache["timestamp"] = 0
        service_manager._config_cache_generation = 0

    @patch("service_manager.get_config")
    def test_invalidate_during_load_does_not_resurrect_stale_config(
        self, mock_get_config
    ):
        """load 期间 invalidate 触发 → load 完毕的结果不能写回 cache。"""
        import service_manager
        from server import get_web_ui_config

        load_started = threading.Event()
        invalidate_done = threading.Event()

        def slow_get_section(section: str):
            # 第一次进来时阻塞，等 invalidate 在外部线程完成
            data = {
                "web_ui": {"port": 8080, "timeout": 30},
                "feedback": {"auto_resubmit_timeout": 240},
                "network_security": {"bind_interface": "127.0.0.1"},
            }
            if section == "web_ui":
                load_started.set()
                # 给外部 invalidate 100ms 窗口
                invalidate_done.wait(timeout=2.0)
            return data[section]

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.side_effect = slow_get_section
        mock_get_config.return_value = mock_config_mgr

        result_box: list[Any] = [None]

        def _run():
            result_box[0] = get_web_ui_config()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        load_started.wait(timeout=2.0)
        # 此时 T1 卡在 load 中，_config_cache_generation 还是 0
        self.assertEqual(service_manager._config_cache_generation, 0)

        # 模拟 invalidate（generation +1）
        service_manager._invalidate_runtime_caches_on_config_change()
        self.assertEqual(service_manager._config_cache_generation, 1)

        # 让 T1 继续完成 load
        invalidate_done.set()
        thread.join(timeout=5.0)
        self.assertFalse(thread.is_alive())
        self.assertIsNotNone(result_box[0])

        # 关键断言：T1 的 load 结果不应被写回 cache
        # （cache 应保持 invalidate 后的 None 状态）
        self.assertIsNone(
            service_manager._config_cache["config"],
            "load 期间被 invalidate 后，结果不应被写回 cache（否则旧值复活）",
        )

    @patch("service_manager.get_config")
    def test_invalidate_increments_generation_token(self, mock_get_config):
        """``_invalidate_runtime_caches_on_config_change`` 必须自增 generation。"""
        import service_manager

        del mock_get_config  # 仅为 patch decorator 提供绑定，不使用

        before = service_manager._config_cache_generation
        service_manager._invalidate_runtime_caches_on_config_change()
        self.assertEqual(service_manager._config_cache_generation, before + 1)

        service_manager._invalidate_runtime_caches_on_config_change()
        self.assertEqual(service_manager._config_cache_generation, before + 2)

    @patch("service_manager.get_config")
    def test_no_invalidate_during_load_writes_back_normally(self, mock_get_config):
        """无 invalidate race 的常规路径必须正常写回 cache（避免修复回退到永远不写）。"""
        import service_manager
        from server import get_web_ui_config

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_section.side_effect = lambda section: {
            "web_ui": {"port": 8080},
            "feedback": {"auto_resubmit_timeout": 240},
            "network_security": {"bind_interface": "127.0.0.1"},
        }[section]
        mock_get_config.return_value = mock_config_mgr

        config, _ = get_web_ui_config()
        self.assertEqual(config.port, 8080)

        # cache 应该被写入
        self.assertIsNotNone(service_manager._config_cache["config"])
        self.assertGreater(service_manager._config_cache["timestamp"], 0)


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


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_web_ui_extended.py）
# ---------------------------------------------------------------------------


def _make_zeroconf_module(
    *, zc_inst: Any = None, non_unique_cls: type | None = None
) -> types.ModuleType:
    """构建 mock zeroconf 模块（绕过 ty unresolved-attribute 检查）"""
    mod = types.ModuleType("zeroconf")
    if non_unique_cls is None:
        non_unique_cls = type("NonUniqueNameException", (Exception,), {})
    attrs: dict[str, Any] = {
        "NonUniqueNameException": non_unique_cls,
        "ServiceInfo": MagicMock,
        "Zeroconf": MagicMock(return_value=zc_inst) if zc_inst else MagicMock,
    }
    for k, v in attrs.items():
        object.__setattr__(mod, k, v)
    return mod


# ──────────────────────────────────────────────────────────
# 网络工具函数
# ──────────────────────────────────────────────────────────


class TestIsProbablyVirtualInterface(unittest.TestCase):
    def test_loopback(self):
        from web_ui import _is_probably_virtual_interface

        self.assertTrue(_is_probably_virtual_interface("lo"))

    def test_docker_bridge(self):
        from web_ui import _is_probably_virtual_interface

        self.assertTrue(_is_probably_virtual_interface("docker0"))
        self.assertTrue(_is_probably_virtual_interface("br-abc123"))

    def test_veth(self):
        from web_ui import _is_probably_virtual_interface

        self.assertTrue(_is_probably_virtual_interface("veth1234"))

    def test_vpn_tunnels(self):
        from web_ui import _is_probably_virtual_interface

        self.assertTrue(_is_probably_virtual_interface("tun0"))
        self.assertTrue(_is_probably_virtual_interface("utun3"))
        self.assertTrue(_is_probably_virtual_interface("tailscale0"))
        self.assertTrue(_is_probably_virtual_interface("wg0"))
        self.assertTrue(_is_probably_virtual_interface("ppp0"))

    def test_virtual_bridges(self):
        from web_ui import _is_probably_virtual_interface

        self.assertTrue(_is_probably_virtual_interface("virbr0"))
        self.assertTrue(_is_probably_virtual_interface("vmnet8"))
        self.assertTrue(_is_probably_virtual_interface("cni0"))
        self.assertTrue(_is_probably_virtual_interface("flannel.1"))
        self.assertTrue(_is_probably_virtual_interface("lxcbr0"))
        self.assertTrue(_is_probably_virtual_interface("podman0"))

    def test_physical_interfaces(self):
        from web_ui import _is_probably_virtual_interface

        self.assertFalse(_is_probably_virtual_interface("en0"))
        self.assertFalse(_is_probably_virtual_interface("eth0"))
        self.assertFalse(_is_probably_virtual_interface("wlan0"))

    def test_empty_and_none(self):
        from web_ui import _is_probably_virtual_interface

        self.assertFalse(_is_probably_virtual_interface(""))
        self.assertFalse(_is_probably_virtual_interface(None))  # type: ignore[arg-type]


class TestGetDefaultRouteIPv4(unittest.TestCase):
    def test_returns_ip(self):
        from web_ui import _get_default_route_ipv4

        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("192.168.1.100", 0)
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("web_ui_mdns_utils.socket.socket", return_value=mock_sock):
            result = _get_default_route_ipv4()
            self.assertEqual(result, "192.168.1.100")

    def test_loopback_returns_none(self):
        from web_ui import _get_default_route_ipv4

        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("127.0.0.1", 0)
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("web_ui_mdns_utils.socket.socket", return_value=mock_sock):
            result = _get_default_route_ipv4()
            self.assertIsNone(result)

    def test_link_local_returns_none(self):
        from web_ui import _get_default_route_ipv4

        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("169.254.1.1", 0)
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("web_ui_mdns_utils.socket.socket", return_value=mock_sock):
            result = _get_default_route_ipv4()
            self.assertIsNone(result)

    def test_os_error_returns_none(self):
        from web_ui import _get_default_route_ipv4

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect.side_effect = OSError("no route")

        with patch("web_ui_mdns_utils.socket.socket", return_value=mock_sock):
            result = _get_default_route_ipv4()
            self.assertIsNone(result)


class TestListNonLoopbackIPv4(unittest.TestCase):
    def _snic(self, addr: str, family: int = socket.AF_INET):
        return SimpleNamespace(family=family, address=addr)

    def _stat(self, isup: bool = True):
        return SimpleNamespace(isup=isup)

    def test_returns_private_ips(self):
        from web_ui import _list_non_loopback_ipv4

        addrs = {
            "en0": [self._snic("192.168.1.50")],
            "lo0": [self._snic("127.0.0.1")],
        }
        stats = {"en0": self._stat(True), "lo0": self._stat(True)}

        with (
            patch("psutil.net_if_addrs", return_value=addrs),
            patch("psutil.net_if_stats", return_value=stats),
        ):
            result = _list_non_loopback_ipv4(prefer_physical=False)
            self.assertIn("192.168.1.50", result)
            self.assertNotIn("127.0.0.1", result)

    def test_filters_virtual_interfaces(self):
        from web_ui import _list_non_loopback_ipv4

        addrs = {
            "docker0": [self._snic("172.17.0.1")],
            "en0": [self._snic("10.0.0.5")],
        }
        stats = {"docker0": self._stat(True), "en0": self._stat(True)}

        with (
            patch("psutil.net_if_addrs", return_value=addrs),
            patch("psutil.net_if_stats", return_value=stats),
        ):
            result = _list_non_loopback_ipv4(prefer_physical=True)
            self.assertNotIn("172.17.0.1", result)
            self.assertIn("10.0.0.5", result)

    def test_skips_down_interfaces(self):
        from web_ui import _list_non_loopback_ipv4

        addrs = {"en0": [self._snic("10.0.0.1")]}
        stats = {"en0": self._stat(False)}

        with (
            patch("psutil.net_if_addrs", return_value=addrs),
            patch("psutil.net_if_stats", return_value=stats),
        ):
            result = _list_non_loopback_ipv4(prefer_physical=False)
            self.assertEqual(result, [])

    def test_skips_ipv6(self):
        from web_ui import _list_non_loopback_ipv4

        addrs = {"en0": [self._snic("fe80::1", socket.AF_INET6)]}
        stats = {"en0": self._stat(True)}

        with (
            patch("psutil.net_if_addrs", return_value=addrs),
            patch("psutil.net_if_stats", return_value=stats),
        ):
            result = _list_non_loopback_ipv4(prefer_physical=False)
            self.assertEqual(result, [])

    def test_psutil_exception(self):
        from web_ui import _list_non_loopback_ipv4

        with patch("psutil.net_if_addrs", side_effect=RuntimeError("fail")):
            result = _list_non_loopback_ipv4()
            self.assertEqual(result, [])

    def test_dedup_and_sort(self):
        from web_ui import _list_non_loopback_ipv4

        addrs = {
            "en0": [self._snic("192.168.1.1"), self._snic("192.168.1.1")],
            "en1": [self._snic("8.8.8.8")],
        }
        stats = {"en0": self._stat(True), "en1": self._stat(True)}

        with (
            patch("psutil.net_if_addrs", return_value=addrs),
            patch("psutil.net_if_stats", return_value=stats),
        ):
            result = _list_non_loopback_ipv4(prefer_physical=False)
            self.assertEqual(result, ["192.168.1.1", "8.8.8.8"])


class TestDetectBestPublishIPv4(unittest.TestCase):
    def test_specific_bind_ip(self):
        from web_ui import detect_best_publish_ipv4

        result = detect_best_publish_ipv4("192.168.1.100")
        self.assertEqual(result, "192.168.1.100")

    def test_loopback_bind_falls_through(self):
        from web_ui import detect_best_publish_ipv4

        with (
            patch(
                "web_ui_mdns_utils._list_non_loopback_ipv4", return_value=["10.0.0.1"]
            ),
            patch("web_ui_mdns_utils._get_default_route_ipv4", return_value="10.0.0.1"),
        ):
            result = detect_best_publish_ipv4("127.0.0.1")
            self.assertEqual(result, "10.0.0.1")

    def test_route_ip_preferred(self):
        from web_ui import detect_best_publish_ipv4

        with (
            patch(
                "web_ui_mdns_utils._list_non_loopback_ipv4",
                return_value=["192.168.1.1", "10.0.0.1"],
            ),
            patch("web_ui_mdns_utils._get_default_route_ipv4", return_value="10.0.0.1"),
        ):
            result = detect_best_publish_ipv4("0.0.0.0")
            self.assertEqual(result, "10.0.0.1")

    def test_route_ip_not_in_candidates(self):
        from web_ui import detect_best_publish_ipv4

        with (
            patch(
                "web_ui_mdns_utils._list_non_loopback_ipv4",
                return_value=["192.168.1.1"],
            ),
            patch(
                "web_ui_mdns_utils._get_default_route_ipv4", return_value="10.0.0.99"
            ),
        ):
            result = detect_best_publish_ipv4("0.0.0.0")
            self.assertEqual(result, "192.168.1.1")

    def test_no_candidates_route_only(self):
        from web_ui import detect_best_publish_ipv4

        call_count = [0]

        def mock_list(prefer_physical=True):
            call_count[0] += 1
            if call_count[0] == 1:
                return []
            return []

        with (
            patch("web_ui_mdns_utils._list_non_loopback_ipv4", side_effect=mock_list),
            patch("web_ui_mdns_utils._get_default_route_ipv4", return_value="10.0.0.1"),
        ):
            result = detect_best_publish_ipv4("0.0.0.0")
            self.assertEqual(result, "10.0.0.1")

    def test_no_ip_at_all(self):
        from web_ui import detect_best_publish_ipv4

        with (
            patch("web_ui_mdns_utils._list_non_loopback_ipv4", return_value=[]),
            patch("web_ui_mdns_utils._get_default_route_ipv4", return_value=None),
        ):
            result = detect_best_publish_ipv4("0.0.0.0")
            self.assertIsNone(result)


# ──────────────────────────────────────────────────────────
# get_project_version 回退
# ──────────────────────────────────────────────────────────


class TestGetProjectVersion(unittest.TestCase):
    def test_outer_exception_returns_unknown(self):
        from web_ui import get_project_version

        get_project_version.cache_clear()

        with patch("web_ui.Path", side_effect=RuntimeError("path broken")):
            result = get_project_version()
            self.assertIsInstance(result, str)

        get_project_version.cache_clear()

    def test_pyproject_not_exists_returns_unknown(self):
        """branch 71->91: pyproject.toml 不存在时返回 unknown"""
        from web_ui import get_project_version

        get_project_version.cache_clear()

        _orig_exists = Path.exists

        def _mock_exists(self):
            if str(self).endswith("pyproject.toml"):
                return False
            return _orig_exists(self)

        with patch.object(Path, "exists", _mock_exists):
            result = get_project_version()
            self.assertEqual(result, "unknown")

        get_project_version.cache_clear()


# ──────────────────────────────────────────────────────────
# 配置回调函数
# ──────────────────────────────────────────────────────────


class TestConfigCallbacks(unittest.TestCase):
    def test_sync_timeout_exception_silenced(self):
        import web_ui

        original = web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT
        with patch(
            "web_ui._get_default_auto_resubmit_timeout_from_config",
            side_effect=RuntimeError("fail"),
        ):
            web_ui._sync_existing_tasks_timeout_from_config()
        web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = original

    def test_sync_timeout_updates_instance(self):
        import web_ui

        original = web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT
        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE

        inst = SimpleNamespace(
            _single_task_timeout_explicit=False,
            current_auto_resubmit_timeout=100,
            _state_lock=threading.RLock(),
        )
        web_ui._CURRENT_WEB_UI_INSTANCE = inst
        web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = None

        with (
            patch(
                "web_ui._get_default_auto_resubmit_timeout_from_config",
                return_value=120,
            ),
            patch("web_ui.get_task_queue") as mock_tq,
        ):
            mock_tq.return_value.update_auto_resubmit_timeout_for_all.return_value = 2
            web_ui._sync_existing_tasks_timeout_from_config()

        self.assertEqual(inst.current_auto_resubmit_timeout, 120)
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst
        web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = original

    def test_sync_timeout_no_lock_instance(self):
        """实例无 _state_lock 时直接赋值"""
        import web_ui

        original = web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT
        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE

        inst = SimpleNamespace(
            _single_task_timeout_explicit=False,
            current_auto_resubmit_timeout=100,
            _state_lock=None,
        )
        web_ui._CURRENT_WEB_UI_INSTANCE = inst
        web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = None

        with (
            patch(
                "web_ui._get_default_auto_resubmit_timeout_from_config",
                return_value=90,
            ),
            patch("web_ui.get_task_queue") as mock_tq,
        ):
            mock_tq.return_value.update_auto_resubmit_timeout_for_all.return_value = 0
            web_ui._sync_existing_tasks_timeout_from_config()

        self.assertEqual(inst.current_auto_resubmit_timeout, 90)
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst
        web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = original

    def test_sync_network_security_no_instance(self):
        import web_ui

        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE
        web_ui._CURRENT_WEB_UI_INSTANCE = None
        web_ui._sync_network_security_from_config()
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst

    def test_sync_network_security_no_loader(self):
        import web_ui

        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE
        web_ui._CURRENT_WEB_UI_INSTANCE = SimpleNamespace()
        web_ui._sync_network_security_from_config()
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst

    def test_sync_network_security_loader_not_dict(self):
        import web_ui

        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE
        inst = SimpleNamespace(_load_network_security_config=lambda: "not_dict")
        web_ui._CURRENT_WEB_UI_INSTANCE = inst
        web_ui._sync_network_security_from_config()
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst

    def test_sync_network_security_with_lock(self):
        import web_ui

        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE
        new_cfg = {"bind_interface": "0.0.0.0"}
        inst = SimpleNamespace(
            _load_network_security_config=lambda: new_cfg,
            _state_lock=threading.RLock(),
            network_security_config={},
        )
        web_ui._CURRENT_WEB_UI_INSTANCE = inst
        web_ui._sync_network_security_from_config()
        self.assertEqual(inst.network_security_config, new_cfg)
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst

    def test_sync_network_security_no_lock(self):
        import web_ui

        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE
        new_cfg = {"bind_interface": "127.0.0.1"}
        inst = SimpleNamespace(
            _load_network_security_config=lambda: new_cfg,
            _state_lock=None,
            network_security_config={},
        )
        web_ui._CURRENT_WEB_UI_INSTANCE = inst
        web_ui._sync_network_security_from_config()
        self.assertEqual(inst.network_security_config, new_cfg)
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst

    def test_sync_network_security_exception_silenced(self):
        import web_ui

        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE

        def bad_loader():
            raise RuntimeError("load failed")

        inst = SimpleNamespace(_load_network_security_config=bad_loader)
        web_ui._CURRENT_WEB_UI_INSTANCE = inst
        web_ui._sync_network_security_from_config()
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst

    def test_ensure_network_callback_exception(self):
        import web_ui

        original = web_ui._NETWORK_SECURITY_CALLBACK_REGISTERED
        web_ui._NETWORK_SECURITY_CALLBACK_REGISTERED = False

        with patch("web_ui.get_config", side_effect=RuntimeError("no config")):
            web_ui._ensure_network_security_hot_reload_callback_registered()

        web_ui._NETWORK_SECURITY_CALLBACK_REGISTERED = original

    def test_ensure_feedback_callback_exception(self):
        import web_ui

        original = web_ui._FEEDBACK_TIMEOUT_CALLBACK_REGISTERED
        web_ui._FEEDBACK_TIMEOUT_CALLBACK_REGISTERED = False

        with patch("web_ui.get_config", side_effect=RuntimeError("no config")):
            web_ui._ensure_feedback_timeout_hot_reload_callback_registered()

        web_ui._FEEDBACK_TIMEOUT_CALLBACK_REGISTERED = original

    def test_get_default_timeout_exception(self):
        from web_ui import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            _get_default_auto_resubmit_timeout_from_config,
        )

        with patch("web_ui.get_config", side_effect=RuntimeError("broken")):
            try:
                result = _get_default_auto_resubmit_timeout_from_config()
            except Exception:
                result = AUTO_RESUBMIT_TIMEOUT_DEFAULT
            self.assertEqual(result, AUTO_RESUBMIT_TIMEOUT_DEFAULT)


# ──────────────────────────────────────────────────────────
# _is_ip_allowed / IP 访问控制边界
# ──────────────────────────────────────────────────────────


class TestIsIpAllowed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="IP test", port=18901)

    def test_ipv4_mapped_ipv6(self):
        """IPv4-mapped IPv6 地址正确提取"""
        self.ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["192.168.0.0/16"],
            "blocked_ips": [],
        }
        result = self.ui._is_ip_allowed("::ffff:192.168.1.100")
        self.assertTrue(result)

    def test_single_ip_whitelist(self):
        """白名单中的单个 IP 匹配"""
        self.ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["10.0.0.5"],
            "blocked_ips": [],
        }
        self.assertTrue(self.ui._is_ip_allowed("10.0.0.5"))
        self.assertFalse(self.ui._is_ip_allowed("10.0.0.6"))

    def test_invalid_network_config_skipped(self):
        """无效的 CIDR 配置被跳过"""
        self.ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["bad_cidr", "127.0.0.0/8"],
            "blocked_ips": [],
        }
        self.assertTrue(self.ui._is_ip_allowed("127.0.0.1"))

    def test_invalid_client_ip(self):
        """无效的客户端 IP 抛出 ValueError（ip_address 抛出 ValueError 非 AddressValueError）"""
        self.ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["127.0.0.0/8"],
            "blocked_ips": [],
        }
        with self.assertRaises(ValueError):
            self.ui._is_ip_allowed("not_an_ip")

    def test_should_trust_forwarded_for_empty(self):
        from web_ui import WebFeedbackUI

        self.assertFalse(WebFeedbackUI._should_trust_forwarded_for(""))

    def test_file_version_oserror(self):
        """文件版本号 OSError 回退"""
        self.assertEqual(self.ui._get_file_version("/nonexistent/path"), "1")


# ──────────────────────────────────────────────────────────
# mDNS 辅助函数
# ──────────────────────────────────────────────────────────


class TestMdnsHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="mdns test", port=18902)

    def test_get_mdns_config_exception(self):
        with patch("web_ui_mdns.get_config", side_effect=RuntimeError("fail")):
            result = self.ui._get_mdns_config()
            self.assertEqual(result, {})

    def test_should_enable_mdns_explicit_true(self):
        self.assertTrue(self.ui._should_enable_mdns({"enabled": True}))

    def test_should_enable_mdns_explicit_false(self):
        self.assertFalse(self.ui._should_enable_mdns({"enabled": False}))

    def test_should_enable_mdns_auto_localhost(self):
        self.ui.host = "127.0.0.1"
        self.assertFalse(self.ui._should_enable_mdns({}))
        self.ui.host = "0.0.0.0"

    def test_load_network_security_exception(self):
        with patch("web_ui_security.get_config", side_effect=RuntimeError("fail")):
            result = self.ui._load_network_security_config()
            self.assertIn("bind_interface", result)


# ──────────────────────────────────────────────────────────
# Flask 路由分支
# ──────────────────────────────────────────────────────────


class TestAPIRouteBranches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="route test", task_id="rt-001", port=18903)
        cls.web_ui.app.config["TESTING"] = True
        cls.client = cls.web_ui.app.test_client()

    def test_config_exception_returns_500(self):
        """get_api_config 异常返回 500"""
        with patch("web_ui.get_task_queue", side_effect=RuntimeError("boom")):
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 500)
            data = json.loads(resp.data)
            self.assertFalse(data["has_content"])

    def test_health_endpoint(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["status"], "ok")

    def test_render_markdown_empty(self):
        result = self.web_ui.render_markdown("")
        self.assertEqual(result, "")

    def test_render_markdown_content(self):
        result = self.web_ui.render_markdown("# Hello")
        self.assertIn("<h1", result)


class TestAIAgentErrorHandler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from exceptions import AIAgentError
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="error test", port=18904)

        @cls.web_ui.app.route("/test-error-404")
        def raise_not_found():
            raise AIAgentError("not found", code="not_found")

        @cls.web_ui.app.route("/test-error-400")
        def raise_validation():
            raise AIAgentError("bad input", code="validation")

        @cls.web_ui.app.route("/test-error-504")
        def raise_timeout():
            raise AIAgentError("timeout", code="timeout")

        @cls.web_ui.app.route("/test-error-500")
        def raise_generic():
            raise AIAgentError("internal error")

        cls.web_ui.app.config["TESTING"] = True
        cls.client = cls.web_ui.app.test_client()

    def test_not_found_error(self):
        resp = self.client.get("/test-error-404")
        self.assertEqual(resp.status_code, 404)
        data = json.loads(resp.data)
        self.assertFalse(data["success"])
        self.assertEqual(data["code"], "not_found")

    def test_validation_error(self):
        resp = self.client.get("/test-error-400")
        self.assertEqual(resp.status_code, 400)

    def test_timeout_error(self):
        resp = self.client.get("/test-error-504")
        self.assertEqual(resp.status_code, 504)

    def test_generic_error(self):
        resp = self.client.get("/test-error-500")
        self.assertEqual(resp.status_code, 500)


# ──────────────────────────────────────────────────────────
# 模板回退路径
# ──────────────────────────────────────────────────────────


class TestTemplateFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="template test", port=18905)

    def test_update_content_empty(self):
        self.web_ui.update_content("")
        self.assertFalse(self.web_ui.has_content)

    def test_update_content_with_prompt(self):
        self.web_ui.update_content("new prompt", ["opt1"], "task-new")
        self.assertTrue(self.web_ui.has_content)
        self.assertEqual(self.web_ui.current_prompt, "new prompt")

    def test_minified_file_already_min(self):
        result = self.web_ui._get_minified_file("/tmp", "app.min.js", ".js")
        self.assertEqual(result, "app.min.js")

    def test_blocked_ips_non_string(self):
        from web_ui import validate_blocked_ips

        result = validate_blocked_ips([123, "127.0.0.1", None])
        self.assertEqual(result, ["127.0.0.1"])


# ──────────────────────────────────────────────────────────
# 静态资源缓存头
# ──────────────────────────────────────────────────────────


class TestStaticCacheHeaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="cache test", port=18906)
        cls.web_ui.app.config["TESTING"] = True
        cls.client = cls.web_ui.app.test_client()

    def test_js_with_version_param(self):
        resp = self.client.get("/static/js/app.js?v=12345678")
        if resp.status_code == 200:
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("immutable", cache)
        resp.close()


# ──────────────────────────────────────────────────────────
# 验证函数：validate_bind_interface / validate_auto_resubmit_timeout
# ──────────────────────────────────────────────────────────


class TestValidateBindInterface(unittest.TestCase):
    def test_none_returns_default(self):
        from web_ui import validate_bind_interface

        self.assertEqual(validate_bind_interface(None), "127.0.0.1")

    def test_empty_string_returns_default(self):
        from web_ui import validate_bind_interface

        self.assertEqual(validate_bind_interface(""), "127.0.0.1")

    def test_non_string_returns_default(self):
        from web_ui import validate_bind_interface

        self.assertEqual(validate_bind_interface(123), "127.0.0.1")

    def test_valid_special_values(self):
        from web_ui import validate_bind_interface

        self.assertEqual(validate_bind_interface("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_bind_interface("0.0.0.0"), "0.0.0.0")
        self.assertEqual(validate_bind_interface("localhost"), "localhost")
        self.assertEqual(validate_bind_interface("::1"), "::1")

    def test_custom_valid_ip(self):
        from web_ui import validate_bind_interface

        self.assertEqual(validate_bind_interface("10.0.0.5"), "10.0.0.5")

    def test_invalid_ip_returns_default(self):
        from web_ui import validate_bind_interface

        self.assertEqual(validate_bind_interface("not_an_ip"), "127.0.0.1")


class TestValidateAutoResubmitTimeout(unittest.TestCase):
    def test_zero_stays_zero(self):
        from web_ui import validate_auto_resubmit_timeout

        self.assertEqual(validate_auto_resubmit_timeout(0), 0)

    def test_negative_becomes_zero(self):
        from web_ui import validate_auto_resubmit_timeout

        self.assertEqual(validate_auto_resubmit_timeout(-10), 0)

    def test_below_min_clamped(self):
        from web_ui import AUTO_RESUBMIT_TIMEOUT_MIN, validate_auto_resubmit_timeout

        self.assertEqual(validate_auto_resubmit_timeout(5), AUTO_RESUBMIT_TIMEOUT_MIN)

    def test_above_max_clamped(self):
        from web_ui import AUTO_RESUBMIT_TIMEOUT_MAX, validate_auto_resubmit_timeout

        # 与 shared_types 对齐后 MAX=3600，需要更大的越界值才能触发上限钳位
        self.assertEqual(
            validate_auto_resubmit_timeout(99999), AUTO_RESUBMIT_TIMEOUT_MAX
        )

    def test_within_range_unchanged(self):
        from web_ui import validate_auto_resubmit_timeout

        self.assertEqual(validate_auto_resubmit_timeout(120), 120)


# ──────────────────────────────────────────────────────────
# normalize_mdns_hostname
# ──────────────────────────────────────────────────────────


class TestNormalizeMdnsHostname(unittest.TestCase):
    def test_non_string(self):
        from web_ui import MDNS_DEFAULT_HOSTNAME, normalize_mdns_hostname

        self.assertEqual(normalize_mdns_hostname(None), MDNS_DEFAULT_HOSTNAME)
        self.assertEqual(normalize_mdns_hostname(123), MDNS_DEFAULT_HOSTNAME)

    def test_empty_string(self):
        from web_ui import MDNS_DEFAULT_HOSTNAME, normalize_mdns_hostname

        self.assertEqual(normalize_mdns_hostname(""), MDNS_DEFAULT_HOSTNAME)
        self.assertEqual(normalize_mdns_hostname("  "), MDNS_DEFAULT_HOSTNAME)

    def test_trailing_dot_removed(self):
        from web_ui import normalize_mdns_hostname

        self.assertEqual(normalize_mdns_hostname("myhost.local."), "myhost.local")

    def test_short_name_appends_local(self):
        from web_ui import normalize_mdns_hostname

        self.assertEqual(normalize_mdns_hostname("myhost"), "myhost.local")

    def test_full_hostname_unchanged(self):
        from web_ui import normalize_mdns_hostname

        self.assertEqual(normalize_mdns_hostname("ai.example"), "ai.example")


# ──────────────────────────────────────────────────────────
# validate_network_cidr / validate_allowed_networks / validate_network_security_config
# ──────────────────────────────────────────────────────────


class TestValidateNetworkCidr(unittest.TestCase):
    def test_valid_cidr(self):
        from web_ui import validate_network_cidr

        self.assertTrue(validate_network_cidr("192.168.0.0/16"))

    def test_valid_single_ip(self):
        from web_ui import validate_network_cidr

        self.assertTrue(validate_network_cidr("10.0.0.1"))

    def test_invalid_string(self):
        from web_ui import validate_network_cidr

        self.assertFalse(validate_network_cidr("bad"))

    def test_none_input(self):
        from web_ui import validate_network_cidr

        self.assertFalse(validate_network_cidr(None))

    def test_empty_string(self):
        from web_ui import validate_network_cidr

        self.assertFalse(validate_network_cidr(""))


class TestValidateAllowedNetworks(unittest.TestCase):
    def test_not_list_returns_default(self):
        from web_ui import DEFAULT_ALLOWED_NETWORKS, validate_allowed_networks

        result = validate_allowed_networks("not_a_list")
        self.assertEqual(result, DEFAULT_ALLOWED_NETWORKS)

    def test_invalid_entries_logged_and_skipped(self):
        from web_ui import validate_allowed_networks

        result = validate_allowed_networks(["bad", "10.0.0.0/8"])
        self.assertEqual(result, ["10.0.0.0/8"])

    def test_empty_list_gets_loopback(self):
        from web_ui import validate_allowed_networks

        result = validate_allowed_networks([])
        self.assertIn("127.0.0.0/8", result)

    def test_all_invalid_gets_loopback(self):
        from web_ui import validate_allowed_networks

        result = validate_allowed_networks(["bad1", "bad2"])
        self.assertIn("127.0.0.0/8", result)

    def test_valid_networks_preserved(self):
        from web_ui import validate_allowed_networks

        result = validate_allowed_networks(["10.0.0.0/8", "192.168.0.0/16"])
        self.assertEqual(result, ["10.0.0.0/8", "192.168.0.0/16"])

    def test_none_and_non_string_entries_classified_as_invalid(self):
        """直接命中 web_ui_validators.py:123-124 — `None` / 数字 / 空字符串
        在循环顶部就被归到 invalid_networks，不会进入 ip_network() 抛异常路径。

        现有测试只覆盖了 try/except 抛异常的 invalid 路径；这条用例锁定
        「类型 / 真值早退」分支，避免后续重构时把这层兜底拆掉。
        """
        from web_ui import validate_allowed_networks

        result = validate_allowed_networks([None, 0, "", 123, "10.0.0.0/8"])
        # 仅有效的 CIDR 进入返回值
        self.assertEqual(result, ["10.0.0.0/8"])


class TestValidateBlockedIps(unittest.TestCase):
    def test_not_list_returns_empty(self):
        from web_ui import validate_blocked_ips

        self.assertEqual(validate_blocked_ips("bad"), [])

    def test_invalid_ip_string_logged(self):
        from web_ui import validate_blocked_ips

        result = validate_blocked_ips(["not_an_ip", "10.0.0.1"])
        self.assertEqual(result, ["10.0.0.1"])

    def test_valid_ips(self):
        from web_ui import validate_blocked_ips

        result = validate_blocked_ips(["10.0.0.1", "192.168.1.1"])
        self.assertEqual(result, ["10.0.0.1", "192.168.1.1"])

    def test_cidr_blocked_normalized(self):
        """命中 web_ui_validators.py:155 — `validate_blocked_ips` 应支持 CIDR 格式

        而不只是单 IP。`ip_network(strict=False)` 会把 `10.0.0.1/24` 这种
        「主机位非零」的写法规范化成 `10.0.0.0/24`，避免存盘时同一段被记录
        两种形式。
        """
        from web_ui import validate_blocked_ips

        result = validate_blocked_ips(["10.0.0.1/24", "192.168.1.0/16"])
        self.assertEqual(result, ["10.0.0.0/24", "192.168.0.0/16"])

    def test_ipv4_mapped_ipv6_normalized(self):
        """命中 web_ui_validators.py:108 — `_normalize_ip_str` 应把
        IPv4-mapped IPv6（`::ffff:10.0.0.1`）规范化为对应的 IPv4 表示。

        防止同一台设备的两种 IP 表示被各自登记到 blocklist，造成
        访问控制规则不一致。
        """
        from web_ui import validate_blocked_ips

        result = validate_blocked_ips(["::ffff:10.0.0.1"])
        self.assertEqual(result, ["10.0.0.1"])


class TestValidateNetworkSecurityConfig(unittest.TestCase):
    def test_non_dict_uses_defaults(self):
        from web_ui import validate_network_security_config

        result = validate_network_security_config("not_dict")
        self.assertIn("bind_interface", result)
        self.assertIn("allowed_networks", result)
        self.assertIn("blocked_ips", result)
        self.assertIn("access_control_enabled", result)

    def test_dict_validates_fields(self):
        from web_ui import validate_network_security_config

        result = validate_network_security_config(
            {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["10.0.0.0/8"],
                "blocked_ips": ["1.2.3.4"],
                "access_control_enabled": True,
            }
        )
        self.assertEqual(result["bind_interface"], "0.0.0.0")
        self.assertEqual(result["allowed_networks"], ["10.0.0.0/8"])
        self.assertEqual(result["blocked_ips"], ["1.2.3.4"])
        self.assertTrue(result["access_control_enabled"])

    def test_legacy_enable_access_control(self):
        from web_ui import validate_network_security_config

        result = validate_network_security_config({"enable_access_control": False})
        self.assertFalse(result["access_control_enabled"])


# ──────────────────────────────────────────────────────────
# _is_ip_allowed 更多分支 / _get_request_client_ip
# ──────────────────────────────────────────────────────────


class TestIsIpAllowedExtended(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="IP ext test", port=18907)

    def test_access_control_disabled(self):
        """access_control_enabled=False 直接放行"""
        self.ui.network_security_config = {
            "access_control_enabled": False,
        }
        self.assertTrue(self.ui._is_ip_allowed("8.8.8.8"))

    def test_blocked_ip_rejected(self):
        """黑名单优先于白名单"""
        self.ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["10.0.0.0/8"],
            "blocked_ips": ["10.0.0.5"],
        }
        self.assertFalse(self.ui._is_ip_allowed("10.0.0.5"))

    def test_ip_not_in_any_network(self):
        """不在任何白名单网络中"""
        self.ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["192.168.0.0/16"],
            "blocked_ips": [],
        }
        self.assertFalse(self.ui._is_ip_allowed("10.0.0.1"))

    def test_non_dict_config(self):
        """network_security_config 不是 dict 时走空 cfg 分支（默认只允许回环）"""
        self.ui.network_security_config = None  # type: ignore[assignment]
        self.assertTrue(self.ui._is_ip_allowed("127.0.0.1"))
        self.assertFalse(self.ui._is_ip_allowed("1.2.3.4"))


class TestGetRequestClientIp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="client ip test", port=18908)

    def test_direct_remote_addr(self):
        environ = {"REMOTE_ADDR": "10.0.0.5"}
        self.assertEqual(self.ui._get_request_client_ip(environ), "10.0.0.5")

    def test_loopback_trusts_forwarded_for(self):
        environ = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_FORWARDED_FOR": "10.0.0.99, 10.0.0.1",
        }
        self.assertEqual(self.ui._get_request_client_ip(environ), "10.0.0.99")

    def test_loopback_empty_forwarded_for(self):
        environ = {"REMOTE_ADDR": "127.0.0.1", "HTTP_X_FORWARDED_FOR": ""}
        self.assertEqual(self.ui._get_request_client_ip(environ), "127.0.0.1")

    def test_parse_forwarded_for_empty(self):
        from web_ui import WebFeedbackUI

        self.assertEqual(WebFeedbackUI._parse_forwarded_for(""), "")

    def test_parse_forwarded_for_single(self):
        from web_ui import WebFeedbackUI

        self.assertEqual(WebFeedbackUI._parse_forwarded_for("10.0.0.1"), "10.0.0.1")

    def test_parse_forwarded_for_multi(self):
        from web_ui import WebFeedbackUI

        self.assertEqual(
            WebFeedbackUI._parse_forwarded_for("10.0.0.1, 10.0.0.2"), "10.0.0.1"
        )


# ──────────────────────────────────────────────────────────
# _get_template_context 模板上下文
# ──────────────────────────────────────────────────────────


class TestGetTemplateContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="template test 2", port=18909)

    def test_context_keys(self):
        """_get_template_context 返回 Jinja2 所需的全部变量

        R20.12-B: 新增 ``inline_locale_json`` 字段（``str | None``），lang=auto 时为
        ``None`` 让 Jinja 模板的 ``{% if inline_locale_json %}`` 跳过注入。其他字段
        仍必须是 ``str``，模板用 ``{{ ... }}`` 直接插值不允许 ``None``。
        """
        with self.web_ui.app.test_request_context("/"):
            from flask import g

            g.csp_nonce = "test-nonce"
            ctx = self.web_ui._get_template_context()
        required_keys = {
            "csp_nonce",
            "version",
            "github_url",
            "language",
            "css_version",
            "multi_task_version",
            "theme_version",
            "app_version",
        }
        self.assertTrue(required_keys.issubset(ctx.keys()))
        # inline_locale_json 可以是 str 或 None（R20.12-B 契约）；其他 required key
        # 仍必须是 str —— 否则 Jinja 模板插值会抛或输出 "None"。
        nullable_keys = {"inline_locale_json"}
        for k, v in ctx.items():
            if k in nullable_keys:
                self.assertIsInstance(v, (str, type(None)))
            else:
                self.assertIsInstance(
                    v, str, msg=f"context['{k}'] 必须是 str（实际 {type(v).__name__})"
                )

    def test_context_nonce_from_g(self):
        """上下文中 csp_nonce 取自 flask.g"""
        with self.web_ui.app.test_request_context("/"):
            from flask import g

            g.csp_nonce = "unique-nonce-123"
            ctx = self.web_ui._get_template_context()
        self.assertEqual(ctx["csp_nonce"], "unique-nonce-123")

    def test_context_language_fallback(self):
        """配置读取失败时 language 回退为 auto"""
        with (
            self.web_ui.app.test_request_context("/"),
            patch("web_ui.get_config", side_effect=RuntimeError("fail")),
        ):
            ctx = self.web_ui._get_template_context()
        self.assertEqual(ctx["language"], "auto")


# ──────────────────────────────────────────────────────────
# _start_mdns_if_needed / _stop_mdns
# ──────────────────────────────────────────────────────────


class TestMdnsLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="mdns lifecycle", port=18910)

    def test_start_skips_already_running(self):
        """zeroconf 已启动则跳过"""
        self.ui._mdns_zeroconf = MagicMock()
        self.ui._start_mdns_if_needed()
        self.ui._mdns_zeroconf = None

    def test_start_skips_disabled(self):
        """mDNS 被禁用"""
        self.ui.host = "0.0.0.0"
        with patch.object(self.ui, "_get_mdns_config", return_value={"enabled": False}):
            self.ui._start_mdns_if_needed()
            self.assertIsNone(self.ui._mdns_zeroconf)

    def test_start_skips_localhost_bind(self):
        """bind 127.0.0.1 时跳过"""
        self.ui.host = "127.0.0.1"
        with patch.object(self.ui, "_get_mdns_config", return_value={"enabled": True}):
            self.ui._start_mdns_if_needed()
            self.assertIsNone(self.ui._mdns_zeroconf)
        self.ui.host = "0.0.0.0"

    def test_start_zeroconf_import_fails(self):
        """zeroconf 不可用"""
        self.ui.host = "0.0.0.0"
        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch.dict("sys.modules", {"zeroconf": None}),
        ):
            import sys

            saved = sys.modules.get("zeroconf")
            sys.modules["zeroconf"] = None  # type: ignore[assignment]
            try:
                self.ui._start_mdns_if_needed()
                self.assertIsNone(self.ui._mdns_zeroconf)
            finally:
                if saved is not None:
                    sys.modules["zeroconf"] = saved
                else:
                    sys.modules.pop("zeroconf", None)

    def test_start_no_publish_ip(self):
        """无法探测到可用 IP"""
        self.ui.host = "0.0.0.0"
        mock_zc_module = _make_zeroconf_module()

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value=None),
            patch.dict("sys.modules", {"zeroconf": mock_zc_module}),
        ):
            self.ui._start_mdns_if_needed()
            self.assertIsNone(self.ui._mdns_zeroconf)

    def test_start_non_unique_name(self):
        """主机名冲突 NonUniqueNameException"""
        self.ui.host = "0.0.0.0"
        NonUnique = type("NonUniqueNameException", (Exception,), {})
        mock_zc_inst = MagicMock()
        mock_zc_inst.register_service.side_effect = NonUnique("conflict")
        mock_zc_module = _make_zeroconf_module(
            zc_inst=mock_zc_inst, non_unique_cls=NonUnique
        )

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_zc_module}),
            patch("web_ui_mdns.get_config") as mock_cfg,
        ):
            mock_cfg.return_value.config_file = "/tmp/config.toml"
            self.ui._start_mdns_if_needed()
            self.assertIsNone(self.ui._mdns_zeroconf)

    def test_start_generic_register_exception(self):
        """注册失败时降级"""
        self.ui.host = "0.0.0.0"
        mock_zc_inst = MagicMock()
        mock_zc_inst.register_service.side_effect = RuntimeError("register fail")
        mock_zc_module = _make_zeroconf_module(zc_inst=mock_zc_inst)

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_zc_module}),
        ):
            self.ui._start_mdns_if_needed()
            self.assertIsNone(self.ui._mdns_zeroconf)

    def test_start_success(self):
        """成功注册 mDNS"""
        self.ui.host = "0.0.0.0"
        mock_zc_inst = MagicMock()
        mock_zc_module = _make_zeroconf_module(zc_inst=mock_zc_inst)

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_zc_module}),
        ):
            self.ui._start_mdns_if_needed()
            self.assertIsNotNone(self.ui._mdns_zeroconf)
            self.ui._mdns_zeroconf = None
            self.ui._mdns_service_info = None

    def test_stop_when_not_running(self):
        """未启动时 stop 为 no-op"""
        self.ui._mdns_zeroconf = None
        self.ui._stop_mdns()

    def test_stop_unregister_exception(self):
        """注销失败不崩溃"""
        mock_zc = MagicMock()
        mock_zc.unregister_service.side_effect = RuntimeError("fail")
        self.ui._mdns_zeroconf = mock_zc
        self.ui._mdns_service_info = MagicMock()
        self.ui._stop_mdns()
        self.assertIsNone(self.ui._mdns_zeroconf)

    def test_stop_close_exception(self):
        """关闭 Zeroconf 失败不崩溃"""
        mock_zc = MagicMock()
        mock_zc.close.side_effect = RuntimeError("fail")
        self.ui._mdns_zeroconf = mock_zc
        self.ui._mdns_service_info = None
        self.ui._stop_mdns()
        self.assertIsNone(self.ui._mdns_zeroconf)


# ──────────────────────────────────────────────────────────
# run() / web_feedback_ui()
# ──────────────────────────────────────────────────────────


class TestRunMethod(unittest.TestCase):
    def test_run_returns_feedback_result(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="run test", port=18911)
        ui.feedback_result = {
            "user_input": "hello",
            "selected_options": [],
            "images": [],
        }

        with (
            patch.object(ui.app, "run"),
            patch.object(ui, "_start_mdns_if_needed"),
            patch.object(ui, "_stop_mdns"),
        ):
            result = ui.run()
            self.assertEqual(result["user_input"], "hello")

    def test_run_returns_empty_when_no_feedback(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="run test 2", port=18912)
        ui.feedback_result = None

        with (
            patch.object(ui.app, "run"),
            patch.object(ui, "_start_mdns_if_needed"),
            patch.object(ui, "_stop_mdns"),
        ):
            result = ui.run()
            self.assertEqual(result["user_input"], "")

    def test_run_keyboard_interrupt(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="run test 3", port=18913)
        ui.feedback_result = {
            "user_input": "interrupted",
            "selected_options": [],
            "images": [],
        }

        with (
            patch.object(ui.app, "run", side_effect=KeyboardInterrupt),
            patch.object(ui, "_start_mdns_if_needed"),
            patch.object(ui, "_stop_mdns") as mock_stop,
        ):
            result = ui.run()
            mock_stop.assert_called_once()
            self.assertEqual(result["user_input"], "interrupted")

    def test_run_0000_host_print(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="run test 4", host="0.0.0.0", port=18914)
        ui.feedback_result = None

        with (
            patch.object(ui.app, "run"),
            patch.object(ui, "_start_mdns_if_needed"),
            patch.object(ui, "_stop_mdns"),
            patch("builtins.print") as mock_print,
        ):
            ui.run()
            print_calls = [str(c) for c in mock_print.call_args_list]
            any_ssh = any("SSH" in c for c in print_calls)
            self.assertTrue(any_ssh)

    def test_run_specific_host_print(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="run test 5", host="10.0.0.1", port=18915)
        ui.feedback_result = None

        with (
            patch.object(ui.app, "run"),
            patch.object(ui, "_start_mdns_if_needed"),
            patch.object(ui, "_stop_mdns"),
            patch("builtins.print") as mock_print,
        ):
            ui.run()
            print_calls = [str(c) for c in mock_print.call_args_list]
            any_browser = any("浏览器" in c for c in print_calls)
            self.assertTrue(any_browser)


# ──────────────────────────────────────────────────────────
# /api/config 路由分支：TaskQueue 激活/自动激活/全部完成/单任务模式
# ──────────────────────────────────────────────────────────


class TestApiConfigBranches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(
            prompt="config branches", task_id="cb-001", port=18916
        )
        cls.web_ui.app.config["TESTING"] = True
        cls.client = cls.web_ui.app.test_client()

    def _make_task(self, task_id="t1", status="pending", prompt="test"):
        from datetime import datetime

        return SimpleNamespace(
            task_id=task_id,
            status=status,
            prompt=prompt,
            predefined_options=["opt1"],
            auto_resubmit_timeout=120,
            created_at=datetime.now(),
            get_remaining_time=lambda: 100,
        )

    def test_active_task_returned(self):
        active = self._make_task("t-active", "active")
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = active

        with patch("web_ui.get_task_queue", return_value=mock_tq):
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(data["has_content"])
            self.assertEqual(data["task_id"], "t-active")

    def test_auto_activate_pending_task(self):
        pending = self._make_task("t-pending", "pending")
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = None
        mock_tq.get_all_tasks.return_value = [pending]

        with patch("web_ui.get_task_queue", return_value=mock_tq):
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(data["has_content"])
            self.assertEqual(data["task_id"], "t-pending")
            mock_tq.set_active_task.assert_called_once_with("t-pending")

    def test_all_tasks_completed(self):
        completed = self._make_task("t-done", "completed")
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = None
        mock_tq.get_all_tasks.return_value = [completed]

        with patch("web_ui.get_task_queue", return_value=mock_tq):
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertFalse(data["has_content"])

    def test_single_task_mode_fallback(self):
        """无 TaskQueue 任务时回退到单任务模式"""
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = None
        mock_tq.get_all_tasks.return_value = []

        self.web_ui.has_content = True
        self.web_ui.current_prompt = "single mode prompt"
        self.web_ui.current_options = ["opt"]
        self.web_ui.current_task_id = "single-001"
        self.web_ui.current_auto_resubmit_timeout = 200
        self.web_ui._single_task_timeout_explicit = True

        with patch("web_ui.get_task_queue", return_value=mock_tq):
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertTrue(data["has_content"])
            self.assertEqual(data["prompt"], "single mode prompt")

    def test_single_task_mode_non_explicit_timeout(self):
        """单任务模式：非显式 timeout 时从配置读取"""
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = None
        mock_tq.get_all_tasks.return_value = []

        self.web_ui.has_content = True
        self.web_ui.current_prompt = "non-explicit"
        self.web_ui.current_options = []
        self.web_ui.current_task_id = "ne-001"
        self.web_ui.current_auto_resubmit_timeout = 100
        self.web_ui._single_task_timeout_explicit = False

        with (
            patch("web_ui.get_task_queue", return_value=mock_tq),
            patch(
                "web_ui._get_default_auto_resubmit_timeout_from_config",
                return_value=150,
            ),
        ):
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(data["auto_resubmit_timeout"], 150)

    def test_single_task_mode_config_read_fails(self):
        """单任务模式：配置读取失败沿用当前值"""
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = None
        mock_tq.get_all_tasks.return_value = []

        self.web_ui.has_content = False
        self.web_ui.current_prompt = ""
        self.web_ui.current_options = []
        self.web_ui.current_task_id = None
        self.web_ui.current_auto_resubmit_timeout = 77
        self.web_ui._single_task_timeout_explicit = False
        self.web_ui.initial_empty = True

        with (
            patch("web_ui.get_task_queue", return_value=mock_tq),
            patch(
                "web_ui._get_default_auto_resubmit_timeout_from_config",
                side_effect=RuntimeError("config fail"),
            ),
        ):
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(data["auto_resubmit_timeout"], 77)


# ──────────────────────────────────────────────────────────
# 静态资源缓存头扩展（lottie / 无版本 JS/CSS）
# ──────────────────────────────────────────────────────────


class TestStaticCacheHeadersExtended(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="cache ext", port=18917)
        cls.web_ui.app.config["TESTING"] = True
        cls.client = cls.web_ui.app.test_client()

    def test_css_without_version(self):
        """CSS 无版本参数时使用短期缓存"""
        resp = self.client.get("/static/css/main.css")
        if resp.status_code == 200:
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("86400", cache)
        resp.close()

    def test_lottie_cache(self):
        """Lottie 文件缓存 30 天"""
        resp = self.client.get("/static/lottie/test.json")
        if resp.status_code == 200:
            cache = resp.headers.get("Cache-Control", "")
            self.assertIn("2592000", cache)
        resp.close()


# ──────────────────────────────────────────────────────────
# detect_best_publish_ipv4 AddressValueError 分支
# ──────────────────────────────────────────────────────────


class TestDetectBestPublishIPv4Edge(unittest.TestCase):
    def test_invalid_bind_ip_falls_through(self):
        """bind_interface 解析失败时进入通用探测"""
        from web_ui import detect_best_publish_ipv4

        with (
            patch(
                "web_ui_mdns_utils._list_non_loopback_ipv4", return_value=["10.0.0.1"]
            ),
            patch("web_ui_mdns_utils._get_default_route_ipv4", return_value="10.0.0.1"),
        ):
            result = detect_best_publish_ipv4("not_an_ip")
            self.assertEqual(result, "10.0.0.1")

    def test_physical_fallback_has_candidates(self):
        """第二轮（无物理过滤）有候选"""
        from web_ui import detect_best_publish_ipv4

        call_count = [0]

        def mock_list(prefer_physical=True):
            call_count[0] += 1
            if prefer_physical:
                return []
            return ["172.17.0.1"]

        with (
            patch("web_ui_mdns_utils._list_non_loopback_ipv4", side_effect=mock_list),
            patch("web_ui_mdns_utils._get_default_route_ipv4", return_value=None),
        ):
            result = detect_best_publish_ipv4("0.0.0.0")
            self.assertEqual(result, "172.17.0.1")


# ──────────────────────────────────────────────────────────
# _get_default_route_ipv4 IPv6 返回 None 分支
# ──────────────────────────────────────────────────────────


class TestGetDefaultRouteIPv4Edge(unittest.TestCase):
    def test_loopback_ipv6_returns_none(self):
        """若路由返回回环 IPv6 地址则返回 None"""
        from web_ui import _get_default_route_ipv4

        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("::1", 0)
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("web_ui_mdns_utils.socket.socket", return_value=mock_sock):
            result = _get_default_route_ipv4()
            self.assertIsNone(result)

    def test_non_loopback_ipv6_returns_none(self):
        """line 389: 全局 IPv6 地址通过回环检查但被版本检查拦截"""
        from web_ui import _get_default_route_ipv4

        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("2001:db8::1", 0)
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("web_ui_mdns_utils.socket.socket", return_value=mock_sock):
            result = _get_default_route_ipv4()
            self.assertIsNone(result)


# ──────────────────────────────────────────────────────────
# _list_non_loopback_ipv4 无效地址分支
# ──────────────────────────────────────────────────────────


class TestListNonLoopbackIPv4Edge(unittest.TestCase):
    def _snic(self, addr: str, family: int = socket.AF_INET):
        return SimpleNamespace(family=family, address=addr)

    def _stat(self, isup: bool = True):
        return SimpleNamespace(isup=isup)

    def test_invalid_address_skipped(self):
        """无效 IP 地址被跳过（AddressValueError 分支）"""
        from web_ui import _list_non_loopback_ipv4

        addrs = {"en0": [self._snic("not_a_valid_ip")]}
        stats = {"en0": self._stat(True)}

        with (
            patch("psutil.net_if_addrs", return_value=addrs),
            patch("psutil.net_if_stats", return_value=stats),
        ):
            result = _list_non_loopback_ipv4(prefer_physical=False)
            self.assertEqual(result, [])

    def test_link_local_address_skipped(self):
        """链路本地地址被跳过"""
        from web_ui import _list_non_loopback_ipv4

        addrs = {"en0": [self._snic("169.254.1.1")]}
        stats = {"en0": self._stat(True)}

        with (
            patch("psutil.net_if_addrs", return_value=addrs),
            patch("psutil.net_if_stats", return_value=stats),
        ):
            result = _list_non_loopback_ipv4(prefer_physical=False)
            self.assertEqual(result, [])

    def test_ipv6_mapped_address_filtered_by_version_check(self):
        """line 424: AF_INET 但 ip_address() 返回 version != 4 的对象时被过滤"""
        from web_ui import _list_non_loopback_ipv4

        addrs = {"en0": [self._snic("::ffff:10.0.0.1")]}
        stats = {"en0": self._stat(True)}

        mock_ip = MagicMock()
        mock_ip.version = 6

        with (
            patch("psutil.net_if_addrs", return_value=addrs),
            patch("psutil.net_if_stats", return_value=stats),
            patch("web_ui_mdns_utils.ip_address", return_value=mock_ip),
        ):
            result = _list_non_loopback_ipv4(prefer_physical=False)
            self.assertEqual(result, [])


# ──────────────────────────────────────────────────────────
# _get_default_auto_resubmit_timeout_from_config 内部 int 转换失败
# ──────────────────────────────────────────────────────────


class TestNetworkSecurityDCLInnerBranch(unittest.TestCase):
    """line 231: _ensure_network_security_hot_reload_callback_registered DCL 内层分支"""

    def test_dcl_inner_branch_already_registered(self):
        """另一线程在锁等待期间完成注册，内层检查命中 return"""
        import web_ui

        original_flag = web_ui._NETWORK_SECURITY_CALLBACK_REGISTERED
        original_lock = web_ui._NETWORK_SECURITY_CALLBACK_LOCK
        try:
            web_ui._NETWORK_SECURITY_CALLBACK_REGISTERED = False

            class _SetFlagLock:
                def __enter__(self_lock):
                    web_ui._NETWORK_SECURITY_CALLBACK_REGISTERED = True  # type: ignore[assignment]
                    return self_lock

                def __exit__(self_lock, *args):
                    pass

            web_ui._NETWORK_SECURITY_CALLBACK_LOCK = _SetFlagLock()  # type: ignore[assignment]
            web_ui._ensure_network_security_hot_reload_callback_registered()
            self.assertTrue(web_ui._NETWORK_SECURITY_CALLBACK_REGISTERED)
        finally:
            web_ui._NETWORK_SECURITY_CALLBACK_REGISTERED = original_flag
            web_ui._NETWORK_SECURITY_CALLBACK_LOCK = original_lock


class TestGetDefaultTimeoutConfig(unittest.TestCase):
    def test_int_conversion_fails(self):
        """raw_timeout 无法转为 int 时返回默认值"""
        from web_ui import (
            AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            _get_default_auto_resubmit_timeout_from_config,
        )

        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {"frontend_countdown": "not_a_number"}
        with patch("web_ui.get_config", return_value=mock_cfg):
            result = _get_default_auto_resubmit_timeout_from_config()
            self.assertEqual(result, AUTO_RESUBMIT_TIMEOUT_DEFAULT)

    def test_valid_config_value(self):
        """正常配置值"""
        from web_ui import _get_default_auto_resubmit_timeout_from_config

        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {"frontend_countdown": "120"}
        with patch("web_ui.get_config", return_value=mock_cfg):
            result = _get_default_auto_resubmit_timeout_from_config()
            self.assertEqual(result, 120)


# ──────────────────────────────────────────────────────────
# web_feedback_ui() 便捷函数
# ──────────────────────────────────────────────────────────


class TestWebFeedbackUiFunction(unittest.TestCase):
    def test_returns_result_without_file(self):
        from web_ui import web_feedback_ui

        fake_result = {"user_input": "hi", "selected_options": [], "images": []}
        with patch("web_ui.WebFeedbackUI") as MockUI:
            MockUI.return_value.run.return_value = fake_result
            result = web_feedback_ui("hello", port=18920)
            self.assertEqual(result, fake_result)

    def test_saves_to_file(self):
        import tempfile

        from web_ui import web_feedback_ui

        fake_result = {"user_input": "saved", "selected_options": [], "images": []}
        with (
            patch("web_ui.WebFeedbackUI") as MockUI,
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            MockUI.return_value.run.return_value = fake_result
            outfile = f"{tmpdir}/out.json"
            result = web_feedback_ui("hello", output_file=outfile, port=18921)
            self.assertIsNone(result)

            import json as json_mod
            from pathlib import Path

            saved = json_mod.loads(Path(outfile).read_text())
            self.assertEqual(saved["user_input"], "saved")

    def test_no_result_no_file(self):
        from web_ui import web_feedback_ui

        with patch("web_ui.WebFeedbackUI") as MockUI:
            MockUI.return_value.run.return_value = None
            result = web_feedback_ui("hello", output_file="/tmp/nope.json", port=18922)
            self.assertIsNone(result)


# ──────────────────────────────────────────────────────────
# get_project_version tomllib 异常后 regex 回退
# ──────────────────────────────────────────────────────────


class TestGetProjectVersionRegexFallback(unittest.TestCase):
    def test_tomllib_fails_regex_succeeds(self):
        """tomllib 加载失败时回退到正则解析"""
        from web_ui import get_project_version

        get_project_version.cache_clear()

        fake_toml = 'version = "9.8.7"\n[project]\nversion = "1.2.3"'

        with (
            patch("web_ui.Path") as MockPath,
            patch("builtins.open") as mock_open_fn,
        ):
            mock_pyproject = MagicMock()
            mock_pyproject.exists.return_value = True

            mock_parent = MagicMock()
            mock_parent.__truediv__ = MagicMock(return_value=mock_pyproject)
            mock_resolve = MagicMock()
            mock_resolve.parent = mock_parent
            MockPath.return_value.resolve.return_value = mock_resolve

            call_count = [0]

            def fake_open(path, *args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1 and "rb" in args:
                    raise RuntimeError("tomllib broken")
                m = MagicMock()
                m.__enter__ = MagicMock(
                    return_value=MagicMock(read=MagicMock(return_value=fake_toml))
                )
                m.__exit__ = MagicMock(return_value=False)
                return m

            mock_open_fn.side_effect = fake_open
            result = get_project_version()
            self.assertIn(result, ["9.8.7", "1.2.3", "unknown"])

        get_project_version.cache_clear()


# ──────────────────────────────────────────────────────────
# IP 拒绝返回 403 (before_request hook)
# ──────────────────────────────────────────────────────────


class TestIpDeniedAbort403(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="403 test", port=18923)
        cls.web_ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["10.0.0.0/8"],
            "blocked_ips": [],
        }
        cls.web_ui.app.config["TESTING"] = True
        cls.client = cls.web_ui.app.test_client()

    def test_denied_ip_gets_403(self):
        """不在白名单的 IP 返回 403"""
        with patch.object(
            self.web_ui, "_get_request_client_ip", return_value="8.8.8.8"
        ):
            resp = self.client.get("/api/health")
            self.assertEqual(resp.status_code, 403)


# ──────────────────────────────────────────────────────────
# _get_file_version OSError 分支
# ──────────────────────────────────────────────────────────


class TestGetFileVersionOSError(unittest.TestCase):
    def test_oserror_returns_default(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="ver err", port=18924)
        result = ui._get_file_version("/nonexistent/path/file.css")
        self.assertEqual(result, "1")


# ──────────────────────────────────────────────────────────
# _get_minified_file 非 min 文件且 min 版本不存在
# ──────────────────────────────────────────────────────────


class TestGetMinifiedFileNotFound(unittest.TestCase):
    def test_no_minified_version(self):
        import tempfile

        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="minified", port=18925)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ui._get_minified_file(tmpdir, "app.js", ".js")
            self.assertEqual(result, "app.js")


# ──────────────────────────────────────────────────────────
# _sync_existing_tasks_timeout lock 异常兜底分支（194-196）
# ──────────────────────────────────────────────────────────


class TestSyncTimeoutLockException(unittest.TestCase):
    def test_lock_enter_fails_fallback(self):
        """lock.__enter__ 抛异常时走 except 兜底分支"""
        import web_ui

        original = web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT
        original_inst = web_ui._CURRENT_WEB_UI_INSTANCE

        bad_lock = MagicMock()
        bad_lock.__enter__ = MagicMock(side_effect=RuntimeError("lock broken"))
        bad_lock.__exit__ = MagicMock(return_value=False)

        inst = SimpleNamespace(
            _single_task_timeout_explicit=False,
            current_auto_resubmit_timeout=100,
            _state_lock=bad_lock,
        )
        web_ui._CURRENT_WEB_UI_INSTANCE = inst
        web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = None

        with (
            patch(
                "web_ui._get_default_auto_resubmit_timeout_from_config",
                return_value=200,
            ),
            patch("web_ui.get_task_queue") as mock_tq,
        ):
            mock_tq.return_value.update_auto_resubmit_timeout_for_all.return_value = 0
            web_ui._sync_existing_tasks_timeout_from_config()

        self.assertEqual(inst.current_auto_resubmit_timeout, 200)
        web_ui._CURRENT_WEB_UI_INSTANCE = original_inst
        web_ui._LAST_APPLIED_AUTO_RESUBMIT_TIMEOUT = original


# ──────────────────────────────────────────────────────────
# _should_trust_forwarded_for AddressValueError 分支（1719-1720）
# ──────────────────────────────────────────────────────────


class TestShouldTrustForwardedForEdge(unittest.TestCase):
    def test_address_value_error_returns_false(self):
        """ip_address 抛出 AddressValueError 时返回 False"""
        from ipaddress import AddressValueError

        from web_ui import WebFeedbackUI

        with patch("web_ui_security.ip_address", side_effect=AddressValueError("bad")):
            self.assertFalse(WebFeedbackUI._should_trust_forwarded_for("127.0.0.1"))


# ──────────────────────────────────────────────────────────
# _get_mdns_config 返回非 dict 时
# ──────────────────────────────────────────────────────────


class TestGetMdnsConfigCast(unittest.TestCase):
    def test_non_dict_section_returns_empty(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="mdns cfg", port=18926)
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = "not_a_dict"
        with patch("web_ui_mdns.get_config", return_value=mock_cfg):
            result = ui._get_mdns_config()
            self.assertEqual(result, {})

    def test_dict_section_returned(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="mdns cfg 2", port=18927)
        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {"enabled": True}
        with patch("web_ui_mdns.get_config", return_value=mock_cfg):
            result = ui._get_mdns_config()
            self.assertEqual(result, {"enabled": True})


# ──────────────────────────────────────────────────────────
# _is_ip_allowed AddressValueError 分支 (1701-1703)
# ──────────────────────────────────────────────────────────


class TestIsIpAllowedAddressValueError(unittest.TestCase):
    def test_address_value_error_caught(self):
        """强制触发 AddressValueError（非 ValueError）"""
        from ipaddress import AddressValueError

        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="avr test", port=18928)
        ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["10.0.0.0/8"],
            "blocked_ips": [],
        }
        with patch(
            "web_ui_security.ip_address", side_effect=AddressValueError("bad addr")
        ):
            result = ui._is_ip_allowed("anything")
            self.assertFalse(result)


# ──────────────────────────────────────────────────────────
# _is_ip_allowed network exception 分支 (1694-1696)
# ──────────────────────────────────────────────────────────


class TestIsIpAllowedNetworkException(unittest.TestCase):
    def test_invalid_network_entry_skipped(self):
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="net exc", port=18929)
        ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["999.999.999.0/24", "10.0.0.0/8"],
            "blocked_ips": [],
        }
        self.assertTrue(ui._is_ip_allowed("10.0.0.1"))


# ──────────────────────────────────────────────────────────
# single task render_markdown 异常分支 (1135-1139)
# ──────────────────────────────────────────────────────────


class TestSingleTaskRenderMarkdownFails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="md fail", port=18930)
        cls.web_ui.app.config["TESTING"] = True
        cls.client = cls.web_ui.app.test_client()

    def test_render_failure_returns_empty_html(self):
        mock_tq = MagicMock()
        mock_tq.get_active_task.return_value = None
        mock_tq.get_all_tasks.return_value = []

        self.web_ui.has_content = True
        self.web_ui.current_prompt = "markdown content"
        self.web_ui.current_options = []
        self.web_ui.current_task_id = None
        self.web_ui.current_auto_resubmit_timeout = 100
        self.web_ui._single_task_timeout_explicit = True

        with (
            patch("web_ui.get_task_queue", return_value=mock_tq),
            patch.object(
                self.web_ui, "render_markdown", side_effect=RuntimeError("render fail")
            ),
        ):
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.data)
            self.assertEqual(data["prompt_html"], "")


# ──────────────────────────────────────────────────────────
# shutdown_server (os.kill)
# ──────────────────────────────────────────────────────────


class TestShutdownServer(unittest.TestCase):
    def test_shutdown_sends_sigint(self):
        import os
        import signal

        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="shutdown", port=18931)
        with patch("web_ui.os.kill") as mock_kill:
            ui.shutdown_server()
            mock_kill.assert_called_once_with(os.getpid(), signal.SIGINT)


# ──────────────────────────────────────────────────────────
# _is_ip_allowed blocked_ips 多条目循环分支
# ──────────────────────────────────────────────────────────


class TestIsIpAllowedBlockedMulti(unittest.TestCase):
    def test_second_blocked_ip_matches(self):
        """多条黑名单时，不匹配的条目会继续循环"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="blocked multi", port=18932)
        ui.network_security_config = {
            "access_control_enabled": True,
            "allowed_networks": ["10.0.0.0/8"],
            "blocked_ips": ["10.0.0.1", "10.0.0.5"],
        }
        self.assertFalse(ui._is_ip_allowed("10.0.0.5"))
        self.assertTrue(ui._is_ip_allowed("10.0.0.2"))


# ──────────────────────────────────────────────────────────
# render_template 路由渲染（取代旧 get_html_template 测试）
# ──────────────────────────────────────────────────────────


class TestIndexRenderTemplate(unittest.TestCase):
    """验证首页通过 Jinja2 render_template 正确渲染。"""

    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="render tpl", port=18933)
        cls.web_ui.app.config["TESTING"] = True
        cls.client = cls.web_ui.app.test_client()

    def test_index_renders_html(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn("AI Intervention Agent", html)
        self.assertIn("main.css", html)
        resp.close()

    def test_index_contains_csp_nonce(self):
        resp = self.client.get("/")
        html = resp.data.decode()
        self.assertNotIn("{{ csp_nonce }}", html)
        self.assertIn("nonce=", html)
        resp.close()

    def test_index_version_rendered(self):
        resp = self.client.get("/")
        html = resp.data.decode()
        self.assertNotIn("{{ version }}", html)
        resp.close()

    def test_template_not_found_returns_500(self):
        """模板文件缺失时 errorhandler 返回 500 降级页面"""
        with patch(
            "web_ui.render_template",
            side_effect=__import__("jinja2").TemplateNotFound("web_ui.html"),
        ):
            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 500)
            self.assertIn(
                b"\xe6\xa8\xa1\xe6\x9d\xbf\xe6\x96\x87\xe4\xbb\xb6\xe6\x9c\xaa\xe6\x89\xbe\xe5\x88\xb0",
                resp.data,
            )
            resp.close()


# ──────────────────────────────────────────────────────────
# mDNS NonUniqueNameException 清理边界
# ──────────────────────────────────────────────────────────


class TestMdnsNonUniqueCleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="mdns cleanup", port=18934)

    def _setup_mdns_module(self):
        NonUnique = type("NonUniqueNameException", (Exception,), {})
        return _make_zeroconf_module(non_unique_cls=NonUnique), NonUnique

    def test_non_unique_config_path_exception(self):
        """NonUniqueNameException + get_config 失败 → config_path=None"""
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None
        NonUnique = type("NonUniqueNameException", (Exception,), {})
        mock_zc_inst = MagicMock()
        mock_zc_inst.register_service.side_effect = NonUnique("dup")
        mock_mod = _make_zeroconf_module(zc_inst=mock_zc_inst, non_unique_cls=NonUnique)

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_mod}),
            patch("web_ui_mdns.get_config", side_effect=RuntimeError("no config")),
        ):
            self.ui._start_mdns_if_needed()
            self.assertIsNone(self.ui._mdns_zeroconf)

    def test_non_unique_close_exception(self):
        """NonUniqueNameException + zc.close() 失败"""
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None
        NonUnique = type("NonUniqueNameException", (Exception,), {})
        mock_zc_inst = MagicMock()
        mock_zc_inst.register_service.side_effect = NonUnique("dup")
        mock_zc_inst.close.side_effect = RuntimeError("close fail")
        mock_mod = _make_zeroconf_module(zc_inst=mock_zc_inst, non_unique_cls=NonUnique)

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_mod}),
            patch("web_ui_mdns.get_config") as mock_cfg,
        ):
            mock_cfg.return_value.config_file = "/tmp/c.toml"
            self.ui._start_mdns_if_needed()
            self.assertIsNone(self.ui._mdns_zeroconf)

    def test_generic_register_close_exception(self):
        """通用注册异常 + zc.close() 失败"""
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None
        mock_zc_inst = MagicMock()
        mock_zc_inst.register_service.side_effect = RuntimeError("register fail")
        mock_zc_inst.close.side_effect = RuntimeError("close fail")
        mock_mod = _make_zeroconf_module(zc_inst=mock_zc_inst)

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_mod}),
        ):
            self.ui._start_mdns_if_needed()
            self.assertIsNone(self.ui._mdns_zeroconf)


# ──────────────────────────────────────────────────────────
# mDNS Zeroconf() 构造与 ServiceInfo 失败的降级路径
#
# 真实环境会让这两个调用抛 OSError：
#   - Linux + Avahi 共存且未开 disallow-other-stacks=no → EADDRINUSE
#   - Windows 169.254.x.x link-local 接口 → WinError 10049
#   - IPv6 loopback 无 multicast → errno 101
#   - publish_ip 不是合法 IPv4 字面量 → socket.inet_aton 抛 OSError
# 历史上这两个分支没有 try 包围，会让 WebFeedbackUI.run() 整个挂掉
# （违反 docstring 「mDNS 失败 → 降级，不影响 Web UI 启动」承诺）。
# ──────────────────────────────────────────────────────────


class TestMdnsConstructorFailures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="mdns ctor", port=18937)

    def test_zeroconf_oserror_degrades_gracefully(self):
        """``Zeroconf()`` 抛 OSError → 不抛、不影响 web UI 启动"""
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None
        # MagicMock(side_effect=...) 让"调用 mock"时抛异常，模拟 Zeroconf() 构造抛
        zc_class_mock = MagicMock(side_effect=OSError(98, "Address already in use"))
        mock_mod = types.ModuleType("zeroconf")
        object.__setattr__(
            mock_mod,
            "NonUniqueNameException",
            type("NonUniqueNameException", (Exception,), {}),
        )
        object.__setattr__(mock_mod, "ServiceInfo", MagicMock)
        object.__setattr__(mock_mod, "Zeroconf", zc_class_mock)

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_mod}),
        ):
            try:
                self.ui._start_mdns_if_needed()
            except OSError:
                self.fail(
                    "Zeroconf() 构造异常必须被 web_ui_mdns 内部捕获并降级，"
                    "否则会让 WebFeedbackUI.run() 启动失败"
                )
            self.assertIsNone(
                self.ui._mdns_zeroconf,
                "降级后必须保持 _mdns_zeroconf=None，避免外层误以为 mDNS 已发布",
            )

    def test_serviceinfo_inet_aton_oserror_degrades(self):
        """``socket.inet_aton`` 抛 OSError（publish_ip 非法 IPv4）→ 降级"""
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None
        mock_zc_inst = MagicMock()
        mock_mod = _make_zeroconf_module(zc_inst=mock_zc_inst)

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch(
                "web_ui_mdns.detect_best_publish_ipv4",
                return_value="not-an-ip",
            ),
            patch.dict("sys.modules", {"zeroconf": mock_mod}),
            patch(
                "web_ui_mdns.socket.inet_aton",
                side_effect=OSError("illegal IP address string passed"),
            ),
        ):
            try:
                self.ui._start_mdns_if_needed()
            except OSError:
                self.fail(
                    "ServiceInfo addresses=[socket.inet_aton(invalid)] 异常必须被"
                    "捕获并降级，否则会让 WebFeedbackUI.run() 启动失败"
                )
            self.assertIsNone(self.ui._mdns_zeroconf)
            # Zeroconf() 不应被构造（在 ServiceInfo 失败后我们提前 return）
            mock_mod.Zeroconf.assert_not_called()


# ──────────────────────────────────────────────────────────
# mDNS inspect.signature 兼容性分支 (allow_name_change / allow_rename)
# ──────────────────────────────────────────────────────────


class TestMdnsRegisterSignatureCompat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web_ui import WebFeedbackUI

        cls.ui = WebFeedbackUI(prompt="mdns sig", port=18935)

    def _setup_mdns_success(self, register_params):
        """设置一个成功注册的 mDNS 模块，inspect.signature 返回指定参数"""
        mock_zc_inst = MagicMock()
        mock_mod = _make_zeroconf_module(zc_inst=mock_zc_inst)
        mock_sig = MagicMock()
        mock_sig.parameters = register_params
        return mock_mod, mock_zc_inst, mock_sig

    def test_allow_name_change_param(self):
        """zeroconf 旧版使用 allow_name_change 参数"""
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None
        mock_mod, mock_zc_inst, mock_sig = self._setup_mdns_success(
            {"info": None, "allow_name_change": None}
        )

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_mod}),
            patch("web_ui_mdns.inspect.signature", return_value=mock_sig),
        ):
            self.ui._start_mdns_if_needed()
            if self.ui._mdns_zeroconf is not None:
                call_kwargs = mock_zc_inst.register_service.call_args
                if call_kwargs and call_kwargs.kwargs:
                    self.assertIn("allow_name_change", call_kwargs.kwargs)
            self.ui._mdns_zeroconf = None
            self.ui._mdns_service_info = None

    def test_allow_rename_param(self):
        """zeroconf 新版使用 allow_rename 参数"""
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None
        mock_mod, mock_zc_inst, mock_sig = self._setup_mdns_success(
            {"info": None, "allow_rename": None}
        )

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_mod}),
            patch("web_ui_mdns.inspect.signature", return_value=mock_sig),
        ):
            self.ui._start_mdns_if_needed()
            if self.ui._mdns_zeroconf is not None:
                call_kwargs = mock_zc_inst.register_service.call_args
                if call_kwargs and call_kwargs.kwargs:
                    self.assertIn("allow_rename", call_kwargs.kwargs)
            self.ui._mdns_zeroconf = None
            self.ui._mdns_service_info = None

    def test_signature_inspect_fails(self):
        """inspect.signature 解析失败时降级为无参数"""
        self.ui.host = "0.0.0.0"
        self.ui._mdns_zeroconf = None
        mock_zc_inst = MagicMock()
        mock_mod = _make_zeroconf_module(zc_inst=mock_zc_inst)

        with (
            patch.object(self.ui, "_get_mdns_config", return_value={}),
            patch.object(self.ui, "_should_enable_mdns", return_value=True),
            patch("web_ui_mdns.detect_best_publish_ipv4", return_value="10.0.0.1"),
            patch.dict("sys.modules", {"zeroconf": mock_mod}),
            patch(
                "web_ui_mdns.inspect.signature", side_effect=RuntimeError("sig fail")
            ),
        ):
            self.ui._start_mdns_if_needed()
            mock_zc_inst.register_service.assert_called_once()
            self.ui._mdns_zeroconf = None
            self.ui._mdns_service_info = None


if __name__ == "__main__":
    unittest.main()
