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
from typing import Any, ClassVar, cast

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

logger = EnhancedLogger(__name__)


_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS = 5
_MISSING_STATS_FIELD = object()
_NOTIFICATION_LATENCY_INF_BUCKET = float("inf")


def _new_provider_stats() -> dict[str, Any]:
    """Return the default per-provider stats payload."""
    return {
        "attempts": 0,
        "success": 0,
        "failure": 0,
        "last_success_at": None,
        "last_failure_at": None,
        "last_error": None,
        "last_latency_ms": None,
        "latency_ms_total": 0,
        "latency_ms_count": 0,
        "success_streak": 0,
        "failure_streak": 0,
    }


def _get_or_create_provider_stats(
    stats_root: dict[str, Any], provider_name: str
) -> dict[str, Any]:
    """Return provider stats, allocating default dicts only when missing."""
    providers_obj = stats_root.get("providers", _MISSING_STATS_FIELD)
    if providers_obj is _MISSING_STATS_FIELD:
        providers_obj = {}
        stats_root["providers"] = providers_obj

    providers = cast("dict[str, Any]", providers_obj)
    try:
        stats_obj = providers[provider_name]
    except KeyError:
        stats_obj = _new_provider_stats()
        providers[provider_name] = stats_obj

    return cast("dict[str, Any]", stats_obj)


_INFLIGHT_FILE_NAME: str = "notification_inflight.json"
_INFLIGHT_SCHEMA_VERSION: int = 1
_INFLIGHT_TTL_SECONDS: int = 300
_COMPACT_JSON_SEPARATORS: tuple[str, str] = (",", ":")


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


_NOTIFICATION_WORKER_COUNT = len(NotificationType)


_RETRY_DELAY_JITTER_RATIO = 0.5


