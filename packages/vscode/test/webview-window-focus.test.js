const assert = require('assert')
const path = require('path')
const vscode = require('vscode')

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

function makeProvider() {
  const ext = getExtension()
  const { WebviewProvider } = require(path.join(ext.extensionPath, 'dist', 'webview.js'))
  const output = {
    name: 'window-focus-test',
    append() {},
    appendLine() {},
    clear() {},
    show() {},
    hide() {},
    dispose() {}
  }
  return new WebviewProvider(vscode.Uri.file(ext.extensionPath), output, 'http://127.0.0.1:1', '0.0.0')
}

// A view whose page records what it is sent and can report ready, be hidden and be shown again.
function makePage(visible) {
  const handlers = { message: [], visibility: [] }
  const posted = []
  const view = {
    visible,
    webview: {
      options: {},
      html: '',
      cspSource: 'vscode-resource:',
      asWebviewUri: uri => uri,
      postMessage: async message => {
        posted.push(message)
        return true
      },
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
    posted,
    reportReady() {
      handlers.message.forEach(callback => callback({ type: 'ready' }))
    },
    setVisible(value) {
      view.visible = value
      handlers.visibility.forEach(callback => callback())
    }
  }
}

const focusMessages = posted => posted.filter(message => message && message.type === 'window-focus')
const windowIsInFront = () => vscode.window.state.focused !== false

async function withPage(visible, body) {
  const provider = makeProvider()
  try {
    const page = makePage(visible)
    await provider.resolveWebviewView(page.view)
    return await body(provider, page)
  } finally {
    provider.dispose()
  }
}

suite('Webview window focus (VSCode)', () => {
  test('a window state change reaches the page as it happens, both ways', async () => {
    await withPage(true, async (provider, page) => {
      page.reportReady()
      const before = focusMessages(page.posted).length

      await provider.onWindowFocusChanged(false)
      await provider.onWindowFocusChanged(true)

      assert.deepStrictEqual(focusMessages(page.posted).slice(before), [
        { type: 'window-focus', focused: false },
        { type: 'window-focus', focused: true }
      ])
    })
  })

  test('a page that has not reported ready hears nothing, then hears how things stand when it does', async () => {
    await withPage(true, async (provider, page) => {
      await provider.onWindowFocusChanged(false)
      await sleep(50)
      assert.deepStrictEqual(focusMessages(page.posted), [], 'nothing is posted to a page that cannot receive it yet')

      page.reportReady()
      await sleep(50)
      const heard = focusMessages(page.posted)

      assert.ok(heard.length >= 2, `the queued state and the state now were expected, got ${JSON.stringify(heard)}`)
      assert.deepStrictEqual(heard[0], { type: 'window-focus', focused: false }, 'the queued message comes first')
      assert.deepStrictEqual(
        heard[heard.length - 1],
        { type: 'window-focus', focused: windowIsInFront() },
        'the state of the window right now comes last, so it is the one that stays'
      )
    })
  })

  test('a panel that is shown again is told, not left with what it heard before it was hidden', async () => {
    await withPage(true, async (provider, page) => {
      page.reportReady()
      await provider.onWindowFocusChanged(false)
      page.setVisible(false)
      const before = focusMessages(page.posted).length

      page.setVisible(true)

      const heard = focusMessages(page.posted).slice(before)
      assert.deepStrictEqual(heard, [{ type: 'window-focus', focused: windowIsInFront() }])
    })
  })

  test('hiding the panel says nothing about the window', async () => {
    await withPage(true, async (provider, page) => {
      page.reportReady()
      const before = focusMessages(page.posted).length

      page.setVisible(false)

      assert.strictEqual(focusMessages(page.posted).length, before)
    })
  })
})
