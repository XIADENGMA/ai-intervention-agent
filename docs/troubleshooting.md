# Troubleshooting

> 中文版：[`troubleshooting.zh-CN.md`](troubleshooting.zh-CN.md)

A focused FAQ for the most common deployment / runtime issues. If your
question is not here, [`SUPPORT.md`](../SUPPORT.md) routes you to the
right channel.

> Tip: most issues become diagnosable in seconds once you have logs.
> Set `web_ui.log_level = "DEBUG"` in `config.toml` (or
> `AI_INTERVENTION_AGENT_LOG_LEVEL=DEBUG` for the standalone server,
> or `ai-intervention-agent.logLevel` to `debug` in VS Code). Then
> reproduce and grab the **last 20-30 lines** of stderr / Output.

## 1. Web UI does not start (port already in use)

**Symptom**: MCP tool calls hang; VS Code Output shows
`Address already in use` or `Errno 48`; browser cannot reach
`http://127.0.0.1:8080`.

**Cause**: another process owns port `8080` (the default for
`web_ui.port`). Common culprits: a previous orphaned `ai-intervention-agent`
process, another local dev server, or a system service that grabbed
the port at boot.

**Fix**:

```bash
# 1. Find and kill any prior agent (macOS / Linux):
pkill -f ai-intervention-agent || true
lsof -nP -iTCP:8080 -sTCP:LISTEN  # confirm it's clear

# 2. Or change the port in config.toml:
# [web_ui]
# port = 8181

# 3. Restart your AI client (Cursor / VS Code) so the MCP process
#    re-resolves the new port.
```

If you change the port, also update `ai-intervention-agent.serverUrl`
in VS Code settings (e.g. `http://localhost:8181`).

## 2. VS Code panel is blank / shows "Loading..." forever

**Symptom**: the AI Intervention Agent activity bar icon opens an
empty / spinning panel.

**Common causes & fixes**:

- **Web UI is not reachable from VS Code** — confirm
  `ai-intervention-agent.serverUrl` matches the actual Web UI URL.
  Open it in a browser; if the browser fails too, see issue #1.
- **MCP server has not started yet** — call any MCP tool once
  (e.g. `interactive_feedback`) so the server can spawn the Web UI
  subprocess. The panel polls; once the URL is up, it renders within
  ~2 seconds.
- **Webview crashed silently** — Output → "AI Intervention Agent" should
  show a 5-line boot log (`webview.resolve`, `webview.boot`,
  `webview.ready`, `webview.config_loaded`,
  `webview.first_task_rendered`). If it stops mid-way, the line that
  fired last tells you the failing stage.
- **Network firewall** — corporate Zscaler / Endpoint Security
  occasionally blocks `localhost` requests from VS Code. Ask IT for
  an exception, or run with `web_ui.host = "0.0.0.0"` and use the
  LAN IP.

## 3. Task list is empty after the AI calls `interactive_feedback`

**Symptom**: the AI says "I'm waiting for your input" but the Web UI
does not show the task.

**Diagnostic order**:

1. **Refresh the page once** — if the task appears, your browser
   missed an SSE event during a network blip. Update to the latest
   release; v1.5.x ships [`Last-Event-ID`-based SSE replay][sse].
2. **Check that the MCP server and the Web UI agree on the task
   queue** — run `curl http://127.0.0.1:8080/api/tasks` and confirm
   the task is present server-side. If yes, the bug is in the
   browser; clear cache + hard reload.
