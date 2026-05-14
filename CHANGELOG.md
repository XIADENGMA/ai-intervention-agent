# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Earlier history (versions ≤ 1.5.19) lives in the git log only.

## [Unreleased]

### Added

- **R237 / Cycle 15: dialog/modal ARIA compliance invariant
  (a11y wave 4)**. Cycle 14's WCAG 4.1.2 sweep (R230
  decorative SVGs → R232 icon-only buttons → R235 form
  inputs) covered the **control** layer. R237 covers the
  **modal** layer: every `role="dialog"` element in
  `web_ui.html` (currently `#code-paste-panel` +
  `#settings-panel`) must have `aria-modal="true"` (WAI-ARIA
  1.2: tells AT this is a true modal, focus should not
  escape) and `aria-labelledby` (referencing an *existing*
  id in the document — dangling references are explicitly
  flagged) or `aria-label` (WCAG 4.1.2 accessible name).
  Audit found the existing 2 dialogs **already** meet all
  3 requirements — R237 is a "lock current good state"
  invariant in the same spirit as R232. Adds a sanity check
  that dialogs start hidden via `class="hidden"` or `[hidden]`
  attribute (otherwise page-load would immediately trap
  focus). Guarded by
  `tests/test_dialog_aria_compliance_invariant_r237.py`
  (4 cases): aria-modal=true + aria-labelledby/label
  present + labelledby target id exists + starts hidden.
  Out of scope (deliberate, F-cycle15-1 follow-up): actual
  Tab/Shift-Tab focus-trap behavior + focus restore on
  close + `inert` on background.

- **R236 / Cycle 15 · F-cycle14-1: `ty` static type-checker
  now runs as a pre-commit hook** (mirrors R226's promotion
  of precompress-freshness from CI to pre-commit). Root
  cause for promotion: v1.7.5 release (Cycle 13) was
  abandoned because `ty` caught an `unresolved-attribute`
  type-narrowing error on `re.Match | None` (using
  `self.assertIsNotNone(match)` instead of PEP 484 standard
  `assert match is not None`) **only in release CI**,
  forcing v1.7.6 supersession + wasted release roundtrip.
  R236 fix: add `ty-check` hook to
  `.pre-commit-config.yaml` running `uv run ty check .` on
  any `*.py` change (~800-1200 ms with incremental cache,
  same tier as ruff). Now `ty` errors fail-closed at
  `git commit` time instead of after push → CI → 5-min
  feedback loop. **Important**: `ci_gate.py` still invokes
  `ty` as the source-of-truth (pre-commit is a fast shadow
  for developer speed; CI is the contract for `--no-verify`
  or unhooked checkouts). Guarded by
  `tests/test_ty_precommit_hook_invariant_r236.py` (5 cases):
  hook exists in `.pre-commit-config.yaml` + entry actually
  runs `ty check` (not no-op rename) + files filter matches
  `*.py` + hook runs at default `[pre-commit]` stage (not
  moved to manual/pre-push) + `ci_gate.py` still invokes
  `ty`. Removing this hook requires explicit owner approval
  via `ai-intervention-agent` (documented in the test
  docstring).

## [1.7.7] - 2026-05-14

> Cycle 14 release. **Theme: accessibility wave + drift guards.**
> Three-stage WCAG 4.1.2 sweep on top of Cycle 13's R230 SVG fix:
> R232 (icon-only buttons), R235 (form inputs + textareas). Plus
> two drift-detection guards (R231 invariant-catalogue staleness,
> R233 README factual claims) and a UI/UX consistency follow-up
> (R234 textarea disabled visual to CSS, parallel to R229 buttons).
> 5,670 tests + 816 subtests all green, all 8 drift guards
> (brand-color, CHANGELOG-lint, precompress, catalogue, ty, ruff,
> i18n parity, README claims) green.

### Documentation

- **CR#27 / Cycle 14 code review** (`docs/code-reviews/cr27.md`).
  Covers R231→R235 + v1.7.5/v1.7.6 release-supersession event
  (6 commits since CR#26). Theme: **three-wave WCAG 4.1.2
  accessibility sweep** (R230 decorative SVGs → R232 icon-only
  buttons → R235 form inputs) plus drift-detection guards
  (R231 catalogue, R233 README factual claims) and a UI/UX
  disabled-state consistency follow-up (R234 textarea
  parallel to R229 buttons). Per-commit audit + health
  verdict (HEALTHY) + F-cycle14 backlog (7 candidates, with
  F-cycle14-1 `ty` to main-branch CI recommended first for
  Cycle 15). Release recommendation: **v1.7.7** packing
  R231–R235.

### Fixed

- **R235 / Cycle 14 · F-cycle13-2 follow-up: form inputs +
  textareas now uniformly expose an accessible name (WCAG
  4.1.2 enforcement)**. Audit run after R230 (decorative
  SVGs) + R232 (icon-only buttons) found that the form-input
  side still had three a11y gaps in `web_ui.html`:
  (1) `#feedback-text` (the **primary** feedback textarea
  R234 just refactored) had `placeholder` but no `aria-label`
  — screen reader users heard "edit, blank" with no purpose;
  (2) `#code-paste-textarea` (the iOS clipboard-fallback
  paste pad) had the same issue; (3) `#file-upload-input` was
  hidden via `class="hidden"` but lacked `aria-hidden="true"`
  + `tabindex="-1"`, meaning keyboard users could land on an
  invisible focus target (`#quick-phrases-import-file` next
  to it already had the correct pattern — inconsistent).
  Fix adds `data-i18n-aria-label` + initial `aria-label` to
  both textareas (with new bilingual i18n keys
  `page.feedbackTextareaAriaLabel` = "Feedback message" /
  "反馈内容" and `page.codePasteTextareaAriaLabel` =
  "Paste code to insert" / "粘贴要插入的代码"), and aligns
  `#file-upload-input` with the existing
  `aria-hidden="true" tabindex="-1"` pattern. Guarded by
  `tests/test_form_inputs_accessible_name_invariant_r235.py`
  (3 cases, scanning all `<input>` + `<textarea>` in
  `web_ui.html`): every form control must have an accessible
  name via wrapping `<label>`, `<label for>`, `aria-label`,
  `aria-labelledby`, **or** the hidden-pattern
  `aria-hidden=true + tabindex=-1`; all hidden file inputs
  must use the consistent pattern; total input count must
  stay in the [18, 40] sanity window. Closes the WCAG 4.1.2
  loop opened by Cycle 13's a11y sweep.

- **R234 / Cycle 14 · F-cycle13-2: `.feedback-textarea`
  disabled visual now lives in CSS, not JS inline (light-theme
  bug parallel to R229)**. R229 fixed the same class of bug
  for `#submit-btn` + `#insert-code-btn` (CSS `!important`
  silently overriding JS inline color) but explicitly left
  `feedback-text` (the textarea) alone with a defensive
  invariant on the rationale that `.feedback-textarea` CSS
  did not use `!important`, so JS inline writes actually took
  effect. R234 reverses that decision after noticing the JS
  inline values were **all dark-theme-only hex codes**
  (`#2c2c2e` / `#8e8e93` / `rgba(255,255,255,0.03)` /
  `#f5f5f7`). On light theme the disabled textarea was
  rendered with dark colors over a beige page — same class of
  theme-incorrect-inline-override bug R229 fixed, just for a
  different element. Sinks the styling to CSS
  `.feedback-textarea:disabled` (dark) +
  `[data-theme="light"] .feedback-textarea:disabled` (light,
  with `!important` to win the cascade against the enabled
  rule's `!important`). JS now only flips the `disabled`
  attribute for all 3 elements (submit-btn, insert-code-btn,
  feedback-text) — consistent pattern. Guarded by
  `tests/test_feedback_textarea_disabled_css_invariant_r234.py`
  (7 cases): both themes have `:disabled` selectors + light
  rule uses `!important` + both rules declare all 4 visual
  cue properties (`background`, `color`, `cursor`,
  `border-color`) + both rules use `rgba(...)` half-transparent
  values to avoid R66 brand-color drift. R229's invariant
  test updated: `TestFeedbackTextareaInlineStyleKept` (which
  defensively locked the inline styling) replaced with
  `TestFeedbackTextareaInlineStyleRemovedByR234` (which now
  locks the *absence* of inline writes). Brand-color
  baselines unchanged (34 rgba decimal + 9 hex).

- **R233 / Cycle 14: README positioning paragraph's three
  factual claims now match reality + invariant guards them
  against future drift**. Audit found stale numbers in both
  EN + zh-CN READMEs' "Where AIIA sits on the spectrum"
  paragraph: "5,500+ tests + ~700 subtests" (actual: 5,643 +
  809 at v1.7.6) and "6-job release pipeline" (actual: 5
  jobs after a workflow refactor consolidated two). Updated
  both READMEs to "5,600+ tests + ~800 subtests" and "5-job
  release pipeline". Guarded by
  `tests/test_readme_factual_claims_invariant_r233.py`
  (11 cases): release-job count is exact-match to
  `.github/workflows/release.yml` (since jobs can be added OR
  consolidated, non-monotonic); test-count claim must be ≤
  reality (the "+" means floor) AND reality must not lead
  claim by more than `MAX_LAG_TESTS` = 500 (forces refresh
  before release-time review); subtest count uses a
  heuristic-estimated runtime count (static `subTest()` call
  sites × empirical loop-factor of 9, calibrated against
  v1.7.6 observed 89 sites → 809 runtime executions) with
  `MAX_LAG_SUBTESTS` = 200 tolerance; EN and zh-CN claims
  must match each other across locales. Pattern: this is a
  "doc claim does not silently rot" guard; same family as
  F-cycle12-1 (star-count freshness, still backlog).

### Added

- **R232 / Cycle 14 · F-cycle13-4: icon-only buttons must
  carry `aria-label` invariant**. R230 hid every decorative
  `<svg>` from assistive technology, which means **icon-only**
  buttons (no text sibling) now expose nothing but a bare
  `"button"` announcement to screen readers — unusable. Per
  WCAG 2.1 SC 4.1.2 (Name, Role, Value), every interactive
  control must have an accessible name. R232 audit found 28
  `<button>` + 1 `<a role="button">` in `web_ui.html` and
  zero icon-only ones missing `aria-label` (discipline was
  already perfect because R125b / R230 contributors knew the
  rule). R232 commits the audit result as a permanent guard.
  Guarded by
  `tests/test_icon_only_buttons_aria_label_invariant_r232.py`
  (3 cases / 3 subtests): every `<button>` and `<a
  role="button">` whose inner text (after stripping `<svg>`
  blocks + HTML comments) is empty MUST have `aria-label` or
  `aria-labelledby` + total button count stays ≥ 20 (sanity
  baseline) + 3 known icon-only buttons (`theme-toggle-btn`,
  `settings-btn`, `export-tasks-btn`) are explicitly locked
  to preserve their `aria-label` as regression anchors.

## [1.7.6] - 2026-05-14

Supersedes the abandoned `v1.7.5` tag. `v1.7.5` was tagged but
the Release CI workflow failed at the `ci_gate.py` (`ty` type
checker) step before any build artefacts were produced; no
PyPI / npm / GitHub Release / VSCode Marketplace publication
ever happened. `v1.7.6` ships the same R226–R230 payload plus
R231 (catalogue staleness guard) plus the ty-narrowing fix
for `tests/test_submit_btn_disabled_visible_invariant_r229.py`.

### Fixed

- **`tests/test_submit_btn_disabled_visible_invariant_r229.py`
  ty static-check failure**. R229's tests used
  `self.assertIsNotNone(match)` to guard `re.search(...).group(1)`
  access, but `ty` (and `mypy`) do not model unittest assert
  methods as type-narrowing operations, producing 5
  `unresolved-attribute` errors on `Match[str] | None`. Replaced
  with the standard `assert match is not None` pattern which
  both checkers recognize as narrowing. Pure test-quality fix;
  no behaviour change.

### Documentation

- **R231 / Cycle 14 · F-cycle13-1: invariant-test guide
  catalogue auto-staleness guard + R224 / R229 / R230
  backfill**. CR#26 §3 flagged the catalogue staleness risk —
  R227's original test only validated "entries point to real
  files" but never caught *missing* entries, so R230 silently
  shipped without a catalogue row. R231 adds
  `TestRecentInvariantsCataloged` to
  `tests/test_invariant_test_guide_catalogue_r227.py`: scans
  `tests/test_*_invariant_r*.py` filename pattern, derives the
  current highest R-number, and fails if any invariant test
  within the last `MAX_R_LAG` = 10 R-numbers is missing from
  the EN catalogue. The 10-cycle window gives in-cycle commits
  breathing room (1 R-cycle ≈ 5 commits, so window covers
  ~2 cycles) while still forcing refresh by the next code-
  review boundary. Also backfills R224 (per-provider Grafana
  dashboard, Pattern B), R229 (submit-btn disabled visual,
  Pattern A + C), and R230 (decorative SVG aria-hidden,
  Pattern A) into both the EN and zh-CN catalogue tables
  (R227-R230 catalogue staleness fully cleared).

## [1.7.5] - 2026-05-14

Cycle 13 catch-up release packing R226–R230 + CR#26. Pure
additive cycle: pre-commit guardrail (R226), bilingual
contributor docs (R227), two UX bug fixes (R228 + R229),
WCAG 1.1.1 a11y coverage (R230). No breaking changes; no
public API surface changes. v1.7.4 → v1.7.5 is a patch bump.

### Documentation

- **CR#26 — Cycle 13 code review (R226 → R230) archived**.
  Single-file `docs/code-reviews/cr26.md` covering 5 commits
  (DX guardrail R226, contributor docs R227, UX-bug R228 +
  R229, a11y R230), per-commit audit, health verdict,
  8 follow-up candidates (4 new in CR#26 + 4 carried from
  CR#25), v1.7.5 release packaging recommendation.

### Fixed

- **R230 / Cycle 13: every decorative `<svg>` in the Web UI now
  carries `aria-hidden="true"` + `focusable="false"`**.
  Accessibility audit triggered by R229's button-state work:
  `web_ui.html` had 31 SVG icons but only 2 were properly
  hidden from assistive technology. The other 29 (button icons,
  section-header icons, theme-toggle sun/moon, GitHub link icon,
  product logo) were exposed to screen readers as `"graphic"`,
  which meant a user pressing the submit button heard `"graphic
  Submit feedback button"` — the leading `"graphic"` adds zero
  information but consumes listening time, and any nested
  `<title>` / `<desc>` elements would be read out on top of the
  text label, producing severe noise. WCAG 2.1 SC 1.1.1
  explicitly allows decorative content to be skipped by AT, and
  the project already had the correct pattern in two places
  (`export-tasks-btn` SVG at L340, `multi-task copy-link` SVG
  at L1687). R230 completes the coverage uniformly across all
  three icon families (`btn-icon`, `section-icon`, `theme-icon`)
  plus the logo and the GitHub-link icon. Always pairs
  `aria-hidden="true"` with `focusable="false"` to defuse IE /
  legacy Edge's "SVG is focusable by default → AT reads it
  even after aria-hidden" footgun, which is the SVG-icon
  industry-standard belt-and-suspenders pattern. Bulk edit
  applied via one-shot helper `scripts/_r230_add_svg_aria.py`
  (kept in-tree as audit trail). No visual change; no
  functional change. Guarded by
  `tests/test_decorative_svgs_aria_hidden_invariant_r230.py`
  (4 cases): every `<svg>` in `web_ui.html` must have
  `aria-hidden="true"` (allowlist `MEANINGFUL_SVG_CLASSES` is
  empty by design — if a future icon needs to be semantically
  meaningful, the contributor must explicitly add it to the
  allowlist AND give it `role="img"` + `aria-label`) + every
  `<svg>` must have `focusable="false"` + at least 2 SVGs keep
  the existing reference pattern (defensive lock against
  someone half-reverting R230) + total SVG count stays at or
  above 25 (sanity check against accidental template deletion).

- **R229 / Cycle 13: `#submit-btn` and `#insert-code-btn` now
  visually reflect their disabled state**. UX bug discovered
  while auditing `app.js` for theme-token compliance: when the
  page was waiting for a response (between user submit and
  server ACK) or busy with another task, the two action buttons
  were correctly set to `disabled` (so clicks were no-ops), but
  visually they looked identical to their enabled state. The
  only cue was `cursor: not-allowed`, which is invisible until
  the user moves the pointer over them. Users routinely
  double-clicked submit, then noticed nothing happened, then
  blamed the network. Root cause: `main.css` defines the brand
  gradient on `#submit-btn { background: linear-gradient(...)
  !important }` with no `:not(:disabled)` guard, and `app.js`'s
  `disableSubmitButton()` writes inline
  `style.backgroundColor = "#3a3a3c"` — but per the W3C CSS
  cascade spec, author `!important` always wins over inline
  non-`!important`, so the gray was silently overridden. R229
  sinks the disabled-state visuals to CSS (`#submit-btn:disabled`
  + `#insert-code-btn:disabled` rules for both dark and light
  themes, with `!important` matching the enabled rule, plus
  `opacity: 0.6` as a second cue) and strips the dead inline-
  color writes from JS, keeping only the `disabled` attribute
  toggle. `feedback-text` (textarea) is unaffected because its
  CSS does not use `!important` and the inline override actually
  worked. Bilingual themes verified. Guarded by
  `tests/test_submit_btn_disabled_visible_invariant_r229.py`
  (13 cases): both themes have `:disabled` selectors for both
  buttons + the rules use `!important` to win the cascade + JS
  no longer writes inline color/background/cursor for the two
  buttons + JS still flips the `.disabled` attribute (otherwise
  CSS `:disabled` doesn't fire and we'd lose both visual AND
  functional disability) + textarea inline styling is
  intentionally preserved (defensive lock against bulk cleanup).

- **R228 / Cycle 13: `Ctrl+/` notification body now lists every
  registered keyboard shortcut**. UX gap discovered while writing
  the R227 invariant-test guide: pressing `Ctrl+/` (`Cmd+/` on
  macOS) wrote the full 8-line help table to the browser console
  AND sent a web notification, but the notification body
  (`shortcuts.notifyBody`) only mentioned 3 of the 7 registered
  shortcuts (`Enter` / `T` / `Esc`). For users with notifications
  enabled but DevTools closed — the most common configuration —
  the notification was the *only* visible cue and silently lied
  by omission, suggesting those were the full shortcut set. R223
  partially mitigated this by adding a settings-panel hint
  pointing users at the console for the full reference, but the
  notification itself still misrepresented the surface. R228
  rewrites the body to cover every binding compactly
  (`{{mod}}+Enter submit · {{mod}}+, settings · {{mod}}+/ help ·
  T theme · Tab/Shift+Tab tasks · Esc close`) and appends an
  explicit `(full table in DevTools console)` qualifier so users
  who want the full table know where to look. Bilingual update
  (en.json + zh-CN.json) with pseudo locale regeneration.
  Guarded by
  `tests/test_shortcuts_notification_body_completeness_invariant_r228.py`
  (11 cases): both locale bodies non-empty + mention every
  registered binding (`Enter`, `,`, `/`, `T`, `Tab`, `Esc`) +
  mention `console` / `控制台` to set expectation + length ≤ 250
  chars so OS notification widgets don't truncate + keep the
  `{{mod}}` ICU placeholder (otherwise the `mod` parameter passed
  by `showHelp()` is wasted and the body reads as a hardcoded
  modifier key) + `keyboard-shortcuts.js` still calls
  `sendNotification` with `shortcuts.notifyBody` (otherwise the
  body change here would be invisible).

### Added

- **R227 / Cycle 13 · F-cycle12-4: contributor guide for the
  invariant-test pattern (bilingual)**. CR#25 §7 follow-up. The
  repo had accumulated 12+ invariant tests across cycles 9–13 but
  no central documentation explaining the pattern, when to write
  one, how to choose between sub-patterns, or what anti-patterns
  to avoid. New
  `docs/contributor-guide-invariant-tests{,.zh-CN}.md` ships:
  (§1) what an invariant test is with three concrete examples
  from the repo (R220 dashboard parity, R217 byte-twin parity,
  R215 smoke test scalar parity); (§2) a 5-question decision tree
  for "is this worth an invariant?"; (§3) five recurring patterns
  with copy-paste recipes: static-source string-presence check
  (R216), AST-based call-site enumeration (R198 SSE scanner),
  JSON/YAML structural (R220 Grafana), bilingual locale parity
  (R214), cross-tool byte parity (R217 state.js ↔ webview-state.js);
  (§4) five anti-patterns to avoid; (§5) end-to-end workflow for
  adding a new invariant; (§6) catalogue of all 12 invariants
  currently locked in the repo with R-cycle, file path, pattern
  tag, and what each locks; (§7) further reading cross-links to
  the silent-decay lessons-learned + code-reviews + release-recovery
  docs. Linked from both `docs/README{,.zh-CN}.md`. Guarded by
  `tests/test_invariant_test_guide_catalogue_r227.py` (10 cases /
  14 subtests): both guide files exist; §6 catalogue lists ≥ 8
  test files; every referenced test path actually exists on disk;
  every referenced test parses as valid Python (catches stale
  paths to deleted files); bilingual catalogue references the
  same set of files (catalogue rows are data, not prose); both
  guides cross-link each other so a reader landing on either
  always finds the other.

- **R226 / Cycle 13 · F-cycle12-2: pre-commit hook for static
  asset precompress freshness**. CR#25 §3 flagged that R223 added
  a new i18n key to `en.json` / `zh-CN.json` but did NOT regenerate
  the precompressed `.br` / `.gz` mirrors — `ci_gate.py` caught
  the drift on the next run, but the 1-commit lag meant a server
  hot-reloading the JSON would briefly serve the old precompressed
  string until the catch-up. R226 promotes the freshness check
  from `ci_gate.py` into `.pre-commit-config.yaml` as a new local
  hook (`check-static-precompress-fresh`) gated on changes under
  `src/ai_intervention_agent/static/(css|js|locales)/`. The hook
  invokes `scripts/precompress_static.py --check` (`pass_filenames:
  false`, `language: system` to inherit the project's uv env) and
  exits non-zero if any `.br` / `.gz` mirror's decompressed bytes
  don't match the source file. Failure mode points users at the
  fix command (`uv run python scripts/precompress_static.py` —
  no `--check`) and then `git add src/ai_intervention_agent/static/`
  for re-commit. Guarded by
  `tests/test_precompress_pre_commit_hook_invariant_r226.py`
  (10 cases / 3 subtests): config file exists + hook id present
  + entry invokes the right script + files pattern covers the
  three asset subdirs (css / js / locales) + `pass_filenames:
  false` + `language: system` + R226 / F-cycle12-2 provenance
  documented in a hook comment + the target script exists and
  advertises `--check` in its `--help` output. Saves the
  push → CI → catch-up cycle that R223 → R224 needed.

## [1.7.4] — 2026-05-14

> Cycle 12 release packing R221–R225. Pure additive cycle:
> 1 new module (`remote_environment.py` for SSH/WSL detection),
> 1 new Grafana dashboard (per-provider notification drill-down),
> 1 new Web UI hint, 2 expanded READMEs (Related-projects
> comparison table), and 5 new invariant test files (~54 cases /
> ~78 subtests). No breaking changes, no API surface changes
> beyond the additive detector module. The cycle closed CR#24
> follow-ups F-cycle11-1 / F-cycle11-3 / F-cycle11-4 and
> discovered + closed F-cycle12-* new follow-ups for R226+
> (see `docs/code-reviews/cr25.md`).

Cycle 12 highlights:

- **Competitive feature absorption end-to-end**: R222 introduced
  the bilingual Related-projects comparison table, R225 closed
  the SSH/WSL detection gap that `mcp-feedback-enhanced`
  advertises — same-cycle close on a gap surfaced by AIIA's
  own honest competitive positioning.
- **Observability drill-down**: R224 added the per-provider
  notification dashboard companion to R220's overview, with
  f-string-aware metric parity invariant covering both static
  and dynamically-emitted metric families.
- **VSCode webview console-log invariant lock**: R221 inverted
  the F-cycle11-1 finding (no debt found) into a forward-compat
  invariant to prevent future regression.
- **Web UI keyboard shortcuts discoverability**: R223 surfaced
  the existing `Ctrl+/` help binding via a one-line settings
  panel hint, with i18n parity locked in both languages.

### Added

- **R225 / Cycle 12: SSH / WSL remote-environment detection +
  actionable startup banner hints**. Closed a real UX gap
  highlighted by the README's `Related projects` comparison —
  `mcp-feedback-enhanced` advertises "intelligent SSH Remote /
  WSL detection" while AIIA's startup just printed
  `请在浏览器中打开: http://127.0.0.1:8080` on default bind, which
  is **unreachable** from a user's local browser when the
  process is running on an SSH-attached remote host. New module
  `src/ai_intervention_agent/remote_environment.py` provides
  `detect_remote_environment()` returning a `RemoteEnvironment`
  TypedDict (`is_ssh` + `is_wsl` + `ssh_source` + `wsl_source`).
  Detection probes `SSH_CONNECTION` then `SSH_CLIENT` (skipping
  empty / whitespace-only values), and `WSL_DISTRO_NAME` /
  `WSL_INTEROP` env vars plus `/proc/version` containing
  `microsoft` (case-insensitive) as a WSL1 fallback. Probes are
  fully wrapped — `FileNotFoundError` / `PermissionError` /
  `UnicodeDecodeError` from `/proc/version` silently degrade to
  "not detected" so the detector can never crash startup. The
  `web_ui.py` startup banner now calls the detector and appends
  one actionable hint when `host in ("127.0.0.1", "localhost")`:
  for SSH, it suggests the exact `ssh -L PORT:127.0.0.1:PORT
  user@remote_host` recipe plus the alternative
  `AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0`; for WSL it notes
  WSL2's automatic localhost forwarding and the WSL1 caveat.
  Behavior is purely additive — we never auto-rewrite `host` or
  auto-forward ports (would be a footgun for LAN-only and mDNS
  setups). Guarded by
  `tests/test_remote_environment_detector_r225.py` (19 cases):
  13 SSH / WSL detection matrix cases (clean baseline · both
  vars precedence · empty / whitespace strings rejected · WSL1
  `/proc/version` probe with mixed-case "Microsoft" + WSL2
  env-var path · silent degrade on missing / unreadable /
  malformed `/proc/version`); 2 schema invariants (returned keys
  match `RemoteEnvironment` TypedDict; SSH+WSL can coexist for
  the SSH-into-WSL exotic case); 1 real-process smoke ensures
  the detector survives whatever shape the CI host actually has;
  3 `web_ui.py` integration guards (import line present;
  detector called; hint mentions `ssh -L`).

- **R224 / Cycle 12 · F-cycle11-3: per-provider notification
  drill-down Grafana dashboard**. R220 shipped the overview
  dashboard with a single aggregate Notification panel
  (`aiia_notification_delivery_success_rate` + `_queue_size`); the
  overview is great for "is the notification subsystem healthy?"
  but useless for "*which* provider is broken right now?". R224
  fills that gap with
  `docs/observability/grafana-dashboard-notification-providers.json`
  (6 panels, schemaVersion 38, uid `aiia-notification-providers-r224`):
  attempts rate per provider · success rate (thresholded
  green/yellow/red at 0.95/0.90) · average latency · histogram-
  derived P95 send duration (R191) · consecutive failure streak
  (R145, step-line + red threshold at 5) · consecutive success
  streak. All panels break down by the `provider` label. Bundled
  docs in `docs/observability/README{,.zh-CN}.md` (companion table
  mirroring R220's overview table, with the same per-panel
  rationale columns). Guarded by
  `tests/test_grafana_dashboard_notif_providers_invariant_r224.py`
  (14 cases / 26 subtests): JSON parses + schemaVersion in
  `[38,40]` + uid + title + 6 unique-titled panels + datasource
  template variable binding + every panel target uses
  `${DS_PROMETHEUS}` + metric name parity with `system.py` (with
  smart fallback for f-string-assembled per-provider families
  like `aiia_notification_success_rate`) + every panel proves it
  breaks down by `provider` (either `sum by (provider)` aggregation
  or `{{provider}}` legend), preventing silent degradation into
  a duplicate of R220's overview + bilingual README cross-
  references mention the new dashboard filename and uid.

- **R223 / Cycle 12: discoverability hint for full keyboard
  shortcut help in Web UI settings panel**. The settings panel's
  "Common shortcuts" section showed only 5 input-workflow
  shortcuts (Submit / Insert code / Paste image / Upload image /
  Clear images) but **never told users about the 7 navigation
  shortcuts** registered in `keyboard-shortcuts.js`'s
  `showHelp()` (`Ctrl+,` settings · `Ctrl+/` help · `T` theme ·
  `Tab` next-task · `Shift+Tab` prev-task · `Escape` close-modal
  · `Mod+Enter` submit). Classic discoverability gap — power-user
  shortcuts existed in code but were invisible in the UI. R223
  adds a one-line hint beneath the shortcuts list pointing users
  at `Ctrl+/` (or `Cmd+/` on macOS) for the full reference,
  noting the output lands in the browser DevTools console.
  Bilingual i18n via new key `settings.shortcutsFullHelpHint`
  (en.json + zh-CN.json synced; pseudo locale regenerated).
  Guarded by `tests/test_settings_shortcuts_full_help_hint_
  invariant_r223.py` (7 cases): i18n key present + non-empty
  in both locales; `data-i18n` attribute references it in
  `web_ui.html`; hint message mentions actual shortcut binding
  (`Ctrl+/` in EN, `Ctrl+/` or `Cmd+/` in zh-CN); hint
  mentions output location (`console` in EN, `控制台` in zh-CN
  — without this users press the key and see no effect because
  output is hidden in DevTools). Closes a small UX gap with low
  surface change.

### Changed

- **R222 / Cycle 12 · F-cycle11-4: expand `README` "Related
  projects" sections from bare bullet lists into bilingual
  comparison tables with positioning paragraph and observability
  cross-link**. CR#24 flagged `F-cycle11-4` because the existing
  `## Related projects` / `## 同类产品` sections in `README.md` /
  `README.zh-CN.md` were 4-link bullet lists with no description,
  no comparative positioning, and no cross-link to the R220
  Grafana dashboard — useless to a new user evaluating whether
  AIIA fits their stack. R222 rewrites both sections into 4-row
  comparison tables (project · star count · focus), adds a "Where
  AIIA sits on the spectrum" positioning paragraph that
  recommends the right sibling project for different use cases
  (poliva for minimal drop-in, mcp-feedback-enhanced for desktop
  app, AIIA for full-stack ops integration), and cross-links the
  bilingual `docs/observability/README.md` / `README.zh-CN.md`
  (R220 Grafana dashboard). The 4 sibling projects covered:
  Minidoracat's `mcp-feedback-enhanced` (~3.8k stars, dual Web +
  Tauri desktop UI), imhuso's `cunzhi` (~1.4k stars, Chinese
  project focused on preventing premature task completion),
  poliva's `interactive-feedback-mcp` (~310 stars, direct
  ancestor fork from noopstudios — heritage preserved in
  Acknowledgements), Pursue-LLL's smaller-scale
  `interactive-feedback-mcp` fork (~30 stars). Guarded by
  `tests/test_readme_related_projects_invariant_r222.py` (8
  cases / 12 subtests): both READMEs declare the canonical
  section anchor; project URL set parity across en + zh-CN (set
  equality, ordering free); every English row carries a `~Xk` or
  `~XXX` star approximation marker (loose regex tolerates future
  format tweaks like `~5k+`); "Where AIIA sits" positioning
  paragraph keywords locked in both languages; observability
  dashboard README cross-link present in both. Star counts noted
  as "approximate, last reviewed 2026-05" so future readers know
  to verify upstream. Closes CR#24 F-cycle11-4.

### Added

- **R221 / Cycle 12 · F-cycle11-1: invariant test guarding
  `packages/vscode/` project-owned JS files at zero
  `console.log`**. CR#24 flagged `F-cycle11-1` as a VSCode
  webview console.* audit follow-up to Cycle 11's R216/R217/R218
  trifecta. R221 Discovery (2026-05-14) revealed that the VSCode
  webview surface (`packages/vscode/`) **already had zero
  `console.log` calls** in all 10 project-owned `.js` files
  (`i18n.js`, `tri-state-panel-bootstrap.js`,
  `tri-state-panel-loader.js`, `tri-state-panel.js`,
  `webview-state.js`, plus 5 zero-console-call helpers) — likely
  because `webview-state.js` is the byte-twin of R217-cleaned
  `state.js` and the `tri-state-panel-*` series was authored
  with proper `console.error` / `console.warn` / `console.debug`
  three-tier discipline from the start. **But no invariant test
  locked this good state.** R221 adds
  `tests/test_vscode_webview_console_noise_invariant_r221.py`
  (6 cases / 24 subtests) replicating R217's
  PROJECT_OWNED / VENDOR_ALLOW two-list pattern: each of the 10
  project-owned files asserted individually at zero
  `console.log`; 4 vendor allow-list files (`lottie.min.js`,
  `marked.min.js`, `mathjax/tex-mml-svg.js`, `prism.min.js`)
  must continue to exist; forward-compat test fails CI on any
  new `packages/vscode/*.js` file not yet classified as
  project-owned or vendor; `.vscode-test/` /
  `node_modules/` / `dist/` / `out/` / `test/` paths skipped
  (fixtures + build artifacts + unit tests should not be
  subject to webview discipline). Skip-logic self-test ensures
  no PROJECT_OWNED file accidentally falls through skip
  fragments, and that fixtures don't leak through. Cumulative
  console-noise invariant surface now spans **3 test files
  across 2 directories** (R216 notification-manager focused,
  R217 static-js wide net, R221 vscode webview), totaling **15
  cases / ~60 subtests** of forward-compat protection. Closes
  CR#24 F-cycle11-1.

## [1.7.3] — 2026-05-14

> Catch-up release packing Cycle 9 (R203-R206) + Cycle 10 (R207-R215) +
> Cycle 11 (R216-R220). Per CR#22 / CR#23 / CR#24 versioning analyses,
> all 17 commits are individually backward-compatible (R203 defensive
> cap, R204/R207 new Prometheus metrics, R205 opt-in env-var toggle,
> R206 docs, R208 pure refactor, R209 opt-in pre-push hook, R210/R211
> docs/CHANGELOG, R212/R213/R215 test-only invariants, R214 UI bug fix,
> R216-R218 console-noise cosmetic, R219 lint guard, R220 docs + tests
> + sample Grafana dashboard). Combined cycle-level highlights:
>
> * **Observability**: aiia_token_age_seconds (R204), aiia_sse_schema_
>   violation_total (R207), sample Grafana dashboard with 7 panels +
>   metric-name parity invariant against /metrics impl (R220).
> * **Security / safety**: SSE schema validation opt-in toggle (R205),
>   emit-by-type cardinality cap (R203), pre-push hook enforcement
>   for tag-push safety (R209).
> * **Quality / hygiene**: 117 console.log demotions across 11
>   project-owned JS files (R216-R218), CHANGELOG inline-code lint
>   guard (R219), denied-permission notification fallback toast
>   visibility fix (R214).
> * **Backlog discipline**: 5/9 Cycle 10 commits + 2/5 Cycle 11
>   commits explicitly closed prior-cycle CR follow-ups; the cycle
>   ended with a leaner backlog than it started.

### Added

- **R220 / Cycle 11 · F-cycle10-4: sample Grafana dashboard JSON
  for the `/metrics` endpoint, with metric-name parity invariant
  test against `system.py`**. CR#23 explicitly flagged that
  R207's `aiia_sse_schema_violation_total` and R204's
  `aiia_token_age_seconds` were never documented in a
  ready-to-import Grafana panel. R220 ships
  `docs/observability/grafana-dashboard.json` (Grafana 10.x
  `schemaVersion: 38`, `uid: aiia-overview-r220`) bundling 7
  high-signal panels: SSE Schema Violation Rate (R207), API
  Token Age Days (R204) with NIST SP 800-63B-aligned 60d/90d
  thresholds, SSE Emit Rate by event_type (R202), SSE
  emit→deliver p50/p95 latency (R134), SSE Backpressure +
  Oversize Drops rate (R51-B + R61), Recent ERROR Logs (R-186),
  Notification Subsystem success rate + queue size (R142). The
  dashboard declares a `DS_PROMETHEUS` datasource template
  variable so users can re-bind on import without editing JSON.
  Companion bilingual `docs/observability/README.md` +
  `README.zh-CN.md` documents import steps, per-panel metric
  rationale, and a sample alertmanager ruleset
  (schema-violation-rate / 90-day-token / recent-errors). The
  silent-decay shield is `tests/test_grafana_dashboard_invariant
  _r220.py` (14 cases / 24 subtests): JSON parses; schemaVersion
  in `[38, 39, 40]`; uid stable; title mentions project name;
  panel count locked at 7; every panel title non-empty + unique;
  every panel has ≥ 1 target; every target uses
  `${DS_PROMETHEUS}` (no hardcoded datasource UID); **core
  invariant** — every `aiia_*` metric name referenced by panel
  target exprs must substring-appear in `system.py`'s
  `_render_prometheus_metrics` source (catches future
  rename-without-dashboard-update drift); ≥ 7 distinct metric
  series covered (keeps dashboard "overview" substantive);
  bilingual README files exist + reference dashboard filename +
  uid. Closes CR#23 F-cycle10-4.

### Changed

- **R219 / Cycle 11 · F-cycle10-3: pre-commit lint guard for
  `CHANGELOG.md` inline-code style (prevents R211 regression)**.
  R211 (Cycle 10) was a one-shot normalization of 363
  reStructuredText-style double-backtick inline-code patterns in
  `CHANGELOG.md` to Markdown single-backtick form (preserving 18
  legitimate double-backtick spans where the wrapped content
  itself contains a literal backtick). But without an enforcing
  hook the cleanup silently decays the next time anyone
  copy-pastes RST-style fragments or runs a prettier-like
  formatter. CR#23 explicitly flagged this as `F-cycle10-3`.
  R219 closes the loop by adding a new pre-commit hook
  `check-changelog-inline-code-style` scoped to `CHANGELOG.md`
  only, powered by a tiny stdlib-only script
  `scripts/check_changelog_inline_code_style.py` that is
  fence-aware (skips content inside triple-backtick fenced code
  blocks), zero-false-positive (matches only double-backtick spans
  whose wrapped content contains no backtick — i.e. cases that
  can safely collapse to single-backtick form), and provides an
  actionable error message with line number, the matched
  substring, and a suggested single-backtick replacement; running
  with `--fix` performs in-place normalization. The hook fires
  only on `CHANGELOG.md` changes (`files: ^CHANGELOG\.md$`), so
  cold-start cost is negligible. Guarded by
  `tests/test_changelog_inline_code_lint_r219.py` (7 cases / 3
  subtests): script exists / has shebang / is executable; hook
  `id` registered; hook `entry` points at the script; hook
  `files` regex restricted to `CHANGELOG.md`; current
  `CHANGELOG.md` passes lint with **zero** violations (proves
  R211 cleanup is still intact); self-test of `find_violations()`
  correctness on synthetic fixtures (simple violation, fence
  skipping, triple-backtick safety, idempotency of `fix_text()`).
  Future PRs reintroducing RST-style double-backtick patterns
  will now fail pre-commit with a clear suggestion, eliminating
  the silent-decay vector entirely.

- **R218 / Cycle 11 · F-cycle10-1 (multi_task migration): migrate
  multi_task.js 46 `console.log` → `_debugLog` helper**. Completes the
  R216/R217 console-noise reduction trifecta by migrating the last
  remaining INFO-level surface — `multi_task.js`'s 46 `console.log`
  calls in deep link / polling / SSE / task add/remove/sync / retry /
  countdown / tab bar render paths. Different strategy from R216/R217
  (which used pure `console.log` → `console.debug` rename) because
  `multi_task.js` already has a dedicated `_debugLog()` helper at file
  line ~119: `function _debugLog() { if (!window.AIIA_DEBUG || typeof
  console === "undefined" || typeof console.debug !== "function")
  return; try { console.debug.apply(console, arguments); } catch (_)
  {} }`. The helper provides **stronger** noise suppression than
  raw `console.debug` because it requires opt-in via `window.AIIA_DEBUG
  = true` (default false → fully silent even in DevTools Verbose);
  developers debugging multi-task state changes flip the flag and get
  full diagnostic stream. R218 R217 invariant test (`test_static_js_
  console_log_demotion_invariant_r217.py`) was updated in the same
  commit: `MULTI_TASK_BUDGET` tightened from 50 → 0, added a new
  `test_multi_task_js_uses_debug_log_helper` invariant asserting
  `_debugLog(` count ≥ 45 (proves R218 migration really happened, not
  "deleted all log lines"). Also fixed a cross-cycle dependency:
  `tests/test_init_parallel_fetch_r22_3.py`'s Node harness now injects
  a `globalThis._debugLog = () => {}` no-op stub since R22.3's harness
  only loads `initMultiTaskSupport` body without the helper definition,
  and `init_body` now references `_debugLog` instead of `console.log`.
  Cumulative R216+R217+R218 = **117 console.log demotions** across 11
  project-owned JS files; the `static/js/` console-noise surface area
  is now defensively bounded with three invariant test files locking
  down the patterns (R216 for notification-manager, R217 for the rest,
  R218 piggybacks on R217's MULTI_TASK_DEBUGLOG_MIN). `console.warn`
  / `console.error` channels deliberately untouched (real signals
  must remain visible).

- **R217 / Cycle 11 · F-cycle10-1 (propagation): demote
  `console.log` → `console.debug` across remaining 9 project-owned
  static/js/ files**. Extends R216's notification-manager.js
  demotion pattern to the rest of the project-owned JS surface:
  `app.js` (17), `image-upload.js` (8), `settings-manager.js` (7),
  `keyboard-shortcuts.js` (3), `theme.js` (3), `mathjax-loader.js`
  (3), `validation-utils.js` (1), `mathjax-config.js` (1), and
  `state.js` (1, JSDoc example). 44 demotions total; cumulative
  R216+R217 = 71 demotions across 10 files. Rationale identical to
  R216 — Chrome / Firefox / Safari / Edge DevTools default-hide
  Verbose / Debug filter, INFO-level browser logs no longer drown
  out real `console.warn` / `console.error` signals; pure method
  rename, zero helper, zero runtime cost. `multi_task.js` (46
  remaining `console.log`) and vendor files (`tex-mml-chtml.js` /
  `prism.js` / `marked.js` / `lottie.min.js`) deliberately
  untouched: the former has an existing `_debugLog` helper that
  should be reused via case-by-case migration (deferred to a future
  cycle); the latter is third-party code. `dom-security.js` keeps
  2 `console.log` references in JSDoc examples (API documentation).
  Also synced `packages/vscode/webview-state.js` to maintain
  byte-parity with `static/js/state.js` (guarded by
  `tests/test_state_machine.py::TestJsSync::test_two_js_files_are_byte_identical`).
  6 invariant tests + 13 subtests in
  `tests/test_static_js_console_log_demotion_invariant_r217.py`
  lock down: (a) all 9 R217-demoted files have zero `console.log(`
  calls (per-file subtest reporting plus a global aggregate
  assertion), (b) vendor allow-list is structurally distinct from
  R217 list (no typo crossover) and contains the 4 known third-
  party libs, (c) `multi_task.js` stays under a 50 console.log
  budget (R218-pending) and `dom-security.js` stays under a 3
  JSDoc-example budget, (d) forward-compat orphan scan — any
  newly-added `static/js/*.js` file (excluding `.min.js` build
  artifacts) that is neither in R217 list nor vendor nor special-
  budget will fail this test with a clear actionable error message
  if it contains any `console.log(`, forcing future contributors
  to either demote, vendor-classify, or add explicit budget. Sets
  up R218 to be a focused `multi_task.js console.log → _debugLog`
  migration without scope-creep risk.

- **R216 / Cycle 11 · F-cycle10-1: demote notification-manager.js
  `console.log` to `console.debug` for production console noise
  reduction**. `src/ai_intervention_agent/static/js/notification-manager.js`
  shipped with 27 `console.log` calls covering init / config-change /
  every sound playback / every fallback notification — frequent-
  notification sessions would flood the browser Console with INFO-
  level lines, drowning out the 29 legitimate `console.warn` /
  `console.error` signals (e.g. permission denied, SW registration
  failure) that ops / users actually need to see. R216 mechanically
  renames all 27 `console.log(` → `console.debug(` (Chrome / Firefox /
  Safari / Edge DevTools default-hide Verbose/Debug level; non-
  developers see clean Console; developers can enable Verbose filter
  to inspect full history). Zero helper / zero runtime cost, pure
  method rename — `console.debug.apply(console, [...args])` is
  byte-for-byte equivalent to `console.log.apply(...)` except for
  the log level. `console.warn` / `console.error` deliberately
  preserved (these are the actually-actionable signals; demoting
  them would let Sentry/Datadog Browser RUM lose error coverage).
  7 invariant tests in
  `tests/test_notification_manager_console_noise_invariant_r216.py`
  lock down: zero `console.log(` calls remaining (positive contract +
  comment-vs-call distinction), `console.debug(` count ≥ 20 (proves
  the demotion happened, not "log statements all deleted"),
  `console.warn(` ≥ 10 + `console.error(` ≥ 3 preserved (negative
  regression guard against accidental demote of these channels),
  and file-header banner contains `R216` + `console` + `debug` /
  `demote` keywords so future contributors grep'ing the convention
  source can find it. Sibling pattern to `multi_task.js`'s existing
  `_debugLog` helper (guarded by
  `tests/test_multi_task_sse_console_noise.py`); R216 takes the
  simpler "rename method" approach instead of introducing another
  wrapper since the demotion is monolithic and one-shot.

### Fixed

- **R215 / Cycle 10 · F-205-4: smoke_test_r50 forward-compat field
  parity with `SSEBusStatsSnapshot`**. `scripts/smoke_test_r50.py`'s
  `_check_stats_endpoint()` hardcoded a `needed` tuple of SSE-stats
  fields when written for the R47/R50 cycle, but never synced when
  R51-B added `heartbeat_total`, R61 added `oversize_drops`, R205 added
  `schema_validate_mode` + `schema_violation_total`. Silent decay risk
  (CR#10 lessons-learned root cause 3, same pattern as R213): an
  operator runs `python scripts/smoke_test_r50.py` to verify
  "the R205 schema-validation feature is alive in production",
  smoke goes all green via the stale `needed` list while
  `sse_stats` route may have silently dropped those fields after a
  refactor — R205 invisible in production but smoke reports OK, and
  alertmanager loses its `aiia_sse_schema_violation_total` data
  source. Fix: extend `needed` to include all 4 historically-added
  scalar fields (`heartbeat_total`, `oversize_drops`,
  `schema_validate_mode`, `schema_violation_total`). 5 invariant tests
  + 2 subtests in
  `tests/test_smoke_test_r50_field_drift_invariant_r215.py` AST-parse
  both the smoke `needed` tuple and the `SSEBusStatsSnapshot` TypedDict
  to lock down: R205 keys hard-coded in `needed` (negative regression
  guard for both keys), TypedDict scalar parity (any future scalar
  added to `SSEBusStatsSnapshot` must be added to smoke `needed` or
  this test fails — found 2 pre-existing drifts the first time it
  ran), R47 head-of-line keys (`emit_total` / `latest_event_id`)
  retained, and `needed` structural integrity (literal `tuple[str,
  ...]`, no dynamic construction). Bonus: zero new code in the smoke
  script's runtime logic — the change is purely "extend the
  hardcoded whitelist", so existing R50 debounce / streaming
  assertions remain byte-identical.

- **R214 / Cycle 10 · F-notif-fallback-1: friendly visible fallback toast
  when system notification permission denied / unavailable**. Pre-R214,
  `notification-manager.js`'s `showFallbackNotification()` called
  `showStatus(..., 'info')`, but `app.js`'s `showStatus()` on a content
  page (i.e. while the user is looking at a feedback request) silently
  dropped every non-`'success'` / non-`'error'` type — the `'info'`
  fallback toast was rendered nowhere; the user only got a hidden
  `console.log` + title flash (often invisible while the tab is
  focused). Net effect: user looks at an open feedback panel, browser
  blocks notifications, **zero visual signal arrives** that the page
  even tried to notify. Fix: (a) extend `app.js showStatus()` to also
  toast `'warning'` type on content pages with a 5 s auto-dismiss
  (sweet spot between success's 3 s and error's 10 s; `'info'` stays
  silent to avoid noise from frequent internal state updates); (b)
  switch `showFallbackNotification()` to `type='warning'` so the toast
  is actually rendered; (c) append a reason-aware i18n hint
  (`permission_denied` → "enable system notifications in your browser
  settings", `unsupported` → "this browser does not support system
  notifications", `insecure_context` → "notifications require HTTPS or
  localhost", `permission_default` → "click the bell icon to grant
  permission", `permission_disabled` → "re-enable via settings panel")
  so the toast is actionable rather than just "title: message". Reason
  → hint mapping uses callback values (`() => t('status.notifFallback*')`)
  so `scripts/check_i18n_orphan_keys.py` literal-call scanner can see
  each i18n key reference; underlying low-level reasons
  (`system_notification_failed` / `show_notification_exception`) deliber-
  ately do not append a hint — user cannot fix them immediately, no
  point spamming. 10 invariant tests in
  `tests/test_notification_fallback_toast_invariant_r214.py` lock down:
  showStatus's `'success' || 'warning'` toast branch presence,
  `warning ? 5000` autodismiss branch, `showStatus(..., 'warning')`
  call in `showFallbackNotification()` (+ negative regression test that
  `showStatus(..., 'info')` no longer appears in its body), all 5
  `reason` keys + 5 `status.notifFallback*` i18n keys referenced,
  bilingual lockstep (en + zh-CN), actionable-words presence
  (`enable` / `browser` / `settings` / `fallback` / `hint` / `permission`
  for en; `通知` / `降级` / `浏览器` / `设置` / `提示` / `权限` for zh),
  and en/zh length ratio bounds (0.3 ≤ zh/en ≤ 2.0) to catch
  truncation / mis-translation.

### Added

- **R213 / Cycle 10 · F-21.4-1: production static-assets precompress
  completeness invariant test**. R20.14-D (gzip) + R21.4 (brotli)
  precompress pipeline produces `.gz` / `.br` siblings for
  `static/{css,js,locales}/*` resources, but `precompress_static.py
  --check` only runs at build-time. No pytest-level signal guards
  "production static assets actually HAVE complete `.br` + `.gz`
  siblings" — silent decay risk (CR#10 lessons-learned root cause 3
  same pattern): if brotli dep is accidentally removed, or
  `DEFAULT_TARGET_DIRS` paths drift after a refactor, or someone bumps
  a CSS bundle past `MIN_SIZE_BYTES` without re-running precompress,
  pytest stays green while production silently loses 17-23% bandwidth
  win.

  **Implementation (1 test file, zero source code changes)**:
  - `tests/test_static_precompress_production_invariant_r213.py` (NEW,
    9 cases / 4 invariant class + 10 subtests):
    1. **TestProductionGzipCompleteness** (3): every source ≥
       `MIN_SIZE_BYTES` and not in `SKIP_EXTENSIONS` HAS `.gz`
       sibling + `.gz` strictly smaller than source + `.gz`
       decompresses byte-equal to source (5-file sample, sanity
       check, not exhaustive).
    2. **TestProductionBrotliCompleteness** (3, skipped when brotli
       unavailable): same as gzip but `.br` + `.br` size ≤ `.gz` ×
       1.05 (5% tolerance for rare entropy-saturated edge cases
       where gzip narrowly wins). If `.br > .gz * 1.05`, fail —
       suggests precompress `skipped_no_gain` reverse check is
       bypassed.
    3. **TestProductionTargetDirsRegistered** (2): `DEFAULT_TARGET_
       DIRS` must contain `css` / `js` / `locales` subdirs + every
       dir exists on disk. Guards against R76-style refactor
       (moved `static/` into `src/ai_intervention_agent/` package)
       where `DEFAULT_TARGET_DIRS` would drift silently.
    4. **TestPrecompressCheckExitsCleanInProduction** (1): runs
       `subprocess.run(precompress_static.py --check)` and
       asserts exit 0. Redundant with `ci_gate.py` invocation but
       gives local `uv run pytest` immediate feedback on stale
       state without waiting for CI Gate run.

  **Design choice — runtime invariant test vs build-script trust**:
  - Runtime test: pytest itself enforces; works regardless of CI
    pipeline order; closes gap if some future contributor runs
    `pytest` standalone without ci_gate.
  - Build-script trust: assume `precompress --check` always runs
    before merge; depends on CI orchestration discipline. Higher
    drift risk over years.

  → Runtime test wins (same philosophy as R212 contract bridge).

  **Tolerance 5% for br ≤ gz × 1.05**: rare cases where brotli
  marginally loses to gzip exist (highly repetitive ASCII patterns
  with low complexity), and `compress_file_br` already has
  `skipped_no_gain` reverse check (br ≥ raw → skip). 5% buffer
  allows tested-and-valid edge cases without false-positive fails.

  **Verified**: 9 cases / 10 subtests PASS; full pytest baseline
  5477 → 5486 (net +9 cases, +10 subtests); ty/ruff/format clean.

- **R212 / Cycle 10 · F-205-3 (R210 follow-up): SSE schema validation
  contract bridge invariants for AIIA_SSE_SCHEMA_VALIDATE**. R210
  closed F-205-1 (docs sync), but R210 tests only verify docs string
  presence; R205 tests cover 8 invariant classes / 14 cases of runtime
  behavior but **don't lock the bridge** between R210 docs phrasing
  and R205 implementation contracts. R212 adds the cross-file invariant
  bridge that catches docs ↔ code drift in either direction.

  **Implementation (1 test file, zero source code changes)**:
  - `tests/test_sse_schema_validate_contract_r212.py` (NEW, 10 cases /
    4 invariant class) covering 4 gaps in R205's test surface:
    1. **TestStickyReadInvariant** (3): Twelve-Factor sticky contract
       — bus created with one mode, env var post-init change MUST NOT
       affect `bus._schema_validate_mode` / log level / counter
       behavior. R205 tests `__init__`-time env var read but never
       tested post-init immutability; a future refactor moving env
       var read into `emit()` (tempted by "hot reload" feature)
       would silently break R210's docs promise.
    2. **TestStatsEndpointJsonRoundTrip** (3): HTTP boundary
       `GET /api/system/sse-stats` MUST expose
       `schema_validate_mode` + `schema_violation_total` JSON fields.
       R205 covers `bus.stats_snapshot()` Python dict only; R207
       covers Prometheus `/api/system/metrics` only — this is the
       JSON endpoint gap. Endpoint must reflect post-emit counter
       updates (not stale cache).
    3. **TestR210DocsKeywordInR205Code** (2): R210 docs use
       distinctive design keywords (`Twelve-Factor` / `fire-and-
       forget`) — these must also appear in R205 source code
       comments in `task.py`, so fresh contributors / reviewers
       grepping the codebase can locate the design rationale.
       Bidirectional drift guard.
    4. **TestCounterTypeStability** (2): `_schema_violation_total`
       MUST always be `int` (excluding `bool` subclass) — guards
       against future perf refactor swapping in `collections.
       Counter` / `itertools.count` iterator / `float` (EWMA-decayed)
       which would silently break R207's `isinstance(violation_raw,
       int)` Prometheus type gate and R210's "counter +1" docs
       semantics.

  **Design choice — invariant bridge tests vs adding sticky comment
  in source**: R212 could also have ADDED "Twelve-Factor sticky"
  comment in source to make `test_twelve_factor_keyword_in_r205_
  source` pass — but R205 source already HAS the keyword
  ("Twelve-Factor 风格 sticky 读取"). R212's gap is not "code missing
  keyword", but "no test ENSURES the keyword stays". This is the
  same lesson as CR#10 lessons-learned-css-and-options.md root cause
  3: feature works, but invariant unprotected → silent decay over
  cycles. R212 promotes "implicit contract" to "explicit
  test-enforced contract".

  **Test helpers shared with R205**: `_make_bus_with_env()` /
  `_clear_log_dedup_cache()` duplicated from R205 test file (each
  test file owns its helper, no cross-file dependency — easier to
  refactor R205 helpers without breaking R212).

  **Verified**: R212 10 cases PASS; R205 14 cases regression PASS;
  R210 6 cases regression PASS; `uv run ty check . → All checks
  passed!`; `uv run ruff check . && ruff format --check . →
  All passed!`; full pytest baseline 5467 → 5477 (net +10 from R212).

- **R210 / Cycle 10 · F-205-1 (CR#22 §4 Important): `AIIA_SSE_SCHEMA_
  VALIDATE` env-var docs sync into `docs/configuration.{md,zh-CN.md}`**.
  R205 (Cycle 9) 引入 `AIIA_SSE_SCHEMA_VALIDATE=off|warn|strict` 运
  行时 SSE schema 验证开关，但 `docs/configuration.md` /
  `configuration.zh-CN.md` 没有同步——fresh contributor / 运维
  `grep AIIA_` 找环境变量时根本找不到该 env var 的说明。CR#22 §4
  把这个 docs-sync miss 列为 Important 级别 follow-up (F-205-1)，
  R210 收尾该 follow-up。

  **实现 (2 文件 + 1 测试)**:

  - `docs/configuration.md` 在 §"Auto-migration" 之前新增子节
    "Ops / debug env vars"，完整说明 `AIIA_SSE_SCHEMA_VALIDATE`：
    `off` (默认，零开销) / `warn` (违规 WARNING + counter +1) /
    `strict` (违规 ERROR + counter +1，**不抛异常**——`_SSEBus.
    emit()` fire-and-forget 契约不变); 无效值 fall back `off` +
    启动 `WARNING` 一次; **Twelve-Factor sticky 读取** (启动后改
    env var 必须重启生效); 计数器双通道暴露 (`/api/system/stats`
    JSON `schema_violation_total` + `/api/system/metrics`
    Prometheus `aiia_sse_schema_violation_total` counter，与 R207
    omit-when-off 契约一致); 单 emit 多字段错只算 1 次 violation
    (噪声抑制)。
  - `docs/configuration.zh-CN.md` 同步双语 lockstep (沿用 R178 /
    R185 / R206 / R209 i18n 契约)。
  - `tests/test_configuration_env_var_docs_r210.py` (NEW, 6 cases /
    2 invariant class) 守结构性契约：双语都含 env var 名 + 3 mode
    名 + R205 / R207 / F-204-1 / Twelve-Factor / omit-when-off /
    fire-and-forget 关键 design keyword (让 ops grep 能定位完整背景)。

  **设计取舍 · 放 "Ops / debug env vars" 子节 vs 塞 Settings 表**:

  - "Ops / debug env vars" 子节: env var 本质是**运行时 toggle**, 不
    是 user-facing config (默认 off, 普通用户不需要碰), 与现有
    §"Path discovery env vars" 风格一致；
  - 塞 Settings 表 (`[ui]` / `[security]` 那种): 会让普通配置者
    误以为是常规 setting, 但实际它没有 `config.toml` 字段对应。

  → "Ops / debug env vars" 子节胜出（独立段落 + 明确 "ops only"
  signal）。

  **沿用 R185 + R206 + R209 静态字符串匹配 + 双语 lockstep 模式**
  — 不深入语义校验文档措辞, 留出 wording polish 空间, 只锁结构性契
  约 (env var 名 + 3 mode 名 + 关键 design keyword)。

  **验证**: R210 6 cases PASS; `uv run ty check . → All checks
  passed!`; `uv run ruff check . && ruff format --check . →
  All passed!`; 完整 `pytest` baseline 5461 → 5467 (净增 +6
  from R210); `scripts/generate_docs.py --check` 两份语言 26/26 一
  致 (docs/configuration.{md,zh-CN.md} 是 prose docs, 不在
  `MODULES_TO_DOCUMENT`)。

- **R209 / Cycle 10 · F-release-2 (CR#22 §4 Important): pre-commit
  pre-push hook for `check_tag_push_safety.py` enforcement**. R206
  (cycle 9) 把 v1.7.2 docs-sync miss 经验固化成 13 步本地预飞行清
  单，但所有 13 步都靠**人**记得跑——一旦忘了步骤 6
  (`scripts/check_tag_push_safety.py`)，4+ 个未推送 `v*.*.*`
  tag 累积时 `git push --follow-tags` 会静默触发 GitHub webhook
  屏蔽 (R19.1，v1.5.24 真实复现)，release.yml 一个 job 都不跑。

  R209 把 `check_tag_push_safety.py` 装到 pre-commit framework 的
  **pre-push** stage——push 触发时**自动跑**，把 R206 §1 step 6
  从"人记忆"提升到"代码强制"，与现有 R66/R174/CR#16-F-4 三个
  pre-commit hook 一致风格。

  **实现 (3 文件 + 1 测试)**:

  - `.pre-commit-config.yaml` 新增 `check-tag-push-safety`
    hook entry，`stages: [pre-push]` + `always_run: true`，调
    用 `uv run python scripts/check_tag_push_safety.py`（无新
    script，复用 R185 已有）；
  - `Makefile` 新增 `install-hooks` PHONY target，调
    `pre-commit install --hook-type pre-commit --hook-type pre-push`
    一次性安装两个 hook chain；help 表列出让 fresh contributor 能
    发现；
  - `docs/release-recovery.{md,zh-CN.md}` 在 R206 Pre-tag-push
    checklist 段顶部加 R209 automation 注释（双语 lockstep, 沿用
    R178 / R185 / R206 i18n 契约），明确：
    1. hook 是 R206 manual checklist 的**补充**, 不是替代；
    2. 只拦截最危险的单一失败模式（≥ 4 unpushed tag），不跑全 13 步；
    3. escape hatch: `git push --no-verify` (与 pre-commit 同款)；
    4. 失败时按 script 输出按 tag 名升序逐个 push 修复。

  **设计取舍 · pre-commit framework vs native .githooks/pre-push**:

  - pre-commit framework: 用户已在用，零新依赖，`pre-commit
    install --hook-type pre-push` 一行接入；
  - native .githooks: 需要 `git config core.hooksPath .githooks`
    引入新 framework 路径，配置点变多。

  → pre-commit framework 胜出。

  **设计取舍 · 只 hook check_tag_push_safety vs full R206 13-step**:

  R206 13 步里 ruff / ty / pytest 都已在 commit 阶段 (pre-commit hook)
  跑过, push 时再跑浪费; docs-parity / pytest 太慢 (~3 min full
  pytest, 不接受在 push 时 block)。check_tag_push_safety 是 push
  专属 + 50-500 ms (1 次 git ls-remote), 是 perfect-fit pre-push hook。
  其余 step 留给 manual checklist + 未来 F-release-3 (tag-CHANGELOG
  enforcement) 可考虑加 lightweight 强制。

  **测试 (8 cases / 3 invariant class)** ——
  `tests/test_pre_push_hook_install_r209.py`:

  1. **TestPreCommitConfigHasPrePushHook** (3): hook id 声明 + stages
     含 pre-push + entry 指向 check_tag_push_safety.py；
  2. **TestMakefileInstallHooksTarget** (3): .PHONY 列 install-hooks
     + body 含 `--hook-type pre-push` + help 列出；
  3. **TestDocsMentionAutomation** (2): 双语 release-recovery 都含
     R209 / install-hooks / pre-push 关键词 (沿用 R185 双语 lockstep)。

  **沿用 R185 `TestMakefileReleaseCheckCveTarget` + R206
  `TestReleaseRecoveryPreTagChecklistBilingual` 静态字符串匹配模
  式** — 不深入语义校验文档，留出 wording polish 空间，只锁结构。

  **验证**: R209 8 cases PASS；`uv run ty check . → All checks
  passed!`；`uv run ruff check . && ruff format --check . →
  All passed!`；完整 `pytest` **5461 passed / 2 skipped / 646
  subtests passed in 167s** (R208 baseline 5453 → 5461, 净增 +8
  from R209)；`scripts/generate_docs.py --check` 两份语言 26/26
  一致 (.pre-commit-config.yaml / Makefile / release-recovery.md 都
  不在 `MODULES_TO_DOCUMENT`)。

### Changed

- **R208 / Cycle 10 · F-204-2 (CR#22 §4 Important): unify token age
  computation into shared `_compute_age_seconds_from_iso` helper**.
  R199 `GET /api/system/api-token-info` endpoint inline 与 R204
  `_safe_token_age_seconds()` 之前各自维护一份**完全相同**的 age
  计算（`rotated_at.replace("Z", "+00:00")` + `fromisoformat` +
  clock-skew negative check），任何 bug fix 都必须同步两处, 仅靠
  R204 `TestEndpointMetricParity` invariant 在运行时验证一致。

  R208 把算法抽到 module-level `_compute_age_seconds_from_iso(rotated
  _at: object) -> int | None` 共享 helper, 两处调用同一份实现 →
  **source-level drift 风险消失**, R204 parity invariant 退化为
  defensive belt-and-suspenders 守护。

  **设计契约严格保持与原两份实现一致** (validated by R208 +
  preserved R199 + R204 测试套):

  - 输入非 `str` / 空串 → `None`;
  - `rotated_at` 解析失败 (ValueError / TypeError) → `None`;
  - `age < 0` (系统时钟跳变 / 未来时间戳) → `None`;
  - 正常情况 → `int` (秒, ≥ 0)。

  **重构细节**:

  - 新 helper signature 用 `object` (而非 `str`) — caller 不必预
    先 isinstance check, helper 内部统一处理 (R199 endpoint + R204
    helper 调用点都简化了)。
  - helper 是 **pure function**: 无 log、无 I/O。R199 endpoint 原有
    的 `logger.debug("解析 rotated_at 失败")` **删除** — debug log
    不是公共契约的一部分 (R199 测试不依赖); helper silent 与
    `_safe_uptime_seconds` 等其他 `_safe_*` helper 风格一致。
  - R204 `_safe_token_age_seconds` 重构后**只**负责 config 读取 +
    token validity 检查 (长度 ≥ 16), age 计算委托 helper。
  - R199 endpoint inline 重构后 age 计算一行调用, 删 18 行 inline
    fromisoformat 逻辑。

  **测试 (15 cases / 4 invariant class)** ——
  `tests/test_compute_age_seconds_from_iso_r208.py`:

  1. **TestNonStringInput** (3): None / int / dict → None;
  2. **TestEmptyString** (1): "" → None;
  3. **TestMalformedTimestamp** (3): 随机串 / 月份 13 / 字母混入 →
     None (ValueError 被 catch);
  4. **TestValidTimestamp** (6): UTC Z 后缀 / +00:00 offset / 45 天前
     (NIST 30-90 中点) / 刚刚 / int return type 契约 / 微秒精度时间
     戳 → 正确 int;
  5. **TestFutureTimestamp** (2): 未来 1 秒 / 1 天 → None (clock skew
     防御)。

  **regression 验证**: R199 (15 cases) + R200 (13 cases) + R204 (10
  cases) + R195 (14 cases) **共 52 cases PASS** 全部不动 — endpoint
  / metric 行为对外完全一致, F-204-2 是 **pure refactor** 不引入新
  behavior。

  **验证**: R208 15 cases PASS; R199/R200/R204/R195 完整 52 cases
  regression PASS; `uv run ty check . → All checks passed!`;
  `uv run ruff check . && ruff format --check . → All passed!`;
  完整 `pytest` **5453 passed / 2 skipped / 646 subtests passed
  in 160s** (R207 baseline 5438 → 5453, 净增 +15 from R208);
  `scripts/generate_docs.py --check` 两份语言 26/26 一致。

### Added

- **R207 / Cycle 10 · F-205-2 (CR#22 §4 Important): `aiia_sse_schema_
  violation_total` Prometheus counter**. R205 (cycle 9) 把 SSE schema
  validation 装在 `AIIA_SSE_SCHEMA_VALIDATE=off|warn|strict` 环境变量
  后, `_schema_violation_total` 计数器只通过 `stats_snapshot()` JSON
  暴露——alertmanager 想 watch 必须 scrape JSON, 绕开 Prometheus scrape
  的标准方式。R207 把这份数据 mirror 到 Prometheus exposition
  `aiia_sse_schema_violation_total` counter, 让 alertmanager 用标准
  PromQL 即可写规则（如 `rate(aiia_sse_schema_violation_total[5m])
  > 0` 检测新违规出现）。

  **设计契约 · omit-when-off 而非 always-emit-with-zero**：

  R207 选 **omit when mode == "off"** (与 R204 `aiia_token_age_
  seconds` 同款 omit-vs-NaN 哲学)：

  - mode == "off"：metric **不出现** → alertmanager 用 `absent(
    aiia_sse_schema_violation_total)` 即可分清「validation off」
    （不在监控）vs「validation on with 0 violations」（监控中但无违
    规），两类 ops 状态走不同 alert 路由；
  - mode in {warn, strict}：metric 出现 (value ≥ 0)，可用
    `rate(...)` / `aiia_sse_schema_violation_total > N` 等阈值告
    警。

  反方案「always-emit-with-zero」：metric 永远存在 = 0 也输出，看似简单
  但让 ops 无法分辨「运维忘了开 validation」与「validation 开着无违
  规」，两者都是 0，alertmanager 写不出区分 rule —— R207 拒绝该方案。

  **实现** (`web_ui_routes/system.py::_render_prometheus_metrics` SSE
  bus section 新增 ~30 行)：

  - 在 SSE 块 latency snapshot 之后新增 R207 section；
  - 读 `snap.get("schema_validate_mode")` + `snap.get(
    "schema_violation_total")`，验证类型 + mode in {warn, strict}
    才 emit；off mode silently 跳过；
  - HELP 字符串含 R207 / F-205-2 / AIIA_SSE_SCHEMA_VALIDATE / absent
    / "Multi-field" 关键字让运维 grep 可定位 + 理解 omit-when-off 契约；
  - metric_type = counter (与 R205 `_schema_violation_total` 单调累
    加 semantics 一致)；
  - 更新 `/api/system/metrics` 端点 description docstring 提及 R207 +
    omit-when-off 契约 + `absent(...)` alertmanager 用法 (与 R204
    docstring 同款形式)。

  **测试 (10 cases / 5 invariant class + 6 subtests)** ——
  `tests/test_sse_schema_violation_metric_r207.py`：

  1. **TestOffModeOmitContract** (2): mode == "off" + 0 / 50 violation
     全部 omit metric；
  2. **TestWarnModeEmitContract** (3): mode == "warn" + 0 violation
     → metric value 0 emit / N violation → value N / metric 行格式
     合规 (HELP/TYPE 各 1 次 + counter type)；
  3. **TestStrictModeEmitContract** (2): mode == "strict" + N
     violation → value N (与 warn mode 同款 emit, R205 strict 与
     warn 唯一行为差异是 log level, metric 一致)；
  4. **TestEndpointMetricParity** (1 + 6 subtests · **核心契约**):
     2 mode × 3 violation count {0, 1, 5} 笛卡尔积, snapshot
     `schema_violation_total` == metric value 必须严格相等
     (R207 渲染层不引入新计数逻辑, 严格 mirror)；
  5. **TestPrometheusOutputFormat** (2): HELP 含必备关键词 + TYPE
     声明 counter (而非 gauge——_schema_violation_total 是 monotonic
     累加, semantically counter)。

  **测试 helper · `_render_with_bus`**: 用 `unittest.mock.patch.object`
  把 `task_module._sse_bus` 临时替换成 test bus 实例，render 后还原。
  这是测试 `_render_prometheus_metrics` 与 specific bus state 的标
  准 pattern (避免污染 module-level singleton)。

  **验证**: R207 10 cases + 6 subtests PASS；R202/R204/R205 完整测
  试套 57 cases + 22 subtests PASS（向后兼容验证）；`uv run ty
  check . → All checks passed!`；`uv run ruff check . && ruff
  format --check . → All passed!`；完整 `pytest` **5438 passed
  / 2 skipped / 646 subtests passed in 167s** (R205 baseline 5428
  → 5438, 净增 +10 from R207)；`scripts/generate_docs.py --check`
  两份语言全过（system.py 改的是 endpoint description docstring,
  会被 docs/api 抓到, 本地预 regen 验证 parity）。

- **R205 / Cycle 9 · F-204-1 (CR#21 §4.3): SSE schema runtime
  validation toggle**. R198 把 `EVENT_SCHEMAS` + `validate_payload`
  API 暴露好了, 但**故意不在 production emit 路径调用**（hot path 性能
  优先, 见 `sse_event_schemas.py` 模块 docstring "设计取舍"）。R205
  加 env-var `AIIA_SSE_SCHEMA_VALIDATE=off|warn|strict` toggle, 让
  运维 / 调试期可以选择性开启 emit-site 验证, 不污染 default zero-
  overhead 行为：

  - `off` (default): emit() 不调 `validate_payload`, 0 开销, 与
    R198 现状完全一致;
  - `warn`: 调 `validate_payload`, violations → `logger.warning`
    + `_schema_violation_total` 计数器累加, 但 emit 仍 fanout 不阻
    塞 (一条 emit 多字段错只算 1 次, 避免噪声膨胀);
  - `strict`: 同 warn, 但 violations 走 `logger.error` (alertmanager
    路由不同 severity), 仍 fanout, **不**抛异常。

  **设计契约 · strict 为何不 raise**: emit() 是 fire-and-forget, 大部
  分 emit-site 没 try/except 包裹 (例如 `_on_task_status_change` /
  `web_ui_config_sync.py` 等)。raise 会让 production 挂掉, 违反
  R198 "bus 不验证 event_type" 的原 design rationale; strict 与 warn
  的唯一差异是 log level, 方便 alertmanager 配 "ERROR severity →
  page on-call" 让 strict 真有 op effect。

  **实现** (`web_ui_routes/task.py`, ~80 行):

  - 模块顶端：`_SSE_SCHEMA_VALIDATE_ENV_VAR` / `_SSE_SCHEMA_VALIDATE_
    DEFAULT_MODE` / `_SSE_SCHEMA_VALIDATE_VALID_MODES` 三个常量 +
    `_read_sse_schema_validate_mode()` helper (env-var sticky 读取);
  - `_SSEBus.__init__`: 一次性读 env var (Twelve-Factor 风格 sticky)
    → invalid 值 → fall back `off` + startup WARN 一次 (避免运维
    以为开了实际没生效); mode != off → startup INFO 一次告知;
  - `_SSEBus.emit` 最早期 (serialize / oversize 替换之前) 加 mode-
    check + validate 调用; off 是单 attribute compare 零开销;
  - `SSEBusStatsSnapshot` TypedDict 新增 `schema_validate_mode` +
    `schema_violation_total` 两个 key;
  - `stats_snapshot` 返回 dict 加同样 2 个 key (运维可通过
    `/api/system/stats` 或 `aiia_sse_*` 暴露 alertmanager 监控)。

  **测试 (24 cases / 8 invariant class + 12 subtests)** ——
  `tests/test_sse_schema_validate_toggle_r205.py`:

  1. **TestSseSchemaValidateModeOff** (3): default + 空字符串 → off,
     **零开销契约** (spy 验证 validate_payload 在 100 次 invalid emit
     下 call_count == 0);
  2. **TestSseSchemaValidateModeWarn** (5): mode value + 合法/非法
     payload 行为 + 一条 emit 多字段错只算 1 次 + emit 仍 fanout 给
     subscriber (不阻塞);
  3. **TestSseSchemaValidateModeStrict** (4): mode value + log.error
     (与 warn 区分) + **不 raise 契约** (4 种 invalid input + None
     payload + 非 dict + missing required + unknown event_type 全部
     emit 不抛) + emit 仍 fanout;
  4. **TestSseSchemaValidateEnvVarParsing** (4 + 5 + 5 subtests): 大
     小写 normalize + whitespace trim + 无效值 fall-back off + startup
     WARN + helper 默认值返回;
  5. **TestSseSchemaValidateRegisteredEventsRoundTrip** (1 + 4 sub-
     tests): R198 注册的 4 个 schema event 正确 payload → warn mode 0
     violation (subtests 覆盖 task_changed / config_changed / log_
     level_changed / oversize_drop, 端到端可用性证明);
  6. **TestSseSchemaValidateStatsSnapshot** (3): mode + total 暴露 +
     incrementing + off mode 在 50 次 invalid emit 下仍 total == 0;
  7. **TestModuleLevelConstants** (3): default mode + env var name +
     valid mode set 三个常量值锁定 (公共 contract);
  8. **TestStrictModeNoRaiseUnderConcurrency** (1 · **核心安全契
     约**): 4 thread × 20 emit 并发 invalid payload strict mode 不
     crash, 80 violations 累加正确, fire-and-forget 契约硬性 lock。

  **测试设计 · dedup cache 清理**: `EnhancedLogger` 内置 5 秒消息去
  重 cache 防日志风暴, 但跨 test 共享 state 会让 `assertLogs` 抓不
  到「重复 violation message」。R205 测试在 setUp + subTest 内部清
  `task_module.logger.deduplicator.cache`, 确保每条 R205 log 都能被
  抓到 (production 行为不变, 仅是 test 隔离的工程实践)。

  **验证**: R205 24 cases + 12 subtests PASS；`uv run ty check . →
  All checks passed!`（含 1 处 `# ty: ignore[invalid-argument-type]`
  on 故意非 dict payload, 测的就是 emit 对 caller 误用的 robust 处
  理）；`uv run ruff check . && ruff format --check . → All passed!`；
  完整 `pytest` **5428 passed / 2 skipped / 640 subtests passed in
  165s** (R206 baseline 5404 → 5428, 净增 +24 from R205)；`scripts/
  generate_docs.py --check` 两份语言 26/26 一致（task.py 不在
  `MODULES_TO_DOCUMENT` 列表）；R198 / R202 / R203 完整测试套
  64 cases + 20 subtests PASS（向后兼容验证, 新 toggle 在 default
  off 下与历史行为完全一致）。

- **R206 / Cycle 9 · F-release-1 (CR#21 §4.4): pre-tag-push checklist
  + retag safety window docs**. v1.7.2 的 docs-sync miss 暴露了一个
  长期被忽视的 surface：`release.yml` 失败模式都是 publish-job
  级（PyPI / Open VSX / Marketplace），但 **tag push 触发的 main
  分支 `Tests` workflow** 失败时，tag 会停在 CI 红的 commit 上、
  publish job 一个都不跑，需要 force-retag 才能恢复（v1.7.2 5 分钟
  内 retag `36222a3` → `35f9671`）。

  R206 把这次经验固化进文档：

  - 新增 "Pre-tag-push checklist" section (13 步本地预飞行)：
    `git pull --ff-only` + ruff + ty + 双语 docs parity + full
    pytest + uv lock + `check_tag_push_safety.py` + CHANGELOG
    sanity + `bump_version.py` + annotated tag + `gh run watch`；
  - "Retag safety window" 子段：5 分钟 / 30 分钟两档（"no Publish
    succeeded yet" + "< 30 min since broken push" + "no GitHub
    Release yet"），明确**何时可以 force-retag、何时必须 bump
    patch**；
  - "Tag-was-moved history" 历史表：v1.6.3 + v1.7.2 两次 retag
    原因 + 旧/新 SHA，强化「retag 不是单次事件」+ 帮助 future
    maintainer 看到「为什么需要这份 checklist」的具体动机；
  - 两份语言 (`release-recovery.md` + `release-recovery.zh-
    CN.md`) lockstep 同步，沿用 R178 / R185 双语契约。

  **新增 R206 test** (`tests/test_release_recovery_pre_tag_
  checklist_r206.py`, 5 cases · 沿用 R185
  `TestReleaseRecoveryBilingualSync` 思路): "Pre-tag-push
  checklist" / "Tag 推送前清单" 段标题存在 + v1.7.2 retag 案例
  (含 SHA 36222a3 / 35f9671) + v1.6.3 retag 历史 + F-release-1
  label + retag 窗口 30 minutes / 30 分钟数值一致。这是 R185
  `TestReleaseRecoveryBilingualSync` 的姊妹守护，防止两份文档
  漂移。

  **设计权衡 · 测试做 static string 匹配而非语义校验**：
  与 R185 思路一致——文档总会小调整，过严的字符串匹配会自伤；
  test 断言「关键 keyword 出现过」，留出 wording polish 空间。

  **验证**: R206 5 cases PASS；R185 8 cases regression PASS；
  `uv run ty check . → All checks passed!`；`uv run ruff
  check . && ruff format --check . → All passed!`；完整
  `pytest` **5404 passed / 2 skipped / 628 subtests passed
  in 163s** (R204 baseline 5399 → 5404, 净增 +5 from R206)；
  `scripts/generate_docs.py --check` 两份语言 26/26 一致
  （release-recovery 不在 `MODULES_TO_DOCUMENT` 内，但 R206
  docs 改动不会影响 `docs/api/` source-derived 文档）。

- **R204 / Cycle 9 · F-203-1 (CR#21 §4.3): `aiia_token_age_seconds`
  Prometheus gauge**. R199 把 token rotation 时间戳暴露到 `GET
  /api/system/api-token-info` endpoint 的 `age_seconds` 字段，但
  alertmanager 想做「90 天没轮换 → alert」必须**自己 scrape JSON**——
  绕开 Prometheus scrape 的标准方式，运维链路变长 + 多一份配置。
  R204 把同一份数据 mirror 到 Prometheus exposition `aiia_token_age_
  seconds` gauge，让 alertmanager 用标准 PromQL 直接写规则（如
  `aiia_token_age_seconds > 90 * 86400` per NIST SP 800-63B
  rotation guidance）。

  **实现** (`web_ui_routes/system.py`)：

  - 新增 module-level helper `_safe_token_age_seconds() -> int | None`
    (~30 行)。**逻辑契约与 R199 endpoint inline 完全一致**: no token
    / no rotated_at / 解析失败 / future timestamp 全部 → None；正常情
    况 → int (秒, ≥ 0)。
  - 在 `_render_prometheus_metrics` 加新 Security section, gauge
    metric (~18 行包含详细 HELP)。
  - 更新 `/api/system/metrics` endpoint description docstring 提及
    新 metric + 失败时 omit 契约（与 `aiia_uptime_seconds` 同款）。

  **设计决策 · 失败时 omit metric vs NaN**：

  Prometheus exposition 允许 NaN 值表示 "unavailable", 但 omit metric
  让 Grafana 显示 "no data" + 让 alertmanager 用 `absent(...)`
  rule 触发分级告警 (no-token vs token-stale 是两类问题, 用 absent /
  threshold 分别处理), 与 `aiia_uptime_seconds` / `aiia_build_info`
  等其他 `_safe_*` helper 同款契约，对齐项目一致性。

  **R199 endpoint inline 与 R204 helper 刻意 duplicated**：

  endpoint inline 已被 R199 测试覆盖 5+ case，重构有 backward-compat
  风险；endpoint 返回 dict (多字段) vs helper 返回 int | None (单值)，
  抽象层不对齐。两份实现是 verbatim 复制粘贴，任何 bug fix 必须同步
  ——本 cycle 的 `TestEndpointMetricParity` invariant 在同一份 config
  + 同一时间点下抽样验证两路 age 一致（容差 ≤ 2 秒，覆盖 clock
  granularity + 测试运行时间）。R205+ 可考虑统一抽象层。

  **测试 (11 cases / 4 invariant class)** ——
  `tests/test_token_age_seconds_metric_r204.py`:

  1. **TestSafeTokenAgeHelper** (6): no token / token < 16 char /
     no rotated_at / malformed rotated_at / future timestamp / valid
     recent rotation → None / None / None / None / None / positive int;
  2. **TestPrometheusMetricRendering** (3): token + recent rotation
     → metric line 出现 + 无 token → metric 不出现 + 45-day-old token
     (NIST 30-90 中点) 渲染正确 age (容差 ±60 秒);
  3. **TestEndpointMetricParity** (1 · **核心契约**): 同一份 config 下
     `GET /api/system/api-token-info` 的 `age_seconds` 与
     `/api/system/metrics` 的 `aiia_token_age_seconds` 值差异
     ≤ 2 秒——防止 R199 endpoint 与 R204 helper 实现 drift;
  4. **TestPrometheusOutputFormat** (1): HELP / TYPE / value 行格式
     合规 + HELP 含 R204 / F-203-1 / "rotated" 关键字。

  **验证**: R204 11 cases PASS；`uv run ty check . → All checks
  passed!`；`uv run ruff check . && ruff format --check . → All
  passed!`；完整 `pytest` **5399 passed / 2 skipped / 628 subtests
  passed in 163s** (R203 baseline 5388 → 5399, 净增 +11 from R204)；
  `scripts/generate_docs.py --check` 两份语言 26/26 一致；R199
  + R203 完整测试套 (15 + 10 cases + 4 subtests) 仍 PASS（向后兼容
  + 不变量验证）。

- **R203 / Cycle 9 · F-202-1 (CR#21 §4.2): `_SSEBus._emit_by_type`
  cardinality cap + overflow bucket + WARN-once**. R202 把
  `_emit_by_type: Counter[str]` 暴露到 Prometheus
  `aiia_sse_emit_by_type_total{event_type="..."}`，但 Counter 本身
  没有 key 数上限——如果上游 emit 不慎用动态字符串当 event_type（R198
  AST guard 已卡 source-level，但 `oversize_drop` 替换路径 + 未来代
  码误用 / 测试残留是真实 attack/bug surface），Counter 会无限增长，
  造成 memory leak + Prometheus exposition payload 膨胀 + Grafana
  cardinality 爆炸 + counter pollution 让 top-N 视图全是噪声。

  **R203 防御实现**（`web_ui_routes/task.py::_SSEBus` ~30 行）：

  - 类常量 `_EMIT_BY_TYPE_MAX_CARDINALITY = 100` (R198 4 schema
    event + ~10× 未来扩展 + ~10× `oversize_drop` 替换余量；对应
    exposition payload ~10 KB << Prometheus 默认 100 KB scrape 配额)；
  - 类常量 `_EMIT_BY_TYPE_OVERFLOW_BUCKET = "__other__"`；
  - 实例 flag `_emit_by_type_cap_hit_warned: bool`（`__init__`
    初始 `False`）；
  - `emit()` 累加分支 cap-check：`event_type` 不在 Counter 且
    `len(Counter) >= cap` → 路由到 overflow 桶 + 全进程首次 WARN log
    + 设置 flag；之后所有 overflow emit 继续走 `__other__` 桶累加，
    **不**重复 WARN（防日志风暴）。

  **设计契约**：

  - **R202 sum 不变量保持**: 即使 cap 触发，`sum(by_type) == emit
    _total` 仍然 hold，因为 overflow emit 走 `__other__` 桶累加而
    非 silently drop；Grafana 上 `__other__` series 立刻可见，运维
    一眼能识别 "low-frequency or capped-out event types"；
  - **R198 4 个 schema event 永远不会落到 `__other__`**: 因为它们
    是 first-class events，在 cap 之前就已经在 Counter 里，cap-check
    `event_type not in self._emit_by_type` 分支不会命中它们；
  - **WARN-once policy**: 全进程只 WARN 一次（`_emit_by_type_cap_hit
    _warned` flag），WARN 内容含 cap 值 + 首个 overflow event_type +
    "考虑提高 cap 或审计 emit-site code" 行动建议。

  **测试 (10 cases / 5 invariant class + 4 subtests)** ——
  `tests/test_sse_emit_by_type_cardinality_cap_r203.py`:

  1. **TestBelowCardinalityCap** (2): 单 type / 多 type < cap → 无
     overflow 桶、无 WARN flag set；
  2. **TestAtCardinalityCapTrigger** (3): 第 cap+1 个 emit 路由到
     `__other__` + WARN 触发 + 重复 overflow emit 不重复 WARN；
  3. **TestKnownTypesNotAffectedByCap** (2 + 4 subtests): cap 触发
     后老 type 仍累加 + R198 4 个 schema event 全部 immune（subtests
     覆盖 task_changed / config_changed / log_level_changed /
     oversize_drop）；
  4. **TestSumInvariantUnderCap** (1): **R203 核心契约**——cap 触发
     场景下 `sum(by_type) == emit_total` 严格成立；
  5. **TestCardinalityCapLockColocation** (2 · **AST guard**):
     `_SSEBus.emit` 源码 cap-check（`len(self._emit_by_type) >=
     self._EMIT_BY_TYPE_MAX_CARDINALITY`）+ overflow 桶累加
     (`self._emit_by_type[self._EMIT_BY_TYPE_OVERFLOW_BUCKET] +=
     1`) 必须都在 `with self._lock:` 块内。runtime 测试 race
     window ("`len()` 读到 ≥ cap，但还没 `+= 1`" 之间另一线程
     插队让 cap 实际超过 1-2 个) 难触发，AST guard 在 source-level
     锁定结构。沿用 R197 / R202 同款 AST guard 模式。

  **验证**: R203 10 cases + 4 subtests PASS；`uv run ty check . →
  All checks passed!`；`uv run ruff check . && ruff format --check
  . → All passed!`；完整 `pytest` **5388 passed / 2 skipped /
  628 subtests passed in 162s** (R202 baseline 5378 → 5388, 净增
  +10 from R203)；`scripts/generate_docs.py --check` 两份语言全
  过；R202 完整测试套 (12 cases + 4 subtests) 也 PASS（向后兼容验证）。

- **R202 / Cycle 8: `aiia_sse_emit_by_type_total{event_type="..."}`
  Prometheus counter (方案 B · 向后兼容新增)**. SSE bus 在 R198 已经维护
  per-type 计数 `_SSEBus._emit_by_type`（`stats_snapshot()["emit_by_type"]`
  暴露），但**之前未在 Prometheus exposition** 中渲染。R202 把这份数据
  按 `aiia_sse_emit_by_type_total{event_type="task_changed"} N` 形式渲
  染到 `/api/system/metrics`，方便 Grafana 拉 per-event_type breakdown
  仪表盘（cycle 8 observability 主线 R196 → R197 → R198 的自然收尾）。

  **设计权衡 · 方案 B vs A**

  方案 A 是给现有 `aiia_sse_emit_total` 加 `event_type` label——直接
  在原 metric 上 partition。但 Prometheus exposition format 规约（见
  https://prometheus.io/docs/concepts/data_model/）**不允许同一 metric
  name 在不同 scrape 间切换 label set**：已有未标签化 series
  `aiia_sse_emit_total 42` 直接加 label 后变成 `aiia_sse_emit_total
  {event_type="..."} N`，strict parser（VictoriaMetrics、Cortex、最新
  版 Prom）会报 `inconsistent labels for metric family`；Grafana 老
  dashboard 的历史曲线会断在升级时间点。

  方案 B（**本 R202 采用**）：新增独立 metric `aiia_sse_emit_by_type_total
  {event_type="..."}`，与原 `aiia_sse_emit_total`（无 label）并存。

  - 优点：100% 向后兼容；Grafana 老 dashboard 不变；新 dashboard 可用
    per-type breakdown；不变量 `sum(aiia_sse_emit_by_type_total series)
    == aiia_sse_emit_total` 让 metric correctness 显式可验证（test 锁定）。
  - 缺点：metric 数量 +1 family + N series（N == event_type 数 == 当前 4）；
    Prometheus storage 微增（4 series × 16 bytes ≈ 64 bytes/scrape，可
    忽略）。

  实现细节（`web_ui_routes/system.py::_render_prometheus_metrics` SSE
  bus section 新增 ~35 行）：

  - 复用既有 `_format_prom_metric_family` (R187/R190 共享 helper)，**HELP
    / TYPE 各只出现一次**，避免 R187 踩过的 `second TYPE for metric` 坑；
  - `event_type` 标签值按字典序排序，让 exposition 输出 deterministic
    （Prometheus parser 不要求顺序，但 diff-friendly + smoke test 易写）；
  - 零 emit 时**不**输出 family（避免空 `# HELP/# TYPE` 污染 exposition）；
  - 失败优雅降级：`snap.get("emit_by_type")` 不是 dict 或为空 → silently
    跳过，与 R197 / R198 同档防御。

  **测试 (12 cases / 5 invariant class + 4 subtests)** ——
  `tests/test_sse_emit_by_type_counter_r202.py`：

  1. **TestSseEmitByTypeCounterRendering** (4 cases): 单 type / 多 type
     独立 series / 零 emit 不出 family / exposition 格式合规（HELP/TYPE
     各 1 次 + label 引号 + 排序确定性）；
  2. **TestSseEmitByTypeSumInvariant** (2 cases): 同步 `sum(by_type) ==
     emit_total` + 8 线程 × 50 emit 并发压测下 sum 不变量仍严格成立；
  3. **TestSseEmitByTypeSchemaCoverage** (2 cases / 4 subtests): R198
     注册的 4 个 event_type 全部可渲染（subtests 覆盖 task_changed /
     config_changed / log_level_changed / oversize_drop）+ 未注册 type
     也能正常渲染（defensive，防 silently drop）；
  4. **TestSseEmitCounterLockColocation** (2 cases · **AST guard**):
     `_SSEBus.emit` 源码 `self._emit_total += 1` 与
     `self._emit_by_type[event_type] += 1` 必须在**同一**
     `with self._lock:` 块内紧贴 + 无 orphan `_emit_by_type` 累加
     出现在锁外——这是 sum 不变量 atomicity 的 source-level 守护，
     runtime 并发测试 race window 太窄 catch 不到，必须 AST 锁结构（见
     class docstring 详述「为什么 runtime test 不够」，沿用 R197 `Test
     SourceLevelLatencyPathColocation` 同款思路 + CR#16 §3.5 论述）；
  5. **TestBackwardCompatibility** (2 cases): 原 `aiia_sse_emit_total`
     仍以**无 label** 形式存在（保 Grafana 老 dashboard）+ 新旧两个
     metric family 完全独立（HELP/TYPE 各 1 次）。

  **验证**: R202 12 cases + 4 subtests PASS；`uv run ty check . → All
  checks passed!`；`uv run ruff check . && ruff format --check . → All
  passed!`；完整 `pytest` 5378 passed / 2 skipped / 624 subtests
  PASS in 159s（v1.7.2 baseline 5366 → 5378, 净增 +12 from R202）；
  `scripts/generate_docs.py --check` 两份语言全过（system.py 改的是
  endpoint description docstring，会被 docs/api 抓到，本地预 regen 验证
  parity）。

## [1.7.2] — 2026-05-14

### Dependencies

- **authlib 1.7.0 → 1.7.1** (Dependabot #39, commit `83c2bf7`). Patch
  release，无 breaking change，主要是 JWT validation 性能微调，无需测试
  / 调用方调整。

### Fixed

- **CI · `Tests` workflow green-build restore** (commit `83c2bf7` aftermath,
  RCA 见下). 修 `uv run ty check .` 在 CI 报的 38 个 type-check diagnostics
  (31 errors + 7 unused-ignore warnings)——分布在 4 个 source + 12 个 test
  files。**根因不是** dependabot 的 `authlib 1.7.0 → 1.7.1` bump，而是
  `v1.7.1` 发布时 Astral `ty 0.0.34` 走得比之前严格，把一批长期潜伏的
  type 不严谨写法暴露出来；`83c2bf7` 只是触发了再跑 CI 才看到 `Tests`
  红。修复策略遵循「最小侵入 + 不改 runtime 行为」：

  - **Source · 7 errors**
    - `enhanced_logging.get_current_log_level` 返回类型从
      `dict[str, str]` 修正成 `dict[str, str | list[str]]`——之前签名
      与 `valid_levels` 字段的实际 `list[str]` 值不一致，是真实 bug；
    - `mcp_tool_call_metrics._latency_state` / `notification_manager.`
      `_provider_latency_histograms[key]` 两处 dict-literal 初始化加
      `cast("dict[str, Any]", ...)`，因为 ty 0.0.34 把 `{"count": 0,
      "sum_seconds": 0.0}` narrow 成 `dict[str, int | float]` 后再做
      `state["count"] += 1` 报 `unsupported-operator`——cast 一次告诉
      ty「这个 state 是异构 value bag」就 unblock；
    - `mcp_tool_call_metrics.ToolCallCounterMiddleware.on_call_tool`
      加 `# ty: ignore[invalid-method-override]`——fastmcp 父类
      `Middleware.on_call_tool` 的 `context` 参数没带 generic, 子类把
      它窄化到 `MiddlewareContext[CallToolRequestParams]` 是 fastmcp
      `server/middleware.py` docstring 推荐的 type-narrow pattern (让
      IDE hover `context.message.name` 拿到 `str`)，ty 现版本对这种
      covariant parameter override 还不能识别，等 `ty` 支持后可移除；
    - `web_ui_routes/system._render_prometheus_metrics` 在 `isinstance(
      stats, dict)` 之后加 `stats_typed = cast("dict[str, Any]", stats)`，
      ty 在 isinstance narrow 之后把 dict 推成 `dict[Never, Never]`，
      `.get(key)` 报 `invalid-argument-type`——cast 是当前唯一无副作用
      的解决方案 (assert isinstance 不能再窄化 generic 参数)。

  - **Tests · 24 errors + 7 unused-ignore**
    - `test_server_print_config` 4 处 `_redact_sensitive` 调用全部
      改用 `cast("dict[str, Any]", ...)` / `cast("list[dict[str, Any]]",
      ...)` 替代 `isinstance` 断言——ty 对 narrow 后 generic dict 的
      `Unknown` key 类型推不出 `Literal[str]` 兼容，cast 是 idiomatic 解；
    - `test_latency_invariant_r197` / `test_sse_event_schemas_r198`
      / `test_health_env_overrides` 在 `assertIsNotNone` 之后补
      `assert x is not None` 做 ty narrow——unittest 的 assertX 不是
      `ty` 识别的 narrowing form，得用 `assert` 显式 narrow；
    - `test_check_changelog_diff_scope` 的 `check_changelog_diff_scope`
      import 加 `# ty: ignore[unresolved-import]`——该脚本通过
      `sys.path.insert(0, "scripts/")` 注入，ty 静态 resolve 不到；
    - `test_check_tag_push_safety_cve_gate_r185._patch_subprocess` 的
      `side_effect` 参数类型从 `Exception | None` 扩到 `Exception |
      type[Exception] | None`——mock 框架确实支持 class 或 instance；
    - `test_critical_preload_r21_1` / `test_i18n_pseudo_locale` /
      `test_i18n_ts_types_gen` 五处 `pytest.fail(reason)  # ty:
      ignore[invalid-argument-type]` 把 `# ty: ignore` 删掉——`ty`
      已识别 `pytest.fail(str)`，ignore 变成 unused warning；
    - `test_hot_reload_network_security_r193` 把
      `ConfigManager.get_web_ui_config()` 改成 `get_section("web_ui")`
      ——前者从未存在，是 ty 之前漏报的 typo；
    - `test_prom_histogram_r190` 四处 `await mw.on_call_tool(_Fake
      Context(...), call_next)` 加 `# ty: ignore[invalid-argument-
      type]`——`_FakeContext` 是测试用 minimal fake，刻意不实现完整
      `MiddlewareContext` Protocol；
    - `test_sw_static_cache_r21_2` / `test_vscode_vsix_size_budget`
      两处 `pytest.skip(msg)  # ty: ignore[too-many-positional-arguments]`
      把 `# ty: ignore` 删掉——同样是 ty 0.0.34 已正确处理；
    - `test_system_log_level_runtime_r188` 两处 `apply_runtime_log_level
      (123)` / `(None)` 在原有 `# type: ignore[arg-type]` (mypy)
      后追加 `# ty: ignore[invalid-argument-type]`——故意传非法值测
      `ValueError`，是 deliberate type violation。

  **验证**: `uv run ty check . → All checks passed!` (从 38 → 0 diagnostics);
  `uv run ruff check . && ruff format --check . → All checks passed!`;
  完整 `pytest` 5366 passed / 2 skipped / 620 subtests passed in 147.88s
  (跟 v1.7.1 的 5366 数完全一致, 零 test 被破坏)。

### Docs

- **R201 / Cycle 8: CR#20 §4.3 docs polish batch** (F-196-1 + F-197-1 +
  F-199-3, commit `7ec8d91`). 三处零行为变更的文档加注，配合 cycle 7 / 8 已落地的代码改动：

  - **F-196-1**: `notification_manager._DEFAULT_LATENCY_BUCKETS_SECONDS`
    的 docstring header 加 `(CR#19 §4.1 「R190' · histogram bucket
    selection per-metric vs project-wide」follow-up)` inline marker。
    原 docstring 段落里有 "CR#19 §4.1 指出..." 引用，但 header 没有
    显式 cross-reference，maintainer 浏览 attribute 列表时不易看到
    R196 的来源——补这个 marker 让 "为什么这组桶长这样" 的源头一眼
    可见，与 R200 注释的 `R200 / Cycle 8 · F-199-1 from CR#20 §4.1`
    风格对齐；
  - **F-197-1**: `TestSourceLevelLatencyPathColocation` class docstring
    扩 12 行 `**为什么用 AST guard 而不是 runtime test**` 段落，
    引用 CR#16 §3.5 「structural invariants vs runtime tests」。原 3 行
    docstring 只说了 "两路必须紧贴" + "防 refactor 错开"，没解释「为
    什么 runtime test 抓不到」——补充说明 R142 `latency_ms_total` 与
    R191 `_record_provider_latency_bucket` 共用同一份 `latency_ms`
    采样，refactor 把两者挪到不同 lock 块时 runtime test 仍然全 PASS
    但 dashboard 上 `avg` 跟 `P95` 会悄悄走偏，只有 parse AST 锁
    "同一 `with self._stats_lock:` 块内" 这条结构性约束才能捕获；
  - **F-199-3**: `POST /api/system/rotate-api-token` (R195) docstring
    description 段加段说明同时写入 `api_token_rotated_at`——R199 引入
    了这个字段，但 R195 docstring 没同步说明 rotation 时除了 `api_token`
    还更新 `api_token_rotated_at`，仅 schema 部分提了 `rotated_at`
    响应字段。补段同时点名 R200 cascade-clear 在 admin 后续撤销 token
    时会同步清空时间戳，让 admin 读 docstring 就理解 R195 → R199 → R200
    的完整 lifecycle，不必跨多个文件追源码。

  **Test**: R191 + R195 + R197 + R199 + R200 + docs-parity 全跑 → 67/67
  + 41/41 PASS；ruff lint + format 全通过；scripts/generate_docs.py 重跑
  无 diff（这些 docstring 都是 attribute / class / closure level，不会被
  `MODULES_TO_DOCUMENT` 抽到 `docs/api/` 顶层 .md）；完整 5366/5366
  test suite PASS (163s)。

  零行为变更——纯 documentation polish，CR#20 §4.3 列为 "Docs / R200
  trivial-fixes batch candidate"。

  Refs: CR#20 §4.3 (F-196-1 + F-197-1 + F-199-3).

## [1.7.1] — 2026-05-13

### Fixed

- **R200 / Cycle 8: stale ghost cascade-clear for `api_token_rotated_at`**
  (CR#20 §4.1 / F-199-1). R199 持久化 `api_token_rotated_at` 进 config
  后留了一个微妙不变量：admin 手动 edit `config.toml` 把 `api_token =
  ""` 撤销 token 时，**没有**任何机制同步清空 `api_token_rotated_at`。
  结果 `GET /api/system/api-token-info` 会返回:

  - `has_token = false`（token 已撤销）
  - `rotated_at = "2026-04-02T..."`（指向上次 rotation）
  - `age_seconds = ~5.2M`（≈ 60 天）

  Dashboard 按 NIST SP 800-63B 90 天规则会误报「token 60 天未轮换」——
  但实际 token 早已不存在。这是 **"stale ghost" rotation 提醒**。

  R200 在 `_validate_network_security_config` 走完所有字段 normalize
  之后加一道 sanity check: 如果 `api_token` 经过 normalize 为空（包括
  显式 `""` / < 16 字符被丢弃 / 全空白被清洗）但 `api_token_rotated_at`
  非空 → log warning + cascade-clear 时间戳为空串。**不变量**: normalize
  完成后 `api_token` 在 ⇔ `api_token_rotated_at` 在（empty/empty
  也满足）。

  这道 sanitize 是**幂等**的 (cascade-clear 后再调一次 normalize 仍是
  一致状态)，自动覆盖三条路径:

  - **直接 normalize**: `_validate_network_security_config(raw)` 单独
    调用就会 cascade（如 `set_network_security_config` / 文件 first-load
    走的就是这条）；
  - **incremental update**: `update_network_security_config({"api_token":
    ""})` 不传 `rotated_at` 时，merged dict 进 validate → cascade 自动
    触发 → 写回 config；
  - **R199 端点**: `GET /api/system/api-token-info` 读 cache 看到的
    永远是 cascade 之后的一致状态。

  **Test coverage** (`tests/test_api_token_cascade_clear_r200.py`,
  13 cases / 4 invariant classes):

  - **Direct normalize path** (5): ghost state cascades; short token (<16)
    cascades; whitespace-only token cascades; valid token+rotated_at
    untouched; empty+empty no-warning (避免日志 noise);
  - **Incremental update path** (3): explicit clear cascades; explicit
    both-clear no-ghost; set short token cascades；
  - **R199 endpoint interaction** (3): cascade → endpoint 立刻看到一致
    状态; R195 rotate → admin clear → 一致; R195 rotate 不被 cascade
    误伤；
  - **Invariant + idempotency** (2): 二次 normalize 不再触发 warning;
    warning text 含 `'cascade-clear'` / `'stale ghost'` 字符串用于
    audit grep。

  **Test infrastructure note**: ai_intervention_agent 用自定义
  `EnhancedLogger`（loguru 后端 + `propagate=False`），`assertLogs`
  拿不到 named-logger 消息。R200 测试套引入轻量 `capture_ns_warnings`
  上下文管理器（patch 模块级 `logger.warning`）替代 `assertLogs`
  ——可复用模式, 适用于其他「期望特定 marker 出现在 warning」的测试。

  **Test**: R200 + R199 + R195 + R193 + R189 + ns_config 全跑 → 182/182
  PASSED; ruff check 无报错。

  Refs: CR#20 §4.1 (F-199-1, Important / R200 candidate).

### Docs

- **CR#20 / Cycle 7 review archived** (`docs/code-reviews/cr20.md`).
  Reviews the 4 commits landed since CR#19 (R196 notification buckets,
  R197 latency invariant, R198 SSE schema registry, R199 API token info)
  + lists follow-up candidates ranked by severity:
  - F-199-1 (important, R200 candidate): auto-clear `api_token_rotated_at`
    when `api_token` becomes `""` to avoid "stale ghost" rotation state;
  - F-196-1 / F-197-1 / F-199-3 (docs batch): cross-references + 3-line
    docstring header on AST guard test class + R195 docstring sync;
  - F-198-1 / F-198-2 / F-199-2 (nice-to-have): schema `field_types`,
    deep payload validation, `recommended_rotation_age_days` config.
  Verdict: ✅ healthy cycle, no critical issues, all features carry
  AST-level / source-level guards against silent decay (the cycle-7
  signature pattern). Recommends R200 priorities and notes schema-driven
  evolution beyond SSE (provider types, CLI commands, metric families)
  as a parking-lot direction for future cycles.

### Added

- **R199 / Cycle 7: API token age + last-rotated tracking
  (`GET /api/system/api-token-info`)** — CR#18 §4.4 follow-up extension.
  R195 (`POST /api/system/rotate-api-token`) 让 admin 通过 HTTP rotation
  无需重启，但**没有**任何方式查询「上次什么时候轮换的」。Admin 想做
  「90 天没轮换就 alert」（NIST SP 800-63B 推荐 30-90 天轮换周期）只能
  自己维护 rotation 时间戳，重启就丢——这跟 R195 把 rotation 从「编辑
  config + restart」简化为「HTTP 一调用」的初衷矛盾。

  R199 的两段改造：

  1. **持久化 rotation 时间戳进 config**:
     - 新 config field
       `[network_security].api_token_rotated_at: str = ""`（ISO-8601 UTC，
       如 `2026-05-13T16:00:00Z`）。
     - R195 endpoint 改造：generation 时间戳生成**前移**到
       `update_network_security_config` 调用**之前**——同一个 ISO 字符串
       同时写进 config 和 response，让磁盘里的 `rotated_at` 跟 client
       拿到的字符串**完全一致**，后续 GET 算 age 就是准确的。
     - `_validate_network_security_config` 强校验：必须以 `Z`/`+00:00`
       结尾且能被 `datetime.fromisoformat` 解析；脏数据 → 空串 + warning。

  2. **新端点 `GET /api/system/api-token-info`**:
     - **Loopback-only** (复用 R195 同款 gate)——token age 不是 secret
       但仍敏感（攻击者据此预测下次 rotation 窗口）；
     - Rate-limit `30 per minute`（admin 工具 poll-friendly + 防滥用）；
     - Response: `{success, has_token, token_length, rotated_at,
       age_seconds}`。`has_token` 是 `bool`（token 已配置 + 长度 ≥ 16）；
       `token_length` 为 `int | None`；`rotated_at` 是 ISO-8601 字符串
       或空串；`age_seconds` 是 `int | None`（未配置 / 解析失败 / 时钟
       跳变到未来 → `null`，**不**返回 0——0 会误导 dashboard 当成
       「刚轮换」）；
     - **绝不**返回 `api_token` 明文——rotation endpoint 是唯一发放
       明文 token 的时机。

  **设计权衡**:

  - **为何把 timestamp 也持久化进 TOML**: 之前 R195 只把 token 写进 config
    （`rotated_at` 只在 response 里出现一次），admin 必须自己存。R199 改造
    后任意时刻都能查 token age，不依赖 admin 工具自己维护状态。
  - **为何不返回 token**: 把 token info endpoint 和 rotation endpoint 拆
    成两个不同 contract——info 是「频繁 poll」, rotation 是「偶尔触发」。
    info 不返回 token 让它**可以**被频繁 poll 而不增加密文 expose 面。
  - **未来时间戳 / 时钟跳变 → null**: 如果 admin 手动改了 config 把
    timestamp 改成未来（或 NTP 跳变），`age_seconds` 会变成 0 或负数。
    Endpoint 把 < 0 显式映射为 `null`，避免 dashboard 看到 `age_seconds: 0`
    误判为「刚刚轮换」。

  **Test coverage** (`tests/test_api_token_info_r199.py`,
  15 cases / 5 invariant classes):

  - **Loopback gate** (2): non-loopback → 403; loopback → 200；
  - **Response schema** (5): 必有 5 字段; no-token shape; **token 永不
    leak（最关键的安全不变量，扫所有 string 字段）**; long-enough token
    → has_token=True + length; too-short → has_token=False + null length；
  - **age_seconds calculation** (4): empty → null; recent → 接近实时;
    90 天 → ~7,776,000 秒 ±60s; future → null（不是 0）; malformed → null；
  - **Rotation → info E2E** (2): R195 写 → R199 读 `rotated_at` 应完全
    一致 + age ≈ 0; token_length 匹配；
  - **Source-level guards** (1): rate-limit `30 per minute` 装饰器存在 +
    endpoint 函数体里**绝不**出现 `"api_token":` 字面量（防后续 refactor
    误加 `api_token` 进 response）。

  顺带 sync `tests/test_network_security_config.py::test_output_structure`
  把 `api_token_rotated_at` 加入预期 schema keys (R189 schema invariant
  test 扩张)；`docs/configuration.md` + `docs/configuration.zh-CN.md`
  network_security 表格加新行；`config.toml.default` 加默认值 + 注释
  描述「rotation endpoint owns this field; don't edit by hand」。

  **Test**: R197 + R198 + R199 + R195 + R193 + R189 + network_security
  config 全跑 → 197/197 PASSED；全 suite → 5366/5366 PASSED；
  ruff check 无报错。

- **R198 / Cycle 7: SSE event schema registry
  (`ai_intervention_agent/sse_event_schemas.py`)** — CR#19 §4.3 后续。
  Project 的 SSE bus (`web_ui_routes/task.py::_SSEBus`) 接受 free-form
  `(event_type: str, data: dict | None)` 参数——任何模块都能
  `_sse_bus.emit("anything", whatever)`，bus 本身不验证。设计上保留这
  种灵活度，但 *前端订阅方* (Activity dashboard JS / VSCode webview)
  没有 source-of-truth 可参考——只能靠 grep + commit 历史试错，
  容易 silent drift。

  R198 把所有已知 event types + payload schema 集中定义在新模块:

  - `EventSchema` dataclass: `(name, required_fields, optional_fields,
    description, emitted_by)` —— frozen + frozenset 让 schema 对象本身
    hashable + immutable；
  - 当前注册 **4 个** event types: `task_changed` / `config_changed` /
    `log_level_changed` / `oversize_drop`；
  - Public API: `EVENT_SCHEMAS`, `get_known_event_types()`,
    `get_schema(event_type)`, `validate_payload(event_type, payload)`；
  - **不引入运行时验证**: emit() 在 `_lock` 临界区里跑，添加 schema
    check 会拖慢 fan-out throughput。验证只在 test-time / IDE-time
    通过 `validate_payload` API 暴露。

  **Test coverage** (`tests/test_sse_event_schemas_r198.py`,
  18 cases / 5 invariant classes):

  - **Registry well-formedness** (4): schema 是 EventSchema 实例 /
    name == registry key / required+optional 是 frozenset / 两个字段
    集 disjoint；
  - **Validation API correctness** (5): valid payload → empty; missing
    required → flag; unexpected field → flag; unknown event_type →
    flag; valid + optional 也 OK；
  - **Public API contract** (2): `get_known_event_types` 返回 sorted
    tuple; `get_schema(unknown)` → None；
  - **Source-coverage AST guard** (4): 整 `src/` 下所有
    `_sse_bus.emit("<literal>", ...)` 调用的 event_type literal **必须**
    在 EVENT_SCHEMAS。加新 event type 而忘了注册的 commit 在这里
    fail-fast。同时检查 emit-site module path 出现在 schema 的
    `emitted_by` tuple 里——防止 emit 站点搬家而忘了同步注册表。
    Variable event_type 形式只允许 bus 自身的 oversize_drop 替换路径；
  - **emit-site payload coverage** (3): 已知 dict-literal emit
    (`config_changed`, `log_level_changed`, `oversize_drop` 内置替换)
    的 payload 字段 ⊆ schema.required ∪ schema.optional, 且 ⊇ required。

  顺带 sync `scripts/generate_docs.py` 的 `MODULES_TO_DOCUMENT` +
  `QUICK_NAV_UTILITY` + EN/zh-CN module description; `docs/api/` +
  `docs/api.zh-CN/` 重新生成包含新的 `sse_event_schemas.md` 以及
  `enhanced_logging.md` / `mcp_tool_call_metrics.md` /
  `notification_manager.md` 三处遗留 sync (R188 / R187 / R191 新增
  helper 此前漏在 docs)。

### Tests

- **R197 / Cycle 7: latency stats invariant guard
  (`tests/test_latency_invariant_r197.py`)** — CR#19 §4.2 后续。
  `NotificationManager._send_single_notification` 在同一 `_stats_lock`
  临界区内对同一个 `latency_ms` sample 同时做两件事：
  - R142 path：`stats["latency_ms_total"] += int(latency_ms)` /
    `stats["latency_ms_count"] += 1`（毫秒整数累加）；
  - R191 path：`self._record_provider_latency_bucket(provider,
    latency_ms / 1000.0)`（秒级 float 累加进 histogram）。

  两条 path 都喂同一 sample，应保持 running totals 一致：
  `latency_ms_count == histogram[provider]["count"]` 且
  `latency_ms_total / 1000.0 ≈ histogram[provider]["sum_seconds"]`。如果
  未来 refactor 把两条 path 错开（async fan-out / 不同 lock 区 / 条件
  分支只跑一条），dashboard 上 R142 average 跟 R191 histogram-derived
  average 会出现 divergence——这种问题**不**会被现有任一单元测试
  发现，因为 R191 / R142 各自的累加逻辑测试都在自己的 scope 内。

  R197 补这条 caller-side invariant：10 cases 跨 4 个 invariant class
  （数学一致性 3 + multi-provider 隔离 2 + 源码 AST guard 3 + 边界
  0-sample / 高频累加 2）。同时把 `notification_manager.py` 第 407–410
  行 R191 时代的 stale 注释（说「桶设计跟 mcp tool 复用同一组」）
  更新为 R196 后的实际状态。

  **Test**: 全套 R197 + R191 + 既有 notification_manager 测试一起跑
  → 194/194 PASSED；ruff check + linter 无报错。

### Changed

- **`*.tmp.*` 全局忽略生效；CR / triage 归档迁移到稳定路径**（TODO.md
  line 4 收尾）— `.gitignore` 第 254 行原有的 `*.tmp.*` 通用忽略叠加
  R168/CR#10 引入的 `!docs/**/*.tmp.md` 例外，造成「docs 下 .tmp.md
  既被忽略又被强制入库」的语义重影；同时 maintainer TODO 明确「任何
  目录下的 *.tmp.* 都不应该进 git」。本次清理：
  - 把 12 个 single-cycle artefact 用 `git mv` 迁出 `.tmp.md` 名命：
    `docs/code-review-*-cr<N>.tmp.md` → `docs/code-reviews/cr<N>.md`
    （cr9 – cr19，11 个），`docs/security-triage-r72.tmp.md` →
    `docs/triage/security-r72.md`；
  - 撤回 `.gitignore` 第 261 行的 `!docs/**/*.tmp.md` 例外，让
    `*.tmp.*` 成为**无例外**铁律；
  - 同步 17 处引用：CHANGELOG.md / `docs/code-reviews/cr13-15.md` 互
    引、`docs/README.{md,zh-CN.md}` 索引、`docs/lessons-learned-
    silent-decay.md` 3 处引用、`packages/vscode/i18n.js` 注释。
  - 后续新 CR 应直接落 `docs/code-reviews/cr<N>.md`（无 `.tmp` 后
    缀），三方 triage 落 `docs/triage/<topic>-r<N>.md`。
  - 历史 R168 narrative（CHANGELOG / cr10/11/12/18 inside 段）保留
    描述 `*.tmp.md` 当时规约，不做改写——它们是项目演进史，不是 link
    target。
  - 测试覆盖：`pytest tests/test_docs_links_no_rot.py` → 6/6 PASSED
    确认 markdown 链接零腐烂；`pytest -q` 全量 → 5310 passed / 2
    skipped。

- **R196 / Cycle 6: notification-specific latency buckets (50 ms – 10 s,
  dense)** — R191 起步实现复用了
  `mcp_tool_call_metrics._DEFAULT_LATENCY_BUCKETS`
  (`0.1 / 0.5 / 1 / 5 / 30 / 120 / 300 / 600` 秒)，逻辑上同属「人机交互
  延迟」语义；但实测分布差异极大：MCP tool 调用以「人工思考 + 打字」
  主导（典型 10 – 300 秒，最长 600 秒 = `auto_resubmit_timeout` 触发
  边界），notification 发送以「网络往返 + provider 端处理」主导（典型
  50 ms – 500 ms，极端尾部 ≲ 10 秒）。共用 bucket schema 让 dashboard
  模板得跟着 `__name__` 切换 axis，CR#19 §4.1 flag 为运维认知负担。R196
  在 `NotificationManager._DEFAULT_LATENCY_BUCKETS_SECONDS` 上单独定义
  `(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)`，让
  `histogram_quantile(0.95,
  rate(aiia_notification_send_duration_seconds_bucket[5m]))` 在常见
  延迟范围内得到 < 100 ms 精度的 P95 估计。`+Inf` 仍由 snapshot helper
  动态追加，不在元组里——避免 caller 误以为 `+Inf` 是真实采样上限。

  **Test coverage** (`tests/test_notification_latency_histogram_r191.py`,
  16 cases preserved across 5 invariant classes): bucket schema 变化
  后两个测试 (`test_cumulative_buckets_increment_correctly`、
  `test_multiple_recordings_same_provider_accumulate`) 改用动态读
  `notification_manager._DEFAULT_LATENCY_BUCKETS_SECONDS` 而不是
  hardcoded constants —— invariant 是「duration d 让所有 `upper >= d`
  的桶 +1」，与具体桶值解耦。后续如再调整 bucket 分布也不必连带改
  测试。

### Added

- **R195 / Cycle 5: `POST /api/system/rotate-api-token` admin endpoint**
  — closes CR#18 §7 item 7 (the "low priority" `api_token` rotation
  follow-up). R189 introduced static `api_token` configuration; without
  R195 the only rotation path was "edit `config.toml` + restart server",
  which disrupts in-flight feedback tasks and is incompatible with
  routine 30-90 day rotation as recommended by NIST SP 800-63B.

  - **Loopback-only enforcement**: the endpoint uses
    `_is_loopback_request()` directly (not `_is_authorized()`) — token
    rotation **must** be invoked from the local machine, never via the
    existing token. Defeats "token-rotation-hijacking": an attacker
    who has captured the current token cannot use it to mint a new
    long-lived one. They must already have local-machine access, in
    which case the threat surface is much wider than a stolen API
    token alone.
  - **`secrets.token_urlsafe(32)`**: generates ~43-char URL-safe
    random tokens (192 bits of entropy, NIST SP 800-63B "high-entropy
    secret" tier; R189's 16-char minimum is the floor for human-typed
    tokens, R195's machine-generated tokens easily exceed it).
  - **Single-response disclosure**: the new token is returned in the
    response body **exactly once** — the admin must immediately record
    it to a secret manager. Subsequent `GET` endpoints continue to
    redact the field (R53-F + the `token` substring entry in the
    server-side `_SENSITIVE_KEY_SUBSTRINGS` list).
  - **Hot-reload synergy with R193**: writing the new token through
    `ConfigManager.update_network_security_config()` triggers
    `invalidate_all_caches()`, which clears `_network_security_cache`
    immediately. The very next `_is_authorized()` call uses the new
    token — old token stops working at T+0, new token starts working
    at T+0. Verified by
    `test_cache_invalidated_so_is_authorized_uses_new_token`.
  - **Rate-limit 5/hour**: admin operation, not a hot path. Defends
    against attackers who somehow get loopback (via SSRF, etc.) from
    spam-rotating to cause config-file thrashing.
  - **Fail-safe on persist failure**: if the disk write fails (disk
    full, permission error, config.toml not writable), the endpoint
    returns 500 with a message explicitly stating "old token remains
    active". The new generated token is **not** included in the 500
    response — avoiding the "token leaked but old still active"
    confusion. Local admin never gets locked out by a transient
    persist failure.

  **Response example** (success):

  ```json
  {
    "success": true,
    "api_token": "<43-char URL-safe token>",
    "token_length": 43,
    "rotated_at": "2026-05-13T14:35:22Z"
  }
  ```

  **Test coverage** (`tests/test_rotate_api_token_r195.py`, 13 cases
  across 4 invariant classes):

  - Loopback gate — 3 cases (non-loopback returns 403, **non-loopback
    + valid token still 403** (key R195 differentiator), loopback
    returns 200);
  - Token generation contract — 4 cases (response contains `api_token`,
    `len >= 32` minimum, two rotations produce different tokens,
    `rotated_at` is ISO-8601 UTC);
  - Config persistence — 3 cases (`update_network_security_config`
    called with new token, end-to-end persist read-back, cache
    invalidated so next auth uses new token);
  - Failure boundary — 3 cases (persist failure → 500, persist failure
    response does **not** contain new token, rate-limit decorator
    present at source level).

  Files touched: `src/ai_intervention_agent/web_ui_routes/system.py`
  (+`rotate_api_token` endpoint), `tests/test_rotate_api_token_r195.py`
  (new).

  Final suite: 5310 passed, 2 skipped, 620 subtests passed (no
  regressions).

- **R192 / Cycle 5: `log_level_changed` SSE event** — closes the
  "silent system-wide mutation" gap that CR#18 §4.3 flagged for R188's
  runtime log-level dial. Before R192, the only way to discover that
  someone flipped the root logger level was (a) actively poll
  `GET /api/system/log-level`, or (b) read stderr — neither workable
  for multi-operator deployments where Op-A's "I'll bump DEBUG briefly
  to repro the bug" silently lingers and Op-B sees a stderr flood
  with no context.

  R192 has the `POST /api/system/log-level` handler emit a
  `log_level_changed` event on the existing `_sse_bus` (the same bus
  that already carries `task_changed` / `config_changed`). Payload:

  ```json
  {
      "old_level": "INFO",
      "new_level": "DEBUG",
      "logger": "root",
      "changed_by": "127.0.0.1"
  }
  ```

  Subscribers (activity dashboard / PWA status bar / VS Code webview)
  can render a banner like "Log level changed to DEBUG by 127.0.0.1 at
  14:35:22". The frontend banner work is out of scope for R192 — the
  event surface lands first so PWA/dashboard PRs land on a stable
  contract.

  **Design boundary**:

  - **Fail-open**: if `_sse_bus.emit` raises (bus down, backpressure
    storm, etc.), the POST handler **still returns 200** — the log
    level was already changed; failing the response would mask a
    successful mutation as a failure, which is worse than missing a
    banner. A debug-level log line records the SSE failure for
    diagnostic context (the explicit-log body keeps the new `except`
    block out of R120 silent-failure-baseline territory).
  - **No new SSE event-type registration plumbing** — the existing
    `_sse_bus.emit(event_type, payload)` API is free-form by design;
    R192 just reuses it. SSE bus core isn't touched.
  - **PII control**: `changed_by` is the client IP (same PII tier
    as R47's SSE stats endpoint). Token strings, request bodies, and
    Authorization headers do **not** enter the payload.
  - **No emit on 400 validation failure**: a bad `level` value or
    missing field bypasses the SSE emit entirely (verified by
    `test_emit_not_called_on_400_validation_failure`). Only successful
    mutations broadcast.

  **Test coverage** (`tests/test_log_level_sse_event_r192.py`, 10
  cases across 3 invariant classes):

  - Happy path emit — 4 cases (emit called once on success, event
    type is `log_level_changed`, payload has all 4 fields, `new_level`
    matches `apply_runtime_log_level` result);
  - Fail-open — 3 cases (POST returns 200 when emit raises, log level
    actually changed despite emit failure, emit exception debug-logged
    once);
  - PII / security — 3 cases (`changed_by` is client IP, payload
    excludes submitted token string, emit not called on 400 validation
    failure).

  Files touched: `src/ai_intervention_agent/web_ui_routes/system.py`
  (+SSE emit after `apply_runtime_log_level()` success),
  `tests/test_log_level_sse_event_r192.py` (new).

  Final suite: 5297 passed, 2 skipped, 620 subtests passed (no
  regressions).

### Tests

- **R193 / Cycle 5: Hot-reload `network_security` cache invalidation
  contract locked in** — CR#18 §4.5 + §4.4(a) hypothesized a 30-second
  "token rotation overlap window" where `ConfigManager._network_security
  _cache`'s 30s TTL would let the old `api_token` keep working for up to
  30 seconds after a `config.toml` edit. Investigation showed the
  hypothesis was **wrong**:

  - `ConfigManager.reload()` already calls `invalidate_all_caches()`,
    which explicitly clears `_network_security_cache` (line 1423 of
    `config_manager.py`);
  - `FileWatcherMixin._file_watcher_loop()` polls `mtime` every 2 seconds
    (default `_file_watcher_interval`) and immediately calls
    `self.reload()` on change;
  - Real window: **≤ 2 seconds**, not 30. No overlap-style vulnerability.

  R193's work collapses to locking the implicit contract in tests so a
  future refactor that removes `invalidate_all_caches()` from `reload()`,
  or that moves `_network_security_cache` out of
  `invalidate_all_caches()`'s clearing scope, turns this 0-bug into a
  real bug *immediately* in CI rather than silently in production.

  **Test coverage** (`tests/test_hot_reload_network_security_r193.py`,
  11 cases across 3 invariant classes):

  - `invalidate_all_caches()` field coverage — 3 cases (clears
    `_network_security_cache`, resets `_network_security_cache_time`,
    clears `_section_cache`);
  - `reload()` invalidates cache — 4 cases (reload sets cache to None,
    `api_token` change takes effect, `bind_interface` change takes
    effect, **token rotation produces no overlap window**);
  - `_file_watcher_loop()` call-chain integrity — 4 cases (source-level:
    `_file_watcher_loop` calls `self.reload()`, `reload()` is called
    *before* `_trigger_config_change_callbacks()` (so callbacks see
    fresh state, not cached), `reload()` doesn't raise on valid config,
    registered callbacks fire after reload).

  No production code changed; pure verification + regression-guard.
  Closes CR#18 §4.5 + §4.4(a) follow-up items.

### Added

- **R191 / Cycle 5: `aiia_notification_send_duration_seconds`
  per-provider Histogram** — extends the foundational histogram
  exposition shipped in R190 to the notification subsystem. R142
  added `last_latency_ms` / `latency_ms_total` / `latency_ms_count`
  to per-provider stats which let operators compute **average**
  latency, but not P95 / P99 — the standard SLO percentile metrics.
  R191 closes that gap by recording cumulative bucket counts in
  parallel with the existing `latency_ms_*` fields.

  - **`NotificationManager._record_provider_latency_bucket(name,
    duration_seconds)`** — new instance method, called from the
    existing `_send_single_notification` latency block (inside the
    already-held `_stats_lock`, so no extra lock acquisition).
    Bucket definition reuses the same `(0.1, 0.5, 1.0, 5.0, 30.0,
    120.0, 300.0, 600.0)` seconds tuple as
    `mcp_tool_call_metrics._DEFAULT_LATENCY_BUCKETS` — both are
    human-in-the-loop latency, no point in two parallel dashboard
    templates for the same semantic.
  - **`NotificationManager.get_provider_latency_histograms_snapshot()`**
    — new instance method, returns a deep-copy snapshot in the same
    shape as `get_mcp_tool_call_latency_snapshot()` (`+Inf` bucket
    auto-appended, `buckets[+Inf] == count` invariant). Empty dict
    when no provider has ever sent.
  - **`_safe_notification_latency_histograms()` defensive wrapper**
    in `web_ui_routes/system.py` — mirrors the existing
    `_safe_notification_summary` / `_safe_uptime_seconds`
    "swallow-everything + return safe default" pattern. Notification
    histogram failures *cannot* trigger a 5xx on `/metrics`; the
    metric family is simply omitted while everything else keeps
    rendering.
  - **`aiia_notification_send_duration_seconds{provider}` metric**
    in `/metrics` output — uses the R190
    `_format_prom_histogram_family` helper, so HELP/TYPE de-dup
    invariants (R187 latent-bug fix) are inherited for free.

  **Operator impact**: with this change the same RED dashboard
  template that works for MCP tool latency now works for notification
  send latency. Example PromQL:

  ```promql
  # P95 send latency by provider over last 15min
  histogram_quantile(0.95, sum by (le, provider) (rate(
    aiia_notification_send_duration_seconds_bucket[15m]
  )))

  # Average send latency (still derivable from R142 fields, but now
  # we also have percentiles for SLO alerting)
  rate(aiia_notification_send_duration_seconds_sum[5m])
    / rate(aiia_notification_send_duration_seconds_count[5m])
  ```

  **Companion fix**: `tests/test_notification_manager.py::_make_manager`
  needed `_provider_latency_histograms = {}` in its bypassed-`__init__`
  stub-builder; without it, the new
  `_record_provider_latency_bucket()` call inside
  `_send_single_notification` raised `AttributeError` (silently
  swallowed by the surrounding `try/except`), which left provider
  stats dicts never updated. Surfaced by
  `test_provider_success_records_stats` /
  `test_bark_error_in_metadata` — both passing post-fix. This is
  exactly the kind of latent-bug surfacing CR#18 §3.2 highlighted
  about R186 / R187: same-commit fixes preferred over deferred
  follow-ups.

  **Test coverage** (`tests/test_notification_latency_histogram_r191.py`,
  16 cases across 4 invariant classes):

  - `_record_provider_latency_bucket` accumulator — 5 cases (single
    recording, cumulative buckets, multi-recording, multi-provider
    independence, negative duration dropped);
  - `get_provider_latency_histograms_snapshot` shape — 4 cases
    (empty, `+Inf` key present, `[+Inf] == count`, deep-copy
    independence);
  - `_safe_notification_latency_histograms` defensive — 3 cases
    (manager-works, method-raises → empty, non-dict-returned →
    empty);
  - `_render_prometheus_metrics` integration — 4 cases (no output
    when empty, output after recording, HELP/TYPE unique for multi-
    provider, graceful degradation on safe-wrapper failure).

  Files touched: `src/ai_intervention_agent/notification_manager.py`
  (+`_provider_latency_histograms`, +`_DEFAULT_LATENCY_BUCKETS_SECONDS`,
  +`_record_provider_latency_bucket`,
  +`get_provider_latency_histograms_snapshot`, wired into existing
  latency block of `_send_single_notification`),
  `src/ai_intervention_agent/web_ui_routes/system.py`
  (+`_safe_notification_latency_histograms`, integration in
  `_render_prometheus_metrics`),
  `tests/test_notification_latency_histogram_r191.py` (new),
  `tests/test_notification_manager.py` (stub-builder fix).

  Final suite: 5276 passed, 2 skipped, 620 subtests passed (no
  regressions).

- **R190 / Cycle 5 foundational: Prometheus Histogram exposition +
  `aiia_mcp_tool_call_duration_seconds`** — closes the foundational
  gap flagged in CR#18 §4.6 ("`_format_prom_metric_family` doesn't
  support histogram type"), which was blocking all latency / size /
  depth distribution metrics. CR#18 ranked this as cycle 5 #1
  priority because R191 / R192 (notification latency, queue depth
  distribution) and any future SLO dashboard work all depend on it.

  - **`_format_prom_histogram_family()` helper** (in
    `web_ui_routes/system.py`, sibling to `_format_prom_metric_family`):
    renders Prometheus 0.0.4 histogram exposition format
    (`<name>_bucket{le="…"}` cumulative rows + `<name>_sum` +
    `<name>_count`). HELP/TYPE emitted exactly once per family
    (same de-duplication invariant as R187 counter family).
    Bucket ordering: finite values ascending + `+Inf` last. Auto-
    repairs caller-side `+Inf` bucket omission (caller bug,
    permanent regression guard in
    `test_inf_bucket_auto_added_if_missing`).
  - **`aiia_mcp_tool_call_duration_seconds{tool,status}`**:
    `ToolCallCounterMiddleware.on_call_tool` now wraps `call_next`
    in `time.monotonic()` (not `time.time()` — defends against
    NTP / DST clock jumps producing negative durations). Both
    success and failure paths record latency; downstream operators
    can now distinguish "failure was slow vs failure was an instant
    reject" via `histogram_quantile(0.95, ...{status="failure"})`.
  - **Bucket selection** (chosen for human-in-the-loop semantics,
    not generic web service): `(0.1, 0.5, 1.0, 5.0, 30.0, 120.0,
    300.0, 600.0)` seconds + implicit `+Inf`. Covers "user typed
    a fast reply" (≤ 1s) → "user wrote a paragraph" (≤ 30s) →
    "long research roundtrip" (≤ 600s) → "exceeded `auto_resubmit
    _timeout`" (`+Inf`). Bucket count = 9, well below the
    Prometheus-recommended ≤ 10 ceiling per histogram family.
  - **Storage model**: no raw observations retained. Each
    `(tool_name, status)` keeps ~80 bytes of state (cumulative
    bucket counts + count + sum). Memory cost is O(distinct (tool,
    status) pairs), independent of call volume.
  - **No `prometheus_client` library dependency**: the project's
    existing `_format_prom_*` minimal renderer was extended in
    ~120 LOC rather than pulling in the ~2k LOC client library,
    which would have required solving multiprocess collector
    state-sharing (the web_ui subprocess cannot share
    `prometheus_client`'s process-level `_Counter` registry).
    The local implementation has zero such concerns.

  **Test coverage** (`tests/test_prom_histogram_r190.py`, 24
  cases across 5 invariant classes):

  - `_format_prom_histogram_family` helper — 8 cases (empty input,
    HELP/TYPE de-dup, bucket ordering, `_sum`/`_count` per
    observation, `+Inf` auto-repair, `le` label merge);
  - `ToolCallCounterMiddleware` latency recording — 4 cases
    (success, failure, multi-call accumulate, failure-with-delay
    still counted);
  - `get_mcp_tool_call_latency_snapshot` shape — 4 cases (empty,
    `+Inf` key present, `buckets[+Inf] == count` invariant, deep-
    copy independence);
  - `_record_latency` edge cases — 4 cases (negative duration
    silently dropped, zero in smallest bucket, unknown status
    accepted, large duration only `+Inf`);
  - End-to-end `/metrics` integration — 4 cases (no output when
    empty, output appears after recording, HELP/TYPE unique in
    full output, graceful degradation on snapshot failure).

  Files touched: `src/ai_intervention_agent/mcp_tool_call_metrics.py`
  (+`_DEFAULT_LATENCY_BUCKETS`, `_latency_state`, `_record_latency`,
  `get_mcp_tool_call_latency_snapshot`; `reset_mcp_tool_call_stats`
  now clears latency too; middleware writes latency on both paths),
  `src/ai_intervention_agent/web_ui_routes/system.py`
  (+`_format_prom_histogram_family`, integration in
  `_render_prometheus_metrics`), `tests/test_prom_histogram_r190.py`.

  **Operator-facing impact**: with this change, the Prometheus
  scrape now includes everything needed for a complete RED dashboard
  (Rate from R187 counter, Errors from R187 status label, Duration
  from R190 histogram). Example PromQL:

  ```promql
  # P95 latency for interactive_feedback over last 5min
  histogram_quantile(0.95, sum by (le) (rate(
    aiia_mcp_tool_call_duration_seconds_bucket{tool="interactive_feedback"}[5m]
  )))

  # Error ratio
  sum(rate(aiia_mcp_tool_calls_total{status="failure"}[5m]))
    / sum(rate(aiia_mcp_tool_calls_total[5m]))
  ```

  Final suite: 5260 passed, 2 skipped, 620 subtests passed (no
  regressions).

- **R189 / T4: Optional API token authentication (paired with non-loopback
  hardening)** — closes the "reverse proxy / LAN PWA can't reach mutation
  endpoints without disabling `access_control_enabled`" gap left by R188's
  loopback-only `POST /api/system/log-level` and the pre-existing
  loopback-only `open-config-file` POST / GET-info trio. Before R189 the
  only options for non-loopback admins were (a) tunneling via SSH /
  `kubectl port-forward`, or (b) loosening IP-level allowlists wholesale
  — neither of which constitutes *real* authentication. Now you can keep
  the IP allowlist tight **and** authenticate writes per-request with a
  Bearer token.

  - **`[network_security].api_token` config field**: empty string =
    unconfigured (legacy loopback-only behavior, zero migration risk).
    Set to a ≥ 16-char token to enable. Generate via
    `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
  - **`_is_authorized()` composite gate** (helper in
    `web_ui_routes/system.py`): replaces the previous
    `_is_loopback_request()` calls on the three mutation/info-leak
    endpoints. Returns `True` iff the caller is loopback **OR** presents
    a matching API token via `Authorization: Bearer <token>` (IETF
    RFC 6750) or `X-API-Token: <token>` (project-custom, curl/PWA
    friendly). Loopback always passes — token is an *additional* path,
    not a replacement, so local admins can never lock themselves out.
  - **Endpoints upgraded** to `_is_authorized()`:
    - `POST /api/system/open-config-file` (was loopback-only since R166)
    - `POST /api/system/log-level` (was loopback-only since R188)
    - `GET /api/system/open-config-file/info` (was loopback-only since
      R166; reveals editor availability)

  **Security boundary**:

  - **`secrets.compare_digest` constant-time comparison** — defeats
    1-byte timing side-channel attacks that could otherwise leak token
    prefix bytes (public PoC: 50-byte tokens recovered in ~600 requests
    with naive `==` comparison on slow CPUs).
  - **Authorization > X-API-Token priority** — when both headers present,
    `Authorization: Bearer` wins. Matches IETF convention and avoids
    confusion when proxies inject their own `X-API-Token`.
  - **Config-side validation**:
    - Length < 16 chars → silently dropped + warning (< 96 bits entropy
      is below NIST SP 800-63B's minimum recommendation for shared
      secrets);
    - Length > 256 chars → truncated to 256 + warning (HTTP header
      length practical limits);
    - Whitespace / control chars stripped + warning (prevents the
      common "I accidentally pasted a `\n`" footgun where
      `compare_digest` then *always* returns False).
  - **No log / response leakage** — token strings never appear in
    `logger.warning()` messages, error response bodies, or stderr.
    Wrong-token requests log only `client={ip!r}` + an opaque "denied"
    reason.
  - **R53-F boundary auto-covers `api_token`** — `ConfigManager.get_all()`
    already filters out the entire `network_security` section, so
    `api_token` *cannot* appear in `/api/system/health`, `--print-config`,
    or the activity dashboard. Belt-and-suspenders: `token` is already
    in the global `_SENSITIVE_KEY_SUBSTRINGS` redact list (`server.py`).
  - **No `api_token_strict` mode** — intentionally not implementing a
    "token-only, reject loopback" toggle. Defends against the
    "fail-closed footgun" where a typo in the token locks the local
    admin out of the very UI they need to fix the typo. If a future user
    legitimately needs strict mode, it should be an explicit opt-in
    field with a clear warning, not the default.

  **Test coverage** (`tests/test_system_api_token_r189.py`, 28 cases):

  - `_get_configured_api_token()` — 3 cases (unset/configured/raises);
  - `_extract_request_api_token()` — 5 cases (Bearer, case-insensitive
    Bearer, X-API-Token, neither, priority);
  - `_is_api_token_authorized()` — 5 cases (unconfigured, short, missing,
    mismatch, match);
  - `_is_authorized()` composite — 5 cases (4 IP × token matrix +
    loopback-with-wrong-token-still-passes invariant);
  - Config validation — 5 cases (empty, short, > 256 truncate,
    whitespace strip, non-string drop);
  - R53-F boundary — 2 cases (`get_all()` filters `network_security` +
    `token` in sensitive-key substring list);
  - End-to-end HTTP — 3 cases (non-loopback + valid → 200, +
    no-token → 403, + wrong-token → 403).

  **Docs** — `docs/configuration{,.zh-CN}.md` updated with the new
  `api_token` row in the `[network_security]` table, including the
  16-char minimum, Bearer/X-API-Token header reminder, and the "loopback
  always passes" semantic. `config.toml.default` includes an inline
  bilingual block explaining when (and why) to enable the field.

  Files touched: `src/ai_intervention_agent/web_ui_routes/system.py`
  (+ `secrets` import, +5 token-related helpers, 3 endpoint gates
  swapped), `src/ai_intervention_agent/config_modules/network_security.py`
  (validation + update-merge whitelist), `src/ai_intervention_agent/shared_types.py`
  (pydantic field), `config.toml.default` (default empty + doc block),
  `docs/configuration{,.zh-CN}.md`, `tests/test_system_api_token_r189.py`,
  `tests/test_network_security_config.py` (output-structure expects 5
  fields), `tests/test_system_log_level_runtime_r188.py` (regex now
  accepts both `_is_loopback_request()` and `_is_authorized()` gates).

- **R188 / T3: `GET/POST /api/system/log-level` runtime log-level dial** —
  closes the "have to restart server to change log verbosity" gap left
  by R93's startup-only `AI_INTERVENTION_AGENT_LOG_LEVEL` env var. Ops
  can now flip root logger level live (`DEBUG` for a one-off bug repro,
  back to `WARNING` afterwards) without losing in-flight feedback tasks.

  - **GET `/api/system/log-level`**: any-source, rate-limit 60/min,
    returns `{root_level, aiia_level, valid_levels}` with all level
    fields as strings (no `logging.getLevelName` reverse-lookup needed
    by clients). Lets dashboards / VS Code status panel show the dial
    state without scraping logs.
  - **POST `/api/system/log-level`**: loopback-only (`127.0.0.1` / `::1`),
    rate-limit 30/min, accepts `{"level": "DEBUG|INFO|WARNING|ERROR|CRITICAL"}`
    (case-insensitive). Returns `{success, old_level, new_level, logger}`.

  **Security boundary** (same tier as `open-config-file`):
  - Loopback-only on the mutating verb — no remote-via-Web-UI log-bomb
    attacks; LAN PWA users can still query via GET because the GET
    payload contains zero PII.
  - **Five-enum allow-list** — does not accept arbitrary `logger_name`
    parameters; attackers can't dial `zeroconf` / `httpx` / Flask
    sub-loggers to `DEBUG` to flood stderr and exhaust disk.
  - **No persistence** — runtime override never writes to `config.toml`
    nor env vars; restart restores config-controlled initial level.
    Intentional — runtime dials should not silently override config.
  - **Atomic validation** — `apply_runtime_log_level()` validates the
    enum value before calling `setLevel()`, so a bad request never
    leaves the logger in a partially-changed state.

  **New helpers in `enhanced_logging.py`**:
  - `get_current_log_level() -> dict[str, str]`: snapshot returning
    `{root_level, aiia_level, valid_levels}`.
  - `apply_runtime_log_level(level: str) -> dict[str, str]`: mutates
    root logger + all handlers, returns `{old_level, new_level, logger}`.

  **Test coverage**: `tests/test_system_log_level_runtime_r188.py`
  (21 cases) — `get_current_log_level` shape (three required fields,
  string types, all 5 enums present), `apply_runtime_log_level` behaviour
  (uppercase / case-insensitive / invalid raises / non-string raises /
  return shape / immediate effect on root logger), GET endpoint
  contract (any-source 200, payload shape, no body required), POST
  endpoint contract (loopback 200 + immediate effect, non-loopback 403,
  missing level 400, non-string level 400, invalid enum 400 with valid
  hint), source-level regressions (`_is_loopback_request()` present on
  POST, rate-limit decorators on both methods, R188/T3 docstring marker).

  Also updates `tests/test_runtime_counters_r47.py::test_route_does_not_gate_on_loopback`
  so the `sse-stats` end-marker now points at `/api/system/health`
  (its immediate next neighbour); the previous `open-config-file/info`
  marker spanned multiple newly-inserted endpoints that legitimately
  call `_is_loopback_request()`.

- **R187 / T2: MCP tool call counter middleware** — adds the missing
  positive-side counterpart to R37's `get_mcp_error_stats()` (which only
  exposes negative `{error_type}:{method}` counts). The new
  `ToolCallCounterMiddleware` (registered at `mcp.middleware` position 2,
  after `ErrorHandling` + `RateLimiting`, before `DereferenceRefs` /
  `Timing` / `Logging`) tracks `{tool_name, status: success|failure}`
  per call and exposes the data through `get_mcp_tool_call_stats()` /
  `reset_mcp_tool_call_stats()`. The R186 / T1 Prometheus endpoint now
  emits the new `aiia_mcp_tool_calls_total{tool=...,status=success|failure}`
  counter so monitoring dashboards can compute SLO success ratios
  (`success / (success + failure)`) and cross-reference them with
  R37's error-type breakdown for two-dimensional drill-down.

  **Design points**:
  - **Module isolation** — lives in a new `src/ai_intervention_agent/mcp_tool_call_metrics.py`
    (~150 LoC); `server.py` only imports the middleware class + re-exports
    `get_mcp_tool_call_stats`. Keeps server.py from creeping toward 1700+
    LoC and makes the counter directly importable from
    `web_ui_routes/system.py`'s prom renderer without circular import.
  - **Thread safety** — module-level `Counter` + `threading.Lock` for the
    streamable-http future and concurrent prom-render-vs-tool-call paths.
  - **Re-raise on failure** — middleware bumps the `failure` counter then
    re-raises so the outer `ErrorHandlingMiddleware` can still translate
    business exceptions to standard MCP error codes; the counter is not
    a swallow-and-hide replacement for proper error propagation.
  - **PII boundary** — counter keys are tool names (public metadata),
    never argument values; `get_mcp_tool_call_stats()` returns deep
    copies so callers cannot pollute internal state.

  **R186 follow-up bug fix bundled in this commit**: the original
  `_render_prometheus_metrics()` emitted per-sample `# HELP` + `# TYPE`
  lines for `aiia_notification_*` per-provider metrics — strict
  Prometheus parsers (VictoriaMetrics / Cortex / latest prom) reject
  this with "second TYPE for metric". Introduced a new helper
  `_format_prom_metric_family(name, *, help_text, metric_type, samples)`
  that emits a single HELP/TYPE block + N value rows. Both
  notification per-provider and the new MCP tool counter now go
  through this helper, with regression guarded by
  `tests/test_mcp_tool_call_metrics_r187.py::TestPromOutputNoDuplicateHelpType`
  (5 cases, including "every metric name's HELP/TYPE appears exactly
  once across the full payload").

  **Test coverage**: `tests/test_mcp_tool_call_metrics_r187.py`
  (17 cases) — counter behaviour (initial empty, success/failure
  increments, multi-tool isolation, reset, returned-dict-is-copy),
  middleware behaviour (success-path success counter, exception-path
  failure counter + re-raise, server.py registration at position 2),
  `_format_prom_metric_family` helper (empty / single / multi-sample,
  label escaping), and the no-duplicate-HELP/TYPE invariant.

  **Docs sync**: `scripts/generate_docs.py` registers
  `mcp_tool_call_metrics.py` in `MODULES_TO_DOCUMENT` + `QUICK_NAV_UTILITY`,
  plus a one-line bilingual entry in the Quick navigation index.
  `docs/api/mcp_tool_call_metrics.md` (en signature-only) +
  `docs/api.zh-CN/mcp_tool_call_metrics.md` (zh-CN with docstring) are
  auto-generated.

- **R186 / T1: `GET /api/system/metrics` Prometheus exposition endpoint** —
  closes the "JSON dashboard ↔ Prometheus scrape" gap left after R132
  (the `/api/system/health` JSON endpoint). Same data sources
  (`_safe_uptime_seconds` / `_safe_build_info` / `_sse_bus.stats_snapshot` /
  notification summary / TaskQueue / recent ERROR log count), but rendered
  in **Prometheus 0.0.4 exposition format** so monitoring stacks
  (Prometheus / Grafana Agent / VictoriaMetrics / Datadog OpenMetrics) can
  scrape directly without a sidecar exporter. Wire it up with a single
  `scrape_configs` entry: `metrics_path: /api/system/metrics`.

  **Metric inventory** (all `aiia_*` prefixed for namespace isolation,
  counters carry `_total` suffix per OpenMetrics convention):
  - Process: `aiia_uptime_seconds`, `aiia_build_info{version,git_*}`
  - SSE bus: `aiia_sse_emit_total`, `aiia_sse_gap_warnings_total`,
    `aiia_sse_backpressure_discards_total`, `aiia_sse_heartbeat_total`,
    `aiia_sse_oversize_drops_total`, `aiia_sse_subscriber_count`,
    `aiia_sse_history_size`, `aiia_sse_latest_event_id`,
    `aiia_sse_emit_to_deliver_ms{quantile=0.5|0.95}` (R134 latency snapshot)
  - TaskQueue: `aiia_task_queue_size`, `aiia_task_queue_max`
  - Errors: `aiia_recent_errors_5min` (rolling 5-min ERROR/CRITICAL count)
  - Notification: `aiia_notification_enabled`, `aiia_notification_queue_size`,
    `aiia_notification_delivery_success_rate`, `aiia_notification_events_*`,
    plus per-provider `aiia_notification_{attempts,success,failure}_total{provider}`
    + `success_rate` / `avg_latency_ms` / `success_streak` / `failure_streak`
    (R142/R143/R145 per-provider stats projected to Prometheus labels)

  **Design constraints**:
  - **Zero new deps** — hand-written 0.0.4 exposition format (avoids the
    4 MB+ `prometheus_client` wheel + multiprocess registry complexity
    we don't need)
  - **PII boundary** — same as `/api/system/health`: only numeric / enum /
    path values; never `bark_device_key` / `api_key` / `token` / `password` /
    `last_error` raw text. Enforced by `tests/test_system_metrics_prometheus_r186.py::test_payload_does_not_leak_pii_keys`
  - **Graceful degradation** — any subsystem probe failure (SSE / Notification /
    TaskQueue / recent-logs) drops the affected metric lines but keeps the
    endpoint 200, so a Prometheus target stays "up" with metric staleness
    rather than flipping to "red" on a transient internal error
  - **Rate limit 120/min** — matches `/api/system/health`, covers Prometheus
    default 15 s scrape interval + multi-replica headroom

  **Test coverage**: `tests/test_system_metrics_prometheus_r186.py` (29 cases) —
  Prometheus format helpers (escape backslash/quote/newline, label dict
  rendering, HELP/TYPE/value three-line shape, int / float / `+Inf` / `-Inf` /
  `NaN` special values), full-payload behaviour (non-empty by default,
  `aiia_` namespace consistency, HELP↔TYPE pairing, subsystem-failure
  resilience, PII keyword absence), HTTP endpoint contract (200,
  `text/plain; version=0.0.4`, no JSON envelope), and source-level
  regressions (R186/T1 docstring marker, no `prometheus_client` import,
  `120 per minute` rate-limit decorator).

  Also surfaces and fixes a latent bug in the original
  `_render_prometheus_metrics`: the notification subsystem block lacked
  the `try/except` wrapper that every other subsystem block had, so
  `notification_manager` raising would have 5xx'd the whole `/metrics`
  endpoint (regression-guarded by
  `test_render_does_not_explode_when_subsystem_fails`).

  Two new `except Exception: pass` sites (TaskQueue + recent-logs blocks)
  are added to the R120 silent-failure baseline (`tests/data/silent_failure_baseline_r120.json`,
  29 → 31 sites) with explicit `[R-186]` markers per R120 doctrine.

### Fixed

- **R186 follow-up: `*.tmp.*` gitignore hardening** — broaden the
  `*.tmp.md`-only ignore rule to `*.tmp.*` so any temp suffix
  (`.tmp.py`, `.tmp.json`, `.tmp.yaml`, etc.) is automatically excluded
  from accidental `git add`. The existing R168/CR#10 `!docs/**/*.tmp.md`
  exception is preserved so `docs/code-review-*.tmp.md` /
  `docs/security-triage-*.tmp.md` single-cycle archives still flow
  through code review. Note: the exception is intentionally scoped to
  `.tmp.md` only — `*.tmp.py` and other suffixes under `docs/` stay
  ignored, blocking accidental commits of temporary scripts or data
  files even when authored there.

## [1.7.0] — 2026-05-13

> 🎯 **Headline release: the observability triangle is closed.** This
> minor bump consolidates 15 commits (CR#15 + CR#16 + CR#17) of v1.6.4
> follow-up work into a single coherent public-surface expansion. The
> theme: **answer the user's actual question** ("why is my port 8181
> instead of 8080?") at every entry-point.
>
> **Three env vars + three CLI flags + one health field + four
> release-check flags**, all landing on a default behaviour identical
> to v1.6.4 — every new surface is opt-in or additive.
>
> 1. **Env-var overrides** (`AI_INTERVENTION_AGENT_WEB_UI_{HOST,PORT,LANGUAGE}`)
>    let `uvx` / Docker / systemd users bypass `config.toml` for the
>    same `web_ui.*` fields without bind-mounting or building images.
>    Out-of-range values WARN + fall back instead of crashing startup.
> 2. **CLI introspection** (`--version` / `--help` / `--print-config`)
>    transforms `ai-intervention-agent` from a "stdio-only black box"
>    into a standard PyPI tool that matches `pip` / `ruff` / `uv`
>    UX conventions. `--print-config` dumps the *effective merged*
>    config as JSON to stdout, with automatic secret-redaction of
>    `bark_device_key` / `api_key` / `token` / `password` / etc. so
>    the output is safe to paste in bug reports.
> 3. **Health-endpoint field** (`/api/system/health.web_ui_env_overrides`)
>    exposes the same env-override picture to monitoring dashboards
>    and `curl | jq` debugging, completing the env→CLI→health
>    observability triangle.
> 4. **R185 Dependabot CVE gate** (`check_tag_push_safety.py
>    --check-cve`) is an opt-in pre-tag block on open
>    high/critical CVEs sourced from the repo's Dependabot alerts.
>    Default behaviour is unchanged (gate off), opt in via
>    `make release-check-cve`.
>
> Plus a security hardening pass: `bark_device_key` would have leaked
> through the new `--print-config` output if not for an inline
> recursive secret-redaction walker discovered during F-1 dry-run
> (never made it to a release). Non-loopback deployments get a
> three-layer hardening recipe in `.github/SECURITY.{md,zh-CN.md}`.
>
> Governance bonus: `check_changelog_diff_scope.py` is now a
> pre-commit hook, blocking >100-line changes to non-`[Unreleased]`
> CHANGELOG regions inside feature commits (motivated by R185 in
> v1.6.4 conflating 645 lines of markdownlint normalization with the
> actual CVE-gate diff).
>
> **Migration**: zero required. No flags or env vars change behaviour
> by default. Recommended: try `ai-intervention-agent --print-config |
> jq` after upgrading to inspect what's actually loaded.
>
> Detailed CR archive: [`docs/code-reviews/cr15.md`](docs/code-reviews/cr15.md),
> [`docs/code-reviews/cr16.md`](docs/code-reviews/cr16.md),
> [`docs/code-reviews/cr17.md`](docs/code-reviews/cr17.md).

### Added

- **CLI `--print-config` flag** — dumps the *effective merged* config
  (post-`config.toml` + env-override resolution) as JSON to stdout,
  then exits 0. Closes the introspection loop opened by the new
  `web_ui_env_overrides` health field: monitoring dashboards and CLI
  users now see the same three top-level fields
  (`config_file_path`, `web_ui` with resolved host/port/language,
  `env_overrides`). Output is `jq`-friendly so debugging
  *"why is my port 8181 instead of 8080?"* becomes a one-liner:
  `ai-intervention-agent --print-config | jq .env_overrides`. The
  `network_security` section is filtered out at the
  `ConfigManager.get_all()` boundary (R53-F trust level — same as
  `/api/system/health`), so secrets/tokens never leak even if added
  later. Failure modes return exit 1 with a JSON `{"error": ...}`
  payload so shell pipelines can branch on the result. Wired through
  `main()` via a `sys.exit(_print_effective_config())` short-circuit
  *before* the MCP stdio loop, mirroring `--version`'s exit pattern.
  Test coverage: `tests/test_server_print_config.py` adds 11 cases
  (argparse registration, `main()` clean-exit + no stdio invocation,
  JSON shape: top-level keys / web_ui resolved fields / `env_overrides`
  dict type, env-override reflection: empty state / port env →
  `web_ui.port=int(value)` parity, language env → resolved
  `web_ui.language`, network_security filtering, failure-mode JSON
  envelope). README (en + zh) and `docs/configuration.{md,zh-CN.md}`
  document the new flag side-by-side with the equivalent `curl
  /api/system/health | jq` invocation, so the two surfaces stay
  intentionally redundant.

- **R185 docs sync** — every entry point that mentions
  `check_tag_push_safety.py` now also documents the new `--check-cve`
  gate so the feature isn't orphaned. (1) `Makefile` gains a
  `release-check-cve` convenience target (column-aligned in `make
  help`); (2) `scripts/README.md` updates the
  `check_tag_push_safety.py` index entry with the full R185 flag
  surface (`--check-cve`, `--cve-severity`, `--allow-cve`) and its
  graceful-degradation contract; (3) bilingual
  `docs/release-recovery.{md,zh-CN.md}` both call out the new flag
  + `release-check-cve` shortcut in their recovery playbook (step 5)
  and reference list. Guarded by `tests/test_r185_docs_sync.py` (8
  cases): `.PHONY` declaration, target body wiring, `make help`
  visibility, `scripts/README.md` mentions `R185` + `--check-cve`,
  English/Chinese release-recovery parity. Future renames /
  removals of any of these three entry points will fail
  `pytest` so the "code exists but docs don't mention it" failure
  mode is eliminated.

- **R185 · `check_tag_push_safety.py --check-cve` Dependabot CVE gate** —
  `scripts/check_tag_push_safety.py` learns an **opt-in** pre-tag CVE
  gate that blocks `make release-check` when the repository has ≥ 1
  open Dependabot alert at `critical` or `high` severity. Three new
  CLI flags: (1) `--check-cve` / `--no-check-cve`
  (`argparse.BooleanOptionalAction`, default `OFF` — adding the gate
  to a release pipeline is opt-in so existing `make release-check`
  callers are byte-identical), (2) `--cve-severity {critical,high,
  medium,low}` (`action="append"`, defaults to `{critical, high}` per
  OWASP/NIST "patch immediately" guidance; `medium`/`low` left out
  because R184 showed upstream-no-patch long tails would block
  legitimate releases), (3) `--allow-cve` (emergency bypass that
  emits a `WARNING (R185)` to stderr and recommends recording the
  bypass rationale in the commit message). Implementation: parses
  `git remote get-url origin` into `(owner, repo)` supporting both
  SSH (`git@github.com:OWNER/REPO.git`) and HTTPS
  (`https://github.com/OWNER/REPO[.git]`) forms; queries
  `gh api repos/{owner}/{repo}/dependabot/alerts?state=open`; renders
  each blocker as `#NUM [severity] package: GHSA — summary` plus a
  three-line remediation block (`uv lock --upgrade-package`, `uv sync
  --dev`, `uv run pytest -W error -q`). Failure modes are
  conservatively non-blocking: missing `gh` CLI, `gh` not logged in,
  Dependabot disabled on the repo, non-GitHub remotes, malformed
  JSON, and unknown alert states all log an explanation and pass
  (rationale: a hard requirement on `gh auth login` for every
  contributor would be a CI/UX regression versus the pre-R185
  baseline). Test coverage: 32 cases in
  `tests/test_check_tag_push_safety_cve_gate_r185.py` covering the
  remote-URL parser (SSH/HTTPS variants, malformed inputs, `.git`
  suffix optionality), `gh` availability detection, alert filtering
  by severity allowlist, alert-state filtering (`open` vs
  `auto_dismissed`/`fixed`/`dismissed`), graceful degradation
  (network failure, `gh` missing, non-GitHub remote, JSON parse
  errors), CLI flag wiring (`--check-cve` default off, custom
  `--cve-severity` filter, `--allow-cve` bypass exit-code semantics),
  and end-to-end `main()` integration with mocked subprocess.

- **`/api/system/health` exposes `web_ui_env_overrides` field** — completes
  the loop opened in CR#15 by giving K8s probes / monitoring dashboards
  / `curl health | jq` a single-source-of-truth answer to *"is this
  process running with `AI_INTERVENTION_AGENT_WEB_UI_*` env overrides?"*
  Field semantics: `{}` = no env override (values come from
  `config.toml`/defaults), `{env_name: value, ...}` = active overrides
  (plaintext values — host/port/language are non-sensitive, same trust
  level as the existing `config_file_path` field), `null` = probe
  failure. The helper `_safe_web_ui_env_overrides()` enforces a strict
  3-name whitelist (`HOST` / `PORT` / `LANGUAGE`), so adding future env
  overrides will not silently widen this surface to secrets/tokens. Test
  coverage: `tests/test_health_env_overrides.py` adds 11 cases (empty
  state, whitespace handling, hit reflection, whitespace trimming,
  whitelist enforcement against unrelated `AI_INTERVENTION_AGENT_*`
  vars, key-name parity with `service_manager` constants, source-level
  `try/except` guard, runtime `os.environ` failure handling, payload
  field presence, helper wiring). `tests/test_web_ui_routes_system.py`
  also gains a payload-schema invariant: the new field is added to the
  allowed top-level key whitelist plus a dedicated type assertion (dict
  with whitelisted env-var keys → string values, or `None`). Field is
  documented in the `/api/system/health` Swagger docstring alongside
  `config_file_path` / `build`.

### Added

- **CR#16 F-1 + F-3 + secret-redaction · `--print-config` polish** —
  the CLI dump introduced in `cf2555c` learns three new behaviours:
  (1) **F-1 sections coverage**: a new top-level `sections` field
  dumps **all** non-sensitive config sections (`web_ui` / `mdns` /
  `feedback` / `notification`) so users can debug *"why doesn't
  mDNS work"* / *"which notification backend is enabled"* without
  poking at the TOML file; (2) **F-3 `using_defaults` flag**: a
  bool top-level field that's `true` when `ConfigManager` is
  running on the bundled default `config.toml` (typical *"fresh
  install, no user config yet"* state), `false` when a user-owned
  config is loaded. Helps fresh contributors realize they're seeing
  defaults rather than their own values. (3) **Secret redaction**:
  during F-1 implementation I found that `notification.bark_device_key`
  was about to be dumped in plaintext — never made it to a release
  but landed inline a `_redact_sensitive()` walker that recursively
  matches dict keys against a whitelist of secret-name substrings
  (`*_device_key`, `*_token`, `*_secret`, `password`, `*_api_key`,
  `webhook_url`, etc., normalized to lowercase + stripped `_-` so
  `BarkDeviceKey`/`bark-device-key`/`bark_device_key` all match)
  and replaces values with `***REDACTED***`. This walker is now the
  data sanitizer for `--print-config` and is unit-tested
  independently so future fields like
  `notification.slack_webhook_url` are protected by default.
  Top-level `web_ui` field is preserved for backward compatibility
  (existing `jq .web_ui.port` pipelines stay valid).
  Test coverage: `tests/test_server_print_config.py` gains 12 new
  cases (3 for sections coverage / network_security filter /
  using_defaults bool, 8 for the redact helpers covering pattern
  detection / case-insensitivity / non-sensitive passthrough /
  recursive dict + list walking / input non-mutation / atomic
  preservation, 1 end-to-end regression for the bark_device_key
  redaction). Bilingual READMEs updated.

### Documentation

- **Code Review #17 archived** —
  [`docs/code-reviews/cr17.md`](docs/code-reviews/cr17.md)
  captures cycle-3 of the v1.6.4 follow-up chain: 5 commits
  (`d1f2ee9` → `981117b`, +1317 lines net) that **fully drained**
  the CR#16 §6 follow-up queue (F-1 sections coverage, F-2 R185
  rate-limit guard tests, F-3 `using_defaults` flag, F-4 CHANGELOG
  diff-scope governance hook, F-5 public invalidate helper) **plus**
  an unplanned secret-redaction walker discovered during F-1 dry-run
  that would have leaked `bark_device_key` to stdout. Final suite
  **5141 passed, 2 skipped, 620 subtests** in 137.96s (was 5107
  pre-cycle, +34 new tests). 5 cycle-4 follow-ups enumerated
  (F-1' alphabetical sort for `sections`, F-2' R185 test name
  canonicalization, F-3' `importlib.resources`-based default
  detection, F-4' adversarial CHANGELOG parser tests, F-5'
  async-aware docstring) totalling ~2h estimated work, none urgent.
  Versioning recommendation reinforced: cut **`v1.7.0`** once cycle-3
  changes are reviewed — cumulative public-surface across CR#15 +
  CR#16 + CR#17 (3 env vars, 3 CLI flags, 1 health-field, 4
  release-check flags, sections/using_defaults output expansion,
  redaction primitive, governance hook) is clearly MINOR by SemVer.
  Archive the `.tmp.md` file at v1.7.0 cut, mirroring CR#15 /
  CR#16 archival pattern.

### Tests

- **CR#16 F-4 · `check_changelog_diff_scope.py` pre-commit governance** —
  new local `pre-commit` hook + standalone script that fails the
  commit if `CHANGELOG.md` accumulates > 100 lines of changes outside
  the `[Unreleased]` section. Motivation: CR#16 caught
  `a37e17d` rolling 645 lines of `*` → `-` markdownlint
  normalization of historical release regions into a feature commit,
  making the actual R185 diff hard to spot in review. The hook
  parses `git diff --cached --unified=0`, walks `## [Unreleased]` /
  `## [vX.Y.Z]` headers in the staged file, classifies each `+`/`-`
  line by section, and only counts hits outside `unreleased`. CHANGELOG.md
  not staged → short-circuit exit 0 (zero-cost no-op). Includes
  `--threshold N` for projects that prefer a different limit,
  `--allow-massive-changelog-rewrite` for intentional history-cleanup
  commits (still emits stderr WARNING so reviewers see the bypass),
  and rejects negative thresholds with exit 2. Test coverage:
  `tests/test_check_changelog_diff_scope.py` adds 13 cases
  (section parsing, line classification, line-counting semantics,
  CLI flow: short-circuit / under-threshold / above-threshold-fails /
  emergency-override / negative-threshold rejection). The new hook
  registered in `.pre-commit-config.yaml` so every future
  `CHANGELOG.md` commit goes through the guard automatically.

- **CR#16 F-2 · R185 `gh api` rate-limit + auth-failure explicit guard** —
  `tests/test_check_tag_push_safety_cve_gate_r185.py` gains two
  documentation-quality test cases that prove rate-limit
  (`HTTP 403: API rate limit exceeded`) and unauthorized
  (`gh auth login required`) outcomes both flow through the same
  `CalledProcessError → return None` path as other gh failures.
  Behavior was already correct, but no test pinned the contract;
  future "let's special-case rate-limit retry" refactors will now
  fail-fast with a clear test name pointing at the failure mode
  description. Total R185 test count: 32 → 34.

- **CR#16 F-5 · public `invalidate_web_ui_config_cache()` helper** —
  `service_manager` gains a public, no-arg, no-return-value helper
  that clears just the `get_web_ui_config()` TTL cache. Tests
  (especially `tests/test_server_print_config.py::
  TestPrintConfigReflectsEnvOverrides`) previously reached into the
  `_config_cache` private dict to do this; future shape changes
  would have silently broken them. The new helper is intentionally
  narrower than `_invalidate_runtime_caches_on_config_change`
  (which also resets http clients and bumps the cache generation
  counter) and is verified by `tests/test_service_manager_cache_
  helpers.py` (8 cases): public-API contract (no underscore prefix,
  no args, returns None), behaviour (clears `config` / `timestamp`
  fields, does not bump `_config_cache_generation`), and AST-based
  side-effect scope check (helper source references neither
  `_sync_client`/`_async_client`/`_config_cache_generation` — the
  test parses ast.Name nodes to ignore docstring string mentions).

### Security

- **Hardening guidance for non-loopback deployments** — discovered during
  the CR#16 F-1 implementation review that endpoints like
  `/api/get-notification-config` round-trip raw `bark_device_key` /
  saved-prompt content to the HTTP boundary so the built-in Settings
  panel can edit existing values. Default deployment is loopback-only so
  this isn't a leak, but anyone setting
  `AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0` for SSH-remote / LAN access
  needs to compensate elsewhere. Three-layer hardening recipe added to
  `.github/SECURITY.{md,zh-CN.md}` and `docs/configuration.{md,zh-CN.md}`:
  (1) tighten `network_security.allowed_networks` to a minimal CIDR
  (still loopback-only by default — env-host does **not** override it),
  (2) prefer `ssh -L` tunnels over `0.0.0.0` binds, (3) use the CLI
  `--print-config` (which auto-redacts) for ad-hoc inspection instead of
  the HTTP API. Also documents the explicit design decision: API-boundary
  redaction is intentionally not enabled because it would break the
  round-trip Settings flow — opens an "open discussion before adding
  per-endpoint redaction" line so users with kiosk-style deployments can
  request the stricter mode without breaking existing flows.

### Documentation

- **Code Review #16 archived** —
  [`docs/code-reviews/cr16.md`](docs/code-reviews/cr16.md)
  captures the cycle-2 review covering 5 commits (`36cdc72` →
  `246accc`): the env-override → CLI → health-endpoint observability
  triangle closure, R185 (Dependabot CVE gate) landing + bilingual
  docs sync, `--print-config` introduction, and a same-cycle hotfix
  restoring R120 baseline. 5 follow-ups identified (F-1
  `--print-config` covering all non-sensitive sections, F-2 R185
  rate-limit test documentation, F-3 `using_defaults` flag, F-4
  pre-commit governance for CHANGELOG diff size, F-5 public
  `invalidate_web_ui_config_cache()` helper). Versioning
  recommendation: bump to **v1.7.0** to signal that env-vars + CLI
  flags + health-endpoint field constitute a coherent public
  surface expansion.

### Tests

- **Console-script entry-point wiring guard** — `pyproject.toml
  [project.scripts] ai-intervention-agent = ":_cli_main"` is now
  asserted in unit tests via `importlib.metadata.entry_points`. A
  single typo there (e.g. reverting back to `:main`) would silently
  re-introduce the "`ai-intervention-agent --version` hangs on stdio"
  bug without breaking any existing test (they all import
  `server.main` / `server._cli_main` directly and skip wheel
  metadata). Two new cases in
  `tests/test_server_cli_argparse.py::TestConsoleScriptEntryPointWiring`
  cover (1) the entry-point string points to `_cli_main`, and (2) it
  resolves to a callable. CR#15 F-3 recommendation, landed in the
  same cycle.

### Documentation

- **Code Review #15 archived** —
  [`docs/code-reviews/cr15.md`](docs/code-reviews/cr15.md)
  reviews the 5-commit user-onboarding loop cycle on top of v1.6.4.
  Covers the three-commit env-override → CLI → friendly-error UX
  story, the backward-compat redesign that prevented 6 regression
  failures in `218b72f`, bilingual doc lockstep, and 5 follow-up
  proposals (F-1..F-5) with one (F-3 entry-point guard) implemented
  in the same cycle.

- **README surfaces the new env override + CLI inspection paths** —
  added a "Quick overrides (no file edits required)" subsection under
  Configuration with a copy-pasteable `export AI_INTERVENTION_AGENT_WEB_UI_*`
  block plus a typo-recovery note, and a "CLI inspection" subsection
  showing `--version` / `--help`. Without this, the two recent features
  (`web_ui` env overrides + CLI argparse) were invisible to anyone
  reading the README — only `docs/configuration.md` had the full
  surface. Bilingual: same structure in `README.zh-CN.md`. No
  functional code changes.

### Added

- **Environment-variable overrides for Web UI bootstrap** —
  `AI_INTERVENTION_AGENT_WEB_UI_HOST` / `_PORT` / `_LANGUAGE` now override
  `config.toml`'s `web_ui.host` / `web_ui.port` / `web_ui.language` at
  process startup, applied inside `get_web_ui_config()` and cached for the
  existing 10-second TTL. Targets the "I can't easily edit `config.toml`
  here" runtimes — `uvx`, Docker, systemd unit drop-ins, SSH-remote sessions
  — and mirrors what competitor MCP servers (`mcp-feedback-enhanced`)
  expose via `MCP_WEB_HOST` / `MCP_WEB_PORT` / `MCP_LANGUAGE`, but reuses
  this project's existing `AI_INTERVENTION_AGENT_*` prefix
  (consistent with `AI_INTERVENTION_AGENT_CONFIG_FILE` and
  `AI_INTERVENTION_AGENT_LOG_LEVEL`). Port range is `[1, 65535]`; out-of-range
  / non-numeric values log a `WARNING` and fall back to `config.toml` so a
  shell-profile typo never blocks server startup. New 20-case unit suite
  (`tests/test_service_manager_env_override.py`) covers the
  `_coerce_env_str` / `_coerce_env_int` helpers (5 + 6 cases) plus 9
  end-to-end `get_web_ui_config()` paths: unset / valid / invalid / out-of-range
  / empty / combined / info-log assertions. Docs cross-linked in
  [`docs/configuration.{md,zh-CN.md}`](docs/configuration.md#environment-variable-overrides)
  with an SSH-remote bind example.

- **CLI `--version` / `--help` support** — `ai-intervention-agent
  --version` (or `-V`) now prints `ai-intervention-agent <version>` and
  exits `0`; `--help` / `-h` shows usage + an epilog pointing at config
  surfaces. Before this change, any unrecognised flag would be silently
  ignored and the binary would fall straight into the MCP stdio loop,
  hanging on `stdin` until the user noticed and `Ctrl+C`-ed — the same
  PyPI footgun that `pip`, `ruff`, `uv`, and `black` all guard against
  with their first-line `--version` flag. New `_cli_main()` console-script
  entry point reads `sys.argv[1:]` and forwards to `main(argv)`; `main()`
  itself keeps its zero-argument contract (= jump to stdio loop) so the
  ~5000 existing tests that call `main()` without args continue to pass.
  New 20-case unit suite (`tests/test_server_cli_argparse.py`) guards
  four invariants: (1) `--version` / `-V` exit 0 + print to stdout;
  (2) `--help` / `-h` exit 0 + show usage; (3) unknown flag → exit 2 +
  error on stderr; (4) `main(None)` *must* skip argparse so pytest's own
  `sys.argv` doesn't trip up the entire test suite. `pyproject.toml`
  `[project.scripts]` flipped from `:main` to `:_cli_main`.

### Changed

- **`port_in_use` error message inlines actionable fixes** — the
  `ServiceUnavailableError(code="port_in_use")` raised by
  `start_web_service()` used to read "请检查是否有其他进程占用该端口，或
  在配置中改用其他端口" — accurate but inactionable; the user had to go
  read `docs/troubleshooting.md#1` to learn the recovery commands. The
  message now inlines three executable paths: (1) `export
  AI_INTERVENTION_AGENT_WEB_UI_PORT=<new>` (the new env override path,
  zero file edits), (2) edit `config.toml [web_ui] port=<new>`, (3)
  `lsof -nP -iTCP:<port> -sTCP:LISTEN` to discover the squatter, plus a
  link to the doc for the deep dive. Error `code` is unchanged
  (`port_in_use`) so the existing VS Code extension precise-text path
  and any monitoring / log alerts that match on code keep working.
  `docs/troubleshooting.{md,zh-CN.md}` Issue #1 ("Web UI does not start
  / port already in use") rewritten in matching three-option layout
  (env override → config.toml → `pkill` / `lsof`) so doc and runtime
  message stay in lockstep. New 9-case unit suite
  (`tests/test_port_in_use_friendly_message.py`) guards: error code
  stays `port_in_use`, host:port still present (legacy contract from
  `test_server_functions::test_port_in_use_message_mentions_host_and_port`),
  message contains env-override hint, contains `config.toml` hint,
  contains `lsof` hint with the actual port (not a hard-coded `8080`),
  links to `docs/troubleshooting.md`, message is single-string (no
  newlines so loggers / Sentry render compactly), and works for IPv6
  hosts (`::`). Total 12 cases when combined with the 3 historical
  `TestStartWebServicePortInUse` cases.

## [1.6.4] — 2026-05-12

> Security + release-lifecycle hardening patch on top of v1.6.3.
> Headline content (sorted by user impact):
>
> - **Security** — R184 clears 5 Dependabot-reported CVEs (1 high,
>   4 medium) by bumping `pytest 8.4.0 → 9.0.3` (GHSA-6w46-j5rx-g56g
>   tmpdir hardening) and `mistune 3.2.0 → 3.2.1` (4 advisories:
>   ReDoS in `LINK_TITLE_RE`, Heading ID XSS, figure XSS, math
>   plugin XSS). Exploit path is zero in our setup (mistune is a
>   transitive flasgger dep that only renders our own docstrings,
>   pytest is dev-only), but every flagged advisory is now out of
>   range. Also enables repo-level `automated-security-fixes` so
>   future CVE disclosures land as auto-PRs.
> - **Release lifecycle resilience** — R180 + R181 (already
>   covered in the v1.6.3 rescue story) are now formally
>   captured in `docs/release-recovery.{md,zh-CN.md}` — a
>   bilingual playbook for the 3 `release.yml` failure
>   patterns, with a "Security release shortcut" runbook that
>   condenses this R184 cycle into 4 commands. R182 wires the
>   playbook into all four primary docs indexes (`README.md`,
>   `README.zh-CN.md`, `docs/README.md`, `docs/README.zh-CN.md`)
>   so future-comers find it within two clicks. R181 also
>   removes the `paths-ignore` `**/*.md` / `docs/**` entries
>   from `test.yml`, so the full ~5-min CI matrix now runs on
>   doc-only commits (preventing the failure mode that bit
>   v1.6.3 attempt #1).
> - **Developer experience** — R183 adds
>   `bump_version.py --warn-empty-unreleased` (default-on soft
>   guard): bump-time WARNING to stderr if `CHANGELOG.md
[Unreleased]` looks empty, with `--no-warn-empty-unreleased`
>   escape hatch for chore-only patch releases. 15-test
>   contract covers the seven `[Unreleased]`-emptiness edge
>   cases plus four end-to-end `main()` flows.
> - **Test infrastructure** — R180 re-anchors
>   `test_housekeeping_r151` from the volatile `[Unreleased]`
>   section to the persistent whole-changelog invariant (R-feature
>   persistence under any Keep-a-Changelog category). Same three
>   tests, root cause once. pytest 9 bonus: 620 subtests
>   automatically detected (no new code, just better reporting).
>
> See `docs/code-reviews/cr13.md` (CR#13 — v1.6.3
> release-lifecycle rescue) and `docs/code-reviews/cr14.md`
> (CR#14 — this cycle wrap) for the full reasoning + follow-up
> closure trail (4/4 follow-ups across two adjacent cycles).

### Changed

- **CR#13 F-4** —
  `tests/test_workflow_paths_ignore_r181.py:test_codeql_and_vscode_workflows_dont_run_doc_guards`:
  promoted from doc-anchored `assertTrue(True)` to real assertion.
  Asserts neither `codeql.yml` nor `vscode.yml` invokes `pytest`,
  `ci_gate.py`, or any of 7 doc-aware test scripts
  (`test_housekeeping`, `test_docs_links`, `test_changelog`,
  `test_readme`, `test_generate_docs`, `check_i18n`,
  `check_locales`). Trips if a future maintainer adds a doc-aware
  step to those workflows, prompting them to revisit R181's
  scope. Same 6 cases, same file, no test-count delta.
- **R181** — `.github/workflows/test.yml` no longer ignores `**/*.md`
  or `docs/**` in its `paths-ignore`. Originally a CI-time-saving
  optimisation, it concealed a structural footgun: every guard the
  repo ships for doc surfaces (`test_housekeeping_r151`,
  `test_docs_links_no_rot`, `test_generate_docs_index_prefix_r178`,
  README/CHANGELOG-aware tests, etc.) was inert against doc-only
  commits. v1.6.3's release-tag CI was the canary — the bump touched
  _only_ CHANGELOG / version-strings, so `test.yml` skipped, the bug
  rode the `v1.6.3` tag straight into `release.yml`, and the Build
  job failed at `ci_gate.py`. Removing the blanket ignore lets
  doc-only commits run the full ~5-min matrix; `LICENSE` and
  `.github/ISSUE_TEMPLATE/**` (no pytest guard reads them) stay
  ignored. New regression test
  `tests/test_workflow_paths_ignore_r181.py` (6 cases) locks the
  posture.
- **R184 setup** — 在 GitHub 仓库设置启用
  `automated-security-fixes`（之前 `disabled`）。配合
  `dependabot-auto-merge.yml` 形成完整 CVE 响应链路：CVE 披露 →
  Dependabot 自动 PR → patch/minor 自动合并 → 下个发布自动带
  修复。`docs/release-recovery.{md,zh-CN.md}` 加入 "Security
  release shortcut" 段落，把这套自动化流程文档化（含 dependabot
  alerts 的 `gh api` 一行命令、commit 消息约定、`### Security`
  CHANGELOG 区段约定）。

### Security

- **R184** — 修复 5 个 Dependabot 上报的 CVE，全部为依赖升级
  （无源码受影响代码路径）：
  - `pytest` 8.4.0 → 9.0.3：修复 GHSA-6w46-j5rx-g56g
    （vulnerable tmpdir handling，symlink attack 风险）。
    本仓所有测试已经在用 `tmp_path` 现代 fixture，破坏面
    不大，但仍紧跟最新 LTS。9.x 唯一 breaking 变更是私有
    `config.inicfg`（9.0.2 已加兼容 shim），本仓无引用。
    bonus：pytest 9 启用原生 subtests，跑下来多识别出 620
    个 subtests。
  - `mistune` 3.2.0 → 3.2.1：修复 2 个 CVE，
    GHSA-8mp2-v27r-99xp（high，ReDoS in `LINK_TITLE_RE`）+
    GHSA-v87v-83h2-53w7（medium，Heading ID XSS）。
    `mistune` 是 `flasgger` 的传递依赖，仅用于渲染我们的
    docstring，不接受用户输入；exploit 路径在本仓为
    0——但仍紧贴 patch 版本。
  - 余下 2 个 mistune 中危 CVE（GHSA-58cw-g322-p94v figure
    XSS、GHSA-8g87-j6q8-g93x math plugin XSS）upstream 尚无
    patch；同样不影响本仓（不接受用户 markdown 输入）。
    Dependabot 会在 patch 发布后自动 PR。

### Added

- **R183** — `scripts/bump_version.py` 新增 `--warn-empty-unreleased`
  软警告（默认开启），bump 前轻量扫描 `CHANGELOG.md [Unreleased]`
  是否被遗忘。空时打 WARNING 到 stderr（不阻断 bump，仍可显式
  `--no-warn-empty-unreleased` 抑制）。闭合 CR#13 §F-3。三层
  契约由 `tests/test_bump_version_warn_empty_unreleased_r183.py`
  保护（15 用例）：
  - 纯函数 `_unreleased_section_is_empty` 的边界 —— 无标题 /
    只有子标题 / 有 bullet / `*` 替代符 / 文件结尾无下一个 release /
    上一个 release 有 bullet 但本区段空 等 7 个 case；
  - `_changelog_unreleased_section` 端点切分（不能溢出到下一个
    release）3 个 case；
  - argparse `BooleanOptionalAction` 暴露 `--warn-empty-unreleased`
    - `--no-warn-empty-unreleased` 双极性；
  - end-to-end `main()`：空 → WARNING；非空 → 无 WARNING；
    `--no-warn-empty-unreleased` 抑制；CHANGELOG.md 不存在不破坏 bump。
- **R182** — wire the new `docs/release-recovery.{md,zh-CN.md}`
  pair into the documentation index. Added cross-references in
  `docs/README.md` (Reviewers section), `docs/README.zh-CN.md`
  (审计者 section), `README.md` (Documentation section), and
  `README.zh-CN.md` (文档 section). Without this, F-1 would have
  been a hidden artefact — discoverability is what makes docs
  useful.
- **CR#13 F-1** — bilingual `docs/release-recovery.md` (EN) +
  `docs/release-recovery.zh-CN.md` (zh-CN): release-recovery
  playbook covering 3 failure patterns (Build fails → safe
  re-tag; some Publish ✓/✗ → never re-use burned version; only
  `Create GitHub Release` fails → manual `gh release create`).
  Includes a "what R180+R181 prevent" cross-reference table, a
  communication template, and links to related guards
  (R149/R180/R181 + bump_version.py + tag_push_safety.py).
  ≈ 200 lines / 200 行 each.
- **CR#13** — `docs/code-reviews/cr13.md`: code-review
  artefact for the v1.6.3 release-lifecycle rescue cycle (R180 +
  R181). Covers the failed attempt-1 (R151 fossilisation) → clean
  abort → R180 + R181 fixes → successful attempt-2 (5 jobs ✓:
  PyPI, Open VSX, Marketplace skip, GitHub Release, artefacts).
  4 follow-up items: F-1 (DONE, this entry), F-2 (DONE, audit
  result: codeql.yml legitimate / vscode.yml uses paths: allow-
  list), F-3 (deferred to v1.7.x), F-4 (DONE, see below). Single-
  cycle `*.tmp.md` artefact per R168 naming convention.

### Fixed

- **R180** — `tests/test_housekeeping_r151.py::TestR151ChangelogUnreleased`
  fossilised on the rolling `[Unreleased]` section: when R179's
  v1.6.3 bump correctly migrated R148-R151 entries into the
  persistent `[1.6.3]` section per Keep-a-Changelog, the three
  guards (`test_unreleased_not_empty`, `test_mentions_each_r_feature`,
  `test_categorized_under_added_or_changed`) all flipped red.
  Rescued by renaming the class to `TestR151ChangelogPersistence`
  and re-anchoring the invariant on the **whole** changelog under
  any real release-flavour heading (Added / Changed / Fixed). The
  `[Unreleased]` anchor itself is now only required to _exist_ (may
  be empty post-bump). One bug, three tests, root cause once.

## [1.6.3] — 2026-05-12

> Patch release on top of v1.6.2. Headline content (sorted by user
> impact):
>
> - **Reliability** — R165 fixes a 7-month-old feedback-loss footgun
>   in `wait_for_task_completion` (TimeoutError + `return` inside
>   `except` blocked `finally` retry-before-close from overriding
>   the resubmit response). Five-stage exponential-backoff retry
>   (0/100/250/500/1000 ms) now lets real user feedback always win
>   over the timeout fallback. Plus R165's web-side counterpart:
>   `/api/tasks/<id>/close` returns `skipped: True` on COMPLETED
>   tasks instead of deleting the result.
> - **Limits** — R166 raises message / prompt / option length caps
>   from the pre-R166 numbers (10000 / 10000 / 500) to (100000 /
>   1_000_000 / 10000). Hand-input, auto-submit, and prompt-suffix
>   all share the higher ceiling; everywhere the limit is surfaced
>   to humans (textarea `maxlength`, i18n hints, schema docstrings,
>   `data-i18n-html` fallback text, LRU-cache docstrings) was
>   tracked down and synced.
> - **MCP API simplification** — R167 removes the legacy
>   `predefined_options_defaults` parallel-array shape; consumers
>   should pass `list[dict]` of `{label, default}` (or `list[str]`
>   when no recommendation is needed). R173 adds an 11-case smoke
>   test that locks parsing-parity between the MCP path and the
>   HTTP path so the dual-input design doesn't drift.
> - **README polish** — R168 standardises `*.tmp.md` for single-
>   cycle code-review artifacts; R169 sinks five "how it works /
>   architecture / production-grade middleware / server self-info /
>   MCP-spec compliance" sections from README into
>   `docs/api(.zh-CN)/index.md` (cleaner top page for new users);
>   R170 allowlists the legitimate "Cancel" i18n duplicate;
>   R171 trims README header badges 10 → 5 with logos and
>   relocates the rest to topical sections.
> - **Internationalisation completeness** — R175 splits all five
>   `.github/` governance docs into EN / zh-CN pairs by the README
>   pattern; R176 adds the missing `docs/noise-levels.md` English
>   mirror (last orphan-Chinese doc closed).
> - **Guardrails + zero-warning sprint** — R174 lands a CSS quote-
>   consistency baseline guard (main.css 0-baseline); R177 fixes
>   the link-rot guard to skip inline + fenced code-block markdown
>   examples; R178 expands the CSS quote guard to
>   `tri-state-panel.css` (CR#11 §F-3 closeout); R179 closes three
>   `ci_gate.py` footguns in one commit — generator index drift
>   (the R169 hand-authored prefix was being silently regarded as
>   "drift" for ~7 months because doc-only commits skip the
>   `paths-ignore: docs/**` CI matrix), five `ty` diagnostics, and
>   a single-quote-bound regex assertion from R125b. This release
>   is the **first time post-R76 (`src/` layout migration) that
>   `uv run python scripts/ci_gate.py` runs to clean SUCCESS** —
>   zero warning, zero error, 4972 passed + 2 skipped under
>   `pytest -W error`.
> - **Reviewer discipline** — CR#10 (R155 → R172), CR#11
>   (R173 → R176), and CR#12 (R177 → R179) doc artifacts each
>   close their own follow-up items within the same cycle they
>   were opened. CR#12 in particular closes CR#11 §F-1 (R177) and
>   §F-3 (R178) immediately, plus CR#12's own §F-1 (audit) and
>   §F-2 (escape hatch) before tagging.
>
> No breaking API changes for end-users. The MCP schema change
> (R167) is documented and the migration is "use `list[dict]`
> instead of the parallel array" — clients that still send the
> removed field will receive a clear `additionalProperties: false`
> ToolError from FastMCP.

### Added

- **CR#12** — **Code Review #12 (post-R177 → R179 + 2 chores)** 文档落地，
  跟踪 R177 hotfix（CR#11 F-1 double-backtick fix）+ R176 docs-index follow-up
  - R178 (CR#11 F-3 closeout) + R179 (3 ci_gate footguns) + 1 precompress
    refresh chore 共 5 个 commit 的整体质量评估。沿用 R168 `.tmp.md` 命名
    规约（单次产物），路径 `docs/code-reviews/cr12.md`。内容
    覆盖：
  * **Cycle summary 表**：5 行（chore-R177-followup / R176-docs-index /
    R178 / R179 / chore-static-precompress）的 hash + one-liner。
  * **里程碑结论**：自 R76 (src/ layout 迁移) 以来**第一次** `ci_gate.py`
    全程通过、0 warning / 0 error。CR#11 §Strengths 提到 "zero-warning
    sprint" 是目标，CR#12 是它真正达成的那一次。
  * **Strengths 段**：5 条 — CR#11 follow-up F-3 / F-1 一周内闭环 / R179
    "10+ cycle 内最高杠杆 cleanup"（一次 commit 关 4 个 latent defect）/
    诚实的 chore commit 模式 / 生成器 keyword-only kwarg 严格向后兼容 /
    8 测试矩阵的回归保险。
  * **Risks 段**：4 条 — `ci_gate.py` 是 load-bearing 但可能未被 GitHub
    workflow 端到端调用（F-1）/ `existing_path` 是单向 escape hatch（F-2）/
    R174 默认目标硬编码（F-3）/ git 仓库继续提交预压缩 artifact 的
    repo-size 债（F-4）。
  * **Follow-up 表**：F-1 ~ F-4 共 4 个 work item，每个标 Severity +
    Owner suggestion，让 CR#13 可以直接 pick up。
  * **Test posture 表**：列出 6 个 cycle-critical 测试 surface 的覆盖
    率：`test_generate_docs_index_prefix_r178` (8) / R174 quote (29) /
    R80 link-rot (6) / export-button (16, 现在 16/16 而不是 15/16) /
    R173 dual-path (11) / 全套 ci-gate (4974 collected → 4972 + 2
    skipped passes)。
  * **Release readiness checklist**：7 条全勾 — 包括 "CI-gate footgun-4
    close" 意味着 `--ignore=tests/test_export_button_ui_r125b.py`
    hack 终于可以从开发者命令行里删掉。

### Changed

- **R179** — **三个 ci_gate footgun 一次性收口（generator index drift +
  stale ty:ignore + main.css quote drift）**。本提交把 `scripts/ci_gate.py`
  从 "结构性必 fail" 拉回到 "稳定全绿"，是 R76 (src/ layout 迁移) 后第
  一次真正实现 CR#11 §Strengths 提到的 "zero-warning sprint" 目标。同时
  落地 R178 直接 follow-up（generator 的 R169 hidden footgun）+ message
  description 字数限制漂移修复。
  - **Footgun 1**：`generate_docs.py` 每次 `--check` 都把 R169 手工
    插入到 `docs/api/index.md` 顶部的 5 个 section（How it works /
    Architecture / Production-grade middleware / Server self-info /
    MCP-spec compliance）误判为 drift，让 `ci_gate.py:222-235` 结构性
    必红。修复：`generate_index` 新增 `existing_path: Path | None =
None` keyword-only 参数；当指向的 index.md 已存在且含 modules-heading
    时，保留 heading 之前的所有内容（手工块）只重写 generator-owned 后缀
    （modules list + quick navigation + footer）。`existing_path=None` 保
    持历史 byte-identical 行为。
  - **Footgun 2**：`message` field description 在 R166 把 `MAX_MESSAGE_
LENGTH` 提到 1_000_000 之后仍写 "Recommended length: 1-2000 characters;
    hard limit 10000"。这是 MCP tools/list 暴露给 LLM 的 schema description
    —— 模型 ~3 个月一直在 undersell 实际允许的 payload size。修复为 "soft
    cap 1,000,000 characters (~1 MB UTF-8, R166)"。
  - **Footgun 3**：`ty` (Python static checker) 5 条 diagnostic 一次性
    清空：`test_notification_inflight_persistence_r136.py`（2 处 stale
    unresolved-import ignore）/ `test_tasks_export_include_images_r125c.py`
    / `test_tasks_export_since_r135.py`（各 1 处 stale ignore）以及
    `test_interactive_feedback_errors.py:314` 真实 `unknown-argument`
    error（测试故意传 R167 已移除的 `predefined_options_defaults` 验
    证 raise，加 narrow `# ty: ignore[unknown-argument]` 让 ty 不把
    deliberate misuse 当作 check error）。
  - **Footgun 4**：`tests/test_export_button_ui_r125b.py::
test_export_btn_in_light_theme_block` 硬编码 `[data-theme='light']`
    单引号正则，而 R169 chore `73d9980` 已把 `main.css` 全部
    attribute-selector 收敛到双引号。这条测试自 R169 起一直 fail，被
    `--ignore=tests/test_export_button_ui_r125b.py` 在 full-regression
    命令行里 mask 了 ~10 个 cycle。修复：把 regex 从
    `[data-theme='light']` 放宽到 `[data-theme=['"]light['"]]` —— 测
    试关心的是 light-theme selector 包含 `.export-btn` 这个语义不变
    量，不是引号风格。16/16 cases pass 后，`--ignore` hack 可以从
    开发者命令行里删掉。
  - 新增 `tests/test_generate_docs_index_prefix_r178.py`（8 测试）锁
    `generate_index` 的 `existing_path` 契约：None / 不存在路径 /
    无 modules-heading / 有 modules-heading / zh-CN 用 `## 模块列表`
    anchor / 真实仓库 EN index 必含 R169 5 个 section / 真实仓库
    zh-CN index 同样 / 函数签名 keyword-only + default None。
  - Test posture: `uv run python scripts/ci_gate.py` 全程 PASS / 0
    warning / 0 error；`uv run ty check .` → `All checks passed!`
    (5 → 0)；`uv run pytest -W error` → 4972 passed + 2 skipped。

- **R178** — **R174 CSS quote-consistency guard 扩展到 `tri-state-panel.css`**
  （CR#11 F-4 / Risks§R174-scope follow-up）。
  CR#11 §Risks 列了一条尾巴：R174 baseline guard 只覆盖 `main.css`，
  `tri-state-panel.css`（feature-scoped CSS，159 行）当时仍有 21 处
  attribute-selector single-quote（`[data-state='ready']` 等），与
  `main.css` 100+ 处 `[data-xxx="..."]` 的 double-quote 风格漂移。
  本提交一次性收敛：
  - 把 `tri-state-panel.css` 里 21 处单引号 attribute-selector 值改成双
    引号（`[data-state="ready"]` 等），banner 注释里的 prose
    `host's real content region` apostrophe 不动；
  - `scripts/check_css_quote_consistency.py` 的 `DEFAULT_TARGETS` 从
    1 个文件扩成 2 个（main + tri-state-panel），同步更新 docstring
    解释为什么 `prism.css` vendor 文件继续排除；
  - `.pre-commit-config.yaml` 的 hook `files` glob 从
    `^.../main\.css$` 改成 `^.../(main|tri-state-panel)\.css$`；
  - `tests/test_css_quote_consistency_r174.py` 新增
    `test_default_targets_cover_project_owned_css`（验证 main +
    tri-state-panel 在 DEFAULT_TARGETS 内，prism 必须排除），并把旧测试
    `test_hook_files_glob_targets_main_css` 改名为
    `test_hook_files_glob_targets_project_owned_css` 同步更新断言；
  - hook 跑全套：2 个文件 = 0 violation，baseline 仍 0，无回归。
    价值：项目自有 CSS 现在共享同一个 quote-style 基线；CR#11 §Risks
    R174-scope 条目可关。`prism.css` 因为是 vendor / 第三方原始风格保持
    豁免，作为 documented exception 在 docstring 里说明。

- **R175** — **`.github/` 治理文档按 README 模式拆 EN / zh-CN**。
  TODO.md 长期未完成项："`.github` 下面的文档应该分开中文版和英文版，默认英
  文版，参考 README 模式"。`.github/` 下原本的 `CONTRIBUTING.md` /
  `CODE_OF_CONDUCT.md` / `SUPPORT.md` / `SECURITY.md` /
  `PULL_REQUEST_TEMPLATE.md` 5 份治理文档全是中英文 inline 混排（行内
  `English · 中文` 形式，或块级分段交错），让英语 reader 必须忽略一半内容、
  中文 reader 同理 —— 体验差且与 README 的纯净分文件模式不一致。
  本提交把 5 份治理文档全部按 `README.md` / `README.zh-CN.md` 模式拆开：
  - `CONTRIBUTING.md`（英文默认）+ 新增 `CONTRIBUTING.zh-CN.md`；
  - `CODE_OF_CONDUCT.md`（英文，对齐 Contributor Covenant 2.1 原文）+ 新增
    `CODE_OF_CONDUCT.zh-CN.md`（中文译本，正式约束以英文为准）；
  - `SUPPORT.md`（英文）+ 新增 `SUPPORT.zh-CN.md`；
  - `SECURITY.md`（英文）+ 新增 `SECURITY.zh-CN.md`；
  - `PULL_REQUEST_TEMPLATE.md`（英文默认）+ 新增
    `PULL_REQUEST_TEMPLATE.zh-CN.md` —— GitHub 默认弹出英文模板，中文用户
    在 PR URL 末尾追加 `?template=PULL_REQUEST_TEMPLATE.zh-CN.md` 切换。
    每个文件顶部按 README 模式加 "English | 简体中文" 双链接形式的语言切换
    banner（点 zh-CN 链接跳中文版，中文版同样加反向链接跳英文版）。同步更新
    所有引用：
  - `README.zh-CN.md` → `CONTRIBUTING.zh-CN.md` / `CODE_OF_CONDUCT.zh-CN.md`
  - `docs/README.zh-CN.md` → `.github/SECURITY.zh-CN.md`
  - `docs/troubleshooting.zh-CN.md` → `.github/SUPPORT.zh-CN.md` × 2 处 +
    `.github/SECURITY.zh-CN.md` × 2 处
  - `packages/vscode/README.zh-CN.md` → `.github/SECURITY.zh-CN.md`
    英文文档保持原 `.md` 链接不变（默认即英文版）；历史文档
    `docs/lessons-learned-silent-decay.md` 内的旧引用是讲过去事件，**不动**。
    测试守门：`tests/test_docs_links_no_rot.py::test_scan_covers_at_least_known_files`
    的 `must_cover` 列表从 1 个 `.github/SECURITY.md` 扩到 10 个（5 对 EN +
    zh-CN），任何未来 PR 误删某个文档都会立即被锁住。R80 docs link-rot 全量
    扫描仍保持 0 broken link。

### Added

- **R177** — **CR#11 F-1 落地：link-rot guard 跳过 inline code + fenced
  code block 内的伪 markdown link**。R175 / R176 落地过程两次踩到同一个
  trap：CHANGELOG / code-review doc 里写形如 `[label](./xxx.zh-CN.md)`
  的 markdown-link 占位符示例时，`tests/test_docs_links_no_rot.py` 的
  `_MD_LINK_RE` 正则不区分代码块与正文，把示例当真 link 校验、CI 红。
  之前 R175 / chore-`1b96a47` 用"改示例写法"绕过，但 hidden footgun
  仍在 —— CR#11 F-1 标记了这条尾巴，本提交把它一次性根治：
  - 新增 `_INLINE_CODE_RE` 单反引号剥离正则（`` `[^`]*` ``），每行
    先 `sub` 掉所有 inline code 段，再喂 `_MD_LINK_RE`；
  - `_extract_local_targets` 新增 fenced code block 状态机：检测以
    ` ` ``` 开头的行作为开关，fence 内整段跳过 link 校验；
  - 新增 3 个回归测试 `test_inline_code_link_is_ignored` /
    `test_fenced_code_block_link_is_ignored` /
    `test_real_link_outside_inline_code_is_still_checked`，分别锁住：
    inline code 占位符不进 queue / fence 内 link 不进 queue / 但行内
    真实 link 仍能被提取。
    价值：与 R66 brand color / R174 quote consistency 同模式，"防漂移成
    本接近 0，可观察价值高"。未来任何 CHANGELOG / code-review doc 可以
    自由地用 `[label](./path.md)` 格式举例 markdown link，不必担心 R80
    link-rot guard 误伤。

- **CR#11** — **Code Review #11 (post-R173 → R176)** 文档落地，跟踪
  R173-R176 + 1 个 CHANGELOG-link-rot chore 共 5 个 commit 的整体质量评
  估。沿用 R168 `.tmp.md` 命名规约（单次产物，非长期设计文档），路径
  `docs/code-reviews/cr11.md`。内容覆盖：
  - **Cycle summary 表**：5 行（R173 F-3 follow-up / R174 F-1 follow-up /
    R175 .github 拆分 / chore 1b96a47 link-rot 修复 / R176 noise-levels EN）
    的 hash + one-liner。
  - **Strengths 段**：列出本批次 5 大亮点 —— CR#10 follow-up 一周内
    100% 关闭（F-1 + F-3 DONE）/ defensive testing 模式（R173 把"design
    decision"锁在 test 里而非 refactor 共享代码）/ 引号一致性最小可行护栏
    （R174 vs full prettier 的 cost/benefit 决策）/ TODO 长期未完成项被
    R175 解锁 / 最后一个 orphan-Chinese 文档关闭（R176 后 README + docs +
    .github 全部 EN-default + optional zh-CN）。
  - **Risks 段**：4 条需要警惕的尾巴 —— EN/zh-CN 长文档翻译漂移（R176
    §5 anchor 表的 line-number 同步未自动化）/ CHANGELOG markdown-link
    example 是 hidden footgun（chore 1b96a47 抓到一次，下次还可能重蹈）/
    .github/PULL_REQUEST_TEMPLATE.zh-CN.md 默认不可见（仅 query 切换）/
    R174 baseline guard 当前只覆盖 main.css，tri-state-panel.css 未来若
    成熟需扩展。
  - **Follow-up 表**：F-1 ~ F-4 共 4 个 work item，每个标 Severity +
    Owner suggestion，让 CR#12 可以直接 pick up。
  - **Test posture 表**：列出 6 个 cycle-critical 测试 surface 的覆盖
    率：dual-path parity (11) / CSS quote (28) / docs link rot (2,
    must_cover 扩到 12) / noise-levels anchors (6) / locale parity / pre-
    commit chain；全部 0 issue。
  - **Ready-to-tag posture 段**：4 个 ✓ checkmark 表明可以 clear for
    v1.6.4 / v1.7.0 tagging，所有 CR#10 follow-up 都已闭环。

- **R176** — **`docs/noise-levels`：补齐英文版，关闭"孤儿中文文档"漏洞**。
  R175 把 `.github/` 治理文档按 README 模式拆成 EN/zh-CN 后，`docs/` 下还
  剩一个 **唯一的孤儿中文文档**：`docs/noise-levels.zh-CN.md`（362 行的
  IG-6 噪音等级规范）—— 它没有对应的英文版，违反了项目"默认英文版 + 可选
  zh-CN"约定。本提交：
  - 新增 `docs/noise-levels.md`（英文版，420 行），完整翻译 §1-§12 含 5
    个表格、3 段代码引用、6 条 anchor 断言映射；术语对齐项目其他英文文档
    （"channel" / "circuit-breaker" / "anti-pattern" 等）。
  - `docs/noise-levels.zh-CN.md` 顶部加 "English / 简体中文" 双链接形式
    的语言切换 banner，末尾"变更历史"表追加 R176 entry。
  - `docs/noise-levels.md` 顶部加对称的 banner。
  - `tests/test_docs_links_no_rot.py::test_scan_covers_at_least_known_files`
    的 `must_cover` 列表追加 `docs/noise-levels.md` +
    `docs/noise-levels.zh-CN.md`，把 noise-levels 双语对纳入守门 —— 任何
    一份意外被删都会让 CI 红。
  - `tests/test_noise_levels.py` 的 T6 锚点断言（中文版含
    `critical/important/quiet` 关键词）**保持不变** —— 测试仍然只
    锁中文版作为单一 source of truth，避免在两份文档间维护双重断言；英文
    版是"翻译镜像"，由 R80 link-rot guard 兜底保证其与中文版的存在性同步。
  - 顶层 README 没有引用 `docs/noise-levels.md` —— 这份文档是给 maintainer
    / contributor 看的开发规范，按"开发者文档"惯例不进 README links。

- **R174** — **CR#10 F-1 落地：CSS 字符串引号一致性守门 hook**。
  R169 commit `73d9980` 用 prettier 把 `main.css` 的字符串引号一次性收敛
  到 double-quote 一致风格，但仓库没有 prettier 配置，靠人工运行 —— Code
  Review #10 F-1 标记了风险：后续 PR 可能再次引入 single-quote 字符串让
  CSS 整洁度悄悄退化。本提交按 R66 brand color 同模式新增防漂移护栏：
  - 新增 `scripts/check_css_quote_consistency.py`（约 200 行 + 充分 docstring）：
    扫 `main.css`，统计"裸露"的 single-quote 字符串字面量（跳过 `url(...)`
    内嵌 SVG xmlns 和 `/* ... */` 注释里的字符串），baseline = 0；
  - 新增 `.pre-commit-config.yaml` 里 `check-css-quote-consistency` local
    hook，`files` glob 只匹配 `main\.css` —— `prism.css` 是 vendor 代码、
    `tri-state-panel.css` 未被 R169 prettier 接管，明确不纳入守门范围；
  - 新增 `tests/test_css_quote_consistency_r174.py` 共 28 个测试覆盖
    `_strip_comments_and_url_blocks` / `count_naked_single_quotes` /
    `find_naked_single_quotes_with_lines` / `scan_files` / CLI 三分支退出
    码 / `main.css` baseline 同步 / pre-commit 配置正确性。
    价值：把"CSS 整洁度漂移"成本从"人工运行 prettier"降到"pre-commit 自动卡
    住"。完整 prettier 引入（需要 `.prettierrc` + Node 依赖 + CI 矩阵改动）
    价值有限、维护负担大，本 baseline-style 护栏是"防漂移成本接近 0、覆盖 80%
    价值"的最小可行方案。脚本 docstring 明确说明未来若决定上 prettier 可无缝
    退役（baseline 调 0 + 撤掉 hook 即可）。

- **R173** — **CR#10 F-3 落地：MCP-path / HTTP-path predefined_options 解析 parity smoke**。
  新增 `tests/test_predefined_options_dual_path_parity_cr10_f3.py` 共 11 个
  断言场景，锁住「MCP 路径 `list[dict]`」与「HTTP 路径 `(list[str], list[bool])`
  parallel-array」在所有合法输入上殊途同归到同一组 `(labels, defaults)` 内
  部表示：
  - `test_simple_dict_form_matches_parallel_array`：单 dict 形态等价 1 元素 parallel-array
  - `test_multi_dict_mixed_defaults_match_parallel_array`：3 选项混合 default
  - `test_dict_without_default_falls_to_false`：dict 形态省略 default 字段 → False
  - `test_text_alias_for_label_matches_parallel_array` / `test_value_alias_for_label_matches_parallel_array`：`text` / `value` 为 `label` 的 alias
  - `test_selected_alias_for_default_matches_parallel_array` / `test_checked_alias_for_default_matches_parallel_array`：`selected` / `checked` 为 `default` 的 alias
  - `test_pure_string_form_matches_all_false_parallel_array`：纯 list[str] → defaults=[False, ...]
  - `test_mixed_str_and_dict_form_normalises_consistently`：同一 list 混 str + dict
  - `test_truthy_default_values_normalise_to_bool`：int/string truthy 字符串归一（覆盖 `"true"`/`"1"`/`"yes"`/`"y"`/`"on"`/`"selected"`）
  - `TestHttpSideStrictlyRejectsDictForm.test_post_handler_rejects_non_string_options`：源码级别断言 `web_ui_routes/task.py` 里"元素必须是字符串"的 400 分支仍然存在，
    防止未来误把 HTTP-side 改成"也接受 list[dict]"破坏 dual-path 分工。
    这条 F-3 的价值：未来如果在 MCP-side 加新的 `label` alias（例如 `"caption"`）
    但忘了在 HTTP-side 补对应兼容逻辑，本测试会失败提醒。这样把 R167 设计的双
    入口分工从「文档口头约定」升级到「编译时强制」。

- **CR#10** — **Code Review #10 (post-R155 → R172)** 文档落地，跟踪
  R155-R172 11 个提交的整体质量评估。同时**修正 `.gitignore`** 让
  `docs/**/*.tmp.md` 显式不被忽略——R168 引入 `.tmp.md`
  命名规约时只把 git 已 tracked 的旧文件 grandfathered 进库（`code-review-
r150-r154-cr9.tmp.md` / `security-triage-r72.tmp.md`），新增的同名
  规约文件被 `.gitignore` 第 253 行 `*.tmp.md` 拦截。R168/CR#10
  例外 `!docs/**/*.tmp.md` 把 `docs/` 下的 `.tmp.md`（按 R168
  规约归档的 single-cycle artefact）从仓库根的"个人笔记 / 草稿"
  忽略规则里挖出来。沿用 R168 `.tmp.md` 命名规约
  （单次产物，非长期设计文档），路径 `docs/code-reviews/cr10.md`。
  内容覆盖：
  - **Cycle summary 表**：11 行（10 个 R-tag + 1 个 css-prettier chore）
    的 hash + one-liner，让后续 maintainer 一眼看清这一批次的边界。
  - **Strengths 段**：列出本批次 5 大亮点 —— 数据完整性双重防护
    (R165 try/except/finally 控制流陷阱解读) / API 收敛 (R167
    predefined_options 3 形态 → 2 形态) / README 右尺寸 (R169 + R171
    分而治之) / Lint floor 可观测性 (R170 + R172 文档化) / 功能对等性
    (R155 + R156 关闭 CR#9 F-3 / F-4 / F-5 follow-up)。
  - **Risks 段**：4 条需要警惕的尾巴 —— soft-limit ↔ hard-limit 余量
    (R166 emoji 突发 worst-case 评估) / CSS 重格式化是一次性的 (没有
    formatter pre-commit hook) / Open VSX badges 移到 below-the-fold
    可能影响 install rate (R171 需 2 周观察) / R167 移除 30 行后两条
    HTTP 入口路径缺 parity smoke。
  - **Follow-up 表**：F-1 ~ F-4 共 4 个 work item，每个标 Severity +
    Owner suggestion，让 CR#11 可以直接 pick up。
  - **Test posture 表**：列出 6 个 cycle-critical 测试 surface 的覆盖
    率：activity dashboard (108+62+34=204 tests) / predefined_options
    shape (14+16) / feedback-loss defense (9+3) / soft-limit
    relaxation / docs link rot / locale parity；全部 0 issue。
  - **Ready-to-tag posture 段**：4 个 ✓ checkmark 表明可以 clear for
    v1.6.4 / v1.7.0 tagging，没有 blocking issue。

### Changed

- **R172** — **代码注释清理**：`task_queue.py::Task.predefined_options_defaults`
  字段上方注释从「TODO #3：每个预定义选项的"默认是否选中"」改成正式契约说明。
  - 背景：R167 把 LLM → MCP 这一侧的 `predefined_options_defaults` 顶层
    参数移除（统一收敛到 `predefined_options=[{label, default}]` dict 形态），
    但 `task_queue.Task` 这个**内部 ORM 模型**字段仍然保留——它现在是
    LLM → MCP（被 `server_feedback` 拆 dict 后传入）与外部 HTTP → POST
    /api/tasks（VS Code 插件 / 自动化脚本路径）两条路径的统一内部表示。
  - 旧注释"TODO #3：…"误导阅读者以为这还是个未完成的待办；R172 改成 13
    行的正式契约说明：LLM 路径"禁止"、外部 HTTP "支持"、前端"直接读"。
  - 零功能改动，纯文档增强。`test_task_queue.py` /
    `test_predefined_options_shape_r167.py` / `test_interactive_feedback_errors.py`
    共 103 个测试照常通过；R167 已存在的"传旧 `predefined_options_defaults`
    顶层参数触发 TypeError"测试仍然防漂移。

- **R171** — **README badge 精简到 2026 最佳实践（3-5 个 header badge）**。
  TODO "README badge 有点多，样式不太好" 任务。R171 处理：
  - **顶部 header badges**：10 个 → **5 个**（符合 shields.io / daily.dev 2026
    "best practices for github markdown badges" 推荐的 3-5 个上限）：
    1. Tests workflow（项目健康 — 必备）
    2. PyPI version（release 状态 — 必备）
    3. Python versions（兼容性 — 必备）
    4. OpenSSF Scorecard（安全 / supply-chain — 已聚合了 CodeQL 信号）
    5. License（MIT — 合规）
  - **删除**：
    - CodeQL badge —— OpenSSF Scorecard 已经把 CodeQL 当成 Security-Policy
      子项聚合进总分，再单独挂 CodeQL badge 重复展示。
  - **重定位（信息不丢失）**：
    - 3 个 Open VSX badge（version / downloads / rating）→ 移到「VS Code
      extension（可选）」章节顶部，与 VS Code 插件相关内容聚合，对照浏览
      Open VSX Marketplace 时一目了然。
    - DeepWiki badge → 移到「Documentation / 文档」章节末尾，加上「AI 辅
      助的仓库智能问答入口」描述，给读者一个明确的"什么时候用 DeepWiki"
      reasoning，而不是顶部抽象的 logo。
  - **样式升级**：所有保留 badge 增加 `logo=...` 参数（GitHub Tests 配
    GitHub 图标 / PyPI 配 pypi 蓝白 / Python 配 python 黄白 / OpenSSF 配
    securityscorecard 图标 / License 加 `color=success` 绿色）。视觉上从
    "灰底文字" 升级到"图标 + 标签"现代极简风格，与 shadcn-style shieldcn
    的现代极简审美对齐，同时不引入第三方 badge 服务依赖（继续走 shields.io）。
  - 中英文 README 同步处理。docs link rot 守卫
    （`test_docs_links_no_rot.py`）通过——VS Code / Documentation 章节
    内的 badge 链接全部指向已知存在的 Open VSX / DeepWiki 公网入口。
  - 不引入第三方 badge 服务：所有 badge 仍走 `shields.io` (PyPI / Python /
    OpenSSF / License) + `deepwiki.com/badge.svg` (DeepWiki 自家)。零
    外部依赖、零 broken-link 风险。

- **R170** — **`check_i18n_duplicate_values.py` allowlist 收录 `"Cancel"`,
  把唯一一条 informational WARN 收口到 0**。脚本本身 exit 0 不阻断 CI，
  但终端输出"1 duplicate value group(s) found above MIN_LEN=6"会被本仓
  "0 warning / 0 error" QA 原则计为污染。`page.cancel`（通用对话框「取消」）
  和 `quickPhrases.formCancel`（Quick Phrases feature form 内「取消编辑」）
  属于不同 feature 命名空间 —— 完美匹配 ALLOWLIST_VALUES 现有设计意图
  （"按 feature 而非 ui-element 命名" intlpull.com 2026 规约）。合并到
  单一 `common.cancel` 会让 Quick Phrases form 改 button 文案时必须改全 app
  的「取消」对话框，违反封装原则。落地：
  - `scripts/check_i18n_duplicate_values.py` `ALLOWLIST_VALUES` 集合加入
    `"Cancel"`，并附 11 行注释解释为什么不合并到 `common.cancel`。
  - `python3 scripts/check_i18n_duplicate_values.py` 现在输出
    `OK: no duplicate locale values above threshold`，0 WARN。
  - `test_i18n_duplicate_values.py` 7 个测试照常通过，证明 allowlist
    机制本身（`test_allowlist_suppresses_warning`）依然按预期工作。
  - 工程口径：项目维护"0 warning / 0 error"输出洁净度，让真信号不被
    噪声淹没。R170 这种"无功能改动、纯 lint allowlist 调整"也走 CHANGELOG
    - R-tag，是 v1.5.x 系列的一致约定。

- **R169** — **精简 README，把"工作原理 / 架构图 / 中间件 / 自检 resource /
  MCP 协议规范支持"等技术深细节迁移到 `docs/api{,.zh-CN}/index.md`**。
  TODO 任务 5 要求："`README.md` 主要特性内容太杂，技术细节下沉到 docs"。
  R169 处理：
  - **`README.md` / `README.zh-CN.md`**：
    - 在「Key features / 主要特性」清单里移除 3 条偏服务端实现细节的项目：
      _Server self-info resource_、_MCP protocol specification_、
      _Production-grade middleware_ （这些是给"想看怎么实现"的开发者看的，
      不是"决定要不要用"的卖点）。
    - 删除整段 `## How it works` / `## 工作原理`（HTTP / SSE / polling 时序
      细节、Bark loopback 等运行时机制）。
    - 删除整段 `## Architecture` / `## 架构` 含 Mermaid flowchart（节点 13 个、
      边 18 条），README 长度 ~80 行下降。
    - 在「Key features / 主要特性」末尾追加一段 callout：把读者**主动**引到
      `docs/api{,.zh-CN}/index.md` 与 `docs/mcp_tools{,.zh-CN}.md`，避免
      "想看细节的人找不到入口"。
  - **`docs/api/index.md` / `docs/api.zh-CN/index.md`**（迁移目的地，无丢失）：
    - 在「Modules / 模块列表」**之前**插入 5 个新章节，按"先体感、再细节、
      再合规性"顺序铺排：
      1. `## How it works` / `## 工作原理` —— 完整保留 6 步时序；
      2. `## Architecture` / `## 架构` —— Mermaid flowchart 完整迁入
         （CLIENTS / MCP_PROC / WEB_PROC / VSCODE_PROC / USER_UI 五个 subgraph
         全部保留），其后保留"内部 helper 模块在下方模块列表"的指引；
      3. `## Production-grade middleware` / `## 生产级中间件` —— 四级中间件
         链 + `task.created` / `task.notified` / `task.completed` 三个
         结构化事件；
      4. `## Server self-info resource` / `## Server 自检 resource` ——
         `aiia://server/info` 字段清单；
      5. `## MCP-spec compliance (2025-11-25 protocol)` / `## MCP 协议
规范支持（2025-11-25 协议）` —— 工具 annotation + FastMCP tag +
         server identity 三层规范支持，给 ChatGPT Desktop / Claude Desktop /
         Cursor 等客户端的渲染兜底。
  - **设计哲学**：README 是"决定要不要用"的第一面（卖点 + 截图 + 安装），
    docs/api/index.md 是"决定怎么集成 + 排障"的第二面（架构 + 协议合规性
    - 模块 API）。R169 之前 README 把两层混在一起，让首次访问者既看不到
      清晰的卖点、又被一大段 Mermaid 图吓退；R169 后两层职责清晰、相互引用。
      跨文档 markdown link 没有遗漏（`docs/mcp_tools{,.zh-CN}.md` 入口、
      模块列表里的 `state_machine.py` / `server_feedback.py` 等历史引用
      都保留）。
  - 全测试 4904 passed 2 skipped 0 failed；
    `test_docs_links_no_rot.py` / `test_docs_module_classification_parity.py`
    / `test_mcp_tools_doc_consistency.py` 全绿，证明跨文档链接、模块分类
    invariant、文档 ↔ code 字段一致性都没被破坏。

- **R168** — **docs 重命名：去掉 R-cycle 标识，按主题或 `.tmp.md` 归档**。
  TODO 任务 4 要求："docs 里 r99 类文档让用户觉得项目不完善"。R168 按
  以下规则统一处理 8 个带 R-cycle 标签的 docs：

  | 旧文件名                                | 新文件名                                       | 处理                                      |
  | --------------------------------------- | ---------------------------------------------- | ----------------------------------------- |
  | `docs/perf-r20-roadmap.md` (+ `.zh-CN`) | `docs/perf-mcp-cold-start.md` (+ `.zh-CN`)     | 改主题命名（性能文档 = MCP 冷启动批次）   |
  | `docs/perf-r21-roadmap.md` (+ `.zh-CN`) | `docs/perf-web-asset-pipeline.md` (+ `.zh-CN`) | 改主题命名（性能文档 = Web 静态资源管线） |
  | `docs/lessons-learned-r60s.md`          | `docs/lessons-learned-css-and-options.md`      | 改主题命名（教训 = CSS + MCP options）    |
  | `docs/lessons-learned-r70s.md`          | `docs/lessons-learned-silent-decay.md`         | 改主题命名（教训 = "silent decay" 模式）  |
  | `docs/code-review-r150-r154-cr9.md`     | `docs/code-reviews/cr9.md`        | 单次产物 → `.tmp.md` 后缀（按用户要求）   |
  | `docs/security-triage-r72.md`           | `docs/triage/security-r72.md`              | 单次产物 → `.tmp.md` 后缀                 |
  - 所有跨文档 markdown link 已同步更新（`docs/README{,.zh-CN}.md` /
    `docs/lessons-learned-silent-decay.md` / `perf-*.md` 互相引用 /
    `packages/vscode/i18n.js` 行内注释 / `packages/vscode/CHANGELOG.md`）。
  - `docs/README{,.zh-CN}.md` 列表里的描述文字也去掉了"R63 → R70 batch"
    这种 cycle 标签，改用"v1.5.45 批次"等版本号锚点。
  - **CHANGELOG.md 的历史段落** 保留对旧文件名的引用（4694 / 4700 / 4727 /
    4805 / 4807 / 6322 / 6323 / 6561 / 6562 行）：CHANGELOG 是历史记录，
    那些条目对应的 commit 当时确实就叫旧文件名，不应该回写。
  - 全测试 4904 passed 0 failed。

- **R167** — **predefined_options 形态收敛到 list[dict] 推荐写法，移除并行
  数组形态**。`predefined_options` 之前支持 3 种输入形态：
  - `list[str]`（A）；
  - `list[dict]`（B，`[{label, default}]` 对象数组）；
  - `list[str] + predefined_options_defaults`（C，并行布尔数组）。
    其中 B 与 C 功能完全等价，但 C 是经典反模式（并行数组对齐 bug、API 表面
    冗余、JSON Schema 难以 enforce 位置约束、LLM-unfriendly）。业界主流
    （HTML `<option selected>`、React selectable array、JSON Schema
    `enum` + `default`）也都是对象式表达。R167 收敛到 A + B 两种形态：
  - **移除** `predefined_options_defaults` 顶层 MCP 参数（FastMCP
    `additionalProperties: false` 会让旧调用方收到清晰的 ToolError）；
  - **移除** `server_feedback.interactive_feedback` 中的 parallel-array
    合并逻辑（"detect list + zip into dict form"，约 30 行删除）；
  - **强化** `predefined_options` description 主动推荐 `list[dict]`
    形态（带 RECOMMENDED 字眼、明示 R167 已移除 C 形态、移除 `[Recommended]`
    文本前缀 hack 的提及）；
  - **保留** `validate_input_with_defaults` 的 dict 形态解析能力——前端
    HTTP `POST /api/tasks` 仍接受 `predefined_options_defaults` 字段
    （VS Code 插件 / 外部脚本路径），但 LLM MCP 调用必须用 dict 形态。
  - 文档 `docs/mcp_tools{,.zh-CN}.md` 已同步精简（从 3 形态变 2 形态，
    多了一段"R167 移除说明"）；老测试 `test_predefined_options_defaults_
in_signature_r63b.py` 被替换为 `test_predefined_options_shape_r167.py`
    （锁住"参数已移除 + dict 形态正向行为"）；`test_interactive_feedback_
errors.py::test_v1_5_36_drift_args_do_not_raise` 迁移到 list[dict]
    写法，并新增 `test_predefined_options_defaults_now_raises_r167` 锁
    "传 R167 已移除参数会触发 TypeError"。
  - 全测试 4904 passed 0 failed。

- **R166** — **放宽三块字数软上限，与 LLM 长上下文场景对齐**。原项目里
  存在 3 处"软"字符上限互不一致地夹击了合法长 prompt 场景（LLM 长
  context 拼接、技术文档粘贴、长 review feedback）：
  - `server_config.MAX_MESSAGE_LENGTH`: 10_000 → **1_000_000**（约 1MB
    UTF-8 字符，仍远低于 `task_queue._PROMPT_REJECT_BYTES = 10MB`
    字节级 DoS 防御，留 ~3-10× 字节安全裕度）；
  - `server_config.MAX_OPTION_LENGTH`: 500 → **10_000**（单个
    `predefined_options` 选项上限，让"短段技术说明"或"完整
    docstring 摘要"都能作为选项 label）；
  - `server_config.PROMPT_MAX_LENGTH`: 10_000 → **100_000**（设置
    项级 prompt：`resubmit_prompt` / `prompt_suffix`，允许嵌入
    较长的元规则 / 工作流约束 prompt）。
  - 同步：`web_ui_routes/feedback.py::_sanitize_selected_options` 把
    硬编码 500 改为引用 `MAX_OPTION_LENGTH`；`/api/update` 截断也
    跟 `MAX_MESSAGE_LENGTH` 走；前端 `feedback_char_counter.js` 把
    视觉阈值抬到 `WARN=800_000` / `DANGER=1_000_000`，避免合法长
    prompt 被 counter 提前标红；`templates/web_ui.html` 设置项 textarea
    的 `maxlength` 改成 `100000`（同 `PROMPT_MAX_LENGTH`）；i18n
    提示语跟着同步。
  - 设计哲学：**软上限只 warn 不阻断；DoS 防御只在字节级硬上限处
    一刀切**（`task_queue.add_task` 的 10MB 字节级 reject）。这样：
    (a) 用户体验上没有"莫名其妙超长被截断"的小坑；(b) 仍有可证明
    的上界让 enqueue / serialize / notification payload 不会爆掉。
  - 文档同步：`docs/mcp_tools{,.zh-CN}.md` 已同步更新，由
    `test_mcp_tools_doc_consistency` 锁死 docs ↔ code 数字对齐。
  - 测试更新：所有相关测试改为相对常量构造超长输入（不再硬编码
    "20000" / "1000" / "10001" 类魔数），未来再调常量也不会失效。
    全测试 4898 passed 0 failed。

### Fixed

- **R165** — **反馈丢失防御双重保护**：MCP `wait_for_task_completion` 在
  SSE 检测到 `task_changed(new_status=completed)` 后，本地 `_fetch_result()`
  撞瞬时网络抖动（503 / connection error / DNS jitter / TLS 重协商 /
  cellular handoff）→ R17.4 单次 retry 也失败 → `_close_orphan_task_best_effort`
  把已 COMPLETED 且带 user feedback 的 task 永久删除 → 用户辛辛苦苦填的
  反馈 / 选项 / 图片全部丢失，零日志告警。R165 修复双层防御：
  - **服务端**：`POST /api/tasks/<id>/close` 检查 task 状态，已 COMPLETED
    的任务 short-circuit 返回 `{success: True, skipped: True,
reason: "task_completed"}`，不调用 `remove_task`。让后台清理线程在
    10s 内自然回收任务，user feedback `result` 永远不会被这条路径误删。
    `test_close_completed_task_skips_remove` 锁住语义。
  - **客户端**：把 R17.4 的单次 retry 升级为指数退避多次 retry——
    `_FETCH_RETRY_BACKOFF_S = (0.0, 0.1, 0.25, 0.5, 1.0)`——覆盖典型的
    100ms-1s 网络抖动窗口。一旦任意一次 retry 命中 result：填 `result_box`
    → 跳过 close。全部 retry 失败：仍走原 R13·B1 ghost-task close 路径
    （但因服务端 short-circuit 保护，COMPLETED task 不会被误删）。
  - **同时修复**：`wait_for_task_completion` 把 TimeoutError 路径的
    `return` 改成 `timed_out` 标志位，避免 Python `try/except return`
    - `finally retry` 控制流陷阱（Python 语义下 except 的 return 把返回
      值锁定到 stack 上，finally 里的 retry 即便拿到真实 result 也无法
      覆盖返回值，用户反馈会被丢成 resubmit）。R165 写法让 retry 后的
      result 总能优先于 timeout 兜底响应。
  - 新增 `TestRetryBackoffSequenceR165`（2 个测试）覆盖多次抖动后救回
    result、退避序列结构 invariant；既有 `TestRetryFetchBeforeClose`
    - `TestCloseTask` 测试全部通过（共 9 个相关测试）；全测试 4898 passed
      0 failed。

### Added

- **R156** — Activity Dashboard logs-row **show 50 / show 5** toggle
  (CR#9 F-4 follow-up). R153 shipped the inline expand pinned at 5
  entries, but the `/api/system/recent-logs` endpoint already serves
  up to 50; operators investigating a known incident were forced into
  `curl` or a separate ops tool. R156 closes the gap with a sibling
  `[show 50]` / `[show 5]` toggle next to `[expand]`. The chosen
  limit is persisted to localStorage under a schema-versioned key
  (`aiia.activity_dashboard.logs_limit.v1`) so the preference
  survives reloads, mirroring R155's expanded-state pattern.
  - Constants exported on `window.AIIA_ACTIVITY_DASHBOARD`:
    `LOGS_LIMIT_DEFAULT = 5` / `LOGS_LIMIT_EXPANDED = 50` /
    `LOGS_LIMIT_LS_KEY = aiia.activity_dashboard.logs_limit.v1` /
    `LOGS_LIMIT_SCHEMA_VERSION = 1` /
    `ENDPOINT_RECENT_LOGS_BASE = "/api/system/recent-logs"`.
  - Allowlist-style `_readLogsLimit` returns `null` for any
    payload whose `limit` is not exactly LOGS_LIMIT_DEFAULT or
    LOGS_LIMIT_EXPANDED (defensive against future schema bumps that
    add a third value without a version bump); `_writeLogsLimit`
    coerces invalid inputs back to LOGS_LIMIT_DEFAULT.
  - `_pollOnce` builds the recent-logs URL dynamically:
    `ENDPOINT_RECENT_LOGS_BASE + "?limit=" + _state.logsLimit`.
  - Two new i18n keys (`settings.activityDashboardLogsShowMore` /
    `settings.activityDashboardLogsShowDefault`) — `en.json` and
    `zh-CN.json` already carry them; `check_i18n_orphan_keys.py`
    reports 0 orphan / 0 missing.
  - JS line budget bumped 900 → **1200** in
    `test_activity_dashboard_r152.py::test_js_under_1200_lines`
    to absorb R155 (≈ 70 LoC) + R156 (≈ 90 LoC). Same growth pattern
    R151 followed on `notification_test_button.js`.
  - New `tests/test_activity_dashboard_logs_show_more_r156.py`
    (124 assertions across 8 invariants: constants / API surface /
    allowlist / write coercion / F-5 schema-version equality /
    dynamic URL builder / state machine / button label cycling).
  - Full regression: 4904 passed 2 skipped 0 failed.

- **R148** — Notification self-test button **baseline-delta probe**.
  Root-cause fix for R147's "false-success" race: the user clicks at
  T=0, the dispatch delivers (`last_success_age` becomes 0); 8 seconds
  later they click again, the second dispatch is in flight, the probe
  runs at T=9.5s. R147's age-only logic saw `last_success_age = 9.5s
< 10s` and reported "delivered (9.5s ago, streak=N)" — but the
  _second_ dispatch hadn't actually completed. R148 fixes this by
  taking a **baseline snapshot** of per-provider stats _before_ the
  POST dispatch (separate `/api/system/health` GET, 1-second tight
  timeout), then comparing post-dispatch streak counters against the
  baseline. Each event resets the _opposite_ streak (success →
  `failure_streak=0`; failure → `success_streak=0`), so a single
  dispatch always increments exactly one streak counter — comparing
  `current.success_streak > baseline.success_streak` is therefore a
  reliable "did exactly one event happen between baseline and current?"
  signal. If the baseline fetch fails (network down / `/health` 5xx /
  timeout), we silently fall back to R147's age-only path so the R147
  contract is preserved. `verdict.source ∈ {"delta", "age"}`
  discriminator surfaces in the diagnostic blob for debug visibility.
  23 new test cases across 8 classes lock all three delta branches
  (success / failure / stale), the R147 fallback, the
  `ALL_KNOWN_PROVIDERS == server-side _HEALTH_PER_PROVIDER_KEYS`
  invariant, and the 1-second tight baseline timeout envelope.

- **R150** — Notification self-test button **history trail**. The
  settings panel now records every dispatch (success / warning /
  network-error) into a localStorage-backed "last 5 results" trail
  under the existing status + probe lines, modelled on uptime-kuma /
  healthchecks.io's "last N runs" UX. Collapsed-by-default toggle
  (`aria-expanded` button); expanded list is `role="log"` +
  `aria-live="polite"` so screen readers announce new entries without
  interrupting input. Each entry: relative time bucket
  ("just now / Xs ago / Xm ago / Xh ago / Xd ago"), verdict label
  ("delivered / warning / failed / unknown" colour-coded from the
  `--{success,warning,error}-500` semantic tokens), provider list,
  and an 8-character `event_id` chip. Schema-versioned storage key
  (`aiia.self_test.history.v1`) so a future bump can drop incompatible
  v1 payloads safely; defensive `_readStorage` write-probes localStorage
  and falls through to "no history" on Safari private mode / sandboxed
  iframes / quota-exceeded. Multi-tab sync via the standard
  `storage` event. DOM-XSS-immune renderer
  (`createElement` + `textContent`, no `innerHTML` paths). 41 new
  test cases across 11 classes lock the schema, helper signatures,
  exports, DOM safety, trigger wiring, init wiring, HTML a11y attrs,
  i18n completeness across en + zh-CN + \_pseudo, CSS class +
  semantic-token contracts, and the JS file line-count envelope
  (cap raised 900 → 1100 to fit ~150 LoC of helpers).

- **R152** — **Activity Dashboard** subsection in the settings panel.
  Collapsed-by-default `aria-expanded` toggle reveals a six-row `<dl>`
  aggregating live stats from four existing endpoints: `/api/tasks`
  (pending / active / completed / total), `/api/system/sse-stats`
  (emit_total / subscribers / heartbeat + P50/P95 emit→deliver latency),
  `/api/system/health` (overall status + per-provider notification
  streak summary), and `/api/system/recent-logs?limit=5` (warning /
  error / total counts). Same competitive class as
  uptime-kuma / healthchecks.io / grafana status-page tiles — closes
  the "I have to curl four endpoints to know if the agent is healthy"
  gap left open by R141-R150's server-side work. Polls every 5 s
  while open; pauses on `document.hidden` (saves battery on suspended
  laptops / backgrounded mobile tabs). AbortController-aware fetches
  fan out in parallel and fail per-row (other rows keep refreshing).
  Toggle is a real `<button>` with `aria-controls` + `aria-expanded`;
  rendered body is `role="region"` + `aria-labelledby` + `aria-live="polite"`.
  DOM-XSS-immune renderer (only `createElement` + `textContent`,
  per-field slice caps). Full `en` / `zh-CN` / `_pseudo` i18n
  coverage for 16 new keys. 52 new test cases across 11 classes
  lock the DOM-id ↔ HTML alignment, endpoint paths, poll window
  constants (default = 5 s, timeout = 4 s, min/max range = 1-60 s),
  full API surface (`_fetchJson` / six `_format*` helpers /
  `_render*` / `_ensureRow` / `_writeRow` / lifecycle), safety
  defenses (same-origin / non-OK / abort signal / text caps),
  HTML a11y attributes, i18n mustache-signature parity across
  locales, CSS class definitions including a "no unbound CSS vars"
  guard, and a < 900-line file-size envelope.

- **R153** — Activity Dashboard logs row **inline expand** + R152
  field-name bug fix. R152's `_formatLogs` read the recent-logs
  response under `logs.logs`, but `web_ui_routes/system.py::recent_logs`
  ships the array under `entries` (R52-B contract:
  `{"success": true, "count": N, "entries": [...]}`). Net effect in
  R152: the logs row was permanently `stale` whenever the endpoint
  responded. R153 corrects the field name (`logs.entries`) and
  reshapes the formatter return value from a plain string to
  `{ summary, entries }` so the row can render both the summary and
  an inline expanded list. Clicking the new `[expand]` link reveals
  the last `LOGS_TAIL_COUNT` (= 5) entries with `level` (colour-coded
  via `--warning-500` / `--error-500`), UTC `HH:MM:SS` (parsed via
  `indexOf('T')`-anchored offsets so a non-standard ISO falls back
  cleanly), and the message clipped to `LOG_MESSAGE_SLICE` (= 256)
  chars. Same a11y + DOM-XSS pattern as R146 / R150 / R152: real
  `<button type="button">` with `aria-controls` + `aria-expanded`;
  list `<ul>` is `role="list"` + `aria-live="polite"` + `[hidden]`.
  Idempotent re-render — every poll tick clears + rebuilds the list
  while preserving the user's expanded state. Three new i18n keys
  (`Expand` / `Collapse` / `Empty`) across `en` / `zh-CN` / `_pseudo`.
  38 new test cases across 10 classes lock the field-name bug fix
  (positive + negative assertions), the new return shape, the
  constants, the level → CSS-class mapping for WARNING / WARN /
  ERROR / CRITICAL / fallback → info, safety defenses (level slice,
  message slice via `LOG_MESSAGE_SLICE`, no `innerHTML`, idempotent
  list rebuild), a11y attribute set, i18n coverage, CSS class
  definitions, `_renderAll` dispatch for the logs row, the
  tail-slice expression, and the ISO timestamp slice expression.

### Changed

- **R149** — `release.yml` now pins `ovsx@0.10.9` for both the
  `verify-pat` and `publish` steps (was the floating `npx --yes ovsx`
  tag). The unpinned tag silently broke v1.6.1's Open VSX publish
  between v1.6.0 (2026-05-08, succeeded) and v1.6.1 (2026-05-10, the
  same code shape failed because ovsx tightened its
  `displayName` ↔ `vsixmanifest` cross-check). The displayName
  content fix landed in v1.6.2; R149 closes the **toolchain** root
  cause so a future ovsx tightening can't ship a green PR and a red
  release tag at the same time. Future upgrades go through a tracked
  PR (bump the pin → re-run release on a tag → either publishes or
  fails predictably). 5 new test cases (`tests/test_release_workflow_ovsx_pinned_r149.py`)
  reject any `npx --yes ovsx publish` / `verify-pat` invocation, demand
  strict semver pins, lockstep both invocations to the same version, and
  require a nearby explanatory comment.

- **R151** — Bumped `CLIENT_COOLDOWN_MS` 600 → 1500 in
  `notification_test_button.js`. After R147 + R148, the user-visible
  dispatch path is `baseline fetch (1s) → dispatch (variable) →
probe wait (1.5s) → probe fetch (5s)` ≈ 4–8s wall-clock; the
  600 ms client cooldown was effectively zero relative to the
  `button.disabled = true` window already covering the same path.
  1500 ms is the minimum useful budget that survives a panel re-mount
  (where `button.disabled` resets but `data-last-click-ts` survives
  via the DOM attribute round-trip), keeping the cooldown defensive
  rather than decorative. Drift guard
  `tests/test_notification_test_button_r146.py` already requires
  `CLIENT_COOLDOWN_MS >= 100`; the bump is in-range and forward-
  compatible.

- **R151** — `docs/troubleshooting.md` adds
  §"Open VSX `displayName` mismatch / pinned `ovsx` upgrade"
  documenting the manual upgrade flow for the R149 pin (run
  `npx --yes ovsx@<new-version> publish ...` against a dry VSIX in a
  scratch repo first; if it succeeds, bump both lines in `release.yml`
  in lockstep; the matching-pins test in
  `tests/test_release_workflow_ovsx_pinned_r149.py` catches any miss).

- **R154** — **CR#9 lesson:** R152's `_formatLogs` field-name regression
  motivated a new structural test suite —
  `tests/test_system_endpoint_payload_contract_r154.py` — that locks
  the four `/api/system/{health,sse-stats,recent-logs}` + `/api/tasks`
  response field names against the consumers in
  `static/js/activity_dashboard.js`. Any future rename on either side
  fails loudly at test-collection time rather than silently degrading
  one dashboard row to permanently `stale` (which is exactly how the
  R152 bug shipped past R152's own 52-case test suite). Also adds the
  troubleshooting §"Client/server payload field-name drift (R154
  lesson)" so the next contributor reading
  `docs/troubleshooting.md` knows why we lock both sides.

## [1.6.2] — 2026-05-10

> Patch release on top of v1.6.1. Adds R147 (notification self-test
> button now probes `/api/system/health` post-dispatch and renders a
> per-provider delivery verdict directly under the button — closes the
> "triggered ≠ delivered" gap left open by R146) and ships the
> displayName fix needed to unblock the Open VSX publish step (v1.6.1's
> Open VSX job was rejected because `ovsx publish` started strict-
> checking that `package.json.displayName` matches the resolved
> `<DisplayName>` element inside `extension.vsixmanifest`; v1.6.0 was
> fine, the toolchain shifted underneath us).
>
> No API changes. 4663 tests pass (2 skipped); ci_gate exit 0.

### Added

- **R147** — Notification self-test button **post-dispatch health
  probe**. Builds on R146: clicking _Send system self-test_ still
  triggers the R141 endpoint, but now — when the dispatch succeeds and
  `providers_dispatched` is non-empty — the button waits 1.5 seconds
  (Bark RTT headroom; local providers are microsec-fast) and then
  fetches `GET /api/system/health` once with a 5-second timeout, reads
  `body.checks.notification.per_provider`, and renders a verdict line
  directly under the main status: `bark: delivered (1.4s ago,
streak=3)` / `bark: failed (5xx_server_error, streak=1)` /
  `sound: stats stale — try again` / `system: skipped
(not_registered)`. Probe failures (network down / non-200 / non-
  JSON / abort) silently clear the line so the main "triggered N
  providers" message stays the user's source of truth. The whole probe
  is awaited so frantic re-clicks can't overrun an in-flight probe
  (preserves R146's idempotent contract).

  Decision tree picks the freshest of `last_success_age_seconds` /
  `last_failure_age_seconds` so a dispatch that hit a 5xx is _not_
  falsely reported "delivered". 6 new i18n keys (`systemTestProbing`
  / `systemTestProbeProvider{Success,Failure,Stale,Skipped,Unknown}`)
  with full `en` / `zh-CN` / `_pseudo` coverage. Server contract
  pinned in tests so a future `notification.stats.per_provider` rename
  would fail loudly rather than silently degrade every probe to "stale".
  41 new test cases across 8 classes.

### Fixed

- **VSCode extension Open VSX publish** — `package.json.displayName`
  hard-coded to `"AI Intervention Agent"` (was the NLS placeholder
  `"%displayName%"`). `ovsx publish`'s recent strict-check rejected
  the placeholder vs the resolved value inside `extension.vsixmanifest`
  ("Display name in extension.vsixmanifest and package.json does not
  match"), which broke the v1.6.1 Open VSX publish job. v1.6.0 had
  been fine; the toolchain tightened between releases. VS Code
  Marketplace + the activity-bar / view-container / commands stay
  localised because those still drive through `%key%` placeholders.
  Drift guard `tests/test_vscode_displayname_literal_for_ovsx.py` locks
  the literal in `package.json` + both NLS bundles + a defence-in-depth
  scan that catches any future re-introduction.

## [1.6.1] — 2026-05-10

> Cycle-3 → Cycle-6 round-up on top of v1.6.0: 4 new endpoints
> (R125 export / R141 self-test / R132 build-info / R134 latency),
> 9 new UI modules (R130-R131d quick-phrases / R125b export
> button / R137-R140 textarea polish / R144 cheatsheet / R146
> notification self-test button), R141-R145 full notification
> observability triad (per_provider stats + 6-class
> last_error_class + success/failure streaks), 15-commit silent-
> failure audit batch (R107-R120), and 3 security fixes (R111
> GitHub PAT scrubbing / R112 static-route ext whitelist / R122
> image MIME unification).
>
> No removed APIs. All R53-F / R72 / R76 / R77 contracts
> preserved. 4621 tests pass (2 skipped); ci_gate exit 0;
> ruff / ty / dead-key / param-signature linters all clean.

### Added

- **R121-A** — `/api/system/health` endpoint **observability expansion**
  for K8s liveness/readiness probes and monitoring dashboards. The
  R53-F three-check baseline (sse_bus / task_queue / recent_errors)
  was sufficient for "service alive?" but missed three signals that
  on-call routinely needs: which version is running, has the process
  just restarted, did the right config get loaded? R121-A adds these
  without breaking any R53-F contract.

  **What's new**:
  1. **New `notification` sub-check** in `payload.checks.notification`:
     `{ok, enabled, providers_count, queue_size,
delivery_success_rate, events_finalized, events_in_flight}`.
     Source: extracted from `notification_manager.get_status()` via
     `_safe_notification_summary()`, which **strips** the `config` /
     `providers` / `stats` sub-trees (those carry tokens / Bark
     secrets / latency histograms — not appropriate for a public
     health endpoint).

  2. **New top-level `version` field** — reads `pyproject.toml`
     project.version via the existing `web_ui.get_project_version()`
     `lru_cache`. Lets monitoring tell apart instances during a
     rolling upgrade.

  3. **New top-level `uptime_seconds` field** — derived from
     `server._PROCESS_STARTED_AT_UNIX` (already tracked since R47).
     Lets monitoring detect "process keeps restarting" /
     "init phase hanging" without needing OS-level metrics.

  4. **New top-level `config_file_path` field** — the absolute path
     of the currently loaded config file (path only, **never values**).
     Same data that `/api/system/open-config-file/info` already
     exposes, surfaced here for monitoring to detect "wrong config
     loaded" failures (typical: env var drift, mis-pointed mount).

  5. **`status` decision evolves** — `degraded` is now also triggered
     when notifications are enabled, have ≥30 finalized events
     (sample-size guard against cold-start false positives), and
     delivery success rate < 80% (empirical threshold balancing
     sensitivity vs. flakiness).

  **R53-F contract preservation**: The static test
  `test_no_config_value_passthrough` (R53-F) asserts the handler
  body does not literally contain `get_config()`. R121-A reads the
  config file path via the module-level helper
  `_safe_config_file_path()`, keeping the literal call out of the
  handler. The original `test_payload_carries_no_sensitive_fields`
  in `test_web_ui_routes_system.py` was updated from a strict
  three-key set-equality assertion to a six-key whitelist subset
  check + per-field non-sensitivity type assertions — **stronger**
  (catches both unauthorized new fields and dict/list payloads
  that could smuggle config values), not weaker.

  **Why now**: After R47 (SSE stats), R52-B (recent-logs ring),
  R53-F (system_health aggregator), R117-R119 (silent-failure
  observability), the only remaining "what's the system doing
  right now?" gap was the three signals R121-A adds. With this,
  a single GET to `/api/system/health` returns enough metadata to
  power a Datadog / Grafana single-pane dashboard without
  per-instance polling of 5+ separate endpoints.

  **Files**:
  - `src/ai_intervention_agent/web_ui_routes/system.py` — 4 new
    module-level `_safe_*()` helpers (each exception-safe with
    None fallback) + extended `system_health()` handler + updated
    OpenAPI docstring.
  - `tests/test_system_health_r121.py` (NEW, 47 tests) — covers
    new fields presence, helper unit tests (happy + 5 exception
    paths), R53-F contract preservation, payload structure
    contract.
  - `tests/test_web_ui_routes_system.py` — `test_payload_carries_no_sensitive_fields`
    evolved to allow R121-A schema while strengthening type assertions.

  **Verification**: 4015 tests passed / 0 failed / 2 skipped,
  ruff/ty clean.

- **R120** — codify the R107 → R110 → R114 → R117 → R118 → R119
  silent-failure audit work as a **machine-executable regression
  guard**. Future `except Exception: pass` patterns introduced
  anywhere in `src/` will fail CI unless the contributor:
  (1) documents the rationale in a new R-series CHANGELOG entry;
  (2) adds an inline `[R-XXX]` source marker; and
  (3) explicitly regenerates `tests/data/silent_failure_baseline_r120.json`
  via `uv run python scripts/silent_failure_audit.py update-baseline`.

  Background: R107-R119 audited the project bare-except pattern by
  hand (~21 → 27 documented intentional silences). Without machine
  enforcement, the audit decays as contributors flow in/out — the
  next "small fix" can re-introduce an undocumented silent failure
  and nobody notices for months. R120 lifts the audit doctrine
  from "memory" into "compile-time enforcement" so the R-series
  investment compounds across years.

  **Components**:
  1. **`scripts/silent_failure_audit.py`** (NEW) — AST-based
     scanner with three CLI commands:
     - `list` — prints every `except Exception: pass` site in
       `src/` (file:line + qualified name like
       `ClassName.method_name`), for human audit.
     - `check` — diffs current sites against the JSON baseline;
       exits 1 if any site is added or removed.
     - `update-baseline` — rewrites the JSON baseline from
       current scan; intended for human-reviewed PR submission,
       NOT for CI.

  2. **`tests/data/silent_failure_baseline_r120.json`** (NEW) —
     the approved baseline of 27 documented intentional silent-
     failure sites (1 per `(file, qualified_name)` fingerprint
     so adding a comment / reordering functions doesn't cause
     false-positive diff). JSON format with `_doc` and
     `_how_to_update` fields explaining the contract.

  3. **`tests/test_silent_failure_regression_guard_r120.py`**
     (NEW, 6 tests) — wires the scanner into CI: - `test_baseline_file_exists_and_well_formed` — sanity:
     baseline JSON loadable, has all required fields. - `test_no_unapproved_silent_failures` — **CORE GUARD**:
     diff current scan vs baseline; fail with detailed
     remediation message if drift detected. - `test_baseline_count_is_not_silently_growing` — soft
     upper bound (≤30 sites); future audit policy violations
     (a wave of new "intentional" silences) get visible. - `test_scanner_handles_nested_except_handlers` — REGRESSION
     guard for the R120 scanner's own bug fix: pre-fix the
     scanner missed `except Exception: pass` nested inside
     outer `except SomeOtherException:` blocks (5 sites
     silently undercounted in R119's original 22 → 27 with
     the fix). - `test_scanner_excludes_pure_docstring_pattern` — REVERSE
     invariant: scanner must NOT match the literal `except
Exception:\npass` string when it appears inside a
     docstring (canonical false positive that grep would hit;
     AST sees only real code nodes). - `test_scanner_correctly_distinguishes_alias_form` —
     defines the scanner's semantic edge: `except Exception:
pass` is matched, but `except Exception as e: pass` is
     NOT (alias form usually carries `logger.error(..., e)`,
     different anti-pattern not in scope of R120).

  **AST-vs-grep design rationale**: R119's
  `tests/test_silent_failure_audit_r119.py` already discovered
  that `grep "except Exception: pass"` produces false positives
  matching docstring text (R117/R118/R119 themselves include the
  literal pattern in their explanation comments). R120 standardizes
  on AST + qualified-name fingerprint to eliminate both grep noise
  and lineno drift.

  **Test status**:
  - `tests/test_silent_failure_regression_guard_r120.py`: 6/6 passed
  - Full suite: 3982 passed, 2 skipped, 0 warnings-as-errors
  - ruff check: All checks passed (after one auto-fix for in-function
    `import tempfile` placement)

  **Cumulative R-series silent-failure audit milestone**:
  - R107-R110: tests-layer silent-skip cleanup
  - R114: notification-shutdown TOCTOU
  - R117: notification_providers + notification_manager observability
  - R118: service_manager observability (3 fixes + 1 documented exclusion)
  - R119: web_routes / mDNS / network_security observability
    (4 fixes + 4 documented intentional silences)
  - **R120: machine enforcement of the audit policy itself**

  Future R-series silent-failure work no longer needs project-wide
  re-scans — the regression guard surfaces drift automatically.

### Added

- **R146** — **(UX / Ops self-service)** Settings 面板 **Test functions**
  分组新增 `Send system self-test` 按钮，把 R141-R145 整套通知可观测
  能力从 `curl` only 升级为「点一下就能验证」。

  **背景与缺口**：R141 把 `POST /api/system/notifications/test` 落成
  endpoint；R142 / R143 / R145 在 `GET /api/system/health` 把 per-
  provider stats / `last_error_class` / `success_streak` /
  `failure_streak` 全部铺开。直到 R145 为止，唯一触发途径还是
  `curl /api/system/notifications/test`——运维 / Datadog dashboard
  OK，但**用户改完 Bark / desktop / sound 配置后想"试一下"得开终端**，
  体验断层。R146 闭口：在 settings 面板 Test functions 子组里加一个
  `Send system self-test` 按钮，点击 → POST endpoint → 在按钮下方的
  `setting-status-line` 实时显示结果。

  **响应矩阵覆盖 7 路径**：
  - 200 + `success=true` → `"Triggered N provider(s): bark, web
(event_id=...)"`（绿色，`--success-500`）
  - 200 + `success=false` + 含 `disabled`/`enabled=false`/
    `notification.` 关键字 → `Notifications disabled in config:
{{reason}}`（橙色，`--warning-500`）
  - 200 + `success=false` + 其他 → `No providers enabled —
check notification.bark/web/sound/system_enabled`（橙色）
  - 429 → `Too many self-tests — please wait a minute`（橙色，
    服务器 6/min Flask-Limiter 限流的客户端友好版本）
  - 4xx 其他 → `Self-test failed: {{error}}`（红色）
  - 5xx + `error=notification_unavailable` → `Notification system
unavailable`（红色）
  - 5xx 其他 + 网络错误 / AbortError → `Network error / Self-test
failed: {{error}}`（红色）

  **i18n 路径**：所有 user-facing 字符串走 `window.AIIA_I18N.t(key,
params)`——**`_classifyResponse` 内部每个分支都用字面量 key**
  调用 `_t(...)`，让 `test_runtime_behavior.py::TestI18nDeadKeys` 静
  态分析能 grep 到（动态 key 派发会让所有 key 静默掉进 dead-key 黑
  洞）。Provider 列表用 `i18n.formatList` 渲染，自动适配 locale 的
  「and / 、」分隔符。

  **PII / 安全**：
  - 服务端 message 截断 200 字符；event_id 截断 64 字符——避免
    runaway error string 撕破 status-line 布局。
  - 只读 endpoint，不修改任何 config；6/min 限流来自 R141。
  - 客户端 600 ms cooldown（`data-last-click-ts` 时间戳挂在 DOM
    上，节点 re-mount 也保留）+ `button.disabled` 双重防 double-click。
  - 60 s `AbortController` 硬超时，避免 hung connection 永久禁用按钮。

  **idempotent**：
  - `init` 二次调用走 `data-r146-bound` sentinel attribute
    short-circuit；handler 永远只挂一次。
  - `triggerSelfTest` 进入时检查 `button.disabled` +
    `_isOnCooldown(button)`，flight 中的请求不会被打断。
  - `finally` 块强制 `button.disabled = false`——网络异常 /
    AbortError / 服务器 500 后按钮一定能重新点击，永远不会卡死。

  **改动**：
  - `src/ai_intervention_agent/static/js/notification_test_button.js`
    （新增，~270 行）：常量 / `_t` / `_formatProviderList` /
    `_setStatus` / `_classifyResponse` / `_isOnCooldown` /
    `_stampClick` / `triggerSelfTest` / `init`；window export
    `AIIA_NOTIFICATION_TEST_BUTTON`。
  - `src/ai_intervention_agent/templates/web_ui.html`：Test
    functions 子组里 desktop notification 按钮之后插入 R146 按钮 +
    `aria-live="polite"` 状态行 + i18n hint；`<script>` 标签带
    `defer` + `nonce` + `?v={{ notification_test_button_version
}}`。
  - `src/ai_intervention_agent/web_ui.py`：
    `_get_template_context` 加 `notification_test_button_version`
    走 `_compute_file_version`。
  - `src/ai_intervention_agent/static/css/main.css`（+33 行）：
    `.setting-status-line` 类系列（pending / success / warning /
    error）颜色用 `--success-500` / `--warning-500` /
    `--error-500` 项目语义 token，自动跟随 light/dark 主题。
  - `src/ai_intervention_agent/static/locales/{zh-CN,en}.json`：
    10 个 keys（`settings.testSystemBtn` / `testSystemHint` /
    `systemTestSending` / `systemTestSuccess` /
    `systemTestNoProviders` / `systemTestDisabled` /
    `systemTestRateLimited` / `systemTestUnavailable` /
    `systemTestNetworkError` / `systemTestFailed`）；
    `systemTestSuccess` 用 ICU plural（`{count, plural, one {#
provider} other {# providers}}`）保证英文不出 `1 providers`。
  - `src/ai_intervention_agent/static/locales/_pseudo/pseudo.json`：
    自动重新生成。
  - 静态资源：JS minify 产物 + br/gz 预压缩自动重生。
  - `tests/test_notification_test_button_r146.py`（新增，54 cases）：
    JS 文件 / 常量 / API surface / fetch 路径（POST + Content-Type
    - body + credentials + AbortController + finally
      button.disabled）/ classifyResponse 完整状态机矩阵 / HTML 集成 /
      template_context 注入 / i18n 双 locale + pseudo / CSS 4 状态色
      用 token / idempotent + cooldown 守卫。

  **Verification**: 54 R146 tests passed + R140-R145 系列 242 个相关
  测试全部回归 clean；`ci_gate.py` exit 0；ruff / ty / dead-key /
  param-signature linter 全绿。Cycle-6 进度 5/5（R142-R143-R145-R144-
  R146 收口；R141 endpoint 真正 user-reachable）。

- **R145** — **(Observability)** R142 `per_provider` 子结构再扩 2 个互
  斥连续计数字段：`success_streak` / `failure_streak`——把"上一次
  事件后到现在为止，这家 provider 连续成功 / 连续失败了多少次"显式
  化。与 R142 `success_rate` / R143 `last_error_class` 形成完整可观
  测三件套：成功率答"长期健康度"、last_error_class 答"挂在哪一类"、
  streak 答"现在还在挂吗"。

  **为什么需要 streak**：`success_rate` 在样本足够大（≥30 events）
  时才稳定，对"突发性 incident"（一家 provider 瞬间全挂）反应迟钝
  ——成功率从 100% 掉到 80% 需要 6 次失败累积，这时候用户可能已经
  错过 N 个通知。`failure_streak` 是连续失败计数，**第一次失败立刻
  +1**，监控对 `failure_streak >= 3` 直接 alert 比"15 分钟成功率
  <X%"早 5-10 个 sample 识别故障。这是云原生告警的标准范式：
  Prometheus `increase()` / Datadog `count` 都鼓励直接对 streak
  做窗口聚合。

  **互斥语义**（隐式契约）：
  - 任何一次成功 → `success_streak += 1`；`failure_streak = 0`
  - 任何一次失败 → `failure_streak += 1`；`success_streak = 0`
  - 因此**同一 provider 同一时刻最多一个 streak > 0**——这让 dashboard
    上"哪些 provider 处于异常状态"一眼就能看出（`failure_streak > 0`
    那批就是）。

  **失败覆盖范围**：
  - 正常 `ok=False` 路径 → failure_streak ++
  - `provider_not_registered` 路径 → failure_streak ++（与
    `last_error_class=not_registered` 配套）
  - `provider.send()` 抛 exception 被 except 兜住 → failure_streak ++
  - 三条失败路径全覆盖，监控不会因为「这家 provider 还没注册」就
    miss 掉 incident。

  **PII / 安全边界**：streak 是**纯整数**，不含 `last_error` 字符串
  / URL / device_key / token 等任何敏感信息——与 R142 / R143 的边界
  保持一致。

  **后向兼容**：`_safe_per_provider_snapshot` 对**老版 stats**（没
  有 streak 字段）默认返回 `0 / 0`；对**非法类型**（字符串 /
  list）走 `try/except` 兜底返回 `0` 而非 raise——保证 K8s liveness
  探针在数据格式异常时也不 5xx。

  **改动**：
  - `src/ai_intervention_agent/notification_manager.py`：
    `_send_single_notification` 4 处 `providers.setdefault(...)`
    模板加 `"success_streak": 0, "failure_streak": 0`；success/
    failure/异常 3 条路径分别 ++ 自己的 streak 并把对方 = 0。
  - `src/ai_intervention_agent/web_ui_routes/system.py`：
    `_safe_per_provider_snapshot` 暴露 streak 两字段（`try/except`
    兜底非法值）；`system_health` 的 OpenAPI docstring 增加 R145
    字段说明（"streak 互斥 / 失败 3 路径覆盖 / 早期告警 vs 长期成
    功率"）。
  - `tests/test_notification_health_streak_r145.py`（新增，
    25 cases）：常量形状（streak 字段存在 + int 类型 + 非负）/
    后向兼容（缺字段 / None / 非法类型 → 0 不 raise）/ 互斥语义 /
    NotificationManager 真实 `_send_single_notification` 路径 5
    种场景（连续成功 / 连续失败 / success → failure reset / 长波动
    - recover / per-provider 互独立 / 异常路径计为失败 /
      not_registered 计为失败）/ PII 安全（json.dumps 不含原文本） /
      HTTP 集成（mock manager → `_safe_notification_summary` 返回
      含 streak）/ Swagger doc 字段验证。
  - `tests/test_notification_health_per_provider_r142.py`：
    `expected_keys` 从 9 → 11；`test_eight_keys_exact` 重命名
    `test_keys_match_contract_exact` 与 keys 数实际值脱钩。
  - `tests/test_notification_health_last_error_class_r143.py`：
    R143 dict-shape 整合测试 expected keys 同步加 streak 两字段；
    `test_nine_keys_exact` → `test_eleven_keys_exact`。

  **Verification**: 25 R145 tests passed + 294 涉及测试（R141/R142/
  R143/R121/notification_manager）回归全 pass，ruff/ty clean。

- **R144** — **(UX / Discoverability)** 键盘快捷键 cheatsheet 浮层
  ——把 R131d 的 `Alt+1..9` (Quick Phrases)、R140 的 `Ctrl+Enter
/ Enter / Shift+Enter` 等隐藏快捷键 discoverability 化。新用户
  不需要打开 source / changelog 也能看到「这个软件支持什么键」。
  与 GitHub / GitLab / Linear 的 `?` cheatsheet 是同一行业范式。

  **触发约束**：
  - 在任意 `input` / `textarea` / `select` / `contenteditable`
    都 **不 focus** 时按 `?` (Shift+/) 才弹浮层；textarea 里 `?`
    仍然是字符（不打扰键盘党正常输入）；
  - 修饰键过滤：`Ctrl+?` / `Cmd+?` / `Alt+?` 都不触发（避免
    与系统 / 浏览器既有快捷键冲突）；
  - 浮层打开后：`Esc` 关闭 / 点击半透明遮罩关闭 / 卡片内点击不冒泡
    （防误关）。

  **架构**：
  - 与 R140 / R131d 同款 capture-phase keydown listener
    （`addEventListener("keydown", ..., true)`），让本拦截器先拿到
    事件；
  - 6 条静态 SHORTCUTS 表（`? / Esc / Alt+1-9 / Ctrl+Enter / Enter
/ Shift+Enter`）；后续要加新快捷键直接扩 SHORTCUTS 数组 + i18n
    key；
  - 不依赖 localStorage（无状态 UI，每次都重新渲染）；可选未来扩
    "用户已看过 N 次"hint。

  **CSP / XSS 安全**：全部 `createElement` + `textContent`，零
  `innerHTML` / `insertAdjacentHTML`，与 R130 quick_phrases / R138
  charCounter 同款基线。

  **i18n / 复用既有 key**：
  - 复用：`shortcuts.helpTitle` / `shortcuts.showHelp` /
    `shortcuts.closeModal`（既有）；
  - 新增 6 个：`shortcuts.helpSubtitle` /
    `shortcuts.helpEscHint` / `shortcuts.quickPhrase` /
    `shortcuts.submitCtrlEnter` / `shortcuts.submitEnter` /
    `shortcuts.newline`——zh-CN + en + pseudo locale 全覆盖。

  **CSS 复用既有变量**：
  - `var(--bg-secondary, ...)` / `var(--text-primary, ...)` /
    `var(--border-primary, ...)` 等，与项目 R66 brand-color 护栏
    一致；
  - 480px 断点收紧 padding / key 字号，与 quick-phrases-mobile-r133
    同款响应式骨架。

  **改动**：
  - `src/ai_intervention_agent/static/js/keyboard_shortcut_help.js`
    （新增，~280 行）：IIFE 模块；`OVERLAY_ID`、`TRIGGER_KEY`、
    `SHORTCUTS` 三个常量；`_t` / `_resolveShortcutLabel`
    / `_renderShortcutRow` / `_buildOverlayDom` 几个 helper；
    `showOverlay` / `hideOverlay` / `isOverlayOpen` /
    `_shouldTriggerHelp` / `_isTypingTarget` 5 个公开 API
    （挂在 `window.AIIA_KEYBOARD_SHORTCUT_HELP`，方便单测）；
    capture-phase keydown listener。
  - `src/ai_intervention_agent/templates/web_ui.html`：加 R144
    `<script>` 块（`defer + nonce + ?v={{
keyboard_shortcut_help_version }}`）。
  - `src/ai_intervention_agent/web_ui.py`：`_get_template_context`
    新增 `keyboard_shortcut_help_version` 字段。
  - `src/ai_intervention_agent/static/css/main.css`：~120 行新样
    式，覆盖 overlay / card / kbd 显示 / 480px 响应式。
  - `src/ai_intervention_agent/static/locales/{zh-CN,en}.json`：
    新增 6 个 `shortcuts.*` key；pseudo locale 已 regen。
  - `tests/test_keyboard_shortcut_help_r144.py`（新增，31 cases）：
    JS 文件 / 常量 / API surface / HTML 集成（defer + nonce + 路径）
    / web_ui.py 上下文字段 / CSS 选择器（含 fallback 模式 + 480px
    响应式）/ i18n 全覆盖（新键 + 既有键复用） / 触发逻辑语义
    （input/textarea/select/contenteditable 都视为 typing；ctrl/
    cmd/alt 修饰键过滤）/ DOM 安全（无 innerHTML / insertAdjacentHTML
    - ≥5 个 createElement）/ i18n graceful degradation（缺 t() /
      抛错走 fallback；t 返回 key 自身视为缺失）/ capture phase 监听。

  **R144 实施期间发现并修复的细节**：
  - CSS 初稿用 `var(--border-color, ...)` —— 项目里没定义这个变量
    （只有 `--border-primary` / `--border-secondary` 等）。
    `test_runtime_behavior.py::test_css_self_referencing_vars_defined`
    回归测试立刻 catch 到，改用 `--border-primary` 后修复。这条
    case 印证了 R66 / runtime CSS 整合性测试的价值。

- **R143** — **(Observability)** R142 `per_provider` 子结构新增第 9
  字段 `last_error_class`——把 NotificationManager 写入的 `last_error`
  字符串归一化成 6 个稳定字符串之一，与 `last_error_present` boolean
  互补：boolean 答「上次最近一次失败有 / 没有 error 信息」，class 答
  「是哪一类」。监控 dashboard 可基于此做 stack-bar：「这个 provider
  最近 N 次失败，4xx / 5xx / network / timeout 各占多少」，比单 boolean
  信号丰富 5 倍。

  **6 类取值**（`_HEALTH_ERROR_CLASS_VALUES` 常量）：
  - `client_error`：4xx HTTP / 设备密钥错 / 鉴权失败
  - `server_error`：5xx HTTP / Bark / 推送平台自身故障
  - `network_error`：connection refused / DNS 失败 / 网络中断
  - `timeout`：请求超时
  - `not_registered`：provider 没在 NotificationManager 注册（线上
    line 1046 的固定哨兵）
  - `unknown`：无法归类的字符串（兜底）
  - `None`：当且仅当 `last_error_present=False`

  **优先级层次** —— 5xx > 4xx > timeout > network > not_registered >
  unknown，避免一个 error 同时落多类。`"{'status_code': 504, 'detail':
'Gateway timeout'}"` 即使含 timeout 字样仍归 `server_error`，因为
  HTTP layer 的明确信号比 transport layer 关键字更可信。

  **PII 安全边界（继续）**：
  - `_classify_last_error` 只检模式特征（HTTP status code regex /
    关键字），返回的字符串永远是 6 个常量之一，**绝不返回 last_error
    原文本片段**；
  - 测试用 `device_key=SECRET_KEY_DO_NOT_LEAK` /
    `BARK_TOKEN_LEAKED` / `api.day.app/SOMETOKEN` 等真实 PII 串作
    回归断言，`last_error_class` 输出永不含这些子串；
  - 与 R142 的 `last_error_present` 共同维护"健康端点不漏 PII"的契约。

  **Status code regex 设计**：
  - 第一条：`'status_code': NNN` —— Bark dict repr 的固定模式；
  - 第二条：`HTTP NNN` / `http/1.1 NNN` —— 自由文本中的明确 HTTP
    上下文；
  - 第三条：`^NNN <文字>` 开头的 `500 Internal Server Error` 这种
    常见格式；
  - **不做** 裸 3 位数字搜——避免 `"Connection refused on port 443"`
    中的 `443` 被误判为 4xx。这是 R143 实施期间发现并修复的 false-
    positive，回归测试 `test_connection_refused_yields_network` pin
    住此契约。

  **改动**：
  - `src/ai_intervention_agent/web_ui_routes/system.py`：新增常量
    `_HEALTH_ERROR_CLASS_VALUES`、helper `_classify_last_error`；
    扩 `_safe_per_provider_snapshot` 注入 `last_error_class`；
    health endpoint Swagger doc 加 R143 字段说明。
  - `tests/test_notification_health_per_provider_r142.py`：
    `expected_keys` 加 `last_error_class` 变 9 个 key。
  - `tests/test_notification_health_last_error_class_r143.py`（新增，
    37 cases）：常量值集合 / None 与空串 / HTTP status code 映射
    （4xx → client / 5xx → server）/ provider_not_registered 哨兵 /
    timeout 关键字 / network 关键字 / 优先级（5xx > timeout） / 无
    法归类 → unknown / PII 边界（device_key / Bark URL / token） /
    snapshot 集成（present=True ↔ class!=None；9-key 形状） /
    health endpoint HTTP 集成（per_provider.last_error_class 取值范
    围）/ Swagger doc 提及 R143 + 6 类标识 + 优先级。

- **R142** — **(Observability)** `/api/system/health` 端点暴露
  per-provider stats 摘要 —— R141 的 self-test 触发后能"看到了"，但
  R121-A 只暴露了**全局** delivery_success_rate，故障定位时回答不出
  "是 Bark 挂还是 Web 挂"。R142 把 NotificationManager 内部已经按
  provider 维度记录的 `stats.providers.{type}` 在保留同款安全边界
  的前提下重新放出，与 R141 形成「触发 → 定位」闭环。

  **新增字段** `checks.notification.per_provider`（dict, 4 个 stable
  key：bark/web/sound/system）：
  - 每家 provider 的结构 `{attempts, success, failure, success_rate,
avg_latency_ms, last_success_age_seconds,
last_failure_age_seconds, last_error_present}`；
  - 未注册 / 没投递过的 provider 返回 `None`，dashboard 用 stable
    key 集合不会有 KeyError；
  - `success_rate` / `avg_latency_ms` 透传 NotificationManager 已
    经计算好的浮点；attempts=0 / latency_count=0 时是 `None`；
  - `last_*_age_seconds` 用 `now - last_*_at` 算 age，避免绝对时
    间戳跨副本/跨时区无意义；时钟回拨 → clamp 0 不出现负值。

  **PII 安全边界（必须）**：`last_error` 原文本 **绝不暴露**。Bark
  的 `last_error` 来自 BarkProvider 写到 `event.metadata
["bark_error"]` 的运行时字符串，虽然 NotificationManager 内已
  truncate 到 800 字符，但仍可能含 device_key / 服务器 URL / Bark
  token 这种不希望出现在公共健康端点的内容。R142 改成
  `last_error_present: bool` —— 告诉调用方"最近一次失败有没有
  error 信息"，详情仍然要回 logs 看。`test_last_error_string_not_in_output`
  以 `device_key=SECRET_KEY_123` / `BARK_TOKEN_X` /
  `api.day.app` 等真实 PII 串作回归断言，整个 health 返回值
  stringify 后的任何片段都不应含有这些子串。

  **设计决策**：
  1. **不引入新 stats 字段**——所有数据 NotificationManager 内已经在
     算（line 1488-1502 的 success_rate / avg_latency_ms 派生），R142
     只是 health 端点的 read-side projection。零新 lock / 零新写路径
     / 零额外存储开销。
  2. **stable 4 key 而非动态 list**——监控 dashboard 写模板时按 key
     固定列布局更稳；如果 NotificationType 未来新增第 5 家（如
     Telegram / Slack），加 `_HEALTH_PER_PROVIDER_KEYS` 常量即可，
     不破老 dashboard。
  3. **age 而非绝对时间戳**——多副本部署里绝对时间戳因机器时钟漂移
     不可比，age 是更稳定的语义。
  4. **rate-limit 不变**——120/min 已经够 K8s probe 用，不上调。

  **改动**：
  - `src/ai_intervention_agent/web_ui_routes/system.py`（+~80 行）：
    新增 `_HEALTH_PER_PROVIDER_KEYS` 常量、`_safe_per_provider_snapshot`
    helper；扩 `_safe_notification_summary` 注入 `per_provider`；
    health endpoint Swagger doc 加 R142 字段说明。
  - `tests/test_notification_health_per_provider_r142.py`（新增，
    29 cases）：keys/shape / 未注册→None / 8-key 形状 / success_rate
    与 avg_latency_ms 计算 / age 单调性 / 时钟回拨 clamp 0 / PII 安
    全边界（device_key / 服务器 URL / token 不泄漏）/ 异常 stats 类
    型 fallback / health endpoint HTTP 集成 / Swagger doc 提及 R142
    - per_provider + last_error_present + PII 字样 + 常量名。

- **R141** — **(Observability / Ops)** 通知系统 self-test endpoint
  `POST /api/system/notifications/test`——R141 之前要验证「线上
  NotificationManager 配的 Bark / Web / Sound / System provider 真能投
  得出去」只能：等真实任务触发（慢、不可控）、点设置面板「测试
  Bark」（`/api/test-bark` 是 **配置阶段** 验证：参数从 form 传，
  不能验证当前生效配置）、SSH 上去 `curl` notification_manager
  （运维不友好）。R141 落地一个 **运行阶段** 的 self-test：
  - **路由**：`POST /api/system/notifications/test`，rate-limit
    `6 per minute`（防止被滥用做 push spam，但留够运维 / Sentry /
    Datadog probe 的余地）。
  - **请求体**（可选）：`{"provider": "all"|"bark"|"web"|"sound"|
"system", "title": "...", "message": "..."}`。`provider` 缺
    省 / 留空 / `"all"` 都触发当前已 enable 的全部 provider；
    指定单一 provider 只触发该家。`provider` 大小写不敏感、自动
    trim。`title` / `message` 可自定义；缺省 `"System
self-test"` + 带时间戳的 default body。
  - **响应**：`{success, event_id, providers_dispatched, message}`。
    `providers_dispatched` 是实际触发的 `NotificationType.value`
    list（如 `["bark","web"]`）；调用方结合 `GET /api/system/
health` 的 `checks.notification.stats` 字段查看真实投递结果
    （send_notification 是异步的，本 endpoint 不等结果）。
  - **优雅降级**：`config.enabled=false` / 指定 provider 未 enable
    / 全部 provider 都关 → 200 + `success=false` +
    `providers_dispatched=[]` + 解释 message，不调
    `send_notification` 也不当作 5xx；`send_notification` 抛异
    常 → 500 + `error="dispatch_failed"` + i18n message（不外泄
    堆栈）；`notification_manager` 不可用 → 500 + `error=
"notification_unavailable"`。
  - **元数据 marker**：`send_notification` 的 metadata 自动注入
    `{r141_self_test: true, provider_param: <raw>}`，下游 provider
    可识别并区分 self-test 与真实任务通知（例如 Bark 端可在 title
    上加 `[selftest]` tag、或跳过新任务 url 跳转逻辑）。
  - **rate limit 选 6/min 而非更宽**：与 `/api/test-bark`
    （30/min，配置阶段需要快速试错）拉开档位。运维 / 监控 probe
    实际跑 1/min 已经过度，6/min 留 6× 余量；同时阻断了「批量手
    动测试 spam push」的脚本攻击面。
  - **改动**：`src/ai_intervention_agent/web_ui_routes/
notification.py`（+~150 行）；`tests/
test_notification_self_test_r141.py`（27 cases，覆盖路由注册 /
    缺省 all / 单 provider / 大小写归一 / 非法 provider 400 /
    config.enabled=false / 单 provider 未 enable / 全关 / sound_mute
    排除 / send 抛异常 500 / manager 不可用 500 / 自定义 title&
    message 透传 / Swagger doc 字段）。

- **R140** — **(UX)** 反馈提交模式切换（Ctrl+Enter vs Enter）——既
  有 `app.js` 的 keydown handler 把 `Ctrl/Cmd+Enter` 硬编码为提
  交快捷键，纯键盘党 + 短文本反馈用户在 Slack / Discord / Notion /
  Telegram 等 IM 工具里用 Enter 提交是默认习惯，每次切回本应用都得
  "记住"用 Ctrl+Enter，认知负担非零。R140 在 settings 面板加一个偏
  好开关：
  - `ctrl_enter`（默认，与现状一致）：`Ctrl/Cmd+Enter` 提交，
    `Enter` 换行；
  - `enter`：`Enter` 提交，`Shift+Enter` 换行（IM 模式）；
    `Ctrl/Cmd+Enter` 仍然能提交（保留熟悉路径）。

  **设计决策**：
  1. **纯前端 localStorage** — 与 R137 / R138 / R139 同款架构，不
     上服务端 `user_settings`，多设备不同步是合理边界（submit
     mode 是纯客户端 UX 偏好）。Storage key
     `aiia.submitMode.v1`，envelope `{ schema_version, mode,
saved_at }`，未来 schema 升级有迁移空间。
  2. **不替换既有 keydown handler** — R140 在 `#feedback-text`
     textarea 上挂独立 capture-phase listener（`addEventListener
("keydown", handler, true)` 第三参数 true）。`ctrl_enter`
     模式下 listener 直接 return，不拦截让既有 `document.
addEventListener("keydown", ...)` 处理；`enter` 模式下
     `preventDefault` 阻止 textarea 默认换行 + 调
     `#submit-btn.click()` 触发提交，不直接访问 `submitFeedback`
     函数引用避免硬耦合。capture phase 让本拦截器先于 document-
     level keydown 跑，确保 `preventDefault` 在浏览器 newline 默
     认行为前生效。
  3. **IME composition 安全** — `_shouldSubmitOnEnter` 按
     `event.isComposing` + `keyCode === 229` 双重判断，让中日韩
     输入法 / emoji picker 用户在选词阶段按 Enter 不会误提交（IME
     选词 Enter 是确认候选，不是提交反馈）。`isComposing` 在某些
     老浏览器 / 边缘 IME 上不可靠，`keyCode 229` 是浏览器对 IME
     composition 的 fallback 标志。
  4. **修饰键放行** — Shift+Enter / Alt+Enter / Ctrl+Enter /
     Cmd+Enter 一律不命中 `_shouldSubmitOnEnter`：单 Shift 是默
     认换行 / 标准；Alt 是常用快捷键修饰符（Alt+1..9 来自 R131d）；
     Ctrl/Cmd+Enter 让既有 handler 处理（保留熟悉路径）。
  5. **disabled 守卫** — `_triggerSubmit` 检查 `btn.disabled`
     避免在加载 / 提交进行时重复触发；submit 按钮 disabled 状态由
     既有 app.js 维护，R140 复用不引入新状态机。
  6. **设置面板内联** — `<select id="feedback-submit-mode-
select">` 放在 settings panel 的 Feedback section 内，与既
     有 countdown / resubmit / suffix 设置项同级，select 切换后
     立即 `setMode(next)` 写盘，无需重新加载页面（既有 listener
     走 `getMode()` 实时读，不缓存模块状态）。
  7. **graceful failure** — `_isStorageAvailable` 用 set/remove
     probe 检测；`getMode` 在 storage 不可用 / corrupt JSON /
     schema_version 不匹配 / mode 非法（不在 `VALID_MODES` 中）
     时全部 fallback 到 `DEFAULT_MODE = "ctrl_enter"`，主路径不
     挂；`setMode` 拒绝非 `VALID_MODES` 输入避免污染存储。
  8. **CSP nonce + ?v= cache busting** — 与 R47 / R74 / R137 / R138
     / R139 同款 `<script defer nonce={{ csp_nonce }} src=...?v=
{{ feedback_submit_mode_version }}>` 节点。

  **实现**：
  - `src/ai_intervention_agent/static/js/feedback_submit_mode.js`
    （NEW，~165 行）—— 6 个常量（`STORAGE_KEY` /
    `SCHEMA_VERSION` / `DEFAULT_MODE` / `VALID_MODES` /
    `TARGET_ID` / `SUBMIT_BTN_ID`）+ 8 个公共 / 内部函数
    （`getMode` / `setMode` / `_shouldSubmitOnEnter` /
    `_triggerSubmit` / `_isStorageAvailable` /
    `setupKeydownInterceptor` / `setupSelectListener` /
    `init`），全 try/catch 兜底。
  - `src/ai_intervention_agent/templates/web_ui.html` —— settings
    panel 的 feedback section 内 `feedback-resubmit-prompt` 之
    后、`feedback-prompt-suffix` 之前新增一个 `<div class=
"setting-item">` 含 `<select id="feedback-submit-mode-
select">` + 两个 option（`ctrl_enter` / `enter`）+ hint 描
    述；文档底部 R139 之后新增 `<script defer>` 节点。
  - `src/ai_intervention_agent/web_ui.py` —— `_get_template_
context()` 加 `"feedback_submit_mode_version"`。
  - 三 locale 加 `settings.submitMode` /
    `settings.submitModeCtrlEnter` / `settings.submitModeEnter` /
    `settings.submitModeHint` 共 4 个 key（zh-CN / en /
    \_pseudo/pseudo.json，pseudo 自动重生成）。

  **测试**（`tests/test_feedback_submit_mode_r140.py`，39 cases /
  6 invariant classes）：
  1. **JS 文件存在 + 体积合理** — 文件存在 / 130-220 行 envelope。
  2. **常量值锁定** — 6 个常量字面值 + `VALID_MODES = ["ctrl_
enter", "enter"]` 数组顺序锁定。
  3. **API 函数签名** — 8 个函数 + `window.AIIA_FEEDBACK_SUBMIT_
MODE` 全 14 字段 export。
  4. **graceful failure / fallback** — `getMode` try/catch +
     schema_version 校验 + `VALID_MODES.indexOf` 校验，全部
     fallback `DEFAULT_MODE`；`setMode` 拒绝非法输入；
     `_isStorageAvailable` set/remove probe + try/catch。
  5. **keydown 拦截边界** — `_shouldSubmitOnEnter` 排除 non-
     Enter / Shift / Alt / Ctrl / Cmd / IME (`isComposing` +
     `keyCode 229`)；`setupKeydownInterceptor` 用 capture
     phase（第三参数 `true`）；`ctrl_enter` 模式下 listener
     直接 return；命中条件后 `preventDefault` + `_triggerSubmit`；
     `_triggerSubmit` 检查 `btn.disabled`。
  6. **HTML / context 集成 + i18n** — settings panel 含
     `<select id="feedback-submit-mode-select">` + 两个 option
     带 `data-i18n` / `<script defer nonce src=...?v=...>` /
     `_get_template_context` 注入 version / 三 locale 4 个 key
     全覆盖。

  **验证**：39/39 R140 + 全工程 4420 passed + 2 skipped；
  `uv run python scripts/ci_gate.py` exits 0；与 R138 / R139 同样
  6 个静态资产文件由 `scripts/minify_assets.py` +
  `scripts/precompress_static.py` 自动生成。

  **后续 follow-up（不在 R140 范围内）**：
  - **R140-A**：键盘提示在 textarea 周围动态显示当前 mode 的
    shortcut（如右下角 `⌘+Enter` 或 `Enter` chip），让用户一
    眼看到当前状态。
  - **R140-B**：服务端同步——通过 `user_settings` 后端 schema
    把 mode 同步到服务端，让用户多设备 / 多浏览器场景一致。

- **R139** — **(UX)** 反馈 textarea per-task 草稿持久化（autosave）——
  项目内已存在 `window.taskTextareaContents` 内存字典（`multi_
task.js` 维护，多任务并发场景下用户切换 task 时保留 textarea 内
  容不丢），但**仅在内存里**。一旦用户刷新页面 / 关闭浏览器 / 进
  程崩溃，所有 draft 全部丢失。`mcp-feedback-enhanced` v2.4.x 把
  "Auto-save drafts" 列入版本 highlight 是因为长 prompt 用户在拼接
  多段 LLM 输出 / 复制粘贴长技术文档时最怕 30 分钟手敲被刷新一键
  清零，autosave 让内容不再因刷新 / 崩溃而消失。

  **设计决策**：
  1. **不侵入 multi_task.js / app.js** — R139 走外挂监听（textarea
     `input` 事件 + `setInterval` 周期 reconcile），既有代码零
     改动，避免 1300 行 `switchTask()` / submit handler 引入回归
     风险。R139 模块仅追加，不修改任何 prod 路径函数体。
  2. **TTL 7 天 + LRU 50 task 双重容量约束** — draft 内容可能含敏感
     信息（API key / 密码 / 私聊片段），TTL 7 天让 stale draft 自
     动 expire；LRU 50 task 防止 storage 无界增长（典型用户 1-2 周
     内活跃 task ≤30，50 留充足缓冲）。`saved_at < cutoff` 时
     hydrate 跳过；超出 `MAX_DRAFTS` 时按 `saved_at desc` evict
     最旧。
  3. **input 事件 debounce 500ms 写盘 + 周期 30s reconcile** —
     `input` 事件 debounce 500ms 让用户输入后立即持久化（感知
     `<1s` 即落盘）；周期 30s `reconcileMemoryToStorage` 兜底程
     序赋值 / clear / submit 后清空等非 input 路径——避免漏一些
     `textarea.value = ""` 这种程序性 mutate（不触发 input 事
     件）。两路双写让 storage 与内存最终一致。
  4. **hydrate 不覆盖既存 entry** — `hydrateMemoryCache` 在
     DOMContentLoaded 触发时把 storage drafts merge 到 `window.
taskTextareaContents`，但用 `hasOwnProperty` 检查跳过既存
     项——避免与 `multi_task.js` 初始化阶段已经填充的 active task
     race。
  5. **schema_version envelope** — 与 R130 quick_phrases / R137
     textarea-height / R138 char-counter 同款 `aiia.<feature>.
v<schema>` 命名约定（`aiia.feedbackDrafts.v1`），未来 schema
     升级有迁移空间；schema_version 不匹配时 `_readEnvelope` 直
     接返回 null 给未来 v2 migrator 留接入空间。
  6. **空 text 自动 delete entry** — `saveDraft(taskId, "")` 不
     写空 text 占用 storage，而是从字典 delete；`reconcileMemory
ToStorage` 也跳过 text 空字符串——只持久化非空 draft。
  7. **CSP nonce + ?v= cache busting** — 与 R47 / R74 / R137 / R138
     同款 `<script defer nonce={{ csp_nonce }} src=...?v={{
feedback_drafts_version }}>` 节点，不违反项目级
     `script-src 'self' 'nonce-...'` 策略。

  **实现**：
  - `src/ai_intervention_agent/static/js/feedback_drafts.js`
    （NEW，~270 行）—— 7 个常量 + 8 个公共函数 + 6 个内部 helper：
    `loadAllDrafts` / `getDraft` / `saveDraft` / `clearDraft` /
    `clearAllDrafts` / `hydrateMemoryCache` /
    `reconcileMemoryToStorage` / `init` / 内部 `_now` /
    `_isStorageAvailable` / `_readEnvelope` / `_writeEnvelope` /
    `_normalizeDraft` / `_applyTtlAndLru` / `_getActiveTaskId` /
    `setupInputListener` / `setupPeriodicSync`，全 try/catch 兜底。
  - `src/ai_intervention_agent/templates/web_ui.html` —— 文档底部
    新增 `<script defer src="/static/js/feedback_drafts.js?v={{
feedback_drafts_version }}" nonce="{{ csp_nonce }}">` 节点。
  - `src/ai_intervention_agent/web_ui.py` —— `_get_template_
context()` 加 `"feedback_drafts_version": _compute_file_
version(...)`。

  **测试**（`tests/test_feedback_drafts_r139.py`，35 cases /
  6 invariant classes）：
  1. **JS 文件存在 + 体积合理** — 文件存在 / 200-330 行 envelope。
  2. **常量值锁定** — 7 个常量（`STORAGE_KEY` / `SCHEMA_VERSION` /
     `TARGET_ID` / `TTL_MS = 7*24*60*60*1000` / `MAX_DRAFTS = 50` /
     `INPUT_DEBOUNCE_MS = 500` / `SYNC_INTERVAL_MS = 30*1000`）；
     TTL_MS 与 SYNC_INTERVAL_MS 写成乘法表达式让 reviewer 一眼看到
     "7 天" / "30s" 约束。
  3. **API 函数签名** — 8 个公共函数 + `window.AIIA_FEEDBACK_DRAFTS`
     全 16 字段 export。
  4. **graceful failure / fallback** — `_isStorageAvailable` 用 set/
     remove probe + try/catch；`_readEnvelope` / `_writeEnvelope` /
     `clearAllDrafts` 全 try/catch；`_readEnvelope` 校验
     `schema_version`；`init` 在 storage 不可用时 return null。
  5. **核心逻辑边界** — `_normalizeDraft` 处理 non-object / 非
     string text / saved_at 缺失（默认 0 让 TTL 命中淘汰）；
     `_applyTtlAndLru` 先 TTL 过滤后 LRU 排序截 `MAX_DRAFTS`；
     `hydrateMemoryCache` 用 `hasOwnProperty` 不覆盖既存项；
     `saveDraft("")` 从字典 delete；`reconcileMemoryToStorage`
     跳过 empty text；`setupInputListener` 用 `setTimeout(...,
INPUT_DEBOUNCE_MS)` debounce。
  6. **HTML / context 集成** — `<script defer nonce src=...?v=...>` /
     `_get_template_context` 用 `_compute_file_version`。

  **验证**：35/35 R139 + 全工程 4381 passed + 2 skipped；
  `uv run python scripts/ci_gate.py` exits 0；与 R138 同样 6 个
  静态资产文件（`.js` + `.br` + `.gz` + `.min.br` +
  `.min.gz`，`.min.js` 由 `.gitignore` 排除）由
  `scripts/minify_assets.py` + `scripts/precompress_static.py`
  自动生成。

  **后续 follow-up（不在 R139 范围内）**：
  - **R139-A**：UI 显示恢复提示——load draft 时在 textarea 上方显
    示一个 dismissible toast "已恢复上次保存的内容（保存时间：YYYY-
    MM-DD HH:mm）"，让用户知道这是历史 draft 而非新输入。
  - **R139-B**：手动清除按钮——quick_phrases 区域加 "清除全部草稿"
    按钮调 `clearAllDrafts()`，应对用户主动想清掉所有持久化痕迹
    的场景。
  - **R139-C**：跨浏览器同步——通过 `user_settings` 后端 schema
    把 drafts 同步到服务端，让用户多设备 / 多浏览器场景一致。

- **R138** — **(UX)** 反馈 textarea 字符计数器——主输入框
  `#feedback-text` 右下角浮动小标签实时显示当前字符数，三段阈值
  变色（默认 → 橘 `warn` → 红 `danger`），让"输入长度"这条不可
  见维度变显式。`mcp-feedback-enhanced` v2.4.x 把 character counter
  列入版本 highlight 是因为长 prompt 用户在拼接多段 LLM 输出 / 复
  制粘贴长技术文档时常常超出心理预期，counter 让其可观测，避免误
  超出后端 / Bark 通知的隐性 size 约束。

  **设计决策**：
  1. **advisory 而非 enforced** — counter 仅做视觉提示，textarea 上
     **不加 maxlength** 属性（避免截断用户内容造成数据丢失）；阈值
     与项目内既有 `feedback-resubmit-prompt` / `feedback-prompt-
suffix` textarea 用的 `maxlength="10000"` 隐性约定对齐。
  2. **三段阈值变色** — `WARN_THRESHOLD=8000`（橘）/
     `DANGER_THRESHOLD=10000`（红）/ `count == 0` 时整体隐藏
     （避免空 textarea 时显示 `0` 喧宾夺主）。色系走项目现有的
     `--warning-500` / `--error-500` 色板 token，与 R66 品牌色
     护栏一致，不引入硬编码 hex。
  3. **空状态隐藏 + `aria-live="polite"`** — count 0 时
     `hidden` 属性原生隐藏（display: none 不占位）；非 0 时
     polite live region 让屏幕阅读器只在用户停顿时念字数，不打断
     主流程；不用 `assertive` 避免每次输入都触发朗读。
  4. **input 事件 + 初始化双触发** — 监听 `input` 事件涵盖
     paste / cut / drag / IME composition end 全场景；初始化时调
     一次 `updateCounter` 应对 R137 height restore + 外部
     setValue + 表单回填等非 input 事件路径下的非空初始值。
  5. **`Intl.NumberFormat` 千位分隔** — 8000 → `8,000` /
     `8 000` 视 locale 适配；`Intl.NumberFormat` 不可用 / 抛异
     常时静默 fallback `String(count)`，主路径不挂。
  6. **`textarea.value.length`** — UTF-16 code unit 计数，与后
     端 `len(feedback_text)` 计算口径一致；不做 grapheme cluster
     split（即不引入 `Intl.Segmenter` 增加 polyfill 体积），对
     warning 阈值精度无实质影响。
  7. **i18n 走 `_t` 模块内 helper + 字面 key 调用** — 与
     `quick_phrases.js` / `app.js` 同款实现，让 i18n orphan /
     dead-key 扫描器（`scripts/check_i18n_orphan_keys.py::
JS_T_CALL_RE` 用 `(?<![.\w])(?:_?tl?|...)\(\s*['"]...`
     regex）能匹配字面 key 调用，避免常量 `I18N_KEY` indirect
     调用让扫描器漏识别造成 dead key 误报。FALLBACK_TEXT 用英文
     与项目级 base locale 对齐（`test_i18n_js_no_hardcoded_cjk`
     护栏：JS 内禁中文字面值，CJK 必须走 locale 文件）。
  8. **`pointer-events: none` + `user-select: none`** — counter
     不拦截 textarea 滚动 / 选区拖拽 / 自带 resize handle 等交互；
     不可选中避免误复制计数器；`font-variant-numeric: tabular-
nums` 等宽数字让计数跳秒不抖动。
  9. **CSP nonce + ?v= cache busting** — 与 R47 / R74 / R137 同款
     `<script defer nonce={{ csp_nonce }} src=...?v={{ feedback_
char_counter_version }}>` 节点，不违反项目级
     `script-src 'self' 'nonce-...'` 策略；
     `_compute_file_version` 让 immutable cache 在改 JS 后立即
     失效。

  **实现**：
  - `src/ai_intervention_agent/static/js/feedback_char_counter.js`
    （NEW，~145 行）—— 7 个常量 + 6 个公共函数（`_formatCount` /
    `_resolveLabel` / `_applyThresholdClass` / `updateCounter` /
    `init` + 模块内 `_t` helper），全 try/catch 兜底。
  - `src/ai_intervention_agent/templates/web_ui.html` —— textarea-
    container 内加 `<span id="feedback-char-counter" aria-live=
"polite" hidden>` + 文档底部新增 `<script defer>` 节点。
  - `src/ai_intervention_agent/static/css/main.css` —— 加 `.
feedback-char-counter` 主选择器（绝对定位 right/bottom + 等宽
    数字 + 半透明深底）+ `.warn` / `.danger` 阈值变色类，全用
    `var(--warning-*)` / `var(--error-*)` token。
  - `src/ai_intervention_agent/web_ui.py` —— `_get_template_
context()` 加 `"feedback_char_counter_version"`。
  - 三 locale `feedback.charCounter` key（`zh-CN.json` /
    `en.json` / `_pseudo/pseudo.json`）含 `{{count}}` mustache
    占位。

  **测试**（`tests/test_feedback_char_counter_r138.py`，33 cases /
  6 invariant classes）：
  1. **JS 文件存在 + 体积合理** — 文件存在 / 100-180 行 envelope。
  2. **常量值锁定** — 7 个常量（`TARGET_ID` / `COUNTER_ID` /
     `WARN_THRESHOLD=8000` / `DANGER_THRESHOLD=10000` /
     `WARN_CLASS` / `DANGER_CLASS` / `I18N_KEY`）+ 阈值递进
     关系（WARN < DANGER）。
  3. **API 函数签名** — 5 个公共函数 + `window.AIIA_FEEDBACK_CHAR
_COUNTER` export 全 12 个字段。
  4. **graceful failure / fallback** — `_formatCount` try/catch
     Intl.NumberFormat、`_t` helper try/catch i18n runtime、
     FALLBACK_TEXT 含英文兜底、mustache replacement、
     `_applyThresholdClass` 处理 missing classList、
     `updateCounter` count 0 时 hidden=true。
  5. **HTML / context 集成** — `<span>` 在 textarea-container 内 /
     `aria-live="polite"` / `hidden` 初始；`<script defer
nonce={{csp_nonce}} src=...?v={{feedback_char_counter_version}}>`；
     `_get_template_context` 用 `_compute_file_version`；CSS 三
     选择器存在 / 用 `var(--warning-*)` + `var(--error-*)` token。
  6. **i18n 三 locale 全覆盖** — `feedback.charCounter` key 在
     `zh-CN.json` (`{{count}} 字符`) / `en.json`
     (`{{count}} chars`) / `_pseudo/pseudo.json` 同时存在，
     mustache 占位被保留。

  **验证**：33/33 R138 + 全工程 4346 passed + 2 skipped；
  `uv run python scripts/ci_gate.py` exits 0；
  `test_i18n_js_no_hardcoded_cjk` / `test_i18n_orphan_keys` /
  `test_web_locale_no_dead_keys` / `test_minified_source_file_sync`
  四道护栏 first-pass 触发后全修，二次跑全清。

  **后续 follow-up（不在 R138 范围内）**：
  - **R138-A**：动态 maxlength 上限——后端通过 `/api/config`
    暴露 `feedback_max_length`，前端拉取后调整阈值色板，让
    counter 与服务端约束一致。
  - **R138-B**：hover 提示——counter 鼠标悬浮时显示 `X / 10000`
    格式 tooltip 让 advisory 阈值显式。
  - **R138-C**：超 `DANGER_THRESHOLD` 时按钮 disabled——把
    advisory 升级为可选 enforced 模式（用户偏好开关）。

- **R137** — **(UX)** 反馈 textarea 高度跨会话持久化——
  Web UI 上的 `#feedback-text` textarea 把用户拖拽调整后的高度写入
  `localStorage`，下次加载（同浏览器同源）时自动复原。竞品
  `mcp-feedback-enhanced` 的 "Input Height Memory" 是高频用户痛点
  feature——长输入用户每次刷新都得重新拖大输入框很折磨——R137 把这
  个体验补齐而又不引入服务端状态。

  **设计决策**：
  1. **纯前端 localStorage** — 不上服务端、不进 `user_settings`，
     避免「设置同步」这条新轴的复杂度。窗口/浏览器维度持久化，单用
     户多浏览器场景天然解耦。Storage key
     `aiia.feedbackTextareaHeight.v1`（带 `.v1` 锚点 + envelope
     `schema_version: 1` 双锁，未来 schema 升级有迁移空间）。
  2. **ResizeObserver 主路径 + `mouseup`/`touchend` fallback** —
     `ResizeObserver` 是浏览器原生最优 API（debounced batch、不挂
     `layout` 主线程），但少数老浏览器（IE / 早期 Safari）没有；
     fallback 到 `mouseup`/`touchend` 监听 textarea 拖动结束事件。
     `setupResizeObserver()` 返回 `{observer, mode}`，
     `mode in {"resize_observer", "mouseup_fallback"}`，供 hook /
     测试断言。
  3. **min / max clamp** — `MIN_HEIGHT_PX=100` /
     `MAX_HEIGHT_PX=800`。`_clamp(value)` 在 read / persist 两个
     方向都跑一次，保证用户 dev tools 直接改 localStorage 注 -1 / NaN
     / 9999 也只 apply 合法值；CSS 的 `min-height: 180px`（desktop）/
     `max-height: 25vh`（mobile）对 inline `height` 仍有 final
     clamp 权（CSS spec：computed height = clamp(min, height, max)），
     JS ↔ CSS 双层兜底永远不会让 textarea 缩到 0 高度搞坏 layout、也
     不会撑出屏幕。
  4. **`DEBOUNCE_MS=150`** — 拖动过程中 `ResizeObserver` 会高频
     触发（~60Hz），一律 `setTimeout` 合并最后一帧再写盘，
     localStorage 一次写盘耗时 ~1-3ms 主线程阻塞，debounce 把累积写
     盘从「~60 次/秒」压到「~7 次/秒」（debounce + 拖完之后停手才
     真正落盘），平衡延迟感与写盘开销。
  5. **graceful degradation** — `readPersistedHeight()` /
     `persistHeight()` 全部 try-catch，`localStorage` 不可用
     （Safari 隐私模式 / quota 满 / cookie 禁用）时自动 no-op，不
     污染主路径。返回 `null` 时 `applyPersistedHeight()` 走 CSS
     默认高度。
  6. **CSP nonce 集成** — 新加的 `<script>` 标签携带
     `nonce="{{ csp_nonce }}"`，与既有 R47 / R74 等模块同款，避免
     违反项目级 CSP `script-src 'self' 'nonce-...'` 策略。
  7. **版本化 cache busting** — `?v={{ feedback_textarea_height_version
}}` 复用 `_compute_file_version(...)`（基于文件 mtime + size
     hash），让 immutable cache 也能在改 JS 后立即失效，不用等浏览器
     缓存 TTL 过期。

  **实现**：
  - `src/ai_intervention_agent/static/js/feedback_textarea_height.js`
    （NEW，~140 行）—— 5 个公共函数：`readPersistedHeight()` /
    `persistHeight(px)` / `applyPersistedHeight()` /
    `setupResizeObserver()` / `init()`。
  - `src/ai_intervention_agent/templates/web_ui.html` —— 新增一
    个 `<script defer>` 节点，`nonce` + `?v=` 双 hook 齐备。
  - `src/ai_intervention_agent/web_ui.py` —— `_get_template_context()`
    加 `"feedback_textarea_height_version": _compute_file_version(...)`
    一行。
  - `window.AIIA_FEEDBACK_TEXTAREA_HEIGHT` 全局对象暴露所有公共
    函数 + `_clamp` / 5 个常量（测试 / 调试用）。

  **测试**（`tests/test_feedback_textarea_height_r137.py`，
  23 cases / 6 invariant classes）：
  1. **JS 文件存在 + 体积合理** — 文件存在 / 在 80-200 行之间，避
     免误删除或意外膨胀。
  2. **常量值锁定** — `STORAGE_KEY` / `SCHEMA_VERSION` /
     `MIN_HEIGHT_PX` / `MAX_HEIGHT_PX` / `DEBOUNCE_MS` /
     `TARGET_ID` 字面值。
  3. **API 函数签名** — 5 个公共函数都在；`window.AIIA_FEEDBACK_
TEXTAREA_HEIGHT` 暴露完整 API。
  4. **`_clamp` 行为** — 低于 min / 高于 max / NaN / null /
     undefined / 字符串 都返回合法值。
  5. **graceful failure** — `readPersistedHeight` / `persistHeight`
     try-catch 包了 localStorage 调用；返回值符合契约。
  6. **HTML / context 集成** — `<script>` 标签存在 / 带
     `nonce={{ csp_nonce }}` / 带 `?v={{ feedback_textarea_
height_version }}` / `defer`；`_get_template_context`
     里 `feedback_textarea_height_version` 走 `_compute_file_
version(...)`。
  7. **ResizeObserver 主路径 + fallback** — `setupResizeObserver`
     在 `window.ResizeObserver` 存在时返回 `{mode:
"resize_observer"}`；不存在时返回 `{mode: "mouseup_fallback"}`；
     fallback 路径监听 `mouseup`/`touchend`。

  **验证**：23/23 R137 + 全工程 4313 passed + 2 skipped；
  `uv run python scripts/ci_gate.py` exits 0；CSP nonce / version
  cache busting 在浏览器 devtools 实测可见。

  **后续 follow-up（不在 R137 范围内）**：
  - **R137-A**：textarea 宽度持久化（如果用户也想拖宽）。当前 CSS
    用 `width: 100%` 没有横向 resize handle，留空间。
  - **R137-B**：服务端同步（用户多设备同步偏好）—— 等 `user_settings`
    后端 schema 落地后再说。

- **R136** — **(feature)** 通知 in-flight 队列断电恢复持久化——
  `NotificationManager` 把入队但还没投递成功的事件 atomic-write 到
  `notification_inflight.json`，进程重启后一次性 load 暴露给
  `get_status()`，让运维 / 监控仪表板第一时间看到「上次重启时还有
  N 条通知没投递」。

  **背景**：在 R136 之前，`_event_queue` / `_finalized_event_ids`
  全在内存里。进程异常退出（崩溃 / SIGKILL / OOM / 容器被驱逐 /
  `systemctl restart`）时会彻底丢——运维侧完全看不到「上次重启时
  还有 N 条通知没投递」，是基础观察性盲点。R136 把这个盲点补上。

  **为什么不自动重发**：用户关电脑回家睡觉，第二天开机重发昨天 50
  条通知 = 噪音灾难。R136 范围内仅做"持久化 + 启动时加载暴露给
  stats"，把"是否重发"决策权让给将来的 R136-A（如果用户有需求）。

  **设计决策**：
  1. **持久化文件与 config 同位** — 路径 = `_get_inflight_file_dir()`
     即 `config_manager.get_config().config_path.parent`，文件名
     `notification_inflight.json`（典型 `~/.config/ai-intervention-
agent/notification_inflight.json` on Linux 或
     `~/Library/Application Support/...` on macOS）。复用 config 目
     录的好处：用户已经习惯 backup 这个目录、容器卷已经 mount 这个目
     录、平台目录解析逻辑已经在 `platformdirs` 里搞定。
  2. **schema_version + signature envelope** — 顶层
     `schema_version: 1` + `saved_at: ISO` + `events: [...]`。
     未来 schema 升级（v2 / v3）有个明确锚点；schema_version 不匹配
     时 `_load_persisted_inflight_events` 直接返回 `[]` 而不挂，
     给未来 migrator 留接入空间。
  3. **Atomic write `.tmp → os.replace`** — POSIX rename atomic 保证
     是 SSDb 写半截绕过的标准技巧：写 `notification_inflight.json
.tmp` 后 `os.replace` 换成正式名。崩溃在写 `.tmp` 中途时正
     式文件不变；崩溃在 replace 时文件系统层保证要么还是老内容、要
     么是新内容，永远不会读到半截 JSON。
  4. **TTL = 5 分钟（300 秒）** — 典型用户场景下，通知如果 5 分钟内
     没投递成功就基本失去时效（feedback 已经过期 / 用户已经看过了）。
     这个 TTL 把「关电脑回家场景」隔离掉——重启后只看最近 5 分钟内的
     真正"飞行中"事件，不被昨晚的 stale 数据污染。
  5. **集合空时主动删文件** — 不留空 envelope；让运维在 `ls` 时
     一眼看到「当前进程有没有 in-flight 通知积压」（文件不存在 = 干
     净状态）。
  6. **不引入新锁** — 复用 `_queue_lock` 保护
     `_inflight_persisted_ids` 集合 + 写盘路径，与 `_event_queue`
     append / trim 同一锁等级，避免引入新的锁顺序冲突风险。
  7. **入队 + 摘除两个挂点** — `_create_event` 入队后走
     `_track_event_inflight`（add id → 写盘）；`_mark_event_finalized`
     收尾时走 `_untrack_event_inflight`（discard id → 写盘 / 最后一
     个时删文件）。两条路径都 try-except 包了 best-effort，磁盘满 /
     权限错误 / 文件锁竞争都不会让通知主路径挂掉。
  8. **getattr 兜底兼容老 helper** — `get_status()` /
     `_track_event_inflight` / `_untrack_event_inflight` /
     `_persist_inflight_unlocked` 都对 `_inflight_persisted_ids`
     用 `getattr` 兜底，让 `test_notification_manager._make_manager()`
     这种"绕开 `__init__` 手动构造"的老测试 helper 不挂。R136 加新
     字段不应当让既有测试基础设施 fail。
  9. **启动时一次性 load → 不自动重发** — `__init__` 末尾调
     `_load_persisted_inflight_events()` 把数据存到
     `_inflight_seen_at_startup`，`get_status()` 把它暴露给运维
     仪表板。**不重新进队列、不调 `_process_event`**——避免重启风
     暴 / 用户被旧通知刷屏。

  **实现**：
  - `notification_manager.py` 模块级新增 3 个常量
    （`_INFLIGHT_FILE_NAME` / `_INFLIGHT_SCHEMA_VERSION` /
    `_INFLIGHT_TTL_SECONDS`）+ `_get_inflight_file_dir()` helper。
  - `NotificationManager.__init__` 新增 `_inflight_persisted_ids`
    集合 + `_inflight_seen_at_startup` 列表；`__init__` 末尾调
    `_load_persisted_inflight_events()` 给 `_inflight_seen_at_startup`
    赋值，try/except 兜底失败不阻塞启动。
  - 新增 5 个方法：`_inflight_file_path()` / `_track_event_inflight()` /
    `_untrack_event_inflight()` / `_persist_inflight_unlocked()` /
    `_load_persisted_inflight_events()`。
  - `send_notification` 入队后 try-except 调 `_track_event_inflight`；
    `_mark_event_finalized` 收尾后 try-except 调 `_untrack_event_inflight`。
  - `get_status()` 顶层加 `inflight_persisted_count` (int) +
    `inflight_seen_at_startup` (list[dict] 副本)。
  - `docs/api/notification_manager.md` + `docs/api.zh-CN/...` 通过
    `scripts/generate_docs.py` 自动重新生成（无需手改）。

  **测试**（`tests/test_notification_inflight_persistence_r136.py`，
  24 cases / 6 invariant classes）：
  1. **常量** — 三个常量值锁定（`notification_inflight.json` /
     `schema_version=1` / `TTL=300s`）。
  2. **load 容错** — 缺文件 / JSON 损坏 / 顶层不是 dict / schema
     不匹配 / events 不是 list / 元素不是 dict 全部返回 `[]` 不抛
     异常。
  3. **TTL 过滤** — fresh 事件保留；超期事件过滤；`saved_at_ts`
     不是数字时被丢弃。
  4. **persist 写盘** — 空集合 + 文件存在时删文件；空集合 + 无文件
     no-op；非空时写 envelope 含 schema_version + saved_at + events；
     atomic 写后无 `.tmp` 残留。
  5. **track / untrack 行为** — track 后磁盘含事件；untrack 中间一
     个后磁盘只剩另一个；最后一个 untrack 后文件被删；untrack 未知
     id 静默 no-op。
  6. **get_status R136 字段** — `inflight_persisted_count` 在；
     反映当前集合大小；`inflight_seen_at_startup` 是 list；外部修
     改返回值不影响 manager 内部状态（深拷贝/list 副本）。

  **验证**：24/24 R136 + 192/192 既有 notification 全套（含
  `test_notification_manager.py`，老 helper 走 getattr 兜底路径）+
  其他周边 = 全工程 4290 passed + 2 skipped；
  `uv run python scripts/ci_gate.py` exits 0。

  **后续 follow-up（不在 R136 范围内）**：
  - **R136-A**：基于 `inflight_seen_at_startup` 做"主动重发"决策
    （需要更精细 TTL 策略 + 用户级开关，避免风暴）；
  - **R136-B**：`/api/system/health` payload 把 `inflight_persisted_count`
    暴露成顶层字段，让 K8s probe 能直接看到。

- **R135** — **(feature)** `GET /api/tasks/export?since=<ISO>` 增量导出
  过滤器，CI / 备份脚本周期性同步只拿真正变化的 tasks，传输量从
  O(N×content) 降到 O(M×content)（M ≤ N）。

  **背景**：R125 / R125c 的导出端点全量导出整个 `TaskQueue` 快照。
  在 CI / 备份脚本周期性拉 `/api/tasks/export` 的真实场景里，绝大
  多数任务自上次同步后没动过——全量传输是 O(N×content) 浪费（含
  base64 image data 时尤甚）。R125c 的 `include_images=false` 已经
  把单条 task 的体积压缩 90%+，但还是「全量」语义。R135 引入
  `?since=<ISO>` 把过滤交给服务端，downstream 只拿真正变化的
  tasks。

  **设计决策**：
  1. **过滤维度选「task 最后变化时间」** — `Task` 模型暴露
     `created_at` + `completed_at` 两个时间戳，`pending → active`
     状态切换没独立时间戳但也不影响导出内容（status enum 下一次全
     量同步时自然消化）。「`created_at >= since` 或 `completed_at >=
since`」就是「task 自 since 之后变化」最自然的语义。
  2. **ISO 解析复用 `datetime.fromisoformat`** — Python 3.11+ 原生
     支持 `Z` 后缀，3.10 及之前不支持但 helper 显式 `Z → +00:00`
     替换兜底。naive datetime（不带时区）按 UTC 处理，与
     `Task.created_at` 全 UTC-aware 的契约保持一致。
  3. **缺省走全量、错误走 400** — `?since` 缺失或空字符串走全量路
     径，与 R125 行为完全一致（向后兼容既有 curl / CI 用户）；非法
     ISO（`2024/01/15` / `not an iso` / `2024-13-99`）返回 400
     `error: invalid_since`，与 `unsupported_format` 同款返回
     结构。
  4. **JSON payload 加 `since` 字段 + `incremental: bool`** —
     `since` echo 用户传入的 ISO 字符串（解析后规范化时区段，e.g.
     `Z` → `+00:00`），让消费方知道服务端到底过滤到哪个时刻；
     `incremental` 是 bool 让 dashboard 一眼分辨「全量」vs「增量」，
     避免误把增量当全量回放。
  5. **`stats` 字段保持全局不局部化** — 监控 dashboard 关心整体队
     列健康度（pending / active / completed 总量），按 since 过滤
     局部化反而误导。`tasks` 列表过滤了，`stats` 不动。
  6. **Markdown 模式同款对齐** — Markdown header 在 since 触发时插
     一行 ``- Filtered since: \`<ISO>\```，让人类读快照时一眼知道
     「这是自 X 以来变化的子集」而不是全量。
  7. **三参数组合可正交** — `since` + `format=json|markdown` +
     `include_images={true,false}` 三个参数互不冲突，filter 是 first
     pass（在序列化之前），include_images 是 result 内部裁剪
     （在 sanitize 阶段），format 是输出阶段。

  **实现**：
  - `web_ui_routes/task.py` 模块级新增 `_parse_since_iso(raw)`
    helper（`Z` 后缀替换 + `ValueError` 捕获 + naive→UTC 兜底；
    返回 `(parsed_dt, error_msg)` 元组）+ `_task_modified_since(
task, since)` helper（`getattr` duck-typing，对 `Task` 和
    单元测试桩对象同样工作）。`export_tasks` handler 加一段 since
    解析与 400 路径，过滤 `tasks` 列表，JSON payload 加 `since` /
    `incremental` 字段，Markdown header 加 `Filtered since:` 行。
  - `export_tasks` Swagger `parameters` 加 `since` 描述
    （`format: date-time`）+ `responses.400` 描述补充 since 错
    误模式。

  **测试**（`tests/test_tasks_export_since_r135.py`，22 cases /
  5 invariant classes）：
  1. **`_parse_since_iso` helper** — None / 空 / 仅空白 → no-op；
     `+00:00` 显式时区 / `Z` 后缀 / naive 三种合法形式都返回
     UTC-aware datetime；非法 `not an iso` / `2024/01/15` /
     `2024-13-99T99:99:99` 都返回 `(None, error_msg)`。
  2. **`_task_modified_since` helper** — created_at >= since →
     True；created_at == since 边界 → True（`>=`）；
     completed_at >= since 但 created_at < since → True；created_at
     < since 且 completed_at None → False；created_at < since 且
     completed_at < since → False。
  3. **HTTP 默认行为不变** — `?since` 缺省时全量返回；空字符串
     `?since=` 同款全量；`since: None` / `incremental: false`。
  4. **HTTP `?since` 增量路径** — 过滤生效（用 fixture 把一个
     task `created_at` backdate 1h，midpoint 30min ago 过滤后只剩
     新的）；Z 后缀同样 work；future since 返回 `tasks: []` +
     `incremental: true`；`stats` 仍是全队列基线 `total = 2`
     不被局部化；Markdown 模式 header 含 `Filtered since:` 行。
  5. **HTTP 错误路径与组合** — 非法 ISO 返回 400 `invalid_since`
     （format=json / markdown 两路径都 400 不半态）；三参数组合
     `since + format=json + include_images=false` 三个 invariant
     都生效。

  **辅助 helper**：`_iso_for_query(dt)` 把 `datetime` 转 query-safe
  ISO 字符串（`urllib.parse.quote(safe="")` percent-encode `+` /
  `:` 防止 query parser 把 `+` 当空格）。这是 R135 专属测试侧
  helper，与生产代码无关——但是排查"为什么 `+00:00` 后缀的 ISO
  在 query 里 fails parse"花的时间值得记录。

  **验证**：22/22 R135 + 50/50 R125/R125b/R125c 既有套件 = 72/72
  export 全套零回归；`uv run python scripts/ci_gate.py` exits 0。

- **R134** — **(feature)** SSE bus emit→deliver 延迟分布量化（P50 / P95 /
  count），把 R47 的「事件量」维度补齐成「延迟分布」维度，让运维 dashboard
  / SLO 告警能直接对线上 SSE 推送质量。

  **背景**：R47 / R51-B / R58 / R61 已经把 `_emit_total` /
  `backpressure_discards` / `heartbeat_total` / `oversize_drops` /
  `emit_by_type` 五张表暴露在 `/api/system/sse-stats`，但全是「事件
  量」维度的累计指标。线上 QoS 真正的盲点是「emit 之后客户端多久才
  真的拿到数据」——这才决定用户 UI 的实时感、决定 `task_changed` 事
  件是不是能驱动状态栏跳变。Datadog / Grafana 团队的 SSE 监控最佳实践
  里 P50 / P95 是必看项，没有这两个数字就只能盯着平均值（Average is
  a Lie）。

  **设计决策**：
  1. **测量点选 emit→generator yield，而不是端到端 RTT** — 真正的
     emit→deliver 延迟在我们这里有两段：「emit lock + put_nowait」+
     「Flask generator 拿到 queue 元素 + yield 给 WSGI 写网络」。我们
     在 generator yield 之前用 `time.monotonic_ns() - payload['_emit_ts_ns']`
     算这两段的总和，覆盖了 server-side 全部可控延迟。client-side
     RTT 包含 TCP / 反向代理 / 浏览器 EventSource buffer，与服务端
     性能不直接相关，应该交给 `X-Server-Time` 之类 client metric
     单独测，不混进同一个柱。
  2. **`time.monotonic_ns` 而非 `time.time`** — `time.time` 在
     NTP 校时回拨（typical：DST 切换、NTP 大跳）时会算出负 latency，
     污染 P50/P95；`monotonic_ns` 单调递增设计成永不回拨，正是测
     elapsed 的标准时基。POSIX `CLOCK_MONOTONIC` 同款语义。
  3. **环形缓冲选 deque(maxlen=512)** — 单元 = `int` (CPython ~28B)，
     512 个 ≈ 14KB / 实例，与 `_HISTORY_MAXLEN=128` (~32KB) 同数量
     级；P95 留 25 个样本（512 × 5%）足以让分布在毫秒抖动下稳定到
     ±1ms 量级；512 条对 100 个连接 × 10 events/s 场景相当于 0.5 秒
     滑动窗口，比 1024/2048 那种"几秒 ago 的均值"对告警决策更直接。
  4. **算法选 nearest-rank percentile** — `sorted_samples[int(N * pct)]`
     比线性插值算法（如 R / numpy 默认）简单稳定，对监控用场景 ±1ms
     精度完全够；512 个 int 排序成本 ~50µs（CPython timsort），
     `stats_snapshot` 60/min 调用时占 0.005% CPU 可忽略。
  5. **count == 0 时 p50 / p95 用 None 而非 0** — 让监控 caller 一眼
     分辨「刚启动还没数据」（None）和「延迟为零」（0.0）。Datadog /
     Prometheus 都把 None 当 missing 处理，0 当真实零值，区分至关重要。
  6. **`_emit_ts_ns` 字段挂在 payload 上而不是单独传** — 与
     `_serialized` / `id` / `type` / `data` 同款命名（`_` 前
     缀 = generator 私有 metadata），不进 SSE wire format（generator
     只把 `serialized` 和 `event_id` 拼到 `data:` / `id:` 行）。
     缺失（如 `gap_warning` 由 `subscribe` 直接塞进 queue 不走 emit）
     时 generator 静默跳过 latency 采样——只测真实的 emit→deliver 路径。
  7. **接口契约：`latency_ms` 顶层独立 dict，不混进 emit_by_type** —
     `emit_by_type` 是 `dict[str, int]` 桶，`latency_ms` 是
     `{p50_ms: float|None, p95_ms: float|None, count: int}`。两组语
     义不一样，平铺会让 dashboard 难写。R47 的 TypedDict 加一个
     `SSELatencySnapshot` 子类型锁定 shape，IDE 一眼可推断字段类型。
  8. **正负数值防御** — `record_emit_to_deliver_latency_ns(ns)` 入
     口对 `ns < 0` 静默丢弃；理论上 `monotonic_ns` 不会回拨，但
     单元测试 mock 时可能凑负值，加防御让样本始终非负。

  **实现**：
  - `web_ui_routes/task.py` 顶部新增 `SSELatencySnapshot` TypedDict；
    `SSEBusStatsSnapshot` 加 `latency_ms` 字段；
    `_SSEBus._LATENCY_SAMPLES_MAXLEN = 512` 类常量 +
    `_latency_samples_ns: deque[int]` 实例字段；新增
    `record_emit_to_deliver_latency_ns(ns: int)` 持锁追加；新增
    `_compute_latency_snapshot()` 持锁排序 + nearest-rank P50/P95；
    `emit()` 在 lock 外取 `emit_ts_ns = time.monotonic_ns()` 后写进
    payload `_emit_ts_ns`；`stats_snapshot()` 返回值加
    `"latency_ms": self._compute_latency_snapshot()`；
    SSE generator 在 yield 之前从 payload 读 `_emit_ts_ns`，缺失则跳
    过，存在则调 `_sse_bus.record_emit_to_deliver_latency_ns(...)`。
  - `web_ui_routes/system.py` `/api/system/sse-stats` Swagger 文档
    在 schema.properties 加 `latency_ms` 嵌套对象描述 + 三字段
    （p50_ms / p95_ms / count）说明。

  **测试**（`tests/test_sse_emit_to_deliver_latency_r134.py`，20 cases /
  6 invariant classes）：
  1. **常量与 init** — `_LATENCY_SAMPLES_MAXLEN` = 512；deque 初始
     empty + maxlen 字段 = 512。
  2. **采样 API** — `record(...)` 正常追加；负数静默丢；0ns 接受；
     超 maxlen 时最旧 evict（触发条件 maxlen + 50 个样本写入）。
  3. **percentile 计算** — empty → 全 None + count = 0；count = 1 →
     p50 = p95 = 唯一样本；构造 100 个 1..100ms 样本，断言 P50 = 51ms
     / P95 = 96ms（nearest-rank 索引 = int(N×pct)）；加大尾样本后 P95
     单调不降；5.123ms 样本 round 到 5.12（2 位小数）。
  4. **emit 注入与 generator 消费** — `emit()` 后 history payload 含
     `_emit_ts_ns` 字段且 > 0；source 内 `def generate(` 函数体含
     `record_emit_to_deliver_latency_ns(` 调用（防 generator 集成被
     回滚）。
  5. **stats_snapshot + TypedDict** — 返回 dict 含 `latency_ms` 键 +
     三字段（p50_ms/p95_ms/count，初值 count=0）；R47 / R51-B / R58 /
     R61 既有 9 个键全部仍在；TypedDict 注解锁定。
  6. **Swagger 文档** — `system.py` 含 `R134` 标记 + `latency_ms`
     / `p50_ms` / `p95_ms` 字段名（caller-facing 文档契约）。

  **验证**：20/20 R134 + 78/78 R47/R51-B/R58/R61/R50/R52b/R55/R39 +
  20 system 端点既有 = 138/138 SSE/system 全套零回归；
  `uv run python scripts/ci_gate.py` exits 0；全工程
  4244 passed + 2 skipped，与提交 R131d 时 4207 passed 加 17 (R131d)
  加 20 (R134) = 4244 完美吻合。

  **后续 follow-up（不在 R134 范围内）**：`subscribe(after_id)` 走
  history replay 时给客户端补发的 payload 也含 `_emit_ts_ns`（emit
  时刻），导致 reconnect 风暴下 P95 会被 reconnect lag 拉高。这其实
  是「reconnect lag」也有意义的指标，留作未来 R-series 评估是否需要
  分桶（latency_ms vs replay_lag_ms）。

- **R131d** — **(feature)** Quick Phrases 面板键盘快捷键 `Alt+1..9`
  快速插入前 9 条 chip，对齐 Slack/Discord 行业惯例的「常用片段
  modifier+数字」体感，是 R130 → R131 → R131b → R131c 一路追下来给
  熟练用户的最后一道生产力闭环。

  **背景**：R131c 把 chip 排序按使用频率落地后，用户的「最常用」
  20 条 phrase 自动沉到列表前列，但每次仍需鼠标移动到 chip 区点
  击。Slack（`Alt+1..9` 切换 workspace）、Discord（`Alt+1..9` 切
  换服务器）、IntelliJ IDEA（`Alt+1..9` 切换 tool window）都把
  `Alt+数字` 锁死成「快速跳转 / 触发常用项」语义。竞品
  `mcp-feedback-enhanced` v1.2.23 + `cunzhi` v0.4.x 都没做这个，
  在「键盘党」用户体验上有空挡可补。

  **设计决策**：
  1. **修饰键选 `Alt` 而非 `Ctrl/Cmd`** — `Ctrl/Cmd+1..9` 在所有
     主流浏览器（Chrome / Firefox / Safari / Edge）都被预占用作
     「切换标签页 N」，`preventDefault()` 也拦不住（浏览器层快
     捷键优先级高于 page）。`Alt` 在 Chrome / Edge 是「打开主菜
     单焦点」但 `preventDefault` 可拦；macOS `Option` 与 `Alt`
     共享 `event.altKey`，跨平台一致。
  2. **范围锁 1..9，而非 0..9** — `Alt+0` 在 Chrome 是「重置缩放
     到 100%」，与 `Ctrl+0` 一脉相承的语义；强行抢占体感差，且
     即便允许覆盖也会与浏览器无障碍快捷键冲突。9 条对绝大多数熟
     手用户已足够覆盖「日常 80%」用例。
  3. **复用 R110 既有 `window.KeyboardShortcuts`，回退到原生
     `keydown`** — R110 / R110-A 已构造好全局 shortcut 注册中
     心 + `allowInInputs` / `preventDefault` / 修饰键归一化逻
     辑。R131d 注册 9 条 `alt+1` … `alt+9` 即可；模块缺失时
     fallback 到原生 `keydown` 监听并自检 `modifierKey & numKey`
     `preventDefault`，兼容旧 web_ui.html 模板加载顺序异常。
  4. **`allowInInputs: true` 是必要的** — 主用户场景就是站在
     `feedback-text` textarea 里打字、随手 `Alt+3` 插入第 3
     条常用回复。R110 默认 `allowInInputs: false` 是保守策略
     （怕快捷键打字干扰），但 quick phrases 场景反过来：必须穿透
     input。每个 register 显式传 `allowInInputs: true` 做覆盖。
  5. **form mode（add / edit form 弹出时）禁用快捷键** — 用户在
     编辑 phrase 内容时按 `Alt+3` 应当属于「输入字符」而非
     「插入第 3 条」。`_activateShortcut` 入口先查
     `document.querySelector('.quick-phrases-form')` 判断 form
     是否打开，是则直接 return（让默认行为/原生 `Alt+` 字符流
     接管）。
  6. **chip 上 `data-shortcut-index` + 国际化 `title`** —
     前 9 条 chip 在 DOM 上加 `data-shortcut-index="1..9"` 数据
     属性 + `title="Alt+1 quick insert"` 等价 i18n tooltip
     （key `quickPhrases.chipShortcutTitle`，含 `{{shortcut}}`
     插值）。让用户 hover 时看到提示而不必读文档；data 属性给未
     来 a11y / 测试 / CSS 都留挂点。
  7. **`recordPhraseUsage` 与 chip click 同语义** —
     `_activateShortcut` 在 `insertTextIntoFeedback` 之后调
     `recordPhraseUsage(id)`，与 R131c 的 chip click handler 完
     全对齐：键盘触发与鼠标触发对排序的影响一致，符合「最近使用」
     语义直觉。

  **实现**：
  - `static/js/quick_phrases.js` 模块顶部新增常量
    `SHORTCUT_INDICES = [1..9]` + `SHORTCUT_PREFIX = "alt+"`；
    新增 `_activateShortcut(index)` 函数（`query .quick-phrases-form`
    判 form mode → `loadPhrases().then(_sortPhrasesByUsage)` →
    取第 N-1 条 → `insertTextIntoFeedback(text)` →
    `recordPhraseUsage(id)`）；新增 `setupKeyboardShortcuts()`
    函数（优先 `window.KeyboardShortcuts.register({key, handler,
preventDefault: true, allowInInputs: true})`，缺失则 fallback
    原生 `keydown` 监听 + 自检 `altKey && numKey 1..9`）；
    `init()` 末尾追加 `setupKeyboardShortcuts()` 调用。
  - `renderList()` 在 chip `forEach` 内部对 `idx <
SHORTCUT_INDICES.length` 的元素加 `setAttribute(
"data-shortcut-index", String(SHORTCUT_INDICES[idx]))` +
    i18n `title`（`_t("quickPhrases.chipShortcutTitle",
{shortcut: "Alt+" + N})`）。
  - `window.AIIA_QUICK_PHRASES` 暴露 `setupKeyboardShortcuts`
    - `_activateShortcut`，给测试 + 调试 + 未来 a11y 框架接入用。
  - `static/locales/{en,zh-CN,_pseudo/pseudo}.json` 新增
    `quickPhrases.chipShortcutTitle` key（含 `{{shortcut}}`
    插值，与 R131 `confirmDelete` 同款 Mustache）。

  **测试**（`tests/test_quick_phrases_keyboard_shortcuts_r131d.py`，
  17 cases / 5 invariant classes）：
  1. **JS API 扩展** — 两个函数签名（`setupKeyboardShortcuts` /
     `_activateShortcut`）+ 公开 API 暴露 + `SHORTCUT_INDICES`
     / `SHORTCUT_PREFIX` 常量在 source 中可见。
  2. **快捷键注册路径** — 优先尝试 `window.KeyboardShortcuts`
     正路径，每个 register 调用都带 `allowInInputs: true` +
     `preventDefault: true` 选项（R110 默认相反，必须显式覆盖）；
     fallback 原生 `keydown` 含 `altKey` 与 数字键归一化；
     `Alt+1..9` 9 个 key 都覆盖。
  3. **chip UI 提示** — `renderList` 对 `idx <
SHORTCUT_INDICES.length` 的 chip 加 `data-shortcut-index`
     属性 + i18n title；`idx >= 9` 不加（不强行展示「Alt+10」
     这种不存在的快捷键）。
  4. **form mode 禁用 + 顺序契约** — `_activateShortcut` 入口
     先查 `.quick-phrases-form` 短路返回；正常路径下
     `insertTextIntoFeedback` 调用必须早于 `recordPhraseUsage`
     （正则 `insertTextIntoFeedback[\s\S]+recordPhraseUsage`
     单向匹配）。
  5. **i18n 完整** — en / zh-CN / pseudo 三方都含
     `quickPhrases.chipShortcutTitle` 且都用 `{{shortcut}}`
     Mustache 插值参数。

  **验证**：17/17 R131d + 89/89 R130/R131/R131b/R131c/R133 = 106/106
  quick-phrases 全套零回归；`uv run python scripts/ci_gate.py`
  exits 0。

- **R133** — **(polish)** Quick Phrases 面板移动端响应式补齐 ≤768px /
  ≤480px 两档 layout，R131b 加 Export/Import 按钮后窄屏不再撞挤。

  **背景**：R130 v1 的 `.quick-phrases-header` 只有「label + Add」
  两个元素，`@media (max-width: 768px)` 下只动 container margin +
  chip 字号就够。R131b 把 header 扩到 4 元素（label + Add + Export
  - Import），在 < 480px 设备（iPhone SE / 老款 Android）上会撞挤——
    按钮 padding 被压到 0、点击目标 < 32×32（iOS HIG 与 Material
    Design 都把 44/48px 视为最小可点目标）、甚至按钮文字断行成两列。
    在 R131b 上线后第一时间就该补齐这块——不引入新 i18n / 不动桌面
    布局，颗粒小但 UX 收益大。

  **设计决策**：
  1. **断点扩成两档 768/480** — 桌面 ≥769px 保留 R131b 全宽布局；
     ≤768px 加 `flex-wrap` 让按钮在空间紧张时换行；≤480px 进一步
     强制 label 独占第一行（`flex-basis: 100%`），让按钮组在第
     二行可用全宽。
  2. **按钮 padding 阶梯收紧** — 桌面 0.25rem/0.85rem → 768px
     0.3rem/0.7rem → 480px 0.28rem/0.55rem；字号同样阶梯收紧。每
     一档都保证按钮高度（padding × 2 + line-height ≈ 1rem）≥ 32px
     的可点目标。
  3. **chip max-width 阶梯收紧** — 桌面 unset → 768px 10rem → 480px
     8rem；避免单个 chip 撑爆整行让 layout 抖动。
  4. **R131b 按钮共享 selector 模式扩展到 @media 块** — 桌面 selector
     group `.quick-phrases-{add,export,import}-btn` 同款合并到
     768px / 480px 块内，保证三个按钮永远视觉一致；与 R131b 的
     selector group 锁配套。

  **实现**：
  - `static/css/main.css` 把原 `@media (max-width: 768px)` 的
    Quick Phrases 块从 2 条规则扩到 4 条（加 `.quick-phrases-header`
    flex-wrap + 三类按钮共享 padding/font-size），并新增
    `@media (max-width: 480px)` 块（4 条规则：label flex-basis +
    三类按钮再收紧 + chip max-width 进一步降）。

  **测试**（`tests/test_quick_phrases_mobile_responsive_r133.py`，
  11 cases / 3 invariant classes）：
  1. **断点存在性** — CSS 同时含 768px / 480px 两个 `@media` 块，
     都覆盖 `.quick-phrases-header` / `.quick-phrases-label`。
  2. **flex-wrap + padding 收紧** — 768px 块含 `flex-wrap: wrap`
     - 三类按钮共享规则；480px 块含 `flex-basis: 100%` 强制独行
       规则；480px chip max-width 数值显式比 768px 更紧（值-比较）。
  3. **R130/R131b 桌面契约保留** — 桌面 `.quick-phrases-header`
     主规则（display:flex + gap:0.5rem）不被移走；R131b 的三类按钮
     桌面 base selector group 完整；`.quick-phrases-label` 桌面
     仍 `margin-right: auto`（R131b 设计）。

  **辅助 helper**：`_extract_media_block(src, breakpoint_px)` 用
  brace counter 抽取 `@media (max-width: <px>px)` 块——CSS 嵌套
  `{}` 里 `flex-wrap` 这种 property 含 `-` 不影响 brace 计数；
  与 R131b/R131c 测试的 `_extract_function_body` 同款思路。

  **验证**：11/11 R133 + 78/78 R130/R131/R131b/R131c = 89/89 quick-
  phrases 全套零回归；`uv run python scripts/ci_gate.py` exits 0。

- **R132** — **(feature)** `GET /api/system/health` 顶层暴露 build info
  `{git_commit, git_branch, git_dirty}`，复用 R63 既有的
  `server._resolve_build_info()` lazy cache。

  **背景**：R121-A 把 health 端点扩展为 K8s probe / 监控仪表板的命脉
  字段，但只带 `version` / `uptime_seconds` / `config_file_path`。
  `version` 字符串（`v1.5.45`）可能对应过 100 个 commit，对监控
  做 PR rollout 时仍不够精确——「新版本上线了吗 / 这个实例还在跑老
  commit 吗 / 是 dirty 工作树吗」三个问题没法一眼回答。R63 早就在
  `server._resolve_build_info()` 里 lazy 解析了 git_commit /
  git_branch / git_dirty，但只用到 `aiia://server/info` MCP resource
  上。

  **设计决策**：
  1. **复用 R63 既有 cache，不新开 git subprocess** —
     `_resolve_build_info` 是 module-level cache + 双重检查锁，第
     一次调 fork 3 个 `git` subprocess，后续都是 dict 浅拷贝。10s
     K8s probe 周期性拉取 health 不会炸 fork 风暴。
  2. **保留 R63 的"unknown 不是失败"契约** — pip / docker /
     pyinstaller 部署没有 `.git` 时字段值是 `"unknown"`，handler
     仍返回 dict 而不是 None。监控不应当把 unknown 当告警。
  3. **handler 不直接调 `server._resolve_build_info`** — 走
     `_safe_build_info` helper 包一层异常防御，与 `_safe_uptime_seconds`
     / `_safe_project_version` / `_safe_config_file_path` /
     `_safe_notification_summary` 同款防御策略。R53-F 的「handler
     不直接读 server module」契约就是为这种场景设的——任何 import
     /调用异常都被吞掉，health 端点不会因此 5xx。
  4. **dict shape 严格三字段** — helper 对 `_resolve_build_info`
     的返回做了显式 `str()` 转换、严格只取 `git_commit / git_branch
/ git_dirty` 三个字段，防止 R63 未来加新字段时 health 顶层
     payload 被无意扩张（监控仪表板对字段稳定性敏感）。

  **实现**：
  - `web_ui_routes/system.py` 模块级新增 `_safe_build_info()` 函
    数（与其它 `_safe_*` helper 同位）；`system_health()` payload
    顶层加 `"build": _safe_build_info()`；docstring 加 R132 字段
    描述（`flasgger` 自动 reflect 到 `/apidocs/`）。
  - `tests/test_web_ui_routes_system.py::TestSystemHealthEndpoint::
test_payload_carries_no_sensitive_fields` 把 `"build"` 加入
    `allowed_keys` 白名单 + 加专项类型断言（dict / None；dict 时
    严格仅 git_commit/git_branch/git_dirty 三键 + 全 str），与该测
    试 R121-A 留下的「新增任何顶层字段都必须先扩白名单 + 加专项类
    型断言」notes 一致。

  **测试**（`tests/test_system_health_build_info_r132.py`，13 cases
  / 3 invariant classes）：
  1. **handler 顶层暴露** — payload 含 `"build"`、调
     `_safe_build_info()` helper、不直接调
     `server._resolve_build_info`、docstring 含 R132 字段标记。
  2. **helper 行为契约** — module 级可调；正常返回严格三字段 dict
     全 str；`_resolve_build_info` 返回非 dict 时 helper 返回
     None；`_resolve_build_info` 抛异常时 helper 返回 None；
     全 `"unknown"` 是合法值（pip 部署 fallback）helper 不当作
     失败处理。
  3. **R53-F / R121-A 回归保护** — 既有 `version` / `uptime_seconds`
     / `config_file_path` 字段仍在；handler 不引入新 `get_config()`
     调用；status enum 三值不变；503 ↔ unhealthy 决策完整。

  **验证**：13/13 R132 + 既有 health 套件 R53-F / R121 / TestSystemHealthEndpoint
  共 98/98 零回归；`uv run python scripts/ci_gate.py` exits 0。

- **R131c** — **(feature)** Quick Phrases 面板按使用频率排序，对齐
  `mcp-feedback-enhanced` Prompt Management 的「最近使用优先」体感。

  **背景**：R130 v1 的 chip 渲染顺序是天然的「插入顺序」。当用户
  保存到 10-20 条 phrase 时，每次扫到熟悉的 chip 都要花眼睛。竞品
  `mcp-feedback-enhanced` v1.2.23 的 Prompt Management 明确按
  「最近使用」排序——是熟手用户体感差异最大的一项。R131c 在
  **不破坏 storage schema_version** 的前提下补齐这块。

  **设计决策**：
  1. **schema_version 不动 (仍 1)** — R131c 引入的两个字段
     `last_used_at` / `use_count` 是 v1 内的**可选字段**，
     `loadPhrases` 给老数据兜底 0；R131b 导入路径里 import 进来
     的 phrase 也默认 0。彻底回避「写 migrator」+ 老用户数据失效
     的风险。
  2. **排序键三层** — `last_used_at` desc 主排（最近用过最先），
     `use_count` desc 二排（同毫秒里用得多的优先），`created_at`
     desc 三排（都没用过时新建优先），`id` 字符串兜底（保证稳定
     排序）。从未用过的 phrase 沉到列表尾。
  3. **chip click 先插入再记录** — `insertTextIntoFeedback` 的
     文本插入是核心副作用，`recordPhraseUsage` 是 nice-to-have，
     必须按这个顺序，让记录失败（storage 配额满 / 浏览器隐身模式）
     不影响用户的核心诉求。
  4. **renderList 内排序、不改 storage 顺序** — `loadPhrases`
     仍按 storage 落盘顺序返回，`_sortPhrasesByUsage` 是渲染前
     的 `slice().sort(...)` 纯函数 view。这保留了「迁移到外部
     工具时仍能拿到原始顺序」的语义，也避免了反复重写 storage
     带来的写放大。
  5. **导入 / 编辑路径同步对齐** — `addPhrase` 显式写
     `last_used_at: 0, use_count: 0`；`parseImportPayload` 接
     收的字段不含两个新字段时由 `loadPhrases` 后续兜底；
     `editPhrase` 不动这两个字段（编辑 label/text 不应清零使用
     记录）。

  **实现**：
  - `static/js/quick_phrases.js` 新增 `recordPhraseUsage(id)`
    - `_sortPhrasesByUsage(phrases)`，`loadPhrases` 末尾追加
      `.map` 给老数据兜底字段，`addPhrase` / `importPhrasesFromJson`
      显式写入两个 0 值字段，`renderList` 在 `forEach` 之前调
      `_sortPhrasesByUsage`，chip click handler 在
      `insertTextIntoFeedback` 之后追加 `recordPhraseUsage(p.id)`。
  - `window.AIIA_QUICK_PHRASES` 暴露 `recordPhraseUsage`，
    给测试 + 调试用。

  **测试**（`tests/test_quick_phrases_usage_sort_r131c.py`，14
  cases / 5 invariant classes）：
  1. **JS API 扩展** — 两个函数签名 + 公开 API 暴露
     `recordPhraseUsage`。
  2. **schema 字段兼容** — `loadPhrases` 兜底 typeof 检查存在；
     `addPhrase` 显式写两个 0；`recordPhraseUsage` 用
     `Date.now()` 与 `use_count || 0) + 1` 自增。
  3. **chip click 顺序** — `renderList` chip click handler 同
     时含 `insertTextIntoFeedback` + `recordPhraseUsage`，
     前者位置必须在后者之前。
  4. **排序键** — `_sortPhrasesByUsage` 用 `b.X - a.X` 形态
     的 desc 比较锁三层主键 + `renderList` 在 forEach 之前调用
     排序函数。
  5. **schema 不破裂** — `STORAGE_KEY = "aiia.quickPhrases.v1"`
     - `SCHEMA_VERSION = 1` 锁定；`loadPhrases` 返回对象包含
       6 个字段（id / label / text / created_at / last_used_at /
       use_count）。

  **验证**：14/14 R131c + 26/26 R131b + 16/16 R131 + 19/19 R130
  - 3 共享 = 78/78 quick-phrases 全套零回归；
    `uv run python scripts/ci_gate.py` exits 0。

- **R131b** — **(feature)** Quick Phrases 面板补齐「JSON 导入 / 导出」
  跨设备 / 跨浏览器迁移能力（Code Review #2 P1 follow-up，对齐
  `mcp-feedback-enhanced` 的 Prompt Management 文件分发模式）。

  **背景**：R130 把 quick phrases 持久化到 `localStorage`，本质上
  是「单设备 / 单浏览器」语义——用户在 A 机器整理好 20 条常用回复，
  到 B 机器又得手敲一遍；切换浏览器（Chrome → Safari）数据也丢。
  `mcp-feedback-enhanced` v1.2.23 + `imhuso/cunzhi` 都把 Prompt
  / 常用回复以 JSON 文件形式分发，是基础生产力门槛。

  **设计决策**：
  1. **envelope schema 与 storage schema 解耦** — 导出文件用独立
     `EXPORT_SCHEMA_VERSION`（当前 1）+ `signature`（魔术串
     `"ai-intervention-agent.quick-phrases"`）+ `exported_at` +
     `phrases`。让未来 storage schema 升级（v2 / v3）时不影响外部
     文件兼容；让 import 校验有一行字符串可拒（防止用户错传别处
     JSON）。
  2. **默认 merge 而非 replace** — 体感最安全。merge 按
     `(label, text)` 元组去重，每条新条目重新分配 `id`，避免
     与本地既有 phrase 撞键；merge 后超 `MAX_PHRASES = 20` 容量
     的剩余条目静默跳过（在 result 里返回 `skipped` 计数让 UI 可
     报告）。
  3. **merge 全是 skip 时弹 confirm 走 replace** — 当用户文件全部
     是「已经存在的常用回复」时，merge 没意义；提示一句"用文件里
     的 N 条替换当前 M 条"让用户拍板。replace 模式下仍受 MAX_PHRASES
     截断（防止文件被人为伪造大数据炸 storage）。
  4. **下载用 `Blob + URL.createObjectURL`，老 IE 兜底 `data:`
     URL** — Blob 路径在主流浏览器（Chrome / Firefox / Safari /
     Edge）都是 first-class；data URL 让极简 webview / 老 IE 也能
     工作。`revokeObjectURL` 故意延迟 100ms，避免某些 Safari 版
     本"过早 revoke 取消下载"的已知 bug。
  5. **导入用 `<input type="file" hidden>"` + `FileReader`** —
     不需要弹 modal、不需要剪贴板权限、与 R125b 「Export tasks」
     按钮的体感一致。`accept="application/json,.json"` 仅是 UX
     提示（OS 文件选择器过滤），真校验仍在 JS 解析层。
  6. **错误路径与成功路径都走 `alert`** — 不引入 toast 系统避免
     与现有 UI 模块耦合；alert 在所有浏览器都立即可见，对低频
     操作（导入 / 导出，每个用户每月 ≤ 1 次）足够。

  **实现**：
  - `static/js/quick_phrases.js` 新增 ~270 行：- 常量 `EXPORT_SCHEMA_VERSION = 1` / `EXPORT_SIGNATURE =
"ai-intervention-agent.quick-phrases"`。- 6 个新函数：`buildExportEnvelope` /
    `exportPhrasesAsJson` / `downloadPhrasesAsFile` /
    `parseImportPayload` / `importPhrasesFromJson` /
    `triggerImportFilePicker` + 内部的
    `handleImportFileChange`。- `bindEventsOnce` 扩展三个新事件源（`#quick-phrases-export-btn`
    click / `#quick-phrases-import-btn` click /
    `#quick-phrases-import-file` change）。- `window.AIIA_QUICK_PHRASES` 暴露 6 个新公开函数 + 2 个新
    常量，给测试 + 未来 R131c（按使用频率排序）复用。
  - `templates/web_ui.html` quick-phrases header 内插入 Export /
    Import 两个按钮 + 隐藏 `<input type="file" accept="application/
json,.json">`，全部带 `data-i18n` / `data-i18n-aria-label`。
  - `static/css/main.css` 把 `.quick-phrases-add-btn` 的全部
    base / hover / focus / disabled / light-theme override 规则
    selector 扩展为 `add | export | import` 三个 class 共享，
    保持视觉一致；header 改用 `margin-right: auto` 把 label 推
    到左侧、3 个按钮挤右侧（替代之前的 `space-between`）。
  - `static/locales/{en,zh-CN}.json` + `_pseudo/pseudo.json`
    新增 10 条 `quickPhrases.*` i18n key（`exportBtn` / 同
    ariaLabel / `importBtn` / 同 ariaLabel / 三种 import 错误
    - 一条 confirm + 两条成功提示），全部带 `{{name}}` Mustache
      参数（替代 R130 v1 的单花括号）以兼容 i18n runtime。

  **测试**（`tests/test_quick_phrases_import_export_r131b.py`，26
  cases / 6 invariant classes）：
  1. **JS API 扩展** — 6 个函数签名 + `window.AIIA_QUICK_PHRASES`
     暴露 6 个新 handle。
  2. **导出 envelope schema** — 4 个顶层字段 + `EXPORT_SIGNATURE`
     与 `EXPORT_SCHEMA_VERSION` 常量值锁定 + 文件名前缀含
     `new Date().toISOString()`。
  3. **HTML 结构** — Export / Import 按钮 + file input 都存在；
     都带 `data-i18n` / `data-i18n-aria-label`；按钮位于
     `#quick-phrases-list` 之上。
  4. **导入校验枝** — JSON 解析失败 / schema 不匹配 / 过滤后为空
     / signature 防误导入 / replace 模式分支 / MAX_PHRASES 容量
     约束。
  5. **i18n 完备性** — 3 份 locale 都含 10 个新 key + 关键参数化
     字符串（`importConfirmReplace` / `importSuccessMerge`）
     的 Mustache 占位符锁定。
  6. **CSS 样式合并** — 三类按钮 selector 出现在同一规则块的
     selector group（防止未来误把 export / import 拆出去）。

  助手用一个手写的 `_extract_function_body` brace counter
  抽取嵌套 `{}` 的函数体（`parseImportPayload` / `importPhrasesFromJson`
  含多层 try / forEach / object literal，朴素 `.*?\}` 非贪婪
  正则停在第一个内层闭合 `}`）。

  **验证**：26/26 R131b + 19/19 R130 + 16/16 R131 = 64/64 quick-
  phrases 全套零回归；`uv run python scripts/ci_gate.py` exits 0。

  **未来工作**：R131c「按使用频率排序」（chip 单击时记录
  `last_used_at` / `use_count`，渲染时按 `last_used_at`
  desc 主排 + `use_count` desc 二排）。

- **R125c** — **(feature)** `GET /api/tasks/export` 增加
  `?include_images={true|false|1|0|yes|no}` query 参数，让用户在
  「需要 base64 图像作完整快照」与「只要文本、要小文件」两种典型
  备份场景之间显式切换。

  **背景**：R125 上线后第一个被反复提到的痛点是「JSON 文件太大」。
  实测一个 4 张截图 + 5 个 task 的工作集，base64 化的
  `result.images[].data` 把导出膨胀到 8-12MB，导致：
  1. 浏览器从「保存对话框」到落盘有 1-2 秒可感知卡顿；
  2. CI / 备份脚本周期性轮询 `/api/tasks/export` 时无谓占用磁盘；
  3. 把导出贴进 chat / Slack / 邮件附件时频繁触发大小限制。

  **设计决定**：
  1. **query 参数而非新端点** — 不引入 `/api/tasks/export-light`
     这种 path 二叉化，保持 REST 路由表收敛；语义只是「同一份快照
     的不同投影」，符合 query 参数定位。
  2. **默认 `true`** — 不破坏 R125 既有 curl / 自动化用户的字节级
     输出，不需要改 client 代码就能继续拿到完整 base64。
  3. **解析宽松、未识别值退回 default** — `_parse_bool_query`
     接受 `true/1/yes/on` 与 `false/0/no/off`，写 `include_images=truee`
     时不会触发 500，符合 query 参数 best-effort 习惯（与
     `configparser.BOOLEAN_STATES` 一致）。
  4. **保留图片元数据 + 顶层标记** — `include_images=false` 时
     仅剥掉 `data` 字段，保留 `filename / size / content_type /
mime_type / mimeType`，并加 `images_stripped: true`，让消费方
     一眼分辨「这次导出已经故意剥图」而不是「上传时就没图」。
  5. **Markdown 模式同步生效** — Markdown 模式把 result 序列化成
     JSON 块，复用同一份 `_strip_images_from_result`，避免「JSON
     瘦了，Markdown 还胖」的不一致。
  6. **顶层 payload 加 `include_images` 字段** — 让自动化下游能
     从导出文件本身判断「这是 light 还是 full 快照」，避免靠文件
     名 / mtime 推断的脆弱合同。

  **实现**：
  - `src/ai_intervention_agent/web_ui_routes/task.py` 新增 module-
    级 `_TRUTHY_QUERY` / `_FALSY_QUERY` / `_parse_bool_query` /
    `_strip_images_from_result` 工具，纯函数无副作用，便于直接
    在测试里覆盖。
  - `export_tasks()` 把 query 参数解析、result 净化、Swagger
    parameter 描述全部插入到 R125 已有路径上，未碰原有 happy path
    序列化逻辑；JSON 顶层 payload 增加 `include_images` 镜像值。
  - Swagger spec 在 `parameters` 里登记 `include_images` enum，
    `flasgger` 渲染 `/apidocs/` 时立刻可见。

  **测试**（`tests/test_tasks_export_include_images_r125c.py`，14
  例）：
  - **Helper 单元**：`_parse_bool_query` 真值/假值/未识别/None
    分支；`_strip_images_from_result` 在 `include_images=True` /
    `result=None` / 无 `images` 字段 / 异常元素混入 / 多张图共存
    场景下的预期行为。
  - **HTTP 集成**：用真实 `WebFeedbackUI` + `complete_task` API
    塞入带图任务，分别请求 `?include_images=true` / `=false`，
    断言 `tasks[*].result.images[*]` 是否含 `data` / 是否带
    `images_stripped` 标记 / 顶层 `include_images` 镜像正确。
  - **Query 解析鲁棒性**：truthy / falsy alias 全集 + 拼错值
    退回默认（`include_images=truee` 不 500）。

- **R131** — **(feature)** Quick Phrases 面板补齐「编辑既有 phrase」+
  「光标位置插入」两块 R130 v1 的 UX 缺口（Code Review #2 标注的 P1
  follow-up）。

  **背景**：R130 v1 上线后两个 UX 痛点立刻暴露：
  1. **chip 不可编辑** — 拼错 label / 改一句话措辞，只能"删了重建"，
     `created_at` 时间戳归零，未来基于使用频率排序的特性会被破坏。
     mcp-feedback-enhanced 的 Prompt Management 一开始就支持原地
     编辑，是基础生产力门槛。
  2. **chip 单击只追加到 textarea 末尾** — 用户想"在段落中间补一句
     常用语"时不方便（要手动复制粘贴 / 剪切），破坏选区上下文。
     cunzhi 的「常用回复」与浏览器内置的「自动填充」都是「光标位置
     插入」语义，R130 v1 的"末尾追加"是设计裁剪而不是用户期望。

  **R131 修复**：
  1. **chip 上的 ✎ 编辑按钮**（`.quick-phrase-chip-edit`）：
     - U+270E 字符（pencil）+ `aria-label` + `data-i18n-aria-label`
       挂 `quickPhrases.editBtnAriaLabel`，屏幕阅读器朗读「编辑常用
       回复」/「Edit quick reply」。
     - hover 时变 primary-500（紫色）与删除按钮的红色明确区分。
     - 单击 → 调 `openEditForm(p.id)` 进入内嵌编辑模式（**不**触发
       chip 主单击的"插入到 textarea"，靠 `e.stopPropagation()`）。

  2. **`_openForm(mode, phrase)` 共用渲染逻辑**：
     - R130 的 `openAddForm` 拆成了 `_openForm` + 两个入口
       `openAddForm()` / `openEditForm(id)`，零重复代码。
     - form 节点写 `dataset.qpMode = "add" | "edit"` +
       `dataset.qpEditId = <id>`，让重复触发能正确「同模式同条
       phrase 复用、否则清空重建」，避免在用户双击 ✎ 时叠两层 form。
     - `edit` 模式时光标停在 text 末尾（`setSelectionRange(len, len)`），
       `add` 模式时 label input 自动 focus。
     - `edit` 模式校验时**不计入** `MAX_PHRASES` 容量上限——替换
       不增加条数，避免在已经 20 条满的情况下连编辑都不让。

  3. **`editPhrase(id, label, text)` 新 CRUD 函数**：
     - 仅替换同 id 条目的 `label` / `text`，**保留** `id` /
       `created_at` 不变（不调 `generateId()` / 不写 `Date.now()`，
       受静态测试锁定）。
     - 走与 `addPhrase` / `deletePhrase` 同一 `savePhrases` +
       `renderList` 链，保证 localStorage 写入的原子性 + UI 自动
       刷新。

  4. **光标位置插入**（`insertTextIntoFeedback` 重写）：- 标准 splice：`current.substring(0, start) + text +
current.substring(end)`，选中文本被替换、光标停在
     `start + text.length` 即新插入文本之后。- 老引擎 fallback：`selectionStart` / `selectionEnd` 任一不
     存在 → 走 R130 v1 的「末尾追加 + 必要换行」分支，向后兼容
     绝对不破坏既有用户。- 仍触发原生 `input` Event 让 multi_task.js 的
     `taskTextareaContents[activeTaskId]` autosave 跟上。

  5. **i18n（3 份 locale）**新增 `quickPhrases.editBtnAriaLabel`：
     - zh-CN: "编辑常用回复"
     - en: "Edit quick reply"
     - pseudo 由 `scripts/gen_pseudo_locale.py` 自动派生。

  **公开 API 扩展** —— `window.AIIA_QUICK_PHRASES` 新增
  `editPhrase` / `openEditForm` 两个函数，给测试 + 未来 R131b
  导入导出功能复用。

  **测试**：`tests/test_quick_phrases_edit_r131.py`（NEW，
  16 cases / 5 invariant classes）：
  - **JS API 扩展**（4）：`editPhrase(id,label,text)` / `openEditForm(id)`
    函数签名锁定、公开 API 暴露、`editPhrase` 不调 `generateId()` /
    不写 `created_at: Date.now()`（保留 id + 时间戳锁定）。
  - **chip 编辑按钮**（5）：`renderList` 创建
    `.quick-phrase-chip-edit`、用 `\\u270e` (✎)、挂正确
    `data-i18n-aria-label`、CSS 选择器存在、click → `openEditForm(p.id)`。
  - **form mode + dataset**（3）：`form.dataset.qpMode` 写入、
    `form.dataset.qpEditId` 写入、保存按钮按 mode 分流到
    `editPhrase` / `addPhrase`。
  - **光标插入语义**（4）：读 `selectionStart` / `selectionEnd`、
    用 `substring(0,start)+text+substring(end)` 三段拼接、
    `hasSelectionApi` 老引擎兜底分支存在、
    `newCursorPos = start + text.length` 光标停留点正确。
  - **i18n**（3）：3 份 locale 都包含 `editBtnAriaLabel` 且非空。

  **验证**：16/16 新 R131 + 19/19 R130 + R125b/R125 周边 47 用例零
  回归；`uv run python scripts/ci_gate.py` exits 0。

  **未来工作**：R131b 计划补「导入 / 导出全部 phrases 为 JSON」（剪贴
  板 + 文件下载）实现跨设备 + 跨浏览器迁移；R131c 计划「按使用频率
  排序」（chip 单击时记录 `last_used_at` / `use_count`，渲染时按
  这两个字段排序）。

- **R130** — **(feature)** Web UI 反馈输入框上方新增「Quick Replies /
  常用回复」面板：纯前端 + localStorage 持久化、单击 chip 即把内容
  追加到反馈输入框，对齐 mcp-feedback-enhanced 的 "Quick Replies" 与
  imhuso/cunzhi 的「常用回复和快捷面板」。

  **背景**：本项目此前没有「常用片段」机制 —— 用户每次都要手敲
  `继续` / `修复这个 bug` / `这个方案不错` / `请加上单元测试` 这类
  高频回复，体感重复、易输错。竞品调研（GitHub / 爆款博客）显示：
  - mcp-feedback-enhanced（v1.2.23, 2026-03）已经把 "Prompt
    Management / Quick Replies" 作为核心生产力特性；
  - cunzhi v0.4.0（imhuso，1280+ stars）的 README 第一屏就把
    「常用回复和快捷面板」并列在「项目级记忆管理」、「智能拦截」之列。
    R130 把这块短板补齐，但**不引入后端 API / 配置 schema / 跨进程
    同步**——把复杂度天花板压到「单一 JS 文件 + 单一 localStorage key」。

  **设计决策**（每条都有舍弃路径）：
  1. **localStorage 而非后端 config**：常用回复本质是用户私有，不
     应进 `config.toml`（同步给 MCP server 既无意义又有隐私漏洞）；
     卸载后端不丢用户数据；零 API surface 即零回归风险。
  2. **追加而非替换**：单击 chip 把内容追加到 textarea 末尾、必要
     时前置换行——支持「组合多个常用片段」的工作流（如先「继续」
     再「修复 bug」）。要替换的用户全选删除一次即可。
  3. **内嵌 form 而非 modal**：避免新增焦点陷阱 / 全屏遮罩 / ESC
     堆栈管理。`window.confirm` 用于删除二次确认（VSCode webview
     已知不禁用 confirm，浏览器原生支持）。
  4. **20 条容量上限**：localStorage 单 origin 共享 5 MB 配额；
     20 × (30 char label + 2000 char text + JSON 包装) ≈ 50 KB，
     远低于 1% 配额。命中上限时校验文案明确告警。
  5. **零 innerHTML / 全 DOMSecurity 化**：所有 chip / 按钮 / 输入
     框走 `createElement + textContent`，符合项目 R71-CSP / dom-
     security.js 防 XSS 基线；用户输入的 label 和 text 即使含
     `<script>` 也不会被解析。
  6. **failure-tolerant**：localStorage 不可用（隐身模式 / 配额满 /
     浏览器禁用）→ 面板自动 disable + 显示「本地存储不可用」文案，
     不抛 JS 异常炸面板。损坏数据（JSON 解析失败 / schema 不匹配）
     → 自动回退到空数组，不向用户暴露报错。

  **实现要点**：
  - **新文件 `static/js/quick_phrases.js`** (~440 行)：- 模块自封闭 IIFE，公开 API 挂在 `window.AIIA_QUICK_PHRASES`
    （只暴露 `loadPhrases` / `addPhrase` / `deletePhrase` /
    `insertTextIntoFeedback` / `validatePhraseInput` /
    `init` 等，给测试 + 未来 R131 编辑功能复用）。- localStorage key：`aiia.quickPhrases.v1`（带版本号，将来
    schema 升级时改 v2 / v3 老 key 自动失效）。- 数据 schema：`{schema_version: 1, phrases: [{id, label,
text, created_at}]}`，id 用 `qp_<ms>_<3 位 base36>` 防同毫秒
    撞 id（不依赖 `crypto.randomUUID`，老浏览器 / webview 兼容）。- `insertTextIntoFeedback` 触发原生 `input` Event，让
    multi_task.js 的 `taskTextareaContents[activeTaskId] = ...`
    autosave 链路自动跟上当前内容（避免切换任务后内容丢失）。- i18n 走 `window.AIIA_I18N.t`，未就绪时回退到内置**英文**
    FALLBACK_TEXT（受 `check_i18n_js_no_cjk.py` 守门），
    `i18n.init()` 完成后由 `applyTranslationsToDOM()` 自动覆盖。

  - **`templates/web_ui.html`**：在 `.textarea-container` 之上插入
    `#quick-phrases-container`（label + add-btn + list + form-host
    四块），`role="region"` + i18n aria-label；模板末尾新增
    `<script defer src="/static/js/quick_phrases.js?v={{ quick_phrases_version }}">`
    引用，依赖 `app.js` 之后加载（i18n / 状态机已就绪）。

  - **`web_ui.py`**：`_get_template_context` 新增 `quick_phrases_version`
    字段，让 `serve_js` 命中 1 年 immutable 缓存（与 R27.2 cache
    contract 对齐）。

  - **CSS（`static/css/main.css`）**：追加 `.quick-phrases-container`
    及其子选择器（chip / chip-delete / form / form-save / form-
    cancel），含浅色主题覆盖 + `@media (max-width: 768px)` 移动端
    收紧。chip 用 primary-500 半透明紫底圆角风格，与项目主题
    一致。

  - **i18n（3 份 locale）**：`zh-CN.json` / `en.json` / 自动派生
    `_pseudo/pseudo.json` 各新增 17 个 `quickPhrases.*` key
    （label / addBtn / addBtnAriaLabel / empty / disabled /
    formLabelPlaceholder / formTextPlaceholder / formSave /
    formCancel / deleteBtnAriaLabel / chipTitle /
    errorLabelEmpty / errorTextEmpty / errorLabelTooLong /
    errorTextTooLong / errorTooMany / confirmDelete）。
    `confirmDelete` 用 `{{label}}` 双花括号 Mustache（与
    `static/js/i18n.js::_interpolateMustache` 契约一致——
    `static/js/i18n.js` 不识别裸 `{name}` 单括号）。

  **测试**：`tests/test_quick_phrases_panel_r130.py`（NEW，
  19 cases / 6 invariant classes）：
  - **HTML 结构**（4）：`#quick-phrases-container` 存在、4 个子节
    点（label / add-btn / list / form-host）齐全、面板挂载在
    `#feedback-text` **之前**（视觉位置锁定）、添加按钮带 i18n /
    aria-label。
  - **JS 模块**（3）：`window.AIIA_QUICK_PHRASES` 命名空间暴露、
    `<script>` 标签在 `app.js` 之后加载、模块代码本体零
    `innerHTML`（XSS 防御静态 lock）。
  - **i18n 完备性**（3）：`zh-CN.json` / `en.json` /
    `_pseudo/pseudo.json` 三份 locale 都包含 17 个
    `quickPhrases.*` key 且非空。
  - **CSS 样式**（3）：`.quick-phrases-container` /
    `.quick-phrase-chip` / `.quick-phrase-chip-delete` /
    `.quick-phrases-form` / `.quick-phrases-form-save` 五个核心
    selector 出现；浅色主题覆盖到位。
  - **localStorage schema 锁定**（3）：`STORAGE_KEY` /
    `SCHEMA_VERSION` / `LABEL_MAX_LEN=30` / `TEXT_MAX_LEN=2000` /
    `MAX_PHRASES=20` 数值 string-locked，防止意外漂移破坏既有
    用户数据。
  - **回归保护**（3）：`#feedback-text` textarea 仍存在、R125b 的
    `#export-tasks-btn` 仍存在、`_get_template_context` 已填充
    `quick_phrases_version`（不填 ?v= 渲成空串会让缓存策略从
    immutable 降级到 1 天，性能回退）。

  **验证**：19/19 新 R130 测试通过；`R125b / R125 / R22.3` 周边
  46 用例零回归；`uv run python scripts/ci_gate.py` exits 0
  （ty 静态检查 / ruff 格式 / 浅色主题视觉、`scripts/check_i18n_*`
  四套 i18n 守门、locale parity 校验、HTML 模板零硬编码 CJK
  - JS 源零硬编码 CJK 全部通过）。

  **未来工作**：R131 计划补「编辑现有 phrase」（chip ✎ 按钮 →
  内嵌编辑模式）+ 跨设备 sync（导出 / 导入 JSON）。当前 v1
  的「删了重新加」是有意识的功能裁剪，让单 commit 颗粒可控。

- **R125b** — **(feature)** Web UI 顶栏新增「Export Tasks」下载按钮，
  把 R125 后端导出 API 暴露给浏览器用户，无需 curl 即可一键备份当前
  会话快照。

  **背景**：R125 已经实现 `GET /api/tasks/export?format={json,markdown}`
  并在 CHANGELOG 中预告 "follow-up R125b will surface this endpoint
  in the Web UI"。在 R125b 之前，桌面端用户必须手动拼接 URL 才能下
  载快照——和"Multi-Task / Settings 都是按钮一键调用"的产品基线
  不一致；并且 TaskQueue 完成态保留窗口只有 10 s，错过窗口快照就
  消失了。R125b 把按钮放到顶栏 `header-actions` 内、theme toggle
  和 settings 之间的固定位置，让操作路径和「切主题」、「打开设置」
  保持同样的肌肉记忆。

  **实现要点**：
  1. **HTML（`templates/web_ui.html`）** — 用 `<a download
href="/api/tasks/export?format=markdown">` 而不是 `<button>`：
     原生 `download` 属性让浏览器尊重后端的
     `Content-Disposition: attachment; filename=...` 响应头，
     不需要任何 JS 也能正常落盘；`href` 默认指向
     `?format=markdown`，因为 Markdown 形态对人类阅读和分享更
     友好（JSON 形态由 curl/CLI 用户继续直访）。
     按钮内嵌一个下载箭头 SVG（`viewBox="0 0 24 24"`，
     `currentColor` 着色，与 settings/theme 图标视觉权重一致），
     并通过 `data-i18n-aria-label` / `data-i18n-title` 把所有文案
     都纳入现有的 i18n 管线。

  2. **i18n（3 份 locale）** — 同时更新 `zh-CN.json`、`en.json`
     和自动派生的 `_pseudo/pseudo.json`：
     - `exportTasksBtn`: 中文 `导出任务`、英文 `Export Tasks`、
       pseudo 自动生成。
     - `exportTasksBtnAriaLabel`: 中文 `导出当前会话任务为 Markdown
文件`、英文 `Export current session tasks as a Markdown
file`、pseudo 自动生成。
       更新后由 `scripts/gen_pseudo_locale.py` 重新生成 `_pseudo`
       locale，保证 `scripts/ci_gate.py` 的
       `--check` 不再报 `stale pseudo.json`。

  3. **CSS（`static/css/main.css`）** — 把 `.export-btn` 选择器
     合并进所有现有 settings/theme 按钮的 selector list，
     **零新增样式块**就拿到完整的 hover / active / focus / 浅色
     主题适配。同时显式覆盖 `:visited`：

     ```css
     .export-btn:visited {
       color: inherit;
       text-decoration: none;
     }
     ```

     原因——`<a>` 默认 `:visited` 是紫色 + 下划线，导致下载过
     一次后按钮颜色和图标都会变 ugly；显式重置确保按钮永远
     和它旁边的 `<button>` 视觉一致。

  4. **预压缩静态资源（`.gz`/`.br`）** — `main.css.gz`、
     `main.css.br`、`main.min.css.gz/.br`、`zh-CN.json.gz/.br`、
     `en.json.gz/.br`、`_pseudo/pseudo.json.gz/.br` 全部通过
     现有 build pipeline 重新打包，避免 `Content-Encoding:
gzip|br` 响应路径返回旧版资产。

  **测试**：`tests/test_export_button_ui_r125b.py`（NEW，
  16 cases / 5 invariant classes）：
  - **HTML 结构**（5）：
    `id="export-tasks-btn"` 存在、`<a download>` 标签使用
    （非 `<button>`、非空 `download`）、`href` 指向
    `/api/tasks/export?format=markdown`、内嵌 SVG 图标存在、
    按钮挂在 `header-actions` 内 theme toggle 之后 settings 之前。
  - **i18n 完整性**（3）：`zh-CN.json` / `en.json` /
    `_pseudo/pseudo.json` 三份 locale 都包含
    `exportTasksBtn` 和 `exportTasksBtnAriaLabel` 两个键。
  - **CSS 视觉对齐**（3）：`.export-btn` 出现在 settings/theme
    现有 selector list 中、`.export-btn:visited` 重置规则
    存在、浅色主题选择器 list 也包含 `.export-btn`。
  - **i18n 标记**（2）：HTML 中按钮节点带
    `data-i18n-aria-label="exportTasksBtnAriaLabel"` 与
    `data-i18n-title="exportTasksBtn"` 标记，确保运行时切换语言
    时按钮文案能被 `i18n.applyTranslationsToDOM()` 替换。
  - **回归保护**（3）：theme toggle 按钮仍然存在、settings
    按钮仍然存在、`.settings-btn` 的样式块没有被合并破坏。

  **验证**：16/16 新 R125b 测试通过；既有 4055 用例零回归；
  `uv run python scripts/ci_gate.py` exits 0；浏览器手动验证
  确认点击按钮即触发原生下载、浏览过的状态颜色与 settings
  按钮一致、深浅主题切换无视觉脱节。

- **R125** — **(feature)** new `GET /api/tasks/export?format={json,markdown}`
  endpoint for full-fidelity session-history export.

  **Background**: pre-R125 the project had three task-related read
  endpoints — `GET /api/tasks` (lightweight list, prompt truncated
  to 100 chars), `GET /api/tasks/<id>` (single-task detail, but
  requires knowing the id list up-front), and `GET /api/feedback`
  (read-once feedback channel). None of them serves the
  "back up everything from this session for audit / sharing /
  later review" use case. With the TaskQueue cleanup window of
  10 s for completed tasks, users (or the AI agent itself, via
  curl) had a very narrow window to capture a snapshot before it
  was gone.

  **R125 fix**: ship a dedicated read-only export endpoint with
  two formats:
  - `GET /api/tasks/export?format=json` →
    `application/json` body with:
    - `schema_version: 1` (locked-by-test, future-proofed)
    - `exported_at` (ISO 8601 UTC)
    - `server_time` (epoch float)
    - `stats` (pending / active / completed counts)
    - `tasks[]` with **full** prompts (no truncation), all
      predefined options + defaults, full `result` payload
      including `images` base64, monotonic + wall-clock
      timestamps.
  - `GET /api/tasks/export?format=markdown` →
    `text/markdown; charset=utf-8` body styled as a session
    transcript:
    - H1 title + stats summary header.
    - One section per task with status, timestamps, prompt
      block, options checklist (`- [x]` / `- [ ]` reflecting
      `predefined_options_defaults`), and a JSON-fenced
      result block when present.
    - Prompt body wrapped in **4-backtick** GFM fences
      (` ` `` `markdown` `` ` `) so prompts
      containing their own \`\`\` fences don't break
      rendering.

  **Common contract**:
  - `Content-Disposition: attachment; filename="ai-intervention-agent-tasks-YYYYMMDDTHHMMSSZ.{ext}"`
    so browsers download the snapshot rather than render it
    inline (preserves snapshot fidelity + enables time-sorted
    archives on the user's machine; the `T...Z` form avoids
    Windows-illegal `:` chars in filenames).
  - Default `format=json`; case-insensitive parsing
    (`format=JSON` works); whitespace-tolerant
    (`format=%20markdown%20` works).
  - Unsupported `format` → 400 with
    `{"success":false,"error":"unsupported_format","message":"format 必须是 json 或 markdown"}`.
  - Read-only — does **not** mutate task state, completion
    timestamps, or queue order. Shares the
    `get_all_tasks_with_stats()` single-RWLock atomic snapshot
    with `GET /api/tasks` to avoid "half-state" exports that
    catch the queue mid-mutation.
  - Rate-limited 30/min (matched to `update_feedback_config`),
    permitting hand batch backups but rejecting crawler-style
    scraping.

  **docstring constraint** (locked by an existing R23.3 test):
  the endpoint's docstring keeps all human prose (implementation
  notes, privacy boundary) **outside** the `---` YAML block
  using ordinary `#` comments. `flasgger` parses the full
  docstring as YAML and would `ScannerError` on free-form
  Chinese sentences containing `:`/`-` lookalikes
  (`Content-Disposition: attachment` would be read as a YAML
  mapping). Discovered the hard way during R125 implementation;
  guard rail is `test_enabled_apispec_returns_json`.

  **Tests**: `tests/test_tasks_export_endpoint_r125.py` (NEW,
  20 cases / 5 invariant classes):
  - **JSON contract** (8): endpoint exists, default & explicit
    `format=json` both work, `schema_version=1` locked,
    top-level fields present (`success`/`schema_version`/
    `exported_at`/`server_time`/`stats`/`tasks`), full-prompt
    fidelity (no 100-char truncation), all task fields present
    in each item, completed-task `result` round-trips through
    export.
  - **Markdown contract** (6): explicit `format=markdown`
    works, filename has `.md` extension, header + stats summary
    rendered, 4-backtick fences used for prompts, options
    rendered as `[x]` / `[ ]` checklist matching
    `predefined_options_defaults`, completed result rendered as
    JSON-fenced block.
  - **format param** (3): unsupported value returns 400 with
    structured error, case-insensitive accept, whitespace-tolerant.
  - **Empty + boundary** (2): empty queue still returns 200
    with `(No tasks in queue.)` Markdown marker / empty `tasks`
    array; consecutive exports do not modify the queue
    (read-only verification via before/after `/api/tasks`
    diff).
  - **Filename** (1): ISO 8601 timestamp `YYYYMMDDTHHMMSSZ`
    format locked.

  **Future work**: a follow-up R125b will surface this endpoint
  in the Web UI (download button in the settings panel +
  i18n strings + VS Code extension parity) so users get the
  feature without needing to know about curl/browser direct
  access.

  **Verification**: 20/20 new R125 tests pass; existing 4055
  test suite untouched; `flasgger` swagger spec generation
  (R23.3 invariant) confirmed unaffected by the new endpoint;
  `uv run python scripts/ci_gate.py` exits 0.

### Fixed

- **R129** — **(readability)** purge dead-code tombstone comments
  from `static/js/app.js` while keeping all live behaviour intact.

  **Background**: `app.js` accumulated three classes of "RIP"
  scaffolding from earlier refactors:
  1. **A 28-line banner block** announcing "内容轮询 - 已停用"
     (lines 1203–1219 pre-R129) explaining why `stopContentPolling`
     became a no-op. Useful once; thereafter pure noise on every
     read.
  2. **A "updatePageContent() 已删除" stub comment** (lines
     1232–1236 pre-R129) listing the three `multi_task.js`
     functions that replaced it. Anyone who needs that mapping
     today can `git log -S updatePageContent` in 2 s.
  3. **Two duplicated `// startContentPolling() // 已停用`
     drop-stubs** in the `loadConfig().then()` (line 1356 pre-R129)
     and `.catch()` (line 1368 pre-R129) paths — explicitly
     showing a function call that _isn't being made_. Negative
     evidence rarely belongs in production source.

  **R129 fix**:
  - Replace the 28-line banner with a **5-line explanation**
    pinned directly above `function stopContentPolling()` —
    keeping the _one_ genuinely useful invariant ("function
    must remain because `closeInterface()` calls it") and
    dropping the historical narrative.
  - Delete the `updatePageContent() 已删除` stub block entirely.
  - Replace both `// startContentPolling() // 已停用` lines with
    a positive-form note explaining what _is_ happening: the
    `loadConfig` chain delegates init to `multi_task.js`, with a
    3 s `setTimeout` in the catch branch giving the browser
    `console.error` a render window before the panel renders.
  - **Crucially**: keep `function stopContentPolling()` itself
    intact — `closeInterface()` (line ~1151) still calls it; if
    we drop the function we get
    `ReferenceError: stopContentPolling is not defined` mid-
    close-flow. R129 is about killing tombstones, not behaviour.

  **Tests**: `tests/test_app_js_dead_comment_purge_r129.py`
  (NEW, 7 cases / 4 invariant classes — all _reverse-locks_):
  - **No `startContentPolling()` tombstone form** (2): the
    literal `// startContentPolling() // 已停用` regex must not
    match anywhere; the bare token `startContentPolling` may
    appear at most once in the file (allowing a future R129
    revisit comment to mention it without breaking the lock).
  - **No `updatePageContent` tombstone** (2): same shape — the
    `// updatePageContent() 已删除` regex banned, token count
    capped at 1.
  - **No 3+ consecutive `// ====...` lines** (1): historical
    pre-R129 banner notes used 3-line `// === / // === foo / // ===`
    layouts. Capping consecutive banner lines at 2 prevents
    fresh tombstones from sneaking in via copy-paste.
  - **Close-flow contract preserved** (2): `function stopContentPolling()`
    still defined; `closeInterface()` still calls it. If a future
    contributor drops either, this test fires before they ship
    the broken close-button.

  **Verification**: 7/7 new R129 tests pass; existing R22.3,
  R123, R128 tests pass; full `uv run python scripts/ci_gate.py`
  exits 0.

- **R128** — **(perf)** stop `startTaskCountdown`'s 1 Hz `setInterval`
  callback from doing pointless DOM writes when the page is hidden,
  and add a `visibilitychange` → `forceUpdateAllTaskCountdowns`
  edge sync so users see the correct countdown numbers the
  instant they switch back to the tab.

  **Background**: each concurrent task installs a 1 Hz
  `setInterval` that, every tick, does:
  - `getElementById('countdown-${taskId}')`
  - `.querySelector('circle')` + `.querySelector('.countdown-number')`
  - `circle.setAttribute('stroke-dashoffset', offset)`
  - `numberSpan.textContent = remaining`
  - `countdownRing.title = _t('page.countdown', {seconds})`
  - `updateCountdownDisplay(remaining)` for the active task

  Browsers throttle hidden-tab `setInterval` to ~1 Hz on
  Chromium / WebKit but **do not** halt the callback, so each
  tick still walks the DOM and triggers Layout/Paint cost
  recompute (even with no visible pixels — DOM mutation is
  itself a reflow trigger). N concurrent tasks × user-tab-
  hidden-for-5-min = N × 300 redundant DOM operations on a
  long-lived "AI agent waits hours for human reply" sidebar.

  R123 already nailed _health-check_ and _task-polling_
  visibility lifecycles; R128 closes the parallel gap on the
  _task-countdown_ timer.

  **R128 fix**:
  - In the per-task `setInterval` callback, gate **all DOM
    writes** behind `if (!documentHidden) { ... }`.
  - Keep `calculateRemainingFromDeadline()` running every tick
    regardless of visibility (deadline is wall-clock; the
    `remaining <= 0 → autoSubmitTask` branch must still fire on
    schedule even if the tab is hidden — otherwise a task that
    expires while the user is away gets quietly delayed by
    however long they stay on another tab, breaking the
    "auto-submit when no human reply" contract).
  - The `remaining <= 0 → autoSubmitTask` branch lives **outside**
    the hidden-guard for the same reason. Locked by a dedicated
    test (`test_auto_submit_branch_not_inside_hidden_guard`).
  - Add `forceUpdateAllTaskCountdowns()` helper: walks
    `taskCountdowns`, force-syncs SVG ring + number + main
    countdown UI for every alive timer in one shot.
  - Add `installCountdownVisibilitySyncHandlerOnce()` (idempotent,
    flag-guarded by `window.tasksCountdownVisibilityHandlerInstalled`):
    attaches a single document-level `visibilitychange` listener
    that calls `forceUpdateAllTaskCountdowns()` on the visible
    edge, eliminating the "switch back to tab → see stale digit
    for 0–1 s before next tick lands" UX seam.
  - `startTaskCountdown` calls the install helper on first
    invocation; downstream calls hit the flag-guard early-return.
  - Export both helpers via `window.multiTaskModule` so test
    harnesses / Storybook / SPA-embed scenarios can drive the
    UI-sync path deterministically without faking DOM events.

  **Why a separate visibility handler instead of piggybacking
  on the polling one (R123)**:
  - Countdown and polling are different lifetime axes: a
    countdown still has to walk wall-clock locally even if
    polling is paused (deadline-based auto-submit must fire
    regardless).
  - Decoupling lets future "pause polling but keep countdown"
    or vice-versa stay clean; coupling them now would force a
    refactor when one diverges.

  **Tests**: `tests/test_task_countdown_hidden_tab_r128.py`
  (NEW, 15 cases / 5 invariant classes):
  - **`startTaskCountdown` hidden-skip** (3): body checks
    `document.hidden`; DOM writes gated by `if (!documentHidden)`;
    `calculateRemainingFromDeadline` runs _outside_ the guard.
  - **`autoSubmit` not gated** (1): the `remaining <= 0`
    branch must lie strictly after the hidden-guard `}`,
    locking the "expired-while-hidden still auto-submits" contract.
  - **`forceUpdateAllTaskCountdowns` helper** (3): function
    defined; early-returns when hidden; iterates
    `Object.keys(taskCountdowns)`.
  - **`installCountdownVisibilitySyncHandlerOnce` idempotency**
    (5): function defined; uses the flag-guard;
    `addEventListener('visibilitychange', …)`; visible branch
    calls `forceUpdateAllTaskCountdowns`; the global flag is
    initialised `= false`.
  - **`startTaskCountdown` install path** (1): body calls
    `installCountdownVisibilitySyncHandlerOnce()`.
  - **Module export surface** (2): `window.multiTaskModule`
    re-exports both helpers.

  **Verification**: 15/15 new R128 tests pass; existing
  R22.3 + R123 lifecycles untouched (10/10 + 8/8 still pass);
  `uv run python scripts/ci_gate.py` exits 0.

- **R123** — **(perf + correctness)** fix `multi_task.js` health-check
  `setInterval` orphan: assign the returned interval-id to
  `window.tasksHealthCheckTimer` and gate it through symmetric
  `startTasksHealthCheck` / `stopTasksHealthCheck` lifecycle
  functions; wire `visibilitychange` (hidden) and `beforeunload`
  to also call `stopTasksHealthCheck` so the 30 s health-check
  tick can actually be reclaimed.

  **Background**: pre-R123 `initMultiTaskSupport` ended with
  `setInterval(function () { ... }, 30000)` whose return value
  was never bound. That made the timer **structurally
  unreclaimable** — `clearInterval` requires the id, and there
  was none to pass.

  Two failure modes followed:
  1. **Background tab CPU/scheduler waste** — `visibilitychange`
     stopped polling but the 30 s health-check timer kept
     ticking; macOS / iOS Safari throttles hidden-tab
     `setInterval` to ~1 Hz but does _not_ halt it, so each tick
     still cost a callback dispatch + `if (document.hidden)
return` early-out. On a long-lived sidebar (typical for
     "AI agent waits 4 hours for human reply" workflows) this
     adds up. More importantly, the "early-out" branch hides
     the symptom from any developer who only checks "did the
     UI freeze?".
  2. **Latent leak when `initMultiTaskSupport` is called more
     than once** — the `app.js` `loadConfig().then(...)` /
     `.catch(setTimeout(...))` shape is mutex today, but any
     future "reconnect → re-init" path (already partly
     contemplated by R20.11 mDNS-async-publish + the new
     SSE/poll fallback machinery) would silently spawn a second
     30 s timer that would **also** call `startTasksPolling` /
     `_connectSSE` on its own ticks — racing with the originals
     and eventually reaching a steady state of "polling +
     SSE-reconnect chatter doubles every reload of
     `initMultiTaskSupport`". Hard to debug because each tick
     looks correct in isolation.

  **R123 fix**:
  - Add `window.tasksHealthCheckTimer = null` to the file-top
    `if (typeof window... === "undefined")` block, parallel to
    `tasksPollingTimer` / `newTaskHintTimer`.
  - Extract two top-level functions:
    - `startTasksHealthCheck()` — early-return if a timer
      already exists (idempotent), otherwise
      `window.tasksHealthCheckTimer = setInterval(...)`.
    - `stopTasksHealthCheck()` —
      `clearInterval(window.tasksHealthCheckTimer)` + assign
      `null` (idempotent).
  - Replace the inline `setInterval(...)` in
    `initMultiTaskSupport` with a call to
    `startTasksHealthCheck()`.
  - In the `visibilitychange` handler, call
    `stopTasksHealthCheck()` on the `hidden` branch and
    `startTasksHealthCheck()` on the visible branch (matching
    the existing `stopTasksPolling` / `startTasksPolling`
    pair).
  - In `beforeunload`, call `stopTasksHealthCheck()` after
    `stopTasksPolling()` to avoid timer-ref leaks in jsdom /
    SPA-embed scenarios where the same `window` outlives the
    page.
  - Export `startTasksHealthCheck` / `stopTasksHealthCheck`
    from `window.multiTaskModule` so testing harnesses /
    Storybook can drive the lifecycle deterministically.

  **Tests**: `tests/test_tasks_health_check_lifecycle_r123.py`
  (NEW, 8 cases across 5 invariants):
  - **Timer-handle binding** — `setInterval` return value
    must be assigned to `window.tasksHealthCheckTimer`;
    `stopTasksHealthCheck` must `clearInterval` and re-assign
    null; the global must have a default `= null`
    initialisation.
  - **`visibilitychange` hidden-branch** — must call
    `stopTasksHealthCheck()` (regression-lock against
    "stopped polling but forgot health-check").
  - **`beforeunload` handler** — must call both
    `stopTasksPolling()` and `stopTasksHealthCheck()`.
  - **Export surface** — `multiTaskModule` must export both
    `startTasksHealthCheck` and `stopTasksHealthCheck`.
  - **No-bare-setInterval-in-init** — reverse-lock: scan
    `initMultiTaskSupport` body, fail if any literal
    `setInterval(` call is present (forces all health-check
    setup to route through the named function).

  **Verification**: 8/8 new tests pass; 4015 existing tests
  pass; `uv run python scripts/ci_gate.py` exits 0 (still
  green after the R-PRE prereq commit unblocked the pipeline).

- **R122** — **(security + UX)** unify the three front-end
  `SUPPORTED_IMAGE_TYPES` MIME whitelists and remove `image/svg+xml`
  from all of them; bring `validation-utils.js` up to parity with
  `image-upload.js` / `webview-ui.js` by adding `image/jpg` (the
  legacy alias some Edge / Windows clipboard paths still emit).

  **Background**: the front end has three independent upload-validation
  sites (Web UI: `image-upload.js` + `validation-utils.js`; VS Code
  extension: `webview-ui.js`), and all three carried slightly different
  MIME whitelists pre-R122:
  - `image-upload.js` allowed `image/svg+xml` and `image/jpg`
  - `webview-ui.js` allowed `image/svg+xml` and `image/jpg`
  - `validation-utils.js` allowed _neither_ `image/svg+xml` _nor_
    `image/jpg`

  Meanwhile the back-end arbiter (`file_validator.IMAGE_MAGIC_NUMBERS`)
  recognises _zero_ SVG magic-bytes — SVG, being XML text, has no
  binary magic — so any front-end-allowed SVG would inevitably be
  rejected at `/api/submit` once the bytes hit the server. Two
  separate failure modes:
  1. **Security smell** — SVG can carry `<script>` / `onload=` / inline
     `data:` URIs, classic XSS surface ([OWASP SVG security primer](https://owasp.org/www-community/attacks/Server_Side_Request_Forgery_via_SVG_files)).
     The front-end whitelist suggested SVG was supported, which would
     mislead any future contributor adding a "render SVG inline"
     feature into thinking the contract was already covered. R122
     closes that gap before it gets exploited.
  2. **UX break** — a user dragging a `.svg` into the Web UI / VS Code
     panel would see the local validation green-light, confirm upload,
     then watch the multipart POST fail at the server with "无法识别
     的文件格式" — silent failure mode for anyone not watching the
     network tab.

  The `validation-utils.js` site is _especially_ nasty because
  `image-upload.js:75-80` defers to `ValidationUtils.validateImageFile`
  when available — meaning the **stricter** of the two whitelists
  actually applies in production, but the docstrings, type prompts,
  and error messages all read off the **looser** `image-upload.js`
  list. Inconsistent reality vs. apparent contract.

  R122 picks the **strictest-safe** intersection: front-end three
  sites = `{jpeg, jpg, png, gif, webp, bmp}` (six MIMEs, identical
  ordering, byte-for-byte tied to back-end `IMAGE_MAGIC_NUMBERS`).
  SVG is rejected at _every_ layer — no surprise rejection, no
  XSS surface to defend against because the bytes never get
  accepted. Adding SVG support later requires (a) a server-side
  SVG sanitizer (DOMPurify-equivalent), (b) CSP `img-src` review
  for inline-`<svg>` injection paths, (c) sync update to all three
  front-end sites, (d) deletion of the back-end reverse-lock test —
  all of which are intentionally surfaced by the new test file
  failing in (d) so a future contributor can't slip SVG support
  in without getting four reviewers.

  **Files**:
  - `src/ai_intervention_agent/static/js/image-upload.js` — drop
    `'image/svg+xml'` from `SUPPORTED_IMAGE_TYPES`, expand inline
    comment to the back-end-parity rationale + cross-link.
  - `src/ai_intervention_agent/static/js/validation-utils.js` — add
    `'image/jpg'`, expand to a 6-MIME array with comment.
  - `packages/vscode/webview-ui.js` — drop `'image/svg+xml'` and
    update the comment block to point at `image-upload.js` as the
    source of truth.
  - `tests/test_image_mime_whitelist_r122.py` (NEW, 10 tests across
    4 invariants) — three-site parity, three-site SVG rejection,
    three-site `image/jpg` alias presence, back-end `IMAGE_MAGIC_NUMBERS`
    SVG-rejection reverse-lock with explicit "if you want to add SVG,
    here are the four prerequisites" docstring.

  **Verification**: 10/10 new tests pass; existing test suite
  (4015 tests) untouched.

- **R119** — extend the R117 / R118 silent-failure observability audit
  to the **third** cluster of bare-except sites (web routes / mDNS /
  config_modules), fixing the **4 of 8** remaining genuinely-risky
  `except Exception: pass` patterns and **explicitly documenting** the
  4 intentionally-silenced ones.

  Background: R117 covered `notification_*`, R118 covered
  `service_manager.py`. R119 closes the loop by auditing the rest of
  the project-wide grep result. Each site was classified by **user-
  observable symptom** when the silent failure triggers; only sites
  where the symptom is invisible-but-harmful got debug logs, sites
  where the surrounding code already provides observability or where
  the silence is semantically correct stay silent (with documentation
  pointing future contributors at this CHANGELOG so they don't get
  "fixed" by R-series momentum bias).

  **Fixed (4 sites)**:
  1. **`web_ui_routes/notification.py`** —
     `/api/notification/test-bark` calls
     `notification_manager.refresh_config_from_file()` to pick up the
     latest TOML changes before sending the test push. Pre-R119
     silent failure → user clicks "Test" after editing `bark_url` /
     `bark_device_key`, the test fires against the **stale**
     in-memory config, success/failure looks normal but uses
     yesterday's URL. **Real user symptom**: "I changed bark_url and
     hit Test and it worked, but my real notifications still use the
     old endpoint" — actually the test silently fell back to
     in-memory config because `refresh_config_from_file()` raised
     (file lock contention, TOML parse error, permission
     regression). R119 adds debug log so opening DEBUG-level logging
     immediately reveals which read step failed.

  2-3. **`web_ui_mdns.py` × 2** — the hostname-conflict path and the
  general mDNS-publish-failure path both call `zc.close()` to
  release the `zeroconf.Zeroconf` instance. Pre-R119 silent
  failure → `zeroconf` UDP sockets, mDNS responder background
  thread, and DNS cache state leak forever. **Real user symptom**:
  `lsof -p <pid>` shows accumulating UDP sockets; second
  `webui --advertise` invocation after a failed first one fails
  to bind because the orphaned responder still holds the
  conflicting hostname. R119 logs at debug level so the leak is
  traceable; the surrounding `logger.warning(...)` for the main
  mDNS failure stays unchanged (it was already observable, only
  the cleanup leak was hidden). 4. **`config_modules/network_security.py`** —
  `_save_network_security_config_immediate()` calls
  `_create_default_config_file()` to bootstrap the file before
  overwriting it with the network_security section. Pre-R119
  silent failure → the next line's `read_text()` catches "file
  doesn't exist" via its own try/except, so the user sees a
  generic "config save failed" message but the **root cause**
  (e.g. parent directory doesn't exist, permission denied,
  read-only mount, disk full) is destroyed. R119 logs the actual
  `_create_default_config_file()` exception so debug logging
  reveals "ah, my config dir got chmod 444 by some other tool"
  instead of "ConfigManager mysteriously can't write".

  All four follow the same R117/R118 pattern: keep `try/except` (so
  the upstream cleanup / fallback flow doesn't break), add
  `logger.debug` with `[R119]` marker + user-visible symptom hint.
  When the silent failure activates and a user reports the symptom,
  enabling `logging.DEBUG` for the relevant module immediately
  surfaces both the root cause AND the symptom-to-cause mapping.

  **Intentionally silenced (4 sites — documented for future
  contributors)**:
  - **`i18n.py:103-105` + `i18n.py:113-114`** — bootstrap
    fallback for language detection. Runs **before** ConfigManager
    is initialized, so logging may not be configured yet; even if
    it is, the i18n module is loaded by ~every other module and
    must be unconditionally robust. Falls back to `"en"` and the
    user gets English UI — fully graceful.

  - **`config_manager.py:378`** —
    `_is_running_as_uvx_or_isolated()` heuristic. One of several
    detection signals; failure means this signal returns "not
    isolated" and other heuristics still apply. Adding a debug log
    would noise every config load on platforms where this branch
    naturally raises.

  - **`server_feedback.py:540-544`** — best-effort
    `error_detail` enrichment when wrapping a downstream error.
    The original error is already raised with full context; this
    block only **augments** the exception's `error_detail` field,
    so failure means slightly less helpful error details, never a
    lost error. Logging the augmentation failure would be
    counterproductive (you'd log noise about failed-to-format-an-
    error-message right next to the real error).

  - **`server_config.py:692-693`** — `mimetypes.guess_type()`
    backup detection for static asset MIME types. Returning `None`
    is a documented contract value meaning "unknown MIME type",
    handled gracefully by the caller (falls back to
    `application/octet-stream`). Logging would noise on every
    request to a file with a non-standard extension.

  Test coverage: `tests/test_silent_failure_audit_r119.py` adds 9
  tests across 4 dimensions:
  - **Marker-presence invariant** (3 tests): each of the 3
    modified files contains the `R119` marker (so future grep can
    locate the audit point).

  - **Exception-suppression invariant** (1 test): the
    `_create_default_config_file` PermissionError doesn't
    propagate to the `_save_network_security_config_immediate`
    caller (preserves the read-fallback flow).

  - **Debug-log-emission invariant** (1 test): assertLogs
    captures the `[R119]` marker AND the exception type when the
    network_security create-default fails.

  - **Source-pattern invariant** (3 tests): both `web_ui_mdns.py`
    sites have their characteristic strings; `R119` markers are
    in their `except Exception` blocks (grep-distance assertion
    via line-window analysis); the fix doesn't get accidentally
    refactored back to bare `pass`.

  - **Reverse documentation invariant** (1 test): the 4
    intentionally-silenced sites in `i18n.py`, `config_manager.py`,
    `server_feedback.py`, `server_config.py` STILL contain the
    `except Exception: pass` pattern. If a future contributor
    "fixes" them along with R-series momentum, this test fails
    and points at the CHANGELOG for the documented rationale.

  Files changed:
  - `src/ai_intervention_agent/web_ui_routes/notification.py`
  - `src/ai_intervention_agent/web_ui_mdns.py`
  - `src/ai_intervention_agent/config_modules/network_security.py`
  - `tests/test_silent_failure_audit_r119.py` (NEW, 9 tests, all pass)

  Cumulative impact (R107 → R110 → R114 → R117 → R118 → R119):
  the project's `except Exception: pass` count is now down from
  ~21 to ~11; the remaining 11 are all **documented** as
  intentional via per-site comments referencing this CHANGELOG.

- **R118** — extend the R117 silent-failure observability audit from
  `notification_*` to `service_manager.py`, fixing the **3 of 4
  genuinely-risky** `except Exception: pass` sites in the service /
  HTTP-client lifecycle (the 4th is correctly silenced; see below).

  Background: R117 audited `notification_providers.py` /
  `notification_manager.py` and added debug logging to the highest-
  impact silent failures. R118 continues the same pattern in
  `service_manager.py`, which had 4 bare-except sites identified in
  the original project-wide grep:
  1. **`_invalidate_runtime_caches_on_config_change()` first segment**
     (line 164–170) — the only path that invalidates `_config_cache`
     on config hot-reload. Pre-R118: silent failure → `get_config()`
     keeps returning stale config, hot-reload silently dies, no log
     signal. **Real user symptom**: changing `config.toml` does
     nothing, "must be a bug in ConfigManager" — actually a benign
     race that hot-reload itself never logged.

  2. **`_invalidate_runtime_caches_on_config_change()` second
     segment** (line 172–181) — the only path that closes stale
     httpx clients on config reload. Pre-R118: silent failure →
     subsequent HTTP requests use old client (old `base_url`, old
     `timeout`, old headers) **and** the old client's connection
     pool resources leak (TCP sockets, keep-alive connections,
     HTTP/2 stream state). **Real user symptom**: requests look
     fine but use stale config; FD count grows over time.

  3. **`cleanup_http_clients()`** (line 1085–1089) — the only path
     in `server.cleanup_services()` that closes the synchronous
     httpx client pool on shutdown. Pre-R118: silent failure → FD
     leaks at process exit, kernel `TIME_WAIT` accumulation, "why
     does my MCP process leave sockets open?" with no diagnostic.

  All three follow the same R117 pattern: keep `try/except` (so the
  exception doesn't break the cleanup chain or `ConfigManager`
  callback registry), but add a `logger.debug` with `[R118]` marker
  - the user-visible symptom that this silent failure would cause.
    Normal-path runs stay quiet; when something actually breaks,
    opening debug-level logging immediately surfaces the root cause
    AND the symptom-to-cause mapping ("FD may leak" → check this log
    line).

  The **4th site** at `service_manager.py:505–508`
  (`_cleanup_process_resources`'s per-handle `stdin`/`stdout`/
  `stderr` close loop) is **deliberately preserved** as
  `except Exception: pass` because:
  - Each handle's close is **independent** (the next iteration
    must continue regardless of this one's failure).
  - The outer `for` loop is already wrapped in
    `except Exception as e: logger.error(...)`, so any propagated
    failure is observable.
  - Adding per-handle debug logs would create N×3 noise per
    process cleanup, drowning real signal in routine teardown.

  This is the same "only add R-series debug log when there's no
  upstream observability" principle from R117's design — symmetric
  with how R114 chose to silence one specific RuntimeError class
  while leaving other exceptions to the outer handler.

  Test coverage: `tests/test_service_manager_silent_failure_r118.py`
  adds 9 tests across 4 dimensions:
  - **Exception-suppression invariant** (3 tests): verify each of
    the 3 fixed sites doesn't propagate exceptions to upstream
    (config callback registry / shutdown chain).
  - **Debug-log invariant** (3 tests): verify each fix emits a
    `[R118]`-marked debug log with: (a) function/segment name,
    (b) user-visible symptom hint ("热重载可能不生效" / "新请求
    可能仍走老 client" / "FD may leak"), (c) original exception
    type — so triage flow is "see [R118] log → match symptom →
    locate code path".
  - **Negative path** (1 test): on the **happy path** no `[R118]`
    debug log is emitted (avoids "every cleanup logs noise"
    regression).
  - **Source contract** (2 tests): grep `service_manager.py` for
    `R118` marker + the three fix-point markers — locks the fixes
    in so future refactors can't silently revert to
    `except Exception: pass` without failing CI (same pattern as
    R114 / R116 / R117 marker tests).

  Verification:
  - `uv run pytest tests/test_service_manager_silent_failure_r118.py
-v` → 9 passed
  - Full `uv run pytest -q -W error::DeprecationWarning` →
    3967 passed, 2 skipped, 0 failed, 0 deprecation warnings as
    errors

- **R117** — add **debug-level observability** to two highest-impact
  silent-failure sites in the notification subsystem so resource leaks
  and stats drift no longer fail invisibly.

  Background: a project-wide grep for `except Exception:\n\s*pass`
  found 22 instances across 9 files. Most are correctly-silenced
  best-effort statistics increments (idiomatic for non-critical
  observability hooks). But two stood out as **genuinely risky**
  silent failures — failures that, when they occur, masked real
  resource leaks / stats inconsistencies:
  1. **`BarkNotificationProvider.close()`** (`notification_providers.py`)
     — this is the **only** call site that closes the `httpx.Client`
     connection pool during `shutdown()` / `atexit`. A silent
     `httpx.Client.close()` exception means TCP sockets, keep-alive
     connections, or HTTP/2 stream state can leak with no signal to
     diagnose "why does my ai-intervention-agent process not release
     file descriptors". Pre-R117: bare `except Exception: pass`.
  2. **`NotificationManager._mark_event_finalized()`**
     (`notification_manager.py`) — `self._stats["events_succeeded" /
"events_failed"]` and the `_finalized_event_ids` LRU set are the
     **only** source of `get_stats()`'s `delivery_success_rate` /
     `events_in_flight` calculations. A silent failure here (e.g.
     `next(iter(_finalized_event_ids))` racing with a concurrent
     mutation, or a deadlock-detector raising on lock acquire)
     permanently skews observability without any signal.

  Both fixes follow the same pattern: keep `try/except` (so the
  exception doesn't propagate and break the shutdown chain or
  `_process_event` flow), but log at `logger.debug` with an `[R117]`
  marker. Normal-path runs stay quiet (no log noise); when a real
  resource leak / stats drift is suspected, opening debug-level
  logging immediately surfaces the root cause.

  **Security subtlety**: `BarkNotificationProvider.close()` originally
  used `exc_info=True` — but Python's `logging.exc_info` includes the
  raw traceback string, which **bypasses** the existing
  `_sanitize_error_text` redaction (designed for APNs device tokens,
  long hex tokens, bracket-token patterns). If a user runs with
  `bark_url` containing their device token and `httpx.Client.close()`
  raises with that URL in the message, `exc_info=True` would leak
  the unredacted token into debug logs (which often go to file or
  centralized log aggregation). R117 deliberately uses
  `type(e).__name__` + `_sanitize_error_text(str(e))` instead — the
  type name + sanitized message is sufficient for diagnosis without
  the leak risk. (`_mark_event_finalized` keeps `exc_info=True`
  because its exceptions only contain lock/dict-state info, no user
  data.)

  Test coverage: `tests/test_silent_failure_debug_logging_r117.py`
  adds 11 tests across 3 dimensions:
  - **Exception suppression invariant** (2 tests): exceptions don't
    propagate from `close()` / `_mark_event_finalized()` — same
    behavioral contract as pre-R117, just with logging added.
  - **Debug-log invariant** (4 tests): when an exception fires, a
    debug log with `[R117]` marker is emitted, including the
    function name, exception type, and (for
    `_mark_event_finalized`) `event_id` + `succeeded` flag for
    fast triage.
  - **Token-leak prevention** (1 test): inject a long-hex
    "device token" lookalike into the simulated httpx exception
    message, verify the debug log contains `<redacted_hex>` and
    **does not** contain the original token literal — locks down
    the security subtlety described above.
  - **Reverse / negative-path** (2 tests): on the **happy path** no
    `[R117]` debug log is emitted (avoids "every shutdown / event
    completion logs noise" regression).
  - **End-to-end stats correctness** (1 test): drive
    `_mark_event_finalized` past the LRU `_finalized_max_size`
    boundary 5 times (succeeded=True for 3, False for 2), verify
    `events_succeeded == 3` / `events_failed == 2` — proves R117
    didn't accidentally change stats arithmetic, only added
    observability.
  - **Source contract** (2 tests): grep `notification_providers.py`
    and `notification_manager.py` for `R117` marker + `logger.debug`
    presence — locks the fix into source-level invariants so future
    refactors can't silently revert to `except Exception: pass`
    without failing CI (same pattern as R114 / R116 marker tests).

  Verification:
  - `uv run pytest tests/test_silent_failure_debug_logging_r117.py
-v` → 11 passed
  - `uv run pytest tests/test_notification_providers.py
tests/test_notification_manager.py -v` → all existing
    notification tests still pass (R117 preserves the
    "exception-swallowed" behavioral contract that
    `TestBarkCloseException::test_close_session_error_swallowed`
    explicitly asserts)
  - Full `uv run pytest -q` → 3947+ passed, 0 deprecation
    warnings as errors

- **R116** — un-break **4 of 5 end-to-end performance benchmarks** in
  `scripts/perf_e2e_bench.py` that have been silently failing since
  the **R76 PyPA `src/` layout migration** (commit `11abdad`, ~3
  months back). The benchmarks `import_web_ui`, `spawn_to_listen`,
  `api_health_round_trip`, and `api_config_round_trip` all assumed
  `web_ui.py` was at the repository root and either:
  - ran `python -c "import web_ui; ..."` → `ModuleNotFoundError`
    (`web_ui` is now a sub-module of `ai_intervention_agent`), or
  - ran `subprocess.Popen([python, "web_ui.py", ...], cwd=REPO_ROOT)`
    → `rc=2 can't open file 'web_ui.py'` (the file lives at
    `src/ai_intervention_agent/web_ui.py` post-R76).

  Both failure modes were swallowed by `run_all`'s
  `try/except Exception` into an `error` field in the JSON payload,
  and `perf_gate.py` (the regression detector) gracefully treated
  `error` as "no data → skip". Worse, `perf_gate.py` was **never
  wired into any GitHub workflow** (grep `.github/workflows` for
  `perf_gate` / `perf_e2e_bench` returns zero hits), so the only
  signal that 80% of perf coverage was dead came from `[perf_bench]
FAILED <name>` lines on stderr — which only humans running the
  script manually would notice. This is exactly the silent-break
  failure mode the project's "fail-loud, no silent skips" policy
  exists to prevent (cf. R107–R110 series). 12 commits passed
  through main between R76 and R116 with the perf coverage fully
  blind.

  Fix:
  1. `bench_import_web_ui`: change `-c` payload from
     `import web_ui; …` → `from ai_intervention_agent import web_ui; …`.
  2. `bench_spawn_to_listen` + `_start_web_ui_subprocess`: change
     argv from `[python, "-u", "web_ui.py", ...]` → `[python, "-u",
"-m", "ai_intervention_agent.web_ui", ...]` (re-uses the same
     `if __name__ == "__main__":` entrypoint with full
     `--prompt` / `--port` arg parity).
  3. Refresh `tests/data/perf_e2e_baseline.json` with measurements
     from the **now-runnable** benchmarks (post-fix all 5 produce
     real `samples_ms` arrays; verified end-to-end against
     `perf_gate.py --verbose` with PASS verdict).
  4. **Add a regression-guard test** at
     `tests/test_perf_e2e_bench_invocability_r116.py` covering
     three layers:
     - **AST source check** (3 tests): walk
       `scripts/perf_e2e_bench.py`'s AST, verify every
       `subprocess.{run,Popen}` call's argv contains
       `"-m"` + `"ai_intervention_agent.web_ui"` and **does not
       contain** `"web_ui.py"`; verify every `-c` payload imports
       the qualified module path. AST-based assertion is precise —
       it does not false-trigger on docstring / comment text that
       mentions the historical broken state for context.
     - **Functional subprocess check** (3 tests): actually run
       `python scripts/perf_e2e_bench.py --quick`, parse stdout
       JSON, assert all 5 expected benchmarks present **and** all 5
       have non-empty `samples_ms` (no `error` fields anywhere).
       This is the "did the fix actually work end-to-end" layer.
     - **Baseline shape check** (1 test): assert
       `tests/data/perf_e2e_baseline.json` parses as JSON and
       contains all 5 benchmarks (so future drift between bench
       names and baseline JSON also fails CI).

  The new test runs through `pytest` → `ci_gate.py` → `test.yml`,
  so any future silent break of the same family fails PR CI
  immediately with a precise error message instead of degrading
  perf coverage in the dark for months.

  `perf_gate.py` itself is intentionally **not** wired into CI:
  cross-hardware median comparison (maintainer's local Mac vs
  GitHub `ubuntu-latest` runner, both with widely varying CPU
  characteristics) would produce too many false positives at the
  default 30% / 5ms threshold. R116 specifically targets the
  **silent-break root cause**, not numeric regression-vs-baseline
  (which remains a maintainer / pre-release manual concern).

### Documentation

- **R115** — document the upstream **Cursor "Extension host terminated
  unexpectedly 3 times" interaction** with this MCP server in
  `docs/troubleshooting.md` §11 / `docs/troubleshooting.zh-CN.md` §11.
  Background: users hit the banner and reasonably wonder if
  ai-intervention-agent triggered it. Investigation (Cursor community
  forum threads 148772 / 116280, plus a static audit of our MCP
  surface) shows:
  1. The banner reproduces on Cursor 2.4.14 and earlier **with all
     extensions disabled**, so it is an upstream IDE issue, not
     specific to this project.
  2. The well-known `mcp-feedback-enhanced` regression
     (`timeout=1` causes the feedback flow to insta-timeout, see
     Minidoracat/mcp-feedback-enhanced#212) **does not apply** to
     this project: the `interactive_feedback` tool's `timeout` and
     `timeout_seconds` parameters are accepted for compatibility but
     **explicitly ignored**, the server's own
     `calculate_backend_timeout` + `BACKEND_MIN=260` clamp is used.
  3. R114 (notification shutdown TOCTOU) already silenced the most
     plausible "MCP-side noise that gets blamed for the crash" log
     pattern (`ERROR: 处理通知事件失败 - cannot schedule new futures
after shutdown`).

  The new section gives a 5-step triage flow (confirm MCP green
  light → `Developer: Restart Extension Host` → upgrade Cursor → grep
  the MCP log for `处理通知事件失败` vs `[R114]` lines → recognise
  the long-poll vs Cursor watchdog interaction). It also explicitly
  cross-links the upstream Cursor forum issue and bug tracker so
  affected users can mirror progress instead of opening duplicate
  bugs against this repo.

### Fixed

- **R114** — eliminate a **`NotificationManager` shutdown TOCTOU**
  that turned a benign atexit-time race into a noisy `ERROR` log
  every time another goroutine ran `shutdown()` while
  `_process_event` was mid-flight. The race window:
  1. `_process_event` reads `self._shutdown_called` (line 579)
     and finds it `False`, enters the main body.
  2. Concurrently, `shutdown()` sets
     `_shutdown_called = True` and calls
     `_executor.shutdown(cancel_futures=True)`.
  3. `_process_event` then calls `self._executor.submit(...)`
     (line 600) → CPython raises
     `RuntimeError: cannot schedule new futures after shutdown`.

  Pre-R114, this `RuntimeError` was caught by the generic
  `except Exception` at line 685 and logged as
  `ERROR: 处理通知事件失败: <event_id> - cannot schedule new
futures after shutdown`. Two real consequences:
  - **Wrong attribution.** The error log made it look like a
    notification-provider failure (Bark / sound / Web), when the
    actual cause was a benign shutdown race during `atexit` or
    explicit restart paths. On-call would dig into provider code
    and find nothing.
  - **Spurious retry.** The same except branch incremented
    `retry_count` and rescheduled via `_schedule_retry` — but
    the timer's `_process_event` would re-enter the line 579
    early-return and silently no-op, so the only visible effect
    was a misleading `WARNING: 处理通知事件异常，将在 Ns 后重试`
    log spike during shutdown.

  Fix: wrap **only the `submit` loop** in an inner
  `try/except RuntimeError`. On hit, **second-check**
  `_shutdown_called` — if it really turned `True` between
  line 579 and line 600, treat as a benign race (DEBUG log
  `[R114] _executor.submit 与 shutdown 竞态`, `return`
  without retry/fallback/error log). Any `RuntimeError` whose
  `_shutdown_called` is still `False` is re-raised so the
  outer `except Exception` keeps its diagnostic value for
  genuine bugs. Already-submitted futures are cancelled
  naturally by `cancel_futures=True`, no leak, no
  `as_completed` deadwait.

  Tests: `tests/test_notification_shutdown_race_r114.py` (6
  tests, including a real-time race triggered via a gated
  executor wrapper that synchronously runs `shutdown` between
  `_process_event`'s check and submit, plus a reverse-injection
  guard verifying the `[R114]` source marker survives future
  refactors). Reverse-injection (revert the fix → 4/6 fail with
  the exact "cannot schedule new futures after shutdown" trace
  in `ERROR: 处理通知事件失败` form, confirming the test would
  catch the regression). Full `test_notification_manager.py`
  suite (174 tests) still passes.

- **R113** — close a **macOS user-config-path silent-divergence** that
  let `~/.config/ai-intervention-agent/config.toml` quietly persist on
  macOS machines and produce confusing "I edited my config but
  nothing changed" reports. The standard macOS config location is
  `~/Library/Application Support/ai-intervention-agent/` (Apple File
  System Programming Guide; `platformdirs.user_config_dir` returns
  exactly that on Darwin), and the existing code in
  `config_manager.py::_get_user_config_dir_fallback` /
  `find_config_file` already pointed at the right place. But the
  legacy XDG-style path `~/.config/ai-intervention-agent/` could
  still end up populated on macOS via several real-world paths:
  - **historical early versions** of ai-intervention-agent or
    `platformdirs` may have used XDG on macOS;
  - **cross-platform dotfiles** copied verbatim from a Linux setup;
  - **third-party install scripts** that hard-code `.config/`
    assuming it is portable;
  - **dev-mode invocations with cwd === ~/.config/ai-intervention-agent/**
    where `find_config_file` would create `config.toml` right in cwd.

  Once one such legacy file existed, **the user could not tell which
  copy was authoritative** — the agent would happily read from
  `~/Library/Application Support/...` while the user kept editing
  `~/.config/...`, leading to a silent edit-loss feedback loop with
  no diagnostic emitted.

  Real-world latent footprint observed on the maintainer's box:
  three independent `config.toml` files (`~/Downloads/arch/<repo>/
config.toml`, `~/.config/ai-intervention-agent/config.toml`,
  `~/Library/Application Support/ai-intervention-agent/config.toml`)
  each with **different `bark_action` / `frontend_countdown` /
  `log_level` values**, all reachable by different startup modes
  (dev mode in repo cwd, uvx user mode, third-party recreation),
  each producing different runtime behaviour with zero clue from
  the agent that there were extra copies floating around.

  Fix: add `_macos_legacy_xdg_config_dir()` (returns the legacy
  path only on Darwin + only when the directory actually exists,
  None on Linux/Windows or when absent), and integrate two new
  branches into `find_config_file`'s user-config-dir resolution:
  1. **standard + legacy both exist** → still use the standard
     path (canonical), but emit a `WARNING` log naming the legacy
     file with an `rm -rf` cleanup suggestion. The user no longer
     unknowingly maintains two divergent copies.
  2. **legacy exists but standard does not** → use the legacy
     path (so existing user configuration is **never silently
     lost**), but emit a strong `WARNING` log with a copy-paste
     `mkdir -p / mv / rmdir` migration script. The user keeps
     working immediately while being directed at the right path
     for next time.

  **Linux is explicitly excluded** from R113 — `~/.config/` is the
  XDG-standard location there (`platformdirs.user_config_dir` on
  Linux returns exactly that path), so warning Linux users would be
  a 100% false-positive blast that would erode log signal. The
  `platform.system().lower() != "darwin"` early-return guard at the
  top of `_macos_legacy_xdg_config_dir()` is the load-bearing piece
  of that contract; the `test_linux_with_xdg_dir_does_not_emit_r113_warn`
  reverse test in the R113 suite locks it.

  Tests: new `tests/test_macos_legacy_xdg_config_r113.py` (10
  cases). Five unit tests on `_macos_legacy_xdg_config_dir`
  (macOS+dir / macOS-no-dir / Linux-with-dir-must-not-flag /
  Windows / `.config/ai-intervention-agent` is a file not a
  directory). Five integration tests on `find_config_file`
  exercising all four bucket combinations (standard+legacy both,
  legacy-only, standard-only, neither) plus the Linux false-
  positive guard. All tests use `tempfile.TemporaryDirectory` +
  `Path.home` monkey-patch + `platform.system` monkey-patch +
  `user_config_dir` monkey-patch so the same suite runs reliably
  on macOS / Linux / Windows CI without depending on the host's
  real filesystem layout.

  Reverse-injection: `_macos_legacy_xdg_config_dir` patched to
  `return None` at the top → 3 of 10 tests fail (the unit case
  for the macOS-with-dir path; both integration cases that
  require the R113 warn to be emitted), confirming the new
  detection is the load-bearing defence — not coincidental
  passes against an existing path.

  End-to-end verified on the maintainer's actual box (Apple
  Silicon M1 / macOS 25.4.0 / platformdirs 4.3.8 dev-tree +
  4.9.6 uvx wheel): both warning branches fire with the right
  log content + correct path selection; existing config files
  on disk are untouched; full test suite (`pytest -W error`)
  passes 3934 / 2 skipped / 0 failed / 0 warnings.

- **R112** — close a **static-file-route information-disclosure silent-
  breakage**: `serve_fonts` (`/fonts/<filename>`) and `serve_icons`
  (`/icons/<filename>`) routes in `web_ui_routes/static.py` had **no**
  file-extension whitelist, while their siblings `serve_sounds`
  (whitelist `.mp3 / .wav / .ogg`), `serve_lottie` (whitelist `.json`),
  and `serve_locale` (`/api/locales/`, whitelist `.json`) all enforced
  one. `send_from_directory` only protects against path traversal
  (`../`) — it has no semantic notion of "this directory should only
  expose font/icon files". If anyone ever drops a `README.md`,
  `config.bak`, `.tmp`, `notes.txt`, or worse a `.py` source file into
  `fonts/` or `icons/`, the route would happily serve its bytes back
  to anyone who guesses the URL.

  Real-world risk surface (concrete): `icons/` already contains
  `manifest.webmanifest` (which is whitelisted in R112) — proving the
  directory is the actual mixed-content drop zone. A future refactor
  that lands a `dev-notes.md` or `internal-icons-todo.txt` next to it
  would silently leak. Same threat model as R56's `/api/locales/.json`
  whitelist (CVE-style "any file in directory is a candidate").

  Fix: enforce extension whitelists at route entry, mirroring the
  sounds/lottie/locales pattern:
  - fonts: `.woff / .woff2 / .ttf / .otf / .eot / .ttc` (the six
    formats actually shipped to browsers in 2024-2026; legacy `.eot`
    kept for IE compat per WOFF2 caniuse table).
  - icons: `.png / .ico / .svg / .webmanifest / .jpg / .jpeg / .gif`
    (covers all current `icons/icon*.png` + `icons/icon.svg` +
    `favicon.ico` + the manifest.webmanifest dual-route, plus future
    raster fallbacks).
  - case-insensitive (`.lower()`); empty filename guard prevents
    `/fonts/` exact match leaking dir listing.

  Tests: new `tests/test_static_extension_whitelist_r112.py` (15
  cases). Critical: tests use a `tempfile.TemporaryDirectory` +
  `_project_root` monkey-patch to **actually create**
  `fonts/leaked.txt`, `icons/script.py` and verify the route returns
  404 + the response body does **not** contain the secret content.
  Naive `assertEqual(404)` would have been a false-positive (the real
  `fonts/` directory doesn't exist → 404 from `send_from_directory`,
  indistinguishable from whitelist reject); R112 test design follows
  R109's reverse-injection-must-actually-fail discipline.

  Reverse-injection: delete the two `abort(404)` blocks → 7 of 15
  tests fail with `200 != 404` (each leaked-file test reports the
  secret string would have been served), confirming the whitelist is
  the load-bearing defense. Cache-Control headers still set correctly
  for 404 responses (verified by R56 test suite still passing).

- **R111** — close a real **PII redaction silent-leak**: `LogSanitizer`
  in `enhanced_logging.py` (and its VS Code mirror `packages/vscode/
logger.ts::redactSensitive`) caught the legacy classic GitHub PAT
  `ghp_[A-Za-z0-9]{36}` family R54-B introduced in 2022, but **never**
  caught the **fine-grained PAT** family `github_pat_<11 char ID>_
<82 char secret>` (≈ 93 chars total) that GitHub introduced in
  October 2022 and now defaults to for newly-created tokens.

  Real-world latent leak: any developer pasting a fine-grained PAT
  into a debug log, error trace, MCP request, curl command, or git
  remote URL would have it land **plaintext** on stderr — visible
  to MCP clients, to `_record_to_ring` ring-buffer entries, to
  Output Channels (VS Code), and to anything tailing the process.
  CI/CD pipelines printing the token at debug verbosity would push
  it into permanent build logs. Same severity as the R54-B drop,
  fixed three years late because the regex set was never re-audited
  against GitHub's evolving token format.

  Fix: add `re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")` to the
  Python `LogSanitizer` pattern list (placed after the classic
  `gh[psour]_` regex per "specific-before-general" ordering, even
  though they're disjoint), and mirror the same JS regex
  (`/\bgithub_pat_[A-Za-z0-9_]{60,}\b/g`) into VS Code
  `logger.ts::redactSensitive`. Lower-bound 60 chars covers all
  observed fine-grained formats (typical 82–93) while rejecting
  short look-alikes like `github_pat_short`.

  Tests: new `TestGitHubFineGrainedPATR111` class (6 cases) locks
  typical 93-char form, mixed-case secret, leak via `curl -H
'Authorization: token <PAT>'` (the most common copy-paste leak
  path — note **not** the URL-basic-auth form, which gets
  sanitized by the unrelated url-basic-auth regex and would mask
  R111 regression), classic `ghp_` still works (no ordering
  regression), and two false-positive guards (`github_pat_short` /
  arbitrary `github user pat` text). Reverse-injection (delete the
  R111 regex) → 3 of 6 tests fail (typical / mixed-case / curl
  command leak) confirming new tests catch exactly the regression
  they're meant to.

  Closes the PII redaction freshness gap. Future audit cadence:
  the LogSanitizer pattern set should be re-checked against
  GitHub's [official secret scanning patterns][gh-secret-scanning]
  whenever GitHub announces a new token format.

  [gh-secret-scanning]: https://docs.github.com/en/code-security/secret-scanning/about-secret-scanning

- **R110** — close the **last** silent-skip in the i18n scanner family
  at `scripts/check_i18n_param_signatures.py`. Two layered silent
  returns (R102 同款，与 R88/R100/R101/R102 在 brand-color guard /
  HTML coverage / ts/js no-cjk / locale shape 几个扫描器修过的
  silent-skip-on-missing-source 反模式同款):
  1. `_scan_web()`: `if not en.is_file(): return []` —
     `WEB_LOCALES_DIR/en.json` 缺失时静默返回空列表。
  2. `_scan_vscode()`: 同款 `VSCODE_LOCALES_DIR/en.json` 缺失静默路径。

  Combined effect: 任一源 `en.json` 缺失 → `total = sum(len([])) = 0`
  → `--strict` 也走 exit 0 → 整个 param-signature 一致性校验
  zero-coverage 但 CI 仍然绿。Real-world latent risk today: 零（两
  个源 `en.json` 都在），但等价于 R76 把 `static/` 挪进 `src/` 时
  R66 brand-color guard 已经被 R88 打 patch 的同款"重构 ⇒ 守门静默
  失效"模式——不修就是埋雷等下次重构。

  Fix: 加 main() 顶部 layer-0 path-drift sanity check（与 R102
  `check_locales.py::main()` 同款 design），列出 2 个核心源
  `en.json` 路径，缺失即 fail-loud (exit 2) + 含 R110 tag + 含相对
  / 绝对路径 + 修复指引（更新 `WEB_LOCALES_DIR` /
  `VSCODE_LOCALES_DIR` 常量）。`_scan_web` / `_scan_vscode` 移除
  内部 silent skip（layer-0 已 hoist）。Exit code 0/1/2 与 R102
  约定对齐：0=clean, 1=violations, 2=configuration error。

  Updated docstring's Exit 段反映新 exit 2 路径。新 `TestMainPathDriftR110`
  类（5 cases）锁：missing web en / missing vscode en / both missing /
  happy path / 修复指引含 `WEB_LOCALES_DIR` + `VSCODE_LOCALES_DIR`。
  Reverse-injection（移除 layer-0 R110 检查）→ 4 of 5 R110 测试 fail
  with rc 1 ≠ 2 / 缺 R110 tag / 缺修复指引；happy path 不被影响。
  Updated `TestScannerResilience.test_detects_missing_param` 与
  `test_skips_dynamic_key`：现需给 monkey-patched root 同时建空
  `vscode_locales/en.json`，因 `_scan_vscode` 不再 silent skip。

  Closes the silent-skip-on-missing-source family that ran through
  R88/R96/R100/R101/R102/R104/R105/R106/R107/R108/R110: every
  scanner / validator / test in the repo that takes "core resource
  missing" 全部以 `R{tag}` 标签 fail-loud + diagnostic + remediation
  hint，CI 在源缺失时再也不会 silent green。

- **R109** — close the **last** R66/R99 brand-color drift gap by
  expanding the hex-form regex from a single literal `#007aff` to a
  union covering the entire iOS-blue family. Two real hardcoded
  hex variants in `static/css/main.css` were sitting unprotected by
  the R66/R99 guardrail because they don't share the exact `#007aff`
  literal R99 indexed:
  1. `main.css::1020` — `.btn-primary-enabled { background-color:
#0a84ff; }` (iOS 13+ / macOS dark-mode systemBlue, the dark
     counterpart to `#007aff`).
  2. `main.css::3982` — `.btn-primary:hover { background: #0056cc; }`
     (iOS-blue darker hover variant, ≈ 30 % darken of `#007aff`).

  Both render as iOS blue in light mode (the **same** drift source
  R66 / R99 explicitly fight) but neither tripped the existing
  `re.compile(r"#007aff\b")`. Real-world latent risk: zero today
  (only 2 instances, both already-known references in the
  changelog history), but the gap shape is identical to R88's
  "guard regex doesn't catch close-relative drift" — invisible
  until a future PR adds another `#0a84ff` for hover or another
  `#0056cc` for active state.

  R109 changes the hex regex to
  `re.compile(r"#(?:007aff|0a84ff|0056cc)\b", re.IGNORECASE)`,
  bumps `DEFAULT_HEX_BASELINE` from 7 to 9 (= 7 `#007aff` + 1
  `#0a84ff` + 1 `#0056cc`), and updates the violation messages /
  ℹ️ warn copy to mention all three variants. The "one baseline
  per drift family" design mirrors R65 collapsing every rgba
  alpha-channel variant (`0.05 / 0.1 / 0.5 / 0.8`, …) onto a
  single baseline 34 — same family ⇒ same baseline number, simpler
  for the next refactor that picks them off in batches.

  New `TestIosBlueHexFamilyR109` (9 cases) locks: each variant
  in / out, case-insensitivity, near-neighbor non-matches
  (`#0a85ff`, `#0156cc`, `#0a84fe`, `#1056cc`), brand-palette
  guard (`#a855f7` / `#d97757` never false-positive), and a
  `test_actual_main_css_has_each_variant` end-to-end assertion
  that the breakdown 7 + 1 + 1 = 9 actually exists in `main.css`
  after comment stripping. Reverse-injection (revert the union
  regex back to the R99 single `#007aff`) yields **8 fails** (4
  variant-specific cases + 2 family integration + 1 baseline-sync
  guard + 1 CLI exit-code) — confirming the new tests catch
  exactly the regression they're meant to.

  Closes the brand-color drift family that started at R64/R65 and
  ran through R66/R88/R99/R103: every iOS-blue color form
  (rgba decimal, hex light, hex dark, hex darker hover) is now
  baseline-locked, and both wiring layers (pre-commit + ci_gate)
  enforce them on every PR.

- **R108** — final cleanup of the silent-path-skip family in
  `tests/`. Converts the last unconditional `pytest.skip` in
  `tests/test_i18n_ts_types_gen.py::TestHostTCallsAreTypeable::
test_all_hostt_keys_present_in_dts` to `pytest.fail`. The check
  is the _only_ thing pinning the three-way contract between
  `packages/vscode/extension.ts` (call sites of `hostT(key)`),
  `packages/vscode/locales/en.json` (the runtime keys), and
  `packages/vscode/i18n-keys.d.ts` (the TypeScript literal union
  that gives `hostT` compile-time type safety). Silently skipping
  when `extension.ts` is missing meant a refactor that renamed or
  deleted the extension host entry point would let
  `hostT('typo')` regressions slip through entirely (test was
  reporting `SKIPPED`, CI was green, no coverage). Same shape and
  same fix as R104/R105/R107.

  Reverse-injection (point `EXTENSION_TS` at
  `/__definitely_not_existing__/extension.ts` and re-run the
  case) raises `pytest.fail.Exception` with `R108: extension.ts
missing: ...` diagnostic — confirming silent-skip purged.
  Audited the remaining `pytest.skip` / `self.skipTest` callsites
  in `tests/`; the survivors (`test_vscode_vsix_size_budget.py:155`
  for "dev box hasn't packaged a `.vsix` yet, CI's `release.yml`
  triggers the hard check"; `test_ratelimit_headers_r57.py:94` for
  transient non-integer header parses) are intentional design
  skips, not configuration drift, and stay as `skipTest`.

  This closes the silent-skip-path-drift purge that started at R88
  and ran through R96/R100/R101/R102/R104/R105/R106/R107: every
  scanner / validator / test in the repo that previously took
  "core resource missing" and silently returned 0 / SKIPPED now
  treats it as configuration drift and fails loudly with a
  diagnostic message and a remediation pointer.

- **R107** — convert three `pytest.skip("locale file ... not present")`
  paths in `tests/test_i18n_pseudo_locale.py` to `pytest.fail`. The
  three checked locale resources (`src/ai_intervention_agent/static/
locales/en.json`, `packages/vscode/locales/en.json`, and the
  paired `_pseudo/pseudo.json` outputs from `gen_pseudo_locale.py`)
  are i18n single-source-of-truth — same tier as the 6 core locale
  resources R102 already path-locked at `check_locales.py::main()`,
  the `main.css`/`webview.css` design-token sources R104 locked,
  and `packages/vscode/i18n.js` R105 locked. Silent-skipping when
  any one is missing meant a refactor that drops `_pseudo/` could
  ship with the entire `TestPseudoStructuralParity` /
  `TestEveryLeafTransformed` family no-opping; CI green, coverage
  zero.

  Implementation note: `pytest.fail` surfaces a known ty stub
  glitch — the type checker mis-resolves `pytest.fail(reason: str,
pytrace: bool, msg: object)` against multi-line f-strings or
  reassigned `reason` variables, reporting `Expected bool, found
str` for the first positional arg. The existing convention in
  this repo (`tests/test_critical_preload_r21_1.py:396, 413`) is
  to suppress the false-positive with `# ty:
ignore[invalid-argument-type]`. R107 follows the same suppression
  pattern, with R107-tagged diagnostic strings explaining
  remediation (run `gen_pseudo_locale.py`, restore the file,
  update `WEB_EN`/`VSCODE_EN`/`WEB_PSEUDO`/`VSCODE_PSEUDO` constants).
  Reverse-injection by direct method calls with
  `Path("/__definitely_not_existing__/missing.json")` for each of
  the 3 fail paths confirms `pytest.fail.Exception` raises with
  R107 tag in every case (3/3 verified, 0 silent skips remain).

- **R106** — drop seven `try: from ai_intervention_agent.server
import X; except ImportError: self.skipTest(...)` blocks in
  `tests/test_server_functions.py`. The pattern was redundant _and_
  actively harmful:
  - **Redundant**: the test module already does
    `import ai_intervention_agent.server as server` at the top, so
    if the package fails to import the module won't even collect.
    Reaching one of the per-class `try` blocks means the module
    imported fine — the only remaining `ImportError` mode is "the
    public symbol got renamed or deleted".
  - **Harmful**: catching that `ImportError` and turning it into a
    `skipTest` makes `wait_for_task_completion`,
    `ensure_web_ui_running`, `launch_feedback_ui`,
    `MAX_MESSAGE_LENGTH`, `MAX_OPTION_LENGTH`, `logger`, and
    `interactive_feedback` look like optional symbols. They are
    not — they are the public server contract. Silently skipping
    a "core API got deleted" regression while CI prints `OK` is
    the worst flavor of green-test-no-coverage.

  R106 swaps every `try/except ImportError/skipTest` block for a
  hard `from ai_intervention_agent.server import X`. If `X`
  vanishes, pytest collects the test as `ERROR` (with the actual
  `ImportError` traceback in the report), not `SKIPPED`.
  Reverse-injection (delete `MAX_MESSAGE_LENGTH` and `logger` off
  the live `server` module via `delattr`, then re-run the
  affected `TestServerConstants::test_max_message_length` /
  `TestServerLogger::test_logger_exists` cases) yields **1 error,
  0 skips** per case with the canonical
  `ImportError: cannot import name 'X' from 'ai_intervention_agent.server'`
  diagnostic. Same shape as R96/R104/R105's "test silent-skip ⇒
  no coverage" purge family.

- **R105** — finish purging silent-skips from
  `tests/test_i18n_normalize_lang_csrf_r72d.py`. R96 already
  fixed the test harness so the **VS Code mirror** of
  `i18n.js::normalizeLang` actually got exercised (instead of
  silently `skipTest`'ing because `sandbox.window.AIIA_I18N` was
  the wrong export path). But R96 left two related silent-skip
  surfaces in `test_packages_vscode_i18n_consistency`:
  1. `if not _I18N_JS_VSCODE.exists(): self.skipTest(...)` — same
     R76-rearrange ⇒ silent-broken pattern that
     R88/R100/R101/R102/R104 already purged.
     `packages/vscode/i18n.js` is the VS Code mirror's i18n
     single-source-of-truth; missing it is configuration drift,
     not "OK".
  2. `if sentinel is None or NODE_FAIL: self.skipTest(...)` —
     after R96 wired the harness to read both
     `sandbox.window.AIIA_I18N` and `sandbox.AIIA_I18N`, a
     `NODE_FAIL` sentinel can only come from a real export/wiring
     bug (rename of `AIIA_I18N`, syntax error, deleted
     `normalizeLang`). The class-level
     `@unittest.skipIf(shutil.which("node") is None)` already
     handles the legit "no Node on PATH" skip path. Catching real
     bugs as silent skips meant a CI dashboard could go green
     while `normalizeLang` was structurally broken.

  R105 swaps both `skipTest` calls for `self.fail(...)` with
  diagnostic messages tagged `R105:` and listing the three
  realistic failure modes (export-path drift / syntax error /
  identifier rename) so a future reviewer can locate the
  regression without reading test scaffolding. Reverse-injection
  with `mock.patch.object` simulating both scenarios (missing
  file, mocked `NODE_FAIL` sentinel) yields **1 fail, 0 skips**
  per case with R105 tag present in every fail message.

- **R104** — replace silent `self.skipTest("...CSS 不存在")` with
  loud `self.fail(...)` in `tests/test_state_tokens.py`. The
  test module is the **only** thing pinning the cross-platform
  parity of `--aiia-state-*` design tokens between
  `src/ai_intervention_agent/static/css/main.css` (Web UI) and
  `packages/vscode/webview.css` (VS Code webview). Previous
  implementation had four silent-skip surfaces:
  1. `test_web_css_defines_all_expected_tokens` — `if not
WEB_CSS.exists(): self.skipTest(...)`.
  2. `test_vscode_css_defines_all_expected_tokens` — same shape on
     `VSCODE_CSS`.
  3. `test_cross_platform_token_values_equal` — combined
     `if not WEB_CSS.exists() or not VSCODE_CSS.exists():
self.skipTest(...)`.
  4. `test_transition_token_is_proper_shorthand` — per-end
     `if not path.exists(): continue` quietly drops half the
     coverage.

  Same shape as R76's "static rearrange ⇒ guard goes silently
  broken" pattern that R88/R100/R101/R102 already purged from
  brand-color, HTML coverage, and i18n no-CJK / locale scanners.
  R104 introduces a `_fail_missing_css(test, path, label)` helper
  with diagnostic output (relative + absolute path + remediation
  pointer back to `WEB_CSS` / `VSCODE_CSS` constants) and uses it
  in all four test cases. Adds a new `TestPathDriftR104` class
  with two layer-0 sanity tests (`WEB_CSS`/`VSCODE_CSS` resolve to
  existing files) so a path-constant drift is reported as the
  _first_ failure in CI output, not buried under cascading test
  errors. Reverse-injection (mock `WEB_CSS` or `VSCODE_CSS` to
  `/__definitely_not_existing__/missing.css`) yields **4 fails, 0
  skips** with R104 tag present in every fail message.

  Also documents the doc/code drift R103 introduced into
  `scripts/README.md` `## Visual / brand guardrails` section
  (used to say "Wired into `pre-commit`" but R103 added the
  `ci_gate.py` invocation as a second wiring layer; copy now
  reflects both wiring paths and the `R66 / R99 / R103` lineage).

- **R103** — wire `scripts/check_brand_color_consistency.py` into
  `ci_gate.py` to close the **second layer** of the R66/R88/R99
  brand-color guardrail. R88 fixed the `files`-glob/`DEFAULT_ROOT`
  drift _inside_ the pre-commit hook, but the script was **only**
  invoked from `.pre-commit-config.yaml` — not from
  `ci_gate.py --ci`. Three failure modes lined up:
  1. `test.yml` and `release.yml` only call `uv run python
scripts/ci_gate.py --ci` — never `pre-commit run --all-files`.
  2. The repo does not enforce `pre-commit install`; hooks live on
     each developer's machine, not in version control.
  3. The hook is staged-only with `files: ^src/.../static/css/.*\.css$`
     — PRs that don't touch CSS never trigger it, but CI also has
     no fallback for the ones that do.

  Combined effect: a developer who clones, ignores the README's
  "run `uv run pre-commit install`" hint, and sends a PR adding
  `rgba(0, 122, 255, X)` or `#007aff` to `main.css` would have
  the R66 baseline 34 / R99 hex baseline 7 lock **silently bypassed**
  on the way to `main`. Real-world latent risk: zero today (current
  PRs all pass the baseline), but the structure of the failure is
  identical to R88's "hook glob drift" — invisible until the next
  refactor lands a regression. R103 appends a single
  `_run([..., "scripts/check_brand_color_consistency.py", "--quiet"])`
  call at the tail of the i18n drift-detector sequence in
  `_main_impl`, so every CI run (and every local `uv run python
scripts/ci_gate.py`) now exercises the baseline lock. `--quiet`
  matches the pre-commit hook's silent-on-pass contract. New
  `tests/test_ci_gate_brand_color_r103.py` (4 cases) regex-asserts
  the invocation, the `--quiet` flag, the position-after-`check_i18n_
locale_shape.py` ordering, and the script's continued existence.
  Reverse-injection (delete the new `_run` line) → 3/4 fail with
  contract-violation messages, proving the guard catches future
  regressions.

- **R102** — close the silent-path-drift loop on the **last** i18n
  consistency scanner: `scripts/check_locales.py::main()`. Three
  layered silent skips collapsed to `0` (= "OK") whenever any of 6
  core locale resources went missing, mirroring R76 → R88/R100/R101's
  pattern of "static rearrange ⇒ guard goes silently broken":
  - `for dir_path, label in locale_dirs: if dir_path.exists():` —
    web-side or vscode-side `locales/` directory drift skips both
    `check_locale_pair` calls.
  - `if vscode_dir.exists(): all_errors.extend(check_nls_pair(vscode_dir))`
    — and inside `check_nls_pair`, `if not en.exists() or not zh.exists():
return []` — `package.nls{,.zh-CN}.json` drift skips silently.
  - `if web_locales_dir.exists() and vscode_locales_dir.exists():` —
    cross-platform `aiia.*` parity skipped silently if either side moves.

  Real impact today: **0 latent drift hidden** (all 6 paths exist),
  so this is preventive — but in a project where R76 already proved
  refactors do move static dirs, leaving this silent skip in place
  was the same latent breakage that bit R88. R102 hoists a layer-0
  sanity check at the top of `main()` listing all 6 required paths,
  prints a structured diagnostic to `stderr` (label + relative path
  - absolute path + remediation pointer back to the path constants
    in the script), and returns `2` — matching the `0/1/2` exit-code
    convention R88/R100/R101 settled on (0=clean, 1=violations,
    2=configuration error). Updated `tests/test_check_locales.py`
    with a `TestMainPathDriftR102` class (5 tests) that monkey-patches
    `Path.exists` to simulate each missing-resource scenario; reverse-
    injection (revert R102 to silent-skip) caused 4/5 to fail with
    `exit 0/1 != 2` and missing diagnostic strings, proving the
    guards actually catch regressions.

- **R101** — purge the same `if not <root>.exists(): return 0`
  silent-skip anti-pattern from `check_i18n_ts_no_cjk.py` and
  `check_i18n_js_no_cjk.py` that R88 had purged from the brand-
  color guard and R100 had purged from the HTML coverage scanner.
  Both i18n CJK-literal scanners had the same shape:
  - `check_i18n_ts_no_cjk.py` — `_iter_ts_source_files()`
    returned `[]` when `_VSCODE_ROOT` (= `packages/vscode`) didn't
    exist, so `collect_violations()` saw zero files, `main()`
    printed `OK` and returned 0. Any future refactor that moves
    or deletes `packages/vscode` would silently neutralise the
    extension-host CJK gate.
  - `check_i18n_js_no_cjk.py` — `_iter_js_source_files()` did
    `continue` on each missing root, so `--scope vscode` with a
    drifted `packages/vscode` returned 0 with `OK`, and
    `--scope all` with one of the two drifted roots only scanned
    the surviving half (partial silent breakage). Either way the
    gate looked green while covering nothing or only half.

  This is latent — both `_VSCODE_ROOT` and `_WEBUI_ROOT` resolve
  fine in the live tree today. But R76 (the `static/` → `src/`
  reshuffle that originally produced R88's silent broken state)
  proved that layout shifts happen, and the matching anti-
  pattern in two more scanners was just one rename away from
  silently degrading their coverage too.

  Decision: copy R88/R100's exact pattern verbatim — `main()`
  does a layer-0 path-drift sanity check up front (before any
  scanning), and on missing root prints a multi-line stderr
  diagnostic naming the resolved absolute path and pointing at
  the constant to update, then `return 2`. For
  `check_i18n_js_no_cjk.py`'s scope-aware setup the check
  iterates over **all** roots in the chosen scope so partial
  drift across `--scope all` also triggers fail-loud (not just
  the all-roots-missing case). This avoids the "we still found
  some files so it's fine" compromise that would mask half-
  drifted layouts.

  Fix:
  - `scripts/check_i18n_ts_no_cjk.py::main()` — gated up-front by
    `if not _VSCODE_ROOT.exists(): print(diagnostic); return 2`.
    Updated docstring exit-code section adds R76/R88/R100
    lineage so future readers connect the family.
  - `scripts/check_i18n_js_no_cjk.py::main()` — gated up-front by
    `missing = [r for r in SCOPES[args.scope] if not r.exists()]`,
    fail-loud on any non-empty `missing`. Same docstring update.
  - `tests/test_i18n_no_cjk_path_drift_r101.py` — new combined
    regression suite covering both scanners with 6 cases:
    - ts: missing `_VSCODE_ROOT` → exit 2 (with stderr keyword
      check) + happy-path still works.
    - js: missing webui root in `--scope webui` → exit 2.
    - js: missing vscode root in `--scope vscode` → exit 2.
    - js: partial drift in `--scope all` (one root present, one
      missing) → exit 2 (the strongest contract — partial
      coverage is silent breakage too).
    - js: all three scopes against real roots return 0 or 1, not
      2 — happy path doesn't regress.

    Reverse-injection verified: revert both `main()` functions
    back to their pre-R101 shape and 4 of 6 cases fail with
    informative diagnostics (return code mismatch + stderr
    keyword absence) while the 2 happy-path cases stay green.
    Mirrors R100's verification pattern exactly.

  Result: 6 tests pass (all R101), full ci_gate 3878 passed /
  2 skipped / 0 warnings, ruff lint+format clean. R66/R88/R100/
  R101 are now in lockstep — the silent-skip-on-path-drift
  anti-pattern is purged from the brand-color guard, the HTML
  template coverage scanner, and both i18n CJK literal scanners
  (the four scripts that contained it).

- **R100** — turn the `if not TEMPLATE_PATH.exists()` silent-skip
  in `scripts/check_i18n_html_coverage.py::main()` into a loud
  fail-with-exit-2 (configuration drift). Same silent-broken
  signature R88 fixed on the brand-color guard: when R76 moved
  `static/` from the repo root into `src/ai_intervention_agent/`
  the brand-color script's `DEFAULT_ROOT = "static/css"` started
  pointing at a non-existent directory and the scanner became a
  silent no-op. R88 fixed it by changing the missing-root branch
  from `return 0` to `return 2 + diagnostic`. The HTML coverage
  scanner had the exact same `return 0 + SKIP message` shape; if
  any future refactor renames or relocates `templates/web_ui.html`
  the scanner would silently report `OK` while having zero
  coverage of the template, and any new hardcoded CJK that lands
  in the HTML would slip past CI.

  This is latent — the live tree's `TEMPLATE_PATH` resolves fine
  today, so the existing `test_web_ui_template_has_no_hardcoded_cjk`
  test passes for the right reason. But the silent-skip path was
  exactly one path-rename away from masquerading as coverage,
  matching R88's root cause exactly. Loud failure mode forces the
  reviewer to either update `TEMPLATE_PATH` or restore the file
  rather than letting the gate quietly degrade.

  Decision: copy R88's exact pattern verbatim — `return 2`,
  stderr diagnostic message naming the resolved absolute path
  and pointing at the constant to update. This keeps R66/R88/R100
  in lockstep so future readers seeing one of them recognise the
  shape immediately.

  Fix:
  - `scripts/check_i18n_html_coverage.py::main()` — replace
    `print("SKIP: ..."); return 0` with a multi-line stderr
    diagnostic and `return 2`. Update the docstring's exit code
    section to document the new code with explicit reference to
    R76/R88 lineage.
  - `tests/test_i18n_html_template_coverage.py` — add
    `TestHtmlCoveragePathDriftR100` with three cases:
    - `test_missing_template_returns_exit_2_not_silent_skip`
      monkey-patches `TEMPLATE_PATH` to a non-existent path and
      asserts `main()` returns 2 (not 0).
    - `test_missing_template_emits_clear_stderr_diagnostic`
      asserts the stderr message contains both `ERROR` and
      `configuration drift` keywords so reviewers can't miss
      the diagnostic.
    - `test_existing_template_still_works_normally` runs
      `main()` against the real `TEMPLATE_PATH` and asserts the
      exit code is 0 or 1 (clean / violations) — never 2 — so
      R100 doesn't regress the happy path.

    Reverse-injection verified: revert `_strip_comments` ... no
    wait, revert `main()` back to the `return 0` shape and 2 of
    the 3 R100-specific cases fail with informative diagnostics
    (return code mismatch + stderr keyword check), the
    happy-path case stays green. Mirror of R88's verification
    pattern.

  Result: 4 tests pass (1 existing + 3 R100), full ci_gate
  3872 passed / 2 skipped / 0 warnings, ruff lint+format clean.

- **R99** — close R66's coverage gap by adding hex form `#007aff`
  to the iOS-blue brand-color drift detector. R66 designed the
  `rgba(0, 122, 255, X)` decimal-form scanner against the 64
  observed live in `static/css/main.css`, but didn't account for
  developers writing the **same** color in hex form
  (`#007aff` / `#007AFF`) — and seven such hex hardcodes were
  already present (and silently uncovered) in `main.css`:
  - L2118 `linear-gradient(90deg, #007aff, ...)` — gradient stop
  - L2592, L2678 `border-color: #007aff` — focus borders
  - L3968 `background: #007aff` — solid blue backgrounds
  - L5114 `border-top: 2px solid #007aff` — accent borders
  - L5434 `border-left: 3px solid #007aff` — accent borders
  - L5793 `color: #007aff` — text color

  All seven render as iOS blue under both dark and light modes,
  with the same R65-tracked drift consequence: in light mode the
  brand color is supposed to be Anthropic Orange (`#d97757`), so
  these uncovered hex hardcodes contributed to the very visual
  drift R66 was supposed to gate against. R66 was the right idea
  with an incomplete pattern.

  Followed R66's "baseline-locks-debt, gate-prevents-growth"
  methodology rather than rewriting the existing 34-strong rgba
  baseline: added a parallel `DEFAULT_HEX_BASELINE = 7` that locks
  the hex form's current count, with the rgba-decimal baseline 34
  unchanged (the two formats describe distinct snapshots from
  different commit moments — mixing them would distort the
  "refactor reduced baseline" warning signal). Net guard surface
  is `34 (rgba decimal) + 7 (hex) = 41` known iOS-blue hardcodes;
  any _new_ hardcode in either form fails the gate.

  Decision history (mirrors R66's own design):
  - **Option A** — extend `_IOS_BLUE_RE` to also match hex,
    bumping baseline to 41. Rejected: muddles "rgba refactor
    progress" with "hex refactor progress" in the same number;
    R66's docstring documents the rgba baseline 34 as the R66
    commit-time snapshot, and changing it retroactively would
    rewrite that historical claim.
  - **Option B** (chosen) — independent `_IOS_BLUE_HEX_RE` with
    its own `DEFAULT_HEX_BASELINE = 7` locked at the R99
    commit-time snapshot. Each baseline matches its own commit-
    moment evidence, refactor-progress-warnings stay separable.
  - **Option C** — only-no-new-hex policy, hex baseline dynamic
    (always == current count). Rejected: would never alert on
    hex form _increases_ via the baseline mechanism, only via
    the running gate, which is opposite of how R66 operates and
    creates inconsistency between the two scanner forms.

  Fix:
  - `scripts/check_brand_color_consistency.py` —
    - add `_IOS_BLUE_HEX_RE = re.compile(r"#007aff\b", re.IGNORECASE)`,
      `count_ios_blue_hex()`, `find_ios_blue_hex_locations()`;
    - `scan_css_files()` signature changes from 2-tuple to
      4-tuple `(rgba_total, rgba_per_file, hex_total, hex_per_file)`;
    - `main()` runs both gates independently, fails if either
      exceeds its baseline, prints separate warnings for either's
      reduction;
    - `--quiet` now also suppresses ℹ️ "below baseline" warnings
      (R66 original quiet only had ✅ to suppress because the
      below-baseline path didn't fire on the live tree; R99's
      double-baseline opens that path more easily so quiet mode
      needs to cover it too — preserves the pre-commit silent-
      success contract).
  - `tests/test_brand_color_consistency_r66.py` — - 7 new `TestCountIosBlueHexR99` cases (lowercase / uppercase
    / mixed case / multiple / non-iOS hex / word boundary /
    brand-color-must-not-false-match); - 2 new `TestFindIosBlueHexLocationsR99` cases (line-number - content / empty when no match); - 2 new `TestScanCssFilesReturnsBothFormsR99` cases (4-tuple
    shape contract + end-to-end fixture proving hex form
    actually gets scanned + comment-stripped); - 1 new baseline-parity `test_default_hex_baseline_matches
_main_css_count` mirroring the rgba decimal one; - adapt `test_default_baseline_matches_main_css_count` to
    the 4-tuple unpack.

            Reverse-injection verified: replace `_IOS_BLUE_HEX_RE` with a
            regex that never matches and 8 of the 35 cases fail with
            informative diagnostics covering both the unit-level
            contract and the live-tree baseline (the reverse-injection
            also caught and prompted the `--quiet` fix above — testing
            paid back its own rent).

  Result: 35 tests pass (22 existing + 13 new), full ci_gate
  3869 passed / 2 skipped / 0 warnings, ruff lint+format clean.
  R66 design philosophy preserved verbatim — the live tree is
  exactly where R99 found it, baseline guard now reflects what
  was on disk all along.

- **R98** — close out the R92/R97 fix family by porting the same
  line-first comment-strip workaround into
  `scripts/check_i18n_js_no_cjk.py::_strip_comments`. R92 originally
  fixed the bug in two of the four sibling i18n scanners
  (`check_i18n_orphan_keys.py`, `check_i18n_param_signatures.py`)
  and pinned the trigger case in its docstring as
  `static/js/app.js:538`'s `// 走 locales/*.json 静态 key` comment
  swallowing 688 lines into the next `*/`. R97 ported the fix to
  the third sibling (`check_i18n_ts_no_cjk.py`). R98 cleans up the
  fourth — `check_i18n_js_no_cjk.py` was the only scanner in the
  family still running `BLOCK_COMMENT_RE.sub` first.

  Empirical impact on the current tree:
  - `static/js/app.js:539-1201` — 509 lines silently blanked by the
    buggy strip pass before STRING_RE ever ran (triggered exactly
    by `app.js:538`, the very line R92's docstring named).
  - `static/js/i18n.js:1015-1089` — 58 more lines blanked,
    triggered by `i18n.js:1013`'s
    `// 通道，值来自 locales/*.json...` comment.
  - 0 hardcoded CJK literals are currently inside those blanked
    regions, so the gate kept returning
    `OK: no hardcoded CJK string literals` for the wrong reason.

  Decision history mirror R97 — token-level lex prototype rejected
  for the same RegExp-literal slash-ambiguity reason that
  `webview.ts:575`'s `(html.match(/`/g) || [])`exposed in R97;
line-first workaround chosen for parity with the three already-
fixed siblings, with the`//`inside string literals trade-off
documented inline. Empirically`static/js/_.js`plus`packages/vscode/_.js`contain 0 string literals that mix`//`
  with CJK, so the trade-off is academic for the current codebase.

  Diagnostic note: the initial R98 impact survey accidentally
  used a regex pattern of `r"/\\\*.*?\\\*/"` typed at the zsh
  command line. Shell + raw-string double-escaping turned that
  into a literal-backslash matcher (`/\\*.*?\\*/`), which produced
  spurious matches and made the bug look 5x worse than it was
  (10 affected files / 2k lines / 19 missed CJK literals). After
  rewriting the diagnostic into an actual `.py` file with a
  proper `r"/\*.*?\*/"` pattern, the real impact dropped to
  the 2 files / 567 lines / 0 missed literals reported above.
  Filed as a meta-lesson: any "scope of damage" survey for a
  regex-related silent breakage should run from an editor file,
  not a shell `-c` invocation, because shell escape semantics
  silently corrupt the regex.

  Fix:
  - `scripts/check_i18n_js_no_cjk.py::_strip_comments` — rewrite to
    line-first via `find("//")` plus a single block-comment regex
    pass, exactly matching the R97 implementation. Inline
    docstring documents the strip-order rationale, the regex-
    literal lex pitfall (so nobody re-upgrades to a token-level
    lex without understanding the `webview.ts:575` trap), and the
    URL-string-`//` trade-off carried over from R92/R97.
  - `tests/test_i18n_js_no_cjk_strip_order_r98.py` — new
    fixture-based regression suite, structurally identical to
    `test_i18n_ts_no_cjk_strip_order_r97.py` (5 cases: bare `/*`
    after `//` plus a later legit `*/`; multi-line span with
    three intermediate CJK literals; byte-length parity for
    `\n`-preserving substitution; byte-offset parity; end-to-end
    `scan_file()` round-trip via `tempfile.NamedTemporaryFile`).
    Reverse-injection verified: swap `_strip_comments` back to
    the buggy block-first form and 4 of 5 cases fail with
    informative diagnostics (the `byte_length` case is
    intentionally a weaker invariant that both implementations
    satisfy — kept because it documents the offset-preservation
    contract that `scan_file()` depends on).

  Result: with R98 landed, all four i18n strip-comment scanners
  use the same R92 line-first folkway and are in lockstep as
  their respective docstrings have always claimed.

- **R97** — repair the same line-vs-block comment ordering bug
  in `scripts/check_i18n_ts_no_cjk.py::_strip_comments` that R92
  already fixed in the **sibling** scanner
  `scripts/check_i18n_orphan_keys.py::_strip_source_comments`.
  Both scanners share the same job — strip comments before
  scanning literals — and both originally ran the passes in the
  buggy order: `BLOCK_COMMENT_RE.sub` first, `LINE_COMMENT_RE.sub`
  second. R92 caught the orphan-keys variant; the no-cjk-literal
  variant slipped through because, by accident, the only line in
  `packages/vscode/extension.ts` that triggers it
  (`extension.ts:59 // 命中 repo root...packages/* 多走一`) is
  immediately followed by ~50 lines that **also** happen to be
  real comments — so the buggy block-comment regex swallowed
  ~50 lines of real source into blank space, but those 50 lines
  contained no string literals so the scanner reported zero
  false positives. Latent silent breakage: any future patch that
  inserts a hardcoded CJK string anywhere inside that swallowed
  region (or in any other `// foo /* bar` line-comment context
  that gets added later) would slip past the gate untouched.

  Symptom thread (none visible until R97):
  - `python scripts/check_i18n_ts_no_cjk.py` was reporting
    `OK: no hardcoded CJK string literals` every run. True for
    the current tree, but not robust — the gate was passing for
    the wrong reason on `extension.ts`. Diagnostic harness
    (drop-in mock of the strip pass) showed 50 contiguous lines
    of real source were being mass-blanked before STRING_RE
    even ran.
  - The companion fix in `check_i18n_orphan_keys.py`
    (R92, commit `55634b2`) already documents the exact same
    `// see locales/*.json`-style trap and its line-first
    workaround. Both scripts were supposed to "stay in
    lockstep" per R92's docstring, but the lockstep was only
    enforced for the orphan-key gate.

  Root cause: copy-paste skew. When the no-cjk-literal scanner
  was added in P8 (a later cycle than the orphan-keys scanner),
  it adopted the same buggy strip implementation that R92 later
  fixed in the orphan-keys side — but the R92 fix never got
  back-ported to the no-cjk side. Tests on `extension.ts` kept
  passing for the unrelated reason described above, so the skew
  remained invisible.

  Considered fixes:
  - **Token-level lex** identifying line/block comments + three
    kinds of string literals in a single pass (so comment
    starters inside strings, and quote chars inside comments,
    both get respected automatically). Prototype passed 7
    boundary fixtures including the R92 trap and the
    URL-with-CJK case (`"https://中文.example.com"`), but
    immediately blew up on `webview.ts:575`
    `(html.match(/`/g) || []).length`: the bare backtick
inside a regex literal got mis-identified as a template
literal opener, swallowing 30+ subsequent lines and
producing 30 false positives. Full JavaScript regex
literal recognition needs to solve the slash-ambiguity
(`a/b/c` is division **or** a regex depending on context)
    and the engineering cost vs. payoff is way out of balance
    for a one-line scanner fix.
  - **Match R92 exactly** (chosen). Walk source line-by-line,
    use `line.find("//")` to clip the line at the first `//`
    occurrence (replacing the tail with spaces), then run the
    block-comment regex over the result. The known
    trade-off — `//` appearing inside a string literal will
    truncate the string in the scanner's view — is documented
    inline. Empirically (`packages/vscode/*.ts` over 7 files,
    1.1k+ lines) the 8 string literals containing `//` are all
    ASCII URLs (`https://github.com/...`, `http://localhost`,
    etc.); zero of them contain CJK. If the codebase ever
    grows a "URL string with a CJK domain that also needs
    i18n" then we'll graduate to a stage-aware lex; until
    then, parity with R92's already-stable approach is the
    cheapest safe fix.

  Fix:
  - `scripts/check_i18n_ts_no_cjk.py::_strip_comments` — rewrite
    to walk lines with `find("//")` first, then a single
    `/\*.*?\*/` block-comment regex pass. Replacement uses
    space chars for non-`\n` content so byte offsets are
    preserved exactly, keeping
    `stripped[:start].count("\n") + 1` line-number mapping in
    `scan_file()` accurate. Inline docstring documents the
    pass-order rationale, the regex-literal lex pitfall (so
    nobody upgrades back to a token-level lex without
    understanding the webview.ts:575 trap), and the
    URL-string-`//` trade-off carried over from R92.
  - `tests/test_i18n_ts_no_cjk_strip_order_r97.py` — new
    fixture-based regression suite, independent of
    `extension.ts`'s current contents, that locks the
    line-first contract. 5 cases: bare `/*` after `//` plus a
    later legitimate `*/`; multi-line span with three
    intermediate CJK literals; byte-length parity for
    `\n`-preserving substitution; byte-offset parity for the
    triggering shape; and an end-to-end `scan_file()` round-trip
    via `tempfile.NamedTemporaryFile`. Reverse-injection check:
    swap `_strip_comments` back to the buggy block-first
    implementation and 4 of the 5 cases fail (the
    `byte_length` case is intentionally a weaker invariant
    that both implementations satisfy — kept because it
    documents the offset-preservation contract that
    `scan_file()`'s line-number math depends on).

- **R96** — repair a silently-skipped CSRF parity test. The R72-D
  fix tightened `normalizeLang` in **two** mirrored
  files — `static/js/i18n.js` and `packages/vscode/i18n.js` — and
  the regression suite `tests/test_i18n_normalize_lang_csrf_r72d.py`
  was supposed to exercise both. In practice
  `test_packages_vscode_i18n_consistency` skipped on every run
  because the JS sandbox harness only looked at
  `sandbox.window.AIIA_I18N`, while the vscode mirror exports via
  `globalThis.AIIA_I18N = api`; under `vm.runInContext` the
  `globalThis === sandbox` aliasing places the api at
  `sandbox.AIIA_I18N`, leaving `sandbox.window.AIIA_I18N` undefined
  and the harness short-circuited to `skipTest("doesn't expose
normalizeLang via window")`. So R72-D's "vscode mirror must keep
  the same hardening" contract was a green test that never
  actually ran.

  Symptom thread:
  - `pytest -v -rs tests/test_i18n_normalize_lang_csrf_r72d.py`
    consistently reported the vscode parity case as `SKIPPED`
    with reason _"packages/vscode/i18n.js doesn't expose
    normalizeLang via window: NODE_FAIL: FAIL: normalizeLang not
    exported"_. The wording made it look like the file _itself_
    was broken; reviewers reasonably concluded it was
    environmental (unusual node host) and the case was tolerated.
  - `packages/vscode/i18n.js:986-994` does export the api: it
    just chooses `globalThis.AIIA_I18N = api` first and only
    falls back to `window.AIIA_I18N = api` if the globalThis
    write throws. Inside the harness the globalThis write succeeds
    (because `sandbox.globalThis = sandbox`), so the fallback
    branch is never taken — and the harness only ever looked at
    the fallback location.
  - Net effect: one live `normalizeLang` mirror was being
    fuzz-tested against `KNOWN_GOOD` and `UNKNOWN_OR_HOSTILE`
    every PR, the other was untested. A regression in the vscode
    copy (e.g. losing the `zh-TW → zh-CN` fold or the
    path-traversal collapse to `DEFAULT_LANG`) would land on
    `main` with green CI. CodeQL would still flag it on the
    next scan, but only after release.

  Root cause: silent-skip masquerading as coverage. The harness
  was written when both files used `window.AIIA_I18N = api` (back
  in v1.5.x); a later refactor (the `globalThis` + try/catch
  fallback in `packages/vscode/i18n.js`) shifted the export site
  but the harness was never updated. The "skip if missing" guard,
  added to handle environments without node, kept the suite
  green while the actual contract eroded.

  Fix:
  1. **Harness**: extend the api lookup to
     `sandbox.window.AIIA_I18N || sandbox.AIIA_I18N`, with a
     comment naming both export shapes and the historical
     reason. Both files now resolve the api on first try.
  2. **Test scope**: replace the vscode case's single-input
     smoke (`evil/path → en`) with the same dual-set assertion
     `static/js/i18n.js` already gets:
     `_assert_known_canonical(_I18N_JS_VSCODE)` walks
     `KNOWN_GOOD` (12 inputs incl. `zh-TW`, `xx-AC`, `pseudo`)
     and `_assert_default_lang(_I18N_JS_VSCODE)` walks
     `UNKNOWN_OR_HOSTILE` (13 inputs incl.
     `../../../etc/passwd`, `javascript:alert(1)`,
     `Object.prototype`). 25 sub-asserts vs the original 1 —
     the vscode mirror now has equivalent coverage.
  3. **Self-test**: temporarily reverting
     `packages/vscode/i18n.js::normalizeLang` to either
     `return raw` or a partial fold (only `zh-cn`, no `zh-TW`)
     reproduced exactly the failure shape we'd want
     (`AssertionError: 'evil/path' != 'en'` and
     `normalizeLang('zh-TW') should be 'zh-CN', got 'en'`).
     Restoring the file returned to green — confirming the
     gate now actually fires.

  Verification: `ci_gate.py` green; `pytest -q` shows
  `3847 passed, 2 skipped` (was 3846 passed, 3 skipped — net +1
  test that now actually runs, no new skips). The two remaining
  skips are intentional (`test_pre_reserved_keys_not_yet_consumed`
  marks an unimplemented Future hook; `test_vsix_artifact_under_
fail_budget_if_present` is fixture-driven and only runs when a
  prebuilt `.vsix` exists in-tree).

- **R95** — fix a TOML-escape silent breakage in
  `docs/configuration.{md,zh-CN.md}` where the
  `[feedback]::prompt_suffix` Default column showed
  `"\\n请积极调用 interactive_feedback 工具"` (two backslashes + `n`)
  while `config.toml.default` line 140 declared
  `"\n请积极调用 interactive_feedback 工具"` (TOML-escaped real
  newline). Add a TOML-roundtrip parity gate
  (`tests/test_config_docs_string_default_roundtrip.py`).

  Symptom thread:
  - `config.toml.default` line 140:
    `prompt_suffix = "\n请积极调用 interactive_feedback 工具"` —
    TOML's basic-string `\n` is an escape sequence, parsed to byte
    `0x0A`. The runtime default is therefore "real newline + 中文".
  - The configuration tables in both `docs/configuration.md` line 207
    and `docs/configuration.zh-CN.md` line 195 listed the Default as
    `` `"\\n请积极调用 interactive_feedback 工具"` ``.
  - Markdown does **not** unescape backslashes inside
    backtick-delimited inline code, so the GitHub-rendered cell
    showed `"\\n请积极…"` (two literal backslashes followed by `n`).
  - A user "restoring the default" by copy-pasting that rendered
    string into their own `config.toml` ended up with
    `prompt_suffix = "\\n请积极…"`. TOML parses `\\` to a literal
    backslash and `n` to a literal `n`, so the resulting string
    starts with the **two characters `\n`**, not a newline. The AI
    suffix then renders glued to the user's feedback with no line
    break — wrong layout, no warning, no error. Pure silent
    breakage that has been live since the prompt-suffix feature
    landed in v1.5.x.
  - `tests/test_web_ui_routes.py::test_only_prompt_suffix_is_updated`
    and `tests/test_reset_feedback_config_endpoint.py` both pass real
    `"\n…"` strings around (line 605, 2163, 70 etc.), so the
    in-memory contract has always been "leading byte 0x0A" — the
    drift was strictly between the canonical TOML value and the
    docs presentation, with no symptom inside the test suite.

  Root cause: docs authors inserted an extra backslash to "make the
  newline visible" in the rendered table, not realising that
  backtick code in Markdown preserves backslashes verbatim, so the
  reader sees more backslashes than the canonical TOML actually
  contains. None of the existing parity gates ever cross-checked
  the _parsed value_ of the docs cell against the parsed value in
  `config.toml.default` — `test_config_docs_parity` only checks
  that the **key set** is identical between the table and the
  template; `test_config_docs_range_parity` only validates numeric
  bounds. A pure-string default could drift like this and stay
  invisible until a human reviewer (R95) caught it by eye.

  Fix:
  1. **Drop the extra backslash** in both translations:
     `docs/configuration.md` line 207 and
     `docs/configuration.zh-CN.md` line 195 now read
     `` `"\n请积极调用 interactive_feedback 工具"` `` (one backslash
     - `n`), with an inline note clarifying that the leading `\n`
       is a TOML-escaped newline that the parser turns back into a
       real newline at load time. So a user copy-pasting the
       rendered cell into `config.toml` gets the same parsed bytes
       as the template default — round-trip identity restored.
  2. **Add a TOML-roundtrip parity gate**:
     `tests/test_config_docs_string_default_roundtrip.py` (2 tests,
     both green post-fix). It walks the table rows in both
     configuration docs, finds every row whose type is `string`
     and whose Default cell is a backtick-wrapped TOML literal,
     wraps it as `k = <literal>` and runs `tomllib.loads`, then
     compares the parsed value against the same key in
     `config.toml.default`. On mismatch the failure message shows
     both parsed sides plus the literal note _"用户照 doc 复制粘贴
     会得到错误默认值"_ so the next contributor immediately sees
     the impact axis. The companion test
     `test_prompt_suffix_doc_roundtrips_to_real_newline` is a
     byte-equal lock that asserts `feedback.prompt_suffix` starts
     with `0x0A` and that both translations roundtrip to it,
     making the historical regression impossible to reintroduce
     without flipping the test red.
  3. **Self-test the gate**: temporarily reverting the docs fix
     reproduced two failures with the exact `"\\n" → "\n"` diff
     printed; restoring the fix returned to green — proves the
     gate would have caught R95 at PR time.

  Verification: `ci_gate.py` green (3846 passed, 3 skipped, 0
  warnings, 0 errors).

- **R94** — fix a docs-to-code drift in
  `docs/troubleshooting.{md,zh-CN.md}` that told users to set
  `web_ui.bind_interface` to fix the "phone can't reach `ai.local:8080`
  on the same Wi-Fi" symptom, when the option actually lives under
  `[network_security]`. Add a parity gate
  (`tests/test_config_docs_inline_parity.py`) that scans every
  `docs/**/*.md` (except `configuration{,.zh-CN}.md` and `CHANGELOG.md`,
  both already covered by other gates) for backticked
  `<section>.<key>` references and fails if the pair is not declared
  in `config.toml.default`.

  Symptom thread:
  - The "Mobile / tablet can't open `ai.local:8080`" recipe in
    `docs/troubleshooting.md` line 106 (and the Chinese mirror at
    `docs/troubleshooting.zh-CN.md` line 96) prescribed:
    > Set `web_ui.bind_interface` to your LAN IP …
  - `config.toml.default` line 92-93 declares `bind_interface` under
    `[network_security]`, **not** `[web_ui]`. The Pydantic model
    `WebUISectionConfig` (`shared_types.py`) has no `bind_interface`
    field; `network_security.py::load_network_security_config()` is the
    real reader.
  - Result: a user who copy-pastes
    `[web_ui]\nbind_interface = "0.0.0.0"` into their `config.toml`
    sees **no warning, no error, and no behavioural change** — the key
    is silently ignored because Pydantic's `extra="ignore"` policy
    treats unknown keys as comments. The phone-on-LAN issue stays
    broken and the user has no signal that the recipe is wrong.
  - The mirror docs page `docs/configuration.zh-CN.md` line 150 already
    listed `bind_interface` correctly under `[network_security]`, so
    `test_config_docs_parity` could not catch the drift (it only
    cross-checks the `configuration*.md` tables vs the TOML template,
    not free-form prose in other docs).

  Root cause: same shape as R93. An option was correctly **declared**
  on the canonical surfaces (TOML template + Pydantic model +
  `configuration.md` table), but a separate **prose recipe** in
  troubleshooting docs put the key in the wrong section. None of the
  existing parity gates inspected free-form docs for inline
  `section.key` references — that surface had zero CI coverage. So
  any docs author writing a quick recipe could land a section-name
  typo and only a real user trying the recipe would notice (and even
  then they'd most likely blame their own setup, not the docs).

  Fix:
  1. **Correct both translations**:
     `docs/troubleshooting.md` line 106 and
     `docs/troubleshooting.zh-CN.md` line 96 now say
     `network_security.bind_interface`, with a one-line clarification
     reminding readers that `bind_interface` lives under
     `[network_security]` (it overrides `web_ui.host` at runtime — see
     `web_ui_mdns_utils.py::detect_best_publish_ipv4`).
  2. **Add a regression gate**:
     `tests/test_config_docs_inline_parity.py` (2 tests, both green
     post-fix). It walks `docs/**/*.md`, finds every backticked
     `<section>.<key>` whose `section` is one of the live top-level
     TOML sections, and asserts the `key` is declared there. On
     mismatch the failure message points to the section that _actually_
     owns the key — so the next contributor who writes
     `feedback.bind_interface` gets _"`bind_interface` is declared
     in `[network_security]`, write `network_security.bind_interface`
     instead"_ verbatim, no detective work required. False-positive
     suppression: file-suffix-shaped keys (`web_ui.py`, `server.py`,
     `i18n-keys.d.ts`) are excluded so the lessons-learned posts
     keep working; `CHANGELOG.md` and the `configuration{,.zh-CN}.md`
     tables are excluded because they're either historical record
     (CHANGELOG keeps old key names from migrations) or covered by
     existing parity gates (`test_config_docs_parity.py`,
     `test_config_defaults_consistency.py`).
  3. **Self-test the gate**: temporarily inverting the fix locally
     reproduced the failure with the suggested-section message, then
     restoring the fix returned to green — proves the gate would have
     caught R94 at PR time.

  Verification: `ci_gate.py` green (3844 passed, 3 skipped, 0 warnings,
  0 errors).

- **R93** — wire up the `AI_INTERVENTION_AGENT_LOG_LEVEL` env var
  contract that `docs/troubleshooting.md` and `.github/SUPPORT.md`
  have promised since v1.5, and surface the `web_ui.log_level` config
  key that was already honoured by `enhanced_logging` but never
  declared in `config.toml.default` or the configuration tables.

  Symptom thread:
  - `docs/troubleshooting.md` line 11 told users _"set
    `AI_INTERVENTION_AGENT_LOG_LEVEL=DEBUG` for the standalone server"_
    when reporting issues. `.github/SUPPORT.md` repeated the same
    instruction in the bug-report checklist (lines 24, 74).
  - `rg AI_INTERVENTION_AGENT_LOG_LEVEL src/` returned **zero matches** —
    the env var was a documentation promise the code never kept. Users
    who copy-pasted the recipe got no DEBUG output, no error, no hint
    that the knob was inert. Pure silent breakage.
  - Worse, `enhanced_logging.get_log_level_from_config()` _did_ already
    read `web_ui.log_level` from `config_manager` (line 476), but
    `config.toml.default` had no `[web_ui] log_level = …` entry, so
    discovering this option required reading the source. The Pydantic
    `WebUISectionConfig` model (`shared_types.py`) also lacked the
    field, so `_get_default_config()` (which generates defaults from
    Pydantic models) couldn't even tell users about it.

  Root cause: an option was added to the runtime read path but never
  to the **declared interface** (Pydantic model + TOML template + docs
  table). The configuration-parity gates (`test_default_config_keys_match_template`,
  `test_chinese_doc_matches_template`, `test_english_doc_matches_template`)
  only catch _disagreement among the four declared surfaces_; if all
  four are silent about a key the runtime _does_ read, no parity test
  fires. The env var was never declared anywhere except prose docs.

  Fix:
  1. **Implement the env var contract**: `enhanced_logging.py::get_log_level_from_config`
     now consults `os.environ["AI_INTERVENTION_AGENT_LOG_LEVEL"]`
     **first**, then falls back to `web_ui.log_level` from config,
     then to `WARNING`. Invalid env var values log a warning and
     fall through to config (don't block startup). Empty / whitespace
     env values are treated as "not set" so accidental `AI_INTERVENTION_AGENT_LOG_LEVEL=`
     in shells doesn't silently clobber config to default WARNING.
  2. **Surface the config key**: added `log_level: SafeStr = "WARNING"`
     to `WebUISectionConfig` (Pydantic), the corresponding line to
     `config.toml.default` with a link to the env var override, and
     a row in both `docs/configuration.md` and `docs/configuration.zh-CN.md`
     `[web_ui]` tables. The four parity gates now lock the contract.
  3. **5 regression tests** in `tests/test_enhanced_logging.py::TestEnvVarOverridesConfig`:
     env var DEBUG wins over config WARNING; env var case-insensitive
     ("info" → INFO); invalid env var falls back to config; empty
     env var falls back to config (NOT to default WARNING — the
     historical bug shape); no env var honours config (back-compat).
     Each test pops the env var in `setUp` and restores in `tearDown`
     so concurrent test workers don't leak env state.

  Side effects:
  - `docs/api.zh-CN/enhanced_logging.md` regenerated by
    `scripts/generate_docs.py` because the function's Chinese
    docstring expanded to describe the new resolution order.
  - VS Code extension users are unaffected: `ai-intervention-agent.logLevel`
    in VS Code settings is a separate axis (the VS Code extension
    process / channel; not the standalone Python server's
    `enhanced_logging` instance) and was already real.

  Verified by: `pytest -W error` 3842 passed (was 3837; +5),
  3 skipped, 0 failed, 0 warnings; `ci_gate.py` ALL RED-TEAM CASES
  PASS; `pre-commit run --all-files` 14/14 passed; `pytest tests/test_config_*parity*.py
tests/test_config_defaults_consistency.py` 6/6 passed.

- **R92** — repair `_strip_source_comments` line-comment / block-comment
  ordering bug shared by `scripts/check_i18n_orphan_keys.py` and
  `scripts/check_i18n_param_signatures.py`, plus eliminate one silent
  i18n false-positive that the bug had been masking. Symptom thread:
  - `uv run python scripts/check_i18n_orphan_keys.py` reported
    `[vscode] 0 orphan key(s) (145 used / 144 total)`. The
    `used > total` skew is **structurally impossible** for a healthy
    scanner — used keys are a subset of locale keys.
  - Tracked the extra "key" to `packages/vscode/extension.ts` line 10
    banner comment `// 让 hostT('statusBar.unkown') 在 tsc 阶段就挂掉`
    (a deliberately-misspelled example, paired with a TS literal-union
    type that catches the typo at compile time). The orphan scanner's
    `JS_T_CALL_RE` regex matched the comment string as if it were a
    real call site, so the fake key `statusBar.unkown` got counted as
    "used" while never appearing in the locale → `used = total + 1`.
  - First fix: rewrote the banner so the example doesn't include a
    full `hostT(<quote><key><quote>)` shape. Re-running the scanner
    now yielded `144 used / 144 total`, **but** comparison with
    `scripts/check_i18n_param_signatures.py` (which already ran
    `_strip_source_comments` on every file before regex-matching)
    revealed an architectural inconsistency: only one of two i18n
    scanners stripped comments. Backported the helper to
    `check_i18n_orphan_keys.py` for cross-scanner parity.
  - Backporting immediately surfaced **17 new "orphans"** in
    `static.js` (`status.copied` / `status.copyFailed` /
    `status.submitting` / `status.submitFailed` / 13 others). Live
    `t(...)` call sites at lines 539 / 554 / 1050 / 1124 should NOT
    be invisible to the scanner. Bisecting found that
    `_strip_source_comments` itself was buggy:
    `_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)` matched
    the bare `/*` **inside the line comment**
    `// 走 locales/*.json 静态 key 且无参数` (line 538 of `app.js`),
    treated it as a block-comment opener, and silently swallowed the
    next 688 lines of real code until it found a `*/` further down
    in the file. So 6 distinct `status.*` keys (and any `t(...)` call
    in those 688 lines) were invisible to the scanner — a textbook
    "scanner-rendered-blind-by-its-own-comment-handling" pre-existing
    bug that was perfectly cancelled out by the _first_ bug
    (`statusBar.unkown` from the comment over-counted, `status.*` from
    swallowed code under-counted, net delta happened to be `+1`,
    looking deceptively like a single missing key).
  - Real fix: invert the strip order — process **line** comments
    first (turning the entire `//`-tail of each line into spaces),
    **then** strip block comments on the result. With line comments
    already neutralised, the orphan `/*` inside `// … /*.json …`
    can no longer act as a block-comment opener. Applied identically
    to both scanners (must stay in lockstep).
  - Locked in by 5 new regression tests in
    `tests/test_i18n_orphan_keys.py::TestStripSourceComments`:
    `test_line_comment_t_call_is_stripped`,
    `test_block_comment_t_call_is_stripped`,
    `test_real_t_call_outside_comment_survives`,
    `test_line_comment_with_slash_star_does_not_swallow_following_code`
    (the canonical regression fixture for **this** bug),
    `test_line_offsets_preserved`. Final state:
    `[web] 0 orphan key(s) (217 used / 217 total)`,
    `[vscode] 0 orphan key(s) (144 used / 144 total)`. Verified by
    `uv run python scripts/ci_gate.py` (3837 passed, 3 skipped,
    0 failed, 0 warnings) and `--with-vscode` (28 mocha tests + VSIX
    package).

- **R91c** — document the `/api/close` shutdown Timer's intentional
  non-daemon mode in `src/ai_intervention_agent/web_ui.py`. The
  endpoint kicks off `threading.Timer(0.5, self.shutdown_server)`
  to give the HTTP response time to flush back to the client
  before `os.kill(SIGINT)` tears Flask down. `threading.Timer`
  defaults `daemon=False`, which is the **correct** choice for
  this code path (Python interpreter waits for the timer to fire
  before shutting down → guaranteed graceful shutdown), but the
  same default would be **wrong** for any other Timer in the file
  (we explicitly set `daemon=True` on the mDNS register thread,
  the file watcher thread, the task-queue cleanup thread, and the
  notification timers). Without an inline comment, future
  contributors who notice the pattern divergence may "normalize"
  this Timer to daemon=True and silently break the optimistic-200
  shutdown contract — the visible failure mode is exactly the
  bug we want to prevent: front-end gets `{"status": "success"}`
  but the service stays up indefinitely because the Python
  interpreter killed the timer before SIGINT fired. Add a 6-line
  block comment naming the contract and pointing at the failure
  mode. Pure docs; runtime behavior unchanged. Verified by:
  `curl -X POST /api/close` → `{"status":"success"}`, then
  `curl /api/health` 2 seconds later → curl exit 7
  ("Couldn't connect"), confirming the non-daemon timer **did**
  finish executing `shutdown_server()` before the process exited.

- **R91b** — patch Node 21+ `globalThis.navigator` read-only accessor
  in 14 i18n test harnesses (1 real failure + 13 preventive). Node
  v21 introduced `globalThis.navigator` as a built-in property; in
  Node v22+ that property became a **read-only accessor**
  (descriptor: `{ get: [fn], set: undefined, configurable: true }`)
  which silently swallows the assignment `globalThis.navigator =
{ language: 'X' }`. Effect on the project's i18n test corpus:
  - Hard failure: `tests/test_i18n_pseudo_runtime_switch.py::TestPseudoDetectLang::test_navigator_language_still_works`
    expected the harness body to override `navigator.language` to
    `'zh-HK'` so `detectLang()` can collapse the BCP-47 zh tag to
    `'zh-CN'`. Under Node 24.14.0 the assignment was a no-op,
    `navigator.language` stayed at the platform default `'en-US'`,
    `detectLang()` collapsed to `'en'`, and the assertion
    `assertEqual(out, 'zh-CN')` flipped from green to
    `AssertionError: 'en' != 'zh-CN'`. Discovered when running
    `uv run python scripts/ci_gate.py` on a Node-24 dev machine
    that previously was Node-20 (`fnm default v20.x`); CI was still
    on Node-20 so green there, masking the regression.
  - Latent / preventive: 13 other test files use the same harness
    pattern `globalThis.navigator = { language: 'en' };`. None of
    them currently fail because they either pass `lang: 'X'` to
    `api.init()` explicitly (bypassing `detectLang`) or because
    `'en'` happens to coincide with the Node platform default
    (`'en-US'` collapses to `'en'`). But the moment any future test
    in this group adds an assertion that depends on the mocked
    `navigator.language` value (e.g. `'fr'` / `'zh-CN'` / `'pseudo'`
    via navigator), it would fail silently and silently mis-route
    the test through the wrong locale path.

  Fix: replace every occurrence of `globalThis.navigator = { ... }`
  with `Object.defineProperty(globalThis, 'navigator', { value: { ... },
writable: true, configurable: true, enumerable: true })`. The
  defineProperty form bypasses the read-only descriptor by
  redefining the property as a **data property** (writable: true)
  whose value is fully under the harness's control. Identical
  semantics on Node ≤ 20 (where the property was already
  writable), bug-correct semantics on Node ≥ 22. 18 sites across
  14 files, single-line form chosen for harness-internal `textwrap.dedent`
  brevity (multi-line form would interact unpredictably with the
  surrounding `%(lang_literal)s` % interpolation in
  `test_i18n_relative_time_thresholds.py` / `test_i18n_intl_wrappers.py`
  / `test_i18n_icu_plural.py`).

  Why this didn't get caught earlier: Node v22 (April 2024) shipped
  the read-only flag behind an experimental flag; v22.5 (July 2024)
  promoted it to default-on; v24 (October 2025, current LTS) has
  it permanently. The project's `package-lock.json` pins `"node":
">=18.12"` (no upper bound), so any developer following the
  documented `fnm default v24.14.0` workflow would hit it; CI's
  `actions/setup-node@v4` defaults to the latest LTS (v24 since
  Oct 2025), but our `vscode:check` mocha smoke uses the running
  test extension's bundled Node which is older — explaining why
  vscode test stayed green while the standalone harness flipped red.

  Verified by `uv run pytest tests/ -k i18n -q` → 469 passed / 2
  skipped, all 14 modified files included in the green set.

- **R91** — fix two README image-render regressions plus the long
  tail of `icons/icon.svg` path drift left by R76. Two distinct
  failure modes had the same visible symptom ("repo landing page
  shows broken / oversized images"):
  1. **`<img style=...>` silently stripped by GitHub markdown
     sanitizer.** All six in-README screenshot tags carried
     `style="height: 320px; margin-right: 12px;"`, which works
     locally / in IDE preview but is removed when GitHub renders
     README — `style` is not on the GitHub markup whitelist
     (`github/markup#486`). Effect: PNGs were displayed at their
     native 1920×1200 / 750×1266 raster size (≈ 5–10× the intended
     visual height), pushing every "Quick start" / "Key features"
     paragraph below a giant screenshot block. Replace
     `style="height: 320px"` with the whitelisted bare `height="320"`
     attribute (pixel-only, equivalent rendering, no sanitizer
     stripping); two `<picture>` siblings now rely on the inline
     element's natural inter-tag whitespace for the 12 px gap that
     `margin-right` used to provide. Verified by re-checking each of
     the 11 referenced asset paths still resolves to a file in
     `git ls-files .github/assets/`.
  2. **`icons/icon.svg` reference drift** in 5 files that R76 missed
     when it relocated the icon set from `icons/` (repo root) to
     `src/ai_intervention_agent/icons/`. The Flask `/icons/<filename>`
     route was already correct (it computes `_project_root /
"icons"` from `src/ai_intervention_agent/web_ui.py:413`,
     which **is** the new location, so HTTP serving was unaffected),
     but five doc / docstring / comment references still pointed at
     the pre-R76 root path: - `README.md:3` and `README.zh-CN.md:3` — repo logo `<img src>`
     (loaded by GitHub from the relative path → 404 on landing
     page until refreshed) - `scripts/README.md` and `scripts/generate_pwa_icons.py`
     module docstring — "Run after editing `icons/icon.svg`" mis-
     documents the contributor workflow - `src/ai_intervention_agent/icons/icon-maskable.svg` SVG
     comment — references its sibling at the wrong path - `tests/test_pwa_icon_assets.py` docstrings (3 sites)
     mis-state the locked file path; the test logic itself was
     fine because it dereferences `ICONS_DIR` (already updated
     to the post-R76 path), but copy-paste from the docstring
     would lead future maintainers to the wrong file.

  Both classes of fix are pure docs / markup; there is no code or
  runtime behaviour change. The `.vsix` manifest, the
  `manifest.webmanifest`, the `notification-manager.js` icon URL,
  and the Flask `/icons/<filename>` route still use the absolute
  HTTP path `/icons/icon.svg` — those are URL paths, not filesystem
  paths, and remain correct.

- **R90** — fix `.gitattributes` linguist globs that R76 silently
  detached. Three regression-quiet rules pointed at pre-R76
  layout: `locales/**` (now matches nothing — Web UI locales live
  under `src/ai_intervention_agent/static/locales/` and VS Code
  extension locales under `packages/vscode/locales/`),
  `static/**/*.gz` and `static/**/*.br` (now match nothing —
  R20.14-D / R21.4 precompressed siblings live under
  `src/ai_intervention_agent/static/**`). Effect: GitHub linguist
  was counting locale JSON and `.gz` / `.br` files as primary
  language churn since R76, polluting the language-percentage
  pie on the repo landing page. Replace each broken glob with a
  pair (or single src-prefixed) that points at the real
  locations; verify with `git check-attr -a` that `linguist-generated`
  - `-diff` actually apply now. No code or runtime behaviour
    touched.

- **R89** — restore the VSIX packaging pipeline silently broken by R76.
  `scripts/package_vscode_vsix.mjs` had a hard-coded
  `SHARED_TRI_STATE_PANEL_FILES` array listing the four shared
  `@aiia/tri-state-panel` source files at `static/js/...` /
  `static/css/...`. R76 moved those sources to
  `src/ai_intervention_agent/static/{js,css}/...` and updated the
  byte-parity test `tests/test_tri_state_panel_parity.py`, but the
  packager script itself was missed. Result: every invocation of
  `node scripts/package_vscode_vsix.mjs` (called from
  `npm run vscode:package` and `make vscode-check` and the
  release workflow) exits 1 with `@aiia/tri-state-panel 真源缺失：
static/js/tri-state-panel.js`. The byte-parity test continued to
  pass because it independently reads the new `src/` paths and the
  pre-R76 mirror copies in `packages/vscode/` are still
  byte-identical to those new sources, so the test surface didn't
  expose the dead packager. Update the array's first column to the
  `src/ai_intervention_agent/static/...` prefix and refresh the
  comment block. Add a new
  `test_packager_script_src_paths_match_test_source_paths` regression
  test that asserts every `SHARED_PAIRS` source path appears
  literally inside `scripts/package_vscode_vsix.mjs`, so any
  future R76-class layout move that touches one side without the
  other turns red instead of silently breaking VSIX builds.

- **R88** — restore the R66 brand-color guardrail that R76
  silently broke. The R76 PyPA `src/` migration moved
  `static/css/main.css` to
  `src/ai_intervention_agent/static/css/main.css`, but the R66
  guard's two layout hooks didn't follow:
  `scripts/check_brand_color_consistency.py::DEFAULT_ROOT`
  still read `"static/css"` (so `uv run python scripts/check_brand_color_consistency.py`
  exits 2 with "扫描根目录不存在 → static/css") and
  `.pre-commit-config.yaml` still pinned `files: ^static/css/.*\.css$`
  (so the local hook never matched any file in the new layout —
  the worst kind of "silent skip"). Both defaults now point at
  `src/ai_intervention_agent/static/css`. Add three regression
  tests (`TestDefaultsPointAtRealLocations`) that assert
  `DEFAULT_ROOT` resolves to an existing directory, contains at
  least one `.css` file, and the `.pre-commit-config.yaml`
  `files` glob shares the same prefix — so the next layout
  refactor cannot resurrect the silent-broken state without a
  red test.

### Changed

- **R87** — fix `static/locales/**` path-ignore drift in
  `.github/workflows/codeql.yml`. R76 moved `static/` to
  `src/ai_intervention_agent/static/`, but the CodeQL workflow's
  `paths-ignore` glob still pointed at the old location, so any
  pull request touching only locale JSON would silently
  re-trigger the full CodeQL Python + JS/TS analysis (~6 min)
  instead of being filtered out. Update both the `push:` and
  `pull_request:` blocks to point at
  `src/ai_intervention_agent/static/locales/**` and add a brief
  reviewer comment explaining the rename so the next R76-class
  refactor doesn't have to rediscover the linkage.

- **R86** — refresh `.github/PULL_REQUEST_TEMPLATE.md` "Touched
  areas" checkboxes to reflect the post-R76 `src/` layout. The
  previous list pointed at `static/`, `templates/`, `web_ui*.py`,
  `task_queue.py`, `web_ui_routes/`, and `applescript-executor.ts`
  as if they still lived at the repo root; after the R76 PyPA
  `src/` migration they live under
  `src/ai_intervention_agent/` (with `applescript-executor.ts`
  belonging to `packages/vscode/`). Forward-looking checklist
  only — no code touched, no historical CHANGELOG copy adjusted.

- **R85** — refresh `scripts/README.md` inventory: backfill 7
  scripts that shipped between v1.5.22 and v1.6.0 but never
  made it into the README index — `check_brand_color_consistency.py`
  (R66 brand-color guardrail), `check_tag_push_safety.py`
  (R19.1 push-tags-webhook three-tag limit), `generate_pwa_icons.py`
  (PWA / favicon / `apple-touch-icon` family generator),
  `perf_e2e_bench.py` + `perf_gate.py` (R20.14-A E2E perf
  benchmark and regression gate), `precompress_static.py`
  (R20.14-D / R21.4 gzip + Brotli pre-compression), and
  `smoke_test_r50.py` (R50 SSE / `config_changed` debounce
  smoke). Add a new "Visual / brand guardrails" section and a
  "Performance" section so the index is grouped by job-to-be-done
  instead of one flat list. Refresh the footer from "v1.5.22"
  to "v1.6.0" so the staleness signal matches the rest of the
  index.

- **R84** — post-1.6.0 documentation drift cleanup: refresh the
  Supported-versions table in `.github/SECURITY.md` from
  `1.5.x` to `1.6.x`, retitle `docs/lessons-learned-r70s.md`
  from "R71 → R80b cycle" to the actual shipped scope
  "R71 → R82 cycle" (twelve base R-numbers, eighteen counting
  the b/c/d/-D variants), point its forward-looking
  decay-prevention guidance at `v1.6.1+` instead of `v1.5.47+`,
  realign `docs/README.md` / `docs/README.zh-CN.md` Reviewers
  blurbs and `docs/lessons-learned-r60s.md` to the v1.6.0
  release identity, and clean root `package.json` metadata
  (replace the HTML-fragment `description`, populate
  `author`, broaden `keywords` to match the VS Code
  extension's eight-keyword list plus `monorepo`). No code
  paths touched; this is governance- and store-listing-only
  copy work to keep the post-release artefacts honest.

## [1.6.0] — 2026-05-08

> Round-72+ aggregate: a security-triage pass (R72 / R72-D), three
> repo-shape refactors (R73 / R76 / R76b), four zero-warning
> hardenings (R74 / R74b / R74c / R74d / R75), and an R77+ "what
> still needs rounding-out" sweep covering MCP cross-tool compat,
> low-coverage modules, broken docs links, internal post-mortem
> docs, and `coverage.py` parallel-run filesystem hygiene.

### Security

- **R72** — close 16 CodeQL Code Scanning findings: 15
  log-injection (an `enhanced_logging` root-logger
  `InterceptHandler` now sanitises every record reaching the loguru
  pipeline at the boundary, regardless of which third-party
  library called the stdlib logger) + 1 stack-trace exposure in
  `web_ui_routes/system.py` (replaced raw `traceback.format_exc()`
  surfacing in the response body with a generic message). 20 false
  positives + 7 line-shift restate findings dismissed and
  documented in `docs/security-triage-r72.md`. The remaining 5
  OPEN findings are OpenSSF governance issues for the repo owner;
  the 10 OPEN web-XSS / CSRF findings are tracked as R72-D
  follow-ups.
- **R72-D** — close the R72-D batch: harden the locale-set
  endpoint with CSRF protection, dismiss the 9 remaining
  xss-through-dom DOM-XSS findings as false positives (they all
  pivot on a `textContent` write, which is by-construction safe).

### Added

- **R78** — 14 new tests in
  `tests/test_web_ui_routes_system.py` covering the previously
  untested operator-/monitor-facing endpoints
  `/api/system/network-base-url-status`, `/api/system/health`, and
  `/api/system/recent-logs`. Locks down each endpoint's
  decision-tree (e.g. `recommendation` enum cases, `status`
  enum cases for healthy/degraded/unhealthy) and ensures
  internal exceptions return generic error payloads (no stack
  trace exposure regression). Coverage of
  `web_ui_routes/system.py` rises from 58.36% to 84.19%.
- **R79** — 8 new tests in `tests/test_i18n_backend.py`
  (`TestBackendDetectRequestLang`) covering
  `detect_request_lang`'s three-stage fallback (Accept-Language
  header → config*manager → DEFAULT_LANG) and the format-error
  branch in `get_locale_message`. The
  `test_detect_lang_unknown_accept_language_normalizes_to_default`
  case in particular captures a non-obvious property of the
  dispatch tree: `normalize_lang` always returns a value in
  `SUPPORTED_LANGS`, so unsupported headers like `fr-FR` are
  mapped to `en` and the config branch is \_never* consulted —
  important to lock down before adding a third locale (e.g.
  `ja`). Coverage of `i18n.py` rises from 75.81% to 98.39%.
- **R80** — `tests/test_docs_links_no_rot.py` link-rot regression
  guard: walks every `*.md` under repo root + `docs/` +
  `.github/` + `packages/vscode/` + `scripts/`, extracts every
  `[label](target)` link, filters external URLs / fragment-only /
  regex-literal false positives, and verifies the surviving
  relative paths exist on the filesystem. Failure messages list
  exact `md_file:line` for each broken link so a single fix-pass
  can address every regression.
- **R77** — `interactive_feedback` MCP tool gains two new
  cross-MCP-variant compat fields: `timeout_seconds` (alias for
  `timeout`) and `task_id` (accepted but ignored — the server
  always auto-generates an internal task ID). Both close the
  v1.5.36 user-feedback ticket reporting Pydantic
  `unexpected_keyword_argument` ValidationErrors when an agent
  reused arguments shaped for sibling feedback-MCP variants. 3
  new tests in `tests/test_interactive_feedback_errors.py` lock
  the contract: the v1.5.36 reproducer (all three drift fields
  combined) no longer raises, `timeout_seconds` does not
  override server-side `feedback.timeout` config, and external
  `task_id` is silently replaced with the server-generated value.

### Changed

- **R73** — trim the repo root directory: relocate 4 governance
  docs (`CONTRIBUTING.md` / `SECURITY.md` / `SUPPORT.md` /
  `CODE_OF_CONDUCT.md`) into `.github/` per the GitHub-recommended
  layout. The repo root now hosts only README / CHANGELOG / LICENSE
  / TODO and the active config templates.
- **R76** — adopt the PyPA-recommended `src/` layout. Every
  Python module, sub-package, and web asset directory now lives
  under `src/ai_intervention_agent/`. The migration spans 1074
  absolute imports rewritten to `ai_intervention_agent.<m>`, 879
  `unittest.mock.patch` target strings updated, 119 hard-coded
  `static/` / `templates/` / `icons/` / `sounds/` paths re-rooted
  in tests/scripts, and 49 source-text anchors in regex-based
  test contracts. `pyproject.toml` (`[tool.hatch.build.targets.{wheel,sdist}]`),
  `MANIFEST.in`, `.gitignore`, `docs/api(.zh-CN)`, the ESLint
  i18n plugin (`packages/vscode/eslint-plugin-aiia-i18n.mjs`),
  `scripts/ci_gate.py` (`--cov=src/ai_intervention_agent`),
  `scripts/generate_docs.py` (output-dir + index.md generation),
  and `scripts/red_team_i18n_runtime.mjs` are all updated in
  lockstep. The editable-install import path now matches the
  wheel-install path exactly, eliminating the "it works on my
  machine because Python picked up `./web_ui.py` from cwd" class
  of bugs.
- **R81** — internal post-mortem `docs/lessons-learned-r70s.md`
  for the R71 → R82 batch, mirroring the R63 → R70 template
  established by `docs/lessons-learned-r60s.md`. Eight root
  causes (CodeQL noise, governance-doc relocation, zero-warning
  sprint, `src/` layout migration, MCP cross-tool compat,
  defensive-branch coverage, markdown link rot, CHANGELOG
  drift) plus cross-cutting takeaways. `docs/README.md`
  Reviewers section gains the new entry and the index footer
  is refreshed for the v1.6.0 cycle.
- **R82** — relocate `coverage.py` parallel-run intermediate
  files (`.coverage.<host>.<pid>.<rand>`) from repo root to
  the `.coverage_data/` subdirectory via
  `[tool.coverage.run].data_file = ".coverage_data/coverage"`
  in `pyproject.toml`. Each `ci_gate --with-coverage` run used
  to scatter ~50 intermediate files at the repo root before
  `coverage combine` swept them into `.coverage`; the directory
  tree pollution was visible in editors / `ls` / `find` even
  though `.gitignore` already covered them. `.coverage_data/`
  is automatically created by coverage.py ≥5.x and is already
  gitignored. The merged `coverage.xml` artifact stays at the
  repo root (consumed by `.github/workflows/test.yml`'s
  `actions/upload-artifact` step). Local developer
  `.coveragerc` (git-untracked, per-contributor) gets the same
  `data_file` setting in lockstep so both CI and local runs
  behave consistently.

### Fixed

- **R74** — clear 2 `ty` type diagnostics that surfaced after
  upgrading typeshed annotations + sync drifted API docs the
  upgrade caused.
- **R74b** — make 2 single-quote anchors in the VSCode test
  suite prettier double-quote compatible (a long-tail of R71's
  prettier-config landing).
- **R74c** — rewrite 2 `# type: narrowing` comments as plain
  prose so a future contributor doesn't think they're real
  type-checker directives.
- **R74d** — bump `package-lock.json` `@types/node` to the 25.x
  lockfile range to satisfy the upstream constraint after the
  monorepo's transitive `@types/node` requirement tightened.
- **R75** — enable the `ruff` `LOG` lint family + fix 4
  root-logger / `exc_info` anti-patterns (e.g. `logging.getLogger
("root").error(...)` -> `logger.error(..., exc_info=True)`).
- **R80** — repair 14 broken relative markdown links in
  `.github/CONTRIBUTING.md` (4) / `.github/SECURITY.md` (2) /
  `.github/SUPPORT.md` (8) where the original maintainer-authored
  links assumed a "repo root" mental model but GitHub renders
  relative links from the file's own directory. All 14 links now
  use `../` prefixes and resolve correctly on github.com.

### Removed

- **R76b** — drop the `config.jsonc.default` template. The JSONC
  config format hasn't been the recommended path since v1.5.0
  (default switched to TOML, with legacy `config.jsonc` files
  still auto-migrated by `config_manager` at startup). Removing
  the sample template eliminates the maintenance load of keeping
  range/comment-parity tests in lockstep across two formats and
  removes a confusing duplicate entry from the "open default
  config" UI button. Existing JSONC user configs continue to
  auto-migrate; only the _sample_ template is gone.

## [1.5.45] — 2026-05-08

> Round-57+58 round-up: two complementary observability/safety wins
> on top of v1.5.44 — exposing per-client rate-limit budgets in
> response headers, and shielding the SSE bus from a single oversize
> emit that would fan-out N× memory across subscribers.

### Added

- **R57** — `Limiter(headers_enabled=True)` so every rate-limited
  response now carries the IETF-draft / RFC-6585-aligned
  `X-RateLimit-Limit` / `X-RateLimit-Remaining` /
  `X-RateLimit-Reset` (and `Retry-After` on 429s). Pre-R57 the
  only signal a client got was a hard 429; with the headers exposed,
  SDKs / reverse proxies (HAProxy, Envoy, Traefik) / monitoring
  dashboards / fail2ban / mobile clients with adaptive backoff can
  proactively slow down before the bucket empties. `limiter.exempt`
  static-asset endpoints (every css/js/locale/font/icon/sound/lottie/
  manifest/favicon/SW) keep their behaviour: no headers leaked. 9
  dedicated tests in `tests/test_ratelimit_headers_r57.py`.

- **R58** — `_SSEBus.emit` now guards a 256 KB byte-size ceiling on
  the JSON-serialized payload. When exceeded, the original payload is
  **not** sent; a synthetic `oversize_drop` event is fan-out instead,
  carrying `original_event_type` / `size_bytes` / `limit_bytes`
  metadata. The drop still consumes one `_next_id` slot (so
  `Last-Event-ID` resume semantics aren't broken) and increments a
  new `oversize_drops` counter exposed via `stats_snapshot()` →
  `/api/system/sse-stats` → cross-process cache →
  `aiia://server/info`. Pre-R58, a single oversize payload (full
  stderr blob, entire task-table dump, misencoded binary, etc.)
  could fan-out N× memory across all subscribers; now it's bounded
  to a tiny metadata replacement. Threshold chosen to clear nginx
  default `proxy_buffer_size` (8 KB) by 32×, sit comfortably below
  Cloudflare's recommended SSE-message ceiling (~1 MB), and stay 100×
  above legitimate traffic (task_changed 1-2 KB, config_changed
  < 500 B, gap_warning < 200 B). 13 dedicated tests in
  `tests/test_sse_oversize_guard_r58.py`.

## [1.5.44] — 2026-05-08

> Round-56 round-up: a single client-side performance/consistency win
> on top of v1.5.43 — fixing a quiet docstring lie and a 24× over-fetch
> on i18n locale JSON.

### Changed

- **R56** — static-asset `Cache-Control` is now consistent across
  the `add_security_headers` after_request hook and the route-level
  handlers. Pre-R56, `serve_css` / `serve_js` set
  `max-age=3600` (1 h) at the route level, but the hook
  unconditionally rewrote it to `max-age=86400` (1 d) — the
  docstring claimed "1 hour" but production was actually "1 day", a
  silent drift. More impactful: `/static/locales/*` was **not**
  matched by any hook prefix, so the route-level 1 h was final, and
  `language='auto'` clients (where R20.12-B's inline optimization
  doesn't apply) refetched ~11 KB of locale JSON every hour — 24×
  more often than every other static asset. Hook now matches
  `/static/locales/` with the same v=hash / no-v split as js/css
  (1 year immutable / 1 day); route-level handlers updated to write
  the same value the hook will overwrite with (belt-and-suspenders
  fallback); docstrings rewritten to truthfully describe the policy;
  hook gains an inline cache-policy table for at-a-glance audit.
  Special-purpose endpoints (`manifest.webmanifest` 1 h,
  `favicon.ico` no-cache, notification SW no-cache) intentionally
  keep their route-level headers because the hook's path prefixes
  don't match them, and their semantic short-cache values are correct.
  16 dedicated tests in
  `tests/test_static_cache_headers_r56.py` verify hook coverage of
  all four prefix groups, special-path retention, ETag presence, and
  conditional-GET 304 Not Modified semantics — because
  `Cache-Control` only saves bytes-not-sent, ETag is what saves
  bytes-not-downloaded after the cache stales.

## [1.5.43] — 2026-05-08

> Round-55 round-up: a single observability win on top of v1.5.42 —
> closing a hard-won blind spot that meant "self-info" had been
> reporting only ~10 % of the platform's actual error stream.

### Added

- **R55** — `server.server_info_resource()` now returns a unified
  `recent_logs` block that aggregates `WARNING`/`ERROR` entries from
  **both** the MCP host process **and** the Web UI subprocess into a
  single timestamp-sorted list, each entry tagged with
  `source: "mcp"` or `source: "web_ui"`. The MCP process's ring buffer
  (R51-C) had always been wired in, but in practice the MCP host emits
  ~0–3 entries per day — almost all real failures (TaskQueue lock
  warnings, SSE bus back-pressure, AppleScript / Bark / config-watcher
  exceptions) live in the Web UI subprocess's separate ring. Pre-R55,
  the MCP-side `aiia://server/info` page was effectively blind to ~90 %
  of operational errors. Cross-process fetch goes through a new
  `server._fetch_recent_logs_cached(host, port, limit)` with the same
  1.0 s TTL / success-only / fresh-copy / cache-key-includes-limit
  shape pioneered in R54-A, so a tight self-info polling loop won't
  blow through the Web UI's 30 / min rate limit on
  `/api/system/recent-logs`. Tagged with new sub-fields
  `mcp_count` / `web_ui_count` / `web_ui_meta` (carries the underlying
  fetch error or `available: false` reason if applicable) for fine-grained
  observability without breaking the long-standing `count` /
  `entries` shape (R51-C tests still green). 13 dedicated tests cover
  cache hit/miss, TTL expiry, different-limit cache invalidation, all
  four HTTP failure paths, the merged sort order, web_ui-offline
  fallback, and isolated-copy semantics.

## [1.5.42] — 2026-05-08

> Round-54 round-up: an observability-and-safety follow-up to v1.5.41
> with two laser-focused fixes — one performance, one security.

### Added

- **R54-A** — `server._fetch_sse_stats_cached(host, port)` interposes
  a 1.0 s TTL cache between `server_info_resource` and the
  cross-process `httpx.get /api/system/sse-stats` round-trip. Without
  this, client UIs that poll `aiia://server/info` on a sub-second
  cadence (PWA status badge, VSCode webview tick) burned through the
  Web UI's 60 / min rate limiter on the sse-stats endpoint within a
  few hundred milliseconds. The cache is success-only (errors are
  never cached so transient failures don't pin the self-info page),
  uses fine-grained locking around the cache dict only (network
  call happens outside the lock), always returns fresh dict copies
  to prevent caller-side mutation, and tags hit responses with
  `cached: true` + `cache_age_s` for observability.

### Changed / Security

- **R54-B** — major `LogSanitizer` expansion. Closes a real silent
  leak: the legacy `\bsk-[A-Za-z0-9]{32,}\b` pattern's character
  class doesn't include `-`, so on `sk-proj-XXX` (OpenAI
  project-scoped) and `sk-ant-XXX` (Anthropic) it would only match
  `sk-proj` (4 chars) — far below the 32-char floor — and drop the
  match, leaking the entire key into stderr / the R51-C ring buffer.
  Added vendor-anchored coverage for OpenAI / Anthropic combined,
  GitHub all five token forms (`gh[psour]_`), Slack expanded
  (`xox[bpasr]-`), AWS Access Key ID, Google / Firebase / GCP, Stripe
  live & test, HuggingFace, JWT (anchored on `eyJ` to avoid
  blanket-redacting arbitrary three-segment dot strings), and URL
  basic-auth (back-reference rewrite that keeps scheme + username for
  forensic value but redacts only the password segment, producing
  `https://alice:***REDACTED***@host`). Deliberately not added: bare
  `Bearer <token>` headers, generic 16+ char hex, generic 32+ char
  base64 — all three would false-positive on legitimate logs (commit
  hashes, image data URIs, digest values).

## [1.5.41] — 2026-05-08

> Round-53 round-up: a small but pointed safety + observability cycle.
> `add_task` finally has a hard upper bound on prompt size (the original
> design had no guard at all, so a single buggy / hostile caller could
> push 100 MB into memory and through every SSE broadcast); and the
> existing telemetry primitives (sse-stats from R47, task_queue size,
> log ring buffer from R51-C / R52-B) are aggregated into one canonical
> `GET /api/system/health` endpoint shaped exactly the way K8s liveness
> / readiness probes and uptime monitors expect.

### Added

- **R53-A** — `task_queue.add_task` now enforces a layered prompt-size
  policy before acquiring the write lock:
  - Above `_PROMPT_WARN_BYTES` (6 MB UTF-8) — log a warning and accept,
    so operators can `grep` for misbehaving callers without blocking
    work;
  - Above `_PROMPT_REJECT_BYTES` (10 MB UTF-8) — return `False`
    immediately without entering the critical section, matching
    existing back-pressure return semantics. The check is done outside
    the watchdog-wrapped `_watched_write_lock` so oversized rejects
    can't starve legitimate tasks. Byte counting uses
    `len(prompt.encode("utf-8", errors="replace"))` so non-ASCII
    prompts are sized realistically.
- **R53-F** — `GET /api/system/health` aggregates SSE bus, TaskQueue,
  and recent-errors signals into a single `{status, ts_unix, checks}`
  payload with a three-state enum:
  - `unhealthy` (HTTP 503) — any sub-check raised internally; K8s
    readiness should depool;
  - `degraded` (HTTP 200) — all sub-checks ran but `backpressure_discards`
    or 5-min ERROR count > 0; alert without auto-restart;
  - `healthy` (HTTP 200) — all green.
    Rate-limited at 120 / min (vs sse-stats 60 / min, recent-logs 30 / min)
    to give two-replica K8s probe traffic 20× headroom. **No loopback
    gate** — probes always come from the cluster network. Endpoint is
    data-only (no `task.prompt`, no config values), safe to expose on
    the same address as the Web UI without a separate auth boundary.

## [1.5.40] — 2026-05-08

> Round-52 follow-up to v1.5.39: completes the watchdog rollout
> (R51-A had only wrapped one write path, R52-A wraps the remaining
> seven) and surfaces the R51-C log ring buffer as its own HTTP
> endpoint so PWAs, web status panels, and cross-process tooling
> don't have to go through MCP. 15 new test cases.

### Added

- **R52-B** — `GET /api/system/recent-logs` returns the most-recent
  WARNING/ERROR entries from the `enhanced_logging` ring buffer
  (entries already sanitized; passwords / `sk-` keys / `ghp_` tokens
  replaced by `***REDACTED***`). Rate-limited at 30 / min, no loopback
  gate (LAN PWAs can fetch — payload is sanitized). Accepts
  `?limit=N` query, default 50, clamped to ring capacity.

### Changed

- **R52-A** — Every `task_queue` write path now runs inside
  `_watched_write_lock(...)` with its own diagnostic label. R51-A
  introduced the wrapper but only applied it to `add_task`; R52-A
  finishes the migration for `clear_all_tasks`,
  `update_auto_resubmit_timeout_for_all`, `set_active_task`,
  `complete_task`, `remove_task`, `clear_completed_tasks`, and
  `cleanup_completed_tasks`. A new source-level invariant test
  enforces that any future write path must use the wrapper too.

## [1.5.39] — 2026-05-08

> Round-50 / Round-51-A / Round-51-B / Round-51-C: an observability +
> reliability follow-up to v1.5.38. Four independent, self-contained
> features that together turn `aiia://server/info` into a single
> drop-in self-diagnostic page (sse_bus counters, recent_logs, plus the
> existing R47 `interactive_feedback` / R44 `runtime` blocks), keep
> SSE keep-alive observable on both ends of the wire, and surface the
> first hint of a TaskQueue lock starvation incident before users
> notice. 64 new test cases total.

### Added

- **R50-A** — `server_info_resource` exposes a new `sse_bus` sub-block
  by polling `/api/system/sse-stats` cross-process with a 0.5 s timeout
  when the Web UI is up. MCP self-info now shows `emit_total` /
  `latest_event_id` / `gap_warnings_emitted` / `backpressure_discards`
  / `subscriber_count` / `history_size` alongside the R47
  `interactive_feedback` totals. Degrades to `{available: false,
reason}` when the Web UI is offline and to `{error}` for any HTTP /
  network failure — never raises, never starts the Web UI itself.
- **R51-A** — `task_queue.add_task` now runs inside a deadlock-aware
  `_watched_write_lock(...)` wrapper. A shared
  `TaskQueueLockWatchdog` daemon scans pending acquisitions every 5 s
  and dumps the full thread-stack snapshot to `logger.error` if a
  critical section is held longer than 30 s, with a per-record
  `dumped` flag preventing log spam. The `ReadWriteLock` itself is
  untouched so existing write paths keep working; future rounds can
  migrate them incrementally.
- **R51-B** — SSE generator's keep-alive frame is now a proper named
  event (`event: heartbeat\ndata: {"ts_unix": ...}`) instead of an
  invisible SSE comment. `_SSEBus` exposes a `_heartbeat_total`
  counter via `bump_heartbeat()` and `stats_snapshot()`, which
  propagates through `/api/system/sse-stats` and (via R50-A) into the
  `aiia://server/info` `sse_bus` block. Frontend (`multi_task.js`) and
  VS Code extension (`extension.ts`) both register a heartbeat
  listener that emits a debug-level log; existing clients that only
  listen for `task_changed` are 100 % backward compatible (SSE spec
  silently drops unhandled named events).
- **R51-C** — `enhanced_logging` gains a process-wide ring buffer
  (max 200 entries, 500-char cap per entry) of WARNING+ log lines.
  `EnhancedLogger.log()` records each line through `_record_to_ring`
  after handing the entry to the underlying logger, with sanitization
  (passwords / `sk-` keys / `ghp_` tokens redacted) and full
  try/except isolation. `server_info_resource` exposes the most recent
  twenty entries as a `recent_logs` sub-block so MCP client UIs and
  operators can see "what went wrong recently" without ssh-ing into
  the box to grep stderr.

### Changed

- **R50-B** — `_emit_config_changed_to_sse_bus` is now leading-edge
  debounced (250 ms) using `time.monotonic` + `threading.Lock`. Editor
  save bursts that trigger multiple mtime callbacks now produce a
  single SSE event, avoiding toast flicker on the PWA and status-bar
  churn in VS Code while keeping the first event instantaneous.

### Tooling / Smoke

- `scripts/smoke_test_r50.py` — manual end-to-end smoke that boots the
  Flask app on a random loopback port, fires five `_emit_*` calls in
  100 ms plus one more after the 250 ms window, and asserts exactly
  two `config_changed` frames are observed on `/api/events` plus an
  `emit_total` delta of 2 on `/api/system/sse-stats`.

## [1.5.38] — 2026-05-08

> Round-47 / Round-48 / Round-49: a hardening + observability follow-up
> to the v1.5.37 R43–R45 cycle. Three independent, self-contained
> improvements that each ship with a dedicated test file (45 new test
> cases total): runtime counters across the SSE bus and
> `interactive_feedback`, a live `config_changed` SSE broadcast for
> hot-reload feedback, and a tightened VSIX size budget.

### Added

- **R47** — Three new monotonic counter families let operators and
  client UIs answer "is the SSE bus dropping events?" / "is my LLM
  hammering the feedback tool?" without subscribing to the live SSE
  stream:
  - `_SSEBus._emit_total` / `_gap_warnings_emitted` /
    `_backpressure_discards`, exposed via `_SSEBus.stats_snapshot()`.
  - `server_feedback._FEEDBACK_COUNTERS`
    (`created_total` / `completed_total` / `failed_total`) wired into
    the existing `task.created` / `task.completed` / `task.failed × 3`
    log anchors. Public read API: `get_feedback_counters()`.
  - `aiia://server/info` resource now includes an
    `interactive_feedback` block (R47-isolated try/except, same pattern
    as R44 `runtime` / `fastmcp` / `middleware` / `task_queue`).
  - `GET /api/system/sse-stats` returns the SSE counter snapshot as
    JSON. Rate-limited to 60 req/min and intentionally **not**
    loopback-gated — LAN PWAs / VS Code status panels need it.
- **R48** — Server-side `ConfigManager` mtime-driven hot reload now
  broadcasts a `config_changed` SSE event so users see a real signal
  when their TOML edits land server-side, instead of the previous
  "I changed it but did anything happen?" silence:
  - `_emit_config_changed_to_sse_bus` callback (no leaked config
    values; only `{reason, hint}` payload).
  - `_ensure_config_changed_sse_callback_registered` follows the
    existing idempotent flag+lock pattern.
  - `static/js/multi_task.js` reuses the project-wide `_showToast`
    helper to surface the hint as a non-blocking 1.8 s toast.
  - `packages/vscode/extension.ts` calls
    `vscode.window.setStatusBarMessage` (6 s, non-blocking) — explicit
    choice over `showInformationMessage` to avoid modal interruption.

### Changed

- **R49** — Tightened the `WARN_PACKED_MB_DEFAULT` /
  `FAIL_PACKED_MB_DEFAULT` thresholds in
  `scripts/package_vscode_vsix.mjs` from `4 / 6` to `3 / 5` MB. Today's
  measured VSIX is **2.60 MB**, so the new review threshold (3 MB)
  still has ~15 % headroom while flagging the next ~400 KB regression
  for PR review. Hard limit (5 MB) now covers a ~2.4 MB catastrophic
  flap (e.g. mathjax getting double-bundled) before tripping
  `process.exit(1)`. Existing env-var escape hatches
  (`AIIA_VSCODE_VSIX_WARN_PACKED_MB` /
  `AIIA_VSCODE_VSIX_MAX_PACKED_MB`) and the `failMb < warnMb`
  runtime guard are unchanged.

## [1.5.37] — 2026-05-08

> Round-43 / Round-44 / Round-45: a three-pronged hardening cycle covering
> (1) config-path resolution (R43), (2) FastMCP 3.x best-practices middleware
> chain + ctx.info forwarding + enriched server self-info (R44), and (3) a
> docs/README/code consistency audit aligning every user-facing surface with
> the SSE Last-Event-ID, Bark-loopback-suppression, and middleware-stack
> reality introduced over R40–R44 (R45). The code is bumped to `v1.5.37`
> after this section is cut.

### Added

- **R44** — Production middleware "four-piece set" (`ErrorHandling` +
  `RateLimiting` + `Timing` + `Logging`): the long-missing `RateLimitingMiddleware`
  (`max_requests_per_second=10.0`, `burst_capacity=20`) is now inserted at
  position 1 of `mcp.middleware`, between `ErrorHandling` (outermost) and
  `DereferenceRefs` / `Timing` / `Logging`. The thresholds are deliberately
  loose for an interactive-blocking tool — they only fire when an LLM goes
  haywire and hammers `interactive_feedback` in a tight loop.
- **R44** — `interactive_feedback` now accepts a keyword-only `ctx:
FastMCPContext | None = None` parameter so FastMCP auto-injects the request
  context. The new `_emit_ctx_info` helper forwards three structured progress
  events to the MCP client (`task.created` / `task.notified` / `task.completed`),
  letting Cursor / Claude Desktop / ChatGPT Desktop render a live "waiting for
  human feedback" line in the chat sidebar instead of a silent block.
- **R44** — `aiia://server/info` self-info resource enriched with `runtime`
  (Python version + executable + platform), `fastmcp.version`,
  `middleware` chain (class names in execution order), and `task_queue` snapshot
  (initialized + size + pending). Each block has its own try/except so a
  partial-introspection failure never breaks the resource. The resource is
  side-effect-free — reading it never wakes the Web UI subprocess.
- **R43** — `AI_INTERVENTION_AGENT_DEV_MODE` and `AI_INTERVENTION_AGENT_USER_MODE`
  environment-variable overrides for the config-path resolution chain. Set
  `DEV_MODE=1` to force `./config.toml` even from outside the repo (useful in CI
  shells); set `USER_MODE=1` to make a process started inside the repo behave
  like a real install (useful for systemd services running from `/opt/aiia`).
- **R43** — `_is_isolated_install_runtime()` helper recognises modern installer
  layouts (`~/.local/share/uv/tools/`, `~/.local/share/pipx/venvs/`,
  `~/.cache/uv/builds-…`, plus any `site-packages` / `dist-packages` install)
  and honours user-set `UV_TOOL_DIR` / `UV_CACHE_DIR` / `PIPX_HOME` /
  `PIPX_LOCAL_VENVS` so custom tool layouts are also detected.

### Changed

- **R45** — README / docs/README / docs/mcp_tools / docs/troubleshooting
  rewritten to reflect SSE + HTTP dual-channel transport (was: "polling the
  Web UI API"), Bark loopback auto-suppression with LAN-IP suggestions (was:
  silent), and the production middleware chain. Mermaid architecture diagram
  now shows `extension.ts` (was: `.js`) and lists `tri-state-panel.js` in the
  Webview frontend tile.
- **R45** — `server.py` ToolAnnotations comment block updated from "MCP spec
  2024-11-05+" to "MCP spec 2025-11-25" matching `mcp.types.LATEST_PROTOCOL_VERSION`
  in the currently shipped `mcp 1.26.x`.
- **R43** — `find_config_file()` now uses a `_pick_existing()` helper that
  walks `config.toml` → `.jsonc` → `.json` per directory and emits a
  `WARNING` log line listing the ignored siblings whenever a directory has
  more than one format. Resolves the long-standing "I edited `config.jsonc`
  but it didn't take effect" surprise where a stale `config.toml` silently
  shadowed the edits.
- **R43** — `_is_uvx_mode()` rewritten as a deterministic 6-level priority
  chain (env override → DEV_MODE / USER_MODE flag → legacy `UVX_PROJECT` →
  isolated-install detection → repo-checkout heuristic guarded by `cwd`
  membership → safe `user`-mode default). The `cwd`-membership guard fixes
  the previous false positive where running an installed copy from inside
  any random repo checkout was misclassified as dev.

### Documentation

- **R45** — Added troubleshooting issue #8 ("Tapping a Bark notification on my
  phone opens Bark instead of the PWA") with a 3-step diagnostic flow
  (settings panel → API endpoint → `external_base_url` patch). The original
  CI-Gate troubleshooting entry slid to #9.
- **R43** — `docs/configuration.md` and `docs/configuration.zh-CN.md` now ship
  a 7-row priority table summarising the new env-override / isolated-install /
  repo-checkout decision tree, plus a "multi-format conflict" tip explaining
  the new warning log.

## [1.5.36] — 2026-05-06

### Changed

- Optimized the VS Code extension status bar polling path to avoid writing the
  same presentation twice when a `/api/tasks` response changes the visible
  state.
- Kept the VSIX packaging success summary free of `WARN`/`FAIL` threshold labels
  unless an actual budget condition is hit, so healthy local and CI logs remain
  easier to scan.

## [1.5.35] — 2026-05-06

### Fixed

- Guarded the Web UI multi-task SSE debug logger against browser-like
  environments where `console` is absent, avoiding a possible `ReferenceError`
  while keeping normal SSE connection churn silent unless `window.AIIA_DEBUG`
  is enabled.

## [1.5.34] — 2026-05-06

### Fixed

- Kept the published release in sync with the latest verified main branch by
  shipping the release workflow notice downgrade and Web UI SSE console-noise
  reduction after `v1.5.33`.

## [1.5.33] — 2026-05-06

### Fixed

- Restored the GitHub Releases page flow by cutting a fresh tag-based release
  after the earlier `workflow_dispatch` validation runs, which build artifacts
  but do not create GitHub Releases.
- Added release workflow noise hardening: optional VS Code Marketplace/Open VSX
  token skips now emit `notice` annotations instead of successful-run
  `warning` annotations.
- Gated Web UI multi-task SSE connection/reconnect status logs behind
  `window.AIIA_DEBUG`, reducing default browser-console noise on normal network
  churn.

## [1.5.32] — 2026-05-05

> Round-25 + early Round-26 (5 commits since v1.5.31 — R25.1 typecheck-tooling
> upgrade + R25.2 lazy-httpx + R26.1 lazy-flask*limiter + R26.2 template-context
> hot path + R26.3 lazy-markdown): a **typecheck-tooling refresh** plus a
> **second cold-start optimization wave** that systematically defers every
> remaining heavy module-top import in the `service_manager` / `server_feedback`
> / `web_ui` import chain to its actual use site, then tightens the most
> frequently-rendered hot path (`_get_template_context`, called once per browser
> page render and once per VS Code webview re-render). Combined wins:
> (a) **R25.1** bumps `ty` from v0.0.7 (the version frozen since v1.5.0's
> initial lock) to v0.0.34 (~6 months and 27 Astral releases later) and
> migrates 60+ `# type: ignore[...]` mypy-style suppressions to `# ty:
ignore[...]` ty-style across 28 files (1 production module + 5 production
> scripts/routes + 22 test files), eliminating the 3 pre-existing
> `possibly-missing-attribute` warnings via real type narrowing rather than
> suppression and keeping the entire repo on green ty diagnostics with the
> latest stable directive syntax — the trigger is that ty's old `# type:
ignore[code]` syntax is going to be removed in a future major bump, and
> doing it now under controlled conditions with full test coverage is far
> safer than under release pressure later. (b) **R25.2** defers the
> module-top `import httpx` in `service_manager.py` and `server_feedback.py`
> to in-function imports at every actual use site (`get_async_client` /
> `get_sync_client` / `health_check_service` / `update_web_content` for
> service_manager; `_sse_listener` / `launch_feedback_ui` /
> `interactive_feedback` for server_feedback), gated behind `if
TYPE_CHECKING: import httpx` for the module-level type annotations,
> dropping `import service_manager` cold-start from ~149 ms to ~69 ms
> (-79 ms / -53%); pair the httpx surgery with a tri-state lazy load of
> the optional notification subsystem because the eager
> `from notification_manager import notification_manager` was the secondary
> cold-start tax (constructs a 4-thread `ThreadPoolExecutor` + reads
> on-disk config + transitively pulls notification_providers' own httpx
> import — undoing all the above httpx surgery on Bark-enabled configs);
> the `_ensure_notification_system_loaded()` 3-state lazy initializer
> (uninitialized → loaded-OK → load-failed) caches the singleton on first
> call and short-circuits at <10 µs per cache-hit thereafter. (c) **R26.1**
> defers the module-top `from flask_limiter import Limiter` /
> `from flask_limiter.util import get_remote_address` in `web_ui.py` to
> in-function imports inside `WebFeedbackUI.__init__`'s `Limiter(...)`
> construction site, saving ~15-21 ms of incremental cold-start cost on
> the frequent "import a small utility from web_ui" path used by 100+
> test sites that don't construct the full `WebUIApp`. (d) **R26.2**
> tightens the `_get_template_context` hot path on every render by
> hoisting `_RTL_LANG_PREFIXES` from a 12-element function-local tuple
> allocated per call to a module-level `frozenset[str]` (O(1) member
> lookup vs the previous up-to-12 `startswith` calls), extracting
> `_compute_file_version(file_path_str)` as a module-level
> `@lru_cache(maxsize=64)` free function (4 fresh `Path.stat().st_mtime`
> syscalls per render → 0 syscalls after first render), and pre-computing
> `static_dir` once at `__init__` time (`self._static_dir`) instead of
> `Path(__file__).resolve().parent / "static"` per call, dropping
> `_get_template_context` from ~70 µs/call to ~41 µs/call (-41%),
> compounding under the empirically-observed ~50-200 calls/min steady-state
> browser polling rate for ~1.5-6 ms/min CPU saving per `web_ui`
> subprocess. (e) **R26.3** defers the module-top `import markdown` in
> `web_ui.py` and the eager `markdown.Markdown(extensions=[...10
plugins...])` instance construction inside `setup_markdown` to a single
> coordinated lazy-init point inside `render_markdown(text)`'s critical
> section (under the existing `self._md_lock`), removing ~20-25 ms of
> wall-clock cost from the cold-start path that was paid for plugin
> warm-up (codehilite Pygments lexer + footnote AST + nl2br rewrite +
> md_in_html sanitizer + table/toc/fenced_code/attr_list/def_list/abbr
> regex compilation), with race-prevention via double-checked locking
> (the \_first* thread to grab the lock pays the import + construct cost;
> subsequent threads see `self.md is not None` and skip), verified via a
> 100-thread `threading.Barrier`-synchronized test that asserts exactly
> 1 `Markdown(...)` constructor call across the contention window.
> Cumulative cold-start improvements from v1.5.31 → v1.5.32:
> `service_manager` cold-start dropped ~80 ms (~149 ms → ~69 ms),
> `web_ui` cold-start dropped ~9 ms (~111 ms → ~102 ms),
> `WebFeedbackUI()` constructor dropped ~20 ms (~145 ms → ~125 ms),
> compounding to a ~30-100 ms reduction in the user-perceived "AI agent
> calls `interactive_feedback` → browser sees `/`" latency depending on
> which path dominates in a given session. The R23.x → R26.3 cumulative
> series totals ~150 ms saved on the cold-start critical path since
> v1.5.29, all behind 60+ new tests across 5 dedicated suites
> (`tests/test_lazy_httpx_r25_2.py` 15 tests +
> `tests/test_lazy_flask_limiter_r26_1.py` 5 tests +
> `tests/test_template_context_hot_path_r26_2.py` 12 tests +
> `tests/test_lazy_markdown_r26_3.py` 11 tests + R25.1 typecheck-cleanup
> behavior tests). All ci_gate stages green at `3099 passed, 1 skipped`
> with zero ruff / ty / pytest warnings, locale-parity / minify /
> red-team-i18n / vscode source-contract / BP byte-parity all clean.

### Tooling

- **R25.1 — `ty` v0.0.7 → v0.0.34 + 60+ ignore-syntax migration**
  (28 files: `enhanced_logging.py`, 5 production scripts/routes,
  22 test files, plus `uv.lock`). Bump triggers an expected ~60 new
  diagnostics that ty v0.0.34's improved TypedDict narrowing /
  tomlkit type tracking / Any-propagation surfaces as known-good
  test patterns (intentionally invalid-type validator probes,
  partial mocks overwriting locked attributes, `tomlkit.Item` subscript
  chains that v0.0.7's typeshed snapshot was widening too aggressively);
  fixes are one-by-one source-text adjustments preserving byte-for-byte
  runtime behavior. Production fixes: 6 ignore-syntax migrations + 1
  defensive null-check refactor in `scripts/bump_version.py:155-156`
  (where `re.match(r"^(\s*)", line).group(1)` was correctly flagged by
  ty even though the `\s*` regex always matches — the explicit
  `indent_match.group(1) if indent_match else ""` form is genuinely
  defensive code at zero runtime cost) + 1 type widening in
  `web_ui_routes/task.py:96` (`result: dict[str, Any]` accommodating
  the route's mixed string / list / dict response shape). Test fixes:
  60+ ignore migrations spanning `not-subscriptable` (×14),
  `invalid-argument-type` (×8), `invalid-assignment` (×9),
  `too-many-positional-arguments` (×4), `unresolved-attribute` (×2),
  `invalid-context-manager` (×1), `invalid-return-type` (×1, in
  `tests/test_tool_annotations.py`'s structural-vs-nominal type
  reconciliation between `fastmcp.tools.base.Tool` and
  `mcp.types.Tool` which inherit but ty enforces nominal), and
  `unresolved-import` (×3, on the Python <3.11 `tomli` fallback that
  is dead code in our ≥3.11-pinned env). Verification:
  `uv run ty check .` post-migration → `All checks passed!` (was
  `Found 60 diagnostics` immediately after the lock bump pre-migration);
  `uv run python scripts/ci_gate.py` → `2958 passed, 1 skipped` (no
  test removed or skipped, baseline preserved). Out of scope: no other
  dependency upgrades — the `uv.lock` diff is exactly one package /
  one version line / corresponding sdist+wheel URL set.

### Performance

- **R25.2 — Lazy `httpx` + lazy notification system**
  (`service_manager.py`, `server_feedback.py`, plus 15-test
  `tests/test_lazy_httpx_r25_2.py` source-text + runtime invariant
  suite). Eliminates ~55 ms `httpx` cold-import + ~24 ms eager
  `NotificationManager` singleton construction (4-thread executor
  - on-disk config parse + Bark provider's transitive httpx pull) from
    the `service_manager` module-load path; `import service_manager` cold-
    start drops from ~149 ms to ~69 ms (-79 ms / -53%). The 3-state
    `_ensure_notification_system_loaded()` lazy-init function caches
    `(_notification_manager_singleton, _initialize_notification_system_fn)`
    on first call (returns cached refs <10 µs/call thereafter, verified
    via 1000-iteration micro-benchmark), with `cleanup_all` gated on
    `_notification_initialized AND _notification_manager_singleton is not None`
    so cold-shutdown paths that never triggered the lazy load don't
    reverse-trigger it just to call `shutdown()`. `start_web_service`
    is the single intentional lazy-load trigger in production (after
    it runs the notification system stays loaded for the rest of the
    process lifetime, so subsequent `cleanup_all` calls do find the
    singleton to shut down).

- **R26.1 — Lazy `flask_limiter` import**
  (`web_ui.py`, plus 5-test `tests/test_lazy_flask_limiter_r26_1.py`
  source-text + runtime + behavior contract suite). Defers the
  module-top `from flask_limiter import Limiter` /
  `from flask_limiter.util import get_remote_address` to in-function
  imports placed inside `WebFeedbackUI.__init__` immediately preceding
  the `self.limiter = Limiter(key_func=get_remote_address, app=self.app,
default_limits=["60 per minute", "10 per second"], storage_uri="memory://",
strategy="fixed-window")` construction call — `flask_limiter`'s
  ~21 ms incremental cold-start cost (after flask is already loaded,
  flask_limiter shares most of its dependency tree so the new cost
  is much less than its ~65 ms isolated cost) is now paid only by
  the WebFeedbackUI-instantiation path (real Flask subprocess startup,
  integration tests, perf benchmarks) rather than by the much-more-
  frequent "import a small utility from web_ui" path used by 100+
  test sites that only need `validate_auto_resubmit_timeout` /
  `MDNS_DEFAULT_HOSTNAME` / `_is_probably_virtual_interface` /
  `_read_inline_locale_json` / etc. Pattern matches R23.3 lazy
  flasgger and R25.2 lazy httpx / notification.

- **R26.2 — `_get_template_context` hot path tightening**
  (`web_ui.py`, plus 12-test `tests/test_template_context_hot_path_r26_2.py`
  module-level constants + source-text + html_dir behavior +
  backward-compat suite). Three independent micro-bottlenecks pulled
  out of the per-render path: (1) `_RTL_LANG_PREFIXES` migrated from
  a 12-element function-local tuple allocated on every invocation
  to a module-level `frozenset[str]` (12 BCP-47 RTL primary subtags
  per W3C language-direction guidance), with `frozenset` chosen over
  `set` for the immutable-shared-data invariant + thread-safe sharing
  - fixed hash table at construction time — the lookup pattern
    simultaneously upgrades from `any(html_lang.lower().startswith(p +
"-") or html_lang.lower() == p for p in _RTL_LANG_PREFIXES)` (12
    fresh string concat allocations + 12 startswith calls per call)
    to `primary_subtag = html_lang.lower().partition("-")[0]; html_dir
= "rtl" if primary_subtag in _RTL_LANG_PREFIXES else "ltr"` (one
    partition + one frozenset lookup, ~12× faster on the membership
    test step); (2) `_compute_file_version(file_path_str: str) -> str`
    extracted as a module-level `@lru_cache(maxsize=64)` free function
    replacing the previous `WebFeedbackUI._get_file_version(self, path)`
    instance method that ran one fresh `Path(file_path).stat().st_mtime`
    syscall per call per file — with 4 calls per render this was 4
    fresh stat() syscalls per render, each costing ~0.5-2 µs warm and
    ~5-15 µs cold; post-fix the cache hit rate is 100% after the first
    render so subsequent calls drop to ~50-200 ns of `lru_cache` dict-
    probe overhead vs the previous ~2-8 µs of stat() per call; (3)
    `static_dir` pre-computed once at `WebFeedbackUI.__init__` time as
    `self._static_dir: Path = self._project_root / "static"` instead of
    `Path(__file__).resolve().parent / "static"` per render, with a
    module-level `_get_module_static_dir()` `@lru_cache(maxsize=1)`
    fallback for unit tests that bypass `__init__` via
    `object.__new__(WebFeedbackUI)`. Net: `_get_template_context` drops
    from ~70 µs/call (range 64-78 µs across 5 runs) to ~41 µs/call
    (range 38-46 µs), -41% / -29 µs per call; at the empirically-
    observed ~50-200 calls/min steady-state browser polling rate this
    saves ~1.5-6 ms/min CPU per `web_ui` subprocess.

- **R26.3 — Lazy `markdown` + lazy `markdown.Markdown(...)` instance**
  (`web_ui.py`, plus 11-test `tests/test_lazy_markdown_r26_3.py` 4-section
  source + runtime + thread-safety + backward-compat suite). Defers the
  module-top `import markdown` (~8.9 ms cold-cache module load) AND
  the eager `markdown.Markdown(extensions=[...10 plugins...])` instance
  construction inside `setup_markdown` (~10-15 ms one-time plugin warm-
  up: codehilite Pygments lexer + footnote AST regex + nl2br rewrite +
  md_in_html sanitizer + table/toc/fenced_code/attr_list/def_list/abbr
  regex compilation) to a single coordinated lazy-init point inside
  `render_markdown(text)`'s critical section, paying the combined
  ~20-25 ms cost at first-render-needed time instead of cold-start time.
  The lazy-init uses double-checked locking via the existing
  `self._md_lock` (`threading.Lock` instance that was already protecting
  `self.md.reset() + self.md.convert()` against concurrent rendering
  because python-markdown's `Markdown` class is not thread-safe).
  `_MD_EXTENSIONS` and `_MD_EXTENSION_CONFIGS` extracted to module-level
  constants for stable test anchoring; the `noclasses=True` codehilite
  setting is preserved in the constants because the project's R23.5-
  hardened CSP header doesn't permit external Pygments stylesheets and
  Pygments must emit `style="..."` inline attributes. Race protection
  verified via 100-thread `threading.Barrier(parties=100)`-synchronized
  test that monkey-patches `markdown.Markdown` with a counting wrapper
  and asserts the constructor is called exactly once across all 100
  workers (not 1+race-leftover). User-perceived: pre-fix `python -X
importtime -c "import web_ui"` showed `markdown` at position #5 with
  ~8.9 ms self-time; post-fix `markdown` is absent from the top-30
  imports. `WebFeedbackUI()` constructor cold drops from ~145 ms to
  ~125 ms (5 cold runs averaged).

## [1.5.31] — 2026-05-05

> Round-24 kickoff (1 commit since v1.5.30 — R24.1): a single but
> high-impact **VS Code webview cold-open** optimization that
> parallelizes the 4 disk reads `WebviewProvider._preloadResources`
> performs on the _only_ synchronous-blocking step of the webview's
> first-frame critical path. Pre-fix, `_preloadResources` was a
> textbook serial-await pattern (`for (const loc of ["en", "zh-CN"])`
> for the locale JSON files, then `await readFile(activity-icon.svg)`,
> then `await readFile(lottie/sprout.json)`) inherited from earlier
> single-locale, no-lottie versions where each read got appended to
> the function body without ever revisiting the dispatch shape; at
> v1.5.30 we'd accumulated 4 fully-independent disk reads pretending
> to depend on each other through shared `await` semicolons. **R24.1**
> collapses them into `await Promise.all([loadLocale("en"),
loadLocale("zh-CN"), loadStaticAssets()])` with a nested
> `Promise.all([svgPromise, lottiePromise])` inside `loadStaticAssets`,
> taking the wall-clock from ~52 ms (range 47-58 ms, σ=4.1) down to
> ~16 ms (range 14-19 ms, σ=2.3) — net **-35 ms** off the user-perceived
> "click activity-bar icon → see first frame" latency on every cold
> open / window reload, with zero behavior change on the warm-open path
> (where the `_cachedLocales[loc]` / `_cachedStaticAssets` cache
> short-circuits already make all 4 branches return immediately).
> The change is locked behind 13 new source-text-contract tests
> (`tests/test_vscode_perf_r24_1.py`) covering serial-loop removal,
> outer/inner Promise.all dispatch shape, fallback-chain preservation
> (`safeReadTextFile` for workspace-trust-restricted environments),
> cache-hit short-circuit preservation, atomic-write invariant
> (`Promise.all` resolves before `_cachedStaticAssets` is assigned),
> and call-site invariants (`resolveWebviewView` still `await`s
> `_preloadResources`). Why ship this as a single-commit release
> instead of accumulating: the saved 35 ms is the largest user-perceived
> latency reduction in any single VS Code-side commit since R20.13,
> directly translates to "the side panel snaps open faster", and the
> R24.x branch's remaining candidates (`_getHtmlContent` URI cache,
> `tl()` HTML-template batching, non-darwin `MacOSNativeNotificationProvider`
> dead-code skip) are all µs-scale optimizations whose accumulated wins
> would still not approach R24.1's individual win — so attaching them
> would only delay the user-visible benefit without meaningful additional
> impact.

### Performance

- **R24.1 — `WebviewProvider._preloadResources` 4 disk reads
  parallelized via `Promise.all`** (`packages/vscode/webview.ts`).
  The function is on the critical path of `resolveWebviewView`
  (line 431, `await this._preloadResources()`) which gates the
  webview's first-frame paint, so any wall-clock saved here is paid
  back 1:1 in user-perceived "click activity-bar icon → see UI"
  latency. The pre-fix inline comment at line 426 already quantified
  the cost as "首次 ~50ms"; measurement on this dev box (macOS 25.4.0
  / Apple Silicon M1 / VS Code 1.105 stable) confirms 52.4 ms pre-fix
  median (5 cold opens, range 47.1-58.3 ms, σ=4.1) vs 16.2 ms post-fix
  median (range 13.8-19.5 ms, σ=2.3) — 36 ms saved, 69 % wall-clock
  reduction. The 16 ms post-fix floor is the unavoidable IPC RTT for
  `vscode.workspace.fs.readFile`'s renderer↔extension-host
  postMessage bridge plus the slowest of the 4 reads (the ~12 KB
  `lottie/sprout.json`); the pre-fix latency was the _sum_ of those
  4 RTTs. The 4 reads are fully independent (proven by
  `rg "_cachedLocales|_cachedStaticAssets" packages/vscode/webview.ts`
  returning the read sites, none of which trigger before
  `_preloadResources` resolves), so `Promise.all` is provably safe.
  Implementation extracts two arrow-function helpers (`loadLocale(loc)`
  and `loadStaticAssets()`) inside `_preloadResources`'s body, each
  preserving its cache short-circuit + main-path
  `vscode.workspace.fs.readFile` + `safeReadTextFile` workspace-trust
  fallback, then dispatches all three via `await Promise.all([...])`;
  `loadStaticAssets` itself uses a nested `Promise.all([svgPromise,
lottiePromise])` to parallelize SVG and lottie reads at a second
  layer, then writes back `this._cachedStaticAssets = {
activityIconSvg, lottieData }` _atomically_ after both promises
  resolve (preventing partial-write states where another path could
  observe `_cachedStaticAssets.activityIconSvg !== undefined &&
_cachedStaticAssets.lottieData === undefined`, which would silently
  break the lottie sprout animation in the empty-state placeholder).
  Tests: 13 new source-text-contract tests in
  `tests/test_vscode_perf_r24_1.py` (covering serial-loop removal,
  outer/inner `Promise.all` shape with named promises for
  documentation value, fallback-chain preservation, cache-hit
  short-circuit, atomic-write ordering, single-definition guard,
  and `resolveWebviewView` still-awaiting); existing
  `tests/test_vscode_perf_r20_13.py` (20 R20.13-A through R20.13-F
  invariants on the same file) and `tests/test_vscode_webview_dispose_race.py`
  (5 R18.2 dispose-race-guard invariants in
  `resolveWebviewView`'s `_preloadResources()` `finally` block) all
  continue to pass. `ci_gate` reports `3056 passed, 1 skipped` with
  zero ruff / ty / pytest warnings; `npx tsc -p packages/vscode/`
  reports zero TypeScript errors. `Promise.all` is the right primitive
  (not `Promise.allSettled`) because both helpers internally
  swallow-and-fallback via `safeReadTextFile`, so neither branch can
  reject in practice — `Promise.all`'s short-circuit semantics are
  unreachable, and `Promise.allSettled` would slow the success path
  with `{status, value}` wrapper allocations we don't need.

## [1.5.30] — 2026-05-05

> Round-23 (5 commits since v1.5.29 — R23.1 + R23.2 + R23.3 + R23.4 + R23.5):
> a tightly-themed **cold-start + hot-path performance pass** that strips
> ~80 ms of redundant work off the `web_ui` subprocess critical path
> (the latency between "AI agent calls `interactive_feedback` MCP tool"
> and "browser can actually open `/`") and tightens the steady-state
> hot path on `/api/tasks` GET, `Content-Security-Policy` header build,
> and `_sse_listener` reconnect cadence — all without changing any
> user-facing behavior, all behind ≥85 new tests (12 + 11 + 27 + 18 + 29) that lock the contracts via source-text invariants, runtime
> spy verification, atomic-snapshot concurrency assertions, and
> integration-level regression coverage. Combined wins:
> (a) **R23.1** switches `server_feedback._sse_listener` from a
> per-call freshly-constructed `httpx.AsyncClient()` to the
> process-level pooled client managed by
> `service_manager.get_async_client(cfg)` — same singleton used by
> `_fetch_result` since R10 — eliminating one full
> `AsyncClient.__init__` (1.4 ms) plus its paired `__aexit__` (0.6 ms)
> per `interactive_feedback` MCP call, and unifying SSE + poll-fallback
> into a single connection pool so the long-lived `/api/events` stream
> and the short `/api/tasks/<id>` polls can keep-alive-share the same
> underlying TCP socket. (b) **R23.2** lazy-imports `psutil` from
> `web_ui_mdns_utils.py` module-top into the `try:` block of
> `_list_non_loopback_ipv4`, eliminating ~5 ms (range 3-8 ms) of
> psutil's C-extension family load per `web_ui` cold start regardless
> of whether mDNS is enabled — fully-loopback workloads (the
> `host=127.0.0.1` default) never pay the cost at all because
> `_list_non_loopback_ipv4` is only invoked from `detect_best_publish_ipv4`
> on non-loopback bind. (c) **R23.3** converts `flasgger.Swagger` from
> a hard module-top dependency to an env-gated opt-in
> (`AI_AGENT_ENABLE_SWAGGER=1` to enable), eliminating the **~75 ms**
> `from flasgger import Swagger` cost from every `web_ui` subprocess
> cold start by default — the largest single win in this round, larger
> than the entire R20.x roadmap's accumulated cold-start savings;
> when disabled, `/apidocs/` returns a 1.4 KB inline-HTML fallback
> page documenting how to flip the env var, so the UX failure mode is
> "informative explanation" not "404". (d) **R23.4** collapses the two
> back-to-back `read_lock` acquisitions on `/api/tasks` GET
> (`get_all_tasks()` + `get_task_count()`) into a single new method
> `TaskQueue.get_all_tasks_with_stats()` holding the `ReadWriteLock`
> reader-side exactly once, eliminating one full reader-acquire/release
> cycle per request (~400-900 ns) plus a redundant O(N) list iteration,
> and tightening the snapshot atomicity from "list then re-acquire then
> count" (which let writers slip in and produce 1-step skews like
> `len(tasks) == N` vs `stats["total"] == N+1`) to a single critical-
> section snapshot where `len(tasks) == stats["total"]` is invariant.
> (e) **R23.5** hoists the immutable parts of the per-response
> `Content-Security-Policy` header out of the hot-path `after_request`
> closure into class-level `SecurityMixin._CSP_PREFIX` /
> `_CSP_SUFFIX` constants plus a tiny `_build_csp_header(nonce)`
> classmethod, so every Flask response now performs a 3-segment string
> concat instead of the previous 10-segment f-string assembly, saving
> ~390 ns per response (a 67% saving on this micro path) which
> compounds to ~20-80 µs/s of CPU savings on a `web_ui` process serving
> 50-200 req/s during active multi-task agent runs.

### Performance

- **R23.1 — `server_feedback._sse_listener` switched to pooled
  `httpx.AsyncClient`**. Pre-fix the SSE listener was the only place
  in the entire `server_feedback` module that still constructed a
  brand-new `httpx.AsyncClient` per call (verified by
  `rg "httpx.AsyncClient\(" server_feedback.py` returning 1 hit on
  the pre-fix tree, while `rg "service_manager.get_async_client"`
  returned 4 hits in the same file — the post-task `interactive_feedback`
  task-creation, `_fetch_result`'s polling, `_close_orphan_task_best_effort`,
  and the heartbeat all already used the singleton). The pre-fix
  per-call cost decomposition (measured with 200 `httpx.AsyncClient()`
  - immediate `__aexit__` constructs against `loopback:8088`):
    full `AsyncClient.__init__` averages 1.4 ms (range 0.9-3.1 ms) for
    fresh `AsyncHTTPTransport` + internal `httpcore.AsyncConnectionPool`
  - asyncio cookie-jar lock + `_event_hooks` dict; the paired
    `__aexit__` averages 0.6 ms (range 0.3-1.2 ms) for keep-alive socket
    teardown + pool drain + waiter wake. Net per-call savings on the
    `interactive_feedback` cold path: ~2.0 ms wall-time off
    `wait_for_task_completion` startup; on a typical 20-step agent run
    that's ~40 ms of pure overhead removed. Bigger structural win: SSE
  - poll-fallback now share one connection pool, so the long-lived
    `/api/events` stream and `_fetch_result`'s short polls can
    keep-alive-share the same TCP socket when both are quiet, and
    process-shutdown teardown only has one client to close instead of
    an opportunistic `__aexit__` race during MCP cancel. Critical
    detail: the `stream(...)` call gets an explicit
    `timeout=httpx.Timeout(None, connect=5.0)` override scoped to the
    SSE invocation alone (without leaking back into the shared pool's
    other consumers), because the singleton's default
    `httpx.Timeout(config.timeout, connect=5.0)` would otherwise kill
    the long-lived SSE stream at the first idle window after
    `config.timeout` seconds. 12 tests in
    `tests/test_sse_listener_pooled_client_r23_1.py` lock the new
    contract: source invariants (must call
    `service_manager.get_async_client`, must not call
    `httpx.AsyncClient(...)`, must pass `httpx.Timeout(None, ...)` to
    `stream(...)`, must not wrap the shared client in `async with`),
    docstring contract, runtime spy verification (using
    `patch.object(httpx.AsyncClient, "__init__")` to confirm zero
    direct constructions during the listener's lifetime), and R22.1
    regression. Co-evolved fixtures: every `_mock_async_client` helper
    in `test_server_feedback_poll_cadence_r22_1.py` and
    `test_server_functions.py` had to set
    `client.stream = MagicMock(side_effect=RuntimeError("SSE blocked in test"))`
    so the listener takes its existing `except Exception` branch
    (preserving the "poll fallback is the path under test" semantics);
    pre-fix those tests deliberately relied on
    `tests/conftest.py::_disable_real_network_requests` to block the
    SSE listener's previously-direct `httpx.AsyncClient()` call, but
    post-fix the listener goes through the _mocked_ singleton and would
    otherwise hit `aiter_lines()`'s `AsyncMock` without awaiting and
    emit 14 `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call'
was never awaited` from pytest's unraisable-exception hook. Commit
    `2617507`.

- **R23.2 — `psutil` lazy-imported in `web_ui_mdns_utils.py`**.
  Pre-fix `import psutil` at line 13 of the module was a ~5 ms
  (range 3-8 ms, median 5.2 ms) synchronous cost on every Python
  process that imported `web_ui_mdns_utils` regardless of whether
  mDNS was actually used (the module is in `web_ui.py`'s import
  closure, which is in `mcp_server.py`'s spawn-subprocess command-
  line for the `web_ui.py` child); the cost decomposes into
  `psutil._psosx` ~1.5 ms + `psutil._common` ~1 ms + sub-module
  wires ~0.5 ms + per-platform `libproc` / `/proc` initialization
  on macOS / Linux. Post-fix `import psutil` lives one indent level
  deeper, inside the existing `try:` block at the top of
  `_list_non_loopback_ipv4`, which means: (a) fully-loopback workloads
  (the dev-box default `host=127.0.0.1`) never pay the 5 ms because
  `_list_non_loopback_ipv4` is only called from
  `detect_best_publish_ipv4(bind_interface)` and that's only invoked
  when `bind_interface != "127.0.0.1"`; (b) LAN-bind workloads load
  psutil exactly once during `_mdns_register_thread`'s first probe,
  _off_ the main thread, so even there the main thread's `app.run()`
  listen-socket bind happens before psutil's C-ext init has finished;
  (c) `sys.modules` cache means the second-and-after
  `_list_non_loopback_ipv4` call is zero-cost. Failure-mode preservation:
  the pre-existing `except Exception` was already wrapping the
  `psutil.net_if_addrs()` call to handle "psutil errored at runtime";
  R23.2 expands the `try` boundary by exactly two lines so an
  unbelievable-but-possible "psutil-not-installed" `ImportError` route
  also returns `[]`, which `detect_best_publish_ipv4` already maps to
  "mDNS publish gracefully disabled". 11 tests in
  `tests/test_lazy_psutil_r23_2.py` lock the new contract: source
  contract (no top-level `import psutil`, lazy import lives inside
  `_list_non_loopback_ipv4`'s `try:` block, function docstring
  documents the lazy-import contract), docstring contract, runtime
  contract (`psutil not in sys.modules` after `import web_ui_mdns_utils`
  in subprocess-isolated check, `psutil in sys.modules` after
  `_list_non_loopback_ipv4()` is invoked, second invocation is a
  no-op), `psutil` unavailable fallback (patching `__import__` to
  raise `ImportError` returns `[]` cleanly; patching
  `psutil.net_if_addrs` to raise `OSError` also returns `[]`), and
  mDNS path regression. Co-evolved fixtures: `tests/test_web_ui_config.py`
  had 17 mocks against `web_ui_mdns_utils.psutil.net_if_addrs` /
  `web_ui_mdns_utils.psutil.net_if_stats` (path-based
  `unittest.mock.patch` style) which `AttributeError`-fail post-fix
  because `web_ui_mdns_utils.psutil` no longer exists as a module
  attribute; every patch now targets `psutil.net_if_addrs` /
  `psutil.net_if_stats` directly so the mock goes into
  `sys.modules['psutil']` and is correctly seen by the lazy-imported
  reference. Commit `55d4b1e`.

- **R23.3 — `flasgger.Swagger` converted from hard dependency to
  env-gated opt-in**. The largest cold-start win in this round:
  `from flasgger import Swagger` was a 75 ms (median 75.4 ms, range
  74-78 ms) synchronous module-load cost paid on every
  `web_ui.py` subprocess cold start, pulling in `flasgger.base` +
  `jsonschema` validator graph + `mistune` markdown renderer +
  `yaml.SafeLoader` + ~30 transitive deps; this 75 ms literally
  extended the latency between "AI agent calls `interactive_feedback`
  MCP tool" and "browser can actually open `/`" because
  `service_manager.spawn_subprocess`'s ready-probe waits for the
  listen-socket bind, which happens _after_ module-top imports.
  Post-fix `__init__` checks `_is_swagger_enabled_via_env()` reading
  `os.environ.get("AI_AGENT_ENABLE_SWAGGER", "").strip().lower() in
{"1", "true", "yes", "on"}`; truthy → call `_init_swagger_lazy()`
  which `from flasgger import Swagger` (lazy) + `Swagger(self.app,
template={...})`s the existing template; falsy (default) → call
  `_register_swagger_disabled_fallback()` which adds two `/apidocs`
  - `/apidocs/` URL rules pointing at a 1.4 KB inline-HTML view that
    documents the env-var to flip + links to the project README's
    `#api-docs` anchor. Three alternatives were considered and rejected:
    (a) "lazy init via `before_request` hook on first `/apidocs/` GET"
    is unimplementable on Flask 3.x (`AssertionError: The setup method
'register_blueprint' can no longer be called on the application`);
    (b) "daemon thread async init parallel with `app.run()` socket
    bind" wins only ~50 ms instead of 75 (GIL-shared subprocess steals
    CPU from main thread's listen bind during first ~10 ms of `app.run()`)
    and adds ~50 LOC of lock-and-wait surface; (c) "move
    `from flasgger import Swagger` to inside `__init__` only" saves zero
    wall-clock on actual cold start because each subprocess constructs
    exactly one `WebFeedbackUI`. The 12-factor rationale for env var
    over `config.json` field: environment is the earliest readable
    source (before config-manager schema validation), and "is this a
    dev box" doesn't belong in user's persisted config. Benchmark
    before/after on this dev box: pre-fix `import web_ui` = 195 ms
    cold; post-fix unset = 120 ms (-75 ms exactly matching the flasgger
    cost); post-fix `=1` = 121 ms `import web_ui` + 30 ms
    `WebFeedbackUI()` construct = 151 ms total to a Swagger-enabled UI
    (still 44 ms faster than pre-fix because module-init noise is now
    serialized in fewer phases). 27 tests in
    `tests/test_lazy_swagger_optin_r23_3.py` lock the new contract:
    env truthy parsing (10 tests covering `unset` / `""` / `"0"` /
    `"false"` / `"FALSE"` / `"enabled"` / `"y"` all-disable plus
    `"1"` / `"true"` / `"TRUE"` / `"yes"` / `"YES"` / `"on"` / `"ON"`
    / `"  1  "` / `"\t true \n"` all-enable, locking case-insensitive
    whitespace-strip), default disabled path (no flasgger in
    `sys.modules`, fallback endpoints registered), fallback HTML body
    (200, `text/html; charset=utf-8`, contains `AI_AGENT_ENABLE_SWAGGER`
  - GitHub URL, < 2 KB, both `/apidocs` and `/apidocs/` direct-200
    without 308 redirect), enabled path (flasgger in `sys.modules`,
    `flasgger.apidocs` + `flasgger.apispec_1` endpoints registered,
    `/apispec_1.json` returns `application/json`), source contract
    (no module-top `from flasgger`, lazy import inside method body),
    docstring contract (mentions `R23.3` + `AI_AGENT_ENABLE_SWAGGER` +
    the literal `75 ms` as an anti-drive-by-revert guardrail). Commit
    `4817048`.

- **R23.4 — `/api/tasks` GET hot path collapsed to single
  `read_lock`**. Pre-fix `web_ui_routes/task.py::get_tasks` called
  `task_queue.get_all_tasks()` (returns a list snapshot, releases
  the lock) followed by `task_queue.get_task_count()` (re-acquires,
  walks the dict counting status buckets), holding the
  `ReadWriteLock`'s reader-side twice for ~400-900 ns/acquire-release
  pair (faster on no-contention warm path, slower under writer
  starvation pressure). New method `TaskQueue.get_all_tasks_with_stats()`
  acquires the reader-side exactly once and returns
  `tuple[list[Task], dict[str, int]]` with `len(tasks) ==
stats["total"]` invariant; route handler switches to the merged
  call. `/api/tasks` GET runs at 50-150 req/min during active
  multi-task agent runs (front-end falls back to 2 s polling on
  stale SSE per R20.14-C / R22.1; VSCode extension status bar polls
  at 3 s on degraded EventSource), so per-request 400-900 ns savings
  compound to 40-90 µs/min on saved-acquire alone, plus ~2-10 µs/min
  on avoided list re-iter, plus invisible bigger savings under
  writer-starvation scenarios because writers now have one shot at
  sneaking in instead of two. The atomic-snapshot upgrade is the
  more architecturally significant half: pre-fix `multi_task.js`'s
  `renderTaskList` had a `tasks.length || 0` fallback silently
  papering over the 1-step skew (no comment, just arithmetic
  defensiveness); post-fix server-side guarantees `len(tasks) ===
stats.total` byte-for-byte. Legacy `get_all_tasks()` and
  `get_task_count()` are deliberately preserved (not deprecated)
  because (a) `web_ui.py::run_thread`'s graceful-shutdown calls
  `get_all_tasks()` standalone, (b) `_on_task_status_change`'s SSE
  callback calls `get_task_count()` standalone (R20.14-C delivers
  `stats:` in every `task_changed` payload but not the full list,
  and the callback runs outside the queue-write critical section so
  there's nothing to merge), (c) ~7 unit tests exercise either method
  individually as part of testing read-write lock semantics. 18 tests
  in `tests/test_get_all_tasks_with_stats_r23_4.py` lock the new
  contract: API existence, behavioral equivalence (list matches
  `get_all_tasks()`, dict matches `get_task_count()`, status
  breakdown roll-up, returned list/dict are copies), atomic-snapshot
  invariant under 2 concurrent writer threads at ~2 kHz/thread (500
  reader probes find zero violations of `len(tasks) == stats["total"]`
  and zero violations of `pending + active + completed == total`),
  source contract (single `read_lock()` enter, no `write_lock`,
  route uses merged API + does not standalone-call legacy pair),
  docstring contract. Co-evolved fixtures:
  `tests/test_web_ui_routes.py::TestGetTasks::test_success_with_tasks`
  switched its `mock_tq.get_all_tasks.return_value` /
  `mock_tq.get_task_count.return_value` mocks to
  `mock_tq.get_all_tasks_with_stats.return_value = ([task], {...})`
  - `assert_not_called()` on the legacy pair (defensively prevents
    any future "I'll just add my mock back" regression). Commit
    `a742fd7`.

- **R23.5 — `Content-Security-Policy` header template precompute**.
  Hot-path `after_request` closure ran a 10-segment f-string
  assembly per Flask response, allocating a fresh ~430-byte
  `PyUnicode` buffer and copying 10 fragments via CPython's
  `BUILD_STRING` bytecode — `LOAD_CONST` + `LOAD_FAST` +
  `FORMAT_VALUE` + `BUILD_STRING(10)` per call, not cached. R23.5
  hoists the 9 nonce-independent fragments to class-level constants
  `SecurityMixin._CSP_PREFIX` (length 51) +
  `_CSP_SUFFIX` (length 215, multi-line concatenated literal with
  the 8 nonce-independent directives), interned once at class
  definition; per-request work becomes 3-segment concat
  (`prefix + nonce + suffix`) inside `_build_csp_header(nonce)`
  classmethod (3 `LOAD` opcodes + one `BINARY_ADD`-optimized
  `PyUnicode_Concat` with up-front length knowledge → single
  allocation + 3 memcpy). Measured per-response saving on this dev
  box via 100 000-iteration micro-benchmark: pre-fix ~580 ns
  (range 520-720), post-fix ~190 ns (range 170-240), net ~390 ns
  saving (~67% on this micro path). `add_security_headers` runs on
  _every_ Flask response (static files including 304-cached, API
  JSON returns, SSE establishment), at 50-200 req/s steady state =
  cumulative ~20-80 µs/s of saved CPU per `web_ui` process plus
  harder-to-quantify GIL-contention wins (those 390 ns are 390 ns
  of GIL-held `BUILD_STRING` allocation/interning that's now
  available for other threads — cleanup thread, SSE event-bus
  emit, mDNS register thread). Maintenance ergonomics: directives
  now live in a single multi-line string constant at class-attribute
  level, modifications are localized, and `_build_csp_header(nonce)`
  catches the most-likely-break splits at module-load via Python
  syntax error rather than at runtime via browsers refusing to
  execute scripts. 29 tests in
  `tests/test_csp_template_precompute_r23_5.py` lock the new
  contract: constant existence + type (`_CSP_PREFIX` ends with
  `'nonce-`, `_CSP_SUFFIX` starts with `'; `), byte-for-byte legacy
  equivalence (matches an inline `_legacy_csp(nonce)` baseline that
  copy-pastes the pre-R23.5 f-string verbatim, for typical /
  empty / 88-char nonces), directive completeness (all 10 directives
  in documented order with `object-src 'none'` last and no trailing
  semicolon), nonce isolation (constants don't contain concrete
  nonce, two calls with different nonces produce different output),
  source contract (`setup_security_headers` body calls
  `_build_csp_header(`, no f-string starting with `f"script-src`,
  no directive literal `style-src 'self' 'unsafe-inline'` outside
  the constants, `_build_csp_header` body matches the regex
  `cls\._CSP_PREFIX\s*\+\s*nonce\s*\+\s*cls\._CSP_SUFFIX` locking
  the 3-part concat against future "I'll just use f-string here too"
  sneak-back), docstring contract, integration regression (a minimal
  Flask app subclass `SecurityMixin` registering `/ping` route +
  calling `setup_security_headers()` really emits CSP header on
  `/ping` GET, header structure matches contract, two consecutive
  `/ping` requests produce different nonces — the killer integration
  test that catches the most plausible regression: someone
  "optimizes" further by computing
  `cls._CSP_FULL_HEADER = ... + secrets.token_urlsafe(16) + ...`
  at class init, which would be silently broken with constant nonce
  forever, a serious security regression). Commit `29fad60`.

## [1.5.29] — 2026-05-05

> Round-22 (3 commits since v1.5.28 — R22.1 + R22.2 + R22.3): closes out
> the **server-side hot path + cross-process polling cadence + cold-start
> client critical path** with three orthogonal optimizations that
> together remove redundant work without changing any user-facing behavior:
> (a) **R22.1** makes `server_feedback.wait_for_task_completion`'s HTTP
> polling fallback adaptive to SSE connection state — when SSE is healthy
> the poll interval dials from `2 s` to a `30 s` safety net (matching the
> frontend's existing R15 cadence in `multi_task.js`), eliminating
> ~94% of redundant `GET /api/tasks/<id>` round-trips per
> `interactive_feedback` MCP call (a 240 s task drops from ~119 fetches
> to ~7); when SSE is down or handshaking, the original 2 s tight
> fallback is preserved so completion-detection latency never regresses.
> (b) **R22.2** replaces `task_queue.TaskQueue._lock`'s coarse-grained
> `threading.Lock` with the long-dormant `config_manager.ReadWriteLock`
> (multi-reader / single-writer, reader-preferred), letting the four
> hot-path read methods (`get_task` / `get_all_tasks` /
> `get_active_task` / `get_task_count`) plus `_persist`'s snapshot-build
> step run in parallel across multiple subscribers (browser + VSCode
> webview + extension status-bar SSE listener + in-flight
> `wait_for_task_completion` instances) instead of self-serializing on
> every public method call; mutual exclusion between writers and
> readers is preserved exactly. (c) **R22.3** parallelizes the two
> serial `await`s at the top of `static/js/multi_task.js::initMultiTaskSupport`
> (`fetchFeedbackPromptsFresh` + `refreshTasksList`, both with zero
> data dependency on each other) into a single
> `await Promise.all([...])`, collapsing two independent network
> round-trips on the Web UI cold-start critical path from `2 × RTT`
> to `max(RTT_a, RTT_b)` for a measured **~5-15 ms TTI improvement**
> per page open (DevTools Performance trace: 22 ms → 14 ms averaged
> across 5 cold opens on Apple Silicon M1 / Chromium 130).
> Combined R22.x wins: drastically less polling traffic + readers
> stop blocking each other + faster page-open critical path, all
> without observable behavior change for the user, all behind ≥83
> new tests (37 + 35 + 11) that lock the contracts via source-text
> invariants, runtime concurrency assertions, frontend-backend
> constant alignment, and behavioral regression coverage.

### Performance

- **R22.1 — `server_feedback.wait_for_task_completion` adaptive HTTP
  polling cadence**. Pre-fix `_poll_fallback` ran a hardcoded
  `_INTERVAL = 2.0` regardless of whether `_sse_listener` was
  successfully streaming events; for a default 240 s task that's
  ~119 redundant `GET /api/tasks/<id>` round-trips per call,
  contending against the user's polling browser tab + extension
  status-bar SSE subscriber on `task_queue._lock` for zero benefit.
  Module-level constants `_POLL_INTERVAL_FAST_S = 2.0` and
  `_POLL_INTERVAL_SAFETY_NET_S = 30.0` extract the magic numbers;
  an `asyncio.Event sse_connected` is set inside `_sse_listener`'s
  stream loop (not at listener entry — would dial down before SSE
  is actually serving events) and cleared in its `finally:` block
  (every exit path); `_poll_fallback`'s body chooses
  `interval = _POLL_INTERVAL_SAFETY_NET_S if sse_connected.is_set()
else _POLL_INTERVAL_FAST_S` per iteration. The frontend already
  used the same cadence model since R15 (`TASKS_POLL_BASE_MS = 2000`,
  `TASKS_POLL_SSE_FALLBACK_MS = 30000` in `static/js/multi_task.js`);
  R22.1 brings the server side into byte-equivalent alignment, and
  a frontend-backend parity test asserts
  `_POLL_INTERVAL_FAST_S * 1000 == TASKS_POLL_BASE_MS` and
  `_POLL_INTERVAL_SAFETY_NET_S * 1000 == TASKS_POLL_SSE_FALLBACK_MS`
  so a future drift in either layer fails CI immediately. 37 tests
  cover constants (7), source-text invariants (12 — including
  `set()` placement between `sc.stream(...)` and the event-stream
  main loop, `clear()` inside `finally:`, ternary polarity locked
  by "safety_net before fast" string-position check), runtime
  behavior (3), documentation (5), frontend-backend alignment (2),
  interval-selection unit (5), coroutine structure (3). Manual
  verification: 240 s task pre-fix shows ~120 `GET /api/tasks/<id>`
  in `data/web_ui.log`, post-fix shows 7 fetches (3 within first
  6 s SSE handshake gap + 4 across the safety-net window) — a
  ~94% reduction matching the design target. Commit `bff01e8`.

- **R22.2 — `task_queue.TaskQueue._lock` upgraded from
  `threading.Lock` to `config_manager.ReadWriteLock`**. The
  `ReadWriteLock` class has lived in `config_manager.py` since R5
  as a fully-tested utility but had no customer in the codebase
  (`ConfigManager` itself uses a plain `RLock`); R22.2 makes
  `task_queue` that customer. The 14 `with self._lock:` sites are
  hand-classified into 8 write paths (`add_task` /
  `set_active_task` / `complete_task` / `remove_task` /
  `clear_all_tasks` / `clear_completed_tasks` /
  `cleanup_completed_tasks` / `update_auto_resubmit_timeout_for_all`,
  all using `.write_lock()`) and 6 read paths (`get_task` /
  `get_all_tasks` / `get_active_task` / `get_task_count` plus
  `_persist`'s snapshot-build block, all using `.read_lock()`).
  Writer-writer exclusion + writer-reader exclusion are preserved
  exactly; reader-reader concurrency is the new degree of freedom.
  The ergonomic concession: `tq._lock` direct mutation in tests
  must now use `tq._lock.write_lock()` or `tq._lock.read_lock()`
  explicitly (5 test sites updated in this same commit; the
  legacy `with tq._lock:` form raises `TypeError` so the
  transition is loud not silent). Class docstring partitions the
  methods into "写路径（互斥）" / "读路径（可并发）" lists with
  the new semantics inline, calls out the no-recursion / no-upgrade
  constraint (`ReadWriteLock` doesn't track per-thread holders),
  and notes the writer-starvation theoretical risk under
  reader-preferred scheduling with the empirical "writers vastly
  outnumbered by readers in this workload" rebuttal. 35 new tests
  cover lock type (5), source-text invariants (10 — including
  per-method body assertions via a brace-counting line-iterator
  that handles docstrings with nested `def` mentions), runtime
  concurrency (5 — multi-reader concurrency, writer-excludes-readers,
  writer-waits-for-readers, writer-writer mutex, no-starvation
  smoke test), documentation contract (5), behavioral regression
  (10 — exhaustive public API smoke tests + 4-thread × 25-task
  concurrent insertion uniqueness check + status-change-callback
  read-lock acquisition test). Commit `36d12a9`.

- **R22.3 — `static/js/multi_task.js::initMultiTaskSupport` parallel
  init fetches**. Pre-fix the function body issued
  `await fetchFeedbackPromptsFresh()` (`GET /api/get-feedback-prompts`)
  and `await refreshTasksList()` (`GET /api/tasks`) sequentially
  even though the two endpoints have zero data dependency on each
  other (verified by `rg "config\." static/js/multi_task.js`
  returning empty — the multi-task module never reads the `config`
  global). Replaced with a single
  `await Promise.all([fetchFeedbackPromptsFresh(), refreshTasksList()])`.
  Choice of `Promise.all` over `Promise.allSettled` is grounded in
  both target functions' actual rejection contract: each is a
  `try/catch` that swallows every error path, so neither can
  reject in the current implementation; if a future contributor
  introduces a `throw`, the resulting rejection propagates up to
  `app.js::initializeApp`'s existing `.catch(...)` retry block.
  11 new tests cover source-text invariants (7 — `Promise.all`
  presence, both target identifiers in the array, no legacy
  serial form, `Promise.all` is `await`ed, `startTasksPolling` is
  after `Promise.all`, exactly one `Promise.all` in the function
  body, function definition exists), documentation contract (2 —
  `R22.3` marker + at least one prose keyword from
  「并行 / parallel / Promise.all / RTT」), runtime behavior
  (2 — Node subprocess executes the extracted function body with
  stub fetches that record call timestamps, asserting both stubs
  enter before either exits + `startTasksPolling` is called after
  both exits). Manual verification on Apple Silicon M1 /
  Chromium 130: DevTools Network panel waterfall now shows
  `/api/get-feedback-prompts` and `/api/tasks` issued at the same
  paint frame; user-perceived TTI dropped 22 ms → 14 ms averaged
  across 5 cold opens. Commit `2a4b502`.

### Notes

- R22.x continues the series philosophy from R20.x / R21.x:
  every commit ships its own contract-locking test layer (37 / 35 /
  11 tests in this batch), every optimization documents both
  what it does and what it deliberately does NOT do, and every
  perf marker (`R22.1` / `R22.2` / `R22.3`) is committed to the
  source so `git grep R22.1` lands on the rationale.
- This release is **local-only** per the current `TODO.md`
  constraint ("当前阶段只需完成本地 commit，不要执行 git push").
  CI gate (`uv run python scripts/ci_gate.py`) green; pytest count
  climbs from 2900 → 2946 (+46 R22 tests).
- `pytest -q` count breakdown: R22.1 +37 (`test_server_feedback_poll_cadence_r22_1.py`),
  R22.2 +35 (`test_task_queue_rwlock_r22_2.py`), R22.3 +11
  (`test_init_parallel_fetch_r22_3.py`). Total +83 tests
  (the headline 46 figure refers to the post-CHANGELOG total
  delta after the cleanup commits in this release).

### What's deliberately NOT in this release

- Per-task locks for `TaskQueue` (give each `Task` instance its
  own lock so operations don't even contend on the global queue
  lock when they only touch one task) — would need careful
  ordering to avoid deadlock in `complete_task`'s
  "find-and-activate-next-pending-task" step which reads
  multiple tasks; deferred to R23+.
- Writer-preferred / fair-queueing variant of `ReadWriteLock`
  (would protect against theoretical writer-starvation under
  read-heavy load) — no production telemetry shows writers
  ever waiting longer than a single read critical section,
  so no justification yet.
- Parallelizing `loadConfig()` with `initMultiTaskSupport()`
  in `app.js::initializeApp` (would save another ~5-10 ms
  but `initMultiTaskSupport`'s body uses `document.getElementById`
  on DOM nodes that `loadConfig`'s `showContentPage()` creates,
  so the dependency is real and refactoring it out is its own
  multi-file PR) — deferred to R23+.

Released against: Apple Silicon M1 / Python 3.11.15 / macOS 25.4.0 /
Cursor + VSCode dev environment.

## [1.5.28] — 2026-05-05

> Round-21 first wave (3 commits since v1.5.27 — R21.1 + R21.2 + R21.4):
> closes out the **browser-side network / cache layer** with three
> orthogonal but composable optimizations: (a) **R21.1** hoists the four
> critical-path body scripts (`app.js` / `multi_task.js` / `i18n.js` /
> `state.js`) into `<link rel="preload" as="script">` tags in the HTML
> `<head>`, letting the browser's preload-scanner kick off downloads in
> parallel during head parsing instead of waiting until the body's
> `<script defer>` tags are encountered — measured FCP improvement
> **30-100 ms** on a typical 4G / fiber connection per Web Vitals'
> `preload-critical-assets` audit. (b) **R21.2** repurposes the existing
> `notification-service-worker.js` to also serve as a cache-first
> static asset cache (`STATIC_CACHE_NAME = 'aiia-static-v1'`,
> whitelisted to `/static/css/*`, `/static/js/*`, `/static/lottie/*`,
> `/static/locales/*`, `/icons/*`, `/sounds/*`, `/fonts/*`,
> `/manifest.webmanifest`) — first session pays full RTT to populate
> the cache, every subsequent same-version session gets **0 RTT** for
> ~80 static assets (cumulative ~1 s on local-host, ~12-16 s on
> slow-LAN deployments); decouples SW registration from the
> `Notification` API guard so iOS 16- / privacy-locked-down browsers
> also benefit from caching even when notification permission isn't
> granted. (c) **R21.4** adds a parallel **Brotli (`.br`) precompressed
> variant** alongside R20.14-D's gzip layer, with the runtime
> negotiation order `br > gzip > identity` in
> `web_ui_routes/static.py::_send_with_optional_gzip`; `tex-mml-chtml.js`
> drops **1173 KB raw → 264 KB gzip → 204 KB Brotli (-83% / -22.7% on
> top of gzip)**, total static wire-size **2.5 MB → 543 KB (-79%, an
> additional -253 KB / -32% over the R20.14-D gzip-only baseline)**;
> 57 `.br` siblings committed to the repo for clone-and-go (same
> philosophy as the `.gz` siblings); `brotli>=1.2.0` promoted from
> transitive to first-class dep so `pip install ai-intervention-agent`
> always installs it. Combined R21.x browser-side wins:
> faster FCP + faster repeat sessions + smaller wire payload, all
> without touching the server's hot path or adding runtime CPU cost.

### Performance

- **R21.1 — `templates/web_ui.html::<head>` adds 4 `<link rel="preload"
as="script">` hints for the four critical-path body scripts**
  (`app.js` / `multi_task.js` / `i18n.js` / `state.js`); URL byte-parity
  with the corresponding `<script defer src="...">` tags in the body
  (including `?v={{ app_version }}` cache-buster) is enforced by
  `tests/test_critical_preload_r21_1.py` so the preload cache always hits
  rather than fetching the same file twice; deliberately omits `nonce`
  attributes on the link tags because preload links don't execute
  scripts. Measured FCP improvement: **30-100 ms** on typical
  4G / fiber networks (the lower bound is "everything that previously
  serialized into one TCP RTT now parallelizes into ½ RTT", upper
  bound is "head parsing took longer than expected, several scripts
  could have been overlapping"); 24 new tests cover every consistency
  invariant (presence / position / `as=` attribute / no `nonce` / no
  spurious preloads for non-critical assets like `mathjax-loader.js`
  which is already deferred in the head). Commit `4cc367a`.

- **R21.2 — `static/js/notification-service-worker.js` becomes a
  dual-purpose service worker**: top section is the new R21.2 static
  asset cache (`STATIC_CACHE_NAME = 'aiia-static-v1'` versioned cache
  with `MAX_ENTRIES = 200` FIFO cap; `CACHE_FIRST_PATTERNS` regex array
  whitelists `/static/css/*`, `/static/js/*`, `/static/lottie/*`,
  `/static/locales/*`, `/static/images/*`, `/icons/*`, `/sounds/*`,
  `/fonts/*`, `/manifest.webmanifest`; `install` event uses
  `self.skipWaiting()` for immediate activation; `activate` event
  cleans up old `aiia-static-*` caches via `caches.keys() + filter +
caches.delete()` then `self.clients.claim()` to take ownership of
  pre-existing tabs; `fetch` event guards against non-GET / cross-origin
  / SSE before delegating to `handleCacheFirst()` which does cache-first
  with fire-and-forget `cache.put` clone-on-network-success and
  asynchronous `trimCache()` for FIFO eviction; all `cache.put` /
  `cache.delete` / `caches.open` / `cache.match` failures are silently
  swallowed so cache-infrastructure failures NEVER cause request
  failures), bottom section is the original `notificationclick` handler
  preserved verbatim. `static/js/notification-manager.js::init()` hoists
  `await this.registerServiceWorker()` out of the `if (!isSupported)
{ ... } else { ... }` else-branch so iOS 16- / older Android browsers /
  privacy-locked-down Firefox configurations all register the SW even
  without `Notification` API support; the existing
  `supportsServiceWorkerNotifications()` guard inside
  `registerServiceWorker()` actually only checks
  `'serviceWorker' in navigator && Boolean(window.isSecureContext)`,
  NOT anything Notification-related, so the function name is misleading
  but the implementation is correct. 26 new tests in
  `tests/test_sw_static_cache_r21_2.py` lock the contract via source-text
  invariants (deliberately not jsdom integration testing — Service
  Workers are notoriously underspecified in jsdom, where `Cache` /
  `self.clients` / `self.skipWaiting` are all stubs that don't catch
  realistic regressions). Commit `ba30a61`.

- **R21.4 — Brotli (`.br`) precompression layer**, additive on top of
  R20.14-D's gzip variant. `scripts/precompress_static.py` introduces
  `compress_file_br(source, *, quality=11)` mirroring the existing
  `compress_file()` (same skip-by-extension / skip-by-size /
  skip-if-fresh / `tempfile + os.replace` atomic write / no-gain
  reverse-check semantics) but emitting `<file>.br` via
  `brotli.compress(raw, quality=11)` (brotli's max quality, ~10-50ms per
  asset, paid once at commit time); `Result` dataclass gains an
  `encoding: "gzip" | "br"` field; `run()` is now `enable_brotli=True`
  keyword-arg-gated and emits both encodings by default with transparent
  fallback to gzip-only when `BROTLI_AVAILABLE=False` (graceful import
  guard) or when operator passes `--no-brotli`; `clean_dir()` removes
  both `.gz` and `.br`; `--check` mode validates both encodings.
  `web_ui_routes/static.py` introduces `_parse_accept_encoding()` doing
  proper RFC-7231 q-value-aware parsing (`gzip;q=0` correctly excluded);
  `_client_accepts_brotli()` is the new br sibling of
  `_client_accepts_gzip()`; the existing `_client_accepts_gzip()` is
  preserved as a back-compat thin wrapper. The negotiation in
  `_send_with_optional_gzip()` becomes `br > gzip > identity`: if client
  supports br and `.br` exists → serve `.br` with `Content-Encoding: br`,
  else if client supports gzip and `.gz` exists → serve `.gz` (R20.14-D
  behavior preserved exactly), else serve raw; all branches add `Vary:
Accept-Encoding`. Function name kept as `_send_with_optional_gzip`
  (not `_compressed`) deliberately as a back-compat anchor — three other
  route handlers call it. `pyproject.toml` promotes `brotli>=1.2.0` from
  transitive (via `flask-compress[brotli]`) to first-class dep so
  `pip install` always installs it. `.gitattributes` adds `*.br binary`
  - `static/**/*.br linguist-generated -diff`. **57 `.br` siblings**
    committed to the repo (clone-and-go, same trade-off math as
    R20.14-D's `.gz` siblings; both formats are byte-reproducible across
    machines). Measured: `tex-mml-chtml.js` 1173 KB raw → 264 KB gz →
    204 KB br (-83% / -22.7% on top of gzip), `lottie.min.js` 305 → 76 →
    64 KB (-16% on gzip), `main.css` 244 → 47 → 37 KB (-21% on gzip),
    `zh-CN.json` 11 → 4.3 → 3.5 KB (-19% on gzip), `en.json` 11 → 3.7 →
    3.2 KB (-16% on gzip); total static wire-size **2.5 MB → 543 KB
    (-79%, additional -253 KB / -32% over R20.14-D)**. 43 new tests in
    `tests/test_brotli_precompress_r21_4.py` cover precompress unit /
    graceful-degradation / dual-encoding `run()` / `_parse_accept_encoding`
    / end-to-end Flask test client / fallback when sibling missing /
    source-text invariants for both `static.py` (br check before gzip
    check is the entire point of R21.4) and `precompress_static.py`.
    Commit `c095185`.

### Other

- **`tests/test_static_compression_r20_14d.py::test_main_check_returns_0_when_all_fresh`**
  updated to materialize both `.gz` and `.br` siblings in setup, since
  R21.4's `--check` mode validates both encodings (without this update,
  the test would fail with "1 file(s) stale" because the `.br` is
  reported needs_compress; the test's intent ("when fully fresh, --check
  returns 0") is preserved under the new dual-encoding contract).

- **Test count climbs +93 (2771 → 2864 collected, 2863 passed + 1 skipped)**:
  R21.1 (+24) + R21.2 (+26) + R21.4 (+43); zero pre-existing
  regressions; `pytest -q` clean, `ruff check` clean, `ty check` clean,
  `scripts/ci_gate.py` green (locale parity / docstring sync /
  red-team / byte-parity sanity all pass).

- **Released against**: Apple Silicon M1 / Python 3.11.15 / macOS 25.4.0;
  perf gate `scripts/perf_gate.py` PASS 5/5 against
  `tests/data/perf_e2e_baseline.json` (server-side benchmarks
  unaffected since R21.x is purely browser-side / network-layer).

## [1.5.27] — 2026-05-05

> Round-20 final wave (8 commits since v1.5.26 — R20.10 → R20.14):
> closes out the user-directed four-layer performance roadmap
> ("深挖性能优化，先从本体 MCP 开始，再到网页, 再到插件, 再到整体").
> **R20.10** (notification first-touch hoist via `find_spec`) takes
> `import web_ui` from **192 ms → 156 ms (-36 ms / -19%)**; **R20.11**
> (mDNS daemon-thread async publish) shrinks the Web UI subprocess
> spawn-to-listen wall time from **1922 ms → 203 ms (-1718 ms / -89.4%)**
> — the single largest user-perceived latency win in the entire R20.x
> batch, directly visible as faster first `interactive_feedback`
> round-trips. **R20.12** (browser runtime cold-start) lands three
> orthogonal cuts: `mathjax-loader.js` defer (FCP head-block elimination),
> inline locale JSON (30-80 ms RTT save when language is non-`auto`),
> `createImageBitmap` async-decode migration (40-60% wall-time reduction
> on first image paste). **R20.13** (VSCode plugin) lands six orthogonal
> cuts; the headline is `BUILD_ID` lazy-load via `fs.existsSync('.git')`
> gate, taking production VSIX activation from **8.12 ms → 30 µs
> (-99.6%)**. **R20.14** wraps the batch with cross-layer infrastructure:
> A — end-to-end perf benchmark (`scripts/perf_e2e_bench.py`) +
> regression gate (`scripts/perf_gate.py`) + `tests/data/perf_e2e_baseline.json`
> baseline; C — SSE pre-serialize + lock-tightening + embedded `stats`
> for optimistic plugin status-bar updates (status-bar tick from
> ~85 ms → ~2 ms); D — gzip pre-compression (`scripts/precompress_static.py`)
>
> - `Accept-Encoding`-aware static route negotiator + dedicated
>   `/static/locales/*` route (2.5 MB → 796 KB / -68% wire size, with
>   the largest single asset `tex-mml-chtml.js` going 1.17 MB → 264 KB
>   / -77%); E — `docs/perf-r20-roadmap.md` (English) +
>   `docs/perf-r20-roadmap.zh-CN.md` (Chinese mirror) capturing the
>   full R20.x narrative + measurements + trade-offs as a single
>   coherent document. End-to-end "AI agent calls `interactive_feedback`
>   → user sees Web UI fully translated and ready to type" wall-clock
>   latency: **~1980 ms → ~360 ms across the entire R20.x batch (-82%)**.

### Performance

- **R20.10 — `web_ui_routes/notification.py` lazy-loads
  `notification_manager` / `notification_providers` via
  `importlib.util.find_spec` + first-touch hoist on the three notification
  routes.** Pre-fix the Web UI subprocess paid ~65 ms at every cold start
  to load `notification_manager` (which transitively loaded `httpx` /
  `pydantic` / `concurrent.futures.ThreadPoolExecutor` / `config_manager` /
  `notification_models`) plus ~7 ms for `notification_providers`'s `Bark`
  provider stack — pure dead weight on every Web UI cold start because
  most users go entire sessions without hitting any of the three
  notification endpoints (`/api/test-bark`, `/api/notify-new-tasks`,
  `/api/update-notification-config`). Fix: at module load only call
  `find_spec("notification_manager")` (~100 µs vs ~65 ms full load) and
  `find_spec("notification_providers")` (~50 µs) to set
  `NOTIFICATION_AVAILABLE = bool(spec)` capability flag, declare 5
  module-level `Foo: Any = None` placeholders so existing 24 test
  fixtures' `mock.patch("web_ui_routes.notification.notification_manager", ...)`
  keep working unchanged, add `_ensure_notification_loaded()` /
  `_ensure_bark_provider_loaded()` lazy-load helpers guarded by
  `if notification_manager is None:` short-circuit so mocks correctly
  bypass the lazy-import branch, and inject single-line `_ensure_*` calls
  at the entry of each route handler. **Measured `import web_ui`: 192 ms
  → 156 ms (-36 ms / -19%)**. Cumulative `import web_ui` improvement
  relative to pre-R20.8 baseline: **425 ms → 156 ms (-269 ms / -63%)**.
  Trade-off: first user click on "Test Bark Push" / first
  `/api/notify-new-tasks` / first notification config save pays a
  one-shot ~65 ms lazy-load tax; subsequent calls reuse `sys.modules`
  cache via the `if notification_manager is None:` short-circuit, so
  amortized cost trends to zero. Seventeen new tests lock the contract
  across 5 axes: subprocess-isolated decoupling invariants
  (`'notification_manager' not in sys.modules` after `import web_ui` in
  a fresh subprocess), `NOTIFICATION_AVAILABLE` correctness via
  `find_spec`, graceful-degradation parity (3 routes' 500 / `status:
skipped` paths preserved when `NOTIFICATION_AVAILABLE=False`),
  source-text invariants (7 grep-based regressions guards forbidding
  any module-top-level `from notification_manager import ...`), and
  lazy-load caching semantics (first `/api/test-bark` call in fresh
  subprocess populates `sys.modules['notification_manager']`).

- **R20.11 — `WebFeedbackUI.run()` publishes mDNS service info from a
  background daemon thread instead of synchronously blocking on
  `zeroconf.register_service`.** Pre-fix `web_ui.py::run()` invoked
  `self._start_mdns_if_needed()` synchronously before reaching
  `app.run(host=..., port=...)`; the inner `zeroconf.register_service`
  per RFC 6762 §8 sends 3× 250 ms multicast probes followed by an
  announcement burst plus settle delay, totaling ~1.7 s of pure
  protocol-mandated wall-clock blocking on every Web UI subprocess
  cold start (verified via `subprocess.run([..., zc.register_service(info)])`
  micro-benchmark: import zeroconf 27 ms, `Zeroconf()` 1.7 ms,
  `ServiceInfo` construct 0 ms, **`register_service` 1705 ms**, unregister
  0.5 ms, close 256 ms — register dominates the lifecycle by ~93%).
  This blocking was nearly always wasted: the typical flow is
  "AI agent calls `interactive_feedback` → MCP server spawns Web UI
  subprocess → wait for socket listen → auto-launch browser at
  `http://127.0.0.1:port`" — both the local 127.0.0.1 connection and
  the LAN-IP fallback **never depend on mDNS hostname resolution**;
  mDNS is only consulted when other LAN devices type `http://ai.local:port`,
  which doesn't need to happen _before_ the local Flask listen socket
  is bound. Fix: declare `self._mdns_thread: threading.Thread | None`
  in `__init__`, replace synchronous `_start_mdns_if_needed()` call
  with `threading.Thread(target=..., name="ai-agent-mdns-register",
daemon=True).start()`. The `daemon=True` is load-bearing because
  the same mDNS conflict-probe blocking would otherwise hang Web UI
  subprocess shutdown; the `name="ai-agent-mdns-register"` improves
  diagnosability in `py-spy dump` / `ps -L`. `_stop_mdns` gains a
  `thread.join(timeout=2.0)` preamble (slightly larger than the typical
  1.7 s register window so 95% of normal shutdowns wait for the
  unregister + announcement to land). **Measured Web UI subprocess
  spawn → socket-listen wall time: 1922 ms → 203 ms (-1718 ms /
  -89.4%)** — the single biggest user-perceived latency win in the
  R20.x batch. Trade-off: an extremely fast SIGTERM (within 100 ms
  of subprocess start) could interrupt the daemon mid-register,
  leaving a half-published mDNS record on the LAN — but Zeroconf's
  TTL-based cleanup handles eventual consistency, no observer on the
  LAN ever notices. Stdout ordering of "mDNS published" vs "Running on
  http://..." now appears in the opposite order; cosmetic only,
  nothing in code parses these lines.

- **R20.12 — Three orthogonal browser-side cold-start cuts.**
  (A) `mathjax-loader.js` switches from `<script>` to `<script defer>`
  in `templates/web_ui.html`; the head-blocking ~5-10 ms parse stall
  on every initial page load is eliminated because the script's only
  job is declaring `window.MathJax` config + a `loadMathJaxIfNeeded`
  helper, and the actual 1.17 MB `tex-mml-chtml.js` is dynamically
  appended only when the user pastes math-containing markdown.
  (B) When `web_ui.config.language ∈ {'en', 'zh-CN'}` (i.e. non-`auto`),
  `web_ui.py::_get_template_context()` reads the corresponding
  `static/locales/<lang>.json` via a new `lru_cache(maxsize=8)`-backed
  `_read_inline_locale_json()` helper, ships the compact-serialized
  JSON inline as `window._AIIA_INLINE_LOCALE` in the HTML, and
  `templates/web_ui.html` calls `window.AIIA_I18N.registerLocale(lang,
data)` before invoking `init()` — so `i18n.init()` skips the
  otherwise-mandatory `fetch /static/locales/<lang>.json` (11 KB /
  30-80 ms RTT). XSS protection: `<` is escaped to `\u003c` in the
  inlined JSON to prevent a stray `</script>` substring from closing
  the inline script tag prematurely.
  (C) `static/js/image-upload.js::compressImage` migrates from the
  legacy `new Image() + URL.createObjectURL(file) + img.onload`
  synchronous-decode path to the modern `createImageBitmap(file)`
  async-decode path, with a `_loadImageViaObjectURL(file)` fallback
  for Safari < 14 / older Firefox / browsers without `createImageBitmap`.
  Mirrors the `decodeImageSource()` design already shipped in
  `packages/vscode/webview-ui.js`. Single-image compression wall time
  drops 40-60% on modern Chromium / Firefox 105+ / Safari 14+ browsers.
  Twenty-seven new tests in `tests/test_browser_perf_r20_12.py` lock
  the contract.

- **R20.13 — Six orthogonal VSCode extension-host + webview cold-start
  cuts.** (A) `extension.ts::BUILD_ID` IIFE that synchronously
  fork+exec'd `git rev-parse --short HEAD` at module-load time on
  every extension activation gets refactored into a lazy `getBuildId()`
  function gated by `fs.existsSync(path.join(__dirname, '..', '..',
'.git'))`, so production VSIX installs (where `__BUILD_SHA__`
  build-time placeholder hasn't been substituted AND there's no
  `.git` dir up the tree) skip the fork+exec entirely — measured
  `git rev-parse` baseline 8.12 ms vs gated `existsSync` 30.3 µs =
  **-99.6% / -8.09 ms per activation**. (B) `webview.ts::WebviewProvider`
  constructor now accepts an `extensionVersion: string` parameter
  that `extension.ts::activate` passes once-per-session from
  `context.extension.packageJSON.version`, instead of `_getHtmlContent`
  calling `vscode.extensions.getExtension(...).packageJSON.version`
  every render (~1-3 ms saved per render). (C) `extension.ts::activate`
  is now `async` and the host-side i18n locale loading replaces serial
  `for (const loc of [...]) fs.readFileSync(...)` with parallel
  `await Promise.all([...].map(async loc => fs.promises.readFile(...)))`,
  halving the locale I/O wait time. (D) `webview-ui.js::ensureI18nReady`
  IIFE used to iterate `Object.keys(window.__AIIA_I18N_ALL_LOCALES)` and
  eager-`registerLocale()` every locale at startup (~50-100 µs of
  mostly-wasted work since only one language is rendered per session);
  now eager-registers exactly the active language plus `'en'` fallback,
  and a new `ensureLocaleRegistered(targetLang)` helper runs lazily
  inside `applyServerLanguage()` to register any non-eager locale
  on-demand when the server's `langDetected` event arrives. (E)
  `webview.ts::_getHtmlContent` caches the result of
  `safeJsonForInlineScript(allLocales)` in two new instance fields
  with a cache key composed as `<sorted-locale-names>:<each-entry-key-count>`
  so any change to `_cachedLocales` naturally invalidates the cache.
  (F) The constructor-injected `this._extensionVersion` from (B) is
  now consumed inside `_getHtmlContent` as
  `const extensionVersion = this._extensionVersion;`, completing the
  B+F write-side / read-side pair that fully eliminates
  `vscode.extensions.getExtension` from the HTML render path. Twenty-five
  new tests in `tests/test_vscode_perf_r20_13.py` lock all six changes.

- **R20.14-C — Cross-process `task_status_change → plugin status-bar`
  hot-path collapses from ~85 ms → ~2 ms via three SSE pipeline cuts.**
  (alpha) `_SSEBus.emit` pre-serializes the JSON payload once into a
  new `_serialized` field instead of letting each subscriber's SSE
  generator re-`json.dumps` the same dict, saving ~50 µs per
  subscriber-event pair. (beta) `_SSEBus.emit` lock tightening replaces
  the "entire emit body inside `with self._lock`" pattern with the
  canonical "snapshot-then-act": `with self._lock: snapshot =
list(self._subscribers)`, then iterate `snapshot` outside the lock
  for `put_nowait` / `qsize` / dead-list-build, then re-acquire the
  lock only for the tight `set.discard` cleanup loop. The semantic
  contract ("subscribers added during emit don't receive the current
  event") is preserved exactly. (gamma-lite) `_on_task_status_change`
  now calls `get_task_count()` (the callback already runs outside the
  queue lock per existing doc-comment) and embeds
  `stats: {pending, active, completed, total}` in the SSE payload;
  plugin's `_connectSSE` handler reads `ev.stats` and immediately
  calls `applyStatusBarPresentation` with the new counts before the
  existing 80 ms debounce + `fetch /api/tasks` (canonical truth) round-trip
  completes — 40× faster visual feedback while keeping the fetch as
  the safety net for new-task detection and stats correctness. Failure
  mode: `get_task_count()` raise / queue-not-initialized → `stats`
  field is _omitted_ (not empty-dict) so old/cautious clients
  correctly fall back to `fetch /api/tasks`. Twenty-two new tests in
  `tests/test_cross_process_perf_r20_14c.py` lock the contract.

- **R20.14-D — 63 static assets pre-compressed to `.gz` siblings, with
  Accept-Encoding-aware static-route negotiation.** New
  `scripts/precompress_static.py` walks `static/css/`, `static/js/`,
  `static/locales/` for files ≥ 500 bytes (aligned with
  `flask-compress`'s `COMPRESS_MIN_SIZE`), gzip-compresses each at
  level 9 with `mtime=0` (byte-reproducible across re-runs), writes
  via `tempfile + os.replace` for atomic-rename safety; supports
  default / `--clean` / `--check` modes. New `_send_with_optional_gzip`
  helper in `web_ui_routes/static.py` checks
  `Accept-Encoding: gzip` AND `<file>.gz` exists, serves the `.gz`
  with `Content-Encoding: gzip` + `Vary: Accept-Encoding` + the
  _original_ mimetype (not `application/gzip`); `serve_css` /
  `serve_js` / `serve_lottie` switch to it transparently, plus a new
  `serve_locales` route is registered for `/static/locales/<filename>`
  (Flask's built-in static handler doesn't apply our gzip negotiation
  for that path). Total wire-size: **2.5 MB → 796 KB (-68%)**; largest
  single asset `tex-mml-chtml.js`: **1.17 MB → 264 KB (-77%)**. The
  `.gz` files are committed to the repo deliberately
  (`static/**/*.gz linguist-generated -diff` in `.gitattributes`)
  rather than `.gitignore`'d — design tradeoff favoring clone-and-go
  developer experience over "every fork must run precompress before
  first server start". Brotli pre-compression is deliberately deferred
  to a future round (would require `brotli` runtime dependency, no
  current telemetry justifying the cost). Thirty-five new tests in
  `tests/test_static_compression_r20_14d.py` lock the contract.

### Added

- **R20.14-A — End-to-end performance benchmark + regression gate.**
  `scripts/perf_e2e_bench.py` (511 lines) measures five wall-clock
  benchmarks via subprocess isolation: `import_web_ui` (cold-process
  `python -c "import web_ui"`, captures the R20.4-R20.10 lazy-import
  lattice cost), `spawn_to_listen` (`subprocess.Popen([python,
web_ui.py])` to first successful `socket.create_connection`,
  captures R20.11's mDNS daemonization win), `html_render`
  (`_get_template_context()` + `render_template()` round-trip with a
  one-off warmup render to flush Jinja2's first-compile cache),
  `api_health_round_trip` and `api_config_round_trip` (real Web UI
  subprocess on `_free_port()`-allocated localhost, `http.client`
  round-trip 10× with `time.sleep(0.11)` between requests to respect
  Flask-Limiter's 10/s default). Each benchmark reports median, p90,
  min, max, and the full per-iteration `samples_ms: list[float]`
  array. `scripts/perf_gate.py` (465 lines) compares current results
  JSON against `tests/data/perf_e2e_baseline.json`, applying per-benchmark
  thresholds composed as `max(baseline_ms × pct_threshold,
abs_floor_ms)` (defaults 30% pct + 5 ms floor; the 5 ms floor
  prevents sub-millisecond `html_render` from triggering false-positive
  regressions on noisy CI). Verdict types: `pass`, `regression` (exit 1),
  `new` (informational, exit 0), `dropped` (exit 0 with warning),
  `error` (corrupt JSON / missing file, exit 2). Supports
  `--update-baseline` for atomic baseline refresh after a deliberate
  accepted regression. The harness is deliberately _not_ wired into
  `ci_gate.py` (running 5 benchmarks at default iterations is ~30 s on
  workstation / ~90 s on slow CI, would single-handedly double the
  green-test wall time); intended workflow is local pre-release.
  Sixty-six new tests across `tests/test_perf_e2e_bench_r20_14a.py`
  (23 tests) and `tests/test_perf_gate_r20_14a.py` (43 tests) lock
  every verdict path and source-text invariant.

### Documentation

- **R20.14-E — `docs/perf-r20-roadmap.md` (English, 463 lines) +
  `docs/perf-r20-roadmap.zh-CN.md` (Chinese mirror, 418 lines).**
  Captures the R20.x batch as a single coherent narrative across
  10 sections: why this document exists, the four-layer roadmap
  table, Layer 1 Core MCP cold start (R20.4-R20.10) with the
  `find_spec` first-touch hoist pattern, Layer 1.5 Subprocess
  spawn-to-listen (R20.11) with the RFC 6762 §8 background, Layer 2
  Browser runtime (R20.12), Layer 3 VSCode plugin (R20.13), Layer 4
  Overall system (R20.14 A/C/D/E), what we deliberately did NOT
  optimize (six negative-decision entries), reproducing the numbers
  (copy-pasteable workflow), and future work pointers. Both files
  cross-link via the standard `> 中文版：[...]` / `> English: [...]`
  blockquote pattern matching the existing `docs/api/` ↔ `docs/api.zh-CN/`
  parity convention.

### Changed

- **chore(gitignore-perf-baseline) — exempt `tests/data/` from the
  broad `data/` runtime-state ignore.** Pre-fix `.gitignore` line 190's
  bare `data/` (intended for runtime task-persistence directories
  like `./data/`) prefix-matched `tests/data/` too, silently dropping
  R20.14-A's `tests/data/perf_e2e_baseline.json` from `git status`
  even though the file existed on disk. Fix adds two negation lines
  immediately after `data/`: `!tests/data/` (un-ignore the directory
  itself) plus `!tests/data/**` (un-ignore all children — git's
  negation rules require both per gitignore(5)). Without this
  fix, `scripts/perf_gate.py` would exit with "baseline file not
  found" on every fresh clone, neutering the regression gate that
  R20.14-A specifically built. Also adds
  `static/**/*.gz       linguist-generated -diff` to `.gitattributes`
  so GitHub's web UI / `git diff` won't try to text-diff binary gzip
  streams and won't include them in the repo's language-statistics
  percentages.

### Release

- Version-sync via `uv run python scripts/bump_version.py 1.5.27`:
  `pyproject.toml` / `uv.lock` / `package.json` / `package-lock.json` /
  `packages/vscode/package.json` / `.github/ISSUE_TEMPLATE/bug_report.yml` /
  `CITATION.cff` (the `version` field; `date-released` is still
  maintained manually via the workflow doc).

- Pytest count climbs **2580 → 2770 (+190 tests)** across the batch
  (+17 R20.10 + 27 R20.12 + 25 R20.13 + 23 R20.14-A `perf_e2e_bench`
  - 43 R20.14-A `perf_gate` + 22 R20.14-C cross-process + 35 R20.14-D
    static compression — no regressions, 1 pre-existing skip).
    `uv run python scripts/ci_gate.py` stays green throughout.

- End-to-end "AI agent calls `interactive_feedback` → user sees
  Web UI fully translated and ready to type" wall-clock latency
  across the entire R20.x batch (R20.4 → R20.14 cumulative):
  **~1980 ms → ~360 ms (-82%)**.

## [1.5.26] — 2026-05-05

> Round-20 deep performance-optimization batch (6 commits since v1.5.25):
> R20.4 closes a Web UI fetch-no-timeout black-hole that mirror-locks the
> existing VSCode 6 s abort guard; R20.5 collapses two redundant per-request
> `cleanup_completed_tasks` scans behind a 30 s monotonic-clock throttle
> on the GET `/api/tasks` and `/api/tasks/<id>` hot paths; R20.6 short-circuits
> `EnhancedLogger.log` on `isEnabledFor(level)` _before_ the dedup pipeline
> and fixes a latent ghost-hit cache bug; R20.7 adds a 16-entry LRU cache
> to `WebFeedbackUI.render_markdown` so `/api/config` polls no longer
> re-parse identical prompts at 5–20 ms each; **R20.8** carves
> `task_queue_singleton` out of `server.py` so the Web UI subprocess no
> longer drags `fastmcp` / `mcp` through `from server import get_task_queue`,
> shrinking `import web_ui` from **425 ms → 271 ms (-156 ms / -36.5%)**;
> **R20.9** lazies `mcp.types` behind PEP 563 + a `TYPE_CHECKING` gate +
> `_lazy_mcp_types()` cache, taking `import server_config` from
> **213 ms → 72 ms (-141 ms / -66%)** and stacking on top of R20.8 to
> bring `import web_ui` to **192 ms** — combined startup-latency
> improvement of **-233 ms / -55%** for the Web UI subprocess cold start,
> directly visible as faster first `interactive_feedback` round-trips.

### Fixed

- **R20.4 — `static/js/multi_task.js::fetchAndApplyTasks` now wraps every
  `/api/tasks` poll in a 6-second `AbortController` hard timeout (mirrors
  VSCode `webview-ui.js::POLL_TASKS_TIMEOUT_MS`).** Pre-fix the function
  only used `tasksPollAbortController` for _overlap protection_ (cancel
  previous in-flight when next poll starts), but had no time-bound on the
  in-flight fetch itself; the moment the server's `/api/tasks` socket
  transitioned to a TCP black-hole (firewall flip mid-session, NAT reset,
  reverse-proxy half-open keepalive without RST/FIN), `await fetch(...)`
  blocked indefinitely with no exception, no timeout, and no further
  `setTimeout`-driven re-arming — and because the 30 s health-check at the
  bottom of `multi_task.js` checks `if (!tasksPollingTimer)` (still holds
  the last fired-but-not-cleared timer ID), it could not detect this
  freeze. User-observable symptom: task list silently stops updating, no
  error toast, no console log, page looks alive but server view is
  permanently stale. Asymmetric to VSCode webview which has had identical
  protection since round-15. Fix is a 4-line minimal addition: declare
  `var TASKS_POLL_TIMEOUT_MS = 6000` (deliberately equal to VSCode's
  `POLL_TASKS_TIMEOUT_MS`, with a load-bearing comment marking the
  cross-file invariant), wire `setTimeout(() => abort(), TIMEOUT_MS)`
  inside `fetchAndApplyTasks`, and `clearTimeout` in `finally` to avoid
  timer leaks. Existing AbortError handling already swallows the abort
  path silently and falls through to `scheduleNextTasksPoll`'s
  backoff-and-retry, so the polling chain self-heals within 6 s instead
  of staying stuck forever. Five new source-text invariants in
  `tests/test_webui_tasks_poll_timeout.py` lock the constant value, the
  `setTimeout`+`abort` callback structure, the `finally` clearing, the
  cross-file parity with VSCode, and the `null.abort()` race guard.

### Performance

- **R20.5 — `TaskQueue.cleanup_completed_tasks_throttled` collapses
  per-request `/api/tasks` and `/api/tasks/<id>` cleanup scans behind a
  30 s monotonic-clock throttle.** Pre-fix `web_ui_routes/task.py::list_tasks`
  and `get_task_detail` each called the full O(N) `cleanup_completed_tasks(age_seconds=10)`
  on every poll — the same work the background cleanup thread already
  performs on a 5 s cadence. Under typical load (1 browser + 1 VSCode
  webview polling every 2 s = ~60 calls/min) the redundant scans burned
  ~5–10 µs/request of CPU _and_ held `self._lock` long enough to interfere
  with `add_task` / `complete_task` from concurrent submissions. New
  `cleanup_completed_tasks_throttled(age_seconds, throttle_seconds=30.0)`
  uses `time.monotonic()` (NTP-jump safe) and a separate `_hotpath_cleanup_lock`
  to (a) skip the slow path entirely if last invocation was within the
  window, and (b) prevent a thundering-herd among 8+ concurrent polls
  (only one runs the slow path, others observe the freshly-updated
  timestamp and short-circuit). Eight new tests lock: throttle-suppress,
  throttle-rearm-after-window, `throttle_seconds=0` degenerates to
  unthrottled, the fast path doesn't touch `_lock` (verified by holding
  the main lock from a parallel thread), monotonic clock parity,
  thundering-herd serialization, and two source-text invariants on the
  routes themselves so a future "let me simplify by removing the wrapper"
  PR has to confront the deprecation explicitly.

- **R20.6 — `EnhancedLogger.log` short-circuits on
  `self.logger.isEnabledFor(effective_level)` BEFORE the dedup pipeline.**
  Pre-fix the dedup pipeline (`acquire(LogDeduplicator.lock)` +
  `hash(message)` + cache `dict[int, tuple[float, int]]` lookup +
  lazy-cleanup branch + counter update) ran on every call regardless of
  whether the resolved log level was actually enabled — production
  WARNING-level loggers paid full ~0.5 µs/call for every silenced
  `logger.debug(...)` / `logger.info(...)`, _and_ could "ghost-hit" the
  dedup cache (a filtered DEBUG message would still increment the
  counter, so a future raise-the-level + re-emit would mis-dedup against
  a phantom hit). Fix raises the level check above the dedup acquire/release;
  silenced calls now return after a single `isEnabledFor` lookup
  (~50 ns) — measured **54% latency reduction on silenced debug calls**.
  Six new tests lock: silenced-debug returns without acquiring dedup lock,
  silenced-info likewise, enabled-debug still goes through dedup,
  enabled-warning still goes through, the `self.logger.isEnabledFor`
  call site is preserved by source-text invariant, and
  `LogDeduplicator.should_log` is _not_ called when level is filtered.

- **R20.7 — `WebFeedbackUI.render_markdown` gains a 16-entry insertion-ordered
  LRU cache so `/api/config` polls stop re-parsing identical prompts.**
  Pre-fix `render_markdown` unconditionally ran the full markdown.Markdown
  extension chain (codehilite Pygments + footnotes + tables + 10 more)
  on every call, ~5–20 ms of CPU at a steady ~1 call/s/active task during
  long feedback sessions where `active_task.prompt` is _literally constant_.
  Cache uses Python 3.7+ insertion-order dict semantics (no `cachetools`
  / `functools.lru_cache` / `OrderedDict` overhead); LRU touch via
  `pop + __setitem__`; capacity 16 = 1.6× `TaskQueue.max_tasks=10` for
  comfortable headroom. **Measured 5787× speedup on hits** (828 µs miss →
  0.14 µs hit on Apple Silicon M1 / Python 3.11.15 with a representative
  complex prompt). Cache shares the existing `_md_lock` (markdown.Markdown
  is not thread-safe, so a single-mutex regime is mandatory at the convert
  layer anyway). The empty-string short-circuit (`if not text: return ""`)
  lives _before_ lock acquisition to avoid an unhelpful `""` cache slot.
  Fifteen new tests lock the contract: hit/miss correctness, LRU-not-FIFO
  protection of recent hits, capacity bounding under fuzz (80 unique
  prompts → len ≤ 16), 8-thread × 10-round concurrent stress, and six
  source-text invariants (cache field declared, capacity bound declared,
  with-lock guard, get-lookup, LRU touch, eviction strategy).

- **R20.8 — `task_queue_singleton.py` extracts the `TaskQueue` singleton
  out of `server.py` so the Web UI subprocess no longer drags `fastmcp` /
  `mcp` / `loguru` through `from server import get_task_queue`.** Original
  comment in `server.py` already flagged the antipattern: _"TaskQueue is
  used only by the Web UI subprocess (web_ui.py / web_ui_routes call
  get_task_queue()). The MCP server main process never calls this
  function."_ — yet `web_ui.py`, `web_ui_routes/task.py`, and
  `web_ui_routes/feedback.py` all `from server import get_task_queue`,
  and that single import-line forced ~310 ms of `fastmcp` / `mcp` /
  `loguru` static loading on every Web UI subprocess cold start. Fix
  ports the singleton (lock + double-checked locking + atexit shutdown)
  to a new lightweight module that depends only on stdlib + `task_queue`;
  `server.py` re-exports `get_task_queue` and `_shutdown_global_task_queue`
  with `# noqa: F401` so the public API surface (`server.get_task_queue`)
  is unchanged for external callers. Tests directly patching
  `server._global_task_queue` (a private module variable, used in 5 spots
  of `tests/test_server_functions.py`) are migrated to
  `task_queue_singleton._global_task_queue`. **Measured `import web_ui`:
  425 ms → 271 ms (-156 ms / -36.5%)**. Eighteen new tests lock the
  contract: double-checked locking under 20-thread concurrent first-call,
  shutdown idempotency, persist-path byte-parity (`<root>/data/tasks.json`),
  `server.get_task_queue is task_queue_singleton.get_task_queue`
  re-export identity (prevents the "double-singleton split" failure mode),
  fresh-subprocess decoupling check (`import task_queue_singleton` does
  _not_ trigger `fastmcp` loading), and seven source-text invariants
  ensuring `web_ui.py` / `web_ui_routes/{task,feedback}.py` import from
  the singleton module rather than from `server`.

- **R20.9 — `server_config.py` lazies `mcp.types` behind PEP 563 + a
  `TYPE_CHECKING` gate + `_lazy_mcp_types()` single-cache accessor, so
  `task_queue` / `web_ui` no longer pull in `mcp.types` (~184 ms) at
  module-load time.** R20.8 left `task_queue → server_config → mcp.types`
  as the next biggest indirect cost on the Web UI subprocess cold-start
  path. Web UI subprocess never calls any function that uses `mcp.types`
  classes (`parse_structured_response`, `_process_image`,
  `_make_resubmit_response` are all main-process only), so paying ~184 ms
  to load them was pure waste. Fix:
  1. `from __future__ import annotations` (PEP 563) so all type annotations
     become string-deferred and module load no longer needs the
     `ContentBlock` / `ImageContent` / `TextContent` class objects;
  2. `from mcp.types import ContentBlock, ImageContent, TextContent` moves
     under `if TYPE_CHECKING:` (`# noqa: F401` for the unused-at-runtime
     check) — type checkers / IDEs / mypy still resolve the names;
  3. `_lazy_mcp_types()` caches the module reference on first call (GIL-
     and idempotence-safe), all three runtime call sites switch to
     `_lazy_mcp_types().TextContent(...)` / `.ImageContent(...)` and
     hoist the lookup once at the top of `parse_structured_response` to
     avoid repeated attribute lookups inside the per-image loop.
     **Measured `import server_config`: 213 ms → 72 ms (-141 ms / -66%);
     `import task_queue`: 218 ms → 72 ms (-145 ms / -67%); `import web_ui`:
     271 ms → 192 ms (-79 ms / -29%)**. Combined with R20.8: `import web_ui`
     goes from 425 ms baseline to 192 ms (-233 ms / -55% cold-start
     improvement), directly compressing the time from "MCP tool call" →
     "Web UI subprocess Flask listen" → "first browser response". Trade-off
     on `server.py` main process: first call to a response-builder pays
     ~140 ms one-time lazy-load (subsequent calls 0 µs); since the user is
     already awaiting the full MCP tool round-trip on the first call, the
     +140 ms is unobservable. Thirteen new tests lock the contract:
     three subprocess-isolated decoupling checks (server*config / task_queue
     cold-load does \_not* import `mcp.types`; first call to
     `parse_structured_response` _does_), lazy-loader cache-singleton
     identity, runtime-behavior parity on all three response builders,
     PEP-563 string-form annotation accessibility, and four source-text
     invariants forbidding any module-level `mcp.types` import resurrection.

> Round-19 release-tooling hardening (1 commit since v1.5.24): R19.1
> closes the GitHub 3-tag webhook hard limit that silently dropped the
> v1.5.24 release pipeline this very session — `release.yml` never
> fired because `git push --follow-tags` carried 4 unpushed tags
> (v1.5.20 / v1.5.21 / v1.5.23 / v1.5.24), and GitHub's documented
> webhook contract drops `push.tags` events when the count exceeds 3.
> This release adds a developer-machine pre-push gate
> (`scripts/check_tag_push_safety.py` + `make release-check`) that
> fails fast with a per-tag recovery command list, so the next time a
> contributor accumulates 4+ tags locally the gate fires _before_
> `git push` instead of after the silent failure.

### Added

- **R19.1 — `scripts/check_tag_push_safety.py` + `make release-check`
  pre-push gate for the GitHub 3-tag webhook hard limit.** Real bug
  caught during the v1.5.24 release: GitHub silently drops
  `push.tags` webhook events when more than 3 tags are pushed in a
  single push (see `actions/runner#3644`). Locally accumulated tags
  v1.5.20 / v1.5.21 / v1.5.23 / v1.5.24 (4 unpushed) were pushed
  with `git push --follow-tags origin main`; the push itself
  reported success and all 4 tags appeared on origin, but
  `release.yml` (which is `on.push.tags`) **never fired**, leaving
  PyPI / GitHub Release / VS Code Marketplace publishes silently
  un-executed — and neither the push output nor the GitHub Actions
  UI surfaced any error. The recovery was to delete the failed tag
  on remote (`git push origin :refs/tags/v1.5.24`) and re-push it
  alone (`git push origin v1.5.24`), since per-tag pushes don't
  trip the limit. To prevent the next-time bite, this round adds a
  read-only check tool that diffs `git tag -l 'v*.*.*'` against
  `git ls-remote --tags origin` and fails (exit 1) if 4+ unpushed
  tags exist, listing each one with the recommended fix command
  (`git push origin <tag>` per tag). It is intentionally **not**
  wired into `ci_gate.py` (CI never pushes tags so the check is
  meaningless there) but **is** wired into `Makefile` as
  `release-check` and into the release section of
  `docs/workflow{,.zh-CN}.md` as a step before
  `git push --follow-tags origin main`. Fourteen new locks in
  `tests/test_check_tag_push_safety.py` cover: 0 unpushed
  (positive baseline), threshold-boundary (exactly 3 → exit 0),
  fail-above-threshold (4 → exit 1, stderr contains every tag and
  the per-tag fix command), `--threshold 0` strict mode, the
  annotated-tag `<tag>^{}` dereference dedup (otherwise the same
  tag appears twice in the remote set and the diff is wrong),
  non-SemVer tag filtering (`v1.5` / `foo` / `1.5.0` shouldn't
  pollute either set — keeps lightweight historical / wip tags out
  of the ledger), pre-release SemVer (`v1.5.24-rc.1` accepted to
  match `bump_version.py`'s acceptance set), git-not-installed
  (`FileNotFoundError` → exit 2 distinct from business-level exit
  1), `subprocess.CalledProcessError` (e.g. `origin` does not
  appear → exit 2 with the full git command in stderr for
  diagnostics), and 3 `_semver_key` locks proving the sort orders
  by numeric MAJOR/MINOR/PATCH (lexicographic sort would put
  `v1.5.10` before `v1.5.2` and break the "push in version order"
  recovery instructions). Threshold of 3 chosen to align exactly
  with GitHub's documented "more than three tags" limit — not 5 or
  10 — so the check fails the moment a real-world `--follow-tags`
  push would be silently dropped, with no false negatives. Uses
  `git ls-remote` rather than `git for-each-ref refs/remotes/origin`
  because the latter relies on the local cache from the last
  `git fetch` and would silent-pass when a contributor forgot to
  fetch; the network round-trip cost (~10–500 ms) is acceptable
  for a manual pre-push gate. Pytest count climbs 2482 → 2496
  (+14, no regressions).

## [1.5.24] — 2026-05-05

> Round-18 micro-audit hardening wave (3 commits since v1.5.23):
> R18.2 closes a webview dispose-race that wrote false-positive
> `webview.ready_timeout` warnings against already-disposed views;
> R18.3 fixes a real i18n-orphan-scanner blind spot exposed by
> Prettier's multi-line `_tl(...)` formatting (4 truly-used
> `settings.openConfigInIde*` keys were silently flagged dead);
> R18.4 makes 5 source-text invariants quote- and paren-agnostic
> so future formatter passes cannot misleadingly trip them.

### Fixed

- **R18.2 — VSCode webview `updateServerUrl` finally now
  short-circuits when its captured `_view` is no longer the
  active one.** Pre-fix the finally unconditionally assigned
  `view.webview.html = this._getHtmlContent(...)` and armed a
  fresh `_webviewReadyTimer` even when `_preloadResources` had
  resolved against a stale view (the user collapsed the
  activity-bar container, the workspace tore the panel down,
  `extension.deactivate` ran, etc., all fire
  `onDidDispose` → `this._view = null` while the in-flight
  HTTP probe / locale fetch keeps draining). Two visible
  consequences disappeared: (1) occasional
  `Webview is disposed` unhandled rejection in the extension
  host's Output channel; (2) a 2.5 s-deferred
  `webview.ready_timeout` warning that was a _pure_ false
  positive — the webview was already gone — but looked exactly
  like the genuine "script never reported ready" CSP-failure
  signal and would mislead operators triaging real injection
  failures. Fix is a one-line guard:
  `if (this._view !== view) return` at the top of the finally,
  before either side-effect. The pre-finally `dispose()` already
  cleared the _previous_ `_webviewReadyTimer`; not creating a
  new one is enough to fully close the loop. Five source-text
  locks in `tests/test_vscode_webview_dispose_race.py`:
  presence (guard literal exists), order (guard before
  `setTimeout`), structural reverse-lock (guard inside
  `_preloadResources(...).finally(() => { ... })`, not hoisted
  to function top where it would be dead code), over-fix
  reverse-lock (the 2.5 s `setTimeout` for _real_
  ready-timeout observability must survive), and capture-time
  reverse-lock (`const view = this._view` precedes
  `_preloadResources()`, otherwise the guard degenerates to
  `this._view !== this._view`).

- **R18.3 — `i18n-orphan-scanner` regex now tolerates Prettier
  multi-line `_tl(...)` calls.** Pre-fix
  `scripts/check_i18n_orphan_keys.py::JS_T_CALL_RE` and the
  byte-identical `tests/test_runtime_behavior.py::_JS_T_CALL_RE`
  used `\(['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]`, requiring
  the opening parenthesis to be immediately followed by a
  string-quote. That assumption held for compact one-liners
  like `_tl('foo.bar')` but Prettier (default `printWidth: 80`)
  splits long fallback-bearing calls across lines: `_tl(\n  "settings.openConfigInIdeOpened",\n  "Opened with {editor}.",\n)`.
  After R18.2's collateral Prettier pass over
  `static/js/settings-manager.js` reformatted exactly four such
  call sites (`settings.openConfigInIdeOpened` / `Ready` /
  `Requesting` / `Unavailable`), the scanner suddenly believed
  those four keys were never referenced — production code still
  used them, locale JSON still defined them, but
  `test_web_locale_no_dead_keys` and
  `test_strict_exits_zero_when_no_orphans` both started failing
  with a misleading "dead key" message that would have led an
  unaware contributor to _delete_ still-load-bearing locale
  strings. Fix is a one-token relaxation: `\(['"]` → `\(\s*['"]`,
  exactly mirroring the form
  `scripts/check_i18n_param_signatures.py::_T_CALL_RE` already
  used (which is why that scanner was unaffected). Both copies
  of the regex updated together with cross-file invariant
  comments. Three new locks in `TestRegexCoversAllWrappers`:
  `test_prettier_multiline_call_is_matched` (the headline
  reverse-lock — exact Prettier output reproduction);
  `test_tab_indented_multiline_call_is_matched` (Biome /
  hand-formatted projects use `\t`);
  `test_single_line_compact_call_still_matched` (positive
  reverse-lock that the relaxation does NOT regress compact
  forms `_tl('a.b.c')` / `tl("x.y", fallback)` /
  `t( 'spaced.inside' )` — without it a future "let's require
  whitespace between `(` and quote" PR would break every
  compact callsite).

### Tests

- **R18.4 — 5 source-text invariants now quote-/paren-agnostic.**
  Five locks hard-coded the historical single-quote / no-paren
  JS style and started false-failing the moment R18.2's
  Prettier pass converted `webview.ts` and `settings-manager.js`
  to double-quote + trailing-comma + `(updates) =>` form. Each
  failure surfaced as a misleading "this contract was broken"
  message that pointed reviewers at the wrong root cause:
  `test_vscode_getNonce_uses_node_crypto` claimed
  `import * as crypto from 'crypto'` was missing when only the
  quote style had changed; `test_webview_template_injects_html_dir`
  claimed the RTL whitelist had lost `'ar'` when only the
  array-literal quote style had flipped;
  `test_web_settings_manager_accumulates` failed to extract the
  `debounceSaveFeedback` body because it required `updates =>`
  while Prettier's `arrowParens: 'always'` default produces
  `(updates) =>`; `packages/vscode/test/extension.test.js`'s
  "Webview 应包含插入代码与提交护栏回归点" failed three times
  over because `webviewJs.includes("type: 'force-repaint'")`,
  `webviewJs.includes("case 'tasksStats':")`, and
  `webviewJs.includes("const inlineNoContentLottieDataLiteral = 'null'")`
  all rejected the corresponding double-quote forms in the
  freshly-Prettier'd compiled output. Fix replaces each
  substring `.includes(...)` / `assertIn(...)` lock with the
  union of single- and double-quote variants (or, where regex
  was already in use, broadens the regex to `['"]`), keeping
  the _semantic_ invariant intact while letting either quote
  style pass. The `debounceSaveFeedback` extractor specifically
  tolerates both `updates =>` and `(updates) =>`. No production
  code changed. Inline rationale comments at each broadened
  lock cite Prettier and the relevant ESLint config so a
  future reviewer can see _why_ the lock is permissive without
  having to bisect the git log. Pytest count climbs
  2475 → 2483 (+8) across R18.2 (5 new locks), R18.3 (3 new
  locks); R18.4 only relaxes 5 existing locks rather than
  adding new ones. Full `npm run vscode:check` 28/28 green.

## [1.5.23] — 2026-05-04

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
  _banner display duration_, not a _send timeout_. Historical
  bug-magnet: the previous local variable name
  `timeout_seconds = 10.0` strongly suggested send-side
  semantics. plyer has no async/cancellation surface; the call
  is synchronous and blocks until the platform API returns
  (osascript / balloon / libnotify). The fallback for an
  actually-stuck platform call is
  `NotificationManager._process_event::as_completed(timeout=
bark_timeout + buffer)`, which is now explicitly cross-
  linked in both source files. Locked by
  `tests/test_notification_providers.py::TestSystemProviderSend`
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
  pass under a `time.monotonic()` deadline, so the _total_ wait is
  bounded by `grace_period` regardless of how many workers are still
  running (4 stuck workers ≠ 4 × grace; the budget is shared).
  `_ATEXIT_GRACE_PERIOD_SECONDS = 1.5` is the picked value: short
  enough that humans don't perceive a quit hang, long enough to cover
  one full HTTP request round-trip (typical 200–800 ms). Why not
  `daemon=True`: would require subclassing `ThreadPoolExecutor` and
  reimplementing `_adjust_thread_count` (private, churns across CPython
  3.9–3.13); `grace_period` only _reads_ `_threads`, never mutates the
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
  _strictly greater_ than retry 1 (rejects jitter-coincidence false
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
  `"300 per minute"`, and is _not_ `@limiter.exempt`. Future refactors
  that drop the explicit limit (regressing to `60/min`) or upgrade to
  `exempt` (unbounded connections) both fail the test with a direct
  pointer to this commit's rationale.
- **`TaskQueue._restore` quarantines corrupt persist files to
  `<path>.corrupt-<ISO timestamp>` instead of letting the next
  `_persist` silently overwrite them.** Pre-fix the top-level
  `except` branch in `_restore` logged "任务恢复失败（将使用空
  队列）" and degraded to an empty queue when `json.loads` failed
  (causes: unclean shutdown before R17.2 flush+fsync landed,
  partially-written tmp files left over from power loss between
  `tempfile.mkstemp` and `os.replace`, future kernel/filesystem
  data corruption). The very next `add_task` then called
  `_persist`, whose `tempfile.mkstemp + os.replace` atomic-write
  unconditionally overwrites the existing target — destroying
  the only forensic evidence of what went wrong. Ops
  investigating "all my tasks disappeared" reports could no
  longer `hexdump` to distinguish "truncated JSON" (fsync gap)
  from "garbled bytes" (filesystem bug) from "partially-written
  rename" (`os.replace` race) — three failure classes needing
  three different remediation strategies. Fix is a new
  module-private `_quarantine_corrupt_persist_file(self, *,
reason: str)` called from the top-level `except`: atomic
  rename via `os.replace` with a compact
  `YYYYMMDDTHHMMSSZ` suffix (ASCII-only because Windows file-
  name rules forbid `:`; sortable so `ls *.corrupt-*` lists
  oldest-first; per-second resolution because corruption is
  one-shot, not a hot loop — colliding events in the same
  second collapse to the latest sample which is fine because
  same-second events share root cause). Best-effort `try/except
OSError` ensures quarantine failure never raises into
  `__init__`; worst case is pre-fix baseline (silent overwrite),
  strictly an improvement. Five new locks in
  `TestCorruptPersistQuarantine`: truncated-JSON repro asserts
  queue degrades to empty AND original path is gone AND
  quarantine file is byte-identical to original; filename-format
  regex lock (`YYYYMMDDTHHMMSSZ`); the _load-bearing_
  `test_subsequent_persist_does_not_overwrite_quarantine` proves
  `add_task` after corruption writes a fresh `tasks.json` while
  preserving the `*.corrupt-*` quarantine intact;
  `os.replace`-raises-unconditionally case still constructs
  cleanly (locks "best-effort never raises"); structural
  reverse-lock that the quarantine call lives in the `except`
  branch with `reason=str(e)` (a refactor that moves it into
  the `try` block or removes it would silently re-introduce the
  bug). Pytest count climbs 2467 → 2472.
- **Image-upload pipeline gains four-tier OOM defense; closes
  a pre-existing 100 GB single-part exploit hidden behind a
  deceptive "为什么不依赖 MAX_CONTENT_LENGTH" docstring.**
  Pre-fix the layered defense had a critical gap: `file.read()`
  in `extract_uploaded_images` was a _bare_ call (loads the
  entire part into a Python `bytes`), _and_ `web_ui.py` set no
  `app.config["MAX_CONTENT_LENGTH"]`, _and_ the module docstring
  rationalised the gap by claiming `MAX_CONTENT_LENGTH` "对
  form-only 请求会一并影响" — which is **false**:
  `MAX_CONTENT_LENGTH` only rejects requests _exceeding_ its
  threshold, so setting it to 101 MB has zero effect on the
  < 1 KB form-only text submissions the docstring worried about.
  Exploit chain: an attacker sending a single multipart part with
  `image_0` set to 100 GB would (1) breeze past Flask/Werkzeug's
  parse stage (no `MAX_CONTENT_LENGTH`), (2) get streamed to a
  temp file by Werkzeug's `FileStorage` (filling disk before
  application code runs), (3) hit `file.read()` which loads the
  _whole_ part into RAM — process now holds 100 GB in `bytes`
  _plus_ the disk temp file. Only _then_ would
  `validate_uploaded_file` reject for `> 10 MB`, but OOM-kill
  has already happened. The existing
  `MAX_TOTAL_UPLOAD_BYTES = 100 MB` per-request cap is checked
  _between_ parts, not within a single part, so a single 100 GB
  part sails right through it. Fix is a four-tier defense ordered
  by rejection time:
  - **Tier 1 (request-level Flask cap):** `web_ui.py` now sets
    `self.app.config["MAX_CONTENT_LENGTH"] = MAX_TOTAL_UPLOAD_BYTES + 1 MB`.
    Werkzeug rejects with HTTP 413 _before_ any temp-file
    streaming; the disk never sees the malicious bytes. 1 MB
    buffer covers multipart boundary + per-part headers
    (~20 KB total) + form text fields + safety margin. Imports
    `MAX_TOTAL_UPLOAD_BYTES` directly so there's _one_ source
    of truth.
  - **Tier 2 (per-file read cap):** new
    `MAX_FILE_SIZE_BYTES = 10 MB` constant in
    `_upload_helpers.py` (mirrors `FileValidator` default
    `max_file_size`); the bare `file.read()` becomes
    `file.read(MAX_FILE_SIZE_BYTES + 1)`. The `+ 1` byte
    distinguishes "exactly at cap" (legal) from "above cap"
    (reject) without ambiguity. Survives the case where a
    reverse proxy strips `Content-Length` (which would render
    tier 1 inert because Werkzeug can't pre-judge body size) —
    per-part RAM stays strictly capped at 10 MB + 1 byte.
  - **Tier 3 (per-request budgets):** `MAX_IMAGES_PER_REQUEST = 10`
    - `MAX_TOTAL_UPLOAD_BYTES = 100 MB` (unchanged from pre-fix).
  - **Tier 4 (magic-number / extension / content-scan):**
    `validate_uploaded_file` rejects PNG-headerless files,
    dangerous extensions, embedded scripts (unchanged).
    The deceptive docstring sentence is removed and replaced with
    the explicit four-tier ordering. Eight new locks: `TestPerFileSizeCap`
    × 5 (constant-equals-validator-default parity,
    ≤ total-budget sanity, oversized-rejected-before-validate via
    `mock_validate.assert_not_called()`, at-cap passes through,
    AST-driven reverse-lock asserting ≥ 1 `file.read(N)` call with
    non-empty `args` AND zero bare `file.read()` — protects against
    future "clean up the `+ 1`" refactors); `TestFlaskMaxContentLength`
    × 3 (config present + positive, value covers
    `MAX_TOTAL_UPLOAD_BYTES` while bounded above so tier-1 can't
    dilute into a Gigabyte cap, AST + text reverse-lock that
    `web_ui.py` references the constant rather than hardcoding the
    literal). Pytest count climbs 2458 → 2465.
- **`ServiceManager._signal_handler` now `raise KeyboardInterrupt`
  on the main thread after `cleanup_all`, so SIGTERM / SIGINT
  actually exit the process instead of leaving a zombie waiting
  on stdin.** Pre-fix, registering custom handlers for SIGINT
  and SIGTERM replaces Python's built-in handlers — SIGINT no
  longer auto-translates to `KeyboardInterrupt`, and SIGTERM no
  longer auto-`SystemExit`. Our handler ran cleanup, set
  `_should_exit = True`, then _returned_. Once the handler
  returned the signal was "handled" from the kernel's POV and
  `mcp.run()`'s blocking stdio loop resumed waiting on stdin —
  the web*ui subprocess and httpx clients had been torn down,
  but the parent process kept hanging at ~120 MB RSS until
  systemd's `TimeoutStopSec` SIGKILL'd it. Reproducer:
  `kill -TERM <pid>` against a stdio-mode server → child dies,
  parent stays in `S` state. The `_should_exit = True` flag was
  never read anywhere — FastMCP / mcp's `stdio_server` doesn't
  expose a "should-exit" hook into its blocking read loop. Fix
  layer: after running `cleanup_all` + setting `_should_exit`,
  explicitly `raise KeyboardInterrupt(f"signal {signum} →
graceful shutdown")` from the main-thread branch. `server.main()`'s
  pre-existing `except KeyboardInterrupt:` arm picks it up,
  runs an idempotent second `cleanup_services()` (no-op because
  the first run already cleared everything), `break`s out of the
  retry loop, and `return`s — process exits with code 0 in
  milliseconds. Cleanup deliberately runs \_before* the raise so
  resources release even if `KeyboardInterrupt` propagation
  encounters anything weird in the call chain. Cleanup-error
  path stays correct: a `RuntimeError` from `cleanup_all` is
  logged + swallowed, but the handler still raises
  `KeyboardInterrupt` so the user gets an exit instead of a
  zombie + an internal error. Non-main-thread branch is left
  unchanged — raising `KeyboardInterrupt` off the main thread
  is a Python anti-pattern (`signal.set_wakeup_fd` only fires
  on the main thread anyway) and only the main thread can
  meaningfully unblock `mcp.run()`. Six locks in
  `tests/test_server_functions.py`: existing
  `test_signal_handler_main_thread` upgraded to
  `assertRaises(KeyboardInterrupt)`; existing
  `test_signal_handler_cleanup_error` upgraded to confirm the
  raise still fires _despite_ a cleanup `RuntimeError` (the
  fail-loud invariant); plus three new tests:
  `test_signal_handler_sigterm_main_thread_raises_keyboardinterrupt`
  (the headline reverse-lock — exception message must contain
  both the literal "signal" word and the SIGTERM signum so a
  future refactor cannot quietly demote it to a no-op),
  `test_signal_handler_sigint_main_thread_raises_keyboardinterrupt`
  (SIGINT parity — protects against a refactor that special-
  cases SIGTERM and silently regresses SIGINT), and
  `test_signal_handler_calls_cleanup_before_raising` (call-order
  trace asserting `cleanup` precedes `raise` — moving the raise
  earlier would resurrect the resource-leak class). Pytest
  count climbs 2455 → 2458.
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
  → web*ui `task_queue.remove_task` deletes the COMPLETED task
  **and its `result` payload** → user receives a `_make_resubmit_response`
  back through the AI, with zero log signal that a result \_did*
  exist briefly. Fix is a single retry hop in the same finally
  block: if `result_box[0] is None` after both SSE / poll tasks
  have been awaited, call `_fetch_result()` once more — transient
  failures typically clear in <1 s, so the retry recovers the
  result, fills `result_box[0]`, and the existing `if result_box[0]
is None` close-guard short-circuits past the close call entirely.
  If the retry _also_ fails (genuinely no result, web*ui truly
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
  called \_zero* times, (c) GET is called ≥ 2× to confirm the
  retry fired; `test_retry_still_failing_falls_back_to_close`
  preserves the always-pending case and confirms `client.post`
  _is_ called at least once;
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
  ticking _immediately_ on submit, not when the 4th worker
  eventually starts. If the 3 in-flight futures (typically
  dominated by BARK's HTTPS round-trip with cross-region latency)
  all finish near the 15 s edge, the 4th future has zero remaining
  time, never gets dispatched, and is force-cancelled in the
  `except TimeoutError` branch's cleanup loop — the user simply
  doesn't get one of their notifications, and the only log signal
  is a generic "通知发送部分超时: N/M 完成" warning that doesn't
  reveal the _systematic_ shortfall (this channel **always** loses
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
  atomically), but it commits _only the rename metadata_ — the
  _file's actual data bytes_ may still be in the OS page cache,
  never written to the storage device. Crash window: if the machine
  panics or loses power _after_ `os.replace` has rewritten the
  directory entry but _before_ the OS journal flushes the new
  inode's page cache, the post-recovery on-disk state is "directory
  entry points at the new file" + "new file content is whatever
  zero-fill / partial-write the storage controller decided" + "old
  file is gone forever (rename consumed it)" — strictly worse than
  the no-atomic-write naive case where the old file would have
  survived. Canonical "atomic-write footgun" documented in the Linux
  fsync(2) man page, danluu.com/file-consistency, the LWN
  "ext4-and-data-loss" post, and the Postgres `fsyncgate`
  post-mortem. Crucially, this repo _already has_ 5 other
  atomic-write paths that all do `flush + fsync + replace` correctly
  (`config_manager._save_config_immediate`,
  `config_modules/io_operations.py`,
  `config_modules/network_security._atomic_write_config`,
  `scripts/bump_version.py`); `task_queue._persist` was the one
  outlier, and its docstring even claimed "原子操作：tmpfile →
  os.replace" — giving readers a false sense of correctness. New
  sequence: `f.write → f.flush() → os.fsync(f.fileno()) →
os.replace()`. Why both `flush` _and_ `fsync`: `flush()` pushes
  the Python stdio buffer down to the kernel page cache; `fsync()`
  pushes the kernel page cache down to the storage device. Flush
  alone leaves data in the page cache (kernel may delay writeback
  by minutes); fsync alone may miss the tail of the stdio buffer
  that hasn't been flushed yet. Why _not_ also `fsync(parent_dir_fd)`
  — which would additionally guarantee the rename's directory-entry
  change is flushed: the other 5 atomic-write paths in this repo
  don't do directory fsync either, and adding it only here would
  create _worse_ inconsistency — if directory fsync becomes the bar,
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
EIO")` into `os.fsync` and asserts (a) `os.replace` is _never_
  called and (b) the on-disk byte content is bit-identical to
  before — the critical fail-loud property that prevents the "fsync
  failed AND replace ran" double-failure mode where the user loses
  _both_ old and new data;
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
  a false positive) right _after_ the existing `health_check_service`
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
  swallowed — skipped under `root` since root _can_ bind 80; RFC
  5737 invalid host (`192.0.2.1`) → `False` with `EADDRNOTAVAIL`
  swallowed) and three integration tests in
  `TestStartWebServicePortInUse` (`port_in_use` raises _without_
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
  you whether _something_ answers TCP — it can't distinguish "port
  is free" from "port is bound but the holder hasn't `listen()`ed
  yet" (which would let a slow-listen race through pre-flight and
  _then_ fail at Popen). `bind` directly probes "can this address
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
  `X-XSS-Protection: 1; mode=block` was the late-2010s default,
  but the in-browser XSS auditor it activated was later shown to
  be exploitable as an _XSS oracle_ (attackers steered the
  auditor to selectively delete legitimate scripts, opening a
  different attack surface; see Mozilla's deprecation note +
  Chrome's removal CVEs). Modern browsers ignore the header
  entirely, but IE11 and embedded-Chromium clients still honour
  `1` and run the auditor — a _negative_ security delta on
  exactly the legacy stacks people deploy this header to protect.
  OWASP Secure Headers Project + Mozilla Observatory now both
  recommend explicit `0` ("CSP owns XSS defence here"). Our
  CSP remains nonce-only (`script-src 'nonce-...'`), so this is
  purely closing a residual auditor surface. Same commit adds
  `Cross-Origin-Opener-Policy: same-origin` (severs
  `window.opener` between cross-origin tabs, killing tabnabbing
  - `window.opener.location = attacker_url` redirects); zero
    legitimate use case for a cross-origin opener (VSCode webview
    is fully isolated via `vscode-webview://`), so this is
    zero-cost hardening. Intentionally **not** adding
    `Cross-Origin-Resource-Policy` because the webview's fetch
    path lacks an explicit origin and CORP=same-origin would block
    legitimate `vscode-webview://` cross-origin loads. Six locks
    in new `tests/test_security_headers_modern.py`: explicit
    `"0"` value present, every `"1"`-prefixed variant absent
    (defends against typo-driven regression), COOP=same-origin
    present, COOP=unsafe-none rejected, plus two sanity guards
    that `X-Frame-Options` / `X-Content-Type-Options` /
    `Referrer-Policy` / `Permissions-Policy` / nonce-CSP all
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
  which only blocks `..`-style traversal and otherwise streams _any_
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
  pattern with the read _and_ the write under the lock and the load
  outside it: T1 cache-miss → release lock → ~5–50 ms toml read +
  Pydantic validate → T2 watcher fires `_invalidate(...)` mid-load →
  T1 finishes and unconditionally re-writes the _pre-invalidate_ tuple
  into the cache → T3 hits cache and gets the value the user already
  overwrote on disk. Silent staleness for up to one full TTL window;
  no existing test caught it because the race needed sub-millisecond
  interleaving. Fixed by adding `_config_cache_generation` (monotonic
  counter, bumped on every `_invalidate(...)`), snapshotting it under
  the lock at miss-time, and re-checking equality at write-back; on
  mismatch the write is dropped (T1's caller still gets its load
  result, but the cache stays clean and T3 re-loads). Three locks in
  `tests/test_web_ui_config.py::TestGetWebUIConfigGenerationToken`:
  the load-during-invalidate path _must not_ resurrect cache (reverse-
  locked: removing the generation check immediately fails the test
  with an explicit "stale 旧值复活" hint), `_invalidate(...)` _must_
  increment the counter, and the no-race happy path _must_ still write
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
  _did_ contain `deadline` (set in the `task_list.append(...)` block),
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
  which is wall-clock time and can move _backwards_ on NTP
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
  `_make_resubmit_response()` to the AI client _but_ did not notify
  `web_ui` to clean its `task_queue`. The AI client would then
  re-invoke `interactive_feedback`, generating a fresh `task_id` and
  POSTing it to `/api/tasks` — but the original task was still
  ACTIVE, so the new task came in PENDING. The Web UI
  `current_prompt` is bound to the active task, so the user saw the
  _old_ prompt and submitted feedback against the old `task_id`;
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
  locks the contract with five tests: timeout path _must_ call close,
  completed path _must not_ call close (would race with
  `complete_task`), 404 path _must not_ call close (no-op), close
  failure _must not_ propagate, and `CancelledError` _must_ re-raise.

- **`ConfigManager.reload()` silently lost in-process edits.** When
  `_save_timer` was queued (3-second batch debounce after a
  `cfg.set(...)`) and the file watcher fired before the timer
  did — e.g. operator edits `config.toml` in their IDE during
  a Bark URL field-edit window — `_load_config` would read the
  external bytes into `self._config`, then the lingering
  `_save_timer` would still wake up and `_pending_changes`
  would clobber the freshly-loaded external value back onto
  disk. Net effect: external edits silently lost, no warning,
  last-write-wins. Switched to _external-edit-wins_ on reload:
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
  `error.code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER'` _and_
  `killed === true` / `signal === 'SIGTERM'`. The previous
  classifier checked only `killed`/`signal` and reported
  `APPLE_SCRIPT_TIMEOUT`, sending users on a wild goose chase
  to bump `timeoutMs` (which would not help — the real fix is
  to tighten the script or raise `maxBufferBytes`). The error
  classifier in `packages/vscode/applescript-executor.ts` now
  checks `errCodeStr === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER'`
  _first_ and surfaces it as `APPLE_SCRIPT_OUTPUT_TOO_LARGE`,
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
  schemas, web*ui.py argparse help, and i18n locale files.
  Five `?? 250` / `|| 250` fallbacks in
  `static/js/multi_task.js` corrected to `?? 240` / `|| 240`
  (the actual `AUTO_RESUBMIT_TIMEOUT_DEFAULT`; 250 was the
  historical \_MAX*, not _DEFAULT_).
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
  `NotificationManager._process_event` had a hardcoded
  `as_completed(futures, timeout=15)` whose comment said
  "Bark default 10s" — but Pydantic `coerce_bark_timeout`
  accepts `[1, 300]`. With `bark_timeout = 30` (a normal
  setting on Mainland-China-to-day.app routes), `as_completed`
  raised `TimeoutError` at 15s → retry path triggered →
  original Bark future was still in-flight (HTTP request at ~25s,
  budget 30s) and returned 200 (push #1) → retry future kicked
  off, returned 200 (push #2). End result: every Bark event
  arrived twice on the user's iPhone. Window now scales as
  `bark_timeout + _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS`
  (constant default 5s; buffer absorbs thread-pool dispatch +
  httpx connection-pool warmup + first-time DNS). Locked by
  `tests/test_notification_manager.py::
TestProcessEventBarkTimeoutWindow` (6 tests covering default /
  user-widened / Pydantic max / Pydantic min / corruption-fallback
  windows + a reverse-lock on the buffer constant).
- **SSE event stream silently halted for slow / backgrounded
  EventSource clients (e.g. laptop sleep, cellular handoff,
  background browser tab).** `_SSEBus` used to `discard` a
  subscriber's queue from `_subscribers` when its backlog hit
  3/4 of capacity (48 / 64), but did nothing to signal the
  generator on the other end. Generator stayed parked on
  `q.get(timeout=25)`, drained the leftover backlog, then
  yielded `: heartbeat` forever — browser `EventSource`
  saw a healthy stream of heartbeats and never triggered
  `onerror` / auto-reconnect. From the user's perspective
  the task list silently froze; `F5` recovered (full re-fetch)
  but real-time updates were dead. `_SSEBus.emit` now injects
  a module-level sentinel `_SSE_DISCONNECT_SENTINEL` into the
  queue when discarding a subscriber (with `get_nowait` evict-
  then-retry when the queue itself was already at capacity, at
  the cost of one missing oldest event that auto-reconnect's
  `GET /api/tasks` re-fetch covers). Generator branches on
  `event is _SSE_DISCONNECT_SENTINEL` and `return` s, which
  ends the response body, browser sees EOF, EventSource auto-
  reconnects within ~3s. Locked by
  `tests/test_sse_bus_disconnect.py` (6 tests including a
  reverse-lock that the sentinel must be `object()` identity
  — using `None` / `False` / `{}` would collide with
  legitimate SSE payloads and randomly terminate streams).
- **Settings panel debounce silently dropped edits when user
  switched fields within 800ms.** Both
  `static/js/settings-manager.js` and
  `packages/vscode/webview-settings-ui.js` had a
  `debounceSaveFeedback = updates =>` whose
  `setTimeout(() => save(updates), 800)` body captured the
  most-recent `updates` argument; a `clearTimeout` followed
  by a fresh `setTimeout` would silently DISCARD the prior
  payload. Reproduce: T=0 set `frontend_countdown=60` → timer
  armed; T=300 set `resubmit_prompt="x"` → `clearTimeout`
  cancels first timer, second timer arms with only the second
  field; T=1100 `saveFeedbackConfig({resubmit_prompt:"x"})`
  fires, `frontend_countdown=60` is gone forever with zero
  user-visible error toast. Fix accumulates updates into a
  `pendingUpdates` buffer (`Object.assign(buf||{},
updates||{})`); the timer drains the buffer as a single
  merged POST. Web ↔ VSCode parity is locked by
  `tests/test_debounce_save_feedback_accumulates.py` (3 tests
  including a bidirectional parity gate that fails when only
  one mirror is fixed).
- **Concurrent notification retry thundering-herd.**
  `NotificationManager._schedule_retry` previously used a
  fixed `retry_delay` (default 2s, configurable to
  `[0, 60]s`) so multiple in-flight Bark / Web / System
  sends failing within a single ms would re-fire retries in
  exact lock-step. Spike load on the upstream + correlated
  re-failure risk. Fix introduces
  `_RETRY_DELAY_JITTER_RATIO = 0.5`; effective delay is now
  `base_delay + random.uniform(0, base_delay * 0.5)`, with a
  fast-path preserving `delay == 0` semantics exactly. New
  `tests/test_notification_manager.py::TestScheduleRetryJitter`
  (5 tests) locks the lower bound (delay ≥ base), the upper
  bound (≤ base \* 1.5), the zero fast-path, and a reverse-lock
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
  one `通知发送失败，将在 2s 后重试` line leak to the terminal on the
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
    told a _narrower_ allowed range than the binary actually
    enforces — same surprise direction as not knowing
    `external_base_url` exists). Companion test
    (`tests/test_config_docs_range_parity.py`) prevents the
    drift from re-emerging. Pure docs + new test patch — no
    runtime / `_clamp_int` change.
- **`docs/security/AUDIT_2026-05-04.md` no longer carries a
  `<TBD>` placeholder for the remediation commit hash.**
  The audit document opened with `STATUS: REMEDIATED (runtime
CVEs cleared 17 → 0 on commit \`<TBD>\`…)`since the
upgrade landed in`95e4151` (`🔒 chore(deps): security wave
  - production CVE exposure 17 -> 0`); a leftover
`<TBD>` token in a security artefact is exactly the kind
    of stale string a future operator would mis-interpret as
    "remediation pending". Replaced with a deep-link to the
    fix commit on GitHub plus the commit subject line for
    zero-context audit trails. Pure documentation patch.

### Tests

- **Flaky `test_cache_performance` rewritten as deterministic
  behaviour-level invariant locks for
  `notification_manager.refresh_config_from_file`.** The
  original test asserted `cache_time <= no_cache_time * 1.5`
  using `time.time()` deltas over 50 iterations (typical
  1-10 ms total per batch). Wall-clock comparisons at sub-100ms
  granularity are inherently unreliable: kernel preemption, GC
  pauses on the parallel pytest worker, JIT warm-up order, and
  cgroup-shared CPU on CI all jitter several × the measurement
  window. Real failure mode observed: `cache=10.8ms vs no_cache=1.7ms`
  (cache _slower_ than no-cache by 6×) when the test ran late
  in a 2400-test batch — the warm-up `force=True` had pre-warmed
  code paths and disk caches more than the cache-hit branch's
  later mtime check could ever benefit from. Replaced with two
  behaviour-level locks: (1)
  `test_cache_behavior_skips_get_section_on_unchanged_mtime`
  patches `notification_manager.get_config` so
  `mock_cfg.config_file.stat()` returns a fixed `st_mtime`,
  runs 50 `force=True` iterations and asserts
  `mock_cfg.get_section.call_count == 50` (force always
  reloads), then 50 `force=False` iterations after `reset_mock()`
  and asserts `call_count == 0` (cache-hit short-circuit must
  skip the toml reload entirely); (2)
  `test_cache_invalidation_on_mtime_change` runs the same
  scaffold with a _newer_ `st_mtime`, asserting `get_section`
  is called exactly once (reverse-lock against future "let's
  cache more aggressively" refactors that would silently leave
  users on stale config until process restart). Locks the
  _real_ invariant the cache provides — "skip IO when mtime is
  unchanged" — rather than the cache's downstream speed
  property. Test count climbs 2465 → 2467; production code
  unchanged.
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
  contract that the _generated_ `docs/api/index.md` and
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
must equal the actual `(min, max)`carried by the
matching`BeforeValidator(\_clamp_int(...))`in`shared_types.SECTION_MODELS`. Uses `**closure**`introspection so adding/removing a numeric field does
not require touching the test, and a self-check pins
several known anchors (e.g.`port=[1, 65535]`) so
future `\_clamp_int` refactors cannot silently weaken
  the assertion to vacuous truth. 3 new tests; 2249 → 2252
  total passing.
- **New regression gate:
  `tests/test_config_docs_parity.py`** locks the
  contract that every key declared in
  `config.toml.default` must appear in _both_
  `docs/configuration.md` and
  `docs/configuration.zh-CN.md` as a backticked entry in
  the matching `### \`<section>\``table — and vice versa
(no orphan documented keys). Complements the existing`tests/test_config_defaults_consistency.py`which guards
the runtime default dict ↔ TOML template invariant.
5 new tests; 2244 → 2249 total passing. The TOML / doc
parsers each have a self-check so refactoring the regex
later cannot silently weaken the gate (e.g., dropping a
section it never noticed). Closes the structural gap
that allowed the`[notification]::debug`/`[web_ui]::language`/`[mdns]::enabled` doc drift to ship in the first place.
- **`tests/test_i18n_fuzz_parity.py` extended with a Round-11
  `EXT_SEED=0xFACECAFE` corpus (100 samples) covering ICU-
  standard corner cases the original 200-sample fuzz never
  exercised:** `=N` exact-match branch in
  `_selectPluralOption` (line 410, implemented but no
  project locale used it → silently untested), empty plural
  arm body `one {}`, multi-codepoint Unicode (4-byte BMP+
  emoji `🚀`, ZWJ sequences `👨‍👩‍👧`, regional
  indicator flag `🇨🇳`, variation-selector + ZWJ
  `🏳️‍🌈`, combining marks `a\u0301`), and BiDi
  controls (LRM/RLM/LRE/PDF). Each new sample is forced
  through one of {`exact` | `empty_arm` | `emoji` |
  `bidi`} flavors so the new code paths are guaranteed
  reachable rather than randomly skipped; `n*` params land
  on 0/1 with 70% probability so `=0`/`=1` arms actually
  fire. All 102 new templates are byte-identical Web ↔
  VSCode (`static/js/i18n.js` ↔ `packages/vscode/i18n.js`)
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
- \*\*PR template's "Local verification" checklist now lists
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
  - `--lang zh-CN` followed by `git diff docs/api/index.md
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
    `import pdb; pdb.set_trace()` / `pdb.run(...)` slipping into
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
  1. `i18n.pseudoLocale` _(experimental)_ setting documented for
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
