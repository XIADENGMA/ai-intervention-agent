from __future__ import annotations

import inspect
from typing import Any, cast
from unittest.mock import MagicMock, patch

from ai_intervention_agent.notification_manager import NotificationManager


def test_notification_cleanup_snapshots_use_tuples() -> None:
    reset_source = inspect.getsource(NotificationManager.reset_for_testing)
    shutdown_source = inspect.getsource(NotificationManager.shutdown)

    assert "tuple(self._delayed_timers.values())" in reset_source
    assert "timers = tuple(self._delayed_timers.values())" in shutdown_source
    assert (
        'worker_threads = tuple(getattr(self._executor, "_threads", ()) or ())'
        in shutdown_source
    )
    assert "providers = tuple(self._providers.values())" in shutdown_source

    assert "list(self._delayed_timers.values())" not in reset_source
    assert "list(self._delayed_timers.values())" not in shutdown_source
    assert "list(self._providers.values())" not in shutdown_source
    assert 'list(getattr(self._executor, "_threads", ()) or ())' not in shutdown_source


def test_reset_for_testing_still_cancels_and_clears_delayed_timers() -> None:
    manager = NotificationManager._create_test_instance()
    timer_a = MagicMock()
    timer_b = MagicMock()
    manager._delayed_timers = {"a": timer_a, "b": timer_b}

    manager.reset_for_testing()

    timer_a.cancel.assert_called_once()
    timer_b.cancel.assert_called_once()
    assert manager._delayed_timers == {}


def test_shutdown_tuple_snapshots_still_cleanup_timers_threads_and_providers() -> None:
    manager = NotificationManager._create_test_instance()
    timer = MagicMock()
    provider = MagicMock()
    worker_thread = MagicMock()
    executor = MagicMock()
    executor._threads = {worker_thread}
    manager._delayed_timers = {"timer": timer}
    cast(Any, manager)._providers = {"provider": provider}
    manager._executor = executor

    with patch.object(manager, "_safe_close_provider") as close_provider:
        manager.shutdown(wait=False, grace_period=0.01)

    timer.cancel.assert_called_once()
    executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    worker_thread.join.assert_called()
    close_provider.assert_called_once_with(provider)
    assert manager._delayed_timers == {}
    assert manager._providers == {}
