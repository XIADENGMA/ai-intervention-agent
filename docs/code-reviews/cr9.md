# Code Review #9 — R150-R154 cycle

> Internal review of the R150 → R154 commit cluster, performed after
> commit `5158d1e` (R154 housekeeping).  Reviewers preparing the
> v1.6.3 release should walk this list before tagging.

> **⚠️ Historical context — UI scope removed in `feat-remove-test`
> (commit `faad96a`, cycle covered by CR#30)**: the R150 self-test
> history trail, R152 activity dashboard subsection, R153 logs-row
> inline expand, R155 expanded-state persistence, and R156 show-more
> toggle were **all deleted** in a later cycle following user
> preference. The associated JS modules (`notification_test_button.js`,
> `activity_dashboard.js`), CSS rules (`.self-test-history*`,
> `.activity-dashboard-*`), locale keys (`systemTest*`, `activityDashboard*`),
> and 9 in-suite invariant tests (`test_activity_dashboard_*_r{152,153,155,156}.py`,
> `test_notification_test_button_*_r{146,147,148,150}.py`, `test_housekeeping_r151.py`,
> `test_system_endpoint_payload_contract_r154.py`) were pruned in
> lockstep. **The R150-R154 narrative below is preserved as
> historical record** — these features no longer exist in the
> running product. The backend `/api/system/{health,sse-stats,
> recent-logs,notifications/test}` endpoints **are still registered**
> for off-process consumers (CI / monitoring / curl debugging); see
> `tests/test_feat_remove_test_uis_removed.py` for the post-removal
> regression contract and `docs/troubleshooting.{md,zh-CN.md}` § 13
> for the rewritten "backend-only" version of the R154 lesson.

## Cycle summary

| Tag | Hash | One-liner |
|---|---|---|
| R150 | `5b6fd67` | Notification self-test **history trail** (localStorage, last 5 entries, schema-versioned) |
| R151 | `1fcd002` | Housekeeping: `CLIENT_COOLDOWN_MS` 600 → 1500 ms, ovsx pin upgrade ritual, `[Unreleased]` backfill |
| R152 | `3cf0812` | **Activity Dashboard** settings subsection (6 rows × 4 endpoints, 5 s poll, visibility-aware) |
| R153 | `bf0191b` | Logs row **inline expand** + R152 `logs.logs` field-name bug fix |
| R154 | `5158d1e` | Housekeeping: `/api/system/*` ↔ JS payload field-name contract (R154 lesson) + CHANGELOG / troubleshooting docs |

Net delta: **5 R-series commits, ≈ 1450 LoC source + ≈ 1600 LoC test
+ ≈ 380 LoC docs.  Total test count climbed by 152 cases (52 in R152,
38 in R153, 41 in R150, 8 in R151, 21 in R154).  All 4855+
existing tests continue to pass.  ci_gate exit 0.**

## Strengths (what the cycle did well)

- **Layered competitive parity.** R150 picked up uptime-kuma /
  healthchecks.io's "last 5 runs" trail directly under the
  trigger button; R152 picked up uptime-kuma / grafana's status-
  page tile pattern.  Both ship without new server endpoints —
  the heavy lifting was already done in R141-R145.  Net effect:
  the dashboard is a pure recombination of existing observability
  + the user gets to see it from inside settings rather than
  needing curl.
- **R154's structural surface.** Pinning every consumer-visible
  field across four endpoints with a 21-case contract gate
  converts a "single bug found by user pain" (R152's `logs.logs`)
  into "an entire bug-class blocked at test-collection time".
  Same pattern that
  `tests/test_server_config_shared_types_parity.py` /
  `tests/test_reset_feedback_config_parity.py` use for the
  config layer — this generalises it to the HTTP API layer.
- **Defensive UI everywhere.** R150's `_readStorage` write-probe
  handles private mode / sandboxed iframes / `QuotaExceededError`
  gracefully; R152's per-row fetch failure isolates one stale
  row without bringing down the dashboard; R153 keeps the
  expanded state across the 5-second re-render by find-or-create
  rather than tear-down-rebuild.  All three use the same
  `createElement` + `textContent` DOM-XSS-immune pattern locked
  in earlier R-cycles.
- **a11y baseline holds.** Every clickable affordance shipped in
  this cycle is a real `<button type="button">` with
  `aria-controls` + `aria-expanded`; every revealed region
  carries `role="region"` or `role="log"` / `role="list"` with
  `aria-live="polite"`.  Screen-reader review (manual smoke
  pass) reads the history trail and dashboard expansions
  naturally.
- **i18n discipline.** Every shipped string passes through
  `window.AIIA_I18N.t` with a literal key the dead-key analyzer
  can grep.  R152 needed a one-off `_labelForRow` helper to
  surface keys that lived only inside `ROW_DEFS`-data; this is
  a documented pattern future
  data-driven UI modules can reuse.

## Findings

### F-1 — R152 testing-blind spot ✅ (closed by R154)

**Severity:** *critical, closed*

R152 shipped with a `logs.logs` field-name regression that bypassed
all 52 of its own test cases because every assertion was either
"function exists", "constant has value", or "DOM has attribute".
None of them inspected the field-name accessor pattern.  The bug
shipped to v1.6.2 (technically) and would have shipped to v1.6.3
batch had R153 not noticed during the recent-logs design review.

**Mitigation:** R154 ships
`tests/test_system_endpoint_payload_contract_r154.py` (21 cases)
locking every consumer-visible field across all four endpoints
that the Activity Dashboard reads.  The next regression on a
*different* field cannot ship past the gate.

**Lesson for future R-cycles:** Every UI module that reads server
JSON needs a contract test in addition to its API-surface test.
The contract test is cheap (~ 200 LoC of `assertIn`-pinning) and
pays back the first time someone renames a field on either side.

### F-2 — Polling load: 48 req/min from a single open dashboard ⚠️

**Severity:** *medium, mitigation deferred*

R152 fires four parallel `GET`s every 5 seconds while the panel
is expanded: 12 req/min × 4 = **48 req/min total**.  Each
endpoint has its own Flask-Limiter cap:

| Endpoint | Cap | Dashboard load (req/min) | Headroom |
|---|---|---|---|
| `/api/tasks` | unlimited (defaults exempt) | 12 | ∞ |
| `/api/system/sse-stats` | 60/min | 12 | 4× |
| `/api/system/health` | 120/min | 12 | 10× |
| `/api/system/recent-logs` | 30/min | 12 | 2.5× |

`recent-logs` is the tightest at 2.5× headroom.  Two concurrent
operators (each with their own dashboard open) would hit 24/min
on `recent-logs` — still under cap, but a single mis-configured
client (poll-loop bug, dev tools open in two windows) could
push past 30.

**What ships now:** `setPollMs` is exported so dev tools / tests
can throttle to a longer interval; `document.hidden` pauses
polling automatically.

**Suggested follow-up (R155 candidate):** Add `ETag` / `If-None-
Match` support to the four endpoints; the dashboard becomes a
304 Not Modified consumer when state hasn't changed, dropping
the effective load to near zero on a quiet system without
changing the perceived freshness.  This is the same trick
fly.io / hosted-tunnel dashboards use.

### F-3 — Dashboard expanded state isn't persisted ⚠️

**Severity:** *low*

R152's toggle defaults to collapsed and forgets across page
reload.  Users who routinely watch the dashboard during a
debugging session have to click open every refresh.  R150's
history trail has the same property but it's less visible
because the trail has fewer entries to "lose" on collapse.

**Suggested follow-up:** Mirror R150's `aiia.self_test.history.v1`
pattern with `aiia.activity_dashboard.expanded.v1` —
schema-versioned, defensive read on private mode, sync across
tabs via `storage` event.  ≈ 40 LoC.  R155 candidate.

### F-4 — Logs row's expanded view hard-caps at 5 entries ⚠️

**Severity:** *low*

R153 ships `LOGS_TAIL_COUNT = 5`.  Sufficient for "is anything
warning right now?" but operators investigating a known incident
would want the full 50 entries the endpoint can serve.  Adding
a "load more" / "show 50" button would surface that without a
separate ops tool.

**Suggested follow-up:** A second `[show 50]` link next to
`[expand]` that swaps `?limit=5` for `?limit=50` and re-renders.
Trivially additive.

### F-5 — R150 schema-version drop path is unit-tested but not
runtime-tested ⚠️

**Severity:** *low*

`tests/test_notification_test_button_history_r150.py` asserts
that `_loadHistory` uses `e.v === HISTORY_SCHEMA_VERSION` as a
filter — but the test does that by grepping the JS source for
the literal expression.  It doesn't actually drive the renderer
with a `v=2` payload and assert "the entry is silently dropped".
If a future R-cycle accidentally weakens the filter (e.g. to
`e.v >= 1`), the source-code grep would still pass.

**Suggested follow-up:** Either (a) introduce a jsdom-based
runtime test fixture for the localStorage path, or (b) add a
property-based literal test that the only comparison shape
appearing in the file body is `=== HISTORY_SCHEMA_VERSION` (not
`>=` / `!==` / `<`).  Option (b) is cheap (~ 10 LoC of test
code, zero new dependencies); jsdom would unblock other UI
runtime tests too but adds dependency surface.

### F-6 — Endpoint poll redundancy on `/api/system/health` 💡

**Severity:** *informational*

Three R-cycles now hit `/api/system/health`:
1. R147's post-dispatch health probe (one-shot, 5 s timeout, on
   button click)
2. R148's pre-dispatch health baseline (one-shot, 1 s timeout,
   on button click)
