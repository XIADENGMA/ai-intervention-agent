# Contributing

> English | [简体中文](./CONTRIBUTING.zh-CN.md)

Thanks for considering a contribution!

This file is the **entry point**; the full development / release workflow lives in
[`docs/workflow.md`](../docs/workflow.md) (English) and
[`docs/workflow.zh-CN.md`](../docs/workflow.zh-CN.md) (Chinese).

This document lists the **minimum required checklist** only; for the detailed
local development / release pipeline see the two `docs/workflow*.md` files above.

---

## 1. Getting started

```bash
# Clone
git clone https://github.com/xiadengma/ai-intervention-agent.git
cd ai-intervention-agent

# Python toolchain (uv ships its own venv + dependency resolver)
uv sync

# Node toolchain (only needed for the VS Code extension; use fnm to manage Node 24+)
fnm use 24
npm install
```

> macOS / Linux users are recommended to use `fnm`; Windows users should use
> `nvm-windows`.
> The authoritative Node version is `engines.node` in
> `packages/vscode/package.json`.

---

## 2. Local CI Gate (must pass before pushing)

```bash
# Recommended: top-level Makefile (thin wrapper, equivalent to
# `uv run python scripts/ci_gate.py ...`)
make ci                # one-shot Python gate
make vscode-check      # gate + VSCode extension packaging
make coverage          # gate + coverage XML report
make help              # list every shortcut

# Equivalent direct entrypoints (kept because CI workflows still call them)
uv run python scripts/ci_gate.py
uv run python scripts/ci_gate.py --with-vscode

# i18n red team only (use when debugging the i18n runtime alone)
node scripts/red_team_i18n_runtime.mjs
```

Requirement: **0 warning · 0 error · all tests green**.

> The Makefile is an alias layer; the source of truth remains
> `scripts/ci_gate.py`.  See the _Makefile shortcuts_ table in
> [`scripts/README.md`](../scripts/README.md) for the mapping.

### 2.1 Pre-commit hooks — fix root cause, never `--no-verify`

When a `git commit` is rejected by a pre-commit hook (build artifact
freshness, lint, type-check, locale parity, brand-color guardrails,
etc.), the **only** acceptable response is to **fix the underlying
cause** and re-commit:

- ❌ `git commit --no-verify -m "..."` — bypasses every hook, hides
  real problems from review.
- ❌ `SKIP=hook-id git commit -m "..."` — skips one hook, often masks
  a real freshness drift.
- ✅ Read the hook's error message → run the suggested regen script
  (`scripts/minify_assets.py` / `scripts/precompress_static.py` /
  `scripts/gen_pseudo_locale.py` / etc.) → `git add -A` → re-commit.
- ✅ If you genuinely believe the hook is wrong, update the hook
  itself or its config, **not** the commit that triggered it.

The narrow exception is **rebase-in-progress** scenarios where you've
already verified the artifacts manually; in those cases bypass needs
explicit reviewer sign-off in the PR description.

This rule was strengthened after cr33 cycle (`16dbc34` review),
where a custom-sound CSS change initially hit the R66 brand-color
guardrail. The right fix was to switch from `var(--color-primary,
#007aff)` to the project's actual design token `--primary-500`,
not to suppress the lint.

<!--
Editor note: the `16dbc34` reference above is the cr33 commit
documenting this exact case. It is **illustrative**: feel free
to replace it with a more recent or canonical example when one
appears, but keep the underlying rule unchanged.
-->


---

## 3. Commit style

Format: `<emoji> <type>(<scope>): <subject>`

| Emoji  | Type     | Notes                                                                                                  |
| ------ | -------- | ------------------------------------------------------------------------------------------------------ |
| ✨     | feat     | New feature (non-breaking)                                                                             |
| 🐛     | fix      | Bug fix                                                                                                |
| 📝     | docs     | Documentation only                                                                                     |
| ✅ / 🧪 | test     | Test-related (`🧪` for new / expanded coverage; `✅` for stabilising, fixing, or migrating existing tests) |
| 🔧     | chore    | Chores, CI, dependencies                                                                               |
| 🔒     | security | Security-related                                                                                       |
| ♻️     | refactor | Behaviour-preserving refactor                                                                          |
| 💥     | breaking | Breaking change (must be flagged explicitly in the PR title)                                           |
| 🔖     | release  | Version bump                                                                                           |

