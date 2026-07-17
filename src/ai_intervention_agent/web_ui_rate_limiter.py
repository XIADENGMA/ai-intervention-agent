"""Lightweight in-memory rate limiter for the local Web UI.

This module intentionally covers the small Flask-Limiter surface used by the
Web UI (``limit`` / ``exempt`` / ``enabled``) without importing
``flask_limiter`` during ``WebFeedbackUI`` construction.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from functools import lru_cache, wraps
from types import MappingProxyType
from typing import Any, Protocol, cast

from flask import Response, g, jsonify, request
from flask.typing import ResponseReturnValue

logger = logging.getLogger(__name__)

_LIMIT_SECONDS: Mapping[str, int] = MappingProxyType(
    {
        "second": 1,
        "minute": 60,
        "hour": 3600,
    }
)


_DecoratedCallable = Callable[..., Any]


class WebUiLimiterProtocol(Protocol):
    """Small limiter surface used by Web UI route mixins."""

    enabled: bool

    def limit(
        self, limit_value: str
    ) -> Callable[[_DecoratedCallable], _DecoratedCallable]: ...

    def exempt(self, func: _DecoratedCallable) -> _DecoratedCallable: ...


class _LimitSpec:
    __slots__ = ("amount", "period_seconds", "raw")

    def __init__(self, amount: int, period_seconds: int, raw: str) -> None:
        self.amount = amount
        self.period_seconds = period_seconds
        self.raw = raw


class _LimitDecision:
    __slots__ = ("allowed", "limit", "remaining", "reset_at", "retry_after")

    def __init__(
        self,
        *,
        allowed: bool,
        limit: int,
        remaining: int,
        reset_at: int,
        retry_after: int,
    ) -> None:
        self.allowed = allowed
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at
        self.retry_after = retry_after


def _parse_limit(raw: str) -> _LimitSpec:
    parts = raw.strip().lower().split()
    if len(parts) != 3 or parts[1] != "per":
        raise ValueError(f"unsupported rate limit expression: {raw!r}")
    amount = int(parts[0])
    period = parts[2].rstrip("s")
    period_seconds = _LIMIT_SECONDS[period]
    if amount <= 0:
        raise ValueError(f"rate limit amount must be positive: {raw!r}")
    return _LimitSpec(amount, period_seconds, raw)


@lru_cache(maxsize=32)
def _limit_period_seconds(raw: str) -> int:
    return _parse_limit(raw).period_seconds


class WebUiRateLimiter:
    """Small fixed-window limiter compatible with the Web UI's decorator use."""

    def __init__(
        self,
        app: Any,
        *,
        default_limits: list[str] | None = None,
        headers_enabled: bool = True,
    ) -> None:
        self.enabled = True
        self.headers_enabled = headers_enabled
        self._default_limits = [_parse_limit(item) for item in (default_limits or [])]
        self._buckets: dict[tuple[str, str, str], tuple[int, int]] = {}
        self._lock = threading.Lock()

        @app.before_request
        def _aiia_apply_default_rate_limits() -> ResponseReturnValue | None:
            view_func = app.view_functions.get(request.endpoint or "")
            if view_func is None or getattr(
                view_func, "_aiia_rate_limit_exempt", False
            ):
                return None
            if getattr(view_func, "_aiia_rate_limit_specs", None):
                return None
            return self._check_limits(
                self._default_limits, scope=request.endpoint or "default"
            )

        @app.after_request
        def _aiia_add_rate_limit_headers(response: Response) -> Response:
            decision = getattr(g, "_aiia_rate_limit_decision", None)
            if self.headers_enabled and decision is not None:
                response.headers["X-RateLimit-Limit"] = str(decision.limit)
                response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
                response.headers["X-RateLimit-Reset"] = str(decision.reset_at)
                if response.status_code == 429:
                    response.headers["Retry-After"] = str(decision.retry_after)
            return response

    def limit(
        self, limit_value: str
    ) -> Callable[[_DecoratedCallable], _DecoratedCallable]:
        specs = [_parse_limit(limit_value)]

        def decorator(func: _DecoratedCallable) -> _DecoratedCallable:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                scope = request.endpoint or getattr(func, "__name__", "anonymous")
                limited = self._check_limits(specs, scope=scope)
                if limited is not None:
                    return limited
                return func(*args, **kwargs)

            cast(Any, wrapper)._aiia_rate_limit_specs = specs
            return wrapper

        return decorator

    def exempt(self, func: _DecoratedCallable) -> _DecoratedCallable:
        cast(Any, func)._aiia_rate_limit_exempt = True
        return func

    def _client_key(self) -> str:
        remote_addr = request.remote_addr or ""
        try:
            from ai_intervention_agent.web_ui_security import SecurityMixin

            if SecurityMixin._should_trust_forwarded_for(remote_addr):
                forwarded_for = request.headers.get("X-Forwarded-For", "")
                forwarded_ip = SecurityMixin._parse_forwarded_for(forwarded_for)
                if forwarded_ip:
                    return forwarded_ip
        except Exception:
            logger.debug(
                "Unable to evaluate trusted X-Forwarded-For client key; "
                "falling back to request.remote_addr",
                exc_info=True,
            )
        return remote_addr or "unknown"

    def _check_limits(
        self, specs: list[_LimitSpec], *, scope: str
    ) -> ResponseReturnValue | None:
        if not self.enabled or not specs:
            return None

        now = time.time()
        client_key = self._client_key()
        decision: _LimitDecision | None = None

        with self._lock:
            self._prune_expired_buckets(now)
            for spec in specs:
                window_start = int(now // spec.period_seconds) * spec.period_seconds
                reset_at = window_start + spec.period_seconds
                bucket_key = (scope, client_key, spec.raw)
                stored_window, count = self._buckets.get(bucket_key, (window_start, 0))
                if stored_window != window_start:
                    stored_window = window_start
                    count = 0
                count += 1
                self._buckets[bucket_key] = (stored_window, count)
                remaining = max(spec.amount - count, 0)
                current_decision = _LimitDecision(
                    allowed=count <= spec.amount,
                    limit=spec.amount,
                    remaining=remaining,
                    reset_at=reset_at,
                    retry_after=max(1, math.ceil(reset_at - now)),
                )
                if decision is None or (
                    current_decision.remaining,
                    current_decision.reset_at,
                ) < (
                    decision.remaining,
                    decision.reset_at,
                ):
                    decision = current_decision

        if decision is None:
            return None
        g._aiia_rate_limit_decision = decision
        if decision.allowed:
            return None

        return jsonify({"error": "rate_limit_exceeded"}), 429

    def _prune_expired_buckets(self, now: float) -> None:
        """Drop windows that cannot receive another hit."""
        expired = [
            bucket_key
            for bucket_key, (window_start, _count) in self._buckets.items()
            if window_start + _limit_period_seconds(bucket_key[2]) <= now
        ]
        for bucket_key in expired:
            del self._buckets[bucket_key]
