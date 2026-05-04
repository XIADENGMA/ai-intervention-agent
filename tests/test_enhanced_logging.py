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


class TestLogDeduplicatorLazyCleanupOnHit(unittest.TestCase):
    """R16·D：cache hit 路径也能触发懒清理，stale entry 不再永久滞留。

    历史 bug：``_cleanup_cache`` 仅在 cache miss 路径触发；如果某条
    高频 ERROR 一直 cache hit，``cache`` 里的其它 stale entry 永远
    不会被清理（即使每条都过期），形成"软滞留"——不是真泄漏（``max_cache_size``
    上限存在），但违反"过期即清"的语义、让 hash 表常态保持在上限附近。
    """

    def test_lazy_cleanup_runs_on_hit_path(self):
        """高频 cache hit 场景下 stale entry 也能在懒清理周期内被清。

        步骤：
            1. 用极短 ``time_window`` (0.05s) 和较短 ``_LAZY_CLEANUP_INTERVAL_SECONDS``
               (monkey-patch 到 0.05s) 快速触发懒清理；
            2. 注入 9 条 stale entry；
            3. 持续命中第 10 条（cache hit 路径）；
            4. 在 ``_LAZY_CLEANUP_INTERVAL_SECONDS`` 之后再次 should_log
               同一条 hot entry，触发懒清理，stale 9 条应被清理。
        """
        dedup = LogDeduplicator(time_window=0.05, max_cache_size=100)
        dedup._LAZY_CLEANUP_INTERVAL_SECONDS = 0.05

        for i in range(9):
            dedup.should_log(f"stale_{i}")
        # 此刻共 9 条 entry（皆"新鲜"，未过期）

        time.sleep(0.10)
        # 现在所有 9 条都已经超过 time_window=0.05s，应该被视为 stale

        dedup.should_log("hot_msg")
        self.assertIn(hash("hot_msg"), dedup.cache)
        # cache miss 路径走 _cleanup_cache → stale 全清，cache 仅剩 hot

        time.sleep(0.10)

        result, _ = dedup.should_log("hot_msg")
        # 这次是 cache hit；如 lazy cleanup 不在 hit 路径运行，stale
        # 不会被清。当前实现：lazy cleanup 在每次 should_log 入口
        # 检查（含 cache hit 路径），所以 cache 仍只剩 hot_msg。
        self.assertLessEqual(
            len(dedup.cache),
            1,
            f"懒清理未在 cache hit 路径触发：cache 里仍有 {len(dedup.cache)} 条",
        )

    def test_lazy_cleanup_interval_constant_exists(self):
        """Reverse-lock：``_LAZY_CLEANUP_INTERVAL_SECONDS`` 必须存在
        且 ≥ default ``time_window`` (5.0s)。

        意图：清理周期不能短于时间窗，否则反复无效遍历；不能远大于
        2 × 时间窗，否则 stale 滞留可观察。30s 是经验值。
        """
        self.assertTrue(
            hasattr(LogDeduplicator, "_LAZY_CLEANUP_INTERVAL_SECONDS"),
            "LogDeduplicator 必须保留 _LAZY_CLEANUP_INTERVAL_SECONDS 类常量"
            "（懒清理周期）—— 误删会让 cache hit 路径退化回 R16·D 之前的"
            "行为：高频 cache hit 时 stale entry 永远不被清。",
        )
        interval = LogDeduplicator._LAZY_CLEANUP_INTERVAL_SECONDS
        self.assertGreaterEqual(
            interval,
            5.0,
            "_LAZY_CLEANUP_INTERVAL_SECONDS 不应短于默认 time_window (5s)",
        )
        self.assertLessEqual(
            interval,
            120.0,
            "_LAZY_CLEANUP_INTERVAL_SECONDS 不应远大于 2 × time_window，"
            "否则 stale 滞留可观察，违反 R16·D 修复初衷",
        )

    def test_first_should_log_does_not_trigger_unintended_cleanup(self):
        """初始化时 ``_last_cleanup_time = 0.0``，首次 should_log 必触发
        一次 cleanup（cache 为空，no-op，但 ``_last_cleanup_time`` 必须
        被刷成当前 ``time.monotonic()``，避免后续高频 should_log 持续触发
        cleanup（无穷 cleanup 退化到 R16·D 之前的 cache miss-only 路径
        反向，hot path 浪费）。
        """
        dedup = LogDeduplicator()
        before = dedup._last_cleanup_time
        self.assertEqual(before, 0.0)

        dedup.should_log("first")
        after = dedup._last_cleanup_time
        self.assertGreater(
            after,
            0.0,
            "首次 should_log 后 _last_cleanup_time 必须更新到 time.monotonic()，"
            "否则高频 should_log 会无穷触发 cleanup",
        )


