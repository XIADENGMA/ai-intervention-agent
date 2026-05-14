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

| R-cycle | Test file                                                     | Invariant type | Locks                                                                          |
| ------- | ------------------------------------------------------------- | -------------- | ------------------------------------------------------------------------------ |
| R212    | `tests/test_sse_schema_validate_contract_r212.py`             | Cross-module   | R205 schema validation toggle ↔ R210 stats snapshot consistency                |
| R213    | `tests/test_static_precompress_production_invariant_r213.py`  | Filesystem     | Production static assets have matching `.gz` + `.br` mirrors                   |
| R215    | `tests/test_smoke_test_r50_field_drift_invariant_r215.py`     | Cross-file     | `smoke_test_r50.py` `needed` tuple ↔ `SSEBusStatsSnapshot` TypedDict           |
| R216    | `tests/test_notification_manager_console_noise_invariant_r216.py` | Pattern A | Zero `console.log(` in `notification-manager.js`                               |
| R217    | `tests/test_static_js_console_log_demotion_invariant_r217.py` | Pattern A      | Zero `console.log(` in 9 project-owned JS files                                |
| R219    | `tests/test_changelog_inline_code_lint_r219.py`               | Pattern A      | CHANGELOG.md uses single-backtick (not RST double-backtick) inline code style  |
| R220    | `tests/test_grafana_dashboard_invariant_r220.py`              | Pattern C      | Grafana overview dashboard ↔ `system.py` `/metrics` parity                     |
| R221    | `tests/test_vscode_webview_console_noise_invariant_r221.py`   | Pattern A      | Zero `console.log(` in `packages/vscode/` project-owned JS                     |
| R222    | `tests/test_readme_related_projects_invariant_r222.py`        | Pattern D      | Bilingual README "Related projects" tables stay in sync                        |
| R223    | `tests/test_settings_shortcuts_full_help_hint_invariant_r223.py` | Pattern D   | Settings panel keyboard shortcut hint i18n parity                              |
| R224    | `tests/test_grafana_dashboard_notif_providers_invariant_r224.py` | Pattern B    | Per-provider notification dashboard JSON parity with `system.py` metrics       |
| R225    | `tests/test_remote_environment_detector_r225.py`              | Mixed (A + D)  | SSH/WSL detector contract + `web_ui.py` integration guards                     |
| R226    | `tests/test_precompress_pre_commit_hook_invariant_r226.py`    | Pattern C      | `.pre-commit-config.yaml` precompress freshness hook is registered + correct   |
| R227    | `tests/test_invariant_test_guide_catalogue_r227.py`            | Pattern C + D  | This very catalogue references only real test files + bilingual parity         |
| R228    | `tests/test_shortcuts_notification_body_completeness_invariant_r228.py` | Pattern D + cross-file | `Ctrl+/` notification body lists every shortcut + cross-checks `keyboard-shortcuts.js` |
| R229    | `tests/test_submit_btn_disabled_visible_invariant_r229.py`             | Pattern A + Pattern C  | CSS `:disabled` rule exists for both themes + JS no longer writes inline color for the submit button |
| R230    | `tests/test_decorative_svgs_aria_hidden_invariant_r230.py`             | Pattern A              | Every `<svg>` in `web_ui.html` has `aria-hidden="true"` + `focusable="false"` (a11y / WCAG 1.1.1) |

## 7. Further reading

- [`docs/lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md)
  — root causes of why silent decay defeats normal review.
- [`docs/code-reviews/`](code-reviews/) — every CR documents the
  follow-up backlog that drove the next batch of invariants.
- [`docs/release-recovery.md`](release-recovery.md) — the 13-step
  release checklist; many invariants exist specifically to make
  one of those steps automated.
