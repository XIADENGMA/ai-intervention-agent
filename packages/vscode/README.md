# AI Intervention Agent (VSCode Extension)

English | [简体中文](https://github.com/XIADENGMA/ai-intervention-agent/blob/main/packages/vscode/README.zh-CN.md)

This VSCode extension embeds the AI Intervention Agent interaction panel into VSCode’s sidebar, so you can handle workflows like `interactive_feedback` directly inside the editor.

## Features

- **Sidebar integration**: A dedicated view entry in the Activity Bar
- **Multi-task / multi-tab**: Switch between multiple tasks easily
- **Countdown display**: Visual ring progress UI
- **Theme adaptive**: Matches VSCode light/dark themes
- **Resilient networking**: Retry and error handling built-in

## Requirements

- VSCode `>= 1.74.0`
- A reachable AI Intervention Agent server (default: `http://localhost:8081`)

## Installation

> Open VSX page: `https://open-vsx.org/extension/xiadengma/ai-intervention-agent`

### Option 1: Install a VSIX

1. Build or download a `.vsix`
2. In VSCode, open Command Palette → **Extensions: Install from VSIX...**

### Option 2: Develop from source (monorepo)

1. Open the repository root (this repo)
2. Install dependencies:

```bash
npm install
```

3. Press `F5` in VSCode to launch an Extension Development Host

## Settings

- `ai-intervention-agent.serverUrl`: server URL (default: `http://localhost:8081`)

## Build a VSIX (.vsix)

From the repository root:

```bash
npm run vscode:package
```

The generated `.vsix` file will appear under `packages/vscode/`.

## Development & Tests

From the repository root:

```bash
npm run vscode:lint
npm run vscode:test
```

## Troubleshooting

- **No requests shown**:
  - Make sure the server is reachable (default port 8081, or your configured `serverUrl`)
  - Check VSCode Developer Tools console logs

## Repository

- [`XIADENGMA/ai-intervention-agent`](https://github.com/XIADENGMA/ai-intervention-agent)

