# Code Review #15 — v1.6.4 follow-ups (env override / CLI / UX)

> Predecessor: [`code-review-r182-r184-cr14.tmp.md`](code-review-r182-r184-cr14.tmp.md).
> Cycle window: 2026-05-12 17:00 UTC → 2026-05-12 17:30 UTC
> (about half an hour, five commits, three new tests, two doc syncs,
> all on top of the `v1.6.4` tag — no new tag yet).
> Outcome: ready to bump a `v1.6.5` (or `v1.7.0` since two are
> user-facing features) when the in-progress R185 work finishes.

## Scope

Five-commit post-release polish cycle, driven by the maintainer's
"what's *still* missing as a complete project, especially performance,
latent bugs, and feature absorption from sibling projects" prompt.
The dominant theme is **closing the user-onboarding loop** — every
commit reduces friction for first-time `uvx ai-intervention-agent`
users:

| Commit    | Theme         | One-liner                                                                                                                                              |
| --------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `444af4c` | README polish | Trim hero badges to 3 `for-the-badge`, lift `cunzhi`-style pain-point lead, emoji feature anchors.                                                     |
| `900d2bb` | Feature       | `AI_INTERVENTION_AGENT_WEB_UI_HOST/PORT/LANGUAGE` env overrides (no file edits for `uvx` / Docker / systemd / SSH-remote).                             |
| `218b72f` | Feature       | CLI `--version` / `--help` via argparse + `_cli_main` console-script entry (fix "hangs forever on unknown flag" PyPI footgun).                         |
| `ced2373` | UX            | `port_in_use` `ServiceUnavailableError` message inlines three executable fixes (env override → `config.toml` → `lsof`), bilingual `troubleshooting.md` rewrite. |
| `2db38d2` | Docs          | Surface the env-override + CLI inspection paths in `README.{md,zh-CN.md}` Configuration section so first-time readers actually see them.               |

## Commits in chronological order

| #   | SHA       | Subject                                                                                                                                                              |
| --- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `444af4c` | `:lipstick: docs(readme): trim hero badges to 3 for-the-badge + cunzhi-style pain-point lead + emoji feature anchors`                                                |
| 2   | `900d2bb` | `:sparkles: feat(service-manager): env overrides for web_ui host/port/language`                                                                                      |
| 3   | `218b72f` | `:sparkles: feat(cli): --version / --help via argparse + _cli_main entry`                                                                                            |
| 4   | `ced2373` | `:art: ux(service-manager): inline actionable fixes into port_in_use error`                                                                                          |
| 5   | `2db38d2` | `:memo: docs(readme): surface env override + CLI inspection paths`                                                                                                   |

## Findings — what went well

### 1. Three commits form a single "no-edit-config-toml" UX loop

The three core commits (`900d2bb` + `218b72f` + `ced2373`) compose
into a single user story: a first-time `uvx ai-intervention-agent`
user hits the default `8080` port collision, gets an error message
that **already names** `AI_INTERVENTION_AGENT_WEB_UI_PORT` as the
fix, can verify the override took with `ai-intervention-agent
--version`, and never has to find `config.toml`. The loop is
deliberately closed:

- `900d2bb` adds the env override path;
- `ced2373` makes the error message advertise that path;
- `218b72f` adds the CLI surface that confirms which binary is
  picking up the env var.

The README commit (`2db38d2`) then surfaces all three so they're
discoverable without reading the source. This is real "user-facing
release polish" — not three independent micro-features.

### 2. Backward-compatibility discipline under pressure (`218b72f`)

The first attempt at `--version` regressed 6 tests
(`test_server_functions::TestMain` × 3, `test_server_main_retry_backoff`
× 2, `test_diagnostic_event_log_r40::test_main_emits_server_boot_event_with_required_fields`).
Root cause: `main(argv: list[str] | None = None)` defaulting to
`argv = sys.argv[1:]` made pytest's own `sys.argv` look like server
CLI flags.

The fix didn't paper over the failures — it redesigned the contract:

1. `main(argv=None)` **skips argparse entirely** and goes straight
   to the stdio loop (preserves the old zero-argument contract that
   ~5000 existing tests rely on);
2. A new `_cli_main()` function explicitly reads `sys.argv[1:]` and
   forwards it to `main(argv)`;
3. `pyproject.toml` `[project.scripts]` flips from `:main` to
   `:_cli_main`.

The PyPA console-script wrapper (which calls the entry with zero
args) now resolves to `_cli_main` → reads `sys.argv` → triggers
argparse. The test suite's direct `main()` calls now resolve to
the old path. Both worlds get what they want.

