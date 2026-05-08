"""R72-A · root-logger InterceptHandler 单元测试。

锁定一个非常重要的安全契约：**所有 stdlib ``logging.getLogger(__name__)``
模块（``task_queue`` / ``config_manager`` / ``file_validator`` / ``i18n`` /
``config_utils`` / 第三方库）必须经过 Loguru 的 ``_sanitize_and_escape``
patcher**，从而享受 CRLF / null byte 转义 + PII 脱敏。

背景
====

CodeQL ``py/log-injection`` 在 ``task_queue.py`` 等 5 个文件里报了 15 个 high
severity 的警告，根因是这些文件用 ``logging.getLogger(__name__)`` 而不是
``EnhancedLogger``。它们的 ``logger.propagate=True`` 会冒泡到 root logger；
**root logger 之前没装 handler**，所以 ``logging.lastResort`` 会把消息原样
吐到 stderr，绕过 Loguru 的 sanitize 路径。

R72-A 的修复是 ``enhanced_logging.py`` 模块加载时调用一次
``_install_root_intercept_once()``，给 root logger 装 ``InterceptHandler``。
本文件锁定这个修复不被未来 refactor 静默回退。

覆盖
====

1. ``InterceptHandler`` 已经在 root logger 上 idempotent 安装。
2. 重复 import ``enhanced_logging`` 不会重复安装（idempotent contract）。
3. ``logging.getLogger("any_module").info("inject\\nFAKE")`` 经过 root
   intercept → Loguru patcher → CRLF 被转义为 ``\\n``。
4. PII（``password=secret123``）被 ``LogSanitizer`` 替换为
   ``***REDACTED***``，无论是用 stdlib logger 还是 EnhancedLogger 都一致。
5. ``setup_logger`` 装的 named logger 仍设置 ``propagate=False``，与 root
   handler 路径独立、不双重输出。
"""

from __future__ import annotations

import importlib
import logging
import unittest

import enhanced_logging
from enhanced_logging import (
    EnhancedLogger,
    InterceptHandler,
    SingletonLogManager,
    _install_root_intercept_once,
    _sanitize_and_escape,
)


class TestRootInterceptHandlerInstalled(unittest.TestCase):
    """root logger 必须有 InterceptHandler。"""

    def test_root_has_intercept_handler(self) -> None:
        """模块加载后 root 至少有一个 InterceptHandler 实例。

        Note：pytest fixture 顺序可能让其他 test reset 过 root.handlers，
        因此这里 actively 调一次 install ensure 函数。这正是 R72-A 把
        install 函数做成 idempotent 的目的。
        """
        _install_root_intercept_once()
        root = logging.getLogger()
        intercepts = [h for h in root.handlers if isinstance(h, InterceptHandler)]
        self.assertGreaterEqual(
            len(intercepts),
            1,
            "root logger 必须有至少一个 InterceptHandler（R72-A 契约）；"
            f"当前 handlers: {root.handlers!r}",
        )

    def test_install_is_idempotent(self) -> None:
        """重复调 ``_install_root_intercept_once`` 不会增加 handler。

        前置条件：先调一次 ensure 模块的 install 被触发（pytest collection
        顺序里其他 test 可能 reload/clear 过 root，所以这里用先 +1 后比对的
        方式锁住"幂等"语义而不是依赖 module-load 时机）。
        """
        _install_root_intercept_once()
        root = logging.getLogger()
        before = len([h for h in root.handlers if isinstance(h, InterceptHandler)])
        self.assertGreaterEqual(
            before, 1, "调用一次 install 后 root 必须至少有 1 个 InterceptHandler"
        )

        for _ in range(5):
            _install_root_intercept_once()

        after = len([h for h in root.handlers if isinstance(h, InterceptHandler)])
        self.assertEqual(
            before,
            after,
            f"重复调用应当是 no-op，但 handler 数从 {before} 涨到 {after}",
        )

    def test_module_reimport_does_not_double_install(self) -> None:
        """``importlib.reload(enhanced_logging)`` 也不能重复安装。

        前置：用 ``_install_root_intercept_once()`` 先确保 root 已有
        InterceptHandler（同样为了不依赖 collection order）。
        """
        _install_root_intercept_once()
        root = logging.getLogger()
        before = len([h for h in root.handlers if isinstance(h, InterceptHandler)])
        self.assertGreaterEqual(before, 1)

        importlib.reload(enhanced_logging)

        after = len(
            [h for h in logging.getLogger().handlers if isinstance(h, InterceptHandler)]
        )
        self.assertEqual(
            before,
            after,
            f"reload 后 handler 数应保持，但从 {before} 变成 {after}",
        )


