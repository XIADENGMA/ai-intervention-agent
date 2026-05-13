# Code Review #12 — post-CR#11 cycle (R177 → R179 + 2 chores)

> Internal review of the R177 → R179 commit cluster (plus the
> R176-followup docs chore and the static-precompress chore),
> performed after commit `c693c45` (precompress refresh).  Reviewers
> preparing the v1.6.x release between v1.6.4 and v1.7.0 should walk
> this list before tagging.

## Cycle summary

| Tag   | Hash      | One-liner                                                                                                                                |
| ----- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| —     | `bc6a25b` | CR#11 F-1 hotfix: link-rot guard handles **double-backtick** inline code (R177 ``inline-code`` regex was single-backtick only)           |
| —     | `065f2b3` | R176 follow-up: list both `noise-levels.md` (EN) and `noise-levels.zh-CN.md` in `docs/README{,.zh-CN}.md` "Operators" section as a pair  |
| R178  | `bbd4814` | **CR#11 F-3 closeout**: CSS quote-consistency guard extended to `tri-state-panel.css` (21 single-quote → double-quote, 2-file baseline)  |
| R179  | `876b214` | **3 ci_gate footguns closed**: generator index drift (R169) + 5 ty diagnostics (4 stale ignores + 1 deliberate misuse) + R169 light-theme quote-style assertion |
| —     | `c693c45` | chore: refresh 22 stale `.br` / `.gz` / `.min` precompressed artifacts that had accumulated drift over R156 → R178                       |

**Net delta**: 1 R-series feature + 3 chores + 1 R-series cleanup
(R179 alone touches 4 latent defects).  ≈ 8 LoC source guard
(`generate_docs.py:existing_path` argument) + ≈ 200 LoC tests
(`test_generate_docs_index_prefix_r178.py` = 8 cases).  Test count
climbs by 8 (CR#11 → CR#12: 4972 passed + 2 skipped, 0 failed,
0 warning under `-W error`).  Pre-commit chain green incl. R66 brand
guard and the R174 quote-consistency guard.

**Crucial milestone**: this is the first cycle since R76 (src/ layout
migration) where `uv run python scripts/ci_gate.py` runs to **clean
SUCCESS** — 0 warning, 0 error.  CR#11 noted "zero-warning sprint"
as a strength; CR#12 is when the project actually reaches that bar
with a full `ci_gate` run, not just `pytest`.

## Strengths (what the cycle did well)

- **CR#11 follow-up F-3 closed in one cycle (R178).** Of CR#11's
  4 follow-up items, F-1 (link-rot regex) was already closed in
  R177 (same cycle).  F-3 (R174 CSS guard scope expansion to
  `tri-state-panel.css`) closed in R178 with full retirement-plan
  documentation in the script docstring.  F-2 (PR-template
  discoverability) is observational, F-4 (anchor-line drift) is
  v1.7.x-roadmap.  Net effect: **zero CR#11 follow-up rotting in
  "Low priority" purgatory** when CR#12 opens.

- **R179 is the highest-leverage cleanup in 10+ cycles.** One
  commit, three orthogonal latent defects fixed:

  1. **`generate_docs.py` index drift**: R169's hand-authored
     "How it works / Architecture / Production-grade middleware /
     Server self-info / MCP-spec compliance" prefix in
     `docs/api/index.md` was being silently regarded as "drift"
     by `generate_docs.py --check`, which `ci_gate.py:222-235`
     enforced.  Every R-cycle past R169 was running CI on a CI
     gate that was structurally guaranteed to fail.  R179's
     `existing_path` kwarg + 8 regression tests close the
     contract: generator owns suffix from `## Modules` onward,
     manual prefix is preserved byte-for-byte.

  2. **Stale `# ty: ignore[unresolved-import]` ignores (4 sites)**
     + 1 deliberate `unknown-argument` test that wasn't marked.
     `ty` had been emitting warnings post-R76, but no one had
     swept the test tree.  R179 sweeps 5 sites in 5 different
     test files, with surgical precision (4 removals + 1
     addition).

  3. **R169 light-theme quote-style assertion** (Footgun 4):
     `tests/test_export_button_ui_r125b.py::test_export_btn_in_light_theme_block`
     was hard-coding single-quote `[data-theme='light']` despite
     `main.css` switching to double-quote in R169 chore
     `73d9980`.  Long-standing `--ignore=tests/test_export_button_ui_r125b.py`
     hack in full-regression runs was masking it.  R179 relaxes
     the regex to accept either quote style, removing the need
     for the ignore.

  Total surface area: 5 files (4 test + 1 generator), but each
  one closes a latent defect that had been silently rotting since
  R169 / R166 / R76.  The commit body explains each footgun
  separately with diagnostic + fix, making the cycle reviewable.

