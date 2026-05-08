# Lessons learned — R71 → R82 cycle

> Internal post-mortem for the v1.6.0 batch (R71 → R82). Reviewers
> auditing the next release should read this alongside
> [`lessons-learned-r60s.md`](lessons-learned-r60s.md) and
> [`security-triage-r72.md`](security-triage-r72.md). Cross-link from
> `CHANGELOG.md` for the bullet version.

This batch shipped twelve base `R` numbers (eighteen counting the
b/c/d/-D variants) between the v1.5.45 tag and the v1.6.0 release:
R71 (post-mortem prep) · R72 / R72-D (CodeQL sweep) · R73 (governance
docs relocation) · R74 / R74b / R74c / R74d (zero-warning sprint) ·
R75 (`ruff LOG` family rollout) · R76 / R76b (`src/` layout +
config-template prune) · R77 (cross-MCP compat aliases) · R78 / R79
(coverage uplift) · R80 (link-rot guardrail) · R80b (`CHANGELOG`
backfill) · R81 (this post-mortem) · R82 (coverage data-file
relocation).

The pattern this cycle is structurally different from R63 → R70:
that batch was driven by user-visible regressions (light-mode iOS
blue, missing default-checked options, deep-link confusion). This
batch is driven by **silent decay** — security alerts piling up,
warnings the team learned to ignore, link rot inside `.github/`
docs, a flat layout that grew past its useful lifetime. We document
the lessons here so the same class of decay does not return in
v1.6.1+.

## Root cause 1 — Security-tool noise creates false confidence; "fix all" is not triage

### What happened

GitHub code-scanning had **54 open alerts** when this cycle started.
The headline number is misleading: most were CodeQL `py/log-injection`
findings on stdlib `logging` callers (15), plus a `py/stack-trace-
exposure` (1), plus a `py/csrf-protection-disabled` (1) on a locale
write endpoint. The remainder split into two camps — **legitimate
false positives** that needed dismissal-with-justification, and
**OpenSSF Scorecard governance items** that are not code defects at
all (token permissions, branch protection, signed commits).

Bulk-fixing the log-injection alerts naively (e.g. by sprinkling
`str(x).replace("\n", "")` everywhere) would have produced 15 noisy
diffs and missed the real defect: stdlib `logging.getLogger(__name__)`
callers across five modules never went through Loguru's
`_sanitize_and_escape` patcher because they had `propagate=True` but
no root handler that ran the sanitizer.

### How we fixed it

- **R72-A** — `enhanced_logging.py::_install_root_intercept_once()`
  attaches a single `InterceptHandler` to `logging.getLogger()` (root).
  Every stdlib logger now bubbles up to root → InterceptHandler →
  Loguru patcher → `_sanitize_and_escape` (CRLF / null-byte escape) +
  `LogSanitizer` (R54-B PII redaction). One module change closes 15
  CodeQL alerts atomically.
- **R72-B** — `web_ui_routes/system.py::open_config_file` was leaking
  the full `subprocess.CalledProcessError` traceback to the HTTP
  response on Windows. Replaced with a generic 500 + structured log.
- **R72-C** (23 dismissals) and **R72-D** (9 dismissals + 1 locale
  CSRF fix) walked through every remaining alert with `gh api ... -X
  PATCH state=dismissed reason=... comment=...`, leaving an audit
  trail in `docs/security-triage-r72.md`.
- **R72 tests** — `tests/test_root_logger_intercept_r72a.py`
  (14 assertions) covers idempotency, repeat `importlib.reload`,
  CRLF / null-byte escaping, PII redaction, no double-emit on managed
  loggers, and stdlib logger never raises after install.

### What contributors should do next time

1. **Read `docs/security-triage-r72.md` before opening alerts in the
   GitHub UI.** Every disposition has a justification; do not
   re-dismiss / re-fix what is already covered.
2. **Treat code-scanning alerts as a triage queue, not a TODO list.**
   For each alert, decide one of: (a) fix-in-code with a regression
   test, (b) dismiss-as-FP with a written justification (the GitHub
   `comment` field is the audit trail), (c) won't-fix with rationale,
   (d) defer-to-policy (Scorecard governance items live in repo
   settings, not source code).
