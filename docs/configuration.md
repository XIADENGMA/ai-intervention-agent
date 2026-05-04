## Configuration

AI Intervention Agent uses a **TOML** config file to configure notifications, Web UI, security, and timeouts.

Default template: `config.toml.default`.

### Config file name

- Recommended: `config.toml`
- Backward compatible: `config.jsonc`, `config.json` (auto-migrated to TOML on first load)

### Config file location & lookup order

The lookup strategy depends on how you run the MCP server.

#### Override (all modes)

You can force a config path via environment variable:

- `AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/config.toml`
- `AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/dir/` (it will append `config.toml`)

#### uvx mode (recommended for end users)

- Uses **only** the user config directory.
- If the file does not exist, it will create it by copying the packaged `config.toml.default`.

#### Dev mode (running from the repo)

Priority order:

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

### Auto-migration

If a `config.jsonc` or `config.json` file is found via auto-discovery (not explicitly specified), it will be automatically migrated to `config.toml`:

- Original file is renamed to `config.jsonc.bak` / `config.json.bak`
- Comments are preserved using the TOML template structure
- `mdns.enabled: null` is converted to `mdns.enabled = "auto"`

### User config directory (by OS)

- Linux: `~/.config/ai-intervention-agent/`
- macOS: `~/Library/Application Support/ai-intervention-agent/`
- Windows: `%APPDATA%/ai-intervention-agent/`

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

| Key                       | Type    | Default  | Notes                                                                       |
| ------------------------- | ------- | -------- | --------------------------------------------------------------------------- |
| `enabled`                 | boolean | `true`   | Global switch                                                               |
| `web_enabled`             | boolean | `true`   | Browser notifications                                                       |
| `auto_request_permission` | boolean | `true`   | Auto request permission on page load                                        |
| `web_icon`                | string  | `"default"` | `"default"` or a custom icon URL                                         |
| `web_timeout`             | number  | `5000`   | Milliseconds, range `[1, 600000]`                                           |
| `system_enabled`          | boolean | `false`  | Desktop notifications via `plyer` (optional dependency)                     |
| `macos_native_enabled`    | boolean | `true`   | macOS native notifications (primarily used by the VS Code/Cursor extension) |
| `sound_enabled`           | boolean | `true`   | Sound notifications                                                         |
| `sound_mute`              | boolean | `false`  | Mute sound                                                                  |
| `sound_file`              | string  | `"default"` | Sound file key/name used by the frontend (e.g. `"default"`, `"deng"`)   |
| `sound_volume`            | number  | `80`     | Range `[0, 100]`                                                            |
| `mobile_optimized`        | boolean | `true`   | Mobile UI tweaks                                                            |
| `mobile_vibrate`          | boolean | `true`   | Vibration on mobile (requires user gesture in browsers)                     |
| `bark_enabled`            | boolean | `false`  | Enable Bark push                                                            |
| `bark_url`                | string  | `""`     | Must start with `http://` or `https://`                                     |
| `bark_device_key`         | string  | `""`     | Required when `bark_enabled=true`                                           |
| `bark_icon`               | string  | `""`     | Optional                                                                    |
| `bark_action`             | string  | `"none"` | `none` / `url` / `copy`                                                     |
| `bark_url_template`       | string  | `"{base_url}/?task_id={task_id}"` | Used when `bark_action="url"` and no explicit event URL exists. Supports `{task_id}`, `{event_id}`, `{base_url}` |
| `retry_count`             | number  | `3`      | Range `[0, 10]` (excluding the first attempt)                               |
| `retry_delay`             | number  | `2`      | Seconds, range `[0, 60]`                                                    |
| `bark_timeout`            | number  | `10`     | Seconds, range `[1, 300]`                                                   |

### `web_ui`

Controls the Web UI server and HTTP client behavior.

| Key                    | Type    | Default     | Notes                                                  |
| ---------------------- | ------- | ----------- | ------------------------------------------------------ |
| `host`                 | string  | `127.0.0.1` | May be overridden by `network_security.bind_interface` |
| `port`                 | number  | `8080`      | Range `[1, 65535]`                                     |
| `debug`                | boolean | `false`     | Debug mode                                             |
| `http_request_timeout` | number  | `30`        | Seconds, range `[1, 300]`                              |
| `http_max_retries`     | number  | `3`         | Range `[0, 10]`                                        |
| `http_retry_delay`     | number  | `1.0`       | Seconds, range `[0.1, 60.0]`                           |
| `external_base_url`    | string  | `""`        | Public Web UI base URL for notification click links, e.g. `http://ai.local:8080`. Empty falls back to `http://{host}:{port}` |

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

| Key            | Type             | Default                 | Notes                                                                   |
| -------------- | ---------------- | ----------------------- | ----------------------------------------------------------------------- |
| `enabled`      | boolean / string | `"auto"`                | `true` forces enable; `false` forces disable; `"auto"` = auto-detect   |
| `hostname`     | string           | `ai.local`              | mDNS hostname (browser can access `http://ai.local:8080`)               |
| `service_name` | string           | `AI Intervention Agent` | DNS-SD instance name (shows up in service browsers)                     |

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

| Key                  | Type   | Default                                     | Notes                                                                     |
| -------------------- | ------ | ------------------------------------------- | ------------------------------------------------------------------------- |
| `backend_max_wait`   | number | `600`                                       | Backend maximum wait (seconds), range `[60, 3600]`                        |
| `frontend_countdown` | number | `240`                                       | Frontend auto-submit countdown (seconds), range `[30, 250]`; `0` disables |
| `resubmit_prompt`    | string | `"请立即调用 interactive_feedback 工具"`    | Returned on error/timeout to encourage re-calling the tool                |
| `prompt_suffix`      | string | `"\\n请积极调用 interactive_feedback 工具"` | Appended to the user feedback text                                        |

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
