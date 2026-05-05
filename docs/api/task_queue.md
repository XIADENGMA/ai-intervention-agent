# task_queue

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/task_queue.md`](../api.zh-CN/task_queue.md)

## Classes

### `class TaskStatus`

### `class Task`

#### Methods

##### `get_remaining_time(self) -> int`

##### `get_deadline_monotonic(self) -> float`

##### `is_expired(self) -> bool`

### `class TaskQueue`

#### Methods

##### `__init__(self, max_tasks: int = 10, persist_path: str | None = None)`

##### `clear_all_tasks(self) -> int`

##### `add_task(self, task_id: str, prompt: str, predefined_options: list[str] | None = None, auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT, predefined_options_defaults: list[bool] | None = None) -> bool`

##### `get_task(self, task_id: str) -> Task | None`

##### `get_all_tasks(self) -> list[Task]`

##### `update_auto_resubmit_timeout_for_all(self, auto_resubmit_timeout: int) -> int`

##### `get_active_task(self) -> Task | None`

##### `set_active_task(self, task_id: str) -> bool`

##### `complete_task(self, task_id: str, result: dict[str, Any]) -> bool`

##### `remove_task(self, task_id: str) -> bool`

##### `clear_completed_tasks(self) -> int`

##### `cleanup_completed_tasks(self, age_seconds: int = 10) -> int`

##### `cleanup_completed_tasks_throttled(self, age_seconds: int = 10, throttle_seconds: float = 30.0) -> int`

##### `stop_cleanup(self) -> None`

##### `get_task_count(self) -> dict[str, int]`

##### `register_status_change_callback(self, callback: Callable[[str, str | None, str], None]) -> None`

##### `unregister_status_change_callback(self, callback: Callable[[str, str | None, str], None]) -> None`
