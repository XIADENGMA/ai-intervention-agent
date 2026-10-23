"""R797 — a value the caller got wrong is a 400, never a 500 with a traceback in the log.

R789 made the write routes agree about the *shape* of the body and R790 made
``/api/update-notification-config`` refuse a value its model cannot hold.  A sweep that
sends every extreme number and every JSON type — one field at a time, field names taken
from the route sources — to every write route (20 routes, ~33 000 requests) still found
three routes that answer ``500 "Update failed"`` and log a traceback for what is plainly
the caller's mistake:

* ``POST /api/update-feedback-config``
  - ``frontend_countdown`` = ``1e999`` / ``-Infinity``: ``int(float("inf"))`` raises
    ``OverflowError``; the handler only expected ``TypeError`` and ``ValueError``;
  - ``resubmit_prompt`` / ``prompt_suffix`` = ``5``, ``true``, ``[1]``, ``{"a": 1}``:
    ``truncate_string`` calls ``.strip()`` on it → ``AttributeError``.
* ``POST /api/update-notification-config``
  - ``soundVolume`` / ``webTimeout`` = an integer with more than 308 digits:
    ``float(10**400)`` raises ``OverflowError``.  ``1e999`` (same magnitude, written as a
    float) has always been clamped to the bound; the integer spelling of the same number
    crashed.
* ``POST /api/test-bark``
  - ``bark_device_key`` (and ``bark_url``, ``bark_icon``, ``bark_action``) that is not a
    string: the provider calls ``.strip()`` / ``.startswith()`` on it, logs
    ``Bark通知发送失败: 'int' object has no attribute 'strip'`` and the route answers
    ``500 "send failed, check the configuration"``.

Now:

* the two config routes answer ``400 {"status": "error", "error": "invalid_value",
  "fields": [...], "message": ...}`` (the envelope R790 introduced) and persist nothing —
  not even the valid fields of the same request;
* ``/api/update-notification-config`` clamps an out-of-range *integer* exactly like the
  same number written as a float;
* ``/api/test-bark`` refuses a non-string field before a provider is built and before
  anything leaves the machine.

``TestNoWriteRouteAnswers5xxForAnUnusableNumberOrType`` repeats the sweep (fewer values,
field names read from the handler's own file) so the next route is covered the day it is
written.
"""

from __future__ import annotations

import inspect
import re
import socket
import subprocess
import threading
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
from ai_intervention_agent.server_config import (
    PROMPT_SUFFIX_DEFAULT,
    RESUBMIT_PROMPT_DEFAULT,
)
from ai_intervention_agent.web_ui import WebFeedbackUI

LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
NOTIFICATION = "ai_intervention_agent.web_ui_routes.notification"


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r797", task_id="r797-task", auto_resubmit_timeout=0, port=19797
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture(scope="module")
def client(ui: WebFeedbackUI) -> FlaskClient:
    return ui.app.test_client()


def _manager() -> NotificationManager:
    mgr = object.__new__(NotificationManager)
    mgr.config = NotificationConfig()
    mgr._config_lock = threading.RLock()
    return mgr


@contextmanager
def _config_manager(section: dict[str, Any] | None = None) -> Iterator[MagicMock]:
    """The route runs against a config manager that records what is persisted."""
    with patch(f"{NOTIFICATION}.get_config") as get_config:
        get_config.return_value.get_section.return_value = dict(section or {})
        yield get_config.return_value


# ---------------------------------------------------------------------------
# /api/update-feedback-config
# ---------------------------------------------------------------------------
NOT_TEXT: list[Any] = [5, 1.5, -1, True, [1], ["a"], {"a": 1}]
DEFAULTS = {
    "resubmit_prompt": RESUBMIT_PROMPT_DEFAULT,
    "prompt_suffix": PROMPT_SUFFIX_DEFAULT,
}


