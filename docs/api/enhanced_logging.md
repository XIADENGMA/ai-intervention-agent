# enhanced_logging

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/enhanced_logging.md`](../api.zh-CN/enhanced_logging.md)

## Functions

### `_sanitize_and_escape(record: dict[str, Any]) -> None`

### `get_log_level_from_config() -> int`

### `configure_logging_from_config() -> None`

## Classes

### `class LogSanitizer`

#### Methods

##### `__init__(self) -> None`

##### `sanitize(self, message: str) -> str`

### `class LogDeduplicator`

#### Methods

##### `__init__(self, time_window: float = 5.0, max_cache_size: int = 1000) -> None`

##### `should_log(self, message: str) -> tuple[bool, str | None]`

### `class InterceptHandler`

#### Methods

##### `emit(self, record: logging.LogRecord) -> None`

### `class SingletonLogManager`

#### Methods

##### `setup_logger(self, name: str, level: int = logging.WARNING) -> logging.Logger`

### `class EnhancedLogger`

#### Methods

##### `__init__(self, name: str) -> None`

##### `log(self, level: int, message: str) -> None`

##### `setLevel(self, level: int) -> None`

##### `debug(self, message: str) -> None`

##### `info(self, message: str) -> None`

##### `warning(self, message: str) -> None`

##### `error(self, message: str) -> None`
