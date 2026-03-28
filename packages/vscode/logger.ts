type LogLevel = 'error' | 'warn' | 'info' | 'debug'

const LEVELS: Record<LogLevel, number> = {
  error: 0,
  warn: 1,
  info: 2,
  debug: 3
}

// =========================
// 控噪策略（Phase 2）
// =========================
const DEDUPE_WINDOW_DEBUG_INFO_MS = 2500
const DEDUPE_WINDOW_WARN_MS = 5000
const DEDUPE_MAX_KEYS = 2000

const DEBUG_BURST_WINDOW_MS = 1500
const DEBUG_BURST_MAX = 30
const DEBUG_BURST_REPORT_MS = 4000

const RECENT_MAX_LINES = 500

interface DebugBurstBucket {
  windowStartMs: number
  count: number
  suppressed: number
  lastReportMs: number
}

interface ChannelState {
  dedupe: Map<string, number>
  debugBurst: Map<string, DebugBurstBucket>
  recentLines: string[]
}

interface OutputChannelLike {
  appendLine?: (line: string) => void
  append?: (text: string) => void
  error?: (msg: string) => void
  warn?: (msg: string) => void
  info?: (msg: string) => void
  debug?: (msg: string) => void
}

export interface LoggerOptions {
  getLevel?: () => string
  component?: string
}

export interface Logger {
  debug: (msg: unknown) => void
  info: (msg: unknown) => void
  warn: (msg: unknown) => void
  error: (msg: unknown) => void
  getRecentLines: (limit?: number) => string[]
  event: (
    eventName: string,
    fields?: Record<string, unknown>,
    options?: { level?: string; message?: string }
  ) => void
  child: (name: string) => Logger
}

const CHANNEL_STATE = new WeakMap<object, ChannelState>()

function getChannelState(outputChannel: OutputChannelLike | null): ChannelState | null {
  try {
    if (!outputChannel) return null
    const t = typeof outputChannel
    if (t !== 'object' && t !== 'function') return null
    let state = CHANNEL_STATE.get(outputChannel)
    if (!state) {
      state = {
        dedupe: new Map(),
        debugBurst: new Map(),
        recentLines: []
      }
      CHANNEL_STATE.set(outputChannel, state)
    }
    return state
  } catch {
    return null
  }
}

