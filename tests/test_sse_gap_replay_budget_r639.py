"""R639 · SSE gap_warning replay copies only queue-visible history prefix."""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _GapHistoryProbe:
    def __init__(self, items: list[tuple[int, dict[str, Any]]]) -> None:
        self._items = items
        self.iter_steps = 0

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> tuple[int, dict[str, Any]]:
        return self._items[index]

    def __iter__(self) -> Iterator[tuple[int, dict[str, Any]]]:
        for item in self._items:
            self.iter_steps += 1
            if self.iter_steps > _SSEBus._QUEUE_MAXSIZE - 1:
                raise AssertionError("gap replay should stop at visible queue budget")
            yield item


def test_evicted_gap_replay_stops_at_queue_visible_prefix() -> None:
    bus = _SSEBus()
    history = _GapHistoryProbe(
        [
            (i, {"id": i, "type": "task_changed", "data": {"task_id": str(i)}})
            for i in range(1, 129)
        ]
    )
    object.__setattr__(bus, "_history", history)

    q = bus.subscribe(after_id=-1)

    items = [q.get_nowait() for _ in range(q.qsize())]
    assert items[0]["type"] == "gap_warning"
    replayed_ids = [item["id"] for item in items[1:]]
    assert replayed_ids == list(range(1, bus._QUEUE_MAXSIZE))
    assert history.iter_steps == bus._QUEUE_MAXSIZE - 1


def test_gap_replay_source_uses_explicit_replay_budget() -> None:
    source_path = (
        REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    subscribe_method: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_SSEBus":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "subscribe":
                    subscribe_method = item
                    break
    assert subscribe_method is not None

    replay_budget_assignment_found = False
    replay_enumerate_loop_found = False
    replay_budget_break_found = False
    full_history_copy_found = False
    for node in ast.walk(subscribe_method):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "replay_budget"
                for target in node.targets
            )
            and isinstance(node.value, ast.BinOp)
            and isinstance(node.value.left, ast.Attribute)
            and node.value.left.attr == "_QUEUE_MAXSIZE"
            and isinstance(node.value.op, ast.Sub)
            and isinstance(node.value.right, ast.Constant)
            and node.value.right.value == 1
        ):
            replay_budget_assignment_found = True
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            target_names = [
                target.id
                for target in ast.walk(node.target)
                if isinstance(target, ast.Name)
            ]
            if (
                "replay_count" in target_names
                and isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "enumerate"
                and len(node.iter.args) == 2
                and isinstance(node.iter.args[0], ast.Attribute)
                and isinstance(node.iter.args[0].value, ast.Name)
                and node.iter.args[0].value.id == "self"
                and node.iter.args[0].attr == "_history"
                and isinstance(node.iter.args[1], ast.Constant)
                and node.iter.args[1].value == 1
            ):
                replay_enumerate_loop_found = True
        if isinstance(node, ast.If) and any(
            isinstance(child, ast.Break) for child in ast.walk(node)
        ):
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "replay_count"
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.GtE)
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Name)
                and test.comparators[0].id == "replay_budget"
            ):
                replay_budget_break_found = True
        if isinstance(node, ast.ListComp):
            for generator in node.generators:
                if (
                    isinstance(generator.iter, ast.Attribute)
                    and isinstance(generator.iter.value, ast.Name)
                    and generator.iter.value.id == "self"
                    and generator.iter.attr == "_history"
                    and not generator.ifs
                ):
                    full_history_copy_found = True

    assert replay_budget_assignment_found
    assert replay_enumerate_loop_found
    assert replay_budget_break_found
    assert not full_history_copy_found
