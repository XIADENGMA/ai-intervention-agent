"""R203 / Cycle 9 · F-202-1 · `_emit_by_type` cardinality cap tests。

设计目标
========

R202 把 ``_SSEBus._emit_by_type: Counter[str]`` 暴露成 Prometheus
``aiia_sse_emit_by_type_total{event_type="..."}``。Counter 本身没有 key
数上限——如果上游 emit 不慎用动态字符串当 event_type（R198 AST guard 已
卡 source-level，但 ``oversize_drop`` 替换路径 + 未来代码误用 / 测试残
留是真实 attack/bug surface），Counter 会无限增长，造成：

1. **Memory leak**: Counter dict 无界增长；
2. **Prometheus exposition payload 膨胀**: scrape 每次拉所有 key，
   Grafana cardinality 爆炸；
3. **Counter pollution**: 一旦混入 1000+ 一次性 type，"top-N" 视图全
   是噪声。

R203 在 ``_SSEBus._lock`` 内增加防御性 cap：

- 上限 ``_EMIT_BY_TYPE_MAX_CARDINALITY = 100`` (R198 4 schema + 余量)；
- cap 触发后新 event_type 累加到 ``_EMIT_BY_TYPE_OVERFLOW_BUCKET =
  "__other__"`` 桶，保 R202 不变量 ``sum(by_type) == emit_total``；
- 全进程 WARN-once (``_emit_by_type_cap_hit_warned`` flag) 避免日志风暴；
- 旧 event_type 计数照常累加，不受影响。

测试覆盖 (10 cases / 4 invariant class + 4 subtests):

1. **Below cap 正常行为** (2): 单 type / 多 type < cap → 无 overflow、无 WARN
2. **At cap 触发** (3): 第 cap+1 个新 type 落到 ``__other__`` + WARN 一次
   + 重复 emit 新 type 不重复 WARN
3. **Cap 之后**老 type 仍累加 + R198 4 schema event 全程不受影响 (2 + 4 subtests)
4. **R202 sum 不变量** cap 触发场景下仍 hold (1)
5. **AST guard** cap-check 必须在 ``with self._lock:`` 内 + overflow 桶累
   加也在锁内 (2)

总计 10 cases + 4 subtests。
"""

from __future__ import annotations

import ast
import logging
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.sse_event_schemas import EVENT_SCHEMAS
from ai_intervention_agent.web_ui_routes import task as task_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_sse_bus_state() -> None:
    """把 module-level ``_sse_bus`` 的 emit 计数 + cap WARN flag 全 reset，
    避免跨 test 状态污染。本函数只接触 R202 / R203 相关字段。"""
    bus = task_module._sse_bus
    with bus._lock:
        bus._emit_total = 0
        bus._emit_by_type.clear()
        bus._emit_by_type_cap_hit_warned = False


def _emit_simple(event_type: str, payload: dict[str, object] | None = None) -> None:
    task_module._sse_bus.emit(event_type, payload or {})


# ---------------------------------------------------------------------------
# 1. Below-cap 正常行为
# ---------------------------------------------------------------------------


class TestBelowCardinalityCap(unittest.TestCase):
    def setUp(self) -> None:
        _reset_sse_bus_state()

    def test_single_event_type_no_overflow_no_warn(self) -> None:
        _emit_simple("task_changed", {"task_id": "t1"})
        snap = task_module._sse_bus.stats_snapshot()
        emit_by_type = snap["emit_by_type"]
        self.assertIsInstance(emit_by_type, dict)
        assert isinstance(emit_by_type, dict)
        self.assertEqual(emit_by_type.get("task_changed"), 1)
        self.assertNotIn(
            task_module._sse_bus._EMIT_BY_TYPE_OVERFLOW_BUCKET, emit_by_type
        )
        self.assertFalse(task_module._sse_bus._emit_by_type_cap_hit_warned)

    def test_many_event_types_below_cap_no_overflow(self) -> None:
        """emit ``cap - 1`` 种 distinct event_type → 全部独立计数，无 overflow
        桶、cap WARN flag 不应设置。"""
        cap = task_module._sse_bus._EMIT_BY_TYPE_MAX_CARDINALITY
        for i in range(cap - 1):
            _emit_simple(f"synthetic_event_{i}", {})
        snap = task_module._sse_bus.stats_snapshot()
        emit_by_type = snap["emit_by_type"]
        assert isinstance(emit_by_type, dict)
        self.assertEqual(len(emit_by_type), cap - 1)
        self.assertNotIn(
            task_module._sse_bus._EMIT_BY_TYPE_OVERFLOW_BUCKET, emit_by_type
        )
        self.assertFalse(task_module._sse_bus._emit_by_type_cap_hit_warned)


