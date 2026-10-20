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
"""

from __future__ import annotations

import ast
import io
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


def _json_loads_without_a_safe_handler(path: Path) -> list[int]:
    """Lines of ``json.loads(...)`` calls no enclosing ``try`` can survive.

    A call is safe when an enclosing ``try`` (the call in its body) has a handler for
    ``Exception`` / a bare ``except``, or handlers for both ``ValueError`` (the parent of
    ``JSONDecodeError`` and the digit-limit error) and ``RecursionError``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    bad: list[int] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "loads"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
        ):
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
                if (
                    caught & {"BaseException", "Exception"}
                    or {
                        "ValueError",
                        "RecursionError",
                    }
                    <= caught
                ):
                    safe = True
                    break
            child = parent
        if not safe:
            bad.append(node.lineno)
    return sorted(bad)


ROUTE_SOURCES = [
    *sorted((PACKAGE / "web_ui_routes").glob("*.py")),
    PACKAGE / "web_ui.py",
]


class TestNoRouteParsesRequestJsonWithTooNarrowAHandler:
    @pytest.mark.parametrize("path", ROUTE_SOURCES, ids=lambda p: p.name)
    def test_every_json_loads_survives_valueerror_and_recursionerror(
        self, path: Path
    ) -> None:
        assert _json_loads_without_a_safe_handler(path) == [], (
            f"{path.name}: json.loads can raise ValueError (int digit limit) and "
            "RecursionError (deep nesting) besides JSONDecodeError; catch both"
        )

    def test_the_scan_sees_the_json_loads_calls_of_the_submit_routes(self) -> None:
        """Without this the scan could pass by finding nothing to look at."""
        calls: dict[str, int] = {}
        for path in ROUTE_SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls[path.name] = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr == "loads"
                and isinstance(node.value, ast.Name)
                and node.value.id == "json"
            )
        assert calls["feedback.py"] >= 1, calls
        assert calls["task.py"] >= 1, calls

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
            "    return json.loads(raw)\n",
            encoding="utf-8",
        )
        assert _json_loads_without_a_safe_handler(sample) == [4, 13]
