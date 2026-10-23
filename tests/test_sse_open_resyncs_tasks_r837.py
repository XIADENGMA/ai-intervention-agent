"""R837: the page and the panel fetch the task list again when their event stream opens.

``EventSource.onopen`` of the Web UI page (``multi_task.js``) and of the VS Code panel's webview
(``webview-ui.js``) slowed the polling down to its 30 s safety net and did nothing else.  That is
only correct while the stream can replay what the page missed.  The server's replay needs the
``last_event_id`` of the page to be a position in *its* history, and a server that was started
again numbers its events from 1: a page that had seen event 57 asks for everything after 57, the
new server has not got that far, and it answers with nothing and no ``gap_warning`` either.  A task
that was created after the last poll and before the stream was back was therefore invisible for
the whole safety net interval.

Measured in real Chrome 153 against a real Web UI that was killed (SIGKILL) and started again on the
same snapshot, which is what the MCP server's revival (R825) does about 10 s after the Web UI
stopped answering: task B created 0.5 s before the page's stream reconnected showed up 30.5 s
after it was created (the poll that would have shown it had been moved from 20 s to 45 s by the
stream opening); with the page fetching when its stream opens it shows up 0.3 s after.  The same
hole is open on every reconnect where the replay cannot cover the gap and, for a page that has just
been loaded, between its first fetch and the moment the server subscribes its stream.

The rule is the usual one for a stream that carries change *notifications*: subscribe first, then
fetch the state once.  Whatever happened before the subscription is in the fetch, whatever happens
after it is in the stream.  ``onopen`` of the page's own stream and of the panel's now schedules one
fetch (reason ``sse-open``); a tab that follows a leader does the same when the leader announces
that its stream is open, but not on the leader's heartbeat, which would be a fetch every few
seconds.  The page lets this reason through while it is hidden, like the other stream-driven
reasons, so that a tab in the background still notices the task.

The tests run both scripts in Node against a fake ``EventSource``, recorded timers and a recording
``fetch``.
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

PRELUDE = r"""
const fs = require('fs');
const vm = require('vm');

const sources = [];
const timers = [];
const fetches = [];
const polls = [];
const posted = [];

function FakeEventSource(url) {
  this.url = url;
  this.closed = false;
  this.addEventListener = function () {};
  this.close = function () { this.closed = true; };
  sources.push(this);
}

// The scripts log with console.debug (stdout in Node), which would end up in the JSON the test reads.
// Errors are kept: a fetch that fails inside the script is a failure of the test, not noise.
const quiet = {
  debug() {},
  log() {},
  info() {},
  warn() {},
  error: (...args) => process.stderr.write(args.join(' ') + '\n'),
};

const common = {
  console: quiet,
  Math,
  Number,
  String,
  JSON,
  Promise,
  URLSearchParams,
  setTimeout(fn, delay) {
    timers.push({ fn, delay, cancelled: false, fired: false });
    return timers.length;
  },
  clearTimeout(id) {
    if (timers[id - 1]) timers[id - 1].cancelled = true;
  },
  setInterval() { return 1; },
  clearInterval() {},
  fetch: async (url) => {
    fetches.push(String(url));
    return { ok: true, json: async () => ({ success: true, tasks: [], stats: {} }) };
  },
  EventSource: FakeEventSource,
};

function newest() { return sources[sources.length - 1]; }

// Runs the timers that are due "now": the ones a stream handler schedules with a delay of at most
// `limit` ms.  The 30 s poll and the reconnect timers are left alone.
function flush(limit) {
  for (let round = 0; round < 20; round += 1) {
    const due = timers.filter((t) => !t.cancelled && !t.fired && t.delay <= limit);
    if (!due.length) return;
    for (const t of due) {
      t.fired = true;
      t.fn();
    }
  }
}

function reset() {
  sources.length = 0;
  timers.length = 0;
  fetches.length = 0;
  polls.length = 0;
  posted.length = 0;
}
"""

PAGE_HARNESS = r"""
const code = fs.readFileSync(__SOURCE__, 'utf8');

function makePage({ channel, hidden }) {
  reset();
  const sandbox = Object.assign({}, common);
  sandbox.window = sandbox;
  sandbox.navigator = {};
  sandbox.document = {
    hidden: !!hidden,
    addEventListener() {},
    getElementById() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    body: { contains() { return true; } },
    documentElement: { setAttribute() {} },
  };
  if (channel) {
    sandbox.BroadcastChannel = function BroadcastChannel() {
      this.postMessage = (message) => posted.push(message);
      this.close = function () {};
    };
  }
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  sandbox.updateTasksList = function () {};
  sandbox.updateTasksStats = function () {};
  return sandbox;
}

