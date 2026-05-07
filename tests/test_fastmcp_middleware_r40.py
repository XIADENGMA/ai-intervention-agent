"""FastMCP 最佳实践增量回归 (R40)

R40 在 ``server.mcp`` 上叠加另外两层 FastMCP 推荐中间件，并暴露一个 self-info
resource，让运维 / client UI 能在不调用任何 tool 的情况下拿到 server 自检
信息：

1. ``TimingMiddleware`` ─ 写每次 request 的执行时间，按需开 INFO 即可看
   tool latency 分布；
2. ``LoggingMiddleware`` ─ 写 request/response 入口出口结构化日志，开
   ``include_payload_length=True`` 让我们能看 payload 大小但不落隐私正文；
3. ``aiia://server/info`` resource ─ 一次性返回 ``name / version /
   transport / error_stats / web_ui``，client UI 可在 "MCP server 详情"
   页面直接渲染。

为什么 R40 单独建一个测试文件而不是合进 R37：

- 静态契约边界清晰：``server.py`` 的中间件 / resource 注册逻辑分两批落地
  （R37 = ErrorHandling，R40 = Timing+Logging+resource），把每批的 spec
  snapshot 单独放一个文件让 ``git log -p tests/test_fastmcp_middleware_r40.py``
  能直接读出"这批改动锁了哪些契约"。
- 运行时行为：R40 关注 timing/logging/resource 都是"运行后能跑出值"而非
  "异常被转换"。两类断言天生不同，分文件更易读。

测试组织：

1. 静态契约
   - ``mcp.middleware`` 必须存在恰好 1 个 TimingMiddleware + 1 个
     LoggingMiddleware；
   - 顺序：ErrorHandling[0] → ... → Timing → Logging（Logging 最内层）；
   - 配置必须与 ``server.py`` 设计一致（logger 名、include_payloads
     的安全默认 False、max_payload_length=1000、include_payload_length=True）。

2. 运行时行为
   - ``server.server_info_resource()`` 返回 dict 含必填字段；
   - resource URI 注册到 ``aiia://server/info``，能通过
     ``mcp.get_resource(...)`` 拿到；
   - resource 是 read-only：不论 web_ui 是否在跑，都不会试图启动它。
"""

from __future__ import annotations

import asyncio
import logging
import unittest
from typing import Any, cast
from unittest.mock import patch

from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import (
    LoggingMiddleware,
    StructuredLoggingMiddleware,
)
from fastmcp.server.middleware.timing import TimingMiddleware

import server

_EXPECTED_TIMING_LOGGER = "ai_intervention_agent.fastmcp_timing"
_EXPECTED_LOGGING_LOGGER = "ai_intervention_agent.fastmcp_requests"
_SERVER_INFO_URI = "aiia://server/info"


class TestTimingMiddlewareStaticContract(unittest.TestCase):
    """``server.mcp`` 必须按 R40 接好 TimingMiddleware。"""

    def test_timing_middleware_registered_exactly_once(self) -> None:
        instances = [
            mw for mw in server.mcp.middleware if isinstance(mw, TimingMiddleware)
        ]
        self.assertEqual(
            len(instances),
            1,
            (
                "mcp.middleware 中应当恰好有 1 个 TimingMiddleware；"
                f"实际 {len(instances)} 个"
            ),
        )

    def test_timing_middleware_singleton_matches_module_attribute(self) -> None:
        """``server._TIMING_MIDDLEWARE`` 必须就是注册到 ``mcp`` 上的那只。"""
        self.assertIn(server._TIMING_MIDDLEWARE, server.mcp.middleware)
        same = [mw for mw in server.mcp.middleware if mw is server._TIMING_MIDDLEWARE]
        self.assertEqual(len(same), 1)

    def test_timing_middleware_configuration(self) -> None:
        mw = server._TIMING_MIDDLEWARE
        self.assertEqual(
            mw.logger.name,
            _EXPECTED_TIMING_LOGGER,
            (
                f"TimingMiddleware logger 名应当是 {_EXPECTED_TIMING_LOGGER!r}，"
                f"实际 {mw.logger.name!r}"
            ),
        )
        self.assertEqual(
            mw.log_level,
            logging.INFO,
            "TimingMiddleware 默认 log_level 必须是 INFO，按需开启时不会触发",
        )


