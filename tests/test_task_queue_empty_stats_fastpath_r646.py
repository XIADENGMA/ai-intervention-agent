"""R646 - empty TaskQueue stats avoid generic values() scan setup."""

from __future__ import annotations

import inspect
from typing import Any, cast

from ai_intervention_agent.task_queue import TaskQueue


class _ExplodingValuesDict(dict[str, object]):
    def values(self):  # type: ignore[no-untyped-def]
        raise AssertionError("empty fast path must not call values()")


def _empty_stats(max_tasks: int) -> dict[str, int]:
    return {
        "total": 0,
        "pending": 0,
        "active": 0,
        "completed": 0,
        "max": max_tasks,
    }


def test_get_all_tasks_with_stats_empty_path_skips_values_scan() -> None:
    queue = TaskQueue(max_tasks=17)
    try:
        queue._tasks = cast(Any, _ExplodingValuesDict())

        tasks, stats = queue.get_all_tasks_with_stats()

        assert tasks == []
        assert stats == _empty_stats(17)
    finally:
        queue.stop_cleanup()


def test_get_task_count_empty_path_skips_values_scan() -> None:
    queue = TaskQueue(max_tasks=23)
    try:
        queue._tasks = cast(Any, _ExplodingValuesDict())

        stats = queue.get_task_count()

        assert stats == _empty_stats(23)
    finally:
        queue.stop_cleanup()


def test_non_empty_queue_keeps_existing_snapshot_counts() -> None:
    queue = TaskQueue(max_tasks=10)
    try:
        queue.add_task("r646-a", "alpha")
        queue.add_task("r646-b", "bravo")
        queue.complete_task("r646-a", {"feedback": "ok"})

        tasks, stats = queue.get_all_tasks_with_stats()

        assert [task.task_id for task in tasks] == ["r646-a", "r646-b"]
        assert stats == {
            "total": 2,
            "pending": 0,
            "active": 1,
            "completed": 1,
            "max": 10,
        }
        assert queue.get_task_count() == stats
    finally:
        queue.stop_cleanup()


def test_task_queue_count_methods_check_empty_before_values_loop() -> None:
    all_tasks_source = inspect.getsource(TaskQueue.get_all_tasks_with_stats)
    count_source = inspect.getsource(TaskQueue.get_task_count)

    for source in (all_tasks_source, count_source):
        assert "if not self._tasks:" in source
        assert source.index("if not self._tasks:") < source.index(
            "for t in self._tasks.values():"
        )
        assert '"total": 0' in source
        assert '"pending": 0' in source
        assert '"active": 0' in source
        assert '"completed": 0' in source
