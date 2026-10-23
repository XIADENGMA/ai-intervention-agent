"""R846: a submit is a success only when the queue took the answer.

``POST /api/tasks/<id>/submit`` - the route the page and the VS Code view use - looks the task up,
then reads the form (which is where a slow upload is received and its images are validated), and only
then calls ``TaskQueue.complete_task``.  It threw away what that call returned.  When the task was
removed in between - the MCP call gave up and closed it, the user closed it in another tab, the
cleanup ran - ``complete_task`` answered ``False``, the route answered ``200 {"success": true}``, the
page said "submitted" and emptied the text box, and nobody ever received the answer.

Now the route answers what it already answers when the task is gone *before* the read:
``404 {"success": false, "error": ...}``.  The page then shows an error and keeps the draft.
``/api/submit`` ignored the result of the same call (a much smaller window there: it looks the task
up after the read), so it tells the truth too.

The window is real, not a thought experiment: the request body is received *inside* the handler, so a
slow upload keeps the window open for as long as it takes.  The first tests below remove the task while
the body is being read, with nothing patched.
"""

from __future__ import annotations

import ast
import io
import itertools
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent.task_queue import TaskStatus
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI

SRC = Path(__file__).resolve().parents[1] / "src" / "ai_intervention_agent"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
QUEUE_LOGGER = "ai_intervention_agent.task_queue"
GONE = {"success": False, "error": "任务不存在"}


class BodyThatRunsAHookWhenFirstRead(io.BytesIO):
    """A request body as the handler sees it: nothing is received until the form is read."""

    def __init__(self, data: bytes, hook: Callable[[], object]) -> None:
        super().__init__(data)
        self._hook: Callable[[], object] | None = hook

    def _fire(self) -> None:
        hook, self._hook = self._hook, None
        if hook is not None:
            hook()

    def read(self, size: int | None = -1) -> bytes:
        self._fire()
        return super().read(size)

    def read1(self, size: int | None = -1) -> bytes:
        self._fire()
        return super().read1(size)

    def readinto(self, buffer: Any) -> int:
        self._fire()
        return super().readinto(buffer)

    def readline(self, size: int | None = -1) -> bytes:
        self._fire()
        return super().readline(size)


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r846", task_id="r846-ui", auto_resubmit_timeout=0, port=19846
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    ui.feedback_result = None
    return ui.app.test_client()


_numbers = itertools.count(1)


@pytest.fixture
def task() -> Iterator[str]:
    """A queued task to answer.  It may be gone by the end of the test."""
    queue = get_task_queue()
    task_id = f"r846-task-{next(_numbers)}"
    queue.add_task(
        task_id=task_id, prompt="p", predefined_options=["x"], auto_resubmit_timeout=0
    )
    try:
        yield task_id
    finally:
        if queue.get_task(task_id) is not None:
            queue.remove_task(task_id)


FORM = b"feedback_text=hello&selected_options=%5B%22x%22%5D"


def removed_when_asked(task_id: str) -> Callable[[str, dict[str, Any]], bool]:
    """A ``complete_task`` that finds the task removed - a removal racing the route.

    ``False`` alone is no longer enough to get a 404: since R851 a queue that refuses an answer for
    a task that is still there is answering "already answered" (409).
    """

    def complete(_task_id: str, _result: dict[str, Any]) -> bool:
        get_task_queue().remove_task(task_id)
        return False

    return complete


def post_form_that_removes(
    client: FlaskClient, url: str, body: bytes, task_id: str
) -> Any:
    """POST ``body``; the task is removed the moment the handler starts reading it."""
    stream = BodyThatRunsAHookWhenFirstRead(
        body, lambda: get_task_queue().remove_task(task_id)
    )
    return client.post(
        url,
        input_stream=stream,
        content_type="application/x-www-form-urlencoded",
        content_length=len(body),
        environ_base=LOOPBACK,
    )


