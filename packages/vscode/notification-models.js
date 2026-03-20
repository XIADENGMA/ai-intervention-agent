const NotificationType = Object.freeze({
  VSCODE: 'vscode',
  MACOS_NATIVE: 'macos_native'
})

const NotificationTrigger = Object.freeze({
  IMMEDIATE: 'immediate',
  DELAYED: 'delayed'
})

const NotificationPriority = Object.freeze({
  LOW: 'low',
  NORMAL: 'normal',
  HIGH: 'high',
  URGENT: 'urgent'
})

function isPlainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function toNonEmptyString(value, fallback = '') {
  const s = value == null ? '' : String(value)
  const t = s.trim()
  return t ? t : fallback
}

function normalizeTypes(types) {
  const raw = Array.isArray(types) ? types : []
  const allowed = new Set(Object.values(NotificationType))
  const uniq = []
  const seen = new Set()
  for (const item of raw) {
    const t = toNonEmptyString(item, '')
    if (!t) continue
    if (!allowed.has(t)) continue
    if (seen.has(t)) continue
    seen.add(t)
    uniq.push(t)
  }
  return uniq
}

function normalizePriority(priority) {
  const raw = toNonEmptyString(priority, NotificationPriority.NORMAL)
  const allowed = new Set(Object.values(NotificationPriority))
  return allowed.has(raw) ? raw : NotificationPriority.NORMAL
}

function normalizeTrigger(trigger) {
  const raw = toNonEmptyString(trigger, NotificationTrigger.IMMEDIATE)
  const allowed = new Set(Object.values(NotificationTrigger))
  return allowed.has(raw) ? raw : NotificationTrigger.IMMEDIATE
}

function newId(prefix = 'notification') {
  try {
    return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`
  } catch {
    return `${prefix}_${Date.now()}`
  }
}

/**
 * 规范化 NotificationEvent（避免 Webview 侧传入异常结构导致扩展崩溃）
 *
 * 事件结构（建议）：
 * - id: string（可省略）
 * - title: string
 * - message: string
 * - trigger: "immediate" | "delayed"
 * - types: ["vscode", "macos_native", ...]
 * - metadata: object（任意附加信息）
 * - priority: "low" | "normal" | "high" | "urgent"
 * - source: string（可选）
 * - dedupeKey: string（可选）
 */
function normalizeNotificationEvent(input) {
  const evt = isPlainObject(input) ? input : {}
  const id = toNonEmptyString(evt.id, newId())
  const title = toNonEmptyString(evt.title, 'AI Intervention Agent')
  const message = toNonEmptyString(evt.message, '')
  const trigger = normalizeTrigger(evt.trigger)
  const types = normalizeTypes(evt.types)
  const metadata = isPlainObject(evt.metadata) ? evt.metadata : {}
  const priority = normalizePriority(evt.priority)
  const source = toNonEmptyString(evt.source, '')
  const dedupeKey = toNonEmptyString(evt.dedupeKey, '')
  const timestamp = typeof evt.timestamp === 'number' && Number.isFinite(evt.timestamp) ? evt.timestamp : Date.now()

  return {
    id,
    title,
    message,
    trigger,
    types,
    metadata,
    priority,
    source,
    dedupeKey,
    timestamp
  }
}

module.exports = {
  NotificationType,
  NotificationTrigger,
  NotificationPriority,
  normalizeNotificationEvent
}

