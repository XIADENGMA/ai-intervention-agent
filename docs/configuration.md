## Configuration

AI Intervention Agent uses a **TOML** config file to configure notifications, Web UI, security, and timeouts.

Default template: `config.toml.default`.

### Config file name

- Recommended: `config.toml`
- Backward compatible: `config.jsonc`, `config.json` (auto-migrated to TOML on first load)

### Config file location & lookup order

The lookup strategy depends on how you run the MCP server. The detection runs
in this order—**first match wins**:

| #   | Source                                      | Mode            | Wins when…                                                                                                                                                      |
| --- | ------------------------------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `AI_INTERVENTION_AGENT_CONFIG_FILE` env var | (any)           | Any value is set; absolute path or directory both supported                                                                                                     |
| 2   | `AI_INTERVENTION_AGENT_DEV_MODE=1` env      | Forced **dev**  | You're hacking inside the repo and want `./config.toml` even from outside the repo                                                                              |
| 3   | `AI_INTERVENTION_AGENT_USER_MODE=1` env     | Forced **user** | Inside the repo but want it to behave like a real install (e.g. systemd service)                                                                                |
| 4   | `UVX_PROJECT` env (legacy)                  | Forced **user** | Set by some uvx runners; back-compat                                                                                                                            |
| 5   | Auto-detected isolated runtime              | **user**        | `sys.executable` is in `~/.local/share/uv/tools/…` / `~/.local/share/pipx/venvs/…` / `~/.cache/uv/builds-…` / module is under `site-packages` / `dist-packages` |
| 6   | Repo-checkout heuristic                     | **dev**         | `pyproject.toml` + `server.py` next to `config_manager.py` AND your shell `cwd` is inside that tree                                                             |
| 7   | Default                                     | **user** (safe) | Anything else — never write `config.toml` into a stranger's `cwd`                                                                                               |

#### Override (all modes)

```bash
# Pin to a specific file
AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/config.toml

# Or a directory; `config.toml` gets appended automatically
AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/dir/

# Force dev mode from outside the repo (e.g. a CI shell)
AI_INTERVENTION_AGENT_DEV_MODE=1

# Force user mode while you're inside the repo (e.g. systemd service running from /opt/aiia)
AI_INTERVENTION_AGENT_USER_MODE=1
```

`UV_TOOL_DIR`, `UV_CACHE_DIR`, `PIPX_HOME`, and `PIPX_LOCAL_VENVS` are also
honoured: if `sys.executable` lives under any of those, the agent treats it as
an installed runtime even if your custom paths don't match the default
`~/.local/share/...` layout.

#### uvx / `uv tool install` / pipx mode (recommended for end users)

- Uses **only** the user config directory.
- If the file does not exist, it will create it by copying the packaged `config.toml.default`.
- `~/.local/share/uv/tools/<name>/`, `~/.local/share/pipx/venvs/<name>/`, and
  `~/.cache/uv/builds-…` are all detected automatically — you don't need to set
  any env vars.

#### Dev mode (running from the repo)

Priority order inside dev mode:

1. `./config.toml`
2. `./config.jsonc` (backward compatible, auto-migrated)
3. `./config.json` (backward compatible, auto-migrated)
4. User config directory (same priority order)
5. If none exist, it will create `config.toml` in the user config directory.

> Tip (avoid "I edited the config but nothing changed"):
> The Web UI "Settings → Config" shows the **actual config file path** used by the current process.
> If you want to force dev mode to use a specific config file, set `AI_INTERVENTION_AGENT_CONFIG_FILE` to that path, for example:
>
> - Linux: `AI_INTERVENTION_AGENT_CONFIG_FILE=~/.config/ai-intervention-agent/config.toml`
> - macOS: `AI_INTERVENTION_AGENT_CONFIG_FILE=~/Library/Application Support/ai-intervention-agent/config.toml`
> - Windows: `AI_INTERVENTION_AGENT_CONFIG_FILE=%APPDATA%/ai-intervention-agent/config.toml`

> Tip (avoid "I edited my config.jsonc but nothing changed"):
> If a directory contains both `config.toml` and `config.jsonc` (or `config.json`), TOML wins
> and the agent emits a `WARNING` log line listing the ignored siblings. Delete or rename the
> stale formats once you've migrated.

### Environment-variable overrides

