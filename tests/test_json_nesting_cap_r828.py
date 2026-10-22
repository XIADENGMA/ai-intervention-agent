"""R828 — a JSON body nested far deeper than any client sends is refused, on every interpreter.

Python 3.14 made ``json.loads`` accept documents nested about 100 000 levels deep (the C
parser's limit now follows the C stack; 3.11–3.13 raise ``RecursionError`` past a few
thousand).  The routes leaned on that limit as a safety net — "an over-nested document is
unparsable" is what R789 / R799 pinned — and on 3.14 the net is gone:

* ``str()`` / ``repr()`` of such a document is quadratic and finally overflows the C stack.
  ``/api/notify-new-tasks`` (``str(item)``), ``/api/submit``, ``/api/test-bark`` ... kept
  a Flask thread busy for 0.6–1.1 s on a 120–200 kB body (idle machine; the C code keeps
  the GIL, so a ``/api/health`` probe sent meanwhile waited 0.66 s and SSE keep-alives
  would too), and ``/api/update-language`` /
  ``/api/update-notification-config`` / ``/api/test-bark`` /
  ``/api/system/open-config-file`` answered ``500 RecursionError: Stack overflow``.
* Nothing else bounded the depth, so a document just *over* what a client could ever
  send (33 levels) was read like any other: ``/api/submit`` took a form field
  ``selected_options="[[[[…]]]]"`` and kept its repr as the selected option.

``web_ui_routes/_request_body.py`` now bounds the depth where every body is read:

* ``MAX_JSON_NESTING`` (32 containers) — no client sends more than 5;
* the app's JSON provider (``BoundedJSONProvider``) refuses anything deeper with the
  ``ValueError`` Werkzeug already maps to "not JSON", and turns the interpreter's own
  ``RecursionError`` into the same ``ValueError`` — so ``require_json_object()`` answers
  ``400 invalid_json`` and ``optional_json_object()`` means "no body" on **every**
  interpreter, which is what R789 promised;
* the form field that carries JSON text on ``/api/submit`` (``selected_options``) uses
  ``json_nesting_exceeds`` on the parsed value.  (The task-scoped submit needs nothing:
  it has always refused everything but a flat array of strings.)

The same sweep found a bug that does not depend on the interpreter: the string-typed
notification settings (``barkDeviceKey``, ``barkUrl``, ``barkIcon``, ``barkAction``,
``barkUrlTemplate``, ``webIcon``) ran every value through ``str()``, so a JSON list or
object was **saved** as its Python repr (``"['abc']"``) and the route said "updated" —
although the route's own OpenAPI says a value of the wrong type is
``400 invalid_value`` and that nothing is changed.  Structured values are refused now;
numbers and ``null`` keep their old meaning (``12345`` → ``"12345"``, ``null`` → ``""``).
"""

from __future__ import annotations

import json
import re
import threading
import time
import tracemalloc
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent.notification_manager import (
    NotificationConfig,
    NotificationManager,
)
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import _request_body as body_contract

LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
TASK_ID = "r828-task"

STRICT_ROUTES = [
    "/api/update-language",
    "/api/update-notification-config",
    "/api/update-feedback-config",
    "/api/notify-new-tasks",
    "/api/test-bark",
]


def chain(levels: int) -> bytes:
    """``levels`` arrays inside each other: ``[[[]]]`` for 3."""
    return b"[" * levels + b"]" * levels


def document(depth: int, **fields: Any) -> bytes:
    """A JSON object whose nesting is exactly ``depth`` containers (``depth`` >= 2)."""
    extra = json.dumps(fields)[1:-1]
    comma = ", " if extra else ""
    return b'{"pad": ' + chain(depth - 1) + (comma + extra).encode() + b"}"


def cap() -> int:
    return int(body_contract.MAX_JSON_NESTING)


