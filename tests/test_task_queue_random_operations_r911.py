"""R911: the task queue keeps its promises whatever order the operations come in.

The tests of ``task_queue.py`` so far each take one operation and check what it does. The promises of
the queue are about the operations together: after any sequence of adds, switches, answers and removals
the queue is still in a state a person could have reached by hand. Nothing checked that, and a rule
like "while a question is unanswered, one of the questions is the active one" is exactly the kind
that holds on every path the author thought of and fails on the one nobody did.

The promises, in words:

1. at most one task is active, it is the one ``get_active_task()`` returns, and while any task is
   unanswered one of them is active (the queue never parks questions with nobody in front);
2. an answered task never becomes active again, and the first answer is the answer for good;
3. the counts agree with the tasks, and the queue never holds more than ``max_tasks``;
4. every operation answers what its docstring says and raises exactly the status events its
   transitions imply (add: ``None -> status``; switch: old ``active -> pending``, new ``-> active``;
   answer: ``-> completed`` and the next pending task ``-> active``; remove: ``-> removed`` and the
   next one ``-> active``);
5. what is on disk brings back the same unanswered tasks, in the same order, with the same fields,
   the same active task and the same loop ledger, whatever happened before the last write, and with
   several threads writing at once the file after the last operation is the state after the last
   operation.

The operations are drawn at random from a seeded generator (so a failure replays: the seed is in the
test id), applied to the real queue and to a model of a few lines that is the promises above and
nothing else, and compared after every step. A small pool of task ids against a small capacity makes
the queue full, makes ids collide and makes answers arrive twice, which are the cases that matter.

The deadline operations (extend, freeze, hot update of the timeout) and the loop ledger take part in
the on-disk comparison: they are the fields that were once changed in memory and not written (R835).
"""

from __future__ import annotations

import random
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ai_intervention_agent import task_queue as task_queue_module
from ai_intervention_agent.task_queue import TaskQueue, TaskStatus

PENDING = TaskStatus.PENDING.value
ACTIVE = TaskStatus.ACTIVE.value
COMPLETED = TaskStatus.COMPLETED.value
REMOVED = TaskStatus.REMOVED.value

CAPACITY = 5
IDS = [f"t{number}" for number in range(8)]
LOOPS = [None, None, "loop-a", "loop-b"]

Event = tuple[str, str | None, str]


@pytest.fixture(autouse=True)
def quiet_queue_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queue logs a warning for every refused operation, which is most of what is done here."""
    monkeypatch.setattr(task_queue_module, "logger", MagicMock())


@pytest.fixture(autouse=True)
def no_fsync(monkeypatch: pytest.MonkeyPatch) -> None:
    """What is checked is what is written, not that it reaches the platter (the fsync has its own test)."""
    monkeypatch.setattr("os.fsync", lambda descriptor: None)


class Model:
    """The promises of the queue and nothing else: ids in queue order, a status each, one active."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.status: dict[str, str] = {}
        self.active: str | None = None
        self.answer: dict[str, dict[str, Any]] = {}

    def add(self, task_id: str) -> tuple[bool, list[Event]]:
        if len(self.status) >= self.capacity or task_id in self.status:
            return False, []
        self.status[task_id] = PENDING if self.active else ACTIVE
        self.active = self.active or task_id
        return True, [(task_id, None, self.status[task_id])]

    def activate(self, task_id: str) -> tuple[bool, list[Event]]:
        if task_id not in self.status or self.status[task_id] == COMPLETED:
            return False, []
        if self.active == task_id:
            return True, []
        events: list[Event] = []
        if self.active is not None:
            self.status[self.active] = PENDING
            events.append((self.active, ACTIVE, PENDING))
        events.append((task_id, self.status[task_id], ACTIVE))
        self.status[task_id] = ACTIVE
        self.active = task_id
        return True, events

    def _hand_over(self, leaving: str) -> list[Event]:
        """The active task is gone or answered: the first unanswered one in queue order takes over."""
        self.active = None
        for task_id, status in self.status.items():
            if task_id != leaving and status in (PENDING, ACTIVE):
                events: list[Event] = [(task_id, status, ACTIVE)]
                self.status[task_id] = ACTIVE
                self.active = task_id
                return events
        return []

    def complete(
        self, task_id: str, answer: dict[str, Any]
    ) -> tuple[bool, list[Event]]:
        if task_id not in self.status or self.status[task_id] == COMPLETED:
            return False, []
        events: list[Event] = [(task_id, self.status[task_id], COMPLETED)]
        self.status[task_id] = COMPLETED
        self.answer[task_id] = answer
        if self.active == task_id:
            events += self._hand_over(task_id)
        return True, events

    def remove(self, task_id: str) -> tuple[bool, list[Event]]:
        if task_id not in self.status:
            return False, []
        events: list[Event] = [(task_id, self.status[task_id], REMOVED)]
        if self.active == task_id:
            events += self._hand_over(task_id)
        del self.status[task_id]
        self.answer.pop(task_id, None)
        return True, events

    def drop_answered(self) -> int:
        gone = [task_id for task_id, s in self.status.items() if s == COMPLETED]
        for task_id in gone:
            del self.status[task_id]
            del self.answer[task_id]
        return len(gone)

    def clear(self) -> int:
        count = len(self.status)
        self.status.clear()
        self.answer.clear()
        self.active = None
        return count


