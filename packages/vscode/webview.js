const vscode = require('vscode')
const fs = require('fs')
const path = require('path')
const { createLogger } = require('./logger')

// 扩展元信息（用于在 Webview 中显示版本号 / GitHub）
const EXT_GITHUB_URL = 'https://github.com/XIADENGMA/ai-intervention-agent'
let EXT_VERSION = '0.0.0'
try {
  EXT_VERSION = require('./package.json').version || EXT_VERSION
} catch {
  // ignore
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
  constructor(extensionUri, outputChannel, serverUrl = 'http://localhost:8081', onVisibilityChanged) {
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
    this._serverUrl = serverUrl
    this._onVisibilityChanged = typeof onVisibilityChanged === 'function' ? onVisibilityChanged : null
    this._view = null
    this._disposables = []
    this._lastServerStatus = null
    // 仅用于日志降噪：首次“未连接”通常是初始化瞬态，不必在 info 下刷屏
    this._hasEverConnected = false
    this._webviewReady = false
    this._webviewReadyTimer = null

    // 缓存 marked.js 内容（只读取一次）
    this._markedJsCache = this._loadMarkedJs()
    // 缓存 Prism 资源（只读取一次）
    this._prismJsCache = this._loadPrismJs()
    this._prismCssCache = this._loadPrismCss()
  }

  // 加载 marked.min.js 内容（仅在构造时调用一次）
  _loadMarkedJs() {
    try {
      const markedPath = path.join(this._extensionUri.fsPath, 'marked.min.js')
      const content = fs.readFileSync(markedPath, 'utf8')
      return content
    } catch (e) {
      this._log(`[警告] 无法读取 marked.min.js: ${e.message}`)
      return ''
    }
  }

  // 获取缓存的 marked.js 内容
  _getMarkedJs() {
    return this._markedJsCache || ''
  }

  _loadPrismJs() {
    try {
      const prismPath = path.join(this._extensionUri.fsPath, 'prism.min.js')
      return fs.readFileSync(prismPath, 'utf8')
    } catch (e) {
      this._log(`[警告] 无法读取 prism.min.js: ${e.message}`)
      return ''
    }
  }

  _loadPrismCss() {
    try {
      const prismCssPath = path.join(this._extensionUri.fsPath, 'prism.min.css')
      return fs.readFileSync(prismCssPath, 'utf8')
    } catch (e) {
      this._log(`[警告] 无法读取 prism.min.css: ${e.message}`)
      return ''
    }
  }

  _getPrismJs() {
    return this._prismJsCache || ''
  }

  _getPrismCss() {
    return this._prismCssCache || ''
  }

  _log(message) {
    try {
      if (this._logger && typeof this._logger.info === 'function') {
        this._logger.info(String(message))
      }
    } catch {
      // ignore
    }
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
      this._log(`[事件] Webview 可见性变化: ${webviewView.visible ? '可见' : '隐藏'}`)
      if (this._onVisibilityChanged) {
        this._onVisibilityChanged(!!webviewView.visible)
      }
      if (webviewView.visible) {
        this._sendMessage({ type: 'refresh' })
      }
    })

    /* 监听视图销毁事件 - 释放所有资源和事件监听器 */
    webviewView.onDidDispose(() => {
      this._log('[事件] Webview 已销毁')
      if (this._onVisibilityChanged) {
        this._onVisibilityChanged(false)
      }
      this._disposables.forEach(d => d.dispose())
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
        this._logger.warn(`Webview HTML 包含 ${tickCount} 个反引号字符：可能导致注入失败（建议继续外链化/运行时生成）`)
      }
    } catch {
      // ignore
    }

    // 诊断：若 Webview 脚本未执行/未上报 ready，会导致面板永远停在“连接中...”
    this._webviewReady = false
    if (this._webviewReadyTimer) {
      clearTimeout(this._webviewReadyTimer)
      this._webviewReadyTimer = null
    }
    this._webviewReadyTimer = setTimeout(() => {
      if (!this._webviewReady && this._logger && typeof this._logger.warn === 'function') {
        this._logger.warn('Webview 未上报 ready：可能脚本未执行（CSP/注入/HTML 结构破损）')
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
      // ignore
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
          } else if ((level === 'warn' || level === 'warning') && this._logger && typeof this._logger.warn === 'function') {
            this._logger.warn(text)
          } else if (level === 'info' && this._logger && typeof this._logger.info === 'function') {
            this._logger.info(text)
          } else if (this._logger && typeof this._logger.debug === 'function') {
            this._logger.debug(text)
          }
        } catch {
          // ignore
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
          // ignore
        }
        break
      case 'ready':
        this._webviewReady = true
        if (this._webviewReadyTimer) {
          clearTimeout(this._webviewReadyTimer)
          this._webviewReadyTimer = null
        }
        this._log('Webview 脚本 ready')
        break
      case 'serverStatus':
        // 只在状态变化时记录，避免刷屏
        try {
          const connected = !!(message && message.connected)
          if (connected !== this._lastServerStatus) {
            this._lastServerStatus = connected
            // 日志降噪策略：
            // - 首次“连接断开”多为初始化瞬态：仅 debug
            // - 首次“已连接”：info
            // - 曾连接过后再断开：warn（重要）
            if (connected) {
              this._hasEverConnected = true
              this._log('[事件] Webview 服务器状态: 已连接')
            } else if (this._hasEverConnected) {
              if (this._logger && typeof this._logger.warn === 'function') {
                this._logger.warn('[事件] Webview 服务器状态: 连接断开')
              } else {
                this._log('[事件] Webview 服务器状态: 连接断开')
              }
            } else if (this._logger && typeof this._logger.debug === 'function') {
              this._logger.debug('[事件] Webview 服务器状态: 连接断开')
            }
          }
        } catch {
          // ignore
        }
        break
      case 'showInfo':
        vscode.window.setStatusBarMessage(`$(info) ${message.message}`, 3000)
        break
      case 'requestClipboardText':
        this._handleRequestClipboardText(message)
        break
      default:
        // 忽略未知消息类型
        break
    }
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
    const serverUrl = this._serverUrl || 'http://localhost:8081'
    const cspSource = webview.cspSource
    // 重要：不要把 marked/prism 以“内联脚本”拼进 HTML（其内容包含反引号等字符，部分 Webview 注入实现会因此失败）
    // 改为外链加载（同样使用 nonce，CSP 更安全且更稳定）
    const markedJsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'marked.min.js'))
    const prismJsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'prism.min.js'))
    const prismCssUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'prism.min.css'))
    const webviewUiUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'webview-ui.js'))
    const extensionVersion = EXT_VERSION || '0.0.0'
    const githubUrl = EXT_GITHUB_URL || ''
    const githubUrlDisplay = githubUrl ? githubUrl.replace(/^https?:\/\//i, '') : ''
    const lottieJsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'lottie.min.js'))
    const noContentLottieJsonUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'lottie', 'sprout.json')
    )
    const nonce = getNonce()

    // 精简日志：移除 HTML 生成相关冗余日志

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; connect-src ${serverUrl} ${cspSource}; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}' ${cspSource}; img-src data: ${serverUrl} https: ${cspSource}; font-src ${serverUrl} data: ${cspSource};">
    <meta id="aiia-config" data-server-url="${serverUrl}" data-csp-nonce="${nonce}" data-lottie-lib-url="${lottieJsUri}" data-no-content-lottie-json-url="${noContentLottieJsonUri}">
    <title>AI Intervention Agent</title>
    <link rel="stylesheet" href="${prismCssUri}">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        /* Cursor 可能在 WebView 内注入默认 padding/margin，这里强制清零 */
        html, body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100%;
            height: 100%;
        }

        body {
            font-family: var(--vscode-font-family);
            font-size: var(--vscode-font-size);
            color: var(--vscode-foreground);
            background: var(--vscode-sideBar-background);
            overflow: hidden;
            height: 100vh;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        /* 全局滚动条 - 完全隐藏（macOS风格，通过滚轮/触摸滚动） */
        * {
            scrollbar-width: none;
        }
        *::-webkit-scrollbar {
            width: 0;
            height: 0;
            background: transparent;
        }

        .container {
            display: flex;
            flex-direction: column;
            height: 100%;
            background: var(--vscode-sideBar-background);
        }


        /* 任务标签栏容器 - 显示多个任务的标签页和连接状态指示器 */
        .tabs-container {
            display: flex;
            align-items: center;
            background: rgba(255, 255, 255, 0.02); /* 半透明背景 */
            border-bottom: 1px solid var(--vscode-panel-border);
            overflow-x: auto;
            overflow-y: hidden;
            flex-shrink: 0;
            position: relative;
            min-height: 34px;
            gap: 6px;
            padding: 4px 34px 4px 8px; /* 左右留白 + 右侧为设置按钮预留空间 */
            -webkit-overflow-scrolling: touch;
        }

        .settings-btn {
            position: absolute;
            right: 6px;
            top: 50%;
            transform: translateY(-50%);
            width: 22px;
            height: 22px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 1px solid transparent;
            border-radius: 6px;
            background: transparent;
            color: var(--vscode-foreground);
            cursor: pointer;
            opacity: 0.85;
            flex-shrink: 0;
            z-index: 2;
        }

        .settings-btn svg {
            width: 16px;
            height: 16px;
            display: block;
        }

        .no-content-settings-btn {
            top: 8px;
            right: 8px;
            transform: none;
        }

        .settings-btn:hover {
            opacity: 1;
            background: rgba(255, 255, 255, 0.06);
            border-color: rgba(127, 127, 127, 0.25);
        }

        /* 标签栏滚动条继承全局细滚动条样式 */

        .tabs-container.hidden {
            display: none;
        }

        .task-tab {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 5px 10px;
            background: rgba(255, 255, 255, 0.025);
            color: var(--vscode-tab-inactiveForeground);
            border: 1px solid rgba(127, 127, 127, 0.15);
            border-radius: 6px;
            cursor: pointer;
            white-space: nowrap;
            font-size: 11px;
            line-height: 1;
            transition: background 0.12s ease-out, border-color 0.12s ease-out, color 0.12s ease-out;
            position: relative;
            flex-shrink: 0;
            will-change: background, border-color;
            contain: layout style;
            user-select: none;
        }

        .task-tab:hover:not(.active) {
            background: rgba(255, 255, 255, 0.06);
            border-color: rgba(127, 127, 127, 0.25);
        }

        .task-tab.active {
            background: rgba(14, 99, 156, 0.1);
            color: var(--vscode-tab-activeForeground);
            border-color: rgba(14, 99, 156, 0.4);
            box-shadow: 0 1px 6px rgba(0, 0, 0, 0.12);
        }

        .task-tab-id {
            font-weight: 600;
            max-width: 140px;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .task-tab-status {
            width: 4px;
            height: 4px;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .task-tab-status.pending {
            background: var(--vscode-inputValidation-warningBackground);
        }

        .task-tab-status.active {
            background: var(--vscode-testing-iconPassed);
        }

        .task-tab-status.completed {
            background: var(--vscode-descriptionForeground);
        }

        .task-tab-countdown {
            position: relative;
            width: 16px;
            height: 16px;
            flex-shrink: 0;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }

        .task-tab-countdown svg {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            transform: rotate(-90deg);
        }

        .task-tab-countdown svg circle {
            stroke: var(--vscode-progressBar-background);
            fill: none;
            stroke-width: 2;
            stroke-linecap: round;
            transition: stroke-dashoffset 0.3s ease, stroke 0.2s;
        }

        .task-tab-countdown-number {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 5.5px;
            font-weight: 600;
            color: var(--vscode-editor-foreground);
            z-index: 2;
            line-height: 1;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .status-indicator {
            display: flex;
            align-items: center;
            padding: 0;
            flex-shrink: 0;
        }

        .breathing-light {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--vscode-testing-iconQueued); /* 黄色 - 初始/加载状态 */
            animation: breathing 2s ease-in-out infinite;
            flex-shrink: 0;
        }

        .breathing-light.connected {
            background: var(--vscode-testing-iconPassed); /* 绿色 - 已连接 */
        }

        .breathing-light.disconnected {
            background: var(--vscode-testing-iconFailed); /* 红色 - 未连接 */
        }

        @keyframes breathing {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }

        /* 主内容区域 - 深色背景以适配VSCode主题 */
        .content {
            flex: 1;
            overflow: hidden;
            background: var(--vscode-sideBar-background);
            display: flex;
            flex-direction: column;
        }

        /* 无有效内容状态 - 等待新任务时显示的占位界面 */
        .no-content {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--vscode-descriptionForeground);
            text-align: center;
            padding: 24px 32px 64px; /* 整体略向上：底部留更大间隙 */
            position: relative;
        }

        .no-content-icon {
            width: 120px; /* 对齐原项目：Lottie 容器较大 */
            height: 120px;
            font-size: 64px; /* 备用 emoji（对齐原项目 4rem ≈ 64px） */
            margin-bottom: 8px;
            opacity: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            pointer-events: none;
        }

        .no-content-icon svg {
            width: 100%;
            height: 100%;
        }

        .no-content .title {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 6px;
            color: var(--vscode-foreground);
        }

        .no-content .status-indicator-standalone {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: var(--vscode-descriptionForeground);
            margin-top: 16px;
            margin-bottom: 12px;
        }

        .no-content-progress {
            width: 180px;
            height: 6px;
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.05));
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1) inset;
        }

        .no-content-progress-bar {
            width: 100%;
            height: 100%;
            background: #5a8dbf; /* 参考原项目：深色模式的深蓝色 */
            animation: loading 1.5s linear infinite;
            border-radius: 8px;
            will-change: transform;
        }

        /* VSCode 浅色主题：参考原项目的浅色进度条配色 */
        body.vscode-light .no-content-progress {
            box-shadow: none;
            background: rgba(0, 0, 0, 0.05);
        }
        body.vscode-light .no-content-progress-bar {
            background: #e3dacc; /* 奶油米色 */
        }

        @keyframes loading {
            0% {
                transform: translateX(-100%);
            }
            50% {
                transform: translateX(0%);
            }
            100% {
                transform: translateX(100%);
            }
        }

        /* Markdown内容容器 - 渲染服务端返回的任务提示信息 */
        .markdown-content {
            line-height: 1.7;
            margin: 0 0 8px 0 !important;
            background: rgba(255, 255, 255, 0.035);
            padding: 14px 12px;
            border-radius: 6px;
            border: 1px solid rgba(127, 127, 127, 0.15);
            contain: layout style;
        }

        .markdown-content h1,
        .markdown-content h2,
        .markdown-content h3 {
            margin-top: 20px;
            margin-bottom: 10px;
            color: var(--vscode-editor-foreground);
        }

        .markdown-content p {
            margin-bottom: 12px;
        }

        /* Markdown行内代码样式 - 红色高亮显示代码片段 */
        .markdown-content code {
            background: rgba(255, 255, 255, 0.08);
            color: var(--vscode-textPreformat-foreground);
            padding: 3px 7px;
            border-radius: 4px;
            font-family: var(--vscode-editor-font-family);
            font-size: 0.88em;
            border: 1px solid rgba(127, 127, 127, 0.15);
        }

        /* Markdown代码块样式 - 深色背景的多行代码展示 */
        .markdown-content pre {
            background: rgba(255, 255, 255, 0.06);
            padding: 14px 16px;
            border-radius: 6px;
            overflow-x: auto;
            margin-bottom: 14px;
            border: 1px solid rgba(127, 127, 127, 0.18);
        }

        .markdown-content pre code {
            background: none;
            padding: 0;
            border: none;
        }

        .markdown-content ul,
        .markdown-content ol {
            margin-bottom: 12px;
            padding-left: 24px;
        }

        .markdown-content li {
            margin-bottom: 6px;
        }

        .markdown-content .task-list {
            list-style: none;
            padding-left: 0;
        }

        .markdown-content .task-item {
            display: flex;
            align-items: flex-start;
            gap: 8px;
        }

        .markdown-content .task-item input[type="checkbox"] {
            margin-top: 4px;
            pointer-events: none;
        }

        .markdown-content blockquote {
            margin: 12px 0;
            padding: 8px 12px;
            border-left: 3px solid var(--vscode-textBlockQuote-border, #666);
            background: rgba(255, 255, 255, 0.02);
            color: var(--vscode-textBlockQuote-foreground, inherit);
        }

        .markdown-content hr {
            border: none;
            border-top: 1px solid var(--vscode-panel-border);
            margin: 16px 0;
        }

        .markdown-content a {
            color: var(--vscode-textLink-foreground);
            text-decoration: none;
        }

        .markdown-content a:hover {
            text-decoration: underline;
        }

        .markdown-content img {
            max-width: 100%;
            height: auto;
            border-radius: 4px;
        }

        .markdown-content del {
            opacity: 0.6;
        }

        .markdown-content strong {
            font-weight: 600;
        }

        .markdown-content em {
            font-style: italic;
        }

        /* 反馈表单容器 - 包含输入框、选项和按钮的主要交互区域 */
        .feedback-form {
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
        }

        .scrollable-content {
            flex: 1;
            overflow-y: auto;
            padding: 4px 10px 8px 10px; /* 顶部4px，底部8px，左右留白 */
            background: var(--vscode-sideBar-background);
            -webkit-overflow-scrolling: touch;
            will-change: scroll-position;
            contain: layout style paint;
            scroll-behavior: smooth;
            overscroll-behavior: contain;
        }

        .scrollable-content > *:first-child {
            margin-top: 0;
        }

        .scrollable-content > * {
            margin: 0 0 8px 0;
        }

        .scrollable-content > *:last-child {
            margin-bottom: 0;
        }

        .fixed-input-area {
            flex-shrink: 0;
            padding: 4px 10px 6px 10px; /* 左右留白，避免输入框贴边 */
            background: transparent;
        }

        .form-section {
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding: 14px 12px;
            margin: 0 0 8px 0 !important;
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid rgba(127, 127, 127, 0.15);
            border-radius: 6px;
        }

        .form-label {
            font-size: 12px;
            font-weight: 600;
            color: var(--vscode-foreground);
            margin-bottom: 2px;
        }

        .textarea-wrapper {
            position: relative;
            display: flex;
            flex-direction: column;
            margin: 0;
            padding: 0;
        }

        .textarea-resize-handle {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 8px;
            cursor: ns-resize;
            z-index: 20;
            background: transparent;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .textarea-resize-handle:hover::before,
        .textarea-resize-handle:active::before {
            content: '';
            width: 40px;
            height: 3px;
            background: var(--vscode-focusBorder);
            border-radius: 2px;
            opacity: 0.6;
        }

        .feedback-textarea {
            width: 100%;
            height: 100px;
            min-height: 80px;
            max-height: 300px;
            padding: 12px;
            padding-top: 16px;
            padding-bottom: 48px;
            background: transparent; /* 输入框边框内背景透明 */
            color: var(--vscode-input-foreground);
            border: 1px solid rgba(127, 127, 127, 0.15);
            border-radius: 6px;
            font-family: var(--vscode-font-family);
            font-size: 13px;
            line-height: 1.65;
            resize: none;
            overflow-y: auto;
            transition: border-color 0.1s ease-out, box-shadow 0.1s ease-out, background 0.1s ease-out;
            will-change: border-color;
            contain: layout style paint;
        }

        .feedback-textarea:focus {
            outline: none;
            border-color: var(--vscode-focusBorder);
            box-shadow: 0 0 0 1px var(--vscode-focusBorder);
            background: transparent;
        }

        .feedback-textarea:hover:not(:focus) {
            border-color: rgba(127, 127, 127, 0.25);
            background: transparent;
        }

        .input-buttons {
            position: absolute;
            bottom: 10px;
            right: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
            z-index: 10;
        }

        .insert-code-btn,
        .upload-btn,
        .submit-btn-embedded {
            width: 28px;
            height: 28px;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            border-radius: 50%;
            font-size: 14px;
            font-weight: 400;
            cursor: pointer;
        }

        .insert-code-btn,
        .upload-btn {
            background: rgba(255, 255, 255, 0.08);
        }

        .insert-code-btn:hover:not(:disabled),
        .upload-btn:hover:not(:disabled) {
            background: rgba(255, 255, 255, 0.15);
        }

        .submit-btn-embedded:hover:not(:disabled) {
            background: var(--vscode-button-hoverBackground);
        }

        .insert-code-btn:disabled,
        .upload-btn:disabled,
        .submit-btn-embedded:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Claude 风格按钮图标（使用 currentColor 适配主题） */
        .btn-icon {
            width: 16px;
            height: 16px;
            display: block;
        }

        /* 右箭头图标旋转为“上箭头”（提交） */
        .submit-icon {
            transform: rotate(-90deg);
        }

        @keyframes aiia-spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }

        .spinner-icon {
            animation: aiia-spin 0.9s linear infinite;
        }

        /* 选项列表容器 - 显示服务端提供的预定义选项供用户选择 */
        .options-container {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 2px;
        }

        .option-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 12px;
            background: rgba(255, 255, 255, 0.025);
            border: 1px solid rgba(127, 127, 127, 0.15);
            border-radius: 5px;
            cursor: pointer;
            transition: background 0.1s ease-out, border-color 0.1s ease-out;
            position: relative;
            will-change: background, border-color;
            contain: layout style;
        }

        .option-item:hover {
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(127, 127, 127, 0.25);
        }

        .option-item.selected {
            background: rgba(14, 99, 156, 0.1);
            border-color: rgba(14, 99, 156, 0.4);
        }

        .option-item.selected:hover {
            background: rgba(14, 99, 156, 0.15);
        }

        .option-checkbox {
            width: 16px;
            height: 16px;
        }

        .option-label {
            flex: 1;
            font-size: 13px;
        }


        .uploaded-images {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 6px;
            min-height: 0;
            transition: min-height 0.2s ease;
        }

        .uploaded-images:not(:empty) {
            min-height: 72px;
        }

        .image-preview {
            position: relative;
            width: 80px;
            height: 80px;
            border-radius: 4px;
            overflow: hidden;
            border: 1px solid var(--vscode-input-border);
            background: rgba(255, 255, 255, 0.05);
        }

        .image-preview img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

        .image-remove {
            position: absolute;
            top: 4px;
            right: 4px;
            background: rgba(0, 0, 0, 0.8);
            color: white;
            border: none;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: bold;
            transition: background 0.2s;
        }

        .image-remove:hover {
            background: rgba(220, 38, 38, 0.9);
        }

        /* 倒计时容器 - 显示任务自动提交的剩余时间 */
        .countdown-container {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 12px;
            background: var(--vscode-inputValidation-warningBackground);
            border: 1px solid var(--vscode-inputValidation-warningBorder);
            border-radius: 6px;
            margin-bottom: 16px;
        }

        .countdown-ring {
            position: relative;
            width: 40px;
            height: 40px;
        }

        .countdown-ring svg {
            transform: rotate(-90deg);
            width: 40px;
            height: 40px;
        }

        .countdown-ring-circle {
            stroke: var(--vscode-panel-border);
            fill: none;
            stroke-width: 3;
        }

        .countdown-ring-progress {
            stroke: var(--vscode-progressBar-background);
            fill: none;
            stroke-width: 3;
            stroke-linecap: round;
            transition: stroke-dashoffset 1s linear;
        }

        .countdown-text-container {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 10px;
            font-weight: 600;
            color: var(--vscode-editor-foreground);
        }

        .countdown-message {
            font-size: 12px;
            color: var(--vscode-inputValidation-warningForeground);
        }

        /* 按钮容器 - 包含提交反馈等操作按钮 */
        .button-container {
            display: flex;
            gap: 8px;
        }

        .submit-btn {
            flex: 1;
            padding: 12px 24px;
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
        }

        .submit-btn:hover:not(:disabled) {
            background: var(--vscode-button-hoverBackground);
            transform: translateY(-2px);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.16);
        }

        .submit-btn:active:not(:disabled) {
            transform: translateY(0);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
        }

        .submit-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }


        .loading {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 200px;
            gap: 12px;
        }

        .spinner {
            width: 20px;
            height: 20px;
            border: 2px solid rgba(127, 127, 127, 0.3);
            border-top: 2px solid var(--vscode-progressBar-background);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* 设置面板（通知配置） */
        .settings-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.35);
            z-index: 2000;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 10px;
        }

        .settings-panel {
            width: 100%;
            max-width: 520px;
            max-height: 90vh;
            background: var(--vscode-sideBar-background);
            border: 1px solid var(--vscode-panel-border);
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
        }

        .settings-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 12px;
            border-bottom: 1px solid var(--vscode-panel-border);
            background: rgba(255, 255, 255, 0.02);
        }

        .settings-title {
            font-size: 12px;
            font-weight: 600;
        }

        .settings-close {
            width: 26px;
            height: 26px;
            border-radius: 8px;
            border: 1px solid transparent;
            background: transparent;
            color: var(--vscode-foreground);
            cursor: pointer;
            opacity: 0.85;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0;
        }

        .settings-close:hover {
            opacity: 1;
            background: rgba(255, 255, 255, 0.06);
            border-color: rgba(127, 127, 127, 0.25);
        }

        .settings-close:focus-visible {
            outline: 1px solid var(--vscode-focusBorder);
            outline-offset: 2px;
        }

        .settings-close svg {
            width: 14px;
            height: 14px;
            display: block;
        }

        .settings-body {
            padding: 12px;
            overflow: auto;
            max-height: calc(90vh - 50px);
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .settings-toggle,
        .settings-field {
            border: 1px solid rgba(127, 127, 127, 0.18);
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.02);
            padding: 8px 10px;
        }

        .settings-toggle {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }

        .settings-field {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .settings-label {
            font-size: 11px;
            opacity: 0.9;
        }

        .settings-field input[type="text"],
        .settings-field input[type="number"] {
            width: 100%;
            padding: 8px 10px;
            border-radius: 8px;
            border: 1px solid rgba(127, 127, 127, 0.22);
            background: rgba(0, 0, 0, 0.12);
            color: var(--vscode-foreground);
            outline: none;
        }

        .settings-field input[type="text"]:focus,
        .settings-field input[type="number"]:focus {
            border-color: var(--vscode-focusBorder);
        }

        .settings-divider {
            height: 1px;
            background: var(--vscode-panel-border);
            opacity: 0.6;
            margin: 4px 0;
        }

        .settings-actions {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            flex-wrap: wrap;
        }

        .settings-actions-right {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-left: auto;
        }

        .settings-action {
            border: 1px solid rgba(127, 127, 127, 0.22);
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border-radius: 8px;
            padding: 6px 10px;
            cursor: pointer;
            font-size: 12px;
        }

        .settings-action:hover {
            background: var(--vscode-button-hoverBackground);
        }

        .settings-action.secondary {
            background: rgba(255, 255, 255, 0.06);
            color: var(--vscode-foreground);
        }

        .settings-action.secondary:hover {
            background: rgba(255, 255, 255, 0.10);
        }

        .settings-hint {
            font-size: 11px;
            opacity: 0.85;
            min-height: 16px;
        }

        .settings-auto-save {
            font-size: 11px;
            opacity: 0.85;
            padding: 2px 8px;
            border-radius: 999px;
            border: 1px solid rgba(127, 127, 127, 0.25);
            background: rgba(255, 255, 255, 0.04);
            user-select: none;
        }

        .settings-footer {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            opacity: 0.75;
            padding-top: 2px;
        }

        .settings-footer-sep {
            opacity: 0.5;
        }

        .settings-footer-link {
            color: var(--vscode-textLink-foreground);
            text-decoration: none;
        }

        .settings-footer-link:hover {
            text-decoration: underline;
        }

        /* 代码块工具栏（复制/语言标签） */
        .code-block-container {
            position: relative;
        }

        .code-toolbar {
            position: absolute;
            top: 8px;
            right: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
            opacity: 0;
            transition: opacity 0.15s ease;
            pointer-events: none; /* 仅按钮可点击 */
        }

        .code-block-container:hover .code-toolbar {
            opacity: 1;
        }

        .code-toolbar .language-label {
            pointer-events: none;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 6px;
            border: 1px solid rgba(127, 127, 127, 0.25);
            background: rgba(0, 0, 0, 0.12);
            color: var(--vscode-foreground);
            opacity: 0.85;
        }

        .code-toolbar .copy-button {
            pointer-events: auto;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 26px;
            height: 24px;
            padding: 0;
            line-height: 0;
            border-radius: 6px;
            border: 1px solid rgba(127, 127, 127, 0.25);
            background: rgba(0, 0, 0, 0.18);
            color: var(--vscode-foreground);
        }

        .code-toolbar .copy-button svg {
            width: 14px;
            height: 14px;
            display: block;
        }

        .code-toolbar .copy-button:hover {
            background: rgba(0, 0, 0, 0.28);
        }

        .code-toolbar .copy-button.copied {
            border-color: rgba(34, 197, 94, 0.55);
            background: rgba(34, 197, 94, 0.18);
        }

        .code-toolbar .copy-button.error {
            border-color: rgba(239, 68, 68, 0.55);
            background: rgba(239, 68, 68, 0.18);
        }

        .hidden {
            display: none !important;
        }

    </style>
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
                <div>正在连接服务器...</div>
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
                <div class="title">无有效内容</div>
                <div class="status-indicator-standalone">
                    <div class="breathing-light" id="statusLightStandalone" title="服务器连接状态"></div>
                    <span id="statusTextStandalone">连接中...</span>
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
                            placeholder="在此输入您的反馈（支持粘贴图片）..."
                        ></textarea>

                        <!-- Hidden file input -->
                        <input type="file" id="imageInput" accept="image/*" multiple class="hidden">

                        <!-- Button group (upload + submit) -->
                        <div class="input-buttons">
                            <button class="insert-code-btn" id="insertCodeBtn" title="插入代码（从剪贴板）" aria-label="插入代码">
                                <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                                    <polyline points="16 18 22 12 16 6"></polyline>
                                    <polyline points="8 6 2 12 8 18"></polyline>
                                    <line x1="14" y1="4" x2="10" y2="20"></line>
                                </svg>
                            </button>
                            <button class="upload-btn" id="uploadBtn" title="上传图片" aria-label="上传图片">
                                <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
                                    <path fill-rule="evenodd" clip-rule="evenodd" d="M3 4.5C3 3.67157 3.67157 3 4.5 3H15.5C16.3284 3 17 3.67157 17 4.5V15.5C17 16.3284 16.3284 17 15.5 17H4.5C3.67157 17 3 16.3284 3 15.5V4.5ZM4.5 4C4.22386 4 4 4.22386 4 4.5V12.2929L6.64645 9.64645C6.84171 9.45118 7.15829 9.45118 7.35355 9.64645L10 12.2929L13.1464 9.14645C13.3417 8.95118 13.6583 8.95118 13.8536 9.14645L16 11.2929V4.5C16 4.22386 15.7761 4 15.5 4H4.5ZM16 12.7071L13.5 10.2071L10.3536 13.3536C10.1583 13.5488 9.84171 13.5488 9.64645 13.3536L7 10.7071L4 13.7071V15.5C4 15.7761 4.22386 16 4.5 16H15.5C15.7761 16 16 15.7761 16 15.5V12.7071ZM7 7.5C7 6.94772 7.44772 6.5 8 6.5C8.55228 6.5 9 6.94772 9 7.5C9 8.05228 8.55228 8.5 8 8.5C7.44772 8.5 7 8.05228 7 7.5Z" fill="currentColor" />
                                </svg>
                            </button>
                            <button class="submit-btn-embedded" id="submitBtn" title="提交反馈" aria-label="提交反馈">
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
                    <span>Web 通知</span>
                    <input type="checkbox" id="notifyWebEnabled">
                </label>
                <label class="settings-toggle">
                    <span>自动请求权限</span>
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
                    <button class="settings-action secondary" id="settingsTestBarkBtn">测试 Bark</button>
                    <div class="settings-actions-right">
                        <span class="settings-auto-save" title="修改后会自动同步到服务端">自动保存</span>
                    </div>
                </div>
                <div class="settings-footer" id="settingsFooter">
                    <span class="settings-footer-item">VSCode 插件 v${extensionVersion}</span>
                    <span class="settings-footer-sep">·</span>
                    <span class="settings-footer-item">GitHub:</span>
                    <a class="settings-footer-link" href="${githubUrl}" target="_blank" rel="noopener noreferrer">${githubUrlDisplay}</a>
                </div>
                <div class="settings-hint" id="settingsHint"></div>
            </div>
        </div>
    </div>

    <!-- Prism.js for code highlighting (from original project) -->
    <!-- Prism.js for code highlighting -->
    <script nonce="${nonce}">window.Prism = window.Prism || {}; Prism.manual = true;</script>
    <script nonce="${nonce}" src="${prismJsUri}"></script>

    <!-- marked.js for Markdown rendering -->
    <script nonce="${nonce}" src="${markedJsUri}"></script>

        <script nonce="${nonce}" src="${webviewUiUri}"></script>
</body>
</html>`
  }
}

module.exports = { WebviewProvider }
