;(function () {
  /* 轻量国际化模块（Web UI）：
   *   - JSON 语言包 + 结构化回退链
   *   - {{param}} 简单插值
   *   - ICU MessageFormat subset：plural / select（P9·L3·G1）
   *   - DOM 自动翻译（data-i18n / data-i18n-* / data-i18n-html）
   *
   * ICU subset 语法（与 @messageformat/core / formatjs 兼容）：
   *   {argName, plural, =N {…} one {…} few {…} many {…} other {…}}
   *   {argName, select, optA {…} optB {…} other {…}}
   * 其中 plural 内的 # 会被替换为 argName 的本地化数字形态（走
   * Intl.NumberFormat）。复数类别由 Intl.PluralRules 依据当前 locale
   * 选出（英语用 one/other，俄语用 one/few/many/other，阿拉伯语全六类）。
   * 不支持嵌套子消息（Y-A-G-N-I）——需要多参数的消息请拆成多个 key。
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

  // ICU subset 解析：找到顶层 {arg, plural|select, …} 块。支持块内
  // 嵌套 { } 对（用于 ICU 的 option body），忽略单花括号 {{param}} 占位
  // —— 那是本模块自己的 mustache 语法、由 _interpolateMustache 单独处理。
  //
  // 返回 {start, end, argName, kind, options} 或 null。
  function _findIcuBlock(str, from) {
    var i = from || 0
    while (i < str.length) {
      var open = str.indexOf('{', i)
      if (open === -1) return null
      if (str.charAt(open + 1) === '{') {
        // {{mustache}}：跳过这个位置 + 关闭的 }}，交给 mustache 替换。
        var close = str.indexOf('}}', open + 2)
        if (close === -1) return null
        i = close + 2
        continue
      }
      // 扫描到匹配的 }，同时取出 arg/kind/options。
      var depth = 1
      var j = open + 1
      while (j < str.length && depth > 0) {
        var ch = str.charAt(j)
        if (ch === '{') depth++
        else if (ch === '}') depth--
        if (depth === 0) break
        j++
      }
      if (depth !== 0) return null // 语法错误：未闭合
      var body = str.substring(open + 1, j)
      // body 形如 "arg, plural, =0 {no} one {# item} other {# items}"
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
      // 跳过空白
      while (i < n && /\s/.test(src.charAt(i))) i++
      if (i >= n) break
      // 读 key（=N / 单词）
      var keyStart = i
      while (i < n && !/\s/.test(src.charAt(i)) && src.charAt(i) !== '{') i++
      var key = src.substring(keyStart, i).trim()
      if (!key) break
      // 跳过空白
      while (i < n && /\s/.test(src.charAt(i))) i++
      if (src.charAt(i) !== '{') break
      // 读 { ... } 匹配块（允许嵌套）
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
      i++ // 消费 }
    }
    return out
  }

  function _selectPluralOption(options, count, lang) {
    // ICU 规范：=N exact match 优先于 CLDR 类别。
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
        // # → 本地化数字。ICU 规定 # 仅在 plural 块里生效。
        chosen = chosen.replace(/#/g, _formatNumber(n, lang))
      } else {
        chosen = _selectSelectOption(block.options, argValue)
      }
      // 递归渲染——option body 可能再嵌套 ICU 或 mustache（YAGNI-lite：
      // 支持一层嵌套就够覆盖 "you have {n, plural, ...} in {{box}}" 这种）。
      chosen = _renderIcu(chosen, params, lang)
      chosen = _interpolateMustache(chosen, params)
      result += chosen
      cursor = block.end
    }
    return result
  }

  // Priority (highest → lowest) for detectLang():
  //   1) ?lang=… URL query (developer tooling; survives reload)
  //   2) localStorage['aiia_i18n_lang'] (sticky opt-in, set by a dev UI
  //      or devtools; survives across sessions)
  //   3) window.__AIIA_I18N_LANG (injected by the host/SSR)
  //   4) navigator.language
  //   5) DEFAULT_LANG
  // Everything maps through normalizeLang() so callers never have to
  // deal with raw BCP-47 strings.
  function detectLang() {
    try {
      if (typeof window !== 'undefined' && window.location && window.location.search) {
        var sp = new URLSearchParams(window.location.search)
        var qp = sp.get('lang')
        if (qp) return normalizeLang(qp)
      }
    } catch (e) {
      /* noop */
    }
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        var ls = window.localStorage.getItem('aiia_i18n_lang')
        if (ls) return normalizeLang(ls)
      }
    } catch (e) {
      /* noop */
    }
    try {
      if (typeof window !== 'undefined' && window.__AIIA_I18N_LANG) {
        return normalizeLang(String(window.__AIIA_I18N_LANG))
      }
    } catch (e) {
      /* noop */
    }
    try {
      if (typeof navigator !== 'undefined' && navigator.language) {
        return normalizeLang(navigator.language)
      }
    } catch (e) {
      /* noop */
    }
    return DEFAULT_LANG
  }

  // Normalize common BCP-47 inputs down to one of our supported tags.
  //
  // P9·L5·G1: ``pseudo`` is a first-class tag — the tooling-built
  // pseudo-locale (``static/locales/_pseudo/pseudo.json``) is not a
  // translation target, but it IS a valid runtime locale when the
  // developer toggles the switch. We preserve it verbatim (including
  // the alias ``xx-AC`` Chrome uses in Accessibility Devtools, which
  // we mirror to ``pseudo`` so one tag is sufficient).
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
    } catch (e) {
      /* noop */
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

  // P9·L5·G2: missing-key observability. The default behavior is
  // unchanged — ``t()`` returns the raw key so the UI never goes
  // blank. But callers can opt into:
  //   - A custom handler (`setMissingKeyHandler(fn)`) invoked with
  //     (key, lang) whenever a lookup falls through. Dev tooling can
  //     surface missing keys in the console / notification center;
  //     prod telemetry can counter them.
  //   - Strict mode (`setStrict(true)`) which makes the handler's
  //     throws bubble up instead of being swallowed — use this in
  //     unit tests and dev builds.
  // ``_missingKeyStats`` is a simple per-key counter exposed via
  // ``getMissingKeyStats()``; reset via ``resetMissingKeyStats()``.
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
        try {
          if (typeof console !== 'undefined' && console.warn) {
            console.warn('[i18n] missing-key handler threw:', e)
          }
        } catch (_) {
          /* noop */
        }
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
      // 首次遇到 current lang miss 且 DEFAULT_LANG 尚未加载时，后台拉取。
      // 这里 fire-and-forget：当前这次调用仍会返回 key，但下一次 t(key)
      // 将拿到英文 fallback；ensureDefaultLocale 成功回调里还会重译 DOM，
      // 所以 data-i18n 的文本也会自动更新。
      if (val === undefined && !locales[DEFAULT_LANG] && _localeBaseUrl) {
        ensureDefaultLocale()
      }
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
    // Fallback：不尝试本地化单位，只输出数值 + 英文单位。够让调用方看到
    // "something went wrong with Intl" 的信号，而不是空字符串。
    return n + ' ' + unit + (Math.abs(n) === 1 ? '' : 's')
  }

  // 调用方通常只有两个 Date 的 delta，没有好办法选 unit；这个高阶包装
  // 按绝对 delta 自动挑 second/minute/hour/day/month/year，阈值遵循
  // Twitter/Slack 广泛使用的惯例。
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
    // Fallback：只在 Intl.ListFormat 缺席（老 Node / 极老浏览器）时触发，
    // 仅区分 zh-* 与其它 locale。分隔符/连词在此处直接硬编码是有意的：
    // 本分支已经是降级路径，再套一层 t() 会在 init 尚未就绪时死循环。
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

  function translateDOM(root) {
    // 允许在无 DOM 环境（unit test / node harness / VSCode extension host
    // 子进程）下被调用而不炸：没有 document 就直接退出，保持 init 能跑通。
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

  // 延迟/懒加载支持（P9·L3·G3）：init 只 block 在 current lang 的首屏加载上，
  // DEFAULT_LANG（fallback）与其它语言都放到非关键路径。这样做的权衡：
  //   - 首屏 payload 从 ~2 × locale_size 降到 ~1 × locale_size
  //   - 冷启动 TTI 主要被 current lang JSON 决定，不再受 en.json 同步阻塞
  //   - fallback 触发（某 key 在 current lang 缺失）期间，t() 会短时间
  //     返回 key 本身；我们用 _defaultPromise 把第一次 miss 触发的加载
  //     缓存住，加载完成后自动 retranslateDOM 补一次，视觉上顶多闪一下。
  var _localeBaseUrl = null
  var _pendingLoads = {}
  var _defaultPromise = null

  async function loadLocale(lang, url) {
    // Pseudo locale lives under ``_pseudo/pseudo.json`` rather than
    // ``<lang>.json``. Keep the on-disk layout unchanged (generator
    // output) by routing ``pseudo`` through the special sub-path here
    // instead of littering call sites with ``_pseudo/`` knowledge.
    var target = url
    if (!target && _localeBaseUrl) {
      if (lang === 'pseudo') {
        target = _localeBaseUrl + '/_pseudo/pseudo.json'
      } else {
        target = _localeBaseUrl + '/' + lang + '.json'
      }
    }
    if (!target) return false
    // 并发去重：同一 lang 多次 loadLocale 应该只 fetch 一次。复用
    // _pendingLoads 确保后续调用都挂在同一 Promise 上。
    if (_pendingLoads[lang]) return _pendingLoads[lang]
    _pendingLoads[lang] = (async function () {
      try {
        var resp = await fetch(target, { cache: 'default' })
        if (!resp.ok) return false
        var data = await resp.json()
        registerLocale(lang, data)
        return true
      } catch (e) {
        return false
      } finally {
        delete _pendingLoads[lang]
      }
    })()
    return _pendingLoads[lang]
  }

  // 确保默认 locale 最终会被加载一次。多次调用复用同一 Promise；成功后
  // retranslateDOM 让之前 miss 的 key 现在能 fallback 到英文。
  function ensureDefaultLocale() {
    if (locales[DEFAULT_LANG]) return Promise.resolve(true)
    if (_defaultPromise) return _defaultPromise
    if (!_localeBaseUrl) return Promise.resolve(false)
    _defaultPromise = loadLocale(DEFAULT_LANG, _localeBaseUrl + '/' + DEFAULT_LANG + '.json').then(
      function (ok) {
        if (ok) {
          try {
            translateDOM()
          } catch (e) {
            /* noop */
          }
        }
        return ok
      }
    )
    return _defaultPromise
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

    if (opts.localeBaseUrl) {
      _localeBaseUrl = opts.localeBaseUrl
      if (!locales[lang]) {
        // Let loadLocale() compute the URL from lang so the
        // ``pseudo`` → ``_pseudo/pseudo.json`` special-case lives in
        // exactly one place.
        await loadLocale(lang)
      }
      // Prefetch DEFAULT_LANG 在后台完成——不 await。对于 current === DEFAULT_LANG
      // 的情形直接跳过（ensureDefaultLocale 自带短路）。
      if (lang !== DEFAULT_LANG) {
        ensureDefaultLocale()
      }
    }

    setLang(lang)

    if (opts.translateDOM !== false) {
      translateDOM()
    }
  }

  // Pending prefetch flush helper (tests may await this to get
  // deterministic ordering without hacking setTimeout loops). Not part
  // of the public API; exposed via AIIA_I18N__test for the pytest harness.
  function _testingFlushPendingLoads() {
    var keys = Object.keys(_pendingLoads)
    return Promise.all(
      keys.map(function (k) {
        return _pendingLoads[k]
      })
    )
  }

  var api = {
    t: t,
    init: init,
    setLang: setLang,
    getLang: getLang,
    getAvailableLangs: getAvailableLangs,
    registerLocale: registerLocale,
    loadLocale: loadLocale,
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
    window.AIIA_I18N = api
  } catch (e) {
    /* noop */
  }
  // Test-only hook (NOT part of the public contract). Kept under a
  // distinct name so downstream code never reaches for it.
  try {
    window.AIIA_I18N__test = { flushPendingLoads: _testingFlushPendingLoads }
  } catch (e) {
    /* noop */
  }
})()
