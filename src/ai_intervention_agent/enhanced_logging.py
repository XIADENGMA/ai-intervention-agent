"""增强日志模块 - 基于 Loguru，提供脱敏、防注入、去重，全部输出到 stderr（MCP 友好）。"""

import collections
import logging
import os
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
    """日志脱敏 - 检测并替换密码、API key 等敏感信息为 ``***REDACTED***``。

    覆盖范围（R54-B 扩展，按高频泄漏 vendor 排序，每条都加注释说明锚点）：

    1. **通用字段写法**：``password=`` / ``passwd=`` / ``secret_key=`` /
       ``private_key=``。这是最常见的 .env / config 文件 / debug 日志格式。
    2. **OpenAI 系列**：
       - 老格式：``sk-XXX``（dash 后续无 dash）；
       - 新工程级 key：``sk-proj-XXX``（dash 后含 dash，`_-` 字符集 / 40+ 字符）；
       - Anthropic：``sk-ant-XXX``（同上）；
       共用一个能把 dash 也吃进 character class 的 regex，避免老 regex 在
       ``sk-proj-...`` 处只 match 到 ``sk-proj`` 4 个字符就失配。
    3. **GitHub** 系列：``ghp_`` (PAT) / ``ghs_`` (server) / ``gho_`` (oauth) /
       ``ghu_`` (user-to-server) / ``ghr_`` (refresh)，全部 36 字符。
       **R111** 起补 fine-grained PAT (``github_pat_<11+82 chars>``)，2022 起
       GitHub 主推格式且成为新建 token 的默认形态，比经典 ``ghp_`` 更常见
       但 R54-B 当时未覆盖，导致 fine-grained PAT 黏到日志会**明文进
       stderr** —— MCP 客户端可见，高严重 PII 漏脱敏。
    4. **Slack**：``xoxb-`` (bot) / ``xoxp-`` (user)。
    5. **AWS**：``AKIA[A-Z0-9]{16}``（Access Key ID，固定 20 字符）。
    6. **Google API**：``AIza[0-9A-Za-z_-]{35}``（39 字符总长）。
    7. **HuggingFace**：``hf_[A-Za-z0-9]{34,}``。
    8. **Stripe**：``sk_live_`` / ``sk_test_`` / ``pk_live_`` / ``pk_test_``，
       通常 24+ 字符。
    9. **URL basic auth**：``http(s)://user:password@host`` 中的密码段——
       人类经常无意把整条 URL 黏到日志里。
    10. **JWT**（保守判定）：必须 ``eyJ`` 开头 + 三段 base64url——避免误伤
        普通 base64 字符串。
    """

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
            # OpenAI / Anthropic 全形态：sk-XXX、sk-proj-XXX、sk-ant-XXX 都吃。
            # 字符集允许 ``-`` 和 ``_``，长度 ≥ 24 避免误伤 ``sk-foo`` 这种短串。
            re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
            # Slack tokens (bot / user / app 各形态)
            re.compile(r"\bxox[bpasr]-[A-Za-z0-9-]{20,}\b"),
            # GitHub tokens (PAT / server / oauth / user-to-server / refresh)
            re.compile(r"\bgh[psour]_[A-Za-z0-9]{36}\b"),
            # R111：GitHub fine-grained PAT（2022 主推格式）。GitHub 官方
            # secret-scanning pattern 是 ``github_pat_[A-Z0-9_]{82}``（全大
            # 写约束），但实测真实 token 包含小写——fine-grained PAT 实际
            # 形态：``github_pat_<11 char ID>_<82 char secret>``，total ≈ 93
            # 字符。用 ``[A-Za-z0-9_]{60,}`` 覆盖所有现行形态且容忍小幅扩张。
            # 必须在 ``ghp_`` regex 之后才注册，避免 ``\bgh[psour]_`` 把
            # ``github_pat_`` 错误吃成 ``ghp_at_...``（实测不会，因为
            # ``github_pat_`` 前缀的 ``g`` 后是 ``i`` 不在 ``[psour]`` 集合
            # 内）；为 robustness 仍按"具体先于概括"原则放在通用前缀之后。
            re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
            # AWS Access Key ID (20 chars total, always AKIA + 16)
            re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
            # Google / Firebase / GCP API key (AIza + 35 chars)
            re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
            # HuggingFace tokens
            re.compile(r"\bhf_[A-Za-z0-9]{34,}\b"),
            # Stripe live/test publishable / secret keys
            re.compile(r"\b(?:sk|pk)_(?:live|test)_[0-9A-Za-z]{16,}\b"),
            # URL basic auth: capture user:password@ from http(s) URLs
            re.compile(r"(https?://)([^:/\s]+):([^@/\s]+)@"),
            # JWT (3 base64url segments, leading eyJ to anchor)
            re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        ]

    def sanitize(self, message: str) -> str:
        """脱敏消息中的敏感信息。

        URL basic auth 是唯一保留 username 的特殊形态，用反向引用把
        ``http(s)://``+username 部分留下，仅密码段替换为 ``***REDACTED***``，
        让运维仍然能从日志里看到"是哪个账号在 leak"。其它形态全部一刀切替换。
        """
        for pattern in self.sensitive_patterns:
            if pattern.pattern.startswith("(https?://)"):
                message = pattern.sub(r"\1\2:***REDACTED***@", message)
            else:
                message = pattern.sub("***REDACTED***", message)
        return message


