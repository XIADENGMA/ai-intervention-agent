## Configuration

AI Intervention Agent uses a **JSONC** config file (JSON with comments) to configure notifications, Web UI, security, and timeouts.

Default template: `config.jsonc.default`.

### Config file name

- Recommended: `config.jsonc`
- Backward compatible: `config.json`

### Config file location & lookup order

The lookup strategy depends on how you run the MCP server.

#### Override (all modes)

You can force a config path via environment variable:

- `AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/config.jsonc`
- `AI_INTERVENTION_AGENT_CONFIG_FILE=/path/to/dir/` (it will append `config.jsonc`)

#### uvx mode (recommended for end users)

- Uses **only** the user config directory.
- If the file does not exist, it will create it by copying the packaged `config.jsonc.default`.

#### Dev mode (running from the repo)

Priority order:

1. `./config.jsonc`
2. `./config.json` (backward compatible)
3. User config directory `config.jsonc`
4. User config directory `config.json` (backward compatible)
5. If none exist, it will create `config.jsonc` in the user config directory.

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

| Key | Type | Default | Notes |
| --- | ---- | ------- | ----- |
| `enabled` | boolean | `true` | Global switch |
| `web_enabled` | boolean | `true` | Browser notifications |
| `auto_request_permission` | boolean | `true` | Auto request permission on page load |
| `sound_enabled` | boolean | `true` | Sound notifications |
| `sound_mute` | boolean | `false` | Mute sound |
| `sound_volume` | number | `80` | Range `[0, 100]` |
| `mobile_optimized` | boolean | `true` | Mobile UI tweaks |
| `mobile_vibrate` | boolean | `true` | Vibration on mobile (requires user gesture in browsers) |
| `bark_enabled` | boolean | `false` | Enable Bark push |
| `bark_url` | string | `""` | Must start with `http://` or `https://` |
| `bark_device_key` | string | `""` | Required when `bark_enabled=true` |
| `bark_icon` | string | `""` | Optional |
| `bark_action` | string | `"none"` | `none` / `url` / `copy` |
| `retry_count` | number | `3` | Range `[0, 10]` (excluding the first attempt) |
| `retry_delay` | number | `2` | Seconds, range `[0, 60]` |
| `bark_timeout` | number | `10` | Seconds, range `[1, 300]` |

### `web_ui`

Controls the Web UI server and HTTP client behavior.

| Key | Type | Default | Notes |
| --- | ---- | ------- | ----- |
| `host` | string | `127.0.0.1` | May be overridden by `network_security.bind_interface` |
| `port` | number | `8080` | Range `[1, 65535]` |
| `debug` | boolean | `false` | Debug mode |
| `http_request_timeout` | number | `30` | Seconds, range `[1, 300]` |
| `http_max_retries` | number | `3` | Range `[0, 10]` |
| `http_retry_delay` | number | `1.0` | Seconds, range `[0.1, 60.0]` |

### `network_security`

Controls which interfaces the Web UI binds to and which networks can access it.

| Key | Type | Default | Notes |
| --- | ---- | ------- | ----- |
| `bind_interface` | string | `0.0.0.0` | `127.0.0.1` for local-only; `0.0.0.0` for all interfaces |
| `allowed_networks` | string[] | (see template) | CIDR allowlist |
| `blocked_ips` | string[] | `[]` | Explicit deny list |
| `access_control_enabled` | boolean | `true` | Enable allow/deny checks |

**Host selection rule**:

- Web UI host is effectively `network_security.bind_interface` (if present), otherwise `web_ui.host`.

### `mdns`

Used for `ai.local` access and LAN service discovery (DNS-SD / `_http._tcp.local`).

| Key | Type | Default | Notes |
| --- | ---- | ------- | ----- |
| `enabled` | boolean / null | `null` | `true` forces enable; `false` forces disable; `null`/missing = auto |
| `hostname` | string | `ai.local` | mDNS hostname (browser can access `http://ai.local:8080`) |
| `service_name` | string | `AI Intervention Agent` | DNS-SD instance name (shows up in service browsers) |

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

| Key | Type | Default | Notes |
| --- | ---- | ------- | ----- |
| `backend_max_wait` | number | `600` | Backend maximum wait (seconds), range `[60, 3600]` |
| `frontend_countdown` | number | `240` | Frontend auto-submit countdown (seconds), range `[30, 290]`; `0` disables |
| `resubmit_prompt` | string | `"请立即调用 interactive_feedback 工具"` | Returned on error/timeout to encourage re-calling the tool |
| `prompt_suffix` | string | `"\\n请积极调用 interactive_feedback 工具"` | Appended to the user feedback text |

**Timeout rule**:

`backend_wait = min(max(frontend_countdown + 60, 300), backend_max_wait)`

## Minimal example

```jsonc
{
  "web_ui": {
    "port": 8080
  },
  "feedback": {
    "frontend_countdown": 240
  }
}
```
