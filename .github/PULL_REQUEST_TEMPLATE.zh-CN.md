<!--
  中文模板。需要切换到此模板时，在 PR URL 末尾追加
  `?template=PULL_REQUEST_TEMPLATE.zh-CN.md`，或直接在 GitHub 的 PR 创建页选择
  "PULL_REQUEST_TEMPLATE.zh-CN.md"。
  English template: `PULL_REQUEST_TEMPLATE.md`.

  无关章节可直接删除；Dependabot 生成的依赖升级 PR 可整段删除本注释下方内容。
-->

## 变更摘要

<!--
  本 PR 改了什么？为什么要改？
-->

Fixes #

## 变更类型

- [ ] 🐛 Bug fix · 缺陷修复（非破坏性）
- [ ] ✨ New feature · 新功能（非破坏性）
- [ ] 💥 Breaking change · 破坏性变更（API / 行为 / 文件布局）
- [ ] 📖 Docs · 仅文档更新
- [ ] 🔧 Chore / CI · 构建、工具链、流水线
- [ ] ♻️ Refactor · 纯重构（行为不变）

## 本地验证

<!--
  勾选你已实际跑过的项；仅修改文档或配置可以酌情跳过对应项。
  命令细节见 docs/workflow.zh-CN.md / docs/workflow.md。
  Makefile shortcut 形式（thin wrapper）等价于 uv 直调形式，挑你顺手的即可。
-->

- [ ] `make ci` 或 `uv run python scripts/ci_gate.py`（ruff / ty / pytest / minify 全绿）
- [ ] `make vscode-check` 或 `uv run python scripts/ci_gate.py --with-vscode`（若改动 VSCode 扩展 / 发布前必跑）
- [ ] `node scripts/red_team_i18n_runtime.mjs`（若改动 i18n 运行时 / 翻译 / locale JSON）
- [ ] `uv run python scripts/bump_version.py --check`（若改动任何带版本号的元文件）
- [ ] `make docs-check`（若改动 Python 公共 API / docstring，确认 `docs/api{,.zh-CN}/` 不漂移）

## 影响面

- [ ] Web UI（`src/ai_intervention_agent/static/`, `src/ai_intervention_agent/templates/`, `src/ai_intervention_agent/web_ui*.py`）
- [ ] VSCode 扩展（`packages/vscode/`）
- [ ] MCP server / runtime（`src/ai_intervention_agent/task_queue.py`, `src/ai_intervention_agent/web_ui_routes/`, `packages/vscode/applescript-executor.ts`）
- [ ] i18n 翻译（`src/ai_intervention_agent/static/locales/`, `packages/vscode/locales/`, `packages/vscode/l10n/`, `packages/vscode/package.nls*.json`）
- [ ] CI / 发布（`.github/workflows/`, `scripts/ci_gate.py`, `scripts/package_vscode_vsix.mjs`）
- [ ] 文档（`README*.md`, `docs/**`）

## 截图

<!--
  Web UI 或 VSCode webview 的变更请贴前/后对比图。CLI 改动贴终端输出即可。
-->

## 自查清单

- [ ] 代码风格与既有约定一致；注释以「非必要不保留」为原则
- [ ] 用户可见字符串已走 i18n（`t('...')` / `vscode.l10n.t(...)`），**没有**硬编码 CJK
- [ ] 新增 / 修改的 locale key 在所有 locale 对齐（`en`, `zh-CN`, `_pseudo`）
- [ ] 已 self-review，至少本地运行过一次受影响的主路径
- [ ] 若是面向用户的变更 → README / CHANGELOG / docs 已同步
- [ ] 若是破坏性变更 → PR 标题已显式标注并在描述中说明迁移路径