3. **Prefer one structural fix over N pointwise fixes.** If five
   modules trip the same rule, look for a single chokepoint
   (interceptor, decorator, base class, lint guardrail) before
   patching each call site. R72-A's `_install_root_intercept_once`
   is the template.
4. **CodeQL re-runs on every default-branch push.** A fix landing on
   `main` will auto-resolve the alert without needing manual
   dismissal — but only if the rule's exact source / sink lines no
   longer match. If you fix the *behaviour* but not the *pattern*,
   the alert stays open. R72-A worked because the new
   InterceptHandler made the stdlib loggers go through the same
   sanitizer; the f-string interpolation lines were unchanged but
   no longer reachable as injection sinks.

## Root cause 2 — Governance docs at the repo root crowd the README; GitHub expects `.github/`

### What happened

`CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, and
`PULL_REQUEST_TEMPLATE.md` lived at the repo root historically. The
root directory listing on GitHub's repo home shows files
alphabetically before the README preview, so a new visitor would
scroll past four governance files (and the equally-alphabetical
`AGENTS.md`, `CHANGELOG.md`, `CLAUDE.md`, `LICENSE`, `TODO.md`)
before reaching the actual project description. The user explicitly
flagged this: "现在主目录下面有过多的代码文件和文档文件了"
("the main directory has too many code and doc files now").

GitHub itself surfaces governance docs from `.github/` exactly as
prominently as from the root — the "Code of Conduct", "Contributing",
"Security policy" tabs in the right-hand sidebar resolve from
`<repo>/.github/<NAME>.md` first, falling back to the root.

### How we fixed it

- **R73** — `git mv` of four governance docs into `.github/`:
  - `CONTRIBUTING.md` → `.github/CONTRIBUTING.md`
  - `SECURITY.md` → `.github/SECURITY.md`
  - `SUPPORT.md` → `.github/SUPPORT.md`
  - `PULL_REQUEST_TEMPLATE.md` → `.github/PULL_REQUEST_TEMPLATE.md`
- **R73 follow-up** — every cross-link in `README.md`, `CHANGELOG.md`,
  `docs/README.md`, and the moved docs themselves was rewritten to
  the new relative path (`.github/SECURITY.md` → `../docs/...` from
  inside `.github/`).

### What contributors should do next time

1. **Default to `.github/` for governance docs**, including
   `CODE_OF_CONDUCT.md`, `FUNDING.yml`, `ISSUE_TEMPLATE/`, and any
   `*.md` that GitHub recognises in the sidebar. The repo root
   should hold project-defining files (`README.md`, `LICENSE`,
   `CHANGELOG.md`, `pyproject.toml`, `package.json`) and as little
   else as possible.
2. **When relocating, update `README.md` cross-links *and*
   `docs/README.md` *and* in-doc back-references in the same
   commit.** R80 caught 14 broken links inside `.github/` because
   the relocation pre-dated the link-rot guardrail and nobody had
   re-tested the relative paths after the `git mv`.
3. **Run the link-rot test (`tests/test_docs_links_no_rot.py`) before
   any `git mv` of a `.md` file.** It is fast (<1 s) and rejects
   obviously-broken paths before the diff lands.

## Root cause 3 — Warnings accumulate quietly until a "zero-warning" sprint forces a reckoning

### What happened

Across the v1.5.43 → v1.5.45 cycle the project accumulated:

- 2 `ty` type diagnostics on legitimate optional-import patterns
  (`mDNS` / `notification_manager` lazy imports) that the type-checker
  flagged as "possibly unbound" because the `try/except ImportError`
  branch leaves the name undefined on failure.
- ~30 prettier "drift" findings on docstring quote style (single
  vs double) inside VSCode webview tests.
- 4 `ruff` `LOG` family findings on root-logger usage and `exc_info`
  anti-patterns (`logger.error(f"failed: {e}")` instead of
  `logger.exception("failed")`).
- A `package-lock.json` `@types/node` constraint mismatch that
  Dependabot's auto-merge had landed but our local `npm ci` did not
  re-resolve.
- Several test files used `# type: narrowing` magic comments that
  modern `ty` no longer recognises, causing benign-but-noisy
  diagnostics.

