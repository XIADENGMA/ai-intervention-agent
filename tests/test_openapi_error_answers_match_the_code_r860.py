"""R860: the OpenAPI text of an error answer says what the route really answers.

The error schemas in the route docstrings were written to raise the coverage ratchets
(R422-R446: "how many 4xx/5xx responses have a ``schema``"), and a ratchet cannot tell a schema
that is true from one that is not.  Reading them against the code found these:

* ``GET /api/tasks``, ``GET /api/loops``, ``GET /api/tasks/export``, ``GET /api/tasks/<id>`` documented
  ``{"status": "error", "message": ...}`` for their 404 / 500 answers; the code answers
  ``{"success": false, "error": ...}``;
* ``POST /api/tasks`` (400 / 409 / 500), ``POST /api/system/open-config-file`` (400 / 403 / 500) and
  ``POST /api/system/log-level`` (400 / 403) documented a ``message`` field and "classification codes"
  (``invalid_payload``, ``duplicate_task_id``, ``queue_full``, ``path_not_found``, ``non_loopback``,
  ``invalid_level`` ...) that exist nowhere in the code: ``error`` is the text, there is no ``message``;
* ``POST /api/tasks/<id>/extend`` documented ``code: extends_exhausted`` for 422; the code (and the VS Code
  panel, which tests for it) uses ``extends_limit_reached``;
* ``POST /api/submit`` and ``POST /api/system/rotate-api-token`` documented a 429 body with ``retry_after``
  (and ``status`` / ``message`` / ``success``); the rate limiter answers ``{"error": "rate_limit_exceeded"}``
  and puts the wait in the ``Retry-After`` header;
* ``GET /api/system/health`` documented ``timestamp`` in its 503 body; the field is ``ts_unix``;
* ``rotate-api-token`` said the new token is "usually 64" characters long (``secrets.token_urlsafe(32)`` is
  43), ``api-token-info`` said ``token_length`` is ``0`` without a token (it is ``null``), and ``log-level``
  said only loopback may call it (a valid API token works too, like ``open-config-file``; R189 and R850
  already pin that behaviour, so only the wording is new).

A client written against those schemas would never see ``extends_limit_reached`` and would look for fields
that are not there.  What the tests pin:

* a rule over every route docstring: each property documented for a 4xx / 5xx answer can be produced by
  the route (a dict literal in a ``return`` with that status, any return whose status the code cannot read,
  a helper the route calls, or the answer the app gives to every route for that status);
* a rule over the identifiers: an ``enum`` value of ``error`` / ``code`` / ``reason``, and every
  ``snake_case`` word in their description or the response description, is a string that exists in the
  source (this is what catches ``invalid_payload`` and ``extends_exhausted``);
* the checkers' own cases, so they cannot go quiet;
* the facts above, against the running routes: token length, ``token_length`` without a token, the real 429
  body and header.
"""

from __future__ import annotations

import ast
import re
import secrets
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from flask.testing import FlaskClient

from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import system as system_module

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"
ROUTES = PACKAGE / "web_ui_routes"
ROUTE_FILES = [PACKAGE / "web_ui.py", *sorted(ROUTES.glob("*.py"))]
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
SNAKE_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
CODE_PROPERTIES = {"error", "code", "reason"}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(path: Path, name: str, owner: str | None = None) -> ast.FunctionDef:
    tree = _parse(path)
    scopes: list[ast.AST] = (
        [tree]
        if owner is None
        else [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == owner
        ]
    )
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
    raise LookupError(f"{path.name}: {owner or ''}.{name}")


