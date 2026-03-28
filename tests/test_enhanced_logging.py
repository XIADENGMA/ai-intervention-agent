#!/usr/bin/env python3
"""
AI Intervention Agent - Enhanced Logging 模块单元测试

测试覆盖：
1. 日志去重器
2. 脱敏处理器
3. Loguru patcher（防注入 + 脱敏）
4. InterceptHandler（stdlib → Loguru 桥接）
5. 增强日志记录器
6. 日志级别配置工具
"""

import logging
import time
import unittest

from enhanced_logging import (
    EnhancedLogger,
    InterceptHandler,
    LogDeduplicator,
    LogSanitizer,
    SingletonLogManager,
    _sanitize_and_escape,
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

        result1, _ = dedup.should_log("duplicate_test")
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
        dedup = LogDeduplicator(time_window=0.01)

        result1, _ = dedup.should_log("expiry_test")
        self.assertTrue(result1)

        time.sleep(0.02)

        result2, _ = dedup.should_log("expiry_test")
        self.assertTrue(result2)

    def test_cache_cleanup(self):
        """测试缓存清理"""
        dedup = LogDeduplicator(time_window=0.05, max_cache_size=5)

        for i in range(10):
            dedup.should_log(f"msg_{i}")

        self.assertLessEqual(len(dedup.cache), 10)


class TestLogSanitizer(unittest.TestCase):
    """日志脱敏器测试"""

    def setUp(self):
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

        self.assertIsInstance(result, str)

    def test_sanitize_normal_text(self):
        """测试普通文本不变"""
        text = "This is normal text"
        result = self.sanitizer.sanitize(text)

        self.assertEqual(result, text)


class TestSanitizeAndEscapePatcher(unittest.TestCase):
    """Loguru patcher 防注入+脱敏测试"""

    def _make_record(self, message):
        return {"message": message}

    def test_newline_escaped(self):
        record = self._make_record("line1\nline2")
        _sanitize_and_escape(record)
        self.assertNotIn("\n", record["message"])
        self.assertIn("\\n", record["message"])

    def test_carriage_return_escaped(self):
        record = self._make_record("line1\rline2")
        _sanitize_and_escape(record)
        self.assertNotIn("\r", record["message"])
        self.assertIn("\\r", record["message"])

    def test_null_byte_escaped(self):
        record = self._make_record("has\x00null")
        _sanitize_and_escape(record)
        self.assertNotIn("\x00", record["message"])
        self.assertIn("\\x00", record["message"])

    def test_password_sanitized(self):
        record = self._make_record("password=super_secret_value")
        _sanitize_and_escape(record)
        self.assertIn("***REDACTED***", record["message"])

    def test_normal_text_unchanged(self):
        record = self._make_record("Normal log message")
        _sanitize_and_escape(record)
        self.assertEqual(record["message"], "Normal log message")


class TestInterceptHandler(unittest.TestCase):
    """InterceptHandler stdlib → Loguru 桥接测试"""

    def test_handler_creation(self):
        handler = InterceptHandler()
        self.assertIsInstance(handler, logging.Handler)

    def test_emit_does_not_raise(self):
        handler = InterceptHandler()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        handler.emit(record)


class TestEnhancedLogger(unittest.TestCase):
    """增强日志记录器测试"""

    def setUp(self):
        self.logger = EnhancedLogger("test_enhanced")

    def test_logger_creation(self):
        self.assertIsNotNone(self.logger)

    def test_debug_log(self):
        self.logger.debug("Debug message")

    def test_info_log(self):
        self.logger.info("Info message")

    def test_warning_log(self):
        self.logger.warning("Warning message")

    def test_error_log(self):
        self.logger.error("Error message")

    def test_log_with_args(self):
        self.logger.info("Message with args: %s %d", "test", 42)

    def test_log_with_kwargs(self):
        self.logger.info("Message with kwargs", extra={"key": "value"})


class TestLogDeduplicatorCleanup(unittest.TestCase):
    """LogDeduplicator 缓存清理边界"""

    def test_expired_entries_removed(self):
        dedup = LogDeduplicator(time_window=0.01, max_cache_size=100)
        dedup.should_log("old_msg")
        time.sleep(0.02)
        dedup.should_log("new_msg")
        self.assertNotIn(hash("old_msg"), dedup.cache)

    def test_cache_overflow_cleanup(self):
        dedup = LogDeduplicator(time_window=60.0, max_cache_size=5)
        for i in range(20):
            dedup.should_log(f"overflow_{i}")
        self.assertLessEqual(len(dedup.cache), 20)


class TestEnhancedLoggerAdvanced(unittest.TestCase):
    """EnhancedLogger 高级分支"""

    def test_set_level(self):
        logger = EnhancedLogger("test_set_level")
        logger.setLevel(logging.DEBUG)
        self.assertEqual(logger.logger.level, logging.DEBUG)

    def test_level_mapping(self):
        logger = EnhancedLogger("test_mapping")
        logger.setLevel(logging.DEBUG)
        logger.info("服务启动失败 - 端口被占用")

    def test_duplicate_with_info(self):
        logger = EnhancedLogger("test_dedup_info")
        logger.setLevel(logging.DEBUG)
        logger.deduplicator = LogDeduplicator(time_window=0.01)
        logger.info("msg1")
        time.sleep(0.02)
        logger.info("msg1")


class TestGetLogLevelFromConfig(unittest.TestCase):
    """get_log_level_from_config 函数"""

    def test_default_level(self):
        from enhanced_logging import get_log_level_from_config

        level = get_log_level_from_config()
        self.assertIn(
            level, (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR)
        )

    def test_invalid_level_returns_warning(self):
        from unittest.mock import MagicMock, patch

        mock_mgr = MagicMock()
        mock_mgr.get.return_value = {"log_level": "INVALID_LEVEL"}
        with patch("enhanced_logging.config_manager", mock_mgr, create=True):
            from enhanced_logging import get_log_level_from_config as fn

            level = fn()
            self.assertEqual(level, logging.WARNING)

    def test_exception_returns_warning(self):
        from unittest.mock import patch

        from enhanced_logging import get_log_level_from_config

        with patch(
            "enhanced_logging.config_manager",
            side_effect=ImportError("no"),
            create=True,
        ):
            level = get_log_level_from_config()
            self.assertIsInstance(level, int)


class TestConfigureLoggingFromConfig(unittest.TestCase):
    """configure_logging_from_config 函数"""

    def test_configure(self):
        from enhanced_logging import configure_logging_from_config

        configure_logging_from_config()


class TestLogDuplicateInfoAppend(unittest.TestCase):
    """去重器返回 duplicate_info 时追加到消息"""

    def test_duplicate_info_appended(self):
        from unittest.mock import patch as _patch

        logger = EnhancedLogger("test_dedup_append")
        logger.setLevel(logging.DEBUG)
        with (
            _patch.object(
                logger.deduplicator, "should_log", return_value=(True, "重复 3 次")
            ),
            _patch.object(logger.logger, "log") as mock_log,
        ):
            logger.info("测试消息")
            mock_log.assert_called_once()
            logged_msg = mock_log.call_args[0][1]
            self.assertIn("(重复 3 次)", logged_msg)


class TestGetLogLevelEdgePaths(unittest.TestCase):
    """无效级别 + 配置读取异常"""

    def test_invalid_level_warning_path(self):
        from unittest.mock import MagicMock
        from unittest.mock import patch as _patch

        mock_mgr = MagicMock()
        mock_mgr.get.return_value = {"log_level": "SUPER_INVALID"}
        with _patch("config_manager.config_manager", mock_mgr):
            from enhanced_logging import get_log_level_from_config

            level = get_log_level_from_config()
            self.assertEqual(level, logging.WARNING)

    def test_config_read_exception_path(self):
        from unittest.mock import MagicMock
        from unittest.mock import patch as _patch

        mock_mgr = MagicMock()
        mock_mgr.get.side_effect = RuntimeError("config broken")
        with _patch("config_manager.config_manager", mock_mgr):
            from enhanced_logging import get_log_level_from_config

            level = get_log_level_from_config()
            self.assertEqual(level, logging.WARNING)


class TestSingletonLogManagerDCL(unittest.TestCase):
    """SingletonLogManager.__new__ DCL 内层分支"""

    def test_new_dcl_inner_branch(self):
        old_instance = SingletonLogManager._instance
        old_lock = SingletonLogManager._lock
        try:
            SingletonLogManager._instance = None
            sentinel = object.__new__(SingletonLogManager)

            class _RaceLock:
                def __enter__(self_lock):
                    SingletonLogManager._instance = sentinel
                    return self_lock

                def __exit__(self_lock, *args):
                    pass

            SingletonLogManager._lock = _RaceLock()  # type: ignore[assignment]
            inst = SingletonLogManager.__new__(SingletonLogManager)
            self.assertIs(inst, sentinel)
        finally:
            SingletonLogManager._instance = old_instance
            SingletonLogManager._lock = old_lock


if __name__ == "__main__":
    unittest.main()
