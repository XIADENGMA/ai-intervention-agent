# mcp_tool_call_metrics

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/mcp_tool_call_metrics.md`](../api/mcp_tool_call_metrics.md)

R187 / T2 · MCP tool call counter middleware。

## 函数

### `reset_mcp_tool_call_stats() -> None`

清零所有累计计数 **和** latency histogram（仅供测试 / 运维 reset 使用）。

### `get_mcp_tool_call_stats() -> dict[str, dict[str, int]]`

返回 ``{tool_name: {"success": int, "failure": int, "total": int}}``
形式的累计计数快照。

### `_record_latency(tool_name: str, status: str, duration_seconds: float) -> None`

内部 helper：把一次工具调用的耗时写入 histogram。

### `get_mcp_tool_call_latency_snapshot() -> dict[tuple[str, str], dict[str, Any]]`

返回 latency histogram 状态深 copy。

## 类

### `class ToolCallCounterMiddleware`

累计 MCP tool 调用次数（success / failure 两档）。

#### 方法

##### `async on_call_tool(self, context: MiddlewareContext[mt.CallToolRequestParams], call_next: Callable[[MiddlewareContext[mt.CallToolRequestParams]], Awaitable[Any]]) -> CallToolResult`
