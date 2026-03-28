;(function () {
  /* 轻量国际化模块（Web UI）：支持 JSON 语言包、参数插值、回退链、DOM 自动翻译 */

  var DEFAULT_LANG = 'en'
  var currentLang = DEFAULT_LANG
  var locales = {}

  function detectLang() {
    try {
      if (typeof window !== 'undefined' && window.__AIIA_I18N_LANG) {
        return normalizeLang(String(window.__AIIA_I18N_LANG))
      }
    } catch (e) { /* noop */ }
    try {
      if (typeof navigator !== 'undefined' && navigator.language) {
        return normalizeLang(navigator.language)
      }
    } catch (e) { /* noop */ }
    return DEFAULT_LANG
  }

  function normalizeLang(raw) {
    var s = String(raw || '').trim().toLowerCase()
    if (s.indexOf('zh') === 0) return 'zh-CN'
    if (s.indexOf('en') === 0) return 'en'
    return s || DEFAULT_LANG
  }

  function registerLocale(lang, data) {
    if (!lang || !data || typeof data !== 'object') return
    locales[normalizeLang(lang)] = data
  }

  function setLang(lang) {
    currentLang = normalizeLang(lang)
    document.documentElement.lang = currentLang === 'zh-CN' ? 'zh-CN' : 'en'
  }

  function getLang() { return currentLang }
  function getAvailableLangs() { return Object.keys(locales) }

  function resolve(key, lang) {
    var dict = locales[lang || currentLang]
    if (!dict) dict = locales[DEFAULT_LANG]
    if (!dict) return undefined
    var parts = String(key).split('.')
    var node = dict
    for (var i = 0; i < parts.length; i++) {
      if (node === null || node === undefined || typeof node !== 'object') return undefined
      node = node[parts[i]]
    }
    return typeof node === 'string' ? node : undefined
  }

  function t(key, params) {
    var val = resolve(key, currentLang)
    if (val === undefined && currentLang !== DEFAULT_LANG) {
      val = resolve(key, DEFAULT_LANG)
    }
    if (val === undefined) return key
    if (params && typeof params === 'object') {
      val = val.replace(/\{\{(\w+)\}\}/g, function (match, name) {
        return params[name] !== undefined ? String(params[name]) : match
      })
    }
    return val
  }

  function translateDOM(root) {
    var els = (root || document).querySelectorAll('[data-i18n]')
    for (var i = 0; i < els.length; i++) {
      var el = els[i]
      var key = el.getAttribute('data-i18n')
      if (!key) continue
      var val = t(key)
      if (val !== key) el.textContent = val
    }
    var attrs = (root || document).querySelectorAll('[data-i18n-title]')
    for (var j = 0; j < attrs.length; j++) {
      var attrEl = attrs[j]
      var attrKey = attrEl.getAttribute('data-i18n-title')
      if (!attrKey) continue
      var attrVal = t(attrKey)
      if (attrVal !== attrKey) attrEl.title = attrVal
    }
    var placeholders = (root || document).querySelectorAll('[data-i18n-placeholder]')
    for (var k = 0; k < placeholders.length; k++) {
      var phEl = placeholders[k]
      var phKey = phEl.getAttribute('data-i18n-placeholder')
      if (!phKey) continue
      var phVal = t(phKey)
      if (phVal !== phKey) phEl.placeholder = phVal
    }
  }

  async function loadLocale(lang, url) {
    try {
      var resp = await fetch(url, { cache: 'default' })
      if (!resp.ok) return false
      var data = await resp.json()
      registerLocale(lang, data)
      return true
    } catch (e) {
      return false
    }
  }

  async function init(options) {
    var opts = options && typeof options === 'object' ? options : {}

    if (opts.locales && typeof opts.locales === 'object') {
      var keys = Object.keys(opts.locales)
      for (var i = 0; i < keys.length; i++) {
        registerLocale(keys[i], opts.locales[keys[i]])
      }
    }

    var lang = opts.lang ? normalizeLang(opts.lang) : detectLang()

    if (opts.localeBaseUrl && !locales[lang]) {
      await loadLocale(lang, opts.localeBaseUrl + '/' + lang + '.json')
      if (lang !== DEFAULT_LANG && !locales[DEFAULT_LANG]) {
        await loadLocale(DEFAULT_LANG, opts.localeBaseUrl + '/' + DEFAULT_LANG + '.json')
      }
    }

    setLang(lang)

    if (opts.translateDOM !== false) {
      translateDOM()
    }
  }

  var api = {
    t: t,
    init: init,
    setLang: setLang,
    getLang: getLang,
    getAvailableLangs: getAvailableLangs,
    registerLocale: registerLocale,
    loadLocale: loadLocale,
    detectLang: detectLang,
    normalizeLang: normalizeLang,
    translateDOM: translateDOM,
    DEFAULT_LANG: DEFAULT_LANG
  }

  try { window.AIIA_I18N = api } catch (e) { /* noop */ }
})()
