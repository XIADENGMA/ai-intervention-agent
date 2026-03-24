const assert = require('assert')
const path = require('path')
const vscode = require('vscode')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

suite('Notification Providers (VSCode)', () => {
  test('VSCodeApiNotificationProvider 默认走状态栏提示', async () => {
    const ext = getExtension()
    const providersPath = path.join(ext.extensionPath, 'notification-providers.js')
    const { VSCodeApiNotificationProvider } = require(providersPath)

    let lastText = ''
    let lastTimeout = null
    const stubVscode = {
      window: {
        setStatusBarMessage: (text, timeout) => {
          lastText = String(text)
          lastTimeout = timeout
        }
      }
    }

    const provider = new VSCodeApiNotificationProvider({ vscodeApi: stubVscode })
    const ok = await provider.send({
      title: 'AI Intervention Agent',
      message: 'hello',
      metadata: { timeoutMs: 1234 }
    })
    assert.strictEqual(ok, true)
    assert.ok(lastText.includes('hello'))
    assert.strictEqual(lastTimeout, 1234)
  })

  test('AppleScriptNotificationProvider 不应依赖 enableAppleScript（原生通知默认开启）', async () => {
    const ext = getExtension()
    const providersPath = path.join(ext.extensionPath, 'notification-providers.js')
    const { AppleScriptNotificationProvider } = require(providersPath)

    let shownError = ''
    const stubVscode = {
      window: {
        showErrorMessage: msg => {
          shownError = String(msg)
        }
      }
    }

    let called = 0
    const executor = {
      runAppleScript: async () => {
        called += 1
        return ''
      }
    }

    const provider = new AppleScriptNotificationProvider({ executor, vscodeApi: stubVscode })

    // isTest=true：允许在任意平台注入 executor 做行为验证
    const ok = await provider.send({
      title: 't',
      message: 'm',
      metadata: { isTest: true }
    })
    assert.strictEqual(ok, true)
    assert.strictEqual(called, 1)
    assert.strictEqual(shownError, '')
  })
})