Examples:

```
✨ feat(mcp): expose server metadata, tool annotations, and icons
🐛 fix(notification): route Bark through MCP backend for plugin-only sessions
📝 docs(release): introduce CHANGELOG and link from READMEs
🧪 test(server-identity): cover icon/version fallback paths
✅ test: silence expected retry warnings, raise perf-test queue cap
```

---

## 3.bis Frontend FOUC checklist for `<html data-*>` writers

> Codified in cr45 §4.1 from R250 perf-audit-cycle-3
> findings.

**Any** JS module that writes a `data-*` attribute to
`<html>` (theme, locale, density, color-scheme, etc.) must
be **paired with a synchronous inline `<head>` pre-write**.
Otherwise the page renders for ~50-500 ms with stale CSS
variables before the deferred script catches up — visible
as a "flash" (FOUC = Flash of Unstyled Content).

**Required pairing checklist**:

| Item | Status |
|---|---|
| 1. Module writes `<html data-X>` from JS? | If yes, continue |
| 2. Inline `<head>` IIFE reads same `localStorage` key + resolves any `"auto"` value | Required |
| 3. Inline IIFE writes `<html data-X>` before any `<link rel="preload">` | Required |
| 4. Inline IIFE wrapped in `try/catch` (privacy mode / sandbox / disabled storage) | Required |
| 5. CSP nonce preserved: `<script nonce="{{ csp_nonce }}">` | Required |
| 6. Tests assert ordering (inline → preload → defer) | Required |
| 7. Tests assert `localStorage` key string matches module's `STORAGE_KEY` literal | Required |

**Reference implementation**:
- Production: `templates/web_ui.html` "Anti-FOUC theme
  bootstrap" IIFE (R250)
- Tests: `tests/test_feat_perf_audit_cycle3_anti_fouc.py`
  (10 invariants)
- Audit: `docs/perf-audit-cycle-3.md` §2.2

**Future extension example**: if a `<html data-locale>`
attribute is added for SSR locale handling, mirror the
anti-FOUC pattern with `localStorage.getItem("locale-
preference")` + `navigator.language` fallback.

---

## 3.quater i18n wrapper function checklist

> Codified in a11y-audit-cycle-5 §2.2 P3 from
> cycle-4 R259c (the `_resolveLabel` orphan-key
> false-positive incident).

The project has 7 i18n wrapper functions, all
**must** be registered in the call-site regex:

| Wrapper | Where defined | Used for |
|---------|---------------|----------|
| `_t` / `t` | `static/js/i18n.js` | universal Web UI t() |
| `_tl` | `static/js/i18n.js` | t() + locale interpolation |
| `hostT` | `packages/vscode/extension.ts` | VSCode extension host |
| `__vuT` | `static/js/validation-utils.js` | local helper (avoid import cycle) |
| `__domSecT` | `static/js/dom-security.js` | local helper |
| `__ncT` | `static/js/webview-notify-core.js` | local helper (P8) |
| `AIIA_I18N.t` | `static/js/i18n.js` (namespace) | multi_task.js dot-access |
| `_resolveLabel` | `static/js/ios_a2hs_hint.js` | fallback-aware i18n |

**Adding a new wrapper**: you **must** update **both**
of these files in lockstep, or you'll silently break
i18n orphan/dead-key detection:

1. `scripts/check_i18n_orphan_keys.py` → `JS_T_CALL_RE`
2. `tests/test_runtime_behavior.py` → `_JS_T_CALL_RE`

**Regex pattern**:

```
(?:(?<![.\w])(?:_?tl?|hostT|__vuT|__domSecT|__ncT|YOUR_NEW_NAME)|AIIA_I18N\.t)\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]
```

Add your function name to the `(?:...)` alternation.
Run both `pytest tests/test_i18n_orphan_keys.py` and
`pytest tests/test_runtime_behavior.py::TestI18nDeadKeys`
to verify no orphan/dead-key false-positives appear.

---

## 3.ter Recurring design constraint for new color tokens

> Codified in cr48 §4 saturation signal: light
> `--bg-primary #e8e6dc` (Anthropic warm beige) has
> been the contrast-constraining axis in **3
> consecutive a11y-audit cycles** (cycle-2 L2 + L5,
> cycle-3 L2).

