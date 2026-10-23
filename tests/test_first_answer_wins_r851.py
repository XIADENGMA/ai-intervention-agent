"""R851: the first answer a task receives is the answer; a later one is refused with 409.

``TaskQueue.complete_task`` took any number of answers for the same task.  The second one replaced
``task.result``, set ``completed_at`` again (so the ten-second retention started over), sent a
COMPLETED -> COMPLETED status event, and returned ``True``; both submit routes then answered
``200 {"success": true}``.  The MCP call had taken the first answer the moment the first
status event arrived, so the replacement reached no one: the agent kept answer A, the Web UI kept
answer B, and the person who sent B was told "submitted" and had the text box emptied.

The second answer is not a thought experiment.  It is what a second browser tab or device on the same
task sends, what a double click sends, and what the auto-resubmit countdown sends when it reaches
zero just after a manual submit - the case ``test_double_complete_records_single_round`` already
names for the loop ledger, which kept the first round while the task kept the last answer.

Now ``complete_task`` is a first-come-first-served decision made under the write lock: it answers
``True`` to exactly one caller per task, and a completed task keeps its answer, its ``completed_at``
and its place in the cleanup order.  When it answers ``False`` both routes ask
``refused_answer_response`` what to say: ``404`` for a task that is gone, ``409`` for one that
already has its answer; the page then shows an error and keeps the draft.
"""

from __future__ import annotations

import ast
import inspect
import itertools
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
import yaml
from flask.testing import FlaskClient

from ai_intervention_agent.i18n import msg
from ai_intervention_agent.task_queue import TaskQueue
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "ai_intervention_agent"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
LANGUAGES = ("en", "zh-CN", "zh-TW")
QUEUE_LOGGER = "ai_intervention_agent.task_queue"
KEY = "feedback.alreadyAnswered"
CODE = "task_already_answered"

FIRST = {"user_input": "first", "selected_options": ["a"]}
SECOND = {"user_input": "second", "selected_options": ["b"]}


# --------------------------------------------------------------------------- the queue


@pytest.fixture
def queue() -> Iterator[TaskQueue]:
    q = TaskQueue(max_tasks=10)
    try:
        assert q.add_task("t1", "prompt", auto_resubmit_timeout=0)
        yield q
    finally:
        q.stop_cleanup()


def _task(q: TaskQueue, task_id: str = "t1") -> Any:
    task = q.get_task(task_id)
    assert task is not None
    return task


class TestTheQueueTakesOneAnswerPerTask:
    def test_the_first_answer_is_taken_and_a_later_one_is_not(
        self, queue: TaskQueue
    ) -> None:
        assert queue.complete_task("t1", FIRST) is True
        assert queue.complete_task("t1", SECOND) is False
        assert queue.complete_task("t1", SECOND) is False

    def test_what_stays_is_the_first_answer_with_its_own_timestamp(
        self, queue: TaskQueue
    ) -> None:
        queue.complete_task("t1", FIRST)
        stamp = _task(queue).completed_at
        assert stamp is not None
        queue.complete_task("t1", SECOND)
        task = _task(queue)
        assert task.result == FIRST
        assert task.status == "completed"
        assert task.completed_at == stamp

    def test_a_refused_answer_sends_no_event_and_writes_nothing(
        self, queue: TaskQueue
    ) -> None:
        events: list[tuple[Any, ...]] = []
        queue.register_status_change_callback(lambda *event: events.append(event))
        with patch.object(queue, "_persist") as persist:
            queue.complete_task("t1", FIRST)
            queue.complete_task("t1", SECOND)
        assert events == [("t1", "active", "completed")]
        assert persist.call_count == 1

    def test_the_retention_timer_is_not_started_over(self, queue: TaskQueue) -> None:
        queue.complete_task("t1", FIRST)
        _task(queue).completed_at = datetime.now(UTC) - timedelta(seconds=30)
        queue.complete_task("t1", SECOND)
        assert queue.cleanup_completed_tasks(age_seconds=10) == 1
        assert queue.get_task("t1") is None

    def test_a_refused_answer_is_not_a_second_round_of_the_loop(
        self, queue: TaskQueue
    ) -> None:
        assert queue.add_task("r1", "prompt", loop_id="lp", auto_resubmit_timeout=0)
        queue.complete_task("r1", FIRST)
        queue.complete_task("r1", SECOND)
        rounds = queue.get_loops_snapshot()[0]["rounds"]
        assert [r["verdict"]["user_input"] for r in rounds] == ["first"]

    def test_the_task_that_follows_is_not_disturbed(self, queue: TaskQueue) -> None:
        assert queue.add_task("t2", "second prompt", auto_resubmit_timeout=0)
        queue.complete_task("t1", FIRST)
        assert _task(queue, "t2").status == "active"
        events: list[tuple[Any, ...]] = []
        queue.register_status_change_callback(lambda *event: events.append(event))
        assert queue.complete_task("t1", SECOND) is False
        assert events == []
        assert _task(queue, "t2").status == "active"

    def test_each_task_has_its_own_first_answer(self, queue: TaskQueue) -> None:
        assert queue.add_task("t2", "second prompt", auto_resubmit_timeout=0)
        assert queue.complete_task("t1", FIRST) is True
        assert queue.complete_task("t2", SECOND) is True
        assert _task(queue, "t1").result == FIRST
        assert _task(queue, "t2").result == SECOND

    def test_a_task_that_is_not_there_is_refused_as_before(
        self, queue: TaskQueue, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR, logger=QUEUE_LOGGER):
            assert queue.complete_task("nope", FIRST) is False


class WritersMeetBeforeTheLock:
    """Stands in for ``TaskQueue._lock`` so that several answers are *really* simultaneous.

    The first time each answering thread asks for the write lock it waits at a barrier, so none
    of them goes on until all have arrived; then they compete for the lock.  A decision taken
    before the lock is asked for (the mutant this exists for) has been taken by every thread by
    then, on the same state; a decision taken under the lock sees the winner's write.  Threads
    that did not ``join`` (the queue's own cleanup thread) pass straight through.
    """

    def __init__(self, inner: Any, parties: int) -> None:
        self._inner = inner
        self._barrier = threading.Barrier(parties, timeout=10)
        self._member = threading.local()

    def join(self) -> None:
        self._member.waiting = True

    def read_lock(self) -> Any:
        return self._inner.read_lock()

    @contextmanager
    def write_lock(self) -> Iterator[None]:
        if getattr(self._member, "waiting", False):
            self._member.waiting = False
            self._barrier.wait()
        with self._inner.write_lock():
            yield


def _answer_together(q: TaskQueue, task_id: str, answers: list[dict[str, Any]]) -> Any:
    """Every answer is sent by its own thread; returns what each call answered."""
    original = q._lock
    gate = WritersMeetBeforeTheLock(original, len(answers))
    outcomes: list[bool | None] = [None] * len(answers)
    errors: list[BaseException] = []

    def send(index: int) -> None:
        try:
            gate.join()
            outcomes[index] = q.complete_task(task_id, answers[index])
        except BaseException as exc:
            errors.append(exc)

    q._lock = cast(Any, gate)
    try:
        threads = [
            threading.Thread(target=send, args=(i,)) for i in range(len(answers))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not any(thread.is_alive() for thread in threads)
    finally:
        q._lock = original
    assert errors == []
    return outcomes


class TestTheDecisionIsMadeUnderTheLock:
    def test_two_answers_that_arrive_together_one_is_taken(
        self, queue: TaskQueue
    ) -> None:
        outcomes = _answer_together(queue, "t1", [FIRST, SECOND])
        assert sorted(outcomes) == [False, True]
        winner = FIRST if outcomes[0] else SECOND
        assert _task(queue).result == winner

    def test_eight_answers_that_arrive_together_one_is_taken(
        self, queue: TaskQueue
    ) -> None:
        answers = [{"user_input": f"a{i}", "selected_options": []} for i in range(8)]
        outcomes = _answer_together(queue, "t1", answers)
        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 7
        assert _task(queue).result == answers[outcomes.index(True)]


# --------------------------------------------------------------------------- the routes

_numbers = itertools.count(1)


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r851", task_id="r851-ui", auto_resubmit_timeout=0, port=19851
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    ui.feedback_result = None
    return ui.app.test_client()


@pytest.fixture
def task() -> Iterator[str]:
    """A queued task to answer.  The route queue is the process-wide one."""
    shared = get_task_queue()
    task_id = f"r851-task-{next(_numbers)}"
    assert shared.add_task(task_id=task_id, prompt="p", auto_resubmit_timeout=0)
    try:
        yield task_id
    finally:
        if shared.get_task(task_id) is not None:
            shared.remove_task(task_id)


def answer_through_the_task_route(
    client: FlaskClient, task_id: str, text: str, **kwargs: Any
) -> Any:
    return client.post(
        f"/api/tasks/{task_id}/submit",
        data={"feedback_text": text, "selected_options": "[]"},
        environ_base=LOOPBACK,
        **kwargs,
    )


def answer_through_the_legacy_route(
    client: FlaskClient, task_id: str, text: str, **kwargs: Any
) -> Any:
    return client.post(
        "/api/submit",
        data={"task_id": task_id, "feedback_text": text, "selected_options": "[]"},
        environ_base=LOOPBACK,
        **kwargs,
    )


Route = Callable[..., Any]
ROUTES: dict[str, Route] = {
    "task route": answer_through_the_task_route,
    "legacy route": answer_through_the_legacy_route,
}


def _stored_text(task_id: str) -> str:
    stored = get_task_queue().get_task(task_id)
    assert stored is not None
    assert stored.result is not None
    return str(stored.result["user_input"])


class TestBothRoutesKeepTheFirstAnswer:
    @pytest.mark.parametrize("route", ROUTES)
    def test_the_second_answer_is_a_409_and_the_first_stays(
        self, client: FlaskClient, task: str, route: str
    ) -> None:
        answer: Route = ROUTES[route]
        first = answer(client, task, "first")
        assert first.status_code == 200, first.get_data(as_text=True)[:200]
        second = answer(client, task, "second", headers={"Accept-Language": "en"})
        assert second.status_code == 409, second.get_data(as_text=True)[:200]
        assert second.get_json() == {
            "success": False,
            "status": "error",
            "error": CODE,
            "message": msg(KEY, lang="en"),
        }
        assert _stored_text(task) == "first"

    @pytest.mark.parametrize(
        ("first_route", "second_route"),
        [
            ("task route", "legacy route"),
            ("legacy route", "task route"),
        ],
    )
    def test_the_other_route_cannot_answer_a_second_time_either(
        self, client: FlaskClient, task: str, first_route: str, second_route: str
    ) -> None:
        assert ROUTES[first_route](client, task, "first").status_code == 200
        refused = ROUTES[second_route](client, task, "second")
        assert refused.status_code == 409, refused.get_data(as_text=True)[:200]
        assert refused.get_json()["error"] == CODE
        assert _stored_text(task) == "first"

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_the_refusal_speaks_the_visitors_language(
        self, client: FlaskClient, task: str, language: str
    ) -> None:
        answer_through_the_task_route(client, task, "first")
        refused = answer_through_the_task_route(
            client, task, "second", headers={"Accept-Language": language}
        )
        assert refused.status_code == 409
        assert refused.get_json()["message"] == msg(KEY, lang=language)

    def test_the_three_languages_say_it_in_their_own_words(self) -> None:
        texts = {language: msg(KEY, lang=language) for language in LANGUAGES}
        assert KEY not in texts.values()
        assert len(set(texts.values())) == len(LANGUAGES)

    def test_a_refused_answer_is_not_left_for_the_legacy_getter(
        self, ui: WebFeedbackUI, client: FlaskClient, task: str
    ) -> None:
        """``GET /api/feedback`` hands out ``feedback_result`` as "what the user submitted"."""
        assert answer_through_the_legacy_route(client, task, "first").status_code == 200
        assert ui.feedback_result is not None
        assert ui.feedback_result["user_input"] == "first"
        assert (
            answer_through_the_legacy_route(client, task, "second").status_code == 409
        )
        assert ui.feedback_result is not None
        assert ui.feedback_result["user_input"] == "first"

    @pytest.mark.parametrize("route", ROUTES)
    def test_two_answers_sent_together_one_is_taken(
        self, ui: WebFeedbackUI, task: str, route: str
    ) -> None:
        answer: Route = ROUTES[route]
        start = threading.Barrier(2, timeout=10)
        replies: dict[str, Any] = {}
        errors: list[BaseException] = []

        def send(text: str) -> None:
            try:
                own_client = ui.app.test_client()
                start.wait()
                replies[text] = answer(own_client, task, text)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=send, args=(t,)) for t in ("A", "B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not any(thread.is_alive() for thread in threads)
        assert errors == []
        codes = {text: reply.status_code for text, reply in replies.items()}
        assert sorted(codes.values()) == [200, 409], codes
        winner = "A" if codes["A"] == 200 else "B"
        assert _stored_text(task) == winner

    def test_answering_a_task_nobody_answered_is_unchanged(
        self, client: FlaskClient, task: str
    ) -> None:
        reply = answer_through_the_task_route(client, task, "only")
        assert reply.status_code == 200
        assert reply.get_json()["success"] is True
        stored = get_task_queue().get_task(task)
        assert stored is not None
        assert stored.status == "completed"
        assert _stored_text(task) == "only"


# ------------------------------------------------------------------ structure and documents


def _complete_task_parts() -> tuple[list[ast.stmt], list[ast.stmt]]:
    """The statements of ``TaskQueue.complete_task`` before its lock and inside it."""
    tree = ast.parse((SRC / "task_queue.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "TaskQueue":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "complete_task":
                    before: list[ast.stmt] = []
                    for statement in item.body:
                        if isinstance(statement, ast.With):
                            return before, statement.body
                        before.append(statement)
    raise AssertionError("TaskQueue.complete_task has no with-block")


class TestStructure:
    def test_the_decision_is_taken_under_the_lock_before_anything_is_written(
        self,
    ) -> None:
        before, body = _complete_task_parts()
        assert not [
            node
            for statement in before
            for node in ast.walk(statement)
            if isinstance(node, ast.Attribute) and node.attr == "status"
        ], "a status read before the lock is a decision on state that may change"
        refusals = [
            index
            for index, statement in enumerate(body)
            if isinstance(statement, ast.If)
            and "TaskStatus.COMPLETED" in ast.unparse(statement.test)
            and ast.unparse(statement.body[-1]) == "return False"
        ]
        writes = [
            index
            for index, statement in enumerate(body)
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == "status"
                for target in statement.targets
            )
        ]
        assert len(refusals) == 1
        assert len(writes) == 1
        assert refusals[0] < writes[0]

    def test_both_routes_ask_one_helper_what_to_answer_when_the_queue_refuses(
        self,
    ) -> None:
        calls: dict[str, int] = {}
        for name in ("task.py", "feedback.py"):
            tree = ast.parse((SRC / "web_ui_routes" / name).read_text(encoding="utf-8"))
            calls[name] = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "refused_answer_response"
            )
        assert calls == {"task.py": 1, "feedback.py": 1}

    def test_the_refusal_is_written_in_one_place(self) -> None:
        homes: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            homes += [
                f"{path.relative_to(SRC)}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and node.value == CODE
            ]
        assert len(homes) == 1, homes
        assert homes[0].startswith("web_ui_routes/_task_answer.py:")

    @pytest.mark.parametrize(
        "path", ["/api/submit", "/api/tasks/<task_id>/submit"], ids=["legacy", "task"]
    )
    def test_the_409_is_documented_with_the_envelope_that_is_sent(
        self, ui: WebFeedbackUI, path: str
    ) -> None:
        for rule in ui.app.url_map.iter_rules():
            if rule.rule == path and "POST" in (rule.methods or set()):
                function = inspect.unwrap(ui.app.view_functions[rule.endpoint])
                doc = inspect.getdoc(function)
                break
        else:
            raise AssertionError(path)
        assert doc is not None
        responses = yaml.safe_load(doc.split("---", 1)[1])["responses"]
        assert 409 in responses, f"{path}: 409 is not documented"
        properties = responses[409]["schema"]["properties"]
        assert set(properties) == {"success", "status", "error", "message"}
        assert properties["error"]["enum"] == [CODE]
        assert properties["success"]["enum"] == [False]

    @pytest.mark.parametrize("guide", ["architecture.md", "architecture.zh-CN.md"])
    def test_the_architecture_guide_says_what_a_second_answer_gets(
        self, guide: str
    ) -> None:
        text = (ROOT / "docs" / guide).read_text(encoding="utf-8")
        assert CODE in text
        assert "409" in text
