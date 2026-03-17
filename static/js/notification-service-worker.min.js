self.addEventListener('install', event => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim())
})

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