# ---------------------------------------------------------------------------
# 2. At-cap 触发
# ---------------------------------------------------------------------------


class TestAtCardinalityCapTrigger(unittest.TestCase):
    def setUp(self) -> None:
        _reset_sse_bus_state()

    def _fill_to_cap(self) -> None:
        cap = task_module._sse_bus._EMIT_BY_TYPE_MAX_CARDINALITY
        for i in range(cap):
            _emit_simple(f"synthetic_event_{i}", {})

    def test_event_type_beyond_cap_routed_to_overflow_bucket(self) -> None:
        self._fill_to_cap()
        _emit_simple("synthetic_event_overflow_1", {})

        snap = task_module._sse_bus.stats_snapshot()
        emit_by_type = snap["emit_by_type"]
        assert isinstance(emit_by_type, dict)
        cap = task_module._sse_bus._EMIT_BY_TYPE_MAX_CARDINALITY
        overflow_bucket = task_module._sse_bus._EMIT_BY_TYPE_OVERFLOW_BUCKET

        self.assertEqual(
            len(emit_by_type),
            cap + 1,
            f"expected cap ({cap}) distinct event_types + 1 overflow bucket, "
            f"got {len(emit_by_type)}; emit_by_type keys = "
            f"{sorted(emit_by_type.keys())}",
        )
        self.assertIn(overflow_bucket, emit_by_type)
        self.assertEqual(emit_by_type[overflow_bucket], 1)

        self.assertNotIn("synthetic_event_overflow_1", emit_by_type)

    def test_cap_warn_emitted_exactly_once(self) -> None:
        self._fill_to_cap()

        with self.assertLogs(
            "ai_intervention_agent.web_ui_routes.task", level="WARNING"
        ) as cm:
            _emit_simple("synthetic_event_overflow_1", {})
            _emit_simple("synthetic_event_overflow_2", {})
            _emit_simple("synthetic_event_overflow_3", {})
        warning_records = [
            r
            for r in cm.records
            if r.levelno >= logging.WARNING and "R203" in r.message
        ]
        self.assertEqual(
            len(warning_records),
            1,
            f"expected exactly 1 R203 WARN, got {len(warning_records)}: "
            f"{[r.message for r in warning_records]}",
        )

        self.assertTrue(task_module._sse_bus._emit_by_type_cap_hit_warned)

    def test_repeated_overflow_emits_accumulate_in_overflow_bucket(self) -> None:
        self._fill_to_cap()
        for _ in range(5):
            _emit_simple("synthetic_event_overflow_X", {})
        for _ in range(3):
            _emit_simple("synthetic_event_overflow_Y", {})

        snap = task_module._sse_bus.stats_snapshot()
        emit_by_type = snap["emit_by_type"]
        assert isinstance(emit_by_type, dict)
        overflow_bucket = task_module._sse_bus._EMIT_BY_TYPE_OVERFLOW_BUCKET

        self.assertEqual(emit_by_type[overflow_bucket], 8)
        self.assertNotIn("synthetic_event_overflow_X", emit_by_type)
        self.assertNotIn("synthetic_event_overflow_Y", emit_by_type)


# ---------------------------------------------------------------------------
# 3. Cap 之后老 type / R198 4 schema event 不受影响
# ---------------------------------------------------------------------------


