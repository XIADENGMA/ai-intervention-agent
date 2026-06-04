# Feature Mining Cycle 5 — kickoff

> Status: **kickoff** · Opened in cr40 cycle
> Predecessor: `feature-mining-cycle-4.md` (closed in cr39)
> Methodology revision: **v3** (this cycle introduces v3)

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

| Track | Scope | Subject type | Rationale |
|---|---|---|---|
| **A** | `Continue.dev` interaction patterns (IDE plugin with mature feedback flow) | IDE plugin | diversification per §5.2 #3; mature in-IDE feedback UX |
| **B** | `Augment` / `Trae` / `Windsurf` quick-feedback UIs (popular AI IDEs we ship VSCode extension for) | IDE plugin | parity with our VSCode extension users' alternatives |
| **C** | Carry-over: `auto_resubmit: once` schema eval (mining-4 §3.4 adjacent) | own codebase | concrete cycle-5 ship candidate |
| **D** | Carry-over: aider / sweep interaction-loop conventions | IDE plugin | deferred from cycle-4 |
| **E** | v1.8.0 release window — promote `[Unreleased]` and cut tag | own codebase | cycle-4 §6 explicit defer; cycle-5 is the right window |

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

- [ ] `git tag -a v1.8.0 -m "Release v1.8.0"` (local only;
  user decides when to push)
- [ ] Generate GitHub release notes from `[1.8.0]` section
- [ ] (user-decision) Push tag → triggers PyPI + Open VSX +
  VSCode Marketplace publish CI

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
| _TBD_ | Track A Continue.dev survey | _TBD_ |
| _TBD_ | Track B AI-IDE survey (Augment / Trae / Windsurf) | _TBD_ |
| _TBD_ | Track C `auto_resubmit: once` eval + ship | _TBD_ |
| _TBD_ | Track D aider/sweep (deferred priority) | _TBD_ |
| _TBD_ | Track E v1.8.0 release | _TBD_ |

## §5 Closeout criteria

Cycle-5 closes when **all**:

1. All planned tracks have explicit evidence in §2.1
   (or marked deferred with reasoning)
2. ≥ 1 ship-able borrow has been moved to "shipped" status
   _or_ all tracks documented as dry (with reasoning)
3. **NEW for cycle-5**: v1.8.0 release tag created locally
   (Track E ship)

## §6 Adjacent / future-cycle candidates

Logged here so they don't get lost in TODO drift:

- **`once: true` semantics** (cycle-4 Track A adjacent finding,
  carried as Track C this cycle): one-shot vs perpetual
  auto-resubmit
- **Source-code dive budget** (cycle-4 §5.2 #2 lesson): allocate
  1 hour per high-priority track to read upstream source code
  beyond docs
- **Diversified niche exploration** (cycle-4 §5.2 #3): consider
  web-form designers (Typeform, Tally) and CLI REPLs (Click,
  Typer) for **non-AI** input UX patterns in future cycles
