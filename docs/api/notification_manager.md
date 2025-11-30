# notification_manager

AI Intervention Agent - 通知管理器模块

【核心功能】
统一管理和调度多种通知渠道，为应用提供灵活的通知能力。

【支持的通知类型】
- Web 浏览器通知：利用 Web Notifications API 发送桌面通知
- 声音通知：播放提示音，支持音量控制和静音
- Bark 推送通知：适用于 iOS 设备的第三方推送服务
- 系统通知：利用操作系统原生通知机制

【架构设计】
- 单例模式：确保全局只有一个通知管理器实例，避免配置冲突
- 插件化提供者：通过注册机制动态加载不同的通知提供者
- 事件队列：异步处理通知事件，支持延迟和重复提醒
- 降级策略：当首选通知方式失败时自动切换备用方案

【使用场景】
- 任务完成或状态变更时提醒用户
- 错误和异常情况的即时告警
- 定期提醒用户处理待办事项
- 多设备同步通知（结合 Bark）

【线程安全】
- 所有公共方法均为线程安全
- 使用锁机制保护事件队列和配置更新
- 支持多线程并发发送通知

【配置管理】
- 从配置文件动态加载设置
- 支持运行时更新配置并持久化
- 提供细粒度的开关控制各类通知

## 类

### `class NotificationType`

通知类型枚举

定义系统支持的所有通知渠道类型。

【使用说明】
- 用于指定发送通知时使用的渠道
- 可以组合多种类型同时发送通知
- 每种类型对应一个通知提供者实现

【属性说明】
WEB: Web 浏览器通知
    - 使用浏览器的 Notification API
    - 需要用户授予通知权限
    - 支持标题、正文、图标和操作按钮
    - 仅在浏览器环境下可用

SOUND: 声音通知
    - 播放本地音频文件提示用户
    - 支持音量调节和静音控制
    - 适用于需要声音提醒的场景
    - 无需额外权限

BARK: Bark 推送通知
    - 第三方推送服务，主要用于 iOS 设备
    - 需要配置服务器 URL 和设备密钥
    - 支持富文本和自定义操作
    - 可穿透系统免打扰模式（取决于配置）

SYSTEM: 系统通知
    - 使用操作系统原生通知机制
    - 跨平台支持（Windows、macOS、Linux）
    - 外观和行为由操作系统决定
    - 需要系统权限

### `class NotificationTrigger`

通知触发时机枚举

定义通知在何时被发送给用户。

【使用说明】
- 控制通知的时间策略
- 支持组合使用（例如延迟后重复）
- 影响通知的发送时机和频率

【属性说明】
IMMEDIATE: 立即通知
    - 创建通知事件后立即发送
    - 适用于紧急或重要的通知
    - 无延迟，用户即时收到

DELAYED: 延迟通知
    - 在指定的延迟时间后发送
    - 延迟时长由配置 trigger_delay 决定（默认30秒）
    - 适用于非紧急但需要提醒的场景
    - 避免打扰用户当前操作

REPEAT: 重复提醒
    - 按固定间隔重复发送通知
    - 重复间隔由配置 trigger_repeat_interval 决定（默认60秒）
    - 适用于需要持续关注的任务
    - 需要配置 trigger_repeat 为 True 才生效

FEEDBACK_RECEIVED: 反馈收到时通知
    - 当系统收到用户反馈时触发
    - 用于确认用户的操作已被接收
    - 提供即时的交互反馈

ERROR: 错误时通知
    - 当系统发生错误或异常时触发
    - 优先级高，通常立即发送
    - 帮助用户快速响应问题
    - 可结合降级策略确保通知送达

### `class NotificationConfig`

通知配置类

集中管理所有通知相关的配置选项，支持细粒度控制。

【配置分类】
1. 全局开关：控制整个通知系统的启用状态
2. Web 通知：浏览器通知的行为设置
3. 声音通知：音频提示的音量和文件配置
4. 触发时机：延迟、重复提醒的时间控制
5. 错误处理：失败重试和降级策略
6. 移动优化：针对移动设备的特殊处理
7. Bark 推送：iOS 推送服务的连接配置

【线程安全】
- 数据类实例本身非线程安全
- 通过 NotificationManager 访问时受锁保护
- 不应直接修改字段，应使用 update_config 方法

