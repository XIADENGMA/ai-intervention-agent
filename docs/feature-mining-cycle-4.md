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

## §3 Track A — `claude-code` `additionalContext` template variables (planned)

### 3.1 What is it?

`claude-code` hooks expose template variables in the
`additionalContext` field of certain hook payloads. Variables
allow the user to interpolate runtime context (file paths, tool
names, working directory, etc.) into static templates without
writing code.

Adjacent to our `feedback_suffix` MCP option, which is currently
**static** — agent passes a fixed string that gets appended to
feedback. If we add **template variables**, agents could write:

```
feedback_suffix: "Continue when ready. Current working dir: {cwd}"
```

…and the Web UI / VSCode extension would expand `{cwd}` based on
the active task's context at render time.

### 3.2 Survey TODO (cr38 / cr39 cycle)

- [ ] Read `claude-code` hooks docs — enumerate full template
  variable list (need official source, GitHub repo, or release
  notes).
- [ ] Determine which variables are agent-side (resolved by
  claude-code itself) vs user-side (must be resolved by hook).
- [ ] Map each to potential equivalent in our context:
  - `{task_id}` — already exposed as URL hash
  - `{cwd}` — needs MCP server to expose `os.getcwd()` or read
    config workspace path
  - `{lang}` — needs i18n state from frontend (round-trip via SSE?)
  - `{user}` — needs OS user; trivial
  - `{timestamp}` — render-time; trivial
- [ ] Decide which 2-3 variables have **high enough** ROI to
  justify the schema + render-pipeline change.

### 3.3 Decision criteria

Borrow ✅ if:
- ≥ 3 distinct use cases where the template variable removes
  ambiguity from agent-side `feedback_suffix` string composition
- Variable can be resolved **server-side** (no frontend
  round-trip needed) — avoids latency / out-of-sync state
- Total LoC budget ≤ 150 (proportional to other §2.1 borrows)

Anti-pattern 🚫 if:
- Variable requires frontend round-trip (e.g. `{lang}` needs
  page state)
- Resolved at agent-side already (no benefit to add on our side)
- Encourages complex templating syntax that competes with
  Markdown / Jinja in feedback render path

Maybe 🤔 if:
- High ROI but requires architecture change (e.g. moving
  `feedback_suffix` render to client side)

## §4 Forward log (will fill as survey progresses)

| Date | Activity | Outcome |
|---|---|---|
| cr38 cycle open | mining-4 kickoff doc | this file |
| _TBD_ | Track A claude-code docs review | _TBD_ |
| _TBD_ | Track B mcp-feedback-enhanced HEAD compare | _TBD_ |
| _TBD_ | Track C gemini-cli sibling-tool survey | _TBD_ |
| _TBD_ | Track D aider/sweep interaction survey | _TBD_ |

## §5 Closeout criteria

Cycle-4 closes when **both**:

1. All 4 planned tracks have explicit `rg` + `git log` evidence
   recorded in §2.1 borrow/not-borrow table.
2. ≥ 1 ship-able borrow has been moved to "shipped" status
   _or_ all tracks documented as dry (with reasoning).

OR: cycle is **suspended** if v1.8.0 release work consumes the
cycle's budget (acceptable — release > new feature mining).

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
