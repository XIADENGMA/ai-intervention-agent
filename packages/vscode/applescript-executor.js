const { exec } = require('child_process')

const DEFAULT_TIMEOUT_MS = 8000
const DEFAULT_MAX_BUFFER_BYTES = 1024 * 1024
const DEFAULT_OSASCRIPT_PATH = '/usr/bin/osascript'

function isMacOS(platform = process.platform) {
  return platform === 'darwin'
}

function sanitizeForLog(input, maxLen = 160) {
  const text = (input ?? '').toString()
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
function toAppleScriptStringLiteral(value) {
  const raw = (value ?? '').toString()
  const escaped = raw
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"')
    .replace(/\r/g, '\\r')
    .replace(/\n/g, '\\n')
    .replace(/\t/g, '\\t')
  return `"${escaped}"`
}

class AppleScriptExecutor {
  constructor(opts = {}) {
    this._logger = opts.logger || null
    this._exec = typeof opts.execImpl === 'function' ? opts.execImpl : exec
    this._timeoutMs = Number.isFinite(Number(opts.timeoutMs))
      ? Number(opts.timeoutMs)
      : DEFAULT_TIMEOUT_MS
    this._maxBufferBytes = Number.isFinite(Number(opts.maxBufferBytes))
      ? Number(opts.maxBufferBytes)
      : DEFAULT_MAX_BUFFER_BYTES
    this._platform = typeof opts.platform === 'string' ? opts.platform : process.platform
    this._osascriptPath = opts.osascriptPath ? String(opts.osascriptPath) : DEFAULT_OSASCRIPT_PATH
  }

  static isSupportedPlatform(platform = process.platform) {
    return isMacOS(platform)
  }

  /**
   * 执行 AppleScript，并返回 stdout（utf8）。
   *
   * 为降低命令注入风险：脚本内容通过 stdin 传入，不拼接到命令行参数里。
   *
   * @param {string} script AppleScript 源码
   * @param {object} [runOptions] 可选执行参数（目前仅支持 env 注入）
   * @returns {Promise<string>} stdout
   */
  runAppleScript(script, runOptions = {}) {
    const platform = this._platform || process.platform
    if (!isMacOS(platform)) {
      const err = new Error('Platform not supported')
      err.code = 'PLATFORM_NOT_SUPPORTED'
      return Promise.reject(err)
    }

    const body = (script ?? '').toString()
    if (!body.trim()) {
      const err = new Error('AppleScript 不能为空')
      err.code = 'APPLE_SCRIPT_EMPTY'
      return Promise.reject(err)
    }

    const timeoutMs = this._timeoutMs
    const maxBufferBytes = this._maxBufferBytes
    const cmd = `${this._osascriptPath} -`
    const envExtra =
      runOptions && runOptions.env && typeof runOptions.env === 'object' ? runOptions.env : null
    const env = envExtra ? { ...process.env, ...envExtra } : process.env
    const startedAt = Date.now()

    try {
      if (this._logger && typeof this._logger.event === 'function') {
        this._logger.event(
          'applescript.run.start',
          {
            platform,
            timeoutMs,
            maxBufferBytes,
            scriptLen: body.length
          },
          { level: 'debug' }
        )
      } else if (this._logger && typeof this._logger.debug === 'function') {
        this._logger.debug(
          `runAppleScript:start platform=${platform} timeoutMs=${timeoutMs} scriptLen=${body.length}`
        )
      }
    } catch {
      // 忽略：日志系统异常不应影响执行
    }

    return new Promise((resolve, reject) => {
      let child
      try {
        child = this._exec(
          cmd,
          {
            timeout: timeoutMs,
            maxBuffer: maxBufferBytes,
            encoding: 'utf8',
            windowsHide: true,
            env
          },
          (error, stdout, stderr) => {
            const errText = (stderr ?? '').toString().trim()
            const outText = (stdout ?? '').toString()
            const durationMs = Date.now() - startedAt

            if (error) {
              const isTimeout =
                !!error.killed || error.signal === 'SIGTERM' || error.signal === 'SIGKILL'
              const msg =
                errText || (error && error.message ? String(error.message) : 'AppleScript 执行失败')
              const err = new Error(msg)
              err.code = isTimeout ? 'APPLE_SCRIPT_TIMEOUT' : 'APPLE_SCRIPT_FAILED'
              err.cause = error

              try {
                if (this._logger && typeof this._logger.event === 'function') {
                  this._logger.event(
                    'applescript.run.fail',
                    {
                      code: err.code,
                      durationMs,
                      msg: sanitizeForLog(msg),
                      stderrLen: errText ? errText.length : 0
                    },
                    { level: 'warn' }
                  )
                } else if (this._logger && typeof this._logger.warn === 'function') {
                  this._logger.warn(
                    `runAppleScript:fail code=${err.code} msg=${sanitizeForLog(msg)}`
                  )
                }
              } catch {
                // 忽略：日志系统异常不应影响执行
              }

              reject(err)
              return
            }

            if (errText) {
              const err = new Error(errText)
              err.code = 'APPLE_SCRIPT_STDERR'

              try {
                if (this._logger && typeof this._logger.event === 'function') {
                  this._logger.event(
                    'applescript.run.stderr',
                    {
                      code: err.code,
                      durationMs,
                      msg: sanitizeForLog(errText)
                    },
                    { level: 'warn' }
                  )
                } else if (this._logger && typeof this._logger.warn === 'function') {
                  this._logger.warn(`runAppleScript:stderr msg=${sanitizeForLog(errText)}`)
                }
              } catch {
                // 忽略：日志系统异常不应影响执行
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
              } else if (this._logger && typeof this._logger.debug === 'function') {
                this._logger.debug(`runAppleScript:ok stdoutLen=${outText.length}`)
              }
            } catch {
              // 忽略：日志系统异常不应影响执行
            }

            resolve(outText)
          }
        )
      } catch (e) {
        const err = e instanceof Error ? e : new Error(String(e))
        err.code = 'APPLE_SCRIPT_SPAWN_FAILED'
        const durationMs = Date.now() - startedAt

        try {
          if (this._logger && typeof this._logger.event === 'function') {
            this._logger.event(
              'applescript.run.spawn_failed',
              { code: err.code, durationMs, msg: sanitizeForLog(err.message) },
              { level: 'error' }
            )
          } else if (this._logger && typeof this._logger.error === 'function') {
            this._logger.error(`runAppleScript:spawn_failed ${sanitizeForLog(err.message)}`)
          }
        } catch {
          // 忽略：日志系统异常不应影响执行
        }

        reject(err)
        return
      }

      // 把脚本写入 stdin
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
