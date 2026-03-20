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
  }

  registerProvider(type, provider) {
    if (!type || !provider) return
    const t = String(type)
    this._providers.set(t, provider)
  }

  _shouldDedupe(key) {
    try {
      const k = String(key || '').trim()
      if (!k) return false
      const now = Date.now()
      const last = this._deduper.get(k)
      if (typeof last === 'number' && now - last < this._dedupeWindowMs) {
        return true
      }
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
            if (this._logger && typeof this._logger.debug === 'function') {
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
            if (this._logger && typeof this._logger.warn === 'function') {
              const msg = e && e.message ? String(e.message) : String(e)
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

