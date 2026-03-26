# enhanced_logging

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/enhanced_logging.md`](../api.zh-CN/enhanced_logging.md)

## Functions

### `get_log_level_from_config() -> int`

### `configure_logging_from_config() -> None`

## Classes

### `class SingletonLogManager`

#### Methods

##### `setup_logger(self, name: str, level: int = logging.WARNING) -> logging.Logger`

### `class LevelBasedStreamHandler`

#### Methods

##### `__init__(self)`

##### `attach_to_logger(self, logger: logging.Logger) -> None`

### `class LogSanitizer`

#### Methods

##### `__init__(self)`

##### `sanitize(self, message: str) -> str`

### `class SecureLogFormatter`

#### Methods

##### `__init__(self)`

##### `format(self, record: logging.LogRecord) -> str`

### `class AntiInjectionFilter`

#### Methods

##### `filter(self, record: logging.LogRecord) -> bool`

### `class LogDeduplicator`

#### Methods

##### `__init__(self, time_window = 5.0, max_cache_size = 1000)`

##### `should_log(self, message: str) -> Tuple[bool, Optional[str]]`

### `class EnhancedLogger`

#### Methods

##### `__init__(self, name: str)`

##### `log(self, level: int, message: str) -> None`

##### `setLevel(self, level: int) -> None`

##### `debug(self, message: str) -> None`

##### `info(self, message: str) -> None`

##### `warning(self, message: str) -> None`

##### `error(self, message: str) -> None`
