# Contributor guide — Invariant tests

> **What this guide is.** A pattern catalogue for the
> `tests/test_*_invariant_*.py` family that this repository uses
> heavily. Read this before adding a new feature that needs
> long-term protection against silent decay; read this before
> _deleting_ an invariant test (so you understand what you're
> giving up); read this if you're confused why CI just failed
> on a test that looks like it tests nothing runtime-y.

> **What this guide is not.** A general testing tutorial. For
> classic unit / integration / end-to-end discipline see
> [`docs/lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md)
> and the existing test files.

> **简体中文版本**: [`contributor-guide-invariant-tests.zh-CN.md`](contributor-guide-invariant-tests.zh-CN.md).

## 1. What is an invariant test?

An **invariant test** asserts a structural property of the codebase
or its outputs that **must remain true across refactors**. It is
not a behavioural test (which asserts what the code _does_ at
runtime). It is a contract test for the codebase shape itself.

Three example invariants that this repo currently locks:

- **R220 / R224**: every `aiia_*` metric name referenced inside
  `docs/observability/grafana-dashboard*.json` must substring-
  exist in `src/ai_intervention_agent/web_ui_routes/system.py`.
  Without this, renaming a metric in `system.py` silently breaks
  the imported Grafana dashboard, and ops doesn't notice until
  the panel goes blank.
- **R217**: `src/ai_intervention_agent/static/js/state.js` and
  `packages/vscode/webview-state.js` must be **byte-identical**.
  Without this, a bug fix in one file silently leaves the other
  carrying the original bug.
- **R215**: the `needed` tuple in `scripts/smoke_test_r50.py`
  must list every scalar key in the `SSEBusStatsSnapshot`
  TypedDict in `task.py`. Without this, adding a new SSE
  observability field silently fails to verify in the production
  smoke test.

Invariant tests are cheap (most run in milliseconds) but pay
back **every refactor**, **every code review**, and **every
contributor onboarding**.

## 2. When to write one — decision tree

Before adding a feature, ask:

1. **Will the feature's correctness depend on multiple files
   staying in sync?**
   - If yes → invariant test almost certainly warranted.
   - If no → maybe not; behavioural tests suffice.
2. **Is the sync rule something a code review would catch reliably?**
   - "All metric names must match between dashboard JSON and
     Python source" — a reviewer would miss this 1 time in 10.
     **Write the invariant.**
   - "`max_attempts` must be a positive integer" — a reviewer
     catches this 100% of the time. Don't bother.
3. **Will the feature outlive its current author?**
   - Yes (almost certainly, in any healthy project) → write the
     invariant so the next contributor doesn't accidentally
     unwind the design decision.
4. **Is the failure mode silent?**
   - "Grafana panel renders blank" — silent. **Write the invariant.**
   - "App crashes immediately on startup" — loud. Don't bother;
     normal CI catches it.
5. **Is the cost of the failure higher than the cost of the test?**
   - Tests cost ~30 minutes to write + maintain.
   - Failures cost hours-to-days of debugging + a user-visible
     outage. **Almost always: write the invariant.**

## 3. Five recurring patterns

This repo has accumulated **12+ invariant tests across 12 R-cycles**
(R212, R213, R215, R216, R217, R219, R220, R221, R222, R223, R225,
R226). They cluster into five reusable patterns.

### Pattern A — Static-source string-presence check

**Use case**: lock a piece of code to "never contain X" or
"always contain X".

**Example**: `tests/test_notification_manager_console_noise_invariant_r216.py`
asserts `src/ai_intervention_agent/static/js/notification-manager.js`
contains **zero** `console.log(` calls (they should be
`console.debug(` for production-quiet operation).

**Recipe**:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "src" / "..." / "your_file.js"


def test_no_console_log_calls() -> None:
    source = TARGET.read_text(encoding="utf-8")
    count = source.count("console.log(")
    assert count == 0, (
        f"{TARGET.name} contains {count} console.log(...) call(s); "
        "should be console.debug(...) for production-quiet operation."
    )
```

**When to upgrade** to an AST scan (Pattern B):

- The string is also a substring of unrelated comments / docstrings
  that would cause false positives.
- You need to count call-sites accurately (`console.log(` inside a
  string literal would otherwise count).
- You need to enforce "every call to X has a corresponding call
  to Y" (cross-call invariants).

### Pattern B — AST-based call-site enumeration

**Use case**: count or constrain function calls / class
references at a structural level.

**Example**: `tests/test_sse_event_schemas_r198.py` walks every
`*.py` file under `src/`, parses with `ast.parse`, finds every
`_sse_bus.emit("<literal>", ...)` call, and asserts each literal
event type appears in the `KNOWN_SSE_EVENTS` registry of
`sse_event_schemas.py`.

**Recipe**:

```python
import ast
from pathlib import Path

def _emit_event_types(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "emit"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.add(node.args[0].value)
    return found
```

**Why AST over regex**: regex matches the string `"emit"` inside
comments, doc strings, and other functions named `emit`. AST sees
only real method invocations.

### Pattern C — JSON / YAML structural check

**Use case**: lock the structure of a config / data file
shipped with the project.

**Example**: `tests/test_grafana_dashboard_invariant_r220.py`
parses `docs/observability/grafana-dashboard.json`, asserts:

- `schemaVersion` is in the supported Grafana 10–11 range
- `uid` is the stable `aiia-overview-r220` value
- `panels` count is exactly 7 (changes to layout are deliberate
  edits, not accidents)
- every panel has a non-empty unique title
- every `aiia_*` metric in panel targets exists in `system.py`

**Recipe**:

```python
import json
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "docs" / "..."


def test_dashboard_structure() -> None:
    data = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    panels = data.get("panels") or []
    assert len(panels) == 7, (
        f"Panel count drifted: expected 7, got {len(panels)}. "
        "If you intentionally added/removed panels, also update "
        "this test's expected count."
    )
    titles = [p.get("title") for p in panels]
    assert len(titles) == len(set(titles)), "Duplicate panel titles"
```

**Pro tip**: when locking a count (panels, fields, options), add
a comment in the test that says "if you intentionally change
this, also update the expected count". Without it, the next
contributor adding a panel will spend 10 minutes wondering why
their commit failed CI.

### Pattern D — Bilingual locale parity

**Use case**: the project ships `en.json` + `zh-CN.json`; new
keys must be present in both, message lengths must be in a
reasonable ratio range (catches accidental empty translations).

**Example**: `tests/test_notification_fallback_toast_invariant_r214.py`
asserts every `status.notifFallback*` key in `en.json` has a
matching key in `zh-CN.json`, and the Chinese length is within
[0.4, 2.5]× the English length (catches truncated translations
and runaway-verbose ones).

**Recipe**:

```python
import json
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "src" / "..." / "static" / "locales"


def test_bilingual_key_parity() -> None:
    en = json.loads((LOCALES / "en.json").read_text())
    zh = json.loads((LOCALES / "zh-CN.json").read_text())

    def flatten(prefix: str, obj: dict) -> dict[str, str]:
        result: dict[str, str] = {}
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(flatten(full_key, v))
            elif isinstance(v, str):
                result[full_key] = v
        return result

    en_keys = flatten("", en)
    zh_keys = flatten("", zh)
    missing_in_zh = set(en_keys) - set(zh_keys)
    assert not missing_in_zh, f"zh-CN missing keys: {sorted(missing_in_zh)}"
```

**Don't forget**: when adding new i18n keys, also run
`uv run python scripts/gen_pseudo_locale.py` to regenerate the
`_pseudo/pseudo.json` locale that other tests check.

### Pattern E — Cross-tool / cross-file byte parity

**Use case**: two files must be **byte-identical** because they
are meant to be the "same" code in different distribution
contexts (e.g. shared logic between Web UI and VS Code webview).

**Example**: `tests/test_state_machine.py::TestJsSync::test_two_js_files_are_byte_identical`
asserts `src/ai_intervention_agent/static/js/state.js` and
`packages/vscode/webview-state.js` have identical bytes. The
files are intentionally duplicated rather than imported because
the VS Code webview cannot reach files outside `packages/vscode`
without inflating the .vsix.

**Recipe**:

```python
import hashlib
from pathlib import Path

TWIN_A = Path(__file__).resolve().parent.parent / "src" / "..."
TWIN_B = Path(__file__).resolve().parent.parent / "packages" / "..."


def test_twins_are_byte_identical() -> None:
    a_hash = hashlib.sha256(TWIN_A.read_bytes()).hexdigest()
    b_hash = hashlib.sha256(TWIN_B.read_bytes()).hexdigest()
    assert a_hash == b_hash, (
        f"{TWIN_A.relative_to(TWIN_A.parents[3])} and "
        f"{TWIN_B.relative_to(TWIN_A.parents[3])} are no longer "
        "byte-identical. If you fixed a bug in one, copy the same "
        "fix to the other; the duplication is deliberate because "
        "the VS Code webview cannot import files outside packages/vscode."
    )
```

**Mid-cycle drift R217 caught**: demoting `console.log` to
`console.debug` in `state.js` without applying the same
change in `webview-state.js` broke this test mid-PR; one minute
to fix vs hours of "why does this work in browser but not in
VS Code?" debugging later.

## 4. Anti-patterns to avoid

- **Don't write an invariant that duplicates a behaviour test.**
  If `test_handler_returns_200_on_valid_input` already passes
  whenever the handler is sane, you don't also need
  `test_handler_function_exists`.

- **Don't lock a count that is naturally going to grow.**
  `assert len(items) == 7` is good for "panel count of a
  finished dashboard". `assert len(items) == 7` is **bad** for
  "number of supported MCP tools" — that grows.
  Use `assert len(items) >= 7` for "grows monotonically" or
  `assert 7 <= len(items) <= 50` for "stays within a sane band".

- **Don't read the same file three times in three tests.**
  Cache the parse result in a module-level constant or a
  `setUpModule()` so 30 invariants don't compound 30 ASTs.

- **Don't write an invariant test that doesn't say WHY in its
  docstring.**
  Future you will not remember why "metric name parity" matters
  6 months from now. Write the docstring as if explaining to a
  contributor who just landed and asked "can I delete this test
  please, it's failing my PR".

- **Don't make the invariant test require ground-truth data
  that doesn't exist in the repo.**
  If your test needs the production Prometheus instance to
  scrape metrics, it's a production smoke test, not an invariant
  test. Move it to `scripts/smoke_test_*.py` and call from a
  dedicated CI job instead.

## 5. Workflow

1. Decide an invariant is warranted (use §2 decision tree).
2. Pick the most relevant pattern from §3.
3. Create `tests/test_<feature>_invariant_r<NNN>.py` named
   after the R-cycle landing the invariant.
4. Open with a multi-line module docstring explaining:
   - which R-cycle added this and why
   - what specific drift the test prevents
   - links to the CR / CHANGELOG entry that motivates it
   - the cases the test covers (numbered list)
5. Write the test using one of the recipes above. Prefer
   `unittest.TestCase` subclasses (matches the rest of the repo).
6. Run `uv run pytest tests/test_<feature>_invariant_r<NNN>.py`
   to confirm green on the current tree.
7. Deliberately break the invariant in your dev branch (e.g.
   rename a metric, add a missing key) and confirm the test
   **fails** with an actionable message. **If the message is
   not actionable, rewrite it.**
8. Restore the working tree, commit the test along with the
   feature it protects, and add a CHANGELOG entry citing the
   R-cycle number.

## 6. Repository-wide invariant test catalogue

The following R-cycles introduced invariant tests covering the
listed surface. New invariants should follow the same naming
pattern (`tests/test_<topic>_invariant_r<NNN>.py`) and the same
docstring template.

| R-cycle | Test file                                                               | Invariant type             | Locks                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------- | ----------------------------------------------------------------------- | -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R212    | `tests/test_sse_schema_validate_contract_r212.py`                       | Cross-module               | R205 schema validation toggle ↔ R210 stats snapshot consistency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| R213    | `tests/test_static_precompress_production_invariant_r213.py`            | Filesystem                 | Production static assets have matching `.gz` + `.br` mirrors                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| R215    | `tests/test_smoke_test_r50_field_drift_invariant_r215.py`               | Cross-file                 | `smoke_test_r50.py` `needed` tuple ↔ `SSEBusStatsSnapshot` TypedDict                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| R216    | `tests/test_notification_manager_console_noise_invariant_r216.py`       | Pattern A                  | Zero `console.log(` in `notification-manager.js`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| R217    | `tests/test_static_js_console_log_demotion_invariant_r217.py`           | Pattern A                  | Zero `console.log(` in 9 project-owned JS files                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| R219    | `tests/test_changelog_inline_code_lint_r219.py`                         | Pattern A                  | CHANGELOG.md uses single-backtick (not RST double-backtick) inline code style                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| R220    | `tests/test_grafana_dashboard_invariant_r220.py`                        | Pattern C                  | Grafana overview dashboard ↔ `system.py` `/metrics` parity                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| R221    | `tests/test_vscode_webview_console_noise_invariant_r221.py`             | Pattern A                  | Zero `console.log(` in `packages/vscode/` project-owned JS                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| R222    | `tests/test_readme_related_projects_invariant_r222.py`                  | Pattern D                  | Bilingual README "Related projects" tables stay in sync                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| R223    | `tests/test_settings_shortcuts_full_help_hint_invariant_r223.py`        | Pattern D                  | Settings panel keyboard shortcut hint i18n parity                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| R224    | `tests/test_grafana_dashboard_notif_providers_invariant_r224.py`        | Pattern B                  | Per-provider notification dashboard JSON parity with `system.py` metrics                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| R225    | `tests/test_remote_environment_detector_r225.py`                        | Mixed (A + D)              | SSH/WSL detector contract + `web_ui.py` integration guards                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| R226    | `tests/test_precompress_pre_commit_hook_invariant_r226.py`              | Pattern C                  | `.pre-commit-config.yaml` precompress freshness hook is registered + correct                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| R227    | `tests/test_invariant_test_guide_catalogue_r227.py`                     | Pattern C + D              | This very catalogue references only real test files + bilingual parity                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| R228    | `tests/test_shortcuts_notification_body_completeness_invariant_r228.py` | Pattern D + cross-file     | `Ctrl+/` notification body lists every shortcut + cross-checks `keyboard-shortcuts.js`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| R229    | `tests/test_submit_btn_disabled_visible_invariant_r229.py`              | Pattern A + Pattern C      | CSS `:disabled` rule exists for both themes + JS no longer writes inline color for the submit button                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| R230    | `tests/test_decorative_svgs_aria_hidden_invariant_r230.py`              | Pattern A                  | Every `<svg>` in `web_ui.html` has `aria-hidden="true"` + `focusable="false"` (a11y / WCAG 1.1.1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| R232    | `tests/test_icon_only_buttons_aria_label_invariant_r232.py`             | Pattern A                  | Every icon-only `<button>` / `<a role=button>` has non-empty `aria-label` / `aria-labelledby` (a11y / WCAG 4.1.2, post-R230 follow-up)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| R233    | `tests/test_readme_factual_claims_invariant_r233.py`                    | Pattern B + Pattern D      | README factual claims (test count, subtest count, release-pipeline job count) stay within tolerance of canonical sources (`release.yml`, `pytest --collect-only`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| R234    | `tests/test_feedback_textarea_disabled_css_invariant_r234.py`           | Pattern A                  | `.feedback-textarea:disabled` CSS rule exists for both themes with all 4 visual cues (background/color/cursor/border-color) + light rule uses `!important`; companion JS-inline-removed assertion lives in R229 test file                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| R235    | `tests/test_form_inputs_accessible_name_invariant_r235.py`              | Pattern A                  | Every `<input>` (non-hidden/submit/button/reset/image) + every `<textarea>` has accessible name via wrapping `<label>` / `<label for>` / `aria-label` / `aria-labelledby` / `aria-hidden=true + tabindex=-1` (a11y / WCAG 4.1.2, post-R230/R232 follow-up)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| R236    | `tests/test_ty_precommit_hook_invariant_r236.py`                        | Pattern B + Pattern A      | `ty-check` hook stays in `.pre-commit-config.yaml` at default `[pre-commit]` stage with `ty check` entry filtering `*.py`; `ci_gate.py` still invokes `ty` (pre-commit is fast shadow, CI is source of truth). Prevents v1.7.5-style abandoned release.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| R237    | `tests/test_dialog_aria_compliance_invariant_r237.py`                   | Pattern A                  | Every `role="dialog"` element has `aria-modal="true"` + (`aria-labelledby` referencing an existing id, or `aria-label`) + starts hidden (class `hidden` / `[hidden]` attr). WAI-ARIA 1.2 + WCAG 4.1.2 lock. Cycle 14 a11y wave 4 (R230→R232→R235 was about controls; R237 covers the modal layer).                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| R238    | `tests/test_modal_focus_trap_invariant_r238.py`                         | Pattern B                  | Both modal dialogs (`#code-paste-panel` + `#settings-panel`) implement a Tab/Shift-Tab focus trap (`_modalFocusTrap` in `app.js` + `_settingsFocusTrap` in `settings-manager.js`) using the standard W3C focusable selector + `offsetParent !== null` visibility filter, and close handlers restore focus to opener (`#feedback-text` / `#settings-btn`). R237's declarative ARIA companion + this imperative focus-management contract.                                                                                                                                                                                                                                                                                                                              |
| R239    | `tests/test_star_counts_freshness_invariant_r239.py`                    | Pattern D                  | README "Related projects" star-count snapshot date ("last reviewed YYYY-MM" / "最近核对：YYYY-MM") must be parseable, not in the future, within 12 months of today (overridable via env `R239_STAR_COUNT_MAX_AGE_MONTHS`), and consistent across EN+ZH READMEs. Pattern D drift-detection.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| R240    | `tests/test_modal_inert_background_invariant_r240.py`                   | Pattern B                  | Both modal open functions (`showSettings`, `openCodePasteModal`) mark `.container` (the `role="main"` wrapper) as `inert` and their close functions clear it. Both use `try { el.inert = … } catch { setAttribute("inert", …) }` defensive pattern. Completes a11y wave 4 trilogy with R237 (ARIA) + R238 (focus trap): blocks mouse, keyboard, and AT from reaching background while modal is open.                                                                                                                                                                                                                                                                                                                                                                  |
| R241    | `tests/test_inert_helper_dry_invariant_r241.py`                         | Pattern B                  | `_safelySetInert(el, value)` DRY helper exists in both `app.js` (top-level function) and `settings-manager.js` (class method) with identical branch behavior. Call sites must use the helper — no `container.inert = …` inline writes outside the helper definition. Closes F-cycle15-2 from CR#28 (extracts R240's 4× duplicated try/catch).                                                                                                                                                                                                                                                                                                                                                                                                                         |
| R242    | `tests/test_minify_precommit_hook_invariant_r242.py`                    | Pattern B                  | `check-static-minified-fresh` pre-commit hook present, entry runs `scripts/minify_assets.py --check`, files filter matches `static/(css\|js)`, hook is not banished to `manual`/`pre-push`, companion script still exists with `--check` flag. R242 closes the silent-stale-`.min.js`/`.min.css` bug surfaced in R234/R238/R240/R241 — same problem-shape as R226 (precompress freshness), now solved on the second build-artifact chain.                                                                                                                                                                                                                                                                                                                             |
| R243    | `tests/test_get_minified_file_freshness_r243.py`                        | Pattern A (runtime)        | `_get_minified_file()` rejects stale `.min` candidates at request time (mtime < source → fallback to source + WARN-once-per-file). End-to-end behavioural test with real tempdir files: fresh-min chosen, stale-min rejected, WARN dedup per-file (different files warn independently), explicit `.min` request still passes through, missing `.min` still falls back, `OSError` on `stat()` doesn't crash the static endpoint. R243 is the belt-and-suspenders runtime layer of the same defense R242 covers at commit time (covers `--no-verify` and pre-existing stale files the hook never inspects).                                                                                                                                                             |
| R244    | `tests/test_modal_not_self_inert_invariant_r244.py`                     | Pattern B                  | Fix R240 cascade self-inert bug: both modals live INSIDE `.container`, so the old `container.inert = true` made the modal itself inert (silently broke clicks/focus). New helper `_setContainerSiblingsInert(openModalEl, value)` exists in both `app.js` (top-level fn) and `settings-manager.js` (class method); it iterates `container.children` and skips `openModalEl`. All four modal open/close paths (`openCodePasteModal`/`closeCodePasteModal`/`showSettings`/`hideSettings`) must call the new helper with the panel element; regression guard forbids `container.inert = …` / `_safelySetInert(document.querySelector(".container"), …)` in any modal path. Closes a 4-cycle silent UX-killer that escaped R240 because R240's tests were Pattern B only. |
| R245    | `tests/test_dialog_not_in_inert_subtree_invariant_r245.py`              | Pattern A++ (HTML cascade) | Cascade-aware structural invariant generalising R244 to any future modal addition. Parses `web_ui.html` to collect every `role="dialog"` element and its ancestor chain to `<body>`; parses `app.js` + `settings-manager.js` to extract DANGEROUS direct-inert selectors (e.g. `.container`); fails if any dialog has such a selector in its ancestor chain (UNLESS the JS uses the R244 sibling-iteration helper that explicitly skips the open dialog). Confirms it catches the original R240 buggy pattern (see test docstring). Limitations: static-only, no runtime DOM mutation (e.g. JS createElement modals — F-cycle16-playwright remains the canonical guard for those).                                                                                    |
| R246    | `tests/test_build_artifact_freshness_matrix_invariant_r246.py`          | Pattern B                  | Complete the build-artifact freshness pre-commit matrix begun by R226 (precompress) + R242 (minify). Promotes 4 remaining generators (`gen_i18n_types`, `gen_pseudo_locale`, `generate_docs` × 2 langs, `generate_pwa_icons`) from CI-only to pre-commit hooks. 5 hook ids required: presence + correct `--check` invocation + scoped `files` filter + non-relegation + companion script + `--check` flag + ci_gate.py still invoking the non-PWA scripts (defense in depth for `--no-verify` bypass). After R246, the matrix is uniform: all 6 build-artifact chains have both pre-commit fail-fast and ci_gate canonical-truth layers.                                                                                                                              |
| R412    | `tests/test_feat_openapi_property_description_completeness_r412.py`     | Pattern A + ratchet        | **v3.10.2 OpenAPI 文档质量矩阵第二个 sub-pattern**. API contract 9th 应用. 静态扫描 `web_ui_routes/*.py` 所有 OpenAPI YAML properties; ratchet 策略锁非 envelope property 的 description 覆盖率 ≥ 70% (R418 ratchet from 45%); envelope 字段 (`status` / `success` / `message` / `error`) 显式 whitelist (REST 通用响应包装含义全球一致). future cycle 可加 description 推 coverage 至 80%+, 然后 ratchet 上调 `MIN_NON_ENVELOPE_DESC_COVERAGE`. ratchet 设计 = 持续改进 + 强制单调递增。  |
| R414    | `tests/test_feat_routes_mixin_matrix_negative_validation_r414.py`       | Pattern B + meta-invariant | **第 14 维度 (Mixin route registration matrix) 第 2 应用 + 项目首个 meta-invariant**. R406 是 positive-only test (只验证当前状态 OK), R414 通过 synthetic 输入验证 R406 的辅助函数在真实漂移场景下会正确 fire (覆盖 layer 2/3/4/naming 4 个 negative 场景). meta-invariant 价值: 保证 R406 在 future 真实漂移时仍然 fire, 而不是因为某次 refactor 把 R406 静默 ignored. self-validation pattern 可扩展到 R404/R412/R408 等其他 invariant; 累计 3+ 应用可提升为 v3.11 系列命名 (meta-invariants).                       |
| R416    | `tests/test_feat_version_quintet_sync_invariant_r416.py`                | Pattern A + Release infra  | **release infrastructure 强化 — 防 v1.7.5-style 多源 version drift release**. Lock 5 个版本来源严格相等: `pyproject.toml` / `CITATION.cff` / `package.json` / `packages/vscode/package.json` / `package-lock.json` (root + packages.""). 结构化 invariant 不锁具体版本号, 每次 release 不需修改 (与 R341/R382/R410 等具体版本锁互补形成 "release 时做对 + release 间不退" 双层保护). 历史失败模式: v1.7.5 release 因 `pyproject.toml` 已 bump 但 `package.json` 未同步 → release 失败 (`docs/release-checklist.md:71`).                  |
| R418    | `tests/test_feat_openapi_property_description_ratchet_r418.py`          | Pattern B + meta-invariant | **R412 ratchet uplift + real improvement + self-validation 2nd 应用**. R412 启动 v3.10.2 锁 baseline 45%, R418 在同 cycle 实施 real improvement: (1) 加 25 个 description 到 task.py + feedback.py 高频字段 (task_id / created_at / auto_resubmit_timeout / remaining_time / server_time / 等), (2) ratchet up `MIN_NON_ENVELOPE_DESC_COVERAGE`: 0.45 → 0.70 (实际 coverage 50% → 75%). 项目第一个 **invariant + 实施改进 + ratchet up** 三位一体 commit. ratchet 模式可扩展到 doc-parity / i18n / security header 等其他 ratchet 型 invariant.        |
| R422    | `tests/test_feat_openapi_error_response_schema_parity_r422.py`          | Pattern A + ratchet        | **v3.10.3 OpenAPI 文档质量矩阵第 3 sub-pattern — error path 完整性**. API contract 11th 应用 (含 v3.10.1 endpoint summary R404 + v3.10.2 property description R412/R418). 静态扫描 `web_ui_routes/*.py` OpenAPI YAML 所有 4xx/5xx response (status code 400-599), 统计有 `schema:` 字段的比例; ratchet 锁 `MIN_ERROR_RESPONSE_SCHEMA_COVERAGE` ≥ 0.05 (当前 3/51 = 5.88%). 业务价值: 当前 51 个 error response 仅 3 个 (5.88%) 有 schema, 客户端无法静态消费错误响应结构, 大量 retry 逻辑靠 try-catch; future cycle 加 schema 推 coverage → ratchet 上调 baseline (推荐节奏 0.05→0.15→0.30→0.50→0.70→0.90). ratchet 模式第 3 应用 (R412/R418/R422). |
| R424    | `tests/test_feat_doc_parity_negative_validation_r424.py`                | Pattern B + meta-invariant | **meta-invariant 第 3 应用 — 元方法学层 (维度 15) 工业化里程碑**. R414 (Mixin matrix negative) → R418 (R412 ratchet uplift validation) → **R424 (doc-parity R400 negative)** 形成 3 应用工业化, 元方法学层 (v3.11 候选) 正式从孵化进入稳定 pattern. 通过 synthetic drift 输入 (H2 count mismatch / unmapped H2 / code block 不平衡 / link 差异 > 3) 反向验证 R400 的辅助函数 (`_extract_h2_headings`, `SECTION_MAPPING`, `_count_code_blocks`, `_count_external_links`) 在真实漂移场景下能正确 fire, 防止 R400 silently broken (positive-only test 的盲点). doc-parity invariant 的 invariant, 守护方法学入口文档不被静默双语漂移。       |
| R436    | `tests/test_feat_openapi_error_schema_ratchet_3rd_r436.py`              | Pattern B + meta-invariant | **R422 ratchet uplift 第 3 次 + meta-invariant 第 8 应用 + 实施改进 + ratchet up 三位一体 第 5 次 — system.py admin endpoints 焦点**. R422 → R428 → R432 → **R436 (cycle-50 #A1, +8 schemas, coverage → 52.94%, ratchet → 0.50)**. cycle-50 内为 `system.py` admin endpoints (open-config-file 400/403/500 + healthz 503 + set-log-level 400/403) + `task.py` GET /api/tasks/<id> 404/500 添加 8 个 schema, 把 4xx/5xx schema coverage 推到 52.94%, 然后 ratchet 至 0.50。**ratchet 模式累计应用 7 (R412/R418/R422/R426/R428/R432/R436) → 巩固期完全成熟**, "实施改进 + ratchet up 三位一体" 累计 5 应用 → pattern 完全工业化, 元方法学层 8 应用进入深化期。 |
| R438    | `tests/test_feat_i18n_untranslated_negative_validation_r438.py`         | Pattern B + meta-invariant | **R350 (i18n untranslated keys audit) 负面自验证 — i18n meta-invariant 子模式第 1 次应用 + 元方法学层第 9 应用 → 完全工业化阈值达成**. cycle-50 #B1. 合成 4 种 i18n drift 场景 (100% 未翻译 / 50% 未翻译 / 平衡翻译 / _meta 元数据过滤), 反向验证 R350 的 `_flatten_strings` helper + 比例上限算法在 locale 漂移场景能正确 fire。**元方法学层 (维度 15) 累计应用 9 (R414/R418/R424/R426/R428/R430/R432/R436/R438) → 完全工业化阈值达成**, 形成 3 个 meta-invariant 子模式: doc-parity (R424) / API contract (R430) / **i18n (R438 首发, 守护 R350+R353+R366+R374 共 4 个 i18n invariants)**。i18n 是 user-facing 体验最关键的维度之一 (主 app + VS Code 共 4 locales), R350 静默失效 = 漏译可能不被发现伤中文用户。 |
| R440    | `tests/test_feat_openapi_error_schema_ratchet_4th_r440.py`              | Pattern B + meta-invariant | **R422 ratchet uplift 第 4 次 + meta-invariant 第 10 应用 + 7 成决胜 threshold 突破 — task.py countdown ops + feedback.py 429 焦点**. R422 → R428 → R432 → R436 → **R440 (cycle-51 #A1, +9 schemas, coverage → 70.59%, ratchet → 0.70)**. cycle-51 内为 `task.py` POST /api/tasks/<id>/extend (400/404/422/500) + POST /api/tasks/<id>/freeze (400/404/409/500) + `feedback.py` POST /api/submit 429 (含 retry_after hint) 添加 9 个 schema, 把 4xx/5xx schema coverage 推到 70.59%, 然后 ratchet 至 0.70。**ratchet 模式累计应用 8 (R412/R418/R422/R426/R428/R432/R436/R440) → 巩固期持续深化**, "实施改进 + ratchet up 三位一体" 累计 6 应用 → pattern 工业化深化期, 元方法学层 10 应用进入完全工业化深化期。 |
| R442    | `tests/test_feat_vscode_i18n_untranslated_negative_validation_r442.py`  | Pattern B + meta-invariant | **R353 (VS Code i18n untranslated audit) 负面自验证 — i18n meta-invariant 子模式第 2 次应用 + 元方法学层第 11 应用 → 完全工业化深化期**. cycle-51 #B1. 合成 5 种 VS Code locale drift 场景 (100%/50%/balanced/near-ceiling 7%/_meta 元数据过滤), 反向验证 R353 的 `_flatten_strings` helper + 8% ceiling 算法在 VS Code locale 漂移场景能正确 fire。**i18n meta-invariant 子模式从 1 应用 (R438) → 2 应用 (R442) 进入巩固期** (与 doc-parity / API contract 子模式形成可比的演化节奏)。VS Code extension 是 IDE 集成用户群入口, R353 静默失效 = 漏译可能直接 ship 到 marketplace 伤中文 IDE 用户群。 |
| R444    | `tests/test_feat_methodology_evolution_doc_parity_r444.py`              | Pattern B + meta-invariant | **v3.11 系列正式启动 + methodology evolution doc structure invariant + doc-parity 子模式第 7 应用 → 完全工业化深化期**. cycle-51 #C1. 创建 `docs/methodology-evolution.{md,zh-CN.md}` 作为 v3.0 → v3.11 方法学维度的 *single source of truth*, 并锁定其结构 (4 layer: bilingual SSoT 存在性 + structural parity heading/table 行 + v3.11 anchor 关键信息 + lineage marker)。**v3.11 系列正式命名** — 元方法学层 (从 R414 cycle-47 1st 应用到 R442 cycle-51 11th 应用 历经 5 cycle) 正式作为方法学维度命名为 v3.11, 与 doc-parity (v3.5) / perf-baseline (v3.6) 等老牌维度同级。**doc-parity 子模式累计应用 7** (R335 → R340 → R346 → R394 → R400 → R408 → R444) → 完全工业化深化期。任何新贡献者 (人 / agent) 想了解 invariant 测试方法学时, 现有 *单一权威来源* 可快速理解全部维度。 |
| R446    | `tests/test_feat_openapi_error_schema_ratchet_5th_r446.py`              | Pattern B + meta-invariant | **R422 ratchet uplift 第 5 次 + meta-invariant 第 12 应用 + production-quality threshold 突破 — notification.py reset + bark-test + system.py rotate-token 焦点**. R422 → R428 → R432 → R436 → R440 → **R446 (cycle-52 #A1, +6 schemas, coverage → 82.35%, ratchet → 0.80)**. cycle-52 内为 `notification.py` POST /api/reset-feedback-config 500 + POST /api/test-bark-notification 400/500 + `system.py` POST /api/rotate-token 403/500/429 (含 retry_after) 添加 6 个 schema, 把 4xx/5xx schema coverage 推到 82.35% (production-quality threshold), 然后 ratchet 至 0.80。**ratchet 模式累计应用 9 (R412/R418/R422/R426/R428/R432/R436/R440/R446) → 完全工业化深化期**, "实施改进 + ratchet up 三位一体" 累计 7 应用 → pattern 工业化深化期, 元方法学层 12 应用进入完全工业化深化期 + 1。 |
| R448    | `tests/test_feat_i18n_zh_tw_untranslated_negative_validation_r448.py`   | Pattern B + meta-invariant | **R366 (main app zh-TW untranslated audit) 负面自验证 — i18n meta-invariant 子模式第 3 次应用 + 元方法学层第 13 应用 → 完全工业化深化期 + 2**. cycle-52 #B1. 合成 5 种 zh-TW locale drift 场景 (100%/50%/balanced/near-ceiling 7%/_meta 元数据过滤), 反向验证 R366 的 `_flatten_strings` helper + 8% ceiling 算法在 zh-TW locale 漂移场景能正确 fire。**i18n meta-invariant 子模式从 2 应用 (R442) → 3 应用 (R448) 进入工业化阈值** (与 doc-parity 6 应用 / API contract 1 应用形成可比演化节奏)。zh-TW (繁体中文) 是台湾/香港 IDE 用户群关键 locale, R366 静默失效 = 漏译可能直接 ship 到 marketplace 伤台港用户。R448 完全复用 R442 模板 + zh-TW 适配, 证明 i18n 子模式有 *机械化复用* 能力。 |
| R452    | `tests/test_task_queue_counter_decision_r452.py`                        | Pattern C + perf decision  | **TaskQueue counter decision invariant**. Locks the measured decision to keep `get_task_count()` snapshot-based while the default `max_tasks=10`; maintained counters are deferred until benchmarks prove queue stats are a bottleneck at larger queue sizes, preventing unmeasured shared-state complexity from entering the hot path. |
| R457    | `tests/test_mcp_dynamic_tools_spike_r457.py`                            | Pattern A + spike contract | **FastMCP dynamic tool registration spike**. Locks local FastMCP 3.2.4 behavior before any future optional/conditional diagnostic tools are added: the stable `interactive_feedback` tool remains statically discoverable, dynamic `add_tool` round-trips metadata and annotations, duplicate name/version conflicts raise under `on_duplicate="error"`, and the current SDK API shape uses `on_duplicate` plus callable/preconstructed tool inputs. |
| R457    | `tests/test_predefined_options_defaults_ui_r457.py`                     | Pattern A + regression     | **Predefined option defaults frontend propagation**. Guards the user-facing default-checkbox path across the VS Code webview fallback, first-render state precedence, and legacy single-task Web UI; only explicit `true` backend defaults should preselect an option, preventing stale local state or falsey values from silently overriding configured defaults. |
| R432    | `tests/test_feat_openapi_error_schema_ratchet_2nd_r432.py`              | Pattern B + meta-invariant | **R422 ratchet uplift 第 2 次 + meta-invariant 第 7 应用 + 实施改进 + ratchet up 三位一体 第 4 次 — notification.py 焦点**. R422 (cycle-48 #B1 baseline 5%) → R428 (cycle-49 #A1, +8 schemas, coverage → 21.57%, ratchet → 0.15) → **R432 (cycle-49 #C1, +8 schemas, coverage → 37.25%, ratchet → 0.30)**. cycle-49 内为 `notification.py` (test-bark-notification 400/500 + trigger-task-notification 500 + notification-config 500 + GET /api/notification-config 500 + GET /api/get-feedback-config 500 + POST /api/update-feedback-config 400/500) 添加 8 个 schema, 把 4xx/5xx schema coverage 推到 37.25%, 然后 ratchet 至 0.30。ratchet 模式累计应用 6 (R412/R418/R422/R426/R428/R432), 元方法学层 7 应用进入超巩固期 + 1。 |
| R430    | `tests/test_feat_endpoint_summary_negative_validation_r430.py`          | Pattern B + meta-invariant | **meta-invariant 第 6 应用 — 元方法学层超巩固期 + API contract meta-invariant 子模式 1st app**. R414 → R418 → R424 → R426 → R428 → **R430** = 6 应用进入超巩固期, 与 doc-parity (6 应用) 并列成熟方法学维度。同时是 API contract pattern 第一次得到元保护层 — 把 meta-invariant 模式从 doc-parity / ratchet 扩展到 API contract 维度。通过 5 种 synthetic OpenAPI docstring drift (空 first-line / < 5 chars / > 200 chars / TODO marker / 待定 中文 marker) 反向验证 R404 的 `_extract_endpoint_summaries` / `FIRST_LINE_MIN_LEN` / `FIRST_LINE_MAX_LEN` / `PLACEHOLDER_MARKERS` 辅助函数能正确 fire, 防止 R404 silently broken。 |
| R428    | `tests/test_feat_openapi_error_response_schema_ratchet_r428.py`         | Pattern B + meta-invariant | **R422 ratchet uplift 1st + meta-invariant 5th 应用 + 实施改进 + ratchet up 三位一体 3rd 次**. R422 (cycle-48 #B1 baseline 5%) → **R428 (cycle-49 #A1, +8 schemas, coverage 5.88% → 21.57%, ratchet 0.05 → 0.15)**. cycle-49 内为 `feedback.py` (POST /api/update-feedback 400/500) + `task.py` (GET /api/tasks 500, GET /api/tasks/download 400/500, POST /api/tasks 400/409/500) 添加 8 个 schema, 把 4xx/5xx schema coverage 从 5.88% 推到 21.57%, 然后 ratchet `MIN_ERROR_RESPONSE_SCHEMA_COVERAGE` 至 0.15。ratchet 模式累计应用 R412/R418/R422/R426/R428 (**5 应用 = 工业化巩固期**)。元方法学层 (维度 15) 应用累计 5 (R414/R418/R424/R426/R428) 进入超稳定 + 与老牌方法学维度并肩。 |
| R426    | `tests/test_feat_openapi_property_description_ratchet_r426.py`          | Pattern B + meta-invariant | **R412 ratchet uplift 2nd + meta-invariant 4th 应用 + 实施改进 + ratchet up 三位一体 第 2 次**. R412 (cycle-47 #A1 baseline 45%) → R418 (cycle-47 #D1, +25 descriptions, coverage 50% → 75%, ratchet 45% → 70%) → **R426 (cycle-48 #D1, +14 descriptions, coverage 70% → 85%, ratchet 70% → 80%)**. cycle-48 内为 `notification.py` (bark / *Enabled / *Volume 通知配置字段) + `feedback.py` (predefined_options / task_id) + `system.py` (token rotation/status 元数据) 添加 14 个 description, 把非 envelope coverage 从 70.15% 推到 85.07%, 然后 ratchet `MIN_NON_ENVELOPE_DESC_COVERAGE` 至 0.80。元方法学层应用累计 4 (R414 / R418 / R424 / R426) 进入超稳定阶段。 |                                                                                                                              |

## 7. Further reading

- [`docs/lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md)
  — root causes of why silent decay defeats normal review.
- [`docs/code-reviews/`](code-reviews/) — every CR documents the
  follow-up backlog that drove the next batch of invariants.
- [`docs/release-recovery.md`](release-recovery.md) — the 13-step
  release checklist; many invariants exist specifically to make
  one of those steps automated.
