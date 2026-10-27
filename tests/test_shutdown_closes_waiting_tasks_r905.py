"""R905: a question that is still waiting for its answer must not outlive the process that asked it.

What was wrong.  ``interactive_feedback`` creates its task in the Web UI and waits.  When the person
closes the IDE window the MCP client closes stdin (or sends SIGTERM) and the server exits.  The
clean-up of an abandoned wait (R13, made independent of the caller's cancellation by R775) lives in
the event loop: it was started, sent its first request, and the loop ended, so ``asyncio.run``
cancelled it before the ``POST /api/tasks/<id>/close`` was sent.  Nothing else closed the task:

* the window that started the Web UI terminates it on the way out, and the task stays in
  ``tasks-<port>.json``; the next Web UI on that port (the next IDE session, or the revival of
  R825) restores it, and the page shows a question nobody is waiting for as the *active* task, with
  the new question behind it.  What the person types into the old one goes nowhere;
* a window that only *used* a Web UI another window had started stays in the shared queue as a
  pending task, for as long as that Web UI lives.

A real stdio MCP server and a real Web UI child showed both: after a graceful close the snapshot
still held the task (and the next session listed it first); and a second window closed while the
first one lived left its task pending in the live Web UI.  A window that only used somebody else's
Web UI had no ``ServiceManager`` at all (it is created when a process starts a Web UI itself), so it
had no atexit hook and no signal handler either.  And in the window that did start the Web UI the
manager's SIGINT / SIGTERM handlers were never installed: the first manager is built in the worker
thread of ``asyncio.to_thread``, where ``signal.signal`` raises ValueError (logged at DEBUG as "not
the main thread").  SIGTERM ended every real server on the spot: no atexit, no clean-up, status -15.

What it is now.  ``interactive_feedback`` lists every task it creates (``_INFLIGHT_TASKS``) and takes
it off the list when the answer was handed to the caller, when a close was confirmed (200 / 404) or
when the Web UI refused the task (4xx) or could not be reached.  The first listing installs three
exit paths for ``_close_inflight_tasks_sync``, which is synchronous, independent of the event loop
and bounded in time: a hook in ``ServiceManager.cleanup_all`` (it runs *before* the Web UI is
terminated; Ctrl-C and the retry after an error get there through ``cleanup_services``), an atexit
callback (a closed stdin), and, when nobody handles SIGTERM, a handler that closes the tasks and
then lets the process die of the signal as before.  It deliberately does not build a
``ServiceManager``: built on the main thread that installs handlers whose ``KeyboardInterrupt``
leaves the interpreter waiting for the thread that is blocked on stdin, and the process never exits.

What is checked.  A real child interpreter against a loopback Web UI, with and without a
``ServiceManager`` built in a worker thread the way the real server does it: the runner cancels the
call and the loop ends at once (what a closed stdin does), Ctrl-C, and SIGTERM with a thread blocked
on stdin (the process must still die of the signal, promptly, with the task closed).  The order in
``cleanup_all``.  The close requests themselves, against a real server: one each, the 404, an
unreachable Web UI, one that never answers.  The exit paths one by one.  And the bookkeeping on the
list through every way a call can end.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anyio
import httpx
import pytest

import ai_intervention_agent.server_config as server_config
import ai_intervention_agent.server_feedback as server_feedback
import ai_intervention_agent.service_manager as service_manager
from ai_intervention_agent.server_config import WebUIConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

# tests/conftest.py makes every ``httpx.Client.send`` raise, so that no test reaches a network.
# The shutdown helper really talks to a loopback server here, so keep the real one from import time
# (before any fixture runs).
_REAL_CLIENT_SEND = httpx.Client.send

TASK = "r905-task"
BASE_URL = "http://127.0.0.1:18905"


@pytest.fixture(autouse=True)
def shutdown_machinery_of_its_own(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No hook, no ``ServiceManager``, no atexit entry and no signal handler outlive a test.

    Listing a task builds the exit machinery for the process (that is the point); a test must
    neither inherit the one an earlier test built nor leave its own behind.
    """
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    monkeypatch.setattr(service_manager, "_pre_shutdown_hooks", [])
    monkeypatch.setattr(service_manager.ServiceManager, "_instance", None)
    monkeypatch.setattr(service_manager.ServiceManager, "_lock", threading.Lock())
    try:
        yield
    finally:
        built = service_manager.ServiceManager._instance
        if built is not None:
            atexit.unregister(built.cleanup_all)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


# --------------------------------------------------------------------------- a Web UI on the loopback


