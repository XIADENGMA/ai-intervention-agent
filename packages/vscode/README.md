# AI Intervention Agent (VS Code Extension)

English | [简体中文](https://github.com/XIADENGMA/ai-intervention-agent/blob/main/packages/vscode/README.zh-CN.md)

This VS Code extension embeds the AI Intervention Agent interaction panel into VS Code’s sidebar, so you can handle workflows like `interactive_feedback` directly inside the editor.

## Features

- **Sidebar integration**: A dedicated view entry in the Activity Bar
- **Multi-task / multi-tab**: Switch between multiple tasks easily
- **Countdown display**: Visual ring progress UI
- **Theme adaptive**: Matches VS Code light/dark themes
- **Resilient networking**: Retry and error handling built-in

## Requirements

- VS Code `>= 1.74.0`
- A reachable AI Intervention Agent server (default: `http://localhost:8080`)

## Installation

> Open VSX page: `https://open-vsx.org/extension/xiadengma/ai-intervention-agent`

### Option 1: Install a VSIX

1. Build or download a `.vsix`
2. In VS Code, open Command Palette → **Extensions: Install from VSIX...**

### Option 2: Develop from source (monorepo)

1. Open the repository root (this repo)
2. Install dependencies:

```bash
npm install
```

3. Press `F5` in VS Code to launch an Extension Development Host

## Settings

- `ai-intervention-agent.serverUrl`: server URL (default: `http://localhost:8080`)
- `ai-intervention-agent.logLevel`: extension log level (default: `info`; view: Output → AI Intervention Agent)
- `ai-intervention-agent.enableAppleScript`: allow running AppleScript via `osascript` on macOS (default: `false`; used for macOS native notifications, window management, etc.)

## macOS native notifications (optional)

1. Enable `ai-intervention-agent.enableAppleScript` in VS Code settings
2. Open Command Palette and run **AI Intervention Agent: 测试 macOS 原生通知**

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
  - Make sure the server is reachable (default port 8080, or your configured `serverUrl`)
  - Check VS Code Developer Tools console logs

## Repository

- [`XIADENGMA/ai-intervention-agent`](https://github.com/XIADENGMA/ai-intervention-agent)

