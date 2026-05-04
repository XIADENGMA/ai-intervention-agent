#!/usr/bin/env node
// Cross-feature red-team for the i18n runtime. Runs both ``i18n.js``
// copies (Web UI + VSCode webview) side-by-side under a pinned
// ``Date.now()`` and exercises every Batch-1 / Batch-1.5 / Batch-2 /
// Batch-3 edge case in one self-contained script.
//
// pytest 对单特性做细粒度断言；本脚本补一份人类可读的 PASS/FAIL
// 集成表，pre-commit smoke 与 CI gate 都用它 catch 两半漂移。
//
// Usage:
//   node scripts/red_team_i18n_runtime.mjs          # runs all cases
//   node scripts/red_team_i18n_runtime.mjs --quiet  # only prints FAIL
//
// Exit: 0 all-green / 1 any failure.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import vm from 'node:vm'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..')
const WEB = path.join(ROOT, 'static', 'js', 'i18n.js')
const VSC = path.join(ROOT, 'packages', 'vscode', 'i18n.js')
const FAKE_NOW = 1_704_164_645_000

const QUIET = process.argv.includes('--quiet')

function log(mark, label, detail = '') {
  if (QUIET && mark === 'PASS') return
  console.log(`[${mark}] ${label}${detail ? '  ' + detail : ''}`)
}

function loadI18n(i18nPath, lang = 'en', locale = {}, extraGlobals = {}) {
  const src = readFileSync(i18nPath, 'utf8')
  class FakeDate extends Date {
    constructor(...a) {
      if (a.length === 0) super(FAKE_NOW)
      else super(...a)
    }
    static now() {
      return FAKE_NOW
    }
  }
  const sandbox = {
    Date: FakeDate,
    Intl,
    JSON,
    Math,
    Map,
    Array,
    Number,
    String,
    Boolean,
    Error,
    Object,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    console,
    ...extraGlobals,
  }
  sandbox.globalThis = sandbox
  sandbox.window = sandbox
  sandbox.document = undefined
  sandbox.navigator = { language: lang }
  sandbox.require = () => ({})
  vm.createContext(sandbox)
  vm.runInContext(src, sandbox)
  const api = sandbox.AIIA_I18N
  const dbg = sandbox.AIIA_I18N__test
  api.registerLocale(lang, locale)
  api.setLang(lang)
  return { api, dbg, sandbox }
}

const failures = []

function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  log(
    ok ? 'PASS' : 'FAIL',
    label,
    `-> ${JSON.stringify(actual)} (expected ${JSON.stringify(expected)})`,
  )
  if (!ok) failures.push({ label, actual, expected })
}

function checkPair(label, out, expected) {
  const ok = out.web === expected && out.vsc === expected
  log(
    ok ? 'PASS' : 'FAIL',
    label,
    `web=${JSON.stringify(out.web)} vsc=${JSON.stringify(out.vsc)} expect=${JSON.stringify(expected)}`,
  )
  if (!ok) failures.push({ label, web: out.web, vsc: out.vsc, expected })
}

function runBoth(lang, locale, key, params) {
  const w = loadI18n(WEB, lang, locale).api
  const v = loadI18n(VSC, lang, locale).api
  return { web: w.t(key, params), vsc: v.t(key, params) }
}

