# i18n key 命名规范（IG-8）

> 本文为本项目**双端 i18n**（Web UI `static/locales/*.json` + VSCode 插件
> `packages/vscode/locales/*.json`）的命名约定与跨端同步路径。
>
> 维护目标：
>
> 1. **消除"阶段 1/2 先各加两份、阶段 3 再合并"时的改动发散**：
>    所有新增的跨端共享文案**从第一次引入起就遵守同一命名**，
>    阶段 3 合并只需 1:1 复制，不用改数十处引用。
> 2. **自动守护，不靠自律**：
>    `scripts/check_locales.py` 会在 CI 里强制 `aiia.*` 命名空间在
>    Web UI 与 VSCode 插件两端**完全对齐**，缺了一端 CI 直接红。
> 3. **给 reviewer 一份检查表**：本文 §六「review checklist」可作为
>    PR review 时的硬性检查项，避免靠口头约定。

---

## 一、现状

| 端 | locale 目录 | 顶层 namespace（en.json） |
|----|------------|---------------------------|
| Web UI | `static/locales/` | `page`、`settings`、`status`、`env`、`notify`、`theme` |
| VSCode 插件 | `packages/vscode/locales/` | `settings`、`statusBar`、`ui` |

两端**各自独立维护**，已有约束（通过 `test_runtime_behavior.py::TestLocaleParity`）：

- 同一端内 `en.json` 与 `zh-CN.json` **顶层到叶子的 key 集合必须完全一致**
  （差一个 key CI 红）。

但**没有**跨端一致性约束——这导致未来 T1（三态 UI 统一）/ S3（诊断日志链）
/ P1（aria-live 文案）/ H1（交互提示）等改动会在双端引入"名字相近但不一致"
的 key（比如一端写 `aiia.state.error.title`，另一端写 `aiia.states.error.heading`），
最终阶段 3 合并时需要重写数十处引用。

---

## 二、命名空间三层划分

| 顶层 namespace | 归属 | 跨端同步 | 典型条目 |
|----------------|------|----------|----------|
| `aiia.*` | **跨端共享** | **强制对齐**（`check_locales.py` 守护） | 三态面板、诊断按钮、全局 toast、aria-live 文案、公共命令标题 |
| `page.*` | Web UI 专有 | 无 | 网页结构（header / footer / 拖拽区 / 占位符） |
| `settings.*` | 双端各自独立 | 无 | 设置面板——**两端各写各的**（UI/开关名称本就不一样） |
| `status.*` / `notify.*` / `theme.*` / `env.*` | Web UI 独有 | 无 | 状态栏 / 通知 / 主题 / 环境 |
| `statusBar.*` / `ui.*` | VSCode 独有 | 无 | 状态栏 / 命令面板 |

**核心规则**：

1. **首次需要把一个文案跨端复用时**，就**必须**把它放到 `aiia.*` namespace 下，
   **不要**在一端用 `page.foo.bar`、另一端用 `ui.foo.bar`。
2. **不要**把已经独立多年的 `page.*` / `settings.*` / `statusBar.*` **强行迁移**到
   `aiia.*`——那不是 IG-8 的目标；IG-8 只拦截**新增**共享 key 的发散。
3. **一旦迁移到 `aiia.*`**（比如阶段 3 的 E1「i18n 抽共享模块」），这些 key
   就受跨端 parity 约束，不能随意只改一端。

---

## 三、key 路径与书写规则

### 3.1 路径层次（4 段优先，最多 5 段）

```
aiia.<domain>.<subject>.<attribute>[.<variant>]
```

| 段 | 取值建议 | 示例 |
|----|----------|------|
| `<domain>` | 功能域，限定语义边界 | `state` / `diagnostics` / `command` / `dialog` / `toast` |
| `<subject>` | 具体对象/状态 | `loading` / `empty` / `error` / `copied` / `reconnect` |
| `<attribute>` | 渲染位置 | `title` / `message` / `action` / `tooltip` / `aria` |
| `<variant>` | 变体/条件 | `network` / `timeout` / `server_500` / `default` |

**超过 5 段视为设计信号不对**——要么拆 namespace，要么改 `<attribute>`
的组织方式。

### 3.2 字面量规则

- **全小写 snake_case**：`aiia.state.error.message.server_500`，**不是**
  `aiia.state.error.message.Server500`。
