"""R452 task-count counter decision invariants.

The tempting optimization is to maintain pending/active/completed counters on
every mutation. For the current product shape that is extra shared state, not a
measured win: TaskQueue defaults to max_tasks=10, completed tasks are cleaned
quickly, and correctness of status transitions matters more than shaving a tiny
O(n) loop.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from ai_intervention_agent.task_queue import TaskQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_QUEUE_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "task_queue.py"
PERF_DOC_EN = REPO_ROOT / "docs" / "perf-mcp-cold-start.md"
PERF_DOC_ZH = REPO_ROOT / "docs" / "perf-mcp-cold-start.zh-CN.md"


def _task_queue_source() -> str:
    return TASK_QUEUE_PY.read_text(encoding="utf-8")


def _method_source(method_name: str) -> str:
    module = ast.parse(_task_queue_source())
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "TaskQueue":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return ast.get_source_segment(_task_queue_source(), item) or ""
    raise AssertionError(f"TaskQueue.{method_name} not found")


def test_default_max_tasks_stays_small_enough_for_snapshot_counting() -> None:
    signature = inspect.signature(TaskQueue)

    assert signature.parameters["max_tasks"].default == 10


def test_get_task_count_remains_snapshot_based_not_maintained_counters() -> None:
    source = _method_source("get_task_count")

    assert "with self._lock.read_lock()" in source
    assert "for t in self._tasks.values()" in source
    assert "counts[t.status] += 1" in source
    assert "len(self._tasks)" in source

    maintained_counter_names = (
        "_pending_count",
        "_active_count",
        "_completed_count",
        "_task_counts",
        "_status_counts",
    )
    full_source = _task_queue_source()
    for name in maintained_counter_names:
        assert name not in full_source


def test_counter_decision_is_documented_bilingually() -> None:
    english = PERF_DOC_EN.read_text(encoding="utf-8")
    chinese = PERF_DOC_ZH.read_text(encoding="utf-8")

    assert "R452 counter decision" in english
    assert "max_tasks=10" in english
    assert "maintained counters" in english
    assert "benchmark shows queue stats as a bottleneck" in english

    assert "R452 计数器决策" in chinese
    assert "max_tasks=10" in chinese
    assert "维护型 counters" in chinese
    assert "benchmark" in chinese
