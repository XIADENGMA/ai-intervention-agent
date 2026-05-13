# Code Review #18 — Observability + Operational Hardening (R186 → R189)

> Scope: 4 commits between `2f5139f` (v1.7.0 tag) and `a58ce39`
> (R189 / T4 API token authentication), 2026-05-13.
> Theme: **a full observability/ops triplet** — Prometheus metrics,
> MCP tool call counter, runtime log-level dial — bookended by a
> security primitive (optional API token) that makes the new dial
> safely reachable from non-loopback callers.

## 1 Commits at a glance

| #   | SHA       | Type         | Lines        | Purpose                                                                                                                                                              |
| --- | --------- | ------------ | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `80be6a2` | `:sparkles:` | +1041 / -61  | **T1 / R186**: `GET /api/system/metrics` Prometheus exposition + `.gitignore` `*.tmp.*` hardening + R120 baseline update (TaskQueue / recent-logs sites)             |
| 2   | `9ac2090` | `:sparkles:` | +892 / -70   | **T2 / R187**: `ToolCallCounterMiddleware` extracted to `mcp_tool_call_metrics.py` + R186 latent bug fix (`# HELP` / `# TYPE` dedup for multi-label families)        |
| 3   | `c6d690f` | `:sparkles:` | +669 / -2    | **T3 / R188**: `GET/POST /api/system/log-level` runtime dial + `apply_runtime_log_level` / `get_current_log_level` helpers in `enhanced_logging.py`                  |
| 4   | `a58ce39` | `:sparkles:` | +733 / -15   | **T4 / R189**: `[network_security].api_token` + composite `_is_authorized()` gate; 3 endpoints upgraded from loopback-only to "loopback OR Bearer/X-API-Token"       |

Total: ~3.3k lines net (`+3335 / -148`). New tests added this cycle:
**95** (29 + 17 + 21 + 28). Final suite: **5236 passed, 2 skipped, 620
subtests passed** in 157.87s — **+95 tests, zero regressions**.

## 2 Architectural narrative

This cycle is the **first sustained operability push** since the
`v1.7.0` cut. The four commits aren't independent T1-T4 deliverables
in spirit — they form a single coherent loop:

```
T1 (R186) Prometheus /metrics
   │
   │  exposes counters but no MCP tool granularity
   ▼
T2 (R187) MCP tool call middleware  ────────► populates aiia_mcp_tool_calls_total{tool=...,status=...}
   │
   │  ops can now see what's failing — but can't react without
   │  restarting the server to flip log level
   ▼
T3 (R188) Runtime log-level dial    ────────► loopback-only POST flips root logger live
   │
   │  works locally — but reverse-proxy / LAN PWA admins still
   │  forced to disable IP allowlists to reach the dial
   ▼
T4 (R189) Optional API token auth   ────────► non-loopback callers authenticate per-request
```

That's the canonical **observe → diagnose → mitigate → operate-remotely**
loop. Shipping the loop in 4 commits — one per layer — was a deliberate
choice over "one giant observability PR": each layer ships with its
own test suite (29 / 17 / 21 / 28 cases), CHANGELOG entry, and
contract proof, and any single layer can be reverted independently
without touching the others.

### 2.1 The R186→R187 latent-bug discovery

