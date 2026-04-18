/**
 * 通知管理系统 - 从 app.js 拆分
 *
 * 提供 Web Notification API、音频播放、Service Worker 通知、
 * Bark 推送、事件去重、降级方案等完整通知功能。
 *
 * 依赖: dom-security.js (DOMSecurity), i18n.js (t())
 * 暴露: window.notificationManager (NotificationManager 实例)
 */

function t(key, params) {
  try {
    if (window.AIIA_I18N && typeof window.AIIA_I18N.t === 'function') {
      return window.AIIA_I18N.t(key, params)
    }
  } catch (_e) { /* noop */ }
  return key
}

function isMobileDevice() {
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
    navigator.userAgent
  )
}

// 通知管理系统
class NotificationManager {
  constructor() {
    this.isSupported = 'Notification' in window
    this.permission = this.isSupported ? Notification.permission : 'denied'
    this.audioContext = null
    this.audioBuffers = new Map()
    this.serviceWorkerRegistration = null
    this.initPromise = null
    this.permissionRequestPromise = null
    this.autoPermissionListenersBound = false
    this.boundPermissionRequestHandler = null
    this.config = {
      enabled: true,
      webEnabled: true,
      soundEnabled: true,
      soundVolume: 0.8,
      soundMute: false,
      autoRequestPermission: true,
      timeout: 5000,
      icon: '/icons/icon.svg',
      mobileOptimized: true,
      mobileVibrate: true
    }
  }

  async init() {
    if (this.initPromise) {
      return this.initPromise
    }

    this.initPromise = (async () => {
      console.log('Initializing notification manager…')
      try {
        const hostname =
          window.location && typeof window.location.hostname === 'string'
            ? window.location.hostname
            : ''
        const origin =
          window.location && typeof window.location.origin === 'string'
            ? window.location.origin
            : ''
        const secureContext =
          typeof window.isSecureContext === 'boolean' ? window.isSecureContext : null
        console.log(
          '[notification env] hostname:',
          hostname,
          'isSecureContext:',
          secureContext,
          'origin:',
          origin
        )
      } catch (e) {
        // 忽略：诊断日志失败不应影响通知初始化
      }
      this.syncPermissionState()

      if (!this.isSupported) {
        console.warn('Browser does not support Web Notification API')
      } else {
        await this.registerServiceWorker()
        this.bindAutoPermissionRequest()
      }

      await this.initAudio()
      console.log('Notification manager initialized')
    })()

    return this.initPromise
  }

  syncPermissionState() {
    this.permission = this.isSupported ? Notification.permission : 'denied'
    return this.permission
  }

  supportsServiceWorkerNotifications() {
    return (
      typeof navigator !== 'undefined' &&
      'serviceWorker' in navigator &&
      Boolean(window.isSecureContext)
    )
  }

  async registerServiceWorker() {
    if (!this.supportsServiceWorkerNotifications()) {
      if (typeof window.isSecureContext === 'boolean' && window.isSecureContext === false) {
        console.warn('Not in a secure context; cannot register notification service worker')
      }
      return null
    }

    if (this.serviceWorkerRegistration) {
      return this.serviceWorkerRegistration
    }

    try {
      await navigator.serviceWorker.register('/notification-service-worker.js')
      this.serviceWorkerRegistration = await navigator.serviceWorker.ready
      console.log('Notification service worker registered')
      return this.serviceWorkerRegistration
    } catch (error) {
      console.warn('Notification service worker registration failed:', error)
      return null
    }
  }

