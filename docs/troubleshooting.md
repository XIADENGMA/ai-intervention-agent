# Troubleshooting

> 中文版：[`troubleshooting.zh-CN.md`](troubleshooting.zh-CN.md)

A focused FAQ for the most common deployment / runtime issues. If your
question is not here, [`SUPPORT.md`](../.github/SUPPORT.md) routes you to the
right channel.

> Tip: most issues become diagnosable in seconds once you have logs.
> Set `web_ui.log_level = "DEBUG"` in `config.toml` (or
> `AI_INTERVENTION_AGENT_LOG_LEVEL=DEBUG`, which wins over the file) and
> restart the MCP server, or set `ai-intervention-agent.logLevel` to
> `debug` in VS Code. Then reproduce and grab the **last 20-30 lines**
> of stderr / Output.

## 1. Web UI does not start (port already in use)

**Symptom**: the agent keeps getting the re-call prompt and no question
ever shows up (the tool returns within seconds instead of waiting for you);
the MCP log shows `端口 127.0.0.1:8080 已被占用（health-check 未识别为本服务）`
(error code `port_in_use`), or the Web UI log shows `Address already in use` /
`Errno 48`; the browser cannot reach `http://127.0.0.1:8080`.

**Cause**: another process owns port `8080` (the default for
`web_ui.port`). Common culprits: a previous orphaned `ai-intervention-agent`
process, another local dev server, or a system service that grabbed
the port at boot.

**Fix** (sorted from fastest to slowest):

```bash
# Option A — Temporary override (no file edits, IDE restart only)
#
# Lands the new port immediately the next time the MCP server starts.
# Survives the current shell session but resets on logout.
export AI_INTERVENTION_AGENT_WEB_UI_PORT=8181
# Restart your AI client (Cursor / VS Code) so the MCP process
# re-resolves the env var. See docs/configuration.md#environment-variable-overrides.

# Option B — Permanent change (edit config.toml)
#
# Locate the file with:
#   ai-intervention-agent --help  # version + bin path
#   uvx ai-intervention-agent     # then check banner: "config_file_path=..."
#
# Then edit:
#   [web_ui]
#   port = 8181

# Option C — Free the port instead of changing it
pkill -f ai-intervention-agent || true
lsof -nP -iTCP:8080 -sTCP:LISTEN  # confirm it's clear
```

If you change the port (Option A or B), also update
`ai-intervention-agent.serverUrl` in VS Code settings
(e.g. `http://localhost:8181`).

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
- **The panel's script did not start** — open Output → "AI Intervention
  Agent". A healthy panel logs `event=webview.ready` once its script is
  running. If the panel is visible and the script has not reported ready
  within 2.5 seconds, the extension logs `event=webview.ready_timeout` at
  `WARN`; its `reason` field says what started the timer (`shown` when the
  panel was hidden and shown again, `serverUrl_changed` after the server URL
  changed, no `reason` for the first load). A hidden panel does not warn, and
  the timer starts again when it is shown. The usual causes are a script the
  page blocked (CSP) or HTML that did not load; **Developer: Open Webview
  Developer Tools** shows the panel's console.
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

| Channel            | Most common cause                                                                                  | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ------------------ | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Web**            | Browser tab is in the background and OS denied permission                                          | Click the bell icon on the page → "Allow notifications". On Safari, also enable in System Settings → Notifications → Safari.                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **Sound**          | `notification.sound_mute = true` or volume = 0                                                    | Settings page → Sound → toggle "Mute" off, raise volume. iOS / iPadOS require the page to be foregrounded once per session.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **System (plyer)** | `system_enabled = false` (the default), or macOS missing `pyobjus` (intentional skip)              | Set `system_enabled = true` under `[notification]`. macOS native notifications via plyer are intentionally skipped; the project relies on `macos_native_enabled = true` (`osascript`-based) instead. Linux requires `libnotify`; Windows uses Toast.                                                                                                                                                                                                                                                                                           |
| **Bark**           | Wrong device key, push server unreachable, or `bark_url` not pointing at your self-hosted instance | Test the URL with `curl -v "$BARK_URL/$DEVICE_KEY/test"`. Set `bark_action = "url"` + `bark_url_template = "{base_url}/?task_id={task_id}"` for a click-through deep link. **If the URL would resolve to a loopback address** (`localhost` / `127.x.x.x` / `::1`) the agent now suppresses it server-side — the phone never gets a useless click target — and the Web UI Bark settings panel surfaces a copy-pasteable LAN-IP suggestion (`http://<lan-ip>:<port>`). Apply that to `web_ui.external_base_url` (or expose mDNS) and re-trigger. |

