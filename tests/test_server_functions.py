"""
AI Intervention Agent - Server 函数测试

针对 server.py 中各种函数的单元测试
"""

import asyncio
import signal
import socket
import subprocess
import threading
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, PropertyMock, patch

import httpx
from mcp.types import TextContent

import server
import service_manager
from exceptions import (
    ServiceConnectionError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)
from server_config import WebUIConfig


class TestValidateInput(unittest.TestCase):
    """输入验证函数测试"""

    def test_validate_normal_message(self):
        """测试正常消息验证"""
        from server import validate_input

        message, options = validate_input("正常消息", ["选项1", "选项2"])

        self.assertEqual(message, "正常消息")
        self.assertEqual(options, ["选项1", "选项2"])

    def test_validate_empty_message(self):
        """测试空消息验证"""
        from server import validate_input

        message, options = validate_input("", [])

        self.assertEqual(message, "")

    def test_validate_long_message_truncation(self):
        """测试长消息截断"""
        from server import validate_input

        long_message = "测" * 20000  # 超长消息
        message, options = validate_input(long_message, [])

        # 应该被截断（可能包含截断提示，所以留一些余量）
        self.assertLess(len(message), 20000)

    def test_validate_options_filtering(self):
        """测试选项过滤"""
        from server import validate_input

        # 混合类型的选项
        mixed_options = ["有效选项", 123, None, "另一个选项"]
        message, options = validate_input("消息", mixed_options)

        # 非字符串选项应该被过滤
        self.assertIsInstance(options, list)

    def test_validate_long_option_truncation(self):
        """测试长选项截断"""
        from server import validate_input

        long_option = "选" * 1000  # 超长选项
        message, options = validate_input("消息", [long_option])

        # 选项应该被截断（可能包含截断提示）
        if options:
            self.assertLess(len(options[0]), 1000)


class TestParseStructuredResponse(unittest.TestCase):
    """解析结构化响应测试"""

    def test_parse_standard_response(self):
        """测试标准响应格式"""
        from mcp.types import TextContent

        from server import parse_structured_response

        response = {
            "user_input": "用户输入内容",
            "selected_options": ["选项A", "选项B"],
            "images": [],
        }

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self.assertTrue(any(isinstance(item, TextContent) for item in result))

    def test_parse_response_with_options_only(self):
        """测试仅有选项的响应"""
        from server import parse_structured_response

        response = {"user_input": "", "selected_options": ["确认"], "images": []}

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)

    def test_parse_response_with_images(self):
        """测试带图片的响应"""
        from mcp.types import ImageContent, TextContent

        from server import parse_structured_response

        response = {
            "user_input": "带图片的反馈",
            "selected_options": [],
            "images": [
                {
                    "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    "mimeType": "image/png",
                }
            ],
        }

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)
        # 应该包含文本和图片内容
        self.assertGreater(len(result), 0)
        self.assertTrue(any(isinstance(item, ImageContent) for item in result))
        self.assertTrue(any(isinstance(item, TextContent) for item in result))
        img = next(item for item in result if isinstance(item, ImageContent))
        self.assertEqual(img.mimeType, "image/png")

    def test_parse_empty_response(self):
        """测试空响应"""
        from server import parse_structured_response

        response = {"user_input": "", "selected_options": [], "images": []}

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)

    def test_parse_legacy_response(self):
        """测试旧格式响应"""
        from server import parse_structured_response

        response = {"interactive_feedback": "旧格式的反馈内容"}

        result = parse_structured_response(response)

        self.assertIsInstance(result, list)


class TestWaitForTaskCompletion(unittest.TestCase):
    """等待任务完成函数测试"""

    def test_wait_for_task_completion_exists(self):
        """测试函数存在"""
        try:
            from server import wait_for_task_completion

            self.assertTrue(callable(wait_for_task_completion))
        except ImportError:
            self.skipTest("无法导入 wait_for_task_completion")


class TestEnsureWebUIRunning(unittest.TestCase):
    """确保 Web UI 运行函数测试"""

    def test_ensure_web_ui_running_exists(self):
        """测试函数存在"""
        try:
            from server import ensure_web_ui_running

            self.assertTrue(callable(ensure_web_ui_running))
        except ImportError:
            self.skipTest("无法导入 ensure_web_ui_running")


class TestGetTargetHost(unittest.TestCase):
    """get_target_host() 行为测试"""

    def test_ipv4_any_to_localhost(self):
        """0.0.0.0 作为监听地址时，客户端应连接 localhost"""
        from server import get_target_host

        self.assertEqual(get_target_host("0.0.0.0"), "localhost")

    def test_ipv6_any_to_localhost(self):
        """:: 作为监听地址时，客户端应连接 localhost"""
        from server import get_target_host

        self.assertEqual(get_target_host("::"), "localhost")

    def test_normal_host_unchanged(self):
        """普通地址应保持不变"""
        from server import get_target_host

        self.assertEqual(get_target_host("127.0.0.1"), "127.0.0.1")


class TestLaunchFeedbackUI(unittest.TestCase):
    """启动反馈 UI 函数测试"""

    def test_launch_feedback_ui_exists(self):
        """测试函数存在"""
        try:
            from server import launch_feedback_ui

            self.assertTrue(callable(launch_feedback_ui))
        except ImportError:
            self.skipTest("无法导入 launch_feedback_ui")


class TestServerConstants(unittest.TestCase):
    """服务器常量测试"""

    def test_max_message_length(self):
        """测试最大消息长度常量"""
        try:
            from server import MAX_MESSAGE_LENGTH

            self.assertIsInstance(MAX_MESSAGE_LENGTH, int)
            self.assertGreater(MAX_MESSAGE_LENGTH, 0)
        except ImportError:
            self.skipTest("无法导入 MAX_MESSAGE_LENGTH")

    def test_max_option_length(self):
        """测试最大选项长度常量"""
        try:
            from server import MAX_OPTION_LENGTH

            self.assertIsInstance(MAX_OPTION_LENGTH, int)
            self.assertGreater(MAX_OPTION_LENGTH, 0)
        except ImportError:
            self.skipTest("无法导入 MAX_OPTION_LENGTH")


class TestServerLogger(unittest.TestCase):
    """服务器日志测试"""

    def test_logger_exists(self):
        """测试日志器存在"""
        try:
            from server import logger

            self.assertIsNotNone(logger)
        except ImportError:
            self.skipTest("无法导入 logger")


class TestInteractiveFeedbackTool(unittest.TestCase):
    """交互式反馈工具测试"""

    def test_interactive_feedback_exists(self):
        """测试 interactive_feedback 函数存在"""
        try:
            from server import interactive_feedback

            # interactive_feedback 可能是被 MCP 装饰器处理的异步函数
            self.assertIsNotNone(interactive_feedback)
        except ImportError:
            self.skipTest("无法导入 interactive_feedback")


class TestContentTypes(unittest.TestCase):
    """MCP 内容类型测试"""

    def test_text_content_creation(self):
        """测试文本内容创建"""
        from mcp.types import TextContent

        content = TextContent(type="text", text="测试文本")

        self.assertEqual(content.type, "text")
        self.assertEqual(content.text, "测试文本")

    def test_image_content_creation(self):
        """测试图片内容创建"""
        from mcp.types import ImageContent

        content = ImageContent(type="image", data="base64data", mimeType="image/png")

        self.assertEqual(content.type, "image")
        self.assertEqual(content.mimeType, "image/png")


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


