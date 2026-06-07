# Feature Mining Cycle N — kickoff template

> Status: **kickoff** · Opened in cr<NN> cycle
> Predecessor: `feature-mining-cycle-<N-1>.md` (closed in cr<NN-1>)
> Methodology revision: **v3.2** (current; bump if introducing v3.3+)

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

### §0.0 Cycle doc filename convention (R254 / mining-11 Track B)

> Codified after `test_covers_multiple_cycle_doc_kinds`
> (mining-10 Track C) introduced reliance on this pattern.

All cycle docs **must** use the canonical filename pattern:

```
<kind>-cycle-<N>.md
```

Where:
- `<kind>` is one of: `feature-mining`, `perf-audit`,
  `security-audit` (future), `a11y-audit` (future),
  `dx-audit` (future). Use **kebab-case** (no underscores).
- `<N>` is a positive integer (1, 2, ...). No leading zeros.
- The separator **must be exactly** `-cycle-` (hyphenated).

**Examples** ✅:
- `feature-mining-cycle-11.md`
- `perf-audit-cycle-3.md`

**Examples** ❌:
- `mining_cycle_11.md` (underscores)
- `cycle-11.md` (no kind prefix)
- `feature-mining-cycle-XI.md` (Roman numeral)
- `audit_cycle_3.md` (underscore + no `-cycle-` separator)
- `MiningCycle11.md` (camelCase)

**Why**: `tests/test_feat_mining9_cycle_doc_no_boilerplate.py`
uses `glob("*-cycle-*.md")` + `p.name.split("-cycle-", 1)[0]`
to enumerate kinds. Deviating from the convention silently
excludes the doc from the boilerplate-leak invariant.

### §0.1 `rg` pre-check boilerplate (copy-paste into §1
candidate table cell)

For every TBD-ship candidate, paste this snippet into the
`rg` pre-check column, replacing `<KEYWORD>`,
`<SYNONYM1>`, `<SYNONYM2>` with the candidate's primary
keyword + 1-2 plausible synonyms (e.g., feature name in
both camelCase and kebab-case, or English + Chinese
romanization, or implementation pattern + UX pattern):

```text
$ rg -l '<KEYWORD>|<SYNONYM1>|<SYNONYM2>' src/ tests/
<paste-output-here-even-if-empty>
```

If output is non-empty, **change candidate row outcome
to "discovered-already"** and add a cross-link to the
existing file:line.

### §0.2.bis Indefinitely-deferred features (do **not**
auto-carry into new cycles)

Per cycle-9 §5.1 lesson #3 (4× carry-over = formal
close-out), the following features have been removed from
the default carry-over pool. Reopen only when explicit
unlock criteria met (see source doc):

| Feature | Source | Unlock criteria |
|---|---|---|
| Voice input for feedback textarea | cycle-9 §5.1 | (1) explicit user demand signal, (2) W3C Permissions-Policy clarification, (3) a11y baseline maintained |

If proposing a new track that matches an indefinitely-
deferred entry, **must cite which unlock criteria triggered
the reopen** in the candidate row's rationale column.

### §0.2 Common keyword categories (synonym brainstorm
hint)

When generating synonyms for the `rg` check, consider:

- **English + Chinese romanization**: e.g., "voice input"
  → `SpeechRecognition`, `webkitSpeechRecognition`,
  `voiceInput`, `microphone`
- **API surface synonyms**: e.g., "drag-and-drop reorder"
  → `dragstart`, `dragover`, `drop`, `reorder`,
  `draggable`
- **Storage / persistence pattern**: e.g., "preference
  X" → `localStorage`, `sessionStorage`, `aiia.<X>`
- **UI affordance synonyms**: e.g., "context menu" →
  `oncontextmenu`, `right-click`, `popper`, `dropdown`

## §1 Cycle-N planned tracks

| Track | Scope | Subject type | Borrow kind | `rg` pre-check (v3.2) | Rationale |
|---|---|---|---|---|---|
| **A** | (description) | (type) | (kind) | (rg evidence per §0.1) | (rationale) |

