"""增强日志模块 - 基于 Loguru，提供脱敏、防注入、去重，全部输出到 stderr（MCP 友好）。"""

import logging
import re
import sys
import threading
import time
from typing import Any

from loguru import logger as _loguru_logger

# ========================================================================
# 日志脱敏
# ========================================================================


class LogSanitizer:
    """日志脱敏 - 检测并替换密码、API key 等敏感信息为 ***REDACTED***。"""

    def __init__(self) -> None:
        """预编译敏感信息正则模式"""
        self.sensitive_patterns = [
            re.compile(r'password["\']?\s*[:=]\s*["\']?[^\s"\']{6,}["\']?'),
            re.compile(r'passwd["\']?\s*[:=]\s*["\']?[^\s"\']{6,}["\']?'),
            re.compile(
                r'secret[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9._-]{16,}["\']?'
            ),
            re.compile(
                r'private[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9._-]{16,}["\']?'
            ),
            re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
            re.compile(r"\bxoxb-[A-Za-z0-9-]{50,}\b"),
            re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
        ]

    def sanitize(self, message: str) -> str:
        """脱敏消息中的敏感信息"""
        for pattern in self.sensitive_patterns:
            message = pattern.sub("***REDACTED***", message)
        return message


_global_sanitizer = LogSanitizer()


# ========================================================================
# 日志去重
# ========================================================================


class LogDeduplicator:
    """日志去重器 - 时间窗口内相同消息只记录一次，使用 hash() 高效判重。"""

    def __init__(self, time_window: float = 5.0, max_cache_size: int = 1000) -> None:
        """初始化时间窗口和缓存"""
        self.time_window = time_window
        self.max_cache_size = max_cache_size
        self.cache: dict[int, tuple[float, int]] = {}
        self.lock = threading.Lock()

    def should_log(self, message: str) -> tuple[bool, str | None]:
        """检查是否应记录，返回 (should_log, duplicate_info)"""
        with self.lock:
            current_time = time.time()
            msg_hash = hash(message)

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
                self._cleanup_cache(current_time)
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


# ========================================================================
# Loguru 全局配置（模块加载时执行一次）
# ========================================================================


def _sanitize_and_escape(record: dict[str, Any]) -> None:
    """Loguru patcher: 防注入转义 + 敏感信息脱敏"""
    msg = record["message"]
    msg = msg.replace("\x00", "\\x00").replace("\n", "\\n").replace("\r", "\\r")
    msg = _global_sanitizer.sanitize(msg)
    record["message"] = msg


_loguru_logger.remove()

_stderr_stream = sys.__stderr__ if getattr(sys, "__stderr__", None) else sys.stderr

_loguru_logger = _loguru_logger.patch(_sanitize_and_escape)  # type: ignore[arg-type]

_sink_id = _loguru_logger.add(  # type: ignore[call-overload]
    _stderr_stream,
    format="{time:YYYY-MM-DD HH:mm:ss,SSS} - {extra[logger_name]} - {level} - {message}",
    level="DEBUG",
    enqueue=False,
    colorize=False,
)


# ========================================================================
# stdlib logging → Loguru 桥接
# ========================================================================


class InterceptHandler(logging.Handler):
    """将 stdlib logging 路由到 Loguru（用于第三方库的 logging 输出）。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        _loguru_logger.bind(logger_name=record.name).opt(exception=record.exc_info).log(
            level, record.getMessage()
        )


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

    def setup_logger(self, name: str, level: int = logging.WARNING) -> logging.Logger:
        """返回已配置的 logger，首次调用时安装 InterceptHandler 路由到 Loguru"""
        with self._lock:
            if name not in self._initialized_loggers:
                logger = logging.getLogger(name)
                logger.handlers.clear()
                logger.addHandler(InterceptHandler())
                logger.setLevel(level)
                logger.propagate = False
                self._initialized_loggers.add(name)

            return logging.getLogger(name)


# ========================================================================
# 增强日志记录器（公开 API，保持不变）
# ========================================================================


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
        should_log, duplicate_info = self.deduplicator.should_log(message)

        if should_log:
            if duplicate_info:
                message += f" ({duplicate_info})"

            self.logger.log(effective_level, message, *args, **kwargs)

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


enhanced_logger = EnhancedLogger(__name__)


# ========================================================================
# 日志级别配置工具
# ========================================================================

LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

VALID_LOG_LEVELS = tuple(LOG_LEVEL_MAP.keys())


def get_log_level_from_config() -> int:
    """从配置文件读取 web_ui.log_level，默认 WARNING"""
    try:
        from config_manager import config_manager

        web_ui_config = config_manager.get("web_ui", {})
        log_level_str = web_ui_config.get("log_level", "WARNING")

        log_level_upper = str(log_level_str).upper()

        if log_level_upper in LOG_LEVEL_MAP:
            return LOG_LEVEL_MAP[log_level_upper]
        else:
            logging.warning(
                f"无效的日志级别 '{log_level_str}'，"
                f"有效值: {VALID_LOG_LEVELS}，使用默认值 WARNING"
            )
            return logging.WARNING

    except Exception as e:
        logging.debug(f"读取日志级别配置失败: {e}，使用默认值 WARNING")
        return logging.WARNING


def configure_logging_from_config() -> None:
    """根据配置设置 root logger 和所有 handler 的级别"""
    log_level = get_log_level_from_config()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in root_logger.handlers:
        handler.setLevel(log_level)

    logging.info(f"日志级别已设置为: {logging.getLevelName(log_level)}")
