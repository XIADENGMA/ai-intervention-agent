const vscode = require('vscode')
const { WebviewProvider } = require('./webview')

/**
 * AI Intervention Agent VSCode Extension
 * iframe模式 - 极简版本，仅显示服务器Web UI
 */
const DEFAULT_SERVER_URL = 'http://localhost:8081'
let EXT_VERSION = '0.3.4'
try {
  EXT_VERSION = require('./package.json').version || EXT_VERSION
} catch {
  // ignore
}

function normalizeServerUrl(input) {
  try {
    const raw = (input ?? '').toString().trim()
    if (!raw) return DEFAULT_SERVER_URL

    // 允许用户省略协议（例如 localhost:8081）
    const withScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw) ? raw : `http://${raw}`
    const u = new URL(withScheme)
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
  // 创建输出频道（不自动显示，避免点击侧边栏图标时错误打开 Output 面板）
  const outputChannel = vscode.window.createOutputChannel('AI Intervention Agent')
  let serverUrl = getConfiguredServerUrl()

  // 简洁的启动日志
  const timestamp = new Date().toLocaleTimeString('zh-CN')
  outputChannel.appendLine(`[${timestamp}] AI Intervention Agent v${EXT_VERSION} 已启动`)
  outputChannel.appendLine(`[${timestamp}] 服务器: ${serverUrl}`)

  // 状态栏：显示连接状态 & 任务数（点击打开面板）
  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100)
  statusBar.command = 'ai-intervention-agent.openPanel'
  statusBar.tooltip = `AI Intervention Agent\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
  statusBar.text = '$(sparkle-filled) --'
  statusBar.show()

  let lastConnected = null
  let lastActive = null
  let lastPending = null

  const updateStatusBar = async () => {
    // Node 18+ 有全局 fetch；若不存在则降级为“未知”
    if (typeof fetch !== 'function') {
      statusBar.text = '$(sparkle-filled) --'
      statusBar.tooltip = `AI Intervention Agent\n（当前运行环境无 fetch，无法探测服务端状态）\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
      return null
    }

    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
    const timeoutId = controller
      ? setTimeout(() => {
          try {
            controller.abort()
          } catch {
            // ignore
          }
        }, 1500)
      : null

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

      // 只在变化时更新，避免频繁重绘
      if (connected !== lastConnected || active !== lastActive || pending !== lastPending) {
        lastConnected = connected
        lastActive = active
        lastPending = pending

        if (connected) {
          statusBar.text = `$(sparkle-filled) ${active + pending}`
          statusBar.tooltip = `AI Intervention Agent（已连接）\nActive: ${active}  Pending: ${pending}\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
        } else {
          statusBar.text = '$(sparkle-filled) 离线'
          statusBar.tooltip = `AI Intervention Agent（未连接）\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
        }
      }
      return connected
    } catch {
      // 离线/超时/连接失败
      if (lastConnected !== false) {
        lastConnected = false
        lastActive = null
        lastPending = null
        statusBar.text = '$(sparkle-filled) 离线'
        statusBar.tooltip = `AI Intervention Agent（未连接）\nserverUrl: ${serverUrl}\n点击打开面板\n命令：AI Intervention Agent: 打开配置（serverUrl）`
      }
      return false
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
    }
  }

  // 状态栏轮询自适应（可见=快，不可见/离线=慢 + 退避）
  const STATUS_POLL_FAST_MS = 3000
  const STATUS_POLL_SLOW_MS = 15000
  const STATUS_POLL_MAX_MS = 60000
  let statusPollTimer = null
  let statusPollBackoffMs = STATUS_POLL_FAST_MS
  let statusPollInFlight = false
  let isViewVisible = true
  let isWindowFocused = vscode.window.state.focused

  const computeBaseDelayMs = () => (isViewVisible && isWindowFocused ? STATUS_POLL_FAST_MS : STATUS_POLL_SLOW_MS)
  const computeNextDelayMs = () => {
    const base = computeBaseDelayMs()
    if (lastConnected === false) {
      return Math.min(STATUS_POLL_MAX_MS, Math.max(base, statusPollBackoffMs))
    }
    return base
  }

  const scheduleStatusPoll = delayMs => {
    if (statusPollTimer) {
      clearTimeout(statusPollTimer)
      statusPollTimer = null
    }
    statusPollTimer = setTimeout(runStatusPoll, Math.max(0, delayMs))
  }

  const runStatusPoll = async () => {
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
      scheduleStatusPoll(computeNextDelayMs())
    }
  }

  // 注册webview provider（支持多标签页和缓存）
  const provider = new WebviewProvider(context.extensionUri, outputChannel, serverUrl, visible => {
    isViewVisible = !!visible
    scheduleStatusPoll(isViewVisible ? 0 : computeNextDelayMs())
  })
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('aiInterventionAgent.feedbackView', provider, {
      webviewOptions: {
        retainContextWhenHidden: true // 保持webview状态，避免重新加载
      }
    })
  )

  // 监听配置变更：serverUrl 更新后同步刷新状态栏与 Webview（需要重建 HTML 以更新 CSP 与 SERVER_URL 常量）
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (!e.affectsConfiguration('ai-intervention-agent.serverUrl')) return

      const next = getConfiguredServerUrl()
      if (!next || next === serverUrl) return

      serverUrl = next
      const ts = new Date().toLocaleTimeString('zh-CN')
      outputChannel.appendLine(`[${ts}] 配置已更新：serverUrl = ${serverUrl}`)

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
    })
  )

  // 启动轮询
  scheduleStatusPoll(0)

  // 注册Hello World命令（保留用于测试）
  let disposable = vscode.commands.registerCommand('ai-intervention-agent.helloWorld', function () {
    vscode.window.showInformationMessage('AI Intervention Agent is running!')
  })

  // 命令：打开面板（活动栏容器）
  const openPanelDisposable = vscode.commands.registerCommand('ai-intervention-agent.openPanel', async function () {
    await vscode.commands.executeCommand('workbench.view.extension.aiInterventionAgent')
    // 尝试聚焦具体 view（失败则忽略）
    try {
      await vscode.commands.executeCommand('aiInterventionAgent.feedbackView.focus')
    } catch {
      // ignore
    }
  })

  // 命令：打开配置（定位到 serverUrl）
  const openSettingsDisposable = vscode.commands.registerCommand('ai-intervention-agent.openSettings', async function () {
    try {
      await vscode.commands.executeCommand('workbench.action.openSettings', 'ai-intervention-agent.serverUrl')
    } catch {
      await vscode.commands.executeCommand('workbench.action.openSettingsJson')
    }
  })

  context.subscriptions.push(disposable)
  context.subscriptions.push(openPanelDisposable)
  context.subscriptions.push(openSettingsDisposable)
  context.subscriptions.push(outputChannel)
  context.subscriptions.push(statusBar)
  context.subscriptions.push({
    dispose: () => {
      if (statusPollTimer) clearTimeout(statusPollTimer)
    }
  })
}

function deactivate() {}

module.exports = {
  activate,
  deactivate
}
