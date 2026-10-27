"""R883: a user who is still typing does not lose the task to the backend.

What went wrong
---------------
While the user types, the page keeps the countdown alive: when 15 s are left it asks the
server for 60 s more (``POST /api/tasks/<id>/extend``) and, at zero, it *holds* instead of
auto-submitting (R689 / R699).  That typing extension drew on the same 3-extension quota as
the (retired) manual "+60 s" button.  Once the quota was gone the page still held at zero
for as long as the user kept typing, but the backend does not know about the page: its wait
(``wait_for_task_completion``) looks at ``remaining_time`` after the first timeout, finds
``0`` and closes the task 40 s (``BACKEND_BUFFER``) after the last deadline.  With the
defaults that is about 460 s in: somebody typing a long answer found the task gone, and the
text they sent afterwards got a ``404``.  The draft is stored under the task id, so the
agent's next request (a new task) does not get it back either.

What is pinned now
------------------
* ``Task.extend_deadline(..., typing_max_extends=N)`` is a *typing* extension: it counts in
  ``typing_extends_used`` against ``N`` and leaves ``extends_used`` / the manual quota alone.
  ``None`` (the default) is the old manual extension.  The other refusals (completed, frozen,
  seconds out of range) are the same for both.
* ``POST /api/tasks/<id>/extend`` takes ``reason``: ``manual`` (the default) or ``typing``;
  anything else is ``400 invalid_reason``.  A typing extension is refused with
  ``422 extends_limit_reached`` after ``COUNTDOWN_TYPING_EXTENDS_MAX`` of them, and the two
  counters do not use each other up.
* The cap must be reached **before** the backend gives up, otherwise the page would still be
  holding for a task the backend has closed: the longest the page can keep a task alive by
  typing (``COUNTDOWN_TYPING_EXTENDS_MAX`` steps of 60 s) is shorter than the least that the
  backend's probes cover (``_DEADLINE_EXTENSION_PROBE_MAX`` x
  ``TYPING_HOLD_TRIGGER_S - 1 + BACKEND_BUFFER`` s).
* Both front-ends (Web page and VS Code panel) send ``{"seconds": 60, "reason": "typing"}``,
  do not look at the manual quota, also try while holding at zero, wait at least
  ``TYPING_EXTEND_MIN_GAP_MS`` between two attempts (a failing request must not be retried on
  every one-second tick, and the route allows 10 per minute), and, once the server answers
  ``extends_limit_reached``, stop asking **and stop holding**: the typed text is submitted
  instead of waiting for the backend to close the task.  A failure that is not a refusal
  (offline, 5xx) keeps the page holding.  The same fallback is what a VS Code panel gets from
  a server older than R883, which charges typing to the manual quota and ignores ``reason``.
"""

from __future__ import annotations

