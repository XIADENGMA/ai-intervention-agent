"""R187 / T2 · MCP tool call counter middleware。"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from fastmcp.server.middleware import Middleware

if TYPE_CHECKING:
    from fastmcp.server.middleware import MiddlewareContext
    from mcp import types as mt
    from mcp.types import CallToolResult


_counter: Counter[tuple[str, str]] = Counter()
_counter_lock: threading.Lock = threading.Lock()


# 设计目标：暴露 ``aiia_mcp_tool_call_duration_seconds`` Prometheus


_DEFAULT_LATENCY_BUCKETS: tuple[float, ...] = (
    0.1,
    0.5,
    1.0,
    5.0,
    30.0,
    120.0,
    300.0,
    600.0,
)
"""默认延迟桶（秒）。``+Inf`` 桶由 ``get_mcp_tool_call_latency_snapshot()``
自动追加，不在这个元组里——避免 caller 误以为 ``+Inf`` 是真实采样上限。"""

_DEFAULT_LATENCY_BUCKET_COUNTS = dict.fromkeys(_DEFAULT_LATENCY_BUCKETS, 0)
_MCP_LATENCY_INF_BUCKET = float("inf")

_latency_state: dict[tuple[str, str], dict[str, Any]] = {}
"""每个 ``(tool_name, status)`` 一份独立的 histogram 状态。读写均需持
``_counter_lock``——为避免双锁死锁，本模块复用 counter 锁。"""


def reset_mcp_tool_call_stats() -> None:
    """清零所有累计计数 **和** latency histogram（仅供测试 / 运维 reset 使用）。"""
    with _counter_lock:
        _counter.clear()
        _latency_state.clear()


def get_mcp_tool_call_stats() -> dict[str, dict[str, int]]:
    """返回 ``{tool_name: {"success": int, "failure": int, "total": int}}``
    形式的累计计数快照。"""
    with _counter_lock:
        snapshot = dict(_counter)

    result: dict[str, dict[str, int]] = {}
    for (tool_name, status), value in snapshot.items():
        tool_stats = result.get(tool_name)
        if tool_stats is None:
            tool_stats = {"success": 0, "failure": 0, "total": 0}
            result[tool_name] = tool_stats
        if status == "success":
            tool_stats["success"] = value
        elif status == "failure":
            tool_stats["failure"] = value
        tool_stats["total"] += value
    return result


def _record_latency(tool_name: str, status: str, duration_seconds: float) -> None:
    """内部 helper：把一次工具调用的耗时写入 histogram。"""
    if duration_seconds < 0:
        return

    key = (tool_name, status)
    state = _latency_state.get(key)
    if state is None:
        state = cast(
            "dict[str, Any]",
            {
                "count": 0,
                "sum_seconds": 0.0,
                "buckets": _DEFAULT_LATENCY_BUCKET_COUNTS.copy(),
            },
        )
        _latency_state[key] = state

    state["count"] += 1
    state["sum_seconds"] += duration_seconds

    for upper in _DEFAULT_LATENCY_BUCKETS:
        if duration_seconds <= upper:
            state["buckets"][upper] += 1


def get_mcp_tool_call_latency_snapshot() -> dict[tuple[str, str], dict[str, Any]]:
    """返回 latency histogram 状态深 copy。"""
    with _counter_lock:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for key, state in _latency_state.items():
            buckets_copy = state["buckets"].copy()
            buckets_copy[_MCP_LATENCY_INF_BUCKET] = state["count"]
            result[key] = {
                "count": state["count"],
                "sum_seconds": state["sum_seconds"],
                "buckets": buckets_copy,
            }
    return result


class ToolCallCounterMiddleware(Middleware):
    """累计 MCP tool 调用次数（success / failure 两档）。"""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: Callable[
            [MiddlewareContext[mt.CallToolRequestParams]], Awaitable[Any]
        ],
    ) -> CallToolResult:  # ty: ignore[invalid-method-override]
        tool_name = context.message.name

        start = time.monotonic()
        try:
            result = await call_next(context)
        except Exception:
            duration = time.monotonic() - start
            with _counter_lock:
                _counter[(tool_name, "failure")] += 1
                _record_latency(tool_name, "failure", duration)
            raise
        else:
            duration = time.monotonic() - start
            with _counter_lock:
                _counter[(tool_name, "success")] += 1
                _record_latency(tool_name, "success", duration)
            return result
