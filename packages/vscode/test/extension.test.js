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
    const webviewNotifyCorePath = path.join(ext.extensionPath, 'webview-notify-core.js')
    const webviewSettingsUiPath = path.join(ext.extensionPath, 'webview-settings-ui.js')
    const webviewCssPath = path.join(ext.extensionPath, 'webview.css')
    const extensionJsPath = path.join(ext.extensionPath, 'extension.js')
    const mathjaxScriptPath = path.join(ext.extensionPath, 'mathjax', 'tex-mml-svg.js')
    const extPkgPath = path.join(ext.extensionPath, 'package.json')

    assert.ok(fs.existsSync(webviewJsPath), 'Missing webview.js in extension')
    assert.ok(fs.existsSync(webviewHelpersPath), 'Missing webview-helpers.js in extension')
    assert.ok(fs.existsSync(webviewUiPath), 'Missing webview-ui.js in extension')
    assert.ok(fs.existsSync(webviewNotifyCorePath), 'Missing webview-notify-core.js in extension')
    assert.ok(fs.existsSync(webviewSettingsUiPath), 'Missing webview-settings-ui.js in extension')
    assert.ok(fs.existsSync(webviewCssPath), 'Missing webview.css in extension')
    assert.ok(fs.existsSync(extensionJsPath), 'Missing extension.js in extension')
    assert.ok(fs.existsSync(mathjaxScriptPath), 'Missing mathjax/tex-mml-svg.js in extension')
    assert.ok(fs.existsSync(extPkgPath), 'Missing package.json in extension')

    const webviewJs = fs.readFileSync(webviewJsPath, 'utf8')
    const webviewUi = fs.readFileSync(webviewUiPath, 'utf8')
    const notifyCore = fs.readFileSync(webviewNotifyCorePath, 'utf8')
    const settingsUi = fs.readFileSync(webviewSettingsUiPath, 'utf8')
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
    assert.ok(notifyCore.includes('macos_native'))
    // 设置面板：原生通知测试应为“手动触发”，不依赖复杂诊断链路
    assert.ok(settingsUi.includes("kind: 'test_macos_native'"))
    // 轮询协同：Webview 上报 tasks stats（用于扩展状态栏降频）
    assert.ok(webviewUi.includes("type: 'tasksStats'"))
    assert.ok(webviewJs.includes("case 'tasksStats':"))
    // 性能回归点：空闲态应自动降低轮询频率，减少无意义请求
    assert.ok(webviewUi.includes('POLL_IDLE_MS'))
    // 内存优先：Webview 状态应使用 getState/setState 持久化
    assert.ok(webviewUi.includes('vscode.getState'))
    assert.ok(webviewUi.includes('vscode.setState'))
    assert.ok(extensionJs.includes('retainContextWhenHidden: false'))
    // 边界回归点：0.0.0.0/:: 仅适合作为监听地址，扩展侧应映射为 localhost（避免客户端无法访问）
    assert.ok(extensionJs.includes("host === '0.0.0.0' || host === '::'"))
    // 稳定性/解耦：MathJax 应优先走 VSIX 内置资源（由 meta 注入 URL）
    assert.ok(webviewJs.includes('data-mathjax-script-url'))
    assert.ok(webviewJs.includes('tex-mml-svg.js'))

    // 启动性能回归点：marked/prism 应由 webview-ui 按需懒加载（不应在 HTML 中强制同步加载）
    assert.ok(webviewJs.includes('data-marked-js-url'))
    assert.ok(webviewJs.includes('data-prism-js-url'))
    assert.ok(webviewUi.includes('data-marked-js-url'))
    assert.ok(webviewUi.includes('data-prism-js-url'))
    assert.ok(webviewUi.includes('ensureMarkedLoaded'))
    assert.ok(webviewUi.includes('ensurePrismLoaded'))
    assert.ok(!webviewJs.includes('script nonce="${nonce}" src="${markedJsUri}"'))
    assert.ok(!webviewJs.includes('script nonce="${nonce}" src="${prismJsUri}"'))

    // 启动性能回归点：通知配置/设置面板应按需懒加载（避免首屏解析负担）
    assert.ok(webviewJs.includes('data-notify-core-js-url'))
    assert.ok(webviewJs.includes('data-settings-ui-js-url'))
    assert.ok(webviewUi.includes('data-notify-core-js-url'))
    assert.ok(webviewUi.includes('data-settings-ui-js-url'))
    assert.ok(webviewUi.includes('ensureNotifyCoreLoaded'))
    assert.ok(webviewUi.includes('ensureSettingsUiLoaded'))

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
    // 高优先稳定性回归点：提交必须有超时兜底（避免服务端无响应导致 UI 永久卡住）
    assert.ok(webviewUi.includes('SUBMIT_TIMEOUT_MS'))
    assert.ok(webviewUi.includes('提交超时：请检查服务端是否可用'))
    assert.ok(webviewUi.includes('buildMarkdownCodeFence'))
    assert.ok(webviewUi.includes('const codeBlockBody = buildMarkdownCodeFence(code, lang)'))
    assert.ok(!webviewUi.includes('const trimmed = raw.trim();'))
    // 高优先稳定性回归点：stopPolling 后不得“复活”轮询定时器
    assert.ok(webviewUi.includes('pollingToken'))
    assert.ok(webviewUi.includes('t !== pollingToken'))
    // 稳定性回归点：/api/config 失败时应回退到 /api/tasks/<id>，避免 UI 卡在“无有效内容”
    assert.ok(webviewUi.includes('fetchTaskDetailAsConfig'))
    // 高优先稳定性回归点：扩展停用后不得继续调度 status poll 定时器
    assert.ok(extensionJs.includes('statusPollDisposed'))

    // 配置回归点：应提供 logLevel 配置项（便于排查问题）
    assert.ok(extPkgText.includes('ai-intervention-agent.logLevel'))
    assert.ok(extPkgText.includes('http://localhost:8080'))
    assert.ok(webviewJs.includes('http://localhost:8080'))
    assert.ok(webviewCss.includes('overflow-wrap: anywhere;'))
    assert.ok(webviewCss.includes('white-space: pre-wrap;'))
    // CSP 收紧回归点：color-scheme 应由 CSS 驱动（不依赖 JS 写 inline style）
    assert.ok(webviewCss.includes('color-scheme: dark'))
    assert.ok(webviewCss.includes('color-scheme: light'))

    // 资源回归点：无内容页 Lottie 资源应存在且路径一致（嫩芽动画：sprout.json；失败应降级为 SVG）
    const sproutJsonPath = path.join(ext.extensionPath, 'lottie', 'sprout.json')
    const lottieLibPath = path.join(ext.extensionPath, 'lottie.min.js')
    assert.ok(fs.existsSync(sproutJsonPath), 'Missing lottie/sprout.json in extension')
    assert.ok(fs.existsSync(lottieLibPath), 'Missing lottie.min.js in extension')
    assert.ok(webviewJs.includes('sprout.json'))
    assert.ok(!webviewJs.includes('hourglass.json'))
    assert.ok(!webviewUi.includes('⏳'), 'webview-ui.js should not fall back to emoji')
    // Lottie JSON 通过 fetch 加载：connect-src 必须允许 Webview 自身/本地资源，否则会永远 data missing → 退化状态
    assert.ok(
      webviewJs.includes("connect-src ${serverUrl} ${cspSource} 'self'"),
      "CSP connect-src should include ${cspSource} and 'self'"
    )
    // manifest 注入回归点：Lottie lib URL 必须通过 meta 下发（CSP-safe 懒加载）
    assert.ok(webviewJs.includes('data-lottie-lib-url'))
    assert.ok(webviewUi.includes('data-lottie-lib-url'))
    // manifest 注入回归点：无内容页 SVG 降级应优先使用 activity-icon.svg（通过 meta 下发 URL）
    assert.ok(webviewJs.includes('data-no-content-fallback-svg-url'))
    assert.ok(webviewUi.includes('data-no-content-fallback-svg-url'))
    // 稳定性回归点：无内容页本地资源（SVG/Lottie JSON）应支持内联注入，避免 fetch 被 CSP/协议差异拦截
    assert.ok(webviewJs.includes('__AIIA_NO_CONTENT_FALLBACK_SVG'))
    assert.ok(webviewJs.includes('__AIIA_NO_CONTENT_LOTTIE_DATA'))
    assert.ok(webviewUi.includes('__AIIA_NO_CONTENT_FALLBACK_SVG'))
    assert.ok(webviewUi.includes('__AIIA_NO_CONTENT_LOTTIE_DATA'))
    // Lottie 降级/恢复关键回归点：应具备 SVG 降级 + 自动重试/恢复机制
    assert.ok(webviewUi.includes('renderNoContentFallbackIcon'))
    assert.ok(webviewUi.includes('scheduleNoContentLottieRetry'))
    assert.ok(webviewUi.includes('installNoContentLottieRecoveryHandlers'))
    assert.ok(
      webviewUi.includes("NO_CONTENT_FALLBACK_ICON_VARIANT = 'hourglass'"),
      'no-content fallback icon should default to hourglass'
    )
    assert.ok(
      webviewUi.includes('if (!ok) lottieLoadPromise = null'),
      'ensureLottieLoaded should reset cached promise on failure'
    )
    assert.ok(
      webviewUi.includes('if (!data) noContentLottieDataPromise = null'),
      'loadNoContentLottieData should reset cached promise on failure'
    )
    assert.ok(webviewUi.includes('DOMLoaded timeout'), 'should have DOMLoaded timeout fallback')
    assert.ok(webviewUi.includes("addEventListener('online'"), 'should retry on online event')
    assert.ok(
      webviewUi.includes("addEventListener('visibilitychange'"),
      'should retry on visibilitychange'
    )
    assert.ok(
      webviewUi.includes('MutationObserver'),
      'should observe no-content visibility changes'
    )
    assert.ok(
      webviewCss.includes('.aiia-fallback-icon'),
      'webview.css should include fallback icon styling'
    )
    assert.ok(
      webviewCss.includes('aiia-fallback-spin'),
      'webview.css should include fallback spin keyframes'
    )

    // manifest 回归点：Activity Bar 容器 icon 应使用文件路径（不应使用 $(codicon)）
    const extPkgJson = JSON.parse(extPkgText)
    // manifest 一致性：commands 与 activationEvents 应保持匹配（避免命令触发时未激活扩展）
    assert.ok(
      Array.isArray(extPkgJson.activationEvents) &&
        extPkgJson.activationEvents.includes('onCommand:ai-intervention-agent.openPanel') &&
        extPkgJson.activationEvents.includes('onCommand:ai-intervention-agent.openSettings'),
      'activationEvents should include openPanel/openSettings commands'
    )
    assert.ok(Array.isArray(extPkgJson.files), 'package.json should include files[]')
    assert.ok(
      extPkgJson.files.includes('webview.css'),
      'package.json files[] should include webview.css'
    )
    assert.ok(
      extPkgJson.files.includes('webview-notify-core.js'),
      'package.json files[] should include webview-notify-core.js'
    )
    assert.ok(
      extPkgJson.files.includes('webview-settings-ui.js'),
      'package.json files[] should include webview-settings-ui.js'
    )
    assert.ok(
      extPkgJson.files.includes('vendor/terminal-notifier/**'),
      'package.json files[] should include vendor/terminal-notifier/**'
    )
    const terminalNotifierBin = path.join(
      ext.extensionPath,
      'vendor',
      'terminal-notifier',
      'terminal-notifier.app',
      'Contents',
      'MacOS',
      'terminal-notifier'
    )
    assert.ok(
      fs.existsSync(terminalNotifierBin),
      'terminal-notifier binary should exist in extension'
    )

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
      assert.ok(packagingScript.includes('"webview-notify-core.js"'))
      assert.ok(packagingScript.includes('"webview-settings-ui.js"'))
      assert.ok(packagingScript.includes('"vendor"'))
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
    // CSP 收紧后不应通过 JS 写入 inline style；color-scheme 由 webview.css 根据 attribute 驱动
    assert.strictEqual(html.style.colorScheme, undefined)
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
})
