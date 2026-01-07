const LEVELS = {
  error: 0,
  warn: 1,
  info: 2,
  debug: 3
}

function normalizeLevel(input, fallback = 'info') {
  const raw = (input ?? '').toString().trim().toLowerCase()
  if (raw && Object.prototype.hasOwnProperty.call(LEVELS, raw)) return raw
  return fallback
}

function formatTimestamp(date = new Date()) {
  // 仅用于日志展示：使用本地时间，避免时区困扰
  return date.toLocaleTimeString('zh-CN')
}

function safeString(value) {
  try {
    if (value === null || value === undefined) return ''
    if (value instanceof Error) {
      // 默认精简：仅输出 name + message；需要堆栈时请在调用侧显式传入 e.stack
      const name = value.name ? String(value.name) : 'Error'
      const msg = value.message ? String(value.message) : ''
      return msg ? `${name}: ${msg}` : name
    }
    if (typeof value === 'string') return value
    return JSON.stringify(value)
  } catch {
    try {
      return String(value)
    } catch {
      return ''
    }
  }
}

/**
 * 创建轻量、可控的日志器
 *
 * 设计目标：
 * - 精简：默认只输出 info/warn/error
 * - 必要：关键生命周期/状态变化必记；高频路径默认不刷屏
 * - 高效：先判级别再格式化，避免不必要的字符串拼接
 * - 清晰：统一格式，包含时间/级别/模块
 */
function createLogger(outputChannel, opts = {}) {
  const getLevel =
    typeof opts.getLevel === 'function' ? opts.getLevel : () => 'info'
  const component = opts.component ? String(opts.component) : 'vscode'

  function shouldLog(level) {
    const current = LEVELS[normalizeLevel(getLevel())]
    return LEVELS[level] <= current
  }

  function write(level, message) {
    if (!shouldLog(level)) return
    if (!outputChannel) return

    const msg = safeString(message)
    if (!msg) return

    // LogOutputChannel（createOutputChannel(name, { log: true })）会自动加时间戳与等级前缀：
    // 例如：2026-01-07 11:13:28.347 [info]
    // 为避免重复，我们只输出 `[component] message`
    const text = `[${component}] ${msg}`

    // 优先使用 LogOutputChannel 的分级方法（info/warn/error/debug）
    const direct =
      level === 'error'
        ? outputChannel.error
        : level === 'warn'
          ? outputChannel.warn
          : level === 'info'
            ? outputChannel.info
            : outputChannel.debug
    if (typeof direct === 'function') {
      try {
        direct.call(outputChannel, text)
        return
      } catch {
        // ignore and fallback
      }
    }

    // 兼容旧版 VSCode：普通 OutputChannel 仅有 appendLine
    if (typeof outputChannel.appendLine !== 'function') return
    const ts = formatTimestamp()
    const lvl = level.toUpperCase()
    outputChannel.appendLine(`[${ts}] [${lvl}] ${text}`)
  }

  return {
    debug: msg => write('debug', msg),
    info: msg => write('info', msg),
    warn: msg => write('warn', msg),
    error: msg => write('error', msg),
    child: name =>
      createLogger(outputChannel, {
        getLevel,
        component: `${component}:${String(name)}`
      })
  }
}

module.exports = {
  createLogger
}

