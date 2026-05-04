# Release notes draft (post-v1.5.22 / candidate v1.5.23)

> Draft assembled by the assistant after the v1.5.22 tag, summarising
> the 101 maintenance commits added on top of the release. This is **not**
> a published release; the file is committed under `.github/` only as a
> paste-ready artifact for whoever cuts the next minor.
>
> When ready to publish:
>
> 1. Bump the version in `pyproject.toml`, `packages/vscode/package.json`,
>    `package.json` (root), `CITATION.cff`, and `.github/ISSUE_TEMPLATE/bug_report.yml`.
>    `uv run python scripts/bump_version.py 1.5.23` covers all of them
>    in a single shot (CITATION.cff joined the synchronised set in this
>    cycle); double-check with `--check`. Manually update
>    `CITATION.cff::date-released` to the tag date — the script
>    deliberately leaves that to the publisher.
> 2. Move the `[Unreleased]` block in `CHANGELOG.md` to
>    `[1.5.23] - <date>` and add a fresh empty `[Unreleased]` heading.
> 3. Update `packages/vscode/CHANGELOG.md`: move the `[Unreleased]`
>    block down to a new `[1.5.23] - <date>` section and add a fresh
>    `[Unreleased]` heading. Keep only the **extension-relevant** rows
>    (no need to mirror the entire root CHANGELOG; see
>    `packages/vscode/CHANGELOG.md` header for the curation rule).
> 4. Tag `v1.5.23`, push, then paste **the body below** (everything
>    under the "What changed" heading) into GitHub Releases.
> 5. Delete this draft file (or replace with the next draft).

---

## What changed in v1.5.23

This is primarily a **documentation + tooling polish** maintenance
release, plus one small but real **runtime fix** worth singling out
(see "Silent feedback-timeout truncation" under Highlights). The rest
of the shipped runtime is functionally unchanged from v1.5.22; every
other commit either fills a long-overdue documentation gap, hardens
the maintenance contract (CI Gate / pre-commit / coverage red line),
or aligns metadata with the actual project ownership. Operators can
drop in the new wheel / extension without config migration;
downstream packagers do not need to update integration scripts.

### Highlights at a glance

- **Server-side defense-in-depth caps on uploaded images
  (10 / 100 MB).** ``extract_uploaded_images`` previously trusted the
  ``image-upload.js`` client-side ``MAX_IMAGE_COUNT = 10`` /
  ``MAX_IMAGE_SIZE = 10 MB`` limits; a curl-based caller bypassing the
  client could push hundreds of images and let the process spend
  memory base64-encoding each one. Added
  ``MAX_IMAGES_PER_REQUEST = 10`` (mirrors client) and
  ``MAX_TOTAL_UPLOAD_BYTES = 100 MB`` (10 × per-file-cap), both
  truncating with ``continue`` not ``break`` and logging once per
  cap per request. Six locks in
  ``tests/test_upload_helpers_caps.py`` including a regex-grep parity
  test that ties ``MAX_IMAGES_PER_REQUEST`` to the client constant,
  preventing silent desync.
- **`service_manager.get_web_ui_config` cache no longer resurrects a
  stale config after a concurrent invalidate.** The 10 s TTL cache was
  protecting *both* read and write under the lock but doing the toml
  load (~5–50 ms) outside, so a file-watcher-triggered
  ``_invalidate_runtime_caches_on_config_change`` mid-load would clear
  the cache, then the in-flight load would re-write the pre-invalidate
  tuple over the cleared slot, leaving subsequent readers with a value
  the user already overwrote on disk — silent staleness for up to one
  full TTL window. Fixed with a generation-token pattern: every
  invalidate bumps ``_config_cache_generation``; cache misses snapshot
  it under the lock, the load runs unlocked as before, and write-back
  re-checks equality and drops the write on mismatch. Three locks in
  ``tests/test_web_ui_config.py::TestGetWebUIConfigGenerationToken``,
  including a reverse-lock that removing the generation check
  immediately re-introduces the bug.
- **`LogDeduplicator` now wall-clock-immune (monotonic time fix).**
  ``should_log`` previously used ``time.time()`` for its 5 s
  ``time_window`` check; if the wall clock moved backwards (NTP
  resync, manual clock adjustment, VM resume-from-suspend, DST
  tail-overlap on naive systems), ``current_time - last_time``
  went negative, ``≤ window`` was trivially true forever, and
  the same ERROR line was silently squelched indefinitely —
  worst-class observability failure (Heisenbug with blast-radius
  scaling to how long the clock stayed backwards). Now uses
  ``time.monotonic()``, the textbook-correct primitive for
  "X seconds elapsed" windows. Two locks in
  ``tests/test_enhanced_logging.py::TestLogDeduplicatorMonotonic``:
  static source-grep that ``should_log`` doesn't revert to
  ``time.time()``, and a black-box test that monkey-patches
  ``time.time`` to report one hour in the past — dedup must
  still allow the fresh log through.
- **MCP-side timeout no longer creates ghost web_ui tasks.**
  ``wait_for_task_completion``'s ``asyncio.wait_for`` TimeoutError
  branch returned ``_make_resubmit_response`` to the AI client but
  never told ``web_ui`` to clean its ``task_queue``. The AI then
  re-invoked ``interactive_feedback`` with a fresh ``task_id`` —
  the old task was still ACTIVE so the new one queued PENDING,
  the Web UI ``current_prompt`` (bound to ACTIVE) still showed the
  old prompt, the user typed feedback that wired back to the
  *old* ``task_id``, and the MCP side waiting on SSE for the *new*
  ``task_id`` would loop forever. The fix adds a finally-block
  ``_close_orphan_task_best_effort`` that POSTs
  ``/api/tasks/<id>/close`` when ``result_box[0] is None`` (covers
  TIMEOUT, KeyboardInterrupt, parent cancel simultaneously),
  with 2 s short timeout, every non-CancelledError swallowed,
  ``CancelledError`` re-raised so asyncio cancel semantics survive,
  and 404 downgraded to debug. Five locking tests
  (``tests/test_server_functions.py::TestGhostTaskCleanupOnTimeout``):
  timeout path *must* close, completed path *must not* close (would
  race with ``/api/submit → complete_task``), 404 path *must not*
  close, close failure *must not* propagate, ``CancelledError``
  *must* re-raise.
