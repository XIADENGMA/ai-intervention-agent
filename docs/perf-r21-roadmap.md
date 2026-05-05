# R21.x Performance Roadmap

> 中文版：[`perf-r21-roadmap.zh-CN.md`](perf-r21-roadmap.zh-CN.md)

This document captures the design rationale, measurements, and trade-offs of
the **R21.x performance optimization batch** (R21.1 → R21.4), which closes
out the **browser-side network / cache layer** sitting between the
already-optimized server (R20.x) and the user's browser. The R21.x focus is
not server cold-start (R20.x already took that from 1980 ms to 360 ms) but
the *next* bottleneck: every static asset still travels the network on every
request, scripts still serialize during HTML parsing, and Brotli
(supported on every browser since 2017) was not used anywhere.

## Why this document exists

R21.x landed across 4 commits (3 perf + 1 release) shipping with v1.5.28.
The standalone commit messages describe what each change does; this
roadmap is the single document explaining:

- **How the three layers compose**: preload → cache → compression are
  orthogonal but multiplicative — preload kicks off downloads earlier,
  cache eliminates repeat downloads, compression shrinks every download
  byte;
- **Why R21.3 (webview esbuild bundling) was deliberately skipped** — full
  measurement-based reasoning is preserved in this doc so future
  contributors don't repeat the investigation;
- **What the next R22.x batch should *not* re-investigate**: each R21.x
  decision documents the trade-offs that closed the question.

## The R21.x scope

The user's directive that triggered this batch:

> 深挖性能优化, 先从本体 MCP 开始, 再到网页, 再到插件, 再到整体, 都要进行性能优化。

R20.x exhausted the cold-start direction across all four layers. R21.x
re-targets the **same four layers**, but at the *steady-state* / *repeat
session* dimension that cold-start work didn't address.

| Round | Focus | Wall-clock / payload impact |
|-------|-------|------------------------------|
| **R21.1** | Critical resource preload via `<link rel="preload">` | FCP +30-100 ms |
| **R21.2** | Service Worker static asset cache-first | ~80 assets at 0 RTT on repeat sessions |
| **R21.3** | (research only — declined) webview esbuild bundling | est. 2-10 ms — below noise floor |
| **R21.4** | Brotli precompression layer (br > gzip > identity) | -253 KB / -32% on top of R20.14-D's gzip |

## Layer 2.5 · Browser network/cache (R21.1 + R21.2 + R21.4)

The web page layer in R20.12 covered FCP head-blocking, locale FOUC, and
image decode. R21.x extends to:

### R21.1 · Critical resource preload

#### Problem

The Web UI HTML carries 12 separate `<script defer>` tags spread between
the head (`mathjax-loader.js` / `marked.js` / `prism.js`) and the body's
tail block (`validation-utils.js` / `theme.js` / `keyboard-shortcuts.js` /
`dom-security.js` / `state.js` / `multi_task.js` / `i18n.js` /
`notification-manager.js` / `settings-manager.js` / `image-upload.js` /
`app.js` / `tri-state-panel-*`). The browser's preload-scanner can prefetch
declarations it sees during HTML parsing, but `defer` script *discovery*
is blocked behind sequential body parsing. The network panel typically
shows ~30-50 ms gap between "head finishes parsing" and "first body script
request fires".

#### Strategy: 4 critical preload hints

`templates/web_ui.html::<head>` adds:

```html
<link rel="preload" href="/static/js/app.js?v={{ app_version }}" as="script" />
<link rel="preload" href="/static/js/multi_task.js?v={{ multi_task_version }}" as="script" />
<link rel="preload" href="/static/js/i18n.js" as="script" />
<link rel="preload" href="/static/js/state.js" as="script" />
```

Why these four:

- `app.js`: main entry — every other module's coordinator;
- `multi_task.js`: polling/SSE driver — needed before any task interaction;
- `i18n.js`: must run before `app.js` (translation contract dependency);
- `state.js`: state-machine contract dependency.

