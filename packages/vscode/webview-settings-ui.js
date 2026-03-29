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

  // 防御性 i18n 初始化（与 webview-ui.js 同步，确保懒加载时 locale 已注册）
  ;(function ensureI18nReady() {
    try {
      var i18n =
        (typeof globalThis !== 'undefined' && globalThis.AIIA_I18N) ||
        (typeof window !== 'undefined' && window.AIIA_I18N)
      if (!i18n || typeof i18n.registerLocale !== 'function') return
      var langs = typeof i18n.getAvailableLangs === 'function' ? i18n.getAvailableLangs() : []
      if (langs.length > 0) return
      var allLocales = (typeof window !== 'undefined' && window.__AIIA_I18N_ALL_LOCALES) || null
      if (allLocales && typeof allLocales === 'object') {
        var keys = Object.keys(allLocales)
        for (var i = 0; i < keys.length; i++) {
          if (allLocales[keys[i]] && typeof allLocales[keys[i]] === 'object') {
            i18n.registerLocale(keys[i], allLocales[keys[i]])
          }
        }
      }
      var loc = (typeof window !== 'undefined' && window.__AIIA_I18N_LOCALE) || null
      var lang = (typeof window !== 'undefined' && window.__AIIA_I18N_LANG) || ''
      if (loc && typeof loc === 'object' && lang) {
        i18n.registerLocale(String(lang), loc)
        if (typeof i18n.setLang === 'function') i18n.setLang(String(lang))
      }
    } catch (e) { /* 忽略 */ }
  })()

  function t(key, params) {
    try {
      var i18n =
        (typeof globalThis !== 'undefined' && globalThis.AIIA_I18N) ||
        (typeof window !== 'undefined' && window.AIIA_I18N)
      if (i18n && typeof i18n.t === 'function') return i18n.t(key, params)
    } catch (e) {
      // 忽略
    }
    return key
  }

  function getNotifyCore() {
    try {
      return globalThis && globalThis.AIIAWebviewNotifyCore
        ? globalThis.AIIAWebviewNotifyCore
        : null
    } catch (e) {
      try {
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
        setSettingsHint(t('settings.hint.coreNotReady'), true)
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
        const msg =
          result && result.message ? String(result.message) : t('settings.hint.loadFailed')
        setSettingsHint(t('settings.hint.loadFailedReason', { reason: msg }), true)
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
          setSettingsHint(t('settings.hint.synced'), false, 1200)
        }
      }
      return true
    }

    if (changed && settingsDirty && !settingsRemoteChangedWhileDirty) {
      settingsRemoteChangedWhileDirty = true
      if (!silent && overlayOpen) {
        setSettingsHint(t('settings.hint.remoteChanged'), true)
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
    setSettingsHint(t('settings.hint.loading'), false)

    try {
      await refreshNotificationSettingsFromServer({ force: true, silent: false })
    } catch (e) {
      setSettingsHint(
        t('settings.hint.loadFailedReason', { reason: e && e.message ? e.message : String(e) }),
        true
      )
    }
    loadFeedbackConfig()
  }

  async function saveSettings({ silent = false } = {}) {
    if (!isSettingsOverlayOpen()) return
    if (!SERVER_URL) {
      if (!silent) setSettingsHint(t('settings.hint.syncFailedNoUrl'), true)
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
        if (!silent) setSettingsHint(t('settings.hint.noChange'), false, 1200)
        return
      }

      if (!silent) {
        setSettingsHint(t('settings.hint.syncing'), false)
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
        const msg =
          data && data.message
            ? data.message
            : t('settings.hint.syncFailedHttp', { status: resp.status })
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
      setSettingsHint(t('settings.hint.synced'), false, 1200)
    } catch (e) {
      const msg =
        e && e.name === 'AbortError'
          ? t('settings.hint.timeout')
          : e && e.message
            ? e.message
            : String(e)
      setSettingsHint(t('settings.hint.syncFailed', { reason: msg }), true)
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
        setSettingsHint(t('settings.hint.notifyDisabled'), true)
        return
      }
      if (!updates || !updates.macosNativeEnabled) {
        setSettingsHint(t('settings.hint.macosNotEnabled'), true, 2000)
      } else {
        setSettingsHint(t('settings.hint.macosTestTriggered'), false, 2000)
      }

      const posted = postMessage({
        type: 'notify',
        event: {
          title: t('settings.test.macosTitle'),
          message: t('settings.test.macosMessage'),
          trigger: 'immediate',
          types: ['macos_native'],
          metadata: { isTest: true, diagnostic: true, kind: 'test_macos_native' },
          source: 'webview-settings-ui',
          dedupeKey: 'test:macos_native'
        }
      })
      if (!posted) {
        setSettingsHint(t('settings.hint.postFailed'), true)
        return
      }
    } catch (e) {
      setSettingsHint(
        t('settings.hint.testFailed', { reason: e && e.message ? e.message : String(e) }),
        true
      )
    }
  }

  async function testBark() {
    try {
      if (!SERVER_URL) {
        setSettingsHint(t('settings.hint.testFailedNoUrl'), true)
        return
      }

      const updates = collectSettingsForm()
      setSettingsHint(t('settings.hint.testing'), false)
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
        const msg =
          data && data.message
            ? data.message
            : t('settings.hint.testFailedHttp', { status: resp.status })
        setSettingsHint(msg, true)
        return
      }

      setSettingsHint(data.message || t('settings.hint.barkTestSent'), false)
      postStatusInfo(data.message || t('settings.hint.barkTestSent'))
    } catch (e) {
      setSettingsHint(
        t('settings.hint.testFailed', { reason: e && e.message ? e.message : String(e) }),
        true
      )
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

      const resetFeedbackBtn = document.getElementById('settingsResetFeedbackBtn')
      if (resetFeedbackBtn) resetFeedbackBtn.addEventListener('click', resetFeedbackConfig)

      let fbSaveTimer = null
      const debounceSaveFeedback = updates => {
        if (fbSaveTimer) clearTimeout(fbSaveTimer)
        fbSaveTimer = setTimeout(() => saveFeedbackConfig(updates), 800)
      }
      const fbCountdown = document.getElementById('feedbackCountdown')
      const fbPrompt = document.getElementById('feedbackResubmitPrompt')
      const fbSuffix = document.getElementById('feedbackPromptSuffix')
      if (fbCountdown) {
        fbCountdown.addEventListener('change', () => {
          const v = parseInt(fbCountdown.value, 10)
          if (!isNaN(v) && v >= 0 && v <= 250) debounceSaveFeedback({ frontend_countdown: v })
        })
      }
      if (fbPrompt) {
        fbPrompt.addEventListener('input', () =>
          debounceSaveFeedback({ resubmit_prompt: fbPrompt.value })
        )
      }
      if (fbSuffix) {
        fbSuffix.addEventListener('input', () =>
          debounceSaveFeedback({ prompt_suffix: fbSuffix.value })
        )
      }

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

  async function loadFeedbackConfig() {
    if (!SERVER_URL) return
    try {
      const resp = await fetch(SERVER_URL + '/api/get-feedback-prompts', { cache: 'no-store' })
      if (!resp.ok) return
      const data = await resp.json()
      if (data && data.status === 'success') {
        const el = (id, v) => {
          const e = document.getElementById(id)
          if (e) e.value = v == null ? '' : String(v)
        }
        if (data.config) {
          const c = data.config
          el('feedbackCountdown', c.frontend_countdown ?? 240)
          el('feedbackResubmitPrompt', c.resubmit_prompt ?? '')
          el('feedbackPromptSuffix', c.prompt_suffix ?? '')
        }
        if (data.meta && data.meta.config_file) {
          el('settingsConfigPath', data.meta.config_file)
        }
      }
    } catch (e) {
      // 静默失败
    }
  }

  async function saveFeedbackConfig(updates) {
    if (!SERVER_URL) return
    try {
      const resp = await fetch(SERVER_URL + '/api/update-feedback-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      })
      const data = await resp.json().catch(() => ({}))
      if (resp.ok && data.status === 'success') {
        setSettingsHint(t('settings.feedback.saved'), false, 1200)
      } else {
        var reason = data.message || 'HTTP ' + resp.status
        setSettingsHint(t('settings.feedback.saveFailed') + ' (' + reason + ')', true)
      }
    } catch (e) {
      setSettingsHint(
        t('settings.feedback.saveFailed') + (e && e.message ? ' (' + e.message + ')' : ''),
        true
      )
    }
  }

  async function resetFeedbackConfig() {
    await saveFeedbackConfig({
      frontend_countdown: 240,
      resubmit_prompt: '\u8bf7\u7acb\u5373\u8c03\u7528 interactive_feedback \u5de5\u5177',
      prompt_suffix: '\n\u8bf7\u79ef\u6781\u8c03\u7528 interactive_feedback \u5de5\u5177'
    })
    await loadFeedbackConfig()
    setSettingsHint(t('settings.feedback.resetDone'), false, 1200)
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
    globalThis.AIIAWebviewSettingsUi = api
  } catch (e) {
    try {
      window.AIIAWebviewSettingsUi = api
    } catch (_) {
      // 忽略
    }
  }
})()
