# Inline 注入清册（IG-7）

> 本文维护项目两端（Web UI / VSCode 插件）**所有运行时向页面注入 `<script>` / `<style>` /
> 内联 DOM style 以及 `window.__AIIA_*` 全局变量的位置**。
>
> 维护目标（按重要性递减）：
>
> 1. **CSP 收紧的路线图基础**：任何想把 `style-src 'unsafe-inline'` 拿掉、
>    或把 `script-src 'self' 'nonce-...'` 进一步收紧成 `'strict-dynamic'` 的改动，
>    都必须先在本文里圈掉所有注入点并给出迁移路径。
> 2. **“新增 inline 注入必须同步登记”**：code review 时对照本文；
>    发现未登记的 inline 注入就要求补登记。
> 3. **防御纵深审计**：XSS 审计 / 依赖审计 / 主题切换故障排查时，
>    先看本文就能定位所有"运行时动态注入"的切面。

> 本文不是完整的 CSP 规范，只是**事实清单 + 迁移建议**。
> 规范层面的参考：`web_ui_security.py::add_security_headers`（Web UI）与
> `packages/vscode/webview.ts` 内的 `Content-Security-Policy` meta（VSCode）。

---

## 一、两端 CSP 现状对比

| 指令 | Web UI (`web_ui_security.py`) | VSCode webview (`webview.ts`) |
|------|-------------------------------|-------------------------------|
| `default-src` | `'self'` | `'none'` |
| `script-src` | `'self' 'nonce-<n>'` | `'nonce-<n>'` |
| `style-src` | `'self' 'unsafe-inline'` ⚠ | `<cspSource>`（无 `'unsafe-inline'`）|
| `img-src` | `'self' data: blob:` | `data: <serverUrl> https: <cspSource>` |
| `connect-src` | `'self'` | `<serverUrl> <cspSource> 'self'` |
| `object-src` | `'none'` | `'none'` |
| `base-uri` | `'self'` | `'none'` |
| `frame-ancestors` | `'none'` | — |
| `frame-src` | — | `'none'` |

**关键差异**：VSCode webview 端 `style-src` 已经不依赖 `'unsafe-inline'`，
所以那边**零 inline style / 零 element.style 赋值**是硬性要求；
Web UI 端仍然依赖 `'unsafe-inline'`，`app.js` / `notification-manager.js` 等
还有大量 `element.style.xxx = ...` 赋值。**IG-7 的核心收紧目标是把 Web UI
也迁到 `style-src 'self' 'nonce-<n>'`**，完成后两端 CSP 对齐。

---

## 二、VSCode webview 注入清册

### 2.1 HTML 模板内的 inline `<script>`

| 位置 | 内容 | 是否带 nonce | CSP 状态 |
|------|------|--------------|----------|
| `packages/vscode/webview.ts` L1203 | 注入 5 个 `window.__AIIA_*` 全局（SVG / Lottie JSON / i18n 语言 / locale 对象 / 所有 locale） | ✅ `nonce="${nonce}"` | **已合规** |

该 inline 脚本体是**同步的**，保证在后续 `defer` 外链脚本执行前就绪。

### 2.2 HTML 模板内的 `<script src>`（全部 nonce 外链）

| 位置 | 目标 | 加载时机 | 备注 |
|------|------|----------|------|
| `webview.ts` L1421 | `prism-bootstrap.js` | 同步 | 禁用 Prism 自动高亮 |
| `webview.ts` L1424 | `i18n.js` | defer | i18n 框架 |
| `webview.ts` L1425 | `webview-state.js` | defer | C3/IG-3 的状态机常量 |
| `webview.ts` L1426 | `webview-helpers.js` | defer | 通用工具函数 |
| `webview.ts` L1427 | `webview-ui.js` | defer | UI 主模块 |
| `webview.ts` L1428 | `webview-notify-core.js` | defer | 通知分发 |

### 2.3 `document.createElement('script')` 动态插入（全部 nonce 外链）

**全部都在 `packages/vscode/webview-ui.js`，均为懒加载外链脚本，不存在 inline 代码**：

