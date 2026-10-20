"""R765: a log call whose arguments do not fit its message does not raise into the caller.

``InterceptHandler`` is the bridge from the stdlib ``logging`` to loguru.  It sits on
the root logger for every third-party library and on each ``EnhancedLogger``.  It asked
the record for its text with ``record.getMessage()`` and nothing around it, so a call
like ``logging.warning("%d items", "many")`` raised ``TypeError`` out of the logging call
and into the code that made it.  A stdlib handler does not do that: ``StreamHandler``
catches the error, prints a report and returns.

The bridge now writes the message as the call gave it, with a note naming the error, and
leaves the arguments out: the stdlib report prints them as they are, outside the
sanitising sink, so a secret passed to a broken call would reach stderr unmasked.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from loguru import logger as loguru_logger

from ai_intervention_agent.enhanced_logging import InterceptHandler

ARGUMENT = "r765-argument-text-nothing-would-mask"


class Unprintable:
    def __str__(self) -> str:
        raise RuntimeError("no text for this object")


@contextmanager
def loguru_lines() -> Iterator[list[str]]:
    lines: list[str] = []
    sink_id = loguru_logger.add(
        lambda text: lines.append(str(text)), format="{message}", level="DEBUG"
    )
    try:
        yield lines
    finally:
        loguru_logger.remove(sink_id)


def record(msg: Any, *args: Any) -> logging.LogRecord:
    return logging.LogRecord("r765", logging.WARNING, __file__, 1, msg, args, None)


def test_a_fitting_message_is_written_as_before() -> None:
    with loguru_lines() as lines:
        InterceptHandler().emit(record("%d items in %s", 3, "queue"))

    assert [line.strip() for line in lines] == ["3 items in queue"]


@pytest.mark.parametrize(
    ("msg", "arguments", "error"),
    [
        pytest.param("%d items", ("many",), "TypeError", id="wrong-type"),
        pytest.param("%s and %s", ("one",), "TypeError", id="too-few"),
        pytest.param("no placeholder", (1,), "TypeError", id="too-many"),
        pytest.param("value: %s", (Unprintable(),), "RuntimeError", id="unprintable"),
    ],
)
def test_a_message_that_cannot_be_filled_in_is_written_with_a_note(
    msg: str, arguments: tuple[Any, ...], error: str
) -> None:
    with loguru_lines() as lines:
        InterceptHandler().emit(record(msg, *arguments))

    assert len(lines) == 1
    assert lines[0].startswith(msg)
    assert error in lines[0]


def test_the_arguments_are_not_written() -> None:
    with loguru_lines() as lines:
        InterceptHandler().emit(record("key=%d", ARGUMENT))

    assert len(lines) == 1
    assert ARGUMENT not in lines[0]


def test_a_message_object_that_cannot_be_printed_does_not_raise() -> None:
    with loguru_lines() as lines:
        InterceptHandler().emit(record(Unprintable()))

    assert len(lines) == 1
    assert "RuntimeError" in lines[0]


def test_the_call_returns_and_nothing_goes_to_stderr(
    capfd: pytest.CaptureFixture[str],
) -> None:
    logger = logging.getLogger("r765.bridge")
    logger.propagate = False
    logger.addHandler(InterceptHandler())
    try:
        with loguru_lines() as lines:
            logger.warning("key=%d", ARGUMENT)
    finally:
        logger.handlers.clear()

    assert len(lines) == 1
    assert ARGUMENT not in capfd.readouterr().err
