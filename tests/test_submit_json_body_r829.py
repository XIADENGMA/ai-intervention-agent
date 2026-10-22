"""R829: ``POST /api/submit`` with a body it cannot read is a 400, not an empty answer.

``/api/submit`` has three kinds of body.  The page and the VS Code panel send a form (with
or without files); a script may send a JSON object.  The JSON branch read the body inside a
``try`` whose ``except Exception`` filled in "no text, nothing selected, no images" and went
on, so

* a body that is not readable at all (empty, ``text/plain``, a syntax error, a JSON string
  / number / array / ``null``, nested deeper than 32 levels) **completed the task that was
  waiting for the user with an empty answer** and answered ``200``: one broken script, and
  the question the user was about to answer ended, and the AI went on with "the user said
  nothing";
* a text field that is JSON ``null`` became the Python word ``"None"``: the answer was
  literally ``None``, and ``{"task_id": null}`` looked for a task called ``None`` and was a
  ``404``;
* a text field that was a number, a list or an object became ``str()`` of it (``"5"``,
  ``"['a']"``).

The route's own OpenAPI already said ``400`` for "JSON cannot be parsed" (R358), and its
neighbours (``/api/update``, ``/api/update-language``, ``/api/update-notification-config``)
have answered ``400 invalid_json`` / ``invalid_body`` / ``invalid_value`` since R789 / R790.
The same helpers are used here (``require_json_object``, ``fields_that_are_not_text``,
``invalid_value_response`` in ``web_ui_routes/_request_body.py``).  The doc also said
"``task_id`` does not exist -> 400" while the code answers ``404``; the doc was wrong.

What does not change: a JSON **object** (an empty one included: it completes the active task
with an empty answer, which is what the R348 performance baseline posts), ``null`` meaning
"not given", the form and multipart branches, ``404`` for a task id that is not there.
"""

from __future__ import annotations

import ast
import inspect
import io
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from flask.testing import FlaskClient

from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import _request_body
from ai_intervention_agent.web_ui_routes._request_body import MAX_JSON_NESTING

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"
ROUTES = PACKAGE / "web_ui_routes"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
TASK = "r829-task"
OTHER = "r829-other"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JSON = "application/json"


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r829", task_id="r829-initial", auto_resubmit_timeout=0, port=19829
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    """A queue that holds exactly two open tasks; ``TASK`` is the active one."""
    queue = get_task_queue()
    queue.clear_all_tasks()
    queue.add_task(
        task_id=TASK, prompt="p", predefined_options=["x"], auto_resubmit_timeout=300
    )
    queue.add_task(
        task_id=OTHER, prompt="q", predefined_options=["y"], auto_resubmit_timeout=300
    )
    ui.feedback_result = None
    try:
        yield ui.app.test_client()
    finally:
        queue.clear_all_tasks()


def _status(task_id: str) -> str:
    task = get_task_queue().get_task(task_id)
    assert task is not None
    return str(task.status)


def _result(task_id: str) -> dict[str, Any]:
    task = get_task_queue().get_task(task_id)
    assert task is not None and task.result is not None, f"{task_id} was not completed"
    return dict(task.result)


def _post_json(client: FlaskClient, body: Any) -> Any:
    return client.post("/api/submit", json=body, environ_base=LOOPBACK)


def _post_raw(client: FlaskClient, data: str | bytes, content_type: str = JSON) -> Any:
    return client.post(
        "/api/submit", data=data, content_type=content_type, environ_base=LOOPBACK
    )


def _deep_array(levels: int) -> str:
    return "[" * levels + "]" * levels


def _deep_object(levels: int) -> str:
    return '{"a":' * levels + "1" + "}" * levels


# (name, post it, the ``error`` code the answer carries)
UNREADABLE: list[tuple[str, Any, str]] = [
    (
        "no body at all",
        lambda c: c.post("/api/submit", environ_base=LOOPBACK),
        "invalid_json",
    ),
    ("an empty JSON body", lambda c: _post_raw(c, b""), "invalid_json"),
    ("a syntax error", lambda c: _post_raw(c, '{"feedback_text": '), "invalid_json"),
    (
        "not JSON at all",
        lambda c: _post_raw(c, "not valid json at all"),
        "invalid_json",
    ),
    (
        "JSON without the JSON content type",
        lambda c: _post_raw(c, '{"feedback_text": "x"}', "text/plain"),
        "invalid_json",
    ),
    (
        "an array nested deeper than the limit",
        lambda c: _post_raw(c, _deep_array(MAX_JSON_NESTING + 1)),
        "invalid_json",
    ),
    (
        "an object nested deeper than the limit",
        lambda c: _post_raw(c, _deep_object(MAX_JSON_NESTING + 1)),
        "invalid_json",
    ),
    ("a JSON string", lambda c: _post_raw(c, '"x"'), "invalid_body"),
    ("a JSON number", lambda c: _post_raw(c, "5"), "invalid_body"),
    ("a JSON array", lambda c: _post_raw(c, '["x"]'), "invalid_body"),
    ("JSON null", lambda c: _post_raw(c, "null"), "invalid_body"),
]
UNREADABLE_IDS = [name for name, _, _ in UNREADABLE]


class TestABodyThatCannotBeReadEndsNothing:
    @pytest.mark.parametrize(("name", "post", "error"), UNREADABLE, ids=UNREADABLE_IDS)
    def test_is_a_400_with_the_envelope_of_its_neighbours(
        self, client: FlaskClient, name: str, post: Any, error: str
    ) -> None:
        response = post(client)
        assert response.status_code == 400, response.get_data(as_text=True)[:200]
        assert response.mimetype == "application/json"
        body = response.get_json()
        assert body["status"] == "error"
        assert body["error"] == error
        assert isinstance(body["message"], str) and body["message"]

    @pytest.mark.parametrize(("name", "post", "error"), UNREADABLE, ids=UNREADABLE_IDS)
    def test_the_waiting_task_is_still_open(
        self, ui: WebFeedbackUI, client: FlaskClient, name: str, post: Any, error: str
    ) -> None:
        post(client)
        assert _status(TASK) != "completed"
        assert _status(OTHER) != "completed"
        assert ui.feedback_result is None, "a refused body must not leave a result"


# a value of each kind that is not text, for every field read as text
NOT_TEXT = {
    "an integer": 5,
    "a float": 1.5,
    "a boolean": True,
    "a list": ["a"],
    "an object": {"a": 1},
}
TEXT_FIELDS = ["task_id", "feedback_text", "user_input"]


class TestATextFieldThatIsNotText:
    @pytest.mark.parametrize("kind", list(NOT_TEXT))
    @pytest.mark.parametrize("field", TEXT_FIELDS)
    def test_is_a_400_invalid_value_naming_the_field(
        self, client: FlaskClient, field: str, kind: str
    ) -> None:
        body = {"feedback_text": "t", field: NOT_TEXT[kind]}
        response = _post_json(client, body)
        assert response.status_code == 400, response.get_data(as_text=True)[:200]
        body = response.get_json()
        assert body["status"] == "error"
        assert body["error"] == "invalid_value"
        assert body["fields"] == [field]
        assert field in body["message"]

    @pytest.mark.parametrize("field", TEXT_FIELDS)
    def test_nothing_is_completed(
        self, ui: WebFeedbackUI, client: FlaskClient, field: str
    ) -> None:
        _post_json(client, {field: ["a"]})
        assert _status(TASK) != "completed"
        assert ui.feedback_result is None

    def test_every_field_that_is_wrong_is_named_once_in_order(
        self, client: FlaskClient
    ) -> None:
        response = _post_json(
            client, {"user_input": 1, "task_id": [], "feedback_text": {"a": 1}}
        )
        assert response.status_code == 400
        assert response.get_json()["fields"] == [
            "feedback_text",
            "task_id",
            "user_input",
        ]

    def test_the_answer_does_not_echo_the_value(self, client: FlaskClient) -> None:
        response = _post_json(client, {"feedback_text": ["pa55word-the-user-typed"]})
        assert response.status_code == 400
        assert "pa55word" not in response.get_data(as_text=True)


