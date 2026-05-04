# notification_providers

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/notification_providers.md`](../api/notification_providers.md)

通知提供者实现 - Web/Sound/Bark/System 四种通知方式。

所有提供者实现 send(event) -> bool 接口，由 NotificationManager 调用。

## 函数

### `_coerce_bark_format_value(value: Any) -> str`

把任意 value 转成对 URL 友好的字符串；非标量一律视为空。

### `render_bark_url_template(template: str, params: dict[str, Any]) -> str`

安全渲染 Bark 点击 URL 模板。

- 模板为空 / 渲染异常时返回空串（调用方应判空跳过 url 字段）。
- 不会抛出 KeyError；缺失的占位符保持 "{name}" 字面量（便于排查）。

### `create_notification_providers(config) -> dict[NotificationType, BaseNotificationProvider]`

工厂函数 - 根据配置启用状态创建提供者实例

### `initialize_notification_system(config)`

创建提供者并注册到全局 notification_manager

## 类

### `class _BarkSafeFormatDict`

str.format_map() 的兜底字典：未命中的 key 原样返回 "{key}"。

#### 方法

### `class BaseNotificationProvider`

通知 Provider 抽象基类（阶段 A：统一接口与可观测性基线）。

#### 方法

##### `__init__(self, config)`

##### `send(self, event: NotificationEvent) -> bool`

发送/准备通知。失败返回 False，异常应在内部捕获并降级为 False。

##### `close(self) -> None`

释放资源（可选）。默认无操作。

### `class WebNotificationProvider`

Web 浏览器通知 - 准备通知数据到 event.metadata 供前端轮询展示。

#### 方法

##### `__init__(self, config)`

##### `register_client(self, client_id: str, client_info: dict[str, Any])`

注册 Web 客户端

##### `unregister_client(self, client_id: str)`

注销 Web 客户端

##### `send(self, event: NotificationEvent) -> bool`

准备通知数据到 event.metadata['web_notification_data']

### `class SoundNotificationProvider`

声音通知 - 准备音频数据到 event.metadata 供前端播放。

#### 方法

##### `__init__(self, config)`

##### `send(self, event: NotificationEvent) -> bool`

准备声音数据到 event.metadata['sound_notification_data']，静音时返回True但不播放

### `class BarkNotificationProvider`

Bark iOS 推送 - 通过 HTTP POST 发送通知到 Bark 服务器。

#### 方法

##### `__init__(self, config)`

初始化 Session 连接池（3次重试）

##### `close(self) -> None`

关闭 HTTP Session，释放连接池资源（幂等）。

##### `send(self, event: NotificationEvent) -> bool`

HTTP POST 发送通知到 Bark，返回成功与否

### `class SystemNotificationProvider`

系统通知 - 通过 plyer 库发送跨平台桌面通知（可选依赖）。

#### 方法

##### `__init__(self, config)`

检查 plyer 库是否可用

##### `send(self, event: NotificationEvent) -> bool`

调用 plyer 发送系统通知

注意：``timeout`` 参数指通知 banner 在屏幕上显示的时长，不是发送超时。
plyer 自身没有发送超时机制；如果底层平台 API 卡住，依赖
``NotificationManager._process_event`` 的 ``as_completed`` 兜底
（见 ``notification_manager._AS_COMPLETED_TIMEOUT_BUFFER_SECONDS``）。
