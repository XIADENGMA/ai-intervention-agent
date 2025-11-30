# notification_providers

AI Intervention Agent - 通知提供者实现

功能概述
--------
提供多种通知方式的具体实现，实现通知发送的插件化架构。

支持的通知方式
--------------
1. **Web 浏览器通知**: 通过 Web Notification API 发送桌面通知
2. **声音通知**: 通过 Web Audio API 播放提示音
3. **Bark 推送通知**: iOS 推送通知服务（支持 iPhone、iPad）
4. **系统通知**: 操作系统级别的通知（需要 plyer 库支持）

主要组件
--------
- WebNotificationProvider: Web 浏览器通知提供者
- SoundNotificationProvider: 声音通知提供者
- BarkNotificationProvider: Bark 推送通知提供者
- SystemNotificationProvider: 系统通知提供者（可选）
- create_notification_providers: 工厂函数（根据配置创建提供者）
- initialize_notification_system: 初始化函数（集成到通知管理器）

提供者接口
----------
所有提供者都实现 send(event: NotificationEvent) -> bool 方法：
- 参数: NotificationEvent（包含标题、消息、时间戳、元数据）
- 返回: bool（是否成功发送）

设计模式
--------
- **策略模式**: 每种通知方式是一个独立的策略
- **工厂模式**: create_notification_providers 根据配置创建实例
- **插件架构**: 提供者通过 register_provider 注册到通知管理器

配置驱动
--------
所有提供者的行为由 NotificationConfig 控制：
- 启用/禁用开关（web_enabled、sound_enabled、bark_enabled）
- 参数配置（音量、超时、图标、URL 等）
- 移动端优化（mobile_optimized、mobile_vibrate）

数据流
------
1. 通知管理器创建 NotificationEvent
2. 调用提供者的 send() 方法
3. 提供者准备通知数据并存储到 event.metadata
4. 前端轮询或接收通知数据并展示

使用场景
--------
- MCP 服务器反馈请求通知
- 长时间等待提示
- 错误和警告通知
- 任务完成提醒

扩展性
------
添加新的通知方式只需：
1. 创建新的提供者类，实现 send() 方法
2. 在 NotificationType 枚举中添加新类型
3. 在 create_notification_providers 中创建实例

注意事项
--------
- Web 和声音通知依赖前端实现
- Bark 通知需要网络连接和有效的设备密钥
- 系统通知需要 plyer 库（可选依赖）
- 所有提供者都应捕获异常并返回 bool 状态

依赖
----
- requests: HTTP 请求（Bark 通知）
- plyer: 系统通知（可选）
- enhanced_logging: 增强日志
- notification_manager: 通知管理器和事件模型

## 函数

### `create_notification_providers(config) -> Dict[NotificationType, Any]`

创建所有通知提供者（工厂函数）

参数
----
config : NotificationConfig
    通知配置对象

返回
----
Dict[NotificationType, Any]
    通知类型枚举到提供者实例的映射字典

功能
----
根据配置中的启用开关，创建相应的通知提供者实例并返回字典。

创建流程
--------
1. 初始化空字典 providers = {}
2. 检查 config.web_enabled，创建 WebNotificationProvider
3. 检查 config.sound_enabled，创建 SoundNotificationProvider
4. 检查 config.bark_enabled，创建 BarkNotificationProvider
5. 尝试创建 SystemNotificationProvider（可选，需 plyer）
6. 返回 providers 字典

提供者映射
----------
{
    NotificationType.WEB: WebNotificationProvider(config),
    NotificationType.SOUND: SoundNotificationProvider(config),
    NotificationType.BARK: BarkNotificationProvider(config),
    NotificationType.SYSTEM: SystemNotificationProvider(config)  # 可选
}

配置开关
--------
- web_enabled: 是否创建 WebNotificationProvider
- sound_enabled: 是否创建 SoundNotificationProvider
- bark_enabled: 是否创建 BarkNotificationProvider
- SystemNotificationProvider: 始终尝试创建，但可能不支持

异常处理
--------
SystemNotificationProvider 创建失败时捕获异常，不影响其他提供者。

