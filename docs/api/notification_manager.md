# notification_manager

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/notification_manager.md`](../api.zh-CN/notification_manager.md)

## Functions

### `_shutdown_global_notification_manager()`

## Classes

### `class NotificationConfig`

#### Methods

##### `from_config_file(cls) -> 'NotificationConfig'`

### `class NotificationManager`

#### Methods

##### `__init__(self)`

##### `register_provider(self, notification_type: NotificationType, provider: Any) -> None`

##### `add_callback(self, event_name: str, callback: Callable) -> None`

##### `trigger_callbacks(self, event_name: str) -> None`

##### `send_notification(self, title: str, message: str, trigger: NotificationTrigger = NotificationTrigger.IMMEDIATE, types: Optional[List[NotificationType]] = None, metadata: Optional[Dict[str, Any]] = None, priority: NotificationPriority | str = NotificationPriority.NORMAL) -> str`

##### `shutdown(self, wait: bool = False) -> None`

##### `restart(self) -> None`

##### `get_config(self) -> NotificationConfig`

##### `refresh_config_from_file(self, force: bool = False) -> None`

##### `update_config(self) -> None`

##### `update_config_without_save(self) -> None`

##### `get_status(self) -> Dict[str, Any]`
