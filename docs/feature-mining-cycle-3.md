# Feature Mining — Cycle 3

> Third-round competitive analysis. **Two-track survey**:
>
> 1. **Track A** — re-baseline against `mcp-feedback-enhanced`
>    HEAD (cycle-2 baselined at v2.6.1-unreleased / `2026-01-15`;
>    cycle-3 checks for new releases / unreleased PRs).
> 2. **Track B** — survey **interaction patterns** (not feature
>    ports) from `gemini-cli` + `claude-code` (cycle-2 §4.3
>    deferred). Output goal: 2-3 idioms we may borrow, not
>    necessarily features.
>
> Applies the **hardened §0 methodology** from cycle-2: every
> candidate item requires BOTH `rg` (filesystem) AND
> `git log --grep` (history) evidence — the cycle-2 doc rewrote
> §0 after 3 survey misses, this cycle is the first run under
> the new rules.

---

## 0. Methodology (cycle-2 hardened — quote-for-quote)

For every candidate feature in §3:

```bash
# 1) filesystem evidence (what's currently in tree)
rg '<feature-keyword>' src/ packages/

# 2) history evidence (what was already shipped / removed / discussed)
git log --grep '<feature-keyword>' --since='2 years ago' --oneline
git log --grep '<keyword-alt>' --since='2 years ago' --oneline
```

Both outputs must be **pasted verbatim** in each §3 candidate
section, even if empty. Empty grep = positive evidence that
nothing exists; presence of matches = strong hint that the
feature is shipped / partially done / consciously rejected.

**Why mandatory**: cycle-2 had 3 survey misses
(§3.3 input-height-memory R137, §3.4 project_directory R partial,
§3.1 Session Export R125/R125c/R135). All were caught **after**
the survey, during implementation grep. New §0 forces the grep
**before** classifying as "not started".

---

## 1. Track A — competitor re-baseline status

### 1.1 Baseline window

- Cycle-2 baseline: `2026-01-15`, v2.6.1-unreleased (v2.6.0 +
  PR #207 merged to main).
- Cycle-3 baseline window: `2026-01-15` → today (`2026-06-04`).
- Method: ddg-search + WebFetch on releases page;
  CHANGELOG.en.md HEAD diff if accessible.

### 1.2 Findings (to be filled by Track A survey)

> **Status as of cycle-3 kickoff**: not yet executed. cycle-3
> Track A is **future work scheduled** for the cycle-3 mining
> loop. This doc opens the cycle and locks in the methodology
> + Track B; Track A's actual competitive diff will land as a
> later patch to this same doc.

Pre-survey expectations (based on cycle-2 forward log):

- Competitor may have released v2.6.1 stable (we baselined
  unreleased HEAD).
- Possible cycle-3 candidates from cycle-2 deferrals:
  - cycle-2 §3.5 "auto-commit pause control v2" — only if user
    signal received.
  - cycle-2 §3.6 "tool docstring LLM hinting" — only if we add
    telemetry first.

---

## 2. Track B — interaction-pattern survey (gemini-cli + claude-code)

Track B targets **idioms**, not features:

- Q: How do these CLIs handle the "AI claims completion but
  user wants follow-up" problem? (our `interactive_feedback`
  niche)
- Q: How do they surface task state to the user during long
  loops? (compare with our task tab + countdown)
- Q: How do they format AI-to-user pre-defined option prompts?

### 2.1 `gemini-cli` (Google) — to survey

- **Repo**: `google-gemini/gemini-cli` (per cycle-2 §4.3
  hint).
- **Survey questions to answer**:
  1. Does gemini-cli have any "ask user before completing"
     primitive akin to our `interactive_feedback`?
  2. Does it have a "task continuation" loop that we could
     learn from for auto-resubmit UX?
  3. What's its prompt-injection / sandboxing model? (relevant
     to our XSS hardening).
- **Method**: `gh repo view` + README skim + grep their
  "interactive" / "prompt user" code paths.
- **Status**: not yet surveyed.

### 2.2 `claude-code` (Anthropic) — to survey

- **Repo**: `anthropic/claude-code` (the actual SDK / CLI).
- **Survey questions to answer**:
  1. Does claude-code have hooks akin to our MCP
     `interactive_feedback` flow? (We integrate via MCP; they
     may have first-party hooks.)
  2. How does it handle the "agent thinks it's done, user
     disagrees" loop?
  3. Any built-in pre-defined-option UI affordance?
- **Method**: similar — repo skim + hook docs.
- **Status**: not yet surveyed.

### 2.3 Output goal

