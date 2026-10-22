"""R821: a stream that is accepted and dropped again is not reconnected once a second for ever.

``EventSource.onopen`` of the Web UI page (``multi_task.js``) and of the VS Code panel's webview
(``webview-ui.js``) set the reconnect delay back to its 1 s base, so the back-off only ever
doubled for a server that could not be reached at all.  A server, a proxy or a captive portal that
answers ``/api/events`` with ``200`` and then ends the stream (a reverse proxy that buffers or
times out the response, a process that crashes right after accepting) made every cycle start at
the base again: one connection a second, for as long as the page was open.  R796 made it worse in
one respect: the stream now opens with a comment frame, so ``onopen`` fires at once instead of
after the first event or heartbeat, and nothing separates "accepted" from "working" any more.
Measured in real Chrome 153 against a proxy that ends the stream 300 ms after it opened it: 23
connections in 30 s, 1.3 s apart.  The VS Code *host* (``extension.ts``, R718) already has the
right rule: the delay goes back to the base only when the connection has lived for
``SSE_STABLE_CONNECTION_MS`` (10 s) by the time it ends.

The page and the panel now follow it.  ``onopen`` records when the stream opened and leaves the
delay alone; ``onerror`` settles the account first: a stream that lived 10 s or more restarts the
back-off at 1 s, anything shorter keeps doubling (1, 2, 4, 8, 16, 30, 30 ... s).  Every way of
dropping a source without an ``onerror`` (``_disconnectSSE``, ``_closeSseSource``, a second
``_connectDirectSSE``) ends the clock too, so a later attempt that never opened is not credited
with an old stream.  Nothing new is scheduled: the check is a comparison of two timestamps.

The tests run both scripts in Node against a fake ``EventSource``, a fake clock and recorded
timers: streams that drop at once keep backing off up to the 30 s cap, a stream that never opened
does too, a stream that lived 10 s (and not 9.999 s) starts again at the base, the leader of a tab
group tells its followers the delay it really uses, the status indicator reaches "disconnected"
for a server that keeps dropping, and the panel's block behaves like the page's.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
EXTENSION_TS = REPO_ROOT / "packages" / "vscode" / "extension.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

# What the two harnesses have in common: a clock the test moves, recorded timers, a fake
# EventSource, and `drive`, which plays a list of connections against whichever script it is given.
PRELUDE = r"""
const fs = require('fs');
const vm = require('vm');

const sources = [];
const timers = [];
const posted = [];
const statuses = [];
let clock = 1000000;

const RealDate = Date;
function FakeDate(...args) {
  return args.length ? new RealDate(...args) : new RealDate(clock);
}
FakeDate.now = () => clock;
FakeDate.parse = RealDate.parse;
FakeDate.UTC = RealDate.UTC;
FakeDate.prototype = RealDate.prototype;

function FakeEventSource(url) {
  this.url = url;
  this.closed = false;
  this.addEventListener = function () {};
  this.close = function () { this.closed = true; };
  sources.push(this);
}

const common = {
  console,
  Math,
  Number,
  String,
  JSON,
  Promise,
  URLSearchParams,
  Date: FakeDate,
  setTimeout(fn, delay) {
    timers.push({ fn, delay, cancelled: false });
    return timers.length;
  },
  clearTimeout(id) {
    if (timers[id - 1]) timers[id - 1].cancelled = true;
  },
  setInterval() { return 1; },
  clearInterval() {},
  fetch: async () => ({ ok: true, json: async () => ({ success: true, tasks: [], stats: {} }) }),
  EventSource: FakeEventSource,
};

function newest() { return sources[sources.length - 1]; }

// One connection per entry of `plan`: the milliseconds the stream lived after it opened, or null
// when it was never accepted.  Returns the delay that was chosen after each of them.
function drive(api, plan) {
  api.connect();
  const delays = [];
  for (const lived of plan) {
    const source = newest();
    if (lived === null) {
      clock += 5;
    } else {
      source.onopen();
      clock += lived;
    }
    source.onerror();
    const timer = api.reconnectTimer();
    delays.push(timer.delay);
    clock += timer.delay;
    timer.fn();
  }
  return delays;
}

