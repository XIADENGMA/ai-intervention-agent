"""协议版本 / Capabilities / ServerClock 定义。"""

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
    """返回服务器当前声明的能力集合。"""
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
    """返回服务器当前时间戳（毫秒）与单调时钟（毫秒）。"""
    return {
        "time_ms": int(time.time() * 1000),
        "monotonic_ms": int(time.monotonic() * 1000),
    }


__all__ = [
    "PROTOCOL_VERSION",
    "get_capabilities",
    "get_server_clock",
]
