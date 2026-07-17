"""R655 - recent logs cache keeps its key outside the cached payload."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import ai_intervention_agent.server as server


def _reset_cache() -> None:
    server.reset_recent_logs_cache_for_testing()


def _ok_response(entries: list[dict[str, object]] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "success": True,
        "entries": entries if entries is not None else [{"message": "r655"}],
    }
    return resp


def test_recent_logs_cache_hit_uses_sidecar_key_and_plain_copy() -> None:
    source = inspect.getsource(server._fetch_recent_logs_cached)

    assert "_recent_logs_cache_key == cache_key" in source
    assert "cached_copy = _recent_logs_cache.copy()" in source
    assert 'if k != "_key"' not in source
    assert '_recent_logs_cache["_key"]' not in source


def test_recent_logs_cache_payload_does_not_store_internal_key() -> None:
    _reset_cache()

    with patch("httpx.get", return_value=_ok_response()) as fake_get:
        first = server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=20)
        second = server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=20)

    assert fake_get.call_count == 1
    assert first["count"] == 1
    assert second["cached"] is True
    with server._recent_logs_cache_lock:
        assert "_key" not in server._recent_logs_cache
        assert server._recent_logs_cache_key == "limit=20"


def test_recent_logs_sidecar_key_keeps_different_limits_isolated() -> None:
    _reset_cache()

    with patch("httpx.get", return_value=_ok_response(entries=[])) as fake_get:
        server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=20)
        server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=50)

    assert fake_get.call_count == 2
    with server._recent_logs_cache_lock:
        assert server._recent_logs_cache_key == "limit=50"
        assert "_key" not in server._recent_logs_cache


def test_recent_logs_cache_reset_clears_sidecar_key() -> None:
    _reset_cache()

    with patch("httpx.get", return_value=_ok_response()):
        server._fetch_recent_logs_cached("127.0.0.1", 41111, limit=20)

    with server._recent_logs_cache_lock:
        assert server._recent_logs_cache_key == "limit=20"

    server.reset_recent_logs_cache_for_testing()

    with server._recent_logs_cache_lock:
        assert server._recent_logs_cache == {}
        assert server._recent_logs_cache_key == ""
        assert server._recent_logs_cache_ts == 0.0
