"""R789 — a request body that is not a JSON object is the caller's mistake, not a server fault.

Nine write routes read a JSON body, and each read it its own way:

* ``/api/update-language``, ``/api/update-notification-config``,
  ``/api/update-feedback-config``, ``/api/notify-new-tasks`` and ``/api/test-bark``
  used ``request.json or {}`` inside a broad ``try``.  A missing or non-JSON
  ``Content-Type``, an empty body, truncated JSON or an over-nested document made
  Werkzeug raise ``BadRequest`` / ``UnsupportedMediaType`` (or ``RecursionError``),
  and the handler's ``except Exception`` turned that into a ``500``.  A document that
  *was* JSON but not an object (``"s"``, ``123``, ``[1]``) gave ``500`` on three of
  them and ``200`` ("nothing to update") on two.
  ``curl -X POST .../api/update-language`` without ``-H 'Content-Type: …'`` therefore
  told the user the *server* was broken.
* ``/api/system/log-level``, ``/api/system/open-config-file``,
  ``/api/system/notifications/test`` and ``/api/tasks/<id>/extend`` took
  ``get_json(silent=True) or {}`` ("the body is optional").  ``silent=True`` only
  covers parse errors: a JSON scalar or array reached ``payload.get`` and crashed
  with an ``AttributeError`` — an *unhandled* ``500`` HTML page with a traceback on
  three of them — and an over-nested document escaped ``silent=True`` altogether
  because ``json.loads`` raises ``RecursionError``, not ``ValueError``.

The contract now lives in ``web_ui_routes/_request_body.py``:

* a route that needs a body calls ``require_json_object()`` *before* its own ``try`` —
  anything that is not a JSON object answers ``400`` with the same
  ``{"status": "error", "error": "invalid_json" | "invalid_body", "message": …}``
  that ``/api/update`` has always used;
* a route whose body is optional calls ``optional_json_object()`` — whatever is not
  a JSON object counts as "no body", exactly what ``silent=True`` already meant for
  unparsable text.

``TestNoHandlerParsesTheBodyItself`` keeps the next route from going back to
``request.json or {}``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent.web_ui import WebFeedbackUI

SRC = Path(__file__).resolve().parent.parent / "src" / "ai_intervention_agent"

TASK_ID = "r789-task"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

STRICT_ROUTES = [
    "/api/update-language",
    "/api/update-notification-config",
    "/api/update-feedback-config",
    "/api/notify-new-tasks",
    "/api/test-bark",
]
LENIENT_ROUTES = [
    "/api/system/log-level",
    "/api/system/open-config-file",
    "/api/system/notifications/test",
    f"/api/tasks/{TASK_ID}/extend",
]

DEEPLY_NESTED = b"[" * 100_000 + b"]" * 100_000

# (label, Content-Type, body)
NOT_PARSABLE: list[tuple[str, str | None, bytes]] = [
    ("no-body-no-content-type", None, b""),
    ("empty-json-body", "application/json", b""),
    ("truncated", "application/json", b"{"),
    ("plain-text", "text/plain", b"hello"),
    ("json-sent-as-text", "text/plain", b'{"language": "en"}'),
    ("utf16-bytes", "application/json", b"\xff\xfe\x00"),
    ("over-nested", "application/json", DEEPLY_NESTED),
]
NOT_AN_OBJECT: list[tuple[str, str | None, bytes]] = [
    ("string", "application/json", b'"s"'),
    ("number", "application/json", b"123"),
    ("boolean", "application/json", b"true"),
    ("null", "application/json", b"null"),
    ("array", "application/json", b"[1]"),
]


def _ids(cases: list[tuple[str, str | None, bytes]]) -> list[str]:
    return [label for label, _, _ in cases]


@pytest.fixture(scope="module")
def client() -> FlaskClient:
    ui = WebFeedbackUI(
        prompt="r789",
        task_id=TASK_ID,
        auto_resubmit_timeout=0,
        port=19789,
    )
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False
    return ui.app.test_client()


def _post(
    client: FlaskClient, route: str, content_type: str | None, body: bytes
) -> Any:
    kwargs: dict[str, Any] = {"data": body, "environ_overrides": LOOPBACK}
    if content_type is not None:
        kwargs["content_type"] = content_type
    return client.post(route, **kwargs)


@contextmanager
def _config_untouched() -> Iterator[list[MagicMock]]:
    """Replace ``get_config`` where the strict routes use it; a refused body must not reach it."""
    with ExitStack() as stack:
        spies = [
            stack.enter_context(patch(f"{module}.get_config"))
            for module in (
                "ai_intervention_agent.web_ui",
                "ai_intervention_agent.web_ui_routes.notification",
            )
        ]
        yield spies


# ---------------------------------------------------------------------------
# A body the route cannot read as a JSON object -> 400, nothing happens
# ---------------------------------------------------------------------------
class TestStrictRoutesRefuseABodyThatIsNotAJsonObject:
    @pytest.mark.parametrize("route", STRICT_ROUTES)
    @pytest.mark.parametrize(
        ("label", "content_type", "body"), NOT_PARSABLE, ids=_ids(NOT_PARSABLE)
    )
    def test_unparsable_body_is_invalid_json(
        self,
        client: FlaskClient,
        route: str,
        label: str,
        content_type: str | None,
        body: bytes,
    ) -> None:
        with _config_untouched() as spies:
            resp = _post(client, route, content_type, body)

        assert resp.status_code == 400, (route, label, resp.get_data(as_text=True))
        assert resp.mimetype == "application/json"
        payload = resp.get_json()
        assert payload["status"] == "error"
        assert payload["error"] == "invalid_json"
        assert payload["message"]
        for spy in spies:
            spy.assert_not_called()

    @pytest.mark.parametrize("route", STRICT_ROUTES)
    @pytest.mark.parametrize(
        ("label", "content_type", "body"), NOT_AN_OBJECT, ids=_ids(NOT_AN_OBJECT)
    )
    def test_json_that_is_not_an_object_is_invalid_body(
        self,
        client: FlaskClient,
        route: str,
        label: str,
        content_type: str | None,
        body: bytes,
    ) -> None:
        with _config_untouched() as spies:
            resp = _post(client, route, content_type, body)

        assert resp.status_code == 400, (route, label, resp.get_data(as_text=True))
        assert resp.mimetype == "application/json"
        payload = resp.get_json()
        assert payload["status"] == "error"
        assert payload["error"] == "invalid_body"
        assert payload["message"]
        for spy in spies:
            spy.assert_not_called()

    def test_the_message_follows_the_request_language(
        self, client: FlaskClient
    ) -> None:
        resp = client.post(
            "/api/update-language",
            data=b"[1]",
            content_type="application/json",
            headers={"Accept-Language": "zh-CN"},
        )
        assert resp.status_code == 400
        assert "JSON" in resp.get_json()["message"]
        assert "请求体" in resp.get_json()["message"]

    def test_a_refused_language_body_leaves_the_stored_language_alone(
        self, client: FlaskClient
    ) -> None:
        """``null`` used to reach ``data.get("language", "auto")`` as ``{}`` and reset the language."""
        with patch("ai_intervention_agent.web_ui.get_config") as get_config:
            resp = client.post(
                "/api/update-language", data=b"null", content_type="application/json"
            )
        assert resp.status_code == 400
        get_config.return_value.update_section.assert_not_called()


# ---------------------------------------------------------------------------
# A real JSON object keeps meaning what it meant
# ---------------------------------------------------------------------------
class TestAnObjectStillGoesThroughTheHandler:
    def test_language_object_without_language_means_auto(
        self, client: FlaskClient
    ) -> None:
        with patch("ai_intervention_agent.web_ui.get_config") as get_config:
            resp = client.post("/api/update-language", json={})
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "success", "language": "auto"}
        get_config.return_value.update_section.assert_called_once_with(
            "web_ui", {"language": "auto"}
        )

    def test_language_is_still_checked_against_the_whitelist(
        self, client: FlaskClient
    ) -> None:
        resp = client.post("/api/update-language", json={"language": "fr"})
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_notification_config_object_without_fields_is_a_no_op(
        self, client: FlaskClient
    ) -> None:
        with _config_untouched():
            resp = client.post("/api/update-notification-config", json={})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_feedback_config_object_without_fields_is_a_no_op(
        self, client: FlaskClient
    ) -> None:
        with _config_untouched():
            resp = client.post("/api/update-feedback-config", json={})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_notify_without_task_ids_is_skipped(self, client: FlaskClient) -> None:
        resp = client.post("/api/notify-new-tasks", json={})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "skipped"

    def test_bark_test_still_demands_a_device_key(self, client: FlaskClient) -> None:
        resp = client.post("/api/test-bark", json={})
        assert resp.status_code == 400
        assert "Device Key" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# Routes whose body is optional: what is not an object is "no body"
# ---------------------------------------------------------------------------
@contextmanager
def _side_effects_stubbed(route: str) -> Iterator[None]:
    """Keep the optional-body routes from opening an editor / notifying anyone."""
    with ExitStack() as stack:
        if route.endswith("/open-config-file"):
            stack.enter_context(
                patch("ai_intervention_agent.web_ui_routes.system.subprocess.Popen")
            )
            stack.enter_context(
                patch(
                    "ai_intervention_agent.web_ui_routes.system._detect_default_editor",
                    return_value=("/usr/local/bin/cursor", []),
                )
            )
        elif route.endswith("/notifications/test"):
            from ai_intervention_agent.notification_models import NotificationType

            manager = MagicMock()
            manager.config.enabled = True
            manager.config.bark_enabled = True
            manager.config.web_enabled = True
            manager.config.sound_enabled = True
            manager.config.sound_mute = False
            manager.config.system_enabled = True
            manager.send_notification.return_value = "evt-r789"
            stack.enter_context(
                patch.multiple(
                    "ai_intervention_agent.web_ui_routes.notification",
                    notification_manager=manager,
                    NotificationType=NotificationType,
                )
            )
        yield


class TestOptionalBodyRoutesTreatWhatIsNotAnObjectAsNoBody:
    @pytest.mark.parametrize("route", LENIENT_ROUTES)
    @pytest.mark.parametrize(
        ("label", "content_type", "body"),
        NOT_PARSABLE + NOT_AN_OBJECT,
        ids=_ids(NOT_PARSABLE + NOT_AN_OBJECT),
    )
    def test_same_answer_as_for_no_body(
        self,
        client: FlaskClient,
        route: str,
        label: str,
        content_type: str | None,
        body: bytes,
    ) -> None:
        with _side_effects_stubbed(route):
            baseline = _post(client, route, None, b"")
        with _side_effects_stubbed(route):
            resp = _post(client, route, content_type, body)

        assert resp.status_code < 500, (route, label, resp.get_data(as_text=True)[:200])
        assert resp.status_code == baseline.status_code
        assert resp.mimetype == "application/json", (route, label)
        assert resp.get_json() == baseline.get_json()


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------
class TestTheHelper:
    @pytest.mark.parametrize(
        ("label", "content_type", "body"),
        NOT_PARSABLE + NOT_AN_OBJECT,
        ids=_ids(NOT_PARSABLE + NOT_AN_OBJECT),
    )
    def test_optional_never_raises(
        self,
        client: FlaskClient,
        label: str,
        content_type: str | None,
        body: bytes,
    ) -> None:
        from ai_intervention_agent.web_ui_routes._request_body import (
            optional_json_object,
        )

        app = client.application
        headers = {"Content-Type": content_type} if content_type else {}
        with app.test_request_context("/x", method="POST", data=body, headers=headers):
            assert optional_json_object() == {}

    def test_optional_returns_the_object(self, client: FlaskClient) -> None:
        from ai_intervention_agent.web_ui_routes._request_body import (
            optional_json_object,
        )

        with client.application.test_request_context(
            "/x", method="POST", json={"seconds": 60}
        ):
            assert optional_json_object() == {"seconds": 60}

    def test_require_returns_the_object(self, client: FlaskClient) -> None:
        from ai_intervention_agent.web_ui_routes._request_body import (
            require_json_object,
        )

        with client.application.test_request_context(
            "/x", method="POST", json={"a": [1, {"b": None}]}
        ):
            assert require_json_object() == {"a": [1, {"b": None}]}

    def test_require_raises_a_400_that_renders_itself_as_json(
        self, client: FlaskClient
    ) -> None:
        """No ``errorhandler`` has to be registered for the answer to be JSON."""
        from ai_intervention_agent.web_ui_routes._request_body import (
            InvalidRequestBody,
            require_json_object,
        )

        with client.application.test_request_context(
            "/x", method="POST", data=b"[]", content_type="application/json"
        ):
            with pytest.raises(InvalidRequestBody) as caught:
                require_json_object()
            response = caught.value.get_response()

        assert caught.value.code == 400
        assert response.status_code == 400
        assert response.mimetype == "application/json"
        assert response.get_json()["error"] == "invalid_body"

    def test_a_refused_body_does_not_poison_the_next_request(
        self, client: FlaskClient
    ) -> None:
        refused = client.post(
            "/api/update-language", data=DEEPLY_NESTED, content_type="application/json"
        )
        assert refused.status_code == 400
        with patch("ai_intervention_agent.web_ui.get_config"):
            ok = client.post("/api/update-language", json={"language": "en"})
        assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Keep it that way
# ---------------------------------------------------------------------------
class _BodyReadFinder(ast.NodeVisitor):
    """Collect ``request.json`` and ``….get_json(…)`` with the innermost function name."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.hits: list[tuple[str, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr == "json"
            and isinstance(node.value, ast.Name)
            and node.value.id == "request"
        ):
            self.hits.append(
                (self.stack[-1] if self.stack else "<module>", node.lineno)
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get_json":
            self.hits.append(
                (self.stack[-1] if self.stack else "<module>", node.lineno)
            )
        self.generic_visit(node)


class TestNoHandlerParsesTheBodyItself:
    #: Handlers that were written to answer a bad body themselves, with their own
    #: messages and ``try`` / ``isinstance`` blocks.  A new route does not belong here:
    #: it takes ``require_json_object()`` or ``optional_json_object()``.
    VETTED = {
        ("feedback.py", "submit_feedback"),
        ("feedback.py", "update_content"),
        ("task.py", "create_task"),
    }

    def test_only_vetted_handlers_read_the_body_directly(self) -> None:
        offenders: list[str] = []
        files = [SRC / "web_ui.py", *sorted((SRC / "web_ui_routes").glob("*.py"))]
        for path in files:
            if path.name == "_request_body.py":
                continue
            finder = _BodyReadFinder()
            finder.visit(ast.parse(path.read_text(encoding="utf-8")))
            offenders.extend(
                f"{path.name}:{line} in {func}()"
                for func, line in finder.hits
                if (path.name, func) not in self.VETTED
            )

        assert not offenders, (
            "Read the body through web_ui_routes/_request_body.py "
            "(require_json_object / optional_json_object); `request.json or {}` and "
            "`get_json(silent=True) or {}` turn a client mistake into a 500 or an "
            "unhandled AttributeError:\n  " + "\n  ".join(offenders)
        )

    def test_the_vetted_handlers_still_exist(self) -> None:
        """A stale entry would silently exempt a future handler of the same name."""
        for filename, func in sorted(self.VETTED):
            tree = ast.parse(
                (SRC / "web_ui_routes" / filename).read_text(encoding="utf-8")
            )
            names = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
            }
            assert func in names, (filename, func)