  bindAutoPermissionRequest() {
    if (!this.isSupported) return

    // 非安全上下文下无法弹出权限请求，避免绑定无意义的自动触发
    if (typeof window.isSecureContext === 'boolean' && window.isSecureContext === false) {
      this.removeAutoPermissionRequestListeners()
      return
    }

    if (!this.config.autoRequestPermission || this.syncPermissionState() !== 'default') {
      this.removeAutoPermissionRequestListeners()
      return
    }

    if (this.autoPermissionListenersBound) {
      return
    }

    this.boundPermissionRequestHandler = () => {
      if (!this.config.autoRequestPermission) {
        this.removeAutoPermissionRequestListeners()
        return
      }

      if (this.syncPermissionState() !== 'default') {
        this.removeAutoPermissionRequestListeners()
        return
      }

      this.requestPermission({ requireUserGesture: false }).finally(() => {
        if (this.syncPermissionState() !== 'default') {
          this.removeAutoPermissionRequestListeners()
        }
      })
    }
    ;['click', 'keydown', 'touchstart'].forEach(eventName => {
      document.addEventListener(eventName, this.boundPermissionRequestHandler, {
        once: true,
        passive: true
      })
    })

    this.autoPermissionListenersBound = true
  }

  removeAutoPermissionRequestListeners() {
    if (!this.autoPermissionListenersBound || !this.boundPermissionRequestHandler) {
      return
    }

    ;['click', 'keydown', 'touchstart'].forEach(eventName => {
      document.removeEventListener(eventName, this.boundPermissionRequestHandler)
    })

    this.autoPermissionListenersBound = false
    this.boundPermissionRequestHandler = null
  }

  async requestPermission({ requireUserGesture = true } = {}) {
    if (!this.isSupported) {
      console.warn('Browser does not support Web Notification API')
      return false
    }

    this.syncPermissionState()
    if (this.permission === 'granted') {
      return true
    }

    if (this.permission === 'denied') {
      return false
    }

    if (typeof window.isSecureContext === 'boolean' && window.isSecureContext === false) {
      console.warn('Not in a secure context; browser will not prompt for notification permission')
      return false
    }

    if (
      requireUserGesture &&
      navigator.userActivation &&
      navigator.userActivation.isActive === false
    ) {
      console.warn('Notification permission request requires user gesture; deferred to next interaction')
      this.bindAutoPermissionRequest()
      return false
    }

    if (this.permissionRequestPromise) {
      return this.permissionRequestPromise
    }

    try {
      this.permissionRequestPromise = (async () => {
        if (Notification.requestPermission.length === 0) {
          this.permission = await Notification.requestPermission()
        } else {
          this.permission = await new Promise(resolve => {
            Notification.requestPermission(resolve)
          })
        }

        console.log(`Notification permission state: ${this.permission}`)
        window.dispatchEvent(
          new CustomEvent('notification-permission-changed', {
            detail: { permission: this.permission }
          })
        )
        return this.permission === 'granted'
      })()

      return await this.permissionRequestPromise
    } catch (error) {
      console.error('Request notification permission failed:', error)
      return false
    } finally {
      this.permissionRequestPromise = null
      if (this.permission !== 'default') {
        this.removeAutoPermissionRequestListeners()
      }
    }
  }

  async initAudio() {
    try {
      // 检查浏览器音频支持
      const AudioContextClass =
        window.AudioContext || window.webkitAudioContext || window.mozAudioContext
      if (!AudioContextClass) {
        console.warn('Browser does not support Web Audio API')
        return
      }

      // 创建音频上下文（需要用户交互后才能启用）
      this.audioContext = new AudioContextClass()

      await this.loadAudioFile('default', '/sounds/deng.mp3')
      if (!this.audioBuffers.has('default')) {
        this._synthBuffer = this._createSynthNotificationBuffer()
      }

      console.log('Audio system initialized')
    } catch (error) {
      console.warn('Audio system initialization failed:', error)
      // 降级：禁用音频功能
      this.config.soundEnabled = false
    }
  }

