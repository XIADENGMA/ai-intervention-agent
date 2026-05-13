"""R198 / Cycle 7 · SSE event schema registry。

背景
====

Project 的 SSE bus（``web_ui_routes/task.py::_SSEBus``）接受 free-form
``(event_type: str, data: dict | None)``——任何模块都能 ``_sse_bus.emit(
"random_string", whatever_payload)``，bus 不验证 event_type 是否「合法」、
也不验证 payload 形态。这种宽松设计让 emit-side 写起来轻便，但前端
（Activity dashboard JS / VSCode webview）订阅时**没有 source-of-truth**
可参考——只能靠注释 + 历史 commit 试错。

R198 把所有已知 event type + 它们的 payload schema 集中在本模块定义,
不引入运行时验证 (避免给 emit 热路径添加开销), 而是:

1. **设计期文档**: emit-site 作者可以 ``from ai_intervention_agent.
   sse_event_schemas import EVENT_SCHEMAS`` 查询 schema, 写 payload 时
   有 reference;
2. **前端协约**: 前端 JS / VSCode extension 可以读 schema 做
   TypeScript-style discriminated union, 知道每种 event_type 该如何
   解析 payload;
3. **测试期 source-coverage**: ``tests/test_sse_event_schemas_r198.py``
   扫描整个 source tree 里所有 ``_sse_bus.emit(...)`` call site,
   断言 event_type literal 必须 in ``EVENT_SCHEMAS``——任何添加新
   event type 而忘了同步本模块的 commit 会被这个测试 catch。

设计取舍
========

- **不验证 payload at runtime**: emit() 在 ``_lock`` 临界区里跑, 增加
  schema 验证会让 fan-out 慢、bus throughput 下降。schema 在测试期 + IDE
  期通过 ``validate_payload`` API 暴露, 但 production hot path 不调用。
- **不强制 emit 通过 schema-aware wrapper**: emit_site 仍然写
  ``_sse_bus.emit("task_changed", payload)`` —— schema registry 是
  *补充约定*, 不是 *强制规则*。这样既保留 free-form 灵活度, 又能
  在测试 / 文档层确立 contract。
- **frozenset 字段**: ``EventSchema.required_fields`` / ``optional_fields``
  用 ``frozenset`` 而不是 ``list`` —— set semantics (无序、唯一) 正符
  合 "字段集" 语义, 且 schema 对象本身可 hash, 方便缓存。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventSchema:
    """单一 SSE event type 的 payload schema 定义。

    Attributes:
        name: event_type 字符串 (与 ``_sse_bus.emit`` 第一个参数对齐);
        required_fields: payload dict 必须出现的字段集;
        optional_fields: payload dict 可以出现的字段集 (出现 → 必须;
            不出现 → emit 不传也 OK);
        description: 一句话描述这个 event 何时被 emit、消费方关心什么;
        emitted_by: tuple of source module paths (relative to repo root)
            that emit this event. **建议**保持 alphabetical sort, 让
            reviewer 快速定位 emit-site。注意: oversize_drop 是 bus
            自身的内置替换路径, emitted_by 指 bus 本身。
    """

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


def get_known_event_types() -> tuple[str, ...]:
    """返回已注册的 event type 名集合 (tuple, 顺序按字母排序)。"""
    return tuple(sorted(EVENT_SCHEMAS))


def get_schema(event_type: str) -> EventSchema | None:
    """按 event_type 查 schema。未注册 → ``None``。"""
    return EVENT_SCHEMAS.get(event_type)


def validate_payload(event_type: str, payload: dict[str, Any] | None) -> list[str]:
    """验证 payload 是否符合 event_type 的 schema。

    返回 violations 字符串列表 (empty == 合规)。**测试期使用**——
    production emit 路径 *不* 调用 (见模块 docstring 说明)。

    检测内容:
      1. event_type 必须在 ``EVENT_SCHEMAS`` 中;
      2. payload 必须为 dict (None / 其他类型 → 1 条 violation);
      3. 每个 ``required_fields`` 字段必须存在;
      4. payload 字段名必须在 ``required_fields ∪ optional_fields``
         (额外字段 → violation, 防止 typo / silent schema drift)。
    """
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
