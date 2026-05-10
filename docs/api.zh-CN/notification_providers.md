# notification_providers

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/notification_providers.md`](../api/notification_providers.md)

通知提供者实现 - Web/Sound/Bark/System 四种通知方式。

所有提供者实现 send(event) -> bool 接口，由 NotificationManager 调用。

## 函数

### `_bark_url_is_loopback(url: str) -> bool`

Bark provider 内部 helper：判断渲染出的点击 URL 是否回环地址。

手机收到 Bark 通知时，``http://localhost:8080`` 等 loopback URL 会被
手机自身解析（RFC 6762 §11 / RFC 5735）—— 把这种 URL 推过去等于让用户
点开后看到 "无法访问"，反而不如不附 ``url`` 字段（这样 Bark 默认行为
是停留在通知中心，体验更可控）。

实现 lazy import ``server_config.is_loopback_url`` 以避免触发 ``mcp.types``
的级联加载（参见 ``server_config._lazy_mcp_types``），任何 import / 解析
异常都返回 ``False``，让通知链路按 "未识别即放行" 优雅降级。

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

### `class _LazyHttpx`

延迟加载 httpx，同时保留 ``notification_providers.httpx.X`` 访问形态。

#### 方法

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

**R117**：``httpx.Client.close()`` 抛异常曾经被 ``except Exception:
pass`` 完全静默——这是 ``shutdown()`` / ``atexit`` 路径上**唯一**
承担连接池清理的调用，静默失败意味着连接池资源（TCP socket、
keep-alive 连接、HTTP/2 stream 状态）有可能泄漏却没有任何信号
让运维 / 维护者察觉。

修复策略：保持 try/except 不让异常扩散打断 shutdown chain（其他
provider 的 close() 还要继续走），但把 exception 写到 debug 级
日志——正常运行时不噪音，需要排查"为什么我的 ai-intervention-agent
进程不释放连接 / FD"时打开 debug 立刻看到 root cause。

与项目"fail-loud, no silent skips"政策（cf. R107-R110 系列）一致：
资源清理失败比业务逻辑失败更隐蔽，更需要可观测性兜底。

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
