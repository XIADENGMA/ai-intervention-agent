"""R207 / Cycle 10 · F-205-2 · ``aiia_sse_schema_violation_total`` Prometheus counter tests。

设计目标
========

R205 (cycle 9) 把 SSE schema validation 装在 ``AIIA_SSE_SCHEMA_VALIDATE=
off|warn|strict`` 环境变量后, ``_schema_violation_total`` 计数器只通过
``stats_snapshot()`` JSON 暴露——alertmanager 想 watch 必须 scrape JSON。
R207 把这份数据 mirror 到 Prometheus exposition ``aiia_sse_schema_
violation_total`` counter, 让 alertmanager 用标准 PromQL 即可写规则
（如 ``rate(aiia_sse_schema_violation_total[5m]) > 0`` 检测新违规）。

设计契约 · omit-when-off vs always-emit-with-zero
==================================================

R207 选 **omit when mode == "off"**（与 R204 ``aiia_token_age_
seconds`` 同款 omit-vs-NaN 哲学）：

- mode == "off"：metric **不出现** → alertmanager 用 ``absent(
  aiia_sse_schema_violation_total)`` 即可分清 "validation off" vs
  "validation on with 0 violations"，两类 ops 状态走不同 alert 路由；
- mode in {warn, strict}：metric 出现 (value ≥ 0), 可用
  ``rate(...)`` / ``aiia_sse_schema_violation_total > N`` 等阈值告警。

Always-emit-with-zero 的反方案：metric 永远存在 = 0 也输出, 看似简单
但让 ops 无法分辨 "运维忘了开 validation" 与 "validation 开着无违规",
两者都是 0, alertmanager 写不出区分 rule。

测试覆盖 (12 cases / 5 invariant class)
========================================

1. **TestOffModeOmitContract** (2): mode == "off" + 0 violation / 50
   violation 都 omit metric
2. **TestWarnModeEmitContract** (3): mode == "warn" + 0 violation →
   value 0 emit / N violation → value N / metric line 格式合规
3. **TestStrictModeEmitContract** (2): mode == "strict" + N violation
   → value N (与 warn mode 同款 emit; 只是 R205 log level 不同)
4. **TestEndpointMetricParity** (3 · **核心契约**): warn + strict
   mode 下 ``stats_snapshot()['schema_violation_total']`` == metric
   value (3 subtests: 0 / 1 / 多 violation)
5. **TestPrometheusOutputFormat** (2): HELP / TYPE 各 1 次 + counter
   type + HELP 含 R207 / F-205-2 / absent / "Multi-field" 关键字

总计 12 cases。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes import system as system_module
from ai_intervention_agent.web_ui_routes import task as task_module
from ai_intervention_agent.web_ui_routes.task import (
    _SSE_SCHEMA_VALIDATE_ENV_VAR,
    _SSEBus,
)


def _make_bus_with_env(env_value: str | None) -> _SSEBus:
    """同 R205 test helper, 但本测试只用 mode 字段, env-var sticky 行为
    一致。"""
    env: dict[str, str] = {}
    if env_value is not None:
        env[_SSE_SCHEMA_VALIDATE_ENV_VAR] = env_value
    with patch.dict("os.environ", env, clear=False):
        if env_value is None:
            __import__("os").environ.pop(_SSE_SCHEMA_VALIDATE_ENV_VAR, None)
        return _SSEBus()


def _clear_log_dedup_cache() -> None:
    task_module.logger.deduplicator.cache.clear()


def _render_with_bus(bus: _SSEBus) -> str:
    """patch task._sse_bus 然后调 _render_prometheus_metrics。

    `_render_prometheus_metrics` 通过 `from ai_intervention_agent.
    web_ui_routes.task import _sse_bus` 拿 module-level singleton；本
    helper 把它临时换成 test bus 实例，render 后还原。
    """
    with patch.object(task_module, "_sse_bus", bus):
        return system_module._render_prometheus_metrics()


# ---------------------------------------------------------------------------
# 1. Off mode omit contract
# ---------------------------------------------------------------------------


class TestOffModeOmitContract(unittest.TestCase):
    """``off`` mode → metric 不出现 (omit-when-off 契约)。"""

    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_off_mode_zero_violations_omits_metric(self) -> None:
        bus = _make_bus_with_env("off")
        payload = _render_with_bus(bus)
        self.assertNotIn(
            "aiia_sse_schema_violation_total",
            payload,
            "off mode 即使 0 violation 也必须 omit metric",
        )

    def test_off_mode_with_invalid_emits_still_omits_metric(self) -> None:
        """off mode 即使 emit 大量 invalid payload, ``_schema_violation_
        total`` 也永远 = 0 (off mode 不验证); metric 仍 omit (off mode
        不发, 与 R205 contract 一致)。"""
        bus = _make_bus_with_env("off")
        for _ in range(50):
            bus.emit("totally_unknown_type", {"bogus": 1})
        self.assertEqual(bus._schema_violation_total, 0)
        payload = _render_with_bus(bus)
        self.assertNotIn("aiia_sse_schema_violation_total", payload)


# ---------------------------------------------------------------------------
# 2. Warn mode emit contract
# ---------------------------------------------------------------------------


class TestWarnModeEmitContract(unittest.TestCase):
    """``warn`` mode → metric 出现 (value ≥ 0)。"""

    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_warn_mode_zero_violations_emits_metric_with_value_zero(self) -> None:
        bus = _make_bus_with_env("warn")
        payload = _render_with_bus(bus)
        self.assertIn(
            "aiia_sse_schema_violation_total",
            payload,
            "warn mode 即使 0 violation 也必须 emit metric (与 'absent' "
            "区分 'monitoring off')",
        )
        self.assertIn(
            "aiia_sse_schema_violation_total 0",
            payload,
            "warn mode 0 violation → value = 0",
        )

    def test_warn_mode_with_violations_emits_correct_value(self) -> None:
        bus = _make_bus_with_env("warn")
        with self.assertLogs(task_module.logger.logger.name, level="WARNING"):
            for _ in range(7):
                bus.emit("task_changed", {})  # 缺所有 required field, +1 per emit
        self.assertEqual(bus._schema_violation_total, 7)
        payload = _render_with_bus(bus)
        self.assertIn("aiia_sse_schema_violation_total 7", payload)

    def test_warn_mode_metric_line_well_formed(self) -> None:
        bus = _make_bus_with_env("warn")
        payload = _render_with_bus(bus)
        # 找出 metric 行 (HELP + TYPE + value)
        lines = payload.splitlines()
        help_lines = [
            line
            for line in lines
            if line.startswith("# HELP aiia_sse_schema_violation_total")
        ]
        type_lines = [
            line
            for line in lines
            if line.startswith("# TYPE aiia_sse_schema_violation_total")
        ]
        value_lines = [
            line
            for line in lines
            if line.startswith("aiia_sse_schema_violation_total ")
        ]
        self.assertEqual(len(help_lines), 1, "HELP 必须只出现 1 次")
        self.assertEqual(len(type_lines), 1, "TYPE 必须只出现 1 次")
        self.assertEqual(len(value_lines), 1, "value 必须只出现 1 行")
        self.assertIn("counter", type_lines[0], "metric_type 必须是 counter")


# ---------------------------------------------------------------------------
# 3. Strict mode emit contract
# ---------------------------------------------------------------------------


class TestStrictModeEmitContract(unittest.TestCase):
    """``strict`` mode → metric 出现 (与 warn mode 同款 emit; R205 strict
    与 warn 唯一行为差异是 log level, metric 本身一致)。"""

    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_strict_mode_emits_metric(self) -> None:
        bus = _make_bus_with_env("strict")
        payload = _render_with_bus(bus)
        self.assertIn("aiia_sse_schema_violation_total", payload)

    def test_strict_mode_violation_count_matches(self) -> None:
        bus = _make_bus_with_env("strict")
        with self.assertLogs(task_module.logger.logger.name, level="ERROR"):
            for _ in range(3):
                bus.emit("task_changed", {})  # missing required
        payload = _render_with_bus(bus)
        self.assertIn("aiia_sse_schema_violation_total 3", payload)


# ---------------------------------------------------------------------------
# 4. Endpoint / metric parity (核心契约)
# ---------------------------------------------------------------------------


class TestEndpointMetricParity(unittest.TestCase):
    """**核心契约**: ``stats_snapshot()['schema_violation_total']`` 与
    Prometheus metric ``aiia_sse_schema_violation_total`` 必须恒等 (R207
    渲染层不引入新的计数逻辑, 严格 mirror)。"""

    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_parity_under_various_violation_counts(self) -> None:
        """0 / 1 / 多 violation 三档下，snapshot value 必须 == metric value。"""
        for mode in ("warn", "strict"):
            for n_violations in (0, 1, 5):
                with self.subTest(mode=mode, n_violations=n_violations):
                    bus = _make_bus_with_env(mode)
                    _clear_log_dedup_cache()
                    if n_violations > 0:
                        level = "ERROR" if mode == "strict" else "WARNING"
                        with self.assertLogs(
                            task_module.logger.logger.name, level=level
                        ):
                            for _ in range(n_violations):
                                bus.emit("task_changed", {})
                    snap_total = bus.stats_snapshot()["schema_violation_total"]
                    self.assertEqual(snap_total, n_violations)
                    payload = _render_with_bus(bus)
                    expected_line = f"aiia_sse_schema_violation_total {n_violations}"
                    self.assertIn(
                        expected_line,
                        payload,
                        f"mode={mode} n={n_violations}: snap {snap_total} 与 "
                        f"metric 不一致 (expected line {expected_line!r})",
                    )


# ---------------------------------------------------------------------------
# 5. Prometheus output format & docstring keyword 契约
# ---------------------------------------------------------------------------


class TestPrometheusOutputFormat(unittest.TestCase):
    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_help_contains_r207_f_205_2_absent_keywords(self) -> None:
        """HELP 字符串必须含 R207 / F-205-2 / absent / 'Multi-field' /
        ``AIIA_SSE_SCHEMA_VALIDATE`` 等关键词, 让运维 grep 也能定位 +
        理解 omit-when-off 契约。"""
        bus = _make_bus_with_env("warn")
        payload = _render_with_bus(bus)
        help_line = next(
            (
                line
                for line in payload.splitlines()
                if line.startswith("# HELP aiia_sse_schema_violation_total")
            ),
            "",
        )
        self.assertTrue(help_line, "HELP 行必须存在")
        for needle in (
            "R207",
            "F-205-2",
            "AIIA_SSE_SCHEMA_VALIDATE",
            "absent",
            "Multi-field",
        ):
            self.assertIn(
                needle,
                help_line,
                f"HELP 必须含关键词 {needle!r} 让运维 grep 定位",
            )

    def test_type_line_declares_counter(self) -> None:
        bus = _make_bus_with_env("strict")
        payload = _render_with_bus(bus)
        type_line = next(
            (
                line
                for line in payload.splitlines()
                if line.startswith("# TYPE aiia_sse_schema_violation_total")
            ),
            "",
        )
        self.assertIn(
            "counter",
            type_line,
            "TYPE 必须声明 counter (与 _emit_total 同款 monotonic 累加语义)",
        )


if __name__ == "__main__":
    unittest.main()