const out = {};

{
  // the page's own stream, without a group of tabs
  const page = makePage({ channel: false });
  page._connectSSE();
  flush(100);
  out.fetchesBeforeOpen = fetches.slice();
  newest().onopen();
  out.fetchPendingAfterOpen = timers.filter((t) => !t.cancelled && !t.fired && t.delay === 0).length;
  flush(100);
  out.fetchesAfterOpen = fetches.slice();
  out.pollDelayAfterOpen = page.tasksPollBackoffMs;
  out.connectedAfterOpen = page._sseConnected;
}

{
  // every open counts, not only the first: drop the stream, let the reconnect timer run, open again
  const page = makePage({ channel: false });
  page._connectSSE();
  newest().onopen();
  flush(100);
  const first = fetches.length;
  newest().onerror();
  const retry = page._sseReconnectTimer;
  timers[retry - 1].fn();
  flush(100);
  const beforeSecondOpen = fetches.length;
  newest().onopen();
  flush(100);
  out.reopen = { first, beforeSecondOpen, afterSecondOpen: fetches.length, sources: sources.length };
}

{
  // a stream that opens and is replaced at once: two opens in a row make one fetch per open at most
  const page = makePage({ channel: false });
  page._connectSSE();
  newest().onopen();
  newest().onopen();
  flush(100);
  out.doubleOpenFetches = fetches.length;
}

{
  // a hidden tab keeps its stream, and the task it missed must be noticed there too
  const page = makePage({ channel: false, hidden: true });
  page._connectSSE();
  newest().onopen();
  flush(100);
  out.hiddenFetches = fetches.slice();
}

{
  // a stream that was replaced before it opened does not fetch for the one that replaced it
  const page = makePage({ channel: false });
  page._connectSSE();
  const stale = newest();
  page._connectDirectSSE(false);
  stale.onopen();
  flush(100);
  out.staleOpenFetches = fetches.length;
}

{
  // the leader of a group of tabs fetches when its own stream opens and tells the others
  const page = makePage({ channel: true });
  page._connectSSE();
  const election = timers.find((t) => t.delay === 160);
  election.fn();
  newest().onopen();
  flush(100);
  out.leader = {
    fetches: fetches.slice(),
    announced: posted.filter((m) => m.kind === 'open').length,
  };
}

{
  // a tab that follows: the leader's announcement that its stream is open fetches, its heartbeat does not
  const page = makePage({ channel: true });
  page._connectSSE();
  const leader = { kind: 'leader', clientId: 'tab-zzz', leaderId: 'tab-zzz' };
  page._onSseSharedMessage({ data: leader });
  page._onSseSharedMessage({ data: leader });
  page._onSseSharedMessage({ data: leader });
  flush(100);
  const afterBeacons = fetches.length;
  page._onSseSharedMessage({ data: { kind: 'open', clientId: 'tab-zzz', leaderId: 'tab-zzz' } });
  flush(100);
  out.follower = {
    afterBeacons,
    afterOpen: fetches.slice(),
    ownSources: sources.length,
    connected: page._sseConnected,
  };
}

{
  // two tabs that both think they lead: the one with the smaller id keeps the stream.  The other
  // stays leader (and fetches nothing for it) or steps down (and reads the list, like a follower).
  const stays = makePage({ channel: true });
  stays._connectSSE();
  timers.find((t) => t.delay === 160).fn();
  const own = fetches.length;
  stays._onSseSharedMessage({ data: { kind: 'open', clientId: 'tab-zzzz', leaderId: 'tab-zzzz' } });
  flush(100);
  out.leaderStays = { own, after: fetches.length, stillLeader: stays._sseSharedIsLeader };

  const steps = makePage({ channel: true });
  steps._connectSSE();
  timers.find((t) => t.delay === 160).fn();
  const before = fetches.length;
  steps._onSseSharedMessage({ data: { kind: 'open', clientId: 'tab-000', leaderId: 'tab-000' } });
  flush(100);
  out.leaderSteps = { before, after: fetches.slice(), stillLeader: steps._sseSharedIsLeader };
}

process.stdout.write(JSON.stringify(out));
"""

PANEL_HARNESS = r"""
const source = fs.readFileSync(__SOURCE__, 'utf8');
const start = source.indexOf('let _sseSource = null');
const end = source.indexOf('function installPollingVisibilityHandler', start);
if (start < 0 || end < 0) throw new Error('the SSE block of webview-ui.js was not found');
const block = source.slice(start, end);

