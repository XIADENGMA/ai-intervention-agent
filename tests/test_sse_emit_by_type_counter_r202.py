"""R202 / Cycle 8 · ``aiia_sse_emit_by_type_total`` Prometheus counter tests。

设计目标
========

R198 在 ``_SSEBus.emit()`` 已经维护了 ``_emit_by_type[event_type] += 1`` 的
per-type 计数（``stats_snapshot()["emit_by_type"]`` 暴露），R202 把这份数据
**通过 Prometheus exposition format 暴露**，方便 Grafana 拉 per-event_type
breakdown。

设计权衡（方案 B vs A）
=======================

方案 A: 给现有 ``aiia_sse_emit_total`` 加 ``event_type`` label。

- 问题：Prometheus 不允许同一 metric name 在不同 series 间切换 label set
  ——已有未标签化 series ``aiia_sse_emit_total 42`` 加 label 后变成
  ``aiia_sse_emit_total{event_type="..."} N``，strict parser 会报
  ``inconsistent labels for metric family``；Grafana 历史曲线也会断。

方案 B（**本 R202 采用**）：新增独立 metric ``aiia_sse_emit_by_type_total
{event_type="..."}``，与现有未标签化的 ``aiia_sse_emit_total`` 并存。

- 优点：100% 向后兼容；Grafana 老 dashboard 继续工作；新 dashboard 可用
  per-type breakdown；不变量 ``sum(by_type series) == aiia_sse_emit_total``
  让 metric correctness 显式可验证（本测试 4.x 锁定）。
- 缺点：metric 数量 +1 family + N series（N == event_type 数 == 4 当前）；
  Prometheus storage 微增（4 series × 16 bytes ≈ 64 bytes/scrape，可忽略）。

测试覆盖
========

1. **Rendering 正确性** (4 cases): 单 type / 多 type / 零 emit 不出 family /
   exposition 格式合规 (HELP/TYPE/quoting/排序确定性)
2. **不变量 sum(by_type) == emit_total** (2 cases): 同步快照 / 多 emit 累积
3. **R198 schema 覆盖** (2 cases): 4 个已注册 event_type 全部可渲染 + 未注
   册 type 也能渲染（防止 silently 漏 emit）
4. **AST guard · _emit_total 与 _emit_by_type 在同一 with self._lock 块**
   (2 cases): R202 的核心契约——sum 不变量靠 source-level lock co-location
   保证，refactor 把任一行挪出锁会破坏 atomicity
5. **向后兼容** (2 cases): 老 ``aiia_sse_emit_total`` 仍存在 + 仍不带 label

总计 12 cases。
"""

from __future__ import annotations

import ast
import sys
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.sse_event_schemas import EVENT_SCHEMAS
from ai_intervention_agent.web_ui_routes import system as system_module
from ai_intervention_agent.web_ui_routes import task as task_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_sse_bus_state() -> None:
    """把 module-level ``_sse_bus`` 的 emit 计数 reset 到 0，避免跨 test
    历史累计干扰 sum 不变量。本函数只接触 R202 关注的 ``_emit_total`` /
    ``_emit_by_type``，不动 history / subscribers (其他 test 可能依赖)。"""
    bus = task_module._sse_bus
    with bus._lock:
        bus._emit_total = 0
        bus._emit_by_type.clear()


def _emit_simple(event_type: str, payload: dict[str, object] | None = None) -> None:
    """直接调 ``_sse_bus.emit``，payload 缺省给空 dict。"""
    task_module._sse_bus.emit(event_type, payload or {})


# ---------------------------------------------------------------------------
# 1. Rendering 正确性
# ---------------------------------------------------------------------------