For `uvx`, Docker, systemd and other "I can't easily edit `config.toml` here"
runtimes, the following env vars override the matching `config.toml` values at
process startup. They're applied inside `get_web_ui_config()` and cached for
the 10-second TTL like any other value.

| Env var                                 | Overrides         | Type / range           | Notes                                                                                          |
| --------------------------------------- | ----------------- | ---------------------- | ---------------------------------------------------------------------------------------------- |
| `AI_INTERVENTION_AGENT_WEB_UI_HOST`     | `web_ui.host`     | string                 | Typical values: `127.0.0.1` (loopback) or `0.0.0.0` (LAN / SSH-remote access)                  |
| `AI_INTERVENTION_AGENT_WEB_UI_PORT`     | `web_ui.port`     | int, `[1, 65535]`      | Out-of-range / non-numeric values are warned and ignored (server keeps using `config.toml`)    |
| `AI_INTERVENTION_AGENT_WEB_UI_LANGUAGE` | `web_ui.language` | `auto` / `en` / `zh-CN`| Forces the Web UI language regardless of OS locale or saved preference                         |

Non-matching values are **warned, not fatal**: env overrides are a convenience
path, so a typo in your shell profile shouldn't keep the MCP server from
starting. The original `config.toml` value is preserved and a `WARNING` line
is logged to stderr so you can find the typo there.

#### Example: SSH-remote bind on a non-default port

```bash
export AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0
export AI_INTERVENTION_AGENT_WEB_UI_PORT=18080
uvx ai-intervention-agent
```

> **Security note — binding to non-loopback.** Setting
> `AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0` (or any non-`127.0.0.1`
> address) exposes endpoints like `/api/get-notification-config` to
> anyone on the same network. Those responses include user-specific
> credentials such as `notification.bark_device_key`. Recommended
> hardening when binding outside loopback:
>
> 1. Set `network_security.allowed_networks` in `config.toml` to the
>    minimal CIDR you actually trust (e.g. `["192.168.1.0/24"]`).
>    The default (`["127.0.0.0/8"]`) is loopback-only and is **not**
>    overridden by the `*_WEB_UI_HOST` env var — they're independent
>    layers.
> 2. Consider an `--ssh -L 18080:127.0.0.1:18080` SSH tunnel instead
>    of binding to `0.0.0.0` — it gives the same UX from your remote
>    machine without exposing the port at all.
> 3. The CLI `ai-intervention-agent --print-config` auto-redacts
>    secret-like keys, but the live HTTP API does not — secret
>    redaction at the API boundary is intentionally not enabled so
>    the settings panel can round-trip existing values.

#### Verifying the effective config

Two complementary observability surfaces tell the same story:

```bash
# Local CLI: dump merged config + active env overrides as JSON
ai-intervention-agent --print-config | jq

# Running process: same fields exposed by the health endpoint
curl -s http://127.0.0.1:8080/api/system/health | jq '{config_file_path, web_ui_env_overrides}'
```

Both routes deliberately omit the `network_security` section (sensitive)
and report **post-merge** values — i.e. what the process actually
bound to, not the raw `config.toml` contents. If the two views disagree
the CLI is the right answer for "next-restart behaviour" and the health
endpoint for "current process behaviour"; in steady state they match.

#### Other env vars (already documented elsewhere)

- `AI_INTERVENTION_AGENT_LOG_LEVEL` — overrides `web_ui.log_level` (standalone
  server only). VS Code extension users tune `ai-intervention-agent.logLevel`
  in VS Code settings instead.
- `AI_INTERVENTION_AGENT_OPEN_WITH` — picks the IDE used by the "Open config
  in IDE" action. See [`docs/troubleshooting.md`](troubleshooting.md).
