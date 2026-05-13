"""R191 / Cycle 5 · Notification provider latency histogram tests。

背景
----
R190 落地了 ``_format_prom_histogram_family`` foundational helper +
``aiia_mcp_tool_call_duration_seconds`` 第一组 histogram 用户。CR#18 §7
排序里 R191 紧随其后：「notification provider 也有 latency_ms_total /
latency_ms_count 两个累计字段，能算 average，**不能算 percentile**」。

R190 已经验证 histogram 渲染 helper 自身正确。R191 的测试聚焦于：

1. **``NotificationManager._record_provider_latency_bucket`` 行为**：
   accumulator 逻辑正确（count / sum / bucket cumulative）；
2. **``get_provider_latency_histograms_snapshot`` 形态**：与
   ``get_mcp_tool_call_latency_snapshot`` 对齐（包含 ``+Inf`` 桶，
   深 copy，空状态时返回空 dict）；
3. **``_safe_notification_latency_histograms`` 防御性**：单例缺失 /
   方法 raise → 返回空 dict 不让 /metrics 5xx；
4. **``_render_prometheus_metrics`` 集成**：渲染出来的 metric name
   == ``aiia_notification_send_duration_seconds``，HELP/TYPE 各一次，
   per-provider 多 sample 不重复 HELP/TYPE。

为什么不复用 R190 的测试套件？两者作用对象不同——R190 是 mcp tool
side（module-level state），R191 是 notification side（NotificationManager
instance state）。共享 helper（``_format_prom_histogram_family``）的契约
已经在 R190 测试套件里固化，本套件只覆盖 R191 引入的新代码路径。

测试覆盖（16 cases / 4 invariant classes）：

1. ``_record_provider_latency_bucket`` 累加行为（5 cases）
2. ``get_provider_latency_histograms_snapshot`` 形态（4 cases）
3. ``_safe_notification_latency_histograms`` 防御（3 cases）
4. ``_render_prometheus_metrics`` 集成（4 cases）
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.notification_manager import notification_manager
from ai_intervention_agent.web_ui_routes import system as system_module


def _reset_provider_histograms() -> None:
    """重置 NotificationManager 单例的 provider latency histograms。"""
    with notification_manager._stats_lock:
        notification_manager._provider_latency_histograms.clear()


# ---------------------------------------------------------------------------
# 1. _record_provider_latency_bucket accumulator behavior
# ---------------------------------------------------------------------------


class TestRecordProviderLatencyBucket(unittest.TestCase):
    def setUp(self) -> None:
        _reset_provider_histograms()

    def tearDown(self) -> None:
        _reset_provider_histograms()

    def test_single_recording_creates_state(self) -> None:
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket("bark", 0.5)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        self.assertIn("bark", snap)
        self.assertEqual(snap["bark"]["count"], 1)
        self.assertAlmostEqual(snap["bark"]["sum_seconds"], 0.5)

    def test_cumulative_buckets_increment_correctly(self) -> None:
        # 关键不变量：duration d 应该让所有 ``upper >= d`` 的 bucket +1。
        # **不**硬编码具体桶值（R196 改动会调整 notification provider
        # 桶分布），改用 ``_DEFAULT_LATENCY_BUCKETS_SECONDS`` 模板读取。
        bucket_template = notification_manager._DEFAULT_LATENCY_BUCKETS_SECONDS
        # 选用一个落在桶模板某个桶里的 duration——找中位桶
        sample_duration = bucket_template[len(bucket_template) // 2]
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket(
                "bark", sample_duration
            )
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        bk = snap["bark"]["buckets"]

        # 对每个桶 upper 检查 cumulative 行为
        for upper in bucket_template:
            expected = 1 if sample_duration <= upper else 0
            self.assertEqual(
                bk[upper],
                expected,
                f"bucket {upper}: duration {sample_duration} expected count={expected}, got {bk[upper]}",
            )
        # +Inf 桶 = count = 1
        self.assertEqual(bk[float("inf")], 1)

    def test_multiple_recordings_same_provider_accumulate(self) -> None:
        # 选三个 duration：分别落在桶模板的不同段位
        bucket_template = notification_manager._DEFAULT_LATENCY_BUCKETS_SECONDS
        # d1 < bucket[0] → 进所有桶
        # d2 中段
        # d3 大于所有有限桶 → 仅 +Inf
        d1 = bucket_template[0] / 2.0  # 比最小桶还小
        d2 = bucket_template[len(bucket_template) // 2]
        d3 = bucket_template[-1] + 1.0  # 比最大桶还大
        with notification_manager._stats_lock:
            for d in (d1, d2, d3):
                notification_manager._record_provider_latency_bucket("bark", d)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        bk = snap["bark"]["buckets"]
        self.assertEqual(snap["bark"]["count"], 3)
        self.assertAlmostEqual(snap["bark"]["sum_seconds"], d1 + d2 + d3)

        # d1 ≤ 第一个桶 → 至少进第一个桶 (累计计数 1)
        self.assertEqual(bk[bucket_template[0]], 1)
        # d2 落在中间 → 至少 d1 + d2 = 2 落在中间桶
        self.assertEqual(bk[d2], 2)
        # d3 超出所有有限桶 → 最大有限桶仅捕获 d1 + d2 = 2
        self.assertEqual(bk[bucket_template[-1]], 2)
        # +Inf 桶捕获全部 3 个
        self.assertEqual(bk[float("inf")], 3)

    def test_multiple_providers_independent_state(self) -> None:
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket("bark", 0.5)
            notification_manager._record_provider_latency_bucket("web", 10.0)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        self.assertIn("bark", snap)
        self.assertIn("web", snap)
        # web 的 0.5 桶应该是 0（web 没收到 < 0.5s 的样本）
        self.assertEqual(snap["web"]["buckets"][0.5], 0)
        # bark 的 0.5 桶应该是 1
        self.assertEqual(snap["bark"]["buckets"][0.5], 1)

    def test_negative_duration_silently_dropped(self) -> None:
        # 时钟跳变保护：负值直接丢弃，不污染 sum
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket("bark", -0.5)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        self.assertEqual(snap, {}, "负 duration 不应创建状态")


# ---------------------------------------------------------------------------
# 2. get_provider_latency_histograms_snapshot shape
# ---------------------------------------------------------------------------


class TestProviderLatencySnapshot(unittest.TestCase):
    def setUp(self) -> None:
        _reset_provider_histograms()

    def tearDown(self) -> None:
        _reset_provider_histograms()

    def test_empty_dict_when_no_recordings(self) -> None:
        self.assertEqual(
            notification_manager.get_provider_latency_histograms_snapshot(), {}
        )

    def test_snapshot_includes_inf_bucket_key(self) -> None:
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket("bark", 0.5)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        self.assertIn(float("inf"), snap["bark"]["buckets"])

    def test_inf_bucket_value_equals_count(self) -> None:
        with notification_manager._stats_lock:
            for d in (0.05, 0.5, 5.0, 100.0):
                notification_manager._record_provider_latency_bucket("bark", d)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        state = snap["bark"]
        self.assertEqual(state["buckets"][float("inf")], state["count"])

    def test_snapshot_is_deep_copy(self) -> None:
        # 外部修改 snapshot 不应污染内部状态
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket("bark", 0.5)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        snap["bark"]["count"] = 9999
        snap["bark"]["buckets"][0.5] = 9999

        new_snap = notification_manager.get_provider_latency_histograms_snapshot()
        self.assertEqual(new_snap["bark"]["count"], 1)
        self.assertEqual(new_snap["bark"]["buckets"][0.5], 1)


# ---------------------------------------------------------------------------
# 3. _safe_notification_latency_histograms defensive behavior
# ---------------------------------------------------------------------------


class TestSafeWrapperDefensive(unittest.TestCase):
    def setUp(self) -> None:
        _reset_provider_histograms()

    def tearDown(self) -> None:
        _reset_provider_histograms()

    def test_returns_data_when_manager_works(self) -> None:
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket("bark", 0.5)
        result = system_module._safe_notification_latency_histograms()
        self.assertIn("bark", result)

    def test_returns_empty_dict_when_method_raises(self) -> None:
        with patch.object(
            notification_manager,
            "get_provider_latency_histograms_snapshot",
            side_effect=RuntimeError("blown up"),
        ):
            result = system_module._safe_notification_latency_histograms()
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_method_returns_non_dict(self) -> None:
        # 防御性：单例返回错误类型也不应崩溃
        with patch.object(
            notification_manager,
            "get_provider_latency_histograms_snapshot",
            return_value="not a dict",
        ):
            result = system_module._safe_notification_latency_histograms()
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# 4. _render_prometheus_metrics integration
# ---------------------------------------------------------------------------


class TestRenderMetricsIntegration(unittest.TestCase):
    def setUp(self) -> None:
        _reset_provider_histograms()

    def tearDown(self) -> None:
        _reset_provider_histograms()

    def test_no_histogram_output_when_no_recordings(self) -> None:
        text = system_module._render_prometheus_metrics()
        self.assertNotIn("aiia_notification_send_duration_seconds", text)

    def test_histogram_appears_after_recording(self) -> None:
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket("bark", 0.5)
        text = system_module._render_prometheus_metrics()
        self.assertIn("aiia_notification_send_duration_seconds_bucket", text)
        self.assertIn("aiia_notification_send_duration_seconds_sum", text)
        self.assertIn("aiia_notification_send_duration_seconds_count", text)
        # 标签包含 provider
        self.assertIn('provider="bark"', text)

    def test_help_and_type_unique_for_multi_provider_output(self) -> None:
        # 关键回归点：R187 latent bug 是 multi-sample family HELP/TYPE 重复
        with notification_manager._stats_lock:
            notification_manager._record_provider_latency_bucket("bark", 0.5)
            notification_manager._record_provider_latency_bucket("web", 5.0)
        text = system_module._render_prometheus_metrics()
        self.assertEqual(
            text.count("# HELP aiia_notification_send_duration_seconds "), 1
        )
        self.assertEqual(
            text.count("# TYPE aiia_notification_send_duration_seconds histogram"),
            1,
        )

    def test_metric_endpoint_survives_safe_wrapper_failure(self) -> None:
        # _safe_notification_latency_histograms raise → /metrics 不应 5xx
        with patch.object(
            system_module,
            "_safe_notification_latency_histograms",
            side_effect=RuntimeError("blown up"),
        ):
            text = system_module._render_prometheus_metrics()
        # 整体输出仍非空
        self.assertIn("aiia_uptime_seconds", text)
        # latency histogram 整段缺失但其他 metric 在
        self.assertNotIn("aiia_notification_send_duration_seconds", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
