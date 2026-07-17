from __future__ import annotations

import inspect

from ai_intervention_agent import web_ui_rate_limiter as rate_limiter


def test_prune_reuses_cached_period_seconds(monkeypatch) -> None:
    original_parse_limit = rate_limiter._parse_limit
    parse_calls: list[str] = []

    def counting_parse_limit(raw: str) -> rate_limiter._LimitSpec:
        parse_calls.append(raw)
        return original_parse_limit(raw)

    rate_limiter._limit_period_seconds.cache_clear()
    monkeypatch.setattr(rate_limiter, "_parse_limit", counting_parse_limit)

    buckets = {
        (f"route-{index}", f"client-{index}", "1 per second"): (1, 1)
        for index in range(40)
    }
    buckets.update(
        {
            (f"route-{index}", f"client-{index}", "1 per hour"): (3600, 1)
            for index in range(40)
        }
    )

    expired = [
        bucket_key
        for bucket_key, (window_start, _count) in buckets.items()
        if window_start + rate_limiter._limit_period_seconds(bucket_key[2]) <= 4000
    ]
    assert len(expired) == 40
    assert parse_calls == ["1 per second", "1 per hour"]

    expired_again = [
        bucket_key
        for bucket_key, (window_start, _count) in buckets.items()
        if window_start + rate_limiter._limit_period_seconds(bucket_key[2]) <= 4000
    ]
    assert expired_again == expired
    assert parse_calls == ["1 per second", "1 per hour"]
    assert rate_limiter._limit_period_seconds.cache_info().maxsize == 32
    rate_limiter._limit_period_seconds.cache_clear()


def test_prune_uses_cached_period_helper_without_changing_bucket_shape() -> None:
    source = inspect.getsource(rate_limiter.WebUiRateLimiter._prune_expired_buckets)

    assert "_limit_period_seconds(bucket_key[2])" in source
    assert "_parse_limit(bucket_key[2])" not in source
    assert "for bucket_key, (window_start, _count)" in source
