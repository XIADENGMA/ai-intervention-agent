"""R734 — programmatic writes to the feedback box reach the listeners that mirror it.

Why this exists
---------------
Three modules mirror ``#feedback-text`` and only learn about edits from
``input`` events: the character counter (``feedback_char_counter.js``), the
per-task draft store (``feedback_drafts.js``) and the in-memory composer
(``multi_task.js::handleRealtimeTextareaAutosave``, which also stamps
``lastFeedbackTypingAtMs`` for the typing hold of the auto-submit countdown).
Assigning ``textarea.value`` raises no event, and two ``app.js`` paths did
exactly that:

1. ``insertCodeBlockIntoFeedbackTextarea`` (the paste-code dialog and the
   clipboard shortcut): the counter kept the old length, and the in-memory
   and stored drafts kept the text from before the insert until the next
   keystroke (the 30 s reconcile even persisted the stale in-memory copy).
2. The ``submitFeedback`` success path clears the box.  When the follow-up
   task-list refresh fails, or hands back the same active task, nothing
   re-renders the composer, so the counter kept showing the length of the
   text that had just been sent.

The fix
-------
(1) dispatches one bubbling ``input`` event once value and selection are
final (the same trick ``slash-commands.js`` uses).  (2) calls
``refreshFeedbackCharCounter()`` directly after the clear.  It deliberately
does *not* dispatch a synthetic ``input`` there: that would stamp the typing
marker, and the next task's countdown could then be held back although
nobody typed.

Pattern: C (runtime) — Node harnesses over the real ``app.js`` functions and,
for the end-to-end check, the real ``feedback_char_counter.js``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.test_app_submit_feedback_stale_task_r452 import (
    APP_JS,
    _extract_function,
    _node_available,
    _run_node,
    _submit_harness,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COUNTER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "feedback_char_counter.js"
)

_INSERT_PRELUDE = """
const calls = [];
const events = [];
class Event {
  constructor(type, init) {
    this.type = type;
    this.bubbles = Boolean(init && init.bubbles);
  }
}
function makeTextarea(value, caret) {
  const listeners = [];
  const textarea = {
    value,
    selectionStart: caret,
    selectionEnd: caret,
    setSelectionRange(start, end) {
      textarea.selectionStart = start;
      textarea.selectionEnd = end;
      calls.push('select');
    },
    focus() {
      calls.push('focus');
    },
    addEventListener(type, handler) {
      listeners.push([type, handler]);
    },
    dispatchEvent(event) {
      calls.push('dispatch:' + event.type);
      events.push({
        type: event.type,
        bubbles: event.bubbles,
        value: textarea.value,
        selectionStart: textarea.selectionStart,
        selectionEnd: textarea.selectionEnd,
      });
      for (const [type, handler] of listeners) {
        if (type === event.type) handler(event);
      }
      return true;
    },
  };
  return textarea;
}
const elements = {};
const document = {
  readyState: 'complete',
  addEventListener() {},
  getElementById(id) {
    return Object.prototype.hasOwnProperty.call(elements, id) ? elements[id] : null;
  },
};
const window = {};
"""


def _insert_functions() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    return "\n".join(
        [
            _extract_function(source, "buildMarkdownCodeFence"),
            _extract_function(source, "insertCodeBlockIntoFeedbackTextarea"),
        ]
    )


def _insert_script(case_js: str) -> str:
    return "\n".join(
        [
            _INSERT_PRELUDE,
            _insert_functions(),
            "(async () => {",
            case_js,
            "})().catch((err) => { console.error(err && err.stack ? err.stack : err); process.exit(1); });",
        ]
    )


def _run_insert_case(value: str, caret: int, text: str) -> dict:
    script = _insert_script(
        f"""
        const textarea = makeTextarea({json.dumps(value)}, {caret});
        elements['feedback-text'] = textarea;
        insertCodeBlockIntoFeedbackTextarea({json.dumps(text)});
        process.stdout.write(JSON.stringify({{
          calls,
          events,
          value: textarea.value,
          caret: textarea.selectionStart,
        }}));
        """
    )
    return json.loads(_run_node(script))


# ``(box before, caret, pasted text, box after)``: the block needs a newline in
# front when the caret follows other text on its line, and one behind it when
# text follows the caret on its line.
_INSERT_CASES = (
    ("", 0, "x = 1", "```\nx = 1\n```\n"),
    ("abc", 3, "x = 1", "abc\n```\nx = 1\n```\n"),
    ("abc\n", 4, "x = 1", "abc\n```\nx = 1\n```\n"),
    ("abcd", 2, "x = 1", "ab\n```\nx = 1\n```\n\ncd"),
    ("ab\ncd", 2, "x = 1", "ab\n```\nx = 1\n```\n\ncd"),
    ("ab\ncd", 3, "x = 1\n", "ab\n```\nx = 1\n```\n\ncd"),
    ("abc", 3, "a ``` b", "abc\n````\na ``` b\n````\n"),
)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_code_insert_dispatches_one_bubbling_input_with_the_final_state() -> None:
    for value, caret, text, expected_value in _INSERT_CASES:
        outcome = _run_insert_case(value, caret, text)
        assert outcome["value"] == expected_value, (value, caret, text)
        # The listeners read the box when the event fires, so value and
        # caret must already be final at that moment.
        assert outcome["events"] == [
            {
                "type": "input",
                "bubbles": True,
                "value": expected_value,
                "selectionStart": outcome["caret"],
                "selectionEnd": outcome["caret"],
            }
        ], (value, caret, text)
        assert outcome["caret"] == len(expected_value) - len(value[caret:]), (
            value,
            caret,
            text,
        )
        assert outcome["calls"] == ["select", "focus", "dispatch:input"], (
            value,
            caret,
            text,
        )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_blank_text_or_missing_box_changes_and_dispatches_nothing() -> None:
    for blank in ("", "   ", "\n\t \r\n"):
        outcome = _run_insert_case("keep me", 7, blank)
        assert outcome["value"] == "keep me", repr(blank)
        assert outcome["events"] == [], repr(blank)
        assert outcome["calls"] == [], repr(blank)

    script = _insert_script(
        """
        insertCodeBlockIntoFeedbackTextarea('x = 1');
        process.stdout.write(JSON.stringify({ calls, events }));
        """
    )
    assert json.loads(_run_node(script)) == {"calls": [], "events": []}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_counter_follows_a_code_insert_through_the_real_counter_module() -> None:
    counter_source = COUNTER_JS.read_text(encoding="utf-8")
    script = _insert_script(
        f"""
        const counter = {{
          hidden: true,
          textContent: '',
          classList: {{ remove() {{}}, add() {{}} }},
        }};
        const textarea = makeTextarea('abc', 3);
        elements['feedback-text'] = textarea;
        elements['feedback-char-counter'] = counter;

        // Load the shipped counter module against this DOM.
        new Function('window', 'document', {json.dumps(counter_source)})(window, document);

        const shown = () => ({{ hidden: counter.hidden, text: counter.textContent }});
        const before = shown();

        // Probe validity: the counter only listens to ``input``, so a bare
        // assignment (what the browser does too) must leave it stale.
        textarea.value = 'abcdef';
        const afterSilentWrite = shown();
        textarea.value = 'abc';

        insertCodeBlockIntoFeedbackTextarea('x = 1');
        process.stdout.write(JSON.stringify({{
          before,
          afterSilentWrite,
          afterInsert: shown(),
          length: textarea.value.length,
        }}));
        """
    )
    outcome = json.loads(_run_node(script))
    assert outcome["before"] == {"hidden": False, "text": "3 chars"}
    assert outcome["afterSilentWrite"] == outcome["before"]
    assert outcome["length"] == 18
    assert outcome["afterInsert"] == {"hidden": False, "text": "18 chars"}


_SUBMIT_COUNTER_PRELUDE = """
        const counterSeen = [];
        const inputEvents = [];
        globalThis.refreshFeedbackCharCounter = function refreshFeedbackCharCounter() {
          counterSeen.push(elements['feedback-text'].value);
        };
        function makeRecordingTextarea(value) {
          return {
            value,
            dispatchEvent(event) {
              inputEvents.push(event.type);
              return true;
            },
          };
        }
