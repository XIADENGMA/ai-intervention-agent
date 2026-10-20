const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const vm = require('vm')
const vscode = require('vscode')

const LANGS = ['en', 'zh-CN', 'zh-TW']
const CJK = /[\u3400-\u9fff]/
const MISSING_EXTENSION_DIR = path.join(os.tmpdir(), 'aiia-no-such-extension-dir')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

function makeOutputChannel() {
  return {
    name: 'new-task-notification-test',
    append() {},
    appendLine() {},
    clear() {},
    show() {},
    hide() {},
    dispose() {}
  }
}

function makeProvider(extensionDir) {
  const ext = getExtension()
  const { WebviewProvider } = require(path.join(ext.extensionPath, 'dist', 'webview.js'))
  const provider = new WebviewProvider(
    vscode.Uri.file(extensionDir || ext.extensionPath),
    makeOutputChannel(),
    'http://127.0.0.1:1',
    '0.0.0'
  )
  provider._fetchNotificationConfig = async () => ({ enabled: true, macosNativeEnabled: false })
  const events = []
  provider._dispatchNotificationEvent = event => {
    events.push(event)
  }
  return { provider, events }
}

function webviewTranslator() {
  const ext = getExtension()
  const all = {}
  for (const lang of LANGS) {
    all[lang] = JSON.parse(fs.readFileSync(path.join(ext.extensionPath, 'locales', lang + '.json'), 'utf8'))
  }
  const sandbox = { __AIIA_I18N_LANG: 'en', __AIIA_I18N_LOCALE: all.en, __AIIA_I18N_ALL_LOCALES: all }
  vm.runInNewContext(fs.readFileSync(path.join(ext.extensionPath, 'i18n.js'), 'utf8'), sandbox)
  return (lang, key, params) => {
    sandbox.AIIA_I18N.setLang(lang)
    return sandbox.AIIA_I18N.t(key, params)
  }
}

async function notify(provider, events, tasks) {
  events.length = 0
  await provider.dispatchNewTaskNotification(tasks)
  assert.strictEqual(events.length, 1, 'exactly one notification event must be dispatched')
  return events[0]
}

