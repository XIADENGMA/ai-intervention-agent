# Contributing · 贡献指南

Thanks for considering a contribution! 感谢愿意贡献代码。

This file is the **entry point**; the full development / release workflow lives in
[`docs/workflow.md`](docs/workflow.md) (English) and
[`docs/workflow.zh-CN.md`](docs/workflow.zh-CN.md) (中文).

本文档只列**最小必备清单**；详细的本地开发 / 发布流程见上述两份 `docs/workflow*.md`。

---

## 1. Getting started · 准备环境

```bash
# Clone
git clone https://github.com/xiadengma/ai-intervention-agent.git
cd ai-intervention-agent

# Python 工具链（uv 自带 venv + dependency resolver）
uv sync

# Node 工具链（VSCode 扩展才需要；用 fnm 管 Node 24+）
fnm use 24
npm install
```

> macOS / Linux 用户推荐 `fnm`，Windows 用户用 `nvm-windows`。
> Node 版本以 `packages/vscode/package.json` `engines.node` 为准。

---

## 2. Local CI Gate · 提交前必跑的本地门禁

```bash
# Python 一键全量门禁
uv run python scripts/ci_gate.py

# 含 VSCode 扩展打包验证
uv run python scripts/ci_gate.py --with-vscode

# 仅看 i18n 红队
node scripts/red_team_i18n_runtime.mjs
```

要求：**0 warning · 0 error · 测试全绿**。

---

## 3. Commit style · 提交风格

格式：`<emoji> <type>(<scope>): <subject>`

| Emoji | Type        | 说明                                |
| ----- | ----------- | ----------------------------------- |
| ✨    | feat        | 新功能（非破坏性）                  |
| 🐛    | fix         | Bug 修复                            |
| 📝    | docs        | 仅文档                              |
| ✅ / 🧪 | test      | 测试相关（`🧪` 推荐用于扩展/新增覆盖；`✅` 用于已有测试的稳定化、修复或迁移） |
| 🔧    | chore       | 杂务、CI、依赖                      |
| 🔒    | security    | 安全相关                            |
| ♻️    | refactor    | 行为不变的重构                      |
| 💥    | breaking    | 破坏性变更（PR 标题必须显式标注）   |
| 🔖    | release     | 版本号 bump                         |

例：

```
✨ feat(mcp): expose server metadata, tool annotations, and icons
🐛 fix(notification): route Bark through MCP backend for plugin-only sessions
📝 docs(release): introduce CHANGELOG and link from READMEs
🧪 test(server-identity): cover icon/version fallback paths
✅ test: silence expected retry warnings, raise perf-test queue cap
```

---

## 4. Pull request flow · PR 流程

1. 从 `main` 分支拉 feature 分支：`git checkout -b feat/<short-name>`
2. 本地跑 CI Gate 全绿 → push 到 fork → 开 PR
3. PR 描述按 [`PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) 模板填写
4. 至少自审一次受影响的主路径
5. 等待 GitHub Actions（`Tests` / `VSCode Extension` / `CodeQL` / `Scorecard`）全绿
6. Maintainer review · 通过后 squash 或 `--no-ff` merge

---

## 5. Where to ask · 提问 / 反馈通道

- 🐛 **Bug** → [Issues](https://github.com/xiadengma/ai-intervention-agent/issues/new?template=bug_report.yml)
- ✨ **Feature** → [Issues](https://github.com/xiadengma/ai-intervention-agent/issues/new?template=feature_request.yml)
- 💬 **Question / Idea** → [Discussions](https://github.com/xiadengma/ai-intervention-agent/discussions)
- 🔐 **Security** → [Private Vulnerability Reporting](https://github.com/xiadengma/ai-intervention-agent/security/advisories/new)（请勿公开 issue）

---

## 6. Code of Conduct · 行为准则

参与本项目即同意遵守 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。
By participating you agree to abide by the project's
[Code of Conduct](CODE_OF_CONDUCT.md).
