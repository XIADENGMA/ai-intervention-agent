from __future__ import annotations

import inspect
from typing import Any, cast

from flask import Flask, Response, g

from ai_intervention_agent import web_ui_rate_limiter as rate_limiter


def _new_limiter() -> tuple[Flask, rate_limiter.WebUiRateLimiter]:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app, rate_limiter.WebUiRateLimiter(app=app, default_limits=[])


def test_check_limits_tracks_selected_decision_without_list_materialization() -> None:
    source = inspect.getsource(rate_limiter.WebUiRateLimiter._check_limits)

    assert "decisions:" not in source
    assert ".append(" not in source
    assert "min(decisions" not in source
    assert "current_decision = _LimitDecision(" in source


def test_multiple_limits_still_select_most_constrained_decision(
    monkeypatch: Any,
) -> None:
    app, limiter = _new_limiter()
    specs = [
        rate_limiter._parse_limit("60 per minute"),
        rate_limiter._parse_limit("10 per second"),
    ]
    monkeypatch.setattr(rate_limiter.time, "time", lambda: 120.25)

    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert limiter._check_limits(specs, scope="default") is None

        decision = g._aiia_rate_limit_decision
        assert decision.allowed is True
        assert decision.limit == 10
        assert decision.remaining == 9
        assert decision.reset_at == 121


def test_streaming_decision_preserves_rate_limit_exceeded_response(
    monkeypatch: Any,
) -> None:
    app, limiter = _new_limiter()
    specs = [
        rate_limiter._parse_limit("60 per minute"),
        rate_limiter._parse_limit("10 per second"),
    ]
    monkeypatch.setattr(rate_limiter.time, "time", lambda: 120.25)

    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        limited = None
        for _index in range(11):
            limited = limiter._check_limits(specs, scope="default")

        assert limited is not None
        assert isinstance(limited, tuple)
        response, status_code = cast(tuple[Response, int], limited)
        assert status_code == 429
        assert response.get_json() == {"error": "rate_limit_exceeded"}

        decision = g._aiia_rate_limit_decision
        assert decision.allowed is False
        assert decision.limit == 10
        assert decision.remaining == 0