class NotificationConfig(BaseModel):
    """通知配置类 - 全局开关/Web/声音/触发时机/重试/移动优化/Bark 等配置。"""

    model_config = ConfigDict(validate_assignment=True)

    enabled: bool = True
    debug: bool = False

    web_enabled: bool = True
    web_permission_auto_request: bool = True
    web_icon: str = "default"
    web_timeout: int = 5000

    sound_enabled: bool = True
    sound_volume: float = 0.8
    sound_file: str = "default"
    sound_mute: bool = False

    trigger_immediate: bool = True
    trigger_delay: int = 30
    trigger_repeat: bool = False
    trigger_repeat_interval: int = 60

    retry_count: int = 3
    retry_delay: int = 2
    fallback_enabled: bool = True

    mobile_optimized: bool = True
    mobile_vibrate: bool = True

    bark_enabled: bool = False
    bark_url: str = ""
    bark_device_key: str = ""
    bark_icon: str = ""
    bark_action: str = "none"
    bark_timeout: int = 10

    bark_url_template: str = "{base_url}/?task_id={task_id}"

    system_enabled: bool = False
    macos_native_enabled: bool = True

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

    _instance = None
    _lock = threading.Lock()

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

            self._providers: dict[NotificationType, Any] = {}
            self._providers_lock = threading.Lock()

            self._event_queue: list[NotificationEvent] = []
            self._queue_lock = threading.Lock()

            self._config_lock = threading.Lock()

            self._config_file_mtime: float = 0.0

            self._worker_thread = None
            self._stop_event = threading.Event()

            self._executor = ThreadPoolExecutor(
                max_workers=_NOTIFICATION_WORKER_COUNT,
                thread_name_prefix="NotificationWorker",
            )

            self._delayed_timers: dict[str, threading.Timer] = {}
            self._delayed_timers_lock = threading.Lock()
            self._shutdown_called: bool = False

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

            self._provider_latency_histograms: dict[str, dict[str, Any]] = {}

            self._finalized_event_ids: dict[str, None] = {}
            self._finalized_max_size: int = 500

            self._inflight_persisted_ids: set[str] = set()
            self._inflight_seen_at_startup: list[dict[str, Any]] = []

            self._callbacks_lock = threading.Lock()
            self._callbacks: dict[str, list[Callable]] = {}

            self._initialized = True

            if self.config.debug:
                logger.setLevel(logging.DEBUG)
                logger.debug("通知管理器初始化完成（调试模式）")
            else:
                logger.info("通知管理器初始化完成")

            if self.config.bark_enabled:
                self._update_bark_provider()
                logger.info("已根据初始配置注册 Bark 通知提供者")

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

    def reset_for_testing(self) -> None:
        """R323 (cycle-34 #B2) · **Test-only**: 重置 singleton instance state
        以实现跨测试隔离 (与 R319 ``_create_test_instance()`` 互补)。

        **为什么需要两个 helper?**

        - **R319 ``_create_test_instance()``** (classmethod): 创建一个**新**
          的 fresh instance, **不操作** singleton ``_instance``。适合需要
          完全独立 instance 的测试 (e.g. R145, 测 streak 累加逻辑)
        - **R323 ``reset_for_testing()``** (instance method, 本方法): 重置
          ``notification_manager`` singleton 自身的 state, 让所有从
          ``from ai_intervention_agent.notification_manager import
          notification_manager`` 拿到 singleton 的代码 (e.g. ``web_ui_routes``
          的多个 route handler) 在每个测试开始时看到 fresh state, 不被前一
          个测试污染

        **R323 重置范围**:

        - state dicts: ``_stats`` (含完整 schema) / ``_providers`` /
          ``_callbacks`` / ``_delayed_timers`` /
          ``_provider_latency_histograms`` / ``_finalized_event_ids`` /
          ``_event_queue``
        - inflight: ``_inflight_persisted_ids`` /
          ``_inflight_seen_at_startup``

        **R323 不重置** (保留 singleton 完整性):

        - ``config`` (由 ConfigManager 控制, conftest.py 已有 reload 逻辑)
        - ``_initialized`` (避免触发 ``__init__`` 重新跑 config load)
        - ``_executor`` / ``_worker_thread`` / ``_stop_event`` (由 shutdown
          / restart 处理, R323 不参与 lifecycle)
        - lock instances 本身 (``_stats_lock`` 等不替换, 因为正在被并发持
          有的 lock 不能换掉, 只能让锁内 state 被覆盖)

        **conftest.py 自动调用 (R323 同 commit)**:
        ``_isolate_config_and_notification_singletons`` fixture 在每个测试
        前后都会调用 ``notification_manager.reset_for_testing()``, 让默认行
        为是 "singleton 跨测试隔离全自动化"。测试方不需要主动调用, 也不
        需要在 setUp 维护一长串 reset 代码。

        **Pattern lineage (test-isolation, v3.8)**:

        - 1st app: R316 (cycle-33 #A1) — R145 setUp 显式补充缺失 attr (单
          点修复, "止血")
        - 2nd app: R319 (cycle-33 #A2) — ``_create_test_instance()`` class
          method (集中化 helper for fresh instance, "升级")
        - **3rd app: R323 (本 commit, cycle-34 #B2)** — ``reset_for_testing()``
          instance method + conftest fixture 自动调用 (singleton 跨测试隔
          离自动化, "全覆盖")

        到 R323 cycle-34 #B2, **v3.8 test-isolation pattern 完全工业化** (3
        app), 是 v3.8 第 2 个全工业化 pattern (与 R322 idempotent 同 cycle
        达到全工业化).
        """
        with self._stats_lock:
            self._stats = {
                "events_total": 0,
                "events_succeeded": 0,
                "events_failed": 0,
                "attempts_total": 0,
                "retries_scheduled": 0,
                "last_event_id": None,
                "last_event_at": None,
                "providers": {},
            }
            self._provider_latency_histograms = {}
            self._finalized_event_ids = {}

        with self._queue_lock:
            self._event_queue = []

        with self._callbacks_lock:
            self._callbacks = {}

        with self._delayed_timers_lock:
            for timer in tuple(self._delayed_timers.values()):
                try:
                    timer.cancel()
                except Exception:
                    pass
            self._delayed_timers = {}

        with self._providers_lock:
            pass

        self._inflight_persisted_ids = set()
        self._inflight_seen_at_startup = []

    @classmethod
    def _create_test_instance(cls) -> "NotificationManager":
        """R319 (cycle-33 #A2) · **Test-only**: 创建一个完整初始化的 fresh
        instance, 绕过 singleton + config file load + background worker。

        **为什么需要**:

        R316 (cycle-33 #A1) 修复了 R145 setUp 的间歇性 flake — 根因是 R145
        ``__new__(NotificationManager)`` 拿到的 singleton instance 在某些
        测试顺序下没有 ``_provider_latency_histograms`` 等 attr, 导致
        ``_send_single_notification`` 下游的 latency histogram 记录 method
        触发 ``AttributeError`` 被外层 ``except`` 静默吞掉, streak 不更新,
        测试 fail (R197 invariant 限制 latency 记录只能从 1 处入口调用,
        所以这里不再展开具体方法名)。

        R316 fix 在 R145 setUp 显式补充 3 个缺失 attr, 是**单点修复**。但
        其他测试文件 (``test_notification_shutdown_race_r114`` /
        ``test_notification_manager`` 等共 5 处) 也用 ``__new__()`` + 手动
        部分初始化模式, 同款 flake 风险**仍未消除**。

        R319 是 **test-isolation pattern 2nd app**, 把"完整 attr 初始化"集中
        到 NotificationManager 自己暴露的 classmethod, 调用方:

        .. code-block:: python

            self.mgr = NotificationManager._create_test_instance()

        即可拿到完整初始化的 instance, 不需要在 setUp 维护一长串 attr 列表,
        也不会随 ``__init__`` 加新 attr 而被新引入 flake。

        **覆盖的 attr** (与 ``__init__`` 完全对齐, 同 schema 但不读 config /
        不启 worker / 不 load inflight 文件):

        - locks: ``_stats_lock`` / ``_providers_lock`` / ``_callbacks_lock``
          / ``_delayed_timers_lock`` / ``_queue_lock`` / ``_config_lock``
        - state dicts: ``_stats`` (含完整 schema) / ``_providers`` /
          ``_callbacks`` / ``_delayed_timers`` / ``_provider_latency_
          histograms`` / ``_finalized_event_ids``
        - state caps: ``_finalized_max_size`` / ``_config_file_mtime``
        - lifecycle: ``_executor`` (None - 测试不启动后台 worker) /
          ``_worker_thread`` / ``_stop_event`` / ``_shutdown_called``
        - inflight: ``_inflight_persisted_ids`` / ``_inflight_seen_at_startup``
        - flags: ``_initialized`` (True - 防止意外触发 ``__init__`` 再去读
          config)
        - config: ``config`` (一个无 side-effect 的 ``NotificationConfig()``
          实例, 拿默认值)

        **不读 config file**: 避免测试环境因为缺少 ``config.toml`` 而 raise
        ``NotificationError``。``config`` 字段始终是默认 ``NotificationConfig()``,
        测试方可以通过 ``inst.config.bark_enabled = True`` 等方式 override
        任何字段而无需 patch。

        **不启 worker / 不 load inflight**: 测试要全确定性, 不引入 I/O 或
        异步副作用。

        **R145 已是 R319 第 1 个 caller** (cycle-33 R319 同 commit 迁移)。其
        他 4 处 (R114 / test_notification_manager:1101 / :1230) 暂保留, 标
        为 future-migration target. R319 不强制迁移避免风险扩散。

        Pattern lineage (test-isolation):

        - 1st app: R316 (5a15a6c, cycle-33 #A1) — R145 setUp 显式补充缺失 attr
        - **2nd app: R319 (本 commit, cycle-33 #A2)** — NotificationManager
          自己提供集中化 helper API, R145 setUp 迁移为 1st caller

        **Returns**: 全初始化的 ``NotificationManager`` instance, **不**等
        于 singleton ``_instance`` (即 ``cls._instance``)。多次调用返回不同
        instance, 适合每个 test 一个独立 instance。
        """
        inst = super().__new__(cls)
        inst._initialized = True

        inst.config = NotificationConfig()

        inst._stats_lock = threading.Lock()
        inst._providers_lock = threading.Lock()
        inst._callbacks_lock = threading.Lock()
        inst._delayed_timers_lock = threading.Lock()
        inst._queue_lock = threading.Lock()
        inst._config_lock = threading.Lock()

        inst._providers = {}
        inst._stats = {
            "events_total": 0,
            "events_succeeded": 0,
            "events_failed": 0,
            "attempts_total": 0,
            "retries_scheduled": 0,
            "last_event_id": None,
            "last_event_at": None,
            "providers": {},
        }
        inst._callbacks = {}
        inst._delayed_timers = {}
        inst._provider_latency_histograms = {}
        inst._finalized_event_ids = {}
        inst._event_queue = []

        inst._finalized_max_size = 500
        inst._config_file_mtime = 0.0

        inst._executor = None
        inst._worker_thread = None
        inst._stop_event = threading.Event()
        inst._shutdown_called = False

        inst._inflight_persisted_ids = set()
        inst._inflight_seen_at_startup = []

        return inst

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

    _DEFAULT_LATENCY_BUCKETS_SECONDS: tuple[float, ...] = (
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    )
    _DEFAULT_LATENCY_BUCKET_COUNTS: dict[float, int] = dict.fromkeys(
        _DEFAULT_LATENCY_BUCKETS_SECONDS, 0
    )
    """provider-side 通知发送的 latency 桶（秒）—— R196 / Cycle 6 重新调
    优 (CR#19 §4.1 「R190' · histogram bucket selection per-metric vs
    project-wide」follow-up)。

    R191 起步实现复用了 ``mcp_tool_call_metrics._DEFAULT_LATENCY_BUCKETS``
    （0.1 / 0.5 / 1 / 5 / 30 / 120 / 300 / 600）——逻辑上同属「人机交互延
    迟」语义。**但**实测分布完全不同：

    - **MCP tool 调用**延迟由「人类阅读问题 + 思考 + 打字」主导，典型分
      布在 10 - 300 秒，最长可达 600 秒（``auto_resubmit_timeout`` 触发
      边界）；
    - **Notification 发送**延迟由「网络往返 + provider 端处理」主导，典
      型分布在 50ms - 500ms（Bark / Pushover / system notif），极端尾部
      也不会超过 ~10 秒（超过基本是 ``http_timeout`` 配置上限）。

    CR#19 §4.1 指出：用同一组桶让两边的 cumulative distribution 看起来
    很不同——dashboard 模板得跟着 metric name 不同切换桶 axis，给运维
    平添 cognitive load。R196 拆出 notification-specific 桶 (50ms - 10s
    密集采样)，让 ``histogram_quantile(0.95, …{__name__=~"aiia_notif.*"})``
    在常见范围内得到 < 100ms 精度的 P95 估计。

    ``+Inf`` 由 snapshot helper 动态追加，不在元组里——避免 caller 误
    以为 ``+Inf`` 是真实采样上限。
    """

    def _record_provider_latency_bucket(
        self, provider_name: str, duration_seconds: float
    ) -> None:
        """把一次 provider 发送耗时写入 latency histogram。

        约定：**必须**在 ``self._stats_lock`` 已持有的临界区内调用——本
        方法不重新加锁，避免双锁死锁。调用点（``_send_single_notification``
        的 latency 记录块）天然持锁，零额外开销。

        边界处理：

        - ``duration_seconds`` < 0（时钟跳变，仅理论上）→ 静默丢弃；
        - 不存在的 provider → 自动初始化空状态；
        - 桶比较用 ``<=``（Prom histogram 标准约定 ``le="..."``）。
        """
        if duration_seconds < 0:
            return
        state = self._provider_latency_histograms.get(provider_name)
        if state is None:
            state = cast(
                "dict[str, Any]",
                {
                    "count": 0,
                    "sum_seconds": 0.0,
                    "buckets": self._DEFAULT_LATENCY_BUCKET_COUNTS.copy(),
                },
            )
            self._provider_latency_histograms[provider_name] = state
        state["count"] += 1
        state["sum_seconds"] += duration_seconds
        for upper in self._DEFAULT_LATENCY_BUCKETS_SECONDS:
            if duration_seconds <= upper:
                state["buckets"][upper] += 1

    def get_provider_latency_histograms_snapshot(
        self,
    ) -> dict[str, dict[str, Any]]:
        """返回 provider latency histogram 快照（深 copy）。

        形态与 ``mcp_tool_call_metrics.get_mcp_tool_call_latency_snapshot``
        对齐——``buckets`` 字典自动附加 ``+Inf`` 键，值 == count。
        若某 provider 还从未发送过，**不**出现在返回字典里。

        返回值是新建 dict，调用者修改不会污染内部状态。
        """
        with self._stats_lock:
            result: dict[str, dict[str, Any]] = {}
            for provider_name, state in self._provider_latency_histograms.items():
                buckets_copy = state["buckets"].copy()
                buckets_copy[_NOTIFICATION_LATENCY_INF_BUCKET] = state["count"]
                result[provider_name] = {
                    "count": state["count"],
                    "sum_seconds": state["sum_seconds"],
                    "buckets": buckets_copy,
                }
        return result

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
            callbacks_raw = self._callbacks.get(event_name)
            callbacks = list(callbacks_raw) if callbacks_raw is not None else []

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

        if getattr(self, "_shutdown_called", False):
            logger.debug("通知管理器已关闭，跳过发送")
            return ""

        created_at_ts = time.time()
        event_id = f"notification_{int(created_at_ts * 1000)}_{uuid.uuid4().hex[:8]}"

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

        event_priority = NotificationPriority.NORMAL
        if isinstance(priority, NotificationPriority):
            event_priority = priority
        elif isinstance(priority, str):
            try:
                event_priority = NotificationPriority(priority)
            except Exception:
                event_priority = NotificationPriority.NORMAL

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

        try:
            with self._stats_lock:
                self._stats["events_total"] += 1
                self._stats["last_event_id"] = event_id
                self._stats["last_event_at"] = created_at_ts
        except Exception:
            pass

        with self._queue_lock:
            self._event_queue.append(event)

            max_keep = 200
            if len(self._event_queue) > max_keep:
                self._event_queue = self._event_queue[-max_keep:]

        try:
            self._track_event_inflight(event)
        except Exception as exc:
            logger.debug(
                "[R136] 持久化 inflight event %s 失败（不影响主流程）: %s",
                event_id,
                exc,
            )

        logger.debug(f"通知事件已创建: {event_id} - {title}")

        if trigger == NotificationTrigger.IMMEDIATE:
            self._process_event(event)
        elif trigger == NotificationTrigger.DELAYED:
            if getattr(self, "_shutdown_called", False):
                logger.debug("通知管理器已关闭，跳过延迟通知调度")
                return event_id

            def _delayed_run():
                try:
                    self._process_event(event)
                finally:
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

                while len(self._finalized_event_ids) > self._finalized_max_size:
                    oldest_key = next(iter(self._finalized_event_ids))
                    del self._finalized_event_ids[oldest_key]
                if succeeded:
                    self._stats["events_succeeded"] += 1
                else:
                    self._stats["events_failed"] += 1

            try:
                self._untrack_event_inflight(event.id)
            except Exception as exc:
                logger.debug(
                    "[R136] 摘除 inflight event %s 失败（不影响主流程）: %s",
                    event.id,
                    exc,
                )
        except Exception as e:
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
        ids = getattr(self, "_inflight_persisted_ids", None)
        try:
            if not ids:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return

            saved_at_ts = time.time()
            saved_at_iso = datetime.fromtimestamp(saved_at_ts, UTC).isoformat()
            payload: dict[str, Any] = {
                "schema_version": _INFLIGHT_SCHEMA_VERSION,
                "saved_at": saved_at_iso,
                "events": [
                    {
                        **e.model_dump(mode="json"),
                        "saved_at_ts": saved_at_ts,
                    }
                    for e in self._event_queue
                    if e.id in ids
                ],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=_COMPACT_JSON_SEPARATORS,
                )
            )
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
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("[R136] inflight 持久化文件损坏，跳过: %s", exc)
            return []

        try:
            data = json.loads(raw)
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

            if now - saved_at_ts > _INFLIGHT_TTL_SECONDS:
                continue
            filtered.append(entry)
        return filtered

    def _process_event(self, event: NotificationEvent):
        """并行发送通知到所有渠道，失败时重试或降级"""

        if getattr(self, "_shutdown_called", False):
            logger.debug(f"通知管理器已关闭，跳过事件处理: {event.id}")
            return

        try:
            logger.debug(f"处理通知事件: {event.id}")

            try:
                with self._stats_lock:
                    self._stats["attempts_total"] += 1
            except Exception:
                pass

            if not event.types:
                logger.debug(f"通知事件无指定类型，跳过: {event.id}")
                return

            futures = {}
            try:
                for notification_type in event.types:
                    future = self._executor.submit(
                        self._send_single_notification, notification_type, event
                    )
                    futures[future] = notification_type
            except RuntimeError as submit_err:
                if getattr(self, "_shutdown_called", False):
                    logger.debug(
                        f"[R114] _executor.submit 与 shutdown 竞态，跳过事件: "
                        f"{event.id} (submitted={len(futures)}/{len(event.types)}, "
                        f"reason={submit_err})"
                    )

                    return
                raise

            success_count = 0
            completed_count = 0
            total_count = len(futures)

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
                unfinished_count = total_count - completed_count
                logger.warning(
                    f"通知发送部分超时: {event.id} - "
                    f"{completed_count}/{total_count} 完成，{unfinished_count} 未完成"
                )

                for future, notification_type in futures.items():
                    if not future.done():
                        cancelled = future.cancel()
                        if cancelled:
                            logger.debug(f"已取消排队任务: {notification_type.value}")
                        else:
                            logger.debug(
                                f"任务正在运行，无法取消: {notification_type.value}"
                            )

            self.trigger_callbacks("notification_sent", event, success_count)

            if success_count == 0:
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

                self._mark_event_finalized(event, succeeded=False)
                if self.config.fallback_enabled:
                    logger.warning(f"所有通知方式失败，启用降级处理: {event.id}")
                    self._handle_fallback(event)
            else:
                self._mark_event_finalized(event, succeeded=True)
                logger.info(
                    f"通知发送完成: {event.id} - 成功 {success_count}/{total_count}"
                )

        except Exception as e:
            logger.error(f"处理通知事件失败: {event.id} - {e}", exc_info=True)

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

            try:
                with self._stats_lock:
                    stats = _get_or_create_provider_stats(
                        self._stats, notification_type.value
                    )
                    stats["attempts"] += 1
                    stats["failure"] += 1
                    stats["last_failure_at"] = time.time()
                    stats["last_error"] = "provider_not_registered"

                    stats["failure_streak"] = (
                        int(stats.get("failure_streak", 0) or 0) + 1
                    )
                    stats["success_streak"] = 0
            except Exception:
                pass
            return False

        try:
            try:
                with self._stats_lock:
                    stats = _get_or_create_provider_stats(
                        self._stats, notification_type.value
                    )
                    stats["attempts"] += 1
            except Exception:
                pass

            started_at = time.time()

            if hasattr(provider, "send"):
                ok = bool(provider.send(event))
            else:
                logger.error(f"通知提供者缺少send方法: {notification_type.value}")
                ok = False
            completed_at = time.time()
            latency_ms = max(int((completed_at - started_at) * 1000), 0)

            try:
                with self._stats_lock:
                    stats = _get_or_create_provider_stats(
                        self._stats, notification_type.value
                    )
                    stats["last_latency_ms"] = latency_ms
                    stats["latency_ms_total"] = int(
                        stats.get("latency_ms_total", 0) or 0
                    ) + int(latency_ms)
                    stats["latency_ms_count"] = (
                        int(stats.get("latency_ms_count", 0) or 0) + 1
                    )

                    # 才是 Prom histogram ``aiia_notification_send_duration

                    self._record_provider_latency_bucket(
                        notification_type.value, latency_ms / 1000.0
                    )
                    if ok:
                        stats["success"] += 1
                        stats["last_success_at"] = completed_at
                        stats["last_error"] = None

                        stats["success_streak"] = (
                            int(stats.get("success_streak", 0) or 0) + 1
                        )
                        stats["failure_streak"] = 0
                    else:
                        stats["failure"] += 1
                        stats["last_failure_at"] = completed_at

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

                        stats["failure_streak"] = (
                            int(stats.get("failure_streak", 0) or 0) + 1
                        )
                        stats["success_streak"] = 0
            except Exception:
                pass

            return ok
        except Exception as e:
            logger.error(f"发送通知失败 {notification_type.value}: {e}", exc_info=True)

            try:
                with self._stats_lock:
                    stats = _get_or_create_provider_stats(
                        self._stats, notification_type.value
                    )
                    stats["failure"] += 1
                    stats["last_failure_at"] = time.time()
                    stats["last_error"] = f"{type(e).__name__}: {e}"[:800]

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

        try:
            with self._delayed_timers_lock:
                timers = tuple(self._delayed_timers.values())
                self._delayed_timers.clear()
            for t in timers:
                try:
                    t.cancel()
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"取消延迟通知 Timer 失败（忽略）: {e}")

        try:
            self._executor.shutdown(wait=wait, cancel_futures=True)
        except TypeError:
            self._executor.shutdown(wait=wait)
        except Exception as e:
            logger.debug(f"关闭通知线程池失败（忽略）: {e}")

        if not wait and grace_period > 0:
            try:
                deadline = time.monotonic() + grace_period

                worker_threads = tuple(getattr(self._executor, "_threads", ()) or ())
                for t in worker_threads:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        t.join(timeout=remaining)
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"grace-wait 期间异常（忽略）: {e}")

        try:
            with self._providers_lock:
                providers = tuple(self._providers.values())
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

            config_file_path = config_mgr.config_file
            try:
                current_mtime = config_file_path.stat().st_mtime

                if not force and current_mtime == self._config_file_mtime:
                    logger.debug("配置文件未变化，跳过刷新")
                    return

                self._config_file_mtime = current_mtime
            except OSError:
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

            bark_now_enabled = self.config.bark_enabled
            if bark_was_enabled != bark_now_enabled:
                self._update_bark_provider()

    def _update_bark_provider(self):
        """根据 bark_enabled 动态添加/移除 Bark 提供者（延迟导入避免循环依赖）"""
        try:
            if self.config.bark_enabled:
                with self._providers_lock:
                    bark_registered = NotificationType.BARK in self._providers
                if not bark_registered:
                    from ai_intervention_agent.notification_providers import (
                        BarkNotificationProvider,
                    )

                    bark_provider = BarkNotificationProvider(self.config)
                    self.register_provider(NotificationType.BARK, bark_provider)
                    logger.info("Bark通知提供者已动态添加")
            else:
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

            sound_volume_int = round(self.config.sound_volume * 100)

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

        with self._queue_lock:
            queue_size = len(self._event_queue)

            inflight_persisted_ids = getattr(self, "_inflight_persisted_ids", None)
            inflight_persisted_count = (
                len(inflight_persisted_ids) if inflight_persisted_ids is not None else 0
            )

        try:
            with self._stats_lock:
                stats_snapshot = self._stats.copy()
                providers_stats_raw = stats_snapshot.pop("providers", None)
                providers_stats = (
                    {
                        k: v.copy() if isinstance(v, dict) else dict(v)
                        for k, v in providers_stats_raw.items()
                    }
                    if isinstance(providers_stats_raw, dict)
                    else {}
                )
                stats_snapshot["providers"] = providers_stats

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

        inflight_seen_at_startup = getattr(self, "_inflight_seen_at_startup", None)
        inflight_seen_at_startup_copy = (
            list(inflight_seen_at_startup)
            if inflight_seen_at_startup is not None
            else []
        )

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
            "inflight_persisted_count": inflight_persisted_count,
            "inflight_seen_at_startup": inflight_seen_at_startup_copy,
        }


notification_manager = NotificationManager()


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
        pass


atexit.register(_shutdown_global_notification_manager)
