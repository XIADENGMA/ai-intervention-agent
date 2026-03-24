const { NotificationType, normalizeNotificationEvent } = require('./notification-models')

class NotificationCenter {
  constructor(options = {}) {
    this._logger = options && options.logger ? options.logger : null
    this._providers = new Map()
    this._deduper = new Map()
    this._dedupeWindowMs =
      options && typeof options.dedupeWindowMs === 'number' && Number.isFinite(options.dedupeWindowMs)
        ? Math.max(0, Math.floor(options.dedupeWindowMs))
        : 2500
    // 兜底：避免 dedupeKey 无限增长导致内存泄漏（尤其是 dedupeKey 含 taskId/时间戳等高基数字段时）
    this._dedupePruneIntervalMs = 60000
    this._dedupeTtlMs = 10 * 60 * 1000
    this._dedupeMaxKeys = 5000
    this._dedupeNextPruneAtMs = 0
  }

  registerProvider(type, provider) {
    if (!type || !provider) return
    const t = String(type)
    this._providers.set(t, provider)
  }

  _pruneDeduper(now) {
    try {
      const cutoff = now - this._dedupeTtlMs
      for (const [k, ts] of this._deduper.entries()) {
        if (typeof ts !== 'number' || !Number.isFinite(ts) || ts < cutoff) {
          this._deduper.delete(k)
        }
      }
      // 硬上限：按插入顺序淘汰最老的 key（近似 LRU）
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

  _shouldDedupe(key) {
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
      // 更新插入顺序（Map set 不会改变既有 key 的顺序，因此先 delete 再 set）
      this._deduper.delete(k)
      this._deduper.set(k, now)
      return false
    } catch {
      return false
    }
  }

  async dispatch(eventInput) {
    const event = normalizeNotificationEvent(eventInput)
    const message = event && event.message ? String(event.message) : ''
    if (!message.trim()) {
      return { event, delivered: {}, skipped: true, reason: 'empty_message' }
    }

    const dedupeKey = event && event.dedupeKey ? String(event.dedupeKey) : ''
    if (dedupeKey && this._shouldDedupe(dedupeKey)) {
      return { event, delivered: {}, skipped: true, reason: 'deduped' }
    }

    const types =
      event && Array.isArray(event.types) && event.types.length > 0 ? event.types : [NotificationType.VSCODE]

    const delivered = {}

    await Promise.allSettled(
      types.map(async t => {
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
            // 忽略：日志系统异常不应影响通知流程
          }
          return
        }

        try {
          const ok = await provider.send(event)
          delivered[type] = !!ok
        } catch (e) {
          delivered[type] = false
          try {
            const msg = e && e.message ? String(e.message) : String(e)
            if (this._logger && typeof this._logger.event === 'function') {
              this._logger.event('notify.provider_failed', { type, error: msg }, { level: 'warn' })
            } else if (this._logger && typeof this._logger.warn === 'function') {
              this._logger.warn(`provider_failed: ${type} ${msg ? `(${msg})` : ''}`.trim())
            }
          } catch {
            // 忽略：日志系统异常不应影响通知流程
          }
        }
      })
    )

    return { event, delivered, skipped: false }
  }
}

module.exports = { NotificationCenter }

