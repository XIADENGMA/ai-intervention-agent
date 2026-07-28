# protocol

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/protocol.md`](../api/protocol.md)

协议版本 / Capabilities / ServerClock 定义。

## 函数

### `get_capabilities(server_version: str, build_id: str | None = None) -> dict[str, Any]`

返回服务器当前声明的能力集合。

### `get_server_clock() -> dict[str, int]`

返回服务器当前时间戳（毫秒）与单调时钟（毫秒）。
