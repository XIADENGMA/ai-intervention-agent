const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const vscode = require('vscode')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

function distPath(filename) {
  return path.join(getExtension().extensionPath, 'dist', filename)
}

function makeOutputChannel() {
  return {
    name: 'test-output',
    append() {},
    appendLine() {},
    clear() {},
    show() {},
    hide() {},
    dispose() {}
  }
}

function makeProvider(onLanguageChanged) {
  const ext = getExtension()
  const { WebviewProvider } = require(distPath('webview.js'))
  return new WebviewProvider(
    vscode.Uri.file(ext.extensionPath),
    makeOutputChannel(),
    'http://lang.test',
    '0.0.0',
    undefined,
    undefined,
    undefined,
    onLanguageChanged
  )
}

function renderHtml(provider) {
  const webview = {
    cspSource: 'vscode-resource:',
    asWebviewUri: uri => uri
  }
  return provider._getHtmlContent(webview)
}

function htmlLangOf(html) {
  const m = /<html lang="([^"]*)"/.exec(html)
  return m ? m[1] : null
}

function injectedGlobal(html, name) {
  const m = new RegExp('window\\.' + name + '="([^"]*)"').exec(html)
  return m ? m[1] : null
}

suite('UI language resolution (VSCode)', () => {
  test('lang.js ships with the extension', () => {
    assert.ok(fs.existsSync(distPath('lang.js')), 'Missing dist/lang.js in extension')
  })

  test('normalizeUiLang maps every zh variant to the right Chinese locale', () => {
    const { normalizeUiLang } = require(distPath('lang.js'))
    const table = [
      ['en', 'en'],
      ['en-US', 'en'],
      ['EN', 'en'],
      ['', 'en'],
      ['fr', 'en'],
      ['de', 'en'],
      ['ja', 'en'],
      ['zh', 'zh-CN'],
      ['zh-CN', 'zh-CN'],
      ['zh-cn', 'zh-CN'],
      ['zh-Hans', 'zh-CN'],
      ['zh-SG', 'zh-CN'],
      ['zh-TW', 'zh-TW'],
      ['zh-tw', 'zh-TW'],
      ['ZH-TW', 'zh-TW'],
      ['zh-HK', 'zh-TW'],
      ['zh-MO', 'zh-TW'],
      ['zh-Hant', 'zh-TW'],
      ['zh-Hant-TW', 'zh-TW'],
      ['zh-hant-hk', 'zh-TW'],
      ['  zh-tw  ', 'zh-TW']
    ]
    for (const [input, expected] of table) {
      assert.strictEqual(normalizeUiLang(input), expected, `normalizeUiLang(${JSON.stringify(input)})`)
    }
    for (const bad of [null, undefined, 0, 123, {}, []]) {
      assert.strictEqual(normalizeUiLang(bad), 'en', `normalizeUiLang(${String(bad)})`)
    }
  })

  test('resolveUiLang prefers an explicit server language and falls back to VS Code for auto', () => {
    const { resolveUiLang } = require(distPath('lang.js'))
    const table = [
      ['zh-CN', 'en', 'zh-CN'],
      ['zh-TW', 'en', 'zh-TW'],
      ['en', 'zh-tw', 'en'],
      ['auto', 'zh-tw', 'zh-TW'],
      ['auto', 'zh-cn', 'zh-CN'],
      ['auto', 'en', 'en'],
      ['AUTO', 'zh-hk', 'zh-TW'],
      ['', 'zh-tw', 'zh-TW'],
      [null, 'zh-cn', 'zh-CN'],
      [undefined, 'de', 'en'],
      ['fr', 'zh-tw', 'en']
    ]
    for (const [server, vsLang, expected] of table) {
      assert.strictEqual(
        resolveUiLang(server, vsLang),
        expected,
        `resolveUiLang(${JSON.stringify(server)}, ${JSON.stringify(vsLang)})`
      )
    }
  })

  test('host language mapping stays in sync with the webview i18n.js normalizeLang', () => {
    const { normalizeUiLang } = require(distPath('lang.js'))
    const source = fs.readFileSync(path.join(getExtension().extensionPath, 'i18n.js'), 'utf8')
    const context = vm.createContext({})
    vm.runInContext(source, context)
    const webviewNormalize = context.AIIA_I18N.normalizeLang
    assert.strictEqual(typeof webviewNormalize, 'function')

    const inputs = [
      'en', 'en-US', 'EN', '', 'fr', 'de', 'ja', 'pt-BR',
      'zh', 'zh-CN', 'zh-cn', 'zh-Hans', 'zh-SG', 'zh_TW',
      'zh-TW', 'zh-tw', 'zh-HK', 'zh-MO', 'zh-Hant', 'zh-Hant-TW', 'zh-hant-hk',
      null, undefined, 123
    ]
    for (const input of inputs) {
      assert.strictEqual(
        normalizeUiLang(input),
        webviewNormalize(input),
        `host/webview normalizeLang diverge for ${JSON.stringify(input)}`
      )
    }
  })

  test('generated webview HTML follows the cached server language, including zh-TW', async () => {
    const { normalizeUiLang } = require(distPath('lang.js'))
    const vsLang = normalizeUiLang(vscode.env.language)
    const provider = makeProvider()
    try {
      await provider._preloadResources()

      for (const [cached, expected] of [
        ['zh-CN', 'zh-CN'],
        ['zh-TW', 'zh-TW'],
        ['en', 'en'],
        [null, vsLang]
      ]) {
        provider._cachedServerLang = cached
        const html = renderHtml(provider)
        assert.strictEqual(htmlLangOf(html), expected, `<html lang> for cached=${cached}`)
        assert.strictEqual(
          injectedGlobal(html, '__AIIA_I18N_LANG'),
          expected,
          `__AIIA_I18N_LANG for cached=${cached}`
        )
        assert.strictEqual(
          injectedGlobal(html, '__AIIA_I18N_AUTO_LANG'),
          vsLang,
          `__AIIA_I18N_AUTO_LANG must always be the VS Code display language (cached=${cached})`
        )
      }
    } finally {
      provider.dispose()
    }
  })

  test('zh-TW webview HTML ships Traditional Chinese strings, not Simplified', async () => {
    const provider = makeProvider()
    try {
      await provider._preloadResources()
      provider._cachedServerLang = 'zh-TW'
      const html = renderHtml(provider)
      const zhTW = JSON.parse(
        fs.readFileSync(path.join(getExtension().extensionPath, 'locales', 'zh-TW.json'), 'utf8')
      )
      const zhCN = JSON.parse(
        fs.readFileSync(path.join(getExtension().extensionPath, 'locales', 'zh-CN.json'), 'utf8')
      )
      const tw = zhTW.ui.noContent.title
      const cn = zhCN.ui.noContent.title
      assert.notStrictEqual(tw, cn, 'fixture sanity: the two Chinese locales must differ')
      assert.ok(html.includes(`>${tw}<`), 'server-rendered no-content title must be Traditional')
      assert.ok(!html.includes(`>${cn}<`), 'Simplified title must not be rendered for zh-TW')
    } finally {
      provider.dispose()
    }
  })

  test('icon buttons expose data-i18n-aria-label so aria-labels follow runtime language switches', async () => {
    const provider = makeProvider()
    try {
      await provider._preloadResources()
      const html = renderHtml(provider)
      const ids = [
        'settingsBtn',
        'settingsBtnNoContent',
        'countdownExtendBtn',
        'countdownFreezeBtn',
        'insertCodeBtn',
        'uploadBtn',
        'submitBtn',
        'settingsClose'
      ]
      for (const id of ids) {
        const m = new RegExp(`<button[^>]*id="${id}"[^>]*>`).exec(html)
        assert.ok(m, `button #${id} not found in generated HTML`)
        assert.ok(
          /\sdata-i18n-aria-label="[^"]+"/.test(m[0]),
          `button #${id} must carry data-i18n-aria-label`
        )
      }
    } finally {
      provider.dispose()
    }
  })

  test('langDetected from the webview updates the cache and notifies the host, including auto', () => {
    const events = []
    const provider = makeProvider(lang => events.push(lang))
    try {
      provider._handleMessage({ type: 'langDetected', language: 'zh-TW' })
      assert.strictEqual(provider._cachedServerLang, 'zh-TW')
      assert.deepStrictEqual(events, ['zh-TW'])

      provider._handleMessage({ type: 'langDetected', language: 'zh-TW' })
      assert.deepStrictEqual(events, ['zh-TW'], 'an unchanged explicit language must not notify twice')

      provider._handleMessage({ type: 'langDetected', language: 'auto' })
      assert.strictEqual(
        provider._cachedServerLang,
        null,
        'auto must clear the cached explicit server language'
      )
      assert.deepStrictEqual(events, ['zh-TW', 'auto'])

      provider._handleMessage({ type: 'langDetected', language: 'en' })
      assert.strictEqual(provider._cachedServerLang, 'en')
      assert.deepStrictEqual(events, ['zh-TW', 'auto', 'en'])

      provider._handleMessage({ type: 'langDetected', language: '' })
      provider._handleMessage({ type: 'langDetected' })
      assert.deepStrictEqual(events, ['zh-TW', 'auto', 'en'], 'empty payloads are ignored')
    } finally {
      provider.dispose()
    }
  })

  test('after auto the regenerated HTML falls back to the VS Code language', async () => {
    const { normalizeUiLang } = require(distPath('lang.js'))
    const vsLang = normalizeUiLang(vscode.env.language)
    const provider = makeProvider()
    try {
      await provider._preloadResources()
      provider._handleMessage({ type: 'langDetected', language: vsLang === 'zh-TW' ? 'en' : 'zh-TW' })
      assert.notStrictEqual(htmlLangOf(renderHtml(provider)), vsLang)
      provider._handleMessage({ type: 'langDetected', language: 'auto' })
      assert.strictEqual(htmlLangOf(renderHtml(provider)), vsLang)
    } finally {
      provider.dispose()
    }
  })

  test('syncServerLanguage bypasses the cache so a running host follows server changes', async () => {
    const events = []
    const provider = makeProvider(lang => events.push(lang))
    const originalFetch = globalThis.fetch
    let next = 'zh-TW'
    globalThis.fetch = async () => ({
      ok: true,
      status: 200,
      async json() {
        return { language: next }
      }
    })
    try {
      await provider.syncServerLanguage()
      assert.strictEqual(provider._cachedServerLang, 'zh-TW')
      assert.deepStrictEqual(events, ['zh-TW'])

      next = 'en'
      await provider._prefetchServerLanguage()
      assert.strictEqual(
        provider._cachedServerLang,
        'zh-TW',
        'the passive prefetch keeps trusting its cache'
      )

      await provider.syncServerLanguage()
      assert.strictEqual(provider._cachedServerLang, 'en')
      assert.deepStrictEqual(events, ['zh-TW', 'en'])

      next = 'auto'
      await provider.syncServerLanguage()
      assert.strictEqual(provider._cachedServerLang, null)
      assert.deepStrictEqual(events, ['zh-TW', 'en', 'auto'])
    } finally {
      globalThis.fetch = originalFetch
      provider.dispose()
    }
  })

  test('a failed syncServerLanguage keeps the last known server language', async () => {
    const events = []
    const provider = makeProvider(lang => events.push(lang))
    const originalFetch = globalThis.fetch
    try {
      globalThis.fetch = async () => ({
        ok: true,
        status: 200,
        async json() {
          return { language: 'zh-TW' }
        }
      })
      await provider.syncServerLanguage()
      assert.strictEqual(provider._cachedServerLang, 'zh-TW')

      globalThis.fetch = async () => {
        throw new Error('connection refused')
      }
      await provider.syncServerLanguage()
      assert.strictEqual(provider._cachedServerLang, 'zh-TW')

      globalThis.fetch = async () => ({ ok: false, status: 503, async json() { return {} } })
      await provider.syncServerLanguage()
      assert.strictEqual(provider._cachedServerLang, 'zh-TW')
      assert.deepStrictEqual(events, ['zh-TW'])
    } finally {
      globalThis.fetch = originalFetch
      provider.dispose()
    }
  })

  test('syncServerLanguage aborts an in-flight prefetch so the older answer can never win', async () => {
    const events = []
    const provider = makeProvider(lang => events.push(lang))
    const originalFetch = globalThis.fetch
    const pending = []
    const respond = language => ({
      ok: true,
      status: 200,
      async json() {
        return { language }
      }
    })
    try {
      globalThis.fetch = (_url, options = {}) =>
        new Promise((resolve, reject) => {
          const entry = { signal: options.signal, resolve }
          pending.push(entry)
          if (options.signal) {
            options.signal.addEventListener('abort', () => {
              const err = new Error('The operation was aborted')
              err.name = 'AbortError'
              reject(err)
            })
          }
        })

      const older = provider._prefetchServerLanguage()
      assert.strictEqual(pending.length, 1)
      const newer = provider.syncServerLanguage()
      assert.strictEqual(pending.length, 2)
      assert.strictEqual(pending[0].signal.aborted, true)
      assert.strictEqual(pending[1].signal.aborted, false)

      pending[1].resolve(respond('zh-CN'))
      await newer
      await older
      assert.strictEqual(provider._cachedServerLang, 'zh-CN')
      assert.deepStrictEqual(events, ['zh-CN'])
    } finally {
      globalThis.fetch = originalFetch
      provider.dispose()
    }
  })

  test('server language prefetch reports both explicit and auto languages to the host', async () => {
    const events = []
    const provider = makeProvider(lang => events.push(lang))
    const originalFetch = globalThis.fetch
    const respond = language => async () => ({
      ok: true,
      status: 200,
      async json() {
        return { language }
      }
    })
    try {
      globalThis.fetch = respond('zh-TW')
      await provider._prefetchServerLanguage()
      assert.strictEqual(provider._cachedServerLang, 'zh-TW')
      assert.deepStrictEqual(events, ['zh-TW'])

      provider._cachedServerLang = null
      globalThis.fetch = respond('auto')
      await provider._prefetchServerLanguage()
      assert.strictEqual(provider._cachedServerLang, null)
      assert.deepStrictEqual(events, ['zh-TW', 'auto'])
    } finally {
      globalThis.fetch = originalFetch
      provider.dispose()
    }
  })
})