class TestSseEmitByTypeCounterRendering(unittest.TestCase):
    def setUp(self) -> None:
        _reset_sse_bus_state()

    def test_single_event_type_renders_one_series(self) -> None:
        _emit_simple("task_changed", {"task_id": "t1"})
        output = system_module._render_prometheus_metrics()
        self.assertIn("aiia_sse_emit_by_type_total", output)
        self.assertIn(
            'aiia_sse_emit_by_type_total{event_type="task_changed"} 1', output
        )

    def test_multiple_event_types_render_independent_series(self) -> None:
        _emit_simple("task_changed", {"task_id": "t1"})
        _emit_simple("task_changed", {"task_id": "t2"})
        _emit_simple("config_changed", {"section": "web_ui"})
        output = system_module._render_prometheus_metrics()
        self.assertIn(
            'aiia_sse_emit_by_type_total{event_type="task_changed"} 2', output
        )
        self.assertIn(
            'aiia_sse_emit_by_type_total{event_type="config_changed"} 1', output
        )

    def test_zero_emits_omits_metric_family(self) -> None:
        """没 emit 过任何 event 时 by_type counter family 应该完全不输出，
        避免空 ``# HELP/# TYPE`` header 污染 exposition（Prometheus parser
        允许，但增加 scrape size 且让 Grafana 出现 "no data" placeholder）。
        """
        output = system_module._render_prometheus_metrics()
        self.assertNotIn("aiia_sse_emit_by_type_total", output)

    def test_exposition_format_compliant(self) -> None:
        """HELP/TYPE 各只出现一次（R187 灾难性 bug 复现守护），label 值正确
        加引号，event_type 按字典序排序使输出 deterministic。"""
        _emit_simple("task_changed", {"task_id": "t1"})
        _emit_simple("config_changed", {"section": "web_ui"})
        _emit_simple("log_level_changed", {"old": "INFO", "new": "DEBUG"})
        output = system_module._render_prometheus_metrics()

        help_count = output.count("# HELP aiia_sse_emit_by_type_total")
        type_count = output.count("# TYPE aiia_sse_emit_by_type_total")
        self.assertEqual(help_count, 1, "HELP must appear exactly once")
        self.assertEqual(type_count, 1, "TYPE must appear exactly once")

        self.assertIn("# TYPE aiia_sse_emit_by_type_total counter\n", output)

        family_lines = [
            line
            for line in output.splitlines()
            if line.startswith("aiia_sse_emit_by_type_total{")
        ]
        labels_in_order = [
            line.split('event_type="', 1)[1].split('"', 1)[0] for line in family_lines
        ]
        self.assertEqual(labels_in_order, sorted(labels_in_order))


# ---------------------------------------------------------------------------
# 2. 不变量 sum(by_type) == emit_total
# ---------------------------------------------------------------------------


class TestSseEmitByTypeSumInvariant(unittest.TestCase):
    def setUp(self) -> None:
        _reset_sse_bus_state()

    def test_sum_by_type_equals_emit_total_after_emits(self) -> None:
        _emit_simple("task_changed", {"task_id": "t1"})
        _emit_simple("task_changed", {"task_id": "t2"})
        _emit_simple("config_changed", {"section": "web_ui"})
        _emit_simple("log_level_changed", {"old": "INFO", "new": "DEBUG"})

        snap = task_module._sse_bus.stats_snapshot()
        emit_total = snap["emit_total"]
        emit_by_type = snap["emit_by_type"]
        self.assertIsInstance(emit_by_type, dict)
        assert isinstance(emit_by_type, dict)
        self.assertEqual(
            sum(emit_by_type.values()),
            emit_total,
            f"sum(by_type)={sum(emit_by_type.values())} != "
            f"emit_total={emit_total}; "
            f"by_type breakdown={dict(emit_by_type)}",
        )

    def test_sum_invariant_holds_under_concurrent_emits(self) -> None:
        """在多线程并发 emit 下，最终 sum 也必须严格相等——这是 R202 sum
        不变量的最严格守护（之所以靠谱：emit 内部 ``_emit_total += 1`` 与
        ``_emit_by_type[...] += 1`` 在同一个 ``with self._lock`` 内原子完
        成；AST guard 在测试 4.x 锁定这个 source-level structure）。"""
        n_threads = 8
        emits_per_thread = 50
        types = ["task_changed", "config_changed", "log_level_changed"]
        barrier = threading.Barrier(n_threads)

        def worker(tid: int) -> None:
            barrier.wait()
            for i in range(emits_per_thread):
                _emit_simple(types[(tid + i) % len(types)], {"i": i})

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = task_module._sse_bus.stats_snapshot()
        emit_total = snap["emit_total"]
        emit_by_type = snap["emit_by_type"]
        assert isinstance(emit_by_type, dict)
        self.assertEqual(emit_total, n_threads * emits_per_thread)
        self.assertEqual(sum(emit_by_type.values()), emit_total)


