const vscode = require('vscode')
const { WebviewProvider } = require('./webview')
const { createLogger } = require('./logger')
const { AppleScriptExecutor } = require('./applescript-executor')
const { AppleScriptNotificationProvider } = require('./notification-providers')

/**
 * AI Intervention Agent VSCode 扩展
 * iframe 模式 - 极简版本，仅显示服务器 Web UI
 */
const DEFAULT_SERVER_URL = 'http://localhost:8080'
let EXT_VERSION = '0.3.4'
try {
  EXT_VERSION = require('./package.json').version || EXT_VERSION
} catch {
  // 忽略：打包/测试环境下可能读取不到版本号
}
// 用于排查“VSIX 是否确实更新”的构建标识（版本号不变时尤为重要）
const BUILD_ID = '2026-01-07-webview-ui-external-logs'

// deactivate() 清理钩子（activate 内赋值）
let deactivateHook = null

function normalizeServerUrl(input) {
  try {
    const raw = (input ?? '').toString().trim()
    if (!raw) return DEFAULT_SERVER_URL

    // 允许用户省略协议（例如 localhost:8080）
    const withScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw) ? raw : `http://${raw}`
    const u = new URL(withScheme)
    const protocol = String(u.protocol || '').toLowerCase()
    // 仅允许 http/https，避免 data/javascript/file 等协议带来的安全边界混淆
    if (protocol !== 'http:' && protocol !== 'https:') return DEFAULT_SERVER_URL
    return u.origin
  } catch {
    return DEFAULT_SERVER_URL
  }
}

function getConfiguredServerUrl() {
  const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
  return normalizeServerUrl(cfg.get('serverUrl', DEFAULT_SERVER_URL))
}