class TestFeedbackConfigRoute:
    @pytest.mark.parametrize("literal", ["1e999", "-1e999", "Infinity", "-Infinity"])
    def test_an_infinite_countdown_is_a_400_not_a_500(
        self, client: FlaskClient, literal: str
    ) -> None:
        # Written as raw JSON text: ``json=`` would refuse to encode an infinity,
        # and ``1e999`` is how a caller can produce one.
        with _config_manager() as config_mgr:
            resp = client.post(
                "/api/update-feedback-config",
                data=f'{{"frontend_countdown": {literal}}}',
                content_type="application/json",
            )
        assert resp.status_code == 400, resp.get_data(as_text=True)
        payload = resp.get_json()
        assert payload["status"] == "error"
        assert payload["error"] == "invalid_value"
        assert payload["fields"] == ["frontend_countdown"]
        assert "frontend_countdown" in payload["message"]
        config_mgr.update_section.assert_not_called()

    def test_nan_was_always_refused_and_still_is(self, client: FlaskClient) -> None:
        with _config_manager() as config_mgr:
            resp = client.post(
                "/api/update-feedback-config",
                data='{"frontend_countdown": NaN}',
                content_type="application/json",
            )
        assert resp.status_code == 400, resp.get_data(as_text=True)
        assert resp.get_json()["error"] == "invalid_value"
        config_mgr.update_section.assert_not_called()

    @pytest.mark.parametrize("field", ["resubmit_prompt", "prompt_suffix"])
    @pytest.mark.parametrize("bad", NOT_TEXT, ids=repr)
    def test_a_prompt_that_is_not_text_is_a_400_not_a_500(
        self, client: FlaskClient, field: str, bad: Any
    ) -> None:
        with _config_manager() as config_mgr:
            resp = client.post("/api/update-feedback-config", json={field: bad})
        assert resp.status_code == 400, resp.get_data(as_text=True)
        payload = resp.get_json()
        assert payload["status"] == "error"
        assert payload["error"] == "invalid_value"
        assert payload["fields"] == [field]
        assert field in payload["message"]
        config_mgr.update_section.assert_not_called()

    def test_nothing_is_persisted_when_one_field_of_the_request_is_refused(
        self, client: FlaskClient
    ) -> None:
        with _config_manager({"frontend_countdown": 240}) as config_mgr:
            resp = client.post(
                "/api/update-feedback-config",
                json={"frontend_countdown": 60, "resubmit_prompt": 5},
            )
        assert resp.status_code == 400
        config_mgr.update_section.assert_not_called()

    def test_every_refused_field_is_named(self, client: FlaskClient) -> None:
        with _config_manager():
            resp = client.post(
                "/api/update-feedback-config",
                json={"resubmit_prompt": 5, "prompt_suffix": [1]},
            )
        assert resp.status_code == 400
        assert resp.get_json()["fields"] == ["prompt_suffix", "resubmit_prompt"]

    def test_the_message_follows_the_request_language(
        self, client: FlaskClient
    ) -> None:
        with _config_manager():
            resp = client.post(
                "/api/update-feedback-config",
                json={"prompt_suffix": 5},
                headers={"Accept-Language": "zh-CN"},
            )
        assert resp.status_code == 400
        assert "prompt_suffix" in resp.get_json()["message"]
        assert "无效" in resp.get_json()["message"]

    @pytest.mark.parametrize("bad", ["not-an-int", None, [], {}, "1e999"])
    def test_the_values_that_were_always_refused_still_are(
        self, client: FlaskClient, bad: Any
    ) -> None:
        with _config_manager() as config_mgr:
            resp = client.post(
                "/api/update-feedback-config", json={"frontend_countdown": bad}
            )
        assert resp.status_code == 400
        assert "frontend_countdown" in resp.get_json()["message"]
        config_mgr.update_section.assert_not_called()

    def test_what_was_always_accepted_is_still_accepted(
        self, client: FlaskClient
    ) -> None:
        with _config_manager({"frontend_countdown": 240}) as config_mgr:
            resp = client.post(
                "/api/update-feedback-config",
                json={
                    "frontend_countdown": 120,
                    "resubmit_prompt": "answer please",
                    "prompt_suffix": "\n-- suffix",
                },
            )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        section, payload = config_mgr.update_section.call_args.args
        assert section == "feedback"
        assert payload["frontend_countdown"] == 120
        assert payload["resubmit_prompt"] == "answer please"
        assert payload["prompt_suffix"] == "\n-- suffix"

    @pytest.mark.parametrize("field", ["resubmit_prompt", "prompt_suffix"])
    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_an_empty_prompt_still_means_the_default(
        self, client: FlaskClient, field: str, empty: Any
    ) -> None:
        with _config_manager({field: "custom"}) as config_mgr:
            resp = client.post("/api/update-feedback-config", json={field: empty})
        assert resp.status_code == 200
        _, payload = config_mgr.update_section.call_args.args
        assert payload[field] == DEFAULTS[field]


# ---------------------------------------------------------------------------
# /api/update-notification-config
# ---------------------------------------------------------------------------
HUGE = 10**400