**Bark behind a proxy.** The Bark push goes straight to `bark_url`: it does not read `HTTP_PROXY`, `HTTPS_PROXY` or `ALL_PROXY` (in either case) or the proxy settings of the operating system, and there is no proxy option. So when `curl -v "$BARK_URL/$DEVICE_KEY/test"` works in a terminal that has the proxy variables set, but the push never arrives, the push is not going through the proxy. On a network that reaches the Internet only through a proxy, route the traffic below the application (a VPN or a TUN-mode proxy, or a transparent proxy), or point `bark_url` at a Bark server that your network reaches directly.

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
- The home-screen icon has a black border, or still shows the old
  picture after an update: iOS stores the icon at the moment the
  shortcut is created, so a shortcut made before the fix keeps the old
  one. Delete it and add the page again. To see what the server
  offers, run `curl -s http://127.0.0.1:8080/ | grep -A2 apple-touch-icon`
  and open the `/icons/apple-touch-icon.png?...` URL it prints: it
  must be a light square tile with no black frame.

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

## 11. Cursor shows "Extension host terminated unexpectedly 3 times within the last 5 minutes"

**Symptom**: Cursor surfaces a banner reading
`Extension host terminated unexpectedly 3 times within the last 5
minutes.` Sometimes the language drops to English even though you had
configured Chinese; sometimes the banner only appears while
`interactive_feedback` is mid-flight (waiting on a human reply).

**Important upstream context**: this is a **Cursor IDE-side known
issue**, not specifically caused by ai-intervention-agent. The
[Cursor community forum thread][cursor-ext-host] reports the same
banner appearing on Cursor 2.4.14 and earlier **even when every
extension is disabled**. The "language reset" symptom is also a Cursor
extension-host restart side effect (the language picker re-reads
defaults after the host respawns).

[cursor-ext-host]: https://forum.cursor.com/t/how-to-recover-from-extension-host-terminated-unexpectedly-3-times/148772

**Defensive measures already in this project (so the banner is unlikely
to come from ai-intervention-agent itself)**:

- The MCP `interactive_feedback` tool **ignores** any caller-supplied
  `timeout` / `timeout_seconds` argument, so it can never get stuck
  with a too-small timeout (`timeout=1` is the well-known mcp-feedback-
  enhanced regression and we are immune to it by design).
- `wait_for_task_completion` clamps backend timeout via
  `max(timeout, server_config.BACKEND_MIN=260)` and `calculate_backend_timeout`.
- `server.py::main()` runs the MCP loop under a 3-retry harness with
  `cleanup_services()` between attempts and `KeyboardInterrupt`-based
  graceful shutdown.
- R114 (notification manager) silences the benign atexit / shutdown
  TOCTOU race, so the noisy `ERROR: 处理通知事件失败` log lines no
  longer appear during host restart and can no longer be confused
  with a genuine MCP-side fault.

If the Cursor / VS Code main log shows `extensionHost crashed with code 9
and reason 'killed'` just before the banner, the host was ended from
outside with `SIGKILL`; see section 14 below for how to classify that
kill.

**Triage order**:

1. **Confirm it really is the MCP server.** In Cursor, open the MCP
   server panel (the one listing `ai-intervention-agent` and any
   other MCP servers); the connection light should be **green**. If
   it stays green throughout the banner, the crash is in some other
   Cursor extension and the workaround below applies regardless.
2. **Try Cursor's own recovery first.** `Cmd/Ctrl+Shift+P` →
   `Developer: Restart Extension Host`. If the banner stops repeating,
   the underlying state was transient.
3. **Update Cursor.** The forum thread tracks a stream of fixes in
   newer Cursor releases (post-2.4.14). Updating is the single highest-
   leverage action.
4. **Inspect the MCP server log** to rule out our side. With
   `web_ui.log_level = "DEBUG"`, look in stderr for either:
   - `处理通知事件失败` ERROR lines → if you see these on a current
     release (post-R114), please [open an issue][bug] with the line.
   - `[R114] _executor.submit 与 shutdown 竞态` DEBUG lines → these
     are **expected** during shutdown / restart and can be ignored;
     they are the post-R114 silenced form of the old ERROR.
