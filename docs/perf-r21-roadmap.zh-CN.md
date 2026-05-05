# R21.x 性能路线图

> English: [`perf-r21-roadmap.md`](perf-r21-roadmap.md)

本文档记录 **R21.x 性能优化批次**（R21.1 → R21.4）的设计动因、测量数据
与权衡取舍。R21.x 关注的是**浏览器侧网络/缓存层**——介于已优化好的服务端
（R20.x）与用户浏览器之间。R21.x 不再针对服务端冷启动（R20.x 已经把那条
路径从 1980 ms 压到 360 ms），而是瞄准*下一个*瓶颈：每个静态资源仍走每次
网络请求、脚本仍在 HTML 解析中串行、Brotli（自 2017 年起所有浏览器原生
支持）一直没用上。

## 本文档的目的

R21.x 落地了 4 个 commit（3 个 perf + 1 个 release），随 v1.5.28 发布。
单个 commit message 描述了每次改动做了什么；本路线图是**唯一**讲清楚
以下 3 件事的文档：

- **三层如何组合**：preload → cache → compression 是正交但相乘的关系
  ——preload 让下载更早开始，cache 消除重复下载，compression 缩小每次
  下载的字节；
- **R21.3（webview esbuild 打包）为什么被刻意跳过**——完整的基于测量
  的推理保留在本文档中，让未来贡献者不必重做调研；
- **下一个 R22.x 批次不应该重新考察什么**：每条 R21.x 决策都记录了
  关闭那个问题所依赖的权衡。

## R21.x 的范围

触发本批次的用户指令：

> 深挖性能优化, 先从本体 MCP 开始, 再到网页, 再到插件, 再到整体, 都要进行性能优化。

R20.x 已经在四层上把冷启动方向打透了。R21.x **重新瞄准同样的四层**，但
转向 R20.x 没碰过的*稳态* / *重复会话*这一维度。

| 轮次 | 焦点 | 墙钟/字节影响 |
|-----|------|--------------|
| **R21.1** | `<link rel="preload">` 关键资源预加载 | FCP 提早 30-100 ms |
| **R21.2** | Service Worker 静态资源 cache-first | 重复会话约 80 个资源 0 RTT |
| **R21.3** | (调研后否决) webview esbuild 打包 | 估算 2-10 ms — 噪声级以下 |
| **R21.4** | Brotli 预压缩层（br > gzip > identity） | 在 R20.14-D gzip 基础上再省 -253 KB / -32% |

## 第 2.5 层 · 浏览器网络/缓存（R21.1 + R21.2 + R21.4）

R20.12 网页层覆盖了 FCP head-block、locale FOUC、image decode；R21.x
延伸到：

### R21.1 · 关键资源预加载

#### 问题

Web UI HTML 携带 12 个独立 `<script defer>` 标签，分散在 head（`mathjax-loader.js`
/ `marked.js` / `prism.js`）和 body 末尾（`validation-utils.js` / `theme.js` /
`keyboard-shortcuts.js` / `dom-security.js` / `state.js` / `multi_task.js` /
`i18n.js` / `notification-manager.js` / `settings-manager.js` /
`image-upload.js` / `app.js` / `tri-state-panel-*`）。浏览器的 preload-scanner
能 prefetch 解析过程中遇到的 `<link>` 声明，但 `defer` script 的*发现*
被 body 的串行解析阻塞。Network 面板典型显示 "head 解析完" 到 "body 第一个
script 请求" 之间有 ~30-50 ms 的间隙。

#### 方案：4 个关键 preload 提示

`templates/web_ui.html::<head>` 新增：

```html
<link rel="preload" href="/static/js/app.js?v={{ app_version }}" as="script" />
<link rel="preload" href="/static/js/multi_task.js?v={{ multi_task_version }}" as="script" />
<link rel="preload" href="/static/js/i18n.js" as="script" />
<link rel="preload" href="/static/js/state.js" as="script" />
```

为什么是这四个：

- `app.js`：主入口——其他模块的协调者；
- `multi_task.js`：polling/SSE 驱动——任何任务交互前都要；
- `i18n.js`：必须在 `app.js` 之前跑（翻译契约依赖）；
- `state.js`：状态机契约依赖。