日志记录
--------
- 每个提供者创建后记录 logger.debug
- 最后记录创建的提供者总数 logger.info

使用场景
--------
- 通知系统初始化
- 动态创建提供者（根据配置）
- 测试和开发环境

注意事项
--------
- 禁用的提供者不会创建
- SystemNotificationProvider 可能不支持（plyer 未安装）
- 返回的字典可能为空（所有提供者都禁用）

### `initialize_notification_system(config)`

初始化通知系统（集成函数）

参数
----
config : NotificationConfig
    通知配置对象

返回
----
NotificationManager
    初始化后的通知管理器实例（已注册所有提供者）

功能
----
创建所有通知提供者并注册到通知管理器，完成通知系统的初始化。

初始化流程
----------
1. 导入 notification_manager（单例）
2. 调用 create_notification_providers(config) 创建提供者
3. 遍历提供者字典，调用 notification_manager.register_provider()
4. 记录日志
5. 返回 notification_manager 实例

注册流程
--------
对于 providers 字典中的每个 (notification_type, provider)：
- 调用 notification_manager.register_provider(notification_type, provider)
- 提供者被注册到通知管理器

日志记录
--------
logger.info("通知系统初始化完成")

使用场景
--------
- 应用启动时初始化通知系统
- 配置更新后重新初始化
- 测试环境初始化

典型调用
--------
通常在应用启动时调用：
1. 加载 config（通过 ConfigManager）
2. 调用 initialize_notification_system(config.notification)
3. 使用返回的 notification_manager 发送通知

注意事项
--------
- notification_manager 是全局单例
- 多次调用会覆盖之前注册的提供者
- 确保在使用通知功能前调用此函数

## 类

### `class WebNotificationProvider`

Web 浏览器通知提供者

功能概述
--------
通过 Web Notification API 发送桌面通知，支持客户端注册、通知数据准备、
移动端优化等功能。

实现方式
--------
- 不直接推送通知到浏览器（无 WebSocket）
- 准备通知数据存储到 event.metadata
- 前端通过轮询 /api/content 端点获取通知数据
- 前端调用 Web Notification API 展示通知

内部状态
--------
- config: NotificationConfig 配置对象
- web_clients: 已注册的 Web 客户端字典（client_id -> {info, last_seen}）

配置参数
--------
- web_enabled: 是否启用 Web 通知
- web_icon: 通知图标 URL
- web_timeout: 通知超时时间（毫秒）
- web_permission_auto_request: 是否自动请求通知权限
- mobile_optimized: 是否启用移动端优化
- mobile_vibrate: 是否启用震动

客户端管理
----------
- register_client: 注册 Web 客户端（记录 client_id 和 last_seen）
- unregister_client: 注销 Web 客户端
- web_clients 可用于追踪活跃客户端数量

通知数据结构
------------
准备的通知数据包含：
- id: 通知事件 ID
- type: "notification"
- title: 通知标题
- message: 通知消息
- timestamp: 时间戳
- config: 通知配置（图标、超时、权限、移动优化）
- metadata: 事件元数据

使用场景
--------
- MCP 服务器反馈请求通知
- 长时间等待提示
- 任务完成提醒

注意事项
--------
- 需要浏览器支持 Web Notification API
- 需要用户授权通知权限
- 移动端浏览器支持有限
- 通知数据通过 event.metadata 传递，不存储在内存中

#### 方法

##### `__init__(self, config)`

初始化 Web 通知提供者

参数
----
config : NotificationConfig
    通知配置对象

初始化流程
----------
1. 保存配置对象
2. 初始化空的 web_clients 字典

内部状态
--------
- config: 通知配置
- web_clients: 空字典（client_id -> {info, last_seen}）

##### `register_client(self, client_id: str, client_info: Dict[str, Any])`

注册 Web 客户端

参数
----
client_id : str
    客户端唯一标识（如 UUID）
client_info : Dict[str, Any]
    客户端信息字典（如浏览器信息、IP 地址）

功能
----
将客户端信息存储到 web_clients 字典，记录注册时间。