【属性说明】
enabled: 通知总开关
    - 控制整个通知系统的启用状态
    - False 时所有通知都不会发送
    - 默认值：True

debug: 调试模式开关
    - 启用后输出详细的调试日志
    - 帮助排查通知发送失败的问题
    - 默认值：False

#### 方法

##### `from_config_file(cls) -> 'NotificationConfig'`

从配置文件创建配置实例

【功能说明】
从全局配置文件的 "notification" 部分读取配置，创建配置实例。

【处理逻辑】
1. 检查配置文件管理器是否可用
2. 从配置文件读取 "notification" 配置段
3. 映射配置键到数据类字段
4. 处理特殊值转换（如音量百分比转换为 0-1 范围）
5. 使用默认值填充缺失的配置项

【数据转换】
- sound_volume: 从百分比（0-100）转换为浮点数（0.0-1.0）
- auto_request_permission: 映射到 web_permission_auto_request

【错误处理】
- 配置管理器不可用时抛出异常并记录错误日志
- 不处理配置文件读取失败的异常，交由调用方处理

Returns:
    NotificationConfig: 从配置文件加载的配置实例

Raises:
    Exception: 配置文件管理器不可用时抛出异常

### `class NotificationEvent`

通知事件数据结构

封装一次通知请求的所有信息，包括内容、类型、触发时机和元数据。

【生命周期】
1. 创建：通过 send_notification 方法生成
2. 入队：添加到通知管理器的事件队列
3. 处理：由处理线程或定时器触发
4. 发送：分发到各个通知提供者
5. 完成/重试：根据发送结果决定是否重试

【重试机制】
- retry_count 记录已重试次数
- max_retries 限制最大重试次数
- 重试之间有延迟（由配置 retry_delay 控制）
- 超过最大重试次数后触发降级处理

【元数据用途】
- 存储额外的上下文信息
- 传递给通知提供者的自定义参数
- 记录通知的来源和关联数据
- 用于回调函数的参数传递

【属性说明】
id: 事件唯一标识符
    - 格式：notification_{时间戳毫秒}_{对象ID}
    - 用于追踪和日志记录

title: 通知标题
    - 显示在通知顶部的标题文本
    - 应简洁明了，一般不超过50个字符

message: 通知消息内容
    - 详细的通知正文
    - 支持多行文本
    - 某些通知类型可能支持 Markdown 或 HTML

trigger: 触发时机
    - 决定通知何时发送
    - 类型为 NotificationTrigger 枚举

types: 通知类型列表
    - 指定使用哪些通知渠道
    - 空列表时使用配置中启用的默认类型
    - 可同时发送到多个渠道

metadata: 元数据字典
    - 存储任意额外信息
    - 可包含图标、URL、操作按钮等配置

timestamp: 事件时间戳
    - 事件创建的 Unix 时间戳（秒）
    - 默认为当前时间
    - 用于计算延迟和排序

retry_count: 当前重试次数
    - 初始值为 0
    - 每次重试后递增
    - 不应手动修改

max_retries: 最大重试次数
    - 默认为 3 次
    - 可在创建事件时自定义
    - 继承自 NotificationConfig.retry_count

### `class NotificationManager`

通知管理器

【设计模式】
采用线程安全的单例模式，确保应用中只有一个通知管理器实例。

【核心职责】
1. 管理通知提供者：注册和维护各类通知渠道的实现
2. 事件队列管理：接收、排队和分发通知事件
3. 配置管理：动态加载和更新通知配置
4. 回调机制：支持事件监听和自定义回调
5. 错误处理：失败重试和降级策略

【线程安全】
- 双重检查锁定的单例实现
- 事件队列使用锁保护
- 配置更新操作线程安全
- 支持多线程并发调用

【使用方式】
直接使用模块级的全局实例 notification_manager，而非手动创建实例。

【关键特性】
- 插件化架构：通过 register_provider 动态注册通知提供者
- 异步处理：支持立即和延迟发送通知
- 多渠道发送：一次请求可同时发送到多个通知渠道
- 状态监控：提供 get_status 查询系统运行状态

#### 方法

##### `__init__(self)`

初始化通知管理器

