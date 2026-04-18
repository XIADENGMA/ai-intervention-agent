# 噪音等级约定（IG-6）

> 本文为本项目**跨四条输出通道**（aria-live / toast / 日志 / 状态栏）
> 的广播级别约定——"一个事件到底该用多大声喊出来"。
>
> 维护目标：
>
> 1. **避免四重噪音**：同一事件同时触发 aria-live + toast + log + 状态栏
>    会把屏幕阅读器用户、视觉用户、日志订阅者**一起吵死**。规范约定
>    默认走 quiet、主动升级、**通道数按级别递增**。
> 2. **前置基础件**：P1（aria-live）、P3（状态栏 tooltip）、S3（诊断
>    日志链）三个改动会各自消费本规范；如果没有统一约定，它们互相
>    踩脚的概率极高（SR-2 标识风险）。
> 3. **长期回归守护**：`tests/test_noise_levels.py` 以 doc-anchor
>    方式断言文档里登记的 DOM 锚点和运行时常量仍然存在，防止未来
>    有人改一处而拆掉半条规范。

---

## 一、三级 × 四通道矩阵

| 级别 | aria-live | toast | 日志等级 | 状态栏 |
|------|-----------|-------|---------|--------|
| **critical** | `assertive`（打断朗读） | error toast（4s 常驻） | `error` | 红色闪烁 + 强 tooltip |
| **important** | `polite`（朗读到再播报） | info / warn toast（1.8s） | `info` | 黄色 + 普通 tooltip（节流 1s） |
| **quiet** | `off` / 静默 | — | `debug` | tooltip 刷新（节流 5s） |

**阅读方式**：一级 → 四个通道的行为是"**一起升级**"的，不能只升其中一个。
例如某事件是 `critical`，就**必须**同时走 assertive aria-live + error toast +
error 日志 + 红色状态栏，不能"只打 error 日志不出 toast"或者"只闪状态栏
不动 aria-live"（否则屏幕阅读器用户或视觉用户会漏感知）。

---

## 二、级别语义

### 2.1 `critical`——**用户必须立即知道，否则任务会失败**

触发条件（仅举例）：

- 提交被拒绝（后端 4xx/5xx 且不可重试）
- SSE 连续失败超过熔断阈值（见 §三 熔断），服务端明确不可达
- 草稿丢失、未保存内容被覆盖的危险时刻
- 配置文件加载失败且功能被禁用

硬约束：

- 频率上限：**每 3 秒最多 1 次 critical**（超频则自动降级到 important）
- 必须可直接 actionable（例如"重新连接"按钮），不能是死结
- 文案带动词指令（"请重试"而不是"失败了"）

### 2.2 `important`——**应当知道，但不打断用户**

触发条件（仅举例）：

- 连接恢复（`aiia.toast.connection.restored`）
- 保存成功（`aiia.toast.save.success`）
- 首次 fetch 降级到缓存（首次切换值得告知）
- 后台任务完成（结果页面已可见）

硬约束：

- 频率上限：**每 1 秒最多 1 次 important**（SR-2 要求的 aria-live 去重窗口
  对 important 同样适用，叠加 3 秒同内容去重）
- 不应包含"请立即操作"这类指令——那是 critical 的职责

### 2.3 `quiet`——**默认全部状态变化走这里**

触发条件（**默认**）：

- 任何 SSE 心跳、轮询命中、缓存命中
- 任何内部状态机迁移（`ConnectionStatus` / `ContentStatus` /
  `InteractionPhase` 变化）
- 任何 UI 可见性切换、tooltip 刷新

硬约束：

- aria-live 必须是 `off`，即：**不要** `role="status"` / `role="alert"`，
  也不要手写 `aria-live`——视觉可见即可
- 状态栏 tooltip 刷新必须节流 **5 秒**（避免 SSE 抖动每秒改 tooltip）
- 日志默认走 `debug`，扩展侧 `logLevel` 配置会决定是否显示；**不要**写 info

