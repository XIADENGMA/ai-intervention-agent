# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Earlier history (versions ≤ 1.5.19) lives in the git log only.

## [Unreleased]

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

### Fixed

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
