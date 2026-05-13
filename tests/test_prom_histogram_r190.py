"""R190 / Cycle 5 · Prometheus Histogram exposition foundational tests。

背景
----
CR#18 §4.6 把「``_format_prom_metric_family`` 不支持 histogram 类型」标
为 foundational gap —— 阻塞所有 latency / size / depth distribution
metric 的暴露。CR#18 §7 排序里把 histogram 支持列为 cycle 5 第一优先级
（≥ R190 / R191 / R192 都依赖此 foundational 实现）。

R190 同时交付两件事：

1. **``_format_prom_histogram_family`` helper** —— 在 ``system.py`` 模
   块级与 ``_format_prom_metric_family`` / ``_format_prom_value`` 同级，
   渲染 Prometheus 0.0.4 exposition format 的 histogram family（``_bucket{le}``
   + ``_sum`` + ``_count`` 三件套，HELP/TYPE 各只 emit 一次）；

2. **``aiia_mcp_tool_call_duration_seconds`` 指标** —— ``ToolCallCounter
   Middleware`` 在 ``on_call_tool`` 钩子里加 ``time.monotonic()`` 计时，
   把耗时累计到 ``mcp_tool_call_metrics.py`` 的 ``_latency_state``，
   ``/metrics`` 端点通过 ``get_mcp_tool_call_latency_snapshot()`` + 新
   helper 渲染。

关键设计取舍（与 CR#18 §4.1 推荐一致）
=====================================
- **桶选择**：``(0.1, 0.5, 1.0, 5.0, 30.0, 120.0, 300.0, 600.0)`` + 隐
  式 ``+Inf``。覆盖「即时反馈 → 分钟级长任务 → ``auto_resubmit_timeout``
  边界」整个语义范围；
- **``time.monotonic()`` 而不是 ``time.time()``**：避免 NTP / 夏令时
  跳变让 latency 出现负值；
- **本地实现，不引入 ``prometheus_client``**：项目已有 ``_format_prom_*``
  极简渲染器，引入 ``prometheus_client`` 只为 histogram 显得过重，而且
  multiprocess collector 在 web_ui 子进程会出问题；
- **复用 ``_counter_lock``**：避免双锁死锁——histogram 读写跟 counter
  读写在同一个临界区，复用同一把锁不增加 contention 面（middleware 单
  路径访问）；
- **不存原始观测值** —— 只存 cumulative bucket counts + sum + count，
  零额外内存（每 (tool, status) ~80 bytes 状态，不随调用量增长）；
- **caller-side count 冗余传入** —— ``_format_prom_histogram_family``
  接受 ``count`` 参数而不是自动 ``buckets[+Inf]`` 推断；用作 sanity
  check 让渲染时 spec-violation 显式暴露而不是静默修复。

测试覆盖（24 cases / 5 invariant classes）：

1. **``_format_prom_histogram_family`` helper**（8 cases）
2. **``ToolCallCounterMiddleware`` 写 latency**（4 cases）
3. **``get_mcp_tool_call_latency_snapshot`` 行为**（4 cases）
4. **``_record_latency`` 边界处理**（4 cases）
5. **``_render_prometheus_metrics`` 端到端集成**（4 cases）
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent import mcp_tool_call_metrics as mtcm
from ai_intervention_agent.web_ui_routes import system as system_module

# ---------------------------------------------------------------------------
# 1. _format_prom_histogram_family helper
# ---------------------------------------------------------------------------


class TestFormatPromHistogramFamily(unittest.TestCase):
    def test_returns_empty_on_empty_observations(self) -> None:
        # 与 ``_format_prom_metric_family`` 行为对齐：空 list → 空串
        self.assertEqual(
            system_module._format_prom_histogram_family(
                "x", help_text="dummy", observations=[]
            ),
            "",
        )

    def test_emits_help_and_type_once_for_single_observation(self) -> None:
        out = system_module._format_prom_histogram_family(
            "test_metric",
            help_text="a test histogram",
            observations=[
                (
                    {"label": "v"},
                    {0.5: 1, 1.0: 2, math.inf: 2},
                    2,
                    1.4,
                )
            ],
        )
        # HELP 出现且仅出现 1 次
        self.assertEqual(out.count("# HELP test_metric"), 1)
        # TYPE 出现且仅出现 1 次
        self.assertEqual(out.count("# TYPE test_metric histogram"), 1)

    def test_emits_help_and_type_once_for_multiple_observations(self) -> None:
        # 关键回归点：R187 的 latent bug 是 multi-label 时 HELP/TYPE 重复
        out = system_module._format_prom_histogram_family(
            "test_metric",
            help_text="x",
            observations=[
                (
                    {"tool": "a"},
                    {0.1: 1, math.inf: 1},
                    1,
                    0.05,
                ),
                (
                    {"tool": "b"},
                    {0.1: 0, math.inf: 1},
                    1,
                    0.5,
                ),
            ],
        )
        self.assertEqual(out.count("# HELP test_metric"), 1)
        self.assertEqual(out.count("# TYPE test_metric histogram"), 1)

    def test_buckets_emit_in_ascending_order_with_inf_last(self) -> None:
        out = system_module._format_prom_histogram_family(
            "m",
            help_text="x",
            observations=[
                (
                    None,
                    # 故意 dict 乱序插入
                    {math.inf: 3, 0.5: 1, 1.0: 2, 0.1: 0},
                    3,
                    1.4,
                )
            ],
        )
        bucket_lines = [ln for ln in out.splitlines() if "_bucket" in ln]
        # 顺序检验：0.1 → 0.5 → 1.0 → +Inf
        self.assertIn('le="0.1"', bucket_lines[0])
        self.assertIn('le="0.5"', bucket_lines[1])
        self.assertIn('le="1.0"', bucket_lines[2])
        self.assertIn('le="+Inf"', bucket_lines[3])

    def test_emits_sum_and_count_per_observation(self) -> None:
        out = system_module._format_prom_histogram_family(
            "m",
            help_text="x",
            observations=[
                (
                    {"tool": "a"},
                    {0.1: 0, math.inf: 5},
                    5,
                    2.5,
                )
            ],
        )
        self.assertIn('m_sum{tool="a"} 2.5', out)
        self.assertIn('m_count{tool="a"} 5', out)

    def test_inf_bucket_auto_added_if_missing(self) -> None:
        # caller bug：忘传 +Inf 桶。helper 应该补上而不是输出残缺 metric
        out = system_module._format_prom_histogram_family(
            "m",
            help_text="x",
            observations=[
                (
                    None,
                    {0.1: 0, 0.5: 1, 1.0: 2},  # 缺 +Inf
                    2,
                    1.4,
                )
            ],
        )
        self.assertIn('le="+Inf"', out)

    def test_le_label_merged_with_base_labels(self) -> None:
        out = system_module._format_prom_histogram_family(
            "m",
            help_text="x",
            observations=[
                (
                    {"tool": "a", "status": "success"},
                    {0.1: 1, math.inf: 1},
                    1,
                    0.05,
                )
            ],
        )
        # ``le`` 与其他 label 拼在同一个 {} 内
        self.assertIn(
            'm_bucket{le="0.1",tool="a",status="success"} 1',
            out,
        )

    def test_sum_uses_float_formatting(self) -> None:
        # _format_prom_value 对 float 保留小数；整数耗时（罕见）保持 int 形式
        out = system_module._format_prom_histogram_family(
            "m",
            help_text="x",
            observations=[
                (
                    None,
                    {0.1: 0, math.inf: 1},
                    1,
                    1.0,  # 注意：是 float 1.0
                )
            ],
        )
        # 至少要出现 m_sum + 1.0/1（任一）
        sum_line = next(ln for ln in out.splitlines() if "m_sum" in ln)
        self.assertTrue(
            "1.0" in sum_line or " 1\n" in sum_line + "\n",
            f"unexpected _sum format: {sum_line!r}",
        )


# ---------------------------------------------------------------------------
# 2. ToolCallCounterMiddleware writes latency
# ---------------------------------------------------------------------------


class _FakeContext:
    """最小化的 FastMCP MiddlewareContext mock"""

    def __init__(self, tool_name: str) -> None:
        self.message = type("Msg", (), {"name": tool_name})()


class TestMiddlewareLatencyRecording(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        mtcm.reset_mcp_tool_call_stats()

    def tearDown(self) -> None:
        mtcm.reset_mcp_tool_call_stats()

    async def test_success_path_records_latency(self) -> None:
        async def call_next(ctx: Any) -> str:
            return "ok"

        mw = mtcm.ToolCallCounterMiddleware()
        await mw.on_call_tool(_FakeContext("t1"), call_next)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        self.assertIn(("t1", "success"), snap)
        self.assertEqual(snap[("t1", "success")]["count"], 1)

    async def test_failure_path_records_latency(self) -> None:
        async def call_next(ctx: Any) -> str:
            raise RuntimeError("simulated")

        mw = mtcm.ToolCallCounterMiddleware()
        with self.assertRaises(RuntimeError):
            await mw.on_call_tool(_FakeContext("t2"), call_next)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        self.assertIn(("t2", "failure"), snap)
        self.assertEqual(snap[("t2", "failure")]["count"], 1)

    async def test_multiple_calls_accumulate_count_and_sum(self) -> None:
        async def call_next(ctx: Any) -> str:
            return "ok"

        mw = mtcm.ToolCallCounterMiddleware()
        for _ in range(5):
            await mw.on_call_tool(_FakeContext("t3"), call_next)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        state = snap[("t3", "success")]
        self.assertEqual(state["count"], 5)
        self.assertGreater(state["sum_seconds"], 0)

    async def test_failure_latency_still_increments_count_on_exception(self) -> None:
        # 关键不变量：failure 路径下 latency 仍要计入——监控才能区分
        # 「failure 慢」vs「failure 立即拒绝」
        async def call_next(ctx: Any) -> str:
            import asyncio

            await asyncio.sleep(0.02)
            raise ValueError("boom")

        mw = mtcm.ToolCallCounterMiddleware()
        with self.assertRaises(ValueError):
            await mw.on_call_tool(_FakeContext("t4"), call_next)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        state = snap[("t4", "failure")]
        self.assertEqual(state["count"], 1)
        self.assertGreaterEqual(state["sum_seconds"], 0.02)


# ---------------------------------------------------------------------------
# 3. get_mcp_tool_call_latency_snapshot behavior
# ---------------------------------------------------------------------------


class TestLatencySnapshot(unittest.TestCase):
    def setUp(self) -> None:
        mtcm.reset_mcp_tool_call_stats()

    def tearDown(self) -> None:
        mtcm.reset_mcp_tool_call_stats()

    def test_empty_when_no_recordings(self) -> None:
        self.assertEqual(mtcm.get_mcp_tool_call_latency_snapshot(), {})

    def test_buckets_include_inf_key(self) -> None:
        with mtcm._counter_lock:
            mtcm._record_latency("a", "success", 0.5)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        self.assertIn(float("inf"), snap[("a", "success")]["buckets"])

    def test_inf_bucket_value_equals_count(self) -> None:
        # 不变量：snapshot 内 ``buckets[+Inf]`` == ``count``
        with mtcm._counter_lock:
            for d in (0.05, 0.5, 5.0, 100.0):
                mtcm._record_latency("a", "success", d)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        state = snap[("a", "success")]
        self.assertEqual(state["buckets"][float("inf")], state["count"])

    def test_snapshot_is_deep_copy_not_alias(self) -> None:
        with mtcm._counter_lock:
            mtcm._record_latency("a", "success", 0.5)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        snap[("a", "success")]["count"] = 9999
        snap[("a", "success")]["buckets"][0.5] = 9999
        # 内部状态不应被外部修改污染
        new_snap = mtcm.get_mcp_tool_call_latency_snapshot()
        self.assertEqual(new_snap[("a", "success")]["count"], 1)
        self.assertEqual(new_snap[("a", "success")]["buckets"][0.5], 1)


# ---------------------------------------------------------------------------
# 4. _record_latency edge cases
# ---------------------------------------------------------------------------


class TestRecordLatencyEdgeCases(unittest.TestCase):
    def setUp(self) -> None:
        mtcm.reset_mcp_tool_call_stats()

    def tearDown(self) -> None:
        mtcm.reset_mcp_tool_call_stats()

    def test_negative_duration_silently_dropped(self) -> None:
        with mtcm._counter_lock:
            mtcm._record_latency("a", "success", -0.5)
        # 不应记录任何状态
        self.assertEqual(mtcm.get_mcp_tool_call_latency_snapshot(), {})

    def test_zero_duration_recorded_in_smallest_bucket(self) -> None:
        with mtcm._counter_lock:
            mtcm._record_latency("a", "success", 0.0)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        state = snap[("a", "success")]
        self.assertEqual(state["count"], 1)
        # 0.0 ≤ 0.1 → 应进 0.1 桶（并 cumulative 进所有更高桶）
        self.assertEqual(state["buckets"][0.1], 1)

    def test_unknown_status_value_still_recorded(self) -> None:
        # docstring 说接受任何 status 字符串——未来加 ``timeout`` /
        # ``rate_limited`` 不需要回头改本函数
        with mtcm._counter_lock:
            mtcm._record_latency("a", "timeout", 1.5)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        self.assertIn(("a", "timeout"), snap)

    def test_very_large_duration_only_inf_bucket_increments(self) -> None:
        with mtcm._counter_lock:
            mtcm._record_latency("a", "success", 99999.0)
        snap = mtcm.get_mcp_tool_call_latency_snapshot()
        state = snap[("a", "success")]
        # 所有有限桶都应该是 0（99999 > 600）
        for upper in (0.1, 0.5, 1.0, 5.0, 30.0, 120.0, 300.0, 600.0):
            self.assertEqual(
                state["buckets"][upper],
                0,
                f"bucket {upper} unexpectedly non-zero",
            )
        # +Inf 桶 = count = 1
        self.assertEqual(state["buckets"][float("inf")], 1)


# ---------------------------------------------------------------------------
# 5. End-to-end: /metrics renders histogram
# ---------------------------------------------------------------------------


class TestRenderPrometheusMetricsIntegration(unittest.TestCase):
    def setUp(self) -> None:
        mtcm.reset_mcp_tool_call_stats()

    def tearDown(self) -> None:
        mtcm.reset_mcp_tool_call_stats()

    def test_no_histogram_output_when_no_recordings(self) -> None:
        text = system_module._render_prometheus_metrics()
        self.assertNotIn("aiia_mcp_tool_call_duration_seconds", text)

    def test_histogram_appears_after_recording(self) -> None:
        with mtcm._counter_lock:
            mtcm._counter[("interactive_feedback", "success")] = 2
            mtcm._record_latency("interactive_feedback", "success", 0.5)
            mtcm._record_latency("interactive_feedback", "success", 5.0)
        text = system_module._render_prometheus_metrics()
        self.assertIn("aiia_mcp_tool_call_duration_seconds_bucket", text)
        self.assertIn("aiia_mcp_tool_call_duration_seconds_sum", text)
        self.assertIn("aiia_mcp_tool_call_duration_seconds_count", text)

    def test_help_and_type_unique_in_full_metrics_output(self) -> None:
        # 关键回归点：R187 之前 multi-sample family 会重复 HELP/TYPE
        with mtcm._counter_lock:
            mtcm._counter[("t1", "success")] = 1
            mtcm._counter[("t2", "success")] = 1
            mtcm._record_latency("t1", "success", 0.5)
            mtcm._record_latency("t2", "success", 5.0)
        text = system_module._render_prometheus_metrics()
        self.assertEqual(text.count("# HELP aiia_mcp_tool_call_duration_seconds "), 1)
        self.assertEqual(
            text.count("# TYPE aiia_mcp_tool_call_duration_seconds histogram"),
            1,
        )

    def test_metric_endpoint_survives_latency_snapshot_failure(self) -> None:
        # 子系统故障不应让 /metrics 5xx——与 R187 counter 失败的优雅
        # 降级模式一致（[R-187] try/except 块）
        with patch.object(
            mtcm,
            "get_mcp_tool_call_latency_snapshot",
            side_effect=RuntimeError("blown up"),
        ):
            # 不应 raise
            text = system_module._render_prometheus_metrics()
        # 整体输出仍要包含其他指标（至少 process uptime 行 + 非空）
        self.assertIn("aiia_uptime_seconds", text)
        # latency histogram 整体被跳过，不应出现部分残缺输出
        self.assertNotIn("aiia_mcp_tool_call_duration_seconds", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
