<div align="center">
  <a href="https://github.com/xiadengma/ai-intervention-agent">
    <img src="src/ai_intervention_agent/icons/icon.svg" width="160" height="160" alt="AI Intervention Agent" />
  </a>

  <h2>AI Intervention Agent</h2>

  <p><strong>Real-time user intervention for MCP agents — pause, course-correct, resume.</strong></p>

  <p>
    <a href="https://pypi.org/project/ai-intervention-agent/">
      <img src="https://img.shields.io/pypi/v/ai-intervention-agent?style=for-the-badge&logo=pypi&logoColor=white&color=a855f7&label=PyPI" alt="PyPI" />
    </a>
    <a href="https://modelcontextprotocol.io">
      <img src="https://img.shields.io/badge/MCP-Compatible-d97757?style=for-the-badge&logo=anthropic&logoColor=white" alt="MCP Compatible" />
    </a>
    <a href="https://github.com/xiadengma/ai-intervention-agent/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge" alt="License: MIT" />
    </a>
  </p>

  <p>
    English | <a href="./README.zh-CN.md">简体中文</a>
  </p>
</div>

---

Ever had your AI agent confidently walk off in the wrong direction mid-task? AI Intervention Agent gives you a Web UI to **pause** the agent at key moments, review what it's about to do, type a course-correction, attach screenshots, and **resume** — all through the MCP `interactive_feedback` tool, without ending the conversation.

Works with `Cursor`, `VS Code`, `Claude Code`, `Augment`, `Windsurf`, `Trae`, and more.

## Quick start

### Quickest: ask your AI to install it for you

If your IDE/CLI has an AI agent (Cursor, Claude Code, VS Code, Windsurf, Trae, Augment, ...), paste the prompt below in chat and let it write the config for you.

<details>
<summary>Click to copy the install prompt</summary>

```text
Please configure my IDE / AI tool to use the `ai-intervention-agent` MCP server:

1. Locate the correct MCP config file for my current IDE
   (e.g. `.cursor/mcp.json` or `~/.cursor/mcp.json` for Cursor,
    `~/.claude.json` for Claude Code,
    `.vscode/mcp.json` for VS Code).
2. Add this entry under `mcpServers`:
   - command: `uvx`
   - args: `["ai-intervention-agent"]`
   - timeout: 600
   - autoApprove: `["interactive_feedback"]`
3. Append the project's recommended prompt rules
   (the "Prompt snippet (copy/paste)" block in this README)
   to my agent rules / system prompt, so the agent always asks me
   through `interactive_feedback` instead of ending tasks silently.
4. Verify by listing MCP servers and confirming `ai-intervention-agent` is loaded.
```

</details>

### Option 1: Using `uvx` (Recommended)

