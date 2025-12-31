# notification_providers

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/notification_providers.md`](../api.zh-CN/notification_providers.md)

## Functions

### `create_notification_providers(config) -> Dict[NotificationType, Any]`

### `initialize_notification_system(config)`

## Classes

### `class WebNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `register_client(self, client_id: str, client_info: Dict[str, Any])`

##### `unregister_client(self, client_id: str)`

##### `send(self, event: NotificationEvent) -> bool`

### `class SoundNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `send(self, event: NotificationEvent) -> bool`

### `class BarkNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `send(self, event: NotificationEvent) -> bool`

### `class SystemNotificationProvider`

#### Methods

##### `__init__(self, config)`

##### `send(self, event: NotificationEvent) -> bool`
