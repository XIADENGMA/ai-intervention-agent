# Code Review #11 — R173-R176 cycle

> Internal review of the R173 → R176 commit cluster (plus one CHANGELOG
> link-rot follow-up chore), performed after commit `0401c37` (R176
> noise-levels English mirror).  Reviewers preparing the v1.6.x release
> between v1.6.3 and v1.7.0 should walk this list before tagging.

## Cycle summary

| Tag   | Hash      | One-liner                                                                                                                       |
| ----- | --------- | ------------------------------------------------------------------------------------------------------------------------------- |
| R173  | `9ad6c33` | **CR#10 F-3 follow-up**: MCP-path `list[dict]` vs HTTP-path parallel-array parsing parity smoke (11 tests + HTTP-side guard)    |
| R174  | `850183b` | **CR#10 F-1 follow-up**: CSS quote-consistency baseline-style guard (`main.css` only, 28 tests, pre-commit hook)                |
| R175  | `2f0da38` | `.github/` governance docs split into EN/zh-CN per README pattern (CONTRIBUTING / CODE_OF_CONDUCT / SUPPORT / SECURITY / PR-TPL) |
| —     | `1b96a47` | CHANGELOG markdown-link example chore: replace `(./xxx.zh-CN.md)` placeholder that broke R80 link-rot guard                     |
| R176  | `0401c37` | `docs/noise-levels.md` — English mirror of `noise-levels.zh-CN.md` (362→420 LoC translation); closes the last orphan-Chinese doc |

Net delta: **4 R-series commits + 1 chore, ≈ 70 LoC source guard +
≈ 65 LoC test + ≈ 870 LoC docs.  Total test count climbed by 39 cases
(R173 +11, R174 +28).  All 4904 pre-cycle tests continue to pass, the
new tests bring the suite to 4943 passed + 2 skipped (0 failed,
0 warning under `-W error`).  Pre-commit chain green incl. R66
brand-colour guard and the new R174 quote-consistency guard.**

## Strengths (what the cycle did well)

- **CR#10 follow-ups closed within one cycle (R173 + R174).** Of CR#10's
  4 follow-up items, the two actionable ones (F-1 CSS formatter guard,
  F-3 dual-path parity smoke) landed in the same week as the CR doc.
  F-2 (Open VSX install-rate monitoring) and F-4 (`main.css` size split)
  are explicitly non-actionable in the short term (F-2 is observational,
  F-4 is deferred to a perf roadmap), and the CR doc was updated in-place
  to mark F-1 / F-3 as **DONE** with hashes — keeps the follow-up table
  honest rather than letting "Low priority" items pile up.

- **Defensive testing pattern: enforce design from the test side
  (R173).** Instead of refactoring `validate_input_with_defaults` /
  `web_ui_routes/task.py` to share parsing logic, R173 added a smoke
  test that asserts the two paths *agree* on every supported input
  shape: pure list[str], list[dict] with `label` / `text` / `value`
  aliases, mixed-shape lists, truthy bool normalisation, and the
  HTTP-side "reject dict for predefined_options" 400-branch source
  check.  Net effect: the design decision "MCP path takes
  list[dict], HTTP path takes parallel arrays" is locked at compile
  time without consolidating the two parsers (which would have meant
  ~30 LoC of refactor and a small regression risk).

