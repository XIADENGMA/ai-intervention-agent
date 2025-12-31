# config_manager

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/config_manager.md`](../api.zh-CN/config_manager.md)

## Functions

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

##### `read_lock(self)`

##### `write_lock(self)`

### `class ConfigManager`

#### Methods

##### `__init__(self, config_file: str = 'config.jsonc')`

##### `get(self, key: str, default: Any = None) -> Any`

##### `set(self, key: str, value: Any, save: bool = True)`

##### `update(self, updates: Dict[str, Any], save: bool = True)`

##### `force_save(self)`

##### `get_section(self, section: str, use_cache: bool = True) -> Dict[str, Any]`

##### `update_section(self, section: str, updates: Dict[str, Any], save: bool = True)`

##### `reload(self)`

##### `invalidate_section_cache(self, section: str)`

##### `invalidate_all_caches(self)`

##### `get_cache_stats(self) -> Dict[str, Any]`

##### `reset_cache_stats(self)`

##### `set_cache_ttl(self, section_ttl: float | None = None, network_security_ttl: float | None = None)`

##### `get_all(self) -> Dict[str, Any]`

##### `get_network_security_config(self) -> Dict[str, Any]`

##### `get_typed(self, key: str, default: Any, value_type: type, min_val: Optional[Any] = None, max_val: Optional[Any] = None) -> Any`

##### `get_int(self, key: str, default: int = 0, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int`

##### `get_float(self, key: str, default: float = 0.0, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float`

##### `get_bool(self, key: str, default: bool = False) -> bool`

##### `get_str(self, key: str, default: str = '', max_length: Optional[int] = None) -> str`

##### `start_file_watcher(self, interval: float = 2.0)`

##### `stop_file_watcher(self)`

##### `shutdown(self)`

##### `register_config_change_callback(self, callback: Callable[[], None])`

##### `unregister_config_change_callback(self, callback: Callable[[], None])`

##### `is_file_watcher_running(self) -> bool`

##### `export_config(self, include_network_security: bool = False) -> Dict[str, Any]`

##### `import_config(self, config_data: Dict[str, Any], merge: bool = True, save: bool = True) -> bool`

##### `backup_config(self, backup_path: Optional[str] = None) -> str`

##### `restore_config(self, backup_path: str) -> bool`