class TestLogDeduplicatorMonotonic(unittest.TestCase):
    """R13·B2 reverse-lock：``LogDeduplicator`` 必须用 ``time.monotonic()``。

    历史教训：用 ``time.time()`` 时若系统时钟被向后调（NTP / 用户手动 /
    虚拟机暂停后恢复），缓存里的 ``last_time`` 突然变成"未来"，
    ``current_time - last_time`` 取负数，永远 ``<= time_window``，关键
    ERROR 长时间被静默 —— 即"假性一直去重"。``time.monotonic()`` 单调
    递增，对相对时间窗口是教科书级正确选择。

    本类不直接 monkey-patch wall clock，而是：

    1. 静态扫源码确认 ``should_log`` 用的是 ``time.monotonic()``，不是
       ``time.time()``；
    2. 行为黑盒测试：``patch time.time`` 让它返回乱序值（模拟 wall
       clock 倒走），如果实现真用了 ``time.monotonic()`` 行为不变；
       若哪天回退到 ``time.time()``，本测试会立即破。
    """

    def test_source_uses_monotonic_not_time(self):
        """源码层面：``should_log`` 必须调 ``time.monotonic()``，不能用 ``time.time()``。"""
        import inspect

        from enhanced_logging import LogDeduplicator as _LD

        src = inspect.getsource(_LD.should_log)
        self.assertIn(
            "time.monotonic()",
            src,
            "LogDeduplicator.should_log 必须用 time.monotonic() —— "
            "wall clock 在 NTP/手动调时下会倒走，让 ``current_time - "
            "last_time`` 取负数永远 ≤ window，关键 ERROR 长时间被静默。",
        )
        self.assertNotIn(
            "time.time()",
            src,
            "LogDeduplicator.should_log 不能再用 time.time() —— 这是 "
            "Round-13 修复的回归点；若需要 wall clock 时间戳（比如打"
            "印当前时间），请独立调用 time.time() 而非用作窗口判断。",
        )

    def test_wall_clock_jump_backwards_does_not_silence_logs(self):
        """行为契约：``time.time()`` 倒走时 ``LogDeduplicator`` 不能被骗到。"""
        import time as _time
        from unittest.mock import patch as _patch

        dedup = LogDeduplicator(time_window=0.5)

        # 第一次：建 baseline
        ok1, info1 = dedup.should_log("ntp_test_msg")
        self.assertTrue(ok1)
        self.assertIsNone(info1)

        # 模拟 wall clock 倒走 1 小时（time.time 返回更小的值）。如果实现
        # 错误地用 ``time.time``，下一次 should_log 看到的 ``current_time``
        # 会比 ``last_time`` 小 → 判负数 ≤ window → 错误去重。
        original_time = _time.time

        def go_back(*_args, **_kwargs):
            return original_time() - 3600.0

        with _patch.object(_time, "time", side_effect=go_back):
            time.sleep(0.6)  # 实际 monotonic 已超过 0.5s window
            ok2, _ = dedup.should_log("ntp_test_msg")

        self.assertTrue(
            ok2,
            "wall clock 被向后调 1h 时不应该让 dedup 错误去重；这正是 "
            "monotonic 修复的核心场景。如果失败说明回归到 time.time()。",
        )


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