def check_promises(queue: TaskQueue) -> None:
    """Promises 1 to 3, read from the queue alone (no model)."""
    tasks = queue.get_all_tasks()
    statuses = [str(task.status) for task in tasks]
    active = [task for task in tasks if str(task.status) == ACTIVE]
    assert len(active) <= 1, statuses
    current = queue.get_active_task()
    assert (current.task_id if current else None) == (
        active[0].task_id if active else None
    )
    if any(status != COMPLETED for status in statuses):
        assert active, f"unanswered tasks and nobody in front: {statuses}"
    assert len({task.task_id for task in tasks}) == len(tasks)
    assert len(tasks) <= queue.max_tasks
    counts = queue.get_task_count()
    assert counts == {
        "total": len(tasks),
        "pending": statuses.count(PENDING),
        "active": statuses.count(ACTIVE),
        "completed": statuses.count(COMPLETED),
        "max": queue.max_tasks,
    }
    listed, listed_counts = queue.get_all_tasks_with_stats()
    assert [task.task_id for task in listed] == [task.task_id for task in tasks]
    assert listed_counts == counts
    first = queue.get_first_incomplete_task()
    unanswered = [task for task in tasks if str(task.status) != COMPLETED]
    assert (first.task_id if first else None) == (
        unanswered[0].task_id if unanswered else None
    )
    assert queue.has_tasks() == bool(tasks)


def check_against_model(queue: TaskQueue, model: Model) -> None:
    tasks = queue.get_all_tasks()
    assert {task.task_id: str(task.status) for task in tasks} == model.status
    assert [task.task_id for task in tasks] == list(model.status)
    current = queue.get_active_task()
    assert (current.task_id if current else None) == model.active
    for task in tasks:
        if str(task.status) == COMPLETED:
            assert task.result == model.answer[task.task_id]
        else:
            assert task.result is None


MODEL_STEPS = (
    (0.30, "add"),
    (0.45, "activate"),
    (0.65, "complete"),
    (0.77, "remove"),
    (0.83, "drop_answered"),
    (0.89, "drop_answered_throttled"),
    (0.95, "clear_completed"),
    (0.97, "clear"),
    (1.00, "look"),
)
DISK_STEPS = (
    (0.26, "add"),
    (0.38, "activate"),
    (0.54, "complete"),
    (0.62, "remove"),
    (0.66, "clear_completed"),
    (0.68, "clear"),
    (0.78, "extend"),
    (0.86, "freeze"),
    (1.00, "update_all"),
)


def random_step(
    rng: random.Random, steps: tuple[tuple[float, str], ...] = MODEL_STEPS
) -> tuple[str, str]:
    roll = rng.random()
    task_id = rng.choice(IDS)
    return next((name, task_id) for limit, name in steps if roll < limit)


