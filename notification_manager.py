#!/usr/bin/env python3
"""
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
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

try:
    from config_manager import get_config

    CONFIG_FILE_AVAILABLE = True
except ImportError:
    CONFIG_FILE_AVAILABLE = False

from config_utils import clamp_dataclass_field, validate_enum_value
from enhanced_logging import EnhancedLogger

# 注意：BarkNotificationProvider 使用延迟导入，避免循环导入问题
# notification_manager.py <-> notification_providers.py 存在相互依赖
# 延迟导入在 _update_bark_provider() 方法中实现

logger = EnhancedLogger(__name__)


class NotificationType(Enum):
    """通知类型枚举

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
    """

    WEB = "web"
    SOUND = "sound"
    BARK = "bark"
    SYSTEM = "system"


class NotificationTrigger(Enum):
    """通知触发时机枚举

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
    """

    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    REPEAT = "repeat"
    FEEDBACK_RECEIVED = "feedback_received"
    ERROR = "error"


@dataclass
class NotificationConfig:
    """通知配置类

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
    """

    # ==================== 全局开关 ====================
    enabled: bool = True  # 通知总开关
    debug: bool = False  # 调试模式

    # ==================== Web 通知配置 ====================
    web_enabled: bool = True  # 启用 Web 浏览器通知
    web_permission_auto_request: bool = True  # 自动请求通知权限
    web_icon: str = "default"  # 通知图标（"default" 或自定义 URL）
    web_timeout: int = 5000  # 通知显示时长（毫秒）

    # ==================== 声音通知配置 ====================
    sound_enabled: bool = True  # 启用声音通知
    sound_volume: float = 0.8  # 音量大小（0.0 - 1.0）
    sound_file: str = "default"  # 音频文件名或路径
    sound_mute: bool = False  # 静音模式（禁用所有声音）

    # ==================== 触发时机配置 ====================
    trigger_immediate: bool = True  # 支持立即触发
    trigger_delay: int = 30  # 延迟通知的等待时间（秒）
    trigger_repeat: bool = False  # 启用重复提醒
    trigger_repeat_interval: int = 60  # 重复提醒的间隔时间（秒）

    # ==================== 错误处理配置 ====================
    retry_count: int = 3  # 发送失败时的最大重试次数
    retry_delay: int = 2  # 重试之间的等待时间（秒）
    fallback_enabled: bool = True  # 启用降级策略（所有方式失败时）

    # ==================== 移动设备优化 ====================
    mobile_optimized: bool = True  # 启用移动设备优化
    mobile_vibrate: bool = True  # 移动设备震动反馈

    # ==================== Bark 通知配置（可选）====================
    bark_enabled: bool = False  # 启用 Bark 推送通知
    bark_url: str = ""  # Bark 服务器 URL
    bark_device_key: str = ""  # Bark 设备密钥
    bark_icon: str = ""  # Bark 通知图标 URL
    bark_action: str = "none"  # Bark 通知点击动作
    bark_timeout: int = 10  # Bark 请求超时（秒）

    # ==================== 边界常量 ====================
    SOUND_VOLUME_MIN: float = 0.0
    SOUND_VOLUME_MAX: float = 1.0
    BARK_ACTIONS_VALID: tuple = ("none", "url", "copy")

    def __post_init__(self):
        """
        数据类初始化后的验证钩子

        验证项
        ------
        1. sound_volume: 范围 [0.0, 1.0]
        2. bark_action: 有效值 none/url/copy
        3. bark_url: 非空时验证 URL 格式
        4. retry_count / retry_delay / bark_timeout: 合理范围限制

        【重构】使用 config_utils 辅助函数简化边界检查和枚举验证。
        """
        # 【重构】使用 clamp_dataclass_field 简化 sound_volume 边界验证
        clamp_dataclass_field(
            self, "sound_volume", self.SOUND_VOLUME_MIN, self.SOUND_VOLUME_MAX
        )

        # 先将可能的字符串值转为数值，再做范围限制（避免比较时报 TypeError）
        try:
            object.__setattr__(self, "retry_count", int(self.retry_count))
        except (TypeError, ValueError):
            object.__setattr__(self, "retry_count", 3)
        try:
            object.__setattr__(self, "retry_delay", int(self.retry_delay))
        except (TypeError, ValueError):
            object.__setattr__(self, "retry_delay", 2)
        try:
            object.__setattr__(self, "bark_timeout", int(self.bark_timeout))
        except (TypeError, ValueError):
            object.__setattr__(self, "bark_timeout", 10)

        clamp_dataclass_field(self, "retry_count", 0, 10)
        clamp_dataclass_field(self, "retry_delay", 0, 60)
        clamp_dataclass_field(self, "bark_timeout", 1, 300)

        # 【重构】使用 validate_enum_value 简化 bark_action 枚举验证
        validated_action = validate_enum_value(
            self.bark_action, self.BARK_ACTIONS_VALID, "bark_action", "none"
        )
        if validated_action != self.bark_action:
            object.__setattr__(self, "bark_action", validated_action)

        # bark_url 格式验证（非空时）
        if self.bark_url:
            if not self._is_valid_url(self.bark_url):
                logger.warning(
                    f"bark_url '{self.bark_url}' 格式无效，应以 http:// 或 https:// 开头"
                )
                # 不自动清空，只警告（用户可能故意使用自定义协议）

        # bark_enabled 时检查必要配置
        if self.bark_enabled and not self.bark_device_key:
            logger.warning(
                "bark_enabled=True 但 bark_device_key 为空，Bark 通知将无法发送"
            )

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """验证 URL 格式是否有效"""
        return url.startswith("http://") or url.startswith("https://")

    @classmethod
    def from_config_file(cls) -> "NotificationConfig":
        """从配置文件创建配置实例

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
        """
        if not CONFIG_FILE_AVAILABLE:
            logger.error("配置文件管理器不可用，无法初始化通知配置")
            raise Exception("配置文件管理器不可用")

        config_mgr = get_config()
        notification_config = config_mgr.get_section("notification")

        # 【优化】sound_volume 从百分比转换为 0-1 范围，并限制边界
        raw_volume = notification_config.get("sound_volume", 80)
        # 确保是数字类型
        try:
            raw_volume = float(raw_volume)
        except (ValueError, TypeError):
            logger.warning(f"sound_volume '{raw_volume}' 类型无效，使用默认值 80")
            raw_volume = 80
        # 限制百分比范围 [0, 100]
        raw_volume = max(0, min(100, raw_volume))
        normalized_volume = raw_volume / 100.0

        def safe_int(value: Any, default: int, min_val: int, max_val: int) -> int:
            try:
                iv = int(value)
            except (TypeError, ValueError):
                return default
            return max(min_val, min(max_val, iv))

        retry_count = safe_int(notification_config.get("retry_count", 3), 3, 0, 10)
        retry_delay = safe_int(notification_config.get("retry_delay", 2), 2, 0, 60)
        bark_timeout = safe_int(notification_config.get("bark_timeout", 10), 10, 1, 300)

        return cls(
            enabled=bool(notification_config.get("enabled", True)),
            debug=bool(notification_config.get("debug", False)),
            web_enabled=bool(notification_config.get("web_enabled", True)),
            web_permission_auto_request=bool(
                notification_config.get("auto_request_permission", True)
            ),
            sound_enabled=bool(notification_config.get("sound_enabled", True)),
            sound_volume=normalized_volume,
            sound_mute=bool(notification_config.get("sound_mute", False)),
            mobile_optimized=bool(notification_config.get("mobile_optimized", True)),
            mobile_vibrate=bool(notification_config.get("mobile_vibrate", True)),
            retry_count=retry_count,
            retry_delay=retry_delay,
            bark_enabled=bool(notification_config.get("bark_enabled", False)),
            bark_url=str(notification_config.get("bark_url", "")),
            bark_device_key=str(notification_config.get("bark_device_key", "")),
            bark_icon=str(notification_config.get("bark_icon", "")),
            bark_action=str(notification_config.get("bark_action", "none")),
            bark_timeout=bark_timeout,
        )


@dataclass
class NotificationEvent:
    """通知事件数据结构

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
    """

    id: str
    title: str
    message: str
    trigger: NotificationTrigger
    types: List[NotificationType] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3


class NotificationManager:
    """通知管理器

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
    """

    _instance = None  # 单例实例
    _lock = threading.Lock()  # 单例创建锁

    def __new__(cls):
        """创建单例实例（双重检查锁定）

        【实现细节】
        - 第一次检查：避免不必要的锁竞争
        - 加锁保护：确保只创建一个实例
        - 第二次检查：防止多线程竞态条件
        - 初始化标志：防止 __init__ 重复执行

        Returns:
            NotificationManager: 唯一的管理器实例
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化通知管理器

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
        """
        if not getattr(self, "_initialized", False):
            try:
                self.config = NotificationConfig.from_config_file()
                logger.info("使用配置文件初始化通知管理器")
            except Exception as e:
                logger.error(f"配置文件加载失败: {e}")
                raise Exception(f"通知管理器初始化失败，无法加载配置文件: {e}") from e

            # 初始化通知提供者字典
            self._providers: Dict[NotificationType, Any] = {}

            # 初始化事件队列和锁
            self._event_queue: List[NotificationEvent] = []
            self._queue_lock = threading.Lock()

            # 【线程安全】配置锁，保护 config 对象的并发读写
            # 用于 refresh_config_from_file() 和 update_config_without_save()
            self._config_lock = threading.Lock()

            # 【性能优化】配置缓存：记录配置文件的最后修改时间
            # 只有文件修改时间变化时才重新读取配置，避免频繁 I/O
            self._config_file_mtime: float = 0.0

            # 初始化工作线程相关（预留扩展）
            self._worker_thread = None
            self._stop_event = threading.Event()

            # 【性能优化】使用线程池异步发送通知，避免阻塞主流程
            # max_workers=3 足够处理 Web/Sound/Bark 三种通知类型的并行发送
            self._executor = ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="NotificationWorker"
            )

            # 【可靠性】延迟通知 Timer 管理（用于测试/退出时可控清理）
            # key: event_id -> threading.Timer
            self._delayed_timers: Dict[str, threading.Timer] = {}
            self._delayed_timers_lock = threading.Lock()
            self._shutdown_called: bool = False

            # 【可观测性】基础统计信息（用于调试/监控；不写入磁盘）
            self._stats_lock = threading.Lock()
            self._stats: Dict[str, Any] = {
                "events_total": 0,
                "events_succeeded": 0,
                "events_failed": 0,
                "attempts_total": 0,
                "retries_scheduled": 0,
                "last_event_id": None,
                "last_event_at": None,
                "providers": {},  # {type: {attempts/success/failure/last_error/...}}
            }
            # 记录已“最终完成”的事件，避免重试场景重复计数
            self._finalized_event_ids: set[str] = set()

            # 初始化回调函数字典
            self._callbacks: Dict[str, List[Callable]] = {}

            # 标记已初始化
            self._initialized = True

            # 根据调试模式设置日志级别
            if self.config.debug:
                logger.setLevel(logging.DEBUG)
                logger.debug("通知管理器初始化完成（调试模式）")
            else:
                logger.info("通知管理器初始化完成")

            # 【关键修复】根据初始配置注册 Bark 提供者
            # 之前的问题：只有在运行时通过 update_config_without_save 更改 bark_enabled 时
            # 才会调用 _update_bark_provider，导致启动时即使 bark_enabled=True 也不会注册
            if self.config.bark_enabled:
                self._update_bark_provider()
                logger.info("已根据初始配置注册 Bark 通知提供者")

    def register_provider(self, notification_type: NotificationType, provider: Any):
        """注册通知提供者

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
        """
        self._providers[notification_type] = provider
        logger.debug(f"已注册通知提供者: {notification_type.value}")

    def add_callback(self, event_name: str, callback: Callable):
        """添加事件回调

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
        """
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)
        logger.debug(f"已添加回调: {event_name}")

    def trigger_callbacks(self, event_name: str, *args, **kwargs):
        """触发事件回调

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
        """
        if event_name in self._callbacks:
            for callback in self._callbacks[event_name]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logger.error(f"回调执行失败 {event_name}: {e}")

    def send_notification(
        self,
        title: str,
        message: str,
        trigger: NotificationTrigger = NotificationTrigger.IMMEDIATE,
        types: Optional[List[NotificationType]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """发送通知

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
        """
        if not self.config.enabled:
            logger.debug("通知功能已禁用，跳过发送")
            return ""

        # 【资源生命周期】若已 shutdown，则拒绝继续发送，避免线程池已关闭导致异常
        if getattr(self, "_shutdown_called", False):
            logger.debug("通知管理器已关闭，跳过发送")
            return ""

        # 生成事件ID
        event_id = f"notification_{int(time.time() * 1000)}_{id(self)}"

        # 默认通知类型
        if types is None:
            types = []
            if self.config.web_enabled:
                types.append(NotificationType.WEB)
            if self.config.sound_enabled and not self.config.sound_mute:
                types.append(NotificationType.SOUND)
            if self.config.bark_enabled:
                types.append(NotificationType.BARK)

        # 创建通知事件
        event = NotificationEvent(
            id=event_id,
            title=title,
            message=message,
            trigger=trigger,
            types=types,
            metadata=metadata or {},
            max_retries=self.config.retry_count,
        )

        # 【可观测性】记录事件创建（只计一次，不随重试重复）
        try:
            with self._stats_lock:
                self._stats["events_total"] += 1
                self._stats["last_event_id"] = event_id
                self._stats["last_event_at"] = time.time()
        except Exception:
            # 统计不影响主流程
            pass

        # 添加到队列
        with self._queue_lock:
            self._event_queue.append(event)
            # 防止队列无限增长（仅保留最近 N 个事件用于调试/状态展示）
            max_keep = 200
            if len(self._event_queue) > max_keep:
                self._event_queue = self._event_queue[-max_keep:]

        logger.debug(f"通知事件已创建: {event_id} - {title}")

        # 立即处理或延迟处理
        if trigger == NotificationTrigger.IMMEDIATE:
            self._process_event(event)
        elif trigger == NotificationTrigger.DELAYED:
            # 【可靠性】threading.Timer 默认是非守护线程，可能导致测试/进程退出被阻塞
            # 这里将 Timer 设为守护线程，并纳入统一管理以便 shutdown() 清理
            if getattr(self, "_shutdown_called", False):
                logger.debug("通知管理器已关闭，跳过延迟通知调度")
                return event_id

            def _delayed_run():
                try:
                    self._process_event(event)
                finally:
                    # 清理 Timer 引用，避免字典增长
                    with self._delayed_timers_lock:
                        self._delayed_timers.pop(event.id, None)

            timer = threading.Timer(self.config.trigger_delay, _delayed_run)
            timer.daemon = True
            with self._delayed_timers_lock:
                self._delayed_timers[event.id] = timer
            timer.start()

        return event_id

    def _mark_event_finalized(self, event: NotificationEvent, succeeded: bool) -> None:
        """标记事件已完成（成功/最终失败），用于统计去重"""
        try:
            with self._stats_lock:
                if event.id in self._finalized_event_ids:
                    return
                self._finalized_event_ids.add(event.id)
                if succeeded:
                    self._stats["events_succeeded"] += 1
                else:
                    self._stats["events_failed"] += 1
        except Exception:
            # 统计不影响主流程
            pass

    def _schedule_retry(self, event: NotificationEvent) -> None:
        """调度一次事件重试（使用 Timer，避免在当前线程阻塞等待）"""
        if getattr(self, "_shutdown_called", False):
            return

        try:
            delay_seconds = max(int(getattr(self.config, "retry_delay", 2)), 0)
        except (TypeError, ValueError):
            delay_seconds = 2

        timer_key = f"{event.id}__retry_{event.retry_count}"

        def _retry_run():
            try:
                self._process_event(event)
            finally:
                with self._delayed_timers_lock:
                    self._delayed_timers.pop(timer_key, None)

        timer = threading.Timer(delay_seconds, _retry_run)
        timer.daemon = True
        with self._delayed_timers_lock:
            self._delayed_timers[timer_key] = timer
        timer.start()

    def _process_event(self, event: NotificationEvent):
        """处理通知事件

        【功能说明】
        将通知事件发送到所有指定的通知提供者，统计成功数量，并在需要时触发降级处理。

        【处理流程】
        1. 记录调试日志，标记事件处理开始
        2. 使用线程池并行发送到所有通知类型
        3. 统计成功发送的数量
        4. 触发 notification_sent 回调，传递事件和成功数量
        5. 如果所有方式失败且启用降级，执行降级处理

        【性能优化】
        - 使用 ThreadPoolExecutor 并行发送通知到多个渠道
        - 避免串行发送导致的延迟累加
        - 每个通知类型在独立线程中执行

        【成功判定】
        - 至少一个提供者成功发送即视为部分成功
        - success_count = 0 时触发降级

        【降级策略】
        - 仅当 config.fallback_enabled 为 True 时触发
        - 调用 _handle_fallback 方法执行降级逻辑
        - 降级处理不影响正常流程

        【异常处理】
        - 捕获所有异常并记录错误日志
        - 异常时如果启用降级则执行降级处理
        - 不向上传播异常，确保不影响其他通知

        【回调触发】
        - 正常完成时触发 notification_sent 回调
        - 异常或全部失败时可能触发 notification_fallback 回调

        Args:
            event: 要处理的通知事件对象
        """
        # shutdown 后可能仍有残留 Timer/线程回调进入，这里直接跳过避免线程池已关闭报错
        if getattr(self, "_shutdown_called", False):
            logger.debug(f"通知管理器已关闭，跳过事件处理: {event.id}")
            return

        try:
            logger.debug(f"处理通知事件: {event.id}")

            # 【可观测性】记录一次“事件尝试”（重试会重复计数）
            try:
                with self._stats_lock:
                    self._stats["attempts_total"] += 1
            except Exception:
                pass

            # 【性能优化】使用线程池并行发送通知
            if not event.types:
                logger.debug(f"通知事件无指定类型，跳过: {event.id}")
                return

            futures = {}
            for notification_type in event.types:
                future = self._executor.submit(
                    self._send_single_notification, notification_type, event
                )
                futures[future] = notification_type

            success_count = 0
            completed_count = 0
            total_count = len(futures)

            # 【优化】使用 try-except 捕获超时，避免未完成任务导致错误日志
            # as_completed 超时时会抛出 TimeoutError: "N (of M) futures unfinished"
            try:
                for future in as_completed(
                    futures, timeout=15
                ):  # 15秒超时（Bark 默认10秒）
                    completed_count += 1
                    notification_type = futures[future]
                    try:
                        if future.result():
                            success_count += 1
                    except Exception as e:
                        logger.warning(f"通知发送异常 {notification_type.value}: {e}")
            except TimeoutError:
                # 【优化】超时时记录警告而非错误，因为部分通知可能已成功
                unfinished_count = total_count - completed_count
                logger.warning(
                    f"通知发送部分超时: {event.id} - "
                    f"{completed_count}/{total_count} 完成，{unfinished_count} 未完成"
                )
                # 尝试取消未完成的任务
                # 注意：cancel() 对已在运行的任务不会生效，只能取消排队中的任务
                for future, notification_type in futures.items():
                    if not future.done():
                        cancelled = future.cancel()
                        if cancelled:
                            logger.debug(f"已取消排队任务: {notification_type.value}")
                        else:
                            logger.debug(
                                f"任务正在运行，无法取消: {notification_type.value}"
                            )

            # 触发回调（每次尝试都会触发，便于调试/前端展示）
            self.trigger_callbacks("notification_sent", event, success_count)

            if success_count == 0:
                # 失败：若仍有重试额度，则调度重试并提前返回（不进入降级）
                if event.retry_count < event.max_retries:
                    event.retry_count += 1
                    try:
                        with self._stats_lock:
                            self._stats["retries_scheduled"] += 1
                    except Exception:
                        pass

                    logger.warning(
                        f"通知发送失败，将在 {self.config.retry_delay}s 后重试 "
                        f"({event.retry_count}/{event.max_retries}): {event.id}"
                    )
                    self._schedule_retry(event)
                    self.trigger_callbacks("notification_retry_scheduled", event)
                    return

                # 无重试额度：最终失败
                self._mark_event_finalized(event, succeeded=False)
                if self.config.fallback_enabled:
                    logger.warning(f"所有通知方式失败，启用降级处理: {event.id}")
                    self._handle_fallback(event)
            else:
                # 只要有任一渠道成功，视为成功（并终止后续重试）
                self._mark_event_finalized(event, succeeded=True)
                logger.info(
                    f"通知发送完成: {event.id} - 成功 {success_count}/{total_count}"
                )

        except Exception as e:
            logger.error(f"处理通知事件失败: {event.id} - {e}")
            # 异常：优先走重试；重试耗尽再降级
            if event.retry_count < event.max_retries:
                event.retry_count += 1
                try:
                    with self._stats_lock:
                        self._stats["retries_scheduled"] += 1
                except Exception:
                    pass
                logger.warning(
                    f"处理通知事件异常，将在 {self.config.retry_delay}s 后重试 "
                    f"({event.retry_count}/{event.max_retries}): {event.id}"
                )
                self._schedule_retry(event)
                self.trigger_callbacks("notification_retry_scheduled", event)
                return

            self._mark_event_finalized(event, succeeded=False)
            if self.config.fallback_enabled:
                self._handle_fallback(event)

    def _send_single_notification(
        self, notification_type: NotificationType, event: NotificationEvent
    ) -> bool:
        """发送单个类型的通知

        【功能说明】
        调用指定类型的通知提供者发送通知事件。

        【处理流程】
        1. 从提供者字典查找对应的提供者实例
        2. 检查提供者是否存在
        3. 检查提供者是否实现 send 方法
        4. 调用 send 方法并返回结果
        5. 捕获异常并记录日志

        【提供者查找】
        - 通过 notification_type 从 _providers 字典查找
        - 未找到提供者时记录调试日志并返回 False
        - 不抛出异常，确保其他提供者继续执行

        【方法验证】
        - 使用 hasattr 检查 send 方法是否存在
        - 缺少 send 方法时记录错误日志
        - 返回 False 而非抛出异常

        【异常处理】
        - 捕获提供者 send 方法抛出的所有异常
        - 记录详细的错误日志（包含类型和异常信息）
        - 返回 False 表示发送失败
        - 不向上传播异常，保护其他提供者

        Args:
            notification_type: 通知类型枚举值
            event: 要发送的通知事件对象

        Returns:
            bool: True 表示成功发送，False 表示失败或提供者不可用
        """
        provider = self._providers.get(notification_type)
        if not provider:
            logger.debug(f"未找到通知提供者: {notification_type.value}")
            return False

        try:
            # 【可观测性】记录提供者级别的尝试次数
            try:
                with self._stats_lock:
                    providers = self._stats.setdefault("providers", {})
                    stats = providers.setdefault(
                        notification_type.value,
                        {
                            "attempts": 0,
                            "success": 0,
                            "failure": 0,
                            "last_success_at": None,
                            "last_failure_at": None,
                            "last_error": None,
                        },
                    )
                    stats["attempts"] += 1
            except Exception:
                pass

            # 调用提供者的发送方法
            if hasattr(provider, "send"):
                ok = bool(provider.send(event))
            else:
                logger.error(f"通知提供者缺少send方法: {notification_type.value}")
                ok = False

            # 【可观测性】记录结果与最近错误
            try:
                with self._stats_lock:
                    providers = self._stats.setdefault("providers", {})
                    stats = providers.setdefault(
                        notification_type.value,
                        {
                            "attempts": 0,
                            "success": 0,
                            "failure": 0,
                            "last_success_at": None,
                            "last_failure_at": None,
                            "last_error": None,
                        },
                    )
                    now = time.time()
                    if ok:
                        stats["success"] += 1
                        stats["last_success_at"] = now
                        stats["last_error"] = None
                    else:
                        stats["failure"] += 1
                        stats["last_failure_at"] = now
                        # Bark 在 debug/test 模式下会写入 event.metadata["bark_error"]
                        last_error = None
                        if (
                            notification_type == NotificationType.BARK
                            and isinstance(event.metadata, dict)
                            and event.metadata.get("bark_error") is not None
                        ):
                            last_error = event.metadata.get("bark_error")
                        stats["last_error"] = (
                            str(last_error)[:800] if last_error is not None else None
                        )
            except Exception:
                pass

            return ok
        except Exception as e:
            logger.error(f"发送通知失败 {notification_type.value}: {e}")

            # 【可观测性】记录异常
            try:
                with self._stats_lock:
                    providers = self._stats.setdefault("providers", {})
                    stats = providers.setdefault(
                        notification_type.value,
                        {
                            "attempts": 0,
                            "success": 0,
                            "failure": 0,
                            "last_success_at": None,
                            "last_failure_at": None,
                            "last_error": None,
                        },
                    )
                    stats["failure"] += 1
                    stats["last_failure_at"] = time.time()
                    stats["last_error"] = f"{type(e).__name__}: {e}"[:800]
            except Exception:
                pass

            return False

    def _handle_fallback(self, event: NotificationEvent):
        """处理降级方案

        【功能说明】
        当所有通知提供者都失败时，执行备用的降级处理逻辑。

        【触发条件】
        - 所有指定的通知类型发送均失败（success_count = 0）
        - 配置中 fallback_enabled 为 True
        - 事件处理过程中发生异常

        【当前实现】
        - 记录信息日志，标记执行降级处理
        - 触发 notification_fallback 回调事件
        - 由回调函数实现具体的降级逻辑

        【扩展点】
        - 可通过注册 notification_fallback 回调实现自定义降级逻辑
        - 可能的降级方案：
          * 发送邮件通知
          * 写入日志文件
          * 存储到数据库待后续重试
          * 通过备用通知渠道发送

        【设计考虑】
        - 降级处理本身不应抛出异常
        - 避免在降级中使用可能失败的外部服务
        - 降级逻辑应尽量简单可靠

        Args:
            event: 发送失败的通知事件对象
        """
        logger.info(f"执行降级处理: {event.id}")
        self.trigger_callbacks("notification_fallback", event)

    def shutdown(self, wait: bool = False):
        """关闭通知管理器并清理后台资源

        目的：
        - 避免后台 Timer / 线程池在测试或程序退出时阻塞进程
        - 为单测与脚本提供显式的资源释放入口

        当前清理项：
        - 延迟通知 Timer（NotificationTrigger.DELAYED）
        - 线程池执行器（_executor）

        参数：
        - wait: 是否等待线程池任务完成。测试场景通常用 False 以快速退出。

        注意：
        - 该方法是幂等的，可安全多次调用
        """
        if getattr(self, "_shutdown_called", False):
            return
        self._shutdown_called = True

        # 取消所有未触发的延迟通知
        try:
            with self._delayed_timers_lock:
                timers = list(self._delayed_timers.values())
                self._delayed_timers.clear()
            for t in timers:
                try:
                    t.cancel()
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"取消延迟通知 Timer 失败（忽略）: {e}")

        # 关闭线程池
        try:
            # cancel_futures 在 Python 3.9+ 可用
            self._executor.shutdown(wait=wait, cancel_futures=True)
        except TypeError:
            # 兼容旧签名（尽管项目要求 3.11+，这里保持稳健）
            self._executor.shutdown(wait=wait)
        except Exception as e:
            logger.debug(f"关闭通知线程池失败（忽略）: {e}")

    def restart(self):
        """重启通知管理器（仅在 shutdown 后可用）

        典型用途：
        - 长驻进程热重启（同一进程内反复启动/停止服务）
        - 测试场景需要反复启动/关闭通知系统

        行为：
        - 清除 shutdown 标记
        - 重建线程池执行器

        注意：
        - 不强制重置 providers/queue/config（调用方可自行 refresh_config_from_file）
        """
        if not getattr(self, "_shutdown_called", False):
            return

        self._shutdown_called = False
        self._executor = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="NotificationWorker"
        )

    def get_config(self) -> NotificationConfig:
        """获取当前配置

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
        """
        return self.config

    def refresh_config_from_file(self, force: bool = False):
        """从配置文件重新加载配置（跨进程同步）

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
        """
        if not CONFIG_FILE_AVAILABLE:
            return

        try:
            config_mgr = get_config()

            # 【性能优化】检查配置文件是否有更新
            config_file_path = config_mgr.config_file
            try:
                import os

                current_mtime = os.path.getmtime(config_file_path)

                # 非强制模式下，如果文件未变化则跳过刷新
                if not force and current_mtime == self._config_file_mtime:
                    logger.debug("配置文件未变化，跳过刷新")
                    return

                # 无论是否强制，都更新 mtime 缓存
                self._config_file_mtime = current_mtime
            except (OSError, AttributeError):
                # 如果无法获取文件修改时间，继续刷新配置
                pass

            notification_config = config_mgr.get_section("notification")

            # 【类型验证】辅助函数：安全获取布尔值
            def safe_bool(value, default: bool) -> bool:
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes")
                return default

            # 【类型验证】辅助函数：安全获取数值
            def safe_number(
                value, default: float, min_val: float = 0, max_val: float = 100
            ) -> float:
                try:
                    num = float(value)
                    return max(min_val, min(max_val, num))
                except (TypeError, ValueError):
                    return default

            # 【类型验证】辅助函数：安全获取字符串
            def safe_str(value, default: str) -> str:
                if value is None:
                    return default
                return str(value)

            # 【线程安全】使用配置锁保护配置更新操作
            with self._config_lock:
                # 记录更新前的 bark_enabled 状态
                bark_was_enabled = self.config.bark_enabled

                # 【类型验证】更新所有配置字段，使用安全类型转换
                self.config.enabled = safe_bool(
                    notification_config.get("enabled"), True
                )
                self.config.web_enabled = safe_bool(
                    notification_config.get("web_enabled"), True
                )
                self.config.web_permission_auto_request = safe_bool(
                    notification_config.get("auto_request_permission"), True
                )
                self.config.sound_enabled = safe_bool(
                    notification_config.get("sound_enabled"), True
                )
                # 音量从 0-100 转换为 0.0-1.0，带范围验证
                self.config.sound_volume = (
                    safe_number(notification_config.get("sound_volume"), 80, 0, 100)
                    / 100.0
                )
                self.config.sound_mute = safe_bool(
                    notification_config.get("sound_mute"), False
                )
                self.config.mobile_optimized = safe_bool(
                    notification_config.get("mobile_optimized"), True
                )
                self.config.mobile_vibrate = safe_bool(
                    notification_config.get("mobile_vibrate"), True
                )
                self.config.bark_enabled = safe_bool(
                    notification_config.get("bark_enabled"), False
                )
                self.config.bark_url = safe_str(notification_config.get("bark_url"), "")
                self.config.bark_device_key = safe_str(
                    notification_config.get("bark_device_key"), ""
                )
                self.config.bark_icon = safe_str(
                    notification_config.get("bark_icon"), ""
                )
                self.config.bark_action = safe_str(
                    notification_config.get("bark_action"), "none"
                )

                # 重试/超时配置（新增：允许通过配置文件调优可靠性与时延）
                self.config.retry_count = int(
                    safe_number(notification_config.get("retry_count"), 3, 0, 10)
                )
                self.config.retry_delay = int(
                    safe_number(notification_config.get("retry_delay"), 2, 0, 60)
                )
                self.config.bark_timeout = int(
                    safe_number(notification_config.get("bark_timeout"), 10, 1, 300)
                )

                logger.debug("已从配置文件刷新通知配置（带类型验证）")

                # 如果 bark_enabled 状态发生变化，动态更新提供者
                bark_now_enabled = self.config.bark_enabled
                if bark_was_enabled != bark_now_enabled:
                    self._update_bark_provider()
                    logger.info(
                        f"Bark 提供者已根据配置文件更新 (enabled: {bark_now_enabled})"
                    )

        except Exception as e:
            logger.warning(f"从配置文件刷新配置失败: {e}")

    def update_config(self, **kwargs):
        """更新配置并保存到文件

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
        """
        self.update_config_without_save(**kwargs)
        self._save_config_to_file()

    def update_config_without_save(self, **kwargs):
        """更新配置但不保存到文件

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
        """
        # 【线程安全】使用配置锁保护配置更新操作
        with self._config_lock:
            bark_was_enabled = self.config.bark_enabled

            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
                    logger.debug(f"配置已更新: {key} = {value}")

            # 如果Bark配置发生变化，动态更新提供者
            bark_now_enabled = self.config.bark_enabled
            if bark_was_enabled != bark_now_enabled:
                self._update_bark_provider()

    def _update_bark_provider(self):
        """动态更新 Bark 通知提供者

        【功能说明】
        根据配置的 bark_enabled 状态，动态添加或移除 Bark 通知提供者。

        【处理流程】
        1. 检查 bark_enabled 配置
        2. 如果启用且未注册：
           - 使用延迟导入加载 BarkNotificationProvider
           - 创建 BarkNotificationProvider 实例
           - 注册到提供者字典
           - 记录添加日志
        3. 如果禁用且已注册：
           - 从提供者字典删除
           - 记录移除日志

        【延迟导入说明】
        - 使用方法内延迟导入解决循环导入问题
        - notification_manager.py <-> notification_providers.py 相互依赖
        - 延迟导入确保在运行时才加载 BarkNotificationProvider
        - 避免模块加载时的循环依赖导致导入失败

        【前提条件】
        - notification_providers 模块必须可导入
        - bark_url 和 bark_device_key 配置正确

        【异常处理】
        - 捕获所有异常并记录错误日志
        - 异常不向上传播，避免影响其他配置更新
        - 导入失败时记录详细错误信息

        【幂等性】
        - 多次调用相同状态不会重复添加或删除
        - 使用字典键存在性检查确保幂等

        【调用时机】
        - update_config_without_save 中检测到 bark_enabled 变化时
        - 初始化时如果 bark_enabled=True 也会调用
        - 不应手动调用，由配置更新自动触发
        """
        try:
            if self.config.bark_enabled:
                # 启用Bark通知，添加提供者
                if NotificationType.BARK not in self._providers:
                    # 【关键修复】使用延迟导入解决循环导入问题
                    # 在方法内部导入，而非模块级别，避免加载时循环依赖
                    from notification_providers import BarkNotificationProvider

                    bark_provider = BarkNotificationProvider(self.config)
                    self.register_provider(NotificationType.BARK, bark_provider)
                    logger.info("Bark通知提供者已动态添加")
            else:
                # 禁用Bark通知，移除提供者
                if NotificationType.BARK in self._providers:
                    del self._providers[NotificationType.BARK]
                    logger.info("Bark通知提供者已移除")
        except ImportError as e:
            logger.error(f"更新Bark提供者失败: 无法导入 BarkNotificationProvider - {e}")
        except Exception as e:
            logger.error(f"更新Bark提供者失败: {e}")

    def _save_config_to_file(self):
        """保存当前配置到配置文件

        【功能说明】
        将内存中的通知配置持久化到配置文件，确保重启后配置保留。

        【处理流程】
        1. 检查配置文件管理器是否可用
        2. 获取配置管理器实例
        3. 处理 sound_volume 的范围转换
        4. 构建配置字典（映射内部字段到配置文件键）
        5. 调用配置管理器更新 "notification" 配置段
        6. 记录成功日志

        【数据转换】
        - sound_volume: 从浮点数（0.0-1.0）转换为整数（0-100）
        - web_permission_auto_request: 映射到 auto_request_permission
        - 自动处理不同范围的 sound_volume 值

        【字段映射】
        内存中的字段名可能与配置文件中的键名不同，需要手动映射：
        - web_permission_auto_request -> auto_request_permission

        【不保存的字段】
        以下字段不会保存到配置文件：
        - debug: 调试模式，通常不持久化
        - web_icon, web_timeout, sound_file: 使用默认值或硬编码
        - trigger_*: 触发时机配置暂不持久化

        【异常处理】
        - 配置管理器不可用时静默返回
        - 保存失败时捕获异常并记录错误日志
        - 不向上传播异常，避免影响配置更新流程

        【文件格式】
        - 通常为 JSON 或 JSONC 格式
        - 配置文件路径由配置管理器决定
        - 更新是部分更新，不影响其他配置段
        """
        if not CONFIG_FILE_AVAILABLE:
            return

        try:
            config_mgr = get_config()

            # 处理 sound_volume 的范围转换
            sound_volume_value = self.config.sound_volume
            if sound_volume_value <= 1.0:
                # 如果是0-1范围，转换为0-100范围
                sound_volume_int = int(sound_volume_value * 100)
            else:
                # 如果已经是0-100范围，直接使用
                sound_volume_int = int(sound_volume_value)

            # 构建配置字典
            notification_config = {
                "enabled": self.config.enabled,
                "web_enabled": self.config.web_enabled,
                "auto_request_permission": self.config.web_permission_auto_request,
                "sound_enabled": self.config.sound_enabled,
                "sound_mute": self.config.sound_mute,
                "sound_volume": sound_volume_int,
                "mobile_optimized": self.config.mobile_optimized,
                "mobile_vibrate": self.config.mobile_vibrate,
                "retry_count": int(self.config.retry_count),
                "retry_delay": int(self.config.retry_delay),
                "bark_enabled": self.config.bark_enabled,
                "bark_url": self.config.bark_url,
                "bark_device_key": self.config.bark_device_key,
                "bark_icon": self.config.bark_icon,
                "bark_action": self.config.bark_action,
                "bark_timeout": int(self.config.bark_timeout),
            }

            # 更新配置文件
            config_mgr.update_section("notification", notification_config)
            logger.debug("配置已保存到文件")
        except Exception as e:
            logger.error(f"保存配置到文件失败: {e}")

    def get_status(self) -> Dict[str, Any]:
        """获取通知管理器状态

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
        """
        # 线程安全地获取队列大小
        with self._queue_lock:
            queue_size = len(self._event_queue)

        # 线程安全地获取统计快照
        try:
            with self._stats_lock:
                providers_stats = {
                    k: dict(v) for k, v in self._stats.get("providers", {}).items()
                }
                stats_snapshot = {
                    k: v for k, v in self._stats.items() if k != "providers"
                }
                stats_snapshot["providers"] = providers_stats
        except Exception:
            stats_snapshot = {}

        return {
            "enabled": self.config.enabled,
            "providers": [t.value for t in self._providers.keys()],
            "queue_size": queue_size,
            "config": {
                "web_enabled": self.config.web_enabled,
                "sound_enabled": self.config.sound_enabled,
                "bark_enabled": self.config.bark_enabled,
                "retry_count": self.config.retry_count,
                "retry_delay": self.config.retry_delay,
                "bark_timeout": self.config.bark_timeout,
            },
            "stats": stats_snapshot,
        }


# 全局通知管理器实例
notification_manager = NotificationManager()

# 【资源生命周期】进程退出时尽量清理后台资源（Timer/线程池）
# - 避免测试或 REPL 退出时出现线程池阻塞
# - shutdown() 幂等，重复调用安全
import atexit  # noqa: E402


def _shutdown_global_notification_manager():
    try:
        notification_manager.shutdown(wait=False)
    except Exception:
        # 退出阶段不再抛异常
        pass


atexit.register(_shutdown_global_notification_manager)
