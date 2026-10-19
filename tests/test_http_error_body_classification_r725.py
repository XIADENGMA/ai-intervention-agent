"""R725 invariant: a failed request is classified by its status code, whatever its body is.

``submitFeedback`` (app.js) and ``closeTask`` (multi_task.js) used to call
``response.json()`` before looking at ``response.ok``. The pages that carry the
status codes worth telling the user about are not JSON: Flask's ``abort(403)``
answers with an HTML page, and a reverse proxy answers 502/503/504 with its own
HTML (or nothing). ``json()`` threw ``SyntaxError`` on all of them, so the user
read "Server returned an invalid response" and the 401/403/5xx messages from
``_classifyHttpResponse`` (R294) were unreachable for exactly the responses they
exist for.

The functions are extracted from the shipped files and run in Node with a
response whose ``json()`` is a real ``JSON.parse`` (so an HTML body raises the
same ``SyntaxError`` a browser raises).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
MULTI_TASK_JS = STATIC_JS / "multi_task.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

FLASK_403_PAGE = (
    "<!doctype html>\n<html lang=en>\n<title>403 Forbidden</title>\n"
    "<h1>Forbidden</h1>\n<p>You don&#39;t have the permission to access the "
    "requested resource.</p>\n"
)
PROXY_PAGE = "<html><body><h1>Bad Gateway</h1></body></html>"

# (id, status, body, submit message, close message)
FAILURES = [
    (
        "403-flask-html",
        403,
        FLASK_403_PAGE,
        "status.unauthorized",
        "status.unauthorized",
    ),
    ("401-empty", 401, "", "status.unauthorized", "status.unauthorized"),
    (
        "401-json",
        401,
        json.dumps({"success": False, "error": "nope"}),
        "status.unauthorized",
        "status.unauthorized",
    ),
    ("502-proxy-html", 502, PROXY_PAGE, "status.badGateway", "status.badGateway"),
    (
        "503-plain-text",
        503,
        "Service Unavailable",
        "status.serviceOverloaded",
        "status.serviceOverloaded",
    ),
    (
        "504-proxy-html",
        504,
        PROXY_PAGE,
        "status.gatewayTimeout",
        "status.gatewayTimeout",
    ),
    (
        "500-html",
        500,
        PROXY_PAGE,
        "status.serviceUnavailable",
        "status.serviceUnavailable",
    ),
    (
        "413-html-unclassified",
        413,
        PROXY_PAGE,
        "status.submitFailed",
        "status.closeFailed",
    ),
    (
        "400-json-message-kept",
        400,
        json.dumps({"success": False, "message": "bad thing", "error": "bad thing"}),
        "bad thing",
        "bad thing",
    ),
    (
        "200-html-is-still-an-error",
        200,
        PROXY_PAGE,
        "status.serverResponseInvalid",
        "status.serverResponseInvalid",
    ),
]
FAILURE_IDS = [case[0] for case in FAILURES]


def _extract_function(source: str, name: str, *, async_function: bool = False) -> str:
    marker = f"{'async ' if async_function else ''}function {name}("
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
    raise AssertionError(f"Could not extract {name}()")


def _run_node(script: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


def _classifiers_source() -> str:
    app = APP_JS.read_text(encoding="utf-8")
    return "\n".join(
        [
            _extract_function(app, "_classifyFetchError"),
            _extract_function(app, "_classifyHttpResponse"),
        ]
    )


RESPONSE_FACTORY = """
function makeResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => JSON.parse(body),
  };
}
"""


def _submit_script(status: int, body: str) -> str:
    app = APP_JS.read_text(encoding="utf-8")
    runtime = "\n".join(
        [
            _classifiers_source(),
            _extract_function(app, "isSubmitTargetStillCurrent"),
            _extract_function(app, "clearSubmittedTaskLocalState"),
            _extract_function(app, "submitFeedback", async_function=True),
        ]
    )
    return (
        textwrap.dedent(
            """
            const statuses = [];
            const refreshCalls = [];
            let clearAllImagesCalls = 0;
            let selectedImages = [];
            let taskTextareaContents = { 'task-a': 'cached draft' };
            let taskOptionsStates = {};
            let taskImages = {};
            let SUBMIT_BTN_ORIGINAL_HTML = null;
            const textarea = { value: 'my answer' };
            const button = { innerHTML: 'Submit', disabled: false };
            const elements = {
              'feedback-text': textarea,
              'submit-btn': button,
              'options-container': null,
            };
            const window = { activeTaskId: 'task-a', AIIA_I18N: { translateDOM() {} } };
            const document = {
              getElementById: (id) => (id in elements ? elements[id] : null),
              querySelectorAll: () => [],
            };
            const console = { debug() {}, error() {}, warn() {} };
            class FormData { append() {} }
            const config = {};
            function captureSubmitBtnOriginalHTML() {
              if (SUBMIT_BTN_ORIGINAL_HTML === null) SUBMIT_BTN_ORIGINAL_HTML = button.innerHTML;
            }
            function showStatus(message, type) { statuses.push({ message, type }); }
            function t(key) { return key; }
            function clearAllImages() { clearAllImagesCalls += 1; }
            async function refreshTasksList() { refreshCalls.push(window.activeTaskId); }
            function showNoContentPage() {}
            __RESPONSE_FACTORY__
            const fetchWithTimeout = async () => makeResponse(__STATUS__, __BODY__);

            __RUNTIME__

            (async () => {
              await submitFeedback();
              process.stdout.write(JSON.stringify({
                statuses,
                refreshCalls,
                textareaValue: textarea.value,
                draftKept: taskTextareaContents['task-a'],
                buttonDisabled: button.disabled,
                buttonHtml: button.innerHTML,
              }));
            })();
            """
        )
        .replace("__RESPONSE_FACTORY__", RESPONSE_FACTORY)
        .replace("__STATUS__", str(status))
        .replace("__BODY__", json.dumps(body))
        .replace("__RUNTIME__", runtime)
    )


def _close_task_script(status: int, body: str) -> str:
    return (
        textwrap.dedent(
            """
            const fs = require('fs');
            const vm = require('vm');
            const statuses = [];
            const renders = [];
            __RESPONSE_FACTORY__
            const sandbox = {
              Date, Error, JSON, Math, Number, Object, Promise, String, URL, URLSearchParams, Array,
              console: { debug() {}, error() {}, info() {}, log() {}, warn() {} },
              confirm() { return true; },
              document: {
                hidden: false,
                readyState: 'complete',
                addEventListener() {},
                createElement() {
                  return {
                    classList: { add() {}, remove() {}, toggle() {} },
                    appendChild(child) { return child; },
                    addEventListener() {},
                    querySelectorAll() { return []; },
                  };
                },
                getElementById() { return null; },
              },
              fetchWithTimeout: async () => makeResponse(__STATUS__, __BODY__),
              showStatus(message, type) { statuses.push({ message, type }); },
              setTimeout() { return 'timeout-id'; },
              clearTimeout() {},
              setInterval() { return 'interval-id'; },
              clearInterval() {},
              location: { href: 'http://127.0.0.1/', search: '', origin: 'http://127.0.0.1', pathname: '/' },
              addEventListener() {},
              removeEventListener() {},
              dispatchEvent() {},
              CustomEvent: function CustomEvent(type, init) { this.type = type; this.detail = init && init.detail; },
              currentTasks: [],
              activeTaskId: null,
              taskCountdowns: {},
              tasksPollingTimer: null,
              taskTextareaContents: {},
              taskOptionsStates: {},
              taskImages: {},
              pendingNewTaskCount: 0,
              newTaskHintTimer: null,
              tasksHealthCheckTimer: null,
              hasLoadedTaskSnapshot: true,
              serverTimeOffset: 0,
              taskDeadlines: {},
              feedbackPrompts: {},
              autoSubmitAttempted: {},
              selectedImages: [],
              AIIA_DEBUG: false,
              AIIA_I18N: { t: (key) => key },
            };
            sandbox.window = sandbox;
            sandbox.globalThis = sandbox;
            vm.createContext(sandbox);
            vm.runInContext(__CLASSIFIERS__ + '\\nwindow._classifyFetchError = _classifyFetchError;\\nwindow._classifyHttpResponse = _classifyHttpResponse;', sandbox);
            vm.runInContext(fs.readFileSync(__MULTI_TASK_JS__, 'utf8'), sandbox, { filename: 'multi_task.js' });
            sandbox.renderTaskTabs = () => { renders.push(1); };
            vm.runInContext(`
              window.currentTasks = [
                { task_id: 'keep-me', status: 'active' },
                { task_id: 'close-me', status: 'pending' },
              ];
              currentTasks = window.currentTasks;
              setActiveTaskId('keep-me');
              taskTextareaContents['close-me'] = 'draft';
            `, sandbox);

            (async () => {
              await sandbox.multiTaskModule.closeTask('close-me');
              const inside = JSON.parse(vm.runInContext(`JSON.stringify({
                taskIds: currentTasks.map((task) => task.task_id),
                draftKept: taskTextareaContents['close-me'] === undefined
                  ? null
                  : taskTextareaContents['close-me'],
              })`, sandbox));
              process.stdout.write(JSON.stringify({
                ...inside,
                statuses,
                renders: renders.length,
              }));
            })();
            """
        )
        .replace("__RESPONSE_FACTORY__", RESPONSE_FACTORY)
        .replace("__STATUS__", str(status))
        .replace("__BODY__", json.dumps(body))
        .replace("__CLASSIFIERS__", json.dumps(_classifiers_source()))
        .replace("__MULTI_TASK_JS__", json.dumps(str(MULTI_TASK_JS)))
    )


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [(c[1], c[2], c[3]) for c in FAILURES],
    ids=FAILURE_IDS,
)
def test_submit_failure_message_follows_the_status_not_the_body(
    status: int, body: str, expected: str
) -> None:
    result = _run_node(_submit_script(status, body))

    assert result["statuses"] == [{"message": expected, "type": "error"}]


@pytest.mark.parametrize(
    ("status", "body"),
    [(c[1], c[2]) for c in FAILURES],
    ids=FAILURE_IDS,
)
def test_submit_failure_keeps_the_users_input_and_frees_the_button(
    status: int, body: str
) -> None:
    result = _run_node(_submit_script(status, body))

    assert result["textareaValue"] == "my answer"
    assert result["draftKept"] == "cached draft"
    assert result["refreshCalls"] == []
    assert result["buttonDisabled"] is False
    assert result["buttonHtml"] == "Submit"


def test_submit_success_still_clears_the_form_and_refreshes() -> None:
    result = _run_node(
        _submit_script(200, json.dumps({"success": True, "message": "submitted"}))
    )

    assert result["statuses"] == [{"message": "submitted", "type": "success"}]
    assert result["textareaValue"] == ""
    assert result["refreshCalls"] == ["task-a"]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [(c[1], c[2], c[4]) for c in FAILURES],
    ids=FAILURE_IDS,
)
def test_close_task_failure_message_follows_the_status_not_the_body(
    status: int, body: str, expected: str
) -> None:
    result = _run_node(_close_task_script(status, body))

    assert result["statuses"] == [{"message": expected, "type": "error"}]


@pytest.mark.parametrize(
    ("status", "body"),
    [(c[1], c[2]) for c in FAILURES],
    ids=FAILURE_IDS,
)
def test_close_task_failure_leaves_the_task_in_place(status: int, body: str) -> None:
    result = _run_node(_close_task_script(status, body))

    assert result["taskIds"] == ["keep-me", "close-me"]
    assert result["renders"] == 0
    assert result["draftKept"] == "draft"


def test_close_task_success_still_removes_the_task() -> None:
    result = _run_node(_close_task_script(200, json.dumps({"success": True})))

    assert result["statuses"] == []
    assert result["taskIds"] == ["keep-me"]
    assert result["renders"] == 1
    assert result["draftKept"] is None
