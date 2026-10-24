"""R856: only this Web UI's own ``/api/health`` answer counts as "the Web UI is running".

What happened
=============

The MCP process decides "is the Web UI already running?" with one request:
``GET /api/health``, and any HTTP 200 meant yes. Port 8080, the default, is also the
default port of front-end dev servers (webpack-dev-server, Vue CLI, ...), and those
answer *every* path with 200 and a page of HTML. With one of them on the port:

* ``ensure_web_ui_running`` returned at once ("already running") and the task was sent
  to the dev server, which has no ``/api/tasks``;
* ``start_web_service`` had the same blind spot in its own "already running" early
  return, so the friendly ``port_in_use`` message (with the ``lsof`` command and the
  two ways to change the port) could never be reached.

The check is now "HTTP 200 and the body is JSON with ``status == "ok"``" - the answer
every version of this Web UI has always given. Anything else on the port is treated
as another program: the normal start path runs, finds the port taken and raises
``port_in_use``.

``/api/health`` also reports ``version``. A Web UI of another version than the MCP
process (an orphan left by an older MCP process, an IDE window that has not restarted
since an upgrade) keeps being used - that combination has always worked - but one
warning says so, because the new version's features may not be there. Old Web UIs have
no ``version``; that is not an error and not a warning.

Contract
========

1. HTTP 200 plus JSON ``{"status": "ok", ...}`` (extra keys allowed) is this Web UI; every
   other answer - other status, HTML, plain text, empty, invalid JSON, JSON that is not an
   object, ``status`` other than ``"ok"`` - is not. Same verdict in the sync check
   (``health_check_service``) and the async one (``ensure_web_ui_running``).
2. Another program answering 200 is reported once per port (the port and the start of its
   answer are in the line), not once per tool call.
3. A different ``version`` is reported once per port and version; a missing, non-string,
   ``unknown`` or equal version, or a local version that cannot be read, is silent. The
   warning never changes the verdict.
4. With a foreign program on the port, the real ``ensure_web_ui_running`` raises
   ``port_in_use``, sends it nothing but the health request and starts no process.
5. This Web UI, served for real, passes both checks without a warning, and its
   ``/api/health`` carries the version.
"""

from __future__ import annotations

import asyncio
import importlib.metadata as metadata
import json
import re
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from werkzeug.serving import make_server

import ai_intervention_agent.service_manager as sm
from ai_intervention_agent.exceptions import ServiceUnavailableError
from ai_intervention_agent.server_config import WebUIConfig
from ai_intervention_agent.web_ui import WebFeedbackUI, get_project_version

REPO = Path(__file__).resolve().parent.parent
OWN_VERSION = "1.8.12"

# conftest's autouse fixture swaps ``httpx.Client.send`` and ``httpx.AsyncClient.send`` for
# stubs that raise (the offline guarantee). These tests speak real HTTP, but only to
# programs on the loopback that they start themselves, so they keep the originals taken
# here, at import time, before that fixture runs.
_REAL_SYNC_SEND = httpx.Client.send
_REAL_ASYNC_SEND = httpx.AsyncClient.send

# The autouse fixture below replaces the module attribute; the real function stays here.
REAL_OWN_VERSION = sm._own_version


