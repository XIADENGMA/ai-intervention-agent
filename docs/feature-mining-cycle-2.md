# Feature Mining — Cycle 2

> Second-round competitive analysis vs `mcp-feedback-enhanced`
> (4K stars, JavaScript-dominant Web UI + Tauri desktop) at HEAD
> `2026-01-15` (v2.6.1 unreleased; v2.6.0 + PR #207 merged to main).
>
> Cycle-1 cleared the entire adoptable §3.x backlog (§3.1 SSE
> status / §3.2 +60s extend / §3.3 zh-TW / §3.4 custom audio /
> §3.5 quick-phrase smart sort). Cycle-2 baselines against
> competitor's main branch since cycle-1's pin (v2.6.0 release).
>
> Source method: ddg-search + WebFetch on
> `RELEASE_NOTES/CHANGELOG.en.md` + PR #207. Cross-checked against
> `https://pypi.org/project/mcp-feedback-enhanced/` for shipping
> versions.

---

## 0. Methodology recap

1. **Baseline diff** — v2.6.0 (cycle-1 baseline) → main HEAD
   (cycle-2 baseline). New code: PR #207 = v2.6.1-unreleased
   session-scoped routes.
2. **Pre-survey grep** — for each candidate feature, run BOTH
   (cycle-2 hardened, after 3 survey misses):
   - `rg '<feature-keyword>' src/` — filesystem scan
   - `git log --grep '<feature-keyword>' --since='1 year ago'`
     — history scan
   This is **mandatory** for every backlog item; cycle-3 mining
   doc must include the grep output as evidence per item.
3. **Score** — each item gets a ROI estimate: { **high** =
   high user-value × low LoC, **medium** = either-or, **low** =
   high LoC for marginal value, **defer** = depends on
   architecture choices we haven't made }.
4. **Forward log** — table at §6 tracks which items get adopted
   in subsequent cycles.

---

## 1. Already aligned (no work)

These were already shipped or are inapplicable to our
architecture; documented here so future audits don't re-survey
them.

| Competitor feature | Our status | Notes |
|---|---|---|
| Built-in & custom audio upload (v2.4.3) | shipped (cycle-1 §3.4, `0e6b1fa`) | 5-API surface, 7 error codes, duration cap, 4 locales |
| Quick-phrase / common-prompt usage sort (v2.4.x) | shipped (R131c, mining §3.5 doc-fix `83918bd`) | persistent count-sort + recency tiebreak |
| Auto-resubmit countdown control (v2.6.0 pause/resume) | shipped MVP (cycle-1 §3.2 +60s, `fcdbc2d`) | we ship +60s extend; pause/resume rejected as over-scope |
| SSE / connection status indicator (v2.5.0 reconnection UI) | shipped (cycle-1 §3.1, `24ae44e`) | 3-state visual indicator |
| zh-TW locale (v2.6.0 i18n refactor) | shipped (cycle-1 §3.3, `c7bac5f`+`df97acc`) | script-derived, web + VSCode parity |
| Settings backend persistence (v2.5.6 unified FastAPI save) | shipped (R20.x) | we already use JSON file + atomic write |
| `SSH_HOST` remote bind (v2.5.5 `MCP_WEB_HOST`) | shipped | our `bind_host` config + 0.0.0.0 documented |
| WebSocket reconnection w/ exponential backoff (v2.5.0) | shipped (SSE w/ jittered retry + Last-Event-ID resume) | SSE not WS, but functional parity |
| XSS protection / DOMPurify (v2.5.0) | shipped (R-cycle: validation-utils.js + dom-security.js) | we have CSP + sanitizer + escape helpers |
| System-level notifications (v2.6.0) | shipped (Bark + Web Notifications API) | dual-channel |
| Session-scoped settings (v2.5.6) | shipped (per-task state in TaskQueue) | architectural difference; we don't need session URLs because tasks ARE sessions |
| AI work summary Markdown rendering (v2.5.0) | shipped (`marked.js` + DOMPurify path) | unified rendering pipeline |
| Input height memory (v2.4.3) | **shipped** (R137 `feedback_textarea_height.js`) | full schema-v1 localStorage envelope + clamp + ResizeObserver primary + mouseup/touchend fallback + 150ms debounce. cycle-2 survey初次漏认；类似 cycle-1 §3.5 R131c 智能排序漂移，列入 process-learning |
| Session Export (v2.6.0) | **shipped** (R125 / R125c / R135 `/api/tasks/export`) | json + markdown formats, include_images toggle, since=<ISO> 增量 export, 30/min rate-limit, Content-Disposition attachment, atomic read-lock snapshot. cycle-2 survey 第 3 次漏认；触发 §0 methodology 强化 |

---

## 2. Architectural mismatches (won't ship)

These competitor features don't translate to our architecture
without significant refactor; documented so we don't keep
mis-classifying them as backlog.

### 2.1 Tauri desktop application (v2.5.0)

- Competitor ships Tauri-based native desktop with Rust toolchain.
- We ship a **Web UI + VSCode extension** pair. The VSCode panel
  is functionally equivalent to a desktop app for the dominant
  user persona (developers in their IDE).
- Building Tauri would add ~30 MB binary, CI cross-compilation
  burden (Windows x64 + macOS Intel/ARM + Linux x64), and a new
  Rust toolchain. **Not worth** for our user base.

### 2.2 `/feedback/{session_id}` session-scoped routing (v2.6.1 PR #207)

- Competitor's old architecture coupled to a single active session
  globally; PR #207 splits to per-session routes + WS bindings.
- Our `TaskQueue` already supports concurrent tasks with task-id
  routing (`GET /api/tasks/<task_id>`, etc.). We never had the
  single-session coupling competitor is fixing.
- **Inapplicable**: we already shipped what this PR is moving
  toward.

### 2.3 Auto Command Execution (v2.6.0)

- Competitor lets you preset shell commands that run after each
  new session or commit (e.g. `git pull && npm install`).
- Our project's threat model treats running arbitrary shell from
  a notification UI as a **command-injection risk surface** that
  the agent shouldn't reach into. We let agents propose commands
  in their feedback request; the user runs them in their IDE.
- **Won't ship** without an explicit user request + audit cycle.

---

## 3. Adoptable backlog (cycle-2)

Items where competitor genuinely has something we don't, ranked
by ROI.

### 3.1 Session Export feature (v2.6.0) — **already shipped (R125 / R125c / R135); doc corrected post-survey**

- **Survey miss (third in cycle-2)**: cycle-2 initial doc
  classified Session Export as "MEDIUM ROI, ~200 LoC adopt".
  Post-survey grep `rg '/api/tasks/export' src/` immediately
  located the existing implementation at `web_ui_routes/task.py
  ::export_tasks`:
  - **R125** initial: `GET /api/tasks/export?format={json,
    markdown}` with Content-Disposition attachment trigger,
    timestamped filename, atomic snapshot via
    `get_all_tasks_with_stats`, 30/min rate limit.
  - **R125c** follow-up: `?include_images={true,false,1,0,yes,no}`
    toggle to strip base64 image data for "lightweight backup"
    workflows (JSON dump shrinks from MB to KB).
  - **R135** later: `?since=<ISO8601>` incremental export filter
    so periodic backups don't re-transfer unchanged tasks
    (O(M×content) instead of O(N×content)).
- **What is NOT shipped (the only real gap)**: no Settings-page UI
  button. Users discover the endpoint only via API docs / curl.
  This is a separate cycle-3 item (~30 LoC: anchor tag pointing
  at `/api/tasks/export` with download attribute, perhaps a small
  format selector dropdown).
- **Process learning**: this is the **third** cycle-2 survey
  miss (§3.3 input-height-memory, §3.4 partial, §3.1 Session
  Export). Three misses in one cycle is a process-pattern, not
  individual mistakes. Now mandatory in §0 methodology:
  **EVERY backlog item, before classifying, must run BOTH**:
  1. `rg '<feature-keyword>' src/` — filesystem scan
  2. `git log --grep '<feature-keyword>' --since='1 year ago'` —
     history scan
  No exceptions. Cycle-3 mining doc must include the grep
  output as evidence per item.
- **Decision**: **no Session Export work needed**. UI button is
  cycle-3 polish item (§7 batch C reordered below).

### 3.2 Session-link copy + open-session UI (v2.6.1 PR #207) — **shipped this cycle**

- **Reference inspiration**: "Session manager UI: open session +
  copy session link" (PR #207).
- **Gap (was)**: We have task-id-keyed URLs implicitly
  (`?task_id=X`), but no explicit UI affordance for "copy a link
  that opens this specific task". Currently URL changes on task
  switch but users don't know they can copy the URL bar contents.
- **What shipped**:
  - **`buildTaskDeepLink(taskId, base?)` helper**: uses the
    standard `URL` API (not string concat) to correctly handle
    pre-existing query strings, hash fragments, and origin /
    pathname extraction. `searchParams.set("task_id", id)`
    overrides any stale `task_id` in the base URL. Returns empty
    string on invalid input or `URL` constructor throw.
  - **`copyTaskLinkToClipboard(taskId)` helper**: composes the
    link via `buildTaskDeepLink` and writes via the shared
    low-level `_writeToClipboard` helper.
  - **`_writeToClipboard(text)` extraction**: the dual-path
    clipboard logic (Clipboard API primary + `execCommand`
    fallback) that previously lived inline in
    `copyTaskIdToClipboard` is now a separate function; both
    `copyTaskIdToClipboard` and `copyTaskLinkToClipboard` call
    it. This avoids the duplicate-execCommand smell that would
    otherwise appear from this commit, and the regression test
    `test_no_duplicated_execcommand` asserts the count stays at
    exactly **1**.
  - **`Shift+dblclick` modifier on task tab textSpan**: same
    handler as the cycle-2 §3.4 dblclick, now branches on
    `e.shiftKey` — Shift+dblclick → link copy; plain dblclick →
    id copy. The modifier-driven design is the universal
    "alternate variant" idiom (cf. shift-click multi-select in
    IDEs, shift-arrow extend selection).
- **What was NOT shipped (deferred)**:
  - **Dedicated "copy link" icon button**: would clutter the task
    tab UI; for a power-user feature the Shift+dblclick gesture
    is sufficient. The existing `title` tooltip already telegraphs
    that the textSpan has special interaction (it shows the full
    `task_id` on hover).
  - **"Open session in new window/tab"** affordance: browsers
    already let users do this with Ctrl+Click on the URL bar
    after copying; we don't add value by re-implementing it.
- **Regression**: `tests/test_feat_mining2_session_link_copy.py`
  with 5 test classes / ~12 cases, covering helper definitions,
  URL API usage, low-level helper extraction (anti-duplication),
  Shift+dblclick wiring, and window exposure.

### 3.3 Input height memory (v2.4.3) — **already shipped (R137); doc corrected post-survey**

- **Survey misread**: initially classified as adoptable backlog.
  Post-survey grep on `localStorage` + `feedback-text` discovered
  `feedback_textarea_height.js` (R137), which already does:
  - `aiia.feedbackTextareaHeight.v1` storage key
  - `schema_version` envelope (compatible with future migrators)
  - `clamp(100, 800)` against extreme drag
  - `ResizeObserver` primary, `mouseup` / `touchend` fallback
  - 150ms debounce on write
  - silent fail on quota / private browsing
- **Process learning**: same class of mining miss as cycle-1 §3.5
  (R131c quick-phrase smart sort). Mining surveys must grep
  `git log --grep` + raw filesystem scan **before** classifying
  features as "not started". Moved to §1 (aligned).
- **Decision**: **no work**.

### 3.4 One-Click copy: project path + task ID (v2.4.3) — **partial ship**

- **Reference inspiration**: "One-Click Copy: Project path and
  session ID support click-to-copy" (v2.4.3).
- **Gap discovered during survey**:
  - `task_id`: shown in task tab (truncated) with `title` tooltip
    for full ID, but no copy affordance. ⇒ **shipped this cycle**.
  - `project_directory`: not surfaced in UI at all; only used
    server-side. ⇒ N/A; would need a separate "show project info"
    UI feature first.
- **What shipped** (in this commit before cr34):
  - `copyTaskIdToClipboard(taskId)` helper in `multi_task.js` with
    dual path: `navigator.clipboard.writeText` primary +
    `document.execCommand("copy")` legacy fallback. Reuses
    project's existing `status.copied` / `status.copyFailed`
    i18n keys (no new strings).
  - `createTaskTab`'s `textSpan` gets `dblclick` listener →
    `copyTaskIdToClipboard(task.task_id)` + `stopPropagation` to
    keep single-click as task-switch.
  - `data-copyable-task-id` attribute on textSpan for UI tests +
    future styling hooks.
  - Anti-regression invariant `test_no_single_click_hijack`
    guarantees `textSpan` never gains a `click` listener (would
    break task-switch UX).
- **Why dblclick not single-click**: single click is reserved for
  task-switch (existing core interaction). Making copy a separate
  affordance (icon button) would clutter the tab UI. Dblclick is
  the universal "do the alternate action" idiom; the title
  tooltip ("hover to see full task_id") was already there as the
  discovery affordance.
- **Decision**: **shipped (partial)**; project_directory deferred
  pending a "show project info" feature that doesn't exist yet.

### 3.5 Auto-commit pause control v2 (v2.6.0) — **DEFER**

- **Reference inspiration**: "Auto-commit Control: Added pause
  and resume buttons for better control over auto-commit timing"
  (v2.6.0).
- **Gap analysis**: We shipped MVP (+60s extend) in cycle-1.
  Competitor's pause/resume is full state-machine: user can hold
  countdown indefinitely.
- **Why deferred**: This is a follow-up to cycle-1 §3.2, but
  requires `Task.is_paused` boolean + scheduler skip-on-paused +
  new SSE event `task_paused`. Estimated 200-300 LoC. The +60s
  extend covers the most common "I need a bit more time" pattern;
  full pause/resume only matters for "I stepped away from
  keyboard for an unknown duration" which is rare.
- **Trigger condition for adoption**: ≥ 2 user reports of
  "+60s wasn't enough, please add pause".
- **Decision**: **defer** to cycle-3+, conditional on user
  signal.

### 3.6 Tool docstring LLM hinting (v2.5.5) — **DEFER**

- **Reference inspiration**: "Moved LLM instructions to tool
  docstring for improved token efficiency" (v2.5.5).
- **Gap analysis**: Our `interactive_feedback` tool's MCP schema
  describes parameters but doesn't include guidance like "ask
  before claiming completion" / "prefer pre-defined options". The
  per-project AGENT.md / CLAUDE.md files carry that.
- **Why deferred**: Moving instructions into docstring adds
  agent-runtime cost (every tool call gets the docstring in
  context) for minor benefit (agents already have project-level
  rules). The cost/benefit is unclear; need a 1-week telemetry
  cycle on "how often do agents skip the feedback step" before
  measuring.
- **Decision**: **defer** to a future cycle that has telemetry.

---

## 4. Non-competitor candidates (originality)

Items that don't come from `mcp-feedback-enhanced` but were
surfaced during this audit; we should evaluate independently.

### 4.1 `zhconv` library evaluation (cr33 §8 #2)

- **Origin**: cr33 recommended evaluating `zhconv` / `opencc-
  python` before `CHAR_MAP_v2` exceeds ~600 entries (currently
  445).
- **Pros**:
  - Industrial-grade Simplified↔Traditional + Traditional
    variants (Taiwan / Hong Kong / Macao) conversion.
  - ~30 MB install, but `zhconv` itself is pure Python ~250 KB.
  - Maintained, tested, used by Wikipedia.
- **Cons**:
  - Adds runtime / build-time dep; our `gen_zhtw_from_zhcn.py`
    is dev-only and runs once at build time, so the dep would
    only be in `[tool.uv.dev-dependencies]`.
  - Has its own opinions (e.g. some idioms get converted in a
    way we may want to override).
- **Decision**: **investigate in cycle-3** — write a small
  prototype that runs both inline-map and `zhconv` over our
  zh-CN.json and diffs the outputs. Adopt only if `zhconv`
  output is ≥ 90% identical and the differences are higher
  quality.

### 4.2 BrowserStack-style cross-locale snapshot tests (internal)

- **Origin**: zh-TW shipped MVP; cr32 §3.3 noted "no native
  speaker review". We could systematize this via screenshot
  diffing.
- **Out of mining scope** — internal QA process improvement, not
  a feature; mention here for future planning cycle.

### 4.3 `gemini-cli` / `claude-code` hooks comparison

- **Not yet researched**. Both are alternative interactive AI
  CLIs with their own MCP / hook ecosystems. Worth a 1-day audit
  in cycle-3 to extract any **interaction-pattern** ideas (not
  necessarily feature ports).
- **Decision**: **survey in cycle-3**, no implementation
  expected.

---

## 5. Risks identified during survey

These aren't features but signals the competitor's project surface
to learn from:

- **SQLite-based session history (v2.5.0)** competitor uses local
  files (not SQLite). We use JSON snapshot + fsync. If we ever
  hit > 1000 historical tasks the JSON read/write cost will
  dominate; SQLite or a JSONL append-log would scale better.
  **Not urgent**; flag in next perf-audit cycle.
- **ESC shortcut removed (v2.5.5)** competitor removed ESC to
  prevent accidental window close. Confirm our keyboard
  shortcuts don't have a similar trap.
  **Verified safe** (cr34 cycle, grep on
  `src/ai_intervention_agent/static/js`): ESC is bound in 5
  places (`keyboard-shortcuts.js::registerDefaults`,
  `settings-manager.js`, `image-upload.js`,
  `keyboard_shortcut_help.js`, `quick_phrases.js`), **all** of
  them limited to "close current modal / overlay / settings
  panel / inline add-form". None close the page, kill a task,
  or otherwise destructively interact with data. The trap that
  bit competitor (ESC = close desktop window) does not apply
  to us — we have no window-level ESC handler at all. **No
  action**.

---

## 6. Forward log

| Item | Status | Commit | Date |
|---|---|---|---|
| §3.1 Session Export | **already shipped (R125 / R125c / R135)** | (pre-cycle-2) | survey miss #3; backend complete, only Settings-page UI button still missing — cycle-3 polish |
| §3.2 Session-link copy | **shipped** | (this commit) | Shift+dblclick task tab; reuses extracted `_writeToClipboard` helper |
| §3.3 Input height memory | **already shipped (R137)** | (pre-cycle-2) | survey miss; corrected |
| §3.4 One-click copy (task_id) | **partial — shipped task_id, project_path n/a** | (this commit) | dblclick task tab to copy full task_id; project_directory not surfaced in UI so n/a |
| §3.5 Pause/resume v2 | deferred (conditional) | — | — |
| §3.6 Tool docstring LLM hinting | deferred (telemetry) | — | — |
| §4.1 zhconv evaluation | not started | — | — |
| §4.3 gemini-cli / claude-code survey | not started | — | — |

---

## 7. Suggested ordering for cycle-3

**Updated cycle-3 ordering** (cycle-2 closed with 3 survey
misses; backlog clean):

1. **Batch A done** (cycle-2): §3.2 + §3.4 shipped; §3.3 + §3.1
   discovered as already shipped (R137 / R125 / R125c / R135).
2. **Batch C polish** (cycle-3): Settings-page "Export task
   history" UI button pointing at existing R125 endpoint with
   format selector (~30 LoC). The only Session Export gap is
   discoverability, not functionality.
3. **§4.1 zhconv prototype** — non-shipping investigation; output
   is a `docs/zhconv-eval.md` go/no-go report.
4. **§4.3 gemini-cli / claude-code interaction-pattern survey**
   — non-shipping; output is a `docs/feature-mining-cycle-3.md`
   draft.
5. **cr35** after 5 commits.

§0 methodology enforcement: cycle-3 mining doc **must** include
explicit grep evidence for each backlog item.

---

## 8. Related documents

- `docs/feature-mining-cycle-1.md` — cycle-1 backlog (all
  resolved)
- `docs/perf-audit-cycle-1.md` — backend perf audit
- `docs/code-reviews/cr30.md` ~ `cr33.md` — review history
