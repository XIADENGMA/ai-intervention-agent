# enhanced_logging

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/enhanced_logging.md`](../api/enhanced_logging.md)

增强日志模块 - 基于 Loguru，提供脱敏、防注入、去重，全部输出到 stderr（MCP 友好）。

## 函数

### `_sanitize_and_escape(record: dict[str, Any]) -> None`

Loguru patcher: 防注入转义 + 敏感信息脱敏

### `get_log_level_from_config() -> int`

从配置文件读取 web_ui.log_level，默认 WARNING

### `configure_logging_from_config() -> None`

根据配置设置 root logger 和所有 handler 的级别

## 类

### `class LogSanitizer`

日志脱敏 - 检测并替换密码、API key 等敏感信息为 ***REDACTED***。

#### 方法

##### `__init__(self) -> None`

预编译敏感信息正则模式

##### `sanitize(self, message: str) -> str`

脱敏消息中的敏感信息

### `class LogDeduplicator`

日志去重器 - 时间窗口内相同消息只记录一次，使用 hash() 高效判重。

#### 方法

##### `__init__(self, time_window: float = 5.0, max_cache_size: int = 1000) -> None`

初始化时间窗口和缓存

##### `should_log(self, message: str) -> tuple[bool, str | None]`

检查是否应记录，返回 (should_log, duplicate_info)

### `class InterceptHandler`

将 stdlib logging 路由到 Loguru（用于第三方库的 logging 输出）。

#### 方法

##### `emit(self, record: logging.LogRecord) -> None`

### `class SingletonLogManager`

单例日志管理器 - 配置 stdlib logger 路由到 Loguru，线程安全。

#### 方法

##### `setup_logger(self, name: str, level: int = logging.WARNING) -> logging.Logger`

返回已配置的 logger，首次调用时安装 InterceptHandler 路由到 Loguru

### `class EnhancedLogger`

增强日志记录器 - 基于 Loguru 输出，集成去重和级别映射，API 与原版兼容。

#### 方法

##### `__init__(self, name: str) -> None`

初始化 logger、去重器和级别映射

##### `log(self, level: int, message: str) -> None`

记录日志，带去重和级别映射

##### `setLevel(self, level: int) -> None`

兼容标准 logging.Logger API：设置底层 logger 的级别。

##### `debug(self, message: str) -> None`

##### `info(self, message: str) -> None`

##### `warning(self, message: str) -> None`

##### `error(self, message: str) -> None`
