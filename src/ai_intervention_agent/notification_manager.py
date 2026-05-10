"""通知管理器模块 - 统一管理 Web/声音/Bark/系统多渠道通知。

采用单例模式，支持插件化提供者注册、事件队列、失败降级。线程安全。
"""

import json
import logging
import os
import random
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ai_intervention_agent.exceptions import NotificationError

try:
    from ai_intervention_agent.config_manager import get_config

    CONFIG_FILE_AVAILABLE = True
except ImportError:
    CONFIG_FILE_AVAILABLE = False

from ai_intervention_agent.config_utils import clamp_value, validate_enum_value
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.notification_models import (
    NotificationEvent,
    NotificationPriority,
    NotificationTrigger,
    NotificationType,
)

# 说明：
# - 通知事件/枚举已抽到 notification_models.py，避免 manager/provider 循环依赖
# - BarkProvider 仍采用延迟导入：仅在需要时加载，降低启动时开销与依赖耦合

logger = EnhancedLogger(__name__)


# `_process_event` 用 ``concurrent.futures.as_completed(..., timeout=...)``
# 等待所有 channel 的 future。这个窗口必须严格大于 ``self.config.bark_timeout``
# （目前唯一会真正阻塞 thread-pool 工作线程的 HTTP-bound provider；其他 channel
# 走纯本地 metadata 准备或 plyer 调用，瞬时返回）。
#
# 历史上这里硬编码 ``timeout=15`` + 注释 "（Bark 默认10秒）"——这把 ``bark_timeout``
# 用户合法配置范围 ``[1, 300]`` 中的所有 ``> 15`` 取值都拍死了：
#   1. 用户把 ``bark_timeout`` 配成 30（Bark 服务器在跨境网络下 25s 才返回是常态）。
#   2. ``as_completed`` 在 15s 抛 TimeoutError；Bark future 仍在 thread-pool 跑。
#   3. ``success_count == 0`` 触发 retry，新一轮 future 进 pool 排队。
#   4. 老 future 在 25s 跑完返回 200；新 future 也跑完返回 200。
#   5. 用户的 iOS 在不到 30s 内收到两条同样的 Bark 推送 = 重复打扰。
#
# Buffer 而不是 +0：thread-pool 调度尾时延 + httpx connection-pool warmup +
# DNS 解析（首次）合计 < 5s，所以这里 +5 既能屏蔽尾时延，又不会让健康的 Bark
# 失败时 retry 拖太久。
_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS = 5


# R136: 通知 in-flight 队列断电恢复
# ----------------------------------------------------------------------------
# 文件名 / schema_version / TTL 三个常量是公开契约；测试侧也读它们做断言，
# 改动需要先写迁移逻辑（schema_version 升级）。
#
# **为什么要持久化**：
# - ``_event_queue`` / ``_finalized_event_ids`` 都在内存里，进程异常退出
#   （崩溃 / SIGKILL / OOM / 容器被驱逐）时彻底丢，运维侧完全看不到
#   "上次重启时还有 N 条通知没投递"。
# - 在分布式 worker / Cloud Native 部署中这是基础观察性盲点。
#
# **为什么不自动重发**：
# - 用户关电脑回家睡觉，第二天开机重发昨天的 50 条通知 = 噪音灾难。
# - 在 R136 范围内，仅做"持久化 + 启动时加载暴露给 stats"，把"是否
#   重发"决策权让给将来的 R136-A（如果用户有需求）。
#
# **TTL = 5 分钟**：典型用户场景下，通知如果 5 分钟内没投递成功就基本
# 失去时效（feedback 已经过期 / 用户已经看过了），保持文件长期不增长，
# 重启后也只看最近 5 分钟内的真正"飞行中"事件。
_INFLIGHT_FILE_NAME: str = "notification_inflight.json"
_INFLIGHT_SCHEMA_VERSION: int = 1
_INFLIGHT_TTL_SECONDS: int = 300  # 5 分钟


def _get_inflight_file_dir() -> Path | None:
    """R136 — 解析 in-flight 持久化文件所在目录。

    优先复用 ``config_manager.get_config()`` 已经解析好的 config 文件路
    径的 ``parent``——保证持久化文件与 config 文件同位（典型为
    ``~/.config/ai-intervention-agent/`` on Linux 或
    ``~/Library/Application Support/ai-intervention-agent/`` on macOS）。

    若 config 模块不可用（e.g. 单元测试隔离场景），返回 ``None``——
    callers 应当跳过持久化路径，避免污染 cwd。"""
    if not CONFIG_FILE_AVAILABLE:
        return None
    try:
        config_mgr = get_config()
        path = getattr(config_mgr, "config_path", None)
        if path is None:
            return None
        return Path(path).parent
    except Exception:
        return None


# ``ThreadPoolExecutor`` worker 数 = 通知渠道总数。
#
# why：
#     ``_process_event`` 会为每个 ``event.types`` 里的渠道 submit 一个
#     future。如果 ``max_workers < len(NotificationType)``，"全开"用户
#     submit 的最后几个 future 会进队列等空闲 worker——一旦前面的
#     渠道接近 ``bark_timeout`` 边缘（HTTPS 上行卡住、DNS 解析慢
#     等），``as_completed(timeout=bark_timeout + buffer)`` 会先到期
#     强 cancel 排队中的 future，用户漏收一条通知却零日志告警。
#
#     绑定到 ``len(NotificationType)`` 让两边自动同步：未来加新渠道
#     时只在 ``notification_models.NotificationType`` 里加一项，本
#     文件无需手动跟随调整常量。
#
# 资源开销：
#     ``ThreadPoolExecutor`` 是惰性创建 worker 的（``submit`` 时按需
#     ``_adjust_thread_count``），所以即使 ``max_workers=10`` 没人用
#     也不会真起 10 个线程。本项目当前是 4 个渠道，每个 worker 大约
#     8KB stack + Python 帧开销 ≈ 几十 KB——上限提到 4 几乎零成本。
_NOTIFICATION_WORKER_COUNT = len(NotificationType)


