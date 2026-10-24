"""R868: the OpenAPI text of a success answer says what the route really answers.

R860 read the error answers of the route docstrings against the code.  The success answers had
never been read against the running routes.  Asking every route what it answers, in three states
of the queue (no task, a task with options next to a task without, an answered task), and
checking each answer against the schema its own docstring declares for that status, found:

* eight properties that are ``null`` in some state but were declared plain ``string`` /
  ``array`` / ``object`` / ``number`` (a client generated from the description, or a validator
  run against it, rejects the answer):

  - ``GET /api/config``: ``task_id`` (``null`` when there is no task to show) and
    ``predefined_options`` (``null`` for an active task that has no options; ``[]`` when there is
    no task);
  - ``GET /api/feedback``: ``feedback`` (``null`` until a feedback arrived);
  - ``GET /api/system/sse-stats``: ``latency_ms.p50_ms`` and ``latency_ms.p95_ms`` (``null``
    while ``count`` is ``0``; the description said so, the schema did not);
  - ``GET /api/tasks/<id>``: ``task.predefined_options`` and ``task.predefined_options_defaults``
    (``null`` for a task created without options or defaults) and ``task.result`` (the
    description said "an empty object" for a task that is not answered yet; it is ``null``);

* ``POST /api/update-language`` had no OpenAPI text at all, so Swagger UI and the generated
  API description left out an ``/api/`` route that the Web UI's own language menu calls.

The docstrings write ``nullable: true`` (OpenAPI 3's word, which ``/api/loops``, ``/api/tasks`` and
``/api/system/api-token-info`` already used); JSON Schema draft 4, which Swagger 2 is built on,
has no such keyword, so the checker below turns it into ``type: [<type>, "null"]`` before it
validates.

What the tests pin:

* every ``/api/`` rule of the Web UI has a docstring with a ``responses`` section;
* the sweep: every route that does not act on the machine (``LEFT_OUT``: stopping the server,
  opening an editor, sending notifications, the event stream, the process-wide log level) is
  called with a request built from its own ``parameters`` (a path id, the required fields of the
  body, the form fields) in the three states, the status of each answer is one the route
  declares, and a JSON answer conforms to the schema declared for that status; the sweep is held
  to reach the routes this is about, and each URL it builds is held to reach the route it means
  (an id that does not fit would be answered by the router's own 404), so a sweep that stops
  short fails instead of passing;
* the eight properties are ``nullable: true`` and their descriptions say when they are ``null``
  (``result`` is no longer "an empty object");
* the nulls are real: each of them is ``null`` in the state the description names, so a
  ``nullable: true`` cannot linger after the answer stopped being null;
* the 400 answers of ``POST /api/update-language`` (unsupported language, a body that is not
  JSON, a body that is not an object) conform to what the new text declares;
* the checker's own cases, so it cannot go quiet.
"""

from __future__ import annotations

import copy
import inspect
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import jsonschema
import pytest
import yaml
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.routing import Rule

from ai_intervention_agent.i18n import SUPPORTED_LANGS
from ai_intervention_agent.server_config import WebUIConfig
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "ai_intervention_agent"
DOCS = ROOT / "docs"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
# The routes the sweep does not call: they act on the machine or the process.
LEFT_OUT = {
    ("/api/close", "POST"),  # stops the server
    ("/api/events", "GET"),  # a stream that does not end
    ("/api/system/open-config-file", "POST"),  # opens an editor
    ("/api/system/notifications/test", "POST"),  # sends a notification
    ("/api/notify-new-tasks", "POST"),  # sends a notification
    ("/api/test-bark", "POST"),  # a request to a push server
    ("/api/system/log-level", "POST"),  # the log level of the whole process
}
# What the sweep has to reach (a sweep that visits too little would pass by looking at nothing).
MUST_VISIT_GET = {
    "/api/config",
    "/api/feedback",
    "/api/tasks",
    "/api/tasks/{task_id}",
    "/api/system/sse-stats",
    "/api/system/api-token-info",
    "/api/capabilities",
    "/api/time",
}
MUST_VISIT_POST = {
    "/api/update-language",
    "/api/update-feedback-config",
    "/api/tasks",
    "/api/tasks/{task_id}/submit",
}


@pytest.fixture
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(prompt="", auto_resubmit_timeout=0, port=19868)
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    queue = get_task_queue()
    queue.clear_all_tasks()
    try:
        yield ui.app.test_client()
    finally:
        queue.clear_all_tasks()


