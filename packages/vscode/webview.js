const vscode = require('vscode')
const fs = require('fs')
const { createLogger } = require('./logger')
const { AppleScriptExecutor } = require('./applescript-executor')
const { NotificationCenter } = require('./notification-center')
const { NotificationType } = require('./notification-models')
const {
  VSCodeApiNotificationProvider,
  AppleScriptNotificationProvider
} = require('./notification-providers')

// 扩展元信息（用于在 Webview 中显示版本号 / GitHub）
const EXT_GITHUB_URL = 'https://github.com/XIADENGMA/ai-intervention-agent'
let EXT_VERSION = '0.0.0'
try {
  EXT_VERSION = require('./package.json').version || EXT_VERSION
} catch {
  // 忽略：打包/测试环境下可能读取不到版本号
}

// 生成 CSP nonce（避免使用 'unsafe-inline' 导致的脚本注入风险）
function getNonce(length = 32) {
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let text = ''
  for (let i = 0; i < length; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length))
  }
  return text
}

function safeReadTextFile(uri) {
  try {
    if (!uri || !uri.fsPath) return ''
    return fs.readFileSync(uri.fsPath, 'utf8')
  } catch {
    return ''
  }
}

// 防止把 JSON/字符串直接注入 <script> 时出现 </script> 提前闭合等问题
function safeJsonForInlineScript(value) {
  try {
    return JSON.stringify(value).replace(/</g, '\\u003c')
  } catch {
    return 'null'
  }
}

function safeStringForInlineScript(value) {
  try {
    return JSON.stringify(String(value ?? '')).replace(/</g, '\\u003c')
  } catch {
    return '""'
  }
}

/**
 * AI交互代理的Webview视图提供器
 *
 * 功能说明：
 * - 提供侧边栏webview视图，展示任务反馈界面
 * - 完全独立实现HTML/CSS/JS，无需iframe
 * - 支持多任务标签页切换和倒计时显示
 * - 实现与本地服务器的轮询通信机制
 */
class WebviewProvider {
  constructor(
    extensionUri,
    outputChannel,
    serverUrl = 'http://localhost:8080',
    onVisibilityChanged,
    onTasksStatsChanged
  ) {
    this._extensionUri = extensionUri
    this._outputChannel = outputChannel
    this._logger = createLogger(outputChannel, {
      component: 'ext:webview',
      getLevel: () => {
        try {
          const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
          return cfg.get('logLevel', 'info')
        } catch {
          return 'info'
        }
      }
    })
    this._appleScriptLogger = this._logger.child('applescript')
    this._appleScriptExecutor = new AppleScriptExecutor({ logger: this._appleScriptLogger })
    this._notificationLogger = this._logger.child('notify')
    this._notificationCenter = new NotificationCenter({ logger: this._notificationLogger })
    this._vscodeNotificationProvider = new VSCodeApiNotificationProvider({
      logger: this._notificationLogger.child('vscode')
    })
    this._macosNativeNotificationProvider = new AppleScriptNotificationProvider({
      logger: this._appleScriptLogger,
      executor: this._appleScriptExecutor
    })
    this._notificationCenter.registerProvider(NotificationType.VSCODE, this._vscodeNotificationProvider)
    this._notificationCenter.registerProvider(
      NotificationType.MACOS_NATIVE,
      this._macosNativeNotificationProvider
    )
    this._serverUrl = serverUrl
    this._onVisibilityChanged =
      typeof onVisibilityChanged === 'function' ? onVisibilityChanged : null
    this._onTasksStatsChanged =
      typeof onTasksStatsChanged === 'function' ? onTasksStatsChanged : null
    this._view = null
    this._disposables = []
    this._lastServerStatus = null
    // 仅用于日志降噪：首次“未连接”通常是初始化瞬态，不必在 info 下刷屏
    this._hasEverConnected = false
    this._webviewReady = false
    this._webviewReadyTimer = null
    // macOS 原生通知“点击打开面板”兜底：
    // AppleScript 原生通知没有点击回调；这里通过“通知触发时若宿主未聚焦则 arm，一旦宿主重新聚焦则自动打开面板”来近似实现。
    this._revealPanelUntilMs = 0
  }

  _log(message) {
    try {
      if (this._logger && typeof this._logger.info === 'function') {
        this._logger.info(String(message))
      }
    } catch {
      // 忽略：日志系统异常不应影响主流程
    }
  }

