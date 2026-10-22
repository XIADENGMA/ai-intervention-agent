"""R796: the event stream answers the moment a client connects.

``/api/events`` produced bytes only when the bus had an event to deliver or, failing that, after
the 25 s idle wait that ends in a heartbeat. A WSGI server sends the status line and the headers
together with the first chunk, so a client that connected to an idle server got nothing at all for
25 s, not even the headers. Everything that treats "the response started" as "connected" was that
late, measured on an idle server:

- the page's ``EventSource.onopen`` (``_sseConnected``, the status dot after a reconnect, and the
  move of the task polling from 2 s to its 30 s safety net),
- ``http.get``'s response callback in the VS Code host (``sse.connected`` and the language sync),
- httpx's ``stream()`` context in the MCP server (``sse_connected``, which switches the HTTP
  safety net of ``wait_for_task_completion`` from 2 s to 30 s).

The stream now opens with the comment frame ``: connected``. A comment is invisible to every
consumer (``EventSource`` drops it, ``SseParser`` skips it, ``_sse_listener`` only reads ``data:``
lines), so nothing else changes: events still arrive in order and the idle heartbeat is unchanged.

These tests use a real werkzeug server on a loopback port because the defect is about when bytes
leave the socket, which a WSGI test client cannot see.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from collections.abc import Iterator

import pytest
from flask import Response
from werkzeug.serving import make_server

from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes import task as task_module

# Long enough for a loaded CI box, far below the 25 s the defect needed.
RESPONSE_DEADLINE_S = 5.0
CONNECT_FRAME = b": connected\n"


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> task_module._SSEBus:
    """A private bus, so event ids start at 1 and other tests' history cannot leak in."""
    fresh = task_module._SSEBus()
    monkeypatch.setattr(task_module, "_sse_bus", fresh)
    return fresh


@pytest.fixture
def port(bus: task_module._SSEBus) -> Iterator[int]:
    ui = WebFeedbackUI(prompt="r796", task_id="r796-task", port=18790)
    server = make_server("127.0.0.1", 0, ui.app, threaded=True)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server.server_port
    finally:
        # End every open stream now instead of after its next 25 s wait.
        with bus._lock:
            subscribers = list(bus._subscribers)
        for subscriber in subscribers:
            subscriber.put_nowait(task_module._SSE_DISCONNECT_SENTINEL)
        server.shutdown()
        thread.join(5)
        server.server_close()


def _connect(
    port: int, path: str = "/api/events"
) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse, float]:
    """Open the stream; fail (instead of hanging for 25 s) when the response does not start."""
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=RESPONSE_DEADLINE_S
    )
    started = time.monotonic()
    connection.request("GET", path, headers={"Accept": "text/event-stream"})
    try:
        response = connection.getresponse()
    except OSError as error:  # socket.timeout is a TimeoutError, which is an OSError
        connection.close()
        pytest.fail(
            f"{path} sent no response within {RESPONSE_DEADLINE_S} s of connecting: {error!r}"
        )
    return connection, response, time.monotonic() - started


def _read_frame(response: http.client.HTTPResponse) -> list[bytes]:
    """The lines of the next SSE frame, up to and excluding its blank line."""
    lines: list[bytes] = []
    while True:
        line = response.readline()
        assert line, "the stream ended in the middle of a frame"
        if line == b"\n":
            return lines
        lines.append(line)


