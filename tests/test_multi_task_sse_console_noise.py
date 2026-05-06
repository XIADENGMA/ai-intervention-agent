"""Web UI SSE 正常路径不应污染浏览器控制台。"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = REPO_ROOT / "static" / "js" / "multi_task.js"


def _read_source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _extract_connect_sse(source: str) -> str:
    match = re.search(
        r"function _connectSSE\(\) \{(?P<body>.*?)\n\}\n\nfunction _disconnectSSE",
        source,
        re.DOTALL,
    )
    assert match is not None, (
        "multi_task.js 必须保留 _connectSSE 到 _disconnectSSE 的结构"
    )
    return match.group("body")


def _extract_debug_log(source: str) -> str:
    match = re.search(
        r"function _debugLog\(\) \{(?P<body>.*?)\n\}\n\nif \(typeof window\.taskDeadlines",
        source,
        re.DOTALL,
    )
    assert match is not None, "multi_task.js 必须保留 _debugLog helper"
    return match.group("body")


def test_sse_normal_state_logs_are_debug_gated() -> None:
    source = _read_source()
    assert "function _debugLog()" in source
    sse_body = _extract_connect_sse(source)

    assert "SSE connected; polling degraded to safety-net mode" in sse_body
    assert "SSE disconnected; falling back to short-interval polling" in sse_body
    assert "SSE task_changed:" in sse_body

    assert "console.log(" not in sse_body
    assert "console.debug(" not in sse_body
    assert "console.warn(" not in sse_body
    assert sse_body.count("_debugLog(") >= 3


def test_debug_log_handles_missing_console_without_reference_error() -> None:
    debug_body = _extract_debug_log(_read_source())
    assert "typeof console === 'undefined'" in debug_body
    assert "!console" not in debug_body
    assert "typeof console.debug !== 'function'" in debug_body
