"""R800: a request body over the upload limit is answered ``413`` with a JSON body.

``MAX_CONTENT_LENGTH`` (``MAX_TOTAL_UPLOAD_BYTES`` + 1 MB) makes Werkzeug raise
``RequestEntityTooLarge`` the moment a handler touches the body.  Before this round:

* ``POST /api/tasks/<id>/submit`` (the browser UI's submit) and
  ``POST /api/tasks/<id>/extend`` read the body inside a ``try`` whose
  ``except Exception`` turned the 413 into ``500`` (an ERROR with a traceback in the
  log, and the UI told the user "the service is unavailable");
* every route that reads a JSON object through ``require_json_object`` answered
  ``400 invalid_json`` ("Request body must be JSON"), because it caught ``Exception``
  and the 413 is one, although ``optional_json_object`` documents that HTTP's own
  status passes through;
* ``POST /api/submit`` answered 413, but with Flask's HTML page, while its OpenAPI
  docstring promised a JSON ``{status, message}`` body and named a limit constant
  (``_FEEDBACK_PAYLOAD_LIMIT_BYTES``) that exists nowhere in the code.

Found by sending oversize bodies of three kinds to every write route.  The tests run
the real app with ``MAX_CONTENT_LENGTH`` lowered to 2 KB, so a 4 KB body takes the same
path as 101 MB in production.
"""

from __future__ import annotations

import inspect
import io
import re
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from flask.testing import FlaskClient
from werkzeug.exceptions import RequestEntityTooLarge

from ai_intervention_agent.notification_manager import NotificationManager
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes._request_body import (
    InvalidRequestBody,
    optional_json_object,
    require_json_object,
)

LIMIT = 2048
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
PNG = b"\x89PNG\r\n\x1a\n"
TASK = "r800-task"
PACKAGE = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r800", task_id="r800-initial", auto_resubmit_timeout=0, port=19800
    )
    instance.app.config["TESTING"] = True
    instance.app.config["MAX_CONTENT_LENGTH"] = LIMIT
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    queue = get_task_queue()
    queue.remove_task(TASK)
    queue.add_task(
        task_id=TASK, prompt="p", predefined_options=["x"], auto_resubmit_timeout=300
    )
    try:
        yield ui.app.test_client()
    finally:
        queue.remove_task(TASK)


def _bodies() -> dict[str, dict[str, Any]]:
    """Three kinds of body, each larger than ``LIMIT`` (built fresh: streams are single use)."""
    pad = b"x" * (LIMIT * 2)
    return {
        "json": {
            "data": b'{"seconds": 60, "pad": "' + pad + b'"}',
            "content_type": "application/json",
        },
        "urlencoded form": {
            "data": b"feedback_text=" + pad,
            "content_type": "application/x-www-form-urlencoded",
        },
        "multipart": {
            "data": {
                "feedback_text": "t",
                "image_0": (io.BytesIO(PNG + pad), "a.png", "image/png"),
            },
            "content_type": "multipart/form-data",
        },
    }


KINDS = list(_bodies())

# Routes that read a JSON object from the body: oversize JSON must be 413.
JSON_ROUTES = [
    "/api/update-language",
    "/api/update-notification-config",
    "/api/update-feedback-config",
    "/api/update",
    "/api/test-bark",
    "/api/notify-new-tasks",
    "/api/tasks",
    f"/api/tasks/{TASK}/extend",
]
# Routes that parse forms and files: every kind of oversize body must be 413.
FORM_ROUTES = ["/api/submit", f"/api/tasks/{TASK}/submit"]


def _write_routes(ui: WebFeedbackUI) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for rule in ui.app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS", "GET"}):
            path = re.sub(r"<(?:[^:>]+:)?[^>]+>", TASK, rule.rule)
            found.append((method, path))
    return found


class TestOversizeBodyIsA413:
    @pytest.mark.parametrize("route", JSON_ROUTES)
    def test_json_routes_answer_413_for_an_oversize_json_body(
        self, client: FlaskClient, route: str
    ) -> None:
        response = client.post(route, environ_base=LOOPBACK, **_bodies()["json"])
        assert response.status_code == 413, response.get_data(as_text=True)[:200]

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("route", FORM_ROUTES)
    def test_form_routes_answer_413_for_every_kind_of_oversize_body(
        self, client: FlaskClient, route: str, kind: str
    ) -> None:
        response = client.post(route, environ_base=LOOPBACK, **_bodies()[kind])
        assert response.status_code == 413, response.get_data(as_text=True)[:200]

    def test_the_task_is_still_open_after_a_refused_submit(
        self, client: FlaskClient
    ) -> None:
        client.post(
            f"/api/tasks/{TASK}/submit", environ_base=LOOPBACK, **_bodies()["multipart"]
        )
        task = get_task_queue().get_task(TASK)
        assert task is not None
        assert task.status != "completed"

    def test_an_oversize_extend_does_not_use_up_an_extension(
        self, client: FlaskClient
    ) -> None:
        client.post(
            f"/api/tasks/{TASK}/extend", environ_base=LOOPBACK, **_bodies()["json"]
        )
        task = get_task_queue().get_task(TASK)
        assert task is not None
        assert task.extends_used == 0


class TestTheAnswerIsJson:
    @pytest.mark.parametrize("route", ["/api/update-language", *FORM_ROUTES])
    def test_envelope(self, client: FlaskClient, route: str) -> None:
        kind = "multipart" if route in FORM_ROUTES else "json"
        response = client.post(route, environ_base=LOOPBACK, **_bodies()[kind])
        assert response.status_code == 413
        assert response.mimetype == "application/json"
        body = response.get_json()
        assert body["success"] is False
        assert body["status"] == "error"
        assert body["error"] == "payload_too_large"
        assert "2 KB" in body["message"]

    @pytest.mark.parametrize(
        ("accept_language", "expected"),
        [("zh-CN", "请求"), ("zh-TW", "請求"), ("en", "Request")],
    )
    def test_message_is_localized(
        self, client: FlaskClient, accept_language: str, expected: str
    ) -> None:
        response = client.post(
            "/api/update-language",
            environ_base=LOOPBACK,
            headers={"Accept-Language": accept_language},
            **_bodies()["json"],
        )
        assert response.status_code == 413
        assert expected in response.get_json()["message"]

    def test_the_message_names_the_real_limit(self, ui: WebFeedbackUI) -> None:
        """Not the 2 KB of this test app: the production figure, 101 MB."""
        from ai_intervention_agent.web_ui_routes._upload_helpers import (
            MAX_TOTAL_UPLOAD_BYTES,
        )

        fresh = WebFeedbackUI(
            prompt="r800", task_id="r800-limit", auto_resubmit_timeout=0, port=19801
        )
        assert (
            fresh.app.config["MAX_CONTENT_LENGTH"] == MAX_TOTAL_UPLOAD_BYTES + 1024**2
        )
        fresh.app.config["TESTING"] = True
        fresh.limiter.enabled = False
        body = fresh.app.test_client().post(
            "/api/update-language",
            environ_base=LOOPBACK,
            data=b'{"language": "'
            + b"x" * (MAX_TOTAL_UPLOAD_BYTES + 2 * 1024**2)
            + b'"}',
            content_type="application/json",
        )
        assert body.status_code == 413
        assert "101 MB" in body.get_json()["message"]


