# Code Review #17 — `v1.6.4` follow-ups, cycle 3

> Scope: 5 commits between `63428b6` (CR#16 archived) and `981117b`
> (CHANGELOG diff-scope governance hook), 2026-05-13.
> Themes: completing every F-suggestion from CR#16 in a single
> cycle (F-1, F-2, F-3, F-4, F-5), plus an unplanned but
> security-critical secret-redaction walker discovered mid-cycle.

## 1 Commits at a glance

| #   | SHA       | Type                 | Lines      | Purpose                                                                                                                    |
| --- | --------- | -------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------- |
| 1   | `d1f2ee9` | `:sparkles:`         | +406 / -16 | CR#16 **F-1 + F-3 + (security)**: `--print-config` gains `sections`/`using_defaults` + recursive secret-redaction walker   |
| 2   | `d8f0e4f` | `:lock:`             | +120 / -0  | **Security hardening doc**: three-layer recipe for non-loopback deployments (`SECURITY.md` + `configuration.md` × 2 langs) |
| 3   | `884a313` | `:recycle:`          | +197 / -4  | CR#16 **F-5**: public `invalidate_web_ui_config_cache()` helper + AST-based shape-contract test                            |
| 4   | `58441c6` | `:white_check_mark:` | +55 / -0   | CR#16 **F-2**: explicit rate-limit + auth-failure guard tests for R185 (32 → 34 cases)                                     |
| 5   | `981117b` | `:police_car:`       | +539 / -0  | CR#16 **F-4**: pre-commit governance hook for "large diff in non-`[Unreleased]` CHANGELOG region" + 13 guard tests         |

Total: ~1.3k lines net (`+1317 / -20`). Tests added across the
cycle: **34** (12 + 0 + 8 + 2 + 13 [#1 had 12 new sub-cases for the
helpers + E2E redaction, not the 23 cumulative count in the commit
body]). Final suite: **5141 passed, 2 skipped, 620 subtests** in
137.96s.

## 2 Architectural narrative

This cycle's job was to **drain the CR#16 follow-up queue**. Every
F-suggestion from CR#16 §6 has landed:

```
CR#16 §6 follow-up queue              →    Cycle 3 commit
─────────────────────────────────────────────────────────────
F-1 sections coverage                 →    d1f2ee9
F-3 using_defaults flag               →    d1f2ee9 (same commit)
F-5 public invalidate helper          →    884a313
F-2 R185 rate-limit explicit tests    →    58441c6
F-4 CHANGELOG diff-scope governance   →    981117b

unplanned (discovered during F-1):
SECURITY · secret-redaction walker    →    d1f2ee9 (rolled in)
SECURITY · non-loopback hardening     →    d8f0e4f
```

The ordering is deliberate: F-1 + F-3 went first because they shared
implementation surface (`_print_effective_config`) and the
redaction walker turned out to be a hard prerequisite once
`bark_device_key` showed up in the F-1 dry-run. The security-doc
commit (#2, `d8f0e4f`) immediately follows the redaction commit so
that the docs and the implementation ship as a coherent unit.

F-5 + F-2 + F-4 are independently scoped, lower-coupling deliverables;
they could have shipped in any order. I went F-5 → F-2 → F-4 by
estimated complexity (15m → 30m → 1h) to leave the largest unit for
last when fatigue would have less impact on smaller earlier wins.

## 3 What went well

### 3.1 100 % CR#16 follow-up completion in one cycle

CR#16 §6 listed five suggested follow-ups (F-1 through F-5) with
estimates totalling ~4h. All five landed in this cycle. No
follow-up was deferred, downgraded, or partially-implemented. This
is the first cycle in this v1.6.4 follow-up chain (CR#13 → CR#16)
where the prior CR's queue was fully drained in the next cycle.

That matters because **a stale follow-up queue compounds**: an
F-suggestion deferred two cycles starts looking like noise in CR#N+3,
loses its champion's mental model, and either gets dropped silently
or re-discovered as a "new" issue later. Draining the queue every
cycle keeps CRs as actionable artifacts rather than wishlists.

### 3.2 Unplanned-but-correct: same-commit secret-redaction

`d1f2ee9` was originally scoped as F-1 + F-3 (sections coverage +
`using_defaults`). During hand-testing of F-1, the JSON dump
contained `notification.bark_device_key` in plaintext — the user's
Bark push device token. That's a **latent information leak** that
F-1 would have just made more discoverable.

The correct response was to:

1. Halt the F-1 ship,
2. Implement the recursive `_redact_sensitive()` walker with a
   substring-based key-name heuristic (catches `device_key` /
   `api_key` / `token` / `password` / `secret` / etc. and their
   case/format variants via `_norm()`),
3. Add a comprehensive 8-case helper test suite plus an E2E
   regression guard (`test_bark_device_key_redacted`),
4. Roll the security fix into the same commit so the F-1 user
   surface and the redaction protection ship atomically (no
   intermediate "vulnerable" state),
5. Document the heuristic + rationale in the commit body.

The trade-off: `d1f2ee9` is bigger than originally planned
(`+406 / -16` vs. the original ~200-line estimate). But splitting
would have left a vulnerable surface area in the working tree
between commits. The single-commit landing is the right call for
security-adjacent changes. **Textbook handling.**

### 3.3 AST-based contract test (F-5)

`tests/test_service_manager_cache_helpers.py::TestInvalidateHelper
DistinctFromBroadFunction::test_narrow_function_ast_does_not_touch_
http_clients` uses Python's `ast` module to parse the actual source
of `invalidate_web_ui_config_cache` and walk the AST for
`ast.Name(id=...)` nodes referencing forbidden identifiers
(`_sync_client`, `_async_client`, `_config_cache_generation`).

This is **strictly stronger** than a string-search test:

- String search would false-positive on docstring mentions
  ("does **not** touch `_sync_client`...").
- String search would false-negative if a refactor renamed the
  attribute to something like `httpx_sync_client` and the test was
  still grepping for `_sync_client`.

The AST test catches only **actual code references**, ignoring
docstrings and string literals. That's the right granularity for a
shape-contract test: the contract is "this function's executable
code doesn't reference these identifiers", and that's exactly what
the AST walker verifies.

### 3.4 F-4 catches the exact bug it was designed for

The governance hook landed in #5 (`981117b`) is motivated by
`a37e17d` (R185 CVE gate, in **last** cycle), where 645 lines of
CHANGELOG markdownlint normalization rode along with the actual R185
content, making `git show --stat` for that commit functionally
useless.

If the hook had been in place during `a37e17d`, it would have
fired with a pre-commit failure pointing at the exact problem —
"You're modifying 600+ lines of `## [v1.6.4]` section". The
contributor would have either (a) split the commits, or (b) used
the documented `--allow-massive-changelog-rewrite` escape hatch
with stderr WARNING that survives in the git log as breadcrumb.

The hook is **idempotent + zero-cost** when CHANGELOG isn't
staged (short-circuits with `git diff --cached --name-only`).
**No production traffic impact** by design.

### 3.5 Test count growth without regression

Cycle 3 added 34 NEW tests against a baseline of 5107 (post-CR#16);
the suite now stands at 5141 passing. **Zero pre-existing tests
broke** — every CHANGELOG entry could be removed and the suite
would still pass at 5107.

That property — "additive tests only, no regressions" — held
across all 5 commits this cycle. Worth noting because secret-
redaction (#1) and the cache invalidate refactor (#3) both touched
files with extensive existing test coverage, and either could
plausibly have broken something subtle. They didn't.

### 3.6 Bilingual docs lockstep (continued)

- `.github/SECURITY.md` + `.github/SECURITY.zh-CN.md` (commit #2)
- `docs/configuration.md` + `docs/configuration.zh-CN.md` (commit #2)
- `README.md` + `README.zh-CN.md` (commit #1, F-1 inspection sub-list)

CR#16's lockstep discipline carried forward without slippage.

## 4 What could be improved

### 4.1 F-1' · `--print-config` `sections` ordering is arbitrary

The new `payload.sections` field returns whatever order
`ConfigManager.get_all()` happens to emit, which is currently
insertion order of the underlying TOML dict. That's stable enough
for `jq` pipelines but could be surprising for users diffing
`--print-config` output across runs (e.g. for change-detection
scripts).

Two options:

(a) Alphabetical-sort section keys before serializing.
(b) Document the current order as "follows config.toml schema
order" (web_ui → mdns → feedback → notification).

(a) is more robust to schema changes; (b) is more readable in
hand-written `--print-config | head` outputs. **Recommended (a)
for the next cycle**, with the sort done at the `_print_effective
_config` level so it doesn't impact other `ConfigManager` callers.

### 4.2 F-2' · R185 graceful-degradation test naming is non-canonical

`tests/test_check_tag_push_safety_cve_gate_r185.py` now contains 34
test methods. The new F-2 tests use names like
`test_gh_api_rate_limit_returns_none` and
`test_gh_api_unauthorized_returns_none`. The pre-existing tests use
names like `test_subprocess_error_returns_none` and
`test_invalid_json_returns_none`.

Both naming styles convey the same information ("input X →
graceful None"), but they're stylistically inconsistent. The new
"`test_<failure_mode>_returns_none`" pattern is slightly more
descriptive, but mixing patterns in a single file makes pytest
verbose output harder to scan.

Low-priority cleanup: a follow-up commit could rename the existing
tests to match the new pattern. **Estimate 15m. Pure cosmetic.**

### 4.3 F-3' · `_is_using_default_config` heuristic is fragile

The new helper checks whether `config_file_path` is _under the
package directory_ (using `Path(__file__).parent` traversal). This
works for the bundled `config.toml` shipping path:

```
/path/to/site-packages/ai_intervention_agent/config.toml
                       └─ package dir starts here
```

But it doesn't account for **editable installs** (`pip install -e .`)
where the package "dir" might be a symlink to the source tree,
or **vendored copies** where someone manually placed a fork of the
bundled config inside the package dir.

A more robust check would compare against the absolute path of the
exact bundled-default file via `importlib.resources`:

```python
bundled = importlib.resources.files("ai_intervention_agent") / "config.toml"
using_defaults = Path(config_file_path).resolve() == bundled.resolve()
```

This is `Path.samefile()`-equivalent and won't false-positive on
"user copied bundled into package dir as overlay". **Recommended
F-3' for cycle 4** if `--print-config` continues to attract
"is this loading my config?" questions.

### 4.4 F-4' · Governance hook's regex section parser is one-pass

`scripts/check_changelog_diff_scope.py::_parse_sections` walks the
staged file line-by-line with a regex to find `## [Unreleased]` /
`## [vX.Y.Z]` headers. This is correct for the canonical Keep-a-
Changelog format that the project follows, but it's not robust to:

- Reformatted headers (e.g. `## v1.7.0 - 2026-05-13` without
  brackets)
- Sub-headers under a release (`### Added` etc.) being misclassified
  if the regex pattern changes
- Multi-file CHANGELOGs (e.g. `CHANGELOG-v1.x.md` split for old
  releases)

None of these are issues today (the project uses canonical format
strictly) but they're latent fragility. Worth a future
`tests/test_check_changelog_diff_scope.py::TestSectionParserRobust`
addition that asserts behavior on adversarial inputs. **Low
priority; current coverage is sufficient for the project's
established format.**

### 4.5 F-5' · `invalidate_web_ui_config_cache()` could be made async-aware

The helper goes through `_config_cache_lock` (a `threading.Lock`),
which is correct for the current sync-only call sites. But
`get_web_ui_config()` itself doesn't have an async variant, and if
one is added later (e.g. for FastAPI dependency injection), the
sync lock could deadlock under uvloop's task-cancellation paths.

Not a current issue — there's no async path through this code today.
But worth a comment in the helper's docstring like:

```python
"""... If get_web_ui_config() ever gains an async variant, this
helper should be split into sync and async forms or be re-entrancy-
safe."""
```

Documentation-only. **5min change**; flag for cycle 4.

## 5 Static contract audit

Re-verified the R-series contracts touched by this cycle:

| Contract                                | Status                     | Evidence                                                                                                                                                          |
| --------------------------------------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R53-F** "no config-value passthrough" | ✅ preserved               | `_print_effective_config` is a CLI dump (not HTTP handler), can read `os.environ` directly; redaction walker doesn't break the contract                           |
| **R120** silent-failure baseline        | ✅ baseline=27 (unchanged) | No new bare `except: pass` introduced; F-1's redaction walker uses explicit `isinstance` checks rather than try/except                                            |
| **R121-A** health payload whitelist     | ✅ unchanged               | No health-payload changes this cycle                                                                                                                              |
| **R178** docs i18n lockstep             | ✅ both pairs synced       | `SECURITY.md` + `SECURITY.zh-CN.md` (commit #2); `configuration.{md,zh-CN.md}` (commit #2)                                                                        |
| **R19.1** tag-push safety               | ✅ unchanged               | No changes to `check_tag_push_safety.py` core flow this cycle; F-2 only added test coverage                                                                       |
| **CR#15 F-3** entry-point wiring        | ✅ unchanged               | `_cli_main` still parses `--print-config` correctly; F-1 expansion to `sections` is purely an output-layer change                                                 |
| **(NEW) Sensitive-key redaction**       | ✅ established             | `_is_sensitive_key` + `_redact_sensitive` defined in `server.py`; 8-case unit test suite + E2E `bark_device_key` regression test in `test_server_print_config.py` |
| **(NEW) CHANGELOG diff scope**          | ✅ established             | New pre-commit hook + 13 guard tests; threshold default = 100 lines; `--allow-massive-changelog-rewrite` escape hatch                                             |

## 6 CHANGELOG audit

CHANGELOG entries this cycle:

- ✅ `Added: -- CLI --print-config gains sections/using_defaults` (d1f2ee9)
- ✅ `Security: -- Hardening guidance for non-loopback deployments` (d8f0e4f)
- ✅ `Refactor: -- Public invalidate_web_ui_config_cache helper` (884a313)
- ✅ `Tests: -- R185 rate-limit + auth-failure explicit guards` (58441c6)
- ✅ `Governance: -- check_changelog_diff_scope.py pre-commit hook` (981117b)

All entries live under `## [Unreleased]`, none touch the released
`## [v1.6.4]` region (the F-4 hook would have blocked us if we did).
Each entry follows the "what + why + how" pattern established in
earlier cycles. **Audit clean.**

## 7 Suggested follow-ups (ordered)

Cycle 4 candidate work, ranked by user-visible impact:

1. **F-3'** — `_is_using_default_config` via `importlib.resources`.
   _est. 30m, low-risk, removes fragility for editable installs_
2. **F-1'** — alphabetical-sort `sections` keys in `--print-config`.
   _est. 15m, improves jq pipeline determinism_
3. **F-2'** — rename R185 graceful-degradation tests to canonical
   `test_<failure_mode>_returns_none` pattern. _est. 15m, pure cosmetic_
4. **F-4'** — `tests/test_check_changelog_diff_scope.py::
TestSectionParserRobust` adversarial-input cases. _est. 45m,
   future-proofing_
5. **F-5'** — docstring comment on `invalidate_web_ui_config_cache`
   re: async-aware future. _est. 5m, documentation_

Total cycle-4 estimate: ~2h if all 5 land. None are urgent; the
cycle could equally well pursue a new theme (e.g. plugin system,
notification backend abstractions) and treat these as backlog.

## 8 Versioning recommendation

Cumulative public-surface changes across CR#15 + CR#16 + CR#17:

- **Env vars** (CR#15):
  `AI_INTERVENTION_AGENT_WEB_UI_{HOST,PORT,LANGUAGE}`
- **CLI flags** (CR#15 + CR#16 + CR#17):
  `--version`, `--help`, `--print-config`
- **Health-endpoint fields** (CR#16):
  `web_ui_env_overrides`
- **Release-check flags** (CR#16):
  `--check-cve` / `--cve-severity` / `--allow-cve` + `make release-check-cve`
- **CLI output fields** (CR#17):
  `--print-config` now returns `sections` + `using_defaults`
- **Security primitive** (CR#17):
  Auto-redaction of sensitive keys in `--print-config` output
- **Pre-commit governance** (CR#17):
  `check-changelog-diff-scope` hook

This is materially **MINOR**-worthy by SemVer. CR#16's recommendation
of `v1.7.0` stands; this cycle reinforces it. The redaction
walker in particular is a security feature that benefits from
being highlighted in v1.7.0 release notes ("`--print-config` is
now safe to share in bug reports").

**Recommendation**: cut `v1.7.0` after a single confirmation cycle
where no critical issues surface from cycle 4 work. The cycle-3
finish line is a natural release boundary — every CR#16 follow-up
drained, security hardening landed, governance hook deployed.

---

_Authored 2026-05-13. Archive this file when v1.7.0 is cut,
mirroring the CR#15 / CR#16 archival pattern._