function makePanel({ hidden }) {
  reset();
  const sandbox = Object.assign({}, common);
  sandbox.document = { hidden: !!hidden };
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
    function pollAllData(reason) { __polls.push(reason); }
    function syncServerLanguage() {}
    ${block}
    globalThis.__panel = {
      connect: _connectSSE,
      timerId: () => _sseReconnectTimer,
      pollBackoff: () => pollBackoffMs,
    };
    `,
    Object.assign(sandbox, { __polls: polls }),
  );
  return sandbox.__panel;
}

const out = {};

{
  const panel = makePanel({ hidden: false });
  panel.connect();
  flush(100);
  out.pollsBeforeOpen = polls.slice();
  newest().onopen();
  flush(100);
  out.pollsAfterOpen = polls.slice();
  out.pollDelayAfterOpen = panel.pollBackoff();
}

{
  const panel = makePanel({ hidden: false });
  panel.connect();
  newest().onopen();
  flush(100);
  const first = polls.length;
  newest().onerror();
  timers[panel.timerId() - 1].fn();
  newest().onopen();
  flush(100);
  out.reopen = { first, afterSecondOpen: polls.length, sources: sources.length };
}

{
  const panel = makePanel({ hidden: false });
  panel.connect();
  const stale = newest();
  panel.connect();
  stale.onopen();
  flush(100);
  out.staleOpenPolls = polls.length;
}

process.stdout.write(JSON.stringify(out));
"""


@functools.cache
def _results(target: str) -> dict[str, Any]:
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
    assert completed.stderr == "", completed.stderr
    return json.loads(completed.stdout)


TASKS = "/api/tasks"


class TestPage:
    def test_nothing_is_fetched_before_the_stream_is_open(self) -> None:
        """Subscribe first, then fetch: a fetch that is sent before the server has subscribed the
        stream would leave the same hole open."""
        assert _results("page")["fetchesBeforeOpen"] == []

    def test_opening_the_stream_fetches_the_task_list_once(self) -> None:
        out = _results("page")
        assert out["fetchPendingAfterOpen"] == 1
        assert out["fetchesAfterOpen"] == [TASKS]

    def test_the_poll_is_still_slowed_down_to_the_safety_net(self) -> None:
        out = _results("page")
        assert out["connectedAfterOpen"] is True
        assert out["pollDelayAfterOpen"] == 30000

    def test_every_open_fetches_not_only_the_first(self) -> None:
        out = _results("page")["reopen"]
        assert out["sources"] == 2
        assert out["first"] == 1
        assert out["beforeSecondOpen"] == 1
        assert out["afterSecondOpen"] == 2

    def test_two_opens_before_the_timer_runs_make_one_fetch(self) -> None:
        assert _results("page")["doubleOpenFetches"] == 1

    def test_a_hidden_tab_fetches_too(self) -> None:
        assert _results("page")["hiddenFetches"] == [TASKS]

    def test_a_stream_that_was_replaced_does_not_fetch(self) -> None:
        assert _results("page")["staleOpenFetches"] == 0

    def test_the_leader_of_a_group_fetches_and_announces_its_open_stream(self) -> None:
        out = _results("page")["leader"]
        assert out["fetches"] == [TASKS]
        assert out["announced"] == 1

    def test_a_follower_fetches_on_open_but_not_on_the_leaders_heartbeat(self) -> None:
        out = _results("page")["follower"]
        assert out["ownSources"] == 0
        assert out["connected"] is True
        assert out["afterBeacons"] == 0
        assert out["afterOpen"] == [TASKS]

    def test_a_leader_that_stays_does_not_fetch_for_the_open_of_another_tab(
        self,
    ) -> None:
        out = _results("page")["leaderStays"]
        assert out["stillLeader"] is True
        assert out["after"] == out["own"] == 0

    def test_a_leader_that_steps_down_reads_the_list_like_a_follower(self) -> None:
        out = _results("page")["leaderSteps"]
        assert out["stillLeader"] is False
        assert out["before"] == 0
        assert out["after"] == [TASKS]


class TestPanel:
    def test_nothing_is_polled_before_the_stream_is_open(self) -> None:
        assert _results("panel")["pollsBeforeOpen"] == []

    def test_opening_the_stream_polls_the_task_list_once(self) -> None:
        assert _results("panel")["pollsAfterOpen"] == ["sse-open"]

    def test_the_poll_is_still_slowed_down_to_the_safety_net(self) -> None:
        assert _results("panel")["pollDelayAfterOpen"] == 30000

    def test_every_open_polls_not_only_the_first(self) -> None:
        out = _results("panel")["reopen"]
        assert out["sources"] == 2
        assert out["first"] == 1
        assert out["afterSecondOpen"] == 2

    def test_a_stream_that_was_replaced_does_not_poll(self) -> None:
        assert _results("panel")["staleOpenPolls"] == 0
