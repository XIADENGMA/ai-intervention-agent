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
      typeof timeoutMsRaw === 'number' && Number.isFinite(timeoutMsRaw)
        ? Math.max(0, Math.floor(timeoutMsRaw))
        : 3000

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
    this._hostBundleId = ''
    this._hostBundleIdResolved = false
    this._hostBundleIdResolvePromise = null
  }

  _looksLikeBundleId(value) {
    try {
      const s = (value ?? '').toString().trim()
      if (!s) return false
      // 仅允许常见 bundle id 字符，避免把异常输出写入环境变量
      return /^[A-Za-z0-9.-]+$/.test(s)
    } catch {
      return false
    }
  }

  async _resolveHostBundleId() {
    if (this._hostBundleIdResolved) return this._hostBundleId
    if (this._hostBundleIdResolvePromise) return this._hostBundleIdResolvePromise

    // 仅在 macOS 尝试：其它平台无意义（且可能在测试环境中没有对应应用）
    if (process.platform !== 'darwin') {
      this._hostBundleIdResolved = true
      this._hostBundleId = ''
      return ''
    }

    const vs = this._vscode
    const appName =
      vs && vs.env && typeof vs.env.appName === 'string' && vs.env.appName.trim()
        ? String(vs.env.appName).trim()
        : ''
    if (!appName || !this._executor || typeof this._executor.runAppleScript !== 'function') {
      this._hostBundleIdResolved = true
      this._hostBundleId = ''
      return ''
    }

    const script = `id of application ${toAppleScriptStringLiteral(appName)}`
    this._hostBundleIdResolvePromise = Promise.resolve()
      .then(() => this._executor.runAppleScript(script))
      .then(out => {
        const id = (out ?? '').toString().trim()
        this._hostBundleId = this._looksLikeBundleId(id) ? id : ''
        this._hostBundleIdResolved = true
        return this._hostBundleId
      })
      .catch(() => {
        this._hostBundleId = ''
        this._hostBundleIdResolved = true
        return ''
      })
      .finally(() => {
        this._hostBundleIdResolvePromise = null
      })
    return this._hostBundleIdResolvePromise
  }

  async send(event) {
    const vs = this._vscode
    const title = toNonEmptyString(event && event.title, 'AI Intervention Agent')
    const message = toNonEmptyString(event && event.message, '')
    if (!message) return false

    const md = event && event.metadata && typeof event.metadata === 'object' ? event.metadata : {}
    const isTest = !!(md && md.isTest)

    // 非测试通知：非 macOS 平台直接跳过，避免无意义的 AppleScript 调用
    // 测试通知（isTest=true）：用于 UI/单测校验，可允许注入的 executor 在任意平台被调用
    if (!isTest && process.platform !== 'darwin') {
      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'notify.macos_native.skipped',
            { reason: 'non_macos', platform: process.platform },
            { level: 'debug' }
          )
        } else if (this._logger && typeof this._logger.debug === 'function') {
          this._logger.debug('忽略原生通知：非 macOS 平台')
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
      // 尝试将通知“归属”到宿主应用（VS Code / Cursor），以改善通知点击行为（避免打开脚本编辑器）
      // 说明：AppleScript 本身不支持通知点击回调；这里的目标仅是让点击激活宿主应用或至少不再打开脚本编辑器。
      // 通过为 osascript 进程注入 __CFBundleIdentifier，可能让系统把通知归属到指定 bundle id。
      let runOptions = undefined
      try {
        const bundleId = await this._resolveHostBundleId()
        if (bundleId) {
          runOptions = { env: { __CFBundleIdentifier: bundleId } }
        }
      } catch {
        runOptions = undefined
      }

      await this._executor.runAppleScript(script, runOptions)
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
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'notify.macos_native.fail',
            { code: code || 'unknown', error: raw || '' },
            { level: 'warn' }
          )
        } else if (this._logger && typeof this._logger.warn === 'function') {
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
