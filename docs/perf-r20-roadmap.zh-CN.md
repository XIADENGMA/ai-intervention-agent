# R20.x 性能优化路线图

> English: [`perf-r20-roadmap.md`](perf-r20-roadmap.md)

本文档汇总 **R20.x 性能优化批次**（R20.4 → R20.14）的设计依据、测量数据
和取舍记录。这一批改造把"AI agent 调用 `interactive_feedback` → 用户看到
Web UI"的端到端 wall-clock 延迟从 **~1980 ms** 压到 **~360 ms**（-82%），
覆盖四层优化目标。

## 为什么需要这份文档

R20.x 落了 11 个 commit，每个 commit message 详细写了「这次改了什么」。
但完整的 *叙事* —— 这些层是怎么叠起来的、阈值是怎么定的、哪些故意没
优化 —— 是分散的。这份路线图把它们集中到一处，给：

- **代码 reviewer**：审查未来某次改动会不会无意打回 R20.x 的某条优化；
- **未来的优化作者**：找出下一个 30%（或者认清剩下的都是边际收益不值得
  动的位置）；
- **运维**：用 `tests/data/perf_e2e_baseline.json` 的基线对比，调试
  「为什么我 fork 的版本性能退化了？」。

## 四层路线图

用户的最初指令：

> 深挖性能优化，先从本体 MCP 开始，再到网页, 再到插件, 再到整体, 都要进行性能优化。

每层的瓶颈分布和工具链都不同，所以我们按顺序逐层啃：

| 层 | 轮次 | 重心 | 单层墙钟收益 |
|----|------|------|------|
| 本体 MCP | R20.4–R20.10 | 冷启动 `import` 时间、惰性模块加载 | 425 ms → 156 ms（-63%） |
| 本体 MCP | R20.11 | mDNS 异步发布（Web UI 子进程 spawn-to-listen） | 1922 ms → 203 ms（-89%） |
| 网页 | R20.12 | 浏览器运行时冷启动（FCP、locale、图像解码） | 首屏减负约 150 ms |
| 插件 | R20.13 | VSCode 插件激活 + webview 渲染 | 8.12 ms → 30 µs 激活（-99.6%） |
| 整体 | R20.14 | 跨层 harness、回归 gate、资源压缩、文档 | （详见 R20.14 节） |

## 第 1 层 · 本体 MCP 冷启动（R20.4 – R20.10）

### 问题

MCP 服务器的 `import web_ui` 是冷启动头号开销：通过 transitive imports
拖进 Flask、Pydantic、Zeroconf、所有通知 provider。R20.4 之前实测：
`python -c "import web_ui"` 中位数 **425 ms**。

### 策略：lazy `find_spec` + first-touch hoist

R20.4 没去逐个追大依赖，而是引入一种范式（之后 R20.5–R20.10 持续套用）：

1. 模块加载时**只**做 `importlib.util.find_spec(name)` 验证可选依赖
   是否存在 —— 每次 ~100 µs，远小于真实 import 的 5–50 ms；
2. 绑定 `_HAS_FOO = bool(spec)` 标志，给下游 feature gate；
3. 第一个真正需要 `foo` 的请求 handler 做局部 `import foo` —— 一进程
   只付一次，**而且**是用户触发该功能之后才付。

这个设计把 ~270 ms 的 import 工作从冷启动挪到（多数情况下不可见的）
首请求路径。通知 provider（Bark、Telegram、Discord、plyer）是最大头 ——
绝大多数用户一个会话里没碰过任何 provider，于是这些代价就被永久摊销。

### 测量数据

| 轮次 | 中位 import 时间 | 节省 | 累计 |
|------|----:|----:|----:|
| R20.4 之前 | 425 ms | — | — |
| R20.10     | 156 ms | -269 ms | -63% |

`scripts/perf_e2e_bench.py::bench_import_web_ui` 是与这条配套的回归基准。

### 取舍

