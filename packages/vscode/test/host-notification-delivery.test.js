const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const vscode = require('vscode')

// R898: "Enable Notifications" on its own must give a notification the user can see.
//
// The host is the only place that knows whether the macOS banner can be shown at all, so it decides what the
// in-editor part of a new-task / test notification looks like:
//   banner will be shown  -> the in-editor part is a quiet status-bar message (as before)
//   no banner             -> the in-editor part is a real VS Code notification (toast)

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

function dist(name) {
  return path.join(getExtension().extensionPath, 'dist', name)
}

function makeOutputChannel() {
  return {
    name: 'notification-delivery-test',
    append() {},
    appendLine() {},
    clear() {},
    show() {},
    hide() {},
    dispose() {}
  }
}

function makeProvider() {
  const ext = getExtension()
  const { WebviewProvider } = require(dist('webview.js'))
  const provider = new WebviewProvider(vscode.Uri.file(ext.extensionPath), makeOutputChannel(), 'http://127.0.0.1:1', '0.0.0')
  provider._cachedServerLang = 'en'
  return provider
}

/** A notification centre that only records what reaches it. */
function recordingCenter() {
  const seen = []
  return {
    seen,
    async dispatch(event) {
      seen.push(event)
      return { event, delivered: {}, skipped: false }
    }
  }
}

/** `_dispatchNotificationEvent` hands the event over in a microtask. */
function settle() {
  return new Promise(resolve => setImmediate(resolve))
}

async function newTask({ enabled = true, native, macos }) {
  const provider = makeProvider()
  provider._fetchNotificationConfig = async () => ({ enabled, macosNativeEnabled: native })
  provider._nativeNotificationsAvailable = () => macos
  const center = recordingCenter()
  provider._notificationCenter = center
  await provider.dispatchNewTaskNotification([{ id: 't-1', prompt: 'Review the diff' }])
  await settle()
  provider.dispose()
  return center.seen
}