# ---------------------------------------------------------------------------
# 3. R198 schema 覆盖
# ---------------------------------------------------------------------------


class TestSseEmitByTypeSchemaCoverage(unittest.TestCase):
    def setUp(self) -> None:
        _reset_sse_bus_state()

    def test_all_registered_event_types_renderable(self) -> None:
        """R198 注册的 4 个 event_type 全部 emit 一次后，by_type counter
        都能在 exposition 中找到对应 series。**未来加 event 必须同步**：
        如果 R198 在 schema 加了第 5 个 event 但 bus.emit 没真的被任何
        feature code 调到，这个测试不会 fail（不属于 R202 守护范围）；
        但 R198 自己的 AST guard (test_sse_event_schemas_r198::Test
        EmitSiteCoverage) 已经守护 source-level 一致性。"""
        for event_type in EVENT_SCHEMAS:
            with self.subTest(event_type=event_type):
                _reset_sse_bus_state()
                _emit_simple(event_type, {})
                output = system_module._render_prometheus_metrics()
                self.assertIn(
                    f'aiia_sse_emit_by_type_total{{event_type="{event_type}"}}',
                    output,
                    f"emit({event_type!r}) does NOT appear in Prometheus "
                    "exposition — _render_prometheus_metrics SSE bus section "
                    "may be filtering unknown types.",
                )

    def test_unregistered_event_type_still_rendered(self) -> None:
        """defensive: 即便 emit 了一个 R198 没注册的 event_type（比如
        ``oversize_drop`` 替换路径），R202 的 counter 也必须如实呈现
        ——不能"silently drop"，否则 sum invariant 会破坏。"""
        _emit_simple("oversize_drop", {"reason": "test"})
        output = system_module._render_prometheus_metrics()
        self.assertIn(
            'aiia_sse_emit_by_type_total{event_type="oversize_drop"} 1', output
        )


# ---------------------------------------------------------------------------
# 4. AST guard · source-level lock co-location 不变量
# ---------------------------------------------------------------------------


