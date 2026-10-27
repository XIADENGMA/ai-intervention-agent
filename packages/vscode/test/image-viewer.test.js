const assert = require('assert')
const path = require('path')
const vscode = require('vscode')

// R903: an image in the message or among the attachments opens in a viewer of its own.
//
// The viewer is part of the page the extension host renders, and what it says comes from the locale files the host
// reads. Two things can therefore only go wrong, or be seen going wrong, in the real host: a label that is still its
// key because the locale lookup missed it, and markup the page's content security policy refuses (an inline style
// attribute, an image that is fetched before anybody asked for it). The behaviour of the viewer (open, zoom, close,
// focus) runs in the panel's own script and is covered by tests/test_image_click_to_enlarge_r903.py.

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

function makeOutputChannel() {
  return {
    name: 'image-viewer-test',
    append() {},
    appendLine() {},
    clear() {},
    show() {},
    hide() {},
    dispose() {}
  }
}

const SERVER = 'http://127.0.0.1:1'

function renderHtml(lang) {
  const ext = getExtension()
  const { WebviewProvider } = require(path.join(ext.extensionPath, 'dist', 'webview.js'))
  const provider = new WebviewProvider(vscode.Uri.file(ext.extensionPath), makeOutputChannel(), SERVER, '0.0.0')
  provider._cachedServerLang = lang
  const webview = { cspSource: 'vscode-resource:', asWebviewUri: uri => uri }
  try {
    return provider._getHtmlContent(webview)
  } finally {
    provider.dispose()
  }
}

// The markup of the viewer: from its opening tag up to the first script that follows it.
function viewerBlock(html) {
  const start = html.indexOf('id="imageViewer"')
  assert.ok(start > 0, 'the viewer is missing from the markup')
  const from = html.lastIndexOf('<div', start)
  const end = html.indexOf('<script', start)
  assert.ok(end > start, 'the viewer must come before the scripts')
  return html.slice(from, end)
}

function attribute(block, id, name) {
  const tag = new RegExp(`<[a-z]+[^>]*\\bid="${id}"[^>]*>`).exec(block)
  assert.ok(tag, `#${id} is missing from the viewer`)
  const value = new RegExp(`\\s${name}="([^"]*)"`).exec(tag[0])
  assert.ok(value, `#${id} has no ${name}`)
  return value[1]
}

function labelsOf(html) {
  const block = viewerBlock(html)
  return {
    dialog: attribute(block, 'imageViewer', 'aria-label'),
    zoomLabel: attribute(block, 'imageViewerZoom', 'aria-label'),
    zoomTitle: attribute(block, 'imageViewerZoom', 'title'),
    closeLabel: attribute(block, 'imageViewerClose', 'aria-label'),
    closeTitle: attribute(block, 'imageViewerClose', 'title')
  }
}

function cspDirective(html, name) {
  const csp = /<meta http-equiv="Content-Security-Policy" content="([^"]*)">/.exec(html)
  assert.ok(csp, 'CSP meta tag not found in generated HTML')
  const directive = new RegExp(`(?:^|;)\\s*${name}\\s+([^;]*)`).exec(csp[1])
  assert.ok(directive, `CSP must declare ${name}`)
  return directive[1].trim().split(/\s+/)
}

suite('Image viewer markup (R903)', () => {
  test('every label of the viewer is the text of the locale, not the key that was looked up', () => {
    for (const lang of ['en', 'zh-CN', 'zh-TW']) {
      const labels = labelsOf(renderHtml(lang))
      for (const [where, text] of Object.entries(labels)) {
        assert.ok(text.trim().length > 0, `${lang}: ${where} is empty`)
        assert.ok(!/^ui\.image\./.test(text), `${lang}: ${where} is still a key: ${JSON.stringify(text)}`)
        assert.ok(!/\{\{|\$\{/.test(text), `${lang}: ${where} has an unfilled placeholder: ${JSON.stringify(text)}`)
      }
      assert.strictEqual(labels.zoomLabel, labels.zoomTitle, `${lang}: the zoom button must say the same thing twice`)
      assert.strictEqual(labels.closeLabel, labels.closeTitle, `${lang}: the close button must say the same thing twice`)
    }
  })

  test('the labels follow the language of the page', () => {
    const en = labelsOf(renderHtml('en'))
    const zh = labelsOf(renderHtml('zh-CN'))
    assert.ok(!/[\u4e00-\u9fff]/.test(Object.values(en).join('')), `English labels contain Chinese: ${JSON.stringify(en)}`)
    for (const [where, text] of Object.entries(zh)) {
      assert.ok(/[\u4e00-\u9fff]/.test(text), `zh-CN: ${where} is not Chinese: ${JSON.stringify(text)}`)
    }
    for (const where of Object.keys(en)) {
      assert.notStrictEqual(en[where], zh[where], `${where} reads the same in English and Chinese`)
    }
  })

  test('the viewer is a modal dialog that starts closed and holds an image nobody has asked for yet', () => {
    const block = viewerBlock(renderHtml('en'))
    const dialog = /<div[^>]*\bid="imageViewer"[^>]*>/.exec(block)[0]
    assert.ok(/\brole="dialog"/.test(dialog), 'the viewer must be a dialog')
    assert.ok(/\baria-modal="true"/.test(dialog), 'the viewer must be modal')
    assert.ok(/\bclass="[^"]*\bhidden\b[^"]*"/.test(dialog), 'the viewer must start hidden')
    const image = /<img[^>]*\bid="imageViewerImg"[^>]*>/.exec(block)
    assert.ok(image, 'the viewer needs its image')
    assert.ok(!/\bsrc=/.test(image[0]), 'the image of the viewer must not be fetched before a click')
    assert.ok(/\balt=""/.test(image[0]), 'the caption names the image, so the image itself carries no second name')
    for (const id of ['imageViewerZoom', 'imageViewerClose']) {
      const button = new RegExp(`<button[^>]*\\bid="${id}"[^>]*>`).exec(block)
      assert.ok(button, `#${id} must be a button`)
      assert.ok(/\btype="button"/.test(button[0]), `#${id} must not submit anything`)
    }
    assert.ok(/\baria-pressed="false"/.test(new RegExp(`<button[^>]*\\bid="imageViewerZoom"[^>]*>`).exec(block)[0]))
  })

  test('nothing in the viewer needs an inline style, which the page policy would refuse', () => {
    for (const lang of ['en', 'zh-CN']) {
      const block = viewerBlock(renderHtml(lang))
      assert.ok(!/\sstyle\s*=/.test(block), `${lang}: the viewer carries an inline style attribute`)
      assert.ok(!/\son[a-z]+\s*=/i.test(block), `${lang}: the viewer carries an inline event handler`)
    }
  })

  test('the policy lets the viewer show what the message shows: pictures of the server, attachments and the extension', () => {
    const sources = cspDirective(renderHtml('en'), 'img-src')
    assert.ok(sources.includes('data:'), `data: is missing from img-src: ${sources.join(' ')}`)
    assert.ok(sources.includes(SERVER), `the server is missing from img-src: ${sources.join(' ')}`)
    assert.ok(sources.includes('vscode-resource:'), `the extension is missing from img-src: ${sources.join(' ')}`)
    assert.ok(!sources.includes('*') && !sources.includes('https:'), `img-src must not open to everything: ${sources.join(' ')}`)
  })
})