class TestNotificationConfigRoute:
    @contextmanager
    def _route_with(self, mgr: NotificationManager) -> Iterator[MagicMock]:
        with (
            patch.multiple(
                NOTIFICATION, notification_manager=mgr, NOTIFICATION_AVAILABLE=True
            ),
            _config_manager({}) as config_mgr,
        ):
            yield config_mgr

    @pytest.mark.parametrize("key", ["soundVolume", "sound_volume"])
    def test_a_huge_integer_volume_is_clamped_like_1e999(
        self, client: FlaskClient, key: str
    ) -> None:
        for number, expected in ((HUGE, 1.0), (-HUGE, 0.0)):
            mgr = _manager()
            with self._route_with(mgr) as config_mgr:
                resp = client.post(
                    "/api/update-notification-config", json={key: number}
                )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            assert mgr.config.sound_volume == pytest.approx(expected)
            config_mgr.update_section.assert_called_once()

    @pytest.mark.parametrize("key", ["webTimeout", "web_timeout"])
    def test_a_huge_integer_timeout_is_clamped_like_1e999(
        self, client: FlaskClient, key: str
    ) -> None:
        for number, expected in ((HUGE, 600000), (-HUGE, 1)):
            mgr = _manager()
            with self._route_with(mgr):
                resp = client.post(
                    "/api/update-notification-config", json={key: number}
                )
            assert resp.status_code == 200, resp.get_data(as_text=True)
            assert mgr.config.web_timeout == expected

    def test_the_float_spelling_of_the_same_number_gives_the_same_result(
        self, client: FlaskClient
    ) -> None:
        mgr_int, mgr_float = _manager(), _manager()
        with self._route_with(mgr_int):
            client.post("/api/update-notification-config", json={"webTimeout": HUGE})
        with self._route_with(mgr_float):
            client.post(
                "/api/update-notification-config",
                data='{"webTimeout": 1e999}',
                content_type="application/json",
            )
        assert mgr_int.config.web_timeout == mgr_float.config.web_timeout == 600000

    @pytest.mark.parametrize("bad", ["abc", None, [], {}])
    def test_a_value_that_is_not_a_number_still_keeps_the_current_setting(
        self, client: FlaskClient, bad: Any
    ) -> None:
        mgr = _manager()
        mgr.config.web_timeout = 1234
        with self._route_with(mgr) as config_mgr:
            config_mgr.get_section.return_value = {"web_timeout": 1234}
            resp = client.post(
                "/api/update-notification-config", json={"webTimeout": bad}
            )
        assert resp.status_code == 200
        assert mgr.config.web_timeout == 1234


# ---------------------------------------------------------------------------
# /api/test-bark
# ---------------------------------------------------------------------------
@contextmanager
def _bark_provider_spy() -> Iterator[MagicMock]:
    """A provider class that must not even be built for a refused request."""
    with patch(f"{NOTIFICATION}.BarkNotificationProvider") as provider_cls:
        provider_cls.return_value.send.return_value = True
        with patch(f"{NOTIFICATION}._ensure_bark_provider_loaded"):
            yield provider_cls


class TestTestBarkRoute:
    @pytest.mark.parametrize(
        "field", ["bark_device_key", "bark_url", "bark_icon", "bark_action"]
    )
    @pytest.mark.parametrize("bad", NOT_TEXT, ids=repr)
    def test_a_field_that_is_not_text_is_a_400_before_any_provider_exists(
        self, client: FlaskClient, field: str, bad: Any
    ) -> None:
        body: dict[str, Any] = {"bark_device_key": "key", field: bad}
        with _bark_provider_spy() as provider_cls:
            resp = client.post("/api/test-bark", json=body)
        assert resp.status_code == 400, resp.get_data(as_text=True)
        payload = resp.get_json()
        assert payload["status"] == "error"
        assert payload["error"] == "invalid_value"
        assert payload["fields"] == [field]
        assert field in payload["message"]
        provider_cls.assert_not_called()

    def test_a_request_with_text_fields_still_reaches_the_provider(
        self, client: FlaskClient
    ) -> None:
        with _bark_provider_spy() as provider_cls:
            resp = client.post(
                "/api/test-bark",
                json={
                    "bark_url": "https://bark.example/push",
                    "bark_device_key": "device-key",
                    "bark_icon": "https://example/icon.png",
                    "bark_action": "none",
                },
            )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        provider_cls.return_value.send.assert_called_once()

    @pytest.mark.parametrize("empty", [None, "", False, 0, [], {}])
    def test_a_missing_device_key_is_still_a_400(
        self, client: FlaskClient, empty: Any
    ) -> None:
        with _bark_provider_spy() as provider_cls:
            resp = client.post("/api/test-bark", json={"bark_device_key": empty})
        assert resp.status_code == 400
        provider_cls.assert_not_called()

    def test_a_failed_send_is_still_reported_as_one(self, client: FlaskClient) -> None:
        """The refusal is about the *request*; a send that fails stays what it was."""
        with _bark_provider_spy() as provider_cls:
            provider_cls.return_value.send.return_value = False
            resp = client.post("/api/test-bark", json={"bark_device_key": "device-key"})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------
