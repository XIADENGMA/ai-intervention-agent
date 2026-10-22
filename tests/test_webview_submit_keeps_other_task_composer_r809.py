"""R809: VS Code webview — a task's submit never touches another task's composer.

``packages/vscode/webview-ui.js`` shows one feedback form (textarea, images, option
check-boxes) and swaps its contents when the reviewer clicks another task's tab. Two
code paths still acted on "the form" as if it always belonged to the task they were
started for:

* ``submitWithData`` — after a successful submit it emptied the live form no matter
  which task was on screen. A slow upload (screenshots over a remote server) finishing
  while the reviewer had moved to task B and started typing wiped B's note, B's images
  and B's ticked options. The browser page has guarded this since R452
  (``isSubmitTargetStillCurrent``); the webview never got the guard.
* ``autoSubmit`` — a countdown that hit zero for task A while the reviewer had just
  clicked B's tab (activation pending) sent the *live* form — B's draft and B's
  images — as A's answer.

Real-Chrome evidence (scratch harness around the real webview-ui.js + Web UI server):
``B-DRAFT-…`` was stored as task A's ``user_input`` and, in the second scenario, B's
typed note and ticked option were emptied when A's slow submit finished.

The webview needs ``acquireVsCodeApi`` and a DOM, so these tests run the real function
sources (extracted from the file) in Node against small stand-ins for the surrounding
state, the same way the other ``test_vscode_webview_*`` guards do.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is required")


def _extract(source: str, marker: str) -> str:
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"could not extract {marker}")


def _functions() -> str:
    source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
    parts = [
        _extract(source, "async function autoSubmit("),
        _extract(source, "function collectTypedFeedbackForAutoSubmit("),
        _extract(source, "function collectSelectedOptionsForAutoSubmit("),
        _extract(source, "async function submitWithData("),
    ]
    if "function isSubmitTargetStillCurrent(" in source:
        parts.append(_extract(source, "function isSubmitTargetStillCurrent("))
    return "\n\n".join(parts)


_PRELUDE = r"""
const calls = [];
const requests = [];
let activeTaskId = __ACTIVE__;
let currentConfig = __CONFIG__;
let lastCountdownTaskId = __COUNTDOWN__;
let submitInFlight = false;
let submitBackoffUntilMs = 0;
let submitBtnDefaultHtml = '<b>Submit</b>';
let uploadedImages = __IMAGES__;
const autoSubmitAttempted = {};
const taskTextareaContents = __TEXTS__;
const taskOptionsStates = __OPTION_STATES__;
const taskImages = __TASK_IMAGES__;
const SERVER_URL = 'http://server.invalid';
const SUBMIT_TIMEOUT_MS = 5000;
const SUBMIT_BTN_SPINNER_HTML = '<i>spinner</i>';
const SUBMIT_BTN_FALLBACK_HTML = '<b>fallback</b>';

