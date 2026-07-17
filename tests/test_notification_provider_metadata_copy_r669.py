"""R669 - Web/Sound provider metadata snapshots use dict.copy()."""

from __future__ import annotations

import inspect
from typing import Any, cast

from ai_intervention_agent.notification_manager import (
    NotificationConfig,
    NotificationEvent,
    NotificationTrigger,
)
from ai_intervention_agent.notification_providers import (
    SoundNotificationProvider,
    WebNotificationProvider,
)


def _event() -> NotificationEvent:
    return NotificationEvent(
        id="r669",
        title="Title",
        message="Message",
        trigger=NotificationTrigger.IMMEDIATE,
        metadata={"task_id": "task-1", "nested": {"kept": True}},
    )


def test_web_and_sound_metadata_snapshots_use_copy_method() -> None:
    web_source = inspect.getsource(WebNotificationProvider.send)
    sound_source = inspect.getsource(SoundNotificationProvider.send)

    assert (
        "metadata_copy = event.metadata.copy() if event.metadata else {}" in web_source
    )
    assert "metadata_copy = dict(event.metadata)" not in web_source
    assert (
        "metadata_copy = event.metadata.copy() if event.metadata else {}"
        in sound_source
    )
    assert "metadata_copy = dict(event.metadata)" not in sound_source


def test_web_metadata_snapshot_top_level_mutation_does_not_pollute_event() -> None:
    provider = WebNotificationProvider(NotificationConfig())
    event = _event()

    assert provider.send(event)
    data = cast(dict[str, Any], event.metadata["web_notification_data"])
    metadata_snapshot = cast(dict[str, Any], data["metadata"])
    metadata_snapshot["task_id"] = "polluted"

    assert event.metadata["task_id"] == "task-1"
    assert "web_notification_data" not in metadata_snapshot


def test_sound_metadata_snapshot_top_level_mutation_does_not_pollute_event() -> None:
    provider = SoundNotificationProvider(NotificationConfig())
    event = _event()

    assert provider.send(event)
    data = cast(dict[str, Any], event.metadata["sound_notification_data"])
    metadata_snapshot = cast(dict[str, Any], data["metadata"])
    metadata_snapshot["task_id"] = "polluted"

    assert event.metadata["task_id"] == "task-1"
    assert "sound_notification_data" not in metadata_snapshot