【初始化流程】
1. 检查是否已初始化（防止重复初始化）
2. 从配置文件加载通知配置
3. 创建通知提供者字典
4. 初始化事件队列和队列锁
5. 准备工作线程和停止事件
6. 初始化回调函数字典
7. 根据调试模式设置日志级别

【数据结构】
- _providers: 通知提供者字典，键为 NotificationType，值为提供者实例
- _event_queue: 待处理的通知事件列表
- _queue_lock: 保护事件队列的线程锁
- _worker_thread: 后台工作线程（当前未使用，预留扩展）
- _stop_event: 用于停止后台线程的事件
- _callbacks: 事件回调字典，键为事件名，值为回调函数列表

【错误处理】
- 配置文件加载失败时抛出异常
- 异常会中断初始化并向上传播
- 调用方需要捕获并处理异常

【调试模式】
- 当 config.debug 为 True 时，设置日志级别为 DEBUG
- 输出详细的初始化和运行日志

Raises:
    Exception: 配置文件加载失败时抛出异常

##### `register_provider(self, notification_type: NotificationType, provider: Any)`

注册通知提供者

【功能说明】
将通知提供者实例注册到管理器，使其可用于发送通知。

【提供者要求】
- 必须实现 send(event: NotificationEvent) 方法
- send 方法应返回 bool 值表示成功或失败
- 应处理自身的异常，避免影响其他提供者
- 可选：实现额外的配置或初始化方法

【注册时机】
- 通常在应用启动时注册
- 可在运行时动态注册新提供者
- 重复注册会覆盖已有的提供者

【线程安全】
- 当前实现非线程安全，应在初始化阶段注册
- 运行时注册应由调用方确保同步

Args:
    notification_type: 通知类型枚举值
    provider: 通知提供者实例，需实现 send 方法

##### `add_callback(self, event_name: str, callback: Callable)`

添加事件回调

【功能说明】
注册一个回调函数，当特定事件发生时被调用。

【支持的事件】
- notification_sent: 通知发送完成（参数：event, success_count）
- notification_fallback: 触发降级处理（参数：event）
- 可自定义其他事件名

【回调执行】
- 回调函数在 trigger_callbacks 中被调用
- 按注册顺序依次执行
- 单个回调异常不影响其他回调
- 异常会被捕获并记录到日志

【回调签名】
- 接受任意位置参数和关键字参数
- 不应有返回值（返回值会被忽略）
- 应尽快执行，避免阻塞通知发送

【线程安全】
- 当前实现非线程安全
- 应在初始化阶段添加回调
- 运行时添加应由调用方确保同步

Args:
    event_name: 事件名称字符串
    callback: 回调函数，接受 (*args, **kwargs)

##### `trigger_callbacks(self, event_name: str)`

触发事件回调

【功能说明】
执行指定事件的所有已注册回调函数。

【执行流程】
1. 检查事件名是否存在注册的回调
2. 按注册顺序遍历回调列表
3. 依次调用每个回调函数
4. 捕获并记录回调中的异常
5. 继续执行后续回调

【异常处理】
- 单个回调异常不会中断其他回调
- 异常会被记录到错误日志
- 不向上传播异常

【参数传递】
- 位置参数和关键字参数透传给回调函数
- 回调函数需要自行处理参数类型和数量

【性能考虑】
- 在通知发送的关键路径上执行
- 回调应快速返回，避免阻塞
- 耗时操作应在回调内启动新线程

Args:
    event_name: 事件名称字符串
    *args: 传递给回调函数的位置参数
    **kwargs: 传递给回调函数的关键字参数

##### `send_notification(self, title: str, message: str, trigger: NotificationTrigger = NotificationTrigger.IMMEDIATE, types: Optional[List[NotificationType]] = None, metadata: Optional[Dict[str, Any]] = None) -> str`

发送通知

【功能说明】
创建通知事件并根据触发时机进行处理。这是通知系统的主入口方法。

【处理流程】
1. 检查通知总开关是否启用
2. 生成唯一的事件 ID
3. 确定通知类型列表（使用参数或配置默认值）
4. 创建 NotificationEvent 对象
5. 添加到事件队列
6. 根据触发时机立即处理或延迟处理

【通知类型选择】
- 如果 types 参数为 None，根据配置自动选择：
  * web_enabled 时添加 WEB
  * sound_enabled 且未静音时添加 SOUND
  * bark_enabled 时添加 BARK
