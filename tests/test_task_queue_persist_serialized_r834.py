"""R834 - ``TaskQueue._persist`` writes happen one at a time, each from a fresh snapshot.

Symptom: every state change ends in ``_persist()``: take a snapshot under the read
lock, write it to a temporary file, ``fsync`` it, ``os.replace`` it over ``tasks.json``.
Nothing ordered the writers. A writer that took its snapshot early and was slow to
reach ``os.replace`` (a slow ``fsync`` is enough) replaced the file *after* a writer
that took its snapshot later, so the file went back in time: the task added last
was missing from ``tasks.json`` while the queue in memory still had it. The next
restart of the Web UI restored the stale file. A probe (30 rounds of 8 threads) lost a
task in 7 of 30 rounds.

Fix: the snapshot and the write are one critical section under ``_persist_lock``. The
snapshot is taken after the lock is held, so the last writer always writes a state
that includes every change made before it was called.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import random
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ai_intervention_agent.task_queue import TaskQueue, TaskStatus

JOIN_TIMEOUT = 20.0

# Two places where a writer can be slow: right before it takes the persist lock (so a
# snapshot taken before the lock would be stale by the time it is written) and while
# flushing to disk.
STALL_POINTS = ("acquire-lock", "fsync")


def _ids_on_disk(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["task_id"] for item in data["tasks"]}


def _ids_in_memory(queue: TaskQueue) -> set[str]:
    return {
        task.task_id
        for task in queue.get_all_tasks()
        if task.status != TaskStatus.COMPLETED
    }


class _StalledFirstPersist:
    """Holds the first writer at one step of ``_persist`` until ``release()``."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self._release = threading.Event()
        self.replaced_meanwhile = threading.Event()
        self._guard = threading.Lock()
        self._first_taken = False

    def release(self) -> None:
        self._release.set()

    def stall_if_first(self) -> None:
        with self._guard:
            is_first = not self._first_taken
            self._first_taken = True
        if is_first:
            self.entered.set()
            self._release.wait(JOIN_TIMEOUT)

    def wrap_fsync(self, real: Callable[[int], None]) -> Callable[[int], None]:
        def wrapper(fd: int) -> None:
            # Only the ``fsync`` of ``_persist``'s own write counts (R844: that write is
            # ``atomic_write_text`` called by ``_persist``).
            callers = (sys._getframe(1).f_code.co_name, sys._getframe(2).f_code.co_name)
            if callers == ("atomic_write_text", "_persist"):
                self.stall_if_first()
            real(fd)

        return wrapper

    def note_replace(
        self, real: Callable[[Any, Any], None]
    ) -> Callable[[Any, Any], None]:
        def wrapper(src: Any, dst: Any) -> None:
            real(src, dst)
            if not self._release.is_set():
                self.replaced_meanwhile.set()

        return wrapper


class _SlowToAcquire:
    """Stands in for ``_persist_lock``: the first writer is delayed before it gets it."""

    def __init__(self, inner: Any, stall: _StalledFirstPersist) -> None:
        self._inner = inner
        self._stall = stall

    def __enter__(self) -> _SlowToAcquire:
        self._stall.stall_if_first()
        self._inner.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._inner.release()


@contextmanager
def _stalling(queue: TaskQueue, stall_point: str) -> Iterator[_StalledFirstPersist]:
    stall = _StalledFirstPersist()
    with patch.object(os, "replace", stall.note_replace(os.replace)):
        try:
            if stall_point == "acquire-lock":
                with patch.object(
                    queue, "_persist_lock", _SlowToAcquire(queue._persist_lock, stall)
                ):
                    yield stall
            else:
                with patch.object(os, "fsync", stall.wrap_fsync(os.fsync)):
                    yield stall
        finally:
            stall.release()


def _start(
    queue: TaskQueue, task_id: str, errors: list[BaseException]
) -> threading.Thread:
    def add() -> None:
        try:
            assert queue.add_task(task_id, f"prompt {task_id}")
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    thread = threading.Thread(target=add, name=f"writer-{task_id}")
    thread.start()
    return thread


@pytest.fixture
def queue(tmp_path: Path) -> Iterator[TaskQueue]:
    q = TaskQueue(max_tasks=10, persist_path=str(tmp_path / "tasks.json"))
    try:
        yield q
    finally:
        q.stop_cleanup()


