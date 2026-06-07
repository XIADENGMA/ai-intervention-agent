# Release checklist

> Reusable runbook for cutting a new `ai-intervention-agent`
> release. Distilled from the v1.8.0 release (cr40 cycle)
> + v1.7.x history of accidental skip-steps.

This checklist is **mandatory** for every release commit.
Each step has a rationale rooted in a past failure mode —
do not skip steps you don't understand; ask first.

## Pre-release audit

### A.1 CHANGELOG hygiene (failure mode: v1.7.5 release shipped with stale CHANGELOG)

- [ ] Run `uv run python scripts/check_changelog_freshness.py --strict`
      — must exit 0. If it reports drift, fix `CHANGELOG.md`
      first.
- [ ] Manually scan `[Unreleased]` for completeness:
  - All cycle ship commits in the release window have a
    CHANGELOG entry?
  - All bug fixes documented in `### Fixed` subsection?
  - All performance changes in `### Performance` subsection?
- [ ] Promote `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`.
- [ ] Add a fresh empty `[Unreleased]` section above with a
      placeholder bullet (keeps `check_changelog_freshness`
      check #2 passing during the immediate-post-promote
      window before the new tag is created).

### A.2 SemVer rationale (failure mode: minor vs patch bump confusion)

- [ ] Justify the version bump shape:
  - **PATCH** (X.Y.Z+1): bug fixes only, no surface change.
  - **MINOR** (X.Y+1.0): additive surface (new MCP schema
    fields, new HTTP endpoints, new UI features). Backward
    compatible.
  - **MAJOR** (X+1.0.0): breaking surface change. Requires
    explicit migration doc + user-side review.
- [ ] Document the rationale in **both** the release
      commit body and the annotated tag message.

### A.3 Full-suite green gate (failure mode: cr40 sweep — 4 latent regressions invisible to per-module runs)

- [ ] Run **full** `uv run pytest --timeout=60`. **Per-
      module test runs are NOT a substitute** — cr40
      caught 4 regressions invisible to isolated runs:
  - invariant scope drift (`test_feat_remove_download_button`)
  - shared-singleton pollution
    (`test_feat_mining3_header_chip`)
  - watchdog label drift
    (`test_lock_watchdog_full_coverage_r52a`)
  - i18n dynamic-key reservation drift
    (`test_runtime_behavior` + `test_i18n_orphan_keys`)
- [ ] Confirm 0 failures, 0 errors. Skips are acceptable
      only if they predate the release window.

### A.4 Build-artifact freshness (failure mode: R246 / cycle-16 build-artifact matrix)

Pre-commit hooks normally enforce these, but a release
commit touches metadata files outside the static-asset
graph, so manually re-run if pre-commit didn't fire them:

- [ ] `uv run python scripts/minify_assets.py`
- [ ] `uv run python scripts/precompress_static.py`
- [ ] `uv run python scripts/gen_zhtw_from_zhcn.py --all`
- [ ] `uv run python scripts/gen_pseudo_locale.py`
- [ ] `uv run python scripts/generate_docs.py --lang en`
- [ ] `uv run python scripts/generate_docs.py --lang zh-CN`

## Version bump

### B.1 Triplet sync (failure mode: v1.7.5 released with `pyproject.toml` ahead of `package.json`)

Four locations must update **together**:

1. `pyproject.toml` — `[project]` section `version = "X.Y.Z"`
2. `package.json` — `"version": "X.Y.Z"`
3. `packages/vscode/package.json` — `"version": "X.Y.Z"`
4. `package-lock.json` — `"version": "X.Y.Z"` in **2 places**:
   - top-level `"version"`
   - `"packages"."": { "version": "X.Y.Z" }`
   - `"packages"."packages/vscode": { "version": "X.Y.Z" }`

Then:

- [ ] `uv lock` — regenerates `uv.lock` with new version.

**Strongly prefer `scripts/bump_version.py X.Y.Z`** for
atomic bump — the existing script (pre-dates this doc;
shipped in v1.5.x) handles all of the above **plus**
`uv.lock`, `.github/ISSUE_TEMPLATE/bug_report.yml`, and
`CITATION.cff`. Run as:

