import { execFile as nodeExecFile } from 'child_process'
import type { Logger } from './logger'

const DEFAULT_TIMEOUT_MS = 8000
const DEFAULT_MAX_BUFFER_BYTES = 1024 * 1024
const DEFAULT_OSASCRIPT_PATH = '/usr/bin/osascript'

export interface AppleScriptError extends Error {
  code?: string
  cause?: unknown
  details?: Record<string, unknown>
}

interface AppleScriptExecutorOptions {
  logger?: Logger | null
  execImpl?: typeof nodeExecFile
  timeoutMs?: number
  maxBufferBytes?: number
  platform?: string
  osascriptPath?: string
}

interface RunOptions {
  env?: Record<string, string | undefined>
}

export function isMacOS(platform: string = process.platform): boolean {
  return platform === 'darwin'
}

export function sanitizeForLog(input: unknown, maxLen = 160): string {
  const text = ((input ?? '') as string).toString()
  const singleLine = text
    .replace(/[\r\n\t]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!singleLine) return ''
  if (singleLine.length <= maxLen) return singleLine
  return `${singleLine.slice(0, maxLen)}…`
}

/**
 * 将任意输入安全转换为 AppleScript 字符串字面量（带双引号）。
 * 适用场景：需要把用户输入拼进 AppleScript 脚本时，避免破坏语法结构。
 */
export function toAppleScriptStringLiteral(value: unknown): string {
  const raw = ((value ?? '') as string).toString()
  const escaped = raw
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"')
    .replace(/\r/g, '\\r')
    .replace(/\n/g, '\\n')
    .replace(/\t/g, '\\t')
  return `"${escaped}"`
}

function makeError(
  message: string,
  code: string,
  extra?: Partial<AppleScriptError>
): AppleScriptError {
  const err: AppleScriptError = new Error(message)
  err.code = code
  if (extra) Object.assign(err, extra)
  return err
}

export class AppleScriptExecutor {
  private _logger: Logger | null
  private _execFile: typeof nodeExecFile
  private _timeoutMs: number
  private _maxBufferBytes: number
  private _platform: string
  private _osascriptPath: string

  constructor(opts: AppleScriptExecutorOptions = {}) {
    this._logger = opts.logger || null
    this._execFile = typeof opts.execImpl === 'function' ? opts.execImpl : nodeExecFile
    this._timeoutMs = Number.isFinite(Number(opts.timeoutMs))
      ? Number(opts.timeoutMs)
      : DEFAULT_TIMEOUT_MS
    this._maxBufferBytes = Number.isFinite(Number(opts.maxBufferBytes))
      ? Number(opts.maxBufferBytes)
      : DEFAULT_MAX_BUFFER_BYTES
    this._platform = typeof opts.platform === 'string' ? opts.platform : process.platform
    this._osascriptPath = opts.osascriptPath ? String(opts.osascriptPath) : DEFAULT_OSASCRIPT_PATH
  }

  static isSupportedPlatform(platform = process.platform): boolean {
    return isMacOS(platform)
  }