function scenarios(make) {
  const out = {};
  const each = (name, plan) => { out[name] = drive(make(), plan); };
  each("quickDrops", [5, 5, 5, 5, 5, 5, 5, 5]);
  each("neverOpened", [null, null, null, null, null, null, null, null]);
  each("neverOpenedAfterQuickDrops", [5, 5, 5, 5, 5, null, null]);
  each("stableThenDrops", [5, 5, 5, 10000, 5, 5, 5]);
  each("justUnderTen", [5, 5, 9999, 5]);
  each("exactlyTen", [5, 5, 10000, 5]);
  each("anHourThenDrops", [5, 5, 3600000, 5, 5]);
  each("stableEveryTime", [10000, 20000, 10000, 60000]);
  each("zeroLivedAfterBackoff", [5, 5, 5, 5, 0, 0]);

  {
    // a source that the script itself drops does not leave its clock running
    const api = make();
    const before = drive(api, [5, 5]);
    newest().onopen();
    clock += 1000;
    api.disconnect();
    clock += 600000;
    api.connect();
    clock += 5;
    newest().onerror();
    out.afterDisconnect = [...before, api.reconnectTimer().delay];
  }
  {
    const api = make();
    const before = drive(api, [5, 5]);
    const source = newest();
    source.onopen();
    clock += 600000;
    api.replace();
    clock += 5;
    newest().onerror();
    out.afterReplacement = [...before, api.reconnectTimer().delay];
    out.replacedWasClosed = source.closed;
  }
  {
    // the late error of a replaced source does not touch the account of the one that replaced it
    const api = make();
    api.connect();
    const first = newest();
    first.onopen();
    api.replace();
    const second = newest();
    second.onopen();
    clock += 20000;
    first.onerror();
    clock += 5;
    second.onerror();
    out.lateErrorOfReplacedSource = api.reconnectTimer().delay;
  }
  return out;
}
"""

PAGE_HARNESS = r"""
const code = fs.readFileSync(__SOURCE__, 'utf8');

function makePage(withChannel) {
  sources.length = 0;
  timers.length = 0;
  posted.length = 0;
  statuses.length = 0;
  const sandbox = Object.assign({}, common);
  sandbox.window = sandbox;
  sandbox.navigator = {};
  sandbox.document = {
    hidden: false,
    addEventListener() {},
    getElementById() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    body: { contains() { return true; } },
    documentElement: { setAttribute() {} },
  };
  if (withChannel) {
    sandbox.BroadcastChannel = function BroadcastChannel() {
      this.postMessage = (message) => posted.push(message);
      this.close = function () {};
    };
  }
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const original = sandbox._setSseStatus;
  sandbox._setSseStatus = function (status) {
    statuses.push(status);
    return original.apply(this, arguments);
  };
  return {
    connect: () => sandbox._connectSSE(),
    replace: () => sandbox._connectDirectSSE(false),
    disconnect: () => sandbox._disconnectSSE(),
    reconnectTimer: () => {
      const id = sandbox._sseReconnectTimer;
      return id ? timers[id - 1] : null;
    },
    election: () => timers.find((timer) => timer.delay === 160),
  };
}

const results = scenarios(() => makePage(false));

{
  drive(makePage(false), Array(7).fill(5));
  results.statusesAfterSevenQuickDrops = statuses.filter((status) => status !== 'connected');
}

