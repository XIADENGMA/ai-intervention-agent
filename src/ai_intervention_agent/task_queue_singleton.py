"""TaskQueue 全局单例访问器（与 server.py 解耦的轻量入口）。"""

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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_intervention_agent.task_queue import TaskQueue


_global_task_queue: TaskQueue | None = None
_global_task_queue_lock = threading.Lock()


def get_task_queue() -> TaskQueue:
    """获取全局任务队列实例"""
    global _global_task_queue
    if _global_task_queue is None:
        with _global_task_queue_lock:
            if _global_task_queue is None:
                from ai_intervention_agent.task_queue import TaskQueue

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
        pass


atexit.register(_shutdown_global_task_queue)
