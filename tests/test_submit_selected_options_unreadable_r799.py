"""R799: ``/api/submit`` reads ``selected_options`` from a form without a 500.

The form branches of ``POST /api/submit`` parse the ``selected_options`` field (a JSON
array inside a string) with ``json.loads`` and caught only ``json.JSONDecodeError``,
falling back to "nothing selected".  ``json.loads`` raises other exceptions for input
that is not a syntax error:

* ``ValueError`` (not a ``JSONDecodeError``) for an integer of more than 4300 digits,
  the interpreter's limit on int/str conversion;
* ``RecursionError`` for nesting deeper than the interpreter allows.

Both escaped the handler and the caller got ``500``, although the same field with a
syntax error (``{``) always meant "no selection".  The task-scoped route
(``/api/tasks/<id>/submit``) catches ``Exception`` and answers ``400`` for all of them;
that contract is pinned here too.  Found by a sweep of form fields over every route.

R845 moved the parsing into ``_request_body.loads_bounded`` (one reader, ``ValueError`` for
anything unreadable); the structural half of this file follows it.
"""

from __future__ import annotations

import ast
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent.web_ui import WebFeedbackUI

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

UNREADABLE = {
    "nesting deeper than the interpreter allows": "[" * 5000,
    "an integer of more than 4300 digits": "1" * 4301,
    "an array holding such an integer": "[" + "1" * 5000 + "]",
}


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r799", task_id="r799-task", auto_resubmit_timeout=0, port=19799
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    ui.feedback_result = None
    return ui.app.test_client()


def _encodings(options: str) -> dict[str, dict[str, Any]]:
    """The three ways a browser can send the same form."""
    fields = {"feedback_text": "t", "selected_options": options}
    return {
        "urlencoded form": {"data": fields},
        "multipart form without files": {
            "data": fields,
            "content_type": "multipart/form-data",
        },
        "multipart form with a file": {
            "data": {**fields, "image_0": (io.BytesIO(PNG), "a.png", "image/png")},
            "content_type": "multipart/form-data",
        },
    }


ENCODINGS = list(_encodings("[]"))


class TestSubmitFormOptionsThatAreNotReadableJson:
    @pytest.mark.parametrize("encoding", ENCODINGS)
    @pytest.mark.parametrize("name", list(UNREADABLE))
    def test_means_nothing_selected_not_a_500(
        self, ui: WebFeedbackUI, client: FlaskClient, name: str, encoding: str
    ) -> None:
        response = client.post(
            "/api/submit",
            environ_base=LOOPBACK,
            **_encodings(UNREADABLE[name])[encoding],
        )
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        assert response.get_json()["status"] == "success"
        assert ui.feedback_result is not None
        assert ui.feedback_result["selected_options"] == []
        assert ui.feedback_result["user_input"] == "t"

    @pytest.mark.parametrize("encoding", ENCODINGS)
    def test_a_syntax_error_still_means_nothing_selected(
        self, ui: WebFeedbackUI, client: FlaskClient, encoding: str
    ) -> None:
        response = client.post(
            "/api/submit", environ_base=LOOPBACK, **_encodings("{")[encoding]
        )
        assert response.status_code == 200
        assert ui.feedback_result is not None
        assert ui.feedback_result["selected_options"] == []

    @pytest.mark.parametrize("encoding", ENCODINGS)
    def test_a_readable_array_is_kept(
        self, ui: WebFeedbackUI, client: FlaskClient, encoding: str
    ) -> None:
        response = client.post(
            "/api/submit",
            environ_base=LOOPBACK,
            **_encodings('["a", "b", "a"]')[encoding],
        )
        assert response.status_code == 200
        assert ui.feedback_result is not None
        assert ui.feedback_result["selected_options"] == ["a", "b"]

    @pytest.mark.parametrize("encoding", ENCODINGS)
    def test_the_largest_integer_the_interpreter_reads_is_not_an_array(
        self, ui: WebFeedbackUI, client: FlaskClient, encoding: str
    ) -> None:
        response = client.post(
            "/api/submit",
            environ_base=LOOPBACK,
            **_encodings("1" * 4300)[encoding],
        )
        assert response.status_code == 200
        assert ui.feedback_result is not None
        assert ui.feedback_result["selected_options"] == []


class TestTaskScopedSubmitStillAnswers400:
    """``/api/tasks/<id>/submit`` already caught ``Exception``; keep it that way."""

    @pytest.mark.parametrize("name", list(UNREADABLE))
    def test_unreadable_options_are_a_400(self, client: FlaskClient, name: str) -> None:
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        queue = get_task_queue()
        queue.remove_task("r799-scoped")
        queue.add_task(
            task_id="r799-scoped",
            prompt="p",
            predefined_options=["x"],
            auto_resubmit_timeout=0,
        )
        try:
            response = client.post(
                "/api/tasks/r799-scoped/submit",
                environ_base=LOOPBACK,
                data={"feedback_text": "t", "selected_options": UNREADABLE[name]},
            )
            assert response.status_code == 400, response.get_data(as_text=True)[:200]
            assert response.get_json()["success"] is False
        finally:
            queue.remove_task("r799-scoped")


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    """Exception class names a handler catches; a bare ``except`` catches all."""
    if handler.type is None:
        return {"BaseException"}
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _is_json_loads(node: ast.AST) -> bool:
    """``json.loads(...)``: besides ``JSONDecodeError`` it raises ``ValueError`` (the digit
    limit) and ``RecursionError`` (depth)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "loads"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
    )


def _is_bounded_read(node: ast.AST) -> bool:
    """``loads_bounded(...)`` (R845), the one reader of request JSON: it raises ``ValueError``
    for every text it cannot read - a too-deep one included - and nothing else."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "loads_bounded"
    )