function recordRecentLine(state: ChannelState | null, line: string): void {
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

function normalizeLevel(input: unknown, fallback: LogLevel = 'info'): LogLevel {
  const raw = ((input ?? '') as string).toString().trim().toLowerCase()
  if (raw && Object.prototype.hasOwnProperty.call(LEVELS, raw)) return raw as LogLevel
  return fallback
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function pad3(n: number): string {
  return String(n).padStart(3, '0')
}

function formatTimestamp(date = new Date()): string {
  const y = date.getFullYear()
  const m = pad2(date.getMonth() + 1)
  const d = pad2(date.getDate())
  const hh = pad2(date.getHours())
  const mm = pad2(date.getMinutes())
  const ss = pad2(date.getSeconds())
  const ms = pad3(date.getMilliseconds())
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}.${ms}`
}

function safeString(value: unknown): string {
  try {
    if (value === null || value === undefined) return ''
    if (value instanceof Error) {
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

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function escapeControlChars(input: unknown): string {
  try {
    const text = ((input ?? '') as string).toString()
    if (!text) return ''
    return text
      .replace(/\r/g, '\\r')
      .replace(/\n/g, '\\n')
      .replace(/\t/g, '\\t')
      .replace(/\0/g, '\\0')
  } catch {
    return ''
  }
}

function redactSensitive(input: unknown): string {
  try {
    let text = ((input ?? '') as string).toString()
    if (!text) return ''

    text = text.replace(/\bsk-[A-Za-z0-9]{32,}\b/g, '***REDACTED***')
    text = text.replace(/\bghp_[A-Za-z0-9]{36}\b/g, '***REDACTED***')
    text = text.replace(/\bxoxb-[A-Za-z0-9-]{50,}\b/g, '***REDACTED***')

    text = text.replace(
      /("?(?:password|passwd|bark_device_key)"?\s*[:=]\s*")([^"]+)(")/gi,
      '$1***REDACTED***$3'
    )

    return text
  } catch {
    return ''
  }
}

function truncate(input: unknown, maxLen = 2000): string {
  try {
    const text = ((input ?? '') as string).toString()
    if (!text) return ''
    if (text.length <= maxLen) return text
    return `${text.slice(0, Math.max(0, maxLen))}…`
  } catch {
    return ''
  }
}

function sanitizeMessage(input: unknown): string {
  const raw = ((input ?? '') as string).toString()
  if (!raw) return ''
  return truncate(redactSensitive(escapeControlChars(raw)))
}

function isBareToken(value: unknown): boolean {
  try {
    const s = ((value ?? '') as string).toString()
    if (!s) return false
    return /^[A-Za-z0-9_.:/-]+$/.test(s)
  } catch {
    return false
  }
}

function normalizeFieldKey(key: unknown): string {
  try {
    const raw = String(key ?? '').trim()
    if (!raw) return ''
    return raw.replace(/[^A-Za-z0-9_.:-]/g, '_')
  } catch {
    return ''
  }
}

function formatFieldValue(value: unknown): string {
  try {
    if (value === undefined) return ''
    if (value === null) return 'null'
    if (typeof value === 'boolean') return value ? 'true' : 'false'
    if (typeof value === 'number' || typeof value === 'bigint') return String(value)
    if (typeof value === 'string') {
      return isBareToken(value) ? value : JSON.stringify(value)
    }

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

function formatKeyValueFields(fields: unknown): string {
  const obj = isPlainObject(fields) ? fields : {}
  const keys = Object.keys(obj).sort()
  const parts: string[] = []
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

function formatEventMessage(
  eventName: string,
  fields: Record<string, unknown> | undefined,
  message: unknown
): string {
  const evt = formatFieldValue(eventName)
  const parts = [`event=${evt || 'unknown'}`]
  const msg = message == null ? '' : String(message)
  const merged = isPlainObject(fields) ? fields : {}
  const kv = formatKeyValueFields(merged)
  if (kv) parts.push(kv)
  if (msg && !Object.prototype.hasOwnProperty.call(merged, 'msg')) {
    const msgToken = formatFieldValue(msg)
    if (msgToken) parts.push(`msg=${msgToken}`)
  }
  return parts.join(' ')
}

interface FormatLineArgs {
  ts: string
  level: string
  component: string
  message: string
}

function formatLine({ ts, level, component, message }: FormatLineArgs): string {
  const lvl = String(level || '').toUpperCase() || 'INFO'
  const comp = component ? String(component) : 'vscode'
  const msg = message ? String(message) : ''
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
export function createLogger(outputChannel: OutputChannelLike, opts: LoggerOptions = {}): Logger {
  const getLevel =
    typeof opts.getLevel === 'function' ? opts.getLevel : () => 'info'
  const component = opts.component ? String(opts.component) : 'vscode'
  const state = getChannelState(outputChannel)

  function shouldLog(level: LogLevel): boolean {
    const current = LEVELS[normalizeLevel(getLevel())]
    return LEVELS[level] <= current
  }

  function emitLine(line: string, fallbackLevel: LogLevel): void {
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

  function maybeReportDebugSuppressed(bucket: DebugBurstBucket, now: number): void {
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

  function write(level: LogLevel, message: unknown): void {
    if (!shouldLog(level)) return
    if (!outputChannel) return

    const raw = safeString(message)
    const msg = sanitizeMessage(raw)
    if (!msg) return

    const now = Date.now()

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

    if (dedupeWindowMs > 0 && state) {
      state.dedupe.set(dedupeKey, now)
      if (state.dedupe.size > DEDUPE_MAX_KEYS) {
        state.dedupe.clear()
      }
    }

    const ts = formatTimestamp()
    const line = formatLine({ ts, level, component, message: msg })

    emitLine(line, level)
  }

  return {
    debug: (msg: unknown) => write('debug', msg),
    info: (msg: unknown) => write('info', msg),
    warn: (msg: unknown) => write('warn', msg),
    error: (msg: unknown) => write('error', msg),
    getRecentLines: (limit = 200): string[] => {
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
    event: (
      eventName: string,
      fields?: Record<string, unknown>,
      options: { level?: string; message?: string } = {}
    ): void => {
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
    child: (name: string): Logger =>
      createLogger(outputChannel, {
        getLevel,
        component: `${component}:${String(name)}`
      })
  }
}

module.exports = {
  createLogger
}
