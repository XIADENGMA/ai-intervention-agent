;(function () {
  // 设置面板 UI：仅在用户打开“通知设置”时按需加载，避免阻塞首屏
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
      // eslint-disable-next-line no-undef
      vscode = acquireVsCodeApi()
    } catch (e) {
      vscode = null
    }
  }

  const cfgEl = typeof document !== 'undefined' ? document.getElementById('aiia-config') : null
  const SERVER_URL =
    cfgEl && cfgEl.getAttribute('data-server-url')
      ? String(cfgEl.getAttribute('data-server-url'))
      : ''

  function postMessage(message) {
    try {
      if (vscode && typeof vscode.postMessage === 'function') {
        vscode.postMessage(message)
        return true
      }
    } catch (e) {
      // 忽略：设置面板异常不应影响主 UI
    }
    return false
  }

  function postNotificationEvent(event) {
    postMessage({ type: 'notify', event: event || {} })
  }

  function postStatusInfo(message, options) {
    postNotificationEvent({
      title: 'AI Intervention Agent',
      message: String(message || ''),
      trigger: 'immediate',
      types: ['vscode'],
      metadata: Object.assign(
        { presentation: 'statusBar', severity: 'info', timeoutMs: 3000 },
        options || {}
      ),
      source: 'webview-settings-ui',
      dedupeKey: message ? 'status:' + String(message).slice(0, 200) : ''
    })
  }

  function getNotifyCore() {
    try {
      // eslint-disable-next-line no-undef
      return globalThis && globalThis.AIIAWebviewNotifyCore
        ? globalThis.AIIAWebviewNotifyCore
        : null
    } catch (e) {
      try {
        // eslint-disable-next-line no-undef
        return window && window.AIIAWebviewNotifyCore ? window.AIIAWebviewNotifyCore : null
      } catch (_) {
        return null
      }
    }
  }

  function computeHash(settings) {
    try {
      return JSON.stringify(settings || {})
    } catch (e) {
      return String(Date.now())
    }
  }

  // 通知设置热更新：当配置文件 / Web UI 修改后，设置面板自动同步（无需重启）
  const SETTINGS_AUTO_REFRESH_MS = 2000
  let settingsAutoRefreshTimer = null
  let settingsDirty = false
  let settingsRemoteChangedWhileDirty = false
  let isPopulatingSettingsForm = false
  let lastNotificationSettingsHash = ''
  let settingsHintClearTimer = null

  // 设置自动保存：对齐原项目（修改即同步，无需手动点“保存”）
  const SETTINGS_AUTO_SAVE_DEBOUNCE_MS = 500
  const SETTINGS_AUTO_SAVE_TIMEOUT_MS = 3500
  let settingsAutoSaveTimer = null
  let settingsAutoSaveAbortController = null
  let settingsAutoSaveInFlight = false
  let settingsAutoSavePending = false

  let uiInitialized = false

  function setSettingsHint(message, isError, autoClearMs) {
    const hint = document.getElementById('settingsHint')
    if (!hint) return
    hint.textContent = message ? String(message) : ''
    // CSP 收紧后禁止动态写入 inline style，这里改为 class 驱动
    hint.classList.toggle('aiia-error', !!isError)
    hint.classList.toggle('aiia-has-message', !!message)

    // 自动清理：避免“已加载”这类状态常驻造成困惑
    if (settingsHintClearTimer) {
      clearTimeout(settingsHintClearTimer)
      settingsHintClearTimer = null
    }
    if (!isError && message && autoClearMs && autoClearMs > 0) {
      settingsHintClearTimer = setTimeout(() => {
        try {
          const overlay = document.getElementById('settingsOverlay')
          // 面板已关闭则不需要再显示任何提示
          if (!overlay || overlay.classList.contains('hidden')) return
          setSettingsHint('', false)
        } catch (e) {
          // 忽略
        }
      }, autoClearMs)
    }
  }

  function isSettingsOverlayOpen() {
    const overlay = document.getElementById('settingsOverlay')
    return !!(overlay && !overlay.classList.contains('hidden'))
  }

  function populateSettingsForm(settings) {
    isPopulatingSettingsForm = true
    try {
      const setChecked = (id, value) => {
        const el = document.getElementById(id)
        if (el) el.checked = !!value
      }
      const setValue = (id, value) => {
        const el = document.getElementById(id)
        if (el) el.value = value === undefined || value === null ? '' : String(value)
      }

      const s = settings || {}
      setChecked('notifyEnabled', s.enabled)
      setChecked('notifyMacOSNativeEnabled', s.macosNativeEnabled)

      setChecked('notifyBarkEnabled', s.barkEnabled)
      setValue('notifyBarkUrl', s.barkUrl)
      setValue('notifyBarkDeviceKey', s.barkDeviceKey)
      setValue('notifyBarkIcon', s.barkIcon)
      setValue('notifyBarkAction', s.barkAction)
    } finally {
      isPopulatingSettingsForm = false
    }
  }

  function collectSettingsForm() {
    const getChecked = id => {
      const el = document.getElementById(id)
      return !!(el && el.checked)
    }
    const getValue = id => {
      const el = document.getElementById(id)
      return el ? String(el.value || '') : ''
    }

    return {
      enabled: getChecked('notifyEnabled'),
      macosNativeEnabled: getChecked('notifyMacOSNativeEnabled'),

      barkEnabled: getChecked('notifyBarkEnabled'),
      barkUrl: getValue('notifyBarkUrl') || 'https://api.day.app/push',
      barkDeviceKey: getValue('notifyBarkDeviceKey'),
      barkIcon: getValue('notifyBarkIcon'),
      barkAction: getValue('notifyBarkAction') || 'none'
    }
  }

  function markSettingsDirty() {
    if (isPopulatingSettingsForm) return
    settingsDirty = true
    scheduleSettingsAutoSave()
  }

  function scheduleSettingsAutoSave() {
    if (!isSettingsOverlayOpen()) return
    if (settingsAutoSaveTimer) {
      clearTimeout(settingsAutoSaveTimer)
      settingsAutoSaveTimer = null
    }
    settingsAutoSaveTimer = setTimeout(() => {
      saveSettings({ silent: true })
    }, SETTINGS_AUTO_SAVE_DEBOUNCE_MS)
  }

  function stopSettingsAutoSave() {
    if (settingsAutoSaveTimer) {
      clearTimeout(settingsAutoSaveTimer)
      settingsAutoSaveTimer = null
    }
    settingsAutoSavePending = false
    try {
      if (
        settingsAutoSaveAbortController &&
        typeof settingsAutoSaveAbortController.abort === 'function'
      ) {
        settingsAutoSaveAbortController.abort()
      }
    } catch (e) {
      // 忽略
    } finally {
      settingsAutoSaveAbortController = null
      settingsAutoSaveInFlight = false
    }
  }

  function startSettingsAutoRefresh() {
    if (settingsAutoRefreshTimer) return
    settingsAutoRefreshTimer = setInterval(() => {
      // 静默刷新：失败不打扰用户；成功时仅在“未编辑”状态下自动同步表单
      refreshNotificationSettingsFromServer({ force: false, silent: true })
    }, SETTINGS_AUTO_REFRESH_MS)
  }

  function stopSettingsAutoRefresh() {
    if (settingsAutoRefreshTimer) {
      clearInterval(settingsAutoRefreshTimer)
      settingsAutoRefreshTimer = null
    }
    stopSettingsAutoSave()
    settingsDirty = false
    settingsRemoteChangedWhileDirty = false
  }

  async function refreshNotificationSettingsFromServer({
    force = false,
    silent = false,
    allowWhenClosed = false
  } = {}) {
    const overlayOpen = isSettingsOverlayOpen()
    // 默认只在设置面板打开时刷新；allowWhenClosed=true 用于面板关闭时的“逻辑配置加载”（不渲染表单）
    if (!overlayOpen && !allowWhenClosed) return false

    const core = getNotifyCore()
    if (!core || typeof core.refreshNotificationSettingsFromServer !== 'function') {
      if (!silent && overlayOpen) {
        setSettingsHint('加载失败：通知核心模块未就绪', true)
      }
      return false
    }

    let result = null
    try {
      result = await core.refreshNotificationSettingsFromServer({ force, silent: true })
    } catch (e) {
      result = null
    }
    if (!result || !result.ok) {
      if (!silent && overlayOpen) {
        const msg = result && result.message ? String(result.message) : '加载失败'
        setSettingsHint('加载失败：' + msg, true)
      }
      return false
    }

    const next =
      result && result.settings
        ? result.settings
        : core.getCachedNotificationSettings
          ? core.getCachedNotificationSettings()
          : null
    const nextHash = computeHash(next)
    const changed = !lastNotificationSettingsHash || nextHash !== lastNotificationSettingsHash

    if (force || (!settingsDirty && changed)) {
      lastNotificationSettingsHash = nextHash
      settingsDirty = false
      settingsRemoteChangedWhileDirty = false
      if (overlayOpen) {
        populateSettingsForm(next)
        if (!silent) {
          // 更清晰：表示“已从服务端同步”，并自动淡出
          setSettingsHint('已同步', false, 1200)
        }
      }
      return true
    }

    // 有未保存编辑：不覆盖，但提示一次
    if (changed && settingsDirty && !settingsRemoteChangedWhileDirty) {
      settingsRemoteChangedWhileDirty = true
      if (!silent && overlayOpen) {
        setSettingsHint('检测到配置已更新（当前有未保存修改），为避免覆盖，本次未自动同步', true)
      }
    }

    return true
  }

  function openSettingsOverlay() {
    const overlay = document.getElementById('settingsOverlay')
    if (overlay) overlay.classList.remove('hidden')
    startSettingsAutoRefresh()
  }

  function closeSettingsOverlay() {
    const overlay = document.getElementById('settingsOverlay')
    if (overlay) overlay.classList.add('hidden')
    stopSettingsAutoRefresh()
    setSettingsHint('', false)
  }

  async function openSettings() {
    initUiOnce()
    openSettingsOverlay()
    setSettingsHint('加载中…', false)

    try {
      // 强制拉一次最新配置并渲染（打开面板时以服务端为准）
      await refreshNotificationSettingsFromServer({ force: true, silent: false })
    } catch (e) {
      setSettingsHint('加载失败：' + (e && e.message ? e.message : String(e)), true)
    }
  }

  async function saveSettings({ silent = false } = {}) {
    if (!isSettingsOverlayOpen()) return
    if (!SERVER_URL) {
      if (!silent) setSettingsHint('同步失败：serverUrl 为空', true)
      return
    }
    if (settingsAutoSaveInFlight) {
      // 有请求在飞：标记 pending，等当前请求结束后再同步最新值
      settingsAutoSavePending = true
      return
    }
    settingsAutoSaveInFlight = true

    let timeoutId = null
    try {
      const core = getNotifyCore()
      const updates = collectSettingsForm()
      const base =
        core && typeof core.getCachedNotificationSettings === 'function'
          ? core.getCachedNotificationSettings() || {}
          : {}
      const mergedFull = Object.assign({}, base, updates)
      const mergedHash = computeHash(mergedFull)

      if (mergedHash === lastNotificationSettingsHash) {
        settingsDirty = false
        settingsRemoteChangedWhileDirty = false
        if (!silent) setSettingsHint('无需同步（未变更）', false, 1200)
        return
      }

      if (!silent) {
        setSettingsHint('同步中…', false)
      }

      try {
        if (
          settingsAutoSaveAbortController &&
          typeof settingsAutoSaveAbortController.abort === 'function'
        ) {
          settingsAutoSaveAbortController.abort()
        }
      } catch (e) {
        // 忽略
      }

      const fetchOptions = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(updates),
        cache: 'no-store'
      }
      if (typeof AbortController !== 'undefined') {
        settingsAutoSaveAbortController = new AbortController()
        fetchOptions.signal = settingsAutoSaveAbortController.signal
        timeoutId = setTimeout(() => {
          try {
            settingsAutoSaveAbortController.abort()
          } catch (e) {
            /* 忽略 */
          }
        }, SETTINGS_AUTO_SAVE_TIMEOUT_MS)
      } else {
        settingsAutoSaveAbortController = null
      }

      const resp = await fetch(SERVER_URL + '/api/update-notification-config', fetchOptions)
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || !data || data.status !== 'success') {
        const msg = data && data.message ? data.message : '同步失败（HTTP ' + resp.status + '）'
        setSettingsHint(msg, true)
        return
      }

      try {
        if (core && typeof core.setCachedNotificationSettings === 'function') {
          core.setCachedNotificationSettings(mergedFull)
        }
      } catch (e) {
        // 忽略
      }

      lastNotificationSettingsHash = mergedHash
      settingsDirty = false
      settingsRemoteChangedWhileDirty = false

      // 同步成功：短暂提示后自动隐藏（避免常驻）
      setSettingsHint('已同步', false, 1200)
    } catch (e) {
      const msg = e && e.name === 'AbortError' ? '请求超时' : e && e.message ? e.message : String(e)
      setSettingsHint('同步失败：' + msg, true)
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
      settingsAutoSaveInFlight = false
      if (settingsAutoSavePending) {
        settingsAutoSavePending = false
        // 若期间仍有未同步修改，则再触发一次（debounce 复用，避免风暴）
        if (settingsDirty && isSettingsOverlayOpen()) {
          scheduleSettingsAutoSave()
        }
      }
    }
  }

  function testMacOSNativeNotification() {
    try {
      const updates = collectSettingsForm()
      if (updates && updates.enabled === false) {
        setSettingsHint('通知已关闭：请先开启“启用通知”', true)
        return
      }
      if (!updates || !updates.macosNativeEnabled) {
        setSettingsHint('提示：当前未开启“macOS 原生通知”，仍将执行一次测试用于排查…', true, 2000)
      } else {
        setSettingsHint('已触发测试通知：请留意系统通知', false, 2000)
      }

      const posted = postMessage({
        type: 'notify',
        event: {
          title: 'AI Intervention Agent 测试',
          message: '这是一个 macOS 原生通知测试，如果收到此消息，说明配置正确。',
          trigger: 'immediate',
          types: ['macos_native'],
          metadata: { isTest: true, diagnostic: true, kind: 'test_macos_native' },
          source: 'webview-settings-ui',
          dedupeKey: 'test:macos_native'
        }
      })
      if (!posted) {
        setSettingsHint(
          '发送失败：VS Code Webview API 不可用（请尝试关闭/重新打开面板或重载窗口）',
          true
        )
        return
      }
    } catch (e) {
      setSettingsHint('测试失败：' + (e && e.message ? e.message : String(e)), true)
    }
  }

  async function testBark() {
    try {
      if (!SERVER_URL) {
        setSettingsHint('测试失败：serverUrl 为空', true)
        return
      }

      const updates = collectSettingsForm()
      setSettingsHint('测试中…', false)
      const resp = await fetch(SERVER_URL + '/api/test-bark', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          bark_url: updates.barkUrl || 'https://api.day.app/push',
          bark_device_key: updates.barkDeviceKey || '',
          bark_icon: updates.barkIcon || '',
          bark_action: updates.barkAction || 'none'
        }),
        cache: 'no-store'
      })

      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || !data || data.status !== 'success') {
        const msg = data && data.message ? data.message : '测试失败（HTTP ' + resp.status + '）'
        setSettingsHint(msg, true)
        return
      }

      setSettingsHint(data.message || '测试通知已发送，请检查设备', false)
      postStatusInfo(data.message || 'Bark 测试通知已发送')
    } catch (e) {
      setSettingsHint('测试失败：' + (e && e.message ? e.message : String(e)), true)
    }
  }

  function initUiOnce() {
    if (uiInitialized) return
    uiInitialized = true

    try {
      const settingsOverlay = document.getElementById('settingsOverlay')
      const settingsPanel = document.getElementById('settingsPanel')
      const settingsClose = document.getElementById('settingsClose')
      const settingsTestNativeBtn = document.getElementById('settingsTestNativeBtn')
      const settingsTestBarkBtn = document.getElementById('settingsTestBarkBtn')

      if (settingsClose) settingsClose.addEventListener('click', closeSettingsOverlay)
      if (settingsTestNativeBtn)
        settingsTestNativeBtn.addEventListener('click', testMacOSNativeNotification)
      if (settingsTestBarkBtn) settingsTestBarkBtn.addEventListener('click', testBark)

      if (settingsOverlay) {
        settingsOverlay.addEventListener('click', e => {
          if (e.target === settingsOverlay) {
            closeSettingsOverlay()
          }
        })
      }
      if (settingsPanel) {
        settingsPanel.addEventListener('click', e => e.stopPropagation())
        // 设置面板：用户编辑时标记 dirty（避免热更新覆盖用户未保存输入）
        const maybeMarkDirty = e => {
          const t = e && e.target
          const id = t && t.id ? String(t.id) : ''
          if (!id || !id.startsWith('notify')) return
          markSettingsDirty()
        }
        settingsPanel.addEventListener('input', maybeMarkDirty)
        settingsPanel.addEventListener('change', maybeMarkDirty)
      }
    } catch (e) {
      // 忽略
    }
  }

  function dispose() {
    try {
      stopSettingsAutoRefresh()
    } catch (e) {
      // 忽略
    }
    try {
      if (settingsHintClearTimer) {
        clearTimeout(settingsHintClearTimer)
        settingsHintClearTimer = null
      }
    } catch (e) {
      // 忽略
    }
  }

  const api = {
    openSettings,
    closeSettingsOverlay,
    refreshNotificationSettingsFromServer,
    dispose
  }

  try {
    // eslint-disable-next-line no-undef
    globalThis.AIIAWebviewSettingsUi = api
  } catch (e) {
    try {
      // eslint-disable-next-line no-undef
      window.AIIAWebviewSettingsUi = api
    } catch (_) {
      // 忽略
    }
  }
})()
