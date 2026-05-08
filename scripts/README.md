# `scripts/` — automation entry points

One-liner index for every script in this directory. Most are wired
into [`ci_gate.py`](ci_gate.py) and `.github/workflows/*.yml`; this
README is here so a fresh contributor can grep one file and see
**what** each script does, **when** it runs, and **what** it gates.

> 中文用户：脚本说明的语言是英文以保持与 docstring 一致；用法示例
> 直接读各脚本的 `--help` 或 docstring 即可。

## Makefile shortcuts

For local use the repo root [`Makefile`](../Makefile) wraps the most
common entry points:

| Target              | Equivalent                                                      |
| ------------------- | --------------------------------------------------------------- |
| `make ci`           | `uv run python scripts/ci_gate.py`                              |
| `make coverage`     | `uv run python scripts/ci_gate.py --with-coverage`              |
| `make vscode-check` | `uv run python scripts/ci_gate.py --with-vscode`                |
| `make docs`         | `generate_docs.py --lang en` + `--lang zh-CN`                   |
| `make docs-check`   | `generate_docs.py --check` for both locales                     |
| `make lint`         | `ruff format` + `ruff check` + `ty check`                       |
| `make test`         | `pytest -q` (no i18n / minify gates — fast loop only)           |
| `make pre-commit`   | `pre-commit run --all-files`                                    |
| `make clean`        | wipe `dist/` / `.coverage*` / `*.vsix` / `.ruff_cache` / et al. |
| `make help`         | print the full table (also the default `make` target)           |

The `Makefile` is a thin wrapper; CI still calls
[`ci_gate.py`](ci_gate.py) directly so the source of truth never
diverges.

## CI Gate orchestrator

- [`ci_gate.py`](ci_gate.py) — single-entry façade:
  `uv sync` → `ruff format/check` → `ty` → 8× i18n parity gates →
  `minify_assets.py` → `precompress_static.py` → `pytest`
  (optionally `--with-coverage`) → red-team i18n smoke → optional
  `--with-vscode` (npm `vscode:check`). Consumed by both local
  pre-commit loops and `.github/workflows/test.yml`.

## i18n static gates (consumed by `ci_gate.py`)

- [`check_i18n_locale_parity.py`](check_i18n_locale_parity.py) —
  locale JSON keys + types + ICU placeholders must match across
  `en` / `zh-CN` / `_pseudo`.
- [`check_i18n_locale_shape.py`](check_i18n_locale_shape.py) —
  every locale must be a tree of objects with string leaves
  (Batch-3 H13 contract).
- [`check_i18n_html_coverage.py`](check_i18n_html_coverage.py) —
  zero hardcoded CJK in HTML templates.
- [`check_i18n_js_no_cjk.py`](check_i18n_js_no_cjk.py) — zero
  hardcoded CJK in `static/js/*.js` and `packages/vscode/*.js`
  (with `--scope all`).
- [`check_i18n_ts_no_cjk.py`](check_i18n_ts_no_cjk.py) — zero
  hardcoded CJK in `packages/vscode/*.ts` (extension host
  post-G6).
- [`check_i18n_param_signatures.py`](check_i18n_param_signatures.py)
  — `t('key', { params })` call sites must match the placeholder
  set declared in the locale value.
- [`check_i18n_orphan_keys.py`](check_i18n_orphan_keys.py)
  _(warn-level)_ — locale keys with no matching call site.
- [`check_i18n_duplicate_values.py`](check_i18n_duplicate_values.py)
  _(warn-level)_ — same string value reused under multiple keys.
- [`check_locales.py`](check_locales.py) — minimal smoke (`en` +
  `zh-CN` parity), kept for legacy invocations.

## Visual / brand guardrails

- [`check_brand_color_consistency.py`](check_brand_color_consistency.py)
  _(R66)_ — fail if `static/css/main.css` re-introduces the
  iOS-system-blue `rgba(0, 122, 255, …)` family the project's
  brand palette (dark-mode `#a855f7`, light-mode Anthropic
  Orange `#d97757`) was meant to replace. Wired into
  `pre-commit` so a single hardcoded blue cannot land on `main`
  again.

## Generators

- [`gen_pseudo_locale.py`](gen_pseudo_locale.py) — synthesise
  `_pseudo.json` from `en.json` via accent substitution + 35 %
  expansion. `--check` enforces "pseudo is in sync" in CI.