- **首请求慢约 50 ms**（lazy 路径下）。我们核对过：在典型 AI 工具
  ~200–500 ms 网络 round-trip 面前不可见。可以接受。
- **`find_spec` 调用要散布在每个用得到的地方**，否则漏一个
  `_HAS_FOO` 守卫就会让 `foo` 在 hot path 进入时再 import 一次。19 条
  mock-friendly 测试（`tests/test_lazy_*`）锁住这个纪律。

## 第 1.5 层 · 子进程 spawn-to-listen（R20.11）

### 问题

R20.10 把 import 砍掉之后，Web UI 子进程从 `subprocess.Popen([python,
web_ui.py, ...])` 到 socket listen，仍然要 **1922 ms** 中位数。深挖
发现：里面 1.7 s 卡在 `zeroconf.register_service` —— 按 RFC 6762 §8 要
连发 3 次 250 ms 的多播探测，再做 announcement。

### 策略：异步 daemon 线程发布

`WebFeedbackUI.run()` 不再等 `_start_mdns_if_needed`。它启一个 daemon
线程（`name="ai-agent-mdns-register"`）后台跑 mDNS，主线程立刻进
`app.run()` 的 listen 状态。

正确性补丁：

- `_stop_mdns` 用 2 秒 timeout 来 join 这个线程（略大于典型的 1.7 s
  register 完成时间，让 95% 的正常关闭能等到 unregister + announcement
  落地）；
- `daemon=True` 是关键 —— 没它，卡住的 mDNS 探测会让 Web UI 子进程
  关停永远阻塞；
- 单元测试**直接** call `_start_mdns_if_needed` 仍保持同步语义（threading
  封装只在 `run()` 调用点，不在函数内部）。

### 测量数据

| 轮次 | spawn → socket listen | 节省 |
|------|----:|----:|
| R20.11 之前 | 1922 ms | — |
| R20.11      |  203 ms | **-1718 ms / -89.4%** |

这是整个 R20.x 批次里**用户感知收益最大的单点**。和 R20.10 的 import
节省叠加：完整的 Web UI 子进程冷启动从 ~1980 ms → ~360 ms（-82%）。
"AI 调工具 → 用户看到 UI" 的延迟现在主要被 AI 客户端的网络 RTT 主导，
不再是我们这边的瓶颈。

### 取舍

- "mDNS 已发布" 那行 stdout 现在出现在 "Running on http://..." **之后**
  而不是之前。纯外观差异，没人在程序里 parse 它；
- 极快 SIGTERM（子进程 spawn 后 100 ms 内 Ctrl-C）下，daemon 线程可能
  被中断在 register 一半。但 LAN 上没人看到过那次半成品广播，所以也
  没什么要清理的；Zeroconf 自己的 TTL 清理机制处理最终一致性。

## 第 2 层 · 浏览器运行时（R20.12）

### 三条正交的浏览器侧改动

R20.12 把浏览器从 HTML 接到首屏画面这条路的每个字节过了一遍：

**R20.12-A · `mathjax-loader.js` 加 `defer`**

`<script>/static/js/mathjax-loader.js</script>` 原本是 head 同步阻塞。
但这个脚本本身只声明 `window.MathJax` 配置 + helper 函数，真正 1.17 MB
的 `tex-mml-chtml.js` 是用户首次粘贴含数学公式 Markdown 时才动态
appendChild。加 `defer` 让 HTML parsing 不再被它卡住。**省 5–10 ms 头
部解析阻塞。**

**R20.12-B · 已知语言时内联 locale JSON**

当 `web_ui.config.language ∈ {'en', 'zh-CN'}`（即非 `'auto'`），
`_get_template_context` 通过 `@lru_cache(maxsize=8)` 包裹的
`_read_inline_locale_json()` 读取对应 `static/locales/<lang>.json`，把
压缩后的 JSON 内联进 HTML 的 `window._AIIA_INLINE_LOCALE`。`i18n.init()`
JS 优先消费内联值，跳过原本必跑的 `fetch /static/locales/<lang>.json`。

