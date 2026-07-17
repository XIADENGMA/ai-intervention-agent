from __future__ import annotations

import inspect
from collections.abc import Iterable, Iterator
from typing import Any

from ai_intervention_agent import enhanced_logging


def _populate_ring(size: int = 200) -> None:
    enhanced_logging.clear_recent_logs()
    with enhanced_logging._log_ring_lock:
        for index in range(size):
            enhanced_logging._log_ring.append(
                {
                    "ts_unix": index,
                    "level_no": 40,
                    "level_name": "ERROR",
                    "logger_name": "test",
                    "message": f"msg-{index}",
                }
            )


def test_recent_logs_small_tail_uses_islice_without_full_snapshot(
    monkeypatch: Any,
) -> None:
    _populate_ring()
    islice_calls: list[tuple[int, int | None]] = []
    original_islice = enhanced_logging.itertools.islice

    def counting_islice(
        iterable: Iterable[dict[str, Any]],
        start: int,
        stop: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        islice_calls.append((start, stop))
        return original_islice(iterable, start, stop)

    monkeypatch.setattr(enhanced_logging.itertools, "islice", counting_islice)

    entries = enhanced_logging.get_recent_logs(limit=50)

    assert [entry["message"] for entry in entries[:2]] == ["msg-150", "msg-151"]
    assert entries[-1]["message"] == "msg-199"
    assert len(entries) == 50
    assert islice_calls == [(150, 200)]


def test_recent_logs_large_tail_keeps_full_snapshot_path(monkeypatch: Any) -> None:
    _populate_ring()
    islice_calls = 0
    original_islice = enhanced_logging.itertools.islice

    def counting_islice(
        iterable: Iterable[dict[str, Any]],
        start: int,
        stop: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        nonlocal islice_calls
        islice_calls += 1
        return original_islice(iterable, start, stop)

    monkeypatch.setattr(enhanced_logging.itertools, "islice", counting_islice)

    entries = enhanced_logging.get_recent_logs(limit=100)

    assert [entry["message"] for entry in entries[:2]] == ["msg-100", "msg-101"]
    assert entries[-1]["message"] == "msg-199"
    assert len(entries) == 100
    assert islice_calls == 0


def test_recent_logs_islice_threshold_is_source_visible() -> None:
    source = inspect.getsource(enhanced_logging.get_recent_logs)

    assert "itertools.islice(_log_ring, ring_len - limit, ring_len)" in source
    assert (
        "limit in (_LOG_RING_SERVER_INFO_LIMIT, _LOG_RING_ENDPOINT_DEFAULT_LIMIT)"
        in source
    )
