"""R668 - build-info cache snapshots use dict.copy().

R904 moved the cache from ``server`` to ``process_meta`` (the Web UI process reads it
without importing the MCP stack); the checks are the same, aimed at the new home.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

from ai_intervention_agent import process_meta


def setup_function() -> None:
    process_meta.reset_build_info_cache_for_testing()


def teardown_function() -> None:
    process_meta.reset_build_info_cache_for_testing()


def test_resolve_build_info_uses_copy_method_for_cached_snapshots() -> None:
    source = inspect.getsource(process_meta.resolve_build_info)

    assert "return _BUILD_INFO_CACHE.copy()" in source
    assert "return cache.copy()" in source
    assert "return dict(_BUILD_INFO_CACHE)" not in source
    assert "return dict(cache)" not in source


def test_build_info_cache_hit_copy_remains_isolated() -> None:
    with process_meta._BUILD_INFO_CACHE_LOCK:
        process_meta._BUILD_INFO_CACHE = {
            "git_commit": "abc1234",
            "git_branch": "main",
            "git_dirty": "no",
        }

    snapshot = process_meta.resolve_build_info()
    snapshot["git_commit"] = "polluted"

    fresh_snapshot = process_meta.resolve_build_info()
    assert fresh_snapshot["git_commit"] == "abc1234"


def test_build_info_initial_result_copy_remains_isolated() -> None:
    values = iter([b"abc1234\n", b"main\n", b""])

    with patch(
        "subprocess.check_output", side_effect=lambda *args, **kwargs: next(values)
    ):
        snapshot = process_meta.resolve_build_info()

    snapshot["git_branch"] = "polluted"

    fresh_snapshot = process_meta.resolve_build_info()
    assert fresh_snapshot == {
        "git_commit": "abc1234",
        "git_branch": "main",
        "git_dirty": "no",
    }
