# a11y Audit Cycle 3 — kickoff + Track A ship

> Status: **kickoff + Track A ship**
> Continues a11y-audit cycle kind (cycle-1: focus
> management + prefers-contrast; cycle-2: WCAG AA text
> + status color contrast). cycle-3 closes the
> **non-text contrast** (WCAG 1.4.11) gap that cycle-2
> §7 backlog identified for borders + focus rings.

---

## §0 Methodology

v3.2 + Track F template + §0.0 filename convention.
This cycle is **WCAG 1.4.11 (Non-text Contrast)** —
applies to UI components like **focus indicators**,
borders, state indicators (active, hover, disabled).
Required contrast: ≥ 3:1 against adjacent colors.

This is **distinct from cycle-2's WCAG 1.4.3** which
applies to text only.

---

## §1 Surface inventory

`rg --primary-(500|600)|--border-` revealed:

| Token | Used for |
|---|---|
| `--primary-500` | Brand orange (light) / purple (dark) — buttons, accents, **focus ring before cycle-3** |
| `--primary-600` | Deeper brand for hover states |
| `--border-primary` | rgba alpha — divider lines |
| `--border-focus` | (defined but not commonly used; preserved for legacy) |

**Critical surface**: `@layer a11y :focus-visible { outline:
2px solid var(--primary-500) }` — the keyboard focus
indicator inherited via cycle-1 R250 + cycle-1 Track A
(R255).

---

## §2 Non-text contrast audit (focus indicator)

WCAG 1.4.11 threshold: **3:1 against adjacent colors**.

| Theme | `--primary-500` | on bg-primary | on bg-secondary | Verdict |
|---|---|---|---|---|
| Dark | `#a855f7` (purple) | 4.38:1 ✅ | 3.84:1 ✅ | PASS |
| Light | `#d97757` (Anthropic orange) | **2.50:1** | **2.96:1** | **FAIL both** ❌ |

**Finding 1**: Light theme focus ring is **invisible**
to keyboard users — 2.50:1 is below WCAG 1.4.11 (3:1).
Same brand orange shines for buttons (where bold text +
larger area provides redundant signal) but fails as a
2px outline.

**Finding 2**: `--primary-600 #c56a4c` reaches only
3.03:1 / 3.60:1 — borderline pass on bg-primary, fine
on bg-secondary. **Margin too thin** for renderer
gamma variations.

---

## §3 Decision

**Track A** introduces a focus-specific token
`--focus-ring-color` independent of brand button color:

| Theme | Old (via `--primary-500`) | New token | Contrast |
|---|---|---|---|
| Dark | `#a855f7` (4.38 / 3.84) | `#a855f7` (reuse) | unchanged ✅ |
| Light | `#d97757` (2.50 / 2.96 FAIL) | `#b35a3c` | 3.78 / 4.49 ✅ |

**Why a NEW token vs reusing primary-600**:
- primary-600 is **hover state** semantic; reusing it
  for focus conflates two distinct UI semantics
- primary-600's 3.03/3.60 leaves no margin for
  rendering variations (anti-aliasing, gamma)
- New `--focus-ring-color` is **single-purpose**, easy
  to tune independently per theme without affecting
  buttons / accents

`#b35a3c` is the same hue family as Anthropic orange
(just deeper) — preserves brand identity while
clearing WCAG 1.4.11.

**`:focus-visible` rule update**:
```css
@layer a11y {
  :focus-visible {
    outline: 2px solid
      var(--focus-ring-color, var(--primary-500, currentColor));
    outline-offset: 2px;
  }
}
```

Triple-tier fallback chain:
1. `--focus-ring-color` (new, AA-compliant)
2. `--primary-500` (legacy reuse if new token undefined)
3. `currentColor` (last-resort browser default)

---

## §4 Forward log

