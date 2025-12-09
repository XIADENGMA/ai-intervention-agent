#!/usr/bin/env python3
"""
AI Intervention Agent - 深度覆盖率测试

针对 server.py, web_ui.py, config_manager.py 的深度测试
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
# server.py 深度测试
# ============================================================================


class TestServerAsyncFunctions(unittest.TestCase):
    """服务器异步函数测试"""

    def test_get_feedback_prompts(self):
        """测试获取反馈提示"""
        from server import get_feedback_prompts

        resubmit, suffix = get_feedback_prompts()

        self.assertIsInstance(resubmit, str)
        self.assertIsInstance(suffix, str)
        self.assertIn("interactive_feedback", resubmit)

    def test_parse_structured_response_with_multiple_options(self):
        """测试解析多选项响应"""
        from server import parse_structured_response

        response = {
            "user_input": "测试多选项",
            "selected_options": ["选项1", "选项2", "选项3"],
            "images": [],
        }

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)
        # 检查选项是否包含在结果中
        result_text = str(result)
        self.assertIn("选项", result_text)

    def test_parse_structured_response_empty_input(self):
        """测试解析空输入响应"""
        from server import parse_structured_response

        response = {"user_input": "", "selected_options": [], "images": []}

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)

    def test_validate_input_with_special_chars(self):
        """测试带特殊字符的输入验证"""
        from server import validate_input

        message = "测试 <script>alert('xss')</script> & 特殊字符"
        options = ["选项 <b>粗体</b>", "选项 &amp;"]

        result_msg, result_opts = validate_input(message, options)

        self.assertIsInstance(result_msg, str)
        self.assertIsInstance(result_opts, list)


class TestServerWebUIManagement(unittest.TestCase):
    """Web UI 管理测试"""

    def test_ensure_web_ui_running_callable(self):
        """测试确保 Web UI 运行函数可调用"""
        from server import ensure_web_ui_running

        # 函数应该存在
        self.assertIsNotNone(ensure_web_ui_running)

    def test_wait_for_task_completion_callable(self):
        """测试等待任务完成函数可调用"""
        from server import wait_for_task_completion

        self.assertIsNotNone(wait_for_task_completion)


# ============================================================================
# web_ui.py 深度测试
# ============================================================================


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


class TestConfigManagerAdvancedFeatures(unittest.TestCase):
    """配置管理器高级功能测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_config_with_comments(self):
        """测试带注释的配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "comments.jsonc"
        content = """{
    // 这是单行注释
    "key1": "value1",
    /* 这是
       多行注释 */
    "key2": "value2"
}"""

        with open(config_file, "w") as f:
            f.write(content)

        mgr = ConfigManager(str(config_file))

        self.assertEqual(mgr.get("key1"), "value1")
        self.assertEqual(mgr.get("key2"), "value2")

    def test_config_deep_nested(self):
        """测试深度嵌套配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "deep_nested.json"
        config = {"level1": {"level2": {"level3": {"level4": {"value": "deep"}}}}}

        with open(config_file, "w") as f:
            json.dump(config, f)

        mgr = ConfigManager(str(config_file))

        level1 = mgr.get_section("level1")
        self.assertIn("level2", level1)

    def test_config_array_values(self):
        """测试数组值配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "array.json"
        config = {"items": ["item1", "item2", "item3"], "numbers": [1, 2, 3, 4, 5]}

        with open(config_file, "w") as f:
            json.dump(config, f)

        mgr = ConfigManager(str(config_file))

        items = mgr.get("items")
        self.assertEqual(len(items), 3)

    def test_config_special_characters(self):
        """测试特殊字符配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "special.json"
        config = {
            "url": "https://example.com/path?query=value&other=123",
            "unicode": "中文测试 日本語 한국어",
            "emoji": "🎉 🚀 ✅",
        }

        with open(config_file, "w") as f:
            json.dump(config, f, ensure_ascii=False)

        mgr = ConfigManager(str(config_file))

        self.assertIn("https://", mgr.get("url"))
        self.assertIn("中文", mgr.get("unicode"))


class TestConfigManagerNetworkSecurityAdvanced(unittest.TestCase):
    """网络安全配置高级测试"""

    def test_get_network_security_config_full(self):
        """测试获取完整网络安全配置"""
        from config_manager import config_manager

        security = config_manager.get_network_security_config()

        # 检查必要字段
        self.assertIn("bind_interface", security)
        self.assertIn("allowed_networks", security)
        # 支持新旧两种配置名称
        self.assertTrue(
            "enable_access_control" in security or "access_control_enabled" in security
        )

    def test_network_security_allowed_networks(self):
        """测试允许的网络列表"""
        from config_manager import config_manager

        security = config_manager.get_network_security_config()
        allowed = security.get("allowed_networks", [])

        self.assertIsInstance(allowed, list)


class TestReadWriteLockAdvanced(unittest.TestCase):
    """读写锁高级测试"""

    def test_write_lock_exclusive(self):
        """测试写锁独占"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        results = []

        def writer():
            with lock.write_lock():
                results.append("write_start")
                time.sleep(0.05)
                results.append("write_end")

        def reader():
            with lock.read_lock():
                results.append("read")

        # 启动写线程
        t1 = threading.Thread(target=writer)
        t1.start()
        time.sleep(0.01)  # 确保写锁先获取

        # 启动读线程
        t2 = threading.Thread(target=reader)
        t2.start()

        t1.join()
        t2.join()

        # 写操作应该先完成
        self.assertEqual(results[0], "write_start")
        self.assertEqual(results[1], "write_end")


# ============================================================================
# 跨模块集成测试
# ============================================================================


class TestCrossModuleIntegration(unittest.TestCase):
    """跨模块集成测试"""

    def test_config_notification_sync(self):
        """测试配置与通知同步"""
        from notification_manager import notification_manager

        # 刷新配置
        notification_manager.refresh_config_from_file(force=True)

        # 获取通知配置
        config = notification_manager.get_config()

        # 验证配置一致性
        self.assertIsNotNone(config)

    def test_web_ui_task_queue_integration(self):
        """测试 Web UI 与任务队列集成"""
        from web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="集成测试", task_id="integration-001", port=8983)

        # 验证 Flask app 已创建
        self.assertIsNotNone(ui.app)

    def test_notification_provider_config(self):
        """测试通知提供者配置"""
        from notification_manager import NotificationConfig

        config = NotificationConfig.from_config_file()

        self.assertIsInstance(config, NotificationConfig)


def run_tests():
    """运行所有深度覆盖测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Server 测试
    suite.addTests(loader.loadTestsFromTestCase(TestServerAsyncFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestServerWebUIManagement))

    # Web UI 测试
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIAdvancedAPIs))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUINotificationAPIs))

    # Config Manager 测试
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerAdvancedFeatures))
    suite.addTests(
        loader.loadTestsFromTestCase(TestConfigManagerNetworkSecurityAdvanced)
    )
    suite.addTests(loader.loadTestsFromTestCase(TestReadWriteLockAdvanced))

    # 集成测试
    suite.addTests(loader.loadTestsFromTestCase(TestCrossModuleIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
