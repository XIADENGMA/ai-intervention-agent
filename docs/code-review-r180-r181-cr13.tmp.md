# Code Review #13 — v1.6.3 release lifecycle rescue (R180 → R181)

> Internal review of the release-cycle commit cluster covering the
> v1.6.3 bump (R179 close), the bump's failed release-tag CI, the
> R180 + R181 rescue commits that closed the failure mode and the
> structural footgun behind it, and the v1.6.3 re-tag that shipped
> all five packaging targets clean (PyPI, Open VSX, VS Code
> Marketplace placeholder, GitHub Release, sdist+wheel artefacts).
> Reviewers preparing v1.6.4 or v1.7.0 should walk this list before
> tagging.

## Cycle summary

| Tag   | Hash      | One-liner                                                                                                                                |
| ----- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| —     | `a5c12b0` | bump v1.6.3 (R155 → R179 + CR#10/11/12 closed). [Unreleased] migrated into [1.6.3]; CHANGELOG / pyproject / package.json / lock files / CITATION.cff / bug_report.yml all bumped via `scripts/bump_version.py`. |
| —     | `7dc643b` | merge `origin/main` (dependabot PR #38: `@types/node` 25.6.0 → 25.6.2 in `packages/vscode`). Auto-merged via `ort`; package-lock + packages/vscode/package.json drift resolved. |
| R180  | `72b0ae1` | **Rescue R151 housekeeping tests from `[Unreleased]`-only fossilisation.** v1.6.3 bump triggered 3 case failures in `TestR151ChangelogUnreleased` (3 assertions tied to an *empty* `[Unreleased]` block). Class renamed → `TestR151ChangelogPersistence`; invariants re-anchored on whole-CHANGELOG search; added line-anchored h3 walker; 4972/4972 green after fix. |
| R181  | `bf68c4d` | **Un-ignore docs/md from `test.yml` `paths-ignore`.** Removed `**/*.md` and `docs/**` from both `on.push.paths-ignore` and `on.pull_request.paths-ignore`. Kept `.github/ISSUE_TEMPLATE/**` + `LICENSE`. Added inline R181 rationale comment + 6-case regression guard `tests/test_workflow_paths_ignore_r181.py`. |

**Net delta**: 1 R-series feature bug-fix (R180) + 1 R-series
structural fix (R181) + 1 bump + 1 dependabot merge.

**Critical milestone**: this cycle isn't about *adding* features —
it's the first cycle to ship a successful end-to-end release
(`v1.6.3 tag push → Build → Publish to PyPI / Open VSX → Create
GitHub Release`) after the v1.6.1 floating-`ovsx` failure (R149
closed) and the post-R179 latent CI-bypass footgun (R181 closed).
Two latent defects, one cycle, one re-tag.

### Release-attempt timeline

| Attempt | Tag commit | CI result                              | What failed                            |
| ------- | ---------- | -------------------------------------- | -------------------------------------- |
| #1      | `a5c12b0`  | Build job failed at "Python CI Gate"   | R151 housekeeping tests fossilised on `[Unreleased]` after the bump moved R148-R151 into `[1.6.3]`. Downstream Publish jobs (PyPI, Open VSX, Marketplace, GitHub Release) all skipped. |
| #2      | `72b0ae1`  | All 5 jobs ✓ (4m39s + 24s + 16s + 33s + 28s) | None. v1.6.3 published to PyPI (Trusted Publisher attestations), Open VSX (`ovsx@0.10.9`), GitHub Release, sdist+wheel artefacts. Marketplace skipped (no `VSCE_PAT` configured — graceful skip, not failure). |

The attempt-1 failure was caught **before** any external artefact
shipped (no PyPI version 1.6.3, no Open VSX, no GitHub Release).
The "clean abort" was: `git push --delete origin v1.6.3` + `git
tag -d v1.6.3` + retag on `72b0ae1` after R180. No history rewrite
on `main`; only the tag moved (which is safe because nothing
downstream had consumed v1.6.3 yet).

## Strengths (what the cycle did well)

- **Same-cycle root-cause closure.** R180 didn't just patch the
  3 failing test cases — it diagnosed *why* the test was failing
  (snapshot fossilisation on a transient state), renamed the class
  to reflect the new semantic (`Persistence`), and added a
  line-anchored regex walker so the new invariant (`R148-R151
  appear under some `### Added / ### Changed / ### Fixed` heading
  anywhere`) is robust against inline `### x` prose in CHANGELOG.

- **Tier-2 fix in same cycle (R181).** The fossilisation could
  have been a one-off bug ("fix the test, move on"). Instead R181
  asked *why a bump that touched only `.md` files passed local
  pre-commit, passed `push`, but failed `release.yml`* — and
  uncovered the `paths-ignore` structural footgun. **Two bugs,
  one root cause** (CI surface inconsistency between branch-push
  and tag-push), and R181 closes it permanently with a regression
  guard that also documents the assumption.

- **Clean abort instead of v1.6.4 hop.** The natural failure mode
  is "v1.6.3 failed → bump to v1.6.4". That would have left a
  ghost `v1.6.3` tag on Git with no PyPI / OVSX artefact — a
  trap for future readers (`pip install ai-intervention-agent==
  1.6.3` would have failed). Instead R180 + R181 + re-tag let
  v1.6.3 = the **working** bundle. Future bisect / pip-pin /
  release-notes are uniformly correct.

- **Regression guard authoring discipline.** R180 added a
  `_all_section_headings_for(ident)` helper with a docstring that
  explains *why* line-anchored regex (`re.MULTILINE`) is used —
  not just *that* it is. R181 added a 6-case test where the sixth
  is **a documentation-anchored test** (no assertion, just
  description in body+docstring) explicitly calling out future
  expansion to `codeql.yml` / `vscode.yml`. Future maintainers
  see the *constraint* (R181 fix), the *posture* (which other
  workflows have the same shape), and the *deferral reason* (they
  don't run pytest guards today).

- **Dependabot integration handled cleanly.** Mid-bump, a
  dependabot PR #38 (`@types/node` patch) auto-merged on remote
  while local was preparing v1.6.3. `git pull --no-edit` resolved
  cleanly because the two commits touched different keys in
  `package-lock.json` and `packages/vscode/package.json` — no
  rebase needed (which would have re-hashed R-series commit
  references in messages). Merge commit `7dc643b` preserved.

- **Tag safety check + clean post-tag verification.** Before the
  re-tag push, `scripts/check_tag_push_safety.py` ran clean
  (1 untagged tag, ≤ 3 budget). After release, `gh run view`
  confirmed all 5 jobs green; the only annotation was a graceful
  `VSCE_PAT not configured` skip on the Marketplace step (Open VSX
  is the primary VSCode distribution channel for this project).

## Risks (what to watch)

- **Tag re-shooting is allowed, but only because nothing
  downstream consumed v1.6.3 attempt #1.** This precedent is
  safe *now*. If a future release attempt fails *after* PyPI /
  Open VSX has accepted the package (e.g. `Publish to PyPI` ✓ +
  `Publish VSCode Extension to Open VSX` ✗), re-tagging the
  same version is **not** safe — PyPI rejects re-upload of the
  same version. **Risk rating: Low** — the failure mode is
  controlled by where in the workflow the failure happens, and
  the current `release.yml` ordering (`Build` → `Publish in
  parallel`) means a Build failure is recoverable (no upload
  yet); a Publish failure is partially-recoverable (some packages
  shipped, some not). Document this in a release-recovery
  playbook in v1.7.x.

- **R181 only fixes `test.yml`, not `codeql.yml` or `vscode.yml`.**
  CR#13's R181 docstring explicitly defers the other two
  workflows because they don't run pytest guards. If a future
  R-cycle adds doc-aware checks to those workflows (e.g.
  `vscode.yml` starts validating `packages/vscode/CHANGELOG.md`),
  the same `paths-ignore: docs/**` footgun will resurface. The
  R181 6th test case explicitly documents this assumption — a
  future contributor adding doc-aware steps to those workflows
  will see the failing-to-mention test name + docstring in CI
  logs. **Risk rating: Low** — defensive-by-documentation.

- **`[Unreleased]` post-bump body is now expected-empty.** R180
  relaxed `test_unreleased_section_exists` to allow empty
  `[Unreleased]` block (anchor only). The risk: a maintainer
  *forgets* to add an entry under `[Unreleased]` before the next
  bump, so the next release ships with an empty CHANGELOG block.
  **Risk rating: Low** — `scripts/bump_version.py` parses
  `[Unreleased]` content into the new version section; an empty
  body means the new version section will *also* be empty, which
  shows up in the release-notes diff (human reviewer catches it).
  Could add a `bump_version.py --warn-empty-unreleased` flag in
  a future cycle if this becomes a problem.

- **R180 `_all_section_headings_for` performance.** The regex
  walker is O(R-tags × ### headings) per test run; today
  CHANGELOG.md has ~30 `### Added/Changed/Fixed` headings and 4
  R-tag occurrences = 120 iterations per case × 3 cases = 360
  iterations. **Negligible (< 1 ms)** for current corpus.
  Long-term: if CHANGELOG grows past 1000 headings, binary-search
  the cached h3 positions. Not worth it today; doc-anchor the
  performance contract instead.

- **No `[Unreleased]` body-emptiness CI guard.** R180 explicitly
  doesn't require `[Unreleased]` to be non-empty (correct for
  post-bump state). But during *active development* between
  releases, you'd want to see at least one entry queueing up.
  CR#12 F-4 (commit precompressed artefacts) and a hypothetical
  F-5 (warn-on-empty-Unreleased between releases) are both
  v1.7.x-roadmap candidates. **Risk rating: Low** — the empty
  state is fine *temporarily*; a regression would only surface
  if the project goes silent for months between releases.

## Cross-cutting follow-ups (Code Review #13 work items)

| ID    | Severity | Item                                                                                                                                  | Owner suggestion                                                                                                                                  |
| ----- | -------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-1   | Medium   | Document a release-recovery playbook (`docs/release-recovery.md`) covering: (a) clean abort when Build fails (re-tag safe); (b) partial-publish recovery when some Publish jobs succeed (PyPI version rejected re-upload); (c) downstream user comms if a tag had to be force-deleted. | **DONE in CR#13 follow-up** — landed bilingual `docs/release-recovery.md` (EN) + `docs/release-recovery.zh-CN.md` (zh-CN), covering all 3 failure patterns plus a communication template plus a "what R180+R181 prevent" cross-reference table. ≈ 200 lines each. |
| F-2   | Low      | Audit `codeql.yml` and `vscode.yml` for the same `paths-ignore: docs/**` posture. If either ever starts running doc-aware checks, expand R181 guard to cover them. | **DONE in CR#13 audit pass** — codeql.yml: legitimate `paths-ignore` (CodeQL is code-analysis-only, no doc surface). vscode.yml: uses `paths:` allow-list (no `paths-ignore`), inherently excludes docs/. Neither runs pytest / ci_gate.py / doc-aware guards. R181 footgun is **scope-limited to test.yml**; F-4 promoted to assert this posture. |
| F-3   | Low      | Consider a `bump_version.py --warn-empty-unreleased` flag that prints a warning (not error) when bumping with an empty `[Unreleased]`. Helps catch "forgot to backfill entries" mistakes during active development. | **DONE in CR#14** — R183 added `--warn-empty-unreleased` (default-on) + `--no-warn-empty-unreleased` escape hatch + 15-test contract. See `code-review-r182-r184-cr14.tmp.md` §F-3 closure. |
| F-4   | Medium   | `tests/test_workflow_paths_ignore_r181.py:test_no_other_workflow_silently_re_ignores_docs` is doc-anchored only. If we agree codeql / vscode shouldn't re-add `docs/**`, expand to assert that posture too. | **DONE in CR#13 follow-up** — promoted to `test_codeql_and_vscode_workflows_dont_run_doc_guards`: asserts neither workflow invokes `pytest`, `ci_gate.py`, or any of the 7 doc-aware test scripts. A future contributor adding a doc-aware step to codeql/vscode trips this and revisits R181's scope. |

## Test posture

| Surface                                                       | Tests | Notes                                                                                                                                                                                                                |
| ------------------------------------------------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/test_housekeeping_r151.py` (R151, rescued in R180)    | 8     | Renamed class `TestR151ChangelogUnreleased` → `TestR151ChangelogPersistence`. 3 invariants re-anchored on whole-CHANGELOG. `_all_section_headings_for` line-anchored regex walker (R180 hardening).                |
| `tests/test_workflow_paths_ignore_r181.py` (R181, new)       | 6     | YAML-parsed guard for `test.yml` paths-ignore: 2× exclude `**/*.md`/`docs/**`, 2× require `LICENSE`/`ISSUE_TEMPLATE`, 1× R181 rationale comment, 1× doc-anchored future-expansion note.                              |
| Total CI-gate sweep                                           | 4978  | 4972 passed (CR#12 baseline) + 6 new R181 cases = 4978. 0 failed, 2 skipped. R180's 3 case fixes restored the baseline that v1.6.3 attempt #1 broke; R181's 6 new cases added net +6 coverage.                       |

## Release readiness checklist

✓ v1.6.3 actually shipped: PyPI (Trusted Publisher attestations),
Open VSX (`ovsx@0.10.9` pin), GitHub Release, sdist+wheel artefacts.

✓ Both R180 and R181 are *forward-compatible* fixes — they don't
require any v1.6.4 to be useful (the R181 guard is already locked
in `main`).

✓ All 4 follow-ups from CR#12 remain in their CR#12-recorded state
(F-1 + F-2 closed in CR#12 cycle; F-3 + F-4 carry over to long-term
roadmap).

✓ All static guards green (`ruff format`, `ruff check`, `ty check`,
`pytest -W error`, `generate_docs --check`, `silent_failure_audit
list`, `check_i18n_*`, `check_css_quote_consistency`,
`check_brand_color_consistency`, `check_locales`).

✓ Pre-commit chain green on every commit in this cycle. Both R180
and R181 commits had hooks run; both passed without retries.

✓ `scripts/check_tag_push_safety.py` ran clean before re-tag push.

✓ R180 + R181 + bump commits all have detailed Git messages
(50/72/multi-paragraph format) explaining problem, root cause, fix,
and validation. No "fix tests" one-liner commits.

## Closing remarks

CR#13 is a **structural-rescue cycle**: zero new user-facing
features, but two latent footguns retired (R180 snapshot
fossilisation, R181 CI paths-ignore). The cycle is short on commit
count (4) but high on architectural impact:

- Before R180: every R-series housekeeping commit's snapshot test
  was a time bomb that the next bump would detonate.
- After R180: snapshot tests are anchored on persistent CHANGELOG
  semantics, not transient `[Unreleased]` state.
- Before R181: every doc-only commit silently bypassed CI, letting
  CHANGELOG / docs / README guard regressions ride straight into a
  release tag.
- After R181: doc-only commits run the full `ci_gate.py` matrix,
  catching the breakage at PR time instead of at tag-push time.

The v1.6.3 release attempt #1 failure was the *evidence* that
these footguns needed retiring; CR#13 is the **post-mortem +
prevention** for the next 50 cycles.

Next R-cycle should consume one of:

1. ~~**F-1** — write `docs/release-recovery.md` (highest user
   value).~~ **DONE in CR#13 same-cycle close.**
2. ~~**F-2** — audit codeql/vscode workflows.~~ **DONE in CR#13
   same-cycle close (no footgun).**
3. ~~**F-4** — promote R181 6th test from doc-anchor to
   assertion.~~ **DONE in CR#13 same-cycle close.**
4. **F-3** — `bump_version.py --warn-empty-unreleased` (deferred
   to v1.7.x roadmap).
5. Pick a new latent defect from the R-cycle backlog (e.g. CR#10
   F-4 anchor-line drift, CR#11 F-2 PR-template discoverability).
6. Address a v1.7.x roadmap item.

End-state: v1.6.3 shipped clean, R180 + R181 added permanent
guardrails, CR#13 F-1/F-2/F-4 closed in-cycle and CR#13 F-3 closed
in CR#14 (R183), project is in a release-ready state.
