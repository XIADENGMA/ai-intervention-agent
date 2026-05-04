# AI Intervention Agent · Documentation index

This directory holds all long-form docs for `ai-intervention-agent`.
Find your role below to jump straight to the page you need.

> 中文版：[`README.zh-CN.md`](README.zh-CN.md)

## End users · just want it to work

- [`configuration.md`](configuration.md) · [`configuration.zh-CN.md`](configuration.zh-CN.md)
  — full TOML reference (`config.toml`), every setting with default and reload semantics.
- [`troubleshooting.md`](troubleshooting.md) · [`troubleshooting.zh-CN.md`](troubleshooting.zh-CN.md)
  — eight most common issues ("port in use", "VS Code panel blank",
  "notifications silent", "mDNS broken", etc.) with
  symptom → cause → fix.
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
  `server_config`, `exceptions`) and utility modules
  (`config_utils`, `i18n`,
  `shared_types`, `notification_models`, `file_validator`,
  `enhanced_logging`). Regenerate with
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

## Bilingual coverage

User-facing docs ship in both English and Chinese (`<name>.md` plus
`<name>.zh-CN.md`). Internal references that are English-source
(API auto-gen, [`i18n.md`](i18n.md)) or Chinese-source
([`noise-levels.zh-CN.md`](noise-levels.zh-CN.md),
[`security/AUDIT_*`](security/)) keep just the original language to
avoid translation drift.

---

_Refresh this file alongside any docs/ addition or rename so the
index never lies. Last refreshed for v1.5.22._
