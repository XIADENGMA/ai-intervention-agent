;(function () {
  // 通知配置核心：负责从服务端拉取/规范化/缓存，并提供新任务通知派发（按需懒加载）
  let vscode = null
  try {
    vscode =
      typeof globalThis !== 'undefined' && globalThis && globalThis.__AIIA_VSCODE_API
        ? globalThis.__AIIA_VSCODE_API
        : null
  } catch (e) {
    vscode = null
  }
  if (!vscode) {
    try {

      vscode = acquireVsCodeApi()
    } catch (e) {
      vscode = null
    }
  }

  // Local i18n helper — mirrors webview-ui.js::t(): looks up AIIA_I18N and
  // falls back to the bare key so a missing locale never breaks the path.
  function __ncT(key, params) {
    try {
      var i18n =
        (typeof globalThis !== 'undefined' && globalThis.AIIA_I18N) ||
        (typeof window !== 'undefined' && window.AIIA_I18N)
      if (i18n && typeof i18n.t === 'function') return i18n.t(key, params)
    } catch (_e) {
      /* noop */
    }
    return key
  }

  const cfgEl = typeof document !== 'undefined' ? document.getElementById('aiia-config') : null
  const SERVER_URL =
    cfgEl && cfgEl.getAttribute('data-server-url') ? String(cfgEl.getAttribute('data-server-url')) : ''

  const SETTINGS_FETCH_TIMEOUT_MS = 2500

  function postMessage(message) {
    try {
      if (vscode && typeof vscode.postMessage === 'function') {
        vscode.postMessage(message)
      }
    } catch (e) {
      // 忽略：通知模块异常不应影响主 UI
    }
  }

  function logDebug(message) {
    postMessage({ type: 'log', level: 'debug', message: String(message || '') })
  }

  function postNotificationEvent(event) {
    postMessage({ type: 'notify', event: event || {} })
  }

  let notificationSettings = null
  let lastNotificationSettingsHash = ''

  function computeNotificationSettingsHash(settings) {
    try {
      return JSON.stringify(settings || {})
    } catch (e) {
      return String(Date.now())
    }
  }

  function normalizeNotificationConfig(cfg) {
    const c = cfg || {}
    return {
      enabled: c.enabled !== false,
      webEnabled: c.web_enabled !== false,
      autoRequestPermission: c.auto_request_permission !== false,
      // 后端默认 true（config.toml.default）；这里对齐“未显式关闭即开启”
      macosNativeEnabled: c.macos_native_enabled !== false,
      soundEnabled: c.sound_enabled !== false,
      soundMute: !!c.sound_mute,
      soundVolume: typeof c.sound_volume === 'number' ? c.sound_volume : 80,
      mobileOptimized: c.mobile_optimized !== false,
      mobileVibrate: c.mobile_vibrate !== false,
      barkEnabled: !!c.bark_enabled,
      barkUrl: c.bark_url || 'https://api.day.app/push',
      barkDeviceKey: c.bark_device_key || '',
      barkIcon: c.bark_icon || '',
      barkAction: c.bark_action || 'none',
      barkUrlTemplate: c.bark_url_template || '{base_url}/?task_id={task_id}'
    }
  }

  function getCachedNotificationSettings() {
    return notificationSettings
  }

  function setCachedNotificationSettings(settings) {
    try {
      notificationSettings = settings || null
      lastNotificationSettingsHash = computeNotificationSettingsHash(notificationSettings)
    } catch (e) {
      notificationSettings = settings || null
      lastNotificationSettingsHash = String(Date.now())
    }
  }

  async function refreshNotificationSettingsFromServer({ force = false, silent = false } = {}) {
    if (!SERVER_URL) {
      return { ok: false, message: __ncT('notify.hint.serverUrlMissing') }
    }

    let controller = null
    let timeoutId = null
    try {
      const fetchOptions = {
        method: 'GET',
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      }
      if (typeof AbortController !== 'undefined') {
        controller = new AbortController()
        fetchOptions.signal = controller.signal
        timeoutId = setTimeout(() => {
          try {
            controller.abort()
          } catch (e) {
            /* 忽略 */
          }
        }, SETTINGS_FETCH_TIMEOUT_MS)
      }

      const resp = await fetch(SERVER_URL + '/api/get-notification-config', fetchOptions)
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || !data || data.status !== 'success') {
        const msg =
          data && data.message
            ? data.message
            : __ncT('notify.hint.loadFailedHttp', { status: resp.status })
        if (!silent) {
          logDebug('[notify-core] ' + msg)
        }
        return { ok: false, message: msg }
      }

      const next = normalizeNotificationConfig(data.config || {})
      const nextHash = computeNotificationSettingsHash(next)
      const changed = !lastNotificationSettingsHash || nextHash !== lastNotificationSettingsHash

      if (force || changed || !notificationSettings) {
        notificationSettings = next
        lastNotificationSettingsHash = nextHash
      }

      return {
        ok: true,
        settings: notificationSettings,
        hash: lastNotificationSettingsHash,
        changed
      }
    } catch (e) {
      const msg =
        e && e.name === 'AbortError'
          ? __ncT('notify.hint.requestTimeout')
          : e && e.message
            ? e.message
            : String(e)
      if (!silent) {
        logDebug('[notify-core] Load failed: ' + msg)
      }
      return { ok: false, message: msg }
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
    }
  }

  var NOTIFY_SUMMARY_MAX_LEN = 120

  function truncateSummary(text, maxLen) {
    if (!text || typeof text !== 'string') return ''
    var s = text.replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim()
    if (s.length <= maxLen) return s
    return s.slice(0, maxLen) + '…'
  }

  // taskData: Array<{ id, prompt }> 或 Array<string>（向后兼容纯 ID 数组）
  async function showNewTaskNotification(taskData) {
    try {
      var items = Array.isArray(taskData) ? taskData.filter(Boolean) : [taskData].filter(Boolean)
      if (!items || items.length === 0) return

      // 兼容：纯字符串数组 → { id, prompt } 格式
      var normalized = items.map(function (item) {
        return typeof item === 'string' ? { id: item, prompt: '' } : item
      })
      var ids = normalized.map(function (t) { return t.id || '' }).filter(Boolean)
      if (ids.length === 0) return

      // 构建通知内容：优先使用第一个任务的 prompt 摘要
      var firstPrompt = (normalized[0] && normalized[0].prompt) || ''
      var summary = truncateSummary(firstPrompt, NOTIFY_SUMMARY_MAX_LEN)
      var msg
      if (summary) {
        msg = ids.length === 1
          ? summary
          : summary + ' ' + __ncT('ui.notification.taskCountSuffix', { count: ids.length })
      } else {
        msg = ids.length === 1
          ? __ncT('ui.notification.newTask', { id: ids[0] })
          : __ncT('ui.notification.newTasks', { count: ids.length })
      }

      logDebug('[notify-core] New task(s) detected: ' + msg)

      // 后台刷新设置（不阻塞通知派发），使用缓存立即决策
      refreshNotificationSettingsFromServer({ force: false, silent: true }).catch(function () {})

      var settings = notificationSettings || { enabled: true, macosNativeEnabled: true }
      if (settings && settings.enabled === false) {
        logDebug('[notify-core] Notifications disabled (enabled=false), skipping')
        return
      }

      var types = ['vscode']
      if (settings && settings.macosNativeEnabled) {
        types.push('macos_native')
      }
      logDebug('[notify-core] Dispatching notification types=' + types.join(',') + ' macosNativeEnabled=' + !!(settings && settings.macosNativeEnabled))

      postNotificationEvent({
        title: __ncT('ui.notification.title'),
        message: msg,
        trigger: 'immediate',
        types: types,
        metadata: {
          presentation: 'statusBar',
          severity: 'info',
          timeoutMs: 3000,
          isTest: false,
          kind: 'new_tasks',
          taskIds: ids
        },
        source: 'webview-notify-core',
        dedupeKey: 'new_tasks:' + ids.join('|')
      })
    } catch (e) {
      // 忽略：通知失败不应影响主流程
    }
  }

  // 暴露最小 API：供 webview-ui / settings-ui 按需调用
  const api = {
    refreshNotificationSettingsFromServer,
    getCachedNotificationSettings,
    setCachedNotificationSettings,
    showNewTaskNotification
  }

  try {

    globalThis.AIIAWebviewNotifyCore = api
  } catch (e) {
    try {

      window.AIIAWebviewNotifyCore = api
    } catch (_) {
      // 忽略
    }
  }
})()
