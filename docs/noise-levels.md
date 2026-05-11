# Noise Levels Convention (IG-6)

> English | [简体中文](./noise-levels.zh-CN.md)
>
> This document defines the broadcast level convention used **across the
> project's four output channels** (aria-live / toast / log / status bar) —
> i.e. "how loud should an event be shouted?".
>
> Maintenance goals:
>
> 1. **Prevent quadruple noise**: triggering aria-live + toast + log + status
>    bar simultaneously for the same event would crush screen-reader users,
>    sighted users, and log subscribers **all at once**. This convention
>    defaults to quiet, escalates only on demand, and **enlarges the channel
>    set monotonically as the level rises**.
> 2. **Foundational primitive**: P1 (aria-live), P3 (status-bar tooltip), and
>    S3 (diagnostic log chain) all consume this convention. Without one
>    unified definition the three changes would step on each other with high
>    probability (SR-2 calls this out as a risk).
> 3. **Long-term regression shield**: `tests/test_noise_levels.py` asserts
>    via doc-anchor matching that the DOM anchors and runtime constants
>    registered in this document remain present — so a future change that
>    touches one half of the spec without updating the other will go red in
>    CI.

---

## 1. The 3-level × 4-channel matrix

| Level         | aria-live                          | toast                          | Log level | Status bar                              |
| ------------- | ---------------------------------- | ------------------------------ | --------- | --------------------------------------- |
| **critical**  | `assertive` (interrupts narration) | error toast (4s persistent)    | `error`   | Red flash + strong tooltip              |
| **important** | `polite` (announce after current)  | info / warn toast (1.8s)       | `info`    | Yellow + normal tooltip (throttled 1 s) |
| **quiet**     | `off` / silent                     | —                              | `debug`   | Tooltip refresh (throttled 5 s)         |

**How to read it**: a single level → all four channel behaviours **upgrade
together**, never just one. For example, if an event is `critical` it
**must** simultaneously go through assertive aria-live + error toast + error
log + red status bar; "log an error but no toast" or "flash the status bar
but leave aria-live alone" is not allowed (otherwise screen-reader users or
sighted users will miss it).

---

## 2. Level semantics

### 2.1 `critical` — **the user must know immediately or the task fails**

Trigger conditions (examples only):

- Submission rejected (backend 4xx / 5xx and not retryable)
- SSE failures exceed the circuit-breaker threshold (see §3) and the server
  is provably unreachable
- Drafts lost; the moment unsaved content might be overwritten
- Config-file load failure that disables the feature

Hard constraints:

- Rate cap: **at most 1 critical every 3 seconds** (excess automatically
  degrades to important)
- Must be directly actionable (e.g. a "Reconnect" button) — never a dead end
- Wording uses imperative verbs ("please retry", not "it failed")

### 2.2 `important` — **worth knowing, but does not interrupt the user**

Trigger conditions (examples only):

- Connection restored (`aiia.toast.connection.restored`)
- Save succeeded (`aiia.toast.save.success`)
- First fetch falling back to cache (the first switchover is worth flagging)
- Background task completed (the result page is already visible)

Hard constraints:

- Rate cap: **at most 1 important per second** (SR-2's aria-live deduplication
  window applies here too, stacking with a 3-second same-content dedupe
  window)
- Wording must **not** include "act immediately" — that is critical's job

### 2.3 `quiet` — **all state changes default here**

Trigger conditions (**default**):

- Any SSE heartbeat, poll hit, or cache hit
- Any internal state-machine transition (`ConnectionStatus` /
  `ContentStatus` / `InteractionPhase` changes)
- Any UI visibility toggle, tooltip refresh

Hard constraints:

- aria-live must be `off` — i.e. **no** `role="status"` / `role="alert"` and
  no hand-written `aria-live`; visual visibility is sufficient
- Status-bar tooltip refresh must be throttled to **5 seconds** (so SSE
  jitter does not rewrite the tooltip every second)