def run_tests():
    """运行所有服务器函数测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestValidateInput))
    suite.addTests(loader.loadTestsFromTestCase(TestParseStructuredResponse))
    suite.addTests(loader.loadTestsFromTestCase(TestWaitForTaskCompletion))
    suite.addTests(loader.loadTestsFromTestCase(TestEnsureWebUIRunning))
    suite.addTests(loader.loadTestsFromTestCase(TestLaunchFeedbackUI))
    suite.addTests(loader.loadTestsFromTestCase(TestServerConstants))
    suite.addTests(loader.loadTestsFromTestCase(TestServerLogger))
    suite.addTests(loader.loadTestsFromTestCase(TestInteractiveFeedbackTool))
    suite.addTests(loader.loadTestsFromTestCase(TestContentTypes))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_server_extended.py）
# ---------------------------------------------------------------------------


_SERVER_DIR = Path(server.__file__ or ".").resolve().parent


def _mock_arun_closing(*return_values):
    """构建 asyncio.run 的 mock side_effect，在返回前关闭传入的协程。

    避免 mock asyncio.run 后真实协程未被 await/close 导致 RuntimeWarning。
    若 return_values 中某项是 BaseException 子类实例，则抛出而非返回。
    """
    it = iter(return_values)

    def _side_effect(coro, *_a, **_kw):
        if hasattr(coro, "close"):
            coro.close()
        val = next(it)
        if isinstance(val, BaseException):
            raise val
        return val

    return _side_effect


def _make_config(
    host: str = "127.0.0.1",
    port: int = 8080,
    timeout: int = 30,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> WebUIConfig:
    return WebUIConfig(
        host=host,
        port=port,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )


class TestInvalidateRuntimeCaches(unittest.TestCase):
    def test_clears_config_cache(self):
        with service_manager._config_cache_lock:
            service_manager._config_cache["config"] = "stale"
            service_manager._config_cache["timestamp"] = 999

        service_manager._invalidate_runtime_caches_on_config_change()

        with service_manager._config_cache_lock:
            self.assertIsNone(service_manager._config_cache["config"])
            self.assertEqual(service_manager._config_cache["timestamp"], 0)

    def test_resets_httpx_clients(self):
        service_manager._sync_client = MagicMock()
        service_manager._sync_client.is_closed = False
        service_manager._async_client = MagicMock()

        service_manager._invalidate_runtime_caches_on_config_change()

        self.assertIsNone(service_manager._sync_client)
        self.assertIsNone(service_manager._async_client)


class TestEnsureConfigCallbacksRegistered(unittest.TestCase):
    def test_registers_once(self):
        original = service_manager._config_callbacks_registered
        service_manager._config_callbacks_registered = False
        try:
            mock_cfg = MagicMock()
            with patch("service_manager.get_config", return_value=mock_cfg):
                service_manager._ensure_config_change_callbacks_registered()
                self.assertTrue(service_manager._config_callbacks_registered)
                mock_cfg.register_config_change_callback.assert_called_once()
        finally:
            service_manager._config_callbacks_registered = original

    def test_double_check_lock_skip(self):
        original = service_manager._config_callbacks_registered
        service_manager._config_callbacks_registered = True
        try:
            service_manager._ensure_config_change_callbacks_registered()
        finally:
            service_manager._config_callbacks_registered = original

    def test_exception_does_not_crash(self):
        """注册失败时不崩溃，但标志位保持 False 以允许下次重试。"""
        original = service_manager._config_callbacks_registered
        service_manager._config_callbacks_registered = False
        try:
            with patch(
                "service_manager.get_config",
                side_effect=RuntimeError("no config"),
            ):
                service_manager._ensure_config_change_callbacks_registered()
                self.assertFalse(service_manager._config_callbacks_registered)
        finally:
            service_manager._config_callbacks_registered = original


# ═══════════════════════════════════════════════════════════════════════════
#  get_task_queue / _shutdown_global_task_queue
#
#  R20.8 后实现已迁移到 task_queue_singleton 模块；server.{get_task_queue,
#  _shutdown_global_task_queue} 是 re-export。测试同时验证 server 入口的
#  公开 API 行为，并在 task_queue_singleton 模块上 patch 全局单例（不再
#  存在 server._global_task_queue 这个模块变量）。
# ═══════════════════════════════════════════════════════════════════════════
import task_queue_singleton


class TestGetTaskQueue(unittest.TestCase):
    def test_lazy_init(self):
        original = task_queue_singleton._global_task_queue
        task_queue_singleton._global_task_queue = None
        try:
            tq = server.get_task_queue()
            self.assertIsNotNone(tq)
            same = server.get_task_queue()
            self.assertIs(tq, same)
        finally:
            task_queue_singleton._global_task_queue = original

    def test_re_export_identity(self):
        """server.get_task_queue 必须是 task_queue_singleton.get_task_queue 的别名。

        R20.8 优化依赖此恒等关系：web_ui 子进程从 task_queue_singleton 直接
        import，而 server.get_task_queue 仍作为公开 API 暴露——两者必须返
        回**完全相同的 callable**，否则会出现「外部调用 server.get_task_queue
        命中实例 A，内部 web_ui 调用拿到实例 B」的双单例分裂 bug。
        """
        self.assertIs(server.get_task_queue, task_queue_singleton.get_task_queue)


class TestShutdownGlobalTaskQueue(unittest.TestCase):
    def test_with_running_queue(self):
        original = task_queue_singleton._global_task_queue
        mock_tq = MagicMock()
        task_queue_singleton._global_task_queue = mock_tq
        try:
            server._shutdown_global_task_queue()
            mock_tq.stop_cleanup.assert_called_once()
        finally:
            task_queue_singleton._global_task_queue = original

    def test_with_none_queue(self):
        original = task_queue_singleton._global_task_queue
        task_queue_singleton._global_task_queue = None
        try:
            server._shutdown_global_task_queue()
        finally:
            task_queue_singleton._global_task_queue = original

    def test_exception_suppressed(self):
        original = task_queue_singleton._global_task_queue
        mock_tq = MagicMock()
        mock_tq.stop_cleanup.side_effect = RuntimeError("oops")
        task_queue_singleton._global_task_queue = mock_tq
        try:
            server._shutdown_global_task_queue()
        finally:
            task_queue_singleton._global_task_queue = original


# ═══════════════════════════════════════════════════════════════════════════
#  ServiceManager
# ═══════════════════════════════════════════════════════════════════════════
class TestServiceManager(unittest.TestCase):
    def setUp(self):
        server.ServiceManager._instance = None
        server.ServiceManager._lock = threading.Lock()

    def tearDown(self):
        server.ServiceManager._instance = None

    def test_singleton(self):
        sm1 = server.ServiceManager()
        sm2 = server.ServiceManager()
        self.assertIs(sm1, sm2)

    def test_register_and_get_process(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 12345
        cfg = _make_config()

        sm.register_process("test_svc", mock_proc, cfg)
        self.assertIs(sm.get_process("test_svc"), mock_proc)

    def test_get_process_not_found(self):
        sm = server.ServiceManager()
        self.assertIsNone(sm.get_process("nonexistent"))

    def test_unregister_process(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        sm.register_process("s1", mock_proc, _make_config())
        sm.unregister_process("s1")
        self.assertIsNone(sm.get_process("s1"))

    def test_unregister_nonexistent(self):
        sm = server.ServiceManager()
        sm.unregister_process("nope")

    def test_is_process_running_true(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 200
        mock_proc.poll.return_value = None
        sm.register_process("running", mock_proc, _make_config())
        self.assertTrue(sm.is_process_running("running"))

    def test_is_process_running_false_exited(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 201
        mock_proc.poll.return_value = 0
        sm.register_process("exited", mock_proc, _make_config())
        self.assertFalse(sm.is_process_running("exited"))

    def test_is_process_running_not_registered(self):
        sm = server.ServiceManager()
        self.assertFalse(sm.is_process_running("ghost"))

    def test_is_process_running_poll_exception(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 202
        mock_proc.poll.side_effect = OSError("gone")
        sm.register_process("error", mock_proc, _make_config())
        self.assertFalse(sm.is_process_running("error"))
        sm.unregister_process("error")

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_terminate_already_exited(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 300
        mock_proc.poll.return_value = 0
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("done", mock_proc, _make_config())
        self.assertTrue(sm.terminate_process("done"))
        self.assertIsNone(sm.get_process("done"))

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_terminate_graceful(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 301
        mock_proc.poll.side_effect = [None, 0]
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("graceful", mock_proc, _make_config())
        self.assertTrue(sm.terminate_process("graceful", timeout=1.0))
        mock_proc.terminate.assert_called_once()

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_terminate_force_kill(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 302
        mock_proc.poll.side_effect = [None, None, 0]
        mock_proc.terminate.side_effect = None
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("force", mock_proc, _make_config())
        result = sm.terminate_process("force", timeout=0.1)
        mock_proc.kill.assert_called_once()

    def test_terminate_not_registered(self):
        sm = server.ServiceManager()
        self.assertTrue(sm.terminate_process("nobody"))

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_cleanup_all_with_processes(self, _):
        sm = server.ServiceManager()
        for i in range(2):
            mock_proc = MagicMock(spec=subprocess.Popen)
            mock_proc.pid = 400 + i
            mock_proc.poll.return_value = 0
            mock_proc.stdin = None
            mock_proc.stdout = None
            mock_proc.stderr = None
            sm.register_process(f"svc_{i}", mock_proc, _make_config())

        sm.cleanup_all(shutdown_notification_manager=False)
        self.assertEqual(sm.get_status(), {})

    def test_cleanup_all_empty(self):
        sm = server.ServiceManager()
        sm.cleanup_all(shutdown_notification_manager=False)

    def test_get_status(self):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 500
        mock_proc.poll.return_value = None
        cfg = _make_config(port=9999)
        sm.register_process("status_test", mock_proc, cfg)

        status = sm.get_status()
        self.assertIn("status_test", status)
        self.assertEqual(status["status_test"]["pid"], 500)
        self.assertTrue(status["status_test"]["running"])

    def test_signal_handler_main_thread(self):
        sm = server.ServiceManager()
        with patch.object(sm, "cleanup_all"):
            with self.assertRaises(KeyboardInterrupt):
                sm._signal_handler(2, None)
            self.assertTrue(sm._should_exit)

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_cleanup_process_resources(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 600
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()

        sm._cleanup_process_resources("test", {"process": mock_proc})
        mock_proc.stdin.close.assert_called_once()
        mock_proc.stdout.close.assert_called_once()
        mock_proc.stderr.close.assert_called_once()

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_graceful_shutdown_timeout(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 1)
        self.assertFalse(sm._graceful_shutdown(mock_proc, "test", 0.1))

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_graceful_shutdown_exception(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.terminate.side_effect = OSError("no process")
        self.assertFalse(sm._graceful_shutdown(mock_proc, "test", 0.1))

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_force_shutdown_timeout(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 2)
        self.assertFalse(sm._force_shutdown(mock_proc, "test"))

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_force_shutdown_exception(self, _):
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.kill.side_effect = OSError("no process")
        self.assertFalse(sm._force_shutdown(mock_proc, "test"))


# ═══════════════════════════════════════════════════════════════════════════
#  get_web_ui_config
# ═══════════════════════════════════════════════════════════════════════════
class TestGetWebUIConfig(unittest.TestCase):
    def setUp(self):
        with service_manager._config_cache_lock:
            self._orig_cache = dict(service_manager._config_cache)
            service_manager._config_cache["config"] = None
            service_manager._config_cache["timestamp"] = 0

    def tearDown(self):
        with service_manager._config_cache_lock:
            service_manager._config_cache.update(self._orig_cache)

    @patch("service_manager.get_config")
    @patch("service_manager._ensure_config_change_callbacks_registered")
    def test_load_config_success(self, _, mock_get_cfg):
        mock_cfg = MagicMock()
        mock_cfg.get_section.side_effect = lambda sec: {
            "web_ui": {"host": "127.0.0.1", "port": 8080},
            "feedback": {},
            "network_security": {},
        }.get(sec, {})
        mock_get_cfg.return_value = mock_cfg

        config, timeout = service_manager.get_web_ui_config()
        self.assertIsInstance(config, WebUIConfig)
        self.assertEqual(config.port, 8080)

    @patch("service_manager.get_config")
    @patch("service_manager._ensure_config_change_callbacks_registered")
    def test_cache_hit(self, _, mock_get_cfg):
        mock_cfg = MagicMock()
        mock_cfg.get_section.side_effect = lambda sec: {
            "web_ui": {"port": 9090},
            "feedback": {},
            "network_security": {},
        }.get(sec, {})
        mock_get_cfg.return_value = mock_cfg

        cfg1, _ = service_manager.get_web_ui_config()
        cfg2, _ = service_manager.get_web_ui_config()
        self.assertEqual(cfg1.port, cfg2.port)
        self.assertEqual(mock_get_cfg.call_count, 1)

    @patch("service_manager.get_config", side_effect=ValueError("bad config"))
    @patch("service_manager._ensure_config_change_callbacks_registered")
    def test_value_error_raises(self, _, __):
        with self.assertRaises(ValueError):
            service_manager.get_web_ui_config()

    @patch("service_manager.get_config", side_effect=RuntimeError("unexpected"))
    @patch("service_manager._ensure_config_change_callbacks_registered")
    def test_generic_error_raises(self, _, __):
        with self.assertRaises(ValueError):
            service_manager.get_web_ui_config()


# ═══════════════════════════════════════════════════════════════════════════
#  create_http_session
# ═══════════════════════════════════════════════════════════════════════════
class TestCreateHttpSession(unittest.TestCase):
    def setUp(self):
        service_manager._sync_client = None
        service_manager._async_client = None

    def tearDown(self):
        if service_manager._sync_client and not service_manager._sync_client.is_closed:
            service_manager._sync_client.close()
        service_manager._sync_client = None
        service_manager._async_client = None

    def test_creates_session(self):
        cfg = _make_config()
        session = server.create_http_session(cfg)
        self.assertIsInstance(session, httpx.Client)

    def test_cache_reuse(self):
        cfg = _make_config()
        s1 = server.create_http_session(cfg)
        s2 = server.create_http_session(cfg)
        self.assertIs(s1, s2)

    def test_closed_client_recreated(self):
        cfg = _make_config()
        s1 = server.create_http_session(cfg)
        s1.close()
        s2 = server.create_http_session(cfg)
        self.assertIsNot(s1, s2)


# ═══════════════════════════════════════════════════════════════════════════
#  is_web_service_running
# ═══════════════════════════════════════════════════════════════════════════
class TestIsWebServiceRunning(unittest.TestCase):
    def test_invalid_port(self):
        self.assertFalse(server.is_web_service_running("localhost", 0))
        self.assertFalse(server.is_web_service_running("localhost", 70000))

    @patch(
        "service_manager.socket.getaddrinfo",
        side_effect=socket.gaierror("resolve fail"),
    )
    def test_dns_failure(self, _):
        self.assertFalse(server.is_web_service_running("bad.host", 8080))

    @patch("service_manager.socket.getaddrinfo")
    @patch("service_manager.socket.socket")
    def test_connection_success(self, mock_sock_cls, mock_getaddr):
        mock_getaddr.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8080))
        ]
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock_cls.return_value = mock_sock

        self.assertTrue(server.is_web_service_running("127.0.0.1", 8080))

    @patch("service_manager.socket.getaddrinfo")
    @patch("service_manager.socket.socket")
    def test_connection_refused(self, mock_sock_cls, mock_getaddr):
        mock_getaddr.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8080))
        ]
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 1
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock_cls.return_value = mock_sock

        self.assertFalse(server.is_web_service_running("127.0.0.1", 8080))

    @patch("service_manager.socket.getaddrinfo")
    @patch("service_manager.socket.socket")
    def test_socket_oserror_fallback(self, mock_sock_cls, mock_getaddr):
        mock_getaddr.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 8080, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8080)),
        ]
        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = [OSError("v6 fail"), 0]
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock_cls.return_value = mock_sock

        self.assertTrue(server.is_web_service_running("localhost", 8080))


# ═══════════════════════════════════════════════════════════════════════════
#  health_check_service
# ═══════════════════════════════════════════════════════════════════════════
class TestHealthCheckService(unittest.TestCase):
    @patch("service_manager.is_web_service_running", return_value=False)
    def test_port_not_listening(self, _):
        cfg = _make_config()
        self.assertFalse(server.health_check_service(cfg))

    @patch("service_manager.create_http_session")
    @patch("service_manager.is_web_service_running", return_value=True)
    def test_health_ok(self, _, mock_session_fn):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_session.get.return_value = mock_resp
        mock_session_fn.return_value = mock_session

        self.assertTrue(server.health_check_service(_make_config()))

    @patch("service_manager.create_http_session")
    @patch("service_manager.is_web_service_running", return_value=True)
    def test_health_non_200(self, _, mock_session_fn):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_session.get.return_value = mock_resp
        mock_session_fn.return_value = mock_session

        self.assertFalse(server.health_check_service(_make_config()))

    @patch("service_manager.create_http_session")
    @patch("service_manager.is_web_service_running", return_value=True)
    def test_request_exception(self, _, mock_session_fn):
        mock_session = MagicMock()
        mock_session.get.side_effect = httpx.ConnectError("fail")
        mock_session_fn.return_value = mock_session

        self.assertFalse(server.health_check_service(_make_config()))


# ═══════════════════════════════════════════════════════════════════════════
#  update_web_content
# ═══════════════════════════════════════════════════════════════════════════
class TestUpdateWebContent(unittest.TestCase):
    def _setup_session(
        self, status_code=200, json_data=None, text="", side_effect=None
    ):
        mock_session = MagicMock()
        if side_effect:
            mock_session.post.side_effect = side_effect
        else:
            mock_resp = MagicMock()
            mock_resp.status_code = status_code
            mock_resp.json.return_value = json_data or {"status": "success"}
            mock_resp.text = text
            mock_resp.headers = {}
            mock_session.post.return_value = mock_resp
        return mock_session

    @patch("service_manager.create_http_session")
    def test_success(self, mock_create):
        mock_create.return_value = self._setup_session(
            200, {"status": "success", "message": "ok"}
        )
        server.update_web_content("hello", ["A"], "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_200_invalid_json(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("bad json")
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_200_non_dict(self, mock_create):
        mock_create.return_value = self._setup_session(200, json_data="string")

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_200_status_not_success(self, mock_create):
        mock_create.return_value = self._setup_session(
            200, {"status": "error", "error": "bad_field", "message": "invalid"}
        )

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_400_json_response(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "missing_field",
            "message": "需要 prompt",
        }
        mock_resp.text = '{"error":"missing_field"}'
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ValidationError

        with self.assertRaises(ValidationError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_400_non_json(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "Bad Request"
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ValidationError

        with self.assertRaises(ValidationError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_429_rate_limited(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests"
        mock_resp.headers = {"Retry-After": "5"}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_404_endpoint_not_found(self, mock_create):
        mock_create.return_value = self._setup_session(404)

        from exceptions import ServiceUnavailableError

        with self.assertRaises(ServiceUnavailableError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_500_server_error(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_unexpected_status(self, mock_create):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 301
        mock_resp.text = "Moved"
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_timeout_exception(self, mock_create):
        mock_create.return_value = self._setup_session(
            side_effect=httpx.TimeoutException("timed out")
        )

        from exceptions import ServiceTimeoutError

        with self.assertRaises(ServiceTimeoutError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_connection_error(self, mock_create):
        mock_create.return_value = self._setup_session(
            side_effect=httpx.ConnectError("refused")
        )

        from exceptions import ServiceUnavailableError

        with self.assertRaises(ServiceUnavailableError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_request_exception(self, mock_create):
        mock_create.return_value = self._setup_session(
            side_effect=httpx.HTTPError("generic")
        )

        from exceptions import ServiceConnectionError

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())


# ═══════════════════════════════════════════════════════════════════════════
#  wait_for_task_completion (async)
# ═══════════════════════════════════════════════════════════════════════════
class TestWaitForTaskCompletionExtended(unittest.TestCase):
    def _mock_async_client(self, get_side_effect=None, get_return_value=None):
        """构建 mock AsyncClient，get 方法返回 awaitable。

        R23.1：``_sse_listener`` 也走 ``service_manager.get_async_client``，
        所以 mock client 必须显式让 ``stream(...)`` 抛异常表示"SSE 不可用"，
        否则 MagicMock 默认让 ``async with sc.stream(...)`` 走 happy path 然后
        触发 ``aiter_lines()`` AsyncMock 未 await 的 RuntimeWarning。SSE 阻断
        后 listener 在 finally 里 ``sse_connected.clear()``，``_poll_fallback``
        以 2s fast cadence 接管，本测试套用的就是 poll-only 路径。
        """
        from unittest.mock import AsyncMock

        mock_client = MagicMock()
        if get_side_effect is not None:
            mock_client.get = AsyncMock(side_effect=get_side_effect)
        else:
            mock_client.get = AsyncMock(return_value=get_return_value)
        mock_client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        return mock_client

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_task_completed(self, mock_get_client, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "task": {
                "status": "completed",
                "result": {"user_input": "done", "selected_options": []},
            },
        }

        mock_get_client.return_value = self._mock_async_client(
            get_return_value=mock_resp
        )
        result = asyncio.run(server.wait_for_task_completion("t1", timeout=5))
        self.assertEqual(result["user_input"], "done")

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_task_404_returns_resubmit(self, mock_get_client, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_get_client.return_value = self._mock_async_client(
            get_return_value=mock_resp
        )
        result = asyncio.run(server.wait_for_task_completion("t-gone", timeout=5))
        self.assertIn("text", result)

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_timeout_returns_resubmit(self, mock_get_client, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "task": {"status": "pending", "result": None},
        }

        mock_get_client.return_value = self._mock_async_client(
            get_return_value=mock_resp
        )
        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(server.wait_for_task_completion("t-slow", timeout=2))
            self.assertIn("text", result)

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_request_exception_continues(self, mock_get_client, mock_get_cfg):
        from unittest.mock import AsyncMock

        mock_get_cfg.return_value = (_make_config(), 120)
        call_count = {"n": 0}

        async def mock_get(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                raise httpx.ConnectError("fail")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "task": {
                    "status": "completed",
                    "result": {"user_input": "recovered"},
                },
            }
            return resp

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        # R23.1：阻 SSE 主循环（详见 _mock_async_client docstring）
        mock_client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        mock_get_client.return_value = mock_client
        result = asyncio.run(server.wait_for_task_completion("t-flaky", timeout=10))
        self.assertEqual(result.get("user_input"), "recovered")

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_non_200_continues(self, mock_get_client, mock_get_cfg):
        from unittest.mock import AsyncMock

        mock_get_cfg.return_value = (_make_config(), 120)
        call_count = {"n": 0}

        async def mock_get(*args, **kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            if call_count["n"] <= 1:
                resp.status_code = 500
            else:
                resp.status_code = 200
                resp.json.return_value = {
                    "success": True,
                    "task": {
                        "status": "completed",
                        "result": {"user_input": "ok"},
                    },
                }
            return resp

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        # R23.1：阻 SSE 主循环
        mock_client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        mock_get_client.return_value = mock_client
        result = asyncio.run(server.wait_for_task_completion("t-retry", timeout=10))
        self.assertEqual(result.get("user_input"), "ok")

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_invalid_json_continues(self, mock_get_client, mock_get_cfg):
        from unittest.mock import AsyncMock

        mock_get_cfg.return_value = (_make_config(), 120)
        call_count = {"n": 0}

        async def mock_get(*args, **kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count["n"] <= 1:
                resp.json.side_effect = ValueError("bad json")
            else:
                resp.json.return_value = {
                    "success": True,
                    "task": {"status": "completed", "result": {"user_input": "ok"}},
                }
            return resp

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        # R23.1：阻 SSE 主循环
        mock_client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        mock_get_client.return_value = mock_client
        result = asyncio.run(server.wait_for_task_completion("t-json", timeout=10))
        self.assertEqual(result.get("user_input"), "ok")

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_non_dict_response_continues(self, mock_get_client, mock_get_cfg):
        from unittest.mock import AsyncMock

        mock_get_cfg.return_value = (_make_config(), 120)
        call_count = {"n": 0}

        async def mock_get(*args, **kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count["n"] <= 1:
                resp.json.return_value = "string response"
            else:
                resp.json.return_value = {
                    "success": True,
                    "task": {"status": "completed", "result": {"user_input": "ok"}},
                }
            return resp

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        # R23.1：阻 SSE 主循环
        mock_client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        mock_get_client.return_value = mock_client
        result = asyncio.run(server.wait_for_task_completion("t-type", timeout=10))
        self.assertEqual(result.get("user_input"), "ok")


# ═══════════════════════════════════════════════════════════════════════════
#  R13·B1 Ghost-task cleanup contract
# ═══════════════════════════════════════════════════════════════════════════
class TestGhostTaskCleanupOnTimeout(unittest.TestCase):
    """``wait_for_task_completion`` 必须在 timeout / cancel 路径通知 web_ui
    清理 ``task_queue`` 中的 ghost task；正常完成路径必须**不**触发 close
    （会跟 ``/api/submit → complete_task`` 形成 race，且后台清理 GC 已经会
    在 10 秒后接手）。这条契约由本类锁住。

    历史 bug 详见 ``server_feedback._close_orphan_task_best_effort`` 的
    docstring：MCP 客户端 timeout 后重新 invoke 会让旧 task 一直占着 active
    槽位，前端展示错乱的 prompt，用户提交反馈被绑到旧 task_id，新 task
    永远 timeout，死循环。
    """

    def _make_async_client(self, get_side_effect):
        """构建 mock AsyncClient：``get`` 走业务 mock，``post`` 单独锁住调用次数。

        R23.1：``stream`` 必须显式 raise，让 ``_sse_listener`` 走 graceful
        degradation 退出，poll fallback 接管。否则 MagicMock 默认让 SSE 主循环
        进入 ``aiter_lines()`` 触发未 await 的 RuntimeWarning。详见
        ``TestWaitForTaskCompletionExtended._mock_async_client``。
        """
        from unittest.mock import AsyncMock

        client = MagicMock()
        client.get = AsyncMock(side_effect=get_side_effect)
        post_mock = AsyncMock()
        post_mock.return_value = MagicMock(status_code=200)
        client.post = post_mock
        client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        return client, post_mock

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_timeout_path_calls_close_endpoint(self, mock_get_client, mock_get_cfg):
        """timeout 路径必须 POST /api/tasks/<id>/close 一次。"""
        mock_get_cfg.return_value = (_make_config(), 120)

        async def always_pending(*_args, **_kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "task": {"status": "pending", "result": None},
            }
            return resp

        client, post_mock = self._make_async_client(always_pending)
        mock_get_client.return_value = client

        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(server.wait_for_task_completion("t-orphan", timeout=2))

        self.assertIn("text", result, "timeout 仍应返回 resubmit_response")
        self.assertGreaterEqual(
            post_mock.call_count,
            1,
            "timeout 路径必须至少调 close 一次（ghost-task cleanup）；"
            f"实际调用次数: {post_mock.call_count}",
        )
        called_url = post_mock.call_args[0][0]
        self.assertIn(
            "/api/tasks/t-orphan/close",
            called_url,
            f"close URL 错误：{called_url}",
        )

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_completed_path_does_not_call_close(self, mock_get_client, mock_get_cfg):
        """正常完成路径必须**不**调 close（避免和 complete_task race）。"""
        mock_get_cfg.return_value = (_make_config(), 120)

        async def already_done(*_args, **_kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "task": {
                    "status": "completed",
                    "result": {"user_input": "done", "selected_options": []},
                },
            }
            return resp

        client, post_mock = self._make_async_client(already_done)
        mock_get_client.return_value = client

        result = asyncio.run(server.wait_for_task_completion("t-done", timeout=5))

        self.assertEqual(result.get("user_input"), "done")
        self.assertEqual(
            post_mock.call_count,
            0,
            "完成路径绝不能调 close —— 会和 web_ui /api/submit 触发的 "
            "complete_task race，且后台 cleanup 线程 10s 后会自然 GC。"
            f"实际调用次数: {post_mock.call_count}",
        )

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_404_path_does_not_call_close(self, mock_get_client, mock_get_cfg):
        """404 路径：web_ui 已经把 task 清掉了，再 close 没意义且会 spam log。"""
        mock_get_cfg.return_value = (_make_config(), 120)

        async def gone(*_args, **_kwargs):
            return MagicMock(status_code=404)

        client, post_mock = self._make_async_client(gone)
        mock_get_client.return_value = client

        result = asyncio.run(server.wait_for_task_completion("t-gone", timeout=5))

        self.assertIn("text", result)
        # _fetch_result 在 404 时返回 resubmit_response（非 None），
        # _poll_fallback 把它写进 result_box → finally 跳过 close。
        self.assertEqual(
            post_mock.call_count,
            0,
            "404 路径 web_ui 已自清，再 close 是无谓 traffic + 404 spam。"
            f"实际调用次数: {post_mock.call_count}",
        )

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_close_endpoint_failure_does_not_propagate(
        self, mock_get_client, mock_get_cfg
    ):
        """close 内部抛异常时主路径仍正常返回 resubmit_response。"""
        from unittest.mock import AsyncMock

        mock_get_cfg.return_value = (_make_config(), 120)

        async def always_pending(*_args, **_kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "task": {"status": "pending", "result": None},
            }
            return resp

        client = MagicMock()
        client.get = AsyncMock(side_effect=always_pending)
        # close 内部抛 ConnectError —— 模拟 web_ui 已经下线
        client.post = AsyncMock(side_effect=httpx.ConnectError("web_ui down"))
        # R23.1：阻止 SSE 主循环进入 mock 默认 aiter_lines 路径
        client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        mock_get_client.return_value = client

        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(server.wait_for_task_completion("t-down", timeout=2))

        self.assertIn(
            "text",
            result,
            "close 失败也必须返回 resubmit_response，best-effort 不能阻塞主路径",
        )

    def test_close_orphan_helper_reraises_cancelled_error(self):
        """``CancelledError`` 必须 re-raise，不能被 best-effort except 吞掉。"""
        from unittest.mock import AsyncMock

        from server_feedback import _close_orphan_task_best_effort

        with (
            patch("service_manager.get_web_ui_config") as mock_cfg,
            patch("service_manager.get_async_client") as mock_client_factory,
        ):
            mock_cfg.return_value = (_make_config(), 120)
            client = MagicMock()
            client.post = AsyncMock(side_effect=asyncio.CancelledError())
            mock_client_factory.return_value = client

            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(
                    _close_orphan_task_best_effort("t-cancel", "127.0.0.1", 8080)
                )


# ═══════════════════════════════════════════════════════════════════════════
#  R17.4 — retry-before-close protects against SSE-completed + transient
#          fetch-failure ghost-close race
# ═══════════════════════════════════════════════════════════════════════════
class TestRetryFetchBeforeClose(unittest.TestCase):
    """``wait_for_task_completion`` 的 finally 必须在 ``_close_orphan_task_best_effort``
    之前 retry ``_fetch_result``——避免"SSE 报告 completed + 首次 fetch
    撞短暂网络抖动"导致 ``close`` 把已 completed 的 task（连同 user feedback）
    永久删掉的 race。

    历史 bug 推导：
        T0  user 提交反馈 → web_ui ``/api/submit`` → ``task_queue.complete_task``
            → status=COMPLETED + ``result`` 写入
        T1  SSE 推送 ``task_changed(new_status=completed)``
        T2  ``_sse_listener`` 收到 → 调 ``_fetch_result()`` → **撞短暂 503
            / connection error / DNS 抖动** → 返回 None
        T3  ``completion.set()`` → finally 执行
        T4  R17.4 之前：``result_box[0] is None`` → ``_close_orphan_task_best_effort``
            → ``POST /close`` → web_ui ``remove_task`` → COMPLETED task 连
            同 result 被立即删掉
        T5  最后一行 ``_fetch_result()`` retry → 404 → ``_make_resubmit_response``
            → AI 让用户重新提交

        用户白填一遍反馈，零日志告警（log 只看到 "ghost task cleanup"
        和 "resubmit"，看不出实际 result 在 T2 fetch 抖动时已存在）。

    本组测试用 mock 驱动 ``_fetch_result``：第 1 次返回 None（模拟抖动），
    第 2 次返回 completed result（模拟抖动恢复）。修复后必须：
        - retry 命中 result，``post`` (close) 调用次数为 0；
        - 最终返回值是 retry 拿到的 result，不是 ``_make_resubmit_response``。
    """

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_retry_recovers_result_skips_close(self, mock_get_client, mock_get_cfg):
        """SSE 检测到 completed + 首次 fetch 抖动 → retry 成功 → 跳过 close。"""
        from unittest.mock import AsyncMock

        mock_get_cfg.return_value = (_make_config(), 120)

        # 状态机：第 1 次 GET → 503（模拟抖动），后续 GET → completed
        call_log = {"get_count": 0}
        completed_result = {
            "user_input": "辛辛苦苦填的反馈",
            "selected_options": ["yes"],
        }

        async def stateful_get(*_args, **_kwargs):
            call_log["get_count"] += 1
            if call_log["get_count"] == 1:
                # 首次抖动：503——_fetch_result 在 except Exception 路径
                # 返回 None，正好复现"SSE 看到 completed + 本地 fetch 失败"
                resp = MagicMock()
                resp.status_code = 503
                resp.json.side_effect = ValueError("bad gateway")
                return resp
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "task": {"status": "completed", "result": completed_result},
            }
            return resp

        client = MagicMock()
        client.get = AsyncMock(side_effect=stateful_get)
        post_mock = AsyncMock()
        post_mock.return_value = MagicMock(status_code=200)
        client.post = post_mock
        # R23.1：阻 SSE 主循环，让 retry-before-close 路径独立可测
        client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        mock_get_client.return_value = client

        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(server.wait_for_task_completion("t-jitter", timeout=3))

        # 1) 最终拿到的是 retry 救回来的 result，不是 resubmit response
        self.assertEqual(
            result,
            completed_result,
            f"retry 必须把 result 救回来，实际：{result}",
        )

        # 2) close 一次都不应被调——因为 retry 成功后 result_box[0] 已填
        self.assertEqual(
            post_mock.call_count,
            0,
            "retry 救回 result 后绝对不能再 close（会把 completed task 真删了）；"
            f"实际 close 次数：{post_mock.call_count}",
        )

        # 3) GET 至少被调 2 次（一次抖动 + 至少一次 retry）
        self.assertGreaterEqual(
            call_log["get_count"],
            2,
            f"retry-before-close 必须确保至少 2 次 GET，实际：{call_log['get_count']}",
        )

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_retry_still_failing_falls_back_to_close(
        self, mock_get_client, mock_get_cfg
    ):
        """retry 也失败 → 走原 R13·B1 close 路径，行为完全等价于修复前。"""
        from unittest.mock import AsyncMock

        mock_get_cfg.return_value = (_make_config(), 120)

        async def always_pending(*_args, **_kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "task": {"status": "pending", "result": None},
            }
            return resp

        client = MagicMock()
        client.get = AsyncMock(side_effect=always_pending)
        post_mock = AsyncMock()
        post_mock.return_value = MagicMock(status_code=200)
        client.post = post_mock
        # R23.1：阻 SSE 主循环，让 poll-only fallback 路径独立可测
        client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        mock_get_client.return_value = client

        with patch("server_config.BACKEND_MIN", 1):
            result = asyncio.run(
                server.wait_for_task_completion("t-still-pending", timeout=2)
            )

        self.assertIn("text", result, "retry 仍失败时必须返回 resubmit response")
        # close 路径仍被走（retry 没救回 result）
        self.assertGreaterEqual(
            post_mock.call_count,
            1,
            "retry 失败时仍必须走 ghost-task close 路径以兼容 R13·B1",
        )

    @patch("service_manager.get_web_ui_config")
    @patch("service_manager.get_async_client")
    def test_retry_does_not_fire_when_result_already_present(
        self, mock_get_client, mock_get_cfg
    ):
        """正常路径：``_sse_listener`` 已经填了 ``result_box`` → finally 跳过 retry。

        这条防 retry 错误改写已成功拿到的 result（``result_box[0] = retry_result``
        在 None 检查内部，但要 lock 住未来重构不会把 retry 提到检查之外）。
        """
        from unittest.mock import AsyncMock

        mock_get_cfg.return_value = (_make_config(), 120)

        completed_result = {"user_input": "first", "selected_options": []}
        get_count = {"value": 0}

        async def already_done(*_args, **_kwargs):
            get_count["value"] += 1
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "task": {"status": "completed", "result": completed_result},
            }
            return resp

        client = MagicMock()
        client.get = AsyncMock(side_effect=already_done)
        post_mock = AsyncMock()
        client.post = post_mock
        # R23.1：阻 SSE 主循环，让 fast poll 完成路径独立可测
        client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))
        mock_get_client.return_value = client

        result = asyncio.run(server.wait_for_task_completion("t-done", timeout=5))

        self.assertEqual(result, completed_result)
        self.assertEqual(post_mock.call_count, 0, "完成路径不应触发 close（不变契约）")


# ═══════════════════════════════════════════════════════════════════════════
#  FeedbackServiceContext
# ═══════════════════════════════════════════════════════════════════════════
class TestFeedbackServiceContext(unittest.TestCase):
    @patch("service_manager.get_web_ui_config")
    def test_enter_success(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        result = ctx.__enter__()
        self.assertIs(result, ctx)
        self.assertIsNotNone(ctx.config)

    @patch("service_manager.get_web_ui_config", side_effect=ValueError("bad"))
    def test_enter_failure(self, _):
        ctx = server.FeedbackServiceContext()
        with self.assertRaises(ValueError):
            ctx.__enter__()

    @patch("service_manager.get_web_ui_config")
    def test_exit_normal(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        with patch.object(ctx.service_manager, "cleanup_all"):
            ctx.__exit__(None, None, None)

    @patch("service_manager.get_web_ui_config")
    def test_exit_with_exception(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        with patch.object(ctx.service_manager, "cleanup_all"):
            ctx.__exit__(RuntimeError, RuntimeError("boom"), None)

    @patch("service_manager.get_web_ui_config")
    def test_exit_with_keyboard_interrupt(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        with patch.object(ctx.service_manager, "cleanup_all"):
            ctx.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

    @patch("service_manager.get_web_ui_config")
    def test_exit_cleanup_error(self, mock_get_cfg):
        mock_get_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        with patch.object(
            ctx.service_manager, "cleanup_all", side_effect=RuntimeError("cleanup fail")
        ):
            ctx.__exit__(None, None, None)


# ═══════════════════════════════════════════════════════════════════════════
#  cleanup_services
# ═══════════════════════════════════════════════════════════════════════════
class TestCleanupServices(unittest.TestCase):
    def test_success(self):
        with patch("server.ServiceManager") as MockSM:
            mock_sm = MagicMock()
            MockSM.return_value = mock_sm
            server.cleanup_services(shutdown_notification_manager=True)
            mock_sm.cleanup_all.assert_called_once_with(
                shutdown_notification_manager=True
            )

    def test_exception_suppressed(self):
        with patch("server.ServiceManager") as MockSM:
            mock_sm = MagicMock()
            mock_sm.cleanup_all.side_effect = RuntimeError("fail")
            MockSM.return_value = mock_sm
            server.cleanup_services()


# ═══════════════════════════════════════════════════════════════════════════
#  main() — 基本重试循环
# ═══════════════════════════════════════════════════════════════════════════
class TestMain(unittest.TestCase):
    @patch("server.mcp")
    @patch("server.cleanup_services")
    def test_normal_exit(self, mock_cleanup, mock_mcp):
        mock_mcp.run.return_value = None
        server.main()
        mock_mcp.run.assert_called_once()

    @patch("server.mcp")
    @patch("server.cleanup_services")
    def test_keyboard_interrupt(self, mock_cleanup, mock_mcp):
        mock_mcp.run.side_effect = KeyboardInterrupt
        server.main()
        mock_cleanup.assert_called_once()

    @patch("server.sys.exit")
    @patch("server.time.sleep")
    @patch("server.mcp")
    @patch("server.cleanup_services")
    def test_retry_then_exit(self, mock_cleanup, mock_mcp, mock_sleep, mock_exit):
        mock_mcp.run.side_effect = RuntimeError("crash")
        server.main()
        self.assertEqual(mock_mcp.run.call_count, 3)
        mock_exit.assert_called_once_with(1)


# ═══════════════════════════════════════════════════════════════════════════
#  ServiceManager — 深层路径
# ═══════════════════════════════════════════════════════════════════════════
class TestServiceManagerDeep(unittest.TestCase):
    def setUp(self):
        server.ServiceManager._instance = None
        server.ServiceManager._lock = threading.Lock()

    def tearDown(self):
        server.ServiceManager._instance = None

    def test_register_cleanup_signal_valueerror(self):
        """非主线程场景：signal 注册抛出 ValueError 但不应崩溃"""
        sm = server.ServiceManager()
        sm._cleanup_registered = False
        with patch(
            "service_manager.signal.signal", side_effect=ValueError("not main thread")
        ):
            sm._register_cleanup()
        self.assertTrue(sm._cleanup_registered)

    def test_signal_handler_non_main_thread(self):
        """非主线程收到信号时不设置 _should_exit"""
        sm = server.ServiceManager()
        sm._should_exit = False
        non_main = threading.Thread(target=lambda: None)
        with (
            patch.object(sm, "cleanup_all"),
            patch("service_manager.threading.current_thread", return_value=non_main),
            patch("server.threading.main_thread", return_value=threading.main_thread()),
        ):
            sm._signal_handler(signal.SIGINT, None)
        self.assertFalse(sm._should_exit)

    def test_signal_handler_cleanup_error(self):
        """cleanup_all 失败不应让其原始异常逃逸；仍应走 KeyboardInterrupt 正常退出路径"""
        sm = server.ServiceManager()
        with patch.object(sm, "cleanup_all", side_effect=RuntimeError("cleanup boom")):
            with self.assertRaises(KeyboardInterrupt):
                sm._signal_handler(signal.SIGTERM, None)
            # 即使 cleanup 抛错，主线程分支仍把 _should_exit 置 True
            self.assertTrue(sm._should_exit)

    def test_signal_handler_sigterm_main_thread_raises_keyboardinterrupt(self):
        """R17.5: SIGTERM 在主线程必须 raise KeyboardInterrupt 让 mcp.run() 退出。

        反向锁：注册自定义 SIGTERM handler 后，Python 默认的 ``raise SystemExit``
        被吞掉。如果 handler 不主动 raise，cleanup 完成后 mcp.run() 的 stdio
        loop 会继续阻塞，进程变僵尸（监督程序发 SIGTERM 没反应）。这条
        测试锁住"必须显式抛出 KeyboardInterrupt"的不变量，未来谁删掉
        ``raise KeyboardInterrupt`` 这一行立即红线。
        """
        sm = server.ServiceManager()
        with patch.object(sm, "cleanup_all"):
            with self.assertRaises(KeyboardInterrupt) as cm:
                sm._signal_handler(signal.SIGTERM, None)
        self.assertIn("signal", str(cm.exception).lower())
        self.assertIn(str(int(signal.SIGTERM)), str(cm.exception))
        self.assertTrue(sm._should_exit)

    def test_signal_handler_sigint_main_thread_raises_keyboardinterrupt(self):
        """R17.5: SIGINT 在主线程必须 raise KeyboardInterrupt（保持与 Python 默认行为兼容）"""
        sm = server.ServiceManager()
        with patch.object(sm, "cleanup_all"):
            with self.assertRaises(KeyboardInterrupt) as cm:
                sm._signal_handler(signal.SIGINT, None)
        self.assertIn(str(int(signal.SIGINT)), str(cm.exception))
        self.assertTrue(sm._should_exit)

    def test_signal_handler_calls_cleanup_before_raising(self):
        """R17.5: cleanup_all 必须在 KeyboardInterrupt 抛出**之前**完成。

        反向锁：如果未来谁把 ``raise KeyboardInterrupt`` 移到 ``cleanup_all``
        之前，cleanup 永远不会跑，web_ui 子进程、ThreadPool、httpx client
        都会泄漏。本测试用调用顺序追踪锁住"先 cleanup 再 raise"。
        """
        sm = server.ServiceManager()
        order: list[str] = []

        def fake_cleanup(*args, **kwargs):
            del args, kwargs
            order.append("cleanup")

        with patch.object(sm, "cleanup_all", side_effect=fake_cleanup):
            try:
                sm._signal_handler(signal.SIGTERM, None)
            except KeyboardInterrupt:
                order.append("raise")
        self.assertEqual(order, ["cleanup", "raise"])

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_terminate_process_outer_exception(self, _):
        """terminate_process 内部 poll 抛出意外异常"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 700
        mock_proc.poll.side_effect = OSError("gone")
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("error", mock_proc, _make_config())
        result = sm.terminate_process("error")
        self.assertFalse(result)

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_cleanup_process_resources_close_exceptions(self, _):
        """stdin/stdout/stderr 的 close() 各自抛出异常不影响整体"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.close.side_effect = OSError("stdin fail")
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.close.side_effect = OSError("stdout fail")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.close.side_effect = OSError("stderr fail")
        sm._cleanup_process_resources("test", {"process": mock_proc})

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_cleanup_process_resources_outer_exception(self, _):
        """process_info["process"] 访问失败的情况"""
        sm = server.ServiceManager()
        sm._cleanup_process_resources("test", {})

    @patch("server.time.sleep")
    @patch(
        "service_manager.is_web_service_running", side_effect=[True, True, True, False]
    )
    def test_wait_for_port_release_eventually(self, mock_running, mock_sleep):
        sm = server.ServiceManager()
        sm._wait_for_port_release("127.0.0.1", 8080)
        self.assertTrue(mock_sleep.call_count >= 1)

    @patch("server.time.sleep")
    @patch("service_manager.is_web_service_running", return_value=True)
    def test_wait_for_port_release_timeout(self, mock_running, mock_sleep):
        """端口始终占用超时"""
        sm = server.ServiceManager()
        sm._wait_for_port_release("127.0.0.1", 8080, timeout=0.001)

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_cleanup_all_with_errors_and_remaining(self, _):
        """cleanup_all: terminate 失败 + 残留进程强制移除"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 800
        mock_proc.poll.side_effect = OSError("gone")
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("stuck", mock_proc, _make_config())

        with patch.object(sm, "terminate_process", return_value=False):
            sm.cleanup_all(shutdown_notification_manager=False)

    @patch("service_manager.NOTIFICATION_AVAILABLE", True)
    @patch("service_manager.notification_manager")
    @patch("service_manager.is_web_service_running", return_value=False)
    def test_cleanup_all_shutdown_notification_manager(self, _, mock_nm):
        sm = server.ServiceManager()
        sm.cleanup_all(shutdown_notification_manager=True)
        mock_nm.shutdown.assert_called_once()

    @patch("service_manager.NOTIFICATION_AVAILABLE", True)
    @patch("service_manager.notification_manager")
    @patch("service_manager.is_web_service_running", return_value=False)
    def test_cleanup_all_shutdown_notification_manager_failure(self, _, mock_nm):
        mock_nm.shutdown.side_effect = RuntimeError("shutdown fail")
        sm = server.ServiceManager()
        sm.cleanup_all(shutdown_notification_manager=True)

    @patch("service_manager.is_web_service_running", return_value=False)
    def test_cleanup_all_terminate_exception(self, _):
        """cleanup_all: terminate_process 抛出异常"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 801
        mock_proc.poll.return_value = 0
        mock_proc.stdin = None
        mock_proc.stdout = None
        mock_proc.stderr = None
        sm.register_process("explode", mock_proc, _make_config())

        with patch.object(sm, "terminate_process", side_effect=RuntimeError("boom")):
            sm.cleanup_all(shutdown_notification_manager=False)


# ═══════════════════════════════════════════════════════════════════════════
#  create_http_session — 旧客户端关闭后重建
# ═══════════════════════════════════════════════════════════════════════════
class TestCreateHttpSessionDeep(unittest.TestCase):
    def setUp(self):
        service_manager._sync_client = None

    def tearDown(self):
        if service_manager._sync_client and not service_manager._sync_client.is_closed:
            service_manager._sync_client.close()
        service_manager._sync_client = None

    def test_closed_client_recreated(self):
        """旧 client is_closed 后自动重建新 client"""
        cfg = _make_config()
        s1 = service_manager.create_http_session(cfg)
        s1.close()
        s2 = service_manager.create_http_session(cfg)
        self.assertIsNot(s1, s2)


# ═══════════════════════════════════════════════════════════════════════════
#  get_async_client
# ═══════════════════════════════════════════════════════════════════════════
class TestGetAsyncClient(unittest.TestCase):
    def setUp(self):
        service_manager._async_client = None

    def tearDown(self):
        service_manager._async_client = None

    def test_creates_async_client(self):
        cfg = _make_config()
        client = service_manager.get_async_client(cfg)
        self.assertIsInstance(client, httpx.AsyncClient)

    def test_cache_reuse(self):
        cfg = _make_config()
        c1 = service_manager.get_async_client(cfg)
        c2 = service_manager.get_async_client(cfg)
        self.assertIs(c1, c2)


# ═══════════════════════════════════════════════════════════════════════════
#  cleanup_services — httpx 客户端关闭
# ═══════════════════════════════════════════════════════════════════════════
class TestCleanupServicesHttpx(unittest.TestCase):
    @patch("service_manager.ServiceManager")
    def test_closes_sync_client(self, mock_sm_cls):
        mock_sm_cls.return_value.cleanup_all.return_value = None
        mock_client = MagicMock()
        mock_client.is_closed = False
        service_manager._sync_client = mock_client
        service_manager._async_client = MagicMock()

        server.cleanup_services()

        mock_client.close.assert_called_once()
        self.assertIsNone(service_manager._sync_client)
        self.assertIsNone(service_manager._async_client)

    @patch("service_manager.ServiceManager")
    def test_close_exception_swallowed(self, mock_sm_cls):
        mock_sm_cls.return_value.cleanup_all.return_value = None
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.close.side_effect = OSError("close fail")
        service_manager._sync_client = mock_client

        server.cleanup_services()

        self.assertIsNone(service_manager._sync_client)


# ═══════════════════════════════════════════════════════════════════════════
#  is_web_service_running — 外层异常
# ═══════════════════════════════════════════════════════════════════════════
class TestIsWebServiceRunningDeep(unittest.TestCase):
    @patch("service_manager.socket.getaddrinfo", side_effect=RuntimeError("unexpected"))
    def test_unexpected_exception_returns_false(self, _):
        self.assertFalse(server.is_web_service_running("localhost", 8080))


# ═══════════════════════════════════════════════════════════════════════════
#  health_check_service — 非 RequestException 的异常
# ═══════════════════════════════════════════════════════════════════════════
class TestHealthCheckServiceDeep(unittest.TestCase):
    @patch("service_manager.create_http_session")
    @patch("service_manager.is_web_service_running", return_value=True)
    def test_unexpected_exception(self, _, mock_session_fn):
        mock_session = MagicMock()
        mock_session.get.side_effect = RuntimeError("unexpected")
        mock_session_fn.return_value = mock_session
        self.assertFalse(server.health_check_service(_make_config()))


# ═══════════════════════════════════════════════════════════════════════════
#  update_web_content — 补充分支
# ═══════════════════════════════════════════════════════════════════════════
class TestUpdateWebContentDeep(unittest.TestCase):
    @patch("service_manager.create_http_session")
    def test_400_with_non_dict_json(self, mock_create):
        """400 响应 JSON 不是 dict"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = "just_a_string"
        mock_resp.text = "just_a_string"
        mock_resp.headers = {}
        mock_session.post.return_value = mock_resp
        mock_create.return_value = mock_session

        with self.assertRaises(ValidationError):
            server.update_web_content("hello", None, "t1", 120, _make_config())

    @patch("service_manager.create_http_session")
    def test_unexpected_exception(self, mock_create):
        """非网络/已知异常"""
        mock_session = MagicMock()
        mock_session.post.side_effect = TypeError("weird")
        mock_create.return_value = mock_session

        with self.assertRaises(ServiceConnectionError):
            server.update_web_content("hello", None, "t1", 120, _make_config())


