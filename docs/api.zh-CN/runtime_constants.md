# runtime_constants

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/runtime_constants.md`](../api/runtime_constants.md)

Runtime constants that must be cheap to import.

Keep these values outside ``server_config`` because ``server_config`` defines
Pydantic models and MCP response helpers. Web UI startup paths need the numeric
contracts only, and importing Pydantic for constants alone costs measurable cold
start time.