class _Program:
    """Something listening on a port: ``GET /api/health`` gets a canned answer, the rest 404."""

    def __init__(
        self, status: int, body: bytes, content_type: str | None = "application/json"
    ) -> None:
        self.requests: list[tuple[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _answer(self) -> None:
                outer.requests.append((self.command, self.path))
                if self.path == "/api/health":
                    code, payload, kind = status, body, content_type
                else:
                    code, payload, kind = 404, b"", None
                self.send_response(code)
                if kind:
                    self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                self._answer()

            def do_POST(self) -> None:
                self._answer()

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fresh HTTP clients, a fresh "already warned" memory, and a known local version."""
    monkeypatch.setattr(httpx.Client, "send", _REAL_SYNC_SEND)
    monkeypatch.setattr(httpx.AsyncClient, "send", _REAL_ASYNC_SEND)
    sm.cleanup_http_clients()
    sm._HEALTH_NOTES_SEEN.clear()
    REAL_OWN_VERSION.cache_clear()
    monkeypatch.setattr(sm, "_own_version", lambda: OWN_VERSION)
    yield
    sm.cleanup_http_clients()
    sm._HEALTH_NOTES_SEEN.clear()
    REAL_OWN_VERSION.cache_clear()


@pytest.fixture
def warned(monkeypatch: pytest.MonkeyPatch) -> Callable[[], list[str]]:
    """The WARNING lines logged so far (the real logger de-duplicates, so look at the calls)."""
    recorder = MagicMock()
    monkeypatch.setattr(sm, "logger", recorder)

    def lines() -> list[str]:
        return [str(call.args[0]) for call in recorder.warning.call_args_list]

    return lines


@pytest.fixture
def program() -> Iterator[Callable[..., _Program]]:
    started: list[_Program] = []

    def start(
        status: int, body: bytes, content_type: str | None = "application/json"
    ) -> _Program:
        one = _Program(status, body, content_type)
        started.append(one)
        return one

    yield start
    for one in started:
        one.close()


def _config(port: int) -> WebUIConfig:
    return WebUIConfig(host="127.0.0.1", port=port)


def _sync_says_running(port: int) -> bool:
    return sm.health_check_service(_config(port))


def _async_says_running(port: int, monkeypatch: pytest.MonkeyPatch) -> bool:
    """``ensure_web_ui_running`` returned without trying to start a Web UI."""
    start = MagicMock()
    monkeypatch.setattr(sm, "start_web_service", start)

    async def main() -> None:
        # a client per event loop: the module-level one stays bound to the first loop
        async with httpx.AsyncClient(trust_env=False) as client:
            await sm.ensure_web_ui_running(_config(port), client=client)

    asyncio.run(main())
    return not start.called


def _ok(**extra: Any) -> bytes:
    return json.dumps({"status": "ok", **extra}).encode()


def _about_health(lines: list[str]) -> list[str]:
    """The lines that report another program answering ``/api/health``."""
    return [line for line in lines if "/api/health" in line]


HTML_PAGE = b"<!doctype html><html><body><div id=app></div></body></html>"

#: (id, status, body, content type, is it this Web UI?)
ANSWERS: list[tuple[str, int, bytes, str | None, bool]] = [
    ("ours-every-version", 200, _ok(), "application/json", True),
    ("ours-with-version", 200, _ok(version=OWN_VERSION), "application/json", True),
    ("ours-with-extra-keys", 200, _ok(uptime=3), "application/json", True),
    ("ours-wrong-content-type", 200, _ok(), "text/plain", True),
    ("dev-server-html", 200, HTML_PAGE, "text/html", False),
    ("plain-ok", 200, b"OK", "text/plain", False),
    ("empty", 200, b"", None, False),
    ("another-json-shape", 200, b'{"healthy": true}', "application/json", False),
    ("status-missing", 200, b"{}", "application/json", False),
    ("status-not-ok", 200, b'{"status": "error"}', "application/json", False),
    ("status-other-case", 200, b'{"status": "OK"}', "application/json", False),
    ("status-is-true", 200, b'{"status": true}', "application/json", False),
    ("json-list", 200, b'["ok"]', "application/json", False),
    ("json-string", 200, b'"ok"', "application/json", False),
    ("json-null", 200, b"null", "application/json", False),
    ("json-number", 200, b"1", "application/json", False),
    ("broken-json", 200, b'{"status": ', "application/json", False),
    ("not-utf8", 200, b"\xff\xfe\x00", "application/json", False),
    ("ok-body-but-503", 503, _ok(), "application/json", False),
    ("ok-body-but-404", 404, _ok(), "application/json", False),
    ("ok-body-but-301", 301, _ok(), "application/json", False),
    ("plain-404", 404, b"", None, False),
    ("plain-500", 500, b"boom", "text/plain", False),
]
ANSWER_IDS = [row[0] for row in ANSWERS]
ANSWER_COLUMNS = ("name", "status", "body", "kind", "ours")


class TestWhatCountsAsThisWebUI:
    @pytest.mark.parametrize(ANSWER_COLUMNS, ANSWERS, ids=ANSWER_IDS)
    def test_the_sync_check(
        self,
        program: Callable[..., _Program],
        warned: Callable[[], list[str]],
        name: str,
        status: int,
        body: bytes,
        kind: str | None,
        ours: bool,
    ) -> None:
        other = program(status, body, kind)

        assert _sync_says_running(other.port) is ours, name
        assert other.requests == [("GET", "/api/health")]

    @pytest.mark.parametrize(ANSWER_COLUMNS, ANSWERS, ids=ANSWER_IDS)
    def test_the_async_check(
        self,
        program: Callable[..., _Program],
        monkeypatch: pytest.MonkeyPatch,
        warned: Callable[[], list[str]],
        name: str,
        status: int,
        body: bytes,
        kind: str | None,
        ours: bool,
    ) -> None:
        other = program(status, body, kind)

        assert _async_says_running(other.port, monkeypatch) is ours, name
        assert other.requests == [("GET", "/api/health")]

    @pytest.mark.parametrize(ANSWER_COLUMNS, ANSWERS, ids=ANSWER_IDS)
    def test_both_checks_agree_and_say_so_once(
        self,
        program: Callable[..., _Program],
        monkeypatch: pytest.MonkeyPatch,
        warned: Callable[[], list[str]],
        name: str,
        status: int,
        body: bytes,
        kind: str | None,
        ours: bool,
    ) -> None:
        other = program(status, body, kind)

        sync_verdict = _sync_says_running(other.port)
        async_verdict = _async_says_running(other.port, monkeypatch)

        assert sync_verdict is async_verdict is ours, name
        # only "200, but not us" is news: a plain error status is the existing failure path
        foreign_answer = status == 200 and not ours
        assert len(_about_health(warned())) == (1 if foreign_answer else 0), warned()


class TestAnotherProgramIsReportedOnce:
    def test_the_line_names_the_port_and_what_answered(
        self, program: Callable[..., _Program], warned: Callable[[], list[str]]
    ) -> None:
        dev_server = program(200, HTML_PAGE, "text/html")

        assert _sync_says_running(dev_server.port) is False

        (line,) = _about_health(warned())
        assert str(dev_server.port) in line
        assert "<!doctype html>" in line
        assert "web_ui.port" in line

    def test_a_long_answer_is_cut_and_an_empty_one_is_called_empty(
        self, program: Callable[..., _Program], warned: Callable[[], list[str]]
    ) -> None:
        chatty = program(200, b"x" * 5000, "text/plain")
        silent = program(200, b"", None)

        _sync_says_running(chatty.port)
        _sync_says_running(silent.port)

        long_line, empty_line = _about_health(warned())
        assert "x" * 80 in long_line
        assert "x" * 81 not in long_line
        assert "…" in long_line
        assert "空响应体" in empty_line

    def test_every_tool_call_does_not_add_a_line(
        self,
        program: Callable[..., _Program],
        monkeypatch: pytest.MonkeyPatch,
        warned: Callable[[], list[str]],
    ) -> None:
        dev_server = program(200, HTML_PAGE, "text/html")

        for _ in range(3):
            _sync_says_running(dev_server.port)
            _async_says_running(dev_server.port, monkeypatch)

        assert len(_about_health(warned())) == 1

    def test_another_port_is_reported_again(
        self, program: Callable[..., _Program], warned: Callable[[], list[str]]
    ) -> None:
        first = program(200, HTML_PAGE, "text/html")
        second = program(200, HTML_PAGE, "text/html")

        _sync_says_running(first.port)
        _sync_says_running(second.port)

        first_line, second_line = _about_health(warned())
        assert str(first.port) in first_line
        assert str(second.port) in second_line


class TestAnotherVersionIsReportedNotRefused:
    def test_the_line_names_both_versions_and_the_way_out(
        self, program: Callable[..., _Program], warned: Callable[[], list[str]]
    ) -> None:
        old = program(200, _ok(version="1.7.0"))

        assert _sync_says_running(old.port) is True

        (line,) = warned()
        assert "1.7.0" in line
        assert OWN_VERSION in line
        assert str(old.port) in line
        assert "lsof" in line
        assert "web_ui.port" in line

    def test_once_per_port_however_many_calls(
        self,
        program: Callable[..., _Program],
        monkeypatch: pytest.MonkeyPatch,
        warned: Callable[[], list[str]],
    ) -> None:
        old = program(200, _ok(version="1.7.0"))

        for _ in range(3):
            assert _sync_says_running(old.port) is True
            assert _async_says_running(old.port, monkeypatch) is True

        assert len(warned()) == 1

    def test_another_port_is_reported_again(
        self, program: Callable[..., _Program], warned: Callable[[], list[str]]
    ) -> None:
        first = program(200, _ok(version="1.7.0"))
        second = program(200, _ok(version="1.7.0"))

        _sync_says_running(first.port)
        _sync_says_running(second.port)

        assert len(warned()) == 2

    def test_a_third_version_on_the_same_port_is_reported_again(
        self, warned: Callable[[], list[str]]
    ) -> None:
        config = _config(18856)

        sm._warn_if_other_version(config, "1.7.0")
        sm._warn_if_other_version(config, "1.7.0")
        sm._warn_if_other_version(config, "1.6.0")

        first_line, second_line = warned()
        assert "1.7.0" in first_line
        assert "1.6.0" in second_line

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(_ok(), id="old-web-ui-without-version"),
            pytest.param(_ok(version=OWN_VERSION), id="same-version"),
            pytest.param(_ok(version=None), id="null"),
            pytest.param(_ok(version=12), id="number"),
            pytest.param(_ok(version=["1.7.0"]), id="list"),
            pytest.param(_ok(version=""), id="empty"),
            pytest.param(_ok(version="unknown"), id="unknown"),
            pytest.param(_ok(version="0.0.0+local"), id="source-checkout"),
        ],
    )
    def test_these_say_nothing(
        self,
        program: Callable[..., _Program],
        monkeypatch: pytest.MonkeyPatch,
        warned: Callable[[], list[str]],
        body: bytes,
    ) -> None:
        other = program(200, body)

        assert _sync_says_running(other.port) is True
        assert _async_says_running(other.port, monkeypatch) is True

        assert warned() == []

    def test_a_local_version_that_cannot_be_read_says_nothing(
        self,
        program: Callable[..., _Program],
        monkeypatch: pytest.MonkeyPatch,
        warned: Callable[[], list[str]],
    ) -> None:
        monkeypatch.setattr(sm, "_own_version", lambda: "")
        other = program(200, _ok(version="1.7.0"))

        assert _sync_says_running(other.port) is True

        assert warned() == []

    def test_the_local_version_is_read_once_from_the_installed_package(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[str] = []

        def installed(name: str) -> str:
            asked.append(name)
            return "7.7.7"

        monkeypatch.setattr(metadata, "version", installed)

        assert REAL_OWN_VERSION() == "7.7.7"
        assert REAL_OWN_VERSION() == "7.7.7"
        assert asked == ["ai-intervention-agent"]

    def test_a_package_that_is_not_installed_has_no_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing(_name: str) -> str:
            raise metadata.PackageNotFoundError

        monkeypatch.setattr(metadata, "version", missing)

        assert REAL_OWN_VERSION() == ""


class TestAForeignProgramBlocksTheStart:
    @pytest.fixture
    def no_process(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        """The real start path, but nothing may be spawned and no notification set-up runs."""
        popen = MagicMock(side_effect=AssertionError("a Web UI process was started"))
        monkeypatch.setattr(sm.subprocess, "Popen", popen)
        monkeypatch.setattr(
            sm, "_ensure_notification_system_loaded", lambda: (None, None)
        )
        return popen

    def test_ensure_web_ui_running_raises_port_in_use(
        self,
        program: Callable[..., _Program],
        no_process: MagicMock,
        warned: Callable[[], list[str]],
    ) -> None:
        dev_server = program(200, HTML_PAGE, "text/html")

        with pytest.raises(ServiceUnavailableError) as raised:
            asyncio.run(sm.ensure_web_ui_running(_config(dev_server.port)))

        assert raised.value.code == "port_in_use"
        assert str(dev_server.port) in str(raised.value)
        assert "lsof" in str(raised.value)
        assert dev_server.requests
        assert set(dev_server.requests) == {("GET", "/api/health")}
        no_process.assert_not_called()

    def test_start_web_service_does_not_call_it_already_running(
        self,
        program: Callable[..., _Program],
        no_process: MagicMock,
        warned: Callable[[], list[str]],
    ) -> None:
        dev_server = program(200, HTML_PAGE, "text/html")

        with pytest.raises(ServiceUnavailableError) as raised:
            sm.start_web_service(_config(dev_server.port), Path(sm.__file__).parent)

        assert raised.value.code == "port_in_use"
        no_process.assert_not_called()

    def test_this_web_ui_on_the_port_is_left_alone(
        self,
        program: Callable[..., _Program],
        no_process: MagicMock,
        warned: Callable[[], list[str]],
    ) -> None:
        ours = program(200, _ok(version=OWN_VERSION))

        asyncio.run(sm.ensure_web_ui_running(_config(ours.port)))
        sm.start_web_service(_config(ours.port), Path(sm.__file__).parent)

        no_process.assert_not_called()
        assert set(ours.requests) == {("GET", "/api/health")}


class TestTheRealWebUI:
    @pytest.fixture
    def running(self) -> Iterator[int]:
        ui = WebFeedbackUI(prompt="r856", task_id="r856-task", port=18856)
        server = make_server("127.0.0.1", 0, ui.app, threaded=True)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()

    def test_health_carries_the_status_and_the_version(self) -> None:
        ui = WebFeedbackUI(prompt="r856", task_id="r856-task", port=18856)

        response = ui.app.test_client().get("/api/health")

        assert response.status_code == 200
        assert response.get_json() == {"status": "ok", "version": get_project_version()}

    def test_it_passes_both_checks_without_a_warning(
        self,
        running: int,
        monkeypatch: pytest.MonkeyPatch,
        warned: Callable[[], list[str]],
    ) -> None:
        # the real local version, not the constant the other tests use
        monkeypatch.setattr(sm, "_own_version", get_project_version)

        assert _sync_says_running(running) is True
        assert _async_says_running(running, monkeypatch) is True

        assert warned() == []

    def test_a_different_local_version_is_noticed_on_the_real_thing(
        self,
        running: int,
        monkeypatch: pytest.MonkeyPatch,
        warned: Callable[[], list[str]],
    ) -> None:
        monkeypatch.setattr(sm, "_own_version", lambda: "99.0.0")

        assert _sync_says_running(running) is True

        (line,) = warned()
        assert get_project_version() in line
        assert "99.0.0" in line


class TestTheTroubleshootingGuideSaysHowItIsRecognised:
    @pytest.mark.parametrize(
        "guide", ["docs/troubleshooting.md", "docs/troubleshooting.zh-CN.md"]
    )
    def test_the_port_in_use_section_names_the_health_answer(self, guide: str) -> None:
        text = (REPO / guide).read_text(encoding="utf-8")
        section = re.split(r"^## 2\. ", text, maxsplit=1, flags=re.MULTILINE)[0]

        assert "/api/health" in section
        assert '{"status": "ok"}' in section
