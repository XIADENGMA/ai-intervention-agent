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

  test('AppleScriptNotificationProvider 应遵守 enableAppleScript 热开关', async () => {
    const ext = getExtension()
    const providersPath = path.join(ext.extensionPath, 'notification-providers.js')
    const { AppleScriptNotificationProvider } = require(providersPath)

    let enabled = false
    let shownError = ''
    const stubVscode = {
      workspace: {
        getConfiguration: () => ({
          get: (key, def) => {
            if (key === 'enableAppleScript') return enabled
            return def
          }
        })
      },
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

    // 未启用：不应调用 executor；isTest=true 时应返回提示
    const r1 = await provider.send({
      title: 't',
      message: 'm',
      metadata: { isTest: true }
    })
    assert.strictEqual(r1, false)
    assert.strictEqual(called, 0)
    assert.ok(shownError.includes('enableAppleScript'))

    // 热开关开启后：应立即生效并触发 executor
    enabled = true
    shownError = ''
    const r2 = await provider.send({
      title: 't',
      message: 'm',
      metadata: { isTest: true }
    })
    assert.strictEqual(r2, true)
    assert.strictEqual(called, 1)
  })
})