class TestNullMeansNotGiven:
    def test_a_null_text_is_an_empty_answer_not_the_word_none(
        self, client: FlaskClient
    ) -> None:
        response = _post_json(client, {"task_id": OTHER, "feedback_text": None})
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        assert _result(OTHER)["user_input"] == ""

    def test_a_null_task_id_means_the_active_task_not_a_task_called_none(
        self, client: FlaskClient
    ) -> None:
        response = _post_json(client, {"task_id": None, "feedback_text": "hi"})
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        assert _result(TASK)["user_input"] == "hi"
        assert _status(OTHER) != "completed"

    def test_a_null_feedback_text_lets_the_old_name_through(
        self, client: FlaskClient
    ) -> None:
        response = _post_json(
            client, {"task_id": OTHER, "feedback_text": None, "user_input": "legacy"}
        )
        assert response.status_code == 200
        assert _result(OTHER)["user_input"] == "legacy"

    def test_every_field_null_is_an_empty_answer_for_the_active_task(
        self, client: FlaskClient
    ) -> None:
        response = _post_json(
            client,
            {
                "task_id": None,
                "feedback_text": None,
                "user_input": None,
                "selected_options": None,
                "images": None,
            },
        )
        assert response.status_code == 200
        result = _result(TASK)
        assert result["user_input"] == ""
        assert result["selected_options"] == []
        assert result["images"] == []


