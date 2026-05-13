# mcp_tool_call_metrics

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/mcp_tool_call_metrics.md`](../api.zh-CN/mcp_tool_call_metrics.md)

## Functions

### `reset_mcp_tool_call_stats() -> None`

### `get_mcp_tool_call_stats() -> dict[str, dict[str, int]]`

## Classes

### `class ToolCallCounterMiddleware`

#### Methods

##### `async on_call_tool(self, context: MiddlewareContext[mt.CallToolRequestParams], call_next: Callable[[MiddlewareContext[mt.CallToolRequestParams]], Awaitable[Any]]) -> CallToolResult`