When introducing **any new color token** that may be
used as a foreground (text, icon, focus indicator,
border with `> 1px width`, status indicator), check
contrast against `#e8e6dc` **first** before
designing for the dark theme:

1. WCAG 2.1 SC 1.4.3 (text): ≥ 4.5:1 for normal,
   ≥ 3:1 for large
2. WCAG 2.1 SC 1.4.11 (UI components, focus ring,
   non-text contrast): ≥ 3:1

Use the project's invariant tests as your computation:
- `tests/test_feat_a11y_cycle2_wcag_contrast.py` for
  text + status colors
- `tests/test_feat_a11y_cycle3_wcag_focus_ring.py`
  for focus rings + UI components

**Constraint family-pattern**: light `#e8e6dc` forces
the brightness lower than most web palettes' "500"
shade — your new color usually needs to be in the
"600-700" Tailwind shade range. Don't trust your eye;
let the WCAG ratio test be the gate.

If your token cannot reach AA-normal (4.5:1) on
`#e8e6dc` and still maintain semantic meaning, document
the **AA-large fallback** path in the test file + CSS
comment.

---

## 3.quinquies Standard CSS tokens for a11y

After a11y-audit cycles 1-7, the project has crystallized
a set of **shared CSS variables** that all new components
should reuse instead of hardcoding hex values:

| Token | Purpose | Dark | Light | Constraint |
|-------|---------|------|-------|------------|
| `--focus-ring-color` | `:focus-visible` outline color (WCAG 1.4.11) | `#a855f7` | `#b35a3c` | ≥ 3:1 on both `--bg-primary` and `--bg-secondary` (cycle-3 R258) |
| `--error-500` | Error text + icons | `#f87171` | `#b03d38` | AA-normal text on `--bg-primary` (cycle-2 R257b, cycle-4 R259a) |
| `--success-500`, `--warning-500`, `--info-500` | Status text | varies | varies | AA-normal text (cycle-2 R257b) |
| `--text-tertiary` | Strikethrough-only foreground | `#98989e` | `#757470` | AA-large (use ONLY for strikethrough; cycle-2 R257) |
| `--text-muted` | **Background-only** | varies | varies | NEVER as `color:` (cycle-4 R259) |

**`:focus-visible` rule template** (cycle-3 R258 / cycle-5 R259g):

```css
.your-component:focus-visible {
  outline: 2px solid
    var(--focus-ring-color, var(--primary-500, currentColor));
  outline-offset: 2px;
}
```

The triple fallback chain protects against ordering bugs
in stylesheet load: `--focus-ring-color` > `--primary-500`
> `currentColor`. **Never hardcode `var(--primary-500)`**
without the `--focus-ring-color` first — this regressed
in cycle-3 and was swept in cycle-5 Track C.

**`@media (prefers-contrast: more)` adapter** (cycle-1 R256)
is already shipped in `@layer a11y` and globally upgrades
any `:focus-visible` to `4px Highlight outline` for OS-level
high-contrast users. Your component automatically inherits.

---

## 4. Pull request flow

1. Branch off `main`: `git checkout -b feat/<short-name>`
2. Run the local CI Gate until it is fully green → push to your fork → open a PR
3. Fill the PR description using
   [`PULL_REQUEST_TEMPLATE.md`](PULL_REQUEST_TEMPLATE.md)
4. Self-review the main paths affected by the change at least once
5. Wait for GitHub Actions (`Tests` / `VSCode Extension` / `CodeQL` /
   `Scorecard`) to go green
6. Maintainer review · squash or `--no-ff` merge once approved

---

## 5. Where to ask

- 🐛 **Bug** → [Issues](https://github.com/xiadengma/ai-intervention-agent/issues/new?template=bug_report.yml)
- ✨ **Feature** → [Issues](https://github.com/xiadengma/ai-intervention-agent/issues/new?template=feature_request.yml)
- 💬 **Question / Idea** → [Discussions](https://github.com/xiadengma/ai-intervention-agent/discussions)
- 🔐 **Security** → [Private Vulnerability Reporting](https://github.com/xiadengma/ai-intervention-agent/security/advisories/new) (do **not** open a public issue)

---

## 6. Code of Conduct

By participating you agree to abide by the project's
[Code of Conduct](CODE_OF_CONDUCT.md).