Each of these passed CI individually because the relevant gate was
either advisory (prettier check warnings, not failures) or scoped to
a different module. The warnings only became visible when running
the full local `ci_gate.py` end-to-end and reading the output line
by line.

### How we fixed it

This was a deliberate **zero-warning sprint** split into atomic
commits:

- **R74** — `ai_intervention_agent/web_ui_security.py` and
  `service_manager.py`: type-narrow the optional imports with
  `cast()` plus a runtime `_AVAILABLE` flag, satisfying `ty` without
  changing behaviour. Same commit also regenerates drifted API docs.
- **R74b** — `tests/test_vscode_*.py`: rewrite single-quoted regex
  anchors to double-quoted to be prettier-stable.
- **R74c** — strip 2 `# type: narrowing` magic comments and rewrite
  as plain prose (the `cast()` / `assert isinstance(...)` already
  does the actual narrowing).
- **R74d** — `package-lock.json` regenerated with `npm ci` so the
  `@types/node` resolution matches the manifest constraint.
- **R75** — `ruff` `LOG` family: enable `LOG001 / LOG002 / LOG004 /
  LOG009 / LOG014` across the project, fix the 4 surviving
  violations (root-logger callers + `exc_info=` anti-patterns),
  add the rule family to `pyproject.toml`'s explicit allowlist.

### What contributors should do next time

1. **Pre-commit must surface every gate, including advisory ones.**
   If `prettier --check` warns but exits 0, the warning gets ignored
   for weeks. Either upgrade the gate to fail on drift or pipe the
   warning into `make verify-warnings` so a human sees it.
2. **Type-checker complaints on optional imports usually mean the
   `try/except ImportError` block is missing a paired `cast()` or
   `# type: ignore[unused-ignore]` on the *successful* import line.**
   See `web_ui_security.py` for the worked pattern.
3. **`ruff` rule families ship one rule at a time.** If a new family
   (`LOG`, `BLE`, `TRY`, `RUF`) lands a useful rule, **enable the
   whole family** and triage the violations — it is cheaper than
   waiting for individual rules to land in v1.x.x.
4. **One commit per warning class.** R74 / R74b / R74c / R74d / R75
   are five commits because each addresses a different gate. This
   makes the rollback target obvious if any of them turns out to
   regress something subtle.

## Root cause 4 — Flat-layout import chaos eventually forces a big-bang reorganisation; lockstep verification is the only safe path

### What happened

Up through v1.5.45, every Python module lived at the repo root
(`server.py`, `web_ui.py`, `task_queue.py`, `notification_manager.py`,
…). Together with templates, static assets, icons, and sounds also
sitting at the root, the top-level `ls` showed **80+ entries**, and
new contributors could not tell at a glance which files were
"public surface" vs "internal helper" vs "template" vs "build
artefact".

