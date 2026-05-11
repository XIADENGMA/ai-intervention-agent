# AI Intervention Agent · VS Code extension changelog

This file is rendered on the **Changelog** tab of the VS Code
Marketplace and Open VSX listing pages. It captures only the
extension-relevant changes; for the complete project history (PyPI
package, MCP server, Web UI internals), see the
[root `CHANGELOG.md`][root-changelog] on GitHub.

> 中文用户请阅读 [`README.zh-CN.md`](README.zh-CN.md)。版本号与 PyPI
> 包同步发布；扩展自身仅依赖 TypeScript dev-dependency，运行时不
> 引入第三方 npm 包。

[root-changelog]: https://github.com/xiadengma/ai-intervention-agent/blob/main/CHANGELOG.md

## [Unreleased]

## [1.6.0] — 2026-05-08

> Server-side cleanup + repo-shape release; no extension-facing
> behaviour changes. Bumped to keep the VS Code extension version
> in lockstep with the PyPI server package. Server-side closed 16
> CodeQL alerts via a global `enhanced_logging` root
> `InterceptHandler` (R72) plus 1 stack-trace exposure fix in
> `web_ui_routes/system.py` (R72-B), relocated 4 governance docs
> into `.github/` (R73), cleared a small zero-warning sprint of
> `ty` / prettier / `ruff LOG` diagnostics (R74 / R74b / R74c /
> R74d / R75), adopted the PyPA `src/` layout with
> `src/ai_intervention_agent/` as the single source root and
> dropped the deprecated `config.jsonc.default` template
> (R76 / R76b), expanded `interactive_feedback`'s MCP signature
> with cross-tool compat aliases `timeout_seconds` and `task_id`
> for older client variants (R77), drove
> `web_ui_routes/system.py` and `i18n.py` test coverage above
> 84% / 98% (R78 / R79), shipped a markdown link-rot regression
> guard plus 14 broken-link fixes inside `.github/` (R80),
> backfilled the `[Unreleased]` section in the project changelog
> for the R72 → R80 batch (R80b), and consolidated the cycle's
> lessons in `docs/lessons-learned-silent-decay.md` (R81). The VS Code
> webview HTML, settings UI, status-bar logic, OAuth flow, and
> `webview-settings-ui.js` are unchanged. `package.json` /
> `package-lock.json` bumped to `1.6.0` for store sync only.

## [1.5.45] — 2026-05-08

