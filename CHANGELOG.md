# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Earlier history (versions ≤ 1.5.19) lives in the git log only.

## [Unreleased]

### Tooling

- **VSIX size budget guard added to the packaging script.**
  `scripts/package_vscode_vsix.mjs` now reads the post-package
  `.vsix` byte size and applies a two-tier check: WARN at 4 MB
  and FAIL (`process.exit(1)`) at 6 MB packed. Current 1.5.x
  ships at ~2.7 MB packed, so both thresholds leave generous
  headroom for normal feature work but trip immediately if a
  bundle accident (e.g. shipping the entire `mathjax/` tree
  uncompressed, or pulling a heavy npm dep transitively into
  the webview) pushes the artifact into the multi-MB range.
  Defaults can be overridden via
  `AIIA_VSCODE_VSIX_WARN_PACKED_MB` /
  `AIIA_VSCODE_VSIX_MAX_PACKED_MB` for one-off intentional
  jumps. Companion `tests/test_vscode_vsix_size_budget.py`
  statically locks the default constants in the [1, 50] MB
  sane range and asserts WARN ≤ FAIL, so a reviewer cannot
  silently disarm the guard by raising the default to 100 MB.
- **Shebang ↔ executable-bit invariant is now enforced.**
  Two layers:
  1. **Repo-wide cleanup**: 6 top-level library modules
     (`config_manager.py` / `config_utils.py` /
     `file_validator.py` / `notification_manager.py` /
     `notification_models.py` / `notification_providers.py`)
     and 14 test files (`tests/test_*.py`) carried a
     leftover `#!/usr/bin/env python3` shebang despite never
     being entry-points — pytest is the sole driver for
     tests, and the library modules are imported, never
     executed. Shebangs removed; `if __name__ == "__main__":
     unittest.main()` blocks already in tests still work
     when invoked via `python -m`.
  2. **Mode normalisation**: 16 entry-point scripts under
     `scripts/` (`ci_gate.py`, all 9 i18n gates,
     `bump_version.py`, `generate_docs.py`,
     `minify_assets.py`, `manual_test.py`,
     `test_mcp_client.py`, `red_team_i18n_runtime.mjs`,
     plus `run_coverage.sh`) were tracked as `100644` even
     though their shebangs implied `chmod +x` —
     `./scripts/run_coverage.sh` would fail with
     `permission denied` on a fresh clone (despite
     `scripts/README.md` documenting that exact
     invocation). Re-tracked as `100755`.
  3. **Pre-commit gate**: two new
     `pre-commit/pre-commit-hooks` hooks
     (`check-shebang-scripts-are-executable` +
     `check-executables-have-shebangs`) prevent both
     directions of drift in future PRs.

### Documentation

- **Cross-links between `SECURITY.md` and the VS Code
  README's AppleScript executor section.** Both bilingual
  `SECURITY.md` "Out of scope" entries already named the
  AppleScript executor as a deliberately-local subsystem,
  but did not point readers at the place where the seven
  safeguards (platform check, absolute binary path, stdin
  delivery, hard timeout, output cap, log redaction, no
  user-supplied scripts) are enumerated. Conversely, the
  `packages/vscode/README{,.zh-CN}.md` security-model
  sections did not flag the private-advisory reporting
  contract for issues found in that very surface — a tiny
  hole that could lead a security researcher to
  accidentally drop a public issue. Added bidirectional
  references in plain language (no anchors, since the
  GitHub slug for `## AppleScript executor (macOS only) ·
  security model` is brittle across renderers); each side
  now nudges to the right document for the other half of
  the contract. Pure docs / no behaviour change.
