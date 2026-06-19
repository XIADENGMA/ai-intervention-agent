"""R452 · Browser multi-tab SSE sharing contract.

The Web UI keeps one direct ``EventSource`` per visible tab when
``BroadcastChannel`` is not available. When it is available, only one same-origin
tab should hold ``/api/events`` and fan out named SSE events to followers.

This is intentionally a source-level invariant suite. The edge we are guarding
is not JSON parsing or DOM rendering; it is the easily-regressed cross-tab
contract: leader election, direct fallback, Last-Event-ID propagation, and
leader handoff on hidden/unload.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _read() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"(^|[^:])//.*", r"\1", src)
    return src


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_broadcast_channel_is_used_for_same_origin_sse_sharing() -> None:
    text = _read()
    code = _strip_comments(text)
    assert 'SSE_SHARED_CHANNEL_NAME = "aiia:sse:v1"' in code
    assert "BroadcastChannel" in code
    assert "new BroadcastChannelCtor(SSE_SHARED_CHANNEL_NAME)" in code


def test_connect_sse_keeps_direct_fallback_when_broadcast_channel_missing() -> None:
    code = _strip_comments(_read())
    match = re.search(
        r"function\s+_connectSSE\s*\(\)\s*\{(?P<body>.*?)\n\}", code, re.S
    )
    assert match, "multi_task.js must expose _connectSSE wrapper"
    body = match.group("body")
    assert "_getBroadcastChannelCtor()" in body
    assert "_connectSharedSSE()" in body
    assert "_connectDirectSSE(false)" in body


def test_leader_mode_broadcasts_named_sse_events_and_last_event_id() -> None:
    code = _strip_comments(_read())
    assert 'eventType: "task_changed"' in code
    assert 'eventType: "gap_warning"' in code
    assert 'eventType: "config_changed"' in code
    assert 'eventType: "heartbeat"' in code
    assert "eventLastEventId" in code
    assert "message.lastEventId" in code
    assert "_updateSharedLastEventId" in code


def test_leader_handoff_and_split_brain_guards_are_present() -> None:
    code = _strip_comments(_read())
    assert "leader_gone" in code
    assert "_scheduleSseLeaderElection(50)" in code
    assert "_startSseSharedWatchdog" in code
    assert "leaderId < _sseSharedClientId" in code
    assert "_stepDownFromSseLeader" in code


def test_disconnect_cleans_shared_channel_and_debounce_timer() -> None:
    code = _strip_comments(_read())
    start = code.find("function _disconnectSSE()")
    end = code.find("function getNextBackoffMs", start)
    assert start >= 0 and end > start, "multi_task.js must expose _disconnectSSE"
    body = code[start:end]
    for literal in (
        "_sseDebounceTimer",
        "_sseSharedElectionTimer",
        "_sseSharedWatchdogTimer",
        "_sseSharedLeaderHeartbeatTimer",
        "_sseSharedChannel.close()",
        "leader_gone",
    ):
        assert literal in body


def test_observable_shared_mode_getter_is_exported() -> None:
    code = _strip_comments(_read())
    assert "get sseSharedMode()" in code
    assert '"leader"' in code
    assert '"follower"' in code
    assert '"direct"' in code


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_shared_sse_connect_is_idempotent_at_runtime() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(MULTI_TASK_JS)!r}, 'utf8');
        const timers = [];
        const intervals = [];
        const posted = [];
        let channelConstructs = 0;
        const sandbox = {{
          console,
          Math,
          Date,
          Number,
          String,
          JSON,
          Promise,
          URLSearchParams,
          setTimeout(fn, delay) {{
            timers.push({{ fn, delay }});
            return timers.length;
          }},
          clearTimeout() {{}},
          setInterval(fn, delay) {{
            intervals.push({{ fn, delay }});
            return intervals.length;
          }},
          clearInterval() {{}},
          fetch: async () => ({{ ok: true, json: async () => ({{ success: true, tasks: [], stats: {{}} }}) }}),
        }};
        sandbox.window = sandbox;
        sandbox.navigator = {{}};
        sandbox.document = {{
          hidden: false,
          addEventListener() {{}},
          getElementById() {{ return null; }},
          querySelector() {{ return null; }},
          querySelectorAll() {{ return []; }},
          body: {{ contains() {{ return true; }} }},
          documentElement: {{ setAttribute() {{}} }},
        }};
        sandbox.EventSource = function EventSource(url) {{
          this.url = url;
          this.addEventListener = function () {{}};
          this.close = function () {{}};
        }};
        sandbox.BroadcastChannel = function BroadcastChannel(name) {{
          channelConstructs += 1;
          this.name = name;
          this.postMessage = (message) => posted.push(message);
          this.close = function () {{}};
        }};
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        sandbox._connectSSE();
        sandbox._connectSSE();

        if (channelConstructs !== 1) {{
          throw new Error('expected one BroadcastChannel, got ' + channelConstructs);
        }}
        const helloCount = posted.filter((m) => m && m.kind === 'hello').length;
        if (helloCount !== 2) {{
          throw new Error('expected two hello messages, got ' + helloCount);
        }}
        process.stdout.write(JSON.stringify({{ channelConstructs, helloCount }}));
        """
    )

    assert _run_node(script) == '{"channelConstructs":1,"helloCount":2}'


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_follower_shared_event_resumes_from_latest_event_id() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(MULTI_TASK_JS)!r}, 'utf8');
        const timers = [];
        const eventSourceUrls = [];
        const fetchReasons = [];
        const sandbox = {{
          console,
          Math,
          Date,
          Number,
          String,
          JSON,
          Promise,
          URLSearchParams,
          setTimeout(fn, delay) {{
            timers.push({{ fn, delay }});
            return timers.length;
          }},
          clearTimeout() {{}},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          fetch: async () => ({{ ok: true, json: async () => ({{ success: true, tasks: [], stats: {{}} }}) }}),
        }};
        sandbox.window = sandbox;
        sandbox.navigator = {{}};
        sandbox.document = {{
          hidden: false,
          addEventListener() {{}},
          getElementById() {{ return null; }},
          querySelector() {{ return null; }},
          querySelectorAll() {{ return []; }},
          body: {{ contains() {{ return true; }} }},
          documentElement: {{ setAttribute() {{}} }},
        }};
        sandbox.EventSource = function EventSource(url) {{
          eventSourceUrls.push(url);
          this.url = url;
          this.addEventListener = function () {{}};
          this.close = function () {{}};
        }};
        sandbox.BroadcastChannel = function BroadcastChannel() {{
          this.postMessage = function () {{}};
          this.close = function () {{}};
        }};
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        sandbox.fetchAndApplyTasks = function (reason) {{
          fetchReasons.push(reason);
          return Promise.resolve(true);
        }};

        sandbox._connectSSE();
        sandbox._onSseSharedMessage({{
          data: {{ kind: 'leader', clientId: 'leader-a', leaderId: 'leader-a', lastEventId: '10' }}
        }});
        sandbox._onSseSharedMessage({{
          data: {{
            kind: 'event',
            clientId: 'leader-a',
            eventType: 'task_changed',
            eventLastEventId: '11',
            data: JSON.stringify({{ task_id: 't1', old_status: 'pending', new_status: 'completed' }})
          }}
        }});
        const scheduledFetch = timers.find((entry) => entry.delay === 80);
        if (!scheduledFetch) throw new Error('expected 80ms shared SSE fetch debounce');
        scheduledFetch.fn();
        sandbox._becomeSseLeader();

        const resumed = eventSourceUrls.some((url) => url === '/api/events?last_event_id=11');
        if (!resumed) {{
          throw new Error('expected resume URL with latest id; saw ' + JSON.stringify(eventSourceUrls));
        }}
        process.stdout.write(JSON.stringify({{ fetchReasons, eventSourceUrls }}));
        """
    )

    result = _run_node(script)
    assert '"fetchReasons":["sse"]' in result
    assert '"/api/events?last_event_id=11"' in result
