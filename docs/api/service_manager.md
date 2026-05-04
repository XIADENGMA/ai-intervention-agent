# service_manager

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/service_manager.md`](../api.zh-CN/service_manager.md)

## Functions

### `_close_async_client_best_effort(client: httpx.AsyncClient | None) -> None`

### `_invalidate_runtime_caches_on_config_change() -> None`

### `_ensure_config_change_callbacks_registered() -> None`

### `get_async_client(config: WebUIConfig) -> httpx.AsyncClient`

### `get_sync_client(config: WebUIConfig) -> httpx.Client`

### `create_http_session(config: WebUIConfig) -> httpx.Client`

### `is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool`

### `health_check_service(config: WebUIConfig) -> bool`

### `get_web_ui_config() -> tuple[WebUIConfig, int]`

### `_get_web_ui_log_path(script_dir: Path) -> Path`

### `_is_port_available(host: str, port: int) -> bool`

### `start_web_service(config: WebUIConfig, script_dir: Path) -> None`

### `update_web_content(summary: str, predefined_options: list[str] | None, task_id: str | None, auto_resubmit_timeout: int, config: WebUIConfig) -> None`

### `async ensure_web_ui_running(config: WebUIConfig) -> None`

### `cleanup_http_clients() -> None`

## Classes

### `class ServiceManager`

#### Methods

##### `__init__(self)`

##### `register_process(self, name: str, process: subprocess.Popen, config: WebUIConfig) -> None`

##### `unregister_process(self, name: str) -> None`

##### `get_process(self, name: str) -> subprocess.Popen | None`

##### `is_process_running(self, name: str) -> bool`

##### `terminate_process(self, name: str, timeout: float = 5.0) -> bool`

##### `cleanup_all(self, shutdown_notification_manager: bool = True) -> None`

##### `get_status(self) -> dict[str, dict]`
