# 贡献指南

> [English](./CONTRIBUTING.md) | 简体中文

感谢愿意贡献代码。

本文档只是**入口**，完整的本地开发 / 发布流程见
[`docs/workflow.md`](../docs/workflow.md)（英文）和
[`docs/workflow.zh-CN.md`](../docs/workflow.zh-CN.md)（中文）。

本文档只列**最小必备清单**；详细的本地开发 / 发布流程见上述两份
`docs/workflow*.md`。

---

## 1. 准备环境

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

## 2. 提交前必跑的本地门禁

```bash
# 推荐：通过顶层 Makefile（thin wrapper，等价于 uv run python scripts/ci_gate.py …）
make ci                # Python 一键全量门禁
make vscode-check      # 含 VSCode 扩展打包验证
make coverage          # 全量门禁 + 覆盖率 XML 报告
make help              # 列出所有快捷命令

# 等价的直调入口（CI 工作流仍在用，下面命令保留是为了脚本/CI 引用）
uv run python scripts/ci_gate.py
uv run python scripts/ci_gate.py --with-vscode

# 仅看 i18n 红队（独立调试 i18n 实现时用）
node scripts/red_team_i18n_runtime.mjs
```

要求：**0 warning · 0 error · 测试全绿**。

> Makefile 仅是别名，源真理仍在 `scripts/ci_gate.py`；详见
> [`scripts/README.md`](../scripts/README.md) 的 _Makefile shortcuts_ 表。

### 2.1 pre-commit hooks — 永远修根因，禁用 `--no-verify`

当 `git commit` 被 pre-commit hook 拒绝（如构建产物新鲜度、lint、
type-check、locale 对齐、品牌色护栏等），**唯一**正确的回应是
**修根因**后重新提交：

- ❌ `git commit --no-verify -m "..."` — 跳过所有 hook，把真问题
  藏起来不让 review 看到。
- ❌ `SKIP=hook-id git commit -m "..."` — 单独跳一个 hook，往往
  掩盖了真实的产物漂移。
- ✅ 阅读 hook 的报错信息 → 运行它推荐的脚本（`scripts/
  minify_assets.py` / `scripts/precompress_static.py` /
  `scripts/gen_pseudo_locale.py` 等）→ `git add -A` → 重新提交。
- ✅ 如果你确认 hook 本身错了，去改 hook 或者它的配置，**不要**
  改触发它的那个 commit。

唯一狭窄的例外：rebase 进行中、你已经手工验证过产物的场景，需要
PR 描述里显式拿到 reviewer 的同意才能 bypass。

本规则在 cr33 cycle (`16dbc34`) 之后被强化 —— 当时 custom-sound
CSS 改动撞上了 R66 品牌色护栏，正确的修法是把 `var(--color-primary,
#007aff)` 改成项目实际的 design token `--primary-500`，而不是
压制 lint。

<!--
Editor note: 上面的 `16dbc34` 引用是 cr33 当时这个 case 的 commit。
仅作**示例**用：未来出现更近期/更典型的案例时可以替换，但底层规则
不变。
-->


---

## 3. 提交风格

格式：`<emoji> <type>(<scope>): <subject>`

| Emoji  | Type     | 说明                                                                                                |
| ------ | -------- | --------------------------------------------------------------------------------------------------- |
| ✨     | feat     | 新功能（非破坏性）                                                                                  |
| 🐛     | fix      | Bug 修复                                                                                            |
| 📝     | docs     | 仅文档                                                                                              |
| ✅ / 🧪 | test     | 测试相关（`🧪` 推荐用于扩展/新增覆盖；`✅` 用于已有测试的稳定化、修复或迁移）                       |
| 🔧     | chore    | 杂务、CI、依赖                                                                                      |
| 🔒     | security | 安全相关                                                                                            |
| ♻️     | refactor | 行为不变的重构                                                                                      |
| 💥     | breaking | 破坏性变更（PR 标题必须显式标注）                                                                   |
| 🔖     | release  | 版本号 bump                                                                                         |

例：

```
✨ feat(mcp): expose server metadata, tool annotations, and icons
🐛 fix(notification): route Bark through MCP backend for plugin-only sessions
📝 docs(release): introduce CHANGELOG and link from READMEs
🧪 test(server-identity): cover icon/version fallback paths
✅ test: silence expected retry warnings, raise perf-test queue cap
```

---

## 4. PR 流程

1. 从 `main` 分支拉 feature 分支：`git checkout -b feat/<short-name>`
2. 本地跑 CI Gate 全绿 → push 到 fork → 开 PR
3. PR 描述按 [`PULL_REQUEST_TEMPLATE.md`](PULL_REQUEST_TEMPLATE.md) 模板填写
4. 至少自审一次受影响的主路径
5. 等待 GitHub Actions（`Tests` / `VSCode Extension` / `CodeQL` / `Scorecard`）全绿
6. Maintainer review · 通过后 squash 或 `--no-ff` merge

---

## 5. 提问 / 反馈通道

- 🐛 **Bug** → [Issues](https://github.com/xiadengma/ai-intervention-agent/issues/new?template=bug_report.yml)
- ✨ **Feature** → [Issues](https://github.com/xiadengma/ai-intervention-agent/issues/new?template=feature_request.yml)
- 💬 **Question / Idea** → [Discussions](https://github.com/xiadengma/ai-intervention-agent/discussions)
- 🔐 **Security** → [Private Vulnerability Reporting](https://github.com/xiadengma/ai-intervention-agent/security/advisories/new)（请勿公开 issue）

---

## 6. 行为准则

参与本项目即同意遵守 [`CODE_OF_CONDUCT.zh-CN.md`](CODE_OF_CONDUCT.zh-CN.md)。
