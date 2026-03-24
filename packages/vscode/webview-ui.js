/* eslint-disable */
// 此文件由 packages/vscode/webview.js 的内联脚本抽取生成
// 说明：用于在 Webview 中执行 UI 逻辑；通过 <meta id="aiia-config"> 注入运行时配置

;(function () {
  let vscode
  try {
    vscode = acquireVsCodeApi()
  } catch (e) {
    vscode = {
      postMessage: function () {},
      getState: function () {
        return null
      },
      setState: function () {}
    }
  }
  const __cfgEl = document.getElementById('aiia-config')
  const SERVER_URL =
    __cfgEl && __cfgEl.getAttribute('data-server-url')
      ? __cfgEl.getAttribute('data-server-url')
      : ''
  const CSP_NONCE =
    __cfgEl && __cfgEl.getAttribute('data-csp-nonce') ? __cfgEl.getAttribute('data-csp-nonce') : ''
  const LOTTIE_LIB_URL =
    __cfgEl && __cfgEl.getAttribute('data-lottie-lib-url')
      ? __cfgEl.getAttribute('data-lottie-lib-url')
      : ''
  const NO_CONTENT_LOTTIE_JSON_URL =
    __cfgEl && __cfgEl.getAttribute('data-no-content-lottie-json-url')
      ? __cfgEl.getAttribute('data-no-content-lottie-json-url')
      : ''
  const MATHJAX_SCRIPT_URL =
    __cfgEl && __cfgEl.getAttribute('data-mathjax-script-url')
      ? __cfgEl.getAttribute('data-mathjax-script-url')
      : ''
  const MARKED_JS_URL =
    __cfgEl && __cfgEl.getAttribute('data-marked-js-url')
      ? __cfgEl.getAttribute('data-marked-js-url')
      : ''
  const PRISM_JS_URL =
    __cfgEl && __cfgEl.getAttribute('data-prism-js-url') ? __cfgEl.getAttribute('data-prism-js-url') : ''
  const NOTIFY_CORE_JS_URL =
    __cfgEl && __cfgEl.getAttribute('data-notify-core-js-url')
      ? __cfgEl.getAttribute('data-notify-core-js-url')
      : ''
  const SETTINGS_UI_JS_URL =
    __cfgEl && __cfgEl.getAttribute('data-settings-ui-js-url')
      ? __cfgEl.getAttribute('data-settings-ui-js-url')
      : ''
  const WEBVIEW_HELPERS =
    typeof window !== 'undefined' && window.AIIAWebviewHelpers ? window.AIIAWebviewHelpers : null
  let themeObserver = null
  // 无有效内容页面：Lottie 动画（默认使用 hourglass.json；失败则降级为 ⏳）
  let noContentHourglassAnimation = null

  // 网络请求超时（避免本地端口“半开/卡住”导致一直停在“正在连接服务器...”）
  const SERVER_STATUS_TIMEOUT_MS = 1500
  const POLL_TASKS_TIMEOUT_MS = 6000
  const POLL_CONFIG_TIMEOUT_MS = 6000
  // 提交可能包含图片上传，允许更长超时；但必须兜底，避免无响应导致 UI 永久卡住
  const SUBMIT_TIMEOUT_MS = 20000

  function parseRgbColor(color) {
    try {
      if (!color) return null
      const s = String(color).trim()
      if (!s) return null

      const start = s.indexOf('(')
      const end = s.indexOf(')')
      if (start < 0 || end < 0 || end <= start) return null

      const head = s.slice(0, start).toLowerCase()
      if (head !== 'rgb' && head !== 'rgba') return null

      const parts = s
        .slice(start + 1, end)
        .split(',')
        .map(p => p.trim())
      if (parts.length < 3) return null

      const r = Number(parts[0])
      const g = Number(parts[1])
      const b = Number(parts[2])
      if (![r, g, b].every(n => Number.isFinite(n))) return null

      return { r, g, b }
    } catch (e) {
      return null
    }
  }

  function isDarkBackground() {
    try {
      const bg = window.getComputedStyle(document.body).backgroundColor
      const rgb = parseRgbColor(bg)
      if (!rgb) return false
      const luminance = 0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b
      return luminance < 128
    } catch (e) {
      return false
    }
  }

  function updateNoContentHourglassColor() {
    const container = document.getElementById('hourglass-lottie')
    if (!container) return
    // CSP 收紧后禁止动态写入 inline style，这里改为 class 驱动
    container.classList.toggle('aiia-invert', isDarkBackground())
  }

  function isMacLikePlatform() {
    try {
      if (WEBVIEW_HELPERS && typeof WEBVIEW_HELPERS.detectMacLikePlatform === 'function') {
        return !!WEBVIEW_HELPERS.detectMacLikePlatform(navigator)
      }
    } catch (e) {
      // 忽略
    }
    return !!(navigator && navigator.platform && navigator.platform.includes('Mac'))
  }

  function applyHostThemeState() {
    try {
      if (WEBVIEW_HELPERS && typeof WEBVIEW_HELPERS.applyThemeKindToDocument === 'function') {
        WEBVIEW_HELPERS.applyThemeKindToDocument(document)
      }
    } catch (e) {
      // 忽略
    }
    updateNoContentHourglassColor()
  }

  function installHostThemeObserver() {
    applyHostThemeState()
    if (themeObserver || typeof MutationObserver === 'undefined' || !document.body) return

    themeObserver = new MutationObserver(() => {
      applyHostThemeState()
    })
    themeObserver.observe(document.body, {
      attributes: true,
      attributeFilter: ['class']
    })
  }

  function destroyNoContentHourglassAnimation() {
    try {
      if (noContentHourglassAnimation) {
        noContentHourglassAnimation.destroy()
      }
    } catch (e) {
      // 忽略
    } finally {
      noContentHourglassAnimation = null
    }
  }

  // 懒加载 Lottie：仅在无内容页需要时加载，降低首屏解析与内存占用
  let lottieLoadPromise = null
  let noContentLottieDataPromise = null
  let noContentLottieInitInFlight = false
  let lottieInitWarned = false

  function ensureLottieLoaded() {
    if (typeof lottie !== 'undefined' && lottie && typeof lottie.loadAnimation === 'function') {
      return Promise.resolve(true)
    }
    if (!LOTTIE_LIB_URL) {
      return Promise.resolve(false)
    }
    if (lottieLoadPromise) return lottieLoadPromise

    lottieLoadPromise = new Promise(resolve => {
      try {
        const s = document.createElement('script')
        s.src = LOTTIE_LIB_URL
        s.defer = true
        // 关键：带 nonce，才能通过 CSP（script-src 'nonce-...'）
        s.setAttribute('nonce', CSP_NONCE)
        s.onload = () => {
          resolve(
            typeof lottie !== 'undefined' && lottie && typeof lottie.loadAnimation === 'function'
          )
        }
        s.onerror = () => resolve(false)
        document.head.appendChild(s)
      } catch (e) {
        resolve(false)
      }
    })
    return lottieLoadPromise
  }

  // 懒加载 marked / Prism：仅在需要渲染 Markdown/高亮代码时加载，降低首屏解析与内存占用
  let markedLoadPromise = null
  let prismLoadPromise = null
  let markedOptionsConfigured = false

  function configureMarkedOnce() {
    if (markedOptionsConfigured) return
    if (typeof marked === 'undefined' || !marked || typeof marked.setOptions !== 'function') return
    try {
      marked.setOptions({
        breaks: true, // 支持 GFM 换行
        gfm: true, // 启用 GitHub Flavored Markdown
        headerIds: false, // 禁用标题ID（避免冲突）
        mangle: false // 禁用邮件地址混淆
      })
      markedOptionsConfigured = true
    } catch (e) {
      // 忽略：配置失败不应影响主流程
    }
  }

  function ensureMarkedLoaded() {
    try {
      if (typeof marked !== 'undefined' && marked && typeof marked.parse === 'function') {
        configureMarkedOnce()
        return Promise.resolve(true)
      }
    } catch (e) {
      // 忽略
    }

    if (!MARKED_JS_URL) {
      return Promise.resolve(false)
    }
    if (markedLoadPromise) return markedLoadPromise

    markedLoadPromise = new Promise(resolve => {
      try {
        const existing = document.getElementById('aiia-marked-script')
        if (existing) {
          const start = Date.now()
          const tick = () => {
            try {
              if (typeof marked !== 'undefined' && marked && typeof marked.parse === 'function') {
                configureMarkedOnce()
                resolve(true)
                return
              }
            } catch (e) {
              // 忽略
            }
            if (Date.now() - start > 5000) {
              resolve(false)
              return
            }
            setTimeout(tick, 50)
          }
          tick()
          return
        }

        const s = document.createElement('script')
        s.id = 'aiia-marked-script'
        s.src = MARKED_JS_URL
        s.defer = true
        // 关键：带 nonce，才能通过 CSP（script-src 'nonce-...'）
        if (CSP_NONCE) {
          try {
            s.setAttribute('nonce', CSP_NONCE)
          } catch (e) {
            // 忽略
          }
        }
        s.onload = () => {
          try {
            if (typeof marked !== 'undefined' && marked && typeof marked.parse === 'function') {
              configureMarkedOnce()
              resolve(true)
              return
            }
          } catch (e) {
            // 忽略
          }
          resolve(false)
        }
        s.onerror = () => resolve(false)
        document.head.appendChild(s)
      } catch (e) {
        resolve(false)
      }
    })

    return markedLoadPromise
  }

  function ensurePrismLoaded() {
    try {
      if (typeof Prism !== 'undefined' && Prism && typeof Prism.highlightAllUnder === 'function') {
        return Promise.resolve(true)
      }
    } catch (e) {
      // 忽略
    }

    if (!PRISM_JS_URL) {
      return Promise.resolve(false)
    }
    if (prismLoadPromise) return prismLoadPromise

    prismLoadPromise = new Promise(resolve => {
      try {
        // 保底：确保禁用自动高亮（与 prism-bootstrap.js 对齐）
        try {
          if (typeof globalThis !== 'undefined') {
            globalThis.Prism = globalThis.Prism || {}
            globalThis.Prism.manual = true
          } else if (typeof window !== 'undefined') {
            window.Prism = window.Prism || {}
            window.Prism.manual = true
          }
        } catch (e) {
          // 忽略
        }

        const existing = document.getElementById('aiia-prism-script')
        if (existing) {
          const start = Date.now()
          const tick = () => {
            try {
              if (typeof Prism !== 'undefined' && Prism && typeof Prism.highlightAllUnder === 'function') {
                resolve(true)
                return
              }
            } catch (e) {
              // 忽略
            }
            if (Date.now() - start > 5000) {
              resolve(false)
              return
            }
            setTimeout(tick, 50)
          }
          tick()
          return
        }

        const s = document.createElement('script')
        s.id = 'aiia-prism-script'
        s.src = PRISM_JS_URL
        s.defer = true
        // 关键：带 nonce，才能通过 CSP（script-src 'nonce-...'）
        if (CSP_NONCE) {
          try {
            s.setAttribute('nonce', CSP_NONCE)
          } catch (e) {
            // 忽略
          }
        }
        s.onload = () => {
          try {
            resolve(typeof Prism !== 'undefined' && Prism && typeof Prism.highlightAllUnder === 'function')
          } catch (e) {
            resolve(false)
          }
        }
        s.onerror = () => resolve(false)
        document.head.appendChild(s)
      } catch (e) {
        resolve(false)
      }
    })

    return prismLoadPromise
  }

  // 按需加载：通知配置核心 & 设置面板 UI（进一步降低首屏解析成本）
  let notifyCoreLoadPromise = null
  let settingsUiLoadPromise = null

  function getNotifyCoreModule() {
    try {
      if (typeof globalThis !== 'undefined' && globalThis && globalThis.AIIAWebviewNotifyCore) {
        return globalThis.AIIAWebviewNotifyCore
      }
    } catch (e) {
      // 忽略
    }
    try {
      if (typeof window !== 'undefined' && window && window.AIIAWebviewNotifyCore) {
        return window.AIIAWebviewNotifyCore
      }
    } catch (e) {
      // 忽略
    }
    return null
  }

  function getSettingsUiModule() {
    try {
      if (typeof globalThis !== 'undefined' && globalThis && globalThis.AIIAWebviewSettingsUi) {
        return globalThis.AIIAWebviewSettingsUi
      }
    } catch (e) {
      // 忽略
    }
    try {
      if (typeof window !== 'undefined' && window && window.AIIAWebviewSettingsUi) {
        return window.AIIAWebviewSettingsUi
      }
    } catch (e) {
      // 忽略
    }
    return null
  }

  function ensureNotifyCoreLoaded() {
    try {
      const existing = getNotifyCoreModule()
      if (existing && typeof existing.showNewTaskNotification === 'function') {
        return Promise.resolve(true)
      }
    } catch (e) {
      // 忽略
    }

    if (!NOTIFY_CORE_JS_URL) return Promise.resolve(false)
    if (notifyCoreLoadPromise) return notifyCoreLoadPromise

    notifyCoreLoadPromise = new Promise(resolve => {
      try {
        const existingScript = document.getElementById('aiia-notify-core-script')
        if (existingScript) {
          const start = Date.now()
          const tick = () => {
            const mod = getNotifyCoreModule()
            if (mod && typeof mod.showNewTaskNotification === 'function') {
              resolve(true)
              return
            }
            if (Date.now() - start > 5000) {
              resolve(false)
              return
            }
            setTimeout(tick, 50)
          }
          tick()
          return
        }

        const s = document.createElement('script')
        s.id = 'aiia-notify-core-script'
        s.src = NOTIFY_CORE_JS_URL
        s.defer = true
        if (CSP_NONCE) {
          try {
            s.setAttribute('nonce', CSP_NONCE)
          } catch (e) {
            // 忽略
          }
        }
        s.onload = () => {
          const mod = getNotifyCoreModule()
          resolve(!!(mod && typeof mod.showNewTaskNotification === 'function'))
        }
        s.onerror = () => resolve(false)
        document.head.appendChild(s)
      } catch (e) {
        resolve(false)
      }
    })

    return notifyCoreLoadPromise
  }

  function ensureSettingsUiLoaded() {
    try {
      const existing = getSettingsUiModule()
      if (existing && typeof existing.openSettings === 'function') {
        return Promise.resolve(true)
      }
    } catch (e) {
      // 忽略
    }

    if (!SETTINGS_UI_JS_URL) return Promise.resolve(false)
    if (settingsUiLoadPromise) return settingsUiLoadPromise

    settingsUiLoadPromise = new Promise(resolve => {
      try {
        const existingScript = document.getElementById('aiia-settings-ui-script')
        if (existingScript) {
          const start = Date.now()
          const tick = () => {
            const mod = getSettingsUiModule()
            if (mod && typeof mod.openSettings === 'function') {
              resolve(true)
              return
            }
            if (Date.now() - start > 5000) {
              resolve(false)
              return
            }
            setTimeout(tick, 50)
          }
          tick()
          return
        }

        const s = document.createElement('script')
        s.id = 'aiia-settings-ui-script'
        s.src = SETTINGS_UI_JS_URL
        s.defer = true
        if (CSP_NONCE) {
          try {
            s.setAttribute('nonce', CSP_NONCE)
          } catch (e) {
            // 忽略
          }
        }
        s.onload = () => {
          const mod = getSettingsUiModule()
          resolve(!!(mod && typeof mod.openSettings === 'function'))
        }
        s.onerror = () => resolve(false)
        document.head.appendChild(s)
      } catch (e) {
        resolve(false)
      }
    })

    return settingsUiLoadPromise
  }

  function scheduleLowPriorityWork(fn, timeoutMs) {
    try {
      const work = () => {
        try {
          fn()
        } catch (e) {
          // 忽略
        }
      }
      if (typeof requestIdleCallback === 'function') {
        requestIdleCallback(work, {
          timeout: typeof timeoutMs === 'number' && Number.isFinite(timeoutMs) ? timeoutMs : 600
        })
      } else if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(() => setTimeout(work, 0))
      } else {
        setTimeout(work, 0)
      }
    } catch (e) {
      try {
        setTimeout(() => fn(), 0)
      } catch (_) {
        // 忽略
      }
    }
  }

  function loadNoContentLottieData() {
    if (noContentLottieDataPromise) return noContentLottieDataPromise
    if (!NO_CONTENT_LOTTIE_JSON_URL) {
      noContentLottieDataPromise = Promise.resolve(null)
      return noContentLottieDataPromise
    }
    noContentLottieDataPromise = (async () => {
      try {
        const resp = await fetch(NO_CONTENT_LOTTIE_JSON_URL, { cache: 'force-cache' })
        if (!resp.ok) return null
        const data = await resp.json()
        return data && typeof data === 'object' ? data : null
      } catch (e) {
        return null
      }
    })()
    return noContentLottieDataPromise
  }

  function initNoContentHourglassAnimation() {
    const container = document.getElementById('hourglass-lottie')
    if (!container) return

    // 已初始化则只做颜色适配，避免轮询反复创建导致卡顿
    if (noContentHourglassAnimation) {
      updateNoContentHourglassColor()
      return
    }
    if (noContentLottieInitInFlight) return

    // 先给一个轻量占位，避免空白
    container.textContent = '⏳'
    noContentLottieInitInFlight = true

    Promise.all([ensureLottieLoaded(), loadNoContentLottieData()])
      .then(([okLib, data]) => {
        if (!okLib || !data) {
          if (!lottieInitWarned) {
            lottieInitWarned = true
            logError('Lottie 动画未加载（已降级为 ⏳）')
          }
          return
        }

        // 若无内容页已被隐藏，则不再创建动画（避免无谓消耗）
        const noContentState = document.getElementById('noContentState')
        if (noContentState && noContentState.classList.contains('hidden')) {
          return
        }

        container.textContent = ''
        noContentHourglassAnimation = lottie.loadAnimation({
          container: container,
          renderer: 'svg',
          loop: true,
          autoplay: true,
          animationData: data,
          rendererSettings: { preserveAspectRatio: 'xMidYMid meet' }
        })

        noContentHourglassAnimation.addEventListener('DOMLoaded', () => {
          updateNoContentHourglassColor()
        })

        noContentHourglassAnimation.addEventListener('error', () => {
          container.textContent = '⏳'
          if (!lottieInitWarned) {
            lottieInitWarned = true
            logError('Lottie 动画加载失败（已降级为 ⏳）')
          }
          destroyNoContentHourglassAnimation()
        })
      })
      .catch(() => {
        // 忽略
      })
      .finally(() => {
        noContentLottieInitInFlight = false
      })
  }

  /* 全局状态管理 */
  let currentConfig = null
  let selectedOptions = []
  let uploadedImages = []
  let textareaManualRows = null // 文本框手动 rows（用于拖拽调整高度）
  let countdownTimer = null
  // 防止超时自动重调进入“失败重试风暴”（例如任务 remaining=0 且提交失败时反复触发）：每任务只允许自动重调一次
  let autoSubmitAttempted = {} // task_id -> lastAttemptAt(ms)
  let pollingTimer = null
  let remainingSeconds = 0
  let allTasks = []
  let activeTaskId = null
  let tabCountdownTimers = {}
  let tabCountdownRemaining = {}
  // 【对齐服务端】server_time/deadline/remaining_time 支持（用于倒计时不漂移）
  let serverTimeOffset = 0 // 服务器时间 - 本地时间（秒）
  let taskDeadlines = {} // task_id -> deadline（秒级时间戳）
  let feedbackPrompts = {
    resubmit_prompt: '请立即调用 interactive_feedback 工具',
    prompt_suffix: '\n请积极调用 interactive_feedback 工具'
  }
  // 【对齐原始实现】多任务输入状态：每个任务独立保存输入/选项/图片，避免切换任务时“串任务”
  let taskTextareaContents = {} // task_id -> string
  let taskOptionsStates = {} // task_id -> { [index:number]: boolean } | boolean[]
  let taskImages = {} // task_id -> Array<{name: string, data: string}>

  // Webview 状态持久化（配合 retainContextWhenHidden=false，降低隐藏时内存常驻）
  const UI_STATE_VERSION = 1
  const UI_STATE_SAVE_DEBOUNCE_MS = 250
  const UI_STATE_TEXT_LIMIT_CHARS = 200000
  let uiStateSaveTimer = null

  function safeGetUiState() {
    try {
      if (vscode && typeof vscode.getState === 'function') {
        return vscode.getState()
      }
    } catch (e) {
      // 忽略
    }
    return null
  }

  function safeSetUiState(nextState) {
    try {
      if (vscode && typeof vscode.setState === 'function') {
        vscode.setState(nextState)
      }
    } catch (e) {
      // 忽略：状态持久化失败不应影响主流程
    }
  }

  function trimTextareaContents(contents) {
    try {
      const src = contents && typeof contents === 'object' ? contents : {}
      const out = {}
      let budget = UI_STATE_TEXT_LIMIT_CHARS
      for (const taskId of Object.keys(src)) {
        if (budget <= 0) break
        const text = src[taskId]
        if (typeof text !== 'string' || !text) continue
        if (text.length <= budget) {
          out[taskId] = text
          budget -= text.length
        } else {
          out[taskId] = text.slice(0, Math.max(0, budget))
          budget = 0
        }
      }
      return out
    } catch (e) {
      return {}
    }
  }

  function restorePersistedUiState() {
    const s = safeGetUiState()
    if (!s || s.v !== UI_STATE_VERSION) return

    try {
      if (s.taskTextareaContents && typeof s.taskTextareaContents === 'object') {
        taskTextareaContents = { ...s.taskTextareaContents }
      }
      if (s.taskOptionsStates && typeof s.taskOptionsStates === 'object') {
        taskOptionsStates = { ...s.taskOptionsStates }
      }
      if (typeof s.activeTaskId === 'string') {
        activeTaskId = s.activeTaskId || null
      }
      if (typeof s.textareaManualRows === 'number' && Number.isFinite(s.textareaManualRows)) {
        textareaManualRows = Math.max(2, Math.floor(s.textareaManualRows))
      }
    } catch (e) {
      // 忽略：持久化状态异常不应影响主流程
    }
  }

  function schedulePersistUiState() {
    if (!vscode || typeof vscode.setState !== 'function') return
    if (uiStateSaveTimer) return
    uiStateSaveTimer = setTimeout(() => {
      uiStateSaveTimer = null
      safeSetUiState({
        v: UI_STATE_VERSION,
        activeTaskId: activeTaskId || '',
        taskTextareaContents: trimTextareaContents(taskTextareaContents),
        taskOptionsStates: taskOptionsStates || {},
        // 图片不做持久化：体积过大且易触发存储上限
        textareaManualRows:
          typeof textareaManualRows === 'number' && Number.isFinite(textareaManualRows)
            ? Math.max(2, Math.floor(textareaManualRows))
            : null,
        savedAt: Date.now()
      })
    }, UI_STATE_SAVE_DEBOUNCE_MS)
  }

  // 启动时恢复一次（后续 poll/render 会自动清理不存在的 taskId 缓存）
  restorePersistedUiState()

  // 提交按钮：默认图标缓存 + Loading 图标（用于提交中切换）
  let submitBtnDefaultHtml = null
  const SUBMIT_BTN_FALLBACK_HTML =
    '<svg class="btn-icon submit-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" aria-hidden="true" focusable="false"><path d="M19.26 9.77C19.91 9.08 20.92 8.91 21.73 9.32L21.89 9.40L21.94 9.43L22.19 9.63C22.20 9.64 22.22 9.65 22.23 9.66L44.63 30.46C45.05 30.86 45.30 31.42 45.30 32.00C45.30 32.44 45.16 32.86 44.91 33.21C44.90 33.23 44.89 33.24 44.88 33.26L44.66 33.50C44.65 33.52 44.64 33.53 44.63 33.54L22.23 54.34C21.38 55.13 20.05 55.08 19.26 54.23C18.47 53.38 18.52 52.05 19.37 51.26L40.12 32.00L19.37 12.74C19.36 12.73 19.35 12.72 19.34 12.70L19.12 12.46C19.11 12.45 19.10 12.43 19.09 12.42C18.52 11.62 18.57 10.52 19.26 9.77Z" fill="currentColor" /></svg>'
  const SUBMIT_BTN_SPINNER_HTML =
    '<svg class="btn-icon spinner-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" opacity="0.25"></circle><path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path></svg>'
  // 插入代码：剪贴板请求 ID（防止短时间重复点击/按钮永久禁用）
  let clipboardRequestId = null
  // 提交治理：避免并发提交；429 时进入冷却，减少误操作导致的限流风暴
  let submitInFlight = false
  let submitBackoffUntilMs = 0
  let submitBackoffTimer = null

  // 【轮询治理】避免重叠请求/页面不可见浪费/错误风暴
  const POLL_BASE_MS = 2000
  const POLL_MAX_MS = 30000
  // 空闲态（无任务/无内容）降频：减少无意义请求与功耗
  const POLL_IDLE_MS = 8000
  let pollBackoffMs = POLL_BASE_MS
  let pollSuggestedDelayMs = null
  let pollAbortController = null
  let pollingInFlight = false
  let pollingVisibilityHandlerInstalled = false
  // 轮询代际：用于解决 stopPolling 与 in-flight 回调的竞态（防止 stop 后“复活”）
  let pollingEnabled = false
  let pollingToken = 0
  let lastTasksHash = ''
  let lastTaskIds = new Set()
  // 新任务通知边界：仅跳过“首次快照”（避免扩展启动时把历史任务当作新任务）
  // 但必须允许“从无任务 → 有任务”的场景触发通知。
  let hasInitializedTaskIdTracking = false
  let lastCountdownTaskId = null // 跟踪当前主倒计时对应的任务ID

  function getNextBackoffMs(currentMs) {
    // 指数退避 + 轻微抖动，避免多客户端同时打爆服务端
    const next = Math.min(POLL_MAX_MS, Math.round(currentMs * 1.7))
    const jitter = Math.round(next * 0.1 * Math.random()) // 0-10%
    return next + jitter
  }

  function installPollingVisibilityHandler() {
    if (pollingVisibilityHandlerInstalled) return
    pollingVisibilityHandlerInstalled = true
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopPolling()
      } else {
        // 恢复时立即拉一次，减少“回到页面后空白/延迟”
        startPolling()
      }
    })
  }

  /* 常规日志：默认 debug（由扩展侧 logLevel 控制是否显示） */
  function log(message) {
    try {
      vscode.postMessage({ type: 'log', level: 'debug', message: String(message) })
    } catch (e) {
      // 忽略：Webview 通信异常不应影响渲染
    }
  }

  function logError(message) {
    const text = String(message || '')
    try {
      vscode.postMessage({ type: 'log', level: 'error', message: text })
    } catch (e) {
      // 忽略
    }
    try {
      vscode.postMessage({ type: 'error', message: text })
    } catch (e) {
      // 忽略
    }
    try {
      showToast(text, { kind: 'error', timeoutMs: 2600, dedupeKey: 'err:' + text.slice(0, 120) })
    } catch (e) {
      // 忽略
    }
  }

  // Webview 内 Toast：非侵入式反馈（避免用户误以为无响应）
  let lastToastKey = ''
  let lastToastAtMs = 0
  function showToast(message, options) {
    const host = document.getElementById('toastHost')
    if (!host) return
    const text = String(message || '').trim()
    if (!text) return

    const kindRaw = options && options.kind ? String(options.kind) : 'info'
    const kind =
      kindRaw === 'success' || kindRaw === 'warn' || kindRaw === 'error' ? kindRaw : 'info'
    const timeoutMsRaw = options && typeof options.timeoutMs === 'number' ? options.timeoutMs : 1800
    const timeoutMs = Math.max(800, Math.min(8000, Math.floor(timeoutMsRaw)))
    const dedupeKey = options && options.dedupeKey ? String(options.dedupeKey) : kind + ':' + text

    const now = Date.now()
    if (dedupeKey && dedupeKey === lastToastKey && now - lastToastAtMs < 700) {
      return
    }
    lastToastKey = dedupeKey
    lastToastAtMs = now

    const el = document.createElement('div')
    el.className = 'toast ' + kind
    el.textContent = text
    el.setAttribute('role', 'status')
    el.setAttribute('aria-live', 'polite')

    let removed = false
    const remove = () => {
      if (removed) return
      removed = true
      try {
        el.classList.remove('show')
      } catch (e) {
        /* 忽略 */
      }
      setTimeout(() => {
        try {
          if (el.parentNode) el.parentNode.removeChild(el)
        } catch (e) {
          // 忽略
        }
      }, 180)
    }

    el.addEventListener('click', () => remove())
    host.appendChild(el)
    requestAnimationFrame(() => {
      try {
        el.classList.add('show')
      } catch (e) {
        /* 忽略 */
      }
    })
    setTimeout(remove, timeoutMs)
  }

  // 文本框：自动高度（Auto-resize），并保留用户手动拖拽的最小高度
  //
  // 注意：Webview CSP 收紧后（移除 style-src 'unsafe-inline'），JS 不能再写 textarea.style.height。
  // 这里改为 rows 属性驱动高度（配合 CSS height:auto）。
  const FEEDBACK_TEXTAREA_MIN_HEIGHT_PX = 80
  const FEEDBACK_TEXTAREA_MAX_HEIGHT_PX = 300

  function clampInt(n, min, max) {
    const x = Number.isFinite(n) ? Math.floor(n) : NaN
    if (!Number.isFinite(x)) return min
    return Math.max(min, Math.min(max, x))
  }

  function getTextareaMetrics(textarea) {
    try {
      const cs = window.getComputedStyle(textarea)
      let lineHeight = parseFloat(cs.lineHeight)
      if (!Number.isFinite(lineHeight) || lineHeight <= 0) {
        const fs = parseFloat(cs.fontSize)
        lineHeight = Number.isFinite(fs) && fs > 0 ? fs * 1.65 : 20
      }

      const paddingTop = parseFloat(cs.paddingTop) || 0
      const paddingBottom = parseFloat(cs.paddingBottom) || 0
      const borderTop = parseFloat(cs.borderTopWidth) || 0
      const borderBottom = parseFloat(cs.borderBottomWidth) || 0
      const verticalExtras = paddingTop + paddingBottom + borderTop + borderBottom
      return { lineHeight, verticalExtras }
    } catch (e) {
      return { lineHeight: 20, verticalExtras: 0 }
    }
  }

  function getTextareaRowsBounds(textarea) {
    const { lineHeight, verticalExtras } = getTextareaMetrics(textarea)
    const safeLineHeight = Number.isFinite(lineHeight) && lineHeight > 0 ? lineHeight : 20
    const minRows = Math.max(
      2,
      Math.ceil((FEEDBACK_TEXTAREA_MIN_HEIGHT_PX - verticalExtras) / safeLineHeight)
    )
    const maxRows = Math.max(
      minRows,
      Math.floor((FEEDBACK_TEXTAREA_MAX_HEIGHT_PX - verticalExtras) / safeLineHeight)
    )
    return { lineHeight: safeLineHeight, verticalExtras, minRows, maxRows }
  }

  function autoResizeFeedbackTextarea(textarea) {
    if (!textarea) return
    try {
      const { lineHeight, verticalExtras, minRows, maxRows } = getTextareaRowsBounds(textarea)

      // 为了让 scrollHeight 更接近“内容真实高度”，先收敛到最小 rows 再计算
      textarea.rows = minRows
      const contentHeight = textarea.scrollHeight || minRows * lineHeight + verticalExtras
      const neededRows = Math.ceil((contentHeight - verticalExtras) / lineHeight)

      let nextRows = clampInt(neededRows, minRows, maxRows)
      if (textareaManualRows && Number.isFinite(textareaManualRows)) {
        nextRows = Math.max(nextRows, textareaManualRows)
      }
      textarea.rows = nextRows
    } catch (e) {
      // 忽略
    }
  }

  // 统一通知事件派发：Webview → Extension（阶段 C）
  function postNotificationEvent(event) {
    try {
      vscode.postMessage({ type: 'notify', event: event || {} })
    } catch (e) {
      // 忽略：Webview 通信异常不应影响渲染
    }
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
      source: 'webview-ui',
      dedupeKey: message ? 'status:' + String(message).slice(0, 200) : ''
    })
  }

  async function fetchFeedbackPrompts(fetchOptions) {
    let controller = null
    let timeoutId = null
    try {
      const options = fetchOptions ? { ...fetchOptions } : { cache: 'no-store' }
      if (!options.cache) options.cache = 'no-store'

      if (typeof AbortController !== 'undefined') {
        controller = new AbortController()
        options.signal = controller.signal
        timeoutId = setTimeout(() => {
          try {
            controller.abort()
          } catch (e) {
            /* 忽略 */
          }
        }, POLL_CONFIG_TIMEOUT_MS)
      }

      const response = await fetch(SERVER_URL + '/api/get-feedback-prompts', options)
      if (!response.ok) return feedbackPrompts

      const payload = await response.json()
      if (payload && payload.status === 'success' && payload.config) {
        feedbackPrompts = {
          resubmit_prompt: payload.config.resubmit_prompt || feedbackPrompts.resubmit_prompt,
          prompt_suffix: payload.config.prompt_suffix || feedbackPrompts.prompt_suffix
        }
      }
    } catch (e) {
      log('获取反馈提示语失败，使用缓存值: ' + (e && e.message ? e.message : String(e)))
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
    }
    return feedbackPrompts
  }

  function buildMarkdownCodeFence(code, lang) {
    try {
      const normalized = String(code || '').replace(/\r\n?/g, '\n')
      if (!normalized.trim()) return null

      // 注意：此文件的 HTML 由外层模板字符串拼接，避免把反引号字符写进 HTML 源码（可能触发 Webview 注入失败）
      const BACKTICK = String.fromCharCode(96)
      const runs = normalized.match(/`+/g) || []
      const longestRun = runs.reduce((max, run) => Math.max(max, run.length), 0)
      const fence = BACKTICK.repeat(Math.max(3, longestRun + 1))
      const fenceHead = lang ? fence + String(lang) : fence
      const codeBody = normalized.endsWith('\n') ? normalized : normalized + '\n'

      return fenceHead + '\n' + codeBody + fence
    } catch (e) {
      return null
    }
  }

  // 插入剪贴板代码：在光标处插入 fenced code block（对齐“插入代码”按钮预期）
  function insertCodeBlockIntoFeedbackTextarea(code, lang) {
    try {
      const textarea = document.getElementById('feedbackText')
      if (!textarea) return false

      const codeBlockBody = buildMarkdownCodeFence(code, lang)
      if (!codeBlockBody) return false

      let cursorPos = 0
      try {
        cursorPos = typeof textarea.selectionStart === 'number' ? textarea.selectionStart : 0
      } catch (e) {
        cursorPos = 0
      }

      const value = textarea.value || ''
      const before = value.slice(0, cursorPos)
      const after = value.slice(cursorPos)
      const needsLeadingNewline = cursorPos > 0 && !before.endsWith('\n')
      const needsTrailingNewline = after.length > 0 && !after.startsWith('\n')
      const codeBlock =
        (needsLeadingNewline ? '\n' : '') + codeBlockBody + (needsTrailingNewline ? '\n' : '')

      textarea.value = before + codeBlock + after

      const newCursor = before.length + codeBlock.length
      try {
        textarea.setSelectionRange(newCursor, newCursor)
        textarea.focus()
      } catch (e) {
        // 忽略
      }

      // 程序写入不会触发 input 事件：手动同步到任务缓存
      if (activeTaskId && typeof taskTextareaContents !== 'undefined') {
        taskTextareaContents[activeTaskId] = textarea.value || ''
      }
      autoResizeFeedbackTextarea(textarea)
      schedulePersistUiState()
      return true
    } catch (e) {
      return false
    }
  }

  function setInsertCodeBtnDisabled(disabled) {
    const btn = document.getElementById('insertCodeBtn')
    if (btn) btn.disabled = !!disabled
  }

  function requestInsertCodeFromClipboard() {
    // 防止短时间重复点击
    if (clipboardRequestId) return
    clipboardRequestId = String(Date.now()) + '-' + Math.random().toString(16).slice(2)
    setInsertCodeBtnDisabled(true)
    vscode.postMessage({ type: 'requestClipboardText', requestId: clipboardRequestId })

    // 兜底：避免异常情况下按钮永久禁用
    setTimeout(() => {
      if (clipboardRequestId) {
        clipboardRequestId = null
        setInsertCodeBtnDisabled(false)
      }
    }, 2000)
  }

  function handleClipboardTextMessage(message) {
    try {
      const ok = !!(message && message.success)
      const text = message && message.text ? String(message.text) : ''

      const reqId = message && message.requestId ? String(message.requestId) : ''
      if (clipboardRequestId && (!reqId || reqId === clipboardRequestId)) {
        clipboardRequestId = null
        setInsertCodeBtnDisabled(false)
      }

      if (!ok || !text.trim()) {
        const err =
          message && message.error ? String(message.error) : '剪贴板为空，请先复制一段代码。'
        vscode.postMessage({ type: 'showInfo', message: err })
        return
      }

      const inserted = insertCodeBlockIntoFeedbackTextarea(text, '')
      if (!inserted) {
        vscode.postMessage({ type: 'showInfo', message: '插入失败：未检测到有效代码' })
        return
      }

      vscode.postMessage({ type: 'showInfo', message: '已插入剪贴板内容' })
    } catch (e) {
      vscode.postMessage({
        type: 'showInfo',
        message: '插入代码失败：' + (e && e.message ? e.message : String(e))
      })
      clipboardRequestId = null
      setInsertCodeBtnDisabled(false)
    }
  }

  /* 初始化函数 */
  async function init() {
    installHostThemeObserver()
    setupEventListeners()
    // 默认先标记为未连接，避免长时间停留在“连接中...”的误导状态
    updateServerStatus(false)
    // 无内容页默认展示：先显示轻量占位（动画仅在 showNoContent 时懒加载）

    // 不阻塞 UI：并行检查服务器状态（避免 await 网络请求导致 init 卡死）
    Promise.resolve()
      .then(() => checkServerStatus())
      .then(ok => {
        if (!ok) {
          hideTabs()
          showNoContent()
        }
      })
      .catch(() => {
        hideTabs()
        showNoContent()
      })
    startPolling()

    // 通知配置：低优先级预取（首屏不阻塞；避免把设置面板逻辑打进关键路径）
    scheduleLowPriorityWork(() => {
      Promise.resolve()
        .then(() => ensureNotifyCoreLoaded())
        .then(ok => {
          if (!ok) return
          const mod = getNotifyCoreModule()
          if (mod && typeof mod.refreshNotificationSettingsFromServer === 'function') {
            return mod.refreshNotificationSettingsFromServer({ force: true, silent: true })
          }
        })
        .catch(() => {
          /* 忽略 */
        })
    }, 1200)

    // Watchdog：兜底防止任何情况下长期停在 loading
    setTimeout(() => {
      try {
        const loading = document.getElementById('loadingState')
        const noContent = document.getElementById('noContentState')
        const form = document.getElementById('feedbackForm')
        if (!loading || !noContent || !form) return
        const isLoadingVisible = !loading.classList.contains('hidden')
        const isNoContentHidden = noContent.classList.contains('hidden')
        const isFormHidden = form.classList.contains('hidden')
        if (isLoadingVisible && isNoContentHidden && isFormHidden) {
          hideTabs()
          showNoContent()
        }
      } catch (e) {
        // 忽略
      }
    }, 3000)
    vscode.postMessage({ type: 'ready' })
  }

  /* 设置所有UI元素的事件监听器 - 包括按钮点击、图片上传、文本框调整等 */
  function setupEventListeners() {
    try {
      /* 提交按钮点击事件 */
      const submitBtn = document.getElementById('submitBtn')
      if (submitBtn) {
        if (submitBtnDefaultHtml === null) {
          submitBtnDefaultHtml = submitBtn.innerHTML
        }
        submitBtn.addEventListener('click', submitFeedback)
      }

      /* 插入代码（剪贴板） */
      const insertCodeBtn = document.getElementById('insertCodeBtn')
      if (insertCodeBtn) {
        insertCodeBtn.addEventListener('click', requestInsertCodeFromClipboard)
      }

      /* 图片上传按钮点击事件 */
      const uploadBtn = document.getElementById('uploadBtn')
      const imageInput = document.getElementById('imageInput')

      if (uploadBtn && imageInput) {
        uploadBtn.addEventListener('click', () => {
          imageInput.click()
        })
        imageInput.addEventListener('change', handleImageSelect)
      }

      /* 文本框粘贴图片支持 - 允许用户通过Ctrl+V粘贴图片 */
      const textarea = document.getElementById('feedbackText')
      if (textarea) {
        textarea.addEventListener('paste', handlePaste)
        // 【对齐原始实现】实时保存 textarea 内容，避免轮询/切换导致内容丢失或串任务
        textarea.addEventListener('input', () => {
          if (activeTaskId) {
            taskTextareaContents[activeTaskId] = textarea.value || ''
          }
          autoResizeFeedbackTextarea(textarea)
          schedulePersistUiState()
        })
        // 【体验对齐】Ctrl/Cmd + Enter 提交
        textarea.addEventListener('keydown', e => {
          const isMac = isMacLikePlatform()
          const ctrlOrCmd = isMac ? e.metaKey : e.ctrlKey
          const key = e && e.key ? String(e.key) : ''
          const isEnter = key === 'Enter' || key === 'NumpadEnter'
          if (e && e.isComposing) return
          if (ctrlOrCmd && isEnter) {
            e.preventDefault()
            submitFeedback()
          }
        })
        // 首次加载：根据内容自动撑开
        autoResizeFeedbackTextarea(textarea)
      }

      // 【对齐原始实现】实时保存选项勾选状态（事件委托，避免重建DOM后丢监听）
      const optionsContainerEl = document.getElementById('optionsContainer')
      if (optionsContainerEl) {
        optionsContainerEl.addEventListener('change', e => {
          if (!activeTaskId) return
          const checkboxes = optionsContainerEl.querySelectorAll('input[type="checkbox"]')
          const states = {}
          checkboxes.forEach((cb, index) => {
            states[index] = !!cb.checked
          })
          taskOptionsStates[activeTaskId] = states
          schedulePersistUiState()
        })
      }

      /* 设置面板（通知配置） */
      const settingsBtn = document.getElementById('settingsBtn')
      if (settingsBtn) {
        settingsBtn.addEventListener('click', openSettingsLazy)
      }
      const settingsBtnNoContent = document.getElementById('settingsBtnNoContent')
      if (settingsBtnNoContent) {
        settingsBtnNoContent.addEventListener('click', openSettingsLazy)
      }

      /* 文本框高度调整句柄 - 支持向上拖动扩展文本框高度 */
      const resizeHandle = document.getElementById('resizeHandle')
      let isResizing = false
      let startY = 0
      let startRows = 0
      let resizeLineHeight = 20
      let resizeMinRows = 2
      let resizeMaxRows = 20

      if (resizeHandle && textarea) {
        resizeHandle.addEventListener('mousedown', e => {
          isResizing = true
          startY = e.clientY
          const bounds = getTextareaRowsBounds(textarea)
          resizeLineHeight = bounds.lineHeight
          resizeMinRows = bounds.minRows
          resizeMaxRows = bounds.maxRows
          startRows = textarea.rows || bounds.minRows
          e.preventDefault()
        })
        // 双击：重置手动高度（回到 Auto-resize）
        resizeHandle.addEventListener('dblclick', e => {
          textareaManualRows = null
          autoResizeFeedbackTextarea(textarea)
          schedulePersistUiState()
          e.preventDefault()
        })
      }

      document.addEventListener('mousemove', e => {
        if (!isResizing || !textarea) return

        /* 计算拖动距离 - 向上拖动时增加文本框高度（rows 驱动） */
        const deltaY = startY - e.clientY
        const perRow = resizeLineHeight || 20
        const deltaRows = Math.round(deltaY / perRow)
        const nextRows = clampInt(startRows + deltaRows, resizeMinRows, resizeMaxRows)
        textarea.rows = nextRows
        textareaManualRows = nextRows
      })

      document.addEventListener('mouseup', () => {
        isResizing = false
        if (textarea) {
          schedulePersistUiState()
        }
      })

      log('事件监听器已设置')
    } catch (error) {
      logError('设置事件监听器失败: ' + error.message)
    }
  }

  /* 检查服务器连接状态 - 向本地服务器发送健康检查请求 */
  async function checkServerStatus() {
    let controller = null
    let timeoutId = null
    try {
      const fetchOptions = {
        method: 'GET',
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      }

      // 超时保护：避免 fetch 一直 pending 导致 UI 卡在“连接中”
      if (typeof AbortController !== 'undefined') {
        controller = new AbortController()
        fetchOptions.signal = controller.signal
        timeoutId = setTimeout(() => {
          try {
            controller.abort()
          } catch (e) {
            /* 忽略 */
          }
        }, SERVER_STATUS_TIMEOUT_MS)
      }

      const response = await fetch(SERVER_URL + '/api/config', fetchOptions)

      if (response.ok) {
        updateServerStatus(true)
        return true
      } else {
        updateServerStatus(false)
        return false
      }
    } catch (error) {
      const msg =
        error && error.name === 'AbortError'
          ? '请求超时'
          : error && error.message
            ? error.message
            : String(error)
      logError('服务器连接失败: ' + msg)
      updateServerStatus(false)
      return false
    } finally {
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
    }
  }

  /* 更新UI中的服务器连接状态指示器 - 同步更新标签栏和无内容页面的状态灯 */
  function updateServerStatus(connected) {
    // 状态变化时给出轻量提示（避免无声重试/用户误以为无响应）
    if (typeof updateServerStatus._last === 'boolean' && updateServerStatus._last !== !!connected) {
      showToast(connected ? '已连接' : '连接断开，正在重试…', {
        kind: connected ? 'success' : 'warn',
        timeoutMs: 1600,
        dedupeKey: connected ? 'net:up' : 'net:down'
      })
    }
    updateServerStatus._last = !!connected

    /* 更新标签栏的连接状态呼吸灯 */
    const light = document.getElementById('statusLight')
    if (light) {
      light.classList.remove('connected', 'disconnected')
      if (connected) {
        light.classList.add('connected')
        light.title = '服务器已连接'
      } else {
        light.classList.add('disconnected')
        light.title = '服务器连接断开'
      }
    }

    /* 更新无内容页面的独立状态指示器和文字 */
    const lightStandalone = document.getElementById('statusLightStandalone')
    const textStandalone = document.getElementById('statusTextStandalone')
    const progressBar = document.getElementById('noContentProgress')

    if (lightStandalone) {
      lightStandalone.classList.remove('connected', 'disconnected')
      if (connected) {
        lightStandalone.classList.add('connected')
        lightStandalone.title = '服务器已连接'
      } else {
        lightStandalone.classList.add('disconnected')
        lightStandalone.title = '服务器连接断开'
      }
    }

    if (textStandalone) {
      textStandalone.textContent = connected ? '已连接' : '连接断开'
    }

    /* 只在服务器已连接时显示加载进度条 */
    if (progressBar) {
      if (connected) {
        progressBar.classList.remove('hidden')
      } else {
        progressBar.classList.add('hidden')
      }
    }

    vscode.postMessage({ type: 'serverStatus', connected })
  }

  /* 启动轮询（治理：不可见暂停/指数退避/AbortController） */
  function startPolling() {
    stopPolling()
    installPollingVisibilityHandler()
    pollingEnabled = true
    pollingToken = pollingToken + 1
    const token = pollingToken
    pollBackoffMs = POLL_BASE_MS
    scheduleNextPoll(0, token)
  }

  function scheduleNextPoll(delayMs, token) {
    const t = typeof token === 'number' && Number.isFinite(token) ? token : pollingToken
    if (!pollingEnabled) return
    if (t !== pollingToken) return
    if (pollingTimer) {
      clearTimeout(pollingTimer)
      pollingTimer = null
    }
    pollingTimer = setTimeout(
      async () => {
        if (!pollingEnabled) return
        if (t !== pollingToken) return
        const ok = await pollAllData('poll')
        if (!pollingEnabled) return
        if (t !== pollingToken) return
        const suggested =
          typeof pollSuggestedDelayMs === 'number' && Number.isFinite(pollSuggestedDelayMs)
            ? Math.max(0, Math.floor(pollSuggestedDelayMs))
            : null
        pollSuggestedDelayMs = null
        if (ok) {
          pollBackoffMs = suggested !== null ? Math.min(POLL_MAX_MS, suggested) : POLL_BASE_MS
        } else {
          pollBackoffMs = getNextBackoffMs(pollBackoffMs)
        }
        scheduleNextPoll(pollBackoffMs, t)
      },
      Math.max(0, delayMs)
    )
  }

  function stopPolling() {
    pollingEnabled = false
    pollingToken = pollingToken + 1
    if (pollingTimer) {
      clearTimeout(pollingTimer)
      pollingTimer = null
    }
    // 取消 in-flight 请求，避免页面切走/重启轮询时堆积
    try {
      if (pollAbortController && typeof pollAbortController.abort === 'function') {
        pollAbortController.abort()
      }
    } catch (e) {
      // 忽略
    } finally {
      pollAbortController = null
    }
    pollingInFlight = false
  }

  /* 轮询服务器数据 - 获取任务列表并渲染标签页，然后获取当前活跃任务的详细内容 */
  async function pollAllData(reason) {
    // 页面不可见：不发请求（由 visibilitychange 负责 stop，但这里再兜底）
    if (typeof document !== 'undefined' && document.hidden) {
      return false
    }

    // 防重叠：同一时间最多 1 个 in-flight
    if (pollingInFlight) {
      return false
    }
    pollingInFlight = true
    let tasksTimeoutId = null
    let configTimeoutId = null

    try {
      // AbortController：保证同时最多 1 个 in-flight 的 /api/tasks 请求
      try {
        if (pollAbortController && typeof pollAbortController.abort === 'function') {
          pollAbortController.abort()
        }
      } catch (e) {
        // 忽略
      }

      if (typeof AbortController !== 'undefined') {
        pollAbortController = new AbortController()
      } else {
        pollAbortController = null
      }

      const fetchOptions = { cache: 'no-store' }
      if (pollAbortController) {
        fetchOptions.signal = pollAbortController.signal
      }

      /* 第一步：获取所有任务列表 */
      if (pollAbortController) {
        tasksTimeoutId = setTimeout(() => {
          try {
            pollAbortController.abort()
          } catch (e) {
            /* 忽略 */
          }
        }, POLL_TASKS_TIMEOUT_MS)
      }
      const tasksResponse = await fetch(SERVER_URL + '/api/tasks', fetchOptions)
      if (tasksTimeoutId) {
        clearTimeout(tasksTimeoutId)
        tasksTimeoutId = null
      }

      if (!tasksResponse.ok) {
        updateServerStatus(false)
        hideTabs()
        showNoContent()
        return false
      }

      updateServerStatus(true)
      const tasksData = await tasksResponse.json()

      // 同步服务器时间偏移，避免倒计时漂移
      if (tasksData && typeof tasksData.server_time === 'number') {
        const localTime = Date.now() / 1000
        serverTimeOffset = tasksData.server_time - localTime
      }

      // 同步 deadline / remaining_time（权威来自服务端）
      if (tasksData && tasksData.tasks && Array.isArray(tasksData.tasks)) {
        tasksData.tasks.forEach(t => {
          if (!t || !t.task_id) return
          if (typeof t.deadline === 'number') {
            taskDeadlines[t.task_id] = t.deadline
          }
          if (typeof t.remaining_time === 'number') {
            tabCountdownRemaining[t.task_id] = Math.max(0, Math.floor(t.remaining_time))
          }
        })
      }

      // 同步 stats 给 Extension：状态栏可直接复用，避免 Webview 可见时重复 /api/tasks 轮询
      try {
        const stats = tasksData && tasksData.stats ? tasksData.stats : null
        if (stats) {
          const active = typeof stats.active === 'number' ? stats.active : 0
          const pending = typeof stats.pending === 'number' ? stats.pending : 0
          const total =
            typeof stats.total === 'number' && Number.isFinite(stats.total) ? stats.total : active + pending
          vscode.postMessage({
            type: 'tasksStats',
            connected: !!(tasksData && tasksData.success),
            active,
            pending,
            total
          })
        }
      } catch (e) {
        // 忽略：消息派发失败不应影响轮询主流程
      }

      if (tasksData && tasksData.success && tasksData.tasks && tasksData.tasks.length > 0) {
        allTasks = tasksData.tasks
        renderTaskTabs()

        // 先同步一次 activeTaskId（/api/config 会返回权威 task_id）
        const activeTask = allTasks.find(t => t && t.status === 'active')
        if (activeTask && activeTask.task_id) {
          activeTaskId = activeTask.task_id
        }

        // 获取活跃任务的详细内容并更新UI（服务端会自动激活第一个 pending 任务）
        // 为 /api/config 创建独立 AbortController，避免 /api/tasks 的超时/abort 影响后续请求
        if (typeof AbortController !== 'undefined') {
          try {
            pollAbortController = new AbortController()
            fetchOptions.signal = pollAbortController.signal
          } catch (e) {
            pollAbortController = null
            try {
              delete fetchOptions.signal
            } catch (e2) {
              // 忽略
            }
          }
        } else {
          pollAbortController = null
          try {
            delete fetchOptions.signal
          } catch (e) {
            // 忽略
          }
        }
        if (pollAbortController) {
          configTimeoutId = setTimeout(() => {
            try {
              pollAbortController.abort()
            } catch (e) {
              /* 忽略 */
            }
          }, POLL_CONFIG_TIMEOUT_MS)
        }
        const okConfig = await pollConfig(fetchOptions)
        if (configTimeoutId) {
          clearTimeout(configTimeoutId)
          configTimeoutId = null
        }
        return !!okConfig
      }

      // 任务列表为空或 success=false
      allTasks = []
      activeTaskId = null
      clearAllTabCountdowns()
      taskDeadlines = {}
      taskTextareaContents = {}
      taskOptionsStates = {}
      taskImages = {}
      schedulePersistUiState()
      lastTasksHash = ''
      lastTaskIds = new Set()
      if (tasksData && tasksData.success) {
        hasInitializedTaskIdTracking = true
      }
      hideTabs()
      showNoContent()

      // 空闲态降频（加少量抖动，避免多客户端齐刷刷打点）
      try {
        const jitter = Math.round(POLL_IDLE_MS * 0.15 * Math.random())
        pollSuggestedDelayMs = POLL_IDLE_MS + jitter
      } catch (e) {
        pollSuggestedDelayMs = POLL_IDLE_MS
      }

      // success=true 且 tasks=[] 属于正常“无任务”状态，不需要退避
      return !!(tasksData && tasksData.success)
    } catch (error) {
      if (error && (error.name === 'AbortError' || error.code === 20)) {
        return false
      }
      logError('轮询失败: ' + error.message)
      updateServerStatus(false)
      allTasks = []
      activeTaskId = null
      hideTabs()
      showNoContent()
      return false
    } finally {
      if (tasksTimeoutId) {
        clearTimeout(tasksTimeoutId)
      }
      if (configTimeoutId) {
        clearTimeout(configTimeoutId)
      }
      pollingInFlight = false
      pollAbortController = null
    }
  }

  /* 隐藏任务标签栏 - 当没有任务或只有一个任务时隐藏标签栏 */
  function hideTabs() {
    const container = document.getElementById('tasksTabsContainer')
    if (!container) return
    const existingTabs = container.querySelectorAll('.task-tab')
    existingTabs.forEach(tab => tab.remove())
    container.classList.add('hidden')
  }

  /* 显示任务标签栏 - 当有多个任务时显示标签栏供用户切换 */
  function showTabs() {
    document.getElementById('tasksTabsContainer').classList.remove('hidden')
  }

  function requestImmediateRefresh() {
    // 页面不可见时不强行刷新
    if (typeof document !== 'undefined' && document.hidden) {
      return
    }
    pollBackoffMs = POLL_BASE_MS
    if (!pollingEnabled) {
      startPolling()
      return
    }
    scheduleNextPoll(0, pollingToken)
  }

  function getAdjustedNowSeconds() {
    return Date.now() / 1000 + (serverTimeOffset || 0)
  }

  function computeRemainingForTask(task) {
    try {
      if (task && typeof task.remaining_time === 'number') {
        return Math.max(0, Math.floor(task.remaining_time))
      }
      if (task && task.task_id && typeof taskDeadlines[task.task_id] === 'number') {
        return Math.max(0, Math.floor(taskDeadlines[task.task_id] - getAdjustedNowSeconds()))
      }
      if (task && task.task_id && typeof tabCountdownRemaining[task.task_id] === 'number') {
        return Math.max(0, Math.floor(tabCountdownRemaining[task.task_id]))
      }
      if (task && typeof task.auto_resubmit_timeout === 'number') {
        return Math.max(0, Math.floor(task.auto_resubmit_timeout))
      }
    } catch (e) {
      // 忽略
    }
    return 0
  }

  function saveLocalStateForTask(taskId) {
    if (!taskId) return
    try {
      const textarea = document.getElementById('feedbackText')
      if (textarea) {
        taskTextareaContents[taskId] = textarea.value || ''
      }

      const optionsContainer = document.getElementById('optionsContainer')
      if (optionsContainer) {
        const states = {}
        const checkboxes = optionsContainer.querySelectorAll('input[type="checkbox"]')
        checkboxes.forEach((cb, index) => {
          states[index] = !!cb.checked
        })
        // 即使没有选项，也保存为空对象，避免切换回来时继承旧状态
        taskOptionsStates[taskId] = states
      }

      if (Array.isArray(uploadedImages)) {
        taskImages[taskId] = uploadedImages
          .map(img => ({
            name: img && img.name ? String(img.name) : 'image',
            data: img && img.data ? String(img.data) : ''
          }))
          .filter(x => x.data)
      }
    } catch (e) {
      // 忽略
    }
  }

  function restoreLocalStateForTask(taskId) {
    if (!taskId) return
    try {
      const textarea = document.getElementById('feedbackText')
      if (textarea) {
        textarea.value = taskTextareaContents[taskId] || ''
        autoResizeFeedbackTextarea(textarea)
      }

      // 恢复图片（使用 dataURL，不依赖 blob:，避免 CSP 额外放行）
      uploadedImages = (taskImages[taskId] || [])
        .map(img => ({
          name: img && img.name ? String(img.name) : 'image',
          data: img && img.data ? String(img.data) : ''
        }))
        .filter(x => x.data)
      renderUploadedImages()
    } catch (e) {
      // 忽略
    }
  }

  function syncImagesToTaskCache(taskId) {
    if (!taskId) return
    try {
      taskImages[taskId] = (uploadedImages || [])
        .map(img => ({
          name: img && img.name ? String(img.name) : 'image',
          data: img && img.data ? String(img.data) : ''
        }))
        .filter(x => x.data)
    } catch (e) {
      // 忽略
    }
  }

  /* 渲染任务标签栏 - 根据服务器返回的任务列表动态生成标签页DOM */
  function renderTaskTabs() {
    const container = document.getElementById('tasksTabsContainer')

    if (!allTasks || allTasks.length === 0) {
      hideTabs()
      lastTasksHash = ''
      clearAllTabCountdowns()
      return
    }

    /* 计算任务列表的哈希值用于检测任务列表是否发生变化 */
    const currentHash = allTasks.map(t => t.task_id + ':' + t.status).join('|')

    /* 检测是否有新任务加入 */
    const currentTaskIds = new Set(allTasks.map(t => t.task_id))
    const newTasks = allTasks.filter(t => !lastTaskIds.has(t.task_id))

    /* 当检测到新任务时显示通知提示 */
    if (newTasks.length > 0 && hasInitializedTaskIdTracking) {
      const ids = newTasks.map(task => task.task_id).filter(Boolean)
      notifyNewTasks(ids)
    }

    lastTaskIds = currentTaskIds
    hasInitializedTaskIdTracking = true

    /* 任务列表未变化时仅更新倒计时 + active 状态，避免不必要的DOM重建 */
    if (currentHash === lastTasksHash) {
      updateTabCountdowns()
      // 只有当“本地已选择 activeTaskId”（例如用户点了标签）时，才覆盖 tab 的 active 样式；
      // 否则保持后端上报的 active 状态，避免初始渲染时把 active 清空。
      if (activeTaskId) {
        try {
          const tabs = container.querySelectorAll('.task-tab')
          tabs.forEach(tab => {
            const id = tab && tab.dataset ? tab.dataset.taskId : ''
            const shouldActive = !!(id && id === activeTaskId)
            tab.classList.toggle('active', shouldActive)
            const dot = tab.querySelector('.task-tab-status')
            if (dot) {
              if (shouldActive) {
                dot.classList.remove('pending', 'active', 'completed')
                dot.classList.add('active')
              } else if (dot.classList.contains('active')) {
                // UI 切换后：旧 active 点回退为 pending（直到后端同步完成）
                dot.classList.remove('active')
                if (!dot.classList.contains('pending')) {
                  dot.classList.add('pending')
                }
              }
            }
          })
        } catch (e) {
          // 忽略
        }
      }
      return
    }

    lastTasksHash = currentHash
    showTabs()

    /* 清除现有的所有任务标签，保留连接状态指示器 */
    const existingTabs = container.querySelectorAll('.task-tab')
    existingTabs.forEach(tab => tab.remove())

    /* 过滤已完成的任务，只显示进行中和等待中的任务 */
    const activeTasks = allTasks.filter(task => task.status !== 'completed')
    const activeTaskIdSet = new Set(activeTasks.map(t => t.task_id))
    // 清理不再存在/已完成任务的倒计时定时器，避免内存泄漏
    let removedAnyTaskCache = false
    Object.keys(tabCountdownTimers).forEach(existingId => {
      if (!activeTaskIdSet.has(existingId)) {
        removedAnyTaskCache = true
        try {
          clearInterval(tabCountdownTimers[existingId])
        } catch (e) {
          // 忽略
        }
        delete tabCountdownTimers[existingId]
        delete tabCountdownRemaining[existingId]
        if (taskDeadlines[existingId] !== undefined) {
          delete taskDeadlines[existingId]
        }
        if (taskTextareaContents[existingId] !== undefined) {
          delete taskTextareaContents[existingId]
        }
        if (taskOptionsStates[existingId] !== undefined) {
          delete taskOptionsStates[existingId]
        }
        if (taskImages[existingId] !== undefined) {
          delete taskImages[existingId]
        }
      }
    })
    if (removedAnyTaskCache) {
      schedulePersistUiState()
    }

    activeTasks.forEach(task => {
      const tab = document.createElement('div')
      tab.className = 'task-tab'
      tab.dataset.taskId = task.task_id

      const isUiActive = !!(activeTaskId && task.task_id && task.task_id === activeTaskId)
      if (isUiActive || task.status === 'active') {
        tab.classList.add('active')
      }

      const statusDot = document.createElement('div')
      statusDot.className = 'task-tab-status'
      statusDot.classList.add(
        isUiActive || task.status === 'active' ? 'active' : task.status || 'pending'
      )
      tab.appendChild(statusDot)

      const taskId = document.createElement('div')
      taskId.className = 'task-tab-id'
      taskId.textContent = task.task_id
      taskId.title = task.task_id // 完整ID作为tooltip

      tab.appendChild(taskId)

      /* 为设置了自动重调超时的任务添加倒计时圆环显示 */
      if (task.auto_resubmit_timeout > 0) {
        const countdown = document.createElement('div')
        countdown.className = 'task-tab-countdown'
        countdown.id = 'tab-countdown-' + task.task_id

        const radius = 9 // 与服务端一致
        const circumference = 2 * Math.PI * radius

        /* 使用缓存的剩余时间或完整超时时间初始化倒计时 */
        const remaining = computeRemainingForTask(task)
        tabCountdownRemaining[task.task_id] = remaining
        const progress = remaining / task.auto_resubmit_timeout
        const offset = circumference * (1 - progress)

        countdown.innerHTML =
          '<svg width="22" height="22" viewBox="0 0 22 22">' +
          '<circle id="tab-countdown-progress-' +
          task.task_id +
          '" ' +
          'cx="11" cy="11" r="' +
          radius +
          '" ' +
          'stroke-dasharray="' +
          circumference +
          '" ' +
          'stroke-dashoffset="' +
          offset +
          '" /></svg>' +
          '<span class="task-tab-countdown-number" id="tab-countdown-text-' +
          task.task_id +
          '">' +
          remaining +
          '</span>'

        countdown.title = '剩余' + remaining + '秒'
        tab.appendChild(countdown)

        /* 避免重复启动定时器 - 只在倒计时未运行时启动 */
        if (!tabCountdownTimers[task.task_id]) {
          startTabCountdown(task.task_id, task.auto_resubmit_timeout, remaining)
        }
      }

      /* 标签点击事件 - 切换到对应任务 */
      tab.addEventListener('click', () => switchToTask(task.task_id))

      container.appendChild(tab)
    })

    log('渲染了 ' + activeTasks.length + ' 个任务标签（已过滤掉已完成任务）')
  }

  /* 切换活跃任务 - 将指定任务设置为当前活跃任务并刷新UI */
  async function switchToTask(taskId) {
    if (taskId === activeTaskId) {
      log('任务已经是active状态: ' + taskId)
      return
    }

    try {
      // 【对齐原始实现】切换前保存当前任务的输入/选项/图片，避免串任务
      const prevTaskId = activeTaskId || (currentConfig && currentConfig.task_id)
      if (prevTaskId) {
        saveLocalStateForTask(prevTaskId)
      }

      log('切换到任务: ' + taskId)
      // 先做本地 UI 立即切换（无网络延迟），再与服务端同步 active_task
      activeTaskId = taskId
      restoreLocalStateForTask(taskId)
      showToast('切换到任务: ' + taskId, {
        kind: 'info',
        timeoutMs: 1200,
        dedupeKey: 'switch:' + taskId
      })
      // 立即更新 tabs 的选中态（无需等待下一轮轮询）
      try {
        const tabs = document.querySelectorAll('#tasksTabsContainer .task-tab')
        tabs.forEach(tab => {
          const id = tab && tab.dataset ? tab.dataset.taskId : ''
          const isActive = !!(id && id === taskId)
          tab.classList.toggle('active', isActive)
          const dot = tab.querySelector('.task-tab-status')
          if (dot) {
            if (isActive) {
              dot.classList.remove('pending', 'active', 'completed')
              dot.classList.add('active')
            } else if (dot.classList.contains('active')) {
              dot.classList.remove('active')
              if (!dot.classList.contains('pending')) {
                dot.classList.add('pending')
              }
            }
          }
        })
      } catch (e) {
        // 忽略
      }

      const response = await fetch(
        SERVER_URL + '/api/tasks/' + encodeURIComponent(taskId) + '/activate',
        {
          method: 'POST'
        }
      )

      if (response.ok) {
        log('任务已激活: ' + taskId)
        requestImmediateRefresh()
      } else {
        logError('激活任务失败: HTTP ' + response.status)
        vscode.postMessage({
          type: 'showInfo',
          message: '切换任务失败：' + taskId
        })
        // 回滚 UI
        if (prevTaskId) {
          activeTaskId = prevTaskId
          restoreLocalStateForTask(prevTaskId)
          try {
            const tabs = document.querySelectorAll('#tasksTabsContainer .task-tab')
            tabs.forEach(tab => {
              const id = tab && tab.dataset ? tab.dataset.taskId : ''
              const isActive = !!(id && id === prevTaskId)
              tab.classList.toggle('active', isActive)
              const dot = tab.querySelector('.task-tab-status')
              if (dot) {
                if (isActive) {
                  dot.classList.remove('pending', 'active', 'completed')
                  dot.classList.add('active')
                } else if (dot.classList.contains('active')) {
                  dot.classList.remove('active')
                  if (!dot.classList.contains('pending')) {
                    dot.classList.add('pending')
                  }
                }
              }
            })
          } catch (e) {
            // 忽略
          }
        }
      }
    } catch (error) {
      logError('激活任务失败: ' + error.message)
      vscode.postMessage({
        type: 'showInfo',
        message: '切换任务失败：' + error.message
      })
      // 回滚 UI（尽力而为）
      try {
        const prevTaskId = currentConfig && currentConfig.task_id ? currentConfig.task_id : null
        if (prevTaskId) {
          activeTaskId = prevTaskId
          restoreLocalStateForTask(prevTaskId)
          try {
            const tabs = document.querySelectorAll('#tasksTabsContainer .task-tab')
            tabs.forEach(tab => {
              const id = tab && tab.dataset ? tab.dataset.taskId : ''
              const isActive = !!(id && id === prevTaskId)
              tab.classList.toggle('active', isActive)
              const dot = tab.querySelector('.task-tab-status')
              if (dot) {
                if (isActive) {
                  dot.classList.remove('pending', 'active', 'completed')
                  dot.classList.add('active')
                } else if (dot.classList.contains('active')) {
                  dot.classList.remove('active')
                  if (!dot.classList.contains('pending')) {
                    dot.classList.add('pending')
                  }
                }
              }
            })
          } catch (e) {
            // 忽略
          }
        }
      } catch (e) {
        // 忽略
      }
    }
  }

  /* 启动任务标签的倒计时圆环动画 - 使用SVG圆环和数字显示剩余时间 */
  function startTabCountdown(taskId, totalSeconds, initialRemaining = null) {
    let remaining = initialRemaining !== null ? initialRemaining : totalSeconds
    const radius = 9 // 与服务端一致
    const circumference = 2 * Math.PI * radius

    const progressCircle = document.getElementById('tab-countdown-progress-' + taskId)
    const numberSpan = document.getElementById('tab-countdown-text-' + taskId)
    const countdownRing = document.getElementById('tab-countdown-' + taskId)

    if (!progressCircle || !numberSpan) return

    function update() {
      // 优先使用 deadline 计算（避免后台节流导致倒计时不准）
      const deadline = typeof taskDeadlines[taskId] === 'number' ? taskDeadlines[taskId] : null
      const computedRemaining = deadline
        ? Math.max(0, Math.floor(deadline - getAdjustedNowSeconds()))
        : Math.max(0, remaining)

      if (computedRemaining <= 0) {
        if (tabCountdownTimers[taskId]) {
          clearInterval(tabCountdownTimers[taskId])
          delete tabCountdownTimers[taskId]
          delete tabCountdownRemaining[taskId]
        }
        return
      }

      const progress = computedRemaining / totalSeconds
      const offset = circumference * (1 - progress)

      progressCircle.setAttribute('stroke-dashoffset', offset)
      numberSpan.textContent = computedRemaining // 只显示数字，无"s"

      if (countdownRing) {
        countdownRing.title = '剩余' + computedRemaining + '秒'
      }

      /* 缓存剩余时间用于任务切换时保持倒计时连续性 */
      tabCountdownRemaining[taskId] = computedRemaining

      // 没有 deadline 时才使用递减方式（向后兼容）
      if (!deadline) {
        remaining = computedRemaining - 1
      }
    }

    /* 立即执行第一次更新 */
    update()

    /* 清除该任务的旧定时器，避免重复计时 */
    if (tabCountdownTimers[taskId]) {
      clearInterval(tabCountdownTimers[taskId])
    }

    /* 启动新的定时器，每秒更新一次 */
    tabCountdownTimers[taskId] = setInterval(update, 1000)
  }

  /* 清除所有任务标签的倒计时定时器和缓存数据 */
  function clearAllTabCountdowns() {
    Object.keys(tabCountdownTimers).forEach(taskId => {
      clearInterval(tabCountdownTimers[taskId])
    })
    tabCountdownTimers = {}
    tabCountdownRemaining = {}
  }

  /* 更新所有任务标签的倒计时显示 - 仅更新数值，不重建DOM结构 */
  function updateTabCountdowns() {
    allTasks.forEach(task => {
      if (task.auto_resubmit_timeout > 0) {
        const progressCircle = document.getElementById('tab-countdown-progress-' + task.task_id)
        /* 检查倒计时元素和定时器状态，必要时启动倒计时 */
        if (progressCircle && !tabCountdownTimers[task.task_id]) {
          startTabCountdown(task.task_id, task.auto_resubmit_timeout, computeRemainingForTask(task))
        }
      }
    })
  }

  /* 获取当前活跃任务的详细配置 - 包括提示信息、选项和倒计时设置 */
  function pickFallbackTaskId() {
    try {
      if (activeTaskId) return String(activeTaskId)
    } catch (e) {
      // 忽略
    }
    try {
      if (Array.isArray(allTasks) && allTasks.length > 0) {
        const inc = allTasks.find(t => t && t.task_id && t.status !== 'completed')
        if (inc && inc.task_id) return String(inc.task_id)
      }
    } catch (e) {
      // 忽略
    }
    return ''
  }

  // 配置端点偶发超时/异常时，用任务详情兜底（避免 UI 卡在“无有效内容”）
  async function fetchTaskDetailAsConfig(taskId) {
    const id = taskId ? String(taskId) : ''
    if (!id) return null

    let timeoutId = null
    try {
      const options = { cache: 'no-store' }

      // 为兜底请求使用独立 AbortController（避免复用已 aborted 的 signal）
      if (typeof AbortController !== 'undefined') {
        try {
          const controller = new AbortController()
          options.signal = controller.signal
          timeoutId = setTimeout(() => {
            try {
              controller.abort()
            } catch (e) {
              /* 忽略 */
            }
          }, POLL_CONFIG_TIMEOUT_MS)
        } catch (e) {
          // 忽略
        }
      }

      const resp = await fetch(SERVER_URL + '/api/tasks/' + encodeURIComponent(id), options)
      if (!resp.ok) return null

      const data = await resp.json()
      if (!data || !data.success || !data.task) return null

      const t = data.task || {}
      const prompt = t.prompt ? String(t.prompt) : ''
      const predefined = Array.isArray(t.predefined_options) ? t.predefined_options : []
      return {
        prompt,
        prompt_html: '',
        predefined_options: predefined,
        task_id: t.task_id ? String(t.task_id) : id,
        auto_resubmit_timeout:
          typeof t.auto_resubmit_timeout === 'number' && Number.isFinite(t.auto_resubmit_timeout)
            ? Math.max(0, Math.floor(t.auto_resubmit_timeout))
            : 0,
        remaining_time:
          typeof t.remaining_time === 'number' && Number.isFinite(t.remaining_time)
            ? Math.max(0, Math.floor(t.remaining_time))
            : undefined,
        server_time:
          typeof data.server_time === 'number' && Number.isFinite(data.server_time)
            ? data.server_time
            : undefined,
        deadline:
          typeof t.deadline === 'number' && Number.isFinite(t.deadline) ? t.deadline : undefined,
        persistent: true,
        has_content: !!prompt,
        initial_empty: false
      }
    } catch (e) {
      return null
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
    }
  }

  async function pollConfig(fetchOptions) {
    const tryFallback = async reason => {
      const id = pickFallbackTaskId()
      if (!id) return false
      const fallback = await fetchTaskDetailAsConfig(id)
      if (!fallback || !fallback.has_content) return false
      try {
        if (typeof fallback.server_time === 'number') {
          const localTime = Date.now() / 1000
          serverTimeOffset = fallback.server_time - localTime
        }
      } catch (e) {
        // 忽略
      }
      try {
        if (fallback.task_id && typeof fallback.deadline === 'number') {
          taskDeadlines[fallback.task_id] = fallback.deadline
        }
      } catch (e) {
        // 忽略
      }
      try {
        if (fallback.task_id) {
          activeTaskId = fallback.task_id
        }
      } catch (e) {
        // 忽略
      }
      try {
        showToast('配置加载失败，已使用任务详情兜底' + (reason ? '（' + reason + '）' : ''), {
          kind: 'warn',
          timeoutMs: 1600,
          dedupeKey: 'config:fallback'
        })
      } catch (e) {
        // 忽略
      }
      updateUI(fallback)
      return true
    }

    try {
      const options = fetchOptions ? { ...fetchOptions } : { cache: 'no-store' }
      if (!options.cache) options.cache = 'no-store'
      const response = await fetch(SERVER_URL + '/api/config', options)

      if (!response.ok) {
        const okFallback = await tryFallback('HTTP ' + response.status)
        if (okFallback) return true
        if (!(currentConfig && currentConfig.has_content)) {
          showNoContent()
        }
        return false
      }

      const config = await response.json()

      /* 验证服务器返回的配置是否包含有效内容 */
      if (config && typeof config.server_time === 'number') {
        const localTime = Date.now() / 1000
        serverTimeOffset = config.server_time - localTime
      }
      if (config && config.task_id && typeof config.deadline === 'number') {
        taskDeadlines[config.task_id] = config.deadline
      }
      if (config && config.task_id) {
        activeTaskId = config.task_id
      }

      if (config.has_content && (config.prompt || config.prompt_html)) {
        updateUI(config)
      } else {
        // tasks 列表不为空但 config 无内容时，尝试用任务详情兜底（避免“有任务但显示无内容”）
        const hasIncomplete =
          Array.isArray(allTasks) && allTasks.some(t => t && t.task_id && t.status !== 'completed')
        if (hasIncomplete) {
          const okFallback = await tryFallback('no_content')
          if (okFallback) return true
        }
        showNoContent()
      }
      return true
    } catch (error) {
      if (error && (error.name === 'AbortError' || error.code === 20)) {
        // 页面隐藏/切走时 abort 属于正常行为：不强制切换 UI，避免闪烁
        try {
          if (typeof document !== 'undefined' && document.hidden) {
            return false
          }
        } catch (e) {
          // 忽略
        }
        const okFallback = await tryFallback('timeout')
        if (okFallback) return true
        if (!(currentConfig && currentConfig.has_content)) {
          showNoContent()
        }
        return false
      }
      const okFallback = await tryFallback('')
      if (okFallback) return true
      logError('获取配置失败: ' + (error && error.message ? error.message : String(error)))
      if (!(currentConfig && currentConfig.has_content)) {
        showNoContent()
      }
      return false
    }
  }

  /* 缓存上次渲染的内容，用于DOM更新优化 */
  let lastRenderedPrompt = ''
  let lastRenderedOptions = ''
  let markdownRenderSeq = 0

  function schedulePromptEnhancements(markdownContent, promptKey, renderSeq) {
    // 分层渲染：先展示文本，再把高开销增强（高亮/复制按钮/MathJax）放到首帧之后
    scheduleLowPriorityWork(() => {
      if (renderSeq !== markdownRenderSeq) return

      try {
        processCodeBlocks(markdownContent)
      } catch (e) {
        // 忽略
      }

      // MathJax：用原始文本做公式检测，避免读取 textContent 触发大 DOM 遍历
      try {
        loadMathJaxIfNeeded(markdownContent, promptKey)
      } catch (e) {
        // 忽略
      }

      let hasCode = false
      try {
        // 只在存在代码块时才加载/执行 Prism（避免无意义的解析开销）
        hasCode = !!markdownContent.querySelector('pre code')
      } catch (e) {
        hasCode = false
      }
      if (!hasCode) return

      ensurePrismLoaded().then(ok => {
        if (!ok) return
        scheduleLowPriorityWork(() => {
          if (renderSeq !== markdownRenderSeq) return
          try {
            if (typeof Prism !== 'undefined' && Prism.highlightAllUnder) {
              Prism.highlightAllUnder(markdownContent)
            }
          } catch (e) {
            // 忽略
          }
        }, 800)
      })
    }, 500)
  }

  /* 根据配置更新UI - 渲染Markdown内容、选项列表和倒计时（优化：只更新变化的部分） */
  function updateUI(config) {
    /* 检测是否为同一任务，用于保持用户的选择状态 */
    const isSameTask = currentConfig && currentConfig.task_id === config.task_id

    currentConfig = config

    /* 隐藏加载动画和无内容页面，显示任务内容 */
    document.getElementById('loadingState').classList.add('hidden')
    document.getElementById('noContentState').classList.add('hidden')
    document.getElementById('feedbackForm').classList.remove('hidden')
    destroyNoContentHourglassAnimation()

    /* 优化：只在 prompt 变化时重新渲染 Markdown */
    const markdownContent = document.getElementById('markdownContent')
    const promptKey = config.prompt_html || config.prompt || ''
    if (promptKey !== lastRenderedPrompt) {
      const renderSeq = ++markdownRenderSeq

      if (config.prompt_html && typeof config.prompt_html === 'string') {
        markdownContent.innerHTML = sanitizePromptHtml(config.prompt_html)
        schedulePromptEnhancements(markdownContent, promptKey, renderSeq)
      } else {
        // 首次快速渲染：若 marked 未加载，会走纯文本降级；marked 加载完成后再升级重渲染
        markdownContent.innerHTML = sanitizePromptHtml(renderSimpleMarkdown(config.prompt))
        schedulePromptEnhancements(markdownContent, promptKey, renderSeq)

        if (typeof marked === 'undefined') {
          ensureMarkedLoaded().then(ok => {
            if (!ok) return
            if (renderSeq !== markdownRenderSeq) return
            try {
              markdownContent.innerHTML = sanitizePromptHtml(renderSimpleMarkdown(config.prompt))
            } catch (e) {
              return
            }
            schedulePromptEnhancements(markdownContent, promptKey, renderSeq)
          })
        }
      }
      lastRenderedPrompt = promptKey
    }

    /* 渲染预定义选项列表 */
    const optionsSection = document.getElementById('optionsSection')
    const optionsContainer = document.getElementById('optionsContainer')

    if (config.predefined_options && config.predefined_options.length > 0) {
      optionsSection.classList.remove('hidden')

      /* 优化：计算选项哈希，只在选项变化时重建DOM */
      const optionsHash = JSON.stringify(config.predefined_options)
      // 【关键修复】把 task_id 纳入缓存键：不同任务即使选项列表相同，也必须恢复各自勾选状态
      const optionsKey = (config.task_id || '') + '|' + optionsHash
      const needRebuildOptions = optionsKey !== lastRenderedOptions

      if (needRebuildOptions) {
        /* 对齐原始实现：优先恢复该任务之前保存的勾选状态；没有则回退到同任务的DOM读取 */
        let savedSelections = []
        const savedState = config.task_id ? taskOptionsStates[config.task_id] : null
        if (savedState) {
          if (Array.isArray(savedState)) {
            savedState.forEach((checked, idx) => {
              if (checked) savedSelections.push(idx)
            })
          } else if (typeof savedState === 'object') {
            Object.keys(savedState).forEach(k => {
              if (savedState[k]) {
                const n = parseInt(k, 10)
                if (!Number.isNaN(n)) savedSelections.push(n)
              }
            })
          }
        } else if (isSameTask) {
          config.predefined_options.forEach((option, index) => {
            const checkbox = document.getElementById('option-' + index)
            if (checkbox && checkbox.checked) {
              savedSelections.push(index)
            }
          })
        }

        /* 清空并重建选项列表的DOM结构 */
        optionsContainer.innerHTML = ''

        config.predefined_options.forEach((option, index) => {
          const optionDiv = document.createElement('div')
          optionDiv.className = 'option-item'
          optionDiv.innerHTML =
            '<input type="checkbox" class="option-checkbox" id="option-' +
            index +
            '">' +
            '<label class="option-label" for="option-' +
            index +
            '">' +
            escapeHtml(option) +
            '</label>'

          /* 恢复之前保存的选中状态 */
          if (savedSelections.includes(index)) {
            const checkbox = optionDiv.querySelector('input')
            checkbox.checked = true
            optionDiv.classList.add('selected')
          }

          /* 绑定复选框变更事件，同步到选项数组 */
          const checkbox = optionDiv.querySelector('input')
          const label = optionDiv.querySelector('label')

          checkbox.addEventListener('change', () => {
            optionDiv.classList.toggle('selected', checkbox.checked)
          })

          /* 点击选项区域时切换复选框 - 提升交互体验 */
          optionDiv.addEventListener('click', e => {
            /* 避免重复触发 - 只在点击非交互元素时手动切换复选框 */
            if (e.target !== checkbox && e.target !== label) {
              checkbox.click()
            }
          })

          optionsContainer.appendChild(optionDiv)
        })

        lastRenderedOptions = optionsKey
      }
    } else {
      optionsSection.classList.add('hidden')
      lastRenderedOptions = ''
    }

    /* 启动自动重调倒计时 - 超时后自动提交空反馈 */
    if (config.auto_resubmit_timeout && config.auto_resubmit_timeout > 0) {
      // 关键修复：只在任务变化或倒计时未运行时启动，避免被轮询无限重置
      if (config.task_id !== lastCountdownTaskId || !countdownTimer) {
        startCountdown(
          config.auto_resubmit_timeout,
          config.task_id,
          config.remaining_time,
          config.deadline
        )
      }
    } else {
      stopCountdown()
    }

    // 【对齐原始实现】任务切换时恢复输入/图片，避免串任务；同任务轮询不覆盖用户输入
    if (!isSameTask && config.task_id) {
      restoreLocalStateForTask(config.task_id)
    } else if (config.task_id) {
      // 同任务：同步图片缓存（输入由 input 事件实时保存）
      syncImagesToTaskCache(config.task_id)
    }

    log('UI已更新')
  }

  // 设置面板：按需加载（避免把通知配置/自动保存逻辑打进首屏解析）
  function openSettingsLazy() {
    Promise.resolve()
      .then(() => Promise.all([ensureNotifyCoreLoaded(), ensureSettingsUiLoaded()]))
      .then(result => {
        const okUi = Array.isArray(result) ? !!result[1] : false
        if (!okUi) {
          throw new Error('设置模块加载失败')
        }
        const ui = getSettingsUiModule()
        if (!ui || typeof ui.openSettings !== 'function') {
          throw new Error('设置模块不可用')
        }
        return ui.openSettings()
      })
      .catch(e => {
        const msg = e && e.message ? String(e.message) : String(e)
        try {
          showToast('打开设置失败：' + msg, {
            kind: 'error',
            timeoutMs: 2600,
            dedupeKey: 'settings:open:' + msg.slice(0, 80)
          })
        } catch (e2) {
          // 忽略
        }
      })
  }

  // 新任务通知：委托给 notify-core（按需加载）
  function notifyNewTasks(taskIds) {
    const ids = Array.isArray(taskIds) ? taskIds.filter(Boolean) : [taskIds].filter(Boolean)
    if (!ids || ids.length === 0) return

    Promise.resolve()
      .then(() => ensureNotifyCoreLoaded())
      .then(ok => {
        const mod = getNotifyCoreModule()
        if (ok && mod && typeof mod.showNewTaskNotification === 'function') {
          return mod.showNewTaskNotification(ids)
        }
        // notify-core 不可用时至少给出 VSCode statusBar 提示（不影响主流程）
        const msg =
          ids.length === 1 ? '新任务已添加: ' + ids[0] : '收到 ' + ids.length + ' 个新任务'
        postStatusInfo(msg)
      })
      .catch(() => {
        try {
          const msg =
            ids.length === 1 ? '新任务已添加: ' + ids[0] : '收到 ' + ids.length + ' 个新任务'
          postStatusInfo(msg)
        } catch (e) {
          // 忽略
        }
      })
  }

  /* 显示无有效内容页面 - 隐藏任务内容，显示等待界面 */
  function showNoContent() {
    // 立即隐藏标签栏（无内容页只保留右上角设置按钮，不显示 tabs）
    hideTabs()
    document.getElementById('loadingState').classList.add('hidden')
    document.getElementById('feedbackForm').classList.add('hidden')
    document.getElementById('noContentState').classList.remove('hidden')
    initNoContentHourglassAnimation()
    stopCountdown()
  }
  // 通知设置/面板 UI 已拆分为按需加载模块（webview-notify-core.js / webview-settings-ui.js）

  /* 使用 marked.js 进行 Markdown 渲染 */
  function renderSimpleMarkdown(text) {
    if (!text) return ''

    try {
      if (typeof marked !== 'undefined') {
        configureMarkedOnce()
        if (marked && typeof marked.parse === 'function') {
          return marked.parse(text)
        }
      }

      // marked.js 未加载时的降级处理
      log('marked.js 未加载，使用纯文本显示')
      return '<pre>' + text.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>'
    } catch (e) {
      log('Markdown 渲染失败，已降级为纯文本: ' + (e && e.message ? e.message : String(e)))
      return '<pre>' + text.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>'
    }
  }

  /* HTML转义 - 防止XSS攻击 */
  function escapeHtml(text) {
    var map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }
    return String(text).replace(/[&<>"']/g, function (m) {
      return map[m]
    })
  }

  // prompt_html 安全净化（防止 XSS / 事件处理器 / javascript: 协议）
  function sanitizePromptHtml(rawHtml) {
    if (!rawHtml || typeof rawHtml !== 'string') return ''

    try {
      const container = document.createElement('div')
      container.innerHTML = rawHtml

      const DROP_TAGS = new Set([
        'script',
        'style',
        'iframe',
        'object',
        'embed',
        'link',
        'meta',
        'base',
        'form',
        'input',
        'textarea',
        'button',
        'select',
        'option'
      ])

      const ALLOWED_TAGS = new Set([
        'div',
        'span',
        'p',
        'br',
        'hr',
        'strong',
        'em',
        'b',
        'i',
        'del',
        'code',
        'pre',
        'blockquote',
        'ul',
        'ol',
        'li',
        'h1',
        'h2',
        'h3',
        'h4',
        'h5',
        'h6',
        'table',
        'thead',
        'tbody',
        'tr',
        'th',
        'td',
        'a',
        'img'
      ])

      const ALLOWED_ATTR = {
        a: new Set(['href', 'title', 'target', 'rel']),
        img: new Set(['src', 'alt', 'title']),
        code: new Set(['class']),
        pre: new Set(['class']),
        span: new Set(['class']),
        div: new Set(['class']),
        p: new Set(['class']),
        table: new Set(['class']),
        thead: new Set(['class']),
        tbody: new Set(['class']),
        tr: new Set(['class']),
        th: new Set(['class', 'colspan', 'rowspan', 'align']),
        td: new Set(['class', 'colspan', 'rowspan', 'align'])
      }

      function normalizeUrl(url, kind) {
        if (!url || typeof url !== 'string') return ''
        const trimmed = url.trim()
        if (!trimmed) return ''

        // 允许页内锚点
        if (trimmed.startsWith('#')) return trimmed

        // 禁止危险协议
        if (/^\s*javascript:/i.test(trimmed) || /^\s*vbscript:/i.test(trimmed)) return ''

        // img 允许 data:image
        if (kind === 'img' && /^\s*data:image\//i.test(trimmed)) return trimmed

        // a 不允许 data:
        if (kind === 'a' && /^\s*data:/i.test(trimmed)) return ''

        // 相对路径（对齐后端静态资源写法）：补齐到后端 SERVER_URL
        if (trimmed.startsWith('/')) return SERVER_URL + trimmed

        // 其它情况按 URL 解析（允许 http/https）
        try {
          const u = new URL(trimmed, SERVER_URL)
          if (u.protocol === 'http:' || u.protocol === 'https:') return u.toString()
          return ''
        } catch (e) {
          return ''
        }
      }

      function unwrapElement(el) {
        const parent = el.parentNode
        if (!parent) return
        while (el.firstChild) {
          parent.insertBefore(el.firstChild, el)
        }
        parent.removeChild(el)
      }

      // 逆序遍历，避免 DOM 结构变化影响遍历
      const all = Array.from(container.querySelectorAll('*')).reverse()
      all.forEach(el => {
        const tag = String(el.tagName || '').toLowerCase()
        if (!tag) return

        if (DROP_TAGS.has(tag)) {
          el.remove()
          return
        }

        if (!ALLOWED_TAGS.has(tag)) {
          unwrapElement(el)
          return
        }

        // 清理属性
        const allowed = ALLOWED_ATTR[tag] || new Set(['class'])
        Array.from(el.attributes || []).forEach(attr => {
          const name = String(attr.name || '').toLowerCase()
          const value = String(attr.value || '')

          // 移除所有 on* 事件与 style
          if (name.startsWith('on') || name === 'style') {
            el.removeAttribute(attr.name)
            return
          }

          // 仅允许白名单属性
          if (!allowed.has(name)) {
            el.removeAttribute(attr.name)
            return
          }

          // URL 属性进一步校验 + 归一化
          if (tag === 'a' && name === 'href') {
            const safe = normalizeUrl(value, 'a')
            if (!safe) {
              el.removeAttribute('href')
            } else {
              el.setAttribute('href', safe)
              el.setAttribute('target', '_blank')
              el.setAttribute('rel', 'noopener noreferrer')
            }
            return
          }
          if (tag === 'img' && name === 'src') {
            const safe = normalizeUrl(value, 'img')
            if (!safe) {
              // src 不安全：直接移除整张图片，避免触发 onerror 等边界行为
              el.remove()
            } else {
              el.setAttribute('src', safe)
            }
            return
          }

          // 其它属性：保留（setAttribute 已安全处理）
          el.setAttribute(attr.name, value)
        })
      })

      return container.innerHTML
    } catch (e) {
      // 任何异常都降级为纯文本显示
      return '<pre>' + escapeHtml(rawHtml) + '</pre>'
    }
  }

  // 处理代码块：添加复制按钮与语言标签（对齐原始项目 app.js 的体验）
  function createCopyButton(targetText) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'copy-button'
    button.setAttribute('aria-label', '复制')
    button.title = '复制'

    // Claude 设计风格：复制图标（currentColor）
    const COPY_ICON_SVG =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 21" fill="none" aria-hidden="true" focusable="false"><path d="M12.5 3.60938C13.3284 3.60938 14 4.28095 14 5.10938V6.60938H15.5C16.3284 6.60938 17 7.28095 17 8.10938V16.1094C17 16.9378 16.3284 17.6094 15.5 17.6094H7.5C6.67157 17.6094 6 16.9378 6 16.1094V14.6094H4.5C3.67157 14.6094 3 13.9378 3 13.1094V5.10938C3 4.28095 3.67157 3.60938 4.5 3.60938H12.5ZM14 13.1094C14 13.9378 13.3284 14.6094 12.5 14.6094H7V16.1094C7 16.3855 7.22386 16.6094 7.5 16.6094H15.5C15.7761 16.6094 16 16.3855 16 16.1094V8.10938C16 7.83323 15.7761 7.60938 15.5 7.60938H14V13.1094ZM4.5 4.60938C4.22386 4.60938 4 4.83323 4 5.10938V13.1094C4 13.3855 4.22386 13.6094 4.5 13.6094H12.5C12.7761 13.6094 13 13.3855 13 13.1094V5.10938C13 4.83323 12.7761 4.60938 12.5 4.60938H4.5Z" fill="currentColor"></path></svg>'
    button.innerHTML = COPY_ICON_SVG

    let lastClickAt = 0

    button.addEventListener('click', async () => {
      // 防抖：避免连续点击导致状态闪烁
      const now = Date.now()
      if (now - lastClickAt < 250) return
      lastClickAt = now

      try {
        await navigator.clipboard.writeText(String(targetText || ''))
        button.classList.add('copied')
        button.classList.remove('error')
        button.title = '已复制'
        setTimeout(() => {
          button.classList.remove('copied')
          button.title = '复制'
        }, 2000)
      } catch (err) {
        button.classList.add('error')
        button.classList.remove('copied')
        button.title = '复制失败'
        setTimeout(() => {
          button.classList.remove('error')
          button.title = '复制'
        }, 2000)
      }
    })

    return button
  }

  function processCodeBlocks(container) {
    if (!container) return

    const codeBlocks = container.querySelectorAll('pre')
    codeBlocks.forEach(pre => {
      // 已处理过则跳过
      if (pre.parentElement && pre.parentElement.classList.contains('code-block-container')) {
        return
      }

      const wrapper = document.createElement('div')
      wrapper.className = 'code-block-container'

      // 包装 pre
      pre.parentNode.insertBefore(wrapper, pre)
      wrapper.appendChild(pre)

      const codeElement = pre.querySelector('code')
      let language = 'text'
      if (codeElement && codeElement.className) {
        const m = codeElement.className.match(/language-([\w-]+)/)
        if (m) language = m[1]
      }

      const toolbar = document.createElement('div')
      toolbar.className = 'code-toolbar'

      if (language && language !== 'text') {
        const label = document.createElement('span')
        label.className = 'language-label'
        label.textContent = String(language).toUpperCase()
        toolbar.appendChild(label)
      }

      const textToCopy = codeElement ? codeElement.textContent || '' : pre.textContent || ''
      toolbar.appendChild(createCopyButton(textToCopy))

      wrapper.appendChild(toolbar)
    })
  }

  // MathJax 懒加载（对齐原始项目：检测到公式才加载 1.17MB）
  window.MathJax = window.MathJax || {
    tex: {
      inlineMath: [
        ['$', '$'],
        ['\\(', '\\)']
      ],
      displayMath: [
        ['$$', '$$'],
        ['\\[', '\\]']
      ],
      processEscapes: true,
      processEnvironments: true,
      packages: { '[+]': ['ams', 'newcommand', 'configmacros'] },
      tags: 'ams'
    },
    options: {
      skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
      ignoreHtmlClass: 'tex2jax_ignore',
      processHtmlClass: 'tex2jax_process'
    },
    startup: {
      ready: () => {
        try {
          MathJax.startup.defaultReady()
        } catch (e) {
          // 忽略
        }
        // 加载完成后渲染队列中的元素
        if (window._mathJaxPendingElements && window.MathJax && window.MathJax.typesetPromise) {
          const pending = window._mathJaxPendingElements.slice()
          window._mathJaxPendingElements = []
          pending.forEach(el => {
            window.MathJax.typesetPromise([el]).catch(() => {})
          })
        }
      }
    }
  }

  window._mathJaxLoading = window._mathJaxLoading || false
  window._mathJaxLoaded = window._mathJaxLoaded || false
  window._mathJaxPendingElements = window._mathJaxPendingElements || []

  function hasMathContent(text) {
    if (!text) return false
    const mathPatterns = [
      /\$[^$]+\$/, // $E=mc^2$
      /\$\$[^$]+\$\$/, // $$...$$
      /\\\([^)]+\\\)/, // \( ... \)
      /\\\[[^\]]+\\\]/ // \[ ... \]
    ]
    return mathPatterns.some(pattern => pattern.test(text))
  }

  function loadMathJaxIfNeeded(element, text) {
    if (!element) return
    const content = text || element.textContent || ''
    if (!hasMathContent(content)) return

    // 已加载：直接渲染
    if (window._mathJaxLoaded && window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise([element]).catch(() => {})
      return
    }

    window._mathJaxPendingElements.push(element)

    // 正在加载：等待 startup.ready 处理队列
    if (window._mathJaxLoading) return

    window._mathJaxLoading = true

    // 避免重复插入
    const existing = document.getElementById('MathJax-script')
    if (existing) return

    const script = document.createElement('script')
    script.id = 'MathJax-script'
    script.async = true
    // 优先从 VSIX 内置资源加载（更稳定，不依赖后端静态资源是否齐全）
    // 兜底：若未注入本地资源 URL，则回退到后端静态资源路径（与原始实现兼容）
    script.src =
      (MATHJAX_SCRIPT_URL ? String(MATHJAX_SCRIPT_URL) : '') ||
      (SERVER_URL ? SERVER_URL + '/static/js/tex-mml-chtml.js' : '')
    // 关键：带 nonce 才能通过 CSP
    if (CSP_NONCE) {
      try {
        script.setAttribute('nonce', CSP_NONCE)
      } catch (e) {
        // 忽略
      }
    }
    script.onload = function () {
      window._mathJaxLoaded = true
      window._mathJaxLoading = false
    }
    script.onerror = function () {
      window._mathJaxLoading = false
    }
    document.head.appendChild(script)
  }

  // 倒计时
  // 启动倒计时（后台运行，不显示UI）
  function startCountdown(totalSeconds, taskId, initialRemaining, deadline) {
    // 清除之前的定时器，避免重复倒计时
    stopCountdown()

    // 验证倒计时秒数有效性
    if (!totalSeconds || totalSeconds <= 0) {
      log('倒计时秒数无效: ' + totalSeconds)
      return
    }

    // 记录 deadline（如果服务端提供）
    if (taskId && typeof deadline === 'number') {
      taskDeadlines[taskId] = deadline
    }

    if (typeof initialRemaining === 'number') {
      remainingSeconds = Math.max(0, Math.floor(initialRemaining))
    } else if (taskId && typeof taskDeadlines[taskId] === 'number') {
      remainingSeconds = Math.max(0, Math.floor(taskDeadlines[taskId] - getAdjustedNowSeconds()))
    } else {
      remainingSeconds = Math.max(0, Math.floor(totalSeconds))
    }
    lastCountdownTaskId = taskId // 记录当前倒计时对应的任务ID
    log('启动倒计时: ' + remainingSeconds + '秒, 任务: ' + taskId)

    function tick() {
      // 任务已切换，停止当前倒计时
      if (lastCountdownTaskId !== taskId) {
        stopCountdown()
        return
      }

      // 优先使用 deadline 计算剩余（避免后台节流导致倒计时不准）
      if (taskId && typeof taskDeadlines[taskId] === 'number') {
        remainingSeconds = Math.max(0, Math.floor(taskDeadlines[taskId] - getAdjustedNowSeconds()))
      } else {
        remainingSeconds = remainingSeconds - 1
      }

      if (remainingSeconds <= 0) {
        autoSubmit()
      }
    }

    // 启动定时器，每秒检查一次
    countdownTimer = setInterval(tick, 1000)
  }

  /* 停止自动重调倒计时 - 用户提交反馈或切换任务时调用 */
  function stopCountdown() {
    if (countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
    lastCountdownTaskId = null // 重置任务ID，允许下次重新启动
  }

  // 自动重调（倒计时结束时触发）
  async function autoSubmit() {
    const taskId = lastCountdownTaskId
    log('倒计时结束，自动重调')
    // 防止同一任务在“超时且提交失败”场景下反复触发自动重调（会导致 429 并阻塞手动提交）
    if (taskId && autoSubmitAttempted[taskId]) {
      stopCountdown()
      return
    }
    if (taskId) {
      autoSubmitAttempted[taskId] = Date.now()
    }
    stopCountdown()

    // 自动重调前实时拉取一次配置，确保 resubmit_prompt 热更新能立刻生效
    let defaultMessage = '请立即调用 interactive_feedback 工具'
    try {
      const prompts = await fetchFeedbackPrompts()
      if (prompts && prompts.resubmit_prompt) {
        defaultMessage = String(prompts.resubmit_prompt)
      }
    } catch (e) {
      // 忽略：保留默认文案兜底
    }

    await submitWithData(defaultMessage, [], taskId)

    // 提交后立即重新轮询，更新任务状态
    setTimeout(() => requestImmediateRefresh(), 500)
  }

  // 提交反馈
  async function submitFeedback() {
    const feedbackText = document.getElementById('feedbackText').value.trim()

    // 获取选中的选项
    const selected = []
    if (currentConfig && currentConfig.predefined_options) {
      currentConfig.predefined_options.forEach((option, index) => {
        const checkbox = document.getElementById('option-' + index)
        if (checkbox && checkbox.checked) {
          selected.push(option)
        }
      })
    }

    // 直接提交用户输入，不添加额外文本（服务器端已处理提示）
    await submitWithData(feedbackText, selected)
  }

  function applySubmitBackoffUi() {
    try {
      const submitBtn = document.getElementById('submitBtn')
      if (!submitBtn) return

      if (submitBackoffTimer) {
        clearTimeout(submitBackoffTimer)
        submitBackoffTimer = null
      }

      const now = Date.now()
      if (submitBackoffUntilMs && now >= submitBackoffUntilMs) {
        submitBackoffUntilMs = 0
      }

      if (submitBackoffUntilMs && now < submitBackoffUntilMs) {
        const leftSec = Math.max(1, Math.ceil((submitBackoffUntilMs - now) / 1000))
        submitBtn.disabled = true
        submitBtn.title = '提交过于频繁，请等待 ' + leftSec + ' 秒'

        submitBackoffTimer = setTimeout(
          () => {
            submitBackoffTimer = null
            submitBackoffUntilMs = 0
            try {
              const b = document.getElementById('submitBtn')
              if (!b) return
              if (submitInFlight) return
              b.disabled = false
              b.title = '提交反馈'
              b.innerHTML = submitBtnDefaultHtml || SUBMIT_BTN_FALLBACK_HTML
            } catch (e) {
              // 忽略
            }
          },
          Math.max(0, submitBackoffUntilMs - now)
        )
      } else {
        // 无冷却：恢复默认 title（不强制 enabled，交由调用侧控制）
        submitBtn.title = '提交反馈'
      }
    } catch (e) {
      // 忽略
    }
  }

  // 提交数据
  async function submitWithData(text, options, taskIdOverride) {
    // 先做轻量 guard：避免并发提交/冷却期重复点击（不进入 try/finally，避免污染按钮状态）
    try {
      const now0 = Date.now()
      if (submitInFlight) {
        showToast('正在提交…', { kind: 'info', timeoutMs: 1200, dedupeKey: 'submit:inflight' })
        return
      }
      if (submitBackoffUntilMs && now0 < submitBackoffUntilMs) {
        const leftSec = Math.max(1, Math.ceil((submitBackoffUntilMs - now0) / 1000))
        applySubmitBackoffUi()
        showToast('提交过于频繁，请等待 ' + leftSec + ' 秒', {
          kind: 'warn',
          timeoutMs: 1600,
          dedupeKey: 'submit:backoff'
        })
        return
      }
    } catch (e) {
      // 忽略
    }

    submitInFlight = true
    let submitController = null
    let submitTimeoutId = null
    try {
      stopCountdown()

      // 安全获取提交按钮（可能在无内容页面时不存在）
      const submitBtn = document.getElementById('submitBtn')
      if (submitBtn) {
        submitBtn.disabled = true
        submitBtn.innerHTML = SUBMIT_BTN_SPINNER_HTML
      }

      const formData = new FormData()
      formData.append('feedback_text', text)
      formData.append('selected_options', JSON.stringify(options))

      /* 添加已上传的图片到FormData */
      uploadedImages.forEach((imageData, index) => {
        formData.append('image_' + index, dataURLtoBlob(imageData.data), imageData.name)
      })

      // 优先使用多任务提交端点（更明确，不依赖“当前激活任务”隐式状态）
      const taskIdToSubmit =
        taskIdOverride || (currentConfig && currentConfig.task_id) || activeTaskId
      if (taskIdToSubmit) {
        // 即使回退到 /api/submit，也让后端知道本次提交面向哪个任务。
        formData.append('task_id', taskIdToSubmit)
      }
      const submitPath = taskIdToSubmit
        ? '/api/tasks/' + encodeURIComponent(taskIdToSubmit) + '/submit'
        : '/api/submit'

      // 关键日志：便于排查“点击提交无效/重复提交/429”
      try {
        const textLen = (text || '').toString().length
        const optLen = Array.isArray(options) ? options.length : 0
        const imgLen = Array.isArray(uploadedImages) ? uploadedImages.length : 0
        vscode.postMessage({
          type: 'log',
          level: 'debug',
          message:
            '[submit] start taskId=' +
            (taskIdToSubmit || '') +
            ' path=' +
            submitPath +
            ' textLen=' +
            textLen +
            ' options=' +
            optLen +
            ' images=' +
            imgLen
        })
      } catch (e) {
        // 忽略
      }

      const requestOptions = {
        method: 'POST',
        body: formData
      }
      // 兜底超时：避免服务端无响应导致 UI 永久“正在提交…”
      if (typeof AbortController !== 'undefined') {
        try {
          submitController = new AbortController()
          requestOptions.signal = submitController.signal
          submitTimeoutId = setTimeout(() => {
            try {
              submitController.abort()
            } catch (e) {
              /* 忽略 */
            }
          }, SUBMIT_TIMEOUT_MS)
        } catch (e) {
          submitController = null
        }
      }

      let response = await fetch(SERVER_URL + submitPath, requestOptions)

      // 向后兼容：如果指定任务端点不存在/任务不存在，回退到通用端点
      if (!response.ok && response.status === 404 && taskIdToSubmit) {
        response = await fetch(SERVER_URL + '/api/submit', requestOptions)
      }

      if (response.ok) {
        log('反馈提交成功')
        try {
          vscode.postMessage({
            type: 'log',
            level: 'info',
            message: '[submit] ok taskId=' + (taskIdToSubmit || '') + ' path=' + submitPath
          })
        } catch (e) {
          // 忽略
        }

        /* 提交成功后清空表单和上传的图片 */
        try {
          const textarea = document.getElementById('feedbackText')
          if (textarea) {
            textarea.value = ''
            autoResizeFeedbackTextarea(textarea)
          }
        } catch (e) {
          // 忽略
        }
        uploadedImages = []
        renderUploadedImages()

        // 重置选项（安全检查）
        document.querySelectorAll('.option-item').forEach(item => {
          item.classList.remove('selected')
          const checkbox = item.querySelector('input')
          if (checkbox) {
            checkbox.checked = false
          }
        })

        // 【对齐原始实现】清理该任务的本地缓存，避免下次切换回来出现旧内容
        if (taskIdToSubmit) {
          if (taskTextareaContents[taskIdToSubmit] !== undefined) {
            delete taskTextareaContents[taskIdToSubmit]
          }
          if (taskOptionsStates[taskIdToSubmit] !== undefined) {
            delete taskOptionsStates[taskIdToSubmit]
          }
          if (taskImages[taskIdToSubmit] !== undefined) {
            delete taskImages[taskIdToSubmit]
          }
        }

        // 显示成功提示
        showToast('反馈已提交', { kind: 'success', timeoutMs: 1400, dedupeKey: 'submit:ok' })

        // 重新轮询（使用pollAllData以更新任务列表）
        setTimeout(() => requestImmediateRefresh(), 200)
      } else {
        // 429：给出更明确的提示，并进入冷却期（避免用户反复点击造成更严重的限流）
        if (response.status === 429) {
          const retryAfter =
            response.headers && response.headers.get
              ? String(response.headers.get('Retry-After') || '')
              : ''
          const retryAfterNum = parseInt(retryAfter, 10)
          const cooldownSec =
            Number.isFinite(retryAfterNum) && retryAfterNum > 0 ? Math.min(120, retryAfterNum) : 15
          submitBackoffUntilMs = Date.now() + cooldownSec * 1000
          applySubmitBackoffUi()

          const hint = retryAfter
            ? '，建议等待 ' + retryAfter + ' 秒后再试'
            : '，建议等待 ' + cooldownSec + ' 秒后再试'
          const msg = '提交过于频繁（HTTP 429）' + hint
          try {
            vscode.postMessage({ type: 'log', level: 'warn', message: msg })
          } catch (e) {
            // 忽略
          }
          showToast(msg, { kind: 'warn', timeoutMs: 1800, dedupeKey: 'submit:429' })
          try {
            vscode.postMessage({
              type: 'log',
              level: 'warn',
              message:
                '[submit] 429 taskId=' + (taskIdToSubmit || '') + ' retryAfter=' + cooldownSec + 's'
            })
          } catch (e) {
            // 忽略
          }
          return
        }

        const msg = '提交失败（HTTP ' + response.status + '）'
        logError(msg)
      }
    } catch (error) {
      const isAbort = !!(error && (error.name === 'AbortError' || String(error.name || '') === 'AbortError'))
      if (isAbort) {
        logError('提交超时：请检查服务端是否可用')
      } else {
        const msg = error && error.message ? String(error.message) : String(error)
        logError('提交失败：' + msg)
      }
    } finally {
      if (submitTimeoutId) {
        clearTimeout(submitTimeoutId)
        submitTimeoutId = null
      }
      submitInFlight = false
      // 安全恢复提交按钮状态
      const submitBtn = document.getElementById('submitBtn')
      if (submitBtn) {
        submitBtn.disabled = false
        submitBtn.innerHTML = submitBtnDefaultHtml || SUBMIT_BTN_FALLBACK_HTML
      }
      // 若仍在冷却期，则覆盖为 disabled 并安排到期恢复
      applySubmitBackoffUi()
    }
  }

  // 图片上传/粘贴（对齐原项目 static/js/app.js 的默认参数）
  const SUPPORTED_IMAGE_TYPES = [
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/bmp',
    'image/svg+xml'
  ]
  const MAX_IMAGE_SIZE = 10 * 1024 * 1024 // 10MB
  const MAX_IMAGE_COUNT = 10
  const MAX_IMAGE_DIMENSION = 1920 // 最大宽度或高度
  const COMPRESS_QUALITY = 0.8 // 0.1-1.0
  const MAX_RETURN_BYTES = 2 * 1024 * 1024 // 2MB：避免 base64 过大
  const LARGE_FILE_BYTES = 5 * 1024 * 1024 // 5MB
  const LARGE_AREA = 4000000 // 4MP
  const MIN_DIMENSION = 320

  function sanitizeFileName(fileName) {
    try {
      const name = String(fileName || '').trim()
      if (!name) return ''
      return name
        .replace(/[<>:"/\\|?*]/g, '')
        .replace(/\s+/g, '_')
        .trim()
        .substring(0, 100)
    } catch (e) {
      return ''
    }
  }

  function getExtensionForMime(mimeType) {
    if (mimeType === 'image/png') return '.png'
    if (mimeType === 'image/webp') return '.webp'
    if (mimeType === 'image/jpeg') return '.jpg'
    if (mimeType === 'image/gif') return '.gif'
    if (mimeType === 'image/bmp') return '.bmp'
    if (mimeType === 'image/svg+xml') return '.svg'
    return ''
  }

  function replaceExtension(filename, newExt) {
    const safe = sanitizeFileName(filename) || 'image'
    if (!newExt) return safe
    const withoutExt = safe.replace(/\.[^/.]+$/, '')
    return withoutExt + newExt
  }

  function readAsDataURL(blob) {
    return new Promise((resolve, reject) => {
      try {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result || ''))
        reader.onerror = () => reject(new Error('读取图片失败'))
        reader.readAsDataURL(blob)
      } catch (e) {
        reject(e)
      }
    })
  }

  function loadImageFromDataURL(dataUrl) {
    return new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error('图片解码失败'))
      img.src = dataUrl
    })
  }

  function canvasToBlob(canvas, mimeType, quality) {
    return new Promise(resolve => {
      try {
        canvas.toBlob(blob => resolve(blob || null), mimeType, quality)
      } catch (e) {
        resolve(null)
      }
    })
  }

  async function decodeImageSource(file) {
    // 优先使用 createImageBitmap（避免先生成巨大的 dataURL）
    if (typeof createImageBitmap === 'function') {
      try {
        const bmp = await createImageBitmap(file)
        return {
          kind: 'bitmap',
          image: bmp,
          width: bmp.width,
          height: bmp.height,
          cleanup: () => {
            try {
              bmp.close()
            } catch (e) {
              /* 忽略 */
            }
          }
        }
      } catch (e) {
        // 回退
      }
    }

    const dataUrl = await readAsDataURL(file)
    const img = await loadImageFromDataURL(dataUrl)
    return {
      kind: 'img',
      image: img,
      width: img.naturalWidth || img.width || 0,
      height: img.naturalHeight || img.height || 0,
      cleanup: () => {}
    }
  }

  async function compressImageToDataURL(file) {
    if (!file || !file.type) {
      throw new Error('无效的图片文件')
    }
    if (!SUPPORTED_IMAGE_TYPES.includes(file.type)) {
      throw new Error('不支持的图片格式：' + String(file.type))
    }
    if (typeof file.size === 'number' && file.size > MAX_IMAGE_SIZE) {
      throw new Error('图片过大：' + (file.size / 1024 / 1024).toFixed(2) + 'MB > 10MB')
    }

    // 文件名兜底（剪贴板图片可能没有名字）
    const rawName =
      sanitizeFileName(file.name) ||
      'image_' + Date.now() + (getExtensionForMime(file.type) || '.png')

    // SVG / GIF：不压缩（对齐原项目）
    if (file.type === 'image/svg+xml' || file.type === 'image/gif') {
      const data = await readAsDataURL(file)
      return { name: rawName, data }
    }

    const forceCompress = file.size > MAX_RETURN_BYTES
    const isLargeFile = file.size > LARGE_FILE_BYTES

    const decoded = await decodeImageSource(file)
    try {
      let width = decoded.width || 0
      let height = decoded.height || 0
      if (!width || !height) {
        // 解码失败：降级为原图 dataURL
        const data = await readAsDataURL(file)
        return { name: rawName, data }
      }

      const originalArea = width * height

      // 大图：更激进的缩放
      let maxDimension = MAX_IMAGE_DIMENSION
      if (forceCompress || isLargeFile || originalArea > LARGE_AREA) {
        maxDimension = Math.min(MAX_IMAGE_DIMENSION, 1200)
      }

      if (width > maxDimension || height > maxDimension) {
        const ratio = Math.min(maxDimension / width, maxDimension / height)
        width = Math.floor(width * ratio)
        height = Math.floor(height * ratio)
      }

      let currentWidth = width
      let currentHeight = height

      const canvas = document.createElement('canvas')
      const ctx = canvas.getContext('2d', {
        alpha: file.type === 'image/png',
        willReadFrequently: false
      })
      if (!ctx) {
        const data = await readAsDataURL(file)
        return { name: rawName, data }
      }

      canvas.width = currentWidth
      canvas.height = currentHeight
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(decoded.image, 0, 0, currentWidth, currentHeight)

      // 初始质量（对齐原项目）
      let quality = COMPRESS_QUALITY
      if (isLargeFile) {
        quality = Math.max(0.6, COMPRESS_QUALITY - 0.2)
      }
      if (forceCompress) {
        quality = Math.min(quality, 0.75)
      }

      // 输出格式候选（对齐原项目）
      const mimeCandidates = []
      if (file.type === 'image/png') {
        if (forceCompress || isLargeFile || originalArea > LARGE_AREA) {
          mimeCandidates.push('image/webp', 'image/jpeg')
        } else {
          mimeCandidates.push('image/png')
        }
      } else if (file.type === 'image/webp') {
        mimeCandidates.push('image/webp', 'image/jpeg')
      } else {
        if (forceCompress) {
          mimeCandidates.push('image/webp', 'image/jpeg')
        } else {
          mimeCandidates.push('image/jpeg')
        }
      }

      const encodeCurrent = async () => {
        for (let i = 0; i < mimeCandidates.length; i++) {
          const outType = mimeCandidates[i]
          const blob = await canvasToBlob(canvas, outType, quality)
          if (blob && blob.type) return blob
        }
        return null
      }

      let blob = await encodeCurrent()
      if (!blob) {
        const data = await readAsDataURL(file)
        return { name: rawName, data }
      }

      // 非强制：仅在变小时采用
      if (!forceCompress && blob.size >= file.size) {
        const data = await readAsDataURL(file)
        return { name: rawName, data }
      }

      // 强制：确保 <= 2MB（否则持续降质/缩放）
      if (forceCompress) {
        let attempt = 0
        const MAX_ATTEMPTS = 8
        while (blob.size > MAX_RETURN_BYTES && attempt < MAX_ATTEMPTS) {
          attempt++

          if (quality > 0.55) {
            quality = Math.max(0.55, quality - 0.1)
          } else {
            const nextWidth = Math.max(MIN_DIMENSION, Math.floor(currentWidth * 0.85))
            const nextHeight = Math.max(MIN_DIMENSION, Math.floor(currentHeight * 0.85))
            if (nextWidth === currentWidth && nextHeight === currentHeight) {
              break
            }
            currentWidth = nextWidth
            currentHeight = nextHeight
            canvas.width = currentWidth
            canvas.height = currentHeight
            ctx.imageSmoothingEnabled = true
            ctx.imageSmoothingQuality = 'high'
            ctx.drawImage(decoded.image, 0, 0, currentWidth, currentHeight)
          }

          const nextBlob = await encodeCurrent()
          if (!nextBlob) break
          blob = nextBlob
        }
      }

      const ext = getExtensionForMime(blob.type)
      const finalName = ext ? replaceExtension(rawName, ext) : rawName
      const data = await readAsDataURL(blob)
      return { name: finalName, data }
    } finally {
      try {
        decoded.cleanup && decoded.cleanup()
      } catch (e) {
        /* 忽略 */
      }
    }
  }

  // 图片处理
  function handleImageSelect(e) {
    const files = Array.from(e.target.files || [])
    processImages(files)
    // 清空 input，允许重复选择同一文件
    e.target.value = ''
  }

  function handlePaste(e) {
    const clipboardData = e && e.clipboardData
    if (!clipboardData) return

    let imageFiles = []
    try {
      if (WEBVIEW_HELPERS && typeof WEBVIEW_HELPERS.collectImageFilesFromClipboard === 'function') {
        imageFiles = WEBVIEW_HELPERS.collectImageFilesFromClipboard(clipboardData)
      }
    } catch (err) {
      imageFiles = []
    }

    if (!imageFiles.length) {
      const items = clipboardData.items || []
      for (let i = 0; i < items.length; i++) {
        const item = items[i]
        if (item && item.type && item.type.startsWith('image/')) {
          const file = item.getAsFile()
          if (file) {
            imageFiles.push(file)
          }
        }
      }
    }

    if (imageFiles.length > 0) {
      const pastedText = (
        clipboardData.getData('text/plain') ||
        clipboardData.getData('text') ||
        ''
      ).trim()
      if (!pastedText) {
        e.preventDefault() // 纯图片粘贴时阻止默认行为，避免 textarea 出现占位文本
      }
      processImages(imageFiles)
      log('从剪贴板粘贴了 ' + imageFiles.length + ' 张图片')
    }
  }

  async function processImages(files) {
    for (const file of files || []) {
      if (!file) continue
      if (uploadedImages.length >= MAX_IMAGE_COUNT) {
        const msg = '最多只能上传 ' + MAX_IMAGE_COUNT + ' 张图片'
        logError(msg)
        vscode.postMessage({ type: 'showInfo', message: msg })
        break
      }

      try {
        const processed = await compressImageToDataURL(file)
        if (!processed || !processed.data) continue

        uploadedImages.push({
          name: processed.name || sanitizeFileName(file.name) || 'image',
          data: processed.data
        })
        renderUploadedImages()
        // 实时同步到当前任务缓存
        if (activeTaskId) {
          syncImagesToTaskCache(activeTaskId)
        }
      } catch (e) {
        const msg = '图片处理失败：' + (e && e.message ? e.message : String(e))
        logError(msg)
        vscode.postMessage({ type: 'showInfo', message: msg })
      }
    }
  }

  function renderUploadedImages() {
    const container = document.getElementById('uploadedImages')
    container.innerHTML = ''

    uploadedImages.forEach((image, index) => {
      const div = document.createElement('div')
      div.className = 'image-preview'

      const img = document.createElement('img')
      img.src = image.data
      // alt/textContent 不会解析 HTML，不需要 escapeHtml，避免出现 &amp; 等“二次转义”展示
      img.alt = image && image.name ? String(image.name) : ''

      const removeBtn = document.createElement('button')
      removeBtn.className = 'image-remove'
      removeBtn.textContent = '×'
      removeBtn.addEventListener('click', () => removeImage(index))

      div.appendChild(img)
      div.appendChild(removeBtn)
      container.appendChild(div)
    })
  }

  function removeImage(index) {
    uploadedImages.splice(index, 1)
    renderUploadedImages()
    if (activeTaskId) {
      syncImagesToTaskCache(activeTaskId)
    }
  }

  function dataURLtoBlob(dataURL) {
    const arr = dataURL.split(',')
    const mime = arr[0].match(/:(.*?);/)[1]
    const bstr = atob(arr[1])
    let n = bstr.length
    const u8arr = new Uint8Array(n)
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n)
    }
    return new Blob([u8arr], { type: mime })
  }

  // 监听消息
  window.addEventListener('message', event => {
    const message = event.data
    switch (message.type) {
      case 'refresh':
        requestImmediateRefresh()
        break
      case 'clipboardText':
        handleClipboardTextMessage(message)
        break
    }
  })

  // 清理
  window.addEventListener('beforeunload', () => {
    stopPolling()
    stopCountdown()
    clearAllTabCountdowns()
    if (themeObserver) {
      try {
        themeObserver.disconnect()
      } catch (e) {
        // 忽略
      }
      themeObserver = null
    }
    try {
      const settingsUi = getSettingsUiModule()
      if (settingsUi && typeof settingsUi.dispose === 'function') {
        settingsUi.dispose()
      }
    } catch (e) {
      // 忽略
    }
  })

  function reportFatalError(prefix, err) {
    try {
      const msg = prefix + (err && err.message ? err.message : String(err))
      try {
        vscode.postMessage({ type: 'log', level: 'error', message: msg })
      } catch (e) {
        /* 忽略 */
      }
      try {
        vscode.postMessage({ type: 'error', message: msg })
      } catch (e) {
        /* 忽略 */
      }
      try {
        postNotificationEvent({
          title: 'AI Intervention Agent',
          message: msg,
          trigger: 'immediate',
          types: ['vscode'],
          metadata: { presentation: 'toast', severity: 'error', timeoutMs: 6000 },
          source: 'webview-ui',
          dedupeKey: 'fatal:' + String(prefix || '').slice(0, 30)
        })
      } catch (e) {
        // 忽略
      }
      try {
        showToast(msg, {
          kind: 'error',
          timeoutMs: 3500,
          dedupeKey: 'fatal:' + String(prefix || '').slice(0, 30)
        })
      } catch (e) {
        /* 忽略 */
      }
    } catch (e) {
      // 忽略
    }
  }

  // 兜底捕获（避免脚本异常导致 UI 停在 loading 而无提示）
  window.addEventListener('error', e => {
    reportFatalError('未捕获异常: ', e && e.error ? e.error : e)
    try {
      hideTabs()
      showNoContent()
    } catch (e2) {
      /* 忽略 */
    }
  })
  window.addEventListener('unhandledrejection', e => {
    reportFatalError('未处理 Promise 拒绝: ', e && e.reason ? e.reason : e)
    try {
      hideTabs()
      showNoContent()
    } catch (e2) {
      /* 忽略 */
    }
  })

  // 启动
  try {
    init()
  } catch (e) {
    reportFatalError('初始化失败: ', e)
    try {
      hideTabs()
      showNoContent()
    } catch (e2) {
      /* 忽略 */
    }
  }
})()
