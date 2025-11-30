/**
 * ValidationUtils - 统一验证工具类
 *
 * 提供前端统一的验证功能，包括：
 * - 文件验证（类型、大小、文件名）
 * - 输入验证（长度、格式）
 * - 安全检查（XSS、特殊字符）
 *
 * @module ValidationUtils
 * @version 1.0.0
 */

class ValidationUtils {
  // ========================================
  // 静态配置常量
  // ========================================

  /** 支持的图片MIME类型 */
  static SUPPORTED_IMAGE_TYPES = [
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/bmp'
  ]

  /** 最小文件大小（100字节） */
  static MIN_FILE_SIZE = 100

  /** 最大文件大小（10MB） */
  static MAX_FILE_SIZE = 10 * 1024 * 1024

  /** 最大文件名长度 */
  static MAX_FILENAME_LENGTH = 255

  /** 可疑文件扩展名（安全黑名单） */
  static SUSPICIOUS_EXTENSIONS = [
    '.exe', '.bat', '.cmd', '.scr', '.com', '.pif',
    '.vbs', '.js', '.jar', '.msi', '.dll', '.ps1'
  ]

  /** 文件名中禁止的字符 */
  static FORBIDDEN_FILENAME_CHARS = /[<>:"/\\|?*\x00-\x1f]/g

  /** XSS危险字符模式 */
  static XSS_PATTERNS = [
    /<script\b[^>]*>/gi,
    /javascript:/gi,
    /on\w+\s*=/gi,
    /data:\s*text\/html/gi
  ]

  // ========================================
  // 文件验证方法
  // ========================================

  /**
   * 验证图片文件
   *
   * @param {File} file - 要验证的文件对象
   * @returns {Object} 验证结果 { valid: boolean, errors: string[] }
   *
   * @example
   * const result = ValidationUtils.validateImageFile(file);
   * if (!result.valid) {
   *   console.error(result.errors);
   * }
   */
  static validateImageFile(file) {
    const errors = []

    // 基础检查
    if (!file) {
      errors.push('文件对象为空')
      return { valid: false, errors }
    }

    if (!file.type) {
      errors.push('无法识别文件类型')
      return { valid: false, errors }
    }

    // 类型验证
    if (!this.SUPPORTED_IMAGE_TYPES.includes(file.type)) {
      errors.push(`不支持的图片格式: ${file.type}`)
    }

    // 大小验证
    if (file.size < this.MIN_FILE_SIZE) {
      errors.push(`文件太小 (${file.size} bytes)，可能是空文件或损坏`)
    }

    if (file.size > this.MAX_FILE_SIZE) {
      const sizeMB = (file.size / 1024 / 1024).toFixed(2)
      errors.push(`文件超过大小限制: ${sizeMB}MB > 10MB`)
    }

    // 文件名验证
    const filenameErrors = this.validateFilename(file.name)
    errors.push(...filenameErrors)

    // 安全检查
    const securityErrors = this.checkFileSecurity(file)
    errors.push(...securityErrors)

    return {
      valid: errors.length === 0,
      errors
    }
  }

  /**
   * 验证文件名
   *
   * @param {string} filename - 文件名
   * @returns {string[]} 错误信息数组
   */
  static validateFilename(filename) {
    const errors = []

    if (!filename) {
      errors.push('文件名为空')
      return errors
    }

    // 长度检查
    if (filename.length > this.MAX_FILENAME_LENGTH) {
      errors.push(`文件名过长 (${filename.length} > ${this.MAX_FILENAME_LENGTH})`)
    }

    // 危险字符检查
    if (this.FORBIDDEN_FILENAME_CHARS.test(filename)) {
      errors.push('文件名包含非法字符')
    }

    // 路径遍历检查
    if (filename.includes('..') || filename.includes('/') || filename.includes('\\')) {
      errors.push('文件名包含路径遍历字符')
    }

    return errors
  }

  /**
   * 文件安全检查
   *
   * @param {File} file - 文件对象
   * @returns {string[]} 安全警告数组
   */
  static checkFileSecurity(file) {
    const errors = []
    const filename = file.name?.toLowerCase() || ''

    // 可疑扩展名检查
    for (const ext of this.SUSPICIOUS_EXTENSIONS) {
      if (filename.endsWith(ext)) {
        errors.push(`检测到可疑文件类型: ${ext}`)
        break
      }
    }

    // 双扩展名检查（如 image.jpg.exe）
    const parts = filename.split('.')
    if (parts.length > 2) {
      const lastExt = '.' + parts[parts.length - 1]
      if (this.SUSPICIOUS_EXTENSIONS.includes(lastExt)) {
        errors.push('检测到伪装的可执行文件')
      }
    }

    return errors
  }

  // ========================================
  // 输入验证方法
  // ========================================

  /**
   * 验证文本输入
   *
   * @param {string} text - 输入文本
   * @param {Object} options - 验证选项
   * @param {number} [options.minLength=0] - 最小长度
   * @param {number} [options.maxLength=10000] - 最大长度
   * @param {boolean} [options.allowEmpty=true] - 是否允许空值
   * @param {boolean} [options.sanitize=true] - 是否进行XSS清理
   * @returns {Object} { valid: boolean, errors: string[], sanitized: string }
   */
  static validateTextInput(text, options = {}) {
    const {
      minLength = 0,
      maxLength = 10000,
      allowEmpty = true,
      sanitize = true
    } = options

    const errors = []
    let sanitized = text || ''

    // 空值检查
    if (!text || text.trim() === '') {
      if (!allowEmpty) {
        errors.push('输入不能为空')
      }
      return { valid: allowEmpty, errors, sanitized: '' }
    }

    // 长度检查
    if (text.length < minLength) {
      errors.push(`输入长度不足 (${text.length} < ${minLength})`)
    }

    if (text.length > maxLength) {
      errors.push(`输入长度超限 (${text.length} > ${maxLength})`)
      sanitized = text.substring(0, maxLength)
    }

    // XSS清理
    if (sanitize) {
      sanitized = this.sanitizeText(sanitized)
    }

    return {
      valid: errors.length === 0,
      errors,
      sanitized
    }
  }

  /**
   * 清理文本中的XSS危险内容
   *
   * @param {string} text - 原始文本
   * @returns {string} 清理后的文本
   */
  static sanitizeText(text) {
    if (!text) return ''

    let sanitized = text

    // 移除XSS危险模式
    for (const pattern of this.XSS_PATTERNS) {
      sanitized = sanitized.replace(pattern, '')
    }

    // HTML实体编码
    sanitized = sanitized
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#x27;')

    return sanitized
  }

  /**
   * 安全的文件名清理
   *
   * @param {string} filename - 原始文件名
   * @param {number} [maxLength=100] - 最大长度
   * @returns {string} 清理后的安全文件名
   */
  static sanitizeFilename(filename, maxLength = 100) {
    if (!filename) return ''

    return filename
      .replace(this.FORBIDDEN_FILENAME_CHARS, '')
      .replace(/\s+/g, '_')
      .replace(/\.{2,}/g, '.')  // 移除连续点
      .trim()
      .substring(0, maxLength)
  }

  // ========================================
  // 数值验证方法
  // ========================================

  /**
   * 验证数值范围
   *
   * @param {number} value - 要验证的数值
   * @param {number} min - 最小值
   * @param {number} max - 最大值
   * @param {string} [fieldName='值'] - 字段名称（用于错误消息）
   * @returns {Object} { valid: boolean, value: number, error: string }
   */
  static validateNumberRange(value, min, max, fieldName = '值') {
    const num = Number(value)

    if (isNaN(num)) {
      return {
        valid: false,
        value: min,
        error: `${fieldName} 必须是数字`
      }
    }

    if (num < min) {
      return {
        valid: false,
        value: min,
        error: `${fieldName} 不能小于 ${min}`
      }
    }

    if (num > max) {
      return {
        valid: false,
        value: max,
        error: `${fieldName} 不能大于 ${max}`
      }
    }

    return {
      valid: true,
      value: num,
      error: null
    }
  }

  /**
   * 限制数值在范围内（不返回错误，直接调整）
   *
   * @param {number} value - 要限制的数值
   * @param {number} min - 最小值
   * @param {number} max - 最大值
   * @returns {number} 限制后的数值
   */
  static clampValue(value, min, max) {
    const num = Number(value)
    if (isNaN(num)) return min
    return Math.max(min, Math.min(max, num))
  }
}

/**
 * APICache - API 响应缓存类
 *
 * 提供简单的 API 响应缓存功能，减少重复请求
 *
 * @module APICache
 * @version 1.0.0
 */

class APICache {
  constructor(defaultTTL = 30000) {
    this.cache = new Map()
    this.defaultTTL = defaultTTL  // 默认缓存时间（毫秒）
  }

