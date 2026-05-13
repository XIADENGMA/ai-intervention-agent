"""R187 / T2 · MCP tool call counter middleware。

设计目标
========
R37 / R40 / R44 给 ``ai-intervention-agent`` 接齐了 FastMCP「生产四件套」
中间件链——``ErrorHandling`` / ``RateLimiting`` / ``Timing`` / ``Logging``。
其中 ``ErrorHandling`` 已经把 ``{error_type}:{method}`` 累计计数暴露在
``server.get_mcp_error_stats()`` 里，可用来诊断"最近哪一类异常最频繁"。

但还缺一道**正向计数**：每个 MCP tool 累计被调用多少次、其中多少次成功 /
失败。这道数据是 SLO（successful request rate）的分母，也是 R186 / T1
Prometheus ``/metrics`` 端点暴露 ``aiia_mcp_tool_calls_total`` 指标的源头。

为什么单独一个模块（不直接堆在 ``server.py``）
================================================
``server.py`` 已经 ~1600 行；继续堆 middleware 类定义 + 全局 state +
公共 helper 会让维护者难找入口。拆出独立模块的好处：

- **单一职责**：本模块只管「计数器 + middleware + 公共 helper」，没有
  其他副作用；
- **测试隔离**：测试 import 本模块时不需要先把整个 ``server.py`` 加载
  （省 ~250 ms cold start），也避免触发 ``mcp`` 实例初始化等连锁副作用；
- **R186 / T1 集成点单纯**：``web_ui_routes/system.py`` 的 prom 渲染器
  只 ``from .mcp_tool_call_metrics import get_mcp_tool_call_stats`` 一行
  即可拉到数据，不需要绕道 server 模块；
- **后续 T3 / T4 扩展面**：本模块的 module-level state 也可以为 T3
  日志级别动态调整、T4 API token 认证等运维端点提供"per-tool 历史" 数据。

线程安全
========
FastMCP 在 stdio transport 下走 ``asyncio`` 单线程事件循环，``on_call_tool``
钩子是 ``async`` 函数，理论上同一时刻只有一个协程在更新计数。但是：

- 未来若切到 ``streamable-http`` transport，FastMCP 会用线程池处理并发
  请求；
- ``get_mcp_tool_call_stats()`` 可能被 web_ui 子进程（**另一个进程**！）
  通过 ``server.py`` re-export 路径读取——虽然进程级隔离让 race
  不会污染数据，但**同一进程内** prom 渲染（线程 A）+ tool call（线程
  B）依然可能同时发生。

所以本模块用 ``threading.Lock`` 同步——``Counter`` 自身不是 thread-safe，
``dict.copy()`` 在 race 时可能 raise ``RuntimeError: dictionary changed
size during iteration``。锁粒度只护 read-modify-write，不护 caller 拿走
副本后的处理，避免长链锁。

错误归类约定
============
``on_call_tool`` 包 ``try/except`` 后：

- 正常 ``return`` → ``success`` 计数 +1；
- ``call_next`` raise（业务异常 / RateLimit / 参数校验） → ``failure``
  计数 +1，**异常被重新 raise**（不吞掉），交给外层
  ``ErrorHandlingMiddleware`` 转标准 MCP 错误码。

R120 silent-failure baseline：本模块**不引入** ``except: pass`` 站点
（重抛保证错误链路完整），不需要登记进 baseline。

PII 边界
========
- counter key 是 tool name（公开元数据），不是 arguments 字段值，不含
  PII；
- counter value 是 int（自然数），不含 PII；
- 通过 ``get_mcp_tool_call_stats()`` 返回的字典是深 copy，外部修改不会
  污染内部状态。
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastmcp.server.middleware import Middleware

if TYPE_CHECKING:
    from fastmcp.server.middleware import MiddlewareContext
    from mcp import types as mt
    from mcp.types import CallToolResult


# ---------------------------------------------------------------------------
# Module-level counter state
# ---------------------------------------------------------------------------

# ``Counter[(tool_name, status)]`` 而不是嵌套 dict——因为：
# 1. ``Counter`` 自带的 ``+=`` / ``update()`` API 更紧凑；
# 2. tuple key 让 ``get_stats()`` 拆解 + 重组成嵌套 dict 时不丢类型；
# 3. 后续若要加新 status（如 "timeout" / "rate_limited"）只是新增 key，
#    不需要修改数据结构形状。
_counter: Counter[tuple[str, str]] = Counter()
_counter_lock: threading.Lock = threading.Lock()


def reset_mcp_tool_call_stats() -> None:
    """清零所有累计计数（仅供测试 / 运维 reset 使用）。

    生产路径**不应**调用此函数——计数器在 server 整个生命周期内累计，
    重启即归零。测试 / 调试时为了 isolation 才需要显式 reset。
    """
    with _counter_lock:
        _counter.clear()


def get_mcp_tool_call_stats() -> dict[str, dict[str, int]]:
    """返回 ``{tool_name: {"success": int, "failure": int, "total": int}}``
    形式的累计计数快照。

    返回值是新建 dict，调用者修改不会污染内部状态。``total`` 字段是
    ``success + failure`` 的便捷投影——避免每个调用方各自再算一遍。

    若某 tool 还从未被调用，**不会**出现在返回字典里（避免 noise）。
    """
    with _counter_lock:
        snapshot = dict(_counter)

    result: dict[str, dict[str, int]] = {}
    for (tool_name, status), value in snapshot.items():
        result.setdefault(tool_name, {"success": 0, "failure": 0, "total": 0})
        if status == "success":
            result[tool_name]["success"] = value
        elif status == "failure":
            result[tool_name]["failure"] = value
        result[tool_name]["total"] += value
    return result


# ---------------------------------------------------------------------------
# FastMCP middleware
# ---------------------------------------------------------------------------


class ToolCallCounterMiddleware(Middleware):
    """累计 MCP tool 调用次数（success / failure 两档）。

    挂在 ``mcp.middleware`` 列表中位置 2（``RateLimiting`` 之后、
    ``DereferenceRefs`` / ``Timing`` / ``Logging`` 之前），所以：

    - 被 ``RateLimiting`` 拦截的请求**不会**计数（合理——这些请求实际
      没进入 tool handler，算作"系统拒绝"而不是"工具失败"）；
    - 业务异常（``ValueError`` / ``TimeoutError`` 等）会被本中间件标记
      为 ``failure``，然后由外层 ``ErrorHandling`` 包成标准 MCP 错误码
      返回给 client。
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: Callable[
            [MiddlewareContext[mt.CallToolRequestParams]], Awaitable[Any]
        ],
    ) -> CallToolResult:
        # ``context.message.name`` 是 tool 名（如 ``"interactive_feedback"``）；
        # FastMCP 已经做过基础 schema 校验，到这里 name 一定是 str 非空。
        tool_name = context.message.name
        try:
            result = await call_next(context)
        except Exception:
            # failure 计数 + 把异常透传给外层 ErrorHandlingMiddleware，
            # 由它转 MCP 标准错误码。本中间件**不吞**异常。
            with _counter_lock:
                _counter[(tool_name, "failure")] += 1
            raise
        else:
            with _counter_lock:
                _counter[(tool_name, "success")] += 1
            return result