# ═══════════════════════════════════════════════════════════════════════════
#  start_web_service
# ═══════════════════════════════════════════════════════════════════════════
class TestStartWebService(unittest.TestCase):
    def setUp(self):
        server.ServiceManager._instance = None
        server.ServiceManager._lock = threading.Lock()
        # 默认让 pre-flight 端口检查放行，避免本地开发机/CI 上恰好被
        # 占用的端口让本类原有的"测 health-check 路径 / Popen 路径 /
        # subprocess 错误路径"的测试因端口冲突提前 fail-fast 而误报。
        # 专门测 _is_port_available 行为的子测自己 stop() 这层 mock。
        self._port_patcher = patch(
            "service_manager._is_port_available", return_value=True
        )
        self._port_patcher.start()
        self.addCleanup(self._port_patcher.stop)

    def tearDown(self):
        server.ServiceManager._instance = None

    @patch("service_manager.health_check_service", return_value=True)
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_already_running_via_health_check(self, mock_hc):
        """服务已在运行，直接返回"""
        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)

    @patch("service_manager.health_check_service", return_value=False)
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_already_running_via_process_manager(self, mock_hc):
        """ServiceManager 中进程还在运行"""
        sm = server.ServiceManager()
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 900
        mock_proc.poll.return_value = None
        cfg = _make_config()
        service_name = f"web_ui_{cfg.host}_{cfg.port}"
        sm.register_process(service_name, mock_proc, cfg)

        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)

    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    @patch("service_manager.health_check_service", return_value=False)
    def test_web_ui_path_not_found(self, mock_hc):
        cfg = _make_config()
        with self.assertRaises(FileNotFoundError):
            server.start_web_service(cfg, Path("/nonexistent/dir"))

    @patch("server.time.sleep")
    @patch("service_manager.health_check_service")
    @patch("service_manager.subprocess.Popen")
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_success_start(self, mock_popen, mock_hc, mock_sleep):
        mock_proc = MagicMock()
        mock_proc.pid = 1000
        mock_popen.return_value = mock_proc
        mock_hc.side_effect = [False, False, True]

        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)
        mock_popen.assert_called_once()

    @patch("service_manager.health_check_service", return_value=False)
    @patch(
        "service_manager.subprocess.Popen",
        side_effect=FileNotFoundError("python not found"),
    )
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_popen_file_not_found(self, mock_popen, mock_hc):
        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceUnavailableError):
            server.start_web_service(cfg, script_dir)

    @patch("service_manager.health_check_service", return_value=False)
    @patch(
        "service_manager.subprocess.Popen", side_effect=PermissionError("access denied")
    )
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_popen_permission_error(self, mock_popen, mock_hc):
        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceUnavailableError):
            server.start_web_service(cfg, script_dir)

    @patch("service_manager.health_check_service")
    @patch("service_manager.subprocess.Popen", side_effect=OSError("disk full"))
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_popen_generic_error_service_already_running(self, mock_popen, mock_hc):
        """Popen 失败但 health_check 显示服务已在运行"""
        mock_hc.side_effect = [False, True]
        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)

    @patch("service_manager.health_check_service", return_value=False)
    @patch("service_manager.subprocess.Popen", side_effect=OSError("disk full"))
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_popen_generic_error_service_not_running(self, mock_popen, mock_hc):
        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceUnavailableError):
            server.start_web_service(cfg, script_dir)

    @patch("server.time.sleep")
    @patch("service_manager.health_check_service", return_value=False)
    @patch("service_manager.subprocess.Popen")
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_health_check_timeout_raises(self, mock_popen, mock_hc, mock_sleep):
        """健康检查始终失败，触发超时清理"""
        mock_proc = MagicMock()
        mock_proc.pid = 1001
        mock_popen.return_value = mock_proc

        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceTimeoutError):
            server.start_web_service(cfg, script_dir)

    @patch("server.time.sleep")
    @patch("service_manager.health_check_service", return_value=False)
    @patch("service_manager.subprocess.Popen")
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_health_check_timeout_cleanup_failure(
        self, mock_popen, mock_hc, mock_sleep
    ):
        """健康检查超时后 cleanup 也失败"""
        mock_proc = MagicMock()
        mock_proc.pid = 1002
        mock_popen.return_value = mock_proc

        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceTimeoutError):
            server.start_web_service(cfg, script_dir)

    @patch("server.time.sleep")
    @patch("service_manager.health_check_service")
    @patch("service_manager.subprocess.Popen")
    @patch("service_manager.initialize_notification_system")
    @patch("service_manager.notification_manager")
    @patch("service_manager.NOTIFICATION_AVAILABLE", True)
    def test_notification_init_success(
        self, mock_nm, mock_init_ns, mock_popen, mock_hc, mock_sleep
    ):
        mock_proc = MagicMock()
        mock_proc.pid = 1003
        mock_popen.return_value = mock_proc
        mock_hc.side_effect = [False, True]
        mock_nm.get_config.return_value = {}

        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)
        mock_init_ns.assert_called_once()

    @patch("server.time.sleep")
    @patch("service_manager.health_check_service")
    @patch("service_manager.subprocess.Popen")
    @patch(
        "service_manager.initialize_notification_system",
        side_effect=RuntimeError("init fail"),
    )
    @patch("service_manager.notification_manager")
    @patch("service_manager.NOTIFICATION_AVAILABLE", True)
    def test_notification_init_failure(
        self, mock_nm, mock_init_ns, mock_popen, mock_hc, mock_sleep
    ):
        """通知系统初始化失败不影响服务启动"""
        mock_proc = MagicMock()
        mock_proc.pid = 1004
        mock_popen.return_value = mock_proc
        mock_hc.side_effect = [False, True]
        mock_nm.get_config.return_value = {}

        cfg = _make_config()
        script_dir = _SERVER_DIR
        server.start_web_service(cfg, script_dir)


