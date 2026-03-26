const vscode = require('vscode')
const fs = require('fs')
const path = require('path')
const { execFile } = require('child_process')
const { toAppleScriptStringLiteral, sanitizeForLog } = require('./applescript-executor')

function toNonEmptyString(value, fallback = '') {
  const s = value == null ? '' : String(value)
  const t = s.trim()
  return t ? t : fallback
}

function execFileAsyncWithOutput(file, args, options) {
  return new Promise((resolve, reject) => {
    const startedAt = Date.now()
    try {
      execFile(
        file,
        Array.isArray(args) ? args : [],
        Object.assign({ encoding: 'utf8', windowsHide: true }, options || {}),
        (error, stdout, stderr) => {
          const durationMs = Date.now() - startedAt
          const outText = (stdout ?? '').toString()
          const errText = (stderr ?? '').toString()
          if (error) {
            const exitCode =
              typeof error.code === 'number' && Number.isFinite(error.code) ? error.code : null
            const signal = error && error.signal ? String(error.signal) : ''
            const msg =
              errText.trim() || (error && error.message ? String(error.message) : 'execFile failed')
            const err = new Error(msg)
            err.code = 'EXEC_FAILED'
            err.cause = error
            err.details = {
              file: String(file || ''),
              args: Array.isArray(args) ? args.map(String) : [],
              exitCode,
              signal,
              durationMs,
              stderr: errText.trim(),
              stderrPreview: sanitizeForLog(errText, 400),
              stdoutPreview: sanitizeForLog(outText, 240),
              stdoutLen: outText.length
            }
            reject(err)
            return
          }
          resolve({ stdout: outText, stderr: errText, durationMs })
        }
      )
    } catch (e) {
      const err = e instanceof Error ? e : new Error(String(e))
      err.code = 'EXEC_SPAWN_FAILED'
      err.details = { file: String(file || ''), args: Array.isArray(args) ? args.map(String) : [] }
      reject(err)
    }
  })
}

function execFileAsync(file, args, options) {
  return new Promise((resolve, reject) => {
    try {
      execFile(
        file,
        Array.isArray(args) ? args : [],
        Object.assign({ encoding: 'utf8', windowsHide: true }, options || {}),
        (error, stdout, stderr) => {
          if (error) {
            const errText = (stderr ?? '').toString().trim()
            const msg =
              errText || (error && error.message ? String(error.message) : 'execFile failed')
            const err = new Error(msg)
            err.code = 'EXEC_FAILED'
            err.cause = error
            err.details = {
              file: String(file || ''),
              args: Array.isArray(args) ? args.map(String) : []
            }
            reject(err)
            return
          }
          resolve((stdout ?? '').toString())
        }
      )
    } catch (e) {
      const err = e instanceof Error ? e : new Error(String(e))
      err.code = 'EXEC_SPAWN_FAILED'
      reject(err)
    }
  })
}

function findMacAppBundlePathFromAppRoot(appRoot) {
  try {
    let p = (appRoot ?? '').toString().trim()
    if (!p) return ''
    // 常见形态：
    // - VS Code: /Applications/Visual Studio Code.app/Contents/Resources/app
    // - Cursor:  /Applications/Cursor.app/Contents/Resources/app
    for (let i = 0; i < 12; i++) {
      if (!p) break
      if (p.toLowerCase().endsWith('.app')) return p
      const parent = path.dirname(p)
      if (!parent || parent === p) break
      p = parent
    }
    return ''
  } catch {
    return ''
  }
}

function resolveBundledTerminalNotifierBinPath() {
  try {
    return path.join(
      __dirname,
      'vendor',
      'terminal-notifier',
      'terminal-notifier.app',
      'Contents',
      'MacOS',
      'terminal-notifier'
    )
  } catch {
    return ''
  }
}