- **层级用 `.`**，**内部连字符用 `_`**（与现有 i18n 保持一致）。
- **动词第三人称/指令式**：`action.retry` 而不是 `action.retrying` /
  `action.try_it`。
- **placeholder 用 `{{name}}`**：与 Web UI `page.countdown` 现有风格一致，
  **不要**混用 `{0}` / `${name}` 两种模板语法。
  - 例：`aiia.state.loading.message` = `"Loading... {{seconds}}s"`

### 3.3 句末标点

- **`title` 类不带末尾句号**（视觉上作为标题处理，尾部句号会显得多余）。
- **`message` 类可以带**（正文描述，带句号更专业）。
- **`action` 类绝不带末尾句号**（按钮文字）。

---

## 四、预留 key 清单（阶段 1/2 的改动将首批落地这些 key）

以下 key **预先登记**在本文，阶段 1/2 改动**必须**使用这些名字，
不要另起炉灶。如果确有遗漏，**先更新本文，再加 key**。

### 4.1 `aiia.state.*`（服务于 T1 三态面板）

```
aiia.state.loading.title
aiia.state.loading.message
aiia.state.empty.title
aiia.state.empty.message.default
aiia.state.empty.message.filtered
aiia.state.error.title
aiia.state.error.message.network
aiia.state.error.message.server_500
aiia.state.error.message.timeout
aiia.state.error.message.unknown
aiia.state.error.action.retry
aiia.state.error.action.open_log
aiia.state.error.action.copy_diagnostics
```

### 4.2 `aiia.diagnostics.*`（服务于 T2 复制诊断 / S3 诊断日志）

```
aiia.diagnostics.copy.title
aiia.diagnostics.copy.action
aiia.diagnostics.copied.toast
aiia.diagnostics.copy.failed
aiia.diagnostics.section.version
aiia.diagnostics.section.platform
aiia.diagnostics.section.connection
aiia.diagnostics.section.recent_errors
aiia.diagnostics.section.config_masked
```

### 4.3 `aiia.command.*`（服务于 P2 命令可发现性）

```
aiia.command.reconnect.title
aiia.command.showLog.title
aiia.command.reportIssue.title
aiia.command.openSettings.title
aiia.command.copyDiagnostics.title
```

### 4.4 `aiia.toast.*`（服务于全局 toast，归 IG-6 噪音等级约定）

```
aiia.toast.connection.restored
aiia.toast.connection.lost
aiia.toast.save.success
aiia.toast.save.failed
```

### 4.5 `aiia.dialog.*`（服务于 H1 草稿提示 / S1 降级 fallback）

```
aiia.dialog.draft.restored
aiia.dialog.draft.beforeunload
aiia.dialog.fallback.js_blocked.title
aiia.dialog.fallback.js_blocked.message
aiia.dialog.fallback.action.refresh
aiia.dialog.fallback.action.open_settings
```

---

## 五、跨端同步约束（硬性）

新增或修改 `aiia.*` 下任何 key 都必须：

1. **同时写入 4 个文件**：
   - `static/locales/en.json`
   - `static/locales/zh-CN.json`
   - `packages/vscode/locales/en.json`
   - `packages/vscode/locales/zh-CN.json`

2. **4 个文件里的路径必须完全一致**（大小写敏感、层级一致）。

3. **placeholder 名称**在 4 个文件里必须一致（`{{seconds}}` 不能在一端写成
   `{{timeLeft}}`）。

4. `scripts/check_locales.py` 会自动执行这 3 条检查：
   - 同端内 en/zh 一致（历史行为）
   - `aiia.*` 跨端对齐（IG-8 新增）
   - 任一失败，CI 红。

5. **非 `aiia.*` 的 key** 两端可以各加各的，不受跨端约束。

---

## 六、review checklist（硬性）

每个引入 / 修改 i18n key 的 PR 都必须回答下面 5 个问题：

- [ ] 这个 key 是 **跨端共享** 还是 **单端专有**？
  - 共享 → 放 `aiia.*`
  - 单端 → 放对应已有 namespace（`page.*` / `settings.*` / `ui.*` / ...）
- [ ] 如果放 `aiia.*`，**4 个 locale 文件**都加了吗？
- [ ] placeholder 在 4 个文件里**名字一致**吗？
- [ ] 路径的**每一段都是 snake_case**吗？层级不超过 5 段？
- [ ] 本文的 §四「预留 key 清单」里有登记吗？没有就**先更新本文**再加 key。

