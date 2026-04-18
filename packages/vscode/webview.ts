import * as vscode from 'vscode'
import * as fs from 'fs'
import { createLogger } from './logger'
import type { Logger } from './logger'
import { AppleScriptExecutor } from './applescript-executor'
import { NotificationCenter } from './notification-center'
import { NotificationType } from './notification-models'
import {
  VSCodeApiNotificationProvider,
  MacOSNativeNotificationProvider
} from './notification-providers'

const EXT_GITHUB_URL = 'https://github.com/XIADENGMA/ai-intervention-agent'

function getNonce(length = 32): string {
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let text = ''
  for (let i = 0; i < length; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length))
  }
  return text
}

function safeReadTextFile(uri: vscode.Uri): string {
  try {
    if (!uri || !uri.fsPath) return ''
    return fs.readFileSync(uri.fsPath, 'utf8')
  } catch {
    return ''
  }
}

function safeJsonForInlineScript(value: unknown): string {
  try {
    return JSON.stringify(value).replace(/</g, '\\u003c')
  } catch {
    return 'null'
  }
}

function safeStringForInlineScript(value: unknown): string {
  try {
    return JSON.stringify(String(value ?? '')).replace(/</g, '\\u003c')
  } catch {
    return '""'
  }
}

interface WebviewMessage {
  type: string
  [key: string]: unknown
}

interface TaskStatsState {
  connected: boolean
  active: number
  pending: number
  total?: number
}

interface NotificationConfig {
  enabled: boolean
  macosNativeEnabled: boolean
}

interface TaskData {
  id: string
  prompt: string
}

type VisibilityCallback = (visible: boolean) => void
type TaskStatsCallback = (stats: TaskStatsState) => void
type TaskIdsCallback = (ids: string[]) => void

/**
 * AI交互代理的Webview视图提供器
 *
 * 功能说明：
 * - 提供侧边栏webview视图，展示任务反馈界面
 * - 完全独立实现HTML/CSS/JS，无需iframe
 * - 支持多任务标签页切换和倒计时显示
 * - 实现与本地服务器的轮询通信机制
 */
export class WebviewProvider implements vscode.WebviewViewProvider {
  private _extensionUri: vscode.Uri
  private _outputChannel: vscode.OutputChannel
  private _logger: Logger
  private _appleScriptLogger: Logger
  private _appleScriptExecutor: AppleScriptExecutor
  private _notificationLogger: Logger
  private _notificationCenter: NotificationCenter
  private _vscodeNotificationProvider: VSCodeApiNotificationProvider
  private _macosNativeNotificationProvider: MacOSNativeNotificationProvider
  private _serverUrl: string
  private _onVisibilityChanged: VisibilityCallback | null
  private _onTasksStatsChanged: TaskStatsCallback | null
  private _onNewTaskIdsFromWebview: TaskIdsCallback | null
  private _onLanguageChanged: ((lang: string) => void) | null
  private _view: vscode.WebviewView | null
  private _disposables: vscode.Disposable[]
  private _lastServerStatus: boolean | null
  private _hasEverConnected: boolean
  private _webviewReady: boolean
  private _webviewReadyTimer: ReturnType<typeof setTimeout> | null
  private _pendingMessages: WebviewMessage[]
  private _pendingMessageLimit: number
  private _revealPanelUntilMs: number
  private _notificationConfig: NotificationConfig | null
  private _notificationConfigFetchedAt: number
  private _notificationConfigFetchPromise: Promise<NotificationConfig | null> | null
  private _cachedServerLang: string | null
  private _cachedLocales: Record<string, Record<string, unknown>>
  private _cachedStaticAssets: { activityIconSvg: string; lottieData: unknown } | null
  private _prefetchServerLangPromise: Promise<void> | null

