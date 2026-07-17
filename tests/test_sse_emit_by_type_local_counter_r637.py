"""R637 · SSE emit hot path binds ``_emit_by_type`` once inside the lock."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes import task as task_module


class _TrackingSSEBus(task_module._SSEBus):
    def __init__(self) -> None:
        object.__setattr__(self, "emit_by_type_reads", 0)
        super().__init__()

    def __getattribute__(self, name: str) -> Any:
        if name == "_emit_by_type":
            object.__setattr__(
                self,
                "emit_by_type_reads",
                object.__getattribute__(self, "emit_by_type_reads") + 1,
            )
        return super().__getattribute__(name)

    def reset_emit_by_type_reads(self) -> None:
        object.__setattr__(self, "emit_by_type_reads", 0)


def test_known_event_type_emit_reads_emit_by_type_once() -> None:
    bus = _TrackingSSEBus()
    with bus._lock:
        bus._emit_by_type["task_changed"] = 1
        bus._emit_total = 1
        bus._next_id = 1

    bus.reset_emit_by_type_reads()
    bus.emit("task_changed", {"task_id": "t1"})

    assert object.__getattribute__(bus, "emit_by_type_reads") == 1
    snap = bus.stats_snapshot()
    assert snap["emit_total"] == 2
    assert snap["emit_by_type"] == {"task_changed": 2}


def test_overflow_emit_reads_emit_by_type_once() -> None:
    bus = _TrackingSSEBus()
    cap = bus._EMIT_BY_TYPE_MAX_CARDINALITY
    overflow_bucket = bus._EMIT_BY_TYPE_OVERFLOW_BUCKET
    with bus._lock:
        for i in range(cap):
            bus._emit_by_type[f"synthetic_event_{i}"] = 1
        bus._emit_total = cap
        bus._next_id = cap
        bus._emit_by_type_cap_hit_warned = True

    bus.reset_emit_by_type_reads()
    bus.emit("synthetic_event_overflow", {})

    assert object.__getattribute__(bus, "emit_by_type_reads") == 1
    snap = bus.stats_snapshot()
    assert snap["emit_total"] == cap + 1
    assert snap["emit_by_type"][overflow_bucket] == 1
    assert "synthetic_event_overflow" not in snap["emit_by_type"]


def test_emit_source_uses_local_emit_by_type_inside_lock() -> None:
    source_path = (
        REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    emit_method: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_SSEBus":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "emit":
                    emit_method = item
                    break
    assert emit_method is not None

    lock_blocks = [
        node
        for node in ast.walk(emit_method)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Attribute)
            and isinstance(item.context_expr.value, ast.Name)
            and item.context_expr.value.id == "self"
            and item.context_expr.attr == "_lock"
            for item in node.items
        )
    ]
    counter_lock_block: ast.With | None = None
    for lock_block in lock_blocks:
        if any(
            isinstance(stmt, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "emit_by_type"
                for target in stmt.targets
            )
            and isinstance(stmt.value, ast.Attribute)
            and isinstance(stmt.value.value, ast.Name)
            and stmt.value.value.id == "self"
            and stmt.value.attr == "_emit_by_type"
            for stmt in lock_block.body
        ):
            counter_lock_block = lock_block
            break

    assert counter_lock_block is not None

    local_counter_increments: list[ast.AugAssign] = []
    direct_counter_increments: list[ast.AugAssign] = []
    for stmt in ast.walk(counter_lock_block):
        if not isinstance(stmt, ast.AugAssign):
            continue
        if not isinstance(stmt.target, ast.Subscript):
            continue
        target_value = stmt.target.value
        if isinstance(target_value, ast.Name) and target_value.id == "emit_by_type":
            local_counter_increments.append(stmt)
        if (
            isinstance(target_value, ast.Attribute)
            and isinstance(target_value.value, ast.Name)
            and target_value.value.id == "self"
            and target_value.attr == "_emit_by_type"
        ):
            direct_counter_increments.append(stmt)

    assert len(local_counter_increments) == 2
    assert direct_counter_increments == []
