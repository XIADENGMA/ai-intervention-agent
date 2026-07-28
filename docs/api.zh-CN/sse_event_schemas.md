# sse_event_schemas

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/sse_event_schemas.md`](../api/sse_event_schemas.md)

R198 / Cycle 7 · SSE event schema registry。

## 函数

### `get_known_event_types() -> tuple[str, ...]`

返回已注册的 event type 名集合 (tuple, 顺序按字母排序)。

### `get_schema(event_type: str) -> EventSchema | None`

按 event_type 查 schema。未注册 → ``None``。

### `validate_payload(event_type: str, payload: dict[str, Any] | None) -> list[str]`

验证 payload 是否符合 event_type 的 schema。

## 类

### `class EventSchema`

单一 SSE event type 的 payload schema 定义。