  dispose() {
    // 注意：该 provider 会被 VSCode 在停用时释放；这里做显式兜底，避免定时器/引用残留
    try {
      this._webviewReady = false
      if (this._webviewReadyTimer) {
        clearTimeout(this._webviewReadyTimer)
        this._webviewReadyTimer = null
      }
    } catch {
      // 忽略
    }

    try {
      for (const d of this._disposables) {
        try {
          d.dispose()
        } catch {
          // 忽略
        }
      }
    } finally {
      this._disposables = []
    }

    try {
      if (this._onVisibilityChanged) {
        this._onVisibilityChanged(false)
      }
    } catch {
      // 忽略
    }

    this._view = null
    this._lastServerStatus = null
  }

  resolveWebviewView(webviewView) {
    // 精简日志：只在首次初始化时输出
    this._view = webviewView

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    }
    // 精简日志：移除冗余输出

    /* 监听视图可见性变化 - 当视图变为可见时刷新数据 */
    webviewView.onDidChangeVisibility(() => {
      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'webview.visibility',
            { visible: !!webviewView.visible },
            { level: 'debug' }
          )
        } else {
          this._log(`[事件] Webview 可见性变化: ${webviewView.visible ? '可见' : '隐藏'}`)
        }
      } catch {
        this._log(`[事件] Webview 可见性变化: ${webviewView.visible ? '可见' : '隐藏'}`)
      }
      if (this._onVisibilityChanged) {
        this._onVisibilityChanged(!!webviewView.visible)
      }
      if (webviewView.visible) {
        this._sendMessage({ type: 'refresh' })
      }
    })

    /* 监听视图销毁事件 - 释放所有资源和事件监听器 */
    webviewView.onDidDispose(() => {
      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event('webview.disposed', {}, { level: 'info' })
        } else {
          this._log('[事件] Webview 已销毁')
        }
      } catch {
        this._log('[事件] Webview 已销毁')
      }
      if (this._onVisibilityChanged) {
        this._onVisibilityChanged(false)
      }

      // 清理 ready watchdog（避免 view 被销毁后仍触发日志/回调）
      try {
        this._webviewReady = false
        if (this._webviewReadyTimer) {
          clearTimeout(this._webviewReadyTimer)
          this._webviewReadyTimer = null
        }
      } catch {
        // 忽略
      }

      // 释放所有 subscriptions
      try {
        for (const d of this._disposables) {
          try {
            d.dispose()
          } catch {
            // 忽略：单个 disposable 失败不应影响其它清理
          }
        }
      } finally {
        this._disposables = []
      }

      // 断开引用，避免 retainContextWhenHidden 或重建视图时的潜在泄漏
      this._view = null
      this._lastServerStatus = null
    })

    // 首次解析时同步一次可见性状态
    if (this._onVisibilityChanged) {
      this._onVisibilityChanged(!!webviewView.visible)
    }

    /* 生成并设置webview的HTML内容 */
    const html = this._getHtmlContent(webviewView.webview)
    // 精简日志：移除 HTML 长度输出

    webviewView.webview.html = html
    // 精简日志：移除 HTML 设置输出

    // 诊断：统计 HTML 中的 script 标签数量/反引号数量（反引号可能导致部分 Webview 注入失败）
    try {
      const scriptCount = (html.match(/<script\b/gi) || []).length
      if (this._logger && typeof this._logger.debug === 'function') {
        this._logger.debug(`Webview HTML script 标签数量: ${scriptCount}`)
      }
      const tickCount = (html.match(/`/g) || []).length
      if (tickCount > 0 && this._logger && typeof this._logger.warn === 'function') {
        this._logger.warn(
          `Webview HTML 包含 ${tickCount} 个反引号字符：可能导致注入失败（建议继续外链化/运行时生成）`
        )
      }
    } catch {
      // 忽略：诊断日志失败不应影响 Webview 初始化
    }

    // 诊断：若 Webview 脚本未执行/未上报 ready，会导致面板永远停在“连接中...”
    this._webviewReady = false
    if (this._webviewReadyTimer) {
      clearTimeout(this._webviewReadyTimer)
      this._webviewReadyTimer = null
    }
    this._webviewReadyTimer = setTimeout(() => {
      if (!this._webviewReady && this._logger && typeof this._logger.warn === 'function') {
        try {
          if (typeof this._logger.event === 'function') {
            this._logger.event(
              'webview.ready_timeout',
              { timeoutMs: 2500, webviewReady: false },
              { level: 'warn', message: 'Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）' }
            )
          } else {
            this._logger.warn('Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）')
          }
        } catch {
          this._logger.warn('Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）')
        }
      }
    }, 2500)

    /* 监听来自webview的消息 - 处理日志、错误、状态更新等消息 */
    webviewView.webview.onDidReceiveMessage(
      message => {
        this._handleMessage(message)
      },
      null,
      this._disposables
    )

    // 默认 info 下不刷此日志：以 “Webview 脚本 ready” 作为真正可用的信号
    try {
      if (this._logger && typeof this._logger.debug === 'function') {
        this._logger.debug('Webview 已就绪')
      }
    } catch {
      // 忽略：日志系统异常不应影响主流程
    }
  }

  updateServerUrl(serverUrl) {
    this._serverUrl = serverUrl
    if (this._view && this._view.webview) {
      // 重新生成 HTML，确保 CSP 与 SERVER_URL 常量同步更新
      this._view.webview.html = this._getHtmlContent(this._view.webview)
    }
  }

  _handleMessage(message) {
    switch (message.type) {
      case 'log':
        // Webview 侧按需上报关键日志（默认 debug；允许携带 level=info/warn/error）
        try {
          const levelRaw = message && message.level ? String(message.level) : 'debug'
          const level = levelRaw.toLowerCase()
          const text = message && message.message ? String(message.message) : ''
          if (!text) break

          if (level === 'error' && this._logger && typeof this._logger.error === 'function') {
            this._logger.error(text)
          } else if (
            (level === 'warn' || level === 'warning') &&
            this._logger &&
            typeof this._logger.warn === 'function'
          ) {
            this._logger.warn(text)
          } else if (level === 'info' && this._logger && typeof this._logger.info === 'function') {
            this._logger.info(text)
          } else if (this._logger && typeof this._logger.debug === 'function') {
            this._logger.debug(text)
          }
        } catch {
          // 忽略：日志系统异常不应影响主流程
        }
        break
      case 'error':
        try {
          if (this._logger && typeof this._logger.error === 'function') {
            this._logger.error(String(message.message))
          } else {
            this._log(`[错误] ${message.message}`)
          }
        } catch {
          // 忽略：日志系统异常不应影响主流程
        }
        break
      case 'ready':
        this._webviewReady = true
        if (this._webviewReadyTimer) {
          clearTimeout(this._webviewReadyTimer)
          this._webviewReadyTimer = null
        }
        try {
          if (this._logger && typeof this._logger.event === 'function') {
            this._logger.event('webview.ready', { ready: true }, { level: 'info' })
          } else {
            this._log('Webview 脚本 ready')
          }
        } catch {
          this._log('Webview 脚本 ready')
        }
        break
      case 'tasksStats':
        try {
          const connected = !!(message && message.connected)
          const active =
            message && typeof message.active === 'number' && Number.isFinite(message.active)
              ? Math.max(0, Math.floor(message.active))
              : 0
          const pending =
            message && typeof message.pending === 'number' && Number.isFinite(message.pending)
              ? Math.max(0, Math.floor(message.pending))
              : 0
          const total =
            message && typeof message.total === 'number' && Number.isFinite(message.total)
              ? Math.max(0, Math.floor(message.total))
              : active + pending

          if (this._onTasksStatsChanged) {
            this._onTasksStatsChanged({ connected, active, pending, total })
          }
        } catch {
          // 忽略：消息处理失败不应影响主流程
        }
        break
      case 'serverStatus':
        // 只在状态变化时记录，避免刷屏
        try {
          const connected = !!(message && message.connected)
          if (connected !== this._lastServerStatus) {
            const prev = this._lastServerStatus
            this._lastServerStatus = connected
            // 日志降噪策略：
            // - 首次“连接断开”多为初始化瞬态：仅 debug
            // - 首次“已连接”：info
            // - 曾连接过后再断开：warn（重要）
            if (connected) {
              this._hasEverConnected = true
              if (this._logger && typeof this._logger.event === 'function') {
                this._logger.event(
                  'webview.server_status',
                  { connected: true, prev: prev === null ? 'null' : prev },
                  { level: prev === false ? 'info' : 'debug' }
                )
              } else {
                this._log('[事件] Webview 服务器状态: 已连接')
              }
            } else if (this._hasEverConnected) {
              if (this._logger && typeof this._logger.event === 'function') {
                this._logger.event(
                  'webview.server_status',
                  { connected: false, prev: prev === null ? 'null' : prev },
                  { level: 'warn' }
                )
              } else if (this._logger && typeof this._logger.warn === 'function') {
                this._logger.warn('[事件] Webview 服务器状态: 连接断开')
              } else {
                this._log('[事件] Webview 服务器状态: 连接断开')
              }
            } else if (this._logger && typeof this._logger.debug === 'function') {
              if (typeof this._logger.event === 'function') {
                this._logger.event(
                  'webview.server_status',
                  { connected: false, prev: prev === null ? 'null' : prev },
                  { level: 'debug' }
                )
              } else {
                this._logger.debug('[事件] Webview 服务器状态: 连接断开')
              }
            }
          }
        } catch {
          // 忽略：状态日志失败不应影响主流程
        }
        break
      case 'notify':
        this._handleNotify(message)
        break
      case 'showInfo':
        this._dispatchNotificationEvent({
          title: 'AI Intervention Agent',
          message: message && message.message ? String(message.message) : '',
          trigger: 'immediate',
          types: [NotificationType.VSCODE],
          metadata: { presentation: 'statusBar', severity: 'info', timeoutMs: 3000 },
          source: 'webview',
          dedupeKey:
            message && message.message ? `status:${String(message.message).slice(0, 200)}` : ''
        })
        break
      case 'requestClipboardText':
        this._handleRequestClipboardText(message)
        break
      case 'showMacOSNativeNotification':
        this._handleShowMacOSNativeNotification(message)
        break
      case 'testMacOSNativeNotification':
        this._handleTestMacOSNativeNotification(message)
        break
      case 'writeClipboardText':
        this._handleWriteClipboardText(message)
        break
      default:
        // 忽略未知消息类型
        break
    }
  }

  _dispatchNotificationEvent(event) {
    try {
      if (!this._notificationCenter || typeof this._notificationCenter.dispatch !== 'function')
        return
      try {
        this._armRevealPanelOnNextFocus(event)
      } catch {
        // 忽略
      }
      Promise.resolve()
        .then(() => this._notificationCenter.dispatch(event))
        .then(result => {
          try {
            if (!this._notificationLogger || typeof this._notificationLogger.event !== 'function')
              return
            const evt = result && result.event ? result.event : event
            const types = evt && Array.isArray(evt.types) ? evt.types.map(t => String(t)) : []
            const delivered = result && result.delivered ? result.delivered : {}
            const skipped = !!(result && result.skipped)
            const reason = result && result.reason ? String(result.reason) : ''
            const eventId = evt && evt.id ? String(evt.id) : ''
            this._notificationLogger.event(
              'notify.dispatch',
              {
                eventId,
                types,
                skipped,
                reason,
                delivered
              },
              { level: 'debug' }
            )
          } catch {
            // 忽略：日志系统异常不应影响通知流程
          }
        })
        .catch(e => {
          try {
            if (!this._notificationLogger || typeof this._notificationLogger.event !== 'function')
              return
            const msg = e && e.message ? String(e.message) : String(e)
            this._notificationLogger.event('notify.dispatch_failed', { error: msg }, { level: 'warn' })
          } catch {
            // 忽略
          }
        })
    } catch {
      // 忽略：通知分发失败不应影响主流程
    }
  }

  _armRevealPanelOnNextFocus(event) {
    try {
      const evt = event && typeof event === 'object' ? event : {}
      const types = evt && Array.isArray(evt.types) ? evt.types.map(t => String(t)) : []
      if (!types.includes(NotificationType.MACOS_NATIVE)) return

      const md = evt && evt.metadata && typeof evt.metadata === 'object' ? evt.metadata : {}
      const isTest = !!(md && md.isTest)
      const kind = md && md.kind ? String(md.kind) : ''
      if (isTest) return
      if (kind !== 'new_tasks') return

      // 仅在宿主当前未聚焦时 arm：避免用户正在编辑时“回到窗口”被强制打开面板
      const focused = !!(
        vscode &&
        vscode.window &&
        vscode.window.state &&
        vscode.window.state.focused
      )
      if (focused) return

      this._revealPanelUntilMs = Date.now() + 30000
    } catch {
      // 忽略
    }
  }

  async onWindowFocusChanged(focused) {
    try {
      if (!focused) return
      const until = typeof this._revealPanelUntilMs === 'number' ? this._revealPanelUntilMs : 0
      if (!until || Date.now() > until) return
      // 消费一次
      this._revealPanelUntilMs = 0
      await vscode.commands.executeCommand('ai-intervention-agent.openPanel')
    } catch {
      // 忽略
    }
  }

  _handleNotify(message) {
    const event = message && message.event ? message.event : null
    if (!event) return
    this._dispatchNotificationEvent(event)
  }

  _handleShowMacOSNativeNotification(message) {
    const title =
      message && typeof message.title === 'string' && message.title
        ? String(message.title)
        : 'AI Intervention Agent'
    const body =
      message && typeof message.message === 'string' && message.message
        ? String(message.message)
        : ''
    const isTest = !!(message && message.isTest)
    if (!body.trim()) return

    this._dispatchNotificationEvent({
      title,
      message: body,
      trigger: 'immediate',
      types: [NotificationType.MACOS_NATIVE],
      metadata: { isTest: !!isTest },
      source: 'webview'
    })
  }

  _handleTestMacOSNativeNotification(message) {
    const requestId = message && message.requestId ? String(message.requestId) : ''
    const title =
      message && typeof message.title === 'string' && message.title
        ? String(message.title)
        : 'AI Intervention Agent 测试'
    const body =
      message && typeof message.message === 'string' && message.message
        ? String(message.message)
        : '这是一条 macOS 原生通知测试'

    if (!requestId) return
    if (!body.trim()) {
      this._sendMessage({
        type: 'testMacOSNativeNotificationResult',
        requestId,
        ok: false,
        error: 'message 不能为空'
      })
      return
    }

    const platform = process.platform
    const env = vscode && vscode.env ? vscode.env : null
    const appName = env && typeof env.appName === 'string' ? String(env.appName) : ''

    const event = {
      title,
      message: body,
      trigger: 'immediate',
      types: [NotificationType.MACOS_NATIVE],
      metadata: { isTest: true, diagnostic: true, skipBundleInjection: true },
      source: 'webview'
    }

    Promise.resolve()
      .then(() => this._notificationCenter.dispatch(event))
      .then(result => {
        const delivered = result && result.delivered ? result.delivered : {}
        const ok = !!(delivered && delivered[NotificationType.MACOS_NATIVE])
        let diagnostic = null
        try {
          diagnostic =
            this._macosNativeNotificationProvider &&
            typeof this._macosNativeNotificationProvider.getLastDiagnostic === 'function'
              ? this._macosNativeNotificationProvider.getLastDiagnostic()
              : null
        } catch {
          diagnostic = null
        }

        const hints = []
        try {
          if (platform !== 'darwin') {
            hints.push('当前平台不是 macOS：macos_native 通知会被跳过')
          } else if (ok) {
            // 成功但用户可能“看不到”：多数是系统通知开关/Focus 或发送方归属导致
            const bundleId = diagnostic && diagnostic.bundleId ? String(diagnostic.bundleId) : ''
            const injected =
              diagnostic &&
              diagnostic.injectedEnvKeys &&
              Array.isArray(diagnostic.injectedEnvKeys) &&
              diagnostic.injectedEnvKeys.includes('__CFBundleIdentifier')
            if (bundleId && injected) {
              hints.push(
                `已尝试将通知归属到宿主应用（bundleId=${bundleId}）。若未看到：请检查 系统设置 → 通知 中对应应用是否允许通知，以及 Focus/勿扰模式。`
              )
            } else {
              hints.push(
                '已执行发送逻辑但你仍未看到通知：请检查 系统设置 → 通知（可能显示为“脚本编辑器/Script Editor”）以及 Focus/勿扰模式。'
              )
            }
          } else {
            hints.push('发送失败：请展开 diagnostic 查看 code/stderr/exitCode，并按提示排查系统权限/环境。')
          }
        } catch {
          // 忽略
        }

        this._sendMessage({
          type: 'testMacOSNativeNotificationResult',
          requestId,
          ok,
          delivered,
          platform,
          appName,
          diagnostic,
          hints
        })
      })
      .catch(e => {
        const msg = e && e.message ? String(e.message) : String(e)
        this._sendMessage({
          type: 'testMacOSNativeNotificationResult',
          requestId,
          ok: false,
          error: msg,
          platform,
          appName
        })
      })
  }

  _handleWriteClipboardText(message) {
    const requestId = message && message.requestId ? String(message.requestId) : ''
    const textRaw = message && typeof message.text === 'string' ? String(message.text) : ''
    const text = textRaw.length > 50000 ? textRaw.slice(0, 50000) : textRaw
    Promise.resolve()
      .then(() => vscode.env.clipboard.writeText(text))
      .then(() => {
        this._sendMessage({ type: 'writeClipboardTextResult', requestId, ok: true })
      })
      .catch(e => {
        const msg = e && e.message ? String(e.message) : String(e)
        this._sendMessage({ type: 'writeClipboardTextResult', requestId, ok: false, error: msg })
      })
  }

  _handleRequestClipboardText(message) {
    const requestId = message && message.requestId ? String(message.requestId) : ''
    Promise.resolve()
      .then(() => vscode.env.clipboard.readText())
      .then(text => {
        const clip = text ? String(text) : ''
        if (!clip.trim()) {
          this._sendMessage({
            type: 'clipboardText',
            success: false,
            requestId,
            error: '剪贴板为空，请先复制一段代码。'
          })
          return
        }

        this._sendMessage({
          type: 'clipboardText',
          success: true,
          requestId,
          text: clip
        })
      })
      .catch(e => {
        this._sendMessage({
          type: 'clipboardText',
          success: false,
          requestId,
          error: e && e.message ? String(e.message) : String(e)
        })
      })
  }

  _sendMessage(message) {
    if (this._view) {
      this._view.webview.postMessage(message)
    }
  }

  _getHtmlContent(webview) {
    const serverUrl = this._serverUrl || 'http://localhost:8080'
    const cspSource = webview.cspSource
    // 重要：不要把 marked/prism 以“内联脚本”拼进 HTML（其内容包含反引号等字符，部分 Webview 注入实现会因此失败）
    // 改为外链加载（同样使用 nonce，CSP 更安全且更稳定）
    const markedJsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'marked.min.js')
    )
    const prismBootstrapUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'prism-bootstrap.js')
    )
    const prismJsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'prism.min.js'))
    const prismCssUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'prism.min.css')
    )
    const webviewCssUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'webview.css')
    )
    const mathjaxScriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'mathjax', 'tex-mml-svg.js')
    )
    const webviewHelpersUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'webview-helpers.js')
    )
    const webviewUiUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'webview-ui.js')
    )
    const activityIconUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'activity-icon.svg')
    )
    const webviewNotifyCoreUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'webview-notify-core.js')
    )
    const webviewSettingsUiUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'webview-settings-ui.js')
    )
    const extensionVersion = EXT_VERSION || '0.0.0'
    const githubUrl = EXT_GITHUB_URL || ''
    const githubUrlDisplay = githubUrl ? githubUrl.replace(/^https?:\/\//i, '') : ''
    const lottieJsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'lottie.min.js')
    )
    const noContentLottieJsonUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'lottie', 'sprout.json')
    )
    const nonce = getNonce()

    // 精简日志：移除 HTML 生成相关冗余日志

    // 稳定性：在 Cursor/VSCode 的不同 Webview 协议/CSP 组合下，fetch 本地资源可能仍被 connect-src 拦截。
    // 这里把“无内容页”所需的本地资源（SVG/JSON）直接内联注入，Webview 侧优先使用内联数据，避免永久降级。
    const activityIconSvgText = safeReadTextFile(
      vscode.Uri.joinPath(this._extensionUri, 'activity-icon.svg')
    )
    let noContentHourglassLottieData = null
    try {
      const hourglassJsonText = safeReadTextFile(
        vscode.Uri.joinPath(this._extensionUri, 'lottie', 'sprout.json')
      )
      noContentHourglassLottieData = hourglassJsonText ? JSON.parse(hourglassJsonText) : null
    } catch {
      noContentHourglassLottieData = null
    }
    const inlineNoContentFallbackSvgLiteral = safeStringForInlineScript(activityIconSvgText)
    const inlineNoContentLottieDataLiteral = noContentHourglassLottieData
      ? safeJsonForInlineScript(noContentHourglassLottieData)
      : 'null'

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; connect-src ${serverUrl} ${cspSource} 'self'; style-src ${cspSource}; script-src 'nonce-${nonce}'; img-src data: ${serverUrl} https: ${cspSource}; font-src ${serverUrl} data: ${cspSource}; object-src 'none'; frame-src 'none';">
    <meta id="aiia-config" data-server-url="${serverUrl}" data-csp-nonce="${nonce}" data-lottie-lib-url="${lottieJsUri}" data-no-content-lottie-json-url="${noContentLottieJsonUri}" data-no-content-fallback-svg-url="${activityIconUri}" data-mathjax-script-url="${mathjaxScriptUri}" data-marked-js-url="${markedJsUri}" data-prism-js-url="${prismJsUri}" data-notify-core-js-url="${webviewNotifyCoreUri}" data-settings-ui-js-url="${webviewSettingsUiUri}">
    <script nonce="${nonce}">window.__AIIA_NO_CONTENT_FALLBACK_SVG=${inlineNoContentFallbackSvgLiteral};window.__AIIA_NO_CONTENT_LOTTIE_DATA=${inlineNoContentLottieDataLiteral};</script>
    <title>AI Intervention Agent</title>
    <link rel="stylesheet" href="${prismCssUri}">
    <link rel="stylesheet" href="${webviewCssUri}">
</head>
<body>
    <div class="container">
        <!-- Task tabs with status indicator -->
        <div class="tabs-container hidden" id="tasksTabsContainer">
            <div class="status-indicator">
                <div class="breathing-light" id="statusLight" title="服务器连接状态"></div>
            </div>
            <!-- Task tabs will be dynamically generated here -->
            <button class="settings-btn" id="settingsBtn" title="通知设置" aria-label="通知设置">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                    <circle cx="12" cy="12" r="3"></circle>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                </svg>
            </button>
        </div>

        <!-- Main content -->
        <div class="content" id="mainContent">
            <!-- Loading state -->
            <div class="loading hidden" id="loadingState">
                <div class="spinner"></div>
                <div>正在连接服务器…</div>
            </div>

            <!-- No content state -->
            <div class="no-content" id="noContentState">
                <button class="settings-btn no-content-settings-btn" id="settingsBtnNoContent" title="通知设置" aria-label="通知设置">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                        <circle cx="12" cy="12" r="3"></circle>
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                    </svg>
                </button>
                <div class="no-content-icon" id="hourglass-lottie" aria-hidden="true">🌱</div>
                <div class="title">暂无交互反馈请求</div>
                <div class="status-indicator-standalone">
                    <div class="breathing-light" id="statusLightStandalone" title="服务器连接状态"></div>
                    <span id="statusTextStandalone">连接中…</span>
                </div>
                <div class="no-content-progress" id="noContentProgress">
                    <div class="no-content-progress-bar"></div>
                </div>
            </div>

            <!-- Feedback form -->
            <div class="feedback-form hidden" id="feedbackForm">
                <!-- Scrollable content -->
                <div class="scrollable-content">
                    <!-- Markdown content -->
                    <div class="markdown-content" id="markdownContent"></div>

                    <!-- Predefined options -->
                    <div class="form-section hidden" id="optionsSection">
                        <div class="form-label">选项（可多选）</div>
                        <div class="options-container" id="optionsContainer"></div>
                    </div>

                </div>

                <!-- Fixed bottom input -->
                <div class="fixed-input-area">
                    <!-- Image preview area (above textarea) -->
                    <div class="uploaded-images" id="uploadedImages"></div>

                    <div class="textarea-wrapper">
                        <div class="textarea-resize-handle" id="resizeHandle"></div>
                        <textarea
                            class="feedback-textarea"
                            id="feedbackText"
                            placeholder="请输入反馈内容（支持粘贴图片）…"
                        ></textarea>

                        <!-- Hidden file input -->
                        <input type="file" id="imageInput" accept="image/*" multiple class="hidden">

                        <!-- Button group (upload + submit) -->
                        <div class="input-buttons">
                            <button type="button" class="insert-code-btn" id="insertCodeBtn" title="插入代码（从剪贴板）" aria-label="插入代码">
                                <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                                    <polyline points="16 18 22 12 16 6"></polyline>
                                    <polyline points="8 6 2 12 8 18"></polyline>
                                    <line x1="14" y1="4" x2="10" y2="20"></line>
                                </svg>
                            </button>
                            <button type="button" class="upload-btn" id="uploadBtn" title="上传图片" aria-label="上传图片">
                                <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
                                    <path fill-rule="evenodd" clip-rule="evenodd" d="M3 4.5C3 3.67157 3.67157 3 4.5 3H15.5C16.3284 3 17 3.67157 17 4.5V15.5C17 16.3284 16.3284 17 15.5 17H4.5C3.67157 17 3 16.3284 3 15.5V4.5ZM4.5 4C4.22386 4 4 4.22386 4 4.5V12.2929L6.64645 9.64645C6.84171 9.45118 7.15829 9.45118 7.35355 9.64645L10 12.2929L13.1464 9.14645C13.3417 8.95118 13.6583 8.95118 13.8536 9.14645L16 11.2929V4.5C16 4.22386 15.7761 4 15.5 4H4.5ZM16 12.7071L13.5 10.2071L10.3536 13.3536C10.1583 13.5488 9.84171 13.5488 9.64645 13.3536L7 10.7071L4 13.7071V15.5C4 15.7761 4.22386 16 4.5 16H15.5C15.7761 16 16 15.7761 16 15.5V12.7071ZM7 7.5C7 6.94772 7.44772 6.5 8 6.5C8.55228 6.5 9 6.94772 9 7.5C9 8.05228 8.55228 8.5 8 8.5C7.44772 8.5 7 8.05228 7 7.5Z" fill="currentColor" />
                                </svg>
                            </button>
                            <button type="button" class="submit-btn-embedded" id="submitBtn" title="提交反馈" aria-label="提交反馈">
                                <svg class="btn-icon submit-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" aria-hidden="true" focusable="false">
                                    <path d="M19.26 9.77C19.91 9.08 20.92 8.91 21.73 9.32L21.89 9.40L21.94 9.43L22.19 9.63C22.20 9.64 22.22 9.65 22.23 9.66L44.63 30.46C45.05 30.86 45.30 31.42 45.30 32.00C45.30 32.44 45.16 32.86 44.91 33.21C44.90 33.23 44.89 33.24 44.88 33.26L44.66 33.50C44.65 33.52 44.64 33.53 44.63 33.54L22.23 54.34C21.38 55.13 20.05 55.08 19.26 54.23C18.47 53.38 18.52 52.05 19.37 51.26L40.12 32.00L19.37 12.74C19.36 12.73 19.35 12.72 19.34 12.70L19.12 12.46C19.11 12.45 19.10 12.43 19.09 12.42C18.52 11.62 18.57 10.52 19.26 9.77Z" fill="currentColor" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

        <!-- Toast host (in-webview, non-intrusive) -->
        <div class="toast-host" id="toastHost" aria-live="polite" aria-atomic="true"></div>

    <!-- Settings overlay (notification config) -->
    <div class="settings-overlay hidden" id="settingsOverlay">
        <div class="settings-panel" id="settingsPanel" role="dialog" aria-modal="true">
            <div class="settings-header">
                <div class="settings-title">通知设置</div>
                <button class="settings-close" id="settingsClose" title="关闭" aria-label="关闭">
                    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                        <path d="M5 5L15 15"></path>
                        <path d="M15 5L5 15"></path>
                    </svg>
                </button>
            </div>
            <div class="settings-body">
                <label class="settings-toggle">
                    <span>启用通知</span>
                    <input type="checkbox" id="notifyEnabled">
                </label>
                <label class="settings-toggle">
                    <span>Web UI 通知</span>
                    <input type="checkbox" id="notifyWebEnabled">
                </label>
                <label class="settings-toggle">
                    <span>macOS 原生通知</span>
                    <input type="checkbox" id="notifyMacOSNativeEnabled">
                </label>
                <label class="settings-toggle">
                    <span>自动请求浏览器通知权限</span>
                    <input type="checkbox" id="notifyAutoRequestPermission">
                </label>
                <label class="settings-toggle">
                    <span>声音提示</span>
                    <input type="checkbox" id="notifySoundEnabled">
                </label>
                <label class="settings-toggle">
                    <span>静音</span>
                    <input type="checkbox" id="notifySoundMute">
                </label>
                <label class="settings-field">
                    <span class="settings-label">音量（0-100）</span>
                    <input type="number" min="0" max="100" id="notifySoundVolume" placeholder="80">
                </label>

                <div class="settings-divider"></div>

                <label class="settings-toggle">
                    <span>Bark 通知</span>
                    <input type="checkbox" id="notifyBarkEnabled">
                </label>
                <label class="settings-field">
                    <span class="settings-label">Bark URL</span>
                    <input type="text" id="notifyBarkUrl" placeholder="https://api.day.app/push">
                </label>
                <label class="settings-field">
                    <span class="settings-label">Bark Device Key</span>
                    <input type="text" id="notifyBarkDeviceKey" placeholder="必填（测试需要）">
                </label>
                <label class="settings-field">
                    <span class="settings-label">Bark Icon</span>
                    <input type="text" id="notifyBarkIcon" placeholder="可选">
                </label>
                <label class="settings-field">
                    <span class="settings-label">Bark Action</span>
                    <input type="text" id="notifyBarkAction" placeholder="none / URL 等">
                </label>

                <div class="settings-actions">
                    <button class="settings-action secondary" id="settingsTestNativeBtn">测试原生通知</button>
                    <button class="settings-action secondary" id="settingsCopyNativeDiagBtn">复制诊断</button>
                    <button class="settings-action secondary" id="settingsTestBarkBtn">测试 Bark</button>
                    <div class="settings-actions-right">
                        <span class="settings-auto-save" title="修改后会自动同步到服务端">自动保存</span>
                    </div>
                </div>
                <div class="settings-footer" id="settingsFooter">
                    <span class="settings-footer-item">VS Code 插件 v${extensionVersion}</span>
                    <span class="settings-footer-sep">·</span>
                    <span class="settings-footer-item">GitHub:</span>
                    <a class="settings-footer-link" href="${githubUrl}" target="_blank" rel="noopener noreferrer">${githubUrlDisplay}</a>
                </div>
                <div class="settings-hint" id="settingsHint"></div>
            </div>
        </div>
    </div>

    <!-- Prism.js for code highlighting (no inline scripts; CSP-safe) -->
    <script nonce="${nonce}" src="${prismBootstrapUri}"></script>
    <!-- prism.min.js / marked.min.js 由 webview-ui.js 按需懒加载（首屏更快） -->

        <script nonce="${nonce}" src="${webviewHelpersUri}"></script>
        <script nonce="${nonce}" src="${webviewUiUri}"></script>
</body>
</html>`
  }
}

module.exports = { WebviewProvider }
