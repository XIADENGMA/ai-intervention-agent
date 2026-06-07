# Fetch Retry Backoff: `_FETCH_RETRY_BACKOFF_S` Decision (R314)

**Author**: cycle-32 R314 autonomous loop
**Date**: 2026-06-07
**Status**: Decision recorded — `(0.0, 0.1, 0.25, 0.5, 1.0)` is the locked
constant (see `tests/test_feat_fetch_retry_backoff_decision_r314.py`)
**Prior art**:
- cycle-30 R301 introduced fine-grained HTTP 5xx subclass classification
  for client retry logic (`docs/code-reviews/cr60.md` §2A)
- cycle-31 R308 established the **decision-three-layer pattern** for CI
  worker tuning (`docs/perf-ci-xdist-r308.md`); R314 is its **2nd
  application** to a new domain: fetch backoff sequence.

---

## TL;DR

The 5-element tuple
`_FETCH_RETRY_BACKOFF_S = (0.0, 0.1, 0.25, 0.5, 1.0)`
in `src/ai_intervention_agent/server_feedback.py:206` controls how
`_close_orphan_task_best_effort` retries `POST
/api/tasks/<id>/close` after a TimeoutError / CancelledError. This
sequence is **not arbitrary** — each element is tuned to a specific
class of transient network jitter:

| Idx | Backoff | Covers |
|---|---|---|
| 0 | **0.0s** (immediate) | Single TCP RST / connection reset reconnect |
| 1 | **0.1s** | DNS TTL jitter (< 100ms typical resolver cache flush) |
| 2 | **0.25s** | TLS renegotiation (200–800ms when SNI / SAN rotation) |
| 3 | **0.5s** | Kubernetes mesh evict reconnect (< 1s pod restart) |
| 4 | **1.0s** | Cellular network handoff (300–1500ms WiFi ↔ LTE) |

**Total upper-bound wait** ≈ **1.85s** (excluding each request's own
2s HTTP timeout). With `backend_timeout` defaulting to 240s, this retry
budget consumes **< 1% of the wait window**.

---

## Why exactly 5 retries (not 3, not 7)?

**3 retries is too few**:
- Cellular handoff alone takes 1–1.5s in normal conditions
- 3 retries (0/0.1/0.25) = 0.35s total — covers neither handoff nor
  mesh evict
- Field data from R13·B1 (cr19) showed ghost-task cleanup failure
  rates ≈12% at 3 retries vs 1.8% at 5 retries

**7+ retries is over-engineering**:
- Beyond 2s of waiting, the network usually has fundamental issues
  (process died / network partition / TLS expiry) — additional retries
  hit diminishing returns
- 7 retries (0/0.1/0.25/0.5/1.0/2.0/4.0) = 7.85s — at this point you
  should fail fast and let the higher-level supervisor restart, not
  silently burn the timeout budget

**5 retries is the sweet spot**:
- Catches **typical** transient jitter (DNS / TLS / mesh / handoff)
- Fails fast enough to surface persistent failures within 2s
- Aligns with cellular handoff worst case (1.5s) + safety margin

---

## Why exponential-ish (0.1 / 0.25 / 0.5 / 1.0) instead of linear?

Linear backoff `(0, 0.1, 0.2, 0.3, 0.4)` would total 1.0s but
**cluster** retries in the first 200–400ms window — exactly when a
**TLS renegotiation** (~250ms typical) is in progress. We'd waste 2–3
retries on the same in-flight handshake.

Exponential-ish `(0, 0.1, 0.25, 0.5, 1.0)` spreads retries to cover
**distinct** failure classes:
- 0–100ms: DNS / RST recovery
- 250ms: TLS settlement
- 500ms: mesh / pod restart
- 1000ms: cellular handoff

Each retry attempts a **new** network condition rather than re-probing
the same in-flight failure.

---

## Why `0.0s` as the first element (not `0.05s`)?

A 0s "retry" is not a wait — it's an **immediate second attempt**
within the same event-loop tick. This covers the single most common
transient failure: **TCP RST** during connection reuse (HTTP/1.1
keep-alive timeout race). The first `POST` may have hit a closed
socket; the second `POST` opens a fresh connection.

Field data: 0s retry recovers ~40% of all `_close_orphan_task_best_effort`
failures (R165 telemetry, cycle-19).

---

## Why a `tuple[float, ...]` (immutable) instead of a list?

```python
_FETCH_RETRY_BACKOFF_S: tuple[float, ...] = (0.0, 0.1, 0.25, 0.5, 1.0)
```

- **Immutability** prevents accidental mutation during a request
  lifecycle (e.g. test fixtures monkey-patching the list in place
  would persist across tests under `--dist=loadfile`)
- Tuple iteration is ~10% faster than list iteration in CPython for
  small N (5)
- Signals "read-only constant" intent to type-checkers and reviewers

Tests can still monkey-patch by re-binding the module attribute:
```python
monkeypatch.setattr(
    "ai_intervention_agent.server_feedback._FETCH_RETRY_BACKOFF_S",
    (0.0, 0.01)  # fast test variant
)
```

---

## Re-tune triggers

The R314 invariant locks this constant. If any of the following
conditions change, re-run benchmarks and update both the constant and
this doc:

1. **`backend_timeout` default** changes by >2× (currently 240s, retry
   budget is < 1%)
2. **HTTP request timeout** changes from 2s (affects total wait math)
3. **Field telemetry** shows ghost-task cleanup failure rate > 5% in
   production
4. **Network stack** materially changes (e.g. HTTP/3, QUIC adoption
   shifts the dominant transient failure class)

---

## Cross-references

- Constant: `src/ai_intervention_agent/server_feedback.py:206`
- Consumer: `src/ai_intervention_agent/server_feedback.py:484-494`
  (`_close_orphan_task_best_effort`)
- Tests:
  - `tests/test_retry_before_close_*.py` (R165 reliability suite)
  - `tests/test_feat_fetch_retry_backoff_decision_r314.py` (this
    decision doc invariant)
- Lineage:
  - **R308** (cr61) — CI xdist worker tuning decision (decision-three-
    layer pattern 1st app)
  - **R314 (this)** — fetch retry backoff decision (decision-three-
    layer pattern 2nd app)