Test investment: 20 new cases in `test_server_cli_argparse.py`
guarding 4 invariants (version/help/unknown/backward-compat), with
one case explicitly named `test_none_argv_skips_argparse` to lock
the regression that triggered the redesign. Future contributors
who try to "simplify" by removing the sentinel will face an immediate
fail with a docstring explaining why.

### 3. Test investment that locks UX text without freezing wording (`ced2373`)

`test_port_in_use_friendly_message.py` (9 cases) does not assert
"the message is *exactly* this string" — it asserts:

- contains `AI_INTERVENTION_AGENT_WEB_UI_PORT` (env override path);
- contains `config.toml` (file-edit path);
- contains `lsof` and the actual port number (diagnosis path);
- contains `docs/troubleshooting.md` (deep-dive link);
- is a single-line string with no `\n` (logger ergonomics);
- works for IPv6 hosts.

This is "lock the user-facing invariants, leave the prose free" —
the i18n / translation / a-b-test wording team can change every
character and still pass, but cannot accidentally drop an
actionable hint or break logger rendering.

It also keeps the legacy contract (`port_in_use` code, `host:port`
in message) verifiable separately from the new contract.

### 4. Bilingual docs stay in lockstep without copy-paste drift

`ced2373` rewrote `docs/troubleshooting.md` Issue #1 (English) and
`docs/troubleshooting.zh-CN.md` Issue #1 (Simplified Chinese) into
the **same three-option structure** (env override → `config.toml`
→ `pkill` / `lsof`). The order, the section titles ("Option A/B/C"
↔ "方案 A/B/C"), and the example port numbers all match. The
runtime error message uses the same ordering. A monolingual
reviewer can verify either side and trust the other.

`2db38d2` does the same for README Configuration sections.

### 5. CHANGELOG entries explain "why this exists" not just "what changed"

Each `[Unreleased]` bullet identifies:

