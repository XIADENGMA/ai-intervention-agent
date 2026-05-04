# Release notes draft (post-v1.5.22 / candidate v1.5.23)

> Draft assembled by the assistant after the v1.5.22 tag, summarising
> the 25 maintenance commits added on top of the release. This is **not**
> a published release; the file is committed under `.github/` only as a
> paste-ready artifact for whoever cuts the next minor.
>
> When ready to publish:
>
> 1. Bump the version in `pyproject.toml`, `packages/vscode/package.json`,
>    `package.json` (root), `CITATION.cff`, and `.github/ISSUE_TEMPLATE/bug_report.yml`.
>    Run `uv run python scripts/bump_version.py 1.5.23` if it covers
>    every file; double-check with `--check`.
> 2. Move the `[Unreleased]` block in `CHANGELOG.md` to
>    `[1.5.23] - <date>` and add a fresh empty `[Unreleased]` heading.
> 3. Update `packages/vscode/CHANGELOG.md`: move the `[Unreleased]`
>    block down to a new `[1.5.23] - <date>` section and add a fresh
>    `[Unreleased]` heading. Keep only the **extension-relevant** rows
>    (no need to mirror the entire root CHANGELOG; see
>    `packages/vscode/CHANGELOG.md` header for the curation rule).
> 4. Tag `v1.5.23`, push, then paste **the body below** (everything
>    under the "What changed" heading) into GitHub Releases.
> 5. Delete this draft file (or replace with the next draft).

---

## What changed in v1.5.23

This is a **documentation + tooling polish** maintenance release. The
shipped runtime is functionally unchanged from v1.5.22; every commit
either fills a long-overdue documentation gap, hardens the maintenance
contract (CI Gate / pre-commit / coverage red line), or aligns metadata
with the actual project ownership. Operators can drop in the new
wheel / extension without config migration; downstream packagers do
not need to update integration scripts.

### Highlights at a glance

- **Audience-first navigation** for the 30+ documents under `docs/`
  and the 20 automation scripts under `scripts/` — fresh
  contributors no longer have to grep titles to find their entry
  point.
- **Two new docs surfaces** that were structurally invisible
  before: `packages/vscode/CHANGELOG.md` (rendered on the VS Code
  Marketplace / Open VSX listing's "Changelog" tab, previously
  empty for every release) and `docs/troubleshooting{,.zh-CN}.md`
  (a bilingual FAQ for the eight most common deployment / runtime
  issues).
- **API reference refreshed** for the v1.5.x signature delta.
  `docs/api/server_config.md` (and Chinese mirror) finally exist
  after being implicitly broken since the v1.5.20 server-side
  refactor; nine other module pages picked up ~250 lines of net
  additions reflecting real signature changes.
- **CI Gate is now WARNING-clean across consecutive runs** —
  previously, a Loguru sink wired to `sys.__stderr__` would
  occasionally leak a `notification_manager` retry warning to
  the terminal (depending on `LogDeduplicator` cache state), making
  freshly-run pre-commit / CI output look noisy without any real
  test failure.
- **Coverage red line at 88 %** (current measurement 90.96 %), so
  future drift surfaces in pull requests instead of in production
  monitoring.
- **`LICENSE` aligned with project metadata** — `xiadengma` is now
  listed as the v1.5 series primary author alongside the upstream
  fork lineage (Pau Oliva 2025, Fábio Ferreira 2024). `pyproject.toml::authors`
  and `CITATION.cff::authors` had said this for releases; the
  licence header was the last lagging surface.
- **Top-level `Makefile` ships 11 thin-wrapper shortcuts** —
  `make ci`, `make test`, `make lint`, `make coverage`,
  `make docs`, `make docs-check`, `make vscode-check`,
  `make pre-commit`, `make clean`, `make install`, `make help`
  (default goal). Every target delegates to an existing
  `scripts/ci_gate.py`-or-friends invocation, so CI workflows
  and the local Makefile cannot drift.
- **Bilingual API reference is now structurally symmetric.**
  Three latent oversights were closed in one swoop: the
  English `index.md` gained the missing "Quick navigation"
  Core/Utility grouping (the Chinese version always had it);
  every Chinese `*.md` page now carries a back-link to its
  English signature-only sibling (the inverse direction
  already existed); and the Chinese index now opens with the
  parity subtitle "中文 API 参考（含完整 docstring 叙述）。"
  matching the existing English subtitle.
- **API reference covers three additional contract modules** —
  `protocol.py` (PROTOCOL_VERSION + Capabilities + ServerClock),
  `state_machine.py` (Connection / Content / Interaction state
  machines), and `i18n.py` (back-end locale-keyed message
  lookup). Total per-locale page count climbs from 11 to 14.

### Documentation

- **`docs/README.md` + `docs/README.zh-CN.md` (new, bilingual)** —
  audience-first directory index for the 30+ markdown files. Splits
  navigation into four roles: end users, contributors, operators,
  reviewers. Replaces the previous "grep + guess" experience.