class Run:
    """A queue, its model and the status events the queue raised, stepped together."""

    def __init__(self) -> None:
        self.queue = TaskQueue(max_tasks=CAPACITY)
        self.model = Model(CAPACITY)
        self.events: list[Event] = []
        self.queue.register_status_change_callback(
            lambda task_id, old, new: self.events.append((task_id, old, new))
        )
        self.answers = 0

    def close(self) -> None:
        self.queue.stop_cleanup()

    def step(self, name: str, task_id: str, rng: random.Random) -> None:
        queue, model = self.queue, self.model
        self.events.clear()
        expected_events: list[Event] = []
        if name == "add":
            loop_id = rng.choice(LOOPS)
            done = queue.add_task(
                task_id,
                f"question {task_id}",
                loop_id=loop_id,
                loop_objective="objective" if loop_id else None,
            )
            expected, expected_events = model.add(task_id)
        elif name == "activate":
            done = queue.set_active_task(task_id)
            expected, expected_events = model.activate(task_id)
        elif name == "complete":
            self.answers += 1
            answer = {"user_input": f"answer {self.answers}", "selected_options": []}
            done = queue.complete_task(task_id, answer)
            expected, expected_events = model.complete(task_id, answer)
        elif name == "remove":
            done = queue.remove_task(task_id)
            expected, expected_events = model.remove(task_id)
        elif name == "drop_answered":
            done = queue.cleanup_completed_tasks(age_seconds=-1)
            expected = model.drop_answered()
        elif name == "drop_answered_throttled":
            done = queue.cleanup_completed_tasks_throttled(
                age_seconds=-1, throttle_seconds=0.0
            )
            expected = model.drop_answered()
        elif name == "clear_completed":
            done = queue.clear_completed_tasks()
            expected = model.drop_answered()
        elif name == "clear":
            done = queue.clear_all_tasks()
            expected = model.clear()
        else:
            done = expected = None
        assert done == expected, (name, task_id)
        assert self.events == expected_events, (name, task_id)
        check_promises(queue)
        check_against_model(queue, model)


SEEDS = range(300)
STEPS = 70


class TestEveryOrderOfOperationsKeepsThePromises:
    @pytest.mark.parametrize("seed", SEEDS, ids=lambda seed: f"seed{seed}")
    def test_the_queue_matches_the_model_after_every_step(self, seed: int) -> None:
        rng = random.Random(seed)
        run = Run()
        try:
            for _ in range(STEPS):
                name, task_id = random_step(rng)
                run.step(name, task_id, rng)
        finally:
            run.close()

    def test_the_random_runs_reach_the_cases_that_matter(self) -> None:
        reached: set[str] = set()
        for seed in range(40):
            rng = random.Random(seed)
            run = Run()
            try:
                for _ in range(STEPS):
                    name, task_id = random_step(rng)
                    before = dict(run.model.status)
                    in_front = run.model.active
                    run.step(name, task_id, rng)
                    if name == "add" and task_id not in before and run.events == []:
                        reached.add("add to a full queue")
                    if name == "add" and task_id in before:
                        reached.add("add an id that is taken")
                    if name == "complete" and before.get(task_id) == COMPLETED:
                        reached.add("a second answer")
                    if name == "complete" and len(run.events) == 2:
                        reached.add("an answer that hands over")
                    if name == "complete" and before.get(task_id) == PENDING:
                        reached.add("an answer for a task that is not in front")
                    if name == "activate" and before.get(task_id) == COMPLETED:
                        reached.add("activate an answered task")
                    if name == "activate" and len(run.events) == 2:
                        reached.add("a switch")
                    if name == "remove" and len(run.events) == 2:
                        reached.add("a removal that hands over")
                    if (
                        name == "remove"
                        and in_front == task_id
                        and run.model.active is None
                    ):
                        reached.add("remove the last unanswered task")
            finally:
                run.close()
        assert reached == {
            "add to a full queue",
            "add an id that is taken",
            "a second answer",
            "an answer that hands over",
            "an answer for a task that is not in front",
            "activate an answered task",
            "a switch",
            "a removal that hands over",
            "remove the last unanswered task",
        }


def describe(queue: TaskQueue) -> dict[str, Any]:
    """What a restart has to bring back: the unanswered tasks with their fields, the active one, the loops."""
    tasks = [task for task in queue.get_all_tasks() if str(task.status) != COMPLETED]
    fields = (
        "task_id",
        "prompt",
        "predefined_options",
        "predefined_options_defaults",
        "auto_resubmit_timeout",
        "auto_resubmit_timeout_explicit",
        "created_at",
        "feedback_placeholder",
        "header_label",
        "loop_id",
        "loop_objective",
        "loop_phase",
        "success_criteria",
        "iteration_label",
    )
    active = queue.get_active_task()
    loops = []
    for entry in queue.get_loops_snapshot():
        loops.append(
            {
                **{key: value for key, value in entry.items() if key != "live_tasks"},
                "live_tasks": [
                    live
                    for live in entry["live_tasks"]
                    if str(live["status"]) != COMPLETED
                ],
            }
        )
    return {
        "tasks": [
            {field: getattr(task, field) for field in fields}
            | {"status": str(task.status)}
            for task in tasks
        ],
        "active": active.task_id if active else None,
        "loops": loops,
    }


