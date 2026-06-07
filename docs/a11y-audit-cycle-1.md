# a11y Audit Cycle 1 — closeout

> Status: **closeout** (Track A + bonus Track B shipped)
> Opened + closed in cr47 cycle. **First-ever a11y-audit cycle**
> kind invoked (joining `feature-mining` + `perf-audit`
> per template §0.0 R254 + template-hygiene generalization
> from cycle-10 Track C).

---

## §0 Methodology

Adopt **v3.2 methodology** (mandatory `rg` pre-check per
candidate), Track F template, and the §0.0 `<kind>-cycle-
<N>.md` filename convention from cycle-11 Track B.

This cycle differs from previous in **audit kind**: we are
not borrowing features from competitor surveys — instead
we are auditing **our own UI** for WAI-ARIA / WCAG 2.1 AA
compliance gaps. Candidates are sourced from:

1. **`rg` survey** of `role="dialog"`, `aria-modal`,
   `focus(`, `tabindex` in `src/.../templates/` +
   `src/.../static/js/` to enumerate every focus-managing
   surface.
2. **Cross-check** each surface against the standard
   modal-dialog a11y checklist:
   - aria-labelled / aria-modal attributes
   - focus moved into dialog on open
   - **focus returned to opener on close**
   - **Tab key trapped inside dialog**
   - Escape key closes
   - background siblings inert / aria-hidden
3. Surfaces missing any item → candidate row.

---

## §1 Surface inventory

`rg -l 'role="dialog"|aria-modal' src/...` → 3 surfaces:

| Surface | File | Trigger | Implementation |
|---|---|---|---|
| Settings panel | `web_ui.html` + `settings-manager.js` | Settings button | Class methods `showSettings`/`hideSettings` |
| Code paste fallback panel | `web_ui.html` + `settings-manager.js` | Paste-failure fallback | Class methods in settings-manager |
| **Keyboard shortcut cheatsheet** | `keyboard_shortcut_help.js` | `?` key | Pure IIFE `showOverlay`/`hideOverlay` |

`ios_a2hs_hint.js` mentions `role="dialog"` only in **doc
comments** — actual rendered DOM is a banner, not a modal.

---

## §2 Per-surface a11y compliance matrix

| Surface | aria-label* | open focus | **close → opener** | **Tab trap** | Esc | inert siblings |
|---|---|---|---|---|---|---|
| Settings panel | ✅ aria-labelledby | ✅ first focusable | ✅ `settingsBtn.focus()` | ✅ `_settingsFocusTrap` | ✅ | ✅ `_setContainerSiblingsInert` |
| Code paste panel | ✅ aria-labelledby | ✅ (same code paths) | ✅ (same code paths) | ✅ (same code paths) | ✅ | ✅ (same code paths) |
| **kshelp overlay** | ✅ aria-label | ✅ card focus | ❌ **MISSING** | ❌ **MISSING** | ✅ | ❌ **MISSING** |

`aria-label*` = either `aria-label` or `aria-labelledby`.

**Finding**: kshelp overlay is the **only** modal-dialog
surface lacking the 3 modal-a11y essentials (focus return /
trap / sibling inert). Settings panel infra already
codifies a proven pattern; kshelp can adopt it 1:1.

---

## §3 Forward log (per-track ship table)

