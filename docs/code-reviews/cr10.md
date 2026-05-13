# Code Review #10 — R155-R172 cycle

> Internal review of the R155 → R172 commit cluster, performed after
> commit `891fe9a` (R172 task-queue comment cleanup).  Reviewers
> preparing the v1.6.x release between v1.6.3 and v1.7.0 should walk
> this list before tagging.

## Cycle summary

| Tag | Hash | One-liner |
|---|---|---|
| R155 | `0ac9bd6` | Activity Dashboard **expanded-state** localStorage persistence + multi-tab sync (CR#9 F-3 / F-5 follow-ups) |
| R165 | `3cbb8a2` | **Feedback-loss defense (dual-layer)**: ``/api/tasks/<id>/close`` short-circuits completed tasks + exponential-backoff retry-before-close in `wait_for_task_completion` |
| R166 | `888276f` | Soft-limit relaxation: ``MAX_MESSAGE_LENGTH`` 10k → 1M / ``MAX_OPTION_LENGTH`` 500 → 10k / ``PROMPT_MAX_LENGTH`` 10k → 100k.  Hard byte-level DoS guard (10 MB) preserved |
| R167 | `1d06d46` | ``predefined_options`` shape convergence: drop ``predefined_options_defaults`` MCP parameter, recommend ``list[dict]`` |
| R168 | `582b81a` | Docs rename: drop R-cycle identifiers (8 files, ``.tmp.md`` for ephemeral artefacts) |
| R169 | `afc9f09` | README trim: move ``how-it-works`` / ``architecture`` / ``middleware`` / ``self-info`` / ``spec-compliance`` to ``docs/api{,.zh-CN}/index.md`` |
| —    | `73d9980` | CSS prettier reflow on ``main.css`` (no functional change) |
| R156 | `1ba566f` | Activity Dashboard logs-row ``[show 50]`` / ``[show 5]`` toggle (CR#9 F-4 follow-up) |
| R170 | `89932d8` | ``check_i18n_duplicate_values.py``: ``"Cancel"`` allowlisted (page.cancel vs quickPhrases.formCancel — both legitimate feature namespaces) |
| R171 | `970f26d` | README badge trim 10 → 5, logos + ``flat-square`` style, Open VSX × 3 + DeepWiki relocated to topical sections |
| R172 | `891fe9a` | ``task_queue.Task`` comment cleanup: stale ``TODO #3`` → R167-era dual-shape contract notes |

Net delta: **10 R-series commits + 1 CSS reformat, ≈ 1100 LoC source +
≈ 600 LoC test + ≈ 280 LoC docs.  Total test count climbed by 124 cases
(R156 alone).  All 4904 existing tests continue to pass (+ 2 skipped).
ci_gate-equivalent local lint chain (ruff / i18n parity / i18n shape /
i18n orphan / i18n no-CJK / brand colour / silent-failure baseline)
all green with 0 warning.**

## Strengths (what the cycle did well)

- **Defense-in-depth on data integrity (R165).** The single highest-
  impact ship in this cycle: combined a server-side short-circuit on
  ``/api/tasks/<id>/close`` (refuse to delete tasks that already
  carry user feedback) with a client-side exponential-backoff retry
  ``(0.0, 0.1, 0.25, 0.5, 1.0)``.  Crucially, refactored the Python
  ``try / except / finally + return`` semantics so a result recovered
  by retry in ``finally`` cannot be overridden by the ``except
  TimeoutError`` branch's resubmit response — a subtle Python control-
  flow trap that was caught by the test suite (R165's
  ``test_retry_recovers_after_multiple_jitters`` proved the failure
  mode before the refactor).

- **API design convergence (R167).** ``predefined_options`` shrunk
  from 3 shapes (``list[str]`` / ``list[dict]`` / ``list[str] +
  predefined_options_defaults``) to 2 (``list[str]`` / ``list[dict]``),
  matching modern industry norms (HTML ``<option selected>`` /
  React Select / JSON Schema ``enum + default``).  The legacy
  parallel-array shape is purged from the MCP-facing parameter
  surface but retained as the internal Task model representation
  for VS Code extension / external HTTP automation — clear dual-
  audience design without breaking either path.

- **README right-sizing (R169 + R171).** The cycle made README a
  marketing-first page (5 trust-signal badges, no ``how-it-works``,
  no Mermaid architecture) while migrating those deep-technical
  sections to ``docs/api{,.zh-CN}/index.md``.  Readers deciding
  "should I install this" now meet a 30-second pitch; readers deciding
  "how does this integrate" follow a single link.  Side benefit:
  badges visually upgraded from "grey-text" to "icon + label" with
  zero new external badge service dependency.

- **Lint-floor improvements stay observable (R170 / R172).** Both
  R170 ("Cancel" allowlist) and R172 (stale ``TODO #3`` cleanup)
  are pure-comment / pure-config changes, but each carries an
  R-tag, CHANGELOG entry, and rationale.  The repo treats output-
  noise reduction as a tracked QA improvement, not a "drive-by
  fix".  Future contributors can answer "why is 'Cancel' in
  ALLOWLIST_VALUES?" by reading R170's rationale rather than
  reverse-engineering the allowlist.

- **Feature parity additions (R155 + R156).** Activity Dashboard
  expanded-state + logs-row show-50 toggle close two long-standing
  Code Review #9 follow-ups (F-3, F-4, F-5).  Both use the same
  ``localStorage`` + schema-versioned key + allowlist-read pattern
  R150 established; F-5's "strict equality on schema version" lesson
  was scaled by R156 to ``LOGS_LIMIT_SCHEMA_VERSION`` (no ``>= v``
  comparisons).

## Risks / things to keep an eye on

- **Soft-limit ↔ hard-limit gap (R166).** ``MAX_MESSAGE_LENGTH``
  jumped 100× (10k → 1M), so the gap to the byte-level
  ``_PROMPT_REJECT_BYTES = 10 MB`` hard cap is now 10× rather than
  1000×.  A single 4-byte UTF-8 emoji burst could close that gap if
  someone pastes 2.5 M emoji.  Mitigation: ``task_queue`` already
  rejects at the 10 MB byte boundary, so the worst case is a UX
  "your prompt got rejected" rather than DoS.  But if we ever raise
  ``MAX_MESSAGE_LENGTH`` again, audit the byte gap first.

- **CSS prettier reformat (`73d9980`) is one-time.** The repo has
  no ``.prettierrc``, no pre-commit prettier hook for CSS — drift
  will silently re-accumulate.  Either land a CSS formatter
  pre-commit hook in the next cycle (rcssmin already in dev deps;
  prettier-css / stylelint a separate sup-chain weight), or accept
  the drift as v1.6.x-era hygiene.

- **VS Code Open VSX badges below-the-fold (R171).** Moving the
  Open VSX × 3 badges out of the README header into the "VS Code
  extension" section is the right call for the *Web UI default
  user*, but a *VS Code-first user* now has to scroll past three
  Open VSX entries to see them.  If extension install counts dip
  noticeably in the next 2 weeks vs the v1.6.3 baseline, consider
  pinning the Open VSX version badge back to the header (without
  the downloads / rating duplicates).

- **R167 silent-failure surface area.** The R167 commit removed
  ~30 lines of "parallel-array → dict-form merging" logic from
  ``server_feedback.interactive_feedback``.  The external HTTP path
  (VS Code plugin / scripts) still has its own parsing in
  ``web_ui_routes/task.py``.  If that path drifts (e.g. accepts an
  incompatible new alias the MCP path rejects), there's no test
  enforcing parity between the two surfaces.  Consider adding a
  small parity smoke if v1.7.x picks up another option-shape PR.

## Cross-cutting follow-ups (Code Review #10 work items)

| ID | Severity | Item | Owner suggestion |
|---|---|---|---|
| F-1 | Low | Land a CSS / Markdown formatter pre-commit hook to prevent the prettier-reflow situation R73d9980 cleaned up from re-accumulating. | **DONE in R174** — landed `scripts/check_css_quote_consistency.py` + `tests/test_css_quote_consistency_r174.py` (28 cases) + `.pre-commit-config.yaml` local hook.  Baseline-style guard (vs full prettier integration) scoped to `main.css` quote consistency.  Full prettier still deferred until cost/benefit shifts (see R174 docstring for retirement plan). |
| F-2 | Low | If extension install rate dips post-R171, revisit Open VSX header badge placement. | Track via [Open VSX](https://open-vsx.org/extension/xiadengma/ai-intervention-agent) downloads over the next 2 weeks. |
| F-3 | Low | Add a smoke test enforcing parity between MCP `interactive_feedback` ``predefined_options=[{label, default}]`` shape parsing and HTTP ``POST /api/tasks`` parallel-array shape parsing. | **DONE in R173** — landed `tests/test_predefined_options_dual_path_parity_cr10_f3.py` (11 cases covering label aliases + default aliases + mixed-form + truthy-bool normalisation + HTTP-side dict-rejection enforcement). |
| F-4 | Informational | The CSS file (`main.css`) is now > 9000 lines.  Not blocking, but consider whether to split into per-feature files in v1.7.x. | Tracked separately under perf / asset-pipeline roadmap. |

## Test posture

| Surface | Tests | Status |
|---|---|---|
| Activity Dashboard logs row + expand + show-50 | `tests/test_activity_dashboard_r152.py` (108) + `tests/test_activity_dashboard_logs_expand_r153.py` (62) + `tests/test_activity_dashboard_logs_show_more_r156.py` (34) | All pass |
| `predefined_options` shape | `tests/test_predefined_options_shape_r167.py` (14) + `tests/test_interactive_feedback_errors.py` (16) | All pass |
| Feedback-loss defense | `tests/test_server_functions.py::TestRetryFetchBeforeClose` + `TestRetryBackoffSequenceR165` (9) + `tests/test_web_ui_routes.py::TestCloseTask` (3) | All pass |
| Soft-limit relaxation | `tests/test_server_config.py` + `tests/test_feedback_char_counter_r138.py` + `tests/test_mcp_tools_doc_consistency.py` + `tests/test_submit_selected_options_validation.py` + `tests/test_server_functions.py::test_validate_long_*` | All pass |
| Docs link rot | `tests/test_docs_links_no_rot.py` (2 sweeping cases) | All pass |
| Locale parity | `scripts/check_i18n_locale_parity.py` + `check_i18n_orphan_keys.py` + `check_i18n_duplicate_values.py` + `check_i18n_locale_shape.py` + `check_i18n_param_signatures.py` | 0 issues |

Full regression: **4904 passed, 2 skipped, 0 failed (0:02:14)**.

## Ready-to-tag posture

✓ All cycle commits land cleanly with pre-commit hooks (ruff /
trailing whitespace / EOF / brand-colour drift guard / merge-conflict
markers).

✓ No outstanding `WARN` / `error` from project-internal lint
chain after R170 (Cancel allowlist).

✓ CHANGELOG.md has dedicated entries for every R-tag in the cycle
plus the CSS prettier reflow chore.

✓ Both README.md (English) and README.zh-CN.md (Simplified Chinese)
mirror each other (R169 + R171 cross-locale parity preserved).

Recommendation: **clear for v1.6.4 / v1.7.0 tagging** once
``bump_version.py`` lands.  No blocking issues identified.

---

> Generated by Code Review #10 (post-R172) — file uses the
> ``.tmp.md`` suffix per the R168 docs-naming policy: this is a
> single-cycle review artefact, not a long-lived design document.
