# Lessons learned — R63 → R70 cycle

> Internal post-mortem for the v1.5.45 batch of fixes. Mostly relevant
> to contributors who write CSS, JavaScript, or MCP-tool schemas in
> this repo. Cross-link from `CHANGELOG.md` for the bullet version.

This batch shipped seven `R` numbers (R63a / R63b / R63c / R64 / R65 /
R66 / R67) that look unrelated on the surface — Bark sentinel,
predefined-options defaults, server build info, light-mode button text,
iOS-blue leakage, brand-color guardrail, docs polish — but trace back
to a small handful of recurring root causes. We document them here so
the same class of bug does not return in v1.5.46+.

## Root cause 1 — "dark-first" CSS without a light counterpart

### What happened

The default theme was authored as a single-source dark palette using
hardcoded `rgba(0, 122, 255, X)` (iOS system blue) for accent / focus
/ active / drag-overlay states. The light-mode override layer
(`[data-theme='light']`) was added later for individual components, so
**nine** components never received a paired override and continued
emitting iOS-blue inside the otherwise warm-orange (Anthropic Orange,
`#d97757`) light palette.

The first user-visible symptom was tracked as R64 (the four "danger"
button labels reading dark on dark in light mode). The systemic
investigation surfaced seven more components in R65 (`focus`, `:active`,
`.description`, `.textarea-drag-over`, `.drag-overlay-content`,
`.setting-input:focus`, `.settings-btn:focus`).

### How we fixed it

- **R64** — `[data-theme='light'] .btn span { color: inherit }` plus
  paired `:hover` overrides with orange shadow.
- **R65** — seven targeted `[data-theme='light']` blocks inside
  `static/css/main.css`, all using the existing
  `var(--accent-primary)` / `rgba(217, 119, 87, X)` orange palette.
- **R65 tests** — `tests/test_light_mode_ios_blue_leakage_r65.py`
  (11 assertions) walks each override and asserts both
  positive (orange present) and negative (iOS-blue absent), so the
  override survives any future minify / lint pass.

### What we changed structurally

- **R66** — `scripts/check_brand_color_consistency.py` is a hand-rolled
  Python guardrail that strips `/* */` comments first, then counts
  literal `rgba(0, 122, 255, X)` occurrences. The current baseline is
  `34` (the count of intentional dark-mode-source rules — the comments
  documenting the migration are stripped before counting). The pre-
  commit hook fails CI if the count grows; if the count shrinks
  (e.g. another light-mode override is added), the script emits a
  green "baseline can be lowered" hint and **does not fail** —
  encouraging continued migration without forcing a config flip.

### What contributors should do next time

1. **Every new `<button>` / `<input>` / `<textarea>` interactive
   variant added to `templates/web_ui.html` must own a paired
   `[data-theme='light']` block** in `main.css` if the dark-mode
   default uses any of `var(--accent-blue)`, `rgba(0, 122, 255, X)`,
   or any other hardcoded blue.
2. Run `uv run python scripts/check_brand_color_consistency.py
   static/css/main.css` locally before commit. If the number went up,
   migrate the new rule too; if it went down, **lower the baseline**
   in `DEFAULT_BASELINE` so the guardrail tightens.
3. Add a test under `tests/test_*_light_mode*.py` that asserts both
   the positive (orange) and negative (no blue) override exists for
   the new component. R65's test file is the template.

## Root cause 2 — MCP tool description encodes capabilities the schema does not

### What happened

`server_feedback.interactive_feedback`'s `predefined_options`
parameter accepts both `list[str]` and `list[dict]` shapes, where the
dict shape lets the LLM mark some options as default-checked
(`{"label": "...", "default": true}`). The runtime supported it for
months. The MCP tool description, however, only documented the simple
`list[str]` form — and the LLM (Cursor / Claude Desktop / ChatGPT
Desktop) only sees the description. **Result: the feature existed but
no LLM ever used it**, leaving multi-select panels without their
recommended defaults pre-checked.

### How we fixed it

