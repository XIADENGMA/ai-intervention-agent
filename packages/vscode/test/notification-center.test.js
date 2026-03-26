const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vscode = require('vscode')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

suite('Notification Center (VSCode)', () => {
  test('通知中心相关文件应随扩展发布', () => {
    const ext = getExtension()
    const files = ['notification-models.js', 'notification-center.js', 'notification-providers.js']
    for (const f of files) {
      const p = path.join(ext.extensionPath, f)
      assert.ok(fs.existsSync(p), `Missing ${f} in extension`)
    }
  })

  test('NotificationCenter 应并行分发且失败隔离', async () => {
    const ext = getExtension()
    const modelsPath = path.join(ext.extensionPath, 'notification-models.js')
    const centerPath = path.join(ext.extensionPath, 'notification-center.js')
    const { NotificationType } = require(modelsPath)
    const { NotificationCenter } = require(centerPath)

    const center = new NotificationCenter({ dedupeWindowMs: 0 })

    const called = { vscode: 0, mac: 0 }
    center.registerProvider(NotificationType.VSCODE, {
      send: async () => {
        called.vscode += 1
        return true
      }
    })
    center.registerProvider(NotificationType.MACOS_NATIVE, {
      send: async () => {
        called.mac += 1
        throw new Error('boom')
      }
    })

    const res = await center.dispatch({
      title: 'AI Intervention Agent',
      message: 'hello',
      trigger: 'immediate',
      types: [NotificationType.VSCODE, NotificationType.MACOS_NATIVE]
    })

    assert.strictEqual(res && res.skipped, false)
    assert.strictEqual(res.delivered[NotificationType.VSCODE], true)
    assert.strictEqual(res.delivered[NotificationType.MACOS_NATIVE], false)
    assert.strictEqual(called.vscode, 1)
    assert.strictEqual(called.mac, 1)
  })

  test('NotificationCenter dedupeKey 命中时应跳过分发', async () => {
    const ext = getExtension()
    const modelsPath = path.join(ext.extensionPath, 'notification-models.js')
    const centerPath = path.join(ext.extensionPath, 'notification-center.js')
    const { NotificationType } = require(modelsPath)
    const { NotificationCenter } = require(centerPath)

    const center = new NotificationCenter({ dedupeWindowMs: 60000 })

    let called = 0
    center.registerProvider(NotificationType.VSCODE, {
      send: async () => {
        called += 1
        return true
      }
    })

    const evt = {
      title: 'AI Intervention Agent',
      message: 'dedupe',
      trigger: 'immediate',
      types: [NotificationType.VSCODE],
      dedupeKey: 'k'
    }

    const r1 = await center.dispatch(evt)
    const r2 = await center.dispatch(evt)

    assert.strictEqual(r1 && r1.skipped, false)
    assert.strictEqual(r2 && r2.skipped, true)
    assert.strictEqual(called, 1)
  })
})