---

## 三、默认规则与升级熔断

### 3.1 默认规则

> **所有状态变化走 quiet，主动调用 `notify(level, payload)` 才升级**。

这条原则意味着：

- 前端代码**不应**为每个 fetch 失败都调 `logError(...)`——默认走 `log(debug)`。
- 前端代码**不应**为每个连接状态变化都 `showToast`——默认什么都不做，只有
  UI 上可见元素（状态栏、连接图标）会变色。
- 屏幕阅读器用户**默认听不到**状态变化，除非事件是 important 或 critical。

### 3.2 升级熔断（防止级别"滑坡"）

| 事件家族 | quiet → important | important → critical |
|----------|-------------------|----------------------|
| SSE 连接失败 | 连续 **3 次**失败升到 important | important 持续 **30 秒**未恢复升到 critical |
| 提交失败 | 单次即 important | 单次 4xx/5xx 且不可重试即 critical |
| 配置加载失败 | N/A（直接 critical） | 单次即 critical |
| 保存冲突 | 单次即 important | 本次提交会丢数据则升 critical |

熔断计数器**在事件家族维度**计数（不是全局），`ConnectionStatus` 从
`connected` 回到 `connected` 会清零该家族的熔断计数。

### 3.3 aria-live 去重（SR-2 补充）

- **同一 level × 同一原文**在 **3 秒**内**不重复广播**（屏幕阅读器对
  重复内容的忍耐度极低）。
- 实现层面：沿用 `showToast` 里既有的 `dedupeKey` 机制，把 `dedupeKey`
  同时作为 aria-live 的去重键（P1 消费时实现）。

---

## 四、通道语义

### 4.1 aria-live 通道（浏览器 / Webview）

- **首选语义角色**（SR-2）：
  - `role="status"`——自带 `aria-live="polite"`，对应 **important**
  - `role="alert"`——自带 `aria-live="assertive"`，对应 **critical**
- **不要**手写 `aria-live` 属性——除非要在 quiet 级别里显式设置 `off`。
- 容器要带 `aria-atomic="true"`，避免部分重读。

### 4.2 toast 通道

- 视觉呈现；非屏幕阅读器用户主要感知通道
- 已有的去重窗口：`TOAST_DEDUPE_WINDOW_MS = 700`（`webview-ui.js` §五 4.1）
- P1 消费后，toast 将和 aria-live **共用同一个 `dedupeKey`**，保证两者
  同频去重（不会出现 toast 压住但屏幕阅读器吵）

### 4.3 日志通道（VSCode OutputChannel / 浏览器 Console）

- 日志等级**只和 IG-6 级别挂钩**，不和业务严重性挂钩
- critical → `error`；important → `info`；quiet → `debug`
- 扩展侧 `logLevel` 配置决定 `debug` 是否写入 Output；Web UI 通过 `localStorage.AIIA_LOG_LEVEL` 同步控制

### 4.4 状态栏通道（VSCode 插件独有）

- `statusBar.text` 改文本 → 立即可见，无节流（这是视觉信号，不是噪音）
- `statusBar.tooltip` 改内容 → **必须节流 5 秒**（quiet）或 1 秒（important），
  或立即刷新（critical，且附加红色背景色）
- `statusBar.backgroundColor` 只用在 critical（例如 `new ThemeColor(
  'statusBarItem.errorBackground')`）

---

## 五、现状快照（本文 commit 时，2026-04-18）

> 这一节是**测试护栏的源文件**——`tests/test_noise_levels.py` 直接对这里
> 登记的锚点做 grep 断言。后续改了锚点必须**同步改本文**，否则 CI 红。

### 5.1 已有的 aria-live 锚点（4 处）

