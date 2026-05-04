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

##### `shutdown(self, wait: bool = False, grace_period: float = 0.0) -> None`

关闭管理器，取消延迟 Timer 并关闭线程池（幂等）。

参数：
    wait: ``True`` 时阻塞直到全部 worker 完成（与
        ``ThreadPoolExecutor.shutdown(wait=True)`` 同语义）；
        ``False`` 时仅取消 pending future、不等 in-flight。
    grace_period: ``wait=False`` 时的额外宽限窗口（秒）。
        取值 ``> 0`` 表示：在 ``shutdown`` 调用线程上 best-effort
        ``join`` 每个 worker 线程，最多累计 ``grace_period`` 秒，
        让正在跑的 osascript / HTTP 通知有机会自然收尾，避免
        ``atexit`` 阶段 in-flight 被切断后才意识到（log 已经
        关、进程已经在 cleanup）。**不**会让 ``shutdown`` 等到
        超过 ``grace_period``——超时则直接 return，worker 继续
        由 Python 主进程退出阶段去 join 收尾（worker 默认
        non-daemon）。

Why grace_period 而不是直接 ``daemon=True``:
    把 worker 标 daemon 需要子类化 ``ThreadPoolExecutor`` 重写
    ``_adjust_thread_count``（私有 API，跨 Python 版本不稳）。
    grace_period 路径只读 ``_threads`` 集合（私有但仅遍历），
    不修改 ``ThreadPoolExecutor`` 行为，最低耦合。

    行业参考：Pgsql / etcd / aiohttp 在退出阶段都给 worker
    一段固定 grace（典型 1-3s），平衡"通知应当尽量送达"与
    "用户不该看到程序挂起"两个目标。

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
