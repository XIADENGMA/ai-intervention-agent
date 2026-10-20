"""R757: a tab click that the server did not accept is reported and undone at once.

``switchTask`` shows the clicked task immediately and tells the server in the
background.  The refresh that follows treats the server's active task as the
truth, so when the request failed the page kept the clicked task for as long
as it took the next refresh to arrive (about 30 s once the event stream is
connected) and then jumped back without a word, possibly while the user was
typing.  The VS Code webview already rolls back and says so; the Web UI now
reports the failure and fetches the task list as soon as the switch lock is
released.

These tests run the real ``multi_task.js`` in Node with a fake clock; only the
browser surface (fetch, timers, ``showStatus``) is faked.
"""

from __future__ import annotations

import json
import unittest

from tests.test_multi_task_active_task_reconcile_r452 import (
    _multi_task_harness,
    _node_available,
    _run_node,
)

_PRELUDE = """
        const timers = [];
        let now = 0;
        setTimeout = (fn, delay) => {
          const timer = {
            id: timers.length + 1,
            fn,
            due: now + (delay || 0),
            cleared: false,
            done: false,
          };
          timers.push(timer);
          return timer.id;
        };
        clearTimeout = (id) => {
          const timer = timers.find((entry) => entry.id === id);
          if (timer) timer.cleared = true;
        };
        const settle = async () => {
          for (let i = 0; i < 40; i += 1) await Promise.resolve();
        };
        const advance = async (ms) => {
          const target = now + ms;
          for (;;) {
            const due = timers
              .filter((entry) => !entry.cleared && !entry.done && entry.due <= target)
              .sort((a, b) => a.due - b.due || a.id - b.id);
            if (due.length === 0) break;
            now = due[0].due;
            due[0].done = true;
            due[0].fn();
            await settle();
          }
          now = target;
        };

        const statuses = [];
        showStatus = (message, type) => statuses.push([message, type]);

        const listRequests = [];
        let serverActive = 'a';
        fetch = async (url) => {
          listRequests.push(String(url));
          const open = (id) => ({
            task_id: id,
            status: id === serverActive ? 'active' : 'pending',
            prompt: 'prompt ' + id,
            auto_resubmit_timeout: 0,
          });
          return {
            ok: true,
            json: async () => ({ success: true, tasks: [open('a'), open('b')] }),
          };
        };

        const activations = {};
        fetchWithTimeout = (url) => {
          const match = /\\/api\\/tasks\\/([^/]+)\\/activate$/.exec(String(url));
          if (!match) return new Promise(() => {});
          return new Promise((resolve, reject) => {
            activations[match[1]] = { resolve, reject };
          });
        };

        const open = (id, status) => ({
          task_id: id,
          status,
          prompt: 'prompt ' + id,
          auto_resubmit_timeout: 0,
        });
        window.currentTasks = [open('a', 'active'), open('b', 'pending')];
        currentTasks = window.currentTasks;
        setActiveTaskId('a');

        const snapshot = () => ({
          activeTaskId,
          statuses: statuses.slice(),
          listRequests: listRequests.slice(),
        });
"""


def _run(case_js: str) -> dict[str, object]:
    script = _multi_task_harness(_PRELUDE + case_js)
    return json.loads(_run_node(script))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_network_failure_is_reported_and_the_page_returns_to_the_servers_task() -> None:
    result = _run(
        """
        await api.switchTask('b');
        activations.b.reject(new TypeError('Failed to fetch'));
        await settle();
        const reported = snapshot();

        await advance(MANUAL_SWITCH_LOCK_MS + 100);
        process.stdout.write(JSON.stringify({ reported, resynced: snapshot() }));
        """
    )

    assert result["reported"] == {
        "activeTaskId": "b",
        "statuses": [["status.switchFailed", "error"]],
        "listRequests": [],
    }
    assert result["resynced"] == {
        "activeTaskId": "a",
        "statuses": [["status.switchFailed", "error"]],
        "listRequests": ["/api/tasks"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_refusal_from_the_server_is_handled_the_same_way() -> None:
    result = _run(
        """
        await api.switchTask('b');
        activations.b.resolve({
          json: async () => ({ success: false, error: 'task not found' }),
        });
        await settle();
        await advance(MANUAL_SWITCH_LOCK_MS + 100);
        process.stdout.write(JSON.stringify(snapshot()));
        """
    )

    assert result == {
        "activeTaskId": "a",
        "statuses": [["status.switchFailed", "error"]],
        "listRequests": ["/api/tasks"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_switch_the_server_applied_is_left_alone() -> None:
    result = _run(
        """
        await api.switchTask('b');
        activations.b.resolve({ json: async () => ({ success: true }) });
        await settle();
        serverActive = 'b';
        await advance(2000);
        process.stdout.write(JSON.stringify(snapshot()));
        """
    )

    assert result == {"activeTaskId": "b", "statuses": [], "listRequests": []}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_resync_waits_for_the_switch_lock() -> None:
    result = _run(
        """
        await api.switchTask('b');
        activations.b.reject(new TypeError('Failed to fetch'));
        await settle();
        const lockedWindow = [];
        await advance(MANUAL_SWITCH_LOCK_MS - 10);
        lockedWindow.push(snapshot().listRequests.length, window.isManualSwitching);
        await advance(100);
        process.stdout.write(JSON.stringify({
          lockedWindow,
          after: snapshot().listRequests.length,
          locked: window.isManualSwitching,
        }));
        """
    )

    assert result == {"lockedWindow": [0, True], "after": 1, "locked": False}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_failure_for_a_task_the_user_left_is_ignored() -> None:
    result = _run(
        """
        await api.switchTask('b');
        await api.switchTask('a');
        activations.a.resolve({ json: async () => ({ success: true }) });
        activations.b.reject(new TypeError('Failed to fetch'));
        await settle();
        await advance(2000);
        process.stdout.write(JSON.stringify(snapshot()));
        """
    )

    assert result == {"activeTaskId": "a", "statuses": [], "listRequests": []}
