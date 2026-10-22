"""R820: ``interactive_feedback`` tells the client it is still alive while a human thinks.

Cursor gives every MCP tool call an *idle* timeout, 120 s by default, and resets it each time
the server sends a ``notifications/progress`` for the call's progress token, up to a total of one
hour (its client sets ``resetTimeoutOnProgress`` and sends ``_meta.progressToken`` with every
``tools/call``). The server never sent one, so a question that was not answered, or auto-submitted
by an open panel, within two minutes ended in ``MCP error -32001: Request timed out``; the
countdown (default 240 s), the 260 s backend wait and the reply a person was still typing were all
cut off, and the answer went to a request nobody waited for any more. Measured in a real Cursor
session: three questions in a row failed after 120 s while the countdown had run out long before
(no panel was open to submit the text).

The wait now carries a keepalive: one progress notification every ``_PROGRESS_KEEPALIVE_INTERVAL_S``
seconds, from the moment the task is on screen until the wait ends. A client that did not send a
progress token ignores the call (``Context.report_progress`` is then a no-op), a client that does
not reset on progress is unaffected, and a failure to send one never touches the wait.

Cases:

A. A real FastMCP server and a real client: progress arrives while the tool waits, increases,
   carries no total (the wait can be extended, so the end is unknown); no token, no notification,
   no error; both protocol modes.
B. The keepalive itself: no ``ctx`` means no task; a failing ``report_progress`` is retried and
   never raises; leaving the block, by return, error or cancellation, stops it at once and leaves
   no task behind.
C. The tool puts the wait inside the keepalive (and not before or after it).
D. The interval stays far below the shortest idle timeout a client is likely to use.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar
from unittest.mock import MagicMock

import anyio
import pytest
from fastmcp import Client

from ai_intervention_agent import server as server_module
from ai_intervention_agent import server_feedback
from ai_intervention_agent.server_config import WebUIConfig

# Read before any fixture can shorten it.
SHIPPED_INTERVAL = getattr(server_feedback, "_PROGRESS_KEEPALIVE_INTERVAL_S", None)

INTERVAL = 0.05
TASK_ID = "task-r820"

T = TypeVar("T")


def _run(scenario: Coroutine[Any, Any, T], deadline: float = 15.0) -> T:
    """``asyncio.run`` that fails after ``deadline`` seconds instead of hanging the suite.

    A beat that is not stopped, or a stuck send that is not given up, would otherwise turn a
    regression into a CI job that never ends. The scenario runs on a daemon thread, so one that
    is stuck cannot keep the interpreter alive either.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(scenario)
        except BaseException as exc:  # handed to the caller below
            box["error"] = exc

    thread = threading.Thread(target=target, name="r820-scenario", daemon=True)
    thread.start()
    thread.join(deadline)
    if thread.is_alive():
        pytest.fail(f"the scenario was still running after {deadline:g} s (it hangs)")
    if "error" in box:
        raise box["error"]
    return box["value"]


class RecordingContext:
    """The two ``Context`` methods the tool uses, recording what the client would have got."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.progress: list[tuple[float, float | None, str | None]] = []
        self.stamps: list[float] = []
        self.attempts = 0

    async def info(self, message: str, **_: Any) -> None:
        return None

    async def report_progress(
        self, progress: float, total: float | None = None, message: str | None = None
    ) -> None:
        self.attempts += 1
        if self.fail_with is not None:
            raise self.fail_with
        self.stamps.append(time.monotonic())
        self.progress.append((progress, total, message))


@pytest.fixture(autouse=True)
def fast_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server_feedback, "_PROGRESS_KEEPALIVE_INTERVAL_S", INTERVAL, raising=False
    )


def _keepalive(ctx: Any) -> Any:
    return server_feedback._client_keepalive(ctx)  # type: ignore[attr-defined]


def _other_tasks() -> set[asyncio.Task[Any]]:
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}


async def _until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the condition"
        await asyncio.sleep(INTERVAL / 2)


async def _quiet_for(ctx: RecordingContext, intervals: float = 4) -> None:
    before = len(ctx.progress)
    await asyncio.sleep(INTERVAL * intervals)
    assert len(ctx.progress) == before, (
        "a progress notification went out after the stop"
    )


# --------------------------------------------------------------------------- A: real server


class Web:
    """Fakes for the Web UI side so ``interactive_feedback`` reaches its wait."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, wait_s: float) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        self.wait_started = 0.0
        self.wait_ended = 0.0

        class Pool:
            async def post(self, *_: Any, **__: Any) -> Any:
                return response

        async def noop(*_: Any, **__: Any) -> None:
            return None

        async def human(*_: Any, **__: Any) -> dict[str, str]:
            self.wait_started = time.monotonic()
            await asyncio.sleep(wait_s)
            self.wait_ended = time.monotonic()
            return {"interactive_feedback": "done"}

        sm = server_feedback.service_manager
        monkeypatch.setattr(
            sm,
            "get_web_ui_config",
            lambda: (WebUIConfig(host="127.0.0.1", port=12345), 30),
        )
        monkeypatch.setattr(sm, "get_async_client", lambda _config: Pool())
        monkeypatch.setattr(sm, "ensure_web_ui_running", noop)
        monkeypatch.setattr(server_feedback, "wait_for_task_completion", human)
        monkeypatch.setattr(server_feedback, "NOTIFICATION_AVAILABLE", False)
        monkeypatch.setattr(
            server_feedback.server_config, "_generate_task_id", lambda: TASK_ID
        )


