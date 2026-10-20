const assert = require('assert')
const path = require('path')
const vscode = require('vscode')

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const PAST_READY_TIMEOUT_MS = 3500

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

function makeProvider() {
  const ext = getExtension()
  const { WebviewProvider } = require(path.join(ext.extensionPath, 'dist', 'webview.js'))
  const lines = []
  const output = {
    name: 'ready-timeout-test',
    append(text) {
      lines.push(String(text))
    },
    appendLine(line) {
      lines.push(String(line))
    },
    clear() {},
    show() {},
    hide() {},
    dispose() {}
  }
  const provider = new WebviewProvider(vscode.Uri.file(ext.extensionPath), output, 'http://127.0.0.1:1', '0.0.0')
  return { provider, lines }
}

function makePage(visible) {
  const handlers = { message: [], visibility: [] }
  const view = {
    visible,
    webview: {
      options: {},
      html: '',
      cspSource: 'vscode-resource:',
      asWebviewUri: uri => uri,
      postMessage: async () => true,
      onDidReceiveMessage(callback, _thisArg, disposables) {
        handlers.message.push(callback)
        const disposable = { dispose() {} }
        if (disposables) disposables.push(disposable)
        return disposable
      }
    },
    onDidChangeVisibility(callback) {
      handlers.visibility.push(callback)
      return { dispose() {} }
    },
    onDidDispose() {
      return { dispose() {} }
    }
  }
  return {
    view,
    reportReady() {
      handlers.message.forEach(callback => callback({ type: 'ready' }))
    },
    setVisible(value) {
      view.visible = value
      handlers.visibility.forEach(callback => callback())
    }
  }
}

function warnings(lines) {
  return lines.filter(line => line.includes('[WARN]'))
}

async function pageThatReportsReady() {
  const { provider, lines } = makeProvider()
  try {
    const page = makePage(true)
    await provider.resolveWebviewView(page.view)
    page.reportReady()
    await sleep(PAST_READY_TIMEOUT_MS)
    return { lines }
  } finally {
    provider.dispose()
  }
}

async function pageThatNeverReportsReady() {
  const { provider, lines } = makeProvider()
  try {
    await provider.resolveWebviewView(makePage(true).view)
    await sleep(PAST_READY_TIMEOUT_MS)
    return { lines }
  } finally {
    provider.dispose()
  }
}

async function reloadWhileHidden({ reportReadyWhenShown }) {
  const { provider, lines } = makeProvider()
  try {
    const page = makePage(true)
    await provider.resolveWebviewView(page.view)
    page.reportReady()
    page.setVisible(false)
    provider.updateServerUrl('http://127.0.0.1:2')
    await sleep(PAST_READY_TIMEOUT_MS)
    const whileHidden = lines.slice()
    page.setVisible(true)
    if (reportReadyWhenShown) page.reportReady()
    await sleep(PAST_READY_TIMEOUT_MS)
    return { whileHidden, afterShown: lines.slice(whileHidden.length) }
  } finally {
    provider.dispose()
  }
}

async function shownBeforeTheFirstWaitEnds() {
  const { provider, lines } = makeProvider()
  try {
    const page = makePage(true)
    await provider.resolveWebviewView(page.view)
    page.reportReady()
    page.setVisible(false)
    provider.updateServerUrl('http://127.0.0.1:2')
    await sleep(600)
    page.setVisible(true)
    await sleep(PAST_READY_TIMEOUT_MS)
    return { lines }
  } finally {
    provider.dispose()
  }
}

async function reloadWhileVisible() {
  const { provider, lines } = makeProvider()
  try {
    const page = makePage(true)
    await provider.resolveWebviewView(page.view)
    page.reportReady()
    provider.updateServerUrl('http://127.0.0.1:2')
    await sleep(PAST_READY_TIMEOUT_MS)
    return { lines }
  } finally {
    provider.dispose()
  }
}

async function hiddenAndShownAgain() {
  const { provider, lines } = makeProvider()
  try {
    const page = makePage(true)
    await provider.resolveWebviewView(page.view)
    page.reportReady()
    page.setVisible(false)
    page.setVisible(true)
    await sleep(PAST_READY_TIMEOUT_MS)
    return { lines }
  } finally {
    provider.dispose()
  }
}

suite('Webview ready timeout (VSCode)', () => {
  let ready
  let neverReady
  let hiddenNeverReady
  let hiddenThenReady
  let shownEarly
  let hiddenAndShown
  let visibleReload

  suiteSetup(async function () {
    this.timeout(30000)
    ;[ready, neverReady, hiddenNeverReady, hiddenThenReady, shownEarly, hiddenAndShown, visibleReload] =
      await Promise.all([
        pageThatReportsReady(),
        pageThatNeverReportsReady(),
        reloadWhileHidden({ reportReadyWhenShown: false }),
        reloadWhileHidden({ reportReadyWhenShown: true }),
        shownBeforeTheFirstWaitEnds(),
        hiddenAndShownAgain(),
        reloadWhileVisible()
      ])
  })

  test('a page that reports ready leaves no warning, not even about the HTML it was given', () => {
    assert.ok(
      ready.lines.some(line => line.includes('event=webview.ready')),
      `the ready message must reach the host; log was:\n${ready.lines.join('\n')}`
    )
    assert.deepStrictEqual(warnings(ready.lines), [])
  })

  test('a visible page that never reports ready is reported once', () => {
    const found = warnings(neverReady.lines)
    assert.strictEqual(found.length, 1, `expected one warning, got:\n${found.join('\n')}`)
    assert.ok(found[0].includes('event=webview.ready_timeout'), found[0])
    assert.ok(found[0].includes('webviewReady=false'), found[0])
    assert.ok(!found[0].includes('reason='), found[0])
  })

  test('a reload while the view is visible is reported once when the page stays silent', () => {
    const found = warnings(visibleReload.lines)
    assert.strictEqual(found.length, 1, `expected one warning, got:\n${found.join('\n')}`)
    assert.ok(found[0].includes('event=webview.ready_timeout'), found[0])
    assert.ok(found[0].includes('reason=serverUrl_changed'), found[0])
  })

  test('a reload while the view is hidden is not reported: a hidden webview loads nothing', () => {
    assert.deepStrictEqual(warnings(hiddenNeverReady.whileHidden), [])
    assert.deepStrictEqual(warnings(hiddenThenReady.whileHidden), [])
  })

  test('the wait starts again when the hidden view is shown and the page stays silent', () => {
    const found = warnings(hiddenNeverReady.afterShown)
    assert.strictEqual(found.length, 1, `expected one warning, got:\n${found.join('\n')}`)
    assert.ok(found[0].includes('event=webview.ready_timeout'), found[0])
    assert.ok(found[0].includes('reason=shown'), found[0])
  })

  test('a hidden view that loads after it is shown and reports ready raises nothing', () => {
    assert.deepStrictEqual(warnings(hiddenThenReady.afterShown), [])
    assert.ok(
      hiddenThenReady.afterShown.some(line => line.includes('event=webview.ready')),
      `the ready message after showing must reach the host; log was:\n${hiddenThenReady.afterShown.join('\n')}`
    )
  })

  test('showing the view before the first wait ends replaces that wait instead of adding one', () => {
    const found = warnings(shownEarly.lines)
    assert.strictEqual(found.length, 1, `expected one warning, got:\n${found.join('\n')}`)
    assert.ok(found[0].includes('reason=shown'), found[0])
  })

  test('hiding and showing a view whose page is alive starts no wait', () => {
    assert.deepStrictEqual(warnings(hiddenAndShown.lines), [])
  })
})
