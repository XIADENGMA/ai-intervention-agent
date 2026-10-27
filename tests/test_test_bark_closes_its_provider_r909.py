"""R909: the Test button of the Bark settings closes the HTTP client it opened.

``POST /api/test-bark`` builds a ``BarkNotificationProvider`` from the form of the settings page for every
press of the button, sends one push through it and answers. The provider owns an ``httpx.Client`` (a
connection pool). The route never closed it, while every other place that creates a provider hands it to
something that does (the notification manager closes the providers it registers).

Letting it go out of scope is not enough. An ``httpx`` response is part of a reference cycle (the stream
it is bound to holds the response and the response holds the stream; httpx 0.28.1), and that stream holds
the pool, so the pool and the idle keep-alive connection in it outlive the client until the cyclic garbage
collector happens to run. Measured against a Bark stand-in that keeps its connections open, with the
collector switched off: after the first, second and third press the server still had 1, 2 and 3
connections open, and none after ``gc.collect()``; with the route closing the provider it has none after
each press.

What is pinned, with a real loopback Bark server and the real provider (a recording subclass, so that the
test can look at the client after the route is done with it): the client of every press is closed when the
answer is given, however the press ended (the push went through; the server refused it with a reason; the
provider rejected the address before anything left; ``send`` raised; the event could not be built), one per
press and not a shared one, and the server sees the connection end with the garbage collector switched off.
The answers themselves are pinned too (they must not change): the status codes, the body of the push, the
detail of a refusal, and the two answers that never reach a provider.
"""

from __future__ import annotations

import gc
import http.server
import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ai_intervention_agent import notification_providers
from ai_intervention_agent.notification_providers import BarkNotificationProvider
from ai_intervention_agent.web_ui_routes import notification as routes

ROUTES = "ai_intervention_agent.web_ui_routes.notification"


@pytest.fixture(autouse=True)
def _disable_real_network_requests() -> None:
    """Replace the guard of ``conftest.py`` for this module only.

    The guard makes every un-mocked ``httpx`` call fail, which is right everywhere else. These tests
    need the push to reach a Bark stand-in on a loopback port, to see what becomes of the connection.
    """


