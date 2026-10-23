"""TaskQueue 全局单例访问器（与 server.py 解耦的轻量入口）。"""

from __future__ import annotations

__all__ = [
    "_global_task_queue",
    "_global_task_queue_lock",
    "_shutdown_global_task_queue",
    "bind_task_queue_to_port",
    "get_task_queue",
]

import atexit
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_intervention_agent.task_queue import TaskQueue


_global_task_queue: TaskQueue | None = None
_global_task_queue_lock = threading.Lock()
_bound_port: int | None = None


def _default_persist_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "tasks.json"


def _snapshot_path() -> Path:
    """快照文件路径；绑定了端口的 Web UI 用 ``tasks-<port>.json``（R836）。"""
    base = _default_persist_path()
    if _bound_port is None:
        return base
    return base.with_name(f"{base.stem}-{_bound_port}{base.suffix}")


def bind_task_queue_to_port(port: int) -> bool:
    """让任务快照以 Web UI 监听的端口命名（R836），必须在队列创建之前调用。

    同一个安装目录下可以同时跑多个 Web UI（不同配置、不同端口）；它们以前共用
    ``<package>/data/tasks.json``：后起的那个会把先起的那个还在等回复的任务恢复成自己的，
    之后各自覆盖对方的写入。按端口分文件后，同一个端口重启（R825）仍然找回自己的任务，
    别的端口看不到。

    返回 ``True`` 表示快照已经（或此前已经）绑定到 ``port``；端口不可用（不是 1..65535
    的整数）或队列已经按别的名字建好了则返回 ``False``，快照名字保持不变。
    """
    global _bound_port
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        return False
    with _global_task_queue_lock:
        if _global_task_queue is not None:
            return _bound_port == port
        _bound_port = port
        return True


def get_task_queue() -> TaskQueue:
    """获取全局任务队列实例"""
    global _global_task_queue
    if _global_task_queue is None:
        with _global_task_queue_lock:
            if _global_task_queue is None:
                from ai_intervention_agent.task_queue import TaskQueue

                _global_task_queue = TaskQueue(
                    max_tasks=10, persist_path=str(_snapshot_path())
                )
    assert _global_task_queue is not None
    return _global_task_queue


def _shutdown_global_task_queue() -> None:
    """进程退出时尽量停止 TaskQueue 后台线程（幂等）。"""
    try:
        if _global_task_queue is not None:
            _global_task_queue.stop_cleanup()
    except Exception:
        pass


atexit.register(_shutdown_global_task_queue)
