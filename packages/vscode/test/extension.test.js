const assert = require('assert')
const fs = require('fs')
const path = require('path')

// You can import and use all API from the 'vscode' module
// as well as import your extension to test it
const vscode = require('vscode')
// const myExtension = require('../extension');

suite('Extension Test Suite', () => {
  vscode.window.showInformationMessage('Start all tests.')

  test('Sample test', () => {
    assert.strictEqual(-1, [1, 2, 3].indexOf(5))
    assert.strictEqual(-1, [1, 2, 3].indexOf(0))
  })

  test('Webview 应包含插入代码与提交护栏回归点', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')

    const webviewJsPath = path.join(ext.extensionPath, 'webview.js')
    const webviewUiPath = path.join(ext.extensionPath, 'webview-ui.js')
    const extPkgPath = path.join(ext.extensionPath, 'package.json')

    assert.ok(fs.existsSync(webviewJsPath), 'Missing webview.js in extension')
    assert.ok(fs.existsSync(webviewUiPath), 'Missing webview-ui.js in extension')
    assert.ok(fs.existsSync(extPkgPath), 'Missing package.json in extension')

    const webviewJs = fs.readFileSync(webviewJsPath, 'utf8')
    const webviewUi = fs.readFileSync(webviewUiPath, 'utf8')
    const extPkg = fs.readFileSync(extPkgPath, 'utf8')

    // 新功能回归点：插入代码按钮（剪贴板链路）
    assert.ok(webviewJs.includes('id="insertCodeBtn"'))
    assert.ok(webviewUi.includes('requestClipboardText'))
    assert.ok(webviewUi.includes('clipboardText'))

    // 安全回归点：script-src 应使用 nonce（不应放开 unsafe-inline）
    assert.ok(webviewJs.includes("script-src 'nonce-${nonce}'"))
    assert.ok(!webviewJs.includes("script-src 'nonce-${nonce}' 'unsafe-inline'"))

    // 边界回归点：自动提交与 429 应有护栏（避免重试风暴/并发提交）
    assert.ok(webviewUi.includes('autoSubmitAttempted'))
    assert.ok(webviewUi.includes('submitBackoffUntilMs'))

    // 配置回归点：应提供 logLevel 配置项（便于排查问题）
    assert.ok(extPkg.includes('ai-intervention-agent.logLevel'))
  })

  test('Logger 应避免在 LogOutputChannel 上重复前缀', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')

    const loggerPath = path.join(ext.extensionPath, 'logger.js')
    assert.ok(fs.existsSync(loggerPath), 'Missing logger.js in extension')

    const { createLogger } = require(loggerPath)

    const calls = []
    const fakeLogChannel = {
      info: msg => calls.push(['info', msg]),
      warn: msg => calls.push(['warn', msg]),
      error: msg => calls.push(['error', msg]),
      debug: msg => calls.push(['debug', msg])
    }

    const logger = createLogger(fakeLogChannel, { component: 't', getLevel: () => 'debug' })
    logger.info('hello')

    assert.strictEqual(calls.length, 1)
    assert.deepStrictEqual(calls[0], ['info', '[t] hello'])
  })

  test('Logger 在普通 OutputChannel 上应保持可读格式', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')

    const loggerPath = path.join(ext.extensionPath, 'logger.js')
    assert.ok(fs.existsSync(loggerPath), 'Missing logger.js in extension')

    const { createLogger } = require(loggerPath)

    const lines = []
    const fakeOutputChannel = {
      appendLine: line => lines.push(String(line))
    }

    const logger = createLogger(fakeOutputChannel, { component: 't', getLevel: () => 'debug' })
    logger.info('hello')

    assert.strictEqual(lines.length, 1)
    assert.ok(/\[INFO\]\s+\[t\]\s+hello/.test(lines[0]))
  })
})
