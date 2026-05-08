"""FastMCP ErrorHandlingMiddleware 集成回归 (R37)

R37 把 ``fastmcp.server.middleware.error_handling.ErrorHandlingMiddleware``
作为 *最外层* middleware 接进 ``server.mcp``，统一捕获 / 记录 / 转换所有下游
异常，并暴露 ``server.get_mcp_error_stats()`` 给运维 / 测试观测。

本文件分两组测试：

1. 静态契约（``TestErrorHandlingMiddlewareStaticContract``）
   - ``mcp.middleware`` 必须存在 ErrorHandlingMiddleware；
   - 它必须在索引 0（最外层），可以 wrap 住 FastMCP 内置的
     DereferenceRefsMiddleware；
   - 配置必须与 server.py 的设计取舍一致：
     * logger.name == ``ai_intervention_agent.fastmcp_errors``
     * include_traceback is False
     * transform_errors is True
   - ``get_mcp_error_stats`` 暴露在 ``server`` 模块上，调用返回 ``dict``。

2. 运行时行为（``TestErrorHandlingMiddlewareRuntime``）
   - 直接调用 ``await middleware(ctx, call_next)``，验证：
     * ValueError / TypeError → McpError(-32602 Invalid params)
     * FileNotFoundError / KeyError @ ``tools/call`` → McpError(-32001 Not found)
     * FileNotFoundError @ ``resources/read`` → McpError(-32002 Resource not found)
     * PermissionError → McpError(-32000 Permission denied)
     * TimeoutError → McpError(-32000 Request timeout)
       （Python 3.11+ 起 ``asyncio.TimeoutError is TimeoutError``，仅锁内置类型）
     * 其它未识别异常 → McpError(-32603 Internal error)
     * 已经是 McpError 时不被二次转换 / 不丢失原始 error code
     * 正常路径 (no exception) 返回值原样透传，logger 不被触发
     * error_counts 按 ``{ErrorType}:{method}`` 累加，``get_error_stats()``
       返回的是 *副本*（外部修改不影响内部累加器）

为什么要既测静态又测运行时：

- 单测静态（spec snapshot）能拦住「有人误删 ``mcp.middleware.insert``」、
  「config 被改回默认值」、「位置被 swap 到 inner」这类回归。
- 单测运行时能拦住「升级 fastmcp 后 _transform_error 表行为改了」、
  「on_message 改名 / 被覆盖」之类的库侧变更，避免我们生产环境
  client 收到的不是统一错误码。
"""

from __future__ import annotations

import asyncio
import logging
import unittest
from datetime import UTC, datetime
from typing import Any, Literal, cast
from unittest.mock import patch

from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext
from mcp import McpError
from mcp.types import ErrorData

import ai_intervention_agent.server as server

_EXPECTED_LOGGER_NAME = "ai_intervention_agent.fastmcp_errors"


def _build_context(
    *,
    method: str | None = "tools/call",
    type_: Literal["request", "notification"] = "request",
    source: Literal["client", "server"] = "client",
    message: Any = None,
) -> MiddlewareContext[Any]:
    """构造一个最小 MiddlewareContext 用来驱动 middleware.

    MiddlewareContext 是 frozen dataclass，必须 keyword-only 构造。这里把
    高频字段封装成 helper，避免每个 test case 重复写 boilerplate。
    """
    return MiddlewareContext(
        message=message if message is not None else object(),
        fastmcp_context=None,
        source=source,
        type=type_,
        method=method,
        timestamp=datetime.now(UTC),
    )


