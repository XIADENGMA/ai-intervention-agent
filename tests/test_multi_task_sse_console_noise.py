"""Web UI SSE 正常路径不应污染浏览器控制台。"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _read_source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _extract_connect_sse(source: str) -> str:
    # R452 split the public _connectSSE wrapper from the direct EventSource
    # connector so BroadcastChannel followers can share one stream. Console-noise
    # assertions belong to the direct connector where EventSource handlers live.
    match = re.search(
        r"function _connectDirectSSE\(sharedLeaderMode\) \{(?P<body>.*?)\n\}\n\nfunction _sseNowMs",
        source,
        re.DOTALL,
    )
    assert match is not None, (
        "multi_task.js 必须保留 _connectDirectSSE 到 _sseNowMs 的结构"
    )
    return match.group("body")


def _extract_debug_log(source: str) -> str:
    match = re.search(
        r"function _debugLog\(\) \{(?P<body>.*?)\n\}\n\nfunction _debugSseTaskChanged",
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
    assert "SSE task_changed:" in source
    assert "_debugSseTaskChanged(" in sse_body

    assert "console.log(" not in sse_body
    assert "console.debug(" not in sse_body
    assert "console.warn(" not in sse_body
    assert sse_body.count("_debugLog(") >= 3


def test_debug_log_handles_missing_console_without_reference_error() -> None:
    source = _read_source()
    debug_body = _extract_debug_log(source)
    debug_enabled_body = re.search(
        r"function _debugLogEnabled\(\) \{(?P<body>.*?)\n\}\n\nfunction _debugLog",
        source,
        re.DOTALL,
    )
    assert debug_enabled_body is not None, "multi_task.js 必须保留 _debugLogEnabled"
    combined_debug_body = debug_enabled_body.group("body") + debug_body
    # 同时接受单/双引号字面量：测试锁住 typeof guard 语义，而不是引号风格。
    # Prettier 默认 singleQuote=false 会把字面量整体改成双引号，重写文件时
    # 这条不应假阴。
    assert re.search(r"typeof console !== ['\"]undefined['\"]", combined_debug_body), (
        "missing typeof console === 'undefined'/\"undefined\" guard"
    )
    assert "!console" not in combined_debug_body
    assert re.search(
        r"typeof console\.debug === ['\"]function['\"]", combined_debug_body
    ), "missing typeof console.debug !== 'function'/\"function\" guard"
