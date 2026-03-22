## WorkFlow

This document describes the recommended development and release workflow for this project. Since `TODO.md` may be gitignored as a personal/local file, the reusable workflow is maintained under `docs/`.

### Web UI / real-machine verification

- `uv run python test.py --port 8080 --verbose --thread-timeout 0`
- Open: `http://0.0.0.0:8080` (LAN: `http://ai.local:8080`)
- VSCode extension (optional): set `ai-intervention-agent.serverUrl` to your server URL (e.g. `http://ai.local:8080`)

### Pre-commit (Local CI Gate)

- `uv sync --all-groups`
- `uv run ruff format .`
- `uv run ruff check .`
- `uv run ty check .`
- `uv run pytest -q`
- `uv run python scripts/minify_assets.py --check` (if it fails: `uv run python scripts/minify_assets.py`)
- VSCode extension: `npm run vscode:check` (Linux/headless: `xvfb-run -a npm run vscode:check`)

### Release (tag triggers GitHub Actions)

- Bump versions: `pyproject.toml` / `uv.lock` / `package.json` / `package-lock.json` / `packages/vscode/package.json`
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
