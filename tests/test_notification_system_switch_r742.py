"""R742 — ``system_enabled = false`` keeps the MCP server from raising desktop notifications.

Why this exists
---------------
``create_notification_providers`` registers the system provider whenever the platform
can run it (``plyer`` imports, plus ``pyobjus`` on macOS) and never looks at
``system_enabled``, while the MCP server asks for the SYSTEM channel with every feedback
request.  So the shipped default (``system_enabled = false``, "off by default to avoid
unexpected popups" in ``config.toml.default``) still raised one desktop notification per
request wherever the provider works, and a user who turned the switch off could not
stop them.

With ``skip_unavailable=True`` the manager now also drops SYSTEM when the switch is off.
The switch is read at send time, so changing it in the config applies to the next
request; callers that pass their own list without the flag are unchanged.

Pattern: A (runtime behaviour of the real manager and provider factory).
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from ai_intervention_agent.notification_manager import (
    NotificationManager,
    NotificationType,
)
from ai_intervention_agent.notification_models import NotificationTrigger
from ai_intervention_agent.notification_providers import (
    SystemNotificationProvider,
    create_notification_providers,
)

SYSTEM = NotificationType.SYSTEM
BARK = NotificationType.BARK
MCP_TYPES = [NotificationType.SYSTEM, NotificationType.SOUND, NotificationType.BARK]


@pytest.fixture
def desktop(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """A platform on which the system provider works; records what it would show."""
    shown: list[dict[str, object]] = []

    def usable(self: SystemNotificationProvider) -> None:
        self._notify = lambda **kwargs: shown.append(kwargs)
        self.supported = True

    monkeypatch.setattr(SystemNotificationProvider, "_check_system_support", usable)
    return shown


@pytest.fixture
def mgr() -> Iterator[NotificationManager]:
    manager = NotificationManager._create_test_instance()
    manager._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="R742")
    manager.config.retry_count = 0
    manager.config.web_enabled = False
    manager.config.sound_enabled = False
    manager.config.bark_enabled = False
    yield manager
    manager._executor.shutdown(wait=True)


def _register_providers(manager: NotificationManager) -> None:
    for kind, provider in create_notification_providers(manager.config).items():
        manager.register_provider(kind, provider)


def _send(
    manager: NotificationManager,
    *,
    types: list[NotificationType] | None = None,
    skip_unavailable: bool | None = None,
) -> str:
    requested = list(MCP_TYPES) if types is None else types
    if skip_unavailable is None:
        return manager.send_notification(
            title="t",
            message="m",
            trigger=NotificationTrigger.IMMEDIATE,
            types=requested,
        )
    return manager.send_notification(
        title="t",
        message="m",
        trigger=NotificationTrigger.IMMEDIATE,
        types=requested,
        skip_unavailable=skip_unavailable,
    )


def test_a_system_channel_that_is_switched_off_raises_no_notification(
    mgr: NotificationManager, desktop: list[dict[str, object]]
) -> None:
    mgr.config.system_enabled = False
    _register_providers(mgr)
    assert SYSTEM in mgr._providers

    event_id = _send(mgr, skip_unavailable=True)

    assert event_id == ""
    assert desktop == []
    assert mgr._event_queue == []
    assert mgr._stats["events_total"] == 0


def test_a_system_channel_that_is_switched_on_raises_one(
    mgr: NotificationManager, desktop: list[dict[str, object]]
) -> None:
    mgr.config.system_enabled = True
    _register_providers(mgr)

    event_id = _send(mgr, skip_unavailable=True)

    assert event_id.startswith("notification_")
    assert mgr._event_queue[-1].types == [SYSTEM]
    assert [(n["title"], n["message"]) for n in desktop] == [("t", "m")]
    assert mgr._stats["events_failed"] == 0


def test_the_switch_is_read_at_send_time(
    mgr: NotificationManager, desktop: list[dict[str, object]]
) -> None:
    mgr.config.system_enabled = False
    _register_providers(mgr)

    _send(mgr, skip_unavailable=True)
    assert len(desktop) == 0

    mgr.config.system_enabled = True
    _send(mgr, skip_unavailable=True)
    assert len(desktop) == 1

    mgr.config.system_enabled = False
    _send(mgr, skip_unavailable=True)
    assert len(desktop) == 1


def test_the_other_channels_do_not_follow_the_system_switch(
    mgr: NotificationManager, desktop: list[dict[str, object]]
) -> None:
    mgr.config.system_enabled = False
    _register_providers(mgr)
    bark = MagicMock()
    bark.send.return_value = True
    mgr._providers[BARK] = bark

    _send(mgr, skip_unavailable=True)

    assert mgr._event_queue[-1].types == [BARK]
    assert bark.send.call_count == 1
    assert desktop == []


def test_without_the_flag_the_callers_own_list_is_taken_as_given(
    mgr: NotificationManager, desktop: list[dict[str, object]]
) -> None:
    mgr.config.system_enabled = False
    _register_providers(mgr)

    _send(mgr, types=[SYSTEM])

    assert len(desktop) == 1
