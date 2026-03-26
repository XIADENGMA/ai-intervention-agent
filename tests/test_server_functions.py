#!/usr/bin/env python3
"""
AI Intervention Agent - Server 函数测试

针对 server.py 中各种函数的单元测试
"""

import sys
import unittest
from pathlib import Path
from typing import Any, cast

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


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


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
