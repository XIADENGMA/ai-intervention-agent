"""任务队列管理 - 线程安全、状态管理、自动清理、延迟删除、持久化。

清理契约：后台守护线程每 5秒 检查一次，完成任务延迟 10秒 后删除
（避免前端轮询遇到 404）。
"""

import copy
import json
import logging
import os
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_intervention_agent.runtime_constants import (
    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
)
from ai_intervention_agent.rw_lock import ReadWriteLock
from ai_intervention_agent.task_constants import (
    LOOP_HISTORY_MAX_LOOPS,
    LOOP_HISTORY_MAX_ROUNDS,
    LOOP_ID_MAX_LENGTH,
    LOOP_LABEL_MAX_LENGTH,
    LOOP_TEXT_MAX_LENGTH,
    LOOP_VERDICT_MAX_LENGTH,
    PLACEHOLDER_MAX_LENGTH,
)

logger = logging.getLogger(__name__)


_PROMPT_WARN_BYTES: int = 6 * 1024 * 1024
"""``add_task`` 收到的 prompt（UTF-8 编码后字节数）超过此值时 ``logger.warning``。
不会拒绝，但日志里会留下 footprint 让运维看到 caller 的异常输入趋势。"""

_PROMPT_REJECT_BYTES: int = 10 * 1024 * 1024
"""``add_task`` 收到的 prompt 超过此值时直接 ``return False``，不进队列。
保护进程内存 + SSE history deque + 跨进程 IPC payload。"""

_COMPACT_JSON_SEPARATORS: tuple[str, str] = (",", ":")
"""Compact separators for machine-state JSON persisted on hot write paths."""


def _prompt_utf8_size_for_guard(prompt: str) -> int:
    """Return a prompt byte size suitable for the R53-A threshold guard."""
    char_count = len(prompt)
    if char_count * 4 <= _PROMPT_WARN_BYTES:
        return char_count
    if prompt.isascii():
        return char_count
    return len(prompt.encode("utf-8", errors="replace"))


HEADER_LABEL_MAX_LENGTH: int = 16
"""mining-cycle-3 §2.1 borrow #1 — header chip clamp。
源自 gemini-cli ``ask_user.header`` 设计（≤16 chars, "chip/tag" 显示）。
理由：chip 必须能在 multi-task pane 顶部窄横条内 fit；长 label
会折行或被截断，反而损害"快速识别领域"的本意。"""


def _normalize_optional_text(value: Any, max_length: int) -> str | None:
    """Loop engineering P1 — 可选自由文本字段的统一 normalize。"""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:max_length]


_LOCK_WATCHDOG_TIMEOUT_S: float = 30.0
"""单次 ``_watched_write_lock`` 的 acquire+hold 上限。超过这个时长 watchdog
扫到一次就 dump 全线程栈到 ``logger.error``。

30 s 是一个折中：实测 ``add_task`` 的临界区微秒级 → 任何 > 5 s 的 wait 都
肯定异常；但 CI 环境跑 pytest 时，sleep / IO 抖动可能超过 1 s，所以保留
一个相对宽松的窗口避免误报。运行时可由测试通过 monkeypatch 调小。"""

_LOCK_WATCHDOG_SCAN_INTERVAL_S: float = 5.0
"""watchdog 扫描周期。``_LOCK_WATCHDOG_TIMEOUT_S / _LOCK_WATCHDOG_SCAN_INTERVAL_S
≈ 6`` 意味着真出现 deadlock 时最快 5 s、最慢 35 s 就会有 dump 进入日志。"""

_pending_acquisitions: dict[int, dict[str, Any]] = {}
"""``rec_id -> {label, thread_id, start, dumped}``：当前正持有 / 等待
``_watched_write_lock`` 的所有 record。``rec_id`` 用 ``id(rec)``，
保证同一线程嵌套调用不会冲突（虽然 ``ReadWriteLock`` 已禁止嵌套）。"""

_pending_acquisitions_lock = threading.Lock()
"""保护 ``_pending_acquisitions`` 的细粒度 lock。作用域非常短（dict 增删），
不嵌入临界区，因此不会和 ``ReadWriteLock`` 形成新的 lock-order 风险。"""

_watchdog_thread: threading.Thread | None = None
_watchdog_started_lock = threading.Lock()


def _capture_all_thread_stacks() -> str:
    """采集进程内所有线程的当前调用栈，拼成可读字符串。"""
    try:
        frames = sys._current_frames()
    except Exception as exc:  # pragma: no cover — 防御性
        return f"<failed to capture stacks: {exc!r}>"
    chunks: list[str] = []
    for tid, frame in frames.items():
        chunks.append(f"\n--- Thread id={tid} ---\n")
        try:
            chunks.extend(traceback.format_stack(frame))
        except Exception as exc:  # pragma: no cover — 防御性
            chunks.append(f"<failed to format stack for tid={tid}: {exc!r}>\n")
    return "".join(chunks)


def _scan_pending_and_dump_slow() -> int:
    """单次扫描：把超时但尚未 dump 的 record 拣出来，dump 全栈到 logger.error。"""
    now = time.monotonic()
    slow_records: list[dict[str, Any]] = []
    with _pending_acquisitions_lock:
        for rec in _pending_acquisitions.values():
            if rec.get("dumped"):
                continue
            if now - rec["start"] > _LOCK_WATCHDOG_TIMEOUT_S:
                rec["dumped"] = True
                slow_records.append(rec.copy())
    if not slow_records:
        return 0
    stacks = _capture_all_thread_stacks()
    for rec in slow_records:
        logger.error(
            f"⚠️ TaskQueue 写锁卡死 > {_LOCK_WATCHDOG_TIMEOUT_S:.0f}s "
            f"(label={rec['label']}, "
            f"waiting_thread_id={rec['thread_id']}, "
            f"waited={(now - rec['start']):.1f}s)\n"
            f"全线程栈快照：\n{stacks}"
        )
    return len(slow_records)


_lock_watchdog_wake_event = threading.Event()
"""测试可通过 ``_lock_watchdog_wake_event.set()`` 把 daemon 从 sleep 里唤醒，
让它立刻执行下一轮 ``_scan_pending_and_dump_slow``。生产路径不会用到。"""


def _lock_watchdog_loop() -> None:
    """daemon 后台线程主循环：用 Event 而非裸 ``time.sleep``，方便测试唤醒。"""
    while True:
        try:
            woke = _lock_watchdog_wake_event.wait(_LOCK_WATCHDOG_SCAN_INTERVAL_S)
            if woke:
                _lock_watchdog_wake_event.clear()
            _scan_pending_and_dump_slow()
        except Exception as exc:
            logger.warning(f"Lock watchdog loop 异常（已吞）: {exc}", exc_info=True)


def _ensure_lock_watchdog_started() -> None:
    """懒启动：第一次有人 ``_watched_write_lock`` 才把 daemon 起来。"""
    global _watchdog_thread
    with _watchdog_started_lock:
        if _watchdog_thread is not None and _watchdog_thread.is_alive():
            return
        _watchdog_thread = threading.Thread(
            target=_lock_watchdog_loop,
            name="TaskQueueLockWatchdog",
            daemon=True,
        )
        _watchdog_thread.start()
        logger.debug("TaskQueueLockWatchdog daemon 已启动")


@contextmanager
def _watched_write_lock(
    rwlock: ReadWriteLock, label: str
) -> Generator[None, None, None]:
    """``rwlock.write_lock()`` 的 deadlock-aware 包装。"""
    _ensure_lock_watchdog_started()
    rec: dict[str, Any] = {
        "label": label,
        "thread_id": threading.get_ident(),
        "start": time.monotonic(),
        "dumped": False,
    }
    rec_id = id(rec)
    with _pending_acquisitions_lock:
        _pending_acquisitions[rec_id] = rec
    try:
        with rwlock.write_lock():
            yield
    finally:
        with _pending_acquisitions_lock:
            _pending_acquisitions.pop(rec_id, None)


class TaskStatus(StrEnum):
    """任务状态枚举（StrEnum 使其与纯字符串完全兼容）"""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    REMOVED = "removed"


class Task(BaseModel):
    """任务数据结构：task_id, prompt, options, status, result"""

    model_config = ConfigDict(validate_assignment=True)

    task_id: str
    prompt: str
    predefined_options: list[str] | None = None

    predefined_options_defaults: list[bool] | None = None
    auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT

    auto_resubmit_timeout_explicit: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at_monotonic: float = Field(default_factory=time.monotonic)
    status: str = TaskStatus.PENDING
    result: dict[str, Any] | None = None
    completed_at: datetime | None = None

    extends_used: int = 0

    feedback_placeholder: str | None = None

    header_label: str | None = None

    loop_id: str | None = None
    loop_objective: str | None = None
    loop_phase: str | None = None
    success_criteria: str | None = None
    iteration_label: str | None = None

    def get_remaining_time(self, now_monotonic: float | None = None) -> int:
        """计算剩余倒计时（使用单调时间）。"""
        if self.status == TaskStatus.COMPLETED:
            return 0

        if self.auto_resubmit_timeout <= 0:
            return 0

        now = time.monotonic() if now_monotonic is None else now_monotonic
        elapsed = now - self.created_at_monotonic
        remaining = self.auto_resubmit_timeout - elapsed

        return max(0, int(remaining))

    def get_deadline_monotonic(self) -> float:
        """获取截止时间的单调时间戳"""

        if self.auto_resubmit_timeout <= 0:
            return float("inf")
        return self.created_at_monotonic + self.auto_resubmit_timeout

    def is_expired(self) -> bool:
        """检查任务是否已超时"""
        if self.status == TaskStatus.COMPLETED:
            return False

        if self.auto_resubmit_timeout <= 0:
            return False
        return time.monotonic() > self.get_deadline_monotonic()

    def extend_deadline(
        self,
        seconds: int,
        *,
        max_extends: int,
        min_seconds: int,
        max_seconds: int,
    ) -> tuple[bool, str | None]:
        """feat-countdown-extend (§3.2): 用户主动延长 task 的 auto-resubmit
        倒计时。"""
        if self.status == TaskStatus.COMPLETED:
            return False, "task_completed"
        if self.auto_resubmit_timeout <= 0:
            return False, "auto_resubmit_disabled"
        if self.extends_used >= max_extends:
            return False, "extends_limit_reached"
        if not (min_seconds <= seconds <= max_seconds):
            return False, "invalid_seconds"

        self.auto_resubmit_timeout = self.auto_resubmit_timeout + seconds
        self.extends_used = self.extends_used + 1
        return True, None

    def freeze_deadline(self) -> tuple[bool, str | None]:
        """mining-6 Track A (cycle-5 §3.6 derivative): 用户主动把 task 的
        auto-resubmit 倒计时禁用，把 task 变成无 timeout 的"等用户回答"状态。"""
        if self.status == TaskStatus.COMPLETED:
            return False, "task_completed"
        if self.auto_resubmit_timeout <= 0:
            return False, "already_frozen"
        self.auto_resubmit_timeout = 0
        return True, None


class TaskQueue:
    """任务队列管理器（线程安全）。

    并发契约（R22.2）：`_lock` 为 ReadWriteLock——读读并发、读写互斥、
    写写互斥。禁止已持锁线程再次获取本锁（不支持递归/升级/降级）；
    写后副作用（_persist / _trigger_status_change）必须在锁外触发。
    """

    def __init__(self, max_tasks: int = 10, persist_path: str | None = None):
        """初始化任务队列"""
        self.max_tasks = max_tasks
        self._tasks: dict[str, Task] = {}

        self._lock = ReadWriteLock()
        self._active_task_id: str | None = None

        self._status_change_callbacks: list[Callable[[str, str | None, str], None]] = []
        self._callbacks_lock = Lock()

        self._last_hotpath_cleanup_monotonic: float = float("-inf")
        self._hotpath_cleanup_lock = Lock()

        self._loop_history: dict[str, dict[str, Any]] = {}

        self._persist_path: Path | None = Path(persist_path) if persist_path else None
        if self._persist_path:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._restore()

        self._stop_cleanup = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="TaskQueueCleanup"
        )
        self._cleanup_thread.start()

        logger.info(
            f"任务队列初始化完成，最大任务数: {max_tasks}，"
            f"持久化: {'启用 → ' + str(self._persist_path) if self._persist_path else '禁用'}，"
            f"后台清理线程已启动"
        )

    def clear_all_tasks(self) -> int:
        """清理所有任务（重置队列）"""
        with _watched_write_lock(self._lock, "clear_all_tasks"):
            count = len(self._tasks)
            had_loop_history = bool(self._loop_history)
            self._tasks.clear()
            self._loop_history.clear()
            self._active_task_id = None
            if count > 0:
                logger.info(f"清理了所有残留任务，共 {count} 个")

        if count > 0 or had_loop_history:
            self._persist()
        return count

    def add_task(
        self,
        task_id: str,
        prompt: str,
        predefined_options: list[str] | None = None,
        auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT,
        predefined_options_defaults: list[bool] | None = None,
        feedback_placeholder: str | None = None,
        header_label: str | None = None,
        auto_resubmit_timeout_explicit: bool = False,
        loop_id: str | None = None,
        loop_objective: str | None = None,
        loop_phase: str | None = None,
        success_criteria: str | None = None,
        iteration_label: str | None = None,
    ) -> bool:
        """添加任务，无活动任务时自动激活"""

        try:
            prompt_bytes = _prompt_utf8_size_for_guard(prompt)
        except Exception:
            prompt_bytes = 0
        if prompt_bytes > _PROMPT_REJECT_BYTES:
            logger.warning(
                f"add_task 拒绝 task_id={task_id}：prompt {prompt_bytes / 1024 / 1024:.1f} MB "
                f"超过硬上限 {_PROMPT_REJECT_BYTES / 1024 / 1024:.0f} MB（R53-A）"
            )
            return False
        if prompt_bytes > _PROMPT_WARN_BYTES:
            logger.warning(
                f"add_task 大 prompt 警告 task_id={task_id}："
                f"prompt {prompt_bytes / 1024 / 1024:.1f} MB 超过 warn 阈值 "
                f"{_PROMPT_WARN_BYTES / 1024 / 1024:.0f} MB（R53-A，未拒绝）"
            )

        new_status: str | None = None

        with _watched_write_lock(self._lock, "add_task"):
            if auto_resubmit_timeout <= 0:
                auto_resubmit_timeout = 0
            else:
                auto_resubmit_timeout = max(
                    AUTO_RESUBMIT_TIMEOUT_MIN,
                    min(auto_resubmit_timeout, AUTO_RESUBMIT_TIMEOUT_MAX),
                )

            if len(self._tasks) >= self.max_tasks:
                logger.warning(
                    f"任务队列已满({self.max_tasks})，无法添加新任务: {task_id}"
                )
                return False

            if task_id in self._tasks:
                logger.warning(f"任务ID已存在: {task_id}")
                return False

            normalized_placeholder: str | None = None
            if isinstance(feedback_placeholder, str):
                s = feedback_placeholder.strip()
                if s:
                    normalized_placeholder = s[:PLACEHOLDER_MAX_LENGTH]

            normalized_header_label: str | None = None
            if isinstance(header_label, str):
                s = header_label.strip()
                if s:
                    normalized_header_label = s[:HEADER_LABEL_MAX_LENGTH]

            task = Task(
                task_id=task_id,
                prompt=prompt,
                predefined_options=predefined_options,
                predefined_options_defaults=predefined_options_defaults,
                auto_resubmit_timeout=auto_resubmit_timeout,
                auto_resubmit_timeout_explicit=auto_resubmit_timeout_explicit,
                feedback_placeholder=normalized_placeholder,
                header_label=normalized_header_label,
                loop_id=_normalize_optional_text(loop_id, LOOP_ID_MAX_LENGTH),
                loop_objective=_normalize_optional_text(
                    loop_objective, LOOP_TEXT_MAX_LENGTH
                ),
                loop_phase=_normalize_optional_text(loop_phase, LOOP_LABEL_MAX_LENGTH),
                success_criteria=_normalize_optional_text(
                    success_criteria, LOOP_TEXT_MAX_LENGTH
                ),
                iteration_label=_normalize_optional_text(
                    iteration_label, LOOP_LABEL_MAX_LENGTH
                ),
            )

            self._tasks[task_id] = task

            if self._active_task_id is None:
                self._active_task_id = task_id
                task.status = TaskStatus.ACTIVE
            else:
                task.status = TaskStatus.PENDING

            logger.info(
                f"添加任务成功: {task_id}, 当前任务数: {len(self._tasks)}/{self.max_tasks}"
            )

            new_status = task.status

        if new_status is not None:
            self._trigger_status_change(task_id, None, new_status)
            self._persist()

        return True

    def get_task(self, task_id: str) -> Task | None:
        """获取指定任务"""
        with self._lock.read_lock():
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[Task]:
        """获取所有任务列表"""
        with self._lock.read_lock():
            return list(self._tasks.values())

    def get_first_incomplete_task(self) -> Task | None:
        """Return the first non-completed task in insertion order."""
        with self._lock.read_lock():
            for task in self._tasks.values():
                if task.status != TaskStatus.COMPLETED:
                    return task
            return None

    def has_tasks(self) -> bool:
        """Return whether the queue currently contains any task."""
        with self._lock.read_lock():
            return bool(self._tasks)

    def get_all_tasks_with_stats(self) -> tuple[list[Task], dict[str, int]]:
        """单次 read_lock 内同时拿 task list + stats，专门给 ``/api/tasks`` 用。

        R23.4：合并旧的 get_all_tasks() + get_task_count() 两次 read_lock，
        原子语义升级（list 与 stats 同一快照）。R521：list 与 counts 在同
        一次 values 循环内一趟构建。R522：状态计数直接分桶，不再二次遍历。
        """
        with self._lock.read_lock():
            if not self._tasks:
                return [], {
                    "total": 0,
                    "pending": 0,
                    "active": 0,
                    "completed": 0,
                    "max": self.max_tasks,
                }
            pending = active = completed = 0
            tasks_view: list[Task] = []
            for t in self._tasks.values():
                tasks_view.append(t)
                if t.status == TaskStatus.PENDING:
                    pending += 1
                elif t.status == TaskStatus.ACTIVE:
                    active += 1
                elif t.status == TaskStatus.COMPLETED:
                    completed += 1
            stats: dict[str, int] = {
                "total": len(tasks_view),
                "pending": pending,
                "active": active,
                "completed": completed,
                "max": self.max_tasks,
            }
            return tasks_view, stats

    def update_auto_resubmit_timeout_for_all(self, auto_resubmit_timeout: int) -> int:
        """更新所有未完成任务的 auto_resubmit_timeout"""
        if auto_resubmit_timeout <= 0:
            auto_resubmit_timeout = 0
        else:
            auto_resubmit_timeout = max(
                AUTO_RESUBMIT_TIMEOUT_MIN,
                min(auto_resubmit_timeout, AUTO_RESUBMIT_TIMEOUT_MAX),
            )

        updated = 0
        with _watched_write_lock(self._lock, "update_auto_resubmit_timeout_for_all"):
            for task in self._tasks.values():
                if task.status == TaskStatus.COMPLETED:
                    continue

                if task.auto_resubmit_timeout_explicit:
                    continue
                if task.auto_resubmit_timeout != auto_resubmit_timeout:
                    task.auto_resubmit_timeout = auto_resubmit_timeout
                    updated += 1

        if updated > 0:
            self._persist()
        return updated

    def get_active_task(self) -> Task | None:
        """获取当前活动任务"""
        with self._lock.read_lock():
            if self._active_task_id:
                return self._tasks.get(self._active_task_id)
            return None

    def extend_task_deadline(
        self,
        task_id: str,
        seconds: int,
        *,
        max_extends: int,
        min_seconds: int,
        max_seconds: int,
    ) -> tuple[bool, str | None, int, int]:
        """cr32 §3.1 fix：在写锁内执行 ``Task.extend_deadline`` 的读改写原语。"""
        with _watched_write_lock(self._lock, "extend_task_deadline"):
            task = self._tasks.get(task_id)
            if task is None:
                return False, "task_not_found", 0, 0
            success, error_code = task.extend_deadline(
                seconds,
                max_extends=max_extends,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
            )
            return (
                success,
                error_code,
                task.extends_used,
                task.auto_resubmit_timeout,
            )

    def freeze_task_deadline(
        self,
        task_id: str,
    ) -> tuple[bool, str | None, int]:
        """mining-6 Track A: 在写锁内调用 ``Task.freeze_deadline``。"""
        with _watched_write_lock(self._lock, "freeze_task_deadline"):
            task = self._tasks.get(task_id)
            if task is None:
                return False, "task_not_found", 0
            success, error_code = task.freeze_deadline()
            return (
                success,
                error_code,
                task.auto_resubmit_timeout,
            )

    def set_active_task(self, task_id: str) -> bool:
        """手动切换活动任务"""
        status_events: list[tuple[str, str | None, str]] = []
        with _watched_write_lock(self._lock, "set_active_task"):
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            new_task = self._tasks[task_id]
            if new_task.status == TaskStatus.COMPLETED:
                logger.warning(f"任务已完成，无法激活: {task_id}")
                return False

            if self._active_task_id == task_id and new_task.status == TaskStatus.ACTIVE:
                logger.debug(f"任务已经是 active 状态，跳过切换: {task_id}")
                return True

            old_active_id = self._active_task_id
            old_active_status = None

            if self._active_task_id and self._active_task_id in self._tasks:
                old_task = self._tasks[self._active_task_id]
                if old_task.status == TaskStatus.ACTIVE:
                    old_active_status = old_task.status
                    old_task.status = TaskStatus.PENDING

            new_task_old_status = new_task.status
            self._active_task_id = task_id
            new_task.status = TaskStatus.ACTIVE

            logger.info(f"切换到任务: {task_id}")

            if old_active_id and old_active_status:
                status_events.append(
                    (old_active_id, TaskStatus.ACTIVE, TaskStatus.PENDING)
                )
            status_events.append((task_id, new_task_old_status, TaskStatus.ACTIVE))

        for ev_task_id, ev_old_status, ev_new_status in status_events:
            self._trigger_status_change(ev_task_id, ev_old_status, ev_new_status)

        if status_events:
            self._persist()
        return True

    def complete_task(self, task_id: str, result: dict[str, Any]) -> bool:
        """完成任务并标记为延迟删除（核心方法）"""
        status_events: list[tuple[str, str | None, str]] = []
        with _watched_write_lock(self._lock, "complete_task"):
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            task = self._tasks[task_id]
            old_status = task.status
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = datetime.now(UTC)
            status_events.append((task_id, old_status, TaskStatus.COMPLETED))

            if task.loop_id and old_status != TaskStatus.COMPLETED:
                self._record_loop_round(task, result)

            if self._active_task_id == task_id:
                self._active_task_id = None
                logger.info(f"任务完成并清空激活任务: {task_id}")

                for tid, t in self._tasks.items():
                    if t.status == TaskStatus.PENDING:
                        self._active_task_id = tid
                        t.status = TaskStatus.ACTIVE
                        logger.info(f"自动激活下一个任务: {tid}")
                        status_events.append(
                            (tid, TaskStatus.PENDING, TaskStatus.ACTIVE)
                        )
                        break
            else:
                logger.info(f"任务完成: {task_id}")

            logger.info(f"任务 {task_id} 已标记为完成（将在 10 秒后自动清理）")

        for ev_task_id, ev_old_status, ev_new_status in status_events:
            self._trigger_status_change(ev_task_id, ev_old_status, ev_new_status)

        self._persist()
        return True

    def _record_loop_round(self, task: Task, result: dict[str, Any]) -> None:
        """把完成的 loop 成员任务压缩为台账轮次条目（调用方必须已持写锁）。"""
        loop_id = task.loop_id
        if not loop_id:
            return

        user_input = result.get("user_input") or result.get("feedback") or ""
        if not isinstance(user_input, str):
            user_input = str(user_input)
        selected = result.get("selected_options")
        if not isinstance(selected, list):
            selected = []
        images = result.get("images")
        image_count = len(images) if isinstance(images, list) else 0

        entry: dict[str, Any] = {
            "task_id": task.task_id,
            "iteration_label": task.iteration_label,
            "loop_phase": task.loop_phase,
            "header_label": task.header_label,
            "completed_at": (
                task.completed_at.isoformat()
                if task.completed_at
                else datetime.now(UTC).isoformat()
            ),
            "verdict": {
                "user_input": user_input[:LOOP_VERDICT_MAX_LENGTH],
                "selected_options": [
                    str(opt)[:LOOP_VERDICT_MAX_LENGTH] for opt in selected
                ],
                "image_count": image_count,
            },
        }

        bucket = self._loop_history.pop(loop_id, None)
        if bucket is None:
            bucket = {
                "loop_id": loop_id,
                "objective": None,
                "success_criteria": None,
                "rounds": [],
            }
        if task.loop_objective:
            bucket["objective"] = task.loop_objective
        if task.success_criteria:
            bucket["success_criteria"] = task.success_criteria

        rounds = bucket.get("rounds")
        if not isinstance(rounds, list):
            rounds = []
            bucket["rounds"] = rounds
        rounds.append(entry)
        if len(rounds) > LOOP_HISTORY_MAX_ROUNDS:
            del rounds[: len(rounds) - LOOP_HISTORY_MAX_ROUNDS]
        bucket["updated_at"] = entry["completed_at"]

        self._loop_history[loop_id] = bucket
        while len(self._loop_history) > LOOP_HISTORY_MAX_LOOPS:
            evicted_id = next(iter(self._loop_history))
            self._loop_history.pop(evicted_id, None)
            logger.info(f"loop 台账超限，驱逐最久未更新的 loop: {evicted_id}")

    def get_loops_snapshot(self) -> list[dict[str, Any]]:
        """获取 loop 台账快照 + 各 loop 当前在队列中的活跃轮次。"""
        with self._lock.read_lock():
            snapshot: list[dict[str, Any]] = []
            live_by_loop: dict[str, list[dict[str, Any]]] = {}
            for task in self._tasks.values():
                if not task.loop_id:
                    continue
                live_by_loop.setdefault(task.loop_id, []).append(
                    {
                        "task_id": task.task_id,
                        "status": task.status,
                        "iteration_label": task.iteration_label,
                        "loop_phase": task.loop_phase,
                        "header_label": task.header_label,
                        "created_at": task.created_at.isoformat(),
                    }
                )

            seen: set[str] = set()

            for loop_id in reversed(list(self._loop_history)):
                bucket = self._loop_history[loop_id]
                seen.add(loop_id)
                snapshot.append(
                    {
                        "loop_id": loop_id,
                        "objective": bucket.get("objective"),
                        "success_criteria": bucket.get("success_criteria"),
                        "updated_at": bucket.get("updated_at"),
                        "rounds": copy.deepcopy(bucket.get("rounds", [])),
                        "live_tasks": live_by_loop.get(loop_id, []),
                    }
                )

            for loop_id, live_tasks in live_by_loop.items():
                if loop_id in seen:
                    continue

                objective = None
                criteria = None
                for task in self._tasks.values():
                    if task.loop_id != loop_id:
                        continue
                    if task.loop_objective:
                        objective = task.loop_objective
                    if task.success_criteria:
                        criteria = task.success_criteria
                snapshot.append(
                    {
                        "loop_id": loop_id,
                        "objective": objective,
                        "success_criteria": criteria,
                        "updated_at": None,
                        "rounds": [],
                        "live_tasks": live_tasks,
                    }
                )

            return snapshot

    def remove_task(self, task_id: str) -> bool:
        """移除任务（立即删除）"""
        status_events: list[tuple[str, str | None, str]] = []
        with _watched_write_lock(self._lock, "remove_task"):
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            old_status = self._tasks[task_id].status
            next_activated_id = None

            if self._active_task_id == task_id:
                self._active_task_id = None

                for tid, t in self._tasks.items():
                    if tid != task_id and t.status in (
                        TaskStatus.PENDING,
                        TaskStatus.ACTIVE,
                    ):
                        self._active_task_id = tid
                        old_next_status = t.status
                        t.status = TaskStatus.ACTIVE
                        next_activated_id = tid
                        break

            self._tasks.pop(task_id, None)

            logger.info(
                f"移除任务: {task_id}, 剩余任务数: {len(self._tasks)}/{self.max_tasks}"
            )

            status_events.append((task_id, old_status, TaskStatus.REMOVED))
            if next_activated_id:
                status_events.append(
                    (next_activated_id, old_next_status, TaskStatus.ACTIVE)
                )

        for ev_task_id, ev_old_status, ev_new_status in status_events:
            self._trigger_status_change(ev_task_id, ev_old_status, ev_new_status)

        self._persist()
        return True

    def clear_completed_tasks(self) -> int:
        """清理所有已完成的任务（立即删除）"""
        with _watched_write_lock(self._lock, "clear_completed_tasks"):
            completed_task_ids = [
                tid
                for tid, task in self._tasks.items()
                if task.status == TaskStatus.COMPLETED
            ]

            for tid in completed_task_ids:
                self._tasks.pop(tid, None)

            count = len(completed_task_ids)
            if count > 0:
                logger.info(f"清理了 {count} 个已完成任务")

            return count

    def cleanup_completed_tasks(self, age_seconds: int = 10) -> int:
        """清理超过指定时间的已完成任务（后台清理核心方法）"""
        with _watched_write_lock(self._lock, "cleanup_completed_tasks"):
            now = datetime.now(UTC)
            tasks_to_remove = []

            for task_id, task in self._tasks.items():
                if task.status == TaskStatus.COMPLETED and task.completed_at:
                    age = (now - task.completed_at).total_seconds()
                    if age > age_seconds:
                        tasks_to_remove.append(task_id)

            for task_id in tasks_to_remove:
                self._tasks.pop(task_id, None)

            if tasks_to_remove:
                logger.info(
                    f"清理了 {len(tasks_to_remove)} 个已完成任务: {tasks_to_remove}"
                )

            return len(tasks_to_remove)

    def cleanup_completed_tasks_throttled(
        self, age_seconds: int = 10, throttle_seconds: float = 30.0
    ) -> int:
        """节流版 cleanup —— 用于 hot path（如 GET /api/tasks）的兜底调用。"""
        now = time.monotonic()

        with self._hotpath_cleanup_lock:
            elapsed = now - self._last_hotpath_cleanup_monotonic
            if elapsed < throttle_seconds:
                return 0

            self._last_hotpath_cleanup_monotonic = now

        return self.cleanup_completed_tasks(age_seconds=age_seconds)

    def _cleanup_loop(self):
        """后台清理循环（守护线程入口）"""
        logger.info("后台清理线程启动")
        while not self._stop_cleanup.wait(timeout=5):
            try:
                cleaned = self.cleanup_completed_tasks(age_seconds=10)
                if cleaned > 0:
                    logger.debug(f"后台清理线程清理了 {cleaned} 个任务")
            except Exception as e:
                logger.error(f"后台清理线程异常: {e}", exc_info=True)
        logger.info("后台清理线程已停止")

    def stop_cleanup(self) -> None:
        """停止后台清理线程"""
        logger.info("正在停止后台清理线程...")
        self._stop_cleanup.set()
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2)
            if self._cleanup_thread.is_alive():
                logger.warning("后台清理线程未能在2秒内停止")
            else:
                logger.info("后台清理线程已成功停止")

    def get_task_count(self) -> dict[str, int]:
        """获取任务统计信息（R522：状态计数单趟直接分桶，不二次遍历）。"""
        with self._lock.read_lock():
            if not self._tasks:
                return {
                    "total": 0,
                    "pending": 0,
                    "active": 0,
                    "completed": 0,
                    "max": self.max_tasks,
                }
            pending = active = completed = 0
            for t in self._tasks.values():
                if t.status == TaskStatus.PENDING:
                    pending += 1
                elif t.status == TaskStatus.ACTIVE:
                    active += 1
                elif t.status == TaskStatus.COMPLETED:
                    completed += 1
            return {
                "total": len(self._tasks),
                "pending": pending,
                "active": active,
                "completed": completed,
                "max": self.max_tasks,
            }

    def register_status_change_callback(
        self, callback: Callable[[str, str | None, str], None]
    ) -> None:
        """注册任务状态变更回调函数"""
        with self._callbacks_lock:
            if callback not in self._status_change_callbacks:
                self._status_change_callbacks.append(callback)
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.debug(f"已注册任务状态变更回调: {cb_name}")

    def unregister_status_change_callback(
        self, callback: Callable[[str, str | None, str], None]
    ) -> None:
        """取消注册任务状态变更回调函数"""
        with self._callbacks_lock:
            if callback in self._status_change_callbacks:
                self._status_change_callbacks.remove(callback)
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.debug(f"已取消任务状态变更回调: {cb_name}")

    def _trigger_status_change(
        self, task_id: str, old_status: str | None, new_status: str
    ):
        """触发任务状态变更回调"""
        with self._callbacks_lock:
            callbacks = list(self._status_change_callbacks)

        for callback in callbacks:
            try:
                callback(task_id, old_status, new_status)
            except Exception as e:
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.error(
                    f"任务状态变更回调执行失败 ({cb_name}): {e}", exc_info=True
                )

    def _persist(self) -> None:
        """将当前任务快照写入磁盘（原子操作：tmpfile → fsync → os.replace）。"""
        if not self._persist_path:
            return
        try:
            with self._lock.read_lock():
                snapshot = []
                for task in self._tasks.values():
                    if task.status == TaskStatus.COMPLETED:
                        continue
                    snapshot.append(
                        {
                            "task_id": task.task_id,
                            "prompt": task.prompt,
                            "predefined_options": task.predefined_options,
                            "predefined_options_defaults": task.predefined_options_defaults,
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "auto_resubmit_timeout_explicit": task.auto_resubmit_timeout_explicit,
                            "created_at": task.created_at.isoformat(),
                            "status": task.status,
                            "feedback_placeholder": task.feedback_placeholder,
                            "header_label": task.header_label,
                            "loop_id": task.loop_id,
                            "loop_objective": task.loop_objective,
                            "loop_phase": task.loop_phase,
                            "success_criteria": task.success_criteria,
                            "iteration_label": task.iteration_label,
                        }
                    )
                active_id = self._active_task_id

                loop_history_snapshot = copy.deepcopy(self._loop_history)

            if not snapshot and not loop_history_snapshot:
                self._persist_path.unlink(missing_ok=True)
                logger.debug("任务快照为空，已删除持久化文件")
                return

            data = {
                "version": 1,
                "active_task_id": active_id,
                "tasks": snapshot,
                "loop_history": loop_history_snapshot,
                "saved_at": datetime.now(UTC).isoformat(),
            }

            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._persist_path.parent),
                prefix=".tasks_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(
                        data,
                        f,
                        ensure_ascii=False,
                        separators=_COMPACT_JSON_SEPARATORS,
                    )

                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(self._persist_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            logger.debug(f"任务快照已持久化: {len(snapshot)} 个任务")
        except Exception as e:
            logger.warning(f"任务持久化失败（不影响运行）: {e}", exc_info=True)

    def _restore(self) -> None:
        """从磁盘恢复未完成的任务。仅在初始化时调用一次。"""
        if not self._persist_path:
            return
        try:
            raw = self._persist_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception as e:
            logger.warning(f"任务恢复失败（将使用空队列）: {e}", exc_info=True)
            self._quarantine_corrupt_persist_file(reason=str(e))
            return

        try:
            if not raw.strip():
                return
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("version") != 1:
                logger.warning("持久化文件版本不匹配，忽略")
                return

            restore_now = datetime.now(UTC)
            saved_at_str = data.get("saved_at")
            saved_at = (
                datetime.fromisoformat(saved_at_str) if saved_at_str else restore_now
            )
            elapsed_since_save = (restore_now - saved_at).total_seconds()

            restored = 0
            skipped = 0
            tasks_raw = data.get("tasks")
            tasks_items = tasks_raw if isinstance(tasks_raw, list) else ()
            for item in tasks_items:
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                task_id = item.get("task_id")
                prompt = item.get("prompt")
                if not task_id or not prompt:
                    skipped += 1
                    continue
                status = item.get("status", TaskStatus.PENDING)
                if status == TaskStatus.COMPLETED:
                    continue

                try:
                    created_at = datetime.fromisoformat(item["created_at"])
                    age_since_creation = (restore_now - created_at).total_seconds()

                    restored_placeholder = item.get("feedback_placeholder")
                    if isinstance(restored_placeholder, str):
                        s = restored_placeholder.strip()
                        restored_placeholder = s[:PLACEHOLDER_MAX_LENGTH] if s else None
                    else:
                        restored_placeholder = None

                    restored_header = item.get("header_label")
                    if isinstance(restored_header, str):
                        s = restored_header.strip()
                        restored_header = s[:HEADER_LABEL_MAX_LENGTH] if s else None
                    else:
                        restored_header = None

                    task = Task(
                        task_id=task_id,
                        prompt=prompt,
                        predefined_options=item.get("predefined_options"),
                        predefined_options_defaults=item.get(
                            "predefined_options_defaults"
                        ),
                        auto_resubmit_timeout=item.get(
                            "auto_resubmit_timeout", AUTO_RESUBMIT_TIMEOUT_DEFAULT
                        ),
                        auto_resubmit_timeout_explicit=bool(
                            item.get("auto_resubmit_timeout_explicit", False)
                        ),
                        created_at=created_at,
                        created_at_monotonic=time.monotonic() - age_since_creation,
                        status=TaskStatus.PENDING,
                        feedback_placeholder=restored_placeholder,
                        header_label=restored_header,
                        loop_id=_normalize_optional_text(
                            item.get("loop_id"), LOOP_ID_MAX_LENGTH
                        ),
                        loop_objective=_normalize_optional_text(
                            item.get("loop_objective"), LOOP_TEXT_MAX_LENGTH
                        ),
                        loop_phase=_normalize_optional_text(
                            item.get("loop_phase"), LOOP_LABEL_MAX_LENGTH
                        ),
                        success_criteria=_normalize_optional_text(
                            item.get("success_criteria"), LOOP_TEXT_MAX_LENGTH
                        ),
                        iteration_label=_normalize_optional_text(
                            item.get("iteration_label"), LOOP_LABEL_MAX_LENGTH
                        ),
                    )
                except Exception as task_err:
                    skipped += 1
                    logger.warning(
                        f"恢复单个任务失败（跳过）: task_id={task_id!r} err={task_err}"
                    )
                    continue

                self._tasks[task_id] = task
                restored += 1

            active_id = data.get("active_task_id")
            if active_id and active_id in self._tasks:
                self._active_task_id = active_id
                self._tasks[active_id].status = TaskStatus.ACTIVE
            elif self._tasks:
                first_id = next(iter(self._tasks))
                self._active_task_id = first_id
                self._tasks[first_id].status = TaskStatus.ACTIVE

            self._restore_loop_history(data.get("loop_history"))

            if restored > 0:
                logger.info(
                    f"从持久化文件恢复了 {restored} 个未完成任务"
                    f"（文件保存于 {elapsed_since_save:.0f}s 前"
                    f"{f'，跳过 {skipped} 个损坏项' if skipped else ''}）"
                )
            elif skipped > 0:
                logger.warning(f"持久化文件中所有 {skipped} 个任务均损坏，已跳过")
        except Exception as e:
            logger.warning(f"任务恢复失败（将使用空队列）: {e}", exc_info=True)
            self._quarantine_corrupt_persist_file(reason=str(e))

    def _restore_loop_history(self, raw: Any) -> None:
        """从快照数据恢复 loop 台账（仅在 ``_restore`` 内调用，无需持锁——
        ``__init__`` 阶段尚无并发访问者）。"""
        if not isinstance(raw, dict):
            return
        restored: dict[str, dict[str, Any]] = {}
        for loop_id, bucket in raw.items():
            if not isinstance(loop_id, str) or not loop_id.strip():
                continue
            if not isinstance(bucket, dict):
                continue
            rounds_raw = bucket.get("rounds")
            rounds = (
                [r for r in rounds_raw if isinstance(r, dict)]
                if isinstance(rounds_raw, list)
                else []
            )
            restored[loop_id] = {
                "loop_id": loop_id,
                "objective": _normalize_optional_text(
                    bucket.get("objective"), LOOP_TEXT_MAX_LENGTH
                ),
                "success_criteria": _normalize_optional_text(
                    bucket.get("success_criteria"), LOOP_TEXT_MAX_LENGTH
                ),
                "updated_at": bucket.get("updated_at"),
                "rounds": rounds[-LOOP_HISTORY_MAX_ROUNDS:],
            }
        if len(restored) > LOOP_HISTORY_MAX_LOOPS:
            keep = list(restored)[-LOOP_HISTORY_MAX_LOOPS:]
            restored = {k: restored[k] for k in keep}
        if restored:
            self._loop_history = restored
            logger.info(f"从持久化文件恢复了 {len(restored)} 个 loop 台账")

    def _quarantine_corrupt_persist_file(self, *, reason: str) -> None:
        """把损坏的 persist 文件重命名为 ``<path>.corrupt-<ISO>``，避免被
        下次 ``_persist`` 的 ``os.replace`` 静默覆盖。"""
        if not self._persist_path:
            return
        try:
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            corrupt_path = self._persist_path.with_name(
                f"{self._persist_path.name}.corrupt-{ts}"
            )
            os.replace(str(self._persist_path), str(corrupt_path))
            logger.warning(
                "已将损坏的持久化文件 quarantine 至 "
                f"{corrupt_path.name}（原因: {reason}）；"
                "运维可保留该文件用于断电 / fsync 异常诊断，"
                "或手动删除"
            )
        except FileNotFoundError:
            return
        except OSError as quarantine_err:
            logger.warning(
                f"quarantine 损坏持久化文件失败（best-effort 已忽略）: {quarantine_err}"
            )
