import * as vscode from 'vscode'
import { WebviewProvider } from './webview'
import { createLogger } from './logger'

/**
 * AI Intervention Agent VSCode 扩展
 * iframe 模式 - 极简版本，仅显示服务器 Web UI
 */
const DEFAULT_SERVER_URL = 'http://localhost:8080'
let EXT_VERSION = '0.0.0'
try {
  EXT_VERSION = require('./package.json').version || EXT_VERSION
} catch {
  // 忽略：打包/测试环境下可能读取不到版本号
}

const BUILD_ID: string = (() => {
  const stamp = '__BUILD_SHA__'
  if (!stamp.startsWith('__')) return stamp
  try {
    return require('child_process')
      .execSync('git rev-parse --short HEAD', {
        encoding: 'utf8', timeout: 2000, cwd: __dirname,
        stdio: ['ignore', 'pipe', 'ignore']
      }).trim()
  } catch { return 'dev' }
})()

let deactivateHook: (() => void) | null = null

function normalizeServerUrl(input: unknown): string {
  try {
    const raw = (input ?? '').toString().trim()
    if (!raw) return DEFAULT_SERVER_URL

    const withScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw) ? raw : `http://${raw}`
    const u = new URL(withScheme)
    const protocol = String(u.protocol || '').toLowerCase()
    if (protocol !== 'http:' && protocol !== 'https:') return DEFAULT_SERVER_URL
    const host = String(u.hostname || '').toLowerCase()
    if (host === '0.0.0.0' || host === '::') {
      const port = u.port ? `:${u.port}` : ''
      return `${protocol}//localhost${port}`
    }
    return u.origin
  } catch {
    return DEFAULT_SERVER_URL
  }
}

function getConfiguredServerUrl(): string {
  const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
  return normalizeServerUrl(cfg.get<string>('serverUrl', DEFAULT_SERVER_URL))
}

interface StatusBarState {
  connected?: boolean | null
  active?: number
  pending?: number
}

interface TaskData {
  id: string
  prompt: string
}

