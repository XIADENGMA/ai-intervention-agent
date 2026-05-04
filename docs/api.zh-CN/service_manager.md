# service_manager

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/service_manager.md`](../api/service_manager.md)

Web 服务编排层 - 进程生命周期管理、HTTP 客户端、Web UI 启动与健康检查。

## 函数

### `_close_async_client_best_effort(client: httpx.AsyncClient | None) -> None`

在同步上下文中尽力关闭异步 HTTP 客户端的连接池。

### `_invalidate_runtime_caches_on_config_change() -> None`

配置变更回调：清空配置缓存 + 关闭 httpx 客户端以便下次重建

### `_ensure_config_change_callbacks_registered() -> None`

确保只注册一次配置变更回调

### `get_async_client(config: WebUIConfig) -> httpx.AsyncClient`

获取（或创建）模块级异步 HTTP 客户端，支持连接池复用和自动重试。

### `get_sync_client(config: WebUIConfig) -> httpx.Client`

获取（或创建）模块级同步 HTTP 客户端。

### `create_http_session(config: WebUIConfig) -> httpx.Client`

向后兼容：返回同步 httpx.Client。

### `is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool`

TCP 端口检查，验证服务是否在监听

### `health_check_service(config: WebUIConfig) -> bool`

HTTP /api/health 检查，验证服务是否正常

### `get_web_ui_config() -> tuple[WebUIConfig, int]`

加载 Web UI 配置（带 10s TTL 缓存），返回 (WebUIConfig, auto_resubmit_timeout)

### `_get_web_ui_log_path(script_dir: Path) -> Path`

获取 Web UI 子进程日志文件路径，自动创建 logs 目录并截断过大文件。

### `start_web_service(config: WebUIConfig, script_dir: Path) -> None`

启动 Flask Web UI 子进程，含健康检查

### `update_web_content(summary: str, predefined_options: list[str] | None, task_id: str | None, auto_resubmit_timeout: int, config: WebUIConfig) -> None`

POST /api/update 更新 Web UI 内容

### `async ensure_web_ui_running(config: WebUIConfig) -> None`

检查并自动启动 Web UI 服务（异步）

### `cleanup_http_clients() -> None`

清理 HTTP 客户端（供 server.cleanup_services 调用）

## 类

### `class ServiceManager`

服务进程生命周期管理器（线程安全单例）

#### 方法

##### `__init__(self)`

##### `register_process(self, name: str, process: subprocess.Popen, config: WebUIConfig) -> None`

##### `unregister_process(self, name: str) -> None`

##### `get_process(self, name: str) -> subprocess.Popen | None`

##### `is_process_running(self, name: str) -> bool`

##### `terminate_process(self, name: str, timeout: float = 5.0) -> bool`

##### `cleanup_all(self, shutdown_notification_manager: bool = True) -> None`

##### `get_status(self) -> dict[str, dict]`
