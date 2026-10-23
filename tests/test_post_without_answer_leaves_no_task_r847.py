"""R847: a task whose creation request got no answer must not stay in the Web UI.

``interactive_feedback`` creates the task with ``POST /api/tasks`` and, when that request fails with an
``httpx`` error, tells the agent to call again.  For some errors the Web UI has *not* seen the request
(``ConnectError``: nothing listens), for others it certainly has: a ``ReadTimeout`` means the request was
sent and the answer did not arrive in time, a ``RemoteProtocolError`` / ``ReadError`` that the connection
broke while the answer was on its way.  The queue had already taken the task by then.  The agent calls
again, a second task with the same question is queued behind the first, and the person sees the first one:
what they type goes to a task that nobody waits for, and the agent's second call (the one that is waiting)
only gets its answer when they answer again.  It is the ghost-task loop that R13 closed for the wait and
R775 for the cancellation, here for the request that creates the task.

The client below hands every request to the real Web UI routes (a Flask test client), so the task is
really created and ``/api/tasks/<id>/close`` really removes it; only the *answer* to ``POST /api/tasks`` is
replaced by the failure.  Nothing in the Web UI is patched.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import itertools
import logging
import textwrap
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from flask.testing import FlaskClient

import ai_intervention_agent.server_feedback as server_feedback
from ai_intervention_agent import server_config
from ai_intervention_agent.server_config import WebUIConfig
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI

LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
_ids = itertools.count(1)


@pytest.fixture(scope="module")
def web_ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r847", task_id="r847-ui", auto_resubmit_timeout=0, port=19847
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    return instance


@pytest.fixture
def flask_client(web_ui: WebFeedbackUI) -> FlaskClient:
    return web_ui.app.test_client()


class WebUIOnTheOtherEnd:
    """The routes of the Web UI behind a client that can lose the answer to the request that creates a task."""

    def __init__(
        self, flask_client: FlaskClient, *, lose_answer_to_create: Exception | None
    ) -> None:
        self.flask_client = flask_client
        self.lose_answer_to_create = lose_answer_to_create
        self.requests: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.lose_answer_to_create is not None and request.url.path == "/api/tasks":
            if not isinstance(self.lose_answer_to_create, httpx.ConnectError):
                self._deliver(request)  # the Web UI handles it, the answer is lost
            raise self.lose_answer_to_create
        return self._deliver(request)

    def _deliver(self, request: httpx.Request) -> httpx.Response:
        reply = self.flask_client.open(
            request.url.path,
            method=request.method,
            data=request.content,
            content_type=request.headers.get("content-type", "application/json"),
            environ_base=LOOPBACK,
        )
        return httpx.Response(
            reply.status_code,
            content=reply.get_data(),
            headers={"content-type": reply.content_type or "application/json"},
        )

    def client(self) -> PostOnlyClient:
        return PostOnlyClient(self)


class PostOnlyClient:
    """What the tool uses of ``httpx.AsyncClient`` here.  Not a real client: ``tests/conftest.py``
    makes every ``AsyncClient.send`` raise, so that no test can reach a real network."""

    def __init__(self, other_end: WebUIOnTheOtherEnd) -> None:
        self.other_end = other_end

    async def post(
        self, url: str, *, json: Any = None, timeout: float | None = None
    ) -> httpx.Response:
        del timeout
        return self.other_end.handle(httpx.Request("POST", url, json=json))


@pytest.fixture
def task_id() -> Iterator[str]:
    identifier = f"r847-task-{next(_ids)}"
    yield identifier
    queue = get_task_queue()
    if queue.get_task(identifier) is not None:
        queue.remove_task(identifier)


def call_the_tool(
    monkeypatch: pytest.MonkeyPatch, other_end: WebUIOnTheOtherEnd, task_id: str
) -> Any:
    async def noop(*_: Any, **__: Any) -> None:
        return None

    sm = server_feedback.service_manager
    monkeypatch.setattr(
        sm,
        "get_web_ui_config",
        lambda: (WebUIConfig(host="127.0.0.1", port=19847), 120),
    )
    client = other_end.client()
    monkeypatch.setattr(sm, "get_async_client", lambda _config: client)
    monkeypatch.setattr(sm, "ensure_web_ui_running", noop)
    monkeypatch.setattr(server_feedback, "NOTIFICATION_AVAILABLE", False)
    monkeypatch.setattr(server_config, "_generate_task_id", lambda: task_id)

    return asyncio.run(
        server_feedback.interactive_feedback(
            message="r847 question",
            predefined_options=None,
            feedback_placeholder=None,
            header_label=None,
            loop_id=None,
            loop_objective=None,
            loop_phase=None,
            success_criteria=None,
            iteration_label=None,
            ctx=None,
        )
    )


def failure(kind: str) -> Exception:
    return {
        "read-timeout": httpx.ReadTimeout("the answer did not arrive in time"),
        "remote-protocol": httpx.RemoteProtocolError(
            "Server disconnected without sending a response."
        ),
        "read-error": httpx.ReadError("connection reset by peer"),
        "write-timeout": httpx.WriteTimeout("the request was not sent in time"),
        "connect-error": httpx.ConnectError("nothing listens"),
    }[kind]


AMBIGUOUS = ["read-timeout", "remote-protocol", "read-error", "write-timeout"]


class TestAnAnswerThatNeverArrived:
    @pytest.mark.parametrize("kind", AMBIGUOUS)
    def test_the_task_the_web_ui_created_is_closed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        flask_client: FlaskClient,
        task_id: str,
        kind: str,
    ) -> None:
        other_end = WebUIOnTheOtherEnd(
            flask_client, lose_answer_to_create=failure(kind)
        )

        result = call_the_tool(monkeypatch, other_end, task_id)

        assert result == server_config._make_resubmit_response()
        assert ("POST", "/api/tasks") in other_end.requests
        assert get_task_queue().get_task(task_id) is None

    def test_it_is_the_close_route_that_does_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
        flask_client: FlaskClient,
        task_id: str,
    ) -> None:
        other_end = WebUIOnTheOtherEnd(
            flask_client, lose_answer_to_create=failure("read-timeout")
        )

        call_the_tool(monkeypatch, other_end, task_id)

        assert other_end.requests == [
            ("POST", "/api/tasks"),
            ("POST", f"/api/tasks/{task_id}/close"),
        ]

    def test_only_the_task_of_this_call_is_closed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        flask_client: FlaskClient,
        task_id: str,
    ) -> None:
        queue = get_task_queue()
        bystander = f"{task_id}-bystander"
        queue.add_task(task_id=bystander, prompt="someone else's question")
        try:
            other_end = WebUIOnTheOtherEnd(
                flask_client, lose_answer_to_create=failure("read-timeout")
            )

            call_the_tool(monkeypatch, other_end, task_id)

            assert queue.get_task(bystander) is not None
            assert queue.get_task(task_id) is None
        finally:
            queue.remove_task(bystander)


class TestAnAnswerThatCouldNotHaveBeenAboutATask:
    def test_a_refused_connection_still_gives_the_resubmit_prompt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        flask_client: FlaskClient,
        task_id: str,
    ) -> None:
        other_end = WebUIOnTheOtherEnd(
            flask_client, lose_answer_to_create=failure("connect-error")
        )

        result = call_the_tool(monkeypatch, other_end, task_id)

        assert result == server_config._make_resubmit_response()
        assert get_task_queue().get_task(task_id) is None

    def test_a_task_the_web_ui_took_and_answered_is_not_closed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        flask_client: FlaskClient,
        task_id: str,
    ) -> None:
        """Control: a request that worked is the wait's business, the failure branch is not run."""
        other_end = WebUIOnTheOtherEnd(flask_client, lose_answer_to_create=None)

        async def finished(*_: Any, **__: Any) -> dict[str, str]:
            return {"interactive_feedback": "ok"}

        monkeypatch.setattr(server_feedback, "wait_for_task_completion", finished)

        call_the_tool(monkeypatch, other_end, task_id)

        assert other_end.requests == [("POST", "/api/tasks")]
        assert get_task_queue().get_task(task_id) is not None


class TestTheCleanupIsBestEffort:
    def test_a_close_that_fails_does_not_change_the_answer_to_the_agent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        flask_client: FlaskClient,
        task_id: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        other_end = WebUIOnTheOtherEnd(
            flask_client, lose_answer_to_create=failure("read-timeout")
        )
        original = other_end.handle

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/close"):
                other_end.requests.append((request.method, request.url.path))
                raise httpx.ReadTimeout("the Web UI is still busy")
            return original(request)

        monkeypatch.setattr(other_end, "handle", handle)

        with caplog.at_level(logging.ERROR):
            result = call_the_tool(monkeypatch, other_end, task_id)

        assert result == server_config._make_resubmit_response()
        assert other_end.requests[-1] == ("POST", f"/api/tasks/{task_id}/close")


class TestStructure:
    def test_the_failure_branch_closes_through_the_shielded_runner(self) -> None:
        """R775: a cleanup awaited directly in a cancelled handler never sends its request."""
        source = textwrap.dedent(
            inspect.getsource(server_feedback.interactive_feedback)
        )
        tree = ast.parse(source)
        handlers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Attribute)
            and node.type.attr == "HTTPError"
        ]
        assert len(handlers) == 1
        awaited = [
            node.value
            for node in ast.walk(handlers[0])
            if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
        ]
        runners = [
            call
            for call in awaited
            if isinstance(call.func, ast.Name) and call.func.id == "_run_to_completion"
        ]
        assert runners, "the failure branch must await _run_to_completion(...)"
        assert any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "_close_orphan_task_best_effort"
            for runner in runners
            for argument in runner.args
            for inner in ast.walk(argument)
        )
