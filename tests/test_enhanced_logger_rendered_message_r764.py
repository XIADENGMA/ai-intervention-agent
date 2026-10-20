"""R764: ``EnhancedLogger`` deduplicates and records the message it writes, not its template.

``logger.error("Jinja2 模板缺失: %s", exc)`` hands the template and its argument to the
stdlib logger separately, and a handler fills the argument in when it formats the record.
``EnhancedLogger.log`` used the template, as it came in, for the other two things it does:

* the duplicate check hashed the template, so a second error with the same template and
  another argument inside the five-second window was dropped as a repeat of the first;
* the ring buffer behind ``aiia://server/info`` and ``get_recent_logs`` stored the
  template, so an entry read ``Jinja2 模板缺失: %s`` and the cause was nowhere in it.

Three calls in the code base pass arguments this way (the missing template in
``web_ui.py``, two damaged-file warnings in ``notification_manager.py``).  ``log`` now
fills the arguments in the way the stdlib does, with the template as the fallback when
that fails, and feeds the result to both.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from ai_intervention_agent import enhanced_logging
from ai_intervention_agent.enhanced_logging import EnhancedLogger


class Collect(logging.Handler):
    """Keeps the records as they arrive, without formatting them."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class Unprintable:
    def __str__(self) -> str:
        raise RuntimeError("no text for this object")


@pytest.fixture(autouse=True)
def _empty_ring() -> Iterator[None]:
    enhanced_logging.clear_recent_logs()
    yield
    enhanced_logging.clear_recent_logs()


@contextmanager
def watched(name: str) -> Iterator[tuple[EnhancedLogger, Collect]]:
    logger = EnhancedLogger(f"r764.{name}")
    collector = Collect()
    logger.logger.addHandler(collector)
    try:
        yield logger, collector
    finally:
        logger.logger.removeHandler(collector)


def ring_messages(logger: EnhancedLogger) -> list[str]:
    return [
        entry["message"]
        for entry in enhanced_logging.get_recent_logs()
        if entry["logger_name"] == logger.logger.name
    ]


def test_the_ring_entry_has_the_arguments_filled_in() -> None:
    with watched("ring") as (logger, _):
        logger.error("Jinja2 模板缺失: %s", RuntimeError("base.html"))

        assert ring_messages(logger) == ["Jinja2 模板缺失: base.html"]


def test_the_same_template_with_another_argument_is_logged_again() -> None:
    with watched("other_argument") as (logger, collector):
        logger.error("Jinja2 模板缺失: %s", "base.html")
        logger.error("Jinja2 模板缺失: %s", "other.html")

        assert [record.getMessage() for record in collector.records] == [
            "Jinja2 模板缺失: base.html",
            "Jinja2 模板缺失: other.html",
        ]
        assert ring_messages(logger) == [
            "Jinja2 模板缺失: base.html",
            "Jinja2 模板缺失: other.html",
        ]


def test_the_same_message_twice_is_still_logged_once() -> None:
    with watched("same_message") as (logger, collector):
        logger.error("Jinja2 模板缺失: %s", "base.html")
        logger.error("Jinja2 模板缺失: %s", "base.html")

        assert len(collector.records) == 1
        assert ring_messages(logger) == ["Jinja2 模板缺失: base.html"]


def test_a_message_without_arguments_is_recorded_as_given() -> None:
    with watched("no_arguments") as (logger, collector):
        logger.warning("50%% off, 100% sure")

        assert [record.msg for record in collector.records] == ["50%% off, 100% sure"]
        assert ring_messages(logger) == ["50%% off, 100% sure"]


def test_a_mapping_argument_fills_named_placeholders() -> None:
    with watched("mapping") as (logger, _):
        logger.warning("%(kind)s: %(name)s", {"kind": "模板", "name": "base.html"})

        assert ring_messages(logger) == ["模板: base.html"]


def test_an_empty_mapping_is_not_unwrapped() -> None:
    with watched("empty_mapping") as (logger, _):
        logger.warning("kept: %s", {})

        assert ring_messages(logger) == ["kept: {}"]


def test_the_repeat_note_reaches_the_ring_as_it_reaches_the_log() -> None:
    with watched("repeat_note") as (logger, collector):
        with patch.object(
            logger.deduplicator, "should_log", return_value=(True, "重复 3 次")
        ):
            logger.warning("again: %s", "base.html")

        assert [record.msg for record in collector.records] == ["again: %s (重复 3 次)"]
        assert ring_messages(logger) == ["again: base.html (重复 3 次)"]


def test_the_deduplicator_is_asked_about_the_filled_in_message() -> None:
    with watched("asked") as (logger, _):
        with patch.object(
            logger.deduplicator, "should_log", return_value=(True, None)
        ) as should_log:
            logger.warning("seen: %s", "base.html")

        should_log.assert_called_once_with("seen: base.html")


@pytest.mark.parametrize(
    ("template", "arguments"),
    [
        pytest.param("%d items", ("many",), id="wrong-type"),
        pytest.param("%s and %s", ("one",), id="too-few"),
        pytest.param("no placeholder", (1,), id="too-many"),
        pytest.param("value: %s", (Unprintable(),), id="unprintable-argument"),
        pytest.param("%(missing)s", ({"other": 1},), id="missing-key"),
    ],
)
def test_a_template_that_cannot_be_filled_in_stays_as_it_is(
    template: str, arguments: tuple[Any, ...]
) -> None:
    assert EnhancedLogger._render(template, arguments) == template


def test_a_template_without_arguments_is_not_touched() -> None:
    assert EnhancedLogger._render("50%% off", ()) == "50%% off"
