# Troubleshooting

> 中文版：[`troubleshooting.zh-CN.md`](troubleshooting.zh-CN.md)

A focused FAQ for the most common deployment / runtime issues. If your
question is not here, [`SUPPORT.md`](../.github/SUPPORT.md) routes you to the
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
| **Bark** | Wrong device key, push server unreachable, or `bark_url` not pointing at your self-hosted instance | Test the URL with `curl -v "$BARK_URL/$DEVICE_KEY/test"`. Set `bark_action = "url"` + `bark_url_template = "{base_url}/?task_id={task_id}"` for a click-through deep link. **If the URL would resolve to a loopback address** (`localhost` / `127.x.x.x` / `::1`) the agent now suppresses it server-side — the phone never gets a useless click target — and the Web UI Bark settings panel surfaces a copy-pasteable LAN-IP suggestion (`http://<lan-ip>:<port>`). Apply that to `web_ui.external_base_url` (or expose mDNS) and re-trigger. |

## 5. mDNS (`ai.local`) does not resolve on the LAN

**Symptom**: phone / tablet on the same Wi-Fi cannot open
`http://ai.local:8080`, but `http://<laptop-IP>:8080` works.

**Causes**:

- **mDNS only publishes when bound to a non-loopback interface**.
  Set `network_security.bind_interface` to your LAN IP (e.g. `192.168.x.y`)
  or `0.0.0.0`, not `127.0.0.1`. (`bind_interface` lives under the
  `[network_security]` section, not `[web_ui]` — it overrides
  `web_ui.host` at runtime.)
- **macOS Sleep / Wi-Fi power-save** drops the Bonjour record after
  ~5 minutes of idle. Either pin caffeinate, or just refresh the
  page on the phone — re-resolution is usually instant.
- **Corporate / hotel Wi-Fi blocks multicast**. Switch to a personal
  hotspot or pre-share the IP-based URL via QR code (the settings
  page will print one once `web_ui.host = "0.0.0.0"`).

## 6. `Open in IDE` button does nothing / opens the wrong editor

**Symptom**: clicking "Open in IDE" on the settings page is silently
ignored.

**Why**: the endpoint enforces three guards (see `.github/SECURITY.md`):

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

## 8. Tapping a Bark notification on my phone opens the Bark app instead of the PWA

**Symptom**: you receive the Bark push, but tapping it lands on Bark's
home screen / "no URL configured" message instead of opening the
AI Intervention Agent feedback page.

**Cause** (almost always one of these two):

1. **The push payload had no `url` field** — the agent detected the
   resolved URL was a loopback address and stripped it (introduced in
   the `bark-r42` round). Loopback URLs cannot route from a phone back
   to your laptop's `localhost`; sending them would always fail.
2. **`bark_action` is set to a value other than `"url"`** — `bark_action
   = "default"` lets the user tap to dismiss; only `"url"` (or any
   absolute http/https URL) makes the Bark app deep-link.

**Fix**:

1. Open the Web UI (or VS Code extension) → **Settings → Notifications →
   Bark**. The new diagnostic panel under the URL template shows one of:
   - `OK: Click target = http://<your-lan-ip>:<port>` — everything is
     fine, retry from the AI client.
   - `Loopback detected — phones cannot reach <url>` + a one-click "Copy
     LAN URL" button. Click it, paste into `web_ui.external_base_url`,
     save, and retry.
   - `Cannot detect any LAN IP` — your machine is offline or only on a
     VPN that hides interfaces. Switch to LAN-bound Wi-Fi or use the
     mDNS `<host>.local` URL.
2. (Optional) Verify with `curl http://127.0.0.1:<port>/api/system/network-base-url-status`
   — the `recommendation` field tells you exactly which knob to turn:
   `ok` / `configure_external_base_url` / `bind_lan_interface`.

> Note: `0.0.0.0` is **not** a valid `external_base_url` — it's a wildcard
> bind on the server side, not a reachable address from the phone. The
> diagnostic panel rejects it with the same loopback warning.

## 9. CI Gate fails locally but passes in GitHub Actions (or vice versa)

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

## 10. `Dependency Review` GitHub check fails on every PR with "not supported on this repository"

**Symptom**: Every PR (including untouched dependabot PRs) reports
the `Dependency Review` workflow as failing, with the log line:

```
##[error]Dependency review is not supported on this repository.
Please ensure that Dependency graph is enabled, see
https://github.com/<owner>/<repo>/settings/security_analysis
```

The other CI checks (`Tests`, `VSCode`, `CodeQL`, `actionlint`) may
pass — only `Dependency Review` is red.

**Root cause**: GitHub's `actions/dependency-review-action` requires
the repository's **Dependency graph** feature to be enabled.
Dependency graph is enabled by default for **public** repos but
**disabled by default for private** repos and for forks. If you
recently switched the repo from private → public, or if you are
running the workflow on a fork, the feature may still be off.

**Fix** (one-time, repo owner only):

1. Go to `Settings` → `Code security` (or `Security & analysis`
   depending on the GitHub UI version).
2. Under **Dependency graph**, click **Enable**. This also unblocks
   `Dependabot alerts` and `Dependabot security updates` if you
   want those.
3. Re-run the failing `Dependency Review` job from the PR's
   "Checks" tab — it should now turn green within a minute.

**How to verify with the API** (without the UI):

```bash
gh api repos/<owner>/<repo>/vulnerability-alerts -i
# 204 No Content → vulnerability alerts (and dependency graph) ON
# 404 Not Found  → OFF — `Dependency Review` will keep failing
```

Until this is enabled, the `Dependency Review` red check is purely
infrastructural and **does not indicate** an actual vulnerability or
license violation in the PR's dependencies.

## Still stuck?

1. Read [`SUPPORT.md`](../.github/SUPPORT.md) for the right channel.
2. For security-related symptoms, **do not** open a public issue —
   follow [`SECURITY.md`](../.github/SECURITY.md).
3. Open a [GitHub Discussion][disc] if you are not sure whether it's
   a bug, configuration, or environment problem.

[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions
