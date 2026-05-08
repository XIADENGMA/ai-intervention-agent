# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Earlier history (versions ≤ 1.5.19) lives in the git log only.

## [Unreleased]

### Fixed

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
  the *parsed value* of the docs cell against the parsed value in
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
     + `n`), with an inline note clarifying that the leading `\n`
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
  ``<section>.<key>`` references and fails if the pair is not declared
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
  ``section.key`` references — that surface had zero CI coverage. So
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
     ``<section>.<key>`` whose `section` is one of the live top-level
     TOML sections, and asserts the `key` is declared there. On
     mismatch the failure message points to the section that *actually*
     owns the key — so the next contributor who writes
     ``feedback.bind_interface`` gets _"`bind_interface` is declared
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
    bug that was perfectly cancelled out by the *first* bug
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
     the pre-R76 root path:
     - `README.md:3` and `README.zh-CN.md:3` — repo logo `<img src>`
       (loaded by GitHub from the relative path → 404 on landing
       page until refreshed)
     - `scripts/README.md` and `scripts/generate_pwa_icons.py`
       module docstring — "Run after editing `icons/icon.svg`" mis-
       documents the contributor workflow
     - `src/ai_intervention_agent/icons/icon-maskable.svg` SVG
       comment — references its sibling at the wrong path
     - `tests/test_pwa_icon_assets.py` docstrings (3 sites)
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
  header → config_manager → DEFAULT_LANG) and the format-error
  branch in `get_locale_message`. The
  `test_detect_lang_unknown_accept_language_normalizes_to_default`
  case in particular captures a non-obvious property of the
  dispatch tree: `normalize_lang` always returns a value in
  `SUPPORTED_LANGS`, so unsupported headers like `fr-FR` are
  mapped to `en` and the config branch is _never_ consulted —
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
