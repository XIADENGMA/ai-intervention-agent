;(function () {
  /* 轻量国际化模块：支持 JSON 语言包、参数插值、回退链 */

  var DEFAULT_LANG = 'en'
  var currentLang = DEFAULT_LANG
  var locales = {}

  function detectLang() {
    try {
      var injected =
        typeof globalThis !== 'undefined' && globalThis.__AIIA_I18N_LANG
          ? String(globalThis.__AIIA_I18N_LANG)
          : ''
      if (injected) return normalizeLang(injected)
    } catch (e) {
      // 忽略
    }
    try {
      if (typeof navigator !== 'undefined' && navigator.language) {
        return normalizeLang(navigator.language)
      }
    } catch (e) {
      // 忽略
    }
    return DEFAULT_LANG
  }

  function normalizeLang(raw) {
    var s = String(raw || '')
      .trim()
      .toLowerCase()
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
  }

  function getLang() {
    return currentLang
  }

  function getAvailableLangs() {
    return Object.keys(locales)
  }

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

  function init(options) {
    var opts = options && typeof options === 'object' ? options : {}
    if (opts.locales && typeof opts.locales === 'object') {
      var keys = Object.keys(opts.locales)
      for (var i = 0; i < keys.length; i++) {
        registerLocale(keys[i], opts.locales[keys[i]])
      }
    }
    if (opts.lang) {
      setLang(opts.lang)
    } else {
      setLang(detectLang())
    }

    try {
      var injectedLocale =
        typeof globalThis !== 'undefined' && globalThis.__AIIA_I18N_LOCALE
          ? globalThis.__AIIA_I18N_LOCALE
          : null
      var injectedLang =
        typeof globalThis !== 'undefined' && globalThis.__AIIA_I18N_LANG
          ? String(globalThis.__AIIA_I18N_LANG)
          : ''
      if (injectedLocale && typeof injectedLocale === 'object' && injectedLang) {
        registerLocale(injectedLang, injectedLocale)
      }
    } catch (e) {
      // 忽略
    }
  }

  // 自动注册注入的 locale 数据（由 webview.ts 通过内联 script 写入 globalThis）
  try {
    var _autoLocale =
      typeof globalThis !== 'undefined' && globalThis.__AIIA_I18N_LOCALE
        ? globalThis.__AIIA_I18N_LOCALE
        : null
    var _autoLang =
      typeof globalThis !== 'undefined' && globalThis.__AIIA_I18N_LANG
        ? String(globalThis.__AIIA_I18N_LANG)
        : ''
    if (_autoLocale && typeof _autoLocale === 'object' && _autoLang) {
      registerLocale(_autoLang, _autoLocale)
      setLang(_autoLang)
    }
  } catch (e) {
    // 忽略
  }

  // 批量注册所有预注入的 Locale（支持动态切换语言，无需重新渲染 webview）
  try {
    var _allLocales =
      typeof globalThis !== 'undefined' && globalThis.__AIIA_I18N_ALL_LOCALES
        ? globalThis.__AIIA_I18N_ALL_LOCALES
        : null
    if (_allLocales && typeof _allLocales === 'object') {
      var _locKeys = Object.keys(_allLocales)
      for (var _li = 0; _li < _locKeys.length; _li++) {
        var _lk = _locKeys[_li]
        if (_allLocales[_lk] && typeof _allLocales[_lk] === 'object') {
          registerLocale(_lk, _allLocales[_lk])
        }
      }
    }
  } catch (e) {
    // 忽略
  }

  var api = {
    t: t,
    init: init,
    setLang: setLang,
    getLang: getLang,
    getAvailableLangs: getAvailableLangs,
    registerLocale: registerLocale,
    detectLang: detectLang,
    normalizeLang: normalizeLang,
    DEFAULT_LANG: DEFAULT_LANG
  }

  try {
    globalThis.AIIA_I18N = api
  } catch (e) {
    try {
      window.AIIA_I18N = api
    } catch (_) {
      // 忽略
    }
  }
})()
