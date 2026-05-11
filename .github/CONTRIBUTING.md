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