- Discovery env vars (`AI_INTERVENTION_AGENT_CONFIG_FILE`, `*_DEV_MODE`,
  `*_USER_MODE`, `UVX_PROJECT`) — see the [lookup table](#config-file-location--lookup-order) above.

### Auto-migration

If a `config.jsonc` or `config.json` file is found via auto-discovery (not explicitly specified), it will be automatically migrated to `config.toml`:

- Original file is renamed to `config.jsonc.bak` / `config.json.bak`
- Comments are preserved using the TOML template structure
- `mdns.enabled: null` is converted to `mdns.enabled = "auto"`

### User config directory (by OS)

- Linux: `~/.config/ai-intervention-agent/`
- macOS: `~/Library/Application Support/ai-intervention-agent/`
- Windows: `%APPDATA%/ai-intervention-agent/`

> **macOS legacy `.config/` compatibility (R113)**
>
> If your macOS box also has `~/.config/ai-intervention-agent/config.toml` (left over from
> early versions, cross-platform dotfiles, or third-party scripts that hard-coded the XDG
> path), the agent will:
>
> 1. **Standard + legacy both present** → use the standard `~/Library/Application Support/...`
>    path and emit a `WARNING` log naming the legacy file with an `rm -rf` cleanup
>    suggestion.
> 2. **Legacy-only** → use the legacy path so your existing config is **never silently lost**,
>    and emit a strong `WARNING` with a copy-paste `mkdir -p / mv / rmdir` migration
>    script.
>
> Linux users are not affected — `~/.config/` is the XDG standard there and the check is
> macOS-specific.

## Backward compatibility

This project keeps compatibility with older config keys:

- **feedback**
  - `timeout` → `backend_max_wait`
  - `auto_resubmit_timeout` → `frontend_countdown`
- **web_ui**
  - `max_retries` → `http_max_retries`
  - `retry_delay` → `http_retry_delay`
- **network_security**
  - `enable_access_control` → `access_control_enabled`

Values are validated and clamped to safe ranges on load.

## Sections

### `notification`

Controls web/sound/system/Bark notifications.

| Key                       | Type    | Default                           | Notes                                                                                                            |
| ------------------------- | ------- | --------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `enabled`                 | boolean | `true`                            | Global switch                                                                                                    |
| `debug`                   | boolean | `false`                           | Notification-module-only log verbosity toggle (does not affect other logs)                                       |
| `web_enabled`             | boolean | `true`                            | Browser notifications                                                                                            |
| `auto_request_permission` | boolean | `true`                            | Auto request permission on page load                                                                             |
| `web_icon`                | string  | `"default"`                       | `"default"` or a custom icon URL                                                                                 |
| `web_timeout`             | number  | `5000`                            | Milliseconds, range `[1, 600000]`                                                                                |
| `system_enabled`          | boolean | `false`                           | Desktop notifications via `plyer` (optional dependency)                                                          |
| `macos_native_enabled`    | boolean | `true`                            | macOS native notifications (primarily used by the VS Code/Cursor extension)                                      |
| `sound_enabled`           | boolean | `true`                            | Sound notifications                                                                                              |
| `sound_mute`              | boolean | `false`                           | Mute sound                                                                                                       |
| `sound_file`              | string  | `"default"`                       | Sound file key/name used by the frontend (e.g. `"default"`, `"deng"`)                                            |
| `sound_volume`            | number  | `80`                              | Range `[0, 100]`                                                                                                 |
| `mobile_optimized`        | boolean | `true`                            | Mobile UI tweaks                                                                                                 |
| `mobile_vibrate`          | boolean | `true`                            | Vibration on mobile (requires user gesture in browsers)                                                          |
| `bark_enabled`            | boolean | `false`                           | Enable Bark push                                                                                                 |
| `bark_url`                | string  | `""`                              | Must start with `http://` or `https://`                                                                          |
| `bark_device_key`         | string  | `""`                              | Required when `bark_enabled=true`                                                                                |
| `bark_icon`               | string  | `""`                              | Optional                                                                                                         |
| `bark_action`             | string  | `"none"`                          | `none` / `url` / `copy`                                                                                          |
| `bark_url_template`       | string  | `"{base_url}/?task_id={task_id}"` | Used when `bark_action="url"` and no explicit event URL exists. Supports `{task_id}`, `{event_id}`, `{base_url}` |
| `retry_count`             | number  | `3`                               | Range `[0, 10]` (excluding the first attempt)                                                                    |
| `retry_delay`             | number  | `2`                               | Seconds, range `[0, 60]`                                                                                         |
| `bark_timeout`            | number  | `10`                              | Seconds, range `[1, 300]`                                                                                        |

### `web_ui`

Controls the Web UI server and HTTP client behavior.

| Key                    | Type    | Default     | Notes                                                                                                                                                                           |
| ---------------------- | ------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `language`             | string  | `"auto"`    | UI language. `"auto"` auto-detects (browser `navigator.language` / VS Code `vscode.env.language`); set explicitly to `"en"` or `"zh-CN"` to force a locale                      |
| `host`                 | string  | `127.0.0.1` | May be overridden by `network_security.bind_interface`                                                                                                                          |
| `port`                 | number  | `8080`      | Range `[1, 65535]`                                                                                                                                                              |
| `debug`                | boolean | `false`     | Debug mode                                                                                                                                                                      |
| `http_request_timeout` | number  | `30`        | Seconds, range `[1, 600]`                                                                                                                                                       |
| `http_max_retries`     | number  | `3`         | Range `[0, 20]`                                                                                                                                                                 |
| `http_retry_delay`     | number  | `1.0`       | Seconds, range `[0, 60]`                                                                                                                                                        |
| `log_level`            | string  | `"WARNING"` | Standalone-server enhanced_logging level. Case-insensitive; valid: `"DEBUG"` / `"INFO"` / `"WARNING"` / `"ERROR"` / `"CRITICAL"`. Override at runtime with env var `AI_INTERVENTION_AGENT_LOG_LEVEL` (env wins). VS Code extension users tune `ai-intervention-agent.logLevel` in VS Code settings instead (separate axis). |
| `external_base_url`    | string  | `""`        | Public Web UI base URL for notification click links, e.g. `http://ai.local:8080`. Empty falls back to mDNS (`http://ai.local:{port}`) when enabled, then `http://{host}:{port}` |

### `network_security`

Controls which interfaces the Web UI binds to and which networks can access it.

| Key                      | Type     | Default        | Notes                                                    |
| ------------------------ | -------- | -------------- | -------------------------------------------------------- |
| `bind_interface`         | string   | `0.0.0.0`      | `127.0.0.1` for local-only; `0.0.0.0` for all interfaces |
| `allowed_networks`       | string[] | (see template) | CIDR allowlist                                           |
| `blocked_ips`            | string[] | `[]`           | Explicit deny list                                       |
| `access_control_enabled` | boolean  | `true`         | Enable allow/deny checks                                 |

**Host selection rule**:

- Web UI host is effectively `network_security.bind_interface` (if present), otherwise `web_ui.host`.

### `mdns`

Used for `ai.local` access and LAN service discovery (DNS-SD / `_http._tcp.local`).

| Key            | Type             | Default                 | Notes                                                                |
| -------------- | ---------------- | ----------------------- | -------------------------------------------------------------------- |
| `enabled`      | boolean / string | `"auto"`                | `true` forces enable; `false` forces disable; `"auto"` = auto-detect |
| `hostname`     | string           | `ai.local`              | mDNS hostname (browser can access `http://ai.local:8080`)            |
| `service_name` | string           | `AI Intervention Agent` | DNS-SD instance name (shows up in service browsers)                  |

**Default enable rule**:

- Auto-enabled when the effective bind interface is not `127.0.0.1` / `localhost` / `::1`.

**IP auto-detection**:

- Prefers IPv4 addresses that look like physical interfaces and tries to avoid common container/VPN tunnel interfaces (e.g. `docker0`, `br-*`, `*tun*`, `tailscale*`).
- If you want to publish a specific IP, set `network_security.bind_interface` to that IP (instead of `0.0.0.0`).

**Conflict behavior**:

- If `hostname` conflicts, the server prints an error and suggests changing config, but **still starts** (you can still access via IP/localhost).

**Security note**:

- mDNS only helps with discovery/resolution; it does not bypass allow/deny access control.

### `feedback`

Controls timeouts and auto re-submit prompts.

| Key                  | Type   | Default                                     | Notes                                                                                                    |
| -------------------- | ------ | ------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `backend_max_wait`   | number | `600`                                       | Backend maximum wait (seconds), range `[10, 7200]`                                                       |
| `frontend_countdown` | number | `240`                                       | Frontend auto-submit countdown (seconds), range `[10, 3600]`; `0` (or any non-positive integer) disables |
| `resubmit_prompt`    | string | `"请立即调用 interactive_feedback 工具"`    | Returned on error/timeout to encourage re-calling the tool                                               |
| `prompt_suffix`      | string | `"\n请积极调用 interactive_feedback 工具"`  | Appended to the user feedback text. Leading `\n` is a TOML-escaped newline; copy-paste verbatim into `config.toml` (the TOML parser unescapes it back to a real newline at load time). |

**Timeout rule**:

If `frontend_countdown <= 0`:

`backend_wait = max(backend_max_wait, 260)`

Otherwise:

`backend_wait = min(max(frontend_countdown + 40, 260), backend_max_wait)`

## Minimal example

```toml
[web_ui]
port = 8080

[feedback]
frontend_countdown = 240
```
