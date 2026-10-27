"""R912: the submit routes do not close a question with a request that holds no answer.

R829 found this on ``POST /api/submit``: a body that was neither a form nor a JSON object was read
as "no answer", ended the question the user was waiting on with an empty one and answered ``200``.
The route the page and the VS Code panel actually use, ``POST /api/tasks/<id>/submit``, was never
given the same look.  It reads ``request.form.get("feedback_text", "")`` and
``request.form.get("selected_options", "[]")``, and a request that is not a form gives it both
defaults, so each of these completed the task with ``{"user_input": "", "selected_options": []}`` and
answered ``200 {"success": true}``:

* no body at all (``curl -X POST``, a script that forgot its payload);
* a JSON document that *holds* the answer: the text and the ticks were thrown away without a word and
  the sender was told "submitted";
* ``null``, an array, a document that does not parse, plain text, bytes;
* a multipart body that Werkzeug cannot read (no boundary, a boundary that does not match, cut off:
  what a proxy or a dropped connection leaves behind), an empty form;
* a form that has fields, but not one of the two an answer is made of (``user_input=...`` is what
  ``/api/submit`` calls the text in its JSON; a form that uses it got the same empty answer).

The agent receives that empty answer as the user's reply (the MCP call returns it the moment the
status event arrives), the question is gone from the page, and nobody can send the real answer: the
second one is a ``409`` (R851).

The page, the VS Code panel and the auto-resubmit all send ``feedback_text`` and ``selected_options``
(``FormData``), also when both are empty, so a request that has neither of them and no file is not
one of them.  It is now answered ``400 {"success": false, "status": "error", "error": "invalid_body",
"message": ...}`` and the task stays open and untouched.  What did work keeps working: a form with
either field (empty or not, with or without other fields next to it), a body that is only an image,
``404`` for a task that is not there (looked up first, as before), the ``selected_options`` errors, the
``413`` and the ``409``.

``POST /api/submit`` shares the rule for forms (one definition, ``request_holds_an_answer``): a form
whose fields are none of the two used to complete the task it names, or the active one, with the
same empty answer; it is the same ``400`` now.  What R829 decided for that route does not change: a
JSON object, an empty one included, is an answer (the R348 baseline posts ``{}``), and the unreadable
bodies stay ``400 invalid_json`` / ``invalid_body`` with their own envelope.
"""

from __future__ import annotations

import ast
import io
import itertools
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from flask.testing import FlaskClient

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.i18n import msg
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "src" / "ai_intervention_agent" / "web_ui_routes"
TASK_ROUTES = ROUTES / "task.py"
FEEDBACK_ROUTES = ROUTES / "feedback.py"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
LANGUAGES = ("en", "zh-CN", "zh-TW")
KEY = "feedback.bodyMustBeForm"
CODE = "invalid_body"

PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)
GOOD_PART = b'--B\r\nContent-Disposition: form-data; name="feedback_text"\r\n\r\nthe real answer\r\n--B--\r\n'
URLENCODED = "application/x-www-form-urlencoded"
MULTIPART = "multipart/form-data"
CUT_OFF_BOUNDARY = "multipart/form-data; boundary=B"

#: Bodies that hold no answer.  Each one used to complete the task with an empty answer.
NO_ANSWER: dict[str, dict[str, Any]] = {
    "no body": {},
    "answer in the query string only": {
        "query_string": {
            "feedback_text": "the real answer",
            "selected_options": '["a"]',
        }
    },
    "json object that holds the answer": {
        "json": {"feedback_text": "the real answer", "selected_options": ["a"]}
    },
    "json null": {"data": "null", "content_type": "application/json"},
    "json array": {"data": "[]", "content_type": "application/json"},
    "json that does not parse": {
        "data": '{"feedback_text": ',
        "content_type": "application/json",
    },
    "plain text": {"data": "the real answer", "content_type": "text/plain"},
    "bytes": {"data": b"\x00\x01\x02", "content_type": "application/octet-stream"},
    "urlencoded, empty": {"data": "", "content_type": URLENCODED},
    "urlencoded, no pairs": {"data": "&&&===&", "content_type": URLENCODED},
    "urlencoded, other fields only": {
        "data": {"user_input": "the real answer", "text": "x"},
        "content_type": URLENCODED,
    },
    "multipart, no boundary": {"data": GOOD_PART, "content_type": MULTIPART},
    "multipart, boundary that does not match": {
        "data": GOOD_PART,
        "content_type": "multipart/form-data; boundary=OTHER",
    },
    "multipart, cut off": {
        "data": GOOD_PART[:60],
        "content_type": CUT_OFF_BOUNDARY,
    },
    "multipart, a form with no fields": {"data": {}, "content_type": MULTIPART},
    "multipart, zero bytes": {
        "input_stream": io.BytesIO(b""),
        "content_type": CUT_OFF_BOUNDARY,
    },
    "multipart, only the closing line": {
        "data": b"--B--\r\n",
        "content_type": CUT_OFF_BOUNDARY,
    },
    "multipart, other fields only": {
        "data": {"user_input": "the real answer"},
        "content_type": MULTIPART,
    },
}