class TestKnownTypesNotAffectedByCap(unittest.TestCase):
    def setUp(self) -> None:
        _reset_sse_bus_state()

    def test_existing_event_types_still_increment_after_cap_hit(self) -> None:
        _emit_simple("task_changed", {"task_id": "t1"})
        _emit_simple("config_changed", {"section": "web_ui"})

        cap = task_module._sse_bus._EMIT_BY_TYPE_MAX_CARDINALITY
        for i in range(cap):
            _emit_simple(f"synthetic_overflow_filler_{i}", {})

        _emit_simple("task_changed", {"task_id": "t2"})
        _emit_simple("config_changed", {"section": "log_level"})
        _emit_simple("task_changed", {"task_id": "t3"})

        snap = task_module._sse_bus.stats_snapshot()
        emit_by_type = snap["emit_by_type"]
        assert isinstance(emit_by_type, dict)

        self.assertEqual(emit_by_type.get("task_changed"), 3)
        self.assertEqual(emit_by_type.get("config_changed"), 2)

    def test_all_r198_registered_event_types_immune_to_cap(self) -> None:
        """R198 注册的 4 个 event_type 必须能在 cap 触发前/后都正常累加，
        不能因为 cap 而被踢到 ``__other__`` 桶——它们是 first-class events。"""
        for event_type in EVENT_SCHEMAS:
            with self.subTest(event_type=event_type):
                _reset_sse_bus_state()

                cap = task_module._sse_bus._EMIT_BY_TYPE_MAX_CARDINALITY
                _emit_simple(event_type, {})

                for i in range(cap - 1):
                    _emit_simple(f"synthetic_{i}", {})

                _emit_simple(event_type, {})

                snap = task_module._sse_bus.stats_snapshot()
                emit_by_type = snap["emit_by_type"]
                assert isinstance(emit_by_type, dict)
                self.assertEqual(
                    emit_by_type.get(event_type),
                    2,
                    f"R198 event {event_type!r} count should be 2 (pre-fill "
                    f"+ post-fill emit), got "
                    f"{emit_by_type.get(event_type)!r}; emit_by_type 内容="
                    f"{dict(emit_by_type)!r}",
                )


# ---------------------------------------------------------------------------
# 4. R202 sum 不变量 cap 场景下仍 hold
# ---------------------------------------------------------------------------


class TestSumInvariantUnderCap(unittest.TestCase):
    def setUp(self) -> None:
        _reset_sse_bus_state()

    def test_sum_by_type_equals_emit_total_when_cap_hit(self) -> None:
        """**R203 的核心契约**——cap 触发后 R202 的 sum 不变量必须仍然
        严格成立。如果 cap 路径漏掉 overflow 桶累加，sum 会偏小，破坏
        R202 testSumInvariant + 实际 Prometheus dashboard 一致性。"""
        cap = task_module._sse_bus._EMIT_BY_TYPE_MAX_CARDINALITY

        for i in range(cap):
            _emit_simple(f"synthetic_{i}", {})

        for i in range(20):
            _emit_simple(f"overflow_{i}", {})

        snap = task_module._sse_bus.stats_snapshot()
        emit_total = snap["emit_total"]
        emit_by_type = snap["emit_by_type"]
        assert isinstance(emit_by_type, dict)

        self.assertEqual(emit_total, cap + 20)
        self.assertEqual(
            sum(emit_by_type.values()),
            emit_total,
            f"sum(by_type)={sum(emit_by_type.values())} != "
            f"emit_total={emit_total} under cap-hit scenario; "
            f"overflow bucket value = "
            f"{emit_by_type.get(task_module._sse_bus._EMIT_BY_TYPE_OVERFLOW_BUCKET)}",
        )

        overflow_bucket = task_module._sse_bus._EMIT_BY_TYPE_OVERFLOW_BUCKET
        self.assertEqual(emit_by_type.get(overflow_bucket), 20)


# ---------------------------------------------------------------------------
# 5. AST guard · cap-check 必须在 with self._lock 块内
# ---------------------------------------------------------------------------