# ═══════════════════════════════════════════════════════════════════════════
#  R17.1 — _is_port_available pre-flight check for start_web_service
# ═══════════════════════════════════════════════════════════════════════════
class TestIsPortAvailable(unittest.TestCase):
    """直接验 ``_is_port_available`` 行为契约。

    why：
        ``start_web_service`` 在 R17.1 之前依赖 15s health-check loop 间接
        发现端口冲突，错误码模糊（``start_timeout``）。pre-flight check
        让端口冲突立刻 fail-fast 为 ``port_in_use``，本组测试锁住该函数
        的核心契约：可绑定→True，被占→False，权限不足→False。
    """

    def test_returns_true_for_unbound_high_port(self):
        """随机高端口（OS 分配）必然可绑定。"""
        from service_manager import _is_port_available

        # bind 到 0 让 OS 选一个可用端口，关闭后立刻测试该端口仍可
        # bind（SO_REUSEADDR 让 TIME_WAIT 不算占用）。
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]
        # s 关闭后，free_port 大概率仍可用
        self.assertTrue(_is_port_available("127.0.0.1", free_port))

    def test_returns_false_when_port_actually_bound(self):
        """端口被另一个 socket 持有时必须返回 False。"""
        from service_manager import _is_port_available

        # 故意持有一个端口模拟"另一个进程占着"
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 不设 SO_REUSEADDR，确保它真的"独占"该地址
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        try:
            occupied = holder.getsockname()[1]
            self.assertFalse(
                _is_port_available("127.0.0.1", occupied),
                f"端口 {occupied} 被 listen 占用时应返回 False",
            )
        finally:
            holder.close()

    def test_returns_false_for_privileged_port_when_unprivileged(self):
        """非 root 进程 bind 80 端口必然 EACCES，应当返回 False。

        skip：root 跑 CI 时 bind 80 可能成功——直接跳过避免误报。
        """
        import os

        from service_manager import _is_port_available

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("以 root 跑测试时低端口可绑定，无法验证 EACCES 路径")

        # 80 端口未被占用时也会因权限不足 raise OSError(EACCES)，
        # 函数应 swallow 并返回 False。
        result = _is_port_available("127.0.0.1", 80)
        self.assertFalse(result, "非 root 进程 bind 80 应返回 False")

    def test_returns_false_for_invalid_host(self):
        """无效 host 字面量（如不存在的网卡 IP）应返回 False 而非抛异常。"""
        from service_manager import _is_port_available

        # 192.0.2.0/24 是 RFC 5737 TEST-NET-1 文档保留段，本机一般
        # 不会有这个地址→bind 抛 EADDRNOTAVAIL，函数应 swallow。
        result = _is_port_available("192.0.2.1", 12345)
        self.assertFalse(result, "无效 host 上的 bind 应返回 False，而非抛 OSError")