| Cycle ID | Track | Status |
|---|---|---|
| cr48 cycle ship | **Track A** WCAG 1.4.11 focus ring contrast (R258) | **shipped** — new `--focus-ring-color` token introduced in dark `:root` (`#a855f7` reused), light `[data-theme="light"]` (`#b35a3c` deeper Anthropic orange = 3.78/4.49 ≥ 3:1), and `@media (prefers-color-scheme: light)` block (mirror). `:focus-visible` rule updated to use `var(--focus-ring-color, var(--primary-500, currentColor))` triple-fallback. 6 new invariants in `tests/test_feat_a11y_cycle3_wcag_focus_ring.py` directly compute WCAG ratios + assert ≥ AA-large 3:1 + verify mirror presence + assert `:focus-visible` rule uses the new token. Closes cycle-2 §7 backlog item "borders + focus rings vs backgrounds" (narrowed scope per cycle-2 §6 L5 cascading-audit lesson) |

---

## §5 Closeout criteria — met ✅

| Criterion | Status |
|---|---|
| §1 surface inventory complete | ✅ |
| §2 audit matrix documented | ✅ |
| §3 decision rationale documented | ✅ |
| Failing cells fixed | ✅ |
| Anti-regression invariants land | ✅ (6 new) |
| Lessons captured (§6) | ✅ |

---

## §6 Lessons learned

### Lesson 1: Brand color ≠ focus color

`--primary-500` (Anthropic Orange `#d97757`) is **a
beautiful brand color** but is **non-text-contrast non-
compliant as a focus indicator** on its native warm
beige background. This is a common a11y trap: designers
assume brand-color = consistent visual language across
all interactive surfaces, but WCAG distinguishes:

- **Text on background** (1.4.3): 4.5:1 / 3:1 thresholds
- **UI component contrast** (1.4.11): 3:1 single threshold
- **Focus indicator** (2.4.7): just needs to be visible

The right architectural answer: **separate
semantic-purpose tokens**. Brand color, hover color,
focus color, error color are *different concerns* even
if they happen to live in the same hue family.

### Lesson 2: Light brand bg is the constraining axis

For the third audit cycle in a row (cycle-2 L2,
cycle-2 L5 cascading, cycle-3 §3), the **light theme
`bg-primary #e8e6dc`** has been the contrast
constraint. Anthropic brand warm beige is
intentionally low-luminance vs Mac/iOS default whites —
beautiful but **forces all foreground/UI colors to
be deeper than default web palettes**.

This is a **recurring pattern** worth documenting
upfront in future audits: any new color token added
should immediately be checked against `#e8e6dc`.

### Lesson 3: Fallback chains are forwards-compat insurance

`var(--focus-ring-color, var(--primary-500, currentColor))`
chain means:
- Existing users (no `--focus-ring-color` override)
  still get sane defaults
- Custom themes that define only `--primary-500` work
- Browsers with no support for either fall back to
  text color
- Future a11y-cycle-N can refine `--focus-ring-color`
  per-theme without disturbing call sites

### Lesson 4: WCAG 1.4.11 ≠ WCAG 1.4.3

cycle-2 was 1.4.3 (text). cycle-3 is 1.4.11 (UI
components). Both apply simultaneously. **A token can
pass 1.4.3 as text and FAIL 1.4.11 as an outline**, or
vice versa. Audit cycles should explicitly call out
which WCAG SC is being audited.

---

## §7 Forward backlog (cycle-4+)

- **a11y-audit-cycle-4 candidate**: keyboard-only nav
  full user-journey walkthrough (carry from cycle-1)
- **a11y-audit-cycle-4 candidate**: WCAG AAA upgrade
  path for dark theme (achievable with minor tweaks)
- **a11y-audit-cycle-4 candidate**: ARIA attribute
  completeness audit (`aria-describedby`,
  `aria-controls` on widget pairs)
- **a11y-audit-cycle-4 candidate**: `--border-*` rgba
  alpha contrast against backgrounds — requires
  alpha-blend computation in invariants
- **a11y-audit-cycle-4 candidate**: hover/active state
  contrast (--bg-hover, --bg-active rgba alpha) vs
  underlying button bg
- **a11y-audit-cycle-4 candidate**: VoiceOver/TalkBack
  manual testing (indefinitely defer per cycle-1 §7)
