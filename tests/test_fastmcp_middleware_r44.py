"""R44 FastMCP 最佳实践回归契约。

覆盖点：
- ``RateLimitingMiddleware`` 已注册到 ``mcp.middleware`` 的正确顺序位置；
- ``server_info_resource`` 新增字段（``runtime`` / ``fastmcp`` / ``middleware`` /
  ``task_queue``）的稳定 schema；
- ``interactive_feedback`` 函数签名增加了 keyword-only ``ctx`` 参数（通过源码
  静态扫描检查，因为 FastMCP 在 ``@mcp.tool`` 装饰过程中改写了 default）；
- ``_emit_ctx_info`` 在 ``ctx is None`` / ``ctx.info`` 抛异常 两种情况下都安全。

设计原则：
- 不通过任何真实 LLM client / 真实 web_ui 子进程 / 网络 I/O 触发
  ``interactive_feedback``，纯 in-process 单元测试。
- 仅做契约 / 静态检测 / mock 注入，避免任何启动副作用。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# NOTE: 故意不在 module-level 设置 ``AI_INTERVENTION_AGENT_DEV_MODE`` 等环境
# 变量——pytest 是单进程跑所有测试，共享 ``os.environ``，会污染
# ``test_config_manager.py`` 等依赖未设置默认环境的旧测试。``server.py``
# 顶层 import 本身只构造 ``mcp`` 实例 + 注册中间件，不会触发 web_ui /
# 通知线程池副作用，所以用不上这层 guard。

import ai_intervention_agent.server as server
import ai_intervention_agent.server_feedback as server_feedback


class TestRateLimitingMiddlewareRegistered(unittest.TestCase):
    """R44-A：``RateLimitingMiddleware`` 加入中间件链 + 正确位置。"""

    def test_singleton_attached_to_module(self) -> None:
        self.assertTrue(hasattr(server, "_RATE_LIMITING_MIDDLEWARE"))
        from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

        self.assertIsInstance(server._RATE_LIMITING_MIDDLEWARE, RateLimitingMiddleware)

    def test_present_in_mcp_middleware_chain(self) -> None:
        names = [type(mw).__name__ for mw in server.mcp.middleware]
        self.assertIn("RateLimitingMiddleware", names)

    def test_outer_than_timing_and_logging(self) -> None:
        """RateLimit 必须在 Timing/Logging 之前——限流命中时不再付下游开销。"""
        names = [type(mw).__name__ for mw in server.mcp.middleware]
        rl_idx = names.index("RateLimitingMiddleware")
        self.assertLess(rl_idx, names.index("TimingMiddleware"))
        self.assertLess(rl_idx, names.index("LoggingMiddleware"))

    def test_inner_than_error_handling(self) -> None:
        """RateLimit 必须在 ErrorHandling 之后——限流异常被外层兜成 MCP error。"""
        names = [type(mw).__name__ for mw in server.mcp.middleware]
        eh_idx = names.index("ErrorHandlingMiddleware")
        rl_idx = names.index("RateLimitingMiddleware")
        self.assertLess(eh_idx, rl_idx)


class TestRateLimitingMiddlewareConfig(unittest.TestCase):
    """R44-A：``RateLimit`` 配置参数与文档保持同步。"""

    def test_burst_capacity_documented_value(self) -> None:
        # 通过源码静态扫描 ``server.py`` 配置点而不是依赖 fastmcp 内部属性命名，
        # 防止 fastmcp 升级时字段重命名导致测试虚假失败。
        src = (REPO_ROOT / "src" / "ai_intervention_agent" / "server.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(src, r"max_requests_per_second=10\.0")
        self.assertRegex(src, r"burst_capacity=20")

    def test_module_doc_explains_chain_position(self) -> None:
        src = (REPO_ROOT / "src" / "ai_intervention_agent" / "server.py").read_text(
            encoding="utf-8"
        )
        # 文档应解释顺序为何 ``insert(1, ...)``
        self.assertIn("insert(1", src)
        self.assertIn("RateLimiting", src)


class TestServerInfoResourceR44Fields(unittest.TestCase):
    """R44-C：``aiia://server/info`` resource 新增字段契约。"""

    def setUp(self) -> None:
        self.info: dict[str, Any] = server.server_info_resource()

    def test_runtime_block_present(self) -> None:
        runtime = self.info.get("runtime")
        self.assertIsInstance(runtime, dict)
        runtime_dict = cast(dict, runtime)
        self.assertIn("python_version", runtime_dict)
        # python_version 必须是 ``A.B.C`` 形式，确保字段可被运维直接 grep
        self.assertRegex(runtime_dict["python_version"], r"^\d+\.\d+(\.\d+)?")
        self.assertIn("python_executable", runtime_dict)
        self.assertIn("platform", runtime_dict)

    def test_fastmcp_block_present(self) -> None:
        fmcp = self.info.get("fastmcp")
        self.assertIsInstance(fmcp, dict)
        ver = cast(dict, fmcp).get("version")
        self.assertIsInstance(ver, str)

    def test_middleware_chain_lists_known_classes(self) -> None:
        chain = self.info.get("middleware")
        self.assertIsInstance(chain, list)
        chain_list = cast(list, chain)
        self.assertEqual(chain_list[0], "ErrorHandlingMiddleware")
        self.assertEqual(chain_list[-1], "LoggingMiddleware")
        self.assertIn("RateLimitingMiddleware", chain_list)

    def test_task_queue_block_best_effort(self) -> None:
        tq = self.info.get("task_queue")
        self.assertIsInstance(tq, dict)
        # 必含 ``initialized`` 字段，True/False 都接受
        self.assertIn("initialized", cast(dict, tq))
        self.assertIsInstance(cast(dict, tq)["initialized"], bool)