import json
import re
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from ai_intervention_agent.runtime_constants import BACKEND_BUFFER
from ai_intervention_agent.server_feedback import _DEADLINE_EXTENSION_PROBE_MAX
from ai_intervention_agent.task_queue import Task, TaskStatus
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui import WebFeedbackUI
from ai_intervention_agent.web_ui_routes.task import (
    COUNTDOWN_EXTEND_REASONS,
    COUNTDOWN_EXTEND_SECONDS_MAX,
    COUNTDOWN_EXTEND_SECONDS_MIN,
    COUNTDOWN_EXTENDS_MAX,
    COUNTDOWN_TYPING_EXTENDS_MAX,
)
from tests.test_multi_task_poll_controller_lifecycle_r452 import (
    MULTI_TASK_JS,
    _node_available,
    _poll_harness,
    _run_node,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
TASK = "r883-task"

KW: dict[str, int] = {
    "max_extends": COUNTDOWN_EXTENDS_MAX,
    "min_seconds": COUNTDOWN_EXTEND_SECONDS_MIN,
    "max_seconds": COUNTDOWN_EXTEND_SECONDS_MAX,
}
TYPING = COUNTDOWN_TYPING_EXTENDS_MAX


def _new_task(timeout: int = 300, **fields: Any) -> Task:
    return Task(task_id="t", prompt="p", auto_resubmit_timeout=timeout, **fields)


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------


class TestTaskModel:
    def test_a_typing_extension_does_not_draw_on_the_manual_quota(self) -> None:
        task = _new_task()
        for _ in range(COUNTDOWN_EXTENDS_MAX):
            assert task.extend_deadline(60, **KW) == (True, None)
        assert task.extend_deadline(60, **KW) == (False, "extends_limit_reached")
        before = task.auto_resubmit_timeout

        assert task.extend_deadline(60, typing_max_extends=TYPING, **KW) == (True, None)

        assert task.auto_resubmit_timeout == before + 60
        assert task.extends_used == COUNTDOWN_EXTENDS_MAX
        assert task.typing_extends_used == 1

    def test_the_two_counters_do_not_use_each_other_up(self) -> None:
        task = _new_task()
        for _ in range(TYPING):
            assert task.extend_deadline(60, typing_max_extends=TYPING, **KW)[0]
        assert task.typing_extends_used == TYPING
        assert task.extends_used == 0

        # the typing cap is reached: typing is refused, manual still has its 3
        assert task.extend_deadline(60, typing_max_extends=TYPING, **KW) == (
            False,
            "extends_limit_reached",
        )
        for _ in range(COUNTDOWN_EXTENDS_MAX):
            assert task.extend_deadline(60, **KW) == (True, None)
        assert task.extend_deadline(60, **KW) == (False, "extends_limit_reached")
        assert (task.extends_used, task.typing_extends_used) == (
            COUNTDOWN_EXTENDS_MAX,
            TYPING,
        )

    def test_a_refused_typing_extension_changes_nothing(self) -> None:
        task = _new_task(typing_extends_used=TYPING)
        before = task.model_dump()

        ok, code = task.extend_deadline(60, typing_max_extends=TYPING, **KW)

        assert (ok, code) == (False, "extends_limit_reached")
        assert task.model_dump() == before

    @pytest.mark.parametrize("typing_max_extends", [None, TYPING])
    @pytest.mark.parametrize(
        ("setup", "seconds", "code"),
        [
            ({"status": TaskStatus.COMPLETED}, 60, "task_completed"),
            ({"auto_resubmit_timeout": 0}, 60, "auto_resubmit_disabled"),
            ({}, COUNTDOWN_EXTEND_SECONDS_MIN - 1, "invalid_seconds"),
            ({}, COUNTDOWN_EXTEND_SECONDS_MAX + 1, "invalid_seconds"),
        ],
    )
    def test_the_other_refusals_are_the_same_for_both_kinds(
        self,
        typing_max_extends: int | None,
        setup: dict[str, Any],
        seconds: int,
        code: str,
    ) -> None:
        fields: dict[str, Any] = {
            "task_id": "t",
            "prompt": "p",
            "auto_resubmit_timeout": 120,
            **setup,
        }
        task = Task(**fields)

        ok, error = task.extend_deadline(
            seconds, typing_max_extends=typing_max_extends, **KW
        )

        assert (ok, error) == (False, code)
        assert task.auto_resubmit_timeout == fields["auto_resubmit_timeout"]

    def test_without_typing_max_extends_it_is_the_manual_extension(self) -> None:
        task = _new_task()
        assert task.extend_deadline(60, **KW) == (True, None)
        assert (task.extends_used, task.typing_extends_used) == (1, 0)

    def test_the_typing_counter_stays_in_memory_like_extends_used(self) -> None:
        source = (
            REPO_ROOT / "src" / "ai_intervention_agent" / "task_queue.py"
        ).read_text(encoding="utf-8")
        persist = source[source.index("def _persist(") : source.index("def _restore(")]
        assert "typing_extends_used" not in persist
        assert "extends_used" not in persist


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ui() -> WebFeedbackUI:
    instance = WebFeedbackUI(
        prompt="r883", task_id="r883-initial", auto_resubmit_timeout=0, port=19883
    )
    instance.app.config["TESTING"] = True
    instance.limiter.enabled = False
    object.__setattr__(instance, "shutdown_server", lambda: None)
    return instance


@pytest.fixture
def client(ui: WebFeedbackUI) -> Iterator[FlaskClient]:
    queue = get_task_queue()
    queue.clear_all_tasks()
    queue.add_task(task_id=TASK, prompt="p", auto_resubmit_timeout=300)
    try:
        yield ui.app.test_client()
    finally:
        queue.clear_all_tasks()


def _extend(client: FlaskClient, body: Any = ...) -> Any:
    if body is ...:
        return client.post(f"/api/tasks/{TASK}/extend", environ_base=LOOPBACK)
    return client.post(f"/api/tasks/{TASK}/extend", json=body, environ_base=LOOPBACK)


def _task() -> Task:
    task = get_task_queue().get_task(TASK)
    assert task is not None
    return task


class TestRoute:
    def test_a_typing_extension_is_still_answered_after_the_manual_quota_is_gone(
        self, client: FlaskClient
    ) -> None:
        for _ in range(COUNTDOWN_EXTENDS_MAX):
            assert _extend(client, {"seconds": 60}).status_code == 200
        refused = _extend(client, {"seconds": 60})
        assert refused.status_code == 422
        assert refused.get_json()["code"] == "extends_limit_reached"
        before = _task().auto_resubmit_timeout

        resp = _extend(client, {"seconds": 60, "reason": "typing"})

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["extends_used"] == COUNTDOWN_EXTENDS_MAX
        assert body["extends_max"] == COUNTDOWN_EXTENDS_MAX
        assert body["new_auto_resubmit_timeout"] == before + 60
        assert (_task().extends_used, _task().typing_extends_used) == (
            COUNTDOWN_EXTENDS_MAX,
            1,
        )

    def test_the_last_typing_extension_is_the_one_before_the_cap(
        self, client: FlaskClient
    ) -> None:
        for n in range(TYPING):
            resp = _extend(client, {"seconds": 60, "reason": "typing"})
            assert resp.status_code == 200, n
        timeout = _task().auto_resubmit_timeout
        assert timeout == 300 + 60 * TYPING

        resp = _extend(client, {"seconds": 60, "reason": "typing"})

        assert resp.status_code == 422
        assert resp.get_json()["code"] == "extends_limit_reached"
        assert _task().auto_resubmit_timeout == timeout
        # the manual quota was never touched by any of those
        assert _task().extends_used == 0
        for _ in range(COUNTDOWN_EXTENDS_MAX):
            assert _extend(client, {"seconds": 60}).status_code == 200

    @pytest.mark.parametrize(
        "reason",
        [
            "TYPING",
            "Typing",
            "",
            " typing",
            "auto",
            None,
            5,
            True,
            ["typing"],
            {"a": 1},
        ],
    )
    def test_any_other_reason_is_a_400(self, client: FlaskClient, reason: Any) -> None:
        before = _task().auto_resubmit_timeout

        resp = _extend(client, {"seconds": 60, "reason": reason})

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert body["code"] == "invalid_reason"
        assert _task().auto_resubmit_timeout == before
        assert (_task().extends_used, _task().typing_extends_used) == (0, 0)

    @pytest.mark.parametrize("body", [..., {}, {"seconds": 60}, {"reason": "manual"}])
    def test_without_a_reason_or_with_manual_it_is_the_manual_extension(
        self, client: FlaskClient, body: Any
    ) -> None:
        assert _extend(client, body).status_code == 200
        assert (_task().extends_used, _task().typing_extends_used) == (1, 0)

    def test_the_documented_reasons_are_the_ones_the_route_accepts(self) -> None:
        assert COUNTDOWN_EXTEND_REASONS == ("manual", "typing")


# ---------------------------------------------------------------------------
# Numbers that have to stay in step across files
# ---------------------------------------------------------------------------


def _int_from(source: str, pattern: str) -> int:
    """The number a constant is set to; ``6 * 1000`` style products are multiplied out."""
    match = re.search(pattern, source)
    assert match is not None, pattern
    product = 1
    for factor in match.group(1).split("*"):
        product *= int(factor)
    return product


def _web() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _vscode() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


class TestNumbersAgree:
    def test_both_front_ends_send_the_same_typing_extension(self) -> None:
        assert 'JSON.stringify({ seconds: 60, reason: "typing" })' in _web()
        assert "JSON.stringify({ seconds: 60, reason: 'typing' })" in _vscode()

    def test_the_trigger_window_is_the_same_in_both(self) -> None:
        pattern = r"TYPING_HOLD_TRIGGER_S = (\d+)"
        assert _int_from(_web(), pattern) == _int_from(_vscode(), pattern)

    def test_the_minimum_gap_is_the_same_and_fits_the_route_limit(self) -> None:
        pattern = r"TYPING_EXTEND_MIN_GAP_MS = ([0-9 *]+)"
        gap = _int_from(_web(), pattern)
        assert gap == _int_from(_vscode(), pattern)
        # the route says "10 per minute"
        assert 60_000 // gap <= 10

    def test_the_typing_cap_is_reached_before_the_backend_gives_up(self) -> None:
        step = _int_from(_web(), r'seconds: (\d+), reason: "typing"')
        trigger = _int_from(_web(), r"TYPING_HOLD_TRIGGER_S = (\d+)")
        # A probe that lands just after the page asked (the tick ran at `trigger`, the answer is
        # on its way) still sees `trigger - 1` s left; the backend then waits that + BUFFER.
        shortest_probe_wait = trigger - 1 + BACKEND_BUFFER
        typing_horizon = COUNTDOWN_TYPING_EXTENDS_MAX * step
        probe_horizon = _DEADLINE_EXTENSION_PROBE_MAX * shortest_probe_wait
        assert typing_horizon < probe_horizon, (
            f"the page may hold for {typing_horizon} s but 50 probes only cover "
            f"{probe_horizon} s: the backend would close a task the page is still holding"
        )


# ---------------------------------------------------------------------------
# Web page (node vm, the real multi_task.js)
# ---------------------------------------------------------------------------

WEB_PRELUDE = """
const fetchCalls = [];
let reply = { ok: true, body: {
  success: true, new_remaining_time: 75, new_auto_resubmit_timeout: 300,
  extends_used: 3, extends_max: 3 } };
fetch = (url, options) => {
  fetchCalls.push({ url: String(url), body: JSON.parse(options.body) });
  const r = reply;
  return Promise.resolve({ ok: r.ok, json: () => Promise.resolve(r.body) });
};
async function flush() { for (let i = 0; i < 25; i += 1) await Promise.resolve(); }
let fake = Date.now();
Date.now = () => fake;
const autoSubmitted = [];
autoSubmitTask = async (id) => { autoSubmitted.push(id); };
updateCountdownDisplay = () => {};
function typeNow() { window.lastFeedbackTypingAtMs = fake; }
function setUp(extendsUsed) {
  activeTaskId = 't1';
  window.currentTasks = [{
    task_id: 't1', auto_resubmit_timeout: 240,
    extends_used: extendsUsed, extends_max: 3 }];
  window.__aiiaTypingAutoExtendNextAtMs = 0;
  window.__aiiaTypingAutoExtendBlocked = {};
  window.__aiiaTypingAutoExtendInFlight = false;
  typeNow();
}
function startTick(remainingSeconds) {
  window.taskDeadlines['t1'] = fake / 1000 + remainingSeconds;
  window.serverTimeOffset = 0;
  taskCountdowns['t1'] = {
    remaining: remainingSeconds, timeout: 240, timer: TASK_COUNTDOWN_SHARED_TIMER_SENTINEL };
}
"""


def _web_case(case_js: str) -> dict[str, Any]:
    result = _run_node(_poll_harness(WEB_PRELUDE + textwrap.dedent(case_js)))
    parsed: dict[str, Any] = json.loads(result)
    return parsed


@pytest.mark.skipif(not _node_available(), reason="node runtime unavailable")
class TestWebPage:
    def test_it_sends_the_typing_reason_and_ignores_the_manual_quota(self) -> None:
        out = _web_case(
            """
            setUp(3);  // extends_used 3 of 3: the manual quota is gone
            maybeAutoExtendCountdownForTyping('t1', 10);
            await flush();
            process.stdout.write(JSON.stringify({ calls: fetchCalls }));
            """
        )
        assert [c["url"] for c in out["calls"]] == ["/api/tasks/t1/extend"]
        assert out["calls"][0]["body"] == {"seconds": 60, "reason": "typing"}

    def test_it_also_asks_while_holding_at_zero_but_not_above_the_window(self) -> None:
        out = _web_case(
            """
            setUp(0);
            const seen = [];
            for (const remaining of [0, 16, NaN, 15, 1000]) {
              window.__aiiaTypingAutoExtendNextAtMs = 0;
              const before = fetchCalls.length;
              maybeAutoExtendCountdownForTyping('t1', remaining);
              await flush();
              seen.push([String(remaining), fetchCalls.length - before]);
            }
            process.stdout.write(JSON.stringify({ seen }));
            """
        )
        assert out["seen"] == [
            ["0", 1],
            ["16", 0],
            ["NaN", 0],
            ["15", 1],
            ["1000", 0],
        ]

    def test_it_does_not_ask_when_the_user_is_not_typing_or_the_task_is_not_on_screen(
        self,
    ) -> None:
        out = _web_case(
            """
            setUp(0);
            window.lastFeedbackTypingAtMs = fake - TYPING_HOLD_IDLE_MS - 1;  // idle
            maybeAutoExtendCountdownForTyping('t1', 5);
            await flush();
            const idle = fetchCalls.length;
            typeNow();
            activeTaskId = 'other';                                             // not on screen
            maybeAutoExtendCountdownForTyping('t1', 5);
            await flush();
            process.stdout.write(JSON.stringify({ idle, offScreen: fetchCalls.length }));
            """
        )
        assert out == {"idle": 0, "offScreen": 0}

    def test_two_attempts_are_at_least_the_minimum_gap_apart(self) -> None:
        out = _web_case(
            """
            setUp(0);
            maybeAutoExtendCountdownForTyping('t1', 10);
            await flush();
            const first = fetchCalls.length;
            fake += TYPING_EXTEND_MIN_GAP_MS - 1000; typeNow();
            maybeAutoExtendCountdownForTyping('t1', 10);
            await flush();
            const tooSoon = fetchCalls.length;
            fake += 1100; typeNow();
            maybeAutoExtendCountdownForTyping('t1', 10);
            await flush();
            process.stdout.write(JSON.stringify({ first, tooSoon, later: fetchCalls.length }));
            """
        )
        assert out == {"first": 1, "tooSoon": 1, "later": 2}

    def test_a_failing_request_is_not_retried_on_every_tick(self) -> None:
        out = _web_case(
            """
            setUp(0);
            reply = { ok: false, body: { success: false, code: 'boom' } };
            for (let i = 0; i < 5; i += 1) {
              maybeAutoExtendCountdownForTyping('t1', 10);
              await flush();
              fake += 1000; typeNow();
            }
            process.stdout.write(JSON.stringify({ calls: fetchCalls.length }));
            """
        )
        assert out == {"calls": 1}

    def test_the_server_refusing_for_good_stops_the_asking_and_the_holding(
        self,
    ) -> None:
        out = _web_case(
            """
            setUp(0);
            reply = { ok: false, body: {
              success: false, code: 'extends_limit_reached', extends_used: 0, extends_max: 3 } };
            startTick(0);                       // at zero, still typing
            tickTaskCountdown('t1');            // asks; the answer has not arrived: holds
            const heldWhileAsking =
              taskCountdowns['t1'].timer === TASK_COUNTDOWN_SHARED_TIMER_SENTINEL
              && autoSubmitted.length === 0;
            await flush();
            const blocked = window.__aiiaTypingAutoExtendBlocked['t1'] === true;
            fake += 1000; typeNow();
            tickTaskCountdown('t1');            // refused: submits what was typed
            process.stdout.write(JSON.stringify({
              heldWhileAsking, blocked, autoSubmitted,
              calls: fetchCalls.length,
              timer: taskCountdowns['t1'] ? taskCountdowns['t1'].timer : 'removed',
            }));
            """
        )
        assert out["heldWhileAsking"] is True
        assert out["blocked"] is True
        assert out["autoSubmitted"] == ["t1"]
        assert out["calls"] == 1
        assert out["timer"] in (None, "removed")

    def test_a_failure_that_is_not_a_refusal_keeps_holding(self) -> None:
        out = _web_case(
            """
            setUp(0);
            reply = { ok: false, body: { success: false, code: 'boom' } };
            startTick(0);
            const held = [];
            for (let i = 0; i < 4; i += 1) {
              tickTaskCountdown('t1');
              await flush();
              held.push(taskCountdowns['t1'].timer === TASK_COUNTDOWN_SHARED_TIMER_SENTINEL);
              fake += 1000; typeNow();
            }
            process.stdout.write(JSON.stringify({
              held, autoSubmitted, blocked: window.__aiiaTypingAutoExtendBlocked['t1'] === true }));
            """
        )
        assert out == {"held": [True] * 4, "autoSubmitted": [], "blocked": False}

    def test_it_still_submits_when_the_user_has_stopped_typing(self) -> None:
        out = _web_case(
            """
            setUp(0);
            startTick(0);
            window.lastFeedbackTypingAtMs = fake - TYPING_HOLD_IDLE_MS - 1;
            tickTaskCountdown('t1');
            process.stdout.write(JSON.stringify({ autoSubmitted, calls: fetchCalls.length }));
            """
        )
        assert out == {"autoSubmitted": ["t1"], "calls": 0}


# ---------------------------------------------------------------------------
# VS Code panel (node vm, the real functions cut out of webview-ui.js)
# ---------------------------------------------------------------------------


def _js_function_source(source: str, name: str) -> str:
    """``function name(...) {...}`` as written in ``source`` (braces in strings/comments skipped)."""
    head = re.search(rf"function {re.escape(name)}\(", source)
    assert head is not None, name
    i = source.index("{", source.index(")", head.end()))
    depth = 0
    quote = ""
    while i < len(source):
        ch = source[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif source.startswith("//", i):
            i = source.index("\n", i)
            continue
        elif source.startswith("/*", i):
            i = source.index("*/", i) + 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[head.start() : i + 1]
        i += 1
    raise AssertionError(f"unterminated function {name}")


def _declaration(source: str, name: str) -> str:
    match = re.search(rf"^[ \t]*(?:let|const) {re.escape(name)} = .*$", source, re.M)
    assert match is not None, name
    return match.group(0).strip()


def _vscode_script(case_js: str) -> str:
    source = _vscode()
    declarations = "\n".join(
        _declaration(source, name)
        for name in (
            "lastFeedbackTypingAtMs",
            "typingAutoExtendInFlight",
            "typingAutoExtendNextAtMs",
            "typingAutoExtendBlockedTasks",
            "TYPING_HOLD_IDLE_MS",
            "TYPING_HOLD_TRIGGER_S",
            "TYPING_EXTEND_MIN_GAP_MS",
        )
    )
    functions = "\n".join(
        _js_function_source(source, name)
        for name in (
            "isUserActivelyTyping",
            "maybeAutoExtendCountdownForTyping",
            "stopCountdown",
            "startCountdown",
        )
    )
    body = (
        declarations
        + textwrap.dedent(
            """
            let countdownTimer = null;
            let remainingSeconds = 0;
            let lastCountdownTaskId = null;
            const taskDeadlines = {};
            const SERVER_URL = 'http://127.0.0.1:8080';
            function log() {}
            let fake = 1700000000000;
            Date.now = () => fake;
            function getAdjustedNowSeconds() { return fake / 1000; }
            const autoSubmitted = [];
            function autoSubmit() { autoSubmitted.push(lastCountdownTaskId); }
            let tickFn = null;
            function setInterval(fn) { tickFn = fn; return 7; }
            function clearInterval() {}
            const fetchCalls = [];
            let reply = { ok: true, body: { success: true, new_remaining_time: 75 } };
            function fetch(url, options) {
              fetchCalls.push({ url: String(url), body: JSON.parse(options.body) });
              const r = reply;
              return Promise.resolve({ ok: r.ok, json: () => Promise.resolve(r.body) });
            }
            async function flush() { for (let i = 0; i < 25; i += 1) await Promise.resolve(); }
            function typeNow() { lastFeedbackTypingAtMs = fake; }
            """
        )
        + "\n"
        + functions
        + "\n(async () => {\n"
        + textwrap.indent(textwrap.dedent(case_js), "  ")
        + "\n})();\n"
    )
    return (
        "const vm = require('vm');\n"
        "const context = vm.createContext({ Promise, JSON, Math, Date, process, console });\n"
        f"vm.runInContext({json.dumps(body)}, context);\n"
    )


def _vscode_case(case_js: str) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(_run_node(_vscode_script(case_js)))
    return parsed


@pytest.mark.skipif(not _node_available(), reason="node runtime unavailable")
class TestVscodePanel:
    def test_it_sends_the_typing_reason_with_no_manual_quota_in_sight(self) -> None:
        out = _vscode_case(
            """
            typeNow();
            maybeAutoExtendCountdownForTyping('t1', 10);
            await flush();
            process.stdout.write(JSON.stringify({ calls: fetchCalls }));
            """
        )
        assert [c["url"] for c in out["calls"]] == [
            "http://127.0.0.1:8080/api/tasks/t1/extend"
        ]
        assert out["calls"][0]["body"] == {"seconds": 60, "reason": "typing"}

    def test_it_also_asks_while_holding_at_zero_but_not_above_the_window(self) -> None:
        out = _vscode_case(
            """
            typeNow();
            const seen = [];
            for (const remaining of [0, 16, NaN, 15, 1000]) {
              typingAutoExtendNextAtMs = 0;
              const before = fetchCalls.length;
              maybeAutoExtendCountdownForTyping('t1', remaining);
              await flush();
              seen.push([String(remaining), fetchCalls.length - before]);
            }
            process.stdout.write(JSON.stringify({ seen }));
            """
        )
        assert out["seen"] == [
            ["0", 1],
            ["16", 0],
            ["NaN", 0],
            ["15", 1],
            ["1000", 0],
        ]

    def test_two_attempts_are_at_least_the_minimum_gap_apart(self) -> None:
        out = _vscode_case(
            """
            typeNow();
            maybeAutoExtendCountdownForTyping('t1', 10);
            await flush();
            const first = fetchCalls.length;
            fake += TYPING_EXTEND_MIN_GAP_MS - 1000; typeNow();
            maybeAutoExtendCountdownForTyping('t1', 10);
            await flush();
            const tooSoon = fetchCalls.length;
            fake += 1100; typeNow();
            maybeAutoExtendCountdownForTyping('t1', 10);
            await flush();
            process.stdout.write(JSON.stringify({ first, tooSoon, later: fetchCalls.length }));
            """
        )
        assert out == {"first": 1, "tooSoon": 1, "later": 2}

    def test_the_server_refusing_for_good_stops_the_asking_and_the_holding(
        self,
    ) -> None:
        out = _vscode_case(
            """
            reply = { ok: false, body: { success: false, code: 'extends_limit_reached' } };
            typeNow();
            startCountdown(240, 't1', 0, fake / 1000);   // at zero, still typing
            tickFn();                                   // asks; no answer yet: holds
            const heldWhileAsking = autoSubmitted.length === 0;
            await flush();
            const blocked = typingAutoExtendBlockedTasks['t1'] === true;
            fake += 1000; typeNow();
            tickFn();                                   // refused: submits what was typed
            process.stdout.write(JSON.stringify({
              heldWhileAsking, blocked, autoSubmitted, calls: fetchCalls.length }));
            """
        )
        assert out == {
            "heldWhileAsking": True,
            "blocked": True,
            "autoSubmitted": ["t1"],
            "calls": 1,
        }

    def test_a_failure_that_is_not_a_refusal_keeps_holding(self) -> None:
        out = _vscode_case(
            """
            reply = { ok: false, body: { success: false, code: 'boom' } };
            typeNow();
            startCountdown(240, 't1', 0, fake / 1000);
            for (let i = 0; i < 4; i += 1) {
              tickFn();
              await flush();
              fake += 1000; typeNow();
            }
            process.stdout.write(JSON.stringify({
              autoSubmitted, blocked: typingAutoExtendBlockedTasks['t1'] === true,
              calls: fetchCalls.length }));
            """
        )
        assert out == {"autoSubmitted": [], "blocked": False, "calls": 1}

    def test_it_still_submits_when_the_user_has_stopped_typing(self) -> None:
        out = _vscode_case(
            """
            typeNow();
            startCountdown(240, 't1', 0, fake / 1000);
            lastFeedbackTypingAtMs = fake - TYPING_HOLD_IDLE_MS - 1;
            tickFn();
            process.stdout.write(JSON.stringify({ autoSubmitted, calls: fetchCalls.length }));
            """
        )
        assert out == {"autoSubmitted": ["t1"], "calls": 0}

    def test_the_helpers_were_found_as_real_source(self) -> None:
        source = _vscode()
        for name in ("maybeAutoExtendCountdownForTyping", "startCountdown"):
            body = _js_function_source(source, name)
            assert body.startswith(f"function {name}(")
            assert body.rstrip().endswith("}")
        assert "reason: 'typing'" in _js_function_source(
            source, "maybeAutoExtendCountdownForTyping"
        )
