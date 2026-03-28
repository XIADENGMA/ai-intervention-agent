/**
 * 设置管理器 - 从 app.js 拆分
 *
 * 管理 Web UI 的本地偏好设置（通知、声音、主题、Bark 等），
 * 支持 localStorage 持久化和后端配置同步。
 *
 * 依赖: notification-manager.js (notificationManager)
 * 暴露: window.settingsManager (SettingsManager 实例)
 */

// 设置管理器
class SettingsManager {
  constructor() {
    this.storageKey = 'ai-intervention-agent-settings'
    this.defaultSettings = {
      enabled: true,
      webEnabled: true,
      autoRequestPermission: true,
      soundEnabled: true,
      soundMute: false,
      soundVolume: 80,
      mobileOptimized: true,
      mobileVibrate: true,
      barkEnabled: false,
      barkUrl: 'https://api.day.app/push',
      barkDeviceKey: '',
      barkIcon: '',
      barkAction: 'none'
    }
    this.initialized = false
    // 注意：不在构造函数中调用 init()，由 DOMContentLoaded 触发
  }

  async init() {
    if (this.initialized) return
    this.settings = await this.loadSettings()
    this.feedbackConfig = await this.loadFeedbackConfig()
    this.initEventListeners()
    this.initialized = true
    console.log('SettingsManager 初始化完成')
  }

  async loadSettings() {
    try {
      // 优先从服务器加载配置
      const response = await fetch('/api/get-notification-config')
      if (response.ok) {
        const result = await response.json()
        if (result.status === 'success') {
          // 将服务器配置映射到前端格式
          const serverConfig = result.config
          const settings = {
            enabled: serverConfig.enabled ?? this.defaultSettings.enabled,
            webEnabled: serverConfig.web_enabled ?? this.defaultSettings.webEnabled,
            autoRequestPermission:
              serverConfig.auto_request_permission ?? this.defaultSettings.autoRequestPermission,
            soundEnabled: serverConfig.sound_enabled ?? this.defaultSettings.soundEnabled,
            soundMute: serverConfig.sound_mute ?? this.defaultSettings.soundMute,
            soundVolume: serverConfig.sound_volume ?? this.defaultSettings.soundVolume,
            mobileOptimized: serverConfig.mobile_optimized ?? this.defaultSettings.mobileOptimized,
            mobileVibrate: serverConfig.mobile_vibrate ?? this.defaultSettings.mobileVibrate,
            barkEnabled: serverConfig.bark_enabled ?? this.defaultSettings.barkEnabled,
            barkUrl: serverConfig.bark_url ?? this.defaultSettings.barkUrl,
            barkDeviceKey: serverConfig.bark_device_key ?? this.defaultSettings.barkDeviceKey,
            barkIcon: serverConfig.bark_icon ?? this.defaultSettings.barkIcon,
            barkAction: serverConfig.bark_action ?? this.defaultSettings.barkAction
          }
          console.log('从服务器加载配置成功')
          return settings
        }
      }
    } catch (error) {
      console.warn('从服务器加载配置失败，尝试localStorage:', error)
    }

    // 回退到localStorage
    try {
      const stored = localStorage.getItem(this.storageKey)
      if (stored) {
        const parsed = JSON.parse(stored)
        return { ...this.defaultSettings, ...parsed }
      }
    } catch (error) {
      console.warn('加载设置失败，使用默认设置:', error)
    }
    return { ...this.defaultSettings }
  }