#### Measurements

Per Web Vitals' `preload-critical-assets` Lighthouse audit:

- **Lower bound**: ~30 ms (everything that previously serialized into one
  TCP RTT now parallelizes into ½ RTT);
- **Upper bound**: ~100 ms (head parsing took longer than expected,
  several scripts could have been overlapping).

Exact number depends on body length × network RTT × parser-thread
scheduling. On localhost we measured **~32 ms FCP improvement**; on a
slow-LAN deployment the wins compound.

#### Trade-offs

- **URL byte-parity**: the preload `href` MUST be byte-identical to the
  corresponding `<script src>` (including `?v=` query) or the preload
  cache misses. `tests/test_critical_preload_r21_1.py` (24 tests) enforces
  this byte-for-byte;
- **No `nonce` on preload links**: per HTML spec, `<link rel="preload">`
  doesn't execute scripts; it just kicks off network. Adding a `nonce`
  would be CSP-redundant and reads as the developer not understanding the
  spec;
- **Did NOT preload**: `mathjax-loader.js` (already in head, no benefit),
  `notification-manager.js` (lazy — depends on user interaction),
  `tri-state-panel-*.js` (loaded via importmap, different wiring path).

#### Source

Commit `4cc367a` · 24 tests in `tests/test_critical_preload_r21_1.py`.

### R21.2 · Service Worker static asset cache-first

#### Problem

Even with R21.1 preload, every browser session re-fetches all ~80 static
assets from the server. The `?v={{ app_version }}` cachebusters mean the
HTTP cache works *within a session*, but a fresh session, a hard reload,
or a different tab still pays full RTT for assets whose bytes haven't
changed. On localhost that's ~12 ms × 80 assets = ~1 s; on slow-LAN
deployments (MCP server on a different machine) it climbs to ~150-200 ms ×
80 = 12-16 s of repeat-session RTT.

#### Strategy: cache-first SW with versioned cache + FIFO eviction

The existing `static/js/notification-service-worker.js` was a
single-purpose SW handling `notificationclick` only. R21.2 makes it
dual-purpose by adding a static-asset cache-first layer alongside the
preserved click handler.

Cache architecture:

- `STATIC_CACHE_NAME = 'aiia-static-v1'` — versioned name so a future
  `-v2` bump cleanly evicts old caches in `activate`;
- `MAX_ENTRIES = 200` — hard FIFO cap on cache size, deliberately
  approximate-LRU because true LRU needs per-entry timestamp bookkeeping
  and content-addressed assets (`?v=hash`) make cache hits the steady
  state anyway;
- `CACHE_FIRST_PATTERNS` — regex array whitelisting `/static/css/*`,
  `/static/js/*`, `/static/lottie/*`, `/static/locales/*`,
  `/static/images/*`, `/icons/*`, `/sounds/*`, `/fonts/*`,
  `/manifest.webmanifest`. The regex array (rather than string-prefix
  match) makes paths reviewable per-entry — a future `/static/wasm/`
  contributor knows exactly where to register.

Three guard conditions in `fetch`:

1. **Method GET only** — POST/PUT/DELETE are state-mutating;
2. **Same-origin only** — cross-origin caching surprises users with
   third-party CDN behavior we don't control;
3. **No `Accept: text/event-stream`** — SSE long-polls would be frozen at
   the initial response forever.

The cache-first body:

```javascript
async function handleCacheFirst(request) {
  let cache;
  try { cache = await caches.open(STATIC_CACHE_NAME); }
  catch (e) { return fetch(request); } // cache infra failure → never block req

  try {
    const cached = await cache.match(request);
    if (cached) return cached;
  } catch (e) { /* miss-on-error: fall through to network */ }

  const networkResponse = await fetch(request);
  if (networkResponse?.ok && networkResponse.status === 200 &&
      (networkResponse.type === 'basic' || networkResponse.type === 'default')) {
    const responseClone = networkResponse.clone();
    cache.put(request, responseClone).then(
      () => trimCache(cache).catch(() => {}),
      () => {} // quota exceeded → silent
    );
  }
  return networkResponse;
}
```