- **`ConfigManager.reload()` external-edit-wins race fix.**
  When ``cfg.set(...)`` queued a 3-second batch save and the
  user edited ``config.toml`` in their IDE during that window,
  ``_load_config`` would read the external bytes into
  ``self._config`` but the still-armed ``_save_timer`` would
  fire on the original tick and clobber the disk with the
  in-memory ``_pending_changes``. Net effect: external edit
  silently lost, no warning, last-write-wins. ``_load_config``
  now clears ``_pending_changes`` and cancels ``_save_timer``
  under the lock on every reload (with a WARNING log listing
  the discarded keys); matches operator intuition that "if I
  edited the file, my edit should win". Reproduced + locked by
  ``tests/test_config_manager.py::TestReloadDiscardsPendingChanges``
  (4 tests, including the full T0→T3 race).
- **mDNS startup no longer crashes the entire Web UI on a bad
  publish address or busy Avahi.** ``Zeroconf()`` and
  ``socket.inet_aton(publish_ip)`` / ``ServiceInfo(...)`` were
  unprotected, so EADDRINUSE / WinError 10049 / ENETUNREACH /
  illegal-IP-string would propagate up out of
  ``WebFeedbackUI.run()`` and prevent startup — violating the
  documented contract that mDNS failure must degrade
  gracefully to IP/localhost-only access. Both call-sites now
  wrap the failure in ``try/except``, log a WARNING with
  ``exc_info``, print a user-visible degradation notice, and
  return early so ``WebFeedbackUI.run()`` continues.
  ``tests/test_web_ui_config.py::TestMdnsConstructorFailures``
  exercises both branches via mock injection (2 tests).
- **AppleScript ``maxBuffer`` overflow no longer reports as
  TIMEOUT.** When ``osascript`` produces > ``maxBufferBytes``
  of combined stdout+stderr, Node throws
  ``ERR_CHILD_PROCESS_STDIO_MAXBUFFER`` *with*
  ``killed=true / signal=SIGTERM``. The previous classifier
  checked only ``killed`` / ``signal`` and surfaced
  ``APPLE_SCRIPT_TIMEOUT``, sending users on a wild goose
  chase to bump ``timeoutMs``. The classifier in
  ``packages/vscode/applescript-executor.ts`` now distinguishes
  the two and surfaces ``APPLE_SCRIPT_OUTPUT_TOO_LARGE``,
  preserving the existing TIMEOUT vs FAILED ladder for
  everything else. New
  ``packages/vscode/test/applescript-executor.test.js::maxBuffer``
  test injects a fake ``execFile`` reproducing the exact error
  shape Node throws, locking the disambiguation.
- **VSIX size budget guard added.**
  ``scripts/package_vscode_vsix.mjs`` reads the post-package
  ``.vsix`` byte size and applies a two-tier check: WARN at
  4 MB and FAIL (``process.exit(1)``) at 6 MB packed. Current
  1.5.x ships at ~2.7 MB packed, leaving generous headroom for
  normal feature work but tripping immediately if a bundle
  accident pushes the artifact into the multi-MB range.
  Defaults overridable via env var
  ``AIIA_VSCODE_VSIX_{WARN,MAX}_PACKED_MB`` for one-off
  intentional jumps. Companion
  ``tests/test_vscode_vsix_size_budget.py`` (6 tests)
  statically locks the default constants in [1, 50] MB sane
  range and asserts WARN ≤ FAIL, so a reviewer cannot silently
  disarm the guard by raising the default.