  /**
   * 获取缓存
   *
   * @param {string} key - 缓存键
   * @returns {*} 缓存的值，不存在或已过期返回 null
   */
  get(key) {
    const entry = this.cache.get(key)
    if (!entry) return null

    if (Date.now() > entry.expiry) {
      this.cache.delete(key)
      return null
    }

    return entry.value
  }

  /**
   * 设置缓存
   *
   * @param {string} key - 缓存键
   * @param {*} value - 缓存值
   * @param {number} [ttl] - 过期时间（毫秒），默认使用 defaultTTL
   */
  set(key, value, ttl = this.defaultTTL) {
    this.cache.set(key, {
      value,
      expiry: Date.now() + ttl
    })
  }

  /**
   * 删除缓存
   *
   * @param {string} key - 缓存键
   */
  delete(key) {
    this.cache.delete(key)
  }

  /**
   * 清空所有缓存
   */
  clear() {
    this.cache.clear()
  }

  /**
   * 清理过期缓存
   */
  cleanup() {
    const now = Date.now()
    for (const [key, entry] of this.cache.entries()) {
      if (now > entry.expiry) {
        this.cache.delete(key)
      }
    }
  }

  /**
   * 获取缓存大小
   *
   * @returns {number} 缓存条目数
   */
  get size() {
    return this.cache.size
  }