# ``_schedule_retry`` 的 thundering-herd 防御：在 ``retry_delay`` 之上叠加
# ``[0, retry_delay * jitter_ratio]`` 区间的随机抖动。
#
# 行业最佳实践（AWS Architecture Blog "Exponential Backoff and Jitter" /
# Google SRE Workbook §22）：当 N 个客户端在网络抖动后同时失败、同时重试，
# 没有 jitter 的话所有重试会在同一时刻撞向同一个下游服务，造成 thundering
# herd → 下游永远恢复不了。引入 0-50% 的随机延迟即可把重试时刻打散，让下游
# 有喘息窗口。
#
# 我们这里**故意不用指数退避**（``2^retry_count`` 那种）：
#   1. ``max_retries`` 默认 3，指数退避在小 N 下没什么区别。
#   2. ``retry_delay`` 默认 2s——加指数退避后总等待变成 2+4+8=14s，对单用户
#      场景的感知延迟太长。
#   3. Notification 不是关键路径（用户已经看到 Web UI），重试只是 best-effort，
#      没必要为了 4-th-retry 的低概率场景拉高 99 分位延迟。
# 简单的固定延迟 + jitter 是这个场景的甜蜜点。
#
# ``retry_delay == 0`` 时绕过 jitter（见 ``_schedule_retry`` 的 fast-path）：
#   1. 测试代码 / 高频压测路径会显式设 ``retry_delay = 0`` 期望「立即重试」。
#   2. 引入 jitter 会让那些场景出现亚秒级抖动 → 测试断言不稳定。
_RETRY_DELAY_JITTER_RATIO = 0.5


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
    # 当 bark_action == "url" 时，事件 metadata 没有提供 url/web_ui_url/action_url/link
    # 则按此模板渲染。支持的占位符：{task_id} / {event_id} / {base_url}
    bark_url_template: str = "{base_url}/?task_id={task_id}"

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
        return url.startswith(("http://", "https://"))

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
            bark_url_template=cfg.get(
                "bark_url_template", "{base_url}/?task_id={task_id}"
            ),
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
            self._providers: dict[NotificationType, Any] = {}
            self._providers_lock = threading.Lock()

            # 初始化事件队列和锁
            self._event_queue: list[NotificationEvent] = []
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

            # 【性能优化】使用线程池异步发送通知，避免阻塞主流程。
            # max_workers 动态等于 ``NotificationType`` 成员数（目前 4：
            # WEB/SOUND/BARK/SYSTEM），这样：
            #   1. 用户同时启用全部渠道时，每个渠道都有专属 worker，
            #      最慢渠道（典型是 BARK 走 HTTPS 上行）不会让其他
            #      渠道排队等空闲 worker；
            #   2. 未来新增渠道时只需在枚举里加一项，线程池自动伸缩，
            #      不需要再来这里改硬编码常量。
            # 历史上写死 ``max_workers=3``：在 4 渠道全开时第 4 个 future
            # 进队列等，前 3 个卡接近 ``bark_timeout`` 边缘时第 4 个
            # 根本没机会跑，``as_completed`` timeout 后被强 cancel——
            # 用户漏收一条通知，零日志告警。
            self._executor = ThreadPoolExecutor(
                max_workers=_NOTIFICATION_WORKER_COUNT,
                thread_name_prefix="NotificationWorker",
            )

            # 【可靠性】延迟通知 Timer 管理（用于测试/退出时可控清理）
            # key: event_id -> threading.Timer
            self._delayed_timers: dict[str, threading.Timer] = {}
            self._delayed_timers_lock = threading.Lock()
            self._shutdown_called: bool = False

            # 【可观测性】基础统计信息（用于调试/监控；不写入磁盘）
            self._stats_lock = threading.Lock()
            self._stats: dict[str, Any] = {
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
            self._finalized_event_ids: dict[str, None] = {}
            self._finalized_max_size: int = 500

            # R136: in-flight 通知持久化追踪
            # ``_inflight_persisted_ids``：当前已写入磁盘 inflight 文件的
            # event id 集合；``_create_event`` 入队后 ``add()``，
            # ``_mark_event_finalized`` 收尾时 ``discard()``；落盘文件 = 集
            # 合内事件的 dump，原子替换。
            #
            # ``_inflight_seen_at_startup``：进程启动时一次性 load 的「上
            # 次进程退出时还在 in-flight 的事件元数据」；TTL 过滤后剩下的
            # 直接暴露给 ``get_status()``，给运维仪表板 / on-call 一个信
            # 号——不会自动重发，避免「重启后用户被旧通知刷屏」尴尬。
            self._inflight_persisted_ids: set[str] = set()
            self._inflight_seen_at_startup: list[dict[str, Any]] = []

            # 初始化回调函数字典
            self._callbacks_lock = threading.Lock()
            self._callbacks: dict[str, list[Callable]] = {}

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

            # R136: 启动时一次性恢复磁盘上的 in-flight 通知元数据。失败
            # 不阻塞启动——磁盘问题 / JSON 损坏 / schema 不匹配都按"清
            # 空"处理，不让单一文件错误把整个通知系统拖死。
            try:
                self._inflight_seen_at_startup = self._load_persisted_inflight_events()
                if self._inflight_seen_at_startup:
                    logger.info(
                        "[R136] 加载到 %d 条上次未投递的 in-flight 通知"
                        "（仅暴露给 stats，不自动重发）",
                        len(self._inflight_seen_at_startup),
                    )
            except Exception as exc:
                logger.warning(
                    "[R136] 加载 inflight 持久化文件失败，跳过恢复: %s",
                    exc,
                    exc_info=True,
                )
                self._inflight_seen_at_startup = []

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
        types: list[NotificationType] | None = None,
        metadata: dict[str, Any] | None = None,
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

        # R136: 入队后立即记入 in-flight 持久化集合并落盘。失败不影响
        # 主流程——磁盘满 / 权限错误时通知仍能正常投递。
        try:
            self._track_event_inflight(event)
        except Exception as exc:
            logger.debug(
                "[R136] 持久化 inflight event %s 失败（不影响主流程）: %s",
                event_id,
                exc,
            )

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
        """标记事件完成状态用于统计去重。

        **R117**：原 ``except Exception: pass`` 把 stats 一致性失败完全静默——
        ``self._stats["events_succeeded" / "events_failed"]`` 与
        ``self._finalized_event_ids`` 集合是 ``get_stats()`` 计算
        ``delivery_success_rate`` / ``events_in_flight`` 的唯一来源，一旦
        这里 raise（例如 LRU dict 内部状态被并发污染、或 ``next(iter())``
        在罕见的 ``OrderedDict`` mutation race 下抛 ``StopIteration`` /
        ``RuntimeError: dictionary changed size during iteration``），
        统计数字会永久偏移，但运维 / 维护者完全看不见。

        修复策略：保持 try/except 不让异常打断调用方（``_process_event``
        在 success / failure 两路都调它，扩散异常会污染上层），但把
        exception 写到 debug 级日志——和 ``BarkNotificationProvider.close()``
        的 R117 修复同一 spirit，符合项目 "fail-loud, no silent skips"
        政策（cf. R107-R110 系列），仅在排查"为什么 ``delivery_success_rate``
        看起来不对"时打开 debug 即可定位 root cause。
        """
        try:
            with self._stats_lock:
                if event.id in self._finalized_event_ids:
                    return
                self._finalized_event_ids[event.id] = None
                # 容量淘汰：超出上限时删除最早插入的条目
                while len(self._finalized_event_ids) > self._finalized_max_size:
                    oldest_key = next(iter(self._finalized_event_ids))
                    del self._finalized_event_ids[oldest_key]
                if succeeded:
                    self._stats["events_succeeded"] += 1
                else:
                    self._stats["events_failed"] += 1
            # R136: 事件最终化后从 in-flight 持久化集合摘除并刷盘。
            # 锁外调用（_untrack_event_inflight 自带 _queue_lock 保护），
            # 不污染 _stats_lock。失败不影响主流程。
            try:
                self._untrack_event_inflight(event.id)
            except Exception as exc:
                logger.debug(
                    "[R136] 摘除 inflight event %s 失败（不影响主流程）: %s",
                    event.id,
                    exc,
                )
        except Exception as e:
            # R117: 不扩散异常（_process_event 调用方期望本函数 best-effort
            # 即可），但留下 debug 痕迹便于排查 stats 偏移。注意只在 debug
            # 级——这条失败本身不是用户可见的功能性 bug，warn / error 会
            # 污染正常日志噪音预算（cf. R114 的同类降噪决策）。
            logger.debug(
                "[R117] _mark_event_finalized stats update raised "
                f"(suppressed to keep _process_event flow intact): "
                f"event_id={event.id} succeeded={succeeded} "
                f"err={type(e).__name__}: {e}",
                exc_info=True,
            )

    def _schedule_retry(self, event: NotificationEvent) -> None:
        """使用 Timer 调度事件重试。

        延迟 = ``retry_delay`` + ``jitter``，``jitter`` ∈ [0,
        ``retry_delay`` * ``_RETRY_DELAY_JITTER_RATIO``]。``retry_delay
        == 0`` 时退化为「立即重试」（jitter 也跳过；见模块级常量
        ``_RETRY_DELAY_JITTER_RATIO`` 的设计说明）。
        """
        if getattr(self, "_shutdown_called", False):
            return

        try:
            base_delay = max(int(getattr(self.config, "retry_delay", 2)), 0)
        except (TypeError, ValueError):
            base_delay = 2

        if base_delay == 0:
            delay_seconds: float = 0.0
        else:
            jitter = random.uniform(0.0, base_delay * _RETRY_DELAY_JITTER_RATIO)
            delay_seconds = base_delay + jitter

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

    # ------------------------------------------------------------------
    # R136: in-flight 持久化辅助方法
    # ------------------------------------------------------------------
    #
    # 设计要点：
    # - 持久化文件 = 当前 ``_inflight_persisted_ids`` 集合内事件的 dump，
    #   原子替换（写 .tmp → ``os.replace``）。
    # - 入队 / 摘除两条路径都过 ``_queue_lock`` 保证集合一致性。
    # - 序列化用 ``NotificationEvent.model_dump`` 以便复用 pydantic 校验
    #   逻辑；启动 load 不重建 ``NotificationEvent`` 对象，仅返回原始
    #   dict 给 ``get_status`` 使用——避免 enum 反序列化在 pydantic
    #   v2 模式下的 strict mode 噪音。
    # - 集合空时主动删除文件，避免长期保留空 envelope。
    # - 任何 disk I/O 都包 try/except，磁盘满 / 权限错误 / 文件锁竞争
    #   都不能让通知主路径挂掉。

    def _inflight_file_path(self) -> Path | None:
        """R136 — 返回 inflight 持久化文件绝对路径，或 ``None`` 表示
        持久化不可用（无 config dir 时）。"""
        base = _get_inflight_file_dir()
        if base is None:
            return None
        return base / _INFLIGHT_FILE_NAME

    def _track_event_inflight(self, event: NotificationEvent) -> None:
        """R136 — 把事件 id 加入持久化集合并刷盘。

        与 ``_create_event`` 入队后路径同步调用；自带 ``_queue_lock``
        保护，复用既有锁避免引入新锁等级冲突。

        ``getattr`` 兜底：兼容绕开 ``__init__`` 的测试 helper / 老调
        用路径——首次访问时按需补建空集合，避免 ``AttributeError`` 把
        通知主路径打挂。"""
        with self._queue_lock:
            ids = getattr(self, "_inflight_persisted_ids", None)
            if ids is None:
                self._inflight_persisted_ids = set()
                ids = self._inflight_persisted_ids
            ids.add(event.id)
            # 把当前队列里 id 仍在集合内的事件序列化落盘
            self._persist_inflight_unlocked()

    def _untrack_event_inflight(self, event_id: str) -> None:
        """R136 — 把事件 id 从持久化集合摘除并刷盘。

        与 ``_mark_event_finalized`` 同步调用；最后一个 id 摘除后会主
        动删除磁盘文件，避免长期保留空 envelope。"""
        with self._queue_lock:
            ids = getattr(self, "_inflight_persisted_ids", None)
            if ids is None or event_id not in ids:
                return
            ids.discard(event_id)
            self._persist_inflight_unlocked()

    def _persist_inflight_unlocked(self) -> None:
        """R136 — caller 持 ``_queue_lock`` 时写盘。

        - 持久化集合空 → 删文件（不留空 envelope）；
        - 否则 dump events 列表 → 写 ``.tmp`` → ``os.replace``。
        - 失败仅 debug 日志，不抛异常（caller 期望 best-effort）。

        ``getattr`` 兜底：与 ``_track_event_inflight`` 同款，绕开
        ``__init__`` 的测试 helper 调用时不挂。"""
        path = self._inflight_file_path()
        if path is None:
            return
        ids = getattr(self, "_inflight_persisted_ids", set())
        try:
            if not ids:
                # 空集合：删文件
                if path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass
                return

            # 从 _event_queue 里挑出 id 仍在持久化集合内的事件
            events_to_save = [e for e in self._event_queue if e.id in ids]
            payload: dict[str, Any] = {
                "schema_version": _INFLIGHT_SCHEMA_VERSION,
                "saved_at": datetime.now(UTC).isoformat(),
                "events": [
                    {
                        # NotificationEvent.model_dump() 输出含 trigger /
                        # types / priority 等 enum，pydantic v2 默认会
                        # dump 成枚举值（str），重启读时直接 dict 暴露给
                        # stats，不重建模型对象避免 strict mode 噪音
                        **e.model_dump(mode="json"),
                        "saved_at_ts": time.time(),
                    }
                    for e in events_to_save
                ],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            os.replace(tmp, path)
        except Exception as exc:
            logger.debug(
                "[R136] 持久化 inflight events 失败（不影响主流程）: %s",
                exc,
            )

    def _load_persisted_inflight_events(self) -> list[dict[str, Any]]:
        """R136 — 启动时从磁盘读 inflight events，返回 ``list[dict]``。

        容错策略（任一失败都返回 ``[]`` 而不抛）：
        - 文件不存在 → ``[]``；
        - JSON 解析失败 → ``[]`` + warn；
        - schema_version 不匹配 → ``[]`` + warn（未来加 migrator 时统一处理）；
        - events 不是 list / 元素不是 dict → 跳过单元；
        - ``saved_at_ts`` 距今超 ``_INFLIGHT_TTL_SECONDS`` → 过期丢弃；
        - 文件权限 / I/O 错误 → ``[]`` + warn。"""
        path = self._inflight_file_path()
        if path is None:
            return []
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[R136] inflight 持久化文件损坏，跳过: %s", exc)
            return []
        if not isinstance(data, dict):
            return []
        if data.get("schema_version") != _INFLIGHT_SCHEMA_VERSION:
            logger.warning(
                "[R136] inflight 文件 schema_version 不匹配，跳过: %s",
                data.get("schema_version"),
            )
            return []
        events = data.get("events")
        if not isinstance(events, list):
            return []

        now = time.time()
        filtered: list[dict[str, Any]] = []
        for entry in events:
            if not isinstance(entry, dict):
                continue
            saved_at_ts = entry.get("saved_at_ts", 0)
            if not isinstance(saved_at_ts, (int, float)):
                continue
            # TTL 过滤：超期事件直接丢，避免重启后看到一周前的 stale
            # in-flight（典型场景：用户关电脑回家，第二天开机）
            if now - saved_at_ts > _INFLIGHT_TTL_SECONDS:
                continue
            filtered.append(entry)
        return filtered

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

            # **R114**：``_shutdown_called`` 与 ``_executor.submit`` 之间存在
            # TOCTOU 窗口——线程 A 在第 579 行已经检查 ``_shutdown_called=False``
            # 进入本块，线程 B 同时调 ``shutdown()`` 把 ``_shutdown_called=True`` +
            # ``_executor.shutdown(cancel_futures=True)``，此时线程 A 再调
            # ``self._executor.submit(...)`` 会抛 ``RuntimeError: cannot schedule
            # new futures after shutdown``。R114 之前这条 RuntimeError 由外层
            # ``except Exception`` 兜底，被记成 ERROR 级 ``处理通知事件失败``
            # 日志——日志归因不准（看上去像 provider 故障，实际是 atexit /
            # restart / 显式 shutdown 引发的良性竞态），还会污染监控告警。
            #
            # 修复策略：把 submit 循环单独包一层 ``try/except RuntimeError``，
            # 命中后识别为"shutdown 并发竞态"——和第 579 行的"shutdown 后跳过
            # 事件"语义一致——降级为 DEBUG 日志并 return；不进入外层 except，
            # 也不触发重试。注意只 catch ``RuntimeError`` 这一狭窄异常类型，
            # 真正的 provider / 序列化异常仍由外层 except 兜底，可观测性不变。
            futures = {}
            try:
                for notification_type in event.types:
                    future = self._executor.submit(
                        self._send_single_notification, notification_type, event
                    )
                    futures[future] = notification_type
            except RuntimeError as submit_err:
                # 二次确认：``_shutdown_called`` 真为 True 时才走 R114 静默路径，
                # 否则（比如 RuntimeError 来自其它原因）仍交给外层 except 处理。
                if getattr(self, "_shutdown_called", False):
                    logger.debug(
                        f"[R114] _executor.submit 与 shutdown 竞态，跳过事件: "
                        f"{event.id} (submitted={len(futures)}/{len(event.types)}, "
                        f"reason={submit_err})"
                    )
                    # 已 submit 的 future 让 cancel_futures=True 自然取消即可。
                    return
                raise

            success_count = 0
            completed_count = 0
            total_count = len(futures)

            # 【优化】使用 try-except 捕获超时，避免未完成任务导致错误日志
            # as_completed 超时时会抛出 TimeoutError: "N (of M) futures unfinished"
            #
            # Window = ``bark_timeout`` + buffer：见模块顶部
            # ``_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS`` 的设计说明。这一行历史上
            # 硬编码 ``timeout=15``，会在 ``bark_timeout > 15`` 时让用户重复
            # 收到 Bark 推送——已通过 ``test_notification_manager_as_completed_timeout``
            # 锁住 contract。
            try:
                bark_timeout = max(int(getattr(self.config, "bark_timeout", 10)), 1)
                as_completed_timeout = (
                    bark_timeout + _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS
                )
                for future in as_completed(futures, timeout=as_completed_timeout):
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
                            # R145: 连续成功 / 连续失败计数
                            "success_streak": 0,
                            "failure_streak": 0,
                        },
                    )
                    stats["attempts"] += 1
                    stats["failure"] += 1
                    stats["last_failure_at"] = time.time()
                    stats["last_error"] = "provider_not_registered"
                    # R145: not_registered 视为失败，累加 failure_streak
                    stats["failure_streak"] = (
                        int(stats.get("failure_streak", 0) or 0) + 1
                    )
                    stats["success_streak"] = 0
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
                            # R145: 连续成功 / 连续失败计数
                            "success_streak": 0,
                            "failure_streak": 0,
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
                            # R145: 连续成功 / 连续失败计数
                            "success_streak": 0,
                            "failure_streak": 0,
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
                        # R145: success_streak / failure_streak 维护——
                        # 成功 → 累加 success_streak，failure_streak 归零
                        stats["success_streak"] = (
                            int(stats.get("success_streak", 0) or 0) + 1
                        )
                        stats["failure_streak"] = 0
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
                        # R145: 失败 → 累加 failure_streak，success_streak 归零
                        stats["failure_streak"] = (
                            int(stats.get("failure_streak", 0) or 0) + 1
                        )
                        stats["success_streak"] = 0
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
                            # R145: 连续成功 / 连续失败计数
                            "success_streak": 0,
                            "failure_streak": 0,
                        },
                    )
                    stats["failure"] += 1
                    stats["last_failure_at"] = time.time()
                    stats["last_error"] = f"{type(e).__name__}: {e}"[:800]
                    # R145: 异常路径视为失败，累加 failure_streak
                    stats["failure_streak"] = (
                        int(stats.get("failure_streak", 0) or 0) + 1
                    )
                    stats["success_streak"] = 0
            except Exception:
                pass

            return False

    def _handle_fallback(self, event: NotificationEvent):
        """所有渠道失败时触发 notification_fallback 回调"""
        logger.info(f"执行降级处理: {event.id}")
        self.trigger_callbacks("notification_fallback", event)

    def shutdown(self, wait: bool = False, grace_period: float = 0.0) -> None:
        """关闭管理器，取消延迟 Timer 并关闭线程池（幂等）。

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

        # grace-wait：给 in-flight worker 显式时间窗口收尾。
        # 仅在 ``wait=False`` 且 ``grace_period > 0`` 时启用——
        # ``wait=True`` 已是无限等待，不需要再叠加 grace。
        if not wait and grace_period > 0:
            try:
                deadline = time.monotonic() + grace_period
                # ``_threads`` 是 ``ThreadPoolExecutor`` 私有属性
                # （CPython 3.9-3.13 一直存在），这里仅 read 不 mutate。
                worker_threads = list(getattr(self._executor, "_threads", ()) or ())
                for t in worker_threads:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        # 超时了，剩下的 worker 留给 Python 主进程退出阶段 join
                        break
                    try:
                        t.join(timeout=remaining)
                    except Exception:
                        # join 罕见地抛异常（线程对象失效等），跳过
                        continue
            except Exception as e:
                logger.debug(f"grace-wait 期间异常（忽略）: {e}")

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
        # 与 ``__init__`` 保持完全一致——不能在这里 fork 出独立的常量，
        # 否则未来加新通知渠道时容易遗漏一处。
        self._executor = ThreadPoolExecutor(
            max_workers=_NOTIFICATION_WORKER_COUNT,
            thread_name_prefix="NotificationWorker",
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
                self.config.bark_url_template = cfg.get(
                    "bark_url_template", "{base_url}/?task_id={task_id}"
                )
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
                    from ai_intervention_agent.notification_providers import (
                        BarkNotificationProvider,
                    )

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

            # 内部 sound_volume 始终为 0.0-1.0，保存到文件时转为 0-100 整数
            sound_volume_int = round(self.config.sound_volume * 100)

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
                "bark_url_template": self.config.bark_url_template,
            }

            # 更新配置文件
            config_mgr.update_section("notification", notification_config)
            logger.debug("配置已保存到文件")
        except Exception as e:
            logger.error(f"保存配置到文件失败: {e}", exc_info=True)

    def get_status(self) -> dict[str, Any]:
        """返回管理器状态：enabled/providers/queue_size/config/stats。

        R136：``status`` 增加两个字段：
        - ``inflight_persisted_count``：当前进程持久化集合中的 inflight
          事件数（与磁盘文件 events 列表长度一致，未过 TTL）。
        - ``inflight_seen_at_startup``：本次进程启动时一次性 load 的
          上次进程退出时还在 in-flight 的事件元数据列表（list[dict]，
          每项 = 序列化的 NotificationEvent + ``saved_at_ts``）。该字
          段仅"暴露给 stats"，进程不会自动重发——避免重启后用户被旧
          通知刷屏；运维 / dashboard 可基于此发出 alarm。
        """
        # 线程安全地获取队列大小
        with self._queue_lock:
            queue_size = len(self._event_queue)
            # R136: getattr 兜底兼容绕开 __init__ 的测试 helper / 老调用
            # 路径——这条路径不应该是常态，但 fail-soft 比 fail-hard 更
            # 适合 status 端点（端点本身不应当因为内部字段缺失就 5xx）。
            inflight_persisted_count = len(
                getattr(self, "_inflight_persisted_ids", set())
            )

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
                    for st in providers_stats.values():
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
            providers = [t.value for t in self._providers]

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
            # R136: 当前进程持久化集合的 inflight 事件数（≥0）；
            # 启动时一次性 load 的上次未投递事件元数据列表（list 副本，
            # 防 caller 改写内部状态）。``getattr`` 兜底兼容绕开 __init__
            # 的测试 helper / 老调用路径。
            "inflight_persisted_count": inflight_persisted_count,
            "inflight_seen_at_startup": list(
                getattr(self, "_inflight_seen_at_startup", [])
            ),
        }


# 全局通知管理器实例
notification_manager = NotificationManager()

# 【资源生命周期】进程退出时尽量清理后台资源（Timer/线程池）
# - 避免测试或 REPL 退出时出现线程池阻塞
# - shutdown() 幂等，重复调用安全
import atexit  # noqa: E402

# atexit 的 grace 窗口（秒）。1.5s 是经验值：
#   - 短到不会让用户察觉"程序卡住"（人对 <2s 退出延迟一般无感）；
#   - 长到能覆盖一次完整的 Bark / 钉钉 HTTP request（典型 200-800ms），
#     让 in-flight 通知有机会自然 ack 后再让进程退出。
# 如果 worker 在 grace 内未完成（例如卡 osascript），剩余 join 留给
# Python 主进程退出阶段（worker 默认 non-daemon，主进程会再等一次），
# grace_period 这一层只负责"显式可观测"。
_ATEXIT_GRACE_PERIOD_SECONDS = 1.5


def _shutdown_global_notification_manager():
    try:
        notification_manager.shutdown(
            wait=False, grace_period=_ATEXIT_GRACE_PERIOD_SECONDS
        )
    except Exception:
        # 退出阶段不再抛异常
        pass


atexit.register(_shutdown_global_notification_manager)