{
  // the tab that leads a group tells its followers the delay it really uses
  const api = makePage(true);
  api.connect();
  api.election().fn();
  const delays = [];
  for (let i = 0; i < 5; i++) {
    const source = newest();
    source.onopen();
    clock += 5;
    source.onerror();
    const timer = api.reconnectTimer();
    delays.push(timer.delay);
    clock += timer.delay;
    timer.fn();
  }
  results.leaderDelays = delays;
  results.leaderBroadcast = posted.filter((m) => m.kind === 'error').map((m) => m.reconnectInMs);
  results.leaderOpenedEachTime = posted.filter((m) => m.kind === 'open').length;
}
process.stdout.write(JSON.stringify(results));
"""

PANEL_HARNESS = r"""
const source = fs.readFileSync(__SOURCE__, 'utf8');
const start = source.indexOf('let _sseSource = null');
const end = source.indexOf('function installPollingVisibilityHandler', start);
if (start < 0 || end < 0) throw new Error('the SSE block of webview-ui.js was not found');
const block = source.slice(start, end);

function makePanel() {
  sources.length = 0;
  timers.length = 0;
  const sandbox = Object.assign({}, common);
  sandbox.document = { hidden: false };
  vm.createContext(sandbox);
  vm.runInContext(
    `
    const SERVER_URL = 'http://127.0.0.1:1';
    const POLL_BASE_MS = 2000;
    const POLL_MAX_MS = 30000;
    const POLL_SSE_FALLBACK_MS = 30000;
    let pollBackoffMs = POLL_BASE_MS;
    let pollingTimer = null;
    let pollingToken = 1;
    let pollingEnabled = true;
    function log() {}
    function scheduleNextPoll() {}
    function pollAllData() {}
    function syncServerLanguage() {}
    ${block}
    globalThis.__panel = {
      connect: _connectSSE,
      disconnect: _disconnectSSE,
      timerId: () => _sseReconnectTimer,
    };
    `,
    sandbox,
  );
  const panel = sandbox.__panel;
  return {
    connect: () => panel.connect(),
    replace: () => panel.connect(),
    disconnect: () => panel.disconnect(),
    reconnectTimer: () => {
      const id = panel.timerId();
      return id ? timers[id - 1] : null;
    },
  };
}