  async loadAudioFile(name, url) {
    if (!this.audioContext) return false

    try {
      const response = await fetch(url)
      const arrayBuffer = await response.arrayBuffer()
      const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer)
      this.audioBuffers.set(name, audioBuffer)
      console.log(`Audio file loaded: ${name}`)
      return true
    } catch (error) {
      console.warn(`Audio file load failed ${name}:`, error)
      return false
    }
  }

  async showNotification(title, message, options = {}) {
    if (!this.config.enabled || !this.config.webEnabled) {
      console.log('Web notifications disabled')
      return null
    }

    if (!this.isSupported) {
      console.warn('Browser does not support notifications; using fallback')
      this.showFallbackNotification(title, message, { ...options, reason: 'unsupported' })
      return null
    }

    if (typeof window.isSecureContext === 'boolean' && window.isSecureContext === false) {
      const origin =
        window.location && typeof window.location.origin === 'string' ? window.location.origin : ''
      const host =
        window.location && typeof window.location.host === 'string' ? window.location.host : ''
      const where = origin || host || 'current page'
      this.showFallbackNotification(
        'Browser native notifications unavailable',
        `Current origin (${where}) is not a secure context. Please access over HTTPS or localhost/127.0.0.1 and retry.`,
        { ...options, reason: 'insecure_context' }
      )
      return null
    }

    this.syncPermissionState()
    if (this.permission !== 'granted') {
      console.warn('No system notification permission granted')
      if (this.config.autoRequestPermission) {
        const granted = await this.requestPermission({
          requireUserGesture: !(navigator.userActivation && navigator.userActivation.isActive)
        })
        if (!granted) {
          this.showFallbackNotification(title, message, {
            ...options,
            reason: this.permission === 'denied' ? 'permission_denied' : 'permission_default'
          })
          return null
        }
      } else {
        this.showFallbackNotification(title, message, {
          ...options,
          reason: 'permission_disabled'
        })
        return null
      }
    }

    try {
      const {
        onClick,
        url,
        data: extraData,
        icon,
        badge,
        tag,
        requireInteraction,
        silent,
        ...restOptions
      } = options

      const notificationOptions = {
        body: message,
        icon: icon || this.config.icon,
        badge: badge || this.config.icon,
        tag: tag || 'ai-intervention-agent',
        requireInteraction: requireInteraction || false,
        silent: silent || false,
        data: {
          url: url || window.location.href,
          ...extraData
        },
        ...restOptions
      }

      const notification = await this.showSystemNotification(title, notificationOptions, {
        ...restOptions,
        onClick
      })

      if (!notification) {
        this.showFallbackNotification(title, message, {
          ...options,
          reason: 'system_notification_failed'
        })
        return null
      }

      console.log('System notification shown:', title)
      return notification
    } catch (error) {
      console.error('Show notification failed:', error)
      this.showFallbackNotification(title, message, {
        ...options,
        reason: 'show_notification_exception'
      })
      return null
    }
  }

  async showSystemNotification(title, notificationOptions, options = {}) {
    const registration = await this.registerServiceWorker()
    if (registration && typeof registration.showNotification === 'function') {
      try {
        await registration.showNotification(title, notificationOptions)
        return {
          close() {}
        }
      } catch (error) {
        console.warn('Failed to show notification via service worker; falling back to page Notification:', error)
      }
    }

    try {
      const notification = new Notification(title, notificationOptions)

      // 设置超时自动关闭
      if (this.config.timeout > 0) {
        setTimeout(() => {
          notification.close()
        }, this.config.timeout)
      }

      // 点击事件处理
      notification.onclick = () => {
        window.focus()
        notification.close()
        if (options.onClick) {
          options.onClick()
        }
      }

      // 移动设备震动
      if (this.config.mobileVibrate && 'vibrate' in navigator) {
        navigator.vibrate([200, 100, 200])
      }

      return notification
    } catch (error) {
      console.error('Page Notification creation failed:', error)
      return null
    }
  }

  async playSound(soundName = 'default', volume = null, retryCount = 0) {
    if (!this.config.enabled || !this.config.soundEnabled || this.config.soundMute) {
      console.log('Sound notifications disabled')
      return false
    }

    if (!this.audioContext) {
      console.warn('Audio context not initialized; trying fallback')
      this.recordFallbackEvent('audio', { reason: 'no_audio_context', soundName })
      return this.playSoundFallback(soundName)
    }

    // 恢复音频上下文（如果被暂停）
    if (this.audioContext.state === 'suspended') {
      try {
        await this.audioContext.resume()
        console.log('Audio context resumed')
      } catch (error) {
        console.warn('Resume audio context failed:', error)
        this.recordFallbackEvent('audio', {
          reason: 'resume_failed',
          error: error.message,
          soundName
        })
        return this.playSoundFallback(soundName)
      }
    }

    const audioBuffer = this.audioBuffers.get(soundName)
    if (!audioBuffer) {
      console.warn(`Audio file not found: ${soundName}`)
      // 尝试加载默认音频文件
      if (soundName !== 'default') {
        console.log('Trying default audio file')
        return this.playSound('default', volume, retryCount)
      }
      this.recordFallbackEvent('audio', { reason: 'buffer_not_found', soundName })
      return this.playSoundFallback(soundName)
    }

    try {
      const source = this.audioContext.createBufferSource()
      const gainNode = this.audioContext.createGain()

      source.buffer = audioBuffer
      source.connect(gainNode)
      gainNode.connect(this.audioContext.destination)

      // 设置音量
      const finalVolume = volume !== null ? volume : this.config.soundVolume
      gainNode.gain.value = Math.max(0, Math.min(1, finalVolume))

      // 添加错误处理
      source.addEventListener('ended', () => {
        console.log(`Sound playback finished: ${soundName}`)
      })

      source.addEventListener('error', error => {
        console.error('Audio playback error:', error)
        this.recordFallbackEvent('audio', {
          reason: 'playback_error',
          error: error.message,
          soundName
        })
      })

      source.start(0)
      console.log(`Playing sound: ${soundName}`)
      return true
    } catch (error) {
      console.error('Play sound failed:', error)
      this.recordFallbackEvent('audio', {
        reason: 'playback_failed',
        error: error.message,
        soundName
      })

      // 重试机制
      if (retryCount < 2) {
        console.log(`Retry play sound (${retryCount + 1}/2): ${soundName}`)
        await new Promise(resolve => setTimeout(resolve, 500)) // 等待500ms后重试
        return this.playSound(soundName, volume, retryCount + 1)
      }

      // 重试失败，使用降级方案
      return this.playSoundFallback(soundName)
    }
  }

  /**
   * 用 Web Audio API 合成一个短促的"叮"声 (C5 → E5 双音，~200ms)
   * @returns {AudioBuffer|null}
   */
  _createSynthNotificationBuffer() {
    if (!this.audioContext) return null
    try {
      const sr = this.audioContext.sampleRate
      const dur = 0.22
      const len = Math.ceil(sr * dur)
      const buf = this.audioContext.createBuffer(1, len, sr)
      const ch = buf.getChannelData(0)
      const f1 = 523.25, f2 = 659.25
      for (let i = 0; i < len; i++) {
        const t = i / sr
        const env = Math.exp(-t * 12)
        ch[i] = env * 0.35 * (Math.sin(2 * Math.PI * f1 * t) + 0.6 * Math.sin(2 * Math.PI * f2 * t))
      }
      return buf
    } catch (e) {
      return null
    }
  }

  playSoundFallback(soundName) {
    console.log(`Using audio fallback: ${soundName}`)

    if (this.audioContext && this._synthBuffer) {
      try {
        if (this.audioContext.state === 'suspended') this.audioContext.resume()
        const src = this.audioContext.createBufferSource()
        const gain = this.audioContext.createGain()
        src.buffer = this._synthBuffer
        src.connect(gain)
        gain.connect(this.audioContext.destination)
        gain.gain.value = Math.max(0, Math.min(1, this.config.soundVolume))
        src.start(0)
        console.log('Synth notification sound played successfully')
        return true
      } catch (e) {
        console.warn('Synth notification sound failed:', e)
      }
    }

    try {
      const audio = new Audio(
        `/sounds/${soundName === 'default' ? 'deng.mp3' : soundName + '.mp3'}`
      )
      audio.volume = Math.max(0, Math.min(1, this.config.soundVolume))
      const playPromise = audio.play()
      if (playPromise !== undefined) {
        playPromise.catch(() => this.vibrateFallback())
      }
      return true
    } catch (error) {
      return this.vibrateFallback()
    }
  }

  vibrateFallback() {
    // 振动降级方案（移动设备）
    if (this.config.mobileVibrate && 'vibrate' in navigator) {
      try {
        navigator.vibrate([200, 100, 200]) // 振动模式：200ms振动，100ms停止，200ms振动
        console.log('Using vibration alert')
        return true
      } catch (error) {
        console.warn('Vibration alert failed:', error)
      }
    }

    console.log('All audio fallbacks failed')
    return false
  }

  async sendNotification(title, message, options = {}) {
    const results = []

    // 同时执行Web通知和音频播放，确保同步
    const promises = []

    // 显示Web通知
    if (this.config.webEnabled) {
      promises.push(
        this.showNotification(title, message, options).then(notification => ({
          type: 'web',
          success: notification !== null
        }))
      )
    }

    // 播放声音
    if (this.config.soundEnabled) {
      promises.push(
        this.playSound(options.sound).then(soundSuccess => ({
          type: 'sound',
          success: soundSuccess
        }))
      )
    }

    // 等待所有通知方式完成
    if (promises.length > 0) {
      try {
        const promiseResults = await Promise.all(promises)
        results.push(...promiseResults)
      } catch (error) {
        console.warn('Notification execution error:', error)
      }
    }

    return results
  }

  /**
   * 统一的“前端通知中心入口”
   * - 由各业务模块（如 multi_task.js）派发事件
   * - 根据设备环境与配置做路由/降级
   */
  async dispatchEvent(event) {
    try {
      const evt = event && typeof event === 'object' ? event : {}
      const type = String(evt.type || evt.kind || '').trim()

      if (type === 'new_tasks' || type === 'newTasks') {
        return await this.notifyNewTasks(evt)
      }

      // 默认回退：若提供 title/message，则复用原 sendNotification 行为
      if (typeof evt.title === 'string' && typeof evt.message === 'string') {
        return await this.sendNotification(evt.title, evt.message, evt.options || {})
      }

      return null
    } catch (error) {
      console.warn('dispatchEvent failed (falling back):', error)
      return null
    }
  }

  /**
   * 新任务通知（Web UI 侧：仅做桌面 Visual Hint + 声音提示；
   * 移动端 Bark 推送由后端 MCP 主进程在 server_feedback.py 里统一发送，
   * 前端不再调用 /api/notify-new-tasks 以避免双推）
   */
  async notifyNewTasks(event = {}) {
    const countRaw = event && typeof event === 'object' ? event.count : null
    const taskIdsRaw = event && typeof event === 'object' ? event.taskIds : null

    const taskIds = Array.isArray(taskIdsRaw) ? taskIdsRaw.filter(Boolean) : []
    const count =
      typeof countRaw === 'number' && Number.isFinite(countRaw)
        ? Math.max(0, Math.floor(countRaw))
        : taskIds.length

    if (!count || count <= 0) return null
    if (this.config && this.config.enabled === false) return null

    const title =
      typeof event.title === 'string' && event.title ? event.title : 'AI Intervention Agent'
    const message =
      count === 1 && taskIds.length === 1 ? `New task added: ${taskIds[0]}` : `Received ${count} new task(s)`

    // 1) 桌面端：Visual Hint（不依赖系统通知权限）
    try {
      if (typeof window.showNewTaskVisualHint === 'function') {
        window.showNewTaskVisualHint(count)
      } else {
        // 兜底：页面内通知（非系统通知）
        this.showInPageNotification(title, message, { timeout: 3000 })
      }
    } catch (e) {
      // 忽略：视觉提示失败不应影响主流程
    }

    // 2) 声音提示：仍沿用现有配置（不使用系统通知）
    try {
      await this.playSound('default')
    } catch (e) {
      // 忽略：声音播放失败不应影响主流程
    }

    // 注：移动端 Bark 推送已迁移到后端 MCP 主进程统一处理（server_feedback.py），
    // 前端不再调用 /api/notify-new-tasks，避免 Web UI + 后端同时触发导致双推。
    // 外部第三方客户端仍可按需 POST /api/notify-new-tasks 主动触发（API 兼容保留）。

    return { title, message, count, taskIds }
  }

  showFallbackNotification(title, message, options = {}) {
    // 增强的降级方案：使用多种方式确保用户能收到通知
    console.log(`Fallback notification: ${title} - ${message}`)
    const reason = options && typeof options === 'object' ? options.reason || 'unknown' : 'unknown'

    // 1. 尝试使用页面状态消息
    if (typeof showStatus === 'function') {
      showStatus(`${title}: ${message}`, 'info')
    }

    // 2. 尝试使用浏览器标题闪烁
    this.flashTitle(title)

    // 3. 尝试使用页面内弹窗（如果没有其他方式）
    if (!this.isSupported || this.permission === 'denied' || reason === 'insecure_context') {
      this.showInPageNotification(title, message, options)
    }

    // 4. 尝试使用控制台样式输出
    console.log(`%c[notification] ${title}`, 'color: #0084ff; font-weight: bold; font-size: 14px;')
    console.log(`%c${message}`, 'color: #666; font-size: 12px;')

    // 5. 记录降级事件用于统计
    this.recordFallbackEvent('notification', {
      title,
      message,
      reason
    })
  }

  flashTitle(message) {
    // 标题闪烁提醒
    const originalTitle = document.title
    let flashCount = 0
    const maxFlashes = 6

    const flashInterval = setInterval(() => {
      document.title = flashCount % 2 === 0 ? t('notify.titleFlash', { message: message }) : originalTitle
      flashCount++

      if (flashCount >= maxFlashes) {
        clearInterval(flashInterval)
        document.title = originalTitle
      }
    }, 1000)
  }

  updateConfig(newConfig) {
    this.config = { ...this.config, ...newConfig }
    this.syncPermissionState()
    this.bindAutoPermissionRequest()
    console.log('Notification config updated:', this.config)
  }

  getStatus() {
    return {
      supported: this.isSupported,
      permission: this.permission,
      serviceWorkerRegistered: Boolean(this.serviceWorkerRegistration),
      audioContext: this.audioContext ? this.audioContext.state : 'unavailable',
      config: this.config
    }
  }

  showInPageNotification(title, message, options = {}) {
    // 创建页面内通知元素
    // 使用安全的通知创建方法
    const notification = DOMSecurity.createNotification(title, message)

    // 添加样式
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: rgba(30, 30, 40, 0.95);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 12px;
      padding: 1rem;
      max-width: 300px;
      z-index: 10000;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
      backdrop-filter: blur(10px);
      color: #f5f5f7;
      font-family: inherit;
    `

    // 添加内容样式
    const titleEl = notification.querySelector('.in-page-notification-title')
    const messageEl = notification.querySelector('.in-page-notification-message')
    const closeEl = notification.querySelector('.in-page-notification-close')

    titleEl.style.cssText = 'font-weight: 600; margin-bottom: 0.5rem; font-size: 1rem;'
    messageEl.style.cssText =
      'font-size: 0.9rem; line-height: 1.4; color: rgba(245, 245, 247, 0.8);'
    closeEl.style.cssText = `
      position: absolute;
      top: 0.5rem;
      right: 0.5rem;
      background: none;
      border: none;
      color: rgba(245, 245, 247, 0.6);
      cursor: pointer;
      font-size: 1.2rem;
      padding: 0.25rem;
      border-radius: 4px;
      transition: all 0.2s ease;
    `

    // 添加到页面
    document.body.appendChild(notification)

    // 关闭按钮事件
    closeEl.addEventListener('click', () => {
      notification.style.transform = 'translateX(100%)'
      notification.style.opacity = '0'
      setTimeout(() => {
        if (notification.parentNode) {
          notification.parentNode.removeChild(notification)
        }
      }, 300)
    })

    closeEl.addEventListener('mouseenter', () => {
      closeEl.style.background = 'rgba(255, 255, 255, 0.1)'
      closeEl.style.color = '#f5f5f7'
    })

    closeEl.addEventListener('mouseleave', () => {
      closeEl.style.background = 'none'
      closeEl.style.color = 'rgba(245, 245, 247, 0.6)'
    })

    // 入场动画
    notification.style.transform = 'translateX(100%)'
    notification.style.transition = 'all 0.3s ease-out'
    setTimeout(() => {
      notification.style.transform = 'translateX(0)'
    }, 10)

    // 自动关闭
    setTimeout(() => {
      if (notification.parentNode) {
        closeEl.click()
      }
    }, options.timeout || 5000)

    return notification
  }

  recordFallbackEvent(type, data) {
    // 记录降级事件用于分析和改进
    const event = {
      type,
      data,
      timestamp: Date.now(),
      userAgent: navigator.userAgent,
      url: window.location.href
    }

    // 性能优化：存储到本地存储
    try {
      const storageKey = 'ai-intervention-fallback-events'
      const events = JSON.parse(localStorage.getItem(storageKey) || '[]')

      // 性能优化：清理过期事件
      const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
      const validEvents = events.filter(e => e.timestamp > sevenDaysAgo)

      validEvents.push(event)

      // 性能优化：只保留最近50个事件
      if (validEvents.length > 50) {
        validEvents.splice(0, validEvents.length - 50)
      }

      localStorage.setItem(storageKey, JSON.stringify(validEvents))

      // 性能优化：监控存储空间使用
      this.monitorLocalStorageUsage(storageKey)
    } catch (error) {
      console.warn('Cannot record fallback event:', error)
      // 如果存储失败，尝试清理存储空间
      this.cleanupLocalStorage()
    }

    if (this.config.debug) {
      console.log('Fallback event recorded:', event)
    }
  }

  // 性能优化：监控 localStorage 使用情况
  monitorLocalStorageUsage(key) {
    try {
      const data = localStorage.getItem(key)
      if (data) {
        const sizeInBytes = new Blob([data]).size
        const sizeInKB = (sizeInBytes / 1024).toFixed(2)

        if (sizeInBytes > 100 * 1024) {
          // 超过100KB时警告
          console.warn(`localStorage event records are large: ${sizeInKB}KB; consider pruning`)
        }

        if (this.config.debug) {
          console.log(`localStorage event records size: ${sizeInKB}KB`)
        }
      }
    } catch (error) {
      console.warn('Cannot monitor localStorage usage:', error)
    }
  }

  // 性能优化：清理 localStorage
  cleanupLocalStorage() {
    try {
      const storageKey = 'ai-intervention-fallback-events'
      const events = JSON.parse(localStorage.getItem(storageKey) || '[]')

      // 只保留最近24小时的事件
      const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000
      const recentEvents = events.filter(e => e.timestamp > oneDayAgo)

      // 进一步限制到最多20个事件
      if (recentEvents.length > 20) {
        recentEvents.splice(0, recentEvents.length - 20)
      }

      localStorage.setItem(storageKey, JSON.stringify(recentEvents))
      console.log(`localStorage pruning complete; kept ${recentEvents.length} events`)
    } catch (error) {
      console.error('localStorage pruning failed:', error)
      // 最后手段：清空事件记录
      try {
        localStorage.removeItem('ai-intervention-fallback-events')
        console.log('localStorage event records cleared')
      } catch (clearError) {
        console.error('Cannot clear localStorage:', clearError)
      }
    }
  }
}

// 创建全局通知管理器实例
const notificationManager = new NotificationManager()
