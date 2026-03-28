export const NotificationType = Object.freeze({
  VSCODE: 'vscode',
  MACOS_NATIVE: 'macos_native'
} as const)

export type NotificationTypeValue = (typeof NotificationType)[keyof typeof NotificationType]

export const NotificationTrigger = Object.freeze({
  IMMEDIATE: 'immediate',
  DELAYED: 'delayed'
} as const)

export type NotificationTriggerValue = (typeof NotificationTrigger)[keyof typeof NotificationTrigger]

export const NotificationPriority = Object.freeze({
  LOW: 'low',
  NORMAL: 'normal',
  HIGH: 'high',
  URGENT: 'urgent'
} as const)

export type NotificationPriorityValue = (typeof NotificationPriority)[keyof typeof NotificationPriority]

export interface NotificationEvent {
  id: string
  title: string
  message: string
  trigger: NotificationTriggerValue
  types: NotificationTypeValue[]
  metadata: Record<string, unknown>
  priority: NotificationPriorityValue
  source: string
  dedupeKey: string
  timestamp: number
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function toNonEmptyString(value: unknown, fallback = ''): string {
  const s = value == null ? '' : String(value)
  const t = s.trim()
  return t ? t : fallback
}

function normalizeTypes(types: unknown): NotificationTypeValue[] {
  const raw = Array.isArray(types) ? types : []
  const allowed = new Set<string>(Object.values(NotificationType))
  const uniq: NotificationTypeValue[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    const t = toNonEmptyString(item, '')
    if (!t) continue
    if (!allowed.has(t)) continue
    if (seen.has(t)) continue
    seen.add(t)
    uniq.push(t as NotificationTypeValue)
  }
  return uniq
}

function normalizePriority(priority: unknown): NotificationPriorityValue {
  const raw = toNonEmptyString(priority, NotificationPriority.NORMAL)
  const allowed = new Set<string>(Object.values(NotificationPriority))
  return (allowed.has(raw) ? raw : NotificationPriority.NORMAL) as NotificationPriorityValue
}

function normalizeTrigger(trigger: unknown): NotificationTriggerValue {
  const raw = toNonEmptyString(trigger, NotificationTrigger.IMMEDIATE)
  const allowed = new Set<string>(Object.values(NotificationTrigger))
  return (allowed.has(raw) ? raw : NotificationTrigger.IMMEDIATE) as NotificationTriggerValue
}

function newId(prefix = 'notification'): string {
  try {
    return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`
  } catch {
    return `${prefix}_${Date.now()}`
  }
}

/**
 * 规范化 NotificationEvent（避免 Webview 侧传入异常结构导致扩展崩溃）
 */
export function normalizeNotificationEvent(input: unknown): NotificationEvent {
  const evt = isPlainObject(input) ? input : {} as Record<string, unknown>
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
