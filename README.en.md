<h1 align="center">
  <a href="">
    <img src="icons/icon.svg" width="150" height="150" alt="banner" /><br>
  </a>
</h1>

<p align="center">
  <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/test.yml">
    <img src="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/test.yml/badge.svg" alt="Tests">
  </a>
  <a href="https://pypi.org/project/ai-intervention-agent/">
    <img src="https://img.shields.io/pypi/v/ai-intervention-agent.svg" alt="PyPI">
  </a>
  <a href="https://pypi.org/project/ai-intervention-agent/">
    <img src="https://img.shields.io/pypi/pyversions/ai-intervention-agent.svg" alt="Python Versions">
  </a>
  <a href="https://github.com/xiadengma/ai-intervention-agent/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/xiadengma/ai-intervention-agent.svg" alt="License">
  </a>
  <a href="https://pypi.org/project/ai-intervention-agent/">
    <img src="https://img.shields.io/pypi/dm/ai-intervention-agent.svg" alt="Downloads">
  </a>
  <a href="https://github.com/xiadengma/ai-intervention-agent">
    <img src="https://img.shields.io/github/stars/xiadengma/ai-intervention-agent.svg?style=social" alt="GitHub Stars">
  </a>
</p>

<p align="center">
  English | <a href="./README.md">简体中文</a>
</p>

# AI Intervention Agent

An MCP tool that enables **real-time user intervention** during AI-assisted workflows.

Works with `Cursor`, `VS Code`, `Claude Code`, `Augment`, `Windsurf`, `Trae`, and more.

## UI

> Screenshots include the **first page (content page)** from `uv run python test.py --port 8080 --verbose --thread-timeout 0`, and the **no-content page** from `web_ui.py`.

### Dark theme

#### Desktop

<p align="center">
  <img src=".github/assets/desktop_dark_content.png" alt="Desktop - dark - content" width="420">
  <img src=".github/assets/desktop_dark_no_content.png" alt="Desktop - dark - no content" width="420">
</p>

#### Mobile

<p align="center">
  <img src=".github/assets/mobile_dark_content.png" alt="Mobile - dark - content" width="220">
  <img src=".github/assets/mobile_dark_no_content.png" alt="Mobile - dark - no content" width="220">
</p>

### Light theme

#### Desktop

<p align="center">
  <img src=".github/assets/desktop_light_content.png" alt="Desktop - light - content" width="420">
  <img src=".github/assets/desktop_light_no_content.png" alt="Desktop - light - no content" width="420">
</p>

#### Mobile

<p align="center">
  <img src=".github/assets/mobile_light_content.png" alt="Mobile - light - content" width="220">
  <img src=".github/assets/mobile_light_no_content.png" alt="Mobile - light - no content" width="220">
</p>

## Key Features

- **Real-time intervention**: The AI pauses at key steps and waits for your input.
- **Web UI**: Browser-based interaction, Markdown rendering and code highlighting.
- **Long-running**: Keep the UI open and handle multiple rounds of feedback.
- **SSH-friendly**: Designed for remote development.
- **Rich content**: Markdown + tables + code blocks + MathJax (lazy loaded).
- **Multi-task**: Multiple tasks with tab switching and independent countdown timers.
- **Auto re-submit**: Configurable countdown to keep AI sessions alive.

## Installation

### Option 1: Install from PyPI (recommended)

```bash
pip install ai-intervention-agent

# or
uv add ai-intervention-agent

# Verify installation (recommended)
python -c "import importlib.metadata as m; print(m.version('ai-intervention-agent'))"
```

### Option 2: Use via uvx

Configure your AI tool to launch the MCP server via `uvx`.

### Option 3: Development mode (local repo)

```bash
git clone https://github.com/xiadengma/ai-intervention-agent.git
cd ai-intervention-agent

pip install uv && uv sync

# Quick smoke test (starts a Web UI on the given port)
uv run python test.py --port 8082 --verbose --thread-timeout 0

# Quality checks
uv run ruff check .
uv run ruff format --check .
uv run ty check .
uv run python scripts/minify_assets.py --check
```

> This repo includes GitHub Actions workflows for tests and release (see `.github/workflows/`).

## VSCode Extension (Monorepo)

This repository is organized as a monorepo. The VSCode extension lives in `packages/vscode/`.

**Note**: The PyPI package `ai-intervention-agent` does not ship the VSCode extension source/artifacts. The extension is provided as a companion project in the same repository.

### Local development

```bash
# Install Node dependencies at repo root (npm workspaces)
npm install

# VSCode extension: lint / test
npm run vscode:lint
npm run vscode:test
```

### Build a VSIX (.vsix)

```bash
# Generates a .vsix file under packages/vscode/
npm run vscode:package
```

### Settings (VSCode)

- `ai-intervention-agent.serverUrl`: AI Intervention Agent server URL (default: `http://localhost:8081`)

## MCP Configuration Examples

### Use PyPI package via uvx (recommended)

```json
{
  "mcpServers": {
    "ai-intervention-agent": {
      "command": "uvx",
      "args": ["ai-intervention-agent"],
      "timeout": 600,
      "autoApprove": ["interactive_feedback"]
    }
  }
}
```

### Use from GitHub via uvx

```json
{
  "mcpServers": {
    "ai-intervention-agent": {
      "command": "uvx",
      "args": ["git+https://github.com/xiadengma/ai-intervention-agent.git"],
      "timeout": 600,
      "autoApprove": ["interactive_feedback"]
    }
  }
}
```

### Local development

```json
{
  "mcpServers": {
    "ai-intervention-agent-local": {
      "command": "uv",
      "args": ["--directory", "/path/to/ai-intervention-agent", "run", "ai-intervention-agent"],
      "timeout": 600,
      "autoApprove": ["interactive_feedback"]
    }
  }
}
```

## Configuration (`config.jsonc`)

This project uses a JSONC configuration file (JSON with comments).

### Config file lookup order

- **uvx mode**: uses the **user config directory** only.
- **dev mode**: prefers `./config.jsonc` in the repo, then falls back to the user config directory.

User config directory:

- Linux: `~/.config/ai-intervention-agent/`
- macOS: `~/Library/Application Support/ai-intervention-agent/`
- Windows: `%APPDATA%/ai-intervention-agent/`

## Tests

### Unit tests

```bash
uv run pytest -q
```

### End-to-end UI smoke test

```bash
uv run python test.py --port 8082 --verbose --thread-timeout 0
```

## Assets / Minified files

Minified assets are generated by a Python script:

```bash
uv run python scripts/minify_assets.py
uv run python scripts/minify_assets.py --check
```

## Release (PyPI + GitHub Release)

- The workflow `.github/workflows/release.yml` triggers on tags like `v1.4.5`.
- It builds `sdist` + `wheel` via `uv build`, validates with `twine check`, publishes to PyPI via **Trusted Publisher**, and creates a GitHub Release.

To publish:

1. Update `pyproject.toml` version.
2. Push a tag `vX.Y.Z`.
3. Ensure PyPI Trusted Publisher is configured for this repo/workflow.