The user surfaced this directly: 既要更好的项目文件组织方式，又
不能让一切功能因路径修改而出错 ("better project file organisation
without breaking any feature due to path changes"). The PyPA gold-
standard answer is the `src/<package>/` layout, but the migration
touches **everything**:

- 24 Python modules → `src/ai_intervention_agent/`
- 4 asset directories (`templates/`, `static/`, `icons/`, `sounds/`)
  → `src/ai_intervention_agent/<name>/` so they ship inside the
  installable wheel
- **1074** import statements across the test corpus (mostly
  `import server` → `import ai_intervention_agent.server`)
- **879** `unittest.mock.patch("module.path")` strings (each one a
  hardcoded module path that must be rewritten)
- **119** hardcoded `"static/..."` / `"templates/..."` strings
  inside route handlers, scripts, and tests
- `pyproject.toml` `[tool.hatch.build.targets.wheel]` configuration
- `scripts/generate_docs.py` output directory paths
- `MANIFEST.in` if any (we did not need it after src/-layout)
- the `config.jsonc.default` template file the user asked to remove
  in the same review pass (R76b)

Touching any one of these in isolation would leave an inconsistent
state that passes a single test file but breaks the next one. The
only safe migration strategy is **lockstep**: every category gets
rewritten in the same commit, and `ci_gate.py --check` is run
end-to-end before the commit lands.

### How we fixed it

- **R76** — single `:building_construction: refactor(layout-r76):`
  commit. The body lists every category of change with a count
  ("24 modules", "1074 imports", "879 mock patches", "119
  hardcoded paths"). Verification block enumerates what the
  `ci_gate.py` run covered: `ruff check`, `ty`, `pytest -p no:cacheprovider`
  (3828 tests), `coverage`, locale parity, red-team-i18n
  runtime, docs drift, link rot.
- **R76b** — separate commit for the `config.jsonc.default`
  removal. The user explicitly asked for "C 删除、同步调整
  references" (delete + sync references); we did exactly that
  rather than fold it into R76 (which would have broken the
  refactor's atomicity).
- **R76 tests** — every existing test continued to pass with no
  edits beyond the import-path rewrite. The migration shipped
  zero new tests because the existing suite already covered the
  invariants we cared about (asset reachability, MCP tool
  surface, route registration). Adding new tests would have
  conflated "did the move work?" with "did the new behaviour
  work?" and we wanted the migration to be behaviour-neutral.

### What contributors should do next time

1. **Schedule big-bang reorganisations as their own R-number
   commit, not a side effect of a feature.** R76 is the entire
   commit for that layout migration; the user got a clean
   "atomic refactor" diff to review, not a 40-file mixed bag.
2. **Lockstep checklist for any "rename a top-level module"
   change.** In order:
   - Update the module path itself.
   - Rewrite every `import` statement (production + test +
     scripts).
   - Rewrite every `unittest.mock.patch("...")` string (the
     static analyser does not catch these — they are runtime
     strings).
   - Rewrite every hardcoded module-path literal inside JSON /
     YAML / TOML configs (e.g. `pyproject.toml`'s
     `[project.scripts]`, `coverage.run.source`).
   - Rewrite every hardcoded asset path (`"static/..."`,
     `"templates/..."`, `"icons/..."`, `"sounds/..."`).
   - Regenerate auto-generated docs (`scripts/generate_docs.py`).
   - Run the full `ci_gate.py` end-to-end before commit.
3. **If the migration removes a config-template file**, search
   the repo for every `references` to the file and update them
   in the same commit (R76b's pattern).
4. **The `src/<package>/` layout is the PyPA-recommended default
   for new Python projects.** Adopt it from day one to avoid an
   R76-style migration later.

## Root cause 5 — MCP tool schemas are external contracts; older clients pin to the old shape

### What happened

A live deployment running v1.5.36 (≈ 8 commits behind `main`) sent
this `interactive_feedback` invocation:

```json
{
  "message": "...",
  "predefined_options_defaults": [...],
  "timeout_seconds": 600,
  "task_id": "src-layout-resources-decision-r76"
}
```

The server raised three Pydantic `unexpected_keyword_argument`
errors:

- `predefined_options_defaults` — actually added in **R63b**, but
  the v1.5.36 client predates that release. (User confirmed: "我项
  目内容很正常".)
- `timeout_seconds` — the client uses this name, but our parameter
  is called `timeout`.
- `task_id` — the client supplies its own trace ID, but the server
  generates its own (we do not want client-supplied IDs because
  they can collide with server-generated ones).

The agent could not retry — Pydantic rejection happens before any
of our code runs, so the LLM saw "tool call failed" and gave up.

### How we fixed it

- **R77** — `server_feedback.py::interactive_feedback`:
  - `timeout_seconds: int | None = Field(...)` — alias for
    `timeout`, used only if `timeout` is unset.
  - `task_id: str | None = Field(...)` — accepted but ignored;
    we still generate `_generate_task_id()` server-side.
  - Both fields documented in the function docstring's
    "Cross-tool compatibility" section so future drift fields
    have a place to land.
  - `_ignored_compat` dict logs at DEBUG level when an ignored
    compat field is supplied, so we can decide later whether to
    promote it to a real parameter or strip it.
- **R77 tests** — `tests/test_interactive_feedback_errors.py`
  added three new cases:
  - `test_v1_5_36_drift_args_do_not_raise` — calls with all
    three drift fields; asserts no `ToolError`.
  - `test_timeout_seconds_alias_does_not_override_server_config`
    — `timeout_seconds=999_999` does not bypass
    `server_config.calculate_backend_timeout()`.
  - `test_external_task_id_is_ignored_in_favour_of_generated_id`
    — externally-supplied `task_id` is not surfaced anywhere
    downstream; the server-generated ID is what shows up in
    `add_task` payloads.

### What contributors should do next time

1. **Treat the MCP tool schema as a versioned external contract.**
   Once a parameter shape is published, it can only be:
   (a) retained as-is, (b) extended with new optional parameters,
   or (c) deprecated with an alias-and-warn path. Removing or
   renaming a parameter without an alias breaks every pinned
   client.
2. **Accept-but-ignore is preferable to reject** for unknown
   parameters that smell like compat drift (suffix matches `_seconds`
   / `_timeout` / `_id`, prefix matches a known parameter). The
   alternative — `model_config = {"extra": "forbid"}` — is more
   strict but breaks pinned clients silently.
3. **Document every accepted compat field in the docstring's
   "Cross-tool compatibility" section.** Future contributors
   need to know which fields were accepted-but-ignored on
   purpose vs which slipped through.
4. **Add a regression test for every compat alias** that asserts
   both the positive (accepts the alias) and negative (does not
   override the canonical parameter) behaviours. R77's three
   tests are the template.

## Root cause 6 — Defensive branches are the most under-tested code in any module

### What happened

Two production modules had below-90% line coverage despite passing
every functional test:

- `web_ui_routes/system.py` — **58.36%** coverage. The endpoints
  `/api/system/network-base-url-status` (LAN-vs-loopback diagnosis),
  `/api/system/health` (multi-component health roll-up), and
  `/api/system/recent-logs` (paginated log fetch) had no dedicated
  tests; the only coverage came from indirect calls during other
  tests. The exception-handling branches (Bonjour resolver crashed,
  health check raised, log limit out of range) were **completely
  untested**.
- `i18n.py::detect_request_lang` — **75.81%** coverage. The function
  has a four-tier fallback (Flask `Accept-Language` header → config
  `web_ui.language` → `DEFAULT_LANG`) but only the "header wins"
  path was exercised by tests. The "config wins" and "default wins"
  paths had no coverage. `get_locale_message` had a `str.format`
  `KeyError` recovery branch that no test triggered.

These are exactly the branches where bugs hide: nobody hits them on
the happy path, but a pathological input or a downstream failure
funnels execution there. R59's SIGTERM handling was a similar story
in the v1.5.45 cycle — we shipped the code, the happy path worked,
but the actual SIGTERM-during-startup race was untested for months.

### How we fixed it

- **R78** — `tests/test_web_ui_routes_system.py` added 14 new test
  methods across three test classes:
  - `TestNetworkBaseUrlStatusEndpoint` (4 tests) — covers `ok`,
    `configure_external_base_url`, `bind_lan_interface` paths,
    plus internal-exception-returns-500.
  - `TestSystemHealthEndpoint` (4 tests) — `healthy`,
    `degraded`, `unhealthy` statuses; asserts no sensitive data
    leaks (no env vars, no full file paths).
  - `TestSystemRecentLogsEndpoint` (6 tests) — default limit,
    explicit limit, invalid limit, out-of-range limit, zero
    limit, full payload roundtrip.
  - Coverage for `web_ui_routes/system.py` jumped to **84.19%**.
- **R79** — `tests/test_i18n_backend.py::TestBackendDetectRequestLang`
  (8 tests):
  - All four `detect_request_lang` priority paths (header zh,
    header en, header unknown, no Flask context).
  - Config `auto` fall-through.
  - Default-language safety net when both Flask context and
    config fail.
  - `get_locale_message(lang=None)` auto-detect path.
  - `str.format` `KeyError` recovery — falls back to the
    unformatted template string.
  - Coverage for `i18n.py` jumped to **98.39%**.

### What contributors should do next time

1. **Read the coverage report after every feature commit, not just
   at release time.** A new feature that drops a module from 95% to
   85% almost always means the new code path has untested error
   branches. `make coverage` (or `uv run pytest --cov ...`)
   surfaces this.
2. **Defensive branches deserve at least one test each.** If
   `try/except` exists, write a test that triggers the `except`.
   If a parameter has a fallback, write a test for each tier of
   the fallback. Use `unittest.mock.patch` to force the failure
   mode if the natural environment cannot.
3. **Coverage targets are a floor, not a ceiling.** Project-level
   95% is a useful Schelling point but does not protect a
   specific module from regression. The R78/R79 sprint targeted
   modules below 90% specifically because that is where the bugs
   were going to land first.
4. **Test classes that group endpoint-by-endpoint mirror the URL
   structure**, making it easy to find the test for any given
   endpoint by `Cmd+P → endpoint name`. R78's structure is the
   template.

## Root cause 7 — Markdown links rot silently; only mechanical scans catch them

### What happened

`README.md`, `CHANGELOG.md`, every page under `docs/`, and every
governance doc under `.github/` use relative markdown links to
cross-reference each other. The R73 governance-doc relocation
(`SECURITY.md` → `.github/SECURITY.md`) silently broke **14 relative
links** because the moved files still carried link targets shaped
`docs/xyz.md` that now had to be `../docs/xyz.md` from inside
`.github/`. The README's "Quick start" still rendered fine; the
broken links were buried two scrolls down inside
`.github/CONTRIBUTING.md` and `.github/SUPPORT.md`.

GitHub's web view shows broken relative links as plain text with no
warning — the user only finds out when they click and get a 404.

### How we fixed it

- **R80** — `tests/test_docs_links_no_rot.py` walks every `*.md`
  file under the repo (skipping `node_modules/`, `.venv/`,
  `.vscode-test/`, and a small allowlist of intentionally-broken
  test fixtures), extracts every relative link with a regex,
  applies a `_looks_like_path` heuristic to filter out regex
  literals (e.g. `(\d+)` inside `CHANGELOG.md`'s
  release-section snippets), and asserts every remaining target
  resolves on disk. The 14 broken links surfaced immediately.
- **R80 fixes** — manual `git mv`-aware path corrections inside
  `.github/CONTRIBUTING.md`, `.github/SECURITY.md`,
  `.github/SUPPORT.md`. Most fixes were `docs/xyz.md` →
  `../docs/xyz.md`; a few were `packages/vscode/README.md` →
  `../packages/vscode/README.md`.

### What contributors should do next time

1. **Run `pytest tests/test_docs_links_no_rot.py` before any
   `git mv` of a `.md` file**, regardless of how trivial the move
   looks. The test is fast and catches both
   accidentally-flipped relatives and dead targets.
2. **Be conservative with the `_SKIP_DIRS` and `_looks_like_path`
   allowlist.** Each entry is a place where the test cannot see
   regressions, so it should only be added when the alternative
   (false positives) is too noisy to maintain.
3. **For new external links** (URLs to GitHub Issues, Wikipedia,
   etc.), do not add them to this test — it scans relative links
   only. A separate `linkcheck` job (e.g. `lychee`) would cover
   external rot, but that is a future project; for now external
   links rot manually.
4. **Write link targets without a leading `./`.** Both `path` and
   `./path` are valid markdown link targets, but the leading `./`
   adds noise without changing resolution. The test accepts both,
   but the canonical form is no `./`.

## Root cause 8 — `CHANGELOG` drifts between releases; backfilling 14 entries from `git log` is doable but lossy

### What happened

`CHANGELOG.md` had a `[Unreleased]` section that was empty between
v1.5.45 (the last release) and the start of this batch. Fourteen
R-numbered commits (R72 → R80) landed without `CHANGELOG`
updates. By the time we backfilled (R80b), some commits were five
weeks old and the original "user-facing impact" wording had to be
reconstructed from the commit body — which is a lossy process
because commit bodies are written for reviewers, not for end-users
reading a release-notes blog post.

### How we fixed it

- **R80b** — single `:books: docs(changelog-r80b): backfill
  [Unreleased] section — R72 → R80 batch` commit. The
  `[Unreleased]` section now has Security / Added / Changed /
  Fixed / Removed sub-sections following Keep a Changelog
  conventions, with one line per R-number summarising the
  user-visible impact. Cross-links to the relevant lessons-learned
  / triage docs are included so a release-notes author can
  expand any line into a paragraph without re-reading the commit.

### What contributors should do next time

1. **Update `CHANGELOG.md` in the same commit as the feature**, or
   in a follow-up commit landed within 24 hours. Waiting weeks to
   backfill costs accuracy.
2. **Use Keep a Changelog's section names.** `Security` /
   `Added` / `Changed` / `Fixed` / `Removed` /
   `Deprecated`. End users skim by section, so a misclassification
   (e.g. a security fix listed under `Fixed` instead of
   `Security`) is a missed signal.
3. **One line per R-number, with a link to the relevant lesson /
   triage doc if the change is non-trivial.** Reviewers reading
   the changelog at release time should be able to drill down
   into the rationale without re-reading the entire commit log.
4. **Do not let `[Unreleased]` empty out for more than two
   weeks.** If the `[Unreleased]` section is empty and the
   default branch is ahead of the last tag, that is a signal
   that the project owes a release-or-changelog-update.

## Cross-cutting takeaways

- **Decay is invisible until you measure it.** Every root cause in
  this batch was a flavour of decay that the team had stopped
  noticing — security alerts piling up in a tab nobody opened,
  warnings the IDE muted, links inside docs nobody clicked, a
  flat layout the IDE indexed without complaint. The fix was
  always to **add a measurement** (link-rot test, brand-color
  guardrail, ruff LOG family, coverage report at module
  granularity) — not to add discipline. Discipline doesn't scale;
  guardrails do.
- **Atomic commits keep refactors safe.** R76 (1074 imports + 879
  mock patches + 119 hardcoded paths) and R80b (14 changelog
  entries) are both single commits. R76b (config-template prune)
  and R80 (link-rot guard) are deliberately separate from the
  refactor / docs-fix they accompany. The principle: each commit
  represents a single rollback target. If R80b regresses anything,
  one revert restores the changelog without touching the link-rot
  fix; if R76b regresses anything, one revert restores
  `config.jsonc.default` without re-flattening the layout.
- **Schema-as-contract applies to internal interfaces too.** R77's
  cross-MCP-tool compat aliases are the same lesson as R63b's MCP
  tool description (covered in `lessons-learned-r60s.md` Root
  cause 2): once an external client pins to a shape, your tool's
  parameter list becomes a public API. The same logic applies to
  the auto-generated `docs/api/` reference, the public Python
  surface enumerated in `docs/README.md`, and the `aiia://server/info`
  resource block — every one of those is a contract somebody
  could be parsing programmatically.
- **Tests as the contract layer (revisited).** Just as in R63 →
  R70, every R-numbered fix in this batch shipped with a
  dedicated regression test or a dedicated coverage uplift. The
  pattern is now well-established: when a bug is found, the test
  that would have caught it is what makes the fix permanent. The
  fix itself is incidental.
- **Documentation is code.** R71 (post-mortem write-up itself), R73
  (governance docs relocation), R80 (link-rot guard), R80b
  (changelog backfill) all touch zero `.py` files but ship as
  R-numbered commits with full Why / What / Verification bodies.
  Treating docs as code means they get the same review, the same
  guardrails, and the same regression tests as the runtime — and
  it is the only sustainable answer to docs decay.
