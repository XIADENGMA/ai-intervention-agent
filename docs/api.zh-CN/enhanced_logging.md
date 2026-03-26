# enhanced_logging

增强日志模块 - 单例管理、脱敏、防注入、去重，所有输出到 stderr（MCP 友好）。

## 函数

### `get_log_level_from_config() -> int`

从配置文件读取 web_ui.log_level，默认 WARNING

### `configure_logging_from_config() -> None`

根据配置设置 root logger 和所有 handler 的级别

## 类

### `class SingletonLogManager`

单例日志管理器 - 防止 logger 重复初始化，线程安全。

#### 方法

##### `setup_logger(self, name: str, level: int = logging.WARNING) -> logging.Logger`

返回已配置的 logger，首次调用时初始化

### `class LevelBasedStreamHandler`

按级别分流的 Handler - DEBUG/INFO 与 WARNING+ 分开处理，全部输出到 stderr。

#### 方法

##### `__init__(self)`

创建双 Handler 并配置脱敏和防注入

##### `attach_to_logger(self, logger: logging.Logger) -> None`

将双 Handler 附加到 logger

### `class LogSanitizer`

日志脱敏 - 检测并替换密码、API key 等敏感信息为 ***REDACTED***。

#### 方法

##### `__init__(self)`

预编译敏感信息正则模式

##### `sanitize(self, message: str) -> str`

脱敏消息中的敏感信息

### `class SecureLogFormatter`

安全格式化器 - 格式化后自动脱敏敏感信息。

#### 方法

##### `__init__(self)`

##### `format(self, record: logging.LogRecord) -> str`

格式化后脱敏

### `class AntiInjectionFilter`

防注入过滤器 - 转义换行符/回车符/空字节防止日志伪造。

#### 方法

##### `filter(self, record: logging.LogRecord) -> bool`

转义 msg 和 args 中的危险字符，始终返回 True

### `class LogDeduplicator`

日志去重器 - 时间窗口内相同消息只记录一次，使用 hash() 高效判重。

#### 方法

##### `__init__(self, time_window = 5.0, max_cache_size = 1000)`

初始化时间窗口和缓存

##### `should_log(self, message: str) -> Tuple[bool, Optional[str]]`

检查是否应记录，返回 (should_log, duplicate_info)

### `class EnhancedLogger`

增强日志记录器 - 集成单例管理、去重、脱敏、防注入、级别映射。

#### 方法

##### `__init__(self, name: str)`

初始化 logger、去重器和级别映射

##### `log(self, level: int, message: str) -> None`

记录日志，带去重和级别映射

##### `setLevel(self, level: int) -> None`

兼容标准 logging.Logger API：设置底层 logger 的级别。

##### `debug(self, message: str) -> None`

##### `info(self, message: str) -> None`

##### `warning(self, message: str) -> None`

##### `error(self, message: str) -> None`