| # | 路径 | 行号 | 角色 | aria-live 值 | 用途 |
|---|------|------|------|-------------|------|
| A1 | `packages/vscode/webview.ts` | ≈1327 | div#toastHost | `polite` + `aria-atomic="true"` | 插件 webview 的 toast host |
| A2 | `packages/vscode/webview-ui.js`（`showToast`）| ≈1578-1582 | 每个 toast 元素 | `polite`（写死）+ `role="status"` | 插件 webview 的具体 toast |
| A3 | `templates/web_ui.html` | ≈267-272 | div#no-content-status-message | `polite` + `role="status"` | Web UI 的空状态提示 |
| A4 | `templates/web_ui.html` | ≈527 | div#status-message | `polite` + `role="status"` | Web UI 的主状态条 |

**命中频率**：测试护栏通过 `Grep` 在对应文件里找到 `toastHost` + `aria-live` 共现，
以及找到 `status-message` + `aria-live="polite"` 共现。

> **P1 改法预告**（SR-2）：P1 落地后 A2 将把"手写 `aria-live='polite'`"
> 替换为"仅 `role='status'`"（后者自带 polite），**A3/A4 同步简化**。
> 那时本文 §五.1 要更新，`test_noise_levels.py` 的 A2 断言也要跟改。

### 5.2 已有的去重 / 节流锚点（2 处）

| # | 路径 | 常量 | 当前值 | 说明 |
|---|------|------|--------|------|
| D1 | `packages/vscode/webview-ui.js` | `TOAST_DEDUPE_WINDOW_MS` | `700` | toast 同 key 去重窗口；P1 落地后 aria-live 会共用这个 key |
| D2 | `packages/vscode/webview-ui.js` | `TOAST_MAX_VISIBLE` | `5` | 同屏最多 5 条 toast（防止 important 刷屏挤掉 critical） |

测试护栏断言这两个常量仍存在于文件中（不校验具体数值，数值允许微调但不能删）。

### 5.3 级别对照表——现状函数 vs 规范目标

| 现有函数 | 当前行为 | 规范对应级别 | 差距 |
|----------|----------|-------------|------|
| `log(message)`（webview-ui.js L1509） | 只走 `log:debug` 通道 | **quiet** | ✅ 已合规 |
| `logError(message)`（webview-ui.js L1517） | 三通道同时广播：`log:error` + `postMessage('error')` + `showToast('error')` | **critical**（四通道） | ❌ 少状态栏通道；但消息内容不一定够 critical（大量 logError 其实只是 important 级） |
| `showToast(message, options)`（webview-ui.js L1542） | kind ∈ `info/success/warn/error` | important（info/success/warn）或 critical（error） | ✅ 大致合规，缺 level 的显式标注 |
| `postStatusInfo(message)`（webview-ui.js L1723） | 发 `severity:info, presentation:statusBar` 到 extension | **important** | ✅ 已合规 |
| `statusBar.tooltip`（extension.ts L166/L252/L718）| 每次 `updateIndicators` 都立即覆写 tooltip | **quiet** | ❌ 无节流；SSE 抖动会高频改 tooltip |

> **P1 / P3 消费本文时的改法提示**——见 §七。

---

## 六、反例清单（以现状为教材）

### 6.1 反例 A：`logError` 三通道同级广播

```1517:1534:packages/vscode/webview-ui.js
  function logError(message) {
    const text = String(message || '')
    try {
      vscode.postMessage({ type: 'log', level: 'error', message: text })
    } catch (e) {
      // 忽略
    }
    try {
      vscode.postMessage({ type: 'error', message: text })
    } catch (e) {
      // 忽略
    }
    try {
      showToast(text, { kind: 'error', timeoutMs: 2600, dedupeKey: 'err:' + text.slice(0, 120) })
    } catch (e) {
      // 忽略
    }
  }
```

**问题**：任何 fetch catch / `Promise.reject` / try-catch 里调 `logError`，
都会**同时**触发三通道——但很多现场只是"一次 fetch 失败"，**不应**升到
critical。屏幕阅读器用户每次 SSE 抖动都被吵一次。