# ---------------------------------------------------------------------------
# The helpers
# ---------------------------------------------------------------------------
class TestJsonNestingExceeds:
    @pytest.mark.parametrize("value", [1, "s", None, True, 1.5])
    def test_a_scalar_has_no_nesting(self, value: object) -> None:
        assert body_contract.json_nesting_exceeds(value, 0) is False

    def test_a_container_counts_as_one_level(self) -> None:
        assert body_contract.json_nesting_exceeds([], 1) is False
        assert body_contract.json_nesting_exceeds({}, 1) is False
        assert body_contract.json_nesting_exceeds([[]], 1) is True
        assert body_contract.json_nesting_exceeds({"a": {}}, 1) is True
        assert body_contract.json_nesting_exceeds([[]], 2) is False
        assert body_contract.json_nesting_exceeds([], 0) is True
        assert body_contract.json_nesting_exceeds({}, 0) is True

    def test_arrays_and_objects_mix(self) -> None:
        value = {"a": [{"b": [1]}]}  # dict, list, dict, list = 4
        assert body_contract.json_nesting_exceeds(value, 4) is False
        assert body_contract.json_nesting_exceeds(value, 3) is True

    def test_it_is_the_deepest_branch_that_counts(self) -> None:
        wide: list[Any] = [[] for _ in range(50_000)]
        wide.append([[[]]])
        assert body_contract.json_nesting_exceeds(wide, 4) is False
        assert body_contract.json_nesting_exceeds(wide, 3) is True

    def test_a_deep_value_after_shallow_siblings_in_an_object_is_found(self) -> None:
        value = {"a": 1, "b": [], "c": {"d": {"e": [[]]}}}  # 5 containers deep
        assert body_contract.json_nesting_exceeds(value, 5) is False
        assert body_contract.json_nesting_exceeds(value, 4) is True

    def test_the_memory_it_needs_follows_the_depth_not_the_width(self) -> None:
        """A 10 MB body of 3.3 million ``[]`` must not cost another 160 MB to look at."""
        wide: list[Any] = [[] for _ in range(300_000)]
        tracemalloc.start()
        try:
            before = tracemalloc.get_traced_memory()[0]
            assert body_contract.json_nesting_exceeds(wide, 2) is False
            extra = tracemalloc.get_traced_memory()[1] - before
        finally:
            tracemalloc.stop()
        assert extra < 200_000, f"{extra} bytes"

    def test_a_wide_document_is_not_deep(self) -> None:
        wide = [[i] for i in range(100_000)]
        assert body_contract.json_nesting_exceeds(wide, 2) is False

    def test_a_structure_far_deeper_than_the_recursion_limit_does_not_raise(
        self,
    ) -> None:
        deep: list[Any] = []
        for _ in range(300_000):
            deep = [deep]
        started = time.monotonic()
        assert body_contract.json_nesting_exceeds(deep, 32) is True
        assert time.monotonic() - started < 1.0

    def test_the_default_limit_is_the_documented_one(self) -> None:
        deepest_ok: Any = 1
        for _ in range(cap()):
            deepest_ok = [deepest_ok]
        assert body_contract.json_nesting_exceeds(deepest_ok) is False
        assert body_contract.json_nesting_exceeds([deepest_ok]) is True

    def test_the_number_in_the_openapi_text_is_the_real_limit(self) -> None:
        from ai_intervention_agent.web_ui_routes import notification as routes

        text = Path(routes.__file__).read_text(encoding="utf-8")
        documented = {int(n) for n in re.findall(r"嵌套超过 (\d+) 层", text)}
        assert documented == {cap()}


