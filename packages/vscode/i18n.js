;(function () {
  /* 轻量国际化模块（VSCode webview）：
   *   - JSON 语言包 + 结构化回退链
   *   - {{param}} 简单插值
   *   - ICU MessageFormat subset：plural / select（P9·L3·G1）
   *   - data-i18n / data-i18n-* / data-i18n-html DOM 自动翻译
   *
   * ICU subset 语法（与 static/js/i18n.js 逐字节保持一致）：
   *   {argName, plural, =N {…} one {…} few {…} many {…} other {…}}
   *   {argName, select, optA {…} optB {…} other {…}}
   * plural 内的 # 替换为 argName 的本地化数字（Intl.NumberFormat）。
   * 复数类别由 Intl.PluralRules 选出——英语 one/other、俄语 one/few/
   * many/other、阿拉伯语六类齐。不支持嵌套子消息以保持实现极简。
   */

  var DEFAULT_LANG = 'en'
  var currentLang = DEFAULT_LANG
  var locales = {}

  // Intl.PluralRules 缓存：只按 locale 键，PluralRules 本身没有 options 需要
  // 区分。单独留这一个缓存表（而不是并入 _intlCache）是因为 _getPluralRules
  // 在 ICU 热路径上被高频调用，多一次 JSON.stringify + 字符串拼接都要避免。
  var _pluralRulesCache = {}

  function _getPluralRules(lang) {
    if (typeof Intl === 'undefined' || typeof Intl.PluralRules !== 'function') {
      return null
    }
    if (!_pluralRulesCache[lang]) {
      try {
        _pluralRulesCache[lang] = new Intl.PluralRules(lang)
      } catch (e) {
        _pluralRulesCache[lang] = null
      }
    }
    return _pluralRulesCache[lang]
  }

  // 通用 Intl 工厂缓存：按 (ctor, locale, JSON(options)) 三元组缓存实例。
  // 构造 DateTimeFormat / NumberFormat 都是毫秒级开销（尤其在低端移动
  // 设备上），按 options 复用可以把同一屏反复调用摊到 1 次构造。
  // 键用 JSON.stringify(options)：对于我们用到的 plain-object options 足够
  // 稳定；哈希冲突仅在同一 locale 内发生，且最坏结果是冷启动一次，不影响
  // 正确性。
  var _intlCache = {
    NumberFormat: {},
    DateTimeFormat: {},
    RelativeTimeFormat: {},
    ListFormat: {}
  }

  function _intlKey(lang, opts) {
    try {
      return lang + '|' + JSON.stringify(opts || {})
    } catch (e) {
      return lang + '|?'
    }
  }

  function _getIntl(ctor, lang, opts) {
    if (typeof Intl === 'undefined' || typeof Intl[ctor] !== 'function') return null
    var bucket = _intlCache[ctor]
    if (!bucket) return null
    var key = _intlKey(lang, opts)
    if (!(key in bucket)) {
      try {
        bucket[key] = new Intl[ctor](lang, opts || undefined)
      } catch (e) {
        bucket[key] = null
      }
    }
    return bucket[key]
  }

  function _getNumberFormat(lang) {
    return _getIntl('NumberFormat', lang, undefined)
  }

  function _findIcuBlock(str, from) {
    var i = from || 0
    while (i < str.length) {
      var open = str.indexOf('{', i)
      if (open === -1) return null
      if (str.charAt(open + 1) === '{') {
        var close = str.indexOf('}}', open + 2)
        if (close === -1) return null
        i = close + 2
        continue
      }
      var depth = 1
      var j = open + 1
      while (j < str.length && depth > 0) {
        var ch = str.charAt(j)
        if (ch === '{') depth++
        else if (ch === '}') depth--
        if (depth === 0) break
        j++
      }
      if (depth !== 0) return null
      var body = str.substring(open + 1, j)
      var commaIdx = body.indexOf(',')
      if (commaIdx === -1) {
        i = j + 1
        continue
      }
      var arg = body.substring(0, commaIdx).trim()
      var rest = body.substring(commaIdx + 1).trimStart()
      var kindMatch = rest.match(/^(plural|select)\s*,\s*/)
      if (!kindMatch) {
        i = j + 1
        continue
      }
      var kind = kindMatch[1]
      var optionsStr = rest.substring(kindMatch[0].length)
      return {
        start: open,
        end: j + 1,
        argName: arg,
        kind: kind,
        options: _parseIcuOptions(optionsStr)
      }
    }
    return null
  }

  function _parseIcuOptions(src) {
    var out = {}
    var i = 0
    var n = src.length
    while (i < n) {
      while (i < n && /\s/.test(src.charAt(i))) i++
      if (i >= n) break
      var keyStart = i
      while (i < n && !/\s/.test(src.charAt(i)) && src.charAt(i) !== '{') i++
      var key = src.substring(keyStart, i).trim()
      if (!key) break
      while (i < n && /\s/.test(src.charAt(i))) i++
      if (src.charAt(i) !== '{') break
      var depth = 1
      var bodyStart = i + 1
      i++
      while (i < n && depth > 0) {
        var ch = src.charAt(i)
        if (ch === '{') depth++
        else if (ch === '}') depth--
        if (depth === 0) break
        i++
      }
      if (depth !== 0) break
      out[key] = src.substring(bodyStart, i)
      i++
    }
    return out
  }

  function _selectPluralOption(options, count, lang) {
    var exactKey = '=' + String(count)
    if (Object.prototype.hasOwnProperty.call(options, exactKey)) {
      return options[exactKey]
    }
    var rules = _getPluralRules(lang)
    var category = rules ? rules.select(count) : count === 1 ? 'one' : 'other'
    if (Object.prototype.hasOwnProperty.call(options, category)) {
      return options[category]
    }
    if (Object.prototype.hasOwnProperty.call(options, 'other')) {
      return options.other
    }
    return ''
  }

  function _selectSelectOption(options, value) {
    var key = String(value)
    if (Object.prototype.hasOwnProperty.call(options, key)) {
      return options[key]
    }
    if (Object.prototype.hasOwnProperty.call(options, 'other')) {
      return options.other
    }
    return ''
  }

  function _formatNumber(value, lang) {
    var nf = _getNumberFormat(lang)
    if (nf) {
      try {
        return nf.format(value)
      } catch (e) {
        /* fallthrough */
      }
    }
    return String(value)
  }

  function _interpolateMustache(template, params) {
    if (!params || typeof params !== 'object') return template
    return template.replace(/\{\{(\w+)\}\}/g, function (match, name) {
      return params[name] !== undefined ? String(params[name]) : match
    })
  }

  function _renderIcu(template, params, lang) {
    if (!params || typeof params !== 'object') return template
    var result = ''
    var cursor = 0
    while (true) {
      var block = _findIcuBlock(template, cursor)
      if (!block) {
        result += template.substring(cursor)
        break
      }
      result += template.substring(cursor, block.start)
      var argValue = params[block.argName]
      var chosen
      if (block.kind === 'plural') {
        var n = Number(argValue)
        if (!isFinite(n)) n = 0
        chosen = _selectPluralOption(block.options, n, lang)
        chosen = chosen.replace(/#/g, _formatNumber(n, lang))
      } else {
        chosen = _selectSelectOption(block.options, argValue)
      }
      chosen = _renderIcu(chosen, params, lang)
      chosen = _interpolateMustache(chosen, params)
      result += chosen
      cursor = block.end
    }
    return result
  }

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

  // P9·L5·G1: ``pseudo`` is a first-class tag (mirrors
  // static/js/i18n.js::normalizeLang); see that file for rationale.
  function normalizeLang(raw) {
    var s = String(raw || '')
      .trim()
      .toLowerCase()
    if (s === 'pseudo' || s === 'xx-ac' || s === 'xx') return 'pseudo'
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

  // P9·L5·G2: mirrors static/js/i18n.js — see that file's banner for
  // the missing-key observability contract. Kept deliberately simple
  // in the VSCode copy because extension-host locale injection means
  // there's no ``ensureDefaultLocale`` race path to worry about.
  var _missingKeyHandler = null
  var _strictMissing = false
  var _missingKeyStats = Object.create(null)

  function _reportMissing(key, lang) {
    try {
      _missingKeyStats[key] = (_missingKeyStats[key] || 0) + 1
    } catch (e) {
      /* noop */
    }
    if (typeof _missingKeyHandler === 'function') {
      try {
        _missingKeyHandler(key, lang)
      } catch (e) {
        if (_strictMissing) throw e
      }
    } else if (_strictMissing) {
      throw new Error('[i18n] missing key: ' + key + ' (lang=' + lang + ')')
    }
  }

  function setMissingKeyHandler(fn) {
    _missingKeyHandler = typeof fn === 'function' ? fn : null
  }

  function setStrict(on) {
    _strictMissing = !!on
  }

  function getMissingKeyStats() {
    var out = {}
    var keys = Object.keys(_missingKeyStats)
    for (var i = 0; i < keys.length; i++) out[keys[i]] = _missingKeyStats[keys[i]]
    return out
  }

  function resetMissingKeyStats() {
    _missingKeyStats = Object.create(null)
  }

  function t(key, params) {
    var val = resolve(key, currentLang)
    if (val === undefined && currentLang !== DEFAULT_LANG) {
      val = resolve(key, DEFAULT_LANG)
    }
    if (val === undefined) {
      _reportMissing(key, currentLang)
      return key
    }
    // Pipeline: ICU (plural/select) → {{mustache}}. 两步不可交换：ICU
    // option body 内部的 {{…}} 需要先等 ICU 挑出正确分支再插值，避免
    // 错误分支里的 {{…}} 被提前替换然后被丢弃。
    val = _renderIcu(val, params, currentLang)
    val = _interpolateMustache(val, params)
    return val
  }

  /* Intl 公共包装（P9·L3·G2）
   *
   * 目标：把散落在各模块里的 `toLocaleString / toFixed / new Date().toString`
   * 收敛到同一个 locale-aware 管道，避免出现中英文字符串混合硬编码数字/
   * 日期的展示 bug；同时给未来 RTL / 阿拉伯数字本地化留出口。
   *
   * 所有 formatter 都走 _getIntl 按 (locale, options) 缓存。
   * - 降级：Intl 全族 API 在现代浏览器已 baseline，但保守起见失败时退到
   *   `String(value)` / `value.toISOString()` / 朴素分隔符拼接，保证页面
   *   不白屏、不抛 uncaught。
   */

  function formatNumber(value, options) {
    var f = _getIntl('NumberFormat', currentLang, options)
    if (f) {
      try {
        return f.format(value)
      } catch (e) {
        /* fallthrough */
      }
    }
    return String(value)
  }

  function _toDate(value) {
    if (value instanceof Date) return value
    if (typeof value === 'number' || typeof value === 'string') return new Date(value)
    return new Date(NaN)
  }

  function formatDate(value, options) {
    var d = _toDate(value)
    var f = _getIntl('DateTimeFormat', currentLang, options)
    if (f) {
      try {
        return f.format(d)
      } catch (e) {
        /* fallthrough */
      }
    }
    try {
      return d.toISOString()
    } catch (e) {
      return String(value)
    }
  }

  function formatRelativeTime(value, unit, options) {
    var n = Number(value)
    if (!isFinite(n)) n = 0
    var f = _getIntl('RelativeTimeFormat', currentLang, options)
    if (f) {
      try {
        return f.format(n, unit)
      } catch (e) {
        /* fallthrough */
      }
    }
    return n + ' ' + unit + (Math.abs(n) === 1 ? '' : 's')
  }

  function formatRelativeFromNow(date, options) {
    var target = _toDate(date)
    var diffMs = target.getTime() - Date.now()
    if (!isFinite(diffMs)) return formatRelativeTime(0, 'second', options)
    var absSec = Math.abs(diffMs) / 1000
    var sign = diffMs < 0 ? -1 : 1
    var value, unit
    if (absSec < 60) {
      value = sign * Math.round(absSec)
      unit = 'second'
    } else if (absSec < 3600) {
      value = sign * Math.round(absSec / 60)
      unit = 'minute'
    } else if (absSec < 86400) {
      value = sign * Math.round(absSec / 3600)
      unit = 'hour'
    } else if (absSec < 86400 * 30) {
      value = sign * Math.round(absSec / 86400)
      unit = 'day'
    } else if (absSec < 86400 * 365) {
      value = sign * Math.round(absSec / (86400 * 30))
      unit = 'month'
    } else {
      value = sign * Math.round(absSec / (86400 * 365))
      unit = 'year'
    }
    return formatRelativeTime(value, unit, options)
  }

  function formatList(values, options) {
    if (!values) return ''
    var arr = []
    for (var i = 0; i < values.length; i++) arr.push(String(values[i]))
    var f = _getIntl('ListFormat', currentLang, options)
    if (f) {
      try {
        return f.format(arr)
      } catch (e) {
        /* fallthrough */
      }
    }
    if (arr.length === 0) return ''
    if (arr.length === 1) return arr[0]
    // Fallback：只在 Intl.ListFormat 缺席时触发，仅区分 zh-* 与其它 locale。
    // 分隔符/连词硬编码是降级路径的必要妥协（再套 t() 会死循环）。
    var zh = /^zh/i.test(currentLang)
    var sep = zh ? '、' : ', ' // aiia:i18n-allow-cjk
    var conj = zh ? '和' : ' and ' // aiia:i18n-allow-cjk
    return arr.slice(0, -1).join(sep) + conj + arr[arr.length - 1]
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

  // ensureDefaultLocale 在 VSCode webview 里是 no-op：locale 由 extension
  // 通过 globalThis.__AIIA_I18N_ALL_LOCALES 注入，没有 fetch 路径。保留
  // 同名方法保证 webview-ui.js 的共享调用点不会在某一端炸 TypeError。
  function ensureDefaultLocale() {
    return Promise.resolve(Boolean(locales[DEFAULT_LANG]))
  }

  var api = {
    t: t,
    init: init,
    setLang: setLang,
    getLang: getLang,
    getAvailableLangs: getAvailableLangs,
    registerLocale: registerLocale,
    ensureDefaultLocale: ensureDefaultLocale,
    detectLang: detectLang,
    normalizeLang: normalizeLang,
    translateDOM: translateDOM,
    formatNumber: formatNumber,
    formatDate: formatDate,
    formatRelativeTime: formatRelativeTime,
    formatRelativeFromNow: formatRelativeFromNow,
    formatList: formatList,
    setMissingKeyHandler: setMissingKeyHandler,
    setStrict: setStrict,
    getMissingKeyStats: getMissingKeyStats,
    resetMissingKeyStats: resetMissingKeyStats,
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