| Cycle ID | Track | Status |
|---|---|---|
| cr47 cycle ship | **Track A** keyboard cheatsheet a11y compliance (R255) | **shipped** — `keyboard_shortcut_help.js` adopts settings-panel pattern: (1) `_previouslyFocusedElement` captured on `showOverlay` + restored on `hideOverlay`, (2) `_onTabInOverlay` keydown listener traps Tab/Shift+Tab to card (overlay has 0 internal focusables; both directions cycle back to card), (3) container siblings set to `inert` while overlay open (graceful try/catch + attribute fallback for browsers without `el.inert` setter). 16 invariants in `tests/test_feat_a11y_cycle1_kshelp_focus.py`. Closes a11y-audit §2 finding |
| cr47 cycle ship | **Track B (bonus)** prefers-contrast: more support (R256) | **shipped** — `main.css` adds `@media (prefers-contrast: more)` block inside `@layer a11y`: upgrades `:focus-visible` to 4px outline-width (vs 2px), 3px outline-offset (vs 2px), `outline-color: Highlight` (system high-contrast color, reuses user's chosen contrast scheme vs hard-coding brand color). Activated when user opens macOS Accessibility → Increase Contrast / Windows High Contrast Mode / Chromium DevTools emulation. 7 invariants in `tests/test_feat_a11y_cycle1_prefers_contrast.py`. Closes §7 backlog item #3 from this same cycle (organic bonus pattern from cycle-10 R253 cross-tab theme sync) |

---

## §4 Closeout criteria

Cycle closes when:

1. ✅ All §1 surfaces have a complete §2 compliance row
2. ✅ Track A shipped (kshelp brought to parity with settings panel)
3. ✅ Track B bonus shipped (prefers-contrast: more)
4. ✅ §5 lessons captured (4 lessons + 1 bonus lesson)

---

## §5 Lessons learned

### Lesson 1: New cycle kind unlocks new gap class

Without the cycle-10 Track C `*-cycle-*.md` glob
generalization + cycle-11 Track B filename convention,
this `a11y-audit-cycle-1.md` would not have a natural home
in the docs taxonomy. **Infrastructure earns its keep when
it lets you invoke new cycle kinds with zero friction**.

### Lesson 2: Audit-driven cycles surface latent gaps quickly

The §2 compliance matrix took ~5 minutes to construct via
`rg` + cross-reference reading; immediately surfaced one
clear gap (kshelp ≠ settings parity). No new
implementation pattern needed — adopt existing
settings-manager pattern. **Total Track A cost: ~80 LoC +
7 invariants**.

### Lesson 3: a11y audit ≠ external feature mining

External mining is uncertain: borrow rate often < 30%
(see cycle-4..10 mining tracks). Audit cycles have higher
**signal density** because audit criteria are
prescriptive (WAI-ARIA spec) rather than subjective
(competitor's UX choice). Both styles complement each
other.

### Lesson 5 (bonus): organic bonus track from same-cycle audit

Track B (prefers-contrast) emerged organically while
documenting §7 backlog — discovered it was a ~30-min
self-contained additive change (1 `@media` block + 7
invariants), so shipped same cycle as cr47 cycle bonus.
Follows the cycle-10 R253 cross-tab theme sync bonus
pattern: **if a backlog item shrinks to < 1h during
documentation, ship it as bonus rather than queue**.

### Lesson 4: 0-focusable trap is still trap

kshelp has 0 internal focusable elements. Tab key would
**escape to background page** if not trapped. Adopted
"trap-to-card" pattern (preventDefault + refocus card on
both directions). Settings panel's
`_settingsFocusTrap` pattern doesn't directly apply when
focusables array is empty — short-circuits at `length ===
0`. kshelp's variant correctly trap when focusables=0.

---

## §6 Methodology validation

- ✅ v3.2 `rg` evidence: §1 inventory built via `rg -l
  'role="dialog"|aria-modal'`
- ✅ Track F template adoption: §3 forward log table
- ✅ §0.0 filename convention: `a11y-audit-cycle-1.md`
  conforms to `<kind>-cycle-<N>.md`
- ✅ Lessons captured: §5 has 4 lessons

---

## §7 Forward backlog (cycles 2+)

- **a11y-audit-cycle-2 candidate**: VoiceOver / TalkBack
  manual testing (requires physical mobile devices;
  bandwidth defer)
- **a11y-audit-cycle-2 candidate**: keyboard-only nav full
  user-journey walkthrough (Tab/Shift+Tab + Enter/Space
  on every interactive element)
- ~~**a11y-audit-cycle-2 candidate**: `prefers-contrast:
  more` support~~ **shipped as cycle-1 Track B bonus**
- **a11y-audit-cycle-2 candidate**: Color contrast ratio
  audit on theme tokens (WCAG AA = 4.5:1 normal text,
  3:1 large text)

None block cycle-1 closeout — all are scope for
future audit cycles.