Track B output is **NOT a feature port list**. It's:

- 0–3 **interaction idioms** worth borrowing (e.g. "claude-code
  surfaces 'pending follow-up' as a status badge — we should
  too").
- 0–2 **anti-idioms** to consciously NOT do (e.g. "gemini-cli
  pops modal-style follow-up — we already have inline + Bark,
  modal is worse").
- Per item: 1-paragraph rationale + ROI tag.

Target effort: **≤ 1 day** total across both CLIs, half a day
each. If it balloons, abort and document why.

---

## 3. Pre-known candidates from cycle-2 forward log

These were explicitly carried forward and are pre-eligible for
cycle-3 work (still subject to §0 grep evidence + ROI gate):

### 3.1 Session-export UI cycle-3 polish — **DONE in cycle-2**

cycle-2 forward log already marked this as "shipped in cycle-2"
(commit `0c8aa7f`). Cited here for completeness only; no
cycle-3 work needed.

### 3.2 zhconv hybrid design — **DEFERRED**

cycle-2 §4.1 evaluation closed with "not adopting" + hybrid
design (inline phrase first + zhconv char fallback) is future
track. Trigger condition not met (CHAR_MAP_v2 ≥ 600 AND ≥ 3
SC-residue bugs). **No cycle-3 work.**

### 3.3 Auto-commit pause control v2 (v2.6.0 mirror) — **DEFER**

cycle-2 §3.5 deferred conditional on ≥ 2 user reports of
"+60s wasn't enough". **No reports received** during cycle-2
loop. Continue defer.

### 3.4 Tool docstring LLM hinting (v2.5.5 mirror) — **DEFER**

cycle-2 §3.6 deferred pending telemetry. **No telemetry shipped
in cycle-2**. Continue defer; consider as cycle-4 candidate
**after** a separate "minimal counter telemetry" investigation
ships.

---

## 4. Cycle-3 work order

Recommended ordering for the cycle-3 loop:

1. **Track A** competitive re-baseline (target: half-day).
   Output: §1.2 filled with 0–N adoptable candidates +
   evidence-per-item grep blocks.
2. **Track B** interaction-pattern survey (target: 1 day).
   Output: §2.3 list of 0–3 idioms + 0–2 anti-idioms.
3. **Highest-ROI Track-A candidate** ships if found (one feat
   commit + test).
4. **Code Review #36** at cycle end (after 4-5 commits).

If Track A finds **nothing new** (likely if no competitor
release dropped in the window), cycle-3 collapses to Track B +
polish work surfaced from cr35 §8 follow-ups (#3 mining miss
rate tracking, #4 grep-helper automation if needed).

---

## 5. Risks identified at cycle-3 kickoff

- **Competitor inactive window risk**: if `mcp-feedback-
  enhanced` had no release in 2026-01..06, Track A returns
  nothing, which could feel like "wasted survey". Counter:
  even a "no new features" finding is **positive evidence**
  for our baseline.
- **Track B scope creep**: surveying two large CLI projects
  in 1 day requires discipline. If either survey hits > 4
  hours, time-box and document partial findings.
- **§0 grep evidence overhead**: per cr35 §8 #4, if per-item
  grep step averages > 5 min, write a small bash helper. The
  baseline is 30 min for ~6 items; if it exceeds 60 min, the
  automation pays off.

---

## 6. Forward log (cycle-3 → cycle-4+)

| Item | Status | Owner-cycle | Notes |
|---|---|---|---|
| Track A re-baseline | open | cycle-3 | half-day budget |
| Track B gemini-cli survey | open | cycle-3 | half-day budget |
| Track B claude-code survey | open | cycle-3 | half-day budget |
| Top Track-A candidate ship | conditional | cycle-3 | only if found |
| cr35 §8 #3 miss-rate tracking | open | cycle-3 | track outcome of new §0 |
| cr35 §8 #4 grep helper | conditional | cycle-3 | only if per-item > 5 min |
| §3.3 pause control v2 | deferred | cycle-4+ | needs user reports |
| §3.4 docstring hinting | deferred | cycle-4+ | needs telemetry |
| §4.1 zhconv hybrid | deferred | future | CHAR_MAP_v2 ≥ 600 + 3 bugs |

---

## 7. Cross-references

- `docs/feature-mining-cycle-1.md` — cycle-1 backlog (closed)
- `docs/feature-mining-cycle-2.md` — cycle-2 backlog (closed)
- `docs/code-reviews/cr35.md` §8 — follow-up items routed here
- `docs/zhconv-eval.md` — cycle-2 §4.1 closeout artifact
