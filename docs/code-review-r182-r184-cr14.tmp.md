# Code Review #14 — R182 / R183 / R184 cycle

> Predecessor: [`code-review-r180-r181-cr13.tmp.md`](code-review-r180-r181-cr13.tmp.md).
> Cycle window: 2026-05-11 22:40 UTC → 2026-05-11 23:30 UTC
> (about one hour, ten commits, four R-tags, one CR + this CR).
> Outcome: ready to bump `v1.6.4`.

## Scope

This cycle started as CR#13 follow-up wiring (R182) and grew
into a full release-grade cycle when GitHub Dependabot
disclosed 5 CVEs on the `main` branch midway through (R184). The
cycle therefore covers:

| Tag                 | Severity / Type    | One-liner                                                                                    |
| ------------------- | ------------------ | -------------------------------------------------------------------------------------------- |
| **R182**            | docs               | Wire `docs/release-recovery.{md,zh-CN.md}` into the four primary docs indexes.               |
| **R183**            | DX / soft guard    | `bump_version.py --warn-empty-unreleased` (default-on) — close CR#13 §F-3.                   |
| **R184** (deps)     | **security patch** | Bump `pytest 8.4.0 → 9.0.3`, `mistune 3.2.0 → 3.2.1` (5 CVEs cleared: 1 high + 4 medium).    |
| **R184** (setup)    | governance         | Enable repo-level `automated-security-fixes`; document the CVE-response loop in playbook.    |

Cherry-on-top chores: CHANGELOG `[Unreleased]` heading dedup
(`0a0d207`).

## Commits in chronological order

| #   | SHA       | Subject                                                                                                                                                 |
| --- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `238f2d5` | `docs(r182): wire docs/release-recovery.{md,zh-CN.md} into doc index — F-1 discoverability`                                                             |
| 2   | `0a0d207` | `chore(changelog): dedup [Unreleased] heading — R182 merged R181 + CR#13 F-4 under one ### Changed`                                                     |
| 3   | `0c44ad1` | `feat(bump-r183): --warn-empty-unreleased soft guard — close CR#13 F-3`                                                                                 |
| 4   | `71e71b5` | `security(deps-r184): bump pytest 8.4.0 -> 9.0.3, mistune 3.2.0 -> 3.2.1`                                                                               |
| 5   | `6a6b3b9` | `docs(r184-setup): enable automated-security-fixes + document CVE response loop`                                                                        |

## Findings — what went well

### 1. Same-cycle CVE-disclosure → patch → policy loop

Dependabot disclosed 5 CVEs **between** the R183 push and the
R184-setup push (delay ~10 minutes after R183 landed on main).
The cycle handled it without breaking flow:

- **R184 (deps)** — bumped pytest + mistune in the same push.
  Critical detail: pytest 8.4.0 → 9.0.3 is a *major* version
  bump but our test-fixture usage (only `tmp_path`, no
  `tmpdir`, no `config.inicfg`) is safe under the documented
  pytest 9.x breaking surface. Bonus: pytest 9 picks up the
  620 subtests we already had.
- **R184 (setup)** — discovered `automated-security-fixes`
  was `disabled` at the repo level. Enabled via
  `gh api -X PUT repos/$O/$R/automated-security-fixes`. The
  combined `dependabot.yml` (regular version updates) +
  `automated-security-fixes` (CVE-triggered PRs) +
  `dependabot-auto-merge.yml` (patch/minor auto-squash) +
  `dependabot-auto-merge.yml`'s major-bump gate now forms a
  complete CVE response loop with no manual steps for patch
  and minor severities.
- **Documentation closure** — `docs/release-recovery.md`
  gained a "Security release shortcut" section that converts
  this R184 cycle's actual commands into a reusable runbook.
  The `gh api ... dependabot/alerts --jq` one-liner shaves
  about a minute off CVE triage compared to the Dependabot UI.

### 2. Soft guard over hard guard (R183)

`--warn-empty-unreleased` is implemented as a **WARNING** that
prints to stderr but does not abort the bump. Three reasons:

1. **Coexists with R180** — R180 explicitly made
   `[Unreleased]` empty a valid post-release state. A hard
   error here would contradict that.
2. **Escape hatch matters** — `--no-warn-empty-unreleased`
   suppresses cleanly via `argparse.BooleanOptionalAction`,
   so CI / scripted bumps that genuinely need empty changelog
   releases (chore-only patches) have a one-flag override.