- **R63b** — rewrote the `predefined_options` Field description to
  document both shapes, added a complete worked example, and
  introduced an explicit second parameter `predefined_options_defaults:
  list | None = None` so even LLMs that only parse the parameter list
  (not the description) see the capability. The runtime merges the
  two forms.
- **R63b tests** — `tests/test_predefined_options_defaults_in_signature_r63b.py`
  (10 assertions) freezes the signature shape, the description text,
  and the merge logic so any future schema migration triggers a
  red-bar instead of silently regressing the LLM-facing contract.

### What contributors should do next time

1. **The MCP tool description is the contract** — if a parameter
   supports a richer shape than the type hint conveys, document it in
   the `Field(description=...)` text **and** add a test that asserts
   the description string contains the keyword the LLM will see.
2. When adding a `default=` / `recommended=` flag to any user-facing
   interactive element, search for `interactive_feedback` callers in
   the test corpus to confirm the LLM-side shape is still consumed.
3. If you change a `Field(description=...)` for an MCP tool, **bump
   the test that asserts the description content** in the same commit
   — the LLM only relearns the schema on tool re-discovery, so a
   silent description drift can leave older LLM sessions stuck on the
   pre-migration contract.

## Root cause 3 — frontend deep-link handler can't tell "real notification" from "test notification"

### What happened

`web_ui_routes/notification.py::test_bark_notification` POST'ed a
synthetic Bark payload with `task_id=test-task-id` so operators could
verify their Bark URL template worked. The frontend
`getDeepLinkedTaskIdFromUrl()` then dutifully tried to deep-link to
that nonexistent task, throwing a "task not found" error and a
confused operator.

### How we fixed it

- **R63a** — backend appends `aiia_test=1` query param to the test
  Bark URL; frontend `getDeepLinkedTaskIdFromUrl()` recognises the
  sentinel, skips the deep-link attempt, and surfaces a friendly
  "Bark connection verified" toast instead.
- **R63a tests** — `tests/test_test_bark_aiia_test_sentinel_r63a.py`
  (8 assertions) covers both ends: backend appends the sentinel even
  when user-supplied template already has query params; frontend
  honours the sentinel even when other params are present.

### What contributors should do next time

1. Any future "test ping" endpoint (test-desktop-notification,
   test-tray-notification, test-N-notification) **must** carry an
   `aiia_test=1` sentinel and the frontend dispatcher **must**
   short-circuit on it before reaching the production deep-link path.
2. Document each new sentinel in `docs/troubleshooting.md` so
   operators who see `aiia_test=1` in their browser URL bar
   understand what it is.

## Root cause 4 — diagnostic build metadata was missing

### What happened

When users hit a regression and reported it, maintainers had no way
to know which exact commit / branch / dirty-state they were running.
The MCP `aiia://server/info` resource exposed version, hostname,
config — but nothing about the deployed binary.

### How we fixed it

- **R63** — `server.py::_resolve_build_info()` runs `git rev-parse
  HEAD` / `git rev-parse --abbrev-ref HEAD` / `git status --porcelain`
  with a 1-second timeout, lazy-caches the result thread-safely
  (`_BUILD_INFO_CACHE_LOCK`), and gracefully degrades to
  `{commit: None, branch: None, dirty: None}` if `git` is unavailable
  (e.g. inside a container with `.git` excluded). The result is
  exposed under `server_info_resource()["build"]`.
- **R63 tests** — `tests/test_server_info_build_block_r63.py`
  (16 assertions) covers happy-path, no-`git`-binary, no-`.git`-dir,
  dirty-tree, timeout, cache hit, and concurrent invocation.

### What contributors should do next time

1. Treat the `build` block as the **first thing** to ask for in any
   bug report (`mcp__ai-intervention-agent__resource(aiia://server/info)`
   then `["build"]["commit"]`).
2. If you add other diagnostic blocks (e.g. `runtime`, `gpu`,
   `proxy`), follow the same pattern: lazy-cached, timeout-protected,
   gracefully-degraded, locked.

## Root cause 5 — Prettier formatting drift across the frontend / docs / VSCode tail

### What happened