#: What ``/api/submit`` refuses as well: no form field and no file and not a JSON object (R829), or a
#: form that has fields but none of the answer's (R912).
ALSO_REFUSED_BY_THE_LEGACY_ROUTE = (
    "no body",
    "answer in the query string only",
    "json null",
    "json array",
    "json that does not parse",
    "plain text",
    "bytes",
    "urlencoded, empty",
    "urlencoded, no pairs",
    "urlencoded, other fields only",
    "multipart, no boundary",
    "multipart, boundary that does not match",
    "multipart, cut off",
    "multipart, a form with no fields",
    "multipart, zero bytes",
    "multipart, only the closing line",
    "multipart, other fields only",
)

#: The refusals that are new on ``/api/submit``: it read these forms, took the defaults and answered 200.
FORMS_WITHOUT_AN_ANSWER = (
    "urlencoded, no pairs",
    "urlencoded, other fields only",
    "multipart, other fields only",
)

_numbers = itertools.count(1)


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r912", task_id="r912-ui", auto_resubmit_timeout=0, port=19912
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    return ui.app.test_client()


@pytest.fixture
def task() -> Iterator[str]:
    """A queued question to answer.  The route queue is the process-wide one."""
    shared = get_task_queue()
    task_id = f"r912-task-{next(_numbers)}"
    assert shared.add_task(task_id=task_id, prompt="p", auto_resubmit_timeout=0)
    try:
        yield task_id
    finally:
        if shared.get_task(task_id) is not None:
            shared.remove_task(task_id)


@pytest.fixture
def events(task: str) -> Iterator[list[tuple[str, str | None, str]]]:
    """The status changes of the question under test, as the MCP call would see them."""
    seen: list[tuple[str, str | None, str]] = []

    def record(task_id: str, old_status: str | None, new_status: str) -> None:
        if task_id == task:
            seen.append((task_id, old_status, new_status))

    shared = get_task_queue()
    shared.register_status_change_callback(record)
    try:
        yield seen
    finally:
        shared.unregister_status_change_callback(record)


def post(client: FlaskClient, task_id: str, **kwargs: Any) -> Any:
    return client.post(
        f"/api/tasks/{task_id}/submit",
        environ_base=LOOPBACK,
        headers={"Accept-Language": "en"},
        **kwargs,
    )


def stored(task_id: str) -> Any:
    found = get_task_queue().get_task(task_id)
    assert found is not None
    return found


class TestABodyWithNoAnswerInItIsRefused:
    @pytest.mark.parametrize("name", NO_ANSWER)
    def test_it_is_a_400_that_says_what_is_missing(
        self, client: FlaskClient, task: str, name: str
    ) -> None:
        response = post(client, task, **NO_ANSWER[name])
        assert response.status_code == 400, response.get_data(as_text=True)[:200]
        assert response.get_json() == {
            "success": False,
            "status": "error",
            "error": CODE,
            "message": msg(KEY, lang="en"),
        }

    @pytest.mark.parametrize("name", NO_ANSWER)
    def test_the_question_stays_open_and_nobody_is_told(
        self,
        client: FlaskClient,
        task: str,
        events: list[tuple[str, str | None, str]],
        name: str,
    ) -> None:
        before = stored(task).status
        post(client, task, **NO_ANSWER[name])
        after = stored(task)
        assert after.status == before
        assert after.status != "completed"
        assert after.result is None
        assert after.completed_at is None
        assert events == []

    @pytest.mark.parametrize("name", NO_ANSWER)
    def test_the_answer_that_follows_is_taken(
        self, client: FlaskClient, task: str, name: str
    ) -> None:
        assert post(client, task, **NO_ANSWER[name]).status_code == 400
        accepted = post(
            client,
            task,
            data={"feedback_text": "the real answer", "selected_options": '["a"]'},
        )
        assert accepted.status_code == 200, accepted.get_data(as_text=True)[:200]
        assert stored(task).result == {
            "user_input": "the real answer",
            "selected_options": ["a"],
        }

    @pytest.mark.parametrize("name", NO_ANSWER)
    def test_a_task_that_is_not_there_is_still_a_404_whatever_the_body(
        self, client: FlaskClient, name: str
    ) -> None:
        response = post(client, "r912-not-there", **NO_ANSWER[name])
        assert response.status_code == 404
        assert response.get_json() == {"success": False, "error": "任务不存在"}

    @pytest.mark.parametrize("name", NO_ANSWER)
    def test_the_body_is_judged_before_the_queue_is_asked(
        self, client: FlaskClient, task: str, name: str
    ) -> None:
        # The order is: the task is there (404), the body holds an answer (400), the
        # options can be read (400), the queue takes it (409).  A request that carries no
        # answer is told so, also for a question that already has its own.
        assert get_task_queue().complete_task(
            task, {"user_input": "first", "selected_options": []}
        )
        response = post(client, task, **NO_ANSWER[name])
        assert response.status_code == 400
        assert response.get_json()["error"] == CODE
        assert stored(task).result == {"user_input": "first", "selected_options": []}