  saveSettings() {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify(this.settings))
      console.log('设置已保存')
    } catch (error) {
      console.error('保存设置失败:', error)
    }
  }

  updateSetting(key, value) {
    this.settings[key] = value
    this.saveSettings()
    this.applySettings()
    console.log(`设置已更新: ${key} = ${value}`)
  }

  applySettings(options = {}) {
    const { syncBackend = true } = options
    // 更新前端通知管理器配置
    if (notificationManager) {
      notificationManager.updateConfig({
        enabled: this.settings.enabled,
        webEnabled: this.settings.webEnabled,
        autoRequestPermission: this.settings.autoRequestPermission,
        soundEnabled: this.settings.soundEnabled,
        soundMute: this.settings.soundMute,
        soundVolume: this.settings.soundVolume / 100,
        mobileOptimized: this.settings.mobileOptimized,
        mobileVibrate: this.settings.mobileVibrate,
        barkEnabled: this.settings.barkEnabled,
        barkUrl: this.settings.barkUrl,
        barkDeviceKey: this.settings.barkDeviceKey,
        barkIcon: this.settings.barkIcon,
        barkAction: this.settings.barkAction
      })
    }

    // 同步配置到后端
    if (syncBackend) {
      this.syncConfigToBackend()
    }
  }

  async syncConfigToBackend() {
    try {
      const response = await fetch('/api/update-notification-config', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(this.settings)
      })

      const result = await response.json()
      if (response.ok && result.status === 'success') {
        console.log('后端通知配置已同步')
      } else {
        console.warn('同步后端配置失败:', result.message)
      }
    } catch (error) {
      console.error('同步后端配置失败:', error)
    }
  }

  resetSettings() {
    this.settings = { ...this.defaultSettings }
    this.saveSettings()
    this.updateUI()
    this.applySettings()
    console.log('设置已重置为默认值')
  }

  updateUI() {
    // 更新设置面板中的控件状态
    document.getElementById('notification-enabled').checked = this.settings.enabled
    document.getElementById('web-notification-enabled').checked = this.settings.webEnabled
    document.getElementById('auto-request-permission').checked = this.settings.autoRequestPermission
    document.getElementById('sound-notification-enabled').checked = this.settings.soundEnabled
    document.getElementById('sound-mute').checked = this.settings.soundMute
    document.getElementById('sound-volume').value = this.settings.soundVolume
    document.querySelector('.volume-value').textContent = `${this.settings.soundVolume}%`
    document.getElementById('mobile-optimized').checked = this.settings.mobileOptimized
    document.getElementById('mobile-vibrate').checked = this.settings.mobileVibrate

    // 语言选择器
    const langSelect = document.getElementById('language-select')
    if (langSelect) {
      const currentLang = window.AIIA_I18N ? window.AIIA_I18N.getLang() : 'auto'
      const cfgLang = window.AIIA_CONFIG_LANG || 'auto'
      langSelect.value = cfgLang !== 'auto' ? cfgLang : (currentLang || 'auto')
    }

    // 更新 Bark 设置
    document.getElementById('bark-notification-enabled').checked = this.settings.barkEnabled
    document.getElementById('bark-url').value = this.settings.barkUrl
    document.getElementById('bark-device-key').value = this.settings.barkDeviceKey
    document.getElementById('bark-icon').value = this.settings.barkIcon
    document.getElementById('bark-action').value = this.settings.barkAction
  }

  /**
   * 获取状态图标 SVG（Claude 风格线条图标）
   *
   * 功能说明：
   *   生成用于设置面板状态显示的 SVG 图标，替代原有的 emoji。
   *   采用 Claude 官方设计风格：线条图标、适当的 stroke-width。
   *
   * 设计规范：
   *   - 尺寸：16x16px
   *   - stroke-width: 2（与其他图标一致）
   *   - stroke-linecap/linejoin: round（圆润的线条端点）
   *   - 垂直居中：vertical-align: middle
   *   - 与文字间距：margin-right: 4px
   *
   * 颜色方案：
   *   - success: #4CAF50（绿色）- 表示正常/已启用
   *   - error: #F44336（红色）- 表示错误/已禁用
   *   - warning: #FF9800（橙色）- 表示警告/未配置
   *   - paused: #9E9E9E（灰色）- 表示暂停状态
   *
   * @param {string} type - 图标类型：'success' | 'error' | 'warning' | 'paused'
   * @returns {string} SVG HTML 字符串，可直接插入到 innerHTML
   */
  getStatusIcon(type) {
    const icons = {
      // 成功图标（勾号）- 浏览器支持/通知已授权/音频运行中
      success: `<svg class="status-icon status-icon-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px; color: #4CAF50;"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
      // 错误图标（叉号）- 不支持/已拒绝/已关闭
      error: `<svg class="status-icon status-icon-error" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px; color: #F44336;"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`,
      // 警告图标（感叹号三角形）- 未请求权限/未知状态
      warning: `<svg class="status-icon status-icon-warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px; color: #FF9800;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`,
      // 暂停图标（双竖线）- 音频已暂停
      paused: `<svg class="status-icon status-icon-paused" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px; color: #9E9E9E;"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>`
    }
    // 默认返回警告图标，处理未知类型
    return icons[type] || icons.warning
  }

  updateStatus() {
    // 更新状态信息（使用 SVG 图标替代 emoji）
    const secureContext =
      typeof window !== 'undefined' && typeof window.isSecureContext === 'boolean'
        ? window.isSecureContext
        : null
    const origin =
      typeof window !== 'undefined' && window.location && typeof window.location.origin === 'string'
        ? window.location.origin
        : ''

    const browserSupportHtml = notificationManager.isSupported
      ? secureContext === false
        ? this.getStatusIcon('warning') + t('env.supportedLimited')
        : this.getStatusIcon('success') + t('env.supported')
      : this.getStatusIcon('error') + t('env.notSupported')

    let secureContextHtml
    if (secureContext === true) {
      secureContextHtml = this.getStatusIcon('success') + (origin ? t('env.secureOrigin', { origin: origin }) : t('env.secure'))
    } else if (secureContext === false) {
      secureContextHtml =
        this.getStatusIcon('warning') +
        (origin ? t('env.insecureOrigin', { origin: origin }) : t('env.insecure'))
    } else {
      secureContextHtml = this.getStatusIcon('warning') + t('env.unknown')
    }

    let permissionHtml
    if (secureContext === false) {
      permissionHtml = this.getStatusIcon('warning') + t('env.permLimited')
    } else if (notificationManager.permission === 'granted') {
      permissionHtml = this.getStatusIcon('success') + t('env.permGranted')
    } else if (notificationManager.permission === 'denied') {
      permissionHtml = this.getStatusIcon('error') + t('env.permDenied')
    } else {
      permissionHtml = this.getStatusIcon('warning') + t('env.permNotRequested')
    }

    // 音频状态中文化
    let audioStateHtml = this.getStatusIcon('error') + t('env.audioUnavailable')
    if (notificationManager.audioContext) {
      const state = notificationManager.audioContext.state
      switch (state) {
        case 'running':
          audioStateHtml = this.getStatusIcon('success') + t('env.audioRunning')
          break
        case 'suspended':
          audioStateHtml = this.getStatusIcon('paused') + t('env.audioPaused')
          break
        case 'closed':
          audioStateHtml = this.getStatusIcon('error') + t('env.audioClosed')
          break
        default:
          audioStateHtml = this.getStatusIcon('warning') + state
      }
    }

    document.getElementById('browser-support-status').innerHTML = browserSupportHtml
    document.getElementById('notification-permission-status').innerHTML = permissionHtml
    document.getElementById('audio-status').innerHTML = audioStateHtml
    const secureEl = document.getElementById('notification-secure-context-status')
    if (secureEl) {
      secureEl.innerHTML = secureContextHtml
    }
  }

  initEventListeners() {
    // 设置按钮点击事件 - 使用直接绑定确保可靠
    const settingsBtn = document.getElementById('settings-btn')
    const settingsCloseBtn = document.getElementById('settings-close-btn')
    const testNotificationBtn = document.getElementById('test-notification-btn')
    const testBarkNotificationBtn = document.getElementById('test-bark-notification-btn')
    const resetSettingsBtn = document.getElementById('reset-settings-btn')

    if (settingsBtn) {
      settingsBtn.addEventListener('click', e => {
        e.stopPropagation()
        this.showSettings()
      })
    }
    if (settingsCloseBtn) {
      settingsCloseBtn.addEventListener('click', () => this.hideSettings())
    }
    if (testNotificationBtn) {
      testNotificationBtn.addEventListener('click', () => this.testNotification())
    }
    if (testBarkNotificationBtn) {
      testBarkNotificationBtn.addEventListener('click', () => this.testBarkNotification())
    }
    if (resetSettingsBtn) {
      resetSettingsBtn.addEventListener('click', () => this.resetSettings())
    }

    const resetFeedbackBtn = document.getElementById('reset-feedback-config-btn')
    if (resetFeedbackBtn) {
      resetFeedbackBtn.addEventListener('click', () => this.resetFeedbackConfig())
    }

    const feedbackCountdown = document.getElementById('feedback-countdown')
    const feedbackPrompt = document.getElementById('feedback-resubmit-prompt')
    const feedbackSuffix = document.getElementById('feedback-prompt-suffix')

    let feedbackSaveTimer = null
    const debounceSaveFeedback = (updates) => {
      if (feedbackSaveTimer) clearTimeout(feedbackSaveTimer)
      feedbackSaveTimer = setTimeout(() => this.saveFeedbackConfig(updates), 800)
    }

    if (feedbackCountdown) {
      feedbackCountdown.addEventListener('change', () => {
        const val = parseInt(feedbackCountdown.value, 10)
        if (!isNaN(val) && val >= 0 && val <= 250) {
          debounceSaveFeedback({ frontend_countdown: val })
        }
      })
    }
    if (feedbackPrompt) {
      feedbackPrompt.addEventListener('input', () => {
        debounceSaveFeedback({ resubmit_prompt: feedbackPrompt.value })
      })
    }
    if (feedbackSuffix) {
      feedbackSuffix.addEventListener('input', () => {
        debounceSaveFeedback({ prompt_suffix: feedbackSuffix.value })
      })
    }

    // 主题切换按钮点击事件 - 已由 theme.js 处理，此处删除避免重复绑定

    // 语言切换
    const langSelect = document.getElementById('language-select')
    if (langSelect) {
      langSelect.addEventListener('change', () => {
        const newLang = langSelect.value
        if (window.AIIA_I18N) {
          if (newLang === 'auto') {
            window.AIIA_I18N.setLang(window.AIIA_I18N.detectLang())
          } else {
            window.AIIA_I18N.setLang(newLang)
          }
          window.AIIA_I18N.translateDOM()
        }
      })
    }

    // 设置面板背景点击关闭
    document.addEventListener('click', e => {
      if (e.target.id === 'settings-panel') {
        this.hideSettings()
      }
    })

    // 设置项变更事件
    document.addEventListener('change', e => {
      const settingMap = {
        'notification-enabled': 'enabled',
        'web-notification-enabled': 'webEnabled',
        'auto-request-permission': 'autoRequestPermission',
        'sound-notification-enabled': 'soundEnabled',
        'sound-mute': 'soundMute',
        'mobile-optimized': 'mobileOptimized',
        'mobile-vibrate': 'mobileVibrate',
        'bark-notification-enabled': 'barkEnabled'
      }

      if (settingMap[e.target.id]) {
        this.updateSetting(settingMap[e.target.id], e.target.checked)
      } else if (e.target.id === 'sound-volume') {
        this.updateSetting('soundVolume', parseInt(e.target.value))
        document.querySelector('.volume-value').textContent = `${e.target.value}%`
      } else if (e.target.id === 'bark-url') {
        this.updateSetting('barkUrl', e.target.value)
      } else if (e.target.id === 'bark-device-key') {
        this.updateSetting('barkDeviceKey', e.target.value)
      } else if (e.target.id === 'bark-icon') {
        this.updateSetting('barkIcon', e.target.value)
      } else if (e.target.id === 'bark-action') {
        this.updateSetting('barkAction', e.target.value)
      }
    })

    window.addEventListener('notification-permission-changed', () => {
      this.updateStatus()
    })
  }

  async showSettings() {
    // 防御性：确保已初始化（极端情况下用户可能在 init() 未完成时快速点击）
    if (!this.initialized) {
      try {
        await this.init()
      } catch (e) {
        console.warn('SettingsManager 初始化失败（打开设置面板时）:', e)
      }
    }

    const panel = document.getElementById('settings-panel')
    if (panel) {
      // 临时移除 container 的 overflow: hidden，以便设置面板可以覆盖整个屏幕
      const container = document.querySelector('.container')
      if (container) {
        container.style.overflow = 'visible'
      }

      panel.classList.remove('hidden')
      panel.style.display = 'flex'

      this.applySettingsTheme()

      this._settingsEscHandler = (e) => { if (e.key === 'Escape') this.hideSettings() }
      document.addEventListener('keydown', this._settingsEscHandler)

      const firstFocusable = panel.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      if (firstFocusable) setTimeout(() => firstFocusable.focus(), 50)
    }

    // 每次打开设置面板都从后端刷新一次配置
    // 目的：
    // - 让“外部编辑 config.jsonc”能在不刷新页面的情况下反映到 UI
    // - 避免打开面板时把旧的本地缓存配置反向写回后端（覆盖外部修改）
    try {
      this.settings = await this.loadSettings()
    } catch (e) {
      console.warn('打开设置面板时刷新配置失败，继续使用当前设置:', e)
    }
    try {
      this.feedbackConfig = await this.loadFeedbackConfig()
    } catch (e) {
      console.warn('打开设置面板时刷新反馈配置失败:', e)
    }

    this.updateUI()
    this.updateFeedbackUI()
    this.updateStatus()
  }

  applySettingsTheme() {
    const theme = document.documentElement.getAttribute('data-theme')

    // 动态注入浅色主题样式（解决 CSS 优先级问题）
    if (!document.getElementById('settings-light-theme-styles')) {
      const style = document.createElement('style')
      style.id = 'settings-light-theme-styles'
      style.textContent = `
        [data-theme="light"] .settings-panel {
          background: rgba(0, 0, 0, 0.7) !important;
        }
        [data-theme="light"] .settings-content {
          background: #faf9f5 !important;
          border: 1px solid rgba(0, 0, 0, 0.12) !important;
          box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2), 0 10px 20px rgba(0, 0, 0, 0.1) !important;
        }
        [data-theme="light"] .settings-body {
          background: #faf9f5 !important;
        }
        [data-theme="light"] .setting-group {
          background: #ffffff !important;
          border: 1px solid rgba(0, 0, 0, 0.1) !important;
        }
        [data-theme="light"] .setting-subgroup {
          background: #f8f8f5 !important;
        }
        [data-theme="light"] .settings-header {
          border-bottom: 1px solid rgba(0, 0, 0, 0.1) !important;
          background: #f2f1ec !important;
        }
        [data-theme="light"] .status-row {
          background: rgba(0, 0, 0, 0.02) !important;
          border-color: rgba(0, 0, 0, 0.08) !important;
          color: #141413 !important;
        }
        [data-theme="light"] .status-row span:first-child {
          color: rgba(20, 20, 19, 0.85) !important;
        }
        [data-theme="light"] .status-row span:last-child {
          color: #141413 !important;
        }
        [data-theme="light"] .setting-description {
          color: rgba(20, 20, 19, 0.65) !important;
        }
        [data-theme="light"] .setting-item:hover .setting-description {
          color: rgba(20, 20, 19, 0.75) !important;
        }
        [data-theme="light"] .setting-label:hover .setting-title {
          color: rgba(20, 20, 19, 0.9) !important;
        }
        [data-theme="light"] .setting-input::placeholder {
          color: rgba(20, 20, 19, 0.5) !important;
        }
        [data-theme="light"] .setting-label,
        [data-theme="light"] .setting-title,
        [data-theme="light"] .setting-subgroup-title,
        [data-theme="light"] .settings-main-title,
        [data-theme="light"] .setting-group-title,
        [data-theme="light"] #settings-title {
          color: #141413 !important;
        }
        [data-theme="light"] .settings-main-title {
          border-bottom-color: rgba(0, 0, 0, 0.1) !important;
        }
        [data-theme="light"] .setting-group::before {
          background: linear-gradient(90deg, transparent, rgba(0, 0, 0, 0.08), transparent) !important;
        }
        [data-theme="light"] .setting-group-title {
          -webkit-text-fill-color: #141413 !important;
          background: none !important;
          border-bottom-color: rgba(0, 0, 0, 0.1) !important;
        }
        [data-theme="light"] .setting-input {
          background: #ffffff !important;
          border-color: rgba(0, 0, 0, 0.15) !important;
          color: #141413 !important;
        }
        [data-theme="light"] .setting-select {
          background: #ffffff !important;
          border-color: rgba(0, 0, 0, 0.15) !important;
          color: #141413 !important;
        }
      `
      document.head.appendChild(style)
    }
  }

  hideSettings() {
    const panel = document.getElementById('settings-panel')
    if (panel) {
      const container = document.querySelector('.container')
      if (container) {
        container.style.overflow = ''
      }

      panel.classList.add('hidden')
      panel.style.display = 'none'
    }

    if (this._settingsEscHandler) {
      document.removeEventListener('keydown', this._settingsEscHandler)
      this._settingsEscHandler = null
    }

    const settingsBtn = document.getElementById('settings-btn')
    if (settingsBtn) settingsBtn.focus()
  }

  async testNotification() {
    try {
      await notificationManager.sendNotification(
        t('notify.testTitle'),
        t('notify.testBody'),
        {
          tag: 'settings-test',
          requireInteraction: false
        }
      )
      showStatus(t('status.testSent'), 'success')
    } catch (error) {
      console.error('测试通知失败:', error)
      showStatus(t('status.testFailed') + ': ' + error.message, 'error')
    }
  }

  async testBarkNotification() {
    try {
      if (!this.settings.barkEnabled) {
        showStatus(t('status.enableBarkFirst'), 'warning')
        return
      }

      if (!this.settings.barkUrl || !this.settings.barkDeviceKey) {
        showStatus(t('status.configureBark'), 'warning')
        return
      }

      // 显示发送中状态
      showStatus(t('status.sendingBark'), 'info')

      // 通过后端API发送Bark通知，避免CORS问题
      const response = await fetch('/api/test-bark', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          bark_url: this.settings.barkUrl,
          bark_device_key: this.settings.barkDeviceKey,
          bark_icon: this.settings.barkIcon,
          bark_action: this.settings.barkAction
        })
      })

      const result = await response.json()

      if (response.ok && result.status === 'success') {
        showStatus(result.message, 'success')
        console.log('Bark 通知发送成功:', result)
      } else {
        showStatus(result.message || t('status.barkFailed'), 'error')
        console.error('Bark 通知发送失败:', result)
      }
    } catch (error) {
      console.error('Bark 测试通知失败:', error)
      showStatus(t('status.barkTestFailed', { reason: error.message }), 'error')
    }
  }

  async loadFeedbackConfig() {
    try {
      const resp = await fetch('/api/get-feedback-prompts', { cache: 'no-store' })
      if (resp.ok) {
        const data = await resp.json()
        if (data.status === 'success' && data.config) {
          return {
            frontend_countdown: data.config.frontend_countdown ?? 240,
            resubmit_prompt: data.config.resubmit_prompt ?? '',
            prompt_suffix: data.config.prompt_suffix ?? ''
          }
        }
      }
    } catch (e) {
      console.warn('加载反馈配置失败:', e)
    }
    return { frontend_countdown: 240, resubmit_prompt: '', prompt_suffix: '' }
  }

  updateFeedbackUI() {
    const fc = this.feedbackConfig || {}
    const countdownEl = document.getElementById('feedback-countdown')
    const promptEl = document.getElementById('feedback-resubmit-prompt')
    const suffixEl = document.getElementById('feedback-prompt-suffix')
    if (countdownEl) countdownEl.value = fc.frontend_countdown ?? 240
    if (promptEl) promptEl.value = fc.resubmit_prompt ?? ''
    if (suffixEl) suffixEl.value = fc.prompt_suffix ?? ''
  }

  async saveFeedbackConfig(updates) {
    try {
      const resp = await fetch('/api/update-feedback-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      })
      const data = await resp.json()
      if (resp.ok && data.status === 'success') {
        Object.assign(this.feedbackConfig, updates)
        showStatus(t('settings.feedbackConfigSaved'), 'success')
      } else {
        showStatus(data.message || t('settings.feedbackConfigSaveFailed'), 'error')
      }
    } catch (e) {
      console.error('保存反馈配置失败:', e)
      showStatus(t('settings.feedbackConfigSaveFailed'), 'error')
    }
  }

  async resetFeedbackConfig() {
    await this.saveFeedbackConfig({
      frontend_countdown: 240,
      resubmit_prompt: '请立即调用 interactive_feedback 工具',
      prompt_suffix: '\n请积极调用 interactive_feedback 工具'
    })
    this.feedbackConfig = await this.loadFeedbackConfig()
    this.updateFeedbackUI()
    showStatus(t('settings.feedbackConfigReset'), 'success')
  }
}

// 创建全局设置管理器实例
const settingsManager = new SettingsManager()