class TestLoggingMiddlewareStaticContract(unittest.TestCase):
    """``server.mcp`` 必须按 R40 接好 LoggingMiddleware（非 Structured）。"""

    def test_logging_middleware_registered_exactly_once(self) -> None:
        # 严格挑 LoggingMiddleware 而不是 StructuredLoggingMiddleware（前者是
        # 后者父类的某个版本，必须用 not isinstance 反向排除以避免误判）。
        instances = [
            mw
            for mw in server.mcp.middleware
            if isinstance(mw, LoggingMiddleware)
            and not isinstance(mw, StructuredLoggingMiddleware)
        ]
        self.assertEqual(
            len(instances),
            1,
            (
                "mcp.middleware 中应当恰好有 1 个 LoggingMiddleware "
                "（非 StructuredLoggingMiddleware）；"
                f"实际 {len(instances)} 个"
            ),
        )

    def test_logging_middleware_singleton_matches_module_attribute(self) -> None:
        self.assertIn(server._LOGGING_MIDDLEWARE, server.mcp.middleware)
        same = [mw for mw in server.mcp.middleware if mw is server._LOGGING_MIDDLEWARE]
        self.assertEqual(len(same), 1)

    def test_logging_middleware_configuration(self) -> None:
        mw = server._LOGGING_MIDDLEWARE
        self.assertEqual(
            mw.logger.name,
            _EXPECTED_LOGGING_LOGGER,
            (
                f"LoggingMiddleware logger 名应当是 {_EXPECTED_LOGGING_LOGGER!r}，"
                f"实际 {mw.logger.name!r}"
            ),
        )
        self.assertEqual(mw.log_level, logging.INFO)
        self.assertFalse(
            mw.include_payloads,
            "include_payloads 必须保持 False，避免把用户对话内容写到 stderr",
        )
        self.assertTrue(
            mw.include_payload_length,
            "include_payload_length 必须保持 True，便于诊断 payload 大小分布",
        )
        self.assertEqual(
            mw.max_payload_length,
            1000,
            "max_payload_length 默认 1000：与 R40 server.py 设计取舍一致",
        )


class TestMiddlewareOrder(unittest.TestCase):
    """ErrorHandling 必须在最外层，Timing 在 Logging 之外。"""

    def test_error_handling_remains_outermost(self) -> None:
        self.assertIsInstance(
            server.mcp.middleware[0],
            ErrorHandlingMiddleware,
            "ErrorHandlingMiddleware 必须保持在 mcp.middleware[0]（R37 契约）",
        )

    def test_timing_outer_than_logging(self) -> None:
        """Timing 必须在 Logging 之前 = 外层（保证 timing 测的是 handler+logging
        总耗时；logging 在内层看到 dereferenced schema，日志噪音最小）。"""
        order = server.mcp.middleware
        timing_idx = next(
            (i for i, mw in enumerate(order) if isinstance(mw, TimingMiddleware)),
            -1,
        )
        logging_idx = next(
            (
                i
                for i, mw in enumerate(order)
                if isinstance(mw, LoggingMiddleware)
                and not isinstance(mw, StructuredLoggingMiddleware)
            ),
            -1,
        )
        self.assertGreaterEqual(timing_idx, 0)
        self.assertGreaterEqual(logging_idx, 0)
        self.assertLess(
            timing_idx,
            logging_idx,
            (
                f"Timing(idx={timing_idx}) 必须在 Logging(idx={logging_idx}) 之前 "
                "= 外层；否则 timing 测到的耗时会缺少 logging 序列化阶段"
            ),
        )

    def test_error_handling_outer_than_both(self) -> None:
        order = server.mcp.middleware
        eh_idx = next(
            (
                i
                for i, mw in enumerate(order)
                if isinstance(mw, ErrorHandlingMiddleware)
            ),
            -1,
        )
        timing_idx = next(
            (i for i, mw in enumerate(order) if isinstance(mw, TimingMiddleware)),
            -1,
        )
        logging_idx = next(
            (
                i
                for i, mw in enumerate(order)
                if isinstance(mw, LoggingMiddleware)
                and not isinstance(mw, StructuredLoggingMiddleware)
            ),
            -1,
        )
        self.assertGreaterEqual(eh_idx, 0)
        self.assertLess(eh_idx, timing_idx)
        self.assertLess(eh_idx, logging_idx)


