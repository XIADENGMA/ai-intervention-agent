#!/usr/bin/env python3
"""通知管理器模块 - 统一管理 Web/声音/Bark/系统多渠道通知。

采用单例模式，支持插件化提供者注册、事件队列、失败降级。线程安全。
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
    """通知类型枚举：WEB(浏览器)、SOUND(声音)、BARK(iOS推送)、SYSTEM(系统)"""

    WEB = "web"
    SOUND = "sound"
    BARK = "bark"
    SYSTEM = "system"


class NotificationTrigger(Enum):
    """通知触发时机：立即/延迟/重复/反馈收到/错误"""

    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    REPEAT = "repeat"
    FEEDBACK_RECEIVED = "feedback_received"
    ERROR = "error"


@dataclass
class NotificationConfig:
    """通知配置类 - 全局开关/Web/声音/触发时机/重试/移动优化/Bark 等配置。"""

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
        """验证并修正配置值边界"""
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
        """从配置文件 notification 段加载配置，sound_volume 自动转换 0-100 到 0.0-1.0"""
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
    """通知事件 - 封装一次通知的标题/消息/类型/触发时机/重试信息。"""

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
    """通知管理器（单例）- 管理提供者注册、事件队列、配置和回调，线程安全。"""

    _instance = None  # 单例实例
    _lock = threading.Lock()  # 单例创建锁

    def __new__(cls):
        """双重检查锁定创建单例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化配置、提供者字典、事件队列、线程池和回调"""
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
        """注册通知提供者（需实现 send(event) -> bool）"""
        self._providers[notification_type] = provider
        logger.debug(f"已注册通知提供者: {notification_type.value}")

    def add_callback(self, event_name: str, callback: Callable):
        """添加事件回调（如 notification_sent, notification_fallback）"""
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)
        logger.debug(f"已添加回调: {event_name}")

    def trigger_callbacks(self, event_name: str, *args, **kwargs):
        """触发指定事件的所有回调，异常不中断后续回调"""
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
        """发送通知主入口，返回事件ID。types=None 时根据配置自动选择渠道。"""
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
        """标记事件完成状态用于统计去重"""
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
        """使用 Timer 调度事件重试"""
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
        """并行发送通知到所有渠道，失败时重试或降级"""
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
        """调用指定类型提供者发送通知，返回成功与否"""
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
        """所有渠道失败时触发 notification_fallback 回调"""
        logger.info(f"执行降级处理: {event.id}")
        self.trigger_callbacks("notification_fallback", event)

    def shutdown(self, wait: bool = False):
        """关闭管理器，取消延迟 Timer 并关闭线程池（幂等）"""
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
        """shutdown 后重建线程池"""
        if not getattr(self, "_shutdown_called", False):
            return

        self._shutdown_called = False
        self._executor = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="NotificationWorker"
        )

    def get_config(self) -> NotificationConfig:
        """返回当前配置对象引用"""
        return self.config

    def refresh_config_from_file(self, force: bool = False):
        """从配置文件刷新配置（mtime 缓存优化，force=True 强制刷新）"""
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
        """更新配置并持久化到文件"""
        self.update_config_without_save(**kwargs)
        self._save_config_to_file()

    def update_config_without_save(self, **kwargs):
        """仅内存更新配置，不写文件。bark_enabled 变化时自动更新提供者。"""
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
        """根据 bark_enabled 动态添加/移除 Bark 提供者（延迟导入避免循环依赖）"""
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
        """持久化配置到文件（sound_volume 0-1 转 0-100）"""
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
        """返回管理器状态：enabled/providers/queue_size/config/stats"""
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