class TestCardinalityCapLockColocation(unittest.TestCase):
    """**R203 核心契约 #2**：``_SSEBus.emit`` 源码里 cap-check（``if event
    _type not in self._emit_by_type and len(self._emit_by_type) >= self._
    EMIT_BY_TYPE_MAX_CARDINALITY``）必须**在同一 ``with self._lock:`` 块内**，
    且**两个分支**（overflow 桶 ``+= 1`` 与正常 event_type ``+= 1``）都
    在锁内。

    **为什么 runtime test 不够**: cap-check 的 race window 是 "``len(...)``
    读到 ≥ cap，但还没 ``_emit_by_type[...] += 1``" 之间另一线程趁机插入
    新 type，结果 cap 实际被超过 1-2 个。runtime test 难触发，AST 锁结构
    才能挡 refactor 时的疏漏。沿用 R197 ``TestSourceLevelLatencyPath
    Colocation`` + R202 ``TestSseEmitCounterLockColocation`` 同款思路。
    """

    @classmethod
    def setUpClass(cls) -> None:
        src_path = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
        )
        cls.source = src_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _find_sse_bus_emit_method(self) -> ast.FunctionDef:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == "_SSEBus":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "emit":
                        return item
        self.fail("could not find _SSEBus.emit in task.py source")

    def _is_self_lock_with(self, node: ast.With) -> bool:
        return any(
            isinstance(item.context_expr, ast.Attribute)
            and isinstance(item.context_expr.value, ast.Name)
            and item.context_expr.value.id == "self"
            and item.context_expr.attr == "_lock"
            for item in node.items
        )

    def test_cap_check_inside_self_lock_block(self) -> None:
        emit_method = self._find_sse_bus_emit_method()

        for node in ast.walk(emit_method):
            if not isinstance(node, ast.With):
                continue
            if not self._is_self_lock_with(node):
                continue

            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.Compare):
                    continue
                if not (
                    isinstance(stmt.left, ast.Call)
                    and isinstance(stmt.left.func, ast.Name)
                    and stmt.left.func.id == "len"
                    and len(stmt.left.args) == 1
                    and isinstance(stmt.left.args[0], ast.Attribute)
                    and isinstance(stmt.left.args[0].value, ast.Name)
                    and stmt.left.args[0].value.id == "self"
                    and stmt.left.args[0].attr == "_emit_by_type"
                ):
                    continue
                if not stmt.comparators or len(stmt.ops) != 1:
                    continue
                op = stmt.ops[0]
                if not isinstance(op, ast.GtE):
                    continue
                rhs = stmt.comparators[0]
                if not (
                    isinstance(rhs, ast.Attribute)
                    and isinstance(rhs.value, ast.Name)
                    and rhs.value.id == "self"
                    and rhs.attr == "_EMIT_BY_TYPE_MAX_CARDINALITY"
                ):
                    continue
                return

        self.fail(
            "_SSEBus.emit source does NOT contain a `len(self._emit_by_type) "
            ">= self._EMIT_BY_TYPE_MAX_CARDINALITY` cap-check inside a "
            "`with self._lock:` block. R203 cap-check must be lock-protected "
            "to avoid race-window cap overshoot. If you refactored, restore "
            "the structure or update this AST guard."
        )

    def test_overflow_bucket_increment_inside_self_lock_block(self) -> None:
        emit_method = self._find_sse_bus_emit_method()

        for with_node in ast.walk(emit_method):
            if not isinstance(with_node, ast.With):
                continue
            if not self._is_self_lock_with(with_node):
                continue

            for stmt in ast.walk(with_node):
                if not isinstance(stmt, ast.AugAssign):
                    continue
                if not isinstance(stmt.op, ast.Add):
                    continue
                tgt = stmt.target
                if not (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Attribute)
                    and isinstance(tgt.value.value, ast.Name)
                    and tgt.value.value.id == "self"
                    and tgt.value.attr == "_emit_by_type"
                ):
                    continue
                if (
                    isinstance(tgt.slice, ast.Attribute)
                    and isinstance(tgt.slice.value, ast.Name)
                    and tgt.slice.value.id == "self"
                    and tgt.slice.attr == "_EMIT_BY_TYPE_OVERFLOW_BUCKET"
                ):
                    return

        self.fail(
            "_SSEBus.emit source does NOT contain `self._emit_by_type[self._"
            "EMIT_BY_TYPE_OVERFLOW_BUCKET] += 1` inside a `with self._lock:` "
            "block. R203 overflow accumulation must be lock-protected to "
            "preserve R202 sum invariant atomicity."
        )


if __name__ == "__main__":
    unittest.main()