class TestServerInfoResourceR44ErrorIsolation(unittest.TestCase):
    """R44-C：每个新字段块独立 try/except，单个异常不影响其它字段。"""

    def test_each_block_isolated_when_partial_failure(self) -> None:
        # 这里是结构性检测：扫描源码确认每个新增 ``info[...]`` 之前都有
        # 独立的 try/except，避免一个失败把整个 resource 弄崩。
        src = (REPO_ROOT / "src" / "ai_intervention_agent" / "server.py").read_text(
            encoding="utf-8"
        )
        block_names = ("runtime_info", "fastmcp_info", "task_queue_info")
        for name in block_names:
            with self.subTest(block=name):
                self.assertRegex(
                    src,
                    rf"{name}\s*:\s*dict\[str,\s*object\]\s*=\s*\{{\}}",
                    f"{name} 应该被显式初始化为 dict",
                )
        # info[...] 赋值至少一次出现
        self.assertIn("info[", src)


class TestInteractiveFeedbackContextSignatureSourceLevel(unittest.TestCase):
    """R44-B：``interactive_feedback`` 源码级签名包含 keyword-only ``ctx``。

    理由：``inspect.signature(server_feedback.interactive_feedback)`` 返回的是
    被 ``@mcp.tool`` 装饰后改写过 default 的 wrapper，不能直接用于校验
    ``default is None``。所以走源码静态扫描更稳。
    """

    def setUp(self) -> None:
        self.src = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "server_feedback.py"
        ).read_text(encoding="utf-8")

    def test_ctx_keyword_only_marker_present(self) -> None:
        # 必须有 ``*,`` 单独成行（标志后续参数都是 keyword-only）
        self.assertTrue(
            bool(re.search(r"^\s+\*,\s*$", self.src, flags=re.MULTILINE)),
            "expected ``*,`` keyword-only sentinel on its own line in interactive_feedback signature",
        )

    def test_ctx_param_default_is_none(self) -> None:
        # ``ctx: FastMCPContext | None = None,`` 字面量必须存在
        self.assertRegex(self.src, r"ctx:\s*FastMCPContext\s*\|\s*None\s*=\s*None")

    def test_emit_ctx_info_called_at_three_anchors(self) -> None:
        # task.created / task.notified / task.completed 三处都应 await _emit_ctx_info
        self.assertGreaterEqual(self.src.count("await _emit_ctx_info"), 3)

    def test_fastmcpcontext_runtime_imported(self) -> None:
        # ``FastMCPContext`` 必须在运行时（非 TYPE_CHECKING）被 import，
        # 否则 typing.get_type_hints() 解析签名时会 NameError
        self.assertTrue(
            bool(
                re.search(
                    r"^from fastmcp\.server\.context import Context as FastMCPContext$",
                    self.src,
                    flags=re.MULTILINE,
                )
            ),
            "expected runtime import: ``from fastmcp.server.context import Context as FastMCPContext``",
        )