- [`gen_i18n_types.py`](gen_i18n_types.py) — emit
  `packages/vscode/i18n-keys.d.ts` from `en.json` so TypeScript
  `hostT(key: I18nKey)` catches typos at build time.
- [`generate_docs.py`](generate_docs.py) — auto-generate
  `docs/api/*.md` (and `docs/api.zh-CN/*.md` with `--lang zh-CN`)
  from Python source docstrings + signatures. `--check` mode
  detects drift without writing (exit 1 + drift list when
  out-of-sync); ideal as a pre-merge sanity check after
  signature edits.
- [`generate_pwa_icons.py`](generate_pwa_icons.py) — build the
  PWA / favicon / `apple-touch-icon` family from a single SVG
  source so the multi-size `favicon.ico` (16/32/48/256), the
  iOS opaque-background tile, and the maskable PWA icon stay in
  sync. Run after editing `src/ai_intervention_agent/icons/icon.svg`.

## Asset / packaging pipeline

- [`minify_assets.py`](minify_assets.py) — minify
  `static/js/*.js` and `static/css/*.css` via `rjsmin` + `rcssmin`.
  `--check` validates `.min` is in sync.
- [`precompress_static.py`](precompress_static.py)
  _(R20.14-D / R21.4)_ — pre-compress `static/**/*.{js,css,json}`
  to `.gz` + `.br` siblings so the Flask static handler can
  ship Brotli / gzip for `tex-mml-chtml.js` (1.1 MB),
  `lottie.min.js` (300 KB), and the locale bundles without
  burning CPU on every request.
- [`package_vscode_vsix.mjs`](package_vscode_vsix.mjs) — build the
  VSCode `.vsix` package via `vsce`.
- [`bump_version.py`](bump_version.py) — bump version across
  `pyproject.toml`, `package.json`, README badges, etc. `--check`
  validates cross-file consistency.
- [`check_tag_push_safety.py`](check_tag_push_safety.py)
  _(R19.1)_ — fail `make release-check` if more than three
  unpushed `v*.*.*` tags exist locally. Works around an
  undocumented GitHub rule that drops `push.tags` webhook events
  when 4+ tags are pushed in one go, which would silently skip
  the `release.yml` workflow.

## Performance

- [`perf_e2e_bench.py`](perf_e2e_bench.py) _(R20.14-A)_ — single
  source of truth for "how fast is `interactive_feedback` →
  Web-UI today?" Captures the four-stage E2E latency the R20.4
  → R20.13 sprints drove from 1980 ms to 360 ms.
- [`perf_gate.py`](perf_gate.py) _(R20.14-A)_ — regression gate
  that compares a fresh `perf_e2e_bench.py` snapshot against the
  committed baseline and fails CI if regressions exceed the
  configured budget. Bench-and-gate are kept strictly separate;
  the bench never bakes in thresholds.

## Tests / QA

- [`manual_test.py`](manual_test.py) — interactive end-to-end
  smoke for the Web UI (config, health, multi-task, Markdown,
  theming). Used for pre-release real-machine verification.
- [`test_mcp_client.py`](test_mcp_client.py) — MCP client
  regression for resubmit timer + image-return wire format.
- [`smoke_test_r50.py`](smoke_test_r50.py) _(R50)_ — out-of-mock
  smoke that boots a real server and asserts (1)
  `/api/system/sse-stats` returns valid JSON,
  (2) `_emit_config_changed_to_sse_bus` actually makes
  `/api/events` emit `event: config_changed`, and (3) 5 emits
  inside 250 ms collapse into 1 frame (R50-B debounce).
- [`red_team_i18n_runtime.mjs`](red_team_i18n_runtime.mjs) —
  cross-feature red-team for both `i18n.js` copies (Web +
  VSCode) under a frozen `Date.now()`. Enforces ICU / apostrophe
  / nested `#` / LRU / miss-key / prototype-pollution /
  byte-parity edges.

## Coverage

- [`run_coverage.sh`](run_coverage.sh) — wrapper that runs pytest
  with `--cov`, optionally emits HTML / XML reports and `open`s
  the HTML one (`--html`, `--xml`, `--open`).

---

_Refresh this file when you add or rename a script so the index
never lies. Last refreshed for v1.6.0 (added 7 scripts that
shipped between v1.5.22 and v1.6.0:
`check_brand_color_consistency.py`, `check_tag_push_safety.py`,
`generate_pwa_icons.py`, `perf_e2e_bench.py`, `perf_gate.py`,
`precompress_static.py`, `smoke_test_r50.py`)._