- **Honest chore commits (`bc6a25b` + `065f2b3` + `c693c45`).**
  Each one is sized to a single concept: R177 hotfix /
  R176-docs-index sync / precompressed-artifact regeneration.
  `c693c45`'s commit message explicitly flags the artifacts as
  "downstream of multiple source commits over the last ~10
  cycles" rather than pretending the diff is "new content".
  This style — chores own their belated catch-up clearly — is the
  right pattern for a project that has Prettier-style binary
  artifacts in git.

- **Generator design: `existing_path` is keyword-only and
  defaults to `None`.** The R179 change to `generate_index`
  signature is **strictly additive** — every prior call site
  (no callers exist outside `generate_docs.main()` today, but
  external tooling could exist) keeps the same behaviour because
  the new kwarg defaults to `None` (= "no existing file, write
  fresh full content").  Test
  `TestGenerateIndexSignature::test_existing_path_param_exists`
  locks this contract: keyword-only, default-`None`, so future
  refactors can't quietly change the call-site contract.

- **8-test regression suite for the new generator behaviour.**
  Coverage matrix:
  - `None` → fresh content
  - Path that doesn't exist → fresh content
  - Existing file without `## Modules` heading → fresh content
  - Existing file **with** `## Modules` heading → custom prefix preserved (the key contract)
  - zh-CN variant uses `## 模块列表` as anchor, not `## Modules`
  - Real-repo EN index has 5 R169 sections (live invariant)
  - Real-repo zh-CN index has 5 R169 sections (mirrored live invariant)
  - Signature shape: kwarg, default None

  This is exactly the test posture R173 / R174 established —
  "lock the design from the test side rather than assume the
  source comment is enough".  Adopted as project pattern.

## Risks (what to watch in the next cycle)

- **`scripts/ci_gate.py` IS run from CI** (audited in CR#12 §F-1
  closeout).  `.github/workflows/test.yml:75-76` invokes
  ``uv run python scripts/ci_gate.py --ci --with-coverage`` as
  the main gate step.  **However**: the workflow has
  ``paths-ignore: ["**/*.md", "docs/**", ...]`` —— so doc-only
  commits (R169, R175, R176, etc.) don't trigger CI, which is
  exactly why the R169 generator-drift footgun could rot for ~7
  months without surfacing on GitHub Actions while developers
  running ``ci_gate.py`` locally would see red.  **Risk rating:
  Low** post-audit — the build-system structure is sound, but
  the next code-touching PR after a long doc-only stretch can
  inherit accumulated CI debt.  Mitigation: maintainers should
  run ``ci_gate.py`` locally before tagging doc-heavy releases,
  not assume the green-on-main signal reflects all states.

- **Generator `existing_path` is a one-way escape hatch.** If a
  future R-cycle wants to **regenerate the manual prefix** (e.g.
  R169's "How it works" section becomes stale after a real
  architecture change), `generate_docs.py` won't notice — the
  preservation logic is "if prefix exists, keep it forever".
  We don't have a "force-regenerate" flag.  **Risk rating: Low**
  — the manual prefix is supposed to be human-authored, so
  silent stale-ness is exactly what we want for routine code
  changes.  If the prefix needs an update, the human deletes
  the heading and runs `generate_docs.py` once to bootstrap
  fresh.

- **R178 + R174 default targets are now 2 files, hard-coded.**
  `scripts/check_css_quote_consistency.py:DEFAULT_TARGETS` is now
  `("main.css", "tri-state-panel.css")`.  Any *new* project-owned
  CSS file (e.g. R-cycle adds `components/foo.css` for a new
  feature) won't be guarded unless someone remembers to extend
  `DEFAULT_TARGETS` + the pre-commit `files` glob.  **Risk
  rating: Low** — adding CSS files is uncommon and obvious in
  PR diffs.  Long-term mitigation: if the CSS surface grows past
  ~5 files, switch the guard to "scan all `static/css/*.css`
  except an explicit `EXCLUDE_TARGETS = ('prism.css',)` set" so
  the default catches new files automatically.  Not worth the
  refactor today.

- **Precompressed `.br` / `.gz` / `.min` artifacts are still in
  git.** Despite the `c693c45` chore, the project's policy of
  committing precompressed artifacts (instead of `.gitignore`-ing
  them and regenerating in CI) means every cosmetic CSS / JS
  change has a 4× artifact tail.  **Risk rating: Medium** — git
  history bloat is real; one-time payoff for cutting these would
  be ≈ 25-30 MB cleanup.  Defer to v1.7.x major: lessons-learned
  doc should call out the trade-off (zero-runtime-startup vs
  repo-size) so a future maintainer makes the call deliberately.

## Cross-cutting follow-ups (Code Review #12 work items)

| ID   | Severity     | Item                                                                                                                          | Owner suggestion                                                                                                                                                                |
| ---- | ------------ | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-1  | Medium       | Confirm `.github/workflows/*.yml` invokes `scripts/ci_gate.py` end-to-end (not just a subset).                               | **DONE in CR#12 audit pass** — `.github/workflows/test.yml:75-76` already runs `uv run python scripts/ci_gate.py --ci --with-coverage` on every push/PR to main.  Caveat: workflow uses `paths-ignore: ["**/*.md", "docs/**", ...]` so doc-only commits skip CI; risk downgraded to Low — call out in `lessons-learned-silent-decay.md` instead. |
| F-2  | Low          | Document a one-shot "force regenerate manual prefix" workflow for `docs/api(.zh-CN)/index.md` so future architecture rewrites don't get silently stale-preserved. | **DONE in CR#12 follow-up** — added a "Force-regenerate the manual prefix (CR#12 §F-2 escape hatch)" subsection to `scripts/generate_docs.py:generate_index` docstring with a 4-step `git rm + regen + manual edit + commit` workflow plus the "small-step daily iteration" alternative. |
| F-3  | Low          | Consider switching R174 CSS guard from `DEFAULT_TARGETS` allow-list to `EXCLUDE_TARGETS` deny-list once project-owned CSS files grow past ~5. | Track separately; ~10 min in a future R-cycle. Note: the docstring already mentions this as a long-term retirement path.                                                       |
| F-4  | Medium       | Stop committing precompressed `.br` / `.gz` artifacts to git (or split them into a separate orphan branch).                  | Defer to v1.7.x major as a deliberate trade-off decision (repo-size vs cold-startup).  Add to `docs/lessons-learned-silent-decay.md` as a long-term debt item.                  |

## Test posture

| Surface                                                     | Tests | Notes                                                                                                                                                                                                                                |
| ----------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `tests/test_generate_docs_index_prefix_r178.py` (R179)     | 8     | Locks the `existing_path` contract: kwarg, default None, real-repo R169 prefix preservation in both EN + zh-CN.                                                                                                                       |
| `tests/test_css_quote_consistency_r174.py` (R174 + R178)   | 29    | Expanded by 1 case (R178): `test_default_targets_cover_project_owned_css` verifies main + tri-state-panel in DEFAULT_TARGETS, prism excluded.                                                                                          |
| `tests/test_docs_links_no_rot.py` (R80, last expanded R177)| 6     | R177 added 4 cases (inline / fenced / double-backtick / real link).  No regressions in CR#12.                                                                                                                                          |
| `tests/test_export_button_ui_r125b.py` (R179 footgun 4)    | 16    | Pre-CR#12: 15/16 (1 skipped due to `--ignore=` hack).  Post-CR#12: 16/16 pass without ignore.  The `--ignore=tests/test_export_button_ui_r125b.py` hack in regression-run command lines can now be removed (clean-up follow-up).      |
| `tests/test_predefined_options_dual_path_parity_cr10_f3.py` (R173) | 11 | No changes in CR#12.  Locked-in design.                                                                                                                                                                                                |
| Total CI-gate sweep                                         | 4974  | 4972 passed + 2 skipped under `-W error`.  Net delta since CR#11 close (≈ 4943 + 2): +29 cases (R175 + R176 + R177 + R178 + R179 incremental additions).  All trending up; `0 regressions` confirmed.                                |

## Release readiness checklist

✓ All 4 follow-ups from CR#11 are accounted for: F-1 (R177
DONE), F-3 (R178 DONE in same cycle), F-2 / F-4 explicitly
observational / deferred (no action required for tag).

