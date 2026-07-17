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
| Service Worker `/static/*` stale-while-revalidate | ✅ R459 已升级（offline.html 兜底仍走 navigation network-first） | ✅ follow-up closed |
| MathJax 按需加载 1.17MB | ✅ R20.12-A 已通过 `mathjax-loader.js` 实现 lazy load | 否 |
| VS Code webview 懒加载脚本 readiness polling | ✅ R461 已改为 `load/error` 事件驱动 + 单 timeout guard | ✅ ship |
| VS Code host 预读 Lottie JSON | ✅ R462 已移出 `_preloadResources()`；仅 webview 需要时 fetch | ✅ ship |

**新增 commit：** 1 ship + 1 audit doc + 1 regression test = 3 commit。

**defer (见 §5)：** 1 个 future track 仍待触发；SW follow-up 已在 R459 关闭。

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
| `multi_task.js` countdown | 1s/页面共享 ticker | window.tasksCountdownTickerTimer | 最后一个倒计时结束/清理时 clearInterval |
| `feedback_drafts.js` sync | 5s | intervalId | 模块自闭包，页面卸载 GC |
| `offline.html` ping | 5s | intervalId 局部 | 服务恢复后 reload 自然停 |

**结论**：全部 setInterval 都有清理路径或自然停止条件，无内存泄漏风险。

### 3.3 R460 · 多任务倒计时共享 1Hz ticker

R128/R266 已经把倒计时热路径做过两层优化：隐藏页跳过 DOM 写入、倒计时
DOM 引用缓存。但旧实现仍然是 **N 个任务 = N 个 `setInterval(..., 1000)`**。
浏览器会对后台 timer 做节流和批处理，但每条 chained timer 仍参与调度；
任务多时，前台也会有 N 个 1Hz callback。

R460 把倒计时模型改成：

- `startTaskCountdown()` 只注册 `taskCountdowns[taskId]` 状态；
- `ensureSharedTaskCountdownTicker()` 只创建一个页面级
  `setInterval(tickAllTaskCountdowns, 1000)`；
- `tickTaskCountdown(taskId)` 继续先算 deadline，再按 `document.hidden`
  跳过 DOM 写入，`remaining <= 0` 的 auto-submit 仍在 hidden guard 外；
- 最后一个倒计时被删除或停止时清理 `window.tasksCountdownTickerTimer`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round10/01-js-timer-visibility.json`
  记录 MDN Page Visibility API：页面不可见时应避免不必要任务，后台 timer
  会被 budget-based throttling；
- `/tmp/smart-search-evidence/aiia-optimization-round10/02-chrome-timer-throttling.json`
  记录 Chrome timer throttling：`setInterval` 属于 chained timer，hidden
  pages 中 timer 会被批处理/强节流，减少 timer 数本身就是降低调度面。

### 3.4 R461 · VS Code webview lazy-script loader 去 50ms polling

VS Code webview 的 Lottie / marked / Prism / notify-core / settings-ui 都已经
是按需脚本，首屏边界正确；但旧实现的 duplicate-script 分支会在已有
`<script id="aiia-*-script">` 时用 `setTimeout(tick, 50)` 反复探测全局对象。
这类 polling 在并发打开设置、通知或 Markdown 渲染时会制造额外 chained
timer，隐藏页还会受到 Chromium 后台 timer throttling 批处理影响。

R461 抽出 `loadLazyScriptOnce(scriptId, scriptUrl, isReady, timeoutMs)`：

- 新脚本和已存在脚本都监听 `load` / `error`，并用 `{ once: true }` 自动收敛；
- 只保留一个 timeout guard，避免异常脚本或丢失事件导致 Promise 永远悬挂；
- 新建脚本继续设置 `defer` 和 CSP `nonce`；
- `ensureLottieLoaded()` 仍保留失败后清空 `lottieLoadPromise` 的恢复语义；
- marked / Prism / notify-core / settings-ui 继续保持原来的 lazy-on-first-use
  边界，不进入 HTML eager script 列表。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round11/01-script-load-events.json`
  记录 MDN/HTMLScriptElement：脚本资源会向元素发送 `load` 或 `error` 事件，
  动态插入示例也使用 `onload` / `onerror`；
- `/tmp/smart-search-evidence/aiia-optimization-round11/06-chrome-timer-exa-text.json`
  记录 Chrome timer throttling：`setTimeout` / `setInterval` 属于 timers，
  state polling 通常应改用事件，hidden pages 下 chained timers 会被批处理或
  intensive throttling。

### 3.5 R462 · VS Code host 不再预读 445KB Lottie JSON

R452 之后，VS Code webview 的无内容页 Lottie JSON 已不再内联进 HTML：
`_getHtmlContent()` 固定写 `window.__AIIA_NO_CONTENT_LOTTIE_DATA = null`，
并通过 `data-no-content-lottie-json-url` 交给 `webview-ui.js` 在无内容页真正
需要动画时 `fetch(..., { cache: 'force-cache' })`。但 `_preloadResources()`
仍然在 `resolveWebviewView()` 的 awaited critical path 上读取并 `JSON.parse`
`packages/vscode/lottie/sprout.json`（约 445KB），解析结果 `lottieData` 已没有
消费者。

R462 把 `_cachedStaticAssets` 收窄为只缓存 `activityIconSvg`：

- `loadStaticAssets()` 不再读取 `lottie/sprout.json`；
- `_preloadResources()` 仍并行预载 3 个 locale + fallback SVG；
- `resolveWebviewView()` 仍 await `_preloadResources()`，保证 locale 首帧可用；
- Lottie JSON 仍保留在 VSIX 中，并继续由 webview resource URL 懒加载；
- CSP 边界不变：`connect-src` 仍允许 `${cspSource}` / `'self'`，本地 resource
  fetch 不会被拦。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round12/02-mdn-lazy-loading-text.json`
  记录 MDN lazy loading：非关键资源应只在需要时加载，以缩短 critical
  rendering path；
- `/tmp/smart-search-evidence/aiia-optimization-round12/01-webdev-lazy-load-text.json`
  记录 web.dev：大型资源会增加启动下载、解析与执行成本；startup 阶段只加载
  初始体验必需的资源。

### 3.6 R463 · 静态压缩协商只解析一次 Accept-Encoding

`_send_with_optional_gzip()` 是 `/static/css/*`、`/static/js/*`、locale JSON、
Lottie JSON 的共享响应器。R21.4 后它要在每个静态请求上做 `br > gzip >
identity` 协商。旧实现复用 `_client_accepts_brotli()` /
`_client_accepts_gzip()` 两个 wrapper，但这两个 wrapper 都会重新调用
`_parse_accept_encoding()`，所以 `Accept-Encoding: br, gzip` 且 br 分支不命中
或需要判断 gzip 时，会对同一个 header 做第二次 split/parse。

R463 把 hot path 改成：

- 单次 `accepted_encodings = _parse_accept_encoding()`；
- 由同一集合派生 `accepts_brotli` / `accepts_gzip`；
- 保持 br 优先、gzip fallback、identity fallback 与 `Vary: Accept-Encoding`
  行为不变；
- 保留 `_client_accepts_brotli()` / `_client_accepts_gzip()` 兼容 wrapper，外部
  或历史测试仍可直接调用。

新增 `TestSendNegotiationHotPath` 用 spy 锁定每个 request 只解析一次 header，
并继续跑 R20.14-D / R21.4 的压缩协商矩阵，覆盖 `br;q=0`、`*`、br 缺失降级
gzip、仅 br 且 br 缺失降级 raw 等边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round13/01-accept-encoding-vary-exa.json`
  记录 MDN HTTP compression：浏览器通过 `Accept-Encoding` 宣告支持的算法，
  服务端选择算法并用 `Content-Encoding` 告知客户端；同一 URL 有不同编码表示
  时响应必须带 `Vary: Accept-Encoding`。

### 3.7 R464 · CSP nonce fallback 真正惰性生成

`SecurityMixin._get_csp_nonce()` 在模板上下文构建时读取 `g.csp_nonce`。旧写法：

```python
return getattr(g, "csp_nonce", secrets.token_urlsafe(16))
```

语义上看似“缺 nonce 才生成 fallback”，但 Python 会在调用 `getattr` 前先求值
全部参数，所以即使 `g.csp_nonce` 已由 `before_request` 设置，仍会额外调用一次
`secrets.token_urlsafe(16)` 并丢弃结果。这个路径覆盖每次 HTML 模板渲染；`secrets`
又是 OS-backed cryptographic randomness，没必要为已存在 nonce 支付这笔开销。

R464 改成显式 sentinel：

- request context 中存在 `g.csp_nonce` → 直接返回，不调用 `secrets`；
- request context 中缺失 `g.csp_nonce` → 仍调用 `secrets.token_urlsafe(16)`；
- 非 request context / Flask context teardown race → 保留原 fallback；
- 新增 regression test 用 `side_effect=AssertionError` 锁定“已有 nonce 不生成
  unused fallback”，并验证缺失 nonce 时仍调用 `token_urlsafe(16)`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round14/01-python-evaluation-order-exa.json`
  记录 Python 官方文档的函数调用/参数求值语义；
- `/tmp/smart-search-evidence/aiia-optimization-round14/02-python-secrets-exa.json`
  记录 Python `secrets` 官方文档：该模块用于 cryptographically strong random
  numbers，并从操作系统提供的最安全随机源取数。

### 3.8 R465 · NotificationManager inflight fallback 不再分配空 set

R136 给通知 in-flight 持久化加了 fail-soft fallback，兼容绕开 `__init__`
的测试 helper / 老路径。但 `_persist_inflight_unlocked()` 和 `get_status()`
旧写法都是：

```python
getattr(self, "_inflight_persisted_ids", set())
```

Python 调用语义会先求值全部实参，再进入 `getattr()`；因此即使正常初始化的
`NotificationManager` 已经有 `_inflight_persisted_ids`，每次持久化刷新和每次
status 轮询仍会构造一个马上丢弃的空 `set`。R465 改成 `None` sentinel：

- `_persist_inflight_unlocked()`：`None` / 空集合继续按空集合处理，删除 stale
  inflight 文件；
- `get_status()`：字段存在时直接 `len(existing_set)`；字段缺失时返回 0；
- 兼容绕开 `__init__` 的 helper：缺 attr 仍不抛，不改变 R136 fail-soft 语义；
- 新增回归测试通过 patch 模块级 `set` 名称，锁定 initialized path 不再调用
  unused `set()` fallback，同时覆盖缺 attr 仍按空集合/0 处理。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round15/04-python3-calls-docs-exa.json`
  记录 Python 3 官方 expressions 文档：调用表达式中实参会在调用前求值，且
  Python 按从左到右顺序求值表达式。

### 3.9 R466 · 任务导出时间戳单快照

`GET /api/tasks/export` 旧实现会在同一次导出里多次调用 `_dt.now(UTC)`：

- 先生成下载文件名里的 `YYYYMMDDTHHMMSSZ`；
- JSON 模式再生成顶层 `exported_at`；
- Markdown 模式再生成头部 `Exported at`。

这有两个问题：第一，多一次 UTC `now()` 调用没有必要；第二，如果导出刚好跨秒，
文件名与 payload 内的 `exported_at` 会出现 1 秒漂移，虽然不破坏功能，但降低
审计快照的一致性。R466 改为每次 export 捕获一次：

```python
exported_at = _dt.now(UTC)
exported_at_iso = exported_at.isoformat()
stamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
```

然后 JSON / Markdown / filename 全部复用同一个对象。新增测试分别覆盖 JSON 与
Markdown 分支：patch route 模块的 `_dt`，断言 `now(UTC)` 只调用一次，同时
`Content-Disposition` 文件名和 `exported_at` / Markdown header 完全一致。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round16/01-python-datetime-now-docs-exa.json`
  记录 Python datetime 官方文档：`datetime` 模块用于日期时间处理，`UTC`
  是 UTC 时区 singleton，`strftime()` 将 date/datetime/time 按格式转成字符串。

### 3.10 R467 · TaskQueue restore 时间戳单快照

`TaskQueue._restore()` 旧实现会在一次启动恢复里多次调用
`datetime.now(UTC)`：

- `saved_at` 缺失时生成 fallback；
- 计算 `elapsed_since_save` 日志字段；
- 每个任务重建 `created_at_monotonic` 时再次取当前 UTC 时间。

因此恢复 N 个任务时会产生 `N + 1` 次 wall-clock 读取（缺 `saved_at` 时为
`N + 2`），并且不同任务的 `created_at_monotonic` 基线会带有恢复循环内的微小
时钟漂移。R467 改为 `_restore()` 成功解析 snapshot 后捕获一次：

```python
restore_now = datetime.now(UTC)
```

随后 `saved_at` fallback、`elapsed_since_save`、每个 task 的
`age_since_creation` 全部复用该对象。这样启动恢复阶段只做一次 UTC wall-clock
读取，且所有恢复任务共享同一个 wall-clock snapshot；倒计时仍以
`time.monotonic()` 重建，保留不受系统时间回拨影响的运行期语义。

新增回归测试覆盖：

- 有 `saved_at` 且包含多个任务时，restore 只调用一次 `now(UTC)`；
- 旧 snapshot 缺 `saved_at` 时仍只调用一次 `now(UTC)`，fallback 与 elapsed
  计算共享同一时间点；
- 两个路径都验证任务仍正常恢复，避免把性能断言变成纯静态锁。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round17/01-python-datetime-now-docs-exa.json`
  记录 Python datetime 官方文档：`datetime.now(tz)` 返回指定时区下的当前
  local date/time，`UTC` 是 UTC 时区 singleton。
- `/tmp/smart-search-evidence/aiia-optimization-round17/02-python-time-monotonic-docs-exa.json`
  记录 Python time 官方文档：`time.monotonic()` 返回不会倒退、不受系统时钟
  更新影响的单调钟，返回值 reference point 未定义，只有两次调用差值有效。

### 3.11 R468 · SSE heartbeat payload 固定格式直写

`/api/events` 的 idle heartbeat 每个 SSE 连接每 25 秒发送一次。旧实现每次都
构造一份 `{"ts_unix": int(time.time())}` dict，再调用：

```python
json.dumps({"ts_unix": int(time.time())}, ensure_ascii=False)
```

但 heartbeat payload 是固定 schema：一个 ASCII key + 一个整数时间戳。R468
抽出 `_format_sse_heartbeat_payload()`，直接返回：

```python
f'{{"ts_unix":{ts_unix}}}'
```

这样每个 idle heartbeat 少一次临时 dict 分配和一次通用 JSON encoder 调用；
wire contract 不变，前端仍用 `JSON.parse(e.data)` 读取 `ts_unix`。边界上，
`time.time()` 异常 mock、`inf` / `nan` / 非数值输入都返回 `"{}"`，保留
“heartbeat 不因时间源异常打断 stream”的 fail-soft 语义。

新增回归测试覆盖：

- formatter 输出可被 `json.loads` 还原为 `{"ts_unix": <int>}`；
- patch `json.dumps` 为抛异常时 formatter 仍成功，锁定 heartbeat hot path
  不走通用 encoder；
- `inf` / `nan` / 非数字输入回退 `"{}"`；
- generator 的 `queue.Empty` heartbeat 分支调用 formatter，且该分支源码中不再
  出现 `json.dumps(`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round18/01-mdn-sse-event-stream-format-exa.json`
  记录 MDN Server-Sent Events：event stream 是 UTF-8 文本，message 由
  `event:` / `data:` 等字段组成；named event 的 `data` 字段可以是 JSON 字符串，
  客户端通过 `JSON.parse(event.data)` 解析。
- `/tmp/smart-search-evidence/aiia-optimization-round18/02-python-json-dumps-docs-exa.json`
  记录 Python `json.dumps` 官方文档：`dumps(obj)` 会按转换表把对象序列化为
  JSON 字符串；默认 separators 带空格，若要更紧凑需额外指定 separators。

### 3.12 R469 · NotificationManager startup inflight fallback 不再分配空 list

R465 已经把 `get_status()` 里的 `_inflight_persisted_ids` fallback 从
`getattr(..., set())` 改成 `None` sentinel，避免 status 轮询时分配马上丢弃的
空集合。同一返回 payload 里还残留一处：

```python
list(getattr(self, "_inflight_seen_at_startup", []))
```

由于 Python 调用表达式会在调用前先求值全部实参，正常初始化的 manager 即使
已经有 `_inflight_seen_at_startup`，也会在每次 status 轮询时构造一个未使用的
空 list。R469 改成：

```python
inflight_seen_at_startup = getattr(self, "_inflight_seen_at_startup", None)
inflight_seen_at_startup_copy = (
    list(inflight_seen_at_startup)
    if inflight_seen_at_startup is not None
    else []
)
```

这样 initialized path 只做必要的 defensive copy；绕开 `__init__` 的老测试 helper
或异常对象仍返回 `[]`，保持 R136 fail-soft status 契约。

新增回归测试覆盖：

- `NotificationManager.get_status` 源码中不再出现
  `getattr(self, "_inflight_seen_at_startup", [])`；
- 缺失 `_inflight_seen_at_startup` attr 时仍返回空 list；
- 已有 `test_inflight_seen_at_startup_is_copy_not_internal_ref` 继续锁定返回值是副本，
  外部 append 不会污染内部状态。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方文档：表达式按从左到右求值，调用表达式中的参数表达式会在
  函数调用前求值；因此 `getattr(obj, name, [])` 的 `[]` 不是惰性 fallback。

### 3.13 R470 · system token age datetime import 提升到模块级

`web_ui_routes/system.py` 的 `_compute_age_seconds_from_iso()` 是两个路径共享的
token age hot helper：

- Prometheus `/metrics` 的 `aiia_token_age_seconds`；
- `GET /api/system/api-token-info` 的 `age_seconds` 字段。

旧实现每次 helper 调用都会执行：

```python
from datetime import UTC, datetime
```

`POST /api/system/rotate-api-token` 生成 `rotated_at` 时也有同样的局部 import。
虽然 `datetime` 模块本身会被 `sys.modules` 缓存，但 import statement 仍要执行
查找和局部名称绑定。R470 把 `UTC` / `datetime` 提升到 `system.py` 模块级，
helper 和 rotation endpoint 复用同一组绑定：

```python
from datetime import UTC, datetime
```

行为边界保持不变：`Z` 后缀继续替换为 `+00:00`，非法 / 非字符串 / 未来时间戳
仍返回 `None`，正常路径仍返回整数秒。新增 source invariant 锁定 helper 内部不再
出现局部 `datetime` import，且模块内该 import 只保留一处，防止后续把重复 import
带回 token age 轮询路径。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round20/01-python-import-system-docs-exa.json`
  记录 Python 官方 import system 文档：import statement 结合 search 与 name
  binding；模块缓存会先查 `sys.modules`，但语句本身仍会执行绑定步骤。

### 3.14 R471 · static Accept-Encoding parser 不再分配空 dict fallback

R463 已经把 `_send_with_optional_gzip()` 的 `Accept-Encoding` 解析从两次收敛到
一次，但 `_parse_accept_encoding()` 内部仍有一处 eager fallback：

```python
accept = getattr(src, "headers", {}).get("Accept-Encoding", "")
```

在正常 Flask request 路径中 `src.headers` 一定存在，第三个参数里的 `{}` 只是
为了测试 mock / 异常对象兜底；但 Python 会在调用 `getattr()` 前先构造这个空
dict。静态资源首屏会多次进入该 helper（CSS、JS、locale JSON、Lottie JSON），
每次都为正常路径分配一个马上丢弃的空 dict。

R471 改为显式 `None` sentinel：

```python
headers = getattr(src, "headers", None)
if headers is None:
    return set()
accept = headers.get("Accept-Encoding", "")
```

行为边界不变：缺 `headers` attr 仍按无 `Accept-Encoding` 返回空集合；真实
headers mapping 仍通过 `.get("Accept-Encoding", "")` 读取；后续 q 值解析、
`br > gzip > identity` 协商、`Vary: Accept-Encoding` 均不变。新增测试覆盖缺
`headers` attr 的 runtime fallback，并用 source invariant 防止
`getattr(src, "headers", {})` 回到静态资源 hot parser。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round21/01-python-call-argument-evaluation-getattr-exa.json`
  记录 Python 官方 built-in/getattr 文档检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：函数调用前会先求值调用表达式中的参数表达式。

### 3.15 R472 · NotificationManager provider stats 默认值惰性创建

`NotificationManager._send_single_notification()` 会在 4 个结果路径更新
per-provider stats：

- provider 未注册；
- provider 调用前记录 attempts；
- provider 返回后记录 latency / success / failure；
- provider 抛异常。

旧实现每个 stats block 都写：

```python
providers = self._stats.setdefault("providers", {})
stats = providers.setdefault(notification_type.value, { ...完整 stats schema... })
```

这里有两层 eager 默认值成本：即使 `_stats["providers"]` 已存在，也会先构造空
`{}`；即使当前 provider stats 已存在，也会先构造完整 stats schema dict 再被
`setdefault()` 丢弃。通知发送路径每个 provider 至少进入两次 stats block
（attempt + result），高频通知或多 provider fan-out 时这属于纯分配噪声。

R472 抽出：

```python
_get_or_create_provider_stats(self._stats, notification_type.value)
```

helper 只在 `"providers"` key 真缺失时创建 providers dict，只在 provider key
真缺失时调用 `_new_provider_stats()`。已有 provider stats 的正常路径复用原对象，
不再构造 unused 默认 dict；`_stats` 损坏、`providers` 非 dict、provider stats
非 dict 等异常状态仍在原来的 stats `try/except` 中 fail-soft，不影响通知发送。

新增回归测试覆盖：

- 已有 provider stats 时 patch `_new_provider_stats` 为抛异常，确认不会分配默认；
- 缺 provider key 时创建完整默认 schema；
- `_send_single_notification()` 源码中不再出现
  `setdefault("providers", {})` / `providers.setdefault(...)`，并调用 lazy helper。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round22/01-python-dict-setdefault-call-evaluation-exa.json`
  记录 Python dict `setdefault(key[, default])` 官方文档：key 存在时返回已有值，
  缺失时插入 default；
- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：函数调用前会先求值调用表达式中的参数表达式。

### 3.16 R473 · `/api/config` option defaults fallback 惰性化

`GET /api/config` 是 Web / VS Code / PWA 前端的轮询型配置入口。TaskQueue active
和 pending 自动激活分支旧实现都写：

```python
getattr(task, "predefined_options_defaults", []) or []
```

正常任务对象通常已经带 `predefined_options_defaults`，但 Python 会在进入
`getattr()` 前先求值第三个实参，所以每次轮询都会先构造一个未使用的空 list。
旧单任务兼容分支也有：

```python
list(getattr(self, "current_options_defaults", []))
```

这同样会在正常 `current_options_defaults` 存在时分配一个 unused `[]`。

R473 把 TaskQueue 分支收敛到 `_task_predefined_options_defaults(task)`：

- attr 存在且为 truthy list → 直接复用原对象，保持旧 wire 行为；
- attr 缺失 / `None` / 空 list → 仍返回 `[]`，保持旧 `or []` 语义；
- active task 和 first pending task 都复用同一个 helper，避免分支漂移。

单任务分支改用模块级 `_MISSING_OPTION_DEFAULTS` sentinel：

- attr 缺失 → 返回 `[]`，兼容绕过 `__init__` 的旧测试 helper / 异常对象；
- attr 存在 → 继续 `list(current_options_defaults)` 做 defensive copy；
- attr 存在但值不可迭代时仍按旧行为抛出并进入 `/api/config` fail-soft 500，
  不把错误状态静默改成空默认值。

新增回归测试覆盖 helper 的缺 attr / 已有 truthy 值路径、active task 缺默认值的
runtime fallback、单任务缺 attr fallback，并用 source invariant 锁定
`getattr(..., [])` 不回到这三条 `/api/config` option-defaults 路径。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round23/01-python-getattr-call-evaluation-exa.json`
  记录 Python `getattr(object, name[, default])` 的默认值参数语义；
- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：函数调用前会先求值调用表达式中的参数表达式。

### 3.17 R474 · network-security TESTING guard fallback 惰性化

R325 把 `SecurityMixin._ensure_network_security_config_loaded()` 设计成 request
enforcement 前的单属性 lazy loader：第一次请求时加载 `network_security_config`，
但在 `app.config["TESTING"]` 为真时短路，避免测试环境读真实配置文件。旧 TESTING
guard 写成：

```python
getattr(getattr(self, "app", None), "config", {}).get("TESTING")
```

正常 `WebFeedbackUI` 实例一定有 `self.app.config`，但第三个参数里的 `{}` 会在
调用 `getattr()` 前先构造；也就是说每次 lazy loader 进入未加载判断时，都会为
已有 app config 分配一个 unused 空 dict。

R474 改成模块级 `_MISSING_APP_CONFIG` sentinel：

- `self.app.config` 存在 → 直接读取 `.get("TESTING")`，不构造 fallback dict；
- `self.app` 或 `config` attr 缺失 → 与旧 `{}` fallback 一样视为非 TESTING，
  继续按普通路径加载配置；
- `config` attr 存在但不是 mapping / 没有 `.get` → 保持旧异常行为，不把损坏
  app 状态静默当成非 TESTING。

新增回归测试覆盖 TESTING short-circuit 不调用 `_load_network_security_config()`，
并用 source invariant 锁定
`getattr(getattr(self, "app", None), "config", {})` 不回到 lazy loader。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round24/02-python-calls-docs-exa.json`
  记录 Python expressions/calls 官方文档：调用前会先求值全部 argument
  expressions；
- `/tmp/smart-search-evidence/aiia-optimization-round24/01-python-getattr-dict-fallback-evaluation-exa.json`
  记录 Python 官方文档检索结果，补充 `getattr(..., default)` 与执行模型上下文。

### 3.18 R475 · Notification provider 结果时间戳复用完成时快照

`NotificationManager._send_single_notification()` 的正常 provider path 旧流程是：

```python
started_at = time.time()
ok = provider.send(event)
latency_ms = max(int((time.time() - started_at) * 1000), 0)
...
now = time.time()
stats["last_success_at" 或 "last_failure_at"] = now
```

一次 provider 发送完成后，`latency_ms` 的结束时间和 `last_success_at` /
`last_failure_at` 的语义边界本质上都是“provider 调用完成时”。旧实现多读一次
wall clock，且两个字段之间可能产生微小漂移；高频通知、多 provider fan-out 时
这属于重复系统时间读取。

R475 改成：

```python
completed_at = time.time()
latency_ms = max(int((completed_at - started_at) * 1000), 0)
stats["last_success_at" 或 "last_failure_at"] = completed_at
```

行为边界：

- provider 正常返回 `True` / `False` 时，wall-clock 读取从 3 次降到 2 次；
- `last_success_at` / `last_failure_at` 与 latency sample 使用同一个完成时快照，
  dashboard 上的“最近状态时间”和“本次耗时”不再有 intra-event 漂移；
- `completed_at < started_at` 的系统时钟回拨边界继续通过 `max(..., 0)` 把
  latency clamp 到 0；
- provider 抛异常路径仍保持单独 `time.time()` 记录失败时间，因为没有正常
  `completed_at` 快照，且不记录 latency sample。

新增回归测试用 patch 后的两点时钟序列锁定 success / failure 正常返回路径：
`time.time()` 只调用两次，`last_latency_ms` 和 `last_success_at` /
`last_failure_at` 都来自同一个完成时值；source invariant 防止重新引入
`now = time.time()`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round25/01-python-time-time-docs-exa.json`
  记录 Python `time.time()` 官方文档：返回 seconds since epoch 的浮点 wall-clock
  时间；该值通常非递减，但系统时钟回拨时可能低于上一次调用。

### 3.19 R476 · system health 请求时间戳单快照

`GET /api/system/health` 旧流程先用一次 `time.time()` 生成顶层
`ts_unix`，随后 `_safe_notification_summary()` 在整理
`checks.notification.per_provider.*_age_seconds` 时又读一次 wall clock。两者
语义上都属于同一次 health probe 的观测时刻，重复读取会制造很小但不必要的
intra-response 漂移。

R476 改成：

```python
now = time.time()
ts = int(now)
...
notification_summary = _safe_notification_summary(now)
```

同时 `_safe_notification_summary(now: float | None = None)` 保留直接调用时的
懒读行为；只有 health handler 传入请求级快照。这样 `/api/system/health` 的
顶层 freshness 字段和 provider 最近成功 / 失败 age 使用同一个时间边界。

行为边界：

- direct helper caller 仍可无参调用，异常 / 非 dict status 仍返回 `None`；
- `per_provider.last_*_age_seconds` 仍由 `_safe_per_provider_snapshot()` 统一计算，
  future timestamp 或系统时钟回拨边界继续 clamp 到 `0.0`；
- health payload 不新增字段，不暴露 notification config / provider 原始错误文本；
- 成功 summary path 少一次重复 wall-clock 读取。

新增回归测试锁定 handler 源码必须 `now = time.time()`、`ts = int(now)`、
`_safe_notification_summary(now)`，并用 patch 验证传入的 `now` 原样流入
`_safe_per_provider_snapshot()`。

### 3.20 R477 · MCP tool call stats setdefault 默认 dict 惰性化

`mcp_tool_call_metrics.get_mcp_tool_call_stats()` 是 Prometheus `/metrics`
渲染会读取的 MCP tool counter 快照 helper。旧实现按 counter snapshot 的每个
`(tool_name, status)` key 执行：

```python
result.setdefault(tool_name, {"success": 0, "failure": 0, "total": 0})
```

当同一个 tool 已经处理过 success、再处理 failure（或反过来）时，`setdefault`
仍会先构造一份 unused 默认 stats dict，再返回已有 dict。工具数量和状态数增长
后，这会在每次 scrape 里制造纯分配噪声。

R477 改成显式 missing branch：

```python
tool_stats = result.get(tool_name)
if tool_stats is None:
    tool_stats = {"success": 0, "failure": 0, "total": 0}
    result[tool_name] = tool_stats
```

行为边界：

- 返回 payload 仍是 `{tool: {success, failure, total}}`，外部修改仍不污染内部
  counter；
- counter snapshot 仍在锁内 copy，聚合仍在锁外完成，不扩大临界区；
- success / failure / total 语义不变；
- 已存在 tool 的第二个 status 不再分配 unused 默认 dict。

新增 source invariant 锁定 `get_mcp_tool_call_stats()` 不再出现 `setdefault(`，
并继续跑 R187 / R190 / R186 相关 metrics 契约测试。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round26/01-python-dict-setdefault-docs-exa.json`
  记录 CPython issue 讨论：`setdefault()` 是方法调用，arguments 会先求值，
  再进入方法；这不是 bug，而是 Python 调用语义。

### 3.21 R478 · `/api/config` TaskQueue 分支复用 monotonic 快照

`GET /api/config` 是 Web / VS Code / PWA 前端轮询配置与当前任务内容的入口。
TaskQueue active / pending 分支旧实现直接调用：

```python
"remaining_time": active_task.get_remaining_time()
```

`Task.get_remaining_time()` 内部会在未传 `now_monotonic` 时读取
`time.monotonic()`。同一项目较新的 `/api/tasks` 和 `/api/tasks/<id>` 路由
已经在 request 层捕获 `now_monotonic = time.monotonic()`，然后传入每个 task，
避免每个任务对象各自读取单调钟。`/api/config` 虽然每次只返回一个 task，但它是
高频轮询入口，仍应复用同一套快路径。

R478 抽出 `_task_remaining_time(task, now_monotonic)`：

- 真实 `Task` 路径调用 `get_remaining_time(now_monotonic=...)`，避免 helper 内部
  再读一次 `time.monotonic()`；
- legacy task-like object / 旧测试 double 若只支持无参 `get_remaining_time()`，
  捕获 `TypeError` 后回退无参调用，保持兼容；
- `deadline` 仍沿用 `/api/config` 原有 `created_at.timestamp() + timeout` 语义，
  本轮不混入行为变更；
- 单任务 fallback 分支不受影响，因为它没有 TaskQueue 倒计时对象。

新增回归测试覆盖 helper 的无参兼容路径、handler 源码必须调用
`_task_remaining_time(active_task, now_monotonic)` /
`_task_remaining_time(first_task, now_monotonic)`，并用 runtime fake task 验证
route 捕获的 monotonic 快照原样传入 `get_remaining_time()`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round17/02-python-time-monotonic-docs-exa.json`
  记录 Python `time.monotonic()` 官方文档：单调钟不会倒退、不受系统时钟更新
  影响，返回值 reference point 未定义，只有两次调用差值有效。

### 3.22 R479 · pyproject version parser 去 eager `{}` fallback

`web_ui.get_project_version()` 在 importlib metadata 不可用时会解析
`pyproject.toml` 的 `[project].version`。旧实现写成：

```python
raw_version = data.get("project", {}).get("version", "unknown")
```

虽然 `get_project_version()` 有 `lru_cache`，这条 fallback 只在进程冷路径发生，
但它仍属于同一类 Python 调用语义问题：`{}` 会在调用 `.get()` 前先构造，即使
`project` key 存在也用不上。同时旧写法隐含假设 `project` 一定是 mapping；
若损坏 TOML 解析成 `{"project": "not a table"}`，会走异常 fallback 读文本正则，
而不是明确返回 `unknown`。

R479 改成：

```python
project_data = data.get("project")
raw_version = (
    project_data.get("version", "unknown")
    if isinstance(project_data, dict)
    else "unknown"
)
```

行为边界：

- 正常 `[project] version = "X.Y.Z"` 返回值不变；
- `project` 缺失或不是 dict 时返回 `unknown`，不依赖 chained fallback；
- tomllib 抛异常时仍进入 regex 兜底，保留 BUG3 修复后的恢复路径；
- importlib metadata 优先级和 `lru_cache(maxsize=1)` 不变。

新增测试覆盖 malformed `project` 非 mapping 时返回 `unknown`，并用 source
invariant 锁定 `data.get("project", {})` 不回到 parser。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：函数 / 方法调用前会先求值调用表达式中的
  argument expressions。

### 3.23 R480 · NotificationManager status provider stats fallback 惰性化

`NotificationManager.get_status()` 是 health / metrics / debug UI 会反复读取的
状态快照入口。旧实现复制 per-provider stats 时写成：

```python
providers_stats = {
    k: dict(v) for k, v in self._stats.get("providers", {}).items()
}
```

正常初始化后 `self._stats["providers"]` 一定存在，但 `.get(..., {})` 的 `{}` 会在
方法调用前先构造，再被丢弃。R465/R469 已经把同一个 `get_status()` 内的
`getattr(..., set())` / `getattr(..., [])` 清掉；R480 把 provider stats 这一处也
收敛到显式 missing branch：

```python
providers_stats_raw = self._stats.get("providers")
if not isinstance(providers_stats_raw, dict):
    providers_stats_raw = {}
providers_stats = {k: dict(v) for k, v in providers_stats_raw.items()}
```

行为边界：

- 正常路径仍返回 per-provider stats 的浅拷贝，caller 不能反向污染内部状态；
- `providers` key 缺失或被损坏为非 dict 时仍返回空 provider snapshot；
- 派生的 `events_finalized` / `events_in_flight` / success_rate / avg_latency_ms
  计算不变；
- stats lock 粒度不变，只替换 fallback 创建策略。

新增回归测试锁定 `get_status()` 源码不再出现
`self._stats.get("providers", {})`，并覆盖缺失 `providers` key 时
`status["stats"]["providers"] == {}`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：方法调用参数会在进入方法前先求值。

### 3.24 R481 · health notification summary 集合 fallback 惰性化

`_safe_notification_summary()` 是 `/api/system/health` 和 metrics 相邻路径会读取的
notification 摘要 helper。R480 把 `NotificationManager.get_status()` 内部的
provider stats fallback 惰性化后，health summary 自己仍有三处 eager fallback：

```python
providers = status.get("providers", [])
stats = status.get("stats", {})
providers_stats_raw = stats.get("providers", {})
```

正常 manager status payload 都含这些 key，但 `[]` / `{}` 会在 `.get()` 前先构造；
而 health endpoint 是探针/监控轮询路径，不应为正常 payload 分配 unused fallback
容器。R481 改成显式 missing branch：

```python
providers = status.get("providers")
providers_count = len(providers) if isinstance(providers, list) else 0

stats = status.get("stats")
if not isinstance(stats, dict):
    stats = {}

providers_stats_raw = stats.get("providers")
if not isinstance(providers_stats_raw, dict):
    providers_stats_raw = {}
```

行为边界：

- status 缺 `providers` 时 `providers_count` 仍为 0；
- status 缺 `stats` 或 `stats.providers` 非 dict 时仍按空 provider snapshot；
- 敏感字段边界不变：不透出 `config`、原始 `stats`、provider 原始 error 文本；
- R476 的 request-level `now` 快照继续传入 `_safe_per_provider_snapshot()`。

新增测试覆盖缺 `providers` / `stats` 的 runtime fallback，并用 source invariant
锁定三处 eager `[]` / `{}` fallback 不回到 `_safe_notification_summary()`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：方法调用参数会在进入方法前先求值。

### 3.25 R482 · NotificationManager callback fallback 惰性化

`NotificationManager.trigger_callbacks()` 是 notification sent / retry / fallback 等事件
都会经过的同步 fanout 点。旧实现：

```python
callbacks = list(self._callbacks.get(event_name, []))
```

即使事件名存在，也会先构造 unused `[]` fallback；事件不存在时再把空列表 copy
成另一个空列表。R482 改成：

```python
callbacks_raw = self._callbacks.get(event_name)
callbacks = list(callbacks_raw) if callbacks_raw is not None else []
```

行为边界：

- 已注册 callback 仍在 `_callbacks_lock` 下 snapshot 成 list，再在锁外执行；
- 缺失事件仍为 no-op，且不写入 `_callbacks`；
- callback exception 仍记录 error，并不阻断后续 callback。

新增测试覆盖缺失事件 no-op，并用 source invariant 锁定
`self._callbacks.get(event_name, [])` 不回到热路径。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：方法调用参数会在进入方法前先求值。

### 3.26 R483 · notify-new-tasks taskIds fallback 惰性化

`/api/notify-new-tasks` 兼容新字段 `taskIds` 和旧字段 `task_ids`。旧实现：

```python
raw_task_ids = data.get("taskIds", data.get("task_ids", []))
```

会在每次请求中先计算 legacy fallback，即使 primary `taskIds` 已存在；同时还会构造
unused `[]`。R483 改成 key-presence branch：

```python
if "taskIds" in data:
    raw_task_ids = data["taskIds"]
else:
    raw_task_ids = data.get("task_ids")
```

行为边界：

- `taskIds` 存在时仍优先使用 primary 字段；
- `{"taskIds": None, "task_ids": [...]}` 仍不回退到 legacy key，保持旧
  `dict.get()` 对 explicit `None` 的行为；
- `taskIds` 缺失时仍支持 legacy `task_ids`；
- 非 list、空元素过滤、最多 50 个 task id、每个 id 截断到 200 字符的逻辑不变。

新增测试覆盖 legacy key、explicit `None` 不 fallback，并用 source invariant 锁定
nested `.get(..., data.get(..., []))` 不回到 route path。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：方法调用参数会在进入方法前先求值。

### 3.27 R484 · network security collection fallback 惰性化

网络安全配置验证与请求期 IP access-control 还有三处 eager empty-list fallback：

```python
blocked_ips = cfg.get("blocked_ips", [])
validate_blocked_ips(config.get("blocked_ips", []))
validate_trusted_hosts(config.get("trusted_hosts", []))
```

R484 把 validator 的 missing-key path 改为先读取 raw value，再复用现有
`validate_blocked_ips(None)` / `validate_trusted_hosts(None)` 非 list 归一化逻辑；
请求期 `_is_ip_allowed()` 则先读取 `blocked_ips_raw`，只在 list/tuple 时遍历：

```python
blocked_ips_raw = cfg.get("blocked_ips")
blocked_ips = blocked_ips_raw if isinstance(blocked_ips_raw, (list, tuple)) else ()
```

行为边界：

- 缺失 `blocked_ips` / `trusted_hosts` 时仍归一化为 `[]`；
- `blocked_ips` 配置被损坏为 string 时仍不阻断合法请求，也不再逐字符尝试解析；
- list 形态黑名单 CIDR、单 IP、异常条目跳过逻辑不变；
- access-control disabled short-circuit、allowed_networks fallback 不变。

新增测试覆盖 validator missing-key 行为、request path 中 malformed `blocked_ips`
的 runtime 行为，并用 source invariant 锁定三处 eager `[]` fallback 不回归。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round19/01-python-call-argument-evaluation-docs-exa.json`
  记录 Python 官方表达式求值语义：方法调用参数会在进入方法前先求值。

### 3.28 R485 · MCP structured-response parser list fallback 惰性化

`server_config.parse_structured_response()` 是 MCP/server feedback payload 转
`TextContent` / `ImageContent` 的共享路径。旧实现：

```python
selected_options_raw = response_data.get("selected_options", [])
images = response_data.get("images", []) or []
```

即使 payload 已含目标字段，也会先构造 unused `[]` fallback。R485 改成：

```python
selected_options_raw = response_data.get("selected_options")
images = response_data.get("images") or ()
```

行为边界：

- 缺失 `selected_options`、`selected_options=None`、非 list 仍归一化为 `[]`；
- 缺失 `images`、`images=None`、空列表仍不生成图片 content；
- truthy 非 list `images` 的容错遍历语义不变，非 dict 条目继续跳过；
- `_lazy_mcp_types()` 单次 hoist、prompt suffix、legacy `interactive_feedback`
  兼容逻辑不变。

新增测试覆盖空 payload runtime 行为，并用 source invariant 锁定
`response_data.get("selected_options", [])` / `response_data.get("images", [])`
不回到 parser path。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.29 R486 · feedback route JSON collection fallback 惰性化

`web_ui_routes.feedback` 的 JSON submit/update path 仍有三处 eager list fallback：

```python
data.get("selected_options", [])
data.get("images", [])
data.get("predefined_options", [])
```

这些字段后续本来都会经过 `_sanitize_selected_options()`、`isinstance(images, list)`
或 `None -> []` 归一化。R486 改成直接读取 raw value：

```python
selected_options = _sanitize_selected_options(data.get("selected_options"))
images = data.get("images")
new_options_raw = data.get("predefined_options")
```

行为边界：

- `selected_options` 缺失、`None`、非 list 仍归一化为 `[]`；
- `images` 缺失、`None`、非 list 仍归一化为 `[]`；
- `/api/update` 缺失或 explicit `predefined_options=None` 仍返回空列表；
- 非 list `predefined_options` 仍返回 400；
- 现有表单 multipart 路径不变。

新增 source invariant 覆盖 `FeedbackRoutesMixin._setup_feedback_routes()`，锁定三处
eager `[]` fallback 不回到 submit/update route path。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.30 R487 · system health status-decision dict fallback 惰性化

`/api/system/health` 在聚合 `checks` 后会读取 `sse_bus`、`recent_errors` 和
`notification` 三个子检查参与 status 决策。旧实现：

```python
sse_check = checks.get("sse_bus", {})
re_check = checks.get("recent_errors", {})
notif_check = checks.get("notification", {})
```

即使三个 key 在正常路径都已存在，也会先构造 unused `{}` fallback。R487 改成：

```python
sse_check = checks.get("sse_bus")
re_check = checks.get("recent_errors")
notif_check = checks.get("notification")
```

行为边界：

- 子检查存在且为 dict 时，backpressure / recent error / notification degraded
  判定不变；
- 子检查缺失或被损坏为非 dict 时，原本的 `isinstance(..., dict)` guard 仍把
  数值降级为 0 / false；
- health payload shape、HTTP 200/503 决策、notification request-level `now`
  快照复用不变。

新增 source invariant 覆盖 `system_health()` handler，锁定三处 eager `{}` fallback
不回到 probe path。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.31 R488 · TaskQueue restore tasks fallback 惰性化

`TaskQueue._restore()` 是进程启动 / 持久化恢复路径。旧实现：

```python
for item in data.get("tasks", []):
```

正常持久化文件都会包含 `tasks` list，但 Python 仍会先构造 unused `[]` fallback。
R488 改成显式 raw read + list guard：

```python
tasks_raw = data.get("tasks")
tasks_items = tasks_raw if isinstance(tasks_raw, list) else ()
for item in tasks_items:
```

行为边界：

- 合法 `tasks` list 仍逐条恢复；
- 缺失 `tasks` 或非 list `tasks` 仍退化为空队列，符合现有 resilience 测试文件
  的契约描述；
- 单条非 dict / 单条损坏 task 的 skip 逻辑不变；
- R467 的单次 `restore_now = datetime.now(UTC)` 快照复用不变。

新增 source invariant 锁定 `data.get("tasks", [])` 不回到 restore path，并继续跑
restore resilience / hot reload 持久化测试覆盖运行时行为。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.32 R489 · service_manager trusted_hosts fallback 惰性化

`service_manager.get_web_ui_config()` 是 Web UI 子进程启动 / config cache miss /
config hot reload 后会走的配置构造路径。旧实现：

```python
trusted_hosts=[
    str(item)
    for item in network_security_config.get("trusted_hosts", [])
    if isinstance(item, str) and item.strip()
]
```

正常 `network_security` 配置已经有 `trusted_hosts` 字段时，仍会先构造 unused
`[]` fallback。R489 改成：

```python
trusted_hosts_raw = network_security_config.get("trusted_hosts")
trusted_hosts_source = (
    trusted_hosts_raw if isinstance(trusted_hosts_raw, list) else ()
)
```

行为边界：

- `trusted_hosts` 为 list 时仍只保留非空字符串；
- 缺失或非 list 时仍归一化为空列表；
- env override、mDNS hostname、cache generation token 逻辑不变；
- `WebUIConfig` 构造和后续 CLI argv `--trusted-hosts` 拼接语义不变。

新增 runtime 测试覆盖非 list fallback，并用 source invariant 锁定
`network_security_config.get("trusted_hosts", [])` 不回到 config-load path。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.33 R490 · config manager network_security fallback 惰性化

`config_modules.network_security.NetworkSecurityMixin` 是启动、config hot reload、
`GET /api/system/api-token-info` 相邻路径会读取的 network security 配置层。旧实现
在 validator 和 loader 中还有多处 eager fallback：

```python
self._get_default_config().get("network_security", {})
raw.get("allowed_networks", default_ns.get("allowed_networks", []))
raw.get("blocked_ips", default_ns.get("blocked_ips", []))
raw.get("trusted_hosts", default_ns.get("trusted_hosts", []))
full_config.get("network_security", {})
```

R490 改成：

- `network_security` 段先 raw read，再 `isinstance(..., dict)`；
- `allowed_networks` / `blocked_ips` / `trusted_hosts` 用 key-presence branch，
  只在字段缺失时读取 default section；
- default section 自身缺失或损坏时降级为 `{}`；
- 显式 `None` 仍按非 list / 非 dict 旧语义处理，不被误替换成 default list。

行为边界：

- 缺失 `network_security` 仍使用默认配置；
- 缺失 collection 字段仍使用 default config 中对应字段；
- explicit `None` / 非 list collection 字段仍进入现有 warning + fallback 逻辑；
- dedupe、CIDR/IP normalization、trusted host filtering、api token 字段不变；
- cache hit / stale cache fallback / exception fallback 逻辑不变。

新增 source invariant 覆盖 validator 和 loader，不允许 eager `{}` / `[]` fallback
回到 network-security config path；继续跑 network-security 全量相关测试验证运行时
边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.34 R491 · enhanced_logging web_ui config fallback 惰性化

`enhanced_logging.get_log_level_from_config()` 是 standalone server 启动和
runtime log-level 配置路径的共享入口。旧实现：

```python
web_ui_config = config_manager.get("web_ui", {})
```

即使 `web_ui` 段存在，也会在调用 `ConfigManager.get()` 前先构造 unused `{}`。
R491 改成无 default 读取，并只在返回值不是 dict 时本地归一化：

```python
web_ui_config = config_manager.get("web_ui")
if not isinstance(web_ui_config, dict):
    web_ui_config = {}
```

行为边界：

- `AI_INTERVENTION_AGENT_LOG_LEVEL` 仍优先于 config；
- 缺失 `web_ui`、`None`、非 dict section 仍回退到 `WARNING`；
- 有效/无效 `web_ui.log_level` 的返回与 warning 语义不变；
- 配置读取异常仍由外层 exception fallback 降级到 `WARNING`。

新增 runtime 测试覆盖缺失 `web_ui` section，并断言
`config_manager.get()` 只以 `"web_ui"` 一个参数调用，防止 eager `{}` default 回归。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.35 R492 · ConfigManager.get_section raw section fallback 惰性化

`ConfigManager.get_section()` 是 `web_ui` / `notification` / `feedback` /
`mdns` 等 validated config section 的共享缓存入口。旧实现：

```python
raw = self.get(section, {})
```

即使 section 存在且 cache miss 后会进入 Pydantic 校验，也会先构造 unused `{}`。
R492 改成：

```python
raw = self.get(section)
result = self._validate_section(section, raw)
```

并复用 `_validate_section()` 既有的非 dict 归一化：

```python
if not isinstance(raw, dict):
    raw = {}
```

行为边界：

- 已存在 dict section 的 Pydantic validate / `model_dump()` 语义不变；
- missing section 从 `self.get(..., {}) -> {}` 变成 `self.get(...) -> None`，
  再由 `_validate_section()` 归一化为 `{}`，最终返回不变；
- explicit `None` / 非 dict section 仍归一化为 `{}`；
- cache hit、cache miss 计数、TTL、network_security 特殊路径不变。

新增 runtime spy 测试覆盖 missing section：返回仍为 `{}`，并断言
`ConfigManager.get()` 只以 section 名调用，不再传 eager `{}` default。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.36 R493 · JSONC→TOML mDNS migration fallback 惰性化

`ConfigManager._migrate_jsonc_to_toml()` 兼容旧 JSON/JSONC 配置迁移到 TOML。
旧实现：

```python
mdns = config_data.get("mdns", {})
if isinstance(mdns, dict) and mdns.get("enabled") is None:
    mdns["enabled"] = "auto"
```

即使旧配置存在 `mdns` section，也会为 `dict.get()` 预先构造 unused `{}`。
R493 改成：

```python
mdns = config_data.get("mdns")
if isinstance(mdns, dict) and mdns.get("enabled") is None:
    mdns["enabled"] = "auto"
```

行为边界：

- `{"mdns": {"enabled": null}}` 仍迁移为 `enabled = "auto"`；
- `{"mdns": {"enabled": true}}` 仍保留 `true`；
- 缺失 `mdns` 时旧代码只会修改一个未插回 `config_data` 的临时 `{}`，
  因此有效输出不变；
- template merge、`.bak` 写入、显式路径跳过 auto-migrate 行为不变。

新增 source invariant 锁定 migration lookup 不再使用
`config_data.get("mdns", {})`；继续跑完整 JSONC→TOML migration 测试组覆盖运行时边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.37 R494 · backup restore config fallback 惰性化

`IOOperationsMixin.restore_config()` 恢复 `backup_config()` 导出的包装格式时，旧实现：

```python
if "config" in backup_data:
    actual_config = backup_data.get("config", {})
```

该分支已经先确认 `"config" in backup_data`，因此 `{}` default 只会在调用前被
eager 构造，实际不会用于 missing-key fallback。R494 改成：

```python
actual_config = backup_data.get("config")
```

行为边界：

- `config` 为 dict 时仍恢复包装内配置；
- `config` 为非 dict / `None` 时仍返回 `False` 并记录错误；
- 裸 dict 备份仍走 raw restore 分支；
- 顶层 `network_security` 合并恢复、TOML/JSON 写盘、atomic replace、reload 行为不变。

新增 source invariant 锁定 restore path 不再使用
`backup_data.get("config", {})`；继续跑 restore 相关测试覆盖坏 JSON、非 dict 备份、
非 dict config、裸 dict、network_security、roundtrip 和通用异常路径。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.38 R495 · --print-config web_ui section fallback 惰性化

`server._print_effective_config()` 为 `ai-intervention-agent --print-config`
生成可机器解析的 effective config。旧实现：

```python
web_ui_section = (
    dict(all_config.get("web_ui", {}))
    if isinstance(all_config.get("web_ui"), dict)
    else {}
)
```

这里既会 eager 构造 `{}` default，也会重复读取 `all_config["web_ui"]`。R495 改成：

```python
web_ui_raw = all_config.get("web_ui")
web_ui_section = dict(web_ui_raw) if isinstance(web_ui_raw, dict) else {}
```

行为边界：

- `web_ui` 为 dict 时仍复制一份后叠加 effective runtime config；
- 缺失 / 非 dict `web_ui` 仍降级为空 dict；
- `sections` 仍包含所有非敏感 dict section；
- `network_security` 过滤、env override 输出、失败时 JSON error 输出不变。

新增 source invariant 锁定 `--print-config` 不再使用
`all_config.get("web_ui", {})`；继续跑完整 `test_server_print_config.py`
覆盖 output shape、env override、redaction、network_security 不泄漏和失败 JSON。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.39 R496 · Web UI CLI result list fallback 惰性化

`web_ui.py` 的 `python -m ai_intervention_agent.web_ui` CLI 分支在展示反馈结果时，
旧实现：

```python
selected_options = result.get("selected_options", [])
images = result.get("images", [])
```

会为两个 result 字段各自 eager 构造 unused `[]`。R496 改成先 raw read，再按
list 类型归一化：

```python
selected_options = result.get("selected_options")
if not isinstance(selected_options, list):
    selected_options = []
images = result.get("images")
if not isinstance(images, list):
    images = []
```

行为边界：

- 正常 list result 仍打印选项和图片数量；
- 缺失 / `None` / 非 list result 字段降级为空列表；
- `user_input`、`web_feedback_ui()` 调用参数、`sys.exit(0)` 行为不变。

新增 source invariant 锁定 CLI branch 不再使用
`result.get("selected_options", [])` / `result.get("images", [])`；同时跑
`web_feedback_ui()` helper 相关测试确认返回/写文件行为不变。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.40 R497 · web_ui_security allowed_networks fallback 常量化

AST 级扫描发现 regex 漏掉的 multiline fallback：

```python
allowed_networks = cfg.get("allowed_networks", ["127.0.0.0/8", "::1/128"])
```

该路径位于 `SecurityMixin._is_ip_allowed()`，是每次请求 Host/IP 访问控制会走到的
安全 hot path。R497 改成模块级不可变默认值：

```python
_DEFAULT_ALLOWED_NETWORKS: tuple[str, ...] = ("127.0.0.0/8", "::1/128")
allowed_networks = cfg.get("allowed_networks", _DEFAULT_ALLOWED_NETWORKS)
```

行为边界：

- 缺失 `allowed_networks` 时仍允许 loopback IPv4 / IPv6；
- 显式 `None` / 非 iterable 的旧 fail-closed 行为不变；
- 显式 string / list / tuple 的迭代语义不变；
- blocked IPs、access-control disabled short-circuit、invalid client IP fallback 不变。

新增 runtime 测试覆盖缺失 `allowed_networks` 仍允许 `127.0.0.1`，并用 source
invariant 锁定不再使用 literal list default。最终 AST 扫描确认 production
Python 中无 `dict.get(..., []/{})` / `getattr(..., []/{})` / `setdefault(...)`
残留。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round27/02-python-call-evaluation-exa.json`
  通过 Exa 保存官方 Python docs 片段，其中 calls 章节说明 all argument
  expressions are evaluated before the call is attempted。

### 3.41 R498 · VS Code webview tab countdown shared ticker

继 R460 把 Flask Web UI 的任务倒计时从 N 个 per-task interval 收敛为一个
共享 1Hz ticker 后，VS Code webview 仍保留等价的 per-task timer：

```javascript
tabCountdownTimers[taskId] = setInterval(update, 1000)
```

并发任务数为 N 时，webview 会产生 N 个 1Hz callback。即使 deadline 已使用绝对
时间避免后台节流导致倒计时漂移，多余 callback 仍会在 webview 生命周期内持续做
DOM 查询和状态更新。R498 将 `tabCountdownTimers` 改为 task_id -> countdown state
注册表，并新增一个页面级 `tabCountdownTickerTimer`：

- `startTabCountdown()` 只注册/刷新 task state，立即 `tickTabCountdown(taskId)`
  同步首帧，然后调用 `ensureSharedTabCountdownTicker()`；
- `ensureSharedTabCountdownTicker()` 是唯一创建
  `setInterval(tickAllTabCountdowns, 1000)` 的入口；
- `tickAllTabCountdowns()` 遍历 `tabCountdownTimers`，对每个任务调用
  `tickTabCountdown()`；
- 单个任务到期后删除自己的 state 和 cached remaining，并在 registry 为空时
  停掉共享 ticker；
- `clearAllTabCountdowns()` 清空所有 task state，并清理共享 ticker；为旧测试和
  旧运行态残留的 numeric interval id 保留 legacy cleanup。

新增 `tests/test_vscode_tab_countdown_shared_ticker_r498.py` 锁定 source invariant：
`startTabCountdown()` 内不再出现 `setInterval`，唯一 tab countdown interval 位于
`ensureSharedTabCountdownTicker()`，清理路径在 registry 为空时释放共享 ticker。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round10/01-js-timer-visibility.json`
- `/tmp/smart-search-evidence/aiia-optimization-round10/02-chrome-timer-throttling.json`

### 3.42 R499 · VS Code webview tab countdown DOM ref cache

R498 已把 VS Code webview 的 tab countdown 从 N 个 interval 收敛为一个共享
1Hz ticker，但 `tickTabCountdown()` 内仍然每个 task、每秒执行 3 次 DOM lookup：

```javascript
document.getElementById('tab-countdown-progress-' + taskId)
document.getElementById('tab-countdown-text-' + taskId)
document.getElementById('tab-countdown-' + taskId)
```

这与 Flask Web UI 侧 R266 修复前的问题同构：N 个并发 task 时是 3N 次 DOM
lookup / 秒。R499 新增 `_getOrCacheTabCountdownDom(taskId, state)`：

- DOM refs 挂在每个 countdown state 的 `state._domCache` 上，task 删除时自然释放；
- cache 命中时直接复用 `progressCircle` / `numberSpan` / `countdownRing`；
- 使用 `document.contains(cache.progressCircle)` 检测 stale ref，覆盖 task tab
  重建、任务完成后 DOM 被替换、webview 局部刷新等边界；
- `startTabCountdown()` 和 `tickTabCountdown()` 都经由 helper，不再 inline
  `getElementById()`；
- 元素缺失时仍不注册/不更新倒计时，保持原 null-safe 行为。

新增 `tests/test_vscode_tab_countdown_dom_cache_r499.py`：

- source invariant 锁定 helper、`document.contains` stale detection、三个 cached
  refs 和 hot path 不再 inline DOM lookup；
- Node runtime harness 启动一个 countdown 后断言首帧只有 3 次 lookup，warm tick
  不新增 lookup，模拟 stale 后才重新 lookup 3 次并刷新 cache。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round28/01-mdn-getelementbyid.json`
  记录 MDN：`getElementById()` 返回匹配 ID 的 Element 或 `null`，且未插入
  document tree 的元素不会被搜索到；
- `/tmp/smart-search-evidence/aiia-optimization-round28/02-mdn-node-contains.json`
  记录 MDN：`Node.contains()` 返回某节点是否包含目标节点，可用于判断 cached
  ref 是否仍在当前 document tree 中。

### 3.43 R500 · VS Code webview tab countdown hidden DOM 写入跳过

R498/R499 已经把 VS Code webview 的 tab countdown 收敛为共享 ticker，并缓存
DOM refs；但 `tickTabCountdown()` 仍在 hidden webview 中执行 DOM render。这个
路径与 Flask Web UI 侧 R128 的 hidden-tab 优化同构：页面不可见时，倒计时逻辑
仍应按 deadline / cached remaining 推进，但 SVG stroke、数字文本和 title 写入
没有用户可见收益。

R500 将 `tickTabCountdown()` 拆成三层：

- `computeTabCountdownRemaining(taskId, state)`：只计算 deadline / remaining；
- `tickTabCountdown()`：每秒更新 `tabCountdownRemaining` 和 non-deadline fallback
  的 `state.remaining`，到期时继续删除 state 并清理 idle ticker；
- `renderTabCountdown()`：只在 `document.hidden === false` 时通过 R499 DOM cache
  写 SVG/text/title。

同时新增 `forceUpdateAllTabCountdowns()` 与
`installTabCountdownVisibilitySyncHandlerOnce()`：

- hidden tick 不做 DOM lookup / write，但仍更新 cached remaining；
- `visibilitychange` visible 边沿强刷当前 UI，避免切回后最多等 1 秒才看到新数字；
- force update 只 render 当前 computed remaining，不递减 non-deadline fallback，
  避免 visible 边沿把倒计时额外吃掉 1 秒；
- listener 用 `tabCountdownVisibilityHandlerInstalled` 幂等守护，避免每个任务
  start 时重复安装。

新增 `tests/test_vscode_tab_countdown_hidden_dom_r500.py`：

- source invariant 锁定 compute 在 hidden guard 之前、render 在 hidden guard 之后；
- source invariant 锁定 visibility handler 幂等安装和 visible-edge force update；
- Node runtime harness 验证 hidden tick 的 DOM lookup/write 都是 0，但
  `tabCountdownRemaining` / `state.remaining` 正常推进；visible force update 后
  才产生 3 次 lookup + 1 次 SVG attribute write，并且没有额外递减。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round10/01-js-timer-visibility.json`
  记录 MDN Page Visibility API：页面不可见时应避免执行不必要任务；
- `/tmp/smart-search-evidence/aiia-optimization-round10/02-chrome-timer-throttling.json`
  记录 Chrome timer throttling：hidden pages 中 chained timers 会被批处理/节流，
  减少 hidden tick 内部工作量可降低后台调度成本。

### 3.44 R501 · SSE oversize UTF-8 byte-size fast path

`_SSEBus.emit()` 的 R58 oversize guard 需要按 UTF-8 byte size 判断单条 SSE
payload 是否超过 256 KiB。旧路径对每条成功预序列化的事件都执行：

```python
len(serialized_data.encode("utf-8"))
```

这会为常规小事件分配一份临时 `bytes`，即使它们距离阈值非常远。R501 新增
`_sse_serialized_utf8_exceeds_limit(serialized, limit)`：

- 先用 `len(serialized) * 4 <= limit` 做上界证明；UTF-8 单个 Unicode code
  point 最多 4 bytes，因此该条件为真时一定不超限；
- 只有靠近阈值时才执行 `serialized.encode("utf-8")`，拿到精确 byte size；
- `oversize_drop.data.size_bytes` 仍只在真实超限路径使用精确 byte size，非 ASCII
  payload 的告警 metadata 不变；
- 序列化失败的 payload 仍保留原 fallback，不会被误归类为 oversize。

新增 `tests/test_sse_oversize_utf8_fastpath_r501.py` 锁定 source invariant 和边界
行为：`emit()` 不再 inline `serialized_data.encode("utf-8")`，helper 保留 4-byte
上界 fast path；ASCII / 非 ASCII 的阈值边界仍按精确 UTF-8 byte size 判定；非
ASCII oversize 事件的 `size_bytes` metadata 与 `len(serialized.encode("utf-8"))`
一致。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round29/01-python-unicode-utf8.json`
  记录 Python Unicode HOWTO：UTF-8 对 `<128` 的 code point 用 1 byte，对其他
  code point 用 2、3 或 4 bytes；
- `/tmp/smart-search-evidence/aiia-optimization-round29/02-python-str-encode.json`
  记录 Python codecs 文档：text encoding 会把 `str` 转换为 `bytes`，因此在热路径
  上应避免不必要的 encode 分配。

### 3.45 R502 · SSE oversize ASCII exact-size fast path

R501 用 `len(serialized) * 4 <= limit` 避免了常规小 SSE payload 的 UTF-8
`bytes` 分配；但靠近阈值的 ASCII payload 仍会走：

```python
len(serialized.encode("utf-8"))
```

对于 ASCII 字符串，UTF-8 byte size 与 `len(serialized)` 完全相同，因此无需
分配临时 `bytes`。R502 在 R501 helper 的 near-threshold 分支中增加：

```python
if serialized.isascii():
    return char_count > limit, char_count
```

边界保持：

- 小 payload 仍先走 R501 的 `char_count * 4 <= limit` 上界 fast path，不多扫；
- ASCII payload 无论低于还是高于 limit，都用 `len(serialized)` 作为精确 byte size；
- 非 ASCII payload 仍回退到 `serialized.encode("utf-8")`，保证
  `oversize_drop.data.size_bytes` 精确；
- `emit()` 的 event id、fan-out、history、`_oversize_drops` 计数语义不变。

新增 `tests/test_sse_oversize_ascii_fastpath_r502.py` 锁定 `serialized.isascii()`
位于 encode 之前，并覆盖 ASCII under/over limit、非 ASCII exact fallback、以及
ASCII oversize metadata 仍等于 `len(serialized)`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round30/01-python-str-isascii.json`
  保存 docs.python.org official-domain 搜索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round30/03-python-str-isascii-curl-snippet.txt`
  记录 Python 官方 `str.isascii()` 文档片段：字符串为空或所有字符为 ASCII 时返回
  `True`，ASCII code points 范围为 U+0000-U+007F。

### 3.46 R503 · TaskQueue prompt size guard UTF-8 fast path

`TaskQueue.add_task()` 的 R53-A guard 在拿写锁前检查 prompt UTF-8 byte size：

```python
len(prompt.encode("utf-8", errors="replace"))
```

这条防护很重要：超过 6 MB warning，超过 10 MB reject，避免巨型 prompt 进入
`Task()` 构造、持久化和 SSE/IPC 路径。但正常 prompt 远低于 6 MB，旧路径仍会为每次
`add_task()` 分配一份临时 `bytes`，只为了证明不超过阈值。

R503 新增 `_prompt_utf8_size_for_guard(prompt)`：

- `len(prompt) * 4 <= _PROMPT_WARN_BYTES` 时直接返回 `len(prompt)`；UTF-8 单个
  code point 最多 4 bytes，因此该 prompt 不可能触发 warn/reject；
- near-threshold ASCII prompt 走 `prompt.isascii()`，`len(prompt)` 就是精确
  UTF-8 byte size；
- near-threshold 非 ASCII prompt 仍执行
  `prompt.encode("utf-8", errors="replace")`，保持 warning/rejection 日志里的
  MB 数精确；
- 非 str caller 仍被 `add_task()` 原有 try/except 兜住，后续由 Task/Pydantic
  校验处理，R53-A size gate 不提前崩。

新增 `tests/test_task_queue_prompt_size_fastpath_r503.py`：

- source invariant 锁定 `add_task()` 不再 inline prompt encode，helper 使用 4-byte
  upper bound 且 `isascii()` 位于 encode 前；
- patched small thresholds 覆盖 small non-ASCII no-warn fast path、ASCII exact path、
  non-ASCII exact fallback、warn path 和 reject path；
- 继续跑 R53-A/R315 既有测试，确认 6 MB / 10 MB 真实阈值、UTF-8 多字节计数和
  perf-baseline constants 不变。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round29/01-python-unicode-utf8.json`
  记录 Python Unicode HOWTO：UTF-8 对 `<128` 的 code point 用 1 byte，对其他
  code point 用 2、3 或 4 bytes；
- `/tmp/smart-search-evidence/aiia-optimization-round30/03-python-str-isascii-curl-snippet.txt`
  记录 Python 官方 `str.isascii()` 文档片段：ASCII code points 范围为
  U+0000-U+007F。

### 3.47 R504 · Notification inflight persistence timestamp single snapshot

`NotificationManager._persist_inflight_unlocked()` 写
`notification_inflight.json` 时旧路径会取多个 wall-clock snapshot：

```python
"saved_at": datetime.now(UTC).isoformat()
"saved_at_ts": time.time()
```

而且 `saved_at_ts` 位于 events list comprehension 内，N 个 inflight events 就会调用
N 次 `time.time()`。这些 timestamp 属于同一次 atomic persistence write，语义上应
共享同一快照；多个 clock read 既多做 syscall/时间转换，也可能让 envelope
`saved_at` 与 event `saved_at_ts` 出现毫秒级漂移。

R504 改为：

- 进入非空持久化路径后捕获一次 `saved_at_ts = time.time()`；
- 用 `datetime.fromtimestamp(saved_at_ts, UTC).isoformat()` 派生 envelope
  `saved_at`；
- 所有 event 的 `saved_at_ts` 复用同一个 float；
- 空集合删除文件、atomic `.tmp -> os.replace`、TTL load 逻辑和 schema version 均不变。

新增 `tests/test_notification_inflight_persist_snapshot_r504.py`：

- source invariant 锁定 `_persist_inflight_unlocked()` 内只有一次 `time.time()`，
  且不再调用 `datetime.now(UTC).isoformat()`；
- runtime test patch `time.time()` 为固定值，写入两条 event，断言 envelope
  `saved_at` 等于 `datetime.fromtimestamp(saved_at_ts, UTC).isoformat()`，且两个
  event 的 `saved_at_ts` 完全相同。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round31/01-python-datetime-fromtimestamp-curl-snippet.txt`
  记录 Python 官方 `datetime.fromtimestamp(timestamp, tz)` 文档：它返回与 POSIX
  timestamp 对应的 datetime；官方推荐用 `datetime.fromtimestamp(timestamp,
  tz=timezone.utc)` 创建 UTC aware datetime。

### 3.48 R505 · Notification enqueue timestamp single snapshot

`NotificationManager.send_notification()` 创建事件时旧路径读取两次 wall clock：

```python
event_id = f"notification_{int(time.time() * 1000)}_..."
self._stats["last_event_at"] = time.time()
```

这两个值描述的是同一次 enqueue/create 事件。分开读取会多一次 wall-clock call，
同时让 event id 前缀中的毫秒时间与 stats 中的 `last_event_at` 可能出现微小漂移。

R505 改为：

- 在通过 enabled/shutdown guard 后捕获一次 `created_at_ts = time.time()`；
- event id 继续保持 `notification_<millis>_<uuid8>` 格式，但 `<millis>` 来自
  `created_at_ts`；
- `self._stats["last_event_at"]` 复用同一个 `created_at_ts`；
- stats 异常隔离、queue append、inflight persistence、immediate/delayed dispatch
  行为不变。

新增 `tests/test_notification_enqueue_timestamp_snapshot_r505.py`：

- source invariant 锁定 `send_notification()` 使用 `created_at_ts` 生成 id 并写
  `last_event_at`，不再直接把 `last_event_at` 设为 `time.time()`；
- runtime test patch `time.time()` 为固定值，并 mock inflight/process side effects，
  断言只调用一次 wall clock，event id 的毫秒前缀和 `last_event_at` 来自同一快照。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round32/01-python-time-time-curl-snippet.txt`
  记录 Python 官方 `time.time()` 文档：返回 seconds since epoch 的浮点数；同页
  说明其底层可能调用 `clock_gettime(CLOCK_REALTIME)` 或 `gettimeofday()`。

### 3.49 R506 · Notification inflight persistence compact JSON

`NotificationManager._persist_inflight_unlocked()` 写
`notification_inflight.json` 时旧路径使用：

```python
json.dumps(payload, ensure_ascii=False, indent=2)
```

这是机器恢复状态文件，不是用户编辑配置。每次通知进入/离开 inflight 都会触发写盘；
pretty-print 会额外生成换行和缩进空格，增加序列化输出长度、临时字符串大小和原子写入
字节数。

R506 改为：

- 新增 `_COMPACT_JSON_SEPARATORS = (",", ":")`；
- 保留 `ensure_ascii=False`，避免改变非 ASCII 内容的存盘行为；
- `json.dumps(..., separators=_COMPACT_JSON_SEPARATORS)` 输出 compact JSON；
- schema_version、saved_at、events、atomic `.tmp` + `os.replace` 行为不变。

新增 `tests/test_notification_inflight_compact_json_r506.py`：

- source invariant 锁定 `_persist_inflight_unlocked()` 使用 compact separators，
  不再使用 `indent=2`；
- runtime test 写入两条 inflight event，断言文件仍可 `json.loads()`，原始内容
  等于 compact dumps、短于旧 pretty dumps、无格式化换行/冒号空格，并保留
  `ensure_ascii=False` 的中文原文。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round33/02-python-json-dumps-exa.json`
  记录 Python 官方 `json` 文档：`indent=None` 选择最紧凑表示；要获得最紧凑
  JSON representation，应指定 `separators=(",", ":")` 来消除空白。
- `/tmp/smart-search-evidence/aiia-optimization-round33/01-python-json-docs.json`
  记录本轮 `smart-search fetch` 对 Python docs 的提取失败详情；因此采用 Exa
  官方域名检索结果作为可复现证据。

### 3.50 R507 · SSE empty payload serialization fast path

`_SSEBus.emit()` 旧路径无论 payload 是否为空，都会先走：

```python
json.dumps(data or {}, ensure_ascii=False)
```

SSE 的 `None` / `{}` payload 按历史契约都归一化为 `{}`，对应 wire data 恒为
`"{}"`。这类事件没有必要进入通用 JSON encoder，也不需要走 circular check /
dict walker。R507 抽出 `_serialize_sse_payload(data)`：

- `payload_data = data or {}` 保留旧的 falsy payload → `{}` 语义；
- 空 payload 直接返回 `_SSE_EMPTY_JSON = "{}"`；
- 非空 payload 仍调用 `json.dumps(..., ensure_ascii=False)`；
- 非 JSON-serializable 的非空 payload 仍返回 `_serialized=None`，让 generator
  保留原有 on-demand fallback 语义。

新增 `tests/test_sse_empty_payload_fastpath_r507.py`：

- source invariant 锁定 `_SSEBus.emit()` 通过 `_serialize_sse_payload()` 获取
  normalized data 和 `_serialized`；
- runtime test patch `json.dumps` 为抛错，断言 `emit(..., None)` 和
  `emit(..., {})` 仍成功写入 `data={}` / `_serialized="{}"`；
- 非空中文 payload 仍走 `json.dumps(..., ensure_ascii=False)`，确保 i18n wire
  contract 不变；
- circular 非空 payload 仍返回 `_serialized=None`，保留坏数据防御边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round34/01-python-json-dumps-official.json`
  记录 Python 官方 `json` 文档：`json.dumps(obj)` 会将对象序列化为 JSON
  formatted `str`，`dump()` / `dumps()` 支持 `ensure_ascii`、circular check、
  separators 等通用编码逻辑；对固定空对象输出直接使用 `"{}"` 可绕开这条通用
  encoder 路径。

### 3.51 R508 · TaskQueue persistence compact JSON

`TaskQueue._persist()` 写 `data/tasks.json` 时旧路径使用：

```python
json.dump(data, f, ensure_ascii=False, indent=2)
```

这个文件是任务队列重启恢复用的 machine-state snapshot，每次 add / status 更新 /
hot reload 配置写回都可能触发，并且写入后会 `flush()` + `os.fsync()` + `os.replace()`。
pretty-print 会额外写入换行和缩进空白，增加 JSON encoder 输出、stdio buffer、
page cache 和 fsync 需要落盘的字节数。

R508 改为：

- 新增 `_COMPACT_JSON_SEPARATORS = (",", ":")`；
- 保留 `ensure_ascii=False`，不改变中文 prompt / options 的磁盘表示；
- `json.dump(..., separators=_COMPACT_JSON_SEPARATORS)` 输出 compact JSON；
- version、active_task_id、tasks、saved_at、atomic tmpfile、flush/fsync/replace
  契约不变。

新增 `tests/test_task_queue_persist_compact_json_r508.py`：

- source invariant 锁定 `_persist()` 使用 compact separators，不再用 `indent=2`；
- runtime test 通过真实 `TaskQueue(persist_path=...)` 写入中文任务，断言原始文件
  等于 compact dumps、短于旧 pretty dumps、无格式化换行/冒号空格；
- 再实例化一个 `TaskQueue` 从同一 compact 文件恢复，断言任务和中文 prompt
  正常恢复，覆盖向后读取边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round35/01-python-json-dump-compact-official.json`
  记录 Python 官方 `json.dump` 文档：`indent` 会 pretty-print；`indent=None`
  选择最紧凑表示；要获得最紧凑 JSON representation，应指定
  `separators=(",", ":")` 消除空白。

### 3.52 R509 · TaskQueue empty snapshot unlink fast path

`TaskQueue._persist()` 只把未完成任务写入 `data/tasks.json`。旧路径即使没有任何
可恢复任务，也会继续构造：

```python
{"version": 1, "active_task_id": None, "tasks": [], "saved_at": "..."}
```

然后执行 compact JSON dump、`flush()`、`fsync()` 和 `os.replace()`。这会在最后
一个 pending/active 任务被完成或删除后，写入一个恢复时只会解析为空队列的空快照。

R509 改为：

- `_persist()` 在 read-lock snapshot 完成后检查 `if not snapshot:`；
- 空 snapshot 直接 `self._persist_path.unlink(missing_ok=True)` 并返回；
- 因此空队列 / 仅 completed 任务内存残留时，不再生成 JSON、不创建 tmpfile、不
  flush/fsync/replace；
- 重启恢复语义不变：无 `tasks.json` 与 `tasks=[]` 都恢复为空队列；损坏文件
  quarantine 路径不变，因为只有成功解析后的空快照才会被删除。

新增 `tests/test_task_queue_persist_empty_snapshot_unlink_r509.py`：

- source invariant 锁定 `if not snapshot:` 和 `unlink(missing_ok=True)` 位于
  `json.dump(` 之前；
- runtime test 覆盖完成最后一个 recoverable task 后删除持久化文件，并用新
  `TaskQueue(persist_path=...)` 验证恢复为空；
- runtime test 覆盖 remove 最后一个任务后删除持久化文件，同样验证恢复为空。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round36/01-python-path-unlink-official.json`
  记录 Python 官方 `pathlib.Path.unlink(missing_ok=False)` 文档：该方法移除文件
  或符号链接；`missing_ok=True` 时路径不存在会忽略 `FileNotFoundError`，等价
  POSIX `rm -f` 行为。

### 3.53 R510 · Notification inflight empty unlink 去 exists probe

`NotificationManager._persist_inflight_unlocked()` 在 in-flight id 集合为空时会删除
`notification_inflight.json`，避免磁盘长期保留空 envelope。旧实现先做：

```python
if path.exists():
    path.unlink()
```

这条路径通常发生在最后一条 in-flight notification finalize 后；如果文件存在，会先
做一次存在性检查再 unlink；如果文件不存在，也仍要做一次 probe 才返回。R510 改为：

```python
path.unlink(missing_ok=True)
```

并保留外层 `except OSError` 的 best-effort 语义。这样：

- 空集合路径少一次 `Path.exists()` / stat 类文件系统查询；
- 文件存在时仍删除；
- 文件缺失时仍静默 no-op；
- 目录 / 权限错误等 `OSError` 仍被吞掉，不影响通知主流程；
- 非空集合的 compact JSON、timestamp snapshot、atomic replace 契约不变。

新增 `tests/test_notification_inflight_empty_unlink_r510.py`：

- source invariant 锁定 empty branch 使用 `path.unlink(missing_ok=True)`，且
  `_persist_inflight_unlocked()` 不再出现 `path.exists()`；
- runtime test 覆盖空集合删除已有文件；
- runtime test patch `Path.exists` 为抛异常，验证缺文件 empty fast path 不再
  probe exists。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round37/01-python-path-unlink-official.json`
  保存 docs.python.org official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round37/03-python-path-unlink-curl-snippet.html`
  记录 Python 官方 `Path.unlink(missing_ok=False)` 片段：`missing_ok=True` 时
  `FileNotFoundError` 会被忽略，行为等同 POSIX `rm -f`。

### 3.54 R511 · Notification inflight restore 去 exists probe

`NotificationManager._load_persisted_inflight_events()` 启动时读取
`notification_inflight.json`，旧路径先做：

```python
if not path.exists():
    return []
data = json.loads(path.read_text(encoding="utf-8"))
```

这会在每次通知管理器初始化时对缺文件或存在文件路径都先做一次存在性查询；文件存在
时紧接着还要再次打开读取。R511 改成直接读取：

```python
try:
    raw = path.read_text(encoding="utf-8")
except FileNotFoundError:
    return []
except OSError as exc:
    logger.warning(...)
    return []
data = json.loads(raw)
```

行为边界：

- 缺文件仍返回 `[]`，并且保持 silent，不污染启动日志；
- 文件存在时少一次 `Path.exists()` / stat 类查询；
- 文件在检查与读取之间消失的 TOCTOU race 变成正常缺文件路径，而不是误报损坏；
- 权限错误、I/O 错误、JSON 损坏仍返回 `[]` 并 warning；
- schema_version、TTL、events list/dict 过滤逻辑不变。

新增 `tests/test_notification_inflight_load_no_exists_r511.py`：

- source invariant 锁定 `_load_persisted_inflight_events()` 直接
  `path.read_text(...)`，显式处理 `FileNotFoundError`，且不再出现
  `path.exists()`；
- runtime test patch `Path.exists` 为抛异常，验证缺文件 restore load 不再 probe
  exists 且不 warning；
- runtime test 覆盖有效文件仍恢复 fresh event；
- runtime test 覆盖非缺文件 `OSError` 仍 warning 并返回空列表。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round38/01-python-path-read-text-official.json`
  保存 docs.python.org official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round38/02-pathlib-concrete-methods-oserror-snippet.html`
  记录 Python 官方 pathlib 文档：部分 concrete path 方法在系统调用失败时会
  raise `OSError`，例如路径不存在；
- `/tmp/smart-search-evidence/aiia-optimization-round38/03-pathlib-read-text-snippet.html`
  记录 `Path.read_text()` 会返回目标文件解码内容，并打开后关闭文件；
- `/tmp/smart-search-evidence/aiia-optimization-round38/04-pathlib-exists-snippet.html`
  记录 `Path.exists()` 是独立的存在性查询，路径缺失时返回 `False`。

### 3.55 R512 · TaskQueue restore 去 exists probe

`TaskQueue._restore()` 启动时读取 `data/tasks.json`。旧路径先做：

```python
if not self._persist_path or not self._persist_path.exists():
    return
raw = self._persist_path.read_text(encoding="utf-8")
```

这会让每次队列初始化先做一次存在性查询；文件存在时紧接着还要打开读取。R512 改为
EAFP 风格的直接读取：

```python
if not self._persist_path:
    return
try:
    raw = self._persist_path.read_text(encoding="utf-8")
except FileNotFoundError:
    return
except Exception as e:
    logger.warning(...)
    self._quarantine_corrupt_persist_file(reason=str(e))
    return
```

行为边界：

- 缺 `tasks.json` 仍静默恢复为空队列；
- 文件存在时少一次 `Path.exists()` / stat 类查询；
- 文件在 `exists()` 与 `read_text()` 之间消失的 TOCTOU race 消失，直接走正常缺文件
  empty-state；
- 权限错误 / I/O 错误仍 warning 并触发 corrupt persist quarantine；
- JSON 截断、schema mismatch、per-item 容错、restore 单 wall-clock snapshot、compact
  JSON 读取兼容性均不变。

新增 `tests/test_task_queue_restore_no_exists_r512.py`：

- source invariant 锁定 `_restore()` 直接
  `self._persist_path.read_text(encoding="utf-8")`，显式处理
  `FileNotFoundError`，且 `_restore()` 内不再出现 `.exists()`；
- runtime test patch `Path.exists` 为抛异常，验证缺文件 restore 不再 probe exists，
  且不会 quarantine；
- runtime test 覆盖有效文件仍恢复 active task；
- runtime test 覆盖非缺文件 read error 仍调用 quarantine 并恢复为空队列。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round39/01-python-path-read-text-official.json`
  保存 docs.python.org official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round39/02-python-eafp-official.json`
  保存 Python glossary official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round39/03-pathlib-concrete-methods-oserror-snippet.html`
  记录 pathlib concrete path 方法在系统调用失败时可 raise `OSError`；
- `/tmp/smart-search-evidence/aiia-optimization-round39/04-pathlib-read-text-snippet.html`
  记录 `Path.read_text()` 返回目标文件解码内容，并打开后关闭文件；
- `/tmp/smart-search-evidence/aiia-optimization-round39/05-pathlib-exists-snippet.html`
  记录 `Path.exists()` 是独立的存在性查询；
- `/tmp/smart-search-evidence/aiia-optimization-round39/06-python-eafp-lbyl-snippet.html`
  记录 Python glossary：EAFP 是 “clean and fast” 的 try/except 风格，LBYL 在并发
  环境里可能在 “looking” 与 “leaping” 之间引入 race。

### 3.56 R513 · Notification inflight persist 去中间 events list

`NotificationManager._persist_inflight_unlocked()` 写非空 inflight 文件时，旧路径先
从 `_event_queue` 过滤出一个临时列表：

```python
events_to_save = [e for e in self._event_queue if e.id in ids]
...
"events": [
    {...}
    for e in events_to_save
]
```

这个中间 list 只被消费一次；真正必须保留的是 JSON payload 里的 `events` list。R513
改成在构造 payload events 时直接过滤 `_event_queue`：

```python
"events": [
    {
        **e.model_dump(mode="json"),
        "saved_at_ts": saved_at_ts,
    }
    for e in self._event_queue
    if e.id in ids
]
```

行为边界：

- payload `events` 仍按 `_event_queue` 顺序输出；
- `_inflight_persisted_ids` 中已经不在队列里的 stale id 仍不会落盘；
- 非 inflight 队列事件仍被过滤；
- `saved_at` / `saved_at_ts` 仍复用 R504 的单次 `time.time()` snapshot；
- R506 紧凑 JSON、schema_version、原子 replace 写入路径不变。

新增 `tests/test_notification_inflight_no_intermediate_list_r513.py`：

- source invariant 锁定 `_persist_inflight_unlocked()` 不再出现 `events_to_save`；
- runtime test 验证 stale event / missing id 过滤、队列顺序、schema_version；
- runtime test 验证 compact JSON 兼容性；
- runtime test 验证所有 persisted event 继续共享同一个 `saved_at_ts`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round40/01-python-list-generator-official.json`
  保存 docs.python.org official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round40/02-python-datastructures.html`
  记录 Python tutorial：list comprehensions 用于创建 list，结果是 new list；
- `/tmp/smart-search-evidence/aiia-optimization-round40/03-python-expressions.html`
  记录 Python reference：list display yields a new list object；generator expression
  evaluates to a generator iterator，非 leftmost 表达式按生成器方式 lazy evaluation。

### 3.57 R514 · TaskQueue quarantine 去 exists probe

`TaskQueue._quarantine_corrupt_persist_file()` 是 `_restore()` 发现顶层
`tasks.json` 损坏后的 forensic 保护路径。旧实现先做：

```python
if not self._persist_path or not self._persist_path.exists():
    return
...
os.replace(str(self._persist_path), str(corrupt_path))
```

这会在真正的 rename 前多一次存在性查询；如果文件在 `exists()` 和 `os.replace()`
之间消失，仍要靠后续异常路径兜底。R514 改为直接执行实际操作：

```python
if not self._persist_path:
    return
try:
    ...
    os.replace(str(self._persist_path), str(corrupt_path))
    logger.warning(...)
except FileNotFoundError:
    return
except OSError as quarantine_err:
    logger.warning(...)
```

行为边界：

- 没有 persist path 时仍直接返回；
- quarantine source 已不存在时仍保持静默 no-op；
- 文件存在且可 rename 时仍生成 `<tasks.json>.corrupt-YYYYMMDDTHHMMSSZ`；
- 权限、跨设备、目标占用等非 missing `OSError` 仍 warning 且不向 `_restore()` 传播；
- R17.8 的 forensic 字节保留、文件名格式、后续 `_persist` 不覆盖 quarantine
  副本语义不变。

新增 `tests/test_task_queue_quarantine_no_exists_r514.py`：

- source invariant 锁定 quarantine 方法不再出现 `.exists()`，且显式处理
  `FileNotFoundError`；
- runtime test patch `Path.exists` 为抛异常，验证 missing-source quarantine 不 probe
  exists 且不 warning；
- runtime test 验证已有损坏文件仍被 rename，字节完全保留；
- runtime test 验证 `PermissionError` 仍 warning、不传播、原文件保留。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round41/01-python-os-replace-pathlib-official.json`
  保存 docs.python.org official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round41/02-python-os.html`
  记录 Python `os` 文档：模块函数在 invalid/inaccessible path 或 OS 拒绝时 raise
  `OSError`；`os.replace()` rename source to destination，目标文件可被替换，成功时
  rename 为原子操作；
- `/tmp/smart-search-evidence/aiia-optimization-round41/03-python-pathlib.html`
  记录 `Path.exists()` 返回存在性布尔值，invalid/inaccessible/missing 都会返回
  `False`，并建议用 `Path.stat()` 区分这些情况。

### 3.58 R515 · SSE gap_warning 固定 payload 直写

`_SSEBus.subscribe(after_id=...)` 在客户端的 `Last-Event-ID` 已经被 history
evict 时，会先塞一条 `gap_warning`，提示前端做全量 refetch。这个 warning 的
payload schema 固定：

```python
warning_data = {
    "reason": "history_evicted",
    "after_id": after_id,
}
warning_serialized = json.dumps(warning_data, ensure_ascii=False)
```

`after_id` 来自路由层 `int(...)` 解析并且只有 `> 0` 才传入 subscribe；evicted
分支里是一个正整数。R515 抽出固定格式 formatter：

```python
def _format_sse_gap_warning_payload(after_id: int) -> str:
    return f'{{"reason":"history_evicted","after_id":{after_id}}}'
```

这样断线重连且 history 已 evict 的路径少一次临时 dict 的通用 JSON encoder 遍历；
仍保留 payload dict 给 Python 侧测试 / queue 消费，`_serialized` 直接复用固定字符串。

行为边界：

- `gap_warning` 的 `id=-1` 哨兵不变，不会污染客户端 `lastEventId`；
- `type == "gap_warning"` 不变，三端前端 listener 不需要改；
- `data.reason == "history_evicted"` / `data.after_id == after_id` 不变；
- 当前 history 的 best-effort replay 仍按原顺序跟在 warning 后；
- 非 evicted 的正常 history replay 继续使用 emit 时预序列化好的 `_serialized`。

新增 `tests/test_sse_gap_warning_fastpath_r515.py`：

- formatter 输出 exact compact JSON，并可被 `json.loads` 还原；
- source invariant 锁定 `inject_gap_warning` 分支调用
  `_format_sse_gap_warning_payload(after_id)` 且不再出现 `json.dumps`；
- runtime test 在填满 history 后 patch `json.dumps` 为抛异常，验证 evicted
  subscribe 仍能生成 `gap_warning`；
- runtime test 验证非 evicted replay 仍保留原有预序列化 payload。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round42/01-sse-event-stream-official.json`
  保存 MDN / WHATWG SSE official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round42/02-python-json-dumps-official.json`
  保存 Python `json.dumps` official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round42/03-mdn-sse.html`
  记录 MDN：event stream 是 UTF-8 text；`data` 字段可以是 JSON string，也可以是任意
  string data；
- `/tmp/smart-search-evidence/aiia-optimization-round42/04-python-json.html`
  记录 Python `json.dumps(obj)` 会按 conversion table 把对象序列化为 JSON string；
  compact JSON 需要指定 separators。

### 3.59 R516 · Prometheus label join 去 parts list

`GET /api/system/metrics` 的 Prometheus 文本渲染会频繁调用
`_format_prom_labels(labels)`，旧实现先构造临时列表再 join：

```python
parts = [f'{k}="{_escape_prom_label_value(str(v))}"' for k, v in labels.items()]
return "{" + ",".join(parts) + "}"
```

这个 `parts` list 只被 `",".join(...)` 消费一次。Python `str.join()` 接受任意
字符串 iterable；R516 改为直接 join generator expression：

```python
return "{" + ",".join(
    f'{k}="{_escape_prom_label_value(str(v))}"' for k, v in labels.items()
) + "}"
```

行为边界：

- 空 `labels` / `None` 仍返回空字符串；
- label 顺序仍按 caller 的 dict 插入顺序；
- label value 的反斜杠、双引号、换行 escaping 不变；
- metric family / histogram / SSE by-type / provider metrics 的文本输出格式不变；
- 每个带 label 的 metric sample 少一次 Python list allocation。

新增 `tests/test_prom_labels_generator_r516.py`：

- source invariant 锁定 `_format_prom_labels()` 不再出现 `parts = [` / `join(parts)`；
- runtime test 覆盖 `None` / `{}` 仍输出 `""`；
- runtime test 覆盖多 label 顺序和 Prometheus label value escaping。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round43/01-python-str-join-official.json`
  保存 Python `str.join(iterable)` official-domain 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round43/02-prometheus-exposition-labels-official.json`
  保存 Prometheus exposition format label escaping 检索结果；
- `/tmp/smart-search-evidence/aiia-optimization-round43/03-python-stdtypes.html`
  记录 Python `str.join(iterable)` 返回 iterable 中字符串的拼接结果；
- `/tmp/smart-search-evidence/aiia-optimization-round43/04-prometheus-exposition.html`
  保存 Prometheus exposition format 页面快照，用于复核 label 文本格式和 escaping。

### 3.60 R517 · Prometheus SSE by-type samples 去临时 list

`GET /api/system/metrics` 渲染
`aiia_sse_emit_by_type_total{event_type="..."}` 时，旧路径先构造
`emit_by_type_samples` list：

```python
emit_by_type_samples = [
    ({"event_type": str(et)}, int(count))
    for et, count in sorted(emit_by_type_raw.items())
    if isinstance(count, int | float)
]
if emit_by_type_samples:
    lines.append(_format_prom_metric_family(..., samples=emit_by_type_samples))
```

这个 list 只被 `_format_prom_metric_family()` 遍历一次。R517 把 family
formatter 的输入从 `list[...]` 放宽为任意 `Iterable[...]`，内部用
`iter(samples)` / `next(...)` 判断空 iterable，并先写首个 sample 再继续
消费剩余 iterator。SSE by-type 渲染路径改为直接传 generator expression：

```python
emit_by_type_metrics = _format_prom_metric_family(
    "aiia_sse_emit_by_type_total",
    ...,
    samples=(
        ({"event_type": str(et)}, int(count))
        for et, count in sorted(emit_by_type_raw.items())
        if isinstance(count, int | float)
    ),
)
if emit_by_type_metrics:
    lines.append(emit_by_type_metrics)
```

行为边界：

- 空 sample iterable 仍返回 `""`，因此没有有效 SSE event_type count 时仍不输出
  metric family；
- HELP / TYPE 仍各只输出一次，且仍位于 sample 行之前；
- `sorted(emit_by_type_raw.items())` 的 deterministic event_type 顺序不变；
- label escaping、numeric formatting、`aiia_sse_emit_total` 与
  `aiia_sse_emit_by_type_total` 的并存语义不变；
- 每次 `/api/system/metrics` scrape 的 SSE by-type family 少一次 sample list
  allocation。

新增 `tests/test_prom_metric_family_iterable_r517.py`：

- runtime test 覆盖 `_format_prom_metric_family()` 可消费 one-pass generator；
- runtime test 覆盖空 generator 仍返回空字符串；
- source invariant 锁定 `_render_prometheus_metrics()` 的 SSE by-type 分支不再出现
  `emit_by_type_samples` list，改用 generator 传给 family formatter。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round44/01-python-iterators-official.json`
  保存 Python official-domain 检索结果，包含 `for` statement 会为 iterable 创建
  iterator 并逐项消费的文档摘录；
- `/tmp/smart-search-evidence/aiia-optimization-round44/02-prometheus-exposition-official.json`
  保存 Prometheus exposition format official-domain 检索结果，包含 HELP / TYPE
  只能各出现一次、TYPE 必须在第一个 sample 前、samples 逐行输出的格式要求。

### 3.61 R518 · Prometheus family 剩余 sample list 全部惰性化

R517 先把 `_format_prom_metric_family()` 放宽成 one-pass iterable，并改掉
SSE by-type 的 `emit_by_type_samples`。继续审计 `/api/system/metrics` 后，仍有
四处 scrape-time staging list：

- notification per-provider metric family：每个 metric suffix 一份 `samples` list；
- notification send-duration histogram：`notif_hist_observations` list；
- MCP tool-call counter family：`mcp_samples` list；
- MCP tool-call latency histogram：`hist_observations` list。

这些 list 都只被 family formatter 消费一次。R518 做两层收敛：

1. `_format_prom_histogram_family()` 的 `observations` 也从 `list[...]` 放宽成
   `Iterable[...]`，空 iterable 仍返回 `""`；
2. 增加四个 generator helper：
   `_iter_notification_provider_metric_samples()`、
   `_iter_notification_latency_histogram_observations()`、
   `_iter_mcp_tool_call_samples()`、
   `_iter_mcp_tool_latency_histogram_observations()`。

渲染路径改成先调用 formatter，formatter 产出非空字符串才 append 到 `lines`：

```python
mcp_tool_call_metrics = _format_prom_metric_family(
    "aiia_mcp_tool_calls_total",
    ...,
    samples=_iter_mcp_tool_call_samples(tool_stats),
)
if mcp_tool_call_metrics:
    lines.append(mcp_tool_call_metrics)
```

行为边界：

- HELP / TYPE 仍各只输出一次，且仍在对应 family 的 sample 行之前；
- 空 sample / observation iterable 仍返回 `""`，不会输出空 family header；
- notification provider / MCP tool 的原有过滤规则不变：非字符串名称、非 dict
  stats、非数值 raw 值继续跳过；
- histogram 的 `+Inf` auto-fill、bucket 升序、`_sum` / `_count` 输出不变；
- `success_rate` / `avg_latency_ms` 仍按 gauge 输出 float，其余 provider metric
  仍按 int 输出；
- 每次 `/api/system/metrics` scrape 少四类临时 list allocation，family 输出文本不变。

新增 `tests/test_prom_family_iterables_r518.py`：

- runtime test 覆盖 `_format_prom_histogram_family()` 可消费 one-pass generator；
- runtime test 覆盖空 histogram generator 仍返回空字符串；
- runtime test 覆盖 notification provider / MCP tool sample generator 的过滤与数值转换；
- source invariant 锁定 `_render_prometheus_metrics()` 不再出现 `samples: list[`、
  `mcp_samples`、`notif_hist_observations`、`hist_observations`，并调用四个 iterator
  helper。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round45/01-python-iterator-generator-official.json`
  保存 Python official-domain 检索结果，包含 `for` statement 会为 iterable 创建
  iterator 并逐项消费的文档摘录；
- `/tmp/smart-search-evidence/aiia-optimization-round45/02-prometheus-histogram-exposition-official.json`
  保存 Prometheus official-domain 检索结果，包含 text exposition 的 HELP / TYPE
  约束，以及 histogram `_bucket` / `_sum` / `_count`、`le="+Inf"` bucket 要求。

### 3.62 R519 · `/api/config` 自动激活首个未完成任务去双 list

`GET /api/config` 在没有 active task 时会尝试自动激活第一个未完成任务。旧路径：

```python
all_tasks = task_queue.get_all_tasks()
incomplete_tasks = [t for t in all_tasks if t.status != "completed"]
if incomplete_tasks:
    first_task = incomplete_tasks[0]
```

这里有两个不必要的分配：

- `get_all_tasks()` 已经把整个 `_tasks.values()` 复制成 list；
- `incomplete_tasks` 又把未完成任务再复制成第二个 list，但 caller 只读取 `[0]`。

R519 在 `TaskQueue` 增加两个 read-side helper：

```python
def get_first_incomplete_task(self) -> Task | None:
    with self._lock.read_lock():
        for task in self._tasks.values():
            if task.status != TaskStatus.COMPLETED:
                return task
        return None

def has_tasks(self) -> bool:
    with self._lock.read_lock():
        return bool(self._tasks)
```

`/api/config` fallback 改为：

- `first_task = task_queue.get_first_incomplete_task()`；
- 有结果时继续调用既有 `set_active_task(first_task.task_id)`，持久化 / callback /
  SSE 语义不变；
- 无未完成任务但 `task_queue.has_tasks()` 为真时，保持“所有任务均已完成”的无内容
  response；
- 无 queue task 时继续回退到旧单任务模式。

行为边界：

- “第一个”仍是 Python dict insertion order，对齐旧 `get_all_tasks()` 返回顺序；
- completed task 继续被跳过；
- `set_active_task()` 仍是唯一写状态入口，幂等、拒绝 completed、持久化和状态回调
  语义不变；
- all-completed 与 no-task 两个 response 分支保持区分；
- active task 正常命中路径不变；
- 没有 active task 的轮询路径少一次全量 task list allocation，且首个未完成任务在
  队列前部时可提前停止扫描。

新增 `tests/test_task_queue_first_incomplete_r519.py`：

- runtime test 覆盖 insertion-order 下返回第一个未完成任务；
- runtime test 覆盖 empty / all-completed 时返回 `None`，并覆盖 `has_tasks()`；
- source invariant 锁定 helper 内不出现 `list(`，route 内不再出现
  `incomplete_tasks = [` / `task_queue.get_all_tasks()`，并调用
  `get_first_incomplete_task()` / `has_tasks()`。

同时更新 `tests/test_web_ui_config.py::TestApiConfigBranches` 的 mocks，验证自动激活
分支调用新 helper 且不再调用 `get_all_tasks()`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round46/01-python-dict-order-official.json`
  保存 Python official-domain 检索结果，包含 `list(d)` 会按 insertion order 返回
  key 的文档摘录，用于证明旧 list 快照与新 `_tasks.values()` 扫描的顺序一致；
- `/tmp/smart-search-evidence/aiia-optimization-round46/02-python-next-iterator-official.json`
  保存 Python official-domain 检索结果，包含 list comprehension 会创建新 list、
  以及 iterator / generator 可逐项消费并提前停止的文档摘录。

### 3.63 R520 · `/api/tasks/export?since=` 去过滤中间 list

`GET /api/tasks/export` 的增量路径旧代码：

```python
tasks, stats = task_queue.get_all_tasks_with_stats()
if since_dt is not None:
    tasks = [t for t in tasks if _task_modified_since(t, since_dt)]

exported = []
for task in tasks:
    ...
```

`tasks` 原始快照仍然有价值：它来自 `get_all_tasks_with_stats()` 的单锁快照，
并和 `stats` 保持同一读时刻。但 `since` 分支里的第二个 list 没有独立语义：
它只被后面的 `for task in tasks` 消费一次，随后所有格式都使用 `exported`
作为唯一响应 payload。

R520 把该分支改为 one-pass iterable：

```python
if since_dt is None:
    tasks_iter = iter(tasks)
else:
    tasks_iter = (
        task for task in tasks if _task_modified_since(task, since_dt)
    )

exported: list[dict[str, Any]] = []
for task in tasks_iter:
    ...
```

行为边界：

- 保留 `get_all_tasks_with_stats()` 的原始 snapshot，不改变 stats 的全局语义；
- `since` 缺省时显式 `iter(tasks)`，全量导出顺序不变；
- `since` 存在时只移除过滤后的中间 list allocation，最终 `exported` list 仍保留，
  因为 JSON payload 和 Markdown renderer 都需要完整响应体；
- `_task_modified_since()` 调用次数、过滤条件、JSON `incremental/since` 元数据、
  Markdown `Filtered since:` header 均不变。

新增 `tests/test_tasks_export_lazy_since_r520.py`：

- source invariant 锁定 route 不再出现
  `tasks = [t for t in tasks if _task_modified_since(t, since_dt)]`；
- source invariant 锁定 `tasks_iter = iter(tasks)` / generator expression /
  `for task in tasks_iter`；
- runtime test 覆盖 JSON 增量导出仍只返回新 task，且 `stats.total` 仍是全局值；
- runtime test 覆盖 Markdown 增量导出仍保留 `Filtered since:` 并排除旧 task。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round47/01-python-list-generator-official.json`
  保存 Python official-domain 检索结果，包含 list comprehension 会创建新 list 的
  文档摘录；
- `/tmp/smart-search-evidence/aiia-optimization-round47/04-python-generator-expression-official.json`
  保存 Python official-domain 检索结果，包含 generator expression / iterator
  逐项消费的文档摘录；
- `/tmp/smart-search-evidence/aiia-optimization-round47/02-python-list-comprehensions-fetch.json`
  和 `03-python-generator-expressions-fetch.json` 记录 direct fetch 尝试未能从
  fetch provider 抽取内容，保留为证据链的可复现失败记录。

### 3.64 R521 · `get_all_tasks_with_stats()` 单遍构建 snapshot + stats

`TaskQueue.get_all_tasks_with_stats()` 是 `/api/tasks` 和 `/api/tasks/export`
共享的读侧 snapshot API。旧实现已经比 R23.4 前的
`get_all_tasks()` + `get_task_count()` 好：它只拿一次 `read_lock`，并保证
`tasks` 和 `stats` 来自同一临界区。但内部仍有一个可收敛的二次扫描：

```python
tasks_view = list(self._tasks.values())
counts = {...}
for t in tasks_view:
    if t.status in counts:
        counts[t.status] += 1
```

这里 `tasks_view` 作为返回值必须保留；问题不是 list snapshot 本身，而是先由
`list(...)` 遍历 `_tasks.values()` 构建 snapshot，再由 Python 层二次遍历这个
snapshot 计数。R521 改为在同一个 read lock 内单遍构建：

```python
counts = {...}
tasks_view: list[Task] = []
for t in self._tasks.values():
    tasks_view.append(t)
    if t.status in counts:
        counts[t.status] += 1
```

行为边界：

- 返回的 `tasks_view` 仍是独立 list copy，调用方清空该 list 不影响 queue；
- 任务顺序仍是 dict insertion order，与旧 `list(self._tasks.values())` 一致；
- `stats` 字段、`total = len(tasks_view)`、`max`、pending / active / completed
  计数规则不变；
- 单次 `read_lock` 和原子 snapshot 语义不变；
- 每次 `/api/tasks` / export snapshot 少一次随任务数增长的 list 二次扫描。

新增 `tests/test_get_all_tasks_with_stats_one_pass_r521.py`：

- runtime test 覆盖返回顺序、stats 计数、list copy 语义；
- source invariant 锁定方法内不再出现
  `tasks_view = list(self._tasks.values())`；
- source invariant 锁定 `tasks_view.append(t)` 与 status count 在同一个
  `for t in self._tasks.values()` loop 内；
- source invariant 锁定 docstring 记录 `R521`，避免未来重构丢失优化原因。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round48/01-python-list-append-values-official.json`
  保存 Python official-domain 检索结果，包含 `list.append` 会向 list 末尾添加项、
  `list(d)` / dictionary iteration 按 insertion order 返回内容的文档摘录；
- `/tmp/smart-search-evidence/aiia-optimization-round48/02-python-for-iterator-list-append-official.json`
  保存 Python official-domain 检索结果，包含 `for` statement 会对 iterable
  创建 iterator 并逐项执行 suite 的文档摘录。

### 3.65 R522 · TaskQueue status 计数去 per-task dict membership

R521 把 `get_all_tasks_with_stats()` 从“先建 list、再扫 list 计数”收敛到单遍
`_tasks.values()`，但两个 status 统计路径仍然使用同一个模式：

```python
counts = {
    TaskStatus.PENDING: 0,
    TaskStatus.ACTIVE: 0,
    TaskStatus.COMPLETED: 0,
}
for t in self._tasks.values():
    if t.status in counts:
        counts[t.status] += 1
```

这里 `TaskStatus` 的合法统计桶是固定三项。R522 把
`get_all_tasks_with_stats()` 和 `get_task_count()` 都改成局部 int counter：

```python
pending = active = completed = 0
for t in self._tasks.values():
    if t.status == TaskStatus.PENDING:
        pending += 1
    elif t.status == TaskStatus.ACTIVE:
        active += 1
    elif t.status == TaskStatus.COMPLETED:
        completed += 1
```

行为边界：

- 返回 dict 字段仍是 `total/pending/active/completed/max`；
- 正常三状态计数不变；
- 非预期 status 继续只进入 `total`，不进入 breakdown，保持旧
  `if t.status in counts` 的容错语义；
- `get_all_tasks_with_stats()` 仍单遍构建 snapshot + stats；
- `get_task_count()` 仍只读一次 `_tasks.values()`，但每个 task 少一次 dict
  membership 和 dict item update。

新增 `tests/test_task_queue_status_direct_counters_r522.py`：

- runtime test 覆盖 `get_task_count()` 遇到未知 status 时 `total` 包含该 task，
  breakdown 忽略该 task；
- runtime test 覆盖 `get_all_tasks_with_stats()` 同样保留顺序并忽略未知 status；
- source invariant 锁定两个方法不再出现 `counts: dict` /
  `if t.status in counts` / `counts[t.status]`；
- source invariant 锁定两个 docstring 都记录 `R522`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round49/01-python-dict-membership-official.json`
  保存 Python official-domain 检索结果，包含 dictionary membership 使用 `in`
  检查 key 的文档摘录；
- `/tmp/smart-search-evidence/aiia-optimization-round49/02-python-if-comparison-official.json`
  保存 Python official-domain 检索结果，包含 `if` / `elif` 会按顺序求值并只执行
  第一个 truthy suite 的文档摘录。

### 3.66 R523 · SSE oversize_drop metadata 固定 schema formatter

`_SSEBus.emit()` 的 R58 oversize guard 已经通过 R501/R502 避免大多数事件的
UTF-8 byte-size 临时 `bytes` 分配，但真正命中 oversize 时仍会重新构造一个
metadata dict 并走一次完整对象级 `json.dumps(data, ensure_ascii=False)`：

```python
data = {
    "original_event_type": original_event_type,
    "size_bytes": payload_bytes,
    "limit_bytes": self._OVERSIZE_LIMIT_BYTES,
}
serialized_data = json.dumps(data, ensure_ascii=False)
```

这个 warning payload 的 schema 是固定三字段，其中两个字段是 bus 内部计算出的
整数；唯一不能手写的部分是 `original_event_type`，因为 R203 已明确防御动态 /
free-form event type，必须保留 JSON 字符串 escaping。R523 增加
`_format_sse_oversize_drop_payload(original_event_type, size_bytes, limit_bytes)`：

```python
event_type_json = json.dumps(original_event_type, ensure_ascii=False)
return (
    '{"original_event_type":'
    f'{event_type_json},"size_bytes":{size_bytes},'
    f'"limit_bytes":{limit_bytes}'
    "}"
)
```

行为边界：

- `original_event_type` 仍由 Python JSON encoder 负责转义，保留引号、换行和中文
  event type 的 wire safety；
- `size_bytes` / `limit_bytes` 仍是精确 int metadata；
- `json.dumps(original_event_type, ...)` 抛 `TypeError` / `ValueError` 时返回
  `None`，保持旧 metadata 序列化失败后的 fail-soft `_serialized=None` 边界；
- fan-out、event id、`oversize_drops`、`emit_by_type["oversize_drop"]` 语义不变；
- oversize 命中路径少一次 metadata dict 的对象级 JSON 遍历。

新增 `tests/test_sse_oversize_drop_fastpath_r523.py`：

- formatter runtime test 覆盖含引号、换行、中文的 event type 仍能
  `json.loads()` 回原对象；
- fail-soft test patch `json.dumps` 抛异常，锁定 helper 返回 `None`；
- source invariant 锁定 oversize branch 调用 dedicated formatter 且不再出现
  `json.dumps(data`；
- runtime spy 锁定一次 oversize emit 只 JSON encode 原 payload dict 和
  event type string，不再 JSON encode metadata dict。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round50/01-python-json-dumps-string-official.json`
  保存 Python official-domain 检索结果，包含 `json.dumps(obj)` 会把对象序列化为
  JSON formatted `str`，以及 `ensure_ascii=False` 时非 ASCII 字符可原样输出；
- `/tmp/smart-search-evidence/aiia-optimization-round50/02-python-fstring-int-official.json`
  保存 Python official-domain 检索结果，包含 Python format mini-language 对整数
  decimal 表示的官方说明。

### 3.67 R524 · Web 任务列表 diff 去 nested `includes`

Web UI 的 `multi_task.js::updateTasksList()` 每次 `/api/tasks` 轮询或 SSE
触发刷新都会比较前后任务列表。旧实现先构造两个完整 id 数组，再用
`Array.prototype.includes()` 做 membership：

```js
const oldTaskIds = currentTasks.map((t) => t.task_id);
const newTaskIds = tasks.map((t) => t.task_id);
const addedTasks = newTaskIds.filter((id) => !oldTaskIds.includes(id));
const removedTasks = oldTaskIds.filter((id) => !newTaskIds.includes(id));
tasks
  .filter((t) => addedTasks.includes(t.task_id))
  .forEach(...)
```

这条路径是 2s poll + SSE debounce 的稳定热路径。任务数增长时，`filter` 内的
`includes` 会变成重复线性扫描；同时为了拿新任务对象又扫了一次 `tasks`。
R524 抽出 `_buildTaskListDiff(previousTasks, nextTasks)`：

- 单遍扫描旧列表，得到 `oldTaskIds`（保留 removed 顺序）和 `oldTaskIdSet`；
- 单遍扫描新列表，得到 `newTaskIdSet`、`addedTaskIds` 和 `addedTasks`；
- 单遍扫描旧 id，得到 `removedTaskIds`；
- `updateTasksList()` 直接消费 `taskDiff.addedTasks` 启动新任务倒计时，不再做
  `tasks.filter(...addedTasks.includes...)`。

行为边界：

- 新任务通知数量和顺序仍按后端返回的任务顺序；
- removed cleanup 顺序仍按旧 `currentTasks` 顺序；
- completed task cleanup、active task reconcile、deep-link、extend/freeze 按钮同步
  语义不变；
- existing runtime test 还锁定了 legacy per-task countdown timer cleanup；本轮发现
  `_clearTaskCountdown()` 对非 shared-ticker timer 只删除 entry、不 `clearInterval`，
  已补回 `clearInterval(timer)`，同时保留 shared ticker idle cleanup。

新增 `tests/test_multi_task_update_diff_sets_r524.py`：

- source invariant 锁定 diff helper 使用 `new Set()` 和 `.has(taskId)`；
- source invariant 锁定 `updateTasksList()` 不再出现旧的 parallel id arrays +
  nested `includes` 形态；
- Node runtime test 直接执行 `_buildTaskListDiff()`，验证 added task ids、added
  task objects、removed ids 的顺序不变。

同时重新生成静态产物：

- `src/ai_intervention_agent/static/js/multi_task.min.js`
- `src/ai_intervention_agent/static/js/multi_task.js.gz`
- `src/ai_intervention_agent/static/js/multi_task.js.br`
- `src/ai_intervention_agent/static/js/multi_task.min.js.gz`
- `src/ai_intervention_agent/static/js/multi_task.min.js.br`

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round51/01-mdn-set-has-array-includes.json`
  保存 MDN `Set` 文档：`Set` 平均访问时间需优于 O(N)，且 `Set.prototype.has`
  在同等元素数量下平均快于 `Array.prototype.includes`；`Set` 迭代顺序是插入顺序。

### 3.68 R525 · SSE debug-only JSON parse 按调试开关惰性化

Web UI 的 `multi_task.js` 在直连 `EventSource` 和 BroadcastChannel follower 两条
SSE 消费路径里，对 `task_changed`、`gap_warning`、`heartbeat` 都先
`JSON.parse()` payload，再传给 `_debugLog()`。但 `_debugLog()` 默认因
`window.AIIA_DEBUG` 为 false 直接返回，所以正常用户路径每条 named SSE 事件都
在做一份无可见效果的解析工作。

R525 抽出 `_debugLogEnabled()` 并让 `_debugLog()` 复用同一判断；同时新增
`_debugSseTaskChanged(data)` 和 `_debugSseDetail(label, data)`，只在 debug
真正启用且 `console.debug` 可用时才解析 JSON：

- `task_changed` 仍更新 `_lastEventId`、debounce `fetchAndApplyTasks("sse")`；
- `gap_warning` 仍立即触发 full resync；
- `heartbeat` 仍保留 named listener 和跨 tab fan-out；
- `config_changed` 不做惰性化，因为它解析 `detail.hint` 作为 i18n fallback，
  是用户可见行为路径，不是纯 debug。

新增 `tests/test_multi_task_sse_debug_parse_guard_r525.py`：

- Node runtime test monkeypatch `JSON.parse` 计数，验证 debug=false 时直连 +
  shared follower 的 6 个 debug-only SSE payload 不再触发解析；
- 同一测试验证 `config_changed` 在 debug=false 下仍解析 1 次，保留可见 hint
  fallback 行为；
- debug=true 测试验证 6 个 debug-only payload 仍被解析，且诊断日志标签不变。

同步更新 `tests/test_multi_task_sse_console_noise.py`，让旧的源码扫描适配
`_debugLogEnabled()` helper，同时继续锁定 SSE 正常路径不使用 `console.log` /
`console.warn` / 直接 `console.debug`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round52/03-exa-mdn-json-parse.json`
  保存 MDN `JSON.parse()` 文档：该 API 会解析 JSON 字符串并构造对应 JS
  value/object，非法 JSON 会抛 `SyntaxError`。因此在 debug 关闭时跳过解析是
  直接减少 CPU/异常路径工作的安全优化。
- `/tmp/smart-search-evidence/aiia-optimization-round52/04-exa-mdn-eventsource.json`
  保存 MDN Server-Sent Events 文档：named SSE 通过 `addEventListener()` 接收，
  `data` 字段可以是任意字符串，并不天然要求 JSON；只有消费方需要字段时才解析。

### 3.69 R526 · Web 任务标签页 diff 去 nested includes/find

`multi_task.js::renderTaskTabs()` 是 `/api/tasks` polling、SSE debounce、手动
刷新都会触发的前端热路径。R524 已经优化了任务列表增删检测，但标签页渲染内部
仍然保留一套独立 diff：

```js
const incompleteTasks = currentTasks.filter((task) => task.status !== "completed");
const existingTaskIds = Array.from(existingTabs).map((tab) => tab.dataset.taskId);
const incompleteTaskIds = incompleteTasks.map((t) => t.task_id);
const removedIds = existingTaskIds.filter((id) => !incompleteTaskIds.includes(id));
const addedIds = incompleteTaskIds.filter((id) => !existingTaskIds.includes(id));
addedIds.forEach((id) => {
  const task = incompleteTasks.find((t) => t.task_id === id);
  ...
});
```

任务数增长时，这里会形成多轮数组分配和 nested membership 扫描；新增任务还要
在 `incompleteTasks` 中再 `find()` 一次。R526 抽出
`_buildTaskTabRenderState(tasks, tabsContainer)`：

- 单遍扫描 `currentTasks`，生成 `incompleteTasks`、`incompleteTaskIds` 和
  `incompleteTaskIdSet`；
- 只有存在未完成任务时才查询 `.task-tab:not(.task-tab-exit)`，保留无开放任务时
  不做 tab DOM 查询的 fast path；
- 单遍扫描现有 tabs，生成 `existingTaskIds` 和 `existingTaskIdSet`；
- 顺序比较仍逐 index，保持“同集合但顺序变了必须 rebuild”的语义；
- `removedIds` 使用 `incompleteTaskIdSet.has(id)`；
- `addedTasks` 直接在扫描 incomplete tasks 时用 `existingTaskIdSet.has(...)`
  得到，`renderTaskTabs()` 不再 `addedIds -> incompleteTasks.find(...)`。

行为边界：

- 正在退出动画的 `.task-tab-exit` 仍被排除，避免虚假重建；
- `removedIds` 顺序仍按现有 DOM tab 顺序；
- `addedTasks` 顺序仍按后端返回的未完成任务顺序；
- 增量动画阈值仍是“新增 + 删除 <= 2 且已有 tabs 非空”；
- active tab 的 `active` / `aria-selected` / `tabindex` 更新路径不变；
- all-completed 时仍只隐藏 tab container，不额外 query existing tabs。

新增 `tests/test_multi_task_render_tabs_state_r526.py`：

- source invariant 锁定 helper 使用两个 `Set` 和 `.has()`，且不再出现
  `.includes()` / `.find()` / `.filter()` / `Array.from()`；
- source invariant 锁定 `renderTaskTabs()` 消费 `tabState.addedTasks`，不再
  `addedIds.forEach(... incompleteTasks.find ...)`；
- Node runtime test 验证 completed task 被跳过，removed/added 顺序保持；
- Node runtime test 验证全 completed path 不调用 `tabsContainer.querySelectorAll()`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round53/01-mdn-set-has-array-includes.json`
  保存 MDN `Set` 文档：`Set.prototype.has()` 在同等元素数量下平均快于
  `Array.prototype.includes()`，`Set` 访问复杂度要求平均优于 O(N)。
- `/tmp/smart-search-evidence/aiia-optimization-round53/02-mdn-queryselectorall-nodelist.json`
  保存 MDN `querySelectorAll()` / `NodeList` 文档：`querySelectorAll()` 返回
  static NodeList，元素按 document order；NodeList 可用 `forEach()` 迭代。

### 3.70 R527 · Web 任务刷新 active/cleanup 状态单遍快照

R524/R526 已经把任务列表增删 diff 和 tab diff 改成 Set-backed 线性路径。
`multi_task.js::updateTasksList()` 后半段仍然在同一次 `/api/tasks` refresh 中做
多轮只读扫描：

```js
tasks
  .filter((task) => task && task.status === "completed")
  .forEach((task) => clearTaskLocalState(getTaskIdString(task)));
const hasActiveTasks =
  tasks.length > 0 && tasks.some((t) => t.status !== "completed");
const activeTask = tasks.find((t) => t.status === "active");
const nextActiveTaskId = activeTask
  ? getTaskIdString(activeTask) || pickOpenTaskId(activeTaskId, tasks)
  : pickOpenTaskId(activeTaskId, tasks);
var _activeTask = tasks.find((t) => getTaskIdString(t) === activeTaskId);
```

其中 `pickOpenTaskId()` 自身又会调用 `getOpenTaskId()` 和 `find()`。这些都是
同一份 task snapshot 的只读派生状态，且位于 polling / SSE debounce 的稳定热路径。

R527 抽出 `_buildTaskRefreshState(tasks, preferredTaskId)`：

- 单遍扫描 `tasks`，收集 `completedTaskIds`；
- 同一轮记录 `hasActiveTasks`，保留“存在任意非 completed task 即显示内容页”的
  原语义；
- 同一轮记录第一个 server-side `active` task、preferred open task、first open
  task；
- `nextActiveTaskId` 仍保持旧优先级：server active > 当前 open task > first open
  task > null；
- `activeTaskForControls` 在 helper 内直接解析，`+60s` / `freeze` 控制不再额外
  `tasks.find(...)`；
- 删除浏览器端已无调用方的 `getOpenTaskId()` / `pickOpenTaskId()`，避免留下旧
  双扫描 helper。

行为边界：

- completed cleanup 顺序仍按后端返回的 `tasks` 顺序；
- server active 仍优先覆盖本地 active；
- 如果 server active 缺可用 id，仍 fallback 到 preferred / first open task；
- preferred open task 仍优先于 first open task；
- all-completed 时 `activeTaskId` 仍清空，控制按钮拿到 `null`；
- 倒计时 ensure loop 保持独立，因为它有 `startTaskCountdown()` /
  `autoSubmitTask()` 等副作用，本轮只合并只读状态扫描。

新增 `tests/test_multi_task_refresh_state_r527.py`：

- source invariant 锁定 `_buildTaskRefreshState()` 只有一个
  `for (const task of tasks)`，且不使用 `.filter()` / `.some()` / `.find()` /
  `.map()`；
- source invariant 锁定 `updateTasksList()` 消费 `taskRefreshState`，不再出现
  completed filter、has-active `some`、server-active `find`、`pickOpenTaskId()`；
- Node runtime test 验证 server active priority、completed cleanup 顺序、
  controls task；
- Node runtime test 验证 server active 无 id 时 fallback 到 preferred open task；
- Node runtime test 验证 all-completed 返回 `nextActiveTaskId = null`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round54/01-mdn-array-filter.json`
  保存 MDN `Array.prototype.filter()` 文档：`filter()` 是 iterative method，会为
  通过 predicate 的元素构造一个新的 shallow-copy array。
- `/tmp/smart-search-evidence/aiia-optimization-round54/02-mdn-array-find-some.json`
  保存 MDN `Array.prototype.find()` / `some()` 文档：这些是 iterative methods；
  `find()` 会按升序调用 callback 直到命中，`some()` 也会独立迭代到结果确定。
  对同一 snapshot 的多个只读派生值，用一轮显式循环收集可以避免重复 callback
  调用和中间数组分配。

### 3.71 R528 · VS Code status poll new-task ids 去重复 map

VS Code extension 的 `updateStatusBar()` 在每轮 `/api/tasks` 轮询中已经遍历一次
`data.tasks`：

```ts
const currentIds = new Set<string>();
const newTaskData: TaskData[] = [];
for (const t of data.tasks as Array<Record<string, unknown>>) {
  if (!t || !t.task_id) continue;
  const taskId = String(t.task_id);
  currentIds.add(taskId);
  if (extTaskTrackingInitialized && !extKnownTaskIds.has(taskId)) {
    newTaskData.push({ id: taskId, prompt: String(t.prompt || "") });
  }
}
```

但后续两个 telemetry 分支只需要 new-task id list 时，又分别执行
`newTaskData.map((t) => t.id)`。这会在 VS Code 扩展主机的 polling hot path 中为
日志 payload 再做一次 callback 迭代和临时数组分配；dispatch 仍需要完整
`TaskData[]`，因此最小改动是在原扫描里同步维护 id list。

R528 在同一轮 new-task detection 中增加 `newTaskIds: string[]`：

- 检测到新任务时同时 `newTaskData.push(...)` 和 `newTaskIds.push(taskId)`；
- `ext.skip_dispatch_webview_visible` 直接记录 `{ ids: newTaskIds }`；
- `ext.dispatch_new_task` 直接记录 `{ ids: newTaskIds, viewVisible: false }`；
- webview dispatch payload 仍保持 `newTaskData`，prompt 字段和触发条件不变。

行为边界：

- 只有 `extTaskTrackingInitialized && !extKnownTaskIds.has(taskId)` 的任务进入
  两个数组，和旧 `newTaskData.map(...)` 的 id 集合一致；
- id 顺序仍是后端 `data.tasks` 返回顺序；
- view visible 时仍只记录 skip telemetry，不 dispatch；
- view hidden 时仍 dispatch 完整 `TaskData[]`，只是日志 ids 不再从 payload 派生。

新增 `tests/test_vscode_status_poll_new_task_ids_r528.py`：

- source invariant 锁定 `updateStatusBar()` 内存在 `newTaskIds`；
- source invariant 锁定 new-task 分支同步 push `taskId`；
- source invariant 锁定两个 logger payload 均使用 `newTaskIds`；
- source invariant 锁定 `updateStatusBar()` 不再出现 `newTaskData.map(...)`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round55/01-mdn-array-map.json`
  保存 MDN `Array.prototype.map()` 文档：`map()` 会对每个元素调用 callback，
  并构造由 callback 结果组成的新数组；如果只为副作用或可在既有扫描中同步收集
  结果，额外 `map()` 会带来不必要的迭代和数组分配。

### 3.72 R529 · VS Code new-task dispatch payload 单遍归一化

R528 已经把 extension host 的 status poll telemetry ids 改成在原扫描中同步收集。
同一条新任务通知链路进入 `WebviewProvider.dispatchNewTaskNotification()` 后，仍然
存在一组独立的数组链：

```ts
const items = Array.isArray(taskData) ? taskData.filter(Boolean) : [];
if (items.length === 0) return;

const ids = items.map((t) => (t && t.id) || "").filter(Boolean);
if (ids.length === 0) return;
```

该方法是 status poll 发现新任务后、真正派发 VS Code / macOS notification 前的
稳定路径。旧写法会为同一份 `TaskData[]` 先构造 filtered items 数组，再 map 出
id 数组，再 filter 一次空 id；而后续逻辑仍需要 `items[0].prompt`、`ids.length`
和 `ids.join("|")`。

R529 把入口归一化改成一轮显式扫描：

- `items: TaskData[]` 保存所有 truthy task，继续作为 first prompt 来源；
- `ids: string[]` 同步收集 truthy `item.id`；
- 非 array payload 仍得到空 items 并直接 return；
- `items.length === 0` 与 `ids.length === 0` 的 early return 顺序保持不变；
- 后续 telemetry、notification config fetch、summary、dedupe key、metadata
  均继续消费同一 `ids` / `items`。

行为边界：

- 第一个 summary prompt 仍来自第一个 truthy task，而不是第一个有 id 的 task；
- id 顺序仍按传入 `taskData` 顺序；
- 无 id 但有 prompt 的 payload 仍在 `ids.length === 0` 时不派发，和旧行为一致；
- `taskData` 非数组时仍不会抛异常；
- notification 类型选择、macOS native 开关、dedupe key wire contract 不变。

新增 `tests/test_vscode_dispatch_new_task_one_pass_r529.py`：

- source invariant 锁定 method 内声明 `items` / `ids` 并用
  `for (const item of taskData)` 单遍收集；
- source invariant 锁定保留 `items[0].prompt` 的 first prompt 语义；
- source invariant 锁定该 method 不再出现 `taskData.filter(Boolean)`、
  `items.map(...)` 或 `.filter(Boolean)` 链。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round56/01-mdn-array-filter-map.json`
  保存 MDN `Array.prototype.filter()` / `map()` 文档：`filter()` 是 iterative
  method，会构造通过 predicate 的新数组；`map()` 也会对每个元素调用 callback
  并构造新数组。对同一 payload 的 items 和 ids 同步派生，用一轮循环可以避免
  额外 callback 调用与中间数组分配。

### 3.73 R530 · VS Code webview 通知入口去 filter/map/filter 链

R528/R529 已经把 extension host status poll 与 `WebviewProvider` host-side
dispatch 做成单遍 id 收集。进入 webview browser 侧后，仍有两处新任务通知入口
保留同类数组链：

```js
const items = Array.isArray(taskData) ? taskData.filter(Boolean) : [taskData].filter(Boolean)
const normalized = items.map(item =>
  typeof item === 'string' ? { id: item, prompt: '' } : item
)
const ids = normalized.map(t => t.id || t).filter(Boolean)
```

`webview-notify-core.js::showNewTaskNotification()` 同样先 filter，再 map
兼容字符串 payload，再 map/filter ids。两者都位于新任务通知派发路径：
`webview-ui.js::notifyNewTasks()` 是前端 message handler 的入口，notify-core 是
真正构造通知文案、metadata 和 dedupe key 的入口。

R530 把两处入口都改为一轮显式扫描：

- `webview-ui.js`：从 `sourceItems` 同步构造 `normalized` 和 `ids`；
- `webview-notify-core.js`：同样同步构造 `normalized` 和 `ids`；
- 字符串 payload 仍归一化为 `{ id: item, prompt: "" }`；
- 空 payload / 全 falsy payload 仍直接 return；
- `normalized` 仍传给 preloaded / lazy-loaded notify-core；
- notify-core 的 first prompt 仍取 `normalized[0].prompt`。

行为边界：

- `webview-ui.js` 保留旧的 `t.id || t` id fallback：对象缺 id 时仍算作 truthy
  legacy id，避免在 wrapper 层改变历史派发边界；
- `webview-notify-core.js` 保留旧的 `t.id || ""` 边界：对象缺 id 不派发；
- id 顺序仍按输入 taskData 顺序；
- 单个非数组 payload 仍走 `[taskData]` 兼容路径；
- notify-core 的 settings refresh、enabled=false skip、macOS native 类型选择、
  metadata.taskIds 和 dedupe key contract 不变。

新增 `tests/test_vscode_webview_notify_one_pass_r530.py`：

- source invariant 锁定 `webview-ui.js::notifyNewTasks()` 使用 `sourceItems`、
  `normalized`、`ids` 和 `for (const item of sourceItems)`；
- source invariant 锁定 wrapper 保留 `normalizedItem.id || normalizedItem`；
- source invariant 锁定 `webview-notify-core.js::showNewTaskNotification()` 使用
  indexed `for` 单遍收集；
- source invariant 锁定 notify-core 保留 `normalizedItem.id || ""` 和 first
  prompt 语义；
- 两处 method 均锁定不再出现 `taskData.filter(Boolean)`、`.filter(Boolean)`、
  `.map(...)` 归一化链。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round57/01-mdn-array-filter-map.json`
  保存 MDN `Array.prototype.filter()` / `map()` 文档：`filter()` 会调用 callback
  并构造 shallow-copy 结果数组；`map()` 会对每个元素调用 callback 并构造新数组。
  对通知 payload 同时派生 normalized task 和 ids 时，一轮循环能避免多次 callback
  和中间数组分配。

### 3.74 R531 · VS Code webview task tab refresh 状态单遍快照

R530 收敛了 webview 通知入口，但 `webview-ui.js::renderTaskTabs()` 在同一次
`allTasks` snapshot 上仍有多轮只读派生：

```js
const currentHash = allTasks.map(t => t.task_id + ':' + t.status).join('|')
const currentTaskIds = new Set(allTasks.map(t => t.task_id))
const newTasks = allTasks.filter(t => !lastTaskIds.has(t.task_id))
const taskData = newTasks
  .filter(t => t && t.task_id)
  .map(t => ({ id: t.task_id, prompt: t.prompt || '' }))
const activeTasks = allTasks.filter(task => task.status !== 'completed')
const activeTaskIdSet = new Set(activeTasks.map(t => getTaskIdString(t)).filter(Boolean))
```

该函数是 VS Code webview 收到任务刷新后的 tab 渲染热路径。旧写法为了同一份
task snapshot 反复构造中间数组：hash parts、current ids、new task list、
notification payload、active task list、active id list。

R531 抽出 `buildTaskTabsRenderState(tasks, previousTaskIds, collectNewTaskData)`：

- 一轮扫描生成 `currentHash`，保持旧格式 `task_id:status|...`；
- 同一轮填充 `currentTaskIds`，供 `lastTaskIds` 更新；
- 同一轮在 tracking 已初始化时收集 `newTaskData`；
- 同一轮收集 `activeTasks` 和 `activeTaskIdSet`；
- `renderTaskTabs()` 后续只消费 `taskTabsState`，不再对 `allTasks` 做
  `map/filter` 派生。

行为边界：

- `currentHash` 顺序仍按后端 `allTasks` 顺序；
- 新任务通知 payload 仍包含新出现且有 `task_id` 的 task，prompt fallback 仍是
  `""`；
- 初始 tracking 未完成时仍不收集/派发新任务通知；
- completed task 仍从 tab DOM 渲染中排除；
- `activeTaskIdSet` 仍只包含 `getTaskIdString(task)` truthy 的未完成任务；
- stale local state cleanup、active tab reconcile、same-hash fast path、
  countdown update 与 DOM rebuild 边界不变。

新增 `tests/test_vscode_webview_task_tabs_state_r531.py`：

- source invariant 锁定 helper 只有一个 `for (const task of tasks)`；
- source invariant 锁定 helper 同步生成 hash、current ids、new-task payload、
  active tasks 和 active id Set；
- source invariant 锁定 `renderTaskTabs()` 消费 `taskTabsState`，不再出现
  `allTasks.map` / `allTasks.filter` / `activeTasks.map` / `.filter(Boolean)`；
- Node runtime test 验证 hash 顺序、新任务 payload 顺序、completed filtering、
  active id Set 和 `collectNewTaskData=false` 边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round58/01-mdn-array-map-filter-set.json`
  保存 MDN `Array.prototype.map()` / `filter()` / `Set` 文档：`map()` 和
  `filter()` 都会按元素调用 callback 并构造新数组；`Set` 存储唯一值，`has()`
  平均快于同规模数组的 `includes()`。对同一 task snapshot 的多个派生状态，
  单遍构建可以减少重复迭代和中间数组。

### 3.75 R532 · VS Code webview active task reconcile 复用 tab 快照

R531 已经让 `renderTaskTabs()` 对 `allTasks` 做一次只读扫描，但同一函数随后仍调用
`reconcileActiveTaskId()`：

```js
function reconcileActiveTaskId() {
  const previous = activeTaskId ? String(activeTaskId) : ''
  const next = pickOpenTaskId(previous)
  ...
}
```

而 `pickOpenTaskId()` 会先 `getOpenTaskId(preferred)`，再 `find()` server active，
再 `find()` first open task。也就是说，R531 的单遍 tab snapshot 后，active id
reconcile 又可能对同一 `allTasks` 再做最多三轮查找。

R532 扩展 `buildTaskTabsRenderState()`：

- 同一轮记录 `serverActiveTaskId`，即第一个 `status === "active"` 且有 id 的任务；
- 同一轮记录 `firstOpenTaskId`，即第一个未 completed 且有 id 的任务；
- `reconcileActiveTaskId(taskTabsState)` 在 render 路径中先看
  `activeTaskIdSet.has(previous)`，再走 `serverActiveTaskId`，再走
  `firstOpenTaskId`；
- 无 snapshot 参数时仍保留旧 `pickOpenTaskId(previous)` fallback，供
  `pickFallbackTaskId()` 和历史测试继续使用。

行为边界：

- 本地已选择且仍 open 的 `activeTaskId` 继续优先于 server active；
- 本地选择失效时，server active 继续优先于 first open；
- 没有 open task 时仍清空 `activeTaskId`；
- `pickFallbackTaskId()` 的 config 兜底路径仍使用旧 helper，不改变非 tab render
  场景；
- 初次 tracking 后的 active reconcile 顺序与旧 `pickOpenTaskId()` 保持一致。

新增 `tests/test_vscode_webview_active_reconcile_state_r532.py`：

- source invariant 锁定 snapshot helper 填充 `serverActiveTaskId` 和
  `firstOpenTaskId`；
- source invariant 锁定 `renderTaskTabs()` 调用 `reconcileActiveTaskId(taskTabsState)`，
  且 render body 不再调用 `pickOpenTaskId()`；
- Node runtime test 把 fallback `pickOpenTaskId()` 替换为抛异常，验证 snapshot
  reconcile 不再触发旧 find path；
- Node runtime test 覆盖 keep local open、fallback server active、fallback first
  open、all completed 清空四个边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round59/01-mdn-array-find.json`
  保存 MDN `Array.prototype.find()` 文档：`find()` 是 iterative method，会按升序
  调用 callback，直到命中或遍历结束。对同一 task snapshot 已经在 R531 扫描时
  可得的 server-active / first-open 状态，复用快照能避免额外 find 迭代。

### 3.76 R533 · VS Code webview unchanged tab countdown 复用 active snapshot

R531/R532 后，`renderTaskTabs()` 已经在每轮 tab refresh 里构造
`taskTabsState.activeTasks`。但 `currentHash === lastTasksHash` 的 fast path 仍调用
`updateTabCountdowns()`，而旧实现会对 `allTasks.forEach(...)`，包括 completed
任务也会进入 callback 再做 DOM id 查询。

R533 把 countdown 更新入口改成可接收 task slice：

```js
function updateTabCountdowns(tasks = allTasks) {
  const tasksForCountdown = Array.isArray(tasks) ? tasks : allTasks
  tasksForCountdown.forEach(task => {
    ...
  })
}
```

并在 unchanged-hash fast path 调用
`updateTabCountdowns(taskTabsState.activeTasks)`。这样同一轮已经过滤出的 active
snapshot 可以直接复用，避免对 completed task 做额外 callback / DOM lookup；同时无参
调用仍保留 `allTasks` fallback，避免改变其它潜在调用方语义。

行为边界：

- 仅优化 `currentHash === lastTasksHash` 的轻量刷新路径；
- countdown 启动条件仍保持 `auto_resubmit_timeout > 0`、DOM 元素存在、未已有 timer；
- `updateTabCountdowns()` 无参时仍扫描 `allTasks`，兼容历史调用；
- 传入非数组时回退到 `allTasks`，避免异常输入破坏刷新。

新增 `tests/test_vscode_webview_tab_countdowns_active_tasks_r533.py`：

- source invariant 锁定 same-hash 分支调用
  `updateTabCountdowns(taskTabsState.activeTasks)`；
- source invariant 锁定 `updateTabCountdowns(tasks = allTasks)` 通过
  `tasksForCountdown` 迭代，避免重新硬编码 `allTasks.forEach(...)`；
- Node runtime test 传入只含 active task 的数组，同时让 `allTasks` 包含 completed
  task，验证显式路径只 lookup/start active；
- Node runtime test 再调用无参 fallback，验证仍会按旧语义扫描 `allTasks`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round60/01-mdn-array-foreach.json`
  保存 MDN `Array.prototype.forEach()` 文档：`forEach()` 是 iterative method，会对数组
  每个元素执行一次 callback。unchanged-hash 路径已经拥有 active task snapshot 时，
  把 callback 范围缩小到可见/open tab 任务可直接减少重复迭代和无效 DOM 查询。

### 3.77 R534 · VS Code webview helper platform detect 单遍归一化

`packages/vscode/webview-helpers.js` 的 `detectMacLikePlatform(nav)` 只需要检查
`userAgentData.platform`、`platform`、`userAgent` 三个字符串，但旧实现先构造数组，
再 `filter(Boolean)`、`map(toLowerCase)`，随后对归一化数组做两次 `some()`：

```js
const haystacks = [uaDataPlatform, platform, userAgent]
  .filter(Boolean)
  .map((value) => value.toLowerCase())

if (haystacks.some((value) => value.includes('mac'))) return true
if (haystacks.some((value) => /iphone|ipad|ipod/.test(value))) return true
```

R534 改成对三个候选值单遍检查：

```js
const haystacks = [uaDataPlatform, platform, userAgent]
for (const value of haystacks) {
  if (!value) continue
  const normalized = value.toLowerCase()
  if (normalized.includes('mac')) return true
  if (/iphone|ipad|ipod/.test(normalized)) return true
}
```

这样保留同样的输入兼容性和 early-return 语义，但不再创建 filter/map 中间数组，
也不再对同一短数组执行第二轮 `some()`。虽然该 helper 不是高频动画路径，但它会在
webview 初始化/测试宿主路径运行；这类小 helper 适合用单遍、无中间数组的写法保持
代码更直接。

行为边界：

- 非字符串 navigator 字段继续通过 `getNavigatorValue()` 被忽略；
- `mac` 仍优先命中，包括 `MacIntel` / `macOS`；
- iPhone / iPad / iPod user agent 或 platform 仍命中；
- Linux 等非 Mac-like 平台仍返回 `false`；
- iPadOS desktop-mode 的 `platform === "MacIntel" && maxTouchPoints > 1`
  fallback 保留原位置。

新增 `tests/test_vscode_webview_helpers_platform_one_pass_r534.py`：

- source invariant 锁定 `detectMacLikePlatform()` 使用 `for...of` 单遍归一化，
  不再出现 `.filter(` / `.map(` / `.some(`；
- Node runtime test 覆盖 `MacIntel`、`userAgentData.platform = macOS`、iPhone
  UA、iPad platform、Linux、非字符串字段六个边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round61/01-mdn-array-filter-map-some.json`
  保存 MDN Array iterative methods 资料：`filter()` / `map()` 会对元素执行 callback
  并返回新数组，`some()` 是可短路 iterative method。当前逻辑候选值固定且很少，
  单遍循环可以同时归一化和判定，省掉中间数组与重复扫描。

### 3.78 R535 · VS Code webview task image cache 单遍归一化

VS Code webview 的任务切换/图片缓存路径里有四处相同的 image cache 归一化：

```js
images
  .map(img => ({
    name: img && img.name ? String(img.name) : 'image',
    data: img && img.data ? String(img.data) : ''
  }))
  .filter(x => x.data)
```

这些路径分别服务于 `saveLocalStateForTask()`、`restoreLocalStateForTask()`、
`syncImagesToTaskCache()`、`cacheImagesForTask()`。每次都会先构造完整 mapped
数组，再过滤掉空 data；同时四处重复同一序列化契约，后续维护容易漂移。

R535 抽出 `normalizeTaskImages(images)`：

- 非数组输入返回空数组；
- 单遍 `for...of` 读取源 image；
- 先归一化 `data`，空 data 直接跳过；
- 保留 `name` 缺失时使用 `"image"` 的旧契约；
- 保留 `name` / `data` 通过 `String(...)` 序列化的旧契约；
- 四个调用点全部复用 helper。

这让每次任务图片状态保存/恢复少一次中间数组分配和一次 filter callback 扫描，
并把 cache shape 的定义收敛到一个函数。

行为边界：

- 有效图片仍保存为 `{ name, data }`；
- 空 `data`、`null` image 继续被丢弃；
- 缺失/空 `name` 继续写成 `"image"`；
- 数字等非字符串 `name` / `data` 继续通过 `String(...)` 保存；
- `cacheImagesForTask()` 仍保留入口处 `Array.isArray(images)` guard；
- upload transport 和 `renderUploadedImages()` 不变。

新增 `tests/test_vscode_webview_task_image_normalize_r535.py`：

- source invariant 锁定 `normalizeTaskImages()` 使用单个 `for...of`，不出现
  `.map(` / `.filter(`；
- source invariant 锁定四个调用点都复用 helper，且不再内联
  `.map(img => ({...})).filter(x => x.data)`；
- Node runtime test 覆盖有效图片、缺 name、数字 name/data、空 data、null
  image、非数组输入。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round62/01-mdn-array-map-filter.json`
  保存 MDN `Array.prototype.map()` / `Array.prototype.filter()` 文档：二者都是
  iterative methods，`map()` 会为每个元素创建 callback 结果数组，`filter()` 会创建
  过滤后的浅拷贝。这里的目标 cache shape 可在一次循环中完成转换和筛选。

### 3.79 R536 · VS Code tab countdown idle check 去 Object.keys 数组

R498 把 VS Code task tab 倒计时收敛成单个 shared ticker。后续 cleanup 路径里，
`stopSharedTabCountdownTickerIfIdle()` 只需要判断 `tabCountdownTimers` 是否为空，
但旧实现使用：

```js
if (!tabCountdownTickerTimer || Object.keys(tabCountdownTimers).length > 0) return
```

这会为了一个 boolean emptiness check 创建完整 key 数组。R536 新增
`hasTabCountdownTimers()`：

```js
function hasTabCountdownTimers() {
  for (const taskId in tabCountdownTimers) {
    if (Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)) return true
  }
  return false
}
```

`stopSharedTabCountdownTickerIfIdle()` 改为复用该 helper。这样空对象路径和首个
active timer 命中路径都不再分配 key array；同时通过 `hasOwnProperty.call(...)`
保持与 `Object.keys()` 相同的 own-enumerable 边界，不会把原型链上的 enumerable
属性误判为 active timer。

行为边界：

- ticker 不存在时仍直接返回；
- 有任意 own timer 时不清理 shared ticker；
- 只有 inherited enumerable 属性时视为 idle，与 `Object.keys()` 旧语义一致；
- 真正空闲时仍 `clearInterval(tabCountdownTickerTimer)` 并置 `null`；
- `tickAllTabCountdowns()` / `forceUpdateAllTabCountdowns()` 仍保留
  `Object.keys(...).forEach(...)` 的快照迭代语义，本轮只优化纯 emptiness check。

新增/更新测试：

- `tests/test_vscode_tab_countdown_idle_has_timer_r536.py` source invariant 锁定
  `hasTabCountdownTimers()` 使用 `for...in` + own-property guard，且 idle check
  不再出现 `Object.keys(tabCountdownTimers).length`；
- Node runtime test 覆盖 inherited-only、own-active、empty 三个状态；
- `tests/test_vscode_tab_countdown_shared_ticker_r498.py` 更新既有 cleanup invariant，
  继续守住 shared ticker idle cleanup，只是不再要求旧的 `Object.keys().length`
  写法。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round63/01-mdn-object-keys-for-in.json`
  保存 MDN `Object.keys()` / `for...in` 资料：`Object.keys()` 返回 own enumerable
  string-keyed property names 的数组；`for...in` 会枚举原型链，因此需要
  `Object.prototype.hasOwnProperty.call(...)` 才能保持 own-property 语义。

### 3.80 R537 · VS Code task-local cache prune 去 Object.keys 数组

`pruneTaskLocalState(activeTaskIdSet)` 会在 tab render / active reconcile 后清理
已关闭任务的本地缓存。旧实现为了收集 stale task id，对六个 cache object 做：

```js
Object.keys(source || {}).forEach(taskId => {
  ...
})
```

并对 `pendingImageUploadCounts` 再做一次
`Object.keys(pendingImageUploadCounts || {}).forEach(...)`。这里并不需要 key array
快照；函数只是在当前 render 轮里收集 stale id，后续统一删除。R537 改成：

- `rememberTaskIds(source)` 先处理 falsy source，再用 `for...in` 遍历；
- 每个 key 都用 `Object.prototype.hasOwnProperty.call(source, taskId)` 过滤；
- `pendingImageUploadCounts` 同样用 `for...in` + own-property guard；
- `task:` 前缀解析、`staleTaskIds` 收集、倒计时 timer clear 和 cache delete
  逻辑全部保持不变。

这样在常规 tab refresh cleanup 中避免为每个 cache object 创建临时 key array；
同时保持与 `Object.keys()` 一致的 own-enumerable 语义，不会把 prototype chain 上的
enumerable key 当作真实任务缓存删除。

行为边界：

- falsy cache object 继续被忽略；
- inherited enumerable key 继续不参与 stale 收集；
- `pendingImageUploadCounts.current` 继续被保留，因为没有 `task:` 前缀；
- stale own timer 仍会 `clearInterval` 后删除；
- `stopSharedTabCountdownTickerIfIdle()` 调用位置不变。

新增 `tests/test_vscode_task_local_cache_prune_own_keys_r537.py`：

- source invariant 锁定 prune 路径不再出现
  `Object.keys(source || {}).forEach` /
  `Object.keys(pendingImageUploadCounts || {}).forEach`；
- source invariant 锁定两个 `for...in` 路径都有 own-property guard；
- Node runtime test 构造带 inherited stale timer / inherited pending upload key 的
  cache object，验证只删除 own stale key，inherited key 仍可读但不参与 prune。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round64/01-mdn-object-keys-for-in-own.json`
  保存 MDN `Object.keys()` / `for...in` / `hasOwnProperty` 资料：`Object.keys()` 返回
  own enumerable string-keyed properties 的数组；`for...in` 会枚举 prototype chain，
  因此用 own-property guard 才能在避免数组分配的同时保持旧边界。

### 3.81 R538 · VS Code inline locale signature 去 map/join 中间数组

R20.13-E 给 `_getHtmlContent()` 增加了 `_cachedInlineAllLocalesJson`：
`safeJsonForInlineScript(allLocales)` 的结果按 locale 名 + entry 数量签名缓存。旧签名构造：

```ts
const localeNames = Object.keys(allLocales).sort();
const localeSignature = localeNames
  .map((n) => `${n}:${Object.keys(allLocales[n] || {}).length}`)
  .join("|");
```

这保留了正确的签名语义，但每次 `_getHtmlContent()` 都会为 `map()` 结果再创建一个
中间数组。R538 改成在已排序的 `localeNames` 上直接增量拼接：

```ts
let localeSignature = "";
for (let i = 0; i < localeNames.length; i += 1) {
  const name = localeNames[i];
  if (i > 0) localeSignature += "|";
  localeSignature += `${name}:${Object.keys(allLocales[name] || {}).length}`;
}
```

缓存 key 仍然由「排序后的 locale name + 对应 locale entry 数」组成，因此新增/移除
locale、或 locale entry 数变化时仍会让 inline all-locales JSON cache 失效。只去掉
`map().join()` 的临时 array。

行为边界：

- locale 名仍来自 `Object.keys(allLocales).sort()`；
- 每个 locale 仍读取 `Object.keys(allLocales[name] || {}).length`；
- signature 格式仍是 `name:count|name:count`；
- 空 locale 集合仍在后续 `localeNames.length === 0` 分支输出 `"null"`；
- `_cachedInlineAllLocalesKey` / `_cachedInlineAllLocalesJson` 的命中逻辑不变。

新增 `tests/test_vscode_inline_locale_signature_r538.py`：

- source invariant 锁定 `_getHtmlContent()` 使用 `for (let i = 0; ...` 构造
  `localeSignature`，不再出现旧的 `.map(...).join("|")`；
- Node runtime test 用乱序 `allLocales` 验证输出仍为
  `en:1|zh-CN:2|zh-TW:0`，即排序 + key count contract 不变。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round65/01-mdn-array-map-join.json`
  保存 MDN `Array.prototype.map()` / `join()` 资料：`map()` 会创建一个 callback
  结果新数组，`join()` 再把数组元素拼接为字符串。这里可在一次 loop 中生成同一
  signature 字符串，避免中间数组。

### 3.82 R539 · VS Code AppleScript injected env keys 单遍归一化

`AppleScriptExecutor.runAppleScript()` 在生成日志 / error details 用的
`injectedEnvKeys` 时，旧路径是：

```ts
const injectedEnvKeys = envExtra
  ? Object.keys(envExtra)
      .filter(Boolean)
      .map(k => String(k))
      .sort()
  : []
```

`Object.keys(envExtra)` 已经返回 own enumerable string key 数组；这里的
`filter(Boolean)` / `map(String)` 只是保留非空 key 与字符串化 contract，但会再创建
两个中间数组。R539 改为一次收集后排序：

```ts
const injectedEnvKeys: string[] = []
if (envExtra) {
  for (const key of Object.keys(envExtra)) {
    if (key) injectedEnvKeys.push(String(key))
  }
  injectedEnvKeys.sort()
}
```

行为边界：

- `envExtra` 仍只来自 object-like `runOptions.env`；
- key 来源仍是 `Object.keys(envExtra)`，因此只包含 own enumerable string keys；
- 空 key guard 保留；
- `String(key)` contract 保留；
- `sort()` 仍在收集后执行，日志 / diagnostic details 的稳定顺序不变。

新增 `tests/test_vscode_applescript_injected_env_keys_r539.py`：

- source invariant 锁定 `runAppleScript()` 使用单个 collection loop，不再出现
  `.filter(Boolean)` / `.map(k => String(k))`；
- Node runtime test 用乱序 env key 验证输出仍排序为
  `["FOO", "ZED", "__CFBundleIdentifier"]`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round66/01-mdn-array-filter-map-object-keys.json`
  保存 MDN `Array.prototype.filter()` / `map()` / `Object.keys()` 资料：`filter()`
  与 `map()` 都返回新数组，`Object.keys()` 返回对象自身 enumerable string-keyed
  properties 的数组；此处可在一个 loop 中保留同一 key 集合与排序 contract。

### 3.83 R540 · VS Code tab countdown shared ticker 去每秒 Object.keys 数组

R498 把每个任务一个 `setInterval` 收敛为页面共享 1Hz ticker；R536 又把 idle
check 从 `Object.keys(tabCountdownTimers).length` 改成 guarded `for...in`。剩余
热路径是 `tickAllTabCountdowns()` 本身：每秒执行一次，并在每次 tick 时创建
`Object.keys(tabCountdownTimers)` 数组后再 `forEach(tickTabCountdown)`。

R540 把 shared ticker 的枚举改为同样的 own-property guarded loop：

```js
function tickAllTabCountdowns() {
  for (const taskId in tabCountdownTimers) {
    if (Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)) {
      tickTabCountdown(taskId)
    }
  }
  stopSharedTabCountdownTickerIfIdle()
}
```

行为边界：

- tick 目标仍等价于旧 `Object.keys(tabCountdownTimers)`：只处理 own enumerable
  string keys；
- prototype 上的 inherited enumerable key 不会被 tick；
- `tickTabCountdown(taskId)` 仍负责 deadline 计算、hidden-page DOM 跳过、到期删除
  与 idle ticker stop；
- `stopSharedTabCountdownTickerIfIdle()` 仍在整轮 tick 后执行一次；
- 删除当前 task key 不影响后续 own task key 的 tick。

新增 `tests/test_vscode_tab_countdown_tick_all_own_keys_r540.py`，并更新
`tests/test_vscode_tab_countdown_shared_ticker_r498.py`：

- source invariant 锁定 `tickAllTabCountdowns()` 不再出现
  `Object.keys(tabCountdownTimers).forEach(...)`；
- runtime test 构造带 inherited timer 的 `tabCountdownTimers`，验证只 tick own keys，
  删除当前 own key 后仍继续 tick 后续 own key，并且 stop-idle hook 仍只调用一次。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round67/01-mdn-object-keys-for-in-hasown.json`
  保存 MDN `Object.keys()` / `for...in` / `hasOwnProperty` 资料：`Object.keys()` 返回
  own enumerable string-keyed properties 的数组；`for...in` 会遍历 prototype chain，
  因此 guarded `for...in` 可以在避免每秒 keys array 的同时保持旧 own-key 边界。

### 3.84 R541 · VS Code tab countdown visible resync 去 Object.keys 数组

R540 处理了共享 1Hz ticker；同一倒计时子系统里，`forceUpdateAllTabCountdowns()`
仍在 `visibilitychange` visible 边沿用：

```js
Object.keys(tabCountdownTimers).forEach(taskId => {
  // recompute + render
})
```

该路径不如 1Hz ticker 热，但用户从后台切回 webview 时会同步执行；任务数多时仍会为
一次 UI resync 分配完整 key 数组。R541 改为与 ticker 相同的 guarded `for...in`：

```js
for (const taskId in tabCountdownTimers) {
  if (!Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)) continue
  const state = tabCountdownTimers[taskId]
  if (!state || typeof state !== 'object') continue
  // recompute + render
}
```

行为边界：

- hidden tab 仍直接 return，不做 DOM lookup / render；
- visible resync 目标仍等价于旧 `Object.keys(tabCountdownTimers)`：只处理 own
  enumerable string keys；
- inherited enumerable key 不会触发 render；
- expired countdown 仍删除 `tabCountdownTimers[taskId]` / `tabCountdownRemaining[taskId]`
  并调用 idle stop check；
- 删除当前 key 后仍继续处理后续 own key。

新增 `tests/test_vscode_tab_countdown_force_update_own_keys_r541.py`，并更新
`tests/test_vscode_tab_countdown_hidden_dom_r500.py`：

- source invariant 锁定 `forceUpdateAllTabCountdowns()` 不再出现
  `Object.keys(tabCountdownTimers).forEach(...)`；
- runtime test 覆盖 hidden skip、inherited timer skip、expired timer prune、live timer
  render，以及删除当前 key 后继续处理后续 own key。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round68/01-mdn-object-keys-for-in-own.json`
  保存 MDN `Object.keys()` / `for...in` / `hasOwnProperty` 资料：`Object.keys()` 返回
  own enumerable string-keyed properties 的数组；guarded `for...in` 可保持 own-key
  边界，同时避免 visible resync 时创建 keys array。

### 3.85 R542 · VS Code tab countdown clear-all 去 Object.keys 数组

R540/R541 已经把 shared ticker 和 visible resync 的 `Object.keys(tabCountdownTimers)`
数组去掉；同一倒计时子系统里，`clearAllTabCountdowns()` 仍在全量清理时使用：

```js
Object.keys(tabCountdownTimers).forEach(taskId => {
  const entry = tabCountdownTimers[taskId]
  if (typeof entry === 'number') clearInterval(entry)
})
```

当前共享 ticker 模型下 `tabCountdownTimers[taskId]` 通常是 state object；但这个函数
仍保留了旧实现的 numeric interval cleanup 兼容分支。R542 将枚举改成 guarded
`for...in`，保留该兼容行为：

```js
for (const taskId in tabCountdownTimers) {
  if (!Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)) continue
  try {
    const entry = tabCountdownTimers[taskId]
    if (typeof entry === 'number') clearInterval(entry)
  } catch (e) {
    // 忽略
  }
}
```

行为边界：

- cleanup 目标仍等价于旧 `Object.keys(tabCountdownTimers)`：只处理 own enumerable
  string keys；
- inherited enumerable numeric timer 不会被 clear；
- own numeric legacy timer 仍会 `clearInterval(entry)`；
- own state object 不会误传给 `clearInterval`；
- shared `tabCountdownTickerTimer` 仍单独 clear 并置 `null`；
- `tabCountdownTimers` / `tabCountdownRemaining` 仍重置为空对象。

新增 `tests/test_vscode_tab_countdown_clear_all_own_keys_r542.py`，并更新
`tests/test_vscode_tab_countdown_shared_ticker_r498.py`：

- source invariant 锁定 `clearAllTabCountdowns()` 不再出现
  `Object.keys(tabCountdownTimers).forEach(...)`；
- runtime test 构造 inherited numeric timer、own numeric legacy timer、own state
  object、shared ticker 与 remaining cache，验证只 clear own numeric legacy timer +
  shared ticker，最后两个 cache 都重置为空对象。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round69/01-mdn-object-keys-for-in-cleanup.json`
  保存 MDN `Object.keys()` / `hasOwnProperty` 资料：`Object.keys()` 返回 own enumerable
  string-keyed properties 的数组；guarded `for...in` 可保持 cleanup 的 own-key 边界，
  同时避免 clear-all 时创建 keys array。

### 3.86 R543 · VS Code webview helper RGB parser 去 split/map/slice 数组

`webview-helpers.js` 的 `resolveThemeKind()` 在 class / `colorScheme` 都无法判断时，
会读取 body background color 并调用 `parseRgbColor()`。旧 parser 使用：

```js
const parts = match[1].split(',').map((part) => Number(part.trim()))
if (parts.length < 3 || parts.slice(0, 3).some((part) => !Number.isFinite(part))) {
  return null
}
return { r: parts[0], g: parts[1], b: parts[2] }
```

这会先为 `split()` 结果创建数组，再为 `map()` 结果创建数组，随后 `slice(0, 3)`
又复制前三项，只是为了验证和读取三个 RGB channel。R543 改为直接扫描括号内
字符串的前三个 comma-separated segment：

```js
const channels = []
const raw = match[1]
let start = 0
for (let i = 0; i <= raw.length && channels.length < 3; i += 1) {
  if (i < raw.length && raw[i] !== ',') continue
  const channel = Number(raw.slice(start, i).trim())
  if (!Number.isFinite(channel)) return null
  channels.push(channel)
  start = i + 1
}
if (channels.length < 3) return null
return { r: channels[0], g: channels[1], b: channels[2] }
```

行为边界：

- 仍只接受 `rgb(...)` / `rgba(...)` 且仍要求 comma-separated channel；
- 仍只用前三个 channel 计算 luminance，alpha / 额外 channel 保持忽略；
- 前三个 channel 中任一项无法转成 finite number 时返回 `null`；
- 少于三个 channel 返回 `null`；
- `resolveThemeKind()` 对 invalid background color 仍回退到
  `data-vscode-theme-kind` 或默认 dark。

新增 `tests/test_vscode_webview_helpers_parse_rgb_one_pass_r543.py`：

- source invariant 锁定 `parseRgbColor()` 不再出现 `.split()` / `.map()` /
  `.slice(0, 3)` / `.some()` pipeline；
- runtime test 经由 exported `resolveThemeKind()` 验证 light/dark luminance、rgba
  alpha ignored、额外 channel ignored、invalid channel fallback 到 existing theme kind。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round70/01-mdn-split-map-slice-some.json`
  保存 MDN `String.prototype.split()` / `Array.prototype.map()` /
  `Array.prototype.slice()` / `Array.prototype.some()` 资料：`split()`、`map()`、
  `slice()` 都会返回新数组；此处只需要前三个 channel，可用单次扫描避免这些
  中间数组。

### 3.87 R544 · VS Code webview UI RGB parser 去 split/map/every 数组

R543 处理了 `webview-helpers.js` 的 theme fallback RGB parser；`webview-ui.js`
里还有一个私有 `parseRgbColor()`，供 `isDarkBackground()` 判断 Lottie fallback
是否需要 invert。旧实现：

```js
const parts = s
  .slice(start + 1, end)
  .split(',')
  .map(p => p.trim())
if (parts.length < 3) return null

const r = Number(parts[0])
const g = Number(parts[1])
const b = Number(parts[2])
if (![r, g, b].every(n => Number.isFinite(n))) return null
```

这里除了 `split()` / `map()` 的中间数组，还会为 `[r, g, b].every(...)` 创建一个
三元素临时数组。R544 改为直接扫描前三个 comma-separated segment：

```js
const channels = []
const raw = s.slice(start + 1, end)
let partStart = 0
for (let i = 0; i <= raw.length && channels.length < 3; i += 1) {
  if (i < raw.length && raw[i] !== ',') continue
  const channel = Number(raw.slice(partStart, i).trim())
  if (!Number.isFinite(channel)) return null
  channels.push(channel)
  partStart = i + 1
}
if (channels.length < 3) return null
return { r: channels[0], g: channels[1], b: channels[2] }
```

行为边界：

- 仍只接受 `rgb(...)` / `rgba(...)` head；
- 仍只使用第一对括号内的前三个 comma-separated channel；
- alpha / 额外 channel 仍忽略；
- 前三个 channel 中任一项无法转成 finite number 时返回 `null`；
- 少于三个 channel 返回 `null`；
- 空 segment 仍按 JS `Number("") === 0` 兼容旧行为。

新增 `tests/test_vscode_webview_ui_parse_rgb_one_pass_r544.py`：

- source invariant 锁定私有 `parseRgbColor()` 不再出现 `.split()` / `.map()` /
  `[r, g, b].every(...)`；
- Node runtime test 直接抽取函数，覆盖 rgb、rgba、额外 channel、空 segment、
  invalid channel、少 channel 与非 rgb/rgba head。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round71/01-mdn-split-map-every.json`
  保存 MDN `String.prototype.split()` / `Array.prototype.map()` /
  `Array.prototype.every()` 资料：`split()` 和 `map()` 会返回新数组，`every()`
  是 predicate 遍历；此处只需要前三个 channel，可用一次扫描同时完成解析与
  finite 校验。

### 3.88 R545 · WebUI multi_task shared countdown ticker 去每秒 Object.keys 数组

R460 已把 WebUI 多任务倒计时从 N 个 per-task interval 收敛成页面共享
`tickAllTaskCountdowns()` 1Hz ticker。但 ticker 本身仍使用：

```js
Object.keys(taskCountdowns).forEach((taskId) => {
  tickTaskCountdown(taskId)
})
```

这在每秒 tick 时为所有 countdown id 创建 key array。R545 改成 guarded
`for...in`：

```js
for (const taskId in taskCountdowns) {
  if (!Object.prototype.hasOwnProperty.call(taskCountdowns, taskId)) continue
  tickTaskCountdown(taskId)
}
stopSharedTaskCountdownTickerIfIdle()
```

行为边界：

- tick 目标仍等价于旧 `Object.keys(taskCountdowns)`：只处理 own enumerable
  string keys；
- inherited enumerable key 不会触发 `tickTaskCountdown()`；
- 删除当前 task key 后仍继续处理后续 own key；
- `stopSharedTaskCountdownTickerIfIdle()` 仍在整轮 tick 后执行一次；
- `tickTaskCountdown()` 内部的 deadline 计算、hidden DOM skip、auto-submit 与
  idle stop 逻辑不变。

新增 `tests/test_multi_task_tick_all_own_keys_r545.py`，并更新
`tests/test_task_countdown_hidden_tab_r128.py`：

- source invariant 锁定 `tickAllTaskCountdowns()` 不再出现
  `Object.keys(taskCountdowns).forEach(...)`；
- runtime test 构造带 inherited countdown 的 `taskCountdowns`，验证只 tick own keys，
  删除当前 own key 后仍继续 tick 后续 own key，并且 idle-stop hook 仍只调用一次。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round72/01-mdn-object-keys-for-in-own.json`
  保存 MDN `Object.keys()` / `for...in` / `Object.hasOwn` 资料：`Object.keys()` 返回
  own enumerable string-keyed properties 的数组；`for...in` 会遍历 prototype chain，
  因此 guarded `for...in` 可以避免每秒 key array，同时保持旧 own-key 边界。

### 3.89 R546 · WebUI multi_task visible-resync 去 Object.keys 数组

R545 已经把 `tickAllTaskCountdowns()` 的 1Hz shared ticker 改成 guarded
`for...in`，但 `forceUpdateAllTaskCountdowns()` 仍在页面从 hidden 回到 visible
时使用：

```js
Object.keys(taskCountdowns).forEach((tid) => {
  const entry = taskCountdowns[tid]
})
```

这个路径不是每秒运行，但它位于可见边沿 resync：用户切回标签页时需要立刻同步
所有 countdown ring / number / active display。并发任务多时，先创建完整 key
array 再遍历没有必要。R546 改成：

```js
for (const tid in taskCountdowns) {
  if (!Object.prototype.hasOwnProperty.call(taskCountdowns, tid)) continue
  const entry = taskCountdowns[tid]
}
```

行为边界：

- 仍只刷新 own enumerable countdown keys，等价于旧 `Object.keys(taskCountdowns)`；
- inherited enumerable key 不会触发 `_getOrCacheCountdownDom()`、`_t()` 或
  `updateCountdownDisplay()`；
- `timer` 缺失 / 已停止的 own entry 仍跳过；
- hidden / 缺 `document` / 非 object `taskCountdowns` 的早返回不变；
- DOM cache helper、active task 主倒计时刷新和 defensive `try/catch` 不变。

新增 `tests/test_multi_task_force_update_own_keys_r546.py`，并更新
`tests/test_task_countdown_hidden_tab_r128.py`：

- source invariant 锁定 `forceUpdateAllTaskCountdowns()` 不再出现
  `Object.keys(taskCountdowns).forEach(...)`；
- runtime test 构造带 inherited countdown、stopped own countdown、active own
  countdown 的 `taskCountdowns`，验证只刷新 own running keys，active display 仍只为
  active task 更新一次。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round73/01-mdn-object-keys-for-in-own.json`
  保存 MDN `Object.keys()` / `for...in` / `hasOwnProperty` 资料：`Object.keys()` 返回
  own enumerable string-keyed properties 的数组；`for...in` 会枚举 prototype chain，
  因此必须 guarded 才能保持旧 own-key 边界，同时避免 visible-resync 的 key array。

### 3.90 R547 · WebUI multi_task idle-check 去 Object.keys().some 数组

R545/R546 已经把 countdown ticking 和 visible-resync 两个遍历点改成 guarded
`for...in`。剩下的 `hasRunningTaskCountdowns()` 仍使用：

```js
return Object.keys(taskCountdowns).some((tid) => {
  const entry = taskCountdowns[tid]
  return entry && entry.timer === TASK_COUNTDOWN_SHARED_TIMER_SENTINEL
})
```

`.some()` 本身有正确的 early-exit 语义，但 `Object.keys()` 会先为所有 own keys
创建数组。这个 helper 在 `_clearTaskCountdown()`、`tickTaskCountdown()` timeout
分支和 `stopSharedTaskCountdownTickerIfIdle()` 中用于判断页面级 ticker 是否可以停；
任务多时，最后一个任务清理前会反复做 idle check。R547 改成：

```js
for (const tid in taskCountdowns) {
  if (!Object.prototype.hasOwnProperty.call(taskCountdowns, tid)) continue
  const entry = taskCountdowns[tid]
  if (entry && entry.timer === TASK_COUNTDOWN_SHARED_TIMER_SENTINEL) return true
}
return false
```

行为边界：

- 仍只检查 own enumerable countdown keys，等价于旧 `Object.keys(taskCountdowns)`；
- inherited sentinel entry 不会让 idle check 误判为 running；
- 遇到第一个 running own entry 立即返回 `true`，保留 `.some()` 的 early-exit；
- 所有 own entries 都非 running 时返回 `false`；
- `stopSharedTaskCountdownTickerIfIdle()` 的 clearInterval / window mirror 清理逻辑不变。

新增 `tests/test_multi_task_has_running_own_keys_r547.py`：

- source invariant 锁定 `hasRunningTaskCountdowns()` 不再出现
  `Object.keys(taskCountdowns).some(...)`；
- runtime test 构造 inherited running entry、stopped own entry、running own entry 和
  after-running throwing getter，验证 inherited 被忽略且 running 命中后不读取后续 key。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round74/01-mdn-object-keys-array-some-for-in.json`
  保存 MDN `Array.prototype.some()`、`Object.keys()`、`for...in`、
  `hasOwnProperty` 资料：`.some()` 会在 callback 返回 truthy 时停止；`Object.keys()`
  返回 own enumerable string-keyed properties 的数组；`for...in` 会遍历 prototype
  chain，因此 guarded loop 可以保留 own-key 和 early-exit 语义，同时避免 key array。

### 3.91 R548 · WebUI keyboard shortcut parser 去 split/map 中间数组

`keyboard-shortcuts.js::parseShortcut()` 是所有 `KeyboardShortcuts.register()` /
`unregister()` 的入口。旧实现：

```js
const parts = shortcut.toLowerCase().split('+').map(p => p.trim())
for (const part of parts) {
  ...
}
```

这会先生成 `split('+')` 数组，再生成 `map(trim)` 数组。快捷键注册不是 1Hz 热路径，
但它是共享 registry API，Quick Phrases 等模块也会调用；解析逻辑很小，直接用
delimiter scan 更明确：

```js
const normalized = shortcut.toLowerCase()
for (let start = 0, i = 0; i <= normalized.length; i += 1) {
  if (i < normalized.length && normalized.charCodeAt(i) !== 43) continue
  const part = normalized.slice(start, i).trim()
  start = i + 1
  ...
}
```

行为边界：

- 仍先对完整 shortcut 做 `toLowerCase()`；
- 每段仍调用 `trim()`，保留 ` CTRL + Shift + SPACE ` 这类输入；
- `space` / `spacebar` 等 alias 仍归一到 canonical id；
- 多个 non-modifier token 仍是 last-key-wins（如 `ctrl + x + enter` → `ctrl+enter`）；
- trailing blank segment 仍会注册成旧行为的 blank key id（如 `ctrl+`）。

新增 `tests/test_keyboard_shortcuts_parse_one_pass_r548.py`：

- source invariant 锁定 `parseShortcut()` 不再出现 `.split('+')` / `.map(...)`；
- Node VM runtime test 通过真实 `KeyboardShortcuts.register()` / keydown dispatch
  验证 trim、alias、last-key-wins 和 trailing blank key 行为不变。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round75/01-mdn-split-map-trim.json`
  保存 MDN `String.prototype.split()`、`Array.prototype.map()`、`String.prototype.trim()`
  资料：`split()` 返回新数组，`map()` 创建新数组，`trim()` 返回去除两端空白的新字符串。
  R548 保留 `trim()` 语义，但避免为解析再创建两个中间数组。

### 3.92 R549 · WebUI Quick Phrases loadPhrases 单遍校验归一化

`quick_phrases.js::loadPhrases()` 是 Quick Phrases 的共享 storage reader：
render、CRUD、import merge、export 和 Alt+N shortcut activation 都会先读它。旧实现：

```js
return parsed.phrases
  .filter(function (p) {
    return p && typeof p === "object" && ...
  })
  .map(function (p) {
    return { id: p.id, label: p.label, ... }
  })
```

这会为同一份 storage payload 先创建 valid phrase 引用数组，再创建 normalized phrase
对象数组。R549 改成一个显式 result collector：

```js
var result = []
for (var i = 0; i < parsed.phrases.length; i += 1) {
  var p = parsed.phrases[i]
  if (!valid) continue
  result.push({ id: p.id, label: p.label, ... })
}
return result
```

行为边界：

- `schema_version` / `phrases` array 校验不变；
- invalid row 仍跳过，不让坏 localStorage 数据炸 UI；
- `created_at` / `last_used_at` / `use_count` 仍只接受 finite number，否则兜底 0；
- 返回对象仍只暴露 6 个规范字段，忽略多余字段；
- valid phrase 顺序不变，后续 `_sortPhrasesByUsage()` 仍只在 render/shortcut 路径负责排序。

新增 `tests/test_quick_phrases_load_one_pass_r549.py`：

- source invariant 锁定 `loadPhrases()` 不再出现 `.filter(function (p)` /
  `.map(function (p)` 链；
- Node VM runtime test 通过真实 `AIIA_QUICK_PHRASES.loadPhrases()` 验证 mixed storage
  payload 的过滤、默认值、额外字段剥离和顺序保持。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round76/01-mdn-filter-map-new-arrays.json`
  保存 MDN `Array.prototype.filter()` / `Array.prototype.map()` 资料：`filter()` 会创建
  shallow copy，`map()` 会创建新数组。R549 把两段数组构造收敛为一个 result array。

### 3.93 R550 · WebUI Quick Phrases deletePhrase no-op path 延迟 filter array

`quick_phrases.js::deletePhrase(id)` 的常见失败路径是用户重复点击删除、快捷键 /
UI 状态竞态，或测试 / 调试 API 传入一个已经不存在的 id。旧实现无论是否命中都会先：

```js
var filtered = phrases.filter(function (p) {
  return p.id !== id
})
if (filtered.length === phrases.length) return false
```

这让 id 不存在的 no-op 路径也分配一个完整 shallow copy。R550 改为 lazy result
collector：扫描到第一个命中项时才 `phrases.slice(0, i)` 复制前缀，后续只 push
非命中项；如果扫描完没有命中，直接 `return false`，不写 storage、不触发 render。

行为边界：

- id 不存在时仍返回 `false`，并且不调用 `savePhrases()`；
- id 存在时仍调用一次 `savePhrases()`，成功后 `renderList()`；
- corrupted / 手工编辑 storage 出现重复 id 时，仍删除所有 `id === id` 的项；
- surviving phrases 的相对顺序和 normalized 字段保持不变；
- `loadPhrases()` 的 schema 校验、默认值和字段剥离仍是唯一入口，delete path 不扩张
  storage 语义。

新增 `tests/test_quick_phrases_delete_lazy_filter_r550.py`：

- source invariant 锁定 `deletePhrase()` 不再使用 `.filter(function (p)`，并包含
  `filtered === null` / `phrases.slice(0, i)` / `filtered.push(p)`；
- Node VM runtime test 验证 missing id 路径返回 `false`、Quick Phrases
  `STORAGE_KEY` 写入计数为 0、storage payload 不被重写；
- Node VM runtime test 验证重复 id 会一次保存并删除所有重复项，只保留中间的
  survivor，顺序不变。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round77/01-mdn-array-filter-exa.json`
  保存 MDN `Array.prototype.filter()` 资料：`filter()` 会创建 shallow copy，调用
  callback 处理数组元素，并构造包含 truthy 结果的新数组。R550 只在发现删除目标后
  才构造 survivor array，避免 no-op 路径的整数组复制。

### 3.94 R551 · WebUI notification new_tasks 延迟 truthy taskIds array

`notification-manager.js::notifyNewTasks(event)` 是 WebUI 新任务事件的通知入口。
旧实现先对 `event.taskIds` 做完整 truthy copy：

```js
const taskIds = Array.isArray(taskIdsRaw) ? taskIdsRaw.filter(Boolean) : []
const count = finiteCountRaw ? Math.floor(countRaw) : taskIds.length
```

但这个路径的核心需求只有三个标量：truthy id 数量、单任务消息里的第一个 id，以及
成功返回值里的 filtered `taskIds`。R551 改成 lazy collector：

```js
let taskIds = null
let taskIdCount = 0
for (...) {
  if (!(i in taskIdsRaw)) continue
  if (taskId) {
    if (taskIds === null) taskIds = []
    taskIds.push(taskId)
    taskIdCount += 1
  }
}
```

这样 no-op 路径（没有 truthy id 且没有正数 `count`）不再分配 `[]`，同时避免
`filter(Boolean)` 的 callback dispatch 和中间 shallow-copy 语义；成功通知路径仍在需要
返回 `taskIds` 时构造同等 filtered array。

行为边界：

- `countRaw` 仍只接受 finite number，并继续 `Math.max(0, Math.floor(countRaw))`；
- `countRaw` 缺失时，count 仍等价于 `taskIdsRaw.filter(Boolean).length`；
- sparse array 语义通过 `i in taskIdsRaw` 保持与 `filter()` 一致；
- 单 truthy id 时仍返回 `New task added: <id>`；
- `config.enabled === false` 和 `count <= 0` 仍提前返回 `null`；
- 成功返回对象仍包含 `{ title, message, count, taskIds }`，其中 `taskIds` 是 truthy ids
  的原值数组。

新增 `tests/test_notification_new_tasks_lazy_ids_r551.py`：

- source invariant 锁定 `notifyNewTasks()` 不再出现 `.filter(Boolean)`，并包含
  lazy `taskIds === null` collector；
- Node VM runtime test 验证 mixed truthy/falsy ids 的 count、visual hint、sound 和
  返回 `taskIds`；
- Node VM runtime test 验证 sparse array 只保留实际 truthy id，单任务消息不变；
- Node VM runtime test 验证 finite `count` override 与空 truthy ids 共存时仍返回
  count override 和 `taskIds: []`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round78/01-mdn-array-filter-boolean-exa.json`
  保存 MDN `Array.prototype.filter()` 资料：`filter()` 会创建 shallow copy，callback
  对元素返回 truthy 才保留，并构造新数组。R551 用显式标量计数 + lazy array 构造保留
  truthy 语义，同时减少 ignored/no-op 新任务事件路径上的数组分配。

### 3.95 R552 · WebUI notification fallback events 有界 tail collector

`notification-manager.js` 的 fallback event 记录和 localStorage cleanup 都是异常 / 降级路径，
但它们正好容易在通知权限失败、AudioContext 失败、存储配额接近上限时重复触发。旧实现先保留
全部 recent events，再用 `splice()` 截断：

```js
const validEvents = events.filter(e => e.timestamp > sevenDaysAgo)
validEvents.push(event)
if (validEvents.length > 50) {
  validEvents.splice(0, validEvents.length - 50)
}
```

`cleanupLocalStorage()` 也有同形的 `filter(...).splice(...)`，只保留最近 20 条。
R552 抽出 `_collectRecentFallbackEvents(events, cutoffTimestamp, maxEvents)`：

```js
const kept = []
for (let i = events.length - 1; i >= 0; i -= 1) {
  if (!(i in events)) continue
  const event = events[i]
  if (event.timestamp > cutoffTimestamp && kept.length < maxEvents) {
    kept.push(event)
  }
}
kept.reverse()
return kept
```

这样结果数组从一开始就是 bounded tail：record 路径最多收集 49 条旧 valid events，
再 append 新 event；cleanup 路径最多收集 20 条 recent events。不再创建可能远大于最终
上限的 intermediate filtered array，也不再需要对 survivor array 做前缀 `splice()`。

行为边界：

- `recordFallbackEvent()` 仍保留 7 天内事件，并最终最多写入 50 条；
- 新 event 仍追加在末尾，含 `type` / `data` / `timestamp` / `userAgent` / `url`；
- `cleanupLocalStorage()` 仍只保留 24 小时内事件，并最终最多 20 条；
- 返回顺序仍是原 storage 顺序里的最后 N 条 valid/recent events；
- sparse array holes 仍跳过，匹配 `filter()` 对 empty slots 的行为；
- storage payload 不是 array 或存在 `null.timestamp` 这类坏 entry 时，仍走 catch，
  最终 fallback 到清空 `ai-intervention-fallback-events`。

新增 `tests/test_notification_fallback_events_bounded_r552.py`：

- source invariant 锁定 `recordFallbackEvent()` / `cleanupLocalStorage()` 不再出现
  `events.filter(e => e.timestamp...)` 和 prefix `splice(0, ...)`；
- Node VM runtime test 验证 record path 从 55 条 valid 旧事件里保留 `e6..e54`
  加新 event，共 50 条；
- Node VM runtime test 验证 cleanup path 从 25 条 recent 里保留 `recent5..recent24`；
- Node VM runtime test 验证 malformed `null` entry 仍触发 defensive clear。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round79/01-mdn-array-filter-splice-exa.json`
  保存 MDN `Array.prototype.filter()` / `Array.prototype.splice()` 资料：`filter()` 会创建
  shallow copy 并构造新数组，`splice()` 会原地改变数组并返回被删除元素数组。R552 用
  bounded tail collector 一次构造最终 survivor array，避免先建大数组再裁剪。

### 3.96 R553 · WebUI image-upload removeImage 单遍 lazy survivor

`image-upload.js::removeImage(imageId)` 是用户点击图片预览删除按钮和取消 pending
上传时都会走到的路径。旧实现先找要释放的 blob URL，再完整过滤数组：

```js
const imageToRemove = selectedImages.find((img) => img.id == imageId)
...
selectedImages = selectedImages.filter((img) => img.id != imageId)
```

这意味着命中路径至少扫描两遍；missing-id no-op 也会创建一份和原数组等价的新数组。
R553 抽出 `prepareImageRemoval(imageId)`，用一次循环构造 lazy survivor：

```js
let nextImages = null
let imageToRemove = null
for (...) {
  if (image.id == imageId) {
    if (imageToRemove === null) imageToRemove = image
    if (nextImages === null) nextImages = selectedImages.slice(0, i)
  } else if (nextImages !== null) {
    nextImages.push(image)
  }
}
```

只有找到第一个匹配项时才复制前缀；完全找不到 id 时返回 `null`，`selectedImages`
引用不变，仍继续尝试删除同 id preview DOM 并更新 counter / visibility。

行为边界：

- 仍使用 loose `==` 匹配，保留旧 DOM string id 与 numeric internal id 的兼容；
- 仍只 revokes 第一个匹配 image 的 blob preview URL；
- corrupted / 手工篡改状态出现重复 id 时，仍移除所有匹配 id 的 selected images；
- missing id 仍会尝试移除 `preview-${imageId}` DOM 并刷新 counter/visibility；
- async failure cleanup 里的 strict `!==` 路径本轮不改，避免改变错误路径异常时序。

新增 `tests/test_image_upload_remove_lazy_r553.py`：

- source invariant 锁定 `removeImage()` 不再出现 `.find((img) => img.id == imageId)` /
  `.filter((img) => img.id != imageId)`，并包含 lazy `nextImages` collector；
- Node VM runtime test 验证 missing-id 删除不替换 `selectedImages` array reference、
  不 revoke blob URL、现有 preview 仍存在；
- Node VM runtime test 验证重复 id 仍全部移除，但只 revoke 第一张图的 blob URL，
  匹配旧 `find()` + `filter()` 组合语义。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round80/01-mdn-array-filter-find-splice-exa.json`
  保存 MDN `Array.prototype.filter()` 资料：`filter()` 会创建 shallow copy、调用 callback
  并构造新数组，且 sparse empty slots 不参与 callback。R553 对 packed `selectedImages`
  用 lazy survivor collector 避免 no-op array copy，并把命中路径从 find+filter 两次
  callback traversal 收敛为一次循环。

### 3.97 R554 · WebUI image-upload failure cleanup 复用 strict lazy removal

R553 只优化了用户主动删除图片的 loose-id path；`addImageToList()` 的 active failure
catch 里仍有一组 strict-id `find()` + `filter()`：

```js
const failed = selectedImages.find((img) => img.id === imageId)
...
selectedImages = selectedImages.filter((img) => img.id !== imageId)
```

这个分支在压缩 / 解码失败时触发，通常只处理 1 个 pending image，但在低端设备、坏图片、
Canvas 失败或浏览器解码异常时会集中出现。R554 将 R553 的 helper 泛化为
`prepareImageRemoval(imageId, strictId = false)`：

```js
const matches = strictId ? image.id === imageId : image.id == imageId
```

failure cleanup 调用 `prepareImageRemoval(imageId, true)`，继续保留旧 `===` / `!==`
contract，同时把 active failure path 的两次 callback traversal 收敛为一次 lazy survivor
循环。`removeImage()` 仍走默认 loose matching。

行为边界：

- cleared / cancelled pending image 仍在 catch 开头通过 `isImageItemActive()` 安静返回；
- active failure 仍记录 `console.error`，并用 `status.imageError` 提示用户；
- preview DOM 仍按 `preview-${imageId}` 删除；
- strict id matching 保持不变：numeric id 与 string lookalike id 不互相删除；
- 如果失败前已经有 blob preview URL，仍只 revoke 第一条 strict match 的 URL；
- helper default 仍是 loose id，R553 的手动删除语义不变。

新增 `tests/test_image_upload_failure_cleanup_lazy_r554.py`：

- source invariant 锁定 `addImageToList()` 不再出现 strict `selectedImages.find(...)`
  / `selectedImages.filter(...)` 清理，并确认使用 `prepareImageRemoval(imageId, true)`；
- Node VM runtime test 验证 active compression failure 会移除 preview、清空 selected
  item、保留 error/status 行为；
- Node VM runtime test 构造 numeric id + string-lookalike id，验证 failure cleanup 只移除
  strict numeric match，保留旧 `!==` contract。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round81/01-mdn-array-filter-find-exa.json`
  保存 MDN `Array.prototype.filter()` 资料：`filter()` 会创建 shallow copy、调用 callback
  并构造新数组。R554 在 active failure path 避免为最终删除结果先构造完整 filtered
  array，同时去掉单独 `find()` callback pass。

### 3.98 R555 · WebUI keyboard task-tab active index 单遍查找

`keyboard-shortcuts.js` 的 Tab / Shift+Tab 任务切换快捷键每次都会从
`querySelectorAll('.task-tab:not(.hidden)')` 得到 visible tab NodeList，然后用：

```js
const currentIndex = Array.from(tabs).findIndex(
  tab => tab.classList.contains('active')
)
```

这会先把 NodeList materialize 成临时数组，再由 `findIndex()` 扫描 active tab。
R555 新增 `getActiveTaskTabIndex(tabs)`，直接按 index 扫描 NodeList：

```js
for (let i = 0; i < tabs.length; i += 1) {
  if (tabs[i].classList.contains('active')) return i
}
return -1
```

Tab 和 Shift+Tab 两条快捷键路径复用该 helper，避免每次键盘切换任务时创建临时
array，并保留旧 `findIndex()` 的 `-1` no-active 语义。

行为边界：

- visible task tab 仍来自同一个 `.task-tab:not(.hidden)` selector；
- active tab 命中后仍返回第一个 active index；
- 没有 active tab 时仍返回 `-1`，因此 Tab wrap 到第一个 tab；
- Shift+Tab 在没有 active tab 且有 4 个 tab 时仍按旧公式点击 index 2；
- 只有 1 个 visible tab 时仍不 click，但快捷键管理器仍会先 prevent default；
- WebUI 静态 JS 无 repo ESLint target，本轮用 `node --check` 做语法验证。

新增 `tests/test_keyboard_shortcuts_task_tab_index_r555.py`：

- source invariant 锁定 `registerDefaults()` 不再出现
  `Array.from(tabs).findIndex(...)`，并确认 helper 使用 `for` + `tabs.length`
  单遍扫描；
- Node VM runtime test 验证 forward / backward tab switching、no-active forward /
  backward wrap、single-tab no-click，以及既有 preventDefault contract。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round82/01-mdn-array-from-findindex-exa.json`
  保存 MDN `querySelectorAll()` / `NodeList` / `findIndex()` 资料：`querySelectorAll()`
  返回 non-live NodeList，NodeList 可用 index 访问也可用 `Array.from()` 转成真实数组；
  `findIndex()` 逐项调用 callback 直到命中并在无命中时返回 `-1`。R555 保留 `-1`
  fallback，同时跳过 NodeList→Array 的 materialization。
- `/tmp/smart-search-evidence/aiia-optimization-round82/02-mdn-array-from-exa.json`
  保存 MDN array construction 资料，用于支持避免临时数组分配的分析背景。

### 3.99 R556 · VS Code webview clipboard image collection 去 Array.from 中间数组

`packages/vscode/webview-helpers.js::collectImageFilesFromClipboard()` 是 VS Code
webview paste 图片入口的共享 helper。旧实现会先 materialize clipboard list：

```js
const items = Array.from(clipboardData.items || [])
...
const clipboardFiles = Array.from(clipboardData.files || [])
```

然后再扫描 item/file，寻找 image MIME、调用 `getAsFile()`、按
`name/type/size/lastModified` 去重。R556 增加 `forEachClipboardEntry(collection,
callback)`：

```js
const iterator =
  typeof Symbol !== 'undefined' ? collection[Symbol.iterator] : null
if (typeof iterator === 'function') {
  for (const entry of collection) callback(entry)
  return
}
const length = Number(collection.length)
for (let i = 0; i < length; i += 1) callback(collection[i])
```

这样 `DataTransferItemList` / `FileList` 支持 iterable 时直接流式扫描；不支持
iteration 的 array-like 宿主对象仍按 length/index 扫描。`collectImageFilesFromClipboard()`
继续优先使用 `items`，只有没有收集到任何 image file 时才 fallback 到
`clipboardData.files`。

行为边界：

- `clipboardData` 缺失仍返回 `[]`；
- item path 仍只接受 `kind === 'file'` 且 `type` 以 `image/` 开头的 item；
- `getAsFile()` 缺失或返回 `null` 时仍不会 push；
- item path 收到至少一张 image 时，仍不会读取 fallback `files`；
- 没有 item image 时仍扫描 `clipboardData.files`；
- duplicate image file key 仍只保留第一份；
- iterable-only collection 和 length/index array-like collection 都继续支持。

新增 `tests/test_vscode_webview_helpers_clipboard_one_pass_r556.py`：

- source invariant 锁定 helper 和 collector 不再出现 `Array.from(`，并确认同时支持
  iterator path 与 indexed path；
- Node runtime test 验证 item path 优先、text item 跳过、duplicate key 去重、
  fallback files 不被混入；
- Node runtime test 验证 iterable-only item collection、`getAsFile() === null`
  后 fallback 到 files，以及 fallback duplicate suppression。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round83/01-mdn-clipboard-data-transfer-exa.json`
  保存 MDN DataTransfer / DataTransferItem 资料：`items` 是 DataTransferItemList，
  file item 通过 `getAsFile()` 取 File，`files` 是 FileList，MDN 示例直接遍历
  `ev.dataTransfer.items`。
- `/tmp/smart-search-evidence/aiia-optimization-round83/02-mdn-array-from-exa.json`
  保存 MDN `Array.from()` 资料：`Array.from()` 会从 iterable 或 array-like 创建新的
  shallow-copied Array instance。R556 保留同一扫描语义，但去掉 clipboard paste hot
  path 上的两个临时 array 分配。

### 3.100 R557 · WebUI image-upload paste clipboard collection 去 Array.from 中间数组

R556 处理了 VS Code webview helper，同一类 paste hot path 在 WebUI
`image-upload.js::initializePasteFunction()` 里仍存在：

```js
const items = Array.from(clipboardData.items || [])
...
const files = Array.from(clipboardData.files || [])
```

这个分支只在反馈文本框聚焦时处理图片粘贴，但它是用户直接交互路径；桌面截图、
移动端图片、富文本编辑器复制图片时都会触发。R557 在 `image-upload.js` 顶层增加
同形 `forEachClipboardEntry(collection, callback)`：

```js
if (typeof iterator === "function") {
  for (const entry of collection) callback(entry)
  return
}
const length = Number(collection.length)
for (let i = 0; i < length; i += 1) callback(collection[i])
```

paste handler 的 items path 和 files fallback path 都改为直接扫描 clipboard list，
不再先构造临时 array。数据 URI fallback、文本粘贴 `preventDefault()` 判断、上传
数量限制和 `addImageToList()` 时序保持不变。

行为边界：

- 仍只在 `document.activeElement === feedback-text` 时处理；
- item path 仍优先，只接受 `kind === "file"` 且 `type.startsWith("image/")`；
- item path 收到 image file 后仍不读取 `clipboardData.files`，避免同一张图片重复添加；
- item path 没有 image 时仍 fallback 到 `clipboardData.files`；
- `getAsFile()` 返回 `null` 时仍不 push，并允许 fallback files path 接管；
- clipboard 同时带文本时仍不 `preventDefault()`，让文字正常进入 textarea；
- 没有 pasted text 或纯 data URI fallback 时仍 `preventDefault()`。

新增 `tests/test_image_upload_paste_clipboard_one_pass_r557.py`：

- source invariant 锁定 `initializePasteFunction()` 不再出现
  `Array.from(clipboardData.items/files)`，并确认 helper 同时支持 iterator 和
  length/index array-like collection；
- Node VM runtime test 验证 item path 优先、跳过 text item、不会读取 fallback
  `files` getter、无文本图片粘贴仍 preventDefault；
- Node VM runtime test 验证 iterable-only items、`getAsFile() === null` 后 fallback
  到 files，并且带普通文本时保留默认文本粘贴。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round84/01-mdn-clipboard-event-data-transfer-exa.json`
  保存 MDN ClipboardEvent / Clipboard API 资料：paste event 通过
  `ClipboardEvent.clipboardData` 暴露 DataTransfer，剪贴板可包含文本、HTML 和图片
  等多种 MIME 数据。
- `/tmp/smart-search-evidence/aiia-optimization-round84/02-mdn-array-from-exa.json`
  保存 MDN `Array.from()` 资料：`Array.from()` 会从 iterable 或 array-like 创建新的
  shallow-copied Array instance。R557 保留原扫描顺序和 fallback contract，但去掉
  WebUI 图片粘贴路径的两个临时 array。

### 3.101 R558 · Service Worker activate 旧 cache 清理单遍 promise collector

`notification-service-worker.js` 的 `activate` 阶段会清理旧版本
`aiia-static-*` 与 `aiia-offline-*` cache，旧实现是：

```js
await Promise.all(
  cacheNames
    .filter(name => /* stale aiia cache */)
    .map(name => caches.delete(name).catch(() => false))
)
```

这个路径通常只在 SW 升级时运行，但它是存储回收和新版本接管的关键路径。R558
把 filter + map 两段 array pipeline 改成单遍 promise collector：

```js
const deletions = []
for (const name of cacheNames) {
  if (/* stale aiia cache */) {
    deletions.push(caches.delete(name).catch(() => false))
  }
}
await Promise.all(deletions)
```

这样不再先构造 stale cache name array，再构造 delete promise array；最终只保留
`Promise.all()` 实际需要的 delete promise list。

行为边界：

- 仍调用 `caches.keys()` 枚举 CacheStorage；
- 仍只删除 string cache name；
- 仍删除 `aiia-static-*` 且 `name !== STATIC_CACHE_NAME` 的旧 static cache；
- 仍删除 `aiia-offline-*` 且 `name !== OFFLINE_CACHE_NAME` 的旧 offline cache；
- 仍保留当前 static/offline cache 和外部非 AIIA cache；
- 单个 `caches.delete()` reject 仍通过 `.catch(() => false)` fail-soft；
- `caches.keys()` 失败仍被外层 catch 吞掉，不阻塞 `clients.claim()`。

新增 `tests/test_service_worker_activate_cleanup_one_pass_r558.py`：

- source invariant 锁定 activate listener 不再出现 `.filter(` /
  `.map(name => caches.delete...)`，并包含 `const deletions = []`、
  `for (const name of cacheNames)`、`await Promise.all(deletions)`；
- Node VM runtime test 验证只删除旧 `aiia-static-v1` / `aiia-offline-v0`，保留当前
  `aiia-static-v2` / `aiia-offline-v1`、foreign cache 和非 string entry，并仍调用
  `clients.claim()`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round85/01-mdn-array-filter-map-exa.json`
  保存 MDN `Array.prototype.filter()` / `map()` 资料：`filter()` 创建 shallow copy，
  `map()` 创建新数组。R558 去掉 activate cleanup 里的两段中间数组。
- `/tmp/smart-search-evidence/aiia-optimization-round85/02-mdn-cache-storage-exa.json`
  保存 MDN CacheStorage 资料：`keys()` 返回 cache name array，`delete(cacheName)`
  删除指定 cache 并返回 Promise；MDN 也把 cache cleanup 放在 service worker
  `activate` 的 `event.waitUntil()` 流程中。

### 3.102 R559 · Service Worker trimCache FIFO 淘汰单遍 promise collector

`notification-service-worker.js` 的 `trimCache(cache)` 会在静态资源 cache 超过
`MAX_ENTRIES` 后异步 FIFO 淘汰最早写入的 entry。旧实现先 `slice()` 出 overflow
前缀，再 `map()` 成 delete promise：

```js
const toDelete = keys.slice(0, keys.length - MAX_ENTRIES)
await Promise.all(toDelete.map(req => cache.delete(req).catch(() => false)))
```

`cache.keys()` 已经返回完整 key array；此处再复制 overflow prefix 会在 cache
接近上限且持续写入时制造额外短命数组。R559 改成根据 overflow 数量直接单遍收集
`Promise.all()` 需要的 delete promise：

```js
const deletions = []
const overflowCount = keys.length - MAX_ENTRIES
for (let i = 0; i < overflowCount; i += 1) {
  deletions.push(cache.delete(keys[i]).catch(() => false))
}
await Promise.all(deletions)
```

行为边界：

- `cache.keys()` 失败仍直接 return，不影响 stale-while-revalidate 响应；
- 非 array 或 `keys.length <= MAX_ENTRIES` 仍 no-op；
- 仍依赖 Cache API 的 key 返回顺序做 FIFO 近似淘汰；
- 仍删除 `keys[0 ... overflowCount - 1]`，保留最后 `MAX_ENTRIES` 条；
- 单个 `cache.delete()` reject 仍通过 `.catch(() => false)` fail-soft；
- 仍等待全部 delete promise settle 后完成 trim。

新增 `tests/test_service_worker_trim_cache_one_pass_r559.py`：

- source invariant 锁定 `trimCache()` 不再出现
  `keys.slice(0, keys.length - MAX_ENTRIES)` / `.map(req => cache.delete...)`，
  并包含 `overflowCount`、显式 loop 和 `await Promise.all(deletions)`；
- Node VM runtime test 验证 `MAX_ENTRIES + 3` 个 key 时只删除最早 3 个 entry，
  且中间一次 `cache.delete()` reject 仍被吞掉；
- Node VM runtime test 验证刚好 `MAX_ENTRIES` 个 key 时不调用 `cache.delete()`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round86/01-mdn-array-slice-map-exa.json`
  保存 MDN `Array.prototype.slice()` / `map()` 资料：`slice()` 返回 shallow copy，
  `map()` 创建新数组。R559 去掉 trimCache overflow prefix copy 和 map promise array。
- `/tmp/smart-search-evidence/aiia-optimization-round86/02-mdn-cache-keys-delete-exa.json`
  保存 MDN Cache API 资料：`Cache.keys()` 返回 Request key array，`Cache.delete()`
  返回 Promise；R559 保持原 FIFO 删除目标，只减少中间数组分配。

### 3.103 R560 · WebUI Lottie fallback SVG handoff 去 Array.from 中间数组

`app.js::initHourglassAnimation()` 在 Lottie runtime 加载完成后，会先把容器内
的 SVG fallback 淡出，再在 Lottie `DOMLoaded` 或 2s timeout 后删除 fallback。
旧实现：

```js
const fallbackSvgs = Array.from(container.querySelectorAll("svg"))
...
fallbackSvgs.forEach((s) => {
  _removeElement(s)
})
```

`querySelectorAll("svg")` 已经返回按 document order 排列的静态 NodeList。这里既
不需要 array 方法链，也不需要修改集合本身；复制成 Array 只是为了 `length` 和
`forEach()`。R560 直接保留 NodeList，并缓存 count 后用 index loop 删除：

```js
const fallbackSvgs = container.querySelectorAll("svg")
const fallbackSvgCount = fallbackSvgs.length
...
for (let i = 0; i < fallbackSvgCount; i += 1) {
  _removeElement(fallbackSvgs[i])
}
```

行为边界：

- 首屏仍先渲染 SVG fallback；
- `prefers-reduced-motion`、`IntersectionObserver`、`requestIdleCallback` gate 不变；
- 有 fallback SVG 时仍先把容器 opacity 设为 `0` 并设置 transition；
- Lottie 创建成功后仍等待 `DOMLoaded` 删除 fallback，并在下一帧恢复 opacity；
- 2s timeout fallback 删除路径仍保留；
- `_removeElement()` 仍兼容 `element.remove()` 和 `parentNode.removeChild()`。

新增 `tests/test_app_lottie_fallback_svg_nodelist_r560.py`：

- source invariant 锁定 `initHourglassAnimation()` 不再出现
  `Array.from(container.querySelectorAll("svg"))` / fallback `.forEach()`，
  并包含 `fallbackSvgCount` 与 indexed loop；
- Node VM runtime test 使用没有 `forEach` 的 indexed NodeList-like collection，
  验证 Lottie handoff 前仍淡出 fallback，`DOMLoaded` 后按 index 删除全部 fallback
  SVG，并恢复 opacity。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round87/01-mdn-queryselectorall-nodelist-exa.json`
  保存 MDN `querySelectorAll()` / `NodeList` 资料：`querySelectorAll()` 返回 static
  NodeList，元素按 document order 排列；NodeList 可用 `length` 和 index/loop 访问。
- `/tmp/smart-search-evidence/aiia-optimization-round87/02-mdn-array-from-exa.json`
  保存 MDN `Array.from()` 资料：`Array.from()` 会从 iterable 或 array-like 创建新的
  shallow-copied Array instance。R560 去掉 Lottie handoff 中这次短命 array copy。

### 3.104 R561 · WebUI image-upload FileList 批处理去 Array.from/slice/map

`image-upload.js::handleFileUpload(files)` 是文件选择和拖拽上传共用的图片入口。
旧实现一开始把 `FileList` 复制成完整 array，随后每批再 `slice()` 出小数组并
`map()` 成 promise：

```js
const fileArray = Array.from(files)
...
const batch = fileArray.slice(i, i + maxConcurrent)
const batchPromises = batch.map(async (file) => { ... })
```

图片本身才是大对象，但在多图上传路径上，额外复制 `FileList`、每批复制 batch、
再映射 promise array 都是可避免的短命分配。R561 直接读取 `files.length`，按
index 构造每批最多 3 个 promise：

```js
const fileCount = files.length
...
const batchEnd = Math.min(i + maxConcurrent, fileCount)
const batchPromises = []
for (let j = i; j < batchEnd; j += 1) {
  const file = files[j]
  batchPromises.push((async () => { ... })())
}
await Promise.all(batchPromises)
```

行为边界：

- 仍以 3 个文件为上限并发处理；
- 仍在多文件时显示 `status.processingBatch`；
- 每个文件完成后仍更新 `status.processProgress`；
- 批次之间仍保留 50ms delay，避免连续图片处理阻塞 UI；
- `updateImagePreviewVisibility()` 仍只在全部处理后调用一次；
- 多文件最终仍显示 `status.batchComplete`；
- 单文件仍根据 `files[0].name` 显示成功/失败消息。

新增 `tests/test_image_upload_filelist_batch_one_pass_r561.py`：

- source invariant 锁定 `handleFileUpload()` 不再出现 `Array.from(files)`、
  `fileArray`、batch `slice()` 或 batch `map(async...)`，并包含 `fileCount`、
  `batchEnd` 与 indexed loop；
- Node VM runtime test 使用只有 `length` 和数字 index 的 FileList-like object，
  验证第一批只启动 3 个文件，触发 50ms delay 后才启动剩余文件，进度/最终状态不变；
- Node VM runtime test 验证单文件路径直接读取 `files[0]` 并保持成功状态消息。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round88/01-mdn-filelist-exa.json`
  保存 MDN File API 资料：`HTMLInputElement.files` 返回 `FileList`；File API
  示例直接用 `files[0]`、`files.length` 和 `for...of` 访问用户选择文件。
- `/tmp/smart-search-evidence/aiia-optimization-round88/02-mdn-array-from-exa.json`
  保存 MDN `Array.from()` 资料：`Array.from()` 会从 iterable 或 array-like 创建新的
  shallow-copied Array instance。R561 去掉文件上传入口的完整 FileList copy 和每批
  `slice()` 中间数组。

### 3.105 R562 · VS Code notification diagnostic array stringification helper

`packages/vscode/notification-providers.ts` 的 `execFileAsyncWithOutput()` /
`execFileAsync()` 错误路径会把 `args` 写入诊断 details；`_extractAppleScriptError()`
也会把 `details.injectedEnvKeys` 标准化为 string array。旧代码在 4 个位置内联
`Array.isArray(...)? ... .map(String) : []`：

```ts
args: Array.isArray(args) ? args.map(String) : []
...
? (details.injectedEnvKeys as unknown[]).map(String)
```

这些路径不是高频成功路径，但它们是失败诊断热路径；重复写法也容易让后续新增
diagnostic array 时继续复制 `map(String)`。R562 抽出单一 helper：

```ts
function stringifyArrayValues(values: unknown): string[] {
  if (!Array.isArray(values)) return []
  const out: string[] = []
  for (const value of values) {
    out.push(String(value))
  }
  return out
}
```

行为边界：

- 非 array 仍返回 `[]`；
- array 项仍逐项 `String(value)`，保持 `null` / `undefined` / boolean / number 的
  字符串化语义；
- exec failure details 仍保留 `file`、`args`、`exitCode`、`signal`、stderr/stdout
  previews 和 duration；
- AppleScript diagnostic 中 `injectedEnvKeys` 仍返回 string array；
- command invocation 仍传原始 `args` array，不改变执行语义。

新增 `tests/test_vscode_notification_providers_stringify_array_r562.py`：

- source invariant 锁定 `notification-providers.ts` 不再出现 `args.map(String)`，
  `_extractAppleScriptError()` 不再内联 `.map(String)`，并确认 3 个 `args` details
  和 injected env keys 共用 `stringifyArrayValues(...)`；
- Node runtime snippet 验证 helper 对非 array 返回 `[]`，对 mixed array 保持
  `String(value)` 转换契约。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round89/01-mdn-array-map-exa.json`
  保存 MDN `Array.prototype.map()` 资料：`map()` 会调用 callback 并构造新的 array；
  R562 避免在多个诊断分支重复内联 callback pipeline。
- `/tmp/smart-search-evidence/aiia-optimization-round89/02-mdn-string-constructor-exa.json`
  保存 MDN JavaScript string conversion 资料；R562 仍通过 `String(value)` 保持原
  diagnostic stringification 语义。

### 3.106 R563 · VS Code notification center dispatch promise collector

`packages/vscode/notification-center.ts` 的 `NotificationCenter.dispatch()` 会对每个
notification type 并行调用 provider，并用 `Promise.allSettled()` 保证单个 provider
失败不会中断其他 provider。旧代码把完整 per-provider body 写在
`types.map(async (t) => ...)` 中：

```ts
await Promise.allSettled(
  types.map(async (t: NotificationTypeValue) => {
    ...
  })
)
```

这里确实需要一个 promise array 交给 `Promise.allSettled()`，但 `map(async ...)`
同时把业务体绑在 callback pipeline 里；后续要复用 provider 分发逻辑时也只能复制
整段匿名函数。R563 抽出 `_dispatchToProvider(...)` 并用显式 collector：

```ts
const dispatchPromises: Promise<void>[] = []
for (const t of types) {
  dispatchPromises.push(this._dispatchToProvider(event, delivered, t))
}
await Promise.allSettled(dispatchPromises)
```

行为边界：

- 仍先为所有 `types` 创建 dispatch promise，再等待 `Promise.allSettled()`，保持并行
  分发语义；
- 空 type 仍跳过；
- 未注册 provider 仍写 `delivered[type] = false` 并发 debug event；
- provider throw/reject 仍写 `delivered[type] = false` 并发 warn event；
- `dispatch()` 返回的 `{ event, delivered, skipped: false }` shape 不变。

新增 `tests/test_vscode_notification_center_dispatch_loop_r563.py`：

- source invariant 锁定 `dispatch()` 不再使用 `types.map(...)`，改为
  `dispatchPromises` + `for...of` + `_dispatchToProvider(...)`；
- Node runtime model 验证两个 provider 在 await 前都已 started，防止未来误改为
  sequential `await`，同时确认 missing provider、成功 provider、失败 provider 的
  `delivered` 结果不变。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round90/01-mdn-array-map-exa.json`
  保存 MDN `Array.prototype.map()` 资料：`map()` 会调用 callback 并构造新 array；
  R563 避免在 dispatch 热路径中把副作用分发体嵌入 mapper callback。
- `/tmp/smart-search-evidence/aiia-optimization-round90/02-mdn-promise-allsettled-exa.json`
  保存 MDN `Promise.allSettled()` 资料：它等待所有输入 promise settle，适合多个
  provider 互不依赖且需要失败隔离的场景；R563 保留该并发等待边界。

### 3.107 R564 · VS Code host locale loader promise collector

`packages/vscode/extension.ts::activate()` 会在扩展激活时并行读取 host 侧
`locales/en.json` 与 `locales/zh-CN.json`，让 status bar / host notification 等
扩展宿主 UI 可以同步调用 `hostT()`。R20.13-C 已把串行 `readFileSync` 改成
`fs.promises.readFile + Promise.all`，但旧实现仍把读取逻辑内联在
`["en", "zh-CN"].map(async (loc) => ...)`：

```ts
await Promise.all(
  ["en", "zh-CN"].map(async (loc) => {
    ...
  }),
)
```

R564 把单个 locale 读取抽成 `loadHostLocale(...)`，并用显式 promise collector：

```ts
const localeReads: Promise<void>[] = []
for (const loc of ["en", "zh-CN"]) {
  localeReads.push(loadHostLocale(localesDir, loc, hostLocales))
}
await Promise.all(localeReads)
```

这样仍保留并行 I/O，只去掉 mapper callback pipeline，并把 per-locale fail-soft
边界放进可复用 helper。

行为边界：

- `en` 与 `zh-CN` 仍在同一个 tick 内启动读取，然后由 `Promise.all()` 等待；
- 每个 locale 仍使用 `fs.promises.readFile(path.join(localesDir, `${loc}.json`),
  "utf8")`；
- 成功读取且 JSON parse 成功时仍写入 `hostLocales[loc]`；
- 单个 locale 读取或 parse 失败仍被吞掉，不影响另一个 locale；
- `hostLang` 仍按 `vscode.env.language` 的 zh 前缀选择 `zh-CN`，否则 `en`；
- `hostT()` 的 fallback 仍是 active dict → `en` → key。

新增 `tests/test_vscode_extension_host_locale_collector_r564.py`，并更新
`tests/test_vscode_perf_r20_13.py::test_c_locale_loading_uses_promises_read_file_and_parallel`：

- source invariant 锁定 `activate()` 不再出现 `["en", "zh-CN"].map(...)` 或
  `.map(async...)`，而是 `localeReads` + `for...of` + `Promise.all(localeReads)`；
- Node runtime model 验证两个 locale read 在 await 前都已 started，且其中一个
  reject 时另一个成功 locale 仍写入 `hostLocales`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round91/01-mdn-array-map-exa.json`
  保存 MDN `Array.prototype.map()` 资料：`map()` 创建由 callback 结果填充的新数组；
  R564 避免在扩展激活 locale loader 中用 mapper callback 承载副作用读取逻辑。
- `/tmp/smart-search-evidence/aiia-optimization-round91/02-mdn-promise-all-exa.json`
  与 `/tmp/smart-search-evidence/aiia-optimization-round91/03-mdn-promise-all-dedicated-exa.json`
  保存 MDN Promise concurrency 资料：`Promise.all()` 以 iterable promises 为输入，
  可同时启动多个互不依赖任务并等待全部 fulfillment；R564 保留并行读取边界。

### 3.108 R565 · VS Code webview image select FileList 直接处理

`packages/vscode/webview-ui.js::handleImageSelect()` 是 VS Code webview 图片选择入口。
旧实现先复制完整 `FileList`：

```js
const files = Array.from(e.target.files || [])
processImages(files)
```

`processImages()` 随后只逐个处理文件，不需要 array 方法链；这个完整 copy 在多图选择
时只是短命中间数组。R565 改为直接传入 `FileList`，并让 `processImages()` 按
`length` + index / `item()` 访问：

```js
const files = target && target.files ? target.files : []
processImages(files)
...
const fileCount = ...
for (let fileIndex = 0; fileIndex < fileCount; fileIndex += 1) {
  const file = files[fileIndex] || files.item(fileIndex)
  ...
}
```

行为边界：

- 文件 input change 仍调用 `processImages(files)`；
- input value 仍在处理后清空，允许重复选择同一文件；
- `processImages()` 仍接受 paste 路径传入的普通 array；
- `FileList` / array-like 只要有 finite `length` 与 index 或 `item()` 即可处理；
- `length` 非 finite / 缺失时按 0 个文件处理；
- 每个文件的数量上限、pending 计数、压缩、缓存同步、错误提示和 finally 递减逻辑不变。

新增 `tests/test_vscode_webview_image_select_filelist_r565.py`：

- source invariant 锁定 `handleImageSelect()` 不再出现 `Array.from(e.target.files...)`，
  并确认 `processImages()` 不再 `for...of files`，而是 `fileCount` + indexed loop；
- Node runtime model 使用没有 iterator 的 FileList-like object，验证 index 与 `item()`
  两种访问都能处理，普通 array 仍能处理，非 finite `length` 不处理，并且 input
  value 仍被清空。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round92/01-mdn-filelist-exa.json`
  保存 MDN File API / `HTMLInputElement.files` 资料：`files` 返回 `FileList`，
  可通过 `length` 判断数量，单个 File 可按数组形式访问。
- `/tmp/smart-search-evidence/aiia-optimization-round92/04-mdn-array-from-exa.json`
  保存 MDN `Array.from()` 资料：它会从 iterable 或 array-like 创建新的 shallow-copied
  `Array` instance；R565 避免图片选择入口的完整 FileList copy。

### 3.109 R566 · VS Code webview sanitizer NodeList 逆序直接遍历

`packages/vscode/webview-ui.js::sanitizePromptHtml()` 旧实现为保证 DOM mutation
期间的逆序处理，先把静态查询结果复制为数组再反转：

```js
const all = Array.from(container.querySelectorAll('*')).reverse()
all.forEach(...)
```

`querySelectorAll('*')` 已经返回 static `NodeList`，而且顺序为 document order
（父节点在子节点前、较早 sibling 在较晚 sibling 前）。R566 直接缓存这个 static
`NodeList`，然后用 index 从尾到头遍历：

```js
const all = container.querySelectorAll('*')
for (let allIndex = all.length - 1; allIndex >= 0; allIndex -= 1) {
  const el = all[allIndex] || all.item(allIndex)
  ...
}
```

行为边界：

- 仍保持逆序处理，避免 `remove()` / `unwrapElement()` 修改 DOM 时影响待处理子树；
- `DROP_TAGS` 删除、非白名单 tag unwrap、URL normalize、属性清理逻辑不变；
- 兼容正常 `NodeList[index]` 与只提供 `item(index)` 的 array-like 模型；
- 本轮不改 `el.attributes` 迭代；`NamedNodeMap` 是另一个 live collection 边界，单独审计更稳。

新增 `tests/test_vscode_webview_sanitize_nodelist_reverse_r566.py`：

- source invariant 锁定 sanitizer 不再出现
  `Array.from(container.querySelectorAll('*')).reverse()`，并确认使用
  `querySelectorAll('*')` + reverse indexed loop + `item()` fallback；
- Node runtime model 使用没有 `reverse()` / `forEach()` 的 NodeList-like object，
  验证逆序顺序为 child / later sibling 先处理、drop / unwrap 行为保持，并覆盖
  `item(index)` fallback。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round93/01-mdn-queryselectorall-nodelist-exa.json`
  保存 MDN `querySelectorAll()` 资料：返回 static/non-live `NodeList`，元素按 document
  order 排列。
- `/tmp/smart-search-evidence/aiia-optimization-round93/02-mdn-array-from-exa.json`
  保存 MDN `Array.from()` 资料：从 iterable 或 array-like 创建新的 shallow-copied
  `Array` instance；R566 去掉 sanitizer 外层遍历的 copy + reverse 中间数组。

### 3.110 R567 · VS Code webview textarea state trim own-key 流式遍历

`packages/vscode/webview-ui.js::trimTextareaContents()` 在每次 debounced
`vscode.setState()` 前裁剪 `taskTextareaContents`，保证持久化文本总量不超过
`UI_STATE_TEXT_LIMIT_CHARS`。旧实现：

```js
for (const taskId of Object.keys(src)) {
  ...
}
```

`Object.keys(src)` 会先分配完整 own enumerable key array；但这个 helper 随后只是
顺序扫描、按预算提前 `break`，不需要完整 key array。R567 改成：

```js
for (const taskId in src) {
  if (!Object.prototype.hasOwnProperty.call(src, taskId)) continue
  ...
}
```

行为边界：

- 仍只处理 own enumerable string keys，继承属性通过 own-property guard 跳过；
- key 顺序继续遵循 `Object.keys()` / `for...in` 的 enumerable string key 顺序；
- 非字符串、空字符串、non-enumerable 属性继续不写入；
- 预算不足时仍写入当前文本前缀并停止，`UI_STATE_TEXT_LIMIT_CHARS` 语义不变；
- catch fallback 仍返回 `{}`，状态持久化异常不影响主流程。

新增 `tests/test_vscode_webview_trim_textarea_own_keys_r567.py`：

- source invariant 锁定 `trimTextareaContents()` 不再调用 `Object.keys(src)`，并确认
  使用 `for...in` + `Object.prototype.hasOwnProperty.call(...)`；
- Node runtime model 禁用 `Object.keys()`，构造带 prototype 继承 key、非枚举 key、
  空字符串、非字符串值和预算截断的输入，验证输出只包含 own enumerable string
  内容并保留截断行为。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round94/01-mdn-object-keys-exa.json`
  保存 MDN `Object.keys()` 资料：返回对象 own enumerable string-keyed property
  names 的 array，顺序与 `for...in` 一致但不含 prototype chain。
- `/tmp/smart-search-evidence/aiia-optimization-round94/02-mdn-for-in-exa.json`
  保存 MDN `for...in` 资料：遍历 enumerable string properties，包含继承属性；
  只需要 own properties 时必须加 guard。
- `/tmp/smart-search-evidence/aiia-optimization-round94/03-mdn-hasown-exa.json`
  保存 MDN own-property 资料：`hasOwnProperty()` / `Object.hasOwn()` 用于区分
  direct own properties 与 inherited properties。

### 3.111 R568 · VS Code webview saved option state own-key 流式遍历

`packages/vscode/webview-ui.js::updateUI()` 在重建 predefined options DOM 前，会从
`taskOptionsStates[task_id]` 恢复用户之前勾选过的 option indexes。array 形态已经
直接 `forEach`；object 形态旧实现为：

```js
Object.keys(savedState).forEach(k => {
  if (savedState[k]) {
    const n = parseInt(k, 10)
    ...
  }
})
```

这个路径只需要顺序扫描并把 truthy key 解析成 index，不需要先分配完整 key array。
R568 改为：

```js
for (const k in savedState) {
  if (!Object.prototype.hasOwnProperty.call(savedState, k)) continue
  ...
}
```

行为边界：

- array 形态仍走 `savedState.forEach(...)`，语义不变；
- object 形态仍只处理 own enumerable string keys，继承属性被 guard 跳过；
- key 顺序继续与 `Object.keys()` 对齐；
- truthy value 才会恢复选中状态；
- `parseInt(k, 10)` / `Number.isNaN(n)` 行为保持不变，包括 `"03-extra"` 这类旧边界。

新增 `tests/test_vscode_webview_saved_options_own_keys_r568.py`：

- source invariant 锁定 savedState object branch 不再调用 `Object.keys(savedState)`，
  并确认使用 `for...in` + own-property guard；
- Node runtime model 禁用 `Object.keys()`，构造带 inherited key、non-enumerable key、
  falsey value、非数字 key 和 legacy parseInt 边界的 savedState object，同时确认
  array savedState 路径仍恢复 truthy indexes。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round95/01-mdn-object-keys-exa.json`
  保存 MDN `Object.keys()` 资料：返回 own enumerable string-keyed property names
  的 array，顺序与 `for...in` 一致但不含 prototype chain。
- `/tmp/smart-search-evidence/aiia-optimization-round95/02-mdn-for-in-hasown-exa.json`
  保存 MDN `for...in` 与 own-property 资料：`for...in` 会遍历 enumerable string
  properties 并包含 inherited properties；只处理 own properties 时需要
  `Object.hasOwn()` 或 `hasOwnProperty` guard。

### 3.112 R569 · VS Code webview sanitizer attributes NamedNodeMap 逆序直接遍历

R566 已去掉 `sanitizePromptHtml()` 外层 `querySelectorAll('*')` 的 array copy；
sanitizer 内层属性清理仍然对每个允许元素执行：

```js
Array.from(el.attributes || []).forEach(attr => {
  ...
})
```

`Element.attributes` 返回 live `NamedNodeMap`，不是 `Array`。旧写法先把每个元素的
属性 snapshot 成新数组，再逐个删除事件属性、`style`、非白名单属性，并规范化
`href` / `src`。R569 改为对 live `NamedNodeMap` 做 reverse indexed loop：

```js
const attributes = el.attributes || []
for (let attrIndex = attributes.length - 1; attrIndex >= 0; attrIndex -= 1) {
  const attr = attributes[attrIndex] || attributes.item(attrIndex)
  ...
}
```

行为边界：

- 逆序遍历 live collection，删除当前属性时不会跳过尚未处理的低位属性；
- `attributes[index]` 与 `attributes.item(index)` 两种 DOM 访问方式都支持；
- 原来的属性规则不变：删除 `on*` / `style` / 非白名单属性，`href` 归一化并补
  `target="_blank"` 与 `rel="noopener noreferrer"`，危险 `img.src` 仍移除整张图；
- `href` 分支新增的 `target` / `rel` 不会被本轮遍历再次处理，和旧 snapshot
  行为一致；
- 外层元素逆序、drop tag、unwrap tag 与 catch fallback 不变。

新增 `tests/test_vscode_webview_sanitize_attributes_namednodemap_r569.py`：

- source invariant 锁定 sanitizer 不再出现 `Array.from(el.attributes || [])`，
  并确认使用 reverse indexed `attributes` loop + `item()` fallback；
- Node runtime model 使用 live `NamedNodeMap`-like object，禁用 `Array.from()`、
  `forEach` 和 iterator，验证相邻 unsafe attributes 不被跳过，`href` 规范化和
  `target` / `rel` append 保持，危险 `img.src` 仍触发整图移除。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round96/01-mdn-element-attributes-namednodemap-exa.json`
  保存 MDN `Element.attributes` 资料：返回 live `NamedNodeMap`，不是 `Array`，
  没有 array methods。
- `/tmp/smart-search-evidence/aiia-optimization-round96/02-mdn-namednodemap-exa.json`
  保存 MDN `NamedNodeMap.item()` / `length` 资料：可按 index 或 `item(index)` 读取
  attribute node，`length` 是 map 中对象数量。
- `/tmp/smart-search-evidence/aiia-optimization-round96/03-mdn-array-from-exa.json`
  保存 MDN `Array.from()` 资料：从 iterable 或 array-like 创建新的 shallow-copied
  `Array` instance；R569 去掉 sanitizer 每个元素属性清理的 snapshot array。

### 3.113 R570 · WebUI VirtualScroller render 可见窗口单次拼接

`src/ai_intervention_agent/static/js/validation-utils.js` 的 `VirtualScroller.render()`
是长列表滚动热路径。旧实现每次滚动先复制可见窗口，再 `map().join("")`：

```js
const visibleItems = this.items.slice(startIndex, endIndex)
this.content.innerHTML = visibleItems
  .map((item, i) => this.renderItem(item, startIndex + i))
  .join("")
```

这会在每次 render 中创建 visible items array 和 mapped HTML array；对任务列表、日志列表
这类高频 scroll render 来说，只需要按原数组 index 读取并拼接 HTML。R570 改为一次
indexed loop：

```js
let html = ""
for (let index = startIndex; index < endIndex; index += 1) {
  if (!(index in this.items)) continue
  const rendered = this.renderItem(this.items[index], index)
  if (rendered !== undefined && rendered !== null) {
    html += rendered
  }
}
this.content.innerHTML = html
```

行为边界：

- `startIndex` / `endIndex` / `translateY(...)` 计算保持不变；
- 继续向 `renderItem()` 传真实全局 index，而不是可见窗口局部 index；
- sparse array hole 与旧 `slice().map().join("")` 行为一致：hole 不调用
  `renderItem()`，显式 `undefined` / `null` 仍调用但最终拼接为空字符串；
- `setItems()` 高度更新、scroll handler 和 destroy 生命周期不变。

新增 `tests/test_validation_utils_virtual_list_render_one_pass_r570.py`：

- source invariant 锁定 `render()` 不再出现 `this.items.slice(startIndex, endIndex)`、
  `visibleItems` 或旧 `.map((item, i) => ...)` 链，并确认使用 indexed loop；
- Node runtime model 禁用 `items.slice()`，验证可见窗口边界、`translateY`、HTML 输出、
  sparse hole、显式 `undefined` / `null` render 结果都与旧 pipeline 等价。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round97/01-mdn-array-slice-exa.json`
  保存 MDN `Array.prototype.slice()` 资料：`slice()` 返回 selected range 的 shallow
  copy/new array，原数组不变。
- `/tmp/smart-search-evidence/aiia-optimization-round97/02-mdn-array-map-exa.json`
  保存 MDN `Array.prototype.map()` 资料：`map()` 为每个元素调用 callback，并构造新的
  array 保存返回值。
- `/tmp/smart-search-evidence/aiia-optimization-round97/03-mdn-array-join-exa.json`
  保存 MDN `Array.prototype.join()` 资料：`join()` 把 array 元素拼成 string，`null` /
  `undefined` 元素按空字符串处理；R570 用直接字符串累积模拟该输出边界。

### 3.114 R571 · WebUI image-upload Object.assign fallback own-key 直接复制

`src/ai_intervention_agent/static/js/image-upload.js::setupFeatureFallbacks()` 为旧浏览器
保留 `Object.assign` fallback。旧 fallback 对每个 source 先创建 own-key array，再用
nested callback 复制：

```js
sources.forEach((source) => {
  if (source) {
    Object.keys(source).forEach((key) => {
      target[key] = source[key]
    })
  }
})
```

这个 fallback 只需要复制 enumerable own string keys；`Object.keys(source)` 的数组
只是中间物。R571 改为 sources indexed loop + guarded `for...in`：

```js
for (let sourceIndex = 0; sourceIndex < sources.length; sourceIndex += 1) {
  const source = sources[sourceIndex]
  if (source) {
    for (const key in source) {
      if (Object.prototype.hasOwnProperty.call(source, key)) {
        target[key] = source[key]
      }
    }
  }
}
```

行为边界：

- 保留原 fallback 的 falsy source skip 行为；
- 继续只复制 enumerable string-keyed own properties，不复制 inherited enumerable keys；
- 使用 `Object.prototype.hasOwnProperty.call(...)`，兼容 source 自己覆盖
  `hasOwnProperty` 或 null-prototype object；
- `for...in` 忽略 symbol keys，与旧 `Object.keys()` 路径一致；
- `target` 返回值、RAF fallback、clipboard warning 和初始化流程不变。

新增 `tests/test_image_upload_object_assign_polyfill_own_keys_r571.py`：

- source invariant 锁定 fallback 不再出现 `Object.keys(source)` / `sources.forEach`
  / key `.forEach(...)`，并确认使用 guarded `for...in`；
- Node runtime 在实际 `image-upload.js` VM 中暴露 `setupFeatureFallbacks()`，禁用
  native `Object.assign`，并把 `Object.keys()` / `Array.prototype.forEach()` 设为
  throwing guard，验证 inherited enumerable、non-enumerable、symbol key 不复制，
  overridden `hasOwnProperty` 与 null-prototype source 仍能正确复制 own keys。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round98/01-mdn-object-keys-exa.json`
  保存 MDN `Object.keys()` 资料：返回给定对象 own enumerable string-keyed property
  names 的 array；这正是 R571 去掉的中间数组。
- `/tmp/smart-search-evidence/aiia-optimization-round98/02-mdn-for-in-exa.json`
  保存 MDN `for...in` 资料：会遍历 enumerable string properties，包括 inherited
  enumerable properties；R571 因此必须配合 own-property guard。
- `/tmp/smart-search-evidence/aiia-optimization-round98/03-mdn-hasownproperty-exa.json`
  保存 MDN `hasOwnProperty()` 资料：可判断 direct/own property；使用
  `Object.prototype.hasOwnProperty.call(...)` 可避开 source 覆盖该方法或没有
  `Object.prototype` 的边界。

### 3.115 R572 · WebUI multi_task 图片状态 clone 去 map callback

`src/ai_intervention_agent/static/js/multi_task.js::switchTask()` 与
`loadTaskDetails()` 在任务切换时分别保存 / 恢复当前任务的图片列表。旧实现两处都用
`map()` clone：

```js
taskImages[activeTaskId] = selectedImages.map((img) => ({ ...img }))
...
selectedImages = taskImages[taskId].map((img) => ({ ...img }))
```

这里每个 image item 的 shallow clone 是必要的，但外层 `map()` callback 不是必要边界。
R572 抽出 `cloneTaskImagesForState(images)`，按 length 预分配目标数组并用 index
直接填充：

```js
const clonedImages = new Array(imageCount)
for (let imageIndex = 0; imageIndex < imageCount; imageIndex += 1) {
  if (!(imageIndex in images)) continue
  clonedImages[imageIndex] = { ...images[imageIndex] }
}
```

行为边界：

- 两个 call site 继续创建新的 array，避免跨任务共享 `selectedImages` array；
- 每个存在的 image item 仍通过 `{ ...img }` shallow clone，保留 blob URL 等 enumerable
  own properties，嵌套对象引用保持 shallow copy 语义；
- sparse hole 仍不调用 clone，并在目标数组中保留 hole，等价于 `Array.prototype.map()`；
- 显式 `undefined` / `null` entry 仍变成 `{}`，等价于旧 object spread callback；
- 保存/恢复后的 preview render、counter、visibility 更新流程不变。

新增 `tests/test_multi_task_image_clone_one_pass_r572.py`：

- source invariant 锁定不再出现 `selectedImages.map` /
  `taskImages[taskId].map`，并确认两个 call site 使用共享 helper；
- Node runtime 在实际 `multi_task.js` VM 中禁用 `Array.prototype.map()`，验证 helper
  保留 length、hole、浅拷贝、non-enumerable / inherited 不复制、symbol enumerable
  复制、`null` / `undefined` entry 输出 `{}` 等边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round99/01-mdn-array-map-exa.json`
  保存 MDN `Array.prototype.map()` 资料：`map()` 创建新 array、对存在的 index 调用
  callback，并且 sparse array 的 empty slots 仍保持 empty。
- `/tmp/smart-search-evidence/aiia-optimization-round99/02-mdn-object-spread-exa.json`
  保存 MDN spread syntax 资料：object literal spread 会枚举 source 的 own
  properties 并加入新对象；R572 保留每个 image item 的 `{ ...img }` shallow clone
  语义，只替换外层 array clone 的控制流。

### 3.116 R573 · WebUI multi_task closeTask 去 filter callback

`src/ai_intervention_agent/static/js/multi_task.js::closeTask()` 在服务端成功关闭任务后，
旧实现用：

```js
currentTasks = currentTasks.filter((t) => t.task_id !== taskId)
```

这条路径会为每次成功 close 创建新 array，并对当前任务列表中的每个已赋值元素调用
callback。R573 改为 `removeTaskFromCurrentTasks(currentTasks, taskId)`：

- 只有遇到首个匹配 `task_id` 时才创建 survivor array；
- 首个匹配之前的 survivor 用直接 index loop 复制，后续 survivor 用 `push()` 追加；
- 删除多个相同 `task_id` 时仍全部移除，并保持 survivor 原顺序；
- 找不到目标 task 时直接返回原 array，避免无意义的 array 分配和 callback 调度；
- `window.currentTasks = currentTasks`、`renderTaskTabs()`、active task 后续切换、
  countdown / deadline / textarea / option / image / auto-submit 缓存清理流程保持在原位置。

新增 `tests/test_multi_task_close_task_lazy_filter_r573.py`：

- source invariant 锁定 `closeTask()` 不再出现 `currentTasks.filter`，并确认 helper
  内部没有 `.filter(`；
- Node runtime 在实际 `multi_task.js` VM 中禁用 `Array.prototype.filter()`，验证成功
  close 会移除全部匹配 task、保持 survivor 顺序、同步 `window.currentTasks`、清理相关
  per-task 状态并切换到第一个未完成任务；
- 缺失 task id 路径同样禁用 `filter()`，验证列表内容、active task 和
  `window.currentTasks` 引用保持不变，避免 no-op close 仍重写 array。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round100/01-mdn-array-filter-exa.json`
  保存 MDN `Array.prototype.filter()` 资料：`filter()` 会创建 shallow copy，按
  callback 结果构造新 array，并仅访问有 assigned values 的 indexes。
- `/tmp/smart-search-evidence/aiia-optimization-round100/02-mdn-array-length-exa.json`
  保存 MDN Array length / Array 资料：array `length` 表示 slots，上界驱动 index
  遍历；array copy 操作为 shallow copy。R573 只替换外层筛选控制流，不改变 task
  object 引用。

### 3.117 R574 · WebUI multi_task task lookup 去 find callback

`src/ai_intervention_agent/static/js/multi_task.js` 仍有几处按 `task_id` 或
“第一个未完成 task”扫描 `currentTasks` 的路径：

- countdown extend / freeze 响应后同步本地 task cache；
- deep-link pending task 应用；
- `switchTask()` 立即从 cache 更新 prompt/options；
- `closeTask()` / submit fallback 自动切换到下一个未完成 task。

旧实现分散使用 `Array.prototype.find()` callback。R574 收敛为 3 个直接 helper：

```js
findTaskById(tasks, taskId)
findOpenTaskById(tasks, taskId)
findFirstOpenTask(tasks, excludedTaskId)
```

行为边界：

- `task_id` 继续使用 strict equality，避免把数字 `42` 和字符串 `"42"` 混为同一
  task；
- deep-link 路径继续要求 `status !== "completed"`，并能跳过已完成 duplicate 后
  命中后续同 id open task；
- `findFirstOpenTask()` 保持原来的“第一个 `status !== "completed"`”语义，
  submit fallback 继续排除刚提交的 task；
- nullish / sparse snapshot entry 被安全跳过，避免 stale snapshot 中的异常 entry
  让 UI lookup 抛错；
- 不改变返回的 task object 引用，后续 extend/freeze 仍直接更新同一个 cache item。

新增 `tests/test_multi_task_task_lookup_direct_loop_r574.py`：

- source invariant 锁定 owned `multi_task.js` 不再出现 `.find(`，并确认所有 call
  site 使用 helper；
- Node runtime 禁用 `Array.prototype.find()`，验证 helper 的 strict id、duplicate
  completed/open、null entry、first-open 与 excluded-task 边界；
- 在实际 VM 中禁用 `find()`，验证 `closeTask()` 仍切换到第一个未完成 task；
- 在实际 VM 中禁用 `find()`，验证 `switchTask()` 仍能从 `currentTasks` cache
  立即更新 prompt/options，并保持 active task 同步。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round101/01-mdn-array-find-exa.json`
  保存 MDN `Array.prototype.find()` 资料：`find()` 是 iterative method，会按升序为
  array index 调用 callback，直到 callback truthy 后返回第一个元素。
- `/tmp/smart-search-evidence/aiia-optimization-round101/02-mdn-for-statement-exa.json`
  保存 MDN loops / `for` 资料：`for` loop 可用 index 与 `length` 直接遍历 array；
  MDN 同时提示 `for...in` 会枚举自定义属性，不适合作为 array element 热路径。

### 3.118 R575 · WebUI multi_task submit 图片 FormData 去 forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::submitTaskFeedback()` 构建
`FormData` 时，旧实现用 `selectedImages.forEach((img, index) => ...)` 添加图片：

```js
selectedImages.forEach((img, index) => {
  if (img.file) {
    formData.append(`image_${index}`, img.file)
  }
})
```

这个路径在每次用户提交反馈时运行；图片数量通常不大，但它位于提交关键路径，且
只需要按原始 index 生成字段名。R575 改成 indexed loop：

```js
const selectedImageCount =
  selectedImages && Number.isFinite(selectedImages.length)
    ? selectedImages.length
    : 0
for (let imageIndex = 0; imageIndex < selectedImageCount; imageIndex += 1) {
  if (!(imageIndex in selectedImages)) continue
  const img = selectedImages[imageIndex]
  if (img.file) {
    formData.append(`image_${imageIndex}`, img.file)
  }
}
```

行为边界：

- `feedback_text` / `selected_options` append 顺序保持在图片之前；
- `image_<index>` 字段名继续使用原始 `selectedImages` index，sparse hole 不会被压缩
  成连续字段；
- hole 与旧 `forEach()` 一样不访问；显式存在但无 `file` 的 entry 不 append；
- `FormData.append()` 仍用于追加字段，不改 multipart upload contract；
- submit 成功后的 countdown cleanup、SSE fallback refresh、auto-switch 逻辑不变。

新增 `tests/test_multi_task_submit_images_index_loop_r575.py`：

- source invariant 锁定 `submitTaskFeedback()` 不再出现旧
  `selectedImages.forEach((img, index)`，并确认 indexed loop / hole guard /
  `image_${imageIndex}` 字段名；
- Node runtime 在实际 `multi_task.js` VM 中禁用 `Array.prototype.forEach()`，
  使用 sparse `selectedImages` 验证只 append `image_0` 和 `image_3`，保留
  `feedback_text` / `selected_options` 顺序和 `/api/tasks/{id}/submit` 请求边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round102/01-mdn-array-foreach-exa.json`
  保存 MDN `Array.prototype.forEach()` 资料：`forEach()` 是 iterative method，会对
  array element 调用 callback；callback 不会为 sparse array empty slots 调用。
- `/tmp/smart-search-evidence/aiia-optimization-round102/02-mdn-formdata-append-exa.json`
  保存 MDN `FormData.append()` 资料：`append(name, value)` 会向 FormData key
  追加新 value；同名 key 不会覆盖已有值。R575 只替换图片 entry 遍历方式，不改变
  FormData append API。

### 3.119 R576 · WebUI app submit 图片 FormData 去 forEach callback

`src/ai_intervention_agent/static/js/app.js::submitFeedback()` 的单任务提交路径与
R575 multi-task 路径有同类图片 append 逻辑：旧实现通过
`selectedImages.forEach((img, index) => ...)` 构造 `image_<index>` 字段。R576
将这段提交关键路径改成 indexed loop，与 R575 保持实现边界一致：

```js
const selectedImageCount =
  selectedImages && Number.isFinite(selectedImages.length)
    ? selectedImages.length
    : 0
for (let imageIndex = 0; imageIndex < selectedImageCount; imageIndex += 1) {
  if (!(imageIndex in selectedImages)) continue
  const img = selectedImages[imageIndex]
  if (img.file) {
    formData.append(`image_${imageIndex}`, img.file)
  }
}
```

行为边界：

- `feedback_text` / `selected_options` 仍先 append，图片字段仍排在它们之后；
- `image_<original index>` 字段名保留原始 `selectedImages` index，sparse hole 不会被压缩；
- sparse hole 与旧 `forEach()` 一样跳过；显式存在但无 `.file` 的 entry 不 append；
- `FormData.append()` contract 不变，仍是追加 field value，而不是覆盖；
- 同函数里的 selected-options `checkboxes.forEach(...)` 属于独立 UI 选项采集逻辑，
  不属于本 slice。

新增 `tests/test_app_submit_images_index_loop_r576.py`：

- source invariant 锁定 `submitFeedback()` 不再出现旧
  `selectedImages.forEach((img, index)`，并确认 indexed loop / hole guard /
  `image_${imageIndex}` 字段名；
- 复用 R452 `app.js` submit harness，在实际 Node VM 中禁用
  `Array.prototype.forEach()`，同时不挂载 options container，避免 unrelated
  selected-options 遍历干扰；
- 使用 sparse `selectedImages` 验证只 append `image_0` 和 `image_3`，保留
  `/api/submit`、`feedback_text`、`selected_options: "[]"` 和 30s timeout 边界。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round103/01-mdn-array-foreach-exa.json`
  保存 MDN `Array.prototype.forEach()` 资料：`forEach()` 会对 assigned array
  index 调用 callback，并跳过 sparse array empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round103/02-mdn-formdata-append-exa.json`
  保存 MDN `FormData.append()` 资料：`append()` 会向 FormData key 追加 value；
  R576 只替换图片 entry 遍历方式，不改变 multipart field 语义。

### 3.120 R577 · WebUI app submit selected-options NodeList 去 forEach callback

`src/ai_intervention_agent/static/js/app.js::submitFeedback()` 在提交前会从
`options-container` 中读取已选 checkbox，旧实现直接对
`querySelectorAll('input[type="checkbox"]:checked')` 返回的 `NodeList` 调
`forEach()`：

```js
checkboxes.forEach((checkbox) => {
  if (checkbox.value) {
    selectedOptions.push(checkbox.value)
  }
})
```

R577 将这段同一提交关键路径改为缓存 `length` 的 indexed loop：

```js
const checkboxCount =
  checkboxes && Number.isFinite(checkboxes.length) ? checkboxes.length : 0
for (let checkboxIndex = 0; checkboxIndex < checkboxCount; checkboxIndex += 1) {
  const checkbox = checkboxes[checkboxIndex]
  if (!checkbox) continue
  if (checkbox.value) {
    selectedOptions.push(checkbox.value)
  }
}
```

行为边界：

- `querySelectorAll()` 返回的 static `NodeList` 顺序保持为 DOM document order；
- selected option value 的顺序不变，仍按 checked checkbox 的原始顺序 push；
- falsy / empty `checkbox.value` 继续跳过；
- `feedback_text`、`selected_options`、图片字段和 submit endpoint 语义不变；
- 成功 cleanup 中的 `document.querySelectorAll('input[type="checkbox"]').forEach(...)`
  是提交后的表单重置逻辑，不属于本 slice。

新增 `tests/test_app_submit_options_nodelist_loop_r577.py`：

- source invariant 锁定 `submitFeedback()` 不再出现 selected-options
  `checkboxes.forEach((checkbox)`，并确认 `checkboxCount` / indexed loop /
  null guard / `selectedOptions.push(checkbox.value)`；
- Node VM runtime 构造一个 NodeList-like checked-options 对象，其 `forEach()`
  会直接 throw，验证 `submitFeedback()` 仍能提交 `["first","third"]`，并跳过
  empty value；
- 使用 HTTP 500 响应停在 FormData 构造后，避免 unrelated success cleanup
  `forEach` 影响本切片判断。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round104/01-mdn-nodelist-foreach-exa.json`
  保存 MDN `NodeList` 资料：`NodeList` 通常由 `querySelectorAll()` 返回，不是
  `Array`，可通过 `length` 与索引访问，也支持 `forEach()`。
- `/tmp/smart-search-evidence/aiia-optimization-round104/02-mdn-queryselectorall-exa.json`
  保存 MDN `querySelectorAll()` 资料：返回 static / non-live `NodeList`，元素按
  document order 排列。R577 缓存长度并按 index 读取不会改变选项顺序。

### 3.121 R578 · WebUI app submit success cleanup NodeList 去 forEach callback

R577 只处理提交前 selected-options 采集；`submitFeedback()` 成功后当前任务仍可见时，
还会重置所有 checkbox：

```js
document
  .querySelectorAll('input[type="checkbox"]')
  .forEach((cb) => (cb.checked = false))
```

R578 将这段 success cleanup 改成同样的 indexed loop：

```js
const allCheckboxes = document.querySelectorAll('input[type="checkbox"]')
const allCheckboxCount =
  allCheckboxes && Number.isFinite(allCheckboxes.length)
    ? allCheckboxes.length
    : 0
for (
  let checkboxIndex = 0;
  checkboxIndex < allCheckboxCount;
  checkboxIndex += 1
) {
  const checkbox = allCheckboxes[checkboxIndex]
  if (checkbox) {
    checkbox.checked = false
  }
}
```

行为边界：

- 只在 `isSubmitTargetStillCurrent(submitTargetTaskId)` 为 true 时运行，保持 R280
  stale-task guard；
- `querySelectorAll()` 返回的 static `NodeList` 缓存长度后逐项访问，不改变 checkbox
  集合边界；
- 每个存在的 checkbox 仍被设置为 `checked = false`，包括提交前未选中的 checkbox；
- 后续 `clearAllImages()`、task local cache cleanup、`refreshTasksList()` 顺序不变；
- 失败响应、HTTP 分类、network catch 和 R577 selected-options 采集逻辑不变。

新增 `tests/test_app_submit_cleanup_nodelist_loop_r578.py`：

- source invariant 锁定 `submitFeedback()` 不再出现
  `.forEach((cb) => (cb.checked = false))`，并确认 `allCheckboxes` /
  `allCheckboxCount` / indexed loop / `checkbox.checked = false`；
- Node VM runtime 构造一个 NodeList-like all-checkboxes 对象，其 `forEach()` 会
  throw，验证 submit success path 仍能清空 textarea、取消所有 checkbox 勾选、
  调用 `clearAllImages()`、清 task local cache 并刷新当前任务；
- 同时验证 FormData 仍包含 `feedback_text`、`selected_options` 和 `image_0`，
  避免 cleanup 优化误伤提交 payload。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round105/01-mdn-nodelist-index-loop-exa.json`
  保存 MDN `NodeList` 资料：`NodeList` 通常由 `querySelectorAll()` 返回，可通过
  `length` 和 index 访问，MDN 示例也展示 `for` loop 遍历。
- `/tmp/smart-search-evidence/aiia-optimization-round105/02-mdn-queryselectorall-static-exa.json`
  保存 MDN `querySelectorAll()` 资料：返回 static / non-live `NodeList`，元素按
  document order 排列。R578 不依赖 live mutation，缓存长度与旧 cleanup 语义一致。

### 3.122 R579 · WebUI LazyLoader 图片集合单次 query + indexed loop

`src/ai_intervention_agent/static/js/validation-utils.js::LazyLoader.init()` 初始化
懒加载图片时，旧实现对 `querySelectorAll(selector)` 结果调用 `forEach()`，随后 debug
日志又重复执行一次相同 selector query：

```js
document.querySelectorAll(selector).forEach((img) => {
  observer.observe(img)
})

console.debug(
  `Lazy loader initialized, watching ${document.querySelectorAll(selector).length} images`,
)
```

R579 缓存 static `NodeList`，用一次 `length` + index loop 同时完成 observe 和 debug
计数；fallback `loadAllImages()` 也从 `NodeList.forEach()` 改成同类 indexed loop：

```js
const images = document.querySelectorAll(selector)
const imageCount =
  images && Number.isFinite(images.length) ? images.length : 0
for (let imageIndex = 0; imageIndex < imageCount; imageIndex += 1) {
  const img = images[imageIndex]
  if (img) {
    observer.observe(img)
  }
}

console.debug(`Lazy loader initialized, watching ${imageCount} images`)
```

行为边界：

- IntersectionObserver 支持路径仍先 `disconnect()` 旧 observer，再创建新 observer；
- 每个存在的 lazy image 仍按 `querySelectorAll()` 的 document order 被 observe；
- debug 日志的数量改用同一个 static `NodeList.length`，避免第二次 DOM selector query；
- 不支持 IntersectionObserver 的 fallback 仍立即调用 `loadImage(img)`；
- observer callback 内 `entries.forEach(...)` 仍是独立事件回调路径，不属于本 slice。

新增 / 更新测试：

- 新增 `tests/test_validation_utils_lazy_loader_query_once_r579.py`：
  - source invariant 锁定 `LazyLoader.init()` / `loadAllImages()` 不再出现
    `document.querySelectorAll(selector).forEach`；
  - Node VM runtime 构造 NodeList-like 对象，其 `forEach()` 会 throw，验证
    `LazyLoader.init()` 只 query 一次、observe 两张图、debug 计数为 2；
  - fallback runtime 验证 `loadAllImages()` 在无 `forEach` 的 NodeList-like 对象上
    仍按顺序调用 `loadImage()`，且只 query 一次。
- 更新 `tests/test_validation_utils_lazy_loader_lifecycle_r452.py`：重复 init 仍会
  disconnect 旧 observer，但每次 init 的 query 次数从 2 次收敛为 1 次。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round106/01-mdn-queryselectorall-static-exa.json`
  保存 MDN `querySelectorAll()` 资料：返回 static / non-live `NodeList`，元素按
  document order 排列。
- `/tmp/smart-search-evidence/aiia-optimization-round106/02-mdn-nodelist-index-loop-exa.json`
  保存 MDN `NodeList` 资料：`NodeList` 不是 `Array`，但可通过 `length` 和 index
  访问；MDN 示例展示可用普通 `for` loop 遍历 `NodeList`。

### 3.123 R580 · WebUI LazyLoader IntersectionObserver entries 去 forEach callback

R579 处理了 LazyLoader 初始化阶段的图片集合查询；observer callback 内仍有一段
`entries.forEach(...)`：

```js
entries.forEach((entry) => {
  if (entry.isIntersecting) {
    this.loadImage(entry.target, config)
    obs.unobserve(entry.target)
  }
})
```

这段在 IntersectionObserver 每次派发 intersection changes 时运行。R580 改成
缓存 `entries.length` 的 indexed loop：

```js
const entryCount =
  entries && Number.isFinite(entries.length) ? entries.length : 0
for (let entryIndex = 0; entryIndex < entryCount; entryIndex += 1) {
  const entry = entries[entryIndex]
  if (!entry) continue
  if (entry.isIntersecting) {
    this.loadImage(entry.target, config)
    obs.unobserve(entry.target)
  }
}
```

行为边界：

- IntersectionObserver callback 仍接收 `(entries, obs)`，保留 R299 的 unobserve
  cleanup contract；
- `isIntersecting === true` 的 entry 仍执行 `loadImage(entry.target, config)` 后
  `obs.unobserve(entry.target)`；
- 非 intersecting entry 继续跳过，不触发 load / unobserve；
- null / missing entry guard 只防御异常 array-like 输入，真实 browser entries 不受影响；
- R579 的 single `querySelectorAll(selector)`、debug image count 和 fallback
  `loadAllImages()` 逻辑不变。

新增 `tests/test_validation_utils_lazy_loader_entries_loop_r580.py`：

- source invariant 锁定 `LazyLoader.init()` 不再出现 `entries.forEach((entry)`，
  并确认 `entryCount` / indexed loop / null guard / load + unobserve；
- Node VM runtime 构造 entries array-like 对象，其 `forEach()` 会 throw，验证
  observer callback 仍只处理 intersecting entries，并按顺序 load / unobserve；
- 覆盖 custom `loadingClass` config 透传，避免回调遍历优化误伤 loadImage 配置。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round107/01-mdn-intersectionobserver-callback-exa.json`
  保存 MDN IntersectionObserver 资料：observer callback 在 target visibility
  crossing threshold 时执行，`takeRecords()` / callback entries 是
  `IntersectionObserverEntry` 对象数组；一个 callback 可处理多个 target 的变化。
- `/tmp/smart-search-evidence/aiia-optimization-round107/02-mdn-array-index-loop-exa.json`
  保存 MDN Array / iterative methods 资料：array 可按 ascending index 遍历；
  `forEach()` 通过 callback 逐项执行。R580 用显式 index loop 保留顺序并移除 callback。

### 3.124 R581 · WebUI Quick Phrases renderList 去 forEach callback

`src/ai_intervention_agent/static/js/quick_phrases.js::renderList()` 每次 Quick
Phrases 状态变更后都会重建 chip 列表。旧实现先按使用频率排序，再用
`phrases.forEach(function (p, idx) { ... })` 创建 chip / edit / delete 三个控件：

```js
phrases = _sortPhrasesByUsage(phrases)

phrases.forEach(function (p, idx) {
  ...
  chip.addEventListener("click", function (e) {
    insertTextIntoFeedback(p.text)
    recordPhraseUsage(p.id)
  })
  ...
})
```

R581 改为显式 indexed loop：

```js
phrases = _sortPhrasesByUsage(phrases)

var phraseCount =
  phrases && Number.isFinite(phrases.length) ? phrases.length : 0
for (let idx = 0; idx < phraseCount; idx += 1) {
  if (!(idx in phrases)) continue
  let p = phrases[idx]
  ...
}
```

这里刻意使用 `let idx` / `let p`：旧 `forEach(function (p, idx) { ... })`
天然给每个 click handler 独立参数作用域；如果改成 `var` loop，chip / edit / delete
handler 会捕获同一个最终 `p`，造成所有按钮指向最后一条 phrase。`let` 保留每轮
block scope，避免为每条 phrase 增加 IIFE / helper wrapper。

行为边界：

- `_sortPhrasesByUsage(phrases)` 仍在渲染循环前执行，常用 phrase 继续排在前面；
- 前 9 条 chip 的 `data-shortcut-index` 与 shortcut title 逻辑不变；
- chip click 仍先 `insertTextIntoFeedback(p.text)`，再 `recordPhraseUsage(p.id)`；
- edit / delete click 仍分别使用当前 phrase 的 `p.id` / `p.label`；
- sparse hole 被显式跳过，对齐 `forEach()` 不访问 empty slots 的行为。

新增 / 更新测试：

- 新增 `tests/test_quick_phrases_render_loop_r581.py`：
  - source invariant 锁定 `renderList()` 不再出现
    `phrases.forEach(function (p, idx)`，并确认 `phraseCount` / indexed loop /
    sparse guard / `let p = phrases[idx]`；
  - Node VM runtime 在 `renderList()`、chip click、delete click 期间禁用
    `Array.prototype.forEach`，验证渲染顺序仍按 usage sort，chip click 插入的是
    当前 phrase text，使用计数只更新当前 phrase，delete click 删除当前 phrase；
  - 验证 input event dispatch / focus 仍发生，防止插入路径退化。
- 更新 `tests/test_quick_phrases_usage_sort_r131c.py`：排序顺序 invariant 从
  `phrases.forEach` 改为 `phraseCount` indexed loop。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round108/01-mdn-array-foreach-exa.json`
  保存 MDN `Array.prototype.forEach()` 资料：`forEach()` 按 ascending index 调用
  callback，只访问 assigned indexes，并会把 element / index 传给 callback。
- `/tmp/smart-search-evidence/aiia-optimization-round108/02-mdn-for-loop-exa.json`
  保存 MDN loops / iteration 资料：普通 `for` loop 可直接按 index 遍历 array；
  R581 用 `let` 保留每轮作用域和 handler 闭包语义。

### 3.125 R582 · WebUI Quick Phrases import parser 去 forEach callback

`src/ai_intervention_agent/static/js/quick_phrases.js::parseImportPayload()` 负责处理
用户导入的 Quick Phrases JSON。旧实现对 `parsed.phrases` 使用
`forEach(function (p) { ... })`，每个导入条目都会进入 callback 调度；在大导入文件、
包含历史脏数据的导入文件、或测试里主动禁用 `Array.prototype.forEach` 时，这条路径
既不够直接，也不利于保持 parser 的低层语义可控。

R582 改为显式 indexed loop：

```js
var phraseCount = parsed.phrases.length
for (var idx = 0; idx < phraseCount; idx += 1) {
  if (!(idx in parsed.phrases)) continue
  var p = parsed.phrases[idx]
  ...
}
```

关键点是把旧 callback 内的 `return` 全部改成 `continue`。旧 `return` 只跳过当前
entry；在 direct loop 中如果原样保留就会提前退出整个 `parseImportPayload()`，
导致「第一条脏数据后面的合法 phrase」被误丢。R582 同时保留
`if (!(idx in parsed.phrases)) continue`，显式对齐 `forEach()` 不访问 sparse
empty slots 的行为。

行为边界：

- JSON parse、signature、schema、空结果错误分支不变；
- invalid phrase 仍静默跳过，而不是 reject 整个导入文件；
- `label` / `text` 仍 trim 后校验，长度上限不变；
- `created_at` 仍只接受 finite number，否则回退 `Date.now()`；
- output shape 仍是 `{ ok: true, phrases: clean }`。

新增测试：

- `tests/test_quick_phrases_import_parse_loop_r582.py`
  - source invariant 锁定 `parseImportPayload()` 不再出现
    `parsed.phrases.forEach`，并确认 `phraseCount` / indexed loop / sparse guard /
    `continue` / `clean.push`；
  - Node VM runtime monkeypatch `JSON.parse` 返回 sparse `phrases` 数组，并禁用
    `Array.prototype.forEach`，验证 parser 会跳过 hole 和 invalid rows，继续保留后续
    valid rows，同时保持 trim 与 `created_at` fallback。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round109/01-mdn-array-foreach-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：`callbackFn` 只对 assigned indexes 调用，
  不访问 sparse array 的 empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round109/02-js-loop-callback-overhead.json`
  保存 MDN / V8 资料：`forEach()` 是 callback-based iterative method；V8 对数组
  fast path 的说明也强调通用 iterator / callback 机制会带来额外调度和对象处理成本，
  在可证明语义等价的固定数组扫描里 direct indexed loop 更可控。

验证：

- `uv run pytest tests/test_quick_phrases_import_parse_loop_r582.py
  tests/test_quick_phrases_import_export_r131b.py
  tests/test_quick_phrases_import_filereader_runtime_r452.py
  tests/test_quick_phrases_render_loop_r581.py
  tests/test_quick_phrases_usage_sort_r131c.py
  tests/test_quick_phrases_keyboard_shortcuts_r131d.py
  tests/test_quick_phrases_shortcut_lifecycle_r452.py` → 65 passed；
- `uv run ruff check tests/test_quick_phrases_import_parse_loop_r582.py`；
- `uv run ty check tests/test_quick_phrases_import_parse_loop_r582.py`；
- `node --check src/ai_intervention_agent/static/js/quick_phrases.js`；
- `node --check src/ai_intervention_agent/static/js/quick_phrases.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.126 R583 · WebUI Quick Phrases import merge 去 forEach callback

`src/ai_intervention_agent/static/js/quick_phrases.js::importPhrasesFromJson()` 的
merge 分支在 R582 parser 清理后仍有两段 callback iteration：

```js
existing.forEach(function (p) {
  existingKey[p.label + "\u0000" + p.text] = true
})

incoming.forEach(function (p) {
  if (existing.length >= MAX_PHRASES) {
    skipped += 1
    return
  }
  ...
})
```

这段代码负责导入合并的核心语义：先按 `(label, text)` 建本地去重 key，再扫描
incoming，重复项计入 `skipped`，容量满后的剩余 incoming 也逐条计入 `skipped`。
R583 把两段 callback 都改为显式 indexed loop：

```js
var existingCount = existing.length
for (var existingIdx = 0; existingIdx < existingCount; existingIdx += 1) {
  if (!(existingIdx in existing)) continue
  var p = existing[existingIdx]
  existingKey[p.label + "\u0000" + p.text] = true
}

var incomingCount = incoming.length
for (var incomingIdx = 0; incomingIdx < incomingCount; incomingIdx += 1) {
  if (!(incomingIdx in incoming)) continue
  var p2 = incoming[incomingIdx]
  ...
}
```

关键点：

- 旧 `incoming.forEach` 内的 `return` 只跳过当前 callback；R583 改为
  `continue`，避免错误提前退出整个 import；
- `incomingCount` 固定在 loop 前，保持 `forEach()` 对初始长度快照的等价边界；
- `idx in array` guard 保留 sparse hole skip 行为，虽然正常 parser 输出是 dense
  clean array；
- 容量满后仍继续扫描 incoming 并累计 `skipped`，保持 UI 的
  `importSuccessMerge({ added, skipped })` 反馈准确。

行为边界：

- replace 模式仍用 `incoming.slice(0, MAX_PHRASES)` 直接覆盖；
- merge 模式仍按 `(label, text)` 去重，不把导入文件中的 id 带入本地 storage；
- 新增 phrase 仍写入 `last_used_at: 0` / `use_count: 0`；
- `savePhrases(existing)`、`renderList()`、返回 `{ ok, added, skipped, total }`
  的顺序不变。

新增测试：

- `tests/test_quick_phrases_import_merge_loop_r583.py`
  - source invariant 锁定 `importPhrasesFromJson()` 不再出现 `existing.forEach`
    / `incoming.forEach`，并确认两个 indexed loop、hole guard、`continue` 与
    `skipped += 1`；
  - Node VM runtime 在 `MAX_PHRASES - 1` 的本地 storage 上导入
    duplicate + fill-slot + overflow 三条 incoming，并禁用
    `Array.prototype.forEach`；验证结果为 `added=1`、`skipped=2`、`total=20`，
    duplicate 未重复、overflow 未写入、导入新 phrase 的 usage 字段仍为 0，
    且 renderList 仍输出 20 个 chip。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round110/01-mdn-foreach-control-flow.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback return value 会被丢弃，
  `forEach()` 不能用普通控制流 break；因此 direct loop 迁移时必须把 callback
  `return` 翻译为当前迭代的 `continue`。
- `/tmp/smart-search-evidence/aiia-optimization-round110/02-mdn-for-loop-control-flow.json`
  保存 MDN loops / iteration 资料：传统 `for` loop 适合按 numeric index 遍历
  array，`continue` 会结束当前迭代并进入下一轮。

验证：

- `uv run pytest tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py
  tests/test_quick_phrases_import_export_r131b.py
  tests/test_quick_phrases_import_filereader_runtime_r452.py
  tests/test_quick_phrases_render_loop_r581.py
  tests/test_quick_phrases_usage_sort_r131c.py
  tests/test_quick_phrases_keyboard_shortcuts_r131d.py
  tests/test_quick_phrases_shortcut_lifecycle_r452.py` → 67 passed；
- `uv run ruff check tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py`；
- `uv run ty check tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py`；
- `node --check src/ai_intervention_agent/static/js/quick_phrases.js`；
- `node --check src/ai_intervention_agent/static/js/quick_phrases.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.127 R584 · WebUI Quick Phrases openEditForm 去 find callback

`src/ai_intervention_agent/static/js/quick_phrases.js::openEditForm(id)` 是 chip
编辑按钮的入口。旧实现每次编辑都调用：

```js
var phrase = loadPhrases().find(function (p) {
  return p.id === id
})
```

`Array.prototype.find()` 会按顺序调用 callback，直到 callback 返回 truthy 后停止。
本路径只需要在 `loadPhrases()` 已经规整出的 phrase 数组里按 id 找第一条匹配项；
直接 indexed loop 能保留 early-exit 行为，同时去掉每次 edit lookup 的 callback
调度。

R584 改为：

```js
var phrases = loadPhrases()
var phrase = null
for (var i = 0; i < phrases.length; i += 1) {
  var p = phrases[i]
  if (p.id === id) {
    phrase = p
    break
  }
}
if (!phrase) return
_openForm("edit", phrase)
```

行为边界：

- `loadPhrases()` 仍是唯一 storage 读取入口，继续负责 schema / 字段规整；
- duplicate id 这种异常历史数据仍按第一条匹配项打开编辑表单，对齐 `find()`；
- missing id 仍直接 no-op，不创建 form；
- `_openForm("edit", phrase)` 的 dataset、input 预填、focus、selection 逻辑不变。

新增测试：

- `tests/test_quick_phrases_open_edit_lookup_r584.py`
  - source invariant 锁定 `openEditForm()` 不再出现 `.find(`，并确认
    `loadPhrases()` / direct loop / `break` / `_openForm("edit", phrase)`；
  - Node VM runtime 写入两条相同 id 的 phrase，禁用 `Array.prototype.find` 后调用
    `api.openEditForm("same")`，验证 edit form 使用第一条 phrase 的 label/text、
    `dataset.qpMode === "edit"`、`dataset.qpEditId` 正确、text selection 停在末尾；
  - 关闭表单后调用 missing id，验证仍不创建 form。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round111/01-mdn-array-find-first.json`
  保存 MDN `Array.prototype.find()` 资料：`find()` 返回第一个满足 callback 的
  element，并在 callback 返回 truthy 后停止遍历；找不到时返回 `undefined`。
- `/tmp/smart-search-evidence/aiia-optimization-round111/02-mdn-for-loop-break.json`
  保存 MDN loops / iteration 资料：传统 `for` loop 可按 numeric index 遍历 array，
  `break` 会立即终止当前 loop。

验证：

- `uv run pytest tests/test_quick_phrases_open_edit_lookup_r584.py
  tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py
  tests/test_quick_phrases_import_export_r131b.py
  tests/test_quick_phrases_import_filereader_runtime_r452.py
  tests/test_quick_phrases_render_loop_r581.py
  tests/test_quick_phrases_usage_sort_r131c.py
  tests/test_quick_phrases_keyboard_shortcuts_r131d.py
  tests/test_quick_phrases_shortcut_lifecycle_r452.py
  tests/test_quick_phrases_edit_r131.py` → 88 passed；
- `uv run ruff check tests/test_quick_phrases_open_edit_lookup_r584.py
  tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py`；
- `uv run ty check tests/test_quick_phrases_open_edit_lookup_r584.py
  tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py`；
- `node --check src/ai_intervention_agent/static/js/quick_phrases.js`；
- `node --check src/ai_intervention_agent/static/js/quick_phrases.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.128 R585 · WebUI Quick Phrases shortcut register 去 forEach callback

`src/ai_intervention_agent/static/js/quick_phrases.js::setupKeyboardShortcuts()`
在存在全局 `window.KeyboardShortcuts.register` 时，会注册 Alt+1 到 Alt+9 的
Quick Phrases shortcut。旧实现使用：

```js
SHORTCUT_INDICES.forEach(function (i) {
  window.KeyboardShortcuts.register(
    SHORTCUT_PREFIX + String(i),
    function () {
      _activateShortcut(i)
    },
    { preventDefault: true, allowInInputs: true }
  )
})
```

这里 callback 参数 `i` 被后续 handler 闭包捕获；替换成 indexed loop 时不能把
单个 `var` loop 变量直接交给 handler，否则所有已注册 handler 都会读到 loop
结束后的同一个值。R585 使用 block-scoped `let shortcutIndex` 保留每一轮注册的
独立 capture：

```js
for (var shortcutIdx = 0; shortcutIdx < SHORTCUT_INDICES.length; shortcutIdx += 1) {
  let shortcutIndex = SHORTCUT_INDICES[shortcutIdx]
  window.KeyboardShortcuts.register(
    SHORTCUT_PREFIX + String(shortcutIndex),
    function () {
      _activateShortcut(shortcutIndex)
    },
    { preventDefault: true, allowInInputs: true }
  )
}
```

行为边界：

- 只调整 `KeyboardShortcuts.register` 存在时的注册 loop；fallback
  `document.addEventListener("keydown", ...)` 路径不变；
- `bound` idempotence guard 不变，`setupKeyboardShortcuts()` 仍只绑定一次；
- 每个 register 失败仍被单独 `try/catch` 吞掉，并继续尝试后续 shortcut；
- shortcut 名称仍是 `alt+1` 到 `alt+9`，options 仍是
  `{ preventDefault: true, allowInInputs: true }`；
- handler 仍调用 `_activateShortcut()`，因此 phrase 排序、使用计数、textarea
  插入、input event、focus 行为全部沿用原路径。

新增测试：

- `tests/test_quick_phrases_shortcut_register_loop_r585.py`
  - source invariant 锁定 `setupKeyboardShortcuts()` 不再出现
    `SHORTCUT_INDICES.forEach`，并确认 indexed loop、`let shortcutIndex`、
    `SHORTCUT_PREFIX + String(shortcutIndex)`、`_activateShortcut(shortcutIndex)`；
  - Node VM runtime 禁用 `Array.prototype.forEach` 后调用
    `api.setupKeyboardShortcuts()`，验证注册了 `alt+1` 到 `alt+9`、所有 options
    不变、触发第一和第九个 handler 后 textarea 得到 `OneNine`、对应 phrase
    use count 增加，并产生两次 input event / focus。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round112/01-mdn-foreach-order.json`
  保存 MDN `Array.prototype.forEach()` 资料：`forEach()` 按升序 index 为数组中
  已存在的元素调用 callback。
- `/tmp/smart-search-evidence/aiia-optimization-round112/02-mdn-let-block-scope.json`
  保存 MDN `let` 资料：`let` 声明是 block scoped；用于 loop body 内的
  `shortcutIndex` 可以为每个 registered handler 保留独立绑定。

验证：

- `uv run pytest tests/test_quick_phrases_shortcut_register_loop_r585.py` → 2 passed；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run pytest tests/test_quick_phrases_shortcut_register_loop_r585.py
  tests/test_quick_phrases_open_edit_lookup_r584.py
  tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py
  tests/test_quick_phrases_import_export_r131b.py
  tests/test_quick_phrases_import_filereader_runtime_r452.py
  tests/test_quick_phrases_render_loop_r581.py
  tests/test_quick_phrases_usage_sort_r131c.py
  tests/test_quick_phrases_keyboard_shortcuts_r131d.py
  tests/test_quick_phrases_shortcut_lifecycle_r452.py
  tests/test_quick_phrases_edit_r131.py` → 90 passed；
- `uv run ruff check tests/test_quick_phrases_shortcut_register_loop_r585.py
  tests/test_quick_phrases_open_edit_lookup_r584.py
  tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py`；
- `uv run ty check tests/test_quick_phrases_shortcut_register_loop_r585.py
  tests/test_quick_phrases_open_edit_lookup_r584.py
  tests/test_quick_phrases_import_merge_loop_r583.py
  tests/test_quick_phrases_import_parse_loop_r582.py`；
- `node --check src/ai_intervention_agent/static/js/quick_phrases.js`；
- `node --check src/ai_intervention_agent/static/js/quick_phrases.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.129 R586 · WebUI app modal focus trap 去 filter array

`src/ai_intervention_agent/static/js/app.js::_modalFocusTrap(panel, event)` 是
code-paste modal 的 Tab / Shift+Tab 焦点闭环。旧实现每次 Tab keydown 都先取
modal 内全部可聚焦元素，然后用 `Array.prototype.filter.call(...)` 生成一份
`visible` 数组：

```js
const visible = Array.prototype.filter.call(
  focusables,
  (el) => el.offsetParent !== null && !el.hasAttribute("aria-hidden"),
)
if (visible.length === 0) return
const first = visible[0]
const last = visible[visible.length - 1]
```

这个路径只需要 first / last 两个可见节点来判断是否 wrap focus；不需要保留完整
可见节点数组。R586 改为单次 indexed scan：

```js
let first = null
let last = null
const focusableCount =
  focusables && Number.isFinite(focusables.length) ? focusables.length : 0
for (let i = 0; i < focusableCount; i += 1) {
  const el = focusables[i]
  if (!el || el.offsetParent === null || el.hasAttribute("aria-hidden")) {
    continue
  }
  if (!first) first = el
  last = el
}
if (!first || !last) return
```

行为边界：

- `event.key !== "Tab"` 的 early return 不变，Escape 仍由 caller 处理；
- focusable selector 不变，仍覆盖 button / link / input / select / textarea /
  tabindex；
- visible 判定不变，仍排除 `offsetParent === null` 和 `aria-hidden` 元素；
- 没有可见 focusable 时仍 no-op；
- active 为 first 且 Shift+Tab 时仍 `preventDefault()` 后 focus last；
- active 为 last 且 Tab 时仍 `preventDefault()` 后 focus first；
- settings panel 的 `_settingsFocusTrap()` 本轮不改，作为独立 follow-up，避免两个
  modal surface 的测试边界混在一起。

新增测试：

- `tests/test_app_modal_focus_trap_loop_r586.py`
  - source invariant 锁定 `_modalFocusTrap()` 不再出现
    `Array.prototype.filter.call` / `.filter(`，并确认 first / last 单次 loop、
    `aria-hidden` 判定和 `event.preventDefault()`；
  - Node VM runtime 禁用 `Array.prototype.filter` 后，构造 visible / hidden /
    aria-hidden 混合 NodeList-like 集合，验证 last+Tab wrap 到 first、
    first+Shift+Tab wrap 到 last，Escape 不触发 query / preventDefault。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round113/01-mdn-array-filter-new-array.json`
  保存 MDN `Array.prototype.filter()` 资料：`filter()` 会调用 callback，并构造 /
  返回包含通过测试元素的新 shallow-copy 数组。
- `/tmp/smart-search-evidence/aiia-optimization-round113/02-wai-aria-modal-dialog-tab.json`
  保存 W3C/WAI dialog focus-management 资料：自定义 modal dialog 激活时要把焦点
  移入 dialog，保持焦点在 dialog 内，关闭后把焦点还给触发控件。

验证：

- `uv run pytest tests/test_app_modal_focus_trap_loop_r586.py` → 2 passed；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run pytest tests/test_app_modal_focus_trap_loop_r586.py
  tests/test_modal_focus_trap_invariant_r238.py
  tests/test_modal_inert_background_invariant_r240.py
  tests/test_minify_precommit_hook_invariant_r242.py
  tests/test_app_submit_cleanup_nodelist_loop_r578.py
  tests/test_app_submit_options_nodelist_loop_r577.py
  tests/test_app_lottie_fallback_svg_nodelist_r560.py` → 29 passed；
- `uv run ruff check tests/test_app_modal_focus_trap_loop_r586.py`；
- `uv run ty check tests/test_app_modal_focus_trap_loop_r586.py`；
- `node --check src/ai_intervention_agent/static/js/app.js`；
- `node --check src/ai_intervention_agent/static/js/app.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.130 R587 · WebUI settings modal focus trap 去 filter array

`src/ai_intervention_agent/static/js/settings-manager.js::_settingsFocusTrap(panel, event)`
是 settings panel 的 Tab / Shift+Tab 焦点闭环。R586 已处理 code-paste modal；
settings 侧仍保留同构实现：

```js
const visible = Array.prototype.filter.call(
  focusables,
  (el) => el.offsetParent !== null && !el.hasAttribute("aria-hidden"),
)
if (visible.length === 0) return
const first = visible[0]
const last = visible[visible.length - 1]
```

本路径同样只需要 first / last 两个可见节点来判断 wrap focus。R587 改为单次
indexed scan，避免每次 Tab keydown 分配完整 `visible` 数组：

```js
let first = null
let last = null
const focusableCount =
  focusables && Number.isFinite(focusables.length) ? focusables.length : 0
for (let i = 0; i < focusableCount; i += 1) {
  const el = focusables[i]
  if (!el || el.offsetParent === null || el.hasAttribute("aria-hidden")) {
    continue
  }
  if (!first) first = el
  last = el
}
if (!first || !last) return
```

行为边界：

- `_attachSettingsKeydownHandler()` 仍只在 `e.key === "Tab"` 时调用
  `_settingsFocusTrap(panel, e)`，Escape 仍优先调用 `hideSettings()`；
- focusable selector 不变，继续覆盖 button / link / input / select / textarea /
  tabindex；
- visible 判定不变，仍排除 `offsetParent === null` 与 `aria-hidden` 元素；
- 没有可见 focusable 时仍 no-op；
- active 为 first 且 Shift+Tab 时仍 `preventDefault()` 后 focus last；
- active 为 last 且 Tab 时仍 `preventDefault()` 后 focus first；
- `hideSettings()` 的 scroll-safe focus restore、settings background inert 逻辑不变。

新增测试：

- `tests/test_settings_focus_trap_loop_r587.py`
  - source invariant 锁定 `_settingsFocusTrap()` 不再出现
    `Array.prototype.filter.call` / `.filter(`，并确认 first / last 单次 loop、
    `aria-hidden` 判定和 `event.preventDefault()`；
  - Node VM runtime 抽取 class method，在禁用 `Array.prototype.filter` 后构造
    visible / hidden / aria-hidden 混合 NodeList-like 集合，验证 last+Tab wrap 到
    first、first+Shift+Tab wrap 到 last、空集合 no-op。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round114/01-mdn-array-filter-new-array.json`
  保存 MDN `Array.prototype.filter()` 资料：`filter()` 会调用 callback，并构造 /
  返回包含通过测试元素的新 shallow-copy 数组。
- `/tmp/smart-search-evidence/aiia-optimization-round114/02-wai-modal-dialog-focus-management.json`
  保存 W3C/WAI dialog 资料：modal dialog 的 Tab 从最后一个 focusable 回到第一个，
  Shift+Tab 从第一个回到最后一个；关闭后应恢复用户焦点位置。

验证：

- `uv run pytest tests/test_settings_focus_trap_loop_r587.py` → 2 passed；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run pytest tests/test_settings_focus_trap_loop_r587.py
  tests/test_modal_focus_trap_invariant_r238.py
  tests/test_modal_inert_background_invariant_r240.py
  tests/test_settings_manager_dom_null_safe_r452.py
  tests/test_settings_manager_init_singleflight_r452.py
  tests/test_settings_manager_language_change_r452.py
  tests/test_settings_manager_backend_sync_queue_r452.py
  tests/test_settings_manager_feedback_config_save_queue_r452.py
  tests/test_settings_manager_custom_sound_upload_runtime_r452.py` → 45 passed；
- `uv run ruff check tests/test_settings_focus_trap_loop_r587.py`；
- `uv run ty check tests/test_settings_focus_trap_loop_r587.py`；
- `node --check src/ai_intervention_agent/static/js/settings-manager.js`；
- `node --check src/ai_intervention_agent/static/js/settings-manager.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.131 R588 · WebUI app processCodeBlocks 去 NodeList forEach callback

`src/ai_intervention_agent/static/js/app.js::processCodeBlocks(container)` 在
Markdown 渲染后处理每个 `<pre>`：包一层 `.code-block-container`、识别
`language-*`、创建 toolbar 和 copy button。旧实现直接对
`container.querySelectorAll("pre")` 返回的 NodeList 调用：

```js
codeBlocks.forEach((pre) => {
  if (
    pre.parentElement &&
    pre.parentElement.classList.contains("code-block-container")
  ) {
    return
  }
  ...
})
```

这个 callback `return` 只表示“跳过当前 pre”，不是退出整个处理流程。R588 改为
length-cached indexed loop，并把 callback `return` 精确翻译为 `continue`：

```js
const codeBlockCount =
  codeBlocks && Number.isFinite(codeBlocks.length) ? codeBlocks.length : 0
for (let codeBlockIndex = 0; codeBlockIndex < codeBlockCount; codeBlockIndex += 1) {
  const pre = codeBlocks[codeBlockIndex]
  if (!pre) continue
  if (
    pre.parentElement &&
    pre.parentElement.classList.contains("code-block-container")
  ) {
    continue
  }
  ...
}
```

行为边界：

- selector 仍是 `pre`，仍只处理当前 render container 内的 code block；
- 已经被 `.code-block-container` 包裹的 `<pre>` 仍跳过，避免重复 toolbar；
- language detection 仍读取 `pre.querySelector("code").className` 的
  `language-(\w+)`；
- `language !== "text"` 时仍添加 uppercase language label；
- copy button 仍由 `DOMSecurity.createCopyButton(pre.textContent || "")` 创建；
- wrapper 插入顺序仍是先 `insertBefore(codeContainer, pre)`，再把 `pre` append
  到 wrapper，最后 append toolbar。

新增测试：

- `tests/test_app_process_code_blocks_loop_r588.py`
  - source invariant 锁定 `processCodeBlocks()` 不再出现 `codeBlocks.forEach`，
    并确认 indexed loop、空 slot guard、`continue` 和
    `DOMSecurity.createCopyButton(pre.textContent || "")`；
  - Node VM runtime 构造 NodeList-like 集合并让 `forEach()` 抛错，验证 already
    wrapped `<pre>` 不移动，未处理 `<pre><code class="language-js">` 被正确包裹、
    toolbar / language label / copy button 均按旧路径生成。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round115/01-mdn-queryselectorall-static-nodelist.json`
  保存 MDN `querySelectorAll()` 资料：返回 non-live/static NodeList，元素按
  document order 排列。
- `/tmp/smart-search-evidence/aiia-optimization-round115/02-mdn-nodelist-foreach-callback.json`
  保存 MDN `NodeList.forEach()` 资料：会按 insertion order 为每个 value 调用
  callback。

验证：

- `uv run pytest tests/test_app_process_code_blocks_loop_r588.py` → 2 passed；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run pytest tests/test_app_process_code_blocks_loop_r588.py
  tests/test_render_markdown_cache.py
  tests/test_lazy_markdown_r26_3.py
  tests/test_feat_loadconfig_copyclipboard_null_check_r285.py
  tests/test_app_toast_runtime_r452.py
  tests/test_app_lottie_fallback_svg_nodelist_r560.py
  tests/test_app_modal_focus_trap_loop_r586.py
  tests/test_minify_precommit_hook_invariant_r242.py` → 53 passed；
- `uv run ruff check tests/test_app_process_code_blocks_loop_r588.py`；
- `uv run ty check tests/test_app_process_code_blocks_loop_r588.py`；
- `node --check src/ai_intervention_agent/static/js/app.js`；
- `node --check src/ai_intervention_agent/static/js/app.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.132 R589 · WebUI app processStrikethrough 去 textNodes forEach callback

`src/ai_intervention_agent/static/js/app.js::processStrikethrough(container)` 用
`document.createTreeWalker(..., NodeFilter.SHOW_TEXT, ...)` 收集非 code/pre/script/style
内的文本节点，再把 `~~text~~` 替换成安全的 DOM fragment。旧实现先 snapshot：

```js
const textNodes = []
let node
while ((node = walker.nextNode())) {
  textNodes.push(node)
}
```

随后用 `textNodes.forEach((textNode) => { ... })` 处理。这个 snapshot 是正确边界：
替换 text node 会改变 DOM tree，先收集再变更可以避免 traversal 与 mutation
相互干扰。本轮只去掉 post-snapshot callback dispatch，不改变 snapshot 策略：

```js
for (let textNodeIndex = 0; textNodeIndex < textNodes.length; textNodeIndex += 1) {
  const textNode = textNodes[textNodeIndex]
  const text = textNode.textContent
  const strikethroughRegex = /~~([^~\n]+?)~~/g

  if (!strikethroughRegex.test(text)) continue
  const parts = text.split(/~~([^~\n]+?)~~/)
  if (parts.length <= 1) continue
  ...
}
```

行为边界：

- TreeWalker root、`NodeFilter.SHOW_TEXT`、accept/reject 规则不变；
- CODE / PRE / SCRIPT / STYLE 及其 descendants 仍被 reject；
- 文本节点仍先 snapshot 到 `textNodes`，再执行 DOM replacement；
- 无 `~~...~~` 的文本节点仍跳过；
- 多段 strikethrough 仍生成 text / `del` 交替 fragment；
- replacement 仍使用 `document.createTextNode()` 和 `document.createElement("del")`，
  不引入 `innerHTML`。

新增测试：

- `tests/test_app_strikethrough_loop_r589.py`
  - source invariant 锁定 `processStrikethrough()` 不再出现 `textNodes.forEach`，
    并确认 indexed loop、`continue`、TreeWalker 与 `NodeFilter.SHOW_TEXT`；
  - Node VM runtime 禁用 `Array.prototype.forEach`，构造 accepted / rejected text
    nodes，验证 code 与 nested-code 文本被 reject，普通文本不替换，单段和多段
    `~~...~~` 都生成正确的 text / `DEL` fragment。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round116/01-mdn-treewalker-nextnode.json`
  保存 MDN `Document.createTreeWalker()` 资料：TreeWalker 可用
  `NodeFilter.SHOW_TEXT` 遍历文本节点，并用 `acceptNode()` 返回 accept/reject。
- `/tmp/smart-search-evidence/aiia-optimization-round116/02-mdn-array-foreach-control-flow.json`
  保存 MDN `Array.prototype.forEach()` 资料：`forEach()` 为元素调用 callback，
  callback return value 会被丢弃，不能用普通控制流 break。

验证：

- `uv run pytest tests/test_app_strikethrough_loop_r589.py` → 2 passed；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run pytest tests/test_app_strikethrough_loop_r589.py
  tests/test_app_process_code_blocks_loop_r588.py
  tests/test_render_markdown_cache.py
  tests/test_lazy_markdown_r26_3.py
  tests/test_feat_loadconfig_copyclipboard_null_check_r285.py
  tests/test_app_toast_runtime_r452.py
  tests/test_app_lottie_fallback_svg_nodelist_r560.py
  tests/test_app_modal_focus_trap_loop_r586.py
  tests/test_minify_precommit_hook_invariant_r242.py` → 55 passed；
- `uv run ruff check tests/test_app_strikethrough_loop_r589.py`；
- `uv run ty check tests/test_app_strikethrough_loop_r589.py`；
- `node --check src/ai_intervention_agent/static/js/app.js`；
- `node --check src/ai_intervention_agent/static/js/app.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.133 R590 · WebUI app predefined options render 去 forEach callback

`src/ai_intervention_agent/static/js/app.js::loadConfig()` 在配置加载成功后渲染
`config.predefined_options`。旧实现用 `forEach((option, index) => { ... })`，
`index` 同时决定 checkbox id、label `htmlFor` 和
`predefined_options_defaults[index]`：

```js
config.predefined_options.forEach((option, index) => {
  const optionDiv = document.createElement("div")
  optionDiv.className = "option-item"
  ...
  checkbox.id = `option-${index}`
  checkbox.value = option
  checkbox.checked = optionDefaults[index] === true
  ...
})
```

R590 改为 indexed loop，去掉每个 option 的 callback 调度；同时保留
`forEach()` 对 sparse array hole 的跳过语义：

```js
const predefinedOptionCount = config.predefined_options.length
for (let index = 0; index < predefinedOptionCount; index += 1) {
  if (!(index in config.predefined_options)) continue
  const option = config.predefined_options[index]
  ...
}
```

行为边界：

- options render 仍只在 `config.predefined_options.length > 0` 且
  `#options-container` / `#separator` 都存在时执行；
- option 顺序、index-derived `option-${index}` id、label `htmlFor` 不变；
- `optionDefaults[index] === true` 的默认选中逻辑不变；
- checked option 仍给 wrapper 添加 `.selected`；
- `optionsContainer.style.display = "block"` 和 `separator.style.display = "block"`
  仍在 options append 完成后执行；
- sparse array hole 仍跳过，避免 direct loop 比旧 `forEach()` 多渲染
  `undefined` option。

新增测试：

- `tests/test_app_predefined_options_loop_r590.py`
  - source invariant 锁定 `loadConfig()` 不再出现
    `config.predefined_options.forEach`，并确认 indexed loop、sparse guard、
    index-derived id/default 逻辑；
  - Node VM runtime 让 `predefined_options.forEach()` 抛错，并构造含 sparse hole
    的 options，验证渲染顺序、checkbox id/value/checked、label `htmlFor`、
    `.selected` class、container/separator display 与旧行为一致。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round117/01-mdn-array-foreach-order-return.json`
  保存 MDN `Array.prototype.forEach()` 资料：`forEach()` 按 ascending-index order
  调用 callback，callback return value 会被丢弃，并跳过 sparse array empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round117/02-mdn-for-statement-loop.json`
  保存 MDN loop 资料：`for` loop 可用 index 按数组 length 顺序访问元素；本轮用
  `index in array` 补齐 `forEach()` 的 sparse-skip 语义。

验证：

- `uv run pytest tests/test_app_predefined_options_loop_r590.py
  tests/test_feat_loadconfig_copyclipboard_null_check_r285.py
  tests/test_predefined_options_defaults_ui_r457.py
  tests/test_app_submit_options_nodelist_loop_r577.py
  tests/test_app_submit_cleanup_nodelist_loop_r578.py
  tests/test_app_submit_feedback_stale_task_r452.py
  tests/test_app_toast_runtime_r452.py
  tests/test_app_strikethrough_loop_r589.py
  tests/test_app_process_code_blocks_loop_r588.py
  tests/test_minify_precommit_hook_invariant_r242.py` → 38 passed；
- `uv run ruff check tests/test_app_predefined_options_loop_r590.py`；
- `uv run ty check tests/test_app_predefined_options_loop_r590.py`；
- `node --check src/ai_intervention_agent/static/js/app.js`；
- `node --check src/ai_intervention_agent/static/js/app.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.134 R591 · WebUI shortcut display 去 Object.entries allocation

`src/ai_intervention_agent/static/js/app.js::updateShortcutDisplay(platform)`
只更新 5 个固定 shortcut hint DOM 节点。旧实现先构造 object literal，再用
`Object.entries(shortcuts).forEach(([id, shortcut]) => { ... })`：

```js
const shortcuts = {
  "shortcut-submit": `${ctrlOrCmd}+Enter`,
  "shortcut-code": `${altOrOption}+C`,
  ...
}

Object.entries(shortcuts).forEach(([id, shortcut]) => {
  const element = document.getElementById(id)
  if (element) {
    element.textContent = shortcut
  }
})
```

这个路径的 key set 是静态的，不需要每次生成 `[key, value]` entries array，
也不需要 callback/destructuring 调度。R591 改为共享小 setter + 5 次直接调用：

```js
function setShortcutText(id, shortcut) {
  const element = document.getElementById(id)
  if (element) {
    element.textContent = shortcut
  }
}

setShortcutText("shortcut-submit", `${ctrlOrCmd}+Enter`)
setShortcutText("shortcut-code", `${altOrOption}+C`)
...
```

行为边界：

- `platform === "mac"` 仍显示 `Cmd` / `Option`；
- 非 mac 平台仍显示 `Ctrl` / `Alt`；
- 5 个 DOM id 和 text 内容不变；
- 缺失 DOM 节点仍静默跳过，不创建元素、不抛错；
- `document.getElementById()` 调用次数与旧实现一致，仍是每个 id 一次。

新增测试：

- `tests/test_app_shortcut_display_direct_r591.py`
  - source invariant 锁定 `updateShortcutDisplay()` 不再出现 `Object.entries`、
    `.forEach(` 或 `const shortcuts =`，并确认 5 个直接 setter 调用；
  - Node VM runtime 禁用 `Object.entries()`，分别执行 mac 与非 mac 平台，验证
    shortcut text、调用顺序与缺失 `shortcut-upload` 的 skip 语义。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round118/07-exa-mdn-object-entries-exact.json`
  保存 MDN `Object` 资料：`Object.entries()` 返回给定对象 own enumerable string
  properties 的 `[key, value]` pair array；固定 key set 不需要这层数组物化。
- `/tmp/smart-search-evidence/aiia-optimization-round118/05-exa-mdn-getelementbyid.json`
  保存 MDN `Document.getElementById()` 资料：按 id 返回 Element，未找到时返回
  `null`；本轮继续保留 null skip。
- `/tmp/smart-search-evidence/aiia-optimization-round118/06-exa-mdn-for-statement.json`
  保存 MDN loop 资料：重复执行固定语句可直接由显式语句/loop 控制；本轮固定 5
  个 id 时直接展开更少抽象和分配。

验证：

- `uv run pytest tests/test_app_shortcut_display_direct_r591.py
  tests/test_keyboard_shortcuts_runtime_r452.py
  tests/test_keyboard_shortcut_help_r144.py
  tests/test_settings_shortcuts_full_help_hint_invariant_r223.py
  tests/test_shortcuts_notification_body_completeness_invariant_r228.py
  tests/test_minify_precommit_hook_invariant_r242.py` → 61 passed；
- `uv run ruff check tests/test_app_shortcut_display_direct_r591.py`；
- `uv run ty check tests/test_app_shortcut_display_direct_r591.py`；
- `node --check src/ai_intervention_agent/static/js/app.js`；
- `node --check src/ai_intervention_agent/static/js/app.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.135 R592 · WebUI notification permission listener 去 fixed-array forEach

`src/ai_intervention_agent/static/js/notification-manager.js::bindAutoPermissionRequest()`
和 `removeAutoPermissionRequestListeners()` 只绑定/解绑 3 个固定事件：
`click`、`keydown`、`touchstart`。旧实现每次 bind/remove 都构造 array literal，
再用 `forEach()` callback 调 `addEventListener()` / `removeEventListener()`：

```js
;['click', 'keydown', 'touchstart'].forEach(eventName => {
  document.addEventListener(eventName, this.boundPermissionRequestHandler, {
    once: true,
    passive: true
  })
})
```

R592 把固定事件展开为两个小 helper，并把 add path 的 listener options 提到
模块常量：

```js
const AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS = {
  once: true,
  passive: true
}

addAutoPermissionRequestListeners() {
  const handler = this.boundPermissionRequestHandler
  document.addEventListener('click', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)
  document.addEventListener('keydown', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)
  document.addEventListener('touchstart', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)
}
```

行为边界：

- 仍只在 supported + secure context + permission `default` + config 允许时绑定；
- 绑定事件名、顺序、handler 对象不变；
- `addEventListener()` 仍使用 `{ once: true, passive: true }`；
- remove path 仍对同一个 handler 解绑同一组事件；
- re-arm / terminal permission response lifecycle 继续由 R452 runtime tests 覆盖。

新增测试：

- `tests/test_notification_permission_listener_direct_r592.py`
  - source invariant 锁定旧 `['click', 'keydown', 'touchstart'].forEach` 不再出现，
    并确认 bind/remove helper 都是直接 event call；
  - Node VM runtime 在禁用 `Array.prototype.forEach` 后执行 bind/remove，验证
    add/remove 事件顺序、options、same-handler cleanup、bound flag 和 handler
    reset 语义。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round119/01-exa-mdn-array-foreach.json`
  保存 MDN `Array.prototype.forEach()` 资料：`forEach()` 会为数组元素调用
  callback，callback return value 被丢弃；固定 3 个事件不需要 callback 调度。
- `/tmp/smart-search-evidence/aiia-optimization-round119/02-exa-mdn-eventtarget-listeners.json`
  保存 MDN `EventTarget` 资料：`addEventListener()` 注册 handler，
  `removeEventListener()` 解绑 handler；本轮保留这两个 API 的调用语义。
- `/tmp/smart-search-evidence/aiia-optimization-round119/03-exa-mdn-loop.json`
  保存 MDN loop 资料：固定重复动作可由显式语句/loop 表达；本轮固定 3 个事件
  直接展开，减少运行期分配与 callback 开销。

验证：

- `uv run pytest tests/test_notification_permission_listener_direct_r592.py
  tests/test_notification_manager_permission_lifecycle_r452.py
  tests/test_notification_manager_inpage_lifecycle_r452.py
  tests/test_notification_fallback_events_bounded_r552.py
  tests/test_notification_fallback_toast_invariant_r214.py
  tests/test_minify_precommit_hook_invariant_r242.py` → 28 passed, 30 subtests passed；
- `uv run ruff check tests/test_notification_permission_listener_direct_r592.py`；
- `uv run ty check tests/test_notification_permission_listener_direct_r592.py`；
- `node --check src/ai_intervention_agent/static/js/notification-manager.js`；
- `node --check src/ai_intervention_agent/static/js/notification-manager.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.136 R593 · WebUI theme toggle buttons 去 NodeList forEach callback

`src/ai_intervention_agent/static/js/theme.js::updateToggleButton()` 和
`bindExistingButtons()` 都遍历 `document.querySelectorAll('.theme-toggle-btn')`
返回的按钮集合。旧实现使用 `buttons.forEach(button => { ... })`：

```js
const buttons = document.querySelectorAll('.theme-toggle-btn')
buttons.forEach(button => {
  button.classList.toggle('is-light', effectiveTheme === THEMES.LIGHT)
  button.classList.toggle('is-auto', currentTheme === THEMES.AUTO)
  button.setAttribute('aria-label', label)
  button.setAttribute('title', label)
})
```

R593 改为 length snapshot + indexed loop：

```js
const buttonCount = buttons.length
for (let index = 0; index < buttonCount; index += 1) {
  const button = buttons[index]
  if (!button) continue
  ...
}
```

这样保留 `querySelectorAll()` 的静态 NodeList 语义，同时去掉两个 callback
dispatch；`if (!button) continue` 让测试 harness 或非标准 DOM polyfill 返回
sparse/空槽时不比旧路径更脆。

行为边界：

- `updateToggleButton()` 仍更新每个 `.theme-toggle-btn` 的 `.is-light`、
  `.is-auto`、`aria-label` 和 `title`；
- `bindExistingButtons()` 仍只给缺 `data-theme-bound` 的按钮绑定一次 click；
- `ThemeManager.init()` 仍可重复调用，storage / media listeners 仍单安装；
- `setTheme('light')` / auto mode effective theme 状态仍按原逻辑同步到按钮。

新增测试：

- `tests/test_theme_toggle_buttons_index_loop_r593.py`
  - source invariant 锁定 `updateToggleButton()` / `bindExistingButtons()` 不再
    使用 `buttons.forEach`，并确认两个函数都使用 indexed loop；
  - Node VM runtime 让 `querySelectorAll('.theme-toggle-btn')` 返回
    `forEach()` 会抛错的 NodeList-like 对象，验证双按钮 update、重复 init
    不重复绑定、`setTheme('light')` 状态同步、storage listener 单安装。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round120/01-exa-mdn-queryselectorall-nodelist.json`
  保存 MDN `querySelectorAll()` 资料：返回 static / non-live `NodeList`，元素按
  document order；本轮缓存 `length` 不会错过后续 DOM 变更。
- `/tmp/smart-search-evidence/aiia-optimization-round120/02-exa-mdn-nodelist-foreach.json`
  保存 MDN `NodeList.forEach()` 资料：它会按 insertion order 为每个 value
  调用 callback；本轮去掉 callback 调度。
- `/tmp/smart-search-evidence/aiia-optimization-round120/03-exa-mdn-for-loop.json`
  保存 MDN `for` loop 资料：`for` statement 通过初始化、条件、afterthought
  控制重复执行；适合这里的 length-indexed NodeList 遍历。

验证：

- `uv run pytest tests/test_theme_toggle_buttons_index_loop_r593.py
  tests/test_theme_manager_lifecycle_r452.py
  tests/test_feat_cycle10_theme_cross_tab_sync.py
  tests/test_feat_perf_audit_cycle3_anti_fouc.py
  tests/test_minify_precommit_hook_invariant_r242.py` → 32 passed；
- `uv run ruff check tests/test_theme_toggle_buttons_index_loop_r593.py`；
- `uv run ty check tests/test_theme_toggle_buttons_index_loop_r593.py`；
- `node --check src/ai_intervention_agent/static/js/theme.js`；
- `node --check src/ai_intervention_agent/static/js/theme.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.137 R594 · WebUI MathJax pending elements flush 去 forEach callback

`src/ai_intervention_agent/static/js/mathjax-loader.js` 在 MathJax
`startup.ready` 后会遍历 `window._mathJaxPendingElements`，为加载期间排队的
公式容器逐个调用 `MathJax.typesetPromise([el])`。旧实现使用：

```js
window._mathJaxPendingElements.forEach(el => {
  MathJax.typesetPromise([el]).catch(err => console.warn('MathJax render failed:', err))
})
```

R594 改成 length snapshot + indexed loop：

```js
const pendingElements = window._mathJaxPendingElements
const pendingElementCount = pendingElements.length
for (let index = 0; index < pendingElementCount; index += 1) {
  if (!(index in pendingElements)) continue
  const el = pendingElements[index]
  MathJax.typesetPromise([el]).catch(err => console.warn('MathJax render failed:', err))
}
```

这样去掉每个待渲染元素的一次 arrow callback dispatch，同时显式保留
`Array.prototype.forEach()` 的关键边界：加载完成前已存在的元素按升序处理、
稀疏空槽不调用回调、遍历范围在开始前固定。`typesetPromise().catch(...)`
仍逐元素安装，单个公式渲染失败不会阻断后续元素。

行为边界：

- `MathJax.startup.defaultReady()` 仍先执行；
- pending 队列按原顺序逐个传给 `MathJax.typesetPromise([el])`；
- sparse hole 仍跳过，显式 `undefined` 元素仍会作为已存在槽传入；
- flush 中新 append 到旧 pending array 的元素不会被本轮遍历访问，保持
  `forEach()` range snapshot 语义；
- flush 完成后仍把 `window._mathJaxPendingElements` 重置为新空数组。

新增测试：

- `tests/test_mathjax_pending_elements_loop_r594.py`
  - source invariant 锁定 `startup.ready` 不再使用 `.forEach()`，并确认
    `pendingElementCount`、indexed loop、hole skip 和队列重置；
  - Node VM runtime 禁用 `Array.prototype.forEach`，构造含 sparse hole 的
    pending queue，并在首个 `typesetPromise` 中追加新元素，验证只处理
    snapshot 内的 present slots；同时让第二个元素 reject，确认 warn catch
    仍触发且第三个元素继续处理。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round121/03-mdn-foreach-exa.json`
  保存 MDN `Array.prototype.forEach()` 文本：callback 按 ascending-index order
  对每个已赋值元素调用，empty slots 不调用；同时说明它读取 `length`
  并访问小于 `length` 的整数键。
- `/tmp/smart-search-evidence/aiia-optimization-round121/04-foreach-spec-exa.json`
  保存 TC39/MDN 资料：`forEach` 的处理范围在第一次 callback 前确定，
  appended elements 不会被访问，删除/缺失元素不访问。
- `/tmp/smart-search-evidence/aiia-optimization-round121/02-foreach-callback-overhead-search.json`
  保存 loop/callback overhead 搜索资料：indexed `for` loop 可避免
  `forEach` 的逐元素 callback 调用开销。

验证：

- `uv run pytest tests/test_mathjax_pending_elements_loop_r594.py
  tests/test_browser_perf_r20_12.py::TestMathjaxLoaderDefer
  tests/test_critical_preload_r21_1.py::TestPreloadDoesNotIncludeAntiPattern::test_mathjax_loader_not_preloaded
  tests/test_integration.py::TestWebFeedbackUIFlaskApp::test_multi_task_mathjax_lazy_load_present
  tests/test_integration.py::TestWebFeedbackUIFlaskApp::test_static_assets_not_rate_limited` → 7 passed；
- `uv run ruff check tests/test_mathjax_pending_elements_loop_r594.py`；
- `uv run ty check tests/test_mathjax_pending_elements_loop_r594.py`；
- `node --check src/ai_intervention_agent/static/js/mathjax-loader.js`；
- `node --check src/ai_intervention_agent/static/js/mathjax-loader.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.138 R595 · WebUI image-upload drag/drop listener 去 forEach callback

`src/ai_intervention_agent/static/js/image-upload.js::initializeDragAndDrop()`
有两段 listener lifecycle 遍历：

```js
["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
  addDocumentListener(eventName, preventDefaults, { passive: false })
})

listenerEntries.forEach((entry) => {
  document.removeEventListener(entry.type, entry.handler, entry.options)
})
```

R595 把固定四事件注册改成 direct calls，并让 cleanup 使用 length snapshot +
indexed loop：

```js
const preventDefaultListenerOptions = { passive: false }
addDocumentListener("dragenter", preventDefaults, preventDefaultListenerOptions)
addDocumentListener("dragover", preventDefaults, preventDefaultListenerOptions)
addDocumentListener("dragleave", preventDefaults, preventDefaultListenerOptions)
addDocumentListener("drop", preventDefaults, preventDefaultListenerOptions)

const listenerEntryCount = listenerEntries.length
for (let index = 0; index < listenerEntryCount; index += 1) {
  if (!(index in listenerEntries)) continue
  const entry = listenerEntries[index]
  document.removeEventListener(entry.type, entry.handler, entry.options)
}
```

这样去掉初始化时固定数组 callback 和 cleanup 时的 per-entry callback
dispatch；同时 cleanup 显式保留 `forEach()` 的 present-slot 遍历语义。四个
prevent-default listener 共享同一个 `{ passive: false }` options 对象，清理时
仍按 `listenerEntries` 里记录的同一 handler/options 调用
`removeEventListener()`。

行为边界：

- 每次成功初始化仍安装 8 个 document listener：4 个 prevent-default listener
  和 4 个实际 drag/drop handler；
- 重复 `initializeDragAndDrop()` 仍先清理旧的 8 个 listener，再绑定当前 DOM；
- 非文件 drag event 仍不调用 `preventDefault()` / `stopPropagation()`；
- 文件 dragover 仍设置 `dropEffect = "copy"`，文件 drop 仍进入
  `handleFileUpload(files)`；
- cleanup 后仍清空 overlay、移除 textarea drag class，并把
  `window.__aiInterventionAgentDragDropCleanup` 置回 `null`。

新增测试：

- `tests/test_image_upload_drag_drop_listener_loop_r595.py`
  - source invariant 锁定固定事件注册不再使用 array `.forEach()`，cleanup
    不再使用 `listenerEntries.forEach()`；
  - Node VM runtime 在加载模块后禁用 `Array.prototype.forEach`，连续执行两次
    `initializeDragAndDrop()`，验证旧 listener 被清理、新 listener 数量保持
    每事件 2 个、非文件事件不被 suppress、文件 drag/drop 行为不变，最终
    cleanup 清掉所有 drag/drop listener。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round122/02-foreach-semantics.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 按 ascending-index order
  调用，empty slots 不调用；R595 的 cleanup loop 显式保留这些边界。
- `/tmp/smart-search-evidence/aiia-optimization-round122/04-mdn-removeeventlistener-matching.json`
  保存 MDN `removeEventListener()` 资料：删除 listener 需要匹配 type、listener
  和 capture；passive 等其他 options 不参与匹配，但复用记录对象仍是最保守路径。
- `/tmp/smart-search-evidence/aiia-optimization-round122/03-foreach-callback-overhead.json`
  保存 loop/callback overhead 搜索资料：indexed loop 避免 `forEach` 的逐元素
  callback 调用开销。

验证：

- `uv run pytest tests/test_image_upload_drag_drop_listener_loop_r595.py
  tests/test_image_upload_init_idempotency_runtime_r452.py
  tests/test_image_upload_file_selection_runtime_r452.py
  tests/test_image_upload_paste_clipboard_one_pass_r557.py
  tests/test_image_upload_filelist_batch_one_pass_r561.py` → 15 passed；
- `uv run ruff check tests/test_image_upload_drag_drop_listener_loop_r595.py`；
- `uv run ty check tests/test_image_upload_drag_drop_listener_loop_r595.py`；
- `node --check src/ai_intervention_agent/static/js/image-upload.js`；
- `node --check src/ai_intervention_agent/static/js/image-upload.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.139 R596 · WebUI image-upload object URL cleanup 去 collection forEach

`src/ai_intervention_agent/static/js/image-upload.js` 的 object URL 生命周期路径
仍有三处 callback 遍历：

```js
objectURLs.forEach((url) => {
  URL.revokeObjectURL(url)
})

urlCreationTime.forEach((creationTime, url) => {
  if (now - creationTime > OBJECT_URL_MAX_AGE_MS) expiredUrls.push(url)
})

expiredUrls.forEach((url) => revokeObjectURL(url))
```

R596 改为 `for...of` / indexed loop：

```js
for (const url of objectURLs) {
  ...
}

for (const [url, creationTime] of urlCreationTime) {
  ...
}

const expiredUrlCount = expiredUrls.length
for (let index = 0; index < expiredUrlCount; index += 1) {
  revokeObjectURL(expiredUrls[index])
}
```

这样去掉 Set / Map / Array 三段 cleanup callback dispatch，同时保留原来的两阶段
过期清理：先从 `urlCreationTime` 收集 expired URL，再逐个调用
`revokeObjectURL()`。`cleanupAllObjectURLs()` 仍对每个 URL 单独 `try/catch`，
单个 revoke 失败不会阻断后续 URL；最后仍 `clear()` 两个 tracking collection
并停止周期 timer。

行为边界：

- `cleanupAllObjectURLs()` 仍按 insertion order 尝试 revoke 当前 `objectURLs`；
- 单个 `URL.revokeObjectURL()` 抛错时仍记录错误并继续处理后续 URL；
- `cleanupExpiredObjectURLs()` 仍返回本轮判定过期的 URL 数量；
- 过期 URL revoke 失败时，`revokeObjectURL()` 仍不会删除该 URL，保持旧的
  fail-soft 行为；后续 full cleanup 会清空 tracking collection；
- hidden / bfcache / pagehide 生命周期 timer 语义不变。

新增测试：

- `tests/test_image_upload_object_url_cleanup_loop_r596.py`
  - source invariant 锁定 `cleanupAllObjectURLs()` / `cleanupExpiredObjectURLs()`
    不再使用 `objectURLs.forEach`、`urlCreationTime.forEach` 或
    `expiredUrls.forEach`；
  - Node VM runtime 在模块加载后禁用 `Set.prototype.forEach`、
    `Map.prototype.forEach` 和 `Array.prototype.forEach`，验证 expired cleanup
    仍按顺序 revoke、revoke 失败仍保留对应 URL、full cleanup 仍继续处理并
    清空 tracking state。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round123/01-mdn-set-iteration.json`
  保存 MDN Set 资料：Set 可按 insertion order 迭代，`for...of` 可直接消费 Set。
- `/tmp/smart-search-evidence/aiia-optimization-round123/02-mdn-map-iteration.json`
  保存 MDN Map 资料：Map 按 key-value pair insertion order 迭代，`for...of`
  返回 `[key, value]`。
- `/tmp/smart-search-evidence/aiia-optimization-round123/03-mdn-object-url-revoke.json`
  保存 MDN Blob URL 资料：object URL 应在不再需要时显式
  `URL.revokeObjectURL()` 释放，避免内存泄漏。
- `/tmp/smart-search-evidence/aiia-optimization-round123/04-set-map-foreach-callback-overhead.json`
  保存 Set/Map `forEach` callback overhead 搜索资料：`for...of` 避免逐元素
  callback 调用，更适合热路径和大 collection。

验证：

- `uv run pytest tests/test_image_upload_object_url_cleanup_loop_r596.py
  tests/test_image_upload_object_url_lifecycle_r452.py` → 14 passed；
- `uv run ruff check tests/test_image_upload_object_url_cleanup_loop_r596.py`；
- `uv run ty check tests/test_image_upload_object_url_cleanup_loop_r596.py`；
- `node --check src/ai_intervention_agent/static/js/image-upload.js`；
- `node --check src/ai_intervention_agent/static/js/image-upload.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.140 R597 · WebUI image-upload clear-all 去 selectedImages.forEach

`src/ai_intervention_agent/static/js/image-upload.js::clearAllImages()` 在清空图片
时会遍历 `selectedImages`，对仍由模块跟踪的 blob preview URL 调用
`revokeObjectURL()`：

```js
selectedImages.forEach((img) => {
  if (img.previewUrl && img.previewUrl.startsWith("blob:")) {
    revokeObjectURL(img.previewUrl)
  }
})
```

R597 改成 length snapshot + indexed loop：

```js
const selectedImageCount = selectedImages.length
for (let index = 0; index < selectedImageCount; index += 1) {
  if (!(index in selectedImages)) continue
  const img = selectedImages[index]
  if (img.previewUrl && img.previewUrl.startsWith("blob:")) {
    revokeObjectURL(img.previewUrl)
  }
}
```

这样去掉清空路径中每张图片一次的 arrow callback dispatch，同时显式保留
`Array.prototype.forEach()` 的 present-slot 语义：遍历范围在开始前由 length
固定，sparse hole 不触发访问；显式存在的异常值仍会沿旧路径暴露错误，不新增
null/undefined 容错导致行为漂移。清空后的 `selectedImages = []`、
`DOMSecurity.clearContent(#image-previews)`、计数更新、预览区 class 更新和开发态
GC 提示均不变。

行为边界：

- 仅 `previewUrl` 以 `blob:` 开头的图片进入 `revokeObjectURL()`；
- `revokeObjectURL()` 仍只实际释放模块 `objectURLs` tracking set 中存在的 URL；
- data URL / 非 blob preview 不释放；
- sparse hole 仍跳过，保持 `forEach()` 对 empty slots 的语义；
- 清空后图片计数仍归零，预览容器仍安全清空，预览区域仍切到 hidden 状态。

新增测试：

- `tests/test_image_upload_clear_all_loop_r597.py`
  - source invariant 锁定 `clearAllImages()` 不再使用
    `selectedImages.forEach`，并确认 `selectedImageCount`、indexed loop、
    hole skip 和 blob URL 判定仍存在；
  - Node VM runtime 先通过模块 `createObjectURL()` 建立 object URL ownership，
    再禁用 `Array.prototype.forEach`，构造含 sparse hole、blob URL 和 data URL
    的 `selectedImages`，验证 clear-all 仍只释放 owned blob URL、清空预览容器、
    计数归零、预览区域 hidden，并保留 debug 日志。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round124/01-mdn-array-foreach-semantics.json`
  保存 MDN `Array.prototype.forEach()` 语义资料：callback 按升序访问已存在元素，
  empty slots 不调用；R597 的 loop 显式保留这些边界。
- `/tmp/smart-search-evidence/aiia-optimization-round124/02-mdn-blob-url-revoke.json`
  保存 MDN Blob URL 资料：object URL 不再需要时应调用
  `URL.revokeObjectURL()` 释放。
- `/tmp/smart-search-evidence/aiia-optimization-round124/03-array-foreach-callback-overhead.json`
  保存 loop/callback overhead 搜索资料：indexed loop 可避免 `forEach` 的逐元素
  callback 调用开销。

验证：

- `uv run pytest tests/test_image_upload_clear_all_loop_r597.py
  tests/test_image_upload_object_url_cleanup_loop_r596.py
  tests/test_image_upload_object_url_lifecycle_r452.py
  tests/test_image_upload_init_idempotency_runtime_r452.py` → 21 passed；
- `uv run ruff check tests/test_image_upload_clear_all_loop_r597.py`；
- `uv run ty check tests/test_image_upload_clear_all_loop_r597.py`；
- `node --check src/ai_intervention_agent/static/js/image-upload.js`；
- `node --check src/ai_intervention_agent/static/js/image-upload.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.141 R598 · WebUI DOMSecurity.createElement 属性遍历去 forEach callback

`src/ai_intervention_agent/static/js/dom-security.js::DOMSecurity.createElement()`
会把调用方传入的 attributes 对象转成 `[key, value]` 列表，再筛掉非
string/number 值：

```js
Object.entries(attributes).forEach(([key, value]) => {
  if (typeof value === 'string' || typeof value === 'number') {
    element.setAttribute(key, String(value))
  }
})
```

R598 保守保留 `Object.entries(attributes)` 的 own-enumerable string-keyed
key/value 快照，只把 callback dispatch 换成 length snapshot + indexed loop：

```js
const attributeEntries = Object.entries(attributes)
const attributeEntryCount = attributeEntries.length
for (let index = 0; index < attributeEntryCount; index += 1) {
  if (!(index in attributeEntries)) continue
  const [key, value] = attributeEntries[index]
  if (typeof value === 'string' || typeof value === 'number') {
    element.setAttribute(key, String(value))
  }
}
```

这里没有改属性名 allowlist 或 URL/style/event 处理策略，原因是本轮目标是
性能形态而不是安全策略重写。保留 `Object.entries()` 也避免 accessor getter
或后续 `setAttribute()` 副作用造成值读取时机变化；旧实现是在进入 callback
前先创建完整 entries 数组，R598 维持这个快照边界。

行为边界：

- 仍只枚举 attributes 自身的 enumerable string-keyed 属性；
- inherited / non-enumerable / symbol-keyed 属性仍不设置；
- 仍只接受 string 和 number 值，boolean / function / object 值仍跳过；
- number 值仍通过 `String(value)` 写入；
- `textContent` 仍用于文本，HTML 字符串不会被当作 markup 解析。

新增测试：

- `tests/test_dom_security_create_element_loop_r598.py`
  - source invariant 锁定 `createElement()` 不再使用
    `Object.entries(attributes).forEach`，并确认 `attributeEntries`、
    `attributeEntryCount`、indexed loop 和 hole guard；
  - Node VM runtime 在加载模块后禁用 `Array.prototype.forEach`，验证
    `createElement()` 仍设置 string/number 属性、跳过 inherited /
    non-enumerable / boolean / function / object 属性，并用会篡改原 attributes
    对象的 `setAttribute()` 桩确认 entries value snapshot 未漂移。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round125/01-mdn-object-entries.json`
  保存 MDN/TC39 资料：`Object.entries()` 返回对象自身 enumerable
  string-keyed 属性的 key/value 列表，TC39 算法经 `EnumerableOwnProperties`
  生成 `entryList` 后 `CreateArrayFromList`。
- `/tmp/smart-search-evidence/aiia-optimization-round125/02-mdn-array-foreach-semantics.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 按升序访问已赋值元素，
  sparse empty slots 不调用；R598 的 indexed loop 显式保留这些边界。
- `/tmp/smart-search-evidence/aiia-optimization-round125/03-foreach-callback-overhead.json`
  保存 loop/callback overhead 搜索资料：indexed loop 避免 `forEach` 的逐元素
  callback 调用开销；`Object.entries().forEach(...)` 还叠加 entries 数组遍历。

验证：

- `uv run pytest tests/test_dom_security_create_element_loop_r598.py
  tests/test_runtime_behavior.py
  tests/test_static_js_console_log_demotion_invariant_r217.py` → 55 passed,
  13 subtests passed；
- `uv run ruff check tests/test_dom_security_create_element_loop_r598.py`；
- `uv run ty check tests/test_dom_security_create_element_loop_r598.py`；
- `node --check src/ai_intervention_agent/static/js/dom-security.js`；
- `node --check src/ai_intervention_agent/static/js/dom-security.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.142 R599 · WebUI app code-fence 最长反引号扫描去 reduce callback

`src/ai_intervention_agent/static/js/app.js::buildMarkdownCodeFence()` 在从剪贴板
插入代码块时，会先用全局正则找出正文内所有 backtick run，再用 `reduce()` 计算
最长 run，确保外层 Markdown fence 比正文中最长连续反引号多 1 个：

```js
const backtickRuns = normalizedText.match(/`+/g) || []
const longestRun = backtickRuns.reduce(
  (max, run) => Math.max(max, run.length),
  0,
)
```

R599 保留 `String.prototype.match(/`+/g)` 的结果数组和 `initialValue = 0`
语义，只把 per-run reducer callback 改成 length snapshot + indexed loop：

```js
const backtickRuns = normalizedText.match(/`+/g) || []
let longestRun = 0
const backtickRunCount = backtickRuns.length
for (let index = 0; index < backtickRunCount; index += 1) {
  if (!(index in backtickRuns)) continue
  const runLength = backtickRuns[index].length
  if (runLength > longestRun) longestRun = runLength
}
```

这样去掉每个 run 的 reducer callback dispatch 和 `Math.max()` 调用，同时显式保留
`reduce()` 对 sparse hole 的跳过语义。虽然真实 `match(/`+/g)` 结果通常是 dense
array，测试仍覆盖 sparse match-like array，防止未来重构替换数据来源时丢掉边界。

行为边界：

- 空白 / 空输入仍返回 `null`；
- CRLF / CR 仍归一化为 LF；
- 没有反引号时仍使用 3-backtick fence；
- 正文包含 `` ``` `` 时外层 fence 变为 4 个反引号，包含 5 个反引号时外层变为
  6 个反引号；
- `lang` 参数仍只影响 fence header，不影响正文和 closing fence；
- sparse hole 仍跳过，显式 `undefined` slot 仍会沿旧路径暴露错误。

新增测试：

- `tests/test_app_markdown_code_fence_loop_r599.py`
  - source invariant 锁定 `buildMarkdownCodeFence()` 不再使用
    `backtickRuns.reduce`，并确认 `backtickRunCount`、indexed loop、hole guard
    和 direct max update；
  - Node VM runtime 禁用 `Array.prototype.reduce`，验证 lang header、无反引号、
    CRLF 归一化、5-backtick 正文和空白输入；
  - patch VM 字符串 intrinsic `match()` 返回 sparse array，验证 loop 像
    `reduce(..., 0)` 一样跳过 missing slot 并仍按最长 present run 生成 fence。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round126/01-mdn-array-reduce-semantics.json`
  保存 MDN `Array.prototype.reduce()` 资料：`initialValue` 存在时 callback 从
  index 0 开始，且 callback 只访问已赋值元素；sparse empty slots 不调用。
- `/tmp/smart-search-evidence/aiia-optimization-round126/02-mdn-string-match.json`
  保存 MDN `String.prototype.match()` 资料：全局正则 `g` 返回所有完整匹配组成的
  数组，无匹配返回 `null`。
- `/tmp/smart-search-evidence/aiia-optimization-round126/03-reduce-callback-overhead.json`
  保存 reduce/callback overhead 搜索资料：indexed loop 避免 reducer 每项函数调用
  和通用 accumulator 管理开销，适合简单热路径扫描。

验证：

- `uv run pytest tests/test_app_markdown_code_fence_loop_r599.py
  tests/test_app_process_code_blocks_loop_r588.py
  tests/test_app_submit_cleanup_nodelist_loop_r578.py` → 7 passed；
- `uv run ruff check tests/test_app_markdown_code_fence_loop_r599.py`；
- `uv run ty check tests/test_app_markdown_code_fence_loop_r599.py`；
- `node --check src/ai_intervention_agent/static/js/app.js`；
- `node --check src/ai_intervention_agent/static/js/app.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.143 R600 · WebUI multi_task copy flash 去 NodeList.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::_flashCopyOnSourceElement()`
在复制 task id / deep-link 后，会通过 `data-copyable-task-id` 找到所有同一 task
的可复制文本节点，清掉旧 flash class、强制 reflow、加上 success/error flash
class，并在 600ms 后移除：

```js
const elements = document.querySelectorAll(
  `[data-copyable-task-id="${CSS.escape(String(taskId || ""))}"]`,
)
elements.forEach((el) => {
  const cls = ok ? "copy-flash-ok" : "copy-flash-err"
  el.classList.remove("copy-flash-ok", "copy-flash-err")
  void el.offsetWidth
  el.classList.add(cls)
  setTimeout(() => { ... }, 600)
})
```

R600 改为 length snapshot + indexed loop：

```js
const elementCount = elements.length
for (let index = 0; index < elementCount; index += 1) {
  const el = elements[index]
  if (!el) continue
  const cls = ok ? "copy-flash-ok" : "copy-flash-err"
  ...
}
```

`querySelectorAll()` 返回 static NodeList，长度快照与旧路径在本场景一致；同时去掉
每个元素一次 callback dispatch。保留 `CSS.escape(String(taskId || ""))`，
所以空 task id、特殊字符 task id 和 selector error fallback 仍沿旧的 try/catch
边界运行。

行为边界：

- selector 仍基于 `data-copyable-task-id` 并使用 `CSS.escape()`；
- 多个匹配元素仍按 querySelectorAll 的 document order 处理；
- 每个元素仍先移除 `copy-flash-ok` / `copy-flash-err`，再读取 `offsetWidth`
  触发 reflow，最后添加本次 class；
- success 仍用 `copy-flash-ok`，失败仍用 `copy-flash-err`；
- 每个元素仍各自注册 600ms cleanup，并在 cleanup 内吞掉 classList 异常；
- 外层仍吞掉 `CSS.escape` / `querySelectorAll` 异常，不影响复制主流程。

新增测试：

- `tests/test_multi_task_copy_flash_loop_r600.py`
  - source invariant 锁定 `_flashCopyOnSourceElement()` 不再使用
    `elements.forEach`，并确认 `elementCount`、indexed loop、null guard、
    success/error class 选择和 reflow 读取；
  - Node VM runtime 返回禁用 `forEach()` 的 NodeList-like 对象，验证 selector
    escape、旧 class reset、reflow、success/error add、600ms timeout cleanup
    和 null slot skip。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round127/01-mdn-queryselectorall-static-nodelist.json`
  保存 MDN `querySelectorAll()` 资料：返回 static / non-live NodeList，元素按
  document order 排列。
- `/tmp/smart-search-evidence/aiia-optimization-round127/02-mdn-nodelist-foreach.json`
  保存 MDN `NodeList.forEach()` 资料：callback 对 NodeList 中每个 value pair
  按 insertion order 调用。
- `/tmp/smart-search-evidence/aiia-optimization-round127/03-nodelist-foreach-callback-overhead.json`
  保存 NodeList / Array callback-loop overhead 搜索资料：indexed loop 避免
  per-node callback 调用；DOM work 往往更重，但热路径扫描仍可减少固定开销。

验证：

- `uv run pytest tests/test_multi_task_copy_flash_loop_r600.py
  tests/test_multi_task_sse_console_noise.py
  tests/test_runtime_behavior.py::TestClientServerRouteAlignment::test_web_js_fetch_routes_exist_in_flask` → 5 passed；
- `uv run ruff check tests/test_multi_task_copy_flash_loop_r600.py`；
- `uv run ty check tests/test_multi_task_copy_flash_loop_r600.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.144 R601 · WebUI multi_task poll response 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::fetchAndApplyTasks()` 的
轮询成功路径会在每次 `/api/tasks` 返回后扫描 `data.tasks`，同步
`window.taskDeadlines`，并把后端热更新的 `auto_resubmit_timeout` /
`remaining_time` 写回已有倒计时：

```js
if (data.tasks) {
  data.tasks.forEach((task) => {
    if (task.deadline) {
      window.taskDeadlines[task.task_id] = task.deadline
    }
    ...
  })
}
```

R601 改为 length snapshot + indexed loop，并显式保留 sparse array 语义：

```js
if (data.tasks) {
  const taskCount = data.tasks.length
  for (let index = 0; index < taskCount; index += 1) {
    if (!(index in data.tasks)) continue
    const task = data.tasks[index]
    ...
  }
}
```

`Array.prototype.forEach()` 不访问 sparse array 的 empty slots；因此 indexed loop
必须带 `index in data.tasks` guard，避免对 hole 做 `task.deadline` 访问。
旧路径如果数组槽位显式存放 `undefined` 仍会抛错，新路径没有新增 null guard，
保持同一行为边界。收益是轮询热路径少一次 `data.tasks.length` 范围内的
per-task callback dispatch，同时不改变 deadline / countdown 更新顺序。

行为边界：

- `data.tasks` truthy 时才扫描，仍不为非数组或 nullish 响应新增兼容分支；
- sparse array empty slots 仍被跳过；
- 显式 `undefined` task 仍会在访问 `task.deadline` 时失败；
- `deadline` truthy 时仍写入 `window.taskDeadlines[task.task_id]`；
- 未完成任务且本地已有 countdown 时，仍同步 `auto_resubmit_timeout` 和
  `remaining_time`；
- `auto_resubmit_timeout <= 0` 时仍调用 `_clearTaskCountdown(task.task_id)` 并
  删除对应 deadline；
- completed task 仍不会更新已有 countdown；
- `updateTasksList(data.tasks)` 与 `updateTasksStats(data.stats)` 的调用参数与
  顺序不变。

新增测试：

- `tests/test_multi_task_poll_tasks_loop_r601.py`
  - source invariant 锁定 `fetchAndApplyTasks()` 不再使用 `data.tasks.forEach`，
    并确认 `taskCount`、indexed loop、sparse slot guard、index 取值和
    `auto_resubmit_timeout <= 0` 清理路径；
  - Node VM runtime 加载完整 `multi_task.js`，stub 下游 `updateTasksList()` /
    `updateTasksStats()` / `_clearTaskCountdown()` 后禁用 `Array.prototype.forEach`，
    返回含 sparse hole 的 `/api/tasks` 响应，验证 deadline 更新、`<=0` 清理、
    completed task 不更新 countdown、原始 sparse tasks 透传和 poll timeout
    cleanup。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round128/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round128/01-mdn-array-foreach-semantics.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 仅对已赋值索引调用，
  不访问 sparse array empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round128/02-array-foreach-callback-overhead.json`
  保存 Array callback-loop overhead 搜索资料：热路径 indexed loop 可避免每元素
  callback 调用开销，收益应按目标 runtime 和真实路径验证。

验证：

- `uv run pytest tests/test_multi_task_poll_tasks_loop_r601.py
  tests/test_multi_task_poll_controller_lifecycle_r452.py
  tests/test_multi_task_update_diff_sets_r524.py
  tests/test_multi_task_refresh_state_r527.py` → 13 passed, 5 subtests passed；
- `uv run ruff check tests/test_multi_task_poll_tasks_loop_r601.py`；
- `uv run ty check tests/test_multi_task_poll_tasks_loop_r601.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.145 R602 · WebUI multi_task removed-task cleanup 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::updateTasksList()` 在 diff 出已
删除任务后，会逐个调用 `clearTaskLocalState(taskId)` 清理本地状态。旧路径在
每次任务列表刷新时对 `taskDiff.removedTaskIds` 使用 `forEach()`：

```js
const removedTasks = taskDiff.removedTaskIds
if (removedTasks.length > 0) {
  _debugLog(`Detected ${removedTasks.length} removed task(s)`)
  removedTasks.forEach((taskId) => {
    clearTaskLocalState(taskId)
  })
}
```

R602 改为 length snapshot + indexed loop：

```js
const removedTaskCount = removedTasks.length
for (let index = 0; index < removedTaskCount; index += 1) {
  if (!(index in removedTasks)) continue
  const taskId = removedTasks[index]
  clearTaskLocalState(taskId)
}
```

这里不改变 `_buildTaskListDiff()` 的输出契约，也不调整 added/completed/task
兜底循环；只把 removed-task cleanup 这一段从 callback dispatch 改为同作用域
indexed traversal。`index in removedTasks` 保留 `forEach()` 跳过 sparse array
empty slots 的语义；显式 `undefined` task id 仍会传给 `clearTaskLocalState()`，
不新增兼容分支。

行为边界：

- 仍仅在 `removedTasks.length > 0` 时记录 debug log 并进入 cleanup；
- cleanup 顺序仍按 `removedTaskIds` 的升序索引顺序；
- sparse array empty slots 仍被跳过；
- 显式 `undefined` / 空字符串等 task id 仍按旧路径传给
  `clearTaskLocalState()`；
- `clearTaskLocalState()` 调用次数与有效已赋值索引数一致；
- added task 倒计时启动、completed task cleanup、task list refresh state 和
  render / load 流程不变。

新增测试：

- `tests/test_multi_task_removed_tasks_loop_r602.py`
  - source invariant 锁定 `updateTasksList()` 不再使用 `removedTasks.forEach`，
    并确认 `removedTaskCount`、indexed loop、sparse slot guard、index 取值和
    `clearTaskLocalState(taskId)`；
  - Node VM runtime 加载完整 `multi_task.js`，stub diff/refresh/render 下游路径，
    给 `removedTaskIds` 设置 sparse hole 和会抛错的实例级 `forEach`，验证只清理
    已赋值 task id、跳过 hole，并保持 `currentTasks` / `hasLoadedTaskSnapshot`
    更新。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round129/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round129/01-mdn-array-foreach-sparse-range.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 按升序索引调用，且不访问
  sparse array empty slots；旧版摘录也记录遍历范围在首次 callback 前确定。
- `/tmp/smart-search-evidence/aiia-optimization-round129/02-array-foreach-cleanup-loop-overhead.json`
  保存 cleanup loop / callback overhead 搜索资料：热路径 cleanup 扫描可用 indexed
  loop 避免每元素 callback 调用；真实收益仍以目标 runtime profiling 为准。

验证：

- `uv run pytest tests/test_multi_task_removed_tasks_loop_r602.py
  tests/test_multi_task_update_diff_sets_r524.py
  tests/test_multi_task_refresh_state_r527.py` → 11 passed, 5 subtests passed；
- `uv run ruff check tests/test_multi_task_removed_tasks_loop_r602.py`；
- `uv run ty check tests/test_multi_task_removed_tasks_loop_r602.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.146 R603 · WebUI multi_task completed-task cleanup 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::updateTasksList()` 在构建
`taskRefreshState` 后，会清理已经完成的任务本地状态。旧路径直接对
`taskRefreshState.completedTaskIds` 使用 `forEach()`：

```js
const taskRefreshState = _buildTaskRefreshState(tasks, activeTaskId)
taskRefreshState.completedTaskIds.forEach((taskId) => {
  clearTaskLocalState(taskId)
})
```

R603 改为 length snapshot + indexed loop：

```js
const completedTaskIds = taskRefreshState.completedTaskIds
const completedTaskCount = completedTaskIds.length
for (let index = 0; index < completedTaskCount; index += 1) {
  if (!(index in completedTaskIds)) continue
  const taskId = completedTaskIds[index]
  clearTaskLocalState(taskId)
}
```

这保持 `_buildTaskRefreshState()` 的单次扫描输出契约，只把 completed cleanup
这一段从每 task 一次 callback dispatch 改成同作用域循环。`index in
completedTaskIds` 保留 `forEach()` 跳过 sparse array empty slots 的语义；显式
`undefined` task id 仍按旧路径传入 `clearTaskLocalState()`，不新增兼容分支。

行为边界：

- `taskRefreshState` 仍只构建一次；
- cleanup 顺序仍按 `completedTaskIds` 的升序索引顺序；
- sparse array empty slots 仍被跳过；
- 显式 `undefined` / 空字符串等 task id 仍传给 `clearTaskLocalState()`；
- `clearTaskLocalState()` 调用次数与有效已赋值索引数一致；
- `hasActiveTasks`、active task 选择、按钮同步、render / deep-link / load 流程不变。

新增测试：

- `tests/test_multi_task_completed_tasks_loop_r603.py`
  - source invariant 锁定 `updateTasksList()` 不再使用
    `taskRefreshState.completedTaskIds.forEach`，并确认 `completedTaskIds` snapshot、
    `completedTaskCount`、indexed loop、sparse slot guard、index 取值和
    `clearTaskLocalState(taskId)`；
  - Node VM runtime 加载完整 `multi_task.js`，stub diff/refresh/render 下游路径，
    给 `completedTaskIds` 设置 sparse hole 和会抛错的实例级 `forEach`，验证只清理
    已赋值 task id、跳过 hole，并保持 `currentTasks` / `hasLoadedTaskSnapshot`
    更新。
- `tests/test_multi_task_refresh_state_r527.py`
  - 更新既有 source invariant：仍要求 `updateTasksList()` 使用
    `_buildTaskRefreshState()`，但不再把旧 `completedTaskIds.forEach` 作为契约。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round130/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round130/01-mdn-array-foreach-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 只对已赋值索引调用，
  不访问 sparse array empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round130/02-array-foreach-completed-cleanup-overhead.json`
  保存 completed-item cleanup / callback overhead 搜索资料：UI hot path 中的 cleanup
  扫描可用 indexed loop 避免每元素 callback 调用；真实收益仍以目标 runtime
  profiling 为准。

验证：

- `uv run pytest tests/test_multi_task_completed_tasks_loop_r603.py
  tests/test_multi_task_refresh_state_r527.py
  tests/test_multi_task_update_diff_sets_r524.py
  tests/test_multi_task_removed_tasks_loop_r602.py` → 13 passed, 5 subtests passed；
- `uv run ruff check tests/test_multi_task_completed_tasks_loop_r603.py
  tests/test_multi_task_refresh_state_r527.py`；
- `uv run ty check tests/test_multi_task_completed_tasks_loop_r603.py
  tests/test_multi_task_refresh_state_r527.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.147 R604 · WebUI multi_task countdown fallback scan 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::updateTasksList()` 在每次任务列表
刷新后，有一段热更新兜底扫描：确保所有未完成任务都有倒计时，禁用
`auto_resubmit_timeout <= 0` 时清掉已有倒计时，active 且已超时的任务直接触发
`autoSubmitTask()`。旧路径使用 `tasks.forEach()`，并通过 callback `return`
跳过当前 task：

```js
tasks.forEach((task) => {
  if (task.status === "completed") return
  ...
  if (total <= 0) {
    if (taskCountdowns[task.task_id]) {
      _clearTaskCountdown(task.task_id)
    }
    return
  }
  ...
})
```

R604 改为 length snapshot + indexed loop，并把 callback `return` 精确翻译为
loop `continue`：

```js
const taskCount = tasks.length
for (let index = 0; index < taskCount; index += 1) {
  if (!(index in tasks)) continue
  const task = tasks[index]
  if (task.status === "completed") continue
  ...
  if (total <= 0) {
    if (taskCountdowns[task.task_id]) {
      _clearTaskCountdown(task.task_id)
    }
    continue
  }
  ...
}
```

`index in tasks` 保留 `forEach()` 跳过 sparse array empty slots 的语义；显式
`undefined` task 仍会在访问 `task.status` 时失败，不新增兼容分支。收益是每次
task-list refresh 少一层 per-task callback dispatch，同时分支控制流更直接。

行为边界：

- completed task 仍直接跳过，不启动倒计时、不自动提交；
- `auto_resubmit_timeout` 非 number 时仍 fallback 到 240；
- `total <= 0` 时仍只在已有 countdown 存在时调用 `_clearTaskCountdown()`，然后
  跳过后续 start/auto-submit；
- active task 且 `remaining_time <= 0` 时仍直接 `autoSubmitTask(task.task_id)`；
- 缺 countdown 或 active countdown 无 timer 时仍兜底恢复；
- 已有 pending countdown 且 timer 存在时仍不重复启动；
- sparse array empty slots 仍被跳过，显式 `undefined` task 不被吞掉。

新增测试：

- `tests/test_multi_task_countdown_fallback_loop_r604.py`
  - source invariant 锁定 `updateTasksList()` 不再使用 `tasks.forEach((task)`，
    并确认 `taskCount`、indexed loop、sparse slot guard、completed `continue` 和
    `total <= 0` 的 `_clearTaskCountdown()` + `continue`；
  - Node VM runtime 加载完整 `multi_task.js`，stub diff/refresh/render/button 下游
    路径，给 `tasks` 设置 sparse hole 和会抛错的实例级 `forEach`，验证 completed
    skip、disabled timeout cleanup、active overdue auto-submit、pending countdown
    start、existing countdown 不重复启动和 `currentTasks` 引用更新。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round131/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round131/01-mdn-array-foreach-return-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 只对已赋值索引调用，不访问
  sparse array empty slots；`forEach` 不能用普通方式 break，callback `return`
  只结束当前 callback。
- `/tmp/smart-search-evidence/aiia-optimization-round131/02-array-foreach-ui-refresh-loop-overhead.json`
  保存 UI refresh / countdown scan callback-loop overhead 搜索资料：热路径扫描可用
  indexed loop 避免 per-element callback 调用，DOM/计时器路径仍应按目标 runtime
  profiling 验证。

验证：

- `uv run pytest tests/test_multi_task_countdown_fallback_loop_r604.py
  tests/test_multi_task_completed_tasks_loop_r603.py
  tests/test_multi_task_refresh_state_r527.py
  tests/test_multi_task_update_diff_sets_r524.py` → 13 passed, 5 subtests passed；
- `uv run ruff check tests/test_multi_task_countdown_fallback_loop_r604.py`；
- `uv run ty check tests/test_multi_task_countdown_fallback_loop_r604.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.148 R605 · WebUI task-tab existing NodeList scan 去 NodeList.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::_buildTaskTabRenderState()` 会在
tab diff 前读取现有 DOM tabs，构建 `existingTaskIds` 和 `existingTaskIdSet`。
旧路径直接对 `querySelectorAll(".task-tab:not(.task-tab-exit)")` 返回的
NodeList 调用 `forEach()`：

```js
const existingTaskIds = []
const existingTaskIdSet = new Set()
existingTabs.forEach((tab) => {
  const taskId = tab && tab.dataset ? tab.dataset.taskId : undefined
  existingTaskIds.push(taskId)
  existingTaskIdSet.add(taskId)
})
```

R605 改为 length snapshot + indexed loop：

```js
const existingTabCount = existingTabs.length
for (let index = 0; index < existingTabCount; index += 1) {
  if (!(index in existingTabs)) continue
  const tab = existingTabs[index]
  const taskId = tab && tab.dataset ? tab.dataset.taskId : undefined
  existingTaskIds.push(taskId)
  existingTaskIdSet.add(taskId)
}
```

`querySelectorAll()` 返回 static NodeList，元素按 document order 排列，且可用
standard array notation 读取；这里不需要 `Array.from()`，避免额外数组分配。
`index in existingTabs` 对真实 NodeList 不改变行为，也保留 array-like test double
的 sparse-slot skip 语义。

行为边界：

- `existingTabs` 仍来自 `.task-tab:not(.task-tab-exit)`，为空时仍是 `[]` fallback；
- existing task id 顺序仍按 DOM document order；
- tab 缺 `dataset` 时仍 push/add `undefined`；
- `existingTabs` 引用仍原样保存在返回 state 中；
- diff 的 `needsRebuild`、`removedIds`、`addedTasks` 计算不变；
- 不引入 `Array.from()` 或扩展运算符分配。

新增测试：

- `tests/test_multi_task_tab_existing_loop_r605.py`
  - source invariant 锁定 `_buildTaskTabRenderState()` 不再使用
    `existingTabs.forEach`，并确认 `existingTabCount`、indexed loop、sparse guard、
    index 读取和 task id push/set 更新；
  - Node VM runtime 加载完整 `multi_task.js`，让 `querySelectorAll()` 返回
    NodeList-like 对象（含 sparse hole、会抛错的实例级 `forEach`），验证现有 tab
    id 顺序、removed/added diff、completed task skip、原始 `existingTabs` 引用和
    sparse hole skip。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round132/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round132/01-mdn-queryselectorall-nodelist-foreach.json`
  保存 MDN `querySelectorAll()` / `NodeList` 资料：返回 static NodeList，元素按
  document order 排列，可用标准数组下标访问；`NodeList.forEach()` 对每个元素执行
  callback。
- `/tmp/smart-search-evidence/aiia-optimization-round132/02-nodelist-foreach-callback-overhead.json`
  保存 NodeList callback-loop overhead 搜索资料：热路径 DOM list 扫描中 indexed
  loop 可避免 per-element callback 调用；实际瓶颈仍通常是 DOM 读写与布局，应按
  DevTools profiling 验证。

验证：

- `uv run pytest tests/test_multi_task_tab_existing_loop_r605.py
  tests/test_multi_task_render_tabs_state_r526.py` → 6 passed；
- `uv run ruff check tests/test_multi_task_tab_existing_loop_r605.py`；
- `uv run ty check tests/test_multi_task_tab_existing_loop_r605.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.149 R606 · WebUI added-task countdown bootstrap 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::updateTasksList()` 在检测到新增
任务后，会为所有新任务启动自动提交倒计时。旧路径直接对
`taskDiff.addedTasks` 使用 `forEach()`：

```js
taskDiff.addedTasks.forEach((task) => {
  if (task.status !== "completed" && !taskCountdowns[task.task_id]) {
    const timeout = task.remaining_time ?? task.auto_resubmit_timeout ?? 240
    startTaskCountdown(
      task.task_id,
      timeout,
      task.auto_resubmit_timeout || 240,
    )
  }
})
```

R606 改为 length snapshot + indexed loop：

```js
const addedTaskCount = taskDiff.addedTasks.length
for (let index = 0; index < addedTaskCount; index += 1) {
  if (!(index in taskDiff.addedTasks)) continue
  const task = taskDiff.addedTasks[index]
  if (task.status !== "completed" && !taskCountdowns[task.task_id]) {
    ...
  }
}
```

`Array.prototype.forEach()` 不访问 sparse array empty slots，因此 indexed loop
保留 `index in taskDiff.addedTasks` guard。显式 `undefined` task 仍会在访问
`task.status` 时失败，不新增兼容分支。倒计时参数保持原语义：
`remaining_time ?? auto_resubmit_timeout ?? 240` 作为 remaining，
`auto_resubmit_timeout || 240` 作为 total。

行为边界：

- 新任务通知与 `addedTaskIds.length` 逻辑不变；
- completed 新任务仍不启动 countdown；
- 已存在 countdown 的新任务仍不重复启动；
- `remaining_time` 优先于 `auto_resubmit_timeout`；
- 缺 timeout 时仍 fallback 到 240；
- sparse array empty slots 仍被跳过；
- 显式 `undefined` task 不被吞掉。

新增测试：

- `tests/test_multi_task_added_tasks_loop_r606.py`
  - source invariant 锁定 `updateTasksList()` 不再使用
    `taskDiff.addedTasks.forEach`，并确认 `addedTaskCount`、indexed loop、sparse
    guard、index 读取和 `startTaskCountdown()` 参数表达式；
  - Node VM runtime 加载完整 `multi_task.js`，stub diff/refresh/render 下游路径，
    给 `addedTasks` 设置 sparse hole 和会抛错的实例级 `forEach`，验证通知计数、
    pending 新任务启动倒计时、completed 跳过、已有 countdown 不重复启动、240
    fallback 和 sparse hole skip。
- `tests/test_multi_task_update_diff_sets_r524.py`
  - 更新既有 source invariant：仍要求 `updateTasksList()` 使用
    `_buildTaskListDiff()`，但不再把旧 `taskDiff.addedTasks.forEach` 作为契约。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round133/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round133/01-mdn-array-foreach-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 只对已赋值索引调用，不访问
  sparse array empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round133/02-array-foreach-task-update-overhead.json`
  保存 UI task update callback-loop overhead 搜索资料：热路径扫描可用 indexed loop
  避免 per-element callback 调用；真实收益仍以目标 runtime profiling 为准。

验证：

- `uv run pytest tests/test_multi_task_added_tasks_loop_r606.py
  tests/test_multi_task_update_diff_sets_r524.py
  tests/test_multi_task_removed_tasks_loop_r602.py
  tests/test_multi_task_completed_tasks_loop_r603.py
  tests/test_multi_task_countdown_fallback_loop_r604.py` → 12 passed, 5 subtests passed；
- `uv run ruff check tests/test_multi_task_added_tasks_loop_r606.py
  tests/test_multi_task_update_diff_sets_r524.py`；
- `uv run ty check tests/test_multi_task_added_tasks_loop_r606.py
  tests/test_multi_task_update_diff_sets_r524.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.150 R607 · WebUI incremental removed-tab cleanup 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::renderTaskTabs()` 的增量 tab
更新路径会对 `tabState.removedIds` 逐个查找旧 tab、添加 `task-tab-exit` 动画
class、监听 `animationend`，并注册 300ms fallback remove。旧路径使用
`forEach()`：

```js
tabState.removedIds.forEach((id) => {
  const el = tabsContainer.querySelector(`[data-task-id="${id}"]`)
  if (el) {
    el.classList.add("task-tab-exit")
    el.addEventListener("animationend", () => el.remove(), { once: true })
    setTimeout(() => {
      if (el.parentNode) el.remove()
    }, 300)
  }
})
```

R607 改为 length snapshot + indexed loop：

```js
const removedTabCount = tabState.removedIds.length
for (let index = 0; index < removedTabCount; index += 1) {
  if (!(index in tabState.removedIds)) continue
  const id = tabState.removedIds[index]
  ...
}
```

`Array.prototype.forEach()` 不访问 sparse array empty slots，因此 indexed loop 保留
`index in tabState.removedIds` guard。增量路径的进入条件仍是
`removedIds.length + addedTasks.length <= 2` 且已有 tabs 存在；R607 不改变 full
rebuild 分支。

行为边界：

- `isIncremental` 判断不变；
- removed id 的 DOM query selector 不变；
- 找不到 tab 时仍只跳过；
- 找到 tab 时仍添加 `task-tab-exit`；
- `animationend` listener 仍使用 `{ once: true }` 并直接 `el.remove()`；
- 300ms fallback 仍只在 `el.parentNode` 存在时 remove；
- sparse array empty slots 仍被跳过；
- 显式 `undefined` id 仍会形成旧路径同等 selector 字符串。

新增测试：

- `tests/test_multi_task_tab_removed_loop_r607.py`
  - source invariant 锁定 `renderTaskTabs()` 不再使用
    `tabState.removedIds.forEach`，并确认 `removedTabCount`、indexed loop、sparse
    guard、index 读取、querySelector 和 `task-tab-exit` class；
  - Node VM runtime 加载完整 `multi_task.js`，stub tab state / DOM 节点，给
    `removedIds` 设置 sparse hole 和会抛错的实例级 `forEach`，验证增量路径、
    class 添加、`animationend` listener、300ms fallback removal、active tab
    aria/tabindex 更新和 sparse hole skip。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round134/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round134/01-mdn-array-foreach-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 只对已赋值索引调用，不访问
  sparse array empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round134/02-array-foreach-tab-remove-overhead.json`
  保存 UI tab remove callback-loop overhead 搜索资料：热路径中 indexed loop 可避免
  per-element callback 调用；DOM mutation / animation cleanup 仍应按 DevTools
  profiling 验证。

验证：

- `uv run pytest tests/test_multi_task_tab_removed_loop_r607.py
  tests/test_multi_task_render_tabs_state_r526.py` → 6 passed；
- `uv run ruff check tests/test_multi_task_tab_removed_loop_r607.py`；
- `uv run ty check tests/test_multi_task_tab_removed_loop_r607.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.151 R608 · WebUI incremental added-tab render 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::renderTaskTabs()` 的增量 tab
更新路径在处理 `tabState.addedTasks` 时，会创建新 tab、添加 enter 动画 class、
监听 `animationend` 移除 enter class，并 append 到 tabs 容器。旧路径使用
`forEach()`：

```js
tabState.addedTasks.forEach((task) => {
  const tab = createTaskTab(task)
  tab.classList.add("task-tab-enter")
  tab.addEventListener("animationend", ...)
  tabsContainer.appendChild(tab)
})
```

R608 改为 length snapshot + indexed loop：

```js
const addedTabCount = tabState.addedTasks.length
for (let index = 0; index < addedTabCount; index += 1) {
  if (!(index in tabState.addedTasks)) continue
  const task = tabState.addedTasks[index]
  ...
}
```

`Array.prototype.forEach()` 不访问 sparse array empty slots，因此 indexed loop 保留
`index in tabState.addedTasks` guard。显式 `undefined` task 仍会传给
`createTaskTab()` 并按旧路径失败，不新增兼容分支。R608 不改变 full rebuild 分支
和 active-tab aria 同步路径。

行为边界：

- `isIncremental` 判断不变；
- 每个 added task 仍调用 `createTaskTab(task)`；
- 新 tab 仍添加 `task-tab-enter`；
- `animationend` listener 仍使用 `{ once: true }`，并移除 `task-tab-enter`；
- append 顺序仍按 `addedTasks` 升序索引；
- sparse array empty slots 仍被跳过；
- 后续 active tab `classList.toggle` / `aria-selected` / `tabindex` 同步不变。

新增测试：

- `tests/test_multi_task_tab_added_loop_r608.py`
  - source invariant 锁定 `renderTaskTabs()` 不再使用
    `tabState.addedTasks.forEach`，并确认 `addedTabCount`、indexed loop、sparse
    guard、index 读取、`createTaskTab()`、enter class 和 append；
  - Node VM runtime 加载完整 `multi_task.js`，stub tab state / DOM 节点，给
    `addedTasks` 设置 sparse hole 和会抛错的实例级 `forEach`，验证只创建/append
    已赋值 task、enter class、`animationend` cleanup、active tab aria/tabindex
    更新和 sparse hole skip。
- `tests/test_multi_task_render_tabs_state_r526.py`
  - 更新既有 source invariant：仍要求 `renderTaskTabs()` 消费预计算
    `addedTasks`，但不再把旧 `tabState.addedTasks.forEach` 作为契约。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round135/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round135/01-mdn-array-foreach-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 只对已赋值索引调用，不访问
  sparse array empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round135/02-array-foreach-tab-add-overhead.json`
  保存 UI tab add callback-loop overhead 搜索资料：热路径中 indexed loop 可避免
  per-element callback 调用；实际瓶颈通常仍是 DOM mutation / layout，应按
  DevTools profiling 验证。

验证：

- `uv run pytest tests/test_multi_task_tab_added_loop_r608.py
  tests/test_multi_task_render_tabs_state_r526.py
  tests/test_multi_task_tab_removed_loop_r607.py` → 8 passed；
- `uv run ruff check tests/test_multi_task_tab_added_loop_r608.py
  tests/test_multi_task_render_tabs_state_r526.py`；
- `uv run ty check tests/test_multi_task_tab_added_loop_r608.py
  tests/test_multi_task_render_tabs_state_r526.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.152 R609 · WebUI full tab rebuild render 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::renderTaskTabs()` 的 full rebuild
分支会清空 `tabsContainer.innerHTML`，然后遍历 `incompleteTasks` 重建全部 tab，
并用 callback index 设置 staggered animation delay。旧路径：

```js
tabsContainer.innerHTML = ""
incompleteTasks.forEach((task, i) => {
  const tab = createTaskTab(task)
  tab.classList.add("task-tab-enter")
  tab.style.animationDelay = i * 60 + "ms"
  ...
  tabsContainer.appendChild(tab)
})
```

R609 改为 length snapshot + indexed loop，并保留原始 array index 用于动画延迟：

```js
const incompleteTaskCount = incompleteTasks.length
for (let index = 0; index < incompleteTaskCount; index += 1) {
  if (!(index in incompleteTasks)) continue
  const task = incompleteTasks[index]
  ...
  tab.style.animationDelay = index * 60 + "ms"
}
```

`Array.prototype.forEach()` 不访问 sparse array empty slots，且 callback 的第二个
参数是原数组索引；因此 indexed loop 必须用 `index in incompleteTasks` guard，
并用同一个 `index` 计算 `animationDelay`。显式 `undefined` task 仍会传给
`createTaskTab()` 并按旧路径失败，不新增兼容分支。

行为边界：

- full rebuild 仍先清空 `tabsContainer.innerHTML`；
- 每个已赋值 incomplete task 仍调用 `createTaskTab(task)`；
- 新 tab 仍添加 `task-tab-enter`；
- `animationDelay` 仍按原数组索引 `index * 60 + "ms"`；
- `animationend` listener 仍使用 `{ once: true }`，并移除 enter class、清空 delay；
- append 顺序仍按升序索引；
- sparse array empty slots 仍被跳过；
- 后续 active tab aria/tabindex 同步不变。

新增测试：

- `tests/test_multi_task_tab_rebuild_loop_r609.py`
  - source invariant 锁定 `renderTaskTabs()` 不再使用 `incompleteTasks.forEach`，
    并确认 `incompleteTaskCount`、indexed loop、sparse guard、index 读取、
    `animationDelay = index * 60 + "ms"`、`createTaskTab()` 和 append；
  - Node VM runtime 加载完整 `multi_task.js`，stub tab state / DOM 节点，给
    `incompleteTasks` 设置 sparse hole 和会抛错的实例级 `forEach`，验证 full
    rebuild 清空、只创建/append 已赋值 task、hole 后 task 的 delay 仍是 `120ms`、
    `animationend` cleanup、active aria/tabindex 更新和 sparse hole skip。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round136/00-doctor.json`
  保存本轮 smart-search 可用性诊断。
- `/tmp/smart-search-evidence/aiia-optimization-round136/01-mdn-array-foreach-index-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 按升序索引调用，第二个
  参数是当前索引，并跳过 sparse array empty slots。
- `/tmp/smart-search-evidence/aiia-optimization-round136/02-array-foreach-full-rebuild-overhead.json`
  保存 full rebuild render / animation callback-loop overhead 搜索资料：render
  hot path 中 indexed loop 可避免 per-element callback 调用；DOM rebuild / layout
  / animation jank 仍应按 DevTools profiling 验证。

验证：

- `uv run pytest tests/test_multi_task_tab_rebuild_loop_r609.py
  tests/test_multi_task_render_tabs_state_r526.py
  tests/test_multi_task_tab_added_loop_r608.py
  tests/test_multi_task_tab_removed_loop_r607.py` → 10 passed；
- `uv run ruff check tests/test_multi_task_tab_rebuild_loop_r609.py`；
- `uv run ty check tests/test_multi_task_tab_rebuild_loop_r609.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.153 R610 · WebUI rebuilt active-tab sync 去 NodeList.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::renderTaskTabs()` 在 tab rebuild
后会重新查询当前未退出的 `.task-tab`，再同步 active class、`aria-selected` 和
`tabindex`。旧路径把 `querySelectorAll()` 的结果直接接 `.forEach()`：

```js
tabsContainer
  .querySelectorAll(".task-tab:not(.task-tab-exit)")
  .forEach((tab) => {
    const taskId = tab.dataset.taskId
    const isActive = taskId === activeTaskId
    tab.classList.toggle("active", isActive)
    tab.setAttribute("aria-selected", isActive ? "true" : "false")
    tab.setAttribute("tabindex", isActive ? "0" : "-1")
  })
```

R610 改为显式保存静态 NodeList 快照并缓存 `length`：

```js
const activeTabs = tabsContainer.querySelectorAll(
  ".task-tab:not(.task-tab-exit)",
)
const activeTabCount = activeTabs.length
for (let index = 0; index < activeTabCount; index += 1) {
  if (!(index in activeTabs)) continue
  const tab = activeTabs[index]
  ...
}
```

`querySelectorAll()` 返回 static / non-live `NodeList`，适合在本轮同步中缓存
集合与长度；`NodeList.forEach()` 是 callback 式遍历。这里不需要 `thisArg`、
callback index 或 list object，因此 indexed loop 避免了每个 tab 的 callback
调用，同时保留 DOM 快照遍历语义。`index in activeTabs` guard 让测试覆盖
NodeList-like sparse hole，和前几轮 `Array.prototype.forEach()` sparse 行为保持
一致；真实浏览器 `querySelectorAll()` 返回的 NodeList 通常是 dense 的，这个
guard 不改变正常路径。

行为边界：

- 仍只在 `tabState.needsRebuild` 分支完成后同步 rebuilt tabs；
- selector 仍为 `.task-tab:not(.task-tab-exit)`；
- active 判断仍是 `tab.dataset.taskId === activeTaskId`；
- active tab 仍设置 `active=true`、`aria-selected="true"`、`tabindex="0"`；
- 非 active tab 仍设置 `active=false`、`aria-selected="false"`、`tabindex="-1"`；
- 不改变 `tabState.existingTabs` 的 no-rebuild 分支，后续单独审计。

新增测试：

- `tests/test_multi_task_tab_active_sync_loop_r610.py`
  - source invariant 锁定 `renderTaskTabs()` rebuild active sync 不再把
    `querySelectorAll(".task-tab:not(.task-tab-exit)")` 直接接 `.forEach()`，
    并确认 `activeTabs`、`activeTabCount`、indexed loop、sparse guard、index
    读取和 active/aria/tabindex 设置；
  - Node VM runtime 加载完整 `multi_task.js`，stub full rebuild DOM，令
    `querySelectorAll()` 返回带 sparse hole 且 `forEach()` 会抛错的
    NodeList-like 对象，验证 first/third tab 均完成 active/aria/tabindex 同步。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round137/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round137/03-exa-mdn-queryselectorall-static-nodelist.json`
  保存 MDN `Document.querySelectorAll()` 资料：返回 static / non-live NodeList，
  元素按 document order；
- `/tmp/smart-search-evidence/aiia-optimization-round137/04-exa-mdn-nodelist-foreach-callback.json`
  保存 MDN `NodeList.forEach()` 资料：会按 insertion order 对每个 value pair
  调用 callback；
- `/tmp/smart-search-evidence/aiia-optimization-round137/05-context7-mdn-library.json`
  保存 Context7 对 MDN Web Docs 资料库的定位信息，作为官方文档检索补充。

验证：

- `uv run pytest tests/test_multi_task_tab_active_sync_loop_r610.py
  tests/test_multi_task_tab_rebuild_loop_r609.py
  tests/test_multi_task_tab_added_loop_r608.py
  tests/test_multi_task_tab_removed_loop_r607.py
  tests/test_multi_task_tab_existing_loop_r605.py
  tests/test_multi_task_render_tabs_state_r526.py` → 14 passed；
- `uv run ruff check tests/test_multi_task_tab_active_sync_loop_r610.py`；
- `uv run ty check tests/test_multi_task_tab_active_sync_loop_r610.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.154 R611 · WebUI existing active-tab sync 去 NodeList.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::renderTaskTabs()` 的 no-rebuild
分支不会创建或删除 tab，只会对 `_buildTaskTabRenderState()` 里已查询出的
`tabState.existingTabs` 同步 active class、`aria-selected` 和 `tabindex`。旧路径：

```js
tabState.existingTabs.forEach((tab) => {
  const taskId = tab.dataset.taskId
  const isActive = taskId === activeTaskId
  tab.classList.toggle("active", isActive)
  tab.setAttribute("aria-selected", isActive ? "true" : "false")
  tab.setAttribute("tabindex", isActive ? "0" : "-1")
})
```

R611 改为 length snapshot + indexed loop：

```js
const syncedTabCount = tabState.existingTabs.length
for (let index = 0; index < syncedTabCount; index += 1) {
  if (!(index in tabState.existingTabs)) continue
  const tab = tabState.existingTabs[index]
  ...
}
```

`tabState.existingTabs` 来自同一 render pass 的 `querySelectorAll()` 静态 NodeList
快照；该分支不使用 `NodeList.forEach()` 的 callback index / list object /
`thisArg`，因此显式索引循环保留同一快照语义，并避免每个现有 tab 的 callback
调用。`index in tabState.existingTabs` guard 与 R610 一致，覆盖 NodeList-like
sparse hole 测试边界。

行为边界：

- 只改变 `tabState.needsRebuild === false` 分支；
- 不重新查询 DOM，不创建、不删除、不 append tab；
- active 判断仍是 `tab.dataset.taskId === activeTaskId`；
- active tab 仍设置 `active=true`、`aria-selected="true"`、`tabindex="0"`；
- 非 active tab 仍设置 `active=false`、`aria-selected="false"`、`tabindex="-1"`；
- rebuild 后 active sync 的 R610 路径不变。

新增测试：

- `tests/test_multi_task_tab_existing_active_sync_loop_r611.py`
  - source invariant 锁定 `renderTaskTabs()` 不再使用
    `tabState.existingTabs.forEach`，并确认 `syncedTabCount`、indexed loop、
    sparse guard、index 读取和 active/aria/tabindex 设置；
  - Node VM runtime 加载完整 `multi_task.js`，stub no-rebuild tab state，使
    `existingTabs` 为带 sparse hole 且 `forEach()` 会抛错的 NodeList-like 对象，
    验证 first/third tab 均完成 active/aria/tabindex 同步。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round138/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round138/01-exa-mdn-nodelist-static-length-loop.json`
  保存 MDN `querySelectorAll()` / `NodeList` 资料：`querySelectorAll()` 返回
  static / non-live NodeList，NodeList 可用 length 和标准数组下标访问，也可用
  for loop 遍历；
- `/tmp/smart-search-evidence/aiia-optimization-round138/02-exa-mdn-nodelist-foreach-callback.json`
  保存 MDN `NodeList.forEach()` 资料：按 insertion order 对每个 value pair
  调用 callback。

验证：

- `uv run pytest tests/test_multi_task_tab_existing_active_sync_loop_r611.py
  tests/test_multi_task_tab_active_sync_loop_r610.py
  tests/test_multi_task_tab_rebuild_loop_r609.py
  tests/test_multi_task_tab_added_loop_r608.py
  tests/test_multi_task_tab_removed_loop_r607.py
  tests/test_multi_task_tab_existing_loop_r605.py
  tests/test_multi_task_render_tabs_state_r526.py` → 16 passed；
- `uv run ruff check tests/test_multi_task_tab_existing_active_sync_loop_r611.py`；
- `uv run ty check tests/test_multi_task_tab_existing_active_sync_loop_r611.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.155 R612 · WebUI switchTask option-state 保存去 NodeList.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::switchTask()` 在切换任务前会保存
当前任务的 checkbox 勾选状态。旧路径对 `optionsContainer.querySelectorAll()`
返回的集合直接 `.forEach()`，并依赖 callback index 写入数组：

```js
const checkboxes = optionsContainer.querySelectorAll(
  'input[type="checkbox"]',
)
const optionsStates = []
checkboxes.forEach((checkbox, index) => {
  optionsStates[index] = checkbox.checked
})
taskOptionsStates[activeTaskId] = optionsStates
```

R612 改为 length snapshot + indexed loop：

```js
const optionCheckboxCount = checkboxes.length
for (let index = 0; index < optionCheckboxCount; index += 1) {
  if (!(index in checkboxes)) continue
  const checkbox = checkboxes[index]
  optionsStates[index] = checkbox.checked
}
```

`querySelectorAll()` 返回 static / non-live `NodeList`，可用 `length` 和标准数组
下标访问；`NodeList.forEach()` 会为每个 value pair 调用 callback，并提供
`currentIndex`。这里唯一需要的是原 index 写回 `optionsStates[index]`，因此
显式索引循环可以保留状态数组的 index 语义，同时避免每个 checkbox 的 callback
调用。`index in checkboxes` guard 覆盖 NodeList-like sparse hole 测试边界；
真实浏览器 checkbox NodeList 是 dense 的，正常路径行为不变。

行为边界：

- 只改变 `switchTask()` 保存旧 active task 选项状态的循环；
- textarea draft 保存不变；
- `taskOptionsStates[activeTaskId]` 仍是按 checkbox index 写入的数组；
- sparse-like hole 仍不生成 own property，JSON 形态表现为 `null`；
- 图片列表仍通过 `cloneTaskImagesForState(selectedImages)` 保存；
- activate 请求、`loadTaskDetails()`、tab render 和 countdown color update 不变。

新增测试：

- `tests/test_multi_task_switch_options_loop_r612.py`
  - source invariant 锁定 `switchTask()` 不再使用
    `checkboxes.forEach((checkbox, index)`，并确认 `optionCheckboxCount`、
    indexed loop、sparse guard、index 读取和 `optionsStates[index]` 写入；
  - Node VM runtime 加载完整 `multi_task.js`，stub 当前 textarea / options
    container / task list，使 checkbox 集合为带 sparse hole 且 `forEach()` 会抛错
    的 NodeList-like 对象，验证切换到 next task 后旧 task 的 draft、options
    和 images 状态保存不变。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round139/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round139/01-exa-mdn-queryselectorall-nodelist-loop.json`
  保存 MDN `Document.querySelectorAll()` / `NodeList` 资料：返回 static /
  non-live NodeList，可按 `length`、标准数组下标和普通循环访问；
- `/tmp/smart-search-evidence/aiia-optimization-round139/02-exa-mdn-nodelist-foreach-index.json`
  保存 MDN `NodeList.forEach()` / `Array.prototype.forEach()` 资料：callback 会
  接收当前元素和 index，callback 形式用于逐项副作用。

验证：

- `uv run pytest tests/test_multi_task_switch_options_loop_r612.py
  tests/test_multi_task_active_task_reconcile_r452.py
  tests/test_multi_task_task_lookup_direct_loop_r574.py
  tests/test_multi_task_image_clone_one_pass_r572.py` → 14 passed；
- `uv run ruff check tests/test_multi_task_switch_options_loop_r612.py`；
- `uv run ty check tests/test_multi_task_switch_options_loop_r612.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.156 R613 · WebUI restored image previews 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::loadTaskDetails()` 在恢复某任务
之前保存的图片列表时，会先通过 `cloneTaskImagesForState()` 深拷贝状态，再清空
`#image-previews` 并逐项调用 `renderImagePreview(imageItem, false)`。旧路径：

```js
selectedImages = cloneTaskImagesForState(taskImages[taskId])
const previewContainer = document.getElementById("image-previews")
if (previewContainer) {
  previewContainer.innerHTML = ""
  selectedImages.forEach((imageItem) => {
    renderImagePreview(imageItem, false)
  })
  updateImageCounter()
  updateImagePreviewVisibility()
}
```

R613 改为 length snapshot + indexed loop：

```js
const restoredImageCount = selectedImages.length
for (
  let imageIndex = 0;
  imageIndex < restoredImageCount;
  imageIndex += 1
) {
  if (!(imageIndex in selectedImages)) continue
  const imageItem = selectedImages[imageIndex]
  renderImagePreview(imageItem, false)
}
```

`Array.prototype.forEach()` 会跳过 sparse array empty slots，并对已存在 index 调用
callback；`cloneTaskImagesForState()` 也保留 sparse hole。新循环用
`imageIndex in selectedImages` 保留同一 sparse skip 语义，同时避免恢复每张图片
时创建/调用 callback。显式 `undefined` 图片项仍是存在的 index，会继续传入
`renderImagePreview()`，不新增兼容分支。

行为边界：

- 只改变 `loadTaskDetails()` 恢复已保存图片预览的循环；
- `cloneTaskImagesForState(taskImages[taskId])` 调用不变；
- `previewContainer.innerHTML = ""` 仍先清空旧预览；
- 每个已赋值 image item 仍调用 `renderImagePreview(imageItem, false)`；
- sparse hole 仍跳过；
- `updateImageCounter()` 和 `updateImagePreviewVisibility()` 仍各调用一次；
- 倒计时启动和任务详情其他 UI 同步不变。

新增测试：

- `tests/test_multi_task_restore_images_loop_r613.py`
  - source invariant 锁定 `loadTaskDetails()` 不再使用
    `selectedImages.forEach((imageItem)`，并确认 `restoredImageCount`、indexed
    loop、sparse guard、index 读取和 `renderImagePreview(imageItem, false)`；
  - Node VM runtime 加载完整 `multi_task.js`，stub task detail fetch / UI helper，
    给 `taskImages[taskId]` 设置 sparse hole，并在调用期间禁用
    `Array.prototype.forEach`，验证只渲染已赋值图片、hole 被保留、计数/可见性
    更新各执行一次。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round140/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round140/01-exa-mdn-array-foreach-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 只对已赋值 index 调用，
  不访问 sparse array empty slots；
- `/tmp/smart-search-evidence/aiia-optimization-round140/02-exa-array-for-loop-callback-overhead.json`
  保存 JavaScript array loop / callback overhead 资料：`forEach` 语义包含
  callback 调用和 length-index 遍历；热路径中显式索引循环可以减少 callback
  分配/调用面，仍需以具体路径回归验证。

验证：

- `uv run pytest tests/test_multi_task_restore_images_loop_r613.py
  tests/test_multi_task_image_clone_one_pass_r572.py
  tests/test_multi_task_active_task_reconcile_r452.py
  tests/test_multi_task_task_lookup_direct_loop_r574.py
  tests/test_multi_task_switch_options_loop_r612.py` → 16 passed；
- `uv run ruff check tests/test_multi_task_restore_images_loop_r613.py`；
- `uv run ty check tests/test_multi_task_restore_images_loop_r613.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.157 R614 · WebUI existing option scan 去 NodeList.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::updateOptionsDisplay()` 在当前
task 没有已保存 selection state 时，会先扫描旧 DOM 里的 checkbox，把现有 UI
状态转成 `selectedStates[checkbox.id] = checkbox.checked`，避免同一任务内刷新
选项时被后端 default 覆盖。旧路径：

```js
const existingCheckboxes = optionsContainer.querySelectorAll(
  'input[type="checkbox"]',
)
existingCheckboxes.forEach((checkbox) => {
  selectedStates[checkbox.id] = checkbox.checked
})
if (existingCheckboxes.length > 0) {
  hasUserInteraction = true
}
```

R614 改为 length snapshot + indexed loop：

```js
const existingCheckboxCount = existingCheckboxes.length
for (let index = 0; index < existingCheckboxCount; index += 1) {
  if (!(index in existingCheckboxes)) continue
  const checkbox = existingCheckboxes[index]
  selectedStates[checkbox.id] = checkbox.checked
}
```

`querySelectorAll()` 返回 static / non-live `NodeList`，可用 `length` 和标准数组
下标访问；`NodeList.forEach()` 会为每个 value pair 调用 callback。这里不需要
callback index / list object / `thisArg`，只需要逐项读取 checkbox id 与 checked
状态，因此索引循环保留同一 DOM 快照语义，同时减少 callback 调用面。`length > 0`
的 `hasUserInteraction` 判断保持不变。

行为边界：

- 只改变 `updateOptionsDisplay()` 中 no saved-state 分支的旧 checkbox 扫描；
- `selectedStates[checkbox.id] = checkbox.checked` 写入不变；
- `existingCheckboxes.length > 0` 仍控制 `hasUserInteraction`；
- 旧 DOM 状态仍优先于后端 `optionDefaults`；
- 后续 options render 的 `options.forEach()` 不在本切片中处理；
- hidden / visible class、separator 更新不变。

新增测试：

- `tests/test_multi_task_existing_options_loop_r614.py`
  - source invariant 锁定 `updateOptionsDisplay()` 不再使用
    `existingCheckboxes.forEach((checkbox)`，并确认 `existingCheckboxCount`、
    indexed loop、sparse guard、index 读取和 selectedStates 写入；
  - Node VM runtime 加载完整 `multi_task.js`，stub options container，使
    `querySelectorAll()` 返回带 sparse hole 且 `forEach()` 会抛错的 NodeList-like
    对象，验证旧 DOM 的 false/true 状态优先于全 true defaults，并确认 container
    / separator visible class 更新仍执行。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round141/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round141/01-exa-mdn-queryselectorall-static-nodelist.json`
  保存 MDN `Document.querySelectorAll()` / `NodeList` 资料：返回 static /
  non-live NodeList，可按 `length`、标准数组下标和普通循环访问；
- `/tmp/smart-search-evidence/aiia-optimization-round141/02-exa-mdn-nodelist-foreach-callback.json`
  保存 MDN `NodeList.forEach()` 资料：按 insertion order 对每个 value pair 调用
  callback，callback 接收 currentValue / currentIndex / listObj。

验证：

- `uv run pytest tests/test_multi_task_existing_options_loop_r614.py
  tests/test_multi_task_switch_options_loop_r612.py
  tests/test_multi_task_active_task_reconcile_r452.py
  tests/test_multi_task_task_lookup_direct_loop_r574.py` → 14 passed；
- `uv run ruff check tests/test_multi_task_existing_options_loop_r614.py`；
- `uv run ty check tests/test_multi_task_existing_options_loop_r614.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`。

### 3.158 R615 · WebUI option render 去 Array.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::updateOptionsDisplay()` 在渲染
后端 `predefined_options` 时，旧路径对 `options.forEach((option, index) => ...)`
逐项创建 checkbox / label：

```js
options.forEach((option, index) => {
  const optionDiv = document.createElement("div")
  const checkbox = document.createElement("input")
  checkbox.id = `option-${index}`
  checkbox.value = option
  const checkboxId = `option-${index}`
  ...
  optionsContainer.appendChild(optionDiv)
})
```

R615 改为保留 sparse-array 语义的 length snapshot + indexed loop：

```js
const optionCount = options.length
for (let index = 0; index < optionCount; index += 1) {
  if (!(index in options)) continue
  const option = options[index]
  ...
}
```

MDN 记录 `Array.prototype.forEach()` 对 empty slots 不调用 callback，并且 callback
会收到 element / index / array；JavaScript 引擎实现资料也提示普通 indexed loop
能避开 callback 调用开销。这里必须保留 `index`，因为 DOM id、label `htmlFor`、
旧 selection state key 和 `optionDefaults[index]` 都以原数组下标为契约。`index in
options` guard 保持 sparse hole 跳过行为，显式 `undefined` 元素仍会像旧
`forEach()` 一样被渲染。

行为边界：

- 只改变 `updateOptionsDisplay()` 中 options render 的循环形式；
- `checkbox.id = \`option-${index}\``、`label.htmlFor`、`checkboxId` key 不变；
- `defaults[index] === true` 仍按原始数组下标读取默认勾选；
- sparse hole 继续跳过，显式 `undefined` option 继续渲染；
- selected state 优先级、container visible / hidden、separator 更新不变；
- autosave 的 `checkboxes.forEach((cb) => ...)` 留给后续切片。

新增测试：

- `tests/test_multi_task_options_render_loop_r615.py`
  - source invariant 锁定 `updateOptionsDisplay()` 不再使用
    `options.forEach((option, index)`，并确认 `optionCount`、indexed loop、
    sparse guard、`options[index]`、`option-${index}` id 和 `defaults[index]`
    契约；
  - Node VM runtime 加载完整 `multi_task.js`，stub sparse `options = ["A", hole,
    "C"]` 且让 `options.forEach()` 抛错，验证只渲染 `option-0` / `option-2`，
    `option-2` 从 defaults 勾选，`option-1` 不被创建，同时 container /
    separator visible class 更新仍执行。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round142/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round142/01-exa-mdn-array-foreach-index-sparse.json`
  保存 MDN `Array.prototype.forEach()` 资料：callback 接收 element / index /
  array，且不会对 empty slots 调用；
- `/tmp/smart-search-evidence/aiia-optimization-round142/02-exa-array-loop-callback-overhead.json`
  保存数组循环与 callback 开销相关资料，用于支持在热路径中移除不必要 callback
  dispatch 的微优化方向。

验证：

- `uv run pytest tests/test_multi_task_options_render_loop_r615.py` → 2 passed。
- `uv run pytest tests/test_multi_task_options_render_loop_r615.py
  tests/test_multi_task_existing_options_loop_r614.py
  tests/test_multi_task_switch_options_loop_r612.py
  tests/test_multi_task_active_task_reconcile_r452.py
  tests/test_multi_task_task_lookup_direct_loop_r574.py` → 16 passed；
- `uv run ruff check tests/test_multi_task_options_render_loop_r615.py`；
- `uv run ty check tests/test_multi_task_options_render_loop_r615.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`；
- `/tmp/smart-search-evidence/aiia-optimization-round142/` empty-file scan；
- `rg -n "options\\.forEach\\(\\(option, index\\)|checkboxes\\.forEach\\(\\(cb\\)"
  src/ai_intervention_agent/static/js/multi_task.js` → only autosave follow-up
  remains at `checkboxes.forEach((cb) => ...)`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.159 R616 · WebUI realtime option autosave 去 NodeList.forEach callback

`src/ai_intervention_agent/static/js/multi_task.js::handleRealtimeOptionsAutosave()`
在 checkbox change/input 事件触发时，会重新扫描当前 options container 中所有
checkbox，把实时勾选状态保存到 `taskOptionsStates[activeTaskId]`。旧路径：

```js
const checkboxes = optionsContainer.querySelectorAll(
  'input[type="checkbox"]',
)
const states = {}
checkboxes.forEach((cb) => {
  states[cb.id] = cb.checked
})
taskOptionsStates[activeTaskId] = states
```

R616 改为 length snapshot + indexed loop：

```js
const checkboxCount = checkboxes.length
for (let index = 0; index < checkboxCount; index += 1) {
  if (!(index in checkboxes)) continue
  const checkbox = checkboxes[index]
  states[checkbox.id] = checkbox.checked
}
```

`querySelectorAll()` 返回 static / non-live `NodeList`，可用 `length` 与数组下标
读取；`NodeList.forEach()` 会按 insertion order 为每个 value pair 调 callback。
这个 autosave 热路径不使用 callback index、list object 或 `thisArg`，只需要把
checkbox id 映射到 checked 布尔值，因此 indexed loop 保留同一 DOM 快照语义，
并移除一次事件响应里的 callback dispatch。

行为边界：

- 只改变 `handleRealtimeOptionsAutosave()` 中 checkbox snapshot 的循环形式；
- 事件 guard 不变：无 active task、非 checkbox 事件、无 options container 都
  继续早退；
- `querySelectorAll('input[type="checkbox"]')` selector 不变；
- `states[checkbox.id] = checkbox.checked` 与 `taskOptionsStates[activeTaskId]`
  写入不变；
- sparse NodeList-like hole 继续跳过，正常 DOM NodeList 顺序语义不变。

新增测试：

- `tests/test_multi_task_realtime_options_loop_r616.py`
  - source invariant 锁定 `handleRealtimeOptionsAutosave()` 不再使用
    `checkboxes.forEach((cb)`，并确认 `checkboxCount`、indexed loop、
    sparse guard、index 读取和 state 写入；
  - Node VM runtime 加载完整 `multi_task.js`，stub `querySelectorAll()` 返回
    sparse NodeList-like 对象且让 `forEach()` 抛错，验证只保存 `option-0` /
    `option-2` 的 checked 状态，并保持 sparse hole 不被写入。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round143/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round143/01-exa-mdn-queryselectorall-static-nodelist.json`
  保存 MDN `Document.querySelectorAll()` / `NodeList` 资料：返回 static /
  non-live NodeList，可按 `length`、标准数组下标和普通循环访问；
- `/tmp/smart-search-evidence/aiia-optimization-round143/02-exa-mdn-nodelist-foreach-callback.json`
  保存 MDN `NodeList.forEach()` 资料：按 insertion order 对每个 value pair 调用
  callback，callback 接收 currentValue / currentIndex / listObj。

验证：

- `uv run pytest tests/test_multi_task_realtime_options_loop_r616.py` → 2 passed。
- `uv run pytest tests/test_multi_task_realtime_options_loop_r616.py
  tests/test_multi_task_options_render_loop_r615.py
  tests/test_multi_task_existing_options_loop_r614.py
  tests/test_multi_task_switch_options_loop_r612.py
  tests/test_multi_task_active_task_reconcile_r452.py
  tests/test_multi_task_task_lookup_direct_loop_r574.py` → 18 passed；
- `uv run ruff check tests/test_multi_task_realtime_options_loop_r616.py`；
- `uv run ty check tests/test_multi_task_realtime_options_loop_r616.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.js`；
- `uv run python scripts/minify_assets.py`；
- `uv run python scripts/precompress_static.py`；
- `node --check src/ai_intervention_agent/static/js/multi_task.min.js`；
- `uv run python scripts/minify_assets.py --check`；
- `uv run python scripts/precompress_static.py --check`；
- `/tmp/smart-search-evidence/aiia-optimization-round143/` non-empty evidence scan；
- `rg -n "options\\.forEach\\(\\(option, index\\)|checkboxes\\.forEach\\(\\(cb\\)"
  src/ai_intervention_agent/static/js/multi_task.js` → no matches；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.160 R617 · Prometheus histogram +Inf fallback 去 dict copy / 二次 sort

`src/ai_intervention_agent/web_ui_routes/system.py::_format_prom_histogram_family()`
在 caller 漏传 `+Inf` bucket 时，会兜底补一个等于 `count` 的 `+Inf` bucket。
旧路径为了补桶会复制整个 buckets dict，并再次排序：

```python
sorted_keys = sorted(buckets.keys())
if not sorted_keys or sorted_keys[-1] != float("inf"):
    buckets = dict(buckets)
    buckets[float("inf")] = count
    sorted_keys = sorted(buckets.keys())
```

R617 改为：

```python
sorted_keys = sorted(buckets)
has_inf_bucket = bool(sorted_keys) and sorted_keys[-1] == _PROM_INF
if not has_inf_bucket:
    sorted_keys.append(_PROM_INF)
...
bucket_value = buckets[le] if has_inf_bucket or le != _PROM_INF else count
```

Prometheus / OpenMetrics 对 classic histogram 的 `+Inf` bucket 有强约束：
`+Inf` bucket 必须存在，并且 count 应等于 `+Inf` bucket。Python `sorted()`
接受任意 iterable，dict 自身迭代的就是 key；因此 `sorted(buckets)` 保留
`sorted(buckets.keys())` 的 key 顺序语义，同时少一次 method lookup / view
创建。缺 `+Inf` 时直接 append `_PROM_INF`，避免复制 buckets，也避免第二次
排序；已有 `+Inf` 时继续读取 caller 提供的 bucket value，不改变历史输出。

行为边界：

- 只改变 histogram helper 内 `+Inf` fallback 的实现方式；
- 有 `+Inf` bucket 的正常路径输出不变，仍使用 caller bucket value；
- 缺 `+Inf` bucket 时仍渲染 `count` 作为 fallback bucket value；
- 原始 `buckets` mapping 不被 mutation；
- `_bucket` / `_sum` / `_count` 顺序、HELP/TYPE 唯一性、label 合并语义不变；
- `_format_prom_value()` 只把 `float("inf")` / `float("-inf")` 常量化为
  `_PROM_INF` / `_PROM_NEG_INF`，输出字符串不变。

新增测试：

- `tests/test_prom_histogram_inf_fallback_r617.py`
  - source invariant 锁定不再出现 `sorted(buckets.keys())`、`buckets =
    dict(buckets)`、`buckets[_PROM_INF] = count`，并确认 `sorted(buckets)`、
    `sorted_keys.append(_PROM_INF)` 和 fallback `bucket_value` 分支；
  - runtime 验证缺 `+Inf` 时渲染 fallback count 且不修改原 buckets dict；
  - runtime 验证已有 `+Inf` 时保留 caller 的 bucket value，即使与冗余
    `count` 参数不同。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round144/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round144/01-exa-prometheus-histogram-inf-bucket.json`
  保存 Prometheus / OpenMetrics histogram 资料：classic histogram 必须包含
  `+Inf` bucket，且 `Count` 必须等于 `+Inf` bucket；
- `/tmp/smart-search-evidence/aiia-optimization-round144/02-exa-python-dict-iteration-keys-sorted.json`
  保存 Python 官方 sorting / data-structure 资料：`sorted()` 接受 iterable，
  dict 输入示例按 key 排序。

验证：

- `uv run pytest tests/test_prom_histogram_inf_fallback_r617.py` → 3 passed；
- `uv run pytest tests/test_prom_histogram_inf_fallback_r617.py
  tests/test_prom_histogram_r190.py
  tests/test_prom_family_iterables_r518.py
  tests/test_prom_metric_family_iterable_r517.py
  tests/test_prom_labels_generator_r516.py
  tests/test_system_metrics_prometheus_r186.py` → 67 passed；
- `uv run ruff check tests/test_prom_histogram_inf_fallback_r617.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_histogram_inf_fallback_r617.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round144/` non-empty evidence scan；
- source invariant scan for removed `sorted(buckets.keys())` / `buckets =
  dict(buckets)` implementation；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.161 R618 · Prometheus histogram bucket label 去每桶 dict merge

`_format_prom_histogram_family()` 旧路径每渲染一个 bucket 都会构造一个临时
dict，再交给 `_format_prom_labels()`：

```python
merged_labels = {"le": le_label_value, **(base_labels or {})}
label_str = _format_prom_labels(merged_labels)
```

histogram scrape 输出里每个 observation 都有多个 `_bucket` 行；当 `base_labels`
存在时，这会在每个 bucket 上重复分配一个 dict，只为把 `le` 放在 label set
第一位。R618 新增 `_format_prom_histogram_bucket_labels()`：

- 无 `base_labels`：直接返回 `{le="..."}`；
- 正常 `base_labels`：直接用 `str.join()` 拼接 `le` + `base_labels.items()`，
  不构造 merged dict；
- 极端 `base_labels` 自带 `le`：回退到旧的 `{"le": ..., **base_labels}` 语义，
  保留 caller override 行为，避免隐藏行为变化。

Prometheus / OpenMetrics label set 是 key-value pair，histogram 明确把 `le`
作为 bucket 维度；官方文档要求 quoted 名称/值中的 `\`、`\n`、`"` 做 escape。
Python `str.join(iterable)` 是构造字符串片段的标准线性方式；这里复用既有
`_escape_prom_label_value()`，只消除每桶 dict merge。

行为边界：

- 只改变 histogram bucket label string 的构造方式；
- label 顺序保持 `le` 在前，随后是 `base_labels` 插入顺序；
- label value escaping 与 `_format_prom_labels()` 保持一致；
- `base_labels["le"]` 冲突时保留旧 override 输出；
- `_sum` / `_count` 仍走 `_format_prom_labels(base_labels)`；
- R617 的 `+Inf` fallback 行为不变。

新增测试：

- `tests/test_prom_histogram_bucket_labels_r618.py`
  - source invariant 锁定 histogram render path 不再出现
    `merged_labels = {"le": ...}`，并确认调用新 helper；
  - helper runtime 覆盖正常 label 顺序、反斜杠 / 双引号 / 换行 escaping；
  - helper runtime 覆盖 `base_labels` 自带 `le` 的 legacy override edge；
  - full histogram output runtime 验证 `_bucket` label 顺序仍为
    `le,tool,status`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round145/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round145/01-exa-prometheus-label-format.json`
  保存 Prometheus / OpenMetrics label 资料：label 是 key-value pair，
  histogram `le` 是 bucket label，quoted 字符串中的 `\` / `\n` / `"` 需要 escape；
- `/tmp/smart-search-evidence/aiia-optimization-round145/02-exa-python-str-join-iterable.json`
  保存 Python 官方 `str.join(iterable)` 资料：用 join 构造字符串片段，避免重复
  字符串拼接的二次复杂度。

验证：

- `uv run pytest tests/test_prom_histogram_bucket_labels_r618.py` → 4 passed；
- `uv run pytest tests/test_prom_histogram_bucket_labels_r618.py
  tests/test_prom_histogram_inf_fallback_r617.py
  tests/test_prom_histogram_r190.py
  tests/test_prom_family_iterables_r518.py
  tests/test_prom_metric_family_iterable_r517.py
  tests/test_prom_labels_generator_r516.py
  tests/test_system_metrics_prometheus_r186.py` → 71 passed；
- `uv run ruff check tests/test_prom_histogram_bucket_labels_r618.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_histogram_bucket_labels_r618.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round145/` non-empty evidence scan；
- source invariant scan for removed `merged_labels = {"le": ...}` render path；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.162 R619 · Prometheus SSE by-type 排序去 item tuple staging

`GET /api/system/metrics` 渲染
`aiia_sse_emit_by_type_total{event_type="..."}` 时，R517 已经把 sample list
改成 generator，但 generator 仍然依赖：

```python
for et, count in sorted(emit_by_type_raw.items())
```

`dict.items()` 会创建 view，`sorted(...)` 还会把每个 `(key, value)` item 放进
排序列表；后续 generator 再拆包成 `et, count`。R619 把这段收敛成专用
iterator：

```python
def _iter_sse_emit_by_type_samples(emit_by_type: dict[Any, Any]) -> Iterator[_PromSample]:
    for event_type in sorted(emit_by_type):
        count = emit_by_type[event_type]
        if isinstance(count, int | float):
            yield {"event_type": str(event_type)}, int(count)
```

call site 直接传 `samples=_iter_sse_emit_by_type_samples(emit_by_type_raw)`。
这样保留 deterministic key 顺序，同时避免先 staging `(event_type, count)` item
tuples；每个 key 的 value 只在排序后读取一次，过滤逻辑仍在 yield 前执行。

行为边界：

- 正常 string event_type 仍按字典序输出，Prometheus family HELP / TYPE /
  sample 行顺序不变；
- 非数值 count 仍被跳过；
- `event_type` label 仍走 `str(event_type)`，既有非字符串 key 的 label 输出不变；
- 混合不可比较 key 仍在 `sorted(...)` 阶段抛 `TypeError`，不吞掉 caller 数据错误；
- `aiia_sse_emit_total` 与 `aiia_sse_emit_by_type_total` 的并存语义和 label 维度不变。

新增测试：

- `tests/test_prom_sse_emit_by_type_keys_r619.py`
  - helper runtime 覆盖 key 排序、非数值 count 过滤和输出 label/value；
  - helper runtime 覆盖混合不可比较 key 仍抛 `TypeError`；
  - source invariant 锁定 render path 不再出现
    `sorted(emit_by_type_raw.items())`，并确认调用
    `_iter_sse_emit_by_type_samples()`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round146/00-doctor.json`
  保存本轮 smart-search 可用性诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round146/01-exa-python-dict-sorted-keys.json`
  保存 Python 官方 sorting / data-structure 资料：`sorted()` 接受 iterable，
  dict 迭代语义是 key，`items()` 暴露 key/value item；
- `/tmp/smart-search-evidence/aiia-optimization-round146/02-exa-prometheus-label-dimensions.json`
  保存 Prometheus / OpenMetrics 资料：label 是 metric 的维度，保留
  `event_type` label 语义是本轮行为边界。

验证：

- `uv run pytest tests/test_prom_sse_emit_by_type_keys_r619.py` → 3 passed；
- `uv run pytest tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_prom_metric_family_iterable_r517.py
  tests/test_prom_family_iterables_r518.py
  tests/test_system_metrics_prometheus_r186.py` → 52 passed, 4 subtests passed；
- `uv run ruff check tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round146/` non-empty evidence scan；
- source invariant scan for removed `sorted(emit_by_type_raw.items())` render path；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.163 R620 · Prometheus scrape 静态 metric spec hoist

`_render_prometheus_metrics()` 是 `/api/system/metrics` 的 scrape render path。
旧实现把几组完全静态的字段定义写在函数内部：

- `sse_counter_fields`；
- `sse_gauge_fields`；
- SSE latency quantile tuple；
- `_per_provider_field_specs`。

这些 tuple 只描述 metric name、snapshot key、help text 和 metric type，不依赖
request、snapshot、config 或当前时间；每次 scrape 重建它们只会增加局部分配和
字节码执行。R620 把它们 hoist 为模块级 immutable tuple 常量：

```python
_SSE_COUNTER_FIELD_SPECS = (...)
_SSE_GAUGE_FIELD_SPECS = (...)
_SSE_LATENCY_QUANTILE_SPECS = (...)
_NOTIFICATION_PROVIDER_FIELD_SPECS = (...)
```

render path 仍在原位置读取动态 `snap` / `notif`，并按这些常量的原顺序 emit。
Prometheus/OpenMetrics 对同一 metric 的 label set 和 metric family 语义敏感，
因此本轮只移动静态规格，不改变 metric name、help text、type、label key 或
输出顺序。

行为边界：

- SSE counter/gauge metric 输出顺序不变；
- SSE latency `quantile="0.5"` / `quantile="0.95"` 顺序不变；
- notification per-provider family 顺序不变；
- HELP/TYPE 唯一性、metric names、source snapshot keys、numeric coercion 不变；
- dynamic subsystem calls 和 exception isolation 仍在 `_render_prometheus_metrics()`
  内，未把任何 runtime state 提前到 import time。

新增测试：

- `tests/test_prom_static_metric_specs_r620.py`
  - runtime 验证 SSE counter/gauge/latency spec 顺序；
  - runtime 验证 notification per-provider spec 顺序；
  - source invariant 锁定 render path 不再定义 `sse_counter_fields`、
    `sse_gauge_fields`、`_per_provider_field_specs`，而是遍历模块常量。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round147/00-doctor.json`
  保存本轮 smart-search 诊断；main-search provider timeout，Exa / Context7
  可用，本轮采用 Exa official-domain evidence；
- `/tmp/smart-search-evidence/aiia-optimization-round147/01-exa-python-expression-tuples.json`
  保存 Python expressions 资料：tuple / display / expression evaluation 是运行期
  语义，静态 tuple hoist 可避免每次函数执行重建同一规格对象；
- `/tmp/smart-search-evidence/aiia-optimization-round147/02-exa-prometheus-label-dimensions.json`
  保存 Prometheus / OpenMetrics 资料：metric name + label set 定义 time series，
  因此本轮明确不改 label 维度或 metric family 语义。

验证：

- `uv run pytest tests/test_prom_static_metric_specs_r620.py` → 3 passed；
- `uv run pytest tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_prom_metric_family_iterable_r517.py
  tests/test_prom_family_iterables_r518.py
  tests/test_system_metrics_prometheus_r186.py` → 55 passed, 4 subtests passed；
- `uv run ruff check tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round147/` non-empty evidence scan；
- source invariant scan for removed in-function static spec definitions；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.164 R621 · Prometheus label escaping 无转义字符 fast path

`_escape_prom_label_value()` 是所有 Prometheus label value 的共享 escaping
helper。旧实现对每个 value 都固定执行三轮 `str.replace()`：

```python
out = value
for old, new in _PROM_LABEL_ESCAPES:
    out = out.replace(old, new)
return out
```

但 `/api/system/metrics` 的常见 label value 是 `task_changed`、`heartbeat`、
`success`、`failure`、`bark`、`0.95` 这类 plain token，绝大多数不含
Prometheus 需要 escape 的 `\`、`"`、`\n`。R621 在替换循环前增加 no-escape
guard：

```python
if "\\" not in value and '"' not in value and "\n" not in value:
    return value
```

命中常见路径时直接返回原字符串，避免三次 `replace()` method call 和替换循环；
只有包含任一特殊字符时才进入原来的 ordered replace pipeline。

行为边界：

- plain label value 输出不变；
- 包含反斜杠、双引号、换行时仍按原顺序替换，输出不变；
- `_format_prom_labels()`、histogram bucket label helper、metric family helper 的
  public 输出契约不变；
- 非字符串 label value 仍在 caller 侧 `str(v)` 后进入本 helper，本轮不改变类型
  coercion；
- no-escape guard 是性能 fast path，不吞异常、不改变 Prometheus label key /
  value 维度。

新增测试：

- `tests/test_prom_label_escape_fastpath_r621.py`
  - runtime 覆盖 plain label value 直接得到原文本；
  - runtime 覆盖反斜杠 / 双引号 / 换行仍按 Prometheus 要求 escape；
  - source invariant 锁定 no-escape guard 在 `_PROM_LABEL_ESCAPES` replace loop
    之前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round148/00-doctor.json`
  保存本轮 smart-search 诊断；main-search provider timeout，Exa / Context7
  可用，本轮采用 Exa official-domain evidence；
- `/tmp/smart-search-evidence/aiia-optimization-round148/01-exa-python-str-replace-contains.json`
  保存 Python 字符串资料：`in` / `not in` 是字符串 containment operation，
  `str.replace(old, new)` 返回替换后的 copy；
- `/tmp/smart-search-evidence/aiia-optimization-round148/02-exa-prometheus-label-escaping.json`
  保存 Prometheus / OpenMetrics label escaping 资料：quoted label value 中
  反斜杠、双引号、换行需要 escape。

验证：

- `uv run pytest tests/test_prom_label_escape_fastpath_r621.py` → 3 passed；
- `uv run pytest tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_prom_metric_family_iterable_r517.py
  tests/test_prom_family_iterables_r518.py
  tests/test_system_metrics_prometheus_r186.py` → 58 passed, 4 subtests passed；
- `uv run ruff check tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round148/` non-empty evidence scan；
- source invariant scan for no-escape guard before `_PROM_LABEL_ESCAPES` loop；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.165 R622 · Prometheus single-label formatter fast path

R621 减少了 plain label value 的 escaping 成本；R622 继续收敛 label set
formatter 本身。`_format_prom_labels()` 旧实现对任何非空 labels 都走：

```python
return "{" + ",".join(
    f'{k}="{_escape_prom_label_value(str(v))}"' for k, v in labels.items()
) + "}"
```

但本项目 `/api/system/metrics` 的常见 sample label set 是单 label：

- `{"event_type": ...}`；
- `{"quantile": ...}`；
- `{"provider": ...}`。

这些路径不需要 generator expression，也不需要 `str.join()`。R622 增加单 label
fast path：

```python
if len(labels) == 1:
    k, v = next(iter(labels.items()))
    return f'{{{k}="{_escape_prom_label_value(str(v))}"}}'
```

多 label 仍走原 `join(labels.items())` 分支，保留插入顺序和既有 escaping。

行为边界：

- `None` / `{}` 仍返回 `""`；
- 单 label 输出文本不变，仍调用 `_escape_prom_label_value(str(v))`；
- 多 label 输出顺序不变，仍按 dict 插入顺序拼接；
- 不改变 label key、label value、metric family、HELP/TYPE 输出；
- histogram bucket label 已有 R618 专用 helper，本轮只改通用
  `_format_prom_labels()`。

新增测试：

- `tests/test_prom_labels_singleton_fastpath_r622.py`
  - runtime 覆盖单 label plain value 与需要 escaping 的 value；
  - runtime 覆盖 `None` / `{}` 和 multi-label insertion order；
  - source invariant 锁定 `len(labels) == 1` fast path 在 `",".join(...)`
    之前，并使用 `next(iter(labels.items()))`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round149/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round149/01-exa-python-dict-items-len-order.json`
  保存 Python dict 资料：dict 可用 `len()`，`items()` 迭代 key/value，dict
  保留插入顺序；
- `/tmp/smart-search-evidence/aiia-optimization-round149/02-exa-prometheus-label-notation.json`
  保存 Prometheus data model / notation 资料：label 是 metric name 后
  `{key="value",...}` 形式的 key-value pair。

验证：

- `uv run pytest tests/test_prom_labels_singleton_fastpath_r622.py` → 3 passed；
- `uv run pytest tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_prom_metric_family_iterable_r517.py
  tests/test_prom_family_iterables_r518.py
  tests/test_system_metrics_prometheus_r186.py` → 61 passed, 4 subtests passed；
- `uv run ruff check tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round149/` non-empty evidence scan；
- source invariant scan for singleton fast path before `",".join(...)`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.166 R623 · Prometheus histogram bucket single-base-label fast path

R618 已经把 histogram bucket label 从每桶 dict merge 改为直接拼接
`le` + `base_labels`。但 `_format_prom_histogram_bucket_labels()` 对非空
`base_labels` 仍统一走 `",".join(...)` generator：

```python
return (
    f'{{le="{_escape_prom_label_value(le_label_value)}",'
    + ",".join(
        f'{k}="{_escape_prom_label_value(str(v))}"'
        for k, v in base_labels.items()
    )
    + "}"
)
```

notification histogram 的常见 bucket 是单 base label：`{"provider": "bark"}`。
这类路径每个 bucket 都不需要 generator / join。R623 在保留 `le` override
edge 之后增加 singleton fast path：

```python
if len(base_labels) == 1:
    k, v = next(iter(base_labels.items()))
    return (
        f'{{le="{_escape_prom_label_value(le_label_value)}",'
        f'{k}="{_escape_prom_label_value(str(v))}"}}'
    )
```

行为边界：

- 无 `base_labels` 路径不变：只输出 `{le="..."}`；
- `base_labels` 自带 `le` 时仍先走 R618 legacy override fallback；
- 单 base label 输出不变，仍 escape `le` 和 base label value；
- 多 base label 仍走原 `join(base_labels.items())`，插入顺序不变；
- `_sum` / `_count` 仍走 `_format_prom_labels(base_labels)`，不改变 histogram
  family 结构。

新增测试：

- `tests/test_prom_histogram_bucket_singleton_labels_r623.py`
  - runtime 覆盖单 base label plain value 与需要 escaping 的 value；
  - runtime 覆盖 multi-label 顺序与 `base_labels["le"]` legacy override；
  - source invariant 锁定 `len(base_labels) == 1` fast path 位于 `le` conflict
    fallback 之后、`",".join(...)` 之前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round150/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round150/01-exa-python-dict-items-order.json`
  保存 Python dict 资料：dict 可用 `len()`，`items()` 迭代 key/value，dict
  保留插入顺序；
- `/tmp/smart-search-evidence/aiia-optimization-round150/02-exa-prometheus-histogram-le-label.json`
  保存 Prometheus / OpenMetrics histogram 资料：classic histogram bucket 使用
  `le` label，`+Inf` bucket 是 histogram 约束的一部分。

验证：

- `uv run pytest tests/test_prom_histogram_bucket_singleton_labels_r623.py` → 3 passed；
- `uv run pytest tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_histogram_bucket_labels_r618.py
  tests/test_prom_histogram_inf_fallback_r617.py
  tests/test_prom_histogram_r190.py
  tests/test_prom_family_iterables_r518.py
  tests/test_system_metrics_prometheus_r186.py` → 74 passed；
- `uv run ruff check tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_histogram_bucket_labels_r618.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round150/` non-empty evidence scan；
- source invariant scan for singleton base-label fast path before `",".join(...)`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.167 R624 · Prometheus metric family single-sample fast path

`_format_prom_metric_family()` 在 R517 后支持 one-pass iterable，避免先 staging
sample list。但旧实现只要拿到第一个 sample，就立即创建 `out_lines` list，再
append 第一行，最后 `join()`：

```python
out_lines = [
    f"# HELP {name} {help_text}\n",
    f"# TYPE {name} {metric_type}\n",
]
out_lines.append(f"{name}{first_label_str} {first_value_str}\n")
...
return "".join(out_lines)
```

很多 family 在 scrape 时可能只有一个 sample：单 event_type 的
`aiia_sse_emit_by_type_total`、单 provider 的 notification metrics、单 tool
状态的 MCP counter。R624 在读取第一个 sample 后尝试读取第二个 sample：

- 没有第二个 sample：直接返回 `header + first_line`，避免 list allocation /
  append / join；
- 有第二个 sample：创建 `out_lines = [header, first_line]`，追加第二个和后续
  samples，保持 multi-sample 行为。

行为边界：

- 空 iterable 仍返回 `""`；
- singleton family 的 HELP / TYPE / sample 三行文本不变；
- multi-sample family HELP / TYPE 仍各只出现一次，sample 顺序不变；
- one-pass generator 仍只顺序消费一次；
- label escaping、value formatting、metric name/type/help text 不变。

新增测试：

- `tests/test_prom_metric_family_singleton_fastpath_r624.py`
  - runtime 覆盖 singleton family 输出完全匹配；
  - runtime 覆盖 empty iterable 与 multi-sample family；
  - runtime 覆盖 one-pass generator 只消费一次；
  - source invariant 锁定 `return header + first_line` 在 `out_lines` list 创建之前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round151/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round151/01-exa-python-iterator-next-join.json`
  保存 Python iterator / `next()` / list append / `str.join()` 资料；
- `/tmp/smart-search-evidence/aiia-optimization-round151/02-exa-prometheus-help-type-family.json`
  保存 Prometheus / OpenMetrics exposition 资料：metric family 的 HELP / TYPE
  元数据与 sample 行语义必须保持稳定。

验证：

- `uv run pytest tests/test_prom_metric_family_singleton_fastpath_r624.py` → 4 passed；
- `uv run pytest tests/test_prom_metric_family_singleton_fastpath_r624.py
  tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  tests/test_prom_static_metric_specs_r620.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_metric_family_iterable_r517.py
  tests/test_prom_family_iterables_r518.py
  tests/test_system_metrics_prometheus_r186.py` → 56 passed；
- `uv run ruff check tests/test_prom_metric_family_singleton_fastpath_r624.py
  tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_metric_family_singleton_fastpath_r624.py
  tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round151/` non-empty evidence scan；
- source invariant scan for singleton family direct return before `out_lines` list；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.168 R625 · Prometheus single metric no-label fast path

审计点：`/system/metrics` 里大量单条 metric 没有 labels，例如
`aiia_uptime_seconds`、SSE top-level counters/gauges、task queue gauges、recent
errors 和 notification top-level metrics。旧版 `_format_prom_metric()` 即使
`labels is None` 或 `{}`，也先调用 `_format_prom_labels(labels)` 再拼值行：

```python
label_str = _format_prom_labels(labels)
value_str = _format_prom_value(value)
return (
    f"# HELP {name} {help_text}\n"
    f"# TYPE {name} {metric_type}\n"
    f"{name}{label_str} {value_str}\n"
)
```

R625 把 no-label case 提前到 value formatting 后：

```python
value_str = _format_prom_value(value)
if not labels:
    return (
        f"# HELP {name} {help_text}\n"
        f"# TYPE {name} {metric_type}\n"
        f"{name} {value_str}\n"
    )

label_str = _format_prom_labels(labels)
...
```

收益：

- `None` / `{}` labels 不再进入 `_format_prom_labels()`，省一次 Python 函数调用
  和内部 truthiness 分支；
- unlabeled value 行直接生成 `name value`，避免构造空 label string 后再插值；
- labeled branch 仍只在确实有 labels 时执行，label escaping 行为不变。

行为边界：

- `labels=None` 与 `labels={}` 输出仍是无 label 的 `metric value`；
- 非空 labels 仍走 `_format_prom_labels(labels)`，保持插入顺序与 escaping；
- HELP / TYPE / value formatting 的文本契约不变；
- Prometheus 数据模型允许 time series 只有 metric name，没有 label set；外部依据
  明确 labels 是 optional key-value pairs。

新增测试：

- `tests/test_prom_metric_no_label_fastpath_r625.py`
  - runtime 覆盖 `None` labels 输出完全匹配；
  - runtime 覆盖 empty dict 仍输出 unlabeled metric；
  - runtime 覆盖 labeled metric 与双引号 escaping 不变；
  - source invariant 锁定 `if not labels:` 位于
    `_format_prom_labels(labels)` 之前，并包含直接 `f"{name} {value_str}\n"`
    返回。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round152/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round152/01-exa-python-truth-fstring.json`
  保存 Python truth value testing 与 f-string 语法资料；
- `/tmp/smart-search-evidence/aiia-optimization-round152/02-exa-prometheus-optional-labels.json`
  保存 Prometheus / OpenMetrics 资料：time series 由 metric name 和 optional
  labels 标识，label set 可为空。

验证：

- `uv run pytest tests/test_prom_metric_no_label_fastpath_r625.py`；
- `uv run pytest tests/test_prom_metric_no_label_fastpath_r625.py
  tests/test_prom_metric_family_singleton_fastpath_r624.py
  tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_prom_metric_no_label_fastpath_r625.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_metric_no_label_fastpath_r625.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round152/` non-empty evidence scan；
- source invariant scan for no-label branch before `_format_prom_labels(labels)`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.169 R626 · Prometheus exact-int value formatter fast path

审计点：`_format_prom_value()` 是 Prometheus exporter 的所有 value 行共享
formatter。旧实现对非 float 一律执行：

```python
return str(int(value))
```

这保守地把 `bool` 渲染成 `1` / `0`，但多数 hot-path 输入已经是精确 `int`：
SSE counters/gauges、task queue gauges、recent error count、histogram bucket
count、`_count`、MCP counter 等。对这些值再次调用 `int(value)` 没有语义收益。

R626 增加 exact-int fast path：

```python
if type(value) is int:
    return str(value)
if isinstance(value, float):
    ...
return str(int(value))
```

收益：

- exact `int` 直接 `str(value)`，省掉一次冗余 `int()` 转换；
- `float` 分支仍保持 `NaN` / `+Inf` / `-Inf` / `repr(float)` 语义；
- `bool` 不走 exact-int 分支，仍落到 `str(int(value))`，继续输出 Prometheus
  需要的 `1` / `0`，不会变成 Python 字符串 `"True"` / `"False"`。

行为边界：

- `42` / `-7` 输出仍是十进制整数；
- `True` / `False` 仍输出 `1` / `0`；
- `float("nan")`、`float("inf")`、`float("-inf")` 与普通 float 输出不变；
- helper 的公开输入类型仍是 `int | float`，没有放宽为任意对象。

新增测试：

- `tests/test_prom_value_exact_int_fastpath_r626.py`
  - runtime 覆盖 exact int 输出；
  - runtime 覆盖 bool 仍按 numeric Prometheus contract 输出；
  - runtime 覆盖普通 float 与特殊 float；
  - source invariant 锁定 `type(value) is int` 在 float 分支之前，并保留
    fallback `str(int(value))`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round153/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round153/01-exa-python-int-bool.json`
  保存 Python 文档资料：`bool` 是 `int` 的 subtype，但字符串转换会得到
  `"False"` / `"True"`；
- `/tmp/smart-search-evidence/aiia-optimization-round153/02-exa-prometheus-values.json`
  保存 OpenMetrics / Prometheus 资料：metric values 必须是 floating point 或
  integer；boolean values 必须遵循 `1==true`、`0==false`。

验证：

- `uv run pytest tests/test_prom_value_exact_int_fastpath_r626.py`；
- `uv run pytest tests/test_prom_value_exact_int_fastpath_r626.py
  tests/test_prom_metric_no_label_fastpath_r625.py
  tests/test_prom_metric_family_singleton_fastpath_r624.py
  tests/test_prom_labels_singleton_fastpath_r622.py
  tests/test_prom_label_escape_fastpath_r621.py
  tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_prom_value_exact_int_fastpath_r626.py
  tests/test_prom_metric_no_label_fastpath_r625.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_value_exact_int_fastpath_r626.py
  tests/test_prom_metric_no_label_fastpath_r625.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round153/` non-empty evidence scan；
- source invariant scan for exact-int branch before float branch；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.170 R627 · Prometheus histogram bucket ordered-input fast path

审计点：`_format_prom_histogram_family()` 每个 observation 都需要输出 classic
histogram `_bucket` 行，旧实现无条件：

```python
sorted_keys = sorted(buckets)
has_inf_bucket = bool(sorted_keys) and sorted_keys[-1] == _PROM_INF
if not has_inf_bucket:
    sorted_keys.append(_PROM_INF)
```

这能保证乱序 caller 输入也按 `le` 升序输出，但本项目的 histogram producers
本身按固定 bucket 规格累积并插入，snapshot 中 bucket dict 通常已经是升序
插入顺序。Python dict 迭代保留插入顺序，因此正常 scrape 每个 observation
都付出一次无条件排序并不必要。

R627 抽出 `_prom_histogram_bucket_keys()`：

```python
bucket_keys = list(buckets)
keys_are_sorted = True
...
if previous_key > key:
    keys_are_sorted = False
    break
...
if not keys_are_sorted:
    bucket_keys.sort()

has_inf_bucket = bool(bucket_keys) and bucket_keys[-1] == _PROM_INF
if not has_inf_bucket:
    bucket_keys.append(_PROM_INF)
return bucket_keys, has_inf_bucket
```

收益：

- 已经按升序插入的 bucket dict 只做一次线性顺序检查，不再调用通用排序；
- 乱序 dict 仍会 `bucket_keys.sort()`，保持历史升序输出；
- 缺 `+Inf` 时仍只 append 到 key list，不复制 / 修改 caller 的 `buckets` dict；
- `has_inf_bucket` 仍返回给渲染循环，用于区分读取 caller 的 `+Inf` bucket value
  还是用冗余 `count` fallback。

行为边界：

- 有 `+Inf` 且升序输入：输出顺序不变；
- 有 `+Inf` 但乱序输入：仍输出有限 bucket 升序、`+Inf` 最后；
- 缺 `+Inf`：仍补渲染 `count` 作为 `+Inf` bucket value，且原 dict 不变；
- OpenMetrics 禁止 histogram bucket threshold 为 `NaN`，本 helper 不为非法
  threshold 设计额外排序语义。

新增测试：

- `tests/test_prom_histogram_bucket_order_fastpath_r627.py`
  - runtime 覆盖 ordered keys 直接保持顺序；
  - runtime 覆盖 unordered keys 仍排序且 `+Inf` 最后；
  - runtime 覆盖 missing `+Inf` append 不修改 caller dict；
  - runtime 覆盖 full histogram output 对乱序输入仍升序；
  - source invariant 锁定不再出现 `sorted(buckets)`，并确认只有检测到
    `previous_key > key` 后才走 `bucket_keys.sort()`。
- 更新 `tests/test_prom_histogram_inf_fallback_r617.py` 的 source invariant：
  R617 的不变量从“直接 `sorted(buckets)`”调整为“helper 中 list key +
  conditional sort + append fallback，不复制 / 不修改 buckets”。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round154/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round154/01-exa-python-dict-order-list-sort.json`
  保存 Python 文档资料：`list(d)` 按 dict 插入顺序返回 key；`list.sort()`
  原地排序，`sorted()` 返回新排序列表；
- `/tmp/smart-search-evidence/aiia-optimization-round154/02-exa-prometheus-histogram-buckets-order.json`
  保存 OpenMetrics / Prometheus 资料：classic histogram 需要 bucket，必须有
  `+Inf` threshold，bucket count 是 cumulative，threshold 不能是 `NaN`。

验证：

- `uv run pytest tests/test_prom_histogram_bucket_order_fastpath_r627.py`；
- `uv run pytest tests/test_prom_histogram_bucket_order_fastpath_r627.py
  tests/test_prom_histogram_inf_fallback_r617.py
  tests/test_prom_histogram_bucket_labels_r618.py
  tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_histogram_r190.py
  tests/test_prom_family_iterables_r518.py
  tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_prom_histogram_bucket_order_fastpath_r627.py
  tests/test_prom_histogram_inf_fallback_r617.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_histogram_bucket_order_fastpath_r627.py
  tests/test_prom_histogram_inf_fallback_r617.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round154/` non-empty evidence scan；
- source invariant scan for conditional sort and no `sorted(buckets)`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.171 R628 · Prometheus histogram bucket sortedness scan 去 slice 分配

审计点：R627 已把 histogram bucket 排序从无条件 `sorted(buckets)` 改成
“先检查是否已经升序，乱序才 `bucket_keys.sort()`”。但 sortedness 检查仍有一处
临时分配：

```python
if len(bucket_keys) > 1:
    previous_key = bucket_keys[0]
    for key in bucket_keys[1:]:
        ...
```

`bucket_keys[1:]` 会构造一个新的同类型 slice 序列。对每个 histogram
observation 来说，这会抵消一部分 R627 在 ordered fast path 上省下的分配。

R628 改成 iterator + `next()`：

```python
key_iter = iter(bucket_keys)
try:
    previous_key = next(key_iter)
except StopIteration:
    pass
else:
    for key in key_iter:
        ...
```

收益：

- ordered bucket fast path 不再为了跳过第一个元素创建 `bucket_keys[1:]`；
- empty buckets 通过 `StopIteration` 落回原逻辑，随后 append `_PROM_INF`；
- singleton buckets 不进入比较循环，仍 append `_PROM_INF`；
- multi-bucket ordered / unordered 行为与 R627 保持一致。

行为边界：

- empty dict 仍返回 `([+Inf], False)`，formatter 会用 `count` 渲染 fallback
  `+Inf` bucket；
- single finite bucket 仍追加 `+Inf`；
- ordered finite buckets + `+Inf` 仍保持原顺序；
- unordered buckets 仍检测到 `previous_key > key` 后执行 `bucket_keys.sort()`。

新增测试：

- `tests/test_prom_histogram_bucket_iter_scan_r628.py`
  - runtime 覆盖 empty bucket keys；
  - runtime 覆盖 singleton bucket key；
  - runtime 覆盖 ordered / unordered multi-bucket 行为不变；
  - source invariant 锁定 `key_iter = iter(bucket_keys)`、`next(key_iter)`、
    `for key in key_iter:`，并禁止 `bucket_keys[1:]` 回归。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round155/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round155/01-exa-python-slicing.json`
  保存 Python sequence slicing 资料：slice 表达式产生同类型序列；
- `/tmp/smart-search-evidence/aiia-optimization-round155/02-exa-python-iter-next.json`
  保存 Python `iter()` / `next()` / iterator 资料：迭代器按需返回下一个元素，
  可用 `StopIteration` 表示耗尽。

验证：

- `uv run pytest tests/test_prom_histogram_bucket_iter_scan_r628.py`；
- `uv run pytest tests/test_prom_histogram_bucket_iter_scan_r628.py
  tests/test_prom_histogram_bucket_order_fastpath_r627.py
  tests/test_prom_histogram_inf_fallback_r617.py
  tests/test_prom_histogram_bucket_labels_r618.py
  tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_histogram_r190.py
  tests/test_prom_family_iterables_r518.py
  tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_prom_histogram_bucket_iter_scan_r628.py
  tests/test_prom_histogram_bucket_order_fastpath_r627.py
  tests/test_prom_histogram_inf_fallback_r617.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_histogram_bucket_iter_scan_r628.py
  tests/test_prom_histogram_bucket_order_fastpath_r627.py
  tests/test_prom_histogram_inf_fallback_r617.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round155/` non-empty evidence scan；
- source invariant scan for iterator traversal and no `bucket_keys[1:]`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.172 R629 · SSE event type accessor 缓存已排序 tuple

审计点：`sse_event_schemas.get_known_event_types()` 每次调用都会执行
`tuple(sorted(EVENT_SCHEMAS))`。`EVENT_SCHEMAS` 是模块级静态 registry，
常规路径不会在 import 后 mutate；对 public accessor 来说，重复排序和分配
只是为了得到同一个已知事件类型集合。

R629 在模块初始化时构造一次：

```python
_KNOWN_EVENT_TYPES: tuple[str, ...] = tuple(sorted(EVENT_SCHEMAS))
```

`get_known_event_types()` 直接返回该 tuple。

收益：

- 重复调用不再构造 `sorted()` 的临时 list；
- 不再为同一组 event type 重复构造 tuple；
- 返回值仍是 immutable tuple，可安全共享给调用方读取。

行为边界：

- 返回值仍等于 `tuple(sorted(EVENT_SCHEMAS))`；
- tuple 顺序仍按字母排序；
- `EVENT_SCHEMAS` 本身不变，直接使用 registry 的调用方行为不变；
- 如果未来要支持 import 后动态注册 event schema，需要同步更新
  `_KNOWN_EVENT_TYPES` 或改回动态 accessor。本轮不引入动态注册语义。

新增测试：

- `tests/test_sse_event_types_cached_tuple_r629.py`
  - runtime 覆盖 accessor 返回 sorted tuple；
  - runtime 覆盖重复调用返回同一个 tuple 对象；
  - source invariant 锁定 `_KNOWN_EVENT_TYPES = tuple(sorted(EVENT_SCHEMAS))`；
  - source invariant 锁定 accessor 返回 `_KNOWN_EVENT_TYPES`，并禁止在
    accessor 内部重新 `sorted(EVENT_SCHEMAS)`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round156/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round156/01-exa-python-sorted-tuple.json`
  保存 Python `sorted()` 资料：`sorted()` 返回新的 sorted list；
- `/tmp/smart-search-evidence/aiia-optimization-round156/02-exa-python-module-init.json`
  保存 Python 模块 import / 初始化资料：module 初始化后其全局对象可被
  accessor 重用。

验证：

- `uv run pytest tests/test_sse_event_types_cached_tuple_r629.py`；
- `uv run pytest tests/test_sse_event_types_cached_tuple_r629.py
  tests/test_sse_event_schemas_r198.py
  tests/test_feat_sse_cross_language_schema_r297.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_sse_emit_by_type_cardinality_cap_r203.py`；
- `uv run ruff check tests/test_sse_event_types_cached_tuple_r629.py
  src/ai_intervention_agent/sse_event_schemas.py`；
- `uv run ty check tests/test_sse_event_types_cached_tuple_r629.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round156/` non-empty evidence scan；
- source invariant scan for cached tuple and accessor without `sorted(EVENT_SCHEMAS)`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.173 R630 · SSE latency empty snapshot 跳过 list materialization

审计点：`_SSEBus._compute_latency_snapshot()` 用于 `/api/system/sse-stats`
和 system metrics 中的 SSE latency 观测。旧实现无论是否有样本，都会先做：

```python
samples = list(self._latency_samples_ns)
count = len(samples)
if count == 0:
    return {"p50_ms": None, "p95_ms": None, "count": 0}
```

在刚启动、无 SSE client、无 task event、或没有已交付样本的常见状态下，这会为
empty deque 构造一个马上丢弃的空 list。R630 改为先读 deque 长度：

```python
count = len(self._latency_samples_ns)
if count == 0:
    return {"p50_ms": None, "p95_ms": None, "count": 0}
samples = list(self._latency_samples_ns)
```

收益：

- empty latency snapshot 不再构造空 list；
- empty path 不再迭代 `_latency_samples_ns`；
- non-empty path 仍复制为 list 后排序，保留原 percentile 计算和并发快照边界。

行为边界：

- `count == 0` 仍返回 `p50_ms=None`、`p95_ms=None`、`count=0`；
- `count > 0` 仍对当前样本做 list snapshot，然后 `samples.sort()`；
- `record_emit_to_deliver_latency_ns()` 的负数丢弃、bounded deque evict、锁语义
  均不变；
- `_compute_latency_snapshot()` 仍只应在持有 `self._lock` 时调用。

新增测试：

- `tests/test_sse_latency_empty_snapshot_fastpath_r630.py`
  - runtime 用 `__iter__` 抛错的 empty sample 容器证明 empty path 只读 `len()`；
  - runtime 覆盖 non-empty 两样本 percentile 行为不变；
  - source invariant 锁定 `len(self._latency_samples_ns)` 在 empty return 前、
    `list(self._latency_samples_ns)` 在 empty return 后，并禁止回归到
    `count = len(samples)`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round157/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round157/01-exa-python-len-list.json`
  保存 Python list / iterable 资料：list 构造会从 iterable 产生新 list，
  `len()` 是容器长度查询；
- `/tmp/smart-search-evidence/aiia-optimization-round157/02-exa-python-deque.json`
  保存 Python `collections.deque` 资料：deque 是 list-like 容器，支持
  `len(d)`，append/pop 两端高效且 bounded deque 会自动丢弃旧元素。

验证：

- `uv run pytest tests/test_sse_latency_empty_snapshot_fastpath_r630.py`；
- `uv run pytest tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  tests/test_sse_emit_to_deliver_latency_r134.py
  tests/test_feat_sse_bus_perf_baseline_r304.py
  tests/test_system_metrics_prometheus_r186.py
  tests/test_prom_static_metric_specs_r620.py`；
- `uv run ruff check tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_latency_empty_snapshot_fastpath_r630.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round157/` non-empty evidence scan；
- source invariant scan for empty fast path before list snapshot；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.174 R631 · SSE latency singleton snapshot 跳过 list + sort

审计点：R630 已让 empty latency snapshot 在构造 list 之前返回；但
`count == 1` 仍会进入：

```python
samples = list(self._latency_samples_ns)
samples.sort()
p50_idx = min(count - 1, int(count * 0.50))
p95_idx = min(count - 1, int(count * 0.95))
```

单样本分布下，P50 和 P95 必然都是同一个样本。继续复制 deque、排序单元素 list、
再做两次索引计算没有语义收益。R631 在 `count == 1` 时直接读取左端样本：

```python
if count == 1:
    sample_ms = round(self._latency_samples_ns[0] / 1_000_000.0, 2)
    return {"p50_ms": sample_ms, "p95_ms": sample_ms, "count": 1}
```

收益：

- singleton latency snapshot 不再构造 list；
- singleton path 不再调用 `samples.sort()`；
- single sample 的 round 只执行一次，结果复用给 p50 / p95；
- multi-sample path 仍走 list snapshot + sort，保持 percentile 语义。

行为边界：

- `count == 0` 仍由 R630 empty fast path 返回全 `None`；
- `count == 1` 仍返回同一个 rounded ms value 给 `p50_ms` / `p95_ms`；
- `count >= 2` 仍复制当前样本、排序并按 nearest-rank index 取 P50/P95；
- deque 下标 `0` 是端点访问；本 helper 仍只应在持有 `self._lock` 时调用。

新增测试：

- `tests/test_sse_latency_singleton_snapshot_fastpath_r631.py`
  - runtime 用 `__iter__` 抛错的 singleton sample 容器证明 singleton path
    不迭代 / 不 list materialize；
  - runtime 覆盖三样本乱序输入仍排序并输出原 percentile；
  - source invariant 锁定 `if count == 1`、`self._latency_samples_ns[0]`、
    singleton return 均在 `samples = list(...)` 之前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round158/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round158/01-exa-python-deque-index-len.json`
  保存 Python `collections.deque` 资料：deque 支持 `len(d)` 和下标访问，端点
  indexed access 是 O(1)；
- `/tmp/smart-search-evidence/aiia-optimization-round158/02-exa-python-list-sort.json`
  保存 Python sorting 资料：`list.sort()` 原地排序，`sorted()` 会从 iterable
  构造新 sorted list；单样本 path 避免进入排序路径。

验证：

- `uv run pytest tests/test_sse_latency_singleton_snapshot_fastpath_r631.py`；
- `uv run pytest tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  tests/test_sse_emit_to_deliver_latency_r134.py
  tests/test_feat_sse_bus_perf_baseline_r304.py
  tests/test_system_metrics_prometheus_r186.py
  tests/test_prom_static_metric_specs_r620.py`；
- `uv run ruff check tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_latency_singleton_snapshot_fastpath_r631.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round158/` non-empty evidence scan；
- source invariant scan for singleton fast path before list snapshot；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.175 R632 · SSE latency two-sample snapshot 跳过 list + sort

审计点：R631 已让 singleton latency snapshot 直接返回；但 `count == 2` 仍会
复制 deque、排序，并计算：

```python
p50_idx = min(1, int(2 * 0.50))  # 1
p95_idx = min(1, int(2 * 0.95))  # 1
```

因此两样本分布下，当前 nearest-rank 语义的 P50 和 P95 都是排序后的第 2 个值，
也就是两个样本中的较大值。R632 增加 two-sample fast path：

```python
if count == 2:
    first_sample = self._latency_samples_ns[0]
    second_sample = self._latency_samples_ns[1]
    p_sample = first_sample if first_sample >= second_sample else second_sample
    sample_ms = round(p_sample / 1_000_000.0, 2)
    return {"p50_ms": sample_ms, "p95_ms": sample_ms, "count": 2}
```

收益：

- two-sample latency snapshot 不再构造 list；
- two-sample path 不再调用 `samples.sort()`；
- 两个 quantile 的 index 计算和两次 list lookup 收敛为一次比较 + 一次 round；
- `count >= 3` 仍走原 list snapshot + sort，保持一般 percentile 行为。

行为边界：

- `count == 0` / `count == 1` 仍走 R630 / R631 fast path；
- `count == 2` 的输出仍等价于 `sorted(samples)[1]` 同时作为 p50 / p95；
- `count >= 3` 的 P50/P95 仍按 nearest-rank index 计算；
- 本 helper 仍只应在持有 `self._lock` 时调用，避免并发 append 期间读到不一致
  的长度和元素。

新增测试：

- `tests/test_sse_latency_pair_snapshot_fastpath_r632.py`
  - runtime 用 `__iter__` 抛错的 two-sample 容器证明 two-sample path 不迭代 /
    不 list materialize；
  - runtime 覆盖 reversed 两样本输入仍返回较大值，匹配排序行为；
  - runtime 覆盖三样本乱序输入仍排序并输出原 percentile；
  - source invariant 锁定 `if count == 2`、两个 direct index、comparison、
    two-sample return 均在 `samples = list(...)` 之前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round159/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round159/01-exa-python-deque-index.json`
  保存 Python `collections.deque` 资料：deque 支持 `len(d)` 和端点下标访问，
  端点 indexed access 是 O(1)；
- `/tmp/smart-search-evidence/aiia-optimization-round159/02-exa-python-comparisons.json`
  保存 Python comparison / conditional expression 资料：数值可用 `>=` 比较，
  `x if C else y` 根据条件只返回一支；
- `/tmp/smart-search-evidence/aiia-optimization-round159/03-exa-python-list-sort.json`
  保存 Python sorting 资料：`list.sort()` 原地排序，`sorted()` 会从 iterable
  构造新 sorted list；two-sample path 避免进入排序路径。

验证：

- `uv run pytest tests/test_sse_latency_pair_snapshot_fastpath_r632.py`；
- `uv run pytest tests/test_sse_latency_pair_snapshot_fastpath_r632.py
  tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  tests/test_sse_emit_to_deliver_latency_r134.py
  tests/test_feat_sse_bus_perf_baseline_r304.py
  tests/test_system_metrics_prometheus_r186.py
  tests/test_prom_static_metric_specs_r620.py`；
- `uv run ruff check tests/test_sse_latency_pair_snapshot_fastpath_r632.py
  tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_latency_pair_snapshot_fastpath_r632.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round159/` non-empty evidence scan；
- source invariant scan for two-sample fast path before list snapshot；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.176 R633 · SSE latency three-sample snapshot 跳过 list + sort

审计点：R632 后，`count == 3` 成为最小仍会进入 `list(...)` + `sort()` 的
latency snapshot。当前 nearest-rank 语义下：

```python
p50_idx = min(2, int(3 * 0.50))  # 1
p95_idx = min(2, int(3 * 0.95))  # 2
```

因此三样本分布的 P50 是排序后的中间值，P95 是最大值。R633 增加
three-sample fast path：直接读取 `self._latency_samples_ns[0..2]`，用常数次
比较算出中位数和最大值，再各自 round 一次。

收益：

- three-sample latency snapshot 不再构造 list；
- three-sample path 不再调用 `samples.sort()`；
- 保留 `count >= 5` 的通用 list snapshot + sort 路径，避免把小样本比较网络扩展
  到可读性和收益都不划算的规模。

行为边界：

- `count == 0` / `count == 1` / `count == 2` 仍走 R630 / R631 / R632 fast path；
- `count == 3` 的输出仍等价于 `sorted(samples)[1]` 和 `sorted(samples)[2]`；
- 重复值、正序、逆序输入均保持排序后 percentile 语义；
- 本 helper 仍只应在持有 `self._lock` 时调用，避免并发 append 期间读到不一致
  的长度和元素。

新增测试：

- `tests/test_sse_latency_triple_snapshot_fastpath_r633.py`
  - runtime 用 `__iter__` 抛错的 three-sample 容器证明 three-sample path 不迭代 /
    不 list materialize；
  - parameterized runtime 覆盖正序、逆序、重复中位数、重复最大值；
  - runtime 覆盖五样本乱序输入仍排序并输出原 percentile；
  - source invariant 锁定 `if count == 3`、三个 direct index、comparison network、
    three-sample return 均在 `samples = list(...)` 之前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round160/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round160/01-exa-python-deque-index.json`
  保存 Python `collections.deque` 资料：deque 支持 `len(d)` 和端点下标访问，
  端点 indexed access 是 O(1)；
- `/tmp/smart-search-evidence/aiia-optimization-round160/02-exa-python-list-sort.json`
  保存 Python sorting 资料：`list.sort()` 原地排序，`sorted()` 会从 iterable
  构造新 sorted list；three-sample path 避免进入排序路径；
- `/tmp/smart-search-evidence/aiia-optimization-round160/03-exa-python-comparisons.json`
  保存 Python comparison / conditional expression 资料：数值可用 ordered
  comparison；条件分支只返回对应路径。

验证：

- `uv run pytest tests/test_sse_latency_triple_snapshot_fastpath_r633.py`；
- `uv run pytest tests/test_sse_latency_triple_snapshot_fastpath_r633.py
  tests/test_sse_latency_pair_snapshot_fastpath_r632.py
  tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  tests/test_sse_emit_to_deliver_latency_r134.py
  tests/test_feat_sse_bus_perf_baseline_r304.py
  tests/test_system_metrics_prometheus_r186.py
  tests/test_prom_static_metric_specs_r620.py`；
- `uv run ruff check tests/test_sse_latency_triple_snapshot_fastpath_r633.py
  tests/test_sse_latency_pair_snapshot_fastpath_r632.py
  tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_latency_triple_snapshot_fastpath_r633.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round160/` non-empty evidence scan；
- source invariant scan for three-sample fast path before list snapshot；
- local `timeit` smoke：旧三样本 sort path `0.247670s / 500k`，新 three-sample
  path `0.163365s / 500k`，约 `1.52x`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.177 R634 · SSE latency four-sample snapshot 跳过 list + sort

审计点：R633 后，`count == 4` 仍会进入 `list(...)` + `sort()`。当前
nearest-rank 语义下：

```python
p50_idx = min(3, int(4 * 0.50))  # 2
p95_idx = min(3, int(4 * 0.95))  # 3
```

因此四样本分布的 P50 是排序后的第 3 个值（second-largest），P95 是最大值。
R634 增加 four-sample fast path：把四个样本分成两对，各自得到 high/low；
最大值是两个 high 的较大值，second-largest 则是“败方 high”和“胜方 low”的较大值。

收益：

- four-sample latency snapshot 不再构造 list；
- four-sample path 不再调用 `samples.sort()`；
- 只为 `count <= 4` 保留小样本比较网络，`count >= 5` 继续走通用排序路径，避免
  为低频大样本分支堆叠复杂手写排序。

行为边界：

- `count == 0..3` 仍走 R630-R633 fast path；
- `count == 4` 的输出仍等价于 `sorted(samples)[2]` 和 `sorted(samples)[3]`；
- 正序、逆序、交错 pair、重复最大值、重复中位数输入均保持排序后 percentile
  语义；
- 本 helper 仍只应在持有 `self._lock` 时调用，避免并发 append 期间读到不一致
  的长度和元素。

新增测试：

- `tests/test_sse_latency_quad_snapshot_fastpath_r634.py`
  - runtime 用 `__iter__` 抛错的 four-sample 容器证明 four-sample path 不迭代 /
    不 list materialize；
  - parameterized runtime 覆盖正序、逆序、交错 pair、重复最大值、重复中位数；
  - runtime 覆盖五样本乱序输入仍排序并输出原 percentile；
  - source invariant 锁定 `if count == 4`、四个 direct index、pair tournament、
    four-sample return 均在 `samples = list(...)` 之前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round161/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round161/01-exa-python-deque-index.json`
  保存 Python `collections.deque` 资料：deque 支持 `len(d)` 和端点下标访问，
  端点 indexed access 是 O(1)；
- `/tmp/smart-search-evidence/aiia-optimization-round161/02-exa-python-list-sort.json`
  保存 Python sorting 资料：`list.sort()` 原地排序，`sorted()` 会从 iterable
  构造新 sorted list；four-sample path 避免进入排序路径；
- `/tmp/smart-search-evidence/aiia-optimization-round161/03-exa-python-comparisons.json`
  保存 Python ordered comparison 资料：数值可用 `<` / `>` / `>=` / `<=`
  比较，comparison 表达式返回布尔值。

验证：

- `uv run pytest tests/test_sse_latency_quad_snapshot_fastpath_r634.py`；
- `uv run pytest tests/test_sse_latency_quad_snapshot_fastpath_r634.py
  tests/test_sse_latency_triple_snapshot_fastpath_r633.py
  tests/test_sse_latency_pair_snapshot_fastpath_r632.py
  tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  tests/test_sse_emit_to_deliver_latency_r134.py
  tests/test_feat_sse_bus_perf_baseline_r304.py
  tests/test_system_metrics_prometheus_r186.py
  tests/test_prom_static_metric_specs_r620.py`；
- `uv run ruff check tests/test_sse_latency_quad_snapshot_fastpath_r634.py
  tests/test_sse_latency_triple_snapshot_fastpath_r633.py
  tests/test_sse_latency_pair_snapshot_fastpath_r632.py
  tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_latency_quad_snapshot_fastpath_r634.py
  tests/test_sse_latency_triple_snapshot_fastpath_r633.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round161/` non-empty evidence scan；
- source invariant scan for four-sample fast path before list snapshot；
- local `timeit` smoke：旧四样本 sort path `0.253061s / 500k`，新 four-sample
  path `0.173154s / 500k`，约 `1.46x`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.178 R635 · SSE latency snapshot 缓存样本 deque 属性

审计点：R630-R634 已为 `count == 0..4` 增加小样本 fast path，但实现里仍在
同一次 `_compute_latency_snapshot()` 内反复解析 `self._latency_samples_ns`：
`len(...)`、direct index、以及通用 `list(...)` snapshot 都各自触发一次属性读取。
这不是大开销，但该 helper 位于 SSE stats / metrics 热路径，且属性对象在函数内
语义上是同一个 deque。

R635 把样本 deque 绑定到局部变量：

```python
samples_ns = self._latency_samples_ns
count = len(samples_ns)
```

后续 empty / singleton / two-/three-/four-sample fast path 和 `count >= 5`
通用排序路径都复用 `samples_ns`。行为不变：仍要求调用方持有 `self._lock`，因此
局部绑定不会放宽或改变并发语义。

收益：

- 每次 `_compute_latency_snapshot()` 只读取一次 `_latency_samples_ns` 属性；
- 小样本 direct-index 分支不再重复走 `self.` 属性解析；
- `samples = list(samples_ns)` 明确表达“前面是同一个 samples deque 的快路径，
  这里开始做通用快照”。

行为边界：

- `count == 0..4` 的 fast path 输出不变；
- `count >= 5` 仍复制当前 deque 并排序，保持 nearest-rank percentile 语义；
- snapshot 期间没有新增锁策略，也不把 deque 引用泄露到函数外；
- 测试仍覆盖小样本不迭代、大样本走 list snapshot、以及源码中属性只绑定一次。

新增测试：

- `tests/test_sse_latency_local_samples_r635.py`
  - runtime 用 `__getattribute__` 计数，证明四样本 fast path 一次 snapshot 只读取
    `_latency_samples_ns` 一次；
  - runtime 覆盖五样本通用排序路径同样只读取属性一次；
  - source invariant 锁定 `samples_ns = self._latency_samples_ns` 位于
    `count = len(samples_ns)` 和 `samples = list(samples_ns)` 之前，且函数源码中
    `self._latency_samples_ns` 只出现一次。
- 同步更新 R630-R634 的 source invariant，使其绑定 `samples_ns[...]` 和
  `samples = list(samples_ns)`，避免测试继续要求重复属性访问。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round162/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round162/01-exa-python-attribute-reference.json`
  保存 Python data model / attribute reference 资料：对象属性访问是独立表达式；
- `/tmp/smart-search-evidence/aiia-optimization-round162/02-exa-python-local-names.json`
  保存 Python execution model / name binding 资料：局部名称绑定可在当前代码块中
  复用同一个对象引用；
- `/tmp/smart-search-evidence/aiia-optimization-round162/03-exa-python-deque-index.json`
  保存 Python `collections.deque` 资料：deque 支持 `len(d)` 和端点下标访问。

验证：

- `uv run pytest tests/test_sse_latency_local_samples_r635.py`；
- `uv run pytest tests/test_sse_latency_local_samples_r635.py
  tests/test_sse_latency_quad_snapshot_fastpath_r634.py
  tests/test_sse_latency_triple_snapshot_fastpath_r633.py
  tests/test_sse_latency_pair_snapshot_fastpath_r632.py
  tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  tests/test_sse_emit_to_deliver_latency_r134.py
  tests/test_feat_sse_bus_perf_baseline_r304.py
  tests/test_system_metrics_prometheus_r186.py
  tests/test_prom_static_metric_specs_r620.py`；
- `uv run ruff check tests/test_sse_latency_local_samples_r635.py
  tests/test_sse_latency_quad_snapshot_fastpath_r634.py
  tests/test_sse_latency_triple_snapshot_fastpath_r633.py
  tests/test_sse_latency_pair_snapshot_fastpath_r632.py
  tests/test_sse_latency_singleton_snapshot_fastpath_r631.py
  tests/test_sse_latency_empty_snapshot_fastpath_r630.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_latency_local_samples_r635.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round162/` non-empty evidence scan；
- source invariant scan for local samples binding；
- local `timeit` smoke：旧重复属性路径 `0.270611s / 500k`，新 local samples
  path `0.263389s / 500k`，约 `1.03x`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.179 R636 · SSE stats 空 emit_by_type 跳过 Counter copy

审计点：`_SSEBus.stats_snapshot()` 每次都会把 `_emit_by_type` 暴露成普通
`dict`，以保证调用方修改快照不会污染内部 Counter。旧路径固定执行：

```python
"emit_by_type": dict(self._emit_by_type)
```

空 Counter 是启动后、低流量实例、或测试中最常见的 baseline；此时 `dict(...)`
仍要进入通用构造路径。R636 在锁内先判断 truth value：

```python
emit_by_type = dict(self._emit_by_type) if self._emit_by_type else {}
```

空路径直接返回新的 `{}`；非空路径仍 `dict(counter)` defensive copy。

收益：

- 空 `emit_by_type` snapshot 不再进入 Counter 迭代 / dict copy 路径；
- 每次空快照仍返回新的 dict，外部修改不影响后续 snapshot；
- 非空 Counter 的公开契约不变，仍是普通 dict 浅拷贝。

行为边界：

- `stats_snapshot()["emit_by_type"]` 类型仍为 dict；
- 空 Counter 返回 `{}`，但不是共享全局对象；
- 非空 Counter 仍复制，调用方修改 returned dict 不影响内部 `_emit_by_type`；
- 该逻辑仍在 `self._lock` 内完成，和其它计数器字段同一快照边界。

新增测试：

- `tests/test_sse_stats_empty_emit_by_type_fastpath_r636.py`
  - runtime 用 `__iter__` / `items` / `keys` 抛错的 empty object 证明空路径不迭代；
  - runtime 覆盖空快照返回 fresh dict，外部修改不污染下一次 snapshot；
  - runtime 覆盖非空 `emit_by_type` 仍是 defensive copy；
  - source invariant 锁定 conditional copy 在 return payload 前，且 return payload
    不再内联 `dict(self._emit_by_type)`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round163/00-doctor.json`
  保存本轮 smart-search 诊断，openai-compatible 首次出现临时 network error；
- `/tmp/smart-search-evidence/aiia-optimization-round163/00b-openai-compatible-diagnose.md`
  保存后续 `diagnose openai-compatible`，真实 `stream=false` / `stream=true`
  search 形态均恢复 OK；
- `/tmp/smart-search-evidence/aiia-optimization-round163/01-exa-python-truth-value.json`
  保存 Python truth-value testing 资料：空 collections 被视为 false；
- `/tmp/smart-search-evidence/aiia-optimization-round163/02-exa-python-dict-constructor.json`
  保存 Python dict constructor / mapping 资料；
- `/tmp/smart-search-evidence/aiia-optimization-round163/03-exa-python-counter.json`
  保存 Python `collections.Counter` 资料：Counter 是 dict subclass，用于计数。

验证：

- `uv run pytest tests/test_sse_stats_empty_emit_by_type_fastpath_r636.py`；
- `uv run pytest tests/test_sse_stats_empty_emit_by_type_fastpath_r636.py
  tests/test_sse_emit_by_type_r61.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_sse_emit_by_type_cardinality_cap_r203.py
  tests/test_sse_emit_to_deliver_latency_r134.py
  tests/test_system_metrics_prometheus_r186.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_static_metric_specs_r620.py`；
- `uv run ruff check tests/test_sse_stats_empty_emit_by_type_fastpath_r636.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_stats_empty_emit_by_type_fastpath_r636.py`；
- `/tmp/smart-search-evidence/aiia-optimization-round163/` non-empty evidence scan；
- source invariant scan for empty emit_by_type conditional copy；
- local `timeit` smoke：旧空 Counter copy `0.045450s / 1m`，新 empty fast path
  `0.018617s / 1m`，约 `2.44x`；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.180 R637 · SSE emit_by_type 锁内本地绑定

审计点：`_SSEBus.emit()` 的每条事件都会在同一个 `self._lock` 临界区内更新
`_emit_total` 与 `_emit_by_type`，以维持 Prometheus by-type counter 的
`sum(by_type) == emit_total` 不变量。旧路径在 common branch 中重复读取
`self._emit_by_type`：

```python
if event_type not in self._emit_by_type and ...:
    ...
else:
    self._emit_by_type[event_type] += 1
```

R637 在锁内先绑定一次：

```python
emit_by_type = self._emit_by_type
```

之后 membership / `len(...)` / `+= 1` 全部复用本地引用。这样保留同一个
Counter 对象和同一个锁边界，同时减少 hot path 的重复 attribute lookup。

收益：

- common known-event 分支每次 emit 只读取一次 `_emit_by_type` 属性；
- overflow 分支同样只读取一次 `_emit_by_type` 属性，`__other__` 累加语义不变；
- R202/R203 的原子性不变量仍由 AST guard 锁定在 `with self._lock` 内。

行为边界：

- `_emit_total` 与 by-type counter 仍在同一锁内更新；
- `event_type` 已存在时仍累加原桶；
- cardinality cap 命中后新 type 仍落到 `__other__`；
- WARN-once 标志、history append、无订阅者 fast path、fan-out snapshot 均不变。

新增/更新测试：

- `tests/test_sse_emit_by_type_local_counter_r637.py`
  - runtime 用 instrumented `_SSEBus` 证明 known event emit 期间 `_emit_by_type`
    只读取一次；
  - runtime 覆盖 overflow event emit 期间 `_emit_by_type` 同样只读取一次；
  - source invariant 锁定 `emit_by_type = self._emit_by_type` 位于
    `with self._lock` 内，且两个 counter 增量都走本地 `emit_by_type[...]`。
- 同步更新 R202/R203 AST guard，使其接受本地绑定写法，同时继续要求 counter
  增量和 cap-check 位于同一个 `self._lock` 临界区。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round164/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round164/01-exa-python-attribute-local.json`
  保存 Python execution model / name binding 资料，以及本地名 `LOAD_FAST` 与
  qualified attribute lookup 的性能背景；
- `/tmp/smart-search-evidence/aiia-optimization-round164/02-exa-python-counter-mapping.json`
  保存 Python `collections.Counter` 资料：Counter 是 dict subclass，支持
  `c[key] += 1` 的计数模式。

验证：

- `uv run pytest tests/test_sse_emit_by_type_local_counter_r637.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_sse_emit_by_type_cardinality_cap_r203.py`；
- `uv run pytest tests/test_sse_emit_by_type_local_counter_r637.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_sse_emit_by_type_cardinality_cap_r203.py
  tests/test_sse_emit_by_type_r61.py tests/test_sse_empty_payload_fastpath_r507.py
  tests/test_sse_oversize_ascii_fastpath_r502.py
  tests/test_sse_oversize_utf8_fastpath_r501.py
  tests/test_sse_oversize_drop_fastpath_r523.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_prom_static_metric_specs_r620.py
  tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_sse_emit_by_type_local_counter_r637.py
  tests/test_sse_emit_by_type_counter_r202.py
  tests/test_sse_emit_by_type_cardinality_cap_r203.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_emit_by_type_local_counter_r637.py`；
- local `timeit` smoke：旧 common counter branch `0.092207s / 1m`，新本地绑定
  `0.091399s / 1m`，best 约 `1.009x`；median `0.093726s → 0.091698s`，
  约 `1.022x`；
- `/tmp/smart-search-evidence/aiia-optimization-round164/` non-empty evidence scan；
- source invariant scan for local counter binding；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.181 R638 · SSE subscribe tail replay 反向扫描

审计点：`_SSEBus.subscribe(after_id=...)` 在 Last-Event-ID resume 时会从 history
补发 `id > after_id` 的 payload。旧路径对“after_id 落在 history 内”的正常分支
使用 full scan list comprehension：

```python
replay_items = [payload for evt_id, payload in self._history if evt_id > after_id]
```

但 `_history` 的 event id 单调递增，常见重连只落后最后 1-3 条事件。R638 改为从
右侧反向扫描：

```python
for evt_id, payload in reversed(self._history):
    if evt_id <= after_id:
        break
    replay_items.append(payload)
replay_items.reverse()
```

这样只扫描需要补发的尾部再多看一条边界事件，最后 `reverse()` 恢复 wire order。

收益：

- after_id 接近 latest_id 时，扫描量从整个 history 窗口降为 `missed + 1`；
- replay 输出顺序仍是递增 id；
- evicted gap_warning 分支仍复制当前 history 前缀，保持已有 best-effort 行为；
- snapshot history → add subscriber 的同锁原子边界不变。

行为边界：

- `after_id is None` 仍不回放；
- `after_id == latest_id` / `after_id > latest_id` 仍不回放；
- `after_id < oldest_id - 1` 仍先注入 `gap_warning`，再 best-effort 补当前
  history；
- `after_id == oldest_id - 1` 会反向扫描完整 history 并恢复原顺序，输出与旧路径一致；
- queue maxsize 截断语义不变，仍由后续 `put_nowait` loop 防御。

新增测试：

- `tests/test_sse_subscribe_tail_replay_r638.py`
  - runtime 用 `_HistoryProbe` 证明 normal tail replay 不走左侧 `__iter__`，
    只反向读取 `[latest, ..., after_id]` 三步即可补发最后两条；
  - runtime 验证补发顺序仍为 `[127, 128]`；
  - source invariant 锁定 `reversed(self._history)` + `replay_items.reverse()`，
    并防止旧的 filtered full-scan list comprehension 回归。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round165/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round165/01-exa-python-deque-reversed.json`
  保存 Python deque / CPython deque 资料：deque 以双端结构支持从右侧访问和反向迭代；
- `/tmp/smart-search-evidence/aiia-optimization-round165/02-exa-python-list-reverse.json`
  保存 Python list 资料：`list.reverse()` 原地反转列表元素，用于恢复 replay wire order。

验证：

- `uv run pytest tests/test_sse_subscribe_tail_replay_r638.py
  tests/test_sse_last_event_id_r41.py tests/test_sse_gap_warning_fastpath_r515.py
  tests/test_cross_process_perf_r20_14c.py`；
- `uv run pytest tests/test_sse_subscribe_tail_replay_r638.py
  tests/test_sse_last_event_id_r41.py tests/test_sse_gap_warning_fastpath_r515.py
  tests/test_cross_process_perf_r20_14c.py tests/test_sse_empty_payload_fastpath_r507.py
  tests/test_sse_emit_by_type_local_counter_r637.py
  tests/test_sse_stats_empty_emit_by_type_fastpath_r636.py
  tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_sse_subscribe_tail_replay_r638.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_subscribe_tail_replay_r638.py`；
- local `timeit` smoke：128 条 history、`after_id=126`、补发 2 条时，旧 full scan
  `1.161017s / 1m`，新 tail scan `0.098805s / 1m`，best 约 `11.751x`；
  median `1.164345s → 0.099373s`，约 `11.717x`；
- `/tmp/smart-search-evidence/aiia-optimization-round165/` non-empty evidence scan；
- source invariant scan for reversed tail replay；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.182 R639 · SSE gap_warning replay 按 queue 可见容量截断

审计点：`_SSEBus.subscribe(after_id=...)` 的 evicted 分支会先向新 queue 塞一条
`gap_warning`，再 best-effort 补当前 history。由于 `_QUEUE_MAXSIZE = 64`，
`gap_warning` 占用 1 个 slot 后，最多只有 63 条 replay payload 能被
`put_nowait()` 接受。旧路径仍先复制完整 history：

```python
replay_items = [payload for _, payload in self._history]
```

随后锁外 `put_nowait` loop 在 queue full 后 break。R639 把复制阶段改成显式
queue-visible budget：

```python
replay_budget = self._QUEUE_MAXSIZE - 1
if replay_budget > 0:
    for replay_count, (_, payload) in enumerate(self._history, 1):
        replay_items.append(payload)
        if replay_count >= replay_budget:
            break
```

收益：

- evicted branch 不再复制之后必然无法入队的 history tail；
- 输出仍是 `gap_warning` + 当前 history 的连续前缀；
- queue maxsize 截断语义从“入队时被动 Full”前移到“复制时主动预算”，减少临时
  list 扩容和无效引用保存；
- R638 的 normal in-history tail replay 不受影响。

行为边界：

- `after_id < oldest_id - 1` 仍注入 `gap_warning`；
- 后续 replay 的第一条仍是当前 `oldest_id`，并保持严格递增；
- 默认 64-slot queue 下仍最多返回 1 条 warning + 63 条 replay payload；
- `_QUEUE_MAXSIZE <= 1` 时只发 warning，不尝试补 payload，等价于旧路径第一条
  replay `put_nowait` 立即 Full 后 break；
- 客户端仍应在收到 `gap_warning` 后 fetch 全量，best-effort replay 不升级为强
  一致性契约。

新增测试：

- `tests/test_sse_gap_replay_budget_r639.py`
  - runtime 用 `_GapHistoryProbe` 证明 evicted gap branch 只迭代
    `_QUEUE_MAXSIZE - 1` 条 history，不读取不可见 tail；
  - runtime 验证 queue 输出仍是 `gap_warning` + `[1..63]` 连续前缀；
  - source invariant 锁定 `replay_budget = self._QUEUE_MAXSIZE - 1`、
    `enumerate(self._history, 1)`、`replay_count >= replay_budget` break，
    并防止无条件 full-history list comprehension 回归。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round166/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round166/01-exa-python-queue-maxsize.json`
  保存 Python `queue.Queue` 资料：`maxsize` 是可入队 item 上限，`put_nowait`
  等价于 non-blocking put，满队列会 raise `Full`；
- `/tmp/smart-search-evidence/aiia-optimization-round166/02-exa-python-break-loop.json`
  保存 Python loop / `break` 资料：`break` 会终止最内层 `for` / `while` loop。

验证：

- `uv run pytest tests/test_sse_gap_replay_budget_r639.py
  tests/test_sse_subscribe_tail_replay_r638.py tests/test_sse_last_event_id_r41.py
  tests/test_sse_gap_warning_fastpath_r515.py tests/test_cross_process_perf_r20_14c.py`；
- `uv run pytest tests/test_sse_gap_replay_budget_r639.py
  tests/test_sse_subscribe_tail_replay_r638.py tests/test_sse_last_event_id_r41.py
  tests/test_sse_gap_warning_fastpath_r515.py tests/test_cross_process_perf_r20_14c.py
  tests/test_sse_empty_payload_fastpath_r507.py
  tests/test_sse_emit_by_type_local_counter_r637.py
  tests/test_sse_stats_empty_emit_by_type_fastpath_r636.py
  tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_sse_gap_replay_budget_r639.py
  src/ai_intervention_agent/web_ui_routes/task.py`；
- `uv run ty check tests/test_sse_gap_replay_budget_r639.py`；
- local `timeit` smoke：128 条 history、64-slot queue、visible prefix 63 条时，旧
  full copy `1.271745s / 1m`，新 budget copy `1.262813s / 1m`，best 约
  `1.007x`；median `1.286370s → 1.265711s`，约 `1.016x`；
- `/tmp/smart-search-evidence/aiia-optimization-round166/` non-empty evidence scan；
- source invariant scan for gap replay budget；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.183 R640 · Prometheus SSE emit_by_type 单桶采样避开 sorted list

发现：

`/api/system/metrics` 的 SSE per-type counter 渲染路径会调用：

```python
for event_type in sorted(emit_by_type):
    count = emit_by_type[event_type]
```

R619 已经避免了 `sorted(emit_by_type.items())` 的 tuple staging；但在实际
稳定运行中，`emit_by_type` 经常只有 1 个桶（例如只有 `task_changed`）。此时
`sorted(dict)` 仍会创建一个新 list，再对单元素做排序调度，属于 scrape 热路径
上的固定小额分配。

R640 在 helper 入口加入 singleton fast path：

```python
if len(emit_by_type) == 1:
    event_type, count = next(iter(emit_by_type.items()))
    if isinstance(count, int | float):
        yield {"event_type": str(event_type)}, int(count)
    return
```

收益：

- 单桶 SSE 指标不再为排序创建临时 list；
- 多桶路径仍走 `sorted(emit_by_type)`，保持 deterministic output；
- 非数值 count 仍被过滤，不输出非法 Prometheus sample；
- 混合 key 的多桶输入仍保留旧的 `TypeError` 边界，避免静默改写异常语义。

新增测试：

- `tests/test_prom_sse_emit_by_type_singleton_fastpath_r640.py`
  - runtime 用覆盖 `__iter__` 的 singleton dict 证明 fast path 不调用
    `sorted(dict)`；
  - runtime 锁定 singleton 非数值 count 仍过滤；
  - runtime 锁定 multi-key 输出仍排序；
  - source invariant 锁定 singleton 分支在 sorted loop 前，并禁止
    `sorted(emit_by_type.items())` 回归；
- `tests/test_prom_sse_emit_by_type_keys_r619.py` 同步旧 guard，承认 singleton
  fast path，同时保留 R619 的 key iterator / deterministic multi-key 约束。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round167/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round167/01-exa-python-sorted-dict-view.json`
  保存 Python 官方 sorting 文档摘录：`sorted()` 会从 iterable 构建新的 sorted
  list；
- `/tmp/smart-search-evidence/aiia-optimization-round167/02-fetch-python-sorting.json`
  / `03-fetch-python-dict-views.json` 保存 fetch 尝试，服务未能抽取页面但保留了
  provider fallback 结果；
- `/tmp/smart-search-evidence/aiia-optimization-round167/04-exa-python-dict-views.json`
  保存 Python 文档侧关于 dictionary / iterator view 的检索证据。

验证：

- `uv run pytest tests/test_prom_sse_emit_by_type_singleton_fastpath_r640.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  tests/test_system_metrics_prometheus_r186.py tests/test_prom_family_iterables_r518.py`；
- `uv run ruff check tests/test_prom_sse_emit_by_type_singleton_fastpath_r640.py
  tests/test_prom_sse_emit_by_type_keys_r619.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_sse_emit_by_type_singleton_fastpath_r640.py
  tests/test_prom_sse_emit_by_type_keys_r619.py`；
- local `timeit` smoke：singleton dict、1,000,000 iterations、7 repeats，旧路径
  `0.179592s` best / `0.181812s` median，新路径 `0.169310s` best /
  `0.171288s` median，best 和 median 均约 `1.061x`；
- `/tmp/smart-search-evidence/aiia-optimization-round167/` non-empty evidence scan；
- source invariant scan for singleton-before-sorted；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.184 R641 · Prometheus histogram 空桶/单桶 key 避开 list materialization

发现：

`_prom_histogram_bucket_keys()` 是 notification / MCP latency histogram 的共享
bucket key helper。R627/R628 已经让多桶输入只在检测到 disorder 后才 sort，且扫描
时不做 slice allocation；但空 histogram 和单 bucket histogram 仍会先执行：

```python
bucket_keys = list(buckets)
key_iter = iter(bucket_keys)
```

空桶场景只需要返回 synthetic `+Inf` fallback；单桶场景只需要判断该 key 是否
已经是 `+Inf`。这两个场景没有排序需求，`list(buckets)` 和后续 iterator scan
都是 scrape 热路径上的固定分配/调度成本。

R641 在 helper 入口加入 cardinality fast path：

```python
bucket_count = len(buckets)
if bucket_count == 0:
    return [_PROM_INF], False
if bucket_count == 1:
    single_key = next(iter(buckets))
    if single_key == _PROM_INF:
        return [single_key], True
    return [single_key, _PROM_INF], False
```

收益：

- 空桶不再构造 `list(buckets)` 后追加 `+Inf`；
- 单桶不再构造一份 bucket key list 再启动 sortedness scan；
- `{+Inf: count}` 仍保留 `has_inf_bucket=True`，渲染使用已有 bucket 值；
- `{0.5: count}` 仍返回 `[0.5, +Inf]` 且 `has_inf_bucket=False`，渲染的
  synthetic `+Inf` bucket 继续使用 observation `count`；
- 多桶路径完全保留 R627/R628 的 ordered-producer fast path 和 disorder sort
  fallback。

新增测试：

- `tests/test_prom_histogram_bucket_empty_singleton_fastpath_r641.py`
  - patch `system_module.list` 为抛异常，证明 empty / singleton path 不调用
    `list(buckets)`；
  - runtime 覆盖 empty、single finite bucket、single `+Inf` bucket；
  - runtime 验证 multi-bucket unordered 输入仍排序到 `[0.1, 0.5, +Inf]`；
  - source invariant 锁定 `bucket_count = len(buckets)`、empty/singleton branch
    都在 `bucket_keys = list(buckets)` 和 scan 前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round168/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round168/01-exa-python-list-iter-next.json`
  保存 Python 官方文档相关摘录：`list(...)` / list comprehension 会产生新 list，
  iterator/`next()` 用于按需取元素；
- `/tmp/smart-search-evidence/aiia-optimization-round168/02-exa-python-dict-order.json`
  保存 Python 官方数据结构文档摘录：`list(d)` 会按插入顺序返回 dict keys，
  `sorted(d)` 才用于排序输出。

验证：

- `uv run pytest tests/test_prom_histogram_bucket_empty_singleton_fastpath_r641.py
  tests/test_prom_histogram_bucket_iter_scan_r628.py
  tests/test_prom_histogram_bucket_order_fastpath_r627.py
  tests/test_prom_histogram_inf_fallback_r617.py tests/test_prom_histogram_r190.py`；
- `uv run pytest tests/test_prom_*.py tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_prom_histogram_bucket_empty_singleton_fastpath_r641.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_histogram_bucket_empty_singleton_fastpath_r641.py`；
- local `timeit` smoke：1,000,000 iterations、7 repeats，empty best
  `0.178870s → 0.059002s`（`3.032x`）、median `3.056x`；finite singleton
  best `0.142817s → 0.095145s`（`1.501x`）、median `1.526x`；`+Inf`
  singleton best `0.138690s → 0.092797s`（`1.495x`）、median `1.492x`；
- `/tmp/smart-search-evidence/aiia-optimization-round168/` non-empty evidence scan；
- source invariant scan for empty/singleton-before-list；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.185 R642 · Prometheus histogram 双桶 key 手动比较避开 list/scan

发现：

R641 已经覆盖 empty / singleton histogram bucket；但常见 latency histogram 的
早期样本还会出现两个 bucket，例如 `{0.5: 1, +Inf: 1}` 或两个有限 bucket。旧
路径仍会：

```python
bucket_keys = list(buckets)
key_iter = iter(bucket_keys)
...
bucket_keys.sort()
```

对于恰好 2 个 key 的输入，排序判断只需要一次比较；无需先把 dict keys 复制到
list，再启动 list iterator scan，乱序时也无需调用通用 `list.sort()`。

R642 在 R641 singleton fast path 后加入 two-bucket fast path：

```python
if bucket_count == 2:
    key_iter = iter(buckets)
    first_key = next(key_iter)
    second_key = next(key_iter)
    if first_key > second_key:
        first_key, second_key = second_key, first_key
    if second_key == _PROM_INF:
        return [first_key, second_key], True
    return [first_key, second_key, _PROM_INF], False
```

收益：

- 两个有限 bucket：一次比较后返回 `[small, large, +Inf]`，不再做
  `list(buckets)` / scan / `sort()`；
- finite + `+Inf`：无论插入顺序如何都返回 `[finite, +Inf]` 且
  `has_inf_bucket=True`，渲染保留已有 `+Inf` bucket 值；
- mixed incompatible key：仍在 `first_key > second_key` 处抛 `TypeError`，
  与旧 sortedness scan 的异常边界一致；
- ≥3 桶仍走 R627/R628 的 ordered producer fast path + disorder sort fallback。

新增测试：

- `tests/test_prom_histogram_bucket_pair_fastpath_r642.py`
  - patch `system_module.list` 为抛异常，证明 two-bucket finite / unordered /
    finite+`+Inf` 都不调用 `list(buckets)`；
  - runtime 验证 finite pair 排序、`+Inf` existing flag、synthetic `+Inf`
    fallback；
  - runtime 锁定 incompatible key 仍抛 `TypeError`；
  - source invariant 锁定 pair branch 在 `bucket_keys = list(buckets)` 前。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round169/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round169/01-exa-python-dict-list-sorted.json`
  保存 Python 官方数据结构文档摘录：`list(d)` 返回 dict keys list，`sorted(d)`
  用于排序输出；
- `/tmp/smart-search-evidence/aiia-optimization-round169/02-exa-python-sorted-list-sort.json`
  保存 Python 官方 sorting 文档摘录：`sorted()` 从 iterable 构建新的 sorted
  list，`list.sort()` 原地排序。

验证：

- `uv run pytest tests/test_prom_histogram_bucket_pair_fastpath_r642.py
  tests/test_prom_histogram_bucket_empty_singleton_fastpath_r641.py
  tests/test_prom_histogram_bucket_iter_scan_r628.py
  tests/test_prom_histogram_bucket_order_fastpath_r627.py
  tests/test_prom_histogram_inf_fallback_r617.py tests/test_prom_histogram_r190.py`；
- `uv run pytest tests/test_prom_*.py tests/test_system_metrics_prometheus_r186.py`；
- `uv run ruff check tests/test_prom_histogram_bucket_pair_fastpath_r642.py
  src/ai_intervention_agent/web_ui_routes/system.py`；
- `uv run ty check tests/test_prom_histogram_bucket_pair_fastpath_r642.py`；
- local `timeit` smoke：1,000,000 iterations、7 repeats，ordered finite pair best
  `0.178305s → 0.117674s`（`1.515x`）、median `1.509x`；unordered finite pair
  best `0.189137s → 0.121716s`（`1.554x`）、median `1.570x`；finite+`+Inf`
  pair best `0.168388s → 0.111330s`（`1.513x`）、median `1.507x`；
  `+Inf`+finite pair best `0.178687s → 0.117428s`（`1.522x`）、median
  `1.524x`；
- `/tmp/smart-search-evidence/aiia-optimization-round169/` non-empty evidence scan；
- source invariant scan for pair-before-list；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.186 R643 · Prometheus histogram generated `le` label 跳过 no-op escape

发现：

R618 / R623 已经把 histogram bucket label 的 dict merge 与单 base label 的
generator/join 分支去掉；但 `_format_prom_histogram_family()` 内部生成的
`le_label_value` 只有两类：

```python
le_label_value = "+Inf" if le == _PROM_INF else f"{le}"
```

这些值来自数值 bucket boundary 或 Prometheus 规定的 `+Inf` bucket，不含
反斜杠、双引号、换行。旧路径仍在每个 bucket 里调用
`_escape_prom_label_value(le_label_value)`，做三次 membership scan 后原样返回。

R643 保留 `_format_prom_histogram_bucket_labels()` 的防御性默认：

```python
le_label_value_is_safe: bool = False
```

直接调用 helper 时仍会 escape 任意 `le` 字符串；只有内部 histogram renderer
在已知生成值安全时显式传入：

```python
le_label_value_is_safe=True
```

收益：

- no-base bucket label（`{le="..."}`）完全跳过 `_escape_prom_label_value()`；
- 单 base label（notification provider histogram）每 bucket 少一次对 `le` 的
  no-op escape；
- 双 base label（MCP tool/status histogram）每 bucket 少一次对 `le` 的 no-op
  escape，base label value 仍逐项 escape；
- `base_labels` 自带 `le` 的 legacy override 路径仍走 `_format_prom_labels()`，
  不改变 override 输出或 escaping 边界；
- 直接调用 `_format_prom_histogram_bucket_labels('bad"value\n', ...)` 仍 escape，
  避免把内部 fast path 泄漏成公共契约。

新增测试：

- `tests/test_prom_histogram_bucket_safe_le_fastpath_r643.py`
  - monkeypatch `_escape_prom_label_value()`，证明 histogram family 渲染时
    `0.1` / `+Inf` 不再进入 escape helper；
  - no-base-label histogram family 完全不调用 escape helper；
  - 直接 helper 调用仍 escape arbitrary `le` label；
  - source invariant 锁定 `_format_prom_histogram_family()` 显式
    `le_label_value_is_safe=True`，helper 默认值仍为 `False`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round170/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round170/01-exa-prometheus-label-escaping.json`
  保存 Prometheus exposition format 资料：label value 中反斜杠、双引号、
  换行需要 escape，histogram bucket 使用 `le` label 且必须包含 `+Inf`；
- `/tmp/smart-search-evidence/aiia-optimization-round170/02-exa-python-string-dict-docs.json`
  保存 Python 官方资料摘录，用于本轮字符串格式化 / dict label 顺序背景。

验证：

- `uv run pytest tests/test_prom_histogram_bucket_safe_le_fastpath_r643.py
  tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_histogram_bucket_labels_r618.py` → 11 passed；
- `uv run pytest tests/test_prom_*.py tests/test_system_metrics_prometheus_r186.py`
  → 126 passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_routes/system.py
  tests/test_prom_histogram_bucket_safe_le_fastpath_r643.py`；
- `uv run ty check tests/test_prom_histogram_bucket_safe_le_fastpath_r643.py`；
- local `timeit` smoke：1,000,000 iterations、7 repeats，no-base label best
  `0.093131s → 0.065837s`（`1.415x`）、median `1.396x`；single-base label
  best `0.218778s → 0.188529s`（`1.160x`）、median `1.165x`；two-base label
  best `0.490653s → 0.453525s`（`1.082x`）、median `1.086x`；
- `/tmp/smart-search-evidence/aiia-optimization-round170/` non-empty evidence scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.187 R644 · Prometheus histogram base labels 每 observation 只 escape 一次

发现：

R643 之后，bucket 的 `le` label 已经能跳过 no-op escape；但同一个 histogram
observation 内，所有 `_bucket` 行、`_sum` 行、`_count` 行共享同一组
`base_labels`。旧路径仍在每个 bucket 中重复 escape 相同的 `provider` 或
`tool/status`：

```python
label_str = _format_prom_histogram_bucket_labels(..., base_labels, ...)
...
base_label_str = _format_prom_labels(base_labels)
```

也就是 notification latency histogram 的 `provider` 会按 bucket 数重复转义；
MCP tool latency histogram 的 `tool` / `status` 也会按 bucket 数重复转义，最后
`_sum` / `_count` 又需要再格式化同一批 base labels。

R644 把 `_format_prom_labels(base_labels)` 提前到每个 observation 的 bucket loop
前，并在没有 legacy `le` override 时复用其中已经 escape 好的 inner suffix：

```python
base_label_str = _format_prom_labels(base_labels)
preescaped_base_label_suffix = (
    base_label_str[1:-1]
    if base_label_str and base_labels and "le" not in base_labels
    else None
)
```

随后 bucket helper 只拼：

```python
{le="<generated>",<preescaped suffix>}
```

收益：

- 单 base label：`provider` 从“每 bucket escape 一次 + `_sum/_count` 一次”收敛为
  每 observation escape 一次；
- 双 base label：`tool` / `status` 同样每 observation 各 escape 一次；
- `_sum` / `_count` 继续复用同一个 `base_label_str`，不增加额外格式化；
- `base_labels` 为空时仍输出 `{le="..."}`，不引入 suffix 分支；
- `base_labels` 自带 `le` 的 legacy override 不走 suffix 复用，bucket 行继续由
  `_format_prom_labels({"le": le_label_value, **base_labels})` 维持原来的 `le`
  first 输出边界；
- 直接调用 `_format_prom_histogram_bucket_labels()` 不传 suffix 时行为不变。

新增测试：

- `tests/test_prom_histogram_preescaped_base_labels_r644.py`
  - monkeypatch `_escape_prom_label_value()`，证明单 base label 在 3 个 bucket +
    `_sum/_count` 输出中只 escape 一次；
  - multi base label 下 `tool` / `status` 也各只 escape 一次；
  - legacy `base_labels["le"]` edge case 不使用 suffix fast path，输出保持旧
    bucket/sum/count 顺序；
  - source invariant 锁定 family renderer 计算并传入
    `preescaped_base_label_suffix`，helper 在 singleton/join 分支前消费 suffix。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round171/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round171/01-exa-prometheus-histogram-labels.json`
  保存 Prometheus histogram 资料：histogram 暴露 `_bucket{le="..."}`、
  `_sum`、`_count` 多条 time series，`_count` 与 `+Inf` bucket 对齐；
- `/tmp/smart-search-evidence/aiia-optimization-round171/02-exa-python-string-dict-order.json`
  保存 Python 字符串拼接 / dict 使用资料（本轮只作为背景；核心行为由本地
  tests 锁定）。

验证：

- `uv run pytest tests/test_prom_histogram_preescaped_base_labels_r644.py
  tests/test_prom_histogram_bucket_safe_le_fastpath_r643.py
  tests/test_prom_histogram_bucket_singleton_labels_r623.py
  tests/test_prom_histogram_bucket_labels_r618.py` → 15 passed；
- `uv run pytest tests/test_prom_*.py tests/test_system_metrics_prometheus_r186.py`
  → 130 passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_routes/system.py
  tests/test_prom_histogram_preescaped_base_labels_r644.py`；
- `uv run ty check tests/test_prom_histogram_preescaped_base_labels_r644.py`；
- local `timeit` smoke：200,000 iterations、7 repeats、6 bucket observation，
  single-base histogram family best `0.890380s → 0.583651s`（`1.526x`）、
  median `1.522x`；two-base histogram family best
  `1.252348s → 0.637206s`（`1.965x`）、median `1.955x`；no-base histogram
  family best `0.489547s → 0.485613s`（`1.008x`）、median `1.001x`；
- `/tmp/smart-search-evidence/aiia-optimization-round171/` non-empty evidence scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.188 R645 · Prometheus synthetic `+Inf` bucket 复用 formatted count

发现：

R617 的 missing `+Inf` fallback 不会修改 `buckets`，而是在
`_prom_histogram_bucket_keys()` 返回的 key 序列尾部追加 synthetic `+Inf`。旧
render 路径对这条 synthetic bucket 和后面的 `_count` line 各格式化一次相同的
`count`：

```python
bucket_value = ... else count
_format_prom_value(bucket_value)
...
_format_prom_value(count)
```

Prometheus classic histogram contract 要求 `+Inf` bucket 与 `_count` 对齐；当
`+Inf` 是 renderer 合成出来的 fallback 时，这两个数值就是同一个 `count` 对象。

R645 在每个 observation 内懒缓存 `count_value_str`：

```python
count_value_str: str | None = None
...
count_value_str = _format_prom_value(count)
bucket_value_str = count_value_str
...
if count_value_str is None:
    count_value_str = _format_prom_value(count)
```

收益与边界：

- missing `+Inf` bucket：synthetic bucket 和 `_count` 共用同一个 formatted
  string，少一次 `_format_prom_value(count)`；
- existing `+Inf` bucket：仍先格式化 `buckets[_PROM_INF]`，再格式化 `_count`，
  保留 R617 “existing `+Inf` bucket value is preserved” 语义；
- 非 `+Inf` bucket 仍逐 bucket 格式化各自累计值；
- empty buckets `{}` 路径也受益：唯一 synthetic `+Inf` bucket 与 `_count`
  复用 count string；
- `sum_value` 仍独立格式化，不改变 `_sum` 输出或异常边界。

新增测试：

- `tests/test_prom_histogram_count_value_reuse_r645.py`
  - monkeypatch `_format_prom_value()`，证明 missing `+Inf` 路径调用顺序为
    `[bucket_1, bucket_2, count, sum]`，`count` 不再格式化第二次；
  - existing `+Inf` 路径仍调用 `[bucket_1, existing_inf_value, sum, count]`，
    保留 existing bucket 与 count 独立；
  - source invariant 锁定 `count_value_str` 在 bucket loop 前初始化、synthetic
    branch 赋值、loop 后按需补格式化。
- `tests/test_prom_histogram_inf_fallback_r617.py`
  - 更新 source invariant：仍禁止 copy/mutate buckets，并锁定新的
    `bucket_value_str` / `count_value_str` 分支。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round172/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round172/01-exa-prometheus-histogram-count-inf.json`
  保存 Prometheus / client_golang 资料：classic histogram 的 `+Inf` bucket
  与 histogram datapoint total count 对齐；
- `/tmp/smart-search-evidence/aiia-optimization-round172/02-exa-python-function-call-formatting.json`
  保存 Python formatting / function call 资料（本轮核心行为由本地 tests 和
  benchmark 锁定）。

验证：

- `uv run pytest tests/test_prom_histogram_count_value_reuse_r645.py
  tests/test_prom_histogram_inf_fallback_r617.py
  tests/test_prom_histogram_preescaped_base_labels_r644.py
  tests/test_prom_histogram_bucket_safe_le_fastpath_r643.py` → 14 passed；
- `uv run pytest tests/test_prom_*.py tests/test_system_metrics_prometheus_r186.py`
  → 133 passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_routes/system.py
  tests/test_prom_histogram_count_value_reuse_r645.py
  tests/test_prom_histogram_inf_fallback_r617.py`；
- `uv run ty check tests/test_prom_histogram_count_value_reuse_r645.py
  tests/test_prom_histogram_inf_fallback_r617.py`；
- local `timeit` smoke：250,000 iterations、7 repeats，missing-`+Inf` 6-bucket
  histogram family best `0.713004s → 0.689393s`（`1.034x`）、median
  `1.041x`；empty bucket best `0.247798s → 0.234164s`（`1.058x`）、median
  `1.066x`；existing-`+Inf` 6-bucket best `0.716140s → 0.694555s`
  （`1.031x`）、median `1.029x`（行为保持独立格式化，数值视为 microbenchmark
  中性/小幅波动）；
- `/tmp/smart-search-evidence/aiia-optimization-round172/` non-empty evidence scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.189 R646 · TaskQueue empty stats 快路径跳过 values scan setup

发现：

R521 / R522 已经把 TaskQueue 的 list snapshot + stats 统计收敛为一次遍历，并把
固定 status 计数从 dict update 改成局部 int counter。但空队列仍走 generic
路径：

```python
pending = active = completed = 0
tasks_view: list[Task] = []
for t in self._tasks.values():
    ...
```

`/api/tasks` 轮询和 VS Code/web UI fallback polling 在“还没有任务”时会频繁命中
空队列；此时可以直接返回相同 shape 的空 stats，避免创建 `dict_values` view、
进入 loop setup、再由 `len(...)` 推导 total。

R646 在两个读快照方法的同一个 read lock 内加入 empty fast path：

```python
if not self._tasks:
    return [], {
        "total": 0,
        "pending": 0,
        "active": 0,
        "completed": 0,
        "max": self.max_tasks,
    }
```

收益与边界：

- `get_all_tasks_with_stats()` 空队列：仍返回新的空 list + 新 stats dict，但不再
  调 `_tasks.values()`；
- `get_task_count()` 空队列：仍返回新 stats dict，但不再调 `_tasks.values()`；
- 非空队列仍走 R521/R522 的单 pass list+counter / direct counter 路径；
- 未知 status 仍只进入 total、不进入 breakdown；
- 仍在 `read_lock` 内判断并返回，snapshot 语义不变。

新增测试：

- `tests/test_task_queue_empty_stats_fastpath_r646.py`
  - 用 `values()` 会抛异常的空 dict subclass 注入 `_tasks`，证明两个 empty
    fast path 都不 touch values view；
  - runtime 覆盖非空队列的 task order、active/pending/completed/max 统计仍不变；
  - source invariant 锁定 `if not self._tasks:` 位于
    `for t in self._tasks.values():` 之前，并锁定空 stats shape。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round173/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round173/01-exa-python-dict-truth-views.json`
  保存 Python dict / truth-value / dict view 资料；
- `/tmp/smart-search-evidence/aiia-optimization-round173/02-exa-python-list-dict-values.json`
  保存 Python list / dict values 相关资料（核心行为由本地 tests 锁定）。

验证：

- `uv run pytest tests/test_task_queue_empty_stats_fastpath_r646.py
  tests/test_get_all_tasks_with_stats_one_pass_r521.py
  tests/test_task_queue_status_direct_counters_r522.py` → 11 passed；
- `uv run pytest tests/test_task_queue_counter_decision_r452.py
  tests/test_task_queue_empty_stats_fastpath_r646.py
  tests/test_get_all_tasks_with_stats_one_pass_r521.py
  tests/test_task_queue_status_direct_counters_r522.py` → 14 passed；
- `uv run pytest tests/test_task_queue_empty_stats_fastpath_r646.py
  tests/test_get_all_tasks_with_stats_one_pass_r521.py
  tests/test_task_queue_status_direct_counters_r522.py tests/test_task_queue.py
  tests/test_task_queue_rwlock_r22_2.py tests/test_web_ui_routes.py` →
  269 passed, 15 subtests passed；
- `uv run ruff check src/ai_intervention_agent/task_queue.py
  tests/test_task_queue_empty_stats_fastpath_r646.py
  tests/test_task_queue_counter_decision_r452.py`；
- `uv run ty check tests/test_task_queue_empty_stats_fastpath_r646.py
  tests/test_task_queue_counter_decision_r452.py`；
- local `timeit` smoke：7 repeats。empty `get_task_count` 400,000 iterations
  best `0.283221s → 0.265080s`（`1.068x`）、median `1.066x`；
  empty `get_all_tasks_with_stats` best `0.290110s → 0.270476s`
  （`1.073x`）、median `1.076x`；non-empty 3-task
  `get_task_count` best `0.314399s → 0.270121s`（`1.164x`）、
  median `1.162x`；non-empty `get_all_tasks_with_stats` best
  `0.271547s → 0.275900s`（`0.984x`）、median `0.990x`，视为
  loop body unchanged 下的中性噪声/极小分支成本；
- `/tmp/smart-search-evidence/aiia-optimization-round173/` non-empty evidence
  scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.190 R647 · SSE emit 复用 serializer-normalized empty payload

发现：

R507 已经把 SSE empty payload 的 JSON 序列化收敛到
`_serialize_sse_payload()`，让 `None` / `{}` 直接复用 `_SSE_EMPTY_JSON`，不再
走 `json.dumps(data or {})`。但 `emit()` 构造内部 payload 时仍写：

```python
data, serialized_data = _serialize_sse_payload(data)
...
"data": data or {},
```

对于最常见的 empty event payload，`_serialize_sse_payload()` 已经返回了一个
normalized `{}`；后续 `data or {}` 因为空 dict falsy，又分配第二个空 dict。
R647 改为直接使用 normalized object：

```python
"data": data,
```

收益与边界：

- empty payload：少一次 bool-or fallback 和一个额外 `{}` 分配；
- non-empty payload：少一次 truthiness branch，语义不变；
- `_serialize_sse_payload()` 仍是唯一 normalization 边界；它继续把所有 falsy
  payload 规范化为 `{}` + `"{}"`；
- oversize replacement path 会把 `data` 换成非空 metadata dict，仍原样进入
  payload；
- generator 继续优先消费 `_serialized`，wire JSON 不变。

新增测试：

- `tests/test_sse_emit_reuses_normalized_payload_r647.py`
  - monkeypatch `_serialize_sse_payload()` 返回一个 falsy dict subclass，证明
    `emit()` 存入的 `payload["data"]` 正是 serializer 返回对象，而不是第二次
    `or {}` 后的新 dict；
  - runtime 覆盖 `emit(..., None)` 仍对外暴露 `{}` + `"{}"`；
  - source invariant 锁定 `data, serialized_data = _serialize_sse_payload(data)`
    在 payload 构造前，且 `emit()` 内不再出现 `"data": data or {}`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round174/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round174/01-exa-python-boolean-or-operands.json`
  保存 Python boolean `or` 语义资料：`x or y` 在 `x` falsy 时会求值并返回
  `y`，空 dict 属于 falsy mapping；本轮 allocation/identity 由本地测试与
  benchmark 锁定。

验证：

- `uv run pytest tests/test_sse_emit_reuses_normalized_payload_r647.py
  tests/test_sse_empty_payload_fastpath_r507.py
  tests/test_sse_oversize_drop_fastpath_r523.py
  tests/test_sse_oversize_ascii_fastpath_r502.py
  tests/test_sse_oversize_utf8_fastpath_r501.py` → 25 passed；
- `uv run pytest tests/test_sse_*.py` → 266 passed, 26 subtests passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_routes/task.py
  tests/test_sse_emit_reuses_normalized_payload_r647.py`；
- `uv run ty check tests/test_sse_emit_reuses_normalized_payload_r647.py`；
- local `timeit` smoke：2,000,000 iterations、7 repeats，empty normalized
  payload construction best `0.128196s → 0.113556s`（`1.129x`）、median
  `1.123x`；non-empty construction best `0.116233s → 0.113888s`
  （`1.021x`）、median `1.015x`；identity smoke：
  old empty path `old_reuses=False`，new empty path `new_reuses=True`；
- `/tmp/smart-search-evidence/aiia-optimization-round174/` non-empty evidence
  scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.191 R648 · Notification status stats snapshot 用 copy/pop 替代过滤 comprehension

发现：

`NotificationManager.get_status()` 是 Web UI / health / notification config
相关路径会调用的状态快照方法。旧实现为了把 provider stats 单独深拷贝，会先：

```python
providers_stats_raw = self._stats.get("providers")
...
stats_snapshot = {k: v for k, v in self._stats.items() if k != "providers"}
stats_snapshot["providers"] = providers_stats
```

这会在 Python 层遍历 `_stats.items()`，并对每个 key 执行一次
`k != "providers"` 分支。`_stats` 是普通 dict，且只需要浅拷贝顶层字段；
provider 子 dict 仍由后续逻辑防御性复制。R648 改为：

```python
stats_snapshot = self._stats.copy()
providers_stats_raw = stats_snapshot.pop("providers", None)
providers_stats = (
    {k: dict(v) for k, v in providers_stats_raw.items()}
    if isinstance(providers_stats_raw, dict)
    else {}
)
stats_snapshot["providers"] = providers_stats
```

收益与边界：

- 顶层 stats snapshot 改为 C 层 dict copy，避免 Python comprehension + branch；
- `providers` 仍从返回 snapshot 中剥离后重建为 provider 子 dict 的浅拷贝；
- 缺失 / 非 dict `providers` 仍返回空 provider snapshot；
- `stats_snapshot["providers"]` 仍始终存在，保持 status JSON shape；
- 派生字段 `events_finalized` / `events_in_flight` /
  `delivery_success_rate` 和 provider `success_rate` / `avg_latency_ms`
  计算边界不变；
- 外部修改 `status["stats"]["providers"][...]` 仍不会污染内部 `_stats`。

新增/更新测试：

- `tests/test_notification_status_stats_copy_pop_r648.py`
  - source invariant 锁定 `self._stats.copy()` → `stats_snapshot.pop(...)` →
    provider copy 的顺序，并禁止重新引入 `if k != "providers"` 过滤；
  - runtime 覆盖 provider stats defensive copy，外部 mutation 不污染内部 stats；
  - runtime 覆盖缺失 provider stats 时仍返回 `{}` 且保留顶层 stats 字段。
- `tests/test_notification_inflight_persistence_r136.py`
  - 更新 R480 source invariant：继续禁止 eager `{}` fallback，同时锁定新的
    copy/pop 快路径。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round175/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round175/02-exa-python-dict-copy-pop.json`
  保存 Python dict / copy / pop / complexity 资料；本轮性能结论由本地
  benchmark 锁定。

验证：

- `uv run pytest tests/test_notification_status_stats_copy_pop_r648.py
  tests/test_notification_inflight_persistence_r136.py tests/test_notification_manager.py
  -k "get_status or status_provider_stats or status_missing_providers or
  inflight_seen_at_startup"` → 7 passed, 204 deselected；
- `uv run pytest tests/test_notification_status_stats_copy_pop_r648.py
  tests/test_notification_inflight_persistence_r136.py tests/test_notification_manager.py
  tests/test_notification_health_per_provider_r142.py
  tests/test_notification_health_streak_r145.py` → 265 passed；
- `uv run ruff check src/ai_intervention_agent/notification_manager.py
  tests/test_notification_status_stats_copy_pop_r648.py
  tests/test_notification_inflight_persistence_r136.py`；
- `uv run ty check tests/test_notification_status_stats_copy_pop_r648.py
  tests/test_notification_inflight_persistence_r136.py`；
- local `timeit` smoke：1,000,000 iterations、7 repeats，带两个 provider 的
  snapshot path best `0.472073s → 0.279337s`（`1.677x`）、median
  `1.682x`；缺失 providers path best `0.347655s → 0.089329s`
  （`3.892x`）、median `3.896x`；old/new output equality smoke 均为
  `True`；
- `/tmp/smart-search-evidence/aiia-optimization-round175/` non-empty evidence
  scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.192 R649 · Notification provider latency +Inf bucket key 常量化

发现：

`NotificationManager.get_provider_latency_histograms_snapshot()` 每次生成
provider latency histogram 快照时都会为每个 provider 执行：

```python
buckets_copy[float("inf")] = state["count"]
```

该路径本身仍需要复制有限 bucket dict 来保证返回值不会污染内部状态，但 `+Inf`
bucket key 是稳定常量。R649 将它提升为模块级
`_NOTIFICATION_LATENCY_INF_BUCKET = float("inf")`，snapshot 循环只复用同一个
key 对象：

```python
buckets_copy[_NOTIFICATION_LATENCY_INF_BUCKET] = state["count"]
```

收益与边界：

- 避免 provider snapshot 循环内重复构造 `float("inf")`；
- Prometheus histogram 形态不变，调用者仍可用 `float("inf")` 查询 `+Inf`
  bucket；
- 仍对每个 provider 的有限 bucket dict 做 defensive copy；
- 不触碰 `mcp_tool_call_metrics`，该处属于独立 measured slice。

新增测试：

- `tests/test_notification_latency_inf_bucket_constant_r649.py`
  - source invariant 锁定 snapshot 循环使用
    `_NOTIFICATION_LATENCY_INF_BUCKET`，禁止回退到 `buckets_copy[float("inf")]`；
  - runtime 覆盖 `float("inf")` 查询仍命中、`+Inf` bucket value 仍等于
    `count`；
  - runtime 覆盖返回 snapshot 仍是 defensive copy。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round176/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round176/01-exa-python-float-inf-dict-key.json`
  保存 Python float / dict key 相关资料；本轮性能结论由本地 benchmark 锁定。

验证：

- `uv run pytest tests/test_notification_latency_inf_bucket_constant_r649.py
  tests/test_notification_latency_histogram_r191.py` → 19 passed；
- `uv run pytest tests/test_notification_latency_inf_bucket_constant_r649.py
  tests/test_notification_latency_histogram_r191.py tests/test_notification_manager.py
  tests/test_web_ui_routes.py tests/test_system_health_r121.py` → 380 passed,
  3 subtests passed；
- `uv run ruff check src/ai_intervention_agent/notification_manager.py
  tests/test_notification_latency_inf_bucket_constant_r649.py`；
- `uv run ty check tests/test_notification_latency_inf_bucket_constant_r649.py`；
- local `timeit` smoke：1,000,000 iterations、7 repeats，单 provider snapshot
  best `0.209761s → 0.192109s`（`1.092x`）；四 provider path best
  `0.634575s → 0.540352s`（`1.174x`）；old/new output equality smoke 为
  `True`。
- `/tmp/smart-search-evidence/aiia-optimization-round176/` non-empty evidence
  scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.193 R650 · MCP tool latency +Inf bucket key 常量化

发现：

R649 只处理了 notification provider histogram producer；MCP tool call latency
snapshot 仍在每个 `(tool_name, status)` series 上执行：

```python
buckets_copy[float("inf")] = state["count"]
```

`get_mcp_tool_call_latency_snapshot()` 是 `/metrics` 读取
`aiia_mcp_tool_call_duration_seconds` 的 producer 快照路径。它仍必须复制有限
bucket dict，避免 caller 或 Prometheus renderer 污染 `_latency_state`；但
`+Inf` bucket key 本身不需要在循环内重复构造。R650 增加模块级
`_MCP_LATENCY_INF_BUCKET = float("inf")`，snapshot 循环复用该 key：

```python
buckets_copy[_MCP_LATENCY_INF_BUCKET] = state["count"]
```

收益与边界：

- 避免 MCP latency snapshot 循环内重复构造 `float("inf")`；
- 返回形态仍可用 `float("inf")` 查询，`+Inf` bucket value 仍等于 `count`；
- snapshot 仍是 defensive copy；
- Prometheus renderer 的 `_PROM_INF` 常量保持不变，本轮只改 producer 快照。

新增测试：

- `tests/test_mcp_latency_inf_bucket_constant_r650.py`
  - source invariant 锁定 snapshot 循环使用 `_MCP_LATENCY_INF_BUCKET`；
  - runtime 覆盖 `float("inf")` 查询仍命中、返回 bucket key 复用模块常量；
  - runtime 覆盖返回 snapshot 仍是 defensive copy。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round177/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round177/01-exa-python-float-inf-dict-key.json`
  保存 Python float / dict key 相关资料；本轮性能结论由本地 benchmark 锁定。

验证：

- `uv run pytest tests/test_mcp_latency_inf_bucket_constant_r650.py
  tests/test_prom_histogram_r190.py tests/test_mcp_tool_call_metrics_r187.py`
  → 45 passed；
- `uv run pytest tests/test_prom_*.py tests/test_system_health_r121.py`
  → 142 passed, 3 subtests passed；
- `uv run ruff check src/ai_intervention_agent/mcp_tool_call_metrics.py
  tests/test_mcp_latency_inf_bucket_constant_r650.py`；
- `uv run ty check tests/test_mcp_latency_inf_bucket_constant_r650.py`；
- local `timeit` smoke：1,000,000 iterations、7 repeats，单 series snapshot
  best `0.219868s → 0.198529s`（`1.107x`）；四 series path best
  `0.663526s → 0.540375s`（`1.228x`）；old/new output equality smoke 为
  `True`。
- `/tmp/smart-search-evidence/aiia-optimization-round177/` non-empty evidence
  scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.194 R651 · Latency histogram 新状态复用 zero bucket 模板

发现：

MCP tool latency 与 notification provider latency 的 histogram state 首次创建
时都会执行一遍：

```python
dict.fromkeys(_DEFAULT_LATENCY_BUCKETS, 0)
```

或 notification 侧等价的 `dict.fromkeys(self._DEFAULT_LATENCY_BUCKETS_SECONDS, 0)`。
这些 bucket 模板固定且 value 全为 immutable `0`，每个新 series / provider
只需要一份独立 dict，没必要每次重新从 tuple 构造 key table。R651 增加固定
zero bucket 模板：

```python
_DEFAULT_LATENCY_BUCKET_COUNTS = dict.fromkeys(_DEFAULT_LATENCY_BUCKETS, 0)
```

新状态创建时改为复制模板：

```python
"buckets": _DEFAULT_LATENCY_BUCKET_COUNTS.copy()
```

notification 侧同样增加 `_DEFAULT_LATENCY_BUCKET_COUNTS` class attribute，并用
`self._DEFAULT_LATENCY_BUCKET_COUNTS.copy()` 初始化 provider state。

收益与边界：

- 新 histogram series / provider 初始化少一次 `dict.fromkeys()` 构造；
- 每个 state 仍拿到独立 bucket dict，不与模板或其他 state alias；
- bucket 累加和 `+Inf` snapshot 行为不变；
- 测过但拒绝的替代方案：用 `bisect` / max-bucket fast path 优化 recording
  循环。它们只在超出最大有限 bucket 时明显获益，但会让常规 in-range sample
  变慢或收益不稳定，因此不落地。

新增测试：

- `tests/test_latency_bucket_template_copy_r651.py`
  - source invariant 锁定 MCP / notification 新 state 都从 zero template
    `.copy()`；
  - runtime 覆盖 state bucket dict 不 alias 模板；
  - runtime 覆盖污染一个 series/provider 的 buckets 不影响下一个新 state。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round178/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round178/01-exa-python-dict-copy-docs.json`
  保存 Python dict shallow copy 资料；本轮性能结论由本地 benchmark 锁定。

验证：

- `uv run pytest tests/test_latency_bucket_template_copy_r651.py
  tests/test_prom_histogram_r190.py tests/test_notification_latency_histogram_r191.py`
  → 44 passed；
- `uv run pytest tests/test_latency_bucket_template_copy_r651.py tests/test_prom_*.py
  tests/test_notification_manager.py tests/test_notification_latency_histogram_r191.py
  tests/test_web_ui_routes.py tests/test_system_health_r121.py`
  → 485 passed, 3 subtests passed；
- `uv run ruff check src/ai_intervention_agent/mcp_tool_call_metrics.py
  src/ai_intervention_agent/notification_manager.py
  tests/test_latency_bucket_template_copy_r651.py`；
- `uv run ty check tests/test_latency_bucket_template_copy_r651.py`；
- local `timeit` smoke：2,000,000 iterations、7 repeats，MCP bucket state
  creation best `0.324799s → 0.086359s`（`3.761x`）；notification bucket state
  creation best `0.351295s → 0.085276s`（`4.120x`）；old/new output equality
  smoke 为 `True`。
- `/tmp/smart-search-evidence/aiia-optimization-round178/` non-empty evidence
  scan；
- touched-file trailing whitespace / CR scans；
- `git diff --check`。

### 3.195 R652 · last_error 分类复用 compiled regex

发现：

`_classify_last_error()` 是 system health per-provider snapshot 的安全归类
路径。旧实现每次遇到非空 `last_error` 都在函数内 `import re`，并用字符串
pattern 调 `re.search()` / `re.match()`。Python 的 regex cache 能避免每次
重新编译，但函数仍要反复走 import lookup、cache lookup、pattern parse/cache key
路径；而这里的两个 pattern 是固定契约，适合提升到 module-level compiled regex。

R652 调整：

- 在 `src/ai_intervention_agent/web_ui_routes/system.py` 顶层导入 `re`；
- 增加 `_LAST_ERROR_STATUS_RE` 与 `_LAST_ERROR_PREFIX_STATUS_RE` compiled
  regex 常量；
- 增加 `_LAST_ERROR_NETWORK_KEYWORDS` tuple，替代内联 `or` 链；
- `_classify_last_error()` 保持原有优先级：
  `not_registered` → HTTP 5xx/4xx → timeout → network → unknown。

收益与边界：

- 非空错误归类路径少了每次 regex cache lookup 和 local import；
- `None` / `""` guard 仍直接返回，不触发 regex；
- HTTP status 提取仍限定在明确 HTTP / status_code 上下文，不把 port 443
  误判成 4xx；
- 原始 `last_error` 文本仍不进入 health payload，PII 边界不变；
- 测过但拒绝的替代方案：Prometheus histogram formatter 的 first-observation
  / header hoist。50,000 iterations、7 repeats 下，0 / 1 / 4 / 16 observations
  全部慢于现状（约 `0.54x`-`0.88x`），因此不落地。

新增测试：

- `tests/test_last_error_classifier_compiled_regex_r652.py`
  - source invariant 锁定 classifier 不再函数内 `import re`；
  - source invariant 锁定使用 module-level compiled regex 与 keyword tuple；
  - runtime 覆盖 `None`、空字符串、`status_code` dict repr、HTTP 文本、
    prefix status、timeout、network、not_registered、unknown。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round179/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round179/01-exa-python-re-compile-docs.json`
  保存 Python regex compile / reuse 相关资料；本轮性能结论由本地 benchmark
  锁定。

验证：

- `uv run pytest tests/test_last_error_classifier_compiled_regex_r652.py
  tests/test_notification_health_last_error_class_r143.py
  tests/test_notification_health_per_provider_r142.py
  tests/test_notification_health_streak_r145.py`
  → 93 passed；
- `uv run pytest tests/test_last_error_classifier_compiled_regex_r652.py
  tests/test_system_health_r121.py tests/test_system_metrics_prometheus_r186.py
  tests/test_web_ui_routes.py`
  → 216 passed, 3 subtests passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_routes/system.py
  tests/test_last_error_classifier_compiled_regex_r652.py`；
- `uv run ty check tests/test_last_error_classifier_compiled_regex_r652.py`；
- local `timeit` smoke：500,000 iterations、7 repeats，old local inline-regex
  function vs imported R652 function，old/new output equality smoke 为 `True`。
  非空路径 best：
  - `status_dict` `0.220466s → 0.149350s`（`1.476x`）；
  - `http_text` `0.212672s → 0.146194s`（`1.455x`）；
  - `prefix` `0.406933s → 0.276793s`（`1.470x`）；
  - `timeout` `0.314942s → 0.190820s`（`1.650x`）；
  - `network` `0.304894s → 0.257399s`（`1.185x`）；
  - `unknown` `0.343143s → 0.306160s`（`1.121x`）。
  `None` / `""` guard 本来不进入 regex 路径，本轮 benchmark 中新函数约
  `0.79x` / `0.82x`，不作为本优化收益点。

### 3.196 R653 · LogDeduplicator miss-path cleanup 加时间窗/容量 gate

发现：

`LogDeduplicator.should_log()` 的 R16·D 修复已经让 cache hit 路径按
`_LAZY_CLEANUP_INTERVAL_SECONDS` 周期触发过期清理，避免高频重复日志让 stale
entry 永久滞留。但 cache miss 分支仍然在每条新消息插入后无条件调用
`_cleanup_cache(current_time)`。这个 helper 会遍历整个 cache 找过期 entry，
必要时还会按 timestamp 排序裁剪，因此 unique error burst 会退化成近似
O(n²)：第 1 条扫 1 个，第 2 条扫 2 个，以此类推。

R653 把 miss-path cleanup 收敛到两个必要条件：

```python
if (
    current_time - self._last_cleanup_time >= self.time_window
    or len(self.cache) > self.max_cache_size
):
    self._cleanup_cache(current_time)
    self._last_cleanup_time = current_time
```

收益与边界：

- 同一 `time_window` 内的 fresh unique misses 保持 O(1)，不再每条日志扫描
  cache；
- 超过 `time_window` 后的 miss 仍会清理过期 entry，保留
  `test_expired_entries_removed` 语义；
- 超过 `max_cache_size` 的 miss 仍立即触发 size-cap cleanup，保留有界 cache；
- cache hit 路径的 `_LAZY_CLEANUP_INTERVAL_SECONDS` 周期清理不变；
- 继续使用 `time.monotonic()`，不受 wall-clock/NTP 回拨影响。

新增测试：

- `tests/test_log_deduplicator_miss_cleanup_gate_r653.py`
  - source invariant 锁定 miss cleanup 由 `time_window` 或 `max_cache_size`
    gate 控制；
  - runtime 覆盖 fresh unique misses 只触发首次 startup cleanup；
  - runtime 覆盖过期 entry 在 miss 后仍被清理；
  - runtime 覆盖超过 size cap 后仍触发 cleanup 且 cache 回到上限内。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round180/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round180/01-exa-python-monotonic-cache-cleanup.json`
  保存 cache TTL / active-vs-lazy cleanup 相关资料；
- `/tmp/smart-search-evidence/aiia-optimization-round180/02-exa-python-docs-monotonic-dict.json`
  保存 Python 官方 `time.monotonic()` 文档证据：monotonic clock 不会倒退，
  不受系统时钟更新影响；本轮性能结论由本地 benchmark 锁定。

验证：

- `uv run pytest tests/test_log_deduplicator_miss_cleanup_gate_r653.py
  tests/test_enhanced_logging.py tests/test_performance.py::TestLogDeduplicatorPerformance`
  → 59 passed；
- `uv run pytest tests/test_log_deduplicator_miss_cleanup_gate_r653.py
  tests/test_enhanced_logging.py tests/test_diagnostic_event_log_r40.py
  tests/test_performance.py`
  → 90 passed；
- `uv run ruff check src/ai_intervention_agent/enhanced_logging.py
  tests/test_log_deduplicator_miss_cleanup_gate_r653.py`；
- `uv run ty check tests/test_log_deduplicator_miss_cleanup_gate_r653.py`；
- local `timeit` smoke：7 repeats，old local unconditional-cleanup class vs
  imported R653 `LogDeduplicator`，expired / unique / repeated / overflow
  contracts 为 `True`：
  - unique 2,000 messages × 20 loops best
    `0.757203s → 0.011454s`（`66.106x`）；
  - repeated 10,000 messages × 50 loops best
    `0.178867s → 0.176420s`（`1.014x`）；
  - overflow 10,000 messages × 20 loops best
    `3.404074s → 0.102969s`（`33.059x`）。

### 3.197 R654 · LogSanitizer marker fast path

发现：

`LogSanitizer.sanitize()` 在 enhanced logging 管线里会处理每条实际输出的日志。
R54-B/R111 扩展后，它要按顺序跑密码字段、OpenAI/Anthropic key、GitHub token、
Slack token、AWS/GCP/HF/Stripe、URL basic auth、JWT 等多条 regex。正常日志通常
只是状态、任务、事件字段，不包含任何 secret-like marker；这些 marker-free 日志
继续逐条跑 regex 属于纯 hot-path 开销。

R654 增加 `_SENSITIVE_LOG_MARKERS` tuple，把现有 regex 能识别的字段名或 token
前缀作为 cheap precheck：

```python
for marker in _SENSITIVE_LOG_MARKERS:
    if marker in message:
        break
else:
    return message
```

收益与边界：

- marker-free 普通日志直接原样返回，不再遍历 regex set；
- 所有已存在 redaction regex 仍是权威实现，marker 只决定是否值得进入 regex
  loop；
- marker tuple 覆盖 `password` / `passwd` / `secret` / `private`、`sk-`、
  GitHub token prefixes、`AKIA`、`AIza`、`hf_`、Stripe prefixes、`http(s)://`
  与 `eyJ`；
- sensitive-bearing 日志会先付一次 marker loop，再进入 regex loop；benchmark
  显示这类路径约 `0.85x`-`0.98x`，但 secret-bearing 日志应远少于正常日志；
- 输出等价 smoke 为 `True`，现有 PII redaction case 仍由 regex 测试覆盖。

新增测试：

- `tests/test_log_sanitizer_marker_fastpath_r654.py`
  - source invariant 锁定 marker fast path 位于 regex loop 之前；
  - runtime 用会抛异常的 fake pattern 验证 marker-free message 不跑 regex；
  - 参数化覆盖 password/passwd/secret/private/OpenAI/Slack/GitHub/AWS/GCP/HF/
    Stripe/URL basic auth/JWT 代表样本仍会脱敏；
  - marker tuple coverage test 防止新增/删改 marker 时遗漏代表前缀。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round181/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round181/01-exa-python-re-string-docs.json`
  保存 Python regex / string containment 相关资料；本轮性能结论由本地 benchmark
  锁定。

验证：

- `uv run pytest tests/test_log_sanitizer_marker_fastpath_r654.py
  tests/test_log_sanitizer_pii_r54b.py tests/test_enhanced_logging.py`
  → 107 passed；
- `uv run pytest tests/test_log_sanitizer_marker_fastpath_r654.py
  tests/test_log_sanitizer_pii_r54b.py tests/test_enhanced_logging.py
  tests/test_log_ring_buffer_r51c.py tests/test_diagnostic_event_log_r40.py
  tests/test_performance.py::TestLogDeduplicatorPerformance`
  → 145 passed；
- `uv run ruff check src/ai_intervention_agent/enhanced_logging.py
  tests/test_log_sanitizer_marker_fastpath_r654.py`；
- `uv run ty check tests/test_log_sanitizer_marker_fastpath_r654.py`；
- local `timeit` smoke：old local sanitizer vs imported R654 `LogSanitizer`，
  output equality 为 `True`：
  - marker-free short normal message，200,000 iterations best
    `0.478315s → 0.070471s`（`6.787x`）；
  - marker-free long normal message，50,000 iterations best
    `1.440651s → 0.272512s`（`5.287x`）；
  - sensitive path old/new ratio：password `0.983x`、OpenAI `0.855x`、
    GitHub `0.929x`、URL `0.973x`、JWT `0.852x`，接受为低频路径的轻微
    precheck overhead。
- 测过但拒绝的替代方案：
  - `get_recent_logs(limit=N)` 用 `itertools.islice`：小 limit 仅约 `1.05x`，
    full limit 约 `0.66x`，不落地；
  - 单个 compiled marker regex：部分 sensitive path 更快，但 long marker-free
    normal message 明显回退（约 `0.38x`），不落地；
  - task route serialization helper extraction：偏维护性，hot loop 里可能增加
    调用开销，本轮不落地。

### 3.198 R655 · recent-logs cache key 移出 payload dict

发现：

`server_info_resource()` 会聚合 MCP 进程本地 ring buffer 与 Web UI 子进程的
`/api/system/recent-logs`。R55 已经用 1 秒 TTL cache 抑制高频 self-info polling
打穿 Web UI 端 30/min 限流；但 cache hit 路径把 limit cache key 存在 payload
dict 内部：

```python
_recent_logs_cache["_key"] = cache_key
cached_copy = {k: v for k, v in _recent_logs_cache.items() if k != "_key"}
```

这让每次 cache hit 都要遍历整个 cache dict 并跑一次过滤 comprehension，只是为了
把内部 metadata 从返回 payload 里剔掉。R655 把 key 拆成独立 sidecar：

```python
_recent_logs_cache_key: str = ""
```

cache payload dict 只保存 `entries` / `count`，hit 时改为：

```python
cached_copy = dict(_recent_logs_cache)
```

收益与边界：

- recent-logs hit path 少一次过滤 comprehension，直接走浅拷贝；
- `limit` 仍参与 cache key，不同 limit 仍会 miss/refetch；
- 返回 dict 仍是独立副本，外部改返回值不污染 cache；
- `_key` 不再混入 payload cache，避免未来 endpoint 字段与内部 metadata
  撞名；
- `reset_recent_logs_cache_for_testing()` 同步清空 sidecar key，保持测试隔离。

新增测试：

- `tests/test_recent_logs_cache_sidecar_key_r655.py`
  - source invariant 锁定 hit path 使用 `_recent_logs_cache_key == cache_key`
    与 `dict(_recent_logs_cache)`；
  - runtime 覆盖 cache payload 不保存 `_key`，hit 仍不发第二次 HTTP；
  - runtime 覆盖不同 `limit` 仍隔离；
  - runtime 覆盖 reset helper 清空 payload、key 与 timestamp。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round182/00-doctor.json`
  保存本轮 smart-search 诊断，`ok: true`；
- `/tmp/smart-search-evidence/aiia-optimization-round182/01-exa-python-dict-copy-comprehension.json`
  保存 Python dict / shallow copy / comprehension 相关资料；本轮性能结论由本地
  benchmark 锁定。

验证：

- `uv run pytest tests/test_recent_logs_cache_sidecar_key_r655.py
  tests/test_recent_logs_aggregation_r55.py tests/test_sse_stats_cache_r54a.py
  tests/test_server_info_sse_r50.py tests/test_feat_notification_cache_perf_baseline_r307.py
  tests/test_feat_module_level_cache_reset_audit_r352.py`
  → 64 passed, 10 subtests passed；
- `uv run ruff check src/ai_intervention_agent/server.py
  tests/test_recent_logs_cache_sidecar_key_r655.py`；
- `uv run ty check tests/test_recent_logs_cache_sidecar_key_r655.py`；
- local `timeit` smoke：500,000 cache-hit calls、7 repeats，old local
  in-payload `_key` implementation vs imported R655 implementation，contract
  check 为 `True` 且 imported cache 不含 `_key`：
  - old hit best `0.292982s`；
  - new hit best `0.231292s`（`1.267x`）。

### 3.199 R656 · CSP nonce helper 复用 has_request_context 绑定

发现：

`SecurityMixin._get_csp_nonce()` 在模板 context / CSP helper 路径上会被请求内
读取；R464 已经修掉 `getattr(..., secrets.token_urlsafe(16))` 的 eager fallback，
但函数体内仍保留：

```python
from flask import has_request_context
```

Python 会复用 `sys.modules` 里的模块对象，但 `import` 语句本身仍要执行查找与
名称绑定。对已经有 `g.csp_nonce` 的 hot path 来说，这段导入没有业务收益。
R656 把 `has_request_context` 移到 `web_ui_security.py` 的 Flask 模块级 import：

```python
from flask import Response, abort, g, has_request_context, request
```

收益与边界：

- request context 内已有 `g.csp_nonce` 时直接返回现有 nonce，不调用
  `secrets.token_urlsafe(16)`；
- request context 内缺 nonce 时仍生成临时 secure nonce；
- 非 request context 时仍生成 fresh fallback nonce；
- `has_request_context()` 自身抛 `RuntimeError` 时仍落到 secure fallback；
- patch target 从 `flask.has_request_context` 变成
  `ai_intervention_agent.web_ui_security.has_request_context`，测试同步锁住。

新增 / 更新测试：

- `tests/test_csp_nonce_has_request_context_binding_r656.py`
  - source invariant 锁定 `_get_csp_nonce()` 内不再有 local import；
  - source invariant 锁定模块级 Flask import 包含 `has_request_context`；
  - runtime 覆盖已有 request nonce 不调用 `token_urlsafe`；
  - runtime 覆盖模块级 `has_request_context` 抛 `RuntimeError` 后 fallback；
- `tests/test_web_ui_security_gaps_r39.py`
  - RuntimeError 测试 patch target 改为模块级绑定，注释同步更新。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round183/00-doctor.json`
  保存本轮 smart-search 诊断；本机 OpenAI-compatible chat smoke 返回 HTTP 400，
  因此 `ok: false`，但 capability status 显示 docs/web_fetch、Exa、Context7
  可用，本轮证据使用后两项；
- `/tmp/smart-search-evidence/aiia-optimization-round183/01-exa-python-import-name-binding.json`
  保存 Python import / name binding / `sys.modules` cache 相关资料；
- `/tmp/smart-search-evidence/aiia-optimization-round183/02-exa-flask-has-request-context.json`
  保存 Flask request context / `has_request_context` 相关资料。

验证：

- `uv run pytest tests/test_csp_nonce_has_request_context_binding_r656.py
  tests/test_web_ui_security_gaps_r39.py tests/test_feat_csp_nonce_consistency_r306.py
  tests/test_csp_template_precompute_r23_5.py tests/test_csp_allows_importmap_nonce.py
  tests/test_web_ui_config.py tests/test_feat_security_headers_strict_mode_r376.py
  tests/test_feat_csp_directive_completeness_r386.py`
  → 344 passed, 89 subtests passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_security.py
  tests/test_csp_nonce_has_request_context_binding_r656.py
  tests/test_web_ui_security_gaps_r39.py`；
- `uv run ty check tests/test_csp_nonce_has_request_context_binding_r656.py`；
- local `timeit` smoke：request context 内设置 `g.csp_nonce = "abc123"`，
  500,000 calls、7 repeats，old local-import helper vs imported R656
  `_get_csp_nonce()`，contract equality 为 `True`：
  - old local import best `0.246754s`；
  - new module binding best `0.183465s`（`1.345x`）；
  - old/new median `0.248661s → 0.185011s`。

测过但拒绝的替代方案：

- `ConfigManager.get_section()` 把 local `import copy` 改成 module-level
  `deepcopy`：isolated benchmark 仅约 `1.02x`
  (`0.4579s → 0.4471s` for 200k)，真实路径由 deepcopy 主导，ROI 低；
- `NotificationManager.get_status()` 增加 int fast-path helper：helper 版更慢，
  old top `0.227s` vs helper `0.275s`，old provider `0.277s` vs helper
  `0.355s`；
- `web_ui_validators.DEFAULT_ALLOWED_NETWORKS.copy()` 默认路径频率低，且不是当前
  hot path，本轮不落地。

### 3.200 R657 · `/metrics` 复用 MCP metrics module 绑定

发现：

`web_ui_routes/system.py::_render_prometheus_metrics()` 在每次 Prometheus scrape
里分别为 MCP tool call counter 和 MCP latency histogram 执行两次 local import：

```python
from ai_intervention_agent.mcp_tool_call_metrics import get_mcp_tool_call_stats
from ai_intervention_agent.mcp_tool_call_metrics import get_mcp_tool_call_latency_snapshot
```

Python 会先查 `sys.modules`，所以这不是冷导入成本；但 import statement 仍要做
module lookup 和 local name binding。`/metrics` 是周期 scrape 路径，且两段 import
指向同一个模块。R657 增加 `_get_mcp_tool_call_metrics_module()`：

- 首次成功时缓存 `ai_intervention_agent.mcp_tool_call_metrics` module object；
- import 失败时返回 `None` 且不污染 cache，下次 scrape 仍会重试；
- `_render_prometheus_metrics()` 每次 scrape 只查一次 module；
- counter snapshot 和 latency snapshot 仍是两个独立 `try/except`，counter 失败
  不影响 latency，latency 失败也不影响 counter；
- 不做 eager module-level import，避免把 `fastmcp.server.middleware` 链路提前拖入
  Web UI route import，也保留原来的 `/metrics` fail-soft 边界。

新增测试：

- `tests/test_metrics_mcp_module_cache_r657.py`
  - cached module 命中时不再触发 `__import__`；
  - import failure 不污染 cache，后续成功 import 仍可缓存；
  - `_render_prometheus_metrics()` 对 MCP metrics module 只做一次 lookup；
  - counter snapshot failure 仍允许 latency histogram 输出；
  - latency snapshot failure 仍允许 counter 输出；
  - source invariant 锁定 `_render_prometheus_metrics()` 不再直接两次
    `from ai_intervention_agent.mcp_tool_call_metrics import ...`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round184/00-doctor.json`
  保存本轮 smart-search 诊断；OpenAI-compatible chat smoke 超时导致 `ok: false`，
  但 `minimum_profile_ok: true`，且 Exa / Context7 / web_fetch capability 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round184/01-exa-python-import-cache.json`
  保存 Python 官方 import system 资料：`import` statement 组合 module search 与
  name binding；`sys.modules` 是已导入 module cache。

验证：

- `uv run pytest tests/test_metrics_mcp_module_cache_r657.py
  tests/test_mcp_tool_call_metrics_r187.py tests/test_prom_histogram_r190.py
  tests/test_prom_family_iterables_r518.py
  tests/test_prom_histogram_bucket_empty_singleton_fastpath_r641.py
  tests/test_prom_histogram_bucket_pair_fastpath_r642.py
  tests/test_mcp_latency_inf_bucket_constant_r650.py`
  → 67 passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_routes/system.py
  tests/test_metrics_mcp_module_cache_r657.py`；
- `uv run ty check tests/test_metrics_mcp_module_cache_r657.py`；
- local `timeit` smoke：imported module 中预置 1 个 MCP counter + 1 个 latency
  series，200,000 calls、7 repeats，old two-local-import helper vs R657 cached
  module path，contract equality 为 `True`：
  - old two local imports best `0.225775s`；
  - new cached module best `0.124295s`（`1.816x`）；
  - old/new median `0.226095s → 0.127829s`。

测过但拒绝的替代方案：

- 只把两段 local import 合并成一次 `from ai_intervention_agent import
  mcp_tool_call_metrics as module`：scratch benchmark 约 `1.069x`
  (`0.670909s → 0.627626s` for 500k)，能省一次 import statement 但仍每次
  scrape 执行 import；
- eager module-level import `mcp_tool_call_metrics`：能更短，但会改变 Web UI
  route import 的冷启动 / 可选依赖失败边界，本轮拒绝；
- latency bucket template `.copy()`：R651 已锁独立 bucket dict，避免不同 series
  共享同一 mutable bucket map，不能为了省首样本成本破坏别名安全。

### 3.201 R658 · backend i18n 语言检测复用 Flask request proxy

发现：

`i18n.detect_request_lang()` 是后端 `msg(...)` 未显式传 `lang` 时的语言检测
helper，反馈 / 通知 / 任务路由错误文案都会走到它。旧实现每次调用都在函数体内：

```python
from flask import request
primary = accept.split(",")[0].split(";")[0].strip()
```

这有两点 hot-path 开销：

- Flask `request` 是稳定的 `LocalProxy`，每次重新执行 import statement 只是在
  已导入模块上重复 lookup + local name binding；
- `split(",")` / `split(";")` 会生成 list，但这里永远只需要第一个 token。

R658 在模块加载时尝试绑定 Flask request proxy：

```python
try:
    from flask import request as _flask_request
except ImportError:
    _flask_request = None
```

然后 request hot path 复用该 proxy，并用 `partition()` 取第一个逗号 / 分号前缀：

```python
primary = accept.partition(",")[0].partition(";")[0].strip()
```

收益与边界：

- request context + `Accept-Language` 命中时不再执行 local Flask import；
- header 解析不再为逗号和分号拆分生成完整 list；
- 不在 request context 时，`LocalProxy` 访问仍抛 `RuntimeError`，继续落到 config
  fallback；
- Flask 不可导入时 `_flask_request is None`，仍走 config fallback；
- `web_ui.language != "auto"` 的 config fallback 保持 lazy import，不把
  `config_manager` 提前拖入 i18n 模块；
- primary-token 语义保持不变：`fr-FR,zh-CN;q=0.9` 仍按旧逻辑先 normalize primary
  为默认 `en`，不会扫描 secondary language。

新增测试：

- `tests/test_i18n_detect_request_lang_fastpath_r658.py`
  - source invariant 锁定 `detect_request_lang()` 内没有 `from flask import request`；
  - source invariant 锁定 hot path 使用 chained `partition()`，不再出现 `.split(`；
  - runtime 覆盖 request header 短路 config；
  - runtime 覆盖 secondary values 不改变旧 primary-only 语义；
  - runtime 覆盖非 request context 仍 fallback 到 config；
  - runtime 覆盖 `_flask_request is None` 时仍 fallback 到 config；
  - runtime 覆盖 `language=auto` 和 config 异常时仍返回默认 `en`。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round185/00-doctor.json`
  保存本轮 smart-search 诊断；OpenAI-compatible chat smoke 仍超时导致
  `ok: false`，但 `minimum_profile_ok: true`，Exa / Context7 / web_fetch
  capability 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round185/01-exa-python-partition-import.json`
  保存 Python string `partition` / `split` 与 import 相关资料；该次 Exa
  返回的 stdtypes 命中包含旧版本 docs 页面，所以只作为发现线索；
- `/tmp/smart-search-evidence/aiia-optimization-round185/02-fetch-python-str-partition.json`
  与 `/tmp/smart-search-evidence/aiia-optimization-round185/03-fetch-python-import.json`
  记录直接 fetch Python 3 docs 时 Tavily/Firecrawl 均返回 empty，不能作为
  claim 依据；
- `/tmp/smart-search-evidence/aiia-optimization-round185/04-exa-python3-stdlib-import.json`
  保存 source-directed Exa 结果，包含 Python 3 import system 文档：
  import statement 会执行 search + name binding，`sys.modules` 是已导入 module
  cache；`partition` / `split` 的具体收益由本地 benchmark 锁定。

验证：

- `uv run pytest tests/test_i18n_detect_request_lang_fastpath_r658.py
  tests/test_i18n_normalize_lang_csrf_r72d.py tests/test_feat_zhtw_locale.py
  tests/test_bug2_config_changed_toast_i18n.py`
  → 46 passed, 70 subtests passed；
- `uv run ruff check src/ai_intervention_agent/i18n.py
  tests/test_i18n_detect_request_lang_fastpath_r658.py`；
- `uv run ty check tests/test_i18n_detect_request_lang_fastpath_r658.py`；
- local `timeit` smoke：Flask request context 内设置
  `Accept-Language: zh-CN,zh;q=0.9,en;q=0.8`，500,000 calls、7 repeats，
  old local-import + split helper vs imported R658 `detect_request_lang()`，
  contract equality 为 `True`：
  - old local import + split best `0.441762s`；
  - new module proxy + partition best `0.344623s`（`1.282x`）；
  - old/new median `0.443480s → 0.346369s`。

测过但拒绝的替代方案：

- 缓存 `config_manager.get_config` 绑定：会让测试 patch / runtime config reload
  边界更难推理，而且该路径只在缺 request header 或 request context 外触发；
- eager import `config_manager`：会扩大 i18n 模块冷启动依赖，本轮拒绝；
- 扫描 `Accept-Language` 的 secondary language 以选择第一个支持项：也许 UX 更好，
  但会改变现有 primary-only 语义，不属于本轮纯性能优化；
- 把 `SUPPORTED_LANGS` 改成 set：只有 3 个元素，benchmark 贡献不可测，且 tuple
  对文档顺序更直观。

### 3.202 R659 · `/api/get-feedback-prompts` 复用 prompt 依赖绑定

结论：已落地。`/api/get-feedback-prompts` 是 settings page / fallback 会重复调用
的 safe + idempotent GET route。旧实现每次请求都执行：

- `from ai_intervention_agent.config_utils import truncate_string`
- `from ai_intervention_agent.server_config import AUTO_RESUBMIT_TIMEOUT_DEFAULT,
  PROMPT_MAX_LENGTH`

Python 官方 import 文档说明 import statement 会执行 module search + name binding；
`sys.modules` 是已导入 module cache，命中后不会重新加载 module，但每次
`from ... import ...` 仍要走 import machinery 和本地绑定。本轮把这三个依赖
收进 `_get_feedback_prompt_route_deps()` 的 first-touch tuple cache：

- 首次 GET 仍 lazy import `server_config`，不扩大 `notification.py` cold-start；
- 后续 GET 只做一次 global cache 读取和 tuple 返回；
- POST `/api/update-feedback-config` 与 reset route 保持原本低频 local import
  结构，避免扩大变更面。

实现：

- `src/ai_intervention_agent/web_ui_routes/notification.py`
  - 新增 `_FEEDBACK_PROMPT_ROUTE_DEPS`；
  - 新增 `_get_feedback_prompt_route_deps()`；
  - `get_feedback_prompts_api()` 改为从 helper 取
    `truncate_string` / `AUTO_RESUBMIT_TIMEOUT_DEFAULT` / `PROMPT_MAX_LENGTH`。
- `tests/test_feedback_prompts_dependency_cache_r659.py`
  - 锁定 cached tuple 命中时不再调用 `__import__`；
  - 锁定 route 仍对 malformed `frontend_countdown` fallback 到默认值，并用
    cached `PROMPT_MAX_LENGTH` 截断两个 prompt 字段。

benchmark：

```text
uv run python - <<'PY'
...
PY

old local imports best        0.5137403340195306s / 1,000,000 calls
new actual cached helper best 0.03241658298065886s / 1,000,000 calls
ratio                         15.848x
```

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round186/00-doctor.json`
  保存本轮 smart-search 诊断；`ok: true`，minimum profile 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round186/01-python-import-cache-exa.json`
  保存 source discovery，命中 Python import system 官方文档；
- `/tmp/smart-search-evidence/aiia-optimization-round186/02-python-import-doc-fetch.json`
  记录直接 fetch `https://docs.python.org/3/reference/import.html` 时 Tavily /
  Firecrawl 均返回 empty，本文件仅作为失败证据；
- `/tmp/smart-search-evidence/aiia-optimization-round186/03-python-import-doc-exa-text.json`
  保存 Exa include-text 结果，来自 `docs.python.org`，包含 import statement
  执行 search + name binding、`sys.modules` module cache 等依据。

验证：

- `uv run pytest tests/test_feedback_prompts_dependency_cache_r659.py -q`
  → 2 passed；
- `uv run pytest tests/test_feedback_prompts_dependency_cache_r659.py
  tests/test_web_ui_routes.py tests/test_web_ui_config.py
  tests/test_notification_lazy_import.py
  tests/test_feat_get_endpoint_idempotency_r322.py -q`
  → 425 passed, 8 subtests passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_routes/notification.py
  tests/test_feedback_prompts_dependency_cache_r659.py`；
- `uv run ty check tests/test_feedback_prompts_dependency_cache_r659.py`。

拒绝项：

- 把 `server_config` constants 改为 module-level eager import：会扩大
  `notification.py` cold-start dependency，违背 R20.10 lazy route 设计；
- 同时缓存 `get_config()`：该 helper 被测试和 runtime patch 边界使用，收益与风险
  不如 prompt dependency tuple 明确；
- 改动 POST/reset 路由：低频写路径，当前 local import 更直观，且能限制本轮 blast
  radius。

### 3.203 R660 · X-Forwarded-For 首值解析改用 `partition`

结论：已落地。`SecurityMixin._parse_forwarded_for()` 同时服务两条请求热路径：

- `SecurityMixin._get_request_client_ip()`，用于每次访问控制判断；
- `WebUiRateLimiter._get_client_key()`，用于本机反代场景下按真实客户端 IP 分桶。

旧实现：

```python
return forwarded_for.split(",")[0].strip()
```

这里语义只需要逗号前的第一个值。`split(",")` 默认会扫描并拆出完整 list；
Python 3 文档说明 `str.partition(sep)` 只在第一次出现处分割并返回三元组，
更贴近这个需求。R660 改为：

```python
return forwarded_for.partition(",")[0].strip()
```

边界：

- 空字符串仍返回 `""`；
- 单个 IP 不变；
- 多跳 proxy list 仍取最左值；
- 前后空白仍通过 `.strip()` 清理；
- 信任边界不变：只有 `_should_trust_forwarded_for(remote_addr)` 为 true
  时才会读取 XFF，远端伪造 XFF 仍被忽略。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round187/00-doctor.json`
  保存本轮 smart-search 诊断；`ok: true`，minimum profile 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round187/02-mdn-x-forwarded-for-exa.json`
  保存 MDN 资料：X-Forwarded-For 是逗号分隔的 `<client>, <proxy1>,
  <proxy2>` 列表，并强调用于安全 / rate limiting 时必须只信任受信任代理添加
  的值；
- `/tmp/smart-search-evidence/aiia-optimization-round187/03-python3-str-partition-split-exa.json`
  保存 Python 3 string method 文档：`partition` 在首次分隔符处返回三元组；
  `split` 返回 list，未指定 `maxsplit` 时会执行全部拆分。

验证：

- `uv run pytest tests/test_forwarded_for_partition_fastpath_r660.py
  tests/test_web_ui_config.py::TestGetRequestClientIp
  tests/test_web_ui_config.py::TestShouldTrustForwardedForEdge
  tests/test_web_ui_security_gaps_r39.py tests/test_network_security_config.py
  tests/test_lazy_flask_limiter_r26_1.py -q`
  → 152 passed, 20 subtests passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_security.py
  tests/test_forwarded_for_partition_fastpath_r660.py`；
- `uv run ty check tests/test_forwarded_for_partition_fastpath_r660.py`；
- local `timeit` smoke：2,000,000 calls、9 repeats，old split helper vs imported
  R660 `SecurityMixin._parse_forwarded_for()`：
  - single value：`0.088166s → 0.076681s`（`1.150x`）；
  - two values：`0.118467s → 0.106688s`（`1.110x`）；
  - six values：`0.197382s → 0.108864s`（`1.813x`）。

新增测试：

- `tests/test_forwarded_for_partition_fastpath_r660.py`
  - source invariant 锁定 parser 使用 `.partition(` 且不再使用 `.split(`；
  - runtime 覆盖空值、单值、多跳 proxy list、IPv6 + whitespace。

拒绝项：

- `split(",", 1)[0]`：也能限制拆分次数，但仍返回 list；`partition` 的返回结构
  与“只需要首次分隔符前后两侧”更匹配；
- 更改 XFF trust algorithm 为从右侧按 trusted proxy count / range 选择：MDN
  文档建议安全用途需要完整代理拓扑配置，但本项目现有契约是“仅本机反代时信任
  XFF 首值”，改算法会改变部署语义，不属于本轮性能优化；
- 在 rate limiter 中复制一份 parser：会分叉安全语义；继续复用
  `SecurityMixin._parse_forwarded_for()`。

### 3.204 R661 · 未信任远端不读取 X-Forwarded-For

结论：已落地。R660 已把 XFF 首值解析从 `split` 改为 `partition`，但两条
请求热路径仍在判断远端是否可信之前读取 XFF：

- `SecurityMixin._get_request_client_ip()`：
  `str(environ.get("HTTP_X_FORWARDED_FOR", "")).strip()`；
- `WebUiRateLimiter._client_key()`：
  `request.headers.get("X-Forwarded-For", "")`。

旧语义下，即使 `REMOTE_ADDR` 是非 loopback 远端客户端，代码也会先读取 /
规范化一个本来必须忽略的 spoofed XFF header，再由
`_should_trust_forwarded_for(remote_addr)` 决定不使用它。R661 把读取动作移动到
trust gate 之后：

```python
remote_addr = str(environ.get("REMOTE_ADDR", "")).strip()
if self._should_trust_forwarded_for(remote_addr):
    forwarded_for = str(environ.get("HTTP_X_FORWARDED_FOR", "")).strip()
    ...
```

以及 limiter：

```python
if SecurityMixin._should_trust_forwarded_for(remote_addr):
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    ...
```

收益与边界：

- 远端非 loopback 请求不再读取 / strip 被忽略的 XFF；
- padded / long spoofed XFF 的无效输入成本被挡在 trust gate 外；
- 本机反代（loopback `REMOTE_ADDR`）仍读取并解析 XFF；
- 空 XFF、直接连接、loopback proxy、spoofed remote XFF 的行为不变；
- 这不是 XFF 信任算法重写，只是让实现顺序和现有 trust contract 更一致。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round188/00-doctor.json`
  保存本轮 smart-search 诊断；`ok: true`，minimum profile 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round188/01-mdn-x-forwarded-for-trust-exa.json`
  保存 MDN Forwarded / XFF 资料：代理链信息可能被添加、修改或删除，且 XFF 是
  de-facto header；
- `/tmp/smart-search-evidence/aiia-optimization-round188/02-owasp-xff-spoofing-exa.json`
  保存 OWASP IP Spoofing via HTTP Headers 资料：客户端 IP 会影响 access control
  与 rate limits，信任 `X-Forwarded-For` 等客户端可控 header 会导致伪造风险。

验证：

- `uv run pytest tests/test_forwarded_for_lazy_read_r661.py
  tests/test_forwarded_for_partition_fastpath_r660.py
  tests/test_web_ui_config.py::TestGetRequestClientIp
  tests/test_network_security_config.py::TestRequestClientIpResolution
  tests/test_lazy_flask_limiter_r26_1.py -q`
  → 22 passed, 6 subtests passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_security.py
  src/ai_intervention_agent/web_ui_rate_limiter.py
  tests/test_forwarded_for_lazy_read_r661.py`；
- `uv run ty check tests/test_forwarded_for_lazy_read_r661.py`；
- local `timeit` smoke：1,000,000 calls、9 repeats，old eager-XFF helper vs imported
  R661 `_get_request_client_ip()`：
  - remote padded spoofed XFF：`1.078313s → 0.976850s`（`1.104x`）；
  - remote plain spoofed XFF：`0.992606s → 0.973456s`（`1.020x`）；
  - loopback trusted XFF：`1.218087s → 1.204219s`（`1.012x`，无回退）。

新增测试：

- `tests/test_forwarded_for_lazy_read_r661.py`
  - untrusted remote path 用 tracking environ 锁定不读取
    `HTTP_X_FORWARDED_FOR`；
  - loopback trusted path 仍读取 XFF 且返回 forwarded client IP；
  - limiter `_client_key` source invariant 锁定 header read 在 trust check 之后。

拒绝项：

- 完整改成 trusted proxy count / CIDR list 从右侧选择 XFF：MDN 推荐这种安全模型，
  但需要新增部署配置与迁移语义，不属于本轮“保持现有契约”的性能优化；
- 删除 XFF 支持：会破坏本机反代和测试中已锁定的 loopback proxy 行为；
- 只优化 access-control path、不改 limiter：两者共享同一安全边界，保持顺序一致
  更容易审计。

### 3.205 R662 · rate limiter prune 缓存 limit period 解析

结论：已落地。`WebUiRateLimiter._prune_expired_buckets()` 旧实现每次扫描
bucket 时都会对 `bucket_key[2]` 中的 raw limit 字符串重新执行 `_parse_limit()`：

```python
if window_start + _parse_limit(bucket_key[2]).period_seconds <= now
```

bucket key 只保存 `(scope, client_key, spec.raw)`，因此同一个 limiter 中通常只有
少量 raw spec（例如 `1 per second`、`10 per minute`、`100 per hour`），但 bucket
数量会随 client / endpoint 组合增长。R662 增加一个有界 helper：

```python
@lru_cache(maxsize=32)
def _limit_period_seconds(raw: str) -> int:
    return _parse_limit(raw).period_seconds
```

并让 prune 只缓存不可变的 `int` period seconds，避免共享 `_LimitSpec` 可变对象。

收益与边界：

- prune 扫描不再为每个 bucket 重复 strip / lower / split / int / dict lookup；
- cache 以 raw spec 字符串为 key，`maxsize=32`，不会在长期 Web 进程中无限增长；
- `_buckets` 的现有私有形状仍是
  `dict[tuple[str, str, str], tuple[int, int]]`，既有测试和调试入口不需要迁移；
- 无请求语义变化：window 计算、remaining、reset、429 response、headers 均不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round189/00-doctor.json`
  保存本轮 smart-search 诊断；`ok: true`，minimum profile 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round189/01-python-functools-lru-cache-exa.json`
  保存 Python 官方 `functools.lru_cache` 文档检索结果：`lru_cache` 会保存最近
  调用结果，可在相同参数重复调用昂贵函数时节省时间，且 size limit 避免 web
  server 这类长期进程中无限增长；
- `/tmp/smart-search-evidence/aiia-optimization-round189/02-python-functools-cache-exa.json`
  保存同一官方文档的补充检索结果，包含“只应缓存需要复用的已计算值、不要缓存
  需要返回不同 mutable object 的函数”等约束；本轮只缓存 `int`；
- `/tmp/smart-search-evidence/aiia-optimization-round189/03-python-functools-lru-cache-fetch.json`
  和 `04-python-functools-fetch.json` 记录了 fetch provider 对官方 Python 文档
  提取失败（Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_rate_limiter_prune_period_cache_r662.py
  tests/test_lazy_flask_limiter_r26_1.py tests/test_forwarded_for_lazy_read_r661.py -q`
  → 14 passed, 6 subtests passed；
- `uv run pytest tests/test_ratelimit_headers_r57.py
  tests/test_web_ui_config.py::TestGetRequestClientIp
  tests/test_network_security_config.py::TestRequestClientIpResolution -q`
  → 17 passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_rate_limiter.py
  tests/test_rate_limiter_prune_period_cache_r662.py`；
- `uv run ty check tests/test_rate_limiter_prune_period_cache_r662.py`；
- local `timeit` smoke：15,000 buckets、250 prune scans、9 repeats，old reparsing
  helper vs imported R662 `_limit_period_seconds()`：
  - old：`1.038857s`；
  - R662：`0.140472s`；
  - speedup：`7.40x`；
  - cache info：`CacheInfo(hits=33764997, misses=3, maxsize=32, currsize=3)`。

新增测试：

- `tests/test_rate_limiter_prune_period_cache_r662.py`
  - monkeypatch `_parse_limit` 计数，确认 80 个 bucket / 2 种 raw limit 只解析
    2 次，第二轮扫描不再新增 parse；
  - source invariant 锁定 prune 使用 `_limit_period_seconds(bucket_key[2])`，且
    保持 `(window_start, _count)` bucket value 解包形状。

拒绝项：

- 直接给 `_parse_limit()` 加 `lru_cache`：会缓存并共享 `_LimitSpec` 实例；虽然内部
  目前不会修改它，但它不是 frozen dataclass，缓存 `int` 更窄；
- 把 period seconds 写入 bucket value：可减少 lookup，但会迁移私有 bucket 形状，
  影响现有测试和调试代码，收益不值得；
- 手写 module-level dict cache：bench 中略慢于 `lru_cache`，且需要额外处理大小上限。

### 3.206 R663 · rate limiter decision 选择不再物化 list

结论：已落地。`WebUiRateLimiter._check_limits()` 旧实现会为每次请求创建
`decisions` list，逐个 append `_LimitDecision`，最后再执行：

```python
decision = min(decisions, key=lambda item: (item.remaining, item.reset_at))
```

现有路由画像：

- 所有显式 `@self.limiter.limit("...")` route 都是单个 spec；
- default limits 是两个 spec：`60 per minute` 和 `10 per second`。

因此旧写法在最常见的 single-spec route 上仍会分配 list、append 一次、构造 lambda
key 并调用 `min()` 做第二步选择；在 default path 上也会多一次 list materialization
和 `min()` pass。R663 改为在写 bucket 的同一个 loop 中维护当前最严格 decision：

```python
decision: _LimitDecision | None = None
...
if decision is None or (
    current_decision.remaining,
    current_decision.reset_at,
) < (
    decision.remaining,
    decision.reset_at,
):
    decision = current_decision
```

收益与边界：

- 不再为每次 request 分配 `decisions` list；
- 不再为选择结果额外调用 `min(..., key=lambda ...)`；
- 仍保持原选择规则：`remaining` 最小优先，`reset_at` 更早作为 tie-breaker；
- single-spec route 和 two-spec default limits 行为一致；
- `g._aiia_rate_limit_decision`、429 JSON、`X-RateLimit-*`、`Retry-After` 语义不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round190/00-doctor.json`
  保存本轮 smart-search 诊断；`ok: true`，minimum profile 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round190/01-python-min-key-exa.json`
  保存 Python 官方 sorting how-to：`min()` 支持 `key`，key function 会对每条输入
  record 调用一次；`min()` / `max()` 是 single pass 且几乎不需要辅助内存，但本轮
  的输入已经在同一 loop 中产生，可以在生成时直接比较；
- `/tmp/smart-search-evidence/aiia-optimization-round190/02-python-list-append-exa.json`
  保存 Python 官方 data structures 文档：`list.append(value)` 会把 item 加到 list
  末尾，list 是 mutable data structure；本轮避免为中间 decisions 创建该容器；
- `/tmp/smart-search-evidence/aiia-optimization-round190/03-python-sorting-key-fetch.json`
  和 `04-python-list-fetch.json` 记录 fetch provider 对官方 Python 文档提取失败
  （Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_rate_limiter_streaming_decision_r663.py
  tests/test_rate_limiter_prune_period_cache_r662.py
  tests/test_lazy_flask_limiter_r26_1.py tests/test_ratelimit_headers_r57.py -q`
  → 23 passed, 6 subtests passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_rate_limiter.py
  tests/test_rate_limiter_streaming_decision_r663.py`；
- `uv run ty check src/ai_intervention_agent/web_ui_rate_limiter.py
  tests/test_rate_limiter_streaming_decision_r663.py`；
- local `timeit` smoke：500,000 iterations、9 repeats，old list+min helper vs
  R663 streaming helper：
  - single route spec：`0.292604s → 0.228251s`（`1.282x`）；
  - default two specs：`0.522695s → 0.459385s`（`1.138x`）。

新增测试：

- `tests/test_rate_limiter_streaming_decision_r663.py`
  - source invariant 锁定 `_check_limits` 不再出现 `decisions` list、`.append(`、
    `min(decisions...)`，并使用 `current_decision`；
  - runtime 覆盖 two-spec default limit 仍选择 `10 per second` 为最 constrained
    decision；
  - 11 次同 window 请求后仍返回 429 和 `{"error": "rate_limit_exceeded"}`，并保留
    denied decision 的 headers 数据来源。

拒绝项：

- 对 single-spec route 写完全独立 fast path：可以再少一次比较，但会复制 bucket
  更新逻辑；当前 streaming 写法同时优化 single / multi spec，代码更小；
- 保留 list 但把 `lambda` 换成 `operator.attrgetter`：只能减少 key callable 成本，
  不能消除 list 分配和第二步选择；
- 提前在 decorator 阶段把 specs 标成 single/multi：会扩大状态面，收益不如当前
  局部 rewrite 明确。

### 3.207 R664 · recent logs 常用 tail limit 避免完整 ring list copy

结论：已落地。`enhanced_logging.get_recent_logs(limit=N)` 旧实现总是先复制完整
ring：

```python
with _log_ring_lock:
    snapshot = list(_log_ring)
if limit is not None and limit > 0:
    snapshot = snapshot[-limit:]
```

ring 上限是 200 条；两个真实热调用点是：

- `server_info_resource` 聚合 recent logs：`limit=20`；
- HTTP `GET /api/system/recent-logs` 默认：`limit=50`。

因此这两条路径旧实现会先复制最多 200 条，再切出 20 / 50 条。R664 对这两个
明确 call-site limit 使用：

```python
list(itertools.islice(_log_ring, ring_len - limit, ring_len))
```

只物化返回 tail。`limit=None` 和 `limit <= 0` 继续直接复制完整 ring；其它正数
limit 继续走旧的 full-copy + slice 语义，避免把优化扩散到未证明收益的输入。

收益与边界：

- `limit=20` server-info path 少分配 180 个 list slot；
- `limit=50` recent-logs endpoint 默认 path 少分配 150 个 list slot；
- 返回顺序仍是旧 → 新；
- `limit=None`、`limit=0`、`limit > len(ring)` 行为不变；
- 返回 list 仍是独立容器；条目 dict 仍是原有浅拷贝语义（不新增 deep copy）；
- 任意正数 limit（如 100/199/999）仍支持，但不走 islice fast path；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round191/00-doctor.json`
  保存本轮 smart-search 诊断；`ok: true`，minimum profile 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round191/01-python-itertools-islice-exa.json`
  保存 Python 官方 `itertools.islice` 文档：`islice` 返回 selected elements
  iterator，`start` 非零时会跳过直到 start，之后连续返回元素；
- `/tmp/smart-search-evidence/aiia-optimization-round191/02-python-deque-index-exa.json`
  保存 Python 官方 `collections.deque` 文档：deque 两端 append/pop 是 O(1)，但
  indexed access 只有两端 O(1)，中间会退化到 O(n)，因此本轮拒绝直接下标 tail；
- `/tmp/smart-search-evidence/aiia-optimization-round191/03-python-itertools-islice-fetch.json`
  和 `04-python-deque-fetch.json` 记录 fetch provider 对官方 Python 文档提取失败
  （Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_recent_logs_islice_tail_r664.py
  tests/test_log_ring_buffer_r51c.py tests/test_recent_logs_endpoint_r52b.py -q`
  → 32 passed；
- `uv run pytest tests/test_recent_logs_islice_tail_r664.py
  tests/test_log_ring_buffer_r51c.py tests/test_recent_logs_endpoint_r52b.py
  tests/test_recent_logs_aggregation_r55.py
  tests/test_recent_logs_cache_sidecar_key_r655.py -q`
  → 49 passed；
- local `timeit` smoke：200-entry deque、200,000 calls、9 repeats，old full-copy
  + slice vs R664:
  - `limit=20`：`0.141047s → 0.130054s`（`1.085x`）；
  - `limit=50`：`0.143899s → 0.143489s`（`1.003x`）；
  - `limit=None`：`0.129167s → 0.127520s`（`1.013x`）；
  - `limit=0`：`0.129943s → 0.128746s`（`1.009x`）；
  - non-call-site positive limits still take the old copy/slice fallback but pay
    a small branch cost in this synthetic benchmark:
    `limit=100` `0.965x`、`199` `0.974x`、`200` `0.966x`、`999` `0.976x`。

新增测试：

- `tests/test_recent_logs_islice_tail_r664.py`
  - `limit=50` + full 200-entry ring uses `itertools.islice` and returns
    `msg-150..msg-199` in order；
  - `limit=100` keeps the full snapshot path and does not call `islice`；
  - source invariant 锁定 fast path 只针对
    `_LOG_RING_SERVER_INFO_LIMIT` / `_LOG_RING_ENDPOINT_DEFAULT_LIMIT`。

拒绝项：

- 直接用 deque indexing 取 tail：Python 官方文档说明 deque 中间 index 会退化到
  O(n)，benchmark 中 `limit=50` 已比 full-copy 慢；
- 对任意 `limit < len/4` 使用 `islice`：`limit=20/50` 更通用，但所有其它正数
  limit 都要先计算 ring length，给非 call-site 输入增加分支成本；
- `collections.deque(_log_ring, maxlen=limit)`：会遍历完整 ring，仅限制输出容量，
  benchmark 中显著慢于旧实现。

### 3.208 R665 · recent error aggregate 避免 full ring list copy

结论：已落地。R664 优化了 recent-log entry 返回路径，但 `/metrics` 和
`/api/system/health` 还有两处只需要“最近 5 分钟 ERROR/CRITICAL 数量”的聚合：

```python
recent = get_recent_logs()
error_count = sum(
    1
    for entry in recent
    if entry.get("level_no", 0) >= 40 and entry.get("ts_unix", 0) >= cutoff
)
```

这会在每次 Prometheus scrape / health probe 中先复制完整 200-entry ring，再做
一次计数。R665 在 `enhanced_logging` 增加：

```python
def get_recent_error_stats(cutoff_ts_unix: float) -> tuple[int, int]:
    ...
```

helper 在 `_log_ring_lock` 下直接遍历 `_log_ring`，返回
`(error_count, buffer_total)`。`/metrics` 只使用 `error_count`，
`/api/system/health` 同时复用 `buffer_total`，保持 payload 字段不变。

收益与边界：

- `/metrics` 不再为 `aiia_recent_errors_5min` 分配完整 recent-log list；
- `/api/system/health` 不再为 `checks.recent_errors` 分配完整 recent-log list；
- 仍只统计 `level_no >= logging.ERROR` 且 `ts_unix >= cutoff`；
- `buffer_total` 仍是当前 ring 长度，等价于旧 `len(recent)`；
- aggregate helper 不返回 entries，不改变 `/api/system/recent-logs` 和
  `server_info_resource` 的 entry 语义；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round192/00-doctor.json`
  保存本轮 smart-search 诊断；`ok: true`，minimum profile 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round192/01-python-deque-docs-exa.json`
  保存 Python 官方 `collections.deque` 文档检索结果：deque 支持 iteration、
  `len(d)`，并作为 bounded deque 适合追踪最近活动；
- `/tmp/smart-search-evidence/aiia-optimization-round192/02-python-sum-generator-exa.json`
  保存 Python builtins 官方文档检索结果；旧实现通过 iterable 聚合计数，本轮保留
  同一谓词但去掉前置 list materialization；
- `/tmp/smart-search-evidence/aiia-optimization-round192/03-python-deque-fetch.json`
  和 `04-python-sum-fetch.json` 记录 fetch provider 对官方 Python 文档提取失败
  （Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_recent_error_stats_r665.py
  tests/test_web_ui_routes_system.py::TestSystemHealthEndpoint
  tests/test_system_health_r121.py -q`
  → 47 passed, 3 subtests passed；
- `uv run ruff check src/ai_intervention_agent/enhanced_logging.py
  src/ai_intervention_agent/web_ui_routes/system.py
  tests/test_recent_error_stats_r665.py tests/test_web_ui_routes_system.py`；
- `uv run ty check src/ai_intervention_agent/enhanced_logging.py
  src/ai_intervention_agent/web_ui_routes/system.py
  tests/test_recent_error_stats_r665.py`；
- local `timeit` smoke：200-entry deque、300,000 calls、9 repeats，old
  `get_recent_logs()` + aggregate vs R665 direct aggregate：
  - `/metrics` count shape：`1.635225s → 1.537714s`（`1.063x`）；
  - health summary shape：`1.611217s → 1.527581s`（`1.055x`）。

新增测试：

- `tests/test_recent_error_stats_r665.py`
  - helper 在 `get_recent_logs` 被 monkeypatch 为抛异常时仍能直接扫描 ring；
  - source invariant 锁定 helper 在锁下遍历 `_log_ring`，不 `return list`；
  - `/metrics` runtime patch helper 返回 `7`，确认
    `aiia_recent_errors_5min 7`；
  - `/api/system/health` runtime patch helper 返回 `(3, 123)`，确认
    `count_last_5min` 与 `buffer_total` 保持 payload 契约；
  - source invariant 锁定两个 aggregate call site 都使用
    `get_recent_error_stats`。

拒绝项：

- 把 error count 维护成增量 counter：需要处理 5 分钟滑动窗口过期、ring overwrite
  和 clock jump，复杂度明显高于 200-entry scan；
- 让 `get_recent_logs(limit=0)` 返回空并用 `len(_log_ring)` 旁路：会破坏已有
  `limit<=0` 返回完整 buffer 的契约；
- 在 `/metrics` 和 health 内直接访问 `_log_ring`：会把锁与 ring 私有细节扩散到
  route 层，helper 更容易测试和审计。

### 3.209 R666 · server-info TTL cache hit 使用 dict.copy()

结论：已落地。`server_info_resource` 的 SSE stats 与 recent logs 子块都有
1 秒 TTL cache。命中 cache 时旧实现为了保证“返回新 dict，不泄漏内部 cache 引用”
使用：

```python
cached_copy = dict(_sse_stats_cache)
cached_copy = dict(_recent_logs_cache)
```

R666 改为对应 dict 实例的 `.copy()`：

```python
cached_copy = _sse_stats_cache.copy()
cached_copy = _recent_logs_cache.copy()
```

语义仍是浅拷贝；随后继续补 `cached=True` 与 `cache_age_s`。这个路径服务
sub-second self-info/status badge polling，cache hit 会远多于 miss，因此微小 copy
成本也值得收敛。

收益与边界：

- SSE stats cache hit 少走通用 `dict(mapping)` 构造路径；
- recent logs cache hit 同样少走通用 constructor；
- 返回值仍是新 dict，外部污染返回 dict 不会污染内部 cache；
- entries / emit_by_type 等 nested value 仍维持既有浅拷贝语义，不新增 deep copy；
- TTL、cache key、success-only write、`cached` / `cache_age_s` 字段不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round193/00-doctor.json`
  保存本轮 smart-search 诊断；OpenAI-compatible main search 超时，`ok=false`，
  但 Exa / Context7 capability 可用，本轮只采用 Exa official-domain docs 结果；
- `/tmp/smart-search-evidence/aiia-optimization-round193/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`dict.copy()` 返回 dictionary 的 shallow copy；
- `/tmp/smart-search-evidence/aiia-optimization-round193/02-python-dict-constructor-exa.json`
  保存 Python 官方文档检索结果：`dict()` constructor 可由 key-value pairs /
  mapping 构造 dictionary；旧实现依赖该通用构造路径；
- `/tmp/smart-search-evidence/aiia-optimization-round193/03-python-dict-copy-fetch.json`
  和 `04-python-dict-mapping-fetch.json` 记录 fetch provider 对官方 Python 文档
  提取失败（Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_server_cache_hit_copy_r666.py
  tests/test_sse_stats_cache_r54a.py tests/test_recent_logs_cache_sidecar_key_r655.py
  tests/test_recent_logs_aggregation_r55.py -q`
  → 32 passed；
- `uv run ruff check src/ai_intervention_agent/server.py
  tests/test_server_cache_hit_copy_r666.py
  tests/test_recent_logs_cache_sidecar_key_r655.py`；
- `uv run ty check src/ai_intervention_agent/server.py
  tests/test_server_cache_hit_copy_r666.py`；
- local `timeit` smoke：cache-hit copy shape、2,000,000 calls、9 repeats，old
  `dict(cache)` vs R666 `cache.copy()`：
  - SSE stats cache shape：`0.223490s → 0.206732s`（`1.081x`）；
  - recent logs cache shape：`0.117330s → 0.098702s`（`1.189x`）。

新增测试：

- `tests/test_server_cache_hit_copy_r666.py`
  - source invariant 锁定 `_fetch_sse_stats_cached` 使用
    `_sse_stats_cache.copy()` 且不再出现 `dict(_sse_stats_cache)`；
  - source invariant 锁定 `_fetch_recent_logs_cached` 使用
    `_recent_logs_cache.copy()` 且不再出现 `dict(_recent_logs_cache)`；
  - runtime 覆盖 SSE stats cache hit 返回 dict 仍与内部 cache 隔离；
  - runtime 覆盖 recent logs cache hit 返回 dict 仍与内部 cache 隔离。
- `tests/test_recent_logs_cache_sidecar_key_r655.py`
  - 更新 sidecar key source invariant，继续锁定 `_key` 不写进 cached payload。

拒绝项：

- 返回 `types.MappingProxyType` 或内部 cache 引用：会破坏“caller 可自由修改返回
  dict 且不污染 cache”的既有契约；
- 深拷贝 entries / emit_by_type：更隔离但成本大，且现有契约一直是 shallow copy；
- 用 `{**cache, "cached": True, ...}`：可读性可以，但 benchmark 中不是本轮胜出路径，
  且会把补充字段和 copy 绑定到一个表达式里，不如当前两步清晰。

### 3.210 R667 · latency histogram bucket snapshot 使用 dict.copy()

结论：已落地。MCP tool latency 与 notification provider latency 的 snapshot
路径都会在锁内复制内部 finite-bucket dict，然后追加 synthetic `+Inf` bucket：

```python
buckets_copy = state["buckets"].copy()
buckets_copy[_MCP_LATENCY_INF_BUCKET] = state["count"]
```

旧实现使用 `dict(state["buckets"])`。这两个 bucket state 都是普通 dict，
且形状固定、小而热（MCP 8 个有限桶，notification provider 使用自己的固定
有限桶模板），因此直接调用 dict 实例的 `.copy()` 可以避开通用 constructor
路径，同时保留既有浅拷贝语义。

收益与边界：

- MCP latency snapshot 每个 `(tool, status)` 少走一次通用 `dict(mapping)`；
- notification latency snapshot 每个 provider 少走一次通用 `dict(mapping)`；
- 返回的 top-level snapshot 与 nested `buckets` dict 仍是新对象，外部 mutation
  不污染内部 histogram state；
- `+Inf` bucket 仍由 snapshot helper 动态追加，值仍等于 `count`；
- 不改变 bucket 模板、计数、sum、Prometheus 输出顺序或标签；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round194/00-doctor.json`
  保存 smart-search 诊断；
- `/tmp/smart-search-evidence/aiia-optimization-round194/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`dict.copy()` 返回 dictionary 的 shallow copy；
- `/tmp/smart-search-evidence/aiia-optimization-round194/02-prometheus-histogram-exa.json`
  保存 Prometheus 官方 histogram 文档检索结果，支持本路径继续保留 bucket /
  `+Inf` / count 语义；
- `/tmp/smart-search-evidence/aiia-optimization-round194/03-python-dict-copy-fetch.json`
  与 `04-prometheus-histogram-fetch.json` 记录 fetch provider 对官方页面提取失败
  （Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_latency_histogram_bucket_copy_r667.py
  tests/test_mcp_latency_inf_bucket_constant_r650.py
  tests/test_notification_latency_inf_bucket_constant_r649.py
  tests/test_prom_histogram_r190.py
  tests/test_notification_latency_histogram_r191.py -q`
  → 50 passed；
- local `timeit` smoke：8-bucket histogram copy shape、1,000,000 calls、11 repeats，
  old `dict(buckets)` + `+Inf` vs R667 `buckets.copy()` + `+Inf`：
  - best：`0.069178s → 0.057007s`（`1.213x`）；
  - median：`0.069841s → 0.058521s`（`1.193x`）。

新增测试：

- `tests/test_latency_histogram_bucket_copy_r667.py`
  - source invariant 锁定 MCP snapshot 使用 `state["buckets"].copy()`，且不再出现
    `dict(state["buckets"])`；
  - source invariant 锁定 notification snapshot 使用 `state["buckets"].copy()`，
    且不再出现 `dict(state["buckets"])`；
  - runtime 覆盖 MCP snapshot 的 finite bucket 与 `+Inf` bucket mutation 不污染
    fresh snapshot；
  - runtime 覆盖 notification snapshot 的 finite bucket 与 `+Inf` bucket mutation
    不污染 fresh snapshot。

拒绝项：

- 返回内部 `state["buckets"]` 引用后再写 `+Inf`：会污染内部 finite-bucket state，
  且破坏 snapshot isolation；
- 使用 `types.MappingProxyType`：能防 mutation，但会改变 caller 可修改返回 dict 的
  既有契约；
- 深拷贝整个 histogram state：当前 value 全是 int / float 标量，深拷贝增加成本但
  不增加有效隔离。

### 3.211 R668 · build-info cache snapshot 使用 dict.copy()

结论：已落地。`server._resolve_build_info()` 第一次调用会 fork `git`
subprocess 解析 `git_commit` / `git_branch` / `git_dirty`，随后把结果缓存在
`_BUILD_INFO_CACHE`。后续 `server_info_resource`、system health build helper
和相关 observability 路径都应该只返回 cache 的浅拷贝，不再 fork subprocess。

旧实现的三个返回拷贝点使用 `dict(...)`：

```python
return dict(_BUILD_INFO_CACHE)
...
return dict(cache)
```

R668 改为直接调用 dict 实例方法：

```python
return _BUILD_INFO_CACHE.copy()
...
return cache.copy()
```

这个 cache payload 固定是 3 个 string 字段；`.copy()` 保留“返回新 dict、
caller mutation 不污染 module-level cache”的契约，同时避开通用 constructor
路径。第一次 cache-fill 返回也用 `cache.copy()`，避免把内部 cache dict 本体
交给 caller。

收益与边界：

- warm build-info cache hit 少走 `dict(mapping)` 通用构造路径；
- lock 内二次 cache-hit 分支同样使用 `.copy()`；
- 首次 cache-fill 返回值仍是新 dict，外部修改不污染 `_BUILD_INFO_CACHE`；
- git subprocess lazy cache、2s timeout、`unknown` graceful fallback 不变；
- health / server-info / metrics 的 build 字段形状不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round195/00-doctor.json`
  保存 smart-search 诊断；main search chat route 返回 HTTP 400 warning，
  但 Exa / Context7 / web_fetch capability 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round195/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`dict.copy()` 返回 dictionary 的 shallow copy；
- `/tmp/smart-search-evidence/aiia-optimization-round195/02-python-subprocess-exa.json`
  保存 Python 官方 subprocess 文档检索结果：`check_output` 运行命令并返回输出，
  非零退出抛 `CalledProcessError`，timeout 参数会触发 timeout 处理；这支撑
  保留当前 lazy cache + graceful fallback 的边界；
- `/tmp/smart-search-evidence/aiia-optimization-round195/03-python-dict-copy-fetch.json`
  与 `04-python-subprocess-fetch.json` 记录 fetch provider 对官方 Python 页面
  提取失败（Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_build_info_cache_copy_r668.py
  tests/test_server_info_build_block_r63.py
  tests/test_system_health_build_info_r132.py
  tests/test_web_ui_routes_system.py -q`
  → 70 passed；
- local `timeit` smoke：3-key build-info dict、2,000,000 calls、11 repeats，
  old `dict(cache)` vs R668 `cache.copy()`：
  - best：`0.088901s → 0.066396s`（`1.339x`）；
  - median：`0.091545s → 0.071181s`（`1.286x`）。

新增测试：

- `tests/test_build_info_cache_copy_r668.py`
  - source invariant 锁定 `_resolve_build_info()` 使用
    `_BUILD_INFO_CACHE.copy()` 和 `cache.copy()`，且不再出现
    `dict(_BUILD_INFO_CACHE)` / `dict(cache)`；
  - runtime 覆盖 warm cache hit 返回 dict mutation 不污染内部 cache；
  - runtime 覆盖首次 cache-fill 返回 dict mutation 不污染 fresh cache snapshot。

拒绝项：

- 直接返回 `_BUILD_INFO_CACHE`：最快但破坏 caller isolation，任何调用方 mutation
  都会污染全局 build cache；
- `MappingProxyType`：能防 mutation，但改变返回类型与既有 API 契约；
- 每次重新解析 git：比 copy 成本高几个数量级，而且会在 health / server-info
  轮询中制造 subprocess 风暴。

### 3.212 R669 · Web/Sound provider metadata snapshot 使用 dict.copy()

结论：已落地。`WebNotificationProvider.send()` 与
`SoundNotificationProvider.send()` 都会在写入 `web_notification_data` /
`sound_notification_data` 之前，把原始 `event.metadata` 复制进 payload 的
`metadata` 字段。这个 snapshot 的目的不是递归深拷贝，而是保留 provider
写回前的 top-level metadata 视图，避免新写入的 provider payload 自己出现在
自己的 metadata snapshot 里。

旧实现：

```python
metadata_copy = dict(event.metadata) if event.metadata else {}
```

R669 改为：

```python
metadata_copy = event.metadata.copy() if event.metadata else {}
```

`event.metadata` 是普通 dict；`.copy()` 保留同样的浅拷贝语义，同时避开
`dict(mapping)` 通用 constructor。顺手把旧注释里的“深拷贝”改为“浅拷贝”，
避免维护者误以为 nested metadata 会被递归复制。

收益与边界：

- Web notification payload metadata snapshot 少走一次通用 dict constructor；
- Sound notification payload metadata snapshot 同样少走一次通用 constructor；
- top-level snapshot 仍是新 dict，外部修改 payload metadata 不污染原始
  `event.metadata`；
- nested values 仍按既有浅拷贝语义共享引用，不额外 deep-copy；
- snapshot 仍发生在 provider payload 写回前，不包含 `web_notification_data` /
  `sound_notification_data` 自引用；
- Bark metadata 白名单转发路径不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round196/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round196/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`dict.copy()` 返回 dictionary 的 shallow copy；
- `/tmp/smart-search-evidence/aiia-optimization-round196/02-python-copy-module-exa.json`
  保存 Python 官方 `copy` 模块文档检索结果：shallow copy 会创建新 compound
  object，并插入原对象中成员的引用；deep copy 会递归复制，且可能复制过多或遇到
  recursive object 问题；
- `/tmp/smart-search-evidence/aiia-optimization-round196/03-python-dict-copy-fetch.json`
  与 `04-python-copy-module-fetch.json` 记录 fetch provider 对官方 Python 页面
  提取失败（Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_notification_provider_metadata_copy_r669.py
  tests/test_notification_providers.py -q`
  → 83 passed；
- local `timeit` smoke：6-key notification metadata dict、2,000,000 calls、
  11 repeats，old `dict(metadata)` vs R669 `metadata.copy()`：
  - best：`0.114900s → 0.087582s`（`1.312x`）；
  - median：`0.117620s → 0.093081s`（`1.264x`）。

新增测试：

- `tests/test_notification_provider_metadata_copy_r669.py`
  - source invariant 锁定 Web provider 使用 `event.metadata.copy()`，且不再出现
    `dict(event.metadata)`；
  - source invariant 锁定 Sound provider 使用 `event.metadata.copy()`，且不再出现
    `dict(event.metadata)`；
  - runtime 覆盖 Web payload metadata 的 top-level mutation 不污染原始
    `event.metadata`，且 snapshot 不包含 `web_notification_data`；
  - runtime 覆盖 Sound payload metadata 的 top-level mutation 不污染原始
    `event.metadata`，且 snapshot 不包含 `sound_notification_data`。

拒绝项：

- `copy.deepcopy(event.metadata)`：能隔离 nested values，但改变既有 shallow
  contract，且会为用户 metadata 中的复杂对象支付递归复制成本；
- 直接引用 `event.metadata`：最快但会形成 provider payload 自引用风险，并让
  caller mutation 互相污染；
- 抽公共 helper：两处逻辑足够直接，引入 helper 不会降低复杂度。

### 3.213 R670 · feedback counters snapshot 去 redundant dict copy

结论：已落地。`get_feedback_counters()` 的锁内 snapshot 改为直接调用
`_FEEDBACK_COUNTERS.copy()`；`server_info_resource()` 在 normal path 复用
getter 已返回的 dict snapshot，不再执行第二次 `dict(getter())`。

旧实现：

```python
with _FEEDBACK_COUNTERS_LOCK:
    return dict(_FEEDBACK_COUNTERS)

feedback_counters_info = dict(getter())
```

R670 改为：

```python
with _FEEDBACK_COUNTERS_LOCK:
    return _FEEDBACK_COUNTERS.copy()

counters = getter()
feedback_counters_info = counters if isinstance(counters, dict) else dict(counters)
```

收益与边界：

- feedback counter snapshot 保留 shallow copy / caller isolation 契约；
- production path 从 helper copy + server wrapper copy 降为一次 copy；
- `server_info_resource()` 仍兼容非 dict mapping-like getter 返回值；
- getter missing / getter exception fallback 行为不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round197/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round197/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`dict.copy()` 返回 dictionary 的 shallow copy；
- `/tmp/smart-search-evidence/aiia-optimization-round197/02-python-dict-constructor-exa.json`
  保存 Python `dict` constructor 文档检索结果，用于对比 generic constructor
  路径；
- `/tmp/smart-search-evidence/aiia-optimization-round197/03-python-dict-copy-fetch.json`
  与 `04-python-dict-fetch.json` 记录 fetch provider 对官方 Python 页面提取失败
  （Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_feedback_counters_copy_r670.py
  tests/test_runtime_counters_r47.py
  tests/test_feat_module_level_cache_reset_audit_r352.py -q`
  → 44 passed, 10 subtests passed；
- `uv run ruff check src/ai_intervention_agent/server_feedback.py
  src/ai_intervention_agent/server.py tests/test_feedback_counters_copy_r670.py`
  → pass；
- `uv run ty check src/ai_intervention_agent/server_feedback.py
  src/ai_intervention_agent/server.py tests/test_feedback_counters_copy_r670.py`
  → pass；
- local `timeit` smoke：3-key feedback counter dict、2,000,000 calls、11 repeats，
  old helper copy + server copy `dict(dict(counters))` vs R670 single
  `counters.copy()`：
  - best：`0.157186s → 0.068879s`（`2.282x`）；
  - median：`0.159479s → 0.071828s`（`2.220x`）。

新增测试：

- `tests/test_feedback_counters_copy_r670.py`
  - source invariant 锁定 `get_feedback_counters()` 使用
    `_FEEDBACK_COUNTERS.copy()`，且不再出现 `dict(_FEEDBACK_COUNTERS)`；
  - source invariant 锁定 `server_info_resource()` 不再出现
    `feedback_counters_info = dict(getter())`；
  - runtime 覆盖 snapshot mutation 不污染 `_FEEDBACK_COUNTERS`；
  - runtime 覆盖 server info path 仍接受非 dict mapping counter snapshot。

拒绝项：

- 直接返回 `_FEEDBACK_COUNTERS`：最快但破坏 public snapshot contract；
- 删除非 dict fallback：能少一行分支，但会让 monkeypatch / adapter 返回 mapping
  时失去兼容性；
- `MappingProxyType`：能防 mutation，但改变既有返回类型。

### 3.214 R671 · notification provider stats inner snapshot 使用 dict.copy()

结论：已落地。`NotificationManager.get_status()` 已经先用
`self._stats.copy()` 拿顶层 stats snapshot，再把 `providers` 从顶层 snapshot
里 `pop` 出来单独复制。R671 把每个 provider 内层 stats dict 从
`dict(v)` 改为 normal path 的 `v.copy()`，仍保留非 dict mapping 的
`dict(v)` fallback。

旧实现：

```python
providers_stats = {k: dict(v) for k, v in providers_stats_raw.items()}
```

R671 改为：

```python
providers_stats = {
    k: v.copy() if isinstance(v, dict) else dict(v)
    for k, v in providers_stats_raw.items()
}
```

收益与边界：

- 每次 `get_status()` 轮询复制 provider stats 时少走通用 dict constructor；
- 返回值仍是独立 top-level / per-provider snapshot，caller mutation 不污染
  `_stats["providers"]`；
- status path 仍兼容 `UserDict` 等非 dict mapping；
- provider success_rate / avg_latency_ms 派生字段仍只写入返回 snapshot；
- corrupted non-mapping provider stats 的 fail-soft 边界不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round198/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round198/01-python-counter-copy-exa.json`
  保存 Python `Counter` 官方文档检索结果：`Counter` 是 dict subclass，且常见
  `dict(c)` 可转 plain dict；这支撑了本轮拒绝 `Counter.copy()` 的语义边界；
- `/tmp/smart-search-evidence/aiia-optimization-round198/02-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：mutable container copy 是 shallow copy，
  `dict` / `set` 等也提供 copy 接口；
- `/tmp/smart-search-evidence/aiia-optimization-round198/03-python-dict-copy-fetch.json`
  与 `04-python-counter-fetch.json` 记录 fetch provider 对官方 Python 页面提取失败
  （Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_notification_provider_stats_copy_r671.py
  tests/test_notification_status_stats_copy_pop_r648.py
  tests/test_notification_inflight_persistence_r136.py
  tests/test_notification_health_per_provider_r142.py -q`
  → 67 passed；
- `uv run ruff check src/ai_intervention_agent/notification_manager.py
  tests/test_notification_provider_stats_copy_r671.py`
  → pass；
- `uv run ty check src/ai_intervention_agent/notification_manager.py
  tests/test_notification_provider_stats_copy_r671.py`
  → pass；
- local `timeit` smoke：3-provider / 5-key provider stats dict、1,000,000 calls、
  11 repeats，old `{k: dict(v) ...}` vs R671 `{k: v.copy() ...}`：
  - best：`0.248164s → 0.232204s`（`1.069x`）；
  - median：`0.253553s → 0.232991s`（`1.088x`）。

新增测试：

- `tests/test_notification_provider_stats_copy_r671.py`
  - source invariant 锁定内层 provider stats 使用
    `v.copy() if isinstance(v, dict) else dict(v)`，且不再出现
    `{k: dict(v) for k, v in providers_stats_raw.items()}`；
  - runtime 覆盖返回 provider stats mutation 不污染内部 `_stats`；
  - runtime 覆盖 `UserDict` provider stats 仍可被转换并参与派生字段计算。

拒绝项：

- MCP `Counter.copy()` snapshot：语义可行，但 benchmark 显示
  `dict(counter)` 明显更快（best `0.124469s` vs `0.756253s`），所以保留
  `get_mcp_tool_call_stats()` 的 `dict(_counter)`；
- 直接返回 provider stats 内部 dict：最快但破坏 status API 的 defensive copy
  contract；
- 删除非 dict mapping fallback：可以少一个分支，但会降低测试 / adapter 兼容性。

### 3.215 R672 · recent-log source tagging 使用 dict.copy()

结论：已落地。`server_info_resource()` 的 `recent_logs` 子块会把 MCP 进程和
Web UI 子进程的 log ring entries 合并，并给每条 entry 添加 `source` 字段。
为了不污染原始 ring entry / HTTP JSON body，旧实现先 `dict(ent)` 再写
`source`。R672 将两处 concrete dict snapshot 改为 `ent.copy()`。

旧实现：

```python
tagged = dict(ent)
tagged["source"] = "mcp"
...
tagged = dict(ent)
tagged["source"] = "web_ui"
```

R672 改为：

```python
tagged = ent.copy()
tagged["source"] = "mcp"
...
tagged = cast("dict[str, object]", ent.copy())
tagged["source"] = "web_ui"
```

收益与边界：

- 每条 recent-log source tagging 少走一次通用 dict constructor；
- MCP ring entry 和 Web UI fetched entry 都不会被写入 `source` 或被 caller
  mutation 污染；
- `recent_logs.entries` wire shape、`mcp_count` / `web_ui_count`、按 `ts_unix`
  排序都不变；
- Web UI fetched entries 仍先做 `isinstance(ent, dict)` 过滤；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round199/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round199/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：mutable container copy 是 shallow copy，
  `dict` / `set` 等也提供 copy 接口；
- `/tmp/smart-search-evidence/aiia-optimization-round199/02-python-dict-constructor-exa.json`
  保存 Python `dict` constructor / mapping 文档检索结果，用于对比 generic
  constructor 路径；
- `/tmp/smart-search-evidence/aiia-optimization-round199/03-python-dict-copy-fetch.json`
  与 `04-python-dict-fetch.json` 记录 fetch provider 对官方 Python 页面提取失败
  （Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_recent_logs_tag_copy_r672.py
  tests/test_recent_logs_aggregation_r55.py
  tests/test_server_cache_hit_copy_r666.py -q`
  → 20 passed；
- `uv run ruff check src/ai_intervention_agent/server.py
  tests/test_recent_logs_tag_copy_r672.py`
  → pass；
- `uv run ty check src/ai_intervention_agent/server.py
  tests/test_recent_logs_tag_copy_r672.py`
  → pass；
- local `timeit` smoke：5-field recent-log entry、2,000,000 calls、11 repeats，
  old `dict(entry)` + source tag vs R672 `entry.copy()` + source tag：
  - best：`0.148821s → 0.133860s`（`1.112x`）；
  - median：`0.149399s → 0.134622s`（`1.110x`）。

新增测试：

- `tests/test_recent_logs_tag_copy_r672.py`
  - source invariant 锁定 `server_info_resource()` 使用 `tagged = ent.copy()`，
    且不再出现 `tagged = dict(ent)`；
  - runtime 覆盖 MCP recent-log source tagging 不污染原始 entry；
  - runtime 覆盖 Web UI fetched recent-log source tagging 不污染 fetched entry。

拒绝项：

- `_SSEBus.stats_snapshot()` 的 `emit_by_type` 改成 `Counter.copy()`：该字段
  public contract 是 plain dict，而 `_emit_by_type` 是 `Counter`；R671 已测出
  `Counter.copy()` 比 `dict(counter)` 慢很多，所以保留现状；
- 直接给原始 log entry 写 `source`：最快但会污染 ring buffer / fetched JSON
  body；
- 让 caller 自己区分来源：会破坏 `recent_logs.entries[*].source` 现有便利字段。

### 3.216 R673 · export image-strip result snapshot 使用 dict.copy()

范围：

- `GET /api/tasks/export?include_images=false` 的
  `_strip_images_from_result()` helper。

变更：

```python
sanitized = result.copy()
```

替换原来的：

```python
sanitized: dict[str, Any] = dict(result)
```

收益与边界：

- helper 已经通过 `isinstance(result, dict)` 收窄，且只需要 shallow top-level
  snapshot；
- `.copy()` 避免通用 `dict(...)` constructor 路径；
- `include_images=true`、`result is None`、无 `images`、`images` 非 list 仍直接
  返回原对象；
- `include_images=false` 仍只剥掉 `images[].data`，保留图片 metadata，并添加
  `images_stripped: true`；
- 原始 task result 不被写入 stripped image list 或 `images_stripped`；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round200/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round200/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：mutable container copy 是 shallow copy，
  `dict` 提供 copy 接口；
- `/tmp/smart-search-evidence/aiia-optimization-round200/02-python-dict-constructor-exa.json`
  保存 Python `dict` constructor / mapping 文档检索结果，用于对比 generic
  constructor 路径；
- `/tmp/smart-search-evidence/aiia-optimization-round200/03-python-dict-copy-fetch.json`
  与 `04-python-dict-fetch.json` 记录 fetch provider 对官方 Python 页面提取失败
  （Tavily / Firecrawl empty），因此 claim-level 文本采用 Exa 保存的
  official-domain page text / highlights。

验证：

- `uv run pytest tests/test_strip_images_result_copy_r673.py
  tests/test_tasks_export_include_images_r125c.py
  tests/test_tasks_export_since_r135.py -q`
  → 40 passed；
- `uv run ruff check src/ai_intervention_agent/web_ui_routes/task.py
  tests/test_strip_images_result_copy_r673.py`
  → pass；
- `uv run ty check src/ai_intervention_agent/web_ui_routes/task.py
  tests/test_strip_images_result_copy_r673.py`
  → pass；
- local `timeit` smoke：result dict 带 2 张图片、预构造 stripped image list、
  2,000,000 calls、11 repeats，old `dict(result)` + replacement vs R673
  `result.copy()` + replacement：
  - best：`0.132812s → 0.117458s`（`1.131x`）；
  - median：`0.133572s → 0.118376s`（`1.128x`）。

新增测试：

- `tests/test_strip_images_result_copy_r673.py`
  - source invariant 锁定 `_strip_images_from_result()` 使用
    `sanitized = result.copy()`，且不再出现 `dict(result)` snapshot；
  - runtime 覆盖 `include_images=true` 原对象 pass-through；
  - runtime 覆盖 `include_images=false` 剥掉 `data`、加
    `images_stripped`、不污染原始 result；
  - runtime 覆盖无 `images` / 非 list `images` 仍 no-op pass-through。

拒绝项：

- 深拷贝整个 result：会复制用户 result 内可能很大的嵌套结构，超出本 helper
  的 shallow-copy contract；
- 直接原地替换 `result["images"]`：最快但会污染 task cache/export caller
  共享的 result 对象；
- 复用 `stripped_images` 写回原对象后再恢复：异常路径复杂，收益不足。

### 3.217 R674 · TaskQueue watchdog slow-record snapshot 使用 dict.copy()

范围：

- `task_queue._scan_pending_and_dump_slow()` 的 slow write-lock record snapshot。

变更：

```python
slow_records.append(rec.copy())
```

替换原来的：

```python
slow_records.append(dict(rec))
```

收益与边界：

- `_pending_acquisitions` 的 value 是模块内部创建的 `dict[str, Any]` record；
- watchdog 在 `_pending_acquisitions_lock` 内把超时 record 标记为
  `dumped=True`，随后只需要 shallow snapshot 给锁外日志路径使用；
- `.copy()` 避免通用 `dict(...)` constructor 路径，并保持日志使用的
  `label` / `thread_id` / `start` 与扫描命中时一致；
- dedup 语义不变：registry 内原 record 仍被标记 `dumped=True`；
- 不改变 watchdog daemon 周期、超时阈值、日志内容或异常吞吐策略；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round201/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round201/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`copy()` 返回 shallow copy，mutable
  containers 包括 `dict` 提供 copy 接口；
- `/tmp/smart-search-evidence/aiia-optimization-round201/02-python-dict-copy-fetch.json`
  记录 fetch provider 对官方 Python `dict.copy` 页面提取失败
  （Tavily / Firecrawl empty）；
- `/tmp/smart-search-evidence/aiia-optimization-round201/03-python-dict-constructor-exa.json`
  保存 Python `dict` constructor / mapping 文档检索结果，用于对比 generic
  constructor 路径。

验证：

- `uv run pytest tests/test_task_queue_watchdog_record_copy_r674.py
  tests/test_lock_watchdog_r51a.py -q`
  → 21 passed；
- `uv run ruff check src/ai_intervention_agent/task_queue.py
  tests/test_task_queue_watchdog_record_copy_r674.py`
  → pass；
- `uv run ty check src/ai_intervention_agent/task_queue.py
  tests/test_task_queue_watchdog_record_copy_r674.py`
  → pass；
- local `timeit` smoke：4-field watchdog record、5,000,000 calls、11 repeats，
  old `dict(rec)` vs R674 `rec.copy()`：
  - best：`0.240139s → 0.193824s`（`1.239x`）；
  - median：`0.243433s → 0.199090s`（`1.223x`）。

新增测试：

- `tests/test_task_queue_watchdog_record_copy_r674.py`
  - source invariant 锁定 `_scan_pending_and_dump_slow()` 使用
    `slow_records.append(rec.copy())`；
  - runtime 覆盖 slow-record snapshot 与 registry 后续 mutation 隔离；
  - runtime 覆盖 registry 内原 record 仍被标记 `dumped=True`。

拒绝项：

- 保留 `dict(rec)`：兼容 mapping-like 输入，但这里的 registry record 是本模块
  自建 dict，兼容面没有实际收益；
- 不复制、直接把 `rec` 放进 `slow_records`：最快但日志会暴露后续 mutation /
  registry cleanup race；
- 深拷贝 record：字段均为 scalar，深拷贝没有语义收益。

### 3.218 R675 · import_config network_security 过滤快照单次复用

范围：

- `config_modules.io_operations.IOOperationsMixin.import_config()` 的通用
  config 导入路径。

变更：

```python
config_without_network_security = actual_config.copy()
config_without_network_security.pop("network_security", None)
```

随后 merge / override / pending-save 都复用同一个已过滤 top-level snapshot：

```python
self._deep_merge(self._config, config_without_network_security)
self._config = config_without_network_security.copy()
self._pending_changes.update(config_without_network_security)
```

替换原来每个分支重复：

```python
tmp = dict(actual_config)
tmp.pop("network_security", None)
```

收益与边界：

- `actual_config` 已经过 `isinstance(actual_config, dict)` 收窄；
- `network_security` 仍先从 wrapper 或 config body 提取，再走
  `set_network_security_config(..., trigger_callbacks=False)` 专用路径；
- 通用 `_config` 和 `_pending_changes` 仍不接收 `network_security`；
- merge 路径复用同一 filtered snapshot；`_deep_merge()` 只写入 destination
  `base`，不修改 update mapping；
- override 路径仍给 `self._config` 单独 top-level copy，避免与 pending snapshot
  共用同一个 dict 对象；
- 原始 import payload 不被 `pop()` 污染；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round202/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round202/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`copy()` 返回 shallow copy，mutable
  containers 包括 `dict` 提供 copy 接口；
- `/tmp/smart-search-evidence/aiia-optimization-round202/02-python-dict-constructor-exa.json`
  保存 Python `dict` constructor / mapping 文档检索结果，用于对比 generic
  constructor 路径；
- `/tmp/smart-search-evidence/aiia-optimization-round202/03-python-dict-copy-fetch.json`
  记录 fetch provider 对官方 Python `dict.copy` 页面提取失败
  （Tavily / Firecrawl empty）。

验证：

- `uv run pytest tests/test_import_config_single_snapshot_r675.py
  tests/test_io_operations.py
  tests/test_config_manager.py::TestConfigManagerExportImportAdvanced
  tests/test_config_manager.py::TestConfigManagerExportImport -q`
  → 41 passed；
- `uv run ruff check
  src/ai_intervention_agent/config_modules/io_operations.py
  tests/test_import_config_single_snapshot_r675.py`
  → pass；
- `uv run ty check src/ai_intervention_agent/config_modules/io_operations.py
  tests/test_import_config_single_snapshot_r675.py`
  → pass；
- local `timeit` smoke：wrapped config 含 `web_ui` / `notification` /
  `feedback` / `mdns` / `network_security`，500,000 calls、11 repeats：
  - merge+save old repeated `dict(actual_config)` vs R675 single snapshot：
    best `2.054926s → 1.998967s`（`1.028x`），median
    `2.057487s → 2.008953s`（`1.024x`）；
  - override+save old repeated `dict(actual_config)` + extra copy vs R675
    single snapshot + config copy：best `0.098591s → 0.062453s`（`1.579x`），
    median `0.099826s → 0.062780s`（`1.590x`）。

新增测试：

- `tests/test_import_config_single_snapshot_r675.py`
  - source invariant 锁定 `import_config()` 只构造一次
    `config_without_network_security`，不再出现 `tmp = dict(actual_config)`；
  - runtime 覆盖 merge+save 仍过滤 `network_security`、调用专用 setter、保留
    原始 import payload；
  - runtime 覆盖 override+save 的 `_config` 与 `_pending_changes` 不共用同一个
    top-level dict。

拒绝项：

- 直接原地 `actual_config.pop("network_security")`：最快但会污染 caller 提供的
  import payload；
- override 分支直接 `self._config = config_without_network_security`：少一次 copy，
  但会让 `_config` 与本轮 pending snapshot 共用 top-level dict；
- 深拷贝整个 config：导入配置可能包含嵌套 section，深拷贝成本高，且现有
  contract 一直是 top-level network_security 过滤。

### 3.219 R676 · network_security incremental update snapshot 使用 dict.copy()

结论：`NetworkSecurityMixin.update_network_security_config()` 的 current snapshot
从 `dict(current)` 改为 `current.copy()`。这里 `current` 来自
`get_network_security_config()`，返回值在本模块 contract 内已经是普通配置 dict；
update 路径只需要 shallow top-level snapshot，再对白名单字段增量覆盖。

为什么成立：

- `get_network_security_config()` 返回 validated dict 或缓存 dict；
- `update_network_security_config()` 后续只写 top-level keys，不需要 deep copy；
- `current.copy()` 保持与缓存/current mapping 隔离，避免在 validation 前污染
  current；
- legacy `enable_access_control` 仍映射到 `access_control_enabled`；
- unknown fields 仍忽略；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round203/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round203/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`dict.copy()` 返回 shallow copy；
- `/tmp/smart-search-evidence/aiia-optimization-round203/02-python-dict-constructor-exa.json`
  保存 Python `dict()` constructor / mapping 文档检索结果，用于对比 generic
  constructor 路径；
- `/tmp/smart-search-evidence/aiia-optimization-round203/03-python-dict-copy-fetch.json`
  记录 fetch provider 对官方 Python `dict.copy` 页面提取失败
  （Tavily / Firecrawl empty）。

验证：

- `uv run pytest tests/test_network_security_update_copy_r676.py
  tests/test_network_security_config.py::TestUpdateNetworkSecurityMixin
  tests/test_config_manager.py::TestUpdateNetworkSecurity
  tests/test_config_manager.py::TestSetNetworkSecurityRouting
  tests/test_config_manager.py::TestUpdateSectionNetworkSecurity -q`
  → pass；
- local `timeit` smoke：7-field network_security dict +
  `bind_interface` / `trusted_hosts` / `enable_access_control` / unknown update，
  2,000,000 calls、11 repeats：
  - old `dict(current)`：best `0.382407s`，median `0.383964s`；
  - R676 `current.copy()`：best `0.358508s`，median `0.359626s`；
  - speedup：best `1.067x`，median `1.068x`。

新增测试：

- `tests/test_network_security_update_copy_r676.py`
  - source invariant 锁定 `merged = current.copy()`，禁止回退到
    `merged = dict(current)`；
  - runtime 覆盖 snapshot 与 current mapping 隔离；
  - runtime 覆盖 `enable_access_control` alias、unknown field ignore。

拒绝项：

- 直接写入 `current`：少一次 shallow copy，但会污染 cache/current snapshot；
- `copy.deepcopy(current)`：当前 update 只覆盖 top-level fields，深拷贝成本不必要；
- `{**current}`：同样能 shallow copy，但对本地读者不如 dict API 直观，也没有比
  `dict.copy()` 更好的 benchmark 证据。

### 3.220 R677 · ConfigManager section fallback snapshot 使用 dict.copy()

范围：

- `ConfigManager._validate_section()` 的两个 fallback 返回路径：
  - unknown section，无 Pydantic model；
  - Pydantic validation 失败，降级返回原始 section。

变更：

```python
return raw.copy()
```

替换原来的：

```python
return dict(raw)
```

收益与边界：

- `_validate_section()` 已经用 `isinstance(raw, dict)` 收窄，非 dict 仍先归一化为
  `{}`；
- fallback 只需要 shallow top-level defensive snapshot，避免 caller 修改返回值
  反向污染原始 raw；
- `dict` 子类的内建 `copy()` 仍返回普通 `dict`，保持返回类型 contract；
- Pydantic 成功路径仍走 `model_validate(...).model_dump()`，不受影响；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round204/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round204/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`dict.copy()` 返回 shallow copy；
- `/tmp/smart-search-evidence/aiia-optimization-round204/02-python-dict-constructor-exa.json`
  保存 Python `dict()` constructor / mapping 文档检索结果，用于对比 generic
  constructor 路径；
- `/tmp/smart-search-evidence/aiia-optimization-round204/03-python-dict-copy-fetch.json`
  记录 fetch provider 对官方 Python `dict.copy` 页面提取失败
  （Tavily / Firecrawl empty）。

验证：

- `uv run pytest tests/test_config_validate_section_copy_r677.py
  tests/test_config_manager.py::TestConfigManagerBasic
  tests/test_config_manager.py::TestConfigManagerDefaults
  tests/test_config_manager.py::TestCacheStatsAndTTL
  tests/test_config_manager.py::TestUpdateSectionNetworkSecurity -q`
  → pass；
- local `timeit` smoke：10-field representative notification section dict，
  5,000,000 calls、11 repeats：
  - old `dict(raw)`：best `0.214736s`，median `0.215266s`；
  - R677 `raw.copy()`：best `0.188883s`，median `0.192835s`；
  - speedup：best `1.137x`，median `1.116x`。

新增测试：

- `tests/test_config_validate_section_copy_r677.py`
  - source invariant 锁定两个 fallback 都使用 `return raw.copy()`，禁止回退
    `return dict(raw)`；
  - runtime 覆盖 unknown section 返回独立 shallow snapshot；
  - runtime 覆盖非 dict raw 仍归一化为 `{}`；
  - runtime 覆盖 Pydantic validation failure fallback 返回独立 snapshot。

拒绝项：

- 直接返回 `raw`：最快但会暴露内部 raw 给 caller mutation；
- `copy.deepcopy(raw)`：`get_section()` 外层已有 deep-copy 返回 contract，fallback
  内部只需要与 cache raw 隔离的 top-level snapshot；
- `{**raw}`：性能与语义可行，但本轮证据和周边 R673-R676 风格都指向
  `dict.copy()`。

### 3.221 R678 · restore_config JSON dict snapshot 使用 dict.copy()

范围：

- `IOOperationsMixin.restore_config()` 的 JSON backup restore 路径：
  - wrapped backup：`backup_data["config"]`；
  - raw backup：整个 `backup_data`。

变更：

```python
restored_config = actual_config.copy()
restored_config = backup_data.copy()
```

替换原来的：

```python
restored_config = dict(actual_config)
restored_config = dict(backup_data)
```

收益与边界：

- `backup_data` 来自 `json.load()`，Python JSON object 默认解码为 `dict`；
- `actual_config` / `backup_data` 在 copy 前都已经过 `isinstance(..., dict)` 收窄；
- restore path 只需要 top-level snapshot：wrapped restore 仍会把顶层
  `network_security` 合并回 `restored_config`，不污染 wrapped `config`；
- raw backup restore、TOML/JSON 写盘、atomic replace、reload、cache invalidation
  和 callbacks 不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round205/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round205/01-python-dict-copy-exa.json`
  保存 Python 官方文档检索结果：`dict.copy()` 返回 shallow copy；
- `/tmp/smart-search-evidence/aiia-optimization-round205/02-python-json-load-exa.json`
  保存 Python `json.load()` 官方文档检索结果：JSON object 默认解码为 Python
  `dict`；
- `/tmp/smart-search-evidence/aiia-optimization-round205/03-python-dict-copy-fetch.json`
  记录 fetch provider 对官方 Python `dict.copy` 页面提取失败
  （Tavily / Firecrawl empty）。

验证：

- `uv run pytest tests/test_restore_config_copy_r678.py
  tests/test_io_operations.py::TestRestoreConfig
  tests/test_io_operations.py::TestRestoreConfigWithNs
  tests/test_config_manager.py::TestConfigManagerExportImportAdvanced -q`
  → pass；
- local `timeit` smoke：representative wrapped/raw backup dict，5,000,000 calls、
  11 repeats：
  - wrapped old `dict(actual_config)`：best `0.183996s`，median `0.184737s`；
  - wrapped R678 `actual_config.copy()`：best `0.129900s`，median `0.130562s`；
  - wrapped speedup：best `1.416x`，median `1.415x`；
  - raw old `dict(backup_data)`：best `0.194144s`，median `0.194741s`；
  - raw R678 `backup_data.copy()`：best `0.138898s`，median `0.140208s`；
  - raw speedup：best `1.398x`，median `1.389x`。

新增测试：

- `tests/test_restore_config_copy_r678.py`
  - source invariant 锁定 wrapped/raw restore 都使用 `.copy()`，禁止回退到
    `dict(...)`；
  - runtime 覆盖 wrapped backup 仍恢复 `notification` 并合并
    `network_security`；
  - runtime 覆盖 raw backup 仍恢复 top-level config。

拒绝项：

- 直接把 `actual_config` 赋给 `restored_config` 后原地加 `network_security`：
  会污染 wrapped backup 中的 `config` 对象；
- 深拷贝整个 backup：restore 写盘只需要 top-level snapshot，嵌套配置保持既有
  JSON/TOML serialization 行为即可；
- `{**actual_config}` / `{**backup_data}`：语义可行，但本轮 benchmark 和周边
  copy-path 风格都支持 `dict.copy()`。

### 3.222 R679 · state_machine transition table snapshot 使用 dict.copy()

范围：

- `state_machine.list_transitions()` 对 `TRANSITIONS` 的每个内层迁移规则表做
  shallow snapshot。

变更：

```python
return {kind: rules.copy() for kind, rules in TRANSITIONS.items()}
```

替换原来的：

```python
return {kind: dict(rules) for kind, rules in TRANSITIONS.items()}
```

收益与边界：

- `TRANSITIONS` 是模块内定义的 `dict[str, dict[str, tuple[str, ...]]]`；
- 内层 `rules` 已是具体 `dict`，不需要保留任意 mapping constructor 兼容；
- `list_transitions()` 的公开契约是浅拷贝：caller 改内层 dict 不会污染模块常量，
  tuple target values 继续共享；
- `StateMachine` 迁移校验、JS 同步测试和 transition table validation 行为不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round206/00-doctor.json`
  保存 smart-search 诊断；本轮 `ok=false`，原因是 OpenAI-compatible chat
  test 返回 HTTP 400，但 Exa / Context7 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round206/01-python-dict-copy-exa.json`
  保存 Python 官方 `dict.copy()` 文档发现结果；
- `/tmp/smart-search-evidence/aiia-optimization-round206/02-python-dict-constructor-exa.json`
  保存 Python 官方 `dict()` constructor 文档发现结果；
- `/tmp/smart-search-evidence/aiia-optimization-round206/03-python-dict-copy-fetch.json`
  记录 fetch provider 对官方 Python `dict.copy` 页面提取失败
  （Tavily / Firecrawl empty）。

验证：

- `uv run pytest tests/test_state_machine_transitions_copy_r679.py
  tests/test_state_machine.py tests/test_state_machine_gaps_r40.py -q` → pass；
- local `timeit` smoke：当前 `TRANSITIONS` 的三个内层 dict，5,000,000 calls、
  11 repeats：
  - old `[dict(rules) for rules in rules_list]`：best `0.907961s`，
    median `0.908847s`；
  - R679 `[rules.copy() for rules in rules_list]`：best `0.777782s`，
    median `0.785042s`；
  - speedup：best `1.167x`，median `1.158x`。

新增测试：

- `tests/test_state_machine_transitions_copy_r679.py`
  - source invariant 锁定 `rules.copy()`，禁止回退到 `dict(rules)`；
  - runtime 覆盖返回 outer/inner dict snapshot 与 `TRANSITIONS` 隔离；
  - runtime 覆盖 tuple target values 保持浅拷贝共享。

拒绝项：

- 直接返回 `TRANSITIONS`：最快但暴露模块常量给 caller mutation；
- `copy.deepcopy(TRANSITIONS)`：函数契约只承诺浅拷贝，target values 是不可变
  tuple；
- `{**rules}`：语义可行，但不如 `.copy()` 直接表达 dict shallow snapshot，
  也与 R673-R678 的 copy-path 风格不一致。

### 3.223 R680 · notification routes 复用 get_section() 已隔离快照

范围：

- `web_ui_routes.notification.NotificationRoutesMixin._setup_notification_routes()`
  中三条写配置路径：
  - `/api/update-notification-config`；
  - `/api/update-feedback-config`；
  - `/api/reset-feedback-config`。

变更：

```python
notification_config = config_mgr.get_section("notification")
feedback_config = config_mgr.get_section("feedback")
current = config_mgr.get_section("feedback")
```

替换原来的：

```python
notification_config = dict(config_mgr.get_section("notification"))
feedback_config = dict(config_mgr.get_section("feedback"))
current = dict(config_mgr.get_section("feedback"))
```

收益与边界：

- `ConfigManager.get_section()` 的 contract 已经是“获取配置段的深拷贝”，且返回
  `dict[str, Any]`；
- `notification` / `feedback` 成功路径来自 Pydantic `model_dump()`，返回 plain
  dict；fallback 也已在 R677 改为 `raw.copy()`；
- route 随后修改的是 `get_section()` 返回的私有 snapshot，再传给
  `update_section()`，不需要第二次 top-level copy；
- partial notification update、feedback prompt update、reset defaults、unknown
  field ignore 和 round-trip readback 行为不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round207/00-doctor.json`
  保存 smart-search 诊断，本轮 `ok=true`；
- `/tmp/smart-search-evidence/aiia-optimization-round207/01-python-copy-deepcopy-exa.json`
  保存 Python `copy` / `deepcopy` 官方文档发现结果，用于说明
  `get_section()` 内部 deep copy 已提供隔离 snapshot；
- `/tmp/smart-search-evidence/aiia-optimization-round207/02-python-dict-constructor-exa.json`
  保存 Python `dict()` constructor 官方文档发现结果，用于对比额外构造 dict 的
  成本边界；
- `/tmp/smart-search-evidence/aiia-optimization-round207/03-python-copy-fetch.json`
  记录 fetch provider 对官方 Python `copy` 页面提取失败
  （Tavily / Firecrawl empty）；
- `/tmp/smart-search-evidence/aiia-optimization-round207/04-python-dict-constructor-fetch.json`
  记录 fetch provider 对官方 Python dictionaries 页面提取失败
  （Tavily / Firecrawl empty）。

验证：

- `uv run pytest tests/test_notification_routes_get_section_direct_r680.py
  tests/test_web_ui_config.py::TestWebUIFinalPush::test_notification_config_update_sound
  tests/test_web_ui_config.py::TestWebUIFinalPush::test_notification_config_update_web
  tests/test_web_ui_config.py::TestWebUINotificationAPIs::test_update_all_notification_settings
  tests/test_web_ui_config.py::TestWebUINotificationAPIs::test_update_bark_settings
  tests/test_integration.py::TestWebFeedbackUINotificationConfig::test_update_notification_config
  tests/test_integration.py::TestWebFeedbackUINotificationConfig::test_update_notification_config_partial_merge
  tests/test_runtime_behavior.py::TestNotificationConfigRoundTrip::test_notification_config_save_and_read_back
  tests/test_runtime_behavior.py::TestFeedbackConfigRoundTrip::test_feedback_config_save_and_read_back -q`
  → 10 passed；
- local `timeit` smoke：representative 12-field notification section，
  `get_section()` 已返回 copied dict，5,000,000 calls、11 repeats：
  - old `dict(get_section())`：best `0.535129s`，median `0.538194s`；
  - R680 `get_section()`：best `0.265134s`，median `0.271587s`；
  - speedup：best `2.018x`，median `1.982x`；
- live `ConfigManager` smoke：`get_section("notification")` 与
  `get_section("feedback")` 均返回 plain dict、两次调用不是同一对象。

新增测试：

- `tests/test_notification_routes_get_section_direct_r680.py`
  - source invariant 锁定三条 route 直接使用 `config_mgr.get_section(...)`；
  - 禁止重新引入 `dict(config_mgr.get_section(...))`；
  - runtime 覆盖 `get_section()` 返回 snapshot 可被 route 局部修改，且不会污染
    后续 `get_section()` 结果。

拒绝项：

- 保留 `dict(get_section(...))`：多一次 top-level allocation，而 `get_section()`
  已经完成 deep-copy 隔离；
- 改成 `.copy()`：比 `dict(...)` 少一点开销，但仍是多余 copy；
- 直接读取 `ConfigManager` 内部缓存或 `_config`：可能更快，但会破坏封装和配置
  校验/缓存失效 contract。

### 3.224 R681 · print-config web_ui snapshot 使用 dict.copy()

范围：

- `server._print_effective_config()` 的 `--print-config` diagnostic 输出路径。

变更：

```python
web_ui_section = web_ui_raw.copy() if isinstance(web_ui_raw, dict) else {}
```

替换原来的：

```python
web_ui_section = dict(web_ui_raw) if isinstance(web_ui_raw, dict) else {}
```

收益与边界：

- `ConfigManager.get_all()` 返回 `_config` 的 deep copy，并过滤
  `network_security`；
- `web_ui_raw` 已经过 `isinstance(web_ui_raw, dict)` 收窄，成功路径是具体
  section dict；
- 仍保留 top-level snapshot：后续 overlay `host` / `port` / `language` 时不污染
  `all_config["web_ui"]`；
- `sections.web_ui` 和顶层 `web_ui` 继续展示 env override 后的 effective 值；
- redaction、安全过滤、失败路径 JSON 输出和 argparse 行为不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round208/00-doctor.json`
  保存 smart-search 诊断；本轮 `ok=false`，原因是 OpenAI-compatible chat
  test 返回 HTTP 400，但 Exa / Context7 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round208/01-python-dict-copy-exa.json`
  保存 Python `dict.copy()` / shallow copy 官方文档发现结果；
- `/tmp/smart-search-evidence/aiia-optimization-round208/02-python-copy-deepcopy-exa.json`
  保存 Python `copy` / `deepcopy` 官方文档发现结果，用于说明 `get_all()`
  deep-copy 隔离 contract 的边界；
- `/tmp/smart-search-evidence/aiia-optimization-round208/03-python-copy-fetch.json`
  记录 fetch provider 对官方 Python `copy` 页面提取失败
  （Tavily / Firecrawl empty）；
- `/tmp/smart-search-evidence/aiia-optimization-round208/04-python-dict-copy-fetch.json`
  记录 fetch provider 对官方 Python `dict.copy` 页面提取失败
  （Tavily / Firecrawl empty）。

验证：

- `uv run pytest tests/test_server_print_config_web_ui_copy_r681.py
  tests/test_server_print_config.py -q` → 26 passed；
- `uv run ruff check src/ai_intervention_agent/server.py
  tests/test_server_print_config_web_ui_copy_r681.py` → pass；
- `uv run ty check src/ai_intervention_agent/server.py
  tests/test_server_print_config_web_ui_copy_r681.py` → pass；
- local `timeit` smoke：representative 10-field `web_ui` section，
  5,000,000 calls、11 repeats：
  - old `dict(web_ui_raw)`：best `0.210948s`，median `0.211600s`；
  - R681 `web_ui_raw.copy()`：best `0.170907s`，median `0.172789s`；
  - speedup：best `1.234x`，median `1.225x`；
- live `ConfigManager` smoke：`get_all()["web_ui"]` 是 concrete dict，`.copy()`
  后 probe mutation 不污染原 section。

新增测试：

- `tests/test_server_print_config_web_ui_copy_r681.py`
  - source invariant 锁定 `web_ui_raw.copy()`，禁止回退到
    `dict(web_ui_raw)`；
  - runtime 覆盖 effective overlay 仍进入 stdout payload；
  - runtime 覆盖 overlay 不污染 `ConfigManager.get_all()` 返回的原始
    `web_ui` section。

拒绝项：

- 直接把 `web_ui_raw` 赋给 `web_ui_section` 后 update：少一次 copy，但会污染
  `all_config["web_ui"]`，并让 `sections_full` 里的原始 section 被后续 overlay
  原地改写；
- `copy.deepcopy(web_ui_raw)`：`get_all()` 已经 deep-copy 整个 config tree，这里只
  需要 overlay 前的 top-level snapshot；
- `{**web_ui_raw}`：语义可行，但 `.copy()` 更直接表达 concrete dict snapshot，
  且本轮 benchmark 支持它。

### 3.225 R682 · notification cleanup 使用 tuple snapshot

范围：

- `NotificationManager.reset_for_testing()` 清理 delayed timers；
- `NotificationManager.shutdown()` 清理 delayed timers、grace-period worker
  threads、providers。

变更：

```python
tuple(self._delayed_timers.values())
timers = tuple(self._delayed_timers.values())
worker_threads = tuple(getattr(self._executor, "_threads", ()) or ())
providers = tuple(self._providers.values())
```

替换原来的：

```python
list(self._delayed_timers.values())
timers = list(self._delayed_timers.values())
worker_threads = list(getattr(self._executor, "_threads", ()) or ())
providers = list(self._providers.values())
```

收益与边界：

- 这些 snapshot 都只用于迭代，不需要 append / pop / index assignment；
- snapshot 后原 dict 会被清空或替换，仍然避免“迭代时修改 dict”的问题；
- tuple 是不可变 sequence，能更准确表达“只读清理快照”；
- `Timer.cancel()`、`Thread.join(timeout=...)`、provider safe-close、异常吞吐和
  shutdown idempotency 不变；
- 无静态 JS 变更。

外部依据：

- `/tmp/smart-search-evidence/aiia-optimization-round209/00-doctor.json`
  保存 smart-search 诊断；本轮 `ok=false`，原因是 OpenAI-compatible chat
  test 返回 HTTP 400，但 Exa / Context7 可用；
- `/tmp/smart-search-evidence/aiia-optimization-round209/01-python-list-tuple-exa.json`
  保存 Python 官方文档发现结果：tuple 是不可变 sequence，list 是 mutable
  sequence；
- `/tmp/smart-search-evidence/aiia-optimization-round209/02-python-tuples-fetch.json`
  记录 fetch provider 对官方 Python tuple/list 文档提取失败
  （Tavily / Firecrawl empty）。

验证：

- `uv run pytest tests/test_notification_cleanup_tuple_snapshots_r682.py
  tests/test_notification_manager.py::TestShutdownRestart
  tests/test_notification_manager.py::TestShutdownEdgeCases
  tests/test_notification_manager.py::TestShutdownGracePeriod
  tests/test_feat_notification_reset_for_testing_r323.py::TestLayer2ResetBehavior::test_delayed_timers_reset_and_cancelled -q`
  → 22 passed；
- `uv run ruff check src/ai_intervention_agent/notification_manager.py
  tests/test_notification_cleanup_tuple_snapshots_r682.py` → pass；
- `uv run ty check src/ai_intervention_agent/notification_manager.py
  tests/test_notification_cleanup_tuple_snapshots_r682.py` → pass；
- local `timeit` smoke，3,000,000 calls、11 repeats：
  - 3-value timer/provider snapshot：`list(values)` best/median
    `0.152585s / 0.153687s`，`tuple(values)` best/median
    `0.121216s / 0.121833s`，speedup best/median `1.259x / 1.261x`；
  - 32-value timer/provider snapshot：`list(values)` best/median
    `0.360361s / 0.363276s`，`tuple(values)` best/median
    `0.339874s / 0.344297s`，speedup best/median `1.060x / 1.055x`；
  - 8-thread set snapshot：`list(threads)` best/median
    `0.160868s / 0.161208s`，`tuple(threads)` best/median
    `0.133285s / 0.134618s`，speedup best/median `1.207x / 1.198x`。

新增测试：

- `tests/test_notification_cleanup_tuple_snapshots_r682.py`
  - source invariant 锁定 reset/shutdown cleanup snapshots 使用 tuple；
  - runtime 覆盖 reset 仍 cancel delayed timers 并清空 timer registry；
  - runtime 覆盖 shutdown 仍 cancel timers、shutdown executor、grace join threads、
    safe-close providers 并清空 registries。

拒绝项：

- 直接迭代 `self._delayed_timers.values()` 后再清空 dict：会触发或冒险触发
  “dict changed size during iteration”；
- 保留 list snapshot：语义可行，但这里不需要 mutable container；
- 把 provider close 放在锁内：可缩短 snapshot 分配但会扩大 lock 持有时间，并把
  provider close 的未知 I/O / user code 风险带进锁内。

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

- `/static/*` → stale-while-revalidate（R459）
- `/icons/*` → stale-while-revalidate
- HTML 导航 → network-first + R249 offline.html 兜底
- 通知点击 → 路由到主窗口或新开

### 4.2 cache 命中率

- 冷启动：所有 21 个 JS + 1 CSS + 5 icon = 27 requests
- 热启动：0 network requests（全 cache 命中）
- 修改单文件：1 request（cache busted by `?v=` query）

---

## 5. Defer / follow-up 列表

按 ROI 降序：

### 5.1 Inline critical CSS (medium ROI)

- **现状**：`main.css` 4500+ 行，brotli 后 ~25KB，FCP 仍要等 CSS 解析完。
- **思路**：抽出首屏 ~5KB critical CSS 内联到 `<head>`，rest async。
- **触发条件**：lab 测试 LCP > 2s（当前 ~600ms 不需要）。
- **工具**：``critters`` / ``critical`` npm 包，但项目无 npm build → 手工
  抽 + 维护成本高，**defer**。

### 5.2 Service Worker offline-first for `/static/*` (closed by R459)

- **原现状**：cache-first 命中快，但未版本化静态资源会一直陈旧到 SW cache
  版本 bump。
- **R459**：已改为 ``stale-while-revalidate``，cache hit 立刻返回并用
  ``event.waitUntil`` 后台刷新。

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