[<img src="https://img.shields.io/badge/Install%20Server-Cursor-black?style=flat-square" alt="Install in Cursor">](https://cursor.com/en/install-mcp?name=ai-intervention-agent&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJhaS1pbnRlcnZlbnRpb24tYWdlbnQiXSwidGltZW91dCI6NjAwLCJhdXRvQXBwcm92ZSI6WyJpbnRlcmFjdGl2ZV9mZWVkYmFjayJdfQ%3D%3D)
[<img src="https://img.shields.io/badge/Install%20Server-VS%20Code-0098FF?style=flat-square" alt="Install in VS Code">](https://vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522ai-intervention-agent%2522%252C%2522command%2522%253A%2522uvx%2522%252C%2522args%2522%253A%255B%2522ai-intervention-agent%2522%255D%252C%2522timeout%2522%253A600%252C%2522autoApprove%2522%253A%255B%2522interactive_feedback%2522%255D%257D)

Configure your AI tool to launch the MCP server directly via `uvx` (this automatically installs and runs the latest version):

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

### Option 2: Using `pip`

1. First, install the package manually (please remember to manually `pip install --upgrade ai-intervention-agent` periodically to get updates):

```bash
pip install ai-intervention-agent
```

2. Configure your AI tool to launch the installed MCP server:

```json
{
  "mcpServers": {
    "ai-intervention-agent": {
      "command": "ai-intervention-agent",
      "args": [],
      "timeout": 600,
      "autoApprove": ["interactive_feedback"]
    }
  }
}
```

> [!NOTE]
> `interactive_feedback` is a **long-running tool**. Some clients have a hard request timeout, so the Web UI provides a countdown + auto re-submit option to keep sessions alive.
>
> - Default: `feedback.frontend_countdown=240` seconds
> - Range: `0` (disabled) or `[10, 3600]` seconds. The default 240 stays
>   under the common 300s session hard timeout; raise it intentionally
>   when your client allows longer turns.

3. (Optional) Customize your config:

- On first run, `config.toml` will be created under your OS user config directory (see [docs/configuration.md](docs/configuration.md)).
- Example:

```toml
[web_ui]
port = 8080

[feedback]
frontend_countdown = 240
backend_max_wait = 600
```

<details>
<summary>Prompt snippet (copy/paste)</summary>

```text
- Only ask me through the MCP `ai-intervention-agent` tool; do not ask directly in chat or ask for end-of-task confirmation in chat.
- If a tool call fails, keep asking again through `ai-intervention-agent` instead of making assumptions, until the tool call succeeds.

ai-intervention-agent usage details:

- If requirements are unclear, use `ai-intervention-agent` to ask for clarification with predefined options.
- If there are multiple approaches, use `ai-intervention-agent` to ask instead of deciding unilaterally.
- If a plan/strategy needs to change, use `ai-intervention-agent` to ask instead of deciding unilaterally.
- Before finishing a request, always ask for feedback via `ai-intervention-agent`.
- Do not end the conversation/request unless the user explicitly allows it via `ai-intervention-agent`.
```

</details>

## Screenshots

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/desktop_dark_content.png">
    <img alt="Desktop - feedback page (multi-task tabs, code highlighting, predefined options)" src=".github/assets/desktop_light_content.png" width="600" height="501" />
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mobile_dark_content.png">
    <img alt="Mobile - feedback page" src=".github/assets/mobile_light_content.png" width="180" height="447" />
  </picture>
</p>

<p align="center"><sub>Feedback page · auto switches between dark/light · multi-task tabs with independent countdowns</sub></p>

<details>
<summary>More screenshots (empty state + settings)</summary>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/desktop_dark_no_content.png">
    <img alt="Desktop - empty state" src=".github/assets/desktop_light_no_content.png" width="600" height="422" />
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mobile_dark_no_content.png">
    <img alt="Mobile - empty state" src=".github/assets/mobile_light_no_content.png" width="180" height="390" />
  </picture>
</p>

<p align="center"><sub>Empty state · waiting for the next interactive request</sub></p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/desktop_dark_settings.png">
    <img alt="Desktop - settings (notifications, Bark, feedback)" src=".github/assets/desktop_light_settings.png" width="600" height="422" />
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mobile_dark_settings.png">
    <img alt="Mobile - settings" src=".github/assets/mobile_light_settings.png" width="180" height="390" />
  </picture>
</p>

<p align="center"><sub>Settings · notifications · Bark · sound · feedback countdown · auto switches between dark/light</sub></p>

</details>

## Key features

- ⚡ **Real-time intervention** — the agent pauses and waits for your input via `interactive_feedback`
- 🖥️ **Web UI** — Markdown, code highlighting, and math rendering out of the box
- 🗂️ **Multi-task tabs** — switch between concurrent requests, each with its own countdown
- 🔁 **Auto re-submit** — keep long-running sessions alive past client hard timeouts; the countdown **auto-extends while you are typing** (reusing the `+60s` quota), and when it hits zero your **typed text and checked options are submitted** instead of an empty prompt — the backend wait follows the extension, so no input is ever lost
- 🔔 **Notifications** — web / sound / system / Bark (loopback URLs auto-suppressed; LAN-IP suggestion in settings)
- 🌐 **SSH / LAN friendly** — works behind port forwarding; mDNS publishes a `<host>.local` URL when supported
- 🏷️ **Header chips & Yes/No buttons** — agents can attach a ≤16-char `header_label` chip ("Auth", "DB", "i18n") for instant context, or set `question_type='yesno'` to render a one-click binary decision instead of a free-text textarea (borrowed from `gemini-cli` `ask_user`)
- 🎨 **Custom placeholder hints** — per-task `feedback_placeholder` lets agents pre-fill the textarea hint (200-char clamp, falls back to i18n default)
- 🌏 **i18n** — Web UI + VS Code extension shipped in `en` / `zh-CN` / `zh-TW` (plus pseudo-locale for translation coverage testing)
- ⚡ **Productivity shortcuts** — keyboard cheatsheet overlay (press `?`), per-textarea **draft autosave** (per-task; survives reload), configurable **submit mode** (Ctrl/Cmd+Enter vs Enter), and a live **character counter** with three-color thresholds
- 💬 **Quick reply phrases** — save / edit / reuse canned responses in `localStorage`; JSON export + import for cross-device migration; one-click insert into the feedback textarea
- 🔊 **Custom notification sound** — upload your own audio file (mp3/wav/ogg/m4a/flac, ≤ 700 KB, ≤ 30 s) to replace the built-in beep; persisted in `localStorage` (base64) so it survives across sessions
- ⏱️ **Countdown extension** — `+60s` button to delay auto-resubmit when you need a bit more thinking time, plus a permanent ❄️ **freeze** button to disable auto-resubmit entirely for sessions where you genuinely need to step away (available in both the web page and the VS Code extension)
- 🟢 **SSE liveness indicator** — 3-state corner badge (good / degraded / offline) so you always know whether the page is in sync with the backend
- 📱 **PWA install support** — `manifest.webmanifest` + Service Worker so the Web UI is installable from the browser's native menu (Chrome / Edge address-bar icon, or iOS Safari Share → Add to Home Screen); a dedicated iOS Safari hint banner reminds users where the native option lives (since iOS doesn't fire `beforeinstallprompt`); permanently dismissable
- 📡 **Offline-aware** — service worker pre-caches a branded `offline.html` shell with bilingual reconnect hints, dark/light theme + reduced-motion respect, and an auto-recovery ping that reloads when service returns (replaces the default browser "site can't be reached" screen)
- ♿ **WCAG 2.1 AA accessible** — every focus indicator, body text, status color, modal overlay, primary/secondary button, and icon-only button passes WCAG 2.1 AA contrast + Name/Role/Value rules (audited cycles 1-40, 240+ a11y / correctness / consistency / concurrency-safety / API-contract invariants and 8,200+ tests, with new meta-lint patterns each cycle for setting labels, async reset confirmations, finally-block DOM null guards, **AST-based lock-acquisition-order contracts** (cycle-35), **cross-runtime resource lifecycle audits** (cycle-38, Python/Browser-JS/VS Code TS), and (new in cycle-40) **OpenAPI docstring coverage** + **i18n untranslated keys detection**); keyboard cheatsheet overlay traps Tab + restores opener focus on close; all three `role="dialog"` modals (settings, image preview, code paste) have consistent ESC + close-button + backdrop-click handling; supports `prefers-reduced-motion` and `prefers-contrast: more` for high-contrast OS modes
- 🛡️ **Stable install** — built on Flask 3.x with conservative dependency pins
  - Immune to the [Starlette 1.0 breaking change](https://github.com/Minidoracat/mcp-feedback-enhanced/issues/213) that left several MCP feedback servers broken-on-default-install in early 2026

> Architecture diagram, "how it works" flow, production middleware chain,
> server self-info resource, and MCP-spec compliance details live under
> [`docs/api/index.md`](docs/api/index.md) and
> [`docs/mcp_tools.md`](docs/mcp_tools.md).

## Architecture overview

A bird's-eye view of how AIIA's components fit together — useful when
you're integrating a new client (custom MCP host, alternate IDE plugin)
or debugging a cross-component issue.

```mermaid
graph LR
    subgraph Clients["Clients (any MCP host)"]
        A1[LLM Agent<br/>Cursor / Cline / Augment]
        A2[Web browser<br/>multi-task dashboard]
        A3[VS Code extension<br/>sidebar webview]
        A4[CLI<br/>--print-config / --version]
    end

    subgraph Backend["AIIA backend (single Python process)"]
        B1[MCP server<br/>stdio + interactive_feedback]
        B2[Flask web server<br/>/api/* + SSE bus]
        B3[Task queue<br/>RW-lock + persist]
        B4[Notification manager<br/>browser / system / Bark]
        B5[Config manager<br/>TOML + env override]
    end

    subgraph External["External"]
        E1[File system<br/>config.toml + tasks.json]
        E2[Browser / OS<br/>system notifications]
        E3[Bark API<br/>iOS push]
    end

    A1 -- MCP stdio --> B1
    A2 -- HTTP + SSE --> B2
    A3 -- HTTP + SSE --> B2
    A4 -- module import --> B5

    B1 -- enqueue task --> B3
    B2 -- read / mutate --> B3
    B3 -- task_changed event --> B2
    B2 -- "broadcast SSE<br/>(R51-B heartbeat 25s)" --> A2
    B2 -- broadcast SSE --> A3
    B3 -- on add_task --> B4
    B4 -- "Web Notification API" --> E2
    B4 -- POST --> E3
    B5 -- read / watch mtime --> E1
    B3 -- persist on mutate --> E1
```

**Key invariants** (locked by tests in `tests/`):
- `task_changed` SSE payload schema enforced cross-language
  (Python ↔ JS, `test_feat_sse_cross_language_schema_r297.py`).
- SSE heartbeat = 25s, cleanup interval = 5s, hot-path throttle = 30s,
  JS health check = 30s — locked across all source files
  (`test_feat_perf_baseline_const_r296.py`).
- Static `interactive_feedback` MCP core tool surface — no dynamic-tool-first
  migration and no fan-out to multiple primary LLM-facing endpoints. Dynamic
  registration is reserved for future optional/conditional diagnostics after
  client `tools/list_changed` refresh behavior is proven.
- **Concurrency safety (new in cycle-35/36)** — AST-based lock-order
  contracts statically verify all `threading.Lock` / `RLock` /
  `ReadWriteLock` usages across `task_queue.py`, `notification_manager.py`,
  `service_manager.py`, `config_manager.py`, `web_ui.py`. Any future
  change is rejected by CI if it (a) introduces a deadlock cycle, (b)
  bypasses the deadlock-aware `_watched_write_lock` wrapper, (c) adds an
  unaudited `RLock`, or (d) acquires the same `Lock` twice in the same
  call chain. See `test_feat_async_race_contract_r326.py` +
  `test_feat_lock_acquisition_order_r328.py` +
  `test_feat_service_manager_lock_order_r329.py` +
  `test_feat_rlock_usage_contract_r330.py` +
  `test_feat_web_ui_rlock_contract_r331.py`.
- **Lazy-init audit (new in cycle-35)** — every `_ensure_*` function in
  `src/` is classified into `_loaded` (multi-attribute import) /
  `_registered` (single-flag callback) / `_started` (daemon thread spawn)
  with category-specific safety contracts; new lazy-init functions are
  rejected by CI until audited and classified
  (`test_feat_lazy_init_audit_r327.py`).

For deeper subsystem detail (config schema, MCP tool reference,
i18n strategy, troubleshooting), follow the links in
[`Documentation`](#documentation) below.

## Agent / Glass mode workflow

AIIA is designed for **long-running autonomous agent loops** (Cursor
Composer, Cursor Glass mode, Cline, Augment, Trae) where the LLM calls
`interactive_feedback` many times during a single run. The combined
agent-side parameters + user-side UX features below let a human reviewer
decide in **< 5 seconds per task**, so the agent never blocks the
flow longer than necessary.

### How a single interaction flows

```mermaid
sequenceDiagram
    participant Agent as LLM Agent<br/>(Cursor / Cline)
    participant MCP as MCP transport
    participant AIIA as AIIA backend<br/>(Flask + SSE)
    participant UI as Web UI / VS Code
    participant Human as Human reviewer

    Agent->>MCP: interactive_feedback(message,<br/>header_label, question_type, ...)
    MCP->>AIIA: POST /api/tasks
    AIIA->>UI: SSE task.created
    UI->>Human: Browser/system notification<br/>+ countdown timer
    Note over Human: Reads chip + prompt,<br/>clicks Yes/No or types reply
    Human->>UI: Submit
    UI->>AIIA: POST /api/tasks/{id}/complete
    AIIA->>MCP: SSE task.completed (+ ctx.info)
    MCP->>Agent: Returns text + images + selected options
    Note over Agent: Resumes execution<br/>with human input
```

### Failure & recovery flows

Beyond the happy path above, three boundary cases keep long-running
Agent / Glass-mode sessions resilient: **auto-resubmit** (human steps
away), **SSE reconnect** (network drop), and **❄️ freeze** (deep review
across page refreshes).

```mermaid
sequenceDiagram
    autonumber
    participant Agent as LLM Agent
    participant AIIA as AIIA backend
    participant UI as Web UI
    participant Human as Human reviewer

    Note over Agent,Human: ① Auto-resubmit (human stepped away)
    Agent->>AIIA: interactive_feedback<br/>(auto_resubmit_timeout=120)
    AIIA->>UI: SSE task.created (countdown=120s)
    Note over UI: countdown hits 0<br/>(no ❄️ freeze clicked)
    UI->>AIIA: POST /api/tasks/{id}/auto-resubmit
    AIIA->>Agent: SSE task.completed<br/>(with "auto-resubmit" marker)

    Note over UI,AIIA: ② SSE drop → degraded poll → reconnect
    UI--xAIIA: SSE disconnect (sleep/network jitter)
    UI->>AIIA: GET /api/tasks (fallback poll, every 5s)
    UI->>AIIA: SSE reconnect (exponential backoff)
    AIIA-->>UI: SSE resumed

    Note over Agent,Human: ③ ❄️ Freeze (long review across refreshes)
    Agent->>AIIA: interactive_feedback<br/>(auto_resubmit_timeout=60)
    UI->>Human: countdown shows 60s
    Human->>UI: click ❄️ freeze
    Note over UI: persist freeze to localStorage<br/>(survives page refresh)
    Human->>UI: unfreeze + submit
    UI->>AIIA: POST /api/tasks/{id}/complete
    AIIA->>Agent: SSE task.completed (full reply)
```

### Agent-side parameters (LLM passes these via MCP)

| Parameter | Purpose | Max | Source |
|---|---|---|---|
| `header_label` | One-word context chip in task pane (`Auth`, `DB`, `i18n`) | 16 chars | gemini-cli `ask_user.header` |
| `question_type='yesno'` | Hide textarea + render 2-button binary decision | — | gemini-cli `ask_user` |
| `feedback_placeholder` | Per-task textarea hint (overrides global i18n) | 200 chars | gemini-cli `ask_user` |
| `auto_resubmit_timeout` | Per-task countdown override (0 = disable) | `[0, 3600]` sec | AIIA native |
| `predefined_options` | Multi-select chips with optional `default: true` recommendation | 10000 chars/each | AIIA + upstream parity |

Full parameter reference + a single complete Agent-mode call example
(`Auth` refactor flow combining all 4 + `predefined_options`) lives in
[`docs/mcp_tools.md#agent-mode-parameters-cursor--composer--cline--augment--trae`](docs/mcp_tools.md#agent-mode-parameters-cursor--composer--cline--augment--trae).

### User-side workflow features (built into the Web UI)

- **Multi-task tabs** — when an agent fires 3+ requests in parallel
  (typical Cursor Composer multi-edit), each gets its own tab + independent
  countdown ring; switching tabs preserves textarea drafts
- **Per-task draft autosave** — typing into one task tab and switching
  to another doesn't lose your in-progress reply
- **Countdown extend (`+60s`) + permanent freeze (`❄️`)** — when you
  need to step away or think longer, extend (limited reps) or freeze
  the auto-resubmit
- **Quick reply phrases** — common replies (`"yes do that"`,
  `"diff first then apply"`) saved to `localStorage`, one-click insert
- **Custom notification sound** — upload your own short audio file
  (`.mp3`/`.wav`/...) so Agent-mode tasks have a distinct chime
- **Per-task images** — paste screenshots / diagrams (≤ 700 KB) inline
  with the reply, returned to the agent as MCP `ImageContent` blocks
- **SSE liveness badge** — green/orange/red corner indicator so you
  always know whether the page is in sync (matters in long Agent runs)

### Recommended LLM system prompt

To force the agent to actually use this tool instead of "auto-finishing"
the task, append the snippet under [`提示词（可复制）`](#方式一使用-uvx-启动推荐)
(or its English copy) to your IDE's system prompt / `.cursorrules`.

## VS Code extension (optional)

<p>
  <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
    <img src="https://img.shields.io/open-vsx/v/xiadengma/ai-intervention-agent?label=Open%20VSX&style=flat-square&logo=eclipseide&logoColor=white" alt="Open VSX version" />
  </a>
  <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
    <img src="https://img.shields.io/open-vsx/dt/xiadengma/ai-intervention-agent?label=downloads&style=flat-square" alt="Open VSX downloads" />
  </a>
  <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
    <img src="https://img.shields.io/open-vsx/rating/xiadengma/ai-intervention-agent?label=rating&style=flat-square" alt="Open VSX rating" />
  </a>
</p>

| Item                           | Value                                                                                                                                                                                                                                                                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Purpose                        | Embed the interaction panel into VS Code’s sidebar to avoid switching to a browser.                                                                                                                                                                                                                                            |
| Install (Open VSX)             | [Open VSX](https://open-vsx.org/extension/xiadengma/ai-intervention-agent)                                                                                                                                                                                                                                                     |
| Download VSIX (GitHub Release) | [GitHub Releases](https://github.com/xiadengma/ai-intervention-agent/releases/latest)                                                                                                                                                                                                                                          |
| Setting                        | `ai-intervention-agent.serverUrl` (should match your Web UI URL, e.g. `http://localhost:8080`; you can change `web_ui.port` in [`config.toml.default`](config.toml.default))                                                                                                                                                   |
| Other settings                 | `ai-intervention-agent.logLevel` (Output → AI Intervention Agent). macOS native notifications are enabled by default and can be toggled in the sidebar's **Notification Settings** panel. See [`packages/vscode/README.md`](packages/vscode/README.md) for the full settings list and the AppleScript executor security model. |

## Configuration

| Item             | Value                                                                                          |
| ---------------- | ---------------------------------------------------------------------------------------------- |
| Docs (English)   | [docs/configuration.md](docs/configuration.md)                                                 |
| Docs (简体中文)  | [docs/configuration.zh-CN.md](docs/configuration.zh-CN.md)                                     |
| Default template | [`config.toml.default`](config.toml.default) (on first run it will be copied to `config.toml`) |

| OS      | User config directory                                  |
| ------- | ------------------------------------------------------ |
| Linux   | `~/.config/ai-intervention-agent/`                     |
| macOS   | `~/Library/Application Support/ai-intervention-agent/` |
| Windows | `%APPDATA%/ai-intervention-agent/`                     |

### Quick overrides (no file edits required)

For `uvx`, Docker, systemd, or SSH-remote runtimes where editing
`config.toml` is awkward, the most-used `web_ui` settings can be
overridden by env var at process startup:

```bash
export AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0      # default 127.0.0.1
export AI_INTERVENTION_AGENT_WEB_UI_PORT=8181         # default 8080, range [1, 65535]
export AI_INTERVENTION_AGENT_WEB_UI_LANGUAGE=en       # auto / en / zh-CN
uvx ai-intervention-agent
```

Invalid values log a `WARNING` and fall back to `config.toml`/defaults
so a typo never blocks server startup. See
[`docs/configuration.md#environment-variable-overrides`](docs/configuration.md#environment-variable-overrides)
for the full surface (timeouts, log level, etc.).

### CLI inspection

```bash
ai-intervention-agent --version       # or -V — print version and exit
ai-intervention-agent --help          # or -h — show usage + config hints
ai-intervention-agent --print-config  # dump effective merged config + env overrides
```

`--print-config` answers _"is my port 8181 because of env, or `config.toml`?"_
in one shell pipeline — output is JSON (`jq` friendly):

- `config_file_path` — absolute path of the loaded TOML
- `using_defaults` — `true` if the loaded file is the bundled default
  (i.e. you haven't created your own `config.toml` yet)
- `web_ui` — resolved host / port / language (back-compat top-level)
- `sections` — every non-sensitive section
  (`web_ui` / `mdns` / `feedback` / `notification`); secret-like
  fields (`*_device_key`, `*_token`, `*_secret`, `password`,
  `*_api_key`, …) auto-redacted to `***REDACTED***`
- `env_overrides` — active `AI_INTERVENTION_AGENT_WEB_UI_*` env vars

`network_security` is filtered out at the `ConfigManager.get_all()`
boundary (same trust level as
[`/api/system/health`](docs/configuration.md#environment-variable-overrides)),
so monitoring and CLI tell the same story.

## Documentation

- **Docs index** (by audience): [`docs/README.md`](docs/README.md) · [`docs/README.zh-CN.md`](docs/README.zh-CN.md)
- **Scripts index** (CI gates / generators / QA): [`scripts/README.md`](scripts/README.md)
- **Release notes**: [`CHANGELOG.md`](CHANGELOG.md) · VS Code marketplace listing: [`packages/vscode/CHANGELOG.md`](packages/vscode/CHANGELOG.md)
- **Contributing**: [`CONTRIBUTING.md`](.github/CONTRIBUTING.md) · [`CODE_OF_CONDUCT.md`](.github/CODE_OF_CONDUCT.md)
- **API docs index**: [`docs/api/index.md`](docs/api/index.md)
- **API docs (简体中文)**: [`docs/api.zh-CN/index.md`](docs/api.zh-CN/index.md)
- **MCP tool reference**: [`docs/mcp_tools.md`](docs/mcp_tools.md)
- **MCP 工具说明**: [`docs/mcp_tools.zh-CN.md`](docs/mcp_tools.zh-CN.md)
- **Troubleshooting / FAQ**: [`docs/troubleshooting.md`](docs/troubleshooting.md) · [`docs/troubleshooting.zh-CN.md`](docs/troubleshooting.zh-CN.md)
- **Release recovery runbook**: [`docs/release-recovery.md`](docs/release-recovery.md) · [`docs/release-recovery.zh-CN.md`](docs/release-recovery.zh-CN.md)
- **i18n contributor guide**: [`docs/i18n.md`](docs/i18n.md)
- **DeepWiki Q&A** — AI-augmented Q&A over the repo: <a href="https://deepwiki.com/xiadengma/ai-intervention-agent"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" valign="middle" /></a>

## Related projects

| Project | Stars (approx.) | Focus |
| --- | --- | --- |
| [mcp-feedback-enhanced](https://github.com/Minidoracat/mcp-feedback-enhanced) (Minidoracat) | ~3.8k | Largest sibling. Dual-interface (Web UI + Tauri desktop app), auto-command execution, intelligent SSH Remote / WSL detection. Supports Cursor / Cline / Windsurf / Augment / Trae. |
| [cunzhi](https://github.com/imhuso/cunzhi) (imhuso) | ~1.4k | Chinese-language project focused on preventing premature task completion ("告别 AI 提前终止烦恼"). |
| [Relay](https://glama.ai/mcp/servers/andeya/ide-relay-mcp) (andeya) | new | Multi-IDE relay (Cursor / Claude Code / Windsurf), multi-tab session merging, native desktop window, Cursor real-time usage monitoring. |
| [interactive-feedback-mcp (Node.js)](https://github.com/wellcomemayhem-spec/interactive-feedback-mcp-nodejs) | new | Node.js implementation of poliva's design with WebSocket real-time UI, **Speech-to-Text via OpenAI Whisper**, command execution with live output. |
| [interactive-feedback-mcp](https://github.com/junanchn/interactive-feedback-mcp) (junanchn) | ~50 | Win32-native always-on-top window, auto-reply rules (oneshot/loop modes), drag-drop / paste file paths. |
| [interactive-feedback-mcp](https://github.com/poliva/interactive-feedback-mcp) (poliva) | ~310 | Direct ancestor fork (rebased from noopstudios original — see Acknowledgements below); minimal Python MCP, single feedback dialog. |
| [interactive-feedback-mcp](https://github.com/Pursue-LLL/interactive-feedback-mcp) (Pursue-LLL) | ~30 | Independent smaller-scale fork emphasising minimal dependencies. |

**Where AIIA sits on the spectrum**: AIIA targets the operationally deep end — Web UI + VS Code extension sharing the same backend, production-grade observability (`/metrics` Prometheus endpoint + a [reference Grafana dashboard](docs/observability/README.md), SSE schema validation toggle), bilingual i18n + docs, strict invariant test discipline (8,200+ tests + 1,050+ subtests across **40 audit cycles**, including **AST-based lock-acquisition-order contracts** that statically prove the absence of deadlock cycles across all critical paths, **cross-runtime resource lifecycle audits** covering Python/Browser-JS/VS Code TS, and **OpenAPI docstring coverage** for all 32 API endpoints), pre-push tag-safety hook, and a 5-job release pipeline. If you want the smallest possible drop-in, poliva's fork; if you want a polished desktop app, mcp-feedback-enhanced; if you want voice / multi-tab UI, Relay or the Node.js fork; if you want full-stack operational integration with the deepest invariant test discipline, AIIA.

**Feature gap callouts** (planned for future releases, contributions welcome):
- 🎤 **Speech-to-Text input** — like the Node.js fork (Whisper API integration)
- 🪟 **Always-on-top native window** — like junanchn (currently Web UI only)
- 📊 **Cursor usage/billing monitoring** — like Relay (Cursor-specific)
- 🗂️ **Multi-tab session merging UI** — like Relay (AIIA has tasks but no unified tab hub)

> Star counts are approximate snapshots (last reviewed 2026-06); check each upstream for current numbers. Submit a PR if you'd like another related project listed.

## Acknowledgements

This project's heritage traces back to **Fábio Ferreira** (2024) and **Pau Oliva** (2025), whose original [`noopstudios/interactive-feedback-mcp`](https://github.com/noopstudios/interactive-feedback-mcp) and [`poliva/interactive-feedback-mcp`](https://github.com/poliva/interactive-feedback-mcp) seeded the MCP `interactive_feedback` tool surface. Their copyright notices are preserved in [`LICENSE`](LICENSE) per the MIT license terms. The v1.5.x line is a substantial rewrite — Web UI, VS Code extension, i18n, notification stack, CI/CD pipeline — owned and maintained by [@xiadengma](https://github.com/xiadengma) (PyPI / Open VSX / VS Code Marketplace publisher).

## License

MIT License

---

<details>
<summary><strong>Quality & Security</strong></summary>

<br />

<p>
  <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/test.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/test.yml?branch=main&label=tests&style=flat-square&logo=github" alt="Tests" />
  </a>
  <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/scorecard.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/scorecard.yml?branch=main&label=OpenSSF&style=flat-square&logo=securityscorecard&logoColor=white" alt="OpenSSF Scorecard" />
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/pypi/pyversions/ai-intervention-agent?style=flat-square&logo=python&logoColor=white" alt="Python versions" />
  </a>
</p>

- **Tests** — GitHub Actions test workflow status (runs on every push / PR)
- **OpenSSF Scorecard** — supply-chain security posture
- **Python versions** — supported runtime compatibility (declared in `pyproject.toml`)

</details>
