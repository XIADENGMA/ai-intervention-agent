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
2. **Pre-survey grep** — for each candidate feature, `git log
   --grep '<reference-feature>'` in our repo to avoid §3.5-style
   "already shipped" mining failures.
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

### 3.1 Session Export feature (v2.6.0) — **MEDIUM ROI, ~200 LoC**

- **Reference inspiration**: "Session Export Feature: Support
  exporting session records to multiple formats for easy sharing
  and archiving" (v2.6.0).
- **Gap**: We have no "export task history as JSON / Markdown /
  CSV" path. A user investigating "what feedback did I give last
  week" has to inspect the JSON state file manually.
- **Proposed scope**:
  - Backend: `GET /api/tasks/export?format={json,md,csv}` returning
    streaming export of completed tasks; rate-limited.
  - Frontend: Settings page → "Export task history" button →
    `<a href download>` trigger.
  - Filter UI: by status, date range, label (if any).
- **Acceptance**: regression test asserts endpoint + 3 formats +
  rate limit; manual smoke on real task history.
- **Risk**: JSON dump may leak prompt content user expected to be
  ephemeral; UI needs "confirm + scope picker" before download.
- **Decision**: **adopt**, plan as cycle-3 ship item.

### 3.2 Session-link copy + open-session UI (v2.6.1 PR #207) — **LOW-MEDIUM ROI, ~80 LoC**

- **Reference inspiration**: "Session manager UI: open session +
  copy session link" (PR #207).
- **Gap analysis**: We have task-id-keyed URLs implicitly
  (`?task_id=X`), but no explicit UI affordance for "copy a link
  that opens this specific task". Currently URL changes on task
  switch but users don't know they can copy the URL bar contents.
- **Proposed scope**:
  - Task tabs: add a small "copy link" icon next to each task
    title.
  - Click → write `${origin}${pathname}?task_id=${id}` to
    clipboard with `navigator.clipboard.writeText`.
  - Toast on success / fallback to `prompt()` if Clipboard API
    unavailable.
- **Acceptance**: regression test for icon presence + handler
  wiring + i18n key; manual smoke on Firefox / Safari (Clipboard
  API quirks).
- **Risk**: Clipboard API requires user gesture + secure context;
  fallback path well-tested.
- **Decision**: **adopt** — small, high-polish, doesn't disrupt
  existing UX.

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

### 3.4 One-Click copy: project path + task ID (v2.4.3) — **LOW ROI, ~50 LoC**

- **Reference inspiration**: "One-Click Copy: Project path and
  session ID support click-to-copy" (v2.4.3).
- **Gap**: We display `project_directory` and `task_id` in task
  panels but they're plain text. Users selecting them have to
  triple-click or drag-select.
- **Proposed scope**:
  - Wrap each in a `<span class="copyable" data-copy-value="...">`.
  - Single click → `navigator.clipboard.writeText` + 200ms
    visual feedback (background flash or check icon).
  - Reuses §3.2 clipboard helper, so once §3.2 lands this is
    almost free.
- **Acceptance**: 1 test for handler + 1 i18n key for
  `actions.copied` toast.
- **Risk**: minimal.
- **Decision**: **adopt** in batch with §3.2.

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
  shortcuts don't have a similar trap. **Action**: grep our
  `keyboard-shortcuts.js` for any destructive single-key bind
  next perf-audit cycle.

---

## 6. Forward log

| Item | Status | Commit | Date |
|---|---|---|---|
| §3.1 Session Export | not started | — | — |
| §3.2 Session-link copy | not started | — | — |
| §3.3 Input height memory | **already shipped (R137)** | (pre-cycle-2) | survey miss; corrected |
| §3.4 One-click copy (path / task_id) | not started | — | — |
| §3.5 Pause/resume v2 | deferred (conditional) | — | — |
| §3.6 Tool docstring LLM hinting | deferred (telemetry) | — | — |
| §4.1 zhconv evaluation | not started | — | — |
| §4.3 gemini-cli / claude-code survey | not started | — | — |

---

## 7. Suggested ordering for cycle-3

1. **Batch A (low-risk batch)**: §3.2 + §3.4 — share the
   clipboard helper. §3.3 dropped (already shipped). ~2 small
   commits + 1 batched test file. Plan ~0.5 day.
2. **Batch B (medium item)**: §3.1 Session Export — separate
   commit due to streaming + format-format dispatch + auth
   considerations. Plan ~1 day.
3. **§4.1 zhconv prototype** — non-shipping investigation; output
   is a `docs/zhconv-eval.md` go/no-go report.
4. **Code review after batches A + B** (5 commits = cr34
   trigger).

---

## 8. Related documents

- `docs/feature-mining-cycle-1.md` — cycle-1 backlog (all
  resolved)
- `docs/perf-audit-cycle-1.md` — backend perf audit
- `docs/code-reviews/cr30.md` ~ `cr33.md` — review history
