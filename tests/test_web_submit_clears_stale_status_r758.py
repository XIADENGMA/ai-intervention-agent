"""R758: a new submit attempt starts without the previous attempt's error.

An error from ``showStatus`` stays in the inline status line for 10 s.  A
success only raises a toast, so after "Please enter feedback" (an empty form
submitted by mistake) or a failed submit followed by a good one, the red
line was still there next to the next task's form.  ``submitFeedback`` now
hides the inline status when an attempt starts, after the form passed
validation.

These tests run the real ``app.js`` in Node against a small DOM model; only
the browser surface (elements, fetch, timers) is faked.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from tests.test_app_toast_runtime_r452 import _app_harness, _node_available, _run_node

_FORM = """
        const doc = sandbox.document;
        const feedback = doc.createElement('textarea');
        feedback.id = 'feedback-text';
        doc.body.appendChild(feedback);
        const submit = doc.createElement('button');
        submit.id = 'submit-btn';
        doc.body.appendChild(submit);
        const status = doc.createElement('div');
        status.id = 'status-message';
        doc.body.appendChild(status);
        doc.querySelectorAll = () => [];
        sandbox.FormData = function FormData() {
          this.append = () => {};
        };
        sandbox.selectedImages = [];
        sandbox.clearAllImages = () => {};
        sandbox.refreshTasksList = async () => {};

        const line = () => ({ display: status.style.display, text: status.textContent });
        const submitWith = async (respond) => {
          sandbox.fetch = respond;
          await vm.runInContext('submitFeedback()', sandbox);
        };
        const accepted = async () => ({
          ok: true,
          status: 200,
          json: async () => ({ message: 'accepted' }),
        });
"""


def _run(case_js: str) -> Any:
    return json.loads(_run_node(_app_harness(_FORM + case_js)))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_good_submit_leaves_no_error_line_behind() -> None:
    result = _run(
        """
        feedback.value = 'text';
        callStatus('Please enter feedback', 'error');
        const before = line();
        await submitWith(accepted);
        process.stdout.write(JSON.stringify({ before, after: line() }));
        """
    )

    assert result["before"] == {"display": "block", "text": "Please enter feedback"}
    assert result["after"]["display"] == "none"


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_the_old_error_is_gone_while_the_request_is_in_flight() -> None:
    result = _run(
        """
        feedback.value = 'text';
        callStatus('Please enter feedback', 'error');
        let duringRequest = null;
        await submitWith(async () => {
          duringRequest = line();
          return accepted();
        });
        process.stdout.write(JSON.stringify(duringRequest));
        """
    )

    assert result["display"] == "none"


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_failed_retry_replaces_the_old_error_with_its_own() -> None:
    result = _run(
        """
        feedback.value = 'text';
        callStatus('Please enter feedback', 'error');
        await submitWith(async () => { throw new TypeError('Failed to fetch'); });
        process.stdout.write(JSON.stringify(line()));
        """
    )

    assert result == {"display": "block", "text": "status.networkOffline"}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_validation_error_of_the_attempt_itself_is_kept() -> None:
    result = _run(
        """
        feedback.value = '';
        await submitWith(accepted);
        process.stdout.write(JSON.stringify(line()));
        """
    )

    assert result == {"display": "block", "text": "status.submitEmpty"}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_the_old_dismiss_timer_is_cancelled_and_cannot_hide_a_newer_error() -> None:
    result = _run(
        """
        feedback.value = 'text';
        callStatus('Please enter feedback', 'error');
        const dismissTimer = sandbox.__timers.find((entry) => entry.delay === 10000);
        await submitWith(accepted);
        const cancelled = dismissTimer.cleared;
        callStatus('Another error', 'error');
        sandbox.__runTimer(dismissTimer.id, true);
        process.stdout.write(JSON.stringify({ cancelled, line: line() }));
        """
    )

    assert result == {
        "cancelled": True,
        "line": {"display": "block", "text": "Another error"},
    }