**冷加载每次省 30–80 ms RTT**（哪怕 HTTP cache 命中也要付 11 KB 的
locale 拉取）。XSS 防御：内联 JSON 里的 `<` 全部转义成 `\u003c`。

**R20.12-C · `createImageBitmap` 替换图片解码**

`compressImage` 从老的 `new Image() + URL.createObjectURL(file) +
img.onload` 同步路径，迁到现代的 `createImageBitmap(file)` async 路径。
老路径作为 `_loadImageViaObjectURL` fallback 留给 Safari < 14 / 旧 Firefox。
**modern Chromium / Firefox 105+ / Safari 14+ 上单图压缩 wall time -50–200 ms。**

### 测量

`tests/test_browser_perf_r20_12.py`（27 条不变量测试）锁住源码行为。
端到端 FCP 在 CI 上不是稳定指标（受浏览器、GPU、DPI 影响），所以没
单一数字 —— 但每条改动都自包含且可单独测量。

### 取舍

- **`mathjax-loader.js`** 现在是 `defer` 而非同步加载。由于真正的
  MathJax bundle 是运行时动态 append 的，对最终行为没观察差异；
- **内联 locale JSON** 给 HTML 响应加 ~11 KB。`language='auto'`（新装
  默认值）模式下不内联，零代价；显式语言模式下，+11 KB 内联永远胜过
  +11 KB locale 拉取；
- **`createImageBitmap` fallback** 保留老路径 —— 不破坏老 Safari / FF
  用户体验。

## 第 3 层 · VSCode 插件（R20.13）

### 六条正交改动

R20.13 深挖了 VSCode 插件激活 + webview HTML 生成两条路：

**R20.13-A · 惰性 `BUILD_ID`** —— 把模块加载期同步 fork+exec
`git rev-parse --short HEAD` 的 IIFE 重构成 `getBuildId()` 函数，并用
`fs.existsSync('.git')` 守卫。**生产 VSIX 安装每次激活 8.12 ms → 30 µs
（-99.6%）**（开发树仍然付完整 ~8 ms 拿真 SHA —— 故意的）。

**R20.13-B/F · 构造器注入 `extensionVersion`** —— `WebviewProvider`
现在构造器接收 `extensionVersion` 参数（由 `activate` 一次性传入），
取代 `_getHtmlContent` 每次渲染都调一次 `vscode.extensions.getExtension()`。
**每次 HTML 渲染省 ~1–3 ms。**

**R20.13-C · 异步并行 locale 读取** —— host 侧 i18n locale 加载从串行
`fs.readFileSync` 改成并行 `Promise.all + fs.promises.readFile`，I/O
等待时间砍半（绝对值微秒级，但建立了 async-friendly 初始化的契约）。

**R20.13-D · 惰性 locale 注册** —— `webview-ui.js::ensureI18nReady`
原本 eager 注册所有 locale（`Object.keys(__AIIA_I18N_ALL_LOCALES)`），
现在只 eager 注册 active 语言 + `'en'` 兜底（`i18n.js::_resolvePath` 行
558–559 契约要求 `'en'` 永远存在做 missing-key fallback）。新增
`ensureLocaleRegistered(lang)` helper 在 `applyServerLanguage` 检测到
运行时切语言时按需补注册。**启动期省 50–100 µs。**

**R20.13-E · 缓存内联 `allLocales` JSON** —— `_getHtmlContent` 把
`safeJsonForInlineScript(allLocales)` 缓存到两个新字段，cache key 是
`"<sorted-names>:<entry-counts>"` —— locale 集合任何变动都会自动失效。
**每次渲染省 50–100 µs。**

### 测量