存储结构
--------
{client_id: {"info": client_info, "last_seen": time.time()}}

使用场景
--------
- 前端页面加载时注册
- WebSocket 连接建立时注册

注意事项
--------
- 当前实现不主动推送，注册主要用于追踪活跃客户端
- last_seen 可用于清理长时间未活跃的客户端

##### `unregister_client(self, client_id: str)`

注销 Web 客户端

参数
----
client_id : str
    客户端唯一标识

功能
----
从 web_clients 字典中删除客户端信息。

使用场景
--------
- 前端页面关闭时注销
- WebSocket 连接断开时注销
- 定期清理长时间未活跃的客户端

注意事项
--------
- 如果 client_id 不存在，静默忽略（不抛出异常）

##### `send(self, event: NotificationEvent) -> bool`

发送 Web 通知（准备通知数据）

参数
----
event : NotificationEvent
    通知事件对象（包含标题、消息、时间戳、元数据）

返回
----
bool
    True: 成功准备通知数据
    False: 准备失败（异常）

功能
----
构建通知数据并存储到 event.metadata["web_notification_data"]，
供前端轮询获取。

通知数据结构
------------
{
    "id": event.id,
    "type": "notification",
    "title": event.title,
    "message": event.message,
    "timestamp": event.timestamp,
    "config": {
        "icon": web_icon,
        "timeout": web_timeout,
        "auto_request_permission": bool,
        "mobile_optimized": bool,
        "mobile_vibrate": bool
    },
    "metadata": event.metadata
}

数据流
------
1. 构建通知数据字典
2. 存储到 event.metadata["web_notification_data"]
3. 前端轮询 /api/content 获取 metadata
4. 前端调用 Web Notification API 展示通知

异常处理
--------
捕获所有异常，记录日志并返回 False。

注意事项
--------
- 不直接发送通知到浏览器（无 WebSocket）
- 通知数据通过 event.metadata 传递
- 前端需要实现轮询和通知展示逻辑
- 避免循环引用：先深拷贝metadata再添加到notification_data
- 验证标题/消息非空，验证web_timeout > 0

### `class SoundNotificationProvider`

声音通知提供者

功能概述
--------
通过 Web Audio API 播放提示音，支持音量控制、静音模式、自定义音频文件。

实现方式
--------
- 准备声音通知数据存储到 event.metadata
- 前端通过轮询获取声音数据
- 前端调用 Web Audio API 播放音频

内部状态
--------
- config: NotificationConfig 配置对象
- sound_files: 音频文件映射字典（名称 -> 文件名）

配置参数
--------
- sound_enabled: 是否启用声音通知
- sound_mute: 是否静音
- sound_volume: 音量（0.0-1.0）
- sound_file: 音频文件名（如 "deng"）

音频文件
--------
当前支持：
- "default": deng[噔].mp3（默认提示音）
- "deng": deng[噔].mp3

扩展支持：
在 sound_files 字典中添加新条目。

声音数据结构
------------
准备的声音数据包含：
- id: 通知事件 ID
- type: "sound"
- file: 音频文件名
- volume: 音量（0.0-1.0）
- timestamp: 时间戳
- metadata: 事件元数据

使用场景
--------
- 反馈请求提示音
- 任务完成提示
- 错误警告音

注意事项
--------
- 音频文件路径相对于 static/sounds/ 目录
- 静音模式（sound_mute）仍返回 True，但不播放
- 前端需要处理浏览器自动播放策略（需用户交互）

#### 方法

##### `__init__(self, config)`

初始化声音通知提供者

参数
----
config : NotificationConfig
    通知配置对象

初始化流程
----------
1. 保存配置对象
2. 初始化 sound_files 字典（音频文件映射）

音频文件映射
------------
{
    "default": "deng[噔].mp3",
    "deng": "deng[噔].mp3"
}

扩展
----
添加新音频文件只需在 sound_files 中添加条目。

##### `send(self, event: NotificationEvent) -> bool`

发送声音通知（准备声音数据）

参数
----
event : NotificationEvent
    通知事件对象

返回
----
bool
    True: 成功准备声音数据或静音模式
    False: 准备失败（异常）

