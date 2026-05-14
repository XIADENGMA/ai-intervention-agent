# Release Recovery Playbook

> Closes CR#13 §F-1. Last revised 2026-05-12 (v1.6.3 cycle).
> Chinese mirror: [`release-recovery.zh-CN.md`](release-recovery.zh-CN.md).

This document is the human-readable runbook for **what to do when a
`v*.*.*` tag push triggers `release.yml` and one or more of the
six release jobs fails or partially ships**.

The six release jobs of `release.yml` (in execution order):

1. **Build (sdist + wheel)** — runs `scripts/ci_gate.py --ci`
   then `uv build` + `twine check` + Node deps + VSIX build. Uploads
   `vsix` and `dist` artefacts.
2. **Publish to PyPI (Trusted Publisher)** — uploads `dist/*` to
   PyPI with sigstore attestations.
3. **Publish VSCode Extension to Open VSX** — `npx --yes
ovsx@0.10.9 publish ...` (pinned per R149).
4. **Publish VSCode Extension to VS Code Marketplace** — `vsce
publish` if `VSCE_PAT` secret is set; gracefully skips otherwise.
5. **Create GitHub Release** — uploads sdist/wheel/vsix as
   release assets + auto-generated release notes from CHANGELOG.

A failure in **any** job leaves the project in a partial state.
This playbook describes how to recover for each failure pattern,
and **the one rule that everything hinges on**:

> Once a Publish job has _succeeded_ (PyPI / Open VSX / Marketplace
> accepted the artefact), the version number is **permanently
> burned**. PyPI explicitly refuses re-upload of the same version,
> even after `yank`. Open VSX is the same. **Never re-use a burned
> version number.** Bump to the next patch instead.

## Failure pattern 1 — Build job fails (no Publish ran)

**Symptom**: GitHub Actions shows `Build (sdist + wheel)` as ✗,
the four Publish jobs all show `-` (skipped because dependency
failed). No artefact uploaded anywhere. No GitHub Release created.

**Example**: v1.6.3 attempt #1 (commit `a5c12b0`) failed at
"Python CI Gate" because of `test_housekeeping_r151` fossilisation
(see R180 commit message).

**Recovery**: clean abort + re-tag is **safe**.

```bash
# 1. Investigate. Pull failed-job logs locally and reproduce.
gh run view <run-id> --log-failed | head -200
uv run python scripts/ci_gate.py  # reproduce locally

# 2. Land the fix on main.
git checkout main
# ... commit the fix(es) ...
git push origin main

# 3. Delete the failed tag, both remote and local.
git push --delete origin v1.6.3
git tag -d v1.6.3

# 4. Re-tag on the new HEAD (which contains the fix).
git tag -a v1.6.3 -m "release v1.6.3 (re-shot after attempt-1 CI failure)"

# 5. Sanity-check push safety. (Add --check-cve for R185 Dependabot
#    CVE gate; requires `gh auth login` + Dependabot enabled on the repo.
#    Or use `make release-check-cve` shortcut.)
uv run python scripts/check_tag_push_safety.py

# 6. Push the new tag — triggers release.yml.
git push origin v1.6.3
```

**Why this is safe**: No external mirror (PyPI / Open VSX / GitHub
Release) accepted anything. The only "leaked" artefact was the
tag itself, which we deleted. Re-tagging the same name is a tag
_move_, not a tag _rewrite_ from the consumer's perspective
(nothing consumed it yet).

**Watchpoint**: if any developer / CI / mirror polled the tag
between push and delete, they may cache the abandoned commit
hash. Communicate the abort in the project's Discussion / Issue
tracker if you suspect external consumers.

## Failure pattern 2 — Build ✓, some Publish jobs ✗

**Symptom**: `Build` succeeds; PyPI ships ✓; Open VSX or
Marketplace ✗. GitHub Release may or may not exist depending on
which job ran first.

**Example (hypothetical)**: PyPI ✓ + Open VSX ✗ because Open VSX
servers had a transient 502.

**Recovery**: **do not re-tag the same version.** PyPI has the
version; you cannot re-upload `v1.6.3` to PyPI. Use one of:

### Option A — Re-run only the failed job (transient failures)

If the failure was transient (network, rate-limit, Open VSX
server outage), re-run the specific job:

```bash
gh run rerun <run-id> --failed
```

This re-attempts the failed jobs **without re-running successful
ones**. PyPI publish won't be re-attempted, so no version-conflict
risk.

### Option B — Manual publish from the existing artefact

If re-run is unavailable (e.g. workflow file changed, run too
old), download the `vsix` artefact and publish manually:

```bash
gh run download <run-id> --name vsix
cd packages/vscode
# OpenVSX:
npx --yes ovsx@0.10.9 publish *.vsix -p $OPENVSX_TOKEN
# Marketplace (if applicable):
vsce publish --packagePath *.vsix -p $VSCE_PAT
```

### Option C — Patch-bump (v1.6.3 → v1.6.4) if the artefact is broken

If the failure was **not transient** (e.g. ovsx validator rejected
the displayName, as in v1.6.1's R149 root cause), the artefact
itself needs a fix. PyPI has v1.6.3 with a working artefact; the
broken artefact is the VSIX. Options:

1. **Acceptable gap**: v1.6.3 ships on PyPI only; the VSIX
   targets v1.6.4. Document this in CHANGELOG: "v1.6.3 ships
   only on PyPI; VSIX users see v1.6.2 → v1.6.4 directly."
2. **Even VSIX users need this fix**: bump to v1.6.4, fix the
   VSIX bug, re-tag. Both `pip install
ai-intervention-agent==1.6.4` and the v1.6.4 VSIX ship. v1.6.3
   becomes a "PyPI-only release" historical artefact.

This is a value-judgement call. Prefer option 1 if the VSIX bug
is minor / cosmetic; prefer option 2 if it's user-facing.

## Failure pattern 3 — Build ✓, all Publish jobs ✓, but `Create GitHub Release` ✗

**Symptom**: PyPI ✓ + Open VSX ✓ + Marketplace ✓ + `Create
GitHub Release` ✗ (e.g. `gh release create` rate-limited or
permissions failed).

**Recovery**: easiest of the three patterns. Create the GitHub
Release manually:

```bash
# Download artefacts from the Build job.
gh run download <run-id> --name dist
gh run download <run-id> --name vsix

# Create the GitHub Release pointing at the existing tag.
gh release create v1.6.3 \
  --notes-from-tag \
  ./dist/*.tar.gz ./dist/*.whl ./packages/vscode/*.vsix
```

Optionally re-run only the `Create GitHub Release` job via `gh
run rerun <run-id> --job <job-id>` if the cause was transient.

## What R180 + R181 prevent

| Before R180 + R181                                  | After R180 + R181                                     |
| --------------------------------------------------- | ----------------------------------------------------- |
| Snapshot test on `[Unreleased]` fossilised on bump  | Snapshot test re-anchored on whole CHANGELOG          |
| CHANGELOG / docs commits silently skip `test.yml`   | CHANGELOG / docs commits run full `ci_gate.py` matrix |
| Latent test regressions surface at tag-push time    | Latent test regressions surface at PR-push time       |
| Failure pattern 1 was the _primary_ tag-push danger | Failure pattern 1 is now much rarer                   |

This playbook still applies to failure patterns 2 and 3, and to
failure pattern 1 in the rare case it slips through (e.g.
upstream toolchain change between PR-merge and tag-push).

## Communication template

If a release attempt failed and you re-tagged or bumped past it,
post a brief note to the project's Discussion / Issue tracker:

> **v1.6.3 release-attempt note**: the first `v1.6.3` tag
> push ([commit `a5c12b0`]) failed CI at Python CI Gate. No
> packages were published. The tag was deleted and re-shot on
> commit `72b0ae1` (which adds the fix). External consumers
> never saw the failed attempt. The published v1.6.3 (PyPI,
> Open VSX, GitHub Release) is the working bundle.

This costs ~2 minutes and prevents months of "why did v1.6.3 tag
move?" detective work in future bisect sessions.

## Related guards

- `tests/test_housekeeping_r151.py` — R180 rescue test.
- `tests/test_workflow_paths_ignore_r181.py` — R181 paths-ignore
  guard.
- `tests/test_release_workflow_ovsx_pinned_r149.py` — R149 ovsx
  pin guard (related: prevents floating-tag toolchain drift).
- `scripts/check_tag_push_safety.py` — pre-push safety check
  (warns if you're pushing more than 3 unpushed tags at once).
  **R185 extension**: `--check-cve` flag blocks the release if
  ≥ 1 open Dependabot alert at `critical`/`high` exists; opt-in,
  default OFF. `make release-check-cve` is the convenience target.
- `scripts/bump_version.py` — programmatic version sync across
  `pyproject.toml`, `package.json`, `uv.lock`, `package-lock.json`,
  `packages/vscode/package.json`, `CITATION.cff`,
  `.github/ISSUE_TEMPLATE/bug_report.yml`. **R183**: now also warns
  if `CHANGELOG.md [Unreleased]` looks empty at bump time
  (`--warn-empty-unreleased` default-on; `--no-warn-empty-unreleased`
  suppresses).
- `docs/troubleshooting.md` §12 (R151) — Open VSX displayName +
  ovsx pin upgrade ritual.
- `.github/dependabot.yml` + `automated-security-fixes`
  (repo-level toggle, **R184**: enabled) — auto-PR for CVE
  disclosures. Combined with `dependabot-auto-merge.yml`, the
  flow is: CVE drops → Dependabot opens patch-bump PR →
  patch/minor auto-merge → next release picks up the fix. Major
  bumps still go to human review (per dependabot-auto-merge.yml).

## Pre-tag-push checklist (R206 / Cycle 9 · F-release-1)

> **Why this section exists**: in addition to the six `release.yml`
> failure patterns above (which fire **after** `git push v*.*.*`), the
> `Tests` workflow on `main` also runs on tag-push and can leave the
> tag pointing at a **CI-red commit** without any Publish job running.
> v1.7.2 hit exactly this: the initial tag commit (`36222a3`) missed a
> `docs/api/enhanced_logging.md` regen, the docs-parity gate inside
> `Tests` flagged it, and the v1.7.2 tag had to be force-retagged 5
> minutes later to a docs-sync commit (`35f9671`).

The list below is **what to run locally** before pushing any
`v*.*.*` tag. Together with the existing `scripts/check_tag_push_
safety.py` (cf. §"Related guards") and the `Tests` workflow's
CHANGELOG-non-Unreleased pre-commit guard (R180 + R181), these are
the **three concentric belts** that catch tag-push-time mistakes.

> **R209 (cycle 10 · F-release-2) automation**: step 6 below
> (`check_tag_push_safety.py`) is now also wired into a Git
> `pre-push` hook via pre-commit. Install once with
> `make install-hooks` (or `pre-commit install --hook-type
> pre-commit --hook-type pre-push`) and the hook will refuse
> the push if ≥ 4 `v*.*.*` tags are unpushed (R19.1 GitHub
> webhook throttle). The hook is **complementary** to the
> manual checklist — it catches the most dangerous single
> failure mode at the latest possible moment, not all 13 steps.
> Escape hatch: `git push --no-verify`.

1. **Local pre-flight** (this checklist) — catches mistakes _before_
   `git push --follow-tags`.
2. **`Tests` workflow on `main`** (R180 + R181 + CHANGELOG drift
   guard) — catches mistakes _after_ tag-push but _before_
   `release.yml` Publish jobs fire.
3. **`release.yml` six-job pipeline** (failure patterns 1-3 above)
   — catches per-job artefact / publish failures.

```bash
# === Pre-tag-push checklist (cycle 9 / F-release-1) =====================

# 1. Sync with remote main, ensure linear history.
git fetch --all --tags --prune
git checkout main
git pull --ff-only origin main
git status --short                          # must be empty

# 2. Static checks (ruff + ty) — the hard gates.
uv run ruff check .
uv run ruff format --check .
uv run ty check .                           # All checks passed!

# 3. API docs parity — both languages. v1.7.2 missed this and CI failed.
uv run python scripts/generate_docs.py --lang en --check
uv run python scripts/generate_docs.py --lang zh-CN --check

# 4. Full pytest. Counts: any drop vs. last release is suspicious.
uv run pytest -q                            # 5xxx passed expected

# 5. Lockfile consistency.
uv lock --check                             # Resolved N packages in Xs
npm install --prefer-offline --no-audit > /dev/null  # if package.json touched

# 6. Release safety check (existing, R185).
uv run python scripts/check_tag_push_safety.py
# (R185 strict mode if you want CVE gate)
make release-check-cve

# 7. CHANGELOG sanity: [Unreleased] must NOT be empty (or you're
#    shipping a no-op release).
rg -n -A1 '^## \[Unreleased\]' CHANGELOG.md | head -5

# 8. Bump version + sync ALL version-bearing files (R183).
uv run python scripts/bump_version.py X.Y.Z

# 9. Final pre-commit gate (lets pre-commit hooks normalise EOL / trim
#    whitespace before the bump-commit lands).
git add -A
pre-commit run --all-files
git commit -m ":bookmark: chore(release): vX.Y.Z"
# (Or amend the previous bump-commit if hooks modified files — only if
# the commit hasn't been pushed yet.)

# 10. Tag with annotation. **Do NOT use lightweight tags** (`git tag X`
#     without `-a`) — release.yml expects annotated tags and skips body
#     auto-summarisation on lightweight ones.
git tag -a vX.Y.Z -m "vX.Y.Z: <one-line summary>

<2-4 bullet detail per CR review>"

# 11. ONE final dry-run before push — catch the misspelled tag name now.
git log --oneline -1 vX.Y.Z
git show vX.Y.Z --stat | head -30

# 12. Push branch + tag in one shot.
git push --follow-tags origin main

# 13. Watch CI live. Don't walk away until Tests + release.yml all green.
gh run watch  # or: gh run list --branch main --limit 5
```

### Retag safety window (Lessons from v1.7.2)

If the `Tests` workflow fails on the tag commit **and** the
`release.yml` Publish jobs have **not yet** started (or have skipped
because `Tests` is a required dep), force-retagging to a fix-up commit
is **safe** within a short window. v1.7.2 retagged from `36222a3`
→ `35f9671` 5 minutes after the initial push.

**Safe-to-retag conditions** (all must be true):

- No PyPI / Open VSX / Marketplace publish has succeeded (check
  `release.yml` run-page or PyPI page directly);
- No GitHub Release has been created yet (or you can delete it);
- < 30 minutes since the failed tag push (statistical: typical
  external fork/clone latency window — beyond this, assume someone
  has a frozen reference).

**Retag procedure** (mirrors v1.7.2's recovery):

```bash
# A. Land the fix on main first.
git checkout main
# ... fix the docs / test / lockfile / whatever ...
git commit -m ":memo: docs(api): regenerate XXX for return-type widen in vX.Y.Z"
git push origin main

# B. Delete the broken tag on both sides.
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z

# C. Re-tag on the fix commit with an updated annotation explicitly
#    mentioning the retag (CR#21 §3.2: future maintainers must know).
git tag -a vX.Y.Z <fix-commit-sha> -m "vX.Y.Z: <summary>

Note: tag was force-retagged from <broken-sha> to <fix-sha> within
5 minutes of initial push due to <reason>. No external consumers
saw the broken tag. The CHANGELOG [vX.Y.Z] entry documents this
recovery."

# D. Re-push.
git push origin vX.Y.Z

# E. Sanity-check release.yml fires on the new tag.
gh run watch
```

### Beyond the retag window

If a tag has been out for > 30 minutes, OR if any Publish job has
already succeeded, the version is **burned**. Bump to the next patch
(e.g. v1.7.2 → v1.7.3) and ship the fix there. Document the burned
version in `CHANGELOG.md`:

```markdown
## [1.7.3] — YYYY-MM-DD

### Fixed

- v1.7.2 was tagged with [...broken thing...]; v1.7.3 ships the fix.
  Users on v1.7.2 should upgrade.
```

See also the "Communication template" section above — same
principles apply, scaled up for burned-version disclosure.

### Tag-was-moved history

Historical tag retags this checklist is designed to prevent:

| Tag    | Old SHA   | New SHA   | Why                                                                  |
| ------ | --------- | --------- | -------------------------------------------------------------------- |
| v1.6.3 | `a5c12b0` | `72b0ae1` | R180 R151 fossilisation broke Python CI Gate on tag-commit           |
| v1.7.2 | `36222a3` | `35f9671` | docs/api parity drift missed `enhanced_logging.md` regen (R204 era)  |

Both incidents → CHANGELOG entry + tag annotation explicitly note
the retag, per "Communication template" above. **If your retag count
ever exceeds 3-4 per year, the pre-flight checklist needs a new
gate**: file a follow-up like F-release-2 to identify which step
missed the latest miss.

## Security release shortcut (R184)

When Dependabot reports a CVE on a runtime dependency, the
release process is the standard cycle compressed:

```bash
# 1. Identify (Dependabot UI or `gh api`):
gh api repos/$OWNER/$REPO/dependabot/alerts --jq \
  '.[] | select(.state == "open") | {pkg: .security_vulnerability.package.name, severity: .security_vulnerability.severity, ghsa: .security_advisory.ghsa_id}'

# 2. Bump the dependency:
uv lock --upgrade-package <pkg>
# or if it's a direct dep, edit pyproject.toml first:
# "foo>=X.Y.Z"  # security: GHSA-...

# 3. Verify:
uv sync --dev
uv run pytest -W error -q
uv run python scripts/ci_gate.py

# 4. Land + bump:
git commit -m ":lock: security(deps-rNNN): bump <pkg> ..."
git push origin main
uv run python scripts/bump_version.py X.Y.<Z+1>
```

The "lock" emoji + `security(deps-...)` commit prefix makes the
CVE patch grep-able in `git log`. The `### Security` section in
CHANGELOG (Keep-a-Changelog convention) keeps the disclosure
discoverable for downstream consumers.
