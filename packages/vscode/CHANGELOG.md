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