| 改动 | 节省 |
|------|----:|
| A · 惰性 BUILD_ID | -8.09 ms / 激活（-99.6%） |
| B/F · ctor extensionVersion | -1–3 ms / 渲染 |
| C · async 并行 locale | 砍半（亚毫秒） |
| D · 惰性 registerLocale | -50–100 µs / 启动 |
| E · 缓存 allLocales JSON | -50–100 µs / 渲染 |

A 是头条数字。C/D/E 是噪声地板级优化；之所以保留是因为用户明确表态
（"领导表态类坚持"）且都是零风险纯重构。

`tests/test_vscode_perf_r20_13.py`（25 条测试）锁住所有六条改动。

### 取舍

- **惰性 BUILD_ID** 意味着如果构建流水线忘了替换 `__BUILD_SHA__`，
  生产 VSIX 会显示 `'dev'`。构建脚本（`scripts/package_vscode_vsix.mjs`）
  会做替换；如果哪天它停止替换，症状是良性外观差异（`'dev'` 而不是
  `'0a1b2c3'`）。

## 第 4 层 · 整体系统（R20.14）

R20.14 拆四个子轮：A（harness）、C（跨进程）、D（资源压缩）、E（本文档）。

### R20.14-A · 端到端性能 harness + 回归 gate

`scripts/perf_e2e_bench.py` 通过 subprocess 隔离测 5 条 wall-clock
benchmark：

| benchmark | 测什么 | R20.x 之后基线（中位） |
|------|------|----:|
| `import_web_ui` | `python -c "import web_ui"` 冷时间 | 156 ms |
| `spawn_to_listen` | `subprocess.Popen([python, web_ui.py])` → socket listen | 203 ms |
| `html_render` | `_get_template_context()` + `render_template()` | 0.07 ms |
| `api_health_round_trip` | localhost `/api/health` GET | ~3 ms |
| `api_config_round_trip` | localhost `/api/config` GET | ~3 ms |

`scripts/perf_gate.py` 把当前 `perf_e2e_bench.py --output current.json` 跟
`tests/data/perf_e2e_baseline.json` 比对。每条 benchmark 的回归容忍度是
`max(baseline × pct_threshold, abs_floor_ms)` —— 默认 30% pct + 5 ms 绝
对地板。亚毫秒 benchmark（`html_render`）走绝对地板（5 ms = 基线 ~70×，
故意宽，避免 CI 噪点误报）。

发布新基线（在故意做了改动并测过之后）：

```bash
uv run python scripts/perf_e2e_bench.py --output /tmp/perf.json --quiet
uv run python scripts/perf_gate.py --results /tmp/perf.json \
    --update-baseline --baseline tests/data/perf_e2e_baseline.json
```

baseline JSON 顶层可选 `thresholds: {bench_name: pct}` 让运维单独收紧
某条 benchmark（适用于本身比全局更确定性的指标）。

### R20.14-C · 跨进程热路径优化

"MCP `task_status_change` → 插件状态栏更新" 完整链路：

```
TaskQueue._trigger_status_change
  → _on_task_status_change         # web_ui_routes/task.py 注册的回调
    → _SSEBus.emit                 # 发布给所有 SSE 订阅者
      → SSE generator              # 给每个订阅者格式化 yield 事件行
        → 插件 _connectSSE         # 解析 ev.new_status
          → 80 ms 防抖              # 合并突发事件
            → fetch /api/tasks     # 3 ms RTT, source of truth
              → 状态栏更新
```

**已落地的优化：**

1. **`_SSEBus.emit` 锁紧缩** —— 只在 `_lock` 内 `list(self._subscribers)`
   拍快照；`put_nowait` 在锁外执行。`emit` 临界区从 O(N 订阅者) 降到
   O(1)。死队列清理时短暂重新拿锁做 `set.discard`；
2. **emit 单次预序列化** —— `json.dumps(data)` 在 emit 里一次性算好，
   存进 `payload['_serialized']`。生成器直接消费它。N 个订阅者时省
   (N−1) 次 `json.dumps`；
