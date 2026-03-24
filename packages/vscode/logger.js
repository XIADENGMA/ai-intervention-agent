const LEVELS = {
  error: 0,
  warn: 1,
  info: 2,
  debug: 3
}

// =========================
// 控噪策略（Phase 2）
// =========================
// 去重窗口（相同 message 在窗口内仅记录一次）
const DEDUPE_WINDOW_DEBUG_INFO_MS = 2500
const DEDUPE_WINDOW_WARN_MS = 5000
const DEDUPE_MAX_KEYS = 2000

// debug 突发限流：当短时间内 debug 日志过多时抑制，并定期输出 suppressed 统计
const DEBUG_BURST_WINDOW_MS = 1500
const DEBUG_BURST_MAX = 30
const DEBUG_BURST_REPORT_MS = 4000

// 诊断信息：保留最近 N 行日志（内存环形缓冲的简化实现）
const RECENT_MAX_LINES = 500

const CHANNEL_STATE = new WeakMap()

function getChannelState(outputChannel) {
  try {
    if (!outputChannel) return null
    const t = typeof outputChannel
    if (t !== 'object' && t !== 'function') return null
    let state = CHANNEL_STATE.get(outputChannel)
    if (!state) {
      state = {
        dedupe: new Map(), // key -> lastTs
        debugBurst: new Map(), // component -> bucket
        recentLines: [] // 最近日志（用于导出诊断信息）
      }
      CHANNEL_STATE.set(outputChannel, state)
    }
    return state
  } catch {
    return null
  }
}

function recordRecentLine(state, line) {
  try {
    if (!state || !Array.isArray(state.recentLines)) return
    const text = (line ?? '').toString()
    if (!text) return
    state.recentLines.push(text)
    if (state.recentLines.length > RECENT_MAX_LINES) {
      state.recentLines.splice(0, state.recentLines.length - RECENT_MAX_LINES)
    }
  } catch {
    // 忽略
  }
}

function normalizeLevel(input, fallback = 'info') {
  const raw = (input ?? '').toString().trim().toLowerCase()
  if (raw && Object.prototype.hasOwnProperty.call(LEVELS, raw)) return raw
  return fallback
}

function pad2(n) {
  return String(n).padStart(2, '0')
}

function pad3(n) {
  return String(n).padStart(3, '0')
}