## §2 Cycle-N ship priority

1. **[priority]** Track ID: rationale
2. ...

## §3 Forward log (will fill as cycle progresses)

| Date | Activity | Outcome |
|---|---|---|
| crN cycle open | mining-N kickoff doc | this file |

## §3.x Track-by-track outcome detail (template)

For each track that warrants more than a 1-line forward
log entry — especially **not-borrow rationales**,
**deferral rationales**, or **discovered-already
findings** — add a `§3.<N>` subsection. Example
structure (adapted from cycle-7 §3.2):

```markdown
## §3.<N> Track <X> <one-line scope> — <outcome>

**Pre-§2.1 `rg` evidence** (v3.2 compliance, repeated
for closeout review):

\`\`\`text
$ rg -l '<keyword>|<synonym1>' src/ tests/
<output>
\`\`\`

**Survey findings** (or rationale):

1. ...
2. ...

**Architectural verdict** (or defer decision):
<concrete decision + reasoning>

**Future revisit conditions** (for deferrals; mirror
voice-input pattern):

1. <Concrete unlock condition>
2. ...
```

## §3.y Carry-over track-classification table (template)

For multi-cycle carry-overs (tracks deferred from
previous cycles), the cycle-7 §3.3 pattern provides clean
classification. **Use this table to standardize carry-
over status reporting**:

| Track | Source | Status | Unlock condition |
|---|---|---|---|
| <ID> | <previous cycle reference> | <"still deferred" / "bandwidth-deferred"> | <"n/a — bonus, not gated" OR explicit condition> |

**Status taxonomy**:

- **still deferred**: gating condition (GitHub issue,
  architecture doc, demand signal) unchanged — work not
  resumable yet
- **bandwidth-deferred**: cycle ran out of bandwidth;
  candidate is **bonus**, not core; explicit punt to
  next cycle without rationale gating
- **discovered-already**: feature already exists in
  codebase per v3.2 `rg` evidence — close immediately

Don't write generic prose about each carry-over; this
table is the canonical format.

## §4 Closeout criteria

Cycle-N closes when **all**:

1. Every planned track has explicit outcome (ship / not-
   borrow / discovered-already / deferred with rationale)
2. v3.2 methodology adoption validated: every candidate
   row in this doc has §5 `rg` evidence attached
3. New cycle-N+1 kickoff candidates surfaced (preserve
   forward pipeline)

## §5 Adjacent / future-cycle candidates

Logged here so they don't get lost in TODO drift:

- _(initially empty — will fill as cycle-N surveys + ships
  reveal new candidates)_

## §5.1 Lessons learned (filled as cycle progresses)

- _(initially empty — will fill as cycle-N closeout
  records lessons)_

<!-- DELETE-ON-COPY-START

Everything between DELETE-ON-COPY-START and DELETE-ON-COPY-END
must be removed when starting a real cycle doc. These markers
also let `scripts/check_cycle_doc_no_template_boilerplate.py`
(future hygiene script) flag cycle docs that forgot to delete.

-->

---

## Usage notes (delete this section when starting a real cycle doc)

1. Copy this file to `feature-mining-cycle-<N>.md` (next
   cycle number).
2. Search-replace `<NN>` with the cr cycle number and
   `<N>` with the mining cycle number.
3. Fill §1 candidate table with v3.2 `rg` evidence for
   every TBD-ship candidate (use §0.1 boilerplate).
4. Update §2 priority order based on ROI assessment.
5. Open cycle by committing the kickoff doc with a commit
   message like `:books: docs(mining-N): cycle-N kickoff
   ...`.
6. As cycle progresses, update §3 forward log with each
   activity.
7. On closeout, append §4 audit + §5.1 lessons learned
   and update header status `kickoff` → `closed`.
8. **DELETE this entire section** (between
   `DELETE-ON-COPY-START` and `DELETE-ON-COPY-END`
   markers above + below) — and re-verify no `<!--
   DELETE-ON-COPY-*-->` markers remain in your cycle doc.

<!-- DELETE-ON-COPY-END -->
