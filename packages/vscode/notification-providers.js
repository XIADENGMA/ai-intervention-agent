const vscode = require('vscode')
const { toAppleScriptStringLiteral } = require('./applescript-executor')

function toNonEmptyString(value, fallback = '') {
  const s = value == null ? '' : String(value)
  const t = s.trim()
  return t ? t : fallback
}

class VSCodeApiNotificationProvider {
  constructor(options = {}) {
    this._logger = options && options.logger ? options.logger : null
    this._vscode = options && options.vscodeApi ? options.vscodeApi : vscode
  }

  async send(event) {
    const vs = this._vscode
    if (!vs || !vs.window) return false

    const title = toNonEmptyString(event && event.title, 'AI Intervention Agent')
    const message = toNonEmptyString(event && event.message, '')
    if (!message) return false

    const md = event && event.metadata && typeof event.metadata === 'object' ? event.metadata : {}
    const presentation = toNonEmptyString(md.presentation, 'statusBar') // 展示方式：statusBar | toast
    const severity = toNonEmptyString(md.severity, 'info') // 严重级别：info | warn | error
    const timeoutMsRaw = md && md.timeoutMs
    const timeoutMs =
      typeof timeoutMsRaw === 'number' && Number.isFinite(timeoutMsRaw) ? Math.max(0, Math.floor(timeoutMsRaw)) : 3000

    if (presentation === 'toast') {
      const text = `${title}: ${message}`
      if (severity === 'error' && typeof vs.window.showErrorMessage === 'function') {
        vs.window.showErrorMessage(text)
      } else if (severity === 'warn' && typeof vs.window.showWarningMessage === 'function') {
        vs.window.showWarningMessage(text)
      } else if (typeof vs.window.showInformationMessage === 'function') {
        vs.window.showInformationMessage(text)
      }
      return true
    }

    // 默认：状态栏提示（对齐旧实现）
    const icon = severity === 'error' ? '$(error)' : severity === 'warn' ? '$(warning)' : '$(info)'
    try {
      vs.window.setStatusBarMessage(`${icon} ${message}`, timeoutMs)
      return true
    } catch (e) {
      try {
        if (this._logger && typeof this._logger.warn === 'function') {
          this._logger.warn(`VSCode 状态栏提示失败: ${e && e.message ? e.message : String(e)}`)
        }
      } catch {
        // 忽略：日志系统异常不应影响通知流程
      }
      return false
    }
  }
}

class AppleScriptNotificationProvider {
  constructor(options = {}) {
    this._logger = options && options.logger ? options.logger : null
    this._executor = options && options.executor ? options.executor : null
    this._vscode = options && options.vscodeApi ? options.vscodeApi : vscode
  }

  _isAppleScriptEnabled() {
    try {
      const cfg = this._vscode.workspace.getConfiguration('ai-intervention-agent')
      return !!cfg.get('enableAppleScript', false)
    } catch {
      return false
    }
  }

  async send(event) {
    const vs = this._vscode
    const title = toNonEmptyString(event && event.title, 'AI Intervention Agent')
    const message = toNonEmptyString(event && event.message, '')
    if (!message) return false

    const md = event && event.metadata && typeof event.metadata === 'object' ? event.metadata : {}
    const isTest = !!(md && md.isTest)

    if (process.platform !== 'darwin') {
      if (isTest && vs && vs.window && typeof vs.window.showErrorMessage === 'function') {
        vs.window.showErrorMessage('Platform not supported')
      }
      try {
        if (this._logger && typeof this._logger.debug === 'function') {
          this._logger.debug('忽略原生通知：非 macOS 平台')
        }
      } catch {
        // 忽略：日志系统异常不应影响通知流程
      }
      return false
    }

    if (!this._isAppleScriptEnabled()) {
      const tip = 'AppleScript 执行未启用：请在设置中打开 ai-intervention-agent.enableAppleScript'
      if (isTest && vs && vs.window && typeof vs.window.showErrorMessage === 'function') {
        vs.window.showErrorMessage(tip)
      }
      try {
        if (this._logger && typeof this._logger.warn === 'function') {
          this._logger.warn(tip)
        }
      } catch {
        // 忽略：日志系统异常不应影响通知流程
      }
      return false
    }

    if (!this._executor || typeof this._executor.runAppleScript !== 'function') {
      if (isTest && vs && vs.window && typeof vs.window.showErrorMessage === 'function') {
        vs.window.showErrorMessage('AppleScript 执行器不可用')
      }
      return false
    }

    const script = `display notification ${toAppleScriptStringLiteral(message)} with title ${toAppleScriptStringLiteral(title)}`
    try {
      await this._executor.runAppleScript(script)
      return true
    } catch (e) {
      const code = e && e.code ? String(e.code) : ''
      const raw = e && e.message ? String(e.message) : String(e)
      const msg =
        code === 'APPLE_SCRIPT_TIMEOUT'
          ? 'AppleScript 执行超时'
          : raw
            ? `AppleScript 执行失败：${raw}`
            : 'AppleScript 执行失败'
      if (isTest && vs && vs.window && typeof vs.window.showErrorMessage === 'function') {
        vs.window.showErrorMessage(msg)
      }
      try {
        if (this._logger && typeof this._logger.warn === 'function') {
          this._logger.warn(`原生通知失败 code=${code || 'unknown'} msg=${raw || ''}`.trim())
        }
      } catch {
        // 忽略：日志系统异常不应影响通知流程
      }
      return false
    }
  }
}

module.exports = {
  VSCodeApiNotificationProvider,
  AppleScriptNotificationProvider
}

