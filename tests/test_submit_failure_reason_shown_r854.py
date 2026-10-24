"""R854 invariant: an automatic submit that is refused says so; the panel says why.

Found while looking at what R851's 409 ("this task was already answered") looks like to
the person it is for. Two places let a refusal pass without a word:

* **Web UI, the countdown's automatic submit** (``multi_task.js::submitTaskFeedback``).
  The Submit button (``app.js::submitFeedback``) shows an error when the server refuses an
  answer, but nobody presses anything when a countdown ends: the answer was already given
  on another device (409), the task is gone (404), the proxy answered with a 502 page, the
  network dropped the request. All of them ended in a ``console.error`` and a page with a
  finished countdown and no explanation. It also read the body with ``response.json()``
  before looking at the status, so the HTML of a proxy's 502 ended as "invalid response"
  (R725 fixed that for the button, not for this path).
* **VS Code panel** (``webview-ui.js::submitWithData``). Every refusal read "Submit failed
  (HTTP 409)"; the sentence the server sends for 409 and 413 (``message``, in the language
  of the request) was thrown away.

Contract:

* The automatic submit shows what the Submit button shows, for the same response: the
  status first (401/403/5xx), then the server's own sentence, then the generic one; a
  request that failed before any answer came gets the message of its failure; nothing is
  shown when the server took the answer, and a failure of the page's own clean-up after
  that is not reported as a failed submit; the reporter never throws.
* The panel names the reason the server gives (a non-empty string ``message``, cut at 200
  characters); without one, the status code stays the message. The wait for that body is
  short, because a body that never comes must not hold the panel, and the timer is always
  released. A 429 keeps its rate-limit handling and never reads the body.

The Web UI half runs the shipped ``multi_task.js`` in the sandbox of the R452 harness with
the shipped classifiers from ``app.js``; the manual path is run with the R725 harness on
the same responses, so the two cannot drift. The panel half extracts the shipped functions
and constants from ``webview-ui.js``. Responses carry a real ``JSON.parse`` as ``json()``,
so an HTML body raises the error a browser raises.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import textwrap
from pathlib import Path
from typing import Any

import pytest

from tests.test_http_error_body_classification_r725 import (
    FLASK_403_PAGE,
    PROXY_PAGE,
    _extract_function,
    _run_node,
    _submit_script,
)
from tests.test_multi_task_poll_controller_lifecycle_r452 import _poll_harness

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"
PANEL_LOCALES = REPO_ROOT / "packages" / "vscode" / "locales"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

ALREADY = "This task was already answered; this answer was not sent"
TOO_LARGE = "The request is too large"

# (id, status, body, shown on the Web UI page, panel: ("reason", text) or ("status", n))
# A ``None`` page / panel entry means the case is not a refusal there.
Refusal = tuple[str, int, str, "str | None", "tuple[str, Any] | None"]
REFUSALS: list[Refusal] = [
    ("409-already-answered", 409, json.dumps({"success": False, "status": "error", "error": "task_already_answered", "message": ALREADY}), ALREADY, ("reason", ALREADY)),
    ("413-too-large", 413, json.dumps({"success": False, "status": "error", "error": "payload_too_large", "message": TOO_LARGE}), TOO_LARGE, ("reason", TOO_LARGE)),
    ("404-task-gone", 404, json.dumps({"success": False, "error": "任务不存在"}), "status.submitFailed", ("status", 404)),
    ("400-no-message", 400, json.dumps({"success": False, "error": "selected_options 必须是 JSON 数组"}), "status.submitFailed", ("status", 400)),
    ("500-json-without-message", 500, json.dumps({"success": False, "error": "服务器内部错误"}), "status.serviceUnavailable", ("status", 500)),
    ("503-json-with-message", 503, json.dumps({"success": False, "message": "upstream said no"}), "status.serviceOverloaded", ("reason", "upstream said no")),
    ("403-flask-html", 403, FLASK_403_PAGE, "status.unauthorized", ("status", 403)),
    ("401-empty", 401, "", "status.unauthorized", ("status", 401)),
    ("502-proxy-html", 502, PROXY_PAGE, "status.badGateway", ("status", 502)),
    ("503-plain-text", 503, "Service Unavailable", "status.serviceOverloaded", ("status", 503)),
    ("504-proxy-html", 504, PROXY_PAGE, "status.gatewayTimeout", ("status", 504)),
    ("409-html-from-a-proxy", 409, PROXY_PAGE, "status.submitFailed", ("status", 409)),
    ("409-message-is-not-text", 409, json.dumps({"success": False, "message": 5}), "status.submitFailed", ("status", 409)),
    ("409-json-null", 409, "null", "status.submitFailed", ("status", 409)),
    ("409-blank-message", 409, json.dumps({"success": False, "message": "   "}), None, ("status", 409)),
    ("409-message-at-the-limit", 409, json.dumps({"success": False, "message": "y" * 200}), None, ("reason", "y" * 200)),
    ("409-message-over-the-limit", 409, json.dumps({"success": False, "message": "y" * 201}), None, ("reason", "y" * 200 + "…")),
    ("409-long-message", 409, json.dumps({"success": False, "message": "x" * 500}), None, ("reason", "x" * 200 + "…")),
    ("409-message-with-padding", 409, json.dumps({"success": False, "message": "  " + ALREADY + " \n"}), None, ("reason", ALREADY)),
    ("200-html-is-an-error", 200, PROXY_PAGE, "status.serverResponseInvalid", None),
    ("200-says-no", 200, json.dumps({"success": False, "message": "refused"}), "refused", None),
]  # fmt: skip
PAGE_CASES = [case for case in REFUSALS if case[3] is not None]
PANEL_CASES = [case for case in REFUSALS if case[4] is not None]

# Responses the Submit button reads differently, on purpose or by accident; the automatic submit
# keeps its own rule for them, and the tests above pin it.
NOT_COMPARED_WITH_THE_BUTTON = {
    # the button reads a JSON ``null`` as the body and fails on ``null.message`` ("UI rendering
    # failed"); the automatic path counts a ``null`` body as no body
    "409-json-null",
    # the button takes any 2xx for a success; the automatic path goes by the ``success`` flag
    "200-says-no",
    # the button shows any truthy ``message`` (a 5 would be shown as "5"); the automatic path only
    # a string
    "409-message-is-not-text",
}
PARITY_CASES = [c for c in PAGE_CASES if c[0] not in NOT_COMPARED_WITH_THE_BUTTON]

# (id, how the request fails, shown on the Web UI page)
NETWORK_FAILURES = [
    ("fetch-failed", "new TypeError('Failed to fetch')", "status.networkOffline"),
    (
        "timed-out",
        "Object.assign(new Error('aborted'), { name: 'AbortError' })",
        "status.requestTimeout",
    ),
    ("something-else", "new Error('boom')", "status.networkError"),
]


def _const_lines(source: str, *names: str) -> str:
    lines = []
    for name in names:
        found = re.search(rf"^\s*const {name} = [^\n]+$", source, re.MULTILINE)
        assert found, f"{name} is not declared in webview-ui.js"
        lines.append(found.group(0).strip())
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Web UI: the countdown's automatic submit
# ---------------------------------------------------------------------------


def _web_prelude() -> str:
    app = APP_JS.read_text(encoding="utf-8")
    classifiers = "\n".join(
        f"globalThis.{name} = ({_extract_function(app, name)});"
        for name in ("_classifyFetchError", "_classifyHttpResponse")
    )
    return (
        textwrap.dedent(
            """
            FormData = class {
              constructor() { this.entries = []; }
              append(key, value) { this.entries.push([key, value]); }
            };
            selectedImages = [];
            const statuses = [];
            const complaints = [];
            console.error = (...args) => {
              const line = args.map(String).join(' ');
              if (line.startsWith('Could not show the submit failure')) complaints.push(line);
            };
            showStatus = (message, type) => { statuses.push({ message, type }); };
            t = (key) => key;
            requestFeedbackInputFocus = () => {};
            fetchFeedbackPromptsFresh = async () => ({ resubmit_prompt: 'RESUBMIT' });
            __CLASSIFIERS__
            function makeResponse(status, body) {
              return { ok: status >= 200 && status < 300, status, json: async () => JSON.parse(body) };
            }
            let next = null;
            fetchWithTimeout = async () => {
              if (next.error) throw next.error;
              return makeResponse(next.status, next.body);
            };
            """
        )
        .replace("__CLASSIFIERS__", classifiers)
        .lstrip("\n")
    )


def _run_web(case_js: str) -> Any:
    return _run_node(_poll_harness(_web_prelude() + textwrap.dedent(case_js)))


@functools.cache
def _web_outcomes() -> dict[str, Any]:
    cases = [{"id": c[0], "status": c[1], "body": c[2]} for c in PAGE_CASES]
    cases.append(
        {
            "id": "200-took-the-answer",
            "status": 200,
            "body": json.dumps({"success": True, "message": "ok"}),
        }
    )
    return _run_web(
        f"""
        const cases = {json.dumps(cases)};
        const out = {{}};
        for (const c of cases) {{
          statuses.length = 0;
          next = c;
          await submitTaskFeedback('t1', 'typed text', []);
          out[c.id] = statuses.slice();
        }}
        process.stdout.write(JSON.stringify(out));
        """
    )


@functools.cache
def _web_network_outcomes() -> dict[str, Any]:
    return _run_web(
        "const out = {};\n"
        + "\n".join(
            f"""
        statuses.length = 0;
        next = {{ error: {error} }};
        await submitTaskFeedback('t1', 'typed text', []);
        out[{how!r}] = statuses.slice();
        """
            for how, error, _expected in NETWORK_FAILURES
        )
        + "\nprocess.stdout.write(JSON.stringify(out));\n"
    )


@needs_node
class TestWebAutomaticSubmit:
    @pytest.mark.parametrize(
        ("case_id", "expected"),
        [(c[0], c[3]) for c in PAGE_CASES],
        ids=[c[0] for c in PAGE_CASES],
    )
    def test_a_refusal_is_shown_in_the_words_the_submit_button_uses(
        self, case_id: str, expected: str
    ) -> None:
        assert _web_outcomes()[case_id] == [{"message": expected, "type": "error"}]

    @pytest.mark.parametrize(
        ("case_id", "status", "body", "expected"),
        [(c[0], c[1], c[2], c[3]) for c in PARITY_CASES],
        ids=[c[0] for c in PARITY_CASES],
    )
    def test_the_submit_button_shows_the_same_for_the_same_response(
        self, case_id: str, status: int, body: str, expected: str
    ) -> None:
        manual = _run_node(_submit_script(status, body))["statuses"]
        assert manual == [{"message": expected, "type": "error"}], case_id
        assert _web_outcomes()[case_id] == manual

    def test_a_task_the_server_took_shows_nothing(self) -> None:
        assert _web_outcomes()["200-took-the-answer"] == []

    @pytest.mark.parametrize(
        ("how", "expected"),
        [(n[0], n[2]) for n in NETWORK_FAILURES],
        ids=[n[0] for n in NETWORK_FAILURES],
    )
    def test_a_request_that_fails_before_any_answer_names_its_failure(
        self, how: str, expected: str
    ) -> None:
        assert _web_network_outcomes()[how] == [{"message": expected, "type": "error"}]

    def test_a_failed_clean_up_after_the_server_took_the_answer_is_not_a_failed_submit(
        self,
    ) -> None:
        result = _run_web(
            """
            requestFeedbackInputFocus = () => { throw new Error('the page broke after the answer was taken'); };
            next = { status: 200, body: JSON.stringify({ success: true, message: 'ok' }) };
            await submitTaskFeedback('t1', 'typed text', []);
            process.stdout.write(JSON.stringify({ statuses }));
            """
        )
        assert result == {"statuses": []}

    def test_a_status_line_that_cannot_be_shown_does_not_break_the_submit(self) -> None:
        result = _run_web(
            """
            showStatus = () => { throw new Error('no status line'); };
            next = { status: 409, body: JSON.stringify({ success: false, message: 'already' }) };
            await submitTaskFeedback('t1', 'typed text', []);
            process.stdout.write(JSON.stringify({ survived: true, complaints }));
            """
        )
        assert result == {
            "survived": True,
            "complaints": ["Could not show the submit failure: Error: no status line"],
        }

    @pytest.mark.parametrize("missing", ["showStatus", "t"])
    def test_a_page_without_the_status_helpers_still_submits_quietly(
        self, missing: str
    ) -> None:
        result = _run_web(
            f"""
            {missing} = undefined;
            next = {{ status: 409, body: JSON.stringify({{ success: false, message: 'already' }}) }};
            await submitTaskFeedback('t1', 'typed text', []);
            process.stdout.write(JSON.stringify({{ statuses, complaints }}));
            """
        )
        assert result == {"statuses": [], "complaints": []}

    def test_without_the_classifiers_a_refusal_still_gets_a_message(self) -> None:
        result = _run_web(
            """
            _classifyHttpResponse = undefined;
            _classifyFetchError = undefined;
            next = { status: 502, body: '<html>Bad Gateway</html>' };
            await submitTaskFeedback('t1', 'typed text', []);
            const afterStatus = statuses.splice(0);
            next = { error: new TypeError('Failed to fetch') };
            await submitTaskFeedback('t1', 'typed text', []);
            process.stdout.write(JSON.stringify({ afterStatus, afterError: statuses }));
            """
        )
        assert result == {
            "afterStatus": [{"message": "status.submitFailed", "type": "error"}],
            "afterError": [{"message": "status.networkError", "type": "error"}],
        }

    def test_a_countdown_that_ends_on_a_task_answered_elsewhere_says_so(self) -> None:
        result = _run_web(
            f"""
            activeTaskId = 't1';
            window.currentTasks = [{{ task_id: 't1' }}];
            const typed = {{ value: 'my answer' }};
            document.getElementById = (id) => (id === 'feedback-text' ? typed : null);
            next = {{ status: 409, body: JSON.stringify({{ success: false, status: 'error', error: 'task_already_answered', message: {ALREADY!r} }}) }};
            await autoSubmitTask('t1');
            process.stdout.write(JSON.stringify({{ statuses, kept: typed.value }}));
            """
        )
        assert result == {
            "statuses": [{"message": ALREADY, "type": "error"}],
            "kept": "my answer",
        }


# ---------------------------------------------------------------------------
# VS Code panel: submitWithData
# ---------------------------------------------------------------------------


def _panel_source() -> str:
    source = WEBVIEW_UI_JS.read_text(encoding="utf-8")
    return "\n".join(
        (
            _const_lines(
                source,
                "SUBMIT_FAILURE_BODY_WAIT_MS",
                "SUBMIT_FAILURE_REASON_MAX_CHARS",
            ),
            _extract_function(source, "isSubmitTargetStillCurrent"),
            _extract_function(source, "finishSuccessfulSubmit"),
            _extract_function(source, "readSubmitFailureReason", async_function=True),
            _extract_function(source, "submitWithData", async_function=True),
        )
    )


PANEL_PRELUDE = """
const SERVER_URL = '';
const SUBMIT_TIMEOUT_MS = 20000;
const SUBMIT_BTN_SPINNER_HTML = '<span>Submitting</span>';
const SUBMIT_BTN_FALLBACK_HTML = '<span>Submit</span>';

