# AI Intervention Agent · Documentation index

This directory holds all long-form docs for `ai-intervention-agent`.
Find your role below to jump straight to the page you need.

> 中文版：[`README.zh-CN.md`](README.zh-CN.md)

## End users · just want it to work

- [`configuration.md`](configuration.md) · [`configuration.zh-CN.md`](configuration.zh-CN.md)
  — full TOML reference (`config.toml`), every setting with default and reload semantics.
- [`troubleshooting.md`](troubleshooting.md) · [`troubleshooting.zh-CN.md`](troubleshooting.zh-CN.md)
  — nine most common issues ("port in use", "VS Code panel blank",
  "notifications silent", "mDNS broken", "Bark notification opens
  Bark instead of the PWA", etc.) with symptom → cause → fix.
- [`mcp_tools.md`](mcp_tools.md) · [`mcp_tools.zh-CN.md`](mcp_tools.zh-CN.md)
  — server-level metadata plus the single `interactive_feedback`
  tool's I/O schema. Drop it in front of Cursor / Claude Desktop /
  ChatGPT Desktop and you have a contract.

## Contributors · adding code or translations

- [`workflow.md`](workflow.md) · [`workflow.zh-CN.md`](workflow.zh-CN.md)
  — recommended dev cycle: branching strategy, local CI Gate
  command, release flow.
- [`i18n.md`](i18n.md) — single source of truth for everything i18n:
  how `t()` works at runtime, what each `check_i18n_*.py` gate
  enforces, how to add a new locale or extend the pseudo locale.
- [`api/index.md`](api/index.md) · [`api.zh-CN/index.md`](api.zh-CN/index.md)
  — auto-generated module reference for the public Python surface:
  core contract modules (`config_manager`, `notification_*`,
  `task_queue`, `protocol`, `state_machine`, `server`,
  `server_feedback`, `server_config`, `service_manager`, `web_ui`,
  `web_ui_security`, `web_ui_validators`, `exceptions`) and utility
  modules (`config_utils`, `i18n`, `shared_types`,
  `notification_models`, `file_validator`, `enhanced_logging`,
  `web_ui_config_sync`, `web_ui_mdns`, `web_ui_mdns_utils`).
  Regenerate with
  `uv run python scripts/generate_docs.py`; verify drift with
  `make docs-check` (or
  `uv run python scripts/generate_docs.py --check`).

## Operators · running it on a real machine

- [`noise-levels.zh-CN.md`](noise-levels.zh-CN.md) — broadcast-level
  contract for aria-live / toast / log / status-bar. Required
  reading before you decide whether a new event should be `quiet` /
  `assert` / `polite`.

## Reviewers · auditing security or releases

- [`security/AUDIT_2026-05-04.md`](security/AUDIT_2026-05-04.md) —
  most recent dependency-vulnerability audit (`pip-audit`) with
  the upgrade recipe and remaining-CVE rationale.
- [`../SECURITY.md`](../SECURITY.md) — disclosure policy, supported
  versions, AppleScript executor security model.
- [`lessons-learned-r60s.md`](lessons-learned-r60s.md) — internal
  post-mortem for the v1.5.45 R63 → R70 batch (light-mode iOS-blue
  leakage, MCP-tool-description drift, Bark deep-link sentinel,
  build-info diagnostic, Prettier rollout, Dependabot major-bump
  triage, README architecture completeness). Required reading
  before adding a new CSS theme variant or a new MCP tool field.
- [`security-triage-r72.md`](security-triage-r72.md) — line-by-line
  disposition of every GitHub code-scanning alert open as of the
  May 2026 sweep. Documents the R72-A (15 × log-injection via
  global root InterceptHandler) and R72-B (1 × stack-trace exposure
  in `open-config-file`) fixes, the 20 false-positive dismissals
  with justifications, and the OpenSSF Scorecard governance items
  intentionally won't-fix.

## Bilingual coverage

User-facing docs ship in both English and Chinese (`<name>.md` plus
`<name>.zh-CN.md`). Internal references that are English-source
(API auto-gen, [`i18n.md`](i18n.md)) or Chinese-source
([`noise-levels.zh-CN.md`](noise-levels.zh-CN.md),
[`security/AUDIT_*`](security/)) keep just the original language to
avoid translation drift.

---

_Refresh this file alongside any docs/ addition or rename so the
index never lies. Last refreshed for v1.5.45 (R63 → R70 batch:
diagnostic build-info under `aiia://server/info`, Bark deep-link
`aiia_test=1` sentinel, MCP `predefined_options_defaults` schema
parameter, light-mode button text + 7 iOS-blue leakage fixes,
brand-color drift guardrail with pre-commit hook, README inner-
modules pointer + Dependency Review FAQ, Prettier-defaults
overhaul across `multi_task.js` / VSCode TS-JS / docs Markdown /
`settings-manager.js` + `web_ui.html`). Internal post-mortem at
[`lessons-learned-r60s.md`](lessons-learned-r60s.md). Earlier
R57 / R58 work (Flask-Limiter `headers_enabled=True` + 256 KB SSE
oversize guard) remains captured in v1.5.44; older R56 → R50 in
v1.5.43 → v1.5.39._