class TestEveryFormThatHoldsAnAnswerStillAnswers:
    @pytest.mark.parametrize("content_type", [URLENCODED, MULTIPART])
    @pytest.mark.parametrize(
        ("fields", "result"),
        [
            pytest.param(
                {"feedback_text": "hello"},
                {"user_input": "hello", "selected_options": []},
                id="text only",
            ),
            pytest.param(
                {"selected_options": '["a", "b"]'},
                {"user_input": "", "selected_options": ["a", "b"]},
                id="options only",
            ),
            pytest.param(
                {"feedback_text": "", "selected_options": "[]"},
                {"user_input": "", "selected_options": []},
                id="both, empty (what the page sends when nothing was typed or ticked)",
            ),
            pytest.param(
                {"feedback_text": "", "selected_options": '["a"]'},
                {"user_input": "", "selected_options": ["a"]},
                id="no text, one tick",
            ),
            pytest.param(
                {"feedback_text": ""},
                {"user_input": "", "selected_options": []},
                id="an empty text and nothing else is an answer of its own",
            ),
            pytest.param(
                {"feedback_text": "hello", "task_id": "x", "source": "vscode"},
                {"user_input": "hello", "selected_options": []},
                id="other fields next to the answer",
            ),
        ],
    )
    def test_the_form_is_the_answer(
        self,
        client: FlaskClient,
        task: str,
        content_type: str,
        fields: dict[str, str],
        result: dict[str, Any],
    ) -> None:
        response = post(client, task, data=fields, content_type=content_type)
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        assert response.get_json()["success"] is True
        assert stored(task).result == result

    def test_a_body_that_is_only_a_picture_is_an_answer(
        self, client: FlaskClient, task: str
    ) -> None:
        response = post(
            client,
            task,
            data={"image_0": (io.BytesIO(PNG), "shot.png")},
            content_type=MULTIPART,
        )
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        answer = stored(task).result
        assert answer is not None
        assert answer["user_input"] == ""
        assert len(answer["images"]) == 1

    def test_a_picture_next_to_the_text_is_taken_with_it(
        self, client: FlaskClient, task: str
    ) -> None:
        response = post(
            client,
            task,
            data={
                "feedback_text": "see the picture",
                "selected_options": "[]",
                "image_0": (io.BytesIO(PNG), "shot.png"),
            },
            content_type=MULTIPART,
        )
        assert response.status_code == 200
        answer = stored(task).result
        assert answer is not None
        assert answer["user_input"] == "see the picture"
        assert len(answer["images"]) == 1


class TestTheOtherChecksAreWhereTheyWere:
    def test_selected_options_that_are_not_an_array_are_still_the_old_400(
        self, client: FlaskClient, task: str
    ) -> None:
        response = post(
            client, task, data={"feedback_text": "x", "selected_options": '{"a": 1}'}
        )
        assert response.status_code == 400
        assert response.get_json() == {
            "success": False,
            "error": "selected_options 必须是 JSON 数组",
        }
        assert stored(task).result is None

    def test_a_second_answer_is_still_the_409_of_r851(
        self, client: FlaskClient, task: str
    ) -> None:
        assert post(client, task, data={"feedback_text": "first"}).status_code == 200
        second = post(client, task, data={"feedback_text": "second"})
        assert second.status_code == 409
        assert second.get_json()["error"] == "task_already_answered"
        assert stored(task).result == {"user_input": "first", "selected_options": []}


def legacy_post(client: FlaskClient, **kwargs: Any) -> Any:
    return client.post(
        "/api/submit",
        environ_base=LOOPBACK,
        headers={"Accept-Language": "en"},
        **kwargs,
    )


