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

  // RTL 语言 BCP-47 前缀白名单。保持精确匹配（ar / fa / he / iw / ps / ur /
  // yi / ug / ckb / ku / dv / sd），避免把 zh-Arab 之类混合脚本误判为 RTL。
  function langToDir(lang) {
    if (/^(ar|fa|he|iw|ps|ur|yi|ug|ckb|ku|dv|sd)(-|$)/i.test(String(lang || ''))) {
      return 'rtl'
    }
    return 'ltr'
  }

  function setLang(lang) {
    currentLang = normalizeLang(lang)
    try {
      var docEl = document.documentElement
      // 当前只支持 en / zh-CN（都是 LTR），但 <html dir> 必须始终显式，未来新增
      // RTL 语言时只需扩 langToDir 白名单即可随 setLang 自动切换方向。
      docEl.lang = currentLang === 'zh-CN' ? 'zh-CN' : currentLang === 'en' ? 'en' : currentLang
      docEl.dir = langToDir(currentLang)
    } catch (e) { /* noop */ }
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

  // 属性翻译映射表：[属性名, 设置方式]
  // setter 传 'property' 表示走 el[prop] = val（如 el.title / el.placeholder），
  // 传 'attribute' 表示走 el.setAttribute(attr, val)（如 aria-label 等标准 HTML 属性）
  var ATTR_BINDINGS = [
    { dataAttr: 'data-i18n-title', target: 'title', setter: 'property' },
    { dataAttr: 'data-i18n-placeholder', target: 'placeholder', setter: 'property' },
    { dataAttr: 'data-i18n-alt', target: 'alt', setter: 'property' },
    { dataAttr: 'data-i18n-aria-label', target: 'aria-label', setter: 'attribute' },
    { dataAttr: 'data-i18n-value', target: 'value', setter: 'property' }
  ]

  function translateDOM(root) {
    var scope = root || document
    var els = scope.querySelectorAll('[data-i18n]')
    for (var i = 0; i < els.length; i++) {
      var el = els[i]
      var key = el.getAttribute('data-i18n')
      if (!key) continue
      var val = t(key)
      if (val !== key) el.textContent = val
    }

    var htmlEls = scope.querySelectorAll('[data-i18n-html]')
    for (var h = 0; h < htmlEls.length; h++) {
      var hEl = htmlEls[h]
      var hKey = hEl.getAttribute('data-i18n-html')
      if (!hKey) continue
      var hVal = t(hKey)
      if (hVal !== hKey) hEl.innerHTML = hVal
    }

    for (var b = 0; b < ATTR_BINDINGS.length; b++) {
      var binding = ATTR_BINDINGS[b]
      var matches = scope.querySelectorAll('[' + binding.dataAttr + ']')
      for (var m = 0; m < matches.length; m++) {
        var mEl = matches[m]
        var mKey = mEl.getAttribute(binding.dataAttr)
        if (!mKey) continue
        var mVal = t(mKey)
        if (mVal === mKey) continue
        if (binding.setter === 'property') {
          mEl[binding.target] = mVal
        } else {
          mEl.setAttribute(binding.target, mVal)
        }
      }
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