class TestStaleSnapshotNeverWinsR834:
    @pytest.mark.parametrize("stall_point", STALL_POINTS)
    def test_slow_first_writer_does_not_overwrite_the_newer_snapshot(
        self, queue: TaskQueue, tmp_path: Path, stall_point: str
    ) -> None:
        """Writer 1 stalls inside ``_persist``; writer 2 adds ``b`` meanwhile.

        Whatever order the two ``os.replace`` calls end up in, the file must finish with
        both tasks, because the queue in memory has both.
        """
        path = tmp_path / "tasks.json"
        errors: list[BaseException] = []

        with _stalling(queue, stall_point) as stall:
            writer_1 = _start(queue, "a", errors)
            assert stall.entered.wait(JOIN_TIMEOUT), "writer 1 never reached the stall"

            writer_2 = _start(queue, "b", errors)
            # Without the lock writer 2 finishes (and replaces the file) while writer 1 is
            # still stalled; with it, writer 2 waits and nothing is replaced yet.
            stall.replaced_meanwhile.wait(0.5)

            stall.release()
            writer_1.join(JOIN_TIMEOUT)
            writer_2.join(JOIN_TIMEOUT)

        assert not errors, errors
        assert not writer_1.is_alive()
        assert not writer_2.is_alive()
        assert _ids_in_memory(queue) == {"a", "b"}
        assert _ids_on_disk(path) == {"a", "b"}

    def test_every_writer_blocked_behind_one_stalled_writer_still_lands(
        self, queue: TaskQueue, tmp_path: Path
    ) -> None:
        """Five tasks are added while the first write stalls; all five reach the file."""
        path = tmp_path / "tasks.json"
        errors: list[BaseException] = []

        with _stalling(queue, "fsync") as stall:
            first = _start(queue, "t0", errors)
            assert stall.entered.wait(JOIN_TIMEOUT)
            others = [_start(queue, f"t{i}", errors) for i in range(1, 5)]
            time.sleep(0.2)
            stall.release()
            for thread in [first, *others]:
                thread.join(JOIN_TIMEOUT)

        assert not errors, errors
        assert all(not thread.is_alive() for thread in [first, *others])
        assert _ids_on_disk(path) == {f"t{i}" for i in range(5)}


class TestConcurrentChurnEndsConsistentR834:
    def test_file_matches_memory_after_concurrent_adds_and_completions(
        self, tmp_path: Path
    ) -> None:
        """A soak over the public API with a slow disk: a broad invariant, not the proof
        (the stalled-writer tests above are deterministic; this one only catches the race
        on the old code some of the time)."""
        seed = 1
        path = tmp_path / "tasks.json"
        # Room for every task the workers add (8 x 20), so no add is refused.
        queue = TaskQueue(max_tasks=200, persist_path=str(path))
        errors: list[BaseException] = []
        real_fsync = os.fsync
        jitter = random.Random(seed)
        jitter_lock = threading.Lock()

        def slow_fsync(fd: int) -> None:
            # A disk that sometimes takes a few milliseconds: the window the race needs.
            with jitter_lock:
                pause = jitter.random() * 0.004
            time.sleep(pause)
            real_fsync(fd)

        def worker(worker_id: int) -> None:
            rng = random.Random(seed * 100 + worker_id)
            try:
                for step in range(20):
                    task_id = f"w{worker_id}-{step}"
                    assert queue.add_task(task_id, f"prompt {task_id}")
                    if rng.random() < 0.4:
                        assert queue.complete_task(task_id, {"text": "done"})
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(i,), name=f"churn-{i}")
            for i in range(8)
        ]
        try:
            with patch.object(os, "fsync", slow_fsync):
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(JOIN_TIMEOUT)

            assert not errors, errors
            assert all(not thread.is_alive() for thread in threads)
            assert _ids_on_disk(path) == _ids_in_memory(queue)
        finally:
            queue.stop_cleanup()


class TestPersistStructureR834:
    def test_snapshot_and_write_sit_inside_the_persist_lock(self) -> None:
        """Locks the shape: one ``with self._persist_lock`` holding snapshot and replace."""
        source = textwrap.dedent(inspect.getsource(TaskQueue._persist))
        function = ast.parse(source).body[0]
        assert isinstance(function, ast.FunctionDef)

        def holds_persist_lock(node: ast.AST) -> bool:
            if not isinstance(node, ast.With):
                return False
            return any(
                ast.unparse(item.context_expr) == "self._persist_lock"
                for item in node.items
            )

        guards = [node for node in ast.walk(function) if holds_persist_lock(node)]
        assert len(guards) == 1, "exactly one critical section under _persist_lock"
        inside = {id(node) for node in ast.walk(guards[0])}

        def calls(*, guarded: bool) -> set[str]:
            return {
                ast.unparse(node.func)
                for node in ast.walk(function)
                if isinstance(node, ast.Call) and (id(node) in inside) == guarded
            }

        assert "self._lock.read_lock" in calls(guarded=True), (
            "the snapshot must be taken inside the critical section"
        )
        assert "atomic_write_text" in calls(guarded=True), (
            "the file replacement must be inside the critical section"
        )
        assert "self._lock.read_lock" not in calls(guarded=False)
        assert "atomic_write_text" not in calls(guarded=False)

    def test_persist_lock_is_a_plain_non_reentrant_lock_per_queue(
        self, tmp_path: Path
    ) -> None:
        first = TaskQueue(persist_path=str(tmp_path / "one.json"))
        second = TaskQueue(persist_path=str(tmp_path / "two.json"))
        try:
            assert first._persist_lock is not second._persist_lock
            assert type(first._persist_lock) is type(threading.Lock())
        finally:
            first.stop_cleanup()
            second.stop_cleanup()
