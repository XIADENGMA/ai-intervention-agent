# server

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/server.md`](../api.zh-CN/server.md)

## Functions

### `_resolve_server_version() -> str`

### `_resolve_build_info() -> dict[str, str]`

### `_build_server_icons() -> list[Icon]`

### `get_mcp_error_stats() -> dict[str, int]`

### `_fetch_sse_stats_cached(host: str, port: int) -> dict[str, object]`

### `_fetch_recent_logs_cached(host: str, port: int, limit: int = 20) -> dict[str, object]`

### `server_info_resource() -> dict[str, object]`

### `cleanup_services(shutdown_notification_manager: bool = True) -> None`

### `main() -> None`
