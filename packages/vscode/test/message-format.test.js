const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const vscode = require('vscode')

const LANGS = ['en', 'zh-CN', 'zh-TW']
const COUNTS = [0, 1, 2, 3, 5, 11, 21, 101, 1000, 1234567]

function extensionPath() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext.extensionPath
}

function loadModule() {
  return require(path.join(extensionPath(), 'dist', 'message-format.js'))
}

function readLocale(lang) {
  return JSON.parse(fs.readFileSync(path.join(extensionPath(), 'locales', lang + '.json'), 'utf8'))
}

function loadWebviewI18n() {
  const all = {}
  for (const lang of LANGS) all[lang] = readLocale(lang)
  const sandbox = {
    __AIIA_I18N_LANG: 'en',
    __AIIA_I18N_LOCALE: all.en,
    __AIIA_I18N_ALL_LOCALES: all
  }
  vm.runInNewContext(fs.readFileSync(path.join(extensionPath(), 'i18n.js'), 'utf8'), sandbox)
  assert.ok(sandbox.AIIA_I18N, 'i18n.js did not register AIIA_I18N')
  return sandbox.AIIA_I18N
}

suite('Host message formatting', () => {
  test('lookupMessage walks dotted keys and only returns strings', () => {
    const { lookupMessage } = loadModule()
    const locale = { a: { b: 'text', c: { d: 'deep' }, n: 3 } }
    assert.strictEqual(lookupMessage(locale, 'a.b'), 'text')
    assert.strictEqual(lookupMessage(locale, 'a.c.d'), 'deep')
    assert.strictEqual(lookupMessage(locale, 'a.c'), null)
    assert.strictEqual(lookupMessage(locale, 'a.n'), null)
    assert.strictEqual(lookupMessage(locale, 'a.missing'), null)
    assert.strictEqual(lookupMessage(locale, 'a.b.deeper'), null)
    assert.strictEqual(lookupMessage(null, 'a.b'), null)
    assert.strictEqual(lookupMessage(undefined, 'a'), null)
  })

  test('placeholders are filled and unknown ones are left alone', () => {
    const { formatMessage } = loadModule()
    assert.strictEqual(formatMessage('Task {{id}} added', { id: 'x1' }, 'en'), 'Task x1 added')
    assert.strictEqual(formatMessage('Task {{id}} added', {}, 'en'), 'Task {{id}} added')
    assert.strictEqual(formatMessage('{{a}}-{{a}}-{{b}}', { a: 1, b: 'z' }, 'en'), '1-1-z')
    assert.strictEqual(formatMessage('{{__proto__}} {{constructor}}', {}, 'en'), '{{__proto__}} {{constructor}}')
  })

  test('English plurals pick one/other and substitute #', () => {
    const { formatMessage } = loadModule()
    const template = 'Got {count, plural, one {# task} other {# tasks}}'
    assert.strictEqual(formatMessage(template, { count: 1 }, 'en'), 'Got 1 task')
    assert.strictEqual(formatMessage(template, { count: 2 }, 'en'), 'Got 2 tasks')
    assert.strictEqual(formatMessage(template, { count: 0 }, 'en'), 'Got 0 tasks')
    assert.strictEqual(formatMessage(template, { count: '3' }, 'en'), 'Got 3 tasks')
  })

  test('languages with a single plural form always use other', () => {
    const { formatMessage } = loadModule()
    const template = '共 {count, plural, other {# 个任务}}'
    for (const count of [0, 1, 2, 10]) {
      assert.strictEqual(formatMessage(template, { count }, 'zh-CN'), `共 ${count} 个任务`)
    }
  })

  test('an exact =N option wins over the plural category', () => {
    const { formatMessage } = loadModule()
    const template = '{count, plural, =0 {none} one {# item} other {# items}}'
    assert.strictEqual(formatMessage(template, { count: 0 }, 'en'), 'none')
    assert.strictEqual(formatMessage(template, { count: 1 }, 'en'), '1 item')
    assert.strictEqual(formatMessage(template, { count: 4 }, 'en'), '4 items')
  })

  test('a plural without a matching option falls back to other, then to empty', () => {
    const { formatMessage } = loadModule()
    assert.strictEqual(formatMessage('{n, plural, one {a} other {b}}', { n: 5 }, 'en'), 'b')
    assert.strictEqual(formatMessage('[{n, plural, one {a}}]', { n: 5 }, 'en'), '[]')
  })

  test('a missing or non-numeric count renders as zero', () => {
    const { formatMessage } = loadModule()
    const template = '{count, plural, one {# task} other {# tasks}}'
    assert.strictEqual(formatMessage(template, {}, 'en'), '0 tasks')
    assert.strictEqual(formatMessage(template, { count: 'many' }, 'en'), '0 tasks')
  })

  test('parameter values are inserted verbatim and never interpreted', () => {
    const { formatMessage } = loadModule()
    const hostile = '{count, plural, other {x}} {{count}} #'
    assert.strictEqual(formatMessage('Task: {{id}}', { id: hostile, count: 7 }, 'en'), 'Task: ' + hostile)
  })

  test('large counts are grouped for the language like the webview runtime does', () => {
    const { formatMessage } = loadModule()
    const template = '{count, plural, other {# tasks}}'
    assert.strictEqual(formatMessage(template, { count: 1234567 }, 'en'), '1,234,567 tasks')
  })

  test('every host notification string renders exactly like the webview i18n runtime', () => {
    const { formatMessage, lookupMessage } = loadModule()
    const web = loadWebviewI18n()
    const cases = []
    for (const lang of LANGS) {
      cases.push({ lang, key: 'ui.notification.title', params: {} })
      cases.push({ lang, key: 'ui.notification.newTask', params: { id: 'task-42' } })
      for (const count of COUNTS) {
        cases.push({ lang, key: 'ui.notification.newTasks', params: { count } })
        cases.push({ lang, key: 'ui.notification.taskCountSuffix', params: { count } })
      }
    }
    const mismatches = []
    for (const { lang, key, params } of cases) {
      web.setLang(lang)
      const expected = web.t(key, params)
      const template = lookupMessage(readLocale(lang), key)
      const actual = template === null ? null : formatMessage(template, params, lang)
      if (actual !== expected || expected === key) {
        mismatches.push(`${lang} ${key} ${JSON.stringify(params)}: host=${JSON.stringify(actual)} web=${JSON.stringify(expected)}`)
      }
    }
    assert.deepStrictEqual(mismatches, [])
  })
})
