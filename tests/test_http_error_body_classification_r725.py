"""R725 invariant: a failed request is classified by its status code, whatever its body is.

``submitFeedback`` (app.js) used to call ``response.json()`` before looking at
``response.ok``. The pages that carry the status codes worth telling the user
about are not JSON: Flask's ``abort(403)`` answers with an HTML page, and a
reverse proxy answers 502/503/504 with its own HTML (or nothing). ``json()``
threw ``SyntaxError`` on all of them, so the user read "Server returned an
invalid response" and the 401/403/5xx messages from ``_classifyHttpResponse``
(R294) were unreachable for exactly the responses they exist for.

The functions are extracted from the shipped file and run in Node with a
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

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node runtime unavailable"
)

FLASK_403_PAGE = (
    "<!doctype html>\n<html lang=en>\n<title>403 Forbidden</title>\n"
    "<h1>Forbidden</h1>\n<p>You don&#39;t have the permission to access the "
    "requested resource.</p>\n"
)
PROXY_PAGE = "<html><body><h1>Bad Gateway</h1></body></html>"

# (id, status, body, message shown)
FAILURES = [
    ("403-flask-html", 403, FLASK_403_PAGE, "status.unauthorized"),
    ("401-empty", 401, "", "status.unauthorized"),
    (
        "401-json",
        401,
        json.dumps({"success": False, "error": "nope"}),
        "status.unauthorized",
    ),
    ("502-proxy-html", 502, PROXY_PAGE, "status.badGateway"),
    ("503-plain-text", 503, "Service Unavailable", "status.serviceOverloaded"),
    ("504-proxy-html", 504, PROXY_PAGE, "status.gatewayTimeout"),
    ("500-html", 500, PROXY_PAGE, "status.serviceUnavailable"),
    ("413-html-unclassified", 413, PROXY_PAGE, "status.submitFailed"),
    (
        "400-json-message-kept",
        400,
        json.dumps({"success": False, "message": "bad thing", "error": "bad thing"}),
        "bad thing",
    ),
    ("200-html-is-still-an-error", 200, PROXY_PAGE, "status.serverResponseInvalid"),
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
            function hideInlineStatus() {}
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
