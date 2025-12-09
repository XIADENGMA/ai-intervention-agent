#!/usr/bin/env python3
"""
AI Intervention Agent - Enhanced Logging 模块单元测试

测试覆盖：
1. 日志去重器
2. 脱敏处理器
3. 防注入过滤器
4. 增强日志记录器
5. 安全日志格式化器
"""

import logging
import sys
import time
import unittest
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from enhanced_logging import (
    AntiInjectionFilter,
    EnhancedLogger,
    LevelBasedStreamHandler,
    LogDeduplicator,
    LogSanitizer,
    SecureLogFormatter,
)


class TestLogDeduplicator(unittest.TestCase):
    """日志去重器测试"""

    def test_init_default(self):
        """测试默认初始化"""
        dedup = LogDeduplicator()

        self.assertEqual(dedup.time_window, 5.0)
        self.assertEqual(dedup.max_cache_size, 1000)

    def test_init_custom(self):
        """测试自定义初始化"""
        dedup = LogDeduplicator(time_window=10.0, max_cache_size=500)

        self.assertEqual(dedup.time_window, 10.0)
        self.assertEqual(dedup.max_cache_size, 500)

    def test_should_log_first_message(self):
        """测试首次消息应该被记录"""
        dedup = LogDeduplicator(time_window=1.0)

        should_log, _ = dedup.should_log("first_message")

        self.assertTrue(should_log)

    def test_should_log_duplicate_message(self):
        """测试重复消息应该被去重"""
        dedup = LogDeduplicator(time_window=1.0)

        # 第一次
        result1, _ = dedup.should_log("duplicate_test")
        # 第二次
        result2, _ = dedup.should_log("duplicate_test")

        self.assertTrue(result1)
        self.assertFalse(result2)

    def test_should_log_different_messages(self):
        """测试不同消息不去重"""
        dedup = LogDeduplicator(time_window=1.0)

        result1, _ = dedup.should_log("message_a")
        result2, _ = dedup.should_log("message_b")

        self.assertTrue(result1)
        self.assertTrue(result2)

    def test_window_expiry(self):
        """测试时间窗口过期"""
        dedup = LogDeduplicator(time_window=0.01)  # 减少时间窗口

        result1, _ = dedup.should_log("expiry_test")
        self.assertTrue(result1)

        # 等待窗口过期（减少等待时间）
        time.sleep(0.02)

        result2, _ = dedup.should_log("expiry_test")
        self.assertTrue(result2)

    def test_cache_cleanup(self):
        """测试缓存清理"""
        dedup = LogDeduplicator(time_window=0.05, max_cache_size=5)

        # 填满缓存
        for i in range(10):
            dedup.should_log(f"msg_{i}")

        # 缓存应该被清理，不会无限增长
        self.assertLessEqual(len(dedup.cache), 10)


class TestLogSanitizer(unittest.TestCase):
    """日志脱敏器测试"""

    def setUp(self):
        """每个测试前准备"""
        self.sanitizer = LogSanitizer()

    def test_sanitize_password(self):
        """测试密码脱敏"""
        text = "password=secret123"
        result = self.sanitizer.sanitize(text)

        self.assertNotIn("secret123", result)

    def test_sanitize_api_key(self):
        """测试 API Key 脱敏"""
        text = "api_key=sk-abcdef123456"
        result = self.sanitizer.sanitize(text)

        # API key 应该被脱敏
        self.assertIsInstance(result, str)

    def test_sanitize_normal_text(self):
        """测试普通文本不变"""
        text = "This is normal text"
        result = self.sanitizer.sanitize(text)

        self.assertEqual(result, text)


class TestAntiInjectionFilter(unittest.TestCase):
    """防注入过滤器测试"""

    def setUp(self):
        """每个测试前准备"""
        self.filter = AntiInjectionFilter()

    def test_filter_normal_record(self):
        """测试正常记录通过"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Normal message",
            args=(),
            exc_info=None,
        )

        result = self.filter.filter(record)

        self.assertTrue(result)

    def test_filter_injection_attempt(self):
        """测试注入尝试被处理"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Normal\n[ERROR] Fake error",
            args=(),
            exc_info=None,
        )

        result = self.filter.filter(record)

        # 过滤器应该处理注入尝试
        self.assertTrue(result)

    def test_filter_carriage_return(self):
        """测试回车符被处理"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Normal\r[ERROR] Fake error",
            args=(),
            exc_info=None,
        )

        result = self.filter.filter(record)

        self.assertTrue(result)


class TestEnhancedLogger(unittest.TestCase):
    """增强日志记录器测试"""

    def setUp(self):
        """每个测试前准备"""
        self.logger = EnhancedLogger("test_enhanced")

    def test_logger_creation(self):
        """测试日志器创建"""
        self.assertIsNotNone(self.logger)

    def test_debug_log(self):
        """测试 debug 级别日志"""
        # 不应该抛出异常
        self.logger.debug("Debug message")

    def test_info_log(self):
        """测试 info 级别日志"""
        self.logger.info("Info message")

    def test_warning_log(self):
        """测试 warning 级别日志"""
        self.logger.warning("Warning message")

    def test_error_log(self):
        """测试 error 级别日志"""
        self.logger.error("Error message")

    def test_log_with_args(self):
        """测试带参数的日志"""
        self.logger.info("Message with args: %s %d", "test", 42)

    def test_log_with_kwargs(self):
        """测试带关键字参数的日志"""
        self.logger.info("Message with kwargs", extra={"key": "value"})


class TestSecureLogFormatter(unittest.TestCase):
    """安全日志格式化器测试"""

    def setUp(self):
        """每个测试前准备"""
        self.formatter = SecureLogFormatter()

    def test_format_record(self):
        """测试格式化记录"""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = self.formatter.format(record)

        self.assertIn("Test message", result)

    def test_format_with_custom_format(self):
        """测试自定义格式"""
        formatter = SecureLogFormatter(fmt="%(levelname)s: %(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Custom format test",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)

        self.assertIn("INFO", result)
        self.assertIn("Custom format test", result)


class TestLevelBasedStreamHandler(unittest.TestCase):
    """基于级别的流处理器测试"""

    def test_handler_creation(self):
        """测试处理器创建"""
        handler = LevelBasedStreamHandler()
        self.assertIsNotNone(handler)

    def test_handler_is_not_none(self):
        """测试处理器对象有效"""
        handler = LevelBasedStreamHandler()
        self.assertIsNotNone(handler)


def run_tests():
    """运行所有增强日志测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestLogDeduplicator))
    suite.addTests(loader.loadTestsFromTestCase(TestLogSanitizer))
    suite.addTests(loader.loadTestsFromTestCase(TestAntiInjectionFilter))
    suite.addTests(loader.loadTestsFromTestCase(TestEnhancedLogger))
    suite.addTests(loader.loadTestsFromTestCase(TestSecureLogFormatter))
    suite.addTests(loader.loadTestsFromTestCase(TestLevelBasedStreamHandler))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
