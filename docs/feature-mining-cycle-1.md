# Feature Mining Cycle #1 — Competitive Differential vs. `mcp-feedback-enhanced`

> Performed during loop-task cycle following CR#30 (commits ≥ `714f756`).
>
> **Why this doc exists**: The user explicitly asked us in this loop to
> "research what's missing from the project compared to similar
> products, especially in Agent / Cursor Glass mode". Doing the
> ddg-search / WebFetch / source-tree-diff exercise every cycle wastes
> tokens; this doc memoizes the **delta**, so subsequent cycles can
> pick from the "待实现 backlog" without re-investigating.

## Reference product

| Project | Version surveyed | URL |
|---|---|---|
| `mcp-feedback-enhanced` (Minidoracat fork) | v2.6.0 | <https://github.com/Minidoracat/mcp-feedback-enhanced> |

We pick `mcp-feedback-enhanced` as the primary reference because it's
the most actively-maintained ancestor of this whole family of
`interactive_feedback` MCP servers, and the README explicitly lists
features by version, making diff-tracking straightforward.

Excluded from the survey (lower bar / superseded):

- `noopstudios/interactive-feedback-mcp` (original, minimal)
- `sanshao85/mcp-feedback-collector` (cited as UI design source)
- `poliva/*` forks (drift toward platform-specific Bark hooks)

## §1. Already aligned / on-par

These features exist in `mcp-feedback-enhanced` **and** in
`ai-intervention-agent`; no investment required.

| Feature | mcp-feedback-enhanced | ai-intervention-agent | Notes |
|---|---|---|---|
| Web UI | ✅ Tauri + Web | ✅ Web + VS Code extension | We deliver desktop via VS Code instead of Tauri |
| Multi-task tabs | ✅ "Multiple Sessions" | ✅ since R-cycle (multi_task.js) | |
| Auto-submit / countdown | ✅ 1–86400 s | ✅ default 240 s, range 0 or [10, 3600] | Ours has a documented safety cap |
| Image upload (PNG/JPG/JPEG/GIF/BMP/WebP) | ✅ | ✅ image-upload.js | Both support drag+drop + clipboard paste |
| Markdown + code highlighting | ✅ | ✅ Prism-based, code-copy buttons | Plus math (KaTeX) on our side |
| I18n | ✅ en / zh-TW / zh-CN | ✅ en / zh-CN | We do not yet ship zh-TW; see §3 |
| System notifications | ✅ "v2.6.0 system-level alerts" | ✅ system / web / sound / Bark | Ours covers a wider channel matrix |
| Sound notifications | ✅ built-in sounds + custom upload | ✅ built-in only | Custom upload missing; see §3 |
| Quick phrases / prompt management | ✅ "CRUD + sort + usage stats" | ✅ quick_phrases.js (R131 series) | Comparable; ours lacks usage-stat sorting |
| Auto-detect environment | ✅ SSH / WSL detection | ✅ Loopback URL suggestion + LAN-IP suggestion | |
| Shortcut: submit | ✅ Ctrl+Enter / Cmd+Enter | ✅ R140 (with Enter-mode toggle) | We additionally let user pick Enter-mode |
| Shortcut: paste image | ✅ Ctrl+V / Cmd+V | ✅ image-upload.js paste handler | |
| Input box height memory | ✅ "smart memory" | ✅ R137 (feedback_textarea_height.js) | |
| Persistent feedback drafts | — *(not advertised)* | ✅ R139 | We extend beyond reference |
| One-click code copy | ✅ | ✅ (app.js copy button) | |
| Char counter | — *(not advertised)* | ✅ feedback_char_counter.js | We extend beyond reference |
| Connection auto-recovery from network loss | — *(not advertised)* | ✅ BUG5 `online` event listener | We extend beyond reference |
| Connection auto-recovery from BFCache | — *(not advertised)* | ✅ commit `9a3d3d8` (this cycle) | We extend beyond reference |
| Keyboard cheatsheet (`?`) | — *(not advertised)* | ✅ R144 (keyboard_shortcut_help.js) | We extend beyond reference |
| Footer GitHub link | — (separate spans) | ✅ feat-footer-link-{web,plugin} (this cycle) | Merged into single anchor |