class TestSseEmitCounterLockColocation(unittest.TestCase):
    """**R202 核心契约**：``_SSEBus.emit`` 源码里 ``self._emit_total += 1``
    与 ``self._emit_by_type[event_type] += 1`` 必须**在同一个**
    ``with self._lock:`` 块内紧贴。

    **为什么 runtime test 不够**：``TestSseEmitByTypeSumInvariant.
    test_sum_invariant_holds_under_concurrent_emits`` 已经做了 8 线程 × 50
    次 emit 的并发压测，但 race window 极窄（两条 ``+= 1`` 之间只差几条
    bytecode）；如果未来 refactor 把 ``_emit_by_type[...] += 1`` 挪到锁外，
    runtime test 在 CI 上**仍可能全 PASS**（race window 触发概率不到 1%），
    然后 prod 上偶尔出现 ``sum(by_type) != emit_total`` 的诡异 bug。**只有
    AST 锁住 source 结构**才能让 refactor diff 一眼挂掉。

    本设计模式来自 CR#16 §3.5「structural invariants vs runtime tests」+
    R197 ``TestSourceLevelLatencyPathColocation`` 同款思路。
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

    def test_emit_total_and_by_type_increment_in_same_lock_block(self) -> None:
        emit_method = self._find_sse_bus_emit_method()

        for node in ast.walk(emit_method):
            if not isinstance(node, ast.With):
                continue
            is_self_lock = any(
                isinstance(item.context_expr, ast.Attribute)
                and isinstance(item.context_expr.value, ast.Name)
                and item.context_expr.value.id == "self"
                and item.context_expr.attr == "_lock"
                for item in node.items
            )
            if not is_self_lock:
                continue

            saw_emit_total_inc = False
            saw_by_type_inc = False
            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.AugAssign):
                    continue
                if not isinstance(stmt.op, ast.Add):
                    continue

                tgt = stmt.target
                if (
                    isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "self"
                    and tgt.attr == "_emit_total"
                ):
                    saw_emit_total_inc = True

                if isinstance(tgt, ast.Subscript) and (
                    (
                        isinstance(tgt.value, ast.Attribute)
                        and isinstance(tgt.value.value, ast.Name)
                        and tgt.value.value.id == "self"
                        and tgt.value.attr == "_emit_by_type"
                    )
                    or (
                        isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "emit_by_type"
                    )
                ):
                    saw_by_type_inc = True

            if saw_emit_total_inc and saw_by_type_inc:
                return

        self.fail(
            "_SSEBus.emit source does NOT contain a `with self._lock:` block "
            "that increments BOTH `self._emit_total` AND `self._emit_by_type"
            "[<event_type>]` — R202 sum invariant requires these two to be "
            "atomic. If you refactored, restore the co-location or update "
            "the invariant guard in TestSseEmitCounterLockColocation."
        )

    def test_no_orphan_emit_by_type_increment_outside_lock(self) -> None:
        """补充守护：整个 ``emit`` 方法里 ``self._emit_by_type[...] += 1``
        必须**只**出现在 ``with self._lock`` 块内——避免有人把累加复制
        到锁外做"快速路径"破坏原子性。"""
        emit_method = self._find_sse_bus_emit_method()

        lock_block_lines: set[int] = set()
        for node in ast.walk(emit_method):
            if isinstance(node, ast.With) and any(
                isinstance(item.context_expr, ast.Attribute)
                and isinstance(item.context_expr.value, ast.Name)
                and item.context_expr.value.id == "self"
                and item.context_expr.attr == "_lock"
                for item in node.items
            ):
                start = node.lineno
                end = node.end_lineno or start
                lock_block_lines.update(range(start, end + 1))

        orphan_increments: list[int] = []
        for node in ast.walk(emit_method):
            if not isinstance(node, ast.AugAssign):
                continue
            if not isinstance(node.op, ast.Add):
                continue
            tgt = node.target
            if not (
                isinstance(tgt, ast.Subscript)
                and (
                    (
                        isinstance(tgt.value, ast.Attribute)
                        and isinstance(tgt.value.value, ast.Name)
                        and tgt.value.value.id == "self"
                        and tgt.value.attr == "_emit_by_type"
                    )
                    or (
                        isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "emit_by_type"
                    )
                )
            ):
                continue
            if node.lineno not in lock_block_lines:
                orphan_increments.append(node.lineno)

        self.assertEqual(
            orphan_increments,
            [],
            f"_SSEBus.emit has `_emit_by_type[...] += 1` at lines "
            f"{orphan_increments} OUTSIDE `with self._lock:` — breaks "
            "R202 sum invariant atomicity.",
        )


# ---------------------------------------------------------------------------
# 5. 向后兼容
# ---------------------------------------------------------------------------


class TestBackwardCompatibility(unittest.TestCase):
    def setUp(self) -> None:
        _reset_sse_bus_state()

    def test_aiia_sse_emit_total_still_exists_unlabeled(self) -> None:
        """方案 B 的关键不变量：原 ``aiia_sse_emit_total`` 仍以 **无 label**
        形式存在，老 Grafana dashboard / Prometheus query 不会断。"""
        _emit_simple("task_changed", {"task_id": "t1"})
        output = system_module._render_prometheus_metrics()

        self.assertIn("# HELP aiia_sse_emit_total ", output)
        self.assertIn("# TYPE aiia_sse_emit_total counter\n", output)
        self.assertIn("\naiia_sse_emit_total 1\n", output)
        self.assertNotIn("aiia_sse_emit_total{", output)

    def test_two_metric_families_are_distinct(self) -> None:
        """``aiia_sse_emit_total`` 和 ``aiia_sse_emit_by_type_total`` 是
        Prometheus 看的两个独立 metric family；R202 引入新 family 不影响
        旧 family 的 HELP/TYPE/value 任何字段。"""
        _emit_simple("task_changed", {"task_id": "t1"})
        output = system_module._render_prometheus_metrics()

        self.assertEqual(output.count("# HELP aiia_sse_emit_total "), 1)
        self.assertEqual(output.count("# HELP aiia_sse_emit_by_type_total "), 1)
        self.assertEqual(output.count("# TYPE aiia_sse_emit_total counter"), 1)
        self.assertEqual(output.count("# TYPE aiia_sse_emit_by_type_total counter"), 1)


if __name__ == "__main__":
    unittest.main()