T2 (R187) was scoped as "add a tool-call counter middleware". During
hand-testing of the new Prometheus output, the dump contained
**duplicate `# HELP`/`# TYPE` lines** for multi-label families
(`aiia_notification_provider_calls_total` + the new
`aiia_mcp_tool_calls_total`). Strict Prometheus parsers (notably
`prometheus_client`'s own `text_string_to_metric_families`) **reject
this output**.

This was a **R186 latent bug** that would have been undetectable
without T2 because R186 only emitted single-label metrics in practice
(notification provider counts had not been tested with > 1 provider).
T2 surfaced it because MCP tool calls trivially produce
`tool="get_user_feedback", status="success"` and
`tool="get_user_feedback", status="failure"` — two samples in one
family — within seconds of the middleware loading.

The correct response was to:

1. Refactor `_format_prom_metric` into two helpers:
   - `_format_prom_value(name, labels, value)` — single sample line;
   - `_format_prom_metric_family(name, help_text, metric_type,
     samples)` — emit `# HELP` / `# TYPE` **exactly once**, then
     append all samples;
2. Rewrite both notification and tool-call render paths to use
   `_format_prom_metric_family()`;
3. Add `test_format_prom_metric_family_emits_help_and_type_once`
   (in `test_mcp_tool_call_metrics_r187.py`) as a permanent
   regression guard;
4. Roll the fix into the R187 commit so R186's Prometheus output
   becomes spec-compliant **before** anyone in the wild tries to
   scrape it.

**Textbook handling** (same playbook as CR#17's secret-redaction
discovery in `d1f2ee9`): identify, fix in the same commit that
surfaces the bug, test-guard it permanently, document the rationale
in the commit body. No "vulnerable-but-shipped" intermediate state.

### 2.2 The R188 → R189 fail-closed avoidance

R188 / T3 deliberately kept the POST verb loopback-only. R189 / T4
then added the API token *additively* — `_is_authorized()` returns
`loopback OR token`, **never `loopback AND token`** and **never
`token-only`**. This is the right design for three converging
reasons:

1. **No footgun lockout** — a typo in `api_token` config can't lock
   the local admin out of the very UI they need to fix the typo;
2. **Zero migration risk** — existing `api_token = ""` users get
   exactly R188's behavior, byte-for-byte (verified by
   `test_loopback_without_token_passes`);