- Logs default to `debug`; the extension's `logLevel` setting decides
  whether they surface. **Never** use `info` here.

---

## 3. Default rule and escalation circuit-breaker

### 3.1 Default rule

> **All state changes go to quiet; only an explicit `notify(level, payload)`
> call escalates them**.

This principle implies:

- Frontend code **should not** call `logError(...)` for every fetch failure
  — the default is `log(debug)`.
- Frontend code **should not** call `showToast` for every connection-state
  change — the default does nothing; only visible UI elements (status bar,
  connection icon) change colour.
- Screen-reader users **hear nothing by default**, unless the event is
  important or critical.

### 3.2 Escalation circuit-breaker (prevents level "creep")

| Event family             | quiet → important            | important → critical                       |
| ------------------------ | ---------------------------- | ------------------------------------------ |
| SSE connection failure   | **3 consecutive** failures   | important sustained **30 s** without recovery |
| Submission failure       | Single failure → important   | Single 4xx / 5xx not retryable → critical  |
| Config-load failure      | N/A (jumps straight to critical) | Single failure → critical              |
| Save conflict            | Single conflict → important  | This submission would lose data → critical |

The breaker counts **per event family** (not globally); a `ConnectionStatus`
trip from `connected` back to `connected` clears that family's counter.

### 3.3 aria-live deduplication (SR-2 addendum)

- **Same level × same source text** is **not re-broadcast within 3 seconds**
  (screen readers have very low tolerance for duplicate content).
- Implementation: reuse `showToast`'s existing `dedupeKey` mechanism and use
  `dedupeKey` as the aria-live dedup key too (P1 will implement this when
  consumed).

---

## 4. Channel semantics

### 4.1 aria-live channel (browser / webview)

- **Preferred semantic roles** (SR-2):
  - `role="status"` — built-in `aria-live="polite"`, maps to **important**
  - `role="alert"` — built-in `aria-live="assertive"`, maps to **critical**
- **Do not** hand-write `aria-live` — except when explicitly setting `off`
  for quiet.
- Containers should carry `aria-atomic="true"` to avoid partial re-reads.

### 4.2 toast channel

- Visual surface; the main perception channel for non-screen-reader users.
- Existing dedup window: `TOAST_DEDUPE_WINDOW_MS = 700` (`webview-ui.js`, §5
  in that file).