class TestStartWebServicePortInUse(unittest.TestCase):
    """``start_web_service`` 在 pre-flight 命中端口冲突时的契约。

    锁定：
        1. health_check 失败 + 端口被占 → 立刻抛 ``port_in_use``，
           **不会**走到 subprocess.Popen
        2. 错误码必须是 ``port_in_use``，便于上层（CLI / Web UI）做
           精确文案 / 自动选端口
    """

    def setUp(self):
        server.ServiceManager._instance = None
        server.ServiceManager._lock = threading.Lock()

    def tearDown(self):
        server.ServiceManager._instance = None

    @patch("service_manager._is_port_available", return_value=False)
    @patch("service_manager.subprocess.Popen")
    @patch("service_manager.health_check_service", return_value=False)
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_port_in_use_raises_fast_without_popen(
        self, mock_hc, mock_popen, mock_port
    ):
        """端口被占时立刻抛 ServiceUnavailableError，subprocess 不应被调用。"""
        cfg = _make_config()
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceUnavailableError) as ctx:
            server.start_web_service(cfg, script_dir)

        # 错误码契约
        self.assertEqual(
            ctx.exception.code,
            "port_in_use",
            f"期望 code='port_in_use'，实际：{ctx.exception.code}",
        )
        # fail-fast 契约：subprocess.Popen 一次都不该被调
        mock_popen.assert_not_called()

    @patch("service_manager._is_port_available", return_value=False)
    @patch("service_manager.health_check_service", return_value=False)
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_port_in_use_message_mentions_host_and_port(self, mock_hc, mock_port):
        """异常消息应包含具体 host:port，方便用户定位。"""
        cfg = _make_config(host="127.0.0.1", port=18080)
        script_dir = _SERVER_DIR
        with self.assertRaises(ServiceUnavailableError) as ctx:
            server.start_web_service(cfg, script_dir)

        msg = str(ctx.exception)
        self.assertIn("127.0.0.1", msg, f"异常消息应含 host：{msg}")
        self.assertIn("18080", msg, f"异常消息应含 port：{msg}")

    @patch("service_manager._is_port_available", return_value=True)
    @patch("service_manager.health_check_service", return_value=True)
    @patch("service_manager.NOTIFICATION_AVAILABLE", False)
    def test_health_check_pass_skips_port_check(self, mock_hc, mock_port):
        """health_check 通过（说明是我们自己的服务）→ pre-flight 不应执行。

        语义：若 health_check 已识别出端口背后是本服务，pre-flight 端口
        bind（必失败，因为我们自己占着）会让 start_web_service 误报
        port_in_use。守住"health_check 是 short-circuit"这条契约。
        """
        cfg = _make_config()
        script_dir = _SERVER_DIR
        # 应当无异常返回，且 _is_port_available 不被调用
        server.start_web_service(cfg, script_dir)
        mock_port.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