| 脚本 id | createElement 行 | 目标 URL 来源 | 触发条件 |
|---------|------------------|---------------|----------|
| `aiia-lottie-script` | L664 | `LOTTIE_LIB_URL`（VSIX 内置资源）| 首次 `showNoContent()` 需要 Lottie 动画 |
| `aiia-marked-script` | L765 | `MARKED_JS_URL` | 首次渲染 Markdown |
| `aiia-prism-script` | L854 | `PRISM_JS_URL` | 首次渲染代码块 |
| `aiia-notify-core-script` | L959 | `NOTIFY_CORE_JS_URL` | 首次收到通知配置 |
| `aiia-settings-ui-script` | L1018 | `SETTINGS_UI_JS_URL` | 首次打开设置面板 |
| `MathJax-script` | L3882 | `MATHJAX_SCRIPT_URL` 或 `${SERVER_URL}/static/js/tex-mml-chtml.js` | 首次遇到 `$...$` 公式 |

每个动态脚本都会 `if (CSP_NONCE) { s.setAttribute('nonce', CSP_NONCE) }`，
与 `script-src 'nonce-<n>'` 相容。

**禁区 / 红线**：这些插入点不得演化成"动态生成 JS 代码字符串 +
`eval` / `new Function()`" —— 这类方式即使带 nonce 也会被 `script-src`
拒绝（除非显式放开 `'unsafe-eval'`，坚决不加）。

### 2.4 Inline `<style>` / `element.style.xxx =`

**当前为零**（在 BM-5 `026599d` 与 C5 `657cf66` 中已巩固 class toggle
模式）。新增一条 `element.style.xxx =` 就会立刻被 `style-src` 拒绝，
**任何需要动态样式的场景必须用 class / data 属性 + 外部 CSS 规则实现**。

### 2.5 `window.__AIIA_*` / `globalThis.__AIIA_*` 全局命名空间（VSCode 侧）

| 全局 | 类型 | 写入点 | 消费者 |
|------|------|--------|--------|
| `window.__AIIA_NO_CONTENT_FALLBACK_SVG` | `string` | `webview.ts` L1203 inline `<script>`（来源：VSIX 内置 `activity-icon.svg`） | `webview-ui.js` L148~149 降级显示 |
| `window.__AIIA_NO_CONTENT_LOTTIE_DATA` | `object` | `webview.ts` L1203 inline（来源：VSIX 内置 Lottie JSON 预序列化） | `webview-ui.js` L153~155 |
| `window.__AIIA_I18N_LANG` | `string` | `webview.ts` L1203 inline（来源：VSCode 语言设置） | `webview-ui.js` L51 / `webview-settings-ui.js` L76 |
| `window.__AIIA_I18N_LOCALE` | `object` | `webview.ts` L1203 inline（来源：当前语言 locale JSON） | `webview-ui.js` L50 / `webview-settings-ui.js` L75 |
| `window.__AIIA_I18N_ALL_LOCALES` | `object` | `webview.ts` L1203 inline（来源：所有 locale） | `webview-ui.js` L38 / `webview-settings-ui.js` L66 |
| `globalThis.__AIIA_VSCODE_API` | `VSCodeAPI` | `webview-ui.js` L21 运行时赋值（`acquireVsCodeApi()`）| 懒加载子模块复用，规避宿主对多次 `acquireVsCodeApi` 的限制 |

命名约定：**VSCode 侧前缀统一 `window.__AIIA_`（双下划线）**，
与 Web UI 的 `window.AIIA_`（单下划线）区分，避免跨端模块被误认。

---

## 三、Web UI 注入清册

### 3.1 HTML 模板内的 inline `<script>`

| 位置 | 内容 | nonce | CSP 状态 |
|------|------|-------|----------|
| `templates/web_ui.html` L12-27 | `redirectZeroHostToLoopback`：把 `0.0.0.0` 地址自动切到 `127.0.0.1` | ✅ `{{ csp_nonce }}` | 合规 |
| `templates/web_ui.html` L1156-1167 | i18n 启动脚本：写入 `window.AIIA_CONFIG_LANG` + 监听 `DOMContentLoaded` → 调 `window.AIIA_I18N.init(...)` | ✅ `{{ csp_nonce }}` | 合规 |