class TestErrorHandlingMiddlewareStaticContract(unittest.TestCase):
    """静态契约：server.mcp 已经按 R37 设计接好 ErrorHandlingMiddleware。"""

    def test_module_exposes_get_mcp_error_stats(self) -> None:
        self.assertTrue(
            callable(getattr(server, "get_mcp_error_stats", None)),
            "server 模块必须暴露 get_mcp_error_stats() 给运维 / 测试入口",
        )
        stats = server.get_mcp_error_stats()
        self.assertIsInstance(stats, dict)

    def test_get_mcp_error_stats_returns_copy(self) -> None:
        """返回值应当是 *副本*——外部修改不能污染内部累加器。"""
        stats_before = server.get_mcp_error_stats()
        stats_before["__poisoned__"] = 99999
        stats_after = server.get_mcp_error_stats()
        self.assertNotIn(
            "__poisoned__",
            stats_after,
            "get_mcp_error_stats() 必须返回副本，否则外部能污染内部 error_counts",
        )

    def test_middleware_is_registered(self) -> None:
        """``mcp.middleware`` 必须含一个 ErrorHandlingMiddleware 实例。"""
        instances = [
            mw
            for mw in server.mcp.middleware
            if isinstance(mw, ErrorHandlingMiddleware)
        ]
        self.assertEqual(
            len(instances),
            1,
            (
                "mcp.middleware 中应当恰好存在 1 个 ErrorHandlingMiddleware；"
                f"实际找到 {len(instances)} 个"
            ),
        )

    def test_middleware_is_outermost(self) -> None:
        """ErrorHandlingMiddleware 必须在索引 0，才能兜住 DereferenceRefsMiddleware
        及其它后接的 middleware。

        FastMCP 的执行链是 ``for mw in reversed(self.middleware)``，索引越靠前 =
        越靠外。如果有人改成 ``add_middleware`` (append)，错误处理就会被内层
        middleware 抛出的异常旁路掉，client 收到的将是非标准 error frame。
        """
        self.assertGreaterEqual(
            len(server.mcp.middleware),
            1,
            "mcp.middleware 不能为空；至少应当有 R37 的 ErrorHandlingMiddleware",
        )
        outermost = server.mcp.middleware[0]
        self.assertIsInstance(
            outermost,
            ErrorHandlingMiddleware,
            (
                "ErrorHandlingMiddleware 必须放在 mcp.middleware 的首位（最外层）"
                "；否则下游 middleware 异常无法被统一捕获"
            ),
        )

    def test_middleware_singleton_matches_module_attribute(self) -> None:
        """``server._ERROR_HANDLING_MIDDLEWARE`` 必须就是注册到 mcp 上那一只
        实例——这是 ``get_mcp_error_stats()`` 能取到正确累加器的前提。"""
        self.assertIs(
            server._ERROR_HANDLING_MIDDLEWARE,
            server.mcp.middleware[0],
            (
                "server._ERROR_HANDLING_MIDDLEWARE 必须与 mcp.middleware[0] "
                "为同一对象，否则 stats 视图会和真实链路脱节"
            ),
        )

    def test_middleware_configuration(self) -> None:
        mw = server._ERROR_HANDLING_MIDDLEWARE
        self.assertEqual(
            mw.logger.name,
            _EXPECTED_LOGGER_NAME,
            (
                f"ErrorHandlingMiddleware logger 名应当是 {_EXPECTED_LOGGER_NAME!r}"
                f"，实际 {mw.logger.name!r}"
            ),
        )
        self.assertFalse(
            mw.include_traceback,
            "include_traceback 必须保持 False，避免与 server_feedback 自身的 "
            "exc_info=True 日志重复",
        )
        self.assertTrue(
            mw.transform_errors,
            "transform_errors 必须保持 True，client 才能收到标准 MCP 错误码",
        )