# --------------------------------------------------------------------------- the checker


def openapi_path(rule: str) -> str:
    return re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule)


def operations(app: Flask) -> dict[tuple[str, str], dict[str, Any]]:
    """``{(path, METHOD): the YAML after the ``---`` of the view's docstring}`` for every ``/api/``
    rule; ``{}`` for a view whose docstring has no such section."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        doc = inspect.getdoc(app.view_functions[rule.endpoint]) or ""
        spec = (yaml.safe_load(doc.split("---", 1)[1]) or {}) if "---" in doc else {}
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            found[(openapi_path(rule.rule), method)] = spec
    return found


def with_null(node: Any) -> Any:
    """``nullable: true`` (the docstrings' word) or ``x-nullable: true`` admits ``null``."""
    if isinstance(node, dict):
        out = {key: with_null(value) for key, value in node.items()}
        if (
            out.get("nullable") is True or out.get("x-nullable") is True
        ) and isinstance(out.get("type"), str):
            out["type"] = [out["type"], "null"]
        return out
    if isinstance(node, list):
        return [with_null(item) for item in node]
    return node


def schema_errors(schema: dict[str, Any], body: Any) -> list[str]:
    validator = jsonschema.Draft4Validator(with_null(copy.deepcopy(schema)))
    return sorted(
        f"{'/'.join('*' if isinstance(p, int) else str(p) for p in e.absolute_path) or '<body>'}: "
        f"{e.message}"
        for e in validator.iter_errors(body)
    )


def sample(schema: Any) -> Any:
    """A value for ``schema``: its ``example``, ``default``, first ``enum`` value, or a plain one of its type."""
    if not isinstance(schema, dict):
        return "x"
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        required = schema.get("required", [])
        return {
            name: sample(value)
            for name, value in schema.get("properties", {}).items()
            if name in required
        }
    if kind == "array":
        return []
    if kind == "integer":
        return schema.get("minimum", 1)
    if kind == "number":
        return schema.get("minimum", 1.0)
    if kind == "boolean":
        return True
    return "x"


def request_for(operation: dict[str, Any]) -> dict[str, Any]:
    """The keyword arguments of the test client call that the operation's ``parameters`` ask for."""
    kwargs: dict[str, Any] = {}
    parameters = operation.get("parameters") or []
    for parameter in parameters:
        if parameter.get("in") == "body":
            kwargs["json"] = sample(parameter.get("schema", {}))
    form = {
        p["name"]: str(sample(p))
        for p in parameters
        if p.get("in") == "formData"
        and (p.get("required") or p["name"] == "feedback_text")
    }
    if form:
        kwargs["data"] = form
    query = {
        p["name"]: sample(p)
        for p in parameters
        if p.get("in") == "query" and p.get("required")
    }
    if query:
        kwargs["query_string"] = query
    return kwargs


def fill_path(path: str, task_id: str) -> str:
    return path.replace("{task_id}", task_id).replace("{index}", "0")


def judge(
    label: str, operation: dict[str, Any], status: int, content_type: str, body: Any
) -> list[str]:
    """Problems with one answer: a status the route does not declare, or a JSON body that does
    not conform to the schema declared for that status."""
    declared = {
        int(code): value for code, value in (operation.get("responses") or {}).items()
    }
    if status not in declared:
        return [f"{label}: answered {status}, declares {sorted(declared)}"]
    schema = (declared[status] or {}).get("schema")
    if not schema or "json" not in content_type:
        return []
    return [f"{label} ({status}): {error}" for error in schema_errors(schema, body)]


class Sweep:
    """Calls the routes and keeps what it visited and what was wrong."""

    def __init__(self, client: FlaskClient, ops: dict[tuple[str, str], dict[str, Any]]):
        self.client = client
        self.ops = ops
        self.visited: set[tuple[str, str]] = set()
        self.problems: list[str] = []
        self.counter = 0

    def fresh_task(self) -> str:
        self.counter += 1
        task_id = f"r868-sweep-{self.counter}"
        assert get_task_queue().add_task(
            task_id=task_id,
            prompt="a prompt",
            predefined_options=["a", "b"],
            auto_resubmit_timeout=240,
        )
        return task_id

    def call(self, path: str, method: str, task_ids: list[str]) -> None:
        operation = self.ops[(path, method)]
        for task_id in task_ids:
            kwargs = request_for(operation)
            url = fill_path(path, task_id)
            rule, _ = self.client.application.url_map.bind("localhost").match(
                url, method=method, return_rule=True
            )
            assert isinstance(rule, Rule)
            assert openapi_path(rule.rule) == path, (
                f"{method} {url} reaches {rule.rule}"
            )
            response = getattr(self.client, method.lower())(
                url, environ_base=LOOPBACK, **kwargs
            )
            body = response.get_json(silent=True)
            self.problems.extend(
                judge(
                    f"{method} {path}",
                    operation,
                    response.status_code,
                    response.content_type or "",
                    body,
                )
            )
        self.visited.add((path, method))

    def gets(self, task_ids: list[str]) -> None:
        for path, method in sorted(self.ops):
            if method != "GET" or (path, method) in LEFT_OUT:
                continue
            self.call(path, method, task_ids if "{task_id}" in path else [""])

    def posts(self) -> None:
        for path, method in sorted(self.ops):
            if method != "POST" or (path, method) in LEFT_OUT:
                continue
            if "{task_id}" in path:
                self.call(path, method, [self.fresh_task()])
            else:
                self.call(path, method, [""])


@pytest.fixture
def ops(ui: WebFeedbackUI) -> dict[tuple[str, str], dict[str, Any]]:
    return operations(ui.app)


# --------------------------------------------------------------------------- the routes


class TestEveryRouteIsDescribed:
    def test_each_api_rule_has_a_responses_section(self, ops: dict[Any, Any]) -> None:
        missing = [
            f"{m} {p}"
            for (p, m), spec in sorted(ops.items())
            if not spec.get("responses")
        ]
        assert missing == []

    def test_the_operations_are_not_an_empty_list(self, ops: dict[Any, Any]) -> None:
        assert len(ops) >= 40

    def test_left_out_routes_exist(self, ops: dict[Any, Any]) -> None:
        assert set(ops) >= LEFT_OUT


class TestTheAnswersConformToTheText:
    def test_with_no_task(self, client: FlaskClient, ops: dict[Any, Any]) -> None:
        sweep = Sweep(client, ops)
        sweep.gets(["r868-missing"])
        assert sweep.problems == []
        assert {p for p, m in sweep.visited if m == "GET"} >= MUST_VISIT_GET - {
            "/api/tasks/{task_id}"
        }

    def test_with_a_task_that_has_options_and_one_that_has_none(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        queue = get_task_queue()
        assert queue.add_task(
            task_id="r868-with",
            prompt="with options",
            predefined_options=["a", "b"],
            predefined_options_defaults=[True, False],
            auto_resubmit_timeout=240,
        )
        assert queue.add_task(
            task_id="r868-bare", prompt="bare", auto_resubmit_timeout=240
        )
        sweep = Sweep(client, ops)
        sweep.gets(["r868-with", "r868-bare"])
        assert sweep.problems == []
        assert {p for p, m in sweep.visited if m == "GET"} >= MUST_VISIT_GET

    def test_with_an_answered_task(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        queue = get_task_queue()
        assert queue.add_task(
            task_id="r868-done", prompt="done", auto_resubmit_timeout=240
        )
        assert queue.add_task(
            task_id="r868-waiting", prompt="waiting", auto_resubmit_timeout=240
        )
        answered = client.post(
            "/api/tasks/r868-done/submit",
            data={"feedback_text": "ok", "selected_options": json.dumps(["a"])},
            environ_base=LOOPBACK,
        )
        assert answered.status_code == 200
        sweep = Sweep(client, ops)
        sweep.gets(["r868-done", "r868-waiting"])
        assert sweep.problems == []
        assert {p for p, m in sweep.visited if m == "GET"} >= MUST_VISIT_GET

    def test_every_post_that_does_not_act_on_the_machine(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        sweep = Sweep(client, ops)
        sweep.posts()
        assert sweep.problems == []
        assert {p for p, m in sweep.visited if m == "POST"} >= MUST_VISIT_POST


# The properties R868 made ``nullable: true``: (method, path, status, the property's path).
MADE_NULLABLE = [
    ("GET", "/api/config", 200, ("predefined_options",)),
    ("GET", "/api/config", 200, ("task_id",)),
    ("GET", "/api/feedback", 200, ("feedback",)),
    ("GET", "/api/system/sse-stats", 200, ("latency_ms", "p50_ms")),
    ("GET", "/api/system/sse-stats", 200, ("latency_ms", "p95_ms")),
    ("GET", "/api/tasks/{task_id}", 200, ("task", "predefined_options")),
    ("GET", "/api/tasks/{task_id}", 200, ("task", "predefined_options_defaults")),
    ("GET", "/api/tasks/{task_id}", 200, ("task", "result")),
]


def property_at(operation: dict[str, Any], status: int, trail: tuple[str, ...]) -> Any:
    node = operation["responses"][status]["schema"]
    for name in trail:
        node = node["properties"][name]
    return node


class TestTheTextSaysWhenItIsNull:
    @pytest.mark.parametrize(
        ("method", "path", "status", "trail"),
        MADE_NULLABLE,
        ids=[f"{path} {'.'.join(trail)}" for _, path, _, trail in MADE_NULLABLE],
    )
    def test_the_property_is_nullable_and_its_description_says_null(
        self,
        ops: dict[Any, Any],
        method: str,
        path: str,
        status: int,
        trail: tuple[str, ...],
    ) -> None:
        node = property_at(ops[(path, method)], status, trail)
        assert node.get("nullable") is True
        assert "null" in node["description"]

    def test_an_unanswered_task_is_not_described_as_having_an_empty_object(
        self, ops: dict[Any, Any]
    ) -> None:
        node = property_at(
            ops[("/api/tasks/{task_id}", "GET")], 200, ("task", "result")
        )
        assert "空对象" not in node["description"]


class TestTheNullsAreReal:
    """Each ``nullable: true`` added here is true in the state its description names."""

    def get(self, client: FlaskClient, url: str) -> dict[str, Any]:
        response = client.get(url, environ_base=LOOPBACK)
        assert response.status_code == 200
        body = response.get_json()
        assert isinstance(body, dict)
        return body

    def test_config_without_a_task(self, client: FlaskClient) -> None:
        body = self.get(client, "/api/config")
        assert body["task_id"] is None
        assert body["predefined_options"] == []

    def test_config_of_an_active_task_without_options(
        self, client: FlaskClient
    ) -> None:
        assert get_task_queue().add_task(
            task_id="r868-bare", prompt="bare", auto_resubmit_timeout=240
        )
        body = self.get(client, "/api/config")
        assert body["task_id"] == "r868-bare"
        assert body["predefined_options"] is None

    def test_feedback_before_any_feedback(self, client: FlaskClient) -> None:
        body = self.get(client, "/api/feedback")
        assert body == {"status": "waiting", "feedback": None}

    def test_sse_latency_without_samples(self, client: FlaskClient) -> None:
        latency = self.get(client, "/api/system/sse-stats")["latency_ms"]
        assert latency["count"] == 0
        assert latency["p50_ms"] is None
        assert latency["p95_ms"] is None

    def test_a_waiting_task_has_no_result_and_may_have_no_defaults(
        self, client: FlaskClient
    ) -> None:
        assert get_task_queue().add_task(
            task_id="r868-bare", prompt="bare", auto_resubmit_timeout=240
        )
        task = self.get(client, "/api/tasks/r868-bare")["task"]
        assert task["result"] is None
        assert task["predefined_options"] is None
        assert task["predefined_options_defaults"] is None

    def test_an_answered_task_has_a_result(self, client: FlaskClient) -> None:
        assert get_task_queue().add_task(
            task_id="r868-done", prompt="done", auto_resubmit_timeout=240
        )
        sent = client.post(
            "/api/tasks/r868-done/submit",
            data={"feedback_text": "ok"},
            environ_base=LOOPBACK,
        )
        assert sent.status_code == 200
        task = self.get(client, "/api/tasks/r868-done")["task"]
        assert isinstance(task["result"], dict)
        assert task["result"]["user_input"] == "ok"


class TestTheTroubleshootingExamplesAreTrue:
    """Section 13 of the troubleshooting guides describes the output of two ``curl | jq`` lines.
    The first showed ``jq '.entries | length'`` (which works) and said it returned ``null``
    because the consumer "was reading ``.logs``" (``jq '.logs | length'`` prints ``0``, not
    ``null``); the second said a field ``status`` had been renamed, but the notification check
    has never had one, it answers with ``ok``.  The lines now show the wrong key and what it
    really prints, and the endpoints still answer that way."""

    def get(self, client: FlaskClient, url: str) -> dict[str, Any]:
        response = client.get(url, environ_base=LOOPBACK)
        assert response.status_code == 200
        body = response.get_json()
        assert isinstance(body, dict)
        return body

    def test_recent_logs_keeps_its_list_under_entries(
        self, client: FlaskClient
    ) -> None:
        body = self.get(client, "/api/system/recent-logs")
        assert isinstance(body["entries"], list)
        assert "logs" not in body

    def test_the_notification_check_answers_with_ok_and_has_no_status(
        self, client: FlaskClient
    ) -> None:
        check = self.get(client, "/api/system/health")["checks"]["notification"]
        assert check["ok"] is True
        assert "status" not in check

    @pytest.mark.parametrize(
        ("name", "logs_sentence", "check_sentence"),
        [
            (
                "troubleshooting.md",
                "list is under `.entries`",
                "answers with `ok`, not `status`",
            ),
            (
                "troubleshooting.zh-CN.md",
                "列表在 `.entries` 下面",
                "检查结果叫 `ok`，不叫 `status`",
            ),
        ],
        ids=["en", "zh-CN"],
    )
    def test_the_guides_name_those_keys(
        self, name: str, logs_sentence: str, check_sentence: str
    ) -> None:
        text = (DOCS / name).read_text(encoding="utf-8")
        assert "jq '.logs'" in text
        assert logs_sentence in text
        assert "jq '.checks.notification.status'" in text
        assert check_sentence in text


class TestUpdateLanguage:
    URL = "/api/update-language"

    def answer(
        self, client: FlaskClient, ops: dict[Any, Any], **kwargs: Any
    ) -> tuple[int, Any]:
        response = client.post(self.URL, environ_base=LOOPBACK, **kwargs)
        body = response.get_json(silent=True)
        operation = ops[(self.URL, "POST")]
        assert (
            judge(
                "POST " + self.URL,
                operation,
                response.status_code,
                response.content_type,
                body,
            )
            == []
        )
        return response.status_code, body

    def test_a_supported_language_is_saved(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        assert self.answer(client, ops, json={"language": "zh-TW"}) == (
            200,
            {"status": "success", "language": "zh-TW"},
        )

    def test_no_language_means_auto(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        assert self.answer(client, ops, json={}) == (
            200,
            {"status": "success", "language": "auto"},
        )

    def test_an_unsupported_language_is_refused(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        status, body = self.answer(client, ops, json={"language": "fr"})
        assert status == 400
        assert body["status"] == "error"
        assert "error" not in body

    def test_a_body_that_is_not_json(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        status, body = self.answer(client, ops, data="x", content_type="text/plain")
        assert (status, body["error"]) == (400, "invalid_json")

    def test_a_body_that_is_not_an_object(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        status, body = self.answer(client, ops, json=[1])
        assert (status, body["error"]) == (400, "invalid_body")

    def test_a_configuration_that_cannot_be_written_is_a_500_as_declared(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        config = MagicMock()
        config.update_section.side_effect = OSError("disk full")
        with patch("ai_intervention_agent.web_ui.get_config", return_value=config):
            status, body = self.answer(client, ops, json={"language": "en"})
        assert status == 500
        assert body["status"] == "error"
        assert isinstance(body["message"], str)

    def test_the_documented_languages_are_the_ones_the_route_takes(
        self, client: FlaskClient, ops: dict[Any, Any]
    ) -> None:
        operation = ops[(self.URL, "POST")]
        asked = operation["parameters"][0]["schema"]["properties"]["language"]["enum"]
        answered = operation["responses"][200]["schema"]["properties"]["language"][
            "enum"
        ]
        # the three places that know the languages: the config model, the translations the
        # server ships, and the files the page loads
        assert asked == answered == list(WebUIConfig.SUPPORTED_LANGS)
        assert set(asked) - {"auto"} == set(SUPPORTED_LANGS)
        shipped = {
            path.stem for path in (PACKAGE / "static" / "locales").glob("*.json")
        }
        assert shipped == set(SUPPORTED_LANGS)
        # and the route takes exactly those
        pool = [*asked, "fr", "ja", "zh", "zh-cn", "EN", "", "auto2"]
        accepted = {
            language
            for language in pool
            if client.post(
                self.URL, json={"language": language}, environ_base=LOOPBACK
            ).status_code
            == 200
        }
        assert accepted == set(asked)


# --------------------------------------------------------------------------- the checker's own cases


class TestTheCheckerItself:
    def test_nullable_admits_null_and_still_refuses_other_types(self) -> None:
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string", "nullable": True}},
        }
        assert schema_errors(schema, {"a": None}) == []
        assert schema_errors(schema, {"a": "x"}) == []
        assert schema_errors(schema, {"a": 1}) != []

    def test_x_nullable_is_read_too(self) -> None:
        schema = {"type": "integer", "x-nullable": True}
        assert schema_errors(schema, None) == []

    def test_a_plain_property_refuses_null(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        assert schema_errors(schema, {"a": None}) == ["a: None is not of type 'string'"]

    def test_nullable_inside_an_array_item_is_found(self) -> None:
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"a": {"type": "string", "nullable": True}},
            },
        }
        assert schema_errors(schema, [{"a": None}, {"a": "x"}]) == []
        assert schema_errors(schema, [{"a": 2}]) == [
            "*/a: 2 is not of type 'string', 'null'"
        ]

    def test_with_null_leaves_its_argument_alone(self) -> None:
        schema = {"type": "string", "nullable": True}
        before = copy.deepcopy(schema)
        with_null(schema)
        assert schema == before

    def test_an_undeclared_status_is_a_problem(self) -> None:
        operation = {
            "responses": {200: {"description": "ok"}, 400: {"description": "no"}}
        }
        assert judge("GET /x", operation, 500, "application/json", {}) == [
            "GET /x: answered 500, declares [200, 400]"
        ]

    def test_a_declared_status_without_a_schema_passes(self) -> None:
        operation = {"responses": {200: {"description": "ok"}}}
        assert judge("GET /x", operation, 200, "application/json", {"a": 1}) == []

    def test_a_body_that_is_not_json_is_not_validated(self) -> None:
        operation = {"responses": {200: {"schema": {"type": "object"}}}}
        assert judge("GET /x", operation, 200, "text/plain", None) == []

    def test_a_json_body_is_validated_against_the_declared_schema(self) -> None:
        operation = {"responses": {"200": {"schema": {"type": "object"}}}}
        assert judge("GET /x", operation, 200, "application/json", []) == [
            "GET /x (200): <body>: [] is not of type 'object'"
        ]

    def test_operations_reads_the_yaml_after_the_dashes_and_converts_the_path(
        self,
    ) -> None:
        app = Flask("r868-checker")

        @app.route("/api/a/<item_id>", methods=["GET"])
        def described(item_id: str) -> str:
            """Summary.
            ---
            responses:
              200:
                description: ok
            """
            return item_id

        @app.route("/api/b", methods=["POST"])
        def undescribed() -> str:
            """Only a summary."""
            return ""

        @app.route("/not-api")
        def elsewhere() -> str:
            return ""

        found = operations(app)
        assert found == {
            ("/api/a/{item_id}", "GET"): {"responses": {200: {"description": "ok"}}},
            ("/api/b", "POST"): {},
        }

    def test_sample_values(self) -> None:
        assert sample({"type": "string", "example": "e"}) == "e"
        assert sample({"type": "integer", "default": 5}) == 5
        assert sample({"type": "string", "enum": ["a", "b"]}) == "a"
        assert sample({"type": "integer"}) == 1
        assert sample({"type": "integer", "minimum": 10}) == 10
        assert sample({"type": "boolean"}) is True
        assert sample({"type": "array"}) == []
        assert sample(
            {
                "type": "object",
                "required": ["a"],
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            }
        ) == {"a": "x"}

    def test_request_for_builds_the_body_the_form_and_the_query(self) -> None:
        operation = {
            "parameters": [
                {
                    "in": "body",
                    "name": "body",
                    "schema": {
                        "type": "object",
                        "properties": {"a": {"type": "string", "default": "d"}},
                        "required": ["a"],
                    },
                },
                {"in": "formData", "name": "feedback_text", "type": "string"},
                {"in": "formData", "name": "other", "type": "string"},
                {"in": "query", "name": "q", "type": "string", "required": True},
                {"in": "query", "name": "skipped", "type": "string"},
            ]
        }
        kwargs = request_for(operation)
        assert kwargs == {
            "json": {"a": "d"},
            "data": {"feedback_text": "x"},
            "query_string": {"q": "x"},
        }

    def test_openapi_path(self) -> None:
        assert (
            openapi_path("/api/tasks/<task_id>/images/<int:index>")
            == "/api/tasks/{task_id}/images/{index}"
        )