_global_sanitizer = LogSanitizer()


# ========================================================================
# 日志去重
# ========================================================================


class LogDeduplicator:
    """日志去重器 - 时间窗口内相同消息只记录一次，使用 hash() 高效判重。

    【R13·B2】时间源刻意选 ``time.monotonic()`` 而不是 ``time.time()``：

    - ``time.time()`` 是 wall clock，会被 NTP 同步、用户手工调时、夏令时
      切换、虚拟机暂停后恢复等改动；任何这些事件都可能让
      ``current_time - last_time`` 取到负数 / 跳大 / 跳小，让"过去 5 秒"
      的窗口语义错乱：
        * 系统时间被向前调 1h → 旧条目突然变成"1 小时后"，``> 5s`` →
          被判过期 → 接下来同样的 ERROR 又会输出（无所谓，安全方向）。
        * 系统时间被向后调 1h → 新消息进来时 ``current_time - last_time``
          是负数 → 永远 ``<= 5s`` → 旧条目永远去重 → 关键 ERROR 长时
          间被静默（**这是真正危险的方向**）。
    - ``time.monotonic()`` 单调递增、不受 wall clock 影响，对"过去 X 秒"
      这种相对时间窗口是教科书级正确选择（Python 官方 ``timeit`` /
      ``asyncio`` 内部 timeout 都用它）。

    由 ``tests/test_enhanced_logging.py::TestLogDeduplicatorMonotonic`` 锁
    住此契约（reverse-lock：源码不能切回 ``time.time()`` 否则测试失败）。
    """

    # 【R16·D】懒清理触发周期（秒）。
    # 历史实现 ``_cleanup_cache`` **仅**在 cache miss 路径触发；如果某条
    # 高频 ERROR 一直 cache hit，``cache`` 里的其它 999 条 stale entry
    # 永远不会被清理（即使每条都 ``time.monotonic() - last_time > 5s``
    # 早过期了），形成软滞留——不是真泄漏（``max_cache_size = 1000``
    # 上限存在），但违反"过期即清"的语义，且让 ``should_log`` 的
    # ``in self.cache`` 哈希表常态保持在上限附近，多无用的 hash
    # collision。lazy cleanup 周期 ≥ ``time_window`` 即可保证最差情况
    # 下 stale entry 滞留不超过 2 × time_window；选 30s（= 6 ×
    # 默认 ``time_window=5s``）平衡"清理频率"与"clean-up 自身开销"。
    _LAZY_CLEANUP_INTERVAL_SECONDS: float = 30.0

    def __init__(self, time_window: float = 5.0, max_cache_size: int = 1000) -> None:
        """初始化时间窗口和缓存"""
        self.time_window = time_window
        self.max_cache_size = max_cache_size
        self.cache: dict[int, tuple[float, int]] = {}
        self.lock = threading.Lock()
        # 上一次 ``_cleanup_cache`` 触发时刻（``time.monotonic()`` 域）。
        # 初值 ``0.0`` 让首次 ``should_log`` 必然触发一次 cleanup（无影响：
        # 此时 cache 为空，cleanup 是 no-op）。
        self._last_cleanup_time: float = 0.0

    def should_log(self, message: str) -> tuple[bool, str | None]:
        """检查是否应记录，返回 (should_log, duplicate_info)"""
        with self.lock:
            # 【R13·B2】monotonic 时间源——参见 class docstring。
            current_time = time.monotonic()
            msg_hash = hash(message)

            # 【R16·D】懒清理：无论 hit/miss 都按周期检查一次过期，
            # 避免高频 cache hit 场景下 cache 里堆 stale entry。
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