class TestTheProvider:
    def _provider(self) -> Any:
        from flask import Flask

        return body_contract.BoundedJSONProvider(Flask("r828"))

    def test_it_reads_what_the_default_provider_reads(self) -> None:
        provider = self._provider()
        assert provider.loads('{"a": [1, {"b": null}]}') == {"a": [1, {"b": None}]}
        assert provider.loads(b"[1, 2]") == [1, 2]

    def test_a_document_at_the_limit_is_read(self) -> None:
        text = (b"[" * cap() + b"]" * cap()).decode()
        assert self._provider().loads(text) is not None

    def test_a_document_one_level_over_the_limit_is_refused_with_a_valueerror(
        self,
    ) -> None:
        text = (b"[" * (cap() + 1) + b"]" * (cap() + 1)).decode()
        with pytest.raises(ValueError, match="nest"):
            self._provider().loads(text)

    def test_what_the_interpreter_cannot_read_is_a_valueerror_too(self) -> None:
        """``RecursionError`` is not a ``ValueError``; Werkzeug's ``silent=True`` needs one."""
        text = (b"[" * 3_000_000 + b"]" * 3_000_000).decode()
        with pytest.raises(ValueError, match="nest"):
            self._provider().loads(text)

    def test_a_syntax_error_is_still_a_jsondecodeerror(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            self._provider().loads("{")

    def test_the_app_uses_it(self, client: FlaskClient) -> None:
        assert isinstance(client.application.json, body_contract.BoundedJSONProvider)


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r828", task_id=TASK_ID, auto_resubmit_timeout=0, port=19828
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    ui.feedback_result = None
    return ui.app.test_client()


def _post(client: FlaskClient, route: str, body: bytes) -> Any:
    return client.post(
        route,
        data=body,
        content_type="application/json",
        environ_overrides=LOOPBACK,
    )


@contextmanager
def _config_untouched() -> Iterator[None]:
    with (
        patch("ai_intervention_agent.web_ui.get_config") as in_app,
        patch(
            "ai_intervention_agent.web_ui_routes.notification.get_config"
        ) as in_routes,
    ):
        yield
        in_app.return_value.update_section.assert_not_called()
        in_routes.return_value.update_section.assert_not_called()


class TestAnOverNestedBodyIsInvalidJsonEverywhere:
    @pytest.mark.parametrize("route", STRICT_ROUTES)
    def test_an_array_one_level_over_the_limit(
        self, client: FlaskClient, route: str
    ) -> None:
        with _config_untouched():
            resp = _post(client, route, chain(cap() + 1))
        assert resp.status_code == 400, resp.get_data(as_text=True)[:200]
        assert resp.get_json()["error"] == "invalid_json"

    @pytest.mark.parametrize("route", STRICT_ROUTES)
    def test_an_object_one_level_over_the_limit(
        self, client: FlaskClient, route: str
    ) -> None:
        with _config_untouched():
            resp = _post(client, route, document(cap() + 1, language="en"))
        assert resp.status_code == 400, resp.get_data(as_text=True)[:200]
        assert resp.get_json()["error"] == "invalid_json"

    @pytest.mark.parametrize("route", STRICT_ROUTES)
    def test_sixty_thousand_levels_are_refused_quickly(
        self, client: FlaskClient, route: str
    ) -> None:
        started = time.monotonic()
        with _config_untouched():
            resp = _post(client, route, chain(60_000))
        elapsed = time.monotonic() - started
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_json"
        assert elapsed < 2.0, f"took {elapsed:.1f}s"

    def test_a_deep_value_under_a_known_key_never_reaches_str(
        self, client: FlaskClient
    ) -> None:
        """The shape that made 3.14 answer ``500 Stack overflow`` / hold a thread for seconds."""
        body = b'{"language": ' + chain(60_000) + b"}"
        started = time.monotonic()
        with _config_untouched():
            resp = _post(client, "/api/update-language", body)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_json"
        assert time.monotonic() - started < 2.0

    def test_the_task_ids_of_a_notify_request_are_not_stringified_when_deep(
        self, client: FlaskClient
    ) -> None:
        body = b'{"taskIds": [' + chain(60_000) + b"]}"
        started = time.monotonic()
        resp = _post(client, "/api/notify-new-tasks", body)
        assert resp.status_code == 400
        assert time.monotonic() - started < 2.0

    def test_a_document_at_the_limit_still_goes_through_the_handler(
        self, client: FlaskClient
    ) -> None:
        with patch("ai_intervention_agent.web_ui.get_config") as get_config:
            resp = _post(client, "/api/update-language", document(cap(), language="en"))
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        get_config.return_value.update_section.assert_called_once_with(
            "web_ui", {"language": "en"}
        )

    def test_an_optional_body_that_is_too_deep_means_no_body(
        self, client: FlaskClient
    ) -> None:
        baseline = client.post("/api/system/log-level", environ_overrides=LOOPBACK)
        over = _post(
            client, "/api/system/log-level", document(cap() + 1, level="debug")
        )
        assert over.status_code == baseline.status_code
        assert over.get_json() == baseline.get_json()

    def test_optional_json_object_returns_an_empty_dict_for_it(
        self, client: FlaskClient
    ) -> None:
        with client.application.test_request_context(
            "/x",
            method="POST",
            data=document(cap() + 1, a=1),
            content_type="application/json",
        ):
            assert body_contract.optional_json_object() == {}

    def test_optional_json_object_still_holds_without_the_provider(self) -> None:
        """An app that did not install the provider (a test's throw-away one) and whose
        interpreter gives up with ``RecursionError``: ``silent=True`` swallows only
        ``ValueError``, so the helper catches it itself."""
        from flask import Flask
        from flask.json.provider import DefaultJSONProvider

        class GivesUp(DefaultJSONProvider):
            def loads(self, s: str | bytes, **kwargs: Any) -> Any:
                raise RecursionError("maximum recursion depth exceeded")

        app = Flask("r828-bare")
        app.json = GivesUp(app)
        with app.test_request_context(
            "/x", method="POST", data=b'{"a": 1}', content_type="application/json"
        ):
            assert body_contract.optional_json_object() == {}

    def test_require_json_object_raises_invalid_json_for_it(
        self, client: FlaskClient
    ) -> None:
        with client.application.test_request_context(
            "/x",
            method="POST",
            data=document(cap() + 1, a=1),
            content_type="application/json",
        ):
            with pytest.raises(body_contract.InvalidRequestBody) as caught:
                body_contract.require_json_object()
            response = caught.value.get_response()
        assert response.get_json()["error"] == "invalid_json"


# ---------------------------------------------------------------------------
# The form field that carries JSON text
# ---------------------------------------------------------------------------
class TestSelectedOptionsThatAreTooDeep:
    def test_submit_selects_nothing(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        resp = client.post(
            "/api/submit",
            data={
                "feedback_text": "t",
                "selected_options": (b"[" * 100 + b"]" * 100).decode(),
            },
            environ_base=LOOPBACK,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert ui.feedback_result is not None
        assert ui.feedback_result["selected_options"] == []
        assert ui.feedback_result["user_input"] == "t"

    def test_the_form_helper_selects_nothing(self) -> None:
        from ai_intervention_agent.web_ui_routes import feedback as feedback_routes

        assert (
            feedback_routes._selected_options_from_form(
                (b"[" * 100 + b"]" * 100).decode()
            )
            == []
        )

    def test_a_readable_array_is_still_read(self) -> None:
        from ai_intervention_agent.web_ui_routes import feedback as feedback_routes

        assert feedback_routes._selected_options_from_form('["a", "b", "a"]') == [
            "a",
            "b",
        ]

    def test_the_task_scoped_submit_answers_400(self, client: FlaskClient) -> None:
        """A pin, not a fix: that route has always taken a flat array of strings only."""
        from ai_intervention_agent.task_queue_singleton import get_task_queue

        queue = get_task_queue()
        queue.remove_task("r828-scoped")
        queue.add_task(
            task_id="r828-scoped",
            prompt="p",
            predefined_options=["x"],
            auto_resubmit_timeout=0,
        )
        try:
            resp = client.post(
                "/api/tasks/r828-scoped/submit",
                environ_base=LOOPBACK,
                data={
                    "feedback_text": "t",
                    "selected_options": (b"[" * 100 + b"]" * 100).decode(),
                },
            )
            assert resp.status_code == 400, resp.get_data(as_text=True)[:200]
            assert resp.get_json()["success"] is False
        finally:
            queue.remove_task("r828-scoped")


# ---------------------------------------------------------------------------
# String-typed notification settings
# ---------------------------------------------------------------------------
STRING_FIELDS = [
    ("webIcon", "web_icon"),
    ("barkUrl", "bark_url"),
    ("barkDeviceKey", "bark_device_key"),
    ("barkIcon", "bark_icon"),
    ("barkAction", "bark_action"),
    ("barkUrlTemplate", "bark_url_template"),
]
# ``barkAction`` is an enum (none / url / copy): any other text is replaced by the
# default with a warning, so the free-text checks leave it out.
FREE_TEXT_FIELDS = [pair for pair in STRING_FIELDS if pair[0] != "barkAction"]
STRUCTURED: list[Any] = [["abc"], {"k": 1}, [[["deep"]]], []]


def _manager() -> NotificationManager:
    mgr = object.__new__(NotificationManager)
    mgr.config = NotificationConfig()
    mgr._config_lock = threading.RLock()
    return mgr


@contextmanager
def _route_with(mgr: NotificationManager) -> Iterator[MagicMock]:
    module = "ai_intervention_agent.web_ui_routes.notification"
    with (
        patch.multiple(module, notification_manager=mgr, NOTIFICATION_AVAILABLE=True),
        patch(f"{module}.get_config") as get_config,
    ):
        get_config.return_value.get_section.return_value = {}
        yield get_config.return_value


class TestAStringSettingRefusesAStructuredValue:
    @pytest.mark.parametrize(("request_key", "field"), STRING_FIELDS)
    @pytest.mark.parametrize("bad", STRUCTURED, ids=repr)
    def test_400_names_the_field_and_changes_nothing(
        self, client: FlaskClient, request_key: str, field: str, bad: Any
    ) -> None:
        mgr = _manager()
        before = mgr.config.model_dump()
        with _route_with(mgr) as config_mgr:
            resp = client.post(
                "/api/update-notification-config",
                json={"webIcon": "changed.png", request_key: bad},
            )

        assert resp.status_code == 400, resp.get_data(as_text=True)
        payload = resp.get_json()
        assert payload["status"] == "error"
        assert payload["error"] == "invalid_value"
        assert payload["fields"] == [field]
        assert field in payload["message"]
        assert mgr.config.model_dump() == before
        config_mgr.update_section.assert_not_called()

    def test_every_offending_field_is_named_once(self, client: FlaskClient) -> None:
        mgr = _manager()
        with _route_with(mgr):
            resp = client.post(
                "/api/update-notification-config",
                json={"barkUrl": ["x"], "barkDeviceKey": {"a": 1}, "webIcon": "ok.png"},
            )
        assert resp.status_code == 400
        assert resp.get_json()["fields"] == ["bark_device_key", "bark_url"]

    def test_the_snake_case_spelling_is_checked_too(self, client: FlaskClient) -> None:
        mgr = _manager()
        with _route_with(mgr) as config_mgr:
            resp = client.post(
                "/api/update-notification-config", json={"bark_device_key": ["abc"]}
            )
        assert resp.status_code == 400
        assert resp.get_json()["fields"] == ["bark_device_key"]
        config_mgr.update_section.assert_not_called()

    def test_the_message_follows_the_request_language(
        self, client: FlaskClient
    ) -> None:
        with _route_with(_manager()):
            resp = client.post(
                "/api/update-notification-config",
                json={"barkDeviceKey": ["abc"]},
                headers={"Accept-Language": "zh-CN"},
            )
        assert resp.status_code == 400
        assert "bark_device_key" in resp.get_json()["message"]
        assert "无效" in resp.get_json()["message"]

    def test_the_refused_value_is_not_echoed(self, client: FlaskClient) -> None:
        """A device key is a secret; the answer names the field, never the value."""
        with _route_with(_manager()):
            resp = client.post(
                "/api/update-notification-config",
                json={"barkDeviceKey": ["s3cr3t-key"]},
            )
        assert "s3cr3t-key" not in resp.get_data(as_text=True)


class TestWhatAStringSettingAlwaysAccepted:
    @pytest.mark.parametrize(("request_key", "field"), FREE_TEXT_FIELDS)
    def test_a_string_is_stored(
        self, client: FlaskClient, request_key: str, field: str
    ) -> None:
        mgr = _manager()
        with _route_with(mgr) as config_mgr:
            resp = client.post(
                "/api/update-notification-config", json={request_key: "value-1"}
            )
        assert resp.status_code == 200
        assert getattr(mgr.config, field) == "value-1"
        saved = config_mgr.update_section.call_args.args[1]
        assert saved[field] == "value-1"

    def test_a_number_is_stored_as_its_text(self, client: FlaskClient) -> None:
        mgr = _manager()
        with _route_with(mgr):
            resp = client.post(
                "/api/update-notification-config", json={"barkDeviceKey": 12345}
            )
        assert resp.status_code == 200
        assert mgr.config.bark_device_key == "12345"

    def test_the_enum_setting_keeps_its_values(self, client: FlaskClient) -> None:
        mgr = _manager()
        with _route_with(mgr):
            resp = client.post(
                "/api/update-notification-config", json={"barkAction": "url"}
            )
        assert resp.status_code == 200
        assert mgr.config.bark_action == "url"

    @pytest.mark.parametrize(("request_key", "field"), FREE_TEXT_FIELDS)
    def test_null_clears_the_value(
        self, client: FlaskClient, request_key: str, field: str
    ) -> None:
        mgr = _manager()
        setattr(mgr.config, field, "old")
        with _route_with(mgr):
            resp = client.post(
                "/api/update-notification-config", json={request_key: None}
            )
        assert resp.status_code == 200
        assert getattr(mgr.config, field) == ""
