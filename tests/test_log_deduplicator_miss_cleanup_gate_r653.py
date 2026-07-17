"""R653 - LogDeduplicator gates miss-path cleanup scans."""

from __future__ import annotations

import inspect
import time
from unittest.mock import patch

from ai_intervention_agent.enhanced_logging import LogDeduplicator


def test_miss_path_cleanup_is_gated_by_expiry_or_size_cap() -> None:
    source = inspect.getsource(LogDeduplicator.should_log)

    assert "len(self.cache) > self.max_cache_size" in source
    assert "current_time - self._last_cleanup_time >= self.time_window" in source


def test_fresh_unique_misses_do_not_scan_cache_after_startup_cleanup() -> None:
    dedup = LogDeduplicator(time_window=60.0, max_cache_size=10_000)

    with patch.object(dedup, "_cleanup_cache", wraps=dedup._cleanup_cache) as spy:
        dedup.should_log("first_unique")
        dedup.should_log("second_unique")
        dedup.should_log("third_unique")

    assert spy.call_count == 1
    assert len(dedup.cache) == 3


def test_expired_entries_still_clean_on_miss_after_time_window() -> None:
    dedup = LogDeduplicator(time_window=0.01, max_cache_size=100)
    dedup.should_log("old_msg")

    time.sleep(0.02)

    with patch.object(dedup, "_cleanup_cache", wraps=dedup._cleanup_cache) as spy:
        dedup.should_log("new_msg")

    assert spy.call_count == 1
    assert hash("old_msg") not in dedup.cache
    assert hash("new_msg") in dedup.cache


def test_size_cap_still_triggers_cleanup_on_miss() -> None:
    dedup = LogDeduplicator(time_window=60.0, max_cache_size=5)
    for index in range(5):
        dedup.should_log(f"seed_{index}")

    with patch.object(dedup, "_cleanup_cache", wraps=dedup._cleanup_cache) as spy:
        dedup.should_log("overflow_entry")

    assert spy.call_count == 1
    assert len(dedup.cache) <= dedup.max_cache_size