suite('Host notification delivery (R898)', () => {
  test('notifications on, macOS banner off: a VS Code toast, no banner', async () => {
    const seen = await newTask({ native: false, macos: true })
    assert.strictEqual(seen.length, 1)
    assert.deepStrictEqual(seen[0].types, ['vscode'])
    assert.strictEqual(seen[0].metadata.presentation, 'toast')
    assert.strictEqual(seen[0].message, 'Review the diff')
  })

  test('notifications on, macOS banner on, host on macOS: banner plus the quiet status-bar message', async () => {
    const seen = await newTask({ native: true, macos: true })
    assert.strictEqual(seen.length, 1)
    assert.deepStrictEqual(seen[0].types, ['vscode', 'macos_native'])
    assert.strictEqual(seen[0].metadata.presentation, 'statusBar')
  })

  test('macOS banner switched on but the host is not macOS (Windows, Linux, a remote host): toast, banner dropped', async () => {
    const seen = await newTask({ native: true, macos: false })
    assert.strictEqual(seen.length, 1)
    assert.deepStrictEqual(seen[0].types, ['vscode'])
    assert.strictEqual(seen[0].metadata.presentation, 'toast')
  })

  test('macOS banner off on a host that is not macOS: toast', async () => {
    const seen = await newTask({ native: false, macos: false })
    assert.deepStrictEqual(seen[0].types, ['vscode'])
    assert.strictEqual(seen[0].metadata.presentation, 'toast')
  })

  test('notifications off: nothing is dispatched, whatever the other switch says', async () => {
    for (const native of [true, false]) {
      for (const macos of [true, false]) {
        const seen = await newTask({ enabled: false, native, macos })
        assert.strictEqual(seen.length, 0, `enabled=false native=${native} macos=${macos}`)
      }
    }
  })

  test('the rest of the event is untouched by the decision', async () => {
    const seen = await newTask({ native: false, macos: true })
    const md = seen[0].metadata
    assert.strictEqual(md.kind, 'new_tasks')
    assert.deepStrictEqual(md.taskIds, ['t-1'])
    assert.strictEqual(md.severity, 'info')
    assert.strictEqual(md.isTest, false)
    assert.strictEqual(seen[0].dedupeKey, 'new_tasks:t-1')
    assert.strictEqual(seen[0].title, 'AI Intervention Agent')
  })

  test('an event that names its presentation is left alone (status messages stay in the status bar)', async () => {
    const provider = makeProvider()
    provider._nativeNotificationsAvailable = () => false
    const center = recordingCenter()
    provider._notificationCenter = center
    provider._dispatchNotificationEvent({
      title: 'AI Intervention Agent',
      message: 'Copied',
      types: ['vscode', 'macos_native'],
      metadata: { presentation: 'statusBar', severity: 'info', timeoutMs: 3000 }
    })
    await settle()
    provider.dispose()
    assert.strictEqual(center.seen.length, 1)
    assert.deepStrictEqual(center.seen[0].types, ['vscode', 'macos_native'])
    assert.strictEqual(center.seen[0].metadata.presentation, 'statusBar')
  })

  test('a test notification from the settings page is decided the same way', async () => {
    const provider = makeProvider()
    const center = recordingCenter()
    provider._notificationCenter = center
    const testEvent = types => ({
      title: 'AI Intervention Agent Test',
      message: 'This is a test notification.',
      types,
      metadata: { isTest: true, diagnostic: true, kind: 'test_notification', presentation: 'auto', severity: 'info', timeoutMs: 3000 },
      dedupeKey: 'test:' + types.join('+')
    })

    provider._nativeNotificationsAvailable = () => false
    provider._dispatchNotificationEvent(testEvent(['vscode', 'macos_native']))
    provider._dispatchNotificationEvent(testEvent(['vscode']))
    provider._nativeNotificationsAvailable = () => true
    provider._dispatchNotificationEvent(testEvent(['vscode', 'macos_native']))
    await settle()
    provider.dispose()

    assert.deepStrictEqual(
      center.seen.map(e => [e.types.join('+'), e.metadata.presentation, e.metadata.isTest, e.metadata.diagnostic]),
      [
        ['vscode', 'toast', true, true],
        ['vscode', 'toast', true, true],
        ['vscode+macos_native', 'statusBar', true, true]
      ]
    )
  })

  test('a bad event never throws out of the dispatcher', () => {
    const provider = makeProvider()
    provider._notificationCenter = recordingCenter()
    for (const bad of [undefined, null, {}, { metadata: null }, { metadata: { presentation: 'auto' }, types: 'vscode' }]) {
      assert.doesNotThrow(() => provider._dispatchNotificationEvent(bad))
    }
    provider.dispose()
  })

  test('through the real centre and provider: the toast is a VS Code information message, the status message is not', async () => {
    const { NotificationCenter } = require(dist('notification-center.js'))
    const { VSCodeApiNotificationProvider } = require(dist('notification-providers.js'))

    const calls = []
    const stubVscode = {
      window: {
        showInformationMessage: text => calls.push(['toast', String(text)]),
        setStatusBarMessage: (text, ms) => calls.push(['status', String(text), ms])
      }
    }
    const center = new NotificationCenter({ dedupeWindowMs: 0 })
    center.registerProvider('vscode', new VSCodeApiNotificationProvider({ vscodeApi: stubVscode }))

    const provider = makeProvider()
    provider._notificationCenter = center
    provider._fetchNotificationConfig = async () => ({ enabled: true, macosNativeEnabled: false })
    provider._nativeNotificationsAvailable = () => true
    await provider.dispatchNewTaskNotification([{ id: 't-1', prompt: 'Review the diff' }])
    await settle()
    assert.deepStrictEqual(calls, [['toast', 'AI Intervention Agent: Review the diff']])

    calls.length = 0
    provider._dispatchNotificationEvent({
      title: 'AI Intervention Agent',
      message: 'Copied',
      types: ['vscode'],
      metadata: { presentation: 'statusBar', timeoutMs: 3000 }
    })
    await settle()
    provider.dispose()
    assert.deepStrictEqual(calls, [['status', '$(info) Copied', 3000]])
  })

  test('with the banner on and no macOS host nothing asks the platform-specific provider to run', async () => {
    const { NotificationCenter } = require(dist('notification-center.js'))
    const provider = makeProvider()
    const center = new NotificationCenter({ dedupeWindowMs: 0 })
    let nativeCalls = 0
    center.registerProvider('macos_native', {
      send() {
        nativeCalls += 1
        return true
      }
    })
    center.registerProvider('vscode', { send: () => true })
    provider._notificationCenter = center
    provider._fetchNotificationConfig = async () => ({ enabled: true, macosNativeEnabled: true })

    provider._nativeNotificationsAvailable = () => false
    await provider.dispatchNewTaskNotification([{ id: 't-1', prompt: 'x' }])
    await settle()
    assert.strictEqual(nativeCalls, 0)

    provider._nativeNotificationsAvailable = () => true
    await provider.dispatchNewTaskNotification([{ id: 't-2', prompt: 'x' }])
    await settle()
    assert.strictEqual(nativeCalls, 1)
    provider.dispose()
  })
})