_loguru_logger = _loguru_logger.patch(_sanitize_and_escape)  # ty: ignore[invalid-argument-type]

_sink_id = _loguru_logger.add(  # ty: ignore[no-matching-overload]
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


def _install_root_intercept_once() -> None:
    """R72-A：在 root logger 上 idempotently 安装一份 ``InterceptHandler``。

    目的
    ----

    项目里一部分模块（``task_queue``、``config_manager``、``file_validator``、
    ``i18n``、``config_utils``）用的是 ``logging.getLogger(__name__)`` 而不是
    走 ``EnhancedLogger`` / ``SingletonLogManager.setup_logger``。它们的
    ``logger.propagate`` 默认是 True，会冒泡到 root logger。如果 root 没装
    handler，stdlib ``logging.lastResort`` 会把这些消息原样吐到 stderr，
    **绕过 Loguru 的 ``_sanitize_and_escape`` patcher**。

    后果是 CodeQL ``py/log-injection`` 在 ``task_queue.add_task`` 等位置上
    报警是技术上正确的——一个能注入 ``\\n`` 到 ``task_id`` 的攻击者就能伪造
    log 行。

    修复方案是在 root logger 上挂一份 ``InterceptHandler``，把所有未显式
    设置 handler 的 stdlib logger 全部桥接进 Loguru，统一享受
    ``_sanitize_and_escape``（CRLF / null byte 转义）+ ``_global_sanitizer``
    （PII 脱敏）。

    幂等性
    ------

    用 ``isinstance(h, InterceptHandler)`` 检测已存在的 handler，避免重复
    安装。这对测试场景特别重要：``pytest`` 可能多次 import 模块，
    ``logging`` root 是进程级单例。

    与 ``SingletonLogManager.setup_logger`` 的关系
    -------------------------------------------------

    ``setup_logger`` 装的 handler 是在 *named* logger 上，且明确把
    ``propagate`` 设为 False；root 的 handler 不会跟 named logger 重复
    输出。两条路径独立、不串。
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, InterceptHandler):
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
        """记录日志，带去重和级别映射

        Fast path：在调用 ``deduplicator.should_log`` 之前先用底层 stdlib
        ``isEnabledFor`` 短路。``deduplicator`` 内部要 ``acquire(self.lock)``
        + ``hash(message)`` + cache 查表（可能触发懒清理），单次 ~1-3 µs；
        但如果当前 effective level 已经被过滤，所有这些工作最终都会被丢弃。
        WARNING 级别（默认）+ 高频 ``debug`` / ``info`` 调用场景下，原实现
        每次 debug 调用都付出 dedup 锁竞争代价，但所有 debug 消息最终都会
        被 stdlib 层过滤——典型的"先工作再判断"反模式。

        why effective_level（不是 raw level）作为短路判断
        ------------------------------------------------
        ``_get_effective_level`` 会把"服务启动失败"等关键词从 caller 传入的
        INFO/DEBUG 强制提升到 ERROR；反之"收到反馈请求"会从 INFO 降到 DEBUG。
        因此 effective_level 可能比 raw level **更高或更低**，不能用 raw level
        预判，必须先做 mapping 再短路。``_get_effective_level`` 自身只做字典
        9-key 遍历 + 字符串 ``in`` 检查（~0.5 µs），远便宜过 dedup 路径。

        副作用差异
        ----------
        预过滤 debug 消息现在不再进入 ``deduplicator`` cache。这与用户预期
        一致：从 WARNING 动态切到 DEBUG 后，第一条 debug 消息应当立即输出，
        而不是被原本不会输出的"幽灵 cache 命中"沉默掉。
        """
        effective_level = self._get_effective_level(message, level)
        if not self.logger.isEnabledFor(effective_level):
            return

        should_log, duplicate_info = self.deduplicator.should_log(message)

        if should_log:
            if duplicate_info:
                message += f" ({duplicate_info})"

            self.logger.log(effective_level, message, *args, **kwargs)
            # R51-C：把 WARNING+ 写进 ring buffer，让 server_info_resource 能拉
            # 最近 N 条诊断日志。``_record_to_ring`` 自带脱敏 + level 过滤 +
            # 长度截断，进 buffer 的内容是安全可外发的。
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

    # R40 P0-S3 端到端诊断日志链：grep-friendly event-style format
    # ----------------------------------------------------------------------
    # 用法：
    #     logger.event("task.created", task_id=tid, summary_len=120,
    #                  options=3)
    # 输出（INFO，进入去重/脱敏管线，落到 stderr）：
    #     2026-05-06 15:54:00,123 - ai_intervention_agent.server_feedback - INFO -
    #         event=task.created task_id=task_abcd1234 summary_len=120 options=3
    #
    # 设计取舍：
    # - 整条日志一行，便于 ``grep '^.*event=task\\.created'`` 把整个子系统时间
    #   线拉出来；
    # - 值序列化最小化：``int/float/bool/None`` bare，含空格 / 特殊符号的
    #   字符串走 ``repr()`` 自动加引号转义，避免 grep 时被空格切错列；
    # - 走 ``self.info()`` 复用现有去重 + 脱敏 + level mapping，但 event
    #   message 不会命中任何 keyword pattern，effective_level 保持 INFO；
    # - 不依赖 loguru ``bind``：保持 stdlib logging API 兼容，单测可以
    #   ``patch.object(logger, 'info')`` 直接断言（见
    #   ``tests/test_enhanced_logging_event_method.py``）。
    @staticmethod
    def _format_event_value(value: Any) -> str:
        """Render a single context value for the event log line.

        Public-static so tests can spot-check formatting rules without
        instantiating an EnhancedLogger (which spins up a SingletonLogManager).
        """
        if value is None or isinstance(value, (bool, int, float)):
            return str(value)
        if isinstance(value, str):
            if value and not any(ch.isspace() or ch in "=\"'\\" for ch in value):
                return value
            return repr(value)
        return repr(value)

    def event(self, name: str, **ctx: Any) -> None:
        """Emit a single grep-friendly event log line.

        ``name`` should be a stable dotted identifier (``task.created``,
        ``task.notified``, ``task.completed``, ``server.boot``, …). ``ctx``
        is rendered as ``key=value`` pairs after the event name.
        """
        parts = [f"event={name}"]
        for key, value in ctx.items():
            parts.append(f"{key}={self._format_event_value(value)}")
        self.info(" ".join(parts))


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


_LOG_LEVEL_ENV_VAR = "AI_INTERVENTION_AGENT_LOG_LEVEL"


def get_log_level_from_config() -> int:
    """从环境变量 / 配置文件读取日志级别。

    解析顺序（first match wins）：

    1. **环境变量** ``AI_INTERVENTION_AGENT_LOG_LEVEL``——standalone server
       场景下最常见的诊断入口。``docs/troubleshooting.md`` /
       ``.github/SUPPORT.md`` 自 v1.5 起就向用户公开承诺这个 env var
       存在，但 R92 之前实际没接入；R93 把契约真兑现到代码层。env var
       不区分大小写，无效值会回退到 config 解析路径并打 warning。
    2. **配置文件** ``[web_ui].log_level``。
    3. **默认值** ``WARNING``。
    """
    raw_env = os.environ.get(_LOG_LEVEL_ENV_VAR)
    if raw_env is not None and raw_env.strip():
        env_upper = raw_env.strip().upper()
        if env_upper in LOG_LEVEL_MAP:
            return LOG_LEVEL_MAP[env_upper]
        # env var 值无效时不直接 fallback——记 warning 提醒用户改回有效值，
        # 然后继续走 config 路径（不阻塞启动）。
        enhanced_logger.warning(
            f"环境变量 {_LOG_LEVEL_ENV_VAR}='{raw_env}' 不是有效日志级别，"
            f"有效值: {VALID_LOG_LEVELS}；尝试退回 config / 默认值。"
        )

    try:
        from ai_intervention_agent.config_manager import config_manager

        web_ui_config = config_manager.get("web_ui", {})
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


# ========================================================================
# R188 / T3: 运行时日志级别动态调整
# ========================================================================


def get_current_log_level() -> dict[str, str]:
    """返回当前运行时日志级别快照（root + ai_intervention_agent 命名空间）。

    给 ``GET /api/system/log-level`` 端点 + 测试断言用。

    返回字段：

    - ``root_level``：``logging.getLogger()`` 当前 effective level 名（如
      ``"INFO"`` / ``"WARNING"``）。
    - ``aiia_level``：``ai_intervention_agent`` 命名空间当前 effective
      level 名——子 logger 如果没显式 setLevel，会继承 root 的 effective
      level（``logging.NOTSET`` 时向上查找）。
    - ``valid_levels``：5 个允许值供 client UI 渲染下拉菜单。

    设计：返回字典字段都是字符串（不返回 int），让 JSON 序列化结果对
    人类直接可读，不需要 client 自己 reverse-lookup logging.getLevelName。
    """
    root_logger = logging.getLogger()
    aiia_logger = logging.getLogger("ai_intervention_agent")
    return {
        "root_level": logging.getLevelName(root_logger.getEffectiveLevel()),
        "aiia_level": logging.getLevelName(aiia_logger.getEffectiveLevel()),
        "valid_levels": list(VALID_LOG_LEVELS),
    }


def apply_runtime_log_level(level: str) -> dict[str, str]:
    """运行时把 root logger + 所有 handler 的级别切到 ``level``。

    用途
    ----
    R188 / T3 ``POST /api/system/log-level`` 端点的核心 helper——让运维
    在不重启 server 的情况下：

    * 调高 level → 临时调试某次反馈或某个 bug，``DEBUG`` 把 SSE / queue /
      notification 全开；
    * 调低 level → 排查完后立刻关回 ``WARNING``，避免 stderr 爆量；
    * 与 ``AI_INTERVENTION_AGENT_LOG_LEVEL`` env var 的关系：env var 控制
      **下次启动**，本 API 控制**当前进程**。两者不互相覆盖；env var 在
      下次 ``main()`` 入口生效。

    设计约束
    --------
    - **只接受 5 个 enum 值**：``DEBUG`` / ``INFO`` / ``WARNING`` /
      ``ERROR`` / ``CRITICAL``（大小写不敏感）。其他值 raise ``ValueError``，
      handler 转 400 给 client；
    - **只改 root logger + handler**：不接受任意 logger 名参数——攻击面
      最小，避免远程把 ``zeroconf`` / ``httpx`` 调成 DEBUG 让日志爆量；
    - **失败原子化**：先验证 level 合法再 setLevel，validation 失败时不
      留半改半未改的状态；
    - **不持久化**：只改运行时；下次启动仍走 env var / config 路径。这是
      故意的——运行时旋钮不应该意外覆盖 config，避免运维忘记关回去。

    参数
    ----
    ``level``：``DEBUG`` / ``INFO`` / ``WARNING`` / ``ERROR`` /
    ``CRITICAL`` 之一，大小写不敏感。

    返回
    ----
    ``{"old_level": str, "new_level": str, "logger": "root"}`` —— 三个
    字段都用 string level name（``logging.getLevelName(...)``）便于 JSON
    序列化。

    异常
    ----
    ``ValueError``：``level`` 不在 ``VALID_LOG_LEVELS`` 内。
    """
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


# ============================================================================
# R51-C：WARNING/ERROR 日志 ring buffer
# ----------------------------------------------------------------------------
# 设计目标：让 ``aiia://server/info`` 资源能附带「最近 N 条 WARN/ERROR」摘要，
# 让运维 / MCP client UI 在看到健康度有异时立即拿到上下文，无需 ssh 上去翻
# stderr / Loguru 的轮转日志文件。
#
# 关键约束：
#   1. 不破坏现有日志输出路径（loguru sink、stdlib logger 桥接、去重器）
#      —— ring buffer 仅在 ``EnhancedLogger.log`` 决定真正输出后才再插一手。
#   2. 进 buffer 的 message **必须脱敏**。``LogSanitizer`` 已经被 loguru
#      patcher 调用，但 patcher 在 sink 层；我们在更早的 ring 写入处主动
#      调一次 ``_global_sanitizer.sanitize``，确保 buffer 里也是 redacted
#      文本。
#   3. 长度截断 500 字符，避免一条超长 stack trace 把 buffer 撑爆，也防止
#      ``server_info_resource`` 一次性返回 MB 级 payload。
#   4. 线程安全 + 容量上限：``collections.deque(maxlen=...)`` 自带 O(1)
#      ring 行为，配合一把 ``threading.Lock`` 即可。
#   5. 字段可序列化：``ts_unix`` / ``level_no`` / ``level_name`` / ``logger_name``
#      / ``message`` 都是 JSON-safe，``server_info_resource`` 直接透传。
# ============================================================================

_LOG_RING_MAXLEN: int = 200
"""ring buffer 容量。200 条 × 平均 200 字节 ≈ 40 KB，对常驻 daemon 可忽略。
日志频率高的项目可调大；R51-C 起步先用 200，留余量。"""

_LOG_RING_MESSAGE_MAXLEN: int = 500
"""单条 ring entry 的 message 字段最大长度。超出截断为 ``message[:500] + '…'``。"""

_log_ring: collections.deque[dict[str, Any]] = collections.deque(
    maxlen=_LOG_RING_MAXLEN
)
_log_ring_lock = threading.Lock()


def _record_to_ring(level_no: int, name: str, message: str) -> None:
    """把一条日志推入 ring buffer，自带 level 过滤 + 脱敏 + 长度截断。

    ``level_no`` < ``logging.WARNING`` 的日志直接丢弃（hot path 上的 INFO/DEBUG
    数量级远高，进 buffer 没意义）。"""
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
        # ring buffer 失败绝不能影响真正的日志输出，吞掉异常即可
        pass


def get_recent_logs(limit: int | None = None) -> list[dict[str, Any]]:
    """返回最近 N 条 WARNING/ERROR 日志，按时间正序（旧 → 新）。

    ``limit=None`` 返回全部 buffer 内容（最多 ``_LOG_RING_MAXLEN`` 条）。
    返回的是 dict 的浅拷贝列表 —— 修改返回值不会污染 buffer。"""
    with _log_ring_lock:
        snapshot = list(_log_ring)
    if limit is not None and limit > 0:
        snapshot = snapshot[-limit:]
    return snapshot


def clear_recent_logs() -> None:
    """清空 ring buffer，主要供测试 setUp 隔离用。"""
    with _log_ring_lock:
        _log_ring.clear()