✓ Both `README.md` (English) and `README.zh-CN.md` (Simplified
Chinese) are still byte-clean and synchronized — no drift
introduced.

✓ All static guards green (`ruff`, `ty`, `pytest -W error`,
`generate_docs --check`, `silent_failure_audit`,
`check_i18n_*`, `check_css_quote_consistency`,
`check_brand_color_consistency`, `check_locales`).

✓ Pre-commit chain mounted on `.pre-commit-config.yaml`
remains 100% green on every commit in this cycle (R178 added
`tri-state-panel.css` to `files` glob, R179 fixed the latent
`ty` diagnostics, chore `c693c45` simply moved binary
artifacts).

✓ **CI-gate footgun-4 close**: `--ignore=tests/test_export_button_ui_r125b.py`
flag in regression-run commands can now be **removed safely**
(R179 footgun 4 resolved the failing assertion).  Recommendation
to follow-up cycle: clean up any developer-facing docs / scripts
that still mention `--ignore` for this file.

✓ Generator contract: `docs/api(.zh-CN)/index.md` R169 prefix
preserved on every future `generate_docs.py --lang {en,zh-CN}`
run; locked by 8 regression tests.

✓ `--check` mode of `generate_docs.py` finally returns 0 on a
fresh clone — `ci_gate.py:222-235` will now run green on
GitHub workflow if anyone wires it in (see F-1).

✓ **Static asset state**: precompressed artifacts now match
source as of `c693c45`.  Any subsequent `static/css/*.css`,
`static/js/*.js`, or `static/locales/*.json` edit needs to
commit the regenerated `.br` / `.gz` / `.min` companions, or
the next CR cycle inherits the drift.

## Out-of-scope items (intentionally not in this CR cycle)

These were noticed but excluded from CR#12 to keep scope tight:

- **`packages/vscode/` web view + Webview UI parity smoke tests**
  — touched indirectly by R178 (tri-state-panel.css mirror byte
  parity), but no design changes warranting a CR pass.
- **VS Code extension `CHANGELOG.md`** — marketplace-facing,
  follows extension version cadence not R-tags.  Defer to extension
  release time.
- **`docs/security/AUDIT_2026-05-04.md`** — last full security
  audit; next audit naturally falls at v1.7.0 milestone.
- **`scripts/` README's "active scripts" list** — last refreshed
  R174; no new scripts added in CR#12 cycle.

---

_Generated for tag review of v1.6.x → v1.7.0 path.  This document
follows the `.tmp.md` convention (single-use, code-review-only)
established in R168; the file is git-tracked via the
`!docs/**/*.tmp.md` exception in `.gitignore` added in CR#10._