const timers = [];
function setTimeout(fn, ms) {
  const timer = { fn, ms, cleared: false };
  timers.push(timer);
  return timer;
}
function clearTimeout(timer) {
  if (timer) timer.cleared = true;
}
class AbortController {
  constructor() { this.signal = { aborted: false }; }
  abort() { this.signal.aborted = true; }
}
class FormData {
  constructor() { this.entries = []; }
  append(key, value) { this.entries.push([key, String(value)]); }
}

const logs = [];
const toasts = [];
const calls = [];
const submitButton = { disabled: false, innerHTML: 'Submit', title: '' };
const textarea = { value: 'draft' };
const document = {
  getElementById(id) {
    if (id === 'submitBtn') return submitButton;
    if (id === 'feedbackText') return textarea;
    return null;
  },
  querySelectorAll() { return []; },
};
const vscode = { postMessage() {} };

let submitInFlight = false;
let submitBackoffUntilMs = 0;
let submitBackoffTimer = null;
let submitBtnDefaultHtml = 'Submit';
let currentConfig = null;
let activeTaskId = 'task-a';
let uploadedImages = [];
let taskTextareaContents = { 'task-a': 'draft' };
let taskOptionsStates = { 'task-a': ['A'] };
let taskImages = { 'task-a': ['image'] };