- **`scripts/README.md` (new)** — one-liner index for all 20
  automation entry points (CI Gate orchestrator, eight i18n static
  gates, three generators, asset/packaging pipeline, three test
  harnesses, coverage wrapper).
- **`docs/troubleshooting.md` + `docs/troubleshooting.zh-CN.md` (new,
  bilingual)** — focused FAQ covering the eight most common deployment
  / runtime issues (port-in-use, blank VS Code panel, empty task
  list / SSE replay, notification channels silence triage, mDNS
  `ai.local` resolution, Open in IDE no-op, PWA install hiccups,
  TOML migration). Each entry follows symptom → cause → fix.
  `SUPPORT.md` updated with cross-links.
- **`packages/vscode/CHANGELOG.md` (new)** — the VS Code Marketplace
  and Open VSX render the extension package's own `CHANGELOG.md` on
  the listing's "Changelog" tab. This project shipped six releases
  with an empty Changelog tab; the new file is a curated per-release
  excerpt of the extension-relevant changes from v1.5.20 onwards,
  with a link back to the root `CHANGELOG.md`. Wired into the VSIX in
  two places (`package.json::files` and
  `scripts/package_vscode_vsix.mjs::includeList`) with explicit
  inline comments documenting the dual-declaration invariant.
- **`packages/vscode/README.md` + `.zh-CN.md`** gain two new
  sections:
  - `i18n.pseudoLocale` _(experimental)_ setting — declared in
    `package.json` for several minor releases but had zero
    end-user documentation, so QA folk wanting to spot
    hardcoded strings or layout overflow could not discover it.
  - **AppleScript executor (macOS only) · security model** — full
    enumeration of the seven safeguards baked into
    `applescript-executor.ts` (platform check, absolute
    `/usr/bin/osascript` path, stdin script delivery, 8 s hard
    timeout, 1 MiB output cap, log redaction, no user-supplied
    scripts). `SECURITY.md` already mentioned the executor in the
    "Out of scope" section; this expansion lets reviewers verify
    the assertion at source.
- **Removed phantom `ai-intervention-agent.enableAppleScript`
  reference from both root READMEs** — the setting key has not been
  declared in `packages/vscode/package.json::contributes.configuration`
  for several minor releases (the AppleScript path is gated only by
  the macOS native notification toggle inside the panel UI). Replaced
  with a one-line pointer to the VS Code extension README.
- **API reference (`docs/api/` + `docs/api.zh-CN/`) refreshed to match
  current source.** Adds `server_config.md` (missing since the v1.5.20
  refactor) and brings nine other module pages up to date with the
  v1.5.x signature delta. `scripts/generate_docs.py` also gained a
  `--check` mode (idempotent byte-level compare against on-disk files)
  and three latent generator-style bugs were fixed (trailing newline,
  italic emphasis style, blank lines around H3 + thematic-break) so
  future regenerations do not re-introduce noise.
- **OpenSSF Scorecard workflow status badge** added to both root
  READMEs, advertising the `scorecard.yml` GitHub Actions workflow's
  pass/fail state. Once the public OpenSSF API begins ingesting the
  repo, this can be swapped to the canonical
  `shields.io/ossf-scorecard/...` endpoint for the actual numeric
  score.
- **Markdown canonicalisation in `CHANGELOG.md` and
  `docs/security/AUDIT_2026-05-04.md`** — table column alignment
  normalised to GitHub-style left-anchored, italic emphasis switched
  from `*…*` to `_…_` so future style sweeps can use a single regex.
