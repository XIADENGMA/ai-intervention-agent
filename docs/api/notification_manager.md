# notification_manager

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/notification_manager.md`](../api.zh-CN/notification_manager.md)

## Functions

### `_shutdown_global_notification_manager()`

## Classes

### `class NotificationType`

### `class NotificationTrigger`

### `class NotificationConfig`

#### Methods

##### `from_config_file(cls) -> 'NotificationConfig'`

### `class NotificationEvent`

### `class NotificationManager`

#### Methods

##### `__init__(self)`

##### `register_provider(self, notification_type: NotificationType, provider: Any)`

##### `add_callback(self, event_name: str, callback: Callable)`

##### `trigger_callbacks(self, event_name: str)`

##### `send_notification(self, title: str, message: str, trigger: NotificationTrigger = NotificationTrigger.IMMEDIATE, types: Optional[List[NotificationType]] = None, metadata: Optional[Dict[str, Any]] = None) -> str`

##### `shutdown(self, wait: bool = False)`

##### `restart(self)`

##### `get_config(self) -> NotificationConfig`

##### `refresh_config_from_file(self, force: bool = False)`

##### `update_config(self)`

##### `update_config_without_save(self)`

##### `get_status(self) -> Dict[str, Any]`