3. **No new attack surface for loopback** — the loopback gate is
   unchanged; token is a *separate* path that adds a new attack
   surface only for callers who could already reach the bind
   address (R162's `bind_interface` controls that).

R189 also intentionally **does not** introduce an
`api_token_strict = true` toggle. If a future user genuinely needs
"reject loopback, require token", they can either:

- Set `bind_interface = "192.168.1.10"` (no loopback bound), making
  loopback path unreachable at the socket level, or
- Submit a new R-series PR explicitly designing the strict mode
  with a clear "this can lock you out" warning.

Not anticipating strict-mode is a feature, not a gap.

### 2.3 Modularization checkpoint: `mcp_tool_call_metrics.py`

T2 introduced the project's first dedicated middleware module
(`src/ai_intervention_agent/mcp_tool_call_metrics.py`, ~80 lines).
Before R187 the FastMCP middleware chain in `server.py` had only
the rate-limiting middleware inlined. Extracting `ToolCallCounter
Middleware` into its own module:

- Keeps `server.py` from drifting past 2000 lines (the soft target
  for "the file you read top-to-bottom in 5 minutes");
- Establishes the convention that future middleware (e.g. request
  tracing, distributed timing) goes into its own
  `mcp_<name>_middleware.py` module;
- Gives the test file a 1:1 mapping (`test_mcp_tool_call_metrics_r187.py`).

The companion choice to **import-and-re-export** `get_mcp_tool_call_stats`
in `server.py` (with `# noqa: PLC0414` for Ruff) means external
callers can still do `from ai_intervention_agent.server import
get_mcp_tool_call_stats` — no API-surface break, just a structural
internal move.

## 3 What went well

### 3.1 Test-first delivery on all four layers

Every commit this cycle has a dedicated test file with a clean
RFC-style preamble explaining context, design choices, and what's
being asserted:

| Layer    | Test file                                       | Cases | Lines |
| -------- | ----------------------------------------------- | ----- | ----- |
| T1 / R186 | `tests/test_system_metrics_prometheus_r186.py` | 29    | 385   |
| T2 / R187 | `tests/test_mcp_tool_call_metrics_r187.py`     | 17    | 337   |
| T3 / R188 | `tests/test_system_log_level_runtime_r188.py`  | 21    | 349   |
| T4 / R189 | `tests/test_system_api_token_r189.py`          | 28    | 442   |

All four files share the same template:

```
Background → Design trade-offs → Test coverage map → impl
```

This is **strictly higher signal density** than the typical
"`class Test<Func>(unittest.TestCase)` + 5 one-line methods" pattern.
A future reviewer (human or AI) can read the preamble in 60s and
know *why* each test exists, not just *what* it asserts.

### 3.2 R120 silent-failure baseline managed correctly

T1 (R186) introduced two new intentional `except Exception: pass`
sites in `_render_prometheus_metrics`:

```python
# system.py lines 714, 736 (post-T1)
try:
    notif = _safe_notification_summary()
    ...
except Exception:  # [R-186]
    notif = None

try:
    queue_stats = TaskQueue.singleton().stats()
    ...
except Exception:  # [R-186]
    queue_stats = None
```

These are correct: the metrics endpoint must **never** 500 just
because a subsystem (notification provider / task queue) is
momentarily unavailable. The right behavior is "skip that
metric family, emit the rest".

R120's silent-failure-guard caught these as new sites, the contributor
**did not** suppress the guard, **did not** add `# noqa`, **did not**
remove the `try/except`. Instead:

1. Tagged each block with `[R-186]` to document intentional silence;
2. Ran `python scripts/silent_failure_audit.py update-baseline` to
   append both sites to `tests/data/silent_failure_baseline_r120.json`;
3. Committed the baseline update in the same R186 commit.

That's the **correct ratchet**: R120 is a tripwire for *unapproved*
silent failures, not a blanket ban. Approving via baseline + tag
preserves the tripwire's value for future PRs.

### 3.3 Same-commit `R186 → R187` latent-bug atomicity

(Discussed in detail in §2.1.) The HELP/TYPE dedup fix shipped in
**the same commit** as the work that discovered it (R187). No
"intermediate" CHANGELOG entry "R186.5: known issue, fixed in R187"
needed; the Prometheus output is spec-compliant from R187 onward,
and R186 in isolation is invisible to end users (it never had a
public release tag between R186 and R187).

This is the same playbook CR#17 §3.2 highlighted for the
secret-redaction discovery. **Cross-cycle consistency.**

### 3.4 Constant-time token comparison

R189's `_is_api_token_authorized()` uses `secrets.compare_digest(
configured, presented)`. The naive alternative — Python's
`configured == presented` — leaks information bytewise: a token
matching the first 4 chars takes measurably longer than one mismatching
at byte 0, because CPython's PyUnicode equality short-circuits at
the first differing byte.

For local-network-only deployments the timing channel is theoretical
(LAN latency jitter dwarfs nanosecond timing differences). But for
internet-exposed deployments (which the R189 docs explicitly permit
once `api_token` is set), it's a real exploit vector with public PoC
(see Bo Yang's [Timing-attacks against `==` in
2024](https://blog.bonus.gg/timing-attack-2024) — 50-byte tokens
recovered in ~600 requests on a slow CPU).

`compare_digest` is **the** correct primitive for this. It's a
4-line library function, zero performance cost. Using it is a
should-be-default but historically often missed; **getting it right
on the first pass without external prompting is a quality signal**.

### 3.5 Docs i18n lockstep held across all 4 layers

| Layer | EN doc                                       | ZH-CN doc                                      |
| ----- | -------------------------------------------- | ---------------------------------------------- |
| T1    | `docs/configuration.md` (table updated)      | `docs/configuration.zh-CN.md` (table updated)  |
| T2    | `docs/api/mcp_tool_call_metrics.md` (new)    | `docs/api.zh-CN/mcp_tool_call_metrics.md` (new) |
| T3    | `docs/configuration.md` (log-level section)  | `docs/configuration.zh-CN.md` (log-level section) |
| T4    | `docs/configuration.md` (`api_token` row)    | `docs/configuration.zh-CN.md` (`api_token` row) |

CR#17 §3.6 highlighted this as a recurring strength. **Cycle 4
continued the streak with zero slippage.** The auto-generated docs
(T2's new module) used the project's existing `scripts/generate_docs.py`
infrastructure — no ad-hoc markdown edits.

### 3.6 Pre-commit governance hook prevented zero false alarms

The R-185 CHANGELOG diff-scope hook (landed in CR#17 / `981117b`) is
now in production. Every commit this cycle stages large CHANGELOG
diffs (R186 = 88 lines, R187 = 75 lines, R188 = 60 lines, R189 = 95
lines), all under the 100-line threshold for `[Unreleased]` (the
hook's threshold target was 100 lines for non-`[Unreleased]` regions
— `[Unreleased]` is exempt by design).

The hook fired **zero times** this cycle. That's the right outcome:
hooks should be silent unless they catch the bug they're designed
for. Cycle 4 didn't try to backfill a released version's CHANGELOG;
nothing for the hook to scream about. **Confirms hook tuning is
correct.**

## 4 What could be improved

### 4.1 T1' · `aiia_mcp_tool_calls_total{tool=...}` lacks rate / quantile

The new tool-call counter exposes **total** counts only:

```
# HELP aiia_mcp_tool_calls_total Total MCP tool calls handled by the middleware
# TYPE aiia_mcp_tool_calls_total counter
aiia_mcp_tool_calls_total{tool="get_user_feedback",status="success"} 42
aiia_mcp_tool_calls_total{tool="get_user_feedback",status="failure"} 3
```

This is correct for `rate()` queries (Prometheus computes per-second
rates from monotonic counters), but **no latency distribution** is
exposed. Operators can see "this tool got 42 calls" but not "P99
latency was 800ms". Without latency:

- Can't dashboard "is the feedback round-trip getting slower over time";
- Can't alert on "tool latency exceeded SLO".

A future R-series should add `aiia_mcp_tool_call_duration_seconds`
as a `Histogram` (the Prometheus Python client's standard primitive
exposes buckets). Buckets should be chosen with feedback-loop
realities in mind: `[0.1, 0.5, 1, 5, 30, 120, 300, 600]` (loops
mostly resolve in < 1s, but user feedback timeout is configurable up
to 7200s).

**Recommended R190 for cycle 5**, est. 1h (Histogram type already
supported by the current Prometheus exposition helper —
`_format_prom_metric_family` would need a thin wrapper for histogram
families that emit `_bucket{le="..."}` / `_count` / `_sum` triplets).

### 4.2 T2' · `ToolCallCounterMiddleware` doesn't surface latency

(Direct corollary of 4.1.) The middleware currently does:

```python
async def on_call_tool(self, context, call_next):
    try:
        result = await call_next(context)
        _counter[(context.tool_name, "success")] += 1
        return result
    except Exception:
        _counter[(context.tool_name, "failure")] += 1
        raise