@pytest.fixture(autouse=True)
def quiet_logs(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The route and the provider log what goes wrong; the tests look at it instead of printing it."""
    logs = SimpleNamespace(route=MagicMock(), provider=MagicMock())
    monkeypatch.setattr(routes, "logger", logs.route)
    monkeypatch.setattr(notification_providers, "logger", logs.provider)
    return logs


class FakeBark:
    """A Bark server on a loopback port that keeps a connection open between requests (HTTP/1.1)."""

    def __init__(self, status: int, answer: dict[str, Any]) -> None:
        outer = self
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.errors: list[str] = []
        self._lock = threading.Lock()
        self._opened = 0
        self._ended = 0

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def handle(self) -> None:
                with outer._lock:
                    outer._opened += 1
                try:
                    super().handle()
                finally:
                    with outer._lock:
                        outer._ended += 1

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append(
                    (self.path, json.loads(self.rfile.read(length) or b"{}"))
                )
                payload = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: Any) -> None:
                return

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request: Any, client_address: Any) -> None:
                outer.errors.append(repr(sys.exc_info()[1]))

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()

    def url(self, path: str = "/push") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    @property
    def opened(self) -> int:
        with self._lock:
            return self._opened

    def open_now(self) -> int:
        with self._lock:
            return self._opened - self._ended

    def wait_until_every_connection_has_ended(self, seconds: float = 3.0) -> bool:
        deadline = time.monotonic() + seconds
        while self.open_now() and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.open_now() == 0

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def make_bark() -> Iterator[Callable[..., FakeBark]]:
    made: list[FakeBark] = []

    def make(status: int = 200, answer: dict[str, Any] | None = None) -> FakeBark:
        server = FakeBark(status, answer or {"code": 200, "message": "success"})
        made.append(server)
        return server

    try:
        yield make
    finally:
        for server in made:
            server.close()
    assert [error for server in made for error in server.errors] == []


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> list[BarkNotificationProvider]:
    """Every provider the route builds, in order (the route keeps no other reference to them)."""
    made: list[BarkNotificationProvider] = []

    class Recording(BarkNotificationProvider):
        def __init__(self, config: Any) -> None:
            super().__init__(config)
            made.append(self)

    monkeypatch.setattr(routes, "BarkNotificationProvider", Recording)
    return made


@pytest.fixture(scope="module")
def web_client() -> Any:
    """The Flask test client of a Web UI that is never started (as in R63a and R906)."""
    from ai_intervention_agent.web_ui import WebFeedbackUI

    ui = WebFeedbackUI(prompt="bark provider test", task_id="rt-r909", port=19097)
    ui.app.config["TESTING"] = True
    ui.limiter.enabled = False
    return ui.app.test_client()


def press(web_client: Any, bark_url: str, **fields: Any) -> Any:
    form = {
        "bark_url": bark_url,
        "bark_device_key": "KEY123",
        "bark_action": "none",
        **fields,
    }
    with patch(f"{ROUTES}.NOTIFICATION_AVAILABLE", True):
        return web_client.post("/api/test-bark", json=form)


class TestTheClientOfEveryPressIsClosed:
    def test_after_a_push_that_goes_through(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        providers: list[BarkNotificationProvider],
    ) -> None:
        bark = make_bark()
        response = press(web_client, bark.url())
        assert response.status_code == 200, response.get_data(as_text=True)
        assert [path for path, _ in bark.requests] == ["/push"]
        (provider,) = providers
        assert provider.session.is_closed
        assert bark.opened == 1
        assert bark.wait_until_every_connection_has_ended()

    def test_after_a_push_the_server_refuses_with_a_reason(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        providers: list[BarkNotificationProvider],
    ) -> None:
        bark = make_bark(500, {"code": 500, "message": "device key is invalid"})
        response = press(web_client, bark.url())
        assert response.status_code == 500
        assert "device key is invalid" in response.get_json()["message"]
        (provider,) = providers
        assert provider.session.is_closed
        assert bark.wait_until_every_connection_has_ended()

    def test_after_a_push_that_is_rejected_before_anything_leaves(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        providers: list[BarkNotificationProvider],
    ) -> None:
        bark = make_bark()
        response = press(web_client, "ftp://bark.test/push")
        assert response.status_code == 500
        assert response.get_json()["status"] == "error"
        assert bark.opened == 0
        (provider,) = providers
        assert provider.session.is_closed

    def test_after_the_send_raises(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        providers: list[BarkNotificationProvider],
        monkeypatch: pytest.MonkeyPatch,
        quiet_logs: SimpleNamespace,
    ) -> None:
        def raising(self: Any, event: Any) -> bool:
            raise RuntimeError("the send fell over")

        monkeypatch.setattr(BarkNotificationProvider, "send", raising)
        bark = make_bark()
        response = press(web_client, bark.url())
        assert response.status_code == 500
        assert response.get_json()["status"] == "error"
        quiet_logs.route.error.assert_called_once()
        (provider,) = providers
        assert provider.session.is_closed

    def test_when_the_event_cannot_be_built_no_client_is_left_open(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        providers: list[BarkNotificationProvider],
    ) -> None:
        bark = make_bark()
        with patch(f"{ROUTES}.NotificationEvent", side_effect=ValueError("no event")):
            response = press(web_client, bark.url())
        assert response.status_code == 500
        assert all(provider.session.is_closed for provider in providers)
        assert bark.opened == 0

    def test_every_press_has_a_client_of_its_own_and_closes_it(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        providers: list[BarkNotificationProvider],
    ) -> None:
        bark = make_bark()
        for _ in range(3):
            assert press(web_client, bark.url()).status_code == 200
        assert len(providers) == 3
        assert len({id(provider.session) for provider in providers}) == 3
        assert all(provider.session.is_closed for provider in providers)
        assert bark.opened == 3
        assert bark.wait_until_every_connection_has_ended()

    def test_the_server_sees_the_connection_end_without_the_garbage_collector(
        self, web_client: Any, make_bark: Callable[..., FakeBark]
    ) -> None:
        bark = make_bark()
        gc.collect()
        gc.disable()
        try:
            for _ in range(3):
                assert press(web_client, bark.url()).status_code == 200
            assert bark.opened == 3
            assert bark.wait_until_every_connection_has_ended()
        finally:
            gc.enable()


class TestTheAnswerIsStillTheSame:
    def test_a_push_that_goes_through_is_a_200_with_the_body_of_the_test(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        quiet_logs: SimpleNamespace,
    ) -> None:
        bark = make_bark()
        response = press(web_client, bark.url())
        assert response.status_code == 200
        assert response.get_json()["status"] == "success"
        ((path, body),) = bark.requests
        assert path == "/push"
        assert body["device_key"] == "KEY123"
        assert body["title"].strip() and body["body"].strip()
        quiet_logs.route.error.assert_not_called()

    def test_a_refusal_with_a_reason_is_a_500_that_carries_the_reason(
        self, web_client: Any, make_bark: Callable[..., FakeBark]
    ) -> None:
        bark = make_bark(500, {"code": 500, "message": "device key is invalid"})
        response = press(web_client, bark.url())
        assert response.status_code == 500
        body = response.get_json()
        assert body["status"] == "error"
        assert "(HTTP 500)" in body["message"]
        assert "device key is invalid" in body["message"]

    def test_an_address_that_is_not_http_is_a_500_and_nothing_is_sent(
        self, web_client: Any, make_bark: Callable[..., FakeBark]
    ) -> None:
        bark = make_bark()
        response = press(web_client, "ftp://bark.test/push")
        assert response.status_code == 500
        assert response.get_json()["status"] == "error"
        assert bark.requests == []

    def test_a_key_of_blanks_is_a_400_and_no_provider_is_built(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        providers: list[BarkNotificationProvider],
    ) -> None:
        bark = make_bark()
        response = press(web_client, bark.url(), bark_device_key="   ")
        assert response.status_code == 400
        assert providers == []
        assert bark.opened == 0

    def test_a_field_that_is_not_text_is_a_400_and_no_provider_is_built(
        self,
        web_client: Any,
        make_bark: Callable[..., FakeBark],
        providers: list[BarkNotificationProvider],
    ) -> None:
        bark = make_bark()
        response = press(web_client, bark.url(), bark_icon=5)
        assert response.status_code == 400
        assert response.get_json()["error"] == "invalid_value"
        assert providers == []
        assert bark.opened == 0