def reload(path: Path) -> TaskQueue:
    return TaskQueue(max_tasks=CAPACITY, persist_path=str(path))


def disk_step(queue: TaskQueue, name: str, task_id: str, rng: random.Random) -> None:
    """One operation of the on-disk comparison: the model's ones, and the ones that change deadlines."""
    if name == "add":
        loop_id = rng.choice(LOOPS)
        options = rng.choice([None, [], ["a"], ["a", "b", "c"]])
        queue.add_task(
            task_id,
            f"question {task_id}",
            predefined_options=options,
            predefined_options_defaults=(
                None if options is None else [rng.random() < 0.5 for _ in options]
            ),
            auto_resubmit_timeout=rng.choice([0, 30, 240, 1800]),
            auto_resubmit_timeout_explicit=rng.random() < 0.5,
            feedback_placeholder=rng.choice([None, "  type here  ", ""]),
            header_label=rng.choice([None, "Auth", "x" * 40]),
            loop_id=loop_id,
            loop_objective=rng.choice([None, "objective"]) if loop_id else None,
            loop_phase=rng.choice([None, "verify"]) if loop_id else None,
            success_criteria=rng.choice([None, "tests pass"]) if loop_id else None,
            iteration_label=rng.choice([None, "iter-2"]) if loop_id else None,
        )
    elif name == "activate":
        queue.set_active_task(task_id)
    elif name == "complete":
        queue.complete_task(
            task_id,
            {
                "user_input": f"answer {rng.random()}",
                "selected_options": ["a"],
                "images": [],
            },
        )
    elif name == "remove":
        queue.remove_task(task_id)
    elif name == "clear_completed":
        queue.clear_completed_tasks()
    elif name == "clear":
        queue.clear_all_tasks()
    elif name == "extend":
        queue.extend_task_deadline(
            task_id, 60, max_extends=3, min_seconds=10, max_seconds=300
        )
    elif name == "freeze":
        queue.freeze_task_deadline(task_id)
    else:
        assert name == "update_all", name
        queue.update_auto_resubmit_timeout_for_all(rng.choice([0, 60, 600]))


class TestWhatIsOnDiskBringsTheSameQueueBack:
    @pytest.mark.parametrize("seed", range(40), ids=lambda seed: f"seed{seed}")
    def test_a_restart_after_every_step_finds_the_same_queue(
        self, seed: int, tmp_path: Path
    ) -> None:
        path = tmp_path / "tasks.json"
        rng = random.Random(10_000 + seed)
        queue = TaskQueue(max_tasks=CAPACITY, persist_path=str(path))
        try:
            for step in range(45):
                name, task_id = random_step(rng, DISK_STEPS)
                disk_step(queue, name, task_id, rng)
                reloaded = reload(path)
                try:
                    assert describe(reloaded) == describe(queue), (
                        f"after step {step}: {name} {task_id}"
                    )
                finally:
                    reloaded.stop_cleanup()
        finally:
            queue.stop_cleanup()

    def test_clearing_everything_forgets_the_loop_ledger_and_the_file(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "tasks.json"
        queue = TaskQueue(max_tasks=CAPACITY, persist_path=str(path))
        try:
            queue.add_task("a", "question", loop_id="loop-a", loop_objective="goal")
            assert queue.complete_task("a", {"user_input": "one"})
            assert path.exists()
            assert [entry["loop_id"] for entry in queue.get_loops_snapshot()] == [
                "loop-a"
            ]
            assert queue.clear_all_tasks() == 1
            assert queue.get_loops_snapshot() == []
            assert not path.exists()
            reloaded = reload(path)
            try:
                assert reloaded.get_loops_snapshot() == []
                assert reloaded.get_all_tasks() == []
            finally:
                reloaded.stop_cleanup()
        finally:
            queue.stop_cleanup()

    def test_the_second_answer_does_not_replace_the_first_on_disk(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "tasks.json"
        queue = TaskQueue(max_tasks=CAPACITY, persist_path=str(path))
        try:
            queue.add_task("a", "first question", loop_id="loop-a")
            queue.add_task("b", "second question")
            assert queue.complete_task("a", {"user_input": "one"})
            assert not queue.complete_task("a", {"user_input": "two"})
            reloaded = reload(path)
            try:
                (entry,) = [
                    entry
                    for entry in reloaded.get_loops_snapshot()
                    if entry["loop_id"] == "loop-a"
                ]
                assert [r["verdict"]["user_input"] for r in entry["rounds"]] == ["one"]
                assert [t.task_id for t in reloaded.get_all_tasks()] == ["b"]
                active = reloaded.get_active_task()
                assert active is not None and active.task_id == "b"
            finally:
                reloaded.stop_cleanup()
        finally:
            queue.stop_cleanup()


def hammer(
    queue: TaskQueue, seed: int, steps: int, failures: list[BaseException]
) -> None:
    """One thread of the stress test: random operations on the shared queue, no model."""
    rng = random.Random(seed)
    try:
        for _ in range(steps):
            name, task_id = random_step(rng, DISK_STEPS)
            disk_step(queue, name, task_id, rng)
    except BaseException as exc:  # handed to the main thread, which asserts on it
        failures.append(exc)


def watch(
    queue: TaskQueue,
    stop: threading.Event,
    failures: list[BaseException],
    looked: list[int],
) -> None:
    """The reader of the stress test: every atomic view of the queue has to satisfy the promises."""
    try:
        while not stop.wait(0.0001):
            _, counts = queue.get_all_tasks_with_stats()
            assert counts["active"] <= 1, counts
            assert counts["active"] == 1 or counts["pending"] == 0, counts
            assert counts["total"] <= counts["max"], counts
            assert counts["total"] == (
                counts["pending"] + counts["active"] + counts["completed"]
            ), counts
            looked.append(1)
    except BaseException as exc:  # handed to the main thread, which asserts on it
        failures.append(exc)


def remove_at_the_signal(
    queue: TaskQueue,
    start: threading.Barrier,
    number: int,
    failures: list[BaseException],
) -> None:
    """One writer of the overlapping-writes test: waits for the others, then removes its own task."""
    try:
        start.wait(timeout=30)
        assert queue.remove_task(f"t{number}")
    except BaseException as exc:  # handed to the main thread, which asserts on it
        failures.append(exc)


class TestSeveralThreadsAtOnce:
    def test_the_promises_hold_in_every_view_and_the_file_ends_up_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A slow disk and short time slices make the threads overlap inside the write, which is
        # where an older snapshot once replaced a newer one (R834).
        monkeypatch.setattr("os.fsync", lambda descriptor: time.sleep(0.001))
        slice_ = sys.getswitchinterval()
        sys.setswitchinterval(1e-5)
        path = tmp_path / "tasks.json"
        queue = TaskQueue(max_tasks=CAPACITY, persist_path=str(path))
        failures: list[BaseException] = []
        looked: list[int] = []
        stop = threading.Event()
        try:
            reader = threading.Thread(
                target=watch, args=(queue, stop, failures, looked), daemon=True
            )
            writers = [
                threading.Thread(
                    target=hammer, args=(queue, seed, 60, failures), daemon=True
                )
                for seed in range(4)
            ]
            reader.start()
            for thread in writers:
                thread.start()
            for thread in writers:
                thread.join(timeout=120)
            stop.set()
            reader.join(timeout=30)
            assert not any(thread.is_alive() for thread in [reader, *writers]), (
                "a thread is stuck: a deadlock in the queue"
            )
            assert failures == []
            assert looked, "the reader never looked"
            check_promises(queue)
            reloaded = reload(path)
            try:
                assert describe(reloaded) == describe(queue)
            finally:
                reloaded.stop_cleanup()
        finally:
            sys.setswitchinterval(slice_)
            stop.set()
            queue.stop_cleanup()

    def test_the_file_is_never_older_than_the_queue_after_writes_that_overlap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The write that starts first may finish last when the disk takes a random time for each. The file
        # has to be the newest state anyway: the snapshot is taken inside the one critical section that
        # also writes it (R834); taken before it, an older snapshot replaced a newer one.
        monkeypatch.setattr(
            "os.fsync", lambda descriptor: time.sleep(random.random() * 0.004)
        )
        path = tmp_path / "tasks.json"
        queue = TaskQueue(max_tasks=CAPACITY, persist_path=str(path))
        writers = 4
        try:
            for round_number in range(25):
                for number in range(writers):
                    assert queue.add_task(f"t{number}", f"question {number}")
                start = threading.Barrier(writers)
                failures: list[BaseException] = []

                threads = [
                    threading.Thread(
                        target=remove_at_the_signal,
                        args=(queue, start, number, failures),
                        daemon=True,
                    )
                    for number in range(writers)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=60)
                assert not any(thread.is_alive() for thread in threads)
                assert failures == []
                reloaded = reload(path)
                try:
                    assert describe(reloaded) == describe(queue), (
                        f"round {round_number}: the file is older than the queue"
                    )
                finally:
                    reloaded.stop_cleanup()
        finally:
            queue.stop_cleanup()


@pytest.fixture
def play() -> Iterator[Callable[..., Run]]:
    runs: list[Run] = []

    def start(*steps: tuple[str, str]) -> Run:
        run = Run()
        runs.append(run)
        rng = random.Random(0)
        for name, task_id in steps:
            run.step(name, task_id, rng)
        return run

    yield start
    for run in runs:
        run.close()


class TestTheModelIsTheContractAndNotJustTheCode:
    """The model is held to the plain facts as well, so it cannot drift to agree with a fault of the code."""

    def test_an_answer_hands_over_to_the_first_waiting_task_in_queue_order(
        self, play: Callable[..., Run]
    ) -> None:
        run = play(
            *[("add", name) for name in "abcd"], ("activate", "c"), ("complete", "c")
        )
        assert run.model.status == {
            "a": ACTIVE,
            "b": PENDING,
            "c": COMPLETED,
            "d": PENDING,
        }

    def test_the_first_answer_is_the_answer_for_good(
        self, play: Callable[..., Run]
    ) -> None:
        run = play(("add", "a"), ("complete", "a"), ("complete", "a"))
        task = run.queue.get_task("a")
        assert task is not None
        assert task.result == {"user_input": "answer 1", "selected_options": []}

    def test_an_answered_task_does_not_come_back_to_the_front(
        self, play: Callable[..., Run]
    ) -> None:
        run = play(("add", "a"), ("add", "b"), ("complete", "b"), ("activate", "b"))
        assert run.model.status == {"a": ACTIVE, "b": COMPLETED}

    def test_removing_the_task_in_front_hands_over(
        self, play: Callable[..., Run]
    ) -> None:
        run = play(("add", "a"), ("add", "b"), ("add", "c"), ("remove", "a"))
        assert run.model.status == {"b": ACTIVE, "c": PENDING}

    def test_nobody_is_in_front_when_everything_is_answered_or_gone(
        self, play: Callable[..., Run]
    ) -> None:
        gone = play(("add", "a"), ("add", "b"), ("remove", "a"), ("remove", "b"))
        assert gone.model.status == {}
        assert gone.queue.get_active_task() is None
        assert not gone.queue.has_tasks()
        answered = play(("add", "a"), ("complete", "a"))
        assert answered.model.status == {"a": COMPLETED}
        assert answered.queue.get_active_task() is None
        assert answered.queue.has_tasks()

    def test_the_queue_is_full_at_its_capacity_and_ids_are_unique(
        self, play: Callable[..., Run]
    ) -> None:
        names = [f"t{number}" for number in range(CAPACITY + 1)]
        run = play(*[("add", name) for name in names], ("add", "t0"))
        assert list(run.model.status) == names[:CAPACITY]
        run = play(
            *[("add", name) for name in names], ("remove", "t0"), ("add", names[-1])
        )
        assert list(run.model.status) == [*names[1:CAPACITY], names[-1]]

    def test_the_events_of_a_switch_an_answer_and_a_removal(
        self, play: Callable[..., Run]
    ) -> None:
        switch = play(("add", "a"), ("add", "b"), ("activate", "b"))
        assert switch.events == [("a", ACTIVE, PENDING), ("b", PENDING, ACTIVE)]
        answer = play(("add", "a"), ("add", "b"), ("complete", "a"))
        assert answer.events == [("a", ACTIVE, COMPLETED), ("b", PENDING, ACTIVE)]
        removal = play(("add", "a"), ("add", "b"), ("remove", "a"))
        assert removal.events == [("a", ACTIVE, REMOVED), ("b", PENDING, ACTIVE)]
