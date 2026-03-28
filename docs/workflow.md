## WorkFlow

This document describes the recommended development and release workflow for this project. Since `TODO.md` may be gitignored as a personal/local file, the reusable workflow is maintained under `docs/`.

### Web UI / real-machine verification

- `uv run python scripts/manual_test.py --port 8080 --verbose --thread-timeout 0`
- Open (local): `http://127.0.0.1:8080` (LAN: `http://ai.local:8080` or `http://<LAN-IP>:8080`)
- VSCode extension (optional): set `ai-intervention-agent.serverUrl` to your server URL (e.g. `http://ai.local:8080`)

### Pre-commit (Local CI Gate)

- One-command gate (recommended): `uv run python scripts/ci_gate.py`
  - Default is **local mode**: auto-formats (`ruff format`) and runs ruff/ty/pytest/minify
  - CI mode (check-only; no auto-format, but may generate gitignored build artifacts like `.min`): `uv run python scripts/ci_gate.py --ci --with-coverage`
  - Include VSCode checks: `uv run python scripts/ci_gate.py --with-vscode`
- Individual tool commands (for targeted fixing):
  - Lint: `uv run ruff check .` (auto-fix: `uv run ruff check --fix .`)
  - Format: `uv run ruff format .` (check-only: `uv run ruff format --check .`)
  - Type check: `uv run ty check .`
  - Test: `uv run pytest -q`
  - Minify: `uv run python scripts/minify_assets.py`
  - Locale check: `uv run python scripts/check_locales.py`
  - Version check: `uv run python scripts/bump_version.py --check --from-pyproject`
- VSCode extension: `npm run vscode:check` (Linux/headless: `xvfb-run -a npm run vscode:check`)
  - If you use `fnm` and `node` is unavailable in non-interactive shells: `fnm exec --using v24.14.0 -- npm run vscode:check`
  - Note: `vscode:check` includes packaging and will generate a `.vsix` under `packages/vscode/` (gitignored)
    - If you run it via `uv run python scripts/ci_gate.py --with-vscode`: the script will automatically clean `.vsix` before/after running (avoid CI/workspace pollution)
    - If you run `npm run vscode:check` manually: please clean it after finishing tests: `rm -f packages/vscode/*.vsix`

### Release (tag triggers GitHub Actions)

- One-command version sync (without the `v` prefix): `uv run python scripts/bump_version.py X.Y.Z`
  - Updates: `pyproject.toml` / `uv.lock` / `package.json` / `package-lock.json` / `packages/vscode/package.json` / `.github/ISSUE_TEMPLATE/bug_report.md`
  - Optional: `--ci-gate --with-vscode` (runs a local CI Gate after syncing)
- `git commit -m "<type>: <message>"`
- `git tag -a vX.Y.Z -m "vX.Y.Z"`
- `git push --follow-tags origin main`
- If the release pipeline fails: **fix it, bump the patch version, and create a new tag** (e.g. `v1.4.17` → `v1.4.18`). Do not move/retag an already published tag.

### Post-release (online acceptance)

- GitHub Actions: ensure `Tests` / `VSCode Extension (Lint/Test)` / `Release` are all Success
  - [GitHub Actions](https://github.com/XIADENGMA/ai-intervention-agent/actions)
  - Suggested commands:
    - `gh run list --limit 20`
    - `gh run watch <run-id> --exit-status`
- PyPI: ensure `ai-intervention-agent` latest version is `X.Y.Z`
  - [PyPI project](https://pypi.org/project/ai-intervention-agent/)
  - Optional: `python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/ai-intervention-agent/json'))['info']['version'])"`
- Open VSX: ensure `xiadengma.ai-intervention-agent` latest version is `X.Y.Z`
  - [Open VSX extension](https://open-vsx.org/extension/xiadengma/ai-intervention-agent)
  - Optional: `python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://open-vsx.org/api/xiadengma/ai-intervention-agent')).get('version',''))"`
- GitHub Releases: ensure the tag has release assets (`.whl` / `.tar.gz` / `.vsix`)
  - [GitHub Releases](https://github.com/XIADENGMA/ai-intervention-agent/releases)
  - Optional: `gh release view vX.Y.Z`