两处都短小精悍，**不能用外链替代**：前者必须同步跑在任何 script 之前，
后者必须读到 Jinja 渲染期的 `{{ language|tojson }}`。

### 3.2 HTML 模板内的 `<script src>`（全部 nonce 外链）

`mathjax-loader.js` / `marked.js` / `prism.js` / `validation-utils.js` /
`theme.js?v=` / `keyboard-shortcuts.js` / `dom-security.js` / `state.js` /
`multi_task.js?v=` / `i18n.js` / `notification-manager.js` /
`settings-manager.js` / `image-upload.js` / `app.js?v=`，共 **14 条**，
全部 `nonce="{{ csp_nonce }}"`。

### 3.3 动态 `document.createElement('style')`

| 位置 | 作用 | nonce | 收紧路径 |
|------|------|-------|----------|
| `static/js/settings-manager.js` L493 (`applySettingsTheme`) | 为设置面板动态注入 `[data-theme="light"] .settings-*` 覆盖样式，解决 CSS 优先级问题 | ❌ 未带 nonce | **应迁入 `static/css/main.css`**（无运行时条件依赖，可完全静态化） |

### 3.4 `element.style.xxx =` 清单（依赖 `'unsafe-inline'`）

下面按文件汇总，**不是重构 TODO，而是 CSP 收紧时需要逐一处理的清单**：

| 文件 | 数量 | 主要场景 | 建议替代 |
|------|------|---------|----------|
| `static/js/app.js` | ~40 | `opacity` / `filter` / `display` / `transition` / `backgroundColor` / `color`（启动 fallback、反色、提交按钮禁用态） | class toggle + 外部 CSS（与 VSCode 侧 `aiia-repainting` / `aiia-boot-skeleton--leaving` 相同范式） |
| `static/js/notification-manager.js` | ~13 | 顶部 toast 的 `transform/opacity/transition/background/color` | toast 层用 keyframe 动画 + class；hover 用 `:hover` 伪类 |
| `static/js/multi_task.js` | ~5 | tab 进入/退出动画的 `animationDelay`，display 判断 | animation 用 `animation-delay: calc(var(--i) * 60ms)` + CSS 自定义属性 |
| `static/js/settings-manager.js` | ~5 | panel 的 `display` toggle + overflow | `.hidden` / `aria-hidden` + CSS rule |
| `static/js/image-upload.js` | 3 | 上传占位的 display | 同上 |
| `static/js/validation-utils.js` | 3 | 错误提示显隐 | 同上 |

**上述改动的前置条件**：IG-4（CSS Cascade Layers，已在 C1
`5128d69` 落地）+ 全站 `[hidden]` 规则（同 C1）已就位，可直接
切换到 `el.hidden = true` 或 `el.classList.toggle('is-visible')` 范式。

### 3.5 Inline `style="..."` 属性

模板里有**少量** `style=` 属性（例如 SVG 定义段内 `x1="50%"` 等不是 CSS，
但 SVG 元素有时会用 `style`）；需要统一审查一遍后列入本清单。
**具体行号在下一次 CSP 收紧前补齐**（当前 grep `style="` 会命中
SVG attribute 而非 CSS，需要更精确的正则）。

> 占位项：**在 CSP 收紧 PR 里填充具体行号**，避免本次 IG-7 PR 炸大。

### 3.6 `window.AIIA_*` 全局命名空间（Web UI 侧）

| 全局 | 类型 | 来源 | 消费者 |
|------|------|------|--------|
| `window.AIIA_CONFIG_LANG` | `string` | 模板内联脚本 L1157 | i18n 启动逻辑 |
| `window.AIIA_I18N` | `Object` | `static/js/i18n.js` | app.js / settings-manager / multi_task |
| `window.AIIAState` | `Object`（冻结） | `static/js/state.js`（C3/IG-3） | app.js / multi_task |

命名约定：Web UI 侧采用 `window.AIIA_*`（单下划线），与 VSCode 侧
`window.__AIIA_*`（双下划线）做前缀区分。