function ensureExecutable(filePath) {
  try {
    if (!filePath) return false
    if (!fs.existsSync(filePath)) return false
    try {
      fs.chmodSync(filePath, 0o755)
    } catch {
      // 忽略：权限保持尽力而为（vsix 解压可能保留原始 mode）
    }
    return true
  } catch {
    return false
  }
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
    this._lastDiagnostic = null
    // 防止“注入 __CFBundleIdentifier”在特定宿主/系统下反复卡住：失败后短时间内禁用注入，优先保证通知可用/快速返回
    this._bundleInjectionDisabledUntilMs = 0
    // 缓存宿主 .app 路径，用于 AppleScript activate 命令
    this._hostAppBundlePath = ''
    this._hostAppBundlePathResolved = false
  }

  getLastDiagnostic() {
    return this._lastDiagnostic
  }

  _extractAppleScriptError(e) {
    const code = e && e.code ? String(e.code) : 'unknown'
    const message = e && e.message ? String(e.message) : String(e)
    const details = e && e.details && typeof e.details === 'object' ? e.details : {}
    const exitCode =
      details && typeof details.exitCode === 'number' && Number.isFinite(details.exitCode)
        ? details.exitCode
        : null
    const signal = details && details.signal ? String(details.signal) : ''
    const stderr = details && details.stderr ? String(details.stderr) : ''
    const durationMs =
      details && typeof details.durationMs === 'number' && Number.isFinite(details.durationMs)
        ? details.durationMs
        : null
    const injectedEnvKeys =
      details && Array.isArray(details.injectedEnvKeys) ? details.injectedEnvKeys.map(String) : []
    return {
      code,
      message,
      exitCode,
      signal,
      durationMs,
      stderr,
      stderrPreview: sanitizeForLog(stderr, 400),
      injectedEnvKeys
    }
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

  /**
   * 解析宿主 .app 路径（如 /Applications/Visual Studio Code.app）
   * 用于 AppleScript `activate` 激活窗口
   */
  _resolveHostAppBundlePath() {
    if (this._hostAppBundlePathResolved) return this._hostAppBundlePath
    try {
      const vs = this._vscode
      const appRoot =
        vs && vs.env && typeof vs.env.appRoot === 'string' && vs.env.appRoot.trim()
          ? String(vs.env.appRoot).trim()
          : ''
      if (appRoot) {
        this._hostAppBundlePath = findMacAppBundlePathFromAppRoot(appRoot) || ''
      }
    } catch {
      this._hostAppBundlePath = ''
    }
    this._hostAppBundlePathResolved = true
    return this._hostAppBundlePath
  }

  /**
   * 发送通知后，尝试通过 AppleScript 激活宿主 IDE 窗口。
   * 这是一个 best-effort 操作，不会阻塞或影响通知发送结果。
   * 使用 bundleId 通过 `tell application id "..."` 来激活，比使用应用名更可靠。
   * @param {string} bundleId 宿主 Bundle ID
   */
  _fireActivateHost(bundleId) {
    if (!bundleId || !this._executor || typeof this._executor.runAppleScript !== 'function') return
    try {
      // 使用 "tell application id" 比 "tell application name" 更可靠
      // Cursor 等非标 IDE 的 appName 可能无法被 AppleScript 识别
      // reopen：恢复最小化到 Dock 的窗口
      // activate：置顶到最前
      const activateScript = [
        `tell application id ${toAppleScriptStringLiteral(bundleId)}`,
        '  reopen',
        '  activate',
        'end tell'
      ].join('\n')
      // fire-and-forget：不等待结果，不影响通知发送
      this._executor.runAppleScript(activateScript).catch(() => {
        // 激活失败不影响通知功能
        try {
          if (this._logger && typeof this._logger.event === 'function') {
            this._logger.event(
              'notify.macos_native.activate_host.fail',
              { bundleId },
              { level: 'debug' }
            )
          }
        } catch {
          // 忽略
        }
      })
    } catch {
      // 忽略：激活是 best-effort
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
    const appRoot =
      vs && vs.env && typeof vs.env.appRoot === 'string' && vs.env.appRoot.trim()
        ? String(vs.env.appRoot).trim()
        : ''
    const appName =
      vs && vs.env && typeof vs.env.appName === 'string' && vs.env.appName.trim()
        ? String(vs.env.appName).trim()
        : ''

    // 优先从 appRoot 的 Info.plist 推导 bundleId：比 “id of application <appName>” 更稳
    // （Cursor/某些宿主的 appName 可能不是 AppleScript 可识别的应用名）
    if (appRoot) {
      const appBundlePath = findMacAppBundlePathFromAppRoot(appRoot)
      if (appBundlePath) {
        const infoPlistPath = path.join(appBundlePath, 'Contents', 'Info.plist')
        this._hostBundleIdResolvePromise = Promise.resolve()
          .then(() =>
            execFileAsync(
              '/usr/bin/plutil',
              ['-extract', 'CFBundleIdentifier', 'raw', '-o', '-', infoPlistPath],
              { timeout: 1500, maxBuffer: 64 * 1024 }
            )
          )
          .then(out => {
            const id = (out ?? '')
              .toString()
              .trim()
              .replace(/^"+|"+$/g, '')
            this._hostBundleId = this._looksLikeBundleId(id) ? id : ''
            this._hostBundleIdResolved = true
            try {
              if (this._logger && typeof this._logger.event === 'function') {
                this._logger.event(
                  'notify.macos_native.bundle_id.resolved',
                  {
                    from: 'appRoot',
                    appRoot,
                    bundleId: this._hostBundleId || '',
                    ok: !!this._hostBundleId
                  },
                  { level: 'debug' }
                )
              }
            } catch {
              // 忽略
            }
            return this._hostBundleId
          })
          .catch(e => {
            this._hostBundleId = ''
            this._hostBundleIdResolved = true
            try {
              const msg = e && e.message ? String(e.message) : String(e)
              if (this._logger && typeof this._logger.event === 'function') {
                this._logger.event(
                  'notify.macos_native.bundle_id.fail',
                  {
                    from: 'appRoot',
                    appRoot,
                    code: e && e.code ? String(e.code) : 'unknown',
                    msg: sanitizeForLog(msg)
                  },
                  { level: 'debug' }
                )
              }
            } catch {
              // 忽略
            }
            return ''
          })
          .finally(() => {
            this._hostBundleIdResolvePromise = null
          })
        return this._hostBundleIdResolvePromise
      }
    }

    if (!appName || !this._executor || typeof this._executor.runAppleScript !== 'function') {
      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'notify.macos_native.bundle_id.skipped',
            {
              hasAppName: !!appName,
              hasExecutor: !!(this._executor && typeof this._executor.runAppleScript === 'function')
            },
            { level: 'debug' }
          )
        }
      } catch {
        // 忽略
      }
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
        try {
          if (this._logger && typeof this._logger.event === 'function') {
            this._logger.event(
              'notify.macos_native.bundle_id.resolved',
              { appName, bundleId: this._hostBundleId || '', ok: !!this._hostBundleId },
              { level: 'debug' }
            )
          }
        } catch {
          // 忽略
        }
        return this._hostBundleId
      })
      .catch(e => {
        this._hostBundleId = ''
        this._hostBundleIdResolved = true
        try {
          const info = this._extractAppleScriptError(e)
          if (this._logger && typeof this._logger.event === 'function') {
            this._logger.event(
              'notify.macos_native.bundle_id.fail',
              {
                from: 'applescript',
                appName,
                code: info.code,
                msg: sanitizeForLog(info.message),
                stderr: info.stderrPreview
              },
              { level: 'debug' }
            )
          }
        } catch {
          // 忽略
        }
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
    const diagnosticMode = !!(md && (md.diagnostic || md.diagnostics || md.debug))
    // 测试/排查专用：允许调用方显式跳过 bundleId 注入（避免某些宿主/系统下首包卡住）
    const skipBundleInjection = !!(md && (md.skipBundleInjection || md.fastTest || md.fast))

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

    // 增加少量 delay：在部分系统/宿主下有助于稳定交付通知（不会引入额外权限）
    const script = `display notification ${toAppleScriptStringLiteral(message)} with title ${toAppleScriptStringLiteral(title)} sound name "Glass"\ndelay 0.05`
    // 是否在通知发送成功后尝试激活宿主 IDE 窗口（使点击通知可跳转到对应窗口）
    const shouldActivateHost = !skipBundleInjection && !!(md && md.activateOnClick !== false)
    const diagBase = {
      at: Date.now(),
      isTest,
      diagnosticMode,
      titleLen: title.length,
      messageLen: message.length
    }
    try {
      // 尝试将通知“归属”到宿主应用（VS Code / Cursor），以改善通知点击行为（避免打开脚本编辑器）
      // 说明：AppleScript 本身不支持通知点击回调；这里的目标仅是让点击激活宿主应用或至少不再打开脚本编辑器。
      // 通过为 osascript 进程注入 __CFBundleIdentifier，可能让系统把通知归属到指定 bundle id。
      let bundleId = ''
      let runOptions = undefined
      let usedFallbackWithoutBundle = false
      try {
        if (!skipBundleInjection) {
          bundleId = await this._resolveHostBundleId()
          const now = Date.now()
          const disabledUntil =
            typeof this._bundleInjectionDisabledUntilMs === 'number' &&
            Number.isFinite(this._bundleInjectionDisabledUntilMs)
              ? this._bundleInjectionDisabledUntilMs
              : 0
          if (bundleId && now >= disabledUntil) {
            runOptions = { env: { __CFBundleIdentifier: bundleId } }
          }
        }
      } catch {
        bundleId = ''
        runOptions = undefined
      }
      const injectedEnvKeys =
        runOptions && runOptions.env && runOptions.env.__CFBundleIdentifier
          ? ['__CFBundleIdentifier']
          : []
      const injectionAttempted = injectedEnvKeys.length > 0

      // 诊断信息：每次发送前清空（仅保留最后一次失败）
      this._lastDiagnostic = null

      // 优先尝试注入 bundleId；若该路径失败，则回退为“不注入直接执行”
      try {
        await this._executor.runAppleScript(script, runOptions)
      } catch (e) {
        const first = this._extractAppleScriptError(e)
        if (injectionAttempted) {
          // 注入失败：短时间内禁用注入，避免每次通知都先卡一轮 timeout
          try {
            this._bundleInjectionDisabledUntilMs = Date.now() + 10 * 60 * 1000
          } catch {
            // 忽略
          }
          try {
            if (this._logger && typeof this._logger.event === 'function') {
              this._logger.event(
                'notify.macos_native.retry_without_bundle',
                {
                  bundleId,
                  code: first.code,
                  msg: sanitizeForLog(first.message),
                  stderr: first.stderrPreview
                },
                { level: 'debug' }
              )
            }
          } catch {
            // 忽略
          }

          try {
            await this._executor.runAppleScript(script)
            usedFallbackWithoutBundle = true
            this._lastDiagnostic = {
              ...diagBase,
              ok: true,
              code: 'OK',
              bundleId,
              injectedEnvKeys: first.injectedEnvKeys,
              usedFallbackWithoutBundle: true,
              primary: first,
              fallback: { ok: true }
            }
            return true
          } catch (e2) {
            const fallback = this._extractAppleScriptError(e2)
            const err = new Error(fallback.message || first.message || 'AppleScript 执行失败')
            err.code = fallback.code || first.code || 'APPLE_SCRIPT_FAILED'
            err.primary = first
            err.fallback = fallback
            throw err
          }
        }
        throw e
      }
      // 通知发送成功后，尝试 fire-and-forget 激活宿主 IDE（不阻塞返回）
      if (shouldActivateHost && bundleId) {
        this._fireActivateHost(bundleId)
      }
      this._lastDiagnostic = {
        ...diagBase,
        ok: true,
        code: 'OK',
        bundleId,
        injectedEnvKeys,
        usedFallbackWithoutBundle: !!usedFallbackWithoutBundle,
        activatedHost: !!(shouldActivateHost && bundleId),
        primary: null,
        fallback: null
      }
      return true
    } catch (e) {
      const info = this._extractAppleScriptError(e)
      const code = info.code
      const raw = info.message
      const bundleId =
        this._hostBundleIdResolved && this._hostBundleId ? String(this._hostBundleId) : ''
      this._lastDiagnostic = {
        ...diagBase,
        ok: false,
        code,
        message: raw,
        stderr: info.stderr,
        stderrPreview: info.stderrPreview,
        exitCode: info.exitCode,
        signal: info.signal,
        bundleId,
        injectedEnvKeys: info.injectedEnvKeys,
        primary: e && e.primary ? e.primary : null,
        fallback: e && e.fallback ? e.fallback : null
      }
      const msg =
        code === 'APPLE_SCRIPT_TIMEOUT'
          ? 'AppleScript 执行超时'
          : raw
            ? `AppleScript 执行失败：${raw}`
            : 'AppleScript 执行失败'
      if (
        !diagnosticMode &&
        isTest &&
        vs &&
        vs.window &&
        typeof vs.window.showErrorMessage === 'function'
      ) {
        vs.window.showErrorMessage(msg)
      }
      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'notify.macos_native.fail',
            {
              code: code || 'unknown',
              error: sanitizeForLog(raw || ''),
              stderr: info.stderrPreview,
              exitCode: info.exitCode,
              signal: info.signal,
              injectedEnvKeys: info.injectedEnvKeys
            },
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

class MacOSNativeNotificationProvider {
  constructor(options = {}) {
    this._logger = options && options.logger ? options.logger : null
    this._executor = options && options.executor ? options.executor : null
    this._vscode = options && options.vscodeApi ? options.vscodeApi : vscode
    this._appleScriptProvider = new AppleScriptNotificationProvider({
      logger: this._logger,
      executor: this._executor,
      vscodeApi: this._vscode
    })
    this._terminalNotifierBin = ''
    this._lastDiagnostic = null
  }

  getLastDiagnostic() {
    return this._lastDiagnostic
  }

  _getTerminalNotifierBin() {
    if (this._terminalNotifierBin) return this._terminalNotifierBin
    const p = resolveBundledTerminalNotifierBinPath()
    if (ensureExecutable(p)) {
      this._terminalNotifierBin = p
      return p
    }
    this._terminalNotifierBin = ''
    return ''
  }

  async send(event) {
    const vs = this._vscode
    const title = toNonEmptyString(event && event.title, 'AI Intervention Agent')
    const message = toNonEmptyString(event && event.message, '')
    if (!message) return false

    const md = event && event.metadata && typeof event.metadata === 'object' ? event.metadata : {}
    const isTest = !!(md && md.isTest)
    const diagnosticMode = !!(md && (md.diagnostic || md.diagnostics || md.debug))

    // 非测试通知：非 macOS 平台直接跳过
    if (!isTest && process.platform !== 'darwin') return false

    const diagBase = {
      at: Date.now(),
      isTest,
      diagnosticMode,
      titleLen: title.length,
      messageLen: message.length
    }

    // 仅在 macOS 尝试 terminal-notifier；其它平台直接走 AppleScriptProvider（其自身会处理 platform gate）
    const tnBin = process.platform === 'darwin' ? this._getTerminalNotifierBin() : ''
    const attempts = []

    let bundleId = ''
    if (process.platform === 'darwin') {
      try {
        bundleId =
          this._appleScriptProvider &&
          typeof this._appleScriptProvider._resolveHostBundleId === 'function'
            ? await this._appleScriptProvider._resolveHostBundleId()
            : ''
      } catch {
        bundleId = ''
      }
    }

    if (process.platform === 'darwin' && tnBin) {
      const baseArgs = ['-title', title, '-message', message, '-sound', 'default']
      if (diagnosticMode && isTest) baseArgs.push('-ignoreDnD')
      const args = [...baseArgs]
      // 点击激活宿主：
      // - `-activate`：处理窗口非最小化时的快速切换（由 terminal-notifier 原生处理，更快）
      // - `-execute`：处理窗口最小化到 Dock 的情况（通过 osascript reopen+activate 恢复窗口）
      // 两者同时指定时互相补充，确保无论窗口状态如何都能正确激活
      if (bundleId) {
        args.push('-activate', bundleId)
        // 构造点击时执行的 osascript 命令：reopen 恢复最小化窗口 + activate 置顶
        const escapedBundleId = bundleId.replace(/"/g, '\\"')
        const executeCmd = `osascript -e "tell application id \\"${escapedBundleId}\\"" -e "reopen" -e "activate" -e "end tell"`
        args.push('-execute', executeCmd)
      }
      try {
        const r = await execFileAsyncWithOutput(tnBin, args, {
          timeout: 2500,
          maxBuffer: 256 * 1024
        })
        this._lastDiagnostic = {
          ...diagBase,
          backend: 'terminal-notifier',
          ok: true,
          code: 'OK',
          mode: bundleId ? 'activate+execute' : 'plain',
          bin: tnBin,
          bundleId,
          durationMs: r.durationMs
        }
        return true
      } catch (e) {
        const msg = e && e.message ? String(e.message) : String(e)
        attempts.push({
          backend: 'terminal-notifier',
          mode: bundleId ? 'activate+execute' : 'plain',
          ok: false,
          bin: tnBin,
          bundleId,
          code: e && e.code ? String(e.code) : 'unknown',
          message: msg,
          stderrPreview:
            e && e.details && e.details.stderrPreview ? String(e.details.stderrPreview) : ''
        })
      }
    }

    // 最后回退：AppleScript（保留原有诊断）
    try {
      const ok = await this._appleScriptProvider.send(event)
      const appleDiag =
        this._appleScriptProvider &&
        typeof this._appleScriptProvider.getLastDiagnostic === 'function'
          ? this._appleScriptProvider.getLastDiagnostic()
          : null
      this._lastDiagnostic = {
        ...diagBase,
        backend: 'applescript',
        ok: !!ok,
        terminalNotifierAttempts: attempts,
        appleScript: appleDiag
      }

      // 把 AppleScript 的关键字段抬平，便于设置面板展示（保持兼容）
      if (appleDiag && typeof appleDiag === 'object') {
        if (appleDiag.code) this._lastDiagnostic.code = String(appleDiag.code)
        if (appleDiag.bundleId) this._lastDiagnostic.bundleId = String(appleDiag.bundleId)
        if (appleDiag.stderrPreview)
          this._lastDiagnostic.stderrPreview = String(appleDiag.stderrPreview)
        if (appleDiag.exitCode === 0 || typeof appleDiag.exitCode === 'number') {
          this._lastDiagnostic.exitCode = appleDiag.exitCode
        }
        if (appleDiag.injectedEnvKeys)
          this._lastDiagnostic.injectedEnvKeys = appleDiag.injectedEnvKeys
      }
      return !!ok
    } catch (e) {
      const msg = e && e.message ? String(e.message) : String(e)
      this._lastDiagnostic = {
        ...diagBase,
        backend: 'applescript',
        ok: false,
        error: msg,
        terminalNotifierAttempts: attempts
      }
      if (
        diagnosticMode &&
        isTest &&
        vs &&
        vs.window &&
        typeof vs.window.showErrorMessage === 'function'
      ) {
        vs.window.showErrorMessage('macOS 原生通知发送失败：' + msg)
      }
      return false
    }
  }
}

module.exports = {
  VSCodeApiNotificationProvider,
  AppleScriptNotificationProvider,
  MacOSNativeNotificationProvider
}