  /**
   * 带缓存的 fetch 请求
   *
   * @param {string} url - 请求URL
   * @param {Object} [options] - fetch 选项
   * @param {number} [cacheTTL] - 缓存时间（毫秒）
   * @returns {Promise<*>} 响应数据
   */
  async fetchWithCache(url, options = {}, cacheTTL = this.defaultTTL) {
    // 只缓存 GET 请求
    const method = options.method?.toUpperCase() || 'GET'
    if (method !== 'GET') {
      const response = await fetch(url, options)
      return response.json()
    }

    // 检查缓存
    const cacheKey = `${method}:${url}`
    const cached = this.get(cacheKey)
    if (cached !== null) {
      return cached
    }

    // 发起请求
    const response = await fetch(url, options)
    const data = await response.json()

    // 存入缓存
    if (response.ok) {
      this.set(cacheKey, data, cacheTTL)
    }

    return data
  }
}

// 创建全局缓存实例
const apiCache = new APICache(30000)  // 30秒默认缓存

// 定期清理过期缓存（每5分钟）
setInterval(() => {
  apiCache.cleanup()
}, 5 * 60 * 1000)


// ========================================
// 性能优化工具：去抖动与节流
// ========================================

/**
 * 去抖动函数 (Debounce)
 *
 * 功能说明：
 *   延迟执行函数，直到最后一次调用后的指定时间内没有新调用。
 *   适用于：搜索输入、窗口调整、配置保存等高频触发场景。
 *
 * @param {Function} func - 要去抖动的函数
 * @param {number} [wait=300] - 等待时间（毫秒）
 * @param {boolean} [immediate=false] - 是否立即执行（首次调用时）
 * @returns {Function} 去抖动后的函数
 *
 * @example
 * const debouncedSave = debounce(() => saveConfig(), 500);
 * input.addEventListener('input', debouncedSave);
 */
function debounce(func, wait = 300, immediate = false) {
  let timeout = null
  let result = null

  const debounced = function(...args) {
    const context = this
    const callNow = immediate && !timeout

    // 清除之前的定时器
    if (timeout) {
      clearTimeout(timeout)
    }

    timeout = setTimeout(() => {
      timeout = null
      if (!immediate) {
        result = func.apply(context, args)
      }
    }, wait)

    // 立即执行模式
    if (callNow) {
      result = func.apply(context, args)
    }

    return result
  }

  // 取消去抖动
  debounced.cancel = function() {
    if (timeout) {
      clearTimeout(timeout)
      timeout = null
    }
  }

  // 立即执行
  debounced.flush = function(...args) {
    debounced.cancel()
    return func.apply(this, args)
  }

  return debounced
}

/**
 * 节流函数 (Throttle)
 *
 * 功能说明：
 *   限制函数在指定时间内只能执行一次。
 *   适用于：滚动事件、拖拽事件、动画帧等需要限制频率的场景。
 *
 * @param {Function} func - 要节流的函数
 * @param {number} [wait=200] - 节流间隔（毫秒）
 * @param {Object} [options] - 配置选项
 * @param {boolean} [options.leading=true] - 是否在开始时执行
 * @param {boolean} [options.trailing=true] - 是否在结束时执行
 * @returns {Function} 节流后的函数
 *
 * @example
 * const throttledScroll = throttle(() => handleScroll(), 100);
 * window.addEventListener('scroll', throttledScroll);
 */
function throttle(func, wait = 200, options = {}) {
  let timeout = null
  let previous = 0
  const { leading = true, trailing = true } = options

  const throttled = function(...args) {
    const context = this
    const now = Date.now()

    // 首次调用时，如果不允许 leading，设置 previous 为当前时间
    if (!previous && !leading) {
      previous = now
    }

    const remaining = wait - (now - previous)

    if (remaining <= 0 || remaining > wait) {
      // 到达执行时间
      if (timeout) {
        clearTimeout(timeout)
        timeout = null
      }
      previous = now
      func.apply(context, args)
    } else if (!timeout && trailing) {
      // 设置尾部执行定时器
      timeout = setTimeout(() => {
        previous = leading ? Date.now() : 0
        timeout = null
        func.apply(context, args)
      }, remaining)
    }
  }

  // 取消节流
  throttled.cancel = function() {
    if (timeout) {
      clearTimeout(timeout)
      timeout = null
    }
    previous = 0
  }

  return throttled
}

/**
 * 请求去重器
 *
 * 功能说明：
 *   防止同一请求在短时间内被重复发送。
 *   适用于：防止表单重复提交、防止按钮连点等场景。
 *
 * @class RequestDeduplicator
 */
class RequestDeduplicator {
  constructor() {
    this.pendingRequests = new Map()
  }

