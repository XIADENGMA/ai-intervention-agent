/* AI Intervention Agent · Service Worker
 *
 * 一个文件承担两件事：
 *
 * 1. **通知点击路由**（既有功能，``notificationclick`` 事件）—— 接住系统
 *    通知中心的点击，把焦点切到已存在的 Web UI 标签页或新开一个窗口。
 *
 * 2. **静态资源缓存（R21.2）** —— 对 ``/static/css/*`` / ``/static/js/*`` /
 *    ``/static/lottie/*`` / ``/static/locales/*`` / ``/icons/*`` /
 *    ``/sounds/*`` / ``/fonts/*`` 等"内容寻址"（``?v=hash`` 版本化）的静态
 *    资源走 **cache-first**：第一次走网络存进 cache，后续重复访问全部命中
 *    本地 IndexedDB-backed cache，零 RTT。``/api/*`` 与 HTML 路径绕过缓存。
 *
 * 设计要点
 * --------
 * - **Cache 名带版本号**（``aiia-static-v1``）：当 SW 升级（比如重构 fetch
 *   逻辑），把版本号 bump 到 ``-v2``，``activate`` 阶段会清理所有旧版本
 *   ``aiia-static-*`` cache，避免 "升级后旧 cache 卡死"。
 * - **白名单 cache-first**：只缓存"内容稳定 + 带版本号"的资源；任何
 *   ``/api/*``、``/sse``、HTML 路径（``/`` / 任何 200 但 ``Content-Type:
 *   text/html``）都不缓存，避免会话状态被冻结。
 * - **同源限制**：只缓存 ``self.location.origin`` 下的资源，跨域引用一律
 *   走默认网络路径（避免 CDN / 第三方资源被错误冻结）。
 * - **Cache size 限流**（``MAX_ENTRIES``）：超过上限时**异步**淘汰最早写入
 *   的 entry，不阻塞响应。LRU 严格性需要额外簿记，这里用 FIFO 近似（cache
 *   key 顺序就是 ``cache.keys()`` 返回顺序），代价是偶尔淘汰错对象，但
 *   静态资源版本化下 cache 命中已经是常态，FIFO 误差可接受。
 * - **失败兜底**：``cache.put`` 抛错（比如 quota exceeded、cache 已被清理）
 *   不能让响应失败——所有 cache 写入都被 ``.catch(() => {})`` 包裹。
 * - **Method 限制**：只缓存 GET 请求；POST/PUT/DELETE 一律 fall-through。
 * - **响应可消费一次**：``response.clone()`` 之前必须确保 stream 还没被读，
 *   ``cache.put(request, response.clone())`` 同步立刻 clone 取一份给 cache，
 *   原 response 给 fetch 的调用者消费。
 *
 * 不在本 SW 中处理的事
 * --------------------
 * - **Push notification**（推送通知）—— 仍由 `notification-manager.js` 走
 *   非 SW 路径或后端 Bark/Telegram 推送。
 * - **离线页面**（offline page fallback）—— 当前不需要 PWA 离线场景，AI
 *   Intervention Agent 是 LAN/loopback only。
 * - **动态 API 缓存**（stale-while-revalidate /api/）—— ``/api/tasks`` 等
 *   端点状态高度动态，缓存反而错误地展示陈旧任务列表。永远 fall-through。
 */

const STATIC_CACHE_NAME = 'aiia-static-v1'
// 200 entry 的硬上限：典型 Web UI 加载 ~80 静态资源（含 prism-components/
// 多语言子包），200 留 2.5× headroom 应对未来无意识资源增长 + locale 切换
// 累积。超过即异步 FIFO 淘汰。
const MAX_ENTRIES = 200

// cache-first 策略适用的路径。``new RegExp`` 在 SW activate 阶段构造一次，
// 后续 fetch 事件直接复用，零 per-request 编译开销。
const CACHE_FIRST_PATTERNS = [
  /^\/static\/css\//,
  /^\/static\/js\//,
  /^\/static\/lottie\//,
  /^\/static\/locales\//,
  /^\/static\/images\//,
  /^\/icons\//,
  /^\/sounds\//,
  /^\/fonts\//,
  /^\/manifest\.webmanifest$/
]

self.addEventListener('install', event => {
  // skipWaiting 让新 SW 立刻接管而不是等待所有旧 client 关闭。
  // 配合 activate 阶段的 cache 清理，确保升级链路最短。
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      // R21.2：清理旧版本 ``aiia-static-*`` cache，让 SW 升级后能回收存储。
      try {
        const cacheNames = await caches.keys()
        await Promise.all(
          cacheNames
            .filter(
              name =>
                typeof name === 'string' &&
                name.startsWith('aiia-static-') &&
                name !== STATIC_CACHE_NAME
            )
            .map(name => caches.delete(name).catch(() => false))
        )
      } catch (e) {
        // 忽略：cache.keys() 失败不影响 SW 接管
      }

      try {
        await self.clients.claim()
      } catch (e) {
        // 忽略：claim 失败不影响 SW 后续 fetch handler 工作
      }
    })()
  )
})