class FakeWebUI:
    """Just enough of the Web UI for a waiting call, on a real loopback socket.

    ``tasks`` is its queue, ``created`` / ``close_requests`` / ``removed`` what it was asked
    and did.  ``get_latency_s`` slows ``GET /api/tasks/<id>`` down the way a real server is slow
    (a few milliseconds): the clean-up of an abandoned wait starts with that request, and the
    loop must be gone before it comes back.  ``close_latency_s`` makes ``/close`` hang.
    """

    def __init__(
        self, *, get_latency_s: float = 0.0, close_latency_s: float = 0.0
    ) -> None:
        self.tasks: dict[str, str] = {}
        self.created: list[str] = []
        self.close_requests: list[str] = []
        self.removed: list[str] = []
        self.get_latency_s = get_latency_s
        self.close_latency_s = close_latency_s
        self._stop = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                path = self.path
                if path == "/api/health":
                    self._json(200, {"status": "ok"})
                elif path == "/api/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    outer._stop.wait()
                elif path == "/api/tasks":
                    tasks = [
                        {"task_id": task_id, "status": status}
                        for task_id, status in outer.tasks.items()
                    ]
                    self._json(200, {"success": True, "tasks": tasks})
                elif path.startswith("/api/tasks/"):
                    time.sleep(outer.get_latency_s)
                    task_id = path.rsplit("/", 1)[1]
                    if task_id in outer.tasks:
                        task = {"task_id": task_id, "status": outer.tasks[task_id]}
                        self._json(200, {"success": True, "task": task})
                    else:
                        self._json(404, {"success": False})
                else:
                    self._json(404, {"success": False})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if self.path == "/api/tasks":
                    task_id = json.loads(raw)["task_id"]
                    outer.created.append(task_id)
                    outer.tasks[task_id] = "pending"
                    self._json(200, {"success": True, "task_id": task_id})
                elif self.path.startswith("/api/tasks/") and self.path.endswith(
                    "/close"
                ):
                    task_id = self.path.split("/")[3]
                    outer.close_requests.append(task_id)
                    if outer.close_latency_s:
                        outer._stop.wait(outer.close_latency_s)
                    if outer.tasks.pop(task_id, None) is None:
                        self._json(404, {"success": False})
                    else:
                        outer.removed.append(task_id)
                        self._json(200, {"success": True})
                else:
                    self._json(404, {"success": False})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(5)


@pytest.fixture
def real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx.Client, "send", _REAL_CLIENT_SEND)


@pytest.fixture
def web_ui() -> Iterator[FakeWebUI]:
    fake = FakeWebUI(get_latency_s=0.15)
    try:
        yield fake
    finally:
        fake.stop()


# --------------------------------------------------------------------------- a real child interpreter

CHILD = r"""
import asyncio
import sys
import threading

import anyio
import httpx

import ai_intervention_agent.server_config as server_config
import ai_intervention_agent.server_feedback as server_feedback
import ai_intervention_agent.service_manager as service_manager

port = int(sys.argv[1])
mode = sys.argv[2]
manager = sys.argv[3]
hold_stdin = sys.argv[4] == "1"
config = server_config.WebUIConfig(
    host="127.0.0.1",
    port=port,
    language="auto",
    timeout=5,
    max_retries=0,
    retry_delay=0.1,
    external_base_url="",
)
service_manager.get_web_ui_config = lambda: (config, 120)


async def the_web_ui_is_up(*_args, **_kwargs):
    if manager == "worker-thread":
        # What ``start_web_service`` does in the real server: the first ServiceManager is built in
        # the worker thread of ``asyncio.to_thread``, where it cannot install its signal handlers.
        await asyncio.to_thread(service_manager.ServiceManager)
    # "none": the Web UI belongs to another window; this process only uses it and has no manager.


service_manager.ensure_web_ui_running = the_web_ui_is_up
server_feedback.NOTIFICATION_AVAILABLE = False

if hold_stdin:
    # anyio reads the MCP client's stdin in a non-daemon worker thread.  While the pipe is open it
    # keeps the interpreter from finishing, as soon as the main thread is done.
    threading.Thread(target=sys.stdin.buffer.readline).start()


async def ask():
    await server_feedback.interactive_feedback(
        message="question",
        predefined_options=None,
        feedback_placeholder=None,
        header_label=None,
        loop_id=None,
        loop_objective=None,
        loop_phase=None,
        success_criteria=None,
        iteration_label=None,
        ctx=None,
    )


async def until_the_web_ui_has_the_task():
    async with httpx.AsyncClient(trust_env=False) as client:
        while True:
            reply = await client.get(f"http://127.0.0.1:{port}/api/tasks")
            if reply.json()["tasks"]:
                return
            await asyncio.sleep(0.02)


async def main():
    if mode == "cancel":
        # What a closed stdin does: the runner cancels the call, and with nothing left to serve
        # the loop ends at once.
        async with anyio.create_task_group() as group:
            group.start_soon(ask)
            await until_the_web_ui_has_the_task()
            group.cancel_scope.cancel()
    else:
        await ask()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
print("EXITING", flush=True)
"""


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _start_child(
    port: int, mode: str, *, manager: str = "none", hold_stdin: bool = False
) -> subprocess.Popen[str]:
    """``manager``: ``"none"`` (a Web UI that belongs to another window) or ``"worker-thread"``
    (the process started the Web UI itself: its ServiceManager is built off the main thread).
    ``hold_stdin``: a non-daemon thread blocks on the stdin pipe, which stays open.
    """
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            CHILD,
            str(port),
            mode,
            manager,
            "1" if hold_stdin else "0",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_child_env(),
        cwd=str(REPO_ROOT),
    )


