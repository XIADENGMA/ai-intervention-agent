"""R759: a message raised while a dialog is open must be visible.

``showStatus`` writes an error to the status line under the feedback form.
The settings dialog and the paste-code dialog cover the whole page, so a failed
"Test Bark notification", a failed settings save or an empty code box produced
no visible message at all.  While one of those dialogs is open, messages now go
to the toast, which sits above the dialogs; an error stays for 6 s so it can be
read.  The toast also wraps long text instead of running off the screen; it needs
``width: max-content``, because a fixed box that starts at 50% of the page would
otherwise shrink to half the page width and wrap into a tall column.

These tests run the real ``app.js`` in Node against a small DOM model.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from tests.test_app_toast_runtime_r452 import _app_harness, _node_available, _run_node

_DOM = """
        const doc = sandbox.document;
        function add(tag, id, className) {
          const el = doc.createElement(tag);
          el.id = id;
          el.className = className || '';
          doc.body.appendChild(el);
          return el;
        }
        const settings = add('div', 'settings-panel', 'settings-panel hidden');
        const paste = add('div', 'code-paste-panel', 'settings-panel hidden');
        const pasteBox = add('textarea', 'code-paste-textarea');
        pasteBox.value = '';
        const inline = add('div', 'status-message', 'status-message');
        const noContent = add('div', 'no-content-container');
        noContent.style.display = 'none';
        const noContentInline = add('div', 'no-content-status-message', 'status-message');

        const open = (panel) => panel.classList.remove('hidden');
        const toast = () => doc.getElementById('_aiia-toast');
        const hideDelays = () => sandbox.__timers.map((t) => t.delay).filter((d) => d !== 16);
"""


def _run(case_js: str) -> Any:
    return json.loads(_run_node(_app_harness(_DOM + case_js)))


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_error_under_the_settings_dialog_is_a_toast_that_stays_long_enough() -> None:
    result = _run(
        """
        open(settings);
        callStatus('Bark push failed', 'error');
        process.stdout.write(JSON.stringify({
          toast: toast().textContent,
          hideDelays: hideDelays(),
          inline: inline.style.display || null,
        }));
        """
    )

    assert result == {"toast": "Bark push failed", "hideDelays": [6000], "inline": None}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_empty_code_box_error_is_visible_over_the_paste_code_dialog() -> None:
    result = _run(
        """
        paste.classList.remove('hidden');
        paste.classList.add('show');
        const inserted = vm.runInContext('handleCodePasteInsertClick()', sandbox);
        process.stdout.write(JSON.stringify({
          inserted,
          toast: toast().textContent,
          inline: inline.style.display || null,
        }));
        """
    )

    assert result == {"inserted": False, "toast": "status.enterCode", "inline": None}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_closed_dialogs_leave_errors_inline_as_before() -> None:
    result = _run(
        """
        open(settings);
        settings.classList.add('hidden');
        callStatus('Submit failed', 'error');
        process.stdout.write(JSON.stringify({
          inline: { display: inline.style.display, text: inline.textContent },
          toast: toast() === null ? null : toast().textContent,
        }));
        """
    )

    assert result == {
        "inline": {"display": "block", "text": "Submit failed"},
        "toast": None,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_success_and_warning_over_a_dialog_are_toasts_on_the_waiting_page_too() -> None:
    result = _run(
        """
        noContent.style.display = 'flex';
        open(settings);
        callStatus('Test notification sent', 'success');
        const afterSuccess = { toast: toast().textContent, hideDelays: hideDelays() };
        callStatus('Enable Bark first', 'warning');
        process.stdout.write(JSON.stringify({
          afterSuccess,
          afterWarning: toast().textContent,
          waitingPageLine: noContentInline.style.display || null,
        }));
        """
    )

    assert result == {
        "afterSuccess": {"toast": "Test notification sent", "hideDelays": [1800]},
        "afterWarning": "Enable Bark first",
        "waitingPageLine": None,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_info_is_still_dropped_over_a_dialog() -> None:
    result = _run(
        """
        open(settings);
        callStatus('Sending...', 'info');
        process.stdout.write(JSON.stringify({ toast: toast() === null }));
        """
    )

    assert result == {"toast": True}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_a_long_message_wraps_inside_the_screen() -> None:
    result = _run(
        """
        callToast('x'.repeat(300));
        const style = toast().style;
        process.stdout.write(JSON.stringify({
          whiteSpace: style.whiteSpace,
          width: style.width,
          maxWidth: style.maxWidth,
        }));
        """
    )

    assert result["whiteSpace"] != "nowrap"
    assert result["width"] == "max-content"
    assert result["maxWidth"]
