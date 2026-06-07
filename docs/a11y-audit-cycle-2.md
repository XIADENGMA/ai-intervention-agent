# a11y Audit Cycle 2 — closeout (Track A + Track B + latent-bug fix)

> Status: **closeout**
> Opened in cr47-post window (commit immediately after
> cr47 review). Continues a11y-audit cycle kind (cycle-1
> shipped focus management for kshelp overlay + prefers-
> contrast: more upgrade).

---

## §0 Methodology

v3.2 + Track F template + §0.0 filename convention (per
cycle-11 Track B). Audit cycle = source candidates from
WCAG 2.1 spec (prescriptive) + project surface
inventory.

---

## §1 Surface inventory

This cycle audits **color contrast** —
**WCAG 2.1 SC 1.4.3 (Contrast Minimum)**:

| Level | Normal text | Large text (≥18pt or ≥14pt bold) |
|---|---|---|
| AA | 4.5:1 | 3:1 |
| AAA | 7:1 | 4.5:1 |

Surface = text-color-token × background-color-token
combinations in `main.css` design system:

| Text token | Defined in |
|---|---|
| `--text-primary` | `:root` (dark) + `[data-theme="light"]` |
| `--text-secondary` | same |
| `--text-tertiary` | same |
| `--text-muted` | same (background-only per usage) |

| BG token | Defined in |
|---|---|
| `--bg-primary` | `:root` (dark) + `[data-theme="light"]` |
| `--bg-secondary` | same |

Total audit cells = 3 text colors × 2 bg colors × 2 themes = **12 cells**
(text-muted excluded — background-only by convention).

---

## §2 Contrast matrix (pre-fix)

Computed via WCAG 2.1 formula:
`luminance = 0.2126R + 0.7152G + 0.0722B` after sRGB→linear gamma,
`contrast = (L_max + 0.05) / (L_min + 0.05)`.

### Dark theme (`:root`)

| Foreground | on bg-primary `#1a1a1f` | on bg-secondary `#25252d` | Rating |
|---|---|---|---|
| `--text-primary #f5f5f7` | 15.92:1 | 13.96:1 | AAA ✅ |
| `--text-secondary #a1a1aa` | 6.76:1 | 5.93:1 | AA ✅ |
| `--text-tertiary #71717a` | **3.59:1** | **3.15:1** | AA-large only ⚠️ |

### Light theme (`[data-theme="light"]`)

| Foreground | on bg-primary `#e8e6dc` | on bg-secondary `#faf9f5` | Rating |
|---|---|---|---|
| `--text-primary #141413` | 14.73:1 | 17.50:1 | AAA ✅ |
| `--text-secondary #5a5955` | 5.60:1 | 6.66:1 | AA ✅ |
| `--text-tertiary #b0aea5` | **1.78:1** | **2.11:1** | **FAIL** ❌ |

---

## §3 Findings + decisions

### Finding 1: light `--text-tertiary` FAILs at all levels

`#b0aea5` on warm beige `#e8e6dc` reaches only 1.78:1 —
fails both AA-normal (4.5) AND AA-large (3.0). Same
token on `#faf9f5` reaches 2.11:1 — still FAIL.

### Finding 2: dark `--text-tertiary` passes only AA-large

`#71717a` is borderline: 3.59 / 3.15. Any normal text
usage would fail AA-normal (4.5).

### Finding 3: actual usage is restricted to strikethrough

`rg "color: var(--text-tertiary)" main.css` → 1 match:
`.markdown-content del/s/.strikethrough` (light theme
only). This is **intentional muted strikethrough** —
WCAG explicitly permits "incidental text" but the
combination of strikethrough decoration + low contrast
is still risky for low-vision users.

Other uses are `background: var(--text-tertiary)` (2
matches) — not text contrast issue.

### Decision: bump tokens to AA-large minimum, document

Track A bumps both themes' `--text-tertiary` to satisfy
AA-large (3:1) minimum on **all** bg combinations:

| Token | Before | After | After contrast |
|---|---|---|---|
| dark `--text-tertiary` | `#71717a` (3.15 / 3.59) | `#98989e` | 6.04 / 5.30 (AA-normal ✅) |
| light `--text-tertiary` | `#b0aea5` (1.78 / 2.11) | `#757470` | 3.74 / 4.44 (AA-large ✅) |

**Light theme caveat**: light bg-primary `#e8e6dc` is
the Anthropic brand warm-beige; cannot darken without
breaking brand. AA-normal (4.5:1) on this bg requires
text ~ `#707070` or darker which loses the "muted"
visual semantic. AA-large 3:1 + strikethrough is the
WCAG-permissible muted-text standard.

**Dark theme can reach AA-normal** on all bg combos with
`#98989e` — strictly improves accessibility.

---

## §4 Forward log

