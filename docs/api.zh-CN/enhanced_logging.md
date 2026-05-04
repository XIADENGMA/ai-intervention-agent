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