The repo adopted Prettier defaults (`singleQuote: false`,
`semi: true`, `trailingComma: "all"`, `arrowParens: "always"`,
`printWidth: 80`) at some point during the v1.5.x cycle. Several
hand-written files were never reformatted because no functional commit
touched them, leaving the working tree noisy and obscuring future
diffs (the user noticed first when the R63a Bark-sentinel diff
threatened to balloon to 1820 lines because `multi_task.js` had
massive uncommitted prettier drift on top).

### How we fixed it

- **R63c** — `static/js/multi_task.js` (1820 lines) reformatted in a
  single pure-style commit, decoupled from R63a's functional change.
- **R68** — `packages/vscode/extension.ts` (1166),
  `packages/vscode/webview-settings-ui.js` (1006),
  `packages/vscode/webview.ts` (3),
  `scripts/package_vscode_vsix.mjs` (273) — same pattern, four files
  in one commit because they share the VSCode-extension scope.
- **R69** — `CHANGELOG.md` (94), `docs/configuration.md` (104),
  `docs/configuration.zh-CN.md` (104), `docs/mcp_tools.md` (28) —
  markdown table-cell padding and `` `code` `` simplification, one
  commit for the docs scope.
- **R70** — `static/js/settings-manager.js`, `templates/web_ui.html`,
  plus the precompressed `.gz` / `.br` artefacts that fell out of
  sync after R63c (intentionally deferred to a single resync commit
  to avoid a `.gz`/`.br` diff in every prettier commit).

### What contributors should do next time

1. **Run `npx prettier --check .` before committing any non-Python
   change**. If it reports drift, write a stylistic-only commit (`chore`
   or `:art: style(...)`) **first**, then write the functional commit
   on top.
2. Never let a stylistic reformat ride along with a functional fix.
   "Fat commits" make it nearly impossible to bisect a regression
   to its real cause and we hit this exact failure mode mid-cycle
   (R63a was committed with the full `multi_task.js` rewrite, then
   undone via `git reset --soft HEAD~1` and re-split into R63a + R63c).
3. The precompressed `static/**/*.gz` / `*.br` artefacts are
   committed for Flask-Compress's `WHITELISTED_PRECOMPRESSED` fast
   path. Regenerate via `uv run python scripts/precompress_static.py`
   in **the same commit** as the source change, or in a single
   follow-up "resync" commit if you grouped multiple stylistic
   changes — never stale.

## Root cause 6 — Dependabot major-bump PRs blindly merged would have broken VSCode tests

### What happened

Six Dependabot PRs (eslint v10, marked v18, @types/node v25,
setup-uv v8, actions/checkout v6, actions/setup-python v6) were sitting
open. Without CI inspection, the temptation is to bulk-merge and
"keep deps fresh". Inspecting the actual CI matrix on each PR
revealed:

- `chore(deps-npm): bump eslint from 9.39.2 to 10.3.0`: VSCode tests
  **fail** on both macOS and Ubuntu (eslint v10 needs flat-config
  migration we have not done).
- `chore(deps-npm): bump marked from 17.0.4 to 18.0.3`: VSCode tests
  **fail** (marked v18 restructured the token tree, our webview
  markdown adapter needs a rewrite).
- `chore(deps-npm): bump @types/node from 22.19.3 to 25.6.0`: all
  matrix jobs **pass** — pure dev-time type bump, safe.
- `chore(ci): bump astral-sh/setup-uv from 7.6.0 to 8.1.0`: all
  matrix jobs **pass** — but our local OAuth token lacks `workflow`
  scope, so `gh pr merge` was rejected; deferred to manual UI merge.
- `chore(ci): bump actions/checkout from 4 to 6`: **CONFLICTING**
  (main already on v5).
- `chore(ci): bump actions/setup-python from 5 to 6`: **CONFLICTING**
  (main already on v5).

### How we fixed it

- **#25 (@types/node)** — auto-merged with delete-branch.
- **#36 (eslint v10), #35 (marked v18)** — closed with explicit
  "VSCode tests fail; deferred to manual flat-config / token-tree
  migration" comment.
