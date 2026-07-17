from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import ai_intervention_agent.server as server


def _sse_ok_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "success": True,
        "emit_total": 100,
        "latest_event_id": 50,
        "gap_warnings_emitted": 0,
        "backpressure_discards": 0,
        "subscriber_count": 1,
        "history_size": 50,
    }
    return resp


def _recent_logs_ok_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "success": True,
        "entries": [{"message": "r666"}],
    }
    return resp


def test_sse_stats_cache_hit_uses_dict_copy_method() -> None:
    source = inspect.getsource(server._fetch_sse_stats_cached)

    assert "cached_copy = _sse_stats_cache.copy()" in source
    assert "cached_copy = dict(_sse_stats_cache)" not in source


def test_recent_logs_cache_hit_uses_dict_copy_method() -> None:
    source = inspect.getsource(server._fetch_recent_logs_cached)

    assert "cached_copy = _recent_logs_cache.copy()" in source
    assert "cached_copy = dict(_recent_logs_cache)" not in source


def test_sse_stats_cache_hit_copy_remains_isolated() -> None:
    server.reset_sse_stats_cache_for_testing()

    with patch("httpx.get", return_value=_sse_ok_response()) as fake_get:
        first = server._fetch_sse_stats_cached("127.0.0.1", 41111)
        second = server._fetch_sse_stats_cached("127.0.0.1", 41111)
        second["emit_total"] = "polluted"
        third = server._fetch_sse_stats_cached("127.0.0.1", 41111)

    assert fake_get.call_count == 1
    assert first["emit_total"] == 100
    assert third["emit_total"] == 100
    assert third["cached"] is True


def test_recent_logs_cache_hit_copy_remains_isolated() -> None:
    server.reset_recent_logs_cache_for_testing()

    with patch("httpx.get", return_value=_recent_logs_ok_response()) as fake_get:
        first = server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=20)
        second = server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=20)
        second["entries"] = "polluted"
        third = server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=20)

    assert fake_get.call_count == 1
    assert first["count"] == 1
    assert isinstance(third["entries"], list)
    assert third["cached"] is True