class TestWhatDoesNotChange:
    def test_a_complete_object_is_delivered_as_before(
        self, client: FlaskClient
    ) -> None:
        response = _post_json(
            client,
            {
                "task_id": f"  {OTHER}  ",
                "feedback_text": "  looks good  ",
                "selected_options": ["y", " y ", "", "z"],
                "images": [{"data": "AAAA", "mime_type": "image/png"}],
            },
        )
        assert response.status_code == 200
        assert response.get_json()["status"] == "success"
        result = _result(OTHER)
        assert result["user_input"] == "looks good"
        assert result["selected_options"] == ["y", "z"]
        assert result["images"] == [{"data": "AAAA", "mime_type": "image/png"}]
        assert _status(TASK) != "completed"

    def test_an_empty_object_completes_the_active_task_with_an_empty_answer(
        self, client: FlaskClient
    ) -> None:
        response = _post_json(client, {})
        assert response.status_code == 200
        assert _result(TASK)["user_input"] == ""

    def test_the_old_name_for_the_text_still_works_and_loses_to_the_new_one(
        self, client: FlaskClient
    ) -> None:
        assert (
            _post_json(client, {"task_id": TASK, "user_input": "old name"}).status_code
            == 200
        )
        assert _result(TASK)["user_input"] == "old name"
        # a feedback_text that is given, even an empty one, wins over the old name
        both = {"task_id": OTHER, "user_input": "old", "feedback_text": ""}
        assert _post_json(client, both).status_code == 200
        assert _result(OTHER)["user_input"] == ""

    def test_a_number_for_selected_options_is_still_nothing_selected(
        self, client: FlaskClient
    ) -> None:
        # selected_options and images are lenient on purpose (R799): not text fields.
        response = _post_json(client, {"selected_options": 5, "images": "nope"})
        assert response.status_code == 200
        result = _result(TASK)
        assert result["selected_options"] == []
        assert result["images"] == []

    def test_an_unknown_task_id_is_still_404(self, client: FlaskClient) -> None:
        response = _post_json(client, {"task_id": "nope", "feedback_text": "x"})
        assert response.status_code == 404
        assert response.get_json()["success"] is False
        assert _status(TASK) != "completed"

    def test_a_form_is_still_a_form(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        response = client.post(
            "/api/submit",
            data={
                "task_id": OTHER,
                "feedback_text": "from a form",
                "selected_options": '["y"]',
            },
            environ_base=LOOPBACK,
        )
        assert response.status_code == 200
        assert _result(OTHER)["user_input"] == "from a form"
        assert _result(OTHER)["selected_options"] == ["y"]

    def test_a_multipart_form_with_a_file_is_still_a_form(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            "/api/submit",
            data={
                "task_id": OTHER,
                "feedback_text": "with a picture",
                "image_0": (io.BytesIO(PNG), "a.png", "image/png"),
            },
            content_type="multipart/form-data",
            environ_base=LOOPBACK,
        )
        assert response.status_code == 200
        assert _result(OTHER)["user_input"] == "with a picture"

    def test_a_form_whose_text_is_json_looking_is_not_parsed_as_json(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            "/api/submit",
            data={"task_id": OTHER, "feedback_text": '{"a": [1, 2]}'},
            environ_base=LOOPBACK,
        )
        assert response.status_code == 200
        assert _result(OTHER)["user_input"] == '{"a": [1, 2]}'

    def test_an_object_exactly_at_the_depth_limit_is_read(
        self, client: FlaskClient
    ) -> None:
        # the object is one level, the array in it the other MAX_JSON_NESTING - 1
        body = (
            '{"feedback_text": "deep", "extra": '
            + _deep_array(MAX_JSON_NESTING - 1)
            + "}"
        )
        response = _post_raw(client, body)
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        assert _result(TASK)["user_input"] == "deep"


def _submit_spec(ui: WebFeedbackUI) -> dict[Any, Any]:
    doc = inspect.getdoc(inspect.unwrap(ui.app.view_functions["submit_feedback"]))
    assert doc and "---" in doc
    return yaml.safe_load(doc.split("---", 1)[1])["responses"]


class TestTheDocumentationAgreesWithTheCode:
    def test_400_lists_the_three_codes_and_the_fields(self, ui: WebFeedbackUI) -> None:
        props = _submit_spec(ui)[400]["schema"]["properties"]
        assert props["error"]["enum"] == [
            "invalid_json",
            "invalid_body",
            "invalid_value",
        ]
        assert props["fields"]["type"] == "array"
        assert {"status", "error", "fields", "message"} <= set(props)

    def test_400_no_longer_claims_to_be_the_answer_for_an_unknown_task(
        self, ui: WebFeedbackUI
    ) -> None:
        assert "task_id 不存在" not in str(_submit_spec(ui)[400])

    def test_404_is_documented_with_the_envelope_that_is_sent(
        self, ui: WebFeedbackUI
    ) -> None:
        responses = _submit_spec(ui)
        assert 404 in responses
        assert {"success", "error"} <= set(responses[404]["schema"]["properties"])

    def test_the_depth_in_the_text_is_the_constant(self, ui: WebFeedbackUI) -> None:
        text = str(_submit_spec(ui)[400])
        assert f"嵌套超过 {MAX_JSON_NESTING} 层" in text


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


class TestTheShapeOfTheCode:
    def test_the_body_is_read_outside_any_try(self) -> None:
        """A ``require_json_object()`` inside the route's own ``try`` is swallowed into 200 again."""
        tree = ast.parse((ROUTES / "feedback.py").read_text(encoding="utf-8"))
        route = _function(tree, "submit_feedback")
        calls = [
            n
            for n in ast.walk(route)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "require_json_object"
        ]
        assert len(calls) == 1, "submit_feedback must read its JSON body exactly once"
        for node in ast.walk(route):
            if isinstance(node, ast.Try):
                inside = {id(n) for part in node.body for n in ast.walk(part)}
                assert id(calls[0]) not in inside

    def test_the_route_does_not_read_the_body_twice(self) -> None:
        tree = ast.parse((ROUTES / "feedback.py").read_text(encoding="utf-8"))
        route = _function(tree, "submit_feedback")
        direct = [
            n
            for n in ast.walk(route)
            if isinstance(n, ast.Attribute) and n.attr == "get_json"
        ]
        assert not direct, (
            "submit_feedback reads the body through require_json_object() only"
        )

    def test_the_two_helpers_live_in_one_place(self) -> None:
        assert callable(_request_body.fields_that_are_not_text)
        assert callable(_request_body.invalid_value_response)
        for path in ROUTES.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert (
                not re.search(r"def _?invalid_value_response\b", text)
                or path.name == "_request_body.py"
            )
            assert (
                not re.search(r"def _?fields_that_are_not_text\b", text)
                or path.name == "_request_body.py"
            )
