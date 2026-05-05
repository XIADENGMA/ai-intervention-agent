"""TaskQueue 全局单例访问器（与 server.py 解耦的轻量入口）。

设计动机（R20.8 性能优化）：
============================

`get_task_queue()` 仅由 Web UI 子进程使用——MCP 主进程从不调用它。
但历史上该函数定义在 ``server.py`` 中，于是 ``web_ui.py`` 通过
``from server import get_task_queue`` 触发整条 ``fastmcp`` / ``mcp`` /
``loguru`` 依赖链加载，给 Web UI 子进程平添约 310 ms 启动延迟，
而这 310 ms 全部白费——子进程根本不需要任何 MCP server 能力。

把单例逻辑抽到本模块后：

* Web UI 子进程仅加载 ``task_queue`` + ``threading`` + ``pathlib``，
  ``import web_ui`` 时间从 ~470 ms 降至 ~155 ms；
* ``server.py`` 通过 re-export 保留公开 API ``server.get_task_queue``
  与 ``server._shutdown_global_task_queue``，外部调用者无感知；
* MCP 主进程行为不变——若不调用 ``get_task_queue()``，绝不会创建
  ``TaskQueue`` 实例，也不会启动后台清理线程。

线程安全：
========

采用经典「双重检查锁定（Double-Checked Locking）」模式，确保即使
多个线程并发调用 ``get_task_queue()``，也只创建一个 ``TaskQueue``
实例。Python 的 GIL 保证 ``is None`` 判断与赋值的原子性，``Lock``
则消除两个线程同时通过外层 ``is None`` 检查后重复创建的窗口。

进程退出清理：
============

``_shutdown_global_task_queue`` 通过 ``atexit.register`` 注册，
进程退出时尽力停止后台清理线程；任何异常都被吞掉——退出阶段不
适合再抛错。幂等：未创建 TaskQueue 时为 no-op；多次调用安全。
"""

from __future__ import annotations

__all__ = [
    "_global_task_queue",
    "_global_task_queue_lock",
    "_shutdown_global_task_queue",
    "get_task_queue",
]

import atexit
import threading
from pathlib import Path

from task_queue import TaskQueue

# TaskQueue 仅由 Web UI 子进程使用（web_ui.py / web_ui_routes 会调用 get_task_queue()）。
# MCP 服务器主进程中此函数从未被调用，因此不会创建 TaskQueue 实例或后台清理线程。
# 采用懒加载 + 双重检查锁定，确保线程安全且无不必要的资源消耗。
_global_task_queue: TaskQueue | None = None
_global_task_queue_lock = threading.Lock()


def get_task_queue() -> TaskQueue:
    """获取全局任务队列实例

    返回:
        TaskQueue: 全局任务队列实例
    """
    global _global_task_queue
    if _global_task_queue is None:
        with _global_task_queue_lock:
            if _global_task_queue is None:
                persist_path = str(
                    Path(__file__).resolve().parent / "data" / "tasks.json"
                )
                _global_task_queue = TaskQueue(max_tasks=10, persist_path=persist_path)
    assert _global_task_queue is not None
    return _global_task_queue


def _shutdown_global_task_queue() -> None:
    """进程退出时尽量停止 TaskQueue 后台线程（幂等）。"""
    try:
        if _global_task_queue is not None:
            _global_task_queue.stop_cleanup()
    except Exception:
        # 退出阶段不再抛异常
        pass


atexit.register(_shutdown_global_task_queue)