// ---- E1..E4 formatRelativeFromNow boundaries & pathological deltas ----
console.log('\n=== E1-E4 formatRelativeFromNow ===')
{
  const cases = [
    ['E1 44s future', 44_000, 'in 44 seconds'],
    ['E1 45s promote', 45_000, 'in 1 minute'],
    ['E1 2699s (45 min cap)', 2_699_000, 'in 45 minutes'],
    ['E1 2700s promote hour', 2_700_000, 'in 1 hour'],
    ['E1 79200s promote day', 79_200_000, 'in 1 day'],
    ['E1 2246400s promote month', 2_246_400_000, 'in 1 month'],
    ['E1 28512000s promote year', 28_512_000_000, 'in 1 year'],
    ['E2 -45s promote', -45_000, '1 minute ago'],
    ['E2 -2700s promote', -2_700_000, '1 hour ago'],
    ['E3 MAX_SAFE delta', Number.MAX_SAFE_INTEGER, null],
    ['E4 Infinity delta handled', Infinity, null],
  ]
  const webApi = loadI18n(WEB, 'en').api
  const vscApi = loadI18n(VSC, 'en').api
  for (const [label, delta, expected] of cases) {
    const target = delta === Infinity ? Number.POSITIVE_INFINITY : FAKE_NOW + delta
    const w = webApi.formatRelativeFromNow(target)
    const v = vscApi.formatRelativeFromNow(target)
    if (expected === null) {
      const ok =
        typeof w === 'string' &&
        typeof v === 'string' &&
        w.length > 0 &&
        v.length > 0 &&
        w === v
      log(
        ok ? 'PASS' : 'FAIL',
        label,
        `web=${JSON.stringify(w)} vsc=${JSON.stringify(v)}`,
      )
      if (!ok) failures.push({ label, w, v })
    } else {
      checkPair(label, { web: w, vsc: v }, expected)
    }
  }
}

// ---- E5 apostrophe: every DOUBLE_OPTIONAL rule ----
console.log('\n=== E5 apostrophe (DOUBLE_OPTIONAL) rules ===')
{
  const table = [
    ["E5a double-apos escape", { msg: "it''s fine" }, {}, "it's fine"],
    ['E5b quoted braces', { msg: "render '{literal}'" }, { x: 1 }, 'render {literal}'],
    [
      'E5c quoted hash in plural',
      { msg: "{n, plural, one {# item (tag '#')} other {# items (tag '#')}}" },
      { n: 1 },
      '1 item (tag #)',
    ],
    ['E5d lone apos literal', { msg: "I don't know" }, {}, "I don't know"],
    ["E5e mixed quoted+double", { msg: "I said '{''Wow!''}'" }, {}, "I said {'Wow!'}"],
    ['E5f empty quoted span', { msg: "before '{}'after" }, {}, 'before {}after'],
    ['E5g unclosed quote eats rest', { msg: "before '{abc" }, {}, 'before {abc'],
  ]
  for (const [label, locale, params, expected] of table) {
    checkPair(label, runBoth('en', locale, 'msg', params), expected)
  }
}

// ---- E6 nested ICU (3 levels) with correct # scoping ----
console.log('\n=== E6 nested ICU (3-level # scoping) ===')
{
  const locale = {
    msg:
      '{items, plural, ' +
      'one {{status, select, ' +
      'new {just added} ' +
      'done {finished} ' +
      'other {{count, plural, one {1 step} other {# steps}}}' +
      '}} ' +
      'other {# items}}',
  }
  checkPair(
    'E6a items=1 status=new',
    runBoth('en', locale, 'msg', { items: 1, status: 'new' }),
    'just added',
  )
  checkPair(
    'E6b items=1 status=other count=3',
    runBoth('en', locale, 'msg', { items: 1, status: 'other', count: 3 }),
    '3 steps',
  )
  checkPair('E6c items=5', runBoth('en', locale, 'msg', { items: 5 }), '5 items')
}

// ---- E7 LRU hard cap + partition ----
console.log('\n=== E7 LRU hard cap + partition ===')
{
  const { api, dbg } = loadI18n(WEB, 'en')
  dbg.clearIntlCaches()
  for (let i = 0; i < 100; i++) api.formatNumber(i, { maximumFractionDigits: i })
  check(
    'E7a NumberFormat bucket saturates at 50',
    dbg.getIntlCacheSize('NumberFormat'),
    50,
  )
  api.formatDate(new Date(0), { dateStyle: 'short' })
  check('E7b DateTimeFormat untouched by NF churn', dbg.getIntlCacheSize('DateTimeFormat'), 1)
}

// ---- E8 LRU eviction order ----
console.log('\n=== E8 LRU eviction order ===')
{
  const { api, dbg } = loadI18n(WEB, 'en')
  dbg.clearIntlCaches()
  for (let i = 0; i < 50; i++) api.formatNumber(0, { maximumFractionDigits: i })
  api.formatNumber(0, { maximumFractionDigits: 0 })
  api.formatNumber(0, { maximumFractionDigits: 999 })
  const keys = dbg.peekIntlCacheKeys('NumberFormat')
  const hasOpt0 = keys.some((k) => k.endsWith('{"maximumFractionDigits":0}'))
  const hasOpt1 = keys.some((k) => k.endsWith('{"maximumFractionDigits":1}'))
  check('E8a touched entry survives', hasOpt0, true)
  check('E8b oldest non-touched evicted', hasOpt1, false)
  check('E8c bucket size stays at cap', keys.length, 50)
}

