# R20.x Performance Roadmap

> 中文版：[`perf-r20-roadmap.zh-CN.md`](perf-r20-roadmap.zh-CN.md)

This document captures the design rationale, measurements, and trade-offs of
the **R20.x performance optimization batch** (R20.4 → R20.14), which took the
end-to-end "AI agent calls `interactive_feedback` → user sees the Web UI"
wall-clock latency from **~1980 ms** down to **~360 ms** (-82%) across four
optimization layers.

## Why this document exists

R20.x landed across 11 commits with detailed messages explaining what each
change did. But the full *narrative* — how the layers compose, why we picked
specific thresholds, what we deliberately *didn't* optimize — was scattered.
This roadmap is the single place to read for:

- **Reviewers** auditing whether a future change accidentally undoes a R20.x
  win;
- **Future optimizers** trying to find the next 30% (or recognize that
  remaining gains are diminishing-returns and not worth touching);
- **Operators** debugging "why did latency regress on my fork?" by comparing
  measurements against `tests/data/perf_e2e_baseline.json`.

## The four-layer roadmap

The user's directive was:

> 深挖性能优化，先从本体 MCP 开始，再到网页, 再到插件, 再到整体, 都要进行性能优化。

Translated: optimize the **MCP core** first, then the **web page**, then the
**VSCode plugin**, then the **overall system**. Each layer has its own
bottleneck profile and tooling, so we tackled them in series:

| Layer | Round | Focus | Wall-clock impact |
|-------|-------|-------|-------------------|
| Core MCP | R20.4–R20.10 | Cold-start `import` time, lazy module loading | 425 ms → 156 ms (-63%) |
| Core MCP | R20.11 | mDNS async publish (Web UI subprocess spawn-to-listen) | 1922 ms → 203 ms (-89%) |
| Web page | R20.12 | Browser runtime cold-start (FCP, locale, image decode) | ~150 ms saved on first paint |
| Plugin | R20.13 | VSCode extension activation + webview render | 8.12 ms → 30 µs activation (-99.6%) |
| Overall | R20.14 | Cross-layer harness, regression gate, asset compression, docs | (see R20.14 sections below) |

## Layer 1 · Core MCP cold start (R20.4 – R20.10)

### Problem

The MCP server's `import web_ui` was the first major cold-path: it dragged in
Flask, Pydantic, Zeroconf, and every notification provider through transitive
imports. Measured wall time before R20.4: **425 ms median** for a fresh `python
-c "import web_ui"`.

### Strategy: lazy `find_spec` + first-touch hoist

Rather than chase individual heavy imports, R20.4 introduced a pattern that
became the template for R20.5–R20.10:

1. At module load time, do **only** `importlib.util.find_spec(name)` to verify
   the optional dependency exists. This costs ~100 µs per check vs. 5–50 ms
   per real import.
2. Bind a `_HAS_FOO = bool(spec)` flag for downstream feature gates.
3. The first request handler that *actually needs* `foo` does a local
   `import foo` — paid once per process, **after** the user has triggered the
   feature.

This pushes ~270 ms of import work from cold-start onto a (mostly invisible)
first-request path. Notification providers (Bark, Telegram, Discord, plyer)
were the biggest offenders — most users never trigger any of them in a
session, so the cost is permanently amortized.

### Measurements

| Round | Median import time | Saving | Cumulative |
|-------|-------------------:|-------:|-----------:|
| Pre-R20.4 | 425 ms | — | — |
| R20.10    | 156 ms | -269 ms | -63% |

`scripts/perf_e2e_bench.py::bench_import_web_ui` is the lockstep benchmark.

### Trade-offs

- **First request slows down ~50 ms** for the lazy-loaded path. We checked
  this is invisible against typical AI-tool latency (network round-trip
  ~200–500 ms). Acceptable.
- **`find_spec` calls add up if you forget them** — a missing `_HAS_FOO`
  guard re-imports `foo` at hot-path entry. The 19 mock-friendly tests in
  `tests/test_lazy_*` lock the discipline.

## Layer 1.5 · Subprocess spawn-to-listen (R20.11)

### Problem

Even with R20.10's import cost slashed, the Web UI subprocess took **1922 ms**
median to go from `subprocess.Popen([python, web_ui.py, ...])` to socket
listen. Investigation: 1.7 s of that was inside `zeroconf.register_service`,
which per RFC 6762 §8 sends 3× 250 ms multicast probe queries before
announcing.