"""


def _submit_counter_script(body: str) -> str:
    return _submit_harness(_SUBMIT_COUNTER_PRELUDE + body)


_SUBMIT_COMMON = """
        const submitButton = makeSubmitButton('Submit', false);
        window.activeTaskId = 'task-a';
        currentCheckboxes = [];
        elements['submit-btn'] = submitButton;
        elements['options-container'] = makeOptionsContainer(currentCheckboxes);
"""


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_submit_success_refreshes_the_counter_once_after_the_clear() -> None:
    script = _submit_counter_script(
        _SUBMIT_COMMON
        + """
        const textarea = makeRecordingTextarea('answer that was just sent');
        elements['feedback-text'] = textarea;
        fetchWithTimeout = async function fetchWithTimeout(url) {
          fetchCalls.push(url);
          return { ok: true, json: async () => ({ message: 'submitted' }) };
        };

        await submitFeedback();

        process.stdout.write(JSON.stringify({
          fetchCalls,
          counterSeen,
          inputEvents,
          text: textarea.value,
          statuses,
        }));
        """
    )
    outcome = json.loads(_run_node(script))
    assert outcome["fetchCalls"] == ["/api/tasks/task-a/submit"]
    assert outcome["statuses"] == [{"message": "submitted", "type": "success"}]
    assert outcome["text"] == ""
    # Exactly one refresh, and it saw the already-cleared box.
    assert outcome["counterSeen"] == [""]
    # No synthetic ``input``: it would stamp the typing marker and could hold
    # the next task's countdown although nobody typed.
    assert outcome["inputEvents"] == []


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_submit_success_for_another_task_leaves_the_counter_alone() -> None:
    script = _submit_counter_script(
        _SUBMIT_COMMON
        + """
        const taskATextarea = makeRecordingTextarea('answer for task a');
        const taskBTextarea = makeRecordingTextarea('task b draft');
        elements['feedback-text'] = taskATextarea;
        fetchWithTimeout = async function fetchWithTimeout(url) {
          fetchCalls.push(url);
          window.activeTaskId = 'task-b';
          elements['feedback-text'] = taskBTextarea;
          return { ok: true, json: async () => ({ message: 'submitted' }) };
        };

        await submitFeedback();

        process.stdout.write(JSON.stringify({
          fetchCalls,
          statuses,
          counterSeen,
          inputEvents,
          taskBText: taskBTextarea.value,
        }));
        """
    )
    outcome = json.loads(_run_node(script))
    # Probe validity: the submit really succeeded for task a while b was shown.
    assert outcome["fetchCalls"] == ["/api/tasks/task-a/submit"]
    assert outcome["statuses"] == [{"message": "submitted", "type": "success"}]
    assert outcome["counterSeen"] == []
    assert outcome["inputEvents"] == []
    assert outcome["taskBText"] == "task b draft"


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_failed_submit_keeps_the_text_and_the_counter_alone() -> None:
    script = _submit_counter_script(
        _SUBMIT_COMMON
        + """
        const textarea = makeRecordingTextarea('answer that must survive');
        elements['feedback-text'] = textarea;
        fetchWithTimeout = async function fetchWithTimeout(url) {
          fetchCalls.push(url);
          return {
            ok: false,
            status: 500,
            json: async () => ({ message: 'boom' }),
          };
        };

        await submitFeedback();

        process.stdout.write(JSON.stringify({
          fetchCalls,
          statuses,
          counterSeen,
          inputEvents,
          text: textarea.value,
        }));
        """
    )
    outcome = json.loads(_run_node(script))
    # Probe validity: the request went out and was reported as a failure.
    assert outcome["fetchCalls"] == ["/api/tasks/task-a/submit"]
    assert [status["type"] for status in outcome["statuses"]] == ["error"]
    assert outcome["counterSeen"] == []
    assert outcome["inputEvents"] == []
    assert outcome["text"] == "answer that must survive"


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_submit_success_without_the_counter_helper_still_completes() -> None:
    # ``refreshFeedbackCharCounter`` lives in multi_task.js; app.js must not
    # assume it is loaded (the R452 harnesses load app.js on its own).
    script = _submit_harness(
        _SUBMIT_COMMON
        + """
        const textarea = { value: 'answer' };
        elements['feedback-text'] = textarea;
        fetchWithTimeout = async function fetchWithTimeout() {
          return { ok: true, json: async () => ({ message: 'submitted' }) };
        };

        await submitFeedback();

        process.stdout.write(JSON.stringify({
          statuses,
          text: textarea.value,
          helperType: typeof refreshFeedbackCharCounter,
        }));
        """
    )
    outcome = json.loads(_run_node(script))
    assert outcome["helperType"] == "undefined"
    assert outcome["statuses"] == [{"message": "submitted", "type": "success"}]
    assert outcome["text"] == ""
