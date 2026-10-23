"""R835 - extending or freezing a countdown reaches ``tasks.json``.

Symptom: ``extend_task_deadline`` and ``freeze_task_deadline`` change
``auto_resubmit_timeout`` - a field the snapshot stores - but never called ``_persist()``
(the same omission R-hot-reload fixed for ``update_auto_resubmit_timeout_for_all``). Until
some other change happened to rewrite the file, ``tasks.json`` still held the old
countdown. When the Web UI restarted in that window, a question the user had frozen
("no timeout, I will answer later") came back with its countdown running and could be
auto-resubmitted to the AI, and an extension of the countdown was gone.

Fix: both methods persist after a *successful* change, outside the write lock (the R22.2
contract: post-write side effects run after the lock is released). Failures change
nothing and write nothing.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ai_intervention_agent.task_queue import TaskQueue, TaskStatus

EXTEND = {"max_extends": 3, "min_seconds": 10, "max_seconds": 600}


@pytest.fixture
def persist_path(tmp_path: Path) -> Path:
    return tmp_path / "tasks.json"


@pytest.fixture
def queue(persist_path: Path) -> Iterator[TaskQueue]:
    q = TaskQueue(max_tasks=20, persist_path=str(persist_path))
    try:
        yield q
    finally:
        q.stop_cleanup()


def _restored(persist_path: Path) -> TaskQueue:
    return TaskQueue(max_tasks=20, persist_path=str(persist_path))


def _timeout_on_disk(persist_path: Path, task_id: str) -> int:
    data = json.loads(persist_path.read_text(encoding="utf-8"))
    return next(
        item["auto_resubmit_timeout"]
        for item in data["tasks"]
        if item["task_id"] == task_id
    )


class TestExtendPersistsR835:
    def test_extension_is_in_the_file_and_survives_a_restart(
        self, queue: TaskQueue, persist_path: Path
    ) -> None:
        assert queue.add_task("t1", "question", auto_resubmit_timeout=300)

        ok, error, used, timeout = queue.extend_task_deadline("t1", 60, **EXTEND)

        assert (ok, error, used, timeout) == (True, None, 1, 360)
        assert _timeout_on_disk(persist_path, "t1") == 360
        revived = _restored(persist_path)
        try:
            task = revived.get_task("t1")
            assert task is not None
            assert task.auto_resubmit_timeout == 360
        finally:
            revived.stop_cleanup()

    @pytest.mark.parametrize(
        ("task_id", "seconds", "error"),
        [
            ("missing", 60, "task_not_found"),
            ("t1", 5, "invalid_seconds"),
            ("t1", 601, "invalid_seconds"),
        ],
    )
    def test_refused_extension_writes_nothing(
        self,
        queue: TaskQueue,
        persist_path: Path,
        task_id: str,
        seconds: int,
        error: str,
    ) -> None:
        assert queue.add_task("t1", "question", auto_resubmit_timeout=300)
        before = persist_path.read_bytes()

        with patch.object(TaskQueue, "_persist") as persist:
            ok, code, _, _ = queue.extend_task_deadline(task_id, seconds, **EXTEND)

        assert (ok, code) == (False, error)
        persist.assert_not_called()
        assert persist_path.read_bytes() == before

    def test_extension_limit_is_not_persisted_as_a_change(
        self, queue: TaskQueue, persist_path: Path
    ) -> None:
        assert queue.add_task("t1", "question", auto_resubmit_timeout=300)
        for _ in range(3):
            assert queue.extend_task_deadline("t1", 10, **EXTEND)[0]

        with patch.object(TaskQueue, "_persist") as persist:
            ok, code, used, timeout = queue.extend_task_deadline("t1", 10, **EXTEND)

        assert (ok, code, used, timeout) == (False, "extends_limit_reached", 3, 330)
        persist.assert_not_called()
        assert _timeout_on_disk(persist_path, "t1") == 330


class TestFreezePersistsR835:
    def test_frozen_countdown_is_in_the_file_and_survives_a_restart(
        self, queue: TaskQueue, persist_path: Path
    ) -> None:
        assert queue.add_task("t1", "question", auto_resubmit_timeout=120)

        ok, error, timeout = queue.freeze_task_deadline("t1")

        assert (ok, error, timeout) == (True, None, 0)
        assert _timeout_on_disk(persist_path, "t1") == 0
        revived = _restored(persist_path)
        try:
            task = revived.get_task("t1")
            assert task is not None
            assert task.auto_resubmit_timeout == 0
            assert task.get_remaining_time() == 0
            assert task.is_expired() is False
        finally:
            revived.stop_cleanup()

    def test_refused_freeze_writes_nothing(
        self, queue: TaskQueue, persist_path: Path
    ) -> None:
        assert queue.add_task("t1", "question", auto_resubmit_timeout=120)
        assert queue.freeze_task_deadline("t1")[0]
        before = persist_path.read_bytes()

        with patch.object(TaskQueue, "_persist") as persist:
            again = queue.freeze_task_deadline("t1")
            missing = queue.freeze_task_deadline("missing")

        assert again[:2] == (False, "already_frozen")
        assert missing[:2] == (False, "task_not_found")
        persist.assert_not_called()
        assert persist_path.read_bytes() == before


def _persisted_view(persist_path: Path) -> dict[str, Any]:
    if not persist_path.exists():
        return {"active": None, "tasks": {}}
    data = json.loads(persist_path.read_text(encoding="utf-8"))
    return {
        "active": data["active_task_id"],
        "tasks": {item["task_id"]: item for item in data["tasks"]},
    }


def _memory_view(queue: TaskQueue) -> dict[str, Any]:
    active = queue.get_active_task()
    return {
        "active": active.task_id if active else None,
        "tasks": {
            task.task_id: task
            for task in queue.get_all_tasks()
            if task.status != TaskStatus.COMPLETED
        },
    }


# Every field of a task the snapshot writes.
PERSISTED_FIELDS = (
    "prompt",
    "predefined_options",
    "predefined_options_defaults",
    "auto_resubmit_timeout",
    "auto_resubmit_timeout_explicit",
    "feedback_placeholder",
    "header_label",
    "loop_id",
    "loop_objective",
    "loop_phase",
    "success_criteria",
    "iteration_label",
    "status",
)

OPERATIONS: list[tuple[str, Callable[[TaskQueue], Any]]] = [
    (
        "add a",
        lambda q: q.add_task("a", "A", ["x"], 300, loop_id="L", loop_objective="o"),
    ),
    ("add b", lambda q: q.add_task("b", "B", None, 120)),
    ("add c", lambda q: q.add_task("c", "C", None, 90)),
    ("extend a", lambda q: q.extend_task_deadline("a", 60, **EXTEND)),
    ("freeze b", lambda q: q.freeze_task_deadline("b")),
    ("activate c", lambda q: q.set_active_task("c")),
    ("update all timeouts", lambda q: q.update_auto_resubmit_timeout_for_all(200)),
    ("complete a", lambda q: q.complete_task("a", {"user_input": "hi"})),
    ("remove b", lambda q: q.remove_task("b")),
    ("clear completed", lambda q: q.clear_completed_tasks()),
    ("clear all", lambda q: q.clear_all_tasks()),
]


class TestFileTracksMemoryAfterEveryOperationR835:
    """The file matches the queue after each public mutating operation, in order.

    This is the contract the two omissions above broke; it also catches the next
    mutator that forgets to persist.
    """

    def test_every_operation_leaves_the_file_equal_to_memory(
        self, queue: TaskQueue, persist_path: Path
    ) -> None:
        for name, operation in OPERATIONS:
            operation(queue)
            memory = _memory_view(queue)
            disk = _persisted_view(persist_path)
            assert memory["active"] == disk["active"], f"after {name}: active id"
            assert set(memory["tasks"]) == set(disk["tasks"]), f"after {name}: tasks"
            for task_id, task in memory["tasks"].items():
                for field in PERSISTED_FIELDS:
                    assert getattr(task, field) == disk["tasks"][task_id][field], (
                        f"after {name}: {task_id}.{field} differs between memory and file"
                    )


class TestPersistRunsOutsideEveryLockR835:
    def test_no_persist_call_is_made_while_a_with_block_is_open(self) -> None:
        """The R22.2 contract, as a rule over the whole class.

        ``_persist`` takes the read lock and the persist lock itself; calling it from
        inside the write lock would deadlock on the first and invert the order of the
        second. So the call sites must all sit outside every ``with`` statement.
        """
        source = textwrap.dedent(inspect.getsource(TaskQueue))
        tree = ast.parse(source)
        offenders: list[tuple[str, int]] = []

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.depth = 0
                self.function = "<class>"
                self.sites = 0

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                previous, self.function = self.function, node.name
                self.generic_visit(node)
                self.function = previous

            def visit_With(self, node: ast.With) -> None:
                self.depth += 1
                self.generic_visit(node)
                self.depth -= 1

            def visit_Call(self, node: ast.Call) -> None:
                if ast.unparse(node.func) == "self._persist":
                    self.sites += 1
                    if self.depth:
                        offenders.append((self.function, node.lineno))
                self.generic_visit(node)

        visitor = Visitor()
        visitor.visit(tree)

        assert visitor.sites >= 6, (
            "the scan found fewer _persist call sites than expected"
        )
        assert not offenders, f"_persist() called under a lock in: {offenders}"

    @pytest.mark.parametrize("method", ["extend_task_deadline", "freeze_task_deadline"])
    def test_deadline_methods_call_persist_after_their_write_lock(
        self, method: str
    ) -> None:
        source = textwrap.dedent(inspect.getsource(getattr(TaskQueue, method)))
        assert "self._persist()" in source
