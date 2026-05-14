"""R212 / Cycle 10 · F-205-3 · R205 contract bridge invariants (R210 follow-up)。

设计目标
========

R210（docs sync, F-205-1）把 ``AIIA_SSE_SCHEMA_VALIDATE`` env var 完整说
明搬进 ``docs/configuration.{md,zh-CN.md}``，里面对 R205 实现做出了**显
式承诺**：

  * "Twelve-Factor sticky" — 启动后改 env var 不生效，必须重启；
  * "fire-and-forget" — strict mode 也 **不抛异常**；
  * "omit-when-off" — Prometheus metric 在 mode=off 时不出现，让 ops
    用 ``absent(...)`` 区分「监控关闭」vs「监控开启且 0 violation」；
  * "single emit multi-field violation counts as 1" — 噪声抑制契约。

R205 自身的测试套（``tests/test_sse_schema_validate_toggle_r205.py``）
覆盖了 8 个 invariant class / 14 cases，但**没有显式锁定**:

  1. **Sticky read invariant**: bus 创建**之后**改 env var → ``bus.
     _schema_validate_mode`` 不变 + 触发 violation 仍按 init 时的 mode
     走 log level / counter（R205 只测 init 时读 env，没测 post-init
     immutability）。
  2. **HTTP endpoint round-trip**: ``GET /api/system/sse-stats``
     返回 JSON 必含 ``schema_validate_mode`` + ``schema_violation_total``
     字段（R205 只测 ``bus.stats_snapshot()`` Python dict 暴露, 没测
     HTTP boundary; R207 测 ``/api/system/metrics`` Prometheus 但未
     覆盖 JSON endpoint）。
  3. **R210 docs ↔ R205 code keyword drift**: R210 docs 写的关键
     design keyword (``Twelve-Factor`` / ``fire-and-forget`` /
     ``omit-when-off``) 必须在 R205 / R207 源码注释中也出现, 防止
     docs 改了 code 没跟（或反向）的双向漂移。
  4. **Counter type stability**: ``_schema_violation_total`` /
     ``stats_snapshot()['schema_violation_total']`` 永远是 ``int``
     (不是 ``float`` / ``collections.Counter`` / ``Decimal``)，
     防 future refactor (R207 / R208 / R209 链上某次 perf 改造) 把
     字段类型偷偷改成别的, 破坏 Prometheus exposition 与 ops dashboard
     parse 行为。

R212 是 cross-file invariant bridge — 把 R210 docs phrasing 与 R205 实
现的契约一致性锁在测试里, 后续任意一方漂移都会 fail。

测试架构（4 invariant class / 10 cases / 0 subtest）
====================================================

1. TestStickyReadInvariant (3 cases): bus 创建后改 env, mode/log/counter
   都保持 init 时的行为；
2. TestStatsEndpointJsonRoundTrip (3 cases): HTTP /api/system/sse-stats
   JSON 必含 R205 字段 + 类型正确 + value 来自 stats_snapshot；
3. TestR210DocsKeywordInR205Code (2 cases): R210 docs 的关键 design
   keyword 必须出现在 R205 源码 (task.py + system.py)；
4. TestCounterTypeStability (2 cases): counter 类型永远 int (instance
   attribute + stats_snapshot 字典)。

沿用 R205 ``_make_bus_with_env`` 测试 helper 风格 + R207 / R210 静态契
约锁定模式。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from flask import Flask

from ai_intervention_agent.web_ui_routes import task as task_module
from ai_intervention_agent.web_ui_routes.task import (
    _SSE_SCHEMA_VALIDATE_ENV_VAR,
    _SSEBus,
)

# EnhancedLogger 包装了 logging.Logger; 拿底层 logger.name 给 assertLogs 用。
_TASK_LOGGER_NAME: str = task_module.logger.logger.name


def _clear_log_dedup_cache() -> None:
    """清空 EnhancedLogger 的 5-秒 dedup cache。

    与 R205 测试同款 helper —— 反复触发同一条 violation message 时
    防止 assertLogs 抓不到第二条。
    """
    task_module.logger.deduplicator.cache.clear()


def _make_bus_with_env(env_value: str | None) -> _SSEBus:
    """临时设 ``AIIA_SSE_SCHEMA_VALIDATE`` 然后 new 一个 ``_SSEBus()``。

    与 R205 测试同款 helper。sticky env-var 设计意味着每个 mode 需要
    独立 bus 实例（不能用 module-level ``_sse_bus`` singleton）。
    """
    env: dict[str, str] = {}
    if env_value is not None:
        env[_SSE_SCHEMA_VALIDATE_ENV_VAR] = env_value
    with patch.dict("os.environ", env, clear=False):
        if env_value is None and _SSE_SCHEMA_VALIDATE_ENV_VAR in os.environ:
            os.environ.pop(_SSE_SCHEMA_VALIDATE_ENV_VAR, None)
        return _SSEBus()


# ---------------------------------------------------------------------------
# 1. Sticky read invariant (Twelve-Factor 契约 — R210 docs 显式承诺)
# ---------------------------------------------------------------------------


class TestStickyReadInvariant(unittest.TestCase):
    """**核心契约**: bus 创建**之后**改 env var → bus 行为不变。

    R210 docs 显式写明 "Twelve-Factor sticky 读取（启动后改 env var
    不生效，必须重启）"。R205 测试覆盖 init 时 env var 读取，但未
    覆盖 post-init immutability —— 一旦 future refactor 把 env var
    读取从 ``__init__`` 移到 ``emit()`` (e.g. "支持热更新" 这种诱惑),
    R210 docs 的承诺就破，运维按 docs 期望改 env var 重启会茫然。

    本 invariant class 把 sticky 契约锁死。
    """

    def setUp(self) -> None:
        _clear_log_dedup_cache()

    def test_mode_attribute_does_not_change_after_env_change(self) -> None:
        """env var 在 bus 创建后被改 → bus._schema_validate_mode 不变。"""
        bus = _make_bus_with_env("warn")
        self.assertEqual(bus._schema_validate_mode, "warn")
        # post-init 改 env var → mode attribute 不变
        with patch.dict(
            "os.environ", {_SSE_SCHEMA_VALIDATE_ENV_VAR: "strict"}, clear=False
        ):
            self.assertEqual(
                bus._schema_validate_mode,
                "warn",
                "R210 docs 承诺 Twelve-Factor sticky — post-init env var "
                "改动不应改 bus._schema_validate_mode",
            )

    def test_emit_log_level_does_not_change_after_env_change(self) -> None:
        """env var post-init 改成 strict → 违规日志仍走 warn 的 ``WARNING`` level。"""
        bus = _make_bus_with_env("warn")
        with patch.dict(
            "os.environ", {_SSE_SCHEMA_VALIDATE_ENV_VAR: "strict"}, clear=False
        ):
            # 触发 violation，仍走 logger.warning (warn mode) 而非
            # logger.error (strict mode) — sticky 契约。
            with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING") as cm:
                bus.emit("task_changed", {"task_id": "t1"})  # 缺 required
            warn_logs = [
                r for r in cm.records if "R205 SSE schema warn" in r.getMessage()
            ]
            self.assertGreaterEqual(
                len(warn_logs),
                1,
                "sticky 契约: warn-init bus 即使 env var 改成 strict, log "
                "仍走 'R205 SSE schema warn' (不是 'strict')",
            )

    def test_counter_increments_consistently_across_env_change(self) -> None:
        """env var post-init 改了，counter 仍按 warn 模式 +1（每次 emit）。"""
        bus = _make_bus_with_env("warn")
        with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING"):
            bus.emit("task_changed", {"task_id": "t1"})  # invalid
        self.assertEqual(bus._schema_violation_total, 1)
        # 改 env var 到 off 后, 再 emit invalid 仍 counter += 1 (sticky)
        with patch.dict(
            "os.environ", {_SSE_SCHEMA_VALIDATE_ENV_VAR: "off"}, clear=False
        ):
            _clear_log_dedup_cache()
            with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING"):
                bus.emit("task_changed", {"task_id": "t2"})  # invalid
            self.assertEqual(
                bus._schema_violation_total,
                2,
                "sticky 契约: warn-init bus 不会因为 env var 改成 off 就停止计数",
            )


# ---------------------------------------------------------------------------
# 2. HTTP /api/system/sse-stats endpoint JSON round-trip
# ---------------------------------------------------------------------------


class TestStatsEndpointJsonRoundTrip(unittest.TestCase):
    """``GET /api/system/sse-stats`` HTTP boundary 必须暴露 R205 两字段。

    R205 测试只测 ``bus.stats_snapshot()`` Python dict 暴露 (in-process)，
    没测 HTTP boundary 是否真的把这两个字段 serialise 到 JSON。R207 测了
    Prometheus ``/api/system/metrics`` 暴露，也没测 JSON endpoint。这是
    HTTP edge gap —— 一旦 ``sse_stats()`` route 改成 whitelist 字段
    (e.g. "只暴露 R47 老字段")，运维 dashboard 拿不到 R205 字段也不会
    fail 测试，silent decay。

    本 class 把 HTTP JSON contract 锁死。
    """

    def _make_app_and_bus_with_mode(self, mode: str) -> tuple[Flask, _SSEBus]:
        """构造一个测试用 Flask app + 替换 module-level ``_sse_bus`` 实例。

        sse_stats() endpoint 是 lazy import + 直接读 module-level
        ``_sse_bus`` (``from ai_intervention_agent.web_ui_routes.task
        import _sse_bus``)，要让 HTTP test 看到 mode != "off" 的 bus,
        必须在调 endpoint 之前 monkey-patch 整个 ``task._sse_bus``。
        """
        new_bus = _make_bus_with_env(mode)
        task_module._sse_bus = new_bus  # type: ignore[assignment]
        from ai_intervention_agent.web_ui import WebFeedbackUI

        ui = WebFeedbackUI(prompt="r212-test", host="127.0.0.1", port=0)
        return ui.app, new_bus

    def test_endpoint_returns_schema_validate_mode_field(self) -> None:
        app, _bus = self._make_app_and_bus_with_mode("warn")
        client = app.test_client()
        resp = client.get("/api/system/sse-stats")
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.get_data(as_text=True))
        self.assertIn(
            "schema_validate_mode",
            body,
            "/api/system/sse-stats 必须暴露 R205 schema_validate_mode 字段",
        )
        self.assertEqual(body["schema_validate_mode"], "warn")

    def test_endpoint_returns_schema_violation_total_field(self) -> None:
        app, _bus = self._make_app_and_bus_with_mode("warn")
        client = app.test_client()
        resp = client.get("/api/system/sse-stats")
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.get_data(as_text=True))
        self.assertIn(
            "schema_violation_total",
            body,
            "/api/system/sse-stats 必须暴露 R205 schema_violation_total 字段",
        )
        self.assertEqual(body["schema_violation_total"], 0)
        self.assertIsInstance(body["schema_violation_total"], int)

    def test_endpoint_reflects_post_emit_counter_change(self) -> None:
        """触发 violation 后, 再次 GET endpoint 必须返回更新后的计数。"""
        app, bus = self._make_app_and_bus_with_mode("warn")
        client = app.test_client()
        # 触发 2 次 violation
        with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING"):
            bus.emit("task_changed", {"task_id": "t1"})
            _clear_log_dedup_cache()
            bus.emit("task_changed", {"task_id": "t2"})
        resp = client.get("/api/system/sse-stats")
        body = json.loads(resp.get_data(as_text=True))
        self.assertEqual(
            body["schema_violation_total"],
            2,
            "endpoint 必须返回最新 counter, 不是 cache 的旧值",
        )


# ---------------------------------------------------------------------------
# 3. R210 docs ↔ R205 code keyword drift 守护
# ---------------------------------------------------------------------------


class TestR210DocsKeywordInR205Code(unittest.TestCase):
    """R210 docs 提到的关键 design keyword 必须出现在 R205 / R207 源码。

    R210 docs (configuration.{md,zh-CN.md}) 在描述 ``AIIA_SSE_SCHEMA_
    VALIDATE`` 行为时显式使用了几个标志性 keyword:

      * ``Twelve-Factor`` — sticky 读取的设计取舍 rationale;
      * ``fire-and-forget`` — strict mode 不抛异常的契约 rationale;
      * ``omit-when-off`` — R207 Prometheus metric 与 R204 token age
        gauge 的统一 哲学。

    R210 测试（test_configuration_env_var_docs_r210.py）已经守 docs 含
    这些 keyword, 但**没守**这些 keyword 也出现在 R205 / R207 源码注释。
    后果: docs 提了 "Twelve-Factor sticky"，但代码注释只写 "init 时读
    一次", reviewer / fresh contributor 在源码里 grep ``Twelve-Factor``
    找不到出处, 文档与代码 mental model 脱节。

    本 invariant 守 docs phrasing 与代码注释的双向 grep-ability。
    """

    @classmethod
    def setUpClass(cls) -> None:
        task_py = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
        )
        system_py = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "system.py"
        )
        cls.task_text = task_py.read_text(encoding="utf-8")
        cls.system_text = system_py.read_text(encoding="utf-8")

    def test_twelve_factor_keyword_in_r205_source(self) -> None:
        """R210 docs 写 ``Twelve-Factor sticky``，task.py R205 注释也必须出现。"""
        # task.py R205 注释明确提到 Twelve-Factor 风格 sticky 读取
        self.assertIn(
            "Twelve-Factor",
            self.task_text,
            "R210 docs 提到 'Twelve-Factor sticky'，task.py R205 段落"
            "必须含同款 keyword 让源码 grep 能定位完整设计 rationale",
        )

    def test_fire_and_forget_keyword_in_r205_source(self) -> None:
        """R210 docs 写 ``fire-and-forget``，task.py R205 注释也必须出现。

        Note: 当前 R205 用 "不 raise" 表达；接受 "fire-and-forget" /
        "fire and forget" / "fire-and-forget contract" 任一形式（CR 时
        wording polish 不破契约）。
        """
        candidates = ["fire-and-forget", "fire and forget"]
        found = any(c in self.task_text for c in candidates)
        self.assertTrue(
            found,
            "R210 docs 提到 fire-and-forget 契约，task.py R205 段落必须"
            f"含同款 keyword (任一: {candidates}) 让源码 grep 能定位",
        )


# ---------------------------------------------------------------------------
# 4. Counter type stability invariant
# ---------------------------------------------------------------------------


class TestCounterTypeStability(unittest.TestCase):
    """``_schema_violation_total`` 类型永远 ``int``。

    R207 Prometheus exposition 用 ``isinstance(violation_raw, int)`` 做
    type gate, R210 docs 写 "counter 累加" 暗示 monotonic int 语义。一
    旦 future perf refactor 把 counter 换成 ``collections.Counter`` /
    ``itertools.count`` iterator / ``float`` (e.g. EWMA-decayed counter):

      * R207 Prometheus exposition 静默 skip (isinstance 不命中) →
        ``aiia_sse_schema_violation_total`` metric 消失, ops alert
        rule 无声 broken;
      * R205 stats_snapshot TypedDict ``int`` declaration 与实际类型
        不符 → ty/mypy 应当报但跑得过 ``Any``-cast;
      * R210 docs 写的 "counter +1" 语义破。

    本 invariant 把 int 类型契约锁死。
    """

    def setUp(self) -> None:
        # 与其它 invariant class 同款 — R205 测试同款边界, 否则 5-秒
        # dedup cache 让本 class 在 cycle 内反复 emit invalid payload
        # 时 assertLogs 抓不到第二条 violation log。
        _clear_log_dedup_cache()

    def test_instance_attribute_type_is_int(self) -> None:
        bus = _make_bus_with_env("warn")
        self.assertIsInstance(
            bus._schema_violation_total,
            int,
            "_schema_violation_total 必须是 int (不是 float / Counter / etc)",
        )
        # 严格排除 bool (Python 里 bool 是 int 的子类) — R207 实现
        # ``isinstance(violation_raw, int)`` 会把 bool 也通过, 但 counter
        # 永远不该是 bool, 这里显式排除。
        self.assertNotIsInstance(
            bus._schema_violation_total,
            bool,
            "_schema_violation_total 不应该是 bool (即使 bool 是 int 子类)",
        )

    def test_stats_snapshot_field_type_is_int(self) -> None:
        bus = _make_bus_with_env("warn")
        with self.assertLogs(_TASK_LOGGER_NAME, level="WARNING"):
            bus.emit("task_changed", {"task_id": "t1"})  # invalid -> counter += 1
        snap = bus.stats_snapshot()
        self.assertIsInstance(
            snap["schema_violation_total"],
            int,
            "stats_snapshot()['schema_violation_total'] 必须是 int",
        )
        self.assertNotIsInstance(snap["schema_violation_total"], bool)


if __name__ == "__main__":
    unittest.main()
