# notification_providers

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/notification_providers.md`](../api.zh-CN/notification_providers.md)

## Functions

### `_coerce_bark_format_value(value: Any) -> str`

### `render_bark_url_template(template: str, params: dict[str, Any]) -> str`

### `create_notification_providers(config) -> dict[NotificationType, BaseNotificationProvider]`

### `initialize_notification_system(config)`

## Classes

### `class _BarkSafeFormatDict`

#### Methods

### `class BaseNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `send(self, event: NotificationEvent) -> bool`

##### `close(self) -> None`

### `class WebNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `register_client(self, client_id: str, client_info: dict[str, Any])`

##### `unregister_client(self, client_id: str)`

##### `send(self, event: NotificationEvent) -> bool`

### `class SoundNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `send(self, event: NotificationEvent) -> bool`

### `class BarkNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `close(self) -> None`

##### `send(self, event: NotificationEvent) -> bool`

### `class SystemNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `send(self, event: NotificationEvent) -> bool`