class TestErrorHandlingMiddlewareRuntime(unittest.TestCase):
    """运行时行为：直接 drive 一个独立 middleware 实例验证转换 / 计数 / 日志。

    使用独立实例（而不是 ``server._ERROR_HANDLING_MIDDLEWARE``）的原因：
    - 测试互相之间不会通过 error_counts 串味；
    - 不依赖测试运行顺序；
    - 不会污染生产 middleware 的统计快照。
    """

    def setUp(self) -> None:
        self.logger = logging.getLogger("test.fastmcp_errors_r37")
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.logger.setLevel(logging.ERROR)
        self.middleware = ErrorHandlingMiddleware(
            logger=self.logger,
            include_traceback=False,
            transform_errors=True,
        )

    async def _drive(
        self,
        exc: BaseException | None,
        *,
        method: str | None = "tools/call",
        return_value: Any = "ok",
    ) -> Any:
        ctx = _build_context(method=method)

        async def _call_next(_ctx: MiddlewareContext[Any]) -> Any:
            if exc is not None:
                raise exc
            return return_value

        # ``CallNext`` 是一个 ``runtime_checkable`` Protocol（接受 Awaitable）；
        # ``async def`` 推断出的类型是 ``Coroutine`` —— 它本质上 *is* 一个
        # Awaitable，运行时完全兼容，但 ty 不会自动把 Coroutine 推升到
        # CallNext。直接 ``cast`` 跳过结构子类型化的保守判断，等价于运行时
        # ``isinstance(_call_next, CallNext) is True`` 的事实。
        return await self.middleware(ctx, cast(CallNext[Any, Any], _call_next))

    def _assert_mcperror(
        self,
        coro: Any,
        *,
        expected_code: int,
        message_contains: str | None = None,
    ) -> McpError:
        with self.assertRaises(McpError) as cm:
            asyncio.run(coro)
        err = cm.exception
        self.assertEqual(
            err.error.code,
            expected_code,
            (
                f"期望 McpError code={expected_code}，实际 {err.error.code}；"
                f"message={err.error.message!r}"
            ),
        )
        if message_contains is not None:
            self.assertIn(message_contains, err.error.message)
        return err

    def test_value_error_maps_to_invalid_params(self) -> None:
        self._assert_mcperror(
            self._drive(ValueError("bad arg")),
            expected_code=-32602,
            message_contains="bad arg",
        )

    def test_type_error_maps_to_invalid_params(self) -> None:
        self._assert_mcperror(
            self._drive(TypeError("wrong type")),
            expected_code=-32602,
            message_contains="wrong type",
        )

    def test_filenotfound_in_resources_maps_to_resource_not_found(self) -> None:
        self._assert_mcperror(
            self._drive(FileNotFoundError("missing"), method="resources/read"),
            expected_code=-32002,
        )

    def test_filenotfound_in_tools_maps_to_generic_not_found(self) -> None:
        self._assert_mcperror(
            self._drive(FileNotFoundError("missing"), method="tools/call"),
            expected_code=-32001,
        )

    def test_keyerror_maps_to_not_found(self) -> None:
        self._assert_mcperror(
            self._drive(KeyError("k")),
            expected_code=-32001,
        )

    def test_permission_error_maps_to_permission_denied(self) -> None:
        self._assert_mcperror(
            self._drive(PermissionError("nope")),
            expected_code=-32000,
            message_contains="Permission denied",
        )

    def test_timeout_error_maps_to_request_timeout(self) -> None:
        """Python 3.11+ 起 ``asyncio.TimeoutError is TimeoutError``，所以这里
        只验证内置 ``TimeoutError`` 的转换路径——FastMCP 之所以同时检查两个
        类型，是为了兼容 Python 3.10。我们只锁现网行为。"""
        self._assert_mcperror(
            self._drive(TimeoutError()),
            expected_code=-32000,
            message_contains="Request timeout",
        )

    def test_unknown_exception_maps_to_internal_error(self) -> None:
        class _Weird(RuntimeError):
            pass

        self._assert_mcperror(
            self._drive(_Weird("boom")),
            expected_code=-32603,
            message_contains="Internal error",
        )

    def test_existing_mcperror_passes_through(self) -> None:
        original = McpError(ErrorData(code=-32099, message="custom"))
        self._assert_mcperror(
            self._drive(original),
            expected_code=-32099,
            message_contains="custom",
        )

    def test_no_exception_passthrough_does_not_log(self) -> None:
        with patch.object(self.middleware.logger, "error") as mock_err:
            result = asyncio.run(self._drive(None, return_value={"ok": True}))
        self.assertEqual(result, {"ok": True})
        mock_err.assert_not_called()
        self.assertEqual(
            self.middleware.get_error_stats(),
            {},
            "成功路径不应当 increment error_counts",
        )

    def test_error_counts_accumulate_per_type_and_method(self) -> None:
        with patch.object(self.middleware.logger, "error"):
            with self.assertRaises(McpError):
                asyncio.run(self._drive(ValueError("a"), method="tools/call"))
            with self.assertRaises(McpError):
                asyncio.run(self._drive(ValueError("b"), method="tools/call"))
            with self.assertRaises(McpError):
                asyncio.run(self._drive(KeyError("c"), method="tools/call"))
            with self.assertRaises(McpError):
                asyncio.run(self._drive(ValueError("d"), method="resources/read"))
        stats = self.middleware.get_error_stats()
        self.assertEqual(stats.get("ValueError:tools/call"), 2)
        self.assertEqual(stats.get("KeyError:tools/call"), 1)
        self.assertEqual(stats.get("ValueError:resources/read"), 1)

    def test_get_error_stats_returns_copy(self) -> None:
        with patch.object(self.middleware.logger, "error"):
            with self.assertRaises(McpError):
                asyncio.run(self._drive(ValueError("x")))
        snap = self.middleware.get_error_stats()
        snap["should_not_persist"] = 999
        self.assertNotIn("should_not_persist", self.middleware.get_error_stats())

    def test_logger_record_format_is_compact(self) -> None:
        """``include_traceback=False`` 时，日志只应当输出一行 ``Error in {method}:
        {ErrorType}: {msg}``，不应包含 traceback 多行栈。"""
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level=logging.ERROR)
        self.logger.addHandler(handler)
        try:
            with self.assertRaises(McpError):
                asyncio.run(self._drive(ValueError("compact"), method="tools/call"))
        finally:
            self.logger.removeHandler(handler)

        self.assertEqual(len(records), 1)
        msg = records[0].getMessage()
        self.assertIn("Error in tools/call", msg)
        self.assertIn("ValueError", msg)
        self.assertIn("compact", msg)
        self.assertNotIn(
            "Traceback",
            msg,
            "include_traceback=False 时日志不应当包含 traceback 文本",
        )


if __name__ == "__main__":
    unittest.main()