function stopCountdown() {}
function appendUploadedImagesToFormData() { return { appended: 0, dropped: 0 }; }
function renderUploadedImages() {}
function syncImagesToTaskCache() {}
function autoResizeFeedbackTextarea() {}
function showToast(message, options) { toasts.push({ message, options }); }
function t(key, params) { return params ? key + JSON.stringify(params) : key; }
function requestImmediateRefresh() {}
function log() {}
function logError(message) { logs.push(message); }
function applySubmitBackoffUi() {}

let queue = [];
function fetch(url) {
  calls.push(url);
  return Promise.resolve(queue.shift());
}
function makeResponse(status, body, extra) {
  return Object.assign(
    {
      ok: status >= 200 && status < 300,
      status,
      headers: { get() { return ''; } },
      json: async () => JSON.parse(body),
    },
    extra || {},
  );
}
"""


def _run_panel(case_js: str) -> Any:
    script = "\n".join(
        (
            PANEL_PRELUDE,
            _panel_source(),
            "(async () => {",
            textwrap.dedent(case_js),
            "})().catch((error) => {",
            "  console.error(error && error.stack ? error.stack : String(error));",
            "  process.exit(1);",
            "});",
        )
    )
    return _run_node(script)


@functools.cache
def _panel_outcomes() -> dict[str, Any]:
    cases = [{"id": c[0], "status": c[1], "body": c[2]} for c in PANEL_CASES]
    return _run_panel(
        f"""
        const cases = {json.dumps(cases)};
        const out = {{}};
        for (const c of cases) {{
          logs.length = 0;
          calls.length = 0;
          timers.length = 0;
          queue = [makeResponse(c.status, c.body)];
          // the route a task that is gone answers on; the panel then asks the old route, which refuses the same way
          if (c.status === 404) queue.push(makeResponse(c.status, c.body));
          const result = await submitWithData('Answer', ['A'], 'task-a');
          out[c.id] = {{
            result,
            logs: logs.slice(),
            calls: calls.slice(),
            draft: textarea.value,
            inFlight: submitInFlight,
            waitTimersLeftRunning: timers.filter((x) => x.ms === SUBMIT_FAILURE_BODY_WAIT_MS && !x.cleared).length,
          }};
        }}
        process.stdout.write(JSON.stringify(out));
        """
    )


def _expected_panel_log(how: tuple[str, Any]) -> str:
    kind, value = how
    if kind == "reason":
        return "ui.submit.failedReason" + json.dumps(
            {"reason": value}, ensure_ascii=False, separators=(",", ":")
        )
    return "ui.submit.failed" + json.dumps({"status": value}, separators=(",", ":"))


@needs_node
class TestPanelSubmit:
    @pytest.mark.parametrize(
        ("case_id", "how"),
        [(c[0], c[4]) for c in PANEL_CASES],
        ids=[c[0] for c in PANEL_CASES],
    )
    def test_the_message_names_the_reason_the_server_gives_or_else_the_status(
        self, case_id: str, how: tuple[str, Any]
    ) -> None:
        outcome = _panel_outcomes()[case_id]
        assert outcome["logs"] == [_expected_panel_log(how)]
        assert outcome["result"] is False

    @pytest.mark.parametrize(
        "case_id", [c[0] for c in PANEL_CASES], ids=[c[0] for c in PANEL_CASES]
    )
    def test_a_refused_submit_keeps_the_draft_and_frees_the_panel(
        self, case_id: str
    ) -> None:
        outcome = _panel_outcomes()[case_id]
        assert outcome["draft"] == "draft"
        assert outcome["inFlight"] is False

    @pytest.mark.parametrize(
        "case_id", [c[0] for c in PANEL_CASES], ids=[c[0] for c in PANEL_CASES]
    )
    def test_the_wait_for_the_body_is_never_left_running(self, case_id: str) -> None:
        assert _panel_outcomes()[case_id]["waitTimersLeftRunning"] == 0

    def test_a_task_the_server_cannot_find_is_asked_again_on_the_old_route(
        self,
    ) -> None:
        assert _panel_outcomes()["404-task-gone"]["calls"] == [
            "/api/tasks/task-a/submit",
            "/api/submit",
        ]

    def test_a_body_that_never_comes_does_not_hold_the_panel(self) -> None:
        result = _run_panel(
            """
            queue = [makeResponse(409, '', { json: () => new Promise(() => {}) })];
            const pending = submitWithData('Answer', ['A'], 'task-a');
            let settled = false;
            pending.then(() => { settled = true; });
            for (let i = 0; i < 30; i += 1) await Promise.resolve();
            const settledBeforeTheWaitEnds = settled;
            const wait = timers.find((x) => x.ms === SUBMIT_FAILURE_BODY_WAIT_MS);
            wait.fn();
            const outcome = await pending;
            process.stdout.write(JSON.stringify({
              settledBeforeTheWaitEnds,
              waitMs: wait.ms,
              outcome,
              logs,
              inFlight: submitInFlight,
              waitCleared: wait.cleared,
            }));
            """
        )
        assert result == {
            "settledBeforeTheWaitEnds": False,
            "waitMs": 1500,
            "outcome": False,
            "logs": ['ui.submit.failed{"status":409}'],
            "inFlight": False,
            "waitCleared": True,
        }

    def test_a_response_without_a_readable_body_says_the_status(self) -> None:
        result = _run_panel(
            """
            queue = [{ ok: false, status: 503, headers: { get() { return ''; } } }];
            const outcome = await submitWithData('Answer', ['A'], 'task-a');
            queue = [makeResponse(500, '', { json: () => { throw new Error('body already used'); } })];
            const second = await submitWithData('Answer', ['A'], 'task-a');
            const waitsBefore = timers.filter((x) => x.ms === SUBMIT_FAILURE_BODY_WAIT_MS).length;
            queue = [makeResponse(502, '', { json: () => Promise.reject(new Error('connection reset')) })];
            const third = await submitWithData('Answer', ['A'], 'task-a');
            const waitsAfter = timers.filter((x) => x.ms === SUBMIT_FAILURE_BODY_WAIT_MS);
            process.stdout.write(JSON.stringify({
              outcome, second, third, logs,
              waitsBefore,
              waitsAfter: waitsAfter.length,
              waitsLeftRunning: waitsAfter.filter((x) => !x.cleared).length,
            }));
            """
        )
        assert result == {
            "outcome": False,
            "second": False,
            "third": False,
            "logs": [
                'ui.submit.failed{"status":503}',
                'ui.submit.failed{"status":500}',
                'ui.submit.failed{"status":502}',
            ],
            # no body to read (or one that throws on the spot): no timer was started;
            # a body that fails later: the timer was started and released
            "waitsBefore": 0,
            "waitsAfter": 1,
            "waitsLeftRunning": 0,
        }

    def test_the_body_of_a_404_that_is_asked_again_is_not_read(self) -> None:
        result = _run_panel(
            """
            let reads = 0;
            queue = [
              makeResponse(404, '', { json: async () => { reads += 1; return { message: 'gone' }; } }),
              makeResponse(200, JSON.stringify({ success: true, message: 'ok' })),
            ];
            const outcome = await submitWithData('Answer', ['A'], 'task-a');
            process.stdout.write(JSON.stringify({
              outcome, reads, calls, logs,
              waits: timers.filter((x) => x.ms === SUBMIT_FAILURE_BODY_WAIT_MS).length,
            }));
            """
        )
        assert result == {
            "outcome": True,
            "reads": 0,
            "calls": ["/api/tasks/task-a/submit", "/api/submit"],
            "logs": [],
            "waits": 0,
        }

    def test_a_rate_limit_keeps_its_own_handling_and_never_reads_the_body(self) -> None:
        result = _run_panel(
            """
            let reads = 0;
            queue = [makeResponse(429, '', { json: async () => { reads += 1; return { message: 'slow down' }; } })];
            const outcome = await submitWithData('Answer', ['A'], 'task-a');
            process.stdout.write(JSON.stringify({
              outcome, reads, logs,
              toast: toasts.map((x) => x.message),
              backedOff: submitBackoffUntilMs > 0,
            }));
            """
        )
        assert result["outcome"] is False
        assert result["reads"] == 0
        assert result["logs"] == []
        assert result["toast"] == [
            'ui.submit.rateLimited429{"hint":"ui.submit.rateLimitHint{\\"seconds\\":15}"}'
        ]
        assert result["backedOff"] is True

    def test_an_answer_the_server_took_is_still_a_success(self) -> None:
        result = _run_panel(
            """
            queue = [makeResponse(200, JSON.stringify({ success: true, message: 'ok' }))];
            const outcome = await submitWithData('Answer', ['A'], 'task-a');
            process.stdout.write(JSON.stringify({ outcome, logs, draft: textarea.value }));
            """
        )
        assert result == {"outcome": True, "logs": [], "draft": ""}


@needs_node
class TestPanelHarness:
    def test_a_timer_runs_until_it_is_cleared(self) -> None:
        result = _run_panel(
            """
            const timer = setTimeout(() => {}, 5);
            const before = timer.cleared;
            clearTimeout(timer);
            process.stdout.write(JSON.stringify({ before, after: timer.cleared }));
            """
        )
        assert result == {"before": False, "after": True}


class TestPanelStrings:
    @pytest.mark.parametrize("lang", ["en", "zh-CN", "zh-TW"])
    def test_the_message_templates_carry_the_reason_and_the_status(
        self, lang: str
    ) -> None:
        submit = json.loads((PANEL_LOCALES / f"{lang}.json").read_text("utf-8"))["ui"][
            "submit"
        ]
        assert "{{reason}}" in submit["failedReason"]
        assert "{{status}}" not in submit["failedReason"]
        assert "{{status}}" in submit["failed"]
        assert "{{reason}}" not in submit["failed"]