// ---- E9 missing-key observability ----
console.log('\n=== E9 missing-key observability ===')
{
  for (const [tag, libPath] of [
    ['WEB', WEB],
    ['VSC', VSC],
  ]) {
    const warnLog = []
    const captureConsole = {
      ...console,
      warn: (...args) => warnLog.push(args.map(String).join(' ')),
    }
    const { api } = loadI18n(libPath, 'en', { ok: 'hello' }, { console: captureConsole })
    api.setMissingKeyHandler(() => {
      throw new Error('boom-' + tag)
    })
    const ret = api.t('no.such.key')
    check(`E9 ${tag} returns raw key`, ret, 'no.such.key')
    check(
      `E9 ${tag} console.warn has [i18n] missing-key handler`,
      warnLog.some((l) => l.includes('missing-key handler') && l.includes('boom-' + tag)),
      true,
    )
  }
}

// ---- E10 prototype-pollution (Batch-1.5 H2 / H3) ----
console.log('\n=== E10 prototype pollution ===')
{
  for (const [key, params, label] of [
    ['greet', {}, 'E10a mustache __proto__ preserved'],
    ['greet_ctor', {}, 'E10b mustache constructor preserved'],
    ['greet_toString', {}, 'E10c mustache toString preserved'],
  ]) {
    const out = runBoth(
      'en',
      {
        greet: 'hi {{__proto__}}',
        greet_ctor: 'hi {{constructor}}',
        greet_toString: 'hi {{toString}}',
      },
      key,
      params,
    )
    const expected = {
      greet: 'hi {{__proto__}}',
      greet_ctor: 'hi {{constructor}}',
      greet_toString: 'hi {{toString}}',
    }[key]
    checkPair(label, out, expected)
  }
  // resolve-side: dotted key with polluting segment must miss.
  const web = loadI18n(WEB, 'en', { ui: { btn: { save: 'Save' } } }).api
  const vsc = loadI18n(VSC, 'en', { ui: { btn: { save: 'Save' } } }).api
  check(
    'E10d resolve proto-chain lookup returns raw key (web)',
    web.t('ui.__proto__.toString'),
    'ui.__proto__.toString',
  )
  check(
    'E10e resolve proto-chain lookup returns raw key (vsc)',
    vsc.t('ui.__proto__.toString'),
    'ui.__proto__.toString',
  )
}

