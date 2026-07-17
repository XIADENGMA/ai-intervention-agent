"""R647 - SSE emit reuses the serializer-normalized payload object."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch

from ai_intervention_agent.web_ui_routes import task as task_module
from ai_intervention_agent.web_ui_routes.task import _SSEBus


class _FalsyPayload(dict[str, Any]):
    """Falsy mapping used to catch a second ``payload or {}`` normalization."""

    def __bool__(self) -> bool:
        return False


def test_emit_reuses_payload_object_returned_by_serializer() -> None:
    bus = _SSEBus()
    q = bus.subscribe()
    normalized_payload = _FalsyPayload()

    with patch.object(
        task_module,
        "_serialize_sse_payload",
        return_value=(normalized_payload, "{}"),
    ):
        bus.emit("task_changed", None)

    payload = q.get_nowait()
    assert payload["data"] is normalized_payload
    assert payload["_serialized"] == "{}"


def test_emit_none_payload_still_exposes_empty_dict() -> None:
    bus = _SSEBus()
    q = bus.subscribe()

    bus.emit("task_changed", None)

    payload = q.get_nowait()
    assert payload["data"] == {}
    assert payload["_serialized"] == "{}"


def test_emit_payload_source_does_not_renormalize_data() -> None:
    source = inspect.getsource(_SSEBus.emit)

    serialize_idx = source.index("data, serialized_data = _serialize_sse_payload(data)")
    payload_idx = source.index('"data": data')
    assert serialize_idx < payload_idx
    assert '"data": data or {}' not in source