- the user pain it solves ("can't easily edit `config.toml` here"
  runtimes, the "PyPI footgun that pip/ruff/uv/black all guard
  against", "inactionable error that requires reading docs");
- the prior-art reference (`mcp-feedback-enhanced` for env naming,
  `pip` / `ruff` / `uv` / `black` for CLI standard);
- the test surface (case count + invariants);
- the backward-compatibility guarantees.

This is the depth needed for release notes that ship to users.

## Findings — what could be improved

### F-1. R185 / R186 / R-naming convention not used in this cycle

Every recent housekeeping cycle uses `R-XXX` tags (R148–R184) on
both source code and CHANGELOG. This cycle's 5 commits are all
user-facing features and use Gitmoji + conventional commits
(`:sparkles: feat(...)` / `:art: ux(...)`) without R-tags.

**Why this is probably fine**: R-tags trace housekeeping /
refactor / footgun-removal work (`test_housekeeping_r151.py` is
specifically about those). User-facing features don't need that
provenance — they live in CHANGELOG `### Added` / `### Changed`.

**Why this might be a problem**: the project's CR template and
historical reviews (CR#10–CR#14) all use R-tags. Future readers
looking for "what landed in v1.6.5" might miss these commits if
they grep CHANGELOG only for `R\d+`.

**Recommendation**: keep Gitmoji+conventional for user-facing
features but add a single "Cycle summary" line to the next
release's CHANGELOG header (similar to v1.6.4's `> Security +
release-lifecycle hardening patch...`) that explicitly names the
feature loop.

### F-2. R185 cohabitation: 3 CHANGELOG stash-pop rounds

The maintainer was in parallel working on R185
(`scripts/check_tag_push_safety.py` + `tests/test_check_tag_push_safety_cve_gate_r185.py`
+ CHANGELOG markdown-style normalization). Every commit in this
cycle had to:

1. `git stash push CHANGELOG.md` to isolate R185's `* → -` + `*foo*
   → _foo_` reformat;
2. write the cycle's `[Unreleased]` entry into a clean CHANGELOG;
3. commit;
4. `git stash pop` to restore R185's reformat to the working tree.

This worked correctly all 3 rounds, but the cognitive overhead
suggests a process improvement: when a cycle starts on top of
uncommitted work, **either land the in-progress work first** (so
the cycle starts clean) **or move it to a branch**. Stash-pop
juggling is recoverable but creates "what if the maintainer
shuts the laptop mid-cycle?" anxiety.

### F-3. Confidence-check coverage on `_cli_main` is implicit, not asserted

`tests/test_server_cli_argparse.py::TestCliMainConsoleScriptEntry`
verifies that `_cli_main()` (a) calls `mcp.run` when no flag is
given and (b) triggers `sys.exit(0)` when `--version` is in
`sys.argv`. **It does not verify** that
`pyproject.toml [project.scripts] ai-intervention-agent` actually
points at `_cli_main`. A typo there (e.g. reverting to `:main`)
would break the user's `ai-intervention-agent --version` without
breaking any test in this cycle.

**Recommendation** (low priority — pre-commit `check-toml` catches
syntax errors, and `pip install` from the wheel would reveal a
missing entry point on the very first integration test): add one
test that does:

```python
import importlib.metadata
ep = importlib.metadata.entry_points(group="console_scripts")
match = [e for e in ep if e.name == "ai-intervention-agent"]
assert len(match) == 1
assert match[0].value == "ai_intervention_agent.server:_cli_main"
```

This guards the wheel-build → console-script wiring at unit-test
speed.

### F-4. README "Verify install" hint not isolated as its own subsection

`2db38d2` added a "CLI inspection" subsection under Configuration,
which is correct but slightly buried — a first-time `uvx`
installer typically reads from the top down, and "I just typed
`uvx ai-intervention-agent` — did it work?" is a Quick start
question, not a Configuration question.

**Recommendation** (cosmetic): consider promoting `ai-intervention-agent
--version` into the existing Quick start §Option 1 (`uvx`) and
§Option 2 (`pip`) blocks as a verification step. Out of scope
for this cycle; could be a one-line append in the next docs
cycle.

### F-5. `_coerce_env_str` / `_coerce_env_int` placement

These two helpers live in `service_manager.py` at module scope,
alongside the override constants. They're generic enough
(env-var coercion with logging) that they could move to a shared
`config_modules/env_overrides.py` if a second module ever needs
the pattern.

**Why this is fine today**: there's exactly one caller. Premature
extraction would create unused abstraction.

**Why mention it**: when the next env override lands (the
roadmap implies `_FEEDBACK_BACKEND_MAX_WAIT` and
`_LOG_LEVEL` could be next), the second caller is the trigger
to refactor. Until then, leave it.

## CHANGELOG audit

`[Unreleased]` after this cycle contains three subsections:

```
### Added
  - Environment-variable overrides for Web UI bootstrap
  - CLI --version / --help support

### Changed
  - port_in_use error message inlines actionable fixes

### Documentation
  - README surfaces the new env override + CLI inspection paths
```

Each entry has 10+ lines of rationale, prior-art reference, and
test surface. The Documentation bullet is in the
`### Documentation` category (`2db38d2`'s pure-README change),
not under `### Added` — correct per Keep-a-Changelog 1.1.0 and
this project's historical convention.

`test_housekeeping_r151.py::TestR151ChangelogPersistence` runs
green after the cycle (`### Added` / `### Changed` /
`### Documentation` all real categories, R148–R151 still present
in 1.6.3 / 1.6.4 sections).

## Static guards

| Guard                                                        | Status     |
| ------------------------------------------------------------ | ---------- |
| `ruff check src/ tests/`                                     | ✓ All passed |
| `ruff format --check` (this cycle's files only)              | ✓ 285 files clean (`tests/test_check_tag_push_safety_cve_gate_r185.py` is R185-in-progress, not this cycle) |
| `ty check src/`                                              | ✓ All checks passed |
| `pytest tests/` (full suite, 5074 cases, 620 subtests)       | ✓ 0 failed, 0 error, 0 warning; 5074 passed + 2 skipped |
| `pytest tests/test_housekeeping_r151.py`                     | ✓ 8/8 passed (`[Unreleased]` exists, R148-R151 persistent) |
| Cycle-specific tests (49 new cases across 3 files)           | ✓ 49/49 passed |
| `pre-commit run` (auto-ran on each commit via hook)          | ✓ ruff / trailing-ws / EOF / TOML / merge-conflict / large-file / line-ending / debug-statements / shebang — all passed |

## Closing remarks

CR#15 is a **post-release polish cycle**: zero structural changes,
zero R-housekeeping, but four user-facing improvements that close
the "first-time `uvx` user gets stuck on port collision" loop end
to end. The cycle adds 49 test cases (5025 → 5074, +0.97%) and
zero CI surface — it's pure value-add with no maintenance burden.

The next cycle should either:

- Land R185 (the in-progress `check_tag_push_safety.py` CVE gate
  work that's been sitting in the working tree across all 5 of
  this cycle's commits) so the working tree is clean again, then
- Consider a `v1.6.5` bump that ships this cycle's loop, **or**
- A `v1.7.0` bump if these two `:sparkles:` features are deemed
  significant enough to warrant minor-version semantics (env
  vars + CLI flags are both new public surfaces, so SemVer says
  MINOR).

Recommended: `v1.6.5` if R185 is a security-driven CVE gate
(matches v1.6.4's "security patch" framing), `v1.7.0` if R185
itself is small and the framing shifts to "user-onboarding
features".

— Reviewer: Claude Opus 4.7 working alongside `xiadengma`,
  session on 2026-05-12.
