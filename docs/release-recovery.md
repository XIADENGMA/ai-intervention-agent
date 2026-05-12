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

> Once a Publish job has *succeeded* (PyPI / Open VSX / Marketplace
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
*move*, not a tag *rewrite* from the consumer's perspective
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

| Before R180 + R181                                  | After R180 + R181                                    |
| --------------------------------------------------- | ---------------------------------------------------- |
| Snapshot test on `[Unreleased]` fossilised on bump  | Snapshot test re-anchored on whole CHANGELOG         |
| CHANGELOG / docs commits silently skip `test.yml`   | CHANGELOG / docs commits run full `ci_gate.py` matrix |
| Latent test regressions surface at tag-push time    | Latent test regressions surface at PR-push time      |
| Failure pattern 1 was the *primary* tag-push danger | Failure pattern 1 is now much rarer                  |

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
