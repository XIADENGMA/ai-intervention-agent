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

- VS Code `>= 1.105.0`
- A reachable AI Intervention Agent server (default: `http://localhost:8080`)

## Installation

> Open VSX page: `https://open-vsx.org/extension/xiadengma/ai-intervention-agent`
>
> The extension is published on Open VSX only. Editors that use Open VSX as their extension registry
> (Cursor, VSCodium, Windsurf and other VS Code-based editors) find it by name in the Extensions view.
> Microsoft's VS Code does not search Open VSX: download the `.vsix` from the Open VSX page or from
> [GitHub Releases](https://github.com/xiadengma/ai-intervention-agent/releases/latest) and use Option 1.

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
- `ai-intervention-agent.i18n.pseudoLocale` _(experimental)_: when `true`, swaps the active UI bundle for a pseudo-localised one — useful for spotting hardcoded strings, layout overflow, and Unicode issues without leaving English. Default: `false`.

> Notification toggles (Web / sound / system / Bark) are managed in the **Notifications** section of the panel's **Settings** page and persisted in the server-side `config.toml`, not in `settings.json`.

> **How a new request reaches you.** **Enable Notifications** is the master switch: when it is off, nothing is raised. When it is on, each new request is announced by a regular VS Code notification (a toast at the bottom right). If **macOS Native Notification** is on as well and the extension runs on macOS, the macOS banner is the notification and the editor keeps only the quiet status-bar message instead of a toast. A remote or non-macOS host cannot show the banner, so there the toast is always used and the **macOS Native Notification** row is not shown at all. The panel's **Test Notification** button sends a test through exactly this route. While **Enable Notifications** is off, the options under it are dimmed; they can still be edited, so Bark can be set up first.

## AppleScript executor (macOS only) · security model

The extension ships an internal AppleScript executor (`applescript-executor.ts`) used by the macOS native notification path. It is **not** a user-facing "run arbitrary AppleScript" command — there is no command palette entry that hands user input to `osascript`. It is bound by the following safeguards:

- **Platform check**: rejects with `PLATFORM_NOT_SUPPORTED` on non-`darwin` (`process.platform !== 'darwin'`).
- **Absolute binary path**: invokes `/usr/bin/osascript` (no `PATH` lookup, immune to PATH poisoning).
- **stdin script delivery**: passes the script body via stdin (`osascript -`) instead of as command-line arguments, eliminating shell-quoting bugs.
- **Hard timeout**: 8 s default (`APPLE_SCRIPT_TIMEOUT` thrown on overrun); kills the child via SIGTERM/SIGKILL.
- **Output cap**: 1 MiB stdout/stderr buffer ceiling.
- **Log redaction**: `sanitizeForLog()` collapses newlines and truncates to 160 chars before any debug log line is emitted.
- **No user-supplied scripts**: the only call sites compose the script from constants + `toAppleScriptStringLiteral()`-escaped values pulled from the notification payload.

If you want to disable the AppleScript path entirely, toggle macOS native notifications off in the panel's **Settings** page (Notifications section) — the executor will not be invoked.

> Reporting a security issue in this surface? Follow the
> repository [`SECURITY.md`](../../.github/SECURITY.md) — please use a
> private GitHub Security Advisory rather than a public issue.

## macOS native notifications

- Native notifications are delivered via a bundled `terminal-notifier` app on macOS (preferred), with a fallback to `osascript display notification`.
- Notification content shows the task's **feedback content summary** (consistent with Bark push), not just the task ID.
- Sender attribution (app icon/name) is **best-effort**. The extension tries to attribute notifications to the host editor app (e.g. VS Code / Cursor). If the attribution mechanism is unavailable on your system, notifications may fall back to the default sender.
- You can enable/disable it in the sidebar panel → **Settings** → **Notifications** → **macOS Native Notification** (default: enabled; the row is only shown when the extension runs on macOS). With it off, a new request is announced by a VS Code notification instead (see above).

### macOS notification display settings

The notification display style (banner / notification center only) is controlled by **macOS System Settings**, not by the extension:

1. Open **System Settings** → **Notifications**
2. Find your host editor in the app list (e.g. **Cursor** or **Visual Studio Code**)
3. Set the notification style to **Banners** (not "None" or "Notification Center" only)
4. Make sure **Allow Notifications** is enabled and **Play sound for notifications** is checked

> Tip: If notifications only appear in the Notification Center but do not pop up as banners, it is usually because step 3 above is set to "Notification Center".

## Build a VSIX (.vsix)

From the repository root:

```bash
npm run vscode:package
```

The generated `.vsix` file will appear under `packages/vscode/`.

> Note: The `.vsix` file is a build artifact (gitignored). If you run `vscode:package` / `vscode:check` repeatedly and want to clean up old files:
>
> ```bash
> rm -f packages/vscode/*.vsix
> ```

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

## Changelog

- **Extension-only (curated for the Open VSX listing)**: [`CHANGELOG.md`](CHANGELOG.md)
- **Repository-wide (server / Web UI / docs)**: [GitHub `CHANGELOG.md`](https://github.com/xiadengma/ai-intervention-agent/blob/main/CHANGELOG.md)

## Repository

- [`XIADENGMA/ai-intervention-agent`](https://github.com/XIADENGMA/ai-intervention-agent)
