"""协议版本 / Capabilities / ServerClock 定义。

此模块是前后端契约的单一事实来源：

* ``PROTOCOL_VERSION`` 使用语义化版本；只有发生破坏性变更（移除字段、
  修改字段含义、更改错误码语义等）时才 bump major。新增向后兼容字段
  仅 bump minor。
* ``get_capabilities()`` 返回服务器当前声明的 feature flags，前端在连接
  早期 fetch 本端点后据此决定是否启用某个 UI 入口，以及是否需要兼容
  模式。
* ``get_server_clock()`` 返回服务器实时时钟与单调时钟，用于客户端时间
  对齐（避免客户端 ``Date.now()`` 与服务端 ``time.time()`` 漂移导致 TTL
  或动画时间错乱）。

设计决策：

* 本模块只依赖标准库，避免 web_ui / server 的循环导入。
* ``get_capabilities()`` 接收 ``server_version`` 作参数而非直接读取
  ``pyproject.toml``，将 IO 职责留给调用方（便于在测试中 mock）。
* ``features`` 字段以布尔标志为主；复杂嵌套结构会随版本膨胀而难以
  演进。真正复杂的探测（例如 SSE 当前是否连通）留给专门的健康检查
  端点。
"""

from __future__ import annotations

import time
from typing import Any

PROTOCOL_VERSION: str = "1.0.0"
"""前后端通信协议的语义化版本。

语义约定：
- major：破坏性变更（老客户端将无法正确解析新响应）
- minor：向后兼容的新增字段 / 功能
- patch：纯文档 / 注释修正，字段结构不变

客户端策略：读到的 major 高于自己已知 major 时应提示升级而非静默
兼容，以避免『看似正常但字段错位』的 silent failure。
"""


def get_capabilities(
    server_version: str,
    build_id: str | None = None,
    *,
    extra_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回服务器当前声明的能力集合。

    Parameters
    ----------
    server_version: str
        服务器自身的发布版本（通常来自 ``pyproject.toml`` / ``package.json``）。
        用于区分同一协议版本下的不同 server build，便于问题排查。
    build_id: str | None
        可选的构建标识（如 git short SHA），回退为空字符串。便于客户端
        上报问题时携带精确的服务端版本。
    extra_features: dict[str, Any] | None
        可选的额外功能开关字典，会被浅合并到返回结果的 ``features`` 字段。
        用于测试注入，或将来某些功能按部署环境动态开关。

    Returns
    -------
    dict[str, Any]
        形如::

            {
                "protocol_version": "1.0.0",
                "server_version": "1.5.18",
                "build_id": "d629a36",
                "features": {
                    "sse": True,
                    "polling": True,
                    "multi_task": True,
                    "capabilities_endpoint": True,
                    "clock": True,
                },
            }

        字段均为基础类型，保证可直接被 ``jsonify`` / ``json.dumps`` 序列化。

    Notes
    -----
    返回的是『声明』而非运行时探测结果；SSE / 推送等功能的可用性仍需
    运行时进一步验证。如果未来需要动态关闭某个 feature，仍可通过
    ``extra_features`` 在运行时覆盖。
    """
    features: dict[str, Any] = {
        "sse": True,
        "polling": True,
        "multi_task": True,
        "capabilities_endpoint": True,
        "clock": True,
    }
    if extra_features:
        features.update(extra_features)

    return {
        "protocol_version": PROTOCOL_VERSION,
        "server_version": server_version or "unknown",
        "build_id": build_id or "",
        "features": features,
    }


def get_server_clock() -> dict[str, int]:
    """返回服务器当前时间戳（毫秒）与单调时钟（毫秒）。

    客户端用法::

        // 客户端：
        const t0 = Date.now();
        const { time_ms, monotonic_ms } = await fetch('/api/time').then(r => r.json());
        const rtt = Date.now() - t0;
        const offset_ms = time_ms - t0 - rtt / 2;  // 粗略对齐
        // 之后 serverTime ≈ Date.now() + offset_ms

    Returns
    -------
    dict[str, int]
        ``{"time_ms": ..., "monotonic_ms": ...}``

    Notes
    -----
    * ``time_ms`` 是 wall clock（epoch 毫秒），可能因 NTP 跳变而非单调
    * ``monotonic_ms`` 来自 ``time.monotonic()``，适合做事件 ID / 超时
      计时等对单调性敏感的场景
    * 两个字段都是整数，避免浮点精度在前后端跨越时丢失
    """
    return {
        "time_ms": int(time.time() * 1000),
        "monotonic_ms": int(time.monotonic() * 1000),
    }


__all__ = [
    "PROTOCOL_VERSION",
    "get_capabilities",
    "get_server_clock",
]