SWEEP_VALUES = [
    "1e999",  # float("inf"): int() raises OverflowError
    "-Infinity",  # the non-standard JSON constant Python's parser accepts
    "NaN",
    "1" + "0" * 400,  # an integer too big for a float: float() raises OverflowError
    "-1",
    "0.5",
    "true",
    "null",
    "[1]",
    '{"a":1}',
]
SWEEP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FIELD_RE = re.compile(
    r"""(?:data|payload|body|request_data)\s*\.get\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""
)
MEMBERSHIP_RE = re.compile(
    r"""["']([A-Za-z_][A-Za-z0-9_]*)["']\s+in\s+(?:data|payload|body)\b"""
)


# ``first_present(("soundVolume", "sound_volume"))``-style alias tuples.
ALIAS_RE = re.compile(
    r"""\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']\s*(?:,\s*["']([A-Za-z_][A-Za-z0-9_]*)["']\s*)?,?\s*\)"""
)


def _field_names_read_by(view: Any) -> set[str]:
    # ``@limiter.limit`` wraps the handler; the wrapper lives in flask-limiter's file.
    handler = inspect.unwrap(view)
    source = Path(inspect.getsourcefile(handler) or "").read_text(encoding="utf-8")
    names = set(FIELD_RE.findall(source)) | set(MEMBERSHIP_RE.findall(source))
    for first, second in ALIAS_RE.findall(source):
        names.update(name for name in (first, second) if name)
    return names


def _write_routes(ui: WebFeedbackUI) -> list[tuple[str, str, set[str]]]:
    found = []
    for rule in ui.app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = (rule.methods or set()) & SWEEP_METHODS
        if not methods:
            continue
        view = ui.app.view_functions[rule.endpoint]
        path = re.sub(r"<[^>]+>", "r797-task", rule.rule)
        for method in sorted(methods):
            found.append((method, path, _field_names_read_by(view)))
    return sorted(found, key=lambda item: (item[1], item[0]))


class TestNoWriteRouteAnswers5xxForAnUnusableNumberOrType:
    @pytest.fixture(autouse=True)
    def _nothing_leaves_the_machine_and_nothing_is_launched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[list[Any]]:
        attempts: list[Any] = []
        real_connect = socket.socket.connect

        def guarded_connect(sock: socket.socket, address: Any, *args: Any) -> Any:
            host = address[0] if isinstance(address, tuple) else address
            if host not in ("127.0.0.1", "::1", "localhost"):
                attempts.append(address)
                raise OSError("R797 sweep: outbound connections are blocked")
            return real_connect(sock, address, *args)

        monkeypatch.setattr(socket.socket, "connect", guarded_connect)
        # ``/api/notify-new-tasks`` and ``/api/system/notifications/test`` really send;
        # a send leaves retry timers (and the in-flight file next to the config) behind
        # that outlive the test and race the temp-dir cleanup at interpreter exit.
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
        routes = _write_routes(ui)
        assert len(routes) >= 15
        every_field = set().union(*(fields for _, _, fields in routes))
        assert {"frontend_countdown", "soundVolume", "bark_device_key"} <= every_field

    def test_no_5xx_and_no_escaped_exception(
        self, ui: WebFeedbackUI, client: FlaskClient
    ) -> None:
        failures: list[str] = []
        requests = 0
        for method, path, fields in _write_routes(ui):
            for field in sorted(fields):
                for literal in SWEEP_VALUES:
                    body = f'{{"{field}": {literal}}}'.encode()
                    requests += 1
                    try:
                        resp = client.open(
                            path,
                            method=method,
                            data=body,
                            content_type="application/json",
                            environ_base=LOOPBACK,
                        )
                    except Exception as exc:
                        failures.append(
                            f"{method} {path} {field}={literal[:24]} raised "
                            f"{type(exc).__name__}: {str(exc)[:80]}"
                        )
                        continue
                    if resp.status_code >= 500:
                        failures.append(
                            f"{method} {path} {field}={literal[:24]} -> "
                            f"{resp.status_code}"
                        )
        assert requests > 1000
        assert not failures, f"{len(failures)} of {requests} requests:\n" + "\n".join(
            failures[:25]
        )