const textarea = { value: __TEXTAREA__ };
const submitBtn = { disabled: false, innerHTML: '', title: '' };
const optionItems = (__LIVE_OPTIONS__).map((checked, index) => {
  const box = { checked, id: 'option-' + index };
  const item = { selected: checked, classList: { remove(name) { if (name === 'selected') item.selected = false; } }, querySelector() { return box; } };
  item.box = box;
  return item;
});
const document = {
  getElementById(id) {
    if (id === 'feedbackText') return textarea;
    if (id === 'submitBtn') return submitBtn;
    const match = /^option-(\d+)$/.exec(id);
    if (match && optionItems[Number(match[1])]) return optionItems[Number(match[1])].box;
    return null;
  },
  querySelectorAll(selector) { return selector === '.option-item' ? optionItems : []; },
};
function t(key) { return key; }
function log() {}
function logError(message) { calls.push('logError:' + message); }
function showToast() {}
function stopCountdown() { calls.push('stopCountdown'); lastCountdownTaskId = null; }
function renderUploadedImages() { calls.push('renderUploadedImages'); }
function syncImagesToTaskCache(id) { calls.push('syncImages:' + id); }
function applySubmitBackoffUi() {}
function autoResizeFeedbackTextarea() { calls.push('autoResize'); }
function requestImmediateRefresh() {}
async function fetchFeedbackPrompts() { return { resubmit_prompt: 'resubmit-default' }; }
function appendUploadedImagesToFormData(formData) {
  uploadedImages.forEach((image, index) => formData.append('image_' + index, image.name));
  return { dropped: 0, appended: uploadedImages.length };
}
const vscode = { postMessage() {} };
globalThis.fetch = async (url, options) => {
  const body = {};
  if (options && options.body && typeof options.body.forEach === 'function') {
    options.body.forEach((value, key) => { body[key] = String(value); });
  }
  requests.push({ url: String(url), body });
  return { ok: true, status: 200, headers: { get() { return ''; } } };
};
"""


def _run(
    *,
    active: str | None,
    countdown: str | None = None,
    config: dict | None = None,
    textarea: str = "",
    images: list[dict] | None = None,
    live_options: list[bool] | None = None,
    texts: dict | None = None,
    option_states: dict | None = None,
    task_images: dict | None = None,
    body: str,
) -> dict:
    script = (
        _PRELUDE.replace("__ACTIVE__", json.dumps(active))
        .replace("__CONFIG__", json.dumps(config))
        .replace("__COUNTDOWN__", json.dumps(countdown))
        .replace("__IMAGES__", json.dumps(images or []))
        .replace("__TEXTS__", json.dumps(texts or {}))
        .replace("__OPTION_STATES__", json.dumps(option_states or {}))
        .replace("__TASK_IMAGES__", json.dumps(task_images or {}))
        .replace("__TEXTAREA__", json.dumps(textarea))
        .replace("__LIVE_OPTIONS__", json.dumps(live_options or []))
        + "\n"
        + _functions()
        + "\n(async () => {\n"
        + body
        + "\n})().then(() => { setTimeout(() => process.exit(0), 0); }).catch((error) => { console.error('HARNESS ERROR', error && error.stack || error); process.exit(1); });\n"
    )
    completed = subprocess.run(
        ["node", "-e", script], check=False, capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout.strip().splitlines()[-1])


_SNAPSHOT = r"""
console.log(JSON.stringify({
  textarea: textarea.value,
  uploadedImages: uploadedImages.map((image) => image.name),
  liveOptions: optionItems.map((item) => item.box.checked),
  liveSelectedClass: optionItems.map((item) => item.selected),
  calls,
  requests,
  savedTexts: Object.keys(taskTextareaContents),
  savedOptionStates: Object.keys(taskOptionsStates),
  savedImages: Object.keys(taskImages),
  attempted: Object.keys(autoSubmitAttempted),
  result: typeof RESULT === 'undefined' ? null : RESULT,
}));
"""

_TWO_TASKS: dict[str, Any] = {
    "texts": {"A": "A saved", "B": "B saved"},
    "option_states": {"A": {"0": True}, "B": {"1": True}},
    "task_images": {
        "A": [{"name": "a.png", "data": "data:image/png;base64,AA"}],
        "B": [{"name": "b.png", "data": "data:image/png;base64,BB"}],
    },
}


# --------------------------------------------------------------------------- submitWithData


def test_a_finished_submit_leaves_the_form_of_the_task_on_screen_alone() -> None:
    """A's slow submit completes while B is on screen: B's note/images/options stay."""
    state = _run(
        active="B",
        config={"task_id": "A", "predefined_options": ["a1", "a2"]},
        textarea="B note typed while A uploads",
        images=[{"name": "b.png", "data": "data:image/png;base64,BB"}],
        live_options=[False, True],
        body="const RESULT = await submitWithData('A answer', ['a1'], 'A');\n"
        + _SNAPSHOT,
        **_TWO_TASKS,
    )

    assert state["requests"][0]["url"].endswith("/api/tasks/A/submit")
    assert state["requests"][0]["body"]["feedback_text"] == "A answer"
    assert state["textarea"] == "B note typed while A uploads"
    assert state["uploadedImages"] == ["b.png"]
    assert state["liveOptions"] == [False, True]
    assert state["liveSelectedClass"] == [False, True]
    assert "renderUploadedImages" not in state["calls"]
    assert "autoResize" not in state["calls"]
    # what belongs to the submitted task is dropped, what belongs to the other one is kept
    assert state["savedTexts"] == ["B"]
    assert state["savedOptionStates"] == ["B"]
    assert state["savedImages"] == ["B"]
    assert state["result"] is True


def test_a_finished_submit_still_empties_the_form_of_its_own_task() -> None:
    state = _run(
        active="A",
        config={"task_id": "A", "predefined_options": ["a1", "a2"]},
        textarea="A answer",
        images=[{"name": "a.png", "data": "data:image/png;base64,AA"}],
        live_options=[True, False],
        body="const RESULT = await submitWithData('A answer', ['a1'], 'A');\n"
        + _SNAPSHOT,
        **_TWO_TASKS,
    )

    assert state["textarea"] == ""
    assert state["uploadedImages"] == []
    assert state["liveOptions"] == [False, False]
    assert state["liveSelectedClass"] == [False, False]
    assert "renderUploadedImages" in state["calls"]
    assert state["savedTexts"] == ["B"]
    assert state["savedOptionStates"] == ["B"]
    assert state["savedImages"] == ["B"]
    assert state["result"] is True


def test_a_finished_submit_without_any_task_id_empties_the_form() -> None:
    """Legacy single-task servers hand out no task id: the one form is the target."""
    state = _run(
        active=None,
        config=None,
        textarea="only answer",
        images=[{"name": "x.png", "data": "data:image/png;base64,XX"}],
        live_options=[True],
        body="const RESULT = await submitWithData('only answer', ['o'], null);\n"
        + _SNAPSHOT,
    )

    assert state["requests"][0]["url"].endswith("/api/submit")
    assert state["textarea"] == ""
    assert state["uploadedImages"] == []
    assert state["liveOptions"] == [False]
    assert state["result"] is True


def test_the_task_picked_by_the_poll_counts_as_on_screen() -> None:
    """Manual submit: no override, the rendered config names the task, the poll agrees."""
    state = _run(
        active="A",
        config={"task_id": "A", "predefined_options": ["a1"]},
        textarea="typed",
        live_options=[True],
        body="const RESULT = await submitWithData('typed', ['a1']);\n" + _SNAPSHOT,
        **_TWO_TASKS,
    )

    assert state["requests"][0]["url"].endswith("/api/tasks/A/submit")
    assert state["textarea"] == ""
    assert state["liveOptions"] == [False]


# --------------------------------------------------------------------------- autoSubmit


def test_a_countdown_for_a_task_that_left_the_screen_sends_nothing() -> None:
    """A's countdown hits zero right after B's tab was clicked: B's draft is not A's answer."""
    state = _run(
        active="B",
        countdown="A",
        config={"task_id": "A", "predefined_options": ["a1"]},
        textarea="B draft restored by the tab click",
        images=[{"name": "b.png", "data": "data:image/png;base64,BB"}],
        live_options=[True],
        body="await autoSubmit();\n" + _SNAPSHOT,
        **_TWO_TASKS,
    )

    assert state["requests"] == []
    assert "stopCountdown" in state["calls"]
    assert state["textarea"] == "B draft restored by the tab click"
    assert state["uploadedImages"] == ["b.png"]
    assert state["liveOptions"] == [True]
    # the retry throttle must not be consumed: when the reviewer returns to A it fires at once
    assert state["attempted"] == []


def test_a_countdown_for_the_task_on_screen_still_sends_what_was_typed() -> None:
    state = _run(
        active="A",
        countdown="A",
        config={"task_id": "A", "predefined_options": ["a1", "a2"]},
        textarea="typed for A",
        live_options=[False, True],
        body="await autoSubmit();\n" + _SNAPSHOT,
        **_TWO_TASKS,
    )

    assert len(state["requests"]) == 1
    request = state["requests"][0]
    assert request["url"].endswith("/api/tasks/A/submit")
    assert request["body"]["feedback_text"] == "typed for A"
    assert json.loads(request["body"]["selected_options"]) == ["a2"]
    assert state["attempted"] == ["A"]


def test_a_countdown_with_nothing_typed_still_sends_the_resubmit_prompt() -> None:
    state = _run(
        active="A",
        countdown="A",
        config={"task_id": "A", "predefined_options": []},
        textarea="",
        body="await autoSubmit();\n" + _SNAPSHOT,
    )

    assert len(state["requests"]) == 1
    assert state["requests"][0]["body"]["feedback_text"] == "resubmit-default"


def test_a_countdown_runs_when_the_page_does_not_know_an_active_task() -> None:
    """No active task id known (legacy / not yet reconciled): behave as before."""
    state = _run(
        active=None,
        countdown="A",
        config={"task_id": "A", "predefined_options": []},
        textarea="typed anyway",
        body="await autoSubmit();\n" + _SNAPSHOT,
    )

    assert len(state["requests"]) == 1
    assert state["requests"][0]["body"]["feedback_text"] == "typed anyway"