function activate(context) {
  // 创建输出频道（不自动显示）
  // 优先使用 LogOutputChannel（若 VSCode 版本不支持则回退为普通 OutputChannel）
  let outputChannel
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
        return cfg.get('logLevel', 'info')
      } catch {
        return 'info'
      }
    }
  })
  let serverUrl = getConfiguredServerUrl()

  const appleScriptLogger = logger.child('applescript')
  const appleScriptExecutor = new AppleScriptExecutor({ logger: appleScriptLogger })
  const appleScriptNotificationProvider = new AppleScriptNotificationProvider({
    logger: appleScriptLogger,
    executor: appleScriptExecutor
  })

  const isAppleScriptEnabled = () => {
    try {
      const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
      return !!cfg.get('enableAppleScript', false)
    } catch {
      return false
    }
  }

  const runAppleScriptGuarded = async script => {
    if (!isAppleScriptEnabled()) {
      const msg = 'AppleScript 执行未启用：请在设置中打开 ai-intervention-agent.enableAppleScript'
      const err = new Error(msg)
      err.code = 'APPLE_SCRIPT_DISABLED'
      try {
        appleScriptLogger.warn(msg)
      } catch {
        // 忽略：日志系统异常不应影响主流程
      }
      vscode.window.showErrorMessage(msg)
      throw err
    }

    try {
      const out = await appleScriptExecutor.runAppleScript(script)
      return out
    } catch (e) {
      const code = e && e.code ? String(e.code) : ''
      const raw = e && e.message ? String(e.message) : String(e)
      const msg =
        code === 'PLATFORM_NOT_SUPPORTED'
          ? 'Platform not supported'
          : code === 'APPLE_SCRIPT_TIMEOUT'
            ? 'AppleScript 执行超时'
            : raw
              ? `AppleScript 执行失败：${raw}`
              : 'AppleScript 执行失败'
      try {
        appleScriptLogger.warn(`执行失败 code=${code || 'unknown'} msg=${raw || ''}`.trim())
      } catch {
        // 忽略：日志系统异常不应影响主流程
      }
      vscode.window.showErrorMessage(msg)
      throw e
    }
  }

  // 启动日志（结构化：便于 grep/定位）
  try {
    const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
    const logLevel = cfg.get('logLevel', 'info')
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

  // 状态栏：显示连接状态 & 任务数（点击打开面板）
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100)
  statusBar.command = 'ai-intervention-agent.openPanel'
  statusBar.tooltip = `AI Intervention Agent\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
  statusBar.text = '$(sparkle-filled) --'
  // 默认隐藏：后续根据“视图可见/有待处理任务”动态 show/hide，避免常驻占用状态栏
  statusBar.hide()
  let statusBarShown = false

  const setStatusBarShown = shouldShow => {
    const next = !!shouldShow
    if (next === statusBarShown) return
    statusBarShown = next
    if (next) {
      statusBar.show()
    } else {
      statusBar.hide()
    }
  }

  let lastConnected = null
  let lastActive = null
  let lastPending = null
  let lastPollAtMs = 0
  let lastPollDurationMs = null
  let lastPollHttpStatus = null
  let lastPollErrorName = ''
  let lastPollError = ''

  const formatTotalCount = n => {
    const num = typeof n === 'number' && Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0
    return num > 99 ? '99+' : String(num)
  }

  const buildStatusBarTooltip = ({ connected, active, pending } = {}) => {
    try {
      const statusText =
        connected === true ? '已连接' : connected === false ? '未连接' : '未知'
      const a = typeof active === 'number' && Number.isFinite(active) ? active : 0
      const p = typeof pending === 'number' && Number.isFinite(pending) ? pending : 0
      const total = a + p

      const lines = []
      lines.push(`AI Intervention Agent（${statusText}）`)
      if (connected === true) {
        lines.push(`任务：Active ${a}  Pending ${p}  Total ${total}`)
      } else {
        lines.push('任务：--')
      }

      // 仅在离线/不可用时补充原因，避免 tooltip 过长
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

  const applyStatusBarPresentation = ({ connected, active, pending } = {}) => {
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

  const updateStatusBarVisibility = () => {
    // 用户诉求：状态栏常驻显示（即使 0 也显示）
    setStatusBarShown(true)
  }

  // 常驻显示：初始化后立刻展示（避免“插件已启动但状态栏无任何反馈”）
  updateStatusBarVisibility()

  const updateStatusBar = async () => {
    // Node 18+ 有全局 fetch；若不存在则降级为“未知”
    if (typeof fetch !== 'function') {
      lastPollAtMs = Date.now()
      lastPollDurationMs = null
      lastPollHttpStatus = null
      lastPollErrorName = 'NoFetch'
      lastPollError = '当前运行环境无 fetch，无法探测服务端状态'
      applyStatusBarPresentation({ connected: null, active: 0, pending: 0 })
      // 该问题会导致功能不可用：显示状态栏提示用户
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
        cache: 'no-store',
        signal: controller ? controller.signal : undefined,
        headers: { Accept: 'application/json' }
      })

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }

      const data = await resp.json()
      const active =
        data && data.stats && typeof data.stats.active === 'number' ? data.stats.active : 0
      const pending =
        data && data.stats && typeof data.stats.pending === 'number' ? data.stats.pending : 0
      const connected = !!(data && data.success)
      const durationMs = Date.now() - startedAt
      const changed = connected !== prevConnected || active !== prevActive || pending !== prevPending
      lastPollAtMs = Date.now()
      lastPollDurationMs = durationMs
      lastPollHttpStatus = resp.status
      lastPollErrorName = ''
      lastPollError = ''

      // 只在变化时更新，避免频繁重绘
      if (changed) {
        lastConnected = connected
        lastActive = active
        lastPending = pending

        applyStatusBarPresentation({ connected, active, pending })

        // 结构化日志：只在状态变化时记录，避免刷屏
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
      // tooltip 的“最后探测时间/耗时”属于诊断信息：当状态栏可见时，即使数值未变也刷新一次
      if (statusBarShown) {
        applyStatusBarPresentation({ connected, active, pending })
      }
      updateStatusBarVisibility(connected, active, pending)
      return connected
    } catch (e) {
      const durationMs = Date.now() - startedAt
      const errName = e && e.name ? String(e.name) : ''
      const errMsg = e && e.message ? String(e.message) : String(e)
      lastPollAtMs = Date.now()
      lastPollDurationMs = durationMs
      lastPollHttpStatus = null
      lastPollErrorName = errName
      lastPollError = errMsg

      // 离线/超时/连接失败
      if (lastConnected !== false) {
        lastConnected = false
        lastActive = null
        lastPending = null
      }
      applyStatusBarPresentation({ connected: false, active: 0, pending: 0 })

      // 仅在首次从“非离线”切到离线时打 warn，其余 debug
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

      updateStatusBarVisibility(false, 0, 0)
      return false
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
    }
  }

  // 状态栏轮询自适应（可见=快，不可见/离线=慢 + 退避）
  const STATUS_POLL_FAST_MS = 3000
  const STATUS_POLL_SLOW_MS = 15000
  const STATUS_POLL_MAX_MS = 60000
  const WEBVIEW_STATS_FRESH_MS = 5000
  let statusPollTimer = null
  let statusPollBackoffMs = STATUS_POLL_FAST_MS
  let statusPollInFlight = false
  // 兜底：用于解决 deactivate 与 in-flight 轮询回调的竞态（防止停用后“复活”定时器）
  let statusPollDisposed = false
  let isViewVisible = true
  let isWindowFocused = vscode.window.state.focused
  let lastWebviewStatsAtMs = 0

  const isWebviewStatsFresh = () =>
    isViewVisible && lastWebviewStatsAtMs > 0 && Date.now() - lastWebviewStatsAtMs < WEBVIEW_STATS_FRESH_MS

  const computeBaseDelayMs = () => {
    // Webview 可见且持续上报 stats：状态栏可复用 Webview 轮询结果，扩展侧降频探测
    if (isWebviewStatsFresh()) return STATUS_POLL_SLOW_MS
    return isViewVisible && isWindowFocused ? STATUS_POLL_FAST_MS : STATUS_POLL_SLOW_MS
  }
  const computeNextDelayMs = () => {
    const base = computeBaseDelayMs()
    if (lastConnected === false) {
      return Math.min(STATUS_POLL_MAX_MS, Math.max(base, statusPollBackoffMs))
    }
    return base
  }

  const scheduleStatusPoll = delayMs => {
    if (statusPollDisposed) return
    if (statusPollTimer) {
      clearTimeout(statusPollTimer)
      statusPollTimer = null
    }
    statusPollTimer = setTimeout(runStatusPoll, Math.max(0, delayMs))
  }

  const runStatusPoll = async () => {
    if (statusPollDisposed) return
    // Webview 可见且 stats 新鲜：不再重复 /api/tasks 请求
    if (isWebviewStatsFresh()) {
      scheduleStatusPoll(computeNextDelayMs())
      return
    }
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

  // 注册webview provider（支持多标签页和缓存）
  const provider = new WebviewProvider(
    context.extensionUri,
    outputChannel,
    serverUrl,
    visible => {
      isViewVisible = !!visible
      updateStatusBarVisibility(lastConnected, lastActive, lastPending)
      scheduleStatusPoll(isViewVisible ? 0 : computeNextDelayMs())
    },
    ({ connected, active, pending } = {}) => {
      // Webview 轮询的 /api/tasks 已包含 stats：这里直接复用来更新状态栏
      lastWebviewStatsAtMs = Date.now()
      const c = connected === true
      const a = typeof active === 'number' && Number.isFinite(active) ? Math.max(0, Math.floor(active)) : 0
      const p = typeof pending === 'number' && Number.isFinite(pending) ? Math.max(0, Math.floor(pending)) : 0

      const changed = c !== lastConnected || a !== lastActive || p !== lastPending
      if (changed) {
        lastConnected = c
        lastActive = a
        lastPending = p
        applyStatusBarPresentation({ connected: c, active: a, pending: p })
      } else if (statusBarShown) {
        applyStatusBarPresentation({ connected: c, active: a, pending: p })
      }

      // 与扩展侧退避保持一致：Webview 上报离线时也适当退避
      if (c) {
        statusPollBackoffMs = STATUS_POLL_FAST_MS
      } else {
        statusPollBackoffMs = Math.min(STATUS_POLL_MAX_MS, Math.round(statusPollBackoffMs * 1.7))
      }
    }
  )
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('aiInterventionAgent.feedbackView', provider, {
      webviewOptions: {
        // 内存优先：隐藏时允许释放 Webview；关键 UI 状态由 Webview 侧 setState/getState 持久化
        retainContextWhenHidden: false
      }
    })
  )

  // 监听配置变更：serverUrl 更新后同步刷新状态栏与 Webview（需要重建 HTML 以更新 CSP 与 SERVER_URL 常量）
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (!e.affectsConfiguration('ai-intervention-agent.serverUrl')) return

      const next = getConfiguredServerUrl()
      if (!next || next === serverUrl) return

      const prev = serverUrl
      serverUrl = next
      logger.event(
        'config.update',
        { key: 'serverUrl', prev, next: serverUrl },
        { level: 'info' }
      )

      // 强制刷新状态栏
      lastConnected = null
      lastActive = null
      lastPending = null
      statusPollBackoffMs = STATUS_POLL_FAST_MS
      statusBar.tooltip = `AI Intervention Agent\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
      scheduleStatusPoll(0)

      // 刷新 Webview（更新 CSP / SERVER_URL）
      if (provider && typeof provider.updateServerUrl === 'function') {
        provider.updateServerUrl(serverUrl)
      }
    })
  )

  // VSCode 窗口焦点变化：不聚焦时降低轮询频率
  context.subscriptions.push(
    vscode.window.onDidChangeWindowState(state => {
      isWindowFocused = !!state.focused
      scheduleStatusPoll(isWindowFocused && isViewVisible ? 0 : computeNextDelayMs())
      try {
        if (provider && typeof provider.onWindowFocusChanged === 'function') {
          provider.onWindowFocusChanged(isWindowFocused)
        }
      } catch {
        // 忽略：不同宿主/版本下 focus 事件不应影响主流程
      }
    })
  )

  // 启动轮询
  scheduleStatusPoll(0)

  // 注册Hello World命令（保留用于测试）
  let disposable = vscode.commands.registerCommand('ai-intervention-agent.helloWorld', function () {
    vscode.window.showInformationMessage('AI Intervention Agent is running!')
  })

  // 命令：打开面板（活动栏容器）
  const openPanelDisposable = vscode.commands.registerCommand(
    'ai-intervention-agent.openPanel',
    async function () {
      await vscode.commands.executeCommand('workbench.view.extension.aiInterventionAgent')
      // 尝试聚焦具体 view（失败则忽略）
      try {
        await vscode.commands.executeCommand('aiInterventionAgent.feedbackView.focus')
      } catch {
        // 忽略：不同宿主/版本下该 view id 可能不可用
      }
    }
  )

  // 命令：打开配置（定位到 serverUrl）
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

  // 命令：执行 AppleScript（仅用于受控调用；默认需要 enableAppleScript 开关）
  const runAppleScriptDisposable = vscode.commands.registerCommand(
    'ai-intervention-agent.runAppleScript',
    async function (script) {
      return await runAppleScriptGuarded(script)
    }
  )

  // 命令：测试 macOS 通知（AppleScript）
  const testAppleScriptNotificationDisposable = vscode.commands.registerCommand(
    'ai-intervention-agent.testAppleScriptNotification',
    async function () {
      // 原生通知应“安装即用”：这里不依赖 enableAppleScript（该开关仅用于执行任意 AppleScript 命令）
      const ok = await appleScriptNotificationProvider.send({
        title: 'AI Intervention Agent 测试',
        message: '这是一条 macOS 原生通知测试',
        metadata: { isTest: true }
      })
      if (!ok) {
        // provider 已在 isTest 模式下尽量提示错误；这里补一句兜底
        try {
          vscode.window.showErrorMessage('原生通知发送失败：请检查系统通知权限/勿扰模式')
        } catch {
          // 忽略
        }
      }
      return ok
    }
  )

  // 命令：复制诊断信息（用于排障/提交 issue）
  const copyDiagnosticsDisposable = vscode.commands.registerCommand(
    'ai-intervention-agent.copyDiagnostics',
    async function () {
      const now = new Date()
      let logLevel = 'info'
      let enableAppleScript = false
      try {
        const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
        logLevel = cfg.get('logLevel', 'info')
        enableAppleScript = !!cfg.get('enableAppleScript', false)
      } catch {
        // 忽略
      }

      const recent =
        logger && typeof logger.getRecentLines === 'function' ? logger.getRecentLines(250) : []

      const out = []
      out.push('# AI Intervention Agent Diagnostics')
      out.push('')
      out.push(`timestamp=${now.toISOString()}`)
      out.push('')
      out.push('## Environment')
      out.push(`appName=${vscode && vscode.env && vscode.env.appName ? String(vscode.env.appName) : ''}`)
      out.push(`vscodeVersion=${vscode && vscode.version ? String(vscode.version) : ''}`)
      out.push(`platform=${process.platform}`)
      out.push(`arch=${process.arch}`)
      out.push(`node=${process.versions && process.versions.node ? String(process.versions.node) : ''}`)
      out.push('')
      out.push('## Extension')
      out.push(`extVersion=${EXT_VERSION}`)
      out.push(`buildId=${BUILD_ID}`)
      out.push(`serverUrl=${serverUrl}`)
      out.push(`logLevel=${logLevel}`)
      out.push(`enableAppleScript=${enableAppleScript}`)
      out.push('')
      out.push('## Status')
      out.push(`connected=${lastConnected === null ? 'null' : String(lastConnected)}`)
      out.push(`active=${lastActive === null ? 'null' : String(lastActive)}`)
      out.push(`pending=${lastPending === null ? 'null' : String(lastPending)}`)
      out.push(
        `lastPollAt=${lastPollAtMs ? new Date(lastPollAtMs).toISOString() : ''}`
      )
      out.push(
        `lastPollDurationMs=${
          typeof lastPollDurationMs === 'number' ? String(lastPollDurationMs) : ''
        }`
      )
      out.push(
        `lastPollHttpStatus=${
          typeof lastPollHttpStatus === 'number' ? String(lastPollHttpStatus) : ''
        }`
      )
      out.push(`lastPollErrorName=${lastPollErrorName || ''}`)
      out.push(`lastPollError=${lastPollError || ''}`)
      out.push('')
      out.push('## Recent logs (last 250)')
      out.push('```')
      if (recent && recent.length > 0) {
        out.push(...recent)
      } else {
        out.push('<empty>')
      }
      out.push('```')

      const text = out.join('\n')

      try {
        await vscode.env.clipboard.writeText(text)
        try {
          vscode.window.showInformationMessage('已复制诊断信息到剪贴板')
        } catch {
          // 忽略
        }
        try {
          if (logger && typeof logger.event === 'function') {
            logger.event('diagnostics.copied', { lines: recent.length }, { level: 'info' })
          }
        } catch {
          // 忽略
        }
        return text
      } catch (e) {
        const msg = e && e.message ? String(e.message) : String(e)
        try {
          vscode.window.showErrorMessage(`复制诊断信息失败：${msg}`)
        } catch {
          // 忽略
        }
        try {
          if (logger && typeof logger.event === 'function') {
            logger.event('diagnostics.copy_failed', { error: msg }, { level: 'warn' })
          }
        } catch {
          // 忽略
        }
        return ''
      }
    }
  )

  context.subscriptions.push(disposable)
  context.subscriptions.push(openPanelDisposable)
  context.subscriptions.push(openSettingsDisposable)
  context.subscriptions.push(runAppleScriptDisposable)
  context.subscriptions.push(testAppleScriptNotificationDisposable)
  context.subscriptions.push(copyDiagnosticsDisposable)
  context.subscriptions.push(outputChannel)
  context.subscriptions.push(statusBar)

  // 兜底清理：避免极端情况下 timer 常驻
  const cleanup = () => {
    try {
      statusPollDisposed = true
      if (statusPollTimer) {
        clearTimeout(statusPollTimer)
        statusPollTimer = null
      }
      // 显式释放 provider（避免持有 Webview/Disposable 引用导致 GC 推迟）
      try {
        if (provider && typeof provider.dispose === 'function') {
          provider.dispose()
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

function deactivate() {
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