def completed_tasks() -> list[str]:
    return [
        found.task_id
        for found in get_task_queue().get_all_tasks()
        if found.status == "completed"
    ]


class TestTheLegacyRouteAgrees:
    """``POST /api/submit`` refuses what the task route refuses (R829, and R912 for forms)."""

    @pytest.mark.parametrize("name", ALSO_REFUSED_BY_THE_LEGACY_ROUTE)
    def test_neither_route_answers_with_a_body_that_holds_no_answer(
        self, client: FlaskClient, task: str, name: str
    ) -> None:
        kwargs = NO_ANSWER[name]
        legacy = legacy_post(client, **kwargs)
        assert legacy.status_code == 400, legacy.get_data(as_text=True)[:200]
        assert completed_tasks() == []
        scoped = post(client, task, **kwargs)
        assert scoped.status_code == 400
        assert stored(task).result is None

    @pytest.mark.parametrize("name", FORMS_WITHOUT_AN_ANSWER)
    def test_a_form_without_an_answer_gets_the_same_envelope_from_both(
        self, client: FlaskClient, task: str, name: str
    ) -> None:
        kwargs = NO_ANSWER[name]
        expected = {
            "success": False,
            "status": "error",
            "error": CODE,
            "message": msg(KEY, lang="en"),
        }
        assert legacy_post(client, **kwargs).get_json() == expected
        assert post(client, task, **kwargs).get_json() == expected

    @pytest.mark.parametrize(
        "name", ["urlencoded, other fields only", "multipart, other fields only"]
    )
    def test_a_form_that_names_the_task_does_not_answer_it_either(
        self, client: FlaskClient, task: str, name: str
    ) -> None:
        fields = {**NO_ANSWER[name]["data"], "task_id": task}
        legacy = legacy_post(
            client, data=fields, content_type=NO_ANSWER[name]["content_type"]
        )
        assert legacy.status_code == 400
        assert stored(task).result is None
        assert stored(task).status != "completed"

    @pytest.mark.parametrize("content_type", [URLENCODED, MULTIPART])
    @pytest.mark.parametrize(
        ("fields", "result"),
        [
            pytest.param(
                {"feedback_text": "hello"},
                {"user_input": "hello", "selected_options": []},
                id="text only",
            ),
            pytest.param(
                {"selected_options": '["a"]'},
                {"user_input": "", "selected_options": ["a"]},
                id="options only",
            ),
            pytest.param(
                {"feedback_text": "", "selected_options": "[]"},
                {"user_input": "", "selected_options": []},
                id="both, empty",
            ),
        ],
    )
    def test_a_form_that_holds_an_answer_still_answers_the_task_it_names(
        self,
        client: FlaskClient,
        task: str,
        content_type: str,
        fields: dict[str, str],
        result: dict[str, Any],
    ) -> None:
        response = legacy_post(
            client, data={**fields, "task_id": task}, content_type=content_type
        )
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        answer = stored(task).result
        assert answer is not None
        assert {key: answer[key] for key in result} == result

    def test_a_body_that_is_only_a_picture_answers_the_task_it_names(
        self, client: FlaskClient, task: str
    ) -> None:
        response = legacy_post(
            client,
            data={"task_id": task, "image_0": (io.BytesIO(PNG), "shot.png")},
            content_type=MULTIPART,
        )
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        assert stored(task).status == "completed"

    def test_a_json_object_is_still_an_answer_here_and_only_here(
        self, client: FlaskClient, task: str
    ) -> None:
        # R829: the legacy route reads a JSON object, an empty one included; the task route
        # declares a form and refuses it (the first test class).
        response = legacy_post(
            client, json={"task_id": task, "feedback_text": "from a script"}
        )
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        answer = stored(task).result
        assert answer is not None
        assert answer["user_input"] == "from a script"
        again = legacy_post(client, json={"task_id": "r912-not-there"})
        assert again.status_code == 404


class TestTheMessage:
    def test_it_exists_in_every_language_and_says_what_a_request_needs(self) -> None:
        texts = {language: msg(KEY, lang=language) for language in LANGUAGES}
        assert len(set(texts.values())) == len(LANGUAGES)
        for language, text in texts.items():
            assert text != KEY, language
            assert "feedback_text" in text, language
            assert "selected_options" in text, language
            assert "multipart/form-data" in text, language

    @pytest.mark.parametrize("language", LANGUAGES)
    def test_the_route_answers_in_the_language_that_was_asked_for(
        self, client: FlaskClient, task: str, language: str
    ) -> None:
        response = client.post(
            f"/api/tasks/{task}/submit",
            environ_base=LOOPBACK,
            headers={"Accept-Language": language},
        )
        assert response.status_code == 400
        assert response.get_json()["message"] == msg(KEY, lang=language)


