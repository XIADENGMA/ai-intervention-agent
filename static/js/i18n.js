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

  // Intl 实例缓存（L3·G2）：按 (ctor, locale, stableKey(options)) 三元组
  // 复用 ``Intl.NumberFormat / DateTimeFormat / …``，避免长列表滚动反复
  // 构造。``Map`` 插入顺序即 LRU——命中时 delete→set 挪到 tail，满则 drop
  // head。上限 50/16 由 tests/test_i18n_intl_cache_lru.py 锁定，改动需同步。
  var _INTL_LRU_MAX = 50
  var _PLURAL_LRU_MAX = 16
  var _pluralRulesCache = new Map()
  // selectordinal 走独立 CLDR rule set（``{ type: 'ordinal' }``）：英语
  // ``plural(3)=other`` 但 ``selectordinal(3)=few``。分桶避免 cardinal
  // 热路径把 ordinal 条目挤出去。
  var _pluralRulesOrdinalCache = new Map()
  var _intlCache = {
    NumberFormat: new Map(),
    DateTimeFormat: new Map(),
    RelativeTimeFormat: new Map(),
    ListFormat: new Map()
  }

  // 双向文本隔离（UAX #9 §3.1）：FSI/PDI 把内嵌片段包成独立的 isolate，
  // 避免 strong 字符溢出到外层段落方向。对 VSCode Output Channel、HTML
  // ``title`` 等非 HTML sink 是 W3C i18n WG 推荐的默认写法。公开 API
  // ``wrapBidi`` 在下方。
  var _FSI = '\u2068'
  var _PDI = '\u2069'

  // ICU AST 编译缓存（Batch-3 H12）：``_findIcuBlock`` + ``_parseIcuOptions``
  // 是模板字符串的纯函数；对同一模板的热重渲不应逐字符再扫。LRU 上限 256
  // 与 FormatJS 默认 ``maxCacheSize`` 对齐；命中走 delete→set 刷新到
  // tail，满时淘汰 head。
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

  // 规范化 ``opts``：``{a:1,b:2}`` 与 ``{b:2,a:1}`` 必须共用缓存项，否
  // 则 ``Object.assign`` / spread 构造出的 options 会让 LRU 体积悄悄翻倍
  // （FormatJS ``intl-format-cache`` 同样走 sort-then-stringify）。
  //
  // 语义刻意对齐 ``JSON.stringify``，仅保证 key 顺序无关：
  //   - 顶层 ``undefined`` 原样返回（让 caller 决定 fallback）
  //   - object 内 ``undefined`` 丢 key、array 内 ``undefined`` 变 ``null``
  //   - ``Object.keys`` 跳过原型链污染
  //   - ``toJSON`` 先于 key walk（保持 Date/Temporal 的契约）
  //   - 循环引用抛 ``err.__aiiaCircular = true``，由 ``_intlKey`` 捕获
  //     后退到 shape-signature key，避免栈溢出塌陷到 ``lang|?`` 单桶
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

  // 无法规范化时的降级签名（cycle / toJSON 抛异常等）：只取顶层 own keys
  // 的字典序拼接，让不同 shape 仍落到不同 fallback key，而不是全部塌陷
  // 成一个 ``lang|?`` 桶。
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
    // 无 Intl.PluralRules 环境下的降级：cardinal 走英语 one/other；
    // ordinal 直接退到 ``other``（CLDR ordinal 类别无跨语言通用项，
    // 猜测反而会给出明显错误的输出）。
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

  // Mustache ``{{name}}`` 插值，带原型污染加固（对齐 Snyk
  // SNYK-JS-I18NEXT-1065979 的建议）：
  //   1. 直接拒绝 ``__proto__`` / ``constructor`` / ``prototype`` 三个
  //      关键字，即使 caller 把它们显式挂到 params 上也不渲染；
  //   2. 其余 name 必须是 ``params`` 自有属性（``hasOwnProperty.call``），
  //      避免原型链方法（``toString`` 等）泄漏出 ``function … [native]`` 文本。
  // 命中不到的 name 保留字面 ``{{name}}``，维持「缺参保留占位」契约。
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

  // 预解析模板顶层 ICU 块并缓存到 ``_icuCompileCache``；同一模板的
  // 多次 ``_renderIcu`` 调用共享这份描述，直到 LRU 淘汰。
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
    // 快路径：模板无任何 ``{`` 时既无 ICU 块也无 mustache 占位，缓存
    // 查询是纯开销；更关键的是 ``#`` 替换后的 "3 items" 等字面串会递
    // 归走回 ``_renderIcu``，这里不短路会让 LRU 被一次性塞满、永不命中。
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

  // detectLang 优先级（高→低）：
  //   1) ``?lang=…`` URL query（开发工具；刷新后保留）
  //   2) ``localStorage['aiia_i18n_lang']``（跨会话 sticky）
  //   3) ``window.__AIIA_I18N_LANG``（host/SSR 注入）
  //   4) ``navigator.language``
  //   5) DEFAULT_LANG
  // 所有结果都过 normalizeLang，调用方不必处理原始 BCP-47 字符串。
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

  // 把常见 BCP-47 输入归一化到本仓库支持的语言 tag。
  // P9·L5·G1：``pseudo`` 是一等 tag（工具生成的 pseudo-locale），
  // 同时把 Chrome a11y devtools 使用的别名 ``xx-AC`` 也折叠到 ``pseudo``。
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

  // key 解析 + 原型污染加固：
  //   1. 每段拒绝 ``__proto__`` / ``constructor`` / ``prototype``；
  //   2. 每段必须是当前节点自有属性（``hasOwnProperty.call``），避免
  //      ``toString`` 之类原型链方法被当作叶子返回。
  // Batch-2 H11：``_resolvePath`` 统一服务 ``resolve``（legacy，返回
  // value-or-undefined）和 ``t()``；返回 {value, shape, nodeType}：
  //   * shape=ok         — 叶子字符串，直接返回
  //   * shape=missing    — 段缺失或被加固规则拦掉，走 fallback 语言 + _reportMissing
  //   * shape=non-string — 末段落在 object/number/null 等非字符串上，
  //                        提醒调用方把 key 改深（_reportNonString）
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

  // P9·L5·G2：missing-key 观测性。默认依旧返回 raw key（UI 不空白）。
  // 调用方可以额外选择：
  //   - ``setMissingKeyHandler(fn)``：每次 miss 回调 (key, lang)，
  //     用于控制台/通知中心或埋点。
  //   - ``setStrict(true)``：handler 抛出不再吞，直接冒泡 —— 单测/dev
  //     构建建议开启。
  // ``_missingKeyStats`` 记录 per-key 次数，经 ``getMissingKeyStats()``
  // 暴露；``resetMissingKeyStats()`` 清零。
  var _missingKeyHandler = null
  var _strictMissing = false
  var _missingKeyStats = Object.create(null)
  // Batch-2 H11：非字符串命中的 warn-once 桶。key 形如
  // ``lang + '\u0001' + key``，每个 (lang, key) 进程内只警告一次 ——
  // 对齐 React DevTools / Vue warn / i18next missingKeyHandler 的去噪策略。
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

  // Batch-2 H11：「key 指向 namespace 而非叶子」的 warn-once。结构与
  // ``_reportMissing`` 并行：
  //   * 非 strict → 首次 ``console.warn``，之后静默；
  //   * strict   → 直接抛，方便单测 / dev 构建捕获；
  //   * 无论哪种都写入 ``_nonStringHits``，让测试断言触发源头。
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
      // 诊断升级：当前 locale 是 plain-missing 但 DEFAULT_LANG 上把
      // 同 key 命中成 namespace 时，仍按「namespace 误用」警告——作者
      // 显然期望走这条路径。
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
      // AIIA-XSS-SAFE: ``data-i18n-html`` 是 opt-in 的 authored-markup
      // 通道，值来自 locales/*.json（开发者受控），此处 ``t()`` 不拼用户
      // 参数。契约详见 docs/i18n.md § Security。
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
    // pseudo locale 的磁盘布局是 ``_pseudo/pseudo.json``，保留在此处
    // 分派，其它调用方无需关心子路径。
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
        // 让 loadLocale 自己按 lang 派发 URL，把 pseudo →
        // ``_pseudo/pseudo.json`` 的特判收拢到一处。
        await loadLocale(lang)
      }
      // DEFAULT_LANG 后台 prefetch，不 await；current===DEFAULT_LANG 时
      // ``ensureDefaultLocale`` 自带短路。
      if (lang !== DEFAULT_LANG) {
        ensureDefaultLocale()
      }
    }

    setLang(lang)

    if (opts.translateDOM !== false) {
      translateDOM()
    }
  }

  // 对外 helper：用 U+2068 FSI / U+2069 PDI 包裹片段。幂等——已包裹的
  // 输入原样返回，避免嵌套调用把文本撑成 ``FSI·FSI·…·PDI·PDI``。
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

  // 测试辅助：等待所有 pending prefetch 完成，避免 setTimeout hack。
  // 不是公共 API，经 AIIA_I18N__test 暴露给 pytest harness。
  function _testingFlushPendingLoads() {
    var keys = Object.keys(_pendingLoads)
    return Promise.all(
      keys.map(function (k) {
        return _pendingLoads[k]
      })
    )
  }

  // 缓存内省钩子（仅测试用）。故意挂在 ``__test`` 对象上而非公共 API，
  // 这样生产代码 grep 一次 ``AIIA_I18N__test`` 就能定位误引用。
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
  // 仅供测试，非公共契约；故意与 AIIA_I18N 区分命名，避免下游误用。
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