def literal_keys(node: ast.AST) -> set[str]:
    """String keys of every dict literal inside ``node``."""
    keys: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            keys |= {
                key.value
                for key in sub.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    return keys


def answers(
    function: ast.FunctionDef,
) -> tuple[dict[int | None, set[str]], set[int | None]]:
    """What ``function`` answers: ``({status: keys}, statuses of answers that have no dict literal)``.

    ``None`` stands for a status the code cannot read (``return jsonify(...), status_code``).
    ``response.status_code = 413`` after the body was built elsewhere counts for the whole function.
    """
    by_status: dict[int | None, set[str]] = {}
    opaque: set[int | None] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and node.value is not None:
            value = node.value
            if isinstance(value, ast.Tuple) and len(value.elts) >= 2:
                response, status_node = value.elts[0], value.elts[1]
            else:
                response, status_node = value, None
            if status_node is None:
                status: int | None = 200
            elif isinstance(status_node, ast.Constant) and isinstance(
                status_node.value, int
            ):
                status = status_node.value
            else:
                status = None
            keys = literal_keys(response)
            by_status.setdefault(status, set()).update(keys)
            if not keys:
                opaque.add(status)
        elif (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == "status_code"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            by_status.setdefault(node.value.value, set()).update(literal_keys(function))
    return by_status, opaque


BODY = ROUTES / "_request_body.py"
# A route that calls one of these gets their answers for the status named; the keys are read from
# the helper's own source, so a change there changes what the routes may document.
CALLS: dict[str, dict[int | None, set[str]]] = {
    "require_json_object": {
        400: literal_keys(_function(BODY, "get_response", "InvalidRequestBody"))
    },
    "invalid_value_response": answers(_function(BODY, "invalid_value_response"))[0],
    "refused_answer_response": answers(
        _function(ROUTES / "_task_answer.py", "refused_answer_response")
    )[0],
}
# What the app answers for every route.
APP_WIDE: dict[int, set[str]] = {
    413: literal_keys(_function(BODY, "request_too_large_response")),
    429: answers(
        _function(
            PACKAGE / "web_ui_rate_limiter.py", "_check_limits", "WebUiRateLimiter"
        )
    )[0][429],
}


def route_functions(tree: ast.AST) -> Iterator[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr == "route"
            for dec in node.decorator_list
        ):
            yield node


def documented_responses(function: ast.FunctionDef) -> dict[int, dict[str, Any]]:
    doc = ast.get_docstring(function, clean=True) or ""
    if "---" not in doc:
        return {}
    spec = yaml.safe_load(doc.split("---", 1)[1]) or {}
    return {
        int(code): response
        for code, response in (spec.get("responses") or {}).items()
        if isinstance(response, dict)
    }


def properties_of(response: dict[str, Any]) -> dict[str, Any]:
    return (response.get("schema") or {}).get("properties") or {}


def producible(function: ast.FunctionDef, status: int) -> set[str]:
    by_status, opaque = answers(function)
    keys = set(by_status.get(status, ())) | set(by_status.get(None, ()))
    if status in opaque or None in opaque:
        keys |= literal_keys(function)  # ``jsonify(payload)``: the dict was built above
    called = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for name in called:
        keys |= CALLS.get(name, {}).get(status, set())
    return keys | APP_WIDE.get(status, set())


def unfounded_properties(function: ast.FunctionDef) -> list[str]:
    """``"<status>: <property>"`` for every property documented for a 4xx / 5xx answer that
    the route cannot produce."""
    found: list[str] = []
    for status, response in documented_responses(function).items():
        if status >= 400:
            missing = set(properties_of(response)) - producible(function, status)
            found.extend(f"{status}: {name}" for name in sorted(missing))
    return found


SOURCE_STRINGS = {
    node.value
    for path in PACKAGE.rglob("*.py")
    for node in ast.walk(_parse(path))
    if isinstance(node, ast.Constant) and isinstance(node.value, str)
}


def invented_identifiers(function: ast.FunctionDef, known: set[str]) -> list[str]:
    """Identifiers an error response documents that are not strings of the source."""
    found: list[str] = []
    for status, response in documented_responses(function).items():
        if status < 400:
            continue
        texts = [("description", str(response.get("description") or ""))]
        for name, prop in properties_of(response).items():
            if name in CODE_PROPERTIES and isinstance(prop, dict):
                texts.extend(("enum", str(value)) for value in prop.get("enum") or [])
                texts.append(
                    (f"{name} description", str(prop.get("description") or ""))
                )
        for where, text in texts:
            words = [text] if where == "enum" else SNAKE_CASE.findall(text)
            found.extend(
                f"{status} {where}: {word}" for word in words if word not in known
            )
    return found


def _function_from(source: str) -> ast.FunctionDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def _route(responses: str, body: str) -> ast.FunctionDef:
    doc = "\n".join(
        f"    {line}"
        for line in ("summary", "---", "responses:", *responses.splitlines())
    )
    lines = "\n".join(f"    {line}" for line in body.splitlines())
    return _function_from(f'def view():\n    """\n{doc}\n    """\n{lines}\n')


class TestTheDocumentedPropertiesRule:
    TEMPLATE = (
        "  {status}:\n    description: x\n    schema:\n      type: object\n"
        "      properties:\n{properties}"
    )

    def _doc(self, status: int, *names: str) -> str:
        properties = "".join(
            f"        {name}:\n          type: string\n          description: d\n"
            for name in names
        )
        return self.TEMPLATE.format(status=status, properties=properties)

    def test_a_property_the_literal_answer_has_is_fine(self) -> None:
        route = _route(
            self._doc(404, "success", "error"),
            'return jsonify({"success": False, "error": "gone"}), 404',
        )
        assert unfounded_properties(route) == []

    def test_a_property_no_answer_has_is_found(self) -> None:
        route = _route(
            self._doc(404, "success", "message"),
            'return jsonify({"success": False, "error": "gone"}), 404',
        )
        assert unfounded_properties(route) == ["404: message"]

    def test_an_answer_with_another_status_does_not_count(self) -> None:
        route = _route(
            self._doc(404, "message"),
            'if x:\n    return jsonify({"message": "m"}), 400\nreturn jsonify({"error": "e"}), 404',
        )
        assert unfounded_properties(route) == ["404: message"]

    def test_a_status_the_code_cannot_read_counts_for_every_status(self) -> None:
        route = _route(
            self._doc(422, "code"),
            'return jsonify({"code": c}), status_code',
        )
        assert unfounded_properties(route) == []

    def test_the_dict_built_above_counts_for_a_return_without_a_literal(self) -> None:
        route = _route(
            self._doc(503, "ts_unix", "timestamp"),
            'payload = {"status": "x", "ts_unix": 1}\nreturn jsonify(payload), 503',
        )
        assert unfounded_properties(route) == ["503: timestamp"]

    def test_a_status_set_on_the_response_counts(self) -> None:
        route = _route(
            self._doc(400, "error", "message"),
            'response = jsonify({"error": "e", "message": "m"})\n'
            "response.status_code = 400\n"
            "return response",
        )
        assert unfounded_properties(route) == []

    def test_a_helper_the_route_calls_answers_for_its_status_only(self) -> None:
        route = _route(
            self._doc(409, "success", "status", "error", "message")
            + self._doc(400, "message"),
            "return refused_answer_response(queue, task_id)",
        )
        assert unfounded_properties(route) == ["400: message"]

    def test_what_the_app_answers_for_every_route_counts(self) -> None:
        route = _route(
            self._doc(429, "error", "retry_after") + self._doc(413, "message"),
            'return jsonify({"ok": True})',
        )
        assert unfounded_properties(route) == ["429: retry_after"]

    @pytest.mark.parametrize("status", [200, 302])
    def test_answers_that_are_not_errors_are_not_looked_at(self, status: int) -> None:
        route = _route(self._doc(status, "anything"), 'return jsonify({"ok": True})')
        assert unfounded_properties(route) == []


class TestTheIdentifierRule:
    KNOWN = {"invalid_json", "extends_limit_reached", "服务器内部错误"}

    def _route(
        self, status: int, prop: str, extra: str, description: str = "x"
    ) -> ast.FunctionDef:
        responses = (
            f"  {status}:\n    description: {description}\n    schema:\n      type: object\n"
            f"      properties:\n        {prop}:\n          type: string\n{extra}"
            "          description: d\n"
        )
        return _route(responses, "return 1")

    def test_a_known_code_in_a_description_is_fine(self) -> None:
        route = self._route(400, "error", "", "see invalid_json")
        assert invented_identifiers(route, self.KNOWN) == []

    def test_an_invented_code_in_the_response_description_is_found(self) -> None:
        route = self._route(400, "error", "", "classification code invalid_payload")
        assert invented_identifiers(route, self.KNOWN) == [
            "400 description: invalid_payload"
        ]

    def test_an_invented_code_in_the_property_description_is_found(self) -> None:
        responses = (
            "  422:\n    description: x\n    schema:\n      type: object\n"
            "      properties:\n        code:\n          type: string\n"
            "          description: always extends_exhausted\n"
        )
        assert invented_identifiers(_route(responses, "return 1"), self.KNOWN) == [
            "422 code description: extends_exhausted"
        ]

    def test_an_enum_value_that_is_not_in_the_source_is_found(self) -> None:
        route = self._route(500, "error", "          enum: [服务器错误]\n")
        assert invented_identifiers(route, self.KNOWN) == ["500 enum: 服务器错误"]

    def test_an_enum_value_in_the_source_is_fine(self) -> None:
        route = self._route(500, "error", "          enum: [服务器内部错误]\n")
        assert invented_identifiers(route, self.KNOWN) == []

    def test_other_properties_and_answers_that_are_not_errors_are_not_read(
        self,
    ) -> None:
        for status in (200, 302):
            route = self._route(status, "error", "", "invalid_payload")
            assert invented_identifiers(route, self.KNOWN) == []
        other = self._route(400, "note", "")
        assert invented_identifiers(other, self.KNOWN) == []


def _documented_routes() -> list[tuple[str, ast.FunctionDef]]:
    return [
        (f"{path.name}::{function.name}", function)
        for path in ROUTE_FILES
        for function in route_functions(_parse(path))
        if any(
            status >= 400 and properties_of(response)
            for status, response in documented_responses(function).items()
        )
    ]


DOCUMENTED = _documented_routes()


def test_the_rules_read_the_routes_they_are_meant_to_read() -> None:
    names = {name for name, _ in DOCUMENTED}
    assert len(names) >= 20
    assert {
        "task.py::create_task",
        "system.py::open_config_file",
        "system.py::rotate_api_token",
        "feedback.py::submit_feedback",
    } <= names


@pytest.mark.parametrize(
    ("name", "function"), DOCUMENTED, ids=[n for n, _ in DOCUMENTED]
)
def test_every_documented_error_property_can_be_produced(
    name: str, function: ast.FunctionDef
) -> None:
    assert unfounded_properties(function) == [], name


@pytest.mark.parametrize(
    ("name", "function"), DOCUMENTED, ids=[n for n, _ in DOCUMENTED]
)
def test_every_documented_error_identifier_exists_in_the_source(
    name: str, function: ast.FunctionDef
) -> None:
    assert invented_identifiers(function, SOURCE_STRINGS) == [], name


def _documented(path: str, function: str, status: int) -> dict[str, Any]:
    file = PACKAGE / path
    return documented_responses(_function(file, function))[status]


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r860", task_id="r860-initial", auto_resubmit_timeout=0, port=19860
    )
    instance.app.config["TESTING"] = True
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    ui.limiter.enabled = False
    yield ui.app.test_client()


class TestTokenFacts:
    def test_a_rotated_token_has_the_length_the_docs_give(
        self, client: FlaskClient
    ) -> None:
        config = MagicMock()
        with patch.object(system_module, "get_config", return_value=config):
            resp = client.post("/api/system/rotate-api-token", environ_base=LOOPBACK)
        body = resp.get_json()
        assert resp.status_code == 200
        assert (
            body["token_length"]
            == len(body["api_token"])
            == len(secrets.token_urlsafe(32))
        )
        description = properties_of(
            _documented("web_ui_routes/system.py", "rotate_api_token", 200)
        )["token_length"]["description"]
        assert str(body["token_length"]) in description
        assert "64" not in description

    def test_token_length_is_null_without_a_token_and_the_docs_say_so(
        self, client: FlaskClient
    ) -> None:
        config = MagicMock()
        config.get_network_security_config.return_value = {
            "api_token": "",
            "api_token_rotated_at": "",
        }
        with patch.object(system_module, "get_config", return_value=config):
            resp = client.get("/api/system/api-token-info", environ_base=LOOPBACK)
        body = resp.get_json()
        assert body["has_token"] is False
        assert body["token_length"] is None
        assert body["age_seconds"] is None
        documented = properties_of(
            _documented("web_ui_routes/system.py", "api_token_info", 200)
        )
        assert documented["token_length"].get("nullable") is True
        assert documented["age_seconds"].get("nullable") is True
        assert "为 0" not in documented["token_length"]["description"]


class TestRateLimitAnswer:
    @pytest.mark.parametrize(
        ("path", "function", "url", "limit", "port"),
        [
            (
                "web_ui_routes/system.py",
                "rotate_api_token",
                "/api/system/rotate-api-token",
                5,
                19861,
            ),
            ("web_ui_routes/feedback.py", "submit_feedback", "/api/submit", 60, 19862),
        ],
        ids=["rotate-api-token", "submit"],
    )
    def test_the_429_has_the_body_and_the_header_the_docs_give(
        self, path: str, function: str, url: str, limit: int, port: int
    ) -> None:
        # Its own app (the limiter is on by default), and a clock that stands still so that
        # no minute can end in the middle of the requests.
        limited_ui = WebFeedbackUI(
            prompt="r860", task_id="r860-limited", auto_resubmit_timeout=0, port=port
        )
        limited_ui.app.config["TESTING"] = True
        client = limited_ui.app.test_client()
        clock = SimpleNamespace(time=lambda: 1_000_000.5)
        with (
            patch("ai_intervention_agent.web_ui_rate_limiter.time", clock),
            patch.object(system_module, "get_config", return_value=MagicMock()),
        ):
            for _ in range(limit):
                assert client.post(url, environ_base=LOOPBACK).status_code != 429
            limited = client.post(url, environ_base=LOOPBACK)
        assert limited.status_code == 429
        body = limited.get_json()
        documented = _documented(path, function, 429)
        assert set(body) == set(properties_of(documented)) == {"error"}
        assert body["error"] == "rate_limit_exceeded"
        assert properties_of(documented)["error"]["enum"] == ["rate_limit_exceeded"]
        assert int(limited.headers["Retry-After"]) >= 1
        assert "Retry-After" in documented["headers"]
