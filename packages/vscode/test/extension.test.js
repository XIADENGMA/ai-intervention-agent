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

    const webviewJsPath = path.join(ext.extensionPath, 'dist', 'webview.js')
    const webviewStatePath = path.join(ext.extensionPath, 'webview-state.js')
    const webviewHelpersPath = path.join(ext.extensionPath, 'webview-helpers.js')
    const webviewUiPath = path.join(ext.extensionPath, 'webview-ui.js')
    const webviewNotifyCorePath = path.join(ext.extensionPath, 'webview-notify-core.js')
    const webviewSettingsUiPath = path.join(ext.extensionPath, 'webview-settings-ui.js')
    const webviewCssPath = path.join(ext.extensionPath, 'webview.css')
    const extensionJsPath = path.join(ext.extensionPath, 'dist', 'extension.js')
    const mathjaxScriptPath = path.join(ext.extensionPath, 'mathjax', 'tex-mml-svg.js')
    const extPkgPath = path.join(ext.extensionPath, 'package.json')

    assert.ok(fs.existsSync(webviewJsPath), 'Missing dist/webview.js in extension')
    assert.ok(fs.existsSync(webviewStatePath), 'Missing webview-state.js in extension')
    assert.ok(fs.existsSync(webviewHelpersPath), 'Missing webview-helpers.js in extension')
    assert.ok(fs.existsSync(webviewUiPath), 'Missing webview-ui.js in extension')
    assert.ok(fs.existsSync(webviewNotifyCorePath), 'Missing webview-notify-core.js in extension')
    assert.ok(fs.existsSync(webviewSettingsUiPath), 'Missing webview-settings-ui.js in extension')
    assert.ok(fs.existsSync(webviewCssPath), 'Missing webview.css in extension')
    assert.ok(fs.existsSync(extensionJsPath), 'Missing dist/extension.js in extension')
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
    // IG-3 统一状态机：HTML 必须在 helpers/ui 之前加载 webview-state.js，以便
    // 后续模块可用 window.AIIAState.createMachine(...) 构造 SSE/内容状态机。
    assert.ok(
      webviewJs.includes('webview-state.js'),
      'webview.ts 生成的 HTML 应加载 webview-state.js（IG-3 状态机契约）'
    )
    // BM-5：规避 VSCode issue #113188 retainContextWhenHidden ghost rendering
    // 两端都必须带 force-repaint 协议：host 可见时派发，webview 收到后做 rAF layer 重建
    assert.ok(
      webviewJs.includes("type: 'force-repaint'"),
      'webview.ts 应在 onDidChangeVisibility 可见时发送 force-repaint（BM-5）'
    )
    assert.ok(
      webviewUi.includes("case 'force-repaint'"),
      "webview-ui.js 应处理 'force-repaint' 消息以清除 ghost 合成层（BM-5）"
    )
    assert.ok(
      webviewUi.includes('aiia-repainting'),
      'webview-ui.js 应通过切换 aiia-repainting class 触发重绘（避开 CSP inline-style）'
    )
    assert.ok(
      webviewCss.includes('aiia-repainting'),
      'webview.css 应定义 body.aiia-repainting 规则（含 translateZ 以建立新合成层）'
    )
    // BM-7：首帧 boot skeleton（纯 CSS 占位 + JS 安全退场 + CSS 级兜底 autohide）
    assert.ok(
      webviewJs.includes('id="aiiaBootSkeleton"'),
      'webview.ts 生成的 HTML 应包含 boot skeleton 容器（BM-7）'
    )
    assert.ok(
      webviewJs.includes('aiia-boot-skeleton__bar--title'),
      'webview.ts 生成的 HTML 应至少包含一条标题型骨架条（BM-7 结构性占位）'
    )
    assert.ok(
      webviewCss.includes('.aiia-boot-skeleton'),
      'webview.css 应定义 .aiia-boot-skeleton 规则（首帧占位层）'
    )
    assert.ok(
      webviewCss.includes('aiia-boot-skeleton-autohide'),
      'webview.css 应定义 aiia-boot-skeleton-autohide 动画作为 JS 失效兜底'
    )
    assert.ok(
      webviewUi.includes('hideBootSkeleton'),
      'webview-ui.js 应定义 hideBootSkeleton 并在 init 成功/错误兜底路径调用（BM-7）'
    )
    assert.ok(
      webviewUi.includes('aiia-boot-skeleton--leaving'),
      'webview-ui.js 应通过切换 --leaving class 触发淡出（避开 CSP inline-style）'
    )
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
    // 侧边栏加载性能回归点：应启用 retainContextWhenHidden 以消除重复 resolveWebviewView 阻塞
    assert.ok(
      extensionJs.includes('retainContextWhenHidden: true'),
      'extension.ts 应设置 retainContextWhenHidden: true，避免侧边栏隐藏/显示时重建 webview'
    )
    // 侧边栏加载性能回归点：语言预取必须 fire-and-forget（不能再 await，否则服务器不可达时首屏最坏 7.5s 空白）
    assert.ok(
      webviewJs.includes('this._prefetchServerLanguage().catch('),
      '_prefetchServerLanguage 应以 .catch() fire-and-forget 方式调用，不得阻塞首屏'
    )
    assert.ok(
      !webviewJs.includes('await this._prefetchServerLanguage('),
      'resolveWebviewView/updateServerUrl 不应 await 语言预取（TLA/超时将阻塞首屏）'
    )
    // 侧边栏加载性能回归点：语言预取应收紧超时（1000ms，localhost 毫秒级，失败即降级）
    assert.ok(
      webviewJs.includes('controller.abort()'),
      '_prefetchServerLanguage 必须有 AbortController 超时护栏'
    )
    // 侧边栏加载性能回归点：Lottie JSON 不应内联进 HTML（~445KB），由前端通过 URL 懒加载
    assert.ok(
      webviewJs.includes("const inlineNoContentLottieDataLiteral = 'null'"),
      '_getHtmlContent 不应将 445KB Lottie JSON 内联进 HTML'
    )
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
    // P8 后：硬编码 CJK 已迁移到 locale，改为断言 i18n key + timeout 配置都在
    assert.ok(webviewUi.includes('SUBMIT_TIMEOUT_MS'))
    assert.ok(webviewUi.includes('ui.submit.timeoutCheckServer'))
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
    // terminal-notifier 仅在 macOS 环境打包，Linux CI 跳过
    if (process.platform === 'darwin') {
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
    }

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
      const includesPath = name =>
        packagingScript.includes(`'${name}'`) || packagingScript.includes(`"${name}"`)
      for (const name of [
        'webview.css',
        'mathjax',
        'webview-state.js',
        'webview-notify-core.js',
        'webview-settings-ui.js',
        'vendor'
      ]) {
        assert.ok(includesPath(name), `packaging script should include ${name}`)
      }
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

    const loggerPath = path.join(ext.extensionPath, 'dist', 'logger.js')
    assert.ok(fs.existsSync(loggerPath), 'Missing dist/logger.js in extension')

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

    const loggerPath = path.join(ext.extensionPath, 'dist', 'logger.js')
    assert.ok(fs.existsSync(loggerPath), 'Missing dist/logger.js in extension')

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

  // ===========================================================================
  // 运行时行为正确性验证（排查 Integration Gap / I18n Bootstrap Failure）
  // ===========================================================================

  test('Extension version 不应为 fallback 值 0.0.0', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found')

    const pkgPath = path.join(ext.extensionPath, 'package.json')
    const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'))
    assert.ok(pkg.version, 'package.json missing version field')
    assert.notStrictEqual(pkg.version, '0.0.0', 'version must not be fallback value 0.0.0')
    assert.ok(/^\d+\.\d+\.\d+/.test(pkg.version), `version '${pkg.version}' must match semver`)
  })

  test('i18n key coverage: 插件 JS 中所有 t() key 必须在 locale 文件中存在', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found')

    const tKeyPattern = /(?<![a-zA-Z_])t\(['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]/g

    const jsFiles = ['webview-ui.js', 'webview-settings-ui.js']
    const allKeys = new Set()
    for (const name of jsFiles) {
      const filePath = path.join(ext.extensionPath, name)
      if (!fs.existsSync(filePath)) continue
      const content = fs.readFileSync(filePath, 'utf8')
      let match
      while ((match = tKeyPattern.exec(content)) !== null) {
        allKeys.add(match[1])
      }
    }

    assert.ok(allKeys.size > 0, 'no t() keys extracted (extraction logic may be broken)')

    const localeNames = ['en', 'zh-CN']
    for (const loc of localeNames) {
      const localePath = path.join(ext.extensionPath, 'locales', loc + '.json')
      if (!fs.existsSync(localePath)) {
        assert.fail(`locale 文件不存在: ${localePath}`)
      }
      const data = JSON.parse(fs.readFileSync(localePath, 'utf8'))

      const flatKeys = new Set()
      function flatten(obj, prefix) {
        for (const [k, v] of Object.entries(obj)) {
          const full = prefix ? prefix + '.' + k : k
          if (v && typeof v === 'object' && !Array.isArray(v)) {
            flatten(v, full)
          } else {
            flatKeys.add(full)
          }
        }
      }
      flatten(data, '')

      const missing = []
      for (const key of allKeys) {
        if (!flatKeys.has(key)) missing.push(key)
      }

      assert.strictEqual(
        missing.length,
        0,
        `[${loc}] locale 文件缺失以下 i18n key:\n  ${missing.sort().join('\n  ')}`
      )
    }
  })

  test('Locale parity: 插件 en.json 和 zh-CN.json 应有相同的键结构', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found')

    function flattenKeys(obj, prefix) {
      const keys = new Set()
      for (const [k, v] of Object.entries(obj)) {
        const full = prefix ? prefix + '.' + k : k
        if (v && typeof v === 'object' && !Array.isArray(v)) {
          for (const sub of flattenKeys(v, full)) keys.add(sub)
        } else {
          keys.add(full)
        }
      }
      return keys
    }

    const enPath = path.join(ext.extensionPath, 'locales', 'en.json')
    const zhPath = path.join(ext.extensionPath, 'locales', 'zh-CN.json')
    assert.ok(fs.existsSync(enPath), 'en.json 不存在')
    assert.ok(fs.existsSync(zhPath), 'zh-CN.json 不存在')

    const enKeys = flattenKeys(JSON.parse(fs.readFileSync(enPath, 'utf8')), '')
    const zhKeys = flattenKeys(JSON.parse(fs.readFileSync(zhPath, 'utf8')), '')

    const onlyInEn = [...enKeys].filter(k => !zhKeys.has(k)).sort()
    const onlyInZh = [...zhKeys].filter(k => !enKeys.has(k)).sort()

    const msgs = []
    if (onlyInEn.length) msgs.push('only in en.json: ' + onlyInEn.join(', '))
    if (onlyInZh.length) msgs.push('only in zh-CN.json: ' + onlyInZh.join(', '))
    assert.strictEqual(msgs.length, 0, 'Locale key structure mismatch:\n  ' + msgs.join('\n  '))
  })

  test('webview.ts 编译产物应包含版本号注入逻辑（非 require 方式）', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found')

    const webviewJsPath = path.join(ext.extensionPath, 'dist', 'webview.js')
    assert.ok(fs.existsSync(webviewJsPath), 'Missing dist/webview.js')
    const webviewJs = fs.readFileSync(webviewJsPath, 'utf8')

    assert.ok(
      webviewJs.includes('extensionVersion'),
      'dist/webview.js 应包含 extensionVersion 变量'
    )
    assert.ok(
      webviewJs.includes('packageJSON'),
      'dist/webview.js 应包含 packageJSON 版本读取逻辑'
    )
  })

  // ===========================================================================
  // 插件运行时行为正确性验证
  // （加载 i18n 模块、注册 locale、实际调用 t() 验证翻译不返回原始 key）
  // ===========================================================================

  test('i18n runtime: 加载模块后 t() 翻译所有 plugin key 不应返回原始 key', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found')

    const i18nPath = path.join(ext.extensionPath, 'i18n.js')
    assert.ok(fs.existsSync(i18nPath), 'Missing i18n.js')

    const enData = JSON.parse(
      fs.readFileSync(path.join(ext.extensionPath, 'locales', 'en.json'), 'utf8')
    )
    const zhData = JSON.parse(
      fs.readFileSync(path.join(ext.extensionPath, 'locales', 'zh-CN.json'), 'utf8')
    )

    // 模拟 webview 注入环境（webview.ts 在 HTML 中通过内联 script 写入这些全局变量）
    const prevLang = globalThis.__AIIA_I18N_LANG
    const prevLocale = globalThis.__AIIA_I18N_LOCALE
    const prevAll = globalThis.__AIIA_I18N_ALL_LOCALES
    const prevApi = globalThis.AIIA_I18N

    globalThis.__AIIA_I18N_LANG = 'en'
    globalThis.__AIIA_I18N_LOCALE = enData
    globalThis.__AIIA_I18N_ALL_LOCALES = { en: enData, 'zh-CN': zhData }

    // 清除缓存以确保 i18n IIFE 重新执行（触发自动注册）
    delete require.cache[require.resolve(i18nPath)]
    require(i18nPath)

    const i18n = globalThis.AIIA_I18N
    assert.ok(i18n, 'AIIA_I18N not registered on globalThis')
    assert.ok(i18n.getAvailableLangs().length >= 2, 'at least en + zh-CN locales must be registered')

    // 提取所有 t() key
    const tKeyPattern = /(?<![a-zA-Z_])t\(['"]([a-zA-Z][a-zA-Z0-9_.]+)['"]\s*[,)]/g
    const allKeys = new Set()
    for (const name of ['webview-ui.js', 'webview-settings-ui.js']) {
      const filePath = path.join(ext.extensionPath, name)
      if (!fs.existsSync(filePath)) continue
      const content = fs.readFileSync(filePath, 'utf8')
      let match
      while ((match = tKeyPattern.exec(content)) !== null) {
        allKeys.add(match[1])
      }
    }

    assert.ok(allKeys.size > 0, 'no t() keys extracted')

    // 验证英文：t() 不应返回原始 key
    i18n.setLang('en')
    const enRawKeys = []
    for (const key of allKeys) {
      if (i18n.t(key) === key) enRawKeys.push(key)
    }
    assert.strictEqual(
      enRawKeys.length,
      0,
      `[en] t() 返回原始 key（翻译缺失）:\n  ${enRawKeys.sort().join('\n  ')}`
    )

    // 验证中文：t() 不应返回原始 key
    i18n.setLang('zh-CN')
    const zhRawKeys = []
    for (const key of allKeys) {
      if (i18n.t(key) === key) zhRawKeys.push(key)
    }
    assert.strictEqual(
      zhRawKeys.length,
      0,
      `[zh-CN] t() 返回原始 key（翻译缺失）:\n  ${zhRawKeys.sort().join('\n  ')}`
    )

    // 清理 globalThis（恢复原状）
    if (prevLang !== undefined) globalThis.__AIIA_I18N_LANG = prevLang
    else delete globalThis.__AIIA_I18N_LANG
    if (prevLocale !== undefined) globalThis.__AIIA_I18N_LOCALE = prevLocale
    else delete globalThis.__AIIA_I18N_LOCALE
    if (prevAll !== undefined) globalThis.__AIIA_I18N_ALL_LOCALES = prevAll
    else delete globalThis.__AIIA_I18N_ALL_LOCALES
    if (prevApi !== undefined) globalThis.AIIA_I18N = prevApi
    else delete globalThis.AIIA_I18N
  })

  test('i18n runtime: setLang() 应正确切换语言，翻译内容应不同', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found')

    const i18nPath = path.join(ext.extensionPath, 'i18n.js')
    const enData = JSON.parse(
      fs.readFileSync(path.join(ext.extensionPath, 'locales', 'en.json'), 'utf8')
    )
    const zhData = JSON.parse(
      fs.readFileSync(path.join(ext.extensionPath, 'locales', 'zh-CN.json'), 'utf8')
    )

    const prevLang = globalThis.__AIIA_I18N_LANG
    const prevLocale = globalThis.__AIIA_I18N_LOCALE
    const prevAll = globalThis.__AIIA_I18N_ALL_LOCALES
    const prevApi = globalThis.AIIA_I18N

    globalThis.__AIIA_I18N_LANG = 'en'
    globalThis.__AIIA_I18N_LOCALE = enData
    globalThis.__AIIA_I18N_ALL_LOCALES = { en: enData, 'zh-CN': zhData }

    delete require.cache[require.resolve(i18nPath)]
    require(i18nPath)

    const i18n = globalThis.AIIA_I18N
    assert.ok(i18n)

    // 英文
    i18n.setLang('en')
    assert.strictEqual(i18n.getLang(), 'en')
    const enTitle = i18n.t('settings.title')
    assert.notStrictEqual(enTitle, 'settings.title', 'English translation must not return raw key')

    // Chinese
    i18n.setLang('zh-CN')
    assert.strictEqual(i18n.getLang(), 'zh-CN')
    const zhTitle = i18n.t('settings.title')
    assert.notStrictEqual(zhTitle, 'settings.title', 'Chinese translation must not return raw key')

    // Translations must differ between the two languages
    assert.notStrictEqual(enTitle, zhTitle, 'settings.title must differ between en and zh-CN')

    // 清理
    if (prevLang !== undefined) globalThis.__AIIA_I18N_LANG = prevLang
    else delete globalThis.__AIIA_I18N_LANG
    if (prevLocale !== undefined) globalThis.__AIIA_I18N_LOCALE = prevLocale
    else delete globalThis.__AIIA_I18N_LOCALE
    if (prevAll !== undefined) globalThis.__AIIA_I18N_ALL_LOCALES = prevAll
    else delete globalThis.__AIIA_I18N_ALL_LOCALES
    if (prevApi !== undefined) globalThis.AIIA_I18N = prevApi
    else delete globalThis.AIIA_I18N
  })

  test('i18n runtime: 不存在的 key 应返回原始 key（降级而非崩溃）', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found')

    const i18nPath = path.join(ext.extensionPath, 'i18n.js')
    const enData = JSON.parse(
      fs.readFileSync(path.join(ext.extensionPath, 'locales', 'en.json'), 'utf8')
    )

    const prevLang = globalThis.__AIIA_I18N_LANG
    const prevLocale = globalThis.__AIIA_I18N_LOCALE
    const prevAll = globalThis.__AIIA_I18N_ALL_LOCALES
    const prevApi = globalThis.AIIA_I18N

    globalThis.__AIIA_I18N_LANG = 'en'
    globalThis.__AIIA_I18N_LOCALE = enData
    globalThis.__AIIA_I18N_ALL_LOCALES = { en: enData }

    delete require.cache[require.resolve(i18nPath)]
    require(i18nPath)

    const i18n = globalThis.AIIA_I18N
    assert.ok(i18n)

    // 不存在的 key 应返回原始 key（不崩溃）
    const result = i18n.t('this.key.definitely.does.not.exist')
    assert.strictEqual(result, 'this.key.definitely.does.not.exist')

    // 参数插值在不存在的 key 上也不应崩溃
    const result2 = i18n.t('nonexistent.key', { param: 'val' })
    assert.strictEqual(result2, 'nonexistent.key')

    // 清理
    if (prevLang !== undefined) globalThis.__AIIA_I18N_LANG = prevLang
    else delete globalThis.__AIIA_I18N_LANG
    if (prevLocale !== undefined) globalThis.__AIIA_I18N_LOCALE = prevLocale
    else delete globalThis.__AIIA_I18N_LOCALE
    if (prevAll !== undefined) globalThis.__AIIA_I18N_ALL_LOCALES = prevAll
    else delete globalThis.__AIIA_I18N_ALL_LOCALES
    if (prevApi !== undefined) globalThis.AIIA_I18N = prevApi
    else delete globalThis.AIIA_I18N
  })

  test('i18n runtime: 参数插值 {{param}} 应正确替换', () => {
    const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
    assert.ok(ext, 'Extension not found')

    const i18nPath = path.join(ext.extensionPath, 'i18n.js')
    const enData = JSON.parse(
      fs.readFileSync(path.join(ext.extensionPath, 'locales', 'en.json'), 'utf8')
    )

    const prevLang = globalThis.__AIIA_I18N_LANG
    const prevLocale = globalThis.__AIIA_I18N_LOCALE
    const prevAll = globalThis.__AIIA_I18N_ALL_LOCALES
    const prevApi = globalThis.AIIA_I18N

    globalThis.__AIIA_I18N_LANG = 'en'
    globalThis.__AIIA_I18N_LOCALE = enData
    globalThis.__AIIA_I18N_ALL_LOCALES = { en: enData }

    delete require.cache[require.resolve(i18nPath)]
    require(i18nPath)

    const i18n = globalThis.AIIA_I18N
    assert.ok(i18n)
    i18n.setLang('en')

    // settings.footer.version template is "v{{version}}"
    const versioned = i18n.t('settings.footer.version', { version: '1.5.0' })
    assert.strictEqual(versioned, 'v1.5.0', 'param interpolation must replace {{version}}')

    // ui.countdown.remaining 模板为 "{{seconds}}s remaining"
    const countdown = i18n.t('ui.countdown.remaining', { seconds: 42 })
    assert.ok(
      countdown.includes('42'),
      `参数插值应包含 42，实际结果: "${countdown}"`
    )

    // 清理
    if (prevLang !== undefined) globalThis.__AIIA_I18N_LANG = prevLang
    else delete globalThis.__AIIA_I18N_LANG
    if (prevLocale !== undefined) globalThis.__AIIA_I18N_LOCALE = prevLocale
    else delete globalThis.__AIIA_I18N_LOCALE
    if (prevAll !== undefined) globalThis.__AIIA_I18N_ALL_LOCALES = prevAll
    else delete globalThis.__AIIA_I18N_ALL_LOCALES
    if (prevApi !== undefined) globalThis.AIIA_I18N = prevApi
    else delete globalThis.AIIA_I18N
  })
})
