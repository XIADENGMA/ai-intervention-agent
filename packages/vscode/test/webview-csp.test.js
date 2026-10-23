const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vscode = require('vscode')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

function makeProvider() {
  const ext = getExtension()
  const { WebviewProvider } = require(path.join(ext.extensionPath, 'dist', 'webview.js'))
  const output = { name: 'test-output', append() {}, appendLine() {}, clear() {}, show() {}, hide() {}, dispose() {} }
  return new WebviewProvider(vscode.Uri.file(ext.extensionPath), output, 'http://csp.test', '0.0.0')
}

function renderHtml(provider) {
  const webview = { cspSource: 'vscode-resource:', asWebviewUri: uri => uri }
  return provider._getHtmlContent(webview)
}

function startTagsWithInlineStyle(html) {
  const markup = html.replace(/<script\b[\s\S]*?<\/script>/gi, '').replace(/<!--[\s\S]*?-->/g, '')
  return markup.match(/<[a-zA-Z][^<>]*?\sstyle\s*=[^<>]*>/g) || []
}

function cspDirective(html, name) {
  const csp = /<meta http-equiv="Content-Security-Policy" content="([^"]*)">/.exec(html)
  assert.ok(csp, 'CSP meta tag not found in generated HTML')
  const directive = new RegExp(`(?:^|;)\\s*${name}\\s+([^;]*)`).exec(csp[1])
  assert.ok(directive, `CSP must declare ${name}`)
  return directive[1].trim().split(/\s+/)
}

function pageNonce(html) {
  const match = /data-csp-nonce="([^"]+)"/.exec(html)
  assert.ok(match, 'aiia-config must carry the page nonce')
  return match[1]
}

suite('Webview CSP compatibility (VSCode)', () => {
  test('style-src trusts the per-load page nonce so MathJax stylesheets apply', async () => {
    const provider = makeProvider()
    try {
      await provider._preloadResources()
      const first = renderHtml(provider)
      const second = renderHtml(provider)
      const nonce = pageNonce(first)

      assert.deepStrictEqual(cspDirective(first, 'style-src'), ['vscode-resource:', `'nonce-${nonce}'`])
      assert.deepStrictEqual(cspDirective(first, 'script-src'), [`'nonce-${nonce}'`])
      assert.ok(first.includes(`<script nonce="${nonce}"`), 'scripts must carry the same page nonce')
      assert.notStrictEqual(pageNonce(second), nonce, 'the nonce must be fresh for every render')
      assert.ok(!first.includes("'unsafe-inline'"), "the page must not contain 'unsafe-inline' anywhere")
    } finally {
      provider.dispose()
    }
  })

  test('images load only from the Web UI server, data: URLs and the panel itself, never from a remote address', async () => {
    const provider = makeProvider()
    try {
      await provider._preloadResources()
      const html = renderHtml(provider)

      assert.deepStrictEqual(cspDirective(html, 'img-src'), ['data:', 'http://csp.test', 'vscode-resource:'])
      for (const name of [
        'default-src',
        'connect-src',
        'style-src',
        'script-src',
        'img-src',
        'font-src',
        'object-src',
        'frame-src'
      ]) {
        assert.deepStrictEqual(
          cspDirective(html, name).filter(source => /^(?:https?|wss?):$|^\*$/.test(source)),
          [],
          `${name} must not name a whole network scheme or a wildcard`
        )
      }
    } finally {
      provider.dispose()
    }
  })

  test('the CSP refuses inline styles, so the template must not rely on them', async () => {
    const provider = makeProvider()
    try {
      await provider._preloadResources()
      const html = renderHtml(provider)
      const csp = /<meta http-equiv="Content-Security-Policy" content="([^"]*)">/.exec(html)
      assert.ok(csp, 'CSP meta tag not found in generated HTML')
      const styleSrc = /(?:^|;)\s*style-src\s+([^;]*)/.exec(csp[1])
      assert.ok(styleSrc, 'CSP must declare style-src')
      assert.ok(
        !styleSrc[1].includes("'unsafe-inline'"),
        "style-src must stay free of 'unsafe-inline'; inline style attributes are blocked"
      )
      assert.deepStrictEqual(
        startTagsWithInlineStyle(html),
        [],
        'generated webview HTML must not contain inline style attributes (blocked by CSP, one violation event each)'
      )
    } finally {
      provider.dispose()
    }
  })

  test('layout that used to be inline lives in webview.css and is reachable from the markup', async () => {
    const provider = makeProvider()
    try {
      await provider._preloadResources()
      const html = renderHtml(provider)
      const css = fs.readFileSync(path.join(getExtension().extensionPath, 'webview.css'), 'utf8')

      assert.ok(
        html.includes('class="settings-bark-base-url-actions"'),
        'bark action row keeps its class hook'
      )
      assert.match(
        css,
        /\.settings-bark-base-url-actions\s*\{[^}]*display:\s*flex[^}]*flex-wrap:\s*wrap[^}]*\}/,
        'bark action row layout must be defined in CSS'
      )

      assert.match(html, /<input type="number" id="feedbackCountdown"[^>]*>/)
      assert.match(
        css,
        /\.settings-field input#feedbackCountdown\s*\{[^}]*max-width:\s*100px[^}]*\}/,
        'countdown input width must be defined in CSS'
      )
    } finally {
      provider.dispose()
    }
  })
})