process.stdout.write(JSON.stringify(scenarios(() => makePanel())));
"""


@functools.cache
def _results(target: str) -> dict[str, object]:
    harness, source = (
        (PAGE_HARNESS, MULTI_TASK_JS)
        if target == "page"
        else (PANEL_HARNESS, WEBVIEW_UI_JS)
    )
    script = PRELUDE + harness.replace("__SOURCE__", json.dumps(str(source)))
    completed = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    return json.loads(completed.stdout)


BACKOFF = [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]


@pytest.fixture(params=["page", "panel"])
def target(request: pytest.FixtureRequest) -> dict[str, object]:
    return _results(request.param)


class TestTheBackoffOfAStreamThatIsAcceptedAndDropped:
    def test_streams_that_drop_at_once_keep_backing_off_up_to_the_cap(
        self, target: dict[str, object]
    ) -> None:
        assert target["quickDrops"] == BACKOFF

    def test_a_server_that_cannot_be_reached_backs_off_the_same_way(
        self, target: dict[str, object]
    ) -> None:
        assert target["neverOpened"] == BACKOFF

    def test_an_attempt_that_never_opens_is_not_credited_with_the_stream_before_it(
        self, target: dict[str, object]
    ) -> None:
        # five connections that dropped at once took 31 s in all; the attempt after them never
        # opened, so it has no stream of its own to be credited with
        assert target["neverOpenedAfterQuickDrops"] == [
            1000,
            2000,
            4000,
            8000,
            16000,
            30000,
            30000,
        ]

    def test_a_stream_that_lived_ten_seconds_starts_the_backoff_again(
        self, target: dict[str, object]
    ) -> None:
        assert target["stableThenDrops"] == [1000, 2000, 4000, 1000, 2000, 4000, 8000]

    def test_nine_seconds_and_a_bit_is_not_stable(
        self, target: dict[str, object]
    ) -> None:
        assert target["justUnderTen"] == [1000, 2000, 4000, 8000]

    def test_exactly_ten_seconds_is_stable(self, target: dict[str, object]) -> None:
        assert target["exactlyTen"] == [1000, 2000, 1000, 2000]

    def test_an_hour_long_stream_restarts_at_the_base_whatever_came_before(
        self, target: dict[str, object]
    ) -> None:
        assert target["anHourThenDrops"] == [1000, 2000, 1000, 2000, 4000]

    def test_streams_that_keep_living_always_reconnect_after_the_base_delay(
        self, target: dict[str, object]
    ) -> None:
        assert target["stableEveryTime"] == [1000, 1000, 1000, 1000]

    def test_a_stream_that_lasted_no_time_after_a_long_backoff_keeps_the_delay(
        self, target: dict[str, object]
    ) -> None:
        assert target["zeroLivedAfterBackoff"] == [1000, 2000, 4000, 8000, 16000, 30000]


class TestEveryWayOfLeavingTheStreamEndsItsClock:
    def test_an_attempt_after_a_disconnect_is_not_credited_with_the_old_stream(
        self, target: dict[str, object]
    ) -> None:
        assert target["afterDisconnect"] == [1000, 2000, 4000]

    def test_an_attempt_after_a_replacement_is_not_credited_with_the_old_stream(
        self, target: dict[str, object]
    ) -> None:
        assert target["afterReplacement"] == [1000, 2000, 4000]
        assert target["replacedWasClosed"] is True

    def test_the_late_error_of_a_replaced_source_is_ignored(
        self, target: dict[str, object]
    ) -> None:
        # the replacement had been open for 20 s when it failed; the first source's error settled
        # nothing, so its stream is the one that is credited
        assert target["lateErrorOfReplacedSource"] == 1000


class TestThePagesOwnSurroundings:
    def test_the_status_reaches_disconnected_once_the_delay_has_hit_the_cap(
        self,
    ) -> None:
        statuses = _results("page")["statusesAfterSevenQuickDrops"]
        assert statuses == ["reconnecting"] * 5 + ["disconnected"] * 2

    def test_the_leader_of_a_tab_group_announces_the_delay_it_uses(self) -> None:
        results = _results("page")
        assert results["leaderDelays"] == [1000, 2000, 4000, 8000, 16000]
        assert results["leaderBroadcast"] == results["leaderDelays"]
        assert results["leaderOpenedEachTime"] == 5


def _block(source: str, marker: str) -> str:
    """The text from ``marker`` to the brace that closes the first ``{`` after it."""
    start = source.index(marker)
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"could not extract {marker}")


class TestTheSourcesAgree:
    SOURCES = (
        ("page", MULTI_TASK_JS.read_text(encoding="utf-8")),
        ("panel", WEBVIEW_UI_JS.read_text(encoding="utf-8")),
    )

    def test_page_panel_and_host_use_the_same_ten_seconds(self) -> None:
        values = []
        for source in (
            MULTI_TASK_JS.read_text(encoding="utf-8"),
            WEBVIEW_UI_JS.read_text(encoding="utf-8"),
            EXTENSION_TS.read_text(encoding="utf-8"),
        ):
            match = re.search(r"SSE_STABLE_CONNECTION_MS\s*=\s*(\d+)", source)
            assert match
            values.append(match.group(1))
        assert values == ["10000"] * 3

    def test_onopen_records_the_time_and_leaves_the_delay_alone(self) -> None:
        for name, source in self.SOURCES:
            body = _block(source, "source.onopen = function")
            assert "_sseReconnectDelay" not in body, name
            assert "_sseOpenedAtMs" in body, name

    def test_the_error_handler_settles_the_account_before_it_schedules_anything(
        self,
    ) -> None:
        for name, source in self.SOURCES:
            body = _block(source, "source.onerror = function")
            assert "_settleSseBackoff()" in body, name
            assert body.index("_settleSseBackoff()") < body.index("setTimeout("), name

    def test_the_settlement_compares_two_timestamps_and_starts_no_timer(self) -> None:
        for name, source in self.SOURCES:
            body = _block(source, "function _settleSseBackoff")
            assert ">= SSE_STABLE_CONNECTION_MS" in body, name
            assert "_sseOpenedAtMs = 0" in body, name
            assert "setTimeout" not in body and "setInterval" not in body, name