- 如果 types 为空列表，不发送任何通知
- 可手动指定一个或多个通知类型

【触发时机处理】
- IMMEDIATE: 在当前线程立即处理
- DELAYED: 使用 threading.Timer 延迟处理
- 其他触发类型：仅入队，不自动处理

【事件 ID 格式】
notification_{毫秒时间戳}_{对象ID}

【线程安全】
- 事件队列操作受锁保护
- 可从多线程安全调用

Args:
    title: 通知标题，建议不超过 50 字符
    message: 通知消息内容，支持多行文本
    trigger: 触发时机枚举，默认为立即触发
    types: 通知类型列表，None 时使用配置的默认类型
    metadata: 元数据字典，传递额外参数给通知提供者

Returns:
    str: 事件 ID，用于追踪通知。如果通知被禁用则返回空字符串

##### `get_config(self) -> NotificationConfig`

获取当前配置

【功能说明】
返回当前生效的通知配置对象。

【返回值特性】
- 返回实际的配置对象引用，而非副本
- 直接修改返回的对象会影响内部状态
- 建议仅用于读取配置，修改应使用 update_config 方法

【使用场景】
- 读取当前配置值
- 序列化配置到 JSON/API 响应
- 在 UI 中展示配置信息
- 日志记录和调试

【线程安全】
- 获取引用本身是线程安全的
- 读取配置字段值也是线程安全的（Python 读取是原子操作）
- 直接修改字段不是线程安全的，请使用 update_config

Returns:
    NotificationConfig: 当前通知配置对象

##### `refresh_config_from_file(self, force: bool = False)`

从配置文件重新加载配置（跨进程同步）

【功能说明】
从配置文件读取最新配置并更新内存中的配置对象。
解决 Web UI 子进程和 MCP 服务器主进程之间配置不同步的问题。

【参数】
force : bool, optional
    是否强制刷新配置（跳过缓存检查），默认 False

【设计背景】
- Web UI 以子进程方式运行（subprocess.Popen）
- Web UI 和 MCP 服务器各自有独立的 notification_manager 实例
- 用户在 Web UI 上更改配置时，只更新了 Web UI 进程的配置和配置文件
- MCP 服务器进程的内存配置不会自动更新
- 此方法用于 MCP 服务器进程在发送通知前同步最新配置

【处理流程】
1. 检查配置文件管理器是否可用
2. 从配置文件读取 notification 配置段
3. 记录更新前的 bark_enabled 状态
4. 更新 self.config 的所有字段（带类型验证）
5. 如果 bark_enabled 状态发生变化，动态更新 Bark 提供者

【配置字段映射】
- enabled: 通知总开关
- web_enabled: Web 通知开关
- web_permission_auto_request: 自动请求权限（对应配置文件中的 auto_request_permission）
- sound_enabled: 声音通知开关
- sound_volume: 音量（配置文件中是 0-100，内存中是 0.0-1.0）
- sound_mute: 静音开关
- mobile_optimized: 移动优化开关
- mobile_vibrate: 震动开关
- bark_enabled: Bark 通知开关
- bark_url: Bark 服务器 URL
- bark_device_key: Bark 设备密钥
- bark_icon: Bark 图标 URL
- bark_action: Bark 点击动作

【Bark 动态更新】
- 如果 bark_enabled 从 False 变为 True，自动添加 Bark 提供者
- 如果 bark_enabled 从 True 变为 False，自动移除 Bark 提供者

【使用场景】
- server.py 中发送通知前调用，确保使用最新配置
- 适用于任何需要跨进程同步配置的场景

【异常处理】
- 配置文件管理器不可用时静默返回（不抛出异常）
- 配置读取失败时记录警告日志并返回
- 配置值类型错误时使用默认值
- 不影响正常通知流程

【线程安全】
- 使用 _config_lock 保护配置更新操作
- 确保配置读写的原子性，避免并发不一致
- 锁粒度：方法级别，保护整个配置更新过程

【性能优化】
- 使用文件修改时间（mtime）作为缓存键
- 只有文件修改时间变化时才重新读取配置
- force=True 时跳过缓存检查，强制刷新

##### `update_config(self)`

更新配置并保存到文件

【功能说明】
更新通知配置并立即持久化到配置文件。