- **Bilingual `README` Acknowledgements section** formalises the
  upstream lineage. Pairs with the `LICENSE` backfill above:
  links to [`noopstudios/interactive-feedback-mcp`](https://github.com/noopstudios/interactive-feedback-mcp)
  (Fábio Ferreira, 2024) and
  [`poliva/interactive-feedback-mcp`](https://github.com/poliva/interactive-feedback-mcp)
  (Pau Oliva, 2025), and explicitly scopes the v1.5.x rewrite
  (Web UI, VS Code extension, i18n, notification stack, CI/CD)
  to `xiadengma`.
- **`README` Documentation index now cross-links
  `packages/vscode/CHANGELOG.md`** so visitors don't have to
  grep the tree to find the Marketplace-specific changelog.
- **`packages/vscode/README{.zh-CN}.md` gain a Changelog
  section** with two bullets — extension-only changelog
  (relative link, resolves through the Marketplace's URL
  rewriter) and the repository-wide changelog (absolute URL
  for safety on Marketplace renderers).
- **`make` shortcuts surfaced in `CONTRIBUTING.md::§2 Local
  CI Gate` and `docs/workflow{.zh-CN}.md`** so contributors
  reading the entry-point pages discover the alias instead of
  only seeing the long-form `uv run python scripts/ci_gate.py …`.

### Tooling / CI

- **`scripts/ci_gate.py` is now WARNING-clean.** A new session-scoped
  `autouse` fixture in `tests/conftest.py`
  (`_silence_loguru_sinks_during_tests`) drops the Loguru stderr
  sink at pytest startup. `assertLogs` continues to capture WARNING
  records as before; only the duplicate stderr drain is removed.
  Verified by two back-to-back `uv run python scripts/ci_gate.py`
  runs producing zero WARNING / ERROR / FAIL / RETRY lines.
- **`scripts/generate_docs.py --check`** introduced as a
  drift-detection mode. The same script can now emit an
  authoritative diff list + remediation command when the
  `docs/api(.zh-CN)/*` files don't match current Python source.
  Idempotent: two consecutive invocations produce zero `git diff`.
- **`scripts/ci_gate.py` runs `generate_docs.py --check` for both
  locales (warn-level, non-blocking)** via a new `_run_warn`
  helper. Translated drift produces a `[ci_gate] WARN: …` line
  on stderr but does not fail the gate, giving contributors a
  human-readable nudge before the contract becomes fail-closed
  (the upgrade is a one-line change documented in source).
- **Coverage red line (`fail_under = 88`) and report polish in
  `pyproject.toml`** — `[tool.coverage.run]` excludes test files
  and one-shot scripts so they cannot inflate themselves to 100 %;
  `[tool.coverage.report] fail_under = 88` defends the 90.96 %
  measurement with ~3 % volatility headroom; `skip_covered = true`
  cleans the term-missing report; `exclude_lines` recognises
  `pragma: no cover`, `raise NotImplementedError`,
  `if TYPE_CHECKING:`, and `if __name__ == "__main__":` so the
  metric stays honest without manual annotation.
- **`.pre-commit-config.yaml` gains three commonly-recommended
  hooks** (no new dependency — already pinned at `v5.0.0`):
  - `check-toml` — covers `pyproject.toml`, `config.toml.default`,
    `tests/fixtures/*.toml`. Sister hooks `check-yaml` /
    `check-json` were already on; the TOML omission left a
    malformed-bracket gap in `pyproject.toml` until `uv sync` /
    `uv build` would surface it.
  - `mixed-line-ending --fix=lf` — closes the loop with
    `.gitattributes`'s `* text=auto eol=lf`. Windows checkouts
    can produce CRLF on newly authored files until the first
    re-normalisation; the hook fixes it pre-push instead of
    waiting for CI.
  - `debug-statements` — guards against `breakpoint()` /
    `pdb.set_trace()` slipping into commits. Particularly nasty
    in the MCP server path because `pdb` blocks on `sys.stdin`
    (the MCP transport channel). `ruff`'s `T20` does not catch
    this.
- **Top-level `Makefile` (new)** — 11 thin-wrapper targets
  expose `make {ci,test,lint,coverage,docs,docs-check,
  vscode-check,pre-commit,clean,install,help}`. Pure
  delegation; CI surface unchanged (`.github/workflows/test.yml`
  still calls `scripts/ci_gate.py` directly). `.DEFAULT_GOAL :=
  help` makes `make` (no args) print the table.

### Packaging / metadata

- **PyPI metadata enrichment in `pyproject.toml`** — added four
  classifiers that were missing despite the underlying capability
  shipping for several minor releases:
  - `Environment :: Web Environment`
  - `Framework :: Flask`
  - `Natural Language :: English`
  - `Natural Language :: Chinese (Simplified)`
  - and a `Discussions` entry under `[project.urls]` mirroring
    the route already advertised in `.github/ISSUE_TEMPLATE/config.yml`.
- **`Development Status` graduated to `5 - Production/Stable`**
  in `pyproject.toml`, reflecting v1.5.x's shipped track record
  (2244 passing tests, 90.96 % line coverage, zero production
  CVEs) — the previous `4 - Beta` was an unnecessary speedbump
  for adopters scanning the project page.
- **`LICENSE` now lists `xiadengma` alongside the upstream
  copyright holders** (Pau Oliva, Fábio Ferreira). `pyproject.toml::authors`
  and `CITATION.cff::authors` had declared `xiadengma` as project
  author for the entire v1.5 series; the licence file was the last
  lagging metadata surface. Pure copyright-holder list change; the
  MIT permission terms are unchanged.

### How to verify before tagging

```sh
# Run the full local CI Gate (≈ 50 s):
uv run python scripts/ci_gate.py

# Optionally include the VS Code extension test suite + VSIX build
# (slower; needed before pushing the Marketplace artefact):
uv run python scripts/ci_gate.py --with-vscode

# Confirm the API references are in sync (now part of ci_gate as a
# warn-level check; this is the explicit explicit form):
uv run python scripts/generate_docs.py --lang en --check
uv run python scripts/generate_docs.py --lang zh-CN --check

# Coverage red line check (CI runner uses --with-coverage; locally
# you can opt in):
uv run python scripts/ci_gate.py --with-coverage
```

### Compat note

Runtime API surface is identical to v1.5.22:
`interactive_feedback`'s tool schema, all Web UI routes, the VS Code
extension's command IDs, and the `config.toml` shape are unchanged.
Bumping is safe; you can roll back to v1.5.22 by re-installing the
old wheel / extension if your environment requires bisection
testing. No data migration is required.