def _fields(frame: list[bytes]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in frame:
        name, _, value = line.decode("utf-8").rstrip("\n").partition(":")
        parsed[name] = value.lstrip(" ")
    return parsed


class TestTheResponseStartsAtOnce:
    def test_headers_arrive_without_waiting_for_an_event_or_a_heartbeat(
        self, port: int
    ) -> None:
        connection, response, elapsed = _connect(port)
        try:
            assert response.status == 200
            assert response.getheader("Content-Type", "").startswith(
                "text/event-stream"
            )
            assert elapsed < 2.0, f"the response took {elapsed:.2f} s to start"
        finally:
            connection.close()

    def test_the_first_frame_is_a_comment_and_carries_no_event(self, port: int) -> None:
        connection, response, _ = _connect(port)
        try:
            frame = _read_frame(response)

            assert frame == [CONNECT_FRAME]
            assert not any(
                line.startswith((b"event:", b"data:", b"id:")) for line in frame
            )
        finally:
            connection.close()

    def test_a_comment_frame_is_never_counted_as_a_heartbeat(
        self, port: int, bus: task_module._SSEBus
    ) -> None:
        connection, response, _ = _connect(port)
        try:
            _read_frame(response)

            assert bus.stats_snapshot()["heartbeat_total"] == 0
        finally:
            connection.close()


class TestEventsStillFollow:
    def test_an_event_emitted_after_connecting_arrives_after_the_comment(
        self, port: int, bus: task_module._SSEBus
    ) -> None:
        connection, response, _ = _connect(port)
        try:
            assert _read_frame(response) == [CONNECT_FRAME]
            bus.emit("task_changed", {"task_id": "r796-a", "new_status": "active"})

            fields = _fields(_read_frame(response))

            assert fields["event"] == "task_changed"
            assert fields["id"] == "1"
            assert json.loads(fields["data"])["task_id"] == "r796-a"
        finally:
            connection.close()

    def test_events_missed_while_away_are_replayed_after_the_comment_in_order(
        self, port: int, bus: task_module._SSEBus
    ) -> None:
        for name in ("one", "two", "three"):
            bus.emit("task_changed", {"task_id": f"r796-{name}"})

        connection, response, _ = _connect(port, "/api/events?last_event_id=1")
        try:
            assert _read_frame(response) == [CONNECT_FRAME]
            second = _fields(_read_frame(response))
            third = _fields(_read_frame(response))

            assert (second["id"], json.loads(second["data"])["task_id"]) == (
                "2",
                "r796-two",
            )
            assert (third["id"], json.loads(third["data"])["task_id"]) == (
                "3",
                "r796-three",
            )
        finally:
            connection.close()

    def test_a_client_that_is_too_far_behind_still_gets_the_gap_warning(
        self, port: int, bus: task_module._SSEBus
    ) -> None:
        for index in range(3):
            bus.emit("task_changed", {"task_id": f"r796-{index}"})
        with bus._lock:
            # The history no longer reaches back to what the client last saw.
            bus._history.popleft()
            bus._history.popleft()

        connection, response, _ = _connect(port, "/api/events?last_event_id=1")
        try:
            assert _read_frame(response) == [CONNECT_FRAME]
            assert _fields(_read_frame(response))["event"] == "gap_warning"
        finally:
            connection.close()


class TestOneStreamPerClient:
    def test_every_connection_gets_its_own_comment(self, port: int) -> None:
        opened: list[http.client.HTTPConnection] = []
        try:
            for _ in range(3):
                connection, response, _ = _connect(port)
                opened.append(connection)
                assert _read_frame(response) == [CONNECT_FRAME]
        finally:
            for connection in opened:
                connection.close()

    def test_the_stream_ends_when_the_bus_drops_the_subscriber(
        self, port: int, bus: task_module._SSEBus
    ) -> None:
        """The disconnect sentinel (backpressure) must still end the stream after the comment."""
        connection, response, _ = _connect(port)
        try:
            assert _read_frame(response) == [CONNECT_FRAME]
            with bus._lock:
                subscribers = list(bus._subscribers)
            assert len(subscribers) == 1
            subscribers[0].put_nowait(task_module._SSE_DISCONNECT_SENTINEL)

            assert response.readline() == b""
        finally:
            connection.close()


class TestSubscriptionHappensBeforeTheFirstByte:
    def test_the_route_subscribes_before_it_produces_its_first_chunk(
        self, bus: task_module._SSEBus
    ) -> None:
        """Calling the view registers the subscriber; the comment is produced afterwards.

        This is the order that matters: the first byte tells the client it is connected, so
        everything emitted from then on has to find a subscriber already waiting.
        """
        ui = WebFeedbackUI(prompt="r796", task_id="r796-task", port=18790)
        view = ui.app.view_functions["sse_events"]
        with ui.app.test_request_context("/api/events"):
            streaming = view()
            assert isinstance(streaming, Response)
            try:
                assert bus.stats_snapshot()["subscriber_count"] == 1
                chunks = iter(streaming.response)
                assert next(chunks) == ": connected\n\n"
            finally:
                streaming.close()

    def test_a_client_that_has_read_the_comment_already_receives_what_happens_next(
        self, port: int, bus: task_module._SSEBus
    ) -> None:
        """An event emitted the instant ``: connected`` has been read reaches that client."""
        connection, response, _ = _connect(port)
        try:
            assert _read_frame(response) == [CONNECT_FRAME]
            assert bus.stats_snapshot()["subscriber_count"] == 1
            bus.emit("task_changed", {"task_id": "r796-race"})

            assert json.loads(_fields(_read_frame(response))["data"])["task_id"] == (
                "r796-race"
            )
        finally:
            connection.close()
