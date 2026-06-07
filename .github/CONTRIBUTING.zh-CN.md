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

## 3.bis 前端 `<html data-*>` 写入者 FOUC 检查清单

> 源自 cr45 §4.1 / R250 perf-audit-cycle-3 经验。

任何从 JS 写入 `<html data-X>` 属性（主题 / locale /
密度 / color-scheme 等）的模块，都**必须配对**一个
`<head>` 内同步 inline `<script>` 提前写入相同 attribute。
否则页面会以"错误 CSS 变量"渲染 ~50-500ms，等 deferred
脚本 fire 后突变，肉眼可感"闪一下"（FOUC = Flash of
Unstyled Content）。

**配对必查项**：

| 项 | 状态 |
|---|---|
| 1. 模块从 JS 写 `<html data-X>`？ | 是 → 必须配对 |
| 2. `<head>` 内 inline IIFE 读相同 localStorage key + 处理 `"auto"` 解析 | 必需 |
| 3. inline IIFE 在所有 `<link rel="preload">` 之前写 `<html data-X>` | 必需 |
| 4. inline IIFE 用 `try/catch` 兜底（隐私模式 / sandbox / 禁用存储）| 必需 |
| 5. 保留 CSP nonce：`<script nonce="{{ csp_nonce }}">` | 必需 |
| 6. 测试验证执行顺序（inline → preload → defer） | 必需 |
| 7. 测试验证 `localStorage` key 字符串与模块 `STORAGE_KEY` 字面量一致 | 必需 |

**参考实现**：
- 生产代码：`templates/web_ui.html` "Anti-FOUC theme
  bootstrap" IIFE (R250)
- 测试：`tests/test_feat_perf_audit_cycle3_anti_fouc.py`
  （10 个不变量）
- 审计文档：`docs/perf-audit-cycle-3.md` §2.2

**未来扩展示例**：如果新增 `<html data-locale>` 用于 SSR
locale 处理，照搬 anti-FOUC 模式：`localStorage.getItem
("locale-preference")` + `navigator.language` fallback。

---

## 3.quater i18n wrapper 函数 checklist

> 源自 a11y-audit-cycle-5 §2.2 P3 / cycle-4 R259c
> （`_resolveLabel` 被误判 orphan 事件）。

项目有 7 个 i18n wrapper，**必须**在 call-site 正则
里全部注册：

| Wrapper | 定义位置 | 用途 |
|---------|----------|------|
| `_t` / `t` | `static/js/i18n.js` | 通用 Web UI t() |
| `_tl` | `static/js/i18n.js` | t() + locale interpolation |
| `hostT` | `packages/vscode/extension.ts` | VSCode 扩展主进程 |
| `__vuT` | `static/js/validation-utils.js` | 本地 helper (避 import 循环) |
| `__domSecT` | `static/js/dom-security.js` | 本地 helper |
| `__ncT` | `static/js/webview-notify-core.js` | 本地 helper (P8) |
| `AIIA_I18N.t` | `static/js/i18n.js`（命名空间） | multi_task.js dot-access |
| `_resolveLabel` | `static/js/ios_a2hs_hint.js` | 带 fallback 的 i18n |

**加新 wrapper 时**：以下两个文件**必须 lockstep**
更新，否则会悄悄破坏 i18n orphan/dead-key 检测：

1. `scripts/check_i18n_orphan_keys.py` → `JS_T_CALL_RE`
2. `tests/test_runtime_behavior.py` → `_JS_T_CALL_RE`

**正则模式**：

```
(?:(?<![.\w])(?:_?tl?|hostT|__vuT|__domSecT|__ncT|YOUR_NEW_NAME)|AIIA_I18N\.t)\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]
```

在 `(?:...)` alternation 里加你的函数名。运行：

```bash
pytest tests/test_i18n_orphan_keys.py \
       tests/test_runtime_behavior.py::TestI18nDeadKeys
```

确认无 orphan/dead-key false-positive。

---

## 3.ter 新颜色 token 的递归设计约束

> 源自 cr48 §4 saturation signal：light `--bg-primary
> #e8e6dc`（Anthropic 暖米色）在 **连续 3 个 a11y-audit
> cycles** 都是 contrast-constraining axis
> (cycle-2 L2 + L5，cycle-3 L2)。

引入任何新颜色 token 时，若可能用作 foreground（文本、
图标、focus indicator、宽 > 1px 的边框、状态指示器），
**必须先**检查与 `#e8e6dc` 的对比度，再设计 dark theme：

1. WCAG 2.1 SC 1.4.3（text）：normal ≥ 4.5:1，
   large ≥ 3:1
2. WCAG 2.1 SC 1.4.11（UI 组件、focus ring、non-text
   contrast）：≥ 3:1

用项目自带的 invariant 测试做计算：
- `tests/test_feat_a11y_cycle2_wcag_contrast.py`：
  text + status 色
- `tests/test_feat_a11y_cycle3_wcag_focus_ring.py`：
  focus ring + UI 组件

**约束家族模式**：light `#e8e6dc` 要求亮度比大部分 web
palette 的 "500" shade 都低 —— 新颜色通常需要落在
Tailwind "600-700" shade 区间。**不要相信肉眼判断**，
让 WCAG ratio 测试当 gate。

如果 token 在 `#e8e6dc` 上无法达 AA-normal (4.5:1)
且需保持语义，把 **AA-large fallback** 路径明确写
进测试 + CSS 注释。

---

## 3.quinquies 标准 CSS a11y token

经 a11y-audit cycles 1-7 沉淀，项目已固化一组**通用
CSS 变量**，新组件应当复用而非硬编码 hex：

| Token | 用途 | Dark | Light | 约束 |
|-------|------|------|-------|------|
| `--focus-ring-color` | `:focus-visible` 外环色 (WCAG 1.4.11) | `#a855f7` | `#b35a3c` | 同时满足 `--bg-primary` 与 `--bg-secondary` ≥ 3:1 (cycle-3 R258) |
| `--error-500` | 错误文字 + 图标 | `#f87171` | `#b03d38` | AA-normal 文字 (cycle-2 R257b, cycle-4 R259a) |
| `--success-500`, `--warning-500`, `--info-500` | 状态文字 | varies | varies | AA-normal 文字 (cycle-2 R257b) |
| `--text-tertiary` | 仅删除线前景 | `#98989e` | `#757470` | AA-large（**仅限删除线**，cycle-2 R257）|
| `--text-muted` | **仅背景** | varies | varies | 禁作 `color:` 用 (cycle-4 R259) |

**`:focus-visible` 规则模板** (cycle-3 R258 / cycle-5 R259g)：

```css
.your-component:focus-visible {
  outline: 2px solid
    var(--focus-ring-color, var(--primary-500, currentColor));
  outline-offset: 2px;
}
```

三段 fallback chain 防 stylesheet 加载顺序 bug：
`--focus-ring-color` > `--primary-500` > `currentColor`。
**禁止硬绑 `var(--primary-500)`** 而不加 `--focus-ring-color`
前置 —— cycle-3 此处出过回归，cycle-5 Track C 已全量扫清。

**`@media (prefers-contrast: more)` 适配** (cycle-1 R256)
已 ship 进 `@layer a11y`，对所有 `:focus-visible` 全局
升级为 `4px Highlight outline`，自动覆盖 OS 高对比度
模式用户。新组件无需手写。

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