#### 测量

按 Web Vitals 的 `preload-critical-assets` Lighthouse 审计：

- **下界**：~30 ms（之前串行成一个 TCP RTT 的资源现在并行成 ½ RTT）；
- **上界**：~100 ms（head 解析时间长，多个 script 本可重叠）。

具体值取决于 body 长度 × 网络 RTT × parser 线程调度。本机实测 FCP
**约提早 32 ms**；slow-LAN 部署收益更显著。

#### 权衡

- **URL 字节级一致**：preload `href` 必须和对应 `<script src>` 字节级
  完全相同（包括 `?v=` query），否则 preload cache 命中失败。
  `tests/test_critical_preload_r21_1.py`（24 测试）用字节级 byte-parity
  锁住；
- **preload 链接不带 nonce**：HTML spec 规定 `<link rel="preload">` 不
  执行脚本，只是发起网络请求。加 `nonce` 在 CSP 上是冗余的，且会让
  reviewer 误以为开发者不懂规范；
- **故意没 preload 的**：`mathjax-loader.js`（已在 head 里，无收益）、
  `notification-manager.js`（lazy——依赖用户交互）、
  `tri-state-panel-*.js`（通过 importmap 加载，wiring 路径不同）。

#### 来源

Commit `4cc367a` · 24 测试在 `tests/test_critical_preload_r21_1.py`。

### R21.2 · Service Worker 静态资源 cache-first

#### 问题

即使有 R21.1 preload，每个新浏览器会话仍需从服务器重新下载 ~80 个静态
资源。`?v={{ app_version }}` cachebuster 让 HTTP cache **在同一会话内**
工作，但全新会话、硬刷新或不同 tab 仍要为字节没变的资源付完整 RTT。
本机 ~12 ms × 80 个 = ~1 s；slow-LAN 部署（MCP server 在另一台机器）
就是 ~150-200 ms × 80 = 12-16 s 的重复会话 RTT。

#### 方案：cache-first SW + 版本化 cache + FIFO 淘汰

`static/js/notification-service-worker.js` 之前是单职能 SW，仅处理
`notificationclick`。R21.2 让它变双职能：在保留 click handler 之外
新增静态资源 cache-first 层。

Cache 架构：

- `STATIC_CACHE_NAME = 'aiia-static-v1'`——版本化名字，未来 bump 到
  `-v2` 时 `activate` 阶段干净清掉旧 cache；
- `MAX_ENTRIES = 200`——cache 大小硬上限 + FIFO 淘汰；故意是近似 LRU
  而不是严格 LRU，因为严格 LRU 需要 per-entry 时间戳 bookkeeping，且
  内容寻址资源（`?v=hash`）让 cache 命中本身就是稳态；
- `CACHE_FIRST_PATTERNS`——白名单正则数组，覆盖 `/static/css/*`、
  `/static/js/*`、`/static/lottie/*`、`/static/locales/*`、
  `/static/images/*`、`/icons/*`、`/sounds/*`、`/fonts/*`、
  `/manifest.webmanifest`。用正则数组（不是 string-prefix 匹配）让
  审稿人逐项 review，未来 `/static/wasm/` 贡献者一眼知道在哪里注册。

`fetch` 守护三条件：

1. **仅 GET**——POST/PUT/DELETE 是状态变更，缓存绝对错误；
2. **仅同源**——跨域缓存会让用户看到第三方 CDN 我们不控制的奇怪行为；
3. **不带 `Accept: text/event-stream`**——SSE 长连接缓存会让
   EventSource 永远停在初始响应。

cache-first 主体：

```javascript
async function handleCacheFirst(request) {
  let cache;
  try { cache = await caches.open(STATIC_CACHE_NAME); }
  catch (e) { return fetch(request); }  // cache 基础设施失败 → 永不阻塞请求

  try {
    const cached = await cache.match(request);
    if (cached) return cached;
  } catch (e) { /* miss-on-error: 落到网络 */ }

  const networkResponse = await fetch(request);
  if (networkResponse?.ok && networkResponse.status === 200 &&
      (networkResponse.type === 'basic' || networkResponse.type === 'default')) {
    const responseClone = networkResponse.clone();
    cache.put(request, responseClone).then(
      () => trimCache(cache).catch(() => {}),
      () => {}  // quota exceeded → 静默
    );
  }
  return networkResponse;
}
```

