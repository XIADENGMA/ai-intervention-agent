# sse_event_schemas

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/sse_event_schemas.md`](../api.zh-CN/sse_event_schemas.md)

## Functions

### `get_known_event_types() -> tuple[str, ...]`

### `get_schema(event_type: str) -> EventSchema | None`

### `validate_payload(event_type: str, payload: dict[str, Any] | None) -> list[str]`

## Classes

### `class EventSchema`
