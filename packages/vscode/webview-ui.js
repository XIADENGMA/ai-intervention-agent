/* eslint-disable */

;(function () {
  let vscode
  try {
    vscode = acquireVsCodeApi()
  } catch (e) {
    vscode = {
      postMessage: function () {},
      getState: function () {
        return null
      },
      setState: function () {}
    }
  }

  try {
    if (typeof globalThis !== 'undefined' && globalThis) {
      globalThis.__AIIA_VSCODE_API = vscode
    }
  } catch (e) {

  }

  ;(function ensureI18nReady() {
    try {
      var i18n =
        (typeof globalThis !== 'undefined' && globalThis.AIIA_I18N) ||
        (typeof window !== 'undefined' && window.AIIA_I18N)
      if (!i18n || typeof i18n.registerLocale !== 'function') return

      var langs = typeof i18n.getAvailableLangs === 'function' ? i18n.getAvailableLangs() : []
      var needsInit = langs.length === 0

      var allLocales = (typeof window !== 'undefined' && window.__AIIA_I18N_ALL_LOCALES) || null
      var activeLang =
        (typeof window !== 'undefined' && window.__AIIA_I18N_LANG) || ''

      if (allLocales && typeof allLocales === 'object') {
        var registerOne = function (lang) {
          if (!lang) return
          var data = allLocales[lang]
          if (data && typeof data === 'object') {
            try {
              i18n.registerLocale(lang, data)
            } catch (_) {

            }
          }
        }
        if (activeLang) registerOne(activeLang)

        if (activeLang !== 'en') registerOne('en')
      }

      if (needsInit) {
        var loc = (typeof window !== 'undefined' && window.__AIIA_I18N_LOCALE) || null
        if (loc && typeof loc === 'object' && activeLang) {
          i18n.registerLocale(String(activeLang), loc)
          if (typeof i18n.setLang === 'function') i18n.setLang(String(activeLang))
        }
      }
    } catch (e) {

    }
  })()

  function ensureLocaleRegistered(targetLang) {
    if (!targetLang) return false
    try {
      var i18n =
        (typeof globalThis !== 'undefined' && globalThis.AIIA_I18N) ||
        (typeof window !== 'undefined' && window.AIIA_I18N)
      if (!i18n || typeof i18n.registerLocale !== 'function') return false
      var registered = typeof i18n.getAvailableLangs === 'function' ? i18n.getAvailableLangs() : []
      if (registered.indexOf(targetLang) >= 0) return true
      var allLocales = (typeof window !== 'undefined' && window.__AIIA_I18N_ALL_LOCALES) || null
      if (allLocales && allLocales[targetLang] && typeof allLocales[targetLang] === 'object') {
        try {
          i18n.registerLocale(targetLang, allLocales[targetLang])
          return true
        } catch (_) {
          return false
        }
      }
      return false
    } catch (_) {
      return false
    }
  }

  function t(key, params) {
    try {
      var i18n =
        (typeof globalThis !== 'undefined' && globalThis.AIIA_I18N) ||
        (typeof window !== 'undefined' && window.AIIA_I18N)
      if (i18n && typeof i18n.t === 'function') return i18n.t(key, params)
    } catch (_e) {

    }
    return key
  }

  let _serverLangLastApplied = ''

  function getI18n() {
    try {
      return (
        (typeof globalThis !== 'undefined' && globalThis.AIIA_I18N) ||
        (typeof window !== 'undefined' && window.AIIA_I18N) ||
        null
      )
    } catch (e) {
      return null
    }
  }

  function applyServerLanguage(lang) {
    if (!lang || lang === 'auto' || lang === _serverLangLastApplied) return
    _serverLangLastApplied = lang
    try {
      vscode.postMessage({ type: 'langDetected', language: lang })
    } catch (e) {

    }
    var i18n = getI18n()
    if (!i18n || typeof i18n.setLang !== 'function' || typeof i18n.getLang !== 'function') return
    var normalized = typeof i18n.normalizeLang === 'function' ? i18n.normalizeLang(lang) : lang
    if (normalized !== i18n.getLang()) {

      ensureLocaleRegistered(normalized)
      i18n.setLang(normalized)
      retranslateAllI18nElements()
    }
  }

  function retranslateAllI18nElements() {
    try {

      var i18n = getI18n()
      if (i18n && typeof i18n.translateDOM === 'function') {
        try {
          i18n.translateDOM()
        } catch (e) {

        }
      } else {

        var els = document.querySelectorAll('[data-i18n]')
        for (var i = 0; i < els.length; i++) {
          try {
            var key = els[i].getAttribute('data-i18n')
            if (!key) continue
            var val = t(key)
            if (val && val !== key) els[i].textContent = val
          } catch (e) {

          }
        }
        var titleEls = document.querySelectorAll('[data-i18n-title]')
        for (var j = 0; j < titleEls.length; j++) {
          try {
            var tkey = titleEls[j].getAttribute('data-i18n-title')
            if (!tkey) continue
            var tval = t(tkey)
            if (tval && tval !== tkey) {
              titleEls[j].setAttribute('title', tval)
              titleEls[j].setAttribute('aria-label', tval)
            }
          } catch (e) {

          }
        }
        var phEls = document.querySelectorAll('[data-i18n-placeholder]')
        for (var k = 0; k < phEls.length; k++) {
          try {
            var pkey = phEls[k].getAttribute('data-i18n-placeholder')
            if (!pkey) continue
            var pval = t(pkey)
            if (pval && pval !== pkey) phEls[k].setAttribute('placeholder', pval)
          } catch (e) {

          }
        }
      }

      var verEls = document.querySelectorAll('[data-i18n][data-i18n-version]')
      for (var v = 0; v < verEls.length; v++) {
        try {
          var vKey = verEls[v].getAttribute('data-i18n')
          if (!vKey) continue
          var ver = verEls[v].getAttribute('data-i18n-version')
          var vVal = t(vKey, { version: ver })
          if (vVal && vVal !== vKey) verEls[v].textContent = vVal
        } catch (e) {

        }
      }
    } catch (e) {

    }
  }

  const __cfgEl = document.getElementById('aiia-config')
  const SERVER_URL =
    __cfgEl && __cfgEl.getAttribute('data-server-url')
      ? __cfgEl.getAttribute('data-server-url')
      : ''
  const CSP_NONCE =
    __cfgEl && __cfgEl.getAttribute('data-csp-nonce') ? __cfgEl.getAttribute('data-csp-nonce') : ''
  const LOTTIE_LIB_URL =
    __cfgEl && __cfgEl.getAttribute('data-lottie-lib-url')
      ? __cfgEl.getAttribute('data-lottie-lib-url')
      : ''
  const NO_CONTENT_LOTTIE_JSON_URL =
    __cfgEl && __cfgEl.getAttribute('data-no-content-lottie-json-url')
      ? __cfgEl.getAttribute('data-no-content-lottie-json-url')
      : ''
  const NO_CONTENT_FALLBACK_SVG_URL =
    __cfgEl && __cfgEl.getAttribute('data-no-content-fallback-svg-url')
      ? __cfgEl.getAttribute('data-no-content-fallback-svg-url')
      : ''
  const INLINE_NO_CONTENT_FALLBACK_SVG =
    typeof window !== 'undefined' && typeof window.__AIIA_NO_CONTENT_FALLBACK_SVG === 'string'
      ? window.__AIIA_NO_CONTENT_FALLBACK_SVG
      : ''
  const INLINE_NO_CONTENT_LOTTIE_DATA =
    typeof window !== 'undefined' &&
    window.__AIIA_NO_CONTENT_LOTTIE_DATA &&
    typeof window.__AIIA_NO_CONTENT_LOTTIE_DATA === 'object'
      ? window.__AIIA_NO_CONTENT_LOTTIE_DATA
      : null
  const MATHJAX_SCRIPT_URL =
    __cfgEl && __cfgEl.getAttribute('data-mathjax-script-url')
      ? __cfgEl.getAttribute('data-mathjax-script-url')
      : ''
  const MARKED_JS_URL =
    __cfgEl && __cfgEl.getAttribute('data-marked-js-url')
      ? __cfgEl.getAttribute('data-marked-js-url')
      : ''
  const PRISM_JS_URL =
    __cfgEl && __cfgEl.getAttribute('data-prism-js-url')
      ? __cfgEl.getAttribute('data-prism-js-url')
      : ''
  const NOTIFY_CORE_JS_URL =
    __cfgEl && __cfgEl.getAttribute('data-notify-core-js-url')
      ? __cfgEl.getAttribute('data-notify-core-js-url')
      : ''
  const SETTINGS_UI_JS_URL =
    __cfgEl && __cfgEl.getAttribute('data-settings-ui-js-url')
      ? __cfgEl.getAttribute('data-settings-ui-js-url')
      : ''
  const WEBVIEW_HELPERS =
    typeof window !== 'undefined' && window.AIIAWebviewHelpers ? window.AIIAWebviewHelpers : null
  let themeObserver = null

  function lazyScriptIsReady(isReady) {
    try {
      return typeof isReady === 'function' && !!isReady()
    } catch (e) {
      return false
    }
  }

  function loadLazyScriptOnce(scriptId, scriptUrl, isReady, timeoutMs) {
    if (lazyScriptIsReady(isReady)) return Promise.resolve(true)
    if (!scriptId || !scriptUrl) return Promise.resolve(false)

    return new Promise(resolve => {
      let done = false
      let timer = null
      let script = null

      const finish = ok => {
        if (done) return
        done = true
        if (timer) {
          try {
            clearTimeout(timer)
          } catch (e) {

          }
        }
        if (script) {
          try {
            script.removeEventListener('load', onLoad)
            script.removeEventListener('error', onError)
          } catch (e) {

          }
        }
        resolve(!!ok)
      }
      const checkAndFinish = () => finish(lazyScriptIsReady(isReady))
      const onLoad = () => checkAndFinish()
      const onError = () => finish(false)

      try {
        script = document.getElementById(scriptId)
        if (!script) {
          script = document.createElement('script')
          script.id = scriptId
          script.defer = true
          if (CSP_NONCE) {
            try {
              script.setAttribute('nonce', CSP_NONCE)
            } catch (e) {

            }
          }
          script.addEventListener('load', onLoad, { once: true })
          script.addEventListener('error', onError, { once: true })
          timer = setTimeout(checkAndFinish, Math.max(1, timeoutMs || 5000))
          script.src = scriptUrl
          document.head.appendChild(script)
          return
        }

        script.addEventListener('load', onLoad, { once: true })
        script.addEventListener('error', onError, { once: true })
        timer = setTimeout(checkAndFinish, Math.max(1, timeoutMs || 5000))
        Promise.resolve().then(() => {
          if (!done && lazyScriptIsReady(isReady)) finish(true)
        })
      } catch (e) {
        finish(false)
      }
    })
  }

  let noContentHourglassAnimation = null
  let noContentLottieDisposed = false

  const SERVER_STATUS_TIMEOUT_MS = 1500
  const POLL_TASKS_TIMEOUT_MS = 6000
  const POLL_CONFIG_TIMEOUT_MS = 6000

  const SUBMIT_TIMEOUT_MS = 20000

  function parseRgbColor(color) {
    try {
      if (!color) return null
      const s = String(color).trim()
      if (!s) return null

      const start = s.indexOf('(')
      const end = s.indexOf(')')
      if (start < 0 || end < 0 || end <= start) return null

      const head = s.slice(0, start).toLowerCase()
      if (head !== 'rgb' && head !== 'rgba') return null

      const channels = []
      const raw = s.slice(start + 1, end)
      let partStart = 0
      for (let i = 0; i <= raw.length && channels.length < 3; i += 1) {
        if (i < raw.length && raw[i] !== ',') continue
        const channel = Number(raw.slice(partStart, i).trim())
        if (!Number.isFinite(channel)) return null
        channels.push(channel)
        partStart = i + 1
      }
      if (channels.length < 3) return null

      return { r: channels[0], g: channels[1], b: channels[2] }
    } catch (e) {
      return null
    }
  }

  function isDarkBackground() {
    try {
      const bg = window.getComputedStyle(document.body).backgroundColor
      const rgb = parseRgbColor(bg)
      if (!rgb) return false
      const luminance = 0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b
      return luminance < 128
    } catch (e) {
      return false
    }
  }

  function updateNoContentHourglassColor() {
    const container = document.getElementById('hourglass-lottie')
    if (!container) return

    const shouldInvert = isDarkBackground() && !!noContentHourglassAnimation
    container.classList.toggle('aiia-invert', shouldInvert)
  }

  function isMacLikePlatform() {
    try {
      if (WEBVIEW_HELPERS && typeof WEBVIEW_HELPERS.detectMacLikePlatform === 'function') {
        return !!WEBVIEW_HELPERS.detectMacLikePlatform(navigator)
      }
    } catch (e) {

    }
    return !!(navigator && navigator.platform && navigator.platform.includes('Mac'))
  }

  function applyHostThemeState() {
    try {
      if (WEBVIEW_HELPERS && typeof WEBVIEW_HELPERS.applyThemeKindToDocument === 'function') {
        WEBVIEW_HELPERS.applyThemeKindToDocument(document)
      }
    } catch (e) {

    }
    updateNoContentHourglassColor()
  }

  function installHostThemeObserver() {
    applyHostThemeState()
    if (themeObserver || typeof MutationObserver === 'undefined' || !document.body) return

    themeObserver = new MutationObserver(() => {
      applyHostThemeState()
    })
    themeObserver.observe(document.body, {
      attributes: true,
      attributeFilter: ['class']
    })
  }

  function destroyNoContentHourglassAnimation() {
    clearNoContentLottieTimers()
    try {
      if (noContentHourglassAnimation) {
        noContentHourglassAnimation.destroy()
      }
    } catch (e) {

    } finally {
      noContentHourglassAnimation = null
    }
  }

  let lottieLoadPromise = null
  let noContentLottieDataPromise = null
  let noContentLottieInitInFlight = false
  let lottieInitWarned = false
  let noContentLottieInlineLogged = false

  const NO_CONTENT_LOTTIE_TIMEOUT_MS = 10000
  const NO_CONTENT_LOTTIE_RETRY_MIN_MS = 600
  const NO_CONTENT_LOTTIE_RETRY_MAX_MS = 12000
  let noContentLottieRetryTimer = null
  let noContentLottieDomLoadedTimer = null
  let noContentLottieRetryAttempt = 0

  const LUCIDE_BASE_SVG_ATTRS =
    'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'

  const LUCIDE_SVG_ICONS = {

    hourglass: `<svg ${LUCIDE_BASE_SVG_ATTRS}>
  <path d="M5 22h14" />
  <path d="M5 2h14" />
  <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22" />
  <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2" />
  <path d="M7.8 20.5H16.2L14 16.5H10Z" fill="currentColor" stroke="none" />
</svg>`,

    loader: `<svg ${LUCIDE_BASE_SVG_ATTRS}>
  <path d="M12 2v4" />
  <path d="m16.2 7.8 2.9-2.9" />
  <path d="M18 12h4" />
  <path d="m16.2 16.2 2.9 2.9" />
  <path d="M12 18v4" />
  <path d="m4.9 19.1 2.9-2.9" />
  <path d="M2 12h4" />
  <path d="m4.9 4.9 2.9 2.9" />
</svg>`,

    'loader-circle': `<svg ${LUCIDE_BASE_SVG_ATTRS}>
  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
</svg>`,

    'rotate-cw': `<svg ${LUCIDE_BASE_SVG_ATTRS}>
  <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
  <path d="M21 3v5h-5" />
</svg>`
  }

  const NO_CONTENT_FALLBACK_ICON_VARIANT = 'hourglass'
  const NO_CONTENT_FALLBACK_ICON_SPIN = true

  let noContentFallbackSvgMarkup = INLINE_NO_CONTENT_FALLBACK_SVG
    ? String(INLINE_NO_CONTENT_FALLBACK_SVG)
    : ''
  let noContentFallbackSvgLoadPromise = null
  let noContentFallbackSvgLoadLogged = false
  let noContentFallbackSvgFailLogged = false
  let noContentFallbackSvgAppliedLogged = false
  function loadNoContentFallbackSvgMarkup() {
    if (noContentFallbackSvgMarkup) return Promise.resolve(noContentFallbackSvgMarkup)
    if (noContentFallbackSvgLoadPromise) return noContentFallbackSvgLoadPromise
    if (!NO_CONTENT_FALLBACK_SVG_URL || typeof fetch !== 'function') return Promise.resolve('')

    try {
      if (!noContentFallbackSvgLoadLogged) {
        noContentFallbackSvgLoadLogged = true
        log('no-content fallback svg: fetching activity-icon.svg')
      }
    } catch (_) {

    }

    noContentFallbackSvgLoadPromise = Promise.resolve()
      .then(() => fetch(NO_CONTENT_FALLBACK_SVG_URL, { cache: 'force-cache' }))
      .then(resp => (resp && resp.ok ? resp.text() : ''))
      .then(text => {
        const raw = (text ?? '').toString().trim()
        if (!raw || !raw.startsWith('<svg')) return ''

        const cleaned = raw.replace(/<script[\s\S]*?<\/script>/gi, '')
        noContentFallbackSvgMarkup = cleaned
        try {
          log(`no-content fallback svg: loaded activity-icon.svg (${cleaned.length} chars)`)
        } catch (_) {

        }
        return cleaned
      })
      .catch(() => '')
      .then(markup => {

        if (!markup) {
          noContentFallbackSvgLoadPromise = null
          try {
            if (!noContentFallbackSvgFailLogged) {
              noContentFallbackSvgFailLogged = true
              log('no-content fallback svg: failed to load activity-icon.svg (will retry)')
            }
          } catch (_) {

          }
        }
        return markup
      })

    return noContentFallbackSvgLoadPromise
  }

  try {
    if (NO_CONTENT_FALLBACK_SVG_URL) {
      loadNoContentFallbackSvgMarkup().catch(() => {

      })
    }
  } catch (_) {

  }

  function clearNoContentLottieTimers() {
    try {
      if (noContentLottieRetryTimer) clearTimeout(noContentLottieRetryTimer)
    } catch (_) {

    } finally {
      noContentLottieRetryTimer = null
    }
    try {
      if (noContentLottieDomLoadedTimer) clearTimeout(noContentLottieDomLoadedTimer)
    } catch (_) {

    } finally {
      noContentLottieDomLoadedTimer = null
    }
  }

  function isNoContentVisible() {
    try {
      const el = document.getElementById('noContentState')
      return !!el && !el.classList.contains('hidden')
    } catch (_) {
      return false
    }
  }

  function renderNoContentFallbackIcon(container, options) {
    if (!container) return
    const opts = options && typeof options === 'object' ? options : {}
    const variantRaw = opts.variant ? String(opts.variant) : ''
    const variant =
      variantRaw && LUCIDE_SVG_ICONS[variantRaw] ? variantRaw : NO_CONTENT_FALLBACK_ICON_VARIANT
    const svg = LUCIDE_SVG_ICONS[variant] || ''
    if (!svg) return

    const preferActivityIcon = variant === 'hourglass' && !!NO_CONTENT_FALLBACK_SVG_URL
    const svgMarkup =
      preferActivityIcon && noContentFallbackSvgMarkup ? noContentFallbackSvgMarkup : svg
    if (preferActivityIcon && noContentFallbackSvgMarkup) {
      try {
        if (!noContentFallbackSvgAppliedLogged) {
          noContentFallbackSvgAppliedLogged = true
          log('no-content fallback icon: using activity-icon.svg')
        }
      } catch (_) {

      }
    }

    try {
      const cur = container.getAttribute('data-aiia-fallback-icon') || ''
      if (cur === variant && container.querySelector('.aiia-fallback-icon')) {
        return
      }
    } catch (_) {

    }

    try {
      container.textContent = ''
    } catch (_) {

    }

    let wrapper = null
    try {
      const canSpin =
        variant === 'loader' ||
        variant === 'loader-circle' ||
        variant === 'rotate-cw' ||
        variantRaw === 'spin'
      const shouldSpin =
        !!(opts && typeof opts === 'object' && opts.spin === true) ||
        (canSpin && NO_CONTENT_FALLBACK_ICON_SPIN)
      wrapper = document.createElement('span')
      wrapper.className = 'aiia-fallback-icon' + (shouldSpin ? ' aiia-spin' : '')
      wrapper.innerHTML = svgMarkup
    } catch (_) {
      wrapper = null
    }

    try {
      if (wrapper) {
        container.appendChild(wrapper)
        container.setAttribute('data-aiia-fallback-icon', variant)

        if (preferActivityIcon && !noContentFallbackSvgMarkup) {
          loadNoContentFallbackSvgMarkup()
            .then(markup => {
              if (!markup) return
              try {
                if (!wrapper.isConnected) return
              } catch (_) {

              }
              try {
                const cur = container.getAttribute('data-aiia-fallback-icon') || ''
                if (cur !== variant) return
              } catch (_) {

              }
              try {
                wrapper.innerHTML = markup
              } catch (_) {

              }
              try {
                if (!noContentFallbackSvgAppliedLogged) {
                  noContentFallbackSvgAppliedLogged = true
                  log('no-content fallback icon: replaced with activity-icon.svg')
                }
              } catch (_) {

              }
            })
            .catch(() => {

            })
        }
      } else {

        container.textContent = t('ui.noContent.waiting')
      }
    } catch (_) {

    }
  }

  function scheduleNoContentLottieRetry(reason) {
    if (noContentLottieDisposed) return
    if (!isNoContentVisible()) return
    if (noContentHourglassAnimation) return
    clearNoContentLottieTimers()

    const a = Math.max(0, Math.min(20, Math.floor(noContentLottieRetryAttempt)))
    const base = NO_CONTENT_LOTTIE_RETRY_MIN_MS * Math.pow(1.7, a)
    const cap = NO_CONTENT_LOTTIE_RETRY_MAX_MS
    const delay = Math.max(
      NO_CONTENT_LOTTIE_RETRY_MIN_MS,
      Math.min(cap, Math.round(base + base * 0.15 * Math.random()))
    )
    noContentLottieRetryAttempt = a + 1

    try {
      noContentLottieRetryTimer = setTimeout(() => {
        try {
          initNoContentHourglassAnimation()
        } catch (_) {

        }
      }, delay)
    } catch (_) {

    }
    if (reason) {
      try {
        log(`no-content lottie retry scheduled in ${delay}ms: ${String(reason)}`)
      } catch (_) {

      }
    }
  }

  let noContentRecoveryHandlersInstalled = false
  let noContentStateObserver = null
  let noContentOnlineHandler = null
  let noContentVisibilityHandler = null
  function installNoContentLottieRecoveryHandlers() {
    if (noContentRecoveryHandlersInstalled) return
    noContentRecoveryHandlersInstalled = true
    noContentLottieDisposed = false

    try {
      noContentOnlineHandler = () => {
        if (noContentLottieDisposed) return
        if (!isNoContentVisible()) return
        if (noContentHourglassAnimation) return
        scheduleNoContentLottieRetry('online')
      }
      window.addEventListener('online', noContentOnlineHandler)
    } catch (_) {

    }

    try {
      noContentVisibilityHandler = () => {
        if (noContentLottieDisposed) return
        if (document.hidden) return
        if (!isNoContentVisible()) return
        if (noContentHourglassAnimation) return
        scheduleNoContentLottieRetry('visibilitychange')
      }
      document.addEventListener('visibilitychange', noContentVisibilityHandler)
    } catch (_) {

    }

    try {
      const el = document.getElementById('noContentState')
      if (el && typeof MutationObserver !== 'undefined') {
        noContentStateObserver = new MutationObserver(() => {
          if (isNoContentVisible()) {
            if (!noContentHourglassAnimation) {

              initNoContentHourglassAnimation()
            }
          } else {
            destroyNoContentHourglassAnimation()
            noContentLottieRetryAttempt = 0
          }
        })
        noContentStateObserver.observe(el, { attributes: true, attributeFilter: ['class'] })
      }
    } catch (_) {

    }
  }

  function disposeNoContentLottieRecoveryHandlers() {
    noContentLottieDisposed = true
    clearNoContentLottieTimers()

    try {
      if (noContentOnlineHandler) {
        window.removeEventListener('online', noContentOnlineHandler)
      }
    } catch (_) {

    } finally {
      noContentOnlineHandler = null
    }

    try {
      if (noContentVisibilityHandler) {
        document.removeEventListener('visibilitychange', noContentVisibilityHandler)
      }
    } catch (_) {

    } finally {
      noContentVisibilityHandler = null
    }

    try {
      if (noContentStateObserver) {
        noContentStateObserver.disconnect()
      }
    } catch (_) {

    } finally {
      noContentStateObserver = null
    }

    destroyNoContentHourglassAnimation()
    noContentLottieInitInFlight = false
    noContentRecoveryHandlersInstalled = false
  }

  function ensureLottieLoaded() {
    const isReady = () => {
      try {
        return typeof lottie !== 'undefined' && lottie && typeof lottie.loadAnimation === 'function'
      } catch (_) {
        return false
      }
    }
    if (isReady()) return Promise.resolve(true)
    if (!LOTTIE_LIB_URL) return Promise.resolve(false)
    if (lottieLoadPromise) return lottieLoadPromise

    lottieLoadPromise = loadLazyScriptOnce(
      'aiia-lottie-script',
      LOTTIE_LIB_URL,
      isReady,
      NO_CONTENT_LOTTIE_TIMEOUT_MS
    ).then(ok => {

      if (!ok) lottieLoadPromise = null
      return ok
    })

    return lottieLoadPromise
  }

  let markedLoadPromise = null
  let prismLoadPromise = null
  let markedOptionsConfigured = false

  function configureMarkedOnce() {
    if (markedOptionsConfigured) return
    if (typeof marked === 'undefined' || !marked || typeof marked.setOptions !== 'function') return
    try {

      if (typeof marked.use === 'function') {
        marked.use({

          renderer: {
            html() {
              return ''
            }
          }
        })
      }
      marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
      })
      markedOptionsConfigured = true
    } catch (e) {

    }
  }

  function ensureMarkedLoaded() {
    try {
      if (typeof marked !== 'undefined' && marked && typeof marked.parse === 'function') {
        configureMarkedOnce()
        return Promise.resolve(true)
      }
    } catch (e) {

    }

    if (!MARKED_JS_URL) {
      return Promise.resolve(false)
    }
    if (markedLoadPromise) return markedLoadPromise

    markedLoadPromise = loadLazyScriptOnce(
      'aiia-marked-script',
      MARKED_JS_URL,
      () => {
        if (typeof marked !== 'undefined' && marked && typeof marked.parse === 'function') {
          configureMarkedOnce()
          return true
        }
        return false
      },
      5000
    )

    return markedLoadPromise
  }

  function ensurePrismLoaded() {
    try {
      if (typeof Prism !== 'undefined' && Prism && typeof Prism.highlightAllUnder === 'function') {
        return Promise.resolve(true)
      }
    } catch (e) {

    }

    if (!PRISM_JS_URL) {
      return Promise.resolve(false)
    }
    if (prismLoadPromise) return prismLoadPromise

    prismLoadPromise = new Promise(resolve => {
      try {

        try {
          if (typeof globalThis !== 'undefined') {
            globalThis.Prism = globalThis.Prism || {}
            globalThis.Prism.manual = true
          } else if (typeof window !== 'undefined') {
            window.Prism = window.Prism || {}
            window.Prism.manual = true
          }
        } catch (e) {

        }

        loadLazyScriptOnce(
          'aiia-prism-script',
          PRISM_JS_URL,
          () =>
            typeof Prism !== 'undefined' && Prism && typeof Prism.highlightAllUnder === 'function',
          5000
        ).then(resolve)
      } catch (e) {
        resolve(false)
      }
    })

    return prismLoadPromise
  }

  let notifyCoreLoadPromise = null
  let settingsUiLoadPromise = null

  function getNotifyCoreModule() {
    try {
      if (typeof globalThis !== 'undefined' && globalThis && globalThis.AIIAWebviewNotifyCore) {
        return globalThis.AIIAWebviewNotifyCore
      }
    } catch (e) {

    }
    try {
      if (typeof window !== 'undefined' && window && window.AIIAWebviewNotifyCore) {
        return window.AIIAWebviewNotifyCore
      }
    } catch (e) {

    }
    return null
  }

  function getSettingsUiModule() {
    try {
      if (typeof globalThis !== 'undefined' && globalThis && globalThis.AIIAWebviewSettingsUi) {
        return globalThis.AIIAWebviewSettingsUi
      }
    } catch (e) {

    }
    try {
      if (typeof window !== 'undefined' && window && window.AIIAWebviewSettingsUi) {
        return window.AIIAWebviewSettingsUi
      }
    } catch (e) {

    }
    return null
  }

  function ensureNotifyCoreLoaded() {
    try {
      const existing = getNotifyCoreModule()
      if (existing && typeof existing.showNewTaskNotification === 'function') {
        return Promise.resolve(true)
      }
    } catch (e) {

    }

    if (!NOTIFY_CORE_JS_URL) return Promise.resolve(false)
    if (notifyCoreLoadPromise) return notifyCoreLoadPromise

    notifyCoreLoadPromise = loadLazyScriptOnce(
      'aiia-notify-core-script',
      NOTIFY_CORE_JS_URL,
      () => {
        const mod = getNotifyCoreModule()
        return !!(mod && typeof mod.showNewTaskNotification === 'function')
      },
      5000
    )

    return notifyCoreLoadPromise
  }

  function ensureSettingsUiLoaded() {
    try {
      const existing = getSettingsUiModule()
      if (existing && typeof existing.openSettings === 'function') {
        return Promise.resolve(true)
      }
    } catch (e) {

    }

    if (!SETTINGS_UI_JS_URL) return Promise.resolve(false)
    if (settingsUiLoadPromise) return settingsUiLoadPromise

    settingsUiLoadPromise = loadLazyScriptOnce(
      'aiia-settings-ui-script',
      SETTINGS_UI_JS_URL,
      () => {
        const mod = getSettingsUiModule()
        return !!(mod && typeof mod.openSettings === 'function')
      },
      5000
    )

    return settingsUiLoadPromise
  }

  function scheduleLowPriorityWork(fn, timeoutMs) {
    try {
      const work = () => {
        try {
          fn()
        } catch (e) {

        }
      }
      if (typeof requestIdleCallback === 'function') {
        requestIdleCallback(work, {
          timeout: typeof timeoutMs === 'number' && Number.isFinite(timeoutMs) ? timeoutMs : 600
        })
      } else if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(() => setTimeout(work, 0))
      } else {
        setTimeout(work, 0)
      }
    } catch (e) {
      try {
        setTimeout(() => fn(), 0)
      } catch (_) {

      }
    }
  }

  let __aiiaBootSkeletonHideStarted = false
  function hideBootSkeleton() {
    if (__aiiaBootSkeletonHideStarted) return
    __aiiaBootSkeletonHideStarted = true
    try {
      const el = document.getElementById('aiiaBootSkeleton')
      if (!el) return
      if (el.hasAttribute('hidden')) return

      const commitHide = () => {
        try {
          el.setAttribute('hidden', '')
        } catch (_) {

        }
      }
      try {
        el.classList.add('aiia-boot-skeleton--leaving')
      } catch (_) {

        commitHide()
        return
      }

      setTimeout(commitHide, 200)
    } catch (_) {

    }
  }

  function loadNoContentLottieData() {
    if (INLINE_NO_CONTENT_LOTTIE_DATA) {
      try {
        if (!noContentLottieInlineLogged) {
          noContentLottieInlineLogged = true
          log('no-content lottie data: using inline sprout.json')
        }
      } catch (_) {

      }
      return Promise.resolve(INLINE_NO_CONTENT_LOTTIE_DATA)
    }
    if (noContentLottieDataPromise) return noContentLottieDataPromise
    if (!NO_CONTENT_LOTTIE_JSON_URL) {
      return Promise.resolve(null)
    }
    noContentLottieDataPromise = (async () => {
      try {
        const resp = await fetch(NO_CONTENT_LOTTIE_JSON_URL, { cache: 'force-cache' })
        if (!resp.ok) return null
        const data = await resp.json()
        return data && typeof data === 'object' ? data : null
      } catch (_) {
        return null
      }
    })().then(data => {

      if (!data) noContentLottieDataPromise = null
      return data
    })
    return noContentLottieDataPromise
  }

  function initNoContentHourglassAnimation() {
    if (noContentLottieDisposed) return
    const container = document.getElementById('hourglass-lottie')
    if (!container) return

    if (noContentHourglassAnimation) {
      updateNoContentHourglassColor()
      return
    }
    if (noContentLottieInitInFlight) return

    renderNoContentFallbackIcon(container)
    noContentLottieInitInFlight = true

    Promise.all([ensureLottieLoaded(), loadNoContentLottieData()])
      .then(([okLib, data]) => {
        if (noContentLottieDisposed) return
        if (!okLib || !data) {
          if (!lottieInitWarned) {
            lottieInitWarned = true
            log('Lottie not loaded (falling back to SVG)')
          }
          scheduleNoContentLottieRetry(!okLib ? 'lottie lib not ready' : 'lottie data missing')
          return
        }

        const noContentState = document.getElementById('noContentState')
        if (noContentState && noContentState.classList.contains('hidden')) {
          return
        }

        try {
          container.textContent = ''
        } catch (_) {

        }

        try {
          if (noContentLottieDomLoadedTimer) clearTimeout(noContentLottieDomLoadedTimer)
        } catch (_) {

        } finally {
          noContentLottieDomLoadedTimer = null
        }

        try {
          noContentHourglassAnimation = lottie.loadAnimation({
            container: container,
            renderer: 'svg',
            loop: true,
            autoplay: true,
            animationData: data,
            rendererSettings: { preserveAspectRatio: 'xMidYMid meet' }
          })
        } catch (e) {
          renderNoContentFallbackIcon(container)
          destroyNoContentHourglassAnimation()
          scheduleNoContentLottieRetry('lottie.loadAnimation throw')
          return
        }

        try {
          noContentLottieDomLoadedTimer = setTimeout(() => {
            try {
              renderNoContentFallbackIcon(container)
              if (!lottieInitWarned) {
                lottieInitWarned = true
                log('Lottie load timeout (falling back to SVG)')
              }
            } catch (_) {

            }
            destroyNoContentHourglassAnimation()
            scheduleNoContentLottieRetry('DOMLoaded timeout')
          }, NO_CONTENT_LOTTIE_TIMEOUT_MS)
        } catch (_) {

        }

        noContentHourglassAnimation.addEventListener('DOMLoaded', () => {
          try {
            if (noContentLottieDomLoadedTimer) clearTimeout(noContentLottieDomLoadedTimer)
          } catch (_) {

          } finally {
            noContentLottieDomLoadedTimer = null
          }
          noContentLottieRetryAttempt = 0
          updateNoContentHourglassColor()
        })

        noContentHourglassAnimation.addEventListener('error', () => {
          try {
            renderNoContentFallbackIcon(container)
          } catch (_) {

          }
          if (!lottieInitWarned) {
            lottieInitWarned = true
            log('Lottie load failed (falling back to SVG)')
          }
          destroyNoContentHourglassAnimation()
          scheduleNoContentLottieRetry('lottie error event')
        })
      })
      .catch(() => {
        if (noContentLottieDisposed) return
        scheduleNoContentLottieRetry('init promise rejected')
      })
      .finally(() => {
        noContentLottieInitInFlight = false
      })
  }

  let currentConfig = null
  let selectedOptions = []
  let uploadedImages = []
  let pendingImageUploadCounts = {}
  let textareaManualRows = null
  let countdownTimer = null

  let autoSubmitAttempted = {}

  let lastFeedbackTypingAtMs = 0
  let typingAutoExtendInFlight = false
  let typingAutoExtendBlockedTasks = {}
  const TYPING_HOLD_IDLE_MS = 10 * 1000
  const TYPING_HOLD_TRIGGER_S = 15

  let pendingInputFocusAtMs = 0
  const PENDING_FOCUS_FRESH_MS = 15 * 1000
  let pollingTimer = null
  let remainingSeconds = 0
  let allTasks = []
  let activeTaskId = null
  let tabCountdownTimers = {}
  let tabCountdownTickerTimer = null
  let tabCountdownVisibilityHandlerInstalled = false
  let tabCountdownRemaining = {}

  let serverTimeOffset = 0
  let taskDeadlines = {}

  let feedbackPrompts = {
    resubmit_prompt: '',
    prompt_suffix: ''
  }

  let taskTextareaContents = {}
  let taskOptionsStates = {}
  let taskImages = {}

  let taskYesnoSelections = {}

  const UI_STATE_VERSION = 1
  const UI_STATE_SAVE_DEBOUNCE_MS = 250
  const UI_STATE_TEXT_LIMIT_CHARS = 200000
  let uiStateSaveTimer = null

  function safeGetUiState() {
    try {
      if (vscode && typeof vscode.getState === 'function') {
        return vscode.getState()
      }
    } catch (e) {

    }
    return null
  }

  function safeSetUiState(nextState) {
    try {
      if (vscode && typeof vscode.setState === 'function') {
        vscode.setState(nextState)
      }
    } catch (e) {

    }
  }

  function trimTextareaContents(contents) {
    try {
      const src = contents && typeof contents === 'object' ? contents : {}
      const out = {}
      let budget = UI_STATE_TEXT_LIMIT_CHARS
      for (const taskId in src) {
        if (!Object.prototype.hasOwnProperty.call(src, taskId)) continue
        if (budget <= 0) break
        const text = src[taskId]
        if (typeof text !== 'string' || !text) continue
        if (text.length <= budget) {
          out[taskId] = text
          budget -= text.length
        } else {
          out[taskId] = text.slice(0, Math.max(0, budget))
          budget = 0
        }
      }
      return out
    } catch (e) {
      return {}
    }
  }

  function restorePersistedUiState() {
    const s = safeGetUiState()
    if (!s || s.v !== UI_STATE_VERSION) return

    try {
      if (s.taskTextareaContents && typeof s.taskTextareaContents === 'object') {
        taskTextareaContents = { ...s.taskTextareaContents }
      }
      if (s.taskOptionsStates && typeof s.taskOptionsStates === 'object') {
        taskOptionsStates = { ...s.taskOptionsStates }
      }
      if (s.taskYesnoSelections && typeof s.taskYesnoSelections === 'object') {
        taskYesnoSelections = { ...s.taskYesnoSelections }
      }
      if (typeof s.activeTaskId === 'string') {
        activeTaskId = s.activeTaskId || null
      }
      if (typeof s.textareaManualRows === 'number' && Number.isFinite(s.textareaManualRows)) {
        textareaManualRows = Math.max(2, Math.floor(s.textareaManualRows))
      }
    } catch (e) {

    }
  }

  function schedulePersistUiState() {
    if (!vscode || typeof vscode.setState !== 'function') return
    if (uiStateSaveTimer) return
    uiStateSaveTimer = setTimeout(() => {
      uiStateSaveTimer = null
      safeSetUiState({
        v: UI_STATE_VERSION,
        activeTaskId: activeTaskId || '',
        taskTextareaContents: trimTextareaContents(taskTextareaContents),
        taskOptionsStates: taskOptionsStates || {},
        taskYesnoSelections: taskYesnoSelections || {},

        textareaManualRows:
          typeof textareaManualRows === 'number' && Number.isFinite(textareaManualRows)
            ? Math.max(2, Math.floor(textareaManualRows))
            : null,
        savedAt: Date.now()
      })
    }, UI_STATE_SAVE_DEBOUNCE_MS)
  }

  restorePersistedUiState()

  let submitBtnDefaultHtml = null
  const SUBMIT_BTN_FALLBACK_HTML =
    '<svg class="btn-icon submit-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" aria-hidden="true" focusable="false"><path d="M19.26 9.77C19.91 9.08 20.92 8.91 21.73 9.32L21.89 9.40L21.94 9.43L22.19 9.63C22.20 9.64 22.22 9.65 22.23 9.66L44.63 30.46C45.05 30.86 45.30 31.42 45.30 32.00C45.30 32.44 45.16 32.86 44.91 33.21C44.90 33.23 44.89 33.24 44.88 33.26L44.66 33.50C44.65 33.52 44.64 33.53 44.63 33.54L22.23 54.34C21.38 55.13 20.05 55.08 19.26 54.23C18.47 53.38 18.52 52.05 19.37 51.26L40.12 32.00L19.37 12.74C19.36 12.73 19.35 12.72 19.34 12.70L19.12 12.46C19.11 12.45 19.10 12.43 19.09 12.42C18.52 11.62 18.57 10.52 19.26 9.77Z" fill="currentColor" /></svg>'
  const SUBMIT_BTN_SPINNER_HTML =
    '<svg class="btn-icon spinner-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" opacity="0.25"></circle><path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path></svg>'

  let clipboardRequestId = null

  let submitInFlight = false
  let submitBackoffUntilMs = 0
  let submitBackoffTimer = null

  const POLL_BASE_MS = 2000
  const POLL_MAX_MS = 30000
  const POLL_SSE_FALLBACK_MS = 30000
  const POLL_IDLE_MS = 8000
  let pollBackoffMs = POLL_BASE_MS
  let pollSuggestedDelayMs = null
  let pollAbortController = null
  let pollingInFlight = false
  let pollingVisibilityHandlerInstalled = false

  let pollingEnabled = false
  let pollingToken = 0
  let pollingRunId = 0
  let activePollingRunId = 0

  let _sseSource = null
  let _sseConnected = false
  let _sseReconnectTimer = null
  let _sseReconnectDelay = 1000
  let _sseDebounceTimer = null

  let _lastEventId = null

  let lastTasksHash = ''
  let lastTaskIds = new Set()

  let hasInitializedTaskIdTracking = false
  let lastCountdownTaskId = null

  function getNextBackoffMs(currentMs) {
    const next = Math.min(POLL_MAX_MS, Math.round(currentMs * 1.7))
    const jitter = Math.round(next * 0.1 * Math.random())
    return next + jitter
  }

  function _connectSSE() {
    if (typeof EventSource === 'undefined') return
    if (_sseSource) {
      try {
        _sseSource.close()
      } catch (_) {

      }
      _sseSource = null
    }

    let sseUrl = SERVER_URL + '/api/events'
    if (_lastEventId) {
      const sep = sseUrl.indexOf('?') >= 0 ? '&' : '?'
      sseUrl += sep + 'last_event_id=' + encodeURIComponent(_lastEventId)
    }
    const source = new EventSource(sseUrl)
    _sseSource = source

    source.onopen = function () {
      if (_sseSource !== source) return
      _sseConnected = true
      _sseReconnectDelay = 1000
      log('SSE connected, polling degraded to fallback mode (30s)')
      pollBackoffMs = POLL_SSE_FALLBACK_MS
      if (pollingTimer) {
        clearTimeout(pollingTimer)
        scheduleNextPoll(POLL_SSE_FALLBACK_MS, pollingToken)
      }
    }

    source.addEventListener('task_changed', function (e) {
      if (_sseSource !== source) return

      if (e && typeof e.lastEventId === 'string' && e.lastEventId !== '') {
        _lastEventId = e.lastEventId
      }
      try {
        const detail = JSON.parse(e.data)
        log(
          'SSE task_changed: ' +
            detail.task_id +
            ' ' +
            detail.old_status +
            ' → ' +
            detail.new_status
        )
      } catch (_) {

      }
      if (_sseDebounceTimer) clearTimeout(_sseDebounceTimer)
      _sseDebounceTimer = setTimeout(function () {
        _sseDebounceTimer = null
        pollAllData('sse')
      }, 80)
    })

    source.addEventListener('gap_warning', function (e) {
      if (_sseSource !== source) return
      log('SSE gap_warning received, fetching tasks for full resync')
      try {
        const detail = JSON.parse(e.data)
        log('SSE gap_warning detail: ' + JSON.stringify(detail))
      } catch (_) {

      }
      if (_sseDebounceTimer) clearTimeout(_sseDebounceTimer)
      _sseDebounceTimer = setTimeout(function () {
        _sseDebounceTimer = null
        pollAllData('sse-gap')
      }, 0)
    })

    source.onerror = function () {
      if (_sseSource !== source) return
      _sseConnected = false
      try {
        source.close()
      } catch (_) {

      }
      _sseSource = null
      log('SSE disconnected, falling back to short-interval polling, reconnecting in ' + _sseReconnectDelay / 1000 + 's')
      pollBackoffMs = POLL_BASE_MS
      if (pollingTimer) {
        clearTimeout(pollingTimer)
        scheduleNextPoll(0, pollingToken)
      }
      if (_sseReconnectTimer) clearTimeout(_sseReconnectTimer)
      _sseReconnectTimer = setTimeout(function () {
        if (!pollingEnabled) return
        if (typeof document !== 'undefined' && document.hidden) return
        _connectSSE()
      }, _sseReconnectDelay)
      _sseReconnectDelay = Math.min(30000, _sseReconnectDelay * 2)
    }
  }

  function _disconnectSSE() {
    if (_sseReconnectTimer) {
      clearTimeout(_sseReconnectTimer)
      _sseReconnectTimer = null
    }
    if (_sseDebounceTimer) {
      clearTimeout(_sseDebounceTimer)
      _sseDebounceTimer = null
    }
    if (_sseSource) {
      try {
        _sseSource.close()
      } catch (_) {

      }
      _sseSource = null
    }
    _sseConnected = false
  }

  function installPollingVisibilityHandler() {
    if (pollingVisibilityHandlerInstalled) return
    pollingVisibilityHandlerInstalled = true
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopPolling()
      } else {

        startPolling()
      }
    })
  }

  function log(message) {
    try {
      vscode.postMessage({ type: 'log', level: 'debug', message: String(message) })
    } catch (e) {

    }
  }

  function logError(message) {
    const text = String(message || '')
    try {
      vscode.postMessage({ type: 'log', level: 'error', message: text })
    } catch (e) {

    }
    try {
      vscode.postMessage({ type: 'error', message: text })
    } catch (e) {

    }
    try {
      showToast(text, { kind: 'error', timeoutMs: 2600, dedupeKey: 'err:' + text.slice(0, 120) })
    } catch (e) {

    }
  }

  var toastDedupeMap = new Map()
  var TOAST_DEDUPE_WINDOW_MS = 700
  var TOAST_MAX_VISIBLE = 5
  var TOAST_EXIT_DURATION_MS = 200

  function showToast(message, options) {
    var host = document.getElementById('toastHost')
    if (!host) return
    var text = String(message || '').trim()
    if (!text) return

    var kindRaw = options && options.kind ? String(options.kind) : 'info'
    var kind = kindRaw === 'success' || kindRaw === 'warn' || kindRaw === 'error' ? kindRaw : 'info'
    var timeoutMsRaw = options && typeof options.timeoutMs === 'number' ? options.timeoutMs : 1800
    var timeoutMs = Math.max(800, Math.min(8000, Math.floor(timeoutMsRaw)))
    var dedupeKey = options && options.dedupeKey ? String(options.dedupeKey) : kind + ':' + text

    var now = Date.now()
    if (dedupeKey) {
      var lastTime = toastDedupeMap.get(dedupeKey)
      if (lastTime && now - lastTime < TOAST_DEDUPE_WINDOW_MS) {
        return
      }
      toastDedupeMap.set(dedupeKey, now)
      if (toastDedupeMap.size > 50) {
        toastDedupeMap.forEach(function (v, k) {
          if (now - v > TOAST_DEDUPE_WINDOW_MS * 2) toastDedupeMap.delete(k)
        })
      }
    }

    var existing = host.querySelectorAll('.toast:not(.toast-removing)')
    if (existing.length >= TOAST_MAX_VISIBLE) {
      try {
        var oldest = existing[0]
        if (oldest && oldest._toastRemove) oldest._toastRemove()
      } catch (e) {

      }
    }

    var el = document.createElement('div')
    el.className = 'toast ' + kind
    el.textContent = text
    el.setAttribute('role', 'status')
    el.setAttribute('aria-live', 'polite')

    var removed = false
    var remainingMs = timeoutMs
    var timerStartedAt = 0
    var autoRemoveTimer = null

    var remove = function () {
      if (removed) return
      removed = true
      if (autoRemoveTimer) {
        clearTimeout(autoRemoveTimer)
        autoRemoveTimer = null
      }
      try {
        el.classList.remove('show')
        el.classList.add('toast-removing')
      } catch (e) {

      }
      setTimeout(function () {
        try {
          if (el.parentNode) el.parentNode.removeChild(el)
        } catch (e) {

        }
      }, TOAST_EXIT_DURATION_MS)
    }

    var startTimer = function () {
      if (removed || remainingMs <= 0) {
        if (!removed) remove()
        return
      }
      timerStartedAt = Date.now()
      autoRemoveTimer = setTimeout(remove, remainingMs)
    }

    var pauseTimer = function () {
      if (removed || !autoRemoveTimer) return
      clearTimeout(autoRemoveTimer)
      autoRemoveTimer = null
      var elapsed = Date.now() - timerStartedAt
      remainingMs = Math.max(0, remainingMs - elapsed)
    }

    el._toastRemove = remove
    el.addEventListener('click', function () {
      remove()
    })
    el.addEventListener('mouseenter', pauseTimer)
    el.addEventListener('mouseleave', startTimer)

    host.appendChild(el)
    requestAnimationFrame(function () {
      try {
        el.classList.add('show')
      } catch (e) {

      }
    })
    startTimer()
  }

  try {
    if (typeof globalThis !== 'undefined') globalThis.__AIIA_showToast = showToast
  } catch (e) {

  }

  const FEEDBACK_TEXTAREA_MIN_HEIGHT_PX = 80
  const FEEDBACK_TEXTAREA_MAX_HEIGHT_PX = 300

  function clampInt(n, min, max) {
    const x = Number.isFinite(n) ? Math.floor(n) : NaN
    if (!Number.isFinite(x)) return min
    return Math.max(min, Math.min(max, x))
  }

  function getTextareaMetrics(textarea) {
    try {
      const cs = window.getComputedStyle(textarea)
      let lineHeight = parseFloat(cs.lineHeight)
      if (!Number.isFinite(lineHeight) || lineHeight <= 0) {
        const fs = parseFloat(cs.fontSize)
        lineHeight = Number.isFinite(fs) && fs > 0 ? fs * 1.65 : 20
      }

      const paddingTop = parseFloat(cs.paddingTop) || 0
      const paddingBottom = parseFloat(cs.paddingBottom) || 0
      const borderTop = parseFloat(cs.borderTopWidth) || 0
      const borderBottom = parseFloat(cs.borderBottomWidth) || 0
      const verticalExtras = paddingTop + paddingBottom + borderTop + borderBottom
      return { lineHeight, verticalExtras }
    } catch (e) {
      return { lineHeight: 20, verticalExtras: 0 }
    }
  }

  function getTextareaRowsBounds(textarea) {
    const { lineHeight, verticalExtras } = getTextareaMetrics(textarea)
    const safeLineHeight = Number.isFinite(lineHeight) && lineHeight > 0 ? lineHeight : 20
    const minRows = Math.max(
      2,
      Math.ceil((FEEDBACK_TEXTAREA_MIN_HEIGHT_PX - verticalExtras) / safeLineHeight)
    )
    const maxRows = Math.max(
      minRows,
      Math.floor((FEEDBACK_TEXTAREA_MAX_HEIGHT_PX - verticalExtras) / safeLineHeight)
    )
    return { lineHeight: safeLineHeight, verticalExtras, minRows, maxRows }
  }

  function autoResizeFeedbackTextarea(textarea) {
    if (!textarea) return
    try {
      const { lineHeight, verticalExtras, minRows, maxRows } = getTextareaRowsBounds(textarea)

      textarea.rows = minRows
      const contentHeight = textarea.scrollHeight || minRows * lineHeight + verticalExtras
      const neededRows = Math.ceil((contentHeight - verticalExtras) / lineHeight)

      let nextRows = clampInt(neededRows, minRows, maxRows)
      if (textareaManualRows && Number.isFinite(textareaManualRows)) {
        nextRows = Math.max(nextRows, textareaManualRows)
      }
      textarea.rows = nextRows
    } catch (e) {

    }
  }

  function postNotificationEvent(event) {
    try {
      vscode.postMessage({ type: 'notify', event: event || {} })
    } catch (e) {

    }
  }

  function postStatusInfo(message, options) {
    postNotificationEvent({
      title: 'AI Intervention Agent',
      message: String(message || ''),
      trigger: 'immediate',
      types: ['vscode'],
      metadata: Object.assign(
        { presentation: 'statusBar', severity: 'info', timeoutMs: 3000 },
        options || {}
      ),
      source: 'webview-ui',
      dedupeKey: message ? 'status:' + String(message).slice(0, 200) : ''
    })
  }

  async function fetchFeedbackPrompts(fetchOptions) {
    let controller = null
    let timeoutId = null
    try {
      const options = fetchOptions ? { ...fetchOptions } : { cache: 'no-store' }
      if (!options.cache) options.cache = 'no-store'

      if (typeof AbortController !== 'undefined') {
        controller = new AbortController()
        options.signal = controller.signal
        timeoutId = setTimeout(() => {
          try {
            controller.abort()
          } catch (e) {

          }
        }, POLL_CONFIG_TIMEOUT_MS)
      }

      const response = await fetch(SERVER_URL + '/api/get-feedback-prompts', options)
      if (!response.ok) return feedbackPrompts

      const payload = await response.json()
      if (payload && payload.status === 'success' && payload.config) {
        feedbackPrompts = {
          resubmit_prompt: payload.config.resubmit_prompt || feedbackPrompts.resubmit_prompt,
          prompt_suffix: payload.config.prompt_suffix || feedbackPrompts.prompt_suffix
        }
      }
    } catch (e) {
      log('Fetch feedback prompts failed, using cached values: ' + (e && e.message ? e.message : String(e)))
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
    }
    return feedbackPrompts
  }

  function buildMarkdownCodeFence(code, lang) {
    try {
      const normalized = String(code || '').replace(/\r\n?/g, '\n')
      if (!normalized.trim()) return null

      const BACKTICK = String.fromCharCode(96)
      const runs = normalized.match(/`+/g) || []
      const longestRun = runs.reduce((max, run) => Math.max(max, run.length), 0)
      const fence = BACKTICK.repeat(Math.max(3, longestRun + 1))
      const fenceHead = lang ? fence + String(lang) : fence
      const codeBody = normalized.endsWith('\n') ? normalized : normalized + '\n'

      return fenceHead + '\n' + codeBody + fence + '\n'
    } catch (e) {
      return null
    }
  }

  function insertCodeBlockIntoFeedbackTextarea(code, lang) {
    try {
      const textarea = document.getElementById('feedbackText')
      if (!textarea) return false

      const codeBlockBody = buildMarkdownCodeFence(code, lang)
      if (!codeBlockBody) return false

      let cursorPos = 0
      try {
        cursorPos = typeof textarea.selectionStart === 'number' ? textarea.selectionStart : 0
      } catch (e) {
        cursorPos = 0
      }

      const value = textarea.value || ''
      const before = value.slice(0, cursorPos)
      const after = value.slice(cursorPos)
      const needsLeadingNewline = cursorPos > 0 && !before.endsWith('\n')
      const needsTrailingNewline = after.length > 0 && !after.startsWith('\n')
      const codeBlock =
        (needsLeadingNewline ? '\n' : '') + codeBlockBody + (needsTrailingNewline ? '\n' : '')

      textarea.value = before + codeBlock + after

      const newCursor = before.length + codeBlock.length
      try {
        textarea.setSelectionRange(newCursor, newCursor)
        textarea.focus()
      } catch (e) {

      }

      if (activeTaskId && typeof taskTextareaContents !== 'undefined') {
        taskTextareaContents[activeTaskId] = textarea.value || ''
      }
      autoResizeFeedbackTextarea(textarea)
      schedulePersistUiState()
      return true
    } catch (e) {
      return false
    }
  }

  function setInsertCodeBtnDisabled(disabled) {
    const btn = document.getElementById('insertCodeBtn')
    if (btn) btn.disabled = !!disabled
  }

  function requestInsertCodeFromClipboard() {

    if (clipboardRequestId) return
    clipboardRequestId = String(Date.now()) + '-' + Math.random().toString(16).slice(2)
    setInsertCodeBtnDisabled(true)
    vscode.postMessage({ type: 'requestClipboardText', requestId: clipboardRequestId })

    setTimeout(() => {
      if (clipboardRequestId) {
        clipboardRequestId = null
        setInsertCodeBtnDisabled(false)
      }
    }, 2000)
  }

  function handleClipboardTextMessage(message) {
    try {
      const ok = !!(message && message.success)
      const text = message && message.text ? String(message.text) : ''

      const reqId = message && message.requestId ? String(message.requestId) : ''
      if (clipboardRequestId && (!reqId || reqId === clipboardRequestId)) {
        clipboardRequestId = null
        setInsertCodeBtnDisabled(false)
      }

      if (!ok || !text.trim()) {
        const err = message && message.error ? String(message.error) : t('ui.clipboard.empty')
        vscode.postMessage({ type: 'showInfo', message: err })
        return
      }

      const inserted = insertCodeBlockIntoFeedbackTextarea(text, '')
      if (!inserted) {
        vscode.postMessage({ type: 'showInfo', message: t('ui.clipboard.noCode') })
        return
      }

      vscode.postMessage({ type: 'showInfo', message: t('ui.clipboard.inserted') })
    } catch (e) {
      vscode.postMessage({
        type: 'showInfo',
        message: t('ui.clipboard.insertFailed', { reason: e && e.message ? e.message : String(e) })
      })
      clipboardRequestId = null
      setInsertCodeBtnDisabled(false)
    }
  }

  async function init() {
    installHostThemeObserver()
    setupEventListeners()

    updateServerStatus(false)

    Promise.resolve()
      .then(() => checkServerStatus())
      .then(ok => {
        if (!ok) {
          hideTabs()
          showNoContent()
        }
      })
      .catch(() => {
        hideTabs()
        showNoContent()
      })
    startPolling()

    scheduleLowPriorityWork(() => {
      Promise.resolve()
        .then(() => ensureNotifyCoreLoaded())
        .then(ok => {
          if (!ok) return
          const mod = getNotifyCoreModule()
          if (mod && typeof mod.refreshNotificationSettingsFromServer === 'function') {
            return mod.refreshNotificationSettingsFromServer({ force: true, silent: true })
          }
        })
        .catch(() => {

        })
    }, 1200)

    setTimeout(() => {
      try {
        const loading = document.getElementById('loadingState')
        const noContent = document.getElementById('noContentState')
        const form = document.getElementById('feedbackForm')
        if (!loading || !noContent || !form) return
        const isLoadingVisible = !loading.classList.contains('hidden')
        const isNoContentHidden = noContent.classList.contains('hidden')
        const isFormHidden = form.classList.contains('hidden')
        if (isLoadingVisible && isNoContentHidden && isFormHidden) {
          hideTabs()
          showNoContent()
        }
      } catch (e) {

      }
    }, 3000)
    vscode.postMessage({ type: 'ready' })

    hideBootSkeleton()
  }

  function setupEventListeners() {
    try {
      const submitBtn = document.getElementById('submitBtn')
      if (submitBtn) {
        if (submitBtnDefaultHtml === null) {
          submitBtnDefaultHtml = submitBtn.innerHTML
        }
        submitBtn.addEventListener('click', submitFeedback)
      }

      const insertCodeBtn = document.getElementById('insertCodeBtn')
      if (insertCodeBtn) {
        insertCodeBtn.addEventListener('click', requestInsertCodeFromClipboard)
      }

      const countdownExtendBtn = document.getElementById('countdownExtendBtn')
      if (countdownExtendBtn) {
        countdownExtendBtn.addEventListener('click', handleCountdownExtendClick)
      }
      const countdownFreezeBtn = document.getElementById('countdownFreezeBtn')
      if (countdownFreezeBtn) {
        countdownFreezeBtn.addEventListener('click', handleCountdownFreezeClick)
      }

      const yesnoYesBtn = document.getElementById('yesnoYesBtn')
      if (yesnoYesBtn) {
        yesnoYesBtn.addEventListener('click', () => handleYesnoToggleClick('yes'))
      }
      const yesnoNoBtn = document.getElementById('yesnoNoBtn')
      if (yesnoNoBtn) {
        yesnoNoBtn.addEventListener('click', () => handleYesnoToggleClick('no'))
      }

      const uploadBtn = document.getElementById('uploadBtn')
      const imageInput = document.getElementById('imageInput')

      if (uploadBtn && imageInput) {
        uploadBtn.addEventListener('click', () => {
          imageInput.click()
        })
        imageInput.addEventListener('change', handleImageSelect)
      }

      const textarea = document.getElementById('feedbackText')
      if (textarea) {
        textarea.addEventListener('paste', handlePaste)

        textarea.addEventListener('input', () => {

          lastFeedbackTypingAtMs = Date.now()
          if (activeTaskId) {
            taskTextareaContents[activeTaskId] = textarea.value || ''
          }
          autoResizeFeedbackTextarea(textarea)
          schedulePersistUiState()
        })

        textarea.addEventListener('keydown', e => {
          const isMac = isMacLikePlatform()
          const ctrlOrCmd = isMac ? e.metaKey : e.ctrlKey
          const key = e && e.key ? String(e.key) : ''
          const isEnter = key === 'Enter' || key === 'NumpadEnter'
          if (e && e.isComposing) return
          if (ctrlOrCmd && isEnter) {
            e.preventDefault()
            submitFeedback()
          }
        })

        autoResizeFeedbackTextarea(textarea)
      }

      const optionsContainerEl = document.getElementById('optionsContainer')
      if (optionsContainerEl) {
        optionsContainerEl.addEventListener('change', e => {
          if (!activeTaskId) return
          const checkboxes = optionsContainerEl.querySelectorAll('input[type="checkbox"]')
          const states = {}
          checkboxes.forEach((cb, index) => {
            states[index] = !!cb.checked
          })
          taskOptionsStates[activeTaskId] = states
          schedulePersistUiState()
        })
      }

      const settingsBtn = document.getElementById('settingsBtn')
      if (settingsBtn) {
        settingsBtn.addEventListener('click', openSettingsLazy)
      }
      const settingsBtnNoContent = document.getElementById('settingsBtnNoContent')
      if (settingsBtnNoContent) {
        settingsBtnNoContent.addEventListener('click', openSettingsLazy)
      }

      const resizeHandle = document.getElementById('resizeHandle')
      let isResizing = false
      let startY = 0
      let startRows = 0
      let resizeLineHeight = 20
      let resizeMinRows = 2
      let resizeMaxRows = 20

      if (resizeHandle && textarea) {
        resizeHandle.addEventListener('mousedown', e => {
          isResizing = true
          startY = e.clientY
          const bounds = getTextareaRowsBounds(textarea)
          resizeLineHeight = bounds.lineHeight
          resizeMinRows = bounds.minRows
          resizeMaxRows = bounds.maxRows
          startRows = textarea.rows || bounds.minRows
          e.preventDefault()
        })

        resizeHandle.addEventListener('dblclick', e => {
          textareaManualRows = null
          autoResizeFeedbackTextarea(textarea)
          schedulePersistUiState()
          e.preventDefault()
        })
      }

      document.addEventListener('mousemove', e => {
        if (!isResizing || !textarea) return

        const deltaY = startY - e.clientY
        const perRow = resizeLineHeight || 20
        const deltaRows = Math.round(deltaY / perRow)
        const nextRows = clampInt(startRows + deltaRows, resizeMinRows, resizeMaxRows)
        textarea.rows = nextRows
        textareaManualRows = nextRows
      })

      document.addEventListener('mouseup', () => {
        isResizing = false
        if (textarea) {
          schedulePersistUiState()
        }
      })

      log('Event listeners installed')
    } catch (error) {
      log('Install event listeners failed: ' + error.message)
    }
  }

  async function checkServerStatus() {
    let controller = null
    let timeoutId = null
    try {
      const fetchOptions = {
        method: 'GET',
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      }

      if (typeof AbortController !== 'undefined') {
        controller = new AbortController()
        fetchOptions.signal = controller.signal
        timeoutId = setTimeout(() => {
          try {
            controller.abort()
          } catch (e) {

          }
        }, SERVER_STATUS_TIMEOUT_MS)
      }

      const response = await fetch(SERVER_URL + '/api/config', fetchOptions)

      if (response.ok) {
        updateServerStatus(true)
        return true
      } else {
        updateServerStatus(false)
        return false
      }
    } catch (error) {
      const msg =
        error && error.name === 'AbortError'
          ? t('settings.hint.timeout')
          : error && error.message
            ? error.message
            : String(error)
      log('Server connection failed: ' + msg)
      updateServerStatus(false)
      return false
    } finally {
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
    }
  }

  function updateServerStatus(connected) {

    if (typeof updateServerStatus._last === 'boolean' && updateServerStatus._last !== !!connected) {
      showToast(connected ? t('ui.status.connected') : t('ui.status.disconnectedRetrying'), {
        kind: connected ? 'success' : 'warn',
        timeoutMs: 1600,
        dedupeKey: connected ? 'net:up' : 'net:down'
      })
    }
    updateServerStatus._last = !!connected

    const light = document.getElementById('statusLight')
    if (light) {
      light.classList.remove('connected', 'disconnected')
      if (connected) {
        light.classList.add('connected')
        light.title = t('ui.status.serverConnected')
      } else {
        light.classList.add('disconnected')
        light.title = t('ui.status.serverDisconnected')
      }
    }

    const lightStandalone = document.getElementById('statusLightStandalone')
    const textStandalone = document.getElementById('statusTextStandalone')
    const progressBar = document.getElementById('noContentProgress')

    if (lightStandalone) {
      lightStandalone.classList.remove('connected', 'disconnected')
      if (connected) {
        lightStandalone.classList.add('connected')
        lightStandalone.title = t('ui.status.serverConnected')
      } else {
        lightStandalone.classList.add('disconnected')
        lightStandalone.title = t('ui.status.serverDisconnected')
      }
    }

    if (textStandalone) {
      textStandalone.textContent = connected
        ? t('ui.status.connected')
        : t('ui.status.disconnected')
    }

    if (progressBar) {
      if (connected) {
        progressBar.classList.remove('hidden')
      } else {
        progressBar.classList.add('hidden')
      }
    }

    vscode.postMessage({ type: 'serverStatus', connected })
  }

  function startPolling() {
    stopPolling()
    installPollingVisibilityHandler()
    pollingEnabled = true
    pollingToken = pollingToken + 1
    const token = pollingToken
    pollBackoffMs = POLL_BASE_MS
    _connectSSE()
    scheduleNextPoll(0, token)
  }

  function scheduleNextPoll(delayMs, token) {
    const t = typeof token === 'number' && Number.isFinite(token) ? token : pollingToken
    if (!pollingEnabled) return
    if (t !== pollingToken) return
    if (pollingTimer) {
      clearTimeout(pollingTimer)
      pollingTimer = null
    }
    pollingTimer = setTimeout(
      async () => {
        if (!pollingEnabled) return
        if (t !== pollingToken) return
        const ok = await pollAllData('poll')
        if (!pollingEnabled) return
        if (t !== pollingToken) return
        const suggested =
          typeof pollSuggestedDelayMs === 'number' && Number.isFinite(pollSuggestedDelayMs)
            ? Math.max(0, Math.floor(pollSuggestedDelayMs))
            : null
        pollSuggestedDelayMs = null
        if (ok) {
          const base = _sseConnected ? POLL_SSE_FALLBACK_MS : POLL_BASE_MS
          pollBackoffMs = suggested !== null ? Math.min(POLL_MAX_MS, suggested) : base
        } else {
          pollBackoffMs = getNextBackoffMs(pollBackoffMs)
        }
        scheduleNextPoll(pollBackoffMs, t)
      },
      Math.max(0, delayMs)
    )
  }

  function stopPolling() {
    pollingEnabled = false
    pollingToken = pollingToken + 1
    _disconnectSSE()
    if (pollingTimer) {
      clearTimeout(pollingTimer)
      pollingTimer = null
    }
    try {
      if (pollAbortController && typeof pollAbortController.abort === 'function') {
        pollAbortController.abort()
      }
    } catch (e) {

    } finally {
      pollAbortController = null
    }
    activePollingRunId = 0
    pollingInFlight = false
  }

  function handleTasksPollFailure() {
    updateServerStatus(false)
    if (currentConfig && currentConfig.task_id) {
      return false
    }
    hideTabs()
    showNoContent()
    return false
  }

  async function pollAllData(reason) {

    if (typeof document !== 'undefined' && document.hidden) {
      return false
    }

    if (pollingInFlight) {
      return false
    }
    pollingInFlight = true
    pollingRunId = pollingRunId + 1
    const runId = pollingRunId
    activePollingRunId = runId
    const isCurrentPollRun = () => activePollingRunId === runId
    let tasksTimeoutId = null
    let configTimeoutId = null
    let tasksAbortController = null
    let configAbortController = null

    try {

      try {
        if (pollAbortController && typeof pollAbortController.abort === 'function') {
          pollAbortController.abort()
        }
      } catch (e) {

      }

      if (typeof AbortController !== 'undefined') {
        tasksAbortController = new AbortController()
        pollAbortController = tasksAbortController
      } else {
        pollAbortController = null
      }

      const fetchOptions = { cache: 'no-store' }
      if (tasksAbortController) {
        fetchOptions.signal = tasksAbortController.signal
      }

      if (tasksAbortController) {
        tasksTimeoutId = setTimeout(() => {
          try {
            tasksAbortController.abort()
          } catch (e) {

          }
        }, POLL_TASKS_TIMEOUT_MS)
      }
      const tasksResponse = await fetch(SERVER_URL + '/api/tasks', fetchOptions)
      if (!isCurrentPollRun()) {
        return false
      }
      if (tasksTimeoutId) {
        clearTimeout(tasksTimeoutId)
        tasksTimeoutId = null
      }

      if (!tasksResponse.ok) {
        return handleTasksPollFailure()
      }

      updateServerStatus(true)
      const tasksData = await tasksResponse.json()
      if (!isCurrentPollRun()) {
        return false
      }

      if (tasksData && typeof tasksData.server_time === 'number') {
        const localTime = Date.now() / 1000
        serverTimeOffset = tasksData.server_time - localTime
      }

      if (tasksData && tasksData.tasks && Array.isArray(tasksData.tasks)) {
        tasksData.tasks.forEach(t => {
          if (!t || !t.task_id) return
          if (typeof t.deadline === 'number') {
            taskDeadlines[t.task_id] = t.deadline
          }
          if (typeof t.remaining_time === 'number') {
            tabCountdownRemaining[t.task_id] = Math.max(0, Math.floor(t.remaining_time))
          }
        })
      }

      try {
        const stats = tasksData && tasksData.stats ? tasksData.stats : null
        if (stats) {
          const active = typeof stats.active === 'number' ? stats.active : 0
          const pending = typeof stats.pending === 'number' ? stats.pending : 0
          const total =
            typeof stats.total === 'number' && Number.isFinite(stats.total)
              ? stats.total
              : active + pending
          vscode.postMessage({
            type: 'tasksStats',
            connected: !!(tasksData && tasksData.success),
            active,
            pending,
            total
          })
        }
      } catch (e) {

      }

      if (!tasksData || tasksData.success !== true) {
        return handleTasksPollFailure()
      }

      if (Array.isArray(tasksData.tasks) && tasksData.tasks.length > 0) {
        allTasks = tasksData.tasks
        renderTaskTabs()

        const activeTask = allTasks.find(t => t && t.status === 'active')
        if (activeTask && activeTask.task_id) {
          activeTaskId = activeTask.task_id
        }

        if (typeof updateCountdownControls === 'function') {
          updateCountdownControls(null)
        }

        if (typeof AbortController !== 'undefined') {
          try {
            configAbortController = new AbortController()
            pollAbortController = configAbortController
            fetchOptions.signal = configAbortController.signal
          } catch (e) {
            if (pollAbortController === tasksAbortController) {
              pollAbortController = null
            }
            try {
              delete fetchOptions.signal
            } catch (e2) {

            }
          }
        } else {
          if (pollAbortController === tasksAbortController) {
            pollAbortController = null
          }
          try {
            delete fetchOptions.signal
          } catch (e) {

          }
        }
        if (configAbortController) {
          configTimeoutId = setTimeout(() => {
            try {
              configAbortController.abort()
            } catch (e) {

            }
          }, POLL_CONFIG_TIMEOUT_MS)
        }
        const okConfig = await pollConfig(fetchOptions)
        if (configTimeoutId) {
          clearTimeout(configTimeoutId)
          configTimeoutId = null
        }
        if (!isCurrentPollRun()) {
          return false
        }
        return !!okConfig
      }

      allTasks = []
      activeTaskId = null
      if (typeof updateCountdownControls === 'function') {
        updateCountdownControls(null)
      }
      clearAllTabCountdowns()
      taskDeadlines = {}
      taskTextareaContents = {}
      taskOptionsStates = {}
      taskYesnoSelections = {}
      taskImages = {}
      pendingImageUploadCounts = {}
      schedulePersistUiState()
      lastTasksHash = ''
      lastTaskIds = new Set()
      hasInitializedTaskIdTracking = true
      hideTabs()
      showNoContent()

      try {
        const jitter = Math.round(POLL_IDLE_MS * 0.15 * Math.random())
        pollSuggestedDelayMs = POLL_IDLE_MS + jitter
      } catch (e) {
        pollSuggestedDelayMs = POLL_IDLE_MS
      }

      return true
    } catch (error) {
      if (error && (error.name === 'AbortError' || error.code === 20)) {
        return false
      }
      if (!isCurrentPollRun()) {
        return false
      }
      log('Poll failed: ' + error.message)
      return handleTasksPollFailure()
    } finally {
      if (tasksTimeoutId) {
        clearTimeout(tasksTimeoutId)
      }
      if (configTimeoutId) {
        clearTimeout(configTimeoutId)
      }
      if (activePollingRunId === runId) {
        pollingInFlight = false
        activePollingRunId = 0
      }
      if (pollAbortController === tasksAbortController || pollAbortController === configAbortController) {
        pollAbortController = null
      }
    }
  }

  function hideTabs() {
    const container = document.getElementById('tasksTabsContainer')
    if (!container) return
    const existingTabs = container.querySelectorAll('.task-tab')
    existingTabs.forEach(tab => tab.remove())
    container.classList.add('hidden')
  }

  function setHiddenById(id, hidden) {
    const element = document.getElementById(id)
    if (!element || !element.classList) return null
    if (hidden) {
      element.classList.add('hidden')
    } else {
      element.classList.remove('hidden')
    }
    return element
  }

  function showTabs() {
    setHiddenById('tasksTabsContainer', false)
  }

  function requestImmediateRefresh() {

    if (typeof document !== 'undefined' && document.hidden) {
      return
    }
    pollBackoffMs = POLL_BASE_MS
    if (!pollingEnabled) {
      startPolling()
      return
    }
    scheduleNextPoll(0, pollingToken)
  }

  function getAdjustedNowSeconds() {
    return Date.now() / 1000 + (serverTimeOffset || 0)
  }

  function computeRemainingForTask(task) {
    try {
      if (task && typeof task.remaining_time === 'number') {
        return Math.max(0, Math.floor(task.remaining_time))
      }
      if (task && task.task_id && typeof taskDeadlines[task.task_id] === 'number') {
        return Math.max(0, Math.floor(taskDeadlines[task.task_id] - getAdjustedNowSeconds()))
      }
      if (task && task.task_id && typeof tabCountdownRemaining[task.task_id] === 'number') {
        return Math.max(0, Math.floor(tabCountdownRemaining[task.task_id]))
      }
      if (task && typeof task.auto_resubmit_timeout === 'number') {
        return Math.max(0, Math.floor(task.auto_resubmit_timeout))
      }
    } catch (e) {

    }
    return 0
  }

  function normalizeTaskImages(images) {
    const normalizedImages = []
    if (!Array.isArray(images)) return normalizedImages
    for (const img of images) {
      const data = img && img.data ? String(img.data) : ''
      if (!data) continue
      normalizedImages.push({
        name: img && img.name ? String(img.name) : 'image',
        data
      })
    }
    return normalizedImages
  }

  function saveLocalStateForTask(taskId) {
    if (!taskId) return
    try {
      const textarea = document.getElementById('feedbackText')
      if (textarea) {
        taskTextareaContents[taskId] = textarea.value || ''
      }

      const optionsContainer = document.getElementById('optionsContainer')
      if (optionsContainer) {
        const states = {}
        const checkboxes = optionsContainer.querySelectorAll('input[type="checkbox"]')
        checkboxes.forEach((cb, index) => {
          states[index] = !!cb.checked
        })

        taskOptionsStates[taskId] = states
      }

      if (Array.isArray(uploadedImages)) {
        taskImages[taskId] = normalizeTaskImages(uploadedImages)
      }
    } catch (e) {

    }
  }

  function restoreLocalStateForTask(taskId) {
    if (!taskId) return
    try {
      const textarea = document.getElementById('feedbackText')
      if (textarea) {
        textarea.value = taskTextareaContents[taskId] || ''
        autoResizeFeedbackTextarea(textarea)
      }

      uploadedImages = normalizeTaskImages(taskImages[taskId] || [])
      renderUploadedImages()
    } catch (e) {

    }
  }

  function syncImagesToTaskCache(taskId) {
    if (!taskId) return
    try {
      taskImages[taskId] = normalizeTaskImages(uploadedImages || [])
    } catch (e) {

    }
  }

  function getImageUploadTargetImages(taskId, fallbackImages) {
    if (taskId && activeTaskId === taskId && Array.isArray(uploadedImages)) {
      return uploadedImages
    }
    if (taskId && Array.isArray(taskImages[taskId])) {
      return taskImages[taskId]
    }
    if (Array.isArray(fallbackImages)) {
      return fallbackImages
    }
    return Array.isArray(uploadedImages) ? uploadedImages : []
  }

  function cacheImagesForTask(taskId, images) {
    if (!taskId || !Array.isArray(images)) return
    try {
      taskImages[taskId] = normalizeTaskImages(images)
      schedulePersistUiState()
    } catch (e) {

    }
  }

  function getPendingImageUploadKey(taskId) {
    return taskId ? 'task:' + String(taskId) : 'current'
  }

  function getPendingImageUploadCount(taskId) {
    const key = getPendingImageUploadKey(taskId)
    const count = pendingImageUploadCounts[key]
    return typeof count === 'number' && count > 0 ? count : 0
  }

  function incrementPendingImageUploadCount(taskId) {
    const key = getPendingImageUploadKey(taskId)
    pendingImageUploadCounts[key] = getPendingImageUploadCount(taskId) + 1
  }

  function decrementPendingImageUploadCount(taskId) {
    const key = getPendingImageUploadKey(taskId)
    const next = Math.max(0, getPendingImageUploadCount(taskId) - 1)
    if (next > 0) {
      pendingImageUploadCounts[key] = next
    } else {
      delete pendingImageUploadCounts[key]
    }
  }

  function getTaskIdString(task) {
    return task && task.task_id ? String(task.task_id) : ''
  }

  function getOpenTaskId(taskId) {
    if (!taskId || !Array.isArray(allTasks)) return ''
    const wanted = String(taskId)
    try {
      const found = allTasks.find(
        task => getTaskIdString(task) === wanted && task.status !== 'completed'
      )
      return found ? wanted : ''
    } catch (e) {
      return ''
    }
  }

  function pickOpenTaskId(preferredTaskId) {
    const preferred = preferredTaskId ? String(preferredTaskId) : ''
    if (!hasInitializedTaskIdTracking && preferred) return preferred

    const openPreferred = getOpenTaskId(preferred)
    if (openPreferred) return openPreferred

    try {
      const serverActive = Array.isArray(allTasks)
        ? allTasks.find(task => getTaskIdString(task) && task.status === 'active')
        : null
      const serverActiveId = getTaskIdString(serverActive)
      if (serverActiveId) return serverActiveId

      const firstOpen = Array.isArray(allTasks)
        ? allTasks.find(task => getTaskIdString(task) && task.status !== 'completed')
        : null
      const firstOpenId = getTaskIdString(firstOpen)
      if (firstOpenId) return firstOpenId
    } catch (e) {

    }
    return ''
  }

  function reconcileActiveTaskId(taskTabsState) {
    const previous = activeTaskId ? String(activeTaskId) : ''
    if (taskTabsState && taskTabsState.activeTaskIdSet) {
      const next = taskTabsState.activeTaskIdSet.has(previous)
        ? previous
        : taskTabsState.serverActiveTaskId || taskTabsState.firstOpenTaskId || ''
      if (previous === next) return false
      activeTaskId = next || null
      return true
    }
    const next = pickOpenTaskId(previous)
    if (previous === next) return false
    activeTaskId = next || null
    return true
  }

  function isTaskStillOpenForLocalState(taskId) {
    if (!taskId || !hasInitializedTaskIdTracking) return true
    try {
      return !!getOpenTaskId(taskId)
    } catch (e) {
      return true
    }
  }

  function pruneTaskLocalState(activeTaskIdSet) {
    if (!activeTaskIdSet || typeof activeTaskIdSet.has !== 'function') return false

    const staleTaskIds = new Set()
    const rememberTaskIds = source => {
      try {
        if (!source) return
        for (const taskId in source) {
          if (!Object.prototype.hasOwnProperty.call(source, taskId)) continue
          if (taskId && !activeTaskIdSet.has(taskId)) {
            staleTaskIds.add(taskId)
          }
        }
      } catch (e) {

      }
    }

    rememberTaskIds(tabCountdownTimers)
    rememberTaskIds(tabCountdownRemaining)
    rememberTaskIds(taskDeadlines)
    rememberTaskIds(taskTextareaContents)
    rememberTaskIds(taskOptionsStates)
    rememberTaskIds(taskImages)
    try {
      if (pendingImageUploadCounts) {
        for (const key in pendingImageUploadCounts) {
          if (!Object.prototype.hasOwnProperty.call(pendingImageUploadCounts, key)) continue
          if (!key || !key.startsWith('task:')) continue
          const taskId = key.slice(5)
          if (taskId && !activeTaskIdSet.has(taskId)) {
            staleTaskIds.add(taskId)
          }
        }
      }
    } catch (e) {

    }

    staleTaskIds.forEach(existingId => {
      try {
        const entry = tabCountdownTimers[existingId]
        if (typeof entry === 'number') {
          clearInterval(entry)
        }
      } catch (e) {

      }
      delete tabCountdownTimers[existingId]
      delete tabCountdownRemaining[existingId]
      delete taskDeadlines[existingId]
      delete taskTextareaContents[existingId]
      delete taskOptionsStates[existingId]
      delete taskYesnoSelections[existingId]
      delete taskImages[existingId]
      delete pendingImageUploadCounts[getPendingImageUploadKey(existingId)]
    })

    if (typeof stopSharedTabCountdownTickerIfIdle === 'function') {
      stopSharedTabCountdownTickerIfIdle()
    }

    return staleTaskIds.size > 0
  }

  function buildTaskTabsRenderState(tasks, previousTaskIds, collectNewTaskData) {
    const currentTaskIds = new Set()
    const newTaskData = []
    const activeTasks = []
    const activeTaskIdSet = new Set()
    let serverActiveTaskId = ''
    let firstOpenTaskId = ''
    const knownTaskIds =
      previousTaskIds && typeof previousTaskIds.has === 'function' ? previousTaskIds : new Set()
    let currentHash = ''
    let index = 0

    for (const task of tasks) {
      if (index > 0) currentHash += '|'
      currentHash += task.task_id + ':' + task.status
      index += 1

      currentTaskIds.add(task.task_id)
      if (collectNewTaskData && !knownTaskIds.has(task.task_id) && task.task_id) {
        newTaskData.push({ id: task.task_id, prompt: task.prompt || '' })
      }

      if (task.status !== 'completed') {
        activeTasks.push(task)
        const taskId = getTaskIdString(task)
        if (taskId) {
          activeTaskIdSet.add(taskId)
          if (!firstOpenTaskId) firstOpenTaskId = taskId
          if (!serverActiveTaskId && task.status === 'active') serverActiveTaskId = taskId
        }
      }
    }

    return {
      currentHash,
      currentTaskIds,
      newTaskData,
      activeTasks,
      activeTaskIdSet,
      serverActiveTaskId,
      firstOpenTaskId
    }
  }

  function renderTaskTabs() {
    const container = document.getElementById('tasksTabsContainer')

    if (!allTasks || allTasks.length === 0) {
      const activeTaskChanged = !!(hasInitializedTaskIdTracking && activeTaskId)
      if (activeTaskChanged) {
        activeTaskId = null
      }
      hideTabs()
      lastTasksHash = ''
      clearAllTabCountdowns()
      if (activeTaskChanged || pruneTaskLocalState(new Set())) {
        schedulePersistUiState()
      }
      return
    }

    const taskTabsState = buildTaskTabsRenderState(
      allTasks,
      lastTaskIds,
      hasInitializedTaskIdTracking
    )
    const currentHash = taskTabsState.currentHash

    if (taskTabsState.newTaskData.length > 0) {
      notifyNewTasks(taskTabsState.newTaskData)
    }

    lastTaskIds = taskTabsState.currentTaskIds
    hasInitializedTaskIdTracking = true
    const activeTaskChanged = reconcileActiveTaskId(taskTabsState)

    if (!container) {
      lastTasksHash = ''
      clearAllTabCountdowns()
      if (activeTaskChanged) {
        schedulePersistUiState()
      }
      log('Skipped task tabs render: tasksTabsContainer not found')
      return
    }

    if (currentHash === lastTasksHash) {
      updateTabCountdowns(taskTabsState.activeTasks)

      if (activeTaskId) {
        try {
          const tabs = container.querySelectorAll('.task-tab')
          tabs.forEach(tab => {
            const id = tab && tab.dataset ? tab.dataset.taskId : ''
            const shouldActive = !!(id && id === activeTaskId)
            tab.classList.toggle('active', shouldActive)
            const dot = tab.querySelector('.task-tab-status')
            if (dot) {
              if (shouldActive) {
                dot.classList.remove('pending', 'active', 'completed')
                dot.classList.add('active')
              } else if (dot.classList.contains('active')) {

                dot.classList.remove('active')
                if (!dot.classList.contains('pending')) {
                  dot.classList.add('pending')
                }
              }
            }
          })
        } catch (e) {

        }
      }
      if (activeTaskChanged) {
        schedulePersistUiState()
      }
      return
    }

    lastTasksHash = currentHash
    showTabs()

    const existingTabs = container.querySelectorAll('.task-tab')
    existingTabs.forEach(tab => tab.remove())

    const activeTasks = taskTabsState.activeTasks
    const activeTaskIdSet = taskTabsState.activeTaskIdSet

    if (activeTaskChanged || pruneTaskLocalState(activeTaskIdSet)) {
      schedulePersistUiState()
    }

    activeTasks.forEach(task => {
      const tab = document.createElement('div')
      tab.className = 'task-tab'
      tab.dataset.taskId = task.task_id

      const isUiActive = !!(activeTaskId && task.task_id && task.task_id === activeTaskId)
      if (isUiActive || task.status === 'active') {
        tab.classList.add('active')
      }

      const statusDot = document.createElement('div')
      statusDot.className = 'task-tab-status'
      statusDot.classList.add(
        isUiActive || task.status === 'active' ? 'active' : task.status || 'pending'
      )
      tab.appendChild(statusDot)

      const taskId = document.createElement('div')
      taskId.className = 'task-tab-id'

      const tabLabel =
        typeof task.header_label === 'string' && task.header_label.trim() !== ''
          ? task.header_label.trim().slice(0, 16)
          : task.task_id
      taskId.textContent = tabLabel
      taskId.title = task.task_id

      tab.appendChild(taskId)

      if (
        typeof task.iteration_label === 'string' &&
        task.iteration_label.trim() !== ''
      ) {
        const iterBadge = document.createElement('span')
        iterBadge.className = 'task-tab-iter'
        iterBadge.textContent = task.iteration_label.trim()
        iterBadge.setAttribute('aria-hidden', 'true')
        tab.appendChild(iterBadge)
      }

      if (task.auto_resubmit_timeout > 0) {
        const countdown = document.createElement('div')
        countdown.className = 'task-tab-countdown'
        countdown.id = 'tab-countdown-' + task.task_id

        const radius = 9
        const circumference = 2 * Math.PI * radius

        const remaining = computeRemainingForTask(task)
        tabCountdownRemaining[task.task_id] = remaining
        const progress = remaining / task.auto_resubmit_timeout
        const offset = circumference * (1 - progress)

        var safeTaskId = escapeHtml(task.task_id)
        countdown.innerHTML =
          '<svg width="22" height="22" viewBox="0 0 22 22">' +
          '<circle id="tab-countdown-progress-' +
          safeTaskId +
          '" ' +
          'cx="11" cy="11" r="' +
          radius +
          '" ' +
          'stroke-dasharray="' +
          circumference +
          '" ' +
          'stroke-dashoffset="' +
          offset +
          '" /></svg>' +
          '<span class="task-tab-countdown-number" id="tab-countdown-text-' +
          safeTaskId +
          '">' +
          remaining +
          '</span>'

        countdown.title = t('ui.countdown.remaining', { seconds: remaining })
        tab.appendChild(countdown)

        if (!tabCountdownTimers[task.task_id]) {
          startTabCountdown(task.task_id, task.auto_resubmit_timeout, remaining)
        }
      }

      tab.addEventListener('click', () => switchToTask(task.task_id))

      container.appendChild(tab)
    })

    log('Rendered ' + activeTasks.length + ' task tab(s) (completed tasks filtered)')
  }

  async function switchToTask(taskId) {
    if (taskId === activeTaskId) {
      log('Task already active: ' + taskId)
      return
    }

    try {

      const prevTaskId = activeTaskId || (currentConfig && currentConfig.task_id)
      if (prevTaskId) {
        saveLocalStateForTask(prevTaskId)
      }

      log('Switching to task: ' + taskId)

      activeTaskId = taskId
      restoreLocalStateForTask(taskId)
      showToast(t('ui.task.switchedTo', { id: taskId }), {
        kind: 'info',
        timeoutMs: 1200,
        dedupeKey: 'switch:' + taskId
      })

      try {
        const tabs = document.querySelectorAll('#tasksTabsContainer .task-tab')
        tabs.forEach(tab => {
          const id = tab && tab.dataset ? tab.dataset.taskId : ''
          const isActive = !!(id && id === taskId)
          tab.classList.toggle('active', isActive)
          const dot = tab.querySelector('.task-tab-status')
          if (dot) {
            if (isActive) {
              dot.classList.remove('pending', 'active', 'completed')
              dot.classList.add('active')
            } else if (dot.classList.contains('active')) {
              dot.classList.remove('active')
              if (!dot.classList.contains('pending')) {
                dot.classList.add('pending')
              }
            }
          }
        })
      } catch (e) {

      }

      let response = null
      let activateController = null
      let activateTimeoutId = null
      try {
        const activateOptions = { method: 'POST' }
        if (typeof AbortController !== 'undefined') {
          try {
            activateController = new AbortController()
            activateOptions.signal = activateController.signal
            activateTimeoutId = setTimeout(() => {
              try {
                activateController.abort()
              } catch (e) {

              }
            }, 4000)
          } catch (e) {
            activateController = null
          }
        }
        response = await fetch(
          SERVER_URL + '/api/tasks/' + encodeURIComponent(taskId) + '/activate',
          activateOptions
        )
      } finally {
        if (activateTimeoutId) clearTimeout(activateTimeoutId)
      }

      if (response && response.ok) {
        log('Task activated: ' + taskId)
        requestImmediateRefresh()
      } else {
        const status = response && typeof response.status === 'number' ? response.status : 0
        logError(t('ui.task.switchFailed', { reason: 'HTTP ' + status }))
        vscode.postMessage({
          type: 'showInfo',
          message: t('ui.task.switchFailed', { reason: taskId })
        })

        if (prevTaskId) {
          activeTaskId = prevTaskId
          restoreLocalStateForTask(prevTaskId)
          try {
            const tabs = document.querySelectorAll('#tasksTabsContainer .task-tab')
            tabs.forEach(tab => {
              const id = tab && tab.dataset ? tab.dataset.taskId : ''
              const isActive = !!(id && id === prevTaskId)
              tab.classList.toggle('active', isActive)
              const dot = tab.querySelector('.task-tab-status')
              if (dot) {
                if (isActive) {
                  dot.classList.remove('pending', 'active', 'completed')
                  dot.classList.add('active')
                } else if (dot.classList.contains('active')) {
                  dot.classList.remove('active')
                  if (!dot.classList.contains('pending')) {
                    dot.classList.add('pending')
                  }
                }
              }
            })
          } catch (e) {

          }
        }
      }
    } catch (error) {
      const isAbort = !!(
        error &&
        (error.name === 'AbortError' || String(error.name || '') === 'AbortError')
      )
      const errMsg =
        error && error.message
          ? String(error.message)
          : isAbort
            ? t('settings.hint.timeout')
            : String(error)
      logError(isAbort ? t('ui.task.activateTimeoutCheckServer') : t('ui.task.switchFailed', { reason: errMsg }))
      vscode.postMessage({
        type: 'showInfo',
        message: t('ui.task.switchFailed', { reason: errMsg })
      })

      try {
        const prevTaskId = currentConfig && currentConfig.task_id ? currentConfig.task_id : null
        if (prevTaskId) {
          activeTaskId = prevTaskId
          restoreLocalStateForTask(prevTaskId)
          try {
            const tabs = document.querySelectorAll('#tasksTabsContainer .task-tab')
            tabs.forEach(tab => {
              const id = tab && tab.dataset ? tab.dataset.taskId : ''
              const isActive = !!(id && id === prevTaskId)
              tab.classList.toggle('active', isActive)
              const dot = tab.querySelector('.task-tab-status')
              if (dot) {
                if (isActive) {
                  dot.classList.remove('pending', 'active', 'completed')
                  dot.classList.add('active')
                } else if (dot.classList.contains('active')) {
                  dot.classList.remove('active')
                  if (!dot.classList.contains('pending')) {
                    dot.classList.add('pending')
                  }
                }
              }
            })
          } catch (e) {

          }
        }
      } catch (e) {

      }
    }
  }

  function hasTabCountdownTimers() {
    for (const taskId in tabCountdownTimers) {
      if (Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)) return true
    }
    return false
  }

  function stopSharedTabCountdownTickerIfIdle() {
    if (!tabCountdownTickerTimer || hasTabCountdownTimers()) return
    clearInterval(tabCountdownTickerTimer)
    tabCountdownTickerTimer = null
  }

  function ensureSharedTabCountdownTicker() {
    if (tabCountdownTickerTimer) return
    if (typeof installTabCountdownVisibilitySyncHandlerOnce === 'function') {
      installTabCountdownVisibilitySyncHandlerOnce()
    }
    tabCountdownTickerTimer = setInterval(tickAllTabCountdowns, 1000)
  }

  function tickAllTabCountdowns() {
    for (const taskId in tabCountdownTimers) {
      if (Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)) {
        tickTabCountdown(taskId)
      }
    }
    stopSharedTabCountdownTickerIfIdle()
  }

  function forceUpdateAllTabCountdowns() {
    if (typeof document !== 'undefined' && document.hidden) return
    for (const taskId in tabCountdownTimers) {
      if (!Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)) continue
      const state = tabCountdownTimers[taskId]
      if (!state || typeof state !== 'object') continue
      const remainingInfo = computeTabCountdownRemaining(taskId, state)
      if (remainingInfo.computedRemaining <= 0) {
        delete tabCountdownTimers[taskId]
        delete tabCountdownRemaining[taskId]
        stopSharedTabCountdownTickerIfIdle()
        continue
      }
      tabCountdownRemaining[taskId] = remainingInfo.computedRemaining
      renderTabCountdown(taskId, state, remainingInfo.computedRemaining)
    }
  }

  function installTabCountdownVisibilitySyncHandlerOnce() {
    if (tabCountdownVisibilityHandlerInstalled) return
    tabCountdownVisibilityHandlerInstalled = true
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        forceUpdateAllTabCountdowns()
      }
    })
  }

  function _getOrCacheTabCountdownDom(taskId, state) {
    const cache = state._domCache
    if (cache && cache.progressCircle && document.contains(cache.progressCircle)) {
      return cache
    }

    const progressCircle = document.getElementById('tab-countdown-progress-' + taskId)
    const numberSpan = document.getElementById('tab-countdown-text-' + taskId)
    const countdownRing = document.getElementById('tab-countdown-' + taskId)

    if (!progressCircle || !numberSpan) return null

    const nextCache = {
      progressCircle: progressCircle,
      numberSpan: numberSpan,
      countdownRing: countdownRing,
    }
    state._domCache = nextCache
    return nextCache
  }

  function computeTabCountdownRemaining(taskId, state) {
    const deadline = typeof taskDeadlines[taskId] === 'number' ? taskDeadlines[taskId] : null
    const computedRemaining = deadline
      ? Math.max(0, Math.floor(deadline - getAdjustedNowSeconds()))
      : Math.max(0, state.remaining)
    return {
      deadline: deadline,
      computedRemaining: computedRemaining,
    }
  }

  function renderTabCountdown(taskId, state, computedRemaining) {
    const domCache = _getOrCacheTabCountdownDom(taskId, state)

    if (!domCache) return

    const progress = computedRemaining / state.totalSeconds
    const offset = state.circumference * (1 - progress)

    domCache.progressCircle.setAttribute('stroke-dashoffset', offset)
    domCache.numberSpan.textContent = computedRemaining

    if (domCache.countdownRing) {
      domCache.countdownRing.title = t('ui.countdown.remaining', { seconds: computedRemaining })
    }
  }

  function tickTabCountdown(taskId) {
    const state = tabCountdownTimers[taskId]
    if (!state || typeof state !== 'object') return

    const remainingInfo = computeTabCountdownRemaining(taskId, state)
    const computedRemaining = remainingInfo.computedRemaining

    if (computedRemaining <= 0) {
      delete tabCountdownTimers[taskId]
      delete tabCountdownRemaining[taskId]
      stopSharedTabCountdownTickerIfIdle()
      return
    }

    tabCountdownRemaining[taskId] = computedRemaining

    if (!remainingInfo.deadline) {
      state.remaining = computedRemaining - 1
    }

    const documentHidden = typeof document !== 'undefined' && document.hidden
    if (documentHidden) return

    renderTabCountdown(taskId, state, computedRemaining)
  }

  function startTabCountdown(taskId, totalSeconds, initialRemaining = null) {
    const radius = 9
    const circumference = 2 * Math.PI * radius
    const state = {
      totalSeconds,
      remaining: initialRemaining !== null ? initialRemaining : totalSeconds,
      circumference,
    }

    if (!_getOrCacheTabCountdownDom(taskId, state)) return

    tabCountdownTimers[taskId] = state

    tickTabCountdown(taskId)

    if (tabCountdownTimers[taskId]) {
      ensureSharedTabCountdownTicker()
    }
  }

  function clearAllTabCountdowns() {
    for (const taskId in tabCountdownTimers) {
      if (!Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)) continue
      try {
        const entry = tabCountdownTimers[taskId]
        if (typeof entry === 'number') {
          clearInterval(entry)
        }
      } catch (e) {

      }
    }
    if (typeof tabCountdownTickerTimer !== 'undefined' && tabCountdownTickerTimer) {
      clearInterval(tabCountdownTickerTimer)
      tabCountdownTickerTimer = null
    }
    tabCountdownTimers = {}
    tabCountdownRemaining = {}
  }

  function updateTabCountdowns(tasks = allTasks) {
    const tasksForCountdown = Array.isArray(tasks) ? tasks : allTasks
    tasksForCountdown.forEach(task => {
      if (task.auto_resubmit_timeout > 0) {
        const progressCircle = document.getElementById('tab-countdown-progress-' + task.task_id)

        if (progressCircle && !tabCountdownTimers[task.task_id]) {
          startTabCountdown(task.task_id, task.auto_resubmit_timeout, computeRemainingForTask(task))
        }
      }
    })
  }

  function pickFallbackTaskId() {
    try {
      return pickOpenTaskId(activeTaskId)
    } catch (e) {
      return ''
    }
  }

  async function fetchTaskDetailAsConfig(taskId) {
    const id = taskId ? String(taskId) : ''
    if (!id) return null

    let timeoutId = null
    try {
      const options = { cache: 'no-store' }

      if (typeof AbortController !== 'undefined') {
        try {
          const controller = new AbortController()
          options.signal = controller.signal
          timeoutId = setTimeout(() => {
            try {
              controller.abort()
            } catch (e) {

            }
          }, POLL_CONFIG_TIMEOUT_MS)
        } catch (e) {

        }
      }

      const resp = await fetch(SERVER_URL + '/api/tasks/' + encodeURIComponent(id), options)
      if (!resp.ok) return null

      const data = await resp.json()
      if (!data || !data.success || !data.task) return null

      const t = data.task || {}
      const prompt = t.prompt ? String(t.prompt) : ''
      const predefined = Array.isArray(t.predefined_options) ? t.predefined_options : []
      const predefinedDefaults = Array.isArray(t.predefined_options_defaults)
        ? t.predefined_options_defaults
        : []
      return {
        prompt,
        prompt_html: '',
        predefined_options: predefined,
        predefined_options_defaults: predefinedDefaults,

        header_label: t.header_label,
        feedback_placeholder: t.feedback_placeholder,
        question_type: t.question_type,

        loop_id: t.loop_id,
        loop_objective: t.loop_objective,
        loop_phase: t.loop_phase,
        success_criteria: t.success_criteria,
        iteration_label: t.iteration_label,
        task_id: t.task_id ? String(t.task_id) : id,
        auto_resubmit_timeout:
          typeof t.auto_resubmit_timeout === 'number' && Number.isFinite(t.auto_resubmit_timeout)
            ? Math.max(0, Math.floor(t.auto_resubmit_timeout))
            : 0,
        remaining_time:
          typeof t.remaining_time === 'number' && Number.isFinite(t.remaining_time)
            ? Math.max(0, Math.floor(t.remaining_time))
            : undefined,
        server_time:
          typeof data.server_time === 'number' && Number.isFinite(data.server_time)
            ? data.server_time
            : undefined,
        deadline:
          typeof t.deadline === 'number' && Number.isFinite(t.deadline) ? t.deadline : undefined,
        persistent: true,
        has_content: !!prompt,
        initial_empty: false
      }
    } catch (e) {
      return null
    } finally {
      if (timeoutId) clearTimeout(timeoutId)
    }
  }

  async function pollConfig(fetchOptions) {
    const tryFallback = async reason => {
      const id = pickFallbackTaskId()
      if (!id) return false
      const fallback = await fetchTaskDetailAsConfig(id)
      if (!fallback || !fallback.has_content) return false
      try {
        if (typeof fallback.server_time === 'number') {
          const localTime = Date.now() / 1000
          serverTimeOffset = fallback.server_time - localTime
        }
      } catch (e) {

      }
      try {
        if (fallback.task_id && typeof fallback.deadline === 'number') {
          taskDeadlines[fallback.task_id] = fallback.deadline
        }
      } catch (e) {

      }
      try {
        if (fallback.task_id) {
          activeTaskId = fallback.task_id
        }
      } catch (e) {

      }
      if (reason !== 'no_content') {
        try {
          showToast(
            reason
              ? t('ui.toast.configFallbackReason', { reason: reason })
              : t('ui.toast.configFallback'),
            {
              kind: 'warn',
              timeoutMs: 1600,
              dedupeKey: 'config:fallback'
            }
          )
        } catch (e) {

        }
      }
      updateUI(fallback)
      return true
    }

    try {
      const options = fetchOptions ? { ...fetchOptions } : { cache: 'no-store' }
      if (!options.cache) options.cache = 'no-store'
      const response = await fetch(SERVER_URL + '/api/config', options)

      if (!response.ok) {
        const okFallback = await tryFallback('HTTP ' + response.status)
        if (okFallback) return true
        if (!(currentConfig && currentConfig.has_content)) {
          showNoContent()
        }
        return false
      }

      const config = await response.json()

      if (config && config.language) {
        applyServerLanguage(config.language)
      }

      if (config && typeof config.server_time === 'number') {
        const localTime = Date.now() / 1000
        serverTimeOffset = config.server_time - localTime
      }
      if (config && config.task_id && typeof config.deadline === 'number') {
        taskDeadlines[config.task_id] = config.deadline
      }
      if (config && config.task_id) {
        activeTaskId = config.task_id
      }

      if (config.has_content && (config.prompt || config.prompt_html)) {
        updateUI(config)
      } else {

        const hasIncomplete =
          Array.isArray(allTasks) && allTasks.some(t => t && t.task_id && t.status !== 'completed')
        if (hasIncomplete) {
          const okFallback = await tryFallback('no_content')
          if (okFallback) return true
        }
        showNoContent()
      }
      return true
    } catch (error) {
      if (error && (error.name === 'AbortError' || error.code === 20)) {

        try {
          if (typeof document !== 'undefined' && document.hidden) {
            return false
          }
        } catch (e) {

        }
        const okFallback = await tryFallback('timeout')
        if (okFallback) return true
        if (!(currentConfig && currentConfig.has_content)) {
          showNoContent()
        }
        return false
      }
      const okFallback = await tryFallback('')
      if (okFallback) return true
      log('Fetch config failed: ' + (error && error.message ? error.message : String(error)))
      if (!(currentConfig && currentConfig.has_content)) {
        showNoContent()
      }
      return false
    }
  }

  let lastRenderedPrompt = ''
  let lastRenderedOptions = ''
  let markdownRenderSeq = 0

  function schedulePromptEnhancements(markdownContent, promptKey, renderSeq) {

    scheduleLowPriorityWork(() => {
      if (renderSeq !== markdownRenderSeq) return

      try {
        processCodeBlocks(markdownContent)
      } catch (e) {

      }

      try {
        loadMathJaxIfNeeded(markdownContent, promptKey)
      } catch (e) {

      }

      let hasCode = false
      try {

        hasCode = !!markdownContent.querySelector('pre code')
      } catch (e) {
        hasCode = false
      }
      if (!hasCode) return

      ensurePrismLoaded().then(ok => {
        if (!ok) return
        scheduleLowPriorityWork(() => {
          if (renderSeq !== markdownRenderSeq) return
          try {
            if (typeof Prism !== 'undefined' && Prism.highlightAllUnder) {
              Prism.highlightAllUnder(markdownContent)
            }
          } catch (e) {

          }
        }, 800)
      })
    }, 500)
  }

  function updateUI(config) {

    const isSameTask = currentConfig && currentConfig.task_id === config.task_id

    currentConfig = config

    setHiddenById('loadingState', true)
    setHiddenById('noContentState', true)
    setHiddenById('feedbackForm', false)
    destroyNoContentHourglassAnimation()
    noContentLottieRetryAttempt = 0

    const markdownContent = document.getElementById('markdownContent')
    const promptKey = config.prompt_html || config.prompt || ''
    if (promptKey !== lastRenderedPrompt) {
      const renderSeq = ++markdownRenderSeq

      if (config.prompt_html && typeof config.prompt_html === 'string') {
        markdownContent.innerHTML = sanitizePromptHtml(config.prompt_html)
        schedulePromptEnhancements(markdownContent, promptKey, renderSeq)
      } else {

        markdownContent.innerHTML = sanitizePromptHtml(renderSimpleMarkdown(config.prompt))
        schedulePromptEnhancements(markdownContent, promptKey, renderSeq)

        if (typeof marked === 'undefined') {
          ensureMarkedLoaded().then(ok => {
            if (!ok) return
            if (renderSeq !== markdownRenderSeq) return
            try {
              markdownContent.innerHTML = sanitizePromptHtml(renderSimpleMarkdown(config.prompt))
            } catch (e) {
              return
            }
            schedulePromptEnhancements(markdownContent, promptKey, renderSeq)
          })
        }
      }
      lastRenderedPrompt = promptKey
    }

    const optionsSection = document.getElementById('optionsSection')
    const optionsContainer = document.getElementById('optionsContainer')

    if (
      config.predefined_options &&
      config.predefined_options.length > 0 &&
      optionsSection &&
      optionsContainer
    ) {
      optionsSection.classList.remove('hidden')

      const optionsHash = JSON.stringify(config.predefined_options)

      const optionsKey = (config.task_id || '') + '|' + optionsHash
      const needRebuildOptions = optionsKey !== lastRenderedOptions

      if (needRebuildOptions) {

        let savedSelections = []
        const savedState = config.task_id ? taskOptionsStates[config.task_id] : null
        if (savedState) {
          if (Array.isArray(savedState)) {
            savedState.forEach((checked, idx) => {
              if (checked) savedSelections.push(idx)
            })
          } else if (typeof savedState === 'object') {
            for (const k in savedState) {
              if (!Object.prototype.hasOwnProperty.call(savedState, k)) continue
              if (savedState[k]) {
                const n = parseInt(k, 10)
                if (!Number.isNaN(n)) savedSelections.push(n)
              }
            }
          }
        } else if (isSameTask) {
          config.predefined_options.forEach((option, index) => {
            const checkbox = document.getElementById('option-' + index)
            if (checkbox && checkbox.checked) {
              savedSelections.push(index)
            }
          })
        } else if (Array.isArray(config.predefined_options_defaults)) {
          config.predefined_options_defaults.forEach((checked, index) => {
            if (checked === true) savedSelections.push(index)
          })
        }

        optionsContainer.innerHTML = ''

        config.predefined_options.forEach((option, index) => {
          const optionDiv = document.createElement('div')
          optionDiv.className = 'option-item'
          optionDiv.innerHTML =
            '<input type="checkbox" class="option-checkbox" id="option-' +
            index +
            '">' +
            '<label class="option-label" for="option-' +
            index +
            '">' +
            escapeHtml(option) +
            '</label>'

          if (savedSelections.includes(index)) {
            const checkbox = optionDiv.querySelector('input')
            checkbox.checked = true
            optionDiv.classList.add('selected')
          }

          const checkbox = optionDiv.querySelector('input')
          const label = optionDiv.querySelector('label')

          checkbox.addEventListener('change', () => {
            optionDiv.classList.toggle('selected', checkbox.checked)
          })

          optionDiv.addEventListener('click', e => {

            if (e.target !== checkbox && e.target !== label) {
              checkbox.click()
            }
          })

          optionsContainer.appendChild(optionDiv)
        })

        lastRenderedOptions = optionsKey
      }
    } else {
      if (optionsSection && optionsSection.classList) {
        optionsSection.classList.add('hidden')
      }
      lastRenderedOptions = ''
    }

    if (config.auto_resubmit_timeout && config.auto_resubmit_timeout > 0) {

      if (config.task_id !== lastCountdownTaskId || !countdownTimer) {
        startCountdown(
          config.auto_resubmit_timeout,
          config.task_id,
          config.remaining_time,
          config.deadline
        )
      }
    } else {
      stopCountdown()
    }

    if (typeof updateCountdownControls === 'function') {
      updateCountdownControls(null)
    }

    if (typeof updateHeaderChip === 'function') {
      updateHeaderChip(config.header_label)
    }
    if (typeof updateFeedbackPlaceholder === 'function') {
      updateFeedbackPlaceholder(config.feedback_placeholder)
    }
    if (typeof updateYesnoButtonGroup === 'function') {
      updateYesnoButtonGroup(config.question_type)
    }

    if (typeof updateLoopContext === 'function') {
      updateLoopContext(config)
    }

    if (!isSameTask && config.task_id) {
      restoreLocalStateForTask(config.task_id)

      if (
        typeof pendingInputFocusAtMs !== 'undefined' &&
        pendingInputFocusAtMs > 0 &&
        Date.now() - pendingInputFocusAtMs <= PENDING_FOCUS_FRESH_MS
      ) {
        pendingInputFocusAtMs = 0
        if (config.question_type !== 'yesno') {
          try {
            const focusTarget = document.getElementById('feedbackText')
            if (focusTarget && typeof focusTarget.focus === 'function') {
              focusTarget.focus()
              log('Focused feedback textarea for next task (R692)')
            }
          } catch (e) {

          }
        }
      }
    } else if (config.task_id) {

      syncImagesToTaskCache(config.task_id)
    }

    log('UI updated')
  }

  function openSettingsLazy() {
    Promise.resolve()
      .then(() => Promise.all([ensureNotifyCoreLoaded(), ensureSettingsUiLoaded()]))
      .then(result => {
        const okUi = Array.isArray(result) ? !!result[1] : false
        if (!okUi) {
          throw new Error(t('ui.settingsPanel.loadFailed'))
        }
        const ui = getSettingsUiModule()
        if (!ui || typeof ui.openSettings !== 'function') {
          throw new Error(t('ui.settingsPanel.unavailable'))
        }
        return ui.openSettings()
      })
      .catch(e => {
        const msg = e && e.message ? String(e.message) : String(e)
        try {
          showToast(t('ui.settingsPanel.openFailed', { reason: msg }), {
            kind: 'error',
            timeoutMs: 2600,
            dedupeKey: 'settings:open:' + msg.slice(0, 80)
          })
        } catch (e2) {

        }
      })
  }

  function notifyNewTasks(taskData) {
    const sourceItems = Array.isArray(taskData) ? taskData : [taskData]
    const normalized = []
    const ids = []
    for (const item of sourceItems) {
      if (!item) continue
      const normalizedItem = typeof item === 'string' ? { id: item, prompt: '' } : item
      normalized.push(normalizedItem)
      const id = normalizedItem.id || normalizedItem
      if (id) ids.push(id)
    }
    if (normalized.length === 0) return
    if (ids.length === 0) return

    const preloaded = getNotifyCoreModule()
    if (preloaded && typeof preloaded.showNewTaskNotification === 'function') {
      log('[notifyNewTasks] notify-core preloaded, dispatching directly (' + ids.length + ' task(s))')
      Promise.resolve()
        .then(() => preloaded.showNewTaskNotification(normalized))
        .catch(() => {
          postStatusInfo(
            ids.length === 1
              ? t('ui.notification.newTask', { id: ids[0] })
              : t('ui.notification.newTasks', { count: ids.length })
          )
        })
      return
    }

    log('[notifyNewTasks] notify-core not preloaded, attempting dynamic load')
    Promise.resolve()
      .then(() => ensureNotifyCoreLoaded())
      .then(ok => {
        const mod = getNotifyCoreModule()
        if (ok && mod && typeof mod.showNewTaskNotification === 'function') {
          return mod.showNewTaskNotification(normalized)
        }
        log('[notifyNewTasks] notify-core load failed, falling back to vscode status bar notification')
        const msg =
          ids.length === 1
            ? t('ui.notification.newTask', { id: ids[0] })
            : t('ui.notification.newTasks', { count: ids.length })
        postStatusInfo(msg)
      })
      .catch(() => {
        try {
          const msg =
            ids.length === 1
              ? t('ui.notification.newTask', { id: ids[0] })
              : t('ui.notification.newTasks', { count: ids.length })
          postStatusInfo(msg)
        } catch (e) {

        }
      })
  }

  function showNoContent() {

    hideTabs()
    setHiddenById('loadingState', true)
    setHiddenById('feedbackForm', true)
    setHiddenById('noContentState', false)

    clearNoContentLottieTimers()
    noContentLottieRetryAttempt = 0
    lottieInitWarned = false
    installNoContentLottieRecoveryHandlers()
    initNoContentHourglassAnimation()
    stopCountdown()
  }

  function renderSimpleMarkdown(text) {
    if (!text) return ''

    try {
      if (typeof marked !== 'undefined') {
        configureMarkedOnce()
        if (marked && typeof marked.parse === 'function') {
          return marked.parse(text)
        }
      }

      log('marked.js not loaded, rendering as plain text')
      return '<pre>' + text.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>'
    } catch (e) {
      log('Markdown render failed, falling back to plain text: ' + (e && e.message ? e.message : String(e)))
      return '<pre>' + text.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>'
    }
  }

  function escapeHtml(text) {
    var map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }
    return String(text).replace(/[&<>"']/g, function (m) {
      return map[m]
    })
  }

  function sanitizePromptHtml(rawHtml) {
    if (!rawHtml || typeof rawHtml !== 'string') return ''

    try {
      const container = document.createElement('div')
      container.innerHTML = rawHtml

      const DROP_TAGS = new Set([
        'script',
        'style',
        'iframe',
        'object',
        'embed',
        'link',
        'meta',
        'base',
        'form',
        'input',
        'textarea',
        'button',
        'select',
        'option'
      ])

      const ALLOWED_TAGS = new Set([
        'div',
        'span',
        'p',
        'br',
        'hr',
        'strong',
        'em',
        'b',
        'i',
        'del',
        'code',
        'pre',
        'blockquote',
        'ul',
        'ol',
        'li',
        'h1',
        'h2',
        'h3',
        'h4',
        'h5',
        'h6',
        'table',
        'thead',
        'tbody',
        'tr',
        'th',
        'td',
        'a',
        'img'
      ])

      const ALLOWED_ATTR = {
        a: new Set(['href', 'title', 'target', 'rel']),
        img: new Set(['src', 'alt', 'title']),
        code: new Set(['class']),
        pre: new Set(['class']),
        span: new Set(['class']),
        div: new Set(['class']),
        p: new Set(['class']),
        table: new Set(['class']),
        thead: new Set(['class']),
        tbody: new Set(['class']),
        tr: new Set(['class']),
        th: new Set(['class', 'colspan', 'rowspan', 'align']),
        td: new Set(['class', 'colspan', 'rowspan', 'align'])
      }

      function normalizeUrl(url, kind) {
        if (!url || typeof url !== 'string') return ''
        const trimmed = url.trim()
        if (!trimmed) return ''

        if (trimmed.startsWith('#')) return trimmed

        if (/^\s*javascript:/i.test(trimmed) || /^\s*vbscript:/i.test(trimmed)) return ''

        if (kind === 'img' && /^\s*data:image\//i.test(trimmed)) return trimmed

        if (kind === 'a' && /^\s*data:/i.test(trimmed)) return ''

        if (trimmed.startsWith('/')) return SERVER_URL + trimmed

        try {
          const u = new URL(trimmed, SERVER_URL)
          if (u.protocol === 'http:' || u.protocol === 'https:') return u.toString()
          return ''
        } catch (e) {
          return ''
        }
      }

      function unwrapElement(el) {
        const parent = el.parentNode
        if (!parent) return
        while (el.firstChild) {
          parent.insertBefore(el.firstChild, el)
        }
        parent.removeChild(el)
      }

      const all = container.querySelectorAll('*')
      for (let allIndex = all.length - 1; allIndex >= 0; allIndex -= 1) {
        const el =
          all[allIndex] ||
          (typeof all.item === 'function' ? all.item(allIndex) : null)
        if (!el) continue
        const tag = String(el.tagName || '').toLowerCase()
        if (!tag) continue

        if (DROP_TAGS.has(tag)) {
          el.remove()
          continue
        }

        if (!ALLOWED_TAGS.has(tag)) {
          unwrapElement(el)
          continue
        }

        const allowed = ALLOWED_ATTR[tag] || new Set(['class'])
        const attributes = el.attributes || []
        for (let attrIndex = attributes.length - 1; attrIndex >= 0; attrIndex -= 1) {
          const attr =
            attributes[attrIndex] ||
            (typeof attributes.item === 'function' ? attributes.item(attrIndex) : null)
          if (!attr) continue
          const name = String(attr.name || '').toLowerCase()
          const value = String(attr.value || '')

          if (name.startsWith('on') || name === 'style') {
            el.removeAttribute(attr.name)
            continue
          }

          if (!allowed.has(name)) {
            el.removeAttribute(attr.name)
            continue
          }

          if (tag === 'a' && name === 'href') {
            const safe = normalizeUrl(value, 'a')
            if (!safe) {
              el.removeAttribute('href')
            } else {
              el.setAttribute('href', safe)
              el.setAttribute('target', '_blank')
              el.setAttribute('rel', 'noopener noreferrer')
            }
            continue
          }
          if (tag === 'img' && name === 'src') {
            const safe = normalizeUrl(value, 'img')
            if (!safe) {

              el.remove()
            } else {
              el.setAttribute('src', safe)
            }
            continue
          }

          el.setAttribute(attr.name, value)
        }
      }

      return container.innerHTML
    } catch (e) {

      return '<pre>' + escapeHtml(rawHtml) + '</pre>'
    }
  }

  function createCopyButton(targetText) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'copy-button'
    button.setAttribute('aria-label', t('ui.copy.label'))
    button.title = t('ui.copy.label')

    const COPY_ICON_SVG =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 21" fill="none" aria-hidden="true" focusable="false"><path d="M12.5 3.60938C13.3284 3.60938 14 4.28095 14 5.10938V6.60938H15.5C16.3284 6.60938 17 7.28095 17 8.10938V16.1094C17 16.9378 16.3284 17.6094 15.5 17.6094H7.5C6.67157 17.6094 6 16.9378 6 16.1094V14.6094H4.5C3.67157 14.6094 3 13.9378 3 13.1094V5.10938C3 4.28095 3.67157 3.60938 4.5 3.60938H12.5ZM14 13.1094C14 13.9378 13.3284 14.6094 12.5 14.6094H7V16.1094C7 16.3855 7.22386 16.6094 7.5 16.6094H15.5C15.7761 16.6094 16 16.3855 16 16.1094V8.10938C16 7.83323 15.7761 7.60938 15.5 7.60938H14V13.1094ZM4.5 4.60938C4.22386 4.60938 4 4.83323 4 5.10938V13.1094C4 13.3855 4.22386 13.6094 4.5 13.6094H12.5C12.7761 13.6094 13 13.3855 13 13.1094V5.10938C13 4.83323 12.7761 4.60938 12.5 4.60938H4.5Z" fill="currentColor"></path></svg>'
    button.innerHTML = COPY_ICON_SVG

    let lastClickAt = 0

    button.addEventListener('click', async () => {

      const now = Date.now()
      if (now - lastClickAt < 250) return
      lastClickAt = now

      try {
        await navigator.clipboard.writeText(String(targetText || ''))
        button.classList.add('copied')
        button.classList.remove('error')
        button.title = t('ui.copy.success')
        setTimeout(() => {
          button.classList.remove('copied')
          button.title = t('ui.copy.label')
        }, 2000)
      } catch (err) {
        button.classList.add('error')
        button.classList.remove('copied')
        button.title = t('ui.copy.failed')
        setTimeout(() => {
          button.classList.remove('error')
          button.title = t('ui.copy.label')
        }, 2000)
      }
    })

    return button
  }

  function processCodeBlocks(container) {
    if (!container) return

    const codeBlocks = container.querySelectorAll('pre')
    codeBlocks.forEach(pre => {

      if (pre.parentElement && pre.parentElement.classList.contains('code-block-container')) {
        return
      }

      const wrapper = document.createElement('div')
      wrapper.className = 'code-block-container'

      pre.parentNode.insertBefore(wrapper, pre)
      wrapper.appendChild(pre)

      const codeElement = pre.querySelector('code')
      let language = 'text'
      if (codeElement && codeElement.className) {
        const m = codeElement.className.match(/language-([\w-]+)/)
        if (m) language = m[1]
      }

      const toolbar = document.createElement('div')
      toolbar.className = 'code-toolbar'

      if (language && language !== 'text') {
        const label = document.createElement('span')
        label.className = 'language-label'
        label.textContent = String(language).toUpperCase()
        toolbar.appendChild(label)
      }

      const textToCopy = codeElement ? codeElement.textContent || '' : pre.textContent || ''
      toolbar.appendChild(createCopyButton(textToCopy))

      wrapper.appendChild(toolbar)
    })
  }

  window.MathJax = window.MathJax || {
    tex: {
      inlineMath: [
        ['$', '$'],
        ['\\(', '\\)']
      ],
      displayMath: [
        ['$$', '$$'],
        ['\\[', '\\]']
      ],
      processEscapes: true,
      processEnvironments: true,
      packages: { '[+]': ['ams', 'newcommand', 'configmacros'] },
      tags: 'ams'
    },
    options: {
      skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
      ignoreHtmlClass: 'tex2jax_ignore',
      processHtmlClass: 'tex2jax_process'
    },
    startup: {
      ready: () => {
        try {
          MathJax.startup.defaultReady()
        } catch (e) {

        }

        if (window._mathJaxPendingElements && window.MathJax && window.MathJax.typesetPromise) {
          const pending = window._mathJaxPendingElements.slice()
          window._mathJaxPendingElements = []
          pending.forEach(el => {
            window.MathJax.typesetPromise([el]).catch(() => {})
          })
        }
      }
    }
  }

  window._mathJaxLoading = window._mathJaxLoading || false
  window._mathJaxLoaded = window._mathJaxLoaded || false
  window._mathJaxPendingElements = window._mathJaxPendingElements || []

  function hasMathContent(text) {
    if (!text) return false
    const mathPatterns = [
      /\$[^$]+\$/,
      /\$\$[^$]+\$\$/,
      /\\\([^)]+\\\)/,
      /\\\[[^\]]+\\\]/
    ]
    return mathPatterns.some(pattern => pattern.test(text))
  }

  function loadMathJaxIfNeeded(element, text) {
    if (!element) return
    const content = text || element.textContent || ''
    if (!hasMathContent(content)) return

    if (window._mathJaxLoaded && window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise([element]).catch(() => {})
      return
    }

    window._mathJaxPendingElements.push(element)

    if (window._mathJaxLoading) return

    window._mathJaxLoading = true

    const existing = document.getElementById('MathJax-script')
    if (existing) return

    const script = document.createElement('script')
    script.id = 'MathJax-script'
    script.async = true

    script.src =
      (MATHJAX_SCRIPT_URL ? String(MATHJAX_SCRIPT_URL) : '') ||
      (SERVER_URL ? SERVER_URL + '/static/js/tex-mml-chtml.js' : '')

    if (CSP_NONCE) {
      try {
        script.setAttribute('nonce', CSP_NONCE)
      } catch (e) {

      }
    }
    script.onload = function () {
      window._mathJaxLoaded = true
      window._mathJaxLoading = false
    }
    script.onerror = function () {
      window._mathJaxLoading = false
    }
    document.head.appendChild(script)
  }

  function updateHeaderChip(label) {
    const chip = document.getElementById('taskHeaderChip')
    if (!chip) return
    if (typeof label === 'string' && label.trim() !== '') {
      const text = label.trim().slice(0, 16)
      chip.textContent = text
      chip.classList.remove('hidden')
      chip.setAttribute('aria-label', text)
    } else {
      chip.textContent = ''
      chip.classList.add('hidden')
      chip.removeAttribute('aria-label')
    }
  }

  function updateLoopContext(task) {
    const container = document.getElementById('taskLoopContext')
    if (!container) return

    function clean(value) {
      return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
    }
    const loopId = clean(task && task.loop_id)
    const loopPhase = clean(task && task.loop_phase)
    const iterLabel = clean(task && task.iteration_label)
    const objective = clean(task && task.loop_objective)
    const criteria = clean(task && task.success_criteria)

    if (typeof updateLoopHistoryToggle === 'function') {
      updateLoopHistoryToggle(loopId)
    }

    if (!loopId && !loopPhase && !iterLabel && !objective && !criteria) {
      container.classList.add('hidden')
      return
    }

    function setChip(elementId, value) {
      const el = document.getElementById(elementId)
      if (!el) return
      if (value) {
        el.textContent = value
        el.classList.remove('hidden')
      } else {
        el.textContent = ''
        el.classList.add('hidden')
      }
    }
    setChip('loopChipId', loopId)
    setChip('loopChipPhase', loopPhase)
    setChip('loopChipIter', iterLabel)

    function setLine(lineId, valueId, value) {
      const line = document.getElementById(lineId)
      const valueEl = document.getElementById(valueId)
      if (!line || !valueEl) return
      if (value) {
        valueEl.textContent = value
        line.classList.remove('hidden')
      } else {
        valueEl.textContent = ''
        line.classList.add('hidden')
      }
    }
    setLine('loopObjectiveLine', 'loopObjectiveValue', objective)
    setLine('loopCriteriaLine', 'loopCriteriaValue', criteria)

    container.classList.remove('hidden')
  }

  let currentLoopId = null

  function updateLoopHistoryToggle(loopId) {
    const toggle = document.getElementById('loopHistoryToggle')
    if (!toggle) return
    if (currentLoopId !== loopId) {
      currentLoopId = loopId
      collapseLoopHistory()
    }
    if (loopId) {
      toggle.classList.remove('hidden')
      if (!toggle.dataset.bound) {
        toggle.dataset.bound = '1'
        toggle.addEventListener('click', toggleLoopHistory)
      }
    } else {
      toggle.classList.add('hidden')
    }
  }

  function collapseLoopHistory() {
    const toggle = document.getElementById('loopHistoryToggle')
    const list = document.getElementById('loopHistoryList')
    const count = document.getElementById('loopHistoryCount')
    if (toggle) {
      toggle.setAttribute('aria-expanded', 'false')
      toggle.classList.remove('expanded')
    }
    if (list) {
      list.classList.add('hidden')
      list.textContent = ''
    }
    if (count) count.textContent = ''
  }

  function renderLoopHistoryMessage(list, message) {
    const row = document.createElement('div')
    row.className = 'loop-history-empty'
    row.textContent = message
    list.appendChild(row)
  }

  function buildLoopHistoryRow(round) {
    const row = document.createElement('div')
    row.className = 'loop-history-row'
    row.setAttribute('role', 'listitem')

    const head = document.createElement('div')
    head.className = 'loop-history-row-head'

    const iter = document.createElement('span')
    iter.className = 'loop-history-iter'
    iter.textContent =
      (typeof round.iteration_label === 'string' && round.iteration_label) ||
      (typeof round.task_id === 'string' ? round.task_id.slice(0, 12) : '—')
    head.appendChild(iter)

    if (typeof round.loop_phase === 'string' && round.loop_phase) {
      const phase = document.createElement('span')
      phase.className = 'loop-history-phase'
      phase.textContent = round.loop_phase
      head.appendChild(phase)
    }

    if (typeof round.completed_at === 'string' && round.completed_at) {
      const time = document.createElement('span')
      time.className = 'loop-history-time'
      const parsed = new Date(round.completed_at)
      time.textContent = isNaN(parsed.getTime())
        ? round.completed_at
        : parsed.toLocaleString()
      head.appendChild(time)
    }
    row.appendChild(head)

    const verdict = round.verdict && typeof round.verdict === 'object' ? round.verdict : {}
    const parts = []
    if (typeof verdict.user_input === 'string' && verdict.user_input.trim()) {
      parts.push(verdict.user_input.trim())
    }
    if (Array.isArray(verdict.selected_options) && verdict.selected_options.length) {
      parts.push('[' + verdict.selected_options.join(', ') + ']')
    }
    if (typeof verdict.image_count === 'number' && verdict.image_count > 0) {
      parts.push('(+' + verdict.image_count + ' img)')
    }
    if (parts.length) {
      const body = document.createElement('div')
      body.className = 'loop-history-verdict'
      body.textContent = parts.join(' ')
      row.appendChild(body)
    }
    return row
  }

  async function toggleLoopHistory() {
    const toggle = document.getElementById('loopHistoryToggle')
    const list = document.getElementById('loopHistoryList')
    if (!toggle || !list) return

    if (toggle.getAttribute('aria-expanded') === 'true') {
      collapseLoopHistory()
      return
    }

    const loopId = currentLoopId
    if (!loopId) return

    toggle.setAttribute('aria-expanded', 'true')
    toggle.classList.add('expanded')
    list.textContent = ''
    list.classList.remove('hidden')

    let loop = null
    try {
      const resp = await fetch(SERVER_URL + '/api/loops', { cache: 'no-store' })
      if (!resp.ok) throw new Error('HTTP ' + resp.status)
      const data = await resp.json()
      if (data && data.success && Array.isArray(data.loops)) {
        loop = data.loops.find(l => l && l.loop_id === loopId) || null
      }
    } catch (e) {
      renderLoopHistoryMessage(list, t('ui.loop.historyError'))
      return
    }

    if (currentLoopId !== loopId) return
    if (toggle.getAttribute('aria-expanded') !== 'true') return

    const rounds = loop && Array.isArray(loop.rounds) ? loop.rounds : []
    const countEl = document.getElementById('loopHistoryCount')
    if (countEl) countEl.textContent = rounds.length ? String(rounds.length) : ''

    if (!rounds.length) {
      renderLoopHistoryMessage(list, t('ui.loop.historyEmpty'))
      return
    }

    for (let r = rounds.length - 1; r >= 0; r--) {
      const round = rounds[r]
      if (!round || typeof round !== 'object') continue
      list.appendChild(buildLoopHistoryRow(round))
    }
  }

  function updateFeedbackPlaceholder(placeholder) {
    const textarea = document.getElementById('feedbackText')
    if (!textarea) return
    if (typeof placeholder === 'string' && placeholder.trim() !== '') {
      textarea.setAttribute('placeholder', placeholder)
    } else {
      const defaultText = t('ui.form.placeholder')
      if (typeof defaultText === 'string' && defaultText) {
        textarea.setAttribute('placeholder', defaultText)
      }
    }
  }

  function updateYesnoButtonGroup(questionType) {
    const group = document.getElementById('yesnoButtonGroup')
    const wrapper = document.querySelector('.textarea-wrapper')
    if (!group) return
    if (questionType === 'yesno') {
      group.classList.remove('hidden')

      if (wrapper && wrapper.classList) wrapper.classList.remove('hidden')

      try {
        const textarea = document.getElementById('feedbackText')
        const taskPlaceholder =
          currentConfig && typeof currentConfig.feedback_placeholder === 'string'
            ? currentConfig.feedback_placeholder.trim()
            : ''
        if (textarea && !taskPlaceholder) {
          const hint = t('ui.form.yesnoSupplementPlaceholder')
          if (typeof hint === 'string' && hint) {
            textarea.setAttribute('placeholder', hint)
          }
        }
      } catch (e) {

      }
      syncYesnoSelectedStyles()
    } else {
      group.classList.add('hidden')
      if (wrapper && wrapper.classList) wrapper.classList.remove('hidden')
    }
  }

  function handleYesnoToggleClick(value) {
    const taskId =
      activeTaskId || (currentConfig && currentConfig.task_id) || null
    if (!taskId) return
    if (taskYesnoSelections[taskId] === value) {
      delete taskYesnoSelections[taskId]
    } else {
      taskYesnoSelections[taskId] = value
    }
    syncYesnoSelectedStyles()
    schedulePersistUiState()
  }

  function syncYesnoSelectedStyles() {
    const group = document.getElementById('yesnoButtonGroup')
    if (!group) return
    const taskId =
      activeTaskId || (currentConfig && currentConfig.task_id) || null
    const selection = taskId ? taskYesnoSelections[taskId] : undefined
    const pairs = [
      ['yesnoYesBtn', 'yes'],
      ['yesnoNoBtn', 'no']
    ]
    for (const [btnId, value] of pairs) {
      const btn = document.getElementById(btnId)
      if (!btn) continue
      const isSelected = selection === value
      btn.classList.toggle('selected', isSelected)
      btn.setAttribute('aria-pressed', isSelected ? 'true' : 'false')
    }
  }

  function getActiveYesnoSelection() {
    const taskId =
      activeTaskId || (currentConfig && currentConfig.task_id) || null
    if (!taskId) return null
    const selection = taskYesnoSelections[taskId]
    return selection === 'yes' || selection === 'no' ? selection : null
  }

  function findActiveTaskFromAllTasks() {
    try {
      if (!Array.isArray(allTasks)) return null
      if (activeTaskId) {
        const byId = allTasks.find(t => t && t.task_id === activeTaskId)
        if (byId) return byId
      }
      return allTasks.find(t => t && t.status === 'active') || null
    } catch (e) {
      return null
    }
  }

  function updateCountdownControls(task) {
    const controls = document.getElementById('countdownControls')
    if (!controls) return
    const extendBtn = document.getElementById('countdownExtendBtn')
    const freezeBtn = document.getElementById('countdownFreezeBtn')

    const target = task || findActiveTaskFromAllTasks()
    const hasCountdown =
      target &&
      target.status !== 'completed' &&
      typeof target.auto_resubmit_timeout === 'number' &&
      target.auto_resubmit_timeout > 0

    if (!hasCountdown) {
      controls.classList.add('hidden')
      if (extendBtn) extendBtn.disabled = true
      if (freezeBtn) freezeBtn.disabled = true
      return
    }

    controls.classList.remove('hidden')
    if (freezeBtn) freezeBtn.disabled = false
    if (extendBtn) {
      const atLimit =
        typeof target.extends_used === 'number' &&
        typeof target.extends_max === 'number' &&
        target.extends_used >= target.extends_max
      extendBtn.disabled = atLimit
      extendBtn.title = atLimit
        ? t('ui.countdown.extendLimitReached')
        : t('ui.countdown.extendTitle')
    }
  }

  function handleCountdownExtendClick() {
    const extendBtn = document.getElementById('countdownExtendBtn')
    if (!extendBtn || extendBtn.disabled) return
    const target = findActiveTaskFromAllTasks()
    const taskId = (target && target.task_id) || activeTaskId
    if (!taskId) return
    extendBtn.disabled = true
    fetch(SERVER_URL + '/api/tasks/' + encodeURIComponent(taskId) + '/extend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seconds: 60 })
    })
      .then(resp => resp.json().then(data => ({ ok: resp.ok, data })))
      .then(res => {
        if (!res.ok || !res.data || !res.data.success) {
          const code = (res.data && res.data.code) || 'unknown'
          if (code !== 'extends_limit_reached') {
            showToast(t('ui.countdown.extendFailed'), { kind: 'error' })
            extendBtn.disabled = false
          }
          if (target && res.data && typeof res.data.extends_used === 'number') {
            target.extends_used = res.data.extends_used
            target.extends_max = res.data.extends_max || target.extends_max
          }
          updateCountdownControls(target)
          return
        }
        const data = res.data
        const newRemaining = data.new_remaining_time
        if (typeof newRemaining === 'number') {
          taskDeadlines[taskId] = getAdjustedNowSeconds() + newRemaining
          if (lastCountdownTaskId === taskId) {
            remainingSeconds = Math.max(0, Math.floor(newRemaining))
          }
        }
        if (target) {
          target.extends_used = data.extends_used
          target.extends_max = data.extends_max
          target.auto_resubmit_timeout = data.new_auto_resubmit_timeout
          target.remaining_time = newRemaining
        }
        updateCountdownControls(target)
        log('Countdown extended for ' + taskId + ': +60s')
      })
      .catch(e => {
        log('Extend countdown network error: ' + e)
        showToast(t('ui.countdown.extendFailed'), { kind: 'error' })
        extendBtn.disabled = false
      })
  }

  function handleCountdownFreezeClick() {
    const freezeBtn = document.getElementById('countdownFreezeBtn')
    if (!freezeBtn || freezeBtn.disabled) return
    const target = findActiveTaskFromAllTasks()
    const taskId = (target && target.task_id) || activeTaskId
    if (!taskId) return
    freezeBtn.disabled = true
    fetch(SERVER_URL + '/api/tasks/' + encodeURIComponent(taskId) + '/freeze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
      .then(resp => resp.json().then(data => ({ ok: resp.ok, data })))
      .then(res => {
        if (!res.ok || !res.data || !res.data.success) {
          const code = (res.data && res.data.code) || 'unknown'
          showToast(
            code === 'already_frozen'
              ? t('ui.countdown.freezeAlreadyFrozen')
              : t('ui.countdown.freezeFailed'),
            { kind: 'error' }
          )
          freezeBtn.disabled = false
          return
        }
        if (target) {
          target.auto_resubmit_timeout = 0
          target.remaining_time = 0
        }
        try {
          delete taskDeadlines[taskId]
        } catch (e) {

        }
        if (lastCountdownTaskId === taskId) {
          stopCountdown()
        }
        updateCountdownControls(target)
        log('Countdown frozen for ' + taskId)
        setTimeout(() => requestImmediateRefresh(), 300)
      })
      .catch(e => {
        log('Freeze countdown network error: ' + e)
        showToast(t('ui.countdown.freezeFailed'), { kind: 'error' })
        freezeBtn.disabled = false
      })
  }

  function isUserActivelyTyping() {
    return lastFeedbackTypingAtMs > 0 && Date.now() - lastFeedbackTypingAtMs < TYPING_HOLD_IDLE_MS
  }

  function maybeAutoExtendCountdownForTyping(taskId, remaining) {
    if (!taskId) return
    if (remaining <= 0 || remaining > TYPING_HOLD_TRIGGER_S) return
    if (!isUserActivelyTyping()) return
    if (typingAutoExtendInFlight) return
    if (typingAutoExtendBlockedTasks[taskId]) return

    typingAutoExtendInFlight = true
    fetch(SERVER_URL + '/api/tasks/' + encodeURIComponent(taskId) + '/extend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seconds: 60 })
    })
      .then(resp => resp.json().then(data => ({ ok: resp.ok, data })))
      .then(res => {
        if (!res.ok || !res.data || !res.data.success) {
          const code = (res.data && res.data.code) || 'unknown'
          if (code === 'extends_limit_reached') {

            typingAutoExtendBlockedTasks[taskId] = true
          }
          log('Typing auto-extend rejected for ' + taskId + ': ' + code)
          return
        }
        const newRemaining = res.data.new_remaining_time
        if (typeof newRemaining === 'number') {
          taskDeadlines[taskId] = getAdjustedNowSeconds() + newRemaining
          if (lastCountdownTaskId === taskId) {
            remainingSeconds = Math.max(0, Math.floor(newRemaining))
          }
        }
        log('Typing auto-extend applied for ' + taskId + ': +60s')
      })
      .catch(e => {
        log('Typing auto-extend network error: ' + e)
      })
      .finally(() => {
        typingAutoExtendInFlight = false
      })
  }

  function startCountdown(totalSeconds, taskId, initialRemaining, deadline) {

    stopCountdown()

    if (!totalSeconds || totalSeconds <= 0) {
      log('Invalid countdown seconds: ' + totalSeconds)
      return
    }

    if (taskId && typeof deadline === 'number') {
      taskDeadlines[taskId] = deadline
    }

    if (typeof initialRemaining === 'number') {
      remainingSeconds = Math.max(0, Math.floor(initialRemaining))
    } else if (taskId && typeof taskDeadlines[taskId] === 'number') {
      remainingSeconds = Math.max(0, Math.floor(taskDeadlines[taskId] - getAdjustedNowSeconds()))
    } else {
      remainingSeconds = Math.max(0, Math.floor(totalSeconds))
    }
    lastCountdownTaskId = taskId
    log('Starting countdown: ' + remainingSeconds + 's, task: ' + taskId)

    function tick() {

      if (lastCountdownTaskId !== taskId) {
        stopCountdown()
        return
      }

      if (taskId && typeof taskDeadlines[taskId] === 'number') {
        remainingSeconds = Math.max(0, Math.floor(taskDeadlines[taskId] - getAdjustedNowSeconds()))
      } else {
        remainingSeconds = remainingSeconds - 1
      }

      maybeAutoExtendCountdownForTyping(taskId, remainingSeconds)

      if (remainingSeconds <= 0) {

        if (isUserActivelyTyping()) {
          return
        }
        autoSubmit()
      }
    }

    countdownTimer = setInterval(tick, 1000)
  }

  function stopCountdown() {
    if (countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
    lastCountdownTaskId = null
  }

  async function autoSubmit() {
    const taskId = lastCountdownTaskId
    log('Countdown ended, auto-resubmitting')
    stopCountdown()

    const now = Date.now()
    const RETRY_INTERVAL_MS = 30 * 1000
    if (taskId) {
      const last = autoSubmitAttempted[taskId]
      if (typeof last === 'number' && last > 0 && now - last < RETRY_INTERVAL_MS) {
        return
      }
    }

    try {
      if (submitInFlight || (submitBackoffUntilMs && now < submitBackoffUntilMs)) {
        return
      }
    } catch (e) {

    }

    if (taskId) {
      autoSubmitAttempted[taskId] = now
    }

    const typedText = collectTypedFeedbackForAutoSubmit(taskId)
    const typedOptions = collectSelectedOptionsForAutoSubmit()
    if ((typedText && typedText.trim()) || typedOptions.length > 0) {
      log(
        'Auto-submitting user-typed content for ' +
          (taskId || '(unknown)') +
          ' (' +
          (typedText || '').length +
          ' chars, ' +
          typedOptions.length +
          ' options)'
      )
      const okTyped = await submitWithData(typedText || '', typedOptions, taskId)
      if (okTyped === null && taskId) {
        try {
          delete autoSubmitAttempted[taskId]
        } catch (e) {

        }
      }
      setTimeout(() => requestImmediateRefresh(), 500)
      return
    }

    let defaultMessage = ''
    try {
      const prompts = await fetchFeedbackPrompts()
      if (prompts && prompts.resubmit_prompt) {
        defaultMessage = String(prompts.resubmit_prompt)
      }
    } catch (e) {

    }
    if (!defaultMessage) {
      try {
        vscode.postMessage({
          type: 'log',
          level: 'warn',
          message:
            'Skip auto-submit for ' +
            (taskId || '(unknown)') +
            ': resubmit_prompt not configured or unavailable'
        })
      } catch (e) {

      }
      if (taskId) {
        try {
          delete autoSubmitAttempted[taskId]
        } catch (e) {

        }
      }
      return
    }

    const ok = await submitWithData(defaultMessage, [], taskId)

    if (ok === null && taskId) {
      try {
        delete autoSubmitAttempted[taskId]
      } catch (e) {

      }
    }

    setTimeout(() => requestImmediateRefresh(), 500)
  }

  function collectTypedFeedbackForAutoSubmit(taskId) {
    try {
      const feedbackTextEl = document.getElementById('feedbackText')
      if (
        feedbackTextEl &&
        typeof feedbackTextEl.value === 'string' &&
        feedbackTextEl.value.trim()
      ) {
        return feedbackTextEl.value
      }
      if (taskId && typeof taskTextareaContents[taskId] === 'string') {
        return taskTextareaContents[taskId]
      }
    } catch (e) {

    }
    return ''
  }

  function collectSelectedOptionsForAutoSubmit() {
    const selected = []
    try {
      if (currentConfig && currentConfig.predefined_options) {
        currentConfig.predefined_options.forEach((option, index) => {
          const checkbox = document.getElementById('option-' + index)
          if (checkbox && checkbox.checked) {
            selected.push(option)
          }
        })
      }
    } catch (e) {

    }
    return selected
  }

  async function submitFeedback() {
    const feedbackTextEl = document.getElementById('feedbackText')
    if (!feedbackTextEl) {
      try {
        vscode.postMessage({
          type: 'log',
          level: 'debug',
          message: '[submit] feedbackText not in DOM; skip submit'
        })
      } catch (e) {

      }
      return
    }

    const yesnoSelection = getActiveYesnoSelection()
    let feedbackText = feedbackTextEl.value.trim()
    if (yesnoSelection) {
      feedbackText = feedbackText
        ? yesnoSelection + '\n\n' + feedbackText
        : yesnoSelection
    }

    const selected = []
    if (currentConfig && currentConfig.predefined_options) {
      currentConfig.predefined_options.forEach((option, index) => {
        const checkbox = document.getElementById('option-' + index)
        if (checkbox && checkbox.checked) {
          selected.push(option)
        }
      })
    }

    const submitOk = await submitWithData(feedbackText, selected)

    if (submitOk === true) {
      pendingInputFocusAtMs = Date.now()
    }
  }

  function applySubmitBackoffUi() {
    try {
      const submitBtn = document.getElementById('submitBtn')
      if (!submitBtn) return

      if (submitBackoffTimer) {
        clearTimeout(submitBackoffTimer)
        submitBackoffTimer = null
      }

      const now = Date.now()
      if (submitBackoffUntilMs && now >= submitBackoffUntilMs) {
        submitBackoffUntilMs = 0
      }

      if (submitBackoffUntilMs && now < submitBackoffUntilMs) {
        const leftSec = Math.max(1, Math.ceil((submitBackoffUntilMs - now) / 1000))
        submitBtn.disabled = true
        submitBtn.title = t('ui.submit.rateLimited', { seconds: leftSec })

        submitBackoffTimer = setTimeout(
          () => {
            submitBackoffTimer = null
            submitBackoffUntilMs = 0
            try {
              const b = document.getElementById('submitBtn')
              if (!b) return
              if (submitInFlight) return
              b.disabled = false
              b.title = t('ui.submit.label')
              b.innerHTML = submitBtnDefaultHtml || SUBMIT_BTN_FALLBACK_HTML
            } catch (e) {

            }
          },
          Math.max(0, submitBackoffUntilMs - now)
        )
      } else {

        submitBtn.title = t('ui.submit.label')
      }
    } catch (e) {

    }
  }

  async function submitWithData(text, options, taskIdOverride) {

    try {
      const now0 = Date.now()
      if (submitInFlight) {
        showToast(t('ui.submit.submitting'), {
          kind: 'info',
          timeoutMs: 1200,
          dedupeKey: 'submit:inflight'
        })
        return null
      }
      if (submitBackoffUntilMs && now0 < submitBackoffUntilMs) {
        const leftSec = Math.max(1, Math.ceil((submitBackoffUntilMs - now0) / 1000))
        applySubmitBackoffUi()
        showToast(t('ui.submit.rateLimited', { seconds: leftSec }), {
          kind: 'warn',
          timeoutMs: 1600,
          dedupeKey: 'submit:backoff'
        })
        return null
      }
    } catch (e) {

    }

    submitInFlight = true
    try {
      stopCountdown()

      const submitBtn = document.getElementById('submitBtn')
      if (submitBtn) {
        submitBtn.disabled = true
        submitBtn.innerHTML = SUBMIT_BTN_SPINNER_HTML
      }

      const formData = new FormData()
      formData.append('feedback_text', text)
      formData.append('selected_options', JSON.stringify(options))

      const taskIdToSubmit =
        taskIdOverride || (currentConfig && currentConfig.task_id) || activeTaskId

      const imageAppendResult = appendUploadedImagesToFormData(formData)
      if (imageAppendResult.dropped > 0) {
        renderUploadedImages()
        if (taskIdToSubmit) {
          syncImagesToTaskCache(taskIdToSubmit)
        }
        try {
          vscode.postMessage({
            type: 'log',
            level: 'warn',
            message:
              '[submit] dropped invalid cached image data before submit: ' +
              imageAppendResult.dropped
          })
        } catch (e) {

        }
      }

      if (taskIdToSubmit) {

        formData.append('task_id', taskIdToSubmit)
      }
      const submitPath = taskIdToSubmit
        ? '/api/tasks/' + encodeURIComponent(taskIdToSubmit) + '/submit'
        : '/api/submit'

      try {
        const textLen = (text || '').toString().length
        const optLen = Array.isArray(options) ? options.length : 0
        const imgLen = imageAppendResult.appended
        vscode.postMessage({
          type: 'log',
          level: 'debug',
          message:
            '[submit] start taskId=' +
            (taskIdToSubmit || '') +
            ' path=' +
            submitPath +
            ' textLen=' +
            textLen +
            ' options=' +
            optLen +
            ' images=' +
            imgLen
        })
      } catch (e) {

      }

      async function postFeedbackAttempt(path) {
        const requestOptions = {
          method: 'POST',
          body: formData
        }
        let attemptController = null
        let attemptTimeoutId = null

        if (typeof AbortController !== 'undefined') {
          try {
            attemptController = new AbortController()
            requestOptions.signal = attemptController.signal
            attemptTimeoutId = setTimeout(() => {
              try {
                attemptController.abort()
              } catch (e) {

              }
            }, SUBMIT_TIMEOUT_MS)
          } catch (e) {
            attemptController = null
          }
        }
        try {
          return await fetch(SERVER_URL + path, requestOptions)
        } finally {
          if (attemptTimeoutId) {
            clearTimeout(attemptTimeoutId)
          }
        }
      }

      let responsePath = submitPath
      let response = await postFeedbackAttempt(submitPath)

      if (!response.ok && response.status === 404 && taskIdToSubmit) {
        responsePath = '/api/submit'
        response = await postFeedbackAttempt(responsePath)
      }

      if (response.ok) {
        log('Feedback submitted successfully')
        try {
          vscode.postMessage({
            type: 'log',
            level: 'info',
            message: '[submit] ok taskId=' + (taskIdToSubmit || '') + ' path=' + responsePath
          })
        } catch (e) {

        }

        try {
          const textarea = document.getElementById('feedbackText')
          if (textarea) {
            textarea.value = ''
            autoResizeFeedbackTextarea(textarea)
          }
        } catch (e) {

        }
        uploadedImages = []
        renderUploadedImages()

        document.querySelectorAll('.option-item').forEach(item => {
          item.classList.remove('selected')
          const checkbox = item.querySelector('input')
          if (checkbox) {
            checkbox.checked = false
          }
        })

        if (taskIdToSubmit) {
          if (taskTextareaContents[taskIdToSubmit] !== undefined) {
            delete taskTextareaContents[taskIdToSubmit]
          }
          if (taskOptionsStates[taskIdToSubmit] !== undefined) {
            delete taskOptionsStates[taskIdToSubmit]
          }
          if (taskYesnoSelections[taskIdToSubmit] !== undefined) {
            delete taskYesnoSelections[taskIdToSubmit]
            syncYesnoSelectedStyles()
          }
          if (taskImages[taskIdToSubmit] !== undefined) {
            delete taskImages[taskIdToSubmit]
          }
        }

        showToast(t('ui.submit.success'), {
          kind: 'success',
          timeoutMs: 1400,
          dedupeKey: 'submit:ok'
        })

        setTimeout(() => requestImmediateRefresh(), 200)
        return true
      } else {

        if (response.status === 429) {
          const retryAfter =
            response.headers && response.headers.get
              ? String(response.headers.get('Retry-After') || '')
              : ''
          const retryAfterNum = parseInt(retryAfter, 10)
          const cooldownSec =
            Number.isFinite(retryAfterNum) && retryAfterNum > 0 ? Math.min(120, retryAfterNum) : 15
          submitBackoffUntilMs = Date.now() + cooldownSec * 1000
          applySubmitBackoffUi()

          const hint = retryAfter
            ? t('ui.submit.rateLimitHint', { seconds: retryAfter })
            : t('ui.submit.rateLimitHint', { seconds: cooldownSec })
          const msg = t('ui.submit.rateLimited429', { hint: hint })
          try {
            vscode.postMessage({ type: 'log', level: 'warn', message: msg })
          } catch (e) {

          }
          showToast(msg, { kind: 'warn', timeoutMs: 1800, dedupeKey: 'submit:429' })
          try {
            vscode.postMessage({
              type: 'log',
              level: 'warn',
              message:
                '[submit] 429 taskId=' + (taskIdToSubmit || '') + ' retryAfter=' + cooldownSec + 's'
            })
          } catch (e) {

          }
          return false
        }

        const msg = t('ui.submit.failed', { status: response.status })
        logError(msg)
      }
      return false
    } catch (error) {
      const isAbort = !!(
        error &&
        (error.name === 'AbortError' || String(error.name || '') === 'AbortError')
      )
      if (isAbort) {
        logError(t('ui.submit.timeoutCheckServer'))
      } else {
        const msg = error && error.message ? String(error.message) : String(error)
        logError(t('ui.submit.failedReason', { reason: msg }))
      }
      return false
    } finally {
      submitInFlight = false

      const submitBtn = document.getElementById('submitBtn')
      if (submitBtn) {
        submitBtn.disabled = false
        submitBtn.innerHTML = submitBtnDefaultHtml || SUBMIT_BTN_FALLBACK_HTML
      }

      applySubmitBackoffUi()
    }
  }

  const SUPPORTED_IMAGE_TYPES = [
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/bmp'
  ]
  const MAX_IMAGE_SIZE = 10 * 1024 * 1024
  const MAX_IMAGE_COUNT = 10
  const MAX_IMAGE_DIMENSION = 1920
  const COMPRESS_QUALITY = 0.8
  const MAX_RETURN_BYTES = 2 * 1024 * 1024
  const LARGE_FILE_BYTES = 5 * 1024 * 1024
  const LARGE_AREA = 4000000
  const MIN_DIMENSION = 320

  function sanitizeFileName(fileName) {
    try {
      const name = String(fileName || '').trim()
      if (!name) return ''
      return name
        .replace(/[<>:"/\\|?*]/g, '')
        .replace(/\s+/g, '_')
        .trim()
        .substring(0, 100)
    } catch (e) {
      return ''
    }
  }

  function getExtensionForMime(mimeType) {
    if (mimeType === 'image/png') return '.png'
    if (mimeType === 'image/webp') return '.webp'
    if (mimeType === 'image/jpeg') return '.jpg'
    if (mimeType === 'image/gif') return '.gif'
    if (mimeType === 'image/bmp') return '.bmp'
    if (mimeType === 'image/svg+xml') return '.svg'
    return ''
  }

  function replaceExtension(filename, newExt) {
    const safe = sanitizeFileName(filename) || 'image'
    if (!newExt) return safe
    const withoutExt = safe.replace(/\.[^/.]+$/, '')
    return withoutExt + newExt
  }

  function readAsDataURL(blob) {
    return new Promise((resolve, reject) => {
      try {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result || ''))
        reader.onerror = () => reject(new Error(t('ui.image.readFailed')))
        reader.readAsDataURL(blob)
      } catch (e) {
        reject(e)
      }
    })
  }

  function loadImageFromDataURL(dataUrl) {
    return new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error(t('ui.image.decodeFailed')))
      img.src = dataUrl
    })
  }

  function canvasToBlob(canvas, mimeType, quality) {
    return new Promise(resolve => {
      try {
        canvas.toBlob(blob => resolve(blob || null), mimeType, quality)
      } catch (e) {
        resolve(null)
      }
    })
  }

  async function decodeImageSource(file) {

    if (typeof createImageBitmap === 'function') {
      try {
        const bmp = await createImageBitmap(file)
        return {
          kind: 'bitmap',
          image: bmp,
          width: bmp.width,
          height: bmp.height,
          cleanup: () => {
            try {
              bmp.close()
            } catch (e) {

            }
          }
        }
      } catch (e) {

      }
    }

    const dataUrl = await readAsDataURL(file)
    const img = await loadImageFromDataURL(dataUrl)
    return {
      kind: 'img',
      image: img,
      width: img.naturalWidth || img.width || 0,
      height: img.naturalHeight || img.height || 0,
      cleanup: () => {}
    }
  }

  async function compressImageToDataURL(file) {
    if (!file || !file.type) {
      throw new Error(t('ui.image.invalid'))
    }
    if (!SUPPORTED_IMAGE_TYPES.includes(file.type)) {
      throw new Error(t('ui.image.unsupportedFormat', { type: String(file.type) }))
    }
    if (typeof file.size === 'number' && file.size > MAX_IMAGE_SIZE) {
      throw new Error(t('ui.image.tooLarge', { size: (file.size / 1024 / 1024).toFixed(2) }))
    }

    const rawName =
      sanitizeFileName(file.name) ||
      'image_' + Date.now() + (getExtensionForMime(file.type) || '.png')

    if (file.type === 'image/svg+xml' || file.type === 'image/gif') {
      const data = await readAsDataURL(file)
      return { name: rawName, data }
    }

    const forceCompress = file.size > MAX_RETURN_BYTES
    const isLargeFile = file.size > LARGE_FILE_BYTES

    const decoded = await decodeImageSource(file)
    try {
      let width = decoded.width || 0
      let height = decoded.height || 0
      if (!width || !height) {

        const data = await readAsDataURL(file)
        return { name: rawName, data }
      }

      const originalArea = width * height

      let maxDimension = MAX_IMAGE_DIMENSION
      if (forceCompress || isLargeFile || originalArea > LARGE_AREA) {
        maxDimension = Math.min(MAX_IMAGE_DIMENSION, 1200)
      }

      if (width > maxDimension || height > maxDimension) {
        const ratio = Math.min(maxDimension / width, maxDimension / height)
        width = Math.floor(width * ratio)
        height = Math.floor(height * ratio)
      }

      let currentWidth = width
      let currentHeight = height

      const canvas = document.createElement('canvas')
      const ctx = canvas.getContext('2d', {
        alpha: file.type === 'image/png',
        willReadFrequently: false
      })
      if (!ctx) {
        const data = await readAsDataURL(file)
        return { name: rawName, data }
      }

      canvas.width = currentWidth
      canvas.height = currentHeight
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(decoded.image, 0, 0, currentWidth, currentHeight)

      let quality = COMPRESS_QUALITY
      if (isLargeFile) {
        quality = Math.max(0.6, COMPRESS_QUALITY - 0.2)
      }
      if (forceCompress) {
        quality = Math.min(quality, 0.75)
      }

      const mimeCandidates = []
      if (file.type === 'image/png') {
        if (forceCompress || isLargeFile || originalArea > LARGE_AREA) {
          mimeCandidates.push('image/webp', 'image/jpeg')
        } else {
          mimeCandidates.push('image/png')
        }
      } else if (file.type === 'image/webp') {
        mimeCandidates.push('image/webp', 'image/jpeg')
      } else {
        if (forceCompress) {
          mimeCandidates.push('image/webp', 'image/jpeg')
        } else {
          mimeCandidates.push('image/jpeg')
        }
      }

      const encodeCurrent = async () => {
        for (let i = 0; i < mimeCandidates.length; i++) {
          const outType = mimeCandidates[i]
          const blob = await canvasToBlob(canvas, outType, quality)
          if (blob && blob.type) return blob
        }
        return null
      }

      let blob = await encodeCurrent()
      if (!blob) {
        const data = await readAsDataURL(file)
        return { name: rawName, data }
      }

      if (!forceCompress && blob.size >= file.size) {
        const data = await readAsDataURL(file)
        return { name: rawName, data }
      }

      if (forceCompress) {
        let attempt = 0
        const MAX_ATTEMPTS = 8
        while (blob.size > MAX_RETURN_BYTES && attempt < MAX_ATTEMPTS) {
          attempt++

          if (quality > 0.55) {
            quality = Math.max(0.55, quality - 0.1)
          } else {
            const nextWidth = Math.max(MIN_DIMENSION, Math.floor(currentWidth * 0.85))
            const nextHeight = Math.max(MIN_DIMENSION, Math.floor(currentHeight * 0.85))
            if (nextWidth === currentWidth && nextHeight === currentHeight) {
              break
            }
            currentWidth = nextWidth
            currentHeight = nextHeight
            canvas.width = currentWidth
            canvas.height = currentHeight
            ctx.imageSmoothingEnabled = true
            ctx.imageSmoothingQuality = 'high'
            ctx.drawImage(decoded.image, 0, 0, currentWidth, currentHeight)
          }

          const nextBlob = await encodeCurrent()
          if (!nextBlob) break
          blob = nextBlob
        }
      }

      const ext = getExtensionForMime(blob.type)
      const finalName = ext ? replaceExtension(rawName, ext) : rawName
      const data = await readAsDataURL(blob)
      return { name: finalName, data }
    } finally {
      try {
        decoded.cleanup && decoded.cleanup()
      } catch (e) {

      }
    }
  }

  function handleImageSelect(e) {
    const target = e && e.target
    const files = target && target.files ? target.files : []
    processImages(files)

    if (target) target.value = ''
  }

  function handlePaste(e) {
    const clipboardData = e && e.clipboardData
    if (!clipboardData) return

    let imageFiles = []
    try {
      if (WEBVIEW_HELPERS && typeof WEBVIEW_HELPERS.collectImageFilesFromClipboard === 'function') {
        imageFiles = WEBVIEW_HELPERS.collectImageFilesFromClipboard(clipboardData)
      }
    } catch (err) {
      imageFiles = []
    }

    if (!imageFiles.length) {
      const items = clipboardData.items || []
      for (let i = 0; i < items.length; i++) {
        const item = items[i]
        if (item && item.type && item.type.startsWith('image/')) {
          const file = item.getAsFile()
          if (file) {
            imageFiles.push(file)
          }
        }
      }
    }

    if (imageFiles.length > 0) {
      const pastedText = (
        clipboardData.getData('text/plain') ||
        clipboardData.getData('text') ||
        ''
      ).trim()
      if (!pastedText) {
        e.preventDefault()
      }
      processImages(imageFiles)
      log('Pasted ' + imageFiles.length + ' image(s) from clipboard')
    }
  }

  async function processImages(files) {
    const targetTaskId = activeTaskId || (currentConfig && currentConfig.task_id) || ''
    const initialTargetImages = Array.isArray(uploadedImages) ? uploadedImages : []
    const fileCount =
      files && typeof files.length === 'number' && Number.isFinite(files.length)
        ? Math.max(0, Math.floor(files.length))
        : 0

    for (let fileIndex = 0; fileIndex < fileCount; fileIndex += 1) {
      const file =
        files[fileIndex] ||
        (files && typeof files.item === 'function' ? files.item(fileIndex) : null)
      if (!file) continue
      const imagesForLimit = getImageUploadTargetImages(targetTaskId, initialTargetImages)
      if (imagesForLimit.length + getPendingImageUploadCount(targetTaskId) >= MAX_IMAGE_COUNT) {
        const msg = t('ui.image.tooManyFiles', { count: MAX_IMAGE_COUNT })
        logError(msg)
        vscode.postMessage({ type: 'showInfo', message: msg })
        break
      }

      incrementPendingImageUploadCount(targetTaskId)
      try {
        const processed = await compressImageToDataURL(file)
        if (!processed || !processed.data) continue
        if (!isTaskStillOpenForLocalState(targetTaskId)) continue
        const targetImages = getImageUploadTargetImages(targetTaskId, initialTargetImages)
        if (targetImages.length >= MAX_IMAGE_COUNT) {
          const msg = t('ui.image.tooManyFiles', { count: MAX_IMAGE_COUNT })
          logError(msg)
          vscode.postMessage({ type: 'showInfo', message: msg })
          break
        }

        targetImages.push({
          name: processed.name || sanitizeFileName(file.name) || 'image',
          data: processed.data
        })
        if (targetTaskId && activeTaskId && targetTaskId !== activeTaskId) {
          cacheImagesForTask(targetTaskId, targetImages)
        } else {
          if (targetImages !== uploadedImages) {
            uploadedImages = targetImages
          }
          renderUploadedImages()

          if (targetTaskId) {
            syncImagesToTaskCache(targetTaskId)
          } else if (activeTaskId) {
            syncImagesToTaskCache(activeTaskId)
          }
        }
      } catch (e) {
        const msg = t('ui.image.processingFailedReason', { reason: e && e.message ? e.message : String(e) })
        logError(msg)
        vscode.postMessage({ type: 'showInfo', message: msg })
      } finally {
        decrementPendingImageUploadCount(targetTaskId)
      }
    }
  }

  function renderUploadedImages() {
    const container = document.getElementById('uploadedImages')
    if (!container) return
    container.innerHTML = ''

    uploadedImages.forEach((image, index) => {
      const div = document.createElement('div')
      div.className = 'image-preview'

      const img = document.createElement('img')
      img.src = image.data

      img.alt = image && image.name ? String(image.name) : ''

      const removeBtn = document.createElement('button')
      removeBtn.className = 'image-remove'
      removeBtn.textContent = '×'
      removeBtn.addEventListener('click', () => removeImage(index))

      div.appendChild(img)
      div.appendChild(removeBtn)
      container.appendChild(div)
    })
  }

  function removeImage(index) {
    uploadedImages.splice(index, 1)
    renderUploadedImages()
    if (activeTaskId) {
      syncImagesToTaskCache(activeTaskId)
    }
  }

  function appendUploadedImagesToFormData(formData) {
    const sourceImages = Array.isArray(uploadedImages) ? uploadedImages : []
    const keptImages = []
    let appended = 0
    let dropped = 0

    sourceImages.forEach(imageData => {
      const data = imageData && imageData.data ? String(imageData.data) : ''
      const blob = dataURLtoBlob(data)
      if (!blob || typeof blob.size !== 'number' || blob.size <= 0) {
        dropped++
        return
      }

      const name = sanitizeFileName(imageData && imageData.name ? imageData.name : '') || 'image'
      formData.append('image_' + appended, blob, name)
      keptImages.push({ name, data })
      appended++
    })

    if (dropped > 0 || keptImages.length !== sourceImages.length) {
      uploadedImages = keptImages
    }

    return { appended, dropped }
  }

  function dataURLtoBlob(dataURL) {
    const raw = String(dataURL || '').trim()
    const commaIndex = raw.indexOf(',')
    if (commaIndex <= 0) return null

    const header = raw.slice(0, commaIndex).trim()
    const body = raw.slice(commaIndex + 1).replace(/\s+/g, '')
    const match = header.match(/^data:(image\/[a-z0-9.+-]+);base64$/i)
    if (!match || !body) return null

    const mime = match && match[1] ? match[1].toLowerCase() : 'application/octet-stream'
    if (!SUPPORTED_IMAGE_TYPES.includes(mime)) return null
    let bstr = ''
    try {
      bstr = atob(body)
    } catch (e) {
      return null
    }
    if (!bstr) return null

    let n = bstr.length
    const u8arr = new Uint8Array(n)
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n)
    }
    return new Blob([u8arr], { type: mime })
  }

  function handleVisibilityBenchmarkProbe(message) {
    try {
      var seq = message && typeof message.seq === 'number' ? message.seq : 0
      var hostSentAtMs =
        message && typeof message.hostSentAtMs === 'number' ? message.hostSentAtMs : 0
      var webviewReceivedAtMs = Date.now()
      var perfStart =
        typeof performance !== 'undefined' && typeof performance.now === 'function'
          ? performance.now()
          : 0
      var finish = function () {
        try {
          var perfEnd =
            typeof performance !== 'undefined' && typeof performance.now === 'function'
              ? performance.now()
              : perfStart
          var memory =
            typeof performance !== 'undefined' &&
            performance &&
            performance.memory &&
            typeof performance.memory === 'object'
              ? performance.memory
              : null
          vscode.postMessage({
            type: 'visibilityBenchmarkResult',
            seq: seq,
            hostSentAtMs: hostSentAtMs,
            webviewReceivedAtMs: webviewReceivedAtMs,
            webviewPaintedAtMs: Date.now(),
            paintLatencyMs: perfEnd - perfStart,
            usedJSHeapSize:
              memory && typeof memory.usedJSHeapSize === 'number'
                ? memory.usedJSHeapSize
                : null,
            totalJSHeapSize:
              memory && typeof memory.totalJSHeapSize === 'number'
                ? memory.totalJSHeapSize
                : null
          })
        } catch (e) {

        }
      }
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(function () {
          requestAnimationFrame(finish)
        })
      } else {
        setTimeout(finish, 0)
      }
    } catch (e) {

    }
  }

  window.addEventListener('message', event => {
    const message = event.data
    switch (message.type) {
      case 'refresh':
        requestImmediateRefresh()
        break
      case 'force-repaint':

        try {
          const body = document.body
          if (body && body.classList && typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(function () {
              try {
                body.classList.add('aiia-repainting')
              } catch (_) {

              }
              requestAnimationFrame(function () {
                try {
                  body.classList.remove('aiia-repainting')
                } catch (_) {

                }
              })
            })
          }
        } catch (_) {

        }
        break
      case 'clipboardText':
        handleClipboardTextMessage(message)
        break
      case 'visibility-benchmark-probe':
        handleVisibilityBenchmarkProbe(message)
        break
      case 'switchToTask':

        try {
          if (message.taskId) {
            const deepLinkTaskId = String(message.taskId)
            setTimeout(() => {
              try {
                if (deepLinkTaskId !== activeTaskId) {
                  switchToTask(deepLinkTaskId)
                }
              } catch (e) {
                log('switchToTask deep-link failed: ' + e)
              }
            }, 300)
          }
        } catch (e) {

        }
        break
    }
  })

  window.addEventListener('beforeunload', () => {
    stopPolling()
    stopCountdown()
    clearAllTabCountdowns()
    disposeNoContentLottieRecoveryHandlers()
    if (themeObserver) {
      try {
        themeObserver.disconnect()
      } catch (e) {

      }
      themeObserver = null
    }
    try {
      const settingsUi = getSettingsUiModule()
      if (settingsUi && typeof settingsUi.dispose === 'function') {
        settingsUi.dispose()
      }
    } catch (e) {

    }
  })

  function reportFatalError(prefix, err) {
    try {
      const msg = prefix + (err && err.message ? err.message : String(err))
      try {
        vscode.postMessage({ type: 'log', level: 'error', message: msg })
      } catch (e) {

      }
      try {
        vscode.postMessage({ type: 'error', message: msg })
      } catch (e) {

      }
      try {
        postNotificationEvent({
          title: 'AI Intervention Agent',
          message: msg,
          trigger: 'immediate',
          types: ['vscode'],
          metadata: { presentation: 'toast', severity: 'error', timeoutMs: 6000 },
          source: 'webview-ui',
          dedupeKey: 'fatal:' + String(prefix || '').slice(0, 30)
        })
      } catch (e) {

      }
      try {
        showToast(msg, {
          kind: 'error',
          timeoutMs: 3500,
          dedupeKey: 'fatal:' + String(prefix || '').slice(0, 30)
        })
      } catch (e) {

      }
    } catch (e) {

    }
  }

  window.addEventListener('error', e => {
    reportFatalError('Uncaught exception: ', e && e.error ? e.error : e)
    try {
      hideTabs()
      showNoContent()
    } catch (e2) {

    }

    try {
      hideBootSkeleton()
    } catch (_) {

    }
  })
  window.addEventListener('unhandledrejection', e => {
    reportFatalError('Unhandled Promise rejection: ', e && e.reason ? e.reason : e)
    try {
      hideTabs()
      showNoContent()
    } catch (e2) {

    }
    try {
      hideBootSkeleton()
    } catch (_) {

    }
  })

  try {
    init()
  } catch (e) {
    reportFatalError('Initialization failed: ', e)
    try {
      hideTabs()
      showNoContent()
    } catch (e2) {

    }

    try {
      hideBootSkeleton()
    } catch (_) {

    }
  }
})()