def _through_a_real_client(
    monkeypatch: pytest.MonkeyPatch,
    wait_s: float,
    *,
    mode: str = "legacy",
    with_progress_handler: bool = True,
) -> tuple[list[tuple[float, float | None, str | None]], Any]:
    Web(monkeypatch, wait_s)
    seen: list[tuple[float, float | None, str | None]] = []

    async def on_progress(
        progress: float, total: float | None, message: str | None
    ) -> None:
        seen.append((progress, total, message))

    async def call() -> Any:
        async with Client(server_module.mcp, mode=mode) as client:  # type: ignore[arg-type]
            return await client.call_tool(
                "interactive_feedback",
                {"message": "r820"},
                progress_handler=on_progress if with_progress_handler else None,
            )

    return seen, _run(call())


class TestARealServerAndClient:
    def test_progress_arrives_while_the_tool_waits_for_the_human(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen, result = _through_a_real_client(monkeypatch, wait_s=0.5)

        assert len(seen) >= 3, f"only {len(seen)} progress notifications in 0.5 s"
        assert "done" in str(result.content)

    def test_progress_increases_and_has_no_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen, _ = _through_a_real_client(monkeypatch, wait_s=0.5)

        assert seen, "no progress at all"
        values = [progress for progress, _, _ in seen]
        assert values == sorted(set(values)), f"not strictly increasing: {values}"
        assert all(total is None for _, total, _ in seen)
        assert all(isinstance(message, str) and message for _, _, message in seen)

    def test_the_first_notification_comes_after_one_interval_not_before(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen, _ = _through_a_real_client(monkeypatch, wait_s=0.5)

        assert seen, "no progress at all"
        assert seen[0][0] >= INTERVAL * 0.8

    def test_a_call_that_ends_before_the_first_interval_sends_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            server_feedback, "_PROGRESS_KEEPALIVE_INTERVAL_S", 5.0, raising=False
        )

        seen, result = _through_a_real_client(monkeypatch, wait_s=0.05)

        assert seen == []
        assert "done" in str(result.content)

    def test_a_client_without_a_progress_token_gets_no_notification_and_no_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen, result = _through_a_real_client(
            monkeypatch, wait_s=0.3, with_progress_handler=False
        )

        assert seen == []
        assert "done" in str(result.content)

    def test_the_sessionless_protocol_still_completes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The newer protocol has no session to push to: the call must still succeed."""
        _, result = _through_a_real_client(monkeypatch, wait_s=0.3, mode="auto")

        assert "done" in str(result.content)


# --------------------------------------------------------------------------- B: the keepalive


class TestTheKeepaliveBlock:
    def test_without_a_context_nothing_is_scheduled(self) -> None:
        async def scenario() -> set[asyncio.Task[Any]]:
            async with _keepalive(None):
                await asyncio.sleep(INTERVAL * 3)
                return _other_tasks()

        assert _run(scenario()) == set()

    def test_it_reports_every_interval_and_stops_on_a_normal_exit(self) -> None:
        async def scenario() -> RecordingContext:
            ctx = RecordingContext()
            async with _keepalive(ctx):
                await asyncio.sleep(INTERVAL * 5.5)
            assert _other_tasks() == set()
            await _quiet_for(ctx)
            return ctx

        ctx = _run(scenario())

        assert 3 <= len(ctx.progress) <= 6
        values = [progress for progress, _, _ in ctx.progress]
        assert values == sorted(set(values))

    def test_a_failing_report_is_retried_and_never_reaches_the_wait(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def scenario() -> RecordingContext:
            ctx = RecordingContext(fail_with=RuntimeError("the client went away"))
            async with _keepalive(ctx):
                await asyncio.sleep(INTERVAL * 5.5)
                assert len(_other_tasks()) == 1, "the failure ended the keepalive"
            return ctx

        with caplog.at_level("DEBUG"):
            ctx = _run(scenario())

        assert ctx.attempts >= 3
        assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]

    def test_a_send_that_never_returns_does_not_hold_up_the_end_of_the_wait(
        self,
    ) -> None:
        """A client that stopped reading its end blocks the send; the result must not wait for it."""

        class Stuck(RecordingContext):
            async def report_progress(
                self,
                progress: float,
                total: float | None = None,
                message: str | None = None,
            ) -> None:
                self.attempts += 1
                await asyncio.Event().wait()

        async def scenario() -> None:
            ctx = Stuck()
            async with _keepalive(ctx):
                await _until(lambda: ctx.attempts >= 1)
            assert _other_tasks() == set()

        _run(scenario(), deadline=10.0)

    def test_an_error_inside_the_block_propagates_and_stops_the_keepalive(
        self,
    ) -> None:
        async def scenario() -> None:
            ctx = RecordingContext()
            with pytest.raises(ValueError, match="boom"):
                async with _keepalive(ctx):
                    await asyncio.sleep(INTERVAL * 2.5)
                    raise ValueError("boom")
            assert _other_tasks() == set()
            await _quiet_for(ctx)

        _run(scenario())

    def test_cancellation_by_the_mcp_runner_stops_it_and_still_reaches_the_caller(
        self,
    ) -> None:
        """The MCP runner cancels a call with an anyio scope, which cancels every ``await``."""

        async def scenario() -> list[str]:
            ctx = RecordingContext()
            outcome: list[str] = []

            async def handler() -> None:
                try:
                    async with _keepalive(ctx):
                        await asyncio.sleep(30)
                except asyncio.CancelledError:
                    outcome.append("cancelled")
                    raise

            async with anyio.create_task_group() as group:
                group.start_soon(handler)
                await _until(lambda: len(ctx.progress) >= 2)
                group.cancel_scope.cancel()
            await asyncio.sleep(INTERVAL)
            assert _other_tasks() == set()
            await _quiet_for(ctx)
            return outcome

        assert _run(scenario()) == ["cancelled"]

    def test_plain_task_cancel_stops_it(self) -> None:
        async def scenario() -> None:
            ctx = RecordingContext()

            async def handler() -> None:
                async with _keepalive(ctx):
                    await asyncio.sleep(30)

            task = asyncio.ensure_future(handler())
            await _until(lambda: len(ctx.progress) >= 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert _other_tasks() == set()
            await _quiet_for(ctx)

        _run(scenario())

    def test_every_block_has_its_own_clock(self) -> None:
        async def scenario() -> list[float]:
            ctx = RecordingContext()
            async with _keepalive(ctx):
                await asyncio.sleep(INTERVAL * 2.5)
            first = len(ctx.progress)
            async with _keepalive(ctx):
                await asyncio.sleep(INTERVAL * 1.5)
            return [progress for progress, _, _ in ctx.progress[first:]]

        second_block = _run(scenario())

        assert second_block
        assert second_block[0] < INTERVAL * 2


# --------------------------------------------------------------------------- C: wiring


def _call_the_tool(ctx: Any) -> Any:
    return _run(
        server_feedback.interactive_feedback(
            message="r820",
            predefined_options=None,
            feedback_placeholder=None,
            header_label=None,
            loop_id=None,
            loop_objective=None,
            loop_phase=None,
            success_criteria=None,
            iteration_label=None,
            ctx=ctx,
        )
    )


class TestTheToolPutsTheWaitInsideTheKeepalive:
    def test_progress_goes_out_between_the_start_and_the_end_of_the_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        web = Web(monkeypatch, wait_s=0.4)
        ctx = RecordingContext()

        _call_the_tool(ctx)

        assert len(ctx.stamps) >= 3
        assert all(
            web.wait_started <= stamp <= web.wait_ended + 0.05 for stamp in ctx.stamps
        )

    def test_the_tool_still_works_without_a_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        Web(monkeypatch, wait_s=0.1)

        assert "done" in str(_call_the_tool(None))


# --------------------------------------------------------------------------- D: the interval


class TestTheShippedInterval:
    def test_it_exists_and_is_far_below_every_idle_timeout_a_client_is_likely_to_use(
        self,
    ) -> None:
        # Cursor's default idle timeout is 120 s; other clients use 60 s or 30 s.
        assert SHIPPED_INTERVAL is not None
        assert 0 < float(SHIPPED_INTERVAL) <= 20.0

    def test_it_is_not_so_short_that_it_floods_the_client(self) -> None:
        assert SHIPPED_INTERVAL is not None
        assert float(SHIPPED_INTERVAL) >= 5.0
