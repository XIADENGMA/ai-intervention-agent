"""R865: a HEAD request for the event stream subscribes to nothing.

Flask answers HEAD for every route that serves GET by running the view and throwing the body away.
``GET /api/events`` subscribes a queue to the SSE bus while the view runs and builds a generator
whose ``finally`` takes the queue off the bus again.  A HEAD answer has no body, so the WSGI server
never starts that generator, ``finally`` never runs and the queue stays on the bus: every HEAD left
a subscriber behind.  Nothing took it off but ``emit()``: once 48 events (``_BACKPRESSURE_THRESHOLD``)
had piled up in the dead queue it was dropped as a client that stopped reading and counted in
``backpressure_discards``, the figure an operator reads to learn about slow clients.  Any client that
sends HEAD (``curl -I``, a monitor, a proxy that probes) made ``emit()`` carry more dead queues and
the figure count clients that never existed.

The route now answers a HEAD with the status and headers of the GET, no body, and no subscription.

What the tests pin, each on a bus of the test's own so that what other tests left on the shared one
cannot count:

* a HEAD request, with or without a point to resume from, leaves no subscriber behind;
* the answer has the status and the headers of the GET answer (``Content-Type``, ``Cache-Control``,
  ``X-Accel-Buffering``), neither of them has a ``Content-Length``, and the HEAD body is empty;
* the events that follow a few HEAD requests discard no subscriber as backpressure;
* a GET is unchanged: it subscribes while the view runs, so an event emitted before the first frame is
  read still reaches it, and closing it takes its queue off the bus;
* a HEAD of every GET route of the Web UI leaves the bus as it found it, with the sweep held to reach
  the stream.
"""

from __future__ import annotations

import pytest
from flask import Response
from flask.testing import FlaskClient

from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import task as task_routes
from tests.test_no_hop_by_hop_response_headers_r864 import STREAM, get_urls

LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
EVENT = {
    "task_id": "r865-task",
    "old_status": None,
    "new_status": "active",
    "stats": {"total": 1, "pending": 0, "active": 1, "completed": 0, "max": 10},
}
STREAM_HEADERS = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
# Enough events for a queue nobody reads to reach the bus's backpressure threshold.
EMITTED = 60


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r865", task_id="r865-ui", auto_resubmit_timeout=0, port=19866
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> FlaskClient:
    return ui.app.test_client()


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> task_routes._SSEBus:
    """A bus of this test's own: the route looks the module's ``_sse_bus`` up on each request."""
    fresh = task_routes._SSEBus()
    monkeypatch.setattr(task_routes, "_sse_bus", fresh)
    return fresh


def head(
    client: FlaskClient,
    url: str = STREAM,
    *,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """``(status, headers, body)`` of a HEAD request for ``url``.

    The body is what the first chunk of the answer holds, not ``get_data()``: a stream that
    wrongly answered a HEAD would never end, and the test would hang instead of fail.
    """
    with client.open(
        url,
        method="HEAD",
        headers=headers,
        query_string=query,
        environ_base=LOOPBACK,
    ) as resp:
        chunk = next(iter(resp.response), b"")
        body = chunk if isinstance(chunk, bytes) else chunk.encode()
        return resp.status_code, dict(resp.headers), body


class TestAHeadRequest:
    def test_subscribes_to_nothing(
        self, client: FlaskClient, bus: task_routes._SSEBus
    ) -> None:
        for _ in range(5):
            status, _headers, _body = head(client)
            assert status == 200
        assert bus.subscriber_count == 0

    @pytest.mark.parametrize(
        ("headers", "query"),
        [({"Last-Event-ID": "1"}, None), (None, {"last_event_id": "1"})],
        ids=["header", "query"],
    )
    def test_subscribes_to_nothing_whatever_it_asks_to_resume_from(
        self,
        client: FlaskClient,
        bus: task_routes._SSEBus,
        headers: dict[str, str] | None,
        query: dict[str, str] | None,
    ) -> None:
        for _ in range(3):
            bus.emit("task_changed", EVENT)
        status, _headers, _body = head(client, headers=headers, query=query)
        assert status == 200
        assert bus.subscriber_count == 0

    def test_answers_the_status_and_headers_of_a_get_and_no_body(
        self, client: FlaskClient, bus: task_routes._SSEBus
    ) -> None:
        status, head_headers, body = head(client)
        with client.open(STREAM, environ_base=LOOPBACK) as resp:
            next(iter(resp.response))
            get_status, get_headers = resp.status_code, dict(resp.headers)
        assert status == get_status == 200
        assert {
            name: head_headers.get(name) for name in STREAM_HEADERS
        } == STREAM_HEADERS
        assert {
            name: get_headers.get(name) for name in STREAM_HEADERS
        } == STREAM_HEADERS
        assert "Content-Length" not in head_headers
        assert "Content-Length" not in get_headers
        assert body == b""
        assert bus.subscriber_count == 0

    def test_the_events_that_follow_discard_no_subscriber_as_backpressure(
        self, client: FlaskClient, bus: task_routes._SSEBus
    ) -> None:
        assert EMITTED >= bus._BACKPRESSURE_THRESHOLD
        for _ in range(5):
            head(client)
        for _ in range(EMITTED):
            bus.emit("task_changed", EVENT)
        assert bus.stats_snapshot()["backpressure_discards"] == 0


class TestAGetIsUnchanged:
    def test_subscribes_while_the_view_runs(
        self, ui: WebFeedbackUI, bus: task_routes._SSEBus
    ) -> None:
        """The view is called as it is, so nothing iterates the stream before the check.

        Flask's test client reads the first chunk of a stream while it opens it, which would hide
        a queue that is only subscribed once the stream starts.
        """
        with ui.app.test_request_context(STREAM, environ_base=LOOPBACK):
            resp = ui.app.view_functions["sse_events"]()
            assert isinstance(resp, Response)
            try:
                assert bus.subscriber_count == 1
            finally:
                resp.close()

    def test_delivers_what_follows_and_unsubscribes_when_closed(
        self, client: FlaskClient, bus: task_routes._SSEBus
    ) -> None:
        with client.open(STREAM, environ_base=LOOPBACK) as resp:
            assert bus.subscriber_count == 1
            bus.emit("task_changed", EVENT)
            frames = iter(resp.response)
            assert next(frames) == b": connected\n\n"
            event = next(frames)
            assert isinstance(event, bytes)
            assert b"event: task_changed" in event
        assert bus.subscriber_count == 0


class TestEveryGetRoute:
    def test_a_head_request_leaves_the_bus_as_it_found_it(
        self, ui: WebFeedbackUI, client: FlaskClient, bus: task_routes._SSEBus
    ) -> None:
        asked: list[str] = []
        for group in get_urls(ui).values():
            for url in group:
                status, _headers, _body = head(client, url)
                assert status < 500, url
                assert bus.subscriber_count == 0, url
                asked.append(url)
        assert STREAM in asked
        assert len(asked) >= 40