- **Minimal-viable guard for CSS quote drift (R174).** R169's prettier
  reflow was a one-shot manual cleanup with no preventative hook.
  R174's response is the right cost/benefit: rather than land a full
  prettier integration (Node.js dependency + .prettierrc + CI matrix
  expansion), R174 ships a 200-line Python baseline-style guard
  scoped to `main.css` only — `prism.css` (vendor) and
  `tri-state-panel.css` (un-prettier'd, feature-scoped) are
  explicitly out of scope.  The script's docstring documents the
  exact retirement plan if the project ever adopts a broader
  formatter, so the guard is not a sunk cost.

- **`.github/` doc split unblocks a long-standing TODO (R175).** The
  TODO.md "`.github` docs split into EN/zh-CN" item was pending since
  before R155.  R175 lands all 5 governance docs split in one commit
  (CONTRIBUTING / CODE_OF_CONDUCT / SUPPORT / SECURITY +
  PULL_REQUEST_TEMPLATE), each with the same `English | 简体中文`
  banner pattern as the project README, and extends
  `tests/test_docs_links_no_rot.py::must_cover` from 1 entry to 10
  entries so any future silent deletion of a localised governance
  doc trips CI immediately.

- **Last orphan-Chinese doc closed (R176).** After R175, the only
  Chinese-only file under `docs/` was `noise-levels.zh-CN.md` (362
  lines of IG-6 noise-levels spec).  R176 ships the English mirror
  with terminology aligned to the rest of the English docs
  ("channel" / "circuit-breaker" / "anti-pattern" rather than
  literal back-translations), preserves all 5 tables and 3 code
  excerpts verbatim, and extends `must_cover` again so the pair
  cannot drift apart silently.  The repo is now fully English-default
  with optional zh-CN mirrors across `README` + `docs/` + `.github/`.

## Risks / things to keep an eye on

- **Translation drift between EN and zh-CN of long-form docs.** R176
  copied the §5 anchor map (line numbers, current behaviours) verbatim
  from zh-CN to EN.  When `webview-ui.js` / `extension.ts` line
  numbers shift (very likely in v1.7.x), only one half of the spec
  will be edited if the maintainer touches only one language version.
  The current `must_cover` guard only enforces existence, not content
  parity.  Consider one of:
  1. A doc-anchor hash test that scans `docs/noise-levels*.md` and
     fails if the `## 5.` / `## 五、` section's line-number references
     are stale relative to the actual source files.
  2. Mark `docs/noise-levels.zh-CN.md` as the canonical version and
     auto-generate a "needs review" stub in the EN file when the
     zh-CN version's commit hash drifts.
  3. Accept the drift — both files exist for a single readership
     (developers who can read both), so as long as one half stays
     current the other still bootstraps a maintainer.

  Recommended for v1.7.x: option 1 (line-number drift detection)
  if it lands organically with another P-line consumption; otherwise
  option 3 (accept drift, do not over-engineer).

- **CHANGELOG markdown-link example as a hidden footgun (chore
  `1b96a47`).** R175's CHANGELOG entry illustrated the new banner
  format with a `[label](./<filename>.zh-CN.md)`-shaped placeholder,
  which the R80 link-rot guard regex treated as a real broken link.  Caught in CI on the
  next test run.  The chore fix rewrote the example as plain prose,
  but the same trap could recur: any future CHANGELOG entry that
  embeds a markdown-link-shaped example will fail link-rot.  Two
  mitigations to consider:
  1. Make `_MD_LINK_RE` in `tests/test_docs_links_no_rot.py`
     backtick-aware so examples inside ` `...` ` or fenced code blocks
     are exempt.  Risk: legitimate inline-code links would also be
     skipped, weakening coverage.
  2. Document the convention "no markdown-link-shaped placeholders in
     CHANGELOG examples" in CONTRIBUTING.md.  Risk: relies on author
     discipline; future CHANGELOG drafts will hit the same wall.

  Option 1 has the bigger blast radius but a smaller maintenance cost;
  option 2 is safer but reactive.  Tracking as F-1 of CR#11.

- **`.github/PULL_REQUEST_TEMPLATE.zh-CN.md` discoverability (R175).**
  GitHub's PR description picker defaults to the English template; the
  Chinese one is only reachable by appending
  `?template=PULL_REQUEST_TEMPLATE.zh-CN.md` to the PR URL.  Native
  Chinese contributors might not discover this.  Two options if the
  Chinese template sees no traffic over the next 2 weeks:
  1. Add a one-line link inside `PULL_REQUEST_TEMPLATE.md`'s comment
     header pointing at the `?template=` URL (the current top-of-file
     comment mentions it but the rendering in GitHub's PR UI hides
     comments).
  2. Move both templates into `.github/PULL_REQUEST_TEMPLATE/` so
     GitHub renders a template picker.  Side effect: the default
     template UX changes (users must always pick one), so the impact
     on first-time contributors is unclear.

  Tracking as F-2 of CR#11; recommend option 1 as the lower-risk
  starting point.

- **R174 baseline guard scope is intentionally narrow.** Only
  `main.css` is enforced; `tri-state-panel.css` (project-owned but
  not prettier'd) currently has 21 single-quote strings and could
  diverge further as the tri-state UI evolves in v1.7.x.  If the
  tri-state panel matures into a stable surface, consider extending
  the guard to it in a future R-cycle (~5 minutes' work: add the
  path to `DEFAULT_TARGETS`, set baseline to the current count,
  watch for regressions).

## Cross-cutting follow-ups (Code Review #11 work items)

| ID   | Severity     | Item                                                                                                                          | Owner suggestion                                                                                                                                                                |
| ---- | ------------ | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-1  | Low          | CHANGELOG markdown-link example trap (chore `1b96a47`): make `_MD_LINK_RE` backtick-aware or document the convention.        | **DONE in R177** — landed inline-code stripping + fenced-code-block state machine in `tests/test_docs_links_no_rot.py::_extract_local_targets`, plus 3 regression tests covering placeholder ignore + real link preservation. |
| F-2  | Informational | Promote `?template=PULL_REQUEST_TEMPLATE.zh-CN.md` discoverability.                                                          | Track over the next 2 weeks via PR-create traffic; if zero Chinese PRs come through, move to option-1 inline link.                                                              |
| F-3  | Low          | Extend R174 CSS quote guard to `tri-state-panel.css` once the tri-state UI surface stabilises.                               | Track separately; ~5 min in a future R-cycle.                                                                                                                                   |
| F-4  | Low          | Detect line-number drift between `docs/noise-levels.md` (EN) §5 anchor table and the actual `webview-ui.js` / `extension.ts`. | Defer to v1.7.x P1 / P3 consumption — those changes will naturally rewrite the anchor table and force both copies to update.                                                    |

## Test posture

| Surface                                | Tests                                                                                                                                                              | Status     |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- |
| Dual-path predefined_options parity    | `tests/test_predefined_options_dual_path_parity_cr10_f3.py` (11)                                                                                                   | All pass   |
| CSS quote consistency                  | `tests/test_css_quote_consistency_r174.py` (28)                                                                                                                    | All pass   |
| Docs link rot + must_cover             | `tests/test_docs_links_no_rot.py` (2 — must_cover grew from 10 → 12 entries with R176)                                                                             | All pass   |
| Noise levels anchors                   | `tests/test_noise_levels.py` (6 — A1-A4, D1-D2, T6 keyword)                                                                                                        | All pass   |
| Locale parity (sanity over R175)       | `scripts/check_i18n_locale_parity.py` + `check_i18n_orphan_keys.py` + `check_i18n_duplicate_values.py` + `check_i18n_locale_shape.py` + `check_i18n_param_signatures.py` | 0 issues |
| Pre-commit chain                       | ruff lint + format + trailing-whitespace + EOF + yaml/json/toml + merge-conflict + large-files + line-ending + debug-statements + R66 brand-color + R174 quote     | All green  |

Full regression: **4943 passed, 2 skipped, 0 failed, 0 warning (under
`-W error`) (0:02:16)**.

## Ready-to-tag posture

✓ All cycle commits land cleanly with pre-commit hooks (R66 brand-
colour + R174 quote-consistency + standard chain).

✓ No outstanding `WARN` / `error` from project-internal lint chain
under strict `-W error`.

✓ CHANGELOG.md has dedicated entries for every R-tag in the cycle
plus the link-rot chore.

✓ All 4 follow-ups from CR#10 are accounted for: F-1 / F-3 DONE in
R174 / R173; F-2 / F-4 explicitly observation / deferred (no action
required for tag).

✓ Both README.md (English) and README.zh-CN.md (Simplified Chinese)
mirror each other after R175 governance docs split.  `.github/`
file pairs match.  `docs/noise-levels.md` + `noise-levels.zh-CN.md`
pair complete.

Recommendation: **clear for v1.6.4 / v1.7.0 tagging** once
`bump_version.py` lands.  No blocking issues identified.

---

> Generated by Code Review #11 (post-R176) — file uses the
> `.tmp.md` suffix per the R168 docs-naming policy: this is a
> single-cycle review artefact, not a long-lived design document.