JSON_LOADS_RAISES = {"ValueError", "RecursionError"}
BOUNDED_READ_RAISES = {"ValueError"}


def _reads_without_a_safe_handler(
    path: Path, is_read: Callable[[ast.AST], bool], raises: set[str]
) -> list[int]:
    """Lines of calls ``is_read`` accepts that no enclosing ``try`` can survive.

    A call is safe when an enclosing ``try`` (the call in its body) has a handler for
    ``Exception`` / a bare ``except``, or handlers for every name in ``raises``
    (``ValueError`` is the parent of ``JSONDecodeError`` and of the digit-limit error).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    bad: list[int] = []
    for node in ast.walk(tree):
        if not is_read(node):
            continue
        safe = False
        child: ast.AST = node
        while child in parents:
            parent = parents[child]
            if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                break  # a ``try`` around a ``def`` does not catch the call made later
            if isinstance(parent, ast.Try) and child in parent.body:
                caught: set[str] = set()
                for handler in parent.handlers:
                    caught |= _handler_names(handler)
                if caught & {"BaseException", "Exception"} or raises <= caught:
                    safe = True
                    break
            child = parent
        if not safe:
            bad.append(getattr(node, "lineno", 0))
    return sorted(bad)


ROUTE_SOURCES = [
    *sorted((PACKAGE / "web_ui_routes").glob("*.py")),
    PACKAGE / "web_ui.py",
]
THE_READER = PACKAGE / "web_ui_routes" / "_request_body.py"
CALLERS = [path for path in ROUTE_SOURCES if path != THE_READER]


class TestNoRouteParsesRequestJsonWithTooNarrowAHandler:
    """R799 found ``json.loads`` calls whose handler knew only ``JSONDecodeError``.  Since R845
    a route reads request JSON through ``loads_bounded`` alone (``test_lone_surrogates_r845``
    pins that), so the rule has two halves: whoever calls the reader handles ``ValueError``,
    and the reader itself turns ``RecursionError`` into one."""

    @pytest.mark.parametrize("path", CALLERS, ids=lambda p: p.name)
    def test_every_json_loads_survives_valueerror_and_recursionerror(
        self, path: Path
    ) -> None:
        assert (
            _reads_without_a_safe_handler(path, _is_json_loads, JSON_LOADS_RAISES) == []
        ), (
            f"{path.name}: json.loads can raise ValueError (int digit limit) and "
            "RecursionError (deep nesting) besides JSONDecodeError; catch both"
        )

    @pytest.mark.parametrize("path", CALLERS, ids=lambda p: p.name)
    def test_every_bounded_read_survives_valueerror(self, path: Path) -> None:
        assert (
            _reads_without_a_safe_handler(path, _is_bounded_read, BOUNDED_READ_RAISES)
            == []
        ), (
            f"{path.name}: loads_bounded raises ValueError for text it cannot read; catch it"
        )

    def test_the_reader_turns_recursionerror_into_valueerror(self) -> None:
        """Its one ``json.loads`` lets ``ValueError`` out on purpose (that is its contract:
        Flask answers ``400`` to it, the form parsers read it as "nothing selected")."""
        assert (
            _reads_without_a_safe_handler(
                THE_READER, _is_json_loads, {"RecursionError"}
            )
            == []
        )

    def test_the_scan_sees_the_reads_of_the_submit_routes(self) -> None:
        """Without this the scan could pass by finding nothing to look at."""

        def count(path: Path, is_read: Callable[[ast.AST], bool]) -> int:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            return sum(1 for node in ast.walk(tree) if is_read(node))

        routes = PACKAGE / "web_ui_routes"
        assert count(routes / "feedback.py", _is_bounded_read) >= 1
        assert count(routes / "task.py", _is_bounded_read) >= 1
        assert count(THE_READER, _is_json_loads) == 1

    def test_the_scan_rejects_a_handler_that_only_knows_jsondecodeerror(
        self, tmp_path: Path
    ) -> None:
        sample = tmp_path / "sample.py"
        sample.write_text(
            "import json\n"
            "def f(raw):\n"
            "    try:\n"
            "        return json.loads(raw)\n"
            "    except json.JSONDecodeError:\n"
            "        return []\n"
            "def g(raw):\n"
            "    try:\n"
            "        return json.loads(raw)\n"
            "    except (ValueError, RecursionError):\n"
            "        return []\n"
            "def h(raw):\n"
            "    return json.loads(raw)\n"
            "def i(raw):\n"
            "    try:\n"
            "        return loads_bounded(raw)\n"
            "    except json.JSONDecodeError:\n"
            "        return []\n"
            "def j(raw):\n"
            "    try:\n"
            "        return loads_bounded(raw)\n"
            "    except ValueError:\n"
            "        return []\n"
            "def k(raw):\n"
            "    return loads_bounded(raw)\n",
            encoding="utf-8",
        )
        assert _reads_without_a_safe_handler(
            sample, _is_json_loads, JSON_LOADS_RAISES
        ) == [4, 13]
        assert _reads_without_a_safe_handler(
            sample, _is_bounded_read, BOUNDED_READ_RAISES
        ) == [16, 25]
