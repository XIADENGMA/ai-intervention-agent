"""Small read/write lock primitive shared by config and task queues.

This module deliberately has no project-local imports. ``task_queue`` is on the
Web UI cold-start path; importing ``config_manager`` just to get ``ReadWriteLock``
would also construct the global ConfigManager and load Pydantic config models.
Keeping the lock here preserves the same synchronization semantics without that
startup tax.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager


class ReadWriteLock:
    """多读者并发、写者独占，基于 Condition + RLock 实现。"""

    def __init__(self) -> None:
        """初始化读写锁。"""
        # RLock rationale (R330 contract): Condition.wait() 内部会 release
        # 然后 re-acquire 锁; 持锁的 reader 线程在 notify_all 后唤醒时需要
        # 重新 acquire (即同一线程 re-entry), 因此必须 RLock 而非 Lock。
        self._read_ready = threading.Condition(threading.RLock())
        self._readers = 0

    @contextmanager
    def read_lock(self) -> Generator[None, None, None]:
        """获取读锁（多读者并发，仅在写者持有锁时阻塞）。"""
        self._read_ready.acquire()
        try:
            self._readers += 1
        finally:
            self._read_ready.release()

        try:
            yield
        finally:
            self._read_ready.acquire()
            try:
                self._readers -= 1
                if self._readers == 0:
                    self._read_ready.notify_all()
            finally:
                self._read_ready.release()

    @contextmanager
    def write_lock(self) -> Generator[None, None, None]:
        """获取写锁（独占访问，等待所有读者退出）。"""
        self._read_ready.acquire()
        try:
            while self._readers > 0:
                self._read_ready.wait()
            yield
        finally:
            self._read_ready.release()