功能
----
构建声音数据并存储到 event.metadata["sound_notification_data"]，
供前端轮询获取。

处理流程
--------
1. 检查静音模式（sound_mute）
   - 如果静音，跳过准备，返回 True
2. 获取音频文件名（从 sound_files 映射）
3. 构建声音数据字典
4. 存储到 event.metadata["sound_notification_data"]

声音数据结构
------------
{
    "id": event.id,
    "type": "sound",
    "file": sound_file,
    "volume": sound_volume,
    "timestamp": event.timestamp,
    "metadata": event.metadata
}

音频文件查找
------------
- 从 sound_files 中查找 config.sound_file
- 如果未找到，使用 "default"

异常处理
--------
捕获所有异常，记录日志并返回 False。

注意事项
--------
- 静音模式返回 True（不视为失败）
- 音频文件路径相对于 static/sounds/ 目录
- 音量范围限制在0.0-1.0（后端验证）
- 避免循环引用：先深拷贝metadata再添加到sound_data

### `class BarkNotificationProvider`

Bark 推送通知提供者

功能概述
--------
iOS 推送通知服务，通过 HTTP POST 请求发送通知到 Bark 服务器，
支持自定义图标、动作、元数据等高级功能。

实现方式
--------
- 通过 HTTP POST 请求发送通知到 Bark 服务器
- 使用 requests.Session 进行连接池管理和重试
- 支持自动序列化复杂元数据（列表、字典）

内部状态
--------
- config: NotificationConfig 配置对象
- session: requests.Session（连接池，3 次重试）

配置参数
--------
- bark_enabled: 是否启用 Bark 通知
- bark_url: Bark 服务器 URL
- bark_device_key: 设备密钥（必需）
- bark_icon: 通知图标 URL（可选）
- bark_action: 点击通知时的动作 URL（可选）

Bark 数据结构
-------------
发送到 Bark 服务器的数据包含：
- title: 通知标题
- body: 通知消息
- device_key: 设备密钥
- icon: 图标 URL（可选）
- action: 动作 URL（可选）
- ...: event.metadata 中的其他字段（自动序列化）

元数据序列化
------------
event.metadata 中的字段会自动添加到 Bark 数据中：
- str, int, float, bool, None: 直接添加
- list, dict: 尝试 JSON 序列化，失败则转为字符串
- 其他类型: 转为字符串

HTTP 配置
---------
- 超时: 10 秒
- 重试: 最多 3 次（通过 HTTPAdapter）
- User-Agent: "AI-Intervention-Agent"
- Content-Type: "application/json"

使用场景
--------
- iOS 设备推送通知
- 移动端反馈请求提醒
- 远程任务完成通知

注意事项
--------
- 需要有效的 bark_url 和 bark_device_key
- 需要网络连接
- 元数据序列化可能失败（会转为字符串）
- 建议在配置中设置合理的 URL 和设备密钥

#### 方法

##### `__init__(self, config)`

初始化 Bark 通知提供者

参数
----
config : NotificationConfig
    通知配置对象

初始化流程
----------
1. 保存配置对象
2. 创建 requests.Session（连接池）
3. 配置 HTTPAdapter（最多 3 次重试）
4. 挂载适配器到 http:// 和 https://
5. 配置默认 HTTP headers

连接池配置
----------
- HTTPAdapter(max_retries=3): 自动重试最多 3 次
- 适用于 HTTP 和 HTTPS

性能优化
--------
- 使用 Session 复用连接，减少 TCP 握手开销
- 预设 HTTP headers，避免每次请求重复创建

##### `send(self, event: NotificationEvent) -> bool`

发送 Bark 通知

参数
----
event : NotificationEvent
    通知事件对象（包含标题、消息、时间戳、元数据）

返回
----
bool
    True: 成功发送通知（HTTP 200）
    False: 发送失败（禁用、配置不完整、网络错误、HTTP 错误）

功能
----
通过 HTTP POST 请求发送通知到 Bark 服务器。

