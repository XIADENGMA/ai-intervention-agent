# task_queue

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/task_queue.md`](../api/task_queue.md)

任务队列管理 - 线程安全、状态管理、自动清理、延迟删除、持久化。

清理契约：后台守护线程每 5秒 检查一次，完成任务延迟 10秒 后删除
（避免前端轮询遇到 404）。

## 函数

### `_prompt_utf8_size_for_guard(prompt: str) -> int`

Return a prompt byte size suitable for the R53-A threshold guard.

### `_normalize_optional_text(value: Any, max_length: int) -> str | None`

Loop engineering P1 — 可选自由文本字段的统一 normalize。

### `_capture_all_thread_stacks() -> str`

采集进程内所有线程的当前调用栈，拼成可读字符串。

### `_scan_pending_and_dump_slow() -> int`

单次扫描：把超时但尚未 dump 的 record 拣出来，dump 全栈到 logger.error。

### `_lock_watchdog_loop() -> None`

daemon 后台线程主循环：用 Event 而非裸 ``time.sleep``，方便测试唤醒。

### `_ensure_lock_watchdog_started() -> None`

懒启动：第一次有人 ``_watched_write_lock`` 才把 daemon 起来。

### `_watched_write_lock(rwlock: ReadWriteLock, label: str) -> Generator[None, None, None]`

``rwlock.write_lock()`` 的 deadlock-aware 包装。

## 类

### `class TaskStatus`

任务状态枚举（StrEnum 使其与纯字符串完全兼容）

### `class Task`

任务数据结构：task_id, prompt, options, status, result

#### 方法

##### `get_remaining_time(self, now_monotonic: float | None = None) -> int`

计算剩余倒计时（使用单调时间）。

##### `get_deadline_monotonic(self) -> float`

获取截止时间的单调时间戳

##### `is_expired(self) -> bool`

检查任务是否已超时

##### `extend_deadline(self, seconds: int) -> tuple[bool, str | None]`

feat-countdown-extend (§3.2): 用户主动延长 task 的 auto-resubmit
倒计时。

##### `freeze_deadline(self) -> tuple[bool, str | None]`

mining-6 Track A (cycle-5 §3.6 derivative): 用户主动把 task 的
auto-resubmit 倒计时禁用，把 task 变成无 timeout 的"等用户回答"状态。

### `class TaskQueue`

任务队列管理器（线程安全）。

并发契约（R22.2）：`_lock` 为 ReadWriteLock——读读并发、读写互斥、
写写互斥。禁止已持锁线程再次获取本锁（不支持递归/升级/降级）；
写后副作用（_persist / _trigger_status_change）必须在锁外触发。

#### 方法

##### `__init__(self, max_tasks: int = 10, persist_path: str | None = None)`

初始化任务队列

##### `clear_all_tasks(self) -> int`

清理所有任务（重置队列）

##### `add_task(self, task_id: str, prompt: str, predefined_options: list[str] | None = None, auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT, predefined_options_defaults: list[bool] | None = None, feedback_placeholder: str | None = None, header_label: str | None = None, auto_resubmit_timeout_explicit: bool = False, loop_id: str | None = None, loop_objective: str | None = None, loop_phase: str | None = None, success_criteria: str | None = None, iteration_label: str | None = None) -> bool`

添加任务，无活动任务时自动激活

##### `get_task(self, task_id: str) -> Task | None`

获取指定任务

##### `get_all_tasks(self) -> list[Task]`

获取所有任务列表

##### `get_first_incomplete_task(self) -> Task | None`

Return the first non-completed task in insertion order.

##### `has_tasks(self) -> bool`

Return whether the queue currently contains any task.

##### `get_all_tasks_with_stats(self) -> tuple[list[Task], dict[str, int]]`

单次 read_lock 内同时拿 task list + stats，专门给 ``/api/tasks`` 用。

R23.4：合并旧的 get_all_tasks() + get_task_count() 两次 read_lock，
原子语义升级（list 与 stats 同一快照）。R521：list 与 counts 在同
一次 values 循环内一趟构建。R522：状态计数直接分桶，不再二次遍历。

##### `update_auto_resubmit_timeout_for_all(self, auto_resubmit_timeout: int) -> int`

更新所有未完成任务的 auto_resubmit_timeout

##### `get_active_task(self) -> Task | None`

获取当前活动任务

##### `extend_task_deadline(self, task_id: str, seconds: int) -> tuple[bool, str | None, int, int]`

cr32 §3.1 fix：在写锁内执行 ``Task.extend_deadline`` 的读改写原语。

##### `freeze_task_deadline(self, task_id: str) -> tuple[bool, str | None, int]`

mining-6 Track A: 在写锁内调用 ``Task.freeze_deadline``。

##### `set_active_task(self, task_id: str) -> bool`

手动切换活动任务

##### `complete_task(self, task_id: str, result: dict[str, Any]) -> bool`

完成任务并标记为延迟删除（核心方法）

##### `get_loops_snapshot(self) -> list[dict[str, Any]]`

获取 loop 台账快照 + 各 loop 当前在队列中的活跃轮次。

##### `remove_task(self, task_id: str) -> bool`

移除任务（立即删除）

##### `clear_completed_tasks(self) -> int`

清理所有已完成的任务（立即删除）

##### `cleanup_completed_tasks(self, age_seconds: int = 10) -> int`

清理超过指定时间的已完成任务（后台清理核心方法）

##### `cleanup_completed_tasks_throttled(self, age_seconds: int = 10, throttle_seconds: float = 30.0) -> int`

节流版 cleanup —— 用于 hot path（如 GET /api/tasks）的兜底调用。

##### `stop_cleanup(self) -> None`

停止后台清理线程

##### `get_task_count(self) -> dict[str, int]`

获取任务统计信息（R522：状态计数单趟直接分桶，不二次遍历）。

##### `register_status_change_callback(self, callback: Callable[[str, str | None, str], None]) -> None`

注册任务状态变更回调函数

##### `unregister_status_change_callback(self, callback: Callable[[str, str | None, str], None]) -> None`

取消注册任务状态变更回调函数