> Server-side observability + safety release; no extension-facing
> behaviour changes. Bumped to keep the VS Code extension version in
> lockstep with the PyPI server package. Server-side now exposes
> ``X-RateLimit-*`` headers on rate-limited API responses so SDK
> clients (incl. this extension's status-bar polling loop) can
> observe their budget proactively (R57); and ``_SSEBus.emit`` now
> drops oversize (>256 KB) payloads in favour of a metadata
> ``oversize_drop`` event to prevent N×fan-out memory blowups (R58).
> Both transparent to the extension UI.

## [1.5.44] — 2026-05-08

> Server-side performance release; no extension-facing behaviour
> changes. Bumped to keep the VS Code extension version in lockstep
> with the PyPI server package. Server-side aligns static-asset
> Cache-Control across the hook and route handlers, fixing a silent
> docstring drift on JS/CSS and a 24× over-fetch on i18n locale JSON
> (R56). Transparent to the extension UI.

## [1.5.43] — 2026-05-08

> Server-side observability release; no extension-facing behaviour
> changes. Bumped to keep the VS Code extension version in lockstep
> with the PyPI server package. Server-side aggregates `recent_logs`
> across the MCP host and Web UI subprocess, exposing both sources in
> the `aiia://server/info` resource through a 1.0 s TTL cross-process
> cache (R55). Transparent to the extension UI.

## [1.5.42] — 2026-05-08

> Server-side hardening release; no extension-facing behaviour
> changes. Bumped to keep the VS Code extension version in lockstep
> with the PyPI server package. Server-side adds a 1.0 s TTL cache
> around the cross-process sse-stats fetch (R54-A) and a major log
> sanitizer expansion that fixes a silent OpenAI / Anthropic key
> leak (R54-B). Both transparent to the extension UI.

## [1.5.41] — 2026-05-08

> Server-side hardening release; no extension-facing behaviour
> changes. Bumped to keep the VS Code extension version in lockstep
> with the PyPI server package. Server-side adds a hard 10 MB cap
> on `add_task` prompts (R53-A) and a new `GET /api/system/health`
> endpoint (R53-F) — both transparent to the extension UI.

## [1.5.40] — 2026-05-08

> Server-side hardening release; no extension-facing behaviour
> changes. Bumped to keep the VS Code extension version in lockstep
> with the PyPI server package.

## [1.5.39] — 2026-05-08

### Added

- **R51-B** — Server SSE keep-alive is now a proper named event
  (`event: heartbeat\ndata: {ts_unix}`) instead of an invisible SSE
  comment. The extension registers an `evType === 'heartbeat'` branch
  that emits a debug-level `sse.heartbeat` log entry — useful for
  diagnosing long-lived connection stalls without affecting the status
  bar at all. Existing connections that don't care about heartbeat
  continue to work because the SSE spec drops unhandled named events
  silently.

## [1.5.38] — 2026-05-08

### Added

- **R48** — Status-bar hint when the server-side configuration file
  changes. The extension now listens for the new `config_changed`
  Server-Sent Event and surfaces it via
  `vscode.window.setStatusBarMessage` (6 seconds, non-blocking). No
  modal popup, no extra polling — you simply see "configuration file
  changed" in the bottom bar when the agent's TOML edits land.

### Changed

- **R49** — Tightened the VSIX size budget from `4 / 6` MB
  (review / hard-limit) to `3 / 5` MB. Current builds are ~2.6 MB so
  this change is invisible to end users; it just makes future bloat
  regressions visible in PR review instead of hiding behind the lax
  4 MB threshold.

## [1.5.37] — 2026-05-08

### Fixed

- **R41** — Settings-panel "GitHub" / "PWA" / docs links now actually open in
  an external browser. They previously did nothing because the click was
  intercepted by the Webview but never sent back to the extension host. The
  Webview now posts an `openExternal` message to `webview.ts` for every
  `target="_blank"` anchor, and the extension forwards it through
  `vscode.env.openExternal` (the same path the status-bar tooltip already used).

## [1.5.36] — 2026-05-06

### Changed

- Reduced redundant status bar work during task polling by avoiding a second
  presentation write when the same response has already applied the changed
  connected/active/pending state.
- Updated the VSIX packaging success summary to use neutral threshold labels,
  keeping healthy package logs free of warning-like wording while preserving the
  existing size-budget guard.

## [1.5.23] — 2026-05-04

### Fixed

- **Webview "frontend countdown" input no longer caps at 250s.**
  The settings panel's `<input type="number" id="feedbackCountdown"
  max="250">` and the `webview-settings-ui.js` save guard
  (`v >= 0 && v <= 250`) silently rejected any user-typed value
  above 250 — even though the backend has supported `[10, 3600]s`
  for several minor releases. Both surfaces are now widened to
  `max="3600"` / `v <= 3600`, matching `AUTO_RESUBMIT_TIMEOUT_MAX`
  on the server. The `<input value="240">` placeholder and the
  bilingual `countdownHint` strings ("Range 10-3600 seconds" /
  "范围 10-3600 秒") were updated in the same wave. Locked by
  `tests/test_frontend_input_range_parity.py`.

### Documentation

- Removed phantom `ai-intervention-agent.enableAppleScript` setting
  reference from this README. The configuration key has not been
  declared in `package.json::contributes.configuration` for several
  minor releases (the AppleScript path is gated by the macOS native
  notification toggle inside the panel UI).
- Documented the experimental
  `ai-intervention-agent.i18n.pseudoLocale` setting for the first
  time. Flag has shipped since v1.5.x but had no end-user docs; QA
  folk who want to spot hardcoded strings or layout overflow could
  not discover it.
- New section detailing the **AppleScript executor security model**
  (seven safeguards: platform check, absolute `osascript` path,
  stdin-only script delivery, 8 s hard timeout, 1 MiB output cap,
  log redaction, no user-supplied scripts).

## [1.5.22] — 2026-05-04

### Chore

- Marketplace metadata polish: `license`, `homepage`, `bugs.url`,
  and `keywords` (`mcp`, `claude`, `cursor`, `windsurf`, etc.)
  added to `package.json`. Marketplace search now surfaces the
  extension on common AI workflow keywords; the License field no
  longer shows `(unknown)`; the Q&A tab links to GitHub Issues.

### Security (project-wide)

- Production runtime CVE exposure cleared from 17 to 0 via a
  coordinated dependency upgrade in the companion PyPI package
  (FastMCP 3.1.1 → 3.2.4 plus cascading transitive bumps). The
  VS Code extension itself ships only TypeScript dev-dependencies,
  so it had no shipped runtime CVEs to begin with — but the MCP
  server you connect to (`serverUrl`) is now CVE-clean.

## [1.5.21] — 2026-05-04

### Added

- The extension now benefits from new MCP **server-level metadata**
  (server name, version, instructions, embedded icons) and **tool
  annotations** (`readOnlyHint=False`, `destructiveHint=False`,
  `idempotentHint=False`, `openWorldHint=True`). Hosts no longer
  prompt for "destructive operation" confirmation on every
  `interactive_feedback` call, so the back-and-forth is materially
  smoother.

### Chore

- `engines.vscode` aligned with `@types/vscode` to keep the
  extension host and the type checker on the same VS Code API
  baseline.
- `dependabot.yml` ignore rule pinning `@types/vscode`, preventing
  recurring rebase conflicts with `engines.vscode`.

## [1.5.20] — 2026-05-04

### Added

- **"Open in IDE"** button on the settings page. Loopback-only,
  path-whitelisted, and shell-injection-proof: editor priority is
  `AI_INTERVENTION_AGENT_OPEN_WITH` env override → request `editor`
  field → cursor / code / windsurf / subl / webstorm / pycharm
  auto-detect → system default (`open` / `xdg-open` / `start`).
- **Bark deep-linking** via `bark_url_template` with placeholders
  `{task_id}`, `{event_id}`, `{base_url}`. iOS users now jump
  straight to the relevant feedback task from the push.
- **Default selection for `predefined_options`** in three input
  shapes (`str` / `dict` / `list`); the multi-task UI honours the
  default while still letting the user change it.
- Full **PWA icon family** (`manifest.webmanifest` plus 16/32/180/
  192/512 PNG and SVG) with `maskable` purpose. Web UI now passes
  Lighthouse PWA installability checks and can be added to the
  home screen / desktop dock.

### Changed

- `interactive_feedback` docstring overhauled with use cases,
  parameter guidance, and behavior contract — visible to LLM
  agents at tool registration.

---

For all earlier versions and full project history, see the
[root `CHANGELOG.md`][root-changelog] on GitHub.
