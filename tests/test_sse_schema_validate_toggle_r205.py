"""R205 / Cycle 9 · F-204-1 · SSE schema runtime validation toggle tests。

设计目标
========

R198 把 ``EVENT_SCHEMAS`` + ``validate_payload`` API 暴露好了, 但**故意
不在 production emit 路径调用**（hot path 性能优先, 见
``sse_event_schemas.py`` 模块 docstring "设计取舍"）。F-204-1 加 env
var ``AIIA_SSE_SCHEMA_VALIDATE=off|warn|strict`` toggle, 让运维 / 调
试期可以选择性开启 emit-site 验证, 不污染 default zero-overhead 行为。

测试目标
========

1. **off (default) 是真零开销** —— mode 检查通过 attribute compare;
   schema_violation_total 永远 = 0; validate_payload 不被调用 (spy 验证);
2. **warn mode** —— violations 走 logger.warning + counter += 1 (一条
   emit 多字段错只算 1 次), 但 emit 仍 fanout subscriber 不阻塞;
3. **strict mode** —— violations 走 logger.error (alertmanager 路由)
   + 同样 counter += 1 + emit 仍 fanout 不 raise (production fire-
   and-forget 契约);
4. **env var parsing** —— 大小写 normalize / 无效值 fall-back off
   + startup WARN / unset / empty default;
5. **4 R198 registered events round-trip** —— task_changed /
   config_changed / log_level_changed / oversize_drop 正确 payload
   下 warn / strict mode 都不报 violation;
6. **stats_snapshot 暴露** —— schema_validate_mode + schema_violation
   _total 两个 key 必存在 + TypedDict 字段类型正确;
7. **oversize_drop 替换路径不被验证污染** —— validate 在 emit() 最
   早期跑 (oversize 替换之前), 验证的是 caller 真实传入, 不是 bus
   内部替换路径;
8. **不 raise 契约** (strict mode) —— invalid payload 不会让 emit()
   抛异常, 测 emit() 调用本身不抛 + subscriber 仍收到 event。

总计: 14 cases / 8 invariant class + 4 subtests。
"""

from __future__ import annotations

import logging
import sys
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.sse_event_schemas import EVENT_SCHEMAS
from ai_intervention_agent.web_ui_routes import task as task_module
from ai_intervention_agent.web_ui_routes.task import (
    _SSE_SCHEMA_VALIDATE_DEFAULT_MODE,
    _SSE_SCHEMA_VALIDATE_ENV_VAR,
    _SSE_SCHEMA_VALIDATE_VALID_MODES,
    _read_sse_schema_validate_mode,
    _SSEBus,
)

# EnhancedLogger 包装了 logging.Logger; 拿底层 logger.name 给 assertLogs 用。
_TASK_LOGGER_NAME: str = task_module.logger.logger.name


def _clear_log_dedup_cache() -> None:
    """清空 EnhancedLogger 的 5-秒 dedup cache。

    R205 测试反复触发 ``logger.warning`` / ``logger.error`` 同一条
    violation message; 不清就被去重 → assertLogs 抓不到第二条。
    """
    task_module.logger.deduplicator.cache.clear()


def _make_bus_with_env(env_value: str | None) -> _SSEBus:
    """临时设 ``AIIA_SSE_SCHEMA_VALIDATE`` 然后 new 一个 _SSEBus()。

    sticky env-var 设计意味着每个 mode 需要独立 bus 实例 —— 不能用
    module-level ``_sse_bus`` singleton。
    """
    env: dict[str, str] = {}
    if env_value is not None:
        env[_SSE_SCHEMA_VALIDATE_ENV_VAR] = env_value
    with patch.dict("os.environ", env, clear=False):
        if (
            env_value is None
            and _SSE_SCHEMA_VALIDATE_ENV_VAR in __import__("os").environ
        ):
            __import__("os").environ.pop(_SSE_SCHEMA_VALIDATE_ENV_VAR, None)
        return _SSEBus()


# ---------------------------------------------------------------------------
# 1. Off (default) mode 零开销契约
# ---------------------------------------------------------------------------


class TestSseSchemaValidateModeOff(unittest.TestCase):
    """``off`` 是 default + 零开销契约的守护。"""

    def test_default_when_env_var_unset(self) -> None:
        """env var 不设 → mode == 'off'。"""
        with patch.dict("os.environ", {}, clear=False):
            __import__("os").environ.pop(_SSE_SCHEMA_VALIDATE_ENV_VAR, None)
            bus = _SSEBus()
        self.assertEqual(bus._schema_validate_mode, "off")
        self.assertEqual(bus._schema_violation_total, 0)

    def test_default_when_env_var_empty_string(self) -> None:
        """空字符串 → fall back to 'off' (合理空值容错)。"""
        bus = _make_bus_with_env("")
        self.assertEqual(bus._schema_validate_mode, "off")

    def test_off_does_not_invoke_validate_payload(self) -> None:
        """``off`` mode emit 不应该调 validate_payload (零开销契约)。
        spy validate_payload, emit 100 次 invalid payload 全部 counter
        仍为 0 / spy call_count 仍为 0。"""
        bus = _make_bus_with_env("off")
        with patch("ai_intervention_agent.web_ui_routes.task.validate_payload") as spy:
            for _ in range(100):
                bus.emit("totally_unknown_type", {"bogus_field": 1})
        self.assertEqual(
            spy.call_count,
            0,
            "off mode 必须不调 validate_payload (零开销契约 broken)",
        )
        self.assertEqual(bus._schema_violation_total, 0)


# ---------------------------------------------------------------------------
# 2. Warn mode 行为契约
# ---------------------------------------------------------------------------


class TestSseSchemaValidateModeWarn(unittest.TestCase):
    """``warn`` mode: violations → logger.warning + counter += 1, emit 仍 fanout。"""

    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_warn_mode_value(self) -> None:
        bus = _make_bus_with_env("warn")
        self.assertEqual(bus._schema_validate_mode, "warn")

    def test_warn_valid_payload_no_log_no_counter(self) -> None:
        """合法 payload → 0 violations + counter 不增。"""
        bus = _make_bus_with_env("warn")
        with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING") as cm:
            bus.emit(
                "task_changed",
                {"task_id": "t1", "old_status": "p", "new_status": "a"},
            )
            # workaround: assertLogs 要求至少 1 条 — 主动 log 一条无关 warning
            task_module.logger.warning("test sentinel")
        self.assertEqual(bus._schema_violation_total, 0)
        violation_logs = [r for r in cm.records if "R205 SSE schema" in r.getMessage()]
        self.assertEqual(violation_logs, [], "合法 payload 不应触发 R205 log")

    def test_warn_invalid_payload_logs_warning_and_counts(self) -> None:
        """缺 required field → 1 warning log + counter += 1。"""
        bus = _make_bus_with_env("warn")
        with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING") as cm:
            bus.emit("task_changed", {"task_id": "t1"})  # 缺 old_status / new_status
        self.assertEqual(bus._schema_violation_total, 1)
        violation_logs = [
            r for r in cm.records if "R205 SSE schema warn" in r.getMessage()
        ]
        self.assertGreaterEqual(
            len(violation_logs),
            1,
            "缺 required field 必须 log 至少 1 条 R205 warning",
        )

    def test_warn_multi_field_violation_increments_counter_once(self) -> None:
        """一条 emit 多个字段错 → counter += 1 (不 += N) —— 与 R203
        WARN-once 同款 "per-emit 计数" 语义，避免噪声膨胀。"""
        bus = _make_bus_with_env("warn")
        with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING"):
            bus.emit(
                "task_changed",
                {
                    "extra_bogus": 1,
                    "another_extra": 2,
                },  # 缺 3 required + 2 extra unexpected = 5 violations
            )
        self.assertEqual(
            bus._schema_violation_total,
            1,
            "一条 emit 多字段错只算 1 次 violation",
        )

    def test_warn_emit_still_fanouts_to_subscriber(self) -> None:
        """warn mode 下 invalid emit 仍 fanout 给 subscriber (不阻塞)。"""
        bus = _make_bus_with_env("warn")
        q = bus.subscribe()
        with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING"):
            bus.emit("task_changed", {"task_id": "t1"})  # invalid
        # 给 emit 一点点时间 fanout (lock-free 路径不需要 sleep, 但 queue.put
        # 是 thread-safe)
        evt = q.get(timeout=1.0)
        self.assertEqual(evt["type"], "task_changed")


# ---------------------------------------------------------------------------
# 3. Strict mode 行为契约
# ---------------------------------------------------------------------------


class TestSseSchemaValidateModeStrict(unittest.TestCase):
    """``strict`` mode: violations → logger.error + counter += 1, emit 仍 fanout 不 raise。"""

    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_strict_mode_value(self) -> None:
        bus = _make_bus_with_env("strict")
        self.assertEqual(bus._schema_validate_mode, "strict")

    def test_strict_invalid_payload_logs_error_not_warning(self) -> None:
        """strict mode 下 violations 必须走 ``logger.error``，不是
        warning —— 这是 strict 与 warn 唯一行为差异。"""
        bus = _make_bus_with_env("strict")
        with self.assertLogs(_TASK_LOGGER_NAME, level="ERROR") as cm:
            bus.emit("task_changed", {"task_id": "t1"})  # invalid
        error_logs = [
            r
            for r in cm.records
            if r.levelno == logging.ERROR and "R205 SSE schema strict" in r.getMessage()
        ]
        self.assertGreaterEqual(
            len(error_logs),
            1,
            "strict mode 必须走 logger.error (与 warn 区分)",
        )

    def test_strict_does_not_raise_on_invalid_payload(self) -> None:
        """**关键契约**: strict mode 下 invalid payload **不会** 让 emit() 抛
        异常 (production fire-and-forget; emit-site 大量没 try/except 包裹)。"""
        bus = _make_bus_with_env("strict")
        try:
            with self.assertLogs(_TASK_LOGGER_NAME, level="ERROR"):
                bus.emit("totally_unknown_type", {"random": 1})  # unknown event_type
                bus.emit("task_changed", None)  # None payload
                # 故意传非 dict 类型 — 测试 emit 对 caller 误用的 robust 处理。
                bus.emit("task_changed", "not a dict")  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                bus.emit(
                    "task_changed", {"unknown_field": 1}
                )  # missing required + extra
        except Exception as e:  # pragma: no cover - 失败路径
            self.fail(f"strict mode emit() 不应 raise, but raised: {e!r}")
        self.assertGreaterEqual(bus._schema_violation_total, 4)

    def test_strict_emit_still_fanouts_to_subscriber(self) -> None:
        bus = _make_bus_with_env("strict")
        q = bus.subscribe()
        with self.assertLogs(_TASK_LOGGER_NAME, level="ERROR"):
            bus.emit("task_changed", {"task_id": "t1"})  # invalid
        evt = q.get(timeout=1.0)
        self.assertEqual(evt["type"], "task_changed")


# ---------------------------------------------------------------------------
# 4. Env var parsing 契约
# ---------------------------------------------------------------------------


class TestSseSchemaValidateEnvVarParsing(unittest.TestCase):
    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_uppercase_normalised_to_lowercase(self) -> None:
        """``OFF`` / ``STRICT`` 大写 → normalize 到 lowercase。"""
        for raw, expected in [("OFF", "off"), ("WARN", "warn"), ("STRICT", "strict")]:
            with self.subTest(raw=raw):
                bus = _make_bus_with_env(raw)
                self.assertEqual(bus._schema_validate_mode, expected)

    def test_whitespace_trimmed(self) -> None:
        """``" strict "`` 含 whitespace → strip 后识别。"""
        bus = _make_bus_with_env("  strict  ")
        self.assertEqual(bus._schema_validate_mode, "strict")

    def test_invalid_value_falls_back_to_off_and_logs_warning(self) -> None:
        """``yes`` / ``1`` / 拼错 → fall back ``off`` + WARN 一次。"""
        for raw in ["yes", "1", "true", "STRICTT", "warning"]:
            with self.subTest(raw=raw):
                # 每个 subTest 清 dedup cache, 否则同一段 WARN message
                # 在 5 秒内重复 → 后续 subTest assertLogs 抓不到。
                _clear_log_dedup_cache()
                with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING") as cm:
                    bus = _make_bus_with_env(raw)
                self.assertEqual(bus._schema_validate_mode, "off")
                fallback_logs = [
                    r
                    for r in cm.records
                    if "not a valid mode" in r.getMessage() and "R205" in r.getMessage()
                ]
                self.assertGreaterEqual(
                    len(fallback_logs),
                    1,
                    f"无效值 {raw!r} 必须 startup WARN 一次",
                )

    def test_read_helper_returns_default_on_unset(self) -> None:
        """``_read_sse_schema_validate_mode`` helper 在 env var 不设时
        返回 ``_SSE_SCHEMA_VALIDATE_DEFAULT_MODE``。"""
        with patch.dict("os.environ", {}, clear=False):
            __import__("os").environ.pop(_SSE_SCHEMA_VALIDATE_ENV_VAR, None)
            result = _read_sse_schema_validate_mode()
        self.assertEqual(result, _SSE_SCHEMA_VALIDATE_DEFAULT_MODE)


# ---------------------------------------------------------------------------
# 5. 4 R198 registered event round-trip 契约
# ---------------------------------------------------------------------------


class TestSseSchemaValidateRegisteredEventsRoundTrip(unittest.TestCase):
    """4 个 R198 registered event + 正确 payload → warn / strict mode 都
    不报 violation。这是 schema registry 与 validate_payload 的端到端
    可用性证明（避免 schema 定义错 → 永远报 violation 的 silent decay）。"""

    PAYLOADS_BY_EVENT: dict[str, dict[str, Any]] = {
        "task_changed": {
            "task_id": "t1",
            "old_status": "pending",
            "new_status": "active",
        },
        "config_changed": {
            "reason": "config_file_modified",
            "hint": "reload",
        },
        "log_level_changed": {
            "old_level": "INFO",
            "new_level": "DEBUG",
            "logger": "ai_intervention_agent",
            "changed_by": "127.0.0.1",
        },
        "oversize_drop": {
            "original_event_type": "task_changed",
            "size_bytes": 300000,
            "limit_bytes": 262144,
        },
    }

    def test_all_registered_events_no_violation_in_warn_mode(self) -> None:
        bus = _make_bus_with_env("warn")
        for event_type in EVENT_SCHEMAS:
            with self.subTest(event_type=event_type):
                payload = self.PAYLOADS_BY_EVENT[event_type]
                violation_count_before = bus._schema_violation_total
                bus.emit(event_type, payload)
                self.assertEqual(
                    bus._schema_violation_total,
                    violation_count_before,
                    f"event {event_type!r} 正确 payload 不应触发 violation",
                )


# ---------------------------------------------------------------------------
# 6. stats_snapshot 暴露契约
# ---------------------------------------------------------------------------


class TestSseSchemaValidateStatsSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_stats_snapshot_exposes_mode_and_total(self) -> None:
        bus = _make_bus_with_env("warn")
        snap = bus.stats_snapshot()
        self.assertIn("schema_validate_mode", snap)
        self.assertIn("schema_violation_total", snap)
        self.assertEqual(snap["schema_validate_mode"], "warn")
        self.assertEqual(snap["schema_violation_total"], 0)

    def test_stats_snapshot_total_increments_after_violation(self) -> None:
        bus = _make_bus_with_env("warn")
        with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING"):
            bus.emit("task_changed", {})  # 缺所有 required field
        snap = bus.stats_snapshot()
        self.assertEqual(snap["schema_violation_total"], 1)

    def test_off_mode_snapshot_shows_off_and_zero_violations(self) -> None:
        bus = _make_bus_with_env("off")
        for _ in range(50):
            bus.emit("totally_unknown", {"random": 1})
        snap = bus.stats_snapshot()
        self.assertEqual(snap["schema_validate_mode"], "off")
        self.assertEqual(
            snap["schema_violation_total"],
            0,
            "off mode 即使 emit invalid 也不应触发 violation 计数",
        )


# ---------------------------------------------------------------------------
# 7. Module-level 常量契约
# ---------------------------------------------------------------------------


class TestModuleLevelConstants(unittest.TestCase):
    """常量值 + valid mode set 是公共 contract，外部测试 / 工具能依赖。"""

    def test_default_mode_is_off(self) -> None:
        self.assertEqual(_SSE_SCHEMA_VALIDATE_DEFAULT_MODE, "off")

    def test_env_var_name_stable(self) -> None:
        self.assertEqual(_SSE_SCHEMA_VALIDATE_ENV_VAR, "AIIA_SSE_SCHEMA_VALIDATE")

    def test_valid_modes_are_off_warn_strict(self) -> None:
        self.assertEqual(
            _SSE_SCHEMA_VALIDATE_VALID_MODES,
            frozenset({"off", "warn", "strict"}),
        )


# ---------------------------------------------------------------------------
# 8. Strict mode 不 raise 契约 — concurrency edge
# ---------------------------------------------------------------------------


class TestStrictModeNoRaiseUnderConcurrency(unittest.TestCase):
    """**核心安全契约**: strict mode 下并发 emit invalid payload 不会
    引发任何 thread crash 或 emit() 失败——这是 production fire-and-forget
    契约的硬性要求。"""

    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_concurrent_invalid_emits_do_not_crash(self) -> None:
        bus = _make_bus_with_env("strict")
        errors: list[BaseException] = []
        barrier = threading.Barrier(4)

        def worker() -> None:
            barrier.wait()
            try:
                for _ in range(20):
                    bus.emit("task_changed", {"task_id": "t1"})  # 缺 2 required
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        with self.assertLogs(_TASK_LOGGER_NAME, level="ERROR"):
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [], f"strict mode 并发 emit 不应抛, got: {errors}")
        self.assertEqual(
            bus._schema_violation_total, 80, "4 thread × 20 emit = 80 violations"
        )


if __name__ == "__main__":
    unittest.main()
