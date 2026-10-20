"""R761: the Web UI binds its port without a reverse DNS lookup of the address.

``http.server.HTTPServer.server_bind`` stores ``socket.getfqdn(host)`` as the
server's ``server_name``, and Werkzeug's development server inherits it.  On macOS 15
and later the reverse lookup of ``127.0.0.1`` blocks for about 35 s in every process
whose Python is not uv's (Homebrew, python.org, pyenv): measured here, the real
``web_ui.py`` answered ``/api/health`` after 35.3 s on Homebrew's Python 3.14 and
after 0.2 s on uv's Python 3.11.  ``start_web_service`` waits 15 s, so on such a
machine every start timed out and the process was killed.  Nothing in the Web UI
reads ``server_name``.

``ensure_bind_without_reverse_dns`` swaps in a ``server_bind`` that binds like
``TCPServer`` and records the bind host as the name; ``WebFeedbackUI`` calls it once
when it is created.  These tests fake the stall (``socket.getfqdn`` sleeps) so that
they hold on every platform.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.request
from collections.abc import Iterator
from http.server import HTTPServer
from pathlib import Path
from typing import Any

import pytest
from werkzeug.serving import BaseWSGIServer, make_server

import ai_intervention_agent.web_ui as web_ui
from ai_intervention_agent.web_ui import (
    WebFeedbackUI,
    ensure_bind_without_reverse_dns,
)

WEB_UI_PATH = Path(web_ui.__file__).resolve()
TEMPLATE = Path(__file__).resolve().parent.parent / "config.toml.default"
STALL_SECONDS = 90
START_WITHIN_SECONDS = 30


def hello_app(environ: Any, start_response: Any) -> list[bytes]:
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"hello"]


def no_lookup(name: str = "") -> str:
    raise AssertionError(f"reverse lookup of {name!r}")


@pytest.fixture
def stock_werkzeug(monkeypatch: pytest.MonkeyPatch) -> None:
    """Werkzeug as it ships: the server class inherits ``HTTPServer.server_bind``."""
    monkeypatch.setattr(BaseWSGIServer, "server_bind", HTTPServer.server_bind)


def test_stock_werkzeug_asks_for_the_name_of_the_bind_address(
    stock_werkzeug: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def getfqdn(name: str = "") -> str:
        asked.append(name)
        return "recorded.example"

    monkeypatch.setattr(socket, "getfqdn", getfqdn)

    server = make_server("127.0.0.1", 0, hello_app)
    try:
        assert asked == ["127.0.0.1"]
        assert server.server_name == "recorded.example"
    finally:
        server.server_close()


def test_the_override_is_installed_once(stock_werkzeug: None) -> None:
    assert ensure_bind_without_reverse_dns() is True
    installed = BaseWSGIServer.server_bind
    assert installed is not HTTPServer.server_bind

    assert ensure_bind_without_reverse_dns() is False
    assert BaseWSGIServer.server_bind is installed


def test_a_werkzeug_with_its_own_server_bind_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def own_server_bind(self: Any) -> None:
        raise AssertionError("never called")

    monkeypatch.setattr(BaseWSGIServer, "server_bind", own_server_bind)

    assert ensure_bind_without_reverse_dns() is False
    assert BaseWSGIServer.server_bind is own_server_bind


def test_a_server_binds_without_asking_for_a_name(
    stock_werkzeug: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_bind_without_reverse_dns()
    monkeypatch.setattr(socket, "getfqdn", no_lookup)

    server = make_server("127.0.0.1", 0, hello_app, threaded=True)
    try:
        port = server.server_address[1]
        assert port != 0
        assert server.server_name == "127.0.0.1"
        assert server.server_port == port
    finally:
        server.server_close()


def test_a_server_that_bound_without_a_name_answers_requests(
    stock_werkzeug: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_bind_without_reverse_dns()
    monkeypatch.setattr(socket, "getfqdn", no_lookup)

    server = make_server("127.0.0.1", 0, hello_app, threaded=True)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.05), daemon=True
    )
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.status == 200
            assert response.read() == b"hello"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_creating_the_web_ui_installs_the_override(stock_werkzeug: None) -> None:
    assert BaseWSGIServer.server_bind is HTTPServer.server_bind

    WebFeedbackUI(prompt="", auto_resubmit_timeout=0)

    assert BaseWSGIServer.server_bind is not HTTPServer.server_bind


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_config(path: Path) -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    old = 'enabled = "auto"'
    assert text.count(old) == 1
    path.write_text(text.replace(old, "enabled = false"), encoding="utf-8")


def is_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return int(response.status) == 200
    except OSError:
        return False


@pytest.fixture
def slow_lookup_script(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """The real ``web_ui.py``, started the way ``ServiceManager`` starts it, in a
    process where ``socket.getfqdn`` takes ``STALL_SECONDS``."""
    config = tmp_path / "config.toml"
    write_config(config)
    log_path = tmp_path / "web_ui.log"
    port = free_port()
    launcher = textwrap.dedent(
        f"""
        import os, runpy, socket, sys, time

        def stalled(name=""):
            time.sleep({STALL_SECONDS})
            return name

        socket.getfqdn = stalled
        script = {str(WEB_UI_PATH)!r}
        sys.path.insert(0, os.path.dirname(script))
        sys.argv = [script, "--prompt", "", "--host", "127.0.0.1", "--port", "{port}"]
        runpy.run_path(script, run_name="__main__")
        """
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AI_INTERVENTION_AGENT_")
    }
    env["AI_INTERVENTION_AGENT_CONFIG_FILE"] = str(config)
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", launcher],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        try:
            yield f"http://127.0.0.1:{port}", log_path
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_a_real_web_ui_starts_while_the_name_lookup_stalls(
    slow_lookup_script: tuple[str, Path],
) -> None:
    base, log_path = slow_lookup_script
    deadline = time.monotonic() + START_WITHIN_SECONDS
    while time.monotonic() < deadline:
        if is_healthy(f"{base}/api/health"):
            return
        time.sleep(0.25)
    pytest.fail(
        f"the Web UI was not up {START_WITHIN_SECONDS} s after the start "
        f"(a name lookup of {STALL_SECONDS} s must not hold it back)\n"
        + log_path.read_text(encoding="utf-8", errors="replace")
    )
