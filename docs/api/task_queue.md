# task_queue

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/task_queue.md`](../api.zh-CN/task_queue.md)

## Classes

### `class Task`

#### Methods

##### `get_remaining_time(self) -> int`

##### `get_deadline_monotonic(self) -> float`

##### `is_expired(self) -> bool`

### `class TaskQueue`

#### Methods

##### `__init__(self, max_tasks: int = 10)`

##### `clear_all_tasks(self)`

##### `add_task(self, task_id: str, prompt: str, predefined_options: Optional[List[str]] = None, auto_resubmit_timeout: int = 240) -> bool`

##### `get_task(self, task_id: str) -> Optional[Task]`

##### `get_all_tasks(self) -> List[Task]`

##### `get_active_task(self) -> Optional[Task]`

##### `set_active_task(self, task_id: str) -> bool`

##### `complete_task(self, task_id: str, result: Dict[str, Any]) -> bool`

##### `remove_task(self, task_id: str) -> bool`

##### `clear_completed_tasks(self) -> int`

##### `cleanup_completed_tasks(self, age_seconds: int = 10) -> int`

##### `stop_cleanup(self)`

##### `get_task_count(self) -> Dict[str, int]`

##### `register_status_change_callback(self, callback: Callable[[str, Optional[str], str], None])`

##### `unregister_status_change_callback(self, callback: Callable[[str, Optional[str], str], None])`