**Verdict**: For core feedback-loop interaction, parity is solid;
our extensions tend toward operational resilience (BUG5 / BFCache /
drafts / char-counter) and IDE integration (VS Code extension).

## §2. Intentionally NOT adopted (with rationale)

These exist in `mcp-feedback-enhanced` but we have **explicit
reasons** not to chase them. Recording these so a future loop cycle
doesn't waste effort re-debating.

### 2.1 Tauri-based desktop application (v2.5.0 in reference)

- **Reference offers**: Cross-platform native desktop app via Tauri,
  Win/macOS/Linux.
- **Why we skip**: The VS Code extension (`packages/vscode/`) already
  delivers the "no-browser-context-switch" UX in IDE-embedded form.
  Adding Tauri would balloon CI matrix (3 OS × 2 arch), ship a 30+
  MB binary, and require Rust toolchain in CI. The IDE-embedded
  webview is strictly better for the actual workflow ("AI agent
  pauses → user types feedback").

### 2.2 `Ctrl+I` focus-textarea shortcut

- **Reference offers**: `Ctrl+I` / `Cmd+I` jumps focus to input.
- **Why we skip**: `Ctrl+I` clashes with browser "italic" semantics
  inside editable contexts; discoverability is poor. R144 chose `?`
  cheatsheet pattern instead (GitHub/GitLab/Linear convention), with
  the explicit reasoning recorded in
  `static/js/keyboard_shortcut_help.js` lines 17–21.

### 2.3 Session export (JSON / CSV / Markdown)

- **Reference offers**: Session history with multi-format export.
- **Why we skip**: User explicitly requested removal of the download
  button (`feat-remove-download`, commit `2708720`). The backend
  `/api/tasks/export` endpoint is still registered for CI / backup
  scripts (see `web_ui_routes/task.py` NOTE comment), but no
  UI affordance is provided. Reintroducing UI requires fresh
  user buy-in.

### 2.4 System self-test notification button / Activity dashboard

- **Reference offers**: Connection-quality dashboard + manual
  self-test trigger.
- **Why we skip**: User explicitly requested removal
  (`feat-remove-test`, commit `faad96a`). Backend endpoints
  (`/api/system/{health,notifications/test,sse-stats,recent-logs}`)
  are still registered for monitoring + CI consumers, see
  `web_ui_routes/{system,notification}.py` NOTE comments. Same
  buy-in rule applies.

### 2.5 Auto Command Execution (v2.6.0 in reference)

- **Reference offers**: Run preset shell commands after session
  create / commit.
- **Why we skip**: Out of scope for an "interactive feedback"
  primitive — and a security footgun (the MCP server would have to
  run arbitrary commands). Cursor/Claude Code already have first-class
  hooks for this at the IDE level. Implementing here would duplicate
  + worsen IDE-native solutions.

## §3. Backlog — candidate adoptions (ordered by ROI ÷ risk)

Sorted top→bottom by `value × discoverability / implementation-cost`.
Each item lists rough scope + commit boundary so future loop cycles
can pull off the top of the queue.

### 3.1 SSE connection-status indicator (HIGH ROI, ~200 LoC)

- **Reference inspiration**: "Connection Monitoring: WebSocket
  status monitoring, auto-reconnection, quality indicators".
- **Gap**: We have `_sseConnected` boolean state in `multi_task.js`
  but never surface it to the user. When SSE silently dies and only
  the 30 s polling safety-net is active, users perceive nothing
  except slower task arrival.
- **Proposed scope**:
  - Add a 3-state visual indicator near the header (connected /
    reconnecting / disconnected); default `connected = hidden` to
    respect non-intrusive UX.
  - Hook into existing `onopen` / `onerror` / `_sseReconnectDelay`
    state transitions.
  - i18n keys × 3 (one per state's tooltip).
  - Regression: HTML element present, CSS three-state classes,
    JS hooks fire, i18n keys exist in `en.json` + `zh-CN.json`.
- **Risk**: Header layout shift; mitigate by reserving 1×1em slot
  and only showing colour on non-connected state.

### 3.2 Auto-resubmit countdown pause / +60s extend (MEDIUM ROI, ~150 LoC backend + 80 LoC frontend)

- **Reference inspiration**: "Auto-commit Control: Added pause and
  resume buttons for better control over auto-commit timing"
  (v2.6.0).
- **Gap**: Once countdown starts, the user cannot pause or extend
  without going into settings + globally disabling auto-resubmit.
  Power users writing long replies have anxiety about the 240 s tick.
- **Proposed scope**:
  - Backend: `POST /api/tasks/<id>/extend?seconds=60` — bump
    `task.deadline` forward, SSE broadcast `task_updated`.
  - Frontend: tiny "+60 s" button next to the countdown ring;
    becomes "+30 s" after first click (diminishing-returns hint to
    avoid users gaming auto-resubmit into 永远).
  - Rate limit: max 3 extensions per task (or until `feedback.
    backend_max_wait` cap).
  - Regression: backend route registered, rate-limit honored,
    frontend button triggers POST + updates UI on broadcast.
- **Risk**: Need server-frontend coordinated deadline source-of-truth.
  Existing `taskDeadlines` cache helps.

### 3.3 zh-TW locale (LOW ROI, ~30 min copy-paste + native review)

- **Reference inspiration**: They ship zh-TW (their primary, since
  fork origin is Taiwan).
- **Gap**: We ship en + zh-CN only. Some zh-TW users prefer not to
  read zh-CN and end up using en.
- **Proposed scope**:
  - Copy `zh-CN.json` → `zh-TW.json`, swap obvious lexical/wording
    differences (`视频→影片`, `档→檔`, `配置→設定`, etc.).
  - Add locale to `LOCALE_REGISTRY` + locale picker.
  - Pseudo-locale regen.
- **Risk**: Without a zh-TW native speaker, machine-translated zh-TW
  is worse than letting users fall back to zh-CN. Defer until a
  native contributor offers to take it on.

### 3.4 Custom notification sound upload (LOW ROI, ~120 LoC)

- **Reference inspiration**: "Built-in multiple sound effects,
  custom audio upload support, volume control".
- **Gap**: We ship built-in sounds but no user-upload path.
- **Proposed scope**: Settings page → file picker → store base64 in
  localStorage → wire into `notification-manager.js` playback path.
- **Risk**: localStorage 5 MB quota; need MIME / size validation;
  storage cleanup on settings reset. Worth it only if user demand
  shows up in issues.

### 3.5 Prompt usage statistics + smart sort (LOW ROI, ~100 LoC)

- **Reference inspiration**: "Prompt Management: CRUD operations
  for common prompts, usage statistics, intelligent sorting".
- **Gap**: Our quick phrases are insertion-ordered; recently/often
  used aren't promoted.
- **Proposed scope**: Increment per-phrase use-count in localStorage
  when chip inserted; secondary sort key.
- **Risk**: Low. But minor UX value compared to §3.1 / §3.2.

## §4. Forward log

Future loop cycles **must** record the picked item back here as
"resolved" (with commit hash and date) so this doc stays
authoritative — same discipline as `docs/code-reviews/cr*.md`.

| Item | Status | Commit | Date |
|---|---|---|---|
| §3.1 SSE status indicator | **resolved** | (this cycle, after feature-mining-cycle-1.md) | 2026-06-04 |
| §3.2 Countdown pause / extend | not started | — | — |
| §3.3 zh-TW locale | not started | — | — |
| §3.4 Custom audio upload | not started | — | — |
| §3.5 Quick-phrase usage sort | not started | — | — |

## §5. Survey methodology + reproducibility

For the next maintainer redoing this exercise:

1. WebFetch `https://raw.githubusercontent.com/Minidoracat/mcp-feedback-enhanced/main/README.md`
   (or current main branch).
2. Walk the "🌟 Key Features" + "Version History" sections and
   cross-reference each bullet against our codebase using `Grep` on
   the key string + reading the relevant module.
3. For each bullet, classify into §1 (have it) / §2 (rejected with
   reason) / §3 (backlog candidate).
4. Update the "Forward log" table when items are picked up; add new
   §3.x rows when new features land in reference product.

This is meant to be done **at most every other release cycle** to
keep effort bounded.