class TestTheTaskScopedRoute:
    def test_a_task_removed_while_the_form_is_read_is_a_404(
        self, client: FlaskClient, task: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR, logger=QUEUE_LOGGER):
            resp = post_form_that_removes(
                client, f"/api/tasks/{task}/submit", FORM, task
            )
        assert resp.status_code == 404, resp.get_data(as_text=True)[:200]
        assert resp.get_json() == GONE

    def test_it_is_the_answer_the_route_gives_when_the_task_is_gone_beforehand(
        self, client: FlaskClient, task: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        get_task_queue().remove_task(task)
        with caplog.at_level(logging.ERROR, logger=QUEUE_LOGGER):
            early = client.post(
                f"/api/tasks/{task}/submit",
                data={"feedback_text": "hello", "selected_options": "[]"},
                environ_base=LOOPBACK,
            )
        assert (early.status_code, early.get_json()) == (404, GONE)

    def test_multipart_with_an_image_is_answered_the_same_way(
        self, client: FlaskClient, task: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        boundary = "r846boundary"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="feedback_text"\r\n\r\nhello\r\n'
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="selected_options"\r\n\r\n[]\r\n'
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="image_0"; filename="a.png"\r\n'
                "Content-Type: image/png\r\n\r\n"
            ).encode()
            + png
            + f"\r\n--{boundary}--\r\n".encode()
        )
        stream = BodyThatRunsAHookWhenFirstRead(
            body, lambda: get_task_queue().remove_task(task)
        )
        with caplog.at_level(logging.ERROR, logger=QUEUE_LOGGER):
            resp = client.post(
                f"/api/tasks/{task}/submit",
                input_stream=stream,
                content_type=f"multipart/form-data; boundary={boundary}",
                content_length=len(body),
                environ_base=LOOPBACK,
            )
        assert (resp.status_code, resp.get_json()) == (404, GONE)

    def test_a_task_that_is_still_there_is_answered_and_completed(
        self, client: FlaskClient, task: str
    ) -> None:
        resp = client.post(
            f"/api/tasks/{task}/submit",
            data=FORM,
            content_type="application/x-www-form-urlencoded",
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert resp.get_json()["success"] is True
        stored = get_task_queue().get_task(task)
        assert stored is not None
        assert stored.status == TaskStatus.COMPLETED
        assert stored.result is not None
        assert stored.result["user_input"] == "hello"
        assert stored.result["selected_options"] == ["x"]

    def test_nothing_is_left_behind_by_the_refused_answer(
        self, client: FlaskClient, task: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR, logger=QUEUE_LOGGER):
            post_form_that_removes(client, f"/api/tasks/{task}/submit", FORM, task)
        assert get_task_queue().get_task(task) is None


class TestTheLegacyRoute:
    """``/api/submit`` with the id of a task, as the VS Code view falls back to it.

    The queue is patched through the instance the routes use, not through the class this module
    imported: ``test_lock_watchdog_r51a`` reloads ``task_queue`` and, in a worker that ran it first,
    that class is no longer the one behind ``get_task_queue()``.
    """

    def test_a_queue_that_does_not_take_the_answer_is_a_404(
        self, client: FlaskClient, task: str
    ) -> None:
        with patch.object(
            get_task_queue(), "complete_task", side_effect=removed_when_asked(task)
        ) as call:
            resp = client.post(
                "/api/submit",
                data={
                    "task_id": task,
                    "feedback_text": "hello",
                    "selected_options": "[]",
                },
                environ_base=LOOPBACK,
            )
        assert call.call_count == 1
        assert (resp.status_code, resp.get_json()) == (404, GONE)

    def test_the_refused_answer_is_not_left_for_the_legacy_getter(
        self, ui: WebFeedbackUI, client: FlaskClient, task: str
    ) -> None:
        """``GET /api/feedback`` hands out ``feedback_result`` as "what the user submitted"."""
        with patch.object(
            get_task_queue(), "complete_task", side_effect=removed_when_asked(task)
        ):
            client.post(
                "/api/submit",
                data={
                    "task_id": task,
                    "feedback_text": "hello",
                    "selected_options": "[]",
                },
                environ_base=LOOPBACK,
            )
        assert ui.feedback_result is None

    def test_the_active_task_is_answered_the_same_way(
        self, client: FlaskClient, task: str
    ) -> None:
        queue = get_task_queue()
        assert queue.set_active_task(task)
        active = queue.get_active_task()
        assert active is not None
        assert active.task_id == task
        with patch.object(queue, "complete_task", side_effect=removed_when_asked(task)):
            resp = client.post(
                "/api/submit",
                data={"feedback_text": "hello", "selected_options": "[]"},
                environ_base=LOOPBACK,
            )
        assert (resp.status_code, resp.get_json()) == (404, GONE)

    def test_a_task_that_is_there_is_answered_and_completed(
        self, client: FlaskClient, task: str
    ) -> None:
        resp = client.post(
            "/api/submit",
            data={"task_id": task, "feedback_text": "hello", "selected_options": "[]"},
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert resp.get_json()["status"] == "success"
        stored = get_task_queue().get_task(task)
        assert stored is not None
        assert stored.status == TaskStatus.COMPLETED


class TestStructure:
    def test_no_code_throws_away_what_complete_task_returns(self) -> None:
        """``complete_task`` says ``False`` for a task that is not there.  A call used as a
        statement is a caller that cannot tell."""
        offenders: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "complete_task"
                ):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
        assert offenders == []

    def test_the_scan_sees_both_routes(self) -> None:
        """Without this the scan could pass by finding nothing to look at."""
        found: dict[str, int] = {}
        for name in ("task.py", "feedback.py"):
            tree = ast.parse((SRC / "web_ui_routes" / name).read_text(encoding="utf-8"))
            found[name] = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "complete_task"
            )
        assert found == {"task.py": 1, "feedback.py": 1}
