"""R762: a test does not see what the tests before it left in two shared places.

Two pieces of process-wide state made the outcome of a test depend on the order in
which the tests ran.  A random order (pytest-randomly) exposed seven such tests.

* ``EnhancedLogger`` drops a message that repeats within five seconds, and the
  window lives as long as the process.  A warning one test had emitted hid the same
  warning from the log capture of the next test.
* ``NotificationManager.__new__`` registers whatever instance it builds as the
  singleton, so a test that built its own manager left it behind for every later
  ``NotificationManager()``, shut down or not.

``tests/conftest.py`` empties the log windows (``reset_log_duplicate_windows``) and
puts the module's ``notification_manager`` back before each test.  The two pairs
below rely on pytest running the functions of a module in definition order: the
first leaves the state behind, the second looks for it.  With the conftest they pass
in any order; without it the second fails whenever it follows the first.  The
remaining tests call the reset itself.
"""

from __future__ import annotations

import logging
import sys
import threading
import types
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from ai_intervention_agent import enhanced_logging as enhanced_logging_module
from ai_intervention_agent import notification_manager as manager_module
from ai_intervention_agent.web_ui_routes import task as task_module
from tests.conftest import reset_log_duplicate_windows

MESSAGE = "R762 one warning, sent twice"
ENTRY = (0.0, 1)

# Looked up when the test runs: a test may reload enhanced_logging, which replaces
# the logger object the module holds.
LOGGERS: dict[str, Callable[[], Any]] = {
    "web_ui_routes.task": lambda: task_module.logger,
    "notification_manager": lambda: manager_module.logger,
    "enhanced_logging": lambda: enhanced_logging_module.enhanced_logger,
}


class Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def captured(module_logger: Any) -> Iterator[list[str]]:
    """What the module logger writes; caplog is blind to it, it does not propagate."""
    target = module_logger.logger
    handler = Collect()
    previous_level = target.level
    target.addHandler(handler)
    target.setLevel(logging.WARNING)
    try:
        yield handler.messages
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)


def probe_module(name: str, **attributes: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    vars(module).update(attributes)
    return module


def stale_logger() -> Any:
    """A logger of a class that was replaced when enhanced_logging was reloaded."""
    replaced_class = type("EnhancedLogger", (), {})
    instance = replaced_class()
    vars(instance)["deduplicator"] = SimpleNamespace(
        lock=threading.Lock(), cache={1: ENTRY}
    )
    return instance


@pytest.mark.parametrize("name", LOGGERS)
def test_a_repeat_within_one_test_is_dropped(name: str) -> None:
    module_logger = LOGGERS[name]()
    with captured(module_logger) as seen:
        module_logger.warning(MESSAGE)
        module_logger.warning(MESSAGE)
    assert seen == [MESSAGE]


@pytest.mark.parametrize("name", LOGGERS)
def test_the_next_test_gets_the_same_message_again(name: str) -> None:
    module_logger = LOGGERS[name]()
    with captured(module_logger) as seen:
        module_logger.warning(MESSAGE)
    assert seen == [MESSAGE]


def test_a_test_that_builds_its_own_manager_leaves_it_as_the_singleton() -> None:
    manager_class = manager_module.NotificationManager
    manager_class._instance = None
    own = manager_class.__new__(manager_class)
    assert manager_class._instance is own


def test_the_next_test_gets_the_module_singleton_again() -> None:
    manager_class = manager_module.NotificationManager
    assert manager_class._instance is manager_module.notification_manager


def test_the_reset_empties_the_window_of_every_module_logger() -> None:
    loggers = [lookup() for lookup in LOGGERS.values()]
    for module_logger in loggers:
        module_logger.deduplicator.cache[1] = ENTRY

    reset_log_duplicate_windows()

    assert not any(module_logger.deduplicator.cache for module_logger in loggers)


def test_the_reset_reaches_a_logger_of_a_replaced_class() -> None:
    stale = stale_logger()
    probe = probe_module("ai_intervention_agent._r762_stale", logger=stale)

    with patch.dict(sys.modules, {probe.__name__: probe}):
        reset_log_duplicate_windows()

    assert stale.deduplicator.cache == {}


def test_the_reset_reads_the_enhanced_logger_attribute_too() -> None:
    stale = stale_logger()
    probe = probe_module("ai_intervention_agent._r762_named", enhanced_logger=stale)

    with patch.dict(sys.modules, {probe.__name__: probe}):
        reset_log_duplicate_windows()

    assert stale.deduplicator.cache == {}


def test_the_reset_leaves_other_objects_named_logger_alone() -> None:
    impostor = SimpleNamespace(
        deduplicator=SimpleNamespace(lock=threading.Lock(), cache={1: ENTRY})
    )
    probe = probe_module("ai_intervention_agent._r762_other", logger=impostor)

    with patch.dict(sys.modules, {probe.__name__: probe}):
        reset_log_duplicate_windows()

    assert impostor.deduplicator.cache == {1: ENTRY}


def test_the_reset_leaves_modules_outside_the_package_alone() -> None:
    stale = stale_logger()
    probe = probe_module("elsewhere_r762_probe", logger=stale)

    with patch.dict(sys.modules, {probe.__name__: probe}):
        reset_log_duplicate_windows()

    assert stale.deduplicator.cache == {1: ENTRY}


def test_the_reset_tolerates_blocked_and_foreign_entries() -> None:
    entries = {
        "ai_intervention_agent._r762_blocked": None,
        "ai_intervention_agent._r762_plain_object": object(),
    }

    with patch.dict(sys.modules, entries):
        reset_log_duplicate_windows()
