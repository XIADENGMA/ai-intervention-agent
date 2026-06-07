# Feature Mining Cycle 9 — closeout

> Status: **closeout** · Opened + closed in cr45 cycle (4th
> consecutive single-cycle execution; v3.2 + template
> validated 4 cycles in a row)
> Predecessor: `feature-mining-cycle-8.md` (closed in cr44)
> Methodology revision: **v3.2** (current; carried over from cycle-8)
> Template source: `feature-mining-cycle-kickoff-template.md` (2nd cycle authored via template)

## §0 Methodology v3.2 (current)

Inherits v3.1 (subject-type + borrow-kind classification).
**v3.2 codified rule** (cycle-6 §5.1 lesson #2): mandatory
blocking pre-§2.1 `rg` check on own codebase before logging
any candidate as TBD ship.

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
5. **own-codebase `rg` pre-check** — run
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

## §1 Cycle-9 planned tracks

Per cr44 §4 lesson #3 ("3rd consecutive single-cycle =
default"), cycle-9 is **scope-restricted** to ≤ 4 tracks
matching the cycle's maturity stage.

| Track | Scope | Subject type | Borrow kind | `rg` pre-check (v3.2) | Rationale |
|---|---|---|---|---|---|
| **A** | **NEW**: Performance audit cycle-3 (own-work; produce concrete metrics + ship 1-2 perf fixes if found) | own codebase | n/a (own work) | `rg -l 'perf-audit\|performance audit' docs/` → multiple matches (cycle-1 + cycle-2 exist; cycle-3 is new) | cr44 §7 #3 follow-up; last full audit was cycle-2 (R47 era); should re-baseline post R140-R248 ships |
| **B** | **NEW**: PWA offline experience — offline.html fallback page + SW navigation cache | own codebase | n/a (own work) | `rg -l 'offline\.html\|offline_fallback\|fetch.*offline' src/ tests/` → **0 matches** ✅ valid candidate (existing SW only caches `/static/*`; no HTML fallback) | cr44 §7 #4 follow-up; current SW intentionally bypasses HTML to avoid stale-session freeze, but full offline (loss of connectivity) shows browser-default error; offline.html with reconnect hint is industry standard |
| **C** | **NEW**: `<!-- DELETE ON COPY -->` markers in kickoff template (cycle-8 cr44 §2.3 hygiene fix) | own codebase | n/a (process) | n/a — process polish; cycle-8 doc inadvertently kept template's "Usage notes" section | cr44 §8 #2 follow-up; trivial template hygiene to prevent future cycles from re-inheriting boilerplate |
| **D** | Carry: voice input (deferred from cycle-7→cycle-8 Track B, originally cycle-6 Track D) | own codebase | n/a | unchanged from cycle-8 §3.8 (still gated on demand signal) | continue deferral; touch-point logging only |

Per cycle budget: cycle-9 is **execution-focused** (Tracks
A + B substantive; Track C trivial polish; Track D
touch-point only). **Bonus surveys deferred** (Typeform/
NVDA already not-borrow; no fresh inspiration sources
proposed).

## §2 Cycle-9 ship priority

1. **[medium-ROI]** Track A: perf-audit cycle-3 —
   substantive audit; could produce 0-3 perf-fix ships
   depending on findings. **First focus.**
2. **[low-medium]** Track B: PWA offline experience —
   contained scope (~80 LoC `offline.html` + ~30 LoC SW
   navigation-cache + Flask route + 1 test file). **2nd
   ship target.**
3. **[trivial]** Track C: template hygiene markers —
   ~5 LoC docs polish. **Quick win.**
4. Track D: carry deferral; no work unless demand signal.

## §3 Forward log (will fill as cycle progresses)

| Date | Activity | Outcome |
|---|---|---|
| cr45 cycle open | mining-9 kickoff doc (2nd cycle via Track F template) | this file |
| cr45 cycle ship | Track A perf-audit cycle-3 | **shipped** — `docs/perf-audit-cycle-3.md` (frontend critical render path 审计) + R250 anti-FOUC theme bootstrap (`<head>` 同步 inline script ~22 LoC + 10 regression tests, eliminates light↔dark flash for users with explicit theme preference differing from system) |
| cr45 cycle ship | Track B PWA offline experience | **shipped** — `templates/offline.html` (~210 LoC self-contained shell w/ bilingual text + dark/light theme + reduced-motion + auto-ping 5s + online event reload) + `notification-service-worker.js` (pre-cache + activate cleanup + navigation network-first w/ offline fallback) + Flask `/offline.html` route + 27 regression tests across 4 layers |
| cr45 cycle ship | Track C template hygiene markers | **shipped** — added `<!-- DELETE-ON-COPY-START/END -->` markers around "Usage notes" in template + 6 invariant tests preventing future cycle docs from inheriting boilerplate |
| cr45 cycle close | Track D voice input | **carry-over → indefinitely deferred** — 4 consecutive cycles (cycle-6/7/8/9) without ship. Unlock criteria formalized below in §5.1; until **explicit user demand signal** or **W3C SpeechRecognition Permissions-Policy clarification**, no further carry-over. **Removed from default cycle template.** |

## §4 Closeout criteria

Cycle-9 closes when **all**:

1. Track A audit completed with concrete findings doc
   (`docs/perf-audit-cycle-3.md` or similar) and 0-3
   perf-fix ships if findings warrant
2. Track B (PWA offline) shipped or not-borrowed with
   explicit rationale
3. Track C (template hygiene) shipped
4. Track D touch-point logged
5. v3.2 methodology adoption validated: every candidate
   row in this doc has §5 `rg` evidence attached

## §5 Adjacent / future-cycle candidates

Logged here so they don't get lost in TODO drift:

- **Critical CSS inlining** (perf-audit-cycle-3 §5.1; defer)
  — extract first-paint ~5KB CSS from `main.css` and inline
  in `<head>`. Trigger condition: lab-measured LCP > 2s
  (currently ~600ms; not warranted). Tool gap: `critters` /
  `critical` are npm packages but project has zero npm
  build — manual extraction high-maintenance.
- **SW `staleWhileRevalidate` for `/static/*`** (perf-audit-
  cycle-3 §5.2; defer) — current `cache-first` has ~1ms
  `cache.match` overhead per request. Trigger: never (100%
  cache hit rate already; no observed degradation).

### §5.1 Track D (voice input) unlock criteria — formalized

Voice input has been deferred across 4 consecutive cycles
(cycle-6 Track D → cycle-7 Track C → cycle-8 Track B →
cycle-9 Track D). Removing from default cycle template.
Reopen only when **all** of the following:

1. **Explicit user demand signal** — GitHub issue / Discord
   thread / Cursor agent feedback explicitly requesting
   voice input for `feedback-text` textarea. Touch-point
   logging in TODO.md no longer counts as demand.
2. **W3C Permissions-Policy clarification** — either browser
   relaxes `microphone` policy for localhost MCP server use
   case, or a viable workaround (proxy / iframe origin
   isolation) emerges that doesn't break CSP.
3. **A11y baseline maintained** — voice input must coexist
   with screen readers (NVDA / VoiceOver) without conflict.

If reopened, scope: ~60 LoC `voice_input.js` + push-to-talk
button + Web Speech API SpeechRecognition. Estimate: 0.5
day implementation + 1 day testing across browsers + a11y
validation = 1.5 days. **Not** a default-pull track.

## §5.2 Lessons learned

### Lesson 1: 4 consecutive single-cycle executions = mature steady state

cycle-5 (3 not-borrows + 1 process artifact) → cycle-6
(1 ship + 2 discovered + 1 defer) → cycle-7 (1 ship + 1
process artifact + 3 defers) → cycle-8 (1 ship + 2
not-borrows + 1 carry + 1 process artifact) → cycle-9
(3 ships + 1 close-out defer).

**Pattern**: every cycle has ≤ 4 substantive tracks and
closes within a single review window. v3.2 methodology +
Track F template have **eliminated the planning overhead**
that previously stretched cycles across multiple reviews.

### Lesson 2: Own-codebase audit cycles are valuable mining sources

cycle-9 Track A demonstrated that **periodic self-audit**
(perf-audit-cycle-3) can find latent ROI bugs (R250 anti-
FOUC) that external feature mining wouldn't surface
because they're invisible from a feature-naming
perspective. **Recommend**: every 2-3 mining cycles,
schedule one own-codebase audit cycle (perf / a11y /
security / DX) as Track A.

### Lesson 3: 4× carry-over defers warrant formal close-out

Track D voice input has been auto-carried 4 cycles in a
row without any progress signal. Continuing to carry it
pollutes the kickoff template and creates illusion of
"planned but unstarted" work that's actually
indefinitely deferred. **Process change**: formalize
unlock criteria + remove from default template (codified
in §5.1 above).

### Lesson 4: PWA features compound

cycle-7 (custom install prompt) + cycle-8 (iOS A2HS
hint) + cycle-9 (offline experience) form a **3-cycle
PWA polish arc** that bumps the project from "PWA
manifest exists" to "PWA install-prompt-aware, iOS-
aware, offline-aware". This was emergent, not planned —
recommend retroactively documenting in README PWA
section.

### Lesson 5: Anti-FOUC is **always** a critical render path bug

R250 fixed a latent issue that's been there since
`theme.js` was first introduced (R??). It went
unnoticed because:
- Dark default + dark system preference = no flash
- Light system default → CSS @media works = no flash
- Only "user preference ≠ system preference" triggers
  it, which is a minority but non-trivial population

**Recommend**: any future feature that writes
`<html data-*>` attributes via JS must be paired with
a `<head>` inline pre-write to avoid the same FOUC
class.
