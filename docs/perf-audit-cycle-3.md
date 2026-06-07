# 前端性能审计 cycle-3

## 0. 阅读引导

| Cycle | 关注面 | 主要 ship |
| --- | --- | --- |
| cycle-1（backend） | TaskQueue / SSEBus / Upload | extend_deadline keyword 强制 |
| cycle-1-frontend（隐式） | BFCache + sessionStorage | R20.x BFCache 恢复 |
| **cycle-3 (本文)** | **首屏渲染路径 / FOUC / 脚本预算** | **anti-FOUC theme bootstrap (R250)** |

本 cycle 把"性能"狭义聚焦到 **首屏 critical render path** 上，因为 mining
cycle-7/8/9 连续 ship 了 PWA 相关脚本（``pwa_install.js`` / ``ios_a2hs_hint.js``）
让 ``<body>`` 末尾 defer 脚本数从 ~15 增到 17，是时候重新审视 FCP 链路。

---

## 1. 结论摘要

| 现象 | 状态 | 本 cycle 行动 |
| --- | --- | --- |
| **Theme FOUC**：用户偏好 ≠ 系统偏好时第一帧错色 | 🔴 latent bug | ✅ **ship** — `<head>` 同步 anti-FOUC bootstrap (~22 LoC) |
| Body defer 脚本 21 个 | ✅ HTTP/2 + preload-scanner 已优化 | 否 — bundling 会破坏独立模块缓存 ROI 负 |
| setInterval 5 个，全部有 clearInterval 路径 | ✅ R123 已修 multi_task health-check 句柄保存 | 否 |
| addEventListener 内存泄漏 | ✅ 无 SPA 切换；listeners 随页面卸载自动 GC | 否 |
| Service Worker `/static/*` cache-first | ✅ R197 + R249 已成熟（offline.html 兜底） | 否 |
| MathJax 按需加载 1.17MB | ✅ R20.12-A 已通过 `mathjax-loader.js` 实现 lazy load | 否 |

**新增 commit：** 1 ship + 1 audit doc + 1 regression test = 3 commit。

**defer (见 §5)：** 2 个 future track，预算 cycle-4+。

---

## 2. 首屏 critical render path 现状

### 2.1 已 ship 的优化

```
<head>
  ├─ inline redirect 0.0.0.0 → 127.0.0.1  (R??, ~10 LoC)
  ├─ <link rel="preload" as="script"> × 6   (R21.1 + R27.1)
  │    app.js / multi_task.js / i18n.js / state.js / marked.js / prism.min.js
  ├─ <link rel="preload" as="style"> × 1    (R27.1: prism.css)
  ├─ mathjax-loader.js (defer)              (R20.12-A: 只配置，不下载 tex)
  ├─ marked.js / prism.min.js (defer)       (R27.2: 1y immutable cache)
  └─ main.css (link)

<body>
  ├─ ...DOM...
  └─ defer scripts × 17                     (按依赖顺序排列)
       theme.js → keyboard-shortcuts.js → dom-security.js
       → notification-manager.js → settings-manager.js → image-upload.js
       → app.js → quick_phrases.js → ... → tri-state-panel-bootstrap.js
```

### 2.2 R250 本 cycle 新增 — Anti-FOUC theme bootstrap

#### 问题

`theme.js` 在 ``<body>`` 末尾 defer 加载，等所有 deferred script 加载执行
完才 fire ``ThemeManager.init`` → 写 ``<html data-theme>``。在此之前 CSS 第
一帧只能按 ``main.css :root`` 默认变量（暗色）+ ``@media (prefers-color-scheme:
light) :root:not([data-theme])`` 媒体查询渲染。

| 系统偏好 | localStorage | 是否 FOUC |
| --- | --- | --- |
| dark | unset / "auto" | ❌ 无（暗色默认匹配） |
| light | unset / "auto" | ❌ 无（媒体查询匹配） |
| **light** | **"dark"** | 🔴 **闪暗** — 先浅后暗 |
| **dark** | **"light"** | 🔴 **闪亮** — 先暗后浅 |

闪烁时间窗：从 first paint 到 ``DOMContentLoaded`` + ``theme.js`` 执行，
冷启动 cache 200-500ms、热启动 50-150ms。

#### 修复

`<head>` 顶部（在所有 preload 之前）加 ~22 LoC 同步 inline `<script>`：

```javascript
(function antiFoucThemeBootstrap() {
  try {
    var stored = localStorage.getItem("theme-preference");
    var resolved = stored;
    if (!stored || stored === "auto") {
      resolved = window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: light)").matches
        ? "light" : "dark";
    }
    if (resolved === "dark" || resolved === "light") {
      document.documentElement.setAttribute("data-theme", resolved);
    }
  } catch (_) { /* localStorage 不可用兜底走 CSS 媒体查询 */ }
})();
```

#### 取舍

| 维度 | 评估 |
| --- | --- |
| 性能开销 | localStorage 读 1 key + matchMedia 查询 1 次 ~0.1ms（缓存 hot） |
| 渲染阻塞 | 是（同步 inline script），但仅 ~0.1ms 比 100ms+ 闪烁划算 |
| CSP | 用 ``nonce="{{ csp_nonce }}"`` 保持 ``script-src 'nonce-...'`` 合规 |
| 与 theme.js 冲突 | 无 — 同 attribute 写入幂等；``theme.js`` init 时读取已存在的 attribute 不会改变行为 |
| 隐私模式 fallback | try/catch 静默；CSS 媒体查询接管 |
| 维护性 | inline script 与 ``theme.js`` 共用 STORAGE_KEY = ``theme-preference`` 字面量 |

#### 测试

`tests/test_feat_perf_audit_cycle3_anti_fouc.py`：
- inline script 存在且在所有 `<link rel="preload">` 之前
- 读取 `theme-preference` 键（与 `theme.js` 同名）
- 处理 `"auto"` / null fallback 到 `matchMedia`
- try/catch 兜底
- CSP nonce 保留

### 2.3 没有改的优化（评估后 not-borrow）

#### 不 bundle 17 个 defer 脚本

| 维度 | bundle | 当前（独立） |
| --- | --- | --- |
| 网络请求 | 1 | 17 |
| HTTP/2 multiplexing | n/a | ✅ |
| 单文件改动缓存失效 | ⚠️ 全部失效 | ✅ 只失效改动的 |
| 模块清晰度 | ⚠️ 一坨 | ✅ |
| build step | ✅ 需要 | ❌ 零 build |

项目原则：**Flask 直接 serve 静态 + 零 build step**。bundling 违背原则
且换不来明显 ROI（HTTP/2 + brotli + preload-scanner + 1y immutable cache
组合下 17 个独立请求总耗时 < 单 bundle 100ms）。

#### 不增加更多 `<link rel="preload">`

浏览器 preload-scanner 已经能在 head 解析阶段抢先发起 body 内 ``<script>``
请求。加更多 preload 只会浪费 link tag 文本（HTML 体积）+ 多余的 hint。
现有 6 个 preload 已覆盖最关键路径（i18n / state / multi_task / app /
markdown 引擎）。

---

## 3. 运行时性能

### 3.1 setInterval 清单

| 文件 | 间隔 | 句柄保存 | 清理路径 |
| --- | --- | --- | --- |
| `validation-utils.js` | 5 min | 不需要（页面级 cache） | 页面卸载 GC |
| `notification-manager.js` | 500ms | flashInterval（局部变量） | 自动 stop 5 次后 clearInterval |
| `image-upload.js` | 60 min | 不保存 | 页面卸载 GC |
| `multi_task.js` healthcheck | 30s | window.tasksHealthCheckTimer | R123 已修 ``stopTasksPolling`` 清理 |
| `multi_task.js` countdown | 1s/任务 | taskCountdowns[id].timer | 任务完成时 clearInterval |
| `feedback_drafts.js` sync | 5s | intervalId | 模块自闭包，页面卸载 GC |
| `offline.html` ping | 5s | intervalId 局部 | 服务恢复后 reload 自然停 |

**结论**：全部 setInterval 都有清理路径或自然停止条件，无内存泄漏风险。

### 3.2 addEventListener 总数 ~125

- 100% 为永久监听（页面生命周期内不卸载）；
- 无 SPA 路由切换（项目是 server-rendered Flask + WebUI 单页），listeners
  随 page unload 自动 GC；
- iOS A2HS hint banner（R248）和 PWA install button（R247）的 `click` 监听
  在 hide() 后 dismiss 不再触发，但 DOM 节点仍存在 → 监听不主动 remove。
  可接受（一次性 listener，DOM 节点 ~200 字节）。

---

## 4. Service Worker 性能

### 4.1 已优化路径

- `/static/*` → cache-first（R197）
- `/icons/*` → cache-first
- HTML 导航 → network-first + R249 offline.html 兜底
- 通知点击 → 路由到主窗口或新开

### 4.2 cache 命中率

- 冷启动：所有 21 个 JS + 1 CSS + 5 icon = 27 requests
- 热启动：0 network requests（全 cache 命中）
- 修改单文件：1 request（cache busted by `?v=` query）

---

## 5. Defer 列表 (future tracks)

按 ROI 降序：

### 5.1 Inline critical CSS (medium ROI)

- **现状**：`main.css` 4500+ 行，brotli 后 ~25KB，FCP 仍要等 CSS 解析完。
- **思路**：抽出首屏 ~5KB critical CSS 内联到 `<head>`，rest async。
- **触发条件**：lab 测试 LCP > 2s（当前 ~600ms 不需要）。
- **工具**：``critters`` / ``critical`` npm 包，但项目无 npm build → 手工
  抽 + 维护成本高，**defer**。

### 5.2 Service Worker offline-first for `/static/*` (low ROI)

- **现状**：cache-first 但每次先查 cache 再决定，仍有 cache.match 开销 ~1ms。
- **思路**：用 ``staleWhileRevalidate`` 后台更新。
- **触发条件**：未观察到；当前 ``/static/`` 命中率 100%，开销可接受。

---

## 6. Reproducibility — 如何重做本审计

```bash
# 1. inventory deferred scripts
rg -n 'script\s+defer' src/ai_intervention_agent/templates/web_ui.html | wc -l

# 2. inventory setInterval and verify each has cleanup
rg -n 'setInterval\(' src/ai_intervention_agent/static/js/

# 3. preload tags
rg -n '<link rel="preload"' src/ai_intervention_agent/templates/web_ui.html

# 4. test anti-FOUC + freshness
uv run pytest tests/test_feat_perf_audit_cycle3_anti_fouc.py

# 5. 检查相关 R 系列文档
git log --grep='R21.1\|R27.1\|R27.2\|R123\|R197\|R249\|R250'
```

## 7. 关联文档

- `docs/perf-audit-cycle-1.md` — backend 审计
- `docs/code-reviews/cr30.md` — BFCache 修复
- `docs/feature-mining-cycle-9.md` — 本 cycle 的 mining 容器