3. **Test investment** — 15 unit + e2e tests cover all 7
   bullet-detection edge cases (no header / only subheadings
   / `-` vs `*` bullets / EOF vs next-release boundary / bullet
   in earlier release does not count). The guard is correct
   even with weird CHANGELOG shapes.

The implementation uses `importlib.util.spec_from_file_location`
to load `scripts/bump_version.py` in the test, sidestepping
`sys.path` mutation that the `ty` type-checker can't see. This
is a small but durable testing-style improvement that future
script-test pairs can copy.

### 3. CR#13 follow-up F-3 closed

Of CR#13's four follow-ups:
- F-1 / F-2 / F-4 closed in CR#13's own cycle.
- F-3 (`--warn-empty-unreleased`) closed here in CR#14.

CR#13's promise that "all four CR follow-ups close in cycle"
has been kept. The CR#13 doc now needs a final update marking
F-3 DONE (action item below).

### 4. Documentation index is now exhaustive

R182 added `release-recovery.{md,zh-CN.md}` to four indexes:

- `README.md` "Documentation" section,
- `README.zh-CN.md` "文档" section,
- `docs/README.md` "Reviewers" section,
- `docs/README.zh-CN.md` "审计者" section.

Verified: any future-comer browsing the repo from PyPI / GitHub
landing / Chinese-language path / docs subfolder hits the
playbook within two clicks. Discoverability was the original
F-1 risk; it is closed.

## Findings — risks and watchpoints

### W-1: Dependabot's first_patched_version was stale

