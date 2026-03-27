#!/usr/bin/env python3
"""通知管理器模块 - 统一管理 Web/声音/Bark/系统多渠道通知。

采用单例模式，支持插件化提供者注册、事件队列、失败降级。线程安全。
"""

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, ClassVar, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from exceptions import NotificationError

try:
    from config_manager import get_config

    CONFIG_FILE_AVAILABLE = True
except ImportError:
    CONFIG_FILE_AVAILABLE = False

from config_utils import clamp_value, validate_enum_value
from enhanced_logging import EnhancedLogger
from notification_models import (
    NotificationEvent,
    NotificationPriority,
    NotificationTrigger,
    NotificationType,
)

# 说明：
# - 通知事件/枚举已抽到 notification_models.py，避免 manager/provider 循环依赖
# - BarkProvider 仍采用延迟导入：仅在需要时加载，降低启动时开销与依赖耦合

logger = EnhancedLogger(__name__)


class NotificationConfig(BaseModel):
    """通知配置类 - 全局开关/Web/声音/触发时机/重试/移动优化/Bark 等配置。"""

    model_config = ConfigDict(validate_assignment=True)

    # ==================== 全局开关 ====================
    enabled: bool = True
    debug: bool = False

    # ==================== Web 通知配置 ====================
    web_enabled: bool = True
    web_permission_auto_request: bool = True
    web_icon: str = "default"
    web_timeout: int = 5000

    # ==================== 声音通知配置 ====================
    sound_enabled: bool = True
    sound_volume: float = 0.8
    sound_file: str = "default"
    sound_mute: bool = False

    # ==================== 触发时机配置 ====================
    trigger_immediate: bool = True
    trigger_delay: int = 30
    trigger_repeat: bool = False
    trigger_repeat_interval: int = 60

    # ==================== 错误处理配置 ====================
    retry_count: int = 3
    retry_delay: int = 2
    fallback_enabled: bool = True

    # ==================== 移动设备优化 ====================
    mobile_optimized: bool = True
    mobile_vibrate: bool = True

    # ==================== Bark 通知配置（可选）====================
    bark_enabled: bool = False
    bark_url: str = ""
    bark_device_key: str = ""
    bark_icon: str = ""
    bark_action: str = "none"
    bark_timeout: int = 10

    # ==================== 系统/平台原生通知 ====================
    system_enabled: bool = False
    macos_native_enabled: bool = True

    # ==================== 边界常量 ====================
    SOUND_VOLUME_MIN: ClassVar[float] = 0.0
    SOUND_VOLUME_MAX: ClassVar[float] = 1.0
    BARK_ACTIONS_VALID: ClassVar[tuple[str, ...]] = ("none", "url", "copy")

    @field_validator("sound_volume")
    @classmethod
    def clamp_sound_volume(cls, v: float) -> float:
        return clamp_value(
            v, cls.SOUND_VOLUME_MIN, cls.SOUND_VOLUME_MAX, "sound_volume"
        )

    @field_validator("retry_count", mode="before")
    @classmethod
    def coerce_retry_count(cls, v: Any) -> int:
        try:
            return max(0, min(10, int(v)))
        except (TypeError, ValueError):
            return 3

    @field_validator("retry_delay", mode="before")
    @classmethod
    def coerce_retry_delay(cls, v: Any) -> int:
        try:
            return max(0, min(60, int(v)))
        except (TypeError, ValueError):
            return 2

    @field_validator("bark_timeout", mode="before")
    @classmethod
    def coerce_bark_timeout(cls, v: Any) -> int:
        try:
            return max(1, min(300, int(v)))
        except (TypeError, ValueError):
            return 10

    @field_validator("bark_action")
    @classmethod
    def validate_bark_action(cls, v: str) -> str:
        v = v.strip()
        if v in cls.BARK_ACTIONS_VALID:
            return v
        if v.startswith(("http://", "https://")):
            return v
        return validate_enum_value(v, cls.BARK_ACTIONS_VALID, "bark_action", "none")

    @model_validator(mode="after")
    def warn_bark_config(self) -> "NotificationConfig":
        if self.bark_url and not self._is_valid_url(self.bark_url):
            logger.warning(
                f"bark_url '{self.bark_url}' 格式无效，应以 http:// 或 https:// 开头"
            )
        if self.bark_enabled and not self.bark_device_key:
            logger.warning(
                "bark_enabled=True 但 bark_device_key 为空，Bark 通知将无法发送"
            )
        return self

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """验证 URL 格式是否有效"""
        return url.startswith("http://") or url.startswith("https://")

    @classmethod
    def from_config_file(cls) -> "NotificationConfig":
        """从配置文件 notification 段加载配置，sound_volume 自动转换 0-100 到 0.0-1.0

        注意：get_section() 已通过 Pydantic 段模型（NotificationSectionConfig）完成
        类型强转（SafeBool/ClampedInt）和范围钳位，此处无需再做手工转换。
        """
        if not CONFIG_FILE_AVAILABLE:
            logger.error("配置文件管理器不可用，无法初始化通知配置")
            raise NotificationError("配置文件管理器不可用", code="config_unavailable")

        config_mgr = get_config()
        cfg = config_mgr.get_section("notification")

        return cls(
            enabled=cfg.get("enabled", True),
            debug=cfg.get("debug", False),
            web_enabled=cfg.get("web_enabled", True),
            web_icon=cfg.get("web_icon", "default"),
            web_timeout=cfg.get("web_timeout", 5000),
            web_permission_auto_request=cfg.get("auto_request_permission", True),
            sound_enabled=cfg.get("sound_enabled", True),
            sound_file=cfg.get("sound_file", "default"),
            sound_volume=cfg.get("sound_volume", 80) / 100.0,
            sound_mute=cfg.get("sound_mute", False),
            mobile_optimized=cfg.get("mobile_optimized", True),
            mobile_vibrate=cfg.get("mobile_vibrate", True),
            retry_count=cfg.get("retry_count", 3),
            retry_delay=cfg.get("retry_delay", 2),
            bark_enabled=cfg.get("bark_enabled", False),
            bark_url=cfg.get("bark_url", ""),
            bark_device_key=cfg.get("bark_device_key", ""),
            bark_icon=cfg.get("bark_icon", ""),
            bark_action=cfg.get("bark_action", "none"),
            bark_timeout=cfg.get("bark_timeout", 10),
            system_enabled=cfg.get("system_enabled", False),
            macos_native_enabled=cfg.get("macos_native_enabled", True),
        )


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
        # __new__ 只保证“创建单例对象”线程安全；这里还需要保证“只初始化一次”
        if getattr(self, "_initialized", False):
            return

        with self.__class__._lock:
            if getattr(self, "_initialized", False):
                return

            try:
                self.config: NotificationConfig = NotificationConfig.from_config_file()
                logger.info("使用配置文件初始化通知管理器")
            except Exception as e:
                logger.error(f"配置文件加载失败: {e}", exc_info=True)
                raise NotificationError(
                    f"通知管理器初始化失败，无法加载配置文件: {e}",
                    code="init_failed",
                ) from e

            # 初始化通知提供者字典
            self._providers: Dict[NotificationType, Any] = {}
            self._providers_lock = threading.Lock()

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
            # max_workers=3 足够覆盖常见场景（通常同时启用的渠道不超过 3 个）
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
            self._callbacks_lock = threading.Lock()
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

    def register_provider(
        self, notification_type: NotificationType, provider: Any
    ) -> None:
        """注册通知提供者（需实现 send(event) -> bool）"""
        old_provider: Any | None = None
        with self._providers_lock:
            old_provider = self._providers.get(notification_type)
            self._providers[notification_type] = provider
        if old_provider is not None and old_provider is not provider:
            self._safe_close_provider(old_provider)
        logger.debug(f"已注册通知提供者: {notification_type.value}")

    @staticmethod
    def _safe_close_provider(provider: Any) -> None:
        """尽力关闭 provider 资源（如 requests.Session），失败不抛异常。"""
        try:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        except Exception as e:
            logger.debug(f"关闭通知提供者资源失败（忽略）: {e}")

    def add_callback(self, event_name: str, callback: Callable) -> None:
        """添加事件回调（如 notification_sent, notification_fallback）"""
        with self._callbacks_lock:
            if event_name not in self._callbacks:
                self._callbacks[event_name] = []
            self._callbacks[event_name].append(callback)
        logger.debug(f"已添加回调: {event_name}")

    def trigger_callbacks(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """触发指定事件的所有回调，异常不中断后续回调"""
        with self._callbacks_lock:
            callbacks = list(self._callbacks.get(event_name, []))

        for callback in callbacks:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"回调执行失败 {event_name}: {e}", exc_info=True)

    def send_notification(
        self,
        title: str,
        message: str,
        trigger: NotificationTrigger = NotificationTrigger.IMMEDIATE,
        types: Optional[List[NotificationType]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        priority: NotificationPriority | str = NotificationPriority.NORMAL,
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
        event_id = f"notification_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

        # 默认通知类型
        if types is None:
            types = []
            if self.config.web_enabled:
                types.append(NotificationType.WEB)
            if self.config.sound_enabled and not self.config.sound_mute:
                types.append(NotificationType.SOUND)
            if self.config.bark_enabled:
                types.append(NotificationType.BARK)
            if self.config.system_enabled:
                types.append(NotificationType.SYSTEM)

        # 兼容：priority 支持传入字符串（例如 "high"）
        event_priority = NotificationPriority.NORMAL
        if isinstance(priority, NotificationPriority):
            event_priority = priority
        elif isinstance(priority, str):
            try:
                event_priority = NotificationPriority(priority)
            except Exception:
                event_priority = NotificationPriority.NORMAL

        # 创建通知事件
        event = NotificationEvent(
            id=event_id,
            title=title,
            message=message,
            trigger=trigger,
            types=types,
            metadata=metadata or {},
            max_retries=self.config.retry_count,
            priority=event_priority,
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
                        logger.warning(
                            f"通知发送异常 {notification_type.value}: {e}",
                            exc_info=True,
                        )
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
            logger.error(f"处理通知事件失败: {event.id} - {e}", exc_info=True)
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
        with self._providers_lock:
            provider = self._providers.get(notification_type)
        if not provider:
            logger.debug(f"未找到通知提供者: {notification_type.value}")
            # 【可观测性】即便 provider 缺失，也记录一次失败（避免“静默丢失”）
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
                            "last_latency_ms": None,
                            "latency_ms_total": 0,
                            "latency_ms_count": 0,
                        },
                    )
                    stats["attempts"] += 1
                    stats["failure"] += 1
                    stats["last_failure_at"] = time.time()
                    stats["last_error"] = "provider_not_registered"
            except Exception:
                pass
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
                            "last_latency_ms": None,
                            "latency_ms_total": 0,
                            "latency_ms_count": 0,
                        },
                    )
                    stats["attempts"] += 1
            except Exception:
                pass

            started_at = time.time()
            # 调用提供者的发送方法
            if hasattr(provider, "send"):
                ok = bool(provider.send(event))
            else:
                logger.error(f"通知提供者缺少send方法: {notification_type.value}")
                ok = False
            latency_ms = max(int((time.time() - started_at) * 1000), 0)

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
                            "last_latency_ms": None,
                            "latency_ms_total": 0,
                            "latency_ms_count": 0,
                        },
                    )
                    now = time.time()
                    stats["last_latency_ms"] = latency_ms
                    stats["latency_ms_total"] = int(
                        stats.get("latency_ms_total", 0) or 0
                    ) + int(latency_ms)
                    stats["latency_ms_count"] = (
                        int(stats.get("latency_ms_count", 0) or 0) + 1
                    )
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
            logger.error(f"发送通知失败 {notification_type.value}: {e}", exc_info=True)

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
                            "last_latency_ms": None,
                            "latency_ms_total": 0,
                            "latency_ms_count": 0,
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

    def shutdown(self, wait: bool = False) -> None:
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

        # 关闭并清空 providers（释放可能的网络连接池等资源）
        try:
            with self._providers_lock:
                providers = list(self._providers.values())
                self._providers.clear()
            for p in providers:
                self._safe_close_provider(p)
        except Exception as e:
            logger.debug(f"关闭通知提供者失败（忽略）: {e}")

    def restart(self) -> None:
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

    def refresh_config_from_file(self, force: bool = False) -> None:
        """从配置文件刷新配置（mtime 缓存优化，force=True 强制刷新）"""
        if not CONFIG_FILE_AVAILABLE:
            return

        try:
            config_mgr = get_config()

            # 【性能优化】检查配置文件是否有更新
            config_file_path = config_mgr.config_file
            try:
                current_mtime = config_file_path.stat().st_mtime

                # 非强制模式下，如果文件未变化则跳过刷新
                if not force and current_mtime == self._config_file_mtime:
                    logger.debug("配置文件未变化，跳过刷新")
                    return

                # 无论是否强制，都更新 mtime 缓存
                self._config_file_mtime = current_mtime
            except OSError:
                # 如果无法获取文件修改时间，继续刷新配置
                pass

            cfg = config_mgr.get_section("notification")

            with self._config_lock:
                bark_was_enabled = self.config.bark_enabled

                self.config.enabled = cfg.get("enabled", True)
                self.config.debug = cfg.get("debug", False)
                self.config.web_enabled = cfg.get("web_enabled", True)
                self.config.web_icon = cfg.get("web_icon", "default")
                self.config.web_timeout = cfg.get("web_timeout", 5000)
                self.config.web_permission_auto_request = cfg.get(
                    "auto_request_permission", True
                )
                self.config.sound_enabled = cfg.get("sound_enabled", True)
                self.config.sound_file = cfg.get("sound_file", "default")
                self.config.sound_volume = cfg.get("sound_volume", 80) / 100.0
                self.config.sound_mute = cfg.get("sound_mute", False)
                self.config.mobile_optimized = cfg.get("mobile_optimized", True)
                self.config.mobile_vibrate = cfg.get("mobile_vibrate", True)
                self.config.bark_enabled = cfg.get("bark_enabled", False)
                self.config.bark_url = cfg.get("bark_url", "")
                self.config.bark_device_key = cfg.get("bark_device_key", "")
                self.config.bark_icon = cfg.get("bark_icon", "")
                self.config.bark_action = cfg.get("bark_action", "none")
                self.config.retry_count = cfg.get("retry_count", 3)
                self.config.retry_delay = cfg.get("retry_delay", 2)
                self.config.bark_timeout = cfg.get("bark_timeout", 10)
                self.config.system_enabled = cfg.get("system_enabled", False)
                self.config.macos_native_enabled = cfg.get("macos_native_enabled", True)

                logger.debug("已从配置文件刷新通知配置")

                # 如果 bark_enabled 状态发生变化，动态更新提供者
                bark_now_enabled = self.config.bark_enabled
                if bark_was_enabled != bark_now_enabled:
                    self._update_bark_provider()
                    logger.info(
                        f"Bark 提供者已根据配置文件更新 (enabled: {bark_now_enabled})"
                    )

        except Exception as e:
            logger.warning(f"从配置文件刷新配置失败: {e}", exc_info=True)

    def update_config(self, **kwargs: Any) -> None:
        """更新配置并持久化到文件"""
        self.update_config_without_save(**kwargs)
        self._save_config_to_file()

    def update_config_without_save(self, **kwargs: Any) -> None:
        """仅内存更新配置，不写文件。bark_enabled 变化时自动更新提供者。"""
        # 【线程安全】使用配置锁保护配置更新操作
        with self._config_lock:
            bark_was_enabled = self.config.bark_enabled
            sensitive_keys = {"bark_device_key"}

            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
                    if key in sensitive_keys:
                        logger.debug(f"配置已更新: {key} = <redacted>")
                    else:
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
                with self._providers_lock:
                    bark_registered = NotificationType.BARK in self._providers
                if not bark_registered:
                    # 【关键修复】使用延迟导入解决循环导入问题
                    # 在方法内部导入，而非模块级别，避免加载时循环依赖
                    from notification_providers import BarkNotificationProvider

                    bark_provider = BarkNotificationProvider(self.config)
                    self.register_provider(NotificationType.BARK, bark_provider)
                    logger.info("Bark通知提供者已动态添加")
            else:
                # 禁用Bark通知，移除提供者
                removed: Any | None = None
                with self._providers_lock:
                    removed = self._providers.pop(NotificationType.BARK, None)
                if removed is not None:
                    self._safe_close_provider(removed)
                    logger.info("Bark通知提供者已移除")
        except ImportError as e:
            logger.error(
                f"更新Bark提供者失败: 无法导入 BarkNotificationProvider - {e}",
                exc_info=True,
            )
        except Exception as e:
            logger.error(f"更新Bark提供者失败: {e}", exc_info=True)

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
                "debug": self.config.debug,
                "web_enabled": self.config.web_enabled,
                "web_icon": self.config.web_icon,
                "web_timeout": int(self.config.web_timeout),
                "auto_request_permission": self.config.web_permission_auto_request,
                "system_enabled": self.config.system_enabled,
                "macos_native_enabled": self.config.macos_native_enabled,
                "sound_enabled": self.config.sound_enabled,
                "sound_mute": self.config.sound_mute,
                "sound_file": self.config.sound_file,
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
            logger.error(f"保存配置到文件失败: {e}", exc_info=True)

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
                # 计算派生指标（阶段 A：delivery_success_rate 等）
                try:
                    succeeded = int(stats_snapshot.get("events_succeeded", 0) or 0)
                    failed = int(stats_snapshot.get("events_failed", 0) or 0)
                    total = int(stats_snapshot.get("events_total", 0) or 0)
                    finalized = succeeded + failed
                    in_flight = max(total - finalized, 0)

                    stats_snapshot["events_finalized"] = finalized
                    stats_snapshot["events_in_flight"] = in_flight
                    stats_snapshot["delivery_success_rate"] = (
                        round(succeeded / finalized, 4) if finalized > 0 else None
                    )
                except Exception:
                    pass

                # 提供者级别 success_rate（不影响主流程）
                try:
                    for _, st in providers_stats.items():
                        attempts = int(st.get("attempts", 0) or 0)
                        success = int(st.get("success", 0) or 0)
                        st["success_rate"] = (
                            round(success / attempts, 4) if attempts > 0 else None
                        )
                        latency_cnt = int(st.get("latency_ms_count", 0) or 0)
                        latency_total = int(st.get("latency_ms_total", 0) or 0)
                        st["avg_latency_ms"] = (
                            round(latency_total / latency_cnt, 2)
                            if latency_cnt > 0
                            else None
                        )
                except Exception:
                    pass
        except Exception:
            stats_snapshot = {}

        with self._providers_lock:
            providers = [t.value for t in self._providers.keys()]

        return {
            "enabled": self.config.enabled,
            "providers": providers,
            "queue_size": queue_size,
            "config": {
                "web_enabled": self.config.web_enabled,
                "sound_enabled": self.config.sound_enabled,
                "bark_enabled": self.config.bark_enabled,
                "system_enabled": self.config.system_enabled,
                "macos_native_enabled": self.config.macos_native_enabled,
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
