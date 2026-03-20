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
    const webviewHelpersPath = path.join(ext.extensionPath, 'webview-helpers.js')
    const webviewUiPath = path.join(ext.extensionPath, 'webview-ui.js')
    const extPkgPath = path.join(ext.extensionPath, 'package.json')

    assert.ok(fs.existsSync(webviewJsPath), 'Missing webview.js in extension')
    assert.ok(fs.existsSync(webviewHelpersPath), 'Missing webview-helpers.js in extension')
    assert.ok(fs.existsSync(webviewUiPath), 'Missing webview-ui.js in extension')
    assert.ok(fs.existsSync(extPkgPath), 'Missing package.json in extension')

    const webviewJs = fs.readFileSync(webviewJsPath, 'utf8')
    const webviewUi = fs.readFileSync(webviewUiPath, 'utf8')
    const extPkg = fs.readFileSync(extPkgPath, 'utf8')

    // 新功能回归点：插入代码按钮（剪贴板链路）
    assert.ok(webviewJs.includes('id="insertCodeBtn"'))
    assert.ok(webviewJs.includes('webview-helpers.js'))
    assert.ok(webviewUi.includes('requestClipboardText'))
    assert.ok(webviewUi.includes('clipboardText'))
    assert.ok(webviewJs.includes('id="notifyMacOSNativeEnabled"'))
    assert.ok(webviewJs.includes('id="settingsTestNativeBtn"'))
    // 阶段 C：统一 NotificationEvent 分发（Webview → Extension）
    assert.ok(webviewUi.includes("type: 'notify'"))
    assert.ok(webviewUi.includes('macos_native'))

    // 安全回归点：script-src 应使用 nonce（不应放开 unsafe-inline）
    assert.ok(webviewJs.includes("script-src 'nonce-${nonce}'"))
    assert.ok(!webviewJs.includes("script-src 'nonce-${nonce}' 'unsafe-inline'"))

    // 边界回归点：自动提交与 429 应有护栏（避免重试风暴/并发提交）
    assert.ok(webviewUi.includes('autoSubmitAttempted'))
    assert.ok(webviewUi.includes('submitBackoffUntilMs'))
    assert.ok(/async function autoSubmit\(\)[\s\S]*fetchFeedbackPrompts\(/.test(webviewUi))
    assert.ok(webviewUi.includes('collectImageFilesFromClipboard'))
    assert.ok(webviewUi.includes('applyHostThemeState'))
    assert.ok(webviewUi.includes("formData.append('task_id', taskIdToSubmit)"))
    assert.ok(webviewUi.includes('buildMarkdownCodeFence'))
    assert.ok(webviewUi.includes('const codeBlockBody = buildMarkdownCodeFence(code, lang)'))
    assert.ok(!webviewUi.includes('const trimmed = raw.trim();'))

    // 配置回归点：应提供 logLevel 配置项（便于排查问题）
    assert.ok(extPkg.includes('ai-intervention-agent.logLevel'))
    assert.ok(extPkg.includes('ai-intervention-agent.enableAppleScript'))
    assert.ok(extPkg.includes('http://localhost:8080'))
    assert.ok(webviewJs.includes('http://localhost:8080'))
    assert.ok(webviewJs.includes('overflow-wrap: anywhere;'))
    assert.ok(webviewJs.includes('white-space: pre-wrap;'))
  })

  test('Webview helpers 应覆盖 macOS / 剪贴板 / 主题同步兼容逻辑', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')

    const helpersPath = path.join(ext.extensionPath, 'webview-helpers.js')
    const helpers = require(helpersPath)

    assert.strictEqual(helpers.detectMacLikePlatform({ platform: 'MacIntel' }), true)
    assert.strictEqual(
      helpers.detectMacLikePlatform({ userAgentData: { platform: 'macOS' } }),
      true
    )
    assert.strictEqual(helpers.detectMacLikePlatform({ platform: 'Linux x86_64' }), false)

    const clipboardFromFilesOnly = {
      items: [],
      files: [
        { name: 'clip.png', type: 'image/png', size: 12, lastModified: 1 },
        { name: 'note.txt', type: 'text/plain', size: 3, lastModified: 2 }
      ]
    }
    const filesOnly = helpers.collectImageFilesFromClipboard(clipboardFromFilesOnly)
    assert.strictEqual(filesOnly.length, 1)
    assert.strictEqual(filesOnly[0].name, 'clip.png')

    const sharedImage = { name: 'dup.png', type: 'image/png', size: 99, lastModified: 9 }
    const clipboardWithDuplicateSources = {
      items: [
        {
          kind: 'file',
          type: 'image/png',
          getAsFile: () => sharedImage
        }
      ],
      files: [sharedImage]
    }
    const deduped = helpers.collectImageFilesFromClipboard(clipboardWithDuplicateSources)
    assert.strictEqual(deduped.length, 1)
    assert.strictEqual(deduped[0].name, 'dup.png')

    const appliedAttrs = {}
    const html = {
      style: {},
      setAttribute: (key, value) => {
        appliedAttrs[key] = value
      },
      getAttribute: key => appliedAttrs[key]
    }
    const lightClasses = new Set(['vscode-light'])
    const fakeDocument = {
      body: {
        classList: {
          contains: value => lightClasses.has(value)
        }
      },
      documentElement: html,
      defaultView: {
        getComputedStyle: () => ({
          colorScheme: 'light',
          backgroundColor: 'rgb(250, 250, 250)'
        })
      }
    }

    const themeKind = helpers.applyThemeKindToDocument(fakeDocument)
    assert.strictEqual(themeKind, 'light')
    assert.strictEqual(appliedAttrs['data-vscode-theme-kind'], 'light')
    assert.strictEqual(html.style.colorScheme, 'light')
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

  test('AppleScript 配置应默认关闭且变更后立即生效', async () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')

    await ext.activate()

    const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
    const original = cfg.get('enableAppleScript')

    try {
      await cfg.update('enableAppleScript', false, vscode.ConfigurationTarget.Global)

      await assert.rejects(
        vscode.commands.executeCommand('ai-intervention-agent.runAppleScript', 'return "ok"'),
        e => {
          const msg = e && e.message ? String(e.message) : String(e)
          assert.ok(msg.includes('enableAppleScript'))
          return true
        }
      )

      await cfg.update('enableAppleScript', true, vscode.ConfigurationTarget.Global)

      if (process.platform === 'darwin') {
        const out = await vscode.commands.executeCommand(
          'ai-intervention-agent.runAppleScript',
          'return "ok"'
        )
        assert.strictEqual(String(out).trim(), 'ok')
      } else {
        await assert.rejects(
          vscode.commands.executeCommand('ai-intervention-agent.runAppleScript', 'return "ok"'),
          e => {
            const msg = e && e.message ? String(e.message) : String(e)
            assert.ok(msg.includes('Platform not supported'))
            return true
          }
        )
      }
    } finally {
      const restore = typeof original === 'boolean' ? original : false
      await cfg.update('enableAppleScript', restore, vscode.ConfigurationTarget.Global)
    }
  })
})
