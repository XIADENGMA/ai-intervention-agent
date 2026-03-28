const assert = require('assert')
const path = require('path')
const vscode = require('vscode')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

/** 获取编译产物中的模块路径 */
function distPath(filename) {
  return path.join(getExtension().extensionPath, 'dist', filename)
}

suite('Notification Providers (VSCode)', () => {
  test('VSCodeApiNotificationProvider 默认走状态栏提示', async () => {
    const { VSCodeApiNotificationProvider } = require(distPath('notification-providers.js'))

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
    const { AppleScriptNotificationProvider } = require(distPath('notification-providers.js'))

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

  test('AppleScriptNotificationProvider 注入 bundleId 失败时应回退为不注入重试', async () => {
    const { AppleScriptNotificationProvider } = require(distPath('notification-providers.js'))

    let shownError = ''
    const stubVscode = {
      window: {
        showErrorMessage: msg => {
          shownError = String(msg)
        }
      },
      env: { appName: 'Visual Studio Code' }
    }

    const calls = []
    const executor = {
      runAppleScript: async (script, opts) => {
        calls.push({
          script: String(script || ''),
          hasInjectedBundleId: !!(opts && opts.env && opts.env.__CFBundleIdentifier),
          injectedBundleId:
            opts && opts.env && opts.env.__CFBundleIdentifier ? String(opts.env.__CFBundleIdentifier) : ''
        })
        if (opts && opts.env && opts.env.__CFBundleIdentifier) {
          const err = new Error('fail injected')
          err.code = 'APPLE_SCRIPT_FAILED'
          err.details = {
            stderr: 'injected fail',
            exitCode: 1,
            signal: '',
            injectedEnvKeys: ['__CFBundleIdentifier'],
            durationMs: 1
          }
          throw err
        }
        return ''
      }
    }

    const provider = new AppleScriptNotificationProvider({ executor, vscodeApi: stubVscode })
    // 用 monkey patch 保证跨平台也能覆盖注入逻辑
    provider._resolveHostBundleId = async () => 'com.example.host'

    const ok = await provider.send({
      title: 't',
      message: 'm',
      metadata: { isTest: true, diagnostic: true }
    })
    assert.strictEqual(ok, true)
    assert.strictEqual(shownError, '')
    assert.strictEqual(calls.length, 2)
    assert.strictEqual(calls[0].hasInjectedBundleId, true)
    assert.strictEqual(calls[0].injectedBundleId, 'com.example.host')
    assert.strictEqual(calls[1].hasInjectedBundleId, false)
  })

  test('AppleScriptNotificationProvider 失败应保存诊断信息，且 diagnostic 模式不弹窗', async () => {
    const { AppleScriptNotificationProvider } = require(distPath('notification-providers.js'))

    let shownError = ''
    const stubVscode = {
      window: {
        showErrorMessage: msg => {
          shownError = String(msg)
        }
      },
      env: { appName: 'Visual Studio Code' }
    }

    const executor = {
      runAppleScript: async (_script, opts) => {
        const isInjected = !!(opts && opts.env && opts.env.__CFBundleIdentifier)
        const err = new Error(isInjected ? 'fail primary' : 'fail fallback')
        err.code = 'APPLE_SCRIPT_FAILED'
        err.details = {
          stderr: isInjected ? 'stderr_primary' : 'stderr_fallback',
          exitCode: 1,
          signal: '',
          injectedEnvKeys: isInjected ? ['__CFBundleIdentifier'] : [],
          durationMs: 2
        }
        throw err
      }
    }

    const provider = new AppleScriptNotificationProvider({ executor, vscodeApi: stubVscode })
    provider._resolveHostBundleId = async () => 'com.example.host'

    const ok = await provider.send({
      title: 't',
      message: 'm',
      metadata: { isTest: true, diagnostic: true }
    })
    assert.strictEqual(ok, false)
    // diagnostic 模式：UI 错误提示应由 extension.js 统一展示，这里不应弹窗
    assert.strictEqual(shownError, '')

    const diag = provider.getLastDiagnostic()
    assert.ok(diag && typeof diag === 'object', 'should store last diagnostic')
    assert.ok(diag.primary && typeof diag.primary === 'object', 'should keep primary attempt info')
    assert.ok(diag.fallback && typeof diag.fallback === 'object', 'should keep fallback attempt info')
    assert.ok(String(diag.primary.stderrPreview || '').includes('stderr_primary'))
    assert.ok(String(diag.fallback.stderrPreview || '').includes('stderr_fallback'))
  })
})