def _wait_until(
    condition: Callable[[], bool], what: str, timeout_s: float = 60
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def _drain(child: subprocess.Popen[str]) -> str:
    stderr = child.stderr.read() if child.stderr else ""
    for pipe in (child.stdin, child.stdout, child.stderr):
        if pipe:
            pipe.close()
    return stderr


def _finish(child: subprocess.Popen[str], timeout_s: float = 60) -> tuple[int, str]:
    # ``communicate`` would close the stdin pipe first, and a thread blocked on it would end:
    # exactly the hang a test with ``hold_stdin`` is there to catch.
    try:
        child.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        raise AssertionError(f"the child did not exit:\n{_drain(child)}") from None
    return child.returncode, _drain(child)


BOTH_KINDS_OF_PROCESS = pytest.mark.parametrize("manager", ["none", "worker-thread"])


class TestExitOfARealProcess:
    @BOTH_KINDS_OF_PROCESS
    def test_the_runner_cancelling_the_call_and_the_loop_ending_closes_the_task(
        self, web_ui: FakeWebUI, manager: str
    ) -> None:
        child = _start_child(web_ui.port, "cancel", manager=manager)

        code, stderr = _finish(child)

        assert code == 0, stderr
        assert len(web_ui.created) == 1
        assert web_ui.removed == web_ui.created, (
            f"the task the call created is still in the Web UI: {web_ui.tasks}\n{stderr}"
        )
        assert web_ui.tasks == {}

    @BOTH_KINDS_OF_PROCESS
    def test_ctrl_c_during_the_wait_closes_the_task(
        self, web_ui: FakeWebUI, manager: str
    ) -> None:
        child = _start_child(web_ui.port, "wait", manager=manager)
        _wait_until(lambda: bool(web_ui.created), "the child to create its task")

        child.send_signal(signal.SIGINT)
        code, stderr = _finish(child)

        assert code == 0, stderr
        assert web_ui.removed == web_ui.created, (
            f"the task the call created is still in the Web UI: {web_ui.tasks}\n{stderr}"
        )
        assert web_ui.close_requests == web_ui.created

    @BOTH_KINDS_OF_PROCESS
    def test_sigterm_during_the_wait_closes_the_task_and_the_process_still_dies_of_it(
        self, web_ui: FakeWebUI, manager: str
    ) -> None:
        child = _start_child(web_ui.port, "wait", manager=manager, hold_stdin=True)
        _wait_until(lambda: bool(web_ui.created), "the child to create its task")

        child.terminate()
        # promptly, and with the stdin pipe still open: nothing may wait for the blocked thread
        code, stderr = _finish(child, timeout_s=30)

        assert code == -signal.SIGTERM, stderr
        assert web_ui.removed == web_ui.created, (
            f"the task the call created is still in the Web UI: {web_ui.tasks}\n{stderr}"
        )
        assert web_ui.tasks == {}
        assert web_ui.close_requests == web_ui.created


# --------------------------------------------------------------------------- cleanup_all runs the hooks first


def _manager_with_a_running_web_ui(
    monkeypatch: pytest.MonkeyPatch, events: list[str]
) -> Any:
    manager = service_manager.ServiceManager()
    process = MagicMock()
    process.poll.return_value = None
    manager.register_process(
        "web_ui_test", process, WebUIConfig(host="127.0.0.1", port=18905)
    )
    monkeypatch.setattr(
        manager,
        "terminate_process",
        lambda name, *_args, **_kwargs: events.append(f"terminate {name}") or True,
    )
    return manager


class TestCleanupAllRunsTheHooksFirst:
    def test_the_hooks_run_before_a_process_is_terminated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[str] = []
        manager = _manager_with_a_running_web_ui(monkeypatch, events)
        service_manager.register_pre_shutdown_hook(lambda: events.append("hook"))

        manager.cleanup_all(shutdown_notification_manager=False)

        assert events == ["hook", "terminate web_ui_test"]

    def test_a_hook_that_fails_does_not_stop_the_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[str] = []
        manager = _manager_with_a_running_web_ui(monkeypatch, events)

        def explode() -> None:
            raise RuntimeError("hook blew up")

        service_manager.register_pre_shutdown_hook(explode)
        service_manager.register_pre_shutdown_hook(lambda: events.append("second hook"))

        manager.cleanup_all(shutdown_notification_manager=False)

        assert events == ["second hook", "terminate web_ui_test"]

    def test_a_hook_is_registered_once(self) -> None:
        calls: list[int] = []

        def hook() -> None:
            calls.append(1)

        service_manager.register_pre_shutdown_hook(hook)
        service_manager.register_pre_shutdown_hook(hook)

        service_manager.ServiceManager().cleanup_all(
            shutdown_notification_manager=False
        )

        assert calls == [1]


# --------------------------------------------------------------------------- the exit paths one by one


@pytest.fixture
def sigterm_is_default() -> None:
    """A fresh server process starts with SIGTERM at its default (the fixture above restores it)."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _record_atexit(monkeypatch: pytest.MonkeyPatch) -> tuple[list[Any], list[Any]]:
    registered: list[Any] = []
    unregistered: list[Any] = []
    monkeypatch.setattr(
        atexit, "register", lambda fn, *_a, **_k: registered.append(fn) or fn
    )
    monkeypatch.setattr(atexit, "unregister", unregistered.append)
    return registered, unregistered


@pytest.mark.usefixtures("sigterm_is_default")
class TestTheExitPaths:
    def test_listing_a_task_installs_the_three_exit_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registered, _ = _record_atexit(monkeypatch)

        server_feedback._track_task(TASK, BASE_URL)

        closer = server_feedback._close_inflight_tasks_sync
        assert service_manager._pre_shutdown_hooks == [closer]
        assert registered == [closer]
        assert signal.getsignal(signal.SIGTERM) is server_feedback._close_tasks_then_die
        assert server_feedback._INFLIGHT_TASKS == {TASK: BASE_URL}

    def test_it_does_not_build_a_service_manager(self) -> None:
        # Built on the main thread the manager installs SIGINT / SIGTERM handlers that raise
        # KeyboardInterrupt.  The interpreter then waits, on the way out, for anyio's worker thread
        # that is blocked on stdin, and the process of a real server never exits.
        server_feedback._track_task(TASK, BASE_URL)

        assert service_manager.ServiceManager._instance is None

    def test_a_second_listing_installs_nothing_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registered, _ = _record_atexit(monkeypatch)

        server_feedback._track_task("a", BASE_URL)
        server_feedback._track_task("b", BASE_URL)

        assert registered == [server_feedback._close_inflight_tasks_sync]
        assert service_manager._pre_shutdown_hooks == [
            server_feedback._close_inflight_tasks_sync
        ]
        assert list(server_feedback._INFLIGHT_TASKS) == ["a", "b"]

    @pytest.mark.parametrize("disposition", ["ignored", "handled"])
    def test_a_sigterm_that_is_ignored_or_handled_is_left_alone(
        self, disposition: str
    ) -> None:
        other: Any = signal.SIG_IGN if disposition == "ignored" else (lambda *_a: None)
        signal.signal(signal.SIGTERM, other)

        server_feedback._track_task(TASK, BASE_URL)

        assert signal.getsignal(signal.SIGTERM) is other

    def test_off_the_main_thread_nothing_fails_and_the_next_listing_tries_again(
        self,
    ) -> None:
        errors: list[BaseException] = []

        def list_a_task_from_a_worker_thread() -> None:
            try:
                server_feedback._track_task("from-a-thread", BASE_URL)
            except BaseException as error:  # whatever it is, the test reports it
                errors.append(error)

        worker = threading.Thread(target=list_a_task_from_a_worker_thread)
        worker.start()
        worker.join()

        assert errors == []
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
        assert "from-a-thread" in server_feedback._INFLIGHT_TASKS

        server_feedback._track_task("from-the-main-thread", BASE_URL)

        assert signal.getsignal(signal.SIGTERM) is server_feedback._close_tasks_then_die

    @pytest.mark.usefixtures("real_http")
    def test_the_sigterm_handler_closes_the_tasks_then_dies_of_the_signal(
        self, web_ui: FakeWebUI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        killed: list[tuple[int, int]] = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
        web_ui.tasks["a"] = "pending"
        server_feedback._track_task("a", web_ui.base_url)
        handler: Any = signal.getsignal(signal.SIGTERM)
        assert handler is server_feedback._close_tasks_then_die

        handler(signal.SIGTERM, None)

        assert web_ui.removed == ["a"]
        assert killed == [(os.getpid(), signal.SIGTERM)]
        # the signal is sent with its default action back in place: that is what ends the process
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL

    def test_the_sigterm_handler_dies_of_the_signal_even_if_closing_blows_up(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        killed: list[tuple[int, int]] = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

        def blow_up() -> None:
            raise RuntimeError("closing blew up")

        monkeypatch.setattr(server_feedback, "_close_inflight_tasks_sync", blow_up)

        with pytest.raises(RuntimeError, match="closing blew up"):
            server_feedback._close_tasks_then_die(signal.SIGTERM, None)

        assert killed == [(os.getpid(), signal.SIGTERM)]

    def test_the_conftest_reset_takes_every_exit_path_away_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, unregistered = _record_atexit(monkeypatch)
        server_feedback._track_task(TASK, BASE_URL)

        server_feedback.reset_inflight_tasks_for_testing()

        assert server_feedback._INFLIGHT_TASKS == {}
        assert service_manager._pre_shutdown_hooks == []
        assert unregistered == [server_feedback._close_inflight_tasks_sync]
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


# --------------------------------------------------------------------------- the close requests themselves


@pytest.mark.usefixtures("real_http")
class TestClosingWhatIsStillWaiting:
    def test_each_task_gets_one_close_and_leaves_the_list(
        self, web_ui: FakeWebUI
    ) -> None:
        for task_id in ("a", "b"):
            web_ui.tasks[task_id] = "pending"
            server_feedback._track_task(task_id, web_ui.base_url)

        server_feedback._close_inflight_tasks_sync()

        assert sorted(web_ui.close_requests) == ["a", "b"]
        assert web_ui.tasks == {}
        assert server_feedback._INFLIGHT_TASKS == {}

    def test_a_task_the_web_ui_no_longer_has_counts_as_closed(
        self, web_ui: FakeWebUI
    ) -> None:
        server_feedback._track_task("gone", web_ui.base_url)

        server_feedback._close_inflight_tasks_sync()

        assert web_ui.close_requests == ["gone"]
        assert server_feedback._INFLIGHT_TASKS == {}

    @pytest.mark.parametrize(
        ("task_id", "sent"),
        [("a b", "a%20b"), ("a/b?c#d", "a%2Fb%3Fc%23d")],
    )
    def test_the_id_is_quoted_into_the_path(
        self, web_ui: FakeWebUI, task_id: str, sent: str
    ) -> None:
        web_ui.tasks[task_id] = "pending"
        server_feedback._track_task(task_id, web_ui.base_url)

        server_feedback._close_inflight_tasks_sync()

        # the fake splits the path as it arrives; unquoted, the second id would turn into a
        # different path (and a query string) and the close would never reach the route
        assert web_ui.close_requests == [sent]

    def test_tasks_of_two_web_uis_go_to_their_own(self, web_ui: FakeWebUI) -> None:
        other = FakeWebUI()
        try:
            web_ui.tasks["mine"] = "pending"
            other.tasks["theirs"] = "pending"
            server_feedback._track_task("mine", web_ui.base_url)
            server_feedback._track_task("theirs", other.base_url)

            server_feedback._close_inflight_tasks_sync()

            assert web_ui.close_requests == ["mine"]
            assert other.close_requests == ["theirs"]
        finally:
            other.stop()

    def test_a_web_ui_that_is_gone_is_survived_and_the_entries_stay(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server_feedback._track_task("lost", f"http://127.0.0.1:{port}")

        started = time.monotonic()
        server_feedback._close_inflight_tasks_sync()

        assert time.monotonic() - started < server_feedback._SHUTDOWN_CLOSE_BUDGET_S
        assert list(server_feedback._INFLIGHT_TASKS) == ["lost"]

    def test_a_proxy_in_the_environment_is_not_used(
        self, web_ui: FakeWebUI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The Web UI is on this machine.  A shell with HTTP_PROXY set (a common setup) must not
        # send the close to the proxy, which cannot reach it.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            dead_proxy = f"http://127.0.0.1:{sock.getsockname()[1]}"
        for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(name, dead_proxy)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        web_ui.tasks["a"] = "pending"
        server_feedback._track_task("a", web_ui.base_url)

        server_feedback._close_inflight_tasks_sync()

        assert web_ui.removed == ["a"]

    def test_no_request_may_outlast_what_is_left_of_the_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A clock the test moves, and a Web UI that uses up every timeout it is given: what each
        # request was allowed shows how the budget is shared out (all numbers exact in binary).
        now = [1000.0]
        allowed: list[float] = []

        class AWebUIThatNeverAnswers:
            def __init__(self, **_kwargs: Any) -> None:
                pass

            def __enter__(self) -> AWebUIThatNeverAnswers:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def post(self, _url: str, *, timeout: float) -> httpx.Response:
                allowed.append(timeout)
                now[0] += timeout
                raise httpx.ReadTimeout("the Web UI does not answer")

        monkeypatch.setattr(httpx, "Client", AWebUIThatNeverAnswers)
        monkeypatch.setattr(
            server_feedback, "time", SimpleNamespace(monotonic=lambda: now[0])
        )
        monkeypatch.setattr(server_feedback, "_SHUTDOWN_CLOSE_BUDGET_S", 1.0)
        monkeypatch.setattr(server_feedback, "_SHUTDOWN_CLOSE_REQUEST_TIMEOUT_S", 0.75)
        for index in range(5):
            server_feedback._track_task(f"t{index}", BASE_URL)

        server_feedback._close_inflight_tasks_sync()

        # the second request gets what is left of the second, the third finds nothing left
        assert allowed == [0.75, 0.25]
        assert len(server_feedback._INFLIGHT_TASKS) == 5

    def test_a_web_ui_that_does_not_answer_cannot_hold_the_exit_up(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stuck = FakeWebUI(close_latency_s=30)
        monkeypatch.setattr(server_feedback, "_SHUTDOWN_CLOSE_BUDGET_S", 0.3)
        monkeypatch.setattr(server_feedback, "_SHUTDOWN_CLOSE_REQUEST_TIMEOUT_S", 0.2)
        try:
            for index in range(6):
                server_feedback._track_task(f"t{index}", stuck.base_url)

            started = time.monotonic()
            server_feedback._close_inflight_tasks_sync()
            elapsed = time.monotonic() - started

            # one request per 0.2 s would need 1.2 s for all six; the budget stops it at 0.3 s
            assert len(stuck.close_requests) < 6
            assert elapsed < 1.0
            assert len(server_feedback._INFLIGHT_TASKS) == 6
        finally:
            stuck.stop()

    def test_a_client_that_cannot_be_built_does_not_break_the_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_client_today(**_kwargs: Any) -> None:
            raise RuntimeError("no client today")

        monkeypatch.setattr(httpx, "Client", no_client_today)
        server_feedback._track_task("a", BASE_URL)

        server_feedback._close_inflight_tasks_sync()

        assert list(server_feedback._INFLIGHT_TASKS) == ["a"]

    def test_an_empty_list_makes_no_request_and_builds_no_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("a client was built for an empty list")

        monkeypatch.setattr(httpx, "Client", boom)

        server_feedback._close_inflight_tasks_sync()

    def test_a_status_that_is_not_a_close_leaves_the_task_on_the_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_client = httpx.Client

        def limited_client(**kwargs: Any) -> httpx.Client:
            kwargs["transport"] = httpx.MockTransport(
                lambda _request: httpx.Response(429)
            )
            return real_client(**kwargs)

        monkeypatch.setattr(httpx, "Client", limited_client)
        server_feedback._track_task("limited", "http://127.0.0.1:1")

        server_feedback._close_inflight_tasks_sync()

        assert list(server_feedback._INFLIGHT_TASKS) == ["limited"]


# --------------------------------------------------------------------------- the list follows a task


class AsyncClientStub:
    """What the tool and the wait use of ``httpx.AsyncClient`` (the real one is blocked in tests).

    ``create`` answers ``POST /api/tasks`` and ``close`` answers ``POST /api/tasks/<id>/close``:
    each is a status code or an exception to raise, and ``create_hangs`` makes the creation request
    never return.  ``polled`` is what ``GET /api/tasks/<id>`` says about the task (``polled_after_close``
    once a close was posted).  There is no event stream unless a test assigns ``stream``.
    """

    def __init__(
        self,
        *,
        create: int | Exception = 200,
        close: int | Exception = 200,
        create_hangs: bool = False,
        polled: dict[str, Any] | None = None,
        polled_after_close: dict[str, Any] | None = None,
    ) -> None:
        self.create = create
        self.close = close
        self.create_hangs = create_hangs
        self.polled = polled or {"status": "pending", "result": None}
        self.polled_after_close = polled_after_close
        self.posts: list[str] = []
        self.stream = MagicMock(
            side_effect=RuntimeError("no event stream in this test")
        )

    async def post(self, url: str, **_kwargs: Any) -> httpx.Response:
        await asyncio.sleep(0)
        self.posts.append(url)
        if self.create_hangs and not url.endswith("/close"):
            await asyncio.Event().wait()
        outcome = self.close if url.endswith("/close") else self.create
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, json={"success": outcome == 200})

    async def get(self, url: str, **_kwargs: Any) -> httpx.Response:
        await asyncio.sleep(0)
        closed = any(posted.endswith("/close") for posted in self.posts)
        task = (
            self.polled_after_close
            if closed and self.polled_after_close
            else self.polled
        )
        return httpx.Response(200, json={"success": True, "task": task})


class EventStream:
    """What ``client.stream(...)`` returns: an async context manager that yields some lines."""

    def __init__(self, *events: dict[str, Any]) -> None:
        self.lines = [f"data: {json.dumps(event)}" for event in events]

    async def __aenter__(self) -> EventStream:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self.lines:
            yield line


@pytest.fixture
def web_ui_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    sm = server_feedback.service_manager

    async def already_running(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        sm,
        "get_web_ui_config",
        lambda: (WebUIConfig(host="127.0.0.1", port=18905), 120),
    )
    monkeypatch.setattr(sm, "ensure_web_ui_running", already_running)
    monkeypatch.setattr(server_feedback, "NOTIFICATION_AVAILABLE", False)
    monkeypatch.setattr(server_config, "_generate_task_id", lambda: TASK)
    monkeypatch.setattr(server_config, "BACKEND_MIN", 1)
    monkeypatch.setattr(server_feedback, "_FETCH_RETRY_BACKOFF_S", (0.0,))


def _use(monkeypatch: pytest.MonkeyPatch, client: AsyncClientStub) -> None:
    monkeypatch.setattr(
        server_feedback.service_manager, "get_async_client", lambda _config: client
    )


def _the_tool() -> Coroutine[Any, Any, Any]:
    return server_feedback.interactive_feedback(
        message="r905 question",
        predefined_options=None,
        feedback_placeholder=None,
        header_label=None,
        loop_id=None,
        loop_objective=None,
        loop_phase=None,
        success_criteria=None,
        iteration_label=None,
        ctx=None,
    )


async def _until_no_cleanup_is_running() -> None:
    while server_feedback._DETACHED_CLEANUPS:
        await asyncio.sleep(0.01)


@pytest.mark.usefixtures("web_ui_stub")
class TestTheListFollowsATask:
    def test_the_task_a_call_creates_is_listed_while_it_waits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = AsyncClientStub()
        _use(monkeypatch, client)
        seen: list[dict[str, str]] = []

        async def scenario() -> None:
            async with anyio.create_task_group() as group:
                group.start_soon(_the_tool)
                while not any(url.endswith("/api/tasks") for url in client.posts):
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.05)
                seen.append(dict(server_feedback._INFLIGHT_TASKS))
                group.cancel_scope.cancel()
            await _until_no_cleanup_is_running()

        asyncio.run(scenario())

        assert seen == [{TASK: BASE_URL}]

    def test_an_answer_takes_the_task_off_the_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = AsyncClientStub(
            polled={
                "status": "completed",
                "result": {"user_feedback": "yes", "selected_options": []},
            }
        )
        _use(monkeypatch, client)

        asyncio.run(_the_tool())

        assert server_feedback._INFLIGHT_TASKS == {}
        assert not any(url.endswith("/close") for url in client.posts)

    def test_a_call_cancelled_while_the_task_is_being_created_stays_listed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The Web UI may have taken the task before the cancellation arrived, and the close that
        # follows is not confirmed here (500): the exit has to try again.
        client = AsyncClientStub(create_hangs=True, close=500)
        _use(monkeypatch, client)

        async def scenario() -> None:
            async with anyio.create_task_group() as group:
                group.start_soon(_the_tool)
                while not client.posts:
                    await asyncio.sleep(0.01)
                group.cancel_scope.cancel()
            await _until_no_cleanup_is_running()

        asyncio.run(scenario())

        assert list(server_feedback._INFLIGHT_TASKS) == [TASK]

    @pytest.mark.parametrize("status", [400, 409, 413, 429])
    def test_a_task_the_web_ui_refused_leaves_nothing_to_close(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        client = AsyncClientStub(create=status)
        _use(monkeypatch, client)

        asyncio.run(_the_tool())

        assert server_feedback._INFLIGHT_TASKS == {}

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_a_server_error_may_have_come_after_the_queue_took_the_task(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        client = AsyncClientStub(create=status)
        _use(monkeypatch, client)

        asyncio.run(_the_tool())

        assert list(server_feedback._INFLIGHT_TASKS) == [TASK]

    def test_a_request_that_never_left_leaves_nothing_to_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = AsyncClientStub(
            create=httpx.ConnectError("nothing listens"),
            close=httpx.ConnectError("nothing listens"),
        )
        _use(monkeypatch, client)

        asyncio.run(_the_tool())

        assert server_feedback._INFLIGHT_TASKS == {}

    @pytest.mark.parametrize(
        ("close", "listed"), [(200, False), (404, False), (500, True)]
    )
    def test_an_answer_that_never_arrived_is_off_the_list_once_the_close_is_confirmed(
        self, monkeypatch: pytest.MonkeyPatch, close: int, listed: bool
    ) -> None:
        client = AsyncClientStub(
            create=httpx.ReadTimeout("the answer did not arrive in time"), close=close
        )
        _use(monkeypatch, client)

        asyncio.run(_the_tool())

        assert (TASK in server_feedback._INFLIGHT_TASKS) is listed

    @pytest.mark.parametrize(
        ("close", "listed"), [(200, False), (404, False), (500, True)]
    )
    def test_a_wait_that_timed_out_is_off_the_list_once_the_close_is_confirmed(
        self, monkeypatch: pytest.MonkeyPatch, close: int, listed: bool
    ) -> None:
        client = AsyncClientStub(close=close)
        _use(monkeypatch, client)
        server_feedback._track_task(TASK, BASE_URL)

        asyncio.run(server_feedback.wait_for_task_completion(TASK, timeout=1))

        assert (TASK in server_feedback._INFLIGHT_TASKS) is listed

    def test_the_wait_takes_an_answered_task_off_the_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = AsyncClientStub(
            polled={"status": "completed", "result": {"user_feedback": "yes"}}
        )
        _use(monkeypatch, client)
        server_feedback._track_task(TASK, BASE_URL)

        result = asyncio.run(server_feedback.wait_for_task_completion(TASK, timeout=5))

        assert result == {"user_feedback": "yes"}
        assert server_feedback._INFLIGHT_TASKS == {}

    def test_an_answer_that_turns_up_after_a_refused_close_takes_the_task_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The event stream says "completed" before the answer can be read; the clean-up of an
        # unanswered task looks once more and finds nothing, and its close is refused (500, so the
        # task stays listed); the answer is there when the wait looks for the last time.
        client = AsyncClientStub(
            close=500,
            polled_after_close={
                "status": "completed",
                "result": {"user_feedback": "late"},
            },
        )
        client.stream = MagicMock(
            side_effect=lambda *_a, **_k: EventStream(
                {"task_id": TASK, "new_status": "completed"}
            )
        )
        _use(monkeypatch, client)
        server_feedback._track_task(TASK, BASE_URL)

        result = asyncio.run(server_feedback.wait_for_task_completion(TASK, timeout=5))

        assert result == {"user_feedback": "late"}
        assert any(url.endswith("/close") for url in client.posts)
        assert server_feedback._INFLIGHT_TASKS == {}

    def test_the_wait_does_not_touch_another_calls_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = AsyncClientStub(
            polled={"status": "completed", "result": {"user_feedback": "yes"}}
        )
        _use(monkeypatch, client)
        server_feedback._track_task("other", BASE_URL)

        asyncio.run(server_feedback.wait_for_task_completion(TASK, timeout=5))

        assert list(server_feedback._INFLIGHT_TASKS) == ["other"]


class TestTheConftestStartsEveryTestWithAnEmptyList:
    """Two tests that rely on running in this order, like the pairs of ``test_conftest_isolation_r762``.

    An entry left in the list is closed when the pytest process exits, with a real request to
    whatever listens on that port - possibly the developer's own Web UI.
    """

    def test_one_leaves_an_entry_behind(self) -> None:
        server_feedback._INFLIGHT_TASKS["left-behind"] = BASE_URL

    def test_the_next_one_does_not_see_it(self) -> None:
        assert server_feedback._INFLIGHT_TASKS == {}
