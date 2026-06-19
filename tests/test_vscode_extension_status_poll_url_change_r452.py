"""Regression coverage for VS Code host status polling across server URL changes."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_TS = REPO_ROOT / "packages" / "vscode" / "extension.ts"


def _source() -> str:
    return EXTENSION_TS.read_text(encoding="utf-8")


def _extract_function_body(source: str, name: str) -> str:
    match = re.search(
        rf"const\s+{re.escape(name)}\s*=\s*(?:async\s*)?\([^)]*\)\s*:\s*[^=]+=>\s*\{{",
        source,
    )
    assert match, f"Cannot find function body for {name}"
    start = match.end()
    depth = 1
    i = start
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:i]
        i += 1
    raise AssertionError(f"Unbalanced function body for {name}")


def _extract_config_change_handler(source: str) -> str:
    marker = "onDidChangeConfiguration((e) => {"
    start = source.find(marker)
    assert start >= 0, "Cannot find onDidChangeConfiguration handler"
    start = source.find("{", start) + 1
    depth = 1
    i = start
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:i]
        i += 1
    raise AssertionError("Unbalanced onDidChangeConfiguration handler")


def test_status_poll_uses_request_scoped_server_url() -> None:
    body = _extract_function_body(_source(), "updateStatusBar")

    assert "const requestServerUrl = serverUrl;" in body
    assert "serverUrl !== requestServerUrl" in body
    assert "fetch(`${requestServerUrl}/api/tasks`" in body
    assert "fetch(`${serverUrl}/api/tasks`" not in body


def test_status_poll_stale_guard_precedes_state_mutation() -> None:
    body = _extract_function_body(_source(), "updateStatusBar")

    stale_idx = body.index("if (isStaleStatusPoll())")
    mutate_idx = body.index("lastPollAtMs = Date.now();", stale_idx)
    assert stale_idx < mutate_idx

    catch_idx = body.index("catch (e: unknown)")
    catch_stale_idx = body.index("if (isStaleStatusPoll())", catch_idx)
    catch_mutate_idx = body.index("lastPollAtMs = Date.now();", catch_idx)
    assert catch_stale_idx < catch_mutate_idx


def test_status_poll_controller_aborted_on_config_change_and_cleanup() -> None:
    source = _source()
    abort_body = _extract_function_body(source, "abortStatusPollRequest")
    config_body = _extract_config_change_handler(source)

    assert "let statusPollAbortController: AbortController | null = null;" in source
    assert "statusPollAbortController.abort();" in abort_body
    assert "abortStatusPollRequest();" in config_body

    cleanup_idx = source.index("const cleanup = (): void => {")
    cleanup_body = source[
        cleanup_idx : source.index("deactivateHook = cleanup;", cleanup_idx)
    ]
    assert "statusPollDisposed = true;" in cleanup_body
    assert "abortStatusPollRequest();" in cleanup_body


def test_server_url_change_resets_sse_cursor_before_reconnect() -> None:
    config_body = _extract_config_change_handler(_source())

    reset_idx = config_body.index("_lastEventId = null;")
    reconnect_idx = config_body.index("_connectSSE();")
    assert reset_idx < reconnect_idx
