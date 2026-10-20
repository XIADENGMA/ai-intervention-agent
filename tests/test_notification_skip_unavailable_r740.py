"""R740 — a notification channel that is not available is skipped, not retried as a failed delivery.

Why this exists
---------------
For every feedback request the MCP server asks the notification manager for
the SYSTEM, SOUND and BARK channels.  A channel has a provider only when its
config switch is on (and, for system notifications, when plyer -- plus pyobjus
on macOS -- is installed).  With sound off, no Bark key and no plyer, none of
the three had a provider, and the manager counted "no provider" as a delivery
that failed: three retries two seconds apart and a fallback, i.e. four WARNING
lines and seven seconds of timers for every task, although nothing could ever
succeed.

``send_notification(..., skip_unavailable=True)`` drops the requested channels
that have no provider and sends nothing when none is left; the MCP server
uses it.  Other callers keep the old accounting, which the health views read
(R143 / R145).  A system channel that is switched on but cannot be used is
reported once, when the providers are created.

Pattern: A (runtime behaviour of the real manager).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from ai_intervention_agent import notification_manager as manager_module
from ai_intervention_agent import notification_providers as providers_module
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.notification_manager import (
    NotificationConfig,
    NotificationManager,
    NotificationType,
)
from ai_intervention_agent.notification_models import NotificationTrigger
from ai_intervention_agent.notification_providers import (
    SystemNotificationProvider,
    create_notification_providers,
)

MCP_TYPES = [NotificationType.SYSTEM, NotificationType.SOUND, NotificationType.BARK]


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def warnings(self) -> list[str]:
        return [
            record.getMessage()
            for record in self.records
            if record.levelno >= logging.WARNING
        ]


@contextmanager
def _captured(module_logger: EnhancedLogger) -> Iterator[_Collect]:
    # caplog is blind to these loggers (they do not propagate), and an
    # identical message repeated within five seconds is dropped.
    module_logger.deduplicator.cache.clear()
    logger = module_logger.logger
    handler = _Collect()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


@pytest.fixture
def mgr() -> Iterator[NotificationManager]:
    manager = NotificationManager._create_test_instance()
    manager._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="R740")
    manager.config.retry_count = 0
    yield manager
    manager._executor.shutdown(wait=True)


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


def test_nothing_is_sent_when_no_requested_channel_has_a_provider(
    mgr: NotificationManager,
) -> None:
    with _captured(manager_module.logger) as logs:
        event_id = _send(mgr, skip_unavailable=True)

    assert event_id == ""
    assert mgr._event_queue == []
    assert mgr._stats["events_total"] == 0
    assert mgr._stats["events_failed"] == 0
    assert mgr._stats["retries_scheduled"] == 0
    assert mgr._stats["providers"] == {}
    assert logs.warnings() == []
    assert any("没有可用的通知渠道" in r.getMessage() for r in logs.records)


def test_only_the_channels_that_have_a_provider_are_used(
    mgr: NotificationManager,
) -> None:
    bark = MagicMock()
    bark.send.return_value = True
    mgr._providers[NotificationType.BARK] = bark

    with _captured(manager_module.logger) as logs:
        event_id = _send(mgr, skip_unavailable=True)

    assert event_id.startswith("notification_")
    assert mgr._event_queue[-1].types == [NotificationType.BARK]
    assert bark.send.call_count == 1
    assert mgr._stats["events_succeeded"] == 1
    assert mgr._stats["events_failed"] == 0
    assert set(mgr._stats["providers"]) == {"bark"}
    assert logs.warnings() == []


def test_the_callers_list_is_left_alone(mgr: NotificationManager) -> None:
    requested = [NotificationType.SYSTEM, NotificationType.BARK]

    _send(mgr, types=requested, skip_unavailable=True)

    assert requested == [NotificationType.SYSTEM, NotificationType.BARK]


def test_without_the_flag_a_missing_provider_is_still_a_failed_delivery(
    mgr: NotificationManager,
) -> None:
    with _captured(manager_module.logger) as logs:
        event_id = _send(mgr)

    assert event_id.startswith("notification_")
    assert mgr._stats["events_failed"] == 1
    for channel in ("system", "sound", "bark"):
        stats = mgr._stats["providers"][channel]
        assert stats["failure"] == 1
        assert stats["last_error"] == "provider_not_registered"
    assert any("所有通知方式失败" in line for line in logs.warnings())


def test_a_channel_that_has_a_provider_but_fails_is_still_reported(
    mgr: NotificationManager,
) -> None:
    bark = MagicMock()
    bark.send.return_value = False
    mgr._providers[NotificationType.BARK] = bark

    with _captured(manager_module.logger) as logs:
        _send(mgr, skip_unavailable=True)

    assert mgr._stats["events_failed"] == 1
    assert mgr._stats["providers"]["bark"]["failure"] == 1
    assert any("所有通知方式失败" in line for line in logs.warnings())


def _unusable_system_support(self: SystemNotificationProvider) -> None:
    self._notify = None
    self.supported = False


def _usable_system_support(self: SystemNotificationProvider) -> None:
    self._notify = lambda **_: None
    self.supported = True


def _config(*, system_enabled: bool) -> NotificationConfig:
    return NotificationConfig(
        web_enabled=False,
        sound_enabled=False,
        bark_enabled=False,
        system_enabled=system_enabled,
    )


def test_a_system_channel_that_is_on_but_unusable_is_reported_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SystemNotificationProvider, "_check_system_support", _unusable_system_support
    )

    with _captured(providers_module.logger) as logs:
        providers = create_notification_providers(_config(system_enabled=True))

    assert providers == {}
    lines = logs.warnings()
    assert len(lines) == 1
    assert "system_enabled" in lines[0]
    assert "plyer" in lines[0]


def test_a_system_channel_that_is_off_is_not_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SystemNotificationProvider, "_check_system_support", _unusable_system_support
    )

    with _captured(providers_module.logger) as logs:
        providers = create_notification_providers(_config(system_enabled=False))

    assert providers == {}
    assert logs.warnings() == []


def test_a_usable_system_channel_is_registered_and_not_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SystemNotificationProvider, "_check_system_support", _usable_system_support
    )

    with _captured(providers_module.logger) as logs:
        providers = create_notification_providers(_config(system_enabled=True))

    assert set(providers) == {NotificationType.SYSTEM}
    assert logs.warnings() == []
