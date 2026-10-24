"""R859: a ``500`` answer does not carry the text of the exception that caused it.

Every route of the Web UI that fails on the server's side answers with a fixed text
(``服务器内部错误``) or a localised one (``msg("notify.updateFailed")``, ``msg("feedback.serverError")``)
and writes the real cause, with the traceback, to the log.  Two routes did not:

* ``GET /api/loops`` answered ``{"success": false, "error": str(e)}``;
* ``POST /api/update-language`` answered ``{"status": "error", "message": str(e)}``.

``str(e)`` of the usual failures here is an ``OSError`` that names a file
(``[Errno 13] Permission denied: '/Users/someone/.config/ai-intervention-agent/config.toml'``),
so a caller that is allowed to reach the page (``allowed_networks``) learned the
account name and the directory layout of the machine, and the two answers were the only ones
in the web layer that differed from their neighbours in the way they fail.  The
notification routes already have a test for the same rule
(``tests/test_web_ui_routes.py``: "标准化文案，不应是 raw exception text").

What the tests pin:

* the two routes answer ``500`` with the standard text and the cause is not in the body;
* the cause is still in the log, with its traceback (``/api/loops`` used to log it without);
* what did not change: a working ``/api/loops``, a working ``/api/update-language``, the
  ``400`` for a language that is not supported (that text repeats the caller's own input);
* a static rule over ``web_ui.py`` and ``web_ui_routes/*.py`` so the next route cannot do the
  same: no ``except ... as name`` block answers with a status of 500 or above (or one that
  cannot be read) and puts ``name`` into the response, other than as ``type(name).__name__``.
  The rule reads the response expression itself, so a cause copied into a variable first
  would pass it; the checker's own cases below show what it does and does not catch.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent.i18n import _MESSAGES
from ai_intervention_agent.task_queue import TaskQueue
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"
WEB_LAYER = [PACKAGE / "web_ui.py", *sorted((PACKAGE / "web_ui_routes").glob("*.py"))]
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
SECRET = "[Errno 13] Permission denied: '/Users/someone/.config/ai-intervention-agent/c.toml'"
UPDATE_FAILED = {texts["notify.updateFailed"] for texts in _MESSAGES.values()}


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r859", task_id="r859-initial", auto_resubmit_timeout=0, port=19859
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    get_task_queue().clear_all_tasks()
    try:
        yield ui.app.test_client()
    finally:
        get_task_queue().clear_all_tasks()


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise OSError(SECRET)


class TestLoopsRoute:
    def test_500_does_not_say_what_went_wrong(self, client: FlaskClient) -> None:
        with patch.object(TaskQueue, "get_loops_snapshot", _boom):
            resp = client.get("/api/loops", environ_base=LOOPBACK)
        assert resp.status_code == 500
        assert resp.get_json() == {"success": False, "error": "服务器内部错误"}
        assert "Permission denied" not in resp.get_data(as_text=True)
        assert "/Users/" not in resp.get_data(as_text=True)

    def test_the_cause_is_in_the_log_with_its_traceback(
        self, client: FlaskClient
    ) -> None:
        with (
            patch.object(TaskQueue, "get_loops_snapshot", _boom),
            patch("ai_intervention_agent.web_ui_routes.task.logger") as log,
        ):
            client.get("/api/loops", environ_base=LOOPBACK)
        log.error.assert_called_once()
        args, kwargs = log.error.call_args
        assert SECRET in args[0]
        assert kwargs.get("exc_info") is True

    def test_it_answers_the_same_as_the_task_list_does(
        self, client: FlaskClient
    ) -> None:
        with patch.object(TaskQueue, "get_all_tasks_with_stats", _boom):
            listing = client.get("/api/tasks", environ_base=LOOPBACK)
        with patch.object(TaskQueue, "get_loops_snapshot", _boom):
            loops = client.get("/api/loops", environ_base=LOOPBACK)
        assert (listing.status_code, listing.get_json()) == (500, loops.get_json())
        assert loops.status_code == 500

    def test_a_working_loop_view_is_unchanged(self, client: FlaskClient) -> None:
        resp = client.get("/api/loops", environ_base=LOOPBACK)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["loops"] == []
        assert isinstance(body["server_time"], float)


class TestUpdateLanguageRoute:
    def _post(self, client: FlaskClient, language: object) -> Any:
        return client.post(
            "/api/update-language", json={"language": language}, environ_base=LOOPBACK
        )

    def test_500_does_not_say_what_went_wrong(self, client: FlaskClient) -> None:
        config = MagicMock()
        config.update_section.side_effect = OSError(SECRET)
        with patch("ai_intervention_agent.web_ui.get_config", return_value=config):
            resp = self._post(client, "en")
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["status"] == "error"
        assert body["message"] in UPDATE_FAILED
        assert "Permission denied" not in resp.get_data(as_text=True)
        assert "/Users/" not in resp.get_data(as_text=True)

    def test_the_cause_is_in_the_log_with_its_traceback(
        self, client: FlaskClient
    ) -> None:
        config = MagicMock()
        config.update_section.side_effect = OSError(SECRET)
        with (
            patch("ai_intervention_agent.web_ui.get_config", return_value=config),
            patch("ai_intervention_agent.web_ui.logger") as log,
        ):
            self._post(client, "en")
        log.error.assert_called_once()
        args, kwargs = log.error.call_args
        assert SECRET in args[0]
        assert kwargs.get("exc_info") is True

    @pytest.mark.parametrize("language", ["auto", "en", "zh-CN", "zh-TW"])
    def test_a_supported_language_is_saved(
        self, client: FlaskClient, language: str
    ) -> None:
        config = MagicMock()
        with patch("ai_intervention_agent.web_ui.get_config", return_value=config):
            resp = self._post(client, language)
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "success", "language": language}
        config.update_section.assert_called_once_with("web_ui", {"language": language})

    def test_a_language_that_is_not_supported_is_still_a_400(
        self, client: FlaskClient
    ) -> None:
        config = MagicMock()
        with patch("ai_intervention_agent.web_ui.get_config", return_value=config):
            resp = self._post(client, "tlh")
        assert resp.status_code == 400
        assert resp.get_json() == {"status": "error", "message": "不支持的语言: tlh"}
        config.update_section.assert_not_called()


def _parents(root: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(root)
        for child in ast.iter_child_nodes(parent)
    }


def _is_type_name_of(node: ast.Name, parents: dict[ast.AST, ast.AST]) -> bool:
    """``node`` is the ``e`` of ``type(e).__name__``: the class of the failure, not its text."""
    call = parents.get(node)
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "type"
    ):
        return False
    attribute = parents.get(call)
    return isinstance(attribute, ast.Attribute) and attribute.attr == "__name__"


def leaking_returns(source: str) -> list[str]:
    """Every ``return`` in an ``except ... as name`` block that answers with a status of 500
    or above (or one that cannot be read, or none) and puts the caught exception into the
    response other than as ``type(name).__name__``."""
    found: list[str] = []
    for handler in ast.walk(ast.parse(source)):
        if not isinstance(handler, ast.ExceptHandler) or handler.name is None:
            continue
        for node in ast.walk(handler):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            value = node.value
            response, status = (
                (value.elts[0], value.elts[1])
                if isinstance(value, ast.Tuple) and len(value.elts) >= 2
                else (value, None)
            )
            if (
                isinstance(status, ast.Constant)
                and isinstance(status.value, int)
                and status.value < 500
            ):
                continue
            parents = _parents(response)
            if any(
                isinstance(name, ast.Name)
                and name.id == handler.name
                and not _is_type_name_of(name, parents)
                for name in ast.walk(response)
            ):
                found.append(f"line {node.lineno}: {ast.unparse(node)}")
    return found


def _in_handler(statement: str) -> str:
    return f"def view():\n    try:\n        work()\n    except Exception as e:\n        {statement}\n"


class TestTheRuleItself:
    @pytest.mark.parametrize(
        "statement",
        [
            'return jsonify({"error": str(e)}), 500',
            'return jsonify({"error": f"failed: {e}"}), 500',
            'return jsonify({"error": repr(e)}), 503',
            'return jsonify({"error": e.args[0]}), 502',
            'return jsonify({"error": str(e)}), status',
            'return jsonify({"error": str(e)})',
            "return fail(str(e)), 500",
            'return (jsonify({"message": str(e)}), 500)',
            'return jsonify({"error": type(e).__doc__}), 500',
        ],
        ids=[
            "str",
            "f-string",
            "repr",
            "args",
            "unreadable-status",
            "no-status",
            "helper",
            "parenthesised",
            "only-__name__-is-exempt",
        ],
    )
    def test_it_catches(self, statement: str) -> None:
        assert len(leaking_returns(_in_handler(statement))) == 1

    @pytest.mark.parametrize(
        "statement",
        [
            'return jsonify({"error": "服务器内部错误"}), 500',
            'return jsonify({"error": f"internal error: {type(e).__name__}"}), 500',
            'return jsonify({"error": str(e)}), 400',
            'return jsonify({"error": msg("notify.updateFailed")}), 500',
        ],
        ids=["fixed-text", "type-name", "client-error", "localised"],
    )
    def test_it_lets_through(self, statement: str) -> None:
        assert leaking_returns(_in_handler(statement)) == []

    def test_it_only_looks_inside_except_blocks(self) -> None:
        source = (
            "def view():\n    e = compute()\n"
            '    return jsonify({"error": str(e)}), 500\n'
        )
        assert leaking_returns(source) == []

    def test_a_different_name_in_the_response_is_not_the_exception(self) -> None:
        source = (
            "def view(request):\n    try:\n        work()\n    except Exception as e:\n"
            '        log(e)\n        return jsonify({"error": request.path}), 500\n'
        )
        assert leaking_returns(source) == []


def test_the_rule_reads_the_files_it_is_meant_to_read() -> None:
    names = {path.name for path in WEB_LAYER}
    assert {
        "web_ui.py",
        "task.py",
        "system.py",
        "feedback.py",
        "notification.py",
    } <= names


@pytest.mark.parametrize("path", WEB_LAYER, ids=lambda path: path.name)
def test_no_route_answers_with_the_text_of_the_exception(path: Path) -> None:
    assert leaking_returns(path.read_text(encoding="utf-8")) == []