---

## 四、收紧路线图（建议）

按风险/收益比排序，**不是本次 PR 要做的事**，只是把方向沉淀下来：

| 阶段 | 动作 | 依赖 | 风险 |
|------|------|------|------|
| **P1-a** | `settings-manager.js::applySettingsTheme` 的 `<style>` 动态注入 → 搬进 `static/css/main.css` | 无 | 低（纯静态规则） |
| **P1-b** | `notification-manager.js` 的 toast 样式：`transform/opacity/transition` → CSS class | 需要设计 `.toast--entering` / `.toast--leaving` 动画 | 中（要保持现有淡入淡出观感） |
| **P1-c** | `multi_task.js` 的 `animationDelay` → CSS 自定义属性 `--i` + `animation-delay: calc(...)` | 无 | 低 |
| **P2-a** | `app.js` 的 `display/opacity/filter` → class toggle | 前三项完成；建一份 CSS 变量映射 | 中 |
| **P2-b** | 全站 `style="..."` 属性盘点 + 移除 | 需要先补 IG-7 3.5 节的具体行号 | 中（易漏） |
| **P3** | Web UI CSP 升级为 `style-src 'self' 'nonce-<n>'`（取消 `'unsafe-inline'`）| P1+P2 完成 | 低（只是删一行策略 + 给 settings 面板的残留 `<style>` 加 nonce） |

**P3 完成后，两端 CSP 对齐，`style-src 'unsafe-inline'` 正式从本项目
消失。**

---

## 五、维护约束（review checklist）

新增以下内容之一就**必须同步更新本文**：

- [ ] 任何新 `<script>` / `<style>` 标签（无论是模板里还是 JS 动态插入）
- [ ] 任何新 `element.style.xxx = ...` / `element.style.cssText = ...`
- [ ] 任何新 `document.createElement('script' | 'style')`
- [ ] 任何新 `window.__AIIA_*` 或 `window.AIIA_*` 全局
- [ ] CSP 指令的任何变更（`web_ui_security.py` / `webview.ts`）

**review 动作**：

1. 登记位置（文件 + 行号）
2. 登记是否带 nonce
3. 登记合规性（当前 CSP 是否接受）
4. 如果是新的 `style-src` 违规，给出"合规后的迁移方式"

---

## 六、与相关 RFC / 改进项的关系

- **IG-4（CSS Cascade Layers）**：已在 `5128d69` 落地；
  本文所有 class toggle 迁移都依赖 IG-4 的分层让新规则干净命中。
- **BM-5（retainContextWhenHidden ghost rendering）**：
  `026599d` 示范了"VSCode 严格 CSP 下用 class toggle 代替
  inline style"的模板（`body.aiia-repainting`）。
- **BM-7（首帧 boot skeleton）**：
  `657cf66` 再次示范同一范式（`.aiia-boot-skeleton--leaving`），
  两者合起来可作为未来 Web UI 迁移的参考实现。
- **E2（CSP 收紧）**：项目原规划的 E2 依赖本 inventory；IG-7 是 E2 的前置
  事实清单。

---

## 七、变更历史

| 日期 | 变更 | 提交 |
|------|------|------|
| 2026-04-18 | 首次创建，盘点两端现状 + P1~P3 路线图 | C7（IG-7 本次提交） |

---

## 八、退场约束（必读）

本文件是**过渡性工程参考文档**。当 §四「收紧路线图」P1-a 至 P3
**全部落地、两端 CSP 对齐、`style-src 'unsafe-inline'` 已从 Web UI
彻底移除**后，本文件的使命即告完成：

- ✅ **直接删除本文件**（`docs/inline-injection-inventory.zh-CN.md`），
  以及若未来派生出的英文版本。
- ✅ 同步把 §五「维护约束 review checklist」的那几条迁入 `docs/workflow.zh-CN.md`
  或 `docs/workflow.md` 的相应安全章节，作为长期守则保留。
- ⛔ **不要**把本文件保留成"历史参考"——退场后它会立刻过时，
  继续保留只会误导未来的贡献者。