  runAppleScript(script: string, runOptions: RunOptions = {}): Promise<string> {
    const platform = this._platform || process.platform
    if (!isMacOS(platform)) {
      return Promise.reject(makeError('Platform not supported', 'PLATFORM_NOT_SUPPORTED'))
    }

    const body = ((script ?? '') as string).toString()
    if (!body.trim()) {
      return Promise.reject(makeError('AppleScript cannot be empty', 'APPLE_SCRIPT_EMPTY'))
    }

    const timeoutMs = this._timeoutMs
    const maxBufferBytes = this._maxBufferBytes
    const osascriptPath = this._osascriptPath
    const osascriptArgs = ['-']
    const envExtra =
      runOptions && runOptions.env && typeof runOptions.env === 'object' ? runOptions.env : null
    const injectedEnvKeys = envExtra
      ? Object.keys(envExtra)
          .filter(Boolean)
          .map(k => String(k))
          .sort()
      : []
    const env = envExtra ? { ...process.env, ...envExtra } : process.env
    const startedAt = Date.now()

    try {
      if (this._logger && typeof this._logger.event === 'function') {
        this._logger.event(
          'applescript.run.start',
          { platform, timeoutMs, maxBufferBytes, scriptLen: body.length, injectedEnvKeys },
          { level: 'debug' }
        )
      } else if (this._logger && typeof this._logger.debug === 'function') {
        this._logger.debug(
          `runAppleScript:start platform=${platform} timeoutMs=${timeoutMs} scriptLen=${body.length}`
        )
      }
    } catch {
      // 忽略
    }

    return new Promise<string>((resolve, reject) => {
      let child: ReturnType<typeof nodeExecFile> | undefined
      try {
        child = this._execFile(
          osascriptPath,
          osascriptArgs,
          {
            timeout: timeoutMs,
            maxBuffer: maxBufferBytes,
            encoding: 'utf8',
            windowsHide: true,
            env
          },
          (error, stdout, stderr) => {
            const errText = ((stderr ?? '') as string).toString().trim()
            const outText = ((stdout ?? '') as string).toString()
            const durationMs = Date.now() - startedAt

            if (error) {
              const errAny = error as NodeJS.ErrnoException & { killed?: boolean; signal?: string }
              const exitCode = typeof errAny.code === 'number' ? errAny.code : null
              const signal = errAny.signal ? String(errAny.signal) : ''
              const isTimeout =
                errAny.code === 'ETIMEDOUT' ||
                !!errAny.killed ||
                signal === 'SIGTERM' ||
                signal === 'SIGKILL'
              const msg =
                errText || (error.message ? String(error.message) : 'AppleScript execution failed')

              const err = makeError(
                msg,
                isTimeout ? 'APPLE_SCRIPT_TIMEOUT' : 'APPLE_SCRIPT_FAILED',
                {
                  cause: error,
                  details: {
                    osascriptPath,
                    osascriptArgs,
                    timeoutMs,
                    maxBufferBytes,
                    injectedEnvKeys,
                    durationMs,
                    exitCode,
                    signal,
                    killed: !!errAny.killed,
                    stderr: errText,
                    stderrLen: errText.length,
                    stdoutPreview: sanitizeForLog(outText, 240),
                    stdoutLen: outText.length
                  }
                }
              )

              try {
                if (this._logger && typeof this._logger.event === 'function') {
                  this._logger.event(
                    'applescript.run.fail',
                    {
                      code: err.code,
                      durationMs,
                      msg: sanitizeForLog(msg),
                      stderrLen: errText.length,
                      exitCode,
                      signal,
                      injectedEnvKeys
                    },
                    { level: 'warn' }
                  )
                }
              } catch {
                /* 忽略 */
              }

              reject(err)
              return
            }

            if (errText) {
              const err = makeError(errText, 'APPLE_SCRIPT_STDERR', {
                details: {
                  osascriptPath,
                  osascriptArgs,
                  timeoutMs,
                  maxBufferBytes,
                  injectedEnvKeys,
                  durationMs,
                  stderr: errText,
                  stderrLen: errText.length,
                  stdoutPreview: sanitizeForLog(outText, 240),
                  stdoutLen: outText.length
                }
              })

              try {
                if (this._logger && typeof this._logger.event === 'function') {
                  this._logger.event(
                    'applescript.run.stderr',
                    { code: err.code, durationMs, msg: sanitizeForLog(errText), injectedEnvKeys },
                    { level: 'warn' }
                  )
                }
              } catch {
                /* 忽略 */
              }

              reject(err)
              return
            }

            try {
              if (this._logger && typeof this._logger.event === 'function') {
                this._logger.event(
                  'applescript.run.ok',
                  { durationMs, stdoutLen: outText.length, scriptLen: body.length },
                  { level: 'debug' }
                )
              }
            } catch {
              /* 忽略 */
            }

            resolve(outText)
          }
        )
      } catch (e: unknown) {
        const baseErr = e instanceof Error ? e : new Error(String(e))
        const durationMs = Date.now() - startedAt
        const err = makeError(baseErr.message, 'APPLE_SCRIPT_SPAWN_FAILED', {
          details: {
            osascriptPath,
            osascriptArgs,
            timeoutMs,
            maxBufferBytes,
            injectedEnvKeys,
            durationMs
          }
        })

        try {
          if (this._logger && typeof this._logger.event === 'function') {
            this._logger.event(
              'applescript.run.spawn_failed',
              { code: err.code, durationMs, msg: sanitizeForLog(err.message), injectedEnvKeys },
              { level: 'error' }
            )
          }
        } catch {
          /* 忽略 */
        }

        reject(err)
        return
      }

      try {
        if (child && child.stdin) {
          child.stdin.on('error', () => {
            // 忽略：stdin 已关闭时可能触发 EPIPE 等错误
          })
          child.stdin.end(body, 'utf8')
        }
      } catch {
        // 忽略：失败信息会在回调中返回
      }
    })
  }
}

module.exports = {
  AppleScriptExecutor,
  isMacOS,
  sanitizeForLog,
  toAppleScriptStringLiteral
}
