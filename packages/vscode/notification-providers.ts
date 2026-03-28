import * as vscode from 'vscode'
import * as fs from 'fs'
import * as path from 'path'
import { execFile, execFileSync } from 'child_process'
import { toAppleScriptStringLiteral, sanitizeForLog } from './applescript-executor'
import type { Logger } from './logger'

// ── 类型定义 ──

interface ExecError extends Error {
  code?: string | number | null
  cause?: unknown
  signal?: string
  details?: Record<string, unknown>
}

interface ExecResult {
  stdout: string
  stderr: string
  durationMs: number
}

interface StablePaths {
  dir: string
  app: string
  bin: string
}

interface StableResult {
  bin: string
  installed: boolean
  error: string
}

interface VsCodeApi {
  window?: {
    showErrorMessage?: (msg: string, ...items: string[]) => Thenable<string | undefined>
    showWarningMessage?: (msg: string, ...items: string[]) => Thenable<string | undefined>
    showInformationMessage?: (msg: string, ...items: string[]) => Thenable<string | undefined>
    setStatusBarMessage?: (text: string, hideAfterTimeout: number) => vscode.Disposable
  }
  env?: {
    appRoot?: string
    appName?: string
  }
}

interface AppleScriptErrorInfo {
  code: string
  message: string
  exitCode: number | null
  signal: string
  durationMs: number | null
  stderr: string
  stderrPreview: string
  injectedEnvKeys: string[]
}

interface DiagnosticBase {
  at: number
  isTest: boolean
  diagnosticMode: boolean
  titleLen: number
  messageLen: number
}

interface NotificationEvent {
  title?: string
  message?: string
  metadata?: Record<string, unknown>
}

interface RunOptions {
  env?: Record<string, string>
}

interface AppleScriptExecutorLike {
  runAppleScript: (script: string, options?: RunOptions) => Promise<string>
}

interface ProviderOptions {
  logger?: Logger | null
  executor?: AppleScriptExecutorLike | null
  vscodeApi?: VsCodeApi
}

// ── 工具函数 ──

function toNonEmptyString(value: unknown, fallback = ''): string {
  const s = value == null ? '' : String(value)
  const t = s.trim()
  return t ? t : fallback
}

function makeExecError(message: string, code: string, extra?: Partial<ExecError>): ExecError {
  const err: ExecError = new Error(message)
  err.code = code
  if (extra) Object.assign(err, extra)
  return err
}

