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

  // RTL 语言 BCP-47 前缀白名单（与 static/js/i18n.js 保持行为一致）。
  function langToDir(lang) {
    if (/^(ar|fa|he|iw|ps|ur|yi|ug|ckb|ku|dv|sd)(-|$)/i.test(String(lang || ''))) {
      return 'rtl'
    }
    return 'ltr'
  }

  function setLang(lang) {
    currentLang = normalizeLang(lang)
    try {
      if (typeof document !== 'undefined' && document.documentElement) {
        var docEl = document.documentElement
        docEl.lang = currentLang === 'zh-CN' ? 'zh-CN' : currentLang === 'en' ? 'en' : currentLang
        docEl.dir = langToDir(currentLang)
      }
    } catch (e) {
      // 忽略（无 DOM 环境下也要能直接 setLang 用于单测）
    }
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

  // 与 static/js/i18n.js::translateDOM 同签名同行为，保障 tri-state-panel-bootstrap.js
  // 等字节镜像共享脚本在 VSCode 端的 data-i18n 扫描能真正生效（详见 §T1 v3 §4 契约）。
  // 仅翻译直接命中的 key（miss 时 t() 返回 key 原值，此处 val === key 判断跳过赋值，
  // 避免 placeholder 误被覆写成 key）。不处理 data-i18n-version 插值以保持双端一致，
  // 该场景继续由 webview-ui.js::retranslateAllI18nElements 覆盖。
  function translateDOM(root) {
    var scope = root || (typeof document !== 'undefined' ? document : null)
    if (!scope || typeof scope.querySelectorAll !== 'function') return

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
    translateDOM: translateDOM,
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