**P1 改法**：

```javascript
function notify(level, message, options) {
  // level ∈ 'critical' | 'important' | 'quiet'
  // 按矩阵分发到对应通道子集
}
function logError(message) {
  notify('important', message)  // 绝大多数场景只升到 important
}
```

### 6.2 反例 B：状态栏 tooltip 无节流

```245:252:packages/vscode/extension.ts
      if (connected) {
        statusBar.text = `$(sparkle-filled) ${formatTotalCount(total)}`
      } else if (offline) {
        statusBar.text = '$(sparkle-filled) 离线'
      } else {
        statusBar.text = '$(sparkle-filled) --'
      }

      statusBar.tooltip = buildStatusBarTooltip({ connected, active: a, pending: p })
```

**问题**：`updateIndicators` 在 SSE 主轮询里被高频调用，tooltip 每次都被
覆写。虽然不直接产生视觉噪音（VSCode 只在 hover 时才渲染 tooltip），但
浪费 VSCode 侧的序列化成本，也违反本规范"quiet 级别 tooltip 节流 5s"。

**P3 改法**：加 `lastTooltipRefreshAt` 闭包变量，quiet 级别下 5s 内重复
刷新直接短路返回。

### 6.3 反例 C：aria-live 写死 `polite`

`webview-ui.js` 每个 toast DOM 元素都**直接**写 `aria-live='polite'`，
导致 `kind='error'` 的 critical toast 也只是 polite——**屏幕阅读器
用户感知不到紧急程度**。

**P1 改法**：按 kind 映射——`kind='error'` → `role='alert'`
（assertive，不依赖手写 aria-live）；其他 → `role='status'`
（polite）。

---

## 七、消费路径——阶段 1/2 各改动点怎么守本文

| 改动 | 负责的消费动作 | 本文被引用的章节 |
|------|---------------|----------------|
| **P1（aria-live / role）** | 落地 `notify(level, message)` 统一入口，在 `showToast` 按 level 决定 `role`；aria-live 和 toast 共用 `dedupeKey` | §二、§三、§四.1-4.2、§五.1、§六.1、§六.3 |
| **P3（状态栏 tooltip 智能化）** | tooltip 更新按 level 节流（critical 立即 / important 1s / quiet 5s）；`backgroundColor` 仅 critical 使用 | §二、§四.4、§五.3、§六.2 |
| **S3（诊断日志链）** | 日志等级严格按 §二 级别映射；启动 banner 是 important（单次），后续 heartbeat 是 quiet | §二、§四.3、§五.3 |
| **T1（三态 UI）** | `error` 态进入 Error 页面本身是 **important**（视觉已足够）；但如果点"重试"又失败则升到 critical | §二、§三.2 |
| **S2（SSE 断线续传）** | 重连过程中 **前 2 次失败都是 quiet**；第 3 次起升 important；30s 未恢复升 critical | §三.2 熔断表 |

---

## 八、review checklist（引入任何新通知 / 日志 / toast 时）

- [ ] 这是 quiet / important / critical 中的哪一级？在 PR 描述里写清楚。
- [ ] **四通道一起升级**了吗？critical 不能只打 error 日志不出 toast；
      important 不能只 toast 不写 info 日志。
- [ ] aria-live 有没有沿用 `role='status'` / `role='alert'`，而不是
      **手写** `aria-live` 属性？（quiet 级别除外）
- [ ] 这个事件家族有没有**升级熔断**规则？连续失败到什么阈值升级？
      `ConnectionStatus` 回到 `connected` 时会清零吗？
- [ ] 状态栏 tooltip 更新有没有按级别**节流**（quiet 5s / important 1s /
      critical 立即）？
- [ ] 新增 toast 文案有没有用 C8 预留的 `aiia.toast.*` 命名？还是先落
      私有 namespace、等 P1 批量迁移？
- [ ] 本文 §五「现状快照」里需要登记新的锚点吗？如果是，**同步改本文 +
      对应测试断言**。