处理流程
--------
1. 检查 bark_enabled（如果禁用，返回 False）
2. 检查配置完整性（bark_url 和 bark_device_key）
3. 构建 Bark 数据字典（title、body、device_key、icon、action）
4. 序列化 event.metadata 并合并到 Bark 数据
5. 发送 HTTP POST 请求到 bark_url
6. 检查响应状态码（200 为成功）

Bark 数据结构
-------------
{
    "title": event.title,
    "body": event.message,
    "device_key": bark_device_key,
    "icon": bark_icon (可选),
    "action": bark_action (可选),
    ...: event.metadata 中的其他字段
}

元数据序列化规则
----------------
- str, int, float, bool, None: 直接添加
- list, dict: 尝试 JSON 序列化（验证可序列化性）
   - 成功: 直接添加
   - 失败: 转为字符串
- 其他类型: 转为字符串

HTTP 请求配置
-------------
- URL: self.config.bark_url
- Method: POST
- Data: JSON 格式的 Bark 数据
- Timeout: 10 秒
- Headers:
  - Content-Type: application/json
  - User-Agent: AI-Intervention-Agent

异常处理
--------
- requests.exceptions.Timeout: 超时
- requests.exceptions.RequestException: 网络错误
- Exception: 其他异常
- 所有异常都会记录日志并返回 False

注意事项
--------
- bark_url 和 bark_device_key 必须配置
- 元数据序列化可能失败（会转为字符串）
- 网络请求可能失败或超时
- HTTP 状态码非 200 视为失败

### `class SystemNotificationProvider`

系统通知提供者

功能概述
--------
操作系统级别的桌面通知，通过 plyer 库实现跨平台通知功能。

实现方式
--------
- 使用 plyer 库（可选依赖）
- 支持 Windows、macOS、Linux 等操作系统
- 通过 plyer.notification.notify() 发送通知

内部状态
--------
- config: NotificationConfig 配置对象
- plyer: plyer 模块（如果可用）
- supported: 是否支持系统通知（bool）

配置参数
--------
- web_timeout: 通知超时时间（毫秒，转换为秒）

依赖
----
- plyer: 跨平台通知库（可选）
  - 安装: pip install plyer
  - 不安装则 supported 为 False

支持的平台
----------
- Windows: 通过 Windows 10 通知中心
- macOS: 通过 Notification Center
- Linux: 通过 libnotify（需要 D-Bus）

通知数据
--------
发送到系统的通知包含：
- title: 通知标题
- message: 通知消息
- app_name: "AI Intervention Agent"
- timeout: 超时时间（秒）

使用场景
--------
- 桌面应用通知
- 跨平台通知支持
- 服务器端通知（如果有桌面环境）

注意事项
--------
- plyer 是可选依赖，未安装则不支持
- Linux 需要 D-Bus 和 libnotify
- 服务器环境可能无法使用（无桌面环境）
- 不支持时返回 False（不视为错误）

#### 方法

##### `__init__(self, config)`

初始化系统通知提供者

参数
----
config : NotificationConfig
    通知配置对象

初始化流程
----------
1. 保存配置对象
2. 调用 _check_system_support() 检查 plyer 库支持

支持检查
--------
尝试导入 plyer 库，设置 self.supported 状态。

##### `send(self, event: NotificationEvent) -> bool`

发送系统通知

参数
----
event : NotificationEvent
    通知事件对象（包含标题、消息、时间戳、元数据）

返回
----
bool
    True: 成功发送通知
    False: 不支持或发送失败

功能
----
使用 plyer.notification.notify() 发送操作系统级别的通知。

处理流程
--------
1. 检查 self.supported（如果不支持，返回 False）
2. 调用 plyer.notification.notify() 发送通知
3. 记录日志

通知参数
--------
- title: event.title
- message: event.message
- app_name: "AI Intervention Agent"
- timeout: 从 web_timeout（毫秒）转为秒，最小 1.0 秒

异常处理
--------
捕获所有异常，记录日志并返回 False。

注意事项
--------
- 不支持时返回 False（不视为错误）
- 使用浮点除法保留小数精度
- 限制最小值为1.0秒，避免通知立即消失
- 平台支持可能受限（如无桌面环境）
