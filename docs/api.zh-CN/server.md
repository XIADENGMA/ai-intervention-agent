# server

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/server.md`](../api/server.md)

MCP 服务器核心 - interactive_feedback 工具、多任务队列、通知集成。

## 函数

### `_resolve_server_version() -> str`

读取已安装包版本号，失败时返回开发占位符。

### `reset_sse_stats_cache_for_testing() -> None`

R352 (cycle-39 #C2) · **Test-only**: 清空 ``_sse_stats_cache`` +
重置 timestamp, 让下次 ``_fetch_sse_stats_cached`` 重新拉取。

### `reset_recent_logs_cache_for_testing() -> None`

R352 (cycle-39 #C2) · **Test-only**: 清空 ``_recent_logs_cache`` +
重置 timestamp, 让下次 ``_fetch_recent_logs_cached`` 重新拉取。

### `_build_server_icons() -> list[Icon]`

启动时一次性把本地 icons 转成 data URI，让 server icons 完全 self-contained。

### `get_mcp_error_stats() -> dict[str, int]`

返回 MCP 中间件累计的异常计数（``{error_type}:{method}`` → 次数）。

### `_fetch_sse_stats_cached(host: str, port: int) -> dict[str, object]`

1.0s TTL 包装 GET /api/system/sse-stats（R54-A）。

### `_fetch_recent_logs_cached(host: str, port: int, limit: int = 20) -> dict[str, object]`

1.0s TTL 包装 GET /api/system/recent-logs（R55）。

### `server_info_resource() -> dict[str, object]`

Return diagnostic self-information for this MCP server.

### `cleanup_services(shutdown_notification_manager: bool = True) -> None`

清理所有启动的服务进程

### `_build_arg_parser() -> argparse.ArgumentParser`

构造 ``ai-intervention-agent`` 的 CLI 解析器。

### `_is_sensitive_key(key: str) -> bool`

匹配规则：key 名 normalized 后包含任意 ``_SENSITIVE_KEY_SUBSTRINGS`` 子串。

### `_redact_sensitive(value: object) -> object`

递归扫一棵 config 子树，把敏感字段的值替换成 ``***REDACTED***``。

### `_is_using_default_config(config_file_path: object) -> bool`

CR#16 F-3：判断 ``config_file_path`` 是否指向项目 bundled 默认配置。

### `_json_for_stdout(payload: object) -> str`

把 ``payload`` 序列化成 JSON 文本，保证 ``print`` 写得进当前的 stdout（R786）。

默认保持中文原样（UTF-8 终端里可读）。stdout 的编码写不下时——Windows 上管道 / 重定向后
是 ANSI 代码页（cp1252 ……），``LANG=C`` 的环境是 ASCII——改用 ``\uXXXX`` 转义：转义后仍是
合法 JSON，``--print-config | jq`` 照样能读，而不是 ``UnicodeEncodeError`` 加零字节输出。

### `_print_effective_config() -> int`

实现 ``--print-config``：dump merged config 到 stdout 后退出。

### `main(argv: list[str] | None = None) -> None`

MCP 服务器主入口函数

### `_cli_main() -> None`

PyPA console_script 入口（``[project.scripts]`` 注册到此函数）。