  constructor(
    extensionUri: vscode.Uri,
    outputChannel: vscode.OutputChannel,
    serverUrl = 'http://localhost:8080',
    onVisibilityChanged?: VisibilityCallback,
    onTasksStatsChanged?: TaskStatsCallback,
    onNewTaskIdsFromWebview?: TaskIdsCallback,
    onLanguageChanged?: (lang: string) => void
  ) {
    this._extensionUri = extensionUri
    this._outputChannel = outputChannel
    this._logger = createLogger(outputChannel, {
      component: 'ext:webview',
      getLevel: () => {
        try {
          const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
          return cfg.get<string>('logLevel', 'info') ?? 'info'
        } catch {
          return 'info'
        }
      }
    })
    this._appleScriptLogger = this._logger.child('applescript')
    this._appleScriptExecutor = new AppleScriptExecutor({ logger: this._appleScriptLogger })
    this._notificationLogger = this._logger.child('notify')
    this._notificationCenter = new NotificationCenter({
      logger: this._notificationLogger,
      dedupeWindowMs: 10000
    })
    this._vscodeNotificationProvider = new VSCodeApiNotificationProvider({
      logger: this._notificationLogger.child('vscode')
    })
    this._macosNativeNotificationProvider = new MacOSNativeNotificationProvider({
      logger: this._appleScriptLogger,
      executor: this._appleScriptExecutor,
      vscodeApi: vscode
    })
    this._notificationCenter.registerProvider(
      NotificationType.VSCODE,
      this._vscodeNotificationProvider
    )
    this._notificationCenter.registerProvider(
      NotificationType.MACOS_NATIVE,
      this._macosNativeNotificationProvider
    )
    this._serverUrl = serverUrl
    this._onVisibilityChanged =
      typeof onVisibilityChanged === 'function' ? onVisibilityChanged : null
    this._onTasksStatsChanged =
      typeof onTasksStatsChanged === 'function' ? onTasksStatsChanged : null
    this._onNewTaskIdsFromWebview =
      typeof onNewTaskIdsFromWebview === 'function' ? onNewTaskIdsFromWebview : null
    this._onLanguageChanged =
      typeof onLanguageChanged === 'function' ? onLanguageChanged : null
    this._view = null
    this._disposables = []
    this._lastServerStatus = null
    this._hasEverConnected = false
    this._webviewReady = false
    this._webviewReadyTimer = null
    this._pendingMessages = []
    this._pendingMessageLimit = 50
    this._revealPanelUntilMs = 0
    this._notificationConfig = null
    this._notificationConfigFetchedAt = 0
    this._notificationConfigFetchPromise = null
    this._cachedServerLang = null
    this._cachedLocales = {}
    this._cachedStaticAssets = null
    this._prefetchServerLangPromise = null
  }

  private async _preloadResources(): Promise<void> {
    const decoder = new TextDecoder('utf-8')
    for (const loc of ['en', 'zh-CN']) {
      if (this._cachedLocales[loc]) continue
      try {
        const uri = vscode.Uri.joinPath(this._extensionUri, 'locales', loc + '.json')
        const bytes = await vscode.workspace.fs.readFile(uri)
        const text = decoder.decode(bytes)
        if (text) this._cachedLocales[loc] = JSON.parse(text) as Record<string, unknown>
      } catch {
        try {
          const text = safeReadTextFile(vscode.Uri.joinPath(this._extensionUri, 'locales', loc + '.json'))
          if (text) this._cachedLocales[loc] = JSON.parse(text) as Record<string, unknown>
        } catch { /* 忽略 */ }
      }
    }
    if (!this._cachedStaticAssets) {
      let svgText = ''
      let lottieData: unknown = null
      try {
        const svgBytes = await vscode.workspace.fs.readFile(
          vscode.Uri.joinPath(this._extensionUri, 'activity-icon.svg')
        )
        svgText = decoder.decode(svgBytes)
      } catch {
        svgText = safeReadTextFile(vscode.Uri.joinPath(this._extensionUri, 'activity-icon.svg'))
      }
      try {
        const lottieBytes = await vscode.workspace.fs.readFile(
          vscode.Uri.joinPath(this._extensionUri, 'lottie', 'sprout.json')
        )
        const raw = decoder.decode(lottieBytes)
        lottieData = raw ? JSON.parse(raw) : null
      } catch {
        try {
          const raw = safeReadTextFile(vscode.Uri.joinPath(this._extensionUri, 'lottie', 'sprout.json'))
          lottieData = raw ? JSON.parse(raw) : null
        } catch { /* 忽略 */ }
      }
      this._cachedStaticAssets = { activityIconSvg: svgText, lottieData }
    }
  }

  private _prefetchServerLanguage(): Promise<void> {
    // 缓存短路：已有结果就不再发请求（updateServerUrl 会清空缓存以便重新预取）
    if (this._cachedServerLang) {
      return Promise.resolve()
    }
    // 单飞锁：并发调用共享同一 Promise，避免对 /api/config 发起重复请求
    if (this._prefetchServerLangPromise) {
      return this._prefetchServerLangPromise
    }
    const task = (async (): Promise<void> => {
      let timer: ReturnType<typeof setTimeout> | null = null
      try {
        const controller = new AbortController()
        // 超时从 3500ms 收紧到 1000ms：localhost 本应毫秒级，失败即降级
        // 不再重试：失败后前端 checkServerStatus 会通过 langDetected 回传语言
        timer = setTimeout(() => controller.abort(), 1000)
        const resp = await fetch(`${this._serverUrl}/api/config`, {
          signal: controller.signal,
          headers: { Accept: 'application/json' }
        })
        clearTimeout(timer)
        timer = null
        if (resp.ok) {
          const data = (await resp.json()) as Record<string, unknown>
          if (data.language && typeof data.language === 'string' && data.language !== 'auto') {
            this._cachedServerLang = data.language
            this._log(`[i18n] 服务器语言预取成功: ${data.language}`)
            if (this._onLanguageChanged) {
              try { this._onLanguageChanged(data.language as string) } catch { /* 忽略 */ }
            }
            return
          }
          this._log('[i18n] 服务器返回 language=auto 或空，使用 vscode.env.language')
          return
        }
        this._log(`[i18n] 服务器响应非 200: ${resp.status}`)
      } catch {
        this._log('[i18n] 语言预取失败，等待前端 langDetected 回传')
      } finally {
        if (timer) clearTimeout(timer)
      }
    })()
    this._prefetchServerLangPromise = task
    // 无论成功失败都清单飞锁，允许 updateServerUrl 后重新预取
    task.finally(() => {
      if (this._prefetchServerLangPromise === task) {
        this._prefetchServerLangPromise = null
      }
    })
    return task
  }