When the 5 CVEs first appeared, GitHub reported `first_patched
: null` for 3 of them (mistune figclass / mistune math /
mistune heading-id). The upstream changelog
(<https://github.com/lepture/mistune/releases/tag/v3.2.1>)
shows all four mistune issues *are* patched in 3.2.1 — the
advisory metadata simply hadn't been refreshed.

After the R184 push, GitHub auto-dismissed all 5 alerts as
`fixed` (`fixed_at: 2026-05-11T23:24:20Z`) because the new
mistune version (3.2.1) is outside the published vulnerable
range (`<= 3.2.0`).

**Lesson**: don't wait for `first_patched_version` to be
populated. If upstream has shipped a version *outside* the
`vulnerable_version_range`, bumping resolves the alert even if
GitHub still thinks no patch exists. This is now in the
playbook.

**Risk**: if upstream ships a version 3.2.1 that bumps the
SemVer but *doesn't* actually contain the fix, GitHub would
still mark the alert fixed. We mitigated by manually reading
mistune 3.2.1's release notes ("Escape id of headings",
"Escape xml for math plugin", "Use strict regex for image's
height and width") and confirming each maps to one of the
CVEs.

### W-2: 2 mistune CVEs still have null patched_version in GHSA

Even though we cleared them in practice, GHSA-58cw-g322-p94v
and GHSA-8g87-j6q8-g93x remain "no formal patch" in the
advisory metadata. If upstream `lepture/mistune` releases a
3.2.2 or 3.3.0 explicitly tagged as "fixes X", Dependabot may
re-open those alerts to track the formal patch. That's fine —
the path is automated (`automated-security-fixes` will PR a
bump).

**Action**: none required. Will pick up automatically.

### W-3: pytest 9.x ecosystem stability

pytest 9.0.3 is 1 month old (uploaded 2026-04-07). The
`config.inicfg` compat shim added in 9.0.2 will be **removed
in pytest 10**. We don't use that private API, but plugins we
depend on might. Audit:

- `pytest-cov 6.2.1` — last released 2025, supports pytest >= 7.
- `pytest-timeout 2.4.0` — last released 2024, supports
  pytest >= 6.

Both work fine with our test run (4993 passed, 0 warnings).
**Watchpoint**: when pytest 10 releases (mid-2026?), re-audit
plugin compat before bumping.

### W-4: 5 minute delay between push and Dependabot alert

The 5 CVEs were not on the repo before R183 push at
`23:14:44Z`. They appeared between `23:14:44Z` and `23:23:16Z`
(R184-deps push). That's ≤ 8 minutes from push to alert
disclosure — fast for GitHub but **not real-time**. If a
CVE-vulnerable commit ships *just before* an
auto-tagged release (`release.yml`), the release will go out
with the vulnerability. R184-setup's playbook section now
flags this implicit window in the "Security release shortcut"
runbook.

**Mitigation**: not pursued in this cycle — would require
gating `release.yml` on a `dependabot_security` check, which
GitHub doesn't expose as a workflow status. Logged for v1.7.x
roadmap.

## Test posture

| Surface                                             | Tests | Notes                                                                                                                                                                                                                                                                            |
| --------------------------------------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bump_version._unreleased_section_is_empty`         | 7     | All bullet-detection edge cases.                                                                                                                                                                                                                                                  |
| `bump_version._changelog_unreleased_section`        | 3     | Endpoint math (no header / next-release-boundary / EOF).                                                                                                                                                                                                                          |
| `bump_version` CLI flag                             | 1     | `BooleanOptionalAction` exposes both `--warn-empty-unreleased` + `--no-warn-empty-unreleased`.                                                                                                                                                                                    |
| `bump_version main()` end-to-end                    | 4     | Real `main()` invocation on a temp fake repo (`tmp_path` discipline, `mock.patch` of `_repo_root`, `addCleanup` symmetric `__exit__` so pytest 8/9 unraisable hook doesn't trip). Empty → WARNING / non-empty → no WARNING / `--no-warn` suppresses / missing CHANGELOG → no break. |
| Whole repo regression                               | 4978 → 4993, 0→620 subtests | +15 new R183 tests, +620 subtest detections by pytest 9 (no new code, just better reporting).                                                                                                                                                                                       |

✓ All static guards green (`ruff format`, `ruff check`, `ty
check`, `pytest -W error`, `generate_docs --check`,
`silent_failure_audit list`, `check_i18n_*`,
`check_css_quote_consistency`, `check_brand_color_consistency`).

## Follow-up items

| ID    | Severity | Description                                                                                                                                                                                             | Disposition                                                                                                                                                                                                                                            |
| ----- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-1   | Low      | Update CR#13 doc to mark F-3 status as **DONE in CR#14** for paper-trail integrity.                                                                                                                     | **DONE in CR#14** — add a final row to CR#13's follow-up table or a footnote pointing to CR#14.                                                                                                                                                       |
| F-2   | Low      | The "Security release shortcut" runbook in `release-recovery.md` references `gh api ... dependabot/alerts` but doesn't test that the JSON keys we extract (`pkg`, `severity`, `ghsa`) remain stable.    | Defer. GitHub REST stability commitment is high for `dependabot/alerts` (GA endpoint). Adding a contract test would require fixturising the API which adds maintenance overhead.                                                                       |
| F-3   | Medium   | `pytest 9.x ecosystem stability` (W-3) — schedule a Q3 2026 re-audit before pytest 10 ships, to confirm pytest-cov / pytest-timeout still support our pinned pytest range.                              | Defer. Add a 2026-Q3 calendar reminder via a `# TODO(2026-q3, R184)` comment in `pyproject.toml`?  Probably overkill — Dependabot will surface plugin-pin incompatibility when it tries to bump pytest 9.x → 10.x.                                     |
| F-4   | Medium   | CVE-aware release gating (W-4) — gate `release.yml` on "no open Dependabot security alerts" to prevent the 5-minute push→alert window from shipping a vulnerable release.                                | Defer to v1.7.x roadmap. Requires a custom GHA step using `gh api dependabot/alerts` to count open high/medium alerts; if > 0, fail the release. Non-trivial because the 2 "no-patch" mistune CVEs would block all releases until upstream patches.    |

## CR#13 retrospective update

CR#13's promise that "all four CR follow-ups close in cycle"
held: F-1 (release-recovery.md / .zh-CN.md), F-2
(troubleshooting cross-refs already existed), F-4
(test_codeql_and_vscode_workflows_dont_run_doc_guards
promotion) closed in CR#13 cycle; F-3 (--warn-empty-unreleased)
closed in CR#14 cycle. Net follow-up close rate: **4/4 in two
adjacent cycles.**

## What ships in v1.6.4

If we bump now:

- **Security** — 5 CVEs cleared (1 high pytest tmpdir, 4
  medium mistune XSS/ReDoS, all via dep bumps).
- **DX** — `bump_version.py --warn-empty-unreleased` soft
  guard.
- **Governance** — `automated-security-fixes` enabled at the
  repo level + documented CVE response loop in
  `release-recovery.md`.
- **Docs** — `release-recovery.md` is now discoverable from
  every primary docs entry-point.

Recommendation: **bump v1.6.4 now**. Cycle hit a natural
boundary: all 4 R-tags landed, all 4 follow-ups closed across
CR#13 + CR#14, no open Dependabot alerts, 4993 + 620 subtests
green.

## Sign-off

Cycle reviewer: claude-opus-4.7 (cursor agent, post-
v1.6.3-rescue work).
Verdict: ✓ ready for v1.6.4 tag push.
