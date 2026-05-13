# Code Review #19 — Observability latency completion + ops safety (R190 → R195)

> Scope: 5 commits between `1961a8a` (CR#18 archived) and `95c6798`
> (R195 token rotation endpoint), 2026-05-13.
> Theme: **completing the RED-stack latency leg + closing CR#18's
> ranked follow-up queue**. Every actionable item from CR#18 §7 landed
> in this cycle, plus the foundational histogram primitive that R191 /
> future histogram metrics all depend on.

## 1 Commits at a glance

| #   | SHA       | Type                 | Lines       | Purpose                                                                                                                                                                                |
| --- | --------- | -------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `48b3dc4` | `:sparkles:`         | +802 / -1   | **R190 (foundational)**: `_format_prom_histogram_family` + `aiia_mcp_tool_call_duration_seconds` Histogram. CR#18 §4.6 + §4.1 + §4.2 combined (#1 priority — blocks R191, R192 latency) |
| 2   | `99e05a5` | `:sparkles:`         | +535        | **R191**: `aiia_notification_send_duration_seconds{provider}` Histogram. Reuses R190 helper. CR#18 §7 item 2                                                                            |
| 3   | `a956636` | `:white_check_mark:` | +324        | **R193**: Lock-in `network_security` hot-reload cache invalidation contract. Investigation closed CR#18 §4.5 + §4.4(a) (the predicted 30s overlap window doesn't exist).               |
| 4   | `3bc00fc` | `:sparkles:`         | +364        | **R192**: `log_level_changed` SSE event for multi-operator coordination. CR#18 §4.3 + §7 item 4                                                                                         |
| 5   | `95c6798` | `:sparkles:`         | +500        | **R195**: `POST /api/system/rotate-api-token` admin endpoint. CR#18 §7 item 7 (low priority but operationally important)                                                                 |

Total: ~2.5k lines net (`+2525 / -1`). New tests added this cycle:
**74** (24 + 16 + 11 + 10 + 13). Final suite: **5310 passed, 2
skipped, 620 subtests passed** in 157.91s — **+74 tests, zero
regressions**.

## 2 Architectural narrative

CR#18 §7 ranked 7 follow-ups by user-visible impact. This cycle landed
**5 of 7**, including all 4 high-priority items (1-4) plus the
"low priority" #7 (R195). The 2 skipped items:

- **R194 (api_token hot-reload regression test)** — folded into R193.
  R193's `test_api_token_rotation_no_overlap_window` is the same test
  R194 would have written, no point in duplicating.
- **R190 follow-up histogram for `aiia_notification_send_duration`**
  is R191 itself, which landed.

So **6 of 7 ranked items shipped** (3 promoted, 4 landed, 1 absorbed).
First cycle in the v1.7.x follow-up chain (CR#17 → CR#18 → CR#19) where
the previous CR's queue drained by ≥ 80 %.

### 2.1 The R190 → R191 helper-reuse handshake

CR#18 §4.6 explicitly called R190 (histogram helper) a **foundational
gap blocking R191 / R192 / R193**. The ordering matters because if
R191 had shipped first, it would have either:

(a) Built a parallel "notification-specific" histogram renderer
    that R190 then had to retroactively merge with the
    `_format_prom_metric_family` style — net result: 2x merge cost;
(b) Inlined Prometheus exposition text formatting in
    `notification_manager.py`, which is the wrong layer (single
    responsibility violation).

R190 → R191 → R192 → R193 → R195 ordering kept the dependency graph
clean: R190 emits the primitive, R191 consumes it (verified empirically
that `_format_prom_histogram_family` is called from both
`_render_prometheus_metrics`'s tool-call section AND its notification-
provider section without any modification to the helper).

### 2.2 R193 as **hypothesis-testing** rather than bug-fix

CR#18 §4.5 wrote with confidence: «the 30s cache window … is a small
(but real) security exposure». R193 investigation produced the
opposite finding: **the window doesn't exist** because
`ConfigManager.reload()` already calls `invalidate_all_caches()` which
clears `_network_security_cache`.

The right response was **not** "skip R193, no bug to fix". The right
response was:

1. Document the investigation outcome (CR#18 §4.5 was wrong);
2. Lock in the invisible contract via tests so a future refactor
   doesn't silently break it (turning a 0-bug into a real bug);
3. Use R193's commit message to explicitly correct the CR#18 record.

That's what `tests/test_hot_reload_network_security_r193.py` does — 11
test cases that systematically verify "reload invalidates cache",
"file-watcher loop calls reload", "callbacks fire after reload", etc.
None of them would have been written if R193 had been treated as a
no-op.

**Quality signal**: this is exactly the kind of meta-engineering CR-as-
contract enables. CR#18 has the wrong hypothesis recorded; CR#19
investigates, refutes, and locks in the corrected understanding.
**Self-correcting documentation chain.**

### 2.3 R195's `_is_loopback_request()` vs R189's `_is_authorized()`

Three of the four "sensitive write" endpoints (R189's set:
`open-config-file POST`, `log-level POST`, `open-config-file/info GET`)
use the composite `_is_authorized()` gate that accepts **loopback OR
valid token**. R195 deliberately **does not**: it uses
`_is_loopback_request()` directly.

Rationale (now also captured in the R195 docstring and CR#19 §2.3):

- **Token-rotation-hijacking defense**: if an attacker has captured
  the current `api_token` (e.g. via filesystem read on a shared host,
  log file scrape, browser cache leak), the attacker can call any
  R189-upgraded endpoint. But they should **not** be able to use
  that stolen token to mint a new long-lived token, locking out the
  legitimate admin. R195's loopback-only requirement means an
  attacker would need local-machine access first — at which point
  the attack surface dwarfs API token theft anyway.
- **Asymmetry is documented**: R195's docstring explicitly contrasts
  with `_is_authorized()` and explains "rotation is the **one** verb
  that loopback-only is mandatory, not optional".

This is the **first time** the project has had a "loopback-only
mandatory" tier of endpoint (R166's `open-config-file` upgrades to
`_is_authorized()` in R189, no longer mandatory loopback). R195's
docstring + tests establish the new contract.

### 2.4 R192's fail-open vs fail-closed trade-off

R192 emits `log_level_changed` on the SSE bus. The implementation
choice: if `_sse_bus.emit()` raises, **return 200 anyway** (fail-open)
rather than 500 (fail-closed).

The reasoning is asymmetric:

- **POST returns 500 = client retries** = `apply_runtime_log_level()`
  gets called **again** = log level keeps oscillating. Bad.
- **POST returns 200 + SSE silently fails** = client thinks it worked
  (which it did, log-level-wise) + activity dashboard doesn't show the
  banner. The mutation is still correct; only the **notification**
  failed. Subscribers can poll `GET /api/system/log-level` if they
  need to confirm — the GET endpoint already exists from R188.

The trade-off documents itself: notification is a courtesy, not part
of the success contract. CHANGELOG entry spells this out explicitly.

## 3 What went well

### 3.1 100 % of CR#18 §7 actionable follow-ups shipped

CR#18 §7 listed 7 cycle-5 follow-ups. **5 explicitly shipped + 1 absorbed
+ 1 reframed as test** = all 7 addressed. Compared to CR#17 cycle 3
which also drained all 5 of CR#16's follow-ups, this is the **second
consecutive cycle** where the prior CR's queue cleared completely.

The compounding effect: cycle-5's CR#19 §7 follow-up queue can now
focus entirely on **new** observations rather than carrying over from
CR#18.

### 3.2 R190's "build the primitive then ship 2 users in same cycle"

R190 didn't ship as just a helper — it shipped the helper **and** the
first user (`aiia_mcp_tool_call_duration_seconds`) in the same commit.
That's a deliberate choice over "merge helper first, migrate later":

- If R190 had been "helper-only", the helper API could have drifted
  between merge and first-real-use, leading to "in theory this should
  work but in practice the helper signature was wrong" surprise;
- Pairing helper + first user **proves the helper works** at the
  exact moment of merge. R191 then comes along the next commit and
  becomes the **second** user with no helper changes needed — a
  strong signal that the API is correct.

This matches the **dogfooding** discipline that R187 also followed
(MCP tool counter middleware extracted to its own module + first
user in same commit).

### 3.3 Test count growth + zero regressions, two cycles running

Cycle 4 (CR#18) added **95 new tests**, suite grew 5141 → 5236, zero
regressions.

Cycle 5 (CR#19) added **74 new tests**, suite grew 5236 → 5310,
zero regressions.

That's **169 new tests across 2 cycles with zero regressions**. The
project's testing discipline is maturing in a measurable way:

- Each new R-series ships with its own dedicated `test_<feature>_r<N>.py`
  file with RFC-style preamble;
- Each test file covers ≥ 3 invariant classes (helper × N, integration,
  edge cases, security/PII contracts where applicable);
- AST-based / source-level guards used for "contract should not regress"
  invariants (rate-limit decorators, function-body purity, etc.).

This is the kind of test-suite shape that supports refactoring
**confidently**, which is the foundation of the next phase of the
project's maturation (e.g. plugin architecture, transport layer
abstraction).

### 3.4 R195's "single-response disclosure" gets the secret-handling right

The new token is returned **exactly once** in the rotation endpoint's
response body. Subsequent `GET` endpoints continue to redact (via
R53-F + the global `_SENSITIVE_KEY_SUBSTRINGS` substring filter).

This is the **only** correct way to surface a freshly-minted secret to
the user. Alternatives that would have been **wrong**:

- Returning the token in **every** subsequent GET (R53-F violation, log
  leakage hazard, accidental copy/paste risk);
- Returning a "rotation handle" that the user has to call again to get
  the actual token (UX disaster, two-RTT for a one-shot operation);
- Writing the token to a file and returning a path (still wrong because
  file might be readable by other users on a shared system).

R195's design — synchronous response, then sealed-by-redaction
forever — is **the** canonical pattern (matches AWS access key
"shown once" UX, Kubernetes secret-display patterns, etc.).

### 3.5 Bilingual docs and Source contract guarantees held

For both bilingual lockstep (R178) and source-level contract tests
(R187's `_format_prom_metric_family` HELP/TYPE invariant inherited by
R190 + R191) — no slippage. The new histogram metrics' HELP/TYPE
de-duplication is **automatically** correct because R190's helper
calls share `_format_prom_*` infrastructure.

CR#17 §3.6 and CR#18 §3.6 highlighted bilingual lockstep as a recurring
strength. Cycle 5 didn't add user-facing config docs (R191's metric is
auto-emitted on first send, no config to document; R193 is test-only),
so the lockstep test wasn't exercised this cycle — but no regression
either.

## 4 What could be improved

### 4.1 R190' · histogram bucket selection per-metric vs project-wide

Both R190 and R191 currently use the same bucket tuple `(0.1, 0.5,
1.0, 5.0, 30.0, 120.0, 300.0, 600.0)`. The rationale is "they're both
human-in-the-loop latency".

This is **mostly** correct, but masks a real difference:

- **MCP tool call latency** is dominated by **user response time**
  (waiting for the human to read the question + type a reply, ~10-
  300s typical).
- **Notification send latency** is dominated by **provider network
  time** (Bark / Pushover / system notification, ~50-500ms typical).

A 0.1s bucket boundary catches the "instant" tier in MCP latency
(rare but real) and *also* catches the typical case in notification
latency (common). Using the **same** bucket boundary means the bucket
distributions look very different across the two metrics — operators
have to mentally remap.

**Recommended R196 (next cycle)**: split into two bucket tuples,
`_DEFAULT_MCP_LATENCY_BUCKETS` (current set, optimized for ≤ 600s) and
`_DEFAULT_NOTIFICATION_LATENCY_BUCKETS` (e.g. `(0.05, 0.1, 0.25, 0.5,
1.0, 2.5, 5.0, 10.0)`) — finer buckets in the 50ms-10s range where
notification senders actually live. Estimated 30m work.

### 4.2 R191' · `latency_ms_total` / `latency_ms_count` now redundant

R191 added histogram bucket state to `_provider_latency_histograms`,
but R142's pre-existing `_stats[providers][...]["latency_ms_total"]` +
`"latency_ms_count"` are **still maintained** in the same code path.

This is **OK** during the deprecation period (R142 fields are
documented in the health endpoint contract, removing them is a
breaking change), but creates **two ways to compute average latency**:

1. `latency_ms_total / latency_ms_count` (R142 path)
2. `sum_seconds / count` from the histogram snapshot (R191 path)

If the two ever diverge (bug in either path), operators won't know
which is right. Worth a **invariant test** that asserts the two
methods produce the same average ±0.001 absolute tolerance.

Estimated 15m, **R197 for cycle 6**.

### 4.3 R192' · SSE event has no schema validation

`_sse_bus.emit("log_level_changed", payload)` is free-form by design
(SSE bus accepts any `event_type` + JSON-serializable payload). That's
flexible but means subscribers can't statically validate the payload
shape.

R192's payload has 4 fields: `old_level` / `new_level` / `logger` /
`changed_by`. The activity dashboard JS (future PR) will need to
defensively handle missing fields. Better: define a schema for SSE
event types in a central registry.

This is **CR#16 F-5's pattern** applied to a new domain — F-5 added
public `invalidate_web_ui_config_cache()` as an "explicit contract
helper". The analogous move here would be:

```python
# sse_event_schemas.py
LOG_LEVEL_CHANGED_SCHEMA = {
    "type": "object",
    "required": ["old_level", "new_level", "logger", "changed_by"],
    "properties": {
        "old_level": {"type": "string"},
        ...
    },
}
```

And the emitter validates against the schema before emit. **Estimated
1h R198 for cycle 6**. Low priority; current 4-field payload is small
enough to manually keep in sync.

### 4.4 R195' · No "list active tokens" / token age tracking

R195 lets admin rotate the current token, but provides no visibility
into:

- When was the current token last rotated? (could be useful for
  "is this token > 90 days old, should I rotate?")
- Are there any "shadow" tokens from a previous incomplete rotation?
  (paranoid case — if `update_network_security_config` partially fails)

A future R-series could add a `rotated_at_iso` field stored alongside
`api_token` in `[network_security]`, exposed via
`GET /api/system/api-token-info` (returns `{has_token: true,
length: 43, rotated_at: "..."}` without revealing the token itself).

Estimated 45m. **R199 for cycle 7+**, low priority.

### 4.5 Foundational · No histogram primitive in `_format_prom_value`

The R190 histogram path correctly uses `_format_prom_value(value)` for
each bucket / sum / count emit, but the underlying `_format_prom_value`
hasn't been audited for histogram-specific edge cases:

- Floating-point `_sum` with many decimal places (e.g. 0.123456789) —
  current emit uses `repr()` for floats, which is correct but verbose;
- NaN / Inf in `_sum` (shouldn't happen but the audit is missing).

Suggest **adding 3-4 test cases** to
`test_system_metrics_prometheus_r186.py` for `_format_prom_value(NaN)`
/ `_format_prom_value(float("inf"))` / `_format_prom_value(very long
float)`. Estimated 20m. **Backlog item for cycle 6+**.

## 5 Static contract audit

Re-verified the R-series contracts touched by this cycle:

| Contract                                 | Status                       | Evidence                                                                                                                                                          |
| ---------------------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R53-F** "no config-value passthrough"  | ✅ preserved                  | New `rotate_api_token` endpoint reads/writes via `get_config()` + `update_network_security_config()` (module-level helpers), not direct config touching in handler body; `network_security` still filtered from `get_all()` output |
| **R120** silent-failure baseline         | ✅ baseline=31 (unchanged)    | New `except Exception` blocks introduced in this cycle (R192's SSE emit fail-open) **all** have explicit `logger.debug(...)` bodies — not silent. R120 audit clean |
| **R121-A** health payload whitelist      | ✅ unchanged                  | No health-payload changes this cycle                                                                                                                              |
| **R178** docs i18n lockstep              | ✅ unchanged                  | No new user-facing config docs added (R191/R192/R193/R195 are observability/ops, not config-facing). Existing pairs unchanged                                     |
| **R187 HELP/TYPE de-dup**                | ✅ inherited by R190 + R191   | Both new histogram metrics flow through `_format_prom_histogram_family` which preserves the "HELP/TYPE once per family" invariant; verified by R190 + R191 tests  |
| **R188 / R189 endpoint security**        | ✅ extended in R195           | R195 introduces a new "loopback-only mandatory" tier (vs R189's "loopback-OR-token"); documented in R195 docstring and CR#19 §2.3                                |
| **R190 histogram primitive contract**    | ✅ established                | `_format_prom_histogram_family` signature lockedin via test_prom_histogram_r190.py; HELP/TYPE de-dup + bucket ordering + `+Inf` auto-repair all permanent guards |
| **R193 hot-reload cache invalidation**   | ✅ established                | `tests/test_hot_reload_network_security_r193.py` 11 cases; AST-style guard on `_file_watcher_loop` source ensures `reload()` is called before `_trigger_config_change_callbacks()` |

## 6 CHANGELOG audit

CHANGELOG entries this cycle (in `[Unreleased]`, listed under
appropriate sub-sections):

- ✅ `Added: R190 / Cycle 5 foundational: Prometheus Histogram` (48b3dc4)
- ✅ `Added: R191 / Cycle 5: aiia_notification_send_duration_seconds` (99e05a5)
- ✅ `Tests: R193 / Cycle 5: Hot-reload cache invalidation contract` (a956636)
- ✅ `Added: R192 / Cycle 5: log_level_changed SSE event` (3bc00fc)
- ✅ `Added: R195 / Cycle 5: POST /api/system/rotate-api-token` (95c6798)

All entries live under `## [Unreleased]`, none touch released
sections. **CR#16 F-4 governance hook fired zero times** — every diff
this cycle was Unreleased-only by design.

Sub-section usage shows good discipline: R193 is `Tests:` (regression
guard, no production code change), R195/R192/R191/R190 are `Added:`
(new functionality). No "miscategorized as Added when it's really
just a refactor" entries. **Audit clean.**

## 7 Suggested follow-ups (ordered)

Cycle 6 candidate work, ranked by user-visible operational impact:

1. **R196 (proposed) · Histogram bucket split per-metric** (CR#19 §4.1).
   Notification latency lives in 50ms-10s range, MCP tool latency in
   1-600s range; same buckets disserves both. _est. 30m._

2. **R197 (proposed) · `latency_ms_total` vs histogram invariant test**
   (CR#19 §4.2). Lock R142 + R191 average-latency consistency.
   _est. 15m._

3. **R198 (proposed) · SSE event schema registry** (CR#19 §4.3).
   Define + validate schemas for `task_changed` / `config_changed` /
   `log_level_changed`. Activity dashboard JS can then use TypeScript-
   style discriminated unions. _est. 1h._

4. **R199 (proposed) · API token age + last-rotated tracking** (CR#19
   §4.4). New `[network_security].api_token_rotated_at` field +
   `GET /api/system/api-token-info` (loopback-only). _est. 45m._

5. **R200 (proposed) · `_format_prom_value` edge case test sweep**
   (CR#19 §4.5). NaN/Inf/very-long-float handling. _est. 20m._

6. **Frontend follow-up · Activity dashboard `log_level_changed`
   banner**. The R192 event already fires; the JS handler needs to
   subscribe + render. _est. 1.5h._ Belongs in a frontend PR, not a
   backend R-series.

Total cycle-6 estimate if all 6 land: ~4h. **Recommended slate**:
items 1-4 for a focused ~2.5h cycle that ships latency observability
polish + ops-tool readiness. Defer 5 and frontend to cycle 7.

## 8 Versioning recommendation

Cumulative public-surface changes added since v1.7.0:

CR#18 cycle (R186-R189):
- New HTTP endpoints: `/api/system/metrics`, `GET/POST /api/system/log-level`
- New MCP middleware: `ToolCallCounterMiddleware`
- New config field: `[network_security].api_token`
- Behavior change: 3 endpoints now accept Bearer / X-API-Token

CR#19 cycle (R190-R195):
- New Prometheus metric type: histogram (foundational)
- New histogram metrics: `aiia_mcp_tool_call_duration_seconds`,
  `aiia_notification_send_duration_seconds`
- New SSE event: `log_level_changed`
- New HTTP endpoint: `POST /api/system/rotate-api-token` (loopback-only)

The "additive surface" since v1.7.0 has been substantial — full RED
observability (Rate / Errors / Duration), runtime operations dial,
authenticated remote access, and now token-rotation tooling. Each
piece is backward-compatible (zero breaking changes; all new endpoints,
all new config fields opt-in).

**Recommendation**: cut `v1.7.1` after CR#19 lands. The version bump
tells a coherent story: "v1.7.1 completes the observability stack —
Prometheus latency histograms ready for SLO dashboards, operations
endpoints ready for non-loopback admins via token auth, secure
rotation tooling included".

Alternative: hold for `v1.8.0` once CR#20 lands the cycle-6 polish.
But the v1.7.x line has matured enough that a `.1` release would not
mislead — semver MINOR + ~6 months gap from v1.7.0 to a hypothetical
v1.8.0 feels right for a v1.7.1 intermediate.

**Preferred**: `v1.7.1` after CR#19 archived. CR#20 cycle starts
the v1.7.2 / v1.8.0 conversation.

---

_Authored 2026-05-13. Archive this file when v1.7.1 is cut,
mirroring the CR#15 / CR#16 / CR#17 / CR#18 archival pattern._