### Strategy: async daemon-thread publish

`WebFeedbackUI.run()` no longer waits on `_start_mdns_if_needed`. Instead it
spawns a daemon thread (`name="ai-agent-mdns-register"`) that does the mDNS
work in the background. `app.run()` enters listen state immediately.

Critical correctness work:

- `_stop_mdns` joins the thread with a 2-second timeout (slightly larger than
  the typical 1.7 s register completion, so 95% of clean shutdowns wait for
  unregister + announcement to land);
- `daemon=True` is load-bearing — without it, a stuck mDNS probe would hang
  Web UI subprocess shutdown indefinitely;
- Direct unit-test calls to `_start_mdns_if_needed` keep their synchronous
  semantics (we threading-wrap only the call site in `run()`, not the function
  itself).

### Measurements

| Round | spawn → socket listen | Saving |
|-------|----------------------:|-------:|
| Pre-R20.11 | 1922 ms | — |
| R20.11     |  203 ms | **-1718 ms / -89.4%** |

This was the **single biggest user-perceived win** in the entire R20.x batch.
Combined with R20.10's import cost: the full Web UI subprocess cold start
went from ~1980 ms → ~360 ms (-82%). The "AI calls tool → user sees UI"
latency is now dominated by the AI client's network RTT, not by us.

### Trade-offs

- The "mDNS 已发布" stdout line now appears **after** "Running on http://..."
  rather than before. Cosmetic; nobody parses it programmatically.
- On extremely fast SIGTERM (Ctrl-C within 100 ms of subprocess spawn), the
  mDNS daemon thread might be killed mid-register without announcing. But
  since nothing on the LAN ever saw the half-broadcast, there's nothing to
  clean up; Zeroconf's TTL-based cleanup handles eventual consistency.

## Layer 2 · Browser runtime (R20.12)

### Three orthogonal browser-side cuts

R20.12 audited every byte the browser receives during cold paint:

**R20.12-A · `mathjax-loader.js` `defer`**

`<script>/static/js/mathjax-loader.js</script>` was head-blocking. The script
itself only declares `window.MathJax` config + helper functions — the actual
1.17 MB `tex-mml-chtml.js` is appended at runtime when the user pastes math
content. Adding `defer` lets HTML parsing continue without waiting. **Saves
5–10 ms head-of-paint blocking.**

**R20.12-B · inline locale JSON when language is known**

When `web_ui.config.language ∈ {'en', 'zh-CN'}` (anything except `'auto'`),
`_get_template_context` reads the corresponding `static/locales/<lang>.json`
via `@lru_cache(maxsize=8)` and ships it inline as `window._AIIA_INLINE_LOCALE`.
The `i18n.init()` JS picks it up before doing any network fetch.

**Saves 30–80 ms RTT on every cold page load** (or 11 KB of locale fetch
that even an HTTP cache hit pays). XSS protection: `<` is escaped to `\u003c`
in the inline JSON serialization.

**R20.12-C · `createImageBitmap` for image upload**

`compressImage` migrated from `new Image() + URL.createObjectURL(file) +
img.onload` to the modern `createImageBitmap(file)` async path. The legacy
path is kept as `_loadImageViaObjectURL` fallback for Safari < 14 / older
Firefox. **Saves 50–200 ms per image** on modern Chromium / Firefox 105+ /
Safari 14+.

### Measurements

`tests/test_browser_perf_r20_12.py` (27 invariant tests) locks the source
behavior. End-to-end FCP isn't a stable CI metric (depends on browser, GPU,
DPI), so we don't have a single number — but each cut is well-contained and
individually measurable.

### Trade-offs

- **`mathjax-loader.js`** is now `defer` instead of synchronous. Since the
  actual MathJax bundle is dynamically appended at runtime, this changes
  nothing observable.
- **Inline locale JSON** adds ~11 KB to the HTML response. For language=auto
  (the default for fresh installs), no inline injection happens, so cost is
  zero. For explicit languages, +11 KB inline beats +11 KB locale fetch
  every time on first paint.
- **`createImageBitmap` fallback** keeps the old path alive — no regression
  for users on legacy Safari / FF.

## Layer 3 · VSCode extension (R20.13)

### Six orthogonal cuts

R20.13 went deeper into the VSCode extension activation + webview HTML
generation:

**R20.13-A · lazy `BUILD_ID`** — Replaced the `child_process.execSync('git
rev-parse --short HEAD')` IIFE at module load with a lazy `getBuildId()`
gated by `fs.existsSync('.git')`. **Saves 8.12 ms → 30 µs (-99.6%) per
production VSIX activation** (the dev-tree path still pays full ~8 ms for
real SHA — that's intentional).

**R20.13-B/F · constructor-injected `extensionVersion`** — `WebviewProvider`
now takes `extensionVersion` as a constructor arg (passed once from
`activate`), eliminating per-render `vscode.extensions.getExtension()` calls.
**Saves ~1–3 ms per HTML render.**

**R20.13-C · async parallel locale read** — Host-side i18n locale loading
went from serial `fs.readFileSync` to parallel `Promise.all` with
`fs.promises.readFile`. Halves the I/O wait time. (Microsecond-range absolute,
but unblocks future async-friendly init.)

**R20.13-D · lazy locale registration** — `webview-ui.js::ensureI18nReady`
used to eager-register *all* locales (`Object.keys(__AIIA_I18N_ALL_LOCALES)`).
Now eager-registers only the active language + `'en'` fallback (the
`i18n.js::_resolvePath` line 558–559 contract requires `'en'` always
registered for missing-key fallback). A new `ensureLocaleRegistered(lang)`
helper lazy-registers any other locale on-demand when `applyServerLanguage`
detects a runtime language switch. **Saves 50–100 µs at startup.**

**R20.13-E · cached inline `allLocales` JSON** — `_getHtmlContent` caches
`safeJsonForInlineScript(allLocales)` in two new fields, with cache key
`"<sorted-names>:<entry-counts>"` so any locale-set change auto-invalidates.
**Saves 50–100 µs per render.**

### Measurements

| Cut | Savings |
|-----|--------:|
| A · lazy BUILD_ID | -8.09 ms / activation (-99.6%) |
| B/F · ctor extensionVersion | -1–3 ms / render |
| C · async parallel locale | ~halved (sub-ms) |
| D · lazy registerLocale | -50–100 µs / startup |
| E · cached allLocales JSON | -50–100 µs / render |

A is the headline number. C/D/E are noise-floor optimizations; we kept them
because the user explicitly insisted ("领导表态类坚持") and they're
zero-risk pure refactors.

`tests/test_vscode_perf_r20_13.py` (25 tests) locks all six cuts.

### Trade-offs

- **Lazy BUILD_ID** means production VSIX shows `'dev'` if the build pipeline
  forgets to substitute `__BUILD_SHA__`. The build script
  (`scripts/package_vscode_vsix.mjs`) does the substitution; if it ever stops
  doing so, the symptom is benign cosmetic ("'dev' instead of '0a1b2c3'").

## Layer 4 · Overall system (R20.14)

R20.14 has four sub-rounds: A (harness), C (cross-process), D (asset
compression), E (this document).

### R20.14-A · End-to-end perf harness + regression gate

`scripts/perf_e2e_bench.py` measures 5 wall-clock benchmarks via subprocess
isolation:

| Benchmark | What it measures | R20.x baseline (median) |
|-----------|------------------|------------------------:|
| `import_web_ui` | `python -c "import web_ui"` cold time | 156 ms |
| `spawn_to_listen` | `subprocess.Popen([python, web_ui.py])` → socket listen | 203 ms |
| `html_render` | `_get_template_context()` + `render_template()` | 0.07 ms |
| `api_health_round_trip` | localhost `/api/health` GET | ~3 ms |
| `api_config_round_trip` | localhost `/api/config` GET | ~3 ms |

`scripts/perf_gate.py` compares a current `perf_e2e_bench.py --output
current.json` against `tests/data/perf_e2e_baseline.json`. Per-benchmark
regression tolerance is `max(baseline × pct_threshold, abs_floor_ms)` —
default 30% pct + 5 ms abs floor. Sub-ms benchmarks (`html_render`) are
governed by abs floor (5 ms = ~70× the baseline, deliberately wide so
measurement noise on shared CI doesn't false-positive).

To update the baseline after a deliberate change:

```bash
uv run python scripts/perf_e2e_bench.py --output /tmp/perf.json --quiet
uv run python scripts/perf_gate.py --results /tmp/perf.json \
    --update-baseline --baseline tests/data/perf_e2e_baseline.json
```

The baseline JSON's optional top-level `thresholds: {bench_name: pct}` lets
ops manually tighten a single benchmark below the global default. Useful for
benchmarks that are inherently more deterministic.

### R20.14-C · Cross-process hot-path optimizations

The "MCP `task_status_change` → plugin status bar updates" round-trip:

```
TaskQueue._trigger_status_change
  → _on_task_status_change         # callback registered by web_ui_routes/task.py
    → _SSEBus.emit                 # publishes to all SSE subscribers
      → SSE generator              # yields formatted event line per subscriber
        → plugin _connectSSE       # parses ev.new_status
          → 80 ms debounce         # coalesces bursts
            → fetch /api/tasks     # 3 ms RTT, source of truth
              → status bar update
```

**Optimizations landed:**

1. **`_SSEBus.emit` lock tightening** — Only `list(self._subscribers)`
   snapshot under `_lock`; `put_nowait` runs lock-free. Reduces emit
   critical-section length from O(N subscribers) to O(1). Re-acquires lock
   briefly for `set.discard` of dead queues.
2. **Pre-serialize SSE payload once per emit** — `json.dumps(data)` happens
   in `emit()` and is stored as `payload['_serialized']`. Generators consume
   it directly. Saves (N−1) `json.dumps` per event when there are N
   subscribers.
3. **Embed task stats in `task_changed` payload** — `_on_task_status_change`
   calls `get_task_count()` after the queue lock is released and embeds
   `stats: {pending, active, completed}` in the SSE event. The plugin can
   then render the status bar **optimistically** before the
   `fetch /api/tasks` round-trip completes, while the fetch still runs as
   the canonical source of truth (used for new-task-detection).
4. **Plugin optimistic status bar** — `extension.ts` SSE handler now reads
   `ev.stats` and immediately calls `applyStatusBarPresentation` if present.
   The 80 ms debounce + `fetch /api/tasks` still happen — they just no longer
   gate the visible UI update.

**Trade-offs:**

- **Lock-tightening** changes the contract slightly: subscribers added
  *during* an `emit()` call (after the snapshot) miss this event. Same
  semantics as before — `subscribe()` queues up after the lock release —
  but worth knowing.
- **Stats embed** does a `get_task_count()` call (O(n) over current tasks)
  on each `task_changed` event. n is typically < 100 in practice; if a future
  workload pushes that high, we may want to switch to maintained counters.
- **Optimistic UI update** can briefly show stale data if the SSE event was
  emitted from a stale snapshot (race between `_trigger_status_change` and
  another mutation). The fetch corrects within ~85 ms. Acceptable trade.

`tests/test_cross_process_perf_r20_14c.py` (22 tests) covers the contract.

### R20.14-D · Static asset gzip pre-compression

**Problem:** `static/js/tex-mml-chtml.js` is 1.17 MB; `static/js/lottie.min.js`
is 300 KB. Flask-Compress (`flask_compress.Compress(self.app)`) was already
wired up, but it gzips on-the-fly **on every request** at level 6. That's
~3–5 ms of runtime CPU per uncached big-file response.

**Solution:** `scripts/precompress_static.py` walks `static/css`, `static/js`,
`static/locales` and produces `<file>.gz` siblings (gzip level 9, `mtime=0`
for reproducibility). At serve time, `_send_with_optional_gzip` checks
`Accept-Encoding: gzip` and the existence of `<file>.gz`; if both pass, the
response is the precompressed bytes with `Content-Encoding: gzip` and the
original `Content-Type`. `Vary: Accept-Encoding` is always set so CDNs /
intermediate caches partition correctly.

**Measurements:** 2624 KB of source → 661 KB gzipped (-75%). 1916 KB freed
across 63 files. The biggest single win: `tex-mml-chtml.js` 1173 KB → 264 KB
(-77%).

**Compression threshold:** 500 bytes (matches `flask-compress`'s
`COMPRESS_MIN_SIZE` default). Smaller files don't benefit from gzip's 18-byte
header overhead. We deliberately avoid Brotli — it's another 15–20% smaller
than gzip, but adds a `pip install brotli` runtime dependency. Future
R20.x round may revisit if metrics justify it.

**Workflow:**

```bash
# Generate fresh .gz siblings (idempotent: re-running produces byte-identical
# output thanks to mtime=0)
uv run python scripts/precompress_static.py

# CI gate: exit 1 if any .gz is stale
uv run python scripts/precompress_static.py --check

# Cleanup (e.g., before a fresh experiment)
uv run python scripts/precompress_static.py --clean
```

`tests/test_static_compression_r20_14d.py` (35 tests) covers the script,
the negotiator (`_client_accepts_gzip`), the helper
(`_send_with_optional_gzip`), and end-to-end integration through the real
`WebFeedbackUI` test client.

**Trade-offs:**

- `.gz` files are committed to the repo (~640 KB of additional git size).
  We considered `.gitignore`-ing them, but commit-and-go beats
  "new-clone-must-build" for a small project. `mtime=0` keeps PR diffs
  minimal — only files whose source actually changed get touched.
- `flask-compress` and our pre-compression coexist via the
  `Content-Encoding`-set check inside flask-compress's `after_request` hook.
  We tested this explicitly (`test_serve_js_no_accept_encoding_returns_uncompressed`).

### R20.14-E · This document

You're reading it.

## What we deliberately did *not* optimize

Picking what to skip is as important as picking what to optimize. The
following candidates were investigated but rejected:

- **service_manager health check polling** — Investigated post-R20.11 since
  the Web UI subprocess listen state arrives in 203 ms but the polling
  interval is 200 ms. Net effect: <10 ms delay in worst case (the next
  poll lands within 200 ms, but the subprocess was usually already listening
  by then). Not worth the code churn.
- **multi_task.js `setInterval` consolidation** — Multiple per-task
  countdown timers running in parallel. Consolidating into one master
  `requestAnimationFrame` loop would save ~50 µs per task. Risk of
  subtle timer-ordering regressions outweighs the savings.
- **Aggressive image format conversion** — Auto-convert paste-uploaded
  PNG to WebP. Modern browsers handle both fine; the user's clipboard PNG
  is what they expect to upload.
- **Brotli pre-compression** — 15–20% smaller than gzip but requires the
  `brotli` Python package as a runtime dep. Defer until a measured user-
  facing transfer-size complaint shows up.
- **VSIX bundle size reduction** — `mathjax/` is 2.0 MB inside the VSIX.
  Removing it would break the offline math rendering on webview. CDN
  fallback isn't an option (VSCode webview CSP restricts external loads).
- **HTTP/2 server push** — Flask's stdlib HTTP server doesn't speak HTTP/2.
  Requires switching to `gunicorn`/`uvicorn` + frontend, which is a big
  architectural shift for marginal first-paint gains.

## Reproducing the numbers

```bash
# Clone, install, run benchmark
git clone https://github.com/xiadengma/ai-intervention-agent
cd ai-intervention-agent
uv sync --all-extras
uv run python scripts/precompress_static.py    # generate .gz siblings
uv run python scripts/perf_e2e_bench.py --format table

# Compare against baseline
uv run python scripts/perf_e2e_bench.py --output /tmp/perf.json --quiet
uv run python scripts/perf_gate.py --results /tmp/perf.json
```

If your machine is significantly faster or slower than my Apple M1, the
*shape* of the numbers should still hold (e.g., `import_web_ui ≈ 1.5×
spawn_to_listen ≈ 50× api_round_trip ≈ 2000× html_render`). If the ratios
shift dramatically, run with `--verbose` and the per-bench `samples_ms`
arrays to find the outlier. Open an issue with the JSON output attached.

## Future work

The R20.x batch closed out the user's stated four-layer roadmap. Plausible
R21+ directions:

- **Brotli pre-compression** — once we have telemetry showing transfer size
  is the bottleneck for a user (e.g., remote tunnel users on slow links).
- **HTTP/2 + server push** — would require swapping Flask's stdlib server.
  Best paired with a separate "production deployment guide" RFC.
- **Service worker for offline asset caching** — the notification service
  worker exists but only handles notifications. Extending it to cache
  static JS/CSS would make repeat visits instant.
- **Webview asset bundling** — `webview-ui.js` is 168 KB unminified.
  esbuild → 50 KB minified would let the webview render in under 16 ms
  even on cold cache. Trade-off: build complexity.

If you tackle any of these, please:

1. Add a benchmark to `scripts/perf_e2e_bench.py` first (R20.14-A pattern);
2. Update the baseline (`--update-baseline`) after measuring;
3. Append a section to this roadmap documenting the design + trade-offs.

— xiadengma & contributors