  _log(message: string): void {
    try {
      if (this._logger && typeof this._logger.info === 'function') {
        this._logger.info(String(message))
      }
    } catch {
      // 忽略：日志系统异常不应影响主流程
    }
  }

  dispose(): void {
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
      this._pendingMessages = []
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

  async resolveWebviewView(webviewView: vscode.WebviewView): Promise<void> {
    // 只阻塞本地资源预加载（locales/svg/lottie，首次 ~50ms，二次 ~0ms）
    // 服务器语言预取改为 fire-and-forget，避免服务器不可达时首屏最坏 7.5s 空白
    // 语言纠偏有两条备份链路：
    //   1) _getHtmlContent 先用 vscode.env.language 兜底
    //   2) 前端 checkServerStatus 拿到 language 后通过 langDetected 回传
    await this._preloadResources()
    this._prefetchServerLanguage().catch(() => { /* 忽略：失败不影响首屏 */ })
    this._view = webviewView

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    }

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
            // 忽略：单个 disposable 失败不应影响其它清理
          }
        }
      } finally {
        this._disposables = []
      }

      this._view = null
      this._lastServerStatus = null
    })

    if (this._onVisibilityChanged) {
      this._onVisibilityChanged(!!webviewView.visible)
    }

    const html = this._getHtmlContent(webviewView.webview)

    webviewView.webview.html = html

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
              {
                level: 'warn',
                message: 'Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）'
              }
            )
          } else {
            this._logger.warn('Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）')
          }
        } catch {
          this._logger.warn('Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）')
        }
      }
    }, 2500)

    webviewView.webview.onDidReceiveMessage(
      (message: WebviewMessage) => {
        this._handleMessage(message)
      },
      null,
      this._disposables
    )

    try {
      if (this._logger && typeof this._logger.debug === 'function') {
        this._logger.debug('Webview 已就绪')
      }
    } catch {
      // 忽略：日志系统异常不应影响主流程
    }
  }

  updateServerUrl(serverUrl: string): void {
    this._serverUrl = serverUrl
    this._notificationConfig = null
    this._notificationConfigFetchedAt = 0
    this._notificationConfigFetchPromise = null
    this._cachedServerLang = null
    if (this._view && this._view.webview) {
      try {
        this._webviewReady = false
        if (this._webviewReadyTimer) {
          clearTimeout(this._webviewReadyTimer)
          this._webviewReadyTimer = null
        }
        this._pendingMessages = []
      } catch {
        // 忽略
      }

      const view = this._view
      // 同 resolveWebviewView：不 await 语言预取，避免切换 serverUrl 时首屏阻塞
      this._prefetchServerLanguage().catch(() => { /* 忽略：失败不影响 UI */ })
      this._preloadResources()
        .catch(() => {})
        .finally(() => {
          if (view.webview) view.webview.html = this._getHtmlContent(view.webview)
          this._webviewReadyTimer = setTimeout(() => {
            if (!this._webviewReady && this._logger && typeof this._logger.warn === 'function') {
              try {
                if (typeof this._logger.event === 'function') {
                  this._logger.event(
                    'webview.ready_timeout',
                    { timeoutMs: 2500, webviewReady: false, reason: 'serverUrl_changed' },
                    {
                      level: 'warn',
                      message: 'Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）'
                    }
                  )
                } else {
                  this._logger.warn('Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）')
                }
              } catch {
                this._logger.warn('Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）')
              }
            }
          }, 2500)
        })
    }
  }

  _handleMessage(message: WebviewMessage): void {
    switch (message.type) {
      case 'log':
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
          this._flushPendingMessages()
        } catch {
          // 忽略
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
        try {
          const connected = !!(message && message.connected)
          if (connected !== this._lastServerStatus) {
            const prev = this._lastServerStatus
            this._lastServerStatus = connected
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
      case 'langDetected':
        try {
          const lang = message && typeof (message as Record<string, unknown>).language === 'string'
            ? String((message as Record<string, unknown>).language)
            : ''
          if (lang && lang !== 'auto' && lang !== this._cachedServerLang) {
            this._cachedServerLang = lang
            this._log(`[i18n] 客户端检测到语言: ${lang}`)
            if (this._onLanguageChanged) {
              try { this._onLanguageChanged(lang) } catch { /* 忽略 */ }
            }
            // 前端 applyServerLanguage 已通过 i18n.setLang + retranslateAllI18nElements
            // 就地重翻译（覆盖 data-i18n / data-i18n-title / data-i18n-placeholder /
            // data-i18n-version），host 侧不再重设 webview.html，避免一次 HTML 重建闪烁。
          }
        } catch { /* 忽略 */ }
        break
      default:
        break
    }
  }

  _dispatchNotificationEvent(event: Record<string, unknown>): void {
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
            const evt =
              result && result.event ? (result.event as unknown as Record<string, unknown>) : event
            const types =
              evt && Array.isArray(evt.types) ? (evt.types as unknown[]).map(t => String(t)) : []
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
        .catch((e: unknown) => {
          try {
            if (!this._notificationLogger || typeof this._notificationLogger.event !== 'function')
              return
            const msg = e instanceof Error ? e.message : String(e)
            this._notificationLogger.event(
              'notify.dispatch_failed',
              { error: msg },
              { level: 'warn' }
            )
          } catch {
            // 忽略
          }
        })
    } catch {
      // 忽略：通知分发失败不应影响主流程
    }
  }

  _armRevealPanelOnNextFocus(event: Record<string, unknown>): void {
    try {
      const evt = event && typeof event === 'object' ? event : ({} as Record<string, unknown>)
      const types =
        evt && Array.isArray(evt.types) ? (evt.types as unknown[]).map(t => String(t)) : []
      if (!types.includes(NotificationType.MACOS_NATIVE)) return

      const md =
        evt && evt.metadata && typeof evt.metadata === 'object'
          ? (evt.metadata as Record<string, unknown>)
          : {}
      const isTest = !!(md && md.isTest)
      const kind = md && md.kind ? String(md.kind) : ''
      if (isTest) return
      if (kind !== 'new_tasks') return

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

  async onWindowFocusChanged(focused: boolean): Promise<void> {
    try {
      if (!focused) return
      const until = typeof this._revealPanelUntilMs === 'number' ? this._revealPanelUntilMs : 0
      if (!until || Date.now() > until) return
      this._revealPanelUntilMs = 0
      await vscode.commands.executeCommand('ai-intervention-agent.openPanel')
    } catch {
      // 忽略
    }
  }

  _handleNotify(message: WebviewMessage): void {
    const event = message && message.event ? (message.event as Record<string, unknown>) : null
    if (!event) return
    try {
      if (this._logger && typeof this._logger.debug === 'function') {
        const dk = event.dedupeKey ? String(event.dedupeKey) : ''
        const src = event.source ? String(event.source) : 'webview'
        this._logger.debug(`_handleNotify: source=${src} dedupeKey=${dk}`)
      }
    } catch {
      /* noop */
    }
    this._dispatchNotificationEvent(event)
    try {
      const md =
        event && event.metadata && typeof event.metadata === 'object'
          ? (event.metadata as Record<string, unknown>)
          : {}
      if (md.kind === 'new_tasks' && Array.isArray(md.taskIds) && this._onNewTaskIdsFromWebview) {
        this._onNewTaskIdsFromWebview(md.taskIds as string[])
      }
    } catch {
      // 同步失败不应影响通知流程
    }
  }

  _handleRequestClipboardText(message: WebviewMessage): void {
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
      .catch((e: unknown) => {
        this._sendMessage({
          type: 'clipboardText',
          success: false,
          requestId,
          error: e instanceof Error ? e.message : String(e)
        })
      })
  }

  _sendMessage(message: WebviewMessage): void {
    if (!this._view || !this._view.webview) return

    if (!this._webviewReady) {
      try {
        this._pendingMessages.push(message)
        if (this._pendingMessages.length > this._pendingMessageLimit) {
          this._pendingMessages.splice(0, this._pendingMessages.length - this._pendingMessageLimit)
        }
      } catch {
        // 忽略：缓冲失败不应影响主流程
      }
      return
    }

    this._postMessage(message)
  }

  _postMessage(message: WebviewMessage): void {
    try {
      if (
        this._view &&
        this._view.webview &&
        typeof this._view.webview.postMessage === 'function'
      ) {
        this._view.webview.postMessage(message)
      }
    } catch {
      // 忽略：Webview 通信失败不应影响主流程
    }
  }

  _flushPendingMessages(): void {
    if (!this._webviewReady) return
    if (!this._pendingMessages || this._pendingMessages.length === 0) return
    const batch = this._pendingMessages.slice(0)
    this._pendingMessages = []
    for (const msg of batch) {
      this._postMessage(msg)
    }
  }

  async _fetchNotificationConfig(force?: boolean): Promise<NotificationConfig | null> {
    const now = Date.now()
    if (!force && this._notificationConfig && now - this._notificationConfigFetchedAt < 30000) {
      return this._notificationConfig
    }
    if (this._notificationConfigFetchPromise) return this._notificationConfigFetchPromise

    this._notificationConfigFetchPromise = (async (): Promise<NotificationConfig | null> => {
      try {
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
        const timeoutId = controller
          ? setTimeout(() => {
              try {
                controller.abort()
              } catch {
                /* noop */
              }
            }, 2500)
          : null
        const resp = await fetch(`${this._serverUrl}/api/get-notification-config`, {
          signal: controller ? controller.signal : undefined,
          headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' }
        } as RequestInit)
        if (timeoutId) clearTimeout(timeoutId)
        if (!resp.ok) return this._notificationConfig
        const data = (await resp.json()) as Record<string, unknown>
        const config = data.config as Record<string, unknown> | undefined
        if (data && data.status === 'success' && config) {
          this._notificationConfig = {
            enabled: config.enabled !== false,
            macosNativeEnabled: config.macos_native_enabled !== false
          }
          this._notificationConfigFetchedAt = Date.now()
        }
        return this._notificationConfig
      } catch {
        return this._notificationConfig
      } finally {
        this._notificationConfigFetchPromise = null
      }
    })()
    return this._notificationConfigFetchPromise
  }

  async dispatchNewTaskNotification(taskData: TaskData[]): Promise<void> {
    try {
      const items = Array.isArray(taskData) ? taskData.filter(Boolean) : []
      if (items.length === 0) return

      const ids = items.map(t => (t && t.id) || '').filter(Boolean)
      if (ids.length === 0) return

      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'ext.dispatch_entry',
            {
              ids,
              hasCenter: !!this._notificationCenter,
              serverUrl: this._serverUrl ? 'set' : 'empty'
            },
            { level: 'info' }
          )
        }
      } catch {
        /* noop */
      }

      const config = await this._fetchNotificationConfig()
      const settings = config || { enabled: true, macosNativeEnabled: true }

      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'ext.dispatch_config',
            {
              enabled: settings.enabled,
              macosNative: settings.macosNativeEnabled,
              configCached: !!config
            },
            { level: 'info' }
          )
        }
      } catch {
        /* noop */
      }

      if (settings.enabled === false) {
        try {
          if (this._logger && typeof this._logger.debug === 'function') {
            this._logger.debug('ext.new_task_notify: skipped (enabled=false)')
          }
        } catch {
          /* noop */
        }
        return
      }

      const SUMMARY_MAX_LEN = 120
      const firstPrompt = (items[0] && items[0].prompt) || ''
      const cleaned = firstPrompt
        ? firstPrompt
            .replace(/[\r\n]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim()
        : ''
      const truncated = cleaned.length > SUMMARY_MAX_LEN
      const summary = truncated ? cleaned.slice(0, SUMMARY_MAX_LEN) + '\u2026' : cleaned
      let msg: string
      if (summary) {
        msg =
          ids.length === 1
            ? summary
            : summary + '\uff08\u5171 ' + ids.length + ' \u4e2a\u4efb\u52a1\uff09'
      } else {
        msg =
          ids.length === 1
            ? '\u65b0\u4efb\u52a1\u5df2\u6dfb\u52a0: ' + ids[0]
            : '\u6536\u5230 ' + ids.length + ' \u4e2a\u65b0\u4efb\u52a1'
      }

      const types: string[] = [NotificationType.VSCODE]
      if (settings.macosNativeEnabled) {
        types.push(NotificationType.MACOS_NATIVE)
      }

      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'ext.new_task_notify',
            {
              count: ids.length,
              types: types.join(','),
              macosNative: !!settings.macosNativeEnabled
            },
            { level: 'info' }
          )
        }
      } catch {
        /* noop */
      }

      this._dispatchNotificationEvent({
        title: 'AI \u4ea4\u4e92\u53cd\u9988',
        message: msg,
        trigger: 'immediate',
        types: types,
        metadata: {
          presentation: 'statusBar',
          severity: 'info',
          timeoutMs: 3000,
          isTest: false,
          kind: 'new_tasks',
          taskIds: ids,
          source: 'extension'
        },
        source: 'extension',
        dedupeKey: 'new_tasks:' + ids.join('|')
      })
    } catch (e: unknown) {
      try {
        if (this._logger && typeof this._logger.warn === 'function') {
          this._logger.warn(
            'ext.new_task_notify failed: ' + (e instanceof Error ? e.message : String(e))
          )
        }
      } catch {
        /* noop */
      }
    }
  }

  _getHtmlContent(webview: vscode.Webview): string {
    const serverUrl = this._serverUrl || 'http://localhost:8080'
    const cspSource = webview.cspSource
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
    const i18nJsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'i18n.js'))
    let extensionVersion = '0.0.0'
    try {
      const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
      if (ext?.packageJSON?.version) {
        extensionVersion = String(ext.packageJSON.version)
      }
    } catch {
      // 忽略
    }
    const githubUrl = EXT_GITHUB_URL || ''
    const githubUrlDisplay = githubUrl ? githubUrl.replace(/^https?:\/\//i, '') : ''
    const lottieJsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'lottie.min.js')
    )
    const noContentLottieJsonUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'lottie', 'sprout.json')
    )
    const nonce = getNonce()

    const activityIconSvgText = this._cachedStaticAssets?.activityIconSvg
      || safeReadTextFile(vscode.Uri.joinPath(this._extensionUri, 'activity-icon.svg'))
    const inlineNoContentFallbackSvgLiteral = safeStringForInlineScript(activityIconSvgText)
    // Lottie JSON (445KB) 不再内联进 HTML，改由前端通过 data-no-content-lottie-json-url
    // 懒加载（webview-ui.js 里的 loadNoContentLottieData 走 fetch + force-cache 兜底）。
    // 收益：HTML 体积 ~500KB → ~50KB，resolveWebviewView 与 langDetected re-render 更快。
    const inlineNoContentLottieDataLiteral = 'null'

    let i18nLang = 'en'
    if (this._cachedServerLang) {
      i18nLang = this._cachedServerLang.toLowerCase().indexOf('zh') === 0 ? 'zh-CN' : 'en'
    } else {
      try {
        const vsLang = vscode.env.language || ''
        i18nLang = vsLang.toLowerCase().indexOf('zh') === 0 ? 'zh-CN' : 'en'
      } catch {
        i18nLang = 'en'
      }
    }
    let i18nLocaleData: Record<string, unknown> | null =
      this._cachedLocales[i18nLang] || null
    if (!i18nLocaleData) {
      try {
        const localeText = safeReadTextFile(
          vscode.Uri.joinPath(this._extensionUri, 'locales', i18nLang + '.json')
        )
        i18nLocaleData = localeText ? (JSON.parse(localeText) as Record<string, unknown>) : null
      } catch { /* 忽略 */ }
    }
    if (!i18nLocaleData) {
      i18nLocaleData = this._cachedLocales['en'] || null
      if (!i18nLocaleData) {
        try {
          const fallbackText = safeReadTextFile(
            vscode.Uri.joinPath(this._extensionUri, 'locales', 'en.json')
          )
          i18nLocaleData = fallbackText ? (JSON.parse(fallbackText) as Record<string, unknown>) : null
        } catch { /* 忽略 */ }
      }
      if (i18nLocaleData) i18nLang = 'en'
    }
    const allLocales: Record<string, Record<string, unknown>> = { ...this._cachedLocales }
    if (!allLocales['en'] || !allLocales['zh-CN']) {
      for (const loc of ['en', 'zh-CN']) {
        if (allLocales[loc]) continue
        try {
          const text = safeReadTextFile(
            vscode.Uri.joinPath(this._extensionUri, 'locales', loc + '.json')
          )
          if (text) allLocales[loc] = JSON.parse(text) as Record<string, unknown>
        } catch { /* 忽略 */ }
      }
    }
    const inlineAllLocalesLiteral = Object.keys(allLocales).length
      ? safeJsonForInlineScript(allLocales)
      : 'null'
    const inlineI18nLocaleLiteral = i18nLocaleData
      ? safeJsonForInlineScript(i18nLocaleData)
      : 'null'
    const inlineI18nLangLiteral = safeStringForInlineScript(i18nLang)
    const tl = (key: string): string => {
      if (!i18nLocaleData) return key
      const parts = String(key).split('.')
      let node: unknown = i18nLocaleData
      for (const p of parts) {
        if (!node || typeof node !== 'object') return key
        node = (node as Record<string, unknown>)[p]
      }
      return typeof node === 'string' ? node : key
    }
    const htmlLang = i18nLang === 'zh-CN' ? 'zh-CN' : 'en'

    return `<!DOCTYPE html>
<html lang="${htmlLang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; connect-src ${serverUrl} ${cspSource} 'self'; style-src ${cspSource}; script-src 'nonce-${nonce}'; img-src data: ${serverUrl} https: ${cspSource}; font-src ${serverUrl} data: ${cspSource}; object-src 'none'; frame-src 'none';">
    <meta id="aiia-config" data-server-url="${serverUrl}" data-csp-nonce="${nonce}" data-lottie-lib-url="${lottieJsUri}" data-no-content-lottie-json-url="${noContentLottieJsonUri}" data-no-content-fallback-svg-url="${activityIconUri}" data-mathjax-script-url="${mathjaxScriptUri}" data-marked-js-url="${markedJsUri}" data-prism-js-url="${prismJsUri}" data-notify-core-js-url="${webviewNotifyCoreUri}" data-settings-ui-js-url="${webviewSettingsUiUri}">
    <script nonce="${nonce}">window.__AIIA_NO_CONTENT_FALLBACK_SVG=${inlineNoContentFallbackSvgLiteral};window.__AIIA_NO_CONTENT_LOTTIE_DATA=${inlineNoContentLottieDataLiteral};window.__AIIA_I18N_LANG=${inlineI18nLangLiteral};window.__AIIA_I18N_LOCALE=${inlineI18nLocaleLiteral};window.__AIIA_I18N_ALL_LOCALES=${inlineAllLocalesLiteral};</script>
    <title>AI Intervention Agent</title>
    <link rel="stylesheet" href="${prismCssUri}">
    <link rel="stylesheet" href="${webviewCssUri}">
</head>
<body>
    <div class="container">
        <!-- Task tabs with status indicator -->
        <div class="tabs-container hidden" id="tasksTabsContainer">
            <div class="status-indicator">
                <div class="breathing-light" id="statusLight" title="${tl('ui.status.serverStatus')}" data-i18n-title="ui.status.serverStatus"></div>
            </div>
            <!-- Task tabs will be dynamically generated here -->
            <button class="settings-btn" id="settingsBtn" title="${tl('ui.settingsBtn')}" aria-label="${tl('ui.settingsBtn')}" data-i18n-title="ui.settingsBtn">
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
                <div data-i18n="ui.connecting">${tl('ui.connecting')}</div>
            </div>

            <!-- No content state -->
            <div class="no-content" id="noContentState">
                <button class="settings-btn no-content-settings-btn" id="settingsBtnNoContent" title="${tl('ui.settingsBtn')}" aria-label="${tl('ui.settingsBtn')}" data-i18n-title="ui.settingsBtn">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                        <circle cx="12" cy="12" r="3"></circle>
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                    </svg>
                </button>
                <div class="no-content-icon" id="hourglass-lottie" aria-hidden="true">\ud83c\udf31</div>
                <div class="title" data-i18n="ui.noContent.title">${tl('ui.noContent.title')}</div>
                <div class="status-indicator-standalone">
                    <div class="breathing-light" id="statusLightStandalone" title="${tl('ui.status.serverStatus')}" data-i18n-title="ui.status.serverStatus"></div>
                    <span id="statusTextStandalone" data-i18n="ui.noContent.connecting">${tl('ui.noContent.connecting')}</span>
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
                        <div class="form-label" data-i18n="ui.form.optionsLabel">${tl('ui.form.optionsLabel')}</div>
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
                            placeholder="${tl('ui.form.placeholder')}"
                            data-i18n-placeholder="ui.form.placeholder"
                        ></textarea>

                        <!-- Hidden file input -->
                        <input type="file" id="imageInput" accept="image/*" multiple class="hidden">

                        <!-- Button group (upload + submit) -->
                        <div class="input-buttons">
                            <button type="button" class="insert-code-btn" id="insertCodeBtn" title="${tl('ui.form.insertCode')}" aria-label="${tl('ui.form.insertCode')}" data-i18n-title="ui.form.insertCode">
                                <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                                    <polyline points="16 18 22 12 16 6"></polyline>
                                    <polyline points="8 6 2 12 8 18"></polyline>
                                    <line x1="14" y1="4" x2="10" y2="20"></line>
                                </svg>
                            </button>
                            <button type="button" class="upload-btn" id="uploadBtn" title="${tl('ui.form.uploadImage')}" aria-label="${tl('ui.form.uploadImage')}" data-i18n-title="ui.form.uploadImage">
                                <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
                                    <path fill-rule="evenodd" clip-rule="evenodd" d="M3 4.5C3 3.67157 3.67157 3 4.5 3H15.5C16.3284 3 17 3.67157 17 4.5V15.5C17 16.3284 16.3284 17 15.5 17H4.5C3.67157 17 3 16.3284 3 15.5V4.5ZM4.5 4C4.22386 4 4 4.22386 4 4.5V12.2929L6.64645 9.64645C6.84171 9.45118 7.15829 9.45118 7.35355 9.64645L10 12.2929L13.1464 9.14645C13.3417 8.95118 13.6583 8.95118 13.8536 9.14645L16 11.2929V4.5C16 4.22386 15.7761 4 15.5 4H4.5ZM16 12.7071L13.5 10.2071L10.3536 13.3536C10.1583 13.5488 9.84171 13.5488 9.64645 13.3536L7 10.7071L4 13.7071V15.5C4 15.7761 4.22386 16 4.5 16H15.5C15.7761 16 16 15.7761 16 15.5V12.7071ZM7 7.5C7 6.94772 7.44772 6.5 8 6.5C8.55228 6.5 9 6.94772 9 7.5C9 8.05228 8.55228 8.5 8 8.5C7.44772 8.5 7 8.05228 7 7.5Z" fill="currentColor" />
                                </svg>
                            </button>
                            <button type="button" class="submit-btn-embedded" id="submitBtn" title="${tl('ui.form.submit')}" aria-label="${tl('ui.form.submit')}" data-i18n-title="ui.form.submit">
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
                <div class="settings-title" data-i18n="settings.title">${tl('settings.title')}</div>
                <button class="settings-close" id="settingsClose" title="${tl('settings.close')}" aria-label="${tl('settings.close')}" data-i18n-title="settings.close">
                    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                        <path d="M5 5L15 15"></path>
                        <path d="M15 5L5 15"></path>
                    </svg>
                </button>
            </div>
            <div class="settings-body">
                <label class="settings-toggle">
                    <span data-i18n="settings.enabled">${tl('settings.enabled')}</span>
                    <input type="checkbox" id="notifyEnabled">
                </label>
                <label class="settings-toggle">
                    <span data-i18n="settings.macosNative">${tl('settings.macosNative')}</span>
                    <input type="checkbox" id="notifyMacOSNativeEnabled">
                </label>

                <div class="settings-divider"></div>

                <label class="settings-toggle">
                    <span data-i18n="settings.bark.enabled">${tl('settings.bark.enabled')}</span>
                    <input type="checkbox" id="notifyBarkEnabled">
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.url">${tl('settings.bark.url')}</span>
                    <input type="text" id="notifyBarkUrl" placeholder="${tl('settings.bark.urlPlaceholder')}" data-i18n-placeholder="settings.bark.urlPlaceholder">
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.deviceKey">${tl('settings.bark.deviceKey')}</span>
                    <input type="text" id="notifyBarkDeviceKey" placeholder="${tl('settings.bark.deviceKeyPlaceholder')}" data-i18n-placeholder="settings.bark.deviceKeyPlaceholder">
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.icon">${tl('settings.bark.icon')}</span>
                    <input type="text" id="notifyBarkIcon" placeholder="${tl('settings.bark.iconPlaceholder')}" data-i18n-placeholder="settings.bark.iconPlaceholder">
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.bark.action">${tl('settings.bark.action')}</span>
                    <select id="notifyBarkAction">
                        <option value="none" data-i18n="settings.bark.actionNone">${tl('settings.bark.actionNone')}</option>
                        <option value="url" data-i18n="settings.bark.actionUrl">${tl('settings.bark.actionUrl')}</option>
                        <option value="copy" data-i18n="settings.bark.actionCopy">${tl('settings.bark.actionCopy')}</option>
                    </select>
                </label>

                <div class="settings-divider"></div>

                <div class="settings-section-title" data-i18n="settings.feedback.title">${tl('settings.feedback.title')}</div>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.feedback.countdown">${tl('settings.feedback.countdown')}</span>
                    <input type="number" id="feedbackCountdown" min="0" max="250" step="10" value="240" style="max-width:100px">
                    <span class="settings-field-hint" data-i18n="settings.feedback.countdownHint">${tl('settings.feedback.countdownHint')}</span>
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.feedback.resubmitPrompt">${tl('settings.feedback.resubmitPrompt')}</span>
                    <textarea id="feedbackResubmitPrompt" rows="2" maxlength="500" placeholder="${tl('settings.feedback.resubmitPromptPlaceholder')}" data-i18n-placeholder="settings.feedback.resubmitPromptPlaceholder"></textarea>
                </label>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.feedback.promptSuffix">${tl('settings.feedback.promptSuffix')}</span>
                    <textarea id="feedbackPromptSuffix" rows="2" maxlength="500" placeholder="${tl('settings.feedback.promptSuffixPlaceholder')}" data-i18n-placeholder="settings.feedback.promptSuffixPlaceholder"></textarea>
                </label>
                <div class="settings-divider"></div>

                <div class="settings-section-title" data-i18n="settings.config.title">${tl('settings.config.title')}</div>
                <label class="settings-field">
                    <span class="settings-label" data-i18n="settings.config.path">${tl('settings.config.path')}</span>
                    <input type="text" id="settingsConfigPath" readonly placeholder="${tl('settings.config.pathPlaceholder')}" data-i18n-placeholder="settings.config.pathPlaceholder">
                </label>

                <div class="settings-divider"></div>

                <div class="settings-actions">
                    <button class="settings-action secondary" id="settingsTestNativeBtn" data-i18n="settings.testNative">${tl('settings.testNative')}</button>
                    <button class="settings-action secondary" id="settingsTestBarkBtn" data-i18n="settings.testBark">${tl('settings.testBark')}</button>
                    <div class="settings-actions-right">
                        <span class="settings-auto-save" title="${tl('settings.autoSaveTooltip')}" data-i18n="settings.autoSave" data-i18n-title="settings.autoSaveTooltip">${tl('settings.autoSave')}</span>
                    </div>
                </div>
                <div class="settings-footer" id="settingsFooter">
                    <span class="settings-footer-version" data-i18n="settings.footer.version" data-i18n-version="${extensionVersion}">${tl('settings.footer.version').replace('{{version}}', extensionVersion)}</span>
                    <a class="settings-footer-link" href="${githubUrl}" target="_blank" rel="noopener noreferrer" data-i18n="settings.footer.github">${tl('settings.footer.github')}</a>
                </div>
                <div class="settings-hint" id="settingsHint"></div>
            </div>
        </div>
    </div>

    <!-- Prism.js for code highlighting (no inline scripts; CSP-safe) -->
    <script nonce="${nonce}" src="${prismBootstrapUri}"></script>
    <!-- prism.min.js / marked.min.js 由 webview-ui.js 按需懒加载（首屏更快） -->

        <script nonce="${nonce}" src="${i18nJsUri}"></script>
        <script nonce="${nonce}" src="${webviewHelpersUri}"></script>
        <script nonce="${nonce}" src="${webviewUiUri}"></script>
        <script nonce="${nonce}" src="${webviewNotifyCoreUri}"></script>
</body>
</html>`
  }
}

module.exports = { WebviewProvider }