- After P1, toast and aria-live will **share the same `dedupeKey`**, so they
  dedupe in lockstep (no "toast suppressed but the screen reader still
  shouts").

### 4.3 Log channel (VSCode OutputChannel / browser console)

- Log levels are **tied to IG-6 levels only**, not business severity.
- critical → `error`; important → `info`; quiet → `debug`.
- The extension's `logLevel` setting decides whether `debug` writes to
  Output; the Web UI uses `localStorage.AIIA_LOG_LEVEL` for the same purpose.

### 4.4 Status-bar channel (VSCode plugin only)

- `statusBar.text` change → visible immediately, no throttle (this is a
  visual signal, not noise).
- `statusBar.tooltip` change → **must throttle to 5 seconds** (quiet) or 1
  second (important), or refresh instantly (critical, with a red background
  attached).
- `statusBar.backgroundColor` is only used for critical (e.g.
  `new ThemeColor('statusBarItem.errorBackground')`).

---

## 5. Current-state snapshot (when this doc was committed, 2026-04-18)

> This section is the **source of truth for the test guard** —
> `tests/test_noise_levels.py` directly greps for the anchors registered
> here. If an anchor changes, this doc must be updated in the **same**
> commit, otherwise CI goes red.

### 5.1 Existing aria-live anchors (4 sites)

| #  | Path                                            | Line   | Role                              | aria-live value                      | Purpose                                |
| -- | ----------------------------------------------- | ------ | --------------------------------- | ------------------------------------ | -------------------------------------- |
| A1 | `packages/vscode/webview.ts`                    | ≈1327  | div#toastHost                     | `polite` + `aria-atomic="true"`      | Plugin webview's toast host            |
| A2 | `packages/vscode/webview-ui.js` (`showToast`)   | ≈1578-1582 | every toast element            | `polite` (hard-coded) + `role="status"` | Each toast in the plugin webview     |
| A3 | `templates/web_ui.html`                         | ≈267-272 | div#no-content-status-message    | `polite` + `role="status"`           | Empty-state hint in the Web UI         |
| A4 | `templates/web_ui.html`                         | ≈527    | div#status-message               | `polite` + `role="status"`           | Main status bar in the Web UI          |

**Hit pattern**: the test guard uses `Grep` to find `toastHost` co-located
with `aria-live` in the relevant files, and `status-message` co-located with
`aria-live="polite"`.

> **P1 preview** (SR-2): once P1 lands, A2's hand-written
> `aria-live='polite'` will be replaced with `role='status'` (which carries
> polite intrinsically), and A3/A4 will simplify the same way. At that point
> §5.1 here and the A2 assertion in `test_noise_levels.py` will need to be
> updated.

### 5.2 Existing dedup / throttle anchors (2 sites)

| #  | Path                                  | Constant                  | Current value | Notes                                                                                |
| -- | ------------------------------------- | ------------------------- | ------------- | ------------------------------------------------------------------------------------ |
| D1 | `packages/vscode/webview-ui.js`       | `TOAST_DEDUPE_WINDOW_MS`  | `700`         | Toast same-key dedup window; aria-live will share this key after P1 lands.           |
| D2 | `packages/vscode/webview-ui.js`       | `TOAST_MAX_VISIBLE`       | `5`           | At most 5 toasts on screen (so an important burst cannot displace a critical toast). |

The test guard asserts that both constants still exist in the file; the
actual numeric values are allowed to tune (e.g. 700 → 800 is fine), they
just cannot be deleted.

### 5.3 Level reference table — existing functions vs spec target

| Existing function                          | Current behaviour                                                                                  | Spec level                              | Gap                                                                                              |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `log(message)` (webview-ui.js L1509)       | Only `log:debug` channel                                                                            | **quiet**                               | ✅ already aligned                                                                               |
| `logError(message)` (webview-ui.js L1517)  | Three channels simultaneously: `log:error` + `postMessage('error')` + `showToast('error')`         | **critical** (four channels)            | ❌ missing status-bar channel; but the message contents are often not critical-grade (most `logError` calls are really only important) |
| `showToast(message, options)` (webview-ui.js L1542) | kind ∈ `info/success/warn/error`                                                          | important (info/success/warn) or critical (error) | ✅ broadly aligned; missing the explicit level label                                            |
| `postStatusInfo(message)` (webview-ui.js L1723) | Sends `severity:info, presentation:statusBar` to the extension                                  | **important**                           | ✅ already aligned                                                                               |
| `statusBar.tooltip` (extension.ts L166/L252/L718) | Every `updateIndicators` overwrites the tooltip immediately                                  | **quiet**                               | ❌ no throttle; SSE jitter rewrites the tooltip at high frequency                                |

> **P1 / P3 consumption guidance** — see §7.

---

## 6. Anti-patterns (using the current code as the textbook)

### 6.1 Anti-pattern A: `logError` broadcasts on three channels at the same level

```1517:1534:packages/vscode/webview-ui.js
  function logError(message) {
    const text = String(message || '')
    try {
      vscode.postMessage({ type: 'log', level: 'error', message: text })
    } catch (e) {
      // ignore
    }
    try {
      vscode.postMessage({ type: 'error', message: text })
    } catch (e) {
      // ignore
    }
    try {
      showToast(text, { kind: 'error', timeoutMs: 2600, dedupeKey: 'err:' + text.slice(0, 120) })
    } catch (e) {
      // ignore
    }
  }
```

**Problem**: any fetch-catch / `Promise.reject` / try-catch that calls
`logError` triggers all three channels **simultaneously** — but in many
sites it is really "one fetch failed", which **should not** escalate to
critical. Screen-reader users get yelled at every time SSE jitters.

**P1 fix**:

```javascript
function notify(level, message, options) {
  // level ∈ 'critical' | 'important' | 'quiet'
  // dispatches to the right subset of channels per the matrix
}
function logError(message) {
  notify('important', message)  // the vast majority of sites only need important
}
```

### 6.2 Anti-pattern B: status-bar tooltip with no throttle

```245:252:packages/vscode/extension.ts
      if (connected) {
        statusBar.text = `$(sparkle-filled) ${formatTotalCount(total)}`
      } else if (offline) {
        statusBar.text = '$(sparkle-filled) offline'
      } else {
        statusBar.text = '$(sparkle-filled) --'
      }

      statusBar.tooltip = buildStatusBarTooltip({ connected, active: a, pending: p })
```

**Problem**: `updateIndicators` is called at high frequency by the SSE main
loop, overwriting the tooltip every time. Although there is no direct
visual noise (VSCode only renders the tooltip on hover), it wastes
serialization cost on the VSCode side and violates this convention's "quiet
level → 5 s tooltip throttle" rule.

**P3 fix**: add a `lastTooltipRefreshAt` closure variable and short-circuit
when a refresh request arrives within 5 seconds of the previous one at
quiet level.

### 6.3 Anti-pattern C: aria-live hard-coded to `polite`

`webview-ui.js` writes `aria-live='polite'` **directly** on every toast DOM
element, so `kind='error'` (critical) toasts are still only polite —
**screen-reader users cannot perceive the urgency**.

**P1 fix**: map by kind — `kind='error'` → `role='alert'` (assertive,
without hand-writing aria-live); everything else → `role='status'`
(polite).

---

## 7. Consumption path — how each phase-1/2 change-set honours this doc

| Change                              | Consumption responsibility                                                                                                                                              | Sections referenced                            |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| **P1 (aria-live / role)**           | Land a unified `notify(level, message)` entrypoint; in `showToast`, decide `role` from level; aria-live and toast share `dedupeKey`.                                    | §2, §3, §4.1-4.2, §5.1, §6.1, §6.3             |
| **P3 (smart status-bar tooltip)**   | Throttle tooltip updates per level (critical → immediate / important → 1 s / quiet → 5 s); use `backgroundColor` only for critical.                                     | §2, §4.4, §5.3, §6.2                           |
| **S3 (diagnostic log chain)**       | Strictly map log levels to §2 levels; the startup banner is important (once), subsequent heartbeats are quiet.                                                          | §2, §4.3, §5.3                                 |
| **T1 (tri-state UI)**               | Reaching the Error page is **important** on its own (the visual is sufficient); but if "Retry" fails again, escalate to critical.                                       | §2, §3.2                                       |
| **S2 (SSE reconnect)**              | During reconnection, **the first 2 failures are quiet**; from the 3rd onwards → important; 30 s without recovery → critical.                                            | §3.2 circuit-breaker table                     |

---

## 8. Review checklist (whenever you add a new notification / log / toast)

- [ ] Which of quiet / important / critical is this? Write it explicitly in
      the PR description.
- [ ] Did **all four channels escalate together**? critical cannot just log
      an error without a toast; important cannot just toast without
      writing an info log.
- [ ] Are you using `role='status'` / `role='alert'` rather than
      **hand-written** `aria-live`? (quiet level excepted)
- [ ] Does this event family have an **escalation circuit-breaker** rule?
      What is the consecutive-failure threshold to escalate? Does
      `ConnectionStatus` going back to `connected` clear the counter?
- [ ] Are status-bar tooltip updates throttled per level (quiet 5 s /
      important 1 s / critical immediate)?
- [ ] Does the new toast wording use the `aiia.toast.*` namespace reserved
      by C8? Or is this a temporary private namespace pending P1's batch
      migration?
- [ ] Does §5 "current-state snapshot" need to register a new anchor? If
      so, update **this doc and the corresponding test assertion in the
      same commit**.

---

## 9. Automated guard (`tests/test_noise_levels.py`)

Test coverage (6 assertions):

| #  | Assertion                                                                                                       | Anchor          |
| -- | --------------------------------------------------------------------------------------------------------------- | --------------- |
| T1 | `packages/vscode/webview.ts` has `aria-live="polite"` on `toastHost`                                            | §5.1 A1         |
| T2 | `packages/vscode/webview-ui.js`'s `showToast` retains at least one `role='status'` + `aria-live='polite'` site  | §5.1 A2         |
| T3 | `templates/web_ui.html`'s `status-message` carries `aria-live="polite"`                                         | §5.1 A3/A4      |
| T4 | `packages/vscode/webview-ui.js` still declares the `TOAST_DEDUPE_WINDOW_MS` constant                            | §5.2 D1         |
| T5 | `packages/vscode/webview-ui.js` still declares the `TOAST_MAX_VISIBLE` constant                                 | §5.2 D2         |
| T6 | This doc (`docs/noise-levels.md`) retains the §1 3×4 matrix key wording (`critical` / `important` / `quiet`)    | self-describing |

> **Not asserted**: the actual numeric values of constants (so 700 → 800 is
> allowed without going red), and the `logError` three-channel anti-pattern
> (asserting it would generate false positives that block the day-to-day
> P1 refactor).

---

## 10. Relationship to other specifications

- **C3 IG-3 (state machine)**: `ConnectionStatus` transitions
  `connecting → connected` / `connected → disconnected` are the **signal
  sources** for the escalation circuit-breaker — the counters hook into the
  state-machine callbacks.
- **C7 IG-7 (inline-injection register)**: §4.1 here requires that
  `role='alert'` and similar attributes be set via HTML templates or
  `setAttribute`, **not** injected via `innerHTML` (CSP-friendly), which
  carries forward IG-7's "do not introduce new inline risk" stance.
- **C8 IG-8 (i18n naming)**: toast / dialog wording here uses the
  `aiia.toast.*` / `aiia.dialog.*` namespaces reserved by C8; concrete keys
  land in P1 / H1.
- **IG-5 (InteractionPhase matrix)**: IG-5 defines "which shortcuts are
  disabled during `SUBMITTING` / which trigger `beforeunload`"; the
  important / critical toasts here should be **deferred** from `SUBMITTING`
  to `COOLDOWN` so the user is not interrupted mid-submission (IG-5
  implements this when consumed).

---

## 11. Change history

| Date       | Change                                                                                          | Commit |
| ---------- | ----------------------------------------------------------------------------------------------- | ------ |
| 2026-04-18 | Initial draft — 3-level × 4-channel matrix + breaker rules + state snapshot + 6 anchor tests    | C9 (IG-6 introduction) |
| 2026-05-12 | R176 — translate into English; the Chinese version lives at `docs/noise-levels.zh-CN.md`        | R176   |

---

## 12. Exit clause (delete when mission complete)

This document is **transitional**, aligned with the archival discipline of
C7 / C8. It should be deleted after **all three** of the following are
done:

1. **P1 (aria-live) + P3 (status-bar tooltip) + S3 (diagnostic log chain)
   all land** — the "default quiet, escalate on demand" rule is now
   codified inside `notify(level, message)`, so this prose reminder is no
   longer needed.
2. **The six anchor tests' anchors are all on E1 shared module** — once
   phase-3 E1 hoists `notify` and toast into a shared module, §5.1 / §5.2's
   anchors here can simply link to the shared module's README, so we no
   longer maintain two parallel documents.
3. **The `logError` three-channel anti-pattern is fixed** (§6.1) —
   `logError` becomes a thin wrapper around `notify('important', ...)`, at
   which point the anti-pattern listing has no demonstrative value.

The PR that deletes this doc must simultaneously:

- Note the archival reason in `BEST_PRACTICES_PLAN.tmp.md` (have all three
  bullets been met?).
- Delete the entire `tests/test_noise_levels.py` file — its anchor
  assertions are now re-covered by the shared module's test in E1.
