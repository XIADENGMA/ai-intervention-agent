"""R187 / T2 · MCP tool call counter middleware 契约测试。

背景
----
R186 / T1 在 ``/api/system/metrics`` 暴露了 Prometheus exposition format
的整体可观测面。但是 MCP tool 本身的「调用次数 / 成功率」一直没有
正向计数（R37 ``get_mcp_error_stats()`` 只统计 ``{error_type}:{method}``
负向计数）。R187 补齐这一面：

1. 新增 ``src/ai_intervention_agent/mcp_tool_call_metrics.py`` 模块，
   提供 ``ToolCallCounterMiddleware`` + ``get_mcp_tool_call_stats()``
   + ``reset_mcp_tool_call_stats()``；
2. 在 ``server.py`` 把 middleware 注册到 ``mcp.middleware`` 位置 2
   （RateLimiting 之后、DereferenceRefs/Timing/Logging 之前）；
3. 在 ``web_ui_routes/system.py`` 的 ``_render_prometheus_metrics()`` 加
   ``aiia_mcp_tool_calls_total{tool=...,status=success|failure}`` 计数；
4. 顺手修一个 R186 latent bug：旧实现对每个 ``notif per-provider``
   sample 都重复发 ``# HELP/# TYPE`` 行，让严格 Prometheus parser
   报 ``second TYPE for metric`` 错误。改用新 helper
   ``_format_prom_metric_family`` 一次性发 family（HELP/TYPE 各一行 +
   N 个 value 行）。

测试覆盖（17 cases / 4 invariant classes）：

1. **module-level counter 行为**（5 cases）
   - 初始空 dict
   - 累加 success / failure / 多 tool
   - reset 清空
   - 返回值是 copy（外部修改不污染内部）

2. **Middleware 在 mcp.middleware 链中位置 + 行为**（3 cases）
   - server.py 把实例注册进 mcp.middleware
   - on_call_tool 成功路径 → success +1
   - on_call_tool 异常路径 → failure +1 + 异常被重抛

3. **`_format_prom_metric_family` helper**（4 cases）
   - 空 samples 返回空串
   - 单 sample 输出 HELP/TYPE/value 三件套
   - 多 sample 共享 HELP/TYPE（HELP+TYPE 各一行 + N value 行）
   - 标签转义

4. **R186 latent bug fix: prom 输出 HELP/TYPE 去重**（5 cases）
   - notification per-provider 不再重复 HELP/TYPE
   - MCP tool call counter 不再重复 HELP/TYPE
   - prom 输出 ``aiia_mcp_tool_calls_total`` 含 success+failure 两个 sample
   - prom 输出格式可被严格 parser 接受（每个 metric name 的 HELP/TYPE
     最多出现一次）
   - 当无 tool 被调用过时，``aiia_mcp_tool_calls_total`` family 完全不出现
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent import mcp_tool_call_metrics as mtcm
from ai_intervention_agent.web_ui_routes import system as system_module


def _reset_counter_state() -> None:
    """每个 test setUp 用——清空内部 ``Counter`` 防止跨测试串扰。"""
    mtcm.reset_mcp_tool_call_stats()


# ---------------------------------------------------------------------------
# 1. module-level counter 行为
# ---------------------------------------------------------------------------


class TestCounterBehaviour(unittest.TestCase):
    def setUp(self) -> None:
        _reset_counter_state()

    def test_initial_state_is_empty_dict(self) -> None:
        self.assertEqual(mtcm.get_mcp_tool_call_stats(), {})

    def test_increment_success_appears_in_stats(self) -> None:
        with mtcm._counter_lock:
            mtcm._counter[("interactive_feedback", "success")] += 3
        stats = mtcm.get_mcp_tool_call_stats()
        self.assertIn("interactive_feedback", stats)
        self.assertEqual(stats["interactive_feedback"]["success"], 3)
        self.assertEqual(stats["interactive_feedback"]["failure"], 0)
        self.assertEqual(stats["interactive_feedback"]["total"], 3)

    def test_multiple_tools_are_isolated(self) -> None:
        with mtcm._counter_lock:
            mtcm._counter[("tool_a", "success")] += 5
            mtcm._counter[("tool_a", "failure")] += 1
            mtcm._counter[("tool_b", "success")] += 7
        stats = mtcm.get_mcp_tool_call_stats()
        self.assertEqual(stats["tool_a"], {"success": 5, "failure": 1, "total": 6})
        self.assertEqual(stats["tool_b"], {"success": 7, "failure": 0, "total": 7})

    def test_reset_clears_all_counters(self) -> None:
        with mtcm._counter_lock:
            mtcm._counter[("foo", "success")] += 10
        self.assertNotEqual(mtcm.get_mcp_tool_call_stats(), {})
        mtcm.reset_mcp_tool_call_stats()
        self.assertEqual(mtcm.get_mcp_tool_call_stats(), {})

    def test_returned_dict_is_independent_copy(self) -> None:
        # 调用者修改返回值不应污染内部 state
        with mtcm._counter_lock:
            mtcm._counter[("foo", "success")] += 1
        first = mtcm.get_mcp_tool_call_stats()
        first["foo"]["success"] = 9999  # 故意搞坏
        second = mtcm.get_mcp_tool_call_stats()
        self.assertEqual(
            second["foo"]["success"],
            1,
            "get_mcp_tool_call_stats 必须返回 copy；外部修改不能反向污染内部",
        )


# ---------------------------------------------------------------------------
# 2. Middleware 行为
# ---------------------------------------------------------------------------


class TestMiddlewareBehaviour(unittest.TestCase):
    def setUp(self) -> None:
        _reset_counter_state()
        self.mw = mtcm.ToolCallCounterMiddleware()

    def _make_context(self, tool_name: str) -> Any:
        # 简化 mock：context.message.name = tool_name；其他字段 middleware 不读
        ctx = MagicMock()
        ctx.message.name = tool_name
        return ctx

    def test_successful_call_increments_success(self) -> None:
        ctx = self._make_context("interactive_feedback")
        call_next = AsyncMock(return_value="some result")

        result = asyncio.run(self.mw.on_call_tool(ctx, call_next))

        self.assertEqual(result, "some result")
        stats = mtcm.get_mcp_tool_call_stats()
        self.assertEqual(stats["interactive_feedback"]["success"], 1)
        self.assertEqual(stats["interactive_feedback"]["failure"], 0)

    def test_exception_increments_failure_and_reraises(self) -> None:
        ctx = self._make_context("interactive_feedback")
        call_next = AsyncMock(side_effect=ValueError("simulated handler crash"))

        with self.assertRaises(ValueError):
            asyncio.run(self.mw.on_call_tool(ctx, call_next))

        # 异常被重抛 + failure 计数 +1
        stats = mtcm.get_mcp_tool_call_stats()
        self.assertEqual(stats["interactive_feedback"]["failure"], 1)
        self.assertEqual(stats["interactive_feedback"]["success"], 0)

    def test_middleware_registered_in_server_mcp_chain(self) -> None:
        # server.py 导入即注册——本测试静态检查链上确实有一个
        # ToolCallCounterMiddleware 实例，且在合理位置（位置 2）
        from ai_intervention_agent import server

        chain = list(server.mcp.middleware)
        counter_indices = [
            i
            for i, mw in enumerate(chain)
            if isinstance(mw, mtcm.ToolCallCounterMiddleware)
        ]
        self.assertEqual(
            len(counter_indices),
            1,
            f"mcp.middleware 必须恰好包含一个 ToolCallCounterMiddleware；当前: {counter_indices}",
        )
        # 位置应该在 ErrorHandling（0）+ RateLimiting（1）之后，
        # 也就是 index == 2（FastMCP 反向折叠，列表前 = 外层）
        self.assertEqual(
            counter_indices[0],
            2,
            "ToolCallCounterMiddleware 应该挂在 mcp.middleware 位置 2 "
            "（ErrorHandling/RateLimiting 之后、DereferenceRefs/Timing/Logging 之前）",
        )


# ---------------------------------------------------------------------------
# 3. _format_prom_metric_family helper
# ---------------------------------------------------------------------------


class TestFormatPromMetricFamily(unittest.TestCase):
    def test_empty_samples_returns_empty_string(self) -> None:
        out = system_module._format_prom_metric_family(
            "aiia_test_total",
            help_text="x",
            metric_type="counter",
            samples=[],
        )
        self.assertEqual(out, "")

    def test_single_sample_emits_help_type_value(self) -> None:
        out = system_module._format_prom_metric_family(
            "aiia_test_total",
            help_text="A test counter.",
            metric_type="counter",
            samples=[({"label": "value"}, 42)],
        )
        self.assertIn("# HELP aiia_test_total A test counter.\n", out)
        self.assertIn("# TYPE aiia_test_total counter\n", out)
        self.assertIn('aiia_test_total{label="value"} 42\n', out)

    def test_multiple_samples_share_single_help_type_block(self) -> None:
        out = system_module._format_prom_metric_family(
            "aiia_test_total",
            help_text="A test counter.",
            metric_type="counter",
            samples=[
                ({"label": "a"}, 1),
                ({"label": "b"}, 2),
                ({"label": "c"}, 3),
            ],
        )
        self.assertEqual(out.count("# HELP aiia_test_total"), 1)
        self.assertEqual(out.count("# TYPE aiia_test_total"), 1)
        # value 行 3 个都出现
        self.assertIn('aiia_test_total{label="a"} 1\n', out)
        self.assertIn('aiia_test_total{label="b"} 2\n', out)
        self.assertIn('aiia_test_total{label="c"} 3\n', out)

    def test_labels_are_escaped(self) -> None:
        out = system_module._format_prom_metric_family(
            "aiia_test_gauge",
            help_text="x",
            metric_type="gauge",
            samples=[({"path": 'C:\\foo "bar"'}, 1)],
        )
        self.assertIn('aiia_test_gauge{path="C:\\\\foo \\"bar\\""} 1\n', out)


# ---------------------------------------------------------------------------
# 4. R186 latent bug fix: prom 输出每个 metric 最多一份 HELP/TYPE
# ---------------------------------------------------------------------------


class TestPromOutputNoDuplicateHelpType(unittest.TestCase):
    """守住「同一 metric name 的 HELP/TYPE 行最多出现一次」严格 Prometheus
    parser 兼容性契约（VictoriaMetrics / Cortex / 最新 prom 会报错）。"""

    def setUp(self) -> None:
        _reset_counter_state()

    def test_render_has_no_duplicate_help_lines(self) -> None:
        # 模拟多个 tool 都被调用过——这会触发 aiia_mcp_tool_calls_total
        # 的多 sample 场景（与 notification per-provider 同理）
        with mtcm._counter_lock:
            mtcm._counter[("tool_a", "success")] += 1
            mtcm._counter[("tool_a", "failure")] += 1
            mtcm._counter[("tool_b", "success")] += 1

        out = system_module._render_prometheus_metrics()
        import re

        help_lines = re.findall(r"^# HELP (\S+) ", out, re.MULTILINE)
        type_lines = re.findall(r"^# TYPE (\S+) ", out, re.MULTILINE)

        from collections import Counter as PyCounter

        help_counter = PyCounter(help_lines)
        type_counter = PyCounter(type_lines)
        duped_help = {n: c for n, c in help_counter.items() if c > 1}
        duped_type = {n: c for n, c in type_counter.items() if c > 1}

        self.assertEqual(
            duped_help,
            {},
            f"以下 metric 的 HELP 行重复（严格 prom parser 会报错）: {duped_help}",
        )
        self.assertEqual(
            duped_type,
            {},
            f"以下 metric 的 TYPE 行重复（严格 prom parser 会报错）: {duped_type}",
        )

    def test_mcp_tool_calls_metric_emits_when_counter_has_data(self) -> None:
        with mtcm._counter_lock:
            mtcm._counter[("interactive_feedback", "success")] += 7
            mtcm._counter[("interactive_feedback", "failure")] += 2

        out = system_module._render_prometheus_metrics()
        self.assertIn("# HELP aiia_mcp_tool_calls_total", out)
        self.assertIn("# TYPE aiia_mcp_tool_calls_total counter", out)
        self.assertIn(
            'aiia_mcp_tool_calls_total{tool="interactive_feedback",status="success"} 7',
            out,
        )
        self.assertIn(
            'aiia_mcp_tool_calls_total{tool="interactive_feedback",status="failure"} 2',
            out,
        )

    def test_mcp_tool_calls_metric_omitted_when_no_data(self) -> None:
        # 没有 tool 被调用过 → 整个 family 不出现（避免 noise）
        out = system_module._render_prometheus_metrics()
        self.assertNotIn("aiia_mcp_tool_calls_total", out)

    def test_pii_not_leaked_in_mcp_tool_metrics(self) -> None:
        # tool 名 + status 是公开元数据，但 PII 关键字不应出现
        with mtcm._counter_lock:
            mtcm._counter[("interactive_feedback", "success")] += 1
        out = system_module._render_prometheus_metrics()
        for pii in ("bark_device_key", "api_key", "password", "token"):
            self.assertNotIn(
                pii,
                out,
                f"PII 关键字 {pii!r} 不能出现在 /metrics 输出中",
            )

    def test_render_function_does_not_raise_when_counter_state_is_unexpected(
        self,
    ) -> None:
        # 故意往 counter 里塞一个奇怪的 key（非预期 status 值）；
        # _render_prometheus_metrics 应当静默忽略而不是 raise
        with mtcm._counter_lock:
            mtcm._counter[("tool_x", "unexpected_status")] += 1
        try:
            out = system_module._render_prometheus_metrics()
        except Exception as exc:
            self.fail(f"_render_prometheus_metrics 不应该 raise：{exc!r}")
        # tool_x 的 unexpected_status 不会被渲染（success/failure 是 0）
        self.assertNotIn('status="unexpected_status"', out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