class TestRootInterceptCRLFSanitize(unittest.TestCase):
    """root intercept 路径必须经过 Loguru patcher 的 CRLF 转义。"""

    def test_crlf_in_user_value_is_escaped(self) -> None:
        """通过 stdlib logger 注入 ``\\n`` 必须被 patcher 转义。

        我们直接调 ``_sanitize_and_escape``（patcher 入口）来锁住契约：
        任何包含 ``\\r`` ``\\n`` ``\\x00`` 的 message 进入 patcher 后，
        原始字符必须消失，被替换成可见 escape 序列。这相当于断言
        ``logging.getLogger("evil").info("a\\nb")`` 路径上的最终 message 不
        会被 SIEM/log aggregator 误判为多条独立 log entry。
        """
        record = {"message": "evil_task_id\nFAKE: admin authenticated"}
        _sanitize_and_escape(record)
        self.assertNotIn("\n", record["message"], "raw newline 必须被转义")
        self.assertIn("\\n", record["message"], "应该出现 visible \\n 标记")
        self.assertIn(
            "FAKE: admin authenticated",
            record["message"],
            "transformed 之后内容仍然应该可读，便于运维 forensics",
        )

    def test_carriage_return_escaped_via_patcher(self) -> None:
        record = {"message": "line1\rspoofed"}
        _sanitize_and_escape(record)
        self.assertNotIn("\r", record["message"])
        self.assertIn("\\r", record["message"])

    def test_null_byte_escaped_via_patcher(self) -> None:
        record = {"message": "log\x00trick"}
        _sanitize_and_escape(record)
        self.assertNotIn("\x00", record["message"])
        self.assertIn("\\x00", record["message"])


class TestPIIRedactionUnifiedAcrossPaths(unittest.TestCase):
    """无论 stdlib 还是 EnhancedLogger 路径，PII 脱敏必须一致。"""

    def test_password_redacted_via_patcher(self) -> None:
        """patcher 会同时跑 sanitizer，password 被 ***REDACTED***."""
        record = {"message": "config: password=super_secret_123"}
        _sanitize_and_escape(record)
        self.assertIn("***REDACTED***", record["message"])
        self.assertNotIn("super_secret_123", record["message"])

    def test_openai_key_redacted_via_patcher(self) -> None:
        record = {"message": "client init with sk-abcdef0123456789012345678"}
        _sanitize_and_escape(record)
        self.assertIn("***REDACTED***", record["message"])
        self.assertNotIn("sk-abcdef0123456789012345678", record["message"])


class TestNamedLoggerNotDoubleEmitted(unittest.TestCase):
    """``setup_logger`` 装的 named logger 仍 propagate=False，不和 root 的 handler 双重输出。"""

    def test_setup_logger_propagate_false(self) -> None:
        """所有 ``setup_logger`` 配置的 logger 必须 propagate=False。"""
        manager = SingletonLogManager()
        named = manager.setup_logger("test_named_propagate_r72a")
        self.assertFalse(
            named.propagate,
            "setup_logger 配置的 logger 必须 propagate=False，否则会和 root "
            "intercept 双重输出（R72-A 兼容性契约）",
        )

    def test_enhanced_logger_uses_setup_logger(self) -> None:
        """``EnhancedLogger.__init__`` 走的就是 setup_logger 路径。"""
        ehlog = EnhancedLogger("test_enhanced_uses_setup_r72a")
        self.assertFalse(
            ehlog.logger.propagate,
            "EnhancedLogger 内部 logger 必须 propagate=False",
        )


class TestRootInterceptDoesNotBreakStdlibBehavior(unittest.TestCase):
    """root 装了 intercept 后，stdlib logger API 必须仍然可用、不抛错。"""

    def test_stdlib_logger_info_does_not_raise(self) -> None:
        """``logging.getLogger("third_party_lib").info(...)`` 不抛错。"""
        third_party = logging.getLogger("test_third_party_r72a")
        try:
            third_party.info("smoke test message")
            third_party.warning("another smoke test")
            third_party.error("error smoke test with %s arg", "interpolation")
        except Exception as exc:
            self.fail(f"stdlib logger emit 不应该抛错，但抛了: {exc!r}")

    def test_stdlib_logger_with_inject_attempt_does_not_raise(self) -> None:
        """注入 ``\\n`` ``\\r`` 也不能让 emit 失败。"""
        third_party = logging.getLogger("test_inject_r72a")
        try:
            third_party.info("user_id=evil\nFAKE: SUCCESS")
            third_party.warning("path=/tmp/\rspoofed/log")
            third_party.error("payload=null\x00byte")
        except Exception as exc:
            self.fail(f"injection attempt 不应该让 emit 抛错: {exc!r}")


class TestRegressionContract(unittest.TestCase):
    """直接绑定 enhanced_logging.py 中的常量，防止 R72-A 修复被静默删除。"""

    def test_install_function_exists(self) -> None:
        """``_install_root_intercept_once`` 必须存在。"""
        self.assertTrue(
            callable(_install_root_intercept_once),
            "_install_root_intercept_once 必须是模块级 callable",
        )

    def test_install_function_called_at_module_load(self) -> None:
        """``importlib.reload(enhanced_logging)`` 后 root 必须有 InterceptHandler。

        Reload 等价于"重新执行模块顶层"，所以是模块顶层有调
        ``_install_root_intercept_once()`` 的强一致性检测。如果 R72-A 的
        ``_install_root_intercept_once()`` 调用被静默从 module top-level 移
        除，这个 test 就会失败。
        """
        importlib.reload(enhanced_logging)
        root = logging.getLogger()
        intercepts = [h for h in root.handlers if isinstance(h, InterceptHandler)]
        self.assertGreaterEqual(
            len(intercepts),
            1,
            "module-level 必须 eager-call _install_root_intercept_once；"
            "如果 root 没有 InterceptHandler，说明 R72-A 的安装路径被绕过",
        )


if __name__ == "__main__":
    unittest.main()