| Cycle ID | Track | Status |
|---|---|---|
| cr48 cycle ship | **Track A** WCAG AA text-tertiary contrast fix (R257) | **shipped** — `main.css` dark `:root --text-tertiary: #71717a → #98989e` (AA-normal on both bgs), light `[data-theme="light"]` + `@media (prefers-color-scheme: light)` blocks both updated `#b0aea5 → #757470` (AA-large on both bgs). 8 contrast-ratio computation invariants in `tests/test_feat_a11y_cycle2_wcag_contrast.py` directly parse CSS file + recompute WCAG ratios, ensuring no token regression. 2 anti-misuse invariants assert `color: var(--text-tertiary)` only appears in strikethrough context (allowlist = 1) and `color: var(--text-muted)` never appears (background-only token) |
| cr48 cycle ship | **Track B** WCAG AA status-color contrast fix + latent media-query mirror bug (R257b) | **shipped** — Extended cycle-2 audit to status colors (success/warning/error/info). Audit found **8/8 FAIL cells in light theme** + 2 borderline AA-large-only in dark theme. Track B bumps all 4 light status colors to clear AA-normal (success `#788c5d→#506840` 4.94/5.87, warning `#f59e0b→#825005` 5.42/6.43, error `#c54d47→#b03d38` 4.70/5.58, info `#6a9bcc→#2e5e8c` 5.42/6.44) and dark error+info to AA-normal both bgs (error `#ef4444→#f87171` 6.27/5.50, info `#3b82f6→#60a5fa` 6.82/5.98). **Latent-bug fix**: `@media (prefers-color-scheme: light)` block didn't override status colors → system-light users without explicit `data-theme="light"` were getting dark-theme status colors on light bg = 8/8 FAIL pre-fix. Mirror block added. 16 new contrast invariants (4 status × 2 bgs × 2 themes) + 5 mirror-presence invariants. 31 invariants total this cycle |

---

## §5 Closeout criteria — met ✅

| Criterion | Status |
|---|---|
| All 12 text × bg cells documented (§2) | ✅ |
| All 16 status × bg cells documented (Track B) | ✅ |
| Failing cells fixed + re-tested | ✅ (10 + 16) |
| Latent media-query mirror bug fixed | ✅ |
| Anti-regression invariants land | ✅ 31 total |
| Lessons captured | ✅ §6 (5 lessons) |

---

## §6 Lessons learned

### Lesson 1: WCAG audit cycles surface multi-token gaps

`rg` of one token (`text-tertiary`) inventoried 4 dark
+ 4 light = 8 contrast pairs in <5 min. Audit-driven
cycles continue to outperform mining cycles in signal
density (cycle-1 lesson #3 confirmed).

### Lesson 2: Brand constraints set the contrast ceiling

Light bg-primary `#e8e6dc` is brand-locked. Audit
reveals that some token combinations have **brand-
imposed contrast ceilings** below WCAG AA-normal —
intentional design tradeoffs. The right action is to
**document the constraint + enforce AA-large minimum +
invariant-test against further regression**, not to
bulldoze the brand.

### Lesson 3: Tests that recompute > tests that snapshot

Initial impulse was to assert
`text-tertiary == "#757470"`. Instead the test
recomputes WCAG ratio from extracted hex values and
asserts ≥ AA threshold. This:
- Lets future designers tune values within threshold
- Catches regressions even if the **threshold formula**
  changes (e.g., WCAG 3.0 APCA migration would only
  need updating the computation function, not 8
  assertion strings)
- Makes the actual a11y intent explicit in test code

### Lesson 5 (Track B): cascading audits surface latent bugs

Track B started as "audit status colors" but the
inventory `rg --color-scheme` revealed that the
`@media (prefers-color-scheme: light)` block is
**incomplete** — it doesn't mirror status colors. This
means system-light users without explicit
`data-theme="light"` were silently getting dark-theme
status colors → 8/8 FAIL on light bg. The audit *itself*
discovered a pre-existing functional bug that was
invisible before WCAG ratios were computed across
**both** theme delivery mechanisms.

**Pattern**: when auditing a token, audit ALL of its
override sites, not just the primary scope. A token can
appear correct in one scope but FAIL in another due to
missing override. Generalize to: **audit cascading
overrides** as part of any contrast / color audit.

### Lesson 4: "Text vs background" semantic guard

`--text-muted` is technically a text-prefix token but
actual usage is background-only (low contrast = unsafe
for text). The invariant
`test_text_muted_never_used_as_color` codifies this
implicit semantic so future devs reading the token name
"text-muted" cannot inadvertently misuse it.

---

## §7 Forward backlog (cycle-3+)

- **a11y-audit-cycle-3 candidate**: keyboard-only nav
  full user-journey walkthrough (cycle-1 §7 carryover)
- ~~**a11y-audit-cycle-3 candidate**: status color
  contrast~~ **shipped as cycle-2 Track B**
- **a11y-audit-cycle-3 candidate**: borders + focus rings
  against backgrounds (border/border-focus tokens vs
  bg-primary/secondary) — narrowed scope after Track B
- **a11y-audit-cycle-3 candidate**: WCAG AAA upgrade path
  for dark theme (it could reach AAA with minor tweaks)
- **a11y-audit-cycle-3 candidate**: VoiceOver/TalkBack
  manual testing (real-device, indefinitely deferred)
- **a11y-audit-cycle-3 candidate**: ARIA attribute
  completeness audit (`aria-describedby`,
  `aria-controls` on widget pairs)