3. **task_changed 事件嵌入 stats** —— `_on_task_status_change` 在
   queue 锁外 call `get_task_count()`，把
   `stats: {pending, active, completed}` 塞进 SSE payload。插件能在
   `fetch /api/tasks` 还没返回前就**乐观**渲染状态栏，fetch 仍然跑作
   为 canonical source of truth（用于新任务检测）；
4. **插件乐观状态栏** —— `extension.ts` 的 SSE handler 现在读
   `ev.stats`，存在时立刻 `applyStatusBarPresentation`。80 ms debounce
   + `fetch /api/tasks` 仍在跑 —— 它们只是不再阻塞用户可见的 UI 更新。

**取舍：**

- **锁紧缩**带轻微契约变化：在 `emit()` 调用过程中（snapshot 之后）新
  `subscribe()` 进来的订阅者会错过这条事件。语义上和之前一致 ——
  `subscribe()` 在锁释放后才能进集合 —— 但值得显式说明；
- **stats 嵌入**让每次 `task_changed` 事件多一次 `get_task_count()`
  调用（O(n) 遍历当前任务）。n 实际典型 < 100；如果未来负载能把它
  推高，可能需要切到维护型计数器；
- **乐观 UI 更新**可能短暂显示陈旧数据（如果 SSE 事件来自老快照 —— 即
  `_trigger_status_change` 和另一个变更竞态）。fetch 在 ~85 ms 内
  纠正。可接受的 trade-off。

`tests/test_cross_process_perf_r20_14c.py`（22 条测试）锁住契约。

### R20.14-D · 静态资源 gzip 预压缩

**问题：** `static/js/tex-mml-chtml.js` 1.17 MB；`static/js/lottie.min.js`
300 KB。Flask-Compress（`flask_compress.Compress(self.app)`）已经接好了，
但它**每次请求都做 on-the-fly gzip**，level=6。每个未缓存大文件响应
~3–5 ms 运行时 CPU。

**解决：** `scripts/precompress_static.py` 走 `static/css`、`static/js`、
`static/locales`，对每个生成 `<file>.gz` 副本（gzip level=9，`mtime=0`
保证可重现）。serve 端 `_send_with_optional_gzip` 检查
`Accept-Encoding: gzip` 与 `<file>.gz` 是否存在，两者都满足时返回预
压缩字节 + `Content-Encoding: gzip` 头 + 原 `Content-Type`。无论是否
压缩，都打 `Vary: Accept-Encoding` 头让 CDN / 中间缓存正确分桶。

**测量：** 2624 KB 源 → 661 KB gzipped（-75%）。63 个文件总计释放
1916 KB。最大单点收益：`tex-mml-chtml.js` 1173 KB → 264 KB（-77%）。

**压缩阈值：** 500 字节（对齐 `flask-compress` 的 `COMPRESS_MIN_SIZE`
默认值）。更小的文件 gzip 18 字节头开销不划算。我们故意没用 Brotli ——
它比 gzip 再小 15–20%，但要 `pip install brotli` 运行时依赖。未来某轮
R20.x 如果有指标支撑可以再考虑。

**工作流：**

```bash
# 生成新鲜 .gz 副本（idempotent：mtime=0 让重复跑产出 byte-identical 输出）
uv run python scripts/precompress_static.py

# CI gate：任何 .gz 过期就 exit 1
uv run python scripts/precompress_static.py --check

# 清理（比如做新实验前）
uv run python scripts/precompress_static.py --clean
```

`tests/test_static_compression_r20_14d.py`（35 条测试）覆盖脚本、
协商器（`_client_accepts_gzip`）、helper（`_send_with_optional_gzip`）
和通过真实 `WebFeedbackUI` test client 跑的端到端集成。

**取舍：**

- `.gz` 文件 commit 进 repo（增加 ~640 KB git 体积）。考虑过
  `.gitignore`，但小项目里 commit-and-go 比 "新 clone 必须 build" 更
  友好。`mtime=0` 让 PR diff 最小化 —— 只有源真的改了才会动 .gz；
- `flask-compress` 与我们的预压缩并存，靠 flask-compress 自身
  `after_request` hook 检查 `Content-Encoding` 已设置时跳过的契约。
  我们显式测过共存（`test_serve_js_no_accept_encoding_returns_uncompressed`）。

### R20.14-E · 本文档

你正在读。

## 我们故意**不**做的优化

挑选什么不做和挑选什么做同等重要。下列候选已调研但被否决：

- **service_manager 健康检查 polling** —— R20.11 之后调研过：Web UI
  子进程在 203 ms 进入 listen 状态，但 polling interval 是 200 ms。
  最坏情况额外延迟 < 10 ms（下次 poll 在 200 ms 内落地，但那时
  子进程通常已经在 listen 了）。代码改动不值；
- **multi_task.js `setInterval` 合并** —— 多个任务的倒计时计时器并行
  跑。合并到一个主 `requestAnimationFrame` loop 能省每任务 ~50 µs。
  但对计时器有序性的细微回归风险大于收益；
- **激进图像格式转换** —— 自动把粘贴的 PNG 转 WebP。现代浏览器对两者
  支持都很好；用户剪贴板里的 PNG 是他们预期上传的；
- **Brotli 预压缩** —— 比 gzip 再小 15–20%，但要 `brotli` Python
  运行时包。等到有用户实测 transfer-size 抱怨再说；
- **VSIX 体积削减** —— `mathjax/` 在 VSIX 里 2.0 MB。删掉会破坏
  webview 离线数学渲染。CDN fallback 不可行（VSCode webview CSP 限制
  外部加载）；
- **HTTP/2 server push** —— Flask 自带 stdlib HTTP server 不支持 HTTP/2。
  要换 `gunicorn`/`uvicorn` + 前置反代，是大架构改动，仅为了边际
  首屏收益。

## 复现这些数字

```bash
# Clone、装依赖、跑 benchmark
git clone https://github.com/xiadengma/ai-intervention-agent
cd ai-intervention-agent
uv sync --all-extras
uv run python scripts/precompress_static.py    # 生成 .gz 副本
uv run python scripts/perf_e2e_bench.py --format table

# 与基线对比
uv run python scripts/perf_e2e_bench.py --output /tmp/perf.json --quiet
uv run python scripts/perf_gate.py --results /tmp/perf.json
```

如果你的机器比我的 Apple M1 显著快或慢，数字的*形状*应该仍成立（即
`import_web_ui ≈ 1.5× spawn_to_listen ≈ 50× api_round_trip ≈ 2000×
html_render`）。如果比例剧烈漂移，加 `--verbose` 看每条 bench 的
`samples_ms` 数组，找异常值，附 JSON 输出开 issue。

## 后续工作

R20.x 完成了用户最初提出的四层路线图。可能的 R21+ 方向：

- **Brotli 预压缩** —— 等到有遥测显示 transfer size 是某用户的瓶颈
  （比如远程隧道走慢链路）；
- **HTTP/2 + server push** —— 需要换 Flask stdlib server。最好和
  独立的「生产部署指南」RFC 配套做；
- **Service worker 离线资源缓存** —— 通知 service worker 已经存在但
  只处理通知。扩展它去缓存 static JS/CSS 能让重复访问瞬时；
- **Webview 资源 bundling** —— `webview-ui.js` 168 KB 未压缩。esbuild
  → 50 KB 压缩后让 webview 冷缓存下也能 16 ms 内渲染。trade-off：构
  建复杂度。

如果你做这些里的任何一个，请：

1. 先给 `scripts/perf_e2e_bench.py` 加一条 benchmark（R20.14-A 范式）；
2. 测过后用 `--update-baseline` 刷新基线；
3. 在本文档追加一节，记录设计 + trade-off。

— xiadengma 与贡献者