class TestServerInfoResourceStaticContract(unittest.TestCase):
    """``aiia://server/info`` resource 必须注册并暴露 server self-info。"""

    def test_resource_callable_exists_on_module(self) -> None:
        self.assertTrue(
            callable(getattr(server, "server_info_resource", None)),
            "server.server_info_resource 必须存在并可调用",
        )

    def test_resource_registered_in_mcp(self) -> None:
        async def _fetch() -> Any:
            # ``list_resources()`` / ``get_resource()`` 在 FastMCP 3.x 都是
            # async；用 asyncio.run 在测试里平展成同步入口。
            listed = await server.mcp.list_resources()
            single = await server.mcp.get_resource(_SERVER_INFO_URI)
            return listed, single

        listed, single = asyncio.run(_fetch())

        uris = sorted(str(r.uri) for r in listed)
        self.assertIn(
            _SERVER_INFO_URI,
            uris,
            (
                f"FastMCP resource registry 中应有 URI {_SERVER_INFO_URI!r}；"
                f"已注册：{uris}"
            ),
        )

        self.assertIsNotNone(
            single,
            f"server.mcp.get_resource({_SERVER_INFO_URI!r}) 必须返回 Resource，不是 None",
        )
        # FastMCP Resource 的 mime_type 字段类型在 3.x 里是 str；为了对未来
        # 可能演进的 enum 包裹也兼容，统一比较 str(...)。
        self.assertEqual(str(single.mime_type), "application/json")
        self.assertIn("diagnostics", single.tags)
        self.assertIn("self-info", single.tags)


class TestServerInfoResourceRuntime(unittest.TestCase):
    """直接调用 ``server.server_info_resource()`` 应该总能拿到结构化 dict。"""

    def test_returns_required_keys(self) -> None:
        info = server.server_info_resource()
        self.assertIsInstance(info, dict)
        for key in ("name", "version", "transport", "error_stats", "web_ui"):
            self.assertIn(key, info, f"server info dict 缺字段 {key!r}：{info}")

    def test_name_matches_mcp_instance(self) -> None:
        info = server.server_info_resource()
        self.assertEqual(info["name"], server.mcp.name)

    def test_transport_is_stdio(self) -> None:
        info = server.server_info_resource()
        self.assertEqual(
            info["transport"],
            "stdio",
            "目前只跑 stdio transport；未来若启用 streamable-http 需同步更新",
        )

    def test_error_stats_is_dict(self) -> None:
        info = server.server_info_resource()
        self.assertIsInstance(info["error_stats"], dict)

    def test_web_ui_is_dict(self) -> None:
        """web_ui 字段必须是 dict（best-effort 探测，永远不抛异常向上冒）。"""
        info = server.server_info_resource()
        self.assertIsInstance(info["web_ui"], dict)

    def test_web_ui_probe_swallows_config_error(self) -> None:
        """``get_web_ui_config`` 抛异常时 resource 仍应返回有效 dict
        （只在 ``web_ui`` 子字段里写错误信息，不向上冒）。"""

        with patch.object(
            server, "get_web_ui_config", side_effect=RuntimeError("synthetic")
        ):
            info = server.server_info_resource()

        self.assertIsInstance(info, dict)
        # ``server_info_resource`` 声明返回 ``dict[str, object]``,
        # ty 静态分析下 ``info["web_ui"]`` 推断为 ``object``,
        # 必须 cast 后才能继续下标访问;
        # 运行时由 self.assertIsInstance 断言兜底实际类型。
        web_ui = cast(dict[str, Any], info["web_ui"])
        self.assertIsInstance(web_ui, dict)
        self.assertIn("error", web_ui)
        self.assertIn("synthetic", str(web_ui["error"]))

    def test_web_ui_probe_swallows_port_check_error(self) -> None:
        """``is_web_service_running`` 抛异常时 ``web_ui`` 子字段仍含 host/port + probe_error，
        不向上冒。"""

        from server_config import WebUIConfig

        # WebUIConfig 必填字段 host / port；其它字段（language/timeout/...）有
        # 默认值。这里只关心 probe 异常的传播，host/port 用 loopback 占位。
        cfg = WebUIConfig(host="127.0.0.1", port=8080)

        with (
            patch.object(server, "get_web_ui_config", return_value=(cfg, 0)),
            patch.object(
                server,
                "is_web_service_running",
                side_effect=RuntimeError("synthetic-probe"),
            ),
        ):
            info = server.server_info_resource()

        # 同 test_web_ui_probe_swallows_config_error: cast 后再下标访问;
        # 运行时由 assertIsInstance 兜底。
        web_ui = cast(dict[str, Any], info["web_ui"])
        self.assertIsInstance(web_ui, dict)
        self.assertEqual(web_ui["running"], False)
        self.assertIn("probe_error", web_ui)
        self.assertIn("synthetic-probe", str(web_ui["probe_error"]))


if __name__ == "__main__":
    unittest.main()
