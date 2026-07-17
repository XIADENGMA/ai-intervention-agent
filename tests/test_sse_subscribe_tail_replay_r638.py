"""R638 · SSE subscribe tail replay scans only the needed history suffix."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _HistoryProbe:
    def __init__(self, items: list[tuple[int, dict[str, Any]]]) -> None:
        self._items = items
        self.reversed_steps = 0

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> tuple[int, dict[str, Any]]:
        return self._items[index]

    def __iter__(self) -> Any:
        raise AssertionError("tail replay should not iterate history from the left")

    def __reversed__(self) -> Any:
        for item in reversed(self._items):
            self.reversed_steps += 1
            yield item


def test_subscribe_tail_replay_stops_after_needed_suffix() -> None:
    bus = _SSEBus()
    history = _HistoryProbe(
        [
            (i, {"id": i, "type": "task_changed", "data": {"task_id": str(i)}})
            for i in range(1, 129)
        ]
    )
    object.__setattr__(bus, "_history", history)

    q = bus.subscribe(after_id=126)

    replayed = [q.get_nowait(), q.get_nowait()]
    assert [payload["id"] for payload in replayed] == [127, 128]
    assert q.empty()
    assert history.reversed_steps == 3


def test_subscribe_tail_replay_source_uses_reversed_history() -> None:
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

    reversed_history_loop_found = False
    replay_reverse_found = False
    old_full_scan_found = False
    for node in ast.walk(subscribe_method):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
            call = node.iter
            if (
                isinstance(call.func, ast.Name)
                and call.func.id == "reversed"
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Attribute)
                and isinstance(call.args[0].value, ast.Name)
                and call.args[0].value.id == "self"
                and call.args[0].attr == "_history"
            ):
                reversed_history_loop_found = True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "replay_items"
            and node.func.attr == "reverse"
        ):
            replay_reverse_found = True
        if isinstance(node, ast.ListComp):
            for generator in node.generators:
                if (
                    isinstance(generator.iter, ast.Attribute)
                    and isinstance(generator.iter.value, ast.Name)
                    and generator.iter.value.id == "self"
                    and generator.iter.attr == "_history"
                    and any(
                        isinstance(if_node, ast.Compare)
                        and isinstance(if_node.left, ast.Name)
                        and if_node.left.id == "evt_id"
                        and len(if_node.ops) == 1
                        and isinstance(if_node.ops[0], ast.Gt)
                        and len(if_node.comparators) == 1
                        and isinstance(if_node.comparators[0], ast.Name)
                        and if_node.comparators[0].id == "after_id"
                        for if_node in generator.ifs
                    )
                ):
                    old_full_scan_found = True

    assert reversed_history_loop_found
    assert replay_reverse_found
    assert not old_full_scan_found
