"""R760: a notification setting the server did not take is reported.

Every change in the notification settings is applied in the browser at once and
sent to the server in the background (the server needs it for Bark and the
other channels).  A failed request used to leave only a console line behind, so
the page kept showing a Bark switch that the server never received, and the next
page load went back to the server's value without a word.  The feedback config
next to it has always reported its failures.

These tests run the real ``settings-manager.js`` in Node; only fetch and the
status line are faked.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from tests.test_settings_manager_backend_sync_queue_r452 import (
    _node_available,
    _run_node,
    _settings_manager_harness,
)

_PRELUDE = """
        const statuses = [];
        sandbox.showStatus = (message, type) => { statuses.push([message, type]); };
        const manager = new exported.SettingsManager();
        manager.settings = { ...manager.defaultSettings };
        const REPORT = ['settings.notificationConfigSaveFailed', 'error'];
"""


def _run(case_js: str) -> Any:
    return json.loads(_run_node(_settings_manager_harness(_PRELUDE + case_js)))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_an_error_answer_is_reported() -> None:
    result = _run(
        """
        manager.updateSetting('barkEnabled', true);
        const queue = manager._backendSyncPromise;
        sandbox.__fetchCalls[0].resolve({ status: 'error', message: 'Update failed' }, false);
        await queue;
        process.stdout.write(JSON.stringify({ statuses, report: REPORT }));
        """
    )

    assert result["statuses"] == [result["report"]]


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_network_failure_is_reported() -> None:
    result = _run(
        """
        manager.updateSetting('barkEnabled', true);
        const queue = manager._backendSyncPromise;
        sandbox.__fetchCalls[0].reject(new TypeError('Failed to fetch'));
        await queue;
        process.stdout.write(JSON.stringify({ statuses, report: REPORT }));
        """
    )

    assert result["statuses"] == [result["report"]]


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_an_answer_that_is_not_json_is_reported() -> None:
    result = _run(
        """
        sandbox.fetch = () => Promise.resolve({
          ok: false,
          json: () => Promise.reject(new SyntaxError('Unexpected token <')),
        });
        manager.updateSetting('barkEnabled', true);
        await manager._backendSyncPromise;
        process.stdout.write(JSON.stringify({ statuses, report: REPORT }));
        """
    )

    assert result["statuses"] == [result["report"]]


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_successful_sync_says_nothing() -> None:
    result = _run(
        """
        manager.updateSetting('barkEnabled', true);
        const queue = manager._backendSyncPromise;
        sandbox.__fetchCalls[0].resolve();
        await queue;
        process.stdout.write(JSON.stringify(statuses));
        """
    )

    assert result == []


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_an_old_failure_is_not_reported_once_a_later_sync_succeeded() -> None:
    result = _run(
        """
        manager.updateSetting('soundVolume', 10);
        const queue = manager._backendSyncPromise;
        manager.updateSetting('soundVolume', 20);
        sandbox.__fetchCalls[0].resolve({ status: 'error' }, false);
        await sandbox.__flushMicrotasks(6);
        const whileQueued = statuses.length;
        sandbox.__fetchCalls[1].resolve();
        await queue;
        process.stdout.write(JSON.stringify({ whileQueued, statuses }));
        """
    )

    assert result == {"whileQueued": 0, "statuses": []}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_failure_after_an_earlier_success_is_reported_once() -> None:
    result = _run(
        """
        manager.updateSetting('soundVolume', 10);
        const queue = manager._backendSyncPromise;
        manager.updateSetting('soundVolume', 20);
        sandbox.__fetchCalls[0].resolve();
        await sandbox.__flushMicrotasks(6);
        sandbox.__fetchCalls[1].resolve({ status: 'error' }, false);
        await queue;
        process.stdout.write(JSON.stringify({ statuses, report: REPORT }));
        """
    )

    assert result["statuses"] == [result["report"]]


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_two_failures_in_a_row_are_reported_once() -> None:
    result = _run(
        """
        manager.updateSetting('soundVolume', 10);
        const queue = manager._backendSyncPromise;
        manager.updateSetting('soundVolume', 20);
        sandbox.__fetchCalls[0].reject(new TypeError('Failed to fetch'));
        await sandbox.__flushMicrotasks(6);
        sandbox.__fetchCalls[1].reject(new TypeError('Failed to fetch'));
        await queue;
        process.stdout.write(JSON.stringify({ statuses, report: REPORT }));
        """
    )

    assert result["statuses"] == [result["report"]]