`cache.put` 故意 fire-and-forget（`.then(...)` 不 `await`）——用户感知
延迟正好等于 `fetch(request)` 时间，永远不是 `fetch + cache.put`。
Cache 失败（quota exceeded、cache 已被清、磁盘满）一律静默吞掉，
因为网络响应已经在路上；让响应失败比让 cache 写失败更糟。

#### SW 注册解耦 `Notification` API

R21.2 之前，`static/js/notification-manager.js::init()` 在
`if (this.isSupported) { ... }` 分支*内部*注册 SW，其中 `isSupported`
检查 `'Notification' in window`。iOS 16-、隐私收紧的 Firefox、部分
嵌入式浏览器都把 `Notification` 关了，但**支持** `serviceWorker` 和
`Cache` API——这些用户在 R21.2 之前完全享受不到 cache-first 收益。

修法：把 `await this.registerServiceWorker()` 调用移到 else 分支
之外。`registerServiceWorker()` 内部已有的
`supportsServiceWorkerNotifications()` 守护尽管名字误导，但实现实际
只检查 `'serviceWorker' in navigator && Boolean(window.isSecureContext)`，
**不**做任何 Notification API 检查——所以前述被 Notification 闸住的
环境现在能正确注册 SW。

#### 测量

- 第一次会话：~80 资源 × ~12 ms RTT = ~1 s（vs R21.2 前无变化）；
- 第二次会话：~80 资源各 0-1 ms（cache 命中）≈ 0 RTT（-95%+ vs 全新网络）；
- slow-LAN 部署：80 × 150-200 ms = 12-16 s → 第一次会话之后 0 ms（-99%+）。

Cursor + Chromium + macOS 手工验证：冷开 Web UI（DevTools 看到 ~80 个
`/static/*` 200 OK），刷新（~80 个 `(ServiceWorker)` 200 OK，0-1 ms），
Cmd-Shift-R 强刷（仍命中 SW，因为 SW 注册在硬刷新中存活），关 tab 在
新窗口重开（仍命中——SW 是 per-origin 不是 per-tab），bump `app.version`
后刷新（版本变了的资源 cache miss、没变的资源仍命中——精确符合"版本
感知失效"语义）。

#### 权衡

R21.2 故意**不**做的事：

1. **不缓存 `/api/*`**——会话状态依赖，缓存会显示陈旧任务列表/设置；
2. **不缓存 HTML 响应**——HTML 携带所有静态资源 cache key 的 `?v=...`
   cachebuster；冻结 HTML 等于冻结整个版本机制；
3. **不实现 offline page fallback**——AIIA 是 LAN/loopback only，用户
   离线时 MCP server 也离线，AI agent 都没法调 `interactive_feedback`，
   没东西可以 fall back 到；
4. **不用 stale-while-revalidate**——版本化做得太规整（`?v={{ app_version }}`
   到处都是），没有"陈旧"状态需要 revalidate；cache 命中 ≡ 全新 fetch
   语义等价；
5. **SW 中不做 Brotli 协商**——那是 R21.4 的事；这里混进来等于同时
   shipping 两套竞争的压缩策略。

测试故意走 source-text invariant 而非 jsdom 集成测试，因为 Service
Worker 在 jsdom 中规范支持极差：`Cache` / `self.clients` /
`self.skipWaiting` 全是 stub，"通过"的 jsdom SW 测试主要证明 mock
内部一致，并不证明 SW 在真实浏览器里行为正确。26 个测试在
`tests/test_sw_static_cache_r21_2.py`。

#### 来源

Commit `ba30a61` · 26 测试在 `tests/test_sw_static_cache_r21_2.py`。

### R21.4 · Brotli 预压缩（br > gzip > identity）

#### 问题

R20.14-D 上线了 gzip 预压缩层，`_send_with_optional_gzip` 协商
`Accept-Encoding: gzip` 来服务 `<file>.gz` 副本。但 Brotli 自 2017
起所有主流浏览器原生支持（Chrome 50+、Firefox 44+、Safari 11+、Edge
15+），且在 gzip 基础上再省 17-23%——整个静态资源 payload 都在走
次优的 gzip-only 路径，而客户端能力其实够。

#### 方案：并行 `.br` 副本 + br 优先协商

三层，故意**叠加**在 R20.14-D 之上而不是替换（保证没装 brotli 的环境
仍享受完整 R20.14-D gzip 收益）：

1. **`scripts/precompress_static.py`** 新增 `compress_file_br()`，与
   `compress_file()` 完全对称（同样的 skip-by-extension /
   skip-by-size / skip-if-fresh / `tempfile + os.replace` 原子写入 /
   `compressed_size >= original_size` no-gain 反检语义），但产出
   `<file>.br`，用 `brotli.compress(raw, quality=11)`。Quality 11 是
   brotli 最高质量（0-11 scale）；每文件 10-50 ms，1.1 MB MathJax
   bundle 约 60-80 ms，全部在 commit time 一次性付清。脚本通过
   `try: import brotli except ImportError: BROTLI_AVAILABLE = False`
   优雅降级到 gzip-only，让没装 brotli 的旧 fork 环境继续工作；
2. **`web_ui_routes/static.py`** 新增 `_parse_accept_encoding()`，做
   严格的 RFC-7231 q-value 解析（正确处理 `gzip;q=0.5`，把 `br;q=0`
   排除出支持集），加 `_client_accepts_brotli()` 作为
   `_client_accepts_gzip()` 的 br 兄弟。`_send_with_optional_gzip()`
   中的协商变成 `br > gzip > identity`：客户端支持 br **且** `.br`
   存在 → 服务 `.br` 带 `Content-Encoding: br`；否则客户端支持 gzip
   **且** `.gz` 存在 → 服务 `.gz`（R20.14-D 行为完全保留）；否则
   服务原文件。函数名保留（向后兼容锚点——三个其他路由 handler 依赖
   它；改名等于多文件 diff 但零功能收益）；
3. **`pyproject.toml`** 把 `brotli>=1.2.0` 从 transitive（通过
   `flask-compress[brotli]`）提升为 first-class dep，让
   `pip install ai-intervention-agent` 总是显式装 brotli。

57 个 `.br` 文件 commit 进 repo 实现 clone-and-go 操作，权衡数学
和 R20.14-D 的 `.gz` 文件相同——把 ~543 KB 字节进 git 历史 vs 让
每次 clone 都先跑 `python scripts/precompress_static.py`。Brotli
确定性输出让 `.br` 文件在不同机器上字节级可重现（与 gzip 的
`mtime=0` 类似），所以 commit history 增长被源文件变化频率约束
（这是稳定代码库，频率本身就低）。

#### 测量

| 资源 | 原始 | gzip | Brotli | br vs gzip |
|------|----:|-----:|-------:|-----------:|
| `tex-mml-chtml.js` | 1173 KB | 264 KB (-77%) | 204 KB (-83%) | -22.7% |
| `lottie.min.js` | 305 KB | 76 KB (-75%) | 64 KB (-79%) | -16.3% |
| `main.css` | 244 KB | 47 KB (-81%) | 37 KB (-85%) | -21.4% |
| `zh-CN.json` | 11 KB | 4.3 KB (-62%) | 3.5 KB (-69%) | -19.0% |
| `en.json` | 11 KB | 3.7 KB (-67%) | 3.2 KB (-72%) | -16.0% |
| **静态资源总计** | **2.5 MB** | **796 KB (-68%)** | **543 KB (-79%)** | **-32%** |

净收益：

- **+253 KB 节省** vs R20.14-D gzip-only baseline（增量 -32%）；
- **总 -79%** vs 原始 payload（vs R20.14-D 的 -68%）；
- 最大单资源（`tex-mml-chtml.js`）从 1.17 MB 掉到 204 KB。

#### 权衡

R21.4 故意**不**做的事：

1. **不加 zstandard 预压缩**——能在 brotli 基础上再省 5-10%，但 Safari
   2026 年仍在观望（Chrome 123+ / Firefox 126+ 支持 `Content-Encoding:
   zstd` 但 Safari 没动作）；
2. **不加 HTTP/3 + 0-RTT**——正交，是网络栈层关注；
3. **不加 per-asset 压缩字典**——需要源语言分析，按当前资源 mix 不
   划算；
4. **不动运行时 CPU 路径**——只走预压缩副本；不在请求路径上做 on-the-fly
   Brotli 压缩（`flask-compress` 已经为没有 `.br` / `.gz` 副本的资源做
   on-the-fly，但我们的副本覆盖了所有大文件）。

#### 来源

Commit `c095185` · 43 测试在 `tests/test_brotli_precompress_r21_4.py`。

## 第 3 层 · VSCode 插件（R21.3 · 否决，保留推理）

### 调研中的问题

`packages/vscode/webview-ui.js` 约 5086 行 / 170 KB；加上 5 个手写
sibling module（`webview-helpers.js` 158 行、`webview-notify-core.js`
268 行、`webview-settings-ui.js` 778 行、`webview-state.js` 156 行、
`i18n.js` 1057 行），总 ~7503 行 / 248 KB webview 端 JS。

假设的 R21.3 会让所有 6 个走 `esbuild --bundle --format=iife` 产出
单一 bundle 文件：

- 减少 5 个 HTTP round-trip（vscode-webview:// 是本地 IO，但每次仍有
  disk-read + script-eval init 开销）；
- 启用对 `export` 但未 `import` 符号的 dead-code elimination；
- 为未来可能的 `--minify` / `--treeshake` 开门，如果体积变重要的话。

### R21.3 为什么被否决

#### 1. 真正的冷启动已经被压缩

R20.13 把 VSCode 扩展激活从 8.12 ms → 30 µs（-99.6%），靠的是
`BUILD_ID` 懒加载 + 5 个其他 sub-cut。R20.13 批次已经打到了高杠杆
点（同步文件系统读取、同步 `getExtension` 调用、eager locale 注册）。
Webview HTML 渲染已经做了 JSON 缓存（`_cachedInlineAllLocalesJson`）。

#### 2. 打包收益在噪声层以下

R21.3 假设的粗略估算：

- 5 个 vscode-webview:// HTTP round-trip 消除：每个 0.5-2 ms → 共
  2-10 ms，**但**它们在 HTML 解析过程中是并行的，所以串行 wall-time
  收益约 **2-5 ms**；
- 手写模块的 DCE：通常 <1 KB 节省字节；module loader 在 init 期间
  本来就 parse 全部，所以连节省的字节都不转化为 eval 时间收益；
- CPU eval 时间：248 KB 未 minify 的 JS 在 M1 Chromium 上 parse
  ~5-10 ms；不开 `--minify` 的 bundling 不缩 eval 时间（parse-time
  被 JS 引擎 warmup 主导，不是 wire bytes）。

合计：估算 **2-10 ms**，**几乎肯定在或低于 ~5 ms 的 abs-floor**，
而 `scripts/perf_gate.py` 用这个 floor 抑制亚毫秒 benchmark 上的
误报回归。

#### 3. 真实成本不低

干净落地 R21.3 需要：

1. **加 esbuild 作为 dev dep**（同步调整 `package.json::scripts`、
   `Makefile`、CI matrix）；
2. **`scripts/package_vscode_vsix.mjs` 加预构建步骤**——当前 includeList
   原样复制手写 .js 文件；bundling 意味着产出 `dist/webview-bundle.js`
   并让 `includeList` 引用它，外加更新 `webview.ts::_getHtmlContent`
   里 ~6 个 `<script src="...">` URI；
3. **CSP nonce 处理**保持不变（单 bundle、单 nonce），但
   **source-map 处理**变复杂：VSCode CSP 严格，可能拒绝 `eval` 风格
   source maps；要么 ship `.map` 文件并配 `webview.asWebviewUri` 服务
   它们，要么砍掉 source-map 接受更差的调试体验；
4. **byte-parity 测试**（`tests/test_tri_state_panel_parity.py` 已经
   把 `static/js/tri-state-panel.js` ↔ `packages/vscode/tri-state-panel.js`
   字节级锁住）——bundling `webview-ui.js` 不直接破坏这个（tri-state-panel
   是单独的文件），但引入一个**新**的 source-of-truth 问题：如果
   `webview-ui.js` 现在是 `dist/` 产物，build-reproducibility 故事是什么？
   不同 esbuild 版本能产出不同字节；`dist/webview-bundle.js` 是 commit
   还是 build-on-demand？
5. **测试重写**：`tests/test_vscode_*.py` 中 30+ 个测试直接读
   `packages/vscode/webview-ui.js` 当字符串然后 grep 模式。Bundling 会
   重排/重命名符号，破坏 ~所有这些测试；要从头写
   `tests/test_vscode_bundle_*.py`。

估计成本：**2-3 天细致工程 + ~50 个测试重写**，换来 **2-10 ms**
wall-time。ROI 明显是负的。

#### 4. "故意不优化" 的先例

R20.x 已经建立这个模式。R20.14 文档了六个负面决策的成本-收益推理，
这样未来贡献者不会重新调研已经关闭的问题。R21.3 加入这个列表。

### 如果将来重新评估 R21.3 能解锁什么

如果未来某个 R22.x 批次发现 VSCode webview 冷启动退化回 >50 ms
（比如有人加了一个肥模块让 JS payload 翻倍），成本/收益数学可能
反转：把 500 KB JS 打成单个 chunk 会按比例省更多 eval-time，"搭
esbuild + 测试基础设施" 的固定成本会摊薄到未来更多模块上。决策
要重跑测量，而不是反射式采纳。

## 复现数据

Bench 脚本和测试在 repo：

```bash
# 服务端 benchmark（R20.x baseline；R21.x 是浏览器侧所以无影响）
uv run python scripts/perf_e2e_bench.py --quick --output /tmp/p.json
uv run python scripts/perf_gate.py --results /tmp/p.json

# 浏览器侧：在 Chromium DevTools 打开 Web UI，看 Network 面板：
# - 第一次加载：~80 个 /static/* 请求，全 200 OK
# - 刷新：~80 个 (ServiceWorker) 响应，多数 0-1 ms
# - 检查 /static/js/tex-mml-chtml.js 响应：Content-Encoding: br

# Brotli 预压缩幂等检查：
uv run python scripts/precompress_static.py --check  # 全 fresh 时 exit 0
uv run python scripts/precompress_static.py          # 按需重生成
```

硬件参考：Apple Silicon M1 / Python 3.11.15 / macOS 25.4.0 / Cursor
+ VSCode 开发环境。

## 未来工作

未约束指针，给将来 R22.x+ 批次。**先按 R20.14-A 加 benchmark，再测量
后 `--update-baseline`，最后给本路线图追加章节**——让 harness + gate
+ docs 系统延续而不是腐败。

- **图片格式现代化**——把 PNG/JPEG 兜底转 AVIF + WebP 中间；预期
  `static/images/*` -20-40%；
- **`service_manager` 轮询整合**——目前三个 `setInterval` 周期跑
  在不同节奏；合并能省 ~1% idle CPU；
- **HTTP/2 server push**——CDN 配置非平凡，预期收益低；
- **R21.3 webview esbuild bundling**——见上面否决推理；如果 webview
  冷启动退化超过 50 ms 可重新评估；
- **zstandard 预压缩**——等 Safari 支持；
- **HTTP/3 + 0-RTT**——和编码层正交，是网络栈关注。

## 交叉引用

- 第 1-4 层 baseline 由 R20.x 确立：
  [`docs/perf-r20-roadmap.zh-CN.md`](perf-r20-roadmap.zh-CN.md);
- End-to-end perf bench：
  [`scripts/perf_e2e_bench.py`](../scripts/perf_e2e_bench.py);
- 回归 gate：
  [`scripts/perf_gate.py`](../scripts/perf_gate.py);
- Baseline 数据：
  [`tests/data/perf_e2e_baseline.json`](../tests/data/perf_e2e_baseline.json);
- 各功能测试：
  [`tests/test_critical_preload_r21_1.py`](../tests/test_critical_preload_r21_1.py)、
  [`tests/test_sw_static_cache_r21_2.py`](../tests/test_sw_static_cache_r21_2.py)、
  [`tests/test_brotli_precompress_r21_4.py`](../tests/test_brotli_precompress_r21_4.py)。