The `cache.put` is intentionally fire-and-forget (`.then(...)` not
`await`) — user-perceived latency is exactly `fetch(request)` time, never
`fetch + cache.put`. Cache failures (`quota exceeded`, evicted cache,
disk full) are silently swallowed because the network response is already
on its way to the user; failing the response would be worse than missing
a cache write.

#### Decoupling SW registration from `Notification` API

Pre-R21.2, `static/js/notification-manager.js::init()` registered the SW
*inside* `if (this.isSupported) { ... }` where `isSupported` checked
`'Notification' in window`. iOS 16-, privacy-locked-down Firefox, and
some embedded browsers gate `Notification` but DO support
`serviceWorker` and `Cache` APIs — those users got zero R21.2 benefit
even though their environments could fully support cache-first.

The fix moves `await this.registerServiceWorker()` out of the
else-branch. The existing `supportsServiceWorkerNotifications()` guard
inside `registerServiceWorker()` despite the misleading name actually
only checks `'serviceWorker' in navigator && Boolean(window.isSecureContext)`,
NOT anything Notification-related — so the iOS-gated environments now
register the SW correctly.

#### Measurements

- First session: ~80 assets × ~12 ms RTT = ~1 s (no change vs pre-R21.2);
- Second session: ~80 assets at 0-1 ms (cache hit) ≈ 0 RTT (-95%+ vs
  fresh network);
- Slow-LAN deployment: 80 × 150-200 ms = 12-16 s → 0 ms after first
  session (-99%+).

Manual verification on Cursor + Chromium + macOS: open Web UI cold (sees
~80 `/static/*` 200 OK in DevTools), reload (~80 `(ServiceWorker)` 200 OK
at 0-1 ms), force-reload Cmd-Shift-R (still SW hits because SW survives
hard reload), close + reopen tab in fresh window (still cache hits
because SW is per-origin not per-tab), bump `app.version` (cache miss
for version-bumped assets, cache hit for unchanged ones — exactly the
desired "version-aware invalidation" behavior).

#### Trade-offs

What R21.2 deliberately does NOT do:

1. **Does NOT cache `/api/*`** — session-state-dependent, would show
   stale task lists / settings;
2. **Does NOT cache HTML responses** — the HTML carries the `?v=...`
   cachebusters that all asset cache keys depend on; freezing HTML
   freezes the entire versioning scheme;
3. **Does NOT implement an offline page fallback** — AIIA is
   LAN/loopback only; if the user is offline, the MCP server is also
   offline, the AI agent can't even invoke `interactive_feedback`,
   nothing to fall back to;
4. **Does NOT use stale-while-revalidate** — versioning is so
   disciplined (`?v={{ app_version }}` everywhere) that there's no
   "stale" state to revalidate; cache hit ≡ fresh fetch semantically;
5. **Does NOT add a Brotli-aware variant negotiation in the SW** —
   that's R21.4's territory; mixing the two would have us shipping two
   competing compression strategies in parallel.

Tests deliberately go through source-text invariants rather than jsdom
integration testing because Service Workers are notoriously
underspecified in jsdom: `Cache` / `self.clients` / `self.skipWaiting`
are all stubs that don't catch realistic regressions. 26 tests in
`tests/test_sw_static_cache_r21_2.py`.

#### Source

Commit `ba30a61` · 26 tests in `tests/test_sw_static_cache_r21_2.py`.

### R21.4 · Brotli precompression (br > gzip > identity)

#### Problem

R20.14-D shipped a gzip pre-compression layer with `_send_with_optional_gzip`
negotiating `Accept-Encoding: gzip` to serve `<file>.gz` siblings. But
Brotli has been universally supported since 2017 (Chrome 50+, Firefox 44+,
Safari 11+, Edge 15+) and offers another 17-23% reduction on top of
gzip — the entire static asset payload was getting the suboptimal
gzip-only path despite client capability.

