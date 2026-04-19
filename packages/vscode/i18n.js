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

  // Intl instance cache + LRU — byte-parallel mirror of static/js/i18n.js.
  // See that file's comment for the rationale. Hard caps:
  //   * _INTL_LRU_MAX        = 50 per-ctor bucket
  //   * _PLURAL_LRU_MAX      = 16 per-module
  // Any adjustment must be kept in lockstep with the Web UI copy and
  // with ``tests/test_i18n_intl_cache_lru.py``.
  var _INTL_LRU_MAX = 50
  var _PLURAL_LRU_MAX = 16
  var _pluralRulesCache = new Map()
  // Byte-parallel mirror of static/js/i18n.js — keep the separate
  // ordinal bucket so dashboards can compare the two caches side by
  // side and byte-parity tests stay green.
  var _pluralRulesOrdinalCache = new Map()
  var _intlCache = {
    NumberFormat: new Map(),
    DateTimeFormat: new Map(),
    RelativeTimeFormat: new Map(),
    ListFormat: new Map()
  }

  // Bidirectional text isolation controls (Unicode UAX #9 §3.1) —
  // byte-parallel mirror of static/js/i18n.js. See that file for the
  // full W3C / Project Fluent / ICU4J 74 rationale. The webview's
  // Output Channel is a plain-text sink that the Unicode
  // Bidirectional Algorithm is free to reorder in surprising ways
  // around mixed-directionality fragments, so the helper needs to
  // exist here too even though the extension host itself never sees
  // RTL output directly.
  var _FSI = '\u2068'
  var _PDI = '\u2069'

  // ICU AST compile cache (Batch-3 H12) — byte-parallel with
  // static/js/i18n.js. FormatJS's ``intl-messageformat`` splits
  // parse and format to amortise the parse cost; we do the same
  // here, caching the top-level ICU block layout for up to
  // ``_ICU_COMPILE_LRU_MAX`` templates. Hits refresh insertion
  // order so MRU entries survive eviction. Any adjustment must be
  // mirrored in ``static/js/i18n.js`` and the
  // ``tests/test_i18n_icu_compile_cache.py`` cap pin.
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

  // Byte-parallel mirror of static/js/i18n.js ``_stableStringify`` /
  // ``_intlKey``. See that file for rationale (FormatJS's
  // ``intl-format-cache`` uses the same sort-then-stringify idiom;
  // cycles / ``toJSON`` / BigInt are handled exactly the same way
  // there so the byte-parity tests stay green).
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

  // Apostrophe-escape tokenizer — byte-parallel mirror of static/js/i18n.js.
  // See that file's comment for the ICU MessagePattern
  // ApostropheMode.DOUBLE_OPTIONAL contract (ICU4J / FormatJS default,
  // lone ``'`` stays literal) and the rationale for the PUA tokenize-then-
  // detokenize strategy.
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

  // Byte-parallel mirror of static/js/i18n.js — see that file for the
  // prototype-pollution rationale (SNYK-JS-I18NEXT-1065979 class of bug).
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

  // Pre-compute the top-level ICU block layout for a template.
  // Byte-parallel mirror of ``static/js/i18n.js`` — see that file for
  // the FormatJS-style parse/format split rationale. LRU-bounded at
  // ``_ICU_COMPILE_LRU_MAX`` entries so a long-lived extension host
  // never retains unbounded state.
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
    // Fast path: a template without any ``{`` character cannot host
    // an ICU block, so skip the compile-cache lookup entirely.
    // Without this guard, post-hash-replacement literals
    // (``"1 item"`` / ``"2 items"`` / …) would each land in the LRU
    // once per distinct ``n``, evicting the actual templates that
    // matter. Byte-parallel mirror of static/js/i18n.js.
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
        // Only replace `#` at depth 0 — see static/js/i18n.js for the
        // nested-plural rationale. Byte-parallel mirror.
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

  // Byte-parallel mirror of static/js/i18n.js ``_resolvePath`` — see
  // that file for the prototype-pollution rationale and the Batch-2
  // H11 shape-aware tuple contract. Both halves must refuse the same
  // three canonical pollution names, require own-property ownership at
  // every segment, and distinguish ``missing`` from ``non-string`` so
  // the downstream warn-once diagnostic reports the right remedy.
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

  // P9·L5·G2: mirrors static/js/i18n.js — see that file's banner for
  // the missing-key observability contract. Kept deliberately simple
  // in the VSCode copy because extension-host locale injection means
  // there's no ``ensureDefaultLocale`` race path to worry about.
  var _missingKeyHandler = null
  var _strictMissing = false
  var _missingKeyStats = Object.create(null)
  // Batch-2 H11: once-set for non-string resolves. Byte-parallel with
  // static/js/i18n.js — see that file's banner for the design rationale.
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
        // Parity with static/js/i18n.js: a throwing handler in non-strict
        // mode is a telemetry bug, not a UI bug. Silently swallowing it
        // would hide the regression from the extension-host devtools /
        // Output Channel, so surface it via ``console.warn`` (node routes
        // this to stderr, which extension host also captures).
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

  // Batch-2 H11: byte-parallel mirror of static/js/i18n.js
  // ``_reportNonString`` — same once-set, same strict-mode throw,
  // same ``console.warn`` shape. Extension-host captures ``console.warn``
  // into the Output Channel / Developer Tools, so the signal lands
  // exactly where the Web UI's warning lands for a browser devtools
  // user.
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
    // Pipeline: apostrophe tokenize → ICU → mustache → detokenize.
    // See static/js/i18n.js for the full rationale; this copy is the
    // byte-parallel mirror and must render identically on the same input.
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

  // Bucket selection mirrors static/js/i18n.js — see that file's comment
  // block for the rationale behind the moment.js 45/45/22/26/11 table.
  // Keep the two copies byte-parallel: any tweak here MUST be mirrored
  // there (enforced by tests/test_i18n_relative_time_thresholds.py's
  // byte-parity case).
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
      // AIIA-XSS-SAFE: ``data-i18n-html`` is an explicit opt-in that
      // the locale value is authored markup. The value lives in
      // locales/*.json (developer-controlled) and ``t()`` does not
      // interpolate user-provided parameters at this call site. See
      // docs/i18n.md § Security for the policy contract.
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

  // Public helper: wrap a fragment in U+2068 FIRST STRONG ISOLATE /
  // U+2069 POP DIRECTIONAL ISOLATE. Byte-parallel mirror of
  // static/js/i18n.js — see that file and ``docs/i18n.md §
  // Bidirectional text isolation`` for the W3C / UAX #9 §3.1
  // rationale. Idempotent so nested call-sites never balloon.
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

  // Test-only cache inspection hook. Mirrored with static/js/i18n.js so
  // tests/test_i18n_intl_cache_lru.py can exercise the two halves through
  // the same harness. Kept on ``__test`` to signal "not public API".
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