---

## 七、自动守护（`scripts/check_locales.py`）

`check_locales.py` 由 `ci_gate.py` 自动调用，也可单独运行：

```bash
uv run python scripts/check_locales.py
```

### 7.1 检查项

| 检查 | 覆盖范围 | 失败信号 |
|------|----------|----------|
| `check_locale_pair("static/locales")` | Web UI en/zh | `[Web UI] zh-CN.json 缺少 key: …` |
| `check_locale_pair("packages/vscode/locales")` | VSCode en/zh | `[VS Code Plugin] en.json 缺少 key: …` |
| `check_cross_platform_aiia_parity`（IG-8 新增） | Web UI ↔ VSCode 的 `aiia.*` | `[cross-platform en.json] VSCode 缺少 key: aiia.…` |
| `check_nls_pair` | `package.nls.*` | `[package.nls] zh-CN 缺少 key: …` |

### 7.2 跨端检查的正样例与反样例

**正样例**（通过）：

```json
// static/locales/en.json
{
  "aiia": { "state": { "loading": { "title": "Loading..." } } }
}
// packages/vscode/locales/en.json
{
  "aiia": { "state": { "loading": { "title": "Loading..." } } }
}
```

**反样例**（失败）：

```json
// static/locales/en.json
{ "aiia": { "state": { "loading": { "title": "Loading..." } } } }
// packages/vscode/locales/en.json
{ "aiia": { "state": { "loading": { "heading": "Loading..." } } } }
// ↑ attribute 不一致：title vs heading
```

---

## 八、与相关改进项的关系

- **IG-3（状态机 `ConnectionStatus` / `ContentStatus` / `InteractionPhase`）**：
  状态机里的**常量名**（例如 `'disconnected'` / `'content'`）直接作为
  `aiia.state.*` 路径段，一一对应。
- **T1（三态 UI 统一）**：消费 `aiia.state.{loading,empty,error}.*`。
- **T2（复制诊断）** + **S3（诊断日志链）**：消费 `aiia.diagnostics.*`。
- **P2（命令可发现性）**：消费 `aiia.command.*`。
- **H1/F2（草稿提示）** + **S1（fallback 卡片）**：消费 `aiia.dialog.*`。
- **IG-6（噪音等级约定）**：对 `aiia.toast.*` 的 level 标签（critical /
  important / quiet）做组织约束。
- **阶段 3 E1（i18n 抽共享模块）**：
  本规范确保到那一步时，`aiia.*` 下的全部 key **4 个文件一字不差**，
  直接把其中一端的 `aiia` 整块复制到共享模块即可，零改引用。

---

## 九、变更历史

| 日期 | 变更 | 提交 |
|------|------|------|
| 2026-04-18 | 首次创建，约定三层 namespace + 预留 key 清单 + 跨端守护 | C8（IG-8 本次提交） |

---

## 十、退场条款（mission complete 即删）

**本文是过渡文档，不是长期维护文件**。完成以下 3 件事后，本文应被删除，
规范以「活的代码契约」形式继续生效，无需独立 markdown：

1. **阶段 3 E1（i18n 抽共享模块）完成**：`aiia.*` 被抽到共享 locale 源，
   Web UI 和 VSCode 插件**不再各自维护 aiia.\* 副本**，跨端对齐退化为
   「共享源只有一份」的物理事实，`check_cross_platform_aiia_parity` 可以
   删除（因为不可能不对齐）。
2. **共享模块的 README 里重述命名规范**：`aiia.*` 的四段路径规则、
   placeholder 规范、review checklist，都挪到新共享模块的 README 中
   就近维护，避免本文与代码路径脱节。
3. **§四「预留 key 清单」全部落地**（或明确作废）：阶段 1/2 改动应已
   消费完 §四 的 5 个子域（`state` / `diagnostics` / `command` /
   `toast` / `dialog`），清单的"预留"属性自然消解。

删除本文的 PR 必须同时：

- 在 `docs/CHANGELOG` 或 `BEST_PRACTICES_PLAN.tmp.md` 注记本文被归档的
  原因（3 条是否全部达成）。
- 保留 `check_locales.py` 里的 `check_cross_platform_aiia_parity` 直到 E1
  物理消除跨端 `aiia` 副本；E1 落地后这个函数与本文一并退场。
