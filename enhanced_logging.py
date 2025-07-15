"""
增强的日志系统 - 解决MCP日志重复和级别错误问题
"""

import hashlib
import json  # noqa: F401
import logging
import os  # noqa: F401
import re
import sys
import threading
import time
from typing import Any, Dict, Optional, Set, Tuple  # noqa: F401


class SingletonLogManager:
    """单例日志管理器，防止重复初始化"""

    _instance = None
    _lock = threading.Lock()
    _initialized_loggers: Set[str] = set()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def setup_logger(self, name: str, level=logging.INFO):
        """确保每个logger只被设置一次"""
        if name in self._initialized_loggers:
            return logging.getLogger(name)

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
    """基于级别的多流输出处理器 - 解决IDE级别错误问题"""

    def __init__(self):
        # INFO和DEBUG使用stdout
        self.stdout_handler = logging.StreamHandler(sys.stdout)
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
        """只允许INFO和DEBUG级别通过stdout"""
        return record.levelno <= logging.INFO

    def attach_to_logger(self, logger):
        """将处理器附加到指定logger"""
        logger.addHandler(self.stdout_handler)
        logger.addHandler(self.stderr_handler)


class LogSanitizer:
    """日志脱敏处理器 - 只脱敏真正敏感的密钥信息"""

    def __init__(self):
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
        """脱敏处理日志消息 - 只处理真正的密码和密钥"""
        # 只脱敏明确的密码和密钥字段
        for pattern in self.sensitive_patterns:
            message = pattern.sub("***REDACTED***", message)

        return message


class SecureLogFormatter(logging.Formatter):
    """安全的日志格式化器 - 包含脱敏功能"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sanitizer = LogSanitizer()

    def format(self, record):
        # 先进行标准格式化
        formatted = super().format(record)
        # 然后进行脱敏处理
        return self.sanitizer.sanitize(formatted)


class AntiInjectionFilter(logging.Filter):
    """防止日志注入攻击的过滤器"""

    def filter(self, record):
        # 只转义真正危险的字符，避免过度转义影响可读性
        if hasattr(record, "msg") and isinstance(record.msg, str):
            # 只转义可能导致日志注入的危险字符，不转义HTML字符
            record.msg = record.msg.replace("\x00", "\\x00")  # 空字节

        # 转义换行符，防止日志分割攻击
        if hasattr(record, "args"):
            escaped_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    # 只转义换行符和回车符，保持可读性
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
    """日志去重器 - 解决重复日志问题"""

    def __init__(self, time_window=5.0, max_cache_size=1000):
        self.time_window = time_window  # 时间窗口（秒）
        self.max_cache_size = max_cache_size
        self.cache: Dict[str, Tuple[float, int]] = {}  # {log_hash: (timestamp, count)}
        self.lock = threading.Lock()

    def should_log(self, message: str) -> Tuple[bool, Optional[str]]:
        """检查是否应该记录日志，返回(是否记录, 重复信息)"""
        with self.lock:
            current_time = time.time()

            # 生成消息哈希
            msg_hash = hashlib.md5(message.encode()).hexdigest()

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
        """清理过期缓存"""
        # 清理过期条目
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
    """增强的日志记录器 - 集成所有优化功能"""

    def __init__(self, name: str):
        self.log_manager = SingletonLogManager()
        self.logger = self.log_manager.setup_logger(name)
        self.deduplicator = LogDeduplicator(
            time_window=5.0,  # 5秒去重窗口
            max_cache_size=1000,  # 最大缓存1000条
        )

        # 日志级别映射 - 降低冗余信息的级别
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
        """根据消息内容获取有效的日志级别"""
        for pattern, level in self.level_mapping.items():
            if pattern in message:
                return level
        return default_level

    def log(self, level: int, message: str, *args, **kwargs):
        """带去重和级别优化的日志记录"""
        # 获取有效级别
        effective_level = self._get_effective_level(message, level)

        # 检查是否应该记录（去重）
        should_log, duplicate_info = self.deduplicator.should_log(message)

        if should_log:
            if duplicate_info:
                message += f" ({duplicate_info})"

            # 使用有效级别记录日志
            self.logger.log(effective_level, message, *args, **kwargs)

    def debug(self, message: str, *args, **kwargs):
        self.log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        self.log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        self.log(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        self.log(logging.ERROR, message, *args, **kwargs)


# 全局增强日志实例
enhanced_logger = EnhancedLogger(__name__)