3. **Look for `Web service already running on a different port`**
   in the MCP server log — the parent process found an old web UI
   on the configured port and skipped spawning a fresh one. Kill
   the orphan (issue #1) and retry.

[sse]: https://html.spec.whatwg.org/multipage/server-sent-events.html#concept-event-stream-last-event-id

## 4. No notifications arrive (Web / sound / system / Bark)

| Channel | Most common cause | Fix |
| --- | --- | --- |
| **Web** | Browser tab is in the background and OS denied permission | Click the bell icon on the page → "Allow notifications". On Safari, also enable in System Settings → Notifications → Safari. |
| **Sound** | `notifications.sound_mute = true` or volume = 0 | Settings page → Sound → toggle "Mute" off, raise volume. iOS / iPadOS require the page to be foregrounded once per session. |
| **System (plyer)** | macOS missing `pyobjus` (intentional skip) | macOS native notifications via plyer are intentionally skipped; the project relies on `macos_native_enabled = true` (`osascript`-based) instead. Linux requires `libnotify`; Windows uses Toast. |
| **Bark** | Wrong device key, push server unreachable, or `bark_url` not pointing at your self-hosted instance | Test the URL with `curl -v "$BARK_URL/$DEVICE_KEY/test"`. Set `bark_action = "url"` + `bark_url_template = "{base_url}/?task_id={task_id}"` for a click-through deep link. |

## 5. mDNS (`ai.local`) does not resolve on the LAN

**Symptom**: phone / tablet on the same Wi-Fi cannot open
`http://ai.local:8080`, but `http://<laptop-IP>:8080` works.

**Causes**:

- **mDNS only publishes when bound to a non-loopback interface**.
  Set `web_ui.bind_interface` to your LAN IP (e.g. `192.168.x.y`) or
  `0.0.0.0`, not `127.0.0.1`.
- **macOS Sleep / Wi-Fi power-save** drops the Bonjour record after
  ~5 minutes of idle. Either pin caffeinate, or just refresh the
  page on the phone — re-resolution is usually instant.
- **Corporate / hotel Wi-Fi blocks multicast**. Switch to a personal
  hotspot or pre-share the IP-based URL via QR code (the settings
  page will print one once `web_ui.host = "0.0.0.0"`).

## 6. `Open in IDE` button does nothing / opens the wrong editor

**Symptom**: clicking "Open in IDE" on the settings page is silently
ignored.

**Why**: the endpoint enforces three guards (see `SECURITY.md`):

1. **Loopback only** — non-loopback origins are 403'd.
2. **Path whitelist** — the only paths it will hand to a child
   process are the resolved active config file and `config.toml.default`.
3. **Editor priority**: `AI_INTERVENTION_AGENT_OPEN_WITH` env var →
   request body's `editor` field → auto-detect chain
   (cursor / code / windsurf / subl / webstorm / pycharm) → system
   default opener (`open` / `xdg-open` / `start`).

**Fix**:

```bash
# 1. Confirm an editor is on PATH:
which cursor code  # one of these should resolve

# 2. Force a specific editor:
export AI_INTERVENTION_AGENT_OPEN_WITH=cursor

# 3. Restart the MCP server so the env var is inherited.
```

## 7. PWA "Install" / "Add to Home Screen" prompt does not appear

**Symptom**: visiting the Web UI in Chrome / Edge / Safari does not
offer to install it as a Progressive Web App.

**Checklist**:

- The PWA install prompt requires **HTTPS or `localhost`**. LAN access
  via plain HTTP `http://192.168.x.y:8080` will never trigger it on
  modern browsers; iOS Safari is the most permissive but still wants
  the user to actively use "Add to Home Screen".
- Confirm the manifest is reachable: `curl http://127.0.0.1:8080/manifest.webmanifest`
  should return JSON with `start_url`, `icons`, and `display: standalone`.
- iOS users: `Share` → `Add to Home Screen` always works regardless
  of the install banner heuristics.

## 8. CI Gate fails locally but passes in GitHub Actions (or vice versa)

**Symptom**: `uv run python scripts/ci_gate.py` reports a failure
that does not reproduce in CI; or the opposite.

**Most common causes**:

- **uv lock drift** — your local `uv.lock` is older. `uv sync --all-groups`
  brings them aligned. CI uses `--frozen`; mismatch surfaces as
  `Locked dependency not found` or transitive version skew.
- **fnm vs system Node** — the i18n red-team smoke check runs Node.
  CI pins `v24`; locally `node --version` may differ. Use
  `fnm exec --using v24.14.0 -- npm run vscode:check` if `npm run`
  picks up the wrong Node.
- **timezone-sensitive tests** — `tests/test_i18n_relative_time_thresholds.py`
  computes "x minutes ago" in the local timezone. Run with
  `TZ=UTC uv run pytest tests/test_i18n_relative_time_thresholds.py`
  to bisect.

If none of the above explains it, capture the full output and open a
[bug report][bug] with the `[ci]` prefix.

[bug]: https://github.com/xiadengma/ai-intervention-agent/issues/new?template=bug_report.yml

## Still stuck?

1. Read [`SUPPORT.md`](../SUPPORT.md) for the right channel.
2. For security-related symptoms, **do not** open a public issue —
   follow [`SECURITY.md`](../SECURITY.md).
3. Open a [GitHub Discussion][disc] if you are not sure whether it's
   a bug, configuration, or environment problem.

[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions
