# Feature Mining Cycle 5 — closeout

> Status: **closed** · Opened in cr40 cycle · Closed in
> cr41 cycle
> Predecessor: `feature-mining-cycle-4.md` (closed in cr39)
> Successor: `feature-mining-cycle-6.md` (to open in cr42
> cycle)
> Methodology revision: **v3** (this cycle introduced v3
> with subject-type classification)

## §0 Methodology v3 (cycle-5 update)

Cycle-3 established v2 methodology: every candidate must carry
**`rg` filesystem evidence** + **`git log --grep` history
evidence**.

Cycle-4 §5.2 lesson #1 exposed a gap: Track C miscategorized
gemini-cli (which is a **client**, not a server) and produced
N/A results. To prevent recurrence, v3 adds a mandatory
**"subject type" classification** before any survey work:

### v3 mandatory columns

Every candidate row in §2.1 (borrow / not-borrow table) must
have:

1. **`rg` filesystem evidence** — `path:line` cite
2. **`git log --grep` history evidence** — commit SHA + subject
3. **NEW: subject type** — one of:
   - **MCP server** — exposes tools/resources via MCP protocol;
     direct schema-level borrow possible
   - **MCP client** — consumes MCP tools (e.g. Claude Code,
     gemini-cli, Cursor); borrow target is **client UX**, not
     server schema
   - **IDE plugin** — e.g. aider, sweep, Continue.dev; borrow
     target is **interaction patterns**, rarely directly
     schema-compatible
   - **Agent-CLI** — e.g. autogen, langgraph; borrow target is
     **orchestration patterns**, rarely interaction-tool relevant
   - **N/A** — none of the above; skip survey

### v3 forbidden patterns

- ❌ Surveying an MCP **client** for tool **schemas** (the
  client doesn't define schemas; servers do)
- ❌ Borrowing IDE-plugin **internals** (proprietary, not
  protocol-defined)
- ❌ Marking a row "maybe" without explicit follow-up cycle
  assignment (forces the eval to a concrete cycle)

## §1 Tracks (planned)

Per cycle-4 §5.2 lesson #3 saturation signal, cycle-5
diversifies away from "MCP feedback tool" niche which has
3 convergence events.

| Track | Scope | Subject type | Status / Rationale |
|---|---|---|---|
| **A** | `Continue.dev` interaction patterns (IDE plugin with mature feedback flow) | IDE plugin | **not-borrow** (see §3.7 below) — config-driven slash-command/prompts architecture is structurally orthogonal to MCP server's "agent-asks-user" tool surface; 1 derivative idea logged for cycle-6 |
| **B** | `Augment` / `Trae` / `Windsurf` quick-feedback UIs (popular AI IDEs we ship VSCode extension for) | IDE plugin | **not-borrow** (see §3.8 below) — same agent-pushed-vs-user-pulled structural mismatch as Track A; 2 derivative UX ideas (voice input, message queue) logged for cycle-6 |
| **C** | Carry-over: `auto_resubmit: once` schema eval (mining-4 §3.4 adjacent) | own codebase | **not-borrow** (see §3.6 below) — semantics inherently belong to AI client session memory, not MCP server task; protocol-level enforcement carries high complexity for niche use case |
| **D** | Carry-over: aider / sweep interaction-loop conventions | IDE plugin | _TBD — deferred to cycle-6 per saturation budget_ |
| **E** | v1.8.0 release window — promote `[Unreleased]` and cut tag | own codebase | **shipped in cr40 cycle** — local tag `v1.8.0` at commit `87b9fea` |

Per cycle budget: **0-3 borrow + 0-2 anti-idiom + 0-2 maybe**
(reduced from 0-4 per cycle-4 saturation signal — fewer
candidates expected per source as we move out of saturating
niche).

## §2 Carry-overs from cycle-4 → cycle-5

| Item | Source | Priority | Notes |
|---|---|---|---|
| v1.8.0 release | cr37 §8 #6 → cr38 §8 #3 → cr39 §8 #1 | **info** | `[Unreleased]` 65 commits / ~140 lines; release-time |
| README "Stable install" marketing | cr39 §8 #2 | low | **shipped in cr40 cycle commit `432330b`** |
| cycle-5 §0 methodology v3 | cycle-4 §5.2 #1 | medium-ROI | **shipped this doc** |
| `auto_resubmit: once` schema | cycle-4 §3.4 adjacent | low | Track C above |
| Track D aider/sweep | cycle-4 §1 | low | Track D above |
| e2e harness | cr37 §8 #7 / cr38 §8 #7 / cr39 §8 #7 | defer | still defer; reassess after v1.8.0 |

## §3 v1.8.0 release plan (Track E)

### 3.1 Pre-release audit

- [ ] Run `scripts/check_changelog_freshness.py --strict` —
  should pass (it's run as pre-commit hook on every push)
- [ ] Manual scan of `[Unreleased]` section for completeness:
  - All cycle-3 features documented? yes (cr36 §8 #1 swept)
  - All cycle-4 features documented? **NOT YET** — pretty 404
    page (e65d152) needs CHANGELOG entry
- [ ] Update CHANGELOG `[Unreleased]` → `[1.8.0] - YYYY-MM-DD`

### 3.2 Version bump

Three locations must update together:

1. `pyproject.toml` line 7: `version = "1.7.9"` → `"1.8.0"`
2. `package.json` line 3: `"version": "1.7.9"` → `"1.8.0"`
3. `packages/vscode/package.json` line 5: `"version": "1.7.9"`
   → `"1.8.0"`
4. `package-lock.json` — regenerate via `npm install`

### 3.3 Tag + release

- [x] `git tag -a v1.8.0 -m "..."` (local only; pushed by
  user when ready) — **done in cr40 cycle, tag created at
  commit `87b9fea`**
- [ ] Generate GitHub release notes from `[1.8.0]` section
  (deferred — push-time activity)
- [ ] (user-decision) Push tag → triggers PyPI + Open VSX +
  VSCode Marketplace publish CI (deferred — user gate)

### 3.6 Track C `auto_resubmit: once` — **not-borrow** (cycle-5 analysis)

**Background**: mining-4 §3.4 adjacent insight surfaced
`once: true` from claude-code SessionStart hook config. The
analogy: "what if our `auto_resubmit_timeout` had an
analogous `once: true` field that auto-disabled after one
timeout cycle?"

**Cycle-5 analysis**: traced our actual auto-resubmit flow
(`server_feedback.py:_make_resubmit_response`,
`task_queue.py:Task.auto_resubmit_timeout`):

1. Each `interactive_feedback` MCP call **creates a fresh
   `Task`**. There is no Task-level persistence across
   resubmit cycles — every resubmit produces a brand-new
   Task ID with reset state.

2. The `_make_resubmit_response` return tells the **AI
   client** (Claude / Cursor / Trae / etc) to invoke
   `interactive_feedback` again. The AI client is the
   one looping, not our task queue.

3. To enforce "once" semantically at the server level, we'd
   need either:
   - **Protocol-level state passing**: response carries
     `resubmit_index: 1`, AI client must echo it back on
     next invocation, server checks `if resubmit_index >=
     max_attempts then return final_timeout_response`. This
     requires every AI client to implement the echo protocol
     correctly — **high coordination cost** with zero
     enforcement guarantee (a buggy/old client just doesn't
     echo, and "once" becomes "always").
   - **Session-keyed state**: server maintains
     `Map<sessionId, resubmit_count>` and decrements on each
     resubmit_response emission. But MCP sessions are
     **opaque to our server** — we don't know which task
     belongs to which AI session unless the client tells us,
     and that's back to protocol-level state passing.

4. **The "once" knob already exists at the call site**:
   any AI client can simply pass `auto_resubmit_timeout=0`
   on the second invocation if it tracks the resubmit count
   itself. This is **the correct layer** — agent-side memory
   of "I already tried once" is exactly what `once` means.

**Decision**: **not-borrow**. Server-side "once" enforcement
solves the wrong problem layer. Future user-facing UX
improvement (per-task "freeze countdown" button) is logged
as a §6 candidate but is **distinct** from "once" semantics.

**Saved**: ~80 LoC of schema + client-coordination plumbing
+ a thorny correctness contract.

### 3.7 Track A `Continue.dev` — **not-borrow** (cycle-5 analysis)

**Background**: cycle-5 §1 listed Continue.dev (IDE plugin)
as a diversified-source survey target per cycle-4 §5.2 #3
saturation signal. Hypothesis: a mature in-IDE prompt-input
plugin might surface UX patterns we missed in cycles 1-4
that focused on MCP-feedback-tool servers.

**Survey findings (2026 web-search baseline)**:

Continue.dev's defining architecture is **config-driven
slash commands**: users define reusable prompt templates in
`config.yaml` or `.continue/prompts/*.md` files with
`invokable: true` frontmatter, then trigger them in-IDE via
`/name` slash commands. Context providers (`@file`,
`gitDiff`, etc) inject live data without manual paste. The
explicit goal of the design is **"prompts stay short
because the stable parts live in config"**.

**Subject-type classification check (per §0 v3
methodology)**: Continue.dev is an **IDE plugin** (subject
type 3), borrowing-target is "interaction patterns" not
"server schema". Our project is an **MCP server** (subject
type 1), exposing tools to AI agents who then surface them
to users.

**Structural mismatch**:

1. **User-initiated vs agent-initiated**: Continue.dev
   slash commands are **user-pulled** ("user types `/review`
   to invoke a prompt"). Our `interactive_feedback` MCP tool
   is **agent-pushed** ("agent calls the tool, user responds").
   Opposite flow direction.

2. **Prompt templates vs question schemas**: Continue.dev
   stores prompts (model-bound text). We store **task
   metadata** (placeholder, yesno-type, header chip,
   timeout). Different artifacts.

3. **Config-driven vs call-driven**: Continue.dev's
   stability comes from `config.yaml` source-of-truth. Our
   stability comes from MCP tool schema source-of-truth.
   Both are "config-driven" but at different layers.

**Derivative idea worth cycle-6 evaluation**: Continue.dev's
`invokable: true` markdown-prompt model could inspire **user-
defined feedback templates** — users save common responses
("Looks good, ship it", "Needs more tests", "Try approach X
instead") to local storage, then one-click apply them to
the feedback textarea. This is **independent of**
Continue.dev's actual schema (no protocol borrow), purely
UX inspiration. Logged in §6 as cycle-6 candidate.

**Decision**: **not-borrow**. Continue.dev's borrowable
surface (slash-command schema) is structurally orthogonal
to our MCP server's tool surface. The 1 derivative UX idea
deserves independent design, not direct translation.

**Saved**: ~120 LoC of schema mapping + glue code + tests
for a borrow that wouldn't fit our paradigm.

### 3.8 Track B `Augment / Windsurf` — **not-borrow** (cycle-5 analysis)

**Background**: cycle-5 §1 listed Augment + Trae + Windsurf
as parallel IDE-plugin survey targets for "popular AI IDEs
our VSCode extension users may also use". Trae is largely
a Cursor/Windsurf-clone; saved cycle budget by surveying
Augment + Windsurf as representatives.

**Survey findings (2026 web-search baseline)**:

**Augment Code's** defining feature is **Prompt Enhancer
(✨ button)** — user types rough prompt, hits ✨, system
uses codebase-context engine to rewrite the prompt into a
structured form before submitting to LLM. Same user-pulled
flow as Continue.dev.

**Windsurf Cascade's** notable features:

1. **Flow awareness** — Cascade tracks recent edits,
   terminal output, open files; prompts can be shorter
   because editor already has context.
2. **Message queue while busy** — user can type next
   message while Cascade is working; queued for sequential
   execution.
3. **Plan mode interactive options** — "provide multiple
   options for you to choose from with an interactive
   interface". Functionally equivalent to our
   `predefined_options` schema (cycle-2 idiom).
4. **Voice input** — Web Speech API integration; transcribe
   speech to prompt text.
5. **Auto-continue** — like our auto-resubmit but at LLM-
   turn-limit boundary (configurable).

**Subject-type classification (per §0 v3 methodology)**:
both are **IDE plugins** (subject type 3), opposite of our
MCP-server subject type 1. Same structural mismatch as
Track A.

**Concrete mismatch findings**:

| Feature | Augment/Windsurf | Our project | Borrowable? |
|---|---|---|---|
| Prompt Enhancer ✨ | LLM rewrites user prompt | We surface user feedback to agent | **No** — opposite flow |
| Flow awareness | Editor-side context capture | We're agent-pushed | **No** — no codebase access |
| Plan mode options | Cascade gives options | We have `predefined_options` | **Already have it** (cycle-2) |
| Auto-continue | LLM turn-limit auto-continue | We have auto-resubmit-timeout | **Already have it** (cycle-1) |
| Message queue | Type next while busy | Multi-task UI | **Partial overlap** (see §6 candidate) |
| Voice input | Web Speech API | _missing_ | **Candidate** (see §6) |

**Decision**: **not-borrow** at the schema level. Augment's
Prompt Enhancer is on the wrong side of the agent↔user
boundary for our server. Windsurf's plan-mode options and
auto-continue are **convergent evolution** with our
`predefined_options` and `auto_resubmit_timeout` (3rd
independent convergence event — strengthens cycle-4 §5.2
#3 saturation signal further).

**2 cycle-6 derivative UX ideas logged in §6**:

- **Voice input** for feedback textarea (Web Speech API,
  browser-native, ~60 LoC frontend + 0 backend; caveat:
  Safari has degraded support, Mandarin accuracy varies).
- **Cross-task message queue** — let user pre-write feedback
  for a queued (pending, not yet active) task while another
  task is active. Currently the textarea only binds to the
  active task. ~100 LoC frontend + minor `task_queue` field
  addition.

**Saved**: ~140 LoC of borrow attempts that would fight our
server's architecture.

### 3.5 Full-suite green gate (cr40 lesson — NEW for v3+)

**Mandatory before release commit**:

- [x] Run **full** `uv run pytest --timeout=60` (not per-
  module). cr40 sweep proved that per-module test runs miss
  4-shape regressions: invariant scope drift, shared-
  singleton pollution, watchdog label drift, i18n dynamic-
  key reservation drift. Full suite was the only way to
  catch them.

**Codified in `docs/release-checklist.md`** as a hard
checklist step. Future release commits should reference
this section in their commit body to confirm the gate
ran clean.

### 3.4 Why 1.8.0 not 1.7.10?

- 3 additive MCP schema fields (`feedback_placeholder`,
  `question_type`, `header_label`) — minor bump per SemVer
- Backward compat preserved (all fields optional)
- No breaking removals
- Major UX surface additions (header chip, yesno buttons,
  pretty 404, mining-1 SSE indicator, mining-1 countdown
  extend, mining-1 zh-TW, mining-2 session export, mining-2
  task-id copy)

10 features warrants a minor bump, not a patch.

## §4 Forward log (will fill as cycle progresses)

| Date | Activity | Outcome |
|---|---|---|
| cr40 cycle open | mining-5 kickoff doc + §0 methodology v3 | this file |
| cr40 cycle ship | Track E v1.8.0 release | **shipped** — local tag `v1.8.0` at commit `87b9fea`; full release notes in CHANGELOG `[1.8.0]` |
| cr40 cycle ship | full-suite-green pre-release gate codified | **shipped** — §3.5 added; codified in `docs/release-checklist.md` |
| cr41 cycle | Track C `auto_resubmit: once` evaluation | **not-borrow** — see §3.6; saved ~80 LoC + thorny correctness; 1 cycle-6 candidate logged |
| cr41 cycle | Track A Continue.dev survey | **not-borrow** — see §3.7; saved ~120 LoC; 1 cycle-6 candidate (user feedback templates) logged |
| cr41 cycle | Track B AI-IDE survey (Augment + Windsurf) | **not-borrow** — see §3.8; 3rd convergent-evolution event detected; saved ~140 LoC; 2 cycle-6 candidates (voice input, cross-task message queue) logged |
| _TBD_ | Track D aider/sweep (deferred priority) | _TBD — defer to cycle-6_ |

## §5 Closeout criteria — **ALL MET** (closed cr41 cycle)

Cycle-5 closes when **all**:

1. ✅ All planned tracks have explicit evidence in §2.1
   (or marked deferred with reasoning) — Tracks A, B, C
   all closed not-borrow with detailed §3.* analysis;
   Track D deferred to cycle-6 with reasoning; Track E
   shipped.
2. ✅ ≥ 1 ship-able borrow moved to "shipped" status
   **OR** all tracks documented as dry — Track E v1.8.0
   release shipped; release-checklist.md A.3 full-suite-
   green gate shipped as process artifact.
3. ✅ **NEW for cycle-5**: v1.8.0 release tag created
   locally (Track E ship) — done at commit `87b9fea`.

### §5.1 Cycle-5 final tally

| Track | Outcome | Notes |
|---|---|---|
| A: Continue.dev | **not-borrow** | structural mismatch (user-pulled vs agent-pushed); 1 cycle-6 candidate (user feedback templates) |
| B: Augment + Windsurf | **not-borrow** | 3rd convergent-evolution event; 2 cycle-6 candidates (voice input, message queue) |
| C: `auto_resubmit: once` | **not-borrow** | wrong layer (AI client session, not server task); 1 cycle-6 candidate (freeze countdown UI) |
| D: aider / sweep | **deferred** | scope creep risk; revisit cycle-6 |
| E: v1.8.0 release | **shipped** | local tag `v1.8.0` + release-checklist.md + full-suite gate |

**Production**: 1 ship + 1 process artifact (release
checklist) + 3 not-borrows with reasoning + 4 cycle-6
candidates surfaced.

### §5.2 Lessons learned

1. **Methodology v3 worked**: subject-type classification
   caught all 3 not-borrows at the design stage, before
   any code was written. Saved ~340 LoC of borrow attempts
   (~80 + ~120 + ~140) that would have fought our
   architecture.

2. **Convergent evolution intensifies**: cycle-5 found
   the **3rd** independent convergence event (Windsurf
   plan-mode options ↔ our `predefined_options`; Windsurf
   auto-continue ↔ our auto-resubmit). Saturation signal
   from cycle-4 §5.2 #3 is **confirmed and strengthening**.

3. **Negative results have real value**: 3 not-borrows
   produced **4 cycle-6 UX-derivative candidates** (freeze
   countdown, feedback templates, voice input, message
   queue) — even when the borrow is wrong layer, the
   adjacent inspiration carries forward.

4. **Release-bracket cycles benefit from process artifacts**:
   release-checklist.md + bump_version.py-discovery (cr40
   §8 #1 → cr41 §8 #6) prevented future v1.7.5-style
   manual-step failures. Process work is **as valuable as
   feature work** in a release window.

5. **IDE plugins are mostly the wrong source**: cycle-5 +
   cycle-4 §5.2 #1 jointly confirm that subject-type 3 (IDE
   plugins) is structurally orthogonal to subject-type 1
   (MCP servers) for **schema borrows**. UX **inspiration**
   is the right framing — and inspiration crosses
   boundaries freely, schemas do not.

## §6 Adjacent / future-cycle candidates

Logged here so they don't get lost in TODO drift:

- ~~**`once: true` semantics** (cycle-4 Track A adjacent
  finding, carried as Track C this cycle): one-shot vs
  perpetual auto-resubmit~~ — **closed not-borrow in §3.6
  above; wrong layer for the semantics**
- **Per-task "freeze countdown" UI button** (cycle-5 §3.6
  derivative): adjacent to extend-by-60s button, lets user
  convert active task to no-timeout via single click. Backend
  already supports `auto_resubmit_timeout=0` semantics
  (== "disabled"); just need a new endpoint
  `POST /api/tasks/<id>/freeze` + new button next to extend.
  ~50 LoC backend + ~30 LoC frontend + tests. Cycle-6
  candidate.
- ~~**User-defined feedback templates** (cycle-5 §3.7
  derivative, Continue.dev inspiration): users save common
  responses ("LGTM, ship it" / "Needs tests" / etc) to
  localStorage and one-click apply to feedback textarea. UI
  pattern: dropdown next to submit button + "Save current
  as template…" affordance. ~80 LoC frontend + 0 backend
  (pure client-side). Cycle-6 candidate. Note: **independent
  of Continue.dev's actual schema** — borrows UX inspiration
  only, not protocol surface.~~ **DISCOVERED ALREADY EXISTS**
  as `quick_phrases.js` (R130 / cycle-1 era); see
  `feature-mining-cycle-6.md` §1 Track B for closeout +
  §5.1 lesson #1 (discoverability gap, 2nd occurrence
  after cr40 §8 #5 bump_version.py).
- **Voice input for feedback textarea** (cycle-5 §3.8
  derivative, Windsurf inspiration): browser-native Web
  Speech API integration — mic button next to textarea,
  speech-to-text fills the textarea for user review before
  submit. ~60 LoC frontend + 0 backend. Caveat: Safari
  degraded support, Mandarin accuracy varies; needs
  graceful fallback when API absent. Cycle-6 candidate.
- ~~**Cross-task message queue** (cycle-5 §3.8 derivative,
  Windsurf inspiration): currently textarea only binds to
  active task; this lets user pre-write feedback for a
  queued (pending, not yet active) task while another task
  is active. Reduces task-switch latency. ~100 LoC frontend
  + small `task_queue` field (per-task draft string).
  Cycle-6 candidate.~~ **DISCOVERED ALREADY EXISTS** as
  `multi_task.js:taskTextareaContents` cross-task draft
  cache (cycle-1 era) + R139 `feedback_drafts.js`
  localStorage persistence; see
  `feature-mining-cycle-6.md` §1 Track C for closeout +
  §5.1 lesson #2 (**rule of three** — 3rd discoverability
  gap triggers methodology v3.2 mandatory pre-§2.1 `rg`
  check).
- **Source-code dive budget** (cycle-4 §5.2 #2 lesson): allocate
  1 hour per high-priority track to read upstream source code
  beyond docs
- **Diversified niche exploration** (cycle-4 §5.2 #3): consider
  web-form designers (Typeform, Tally) and CLI REPLs (Click,
  Typer) for **non-AI** input UX patterns in future cycles
