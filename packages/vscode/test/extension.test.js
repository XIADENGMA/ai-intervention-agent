const assert = require('assert')
const fs = require('fs')
const path = require('path')

// 可直接使用 'vscode' 模块的所有 API。
// 如需测试扩展入口，可在此处引入 extension（当前测试不需要）。
const vscode = require('vscode')

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
    const webviewCssPath = path.join(ext.extensionPath, 'webview.css')
    const extensionJsPath = path.join(ext.extensionPath, 'extension.js')
    const mathjaxScriptPath = path.join(ext.extensionPath, 'mathjax', 'tex-mml-svg.js')
    const extPkgPath = path.join(ext.extensionPath, 'package.json')

    assert.ok(fs.existsSync(webviewJsPath), 'Missing webview.js in extension')
    assert.ok(fs.existsSync(webviewHelpersPath), 'Missing webview-helpers.js in extension')
    assert.ok(fs.existsSync(webviewUiPath), 'Missing webview-ui.js in extension')
    assert.ok(fs.existsSync(webviewCssPath), 'Missing webview.css in extension')
    assert.ok(fs.existsSync(extensionJsPath), 'Missing extension.js in extension')
    assert.ok(fs.existsSync(mathjaxScriptPath), 'Missing mathjax/tex-mml-svg.js in extension')
    assert.ok(fs.existsSync(extPkgPath), 'Missing package.json in extension')

    const webviewJs = fs.readFileSync(webviewJsPath, 'utf8')
    const webviewUi = fs.readFileSync(webviewUiPath, 'utf8')
    const webviewCss = fs.readFileSync(webviewCssPath, 'utf8')
    const extensionJs = fs.readFileSync(extensionJsPath, 'utf8')
    const extPkgText = fs.readFileSync(extPkgPath, 'utf8')

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
    // 轮询协同：Webview 上报 tasks stats（用于扩展状态栏降频）
    assert.ok(webviewUi.includes("type: 'tasksStats'"))
    assert.ok(webviewJs.includes("case 'tasksStats':"))
    // 内存优先：Webview 状态应使用 getState/setState 持久化
    assert.ok(webviewUi.includes('vscode.getState'))
    assert.ok(webviewUi.includes('vscode.setState'))
    assert.ok(extensionJs.includes('retainContextWhenHidden: false'))
    // 稳定性/解耦：MathJax 应优先走 VSIX 内置资源（由 meta 注入 URL）
    assert.ok(webviewJs.includes('data-mathjax-script-url'))
    assert.ok(webviewJs.includes('tex-mml-svg.js'))

    // 安全回归点：script-src 应使用 nonce-only（不应再额外放开 ${cspSource} 或 unsafe-inline）
    assert.ok(webviewJs.includes("script-src 'nonce-${nonce}';"))
    assert.ok(!webviewJs.includes("script-src 'nonce-${nonce}' ${cspSource};"))
    assert.ok(!webviewJs.includes("script-src 'nonce-${nonce}' 'unsafe-inline'"))

    // 安全回归点：style-src 不应放开 unsafe-inline（CSS 应通过外链引入）
    assert.ok(webviewJs.includes('style-src ${cspSource};'))
    assert.ok(!webviewJs.includes("style-src ${cspSource} 'unsafe-inline'"))
    assert.ok(webviewJs.includes('webview.css'))

    // CSP 细化回归点：应显式禁止 base-uri/object/frame
    assert.ok(webviewJs.includes("base-uri 'none'"))
    assert.ok(webviewJs.includes("object-src 'none'"))
    assert.ok(webviewJs.includes("frame-src 'none'"))

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
    assert.ok(extPkgText.includes('ai-intervention-agent.logLevel'))
    assert.ok(extPkgText.includes('ai-intervention-agent.enableAppleScript'))
    assert.ok(extPkgText.includes('http://localhost:8080'))
    assert.ok(webviewJs.includes('http://localhost:8080'))
    assert.ok(webviewCss.includes('overflow-wrap: anywhere;'))
    assert.ok(webviewCss.includes('white-space: pre-wrap;'))

    // 资源回归点：无内容页 Lottie 资源应存在且路径一致（避免回退为 emoji）
    const hourglassJsonPath = path.join(ext.extensionPath, 'lottie', 'hourglass.json')
    assert.ok(fs.existsSync(hourglassJsonPath), 'Missing lottie/hourglass.json in extension')
    assert.ok(webviewJs.includes('hourglass.json'))
    assert.ok(!webviewJs.includes('sprout.json'))

    // manifest 回归点：Activity Bar 容器 icon 应使用文件路径（不应使用 $(codicon)）
    const extPkgJson = JSON.parse(extPkgText)
    assert.ok(Array.isArray(extPkgJson.files), 'package.json should include files[]')
    assert.ok(extPkgJson.files.includes('webview.css'), 'package.json files[] should include webview.css')

    const containers =
      extPkgJson &&
      extPkgJson.contributes &&
      extPkgJson.contributes.viewsContainers &&
      extPkgJson.contributes.viewsContainers.activitybar
        ? extPkgJson.contributes.viewsContainers.activitybar
        : []
    assert.ok(Array.isArray(containers) && containers.length > 0)
    assert.strictEqual(containers[0].icon, 'activity-icon.svg')

    // 打包脚本回归点：最小文件集合必须包含 webview.css（否则 VSIX 缺资源）
    const repoRoot = path.resolve(ext.extensionPath, '..', '..')
    const packagingScriptPath = path.join(repoRoot, 'scripts', 'package_vscode_vsix.mjs')
    if (fs.existsSync(packagingScriptPath)) {
      const packagingScript = fs.readFileSync(packagingScriptPath, 'utf8')
      assert.ok(packagingScript.includes('"webview.css"'))
      assert.ok(packagingScript.includes('"mathjax"'))
    }
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
    const lines = []
    const fakeLogChannel = {
      info: msg => calls.push(['info', msg]),
      warn: msg => calls.push(['warn', msg]),
      error: msg => calls.push(['error', msg]),
      debug: msg => calls.push(['debug', msg]),
      appendLine: line => lines.push(String(line))
    }

    const logger = createLogger(fakeLogChannel, { component: 't', getLevel: () => 'debug' })
    logger.info('hello')

    // 方案 A：应优先走 appendLine，避免 LogOutputChannel 的二次过滤（且不应调用 info/warn/error/debug）
    assert.strictEqual(calls.length, 0)
    assert.strictEqual(lines.length, 1)
    assert.ok(/\[INFO\]\s+\[t\]\s+hello/.test(lines[0]))
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
