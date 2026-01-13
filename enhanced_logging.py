"""增强日志模块 - 单例管理、脱敏、防注入、去重，所有输出到 stderr（MCP 友好）。"""

import json  # noqa: F401
import logging
import os  # noqa: F401
import re
import sys
import threading
import time
from typing import Any, Dict, Optional, Set, Tuple  # noqa: F401


class SingletonLogManager:
    """单例日志管理器 - 防止 logger 重复初始化，线程安全。"""

    _instance = None
    _lock = threading.Lock()
    _initialized_loggers: Set[str] = set()

    def __new__(cls):
        """双重检查锁创建单例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def setup_logger(self, name: str, level=logging.WARNING):
        """返回已配置的 logger，首次调用时初始化"""
        # 始终加锁检查，避免快速路径的竞态条件
        # 原逻辑的快速路径可能导致返回未完全初始化的 logger
        with self._lock:
            if name not in self._initialized_loggers:
                logger = logging.getLogger(name)
                # 清除现有处理器
                logger.handlers.clear()

                # 使用多流输出策略
                stream_handler = LevelBasedStreamHandler()
                stream_handler.attach_to_logger(logger)

                logger.setLevel(level)
                logger.propagate = False  # 防止向父logger传播

                self._initialized_loggers.add(name)

            return logging.getLogger(name)


class LevelBasedStreamHandler:
    """按级别分流的 Handler - DEBUG/INFO 与 WARNING+ 分开处理，全部输出到 stderr。"""

    def __init__(self):
        """创建双 Handler 并配置脱敏和防注入"""
        self.stdout_handler = logging.StreamHandler(sys.stderr)
        self.stdout_handler.setLevel(logging.DEBUG)
        self.stdout_handler.addFilter(self._stdout_filter)

        # WARNING和ERROR使用stderr
        self.stderr_handler = logging.StreamHandler(sys.stderr)
        self.stderr_handler.setLevel(logging.WARNING)

        # 设置安全格式化器
        formatter = SecureLogFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.stdout_handler.setFormatter(formatter)
        self.stderr_handler.setFormatter(formatter)

        # 添加注入防护过滤器
        anti_injection_filter = AntiInjectionFilter()
        self.stdout_handler.addFilter(anti_injection_filter)
        self.stderr_handler.addFilter(anti_injection_filter)

    def _stdout_filter(self, record):
        """只允许 DEBUG/INFO 通过"""
        return record.levelno <= logging.INFO

    def attach_to_logger(self, logger):
        """将双 Handler 附加到 logger"""
        logger.addHandler(self.stdout_handler)
        logger.addHandler(self.stderr_handler)


class LogSanitizer:
    """日志脱敏 - 检测并替换密码、API key 等敏感信息为 ***REDACTED***。"""

    def __init__(self):
        """预编译敏感信息正则模式"""
        # 只保护真正的密码和密钥，避免过度脱敏
        self.sensitive_patterns = [
            # 明确的密码字段
            re.compile(r'password["\']?\s*[:=]\s*["\']?[^\s"\']{6,}["\']?'),
            re.compile(r'passwd["\']?\s*[:=]\s*["\']?[^\s"\']{6,}["\']?'),
            # 明确的密钥字段
            re.compile(
                r'secret[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9._-]{16,}["\']?'
            ),
            re.compile(
                r'private[_-]?key["\']?\s*[:=]\s*["\']?[A-Za-z0-9._-]{16,}["\']?'
            ),
            # 知名API密钥格式（精确匹配）
            re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),  # OpenAI API key
            re.compile(r"\bxoxb-[A-Za-z0-9-]{50,}\b"),  # Slack Bot Token
            re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),  # GitHub Personal Access Token
        ]

    def sanitize(self, message: str) -> str:
        """脱敏消息中的敏感信息"""
        for pattern in self.sensitive_patterns:
            message = pattern.sub("***REDACTED***", message)

        return message


class SecureLogFormatter(logging.Formatter):
    """安全格式化器 - 格式化后自动脱敏敏感信息。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sanitizer = LogSanitizer()

    def format(self, record):
        """格式化后脱敏"""
        # 先进行标准格式化
        formatted = super().format(record)
        # 然后进行脱敏处理
        return self.sanitizer.sanitize(formatted)


