"""R914: a request that one limit refuses is not let through by another limit.

Every route that carries no limit of its own falls under the default limits of
the Web UI, ``60 per minute`` and ``10 per second`` (``GET /``, ``/api/health``,
``/api/capabilities``, ``/api/get-notification-config``, ``/api/time``,
``/api/close``, ``/api/update``, ``/api/test-bark`` ...). A request has to pass
*both*. The limiter counted both correctly, but then picked the decision to act
on as "the one with the fewest calls left, the earlier reset on a tie", and
never looked at whether that decision was a refusal.

The case that went wrong: the minute is used up (count 61 of 60, remaining 0,
refused) and the request is the 10th of its second (count 10 of 10, remaining
0, passes). Both have ``remaining == 0``, the second resets first, so the
second's *pass* was the decision and the request went through. A client that
paces itself at the per-second limit, 10 requests every second, got 113
requests through a ``60 per minute`` limit in one minute.

Before / after, for a client sending 10 requests per second for a minute:

==============================================  ================  ===============
what                                            before            after
==============================================  ================  ===============
requests let through in that minute             113               60
the 10th request of a second, minute spent      200               429
``Retry-After`` of a request both refuse        1 (the second)    the minute's
==============================================  ================  ===============

Which decision is reported is now ``_is_more_limiting``: a refusal outranks a
pass; of two refusals the one that lifts later; of two passes the one with
fewer calls left, the earlier reset on a tie (unchanged).

Layout: A, B, C, D, E are the cases by hand (what a client sees, in both orders
of the two limits), F is a route with a limit of its own (unchanged), G is a
wall clock that steps back (unchanged), and H states the rule from the other
side with a model that keeps the times of the hits and counts, for each limit,
how many fall in the window of the request.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask

from ai_intervention_agent import web_ui_rate_limiter as rate_limiter
from ai_intervention_agent.web_ui_rate_limiter import WebUiRateLimiter

PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600}
START = 1_000_000_020  # a minute boundary: divisible by 60

MINUTE_FIRST = ["60 per minute", "10 per second"]
SECOND_FIRST = ["10 per second", "60 per minute"]
BOTH_ORDERS = pytest.mark.parametrize(
    "limits", [MINUTE_FIRST, SECOND_FIRST], ids=["minute first", "second first"]
)


class Clock:
    """The time the limiter sees; the tests move it by hand."""

    def __init__(self) -> None:
        self.now = float(START)

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    # Only the limiter's own name for the module: ``time.time`` stays real for Flask.
    monkeypatch.setattr(rate_limiter, "time", SimpleNamespace(time=clock))
    return clock


def build(default_limits: list[str]) -> Any:
    app = Flask(__name__)
    app.config["TESTING"] = True
    limiter = WebUiRateLimiter(app, default_limits=default_limits)

    @app.route("/x")
    def x() -> str:
        return "ok"

    @app.route("/y")
    def y() -> str:
        return "ok"

    @app.route("/own")
    @limiter.limit("3 per minute")
    def own() -> str:
        return "ok"

    return app.test_client()


def hit(client: Any, path: str = "/x", ip: str = "127.0.0.1") -> Any:
    return client.get(path, environ_base={"REMOTE_ADDR": ip})


def use_up_the_minute(client: Any, clock: Clock) -> None:
    """60 requests, 10 in each of the first 6 seconds: all pass, the minute is spent."""
    for second in range(6):
        clock.now = START + second + 0.25
        assert [hit(client).status_code for _ in range(10)] == [200] * 10


# ──────────────────────────────────────────────────────────────────────────
# A. The per-minute limit holds for a client that paces itself at the other
# ──────────────────────────────────────────────────────────────────────────


@BOTH_ORDERS
def test_pacing_the_per_second_limit_gets_exactly_the_per_minute_limit(
    clock: Clock, limits: list[str]
) -> None:
    client = build(limits)
    statuses: list[int] = []
    for second in range(60):
        clock.now = START + second + 0.25
        statuses.extend(hit(client).status_code for _ in range(10))

    assert statuses.count(200) == 60  # was 113
    assert statuses[:60] == [200] * 60
    assert set(statuses[60:]) == {429}


@BOTH_ORDERS
def test_a_burst_over_the_per_second_limit_does_not_buy_extra_calls_later(
    clock: Clock, limits: list[str]
) -> None:
    client = build(limits)
    allowed = 0
    for second in range(10):
        clock.now = START + second + 0.25
        allowed += sum(hit(client).status_code == 200 for _ in range(12))

    # 12 calls a second, 2 of them refused by the per-second limit but all of
    # them counted: the minute is spent after 5 seconds, 50 calls passed
    assert allowed == 50  # was 55


@BOTH_ORDERS
def test_the_next_minute_starts_clean(clock: Clock, limits: list[str]) -> None:
    client = build(limits)
    use_up_the_minute(client, clock)
    clock.now = START + 6.25
    assert hit(client).status_code == 429

    clock.now = START + 60.25
    assert hit(client).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# B. What a refusal that used to be a pass says
# ──────────────────────────────────────────────────────────────────────────


@BOTH_ORDERS
def test_the_tenth_request_of_a_second_is_refused_when_the_minute_is_spent(
    clock: Clock, limits: list[str]
) -> None:
    client = build(limits)
    use_up_the_minute(client, clock)

    clock.now = START + 6.25
    answers = [hit(client) for _ in range(10)]

    assert [answer.status_code for answer in answers] == [429] * 10
    tenth = answers[-1]  # count 10 of 10 in its second: this one used to go through
    assert tenth.headers["X-RateLimit-Limit"] == "60"
    assert tenth.headers["X-RateLimit-Remaining"] == "0"
    assert tenth.headers["X-RateLimit-Reset"] == str(START + 60)
    assert tenth.headers["Retry-After"] == str(math.ceil(START + 60 - clock.now))
    assert tenth.get_json() == {"error": "rate_limit_exceeded"}


# ──────────────────────────────────────────────────────────────────────────
# C. Two refusals: the one that lifts later is reported
# ──────────────────────────────────────────────────────────────────────────


@BOTH_ORDERS
def test_two_refusals_report_the_one_that_lifts_later(
    clock: Clock, limits: list[str]
) -> None:
    client = build(limits)
    use_up_the_minute(client, clock)

    clock.now = START + 6.25
    answers = [hit(client) for _ in range(11)]
    eleventh = answers[-1]  # past 10 in its second and past 60 in its minute

    assert eleventh.status_code == 429
    assert eleventh.headers["X-RateLimit-Limit"] == "60"  # was 10
    assert eleventh.headers["X-RateLimit-Reset"] == str(START + 60)
    assert eleventh.headers["Retry-After"] == "54"  # was 1


@BOTH_ORDERS
def test_a_refusal_by_the_second_alone_still_reports_the_second(
    clock: Clock, limits: list[str]
) -> None:
    client = build(limits)
    clock.now = START + 0.25
    answers = [hit(client) for _ in range(11)]

    assert [answer.status_code for answer in answers] == [200] * 10 + [429]
    refused = answers[-1]
    assert refused.headers["X-RateLimit-Limit"] == "10"
    assert refused.headers["X-RateLimit-Remaining"] == "0"
    assert refused.headers["X-RateLimit-Reset"] == str(START + 1)
    assert refused.headers["Retry-After"] == "1"


# ──────────────────────────────────────────────────────────────────────────
# D. Two passes: fewer calls left, the earlier reset on a tie (unchanged)
# ──────────────────────────────────────────────────────────────────────────


@BOTH_ORDERS
def test_two_passes_report_the_one_with_fewer_calls_left(
    clock: Clock, limits: list[str]
) -> None:
    client = build(limits)
    clock.now = START + 0.25
    answer = hit(client)

    assert answer.status_code == 200
    assert answer.headers["X-RateLimit-Limit"] == "10"
    assert answer.headers["X-RateLimit-Remaining"] == "9"
    assert answer.headers["X-RateLimit-Reset"] == str(START + 1)


@pytest.mark.parametrize(
    "limits",
    [["5 per minute", "5 per second"], ["5 per second", "5 per minute"]],
    ids=["minute first", "second first"],
)
def test_on_a_tie_of_calls_left_the_limit_that_resets_first_is_reported(
    clock: Clock, limits: list[str]
) -> None:
    client = build(limits)
    clock.now = START + 0.25
    answer = hit(client)

    assert answer.headers["X-RateLimit-Remaining"] == "4"
    assert answer.headers["X-RateLimit-Reset"] == str(START + 1)


# ──────────────────────────────────────────────────────────────────────────
# E. The rule on its own
# ──────────────────────────────────────────────────────────────────────────


def decision(*, allowed: bool, remaining: int, reset_at: int) -> Any:
    return rate_limiter._LimitDecision(
        allowed=allowed,
        limit=10,
        remaining=remaining,
        reset_at=reset_at,
        retry_after=1,
    )


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        # a refusal outranks a pass, whatever the numbers say
        ((False, 0, 160), (True, 0, 101), True),
        ((False, 0, 100), (True, 0, 160), True),
        ((False, 0, 160), (True, 9, 101), True),
        ((True, 0, 101), (False, 0, 160), False),
        ((True, 0, 160), (False, 0, 100), False),
        ((True, 0, 101), (False, 0, 100), False),
        # two refusals: the one that lifts later
        ((False, 0, 160), (False, 0, 101), True),
        ((False, 0, 101), (False, 0, 160), False),
        ((False, 0, 101), (False, 0, 101), False),
        # two passes: fewer calls left, then the earlier reset
        ((True, 3, 160), (True, 9, 101), True),
        ((True, 9, 101), (True, 3, 160), False),
        ((True, 3, 101), (True, 3, 160), True),
        ((True, 3, 160), (True, 3, 101), False),
        ((True, 3, 101), (True, 3, 101), False),
    ],
)
def test_which_decision_is_reported(
    candidate: tuple[bool, int, int],
    current: tuple[bool, int, int],
    expected: bool,
) -> None:
    def make(values: tuple[bool, int, int]) -> Any:
        allowed, remaining, reset_at = values
        return decision(allowed=allowed, remaining=remaining, reset_at=reset_at)

    assert rate_limiter._is_more_limiting(make(candidate), make(current)) is expected


# ──────────────────────────────────────────────────────────────────────────
# F. A route with a limit of its own: one limit, nothing to choose between
# ──────────────────────────────────────────────────────────────────────────


def test_a_route_with_its_own_limit_is_unchanged(clock: Clock) -> None:
    client = build(MINUTE_FIRST)
    clock.now = START + 0.25

    answers = [hit(client, "/own") for _ in range(4)]

    assert [answer.status_code for answer in answers] == [200, 200, 200, 429]
    assert [answer.headers["X-RateLimit-Remaining"] for answer in answers] == [
        "2",
        "1",
        "0",
        "0",
    ]
    assert answers[-1].headers["X-RateLimit-Limit"] == "3"
    assert answers[-1].headers["Retry-After"] == "60"  # 59.75 s left, rounded up


def test_each_route_and_each_address_has_its_own_count(clock: Clock) -> None:
    client = build(SECOND_FIRST)
    clock.now = START + 0.25
    assert [hit(client, "/x").status_code for _ in range(11)] == [200] * 10 + [429]

    assert hit(client, "/y").status_code == 200  # another route
    assert hit(client, "/x", ip="192.168.1.5").status_code == 200  # another address
    assert hit(client, "/x").status_code == 429  # the same one is still refused


# ──────────────────────────────────────────────────────────────────────────
# G. A wall clock that steps back (NTP): a fresh count, not a refusal for a
# window that lies in the future
# ──────────────────────────────────────────────────────────────────────────


def test_a_clock_that_steps_back_starts_a_fresh_count(clock: Clock) -> None:
    client = build(["2 per second"])
    clock.now = START + 10.25
    assert [hit(client).status_code for _ in range(3)] == [200, 200, 429]

    clock.now = START + 3.25  # the clock stepped back to an earlier window
    assert [hit(client).status_code for _ in range(3)] == [200, 200, 429]


# ──────────────────────────────────────────────────────────────────────────
# H. A model: the times of the hits, counted per limit and window
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Spec:
    amount: int
    unit: str

    @property
    def raw(self) -> str:
        return f"{self.amount} per {self.unit}"

    @property
    def seconds(self) -> int:
        return PERIOD_SECONDS[self.unit]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    limit: int
    remaining: int
    reset: int


@dataclass(frozen=True)
class Expected:
    status: int
    remaining: int
    reset: int
    retry_after: int | None
    limits: frozenset[int]
    masked: bool  # a pass with nothing left that resets before a refusal


class Model:
    """Keeps the time of every hit (refused ones too) per route and address."""

    def __init__(self, specs: list[Spec]) -> None:
        self.specs = specs
        self.hits: dict[tuple[str, str], list[float]] = {}

    def hit(self, route: str, address: str, now: float) -> Expected:
        times = self.hits.setdefault((route, address), [])
        times.append(now)
        verdicts = []
        for spec in self.specs:
            window = math.floor(now / spec.seconds)
            count = sum(1 for t in times if math.floor(t / spec.seconds) == window)
            verdicts.append(
                Verdict(
                    allowed=count <= spec.amount,
                    limit=spec.amount,
                    remaining=max(spec.amount - count, 0),
                    reset=(window + 1) * spec.seconds,
                )
            )

        refused = [v for v in verdicts if not v.allowed]
        if refused:
            reset = max(v.reset for v in refused)
            return Expected(
                status=429,
                remaining=0,
                reset=reset,
                retry_after=max(1, math.ceil(reset - now)),
                limits=frozenset(v.limit for v in refused if v.reset == reset),
                masked=any(
                    v.allowed and v.remaining == 0 and v.reset < reset for v in verdicts
                ),
            )

        remaining = min(v.remaining for v in verdicts)
        reset = min(v.reset for v in verdicts if v.remaining == remaining)
        return Expected(
            status=200,
            remaining=remaining,
            reset=reset,
            retry_after=None,
            limits=frozenset(
                v.limit
                for v in verdicts
                if v.remaining == remaining and v.reset == reset
            ),
            masked=False,
        )


POOL = [Spec(amount, unit) for amount in range(1, 7) for unit in PERIOD_SECONDS]
STEPS = [0, 0, 0, 0.25, 0.25, 0.5, 0.75, 1, 1, 2, 5, 30, 60, 61, 300, 3600, 5000]
SEEDS = range(40)
STEPS_PER_SEED = 300


def test_the_limiter_agrees_with_a_model_on_random_traffic(clock: Clock) -> None:
    masked = 0
    refused = 0
    for seed in SEEDS:
        rng = random.Random(914_000 + seed)
        specs = rng.sample(POOL, rng.randint(1, 3))
        model = Model(specs)
        client = build([spec.raw for spec in specs])
        clock.now = START + 0.0
        for step in range(STEPS_PER_SEED):
            clock.now += rng.choice(STEPS)
            route = rng.choice(["/x", "/y"])
            address = rng.choice(["127.0.0.1", "192.168.1.5"])
            where = f"seed {seed} step {step} specs {[s.raw for s in specs]}"

            expected = model.hit(route, address, clock.now)
            answer = hit(client, route, address)

            assert answer.status_code == expected.status, where
            assert int(answer.headers["X-RateLimit-Remaining"]) == expected.remaining, (
                where
            )
            assert int(answer.headers["X-RateLimit-Reset"]) == expected.reset, where
            assert int(answer.headers["X-RateLimit-Limit"]) in expected.limits, where
            if expected.status == 429:
                assert int(answer.headers["Retry-After"]) == expected.retry_after, where
                refused += 1
            else:
                assert "Retry-After" not in answer.headers, where
            masked += expected.masked

    # the traffic reaches the case that went wrong (544 times as written), and
    # refusals in general (2,296 of 12,000)
    assert masked >= 300, masked
    assert refused >= 2000, refused