class TestNothingElseChanged:
    def test_a_body_under_the_limit_is_still_accepted(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            f"/api/tasks/{TASK}/submit",
            environ_base=LOOPBACK,
            data={"feedback_text": "small"},
        )
        assert response.status_code == 200
        assert response.get_json()["success"] is True

    def test_malformed_json_under_the_limit_is_still_a_400(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            "/api/update-language",
            environ_base=LOOPBACK,
            data=b"{",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "invalid_json"

    def test_a_non_object_json_under_the_limit_is_still_a_400(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            "/api/update-language",
            environ_base=LOOPBACK,
            data=b"[1]",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.get_json()["error"] == "invalid_body"

    def test_an_unknown_path_is_still_the_json_404(self, client: FlaskClient) -> None:
        response = client.post("/api/nope", environ_base=LOOPBACK)
        assert response.status_code == 404
        assert response.get_json() == {"success": False, "error": "not_found"}


class TestBodyHelpersLetTheHttpStatusThrough:
    def test_require_json_object_raises_413_not_invalid_request_body(
        self, ui: WebFeedbackUI
    ) -> None:
        with (
            ui.app.test_request_context(method="POST", **_bodies()["json"]),
            pytest.raises(RequestEntityTooLarge),
        ):
            require_json_object()

    def test_require_json_object_still_refuses_a_bad_body_with_400(
        self, ui: WebFeedbackUI
    ) -> None:
        with (
            ui.app.test_request_context(
                method="POST", data=b"{", content_type="application/json"
            ),
            pytest.raises(InvalidRequestBody),
        ):
            require_json_object()

    def test_optional_json_object_lets_413_through(self, ui: WebFeedbackUI) -> None:
        with (
            ui.app.test_request_context(method="POST", **_bodies()["json"]),
            pytest.raises(RequestEntityTooLarge),
        ):
            optional_json_object()


class TestNoWriteRouteAnswers5xxForAnOversizeBody:
    @pytest.fixture(autouse=True)
    def _nothing_leaves_the_machine_and_nothing_is_launched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[list[Any]]:
        """The sweep reaches every write route: some send, some open a file."""
        attempts: list[Any] = []
        real_connect = socket.socket.connect

        def guarded_connect(sock: socket.socket, address: Any, *args: Any) -> Any:
            host = address[0] if isinstance(address, tuple) else address
            if host not in ("127.0.0.1", "::1", "localhost"):
                attempts.append(address)
                raise OSError("R800 sweep: outbound connections are blocked")
            return real_connect(sock, address, *args)

        monkeypatch.setattr(socket.socket, "connect", guarded_connect)
        monkeypatch.setattr(
            NotificationManager, "send_notification", lambda self, *a, **k: ""
        )
        # ``/api/system/open-config-file`` launches an editor or the system opener. ``Popen`` is
        # replaced below, but the route answers 500 before it gets that far when the machine has
        # neither (a bare Linux container has no ``xdg-open``), so hand it an opener to "launch".
        monkeypatch.setattr(
            "ai_intervention_agent.web_ui_routes.system._system_open_command",
            lambda target: ["xdg-open", str(target)],
        )
        monkeypatch.setattr(
            subprocess, "Popen", lambda *a, **k: MagicMock(pid=1, poll=lambda: None)
        )
        yield attempts
        assert attempts == [], f"the sweep tried to reach {attempts}"

    def test_the_sweep_has_something_to_sweep(self, ui: WebFeedbackUI) -> None:
        assert len(_write_routes(ui)) >= 15

    @pytest.mark.parametrize("kind", KINDS)
    def test_no_5xx(self, ui: WebFeedbackUI, client: FlaskClient, kind: str) -> None:
        failures: list[str] = []
        for method, path in _write_routes(ui):
            response = client.open(
                path, method=method, environ_base=LOOPBACK, **_bodies()[kind]
            )
            if response.status_code >= 500:
                failures.append(f"{method} {path} ({kind}) -> {response.status_code}")
        assert not failures, "\n".join(failures)


def _documented_responses(ui: WebFeedbackUI, path: str) -> dict[Any, Any]:
    for rule in ui.app.url_map.iter_rules():
        if re.sub(r"<(?:[^:>]+:)?[^>]+>", TASK, rule.rule) == path and "POST" in (
            rule.methods or set()
        ):
            doc = inspect.getdoc(inspect.unwrap(ui.app.view_functions[rule.endpoint]))
            assert doc and "---" in doc, path
            spec = yaml.safe_load(doc.split("---", 1)[1])
            return spec.get("responses", {})
    raise AssertionError(path)


class TestTheDocumentationDescribesTheRealAnswer:
    @pytest.mark.parametrize(
        "route",
        ["/api/submit", f"/api/tasks/{TASK}/submit", f"/api/tasks/{TASK}/extend"],
    )
    def test_413_is_documented_with_the_envelope_that_is_sent(
        self, ui: WebFeedbackUI, route: str
    ) -> None:
        responses = _documented_responses(ui, route)
        assert 413 in responses, f"{route}: 413 is not documented"
        properties = responses[413]["schema"]["properties"]
        assert {"success", "status", "error", "message"} <= set(properties)
        assert properties["error"].get("enum") == ["payload_too_large"] or (
            "payload_too_large" in str(properties["error"])
        )

    def test_no_route_docstring_names_a_limit_constant_that_does_not_exist(
        self,
    ) -> None:
        text = (PACKAGE / "web_ui_routes" / "feedback.py").read_text(encoding="utf-8")
        assert "_FEEDBACK_PAYLOAD_LIMIT_BYTES" not in text
