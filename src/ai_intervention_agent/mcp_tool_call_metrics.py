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
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

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


# ---------------------------------------------------------------------------
# R190 / latency histogram state（Cycle 5 / CR#19 foundational）
# ---------------------------------------------------------------------------
#
# 设计目标：暴露 ``aiia_mcp_tool_call_duration_seconds`` Prometheus
# histogram，让监控仪表板能画出「P95 工具调用耗时随时间漂移」、告警
# 「P99 > 30s 持续 5 分钟」等 SLO 类指标。R187 的纯 counter 只能算
# success rate（成功率），算不了延迟分布——这是 CR#18 §4.1 / §4.2 / §4.6
# 已经标注的「foundational gap」。
#
# 数据形态：
#   _latency_state[(tool_name, status)] = {
#       "count": int,           # 观测次数
#       "sum_seconds": float,   # 累计耗时（Prom histogram _sum）
#       "buckets": {0.1: int, 0.5: int, ..., math.inf: int},  # cumulative
#   }
#
# 注意 ``buckets`` 是 **cumulative**（Prom histogram 约定）：``buckets[1.0]``
# 表示「耗时 ≤ 1.0s 的观测数」，包含所有 ≤ 0.5s / ≤ 0.1s 的样本。最后一
# 个 bucket 是 ``+Inf``，必然 == count。
#
# 桶选择哲学：本项目场景是「人机交互 feedback 循环」——
#   * < 0.5s：localhost / 高速 LAN PWA 内部即时反馈（罕见，"用户秒回"）；
#   * 0.5-5s：典型「读完问题→点选项」窗口；
#   * 5-30s：人写一段反馈文字；
#   * 30-120s：人去查文档 / 试代码再回来；
#   * 120-600s：长任务（multi-round 调研）；
#   * > 600s：分钟级以上等待，往往是触发 ``auto_resubmit_timeout`` 边界。
#
# 不用 prometheus_client 库的 ``Histogram``：项目自己有
# ``_format_prom_metric_family`` 的极简渲染器（R187），引入 prometheus_client
# 只为 histogram 显得过重，而且要解决 multiprocess collector 问题（web_ui
# 子进程不能共享 prometheus_client 的进程级 _Counter）。手写一份本地实现
# 反而干净——所有状态在父进程，子进程不写 histogram。
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

_latency_state: dict[tuple[str, str], dict[str, Any]] = {}
"""每个 ``(tool_name, status)`` 一份独立的 histogram 状态。读写均需持
``_counter_lock``——为避免双锁死锁，本模块复用 counter 锁。"""


def reset_mcp_tool_call_stats() -> None:
    """清零所有累计计数 **和** latency histogram（仅供测试 / 运维 reset 使用）。

    生产路径**不应**调用此函数——计数器在 server 整个生命周期内累计，
    重启即归零。测试 / 调试时为了 isolation 才需要显式 reset。

    R190 起本函数同时清空 ``_latency_state``——避免「counter reset 了
    但 histogram 还残留上次测试数据」的状态污染。
    """
    with _counter_lock:
        _counter.clear()
        _latency_state.clear()


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


def _record_latency(tool_name: str, status: str, duration_seconds: float) -> None:
    """内部 helper：把一次工具调用的耗时写入 histogram。

    调用约定：必须**在已持锁**或**线程独占**条件下被调用。本函数自身
    不重新拿 ``_counter_lock`` ——middleware 在 success/failure 分支里
    已经拿了锁同时写 counter，再嵌套锁会增加死锁面。

    边界处理：
    - ``duration_seconds`` < 0（``time.monotonic()`` 退化，仅理论上）→
      静默丢弃，避免污染 sum；
    - ``status`` 不是 ``success`` / ``failure`` → 静默接受（让未来加
      ``timeout`` / ``rate_limited`` 等档不需要回头改本函数）；
    - bucket 比较用 ``<=``（Prom histogram 标准约定，``le="..."``）。
    """
    if duration_seconds < 0:
        return

    key = (tool_name, status)
    state = _latency_state.get(key)
    if state is None:
        # ty 0.0.34: dict literal 字面量推导会把 value type union 化
        # （int | float | dict[float, int]），导致下面 ``state["count"] += 1``
        # 落到 ty 认为不能 += 的分支。``cast`` 把 state 强制窄化回模块声明
        # 的 ``dict[str, Any]`` 类型——这跟 ``_latency_state`` value type 一
        # 致，是 type-safe narrow，不是 silent ignore。
        state = cast(
            "dict[str, Any]",
            {
                "count": 0,
                "sum_seconds": 0.0,
                "buckets": dict.fromkeys(_DEFAULT_LATENCY_BUCKETS, 0),
            },
        )
        _latency_state[key] = state

    state["count"] += 1
    state["sum_seconds"] += duration_seconds
    # cumulative bucket 写法：所有 ``upper >= duration`` 的 bucket 都 +1
    for upper in _DEFAULT_LATENCY_BUCKETS:
        if duration_seconds <= upper:
            state["buckets"][upper] += 1


def get_mcp_tool_call_latency_snapshot() -> dict[tuple[str, str], dict[str, Any]]:
    """返回 latency histogram 状态深 copy。

    返回形态：

    .. code-block:: python

        {
            ("interactive_feedback", "success"): {
                "count": 42,
                "sum_seconds": 187.4,
                "buckets": {0.1: 1, 0.5: 5, 1.0: 12, ..., float("inf"): 42},
            },
            ...
        }

    关键性质：

    - 返回字典是新建的，调用者修改不会污染内部状态；
    - ``buckets`` 字典自带 ``float("inf")`` 这个键，值 == ``count``（因为
      所有观测必然 ≤ +Inf）——caller 直接 emit ``le="+Inf"`` bucket 即可；
    - 若某 ``(tool, status)`` 还从未被记录，**不会**出现在返回字典里。
    """
    with _counter_lock:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for key, state in _latency_state.items():
            buckets_copy = dict(state["buckets"])
            buckets_copy[float("inf")] = state["count"]
            result[key] = {
                "count": state["count"],
                "sum_seconds": state["sum_seconds"],
                "buckets": buckets_copy,
            }
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
    ) -> CallToolResult:  # ty: ignore[invalid-method-override]
        # 上一行 ignore 原因: fastmcp ``Middleware.on_call_tool`` 父类签名
        # ``context: MiddlewareContext`` 不带 Generic 参数, 子类把它窄
        # 化到 ``MiddlewareContext[CallToolRequestParams]`` 是 fastmcp
        # 推荐的 type-narrow pattern (让 IDE hover ``context.message.name``
        # 拿到 ``str`` 而不是 ``Any``). ty 0.0.34 把这种 covariant
        # parameter override 标为 invalid override; 待 ty 支持 generic
        # parameter narrowing 后即可移除 (跟踪: astral-sh/ty issues).
        # ``context.message.name`` 是 tool 名（如 ``"interactive_feedback"``）；
        # FastMCP 已经做过基础 schema 校验，到这里 name 一定是 str 非空。
        tool_name = context.message.name
        # R190：用 ``time.monotonic()``（不是 ``time.time()``）测耗时，避
        # 免系统时钟跳变（NTP / 夏令时）让 latency 出现负值。
        start = time.monotonic()
        try:
            result = await call_next(context)
        except Exception:
            # failure 计数 + 把异常透传给外层 ErrorHandlingMiddleware，
            # 由它转 MCP 标准错误码。本中间件**不吞**异常。
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