function execFileAsyncWithOutput(
  file: string,
  args: string[],
  options?: Record<string, unknown>
): Promise<ExecResult> {
  return new Promise((resolve, reject) => {
    const startedAt = Date.now()
    try {
      execFile(
        file,
        Array.isArray(args) ? args : [],
        Object.assign({ encoding: 'utf8', windowsHide: true }, options || {}) as { encoding: 'utf8' },
        (error, stdout, stderr) => {
          const durationMs = Date.now() - startedAt
          const outText = (stdout ?? '').toString()
          const errText = (stderr ?? '').toString()
          if (error) {
            const exitCode =
              typeof error.code === 'number' && Number.isFinite(error.code) ? error.code : null
            const signal = error && (error as unknown as Record<string, unknown>).signal ? String((error as unknown as Record<string, unknown>).signal) : ''
            const msg =
              errText.trim() || (error && error.message ? String(error.message) : 'execFile failed')
            reject(makeExecError(msg, 'EXEC_FAILED', {
              cause: error,
              details: {
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
            }))
            return
          }
          resolve({ stdout: outText, stderr: errText, durationMs })
        }
      )
    } catch (e: unknown) {
      const err = e instanceof Error ? e : new Error(String(e))
      reject(makeExecError(err.message, 'EXEC_SPAWN_FAILED', {
        details: { file: String(file || ''), args: Array.isArray(args) ? args.map(String) : [] }
      }))
    }
  })
}

function execFileAsync(
  file: string,
  args: string[],
  options?: Record<string, unknown>
): Promise<string> {
  return new Promise((resolve, reject) => {
    try {
      execFile(
        file,
        Array.isArray(args) ? args : [],
        Object.assign({ encoding: 'utf8', windowsHide: true }, options || {}) as { encoding: 'utf8' },
        (error, stdout, stderr) => {
          if (error) {
            const errText = (stderr ?? '').toString().trim()
            const msg =
              errText || (error && error.message ? String(error.message) : 'execFile failed')
            reject(makeExecError(msg, 'EXEC_FAILED', {
              cause: error,
              details: {
                file: String(file || ''),
                args: Array.isArray(args) ? args.map(String) : []
              }
            }))
            return
          }
          resolve((stdout ?? '').toString())
        }
      )
    } catch (e: unknown) {
      const err = e instanceof Error ? e : new Error(String(e))
      reject(makeExecError(err.message, 'EXEC_SPAWN_FAILED'))
    }
  })
}

function findMacAppBundlePathFromAppRoot(appRoot: string): string {
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

function resolveBundledTerminalNotifierBinPath(): string {
  try {
    return path.join(
      __dirname, '..',
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

function ensureExecutable(filePath: string): boolean {
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

// ── terminal-notifier 稳定路径管理 ──
// macOS 按「应用路径 + bundle ID」来识别通知源。如果扩展升级/开发目录变化导致
// terminal-notifier.app 路径变化，macOS 会注册为新的通知源，产生重复条目。
// 将 terminal-notifier.app 安装到固定的 Application Support 路径来规避此问题。

function getStableAppSupportDir(): string {
  const home = process.env.HOME || ''
  if (!home) return ''
  return path.join(home, 'Library', 'Application Support', 'ai-intervention-agent')
}

function getStableTerminalNotifierPaths(): StablePaths {
  const dir = getStableAppSupportDir()
  if (!dir) return { dir: '', app: '', bin: '' }
  const app = path.join(dir, 'terminal-notifier.app')
  const bin = path.join(app, 'Contents', 'MacOS', 'terminal-notifier')
  return { dir, app, bin }
}

function _migrateLegacyAppSupportDir(newDir: string): void {
  const home = process.env.HOME || ''
  if (!home) return
  const legacyDir = path.join(home, 'Library', 'Application Support', 'AI Intervention Agent')
  try {
    if (legacyDir === newDir) return
    if (!fs.existsSync(legacyDir)) return
    const legacyApp = path.join(legacyDir, 'terminal-notifier.app')
    if (!fs.existsSync(legacyApp)) return
    if (!fs.existsSync(newDir)) fs.mkdirSync(newDir, { recursive: true })
    const destApp = path.join(newDir, 'terminal-notifier.app')
    if (!fs.existsSync(destApp)) {
      fs.cpSync(legacyApp, destApp, { recursive: true })
    }
    fs.rmSync(legacyDir, { recursive: true, force: true })
  } catch {
    // 迁移失败不阻塞正常流程
  }
}

function readBundleVersionFromXmlPlist(infoPlistPath: string): string {
  try {
    if (!infoPlistPath || !fs.existsSync(infoPlistPath)) return ''
    const content = fs.readFileSync(infoPlistPath, 'utf8')
    const match = content.match(/<key>CFBundleVersion<\/key>\s*<string>([^<]*)<\/string>/)
    return match ? match[1].trim() : ''
  } catch {
    return ''
  }
}

/**
 * 将 vendor 目录中的 terminal-notifier.app 安装到 ~/Library/Application Support/ai-intervention-agent/
 * 确保 macOS 始终从同一路径加载，避免重复的通知中心注册条目。
 */
function ensureStableTerminalNotifier(): StableResult {
  const fail = (error: string): StableResult => ({ bin: '', installed: false, error: error || '' })

  if (process.platform !== 'darwin') return fail('non-darwin')

  const stable = getStableTerminalNotifierPaths()
  if (!stable.dir) return fail('no-home')

  _migrateLegacyAppSupportDir(stable.dir)

  const srcAppPath = path.join(
    __dirname, '..', 'vendor', 'terminal-notifier', 'terminal-notifier.app'
  )
  if (!fs.existsSync(srcAppPath)) return fail('src-not-found')

  try {
    const srcInfoPlist = path.join(srcAppPath, 'Contents', 'Info.plist')
    const destInfoPlist = path.join(stable.app, 'Contents', 'Info.plist')

    const srcVersion = readBundleVersionFromXmlPlist(srcInfoPlist)
    const destVersion = readBundleVersionFromXmlPlist(destInfoPlist)

    if (destVersion && srcVersion && destVersion === srcVersion && fs.existsSync(stable.bin)) {
      ensureExecutable(stable.bin)
      return { bin: stable.bin, installed: false, error: '' }
    }

    fs.mkdirSync(stable.dir, { recursive: true })

    if (fs.existsSync(stable.app)) {
      execFileSync('/bin/rm', ['-rf', stable.app], { timeout: 5000 })
    }
    execFileSync('/bin/cp', ['-R', srcAppPath, stable.app], { timeout: 10000 })

    if (!ensureExecutable(stable.bin)) return fail('chmod-failed')
    if (!fs.existsSync(stable.bin)) return fail('bin-missing-after-copy')

    return { bin: stable.bin, installed: true, error: '' }
  } catch (e: unknown) {
    if (fs.existsSync(stable.bin)) {
      ensureExecutable(stable.bin)
      return { bin: stable.bin, installed: false, error: 'copy-failed-using-existing' }
    }
    return fail(e instanceof Error ? e.message : 'unknown')
  }
}

// ── Provider 类 ──

export class VSCodeApiNotificationProvider {
  private _logger: Logger | null
  private _vscode: VsCodeApi

  constructor(options: ProviderOptions = {}) {
    this._logger = options && options.logger ? options.logger : null
    this._vscode = options && options.vscodeApi ? options.vscodeApi : vscode
  }

  async send(event: NotificationEvent): Promise<boolean> {
    const vs = this._vscode
    if (!vs || !vs.window) return false

    const title = toNonEmptyString(event && event.title, 'AI Intervention Agent')
    const message = toNonEmptyString(event && event.message, '')
    if (!message) return false

    const md = event && event.metadata && typeof event.metadata === 'object' ? event.metadata : {} as Record<string, unknown>
    const presentation = toNonEmptyString((md as Record<string, unknown>).presentation, 'statusBar')
    const severity = toNonEmptyString((md as Record<string, unknown>).severity, 'info')
    const timeoutMsRaw = (md as Record<string, unknown>).timeoutMs
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

    const icon = severity === 'error' ? '$(error)' : severity === 'warn' ? '$(warning)' : '$(info)'
    if (typeof vs.window.setStatusBarMessage === 'function') {
      vs.window.setStatusBarMessage(`${icon} ${message}`, timeoutMs)
      return true
    }
    return false
  }
}

export class AppleScriptNotificationProvider {
  private _logger: Logger | null
  private _executor: AppleScriptExecutorLike | null
  private _vscode: VsCodeApi
  private _hostBundleId: string
  private _hostBundleIdResolved: boolean
  private _hostBundleIdResolvePromise: Promise<string> | null
  private _lastDiagnostic: Record<string, unknown> | null
  private _bundleInjectionDisabledUntilMs: number
  private _hostAppBundlePath: string
  private _hostAppBundlePathResolved: boolean

  constructor(options: ProviderOptions = {}) {
    this._logger = options && options.logger ? options.logger : null
    this._executor = options && options.executor ? options.executor : null
    this._vscode = options && options.vscodeApi ? options.vscodeApi : vscode
    this._hostBundleId = ''
    this._hostBundleIdResolved = false
    this._hostBundleIdResolvePromise = null
    this._lastDiagnostic = null
    this._bundleInjectionDisabledUntilMs = 0
    this._hostAppBundlePath = ''
    this._hostAppBundlePathResolved = false
  }

  getLastDiagnostic(): Record<string, unknown> | null {
    return this._lastDiagnostic
  }

  _extractAppleScriptError(e: unknown): AppleScriptErrorInfo {
    const err = e as ExecError | null
    const code = err && err.code ? String(err.code) : 'unknown'
    const message = err && err.message ? String(err.message) : String(e)
    const details = err && err.details && typeof err.details === 'object' ? err.details : {} as Record<string, unknown>
    const exitCode =
      details && typeof details.exitCode === 'number' && Number.isFinite(details.exitCode)
        ? details.exitCode as number
        : null
    const signal = details && details.signal ? String(details.signal) : ''
    const stderr = details && details.stderr ? String(details.stderr) : ''
    const durationMs =
      details && typeof details.durationMs === 'number' && Number.isFinite(details.durationMs)
        ? details.durationMs as number
        : null
    const injectedEnvKeys =
      details && Array.isArray(details.injectedEnvKeys) ? (details.injectedEnvKeys as unknown[]).map(String) : []
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

  _looksLikeBundleId(value: unknown): boolean {
    try {
      const s = (value ?? '').toString().trim()
      if (!s) return false
      return /^[A-Za-z0-9.-]+$/.test(s)
    } catch {
      return false
    }
  }

  /**
   * 解析宿主 .app 路径（如 /Applications/Visual Studio Code.app）
   * 用于 AppleScript `activate` 激活窗口
   */
  _resolveHostAppBundlePath(): string {
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
   * best-effort 操作，不阻塞也不影响通知发送结果。
   */
  _fireActivateHost(bundleId: string): void {
    if (!bundleId || !this._executor || typeof this._executor.runAppleScript !== 'function') return
    try {
      const activateScript = [
        `tell application id ${toAppleScriptStringLiteral(bundleId)}`,
        '  reopen',
        '  activate',
        'end tell'
      ].join('\n')
      this._executor.runAppleScript(activateScript).catch(() => {
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

  async _resolveHostBundleId(): Promise<string> {
    if (this._hostBundleIdResolved) return this._hostBundleId
    if (this._hostBundleIdResolvePromise) return this._hostBundleIdResolvePromise

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
          .catch((e: unknown) => {
            this._hostBundleId = ''
            this._hostBundleIdResolved = true
            try {
              const msg = e instanceof Error ? e.message : String(e)
              if (this._logger && typeof this._logger.event === 'function') {
                this._logger.event(
                  'notify.macos_native.bundle_id.fail',
                  {
                    from: 'appRoot',
                    appRoot,
                    code: (e as ExecError)?.code ? String((e as ExecError).code) : 'unknown',
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
      .then(() => this._executor!.runAppleScript(script))
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
      .catch((e: unknown) => {
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

  async send(event: NotificationEvent): Promise<boolean> {
    const vs = this._vscode
    const title = toNonEmptyString(event && event.title, 'AI Intervention Agent')
    const message = toNonEmptyString(event && event.message, '')
    if (!message) return false

    const md = event && event.metadata && typeof event.metadata === 'object' ? event.metadata : {} as Record<string, unknown>
    const isTest = !!(md && (md as Record<string, unknown>).isTest)
    const diagnosticMode = !!((md as Record<string, unknown>).diagnostic || (md as Record<string, unknown>).diagnostics || (md as Record<string, unknown>).debug)
    const skipBundleInjection = !!((md as Record<string, unknown>).skipBundleInjection || (md as Record<string, unknown>).fastTest || (md as Record<string, unknown>).fast)

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

    const script = `display notification ${toAppleScriptStringLiteral(message)} with title ${toAppleScriptStringLiteral(title)} sound name "Glass"\ndelay 0.05`
    const shouldActivateHost = !skipBundleInjection && !!((md as Record<string, unknown>).activateOnClick !== false)
    const diagBase: DiagnosticBase = {
      at: Date.now(),
      isTest,
      diagnosticMode,
      titleLen: title.length,
      messageLen: message.length
    }
    try {
      let bundleId = ''
      let runOptions: RunOptions | undefined = undefined
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

      this._lastDiagnostic = null

      try {
        await this._executor.runAppleScript(script, runOptions)
      } catch (e: unknown) {
        const first = this._extractAppleScriptError(e)
        if (injectionAttempted) {
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
          } catch (e2: unknown) {
            const fallback = this._extractAppleScriptError(e2)
            const errObj = makeExecError(
              fallback.message || first.message || 'AppleScript 执行失败',
              fallback.code || first.code || 'APPLE_SCRIPT_FAILED'
            );
            (errObj as unknown as Record<string, unknown>).primary = first;
            (errObj as unknown as Record<string, unknown>).fallback = fallback
            throw errObj
          }
        }
        throw e
      }
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
    } catch (e: unknown) {
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
        primary: (e as Record<string, unknown>)?.primary ?? null,
        fallback: (e as Record<string, unknown>)?.fallback ?? null
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

export class MacOSNativeNotificationProvider {
  private _logger: Logger | null
  private _executor: AppleScriptExecutorLike | null
  private _vscode: VsCodeApi
  private _appleScriptProvider: AppleScriptNotificationProvider
  private _terminalNotifierBin: string
  private _terminalNotifierBinPromise: Promise<string> | null
  private _lastDiagnostic: Record<string, unknown> | null

  constructor(options: ProviderOptions = {}) {
    this._logger = options && options.logger ? options.logger : null
    this._executor = options && options.executor ? options.executor : null
    this._vscode = options && options.vscodeApi ? options.vscodeApi : vscode
    this._appleScriptProvider = new AppleScriptNotificationProvider({
      logger: this._logger,
      executor: this._executor,
      vscodeApi: this._vscode
    })
    this._terminalNotifierBin = ''
    this._terminalNotifierBinPromise = null
    this._lastDiagnostic = null
    // 在 macOS 上延迟预加载 terminal-notifier，避免阻塞扩展激活
    if (process.platform === 'darwin') {
      this._warmupTerminalNotifier()
    }
  }

  private _warmupTerminalNotifier(): void {
    this._terminalNotifierBinPromise = new Promise<string>(resolve => {
      setTimeout(() => {
        resolve(this._resolveTerminalNotifierBinSync())
      }, 0)
    })
  }

  private _resolveTerminalNotifierBinSync(): string {
    const stable = ensureStableTerminalNotifier()
    if (stable.bin) {
      this._terminalNotifierBin = stable.bin
      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'notify.terminal_notifier.resolved',
            { from: 'stable', path: stable.bin, installed: stable.installed, error: stable.error || '' },
            { level: 'debug' }
          )
        }
      } catch { /* noop */ }
      return stable.bin
    }
    const p = resolveBundledTerminalNotifierBinPath()
    if (ensureExecutable(p)) {
      this._terminalNotifierBin = p
      try {
        if (this._logger && typeof this._logger.event === 'function') {
          this._logger.event(
            'notify.terminal_notifier.resolved',
            { from: 'vendor-fallback', path: p, stableError: stable.error || '' },
            { level: 'debug' }
          )
        }
      } catch { /* noop */ }
      return p
    }
    this._terminalNotifierBin = ''
    return ''
  }

  getLastDiagnostic(): Record<string, unknown> | null {
    return this._lastDiagnostic
  }

  async _getTerminalNotifierBin(): Promise<string> {
    if (this._terminalNotifierBin) return this._terminalNotifierBin
    if (this._terminalNotifierBinPromise) {
      return this._terminalNotifierBinPromise
    }
    return this._resolveTerminalNotifierBinSync()
  }

  async send(event: NotificationEvent): Promise<boolean> {
    const vs = this._vscode
    const title = toNonEmptyString(event && event.title, 'AI Intervention Agent')
    const message = toNonEmptyString(event && event.message, '')
    if (!message) return false

    const md = event && event.metadata && typeof event.metadata === 'object' ? event.metadata : {} as Record<string, unknown>
    const isTest = !!(md && (md as Record<string, unknown>).isTest)
    const diagnosticMode = !!((md as Record<string, unknown>).diagnostic || (md as Record<string, unknown>).diagnostics || (md as Record<string, unknown>).debug)

    if (!isTest && process.platform !== 'darwin') return false

    const diagBase: DiagnosticBase = {
      at: Date.now(),
      isTest,
      diagnosticMode,
      titleLen: title.length,
      messageLen: message.length
    }

    const tnBin = process.platform === 'darwin' ? await this._getTerminalNotifierBin() : ''
    const attempts: Record<string, unknown>[] = []

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
      if (bundleId) {
        args.push('-activate', bundleId)
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
      } catch (e: unknown) {
        const err = e as ExecError
        const msg = err && err.message ? String(err.message) : String(e)
        this._terminalNotifierBin = ''
        this._terminalNotifierBinPromise = null
        const details = err && err.details && typeof err.details === 'object' ? err.details : {} as Record<string, unknown>
        attempts.push({
          backend: 'terminal-notifier',
          mode: bundleId ? 'activate+execute' : 'plain',
          ok: false,
          bin: tnBin,
          bundleId,
          code: err && err.code ? String(err.code) : 'unknown',
          message: msg,
          stderrPreview: details.stderrPreview ? String(details.stderrPreview) : ''
        })
      }
    }

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
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
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