```sh
uv run python scripts/bump_version.py X.Y.Z --dry-run  # preview
uv run python scripts/bump_version.py X.Y.Z            # apply
uv run python scripts/bump_version.py --check          # verify post-bump
```

The script also warns when `[Unreleased]` in `CHANGELOG.md`
looks empty at bump-time (R183 guard against forgotten
backfill). **Use this script — manual edits were the v1.8.0
release's fallback only because the operator wasn't aware
of its existence. Don't repeat that mistake.**

### B.2 npm install workaround (failure mode: fnm lazy-load `npm install` returns silently)

Some shells (zsh + fnm + lazy-load) cause `npm install` to
exit 1 silently without writing the lockfile. Workaround:

- Patch `package-lock.json` manually (the 3 version fields
  enumerated in B.1 above).
- This is **safe for metadata-only version bumps** because
  lockfile integrity hashes are over package tarballs, not
  root project metadata.
- If dependency changes are involved, do not use the
  manual patch — fix the shell issue first.

## Tag + release

### C.1 Local tag (always, before push)

- [ ] `git tag -a vX.Y.Z -m "Release vX.Y.Z (...)"` — tag
      must be annotated (not lightweight) so `git tag -n`
      shows the release message.
- [ ] Tag message should include:
  - One-line release theme
  - SemVer rationale (per A.2)
  - Cycle range covered (e.g. "cycles 17-21")
  - Push-status note ("local only" or "ready to push")

### C.2 Post-tag verification (failure mode: cr40 mutation-test edge case)

- [ ] Re-run `scripts/check_changelog_freshness.py --strict`
      — should now pass with **0 commits since latest tag**
      (HEAD == tag).
- [ ] Re-run **full** `uv run pytest --timeout=60` — catches
      any test that depends on the tag state. (cr40 caught
      `test_detects_missing_unreleased` mutation-test edge
      case this way.)
- [ ] If post-tag tests fail, fix in a new commit (do NOT
      `git tag -f` to move the tag).

### C.3 Push decision (user-gated)

Default: **do not push**. The release commit + local tag
sit in local repo until user explicitly approves push.
Rationale:

- Push triggers PyPI publish CI (irreversible)
- Push triggers Open VSX + VSCode Marketplace publish CI
  (irreversible)
- A wrong release tag pushed publicly cannot be cleanly
  retracted (deleted-tag forks already exist in the wild)

When user approves push:

- [ ] `git push origin main`
- [ ] `git push origin vX.Y.Z`
- [ ] Monitor CI for ≥30 min after push.
- [ ] Verify package appears on PyPI + Open VSX.

## Rollback

If a published release is broken:

- **Never delete the tag** on the public remote. Cut a
  patch release instead (`X.Y.Z+1` with a `### Fixed` entry
  citing the broken release).
- Yank the bad PyPI version with `twine yank` if it's
  outright dangerous (security / data loss). Otherwise,
  leave it for SemVer history.

## Historical references

- v1.8.0 release (cr40 cycle, 2026-06-05) — first release
  to use this checklist; codified from the v1.7.x failure
  modes listed in each "failure mode" reference.
- v1.7.5 release — release commit shipped with stale
  `pyproject.toml` version + missing CHANGELOG entry; took
  2 follow-up patches to recover. Origin of A.2 + B.1.
- cycle-16 build-artifact matrix (R246) — multiple
  releases shipped with stale minified assets. Origin of
  A.4.

## Future improvements (TODO)

- [x] `scripts/bump_version.py` — atomic version triplet
      bump (cr41 §8 #5 follow-up) — **already exists** since
      v1.5.x; this doc now points at it as the canonical path.
- [ ] Pre-commit hook that blocks commits whose subject
      matches `:bookmark: release(v*):` unless the most
      recent `uv run pytest` log shows 0 failures.
- [ ] GitHub Action that auto-yanks PyPI versions on
      explicit `[YANK]` label.