5. **If the banner only fires while** `interactive_feedback` **is
   blocking on you**, you are seeing the long-poll (default
   `frontend_countdown=240s` + `BACKEND_BUFFER=40s` ≈ 280s wait)
   colliding with Cursor's extension-host watchdog. As of Cursor
   2.4.14 there is no documented public knob to extend that watchdog
   from the MCP server side, so the practical workaround is to keep
   the Web UI / VS Code panel foregrounded and reply within the
   countdown.

If after the above the banner still reproduces and the MCP log is
clean, please file the issue against
[Cursor's tracker][cursor-bugs] (with your `ai-intervention-agent`
version and the relevant `Help → Toggle Developer Tools → Console`
trace) and cross-link it from a [GitHub Discussion][disc] here so we
can mirror upstream progress.

[cursor-bugs]: https://forum.cursor.com/c/bug-report/6
[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions

## 12. Open VSX publish step fails (`displayName` mismatch / pinned `ovsx` upgrade)

**Symptom**

Release workflow's `open-vsx` job exits with one of:

```
ERROR: Display name in extension.vsixmanifest and package.json does not match.
ERROR: Description in extension.vsixmanifest and package.json does not match.
ERROR: Categories in extension.vsixmanifest and package.json do not match.
```

— typically _only_ the Open VSX job, with the same VSIX uploading
fine to the Microsoft VS Code Marketplace.

### Why this happens

`ovsx publish`'s server-side validator strict-checks that string
fields in `package.json` (after NLS placeholder resolution) literally
match the corresponding fields in the VSIX's `extension.vsixmanifest`.
NLS placeholders in `package.json` (e.g. `"%displayName%"`) are
**not** resolved by `ovsx`; they're forwarded as-is and compared
against the resolved manifest. The Microsoft Marketplace tolerates
this; Open VSX (since ~2026-05) does not.

This historically broke v1.6.1 — see
[`CHANGELOG.md`](../CHANGELOG.md#162--2026-05-10) — when the floating
`npx --yes ovsx publish` tag picked up a newly-strict version of
ovsx between v1.6.0 (2026-05-08, succeeded) and v1.6.1 (2026-05-10,
failed) without any code change on our side.

### Fix tier 1 — match content literally

Hard-code the affected field in `packages/vscode/package.json` to the
literal string instead of `"%placeholderKey%"`:

```diff
- "displayName": "%displayName%",
+ "displayName": "AI Intervention Agent",
```

The field is ASCII / Latin so the localised look-up was buying us
nothing; the other fields that _do_ differ across locales
(`activitybar.title`, `views.title`, `commands.title`) keep their
NLS placeholders because those are user-visible strings that benefit
from translation.

The drift guard
[`tests/test_vscode_displayname_literal_for_ovsx.py`](../tests/test_vscode_displayname_literal_for_ovsx.py)
locks `displayName` as a literal and demands the NLS bundles
agree, so a future regression fails CI rather than the next release.

### Fix tier 2 — pin the toolchain (R149)

Even with literal content, a future `ovsx` tightening could rebreak
us silently if we kept the floating tag. R149 pins both invocations
in `.github/workflows/release.yml`:

```yaml
- name: 发布到 Open VSX（从 VSIX 发布）
  run: |
    npx --yes ovsx@0.10.9 verify-pat xiadengma -p "$OVSX_TOKEN"
    npx --yes ovsx@0.10.9 publish -p "$OVSX_TOKEN" vsix/*.vsix
```

[`tests/test_release_workflow_ovsx_pinned_r149.py`](../tests/test_release_workflow_ovsx_pinned_r149.py)
rejects floating invocations and demands matching pins on both
lines.

### Upgrading the pinned `ovsx` version (manual ritual)

Toolchain upgrades are deliberately tracked PRs, not silent drift:

1. **Verify the new version against a dry VSIX first.**
   In a scratch directory:

   ```sh
   git clone --depth 1 https://github.com/xiadengma/ai-intervention-agent
   cd ai-intervention-agent/packages/vscode
   npm ci
   npm run build:vscode      # produces dist/vsix/*.vsix
   npx --yes ovsx@<new>.<x>.<y> verify-pat xiadengma -p "$YOUR_OVSX_PAT"
   ```

   If `verify-pat` succeeds, `ovsx@<new>.<x>.<y>` accepts the same
   PAT format. Move on.

2. **Bump `release.yml` in lockstep.** Edit both lines so the
   `ovsx@<X.Y.Z>` substring is identical. The matching-pins test
   (`test_publish_and_verify_use_same_pin`) catches a one-line
   bump.

3. **Re-run release on a sacrificial tag** (e.g. tag a
   `vX.Y.Z-rc1`, push it, watch the workflow). If the new ovsx
   accepts the existing VSIX, ship for real on the next PATCH /
   MINOR release. If it rejects, revert the pin to the previous
   working version and file an upstream issue against
   [`eclipse-openvsx/cli`](https://github.com/eclipse/openvsx/issues).

4. **Update the inline comment in `release.yml`** so future
   maintainers can see when each pin was last verified, e.g.

   ```yaml
   # R149 — pin ovsx version. Pinned to <new>.<x>.<y> on YYYY-MM-DD
   # after verifying <upstream changelog link>.
   ```

5. **Update this section** to mention the new version.

> **Note** — `npx --yes ovsx@latest` is **never** correct in a CI
> workflow even as a "temporary" measure. It re-creates the same
> drift that broke v1.6.1. If a release is blocked because the
> currently-pinned ovsx has a known bug, revert to the _previous_
> known-working pin (find it in `git log` for `release.yml`) rather
> than going floating.

## 13. Backend `/api/system/*` payload field stability (R154 lesson, post-feat-remove-test)

> **Status note (feat-remove-test)** — The original UI consumers of
> these endpoints (settings page's "Send system self-test" button +
> "Activity dashboard" panel) were **removed**. The R154 client-side
> JS contract (`activity_dashboard.js`) and the in-suite
> `test_system_endpoint_payload_contract_r154.py` were pruned in the
> same cycle. **The lesson is still relevant** — just retargeted at
> remaining backend consumers (CI smoke tests, Prometheus exporter,
> k8s liveness probes, ad-hoc `curl` debugging) rather than in-app UI
> indicators.

**Symptom** — A monitoring dashboard row, CI assertion, or `curl | jq`
pipeline silently shows "stale" / "—" / missing fields even though the
endpoint returns 200 with a JSON body.

- `curl /api/system/recent-logs | jq '.entries | length'` returns
  `null` (was reading `.logs`).
- `curl /api/system/health | jq '.checks.notification.status'` returns
  `undefined` (field renamed under the hood).
- Prometheus exporter shows no per-provider streak metrics even
  though the JSON contains them.

**Root cause** — The server endpoint renamed a top-level JSON field
(e.g. `entries → logs`, `stats → counters`) **or** the consumer reads
under a different name than the server emits. The fetch succeeds, the
JSON parses, but the consumer reads `undefined` and treats it as "no
data".

R152's `_formatLogs` shipped with `var entries = logs.logs` while the
server has always shipped `entries`; the bug persisted until R153
caught it. The class of bug doesn't go away just because the UI
consumer did — every off-process consumer has the same brittleness.

**What to do if you suspect drift**

1. **Inspect the live payload** with
   `curl -s http://localhost:8080/api/system/<endpoint> | jq` and
   compare its top-level keys to whatever your consumer is reading
   (CI test, monitoring scrape config, Grafana dashboard JSON).
2. **Diff against `_get_template_context` history**: the affected
   route view function (in `web_ui_routes/system.py` /
   `web_ui_routes/notification.py`) commits often label field renames
   in their messages — `git log --follow -p` on the view function
   surfaces the change.
3. **Pin the field structurally** in your own consumer-side test
   suite (CI smoke / monitoring config schema test) so a future
   server-side rename trips your tests first.

**Prevention going forward** — Treat every endpoint's top-level field
name as part of the **public** API contract — even with no in-app UI
consumer, off-process consumers depend on it. Renames must:

- update inline route docstring (so `docs/api*/` regen catches it);
- bump a documented API version note if the rename is breaking;
- ideally land alongside a deprecation alias period.

Don't ship a "no UI consumer left, so I can rename freely" PR — the
absence of an in-app consumer makes silent regressions **harder**, not
easier, to notice. UI dashboard rows go to "—" loudly; a CI scrape
job goes to "0 metrics" silently.

## 14. The log says `extensionHost crashed with code 9 and reason 'killed'`

**Symptom**: the Cursor / VS Code main log contains a pair of lines like

```log
[error] [UtilityProcess id: 20, type: extensionHost, pid: 65757]: crashed with code 9 and reason 'killed'
[info] Extension host with pid 65756 exited with code: 9, signal: unknown.
```

and every extension (this one included) restarts, with no error message of its own beforehand.

**What it means**: exit code 9 is `SIGKILL`. The extension host did not fail on its own; something outside it ended the process. The usual senders on macOS are the memory-pressure killer ("jetsam"), the kernel killing a process that ran out of Mach ports (a [known macOS 26 + VS Code / Electron failure class][vscode-326338]: a spawn storm, then `spawn EBADF` / `EMFILE`, then the renderer or the extension host is killed), or another tool running `kill -9`. This extension cannot produce it: nothing in it signals its host, and its host-side resource behaviour is tested inside a real VS Code extension host (R718: bounded SSE buffer, reconnect backoff, released HTTP bodies, and no leaked sockets or heap under flapping / event-storm / error-body fault injection).

[vscode-326338]: https://github.com/microsoft/vscode/issues/326338

**Triage (macOS, right after it happens)**:

1. Classify the kill. Use the full path, because a bare `log` is a zsh builtin:

   ```bash
   /usr/bin/log show --last 30m \
     --predicate 'eventMessage CONTAINS "FATAL exception" OR eventMessage CONTAINS "exiting with signal 9"' \
     | grep -iE "code helper|cursor helper"
   ls -lt /Library/Logs/DiagnosticReports/JetsamEvent-*.ips | head
   ```

   - A `JetsamEvent` close to the crash time whose largest processes are *not* the editor means system-wide memory pressure; close the heavy apps or VMs it lists.
   - A `FATAL exception ... EXC_RESOURCE` line, or `spawn EBADF` / `EMFILE` lines in the Extension Host output shortly before the crash, mean resource exhaustion. In the upstream report the trigger was a custom `files.watcherExclude` that *replaced* the VS Code defaults (so `node_modules` was watched and the built-in Git extension spawned a child process per nested repository). Make it add to the defaults, and consider `git.autofetch = false` and `git.autoRepositoryDetection = "openEditors"`.
   - Every Cursor / VS Code process (renderer, file watcher, pty host) dying with code 9 at the same instant also points at system memory pressure rather than at one extension.
2. Update Cursor / VS Code, then retry with `cursor --disable-extensions`. If the kill still happens with every extension disabled, it is not this extension.
3. Rule this extension out from its own log: open **Output → AI Intervention Agent**. A `sse.buffer_overflow` warning means the server sent a single SSE line or event larger than 1 MiB; the connection is dropped and re-opened with backoff on purpose.

If it still reproduces, open an [issue][bug] with the crash timestamp, the `JetsamEvent` / `FATAL exception` lines from step 1 and the **AI Intervention Agent** output.

## 15. The sidebar panel is slow to appear or to reload

**Symptom**: after Cursor / VS Code starts, or when you switch back to the AI Intervention Agent sidebar, the panel stays empty or on its loading skeleton for a noticeable time; or a prompt with long code blocks takes a moment to show up.

**What takes how long** (measured in a real VS Code 1.110.0 extension host and, read-only, in a live Cursor session; medians of warm runs on an Apple-silicon Mac):

- **The editor creating the webview (cold start only): about 1 s in the Cursor session that was measured.** The editor builds the webview frame and registers its service worker before it requests the extension's page, so none of the extension's code has run yet and nothing in the extension can shorten it.
- **The extension's own work, from setting the HTML to content on screen: about 60 ms in VS Code 1.110 and about 90 ms in Cursor.** The page is 59 KB and loads its scripts synchronously from local files.
- **Hiding and re-showing the sidebar: about 55 ms to restore the content.** By default the webview is re-created from the state the page saved with `setState`. `ai-intervention-agent.webview.retainContextWhenHidden` keeps it alive instead (about 25 ms) at the price of more memory; it is off by default on purpose (R452).
- **A prompt with long code blocks: about 110 ms for the first render of a 52 KB prompt with 12 000 highlighted tokens (259 ms before R719).** The server highlights the code (about 70 ms on the first request for a prompt that size, cached afterwards).

**Triage**:

1. Open **Output → AI Intervention Agent** and compare the `event=webview.ready` timestamp with the moment you opened the panel. A gap there is the editor creating the webview, not the extension.
2. Run **Developer: Open Webview Developer Tools** and look at the console. An ordinary prompt must not print `Refused to apply inline style because it violates the following Content Security Policy directive`: each of those is a violation event the browser has to create, and R719 keeps the extension's own markup free of them. If you see many, open an issue and describe the prompt.
3. To get numbers instead of impressions, start the editor with the probe on, hide and show the sidebar a few times, then summarize the file from a checkout of this repository:

   ```bash
   AIIA_WEBVIEW_BENCH_OUTPUT=/tmp/aiia-webview.ndjson cursor .
   npm run vscode:webview-bench -- --input /tmp/aiia-webview.ndjson
   ```

4. If only long prompts are slow, time the request the panel makes for the active task (the server renders and caches the Markdown): `curl -s -o /dev/null -w '%{time_total}\n' http://localhost:8081/api/config`.

If it still feels slow, open an [issue][bug] with the probe summary, the editor and its version, and whether the first open after startup or every re-show is slow.

## 16. Cursor marks the server "Needs Authentication" or lists an `mcp_auth` tool

**Symptom**: in Cursor's MCP list this server shows **Needs Authentication**, or the tool list an agent receives for it contains an extra `mcp_auth` tool ("Authenticate this MCP server so its tools can be used").

**What it means**: this server never asks for authentication. It runs as a local stdio process (`uvx ai-intervention-agent`), so nothing is signed in between Cursor and it, and its entry in `~/.cursor/mcp.json` needs no `headers`, `auth` or token. The Web UI has no sign-in page either. Both signs come from Cursor, which treats every MCP server alike (behaviour read from Cursor 3.26):

- Cursor adds a virtual `mcp_auth` tool to the lists it builds for agents. The server does not define it and cannot switch it off. An agent should call it only for a server that is marked as needing authentication.
- Cursor marks a server as needing authentication when a request to it fails with an error whose text contains `unauthorized` or the number `401`. This is a plain text match and it applies to stdio servers too, so a message relayed from something else (for example another program that already owns the Web UI port and answers `401`) can trigger it.

**Triage**:

1. Open **Output → MCP Logs**, or on macOS the file `~/Library/Application Support/Cursor/logs/<session>/mcp-server-user-<name>.log` (`<name>` is the key in `mcp.json`, for example `ai-intervention-agent`), and search for `401` or `unauthorized` around the time the label appeared. The line names the call that failed.
2. If another program answers on the Web UI port, free the port or change `web_ui.port` (section 1).
3. Run **Developer: Reload Window**, or switch the server off and on again in Cursor's MCP settings, to reconnect it. The label also clears by itself once a later tool call gets an answer; if it keeps coming back, the line from step 1 is the cause.

The access-denied message in the Web UI is a different thing: it means the server, or a proxy in front of it, answered the page with 401 or 403. Check `network_security.allowed_networks` and `blocked_ips` in `config.toml`.

## 17. A local image in the prompt is replaced by an "image not shown" note, or shows as broken

**Symptom**: the agent put `![shot](path/to/shot.png)` in its message, but the feedback page shows a one-line note such as 🖼️ *(image not shown: outside the allowed folders)* instead of the picture, or a broken-image icon.

**How it works**: the MCP server runs next to the files, so it reads the image and sends the bytes with the task; the Web UI never opens a path by itself. A reference that cannot be shown is replaced by a note that says why:

- `outside the allowed folders`: the file is not under a folder the MCP client reports as its workspace, the system temp directory, or a folder listed in `[feedback] local_image_dirs`. Move or copy it into the workspace, or add its folder to the list. `..` and symlinks that lead out of an allowed folder count as outside.
- `file not found`: the path does not exist. Relative paths are resolved against the workspace folders; `~` is your home directory.
- `not a png, jpg, gif, webp, bmp or avif image`: SVG, ICO, HEIC and similar formats are refused, and so is a file whose first bytes do not match its extension.
- `too large (max 8 MB each, 16 MB per prompt)`, `more than 8 images in one prompt`, `cannot be read`: the limits and permissions described in [`configuration.md`](configuration.md).

**A broken-image icon without a note** means the reference never went through the MCP server:

- `local_image_dirs = []` turns the feature off, so references stay as written.
- The destination is a remote (`https:`) or `data:` URL: these are left alone and the browser loads them itself. The Web UI's content security policy only allows images from its own server and `data:` / `blob:`, so a remote image is blocked there.
- The Web UI was restarted: images are kept in memory only, so a task restored after a restart shows its images as missing. Ask the agent to call the tool again.
- The reference is inside a code block or inline code, which is never treated as an image.

**Triage**:

1. Open the MCP server log and look for `本地图片`: `任务 <task_id> 的本地图片: 已附带 N 张，跳过 M 张` says how many images were attached and how many were skipped; at debug level each skipped reference is listed with its reason.
2. Ask the Web UI whether it holds the image (task ids are listed by `/api/tasks`): `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/tasks/<task_id>/images/0` prints `200` when image 0 is stored and `404` when it is not.
3. If the MCP client does not report workspace folders, the server falls back to its working directory, which is not used when it is `/` or your home directory (common for a server started by an editor). List the workspace explicitly, for example `local_image_dirs = ["auto", "~/work"]`.

## 18. Every start of the MCP server logs a `WARNING` line, `event=server.boot`

**Symptom**: the MCP log has one line like this at every start, with the level `WARNING`:

```text
2026-10-20 20:11:15,910 - ai_intervention_agent.server - WARNING - event=server.boot version=1.8.12 transport=stdio mcp_name='AI Intervention Agent MCP' python=3.11.15 middleware=ErrorHandlingMiddleware,...
```

**What it means**: nothing is wrong. It is the start-up banner: the version, the transport, the Python version and the middleware stack that answered. It is written at `WARNING` on purpose. The MCP server logs at `WARNING` unless you change `web_ui.log_level` (or `AI_INTERVENTION_AGENT_LOG_LEVEL`) and restart it, so a banner written at `INFO` would be dropped, and it is the one line that says which build is running.

- It appears once per process start. Several of them close together mean the MCP client started the server several times; the lines before each one say why.
- Include it when you report a problem: it names the version.
- `web_ui.log_level = "ERROR"` hides it together with every other warning.

## 19. A button in the Web UI does nothing, and the browser shows `403 cross_origin_write_blocked`

**Symptom**: the Web UI loads, but submitting an answer, closing a task or saving a setting fails. In the browser's network panel the `POST` answers `403` with `{"success": false, "error": "cross_origin_write_blocked", ...}`, and the Web UI log has a warning that starts with `拒绝跨源写请求` and shows the request's `Origin`, `Host` and `Sec-Fetch-Site`. It only happens when you open the Web UI through a reverse proxy, a tunnel or a custom host name; `http://127.0.0.1:<port>`, `http://localhost:<port>` and the machine's own LAN address are not affected.

**What it means**: a request that changes state (every `POST` / `PUT` / `PATCH` / `DELETE`, plus `GET /api/feedback`, which reads and clears the stored answer) is refused when the browser says another page caused it. Without that, any web page open in your browser could answer the agent's question as you, close tasks or shut the Web UI down. A request passes when the browser reports `Sec-Fetch-Site: same-origin`, when it carries neither `Origin` nor `Sec-Fetch-Site` (the MCP server, `curl`, scripts and the VS Code extension are not browsers), or when its `Origin` is the Web UI's own: the same host and port as the `Host` header, `localhost` / `127.0.0.1` on the Web UI's port, the VS Code webview, or `web_ui.external_base_url`. A plain-HTTP proxy that rewrites `Host` (nginx's default) defeats the first and the last: a browser sends no `Sec-Fetch-Site` to a plain-HTTP address, and the `Origin` (`http://agent.example.com`) no longer equals the rewritten `Host` (`127.0.0.1:8080`).

**Fix** (either one):

1. Set `web_ui.external_base_url` to the address you type in the browser, for example `http://agent.example.com`, and restart the MCP server. The Web UI then treats that origin as its own.
2. Let the proxy pass the original `Host` on (nginx: `proxy_set_header Host $http_host;`) and add that name to `network_security.trusted_hosts`. The `Origin` then equals `Host`.

Over HTTPS, a browser that sends `Sec-Fetch-Site` (Chrome 76, Firefox 90, Safari 16.4 and later) says `same-origin`, so an HTTPS proxy needs neither. If the log shows a request you did not make, with an `Origin` of a site you do not recognise, that is the protection working: close that page.

## 20. A call ends with `MCP error -32001: Request timed out` after about two minutes

**Symptom**: the agent calls `interactive_feedback` and, about 120 seconds later, the tool result (or Cursor's MCP log) says `MCP error -32001: Request timed out`. The question was still on the page, or had already gone from it, and an answer you typed afterwards never reached the agent.

**What it means**: the client gave up on a call that had been silent for too long. Waiting for a person is slow, and a client puts an idle timeout on every tool call (Cursor 3.27: 120 seconds). While it waits, the server sends a progress notification every 20 seconds (`progress` is the number of seconds waited, the message reads `Waiting for human feedback (N s)`). A client that restarts its idle timer on progress, as Cursor does, then keeps waiting until the call ends: when you answer, when an open panel's countdown submits (`frontend_countdown`), or when the server's own limit is reached and it returns the resubmit prompt (`frontend_countdown` + 40 seconds, at least 260, at most `backend_max_wait`).

- Versions up to 1.8.12 send nothing while they wait. Update to a newer release and restart the MCP server.
- A client that does not ask for progress (it sends no progress token) gets none and keeps its own idle timeout. Raise that timeout in the client if it has such a setting, or lower `frontend_countdown` so that an open panel answers before it.
- When no panel or browser tab shows the question, nothing counts down, so the call ends at the server's limit; the agent then calls the tool again.

**Triage**:

1. Find the failure in the MCP log (section 16 says where) and note the time. Set `web_ui.log_level = "INFO"` and restart the server, then look for `等待任务完成:` in its log: the line names the task and the limit (`超时: 260秒`). A failure about 120 seconds after the call, with a larger limit in that line, is the client's idle timeout.
2. At `DEBUG` level, `progress keepalive failed (ignored)` marks a notification that could not be sent, which means the client was not reading its end of the connection.

## 21. The Web UI page stops answering while a question is waiting, and the MCP log says `Web UI 没有响应`

**Symptom**: the page that shows the question loses its connection or will not load (`ERR_CONNECTION_REFUSED`), and about ten seconds later with the default settings (a little more when the restart itself is slow) it answers again with the question still on it. The log of one MCP server has a `WARNING` line like this:

```text
Web UI 没有响应（连续 3 次连接被拒绝），任务 <task_id> 仍在等待，正在重新启动（第 1/3 次）
```

**What it means**: the Web UI process was stopped while a call was waiting for it. The usual reason is two editor windows that share one Web UI (the same `web_ui.port`): the MCP server that started it belongs to the window that was just closed, and a server stops the Web UI it started when it exits. A `kill` or a crash of the Web UI does the same. A window that is still waiting sees three refused polls in a row, starts the Web UI again (at most three attempts per outage, three polls apart) and goes on waiting. The new process restores the task list from its snapshot, `data/tasks-<port>.json` in the package folder (one file per `web_ui.port`, so Web UIs on different ports never see each other's questions), so the question comes back with its countdown as it was, including a time extension or a "no timeout" you set; a question that the closed window left behind comes back as well, and stays until it is answered, closed or counted down.

- If the restart fails, the log then shows `重新启动 Web UI 失败` with the reason. A port that another program holds is the common one: see section 1. The call keeps waiting until its limit and then returns the resubmit prompt; the agent calls the tool again, and that call tries to start the Web UI once more.
- Only a refused connection counts. A Web UI that is alive but slow, or that answers with an error, is left alone.
- Nothing needs doing in the normal case: reload the page once it answers.

**Triage**:

1. In the log of the window that was still waiting, look for `Web UI 没有响应` followed by `Web服务已启动`. The first line names the task and the attempt. When another window got there first, the second line is missing from this log and the page simply answers again.
2. If the page stays down and the second line never comes, read the reason in `重新启动 Web UI 失败`, then see which process holds the port: `lsof -nP -iTCP:8080 -sTCP:LISTEN` (use your `web_ui.port`).

## Still stuck?

1. Read [`SUPPORT.md`](../.github/SUPPORT.md) for the right channel.
2. For security-related symptoms, **do not** open a public issue —
   follow [`SECURITY.md`](../.github/SECURITY.md).
3. Open a [GitHub Discussion][disc] if you are not sure whether it's
   a bug, configuration, or environment problem.

[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions
