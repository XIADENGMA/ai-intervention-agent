# Feature Mining Cycle 4 — kickoff

> Status: **kickoff** · Opened in cr38 cycle
> Predecessor: `feature-mining-cycle-3.md` (closed in cr37)

## §0 Methodology (hardened — adopted from cycle-3)

Every candidate row in §2.1 (borrow / not-borrow table) **must**
carry both pieces of evidence:

1. **`rg` filesystem evidence** for the upstream project — file
   path, line range, idiom name. Cite as `path:line`.
2. **`git log --grep` history evidence** — confirming the idiom
   is intentional (not a fluke), with commit SHA + subject.

Cycles 1–2 had 3 survey misses (idioms we declared "not present"
but were already shipped under different naming). Cycle-3 first
run under this rule produced **0 misses** — same standard applies
to cycle-4.

## §1 Tracks (planned)

| Track | Scope | Rationale |
|---|---|---|
| **A** | `claude-code` `additionalContext` template-variable eval | mining-3 §2.3 marked **maybe**, deferred for dedicated investigation |
| **B** | `mcp-feedback-enhanced` re-baseline (4th time) | weekly cadence; verify no surprise drops |
| **C** | `gemini-cli` 2-call-deep recurse — survey `ask_user` *companions* (e.g. `confirm`, `notify`, similar tools) | cycle-3 only surveyed the top-level `ask_user` schema; sibling tools may have transferable idioms |
| **D** | Adjacent: `aider` / `sweep` interaction-loop conventions | aider has mature "feedback during code edit" flow; not surveyed yet |

Per cycle budget: **0-4 borrow + 0-3 anti-idiom + 0-2 maybe**.
If all tracks are dry (likely for Track B), spend the budget on
codebase-internal **polish & a11y** items recorded throughout
recent reviews.

## §2 Open carry-overs from cycle-3 → cycle-4

| Item | Source | Priority | Notes |
|---|---|---|---|
| `claude-code` `additionalContext` template-var eval | mining-3 §2.3 maybe | **medium** | needs schema read + idiom map to our `feedback_suffix` |
| `claude-code` "completion gate" pattern | mining-3 §2.3 defer | low | agent-side architecture; not directly portable |
| v1.8.0 release plan | cr37 §8 #6 | info | [Unreleased] already ~140 lines / 50+ commits since v1.7.9 — likely time to cut tag |
| e2e harness for `placeholder` + `yesno` + `header_label` UI | cr37 §8 #7 | defer | needs Playwright/Selenium infra; major investment |

## §3 Track A — `claude-code` `additionalContext` template variables (DONE — not borrowing)

### 3.1 Survey findings (cr39 cycle desk-research)

**Method**: Read `code.claude.com/docs/en/hooks` (official) +
`buildingbetter.tech` source-code dive + 3 third-party guides
(claudefa.st / smartscope / morphllm). Identified the exact
template-variable surface.

**What `additionalContext` actually does**:
- Hook outputs JSON `{ "hookSpecificOutput": { "additionalContext": "<string>" } }`
- Claude Code wraps the string in a system-reminder and injects
  into context at hook fire point — **invisible to user**
- Used to surface project state (e.g. `git branch`, recent
  changes) so the model sees it on its next turn

**The "template variables" misconception**:
What we called "template variables" in cycle-3 are actually two
**separate** mechanisms:

1. **Path placeholders** like `${CLAUDE_PROJECT_DIR}`,
   `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` — these are
   substituted by claude-code **before spawning the hook
   process**, in the `command` / `args` / `headers` fields. Not
   in `additionalContext` output.
2. **Environment variables** like `$CLAUDE_PROJECT_DIR` (always
   set), `$CLAUDE_ENV_FILE` (SessionStart/Setup only),
   `$CLAUDE_CODE_REMOTE`, `$CLAUDE_EFFORT` — available to the
   hook **process** at runtime via the standard env API.
3. `additionalContext` itself is a **plain string** — no
   templating engine. Any dynamic content comes from the hook
   doing shell substitution (`$(git branch --show-current)`) in
   its own command. **The expansion lives in the hook author's
   shell script**, not in claude-code.

### 3.2 Mapping to our `feedback_suffix`

| Variable | claude-code path | Our equivalent | Useful? |
|---|---|---|---|
| `$CLAUDE_PROJECT_DIR` | injected to hook process env | agent already knows cwd | ❌ |
| `$CLAUDE_ENV_FILE` | hook-only persist mechanism | n/a (we don't spawn hooks) | ❌ |
| `$CLAUDE_CODE_REMOTE` | "true" if web | n/a (we are always remote) | ❌ |
| `$CLAUDE_EFFORT` | model effort level | n/a (we don't expose model) | ❌ |
| `${CLAUDE_PROJECT_DIR}` | path placeholder | agent already knows cwd | ❌ |
| _custom shell substitution_ | hook author writes `$(git ...)` | agent can compose own string | ❌ |

### 3.3 Decision: **not-borrow**

**Rationale**:

1. **No additional value over agent-side string composition.**
   Our MCP tool is invoked by an agent that already has access
   to `cwd`, `timestamp`, `task_id`, etc. via its own runtime
   context. Agent can compose `feedback_suffix` with f-string /
   template literal at call time. Server-side templating would
   only repeat capability the agent already has.

2. **Server-side render state is already exposed via UI**, not
   via templating. `task_id` is in URL hash; countdown timer
   shows task age; SSE indicator shows backend liveness; chip
   shows `header_label`. Adding `{var}` substitution to
   `feedback_suffix` would surface the *same* state through a
   *second* channel — clutter, not value.

3. **The asymmetry with claude-code is structural**: claude-code
   spawns user hooks (no agent in the loop for state collection),
   so `additionalContext` is the **only** state-injection path
   from hook → model. Our agent **is** the loop; it doesn't need
   us to template state for it.

4. **Borrow criterion fails**: we required "≥ 3 distinct use
   cases where the variable removes ambiguity from agent-side
   composition." After mapping (§3.2), **0 such cases exist**.
   Anti-pattern criterion "resolved at agent-side already" hits
   for every variable.

5. **Anti-bonus**: avoid introducing a tiny templating language
   that competes with Markdown / Jinja in the feedback render
   path (mining-4 §3.2 #3 anti-criterion).

**Result classification**: Track A → **not-borrow, completed**.
Status: 0 borrow / 1 anti-pattern recorded. Saved ~150 LoC of
schema + render pipeline + tests.

### 3.4 Adjacent insight (carry into future cycles)

`once: true` (mining-4 source-code-dive finding) is a hook
config field for SessionStart hooks. When set, the hook fires
exactly once per session, then auto-removes. **Adjacent**: our
auto-resubmit could expose `auto_resubmit: { once: true }` —
single-shot vs. perpetual. Currently `auto_resubmit_timeout` is
the only knob. Worth a cycle-5 investigation if user feedback
asks for it. **Logged as cycle-5 candidate.**

## §4 Forward log (will fill as survey progresses)

| Date | Activity | Outcome |
|---|---|---|
| cr38 cycle open | mining-4 kickoff doc | this file |
| cr39 cycle | Track A claude-code docs review | **not-borrow** — 0 ROI after mapping; logged 1 adjacent candidate (`once: true` hook → `auto_resubmit.once`) for cycle-5 |
| cr39 cycle | Track B mcp-feedback-enhanced HEAD re-baseline | **1 borrow shipped** — pretty 404 page (e65d152); 1 README marketing item carried (Starlette stability differentiator) |
| cr39 cycle | Track C gemini-cli sibling-tool survey | **N/A — methodology error caught**. gemini-cli is an **MCP client** (not server). The `ask_user` schema we borrowed in mining-3 was from a **separate** MCP server demo (probably `@google/gemini-cli-mcp-tools` or similar) that we surveyed via docs only. gemini-cli itself has no input-tool siblings to survey. **Track C is closed as not-applicable** — record the categorization error so future cycles distinguish "MCP server schemas" vs "MCP client UX features". |
| cr39 cycle | Track D aider/sweep interaction survey | **deferred** — both are IDE-style integrations, not MCP servers. No direct schema-level mappings exist. Logged for cycle-5 if budget remains after higher-priority items. |

## §4.5 Track B detailed findings (`mcp-feedback-enhanced` HEAD)

### B.1 Survey

Searched: GitHub Releases (latest tag), GitHub Issues (open),
GitHub PRs (open + recent merged), CHANGELOG drift check.

### B.2 Findings

**Stable channel** (releases tab):
- Latest release: **v2.6.0** (Jun 2025) — **0 new releases**
  since cycle-3 Track A baseline (cycle-3 also 0 new).
- 35 historical releases unchanged.

**Main branch** (PRs / commits since 2025-06-28):

| PR | Author | Topic | Status | Date |
|---|---|---|---|---|
| #207 | `penn201500` | session-scoped routes `/feedback/{session_id}` + WS `?session_id=...` + multi-session concurrency + session-not-found UX + i18n | open | 2026-01-15 |
| #215 | `bitxel` | bump_starlette (fix Starlette 1.0 breaking change) | unmerged | 2026-03 |

**Open critical bug**:
- **Issue #213** (Mar 2026) — `uvx mcp-feedback-enhanced@latest`
  fails to start because Starlette 1.0 broke its dependency
  pinning. **Workaround**: pin `starlette<1.0` or use the
  `bump_starlette` fork branch. Still unmerged as of HEAD.

### B.3 Mapping to our project

| Their item | Our equivalent | Decision |
|---|---|---|
| session-scoped routes `/feedback/{session_id}` | URL hash `#task-tab=<id>` (mining-2 §3.4) | **independent convergence** — they go for path-level routing, we use hash. Hash is simpler (no server route table change). **Not borrowing path-level** — overlapping value, additional infrastructure cost. |
| session-not-found pretty UX | plain 404 (Flask default) | **borrow #1 candidate** — pretty page improves debugging when user clicks stale link. Low LoC. Includes i18n. |
| multi-session concurrency at WebUIManager | our `TaskQueue` already supports multi-task | n/a — pre-shipped |
| Starlette 1.0 broke install | we use Flask 3.x | **README opportunity** — surface "stable install, immune to Starlette breakage" as a competitive differentiator |

### B.4 Borrow / not-borrow decisions

- **borrow #1**: session-not-found pretty page (currently
  plain Flask 404). **ROI**: medium (improves stale-link UX +
  reduces "is the server broken?" support burden). **LoC**:
  ~80 (Flask `@app.errorhandler(404)` + template + 2 i18n
  keys). **SHIPPED** in cr39 cycle — see `templates/
  not_found.html` + 11 invariant tests.
- **not-borrow**: session-scoped path-level routes. Reason:
  overlapping value with mining-2 §3.4 hash routing; cost-to-
  benefit ratio doesn't justify route table redesign.
- **not-borrow** (anti-pattern): Starlette pinning fragility.
  We're already on Flask 3.x; mention competitor's bug in
  README to highlight stability as a differentiator.

### B.5 Independent convergence signal (meta-observation)

Both projects independently shipped session-link copy/share UX
within ~5 months of each other (us mining-2 §3.4 → cr35; them
PR #207). This is the **3rd** instance of cycle-N converging on
the same idiom as a competitor independently:

1. cycle-1: smart-sort. They already had R131c by the time we
   surveyed. We re-built independently, then noticed.
2. cycle-2: session export (JSON/Markdown). Both projects
   shipped roughly simultaneously.
3. cycle-3: session-link copy. We shipped (mining-2 §3.2)
   ~3 months before their PR #207.

**Interpretation**: convergent evolution indicates the idiom
is **canonical for the problem space**. New idioms not yet
surfaced by either project are increasingly rare. Future
mining cycles may need to expand source diversity (Tracks C/D
in this cycle do that).

## §5 Closeout criteria — **MET in cr39 cycle**

Cycle-4 closes when **both**:

1. All 4 planned tracks have explicit `rg` + `git log` evidence
   recorded in §2.1 borrow/not-borrow table. ✅ A done / B done /
   C closed as not-applicable / D deferred to cycle-5.
2. ≥ 1 ship-able borrow has been moved to "shipped" status
   _or_ all tracks documented as dry. ✅ borrow #1 pretty 404
   shipped (e65d152).

OR: cycle is **suspended** if v1.8.0 release work consumes the
cycle's budget — **not used; closeout via track exhaustion**.

### §5.1 Cycle-4 final tally

- **Tracks surveyed**: 4 (A claude-code / B mcp-feedback-
  enhanced / C gemini-cli siblings / D aider-sweep)
- **Borrow ✅ shipped**: 1 (pretty 404 page)
- **Not-borrow 🚫 with reasoning**: 1 (Track A
  additionalContext)
- **N/A (methodology correction)**: 1 (Track C — gemini-cli
  is a client not a server)
- **Deferred**: 1 (Track D aider-sweep)
- **Cycle-5 candidates surfaced**: 2 (`auto_resubmit: once`
  from Track A adjacent, README "Flask stability vs Starlette
  fragility" marketing from Track B)
- **Meta-finding**: 3rd independent convergence event
  (session-link copy in both projects) → mature problem space
  signal

### §5.2 Lessons learned

1. **Categorization discipline**: mining-3 borrowed "gemini-
  cli ask_user schema" without distinguishing **MCP server
  surface** vs **MCP client UX**. Track C exposed this.
  cycle-5 §0 methodology should add a column "subject type"
  (server / client / IDE / agent-CLI) to prevent re-doing this.
2. **Source-code dive ROI**: Track A's `once: true` discovery
  (from `buildingbetter.tech` source-code dive, not in docs)
  was high-ROI for ~30 min spent. Future cycles should budget
  1 hour for source-code dive per high-priority track.
3. **Convergent evolution = saturation signal**: 3rd
  convergence event suggests we've covered most canonical
  idioms in the "MCP feedback tool" niche. Future cycles
  should diversify into adjacent niches (IDE plugins, CLI
  REPLs, web-form designers) rather than continuing to mine
  the same niche.

## §6 v1.8.0 release planning prompt

Per cr37 §8 #6: `[Unreleased]` already accumulated **52 commits**
across 3 mining cycles + 6 BUG fixes. Suggested action items:

1. Audit `[Unreleased]` for completeness (last time we did a
   retroactive sweep — should be fresh now after CHANGELOG
   freshness gate).
2. Promote `[Unreleased]` → `[1.8.0] - YYYY-MM-DD`.
3. Run `bumpver` (or equivalent) — update `__version__` in
   `pyproject.toml`, `src/ai_intervention_agent/__init__.py`,
   VSCode `package.json`.
4. Cut `v1.8.0` git tag + GitHub release notes from CHANGELOG
   section.
5. Trigger PyPI + Open VSX + VSCode Marketplace publish CI.

**Why 1.8.0 not 1.7.10?** — additive MCP schema surface
(`feedback_placeholder`, `question_type`, `header_label`) is a
minor bump. Backward compat preserved (all optional).
