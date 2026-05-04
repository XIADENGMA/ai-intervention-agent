# notification_manager

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/notification_manager.md`](../api/notification_manager.md)

通知管理器模块 - 统一管理 Web/声音/Bark/系统多渠道通知。

采用单例模式，支持插件化提供者注册、事件队列、失败降级。线程安全。

## 函数

### `_shutdown_global_notification_manager()`

## 类

### `class NotificationConfig`

通知配置类 - 全局开关/Web/声音/触发时机/重试/移动优化/Bark 等配置。

#### 方法

##### `clamp_sound_volume(cls, v: float) -> float`

##### `coerce_retry_count(cls, v: Any) -> int`

##### `coerce_retry_delay(cls, v: Any) -> int`

##### `coerce_bark_timeout(cls, v: Any) -> int`

##### `validate_bark_action(cls, v: str) -> str`

##### `warn_bark_config(self) -> 'NotificationConfig'`

##### `from_config_file(cls) -> 'NotificationConfig'`

从配置文件 notification 段加载配置，sound_volume 自动转换 0-100 到 0.0-1.0

注意：get_section() 已通过 Pydantic 段模型（NotificationSectionConfig）完成
类型强转（SafeBool/ClampedInt）和范围钳位，此处无需再做手工转换。

### `class NotificationManager`

通知管理器（单例）- 管理提供者注册、事件队列、配置和回调，线程安全。

#### 方法

##### `__init__(self)`

初始化配置、提供者字典、事件队列、线程池和回调

##### `register_provider(self, notification_type: NotificationType, provider: Any) -> None`

注册通知提供者（需实现 send(event) -> bool）

##### `add_callback(self, event_name: str, callback: Callable) -> None`

添加事件回调（如 notification_sent, notification_fallback）

##### `trigger_callbacks(self, event_name: str) -> None`

触发指定事件的所有回调，异常不中断后续回调

##### `send_notification(self, title: str, message: str, trigger: NotificationTrigger = NotificationTrigger.IMMEDIATE, types: list[NotificationType] | None = None, metadata: dict[str, Any] | None = None, priority: NotificationPriority | str = NotificationPriority.NORMAL) -> str`

发送通知主入口，返回事件ID。types=None 时根据配置自动选择渠道。

##### `shutdown(self, wait: bool = False) -> None`

关闭管理器，取消延迟 Timer 并关闭线程池（幂等）

##### `restart(self) -> None`

shutdown 后重建线程池

##### `get_config(self) -> NotificationConfig`

返回当前配置对象引用

##### `refresh_config_from_file(self, force: bool = False) -> None`

从配置文件刷新配置（mtime 缓存优化，force=True 强制刷新）

##### `update_config(self) -> None`

更新配置并持久化到文件

##### `update_config_without_save(self) -> None`

仅内存更新配置，不写文件。bark_enabled 变化时自动更新提供者。

##### `get_status(self) -> dict[str, Any]`

返回管理器状态：enabled/providers/queue_size/config/stats
