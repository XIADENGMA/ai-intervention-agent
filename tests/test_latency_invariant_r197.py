"""R197 / Cycle 6 · Latency stats invariant tests.

Background
----------
``NotificationManager._send_single_notification`` 在同一 ``_stats_lock``
临界区内做两件事：

1. **R142 path** —— int-millisecond running totals 累加:
   ``stats["latency_ms_total"] += int(latency_ms)``
   ``stats["latency_ms_count"] += 1``

2. **R191 path** —— float-second histogram 累加:
   ``self._record_provider_latency_bucket(provider, latency_ms / 1000.0)``

两条 path 喂的是 *同一个* ``latency_ms`` sample，因此 R197 锁定它们的
running totals 之间的一致性：

- ``latency_ms_count`` (R142) **==** ``histogram[provider]["count"]`` (R191)
- ``latency_ms_total / 1000.0`` (R142) **≈** ``histogram[provider]["sum_seconds"]``
  (R191)  ← float 精度 (1e-9 tolerance) 容忍。

为什么这条 invariant 值得专门写测试 ?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CR#19 §4.2 指出: 如果未来 refactor 把两条 path 错开 (例如:
拆 async fan-out / 不同 lock 区 / 在某个 ``return`` 分支只跑一条),
dashboard 上 R142 average (``latency_ms_total / latency_ms_count / 1000``)
和 R191 histogram-derived average (``rate(_sum[5m]) / rate(_count[5m])``)
就会出现 divergence。这种 divergence **不**会被现有任何单元测试发现:

- R191 ``_record_provider_latency_bucket`` 测试 (R191 / cycle 5)
  只测自身累加逻辑;
- R142 latency stats 测试只测 R142 自身。

中间「这两条路径**是同一个事件源**」的 contract 没人 guard。R197 补
这个 caller-side invariant 测试。

测试覆盖 (10 cases / 4 invariant classes):

1. **数学不变量**: 直接 record N sample → count / sum 同步 (3 cases)
2. **Multi-provider isolation**: 每个 provider 独立累加, 互不污染 (2 cases)
3. **Source-level AST guard**: ``_send_single_notification`` 源码里
   R142 + R191 两条路径必须在同一 ``_stats_lock`` 块内, 且 R191
   call 紧跟 R142 自增之后 (3 cases)
4. **Edge case**: 0-sample baseline + 大量 sample 浮点累加精度 (2 cases)
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent import notification_manager as nm_module
from ai_intervention_agent.notification_manager import notification_manager

# 容忍 float 累加误差: 1e-9 远低于任何 dashboard / SLO 精度需求,
# 但又能 catch 真正的 "两条 path 喂了不同 sample" 错误。
_FLOAT_EPS = 1e-9


def _reset_provider_histograms() -> None:
    """重置 NotificationManager 单例的 provider latency histograms。"""
    with notification_manager._stats_lock:
        notification_manager._provider_latency_histograms.clear()


def _reset_provider_r142_stats(provider_name: str) -> None:
    """重置某个 provider 的 R142 latency_ms_total / latency_ms_count。"""
    with notification_manager._stats_lock:
        providers = notification_manager._stats.setdefault("providers", {})
        providers[provider_name] = {
            "attempts": 0,
            "success": 0,
            "failure": 0,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
            "last_latency_ms": None,
            "latency_ms_total": 0,
            "latency_ms_count": 0,
            "success_streak": 0,
            "failure_streak": 0,
        }


def _feed_sample(provider_name: str, latency_ms: int) -> None:
    """同时给两条 path 喂同一个 sample, 严格模拟 ``_send_single_notification``
    内 latency 记录块的行为 (同一 ``_stats_lock`` 临界区, R142 +
    R191 顺序)。"""
    with notification_manager._stats_lock:
        providers = notification_manager._stats.setdefault("providers", {})
        stats = providers.setdefault(
            provider_name,
            {
                "attempts": 0,
                "success": 0,
                "failure": 0,
                "last_latency_ms": None,
                "latency_ms_total": 0,
                "latency_ms_count": 0,
            },
        )
        stats["last_latency_ms"] = latency_ms
        stats["latency_ms_total"] = int(stats.get("latency_ms_total", 0) or 0) + int(
            latency_ms
        )
        stats["latency_ms_count"] = int(stats.get("latency_ms_count", 0) or 0) + 1
        notification_manager._record_provider_latency_bucket(
            provider_name, latency_ms / 1000.0
        )


def _r142_sum_seconds(provider_name: str) -> float:
    """读取 R142 path 的 latency_ms_total, 换算成秒。"""
    with notification_manager._stats_lock:
        providers = notification_manager._stats.get("providers", {})
        return int(providers.get(provider_name, {}).get("latency_ms_total", 0)) / 1000.0


def _r142_count(provider_name: str) -> int:
    """读取 R142 path 的 latency_ms_count。"""
    with notification_manager._stats_lock:
        providers = notification_manager._stats.get("providers", {})
        return int(providers.get(provider_name, {}).get("latency_ms_count", 0))


# ---------------------------------------------------------------------------
# 1. Math invariant: count / sum 同步
# ---------------------------------------------------------------------------


class TestLatencyStatsInvariantMath(unittest.TestCase):
    """同一 sample fed 进 R142 + R191 两条 path 后 running totals 一致。"""

    def setUp(self) -> None:
        _reset_provider_histograms()
        _reset_provider_r142_stats("bark")

    def tearDown(self) -> None:
        _reset_provider_histograms()
        _reset_provider_r142_stats("bark")

    def test_single_sample_invariant(self) -> None:
        """单次 sample 后两路 count == 1, sum 一致。"""
        _feed_sample("bark", 250)
        r142_sum = _r142_sum_seconds("bark")
        r142_cnt = _r142_count("bark")
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        r191 = snap["bark"]
        self.assertEqual(r142_cnt, r191["count"], "count divergence after 1 sample")
        self.assertAlmostEqual(
            r142_sum,
            r191["sum_seconds"],
            delta=_FLOAT_EPS,
            msg="sum_seconds divergence after 1 sample",
        )

    def test_multiple_samples_invariant(self) -> None:
        """N 次 sample 累加后两路仍然一致。"""
        samples = [50, 100, 250, 500, 1000, 2000, 5000]
        for ms in samples:
            _feed_sample("bark", ms)
        r142_sum = _r142_sum_seconds("bark")
        r142_cnt = _r142_count("bark")
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        r191 = snap["bark"]
        self.assertEqual(r142_cnt, len(samples), "R142 count != N")
        self.assertEqual(r142_cnt, r191["count"], "count divergence after N samples")
        # 理论 sum: sum(samples) / 1000
        expected = sum(samples) / 1000.0
        self.assertAlmostEqual(r142_sum, expected, delta=_FLOAT_EPS)
        self.assertAlmostEqual(r191["sum_seconds"], expected, delta=_FLOAT_EPS)
        # 互相一致
        self.assertAlmostEqual(
            r142_sum,
            r191["sum_seconds"],
            delta=_FLOAT_EPS,
            msg="R142 sum != R191 sum_seconds",
        )

    def test_int_to_float_unit_conversion_invariant(self) -> None:
        """R142 是 int ms 累加, R191 是 float second 累加。invariant 是单位
        换算 (``ms / 1000.0``) 不丢精度。用整 1000 倍数 sample 避免 float
        rounding noise。"""
        for ms in (1000, 2000, 5000, 10000):
            _feed_sample("bark", ms)
        r142_sum = _r142_sum_seconds("bark")
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        r191_sum = snap["bark"]["sum_seconds"]
        # 1000 倍数 sample 单位换算精确无误差
        self.assertEqual(
            r142_sum,
            r191_sum,
            "1000-multiple ms samples should be exactly equal after /1000 conversion",
        )


# ---------------------------------------------------------------------------
# 2. Multi-provider isolation
# ---------------------------------------------------------------------------


class TestLatencyStatsMultiProviderIsolation(unittest.TestCase):
    """provider A 的 sample 不污染 provider B 的 stats。"""

    def setUp(self) -> None:
        _reset_provider_histograms()
        _reset_provider_r142_stats("bark")
        _reset_provider_r142_stats("pushover")

    def tearDown(self) -> None:
        _reset_provider_histograms()

    def test_separate_providers_track_independently(self) -> None:
        for ms in (100, 200, 300):
            _feed_sample("bark", ms)
        for ms in (1000, 2000):
            _feed_sample("pushover", ms)
        # R142 path
        self.assertEqual(_r142_count("bark"), 3)
        self.assertEqual(_r142_count("pushover"), 2)
        self.assertAlmostEqual(_r142_sum_seconds("bark"), 0.6, delta=_FLOAT_EPS)
        self.assertAlmostEqual(_r142_sum_seconds("pushover"), 3.0, delta=_FLOAT_EPS)
        # R191 path
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        self.assertEqual(snap["bark"]["count"], 3)
        self.assertEqual(snap["pushover"]["count"], 2)
        self.assertAlmostEqual(snap["bark"]["sum_seconds"], 0.6, delta=_FLOAT_EPS)
        self.assertAlmostEqual(snap["pushover"]["sum_seconds"], 3.0, delta=_FLOAT_EPS)

    def test_cross_invariant_holds_per_provider(self) -> None:
        """同一 provider 内 R142 / R191 一致, 不同 provider 间互不影响。"""
        _feed_sample("bark", 500)
        _feed_sample("pushover", 1500)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        # bark invariant
        self.assertAlmostEqual(
            _r142_sum_seconds("bark"),
            snap["bark"]["sum_seconds"],
            delta=_FLOAT_EPS,
        )
        self.assertEqual(_r142_count("bark"), snap["bark"]["count"])
        # pushover invariant
        self.assertAlmostEqual(
            _r142_sum_seconds("pushover"),
            snap["pushover"]["sum_seconds"],
            delta=_FLOAT_EPS,
        )
        self.assertEqual(_r142_count("pushover"), snap["pushover"]["count"])


# ---------------------------------------------------------------------------
# 3. Source-level AST guard: 两条 path 必须在同一 lock 块、紧邻
# ---------------------------------------------------------------------------


class TestSourceLevelLatencyPathColocation(unittest.TestCase):
    """``_send_single_notification`` 源码里 R142 latency 记录块 + R191
    histogram 记录调用必须紧贴在一起 (同 ``_stats_lock`` 块内, R191
    紧跟 R142 自增后), 防止未来 refactor 把两路错开。

    **为什么用 AST guard 而不是 runtime test** (CR#20 §4.3 F-197-1 /
    CR#16 §3.5 「structural invariants vs runtime tests」):
    R142 的 ``latency_ms_total`` 累加 和 R191 的 ``_record_provider_
    latency_bucket`` 共用同一个 ``latency_ms`` 采样, 但**单独**给每
    条 counter 写 runtime test 是抓不到 silent drift 的——把两条更新
    挪到**不同** lock 块 (或一条放 fast-path / 一条放 slow-path /
    一条被 ``if cond:`` 条件跳过) 时, 每个 counter 各自看仍然「值
    对得上」, 但 dashboard 上 ``avg_latency_ms = total / count`` 跟
    ``histogram_quantile(0.95, …)`` 算出的 P95 会悄悄走偏 (R142 漏
    采样而 R191 没漏, 或反过来). 结构性不变量 (「同一 ``with self.
    _stats_lock:`` 块内 + 单位换算正确 + 没有备用 emit 路径绕过 lock」)
    只能 parse 源码 AST 才锁得住, 不能靠 input/output 黑盒测试.
    """

    def setUp(self) -> None:
        self.src = Path(nm_module.__file__).read_text(encoding="utf-8")

    def test_latency_ms_total_and_histogram_call_in_same_lock_block(self) -> None:
        """从 ``with self._stats_lock`` 出现到下一个 ``with self._stats_lock``
        / 函数结束之间, ``latency_ms_total`` 增量 和
        ``_record_provider_latency_bucket`` 调用都必须在内。"""
        # 找到 _send_single_notification 函数体
        match = re.search(
            r"def _send_single_notification\(.*?\n(.*?)(?=\n    def [^_]|\nclass )",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match, "couldn't isolate _send_single_notification body in source"
        )
        assert match is not None  # ty narrow: 上一行 assertIsNotNone 已挡 None
        body = match.group(1)
        # 找到第一个 latency 记录的 `with self._stats_lock:` 块
        # (函数内可能有多个 lock 区段)
        lock_iter = list(re.finditer(r"with self\._stats_lock:\s*\n", body))
        self.assertGreater(
            len(lock_iter), 0, "no _stats_lock acquired in _send_single_notification"
        )
        # 关键: 必须有**至少一个** lock 块同时包含两个 mutation
        found_pair = False
        for i, m in enumerate(lock_iter):
            block_start = m.end()
            block_end = (
                lock_iter[i + 1].start() if i + 1 < len(lock_iter) else len(body)
            )
            block = body[block_start:block_end]
            has_r142 = "latency_ms_total" in block and "+=" in block.replace(
                "+ int", "+ "
            )
            # 兼容现写法 stats["latency_ms_total"] = ... + int(latency_ms)
            has_r142 = has_r142 or (
                "latency_ms_total" in block and "int(latency_ms)" in block
            )
            has_r191 = "_record_provider_latency_bucket" in block
            if has_r142 and has_r191:
                found_pair = True
                # 顺序断言: R191 在 R142 之后 (R191 必须看到已经更新的 R142
                # state, 虽然这俩不直接共享内存, 但顺序是 caller-side 契约)
                r142_idx = block.find("latency_ms_total")
                r191_idx = block.find("_record_provider_latency_bucket")
                self.assertLess(
                    r142_idx,
                    r191_idx,
                    "R142 latency_ms_total update must precede R191 "
                    "_record_provider_latency_bucket call (CR#19 §4.2 contract)",
                )
                break
        self.assertTrue(
            found_pair,
            "no single _stats_lock block contains both R142 latency_ms_total "
            "mutation and R191 _record_provider_latency_bucket call — "
            "they MUST be co-located to keep the dashboard invariant.",
        )

    def test_histogram_call_uses_seconds_unit(self) -> None:
        """R191 call site 必须传 ``latency_ms / 1000.0`` (秒), 不是直接传
        毫秒——否则 histogram 桶分布跟 metric name (..._seconds) 对不上。"""
        # 找 *call site* (不是 def 定义): 必须以 ``self.`` 开头, 且参数里
        # 包含 ``latency_ms``。re.DOTALL 让 ``[^)]+`` 跨多行匹配。
        call_match = re.search(
            r"self\._record_provider_latency_bucket\s*\(([^)]+)\)",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            call_match,
            "no `self._record_provider_latency_bucket(...)` call site found",
        )
        assert call_match is not None  # ty narrow: 上一行 assertIsNotNone 已挡 None
        args = call_match.group(1).strip()
        # args 形如: ``notification_type.value, latency_ms / 1000.0``
        # 第二个参数 (split-comma 取最后一段) 应含 "1000" (单位换算)
        parts = [p.strip() for p in args.split(",")]
        self.assertGreaterEqual(
            len(parts), 2, f"expected ≥2 args at call site, got: {args!r}"
        )
        second_arg = parts[-1]
        self.assertIn(
            "1000",
            second_arg,
            f"_record_provider_latency_bucket second arg should be ms/1000 "
            f"(seconds), got: {second_arg!r}",
        )

    def test_no_alternate_histogram_call_outside_lock(self) -> None:
        """``_record_provider_latency_bucket`` 不应该在 ``_stats_lock`` 外被
        其他地方 (比如 retry 路径) 二次调用——否则 R191 sample 被
        double-count 而 R142 没被同步, invariant 破。"""
        # 全文搜索 _record_provider_latency_bucket 调用点 (排除定义和注释)
        call_sites = [
            m
            for m in re.finditer(
                r"^\s*[^#]*?\b(self\.)?_record_provider_latency_bucket\b",
                self.src,
                re.MULTILINE,
            )
            if "def _record_provider_latency_bucket" not in m.group(0)
        ]
        # 期望只有 1 个 caller (在 _send_single_notification 内 latency 记录块)
        self.assertEqual(
            len(call_sites),
            1,
            f"expected exactly 1 caller of _record_provider_latency_bucket, "
            f"found {len(call_sites)}; suspicious sites: "
            f"{[m.group(0).strip() for m in call_sites]}",
        )


# ---------------------------------------------------------------------------
# 4. Edge case: 0-sample baseline + 大量 sample 浮点容忍
# ---------------------------------------------------------------------------


class TestLatencyStatsInvariantEdgeCases(unittest.TestCase):
    def setUp(self) -> None:
        _reset_provider_histograms()
        _reset_provider_r142_stats("bark")

    def tearDown(self) -> None:
        _reset_provider_histograms()

    def test_zero_samples_baseline(self) -> None:
        """无 sample 时两路 stats 都应该是 0 / empty, invariant 在 zero 状态
        下也成立 (避免一边返回空 dict 一边返回 ``{count: 0}``)。"""
        # R142: count == 0
        self.assertEqual(_r142_count("bark"), 0)
        self.assertEqual(_r142_sum_seconds("bark"), 0.0)
        # R191: snapshot 里 "bark" 不存在 (空 dict)
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        self.assertNotIn(
            "bark",
            snap,
            "zero-sample provider should NOT appear in R191 snapshot "
            "(R191 only registers providers after first sample)",
        )

    def test_high_volume_float_accumulation_tolerance(self) -> None:
        """大量小 sample 累加 (1000 次 1ms) 后 invariant 仍然成立, 容忍
        浮点 rounding error。"""
        for _ in range(1000):
            _feed_sample("bark", 1)
        r142_sum = _r142_sum_seconds("bark")
        snap = notification_manager.get_provider_latency_histograms_snapshot()
        r191 = snap["bark"]
        self.assertEqual(_r142_count("bark"), 1000)
        self.assertEqual(_r142_count("bark"), r191["count"])
        # R142 sum: 1000 * 1ms = 1000ms = 1.0s
        # R191 sum_seconds: 1000 * (1/1000) = 1.0  (float, 但 1/1000 不可
        # 精确, 累加 1000 次 ≈ 1.0 ± 1e-13)
        self.assertAlmostEqual(r142_sum, 1.0, delta=_FLOAT_EPS)
        self.assertAlmostEqual(r191["sum_seconds"], 1.0, delta=1e-12)
        # 关键: 两者互相一致 (容忍累加噪声)
        self.assertAlmostEqual(
            r142_sum,
            r191["sum_seconds"],
            delta=1e-12,
            msg="float accumulation drift exceeds 1e-12 tolerance",
        )


if __name__ == "__main__":
    unittest.main()