/* R21.2：fetch event handler — cache-first for whitelisted static paths */
self.addEventListener('fetch', event => {
  const request = event.request

  // 只缓存 GET：POST/PUT/DELETE 都是状态变更，缓存绝对错误。
  if (request.method !== 'GET') return

  // 只缓存同源：跨域资源不在我们控制下，避免误冻结第三方 CDN / API。
  let url
  try {
    url = new URL(request.url)
  } catch (e) {
    return
  }
  if (url.origin !== self.location.origin) return

  // 只缓存白名单路径
  if (!CACHE_FIRST_PATTERNS.some(re => re.test(url.pathname))) return

  // SSE 端点（如 /api/sse-events）虽然是 GET，但是 EventSource 长连接，
  // 绝不能 cache。CACHE_FIRST_PATTERNS 已经排除了 /api/，但保险起见
  // 再检查一遍 ``Accept: text/event-stream``。
  const acceptHeader = request.headers.get('Accept') || ''
  if (acceptHeader.includes('text/event-stream')) return

  event.respondWith(handleCacheFirst(request))
})

/* cache-first 策略：先查 cache，命中直接返回；未命中走网络并异步写 cache。 */
async function handleCacheFirst(request) {
  let cache
  try {
    cache = await caches.open(STATIC_CACHE_NAME)
  } catch (e) {
    // 完全失败时让浏览器走默认网络路径
    return fetch(request)
  }

  try {
    const cached = await cache.match(request)
    if (cached) return cached
  } catch (e) {
    // cache.match 失败不致命，继续走网络
  }

  // 未命中：网络拉取 + 异步写 cache
  const networkResponse = await fetch(request)

  // 只缓存 200 OK 响应。redirect / 4xx / 5xx 都不该写 cache。
  // ``response.type === 'basic'`` 是同源响应；我们已经在 fetch handler 里
  // 验证过同源，但 ``Response.type`` 在 SW spec 里仍可能是 'opaqueredirect'
  // 等异常值，多查一次更稳。
  if (
    networkResponse &&
    networkResponse.ok &&
    networkResponse.status === 200 &&
    (networkResponse.type === 'basic' || networkResponse.type === 'default')
  ) {
    // 异步写 cache：``response.clone()`` 同步执行（cheap），``cache.put``
    // 走异步 promise，不阻塞响应返回给页面。
    const responseClone = networkResponse.clone()
    cache.put(request, responseClone).then(
      () => {
        trimCache(cache).catch(() => {})
      },
      () => {
        // 忽略：write 失败（quota exceeded、cache 被清等）不该影响响应
      }
    )
  }

  return networkResponse
}

/* FIFO 淘汰：cache 超过 MAX_ENTRIES 时，删掉最早写入的 entry。 */
async function trimCache(cache) {
  let keys
  try {
    keys = await cache.keys()
  } catch (e) {
    return
  }
  if (!Array.isArray(keys) || keys.length <= MAX_ENTRIES) return

  // ``cache.keys()`` 按写入顺序返回（spec: "the order they were added"），
  // 所以 ``keys[0]`` 是最早写的，``keys[keys.length - 1]`` 是最晚写的。
  // 削减到 MAX_ENTRIES 大小：保留最后 MAX_ENTRIES 条，删除前面所有。
  const toDelete = keys.slice(0, keys.length - MAX_ENTRIES)
  await Promise.all(toDelete.map(req => cache.delete(req).catch(() => false)))
}

/* 既有功能：通知点击路由，原样保留 */
self.addEventListener('notificationclick', event => {
  event.notification.close()

  const data = event.notification.data || {}
  const targetUrl = typeof data.url === 'string' && data.url ? data.url : '/'

  event.waitUntil(
    (async () => {
      const absoluteTargetUrl = new URL(targetUrl, self.location.origin).toString()
      const targetPathname = new URL(absoluteTargetUrl).pathname
      const windowClients = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true
      })

      for (const client of windowClients) {
        try {
          const clientUrl = new URL(client.url, self.location.origin)
          if (
            client.url === absoluteTargetUrl ||
            clientUrl.pathname === targetPathname
          ) {
            if ('focus' in client) {
              await client.focus()
            }
            return
          }
        } catch (error) {
          // 忽略无法解析的 client URL，继续尝试其他窗口
        }
      }

      if (self.clients.openWindow) {
        await self.clients.openWindow(absoluteTargetUrl)
      }
    })()
  )
})
