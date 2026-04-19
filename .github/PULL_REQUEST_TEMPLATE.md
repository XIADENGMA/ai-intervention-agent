<!--
  中文 / English 双语模板，保留与你习惯一致的分节；按需删除无关章节。
  若这是依赖升级 PR 由 Dependabot 生成，可直接删除此注释以下所有内容。
-->

## Summary · 变更摘要

<!--
  - What does this PR change and why?
  - 本 PR 改了什么？为什么要改？
-->

Fixes #

## Type of change · 变更类型

- [ ] 🐛 Bug fix · 缺陷修复（非破坏性）
- [ ] ✨ New feature · 新功能（非破坏性）
- [ ] 💥 Breaking change · 破坏性变更（API / 行为 / 文件布局）
- [ ] 📖 Docs · 仅文档更新
- [ ] 🔧 Chore / CI · 构建、工具链、流水线
- [ ] ♻️ Refactor · 纯重构（行为不变）

## Local verification · 本地验证

<!--
  勾选你已实际跑过的项；仅修改文档或配置可以酌情跳过对应项。
  命令细节见 docs/workflow.zh-CN.md / docs/workflow.md。
-->

- [ ] `uv run python scripts/ci_gate.py`（ruff / ty / pytest / minify 全绿）
- [ ] `uv run python scripts/ci_gate.py --with-vscode`（若改动 VSCode 扩展 / 发布前必跑）
- [ ] `node scripts/red_team_i18n_runtime.mjs`（若改动 i18n 运行时 / 翻译 / locale JSON）
- [ ] `uv run python scripts/bump_version.py --check`（若改动任何带版本号的元文件）

## Touched areas · 影响面

- [ ] Web UI（`static/`, `templates/`, `web_ui*.py`）
- [ ] VSCode 扩展（`packages/vscode/`）
- [ ] MCP server / runtime（`task_queue.py`, `web_ui_routes/`, `applescript-executor.ts`）
- [ ] i18n 翻译（`static/locales/`, `packages/vscode/locales/`, `packages/vscode/l10n/`, `packages/vscode/package.nls*.json`）
- [ ] CI / 发布（`.github/workflows/`, `scripts/ci_gate.py`, `scripts/package_vscode_vsix.mjs`）
- [ ] 文档（`README*.md`, `docs/**`）

## Screenshots · 截图

<!--
  Web UI 或 VSCode webview 的变更请贴前/后对比图。CLI 改动贴终端输出即可。
-->

## Checklist · 自查

- [ ] 代码风格与既有约定一致；注释以「非必要不保留」为原则
- [ ] 用户可见字符串已走 i18n（`t('...')` / `vscode.l10n.t(...)`），**没有**硬编码 CJK
- [ ] 新增 / 修改的 locale key 在所有 locale 对齐（`en`, `zh-CN`, `_pseudo`）
- [ ] 已 self-review，至少本地运行过一次受影响的主路径
- [ ] 若是面向用户的变更 → README / CHANGELOG / docs 已同步
- [ ] 若是破坏性变更 → PR 标题已显式标注并在描述中说明迁移路径