suite('Host new-task notification language', () => {
  test('English reads naturally for one task, several tasks and a prompt summary', async () => {
    const { provider, events } = makeProvider()
    provider._cachedServerLang = 'en'

    const one = await notify(provider, events, [{ id: 't-1', prompt: '' }])
    assert.strictEqual(one.title, 'AI Intervention Agent')
    assert.strictEqual(one.message, 'New task added: t-1')

    const many = await notify(provider, events, [
      { id: 't-1', prompt: '' },
      { id: 't-2', prompt: '' },
      { id: 't-3', prompt: '' }
    ])
    assert.strictEqual(many.message, 'Received 3 new tasks')

    const summarised = await notify(provider, events, [{ id: 't-1', prompt: 'Review the\n  diff' }])
    assert.strictEqual(summarised.message, 'Review the diff')

    const summarisedMany = await notify(provider, events, [
      { id: 't-1', prompt: 'Review the diff' },
      { id: 't-2', prompt: 'later' }
    ])
    assert.strictEqual(summarisedMany.message, 'Review the diff (2 tasks)')
  })

  test('a long prompt summary is cut at 120 characters with an ellipsis', async () => {
    const { provider, events } = makeProvider()
    provider._cachedServerLang = 'en'
    const event = await notify(provider, events, [{ id: 't-1', prompt: 'x'.repeat(300) }])
    assert.strictEqual(event.message, 'x'.repeat(120) + '\u2026')
  })

  test('every supported language renders exactly what the webview renders for the same task set', async () => {
    const { provider, events } = makeProvider()
    const translate = webviewTranslator()
    const english = {}
    for (const lang of LANGS) {
      provider._cachedServerLang = lang

      const one = await notify(provider, events, [{ id: 't-9', prompt: '' }])
      assert.strictEqual(one.title, translate(lang, 'ui.notification.title'), `${lang} title`)
      assert.strictEqual(one.message, translate(lang, 'ui.notification.newTask', { id: 't-9' }), `${lang} one task`)

      const many = await notify(provider, events, [
        { id: 'a', prompt: '' },
        { id: 'b', prompt: '' }
      ])
      assert.strictEqual(many.message, translate(lang, 'ui.notification.newTasks', { count: 2 }), `${lang} two tasks`)

      const withSummary = await notify(provider, events, [
        { id: 'a', prompt: 'summary' },
        { id: 'b', prompt: '' },
        { id: 'c', prompt: '' }
      ])
      assert.strictEqual(
        withSummary.message,
        'summary ' + translate(lang, 'ui.notification.taskCountSuffix', { count: 3 }),
        `${lang} summary with count`
      )

      if (lang === 'en') {
        english.title = one.title
        english.one = one.message
        english.many = many.message
      } else {
        assert.ok(CJK.test(one.title), `${lang} title must be localised`)
        assert.ok(CJK.test(one.message), `${lang} single-task message must be localised`)
        assert.ok(CJK.test(many.message), `${lang} multi-task message must be localised`)
        assert.notStrictEqual(one.title, english.title)
        assert.notStrictEqual(one.message, english.one)
        assert.notStrictEqual(many.message, english.many)
      }
    }
  })

  test('traditional and simplified Chinese stay distinct', async () => {
    const { provider, events } = makeProvider()
    provider._cachedServerLang = 'zh-CN'
    const simplified = await notify(provider, events, [{ id: 'a', prompt: '' }])
    provider._cachedServerLang = 'zh-TW'
    const traditional = await notify(provider, events, [{ id: 'a', prompt: '' }])
    assert.notStrictEqual(simplified.title, traditional.title)
    assert.notStrictEqual(simplified.message, traditional.message)
  })

  test('the language follows the server setting between two notifications', async () => {
    const { provider, events } = makeProvider()
    provider._cachedServerLang = 'en'
    const first = await notify(provider, events, [{ id: 'a', prompt: '' }])
    provider._cachedServerLang = 'zh-CN'
    const second = await notify(provider, events, [{ id: 'a', prompt: '' }])
    assert.strictEqual(first.title, 'AI Intervention Agent')
    assert.ok(CJK.test(second.title))
  })

  test('automatic language follows the VS Code display language, an explicit server language wins', async () => {
    const { provider, events } = makeProvider()
    const translate = webviewTranslator()
    provider._cachedServerLang = null
    for (const [display, expected] of [
      ['en', 'en'],
      ['zh-cn', 'zh-CN'],
      ['zh-tw', 'zh-TW'],
      ['fr', 'en']
    ]) {
      provider._displayLanguage = () => display
      const event = await notify(provider, events, [{ id: 'a', prompt: '' }])
      assert.strictEqual(event.title, translate(expected, 'ui.notification.title'), `display language ${display}`)
    }
    provider._cachedServerLang = 'en'
    provider._displayLanguage = () => 'zh-cn'
    const explicit = await notify(provider, events, [{ id: 'a', prompt: '' }])
    assert.strictEqual(explicit.title, 'AI Intervention Agent')
  })

  test('works before the panel was ever opened (locales are read on demand)', async () => {
    const { provider, events } = makeProvider()
    provider._cachedServerLang = 'zh-TW'
    assert.deepStrictEqual(Object.keys(provider._cachedLocales), [])
    const event = await notify(provider, events, [{ id: 'a', prompt: '' }])
    assert.ok(CJK.test(event.title))
    assert.ok(Object.keys(provider._cachedLocales).includes('zh-TW'))
  })

  test('a missing locale file falls back to English instead of showing raw keys', async () => {
    const { provider, events } = makeProvider(MISSING_EXTENSION_DIR)
    provider._cachedLocales = { en: { ui: { notification: { title: 'Cached title', newTask: 'Cached {{id}}' } } } }
    provider._cachedServerLang = 'zh-CN'
    const event = await notify(provider, events, [{ id: 'a', prompt: '' }])
    assert.strictEqual(event.title, 'Cached title')
    assert.strictEqual(event.message, 'Cached a')
  })

  test('without any locale data the key is shown rather than throwing', async () => {
    const { provider, events } = makeProvider(MISSING_EXTENSION_DIR)
    provider._cachedServerLang = 'en'
    const event = await notify(provider, events, [{ id: 'a', prompt: '' }])
    assert.strictEqual(event.title, 'ui.notification.title')
    assert.strictEqual(event.message, 'ui.notification.newTask')
  })

  test('the dispatched event keeps its routing metadata', async () => {
    const { provider, events } = makeProvider()
    provider._cachedServerLang = 'en'
    const event = await notify(provider, events, [
      { id: 'a', prompt: '' },
      { id: 'b', prompt: '' }
    ])
    assert.strictEqual(event.dedupeKey, 'new_tasks:a|b')
    assert.deepStrictEqual(event.types, ['vscode'])
    assert.strictEqual(event.metadata.kind, 'new_tasks')
    assert.deepStrictEqual(event.metadata.taskIds, ['a', 'b'])
  })
})