def _route_function(name: str, source: Path = TASK_ROUTES) -> ast.FunctionDef:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise LookupError(name)


class TestTheOpenApiTextSaysSo:
    def _responses(self) -> dict[int, dict[str, Any]]:
        doc = ast.get_docstring(_route_function("submit_task_feedback"), clean=True)
        assert doc is not None
        spec = yaml.safe_load(doc.split("---", 1)[1])
        return {int(code): body for code, body in spec["responses"].items()}

    def test_the_400_names_the_new_answer(self) -> None:
        answer = self._responses()[400]
        assert CODE in answer["description"]
        properties = answer["schema"]["properties"]
        assert {"success", "status", "error", "message"} <= set(properties)

    def test_the_route_still_says_it_takes_a_form(self) -> None:
        doc = ast.get_docstring(_route_function("submit_task_feedback"), clean=True)
        assert doc is not None
        spec = yaml.safe_load(doc.split("---", 1)[1])
        assert spec["consumes"] == ["multipart/form-data"]

    def _legacy_spec(self) -> dict[str, Any]:
        doc = ast.get_docstring(
            _route_function("submit_feedback", FEEDBACK_ROUTES), clean=True
        )
        assert doc is not None
        return yaml.safe_load(doc.split("---", 1)[1])

    def test_the_legacy_400_names_the_form_without_an_answer(self) -> None:
        answer = self._legacy_spec()["responses"][400]
        for field in ("feedback_text", "selected_options"):
            assert field in answer["description"], field
        properties = answer["schema"]["properties"]
        assert {"success", "status", "error", "message"} <= set(properties)
        assert "表单" in properties["error"]["description"]
        assert set(properties["error"]["enum"]) == {
            "invalid_json",
            CODE,
            "invalid_value",
        }

    def test_the_legacy_route_still_says_it_takes_json_as_well(self) -> None:
        assert self._legacy_spec()["consumes"] == [
            "multipart/form-data",
            "application/json",
        ]


Line = tuple[int, str]
SECRET = "R912-PRIVATE hunter2 密码😀"


class TestTheRefusalIsLoggedWithoutTheText:
    @pytest.fixture
    def lines(self, monkeypatch: pytest.MonkeyPatch) -> list[Line]:
        """Every log call, as ``(level, text)``, before the logger's level filter."""
        seen: list[Line] = []

        def record(
            self: EnhancedLogger, level: int, message: str, *args: Any, **_kwargs: Any
        ) -> None:
            seen.append((level, EnhancedLogger._render(message, args)))

        monkeypatch.setattr(EnhancedLogger, "log", record)
        return seen

    @staticmethod
    def _refusals(lines: list[Line]) -> list[str]:
        return [
            text
            for level, text in lines
            if level == logging.WARNING and "没有答案" in text
        ]

    def test_the_task_route_warns_once_and_names_the_task_and_the_kind_of_request(
        self, client: FlaskClient, task: str, lines: list[Line]
    ) -> None:
        post(client, task, json={"feedback_text": SECRET})
        (refusal,) = self._refusals(lines)
        assert task in refusal
        assert "application/json" in refusal
        assert "content_length=" in refusal

    def test_the_legacy_route_warns_once_without_a_task(
        self, client: FlaskClient, lines: list[Line]
    ) -> None:
        legacy_post(client, data={"user_input": SECRET}, content_type=URLENCODED)
        (refusal,) = self._refusals(lines)
        assert "x-www-form-urlencoded" in refusal
        assert "任务 " not in refusal

    @pytest.mark.parametrize("route", ["task", "legacy"])
    def test_no_text_of_the_request_gets_into_the_log(
        self, client: FlaskClient, task: str, lines: list[Line], route: str
    ) -> None:
        kwargs = {"data": {"user_input": SECRET}, "content_type": URLENCODED}
        if route == "task":
            post(client, task, **kwargs)
        else:
            legacy_post(client, **kwargs)
        assert self._refusals(lines)
        for level, text in lines:
            for marker in ("R912-PRIVATE", "hunter2", "密码"):
                assert marker not in text, f"{logging.getLevelName(level)}: {text}"

    def test_a_long_content_type_is_cut_where_the_log_line_keeps_it_short(
        self, client: FlaskClient, task: str, lines: list[Line]
    ) -> None:
        post(
            client,
            task,
            input_stream=io.BytesIO(b""),
            content_type=MULTIPART + "; boundary=" + "b" * 300,
        )
        (refusal,) = self._refusals(lines)
        assert "b" * 40 in refusal
        assert "b" * 100 not in refusal
