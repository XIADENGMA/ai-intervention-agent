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

  // Intl 实例缓存（L3·G2）——按 (ctor, locale, JSON(options)) 三元组缓存
  // ``new Intl.NumberFormat / DateTimeFormat / …`` 实例。Intl 构造器在
  // 低端移动设备和扩展宿主上单次开销可达毫秒级（见 Node.js
  // performance 追踪），长列表滚动场景反复构造会明显掉帧；缓存把同一
  // 屏多次调用摊到 1 次构造。
  //
  // LRU 有界：一个长会话若反复变换 NumberFormat options（每个条目各
  // 自不同的 ``maximumFractionDigits``、ad-hoc style 对象）没有上界会
  // 持续增长，Node 侧 extension host 没有 GC 压力时尤其危险。我们按
  // ``Map`` 插入顺序做 LRU，命中时 delete→set 把 key 挪到 tail，满时
  // drop head。
  //
  // 上限值 ``_INTL_LRU_MAX = 50`` / ``_PLURAL_LRU_MAX = 16`` 与
  // ``tests/test_i18n_intl_cache_lru.py`` 锁定的常量一致；若要调高/
  // 降低，必须同步更新该测试，避免契约悄悄漂移。
  var _INTL_LRU_MAX = 50
  var _PLURAL_LRU_MAX = 16
  var _pluralRulesCache = new Map()
  // ICU ``selectordinal`` resolves against a separate CLDR rule set
  // (``Intl.PluralRules(lang, { type: 'ordinal' })``) — in English
  // ``plural(3)`` is ``other`` but ``selectordinal(3)`` is ``few``
  // (3rd). Keeping ordinal rules in their own bucket means hot-path
  // cardinal callers (e.g. "N items") never evict their ordinal
  // counterparts and vice-versa, and dashboards can show the two
  // caches side-by-side.
  var _pluralRulesOrdinalCache = new Map()
  var _intlCache = {
    NumberFormat: new Map(),
    DateTimeFormat: new Map(),
    RelativeTimeFormat: new Map(),
    ListFormat: new Map()
  }

  // Bidirectional text isolation controls (Unicode UAX #9 §3.1).
  //
  // ``_FSI`` / ``_PDI`` bracket an embedded inline segment so the
  // Unicode Bidirectional Algorithm treats it as an isolate instead
  // of letting its strong characters bleed into the surrounding
  // paragraph's directional run. Mozilla's Project Fluent,
  // ICU4J 74's ``MessageFormatter.formatWithBidiIsolate`` and the
  // W3C i18n WG's ``qa-bidi-unicode-controls`` all recommend this
  // wrapping as the default for non-HTML sinks — which is exactly
  // what the VSCode webview's Output Channel and our HTML ``title``
  // attributes happen to be. The public ``wrapBidi`` helper
  // (declared next to the API surface below) applies the pair.
  var _FSI = '\u2068'
  var _PDI = '\u2069'

  // ICU AST compile cache (Batch-3 H12).
  //
  // ``_findIcuBlock`` + ``_parseIcuOptions`` are pure functions of
  // the (already apostrophe-escaped) template string. FormatJS's
  // ``intl-messageformat`` separates parse from format for exactly
  // the same reason: hot re-renders should not re-walk the string
  // character-by-character. We cache a descriptor of **all
  // top-level ICU blocks** for a template once, then ``_renderIcu``
  // iterates the cached array instead of calling ``_findIcuBlock``
  // on every call.
  //
  // The cache is LRU-bounded to keep long-running webview hosts
  // (extension host can live for hours) from retaining every
  // template they ever saw; 256 entries matches FormatJS's default
  // ``maxCacheSize`` for their parser LRU. Hits refresh insertion
  // order (delete → set) so MRU templates survive eviction.
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
      // Promote to MRU on every hit so the classic LRU guarantee holds.
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

  // Canonicalise ``opts`` so ``{a:1,b:2}`` and ``{b:2,a:1}`` share a
  // cache entry. FormatJS's ``intl-format-cache`` uses the same
  // sort-then-stringify idiom for the exact same reason: without it,
  // callers that build options via ``Object.assign`` or spread produce
  // order-sensitive keys and silently double the LRU footprint.
  //
  // Semantics intentionally match ``JSON.stringify`` except for key
  // order:
  //   - ``undefined`` at the top level round-trips to ``undefined``
  //     (caller decides the fallback).
  //   - ``undefined`` inside an object drops the key (same as JSON).
  //   - ``undefined`` inside an array becomes ``null`` (same as JSON).
  //   - Arrays preserve their positional order (arrays have positional
  //     semantics in every ``Intl.*`` options shape we ship).
  //   - ``Object.keys`` skips prototype-chain pollution, so a mutated
  //     ``Object.prototype`` cannot leak extra keys into the cache key.
  //   - ``toJSON`` on objects (Date, Temporal, user-defined) is honoured
  //     before the key walk — the same "if toJSON exists, call it and
  //     recurse" contract JSON.stringify applies — so two distinct Date
  //     fields don't collapse to the same ``{}`` cache bucket.
  //   - Cycles throw a tagged error (``err.__aiiaCircular = true``)
  //     which ``_intlKey`` catches and degrades to a shape-sensitive
  //     fallback key. Without the guard the recursion overflows the
  //     stack and lands every cyclic caller on ``lang|?``, silently
  //     sharing a single Intl instance across unrelated options.
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

  // Degraded fallback signature for opts we couldn't canonicalise
  // (cycles / BigInt in unusual shapes / ToJSON that throws). Takes
  // only the own top-level key names, alphabetised, so distinct shapes
  // still collide on distinct fallback keys — never on a single
  // ``lang|?`` bucket.
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

  // ICU MessagePattern ApostropheMode.DOUBLE_OPTIONAL 实现（L3·G1 续）。
  // 对齐 ICU4J 默认模式 + FormatJS/messageformat.js 默认行为，**不是**
  // JDK 兼容的 DOUBLE_REQUIRED：孤立的 `'` 保留字面（例如 ``I don't
  // know`` 不需要写成 ``I don''t know``），只有 `'{/}/|/#` 才触发 quote
  // span。
  //
  // 规则（来自 ICU4J MessagePattern.ApostropheMode 文档 + messageformat/
  // messageformat issue tracker）：
  //   1. ``''`` —— 任意位置都表示字面 ``'``。
  //   2. ``'`` + 紧跟 {``{``, ``}``, ``|``, ``#``} —— 开启 quote span，
  //      直到下一个**非成对**的 ``'``。span 内特殊字符全部按字面处理，
  //      ``''`` 在 span 内依然表示字面 ``'``。span 的开闭 ``'`` 本身被
  //      吃掉不输出。
  //   3. 其他孤立的 ``'`` —— 保留字面 ``'``（DOUBLE_OPTIONAL 的关键
  //      特征；DOUBLE_REQUIRED 会把它当作语法错误并吃掉）。
  //
  // 实现策略：tokenize-first。一次线性扫描把「受转义保护」的 ``{}|#'``
  // 替换成 Private Use Area 标记（``\uE001..\uE005``），让下游的 ICU /
  // mustache 解析把它们当作普通字符，最后在 ``t()`` 出口一次性还原。
  // 好处：下游 parser 代码零侵入，也天然支持任意深度嵌套 ICU 块——因为
  // PUA 字符不是 ICU 语法字符。
  //
  // PUA 的选择：``\uE001..\uE005`` 位于 BMP Private Use Area 起始段，
  // 和任何真实用户文本冲突的概率可以忽略。
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
        // 扫描 quote span 到下一个未成对 ``'``。``''`` 在 span 内是字面
        // ``'``，不关闭 span（ICU DOUBLE_OPTIONAL 在 span 内部的行为和
        // DOUBLE_REQUIRED 一致）。
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
        // 消费闭合 ``'`` 本身；若 span 未闭合到 EOS，ICU spec 允许让它
        // 延伸到字符串末尾（已经在上面 for 循环里吃完了）。
        i = endIdx + (j < n ? 1 : 0)
        continue
      }
      // 孤立 ``'`` 后面不跟特殊字符 → 字面。
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

  // ICU subset 解析：找到顶层 {arg, plural|selectordinal|select, …} 块。
  // 支持块内嵌套 { } 对（用于 ICU 的 option body），忽略单花括号 {{param}}
  // 占位——那是本模块自己的 mustache 语法、由 _interpolateMustache 单独处理。
  //
  // ``selectordinal`` 与 ``plural`` 的唯一差别是 CLDR 类别（``Intl.PluralRules``
  // 的 ``{ type: 'ordinal' }`` 模式）；语法、``=N`` exact match、``#``
  // 占位的作用域规则全部一致。保留在同一个 ``kind`` 字段里，由
  // ``_selectPluralOption`` 根据 kind 分派给不同的 rule set。
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

  function _selectPluralOption(options, count, lang, ordinal) {
    // ICU 规范：=N exact match 优先于 CLDR 类别。
    var exactKey = '=' + String(count)
    if (Object.prototype.hasOwnProperty.call(options, exactKey)) {
      return options[exactKey]
    }
    var rules = ordinal ? _getPluralRulesOrdinal(lang) : _getPluralRules(lang)
    // Fallback for environments without Intl.PluralRules: cardinal keeps
    // the classic English one/other split; ordinal degrades straight to
    // ``other`` (since no two CLDR languages share ordinal categories,
    // picking anything else would produce actively wrong output).
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

  // Mustache `{{name}}` interpolation with prototype-pollution hardening.
  //
  // Two defensive layers (the same combo Snyk SNYK-JS-I18NEXT-1065979
  // recommends for i18n pipelines):
  //   1. Hard-reject the three canonical prototype-pollution keywords
  //      (`__proto__`, `constructor`, `prototype`) **before** any
  //      property lookup — even if a caller mistakenly sets them as
  //      genuine own properties on `params`, we never render them.
  //   2. Require the remaining names to be **own** properties of
  //      `params` via `Object.prototype.hasOwnProperty.call`, so
  //      prototype-inherited methods like `toString` / `hasOwnProperty`
  //      can never leak `function … { [native code] }` strings into
  //      user-visible text.
  //
  // Unknown names fall through to the literal `{{name}}` so the existing
  // "undefined param keeps placeholder" contract is preserved.
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

  // Pre-compute the top-level ICU block layout for a template. See the
  // ``_icuCompileCache`` comment above for the full rationale. The
  // returned descriptor is shared across all ``_renderIcu`` calls for
  // the same template string until it gets LRU-evicted.
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
    // Fast path: a template without any ``{`` character cannot host an
    // ICU block and cannot host a ``{{mustache}}`` placeholder either,
    // so both the compile-cache lookup and ``_findIcuBlock``'s scan
    // are pure overhead. Skipping the cache here also prevents post-
    // hash-replacement literals like ``"3 items"`` — which recurse
    // through ``_renderIcu`` once per plural branch — from polluting
    // the LRU with thousands of never-revisited entries.
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
        // `#` → 本地化数字。ICU 规定 `#` 的作用域仅限**当前** plural /
        // selectordinal 分支 body 的顶层文本——任何嵌套 `{…}` 块
        // （inner plural / inner select / mustache `{{…}}`）内部的 `#`
        // 属于各自的上下文，绝不能被外层 plural 替换。这里只替换 depth=0
        // 的 `#`，避免出现 "items=1 + count=3 → 1 steps" 这种作用域串位
        // 的 bug。
        chosen = _replaceHashAtDepth0(chosen, _formatNumber(n, lang))
      } else {
        chosen = _selectSelectOption(block.options, argValue)
      }
      // 递归渲染——option body 内部可能还有任意层数的嵌套 ICU 块或
      // mustache 占位符。递归时每一层 plural 各自处理自己的 depth-0 `#`，
      // 语义等价于 ICU4J MessageFormat 的嵌套行为。每一层递归都会穿过
      // ``_compileIcuTemplate``，所以 branch body 的解析结果也被复用。
      chosen = _renderIcu(chosen, params, lang)
      chosen = _interpolateMustache(chosen, params)
      result += chosen
      cursor = block.end
    }
    result += template.substring(cursor)
    return result
  }

  // 只替换 plural 分支 body 在 depth=0 文本层的 `#`。``{`` / ``}`` 用作
  // depth 计数器：mustache ``{{name}}`` 的 ``{{…}}`` 在本扫描里算作
  // depth 0→2→0 的瞬时变化，内容字符处于 depth≥1 不会被误替换；内层
  // ICU 块 ``{arg, plural, …}`` 同样让 depth>0 保护块内 `#`。apostrophe-
  // escape 已经把「quote 内字面 ``{``/``}``」替换为 PUA 字符，不再参与
  // depth 计数，所以 ``'{'`` 这类字面大括号不会破坏扫描。
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

  // Key resolution with prototype-pollution hardening.
  //
  // The dotted-key descent `node = node[part]` used to rely on the
  // `typeof === 'string'` fallback to stop values like
  // `Object.prototype.toString` from ever reaching callers. That's a
  // fragile fuse (a later refactor that relaxes the type guard would
  // reopen the hole), so we additionally:
  //   1. Refuse the three canonical pollution names
  //      (`__proto__`, `constructor`, `prototype`) at every segment.
  //   2. Require each segment to be an **own** property of the current
  //      node via `Object.prototype.hasOwnProperty.call`. An attacker-
  //      controlled locale bundle that puts a literal `"__proto__"`
  //      key into the JSON *would* satisfy ownership at that segment,
  //      but step (1) still blocks it first; a deeply nested
  //      `ui.toString.foo` lookup falls through here because
  //      `toString` is prototype-inherited, not own.
  // Batch-2 H11: ``_resolvePath`` is the walk-and-report helper under
  // both ``resolve`` (legacy signature, value-or-undefined) and
  // ``t()``. We return a small tuple so ``t()`` can distinguish three
  // genuinely different developer mistakes without doubling the
  // traversal cost:
  //
  //   * ``shape: 'ok'``         — leaf string resolved; caller gets it.
  //   * ``shape: 'missing'``    — a segment was absent, blocked by the
  //                                prototype-pollution guard, or the
  //                                locale bundle itself was not loaded.
  //                                Caller falls through to the default
  //                                locale and then to ``_reportMissing``.
  //   * ``shape: 'non-string'`` — traversal reached the last segment
  //                                but landed on an object / number /
  //                                null, meaning the caller aimed at
  //                                a namespace instead of a leaf.
  //                                Caller should nudge the developer
  //                                with a *different* warning
  //                                (``_reportNonString``) whose
  //                                remedy is to use a deeper key,
  //                                **not** to add a duplicate leaf.
  //
  // The legacy ``resolve`` stays value-or-undefined so the
  // ``translateDOM`` hot path, ``_renderIcu``, and the existing
  // missing-key tests never see the new shape.
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
  // Batch-2 H11: once-set for non-string resolves. Keyed by
  // ``lang + '\u0001' + key`` so a single ``(lang, key)`` pair can
  // only ever warn once per process — matching how React DevTools,
  // Vue's ``warn``, and i18next's ``missingKeyHandler`` dedupe
  // developer-facing noise. ``AIIA_I18N__test.resetNonStringHits``
  // clears it so tests can assert the first-hit-only contract
  // without process isolation.
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

  // Batch-2 H11: warn-once (per locale+key) diagnostic for the
  // "namespace instead of leaf" mistake. Kept strictly parallel with
  // ``_reportMissing``:
  //   * no handler, strict off → ``console.warn`` once then silent.
  //   * strict on              → throw so tests / dev builds catch it.
  //   * always records into ``_nonStringHits`` so ``getNonStringHits``
  //     can show tests exactly what triggered.
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
      // Prefer the stronger diagnostic: if the current locale was
      // plain-missing but the default locale has the key as an
      // object (namespace), we still want to warn about the
      // namespace mistake, because the author clearly intended to
      // hit that path.
      if (observed.shape === 'missing' && fallback.shape !== 'missing') {
        observed = fallback
      }
      // 首次遇到 current lang miss 且 DEFAULT_LANG 尚未加载时，后台拉取。
      // 这里 fire-and-forget：当前这次调用仍会返回 key，但下一次 t(key)
      // 将拿到英文 fallback；ensureDefaultLocale 成功回调里还会重译 DOM，
      // 所以 data-i18n 的文本也会自动更新。
      if (val === undefined && !locales[DEFAULT_LANG] && _localeBaseUrl) {
        ensureDefaultLocale()
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
    // Pipeline: ICU apostrophe tokenize → ICU (plural/select) →
    // {{mustache}} → detokenize. 顺序要点：
    //   * tokenize 必须发生在 ICU 解析之前，否则 ``'{literal}'`` 会被
    //     当成 ICU 块误解析。
    //   * mustache 在 ICU 之后：ICU option body 内部的 {{…}} 需要先等
    //     ICU 挑出正确分支再插值，否则错误分支里的 {{…}} 会被提前替换
    //     然后随分支丢弃。
    //   * detokenize 一次性还原 PUA 标记。即使 mustache value 里含 PUA
    //     字符（极端情况），也会被统一还原；这是可接受的代价。
    //   * params 为 null/undefined 时跳过整个 tokenize 流程，保留
    //     ``t(key)`` 直接返回原模板的契约，让调用方可以用它探测 key 存在。
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
    // Fallback：不尝试本地化单位，只输出数值 + 英文单位。够让调用方看到
    // "something went wrong with Intl" 的信号，而不是空字符串。
    return n + ' ' + unit + (Math.abs(n) === 1 ? '' : 's')
  }

  // 调用方通常只有两个 Date 的 delta，没有好办法选 unit；这个高阶包装
  // 按绝对 delta 自动挑 second/minute/hour/day/month/year。
  //
  // 阈值遵循 moment.js 的 relativeTimeThreshold 默认值（s=45/m=45/h=22/
  // d=26/M=11），这是 day.js/luxon/date-fns-tz 以及几乎所有 humanize
  // 风格的 UI 库沿用的行业事实标准。选择 moment 表而不是 `< 60 则秒 /
  // < 3600 则分` 的朴素切分，是因为朴素表会在边界整秒渲染出 "in 60
  // seconds" / "in 24 hours" / "in 30 days" 这种反直觉输出——从
  // Twitter/Slack/GitHub 的 UI 复现看，用户期望在 45 秒时就已经看到
  // "1 minute" 而不是继续数秒。
  //
  // 下表以 absSec（绝对秒差）为键：
  //   absSec <     45 → second
  //   absSec <  2 700 → minute   (= 45 × 60)
  //   absSec < 79 200 → hour     (= 22 × 3 600)
  //   absSec <  2 246 400 → day  (= 26 × 86 400)
  //   absSec < 28 512 000 → month (= 11 × 30 × 86 400)
  //   else               → year
  //
  // 注：month/year divisor 延续 moment 的「月 = 30 天 / 年 = 365 天」
  // 粗粒度转换；精确日历换算与 UX 目标（快速粗分类时间轴）无关，留给
  // 调用方若真需要精确日历差自行传 unit/value 给 formatRelativeTime。
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

  // Public helper: wrap a fragment in U+2068 FIRST STRONG ISOLATE
  // / U+2069 POP DIRECTIONAL ISOLATE. See the ``_FSI`` / ``_PDI``
  // comment near the top of the module for the W3C / UAX #9 §3.1
  // rationale. Idempotent: already-wrapped input passes through
  // unchanged so nested call-sites don't balloon into
  // ``FSI·FSI·FSI·…·PDI·PDI·PDI``.
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

  // Cache-introspection hooks for tests/test_i18n_intl_cache_lru.py. These
  // intentionally live on a ``__test`` object rather than the public API
  // so production code can grep ``AIIA_I18N__test`` in one sweep to catch
  // accidental dependencies.
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
    wrapBidi: wrapBidi,
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
    window.AIIA_I18N__test = {
      flushPendingLoads: _testingFlushPendingLoads,
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
  } catch (e) {
    /* noop */
  }
})()
