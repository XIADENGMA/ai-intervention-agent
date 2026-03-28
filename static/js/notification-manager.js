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
    // 事件去重：避免短时间内重复触发（尤其是移动端 Bark）
    this._eventDeduper = new Map()
    this._dedupeMaxKeys = 200
    this._dedupeTtlMs = 5 * 60 * 1000
    this._dedupeNextPruneAtMs = 0
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
      console.log('初始化通知管理器...')
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
          '[通知环境] hostname:',
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
        console.warn('浏览器不支持 Web Notification API')
      } else {
        await this.registerServiceWorker()
        this.bindAutoPermissionRequest()
      }

      await this.initAudio()
      console.log('通知管理器初始化完成')
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
        console.warn('当前不是安全上下文，无法注册通知 service worker')
      }
      return null
    }

    if (this.serviceWorkerRegistration) {
      return this.serviceWorkerRegistration
    }

    try {
      await navigator.serviceWorker.register('/notification-service-worker.js')
      this.serviceWorkerRegistration = await navigator.serviceWorker.ready
      console.log('通知 service worker 已注册')
      return this.serviceWorkerRegistration
    } catch (error) {
      console.warn('通知 service worker 注册失败:', error)
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
      console.warn('浏览器不支持 Web Notification API')
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
      console.warn('当前不是安全上下文，浏览器不会弹出通知权限请求')
      return false
    }

    if (
      requireUserGesture &&
      navigator.userActivation &&
      navigator.userActivation.isActive === false
    ) {
      console.warn('通知权限请求需要用户操作，已延迟到下一次交互')
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

        console.log(`通知权限状态: ${this.permission}`)
        window.dispatchEvent(
          new CustomEvent('notification-permission-changed', {
            detail: { permission: this.permission }
          })
        )
        return this.permission === 'granted'
      })()

      return await this.permissionRequestPromise
    } catch (error) {
      console.error('请求通知权限失败:', error)
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
        console.warn('浏览器不支持Web Audio API')
        return
      }

      // 创建音频上下文（需要用户交互后才能启用）
      this.audioContext = new AudioContextClass()

      // 预加载默认音频文件
      await this.loadAudioFile('default', '/sounds/deng[噔].mp3')

      console.log('音频系统初始化完成')
    } catch (error) {
      console.warn('音频系统初始化失败:', error)
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
      console.log(`音频文件加载成功: ${name}`)
      return true
    } catch (error) {
      console.warn(`音频文件加载失败 ${name}:`, error)
      return false
    }
  }

  async showNotification(title, message, options = {}) {
    if (!this.config.enabled || !this.config.webEnabled) {
      console.log('Web 通知已禁用')
      return null
    }

    if (!this.isSupported) {
      console.warn('浏览器不支持通知，使用降级方案')
      this.showFallbackNotification(title, message, { ...options, reason: 'unsupported' })
      return null
    }

    if (typeof window.isSecureContext === 'boolean' && window.isSecureContext === false) {
      const origin =
        window.location && typeof window.location.origin === 'string' ? window.location.origin : ''
      const host =
        window.location && typeof window.location.host === 'string' ? window.location.host : ''
      const where = origin || host || '当前页面'
      this.showFallbackNotification(
        '浏览器原生通知不可用',
        `当前访问地址（${where}）不是安全上下文。请使用 HTTPS 或 localhost/127.0.0.1 访问后重试。`,
        { ...options, reason: 'insecure_context' }
      )
      return null
    }

    this.syncPermissionState()
    if (this.permission !== 'granted') {
      console.warn('当前没有系统通知权限')
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

      console.log('系统通知已显示:', title)
      return notification
    } catch (error) {
      console.error('显示通知失败:', error)
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
        console.warn('通过 service worker 显示通知失败，回退到页面 Notification:', error)
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
      console.error('页面 Notification 创建失败:', error)
      return null
    }
  }

  async playSound(soundName = 'default', volume = null, retryCount = 0) {
    if (!this.config.enabled || !this.config.soundEnabled || this.config.soundMute) {
      console.log('声音通知已禁用')
      return false
    }

    if (!this.audioContext) {
      console.warn('音频上下文未初始化，尝试降级方案')
      this.recordFallbackEvent('audio', { reason: 'no_audio_context', soundName })
      return this.playSoundFallback(soundName)
    }

    // 恢复音频上下文（如果被暂停）
    if (this.audioContext.state === 'suspended') {
      try {
        await this.audioContext.resume()
        console.log('音频上下文已恢复')
      } catch (error) {
        console.warn('恢复音频上下文失败:', error)
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
      console.warn(`音频文件未找到: ${soundName}`)
      // 尝试加载默认音频文件
      if (soundName !== 'default') {
        console.log('尝试使用默认音频文件')
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
        console.log(`声音播放完成: ${soundName}`)
      })

      source.addEventListener('error', error => {
        console.error('音频播放错误:', error)
        this.recordFallbackEvent('audio', {
          reason: 'playback_error',
          error: error.message,
          soundName
        })
      })

      source.start(0)
      console.log(`播放声音: ${soundName}`)
      return true
    } catch (error) {
      console.error('播放声音失败:', error)
      this.recordFallbackEvent('audio', {
        reason: 'playback_failed',
        error: error.message,
        soundName
      })

      // 重试机制
      if (retryCount < 2) {
        console.log(`重试播放声音 (${retryCount + 1}/2): ${soundName}`)
        await new Promise(resolve => setTimeout(resolve, 500)) // 等待500ms后重试
        return this.playSound(soundName, volume, retryCount + 1)
      }

      // 重试失败，使用降级方案
      return this.playSoundFallback(soundName)
    }
  }

  playSoundFallback(soundName) {
    // 音频播放降级方案
    console.log(`使用音频降级方案: ${soundName}`)

    try {
      // 方案1: 尝试使用HTML5 Audio元素
      const audio = new Audio(
        `/sounds/${soundName === 'default' ? 'deng[噔].mp3' : soundName + '.mp3'}`
      )
      audio.volume = this.config.soundVolume

      const playPromise = audio.play()
      if (playPromise !== undefined) {
        playPromise
          .then(() => {
            console.log('HTML5 Audio播放成功')
          })
          .catch(error => {
            console.warn('HTML5 Audio播放失败:', error)
            // 方案2: 使用振动API（移动设备）
            this.vibrateFallback()
          })
      }
      return true
    } catch (error) {
      console.warn('HTML5 Audio降级失败:', error)
      // 方案2: 使用振动API（移动设备）
      return this.vibrateFallback()
    }
  }

  vibrateFallback() {
    // 振动降级方案（移动设备）
    if (this.config.mobileVibrate && 'vibrate' in navigator) {
      try {
        navigator.vibrate([200, 100, 200]) // 振动模式：200ms振动，100ms停止，200ms振动
        console.log('使用振动提醒')
        return true
      } catch (error) {
        console.warn('振动提醒失败:', error)
      }
    }

    console.log('所有音频降级方案都失败了')
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
        console.warn('通知执行过程中出现错误:', error)
      }
    }

    return results
  }

  _pruneDeduper(now) {
    try {
      const cutoff = now - this._dedupeTtlMs
      for (const [k, ts] of this._eventDeduper.entries()) {
        if (typeof ts !== 'number' || ts < cutoff) {
          this._eventDeduper.delete(k)
        }
      }
      while (this._eventDeduper.size > this._dedupeMaxKeys) {
        const firstKey = this._eventDeduper.keys().next().value
        if (firstKey === undefined) break
        this._eventDeduper.delete(firstKey)
      }
    } catch (e) {
      // noop
    }
    this._dedupeNextPruneAtMs = now + 60000
  }

  _shouldDedupe(key, windowMs) {
    try {
      const k = String(key || '')
      if (!k) return false
      const now = Date.now()
      if (now >= this._dedupeNextPruneAtMs || this._eventDeduper.size > this._dedupeMaxKeys) {
        this._pruneDeduper(now)
      }
      const last = this._eventDeduper.get(k)
      if (typeof last === 'number' && now - last < windowMs) {
        return true
      }
      this._eventDeduper.set(k, now)
      return false
    } catch (e) {
      return false
    }
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
      console.warn('dispatchEvent 处理失败（已降级）:', error)
      return null
    }
  }

  /**
   * 新任务通知（阶段 B：桌面端走 Visual Hint；移动端按配置优先 Bark）
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
      count === 1 && taskIds.length === 1 ? `新任务已添加: ${taskIds[0]}` : `收到 ${count} 个新任务`

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

    // 3) 移动端：按配置优先 Bark（通过后端触发，避免前端直连 Bark）
    try {
      if (
        this.config &&
        this.config.enabled !== false &&
        this.config.mobileOptimized &&
        isMobileDevice() &&
        this.config.barkEnabled
      ) {
        const dedupeKey = String(event.dedupeKey || 'bark:new_tasks')
        if (!this._shouldDedupe(dedupeKey, 3000)) {
          await this._triggerBarkNewTasks({ count, taskIds })
        }
      }
    } catch (e) {
      // 忽略：Bark 触发失败不应影响主流程
    }

    return { title, message, count, taskIds }
  }

  async _triggerBarkNewTasks(payload) {
    try {
      const body = {
        count: payload && payload.count ? payload.count : 0,
        taskIds: payload && Array.isArray(payload.taskIds) ? payload.taskIds : []
      }

      const resp = await fetch('/api/notify-new-tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        console.warn('触发 Bark 新任务通知失败（HTTP）:', resp.status, data && data.message)
        return false
      }

      // status: success / skipped / error（不抛异常，避免影响主流程）
      if (data && data.status === 'success') {
        return true
      }
      return false
    } catch (error) {
      console.warn('触发 Bark 新任务通知失败（已降级）:', error)
      return false
    }
  }

  showFallbackNotification(title, message, options = {}) {
    // 增强的降级方案：使用多种方式确保用户能收到通知
    console.log(`降级通知: ${title} - ${message}`)
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
    console.log(`%c[通知] ${title}`, 'color: #0084ff; font-weight: bold; font-size: 14px;')
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
    console.log('通知配置已更新:', this.config)
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
      console.warn('无法记录降级事件:', error)
      // 如果存储失败，尝试清理存储空间
      this.cleanupLocalStorage()
    }

    if (this.config.debug) {
      console.log('降级事件记录:', event)
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
          console.warn(`localStorage事件记录过大: ${sizeInKB}KB，建议清理`)
        }

        if (this.config.debug) {
          console.log(`localStorage事件记录大小: ${sizeInKB}KB`)
        }
      }
    } catch (error) {
      console.warn('无法监控localStorage使用情况:', error)
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
      console.log(`localStorage清理完成，保留 ${recentEvents.length} 个事件`)
    } catch (error) {
      console.error('localStorage清理失败:', error)
      // 最后手段：清空事件记录
      try {
        localStorage.removeItem('ai-intervention-fallback-events')
        console.log('已清空localStorage事件记录')
      } catch (clearError) {
        console.error('无法清空localStorage:', clearError)
      }
    }
  }
}

// 创建全局通知管理器实例
const notificationManager = new NotificationManager()