suite('Host notification config cache (R898)', () => {
  const CONFIG_URL = 'http://127.0.0.1:1/api/get-notification-config'

  function stubFetch(responses) {
    const original = globalThis.fetch
    const urls = []
    globalThis.fetch = async url => {
      urls.push(String(url))
      const config = responses.shift()
      return { ok: true, status: 200, async json() { return { status: 'success', config } } }
    }
    return { urls, restore: () => (globalThis.fetch = original) }
  }

  test('a settings save in the panel makes the next notification use the new settings', async () => {
    const provider = makeProvider()
    const fetchStub = stubFetch([
      { enabled: false, macos_native_enabled: false },
      { enabled: true, macos_native_enabled: false }
    ])
    try {
      assert.deepStrictEqual(await provider._fetchNotificationConfig(), { enabled: false, macosNativeEnabled: false })
      assert.deepStrictEqual(await provider._fetchNotificationConfig(), { enabled: false, macosNativeEnabled: false })
      assert.strictEqual(fetchStub.urls.length, 1, 'inside the cache window nothing is fetched again')

      provider._handleMessage({ type: 'notificationSettingsChanged' })

      assert.deepStrictEqual(await provider._fetchNotificationConfig(), { enabled: true, macosNativeEnabled: false })
      assert.deepStrictEqual(fetchStub.urls, [CONFIG_URL, CONFIG_URL])
    } finally {
      fetchStub.restore()
      provider.dispose()
    }
  })

  test('the cache window is short, so a change made elsewhere is picked up within seconds', async () => {
    const provider = makeProvider()
    const fetchStub = stubFetch([
      { enabled: false, macos_native_enabled: false },
      { enabled: true, macos_native_enabled: false }
    ])
    try {
      await provider._fetchNotificationConfig()
      provider._notificationConfigFetchedAt = Date.now() - 4000
      await provider._fetchNotificationConfig()
      assert.strictEqual(fetchStub.urls.length, 1, 'still inside the window at 4 s')
      provider._notificationConfigFetchedAt = Date.now() - 6000
      assert.deepStrictEqual(await provider._fetchNotificationConfig(), { enabled: true, macosNativeEnabled: false })
      assert.strictEqual(fetchStub.urls.length, 2, 'past the window at 6 s')
    } finally {
      fetchStub.restore()
      provider.dispose()
    }
  })
})

suite('Webview events meet the host decision (R898)', () => {
  function runNotifyCore(settings) {
    const ext = getExtension()
    const posted = []
    const sandbox = {
      acquireVsCodeApi: () => ({ postMessage: m => posted.push(m) }),
      document: { getElementById: () => null },
      fetch: async () => ({ ok: true, status: 200, async json() { return { status: 'success', config: settings } } }),
      AbortController,
      setTimeout,
      clearTimeout,
      console
    }
    sandbox.globalThis = sandbox
    sandbox.window = sandbox
    vm.runInNewContext(fs.readFileSync(path.join(ext.extensionPath, 'webview-notify-core.js'), 'utf8'), sandbox)
    // the sandbox is another realm: a plain copy compares equal to a plain literal
    return { core: sandbox.AIIAWebviewNotifyCore, posts: () => JSON.parse(JSON.stringify(posted)) }
  }

  test('what the panel sends for a new task reaches the user as a toast when the banner is off', async () => {
    const { core, posts } = runNotifyCore({ enabled: true, macos_native_enabled: false })
    core.setCachedNotificationSettings({ enabled: true, macosNativeEnabled: false })
    await core.showNewTaskNotification([{ id: 't-7', prompt: 'Ship it' }])
    const notify = posts().filter(m => m.type === 'notify')
    assert.strictEqual(notify.length, 1)
    assert.strictEqual(notify[0].event.metadata.presentation, 'auto')
    assert.deepStrictEqual(notify[0].event.types, ['vscode'])

    const provider = makeProvider()
    const center = recordingCenter()
    provider._notificationCenter = center
    provider._nativeNotificationsAvailable = () => true
    provider._handleMessage(notify[0])
    await settle()
    provider.dispose()
    assert.strictEqual(center.seen.length, 1)
    assert.strictEqual(center.seen[0].metadata.presentation, 'toast')
    assert.deepStrictEqual(center.seen[0].types, ['vscode'])
  })

  test('with the banner on (and a macOS host) the panel event keeps the status-bar message and the banner', async () => {
    const { core, posts } = runNotifyCore({ enabled: true, macos_native_enabled: true })
    core.setCachedNotificationSettings({ enabled: true, macosNativeEnabled: true })
    await core.showNewTaskNotification([{ id: 't-8', prompt: 'Ship it' }])
    const event = posts().find(m => m.type === 'notify').event
    assert.deepStrictEqual(event.types, ['vscode', 'macos_native'])

    const provider = makeProvider()
    const center = recordingCenter()
    provider._notificationCenter = center
    provider._nativeNotificationsAvailable = () => true
    provider._handleMessage({ type: 'notify', event })
    await settle()
    provider.dispose()
    assert.strictEqual(center.seen[0].metadata.presentation, 'statusBar')
    assert.deepStrictEqual(center.seen[0].types, ['vscode', 'macos_native'])
  })

  test('with notifications off the panel sends nothing at all', async () => {
    const { core, posts } = runNotifyCore({ enabled: false, macos_native_enabled: true })
    core.setCachedNotificationSettings({ enabled: false, macosNativeEnabled: true })
    await core.showNewTaskNotification([{ id: 't-9', prompt: 'Ship it' }])
    assert.strictEqual(posts().filter(m => m.type === 'notify').length, 0)
  })
})