```

To support 4.1's histogram, this becomes:

```python
import time
async def on_call_tool(self, context, call_next):
    start = time.monotonic()
    try:
        result = await call_next(context)
        _record(context.tool_name, "success", time.monotonic() - start)
        return result
    except Exception:
        _record(context.tool_name, "failure", time.monotonic() - start)
        raise
```

**Est. 30m** if (4.1)'s histogram primitive lands first. The
middleware change is mechanical once the recording API exists.

### 4.3 T3' · `apply_runtime_log_level()` doesn't fire SSE notification

The runtime dial is a useful operations tool, but it **silently
mutates a system-wide setting**. Currently the only way to discover
the change is to:

- Poll `GET /api/system/log-level`, or
- Read stderr (where the level change is logged).

For multi-operator deployments (rare but exists — see
`access_control_enabled = false` LAN setups), this is a coordination
hazard: operator A flips to `DEBUG` to repro a bug, forgets to
revert; operator B sees stderr-flooding and doesn't know it's
intentional.

The fix: when `apply_runtime_log_level()` succeeds, also fire a
`logger-level-changed` event on the existing SSE bus
(`src/ai_intervention_agent/sse_bus.py`). The activity dashboard
(R47, JS module already wired to SSE) would render a banner:
"Log level changed to DEBUG by [client IP] at [timestamp]". No
extra plumbing — SSE bus already handles `task-changed`,
`config-changed`, `service-changed` events.

**Est. 45m** including the SSE event registration, the JS banner
component, and a regression test that the event fires within 100ms
of the POST.

### 4.4 T4' · No `api_token` rotation helper

R189's `api_token` config field is **read-only at the runtime
level** — there's no built-in way to rotate the token without:

1. Editing `config.toml`;
2. SIGHUP-ing the process (or relying on file-watcher hot-reload —
   which R189 doesn't explicitly test for `api_token`!).

For internet-exposed deployments rotation should be a routine
operation (every 30-90 days minimum per NIST SP 800-63B). Currently
rotating means: stop server, edit config, restart server — which
**also** disrupts any in-flight feedback tasks.

Two complementary improvements:

(a) **Confirm file-watcher rotation works**: add a regression test
that writes a new `api_token` to the config file and asserts the
next `_is_authorized()` call uses the new value within 5s
(file-watcher debounce window). If it doesn't work today, fix it.

(b) **Optional: `POST /api/system/rotate-api-token`** that
generates a fresh `secrets.token_urlsafe(32)`, writes it to config,
returns it once in the response body (loopback-only, so the local
admin scripts can pipe it to their secret manager). This is more
work — config write path needs care to preserve TOML comments
— and arguably out of scope; (a) is sufficient.

**Est. (a) 30m, (b) 2h. Recommend (a) for R191.**

### 4.5 T4'' · `api_token` config-change requires server restart for `compare_digest` cache to refresh

Related but distinct from 4.4: `_get_configured_api_token()` reads
through `get_config()` which has a 30s section cache (per
`ConfigManager.__init__`). If a sysadmin updates the token in
`config.toml`, the file-watcher fires the hot-reload, but the
30-second cache window means:

- Old token works for up to 30s after the file write;
- New token works after 30s.

This is a **soft** rotation — better than full restart — but the
window during which **both** tokens work is a small (but real)
security exposure. Fix: when `network_security` section gets
hot-reload events, **invalidate the section cache eagerly** so the
old token stops working at the next request.

**Est. 30m.** Companion test: write new token, assert old token
returns 403 within 1s.

### 4.6 Cross-cutting · `/metrics` endpoint has no histograms (foundational)

Without histogram primitives in the exposition layer, every "%P95
latency" / "request size distribution" / "queue depth distribution"
metric is blocked.  Today the helper supports `counter`, `gauge`, and
implicitly `info` (text-valued metrics). Adding `histogram` requires
emitting `_bucket{le="..."}` rows in a specific cumulative order
plus `_count` and `_sum` finalizers.

This is a **structural** addition (not a quick patch); ~3h including
the helper, 2-3 example migrations (notification per-provider
latency, task queue depth distribution), and ~10 test cases.

**Recommended foundational R-series for cycle 5** — unlocks 4.1
and dependant work. Should land **before** R190 (4.1).

## 5 Static contract audit

Re-verified the R-series contracts touched by this cycle:

| Contract                                | Status                                         | Evidence                                                                                                                                                          |
| --------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R53-F** "no config-value passthrough" | ✅ preserved                                   | `system_health()` body still doesn't touch `get_config()`; metrics endpoint also via module-level helpers; `network_security` filtered from both `get_all()` paths |
| **R120** silent-failure baseline        | ✅ baseline +2 sites (29 → 31, both `[R-186]`) | New TaskQueue / recent-logs `except Exception: pass` in `_render_prometheus_metrics`; baseline JSON updated in R186 commit; no `# noqa` workarounds              |
| **R121-A** health payload whitelist     | ✅ unchanged                                   | No health-payload field changes; metrics endpoint is a separate URL (`/metrics`) and is not bound by R121-A                                                       |
| **R178** docs i18n lockstep             | ✅ all 4 layers synced                        | EN+ZH pairs for `configuration` (T1/T3/T4), new `mcp_tool_call_metrics` API docs (T2)                                                                            |
| **R19.1** tag-push safety               | ✅ unchanged                                   | No changes to `check_tag_push_safety.py` this cycle                                                                                                              |
| **R47** SSE stats route                 | ✅ unchanged + regex hardened                  | `test_runtime_counters_r47.py` `end_marker` regex updated from `open-config-file/info` → `health` (R188 commit) to keep test scope tight after new endpoints     |
| **R168** docs `*.tmp.md` exception      | ✅ generalized to `*.tmp.*`                    | `.gitignore` broadened to `*.tmp.*` with `!docs/**/*.tmp.md` exception preserved; verified by `git check-ignore`                                                 |
| **(NEW) Prometheus HELP/TYPE dedup**    | ✅ established                                 | `_format_prom_metric_family` emits HELP/TYPE exactly once per family; permanent regression guard in `test_mcp_tool_call_metrics_r187.py`                         |
| **(NEW) Loopback-OR-token gate**        | ✅ established                                 | `_is_authorized()` in `system.py` is the single chokepoint; 3 endpoints upgraded; 28-case test suite locks in matrix behavior                                    |