  /**
   * 执行去重的异步操作
   *
   * @param {string} key - 请求标识符
   * @param {Function} asyncFn - 异步函数
   * @returns {Promise<*>} 请求结果
   */
  async dedupe(key, asyncFn) {
    // 如果已有相同请求在进行中，返回该请求的 Promise
    if (this.pendingRequests.has(key)) {
      console.debug(`[RequestDeduplicator] 去重请求: ${key}`)
      return this.pendingRequests.get(key)
    }

    // 创建新请求
    const promise = asyncFn().finally(() => {
      this.pendingRequests.delete(key)
    })

    this.pendingRequests.set(key, promise)
    return promise
  }

  /**
   * 检查是否有待处理的请求
   *
   * @param {string} key - 请求标识符
   * @returns {boolean}
   */
  isPending(key) {
    return this.pendingRequests.has(key)
  }

  /**
   * 清除所有待处理请求
   */
  clear() {
    this.pendingRequests.clear()
  }
}

// 创建全局请求去重器实例
const requestDeduplicator = new RequestDeduplicator()


// ========================================
// 性能优化工具：图片懒加载
// ========================================

/**
 * 图片懒加载器
 *
 * 功能说明：
 *   使用 Intersection Observer API 实现图片懒加载，
 *   仅当图片进入视口时才开始加载，减少首屏加载时间。
 *
 * 使用方法：
 *   1. 图片使用 data-src 属性存储真实 URL，src 设置为占位图
 *   2. 添加 .lazy-image 类标记需要懒加载的图片
 *   3. 调用 LazyLoader.init() 初始化
 *
 * @class LazyLoader
 */
class LazyLoader {
  /**
   * 配置选项
   */
  static defaultOptions = {
    rootMargin: '50px 0px',    // 提前 50px 开始加载
    threshold: 0.01,            // 1% 可见即触发
    loadingClass: 'lazy-loading',
    loadedClass: 'lazy-loaded',
    errorClass: 'lazy-error'
  }