【处理流程】
1. 调用 update_config_without_save 更新内存中的配置
2. 调用 _save_config_to_file 保存到配置文件

【配置生效】
- 配置立即在内存中生效
- 持久化确保重启后配置保留
- Bark 提供者会根据配置变化动态更新

【支持的配置项】
可以更新 NotificationConfig 数据类中的任意字段，常用的包括：
- enabled: 启用/禁用通知
- web_enabled, sound_enabled, bark_enabled: 各渠道开关
- sound_volume: 音量大小（0.0-1.0）
- sound_mute: 静音开关
- bark_url, bark_device_key: Bark 服务配置

【批量更新】
- 支持同时更新多个配置项
- 未指定的配置项保持不变
- 所有更新在一次文件写入中完成

【线程安全】
- 当前实现非线程安全
- 并发更新可能导致配置丢失
- 应由调用方确保同步

Args:
    **kwargs: 要更新的配置键值对，键为 NotificationConfig 的字段名

##### `update_config_without_save(self)`

更新配置但不保存到文件

【功能说明】
仅在内存中更新配置，不写入配置文件，适用于批量更新或临时修改。

【使用场景】
- 批量更新多个配置项，最后一次性保存
- 临时更改配置进行测试
- 频繁更新配置时减少磁盘 I/O
- 从外部配置源同步时先更新内存再统一保存

【处理流程】
1. 记录 Bark 启用状态（用于检测变化）
2. 遍历所有传入的配置项
3. 验证配置项是否存在于 NotificationConfig
4. 使用 setattr 更新配置值
5. 记录每个配置项的更新日志
6. 检测 Bark 配置是否变化
7. 如果 Bark 启用状态改变，动态更新提供者

【Bark 动态更新】
- 当 bark_enabled 从 False 变为 True 时，自动添加 Bark 提供者
- 当 bark_enabled 从 True 变为 False 时，自动移除 Bark 提供者
- 其他 Bark 配置（url、key）变化时需手动重启提供者

【配置验证】
- 仅更新 NotificationConfig 中存在的字段
- 不存在的字段会被静默忽略（不报错）
- 不进行值类型验证，由 Python 类型系统保障

【线程安全】
- 使用 _config_lock 保护配置更新操作
- 确保配置读写的原子性，避免并发不一致
- 锁粒度：方法级别，保护整个配置更新过程

Args:
    **kwargs: 要更新的配置键值对，键为 NotificationConfig 的字段名

##### `shutdown(self)`

关闭通知管理器

【功能说明】
优雅地关闭线程池，等待所有正在执行的通知任务完成。

【调用时机】
- 应用关闭时
- 重置通知管理器时

【处理流程】
1. 调用线程池的 shutdown 方法
2. 等待所有任务完成（wait=True）
3. 记录关闭日志

【线程安全】
- shutdown 方法本身是线程安全的
- 多次调用是安全的（幂等操作）

##### `get_status(self) -> Dict[str, Any]`

获取通知管理器状态

【功能说明】
返回当前通知系统的运行状态和配置信息，用于监控和调试。

【返回信息】
- enabled: 通知总开关状态
- providers: 已注册的通知提供者类型列表
- queue_size: 当前事件队列中的事件数量
- config: 关键配置项的快照

【队列大小】
- 通过锁保护访问事件队列
- 返回瞬时队列大小（可能在返回后立即变化）
- 队列大小持续增长可能表示处理速度不足或有问题

【提供者列表】
- 返回 NotificationType 枚举值的列表
- 列表顺序不保证
- 可用于检查某个通知类型是否可用

【配置快照】
- 仅包含关键配置项（各渠道的启用状态）
- 不包含敏感信息（如 Bark 密钥）
- 可安全用于 API 响应或日志记录

【使用场景】
- 健康检查接口
- 管理后台状态展示
- 日志记录和监控
- 调试通知系统问题

【线程安全】
- 队列大小查询受锁保护
- 其他字段读取是线程安全的

Returns:
    Dict[str, Any]: 状态信息字典，包含以下键：
        - enabled (bool): 通知是否启用
        - providers (List[NotificationType]): 已注册的通知提供者列表
        - queue_size (int): 事件队列大小
        - config (Dict[str, bool]): 当前配置详情
