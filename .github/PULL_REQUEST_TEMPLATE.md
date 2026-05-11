<!--
  English template.  For the Chinese version, append `?template=PULL_REQUEST_TEMPLATE.zh-CN.md`
  to the PR URL, or open the PR with that template selected.
  中文模板请在 PR URL 末尾追加 `?template=PULL_REQUEST_TEMPLATE.zh-CN.md`。

  Delete sections that do not apply.  Dependabot-generated dependency PRs may
  delete everything below this comment.
-->

## Summary

<!--
  What does this PR change and why?
-->

Fixes #

## Type of change

- [ ] 🐛 Bug fix (non-breaking)
- [ ] ✨ New feature (non-breaking)
- [ ] 💥 Breaking change (API / behaviour / file layout)
- [ ] 📖 Docs only
- [ ] 🔧 Chore / CI (build, toolchain, pipeline)
- [ ] ♻️ Refactor (behaviour preserved)

## Local verification

<!--
  Tick the checks you actually ran; docs/config-only changes may skip the
  corresponding rows.  Full command details live in docs/workflow.md /
  docs/workflow.zh-CN.md.  Makefile shortcuts (thin wrappers) are equivalent
  to the direct `uv run` invocations — pick whichever feels more natural.
-->

- [ ] `make ci` or `uv run python scripts/ci_gate.py` (ruff / ty / pytest / minify all green)
- [ ] `make vscode-check` or `uv run python scripts/ci_gate.py --with-vscode` (required when touching the VSCode extension or before a release)
- [ ] `node scripts/red_team_i18n_runtime.mjs` (when touching the i18n runtime, translations, or locale JSON)
- [ ] `uv run python scripts/bump_version.py --check` (when touching any metadata file that carries a version)
- [ ] `make docs-check` (when touching public Python APIs / docstrings; confirms `docs/api{,.zh-CN}/` did not drift)

## Touched areas

- [ ] Web UI (`src/ai_intervention_agent/static/`, `src/ai_intervention_agent/templates/`, `src/ai_intervention_agent/web_ui*.py`)
- [ ] VSCode extension (`packages/vscode/`)
- [ ] MCP server / runtime (`src/ai_intervention_agent/task_queue.py`, `src/ai_intervention_agent/web_ui_routes/`, `packages/vscode/applescript-executor.ts`)
- [ ] i18n translations (`src/ai_intervention_agent/static/locales/`, `packages/vscode/locales/`, `packages/vscode/l10n/`, `packages/vscode/package.nls*.json`)
- [ ] CI / release (`.github/workflows/`, `scripts/ci_gate.py`, `scripts/package_vscode_vsix.mjs`)
- [ ] Documentation (`README*.md`, `docs/**`)

## Screenshots

<!--
  Attach before / after screenshots for Web UI or VSCode webview changes.
  CLI changes can paste terminal output instead.
-->

## Checklist

- [ ] Code style is consistent with existing conventions; comments follow the "only when necessary" principle
- [ ] All user-visible strings go through i18n (`t('...')` / `vscode.l10n.t(...)`); **no** hard-coded CJK characters
- [ ] New / modified locale keys are aligned across every locale (`en`, `zh-CN`, `_pseudo`)
- [ ] Self-reviewed at least once; the primary affected paths were exercised locally
- [ ] User-facing changes → README / CHANGELOG / docs updated in this PR
- [ ] Breaking changes → PR title is explicitly flagged and the description spells out the migration path
