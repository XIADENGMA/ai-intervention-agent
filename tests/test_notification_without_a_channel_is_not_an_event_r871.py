"""R871 - a notification with no channel to go to is not an event.

What was wrong
--------------
``NotificationManager.send_notification`` created the event first and found out only
afterwards that there was nothing to send it to. With ``types=None`` and every channel
off in the configuration (a muted sound counts as off), or with an explicit
``types=[]``, it

* returned a real event id,
* counted the event in ``events_total``,
* wrote the event into ``notification_inflight.json``,
* and then ``_process_event`` returned at ``if not event.types`` without ever calling
  ``_mark_event_finalized``.

So the event stayed in flight for the life of the process: ``get_status()`` reported
``events_in_flight == 1`` for good, and the in-flight file kept the event, so the next
process reported "a notification was not delivered last time" for something that never
had a place to go.

Nothing in the project asks for such an event today (the Web UI and the MCP server name
their channels, and the MCP server passes ``skip_unavailable=True``), so nothing
user-visible broke. But the ``skip_unavailable`` branch already answered ``""`` for the
same situation, so the two ways of having no channel disagreed. The old branch-coverage
test ``test_auto_types_all_disabled`` asserted the leak (a non-empty id); it now asserts
the empty answer.

What this module pins
---------------------
* every way of ending up with no channel answers ``""`` and leaves nothing behind: no
  count, no queue entry, no in-flight id, no file, no timer, nothing for a process that
  starts afterwards to find, whatever the trigger;
* a channel that is named but cannot deliver is still an event (it fails, and is
  finalized as a failure), so the new answer does not swallow real failures;
* a channel that is on still makes an event that is delivered, finalized and removed
  from the in-flight file, and explicit channels are not filtered by the configuration.

The in-flight directory is the real one of a real ``ConfigManager`` in ``tmp_path``
(R794), not a patched function.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from ai_intervention_agent import notification_manager as nm
from ai_intervention_agent.config_manager import ConfigManager
from ai_intervention_agent.notification_manager import (
    _INFLIGHT_FILE_NAME,
    NotificationManager,
    NotificationTrigger,
    NotificationType,
)


class Records:
    """A channel provider that remembers what it was asked to send."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def send(self, event: Any) -> bool:
        self.events.append(event)
        return True


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A real ``ConfigManager`` whose file is in ``tmp_path``."""
    manager = ConfigManager(str(tmp_path / "config.toml"))
    monkeypatch.setattr(nm, "get_config", lambda: manager)
    try:
        yield tmp_path
    finally:
        manager.shutdown()


@pytest.fixture
def mgr(config_dir: Path) -> Iterator[NotificationManager]:
    """A fresh manager with a real worker pool and no channel switched on."""
    manager = NotificationManager._create_test_instance()
    manager._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="R871")
    manager.config.enabled = True
    manager.config.retry_count = 0
    set_channels(manager)
    try:
        yield manager
    finally:
        manager.shutdown(wait=True)


def set_channels(
    manager: NotificationManager,
    *,
    web: bool = False,
    sound: bool = False,
    mute: bool = False,
    bark: bool = False,
    system: bool = False,
) -> None:
    manager.config.web_enabled = web
    manager.config.sound_enabled = sound
    manager.config.sound_mute = mute
    manager.config.bark_enabled = bark
    manager.config.system_enabled = system


def stats(manager: NotificationManager) -> dict[str, Any]:
    return manager.get_status()["stats"]


def inflight_file(config_dir: Path) -> Path:
    return config_dir / _INFLIGHT_FILE_NAME


def assert_nothing_was_created(manager: NotificationManager, config_dir: Path) -> None:
    """The manager is exactly as it was before the call."""
    snapshot = stats(manager)
    assert snapshot["events_total"] == 0
    assert snapshot["events_in_flight"] == 0
    assert snapshot["events_finalized"] == 0
    assert snapshot["last_event_id"] is None
    assert manager._event_queue == []
    assert manager._inflight_persisted_ids == set()
    assert manager.get_status()["inflight_persisted_count"] == 0
    assert manager._delayed_timers == {}
    assert not inflight_file(config_dir).exists()


# ---------------------------------------------------------------------------
# 1. No channel: no event
# ---------------------------------------------------------------------------
class TestNoChannelNoEvent:
    def test_every_channel_off_in_the_configuration(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        assert mgr.send_notification("title", "message") == ""
        assert_nothing_was_created(mgr, config_dir)

    def test_an_empty_list_of_channels(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        set_channels(mgr, web=True, bark=True)  # the configuration is not consulted
        assert mgr.send_notification("title", "message", types=[]) == ""
        assert_nothing_was_created(mgr, config_dir)

    def test_a_muted_sound_is_no_channel(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        set_channels(mgr, sound=True, mute=True)
        assert mgr.send_notification("title", "message") == ""
        assert_nothing_was_created(mgr, config_dir)

    @pytest.mark.parametrize("trigger", list(NotificationTrigger))
    def test_the_answer_does_not_depend_on_the_trigger(
        self,
        mgr: NotificationManager,
        config_dir: Path,
        trigger: NotificationTrigger,
    ) -> None:
        assert mgr.send_notification("title", "message", trigger=trigger) == ""
        assert_nothing_was_created(mgr, config_dir)

    def test_a_delayed_notification_without_a_channel_starts_no_timer(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        mgr.config.trigger_delay = 3600
        result = mgr.send_notification(
            "title", "message", trigger=NotificationTrigger.DELAYED
        )
        assert result == ""
        assert mgr._delayed_timers == {}
        assert_nothing_was_created(mgr, config_dir)

    def test_asking_again_and_again_leaves_nothing(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        for _ in range(6):
            assert mgr.send_notification("title", "message") == ""
            assert mgr.send_notification("title", "message", types=[]) == ""
        assert_nothing_was_created(mgr, config_dir)

    def test_a_process_that_starts_afterwards_finds_nothing_in_flight(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        mgr.send_notification("title", "message")
        mgr.send_notification("title", "message", types=[])
        later = NotificationManager._create_test_instance()
        try:
            assert later._load_persisted_inflight_events() == []
        finally:
            later.shutdown(wait=False)

    def test_skip_unavailable_gives_the_same_answer(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        # the channels are named, but none of them has a provider
        result = mgr.send_notification(
            "title",
            "message",
            types=[NotificationType.WEB, NotificationType.BARK],
            skip_unavailable=True,
        )
        assert result == ""
        assert_nothing_was_created(mgr, config_dir)

    def test_skip_unavailable_with_the_system_channel_switched_off(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        mgr.register_provider(NotificationType.SYSTEM, Records())
        result = mgr.send_notification(
            "title",
            "message",
            types=[NotificationType.SYSTEM],
            skip_unavailable=True,
        )
        assert result == ""
        assert_nothing_was_created(mgr, config_dir)

    def test_the_disabled_and_closed_answers_are_unchanged(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        set_channels(mgr, web=True)
        mgr.config.enabled = False
        assert mgr.send_notification("title", "message") == ""
        mgr.config.enabled = True
        mgr._shutdown_called = True
        assert mgr.send_notification("title", "message") == ""
        assert_nothing_was_created(mgr, config_dir)


# ---------------------------------------------------------------------------
# 2. A named channel that cannot deliver is still an event
# ---------------------------------------------------------------------------
class TestAChannelThatFailsIsStillAnEvent:
    def test_a_channel_without_a_provider_is_an_event_that_fails(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        event_id = mgr.send_notification(
            "title", "message", types=[NotificationType.BARK]
        )
        assert event_id.startswith("notification_")
        snapshot = stats(mgr)
        assert snapshot["events_total"] == 1
        assert snapshot["events_failed"] == 1
        assert snapshot["events_in_flight"] == 0
        assert not inflight_file(config_dir).exists()

    def test_a_provider_that_says_no_is_an_event_that_fails(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        class Refuses:
            def send(self, event: Any) -> bool:
                return False

        mgr.register_provider(NotificationType.WEB, Refuses())
        set_channels(mgr, web=True)
        assert mgr.send_notification("title", "message").startswith("notification_")
        snapshot = stats(mgr)
        assert (snapshot["events_total"], snapshot["events_failed"]) == (1, 1)
        assert snapshot["events_in_flight"] == 0


# ---------------------------------------------------------------------------
# 3. A channel that is on still works
# ---------------------------------------------------------------------------
class TestAChannelThatIsOnStillWorks:
    def test_the_configured_channel_gets_the_event_and_it_is_finalized(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        channel = Records()
        mgr.register_provider(NotificationType.WEB, channel)
        set_channels(mgr, web=True)

        event_id = mgr.send_notification("title", "message")

        assert event_id.startswith("notification_")
        assert [event.id for event in channel.events] == [event_id]
        assert channel.events[0].types == [NotificationType.WEB]
        snapshot = stats(mgr)
        assert snapshot["events_total"] == 1
        assert snapshot["events_succeeded"] == 1
        assert snapshot["events_in_flight"] == 0
        assert snapshot["last_event_id"] == event_id
        assert mgr.get_status()["inflight_persisted_count"] == 0
        assert not inflight_file(config_dir).exists()

    def test_an_explicit_channel_is_not_filtered_by_the_configuration(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        channel = Records()
        mgr.register_provider(NotificationType.WEB, channel)
        set_channels(mgr)  # every channel off in the configuration

        event_id = mgr.send_notification(
            "title", "message", types=[NotificationType.WEB]
        )

        assert event_id.startswith("notification_")
        assert [event.id for event in channel.events] == [event_id]
        assert stats(mgr)["events_in_flight"] == 0

    def test_only_the_channels_that_remain_are_asked(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        web, sound = Records(), Records()
        mgr.register_provider(NotificationType.WEB, web)
        mgr.register_provider(NotificationType.SOUND, sound)
        set_channels(mgr, web=True, sound=True, mute=True)

        event_id = mgr.send_notification("title", "message")

        assert event_id.startswith("notification_")
        assert len(web.events) == 1
        assert sound.events == []

    def test_the_event_is_in_the_file_while_the_channel_is_busy(
        self, mgr: NotificationManager, config_dir: Path
    ) -> None:
        import json
        import threading

        entered, release = threading.Event(), threading.Event()
        seen_on_disk: list[list[str]] = []

        class Busy:
            def send(self, event: Any) -> bool:
                entered.set()
                path = inflight_file(config_dir)
                seen_on_disk.append(
                    [
                        e["id"]
                        for e in json.loads(path.read_text(encoding="utf-8"))["events"]
                    ]
                )
                release.set()
                return True

        mgr.register_provider(NotificationType.WEB, Busy())
        set_channels(mgr, web=True)

        event_id = mgr.send_notification("title", "message")

        assert entered.is_set() and release.is_set()
        assert seen_on_disk == [[event_id]]
        assert not inflight_file(config_dir).exists()