- **#4 (checkout v6), #3 (setup-python v6)** — closed with explicit
  "main already ahead; conflicts confirm staleness" comment.
- **#31 (setup-uv v8)** — left OPEN with a TODO note for the
  maintainer to merge via the GitHub UI (CLI cannot merge workflow
  files without `workflow` token scope).

### What contributors should do next time

1. **Always run `gh pr checks <NUM>` before merging a Dependabot
   major-bump PR.** A green "MERGEABLE" status from `gh pr list` only
   covers git-level conflicts, not CI.
2. For Dependabot major bumps that fail CI, **close with rationale**.
   Dependabot will re-open with the next minor bump (which may have
   the breaking changes either dropped or made opt-in).
3. The `Dependency Review` action will fail on every PR until the
   GitHub repository's "Dependency graph" feature is enabled in
   Settings → Code security → "Dependency graph". This is documented
   under `docs/troubleshooting.md` §10 — point Dependabot-confused
   users there before they panic about phantom CVEs.

## Root cause 7 — README architecture diagram understated the implementation

### What happened

The Mermaid `architecture-beta` diagram in `README.md` listed only
the headline modules (`server.py`, `web_ui.py`, `task_queue.py`,
`config_manager.py`, etc.). Internal helpers (`state_machine.py`,
`web_ui_mdns.py`, `web_ui_security.py`, `task_queue_singleton.py`,
`server_feedback.py`, `enhanced_logging.py`, `protocol.py`) were
implementation-time additions that never made it into the diagram —
so a new contributor reading just the diagram would think the codebase
is half its actual size.

### How we fixed it

- **R67** — added a blockquote immediately after the Mermaid block,
  explicitly enumerating the internal helpers and linking to
  `docs/api/index.md` (English) / `docs/api.zh-CN/index.md` (Chinese)
  for the full auto-generated API reference. Mermaid block was
  intentionally **not** modified — diagrams should stay readable, the
  blockquote carries the long-tail completeness.
- **R67 (continued)** — added `docs/troubleshooting.md` §10 covering
  the `Dependency Review` failure mode (see Root cause 6), so future
  Dependabot-confused users find the answer without re-asking.

### What contributors should do next time

1. **When you add a new top-level module to the repo**, ask:
   - Does it appear in the README architecture Mermaid block? If
     yes, add the box.
   - Does it appear in the `docs/README.md` "Contributors" list of
     auto-generated API surface? If yes, add it there too.
   - If it's an internal helper that should not clutter the diagram,
     add it to the README blockquote (R67's pattern).
2. **Re-run `uv run python scripts/generate_docs.py` after adding any
   new public Python surface**, then `make docs-check` (or
   `uv run python scripts/generate_docs.py --check`) to confirm
   no auto-gen drift.

## Cross-cutting takeaways

- **Tests as the contract layer.** Every R-numbered fix in this batch
  shipped with a dedicated regression test file (`test_*_<R>.py` /
  `test_*_<R>_<scope>.py`). When the user-visible bug is in CSS, the
  test asserts CSS rules exist (`grep`-style) — not pixel-perfect
  rendering, which would be flaky. When the bug is in an MCP schema
  description, the test asserts substring presence in the description
  string. Pick the lowest-fidelity assertion that still detects the
  regression class.
- **Atomic commits + commit-message discipline.** The `:art:` /
  `:lipstick:` / `:sparkles:` / `:books:` / `:shield:` gitmoji prefix
  encodes the change class so `git log --oneline` is grep-able for
  reviewer attention (style vs UI vs functional vs docs vs guardrail).
  Long commit-message bodies follow the **Why / What this commit is
  / What this commit is NOT / Verification** template — the "is NOT"
  section catches reviewer assumptions before they bite.
- **Guardrails over exhortation.** Wherever we found a class of bug
  twice (iOS-blue migration; prettier drift), we shipped a guardrail
  (R66 brand-color script + pre-commit hook; the prettier-only
  commits make `npx prettier --check .` clean) instead of writing a
  CONTRIBUTING note that nobody would read.