class AntiInjectionFilter(logging.Filter):
    """防注入过滤器 - 转义换行符/回车符/空字节防止日志伪造。"""

    def filter(self, record):
        """转义 msg 和 args 中的危险字符，始终返回 True"""
        # 转义record.msg中的危险字符（换行符、回车符、空字节）
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = (
                record.msg.replace("\x00", "\\x00")  # 空字节
                .replace("\n", "\\n")  # 换行符
                .replace("\r", "\\r")  # 回车符
            )

        # 转义 record.args 中的危险字符
        if hasattr(record, "args"):
            escaped_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    # 转义换行符、回车符和空字节，保持可读性
                    escaped_arg = (
                        arg.replace("\n", "\\n")
                        .replace("\r", "\\r")
                        .replace("\x00", "\\x00")
                    )
                    escaped_args.append(escaped_arg)
                else:
                    escaped_args.append(arg)
            record.args = tuple(escaped_args)

        return True


class LogDeduplicator:
    """日志去重器 - 时间窗口内相同消息只记录一次，使用 hash() 高效判重。"""

    def __init__(self, time_window=5.0, max_cache_size=1000):
        """初始化时间窗口和缓存"""
        self.time_window = time_window  # 时间窗口（秒）
        self.max_cache_size = max_cache_size
        # 使用内置 hash(message)（int）作为 key
        self.cache: Dict[int, Tuple[float, int]] = {}  # {msg_hash: (timestamp, count)}
        self.lock = threading.Lock()

    def should_log(self, message: str) -> Tuple[bool, Optional[str]]:
        """检查是否应记录，返回 (should_log, duplicate_info)"""
        with self.lock:
            current_time = time.time()

            # 【性能优化】使用 Python 内置 hash()，比 MD5 快 5-10 倍
            # 对于日志去重场景，不需要加密安全性，只需要高效的哈希区分
            msg_hash = hash(message)

            if msg_hash in self.cache:
                last_time, count = self.cache[msg_hash]
                if current_time - last_time <= self.time_window:
                    # 在时间窗口内，增加计数但不记录
                    self.cache[msg_hash] = (current_time, count + 1)
                    return False, f"重复 {count + 1} 次"
                else:
                    # 超出时间窗口，重新记录
                    self.cache[msg_hash] = (current_time, 1)
                    return True, None
            else:
                # 新消息，记录
                self.cache[msg_hash] = (current_time, 1)
                self._cleanup_cache(current_time)
                return True, None

    def _cleanup_cache(self, current_time: float):
        """清理过期条目，超限时删除最旧的 25%"""
        expired_keys = [
            key
            for key, (timestamp, _) in self.cache.items()
            if current_time - timestamp > self.time_window
        ]
        for key in expired_keys:
            del self.cache[key]

        # 限制缓存大小
        if len(self.cache) > self.max_cache_size:
            # 删除最旧的条目
            sorted_items = sorted(self.cache.items(), key=lambda x: x[1][0])
            for key, _ in sorted_items[: len(sorted_items) // 4]:
                del self.cache[key]


class EnhancedLogger:
    """增强日志记录器 - 集成单例管理、去重、脱敏、防注入、级别映射。"""

    def __init__(self, name: str):
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

    def log(self, level: int, message: str, *args, **kwargs):
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

    def debug(self, message: str, *args, **kwargs):
        self.log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        self.log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        self.log(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        self.log(logging.ERROR, message, *args, **kwargs)


enhanced_logger = EnhancedLogger(__name__)


# ========================================================================
# 日志级别配置工具
# ========================================================================

# 日志级别映射
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# 有效的日志级别名称
VALID_LOG_LEVELS = tuple(LOG_LEVEL_MAP.keys())


def get_log_level_from_config() -> int:
    """从配置文件读取 web_ui.log_level，默认 WARNING"""
    try:
        from config_manager import config_manager

        web_ui_config = config_manager.get("web_ui", {})
        log_level_str = web_ui_config.get("log_level", "WARNING")

        # 标准化为大写
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
        # 配置读取失败时使用默认级别
        logging.debug(f"读取日志级别配置失败: {e}，使用默认值 WARNING")
        return logging.WARNING


def configure_logging_from_config() -> None:
    """根据配置设置 root logger 和所有 handler 的级别"""
    log_level = get_log_level_from_config()

    # 设置 root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 更新所有 handler
    for handler in root_logger.handlers:
        handler.setLevel(log_level)

    logging.info(f"日志级别已设置为: {logging.getLevelName(log_level)}")