function formatTimestamp(date = new Date()) {
  // 本地时间：更符合“看日志排查”的直觉（避免时区困扰）
  const y = date.getFullYear()
  const m = pad2(date.getMonth() + 1)
  const d = pad2(date.getDate())
  const hh = pad2(date.getHours())
  const mm = pad2(date.getMinutes())
  const ss = pad2(date.getSeconds())
  const ms = pad3(date.getMilliseconds())
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}.${ms}`
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

function isPlainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function escapeControlChars(input) {
  try {
    const text = (input ?? '').toString()
    if (!text) return ''
    // 防止“多行日志伪造/注入”：把控制字符转义为可见形式
    return text
      .replace(/\r/g, '\\r')
      .replace(/\n/g, '\\n')
      .replace(/\t/g, '\\t')
      .replace(/\0/g, '\\0')
  } catch {
    return ''
  }
}

function redactSensitive(input) {
  try {
    let text = (input ?? '').toString()
    if (!text) return ''

    // 常见密钥格式（尽量精确，避免过度脱敏）
    text = text.replace(/\bsk-[A-Za-z0-9]{32,}\b/g, '***REDACTED***')
    text = text.replace(/\bghp_[A-Za-z0-9]{36}\b/g, '***REDACTED***')
    text = text.replace(/\bxoxb-[A-Za-z0-9-]{50,}\b/g, '***REDACTED***')

    // 明确字段（JSON/日志片段）
    text = text.replace(/("?(?:password|passwd|bark_device_key)"?\s*[:=]\s*")([^"]+)(")/gi, '$1***REDACTED***$3')

    return text
  } catch {
    return ''
  }
}

function truncate(input, maxLen = 2000) {
  try {
    const text = (input ?? '').toString()
    if (!text) return ''
    if (text.length <= maxLen) return text
    return `${text.slice(0, Math.max(0, maxLen))}…`
  } catch {
    return ''
  }
}

function sanitizeMessage(input) {
  const raw = (input ?? '').toString()
  if (!raw) return ''
  return truncate(redactSensitive(escapeControlChars(raw)))
}

function isBareToken(value) {
  try {
    const s = (value ?? '').toString()
    if (!s) return false
    // 允许常见 token 字符（便于 grep 和肉眼扫描）
    return /^[A-Za-z0-9_.:/-]+$/.test(s)
  } catch {
    return false
  }
}

function normalizeFieldKey(key) {
  try {
    const raw = String(key ?? '').trim()
    if (!raw) return ''
    // key=value 格式：key 不允许空格/等号等分隔符；其它字符用 _ 替代
    return raw.replace(/[^A-Za-z0-9_.:-]/g, '_')
  } catch {
    return ''
  }
}

function formatFieldValue(value) {
  try {
    if (value === undefined) return ''
    if (value === null) return 'null'
    if (typeof value === 'boolean') return value ? 'true' : 'false'
    if (typeof value === 'number' || typeof value === 'bigint') return String(value)
    if (typeof value === 'string') {
      return isBareToken(value) ? value : JSON.stringify(value)
    }

    // object / array
    const json = JSON.stringify(value)
    return isBareToken(json) ? json : json
  } catch {
    try {
      const s = String(value)
      return isBareToken(s) ? s : JSON.stringify(s)
    } catch {
      return ''
    }
  }
}

function formatKeyValueFields(fields) {
  const obj = isPlainObject(fields) ? fields : {}
  const keys = Object.keys(obj).sort()
  const parts = []
  for (const k of keys) {
    if (k === 'event') continue
    const key = normalizeFieldKey(k)
    if (!key) continue
    const v = obj[k]
    if (v === undefined) continue
    const token = formatFieldValue(v)
    if (!token) continue
    parts.push(`${key}=${token}`)
  }
  return parts.join(' ')
}

function formatEventMessage(eventName, fields, message) {
  const evt = formatFieldValue(eventName)
  const parts = [`event=${evt || 'unknown'}`]
  const msg = message == null ? '' : String(message)
  const merged = isPlainObject(fields) ? fields : {}
  const kv = formatKeyValueFields(merged)
  if (kv) parts.push(kv)
  if (msg && !Object.prototype.hasOwnProperty.call(merged, 'msg')) {
    // message 一律作为 msg= 字段（避免自由文本破坏结构化 grep）
    const msgToken = formatFieldValue(msg)
    if (msgToken) parts.push(`msg=${msgToken}`)
  }
  return parts.join(' ')
}

function formatLine({ ts, level, component, message }) {
  const lvl = String(level || '').toUpperCase() || 'INFO'
  const comp = component ? String(component) : 'vscode'
  const msg = message ? String(message) : ''
  // 单行、结构化、可 grep：固定顺序 [ts] [LEVEL] [component] message
  return `[${ts}] [${lvl}] [${comp}] ${msg}`
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
  const state = getChannelState(outputChannel)

  function shouldLog(level) {
    const current = LEVELS[normalizeLevel(getLevel())]
    return LEVELS[level] <= current
  }

  function emitLine(line, fallbackLevel) {
    recordRecentLine(state, line)
    try {
      if (typeof outputChannel.appendLine === 'function') {
        outputChannel.appendLine(line)
        return
      }
      if (typeof outputChannel.append === 'function') {
        outputChannel.append(`${line}\n`)
        return
      }
    } catch {
      // 忽略：写入失败不应影响主流程
    }

    // 极端兼容：某些 fake channel 可能只实现了 info/warn/error/debug
    try {
      const direct =
        fallbackLevel === 'error'
          ? outputChannel.error
          : fallbackLevel === 'warn'
            ? outputChannel.warn
            : fallbackLevel === 'info'
              ? outputChannel.info
              : outputChannel.debug
      if (typeof direct === 'function') {
        direct.call(outputChannel, line)
      }
    } catch {
      // 忽略
    }
  }

  function maybeReportDebugSuppressed(bucket, now) {
    try {
      if (!bucket || !bucket.suppressed) return
      const last = typeof bucket.lastReportMs === 'number' ? bucket.lastReportMs : 0
      if (now - last < DEBUG_BURST_REPORT_MS) return

      const msg = sanitizeMessage(
        formatEventMessage(
          'log.suppressed',
          {
            level: 'debug',
            suppressed: bucket.suppressed,
            windowMs: DEBUG_BURST_WINDOW_MS,
            max: DEBUG_BURST_MAX
          },
          ''
        )
      )
      if (!msg) return

      const ts = formatTimestamp()
      const line = formatLine({ ts, level: 'info', component, message: msg })
      emitLine(line, 'info')

      bucket.lastReportMs = now
      bucket.suppressed = 0
    } catch {
      // 忽略
    }
  }

  function write(level, message) {
    if (!shouldLog(level)) return
    if (!outputChannel) return

    const raw = safeString(message)
    const msg = sanitizeMessage(raw)
    if (!msg) return

    const now = Date.now()

    // 去重：相同消息在窗口内只记录一次（避免刷屏）
    const dedupeWindowMs =
      level === 'warn'
        ? DEDUPE_WINDOW_WARN_MS
        : level === 'debug' || level === 'info'
          ? DEDUPE_WINDOW_DEBUG_INFO_MS
          : 0
    const dedupeKey = dedupeWindowMs > 0 ? `${level}|${component}|${msg}` : ''
    if (dedupeWindowMs > 0 && state) {
      const last = state.dedupe.get(dedupeKey)
      if (typeof last === 'number' && now - last < dedupeWindowMs) {
        return
      }
    }

    // debug 突发限流：高频 debug 刷屏时抑制（并输出 suppressed 统计）
    if (level === 'debug' && state) {
      let bucket = state.debugBurst.get(component)
      if (!bucket) {
        bucket = { windowStartMs: now, count: 0, suppressed: 0, lastReportMs: 0 }
      }
      const windowStartMs = typeof bucket.windowStartMs === 'number' ? bucket.windowStartMs : now
      if (now - windowStartMs >= DEBUG_BURST_WINDOW_MS) {
        bucket.windowStartMs = now
        bucket.count = 0
      }

      if (typeof bucket.count !== 'number') bucket.count = 0
      if (bucket.count >= DEBUG_BURST_MAX) {
        bucket.suppressed = (typeof bucket.suppressed === 'number' ? bucket.suppressed : 0) + 1
        maybeReportDebugSuppressed(bucket, now)
        state.debugBurst.set(component, bucket)
        return
      }

      bucket.count += 1
      state.debugBurst.set(component, bucket)
    }

    // 提交去重状态（仅对“将要写入”的日志生效，避免被限流的日志污染去重表）
    if (dedupeWindowMs > 0 && state) {
      state.dedupe.set(dedupeKey, now)
      if (state.dedupe.size > DEDUPE_MAX_KEYS) {
        state.dedupe.clear()
      }
    }

    const ts = formatTimestamp()
    const line = formatLine({ ts, level, component, message: msg })

    // 方案 A：统一使用 appendLine 写入，绕开 LogOutputChannel 的 logLevel 二次过滤
    emitLine(line, level)
  }

  return {
    debug: msg => write('debug', msg),
    info: msg => write('info', msg),
    warn: msg => write('warn', msg),
    error: msg => write('error', msg),
    getRecentLines: (limit = 200) => {
      try {
        const nRaw = Number(limit)
        const n = Number.isFinite(nRaw) ? Math.max(0, Math.floor(nRaw)) : 200
        if (!state || !Array.isArray(state.recentLines) || state.recentLines.length === 0) return []
        if (n <= 0) return []
        const start = Math.max(0, state.recentLines.length - n)
        return state.recentLines.slice(start)
      } catch {
        return []
      }
    },
    event: (eventName, fields, options = {}) => {
      try {
        const optsObj = isPlainObject(options) ? options : {}
        const lvl = normalizeLevel(optsObj.level, 'info')
        const msg = optsObj && typeof optsObj.message !== 'undefined' ? optsObj.message : ''
        const payload = formatEventMessage(eventName, fields, msg)
        write(lvl, payload)
      } catch {
        // 忽略：日志本身不应影响主流程
      }
    },
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

