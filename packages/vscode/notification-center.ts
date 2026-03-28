import type { Logger } from './logger'
import type { NotificationEvent, NotificationTypeValue } from './notification-models'

const { NotificationType, normalizeNotificationEvent } = require('./notification-models')

export interface NotificationProvider {
  send(event: NotificationEvent): Promise<boolean> | boolean
}

interface NotificationCenterOptions {
  logger?: Logger | null
  dedupeWindowMs?: number
}

interface DispatchResult {
  event: NotificationEvent
  delivered: Record<string, boolean>
  skipped: boolean
  reason?: string
}

export class NotificationCenter {
  private _logger: Logger | null
  private _providers: Map<string, NotificationProvider>
  private _deduper: Map<string, number>
  private _dedupeWindowMs: number
  private _dedupePruneIntervalMs: number
  private _dedupeTtlMs: number
  private _dedupeMaxKeys: number
  private _dedupeNextPruneAtMs: number

  constructor(options: NotificationCenterOptions = {}) {
    this._logger = options && options.logger ? options.logger : null
    this._providers = new Map()
    this._deduper = new Map()
    this._dedupeWindowMs =
      options && typeof options.dedupeWindowMs === 'number' && Number.isFinite(options.dedupeWindowMs)
        ? Math.max(0, Math.floor(options.dedupeWindowMs))
        : 2500
    this._dedupePruneIntervalMs = 60000
    this._dedupeTtlMs = 10 * 60 * 1000
    this._dedupeMaxKeys = 5000
    this._dedupeNextPruneAtMs = 0
  }

  registerProvider(type: string, provider: NotificationProvider): void {
    if (!type || !provider) return
    const t = String(type)
    this._providers.set(t, provider)
  }

  private _pruneDeduper(now: number): void {
    try {
      const cutoff = now - this._dedupeTtlMs
      for (const [k, ts] of this._deduper.entries()) {
        if (typeof ts !== 'number' || !Number.isFinite(ts) || ts < cutoff) {
          this._deduper.delete(k)
        }
      }
      while (this._deduper.size > this._dedupeMaxKeys) {
        const firstKey = this._deduper.keys().next().value
        if (firstKey === undefined) break
        this._deduper.delete(firstKey)
      }
    } catch {
      // 忽略：去重表清理失败不应影响通知流程
    } finally {
      this._dedupeNextPruneAtMs = now + this._dedupePruneIntervalMs
    }
  }

  private _shouldDedupe(key: string): boolean {
    try {
      const k = String(key || '').trim()
      if (!k) return false
      const now = Date.now()
      if (now >= this._dedupeNextPruneAtMs || this._deduper.size > this._dedupeMaxKeys) {
        this._pruneDeduper(now)
      }
      const last = this._deduper.get(k)
      if (typeof last === 'number' && now - last < this._dedupeWindowMs) {
        return true
      }
      this._deduper.delete(k)
      this._deduper.set(k, now)
      return false
    } catch {
      return false
    }
  }

  async dispatch(eventInput: unknown): Promise<DispatchResult> {
    const event = normalizeNotificationEvent(eventInput) as NotificationEvent
    const message = event && event.message ? String(event.message) : ''
    if (!message.trim()) {
      return { event, delivered: {}, skipped: true, reason: 'empty_message' }
    }

    const dedupeKey = event && event.dedupeKey ? String(event.dedupeKey) : ''
    if (dedupeKey && this._shouldDedupe(dedupeKey)) {
      try {
        if (this._logger && typeof this._logger.debug === 'function') {
          this._logger.debug(`deduped: key=${dedupeKey} window=${this._dedupeWindowMs}ms`)
        }
      } catch { /* noop */ }
      return { event, delivered: {}, skipped: true, reason: 'deduped' }
    }

    const types: NotificationTypeValue[] =
      event && Array.isArray(event.types) && event.types.length > 0
        ? event.types
        : [NotificationType.VSCODE as NotificationTypeValue]

    const delivered: Record<string, boolean> = {}

    await Promise.allSettled(
      types.map(async (t: NotificationTypeValue) => {
        const type = String(t || '')
        if (!type) return

        const provider = this._providers.get(type)
        if (!provider || typeof provider.send !== 'function') {
          delivered[type] = false
          try {
            if (this._logger && typeof this._logger.event === 'function') {
              this._logger.event('notify.provider_not_registered', { type }, { level: 'debug' })
            } else if (this._logger && typeof this._logger.debug === 'function') {
              this._logger.debug(`provider_not_registered: ${type}`)
            }
          } catch {
            // 忽略
          }
          return
        }

        try {
          const ok = await provider.send(event)
          delivered[type] = !!ok
        } catch (e: unknown) {
          delivered[type] = false
          try {
            const msg = e instanceof Error ? e.message : String(e)
            if (this._logger && typeof this._logger.event === 'function') {
              this._logger.event('notify.provider_failed', { type, error: msg }, { level: 'warn' })
            } else if (this._logger && typeof this._logger.warn === 'function') {
              this._logger.warn(`provider_failed: ${type} ${msg ? `(${msg})` : ''}`.trim())
            }
          } catch {
            // 忽略
          }
        }
      })
    )

    return { event, delivered, skipped: false }
  }
}

module.exports = { NotificationCenter }