function activate(context: vscode.ExtensionContext): void {
  let outputChannel: vscode.OutputChannel
  try {
    outputChannel = vscode.window.createOutputChannel('AI Intervention Agent', { log: true })
  } catch {
    outputChannel = vscode.window.createOutputChannel('AI Intervention Agent')
  }

  const logger = createLogger(outputChannel, {
    component: 'ext',
    getLevel: () => {
      try {
        const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
        return cfg.get<string>('logLevel', 'info') ?? 'info'
      } catch {
        return 'info'
      }
    }
  })
  let serverUrl = getConfiguredServerUrl()

  try {
    const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
    const logLevel = cfg.get<string>('logLevel', 'info')
    logger.event(
      'ext.activate',
      {
        version: EXT_VERSION,
        buildId: BUILD_ID,
        serverUrl,
        logLevel
      },
      { level: 'info' }
    )
  } catch {
    logger.event(
      'ext.activate',
      {
        version: EXT_VERSION,
        buildId: BUILD_ID,
        serverUrl
      },
      { level: 'info' }
    )
  }

  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100)
  statusBar.command = 'ai-intervention-agent.openPanel'
  statusBar.tooltip = `AI Intervention Agent\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
  statusBar.text = '$(sparkle-filled) --'
  statusBar.hide()
  let statusBarShown = false

  const setStatusBarShown = (shouldShow: boolean): void => {
    const next = !!shouldShow
    if (next === statusBarShown) return
    statusBarShown = next
    if (next) {
      statusBar.show()
    } else {
      statusBar.hide()
    }
  }

  let lastConnected: boolean | null = null
  let lastActive: number | null = null
  let lastPending: number | null = null
  let lastPollAtMs = 0
  let lastPollDurationMs: number | null = null
  let lastPollHttpStatus: number | null = null
  let lastPollErrorName = ''
  let lastPollError = ''

  let extKnownTaskIds = new Set<string>()
  let extTaskTrackingInitialized = false

  const formatTotalCount = (n: unknown): string => {
    const num = typeof n === 'number' && Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0
    return num > 99 ? '99+' : String(num)
  }

  const buildStatusBarTooltip = ({ connected, active, pending }: StatusBarState = {}): string => {
    try {
      const statusText = connected === true ? '已连接' : connected === false ? '未连接' : '未知'
      const a = typeof active === 'number' && Number.isFinite(active) ? active : 0
      const p = typeof pending === 'number' && Number.isFinite(pending) ? pending : 0
      const total = a + p

      const lines: string[] = []
      lines.push(`AI Intervention Agent（${statusText}）`)
      if (connected === true) {
        lines.push(`任务：Active ${a}  Pending ${p}  Total ${total}`)
      } else {
        lines.push('任务：--')
      }

      if (connected === false || connected === null) {
        lines.push(`serverUrl: ${serverUrl}`)
      }
      if ((connected === false || connected === null) && lastPollError) {
        const name = lastPollErrorName ? `${lastPollErrorName}: ` : ''
        lines.push(`原因：${name}${lastPollError}`)
      }

      return lines.join('\n')
    } catch {
      return `AI Intervention Agent\nserverUrl: ${serverUrl}`
    }
  }

  const applyStatusBarPresentation = ({ connected, active, pending }: StatusBarState = {}): void => {
    try {
      const a = typeof active === 'number' && Number.isFinite(active) ? active : 0
      const p = typeof pending === 'number' && Number.isFinite(pending) ? pending : 0
      const total = a + p

      if (connected === true) {
        statusBar.text = `$(sparkle-filled) ${formatTotalCount(total)}`
      } else if (connected === false) {
        statusBar.text = '$(sparkle-filled) 离线'
      } else {
        statusBar.text = '$(sparkle-filled) --'
      }

      statusBar.tooltip = buildStatusBarTooltip({ connected, active: a, pending: p })
      try {
        statusBar.accessibilityInformation = {
          label:
            connected === true
              ? `AI Intervention Agent 已连接，任务总数 ${total}`
              : connected === false
                ? 'AI Intervention Agent 未连接'
                : 'AI Intervention Agent 状态未知',
          role: 'status'
        }
      } catch {
        // 忽略：不同宿主/版本下 accessibilityInformation 可能不可用
      }
    } catch {
      // 忽略
    }
  }

  const updateStatusBarVisibility = (): void => {
    setStatusBarShown(true)
  }

  updateStatusBarVisibility()

  const updateStatusBar = async (): Promise<boolean | null> => {
    if (typeof fetch !== 'function') {
      lastPollAtMs = Date.now()
      lastPollDurationMs = null
      lastPollHttpStatus = null
      lastPollErrorName = 'NoFetch'
      lastPollError = '当前运行环境无 fetch，无法探测服务端状态'
      applyStatusBarPresentation({ connected: null, active: 0, pending: 0 })
      setStatusBarShown(true)
      return null
    }

    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    const timeoutId = controller
      ? setTimeout(() => {
          try {
            controller.abort()
          } catch {
            // 忽略：极少数环境 AbortController 可能不可用/不可中止
          }
        }, 1500)
      : null

    const requestId = `status_${Date.now().toString(16)}_${Math.random().toString(16).slice(2, 8)}`
    const startedAt = Date.now()
    const prevConnected = lastConnected
    const prevActive = lastActive
    const prevPending = lastPending

    try {
      const resp = await fetch(`${serverUrl}/api/tasks`, {
        signal: controller ? controller.signal : undefined,
        headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' }
      } as RequestInit)

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }

      const data = await resp.json() as Record<string, unknown>
      const stats = data && data.stats && typeof data.stats === 'object' ? data.stats as Record<string, unknown> : {}
      const active =
        stats && typeof stats.active === 'number' ? stats.active : 0
      const pending =
        stats && typeof stats.pending === 'number' ? stats.pending : 0
      const connected = !!(data && data.success)
      const durationMs = Date.now() - startedAt
      const changed =
        connected !== prevConnected || active !== prevActive || pending !== prevPending
      lastPollAtMs = Date.now()
      lastPollDurationMs = durationMs
      lastPollHttpStatus = resp.status
      lastPollErrorName = ''
      lastPollError = ''

      if (changed) {
        lastConnected = connected
        lastActive = active
        lastPending = pending

        applyStatusBarPresentation({ connected, active, pending })

        const level =
          connected === false && prevConnected === true
            ? 'warn'
            : connected === true && prevConnected === false
              ? 'info'
              : 'debug'
        logger.event(
          'server.poll',
          {
            requestId,
            ok: true,
            httpStatus: resp.status,
            connected,
            active,
            pending,
            durationMs
          },
          { level }
        )
      }
      if (statusBarShown) {
        applyStatusBarPresentation({ connected, active, pending })
      }
      updateStatusBarVisibility()

      if (connected && data && Array.isArray(data.tasks)) {
        try {
          const currentIds = new Set<string>()
          const newTaskData: TaskData[] = []
          for (const t of data.tasks as Array<Record<string, unknown>>) {
            if (!t || !t.task_id) continue
            const taskId = String(t.task_id)
            currentIds.add(taskId)
            if (extTaskTrackingInitialized && !extKnownTaskIds.has(taskId)) {
              newTaskData.push({ id: taskId, prompt: String(t.prompt || '') })
            }
          }
          if (newTaskData.length > 0 && extTaskTrackingInitialized) {
            if (provider && typeof (provider as unknown as Record<string, unknown>).dispatchNewTaskNotification === 'function') {
              logger.event(
                'ext.dispatch_new_task',
                { ids: newTaskData.map(t => t.id), viewVisible: isViewVisible },
                { level: 'info' }
              )
              ;(provider as unknown as { dispatchNewTaskNotification: (tasks: TaskData[]) => void }).dispatchNewTaskNotification(newTaskData)
            }
          }
          extKnownTaskIds = currentIds
          if (!extTaskTrackingInitialized && connected) {
            extTaskTrackingInitialized = true
            logger.event(
              'ext.tracking_initialized',
              { knownCount: currentIds.size },
              { level: 'info' }
            )
          }
        } catch {
          // 新任务检测失败不应影响状态栏轮询
        }
      }

      return connected
    } catch (e: unknown) {
      const durationMs = Date.now() - startedAt
      const errName = e instanceof Error ? e.name : ''
      const errMsg = e instanceof Error ? e.message : String(e)
      lastPollAtMs = Date.now()
      lastPollDurationMs = durationMs
      lastPollHttpStatus = null
      lastPollErrorName = errName
      lastPollError = errMsg

      if (lastConnected !== false) {
        lastConnected = false
        lastActive = null
        lastPending = null
      }
      applyStatusBarPresentation({ connected: false, active: 0, pending: 0 })

      const level = prevConnected === true ? 'warn' : prevConnected === false ? 'debug' : 'debug'
      logger.event(
        'server.poll',
        {
          requestId,
          ok: false,
          connected: false,
          durationMs,
          errorName: errName,
          error: errMsg
        },
        { level }
      )

      updateStatusBarVisibility()
      return false
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
    }
  }

  const STATUS_POLL_FAST_MS = 3000
  const STATUS_POLL_SLOW_MS = 15000
  const STATUS_POLL_MAX_MS = 60000
  const WEBVIEW_STATS_FRESH_MS = 5000
  let statusPollTimer: ReturnType<typeof setTimeout> | null = null
  let statusPollBackoffMs = STATUS_POLL_FAST_MS
  let statusPollInFlight = false
  let statusPollDisposed = false
  let isViewVisible = true
  let isWindowFocused = vscode.window.state.focused
  let lastWebviewStatsAtMs = 0

  const isWebviewStatsFresh = (): boolean =>
    isViewVisible &&
    lastWebviewStatsAtMs > 0 &&
    Date.now() - lastWebviewStatsAtMs < WEBVIEW_STATS_FRESH_MS

  const computeBaseDelayMs = (): number => {
    if (isWebviewStatsFresh()) return STATUS_POLL_SLOW_MS
    if (isViewVisible && isWindowFocused) return STATUS_POLL_FAST_MS
    if (isWindowFocused) return STATUS_POLL_FAST_MS * 2
    return STATUS_POLL_SLOW_MS
  }
  const computeNextDelayMs = (): number => {
    const base = computeBaseDelayMs()
    if (lastConnected === false) {
      return Math.min(STATUS_POLL_MAX_MS, Math.max(base, statusPollBackoffMs))
    }
    return base
  }

  const scheduleStatusPoll = (delayMs: number): void => {
    if (statusPollDisposed) return
    if (statusPollTimer) {
      clearTimeout(statusPollTimer)
      statusPollTimer = null
    }
    statusPollTimer = setTimeout(runStatusPoll, Math.max(0, delayMs))
  }

  const runStatusPoll = async (): Promise<void> => {
    if (statusPollDisposed) return
    if (statusPollInFlight) {
      scheduleStatusPoll(computeNextDelayMs())
      return
    }
    statusPollInFlight = true
    try {
      const connected = await updateStatusBar()
      if (connected === true) {
        statusPollBackoffMs = STATUS_POLL_FAST_MS
      } else if (connected === false) {
        statusPollBackoffMs = Math.min(STATUS_POLL_MAX_MS, Math.round(statusPollBackoffMs * 1.7))
      }
    } finally {
      statusPollInFlight = false
      if (!statusPollDisposed) {
        scheduleStatusPoll(computeNextDelayMs())
      }
    }
  }

  const provider = new WebviewProvider(
    context.extensionUri,
    outputChannel,
    serverUrl,
    (visible: boolean) => {
      isViewVisible = !!visible
      updateStatusBarVisibility()
      scheduleStatusPoll(0)
    },
    ({ connected, active, pending }: StatusBarState = {}) => {
      lastWebviewStatsAtMs = Date.now()
      const c = connected === true
      const a =
        typeof active === 'number' && Number.isFinite(active) ? Math.max(0, Math.floor(active)) : 0
      const p =
        typeof pending === 'number' && Number.isFinite(pending)
          ? Math.max(0, Math.floor(pending))
          : 0

      const changed = c !== lastConnected || a !== lastActive || p !== lastPending
      if (changed) {
        lastConnected = c
        lastActive = a
        lastPending = p
        applyStatusBarPresentation({ connected: c, active: a, pending: p })
      } else if (statusBarShown) {
        applyStatusBarPresentation({ connected: c, active: a, pending: p })
      }

      if (c) {
        statusPollBackoffMs = STATUS_POLL_FAST_MS
      } else {
        statusPollBackoffMs = Math.min(STATUS_POLL_MAX_MS, Math.round(statusPollBackoffMs * 1.7))
      }
    },
    (taskIds: string[]) => {
      if (!Array.isArray(taskIds)) return
      for (const id of taskIds) {
        if (id) extKnownTaskIds.add(String(id))
      }
    }
  )
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('aiInterventionAgent.feedbackView', provider, {
      webviewOptions: {
        retainContextWhenHidden: false
      }
    })
  )

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (!e.affectsConfiguration('ai-intervention-agent.serverUrl')) return

      const next = getConfiguredServerUrl()
      if (!next || next === serverUrl) return

      const prev = serverUrl
      serverUrl = next
      logger.event('config.update', { key: 'serverUrl', prev, next: serverUrl }, { level: 'info' })

      lastConnected = null
      lastActive = null
      lastPending = null
      statusPollBackoffMs = STATUS_POLL_FAST_MS
      extKnownTaskIds = new Set<string>()
      extTaskTrackingInitialized = false
      statusBar.tooltip = `AI Intervention Agent\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
      scheduleStatusPoll(0)

      if (provider && typeof (provider as unknown as { updateServerUrl?: (url: string) => void }).updateServerUrl === 'function') {
        (provider as unknown as { updateServerUrl: (url: string) => void }).updateServerUrl(serverUrl)
      }
    })
  )

  context.subscriptions.push(
    vscode.window.onDidChangeWindowState(state => {
      isWindowFocused = !!state.focused
      scheduleStatusPoll(isWindowFocused && isViewVisible ? 0 : computeNextDelayMs())
      try {
        if (provider && typeof (provider as unknown as { onWindowFocusChanged?: (focused: boolean) => void }).onWindowFocusChanged === 'function') {
          (provider as unknown as { onWindowFocusChanged: (focused: boolean) => void }).onWindowFocusChanged(isWindowFocused)
        }
      } catch {
        // 忽略：不同宿主/版本下 focus 事件不应影响主流程
      }
    })
  )

  scheduleStatusPoll(0)

  const openPanelDisposable = vscode.commands.registerCommand(
    'ai-intervention-agent.openPanel',
    async function () {
      await vscode.commands.executeCommand('workbench.view.extension.aiInterventionAgent')
      try {
        await vscode.commands.executeCommand('aiInterventionAgent.feedbackView.focus')
      } catch {
        // 忽略：不同宿主/版本下该 view id 可能不可用
      }
    }
  )

  const openSettingsDisposable = vscode.commands.registerCommand(
    'ai-intervention-agent.openSettings',
    async function () {
      try {
        await vscode.commands.executeCommand(
          'workbench.action.openSettings',
          'ai-intervention-agent.serverUrl'
        )
      } catch {
        await vscode.commands.executeCommand('workbench.action.openSettingsJson')
      }
    }
  )

  context.subscriptions.push(openPanelDisposable)
  context.subscriptions.push(openSettingsDisposable)
  context.subscriptions.push(outputChannel)
  context.subscriptions.push(statusBar)

  const cleanup = (): void => {
    try {
      statusPollDisposed = true
      if (statusPollTimer) {
        clearTimeout(statusPollTimer)
        statusPollTimer = null
      }
      try {
        if (provider && typeof (provider as unknown as { dispose?: () => void }).dispose === 'function') {
          (provider as unknown as { dispose: () => void }).dispose()
        }
      } catch {
        // 忽略
      }
    } catch {
      // 忽略
    }
  }
  deactivateHook = cleanup
  context.subscriptions.push({ dispose: cleanup })
}

function deactivate(): void {
  try {
    if (deactivateHook && typeof deactivateHook === 'function') {
      deactivateHook()
    }
  } catch {
    // 忽略
  } finally {
    deactivateHook = null
  }
}

module.exports = {
  activate,
  deactivate
}