## 6 CHANGELOG audit

CHANGELOG entries this cycle:

- ✅ `Added: R186 / T1 — Prometheus exposition + gitignore + R120 baseline` (80be6a2)
- ✅ `Added: R187 / T2 — MCP tool call counter + R186 HELP/TYPE dedup fix` (9ac2090)
- ✅ `Added: R188 / T3 — Runtime log-level dial + R47 test regex fix` (c6d690f)
- ✅ `Added: R189 / T4 — Optional API token authentication + non-loopback hardening` (a58ce39)

All entries live under `## [Unreleased]`, none touch the released
`## [v1.7.0]` region (the CR#16 F-4 diff-scope hook would have
blocked us). Each entry follows the **"context / design / boundary /
test coverage / files touched"** template that's matured across CR#15
through CR#17. Verbose but **searchable**: a future bug report
referencing "the duplicate HELP line issue" will land directly on
the R187 entry via Ctrl-F.

**Audit clean.**

## 7 Suggested follow-ups (ordered)

Cycle 5 candidate work, ranked by user-visible operational impact:

1. **Foundational · Histogram support in `_format_prom_metric_family`**
   (CR#18 §4.6). Unlocks all latency / size / depth distributions.
   _est. 3h, blocks 2 + 3._

2. **R190 (proposed) · `aiia_mcp_tool_call_duration_seconds` Histogram**
   (§4.1). Dashboard "is the feedback loop getting slower" requires
   this. _est. 1h after (1) lands._

3. **R191 (proposed) · `aiia_notification_send_duration_seconds`
   per-provider Histogram**. Same pattern as (2) for notifications.
   _est. 1h after (1) lands._

4. **R192 (proposed) · SSE event for `logger-level-changed`** (§4.3).
   Multi-operator coordination + activity dashboard banner.
   _est. 45m._

5. **R193 (proposed) · `network_security` section cache eager
   invalidation on hot-reload** (§4.5). Closes the 30s
   token-rotation overlap window. _est. 30m._

6. **R194 (proposed) · `api_token` hot-reload regression test** (§4.4
   item (a)). Confirms file-watcher catches token changes.
   _est. 30m, runnable in parallel with (5)._

7. **R195 (proposed, low priority) · `POST /api/system/rotate-api-token`**
   (§4.4 item (b)). Loopback-only token mint + config write. _est. 2h._

Total cycle-5 estimate if all 7 land: ~9h. **Recommended slate**:
(1), (2), (5), (6) for a focused ~5h cycle that ships latency
visibility + rotation safety. Defer (3), (4), (7) to cycle 6.

## 8 Versioning recommendation

Cumulative public-surface changes added since v1.7.0:

- **New HTTP endpoints**:
  - `GET /api/system/metrics` (Prometheus exposition, R186)
  - `GET /api/system/log-level` (current level + valid enum, R188)
  - `POST /api/system/log-level` (runtime dial, R188)
- **New MCP middleware**:
  - `ToolCallCounterMiddleware` registered in `server.py` chain (R187)
- **New config field**:
  - `[network_security].api_token` (R189) — opt-in, default `""`
- **New behavior on existing endpoints** (R189):
  - `POST /api/system/open-config-file` — now accepts Bearer token
  - `GET /api/system/open-config-file/info` — now accepts Bearer token

This is **materially MINOR-worthy by SemVer**. The endpoints are
all additive (no breaking changes to existing routes); the config
field is opt-in (empty default preserves all v1.7.0 behavior); the
middleware is observability-only (counters, no observable side
effects in the request/response path).

**Recommendation**: cut `v1.7.1` after CR#19 / cycle 5 drains at
least the foundational histogram work (item 1) — a "v1.7.1
observability stack" framing tells operators "this is the release
where Prometheus latency dashboards become possible". Alternatively,
hold for `v1.8.0` once the full CR#19 slate lands.

**Preferred**: `v1.7.1` after foundational histogram + R190 / R191
ship (items 1-3 from §7), so the version bump tells a coherent
story ("observability completion").

---

_Authored 2026-05-13. Archive this file when v1.7.1 is cut,
mirroring the CR#15 / CR#16 / CR#17 archival pattern._
