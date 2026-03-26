# config_manager

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/config_manager.md`](../api.zh-CN/config_manager.md)

## Functions

### `_is_sensitive_config_key(key: str) -> bool`

### `_sanitize_config_value_for_log(key: str, value: Any) -> str`

### `parse_jsonc(content: str) -> Dict[str, Any]`

### `_is_uvx_mode() -> bool`

### `find_config_file(config_filename: str = 'config.jsonc') -> Path`

### `_get_user_config_dir_fallback() -> Path`

### `_shutdown_global_config_manager()`

### `get_config() -> ConfigManager`

## Classes

### `class ReadWriteLock`

#### Methods

##### `__init__(self)`

##### `read_lock(self) -> Generator[None, None, None]`

##### `write_lock(self) -> Generator[None, None, None]`

### `class ConfigManager`

#### Methods

##### `__init__(self, config_file: str = 'config.jsonc')`

##### `get(self, key: str, default: Any = None) -> Any`

##### `set(self, key: str, value: Any, save: bool = True) -> None`

##### `update(self, updates: Dict[str, Any], save: bool = True) -> None`

##### `force_save(self) -> None`

##### `get_section(self, section: Literal['notification'], use_cache: bool = ...) -> 'NotificationConfig'`

##### `get_section(self, section: Literal['web_ui'], use_cache: bool = ...) -> 'WebUISectionConfig'`

##### `get_section(self, section: Literal['mdns'], use_cache: bool = ...) -> 'MdnsConfig'`

##### `get_section(self, section: Literal['network_security'], use_cache: bool = ...) -> 'NetworkSecurityConfig'`

##### `get_section(self, section: Literal['feedback'], use_cache: bool = ...) -> 'FeedbackConfig'`

##### `get_section(self, section: str, use_cache: bool = ...) -> Dict[str, Any]`

##### `get_section(self, section: str, use_cache: bool = True) -> Dict[str, Any]`

##### `update_section(self, section: str, updates: Dict[str, Any], save: bool = True) -> None`

##### `reload(self) -> None`

##### `invalidate_section_cache(self, section: str) -> None`

##### `invalidate_all_caches(self) -> None`

##### `get_cache_stats(self) -> Dict[str, Any]`

##### `reset_cache_stats(self) -> None`

##### `set_cache_ttl(self, section_ttl: float | None = None, network_security_ttl: float | None = None) -> None`

##### `get_all(self) -> Dict[str, Any]`

##### `get_typed(self, key: str, default: Any, value_type: type, min_val: Optional[Any] = None, max_val: Optional[Any] = None) -> Any`

##### `get_int(self, key: str, default: int = 0, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int`

##### `get_float(self, key: str, default: float = 0.0, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float`

##### `get_bool(self, key: str, default: bool = False) -> bool`

##### `get_str(self, key: str, default: str = '', max_length: Optional[int] = None) -> str`