#  ensure_web_ui_running (async)
# ═══════════════════════════════════════════════════════════════════════════
class TestEnsureWebUIRunningExtended(unittest.TestCase):
    @patch("service_manager.get_async_client")
    def test_already_running(self, mock_get_client):
        from unittest.mock import AsyncMock

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_client

        asyncio.run(server.ensure_web_ui_running(_make_config()))

    @patch("service_manager.start_web_service")
    @patch("service_manager.get_async_client")
    def test_health_fail_starts_service(self, mock_get_client, mock_start):
        from unittest.mock import AsyncMock

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("fail"))
        mock_get_client.return_value = mock_client

        async def _noop_sleep(_: float) -> None:
            pass

        with patch("service_manager.asyncio.sleep", side_effect=_noop_sleep):
            asyncio.run(server.ensure_web_ui_running(_make_config()))
        mock_start.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
#  launch_feedback_ui
# ═══════════════════════════════════════════════════════════════════════════
class TestLaunchFeedbackUIExtended(unittest.TestCase):
    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-1")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_success_flow(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        mock_arun.side_effect = _mock_arun_closing(
            None, {"user_input": "done", "selected_options": []}
        )

        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertEqual(result["user_input"], "done")

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-2")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_api_non_200_dict_json(self, mock_tid, mock_cfg, mock_arun):
        """API 返回非 200 + dict JSON"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "server down"}
        mock_resp.text = '{"error": "server down"}'

        mock_arun.side_effect = _mock_arun_closing(None)

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-3")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_api_non_200_non_dict_json(self, mock_tid, mock_cfg, mock_arun):
        """API 返回非 200 + 非 dict JSON"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = "string payload"
        mock_resp.text = '"string payload"'

        mock_arun.side_effect = _mock_arun_closing(None)

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-4")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_api_non_200_invalid_json(self, mock_tid, mock_cfg, mock_arun):
        """API 返回非 200 + 无效 JSON"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        mock_resp.text = "Internal Error"

        mock_arun.side_effect = _mock_arun_closing(None)

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-5")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_api_connection_error(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)
        mock_arun.side_effect = _mock_arun_closing(None)

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-6")
    @patch("server_feedback.notification_manager")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", True)
    def test_notification_send_success(self, mock_nm, mock_tid, mock_cfg, mock_arun):
        from notification_manager import NotificationType

        mock_cfg.return_value = (_make_config(), 120)
        mock_nm.send_notification.return_value = "event-1"
        mock_nm.refresh_config_from_file.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = _mock_arun_closing(None, {"user_input": "ok"})

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertEqual(result["user_input"], "ok")
        mock_nm.send_notification.assert_called_once()

        # 回归保护：MCP 主进程必须同时承担 Bark 推送
        # （否则"插件+MCP"场景会丢失 Bark 通知）
        call_kwargs = mock_nm.send_notification.call_args.kwargs
        types = call_kwargs.get("types") or []
        self.assertIn(NotificationType.SYSTEM, types)
        self.assertIn(NotificationType.SOUND, types)
        self.assertIn(NotificationType.BARK, types)

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-7")
    @patch("server_feedback.notification_manager")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", True)
    def test_notification_send_failure(self, mock_nm, mock_tid, mock_cfg, mock_arun):
        """通知发送失败不影响任务创建"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_nm.refresh_config_from_file.side_effect = RuntimeError("notify fail")

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = _mock_arun_closing(None, {"user_input": "ok"})

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertEqual(result["user_input"], "ok")

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-8")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_task_error_result(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = _mock_arun_closing(None, {"error": "timeout"})

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    def test_value_error(self):
        with self.assertRaises(ValidationError):
            server.launch_feedback_ui(123)  # ty: ignore[invalid-argument-type]

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-9")
    def test_file_not_found(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)
        mock_arun.side_effect = _mock_arun_closing(
            FileNotFoundError("web_ui.py"),
        )
        with self.assertRaises(ServiceUnavailableError):
            server.launch_feedback_ui("hello")

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-10")
    def test_generic_exception(self, mock_tid, mock_cfg, mock_arun):
        mock_cfg.return_value = (_make_config(), 120)
        mock_arun.side_effect = _mock_arun_closing(RuntimeError("unexpected"))
        with self.assertRaises(ServiceUnavailableError):
            server.launch_feedback_ui("hello")

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-11")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_timeout_ensures_minimum(self, mock_tid, mock_cfg, mock_arun):
        """timeout 小于 300 时会被提升到 300"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = _mock_arun_closing(None, {"user_input": "ok"})

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello", timeout=10)
        self.assertEqual(result["user_input"], "ok")

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-12")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_api_non_200_invalid_json_no_text(self, mock_tid, mock_cfg, mock_arun):
        """API 返回非 200 + 无效 JSON + response.text 读取失败"""
        mock_cfg.return_value = (_make_config(), 120)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        type(mock_resp).text = PropertyMock(side_effect=RuntimeError("text fail"))

        mock_arun.side_effect = _mock_arun_closing(None)

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertIn("error", result)

    @patch("server_feedback.asyncio.run")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="test-task-13")
    @patch("server_feedback.notification_manager")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", True)
    def test_notification_send_returns_none(
        self, mock_nm, mock_tid, mock_cfg, mock_arun
    ):
        """通知发送返回 None（通知系统已禁用）"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_nm.send_notification.return_value = None
        mock_nm.refresh_config_from_file.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_arun.side_effect = _mock_arun_closing(None, {"user_input": "ok"})

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("service_manager.get_sync_client", return_value=mock_client):
            result = server.launch_feedback_ui("hello")
        self.assertEqual(result["user_input"], "ok")


