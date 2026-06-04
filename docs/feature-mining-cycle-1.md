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
| Quick phrases / prompt management | ✅ "CRUD + sort + usage stats" | ✅ quick_phrases.js (R131 series incl. R131c) | At parity; R131c added `last_used_at` + `use_count` + `_sortPhrasesByUsage` |
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

### 3.2 Auto-resubmit countdown +60s extend (MVP, **resolved** commit `fcdbc2d`)

- **Reference inspiration**: "Auto-commit Control: Added pause and
  resume buttons for better control over auto-commit timing"
  (v2.6.0).
- **Gap (was)**: Once countdown starts, the user cannot pause or
  extend without going into settings + globally disabling
  auto-resubmit. Power users writing long replies had anxiety about
  the 240 s tick.
- **What shipped** (MVP scope):
  - Backend: `POST /api/tasks/<id>/extend` with body `{seconds: 60}`,
    rate-limited 30/min. Returns 404 / 400 / 422 / 500.
    `Task` model gains `extends_used: int = 0` + `extend_deadline(...)`
    method enforcing 4 reject paths: completed / disabled / range /
    max-reached.
  - Frontend: "+60s" button next to countdown text in
    `#countdown-container`. `updateCountdownExtendButton(task)` and
    `handleExtendCountdownClick()` in `multi_task.js` keep button
    state in sync and POST then update local `taskDeadlines`
    immediately.
  - Limits: each task max 3 extends × [10, 300]s. Hard cap prevents
    users from gaming auto-resubmit into 永远.
  - i18n: `page.extendCountdown.{label,title,ariaLabel,limitReached,networkError}`.
- **What was NOT shipped (deferred for separate cycle)**:
  - **True pause/resume**: Needs `Task.is_paused` state field +
    scheduler skip + 2 buttons + SSE event. Larger surface; observe
    if +60s suffices before investing.
  - **SSE `task_updated` broadcast**: Avoided to keep
    `sse_event_schemas.py` stable. Multi-client sync via 5s polling
    (seconds-level latency acceptable).
- **Regression**: `tests/test_feat_countdown_extend.py` — 39 cases
  covering Task model + endpoint + HTML + CSS + JS + i18n + anchors.

### 3.3 zh-TW locale (MVP, **resolved** commit `c7bac5f`)

- **Reference inspiration**: They ship zh-TW (their primary, since
  fork origin is Taiwan).
- **Gap (was)**: We shipped en + zh-CN only. zh-TW / zh-HK / zh-MO /
  zh-Hant* BCP-47 tags were all collapsed to ``zh-CN`` by
  ``normalizeLang`` (R72-D SSRF hardening side-effect).
- **What shipped** (MVP scope):
  - Dev-only script ``scripts/gen_zhtw_from_zhcn.py`` derives
    ``static/locales/zh-TW.json`` from ``zh-CN.json`` via two-layer
    PHRASE_MAP (~160 GUI 高频词组) + CHAR_MAP_v2 (~445 单字 fallback).
    No new runtime dependency (avoids OpenCC license / size cost).
  - ``_meta.translationNote`` injected at JSON top-level inviting
    native PR polish; invariant tests treat ``_meta`` as metadata
    (excluded from key parity check via ``_flatten_paths`` ignore).
  - Frontend + backend ``normalizeLang`` aligned to fold
    ``zh-TW / zh-HK / zh-MO / zh-Hant*`` → ``zh-TW``, and
    ``zh-CN / zh-Hans / zh-SG / zh-MY`` → ``zh-CN``. Unknown tags
    still fall back to DEFAULT_LANG (R72-D preserved).
  - ``i18n.py._MESSAGES["zh-TW"]`` with 28 backend notification
    strings (config saved / language updated / validation errors).
  - ``server_config.WebUIConfig.SUPPORTED_LANGS`` + ``/api/update-language``
    whitelist + ``web_ui.html`` ``<option value="zh-TW">`` all wired.
  - en + zh-CN gain ``settings.langZhTW`` (endonym "繁體中文").
- **What was NOT shipped (deferred)**:
  - **Native zh-TW review polish** of single keys (PRs welcome via
    the ``_meta.translationNote`` channel).
  - **VSCode extension** ``packages/vscode/locales/zh-TW.json``
    (extension i18n is mirrored separately; defer to next cycle).
  - **README zh-TW** translation (lowest priority).
- **Regression**: ``tests/test_feat_zhtw_locale.py`` — 25 cases
  covering script + _meta + schema parity + content sanity +
  normalizeLang + i18n.py + server_config + web_ui whitelist + HTML
  option + i18n keys + SSRF hardening preservation.

### 3.4 Custom notification sound upload (**resolved** commit `0e6b1fa`)

- **Reference inspiration**: "Built-in multiple sound effects,
  custom audio upload support, volume control".
- **Gap (was)**: Built-in `/sounds/deng.wav` + synth fallback only;
  no user-upload path. Users wanting their own notification sound
  had to monkey-patch.
- **What shipped**:
  - **NotificationManager API**: `hasCustomSound() / getCustomSoundMeta() /
    loadCustomSoundFromStorage() / saveCustomSoundFromFile(file) /
    clearCustomSound()` 5-method surface. `saveCustomSoundFromFile`
    returns `{success, error, ...}` with 6 distinct error codes
    (`no_file / invalid_mime / too_large / read_failed /
    storage_failed / decode_failed`) for precise UI messaging.
  - **`playSound()` default-param dispatch**: changed signature from
    `playSound('default', ...)` to `playSound(null, ...)`; when null,
    dispatches to `'custom'` if `audioBuffers.has('custom')` else
    `'default'`. Explicit `playSound('default')` (used by the Test
    button) preserves original semantics.
  - **Settings UI**: file input + Test + Remove buttons + live status
    string. Wire via `settings-manager.js::_wireCustomSoundControls`.
    Settings reset also calls `clearCustomSound()` to honour
    "reset = factory default" semantics.
  - **Limits**: `CUSTOM_SOUND_LS_KEY = 'aiia.notif.customSound.v1'`
    (versioned for future schema migrations), 700KB max (~933KB
    base64, leaves 4MB+ in 5MB localStorage quota), 9-MIME whitelist
    (mp3/wav/ogg/webm/aac/m4a/flac).
  - **a11y**: hidden `<input type=file>` with `<label for>` trigger
    (keyboard navigable), `prefers-reduced-motion` disables button
    transition, `data-i18n-aria-label` for SR users.
  - **i18n**: `settings.customSound.{label, upload, uploadTitle, test,
    clear, uploaded, notUploaded, errors.{generic, invalidMime,
    tooLarge, readFailed, storageFailed, decodeFailed}}` × 4 locales.
  - **CSS**: walks project's `--primary-500` design token (no hex
    fallback; passes R66 brand-colour drift guardrail).
- **What was NOT shipped (deferred)**:
  - **Multi-slot sound management**: competitor also single-slot; not
    worth complexity until user demand observed.
  - **Server-side upload endpoint**: would add SSRF / storage attack
    surface; localStorage roundtrip is sufficient and per-device.
  - **Built-in sound pack**: needs license-clear audio assets;
    deferred to a future content-curation cycle.
- **Regression**: `tests/test_feat_custom_sound.py` 17 cases / 7
  classes covering API surface, error codes, dispatch logic,
  initAudio integration, HTML controls, settings wiring, CSS+i18n.

### 3.5 Prompt usage statistics + smart sort (**already shipped**, R131c)

- **Reference inspiration**: "Prompt Management: CRUD operations
  for common prompts, usage statistics, intelligent sorting".
- **Status**: **Not actually a gap.** Discovered during cycle-1
  loop work that R131c already ships `recordPhraseUsage(id)` +
  `_sortPhrasesByUsage(phrases)` in `static/js/quick_phrases.js`
  (lines 654-697), with regression coverage in
  `tests/test_quick_phrases_usage_sort_r131c.py` (14 cases /
  5 invariant classes).
- **What R131c shipped**:
  - Each phrase gains optional `last_used_at` (ms epoch) + `use_count`
    fields (v1 schema, forward-compatible bootstrap on old data).
  - Chip click handler calls `insertTextIntoFeedback` then
    `recordPhraseUsage` (insert-first, record-second so insertion
    failure doesn't gate the user's primary action).
  - `renderList()` sorts via `_sortPhrasesByUsage` before `forEach`:
    primary `last_used_at` desc → secondary `use_count` desc →
    tertiary `created_at` desc → quaternary `id` lexical for
    stability.
- **Why I missed it in the original cycle-1 survey**: scanned
  by feature name ("smart sort") and matched only file names,
  not the R131c history. Forward log corrected — this row is
  here as a doc fix so future cycles don't re-investigate.

## §4. Forward log

Future loop cycles **must** record the picked item back here as
"resolved" (with commit hash and date) so this doc stays
authoritative — same discipline as `docs/code-reviews/cr*.md`.

| Item | Status | Commit | Date |
|---|---|---|---|
| §3.1 SSE status indicator | **resolved** | (this cycle, after feature-mining-cycle-1.md) | 2026-06-04 |
| §3.2 Countdown +60s extend (MVP, not pause/resume) | **resolved** | `fcdbc2d` | 2026-06-04 |
| §3.3 zh-TW locale (MVP, dev-script derived, awaiting native polish) | **resolved** | `c7bac5f` | 2026-06-05 |
| §3.4 Custom audio upload | **resolved** | `0e6b1fa` | 2026-06-05 |
| §3.5 Quick-phrase usage sort | **already shipped** (R131c) | (pre-cycle-1, retroactive) | (existed) |

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