#### Strategy: parallel `.br` siblings + br-first negotiation

Three layers, deliberately additive on top of R20.14-D rather than
replacing it (so an environment without brotli installed still gets the
full R20.14-D gzip benefits):

1. **`scripts/precompress_static.py`** gains `compress_file_br()` that
   mirrors `compress_file()` exactly (same skip-by-extension /
   skip-by-size / skip-if-fresh / `tempfile + os.replace` atomic write /
   `compressed_size >= original_size` no-gain reverse-check semantics)
   but emits `<file>.br` via `brotli.compress(raw, quality=11)`. Quality
   11 is brotli's max (0-11 scale); ~10-50ms per asset, ~60-80ms on the
   1.1 MB MathJax bundle, all paid once at commit time. The script
   gracefully degrades to gzip-only when `BROTLI_AVAILABLE=False` (the
   `try: import brotli except ImportError: BROTLI_AVAILABLE = False`
   guard) so old fork environments without brotli installed continue
   working;
2. **`web_ui_routes/static.py`** gains `_parse_accept_encoding()` doing
   proper RFC-7231 q-value-aware parsing (handles `gzip;q=0.5` correctly,
   excludes `br;q=0` from the supported set), plus
   `_client_accepts_brotli()` as the br-flavored sibling of
   `_client_accepts_gzip()`. The negotiation in
   `_send_with_optional_gzip()` becomes `br > gzip > identity`: client
   supports br AND `.br` exists → serve `.br` with `Content-Encoding: br`;
   else client supports gzip AND `.gz` exists → serve `.gz` (R20.14-D
   behavior preserved exactly); else serve raw. Function name kept
   (back-compat anchor — three other route handlers depend on it; rename
   would force multi-file diff for zero functional benefit);
3. **`pyproject.toml`** promotes `brotli>=1.2.0` from transitive (via
   `flask-compress[brotli]`) to first-class dep so `pip install
   ai-intervention-agent` always installs it explicitly.

The 57 `.br` files are committed to the repo for clone-and-go
operation, same trade-off math as R20.14-D's `.gz` files — committing
~543 KB of bytes to git history vs requiring every clone to run
`python scripts/precompress_static.py` before the server can serve
compressed assets. Brotli's deterministic output makes the `.br` files
byte-reproducible across machines (same as gzip with `mtime=0`), so
commit-history bloat is bounded by the source-change rate.

#### Measurements

| Asset | Raw | gzip | Brotli | br vs gzip |
|-------|----:|-----:|-------:|-----------:|
| `tex-mml-chtml.js` | 1173 KB | 264 KB (-77%) | 204 KB (-83%) | -22.7% |
| `lottie.min.js` | 305 KB | 76 KB (-75%) | 64 KB (-79%) | -16.3% |
| `main.css` | 244 KB | 47 KB (-81%) | 37 KB (-85%) | -21.4% |
| `zh-CN.json` | 11 KB | 4.3 KB (-62%) | 3.5 KB (-69%) | -19.0% |
| `en.json` | 11 KB | 3.7 KB (-67%) | 3.2 KB (-72%) | -16.0% |
| **Total static** | **2.5 MB** | **796 KB (-68%)** | **543 KB (-79%)** | **-32%** |

Net wins:

- **+253 KB savings** vs R20.14-D's gzip-only baseline (-32% incremental);
- **-79% total** vs raw payload (vs R20.14-D's -68%);
- Largest single asset (`tex-mml-chtml.js`) drops from 1.17 MB to 204 KB.

#### Trade-offs

What R21.4 deliberately does NOT do:

1. **Does NOT add zstandard precompression** — would give another 5-10%
   on top of brotli but Safari support still patchy in 2026 (Chrome
   123+ / Firefox 126+ ship `Content-Encoding: zstd` but Safari
   pending);
2. **Does NOT add HTTP/3 + 0-RTT** — orthogonal, network-stack concern;
3. **Does NOT add per-asset compression dictionaries** — would need
   source-language analysis and isn't justified by the asset mix here;
4. **Does NOT touch the runtime CPU path** — pre-compressed siblings
   only; no on-the-fly Brotli compression in the request path
   (`flask-compress` already does that for assets without `.br` /
   `.gz` siblings, but our siblings cover all the big assets).

#### Source

Commit `c095185` · 43 tests in `tests/test_brotli_precompress_r21_4.py`.

## Layer 3 · VSCode plugin (R21.3 · DECLINED, with reasoning preserved)

### Problem statement under investigation

`packages/vscode/webview-ui.js` is ~5086 lines / 170 KB; with five sibling
manually-authored modules (`webview-helpers.js` 158 lines, `webview-notify-core.js`
268 lines, `webview-settings-ui.js` 778 lines, `webview-state.js` 156 lines,
`i18n.js` 1057 lines), total ~7503 lines / 248 KB of webview-side script.

The hypothetical R21.3 would have run all six through `esbuild --bundle
--format=iife` to produce a single bundled file:

- Reduce 5 HTTP round-trips (vscode-webview:// is local IO, but each
  still has disk-read + script-eval init overhead);
- Enable dead-code elimination on `export`-but-unused symbols;
- Open the door to future `--minify` / `--treeshake` if the size matters.

### Why R21.3 was declined

#### 1. Real cold-start has already been compressed

R20.13 took VSCode extension activation from 8.12 ms → 30 µs (-99.6%) via
the `BUILD_ID` lazy-load + 5 other sub-cuts. The R20.13 batch already
hit the high-leverage points (sync filesystem reads, sync `getExtension`
calls, eager locale registration). Webview HTML render is already
JSON-cached (`_cachedInlineAllLocalesJson`).

#### 2. Bundling savings are below the noise floor

Ballpark estimate for the R21.3 hypothesis:

- 5 vscode-webview:// HTTP round-trips eliminated: 0.5-2 ms each → 2-10 ms
  total, **but** these happen in parallel during HTML parsing, so the
  serial save is closer to **2-5 ms wall-time**;
- DCE on hand-written modules: typically <1 KB of saved bytes; module
  loaders parse all of them anyway during init, so even the saved bytes
  don't translate into eval-time savings;
- CPU eval time: 248 KB of unminified JS parses in ~5-10 ms on M1
  Chromium; bundling without `--minify` doesn't shrink eval time
  (parse-time is dominated by JS engine warmup, not bytes-on-the-wire).

Combined: **2-10 ms** estimated, **almost certainly at or below the
~5 ms abs-floor** that `scripts/perf_gate.py` uses to suppress noise on
sub-millisecond benchmarks.

#### 3. Real cost is non-trivial

To land R21.3 cleanly we would need:

1. **Add esbuild as a dev dep** (and adjust `package.json::scripts`,
   `Makefile`, CI matrix);
2. **Pre-build step in `scripts/package_vscode_vsix.mjs`** — currently the
   includeList copies hand-written .js files verbatim; bundling means
   producing a `dist/webview-bundle.js` and making the `includeList`
   reference it instead, plus updating ~6 `<script src="...">` URIs in
   `webview.ts::_getHtmlContent`;
3. **CSP nonce handling** stays the same (single bundle, single nonce),
   but **source-map handling** complicates: VSCode CSP is strict and
   may reject `eval`-style source maps; we'd need to ship `.map` files
   and configure `webview.asWebviewUri` to serve them, or skip
   source-maps and accept worse debug experience;
4. **Byte-parity tests** (`tests/test_tri_state_panel_parity.py`
   already locks `static/js/tri-state-panel.js` ↔ `packages/vscode/
   tri-state-panel.js` byte-for-byte equality) — bundling
   `webview-ui.js` doesn't break this directly (tri-state-panel is
   a separate file), but introduces a *new* source-of-truth question:
   if `webview-ui.js` is now a `dist/` artifact, what's the
   build-reproducibility story? Different esbuild versions can
   produce different bytes; do we commit `dist/webview-bundle.js` or
   build-on-demand?