- **`docs/mcp_tools{,.zh-CN}.md` timeout description matches
  the runtime `_clamp_int` bounds.** The "Notes on
  timeouts" section quoted `feedback.frontend_countdown`'s
  range as "default 240s, max **250s**" — but the actual
  v1.5.x clamp is `[10, 3600]s` (with `0` / non-positive
  integers disabling the countdown), and `backend_max_wait`
  is `[10, 7200]s`. Reading the wrong upper bound led at
  least one issue (#xxx) to assume the long-running tool
  capped at ~4 min when it really tolerates a full hour.
  Updated both bilingual mentions to expose the actual
  ranges and the disable-countdown semantic. Companion
  `tests/test_config_docs_range_parity.py` (introduced in
  the same release window) already enforces the
  `docs/configuration{,.zh-CN}.md` table; this commit
  catches up the secondary mention in `docs/mcp_tools*.md`.
- **README badges advertise the CodeQL workflow alongside
  OpenSSF Scorecard.** `.github/workflows/codeql.yml` has
  been running on every push / PR / weekly schedule for
  several minor releases, but neither English nor Chinese
  README surfaced its pass/fail state — only the Scorecard
  badge made the security workflow chain visible to
  visitors. Both READMEs now carry a CodeQL badge in the
  same row, signalling that static analysis is
  continuously enforced.
- **API reference now covers every project-root `*.py`
  module (23 of 23, was 14).** Round-8/9 audit discharged
  the 9-entry documentation backlog by graduating
  `server.py`, `web_ui.py`, `server_feedback.py`,
  `service_manager.py`, `web_ui_security.py`,
  `web_ui_validators.py`, `web_ui_config_sync.py`,
  `web_ui_mdns.py`, and `web_ui_mdns_utils.py` over four
  sequential commits (one per surface, plus a final
  6-module batch). Each commit moved the module name from
  `IGNORED_MODULES` to `MODULES_TO_DOCUMENT` in
  `scripts/generate_docs.py`, placed it in
  `QUICK_NAV_CORE` or `QUICK_NAV_UTILITY` based on whether
  it owns a public contract or is internal plumbing,
  regenerated the bilingual `docs/api(.zh-CN)/` pages
  (English signature-only, Chinese full-docstring), and
  refreshed `docs/api(.zh-CN)/index.md` plus the
  bilingual `docs/README{,.zh-CN}.md` cross-links. The
  classification invariant established in the same wave
  (see Tooling) prevents future modules from slipping in
  undocumented; `IGNORED_MODULES` is now an empty
  `frozenset[str]` for the first time in the v1.5.x line.
  Per-locale page count: 14 → 23. No source-side change
  in any graduation commit; the new pages render existing
  module/function docstrings as-is.

### Tooling

- **`scripts/generate_docs.py` now refuses to ship an
  `index.md` whose Quick navigation grouping does not cover
  every entry in `MODULES_TO_DOCUMENT`.** Promotes the two
  hand-curated lists to module-level constants
  (`QUICK_NAV_CORE` + `QUICK_NAV_UTILITY`) and asserts their
  union equals the rendered set on every `generate_index`
  call. Fail-fast on missing/extra entries with an actionable
  error message instead of silently emitting an asymmetric
  index.
- **`scripts/bump_version.py` now also synchronises
  `CITATION.cff::version`** — the script previously walked
  six version-bearing files (`pyproject.toml`, `uv.lock`,
  `package.json`, root + nested `package-lock.json`,
  `packages/vscode/package.json`,
  `.github/ISSUE_TEMPLATE/bug_report.yml`) but **silently
  skipped** `CITATION.cff::version`. After running
  `uv run python scripts/bump_version.py 1.5.23`, the
  citation file would still report `version: "1.5.22"` to
  Zenodo / academic citation tooling — and `--check` would
  not catch the drift. Added a third helper pair
  (`_extract_citation_version` / `_update_citation_version`)
  that rewrites only the top-level `version: "X.Y.Z"` line
  (anchored at line start, so `cff-version: 1.2.0` stays
  put), preserves `date-released` and the rest of the file
  byte-for-byte, and is idempotent. The dry-run output and
  `--check` validation pass have been extended to mention
  CITATION.cff. Companion test (`tests/test_bump_version_citation.py`,
  13 cases) covers extraction edge cases (pre-release tags,
  build metadata, missing field), single-line replacement
  contract, and a real-repo sanity parse.
- **`docs/api(.zh-CN)/*` drift detection promoted from
  warn-level to fail-closed in `scripts/ci_gate.py`.** The
  round-6 audit caught `docs/api/task_queue.md` (English) one
  round behind the Chinese mirror after a DRY refactor of
  `task_queue.add_task` — the warn signal had been emitting
  across multiple CI runs without action. Both
  `generate_docs.py --lang {en,zh-CN} --check` invocations
  now use the fail-closed `_run` helper with a `label`
  suffix in the failure message that points at the exact
  remediation command. An inline comment in `ci_gate.py`
  preserves the upgrade rationale so future maintainers do
  not regress to warn-level.
- **Local-CI parity holes closed for two pre-existing
  scripts.** Two maintenance scripts that had lived under
  `scripts/` but were never wired into `scripts/ci_gate.py`
  are now fail-closed gates, so `make ci` /
  `make pre-commit` finally surface them:
  - `scripts/check_locales.py` covers two locale surfaces
    that the primary `check_i18n_locale_parity.py` does not
    touch — VS Code manifest translations
    (`packages/vscode/package.nls{,.zh-CN}.json`) and
    cross-platform `aiia.*` namespace alignment between
    Web UI (`static/locales/`) and the VSCode webview
    locale bundles. Without it, a missing key in the
    manifest meant commands/views showed as raw `%key%`
    placeholders in one language at install time, with
    zero CI signal.
  - `scripts/bump_version.py --check` runs the
    eight-file version-sync invariant
    (`pyproject.toml`/`uv.lock`/`package.json`/`package-lock.json`
    × {root, plugin}, `bug_report.yml`, `CITATION.cff`)
    locally instead of only in the GitHub Actions matrix
    (Python 3.11 slice). Local pre-flight signal now
    matches remote CI signal exactly; the test.yml step
    is preserved as a defensive second layer.
- **`scripts/minify_assets.py --check` switched from mtime
  heuristic to byte-level content comparison.** The
  previous `src.stat().st_mtime > dst.stat().st_mtime`
  test produced 100% false positives on fresh CI runners
  and after every `git checkout` (because checkout resets
  working-tree mtimes). New
  `content_drifts(src, dst, minify_func)` actually runs the
  minifier and byte-compares the output to the on-disk
  `.min.{js,css}`, reporting drift only when contents
  differ. Missing destination or minifier exception are
  both treated as drift so CI surfaces problems instead of
  silently fixing them. Default execution mode (no flag)
  keeps the mtime fast-path for incremental local
  rebuilds. 7 unit tests
  (`tests/test_minify_assets_helpers.py`) lock the new
  contract, including a reverse-lock that fails if a
  future contributor wires `needs_minification` back into
  the `--check` path.
- **`scripts/ci_gate.py` no longer silently skips the
  Node-driven i18n red-team smoke when `node`/`fnm` is
  absent.** The runtime gate
  (`scripts/red_team_i18n_runtime.mjs`, runs the bilingual
  locale bundles end-to-end through the actual `Intl`
  pipeline) historically printed a single "skip" line and
  exited 0 on machines without Node, so a CI runner that
  lost Node mid-upgrade would go silently green. Decision
  logic extracted into a new helper
  `_resolve_node_redteam_cmd(node_version)` that returns a
  command list when `fnm`/`node` is available and an empty
  list otherwise; `ci_gate` now raises `RuntimeError` on the
  empty case unless the operator explicitly opts out via
  `AIIA_SKIP_NODE_REDTEAM=1`. 5 unit tests
  (`tests/test_ci_gate_node_redteam.py`) lock the four
  branches plus a stability assertion on the `_run_warn`
  signature.
- **Top-level Python module classification invariant
  (`scripts/generate_docs.py`).** Introduces a new
  `IGNORED_MODULES: frozenset[str]` constant — initially
  populated with the 9 root `*.py` modules that had no
  generated docs (`server`, `web_ui`, `server_feedback`,
  `service_manager`, `web_ui_security`,
  `web_ui_validators`, `web_ui_config_sync`,
  `web_ui_mdns`, `web_ui_mdns_utils`) plus per-module
  `TODO(round-8/docs-debt)` markers explaining the
  rationale — and adds the
  `_assert_top_level_modules_classified()` invariant
  called from `generate_index()`. The invariant rejects
  any unclassified `*.py` (must appear in
  `MODULES_TO_DOCUMENT` xor `IGNORED_MODULES`) and any
  overlap between the two sets. 5 introspection-based
  unit tests
  (`tests/test_docs_module_classification_parity.py`)
  cover the full state machine plus a `TODO`-marker
  contract for any non-empty `IGNORED_MODULES`.
  Round-8/9 then graduated all 9 entries in three
  sequential commits (`server.py`, `web_ui.py`,
  `server_feedback.py`, then a final batch of 6:
  `service_manager.py`, `web_ui_security.py`,
  `web_ui_validators.py`, `web_ui_config_sync.py`,
  `web_ui_mdns.py`, `web_ui_mdns_utils.py`). Each
  graduation moves the module name from
  `IGNORED_MODULES` to `MODULES_TO_DOCUMENT`, places it
  in `QUICK_NAV_CORE` or `QUICK_NAV_UTILITY` based on
  whether it owns a public contract or is internal
  plumbing, regenerates the bilingual `docs/api(.zh-CN)/`
  pages, and refreshes `docs/api(.zh-CN)/index.md` plus
  the bilingual `docs/README{,.zh-CN}.md` cross-links.
  `IGNORED_MODULES` is now an empty `frozenset[str]`
  (typed annotation preserved with a docstring marking
  the contract for any future re-population). Per-locale
  page count climbs from 14 to 23. No source-side change
  in any graduation commit; the pages render existing
  docstrings only.
- **`SystemNotificationProvider`'s plyer `timeout` magic
  number now lives in `_DISPLAY_DURATION_SECONDS`** (= 10s)
  with a fully documented contract that the value is the
  *banner display duration*, not a *send timeout*. Historical
  bug-magnet: the previous local variable name
  ``timeout_seconds = 10.0`` strongly suggested send-side
  semantics. plyer has no async/cancellation surface; the call
  is synchronous and blocks until the platform API returns
  (osascript / balloon / libnotify). The fallback for an
  actually-stuck platform call is
  ``NotificationManager._process_event::as_completed(timeout=
  bark_timeout + buffer)``, which is now explicitly cross-
  linked in both source files. Locked by
  ``tests/test_notification_providers.py::TestSystemProviderSend``
  (2 new tests including a `[3, 30]` range justification on
  the constant).

### Tooling

- **`LogDeduplicator` now reaps expired cache entries on the cache-hit
  path, not just on cache miss.** Pre-fix, `_cleanup_cache` only ran
  inside the cache-miss branch — so if the runtime hits a stable
  steady state where one hot ERROR keeps re-firing and getting
  deduped (cache hit branch), the other 999 entries already older
  than `time_window` would never be reaped. Not a true memory leak
  (the `max_cache_size = 1000` ceiling still applies), but a
  correctness violation: a "5-second dedup window" should mean
  expired entries drop within ~5 s, not "whenever the next miss
  happens to fire — which might be never". The hash-table also
  stayed permanently near the cap, lengthening probe chains for
  every subsequent `in self.cache` lookup on the hot path. New
  behaviour: lazy-cleanup token
  (`_LAZY_CLEANUP_INTERVAL_SECONDS = 30.0`, 6 × default `time_window`
  = ≤ 2 stale windows of residency); both `should_log` paths now
  check `current_time - self._last_cleanup_time >= interval` and
  drain expired entries on the way through. `_last_cleanup_time`
  initialised to `0.0` so the very first call always settles a
  real `time.monotonic()` baseline (without it, every call in the
  first 30 s would re-trigger cleanup, the inverse degenerate
  case). Three locks in
  `tests/test_enhanced_logging.py::TestLogDeduplicatorLazyCleanupOnHit`:
  behavioural test injects 9 stale entries, hammers a hot key while
  sleeping past `time_window`, asserts cache shrinks to ≤ 1 entry
  on next hit; constant-range invariant
  `5.0 <= _LAZY_CLEANUP_INTERVAL_SECONDS <= 120.0`; and first-call
  baseline guard that prevents perpetual cleanup.
- **`NotificationManager.shutdown` gains a `grace_period` knob and
  `atexit` now uses a 1.5 s grace window.** Pre-fix, `atexit` called
  `shutdown(wait=False)`, which cancelled pending futures but did
  nothing for already-running ones — meanwhile the worker threads are
  non-daemon, so a wedged `osascript`/Bark/钉钉 HTTP call could keep
  the interpreter alive long after `sys.exit` / Ctrl-C, with stdout
  half torn down and atexit hooks already gone. New signature:
  `shutdown(wait=False, grace_period=0.0)` — default `0.0` is a perfect
  no-op for existing callers; positive values trigger a
  `for thread in self._executor._threads: thread.join(timeout=remaining)`
  pass under a `time.monotonic()` deadline, so the *total* wait is
  bounded by `grace_period` regardless of how many workers are still
  running (4 stuck workers ≠ 4 × grace; the budget is shared).
  `_ATEXIT_GRACE_PERIOD_SECONDS = 1.5` is the picked value: short
  enough that humans don't perceive a quit hang, long enough to cover
  one full HTTP request round-trip (typical 200–800 ms). Why not
  `daemon=True`: would require subclassing `ThreadPoolExecutor` and
  reimplementing `_adjust_thread_count` (private, churns across CPython
  3.9–3.13); `grace_period` only *reads* `_threads`, never mutates the
  pool, and survives a hypothetical CPython removal via the
  `getattr(..., ()) or ()` fallback. Eight locks in new
  `TestShutdownGracePeriod`: `grace=0` doesn't touch `_threads`,
  `grace>0` joins every worker exactly once with positive
  `timeout <= grace`, `wait=True` ignores grace (no double-wait),
  shared deadline budget bounds total elapsed, single `thread.join`
  exception is swallowed (atexit must not raise), missing `_threads`
  attribute is safe, `_ATEXIT_GRACE_PERIOD_SECONDS ∈ (0, 5)` (reverse-
  locked), and the signature keeps `grace_period=0.0` default.
- **`server.main()` MCP-restart loop now uses capped exponential
  backoff + jitter instead of `time.sleep(1)` between every retry.**
  The original loop slept exactly 1.0 s between every restart attempt;
  if a user runs the same `ai-intervention-agent` MCP server from
  multiple IDE clients on the same machine (Cursor + VS Code is the
  common combo, but also IDE multi-workers / browser automation that
  spawns its own MCP child), an upstream blip that knocks all of them
  over at once will lockstep them through retries — every instance
  wakes within the same ~10 ms window, hammers whatever resource just
  recovered, and amplifies the original blip into a denial-of-recovery
  loop. Classic thundering-herd reproduction. Replaced with
  `delay = min(base × 2^(n-1), 4.0) + uniform(0, base × 0.5)` per AWS
  Architecture Blog "Exponential Backoff and Jitter" / Google SRE
  Workbook §22; first retry sleeps `[1.0, 1.5)` s, second sleeps
  `[2.0, 3.0)` s, cap stays harmless at `MAX_RETRIES = 3` but is
  future-proof if the ceiling ever rises. Six locks in
  `tests/test_server_main_retry_backoff.py`: four AST/source-text
  invariants (`2 **`, `random.uniform`, `min(...)`, no hardcoded
  `time.sleep(1)`/`time.sleep(2)`) and two behavioural ones that drive
  `server.main()` with mocked `mcp.run` — first verifies retry 2 is
  *strictly greater* than retry 1 (rejects jitter-coincidence false
  positives), second verifies `KeyboardInterrupt` still bypasses both
  `time.sleep` and `sys.exit`.
- **`/api/events` SSE endpoint now declares an explicit
  `@limiter.limit("300 per minute")` instead of inheriting the global
  default `60/min`.** Reproducer: open the Web UI, do a brisk
  `Cmd+R`/`F5` cycle 5–10 times in 30 s (also happens on flaky LAN
  where the browser auto-reconnects EventSource). Pre-fix the limiter
  starts returning 429 to the SSE handshake; `EventSource.onerror`
  kicks in, the `multi_task.js` polling fallback takes over, and the
  observer blames the SSE pipeline rather than the limiter that
  rejected it. New `300/min` matches the `/api/tasks` neighbour
  endpoint, leaves multiple browser tabs and reconnect bursts breathing
  room, and intentionally avoids `@limiter.exempt` so a misbehaving
  client can't open unbounded connections to drain the per-subscriber
  queue. Three AST-driven locks in
  `tests/test_sse_endpoint_rate_limit.py`: `def sse_events` exists,
  has exactly one `@self.limiter.limit(...)` decorator with
  `"300 per minute"`, and is *not* `@limiter.exempt`. Future refactors
  that drop the explicit limit (regressing to `60/min`) or upgrade to
  `exempt` (unbounded connections) both fail the test with a direct
  pointer to this commit's rationale.
- **`wait_for_task_completion` now retries `_fetch_result()` once
  before `_close_orphan_task_best_effort()` so a transient SSE-
  completion + fetch-jitter race no longer permanently deletes a
  user's already-submitted feedback.** Pre-fix race window: SSE
  reports `task_changed(new_status=completed)` while the user's
  result is already written to `task_queue` → `_sse_listener`
  calls `_fetch_result()` to grab the payload → that GET hits a
  transient 503 / ConnectError / DNS jitter (cross-region cellular
  handoff, proxy returning 502 mid-TLS-cert-rotation, momentary
  `httpx.AsyncClient` pool eviction) → `_fetch_result` returns
  `None` from its broad `except Exception` branch → `completion.set()`
  fires regardless → finally checks `result_box[0] is None` → True
  → `_close_orphan_task_best_effort()` POSTs `/api/tasks/<id>/close`
  → web_ui `task_queue.remove_task` deletes the COMPLETED task
  **and its `result` payload** → user receives a `_make_resubmit_response`
  back through the AI, with zero log signal that a result *did*
  exist briefly. Fix is a single retry hop in the same finally
  block: if `result_box[0] is None` after both SSE / poll tasks
  have been awaited, call `_fetch_result()` once more — transient
  failures typically clear in <1 s, so the retry recovers the
  result, fills `result_box[0]`, and the existing `if result_box[0]
  is None` close-guard short-circuits past the close call entirely.
  If the retry *also* fails (genuinely no result, web_ui truly
  wedged), control flows into the original R13·B1 close path with
  behaviour bit-identical to pre-fix — no regression for the
  timeout / genuinely-stuck scenarios the original commit was
  written for. The post-finally line-230 `_fetch_result()` is
  preserved as a third-tier fallback for the rare case where
  `_close_orphan_task_best_effort` raised `CancelledError` yet
  the task was never actually closed (its role is largely subsumed
  by the new retry but it's free defence-in-depth). Three new
  locks in `TestRetryFetchBeforeClose`:
  `test_retry_recovers_result_skips_close` drives the exact race
  with a stateful `AsyncMock` GET (1st → 503, 2nd → completed
  result) and asserts (a) the return value is the recovered result
  not `_make_resubmit_response`, (b) `client.post` (close) is
  called *zero* times, (c) GET is called ≥ 2× to confirm the
  retry fired; `test_retry_still_failing_falls_back_to_close`
  preserves the always-pending case and confirms `client.post`
  *is* called at least once;
  `test_retry_does_not_fire_when_result_already_present` reverse-
  locks the normal completion path so a future refactor moving
  the retry outside the `is None` guard cannot silently overwrite
  a legitimately-obtained result. Pytest count 2452 → 2455.
- **`NotificationManager.ThreadPoolExecutor(max_workers=...)` now
  binds to `len(NotificationType)` (currently 4) instead of a
  hardcoded `3`, closing a "全开" user's silent notification drop.**
  Pre-fix, both `__init__` and the `restart()` recreate-pool path
  created the executor with `max_workers=3` plus a comment claiming
  "通常同时启用的渠道不超过 3 个" — but
  `notification_models.NotificationType` actually enumerates 4
  members (`WEB`/`SOUND`/`BARK`/`SYSTEM`). Reproducer: a user with
  `web_enabled=True` + `sound_enabled=True` + `bark_enabled=True` +
  system available submits a feedback → `_process_event` iterates
  `event.types` (4 items) and `submit()`s 4 futures into a 3-worker
  pool. The 4th future enters the executor's queue waiting for a
  free worker, but
  `as_completed(futures, timeout=bark_timeout +
  _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS)` (default 10+5 = 15 s) starts
  ticking *immediately* on submit, not when the 4th worker
  eventually starts. If the 3 in-flight futures (typically
  dominated by BARK's HTTPS round-trip with cross-region latency)
  all finish near the 15 s edge, the 4th future has zero remaining
  time, never gets dispatched, and is force-cancelled in the
  `except TimeoutError` branch's cleanup loop — the user simply
  doesn't get one of their notifications, and the only log signal
  is a generic "通知发送部分超时: N/M 完成" warning that doesn't
  reveal the *systematic* shortfall (this channel **always** loses
  to scheduling order, not random network luck). New module-level
  `_NOTIFICATION_WORKER_COUNT = len(NotificationType)` makes the
  worker count auto-sync with the enum; future contributors adding
  a 5th channel just add a member to `NotificationType` and the
  executor's capacity grows automatically, with zero hardcoded
  constants to forget. Both `__init__` and `restart()` reference
  the same constant, eliminating the historical drift class where
  one path got updated and the other didn't. Resource impact is
  essentially zero: `ThreadPoolExecutor` lazily spawns workers
  (`_adjust_thread_count` only creates threads on
  `submit()`-with-backlog), so 3→4 doesn't pre-allocate anything;
  per-thread overhead (~8 KB stack + Python frame) is negligible
  next to interpreter baseline. Five new locks in
  `TestWorkerCountMatchesNotificationTypes`:
  `_NOTIFICATION_WORKER_COUNT == len(NotificationType)` (the
  auto-sync invariant); `_NOTIFICATION_WORKER_COUNT >= 4` (hard
  floor — shrinking the enum to 3 must be conscious, not silent);
  live executor's `_max_workers` after `__init__` matches the
  constant; live executor after `shutdown(wait=False) → restart()`
  also matches (locks the dual-path parity that historically
  diverged); AST reverse-lock walking
  `NotificationManager.__init__` + `restart()` via
  `inspect.getsource` + `ast.parse`, asserting no
  `Call(func=ThreadPoolExecutor, keywords=[..., max_workers=
  Constant(3)])` survives (chose AST over textual grep because
  textual grep false-positives on test fixtures and changelog
  quotes). Pytest count climbs 2447 → 2452.
- **`TaskQueue._persist` now `flush()`es and `fsync()`s before
  `os.replace()` so a kernel panic / power loss after rename can no
  longer leave the on-disk task-queue file as NUL-filled or
  truncated bytes.** Pre-fix, `_persist` did `tempfile.mkstemp →
  write → os.replace` without flushing the stdio buffer or fsyncing
  the file descriptor; `os.replace` is atomic at the rename(2)
  / inode level (the kernel guarantees old-name → new-name flips
  atomically), but it commits *only the rename metadata* — the
  *file's actual data bytes* may still be in the OS page cache,
  never written to the storage device. Crash window: if the machine
  panics or loses power *after* `os.replace` has rewritten the
  directory entry but *before* the OS journal flushes the new
  inode's page cache, the post-recovery on-disk state is "directory
  entry points at the new file" + "new file content is whatever
  zero-fill / partial-write the storage controller decided" + "old
  file is gone forever (rename consumed it)" — strictly worse than
  the no-atomic-write naive case where the old file would have
  survived. Canonical "atomic-write footgun" documented in the Linux
  fsync(2) man page, danluu.com/file-consistency, the LWN
  "ext4-and-data-loss" post, and the Postgres `fsyncgate`
  post-mortem. Crucially, this repo *already has* 5 other
  atomic-write paths that all do `flush + fsync + replace` correctly
  (`config_manager._save_config_immediate`,
  `config_modules/io_operations.py`,
  `config_modules/network_security._atomic_write_config`,
  `scripts/bump_version.py`); `task_queue._persist` was the one
  outlier, and its docstring even claimed "原子操作：tmpfile →
  os.replace" — giving readers a false sense of correctness. New
  sequence: `f.write → f.flush() → os.fsync(f.fileno()) →
  os.replace()`. Why both `flush` *and* `fsync`: `flush()` pushes
  the Python stdio buffer down to the kernel page cache; `fsync()`
  pushes the kernel page cache down to the storage device. Flush
  alone leaves data in the page cache (kernel may delay writeback
  by minutes); fsync alone may miss the tail of the stdio buffer
  that hasn't been flushed yet. Why *not* also `fsync(parent_dir_fd)`
  — which would additionally guarantee the rename's directory-entry
  change is flushed: the other 5 atomic-write paths in this repo
  don't do directory fsync either, and adding it only here would
  create *worse* inconsistency — if directory fsync becomes the bar,
  all 6 paths should be upgraded together in a separate commit.
  Five new locks in `tests/test_task_queue_persist_fsync.py`:
  `TestPersistFsyncContract::test_persist_calls_fsync_before_replace`
  (syscall-order trace via `patch(side_effect=...)` asserting
  `fsync` precedes `replace` — without it a "fsync after replace
  as cleanup" refactor would silently regress);
  `test_persist_calls_flush_before_fsync` (source-text inspection
  of `f.flush()` < `os.fsync(f.fileno())` index, blended with
  behavioural fsync→replace assertion — `MagicMock(spec=StringIO)`
  was rejected because ty's strict-shadow check forbids implicit
  instance-method override of `StringIO.flush`);
  `test_fsync_failure_does_not_replace` injects `OSError("simulated
  EIO")` into `os.fsync` and asserts (a) `os.replace` is *never*
  called and (b) the on-disk byte content is bit-identical to
  before — the critical fail-loud property that prevents the "fsync
  failed AND replace ran" double-failure mode where the user loses
  *both* old and new data;
  `TestPersistAtomicWriteParity::test_targeted_functions_have_flush_and_fsync_before_replace`
  is AST-driven cross-file invariant checking against
  `task_queue.TaskQueue._persist` AND
  `config_manager._save_config_immediate` (the two class-method /
  module-level representatives of the atomic-write idiom),
  asserting all three tokens (`.flush()`, `os.fsync(`,
  `os.replace(`) appear in each function source — without this
  static check, a future copy-paste of `_persist` into another
  module could silently lose `fsync`; `test_persist_signature_unchanged`
  reverse-locks `inspect.signature(TaskQueue._persist).parameters
  == ["self"]` so a future "let's parameterize fsync behaviour"
  refactor (e.g. adding `no_fsync=True`) fails immediately —
  parameterized fsync = optional fsync = back to the bug. Full
  pytest count climbs from 2442 → 2447 (+5, no regressions). API
  docs unchanged: `_persist` is private and doesn't appear in
  `task_queue.md`.
- **`start_web_service` now fails fast on port conflict
  (`code="port_in_use"`) instead of waiting 15 s for a misleading
  `start_timeout`.** Pre-fix, when the configured port (default
  `8080`) was already held by another process, the spawned subprocess
  exited immediately with `OSError: [Errno 48] Address already in
  use`, but `start_web_service` would happily wait the full
  `max_wait = 15 s` health-check loop before raising
  `ServiceTimeoutError(code="start_timeout")` — a misleading
  "service is slow to start" diagnosis when the actual root cause is
  a hard, deterministic port collision. Troubleshooting docs even
  called this out as a known papercut. New module-private
  `_is_port_available(host, port)` performs a pre-flight
  `socket.bind` (with `SO_REUSEADDR` so `TIME_WAIT` doesn't trigger
  a false positive) right *after* the existing `health_check_service`
  short-circuit, so the "our own healthy service is already
  listening" path is unchanged (we'd otherwise spuriously self-fail
  every restart, since pre-flight bind would fail against our own
  listener). When the port is genuinely owned by another process,
  `start_web_service` raises
  `ServiceUnavailableError(code="port_in_use", ...)` containing
  `host:port` for log/UI surfacing, in milliseconds rather than 15
  seconds. There is a sub-millisecond TOCTOU window between
  pre-flight close and subprocess re-bind where another process
  could grab the port; in that case the existing `except Exception`
  Popen branch still produces a truthful `code="start_failed"`, so
  the worst case under contention is "as good as before" rather
  than "worse than before". Seven new locks in
  `tests/test_server_functions.py`: four direct contract tests in
  `TestIsPortAvailable` (free high port → `True`; bound listening
  socket → `False`; privileged port (`80`) → `False` with `EACCES`
  swallowed — skipped under `root` since root *can* bind 80; RFC
  5737 invalid host (`192.0.2.1`) → `False` with `EADDRNOTAVAIL`
  swallowed) and three integration tests in
  `TestStartWebServicePortInUse` (`port_in_use` raises *without*
  invoking `subprocess.Popen` — the entire point of pre-flight is
  fail-fast; error message contains both host and port for log/UI
  surfacing; reverse-lock that `health_check_service`'s short-
  circuit still wins over pre-flight — without that lock our own
  already-running healthy server would spuriously self-reject every
  restart attempt). The pre-existing 12 `TestStartWebService` cases
  now stub `_is_port_available = True` in `setUp` so they validate
  Popen / health-check / notification paths independent of whatever
  the dev's `8080` happens to look like at runtime — previously they
  passed only because the test machine's `8080` was empty. Why
  `socket.bind` instead of `socket.connect`: `connect` only tells
  you whether *something* answers TCP — it can't distinguish "port
  is free" from "port is bound but the holder hasn't `listen()`ed
  yet" (which would let a slow-listen race through pre-flight and
  *then* fail at Popen). `bind` directly probes "can this address
  family + port tuple be claimed", which is the property
  `subprocess.Popen` will need a moment later. Why not also
  `SO_REUSEPORT`: macOS / Linux disagree on its semantics (Linux
  load-balances incoming connections across listeners, macOS allows
  multiple bind-only-no-listen sockets), so leaving it off keeps
  pre-flight's verdict aligned with what the actual subprocess
  bind will see.

### Security

- **`X-XSS-Protection` flipped from `1; mode=block` to `0`; new
  `Cross-Origin-Opener-Policy: same-origin` header.** The legacy
  ``X-XSS-Protection: 1; mode=block`` was the late-2010s default,
  but the in-browser XSS auditor it activated was later shown to
  be exploitable as an *XSS oracle* (attackers steered the
  auditor to selectively delete legitimate scripts, opening a
  different attack surface; see Mozilla's deprecation note +
  Chrome's removal CVEs). Modern browsers ignore the header
  entirely, but IE11 and embedded-Chromium clients still honour
  ``1`` and run the auditor — a *negative* security delta on
  exactly the legacy stacks people deploy this header to protect.
  OWASP Secure Headers Project + Mozilla Observatory now both
  recommend explicit ``0`` ("CSP owns XSS defence here"). Our
  CSP remains nonce-only (``script-src 'nonce-...'``), so this is
  purely closing a residual auditor surface. Same commit adds
  ``Cross-Origin-Opener-Policy: same-origin`` (severs
  ``window.opener`` between cross-origin tabs, killing tabnabbing
  + ``window.opener.location = attacker_url`` redirects); zero
  legitimate use case for a cross-origin opener (VSCode webview
  is fully isolated via ``vscode-webview://``), so this is
  zero-cost hardening. Intentionally **not** adding
  ``Cross-Origin-Resource-Policy`` because the webview's fetch
  path lacks an explicit origin and CORP=same-origin would block
  legitimate ``vscode-webview://`` cross-origin loads. Six locks
  in new ``tests/test_security_headers_modern.py``: explicit
  ``"0"`` value present, every ``"1"``-prefixed variant absent
  (defends against typo-driven regression), COOP=same-origin
  present, COOP=unsafe-none rejected, plus two sanity guards
  that ``X-Frame-Options`` / ``X-Content-Type-Options`` /
  ``Referrer-Policy`` / ``Permissions-Policy`` / nonce-CSP all
  survive unchanged.
- **VSCode webview CSP nonce now uses Node CSPRNG (`crypto.randomBytes`)
  instead of `Math.random`.** Pre-fix, `getNonce` in
  `packages/vscode/webview.ts` sampled a 62-char alphabet × 32 chars,
  which **looks** like ~190 bits of entropy on paper but in practice
  draws every char from V8's `Math.random` — implemented as
  xorshift128+ with **53 bits of internal state**, publicly
  analysable, and predictable from a handful of observations.
  An attacker observing nonces emitted by a session could project
  the next ones with off-the-shelf tooling, regressing the
  `script-src 'nonce-${nonce}'` allowlist for inline `<script>`
  blocks back to effectively `script-src 'unsafe-inline'`. New
  implementation uses `crypto.randomBytes(16).toString('base64')`
  (Node CSPRNG → OS `getentropy` / `getrandom` / `BCryptGenRandom`,
  16 bytes = 128 bits real entropy, ≥ 2× the CSP3 §6 threshold of
  64 bits), matching the [vscode-extension-samples webview-sample](https://github.com/microsoft/vscode-extension-samples/blob/main/webview-sample/src/extension.ts)
  pattern verbatim. Four AST/text locks in
  `tests/test_csp_allows_importmap_nonce.py::TestNonceCsprngContract`:
  VSCode `getNonce` body must contain `crypto.randomBytes` AND must
  NOT contain `Math.random` or the legacy 62-char alphabet literal,
  the `import * as crypto from 'crypto'` line at file top is
  required (without it the new body is a `ReferenceError`, not a
  graceful failure), and the corresponding Python
  `web_ui_security.py` path must use `secrets.token_urlsafe(N≥16)`
  (rejecting `N=8` which would land exactly on the 64-bit threshold
  with zero safety margin).
- **NUL byte (`\x00`) in upload filenames promoted from `warnings` to
  `errors`.** `file_validator.FileValidator._validate_filename` previously
  routed `\x00` through `_DANGEROUS_CHARS`, producing only a warning while
  leaving `valid=True` for filenames like `image.png\x00.exe`. Filenames
  containing NUL have zero legitimate use and are the canonical
  C-string-truncation attack vector — any downstream that re-crosses a
  C boundary (OS path APIs, CGI forwarders, third-party libs that call
  into glibc) can have the name silently truncated to `image.png` and
  bypass the extension whitelist. Python 3's `open()` / `Path()` does
  raise `ValueError`, but enforcement should live at the validator gate,
  not be deferred to whichever downstream happens to fail first. Fix:
  `\x00` removed from `_DANGEROUS_CHARS` entirely and given a dedicated
  `errors.append(...)` branch with a precise "path-truncation 攻击向量"
  message. Three locks in `TestFilenameValidation`: mid-string NUL
  produces `valid=False`, leading NUL produces `valid=False`, and a
  reverse-lock asserts `\x00 not in FileValidator._DANGEROUS_CHARS`
  (defends against a "let's unify special-char handling" refactor that
  would silently demote NUL back to warning).
- **`/sounds/<filename>` route now enforces an explicit
  `.mp3`/`.wav`/`.ogg` extension whitelist.** Pre-fix the handler
  delegated entirely to `send_from_directory(sounds_dir, filename)`,
  which only blocks `..`-style traversal and otherwise streams *any*
  file inside `sounds/`. The directory currently holds a single
  `deng[噔].mp3`, but a future contributor dropping a `.json` config or
  `.txt` README in there would silently turn it into an HTTP-fetchable
  static asset (information disclosure with zero log signal). Fix
  mirrors the `/static/lottie/<filename>` idiom (`if not filename or not
  filename.lower().endswith((...)): abort(404)`), so the two static
  routes stay structurally aligned for future review. Three locks in
  `TestStaticRoutesEdge`: non-audio extensions (`.json`/`.txt`/`.env`/
  `.exe`) hit `abort(404)` before `send_from_directory` is consulted,
  uppercase `.MP3` passes the whitelist (defends the lower-cased
  `endswith` contract), and empty filename routes-to-308 / 404 from
  Flask's own routing (parity with `/static/lottie/`).
- **Server-side defense-in-depth caps on uploaded image count and total
  bytes.** `web_ui_routes/_upload_helpers.py::extract_uploaded_images`
  is the entry point for `/api/submit-feedback` and
  `/api/tasks/<id>/submit` image streams. The `static/js/image-upload.js`
  client side already capped `MAX_IMAGE_COUNT = 10` and
  `MAX_IMAGE_SIZE = 10 MB`, but the server side had no matching limits
  beyond `file_validator`'s per-file 10 MB check — a curl-based caller
  bypassing the client could push hundreds of images and let the
  process eat memory translating each into base64 + storing the
  validated copy in the queue. Added `MAX_IMAGES_PER_REQUEST = 10`
  (mirrors client) and `MAX_TOTAL_UPLOAD_BYTES = 100 * 1024 * 1024`
  (10 × per-file-cap). Both caps `continue` past offending fields
  rather than `break`-ing, so a single oversized field doesn't abort
  scanning of the rest of the request, and each cap logs exactly once
  per request to keep observability without log-flooding. Six locks
  in `tests/test_upload_helpers_caps.py`: regex-grep parity with
  `image-upload.js::MAX_IMAGE_COUNT` (future client changes can't
  silently desync), `MAX_TOTAL_UPLOAD_BYTES` sanity range
  `[10 × per-file, 500 MB]`, both at-cap and over-cap count paths,
  monkey-patched byte cap drives byte-cap truncation, and AST assertion
  that the loop uses `continue` rather than `break` (defends against a
  refactor that would let one bad field abort the rest of the scan).

### Fixed

- **`service_manager.get_web_ui_config` could resurrect a stale config
  after a concurrent `[config]` invalidate.** The cached config sits
  behind a 10 s TTL and is wiped by
  `_invalidate_runtime_caches_on_config_change` whenever the file
  watcher fires (manual edits in IDE, or any `cfg.set(...)` that
  cascades through). But the get path was a textbook double-checked
  pattern with the read *and* the write under the lock and the load
  outside it: T1 cache-miss → release lock → ~5–50 ms toml read +
  Pydantic validate → T2 watcher fires `_invalidate(...)` mid-load →
  T1 finishes and unconditionally re-writes the *pre-invalidate* tuple
  into the cache → T3 hits cache and gets the value the user already
  overwrote on disk. Silent staleness for up to one full TTL window;
  no existing test caught it because the race needed sub-millisecond
  interleaving. Fixed by adding `_config_cache_generation` (monotonic
  counter, bumped on every `_invalidate(...)`), snapshotting it under
  the lock at miss-time, and re-checking equality at write-back; on
  mismatch the write is dropped (T1's caller still gets its load
  result, but the cache stays clean and T3 re-loads). Three locks in
  `tests/test_web_ui_config.py::TestGetWebUIConfigGenerationToken`:
  the load-during-invalidate path *must not* resurrect cache (reverse-
  locked: removing the generation check immediately fails the test
  with an explicit "stale 旧值复活" hint), `_invalidate(...)` *must*
  increment the counter, and the no-race happy path *must* still write
  back normally — last lock is the guard against the fix trivially
  regressing into "never cache anything".
- **`GET /api/tasks` OpenAPI response schema dropped `deadline` from
  the per-task properties due to a 2-column docstring indentation
  drift.** In `web_ui_routes/task.py::get_tasks` the `deadline:` line
  was indented to the same column as `properties:`, which YAML
  interpreted as a sibling key of `items.type` / `items.properties`
  rather than a child of `items.properties`. Result: every OpenAPI
  consumer (swagger-ui, generated TypeScript / Python clients,
  `swagger-cli validate`, `openapi-generator-cli`) saw a `task` object
  schema without a `deadline` field — but the live JSON response
  *did* contain `deadline` (set in the `task_list.append(...)` block),
  so downstream deserializers either silently ignored it or failed
  validation depending on strictness. Reproducing the broken schema
  is invisible because YAML doesn't error on this kind of misindent;
  it just rebinds the key. Re-indented `deadline:` to align with
  sibling fields (`task_id` / `status` / `remaining_time` / etc.).
  Locked by
  `tests/test_openapi_input_range_parity.py::test_get_tasks_response_includes_deadline_under_items_properties`,
  which runs `yaml.safe_load` on the docstring and asserts
  `"deadline" in tasks.items.properties` — reverse-locked: re-applying
  the bad 24-column indent makes the test fail with an explicit
  pointer to the responsible docstring line.
- **`LogDeduplicator` could silently drop critical ERROR logs after
  wall-clock backwards jumps.** The deduplicator's "did this exact
  message fire within the last 5 s?" check used `time.time()`,
  which is wall-clock time and can move *backwards* on NTP
  resync, manual clock adjustment, DST tail-overlap on naive
  systems, or a virtual machine resuming from suspend. When that
  happens, `current_time - last_time` becomes negative,
  `≤ time_window` is trivially true forever, and the same ERROR
  line is silently squelched indefinitely — one of the worst
  observability failure modes (Heisenbug whose blast-radius
  scales with how long the clock stayed backwards). Switched the
  comparison to `time.monotonic()`, which is the textbook-correct
  primitive for "X seconds elapsed" windows (it cannot move
  backwards or be tampered with by NTP / users / hypervisors).
  Companion `tests/test_enhanced_logging.py::TestLogDeduplicatorMonotonic`
  carries two locks: a static-source assertion that
  `should_log` never reverts to `time.time()`, and a black-box
  contract test that monkey-patches `time.time()` to report
  one hour in the past — the dedup must still allow a fresh log
  through, proving the implementation is wall-clock-immune.
- **`wait_for_task_completion` orphaned web_ui tasks on timeout / cancel.**
  When the MCP-side `asyncio.wait_for(completion.wait())` tripped its
  `effective_timeout` (default 600s) the function returned a
  `_make_resubmit_response()` to the AI client *but* did not notify
  `web_ui` to clean its `task_queue`. The AI client would then
  re-invoke `interactive_feedback`, generating a fresh `task_id` and
  POSTing it to `/api/tasks` — but the original task was still
  ACTIVE, so the new task came in PENDING. The Web UI
  `current_prompt` is bound to the active task, so the user saw the
  *old* prompt and submitted feedback against the old `task_id`;
  meanwhile the MCP side was still waiting on SSE for the new
  `task_id`'s `task_changed(completed)` event, which would never
  fire — leading to another timeout and another resubmit, an
  effectively infinite loop visible only as "AI keeps asking the
  same question". The fix adds an asyncio finally-block hook
  (`_close_orphan_task_best_effort`) that POSTs
  `/api/tasks/<task_id>/close` whenever `result_box[0]` is still
  `None` at exit (covers TIMEOUT, KeyboardInterrupt, parent
  cancel paths simultaneously). The helper:
  - uses a 2 s short timeout (LAN/loopback close should never need
    more), so a wedged Web UI doesn't pin the cleanup,
  - swallows every non-`CancelledError` exception (`httpx.ConnectError`,
    HTTP 5xx, DNS, etc.) — it's best-effort cleanup, not a critical
    path,
  - re-raises `CancelledError` to preserve asyncio cancel semantics
    and avoid `Task was destroyed but it is pending!` warnings,
  - downgrades 404 to debug log (Web UI already GC'd the task; not
    worth a warning).

  Companion `tests/test_server_functions.py::TestGhostTaskCleanupOnTimeout`
  locks the contract with five tests: timeout path *must* call close,
  completed path *must not* call close (would race with
  `complete_task`), 404 path *must not* call close (no-op), close
  failure *must not* propagate, and `CancelledError` *must* re-raise.
- **`ConfigManager.reload()` silently lost in-process edits.** When
  `_save_timer` was queued (3-second batch debounce after a
  `cfg.set(...)`) and the file watcher fired before the timer
  did — e.g. operator edits `config.toml` in their IDE during
  a Bark URL field-edit window — `_load_config` would read the
  external bytes into `self._config`, then the lingering
  `_save_timer` would still wake up and `_pending_changes`
  would clobber the freshly-loaded external value back onto
  disk. Net effect: external edits silently lost, no warning,
  last-write-wins. Switched to *external-edit-wins* on reload:
  `_load_config` now clears `_pending_changes` and cancels
  `_save_timer` under the lock, logging a WARNING listing the
  discarded keys; matches operator intuition ("if I edited the
  file, my edit should win"). Companion
  `tests/test_config_manager.py::TestReloadDiscardsPendingChanges`
  reproduces the full race + locks the warning behaviour.
- **mDNS startup could crash the entire Web UI when Zeroconf
  endpoint was unavailable.** `WebFeedbackUI._start_mdns_if_needed`
  called `Zeroconf()` and `socket.inet_aton(publish_ip)` /
  `ServiceInfo(...)` without try/except, so any of:
  - Linux + Avahi conflict (`errno 98 EADDRINUSE`),
  - Windows 169.254.x.x link-local interfaces (`WinError 10049`),
  - IPv6-only loopback without multicast (`errno 101 ENETUNREACH`),
  - or a malformed `publish_ip` reaching `socket.inet_aton`
    (`OSError: illegal IP address string passed`)

  would propagate up out of `WebFeedbackUI.run()` and prevent
  the Web UI from starting at all — violating the documented
  contract that "mDNS failure must degrade gracefully to
  IP/localhost-only access". Both call-sites now wrap the
  failure in `try/except (OSError, ValueError)`, log a WARNING
  with `exc_info`, print a user-visible degradation notice, and
  return early so `WebFeedbackUI.run()` continues normally.
  `tests/test_web_ui_config.py::TestMdnsConstructorFailures`
  exercises both branches via mock injection.
- **AppleScript `maxBuffer` overflow misclassified as timeout.**
  When `osascript` produced more than `maxBufferBytes` of
  combined stdout+stderr (e.g. when a developer accidentally
  pasted a large AppleScript that returns a 5 MB result),
  `child_process.execFile` would throw with
  `error.code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER'` *and*
  `killed === true` / `signal === 'SIGTERM'`. The previous
  classifier checked only `killed`/`signal` and reported
  `APPLE_SCRIPT_TIMEOUT`, sending users on a wild goose chase
  to bump `timeoutMs` (which would not help — the real fix is
  to tighten the script or raise `maxBufferBytes`). The error
  classifier in `packages/vscode/applescript-executor.ts` now
  checks `errCodeStr === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER'`
  *first* and surfaces it as `APPLE_SCRIPT_OUTPUT_TOO_LARGE`,
  preserving the existing TIMEOUT vs FAILED ladder for
  everything else. New
  `packages/vscode/test/applescript-executor.test.js::maxBuffer
  overflow` test injects a fake `execFile` that reproduces the
  exact error shape Node throws, locking the disambiguation.

- **Silent feedback-timeout truncation.** `server_config.py`'s
  `FEEDBACK_TIMEOUT_MIN/MAX` and `AUTO_RESUBMIT_TIMEOUT_MIN/MAX`
  were stricter than the Pydantic `_clamp_int(...)` ranges in
  `shared_types.SECTION_MODELS::feedback`, so a user setting
  `frontend_countdown = 1000` in `config.toml` saw the value
  accepted by the schema, surfaced as `1000` in the Web UI's
  current-config panel, but at runtime `task_queue.py` and
  `web_ui_validators.py` (reading `AUTO_RESUBMIT_TIMEOUT_MAX = 250`)
  silently truncated to 250. Same story for `backend_max_wait`
  (capped at 3600 instead of the documented 7200). Constants
  widened to `[10, 3600]` / `[10, 7200]` to match Pydantic.
  Configurations that previously hit the cap now actually take
  effect; existing in-range configs see identical behaviour.
- **Silent HTTP-retry / HTTP-timeout truncation.** Same
  pattern as feedback-timeout, on `WebUIConfig.ClassVar` bounds
  in `server_config.py`: `TIMEOUT_MAX=300` / `MAX_RETRIES_MAX=10`
  / `RETRY_DELAY_MIN=0.1` were stricter than Pydantic
  `[1, 600]` / `[0, 20]` / `[0, 60]`. So
  `[web_ui] http_request_timeout = 500` was accepted by Pydantic
  but `service_manager._load_web_ui_config_from_disk` re-clamped
  to 300 in the second-pass `WebUIConfig(...)` construction.
  Bounds now match Pydantic side; six new introspection tests
  guarantee the lockstep stays.
- **Frontend `frontend_countdown` input pinned at 250s** even
  after the runtime widening above. Web UI HTML (`<input
  max="250">`), VS Code webview HTML, and the two settings-
  manager JS guards (`v <= 250`) all silently rejected
  user-typed values above 250. All four input surfaces now
  walked up to `max="3600"` (mirroring
  `AUTO_RESUBMIT_TIMEOUT_MAX`); 13 user-facing copy lines
  saying "Range 30-250" refreshed across READMEs, OpenAPI
  schemas, web_ui.py argparse help, and i18n locale files.
  Five `?? 250` / `|| 250` fallbacks in
  `static/js/multi_task.js` corrected to `?? 240` / `|| 240`
  (the actual `AUTO_RESUBMIT_TIMEOUT_DEFAULT`; 250 was the
  historical *MAX*, not *DEFAULT*).
- **`POST /api/reset-feedback-config` partial reset**: the
  endpoint backing the Web UI's "Reset feedback config to
  defaults" button only included 3 of 4 SECTION_MODELS::feedback
  fields in its `defaults` dict (`backend_max_wait` was
  silently NOT reset). Operators who'd previously customised
  `backend_max_wait` saw three fields revert and one preserve
  the old value. Endpoint now imports `FEEDBACK_TIMEOUT_DEFAULT`
  and covers the fourth key; AST-based parity test prevents
  regression.
- **Bark notifications fired twice on cross-region networks when
  user widened `bark_timeout` above 15s.** The async waiter inside
  ``NotificationManager._process_event`` had a hardcoded
  ``as_completed(futures, timeout=15)`` whose comment said
  "Bark default 10s" — but Pydantic ``coerce_bark_timeout``
  accepts ``[1, 300]``. With ``bark_timeout = 30`` (a normal
  setting on Mainland-China-to-day.app routes), ``as_completed``
  raised ``TimeoutError`` at 15s → retry path triggered →
  original Bark future was still in-flight (HTTP request at ~25s,
  budget 30s) and returned 200 (push #1) → retry future kicked
  off, returned 200 (push #2). End result: every Bark event
  arrived twice on the user's iPhone. Window now scales as
  ``bark_timeout + _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS``
  (constant default 5s; buffer absorbs thread-pool dispatch +
  httpx connection-pool warmup + first-time DNS). Locked by
  ``tests/test_notification_manager.py::
  TestProcessEventBarkTimeoutWindow`` (6 tests covering default /
  user-widened / Pydantic max / Pydantic min / corruption-fallback
  windows + a reverse-lock on the buffer constant).
- **SSE event stream silently halted for slow / backgrounded
  EventSource clients (e.g. laptop sleep, cellular handoff,
  background browser tab).** ``_SSEBus`` used to ``discard`` a
  subscriber's queue from ``_subscribers`` when its backlog hit
  3/4 of capacity (48 / 64), but did nothing to signal the
  generator on the other end. Generator stayed parked on
  ``q.get(timeout=25)``, drained the leftover backlog, then
  yielded ``: heartbeat`` forever — browser ``EventSource``
  saw a healthy stream of heartbeats and never triggered
  ``onerror`` / auto-reconnect. From the user's perspective
  the task list silently froze; ``F5`` recovered (full re-fetch)
  but real-time updates were dead. ``_SSEBus.emit`` now injects
  a module-level sentinel ``_SSE_DISCONNECT_SENTINEL`` into the
  queue when discarding a subscriber (with ``get_nowait`` evict-
  then-retry when the queue itself was already at capacity, at
  the cost of one missing oldest event that auto-reconnect's
  ``GET /api/tasks`` re-fetch covers). Generator branches on
  ``event is _SSE_DISCONNECT_SENTINEL`` and ``return`` s, which
  ends the response body, browser sees EOF, EventSource auto-
  reconnects within ~3s. Locked by
  ``tests/test_sse_bus_disconnect.py`` (6 tests including a
  reverse-lock that the sentinel must be ``object()`` identity
  — using ``None`` / ``False`` / ``{}`` would collide with
  legitimate SSE payloads and randomly terminate streams).
- **Settings panel debounce silently dropped edits when user
  switched fields within 800ms.** Both
  ``static/js/settings-manager.js`` and
  ``packages/vscode/webview-settings-ui.js`` had a
  ``debounceSaveFeedback = updates =>`` whose
  ``setTimeout(() => save(updates), 800)`` body captured the
  most-recent ``updates`` argument; a ``clearTimeout`` followed
  by a fresh ``setTimeout`` would silently DISCARD the prior
  payload. Reproduce: T=0 set ``frontend_countdown=60`` → timer
  armed; T=300 set ``resubmit_prompt="x"`` → ``clearTimeout``
  cancels first timer, second timer arms with only the second
  field; T=1100 ``saveFeedbackConfig({resubmit_prompt:"x"})``
  fires, ``frontend_countdown=60`` is gone forever with zero
  user-visible error toast. Fix accumulates updates into a
  ``pendingUpdates`` buffer (``Object.assign(buf||{},
  updates||{})``); the timer drains the buffer as a single
  merged POST. Web ↔ VSCode parity is locked by
  ``tests/test_debounce_save_feedback_accumulates.py`` (3 tests
  including a bidirectional parity gate that fails when only
  one mirror is fixed).
- **Concurrent notification retry thundering-herd.**
  ``NotificationManager._schedule_retry`` previously used a
  fixed ``retry_delay`` (default 2s, configurable to
  ``[0, 60]s``) so multiple in-flight Bark / Web / System
  sends failing within a single ms would re-fire retries in
  exact lock-step. Spike load on the upstream + correlated
  re-failure risk. Fix introduces
  ``_RETRY_DELAY_JITTER_RATIO = 0.5``; effective delay is now
  ``base_delay + random.uniform(0, base_delay * 0.5)``, with a
  fast-path preserving ``delay == 0`` semantics exactly. New
  ``tests/test_notification_manager.py::TestScheduleRetryJitter``
  (5 tests) locks the lower bound (delay ≥ base), the upper
  bound (≤ base * 1.5), the zero fast-path, and a reverse-lock
  on the ratio constant (must stay ≤ 1.0 or jitter could
  exceed base delay → retry order becomes nondeterministic).

- **OpenAPI input-spec `auto_resubmit_timeout` lacked
  `minimum`/`maximum` bounds.** Both
  `POST /api/add-task` and `POST /api/update-feedback`
  declared the field as a free `type: number` with no
  range constraint and no integer constraint, but
  `task_queue.add_task` and the Web UI feedback writer
  pin it to `[0, 3600]` (with 0 disabling, otherwise
  `[10, 3600]`). External clients hitting the OpenAPI
  spec to discover the contract had to either read the
  Python source or get bitten at runtime. Both endpoint
  yaml docstrings now declare
  `type: integer, minimum: 0, maximum: 3600` with a
  description explicitly cross-referencing
  `server_config.AUTO_RESUBMIT_TIMEOUT_MAX`. New AST/YAML
  parity test
  (`tests/test_openapi_input_range_parity.py`) loads the
  endpoint source, walks the docstring `requestBody`
  schema, and asserts the OpenAPI bounds equal the
  `_clamp_int` closure cells of
  `SECTION_MODELS::feedback.auto_resubmit_timeout` — so
  any future Pydantic-side widening (e.g.
  `[0, 7200]`) automatically requires the OpenAPI
  spec to follow.
- **CI Gate output is now WARNING-clean across consecutive runs.**
  `enhanced_logging.py` registers a Loguru sink against `sys.__stderr__`
  at module import — that path bypasses pytest's `capsys`/`capfd` capture
  and `unittest.TestCase.assertLogs` (which only collects stdlib
  `LogRecord`s before the `InterceptHandler` forwards them). Combined
  with `LogDeduplicator`'s 5-second time window, that occasionally let
  one ``通知发送失败，将在 2s 后重试`` line leak to the terminal on the
  first `ci_gate.py` invocation of a fresh shell, then silently
  disappear on subsequent re-runs (dedup hit) — a flaky-output footgun.
  A new session-scoped `autouse` fixture in `tests/conftest.py`
  (`_silence_loguru_sinks_during_tests`) drops the Loguru sink at
  pytest startup. `assertLogs` continues to assert WARNING records as
  before; only the duplicate stderr drain is removed. Verified by two
  back-to-back `uv run python scripts/ci_gate.py` runs producing zero
  WARNING/ERROR/FAIL/RETRY lines.

### Documentation

- **`docs/configuration{,.zh-CN}.md` numeric ranges are
  back in sync with `shared_types.SECTION_MODELS`** —
  `cbe5b9a` (TypedDict → Pydantic refactor) and `d0e60ea`
  (range bumps) updated the runtime `_clamp_int(...)`
  bounds without touching the docs, leaving five fields
  with stale ranges:
  - `[web_ui]::http_request_timeout` doc said `[1, 300]`,
    code allows `[1, 600]`
  - `[web_ui]::http_max_retries` doc said `[0, 10]`, code
    allows `[0, 20]`
  - `[web_ui]::http_retry_delay` doc said `[0.1, 60.0]`,
    code allows `[0, 60]`
  - `[feedback]::backend_max_wait` doc said `[60, 3600]`,
    code allows `[10, 7200]`
  - `[feedback]::frontend_countdown` doc said `[30, 250]`,
    code allows `[10, 3600]` (with `0`/non-positive
    disabling)
  Doc updates align both bilingual tables with the runtime
  reality (a user constraint reading the docs was being
  told a *narrower* allowed range than the binary actually
  enforces — same surprise direction as not knowing
  `external_base_url` exists). Companion test
  (`tests/test_config_docs_range_parity.py`) prevents the
  drift from re-emerging. Pure docs + new test patch — no
  runtime / `_clamp_int` change.
- **`docs/security/AUDIT_2026-05-04.md` no longer carries a
  `<TBD>` placeholder for the remediation commit hash.**
  The audit document opened with `STATUS: REMEDIATED (runtime
  CVEs cleared 17 → 0 on commit \`<TBD>\`…)` since the
  upgrade landed in `95e4151` (`🔒 chore(deps): security wave
  - production CVE exposure 17 -> 0`); a leftover
  `<TBD>` token in a security artefact is exactly the kind
  of stale string a future operator would mis-interpret as
  "remediation pending". Replaced with a deep-link to the
  fix commit on GitHub plus the commit subject line for
  zero-context audit trails. Pure documentation patch.

### Tests

- **Six new introspection-based parity gates** lock the
  numeric clamp bounds, default values, and reset-endpoint
  field coverage in `shared_types.SECTION_MODELS` against
  five other surfaces that historically drifted (or could
  drift in the future):
  - `tests/test_server_config_shared_types_parity.py` —
    `server_config.{FEEDBACK_TIMEOUT_MIN/MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN/MAX}` and the six
    `WebUIConfig.ClassVar` bounds equal the
    `SECTION_MODELS::{feedback, web_ui}` Pydantic ranges
    via `BeforeValidator` closure introspection (5 tests).
  - `tests/test_default_config_range_parity.py` — both
    `config.toml.default` and `config.jsonc.default` inline
    `range/范围 [a, b]` comments equal the introspected
    Pydantic bounds (2 tests).
  - `tests/test_frontend_input_range_parity.py` — Web UI
    HTML / settings JS, VS Code webview HTML / settings JS
    input bounds + `multi_task.js` fallbacks +
    `settings-manager.js` fallback all equal
    `server_config.AUTO_RESUBMIT_TIMEOUT_{MAX,DEFAULT}`
    (6 tests, 14 magic numbers across 5 files).
  - `tests/test_server_config_defaults_parity.py` —
    `server_config.*_DEFAULT` constants equal
    `SECTION_MODELS::feedback` field defaults via
    `model_fields[name].default` introspection (4 tests).
  - `tests/test_notification_config_parity.py` —
    `NotificationConfig`'s four `coerce_*` 2nd-clamp
    bounds equal Pydantic ranges via black-box behaviour
    assertions; explicit ÷100 scale-mismatch invariant for
    `sound_volume` (8 tests).
  - `tests/test_reset_feedback_config_parity.py` — AST
    extracts the `defaults = {...}` dict literal in
    `web_ui_routes/notification.py::reset_feedback_config`
    and asserts equality with
    `SECTION_MODELS::feedback.model_fields` (1 test).
- **New regression gate:
  `tests/test_mcp_tools_doc_consistency.py`** (3 cases)
  locks the contract that `docs/mcp_tools{,.zh-CN}.md`
  surfaces the **exact** current values of
  `server_config.MAX_MESSAGE_LENGTH` (10000) and
  `MAX_OPTION_LENGTH` (500) in their bold form
  (`**N**`). Includes a sanity guard that lists every
  bold 2–5 digit integer in those two docs and
  whitelists only constants tied to known runtime values
  — adding a new magic number to the docs without
  whitelist updates fails the test, forcing reviewers
  to confirm the new docs token has a backing constant.
  Forms a third layer of docs↔code defence next to
  `test_config_docs_parity.py` (key set) and
  `test_config_docs_range_parity.py` (numeric ranges).
- **New regression suite:
  `tests/test_bump_version_helpers.py`** (27 cases) covers
  the remaining six file-type helpers in
  `scripts/bump_version.py` that previously had **zero**
  unit coverage —
  `_{update,extract}_pyproject_version`,
  `_{update,extract}_uv_lock_version`,
  `_update_json_version_text` (package.json /
  packages/vscode/package.json),
  `_update_package_lock_text` (root + nested workspace
  triple-write), and
  `_{update,extract}_bug_template_example_version`. Forms a
  symmetric defence with the existing
  `tests/test_bump_version_citation.py` (CITATION.cff) and
  closes the test gap that let the CITATION omission ship in
  the first place. Each helper gets contract-level
  assertions: round-trip preservation, side-effect locality
  (third-party deps in `package-lock.json::node_modules/*`
  unchanged, `[tool.*]` sections in `pyproject.toml`
  preserved, multiline `placeholder: |` YAML blocks not
  touched), failure-path raises, and a real-repo sanity
  parse. Cross-file round-trip pins all helpers converging
  on the same target string. 2274 → 2301 total passing.
- **New regression gate:
  `tests/test_api_index_quick_nav_parity.py`** locks the
  contract that the *generated* `docs/api/index.md` and
  `docs/api.zh-CN/index.md` Quick navigation sections cover
  every module declared in `scripts/generate_docs.py::
  MODULES_TO_DOCUMENT`. Catches the
  `notification_providers`-style omission both at generator
  invocation (via `_assert_quick_nav_covers_all_modules`'s
  fail-fast `SystemExit`) **and** at the rendered file level
  (parses `### Core/Utility` blocks of both bilingual
  indexes). 9 new tests; 2265 → 2274 total passing.
- **New regression gate:
  `tests/test_config_docs_range_parity.py`** locks the
  contract that any numeric range stated in
  `docs/configuration{,.zh-CN}.md` (e.g. `range \`[1, 600]\``)
  must equal the actual `(min, max)` carried by the
  matching `BeforeValidator(_clamp_int(...))` in
  `shared_types.SECTION_MODELS`. Uses `__closure__`
  introspection so adding/removing a numeric field does
  not require touching the test, and a self-check pins
  several known anchors (e.g. `port=[1, 65535]`) so
  future `_clamp_int` refactors cannot silently weaken
  the assertion to vacuous truth. 3 new tests; 2249 → 2252
  total passing.
- **New regression gate:
  `tests/test_config_docs_parity.py`** locks the
  contract that every key declared in
  `config.toml.default` must appear in *both*
  `docs/configuration.md` and
  `docs/configuration.zh-CN.md` as a backticked entry in
  the matching `### \`<section>\`` table — and vice versa
  (no orphan documented keys). Complements the existing
  `tests/test_config_defaults_consistency.py` which guards
  the runtime default dict ↔ TOML template invariant.
  5 new tests; 2244 → 2249 total passing. The TOML / doc
  parsers each have a self-check so refactoring the regex
  later cannot silently weaken the gate (e.g., dropping a
  section it never noticed). Closes the structural gap
  that allowed the
  `[notification]::debug` /
  `[web_ui]::language` /
  `[mdns]::enabled` doc drift to ship in the first place.
- **`tests/test_i18n_fuzz_parity.py` extended with a Round-11
  ``EXT_SEED=0xFACECAFE`` corpus (100 samples) covering ICU-
  standard corner cases the original 200-sample fuzz never
  exercised:** ``=N`` exact-match branch in
  ``_selectPluralOption`` (line 410, implemented but no
  project locale used it → silently untested), empty plural
  arm body ``one {}``, multi-codepoint Unicode (4-byte BMP+
  emoji ``🚀``, ZWJ sequences ``👨‍👩‍👧``, regional
  indicator flag ``🇨🇳``, variation-selector + ZWJ
  ``🏳️‍🌈``, combining marks ``a\u0301``), and BiDi
  controls (LRM/RLM/LRE/PDF). Each new sample is forced
  through one of {``exact`` | ``empty_arm`` | ``emoji`` |
  ``bidi``} flavors so the new code paths are guaranteed
  reachable rather than randomly skipped; ``n*`` params land
  on 0/1 with 70% probability so ``=0``/``=1`` arms actually
  fire. All 102 new templates are byte-identical Web ↔
  VSCode (``static/js/i18n.js`` ↔ ``packages/vscode/i18n.js``)
  with zero PUA leakage and zero exceptions. Locks the
  surrogate-pair-safe substring and BiDi pass-through
  invariants forever.

### Documentation

- **`docs/configuration{,.zh-CN}.md` is back in sync with
  `config.toml.default`.** Three drift points were silently
  shipping in v1.5.x:
  - `[notification]::debug` (boolean, default `false`) was
    documented in the TOML template but absent from both
    bilingual configuration tables — readers reaching for
    extra notification log verbosity had to grep the
    template.
  - `[web_ui]::language` (string, default `"auto"`) — same
    issue. The setting controls the UI locale (`"auto"` /
    `"en"` / `"zh-CN"`) and is one of the most user-asked
    config keys.
  - The Chinese `[mdns]::enabled` row showed type
    `boolean / null` and default `null`, but the actual
    runtime contract has used the string sentinel `"auto"`
    for several minor releases (the English doc and the TOML
    template both already say `"auto"`). Updated to match.
  - The Chinese "最小示例" was still a stale `jsonc` snippet
    even though the recommended on-disk format is `config.toml`.
    Replaced with the parallel TOML form already used by the
    English doc.
  Pure docs patch — neither the runtime config schema nor
  `config.toml.default` change. `make ci` passes.
- **`docs/README{,.zh-CN}.md` API-reference module list is in
  sync with `MODULES_TO_DOCUMENT` again.** Both bilingual
  index files used to enumerate the API auto-gen scope as
  "`config_manager`, `notification_*`, `task_queue`,
  `file_validator`, `enhanced_logging`, `exceptions`,
  `shared_types`, `config_utils`" — that list was last
  refreshed before commit `a8db779` added `protocol.py`,
  `state_machine.py`, and `i18n.py` to the generator. The
  index now groups the modules by Core / Utility (matching
  the bilingual quick-navigation grid emitted into the
  generated `api{,.zh-CN}/index.md`) and additionally
  surfaces the `make docs-check` shortcut for drift
  detection. Pure docs patch — no generator or test
  change.
- **PR template's "Local verification" checklist now lists
  `make ci` / `make vscode-check` shortcuts alongside the
  existing `uv run python scripts/ci_gate.py …` invocations,
  closing the consistency gap with `CONTRIBUTING.md` and
  `docs/workflow{,.zh-CN}.md`. Also adds a `make docs-check`
  bullet so contributors who touch Python public API or
  docstrings are reminded to verify `docs/api{,.zh-CN}/`
  doesn't drift.
- **`docs/workflow{,.zh-CN}.md` no longer recommends the
  legacy `scripts/check_locales.py` for ad-hoc locale
  validation.** Both files used to instruct contributors to
  run `check_locales.py` as the "Locale check" entry under
  the per-tool list, but `scripts/README.md::§i18n static
  gates` already flagged that script as "minimal smoke
  (key-only parity), kept for legacy invocations" — the
  modern equivalent is `check_i18n_locale_parity.py` (full
  parity: keys + nested shapes + ICU placeholders), which is
  what `ci_gate.py` already runs. The bullet now points new
  contributors at the modern script with a parenthetical
  noting `check_locales.py` survives only for backward
  compatibility, eliminating a discoverability trap where a
  reader who skipped the scripts/README would reach for the
  weaker validator.
- **`docs/api.zh-CN/index.md` gains a one-line subtitle.**
  Symmetric polish to the English index's "English API
  reference (signatures-focused)." subtitle: the Chinese
  index now opens with "中文 API 参考（含完整 docstring 叙述）。"
  so a Chinese reader landing on the index immediately knows
  they're getting full docstring narratives (vs the English
  signature-only summary), without having to click a module
  page first to find out. Generator emits both subtitles from
  the same `lang`-conditional block in
  `scripts/generate_docs.py::generate_index`; re-running
  `--lang zh-CN` rewrites the on-disk index with the new line.
- **Chinese API reference pages now carry a back-link to the
  English signature-only version.** Symmetric to the existing
  English pages' "For the Chinese version with full
  docstrings, see…" header, every `docs/api.zh-CN/*.md` now
  starts with "英文 signature-only 版本（仅函数 / 类签名速查）：…"
  pointing at its sibling under `docs/api/`. Previously the
  link was one-directional: English readers could jump to
  Chinese for full narrative, but Chinese readers had no
  pointer to the signature-focused English summary even though
  the latter is often more useful when scanning an unfamiliar
  module quickly. Implemented in `scripts/generate_docs.py::generate_markdown`
  by adding a symmetric `else` branch to the existing
  language-conditional cross-link block. Re-running the
  generator inserts the link into all 14 Chinese pages
  (existing 11 + the three added in the previous commit).
- **API reference now covers `protocol.py`, `state_machine.py`,
  and `i18n.py`.** These three modules are the front/back-end
  contract for protocol versioning, state-machine transitions,
  and back-end i18n message lookup respectively — all single-
  source-of-truth modules whose absence from the API reference
  was a discoverability gap. `scripts/generate_docs.py`
  appends them to `MODULES_TO_DOCUMENT` and slots them into the
  bilingual quick-navigation grouping (`protocol` /
  `state_machine` → Core; `i18n` → Utility). Re-running the
  generator emits 14 module pages per locale (was 11) plus the
  refreshed `index.md`. Pure documentation surface — no Python
  source change. Verified with `make ci` (full gate green) and
  by spot-checking the three new pages render the public
  function signatures.

### Fixed

- **English API reference index now has a parity "Quick
  navigation" section.** `scripts/generate_docs.py::generate_index`
  used to emit a Core/Utility-modules grouped quick-navigation
  block only for `--lang zh-CN` (lines 236–262 of the previous
  generator), so `docs/api/index.md` (English) had a flat
  module list while `docs/api.zh-CN/index.md` (Chinese) gained
  a structured "核心模块 / 工具模块" overview. That meant
  English readers landing on the auto-generated reference got a
  visibly degraded onboarding experience compared to Chinese
  readers — for a project that ships bilingual READMEs and
  bilingual workflow docs, that's an unintended asymmetry.
  Both languages now emit the same Core/Utility groupings; the
  English copy uses the audience-appropriate wording
  ("Configuration management", "Notification orchestration",
  etc.). Verified with `uv run python scripts/generate_docs.py --lang en`
  + `--lang zh-CN` followed by `git diff docs/api/index.md
  docs/api.zh-CN/index.md` showing identical structural skeletons.

### Chore

- **Bilingual `README` Acknowledgements section formalises the
  upstream lineage.** Pairs with the LICENSE backfill (which
  retained Fábio Ferreira (2024) and Pau Oliva (2025) per MIT
  terms): the new section credits both upstream authors with
  links to their original repos
  ([`noopstudios/interactive-feedback-mcp`](https://github.com/noopstudios/interactive-feedback-mcp)
  · [`poliva/interactive-feedback-mcp`](https://github.com/poliva/interactive-feedback-mcp))
  and explicitly scopes the v1.5.x rewrite (Web UI, VS Code
  extension, i18n, notification stack, CI/CD pipeline) to
  [@xiadengma](https://github.com/xiadengma) so attribution
  intent is unambiguous to PyPI / Marketplace readers landing
  on either README. Inserted immediately above the existing
  License section in both `README.md` and `README.zh-CN.md`.
- **Top-level `Makefile` exposes `make test` / `make ci` /
  `make docs` / `make lint` / `make coverage` /
  `make vscode-check` / `make pre-commit` / `make clean` as
  thin wrappers around `scripts/ci_gate.py` and friends.** The
  source of truth still lives in those scripts; the `Makefile`
  only saves contributors from typing `uv run python scripts/…`
  four times a day and matches the muscle memory that most
  Python projects standardise on. `.DEFAULT_GOAL := help` makes
  bare `make` print the target table, so a fresh checkout's
  first `make` is informative instead of surprising. No CI
  surface change — `scripts/ci_gate.py` remains the canonical
  entrypoint for `.github/workflows/test.yml`; `make ci` is
  just an alias for local use. Verified `make help`,
  `make lint`, `make docs-check`, and `make ci` against a
  clean tree. The shortcut is also surfaced in
  `CONTRIBUTING.md` (Section 2 Local CI Gate),
  `docs/workflow.md`, `docs/workflow.zh-CN.md`, and
  `scripts/README.md` so newcomers landing in any of those
  pages discover it without having to grep for `Makefile`.
- **`scripts/ci_gate.py` now runs `generate_docs.py --check` for
  both locales (warn-level, non-blocking).** A new `_run_warn`
  helper executes the command but converts a non-zero exit into
  a `[ci_gate] WARN: …` line on stderr instead of aborting. Now
  any `git push` that ships Python signature / docstring changes
  but forgets to run `uv run python scripts/generate_docs.py
  --lang en` (and `--lang zh-CN`) gets a human-readable nudge
  in the local CI output, with the exact remediation command
  printed. The main flow stays green so single-letter
  contributor pull-requests don't get blocked by API-doc
  drift on day one. Promotion path: when the team standardises
  on regenerate-on-commit, switching the two lines from
  `_run_warn` to `_run` upgrades the gate to fail-closed.
- **`LICENSE` now lists xiadengma alongside the upstream
  copyright holders (Fábio Ferreira, Pau Oliva).** The MIT
  license requires retaining the original notices, but
  `pyproject.toml::authors` and `CITATION.cff::authors` had
  declared xiadengma as the project author for the entire v1.5
  series while `LICENSE` still attributed the work solely to
  the upstream forks. Downstream consumers reading the wheel's
  `LICENSE` file (or the GitHub "About" sidebar's copyright
  resolver) saw a misleading "owned by Fabio + Pau" signal.
  xiadengma's notice is placed first to reflect being the
  current primary author of the v1.5.x rewrite (per the v1.5.20
  server-side refactor and full VS Code extension authoring);
  Fábio Ferreira (2024) and Pau Oliva (2025) are retained per
  MIT's "the above copyright notice ... shall be included" rule.
- **Coverage red line (`fail_under = 88`) and report polish in
  `pyproject.toml`.** The project shipped without any
  `[tool.coverage.*]` section, so coverage could regress
  arbitrarily without CI noticing. Added:
  - `[tool.coverage.run] omit = ["scripts/*", "tests/*", "*/test_*.py", "manual_test.py"]`
    so the denominator only includes production code (test
    files inflating their own coverage to 100% would mask
    regressions in the surfaces that matter).
  - `[tool.coverage.run] parallel = true` to correctly merge
    `.coverage` data when pytest is run with `-n` / xfail
    rerun-on-failure tooling later.
  - `[tool.coverage.report] fail_under = 88` — the v1.5.22
    measurement is 90.96%, leaving ~3% volatility headroom
    before CI blocks the merge. Includes a comment recommending
    `+1%` per minor release while keeping `≥2%` of headroom to
    absorb innocuous churn.
  - `[tool.coverage.report] skip_covered = true` and
    `show_missing = true` — the term-missing report no longer
    drowns reviewers in 100%-clean files, and remaining gaps
    surface their specific line numbers.
  - `[tool.coverage.report] exclude_lines` — recognise
    `pragma: no cover`, `raise NotImplementedError`,
    `if TYPE_CHECKING:`, and `if __name__ == "__main__":` so
    the metric stays honest without manual annotation in every
    file.
  Verified by running `uv run python scripts/ci_gate.py
  --with-coverage`: TOTAL = 90.96%, fail_under = 88, exit 0.
- **`.pre-commit-config.yaml` gains three commonly-recommended
  hooks from `pre-commit/pre-commit-hooks` (already pinned at
  `v5.0.0`, so zero new dependency).**
  - `check-toml` — the project lives on TOML (`pyproject.toml`,
    `config.toml.default`, `tests/fixtures/*.toml`, every release
    note's `[project.urls]` entry). `check-yaml` and `check-json`
    were already on; without `check-toml` a malformed bracket in
    `pyproject.toml` would have to wait for `uv sync` /
    `uv build` to fail. Added next to the existing format
    sanity checks.
  - `mixed-line-ending --fix=lf` — `.gitattributes` already declares
    `* text=auto eol=lf`, but Windows checkouts can still produce
    CRLF in newly authored files until the first `git checkout`
    re-normalisation. The hook auto-rewrites to LF at commit time,
    closing the loop pre-push (instead of letting CI catch it).
  - `debug-statements` — guards against `breakpoint()` /
    `import pdb; pdb.set_trace()` /  `pdb.run(...)` slipping into
    commits. Particularly nasty in the MCP server path where
    `pdb` will block on `sys.stdin` and the host process appears
    to hang silently. `ruff`'s `T20` category does not catch
    `breakpoint()`, so the dedicated hook adds a real safety net.
  Verified with `uv run pre-commit run --all-files`: all three
  new hooks pass on the current tree, no surprises to clean up.
- **PyPI metadata enrichment in `pyproject.toml`.** Added four new
  `classifiers` that the listing was missing despite shipping the
  underlying capability for several minor releases:
  - `Environment :: Web Environment` — the bundled Flask Web UI is
    a first-class user-facing surface, not a hidden runtime detail.
  - `Framework :: Flask` — Flask is the listed runtime dependency
    powering the Web UI; declaring it lets PyPI's faceted search
    surface the project under Flask's framework filter.
  - `Natural Language :: English` and `Natural Language :: Chinese
    (Simplified)` — the project ships fully bilingual READMEs,
    docs, locale bundles, and VS Code extension `package.nls.*`;
    declaring both Natural Language facets lets non-English Python
    devs find the package without guessing.
  Also added a `Discussions` entry under `[project.urls]` pointing
  at GitHub Discussions, mirroring the route already advertised in
  `.github/ISSUE_TEMPLATE/config.yml` for "use questions / share
  ideas". `pip show ai-intervention-agent` and the PyPI sidebar now
  surface a direct route to the discussions board, not just the
  issue tracker.
  Did **not** add `Typing :: Typed`: that classifier is for
  PEP 561 library packages whose downstream users `import` typed
  symbols. This project ships as a CLI / MCP-server application;
  there are no public Python APIs for downstream consumers.

### Documentation

- **`scripts/generate_docs.py` gains a `--check` mode + the
  generator is now idempotent.** The new flag does an in-memory
  byte-level compare against the on-disk file and exits with
  status 1 + a list of drifted paths when they don't match —
  ready to be wired into CI once contributors are comfortable
  running `--lang en` and `--lang zh-CN` after every signature
  edit. Idempotency required tightening `generate_markdown()` to
  strip a stray pair of trailing newlines that pre-commit's
  `end-of-file-fixer` was collapsing on every run, which had
  previously caused first-time `--check` users to see a phantom
  drift on a freshly-regenerated tree. Verified by running the
  generator twice in a row and confirming `git diff --stat`
  reports zero changes; `--check` then exits cleanly. Wiring
  to `ci_gate.py` deferred so the contract remains opt-in until
  the team standardises on regenerate-on-commit.
- **API reference (`docs/api/` + `docs/api.zh-CN/`) refreshed to
  match current source.** Running
  `uv run python scripts/generate_docs.py --lang en`
  and `--lang zh-CN` against the v1.5.22 tree revealed two
  drifts that had built up since the last regeneration:
  1. **`server_config.py` was completely missing** from both
     index pages despite being declared in
     `MODULES_TO_DOCUMENT` (`scripts/generate_docs.py:33-44`).
     The module is the result of the v1.5.20 server-side
     refactor that hoisted dataclasses + input validation +
     response parsing out of `server.py`; without its API doc
     reviewers had to grep source. Now generated for both
     locales and surfaced in the Chinese index's "核心模块"
     quick-nav alongside `config_manager` / `task_queue`.
  2. **Nine existing module docs (`config_manager`,
     `notification_*`, `task_queue`, `enhanced_logging`,
     `shared_types`, etc.) had ~250 lines of net additions**
     mirroring real signature changes / new methods that
     landed across v1.5.x. The regenerate is purely
     reflection of in-source docstrings and signatures, no
     hand-editing.
  Also fixed three latent generator-style bugs in
  `scripts/generate_docs.py` so future regenerations don't
  re-introduce noise:
  - Output now ends with a trailing `\n` (was missing,
    triggering pre-commit's `end-of-file-fixer` on every
    regenerate).
  - Italic emphasis switched from `*…*` to `_…_` to match
    the style canonicalised across the repo (CHANGELOG +
    AUDIT entries follow the same convention since the
    earlier markdown sweep).
  - Empty lines after `### 核心模块` / `### 工具模块` /
    `---` separators added so MD renderers (GitHub web,
    Marked, Pandoc) all parse the H3s as block headings.
- **`packages/vscode/CHANGELOG.md` (new)** — VS Code Marketplace and
  Open VSX render the extension package's own `CHANGELOG.md` on the
  listing's "Changelog" tab. Until now the extension shipped without
  this file, so users on the Marketplace page saw an empty Changelog
  tab no matter how many releases had landed. The new file is a
  curated per-release excerpt of the extension-relevant changes from
  v1.5.20 onwards, with a link back to the root `CHANGELOG.md` for
  the full project history. Wired into the VSIX in two places:
  `package.json::files` (npm metadata) and
  `scripts/package_vscode_vsix.mjs::includeList` (the actual VSIX
  copy step uses an explicit allowlist rather than reading `files`,
  to keep the monorepo from leaking sibling packages into the
  vsix). Single source of truth stays the root `CHANGELOG.md`; the
  extension copy is updated alongside each version bump.
- **`docs/README.md` + `docs/README.zh-CN.md` (new, bilingual)** —
  audience-first directory index for the 30+ markdown files under
  `docs/`. Splits navigation into four roles (end users wanting
  config / troubleshooting; contributors touching code or
  translations; operators caring about noise levels; reviewers
  auditing security). Replaces the previous "grep + guess"
  onboarding experience and is referenced from both root READMEs'
  Documentation section.
- **`scripts/README.md` (new)** — one-liner index for all 20
  automation entry points (the `ci_gate.py` orchestrator, eight
  i18n static gates, three generators, the asset/packaging
  pipeline, three test harnesses, and the coverage wrapper).
  Lets fresh contributors grep one file and learn **what** each
  script does, **when** it runs, and **what** it gates without
  reading every docstring. Linked from both root READMEs'
  Documentation section.
- **Removed phantom `ai-intervention-agent.enableAppleScript`
  reference from both root READMEs.** The setting key has not been
  declared in `packages/vscode/package.json::contributes.configuration`
  for several minor releases (the AppleScript path is gated only by
  the macOS native notification toggle inside the panel UI). The
  outdated row sent users hunting through `settings.json` for a
  control that no longer exists; replaced with a one-line pointer
  to the VS Code extension README.
- **`packages/vscode/README.md` + `.zh-CN.md` gain two new
  sections:**
    1. `i18n.pseudoLocale` *(experimental)* setting documented for
       the first time — it had been declared in `package.json`
       and tagged `experimental` since v1.5.x but had no end-user
       documentation, so QA folk who want to spot hardcoded strings
       or layout overflow could not discover it.
    2. **AppleScript executor security model** — full enumeration of
       the seven safeguards baked into `applescript-executor.ts`
       (platform check, absolute `/usr/bin/osascript` path, stdin
       script delivery, 8 s hard timeout, 1 MiB output cap, log
       redaction, and "no user-supplied scripts" architectural
       invariant). `SECURITY.md` already mentioned the executor in
       the "Out of scope" section; this expansion lets reviewers
       (and downstream packagers) verify the assertion at source.
- **`docs/troubleshooting.md` + `docs/troubleshooting.zh-CN.md` (new,
  bilingual)** — focused FAQ covering the eight most common
  deployment / runtime issues: port-in-use Web UI failure, blank
  VS Code panel, empty task list / SSE replay, notification
  channels (Web / sound / system / Bark) silence triage, mDNS
  `ai.local` resolution, "Open in IDE" button no-op, PWA install
  prompt missing, and local-vs-CI Gate divergence. Each entry
  follows a "symptom → cause → fix" structure so users can
  self-diagnose in <2 minutes. Linked from `SUPPORT.md` (under
  "Before opening an issue") and from both READMEs (Documentation
  section).
- **OpenSSF Scorecard badge added to both READMEs** (English + 简体中文).
  The badge tracks the `scorecard.yml` workflow status (currently green;
  `publish_results: true` already streams attested SARIF to Sigstore +
  GitHub Security tab via OIDC). Wired in as a workflow-status badge —
  rather than the shields.io `ossf-scorecard` endpoint — until the
  OpenSSF public catalogue (`api.securityscorecards.dev`) finishes
  ingesting this repository, so visitors don't see "no score / invalid
  repo path" on first paint. We can swap to the score badge in a
  follow-up once the public API returns 200.

### Chore

- **PyPI Development Status classifier graduated from `4 - Beta` to
  `5 - Production/Stable`** in `pyproject.toml`. v1.5.22 ships 2244 passing
  tests at 90.96% line coverage, zero known CVEs in the production dependency
  chain (post pip-audit wave), and is published on PyPI / Open VSX / VS Code
  Marketplace under v1.5.x; the `Beta` label was an unnecessary speedbump for
  adopters scanning the project page. Pure metadata change — no runtime impact.

## [1.5.22] — 2026-05-04

A maintenance + security release. Runtime CVE exposure cleared from 17
to 0; +32 boundary-tests; full GitHub Community Standards compliance;
PyPI / VSCode marketplace metadata polish; release notes draft and
audit artefacts. Runtime behaviour is functionally unchanged from
v1.5.21 — operators can drop in the new wheel / extension without
config migration.

### Security

- **Dependency vulnerability audit + remediation.** Ran `pip-audit 2.10.0`
  against the v1.5.21 environment, found 17 CVE/GHSA items across 10
  packages, and **upgraded the runtime chain in one coordinated bump**:
  `fastmcp 3.1.1 → 3.2.4` (which cascaded `starlette 0.46 → 1.0`,
  `cryptography 45 → 47`, `cffi 1 → 2`, `python-multipart 0.0.20 → 0.0.27`,
  `werkzeug 3.1.3 → 3.1.8`, `authlib 1.6.9 → 1.7.0`,
  `markdown 3.8 → 3.10.2`, `pygments 2.19 → 2.20`,
  `python-dotenv 1.1 → 1.2.2`). Post-upgrade `pip-audit` reports **1
  remaining finding** (`pytest 8.4.0 / CVE-2025-71176`), which is
  dev-only tooling and intentionally deferred to a separate PR (8 → 9
  is a major version bump). Net production CVE exposure: **17 → 0**.
  Both the pre- (`pip-audit-2026-05-04.json`) and post-upgrade
  (`pip-audit-2026-05-04-post-upgrade.json`) snapshots are committed
  under `docs/security/` for future-baseline diffs.
- **Compat fix in `scripts/test_mcp_client.py`**: fastmcp 3.2 moved the
  private `_convert_to_content` helper from `fastmcp.tools.tool` to
  `fastmcp.tools.base`. The self-check now does a `try/except ImportError`
  fallback so it works on both 3.1 and 3.2+.

### Documentation

- **`docs/mcp_tools.md` / `docs/mcp_tools.zh-CN.md` now document all three
  shapes of `predefined_options`** (simple `list[str]`, object form
  `list[{label, default}]`, and `list[str]` + `predefined_options_defaults`).
  Previously only the simple form was documented; LLM clients had to read
  the source to discover the pre-selection capability shipped in v1.5.20.
  Includes the documented normalisation matrix (truthy alias list, length
  truncate / pad-with-False rule) and side-by-side examples for both new
  shapes.
- **`CONTRIBUTING.md` clarifies `✅` vs `🧪` test-commit emoji semantics**:
  `🧪` for new / expanded test surface (boundary tests, missing route
  coverage), `✅` for stabilising / fixing / migrating existing tests.

### Chore

- **PyPI metadata gains `Changelog` and `Release notes` Project-URL
  entries** in `pyproject.toml`. PyPI's "Project links" sidebar and
  `pip show` now include direct links to `CHANGELOG.md` and the GitHub
  Releases tab.
- **VSCode extension manifest gains `license`, `homepage`, `bugs.url`,
  and `keywords`** in `packages/vscode/package.json`. Marketplace search
  surfaces the extension on common AI workflow keywords (`mcp`, `claude`,
  `cursor`, `windsurf`, …); the License field no longer shows
  `(unknown)`; the Q&A tab links to GitHub Issues.
- **`CITATION.cff` (Citation File Format 1.2.0)** at the repo root, so
  GitHub's "Cite this repository" sidebar button works (renders BibTeX
  / APA / RIS) and Zotero / Zenodo plugins pick up correct metadata.
- **`SUPPORT.md` (bilingual)** — closes the last unchecked item on
  GitHub's Community Standards page. Routes incoming questions by
  topic (defect → bug template, security → private advisory, etc.)
  and lays out maintainer-driven best-effort SLOs (1–3 day ack,
  2-week silent-bump grace) so newcomers know what response time to
  expect.

### Tests

- **Boundary-test hardening for the v1.5.21 line.** Added 32 regression tests
  covering previously-unexercised failure paths and routes that had zero
  coverage. Net effect: full-suite count rose from 2212 to 2244, and overall
  line coverage improved from 89.93% to 90.96%.
  - `tests/test_server_identity.py` — single-icon read failure isolation
    (one corrupt PNG must not nuke the whole `icons` list) +
    `importlib.metadata` exception fallback to `0.0.0+local`.
  - `tests/test_web_ui_routes_system.py` — `/api/system/open-config-file`
    edge cases: empty `_resolve_allowed_paths()`, default target missing on
    disk, explicit editor uninstalled (graceful auto-detect fallback).
  - `tests/test_web_ui_update_language.py` (new file) — `/api/update-language`
    full contract: three valid languages, empty-payload default, unknown /
    empty-string rejection, whitespace stripping, write-failure 500 path.
  - `tests/test_web_ui_routes.py::TestStaticRoutesEdge` — new
    `/manifest.webmanifest` regression point (PWA install banner depends on
    it; v1.5.20 added the route with no test).
  - `tests/test_web_ui_routes.py::TestUpdateFeedbackConfigEndpoint` — error
    branches for `/api/update-feedback-config` (non-int countdown,
    `frontend_countdown=0` "disable timer" semantics, single-field updates,
    no-recognised-fields message, non-dict payload coercion, 500 path with
    i18n message wrapping verification).
  - `tests/test_web_ui_routes.py::TestCreateTask` — full type-coercion matrix
    for `predefined_options_defaults` (TODO #3 field shipped in v1.5.20 with
    zero direct tests): bool / int / float / str-aliases / unknown types,
    plus length truncate / pad-with-False.
  - `tests/test_web_ui_routes.py::TestCloseTask` (new class) —
    `/api/tasks/<id>/close` happy / 404 / 500 (route was untested since
    multi-task feature shipped).
  - `tests/test_web_ui_config.py::TestValidateAllowedNetworks` and
    `TestValidateBlockedIps` — three security-critical branches
    previously skipped: `None` / non-string / empty-string early-reject
    for `allowed_networks`, CIDR normalisation (`10.0.0.1/24` →
    `10.0.0.0/24`) for `blocked_ips`, and IPv4-mapped IPv6 unwrap
    (`::ffff:10.0.0.1` → `10.0.0.1`) so the same physical host can't
    bypass blocklist via dual-stack representation.

### Coverage by file (informational)

| Module                          | v1.5.21 | Now        | Δ       |
| ------------------------------- | ------- | ---------- | ------- |
| `web_ui_routes/static.py`       | 89.0%   | **100.0%** | +11.0%  |
| `web_ui.py`                     | 88.0%   | **98.77%** | +10.77% |
| `web_ui_routes/task.py`         | 73.37%  | **87.62%** | +14.25% |
| `web_ui_routes/notification.py` | 92.88%  | **97.41%** | +4.53%  |
| `web_ui_routes/system.py`       | 79.53%  | **82.33%** | +2.80%  |
| `web_ui_validators.py`          | 93.85%  | **99.23%** | +5.38%  |

## [1.5.21] - 2026-05-04

### Added

- **MCP server identity** advertised in the `initialize` response: `name`,
  `version` (auto-resolved from `importlib.metadata`), `instructions` (Chinese
  guide on when to / not to call the tool), `website_url`, and self-contained
  `icons` (4 base64 data URIs covering 32/192/512 PNG + SVG, ~17 KB total, no
  remote CDN dependency).
- **MCP tool annotations** on `interactive_feedback`: `title`,
  `readOnlyHint=False`, `destructiveHint=False`, `idempotentHint=False`,
  `openWorldHint=True`. Clients (ChatGPT Desktop / Claude Desktop / Cursor)
  no longer ask for "destructive operation" confirmation on every call.
- 20 contract tests in `tests/test_tool_annotations.py` and
  `tests/test_server_identity.py` to lock the new metadata and prevent silent
  regressions.
- `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, bilingual)
  so GitHub's Community Standards page is fully green and new contributors find
  setup / commit-style guidance on the first click.

### Documentation

- New "Server-level metadata" and "Tool-level annotations" sections in
  `docs/mcp_tools.md` and `docs/mcp_tools.zh-CN.md`.
- README and README.zh-CN now highlight the MCP 2025-11-25 spec compliance and
  link to `CHANGELOG.md`, `CONTRIBUTING.md`, and `CODE_OF_CONDUCT.md`.

### Chore

- `.editorconfig` for cross-editor formatting consistency (Python 4-space,
  JS/TS/MD 2-space, Makefile tab), aligned with the existing ruff conventions.
- `.gitattributes` to force LF line endings on text sources (so Windows clones
  do not silently break byte-sensitive tests) and to mark binary assets and
  vendored / generated files for GitHub linguist.

## [1.5.20] - 2026-05-04

### Added

- Pydantic-validated fallbacks and alias mapping for `interactive_feedback`,
  so drift parameters (`summary` / `prompt` / `project_directory` /
  `submit_button_text` / `timeout` / `feedback_type` / `priority` /
  `language` / `tags` / `user_id`) no longer break first-call validation.
- Full PWA icon family (`manifest.webmanifest` + 16/32/180/192/512 PNG + SVG)
  with `maskable` purpose for adaptive icons; Web UI now passes Lighthouse
  PWA installability checks.
- Default-selection support for `predefined_options` in three input shapes
  (`str` / `dict` / `list`), with the multi-task UI honouring the default
  while still allowing the user to change it.
- "Open in IDE" button on the settings page, gated by:
  - **Loopback-only** (`127.0.0.1` / `::1`) — remote requests are rejected.
  - **Path whitelist** — only the resolved active config file and
    `config.toml.default` are openable; never accepts an arbitrary path.
  - **No shell** — commands are passed as argument lists to `subprocess.Popen`
    with `shell=False`, blocking shell injection.
  - Editor priority: env var `AI_INTERVENTION_AGENT_OPEN_WITH` → request
    `editor` → auto-detect (cursor / code / windsurf / subl / webstorm /
    pycharm) → system default (`open` / `xdg-open` / `start`).
- Bark notification deep-linking via `bark_url_template` with placeholders
  `{task_id}`, `{event_id}`, `{base_url}` so iOS users can jump straight to
  the relevant feedback task.

### Changed

- `PROMPT_MAX_LENGTH` raised from 500 to 10 000 characters to match the
  longer prompts agents now produce.
- `interactive_feedback` docstring overhauled with use cases, parameter
  guidance, and behavior contract — visible to LLM agents at registration.
- VS Code extension `engines.vscode` aligned with `@types/vscode` to keep
  the extension host and the type checker on the same baseline.
- `web_ui_routes/system.py` test coverage raised from 13.02% to 79.53%
  (20 new tests).

### Fixed

- All CI Gate warnings silenced: expected retry log lines now captured via
  `assertLogs`, and the perf-test `TaskQueue` capacity raised to 2 000 to
  avoid spurious "queue full" warnings.

### Security

- New `dependabot.yml` ignore rule pinning `@types/vscode` to its
  manually-aligned version, preventing recurring `engines.vscode` /
  `@types/vscode` rebase conflicts.