// ---- E11 Intl cache key stable under option-key permutation (Batch-1.5 H1) ----
console.log('\n=== E11 Intl cache stable-sorted key ===')
{
  const { api, dbg } = loadI18n(WEB, 'en')
  dbg.clearIntlCaches()
  api.formatNumber(1, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
  api.formatNumber(2, { maximumFractionDigits: 2, style: 'currency', currency: 'USD' })
  api.formatNumber(3, { currency: 'USD', maximumFractionDigits: 2, style: 'currency' })
  check(
    'E11a three permutations collapse to one bucket entry',
    dbg.getIntlCacheSize('NumberFormat'),
    1,
  )
}

// ---- R5 apostrophe + plural mix ----
console.log('\n=== R5 apostrophe + plural mix ===')
{
  const locale = {
    msg:
      "You have {count, plural, one {# task (don''t forget!)} other {# tasks: '{#total}' = #}}",
  }
  checkPair(
    'R5a count=1 apostrophe in one',
    runBoth('en', locale, 'msg', { count: 1 }),
    "You have 1 task (don't forget!)",
  )
  checkPair(
    'R5b count=5 quoted #total literal + trailing # expands',
    runBoth('en', locale, 'msg', { count: 5 }),
    'You have 5 tasks: {#total} = 5',
  )
}

// ---- R6 PluralRules LRU ----
console.log('\n=== R6 PluralRules LRU ===')
{
  const { api, dbg } = loadI18n(WEB, 'en')
  dbg.clearIntlCaches()
  const tags = []
  for (let i = 0; i < 30; i++) tags.push('en-' + i.toString(36).toUpperCase())
  for (const tag of tags) {
    api.setLang(tag)
    api.registerLocale(tag, { m: '{c, plural, one {# item} other {# items}}' })
    api.t('m', { c: 1 })
  }
  const size = dbg.getPluralRulesCacheSize()
  check('R6 PluralRules cache bounded ≤ 16', size <= 16 && size > 0, true)
}

// ---- E12 selectordinal + ordinal PluralRules LRU (Batch-2 H9) ----
console.log('\n=== E12 selectordinal (Batch-2 H9) ===')
{
  // CLDR 英文 ordinal 类别（out-of-band 验证过 Intl.PluralRules({type:'ordinal'})）
  const ordinalLocale = {
    msg:
      '{n, selectordinal, ' +
      'one {#st} two {#nd} few {#rd} other {#th}' +
      '}',
  }
  const cases = [
    [1, '1st'],
    [2, '2nd'],
    [3, '3rd'],
    [4, '4th'],
    [11, '11th'],
    [12, '12th'],
    [13, '13th'],
    [21, '21st'],
    [22, '22nd'],
    [23, '23rd'],
    [101, '101st'],
    [111, '111th'],
    [121, '121st'],
  ]
  for (const [n, expected] of cases) {
    checkPair(`E12a en n=${n}`, runBoth('en', ordinalLocale, 'msg', { n }), expected)
  }
  // 中文 ordinal 只有 ``other`` 一档，任何数字都落到同一分支。
  for (const n of [1, 2, 3, 21, 101]) {
    checkPair(`E12b zh-CN n=${n}`, runBoth('zh-CN', ordinalLocale, 'msg', { n }), `${n}th`)
  }
  // ``=N`` 精确匹配仍应胜过 CLDR 类别（与 cardinal plural 对齐）。
  const exactLocale = {
    msg: '{n, selectordinal, =0 {first-ever} one {#st} other {#th}}',
  }
  checkPair('E12c exact =0 beats other', runBoth('en', exactLocale, 'msg', { n: 0 }), 'first-ever')
  checkPair('E12d exact =0 non-match falls through', runBoth('en', exactLocale, 'msg', { n: 1 }), '1st')
  // cardinal/ordinal 各自 LRU 桶，混跑时两个 cache 都应各自增长。
  const cardinalLocale = { msg: '{n, plural, one {# item} other {# items}}' }
  const { api: api12, dbg: dbg12 } = loadI18n(WEB, 'en', ordinalLocale)
  dbg12.clearIntlCaches()
  api12.t('msg', { n: 1 })
  api12.registerLocale('en', cardinalLocale)
  api12.t('msg', { n: 1 })
  check('E12e cardinal PluralRules cache populated', dbg12.getPluralRulesCacheSize() >= 1, true)
  check('E12f ordinal PluralRules cache populated', dbg12.getPluralRulesOrdinalCacheSize() >= 1, true)
}

// ---- E13 circular / BigInt / Date-via-toJSON cache keys (Batch-2 H8) ----
console.log('\n=== E13 cycle-safe cache key (Batch-2 H8) ===')
{
  const { api, dbg } = loadI18n(WEB, 'en')
  dbg.clearIntlCaches()
  // 循环 options 不能崩，且仍产出一条 cache 项。
  const a = { style: 'decimal', context: null }
  a.context = a
  const out13a = api.formatNumber(1, a)
  check('E13a cycle: formatNumber returns a formatted string', out13a, '1')
  check('E13b cycle: NumberFormat bucket has exactly one entry', dbg.getIntlCacheSize('NumberFormat'), 1)
  // 不同 shape 的循环 options 不得 alias 到同一 entry（_intlKey shape-signature fallback）。
  const b = { style: 'decimal', note: 'extra' }
  b.note = b
  api.formatNumber(1, b)
  check(
    'E13c cycle: distinct shapes → distinct cache entries',
    dbg.getIntlCacheSize('NumberFormat') >= 2,
    true,
  )
  // BigInt 走 _stableStringifyInner 的 typeof==='bigint' 分支，不得抛错且不同 BigInt 不得同 key。
  dbg.clearIntlCaches()
  api.formatNumber(1, { minimumIntegerDigits: 2, bigMarker: 1n })
  api.formatNumber(1, { minimumIntegerDigits: 2, bigMarker: 2n })
  check(
    'E13d BigInt in options produces distinct cache entries',
    dbg.getIntlCacheSize('NumberFormat'),
    2,
  )
  // Date 经 toJSON 收敛为 ISO 字符串（与 JSON.stringify 一致），语义等价的两个 Date 合并。
  dbg.clearIntlCaches()
  const fixed = new Date('2025-01-01T00:00:00.000Z')
  api.formatNumber(1, { style: 'decimal', anchoredAt: fixed })
  api.formatNumber(1, { style: 'decimal', anchoredAt: new Date(fixed.getTime()) })
  check(
    'E13e Date toJSON canonicalisation collapses to one cache entry',
    dbg.getIntlCacheSize('NumberFormat'),
    1,
  )
}

// ---- E14 non-string resolve warn-once (Batch-2 H11) ----
console.log('\n=== E14 non-string resolve warn-once (Batch-2 H11) ===')
{
  for (const [tag, libPath] of [
    ['WEB', WEB],
    ['VSC', VSC],
  ]) {
    const warnLog = []
    const captureConsole = {
      ...console,
      warn: (...args) => warnLog.push(args.map(String).join(' ')),
    }
    const { api, dbg } = loadI18n(
      libPath,
      'en',
      { aiia: { foo: { bar: 'deep' } } },
      { console: captureConsole },
    )
    dbg.resetNonStringHits()
    // 同一 (lang,key) 连打三次 → 仅一次 warn（warn-once）
    api.t('aiia.foo')
    api.t('aiia.foo')
    api.t('aiia.foo')
    check(
      `E14 ${tag} warn-once: exactly 1 warn per (lang,key)`,
      warnLog.filter((l) => l.toLowerCase().includes('non-string')).length,
      1,
    )
    check(
      `E14 ${tag} warn contains key + hint`,
      warnLog[0].includes('aiia.foo') && warnLog[0].toLowerCase().includes('deeper key'),
      true,
    )
    // pytest 侧可直接读 hits，无需解析 console
    const hits = dbg.getNonStringHits()
    check(
      `E14 ${tag} hits roundtrip through getNonStringHits`,
      hits.length === 1 && hits[0].key === 'aiia.foo' && hits[0].type === 'object',
      true,
    )
    // strict 模式应抛 non-string resolve，而不是退到 missing-key 路径
    dbg.resetNonStringHits()
    api.setStrict(true)
    let thrown = null
    try {
      api.t('aiia.foo')
    } catch (e) {
      thrown = e
    }
    api.setStrict(false)
    check(
      `E14 ${tag} strict mode throws non-string error`,
      thrown != null && /non-string resolve/i.test(thrown.message) && /aiia\.foo/.test(thrown.message),
      true,
    )
  }
}

// ---- E16 wrapBidi (Batch-3 H14) ----
console.log('\n=== E16 wrapBidi FSI/PDI (Batch-3 H14) ===')
{
  const FSI = '\u2068'
  const PDI = '\u2069'
  for (const [tag, libPath] of [
    ['WEB', WEB],
    ['VSC', VSC],
  ]) {
    const { api } = loadI18n(libPath, 'en', {})
    check(`E16 ${tag} wraps plain string`, api.wrapBidi('Ada'), FSI + 'Ada' + PDI)
    check(`E16 ${tag} null → empty`, api.wrapBidi(null), '')
    check(`E16 ${tag} undefined → empty`, api.wrapBidi(undefined), '')
    check(`E16 ${tag} missing arg → empty`, api.wrapBidi(), '')
    check(`E16 ${tag} empty string → empty`, api.wrapBidi(''), '')
    check(`E16 ${tag} coerces number`, api.wrapBidi(42), FSI + '42' + PDI)
    check(`E16 ${tag} idempotent on wrapped input`, api.wrapBidi(FSI + 'x' + PDI), FSI + 'x' + PDI)
    check(
      `E16 ${tag} RTL segment gets its own isolate`,
      api.wrapBidi('עברית'),
      FSI + 'עברית' + PDI,
    )
  }
  // Byte-parity：web / vsc 对每个样本必须给出同样输出。
  const samples = ['Ada', '', 'עברית', 'abc مرحبا', '42', FSI + 'pre' + PDI, 'صَفر']
  const webApi = loadI18n(WEB, 'en').api
  const vscApi = loadI18n(VSC, 'en').api
  for (const s of samples) {
    const w = webApi.wrapBidi(s)
    const v = vscApi.wrapBidi(s)
    const ok = w === v
    log(ok ? 'PASS' : 'FAIL', `E16 parity wrapBidi(${JSON.stringify(s)})`, `web=${JSON.stringify(w)} vsc=${JSON.stringify(v)}`)
    if (!ok) failures.push({ label: 'E16 parity', input: s, web: w, vsc: v })
  }
}

// ---- E17 ICU AST compile cache (Batch-3 H12) ----
console.log('\n=== E17 ICU AST compile cache (Batch-3 H12) ===')
{
  for (const [tag, libPath] of [
    ['WEB', WEB],
    ['VSC', VSC],
  ]) {
    const { api, dbg } = loadI18n(libPath, 'en', {
      msg: '{n, plural, one {# item} other {# items}}',
      hello: 'Hello {{name}}',
      literal: 'no placeholders at all',
    })
    // 调试钩子存在
    check(
      `E17 ${tag} debug hooks present`,
      typeof dbg.getIcuCompileCacheSize === 'function' &&
        typeof dbg.peekIcuCompileKeys === 'function',
      true,
    )
    // 同模板热重渲 → 缓存稳定在 1
    dbg.clearIntlCaches()
    for (let i = 0; i < 8; i++) api.t('msg', { n: i })
    check(`E17 ${tag} hot-hit pins at 1`, dbg.getIcuCompileCacheSize(), 1)
    // 无 `{` 字面量走 fast path、不进缓存（防止渲染后 plural body 污染 LRU）
    dbg.clearIntlCaches()
    for (let i = 0; i < 8; i++) api.t('literal')
    check(`E17 ${tag} fast-path literal not cached`, dbg.getIcuCompileCacheSize(), 0)
    // 带 `{{…}}` 的 mustache 模板占一条 trivial entry
    dbg.clearIntlCaches()
    api.t('hello', { name: 'Ada' })
    check(`E17 ${tag} mustache template counted as trivial entry`, dbg.getIcuCompileCacheSize(), 1)
    // clearIntlCaches() 同步清空 ICU 桶
    dbg.clearIntlCaches()
    check(`E17 ${tag} clear empties ICU bucket`, dbg.getIcuCompileCacheSize(), 0)
  }
  // LRU 硬上限 256
  {
    const bundle = {}
    for (let i = 0; i < 400; i++) {
      bundle['k' + i] = 'row ' + i + ' — {n, plural, one {# a-' + i + '} other {# b-' + i + '}}'
    }
    const { api, dbg } = loadI18n(WEB, 'en', bundle)
    for (let j = 0; j < 400; j++) api.t('k' + j, { n: 1 })
    const sizeWeb = dbg.getIcuCompileCacheSize()
    log(
      sizeWeb <= 256 && sizeWeb >= 200 ? 'PASS' : 'FAIL',
      'E17 WEB LRU cap 256 enforced',
      `size=${sizeWeb}`,
    )
    if (sizeWeb > 256 || sizeWeb < 200) {
      failures.push({ label: 'E17 WEB LRU cap', actual: sizeWeb, expected: '<=256, >=200' })
    }
    const vsc = loadI18n(VSC, 'en', bundle)
    for (let j = 0; j < 400; j++) vsc.api.t('k' + j, { n: 1 })
    const sizeVsc = vsc.dbg.getIcuCompileCacheSize()
    log(
      sizeVsc <= 256 && sizeVsc >= 200 ? 'PASS' : 'FAIL',
      'E17 VSC LRU cap 256 enforced',
      `size=${sizeVsc}`,
    )
    if (sizeVsc > 256 || sizeVsc < 200) {
      failures.push({ label: 'E17 VSC LRU cap', actual: sizeVsc, expected: '<=256, >=200' })
    }
    check('E17 parity: both halves report same cache geometry', sizeWeb, sizeVsc)
  }
}

// ---- E18 smoke fuzz (Batch-3 H16 cross-check) ----
console.log('\n=== E18 smoke fuzz (Batch-3 H16) ===')
{
  // 精选 landmine 模板——每条都曾在实际 ICU tokenizer 里炸过（formatjs /
  // i18next / icu4j 的历史 issue），这里作为 fuzz 的人工边界样本。
  const mines = [
    // 嵌套 plural + 转义撇号 + 尾部字面量
    [
      "{n, plural, =0 {It''s none} one {# thing here} other {# ''{items}'' left}}",
      { n: 0 },
      "It's none",
    ],
    [
      "{n, plural, =0 {It''s none} one {# thing here} other {# ''{items}'' left}}",
      { n: 3 },
      "3 '{items}' left",
    ],
    // 三层嵌套（plural → select → plural）：select 分支里的字面量 ``one``
    // 必须当成普通文本，不能让内层 `#` 逃逸到外层 items 的数值上。
    [
      '{items, plural, one {{status, select, ok {one ok} other {one {count, plural, one {1 step} other {# steps}}}}} other {# items}}',
      { items: 1, status: 'other', count: 5 },
      'one 5 steps',
    ],
    // selectordinal + =N 精确匹配优先级
    ['{n, selectordinal, =1 {first!} one {#st} two {#nd} few {#rd} other {#th}}', { n: 1 }, 'first!'],
    ['{n, selectordinal, =1 {first!} one {#st} two {#nd} few {#rd} other {#th}}', { n: 2 }, '2nd'],
    // 纯 mustache，无 ICU
    ['Hello {{name}}!', { name: 'Ada' }, 'Hello Ada!'],
    // trivial 字面量走 fast path，不占缓存
    ['just a literal', {}, 'just a literal'],
  ]
  for (const [tpl, params, expected] of mines) {
    const webApi = loadI18n(WEB, 'en', { k: tpl }).api
    const vscApi = loadI18n(VSC, 'en', { k: tpl }).api
    const w = webApi.t('k', params)
    const v = vscApi.t('k', params)
    const parityOk = w === v
    const valueOk = w === expected
    log(
      parityOk && valueOk ? 'PASS' : 'FAIL',
      `E18 ${tpl.slice(0, 38).replace(/\n/g, ' ')}…`,
      `web=${JSON.stringify(w)} vsc=${JSON.stringify(v)} expect=${JSON.stringify(expected)}`,
    )
    if (!parityOk || !valueOk) {
      failures.push({ label: 'E18 fuzz mine', tpl, params, web: w, vsc: v, expected })
    }
  }
}

// ---- BP byte-parity sanity ----
console.log('\n=== BP byte-parity sanity ===')
{
  const locale = {
    greet: 'Hello, {{name}}!',
    apos: "Don''t forget: render '{literal}'",
    nested:
      '{items, plural, one {{status, select, other {{count, plural, one {1 step} other {# steps}}}}} other {# items}}',
  }
  for (const [key, params, label] of [
    ['greet', { name: 'Ada' }, 'BP greet'],
    ['apos', {}, 'BP apos'],
    ['nested', { items: 1, status: 'other', count: 4 }, 'BP nested one'],
    ['nested', { items: 7 }, 'BP nested other'],
  ]) {
    const out = runBoth('en', locale, key, params)
    const ok = out.web === out.vsc
    log(
      ok ? 'PASS' : 'FAIL',
      label,
      `web=${JSON.stringify(out.web)} vsc=${JSON.stringify(out.vsc)}`,
    )
    if (!ok) failures.push({ label, ...out })
  }
}

console.log(
  `\n=== SUMMARY ===\n${failures.length === 0 ? 'ALL RED-TEAM CASES PASS' : failures.length + ' failures'}`,
)
if (failures.length) {
  console.log(JSON.stringify(failures, null, 2))
  process.exit(1)
}
