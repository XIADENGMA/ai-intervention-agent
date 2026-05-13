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

### `_build_arg_parser() -> argparse.ArgumentParser`

### `_is_sensitive_key(key: str) -> bool`

### `_redact_sensitive(value: object) -> object`

### `_is_using_default_config(config_file_path: object) -> bool`

### `_print_effective_config() -> int`

### `main(argv: list[str] | None = None) -> None`

### `_cli_main() -> None`