  /**
   * 初始化懒加载
   *
   * @param {string} [selector='.lazy-image'] - 图片选择器
   * @param {Object} [options] - 配置选项
   */
  static init(selector = '.lazy-image', options = {}) {
    const config = { ...this.defaultOptions, ...options }

    // 检查浏览器支持
    if (!('IntersectionObserver' in window)) {
      console.warn('浏览器不支持 IntersectionObserver，使用降级方案')
      this.loadAllImages(selector)
      return
    }

    // 创建观察器
    const observer = new IntersectionObserver((entries, obs) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          this.loadImage(entry.target, config)
          obs.unobserve(entry.target)
        }
      })
    }, {
      rootMargin: config.rootMargin,
      threshold: config.threshold
    })

    // 观察所有懒加载图片
    document.querySelectorAll(selector).forEach(img => {
      observer.observe(img)
    })

    // 保存观察器引用
    this._observer = observer
    console.log(`懒加载已初始化，监控 ${document.querySelectorAll(selector).length} 张图片`)
  }

  /**
   * 加载单张图片
   *
   * @param {HTMLImageElement} img - 图片元素
   * @param {Object} config - 配置选项
   */
  static loadImage(img, config = this.defaultOptions) {
    const src = img.dataset.src
    if (!src) return

    // 添加加载中状态
    img.classList.add(config.loadingClass)

    // 预加载图片
    const tempImg = new Image()

    tempImg.onload = () => {
      img.src = src
      img.classList.remove(config.loadingClass)
      img.classList.add(config.loadedClass)
      img.removeAttribute('data-src')
    }

    tempImg.onerror = () => {
      img.classList.remove(config.loadingClass)
      img.classList.add(config.errorClass)
      console.warn(`图片加载失败: ${src}`)
    }

    tempImg.src = src
  }

  /**
   * 降级方案：立即加载所有图片
   *
   * @param {string} selector - 图片选择器
   */
  static loadAllImages(selector) {
    document.querySelectorAll(selector).forEach(img => {
      this.loadImage(img)
    })
  }

  /**
   * 手动触发特定图片加载
   *
   * @param {HTMLImageElement|string} target - 图片元素或选择器
   */
  static load(target) {
    const img = typeof target === 'string'
      ? document.querySelector(target)
      : target

    if (img) {
      this.loadImage(img)
    }
  }

  /**
   * 观察新添加的图片
   *
   * @param {HTMLImageElement} img - 新图片元素
   */
  static observe(img) {
    if (this._observer && img) {
      this._observer.observe(img)
    }
  }

  /**
   * 停止观察
   */
  static disconnect() {
    if (this._observer) {
      this._observer.disconnect()
      this._observer = null
    }
  }
}


// ========================================
// 性能优化工具：虚拟滚动（长列表优化）
// ========================================

/**
 * 简易虚拟滚动实现
 *
 * 功能说明：
 *   只渲染可视区域内的列表项，减少 DOM 节点数量，
 *   适用于任务列表、日志列表等长列表场景。
 *
 * @class VirtualScroller
 */
class VirtualScroller {
  /**
   * @param {HTMLElement} container - 滚动容器
   * @param {Object} options - 配置选项
   */
  constructor(container, options = {}) {
    this.container = container
    this.itemHeight = options.itemHeight || 50
    this.buffer = options.buffer || 5
    this.items = []
    this.renderItem = options.renderItem || (item => `<div>${item}</div>`)

    this.init()
  }

  init() {
    // 创建内部结构
    this.wrapper = document.createElement('div')
    this.wrapper.className = 'virtual-scroll-wrapper'
    this.wrapper.style.position = 'relative'

    this.content = document.createElement('div')
    this.content.className = 'virtual-scroll-content'
    this.wrapper.appendChild(this.content)

    this.container.appendChild(this.wrapper)

    // 绑定滚动事件（使用节流）
    this.container.addEventListener('scroll',
      typeof throttle !== 'undefined'
        ? throttle(() => this.render(), 16)  // ~60fps
        : () => this.render()
    )
  }

  /**
   * 设置数据
   *
   * @param {Array} items - 列表数据
   */
  setItems(items) {
    this.items = items
    this.wrapper.style.height = `${items.length * this.itemHeight}px`
    this.render()
  }

  /**
   * 渲染可见项
   */
  render() {
    const scrollTop = this.container.scrollTop
    const containerHeight = this.container.clientHeight

    const startIndex = Math.max(0, Math.floor(scrollTop / this.itemHeight) - this.buffer)
    const endIndex = Math.min(
      this.items.length,
      Math.ceil((scrollTop + containerHeight) / this.itemHeight) + this.buffer
    )

    const visibleItems = this.items.slice(startIndex, endIndex)

    this.content.style.transform = `translateY(${startIndex * this.itemHeight}px)`
    this.content.innerHTML = visibleItems
      .map((item, i) => this.renderItem(item, startIndex + i))
      .join('')
  }

  /**
   * 滚动到指定项
   *
   * @param {number} index - 项索引
   */
  scrollToIndex(index) {
    this.container.scrollTop = index * this.itemHeight
  }

  /**
   * 销毁
   */
  destroy() {
    this.container.removeChild(this.wrapper)
  }
}


// 导出（兼容不同的模块系统）
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    ValidationUtils,
    APICache,
    apiCache,
    debounce,
    throttle,
    RequestDeduplicator,
    requestDeduplicator,
    LazyLoader,
    VirtualScroller
  }
}
