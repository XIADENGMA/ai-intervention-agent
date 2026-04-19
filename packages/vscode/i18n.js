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

  // Intl 实例缓存 + LRU，与 static/js/i18n.js 行为对齐。上限 50/16 由
  // tests/test_i18n_intl_cache_lru.py 锁定，改动需两份一起改。
  var _INTL_LRU_MAX = 50
  var _PLURAL_LRU_MAX = 16
  var _pluralRulesCache = new Map()
  // selectordinal 专用桶，保证 cardinal 热路径不会挤掉 ordinal 条目。
  var _pluralRulesOrdinalCache = new Map()
  var _intlCache = {
    NumberFormat: new Map(),
    DateTimeFormat: new Map(),
    RelativeTimeFormat: new Map(),
    ListFormat: new Map()
  }

  // 双向文本隔离（UAX #9 §3.1），与 Web 版逐字节并行：webview Output
  // Channel 是 plain-text sink，UBA 会对混合方向片段做出奇的重排，因此
  // 扩展侧也需要 wrapBidi。
  var _FSI = '\u2068'
  var _PDI = '\u2069'

  // ICU AST 编译缓存（Batch-3 H12），对齐 Web 版。FormatJS 同样把 parse
  // 与 format 拆开摊销；LRU 上限 256 由 tests/test_i18n_icu_compile_cache.py
  // 锁定，改动需两份同步。
  var _ICU_COMPILE_LRU_MAX = 256
  var _icuCompileCache = new Map()

  function _touchLru(map, key, value, max) {
    if (map.has(key)) map.delete(key)
    map.set(key, value)
    while (map.size > max) {
      var firstKey = map.keys().next().value
      if (firstKey === undefined) break
      map.delete(firstKey)
    }
  }

  function _getPluralRules(lang) {
    if (typeof Intl === 'undefined' || typeof Intl.PluralRules !== 'function') {
      return null
    }
    if (_pluralRulesCache.has(lang)) {
      var hit = _pluralRulesCache.get(lang)
      _pluralRulesCache.delete(lang)
      _pluralRulesCache.set(lang, hit)
      return hit
    }
    var instance
    try {
      instance = new Intl.PluralRules(lang)
    } catch (e) {
      instance = null
    }
    _touchLru(_pluralRulesCache, lang, instance, _PLURAL_LRU_MAX)
    return instance
  }

  function _getPluralRulesOrdinal(lang) {
    if (typeof Intl === 'undefined' || typeof Intl.PluralRules !== 'function') {
      return null
    }
    if (_pluralRulesOrdinalCache.has(lang)) {
      var hit = _pluralRulesOrdinalCache.get(lang)
      _pluralRulesOrdinalCache.delete(lang)
      _pluralRulesOrdinalCache.set(lang, hit)
      return hit
    }
    var instance
    try {
      instance = new Intl.PluralRules(lang, { type: 'ordinal' })
    } catch (e) {
      instance = null
    }
    _touchLru(_pluralRulesOrdinalCache, lang, instance, _PLURAL_LRU_MAX)
    return instance
  }

  // 稳定序列化：{a:1,b:2} 与 {b:2,a:1} 需共享缓存项。语义对齐 Web 版
  // ``_stableStringify`` / ``_intlKey``——JSON-ish，额外处理 BigInt /
  // toJSON，并对循环引用抛 ``err.__aiiaCircular`` 让 ``_intlKey`` 落到
  // shape-signature 降级桶。
  function _stableStringify(value) {
    return _stableStringifyInner(value, new WeakSet())
  }

  function _stableStringifyInner(value, seen) {
    if (value === undefined) return undefined
    if (value === null) return 'null'
    var t = typeof value
    if (t === 'bigint') {
      return JSON.stringify(value.toString() + 'n')
    }
    if (t !== 'object') return JSON.stringify(value)
    if (typeof value.toJSON === 'function') {
      var viaToJson
      try {
        viaToJson = value.toJSON()
      } catch (e) {
        viaToJson = undefined
      }
      if (viaToJson !== value) {
        return _stableStringifyInner(viaToJson, seen)
      }
    }
    if (seen.has(value)) {
      var cycleErr = new Error('_stableStringify: circular reference')
      cycleErr.__aiiaCircular = true
      throw cycleErr
    }
    seen.add(value)
    try {
      if (Array.isArray(value)) {
        var arr = []
        for (var i = 0; i < value.length; i++) {
          var el = _stableStringifyInner(value[i], seen)
          arr.push(el === undefined ? 'null' : el)
        }
        return '[' + arr.join(',') + ']'
      }
      var keys = Object.keys(value).sort()
      var parts = []
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j]
        var v = _stableStringifyInner(value[k], seen)
        if (v === undefined) continue
        parts.push(JSON.stringify(k) + ':' + v)
      }
      return '{' + parts.join(',') + '}'
    } finally {
      seen.delete(value)
    }
  }

  function _shapeSignature(opts) {
    if (!opts || typeof opts !== 'object') return ''
    try {
      return Object.keys(opts).sort().join(',')
    } catch (e) {
      return ''
    }
  }

  function _intlKey(lang, opts) {
    try {
      var body = _stableStringify(opts || {})
      return lang + '|' + (body === undefined ? '{}' : body)
    } catch (e) {
      var marker = e && e.__aiiaCircular ? 'cycle' : 'err'
      return lang + '|?' + marker + '|' + _shapeSignature(opts)
    }
  }

  function _getIntl(ctor, lang, opts) {
    if (typeof Intl === 'undefined' || typeof Intl[ctor] !== 'function') return null
    var bucket = _intlCache[ctor]
    if (!bucket) return null
    var key = _intlKey(lang, opts)
    if (bucket.has(key)) {
      var hit = bucket.get(key)
      bucket.delete(key)
      bucket.set(key, hit)
      return hit
    }
    var instance
    try {
      instance = new Intl[ctor](lang, opts || undefined)
    } catch (e) {
      instance = null
    }
    _touchLru(bucket, key, instance, _INTL_LRU_MAX)
    return instance
  }

  function _getNumberFormat(lang) {
    return _getIntl('NumberFormat', lang, undefined)
  }

  // 撇号转义分词器：ICU MessagePattern ApostropheMode.DOUBLE_OPTIONAL
  // 语义（ICU4J / FormatJS 默认：孤立 ``'`` 按字面），通过 PUA 占位先
  // tokenize 再 detokenize，避开 ICU 子语法冲突。
  var _PUA_BRACE_OPEN = '\uE001'
  var _PUA_BRACE_CLOSE = '\uE002'
  var _PUA_PIPE = '\uE003'
  var _PUA_HASH = '\uE004'
  var _PUA_APOSTROPHE = '\uE005'
  var _PUA_CLEAN_RE = /[\uE001\uE002\uE003\uE004\uE005]/g
  function _puaFor(ch) {
    if (ch === '{') return _PUA_BRACE_OPEN
    if (ch === '}') return _PUA_BRACE_CLOSE
    if (ch === '|') return _PUA_PIPE
    if (ch === '#') return _PUA_HASH
    return ch
  }
  function _icuEscapeApostrophes(str) {
    if (str.indexOf("'") === -1) return str
    var out = ''
    var i = 0
    var n = str.length
    while (i < n) {
      var ch = str.charAt(i)
      if (ch !== "'") {
        out += ch
        i++
        continue
      }
      var next = i + 1 < n ? str.charAt(i + 1) : ''
      if (next === "'") {
        out += _PUA_APOSTROPHE
        i += 2
        continue
      }
      if (next === '{' || next === '}' || next === '|' || next === '#') {
        var j = i + 1
        while (j < n) {
          if (str.charAt(j) === "'") {
            if (j + 1 < n && str.charAt(j + 1) === "'") {
              j += 2
              continue
            }
            break
          }
          j++
        }
        var endIdx = j < n ? j : n
        for (var k = i + 1; k < endIdx; k++) {
          var cc = str.charAt(k)
          if (cc === "'" && k + 1 < endIdx && str.charAt(k + 1) === "'") {
            out += _PUA_APOSTROPHE
            k++
            continue
          }
          out += _puaFor(cc)
        }
        i = endIdx + (j < n ? 1 : 0)
        continue
      }
      out += "'"
      i++
    }
    return out
  }
  function _icuUnescapePua(str) {
    if (!str) return str
    return str.replace(_PUA_CLEAN_RE, function (ch) {
      if (ch === _PUA_BRACE_OPEN) return '{'
      if (ch === _PUA_BRACE_CLOSE) return '}'
      if (ch === _PUA_PIPE) return '|'
      if (ch === _PUA_HASH) return '#'
      return "'"
    })
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
      var kindMatch = rest.match(/^(plural|selectordinal|select)\s*,\s*/)
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

  function _selectPluralOption(options, count, lang, ordinal) {
    var exactKey = '=' + String(count)
    if (Object.prototype.hasOwnProperty.call(options, exactKey)) {
      return options[exactKey]
    }
    var rules = ordinal ? _getPluralRulesOrdinal(lang) : _getPluralRules(lang)
    var category
    if (rules) {
      category = rules.select(count)
    } else if (ordinal) {
      category = 'other'
    } else {
      category = count === 1 ? 'one' : 'other'
    }
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

  // Mustache 插值 + 原型污染加固：拒绝 ``__proto__`` / ``constructor`` /
  // ``prototype``，其余 name 必须为 params 自有属性；命中不到保留占位。
  // 对齐 SNYK-JS-I18NEXT-1065979 的加固建议。
  function _interpolateMustache(template, params) {
    if (!params || typeof params !== 'object') return template
    return template.replace(/\{\{(\w+)\}\}/g, function (match, name) {
      if (name === '__proto__' || name === 'constructor' || name === 'prototype') {
        return match
      }
      if (!Object.prototype.hasOwnProperty.call(params, name)) {
        return match
      }
      var value = params[name]
      return value !== undefined ? String(value) : match
    })
  }

  // 预编译模板的顶层 ICU 块布局。FormatJS 同款 parse/format 拆分，LRU
  // 上限 256 防止扩展宿主长期驻留无界状态。
  function _compileIcuTemplate(template) {
    if (_icuCompileCache.has(template)) {
      var hit = _icuCompileCache.get(template)
      _icuCompileCache.delete(template)
      _icuCompileCache.set(template, hit)
      return hit
    }
    var blocks = []
    var cursor = 0
    while (true) {
      var block = _findIcuBlock(template, cursor)
      if (!block) break
      blocks.push(block)
      cursor = block.end
    }
    var compiled = { blocks: blocks, trivial: blocks.length === 0 }
    _touchLru(_icuCompileCache, template, compiled, _ICU_COMPILE_LRU_MAX)
    return compiled
  }

  function _renderIcu(template, params, lang) {
    if (!params || typeof params !== 'object') return template
    // 快速路径：无 ``{`` 即不可能含 ICU 块，跳过 compile 查表。否则
    // ``"1 item"`` / ``"2 items"`` 这类 # 替换后的字面量会逐个占位 LRU，
    // 把真正的模板挤掉。
    if (template.indexOf('{') === -1) return template
    var compiled = _compileIcuTemplate(template)
    if (compiled.trivial) return template
    var result = ''
    var cursor = 0
    var blocks = compiled.blocks
    for (var bi = 0; bi < blocks.length; bi++) {
      var block = blocks[bi]
      result += template.substring(cursor, block.start)
      var argValue = params[block.argName]
      var chosen
      if (block.kind === 'plural' || block.kind === 'selectordinal') {
        var n = Number(argValue)
        if (!isFinite(n)) n = 0
        chosen = _selectPluralOption(block.options, n, lang, block.kind === 'selectordinal')
        // 仅替换 depth=0 的 ``#``，保留内层 plural/selectordinal 自己的 # 作用域。
        chosen = _replaceHashAtDepth0(chosen, _formatNumber(n, lang))
      } else {
        chosen = _selectSelectOption(block.options, argValue)
      }
      chosen = _renderIcu(chosen, params, lang)
      chosen = _interpolateMustache(chosen, params)
      result += chosen
      cursor = block.end
    }
    result += template.substring(cursor)
    return result
  }

  function _replaceHashAtDepth0(str, replacement) {
    if (!str || str.indexOf('#') === -1) return str
    var out = ''
    var depth = 0
    for (var i = 0, L = str.length; i < L; i++) {
      var ch = str.charAt(i)
      if (ch === '{') {
        depth++
        out += ch
      } else if (ch === '}') {
        if (depth > 0) depth--
        out += ch
      } else if (ch === '#' && depth === 0) {
        out += replacement
      } else {
        out += ch
      }
    }
    return out
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

  // P9·L5·G1：``pseudo`` 作为一等标签（与 static/js/i18n.js 一致）。
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

  // key 解析 + 原型污染加固：每段拒绝 ``__proto__`` / ``constructor`` /
  // ``prototype``，且必须是当前节点自有属性（``hasOwnProperty.call``）。
  // Batch-2 H11：返回 {value, shape, nodeType}，区分 ``missing`` 与
  // ``non-string`` 以触发不同的 warn-once 诊断。
  function _resolvePath(key, lang) {
    var dict = locales[lang || currentLang]
    if (!dict) dict = locales[DEFAULT_LANG]
    if (!dict) return { value: undefined, shape: 'missing', nodeType: 'undefined' }

    var parts = String(key).split('.')
    var node = dict
    for (var i = 0; i < parts.length; i++) {
      if (node === null || node === undefined || typeof node !== 'object') {
        return { value: undefined, shape: 'missing', nodeType: typeof node }
      }
      var part = parts[i]
      if (part === '__proto__' || part === 'constructor' || part === 'prototype') {
        return { value: undefined, shape: 'missing', nodeType: 'blocked' }
      }
      if (!Object.prototype.hasOwnProperty.call(node, part)) {
        return { value: undefined, shape: 'missing', nodeType: 'undefined' }
      }
      node = node[part]
    }
    if (typeof node === 'string') return { value: node, shape: 'ok', nodeType: 'string' }
    return { value: undefined, shape: 'non-string', nodeType: node === null ? 'null' : typeof node }
  }

  // P9·L5·G2：缺 key 观测三件套（handler/strict/stats）。VSCode 这份
  // 因宿主直接注入 locale，不需要 ensureDefaultLocale 竞态处理。
  var _missingKeyHandler = null
  var _strictMissing = false
  var _missingKeyStats = Object.create(null)
  // Batch-2 H11：non-string resolve 的 (lang|key) 去重集合。
  var _nonStringHits = Object.create(null)
  var _NONSTRING_SEP = '\u0001'

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
        // 非 strict 下：handler 抛异常属于遥测 bug，不要静默吞掉，
        // 经 console.warn 浮到 Output Channel / devtools。
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

  // Batch-2 H11：once-set 去重 → strict 模式抛错 / 非 strict ``console.warn``
  // 输出 deeper-key 建议，扩展宿主会把它捕获到 Output Channel。
  function _reportNonString(key, lang, nodeType) {
    var bucketKey = (lang == null ? '' : String(lang)) + _NONSTRING_SEP + String(key)
    if (Object.prototype.hasOwnProperty.call(_nonStringHits, bucketKey)) {
      return
    }
    _nonStringHits[bucketKey] = { lang: lang, key: key, type: nodeType }
    if (_strictMissing) {
      throw new Error(
        '[i18n] non-string resolve: ' + key +
        ' (lang=' + lang + ', type=' + nodeType + ')'
      )
    }
    try {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn(
          '[i18n] resolved non-string:',
          key,
          '(lang=' + lang + ', type=' + nodeType + ', hint: try a deeper key)'
        )
      }
    } catch (_) {
      /* noop */
    }
  }

  function t(key, params) {
    var detail = _resolvePath(key, currentLang)
    var val = detail.value
    var observed = detail
    if (val === undefined && currentLang !== DEFAULT_LANG) {
      var fallback = _resolvePath(key, DEFAULT_LANG)
      val = fallback.value
      if (observed.shape === 'missing' && fallback.shape !== 'missing') {
        observed = fallback
      }
    }
    if (val === undefined) {
      if (observed.shape === 'non-string') {
        _reportNonString(key, currentLang, observed.nodeType)
      } else {
        _reportMissing(key, currentLang)
      }
      return key
    }
    // 渲染管线：撇号 tokenize → ICU → mustache → detokenize。
    if (params && typeof params === 'object') {
      val = _icuEscapeApostrophes(val)
      val = _renderIcu(val, params, currentLang)
      val = _interpolateMustache(val, params)
      val = _icuUnescapePua(val)
    } else {
      val = _renderIcu(val, params, currentLang)
      val = _interpolateMustache(val, params)
    }
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

  // 相对时间桶阈值沿用 moment.js 的 45/45/22/26/11 表；两份 i18n.js 必须
  // 同步，由 tests/test_i18n_relative_time_thresholds.py 的 byte-parity 用例强约束。
  function formatRelativeFromNow(date, options) {
    var target = _toDate(date)
    var diffMs = target.getTime() - Date.now()
    if (!isFinite(diffMs)) return formatRelativeTime(0, 'second', options)
    var absSec = Math.abs(diffMs) / 1000
    var sign = diffMs < 0 ? -1 : 1
    var value, unit
    if (absSec < 45) {
      value = sign * Math.round(absSec)
      unit = 'second'
    } else if (absSec < 2700) {
      value = sign * Math.round(absSec / 60)
      unit = 'minute'
    } else if (absSec < 79200) {
      value = sign * Math.round(absSec / 3600)
      unit = 'hour'
    } else if (absSec < 2246400) {
      value = sign * Math.round(absSec / 86400)
      unit = 'day'
    } else if (absSec < 28512000) {
      value = sign * Math.round(absSec / 2592000)
      unit = 'month'
    } else {
      value = sign * Math.round(absSec / 31536000)
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
      // AIIA-XSS-SAFE: ``data-i18n-html`` 是显式 opt-in，locale 值来自
      // 开发者控制的 locales/*.json；此处 ``t()`` 无用户参数插值。
      // 合约详见 docs/i18n.md § Security。
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

  // 公共 helper：用 U+2068 FSI / U+2069 PDI 包裹片段（UAX #9 §3.1）。
  // 幂等——已包裹的字符串原样返回，避免嵌套调用膨胀。详见 docs/i18n.md。
  function wrapBidi(value) {
    if (value === undefined || value === null) return ''
    var s = typeof value === 'string' ? value : String(value)
    if (s === '') return ''
    if (
      s.length >= 2 &&
      s.charAt(0) === _FSI &&
      s.charAt(s.length - 1) === _PDI
    ) {
      return s
    }
    return _FSI + s + _PDI
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
    wrapBidi: wrapBidi,
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

  // 测试专用缓存探针；挂在 ``__test`` 上表明非公共 API。
  function _testingClearIntlCaches() {
    _pluralRulesCache.clear()
    _pluralRulesOrdinalCache.clear()
    _icuCompileCache.clear()
    var names = Object.keys(_intlCache)
    for (var i = 0; i < names.length; i++) _intlCache[names[i]].clear()
  }
  function _testingGetIcuCompileCacheSize() {
    return _icuCompileCache.size
  }
  function _testingPeekIcuCompileKeys() {
    return Array.from(_icuCompileCache.keys())
  }
  function _testingGetIntlCacheSize(ctor) {
    var bucket = _intlCache[ctor]
    return bucket ? bucket.size : 0
  }
  function _testingPeekIntlCacheKeys(ctor) {
    var bucket = _intlCache[ctor]
    return bucket ? Array.from(bucket.keys()) : []
  }
  function _testingGetPluralRulesCacheSize() {
    return _pluralRulesCache.size
  }
  function _testingPeekPluralRulesKeys() {
    return Array.from(_pluralRulesCache.keys())
  }
  function _testingGetPluralRulesOrdinalCacheSize() {
    return _pluralRulesOrdinalCache.size
  }
  function _testingPeekPluralRulesOrdinalKeys() {
    return Array.from(_pluralRulesOrdinalCache.keys())
  }
  function _testingGetNonStringHits() {
    var out = []
    var keys = Object.keys(_nonStringHits)
    for (var i = 0; i < keys.length; i++) out.push(_nonStringHits[keys[i]])
    return out
  }
  function _testingResetNonStringHits() {
    _nonStringHits = Object.create(null)
  }
  var _testHookBag = {
    clearIntlCaches: _testingClearIntlCaches,
    getIntlCacheSize: _testingGetIntlCacheSize,
    peekIntlCacheKeys: _testingPeekIntlCacheKeys,
    getPluralRulesCacheSize: _testingGetPluralRulesCacheSize,
    peekPluralRulesKeys: _testingPeekPluralRulesKeys,
    getPluralRulesOrdinalCacheSize: _testingGetPluralRulesOrdinalCacheSize,
    peekPluralRulesOrdinalKeys: _testingPeekPluralRulesOrdinalKeys,
    getIcuCompileCacheSize: _testingGetIcuCompileCacheSize,
    peekIcuCompileKeys: _testingPeekIcuCompileKeys,
    getNonStringHits: _testingGetNonStringHits,
    resetNonStringHits: _testingResetNonStringHits
  }
  try {
    globalThis.AIIA_I18N__test = _testHookBag
  } catch (e) {
    try {
      window.AIIA_I18N__test = _testHookBag
    } catch (_) {
      // 忽略
    }
  }
})()
