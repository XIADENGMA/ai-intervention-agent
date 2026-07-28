"""R198 / Cycle 7 · SSE event schema registry。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventSchema:
    """单一 SSE event type 的 payload schema 定义。"""

    name: str
    required_fields: frozenset[str]
    optional_fields: frozenset[str] = field(default_factory=frozenset)
    description: str = ""
    emitted_by: tuple[str, ...] = ()


EVENT_SCHEMAS: dict[str, EventSchema] = {
    "task_changed": EventSchema(
        name="task_changed",
        required_fields=frozenset({"task_id", "old_status", "new_status"}),
        optional_fields=frozenset({"stats"}),
        description=(
            "A feedback task transitioned between states (pending → "
            "active → completed / failed / cancelled). Subscribers update "
            "the activity dashboard and PWA status bar in response. "
            "``stats`` field (optional) carries the current per-status "
            "task counts so subscribers can refresh totals without an "
            "extra API call."
        ),
        emitted_by=("src/ai_intervention_agent/web_ui_routes/task.py",),
    ),
    "config_changed": EventSchema(
        name="config_changed",
        required_fields=frozenset({"reason", "hint"}),
        optional_fields=frozenset(),
        description=(
            "The ``config.toml`` file's mtime changed (file-watcher loop "
            "detected). Subscribers should prompt the user / reload "
            "client-side config. ``reason`` is currently always "
            "``config_file_modified`` but reserved for future expansion "
            "(e.g. ``config_api_modified`` if an admin endpoint ever "
            "edits config without touching disk)."
        ),
        emitted_by=("src/ai_intervention_agent/web_ui_config_sync.py",),
    ),
    "log_level_changed": EventSchema(
        name="log_level_changed",
        required_fields=frozenset({"old_level", "new_level", "logger", "changed_by"}),
        optional_fields=frozenset(),
        description=(
            "An admin successfully invoked ``POST /api/system/log-level`` "
            "(R188 endpoint). Subscribers render a top-of-dashboard banner "
            "so other operators see the runtime log-level dial moved. "
            "``changed_by`` is the client IP (or ``unknown`` if not "
            "determinable). R192 introduced this event."
        ),
        emitted_by=("src/ai_intervention_agent/web_ui_routes/system.py",),
    ),
    "oversize_drop": EventSchema(
        name="oversize_drop",
        required_fields=frozenset({"original_event_type", "size_bytes", "limit_bytes"}),
        optional_fields=frozenset(),
        description=(
            "The SSE bus itself replaced a fan-out attempt when the "
            "serialized payload exceeded ``_OVERSIZE_LIMIT_BYTES`` (R58 "
            "guard). Subscribers can render a warning toast or surface "
            "the count in observability metrics. Not emitted by feature "
            "code directly — this is the bus's self-protective "
            "replacement path."
        ),
        emitted_by=("src/ai_intervention_agent/web_ui_routes/task.py",),
    ),
}


_KNOWN_EVENT_TYPES: tuple[str, ...] = tuple(sorted(EVENT_SCHEMAS))


def get_known_event_types() -> tuple[str, ...]:
    """返回已注册的 event type 名集合 (tuple, 顺序按字母排序)。"""
    return _KNOWN_EVENT_TYPES


def get_schema(event_type: str) -> EventSchema | None:
    """按 event_type 查 schema。未注册 → ``None``。"""
    return EVENT_SCHEMAS.get(event_type)


def validate_payload(event_type: str, payload: dict[str, Any] | None) -> list[str]:
    """验证 payload 是否符合 event_type 的 schema。"""
    schema = EVENT_SCHEMAS.get(event_type)
    if schema is None:
        return [f"unknown event_type: {event_type!r}"]
    if payload is None:
        return [f"event_type {event_type!r} requires payload dict, got None"]
    if not isinstance(payload, dict):
        return [
            f"event_type {event_type!r} requires payload dict, "
            f"got {type(payload).__name__}"
        ]
    violations: list[str] = []
    for required in schema.required_fields:
        if required not in payload:
            violations.append(
                f"event_type {event_type!r}: missing required field {required!r}"
            )
    allowed = schema.required_fields | schema.optional_fields
    for key in payload:
        if key not in allowed:
            violations.append(
                f"event_type {event_type!r}: unexpected field {key!r} "
                f"(not in required or optional)"
            )
    return violations
