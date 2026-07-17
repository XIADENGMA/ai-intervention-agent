/**
 * 通知管理系统 - 从 app.js 拆分
 *
 * 提供 Web Notification API、音频播放、Service Worker 通知、
 * Bark 推送、事件去重、降级方案等完整通知功能。
 *
 * 依赖: dom-security.js (DOMSecurity), i18n.js (t())
 * 暴露: window.notificationManager (NotificationManager 实例)
 *
 * ──────────────────────────────────────────────────────────────────
 * R216 / Cycle 11 · F-cycle10-1 · console noise demotion
 * ──────────────────────────────────────────────────────────────────
 * 本模块原有 27 个 ``console.log`` 调用 (init / config-change /
 * 每次播放声音 / 每次降级通知 等)，对于通知频繁的会话, 浏览器
 * Console 会被刷屏, 真正的 ``console.warn`` / ``console.error``
 * (29 处) 被淹没在 INFO-级日志里, 用户难以发现 actionable 问题。
 *
 * R216 把所有 27 个 ``console.log`` 统一 demote 为 ``console.debug``
 * (Chrome DevTools 默认在 Console 顶部 filter 里关掉 Verbose / Debug
 * 级别——非开发者打开 DevTools 时不会看到这些; 开发者主动开启
 * Verbose 即可看到全部历史) ——零 helper / 零运行时开销, 纯方法
 * 名 rename, ``console.debug.apply(console, [...args])`` 与
 * ``console.log.apply(console, [...args])`` 在所有现代浏览器
 * (Chrome / Firefox / Safari / Edge) 行为完全一致, 只是 level
 * 不同。``console.warn`` / ``console.error`` 保留, 它们是真正
 * 应当被看见的信号。
 *
 * 守护: ``tests/test_notification_manager_console_noise_invariant_r216.py``
 * 字面 substring 检查源码不再出现带括号的 console.log 调用, 防止
 * 未来 contributor 不知道这条约定又加回 INFO 级日志。invariant 也
 * 守 console.debug 至少 ≥ 20 (证明真的发生了 demotion, 不是把 log
 * 全删光)。
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

const DEFAULT_NOTIFICATION_SOUND_URL = '/sounds/deng.wav'
const AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS = {
  once: true,
  passive: true
}

// ============================================================================
// feat-custom-sound (mining-cycle-1 §3.4) — 自定义通知音效
// ============================================================================
//
// 存储模型：单一 localStorage key 持久化用户上传的 1 个自定义音效。
// 选择 "single slot" 而不是 multi-slot 的理由：
//   - 5MB localStorage 配额；单个音效 base64 后 ~1.3x 实际字节，给单个
//     ~700KB 的 ogg/mp3 留充足余量
//   - 多 slot 引入命名 / 管理 UI 复杂度，竞品 mcp-feedback-enhanced 也
//     只支持单个 custom slot
//
// MIME 白名单：浏览器 ``decodeAudioData`` 真正能解的格式
//   - audio/mpeg (mp3)
//   - audio/wav / audio/wave / audio/x-wav (wav)
//   - audio/ogg (ogg vorbis / opus)
//   - audio/webm (webm)
//   - audio/aac (aac)
//   - audio/mp4 (m4a)
//   - audio/flac
// 其它 MIME 一律拒绝，避免用户上传 .midi / .au / 视频被假冒为音频。
const CUSTOM_SOUND_LS_KEY = 'aiia.notif.customSound.v1'
const CUSTOM_SOUND_MAX_BYTES = 700 * 1024 // 700KB，base64 ~ 933KB，留 4MB+ 余量
// cr33 §8 #1 fix：上限 30s 时长。理论上 700KB 已经 cap 了文件大小，但
// 低比特率（如 32kbps mono ogg）可以塞进 30 分钟音频；decode 后 PCM
// 1.4MB/分钟 (44.1kHz mono) → 30 分钟 = ~40MB；stereo 双倍 → 80MB；
// 完全是真实 foot-gun。改在 ``saveCustomSoundFromFile`` 写 localStorage
// **之前**做 ``decodeAudioData → duration`` 检查，超过阈值直接拒绝。
const CUSTOM_SOUND_MAX_DURATION_S = 30
const CUSTOM_SOUND_ALLOWED_MIMES = [
  'audio/mpeg',
  'audio/wav',
  'audio/wave',
  'audio/x-wav',
  'audio/ogg',
  'audio/webm',
  'audio/aac',
  'audio/mp4',
  'audio/flac'
]

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
    this._titleFlashInterval = null
    this._titleFlashOriginalTitle = null
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
      console.debug('Initializing notification manager…')
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
        console.debug(
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
        this.bindAutoPermissionRequest()
      }

      // R21.2：service worker 注册移出 ``isSupported`` 守护
      // ----------------------------------------------------------------
      // 历史上 ``registerServiceWorker`` 只在 ``isSupported``（``Notification``
      // API 存在）路径上跑，导致 iOS 16- / 部分 Android 自带浏览器（不支持
      // ``Notification`` 但支持 ``serviceWorker``）拿不到 SW，自然也享受
      // 不到静态资源 cache-first 加速。现在把注册提前到 init 主流程，
      // ``registerServiceWorker`` 内部仍然有 ``supportsServiceWorkerNotifications``
      // 守护（名字 misleading，但实现实际只检查 ``serviceWorker`` in
      // navigator + secure context，与 Notification 无关），所以无 SW
      // 支持的环境会优雅返回 null，不破坏现有契约。
      await this.registerServiceWorker()

      await this.initAudio()
      console.debug('Notification manager initialized')
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
      console.debug('Notification service worker registered')
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

      this.removeAutoPermissionRequestListeners()
      this.requestPermission({ requireUserGesture: false }).finally(() => {
        if (!this.config.autoRequestPermission || this.syncPermissionState() !== 'default') {
          this.removeAutoPermissionRequestListeners()
          return
        }
        this.bindAutoPermissionRequest()
      })
    }
    this.addAutoPermissionRequestListeners()

    this.autoPermissionListenersBound = true
  }

  addAutoPermissionRequestListeners() {
    const handler = this.boundPermissionRequestHandler
    document.addEventListener('click', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)
    document.addEventListener('keydown', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)
    document.addEventListener('touchstart', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)
  }

  removeAutoPermissionRequestListeners() {
    if (!this.autoPermissionListenersBound || !this.boundPermissionRequestHandler) {
      return
    }

    this.removeBoundAutoPermissionRequestListeners()

    this.autoPermissionListenersBound = false
    this.boundPermissionRequestHandler = null
  }

  removeBoundAutoPermissionRequestListeners() {
    const handler = this.boundPermissionRequestHandler
    document.removeEventListener('click', handler)
    document.removeEventListener('keydown', handler)
    document.removeEventListener('touchstart', handler)
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

        console.debug(`Notification permission state: ${this.permission}`)
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

      await this.loadAudioFile('default', DEFAULT_NOTIFICATION_SOUND_URL)
      if (!this.audioBuffers.has('default')) {
        this._synthBuffer = this._createSynthNotificationBuffer()
      }

      // feat-custom-sound (§3.4): 如果用户之前上传过自定义音效，
      // 同步 decode 它到 audioBuffers['custom']。这样 ``playSound()``
      // (无参) 会自动 dispatch 到 'custom'（如果 hasCustomSound() 为 true）。
      // 失败时静默：用户上传时如果文件就是坏的，错误已经在上传时报过；
      // init 阶段不应该 spam 用户控制台。
      await this.loadCustomSoundFromStorage()

      console.debug('Audio system initialized')
    } catch (error) {
      console.warn('Audio system initialization failed:', error)
      // 降级：禁用音频功能
      this.config.soundEnabled = false
    }
  }

  // ==========================================================================
  // feat-custom-sound (§3.4): 自定义音效上传 / 加载 / 清理
  // ==========================================================================

  /**
   * 检查 localStorage 是否有用户上传的自定义音效（不解码，只看 key 存在）。
   * 用于 playSound() 路由决策 + Settings UI 显示状态。
   * @returns {boolean}
   */
  hasCustomSound() {
    try {
      const raw = localStorage.getItem(CUSTOM_SOUND_LS_KEY)
      return Boolean(raw)
    } catch (e) {
      return false
    }
  }

  /**
   * 读取用户当前上传的自定义音效元数据（不返回 dataUri 主体）。
   * @returns {{name: string, mime: string, size: number}|null}
   */
  getCustomSoundMeta() {
    try {
      const raw = localStorage.getItem(CUSTOM_SOUND_LS_KEY)
      if (!raw) return null
      const obj = JSON.parse(raw)
      if (!obj || typeof obj !== 'object') return null
      return {
        name: String(obj.name || 'custom'),
        mime: String(obj.mime || ''),
        size: Number(obj.size || 0)
      }
    } catch (e) {
      return null
    }
  }

  /**
   * 从 localStorage 取自定义音效 dataUri，fetch + decode 到 audioBuffers['custom']。
   * @returns {Promise<boolean>} true=加载成功
   */
  async loadCustomSoundFromStorage() {
    if (!this.audioContext) return false
    let raw
    try {
      raw = localStorage.getItem(CUSTOM_SOUND_LS_KEY)
    } catch (e) {
      // localStorage 可能在 Safari 隐私模式 / quota exceeded 时抛
      return false
    }
    if (!raw) {
      // 没有自定义音效；确保 audioBuffers 里也没有 stale 'custom' buffer
      this.audioBuffers.delete('custom')
      return false
    }
    let obj
    try {
      obj = JSON.parse(raw)
    } catch (e) {
      console.warn('Custom sound localStorage entry not valid JSON; clearing')
      this.clearCustomSound()
      return false
    }
    if (!obj || typeof obj.dataUri !== 'string') {
      this.clearCustomSound()
      return false
    }
    try {
      const response = await fetch(obj.dataUri)
      const arrayBuffer = await response.arrayBuffer()
      const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer)
      this.audioBuffers.set('custom', audioBuffer)
      console.debug(`Custom sound loaded: ${obj.name || '(unnamed)'}`)
      return true
    } catch (error) {
      // decode 失败：把 stale entry 也清掉，避免每次启动都 retry 同一个坏文件。
      console.warn('Custom sound decode failed:', error)
      this.audioBuffers.delete('custom')
      return false
    }
  }

  /**
   * 用户上传自定义音效。
   *
   * 副作用：
   *   - 校验 MIME / size；失败时返回 {success: false, error}
   *   - 成功时写 localStorage + 触发 loadCustomSoundFromStorage 让新音效立即可用
   *
   * @param {File} file 来自 ``<input type="file" accept="audio/*">``
   * @returns {Promise<{success: boolean, error?: string, meta?: object}>}
   *   error code ∈ {'no_file', 'invalid_mime', 'too_large', 'read_failed',
   *                  'storage_failed', 'decode_failed', 'duration_too_long'}
   */
  async saveCustomSoundFromFile(file) {
    if (!file || typeof file !== 'object') {
      return { success: false, error: 'no_file' }
    }
    const mime = String(file.type || '').toLowerCase()
    if (!CUSTOM_SOUND_ALLOWED_MIMES.includes(mime)) {
      return { success: false, error: 'invalid_mime', mime }
    }
    if (typeof file.size !== 'number' || file.size > CUSTOM_SOUND_MAX_BYTES) {
      return {
        success: false,
        error: 'too_large',
        size: file.size,
        maxBytes: CUSTOM_SOUND_MAX_BYTES
      }
    }
    // 读 dataURI（include base64 prefix），用 FileReader 而不是 arrayBuffer
    // 因为 localStorage 只能存字符串，base64 是最方便的 round-trip 编码。
    const dataUri = await new Promise((resolve, reject) => {
      try {
        const fr = new FileReader()
        fr.onload = () => resolve(String(fr.result || ''))
        fr.onerror = () => reject(fr.error || new Error('FileReader error'))
        fr.readAsDataURL(file)
      } catch (e) {
        reject(e)
      }
    }).catch(() => null)
    if (!dataUri || !dataUri.startsWith('data:')) {
      return { success: false, error: 'read_failed' }
    }
    // cr33 §8 #1 fix：在 setItem 之前先 decode + 检查 duration。
    // why pre-storage：失败时 localStorage 完全没被污染，调用方不用做
    // commit-then-rollback；且失败的 file 不会触发 ``decoded ===
    // audioBuffers['custom']``，保留了已有 custom 音效。
    // why duration check：700KB 大小 cap 仍然能塞 30 分钟 lo-bitrate 音频；
    // 解码后 PCM 几十 MB，是真实内存 foot-gun。
    if (this.audioContext) {
      let preflightBuffer = null
      try {
        const r = await fetch(dataUri)
        const ab = await r.arrayBuffer()
        preflightBuffer = await this.audioContext.decodeAudioData(ab)
      } catch (e) {
        return { success: false, error: 'decode_failed', detail: String(e && e.message ? e.message : e) }
      }
      if (preflightBuffer.duration > CUSTOM_SOUND_MAX_DURATION_S) {
        return {
          success: false,
          error: 'duration_too_long',
          duration: preflightBuffer.duration,
          maxDuration: CUSTOM_SOUND_MAX_DURATION_S
        }
      }
    }
    const meta = {
      name: String(file.name || 'custom'),
      mime,
      size: Number(file.size || 0),
      uploadedAt: Date.now()
    }
    try {
      localStorage.setItem(
        CUSTOM_SOUND_LS_KEY,
        JSON.stringify({ ...meta, dataUri })
      )
    } catch (e) {
      return { success: false, error: 'storage_failed', detail: e.message }
    }
    const decoded = await this.loadCustomSoundFromStorage()
    if (!decoded) {
      // 兜底：理论上不会到这里（preflight 已通过）；如果 audioContext
      // 在两次 decode 之间出问题，清掉 localStorage 让用户知道。
      this.clearCustomSound()
      return { success: false, error: 'decode_failed', meta }
    }
    return { success: true, meta }
  }

  /**
   * 清除自定义音效（localStorage + audioBuffers）。
   * 设置 reset / Clear 按钮使用。
   */
  clearCustomSound() {
    try {
      localStorage.removeItem(CUSTOM_SOUND_LS_KEY)
    } catch (e) {
      // 忽略：清不掉就清不掉
    }
    this.audioBuffers.delete('custom')
  }

  async loadAudioFile(name, url) {
    if (!this.audioContext) return false

    try {
      const response = await fetch(url)
      const arrayBuffer = await response.arrayBuffer()
      const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer)
      this.audioBuffers.set(name, audioBuffer)
      console.debug(`Audio file loaded: ${name}`)
      return true
    } catch (error) {
      console.warn(`Audio file load failed ${name}:`, error)
      return false
    }
  }

  async showNotification(title, message, options = {}) {
    if (!this.config.enabled || !this.config.webEnabled) {
      console.debug('Web notifications disabled')
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
        badge, // BUG4：保留解构以便外部传入的 badge 仍可被 spread 覆盖；默认不写到 notificationOptions（见下）
        tag,
        requireInteraction,
        silent,
        ...restOptions
      } = options

      // BUG4 修复：去除默认 badge 字段。
      //
      // 历史代码默认 ``badge: badge || this.config.icon`` —— Android Chrome
      // 会在通知中心和状态栏显示一个等价大小的小图标（"角标"），用户表示
      // 不喜欢这种视觉噪声。桌面浏览器多数会忽略该字段，所以删除它在桌面
      // 端无视觉变化；移动端则会回到"无 badge 的纯文字通知"。
      //
      // 仍允许调用方主动传 ``options.badge`` 覆盖（罕见用法），通过 ``...
      // restOptions`` 不会带回 badge —— 因为它已经被解构出去 —— 所以只在
      // 调用方显式传 badge 时才会写入 notificationOptions。
      const notificationOptions = {
        body: message,
        icon: icon || this.config.icon,
        tag: tag || 'ai-intervention-agent',
        requireInteraction: requireInteraction || false,
        silent: silent || false,
        data: {
          url: url || window.location.href,
          ...extraData
        },
        ...restOptions
      }
      if (typeof badge === 'string' && badge) {
        // 调用方显式传入非空字符串时才尊重；空字符串 / undefined / null 都视为"不要 badge"。
        notificationOptions.badge = badge
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

      console.debug('System notification shown:', title)
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

  async playSound(soundName = null, volume = null, retryCount = 0) {
    if (!this.config.enabled || !this.config.soundEnabled || this.config.soundMute) {
      console.debug('Sound notifications disabled')
      return false
    }

    // feat-custom-sound (§3.4): 默认 dispatch —— 如果用户上传了 custom
    // 音效，没有显式指定 soundName 时优先 'custom'；否则 fallback 'default'。
    // 既保留显式 ``playSound('default')`` 的语义（默认音效测试按钮用），
    // 又让常规通知路径自动 honor 用户偏好。
    if (soundName === null || soundName === undefined) {
      soundName = this.audioBuffers.has('custom') ? 'custom' : 'default'
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
        console.debug('Audio context resumed')
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
        console.debug('Trying default audio file')
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
        console.debug(`Sound playback finished: ${soundName}`)
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
      console.debug(`Playing sound: ${soundName}`)
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
        console.debug(`Retry play sound (${retryCount + 1}/2): ${soundName}`)
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
    console.debug(`Using audio fallback: ${soundName}`)

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
        console.debug('Synth notification sound played successfully')
        return true
      } catch (e) {
        console.warn('Synth notification sound failed:', e)
      }
    }

    try {
      const audio = new Audio(
        soundName === 'default' ? DEFAULT_NOTIFICATION_SOUND_URL : `/sounds/${soundName}.mp3`
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
        console.debug('Using vibration alert')
        return true
      } catch (error) {
        console.warn('Vibration alert failed:', error)
      }
    }

    console.debug('All audio fallbacks failed')
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

    let taskIds = null
    let taskIdCount = 0
    if (Array.isArray(taskIdsRaw)) {
      for (let i = 0; i < taskIdsRaw.length; i += 1) {
        if (!(i in taskIdsRaw)) continue
        const taskId = taskIdsRaw[i]
        if (taskId) {
          if (taskIds === null) taskIds = []
          taskIds.push(taskId)
          taskIdCount += 1
        }
      }
    }
    const count =
      typeof countRaw === 'number' && Number.isFinite(countRaw)
        ? Math.max(0, Math.floor(countRaw))
        : taskIdCount

    if (!count || count <= 0) return null
    if (this.config && this.config.enabled === false) return null
    if (taskIds === null) taskIds = []

    const title =
      typeof event.title === 'string' && event.title ? event.title : 'AI Intervention Agent'
    const message =
      count === 1 && taskIdCount === 1 ? `New task added: ${taskIds[0]}` : `Received ${count} new task(s)`

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
    console.debug(`Fallback notification: ${title} - ${message}`)
    const reason = options && typeof options === 'object' ? options.reason || 'unknown' : 'unknown'

    // R214 / Cycle 10 · F-notif-fallback-1: 降级通知改用 type='warning'
    // 而非 'info'，让 content-page 上的 toast 真的可见 (修前 'info' 类
    // 型在 content page 上被 silently dropped, 见 app.js showStatus
    // R214 注释)。同时根据 reason 追加 i18n 化的 hint 让用户知道为何
    // 降级——单纯的 "标题: 消息" 不够 actionable, 用户不会去检查通知权限。
    // reason -> i18n hint 映射 (用 callback 而非字符串 lookup, 让
    // scripts/check_i18n_orphan_keys.py 的 literal-call 扫描器能识别
    // 每个 i18n key 都被引用, 否则会被报为 orphan)。
    // 其他/未知 reason (system_notification_failed / show_notification_exception
    // 等底层异常) 不追加 hint, 用户不能立即修复, 不打扰。
    const reasonHintMap = {
      permission_denied: () => t('status.notifFallbackPermDenied'),
      permission_default: () => t('status.notifFallbackPermDefault'),
      permission_disabled: () => t('status.notifFallbackPermDisabled'),
      unsupported: () => t('status.notifFallbackUnsupported'),
      insecure_context: () => t('status.notifFallbackInsecure')
    }
    let toastMessage = `${title}: ${message}`
    const hintFn = reasonHintMap[reason]
    if (typeof hintFn === 'function') {
      const hint = hintFn()
      // i18n 未加载时 t() 会原样返回 'status.notifFallback*' key,
      // 此时不要把 ugly key 追加到 toast (检查包含 dot 的 key prefix)
      if (hint && !hint.startsWith('status.notifFallback')) {
        toastMessage = `${title}: ${message} — ${hint}`
      }
    }

    // 1. 尝试使用页面状态消息 (warning level, R214 后 content page 可见)
    if (typeof showStatus === 'function') {
      showStatus(toastMessage, 'warning')
    }

    // 2. 尝试使用浏览器标题闪烁
    this.flashTitle(title)

    // 3. 尝试使用页面内弹窗（如果没有其他方式）
    if (!this.isSupported || this.permission === 'denied' || reason === 'insecure_context') {
      this.showInPageNotification(title, message, options)
    }

    // 4. 尝试使用控制台样式输出
    console.debug(`%c[notification] ${title}`, 'color: #0084ff; font-weight: bold; font-size: 14px;')
    console.debug(`%c${message}`, 'color: #666; font-size: 12px;')

    // 5. 记录降级事件用于统计
    this.recordFallbackEvent('notification', {
      title,
      message,
      reason
    })
  }

  clearTitleFlash() {
    if (this._titleFlashInterval !== null) {
      clearInterval(this._titleFlashInterval)
      this._titleFlashInterval = null
    }

    if (this._titleFlashOriginalTitle !== null) {
      document.title = this._titleFlashOriginalTitle
      this._titleFlashOriginalTitle = null
    }
  }

  flashTitle(message) {
    // 标题闪烁提醒；同一时间只保留一个 interval，避免连续降级通知互相恢复旧标题。
    this.clearTitleFlash()
    this._titleFlashOriginalTitle = document.title
    let flashCount = 0
    const maxFlashes = 6

    this._titleFlashInterval = setInterval(() => {
      const originalTitle =
        this._titleFlashOriginalTitle !== null ? this._titleFlashOriginalTitle : document.title
      document.title = flashCount % 2 === 0 ? t('notify.titleFlash', { message: message }) : originalTitle
      flashCount++

      if (flashCount >= maxFlashes) {
        this.clearTitleFlash()
      }
    }, 1000)
  }

  updateConfig(newConfig) {
    this.config = { ...this.config, ...newConfig }
    this.syncPermissionState()
    this.bindAutoPermissionRequest()
    console.debug('Notification config updated:', this.config)
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

  _getInPageNotificationTimeoutMs(options = {}) {
    const rawTimeout = Object.prototype.hasOwnProperty.call(options, 'timeout')
      ? options.timeout
      : this.config.timeout
    const timeout = Number(rawTimeout)
    if (!Number.isFinite(timeout)) {
      return 5000
    }
    return Math.max(0, Math.floor(timeout))
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

    let closeStarted = false
    let autoCloseTimerId = null

    const closeNotification = () => {
      if (closeStarted) return
      closeStarted = true
      if (autoCloseTimerId !== null) {
        clearTimeout(autoCloseTimerId)
        autoCloseTimerId = null
      }
      notification.style.transform = 'translateX(100%)'
      notification.style.opacity = '0'
      setTimeout(() => {
        if (notification.parentNode) {
          notification.parentNode.removeChild(notification)
        }
      }, 300)
    }

    // 关闭按钮事件
    closeEl.addEventListener('click', closeNotification)

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
    const timeoutMs = this._getInPageNotificationTimeoutMs(options)
    if (timeoutMs > 0) {
      autoCloseTimerId = setTimeout(closeNotification, timeoutMs)
    }

    return notification
  }

  _collectRecentFallbackEvents(events, cutoffTimestamp, maxEvents) {
    if (!Array.isArray(events)) {
      throw new TypeError('fallback events payload is not an array')
    }

    const kept = []
    for (let i = events.length - 1; i >= 0; i -= 1) {
      if (!(i in events)) continue
      const event = events[i]
      if (event.timestamp > cutoffTimestamp && kept.length < maxEvents) {
        kept.push(event)
      }
    }
    kept.reverse()
    return kept
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
      const validEvents = this._collectRecentFallbackEvents(events, sevenDaysAgo, 49)

      validEvents.push(event)

      localStorage.setItem(storageKey, JSON.stringify(validEvents))

      // 性能优化：监控存储空间使用
      this.monitorLocalStorageUsage(storageKey)
    } catch (error) {
      console.warn('Cannot record fallback event:', error)
      // 如果存储失败，尝试清理存储空间
      this.cleanupLocalStorage()
    }

    if (this.config.debug) {
      console.debug('Fallback event recorded:', event)
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
          console.debug(`localStorage event records size: ${sizeInKB}KB`)
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
      const recentEvents = this._collectRecentFallbackEvents(events, oneDayAgo, 20)

      localStorage.setItem(storageKey, JSON.stringify(recentEvents))
      console.debug(`localStorage pruning complete; kept ${recentEvents.length} events`)
    } catch (error) {
      console.error('localStorage pruning failed:', error)
      // 最后手段：清空事件记录
      try {
        localStorage.removeItem('ai-intervention-fallback-events')
        console.debug('localStorage event records cleared')
      } catch (clearError) {
        console.error('Cannot clear localStorage:', clearError)
      }
    }
  }
}

// 创建全局通知管理器实例
const notificationManager = new NotificationManager()