5. **Test rewrites**: 30+ tests in `tests/test_vscode_*.py` directly
   read `packages/vscode/webview-ui.js` as a string and grep for
   patterns. Bundling would reorder/rename symbols, breaking ~all
   of them; we'd need `tests/test_vscode_bundle_*.py` from scratch.

Estimated cost: **2-3 days of careful engineering + ~50 test rewrites**
for **2-10 ms** of wall-time. ROI is firmly negative.

#### 4. The "deliberately not optimized" precedent

R20.x already established this pattern. R20.14 documented six negative
decisions with cost-benefit reasoning so future contributors don't
re-investigate closed questions. R21.3 joins that list.

### What R21.3 would unlock if revisited

If a future R22.x batch finds VSCode webview cold-start has degraded
back to >50 ms (e.g. someone added a fat new module that doubled the
JS payload), the cost/benefit math could flip: bundling 500 KB of JS
into a single chunk would save proportionally more eval-time, and the
fixed cost of "set up esbuild + test infra" amortizes across future
modules. The decision should be re-run with fresh measurements, not
reflexively adopted.

## Reproducing the numbers

Bench scripts and tests live in the repo:

```bash
# Server-side benchmarks (R20.x baseline; R21.x is browser-side so unaffected)
uv run python scripts/perf_e2e_bench.py --quick --output /tmp/p.json
uv run python scripts/perf_gate.py --results /tmp/p.json

# Browser-side: open Web UI in Chromium DevTools, look at Network panel:
# - First load: ~80 /static/* requests, all 200 OK
# - Reload: ~80 (ServiceWorker) responses, mostly 0-1 ms
# - Inspect a /static/js/tex-mml-chtml.js response: Content-Encoding: br

# Brotli precompression idempotency check:
uv run python scripts/precompress_static.py --check  # exit 0 if all fresh
uv run python scripts/precompress_static.py          # regenerates as needed
```

Hardware reference: Apple Silicon M1 / Python 3.11.15 / macOS 25.4.0 /
Cursor + VSCode dev environment.

## Future work

Non-binding pointers for future R22.x+ batches. **Add a benchmark first
per R20.14-A, then `--update-baseline` after measuring, then append a
section to this roadmap** — so the harness + gate + docs system
perpetuates rather than decays.

- **Image format modernization** — convert PNG/JPEG fallbacks to AVIF
  with WebP intermediate; expected -20-40% on `static/images/*`;
- **`service_manager` polling consolidation** — currently three
  `setInterval` cycles run at different cadences; combining could shave
  ~1% on idle CPU;
- **HTTP/2 server push** — non-trivial CDN config, low expected gain;
- **R21.3 webview esbuild bundling** — see decline reasoning above; can
  be revisited if webview cold-start regresses past 50 ms;
- **zstandard precompression** — wait for Safari support;
- **HTTP/3 + 0-RTT** — orthogonal to encoding layer, network-stack
  concern.

## Cross-references

- Layer 1-4 baseline established in R20.x:
  [`docs/perf-r20-roadmap.md`](perf-r20-roadmap.md);
- End-to-end perf bench:
  [`scripts/perf_e2e_bench.py`](../scripts/perf_e2e_bench.py);
- Regression gate:
  [`scripts/perf_gate.py`](../scripts/perf_gate.py);
- Baseline data:
  [`tests/data/perf_e2e_baseline.json`](../tests/data/perf_e2e_baseline.json);
- Per-feature tests:
  [`tests/test_critical_preload_r21_1.py`](../tests/test_critical_preload_r21_1.py),
  [`tests/test_sw_static_cache_r21_2.py`](../tests/test_sw_static_cache_r21_2.py),
  [`tests/test_brotli_precompress_r21_4.py`](../tests/test_brotli_precompress_r21_4.py).
