"""增强日志模块 - 基于 Loguru，提供脱敏、防注入、去重，全部输出到 stderr（MCP 友好）。"""

import collections
import itertools
import logging
import os
import re
import sys
import threading
import time
from typing import Any

from loguru import logger as _loguru_logger

_SENSITIVE_LOG_MARKERS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "private",
    "sk-",
    "xox",
    "ghp_",
    "ghs_",
    "gho_",
    "ghu_",
    "ghr_",
    "github_pat_",
    "AKIA",
    "AIza",
    "hf_",
    "sk_live_",
    "sk_test_",
    "pk_live_",
    "pk_test_",
    "http://",
    "https://",
    "eyJ",
)


class LogSanitizer:
    """日志脱敏 - 检测并替换密码、API key 等敏感信息为 ``***REDACTED***``。"""

    def __init__(self) -> None:
        self.sensitive_patterns = [
            re.compile(r'password["\']?\s*[:=]\s*["\']?[^\s"\']{6,}["\']?'),
            re.compile(r'passwd["\']?\s*[:=]\s*["\']?[^\s"\']{6,}["\']?'),
            re.compile(
                r'secret[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9._-]{16,}["\']?'
            ),
            re.compile(
                r'private[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9._-]{16,}["\']?'
            ),
            re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
            re.compile(r"\bxox[bpasr]-[A-Za-z0-9-]{20,}\b"),
            re.compile(r"\bgh[psour]_[A-Za-z0-9]{36}\b"),
            re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
            re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
            re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
            re.compile(r"\bhf_[A-Za-z0-9]{34,}\b"),
            re.compile(r"\b(?:sk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
            re.compile(r"(https?://)([^:/\s]+):([^@/\s]+)@"),
            re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        ]

    def sanitize(self, message: str) -> str:
        """脱敏消息中的敏感信息。"""

        for marker in _SENSITIVE_LOG_MARKERS:
            if marker in message:
                break
        else:
            return message
        for pattern in self.sensitive_patterns:
            if pattern.pattern.startswith("(https?://)"):
                message = pattern.sub(r"\1\2:***REDACTED***@", message)
            else:
                message = pattern.sub("***REDACTED***", message)
        return message


_global_sanitizer = LogSanitizer()


class LogDeduplicator:
    """日志去重器 - 时间窗口内相同消息只记录一次，使用 hash() 高效判重。"""

    _LAZY_CLEANUP_INTERVAL_SECONDS: float = 30.0

    def __init__(self, time_window: float = 5.0, max_cache_size: int = 1000) -> None:
        """初始化时间窗口和缓存"""
        self.time_window = time_window
        self.max_cache_size = max_cache_size
        self.cache: dict[int, tuple[float, int]] = {}
        self.lock = threading.Lock()

        self._last_cleanup_time: float = 0.0

    def should_log(self, message: str) -> tuple[bool, str | None]:
        """检查是否应记录，返回 (should_log, duplicate_info)"""
        with self.lock:
            current_time = time.monotonic()
            msg_hash = hash(message)

            if (
                current_time - self._last_cleanup_time
                >= self._LAZY_CLEANUP_INTERVAL_SECONDS
            ):
                self._cleanup_cache(current_time)
                self._last_cleanup_time = current_time

            if msg_hash in self.cache:
                last_time, count = self.cache[msg_hash]
                if current_time - last_time <= self.time_window:
                    self.cache[msg_hash] = (current_time, count + 1)
                    return False, f"重复 {count + 1} 次"
                else:
                    self.cache[msg_hash] = (current_time, 1)
                    return True, None
            else:
                self.cache[msg_hash] = (current_time, 1)

                if (
                    current_time - self._last_cleanup_time >= self.time_window
                    or len(self.cache) > self.max_cache_size
                ):
                    self._cleanup_cache(current_time)
                    self._last_cleanup_time = current_time
                return True, None

    def _cleanup_cache(self, current_time: float) -> None:
        """清理过期条目，超限时删除最旧的 25%"""
        expired_keys = [
            key
            for key, (timestamp, _) in self.cache.items()
            if current_time - timestamp > self.time_window
        ]
        for key in expired_keys:
            del self.cache[key]

        if len(self.cache) > self.max_cache_size:
            sorted_items = sorted(self.cache.items(), key=lambda x: x[1][0])
            for key, _ in sorted_items[: len(sorted_items) // 4]:
                del self.cache[key]


def _sanitize_and_escape(record: dict[str, Any]) -> None:
    """Loguru patcher: 防注入转义 + 敏感信息脱敏"""
    msg = record["message"]
    msg = msg.replace("\x00", "\\x00").replace("\n", "\\n").replace("\r", "\\r")
    msg = _global_sanitizer.sanitize(msg)
    record["message"] = msg


_loguru_logger.remove()

_stderr_stream = sys.__stderr__ if getattr(sys, "__stderr__", None) else sys.stderr

_loguru_logger = _loguru_logger.patch(_sanitize_and_escape)  # ty: ignore[invalid-argument-type]

_sink_id = _loguru_logger.add(  # ty: ignore[no-matching-overload]
    _stderr_stream,
    format="{time:YYYY-MM-DD HH:mm:ss,SSS} - {extra[logger_name]} - {level} - {message}",
    level="DEBUG",
    enqueue=False,
    colorize=False,
)


_ROOT_INTERCEPT_HANDLER_ATTR = "_aiia_root_intercept_handler"


class InterceptHandler(logging.Handler):
    """将 stdlib logging 路由到 Loguru（用于第三方库的 logging 输出）。"""

    _aiia_root_intercept_handler = True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        _loguru_logger.bind(logger_name=record.name).opt(exception=record.exc_info).log(
            level, record.getMessage()
        )


def _is_root_intercept_handler(handler: logging.Handler) -> bool:
    """Return whether *handler* is this module's root logging bridge."""
    if isinstance(handler, InterceptHandler):
        return True
    if getattr(handler, _ROOT_INTERCEPT_HANDLER_ATTR, False) is True:
        return True

    handler_type = type(handler)
    return (
        isinstance(handler, logging.Handler)
        and handler_type.__module__ == __name__
        and handler_type.__name__ == InterceptHandler.__name__
    )


def _install_root_intercept_once() -> None:
    """R72-A：在 root logger 上 idempotently 安装一份 ``InterceptHandler``。"""
    root = logging.getLogger()
    for handler in root.handlers:
        if _is_root_intercept_handler(handler):
            return
    root.addHandler(InterceptHandler())


_install_root_intercept_once()


class SingletonLogManager:
    """单例日志管理器 - 配置 stdlib logger 路由到 Loguru，线程安全。"""

    _instance: "SingletonLogManager | None" = None
    _lock = threading.Lock()
    _initialized_loggers: set[str] = set()

    def __new__(cls) -> "SingletonLogManager":
        """双重检查锁创建单例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def setup_logger(self, name: str, level: int = logging.NOTSET) -> logging.Logger:
        """返回已配置的 logger，首次调用时安装 InterceptHandler 路由到 Loguru。"""
        with self._lock:
            if name not in self._initialized_loggers:
                logger = logging.getLogger(name)
                logger.handlers.clear()
                logger.addHandler(InterceptHandler())
                logger.setLevel(level)
                logger.propagate = False
                self._initialized_loggers.add(name)

            return logging.getLogger(name)


class EnhancedLogger:
    """增强日志记录器 - 基于 Loguru 输出，集成去重和级别映射，API 与原版兼容。"""

    def __init__(self, name: str) -> None:
        """初始化 logger、去重器和级别映射"""
        self.log_manager = SingletonLogManager()
        self.logger = self.log_manager.setup_logger(name)
        self.deduplicator = LogDeduplicator(
            time_window=5.0,
            max_cache_size=1000,
        )

        self.level_mapping = {
            "收到反馈请求": logging.DEBUG,
            "Web UI 配置加载成功": logging.DEBUG,
            "启动反馈界面": logging.DEBUG,
            "Web 服务已在运行": logging.DEBUG,
            "内容已更新": logging.INFO,
            "等待用户反馈": logging.INFO,
            "收到用户反馈": logging.INFO,
            "服务启动失败": logging.ERROR,
            "配置加载失败": logging.ERROR,
        }

    def _get_effective_level(self, message: str, default_level: int) -> int:
        """根据消息关键词返回映射的日志级别"""
        for pattern, level in self.level_mapping.items():
            if pattern in message:
                return level
        return default_level

    def log(self, level: int, message: str, *args: Any, **kwargs: Any) -> None:
        """记录日志，带去重和级别映射"""
        effective_level = self._get_effective_level(message, level)
        if not self.logger.isEnabledFor(effective_level):
            return

        should_log, duplicate_info = self.deduplicator.should_log(message)

        if should_log:
            if duplicate_info:
                message += f" ({duplicate_info})"

            self.logger.log(effective_level, message, *args, **kwargs)

            _record_to_ring(effective_level, self.logger.name, message)

    def setLevel(self, level: int) -> None:
        """兼容标准 logging.Logger API：设置底层 logger 的级别。"""
        self.logger.setLevel(level)

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.ERROR, message, *args, **kwargs)

    @staticmethod
    def _format_event_value(value: Any) -> str:
        """Render a single context value for the event log line."""
        if value is None or isinstance(value, (bool, int, float)):
            return str(value)
        if isinstance(value, str):
            if value and not any(ch.isspace() or ch in "=\"'\\" for ch in value):
                return value
            return repr(value)
        return repr(value)

    def event(self, name: str, **ctx: Any) -> None:
        """Emit a single grep-friendly event log line."""
        parts = [f"event={name}"]
        for key, value in ctx.items():
            parts.append(f"{key}={self._format_event_value(value)}")
        self.info(" ".join(parts))


enhanced_logger = EnhancedLogger(__name__)


LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

VALID_LOG_LEVELS = tuple(LOG_LEVEL_MAP.keys())


_LOG_LEVEL_ENV_VAR = "AI_INTERVENTION_AGENT_LOG_LEVEL"


def get_log_level_from_config() -> int:
    """从环境变量 / 配置文件读取日志级别。"""
    raw_env = os.environ.get(_LOG_LEVEL_ENV_VAR)
    if raw_env is not None and raw_env.strip():
        env_upper = raw_env.strip().upper()
        if env_upper in LOG_LEVEL_MAP:
            return LOG_LEVEL_MAP[env_upper]

        enhanced_logger.warning(
            f"环境变量 {_LOG_LEVEL_ENV_VAR}='{raw_env}' 不是有效日志级别，"
            f"有效值: {VALID_LOG_LEVELS}；尝试退回 config / 默认值。"
        )

    try:
        from ai_intervention_agent.config_manager import config_manager

        web_ui_config = config_manager.get("web_ui")
        if not isinstance(web_ui_config, dict):
            web_ui_config = {}
        log_level_str = web_ui_config.get("log_level", "WARNING")

        log_level_upper = str(log_level_str).upper()

        if log_level_upper in LOG_LEVEL_MAP:
            return LOG_LEVEL_MAP[log_level_upper]
        else:
            enhanced_logger.warning(
                f"无效的日志级别 '{log_level_str}'，"
                f"有效值: {VALID_LOG_LEVELS}，使用默认值 WARNING"
            )
            return logging.WARNING

    except Exception as e:
        enhanced_logger.debug(f"读取日志级别配置失败: {e}，使用默认值 WARNING")
        return logging.WARNING


def configure_logging_from_config() -> None:
    """根据配置设置 root logger 和所有 handler 的级别"""
    log_level = get_log_level_from_config()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in root_logger.handlers:
        handler.setLevel(log_level)

    enhanced_logger.info(f"日志级别已设置为: {logging.getLevelName(log_level)}")


def get_current_log_level() -> dict[str, str | list[str]]:
    """返回当前运行时日志级别快照（root + ai_intervention_agent 命名空间）。"""
    root_logger = logging.getLogger()
    aiia_logger = logging.getLogger("ai_intervention_agent")
    return {
        "root_level": logging.getLevelName(root_logger.getEffectiveLevel()),
        "aiia_level": logging.getLevelName(aiia_logger.getEffectiveLevel()),
        "valid_levels": list(VALID_LOG_LEVELS),
    }


def apply_runtime_log_level(level: str) -> dict[str, str]:
    """运行时把 root logger + 所有 handler 的级别切到 ``level``。"""
    if not isinstance(level, str):
        raise ValueError(
            f"log level 必须是字符串，收到 {type(level).__name__}; "
            f"valid={VALID_LOG_LEVELS}"
        )
    level_upper = level.strip().upper()
    if level_upper not in LOG_LEVEL_MAP:
        raise ValueError(f"log level '{level}' 不是有效值; valid={VALID_LOG_LEVELS}")
    new_level_int = LOG_LEVEL_MAP[level_upper]

    root_logger = logging.getLogger()
    old_level_int = root_logger.getEffectiveLevel()
    root_logger.setLevel(new_level_int)
    for handler in root_logger.handlers:
        handler.setLevel(new_level_int)

    old_name = logging.getLevelName(old_level_int)
    enhanced_logger.info(
        f"运行时日志级别已切换: {old_name} -> {level_upper}（R188 / T3 runtime override）"
    )
    return {
        "old_level": old_name,
        "new_level": level_upper,
        "logger": "root",
    }


# 设计目标：让 ``aiia://server/info`` 资源能附带「最近 N 条 WARN/ERROR」摘要，


_LOG_RING_MAXLEN: int = 200
"""ring buffer 容量。200 条 × 平均 200 字节 ≈ 40 KB，对常驻 daemon 可忽略。
日志频率高的项目可调大；R51-C 起步先用 200，留余量。"""

_LOG_RING_MESSAGE_MAXLEN: int = 500
"""单条 ring entry 的 message 字段最大长度。超出截断为 ``message[:500] + '…'``。"""

_LOG_RING_SERVER_INFO_LIMIT: int = 20
"""Recent-log tail size used by server-info aggregation."""

_LOG_RING_ENDPOINT_DEFAULT_LIMIT: int = 50
"""Default recent-log tail size used by the HTTP endpoint."""

_log_ring: collections.deque[dict[str, Any]] = collections.deque(
    maxlen=_LOG_RING_MAXLEN
)
_log_ring_lock = threading.Lock()


def _record_to_ring(level_no: int, name: str, message: str) -> None:
    """把一条日志推入 ring buffer，自带 level 过滤 + 脱敏 + 长度截断。"""
    if level_no < logging.WARNING:
        return
    try:
        sanitized = _global_sanitizer.sanitize(str(message))
        if len(sanitized) > _LOG_RING_MESSAGE_MAXLEN:
            sanitized = sanitized[:_LOG_RING_MESSAGE_MAXLEN] + "…"
        entry: dict[str, Any] = {
            "ts_unix": int(time.time()),
            "level_no": int(level_no),
            "level_name": logging.getLevelName(level_no),
            "logger_name": name,
            "message": sanitized,
        }
        with _log_ring_lock:
            _log_ring.append(entry)
    except Exception:
        pass


def get_recent_logs(limit: int | None = None) -> list[dict[str, Any]]:
    """返回最近 N 条 WARNING/ERROR 日志，按时间正序（旧 → 新）。"""
    if limit is None or limit <= 0:
        with _log_ring_lock:
            return list(_log_ring)
    with _log_ring_lock:
        if limit in (_LOG_RING_SERVER_INFO_LIMIT, _LOG_RING_ENDPOINT_DEFAULT_LIMIT):
            ring_len = len(_log_ring)
            if limit < ring_len:
                return list(itertools.islice(_log_ring, ring_len - limit, ring_len))
        snapshot = list(_log_ring)
    if limit is not None and limit > 0:
        snapshot = snapshot[-limit:]
    return snapshot


def get_recent_error_stats(cutoff_ts_unix: float) -> tuple[int, int]:
    """Return ``(error_count, buffer_total)`` for entries newer than ``cutoff``."""
    error_count = 0
    with _log_ring_lock:
        buffer_total = len(_log_ring)
        for entry in _log_ring:
            if (
                entry.get("level_no", 0) >= logging.ERROR
                and entry.get("ts_unix", 0) >= cutoff_ts_unix
            ):
                error_count += 1
    return error_count, buffer_total


def clear_recent_logs() -> None:
    """清空 ring buffer，主要供测试 setUp 隔离用。"""
    with _log_ring_lock:
        _log_ring.clear()