---

## 九、自动守护（`tests/test_noise_levels.py`）

测试覆盖（6 条断言）：

| # | 断言 | 锚点 |
|---|------|------|
| T1 | `packages/vscode/webview.ts` 里 `toastHost` 上有 `aria-live="polite"` | §五.1 A1 |
| T2 | `packages/vscode/webview-ui.js` 的 `showToast` 至少保留一处 `role='status'` + `aria-live='polite'` | §五.1 A2 |
| T3 | `templates/web_ui.html` 的 `status-message` 带 `aria-live="polite"` | §五.1 A3/A4 |
| T4 | `packages/vscode/webview-ui.js` 仍声明 `TOAST_DEDUPE_WINDOW_MS` 常量 | §五.2 D1 |
| T5 | `packages/vscode/webview-ui.js` 仍声明 `TOAST_MAX_VISIBLE` 常量 | §五.2 D2 |
| T6 | 本文（`docs/noise-levels.zh-CN.md`）里 §一 3×4 矩阵关键文案（`critical` / `important` / `quiet`）都在 | 自描述性 |

> **不校验**：不断言常量具体数值（允许微调 700→800 不红 CI），不
> 扫描 `logError` 三通道反例（避免 false positive 卡死 P1 重构前的日常）。

---

## 十、与其他规范的关系

- **C3 IG-3（状态机）**：`ConnectionStatus` 的 `connecting → connected` /
  `connected → disconnected` 转换是**升级熔断**的信号源——计数器挂在
  状态机回调里。
- **C7 IG-7（inline 注入清册）**：本文的 §四.1 要求 `role='alert'`
  等属性必须是 HTML 模板或 `setAttribute`，**不能**用 innerHTML 注入
  （CSP 友好）——延续 IG-7 的"不新增 inline 风险"精神。
- **C8 IG-8（i18n 命名）**：本文的 toast / dialog 文案走 C8 预留的
  `aiia.toast.*` / `aiia.dialog.*` namespace；具体 key 落地在 P1 / H1
  阶段。
- **IG-5（InteractionPhase 矩阵）**：IG-5 定义"在 `SUBMITTING`
  阶段哪些快捷键禁用 / 哪些弹 `beforeunload`"，本文的 important /
  critical toast 在 `SUBMITTING` 期间应**延后**到 `COOLDOWN`——避免
  在提交中被弹窗打断（IG-5 消费时实现）。

---

## 十一、变更历史

| 日期 | 变更 | 提交 |
|------|------|------|
| 2026-04-18 | 首次创建，约定三级 × 四通道矩阵 + 熔断规则 + 现状快照 + 6 条锚点测试 | C9（IG-6 本次提交） |

---

## 十二、退场条款（mission complete 即删）

本文是**过渡文档**，对齐 C7/C8 的归档纪律。完成以下 3 件事后，本文应被
删除：

1. **P1（aria-live）+ P3（状态栏 tooltip）+ S3（诊断日志链）三个
   改动全部落地**——本文定义的"默认 quiet + 主动升级"已经写进
   `notify(level, message)` 这个统一入口，不再需要散文形式提醒。
2. **六条锚点测试的锚点全部就位在 E1 共享模块**——阶段 3 E1 把
   `notify` 和 toast 抽到共享模块后，本文的 §五.1 / §五.2 锚点直接
   从共享模块的 README 里 link 过去，不再需要双文档维护。
3. **`logError` 三通道反例被修正**（§六.1）——`logError` 变成
   `notify('important', ...)` 的薄 wrapper，反例清单失去展示价值。

删除本文的 PR 必须同时：

- 在 `BEST_PRACTICES_PLAN.tmp.md` 注记归档原因（3 条是否全部达成）。
- 删除 `tests/test_noise_levels.py` 整个文件——它的锚点断言在 E1 共享
  模块的测试里已经重新覆盖。
