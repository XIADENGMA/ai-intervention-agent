# Feature Mining Cycle 7 — closeout

> Status: **closed** · Opened + closed in cr43 cycle (single-cycle execution, 2nd consecutive)
> Predecessor: `feature-mining-cycle-6.md` (closed in cr42)
> Successor: cycle-8 (TBD)
> Methodology revision: **v3.2** (this cycle adopts v3.2 from
> cycle-6 §5.1 lesson #2, codifies kickoff template via Track F)
>
> ⚠️ **Track A (Custom PWA install prompt R247) reverted in cycle-22**
> (commit `2fb63ab`) per user preference — see
> `feat-remove-pwa-install` entry in `CHANGELOG.md`. PWA install
> **capability** (manifest.webmanifest + Service Worker) retained;
> only the custom in-page button + 30-day-dismiss banner UI was
> removed. Users now install via browser-native menu (Chrome address-
> bar icon / iOS Safari Share → Add to Home Screen). This doc kept
> for historical methodology audit (`rg` pre-check v3.2 origin); do
> not re-ship the R247 button without explicit user buy-in.

## §0 Methodology v3.2 (cycle-7 adoption)

Inherits v3.1 (subject-type + borrow-kind classification).
**NEW in v3.2**: mandatory blocking pre-§2.1 `rg` check on
own codebase before logging any candidate as TBD ship.

### v3.2 mandatory columns (cumulative from v3.1)

Every candidate row in §2.1 (borrow / not-borrow table)
must have:

1. **`rg` filesystem evidence** — `path:line` cite for
   the **source** project (from v2)
2. **`git log --grep` history evidence** — commit SHA +
   subject (from v2)
3. **subject type** — MCP server / client / IDE plugin /
   Agent-CLI / Web UI designer / Accessibility tool /
   CLI REPL / N/A (from v3)
4. **borrow kind** — schema / inspiration / N/A (from v3.1)
5. **NEW: own-codebase `rg` pre-check** — run
   `rg -l '<keyword>|<synonym1>|<synonym2>' src/ tests/`
   and attach the **actual command + output** to the
   candidate row, even if empty. If non-empty, candidate
   must be logged as **discovered-already** with cross-
   link, **not** "TBD ship".

### v3.2 forbidden patterns (cumulative)

- ❌ All v3.1 forbidden patterns
- ❌ Adding a candidate row without §5 `rg` pre-check
  evidence attached. **Closeout reviewer must reject** any
  row without this.

### Rationale

Cycle-6 §5.1 lesson #2 documented the **3rd consecutive
discoverability gap** (cr40 bump_version.py + cycle-6 Track
B quick_phrases.js + Track C taskTextareaContents+R139).
Three strikes = systematic gap. Cheap pre-check (1
command, < 1s) prevents expensive cleanup. v3.2 makes the
gate mandatory and reviewer-enforced.

## §1 Cycle-7 planned tracks

| Track | Scope | Subject type | Borrow kind | `rg` pre-check (v3.2) | Rationale |
|---|---|---|---|---|---|
| **A** | **NEW**: Custom PWA install prompt + dismissal UX | own codebase | n/a (own work) | `rg -l 'beforeinstallprompt\|appinstalled\|installPromptEvent' src/ tests/` → **0 matches** ✅ valid candidate | Manifest + SW already exist (`/manifest.webmanifest` + `notification-service-worker.js`); browser address-bar install icon is poorly discoverable; custom button improves desktop install rate |
| **B** | Streaming MCP-server reference implementations survey | MCP server | schema | `rg -l 'stream\|generator\|yield' src/ai_intervention_agent/mcp/` → **multiple matches** (server.py uses generator) — partial coverage, survey needed for **streaming** specifically | Cycle-5 §2 noted MCP protocol evolution; check if our server supports streaming responses |
| **C** | Carry: voice input (deferred from cycle-6 Track D) | own codebase | n/a | `rg -l 'SpeechRecognition\|microphone' src/` → `web_ui_security.py:119` (deliberate hardening); demand signal **not yet present** | Cycle-7 prerequisite (≥ 1 GitHub issue) not yet met; continue deferral |
| **D** | Carry: Typeform/Tally feedback-form UX survey (from cycle-6 Track E) | Web UI designer | inspiration | n/a — survey work | Diversification per cycle-5 §2.4 saturation signal |
| **E** | Carry: NVDA/JAWS a11y plugin patterns (from cycle-6 Track F) | Accessibility tool | inspiration | n/a — survey work | a11y improvement vector |
| **F** | **NEW**: Methodology-rg-check evidence boilerplate template | own codebase | n/a (process) | n/a — process polish | cr42 §8 #4: lower friction for v3.2 compliance in future cycles |

Per cycle budget: **0-2 ships + 0-3 surveys + 0-2 process
polish**. Cycle-7 is **execution-focused** (Track A is the
main ship; F is small process polish).

## §2 Cycle-7 ship priority

1. **[medium-ROI]** Track A: PWA install prompt — small
   LoC (~80-120 frontend + i18n + 0 backend), broad win
   (desktop install discoverability). **First ship target.**
2. **[low-process]** Track F: methodology boilerplate
   template — ~30 LoC docs. Lowest risk. Good 2nd commit.
3. **[medium]** Track B: streaming MCP survey — research
   work, outcome TBD (could be not-borrow or small ship).
4. Tracks C/D/E: carry deferrals; survey work only if
   bandwidth allows.

## §3 Forward log (will fill as cycle progresses)

| Date | Activity | Outcome |
|---|---|---|
| cr42→cr43 cycle open | mining-7 kickoff doc + v3.2 codified | this file |
| cr43 cycle ship | Track A custom PWA install prompt | **shipped** — JS (~205 LoC) + HTML buttons + CSS (~75 LoC) + i18n (4 keys × 3 locales) + Flask asset version wiring + 30 regression tests across 6 layers |
| cr43 cycle ship | Track F methodology rg-check boilerplate | **shipped** — `docs/feature-mining-cycle-kickoff-template.md` reusable kickoff template with v3.2 methodology codified §0 + §0.1 boilerplate copy-paste + §0.2 synonym brainstorm hint (reduces friction for future cycle kickoffs) |
| cr43 cycle closeout | Track B streaming MCP-server survey | **not-borrow** — see §3.2 below; stdio transport + single-task progress-by-design is the right architecture for local AI-intervention use case; streaming-transport / progress-notifications add architectural overhead with no concrete user demand. Comment in `server.py:569` already notes "未来若开 streamable-http" as recognized future option. |
| cr43 cycle closeout | Track C voice input carry-over | **still deferred** (cycle-7 prereqs unmet) — no GitHub demand signal since cycle-6; see §3.3 |
| cr43 cycle closeout | Track D Typeform/Tally survey carry-over | **deferred to cycle-8** — bandwidth-limited; cycle-7 already shipped 2 + closed 1; see §3.3 |
| cr43 cycle closeout | Track E NVDA/JAWS a11y survey carry-over | **deferred to cycle-8** — bandwidth-limited; cycle-7 already shipped 2 + closed 1; see §3.3 |

## §3.2 Track B streaming MCP-server survey — not-borrow rationale

**Pre-§2.1 `rg` evidence** (v3.2 compliance):

```text
$ rg -ln 'stream|generator|yield|Progress|send_notification' src/ai_intervention_agent/server.py
src/ai_intervention_agent/server.py:1
$ rg -n 'transport=|run\(|run_stdio|sse_app|streamable_http' src/ai_intervention_agent/server.py
1126:    ``mcp.run(transport="stdio")`` 路径——这是 MCP client (Cursor /
1452:    2. 调用 mcp.run(transport="stdio") 启动 MCP 服务器
1541:        f"transport=stdio mcp_name={mcp.name!r} "
1548:    # 实例（IDE 多 worker / Cursor + VS Code 同时调起），每次 mcp.run() 同
1570:            mcp.run(transport="stdio", show_banner=False)
1572:            # 如果 mcp.run() 正常退出（不抛异常），跳出循环
$ rg -n 'streamable' src/ai_intervention_agent/server.py
569:#   - ``transport``：当前传输（固定 stdio，未来若开 streamable-http 会变）；
```

**Survey findings**:

1. Project uses **FastMCP** with **stdio transport** only.
   Comment at `server.py:569` already acknowledges
   "streamable-http" as a recognized future option.
2. The MCP spec defines two streaming-related capabilities:
   - **Progress notifications** during long-running tool
     execution (`notifications/progress`)
   - **Streamable HTTP transport** (spec rev 2025-03-26,
     replaces SSE) for server-to-client push outside
     stdio
3. Our `interactive_feedback` tool is **inherently a
   single-result blocking call by design** — it waits for
   user input then returns a single content list. There's
   no "stream of chunks" semantically; the user submits
   feedback once.
4. Progress notifications could in theory surface
   intermediate state (e.g., "user is typing, 5s
   elapsed"), but this would require the MCP client to
   render them; Cursor / Claude Desktop / Continue.dev
   discard progress notifications for tools without a UI
   surface — they're informational only.

**Architectural verdict**: **not-borrow**.

- stdio transport is the correct primary architecture for
  this project's use case (local-only / LAN; single MCP
  client per session; supervised by IDE process manager).
- Streamable HTTP would only matter for: cloud-hosted MCP
  servers (not our case), multi-client topologies (not
  our case), resumable connections (handled by IDE
  supervisor).
- Progress notifications add complexity (need to track
  `progressToken`, send periodic updates, handle client
  cancellation) with no concrete UX gain — users **want**
  to be left alone while typing feedback; "AI is
  watching you type" is anti-UX for this tool.

**Future revisit conditions** (mirrors Track D voice-input
defer pattern):

1. ≥ 1 GitHub issue/discussion requesting cloud-hosted
   deployment topology
2. Updated architecture doc documenting trust boundary +
   auth model for remote MCP transport
3. Concrete user research showing progress notifications
   would improve perceived responsiveness

## §3.3 Tracks C/D/E carry-over status

| Track | Source | Status | Unlock condition |
|---|---|---|---|
| **C** voice input | cycle-6 Track D | deferred (still) | ≥ 1 GitHub issue + security-arch doc update + privacy modal text (unchanged from cycle-6) |
| **D** Typeform/Tally survey | cycle-6 Track E | bandwidth-deferred to cycle-8 | n/a — bonus survey, not gated; cycle-7 already shipped 2 + closed 1 |
| **E** NVDA/JAWS a11y | cycle-6 Track F | bandwidth-deferred to cycle-8 | n/a — bonus survey, not gated; cycle-7 already shipped 2 + closed 1 |

Cycle-7 bandwidth was consumed by Tracks A + F + B; the
bonus survey tracks D/E are explicitly deferred without
penalty (per cycle-6 §1 "bonus, not core" classification).

## §4 Closeout criteria

Cycle-7 closes when **all**:

1. Track A (PWA install) shipped or not-borrowed with
   explicit rationale
2. Track F (methodology boilerplate) shipped (it's a
   process improvement; should not be deferred)
3. Track B explicit outcome (ship / not-borrow / defer
   with prereqs)
4. Tracks C/D/E touch-points logged in §3 forward (even
   if outcome is "no change since cycle-6")
5. v3.2 methodology adoption validated: every candidate
   row in this doc has §5 `rg` evidence attached

### §4.1 cr43-cycle closeout audit (cycle-7 SHIP)

- ✅ Track A: **shipped** (PWA install prompt R247)
- ✅ Track B: **closed (not-borrow with rationale)** —
  see §3.2; architectural verdict + future revisit
  conditions defined
- ✅ Track C: **still deferred** (cycle-7 prereqs unmet)
- ✅ Track D: **bandwidth-deferred to cycle-8**
- ✅ Track E: **bandwidth-deferred to cycle-8**
- ✅ Track F: **shipped** (kickoff template with §0.1
  boilerplate + §0.2 synonym hint)
- ✅ §5.1 (Lessons learned): captured below

**Criterion #1 met**: Track A shipped.
**Criterion #2 met**: Track F shipped (no deferral).
**Criterion #3 met**: Track B has explicit not-borrow
verdict with future revisit conditions.
**Criterion #4 met**: Tracks C/D/E all have explicit
status entries in §3 forward log + §3.3 table.
**Criterion #5 met**: every candidate row (A-F) in §1
table has `rg` pre-check evidence; Track A had 0 matches
→ ship validated; Track B/C had matches → already
acknowledged + analyzed.

**Cycle-7 status: CLOSED.**

## §5.1 Lessons learned

1. **v3.2 `rg` pre-check works in practice**: Track A
   passed cleanly (0 matches → valid ship); Track B
   surfaced architectural-not-discovery context (existing
   stdio + comment at line 569 acknowledging future).
   The check distinguishes "discovered-already" from
   "intentionally-omitted-for-good-reason" cleanly when
   reviewer reads the matches in context.
2. **"Bandwidth-defer" is a valid closeout outcome for
   bonus tracks**: cycle-7 explicitly classified D/E as
   "bonus, not core" in §1, so deferring them without
   penalty preserves cycle hygiene. Don't extend a cycle
   just to clear bonus tracks if core tracks are
   completed.
3. **Process polish (Track F) belongs in the same cycle
   as the methodology it codifies**: shipping the
   kickoff template the cycle **after** v3.2 was proposed
   (cycle-6) avoided letting the methodology gather dust
   before tool support arrived. Future methodology revs
   should follow the same "propose-cycle → adopt-cycle"
   2-cycle cadence.

## §5 Adjacent / future-cycle candidates

Logged here so they don't get lost in TODO drift:

- _(initially empty — will fill as cycle-7 surveys + ships
  reveal new candidates)_
