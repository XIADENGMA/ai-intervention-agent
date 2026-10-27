const assert = require('assert')
const path = require('path')
const vscode = require('vscode')

// R899: the settings page is organised around what the user does there.
//
// One part of it depends on the machine the extension host runs on: the "macOS Native Notification" row.
// A macOS banner can only be shown by a macOS host, so on Windows, Linux and remote hosts the row must not be
// offered at all (the setting itself stays untouched - it is shared with the Web UI and other machines).
// The panel is rendered by the host, so this is checked here, against the real extension host; the rest of the
// page (order, labels, muting) is covered by tests/test_vscode_settings_structure_r899.py.

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
    name: 'settings-structure-test',
    append() {},
    appendLine() {},
    clear() {},
    show() {},
    hide() {},
    dispose() {}
  }
}

function renderHtmlOn(platform) {
  const ext = getExtension()
  const { WebviewProvider } = require(dist('webview.js'))
  const provider = new WebviewProvider(vscode.Uri.file(ext.extensionPath), makeOutputChannel(), 'http://127.0.0.1:1', '0.0.0')
  provider._cachedServerLang = 'en'
  const webview = { cspSource: 'vscode-resource:', asWebviewUri: uri => uri }
  const original = Object.getOwnPropertyDescriptor(process, 'platform')
  Object.defineProperty(process, 'platform', { value: platform, configurable: true })
  try {
    return provider._getHtmlContent(webview)
  } finally {
    Object.defineProperty(process, 'platform', original)
    provider.dispose()
  }
}

function macosRowAttributes(html) {
  const match = /<label class="settings-toggle" id="settingsMacosRow"([^>]*)>/.exec(html)
  assert.ok(match, 'the macOS row is missing from the markup')
  return match[1]
}

suite('Settings panel markup (R899)', () => {
  test('the macOS row is rendered visible on a macOS host', () => {
    const attrs = macosRowAttributes(renderHtmlOn('darwin'))
    assert.ok(!/\bhidden\b/.test(attrs), `unexpected hidden attribute: ${JSON.stringify(attrs)}`)
  })

  test('the macOS row is rendered hidden on every other host', () => {
    for (const platform of ['linux', 'win32', 'freebsd', 'openbsd', 'aix', 'sunos']) {
      const attrs = macosRowAttributes(renderHtmlOn(platform))
      assert.ok(/\bhidden\b/.test(attrs), `${platform}: the row must be hidden, got ${JSON.stringify(attrs)}`)
    }
  })

  test('the platform the panel script is told is the one the row was decided with', () => {
    for (const platform of ['darwin', 'linux', 'win32']) {
      const html = renderHtmlOn(platform)
      assert.ok(html.includes(`data-host-platform="${platform}"`), `${platform}: data-host-platform missing`)
    }
  })

  test('the panel is a labelled dialog with the title the locale provides', () => {
    const html = renderHtmlOn('darwin')
    assert.ok(/id="settingsPanel" role="dialog" aria-modal="true" aria-labelledby="settingsTitle"/.test(html))
    assert.ok(/id="settingsTitle" data-i18n="settings\.title">[^<]+</.test(html))
    assert.ok(!/Notification Settings/.test(html.slice(html.indexOf('id="settingsOverlay"'))), 'the old title is gone')
  })
})