# ═══════════════════════════════════════════════════════════════════════════
#  interactive_feedback (async MCP tool)
# ═══════════════════════════════════════════════════════════════════════════
_interactive_feedback_fn = server.interactive_feedback


class TestInteractiveFeedback(unittest.TestCase):
    def _run(self, message: str, predefined_options=None):
        """调用底层 async 函数，显式传 predefined_options 避免 FieldInfo 默认值"""
        return asyncio.run(_interactive_feedback_fn(message, predefined_options))

    def _patch_async_post(self, *, return_value=None, side_effect=None):
        """返回 context manager：patch get_async_client 并配置 async post"""
        from unittest.mock import AsyncMock

        mock_client = MagicMock()
        if side_effect is not None:
            mock_client.post = AsyncMock(side_effect=side_effect)
        else:
            mock_client.post = AsyncMock(return_value=return_value)
        return patch("service_manager.get_async_client", return_value=mock_client)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-1")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_success_structured_response(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {
            "user_input": "hello",
            "selected_options": ["A"],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)
        self.assertTrue(any(isinstance(c, TextContent) for c in result))

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-2")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_success_text_only_result(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """wait_for_task_completion 返回 {"text": "..."} 降级格式"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"text": "请重新调用工具"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        self.assertIsInstance(result[0], TextContent)
        self.assertIn("请重新调用工具", result[0].text)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-3")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_success_legacy_format(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """旧格式：interactive_feedback 字段"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"interactive_feedback": "old response"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result[0], TextContent)
        self.assertIn("old response", result[0].text)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-4")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_success_fallback_dict(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """未知 dict 格式的兜底"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"unknown_key": "value"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result[0], TextContent)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-5")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_success_string_result(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """非 dict 字符串结果"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = "simple string"

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result[0], TextContent)

    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-6")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_add_task_non_200(self, mock_tid, mock_cfg, mock_ensure):
        """添加任务 API 返回非 200"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "server down"}
        mock_resp.text = "server error"

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-7")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_add_task_non_200_invalid_json_with_text(
        self, mock_tid, mock_cfg, mock_ensure
    ):
        """添加任务 API 返回非 200 + 无效 JSON + 有 text"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        mock_resp.text = "Internal Error"

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-8")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_add_task_connection_error(self, mock_tid, mock_cfg, mock_ensure):
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        with self._patch_async_post(side_effect=httpx.ConnectError("refused")):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-9")
    @patch("server_feedback.notification_manager")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", True)
    def test_notification_available_path(
        self, mock_nm, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """NOTIFICATION_AVAILABLE=True 时走通知分支"""
        from notification_manager import NotificationType

        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_nm.send_notification.return_value = "event-1"
        mock_nm.refresh_config_from_file.return_value = None
        mock_wait.return_value = {"user_input": "ok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

        # 回归保护：interactive_feedback 同样必须把 Bark 纳入 MCP 主推送
        mock_nm.send_notification.assert_called_once()
        call_kwargs = mock_nm.send_notification.call_args.kwargs
        types = call_kwargs.get("types") or []
        self.assertIn(NotificationType.SYSTEM, types)
        self.assertIn(NotificationType.SOUND, types)
        self.assertIn(NotificationType.BARK, types)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-10")
    @patch("server_feedback.notification_manager")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", True)
    def test_notification_failure(
        self, mock_nm, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """通知失败不影响任务"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_nm.refresh_config_from_file.side_effect = RuntimeError("fail")
        mock_wait.return_value = {"user_input": "ok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-11")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_task_error_returns_resubmit(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"error": "timeout"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("service_manager.ensure_web_ui_running", side_effect=RuntimeError("crash"))
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-12")
    def test_generic_exception_returns_resubmit(self, mock_tid, mock_cfg, mock_ensure):
        mock_cfg.return_value = (_make_config(), 120)
        result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-13")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_add_task_non_200_non_dict_json(self, mock_tid, mock_cfg, mock_ensure):
        """添加任务 API 返回非 200 + 非 dict JSON"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = "string payload"
        mock_resp.text = '"string payload"'

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-14")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_success_with_images(self, mock_tid, mock_cfg, mock_ensure, mock_wait):
        """含图片的结构化响应"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {
            "user_input": "see image",
            "selected_options": [],
            "images": [],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-15")
    @patch("server_feedback.notification_manager")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", True)
    def test_notification_send_returns_none(
        self, mock_nm, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """通知发送返回 None（通知系统已禁用但可用标志为 True）"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_nm.send_notification.return_value = None
        mock_nm.refresh_config_from_file.return_value = None
        mock_wait.return_value = {"user_input": "ok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-16")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_long_message_truncated_for_notification(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """消息超过 100 字符时截断"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"user_input": "ok"}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("A" * 200)
        self.assertIsInstance(result, list)

    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-17")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_add_task_non_200_invalid_json_text_fail(
        self, mock_tid, mock_cfg, mock_ensure
    ):
        """添加任务 API 返回非 200 + 无效 JSON + response.text 读取失败"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        type(mock_resp).text = PropertyMock(side_effect=RuntimeError("text fail"))

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)

    @patch("server_feedback.wait_for_task_completion")
    @patch("service_manager.ensure_web_ui_running")
    @patch("service_manager.get_web_ui_config")
    @patch("server_config._generate_task_id", return_value="if-task-18")
    @patch("server_feedback.NOTIFICATION_AVAILABLE", False)
    def test_fallback_dict_with_text_field(
        self, mock_tid, mock_cfg, mock_ensure, mock_wait
    ):
        """dict 有 text 字段但不只有 text — 走兜底路径"""
        mock_cfg.return_value = (_make_config(), 120)
        mock_ensure.return_value = None
        mock_wait.return_value = {"text": "fallback", "extra": True}

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with self._patch_async_post(return_value=mock_resp):
            result = self._run("test prompt")
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        self.assertIsInstance(result[0], TextContent)


# ═══════════════════════════════════════════════════════════════════════════
#  FeedbackServiceContext.launch_feedback_ui_method (line 1617)
# ═══════════════════════════════════════════════════════════════════════════
class TestFeedbackServiceContextMethod(unittest.TestCase):
    @patch("server_feedback.launch_feedback_ui", return_value={"user_input": "ok"})
    @patch("service_manager.get_web_ui_config")
    def test_launch_delegates(self, mock_cfg, mock_launch):
        mock_cfg.return_value = (_make_config(), 120)
        ctx = server.FeedbackServiceContext()
        ctx.__enter__()
        result = ctx.launch_feedback_ui("hello", ["A"], "t1", 300)
        self.assertEqual(result["user_input"], "ok")
        mock_launch.assert_called_once_with("hello", ["A"], "t1", 300)


if __name__ == "__main__":
    unittest.main()
