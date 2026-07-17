from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch

import ai_intervention_agent.task_queue as task_queue


def _clear_pending_records() -> None:
    with task_queue._pending_acquisitions_lock:
        task_queue._pending_acquisitions.clear()


def test_lock_watchdog_slow_record_snapshot_uses_dict_copy() -> None:
    source = inspect.getsource(task_queue._scan_pending_and_dump_slow)

    assert "slow_records.append(rec.copy())" in source
    assert "slow_records.append(dict(rec))" not in source


def test_lock_watchdog_slow_record_copy_is_isolated_from_registry() -> None:
    original_timeout = task_queue._LOCK_WATCHDOG_TIMEOUT_S
    original_capture = task_queue._capture_all_thread_stacks
    _clear_pending_records()

    record: dict[str, Any] = {
        "label": "r674-slow",
        "thread_id": 123,
        "start": 0.0,
        "dumped": False,
    }
    try:
        task_queue._LOCK_WATCHDOG_TIMEOUT_S = 0.1
        with task_queue._pending_acquisitions_lock:
            task_queue._pending_acquisitions[1] = record

        captured: list[dict[str, Any]] = []

        def mutate_registry_after_snapshot() -> str:
            with task_queue._pending_acquisitions_lock:
                record["label"] = "polluted"
                record["thread_id"] = 999
            return "stack snapshot"

        def capture_logged_record(message: str) -> None:
            captured.append(
                {
                    "message": message,
                    "registry_label": record["label"],
                    "registry_thread_id": record["thread_id"],
                    "registry_dumped": record["dumped"],
                }
            )

        with (
            patch("ai_intervention_agent.task_queue.time.monotonic", return_value=1.0),
            patch.object(
                task_queue,
                "_capture_all_thread_stacks",
                side_effect=mutate_registry_after_snapshot,
            ),
            patch.object(
                task_queue.logger,
                "error",
                side_effect=capture_logged_record,
            ),
        ):
            dumped_count = task_queue._scan_pending_and_dump_slow()

        assert dumped_count == 1
        assert captured == [
            {
                "message": (
                    "⚠️ TaskQueue 写锁卡死 > 0s "
                    "(label=r674-slow, waiting_thread_id=123, waited=1.0s)\n"
                    "全线程栈快照：\nstack snapshot"
                ),
                "registry_label": "polluted",
                "registry_thread_id": 999,
                "registry_dumped": True,
            }
        ]
    finally:
        task_queue._LOCK_WATCHDOG_TIMEOUT_S = original_timeout
        task_queue._capture_all_thread_stacks = original_capture
        _clear_pending_records()