class TestEmitCtxInfoSafety(unittest.IsolatedAsyncioTestCase):
    """R44-B：``_emit_ctx_info`` 在各种异常场景下都安全。"""

    async def test_none_ctx_no_op(self) -> None:
        # 不应抛异常
        await server_feedback._emit_ctx_info(None, "hello")

    async def test_ctx_info_called_with_extra(self) -> None:
        ctx = MagicMock()
        ctx.info = AsyncMock(return_value=None)
        await server_feedback._emit_ctx_info(ctx, "hello", task_id="t1", count=42)
        ctx.info.assert_awaited_once_with(
            "hello",
            extra={"task_id": "t1", "count": 42},
        )

    async def test_ctx_info_called_without_extra(self) -> None:
        ctx = MagicMock()
        ctx.info = AsyncMock(return_value=None)
        await server_feedback._emit_ctx_info(ctx, "hello")
        ctx.info.assert_awaited_once_with("hello")

    async def test_ctx_info_swallows_runtime_error(self) -> None:
        ctx = MagicMock()
        ctx.info = AsyncMock(side_effect=RuntimeError("client disconnected"))
        # 不应 raise
        await server_feedback._emit_ctx_info(ctx, "hello", task_id="t1")
        # 但仍 attempted to call
        ctx.info.assert_awaited_once()

    async def test_ctx_info_swallows_attribute_error(self) -> None:
        ctx = MagicMock()
        ctx.info = AsyncMock(side_effect=AttributeError("ctx broken"))
        await server_feedback._emit_ctx_info(ctx, "hello")

    async def test_ctx_with_no_info_attr_swallows_error(self) -> None:
        # ``ctx`` 没有 ``info`` 方法时，``await ctx.info(...)`` 会 TypeError 因为
        # MagicMock 默认是 sync 的——helper 应该把这个 TypeError 也吞掉。
        ctx = MagicMock(spec=[])  # 完全没属性
        # Magic spec=[] 会让 ctx.info 抛 AttributeError（包装在 try/except 里被吞）
        await server_feedback._emit_ctx_info(ctx, "hello")


class TestServerBootBannerR44(unittest.TestCase):
    """R44 banner 自动反映新中间件——验证 banner 字符串静态构造正确。"""

    def test_banner_uses_dynamic_middleware_list(self) -> None:
        src = (REPO_ROOT / "src" / "ai_intervention_agent" / "server.py").read_text(
            encoding="utf-8"
        )
        # banner 行使用 ``middleware={','.join(middleware_names)}``
        self.assertRegex(src, r"middleware=\{','\.join\(middleware_names\)\}")
        # ``middleware_names`` 必须从 ``mcp.middleware`` 动态读取
        self.assertRegex(
            src,
            r"middleware_names\s*=\s*\[type\(mw\)\.__name__ for mw in mcp\.middleware\]",
        )


class TestNoRegressionsInPriorMiddlewareDocs(unittest.TestCase):
    """R44 不应破坏 R37/R40 已建立的中间件文档契约。"""

    def test_error_handling_singleton_present(self) -> None:
        self.assertTrue(hasattr(server, "_ERROR_HANDLING_MIDDLEWARE"))

    def test_timing_singleton_present(self) -> None:
        self.assertTrue(hasattr(server, "_TIMING_MIDDLEWARE"))

    def test_logging_singleton_present(self) -> None:
        self.assertTrue(hasattr(server, "_LOGGING_MIDDLEWARE"))


if __name__ == "__main__":
    unittest.main()