3. R152's dashboard poll (every 5 s while open)

All three concurrent calls go through Flask-Limiter's
"120 per minute" cap; with two operators dashboarding +
clicking the self-test button intermittently, the cap is
nowhere near hit (~ 30/min realistic ceiling).  No risk **right
now**, but the pattern would deserve a single shared client-
side fetch cache if a future R-cycle adds yet another consumer.

### F-7 — UI naming alignment 💡

**Severity:** *informational*

R152 introduced the **"Activity Dashboard"** term in en + zh-CN
locales.  README mentions "settings panel" and "observability
APIs" but not "Activity Dashboard" yet.  When v1.6.3 ships,
the README "What's new" line should adopt the user-facing term
so the feature is discoverable from project docs.

## Action items (mapped to R155+)

| ID | Severity | Action | Suggested cycle |
|---|---|---|---|
| F-1 | closed | (no action — R154 already mitigated) | — |
| F-2 | medium | Add `ETag` / `If-None-Match` to the four polled endpoints | R156 (release-blocker if dashboard goes wider) |
| F-3 | low | localStorage-persist `aria-expanded` state | R155 |
| F-4 | low | `[show 50]` link beside `[expand]` | R155 |
| F-5 | low | Property-test the schema-version filter shape | R155 |
| F-6 | info | Defer — single-shared-fetch-cache only when 4th consumer lands | — |
| F-7 | info | README "What's new" once v1.6.3 ships | release-prep |

## Release readiness

- **v1.6.3 batch (R148-R154):** ready in principle.  All tests
  green, ci_gate green, `[Unreleased]` backfilled in
  `CHANGELOG.md`, no migrations required.
- **Open VSX:** R149 pin (`ovsx@0.10.9`) is in place; release
  should publish cleanly.
- **Suggested release-prep checklist:**
  1. Land R155 (F-3 / F-4 / F-5 follow-ups), keep R156 (ETag)
     for the next minor.
  2. README "What's new" update (F-7) referencing the Activity
     Dashboard term.
  3. `uv run python scripts/bump_version.py patch` → v1.6.3.
  4. Tag + push, monitor the release workflow.
  5. After release: write `docs/lessons-learned-r140s.md` post-
     mortem (R141-R154 cluster) including the R152 → R153 →
     R154 testing-blind-spot lesson.

## Sign-off

Reviewer: project owner (Cycle CR#9, automatic continuation).

Date: 2026-05-10 (UTC+8).

Status: **Approved for v1.6.3 prep after R155 follow-ups land.**
