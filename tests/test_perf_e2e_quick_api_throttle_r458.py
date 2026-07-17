"""R458 · quick API perf benchmarks should not sleep below the rate limit."""

from __future__ import annotations

import http.client
from typing import Any

import scripts.perf_e2e_bench as perf_bench


class _FakeConnection:
    def close(self) -> None:
        return None


def _install_api_round_trip_fakes(monkeypatch: Any) -> list[float]:
    sleeps: list[float] = []

    monkeypatch.setattr(perf_bench, "_free_port", lambda: 43210)
    monkeypatch.setattr(perf_bench, "_start_web_ui_subprocess", lambda port: object())
    monkeypatch.setattr(perf_bench, "_cleanup_subprocess", lambda proc: None)
    monkeypatch.setattr(
        http.client, "HTTPConnection", lambda *args, **kwargs: _FakeConnection()
    )
    monkeypatch.setattr(
        perf_bench.time, "sleep", lambda seconds: sleeps.append(seconds)
    )
    monkeypatch.setattr(
        perf_bench, "_http_get_keepalive", lambda conn, path: (200, b"{}")
    )

    return sleeps


def test_quick_api_iterations_are_below_throttle_budget() -> None:
    assert (
        perf_bench.QUICK_ITERATIONS["api_health_round_trip"]
        == perf_bench.QUICK_API_RATE_LIMIT_SAFE_ITERATIONS
    )
    assert (
        perf_bench.QUICK_ITERATIONS["api_config_round_trip"]
        == perf_bench.QUICK_API_RATE_LIMIT_SAFE_ITERATIONS
    )


def test_quick_sized_api_benchmark_does_not_sleep(monkeypatch: Any) -> None:
    sleeps = _install_api_round_trip_fakes(monkeypatch)

    samples = perf_bench.bench_api_round_trip(
        "/api/health",
        perf_bench.QUICK_API_RATE_LIMIT_SAFE_ITERATIONS,
    )

    assert len(samples) == perf_bench.QUICK_API_RATE_LIMIT_SAFE_ITERATIONS
    assert sleeps == []


def test_default_sized_api_benchmark_keeps_rate_limit_spacing(monkeypatch: Any) -> None:
    sleeps = _install_api_round_trip_fakes(monkeypatch)

    samples = perf_bench.bench_api_round_trip(
        "/api/health",
        perf_bench.DEFAULT_ITERATIONS["api_health_round_trip"],
    )

    assert len(samples) == perf_bench.DEFAULT_ITERATIONS["api_health_round_trip"]
    assert sleeps == [0.11] * (
        perf_bench.DEFAULT_ITERATIONS["api_health_round_trip"] - 1
    )