- **Bark double-push when `bark_timeout > 15s` is fixed.**
  ``_process_event``'s ``as_completed(timeout=15)`` was hardcoded
  even though Pydantic ``coerce_bark_timeout`` accepts ``[1, 300]``.
  Users on cross-region networks who configured ``bark_timeout = 30``
  saw two iOS pushes per logical event: ``as_completed`` would time
  out at 15s → retry path triggered → original Bark request still
  in-flight returned 200 (push #1) → retry returned 200 (push #2).
  Window now scales as ``bark_timeout +
  _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS`` (default buffer 5s).
  ``tests/test_notification_manager.py::TestProcessEventBarkTimeoutWindow``
  locks the contract with 6 unit tests including a reverse-lock on
  the buffer constant.
- **SSE silent disconnect on slow clients is fixed.** ``_SSEBus``
  used to ``discard`` slow consumers from ``_subscribers`` without
  notifying the generator on the other side; the browser kept
  receiving heartbeats but real ``task_changed`` events stopped
  flowing → user's task list silently froze. New
  ``_SSE_DISCONNECT_SENTINEL`` is injected into the queue when a
  consumer is forced out, generator returns on it, browser sees EOF
  + auto-reconnect → fresh subscription. New
  ``tests/test_sse_bus_disconnect.py`` (6 tests) locks the contract,
  including a reverse-lock that the sentinel must be ``object()``
  identity (not ``None`` / ``False`` / ``""`` which would collide
  with legitimate payloads).
- **Settings debounce no longer drops your edits across fields.**
  ``debounceSaveFeedback`` (Web UI ``static/js/settings-manager.js``
  + VSCode webview ``packages/vscode/webview-settings-ui.js``)
  used a `setTimeout` closure that captured the most-recent
  `updates` argument; a `clearTimeout` followed by a fresh
  `setTimeout` silently DISCARDED the prior payload. So editing
  `frontend_countdown` then within 800ms editing `resubmit_prompt`
  would only POST the second field, leaving the first edit
  unsaved with no error toast. The fix collects updates into a
  `pendingUpdates` buffer via `Object.assign(...||{}, updates||{})`
  and the timer drains it as a single merged POST. New
  `tests/test_debounce_save_feedback_accumulates.py` locks the
  Web/VSCode parity contract (3 tests), including a *bidirectional*
  parity gate that fails when only one mirror gets fixed.
- **Notification retry jitter (0–50%) added to defeat
  thundering-herd on synchronized failures.**
  `NotificationManager._schedule_retry` previously used a fixed
  `retry_delay`, so when multiple in-flight Bark / Web /
  System sends failed within a single ms the retries fired in
  exact lock-step → spike load on the upstream and a higher
  chance of correlated re-failure. New
  `_RETRY_DELAY_JITTER_RATIO = 0.5` adds `random.uniform(0,
  base_delay * 0.5)` jitter; the base delay is preserved as a
  floor so the existing fixed-delay contract still holds.
  `tests/test_notification_manager.py::TestScheduleRetryJitter`
  (5 tests) locks the bound and verifies the constant cannot be
  silently inflated past 1.0 (which would let jitter > base
  delay and let order-of-arrival depend on luck).
- **`SystemNotificationProvider`'s plyer `timeout` magic number
  (`10.0`) now lives in `_DISPLAY_DURATION_SECONDS`** with a
  documented invariant that the value is a *banner display
  duration*, not a *send timeout*. plyer has no async surface;
  the call is synchronous and blocks until the platform API
  returns (osascript / balloon notification / libnotify). The
  fallback for an actually-stuck platform call is
  `NotificationManager._process_event::as_completed(timeout=
  bark_timeout + buffer)`, which is now explicitly cross-linked
  in both source files. Reverse-locked by
  `tests/test_notification_providers.py::TestSystemProviderSend`
  (2 new tests, including a `[3, 30]` range justification on
  the constant).
- **i18n fuzz parity coverage extended to ICU corner cases.**
  The original 200-sample `tests/test_i18n_fuzz_parity.py`
  covered `literal | mustache | plural | selectordinal | select`
  up to depth 2, plus `'` / `#` / `{not-a-brace}` tokenizer
  edges — but four ICU-standard corner cases were silently
  untested for the project's lifetime: `=N` literal-value
  branch in `_selectPluralOption` (line 410), empty plural arm
  body `one {}`, multi-codepoint Unicode (4-byte BMP+ emoji,
  ZWJ sequences `👨‍👩‍👧`, regional indicator flags `🇨🇳`,
  variation-selector + ZWJ `🏳️‍🌈`, combining marks
  `a\u0301`), and BiDi controls (LRM/RLM/LRE/PDF). New
  `EXT_SEED=0xFACECAFE` corpus of 100 samples forces each new
  sample through one of `{exact | empty_arm | emoji | bidi}`
  flavors; `n*` params land on 0/1 with 70% probability so
  `=0`/`=1` arms actually fire. Web ↔ VSCode `i18n.js` are
  byte-identical across all 102 new templates with zero PUA
  leakage and zero exceptions; the new gate locks the
  surrogate-pair-safe substring and BiDi pass-through
  invariants forever.
- **Frontend `frontend_countdown` input is no longer pinned at
  250s.** Even after the runtime fix below, the actual UI controls
  (Web UI HTML `<input max="250">`, VS Code webview HTML, and the
  two settings-manager JS guards `val <= 250`) silently rejected
  any user-typed value above 250 — so the bug was visible to
  operators trying to *raise* the countdown but not the underlying
  runtime constants. This release walks all four input surfaces
  up to `max="3600"` (mirroring `AUTO_RESUBMIT_TIMEOUT_MAX`),
  refreshes the five `?? 250` / `|| 250` fallbacks in
  `static/js/multi_task.js` to `?? 240` / `|| 240` (the actual
  `AUTO_RESUBMIT_TIMEOUT_DEFAULT`; 250 was the historical *MAX*,
  not *DEFAULT*), and refreshes the 13 user-facing copy lines that
  still said "Range 30-250" — both READMEs, `web_ui.py` docstring
  + argparse help, three OpenAPI yaml schemas under
  `web_ui_routes/`, and the four `autoResubmitTimeoutHint` /
  `countdownHint` i18n bundles. `tests/test_frontend_input_range_parity.py`
  locks all 13 magic numbers against
  `server_config.AUTO_RESUBMIT_TIMEOUT_{MAX,DEFAULT}` so the next
  refactor cannot drift again.
- **Silent feedback-timeout truncation fixed.** The four runtime
  clamp constants in `server_config.py`
  (`FEEDBACK_TIMEOUT_MIN/MAX`, `AUTO_RESUBMIT_TIMEOUT_MIN/MAX`)
  were stricter than the Pydantic `_clamp_int(...)` bounds in
  `shared_types.SECTION_MODELS::feedback`, so a user setting
  `frontend_countdown = 1000` in `config.toml` saw the value
  accepted by the schema, surfaced as "1000" in the Web UI's
  current-config panel, but at runtime `task_queue.py` and
  `web_ui_validators.py` (reading `AUTO_RESUBMIT_TIMEOUT_MAX = 250`)
  silently truncated the active countdown to 250. Same story for
  `backend_max_wait` (capped at 3600 instead of the documented
  7200). Constants now match `shared_types`'s `[10, 3600]` /
  `[10, 7200]` ranges and `tests/test_server_config_shared_types_parity.py`
  prevents regression by introspecting `BeforeValidator` closure
  cells. Configurations that previously hit the cap now actually
  take effect; configurations already inside the new range see
  identical behaviour.
- **`POST /api/reset-feedback-config` now actually resets all 4
  feedback fields (was: 3 of 4 silently).** The endpoint backing
  the Web UI's "Reset feedback config to defaults" button only
  included `frontend_countdown`, `resubmit_prompt`, `prompt_suffix`
  in its `defaults` dict — `backend_max_wait` was missing. So an
  operator who'd previously bumped `backend_max_wait` in
  `config.toml` (or via a now-fixed config edit path) and clicked
  "Reset" would see three fields revert and one silently retain
  the old value. Partial reset. Endpoint now imports
  `FEEDBACK_TIMEOUT_DEFAULT` and adds the fourth key, and a new
  AST-based parity test
  (`tests/test_reset_feedback_config_parity.py`) statically extracts
  the dict-literal keys and asserts equality with
  `SECTION_MODELS::feedback.model_fields` — so any future
  Pydantic-side field addition that doesn't update the endpoint
  fails CI before merge.
- **Silent HTTP-retry / HTTP-timeout truncation fixed.** Same
  pattern as feedback-timeout, on a different code surface: the
  six `WebUIConfig.ClassVar` clamp bounds in `server_config.py`
  (`TIMEOUT_MAX=300`, `MAX_RETRIES_MAX=10`, `RETRY_DELAY_MIN=0.1`)
  were stricter than the Pydantic `_clamp_int/_clamp_float(...)`
  bounds in `shared_types.SECTION_MODELS::web_ui`. So a user
  writing `[web_ui] http_request_timeout = 500` (or
  `http_max_retries = 15`, or `http_retry_delay = 0.05`) in
  `config.toml` saw the value accepted by Pydantic, but
  `service_manager._load_web_ui_config_from_disk` then
  re-constructed `WebUIConfig(timeout=500, ...)` and the
  `@field_validator` did a *second* clamp round — silently
  capping 500 → 300, 15 → 10, 0.05 → 0.1 (with a warning log,
  but the schema and config docs both promised the wider range
  was honoured). Bounds now match the Pydantic side
  (`[1, 600]` / `[0, 20]` / `[0, 60]`); the `web_ui` section was
  added to `tests/test_server_config_shared_types_parity.py`
  with three new introspection-based gates, so any future
  Pydantic edit (or `WebUIConfig.ClassVar` edit) that breaks
  parity will fail CI before merge.
- **Default-config inline range comments aligned with SECTION_MODELS.**
  The first surface a new operator reads — the `range/范围 [a, b]`
  hints in `config.toml.default` and `config.jsonc.default` — had
  five stale entries (`http_request_timeout`, `http_max_retries`,
  `http_retry_delay`, `backend_max_wait`, `frontend_countdown`)
  that drifted when `shared_types` widened its `_clamp_int` bounds
  earlier in v1.5.x. `tests/test_default_config_range_parity.py`
  uses the same introspection helper as the docs/configuration parity
  test to lock both templates against future drift.
- **Audience-first navigation** for the 30+ documents under `docs/`
  and the 20 automation scripts under `scripts/` — fresh
  contributors no longer have to grep titles to find their entry
  point.
- **Two new docs surfaces** that were structurally invisible
  before: `packages/vscode/CHANGELOG.md` (rendered on the VS Code
  Marketplace / Open VSX listing's "Changelog" tab, previously
  empty for every release) and `docs/troubleshooting{,.zh-CN}.md`
  (a bilingual FAQ for the eight most common deployment / runtime
  issues).
- **API reference refreshed** for the v1.5.x signature delta.
  `docs/api/server_config.md` (and Chinese mirror) finally exist
  after being implicitly broken since the v1.5.20 server-side
  refactor; nine other module pages picked up ~250 lines of net
  additions reflecting real signature changes.
- **CI Gate is now WARNING-clean across consecutive runs** —
  previously, a Loguru sink wired to `sys.__stderr__` would
  occasionally leak a `notification_manager` retry warning to
  the terminal (depending on `LogDeduplicator` cache state), making
  freshly-run pre-commit / CI output look noisy without any real
  test failure.
- **Coverage red line at 88 %** (current measurement 90.96 %), so
  future drift surfaces in pull requests instead of in production
  monitoring.
- **`LICENSE` aligned with project metadata** — `xiadengma` is now
  listed as the v1.5 series primary author alongside the upstream
  fork lineage (Pau Oliva 2025, Fábio Ferreira 2024). `pyproject.toml::authors`
  and `CITATION.cff::authors` had said this for releases; the
  licence header was the last lagging surface.
- **Top-level `Makefile` ships 11 thin-wrapper shortcuts** —
  `make ci`, `make test`, `make lint`, `make coverage`,
  `make docs`, `make docs-check`, `make vscode-check`,
  `make pre-commit`, `make clean`, `make install`, `make help`
  (default goal). Every target delegates to an existing
  `scripts/ci_gate.py`-or-friends invocation, so CI workflows
  and the local Makefile cannot drift.
- **Bilingual API reference is now structurally symmetric.**
  Three latent oversights were closed in one swoop: the
  English `index.md` gained the missing "Quick navigation"
  Core/Utility grouping (the Chinese version always had it);
  every Chinese `*.md` page now carries a back-link to its
  English signature-only sibling (the inverse direction
  already existed); and the Chinese index now opens with the
  parity subtitle "中文 API 参考（含完整 docstring 叙述）。"
  matching the existing English subtitle.
- **API reference covers three additional contract modules** —
  `protocol.py` (PROTOCOL_VERSION + Capabilities + ServerClock),
  `state_machine.py` (Connection / Content / Interaction state
  machines), and `i18n.py` (back-end locale-keyed message
  lookup). Total per-locale page count climbs from 11 to 14.
- **Configuration docs (`docs/configuration{,.zh-CN}.md`) are
  back in sync with `config.toml.default`** plus a new pytest
  regression gate (`tests/test_config_docs_parity.py`) that
  fails CI if they ever drift again. Three real drift points
  shipped silently in v1.5.x and were fixed in this wave:
  `[notification]::debug` and `[web_ui]::language` were absent
  from both bilingual tables; `docs/configuration.zh-CN.md::
  [mdns]::enabled` was still describing the pre-v1.5 contract
  (`null` default) instead of the runtime sentinel `"auto"`;
  the Chinese minimal example was a stale `jsonc` snippet
  although the recommended on-disk format has been TOML for
  the entire v1.5.x line.
- **`scripts/bump_version.py` now also synchronises
  `CITATION.cff::version`.** The script previously walked six
  version-bearing files (`pyproject.toml`, `uv.lock`,
  `package.json`, both `package-lock.json` paths,
  `packages/vscode/package.json`,
  `.github/ISSUE_TEMPLATE/bug_report.yml`) but silently skipped
  `CITATION.cff::version`. After running
  `bump_version.py 1.5.23` the citation file would still report
  `version: "1.5.22"` to Zenodo / academic citation tooling —
  and `--check` would not catch it. Both code-paths
  (`apply` + `--check`) now include CITATION.cff; covered by
  `tests/test_bump_version_citation.py` (13 cases). The
  `date-released` field is intentionally still publisher-owned
  (the script has no clock side-effect).

### Documentation

- **`GET /api/tasks` OpenAPI response schema now lists `deadline` as
  a per-task field (was silently misparented).** The docstring YAML
  in `web_ui_routes/task.py::get_tasks` had `deadline:` indented to
  the same column as `properties:`, so YAML treated it as a sibling
  key of `items.type` / `items.properties` rather than a child of
  `items.properties`. Result: every OpenAPI consumer (swagger-ui,
  generated TypeScript / Python clients, `swagger-cli validate`,
  `openapi-generator-cli`) saw a task object schema *without* a
  `deadline` field — but the live JSON response **did** contain
  `deadline` (set in `task_list.append(...)`), so downstream
  deserializers either silently ignored it or failed validation
  depending on strictness. The bug is invisible because YAML doesn't
  error on this kind of misindent; it just rebinds the key. Re-indented
  to align with sibling fields. Locked by
  `tests/test_openapi_input_range_parity.py::test_get_tasks_response_includes_deadline_under_items_properties`,
  which runs `yaml.safe_load` on the docstring and asserts
  `"deadline" in tasks.items.properties` — reverse-locked: re-applying
  the bad 24-column indent makes the test fail with an explicit
  pointer to the responsible docstring line.
- **`docs/README.md` + `docs/README.zh-CN.md` (new, bilingual)** —
  audience-first directory index for the 30+ markdown files. Splits
  navigation into four roles: end users, contributors, operators,
  reviewers. Replaces the previous "grep + guess" experience.
- **`scripts/README.md` (new)** — one-liner index for all 20
  automation entry points (CI Gate orchestrator, eight i18n static
  gates, three generators, asset/packaging pipeline, three test
  harnesses, coverage wrapper).
- **`docs/troubleshooting.md` + `docs/troubleshooting.zh-CN.md` (new,
  bilingual)** — focused FAQ covering the eight most common deployment
  / runtime issues (port-in-use, blank VS Code panel, empty task
  list / SSE replay, notification channels silence triage, mDNS
  `ai.local` resolution, Open in IDE no-op, PWA install hiccups,
  TOML migration). Each entry follows symptom → cause → fix.
  `SUPPORT.md` updated with cross-links.
- **`packages/vscode/CHANGELOG.md` (new)** — the VS Code Marketplace
  and Open VSX render the extension package's own `CHANGELOG.md` on
  the listing's "Changelog" tab. This project shipped six releases
  with an empty Changelog tab; the new file is a curated per-release
  excerpt of the extension-relevant changes from v1.5.20 onwards,
  with a link back to the root `CHANGELOG.md`. Wired into the VSIX in
  two places (`package.json::files` and
  `scripts/package_vscode_vsix.mjs::includeList`) with explicit
  inline comments documenting the dual-declaration invariant.
- **`packages/vscode/README.md` + `.zh-CN.md`** gain two new
  sections:
  - `i18n.pseudoLocale` _(experimental)_ setting — declared in
    `package.json` for several minor releases but had zero
    end-user documentation, so QA folk wanting to spot
    hardcoded strings or layout overflow could not discover it.
  - **AppleScript executor (macOS only) · security model** — full
    enumeration of the seven safeguards baked into
    `applescript-executor.ts` (platform check, absolute
    `/usr/bin/osascript` path, stdin script delivery, 8 s hard
    timeout, 1 MiB output cap, log redaction, no user-supplied
    scripts). `SECURITY.md` already mentioned the executor in the
    "Out of scope" section; this expansion lets reviewers verify
    the assertion at source.
- **Removed phantom `ai-intervention-agent.enableAppleScript`
  reference from both root READMEs** — the setting key has not been
  declared in `packages/vscode/package.json::contributes.configuration`
  for several minor releases (the AppleScript path is gated only by
  the macOS native notification toggle inside the panel UI). Replaced
  with a one-line pointer to the VS Code extension README.
- **API reference (`docs/api/` + `docs/api.zh-CN/`) refreshed to match
  current source.** Adds `server_config.md` (missing since the v1.5.20
  refactor) and brings nine other module pages up to date with the
  v1.5.x signature delta. `scripts/generate_docs.py` also gained a
  `--check` mode (idempotent byte-level compare against on-disk files)
  and three latent generator-style bugs were fixed (trailing newline,
  italic emphasis style, blank lines around H3 + thematic-break) so
  future regenerations do not re-introduce noise.
- **OpenSSF Scorecard workflow status badge** added to both root
  READMEs, advertising the `scorecard.yml` GitHub Actions workflow's
  pass/fail state. Once the public OpenSSF API begins ingesting the
  repo, this can be swapped to the canonical
  `shields.io/ossf-scorecard/...` endpoint for the actual numeric
  score.
- **Markdown canonicalisation in `CHANGELOG.md` and
  `docs/security/AUDIT_2026-05-04.md`** — table column alignment
  normalised to GitHub-style left-anchored, italic emphasis switched
  from `*…*` to `_…_` so future style sweeps can use a single regex.
- **Bilingual `README` Acknowledgements section** formalises the
  upstream lineage. Pairs with the `LICENSE` backfill above:
  links to [`noopstudios/interactive-feedback-mcp`](https://github.com/noopstudios/interactive-feedback-mcp)
  (Fábio Ferreira, 2024) and
  [`poliva/interactive-feedback-mcp`](https://github.com/poliva/interactive-feedback-mcp)
  (Pau Oliva, 2025), and explicitly scopes the v1.5.x rewrite
  (Web UI, VS Code extension, i18n, notification stack, CI/CD)
  to `xiadengma`.
- **`README` Documentation index now cross-links
  `packages/vscode/CHANGELOG.md`** so visitors don't have to
  grep the tree to find the Marketplace-specific changelog.
- **`packages/vscode/README{.zh-CN}.md` gain a Changelog
  section** with two bullets — extension-only changelog
  (relative link, resolves through the Marketplace's URL
  rewriter) and the repository-wide changelog (absolute URL
  for safety on Marketplace renderers).
- **`make` shortcuts surfaced in `CONTRIBUTING.md::§2 Local
  CI Gate` and `docs/workflow{.zh-CN}.md`** so contributors
  reading the entry-point pages discover the alias instead of
  only seeing the long-form `uv run python scripts/ci_gate.py …`.
- **PR template `.github/PULL_REQUEST_TEMPLATE.md::§Local
  verification`** now lists the `make ci` / `make vscode-check`
  / `make docs-check` aliases alongside the long-form
  invocations, closing the consistency gap with
  `CONTRIBUTING.md` and `docs/workflow*.md`.
- **`docs/README{,.zh-CN}.md` API-module list synced with
  `MODULES_TO_DOCUMENT`** — both bilingual indexes were still
  enumerating the pre-`a8db779` module set; refreshed to the
  Core / Utility grouping that mirrors the auto-generated
  index, plus a `make docs-check` callout so contributors
  who add a new module see the verification command on the
  same page.
- **`docs/security/AUDIT_2026-05-04.md::STATUS line** no
  longer carries a `<TBD>` placeholder for the remediation
  commit hash — replaced with a deep-link to commit
  `95e4151` (the `:lock: chore(deps): security wave …`
  commit that actually closed all 17 runtime CVEs). A
  forensic-trail token in a security artefact should not
  read as "remediation pending" when remediation has
  shipped.
- **`docs/workflow{,.zh-CN}.md` ad-hoc Locale-check entry
  now points at the modern `scripts/check_i18n_locale_parity.py`**
  instead of the legacy key-only `scripts/check_locales.py`,
  with a parenthetical explaining the legacy survives only
  for backward compatibility.
- **API reference now covers every project-root `*.py` module
  (23 of 23, was 14).** The round-8 audit introduced an
  `IGNORED_MODULES` set in `scripts/generate_docs.py` to make
  the previously-implicit "we deliberately skip these" choice
  visible (with `TODO` markers and a per-module rationale), and
  added a classification invariant
  (`tests/test_docs_module_classification_parity.py`) so a new
  module can no longer slip in undocumented. Round-8/9 then
  discharged the entire backlog by graduating all 9 originally
  ignored modules in three sequential commits — `server.py`,
  `web_ui.py`, `server_feedback.py`, and a final batch of 6
  (`service_manager.py`, `web_ui_security.py`,
  `web_ui_validators.py`, `web_ui_config_sync.py`,
  `web_ui_mdns.py`, `web_ui_mdns_utils.py`). `IGNORED_MODULES`
  is now an empty `frozenset[str]`, the largest visible
  documentation gap in v1.5.x is closed, and the bilingual
  `docs/README{,.zh-CN}.md` index plus the auto-generated Quick
  navigation in `docs/api(.zh-CN)/index.md` enumerate every
  module under both Core and Utility groupings. Per-locale page
  count climbs from 14 to 23. No source-side change in any of
  the four graduation commits — the new pages render existing
  module/function docstrings, so the underlying public API
  surface is unchanged.

### Tests

- **New regression gate
  (`tests/test_config_docs_parity.py`)** locks the contract
  that every key declared in `config.toml.default` must
  appear in *both* `docs/configuration.md` and
  `docs/configuration.zh-CN.md` as a backticked entry in
  the matching `### \`<section>\`` table — and vice versa
  (no orphan documented keys). Complements the existing
  `tests/test_config_defaults_consistency.py` (runtime
  default dict ↔ TOML template). 5 new tests; pytest total
  climbs from 2244 to 2249. The TOML / doc parsers each
  carry a self-check so refactoring the regex later cannot
  silently weaken the gate.
- **Six new introspection-based parity gates** lock the
  numeric clamp bounds, default values, and reset-endpoint field
  coverage in `shared_types.SECTION_MODELS` against the six
  surfaces that historically drifted (or could drift in the
  future):
  - `tests/test_server_config_shared_types_parity.py`
    asserts `server_config.{FEEDBACK_TIMEOUT_MIN/MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN/MAX}` equal the
    `(min, max)` pulled directly from the
    `BeforeValidator` closure cells of
    `feedback.{backend_max_wait, frontend_countdown}`, and
    additionally asserts the six `WebUIConfig.ClassVar`
    bounds (`TIMEOUT_MIN/MAX`, `MAX_RETRIES_MIN/MAX`,
    `RETRY_DELAY_MIN/MAX`) equal the
    `web_ui.{http_request_timeout, http_max_retries,
    http_retry_delay}` Pydantic ranges — closing the same
    silent-truncation gap on the HTTP-retry surface. 5 tests
    total (2 feedback + 3 web_ui).
  - `tests/test_default_config_range_parity.py` walks both
    `config.toml.default` and `config.jsonc.default` with
    format-aware regex, parses every `range/范围 [a, b]`
    inline comment, and asserts equality against the same
    introspected bounds. 2 tests; ~5 ranges captured per
    file (sanity-checked).
  - `tests/test_frontend_input_range_parity.py` covers the
    four frontend input controls (Web UI HTML / settings JS,
    VS Code webview HTML / settings JS) plus the five
    `?? 250` / `|| 250` fallbacks in `static/js/multi_task.js`,
    asserting that all 13 magic numbers stay in sync with
    `server_config.AUTO_RESUBMIT_TIMEOUT_{MAX,DEFAULT}`. The
    multi_task sweep self-checks by requiring at least 5
    captures so a regex regression cannot vacuously pass.
    5 tests.
  - `tests/test_server_config_defaults_parity.py` is the
    sister gate to `test_server_config_shared_types_parity.py`
    — that one locks MIN/MAX clamp bounds, this one locks
    field DEFAULTS (the parallel invariant that controls
    first-load values + what the panel's "reset to defaults"
    button writes back). All four feedback constants
    (`FEEDBACK_TIMEOUT_DEFAULT`,
    `AUTO_RESUBMIT_TIMEOUT_DEFAULT`,
    `RESUBMIT_PROMPT_DEFAULT`, `PROMPT_SUFFIX_DEFAULT`) are
    pulled directly from `model_fields[name].default` and
    asserted to equal the imported `server_config` values.
    4 tests.
  - `tests/test_notification_config_parity.py` covers the
    fifth (and last historically-vulnerable)
    "config layer that re-clamps Pydantic-validated values"
    surface: `NotificationConfig`'s four `coerce_*`
    validators (`retry_count`, `retry_delay`, `bark_timeout`,
    `sound_volume`). Today's bounds happen to match
    `SECTION_MODELS::notification` exactly, but no CI gate
    locked that — a future Pydantic-side widening would have
    silently re-introduced the truncation pattern. Uses
    **black-box behaviour assertions** (feed an oversized /
    undersized value, confirm clamp-result equals the
    introspected Pydantic max / min) so it works regardless of
    whether the validator is hardcoded inline or
    `ClassVar`-driven. The `sound_volume` percentage / decimal
    scale mismatch (Pydantic `[0, 100]` vs runtime `[0.0, 1.0]`,
    `from_config_file` divides by 100) is asserted explicitly
    so a future refactor can't break the implicit ÷100 contract
    silently. 8 tests.
  - `tests/test_reset_feedback_config_parity.py` covers the
    "reset endpoint partial coverage" failure mode that the
    round-4 audit caught: the
    `POST /api/reset-feedback-config` endpoint's `defaults`
    dict literal must contain **every** field from
    `SECTION_MODELS::feedback`, not just the UI-visible subset.
    Uses Python's `ast` module to statically extract
    dict-literal keys (more direct than spinning up a Flask
    test client and inspecting the response), with a sanity
    check that ≥ 1 key is found so a refactor to
    `dict(...)`-constructor or comprehension form would fail
    loudly rather than vacuously pass. 1 test.
  - `test_frontend_input_range_parity.py` extended with a new
    `TestSettingsManagerFallbackDefault` class that locks
    `static/js/settings-manager.js::updateFeedbackUI`'s
    `frontend_countdown ?? 240` fallback to
    `AUTO_RESUBMIT_TIMEOUT_DEFAULT`. Sister gate to the
    existing `multi_task.js` 5-fallback sweep. The settings
    panel input element pulls from this fallback in the brief
    window before `/api/feedback-config` resolves; without
    this gate, a future `DEFAULT` change would silently leave
    the settings-panel skeleton showing the old number. 1
    test (total parity gate now covers 14 magic numbers across
    5 frontend files).

### Tooling / CI

- **`/api/events` SSE endpoint now has an explicit `300/min` rate
  limit instead of inheriting the global default `60/min`.** SSE is a
  long connection (one ``EventSource`` instance = one limiter token)
  but browsers auto-reconnect on flaky LAN, and a brisk page-reload
  cycle in dev / debug easily punches through 60/min — the limiter's
  ``429`` lands on the SSE handshake, ``EventSource.onerror`` fires,
  the polling fallback kicks in, and the observer blames the SSE
  pipeline rather than the limiter that rejected it. ``300/min``
  aligns with the ``/api/tasks`` neighbour and leaves headroom for
  multiple tabs / reconnect bursts. Intentionally **not**
  ``@limiter.exempt`` so a misbehaving client can't open unbounded
  connections. Three AST-driven locks in
  ``tests/test_sse_endpoint_rate_limit.py`` (existence + exact value
  + ``not exempt``).
- **`scripts/ci_gate.py` is now WARNING-clean.** A new session-scoped
  `autouse` fixture in `tests/conftest.py`
  (`_silence_loguru_sinks_during_tests`) drops the Loguru stderr
  sink at pytest startup. `assertLogs` continues to capture WARNING
  records as before; only the duplicate stderr drain is removed.
  Verified by two back-to-back `uv run python scripts/ci_gate.py`
  runs producing zero WARNING / ERROR / FAIL / RETRY lines.
- **`scripts/generate_docs.py --check`** introduced as a
  drift-detection mode. The same script can now emit an
  authoritative diff list + remediation command when the
  `docs/api(.zh-CN)/*` files don't match current Python source.
  Idempotent: two consecutive invocations produce zero `git diff`.
- **`docs/api(.zh-CN)/*` drift detection promoted to fail-closed.**
  Round-6 audit caught `docs/api/task_queue.md` (English) drifting
  one round behind the Chinese mirror after a DRY refactor of
  `task_queue.add_task` — the warn-level gate had been emitting
  the warning across multiple CI runs but nobody acted on it.
  `scripts/ci_gate.py` now invokes both `generate_docs.py --lang
  {en,zh-CN} --check` via the fail-closed `_run` helper (with a
  `label` suffix in the failure message pointing at the exact
  remediation command). The upgrade history is preserved in an
  inline comment in `ci_gate.py` so future maintainers understand
  why warn-level was rejected.
- **Local-CI parity holes closed** — two pre-existing maintenance
  scripts that lived in `scripts/` but were never wired into
  `scripts/ci_gate.py` are now part of the fail-closed pipeline,
  so `make ci` / `make pre-commit` finally see them:
  - `scripts/check_locales.py` covers two surfaces that the
    primary `check_i18n_locale_parity.py` does not touch:
    VS Code manifest translations
    (`packages/vscode/package.nls{,.zh-CN}.json`) and
    cross-platform `aiia.*` namespace alignment between Web UI
    and the VSCode webview locale bundles. Without it, a
    missing key in the manifest meant commands/views showed as
    raw `%key%` placeholders in one language at install time
    with no CI signal.
  - `scripts/bump_version.py --check` runs the eight-file
    version-sync invariant
    (`pyproject.toml`/`uv.lock`/`package.json`/`package-lock.json`
    × {root, plugin}, `bug_report.yml`, `CITATION.cff`)
    locally instead of only in the GitHub Actions matrix
    (Python 3.11 slice). Local pre-flight signal now matches
    remote CI signal exactly.
- **`scripts/minify_assets.py --check` switched from mtime
  heuristic to byte-level content comparison.** The previous
  `src.stat().st_mtime > dst.stat().st_mtime` test produced
  100% false positives on fresh CI runners and after every
  `git checkout` because checkout resets working-tree mtimes.
  New `content_drifts(src, dst, minify_func)` actually runs the
  minifier and byte-compares the output to the on-disk
  `.min.{js,css}`, reporting a real drift only when the
  contents differ. A missing destination or a minifier
  exception are both treated as drifts so CI surfaces problems
  loudly instead of silently fixing them. Default execution
  mode (no flag) keeps the mtime fast-path for incremental
  local rebuilds. 7 new unit tests
  (`tests/test_minify_assets_helpers.py`) lock the new
  contract, including a reverse-lock that fails immediately if
  a future contributor wires `needs_minification` back into
  the `--check` path.
- **Coverage red line (`fail_under = 88`) and report polish in
  `pyproject.toml`** — `[tool.coverage.run]` excludes test files
  and one-shot scripts so they cannot inflate themselves to 100 %;
  `[tool.coverage.report] fail_under = 88` defends the 90.96 %
  measurement with ~3 % volatility headroom; `skip_covered = true`
  cleans the term-missing report; `exclude_lines` recognises
  `pragma: no cover`, `raise NotImplementedError`,
  `if TYPE_CHECKING:`, and `if __name__ == "__main__":` so the
  metric stays honest without manual annotation.
- **`.pre-commit-config.yaml` gains three commonly-recommended
  hooks** (no new dependency — already pinned at `v5.0.0`):
  - `check-toml` — covers `pyproject.toml`, `config.toml.default`,
    `tests/fixtures/*.toml`. Sister hooks `check-yaml` /
    `check-json` were already on; the TOML omission left a
    malformed-bracket gap in `pyproject.toml` until `uv sync` /
    `uv build` would surface it.
  - `mixed-line-ending --fix=lf` — closes the loop with
    `.gitattributes`'s `* text=auto eol=lf`. Windows checkouts
    can produce CRLF on newly authored files until the first
    re-normalisation; the hook fixes it pre-push instead of
    waiting for CI.
  - `debug-statements` — guards against `breakpoint()` /
    `pdb.set_trace()` slipping into commits. Particularly nasty
    in the MCP server path because `pdb` blocks on `sys.stdin`
    (the MCP transport channel). `ruff`'s `T20` does not catch
    this.
- **Top-level `Makefile` (new)** — 11 thin-wrapper targets
  expose `make {ci,test,lint,coverage,docs,docs-check,
  vscode-check,pre-commit,clean,install,help}`. Pure
  delegation; CI surface unchanged (`.github/workflows/test.yml`
  still calls `scripts/ci_gate.py` directly). `.DEFAULT_GOAL :=
  help` makes `make` (no args) print the table.

### Packaging / metadata

- **PyPI metadata enrichment in `pyproject.toml`** — added four
  classifiers that were missing despite the underlying capability
  shipping for several minor releases:
  - `Environment :: Web Environment`
  - `Framework :: Flask`
  - `Natural Language :: English`
  - `Natural Language :: Chinese (Simplified)`
  - and a `Discussions` entry under `[project.urls]` mirroring
    the route already advertised in `.github/ISSUE_TEMPLATE/config.yml`.
- **`Development Status` graduated to `5 - Production/Stable`**
  in `pyproject.toml`, reflecting v1.5.x's shipped track record
  (2244 passing tests, 90.96 % line coverage, zero production
  CVEs) — the previous `4 - Beta` was an unnecessary speedbump
  for adopters scanning the project page.
- **`LICENSE` now lists `xiadengma` alongside the upstream
  copyright holders** (Pau Oliva, Fábio Ferreira). `pyproject.toml::authors`
  and `CITATION.cff::authors` had declared `xiadengma` as project
  author for the entire v1.5 series; the licence file was the last
  lagging metadata surface. Pure copyright-holder list change; the
  MIT permission terms are unchanged.

### How to verify before tagging

```sh
# Run the full local CI Gate (≈ 50 s):
uv run python scripts/ci_gate.py
# Or via the new Makefile shortcut: `make ci`

# Optionally include the VS Code extension test suite + VSIX build
# (slower; needed before pushing the Marketplace artefact):
uv run python scripts/ci_gate.py --with-vscode
# Or: `make vscode-check`

# Confirm the API references are in sync (now part of ci_gate as a
# warn-level check; this is the explicit form):
uv run python scripts/generate_docs.py --lang en --check
uv run python scripts/generate_docs.py --lang zh-CN --check
# Or: `make docs-check`

# Coverage red line check (CI runner uses --with-coverage; locally
# you can opt in):
uv run python scripts/ci_gate.py --with-coverage
# Or: `make coverage`
```

### Compat note

Runtime API surface is identical to v1.5.22:
`interactive_feedback`'s tool schema, all Web UI routes, the VS Code
extension's command IDs, and the `config.toml` shape are unchanged.
Bumping is safe; you can roll back to v1.5.22 by re-installing the
old wheel / extension if your environment requires bisection
testing. No data migration is required.
