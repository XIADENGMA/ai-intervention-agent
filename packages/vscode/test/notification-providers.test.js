const assert = require('assert')
const path = require('path')
const vscode = require('vscode')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

/** 获取编译产物中的模块路径 */
function distPath(filename) {
  return path.join(getExtension().extensionPath, 'dist', filename)
}

suite('Notification Providers (VSCode)', () => {
  test('VSCodeApiNotificationProvider 默认走状态栏提示', async () => {
    const { VSCodeApiNotificationProvider } = require(distPath('notification-providers.js'))

    let lastText = ''
    let lastTimeout = null
    const stubVscode = {
      window: {
        setStatusBarMessage: (text, timeout) => {
          lastText = String(text)
          lastTimeout = timeout
        }
      }
    }

    const provider = new VSCodeApiNotificationProvider({ vscodeApi: stubVscode })
    const ok = await provider.send({
      title: 'AI Intervention Agent',
      message: 'hello',
      metadata: { timeoutMs: 1234 }
    })
    assert.strictEqual(ok, true)
    assert.ok(lastText.includes('hello'))
    assert.strictEqual(lastTimeout, 1234)
  })

  test('AppleScriptNotificationProvider 不应依赖 enableAppleScript（原生通知默认开启）', async () => {
    const { AppleScriptNotificationProvider } = require(distPath('notification-providers.js'))

    let shownError = ''
    const stubVscode = {
      window: {
        showErrorMessage: msg => {
          shownError = String(msg)
        }
      }
    }

    let called = 0
    const executor = {
      runAppleScript: async () => {
        called += 1
        return ''
      }
    }

    const provider = new AppleScriptNotificationProvider({ executor, vscodeApi: stubVscode })

    // isTest=true：允许在任意平台注入 executor 做行为验证
    const ok = await provider.send({
      title: 't',
      message: 'm',
      metadata: { isTest: true }
    })
    assert.strictEqual(ok, true)
    assert.strictEqual(called, 1)
    assert.strictEqual(shownError, '')
  })

  test('AppleScriptNotificationProvider 注入 bundleId 失败时应回退为不注入重试', async () => {
    const { AppleScriptNotificationProvider } = require(distPath('notification-providers.js'))

    let shownError = ''
    const stubVscode = {
      window: {
        showErrorMessage: msg => {
          shownError = String(msg)
        }
      },
      env: { appName: 'Visual Studio Code' }
    }

    const calls = []
    const executor = {
      runAppleScript: async (script, opts) => {
        calls.push({
          script: String(script || ''),
          hasInjectedBundleId: !!(opts && opts.env && opts.env.__CFBundleIdentifier),
          injectedBundleId:
            opts && opts.env && opts.env.__CFBundleIdentifier ? String(opts.env.__CFBundleIdentifier) : ''
        })
        if (opts && opts.env && opts.env.__CFBundleIdentifier) {
          const err = new Error('fail injected')
          err.code = 'APPLE_SCRIPT_FAILED'
          err.details = {
            stderr: 'injected fail',
            exitCode: 1,
            signal: '',
            injectedEnvKeys: ['__CFBundleIdentifier'],
            durationMs: 1
          }
          throw err
        }
        return ''
      }
    }

    const provider = new AppleScriptNotificationProvider({ executor, vscodeApi: stubVscode })
    // 用 monkey patch 保证跨平台也能覆盖注入逻辑
    provider._resolveHostBundleId = async () => 'com.example.host'

    const ok = await provider.send({
      title: 't',
      message: 'm',
      metadata: { isTest: true, diagnostic: true }
    })
    assert.strictEqual(ok, true)
    assert.strictEqual(shownError, '')
    assert.strictEqual(calls.length, 2)
    assert.strictEqual(calls[0].hasInjectedBundleId, true)
    assert.strictEqual(calls[0].injectedBundleId, 'com.example.host')
    assert.strictEqual(calls[1].hasInjectedBundleId, false)
  })

  test('AppleScriptNotificationProvider 失败应保存诊断信息，且 diagnostic 模式不弹窗', async () => {
    const { AppleScriptNotificationProvider } = require(distPath('notification-providers.js'))

    let shownError = ''
    const stubVscode = {
      window: {
        showErrorMessage: msg => {
          shownError = String(msg)
        }
      },
      env: { appName: 'Visual Studio Code' }
    }

    const executor = {
      runAppleScript: async (_script, opts) => {
        const isInjected = !!(opts && opts.env && opts.env.__CFBundleIdentifier)
        const err = new Error(isInjected ? 'fail primary' : 'fail fallback')
        err.code = 'APPLE_SCRIPT_FAILED'
        err.details = {
          stderr: isInjected ? 'stderr_primary' : 'stderr_fallback',
          exitCode: 1,
          signal: '',
          injectedEnvKeys: isInjected ? ['__CFBundleIdentifier'] : [],
          durationMs: 2
        }
        throw err
      }
    }

    const provider = new AppleScriptNotificationProvider({ executor, vscodeApi: stubVscode })
    provider._resolveHostBundleId = async () => 'com.example.host'

    const ok = await provider.send({
      title: 't',
      message: 'm',
      metadata: { isTest: true, diagnostic: true }
    })
    assert.strictEqual(ok, false)
    // diagnostic 模式：UI 错误提示应由 extension.js 统一展示，这里不应弹窗
    assert.strictEqual(shownError, '')

    const diag = provider.getLastDiagnostic()
    assert.ok(diag && typeof diag === 'object', 'should store last diagnostic')
    assert.ok(diag.primary && typeof diag.primary === 'object', 'should keep primary attempt info')
    assert.ok(diag.fallback && typeof diag.fallback === 'object', 'should keep fallback attempt info')
    assert.ok(String(diag.primary.stderrPreview || '').includes('stderr_primary'))
    assert.ok(String(diag.fallback.stderrPreview || '').includes('stderr_fallback'))
  })
})

// terminal-notifier 2.0.0 (the binary bundled under vendor/) reads the value of -title / -message
// through NSUserDefaults' command-line argument parser. Measured on the real binary, one first
// character at a time over every printable ASCII character:
//   - a -message that starts with  [  (  {  <  "  -  is read as "no message", and the binary then
//     waits for one on its standard input; execFile gives it a pipe that never closes, so it hangs
//     until the provider's 2.5 s timeout kills it and the AppleScript fallback shows the banner
//     2.5 s late, by another notification path and with another sound;
//   - a value that is nothing but a property list ( ()  {}  (x) ) hangs the same way;
//   - a -title read as "no title" becomes the default title, "Terminal";
//   - a value that starts with a backslash loses it.
// The summary of a request is the first 120 characters of what the AI asked, and AI questions often
// start exactly like that: "- item", "[x] done", "(1) first", '"quoted" ...'.
const TEXTS_THE_BINARY_MISREADS = [
  '[Plan] next steps',
  '[x] done',
  '(1) first',
  '(R823) fixed',
  '{x} y',
  '<think> abc',
  '"quoted" start',
  '- item one',
  '- [ ] todo',
  '-flag',
  '--',
  '\\path\\n',
  '\\"quote',
  '[',
  '(',
  '{',
  '<',
  '"',
  '-',
  '\\',
  '()',
  '{}',
  '(x)',
  '[]',
  '<abc>',
  '(a, b) tail',
  '{a = b;}'
]

// Starts the binary reads correctly today; they must come out the same after the change.
const TEXTS_THE_BINARY_READS_RIGHT = [
  'plain text',
  'Done: 3 files changed',
  '\u4e2d\u6587\u5f00\u5934\uff0c\u7ee7\u7eed',
  '\u{1F642} emoji first',
  '\u3010\u8ba1\u5212\u3011 full-width bracket',
  'say "hi"',
  'a = b;',
  '# heading',
  '> quote',
  '**bold** text',
  '$HOME `x`',
  '/path/to/file',
  "'single' quoted",
  '1. first item',
  '...and more',
  ')',
  ']',
  '}',
  '>'
]

suite('MacOSNativeNotificationProvider values for terminal-notifier (R824)', function () {
  const childProcess = require('child_process')

  function loadProviders() {
    return require(distPath('notification-providers.js'))
  }

  /** Runs `send` with child_process.execFile replaced, on a provider that already knows its binary. */
  async function sendWithFakeExecFile(event, { failWith = null, bundleId = '' } = {}) {
    const { MacOSNativeNotificationProvider } = loadProviders()
    const calls = []
    const appleScripts = []
    const realExecFile = childProcess.execFile
    childProcess.execFile = (file, args, options, callback) => {
      calls.push({ file, args: Array.from(args) })
      setImmediate(() => {
        if (failWith) callback(failWith, '', String(failWith.message))
        else callback(null, '', '')
      })
      return { kill() {}, on() {} }
    }
    try {
      const provider = new MacOSNativeNotificationProvider({
        executor: {
          runAppleScript: async script => {
            appleScripts.push(String(script))
            return ''
          }
        },
        vscodeApi: { env: {} }
      })
      provider._terminalNotifierBin = '/fake/terminal-notifier'
      if (bundleId) provider._appleScriptProvider._resolveHostBundleId = async () => bundleId
      const ok = await provider.send(event)
      return { ok, calls, appleScripts }
    } finally {
      childProcess.execFile = realExecFile
    }
  }

  test('escapeTerminalNotifierValue puts one backslash in front of any value', () => {
    const { escapeTerminalNotifierValue } = loadProviders()
    assert.strictEqual(typeof escapeTerminalNotifierValue, 'function')
    for (const text of [...TEXTS_THE_BINARY_MISREADS, ...TEXTS_THE_BINARY_READS_RIGHT]) {
      const escaped = escapeTerminalNotifierValue(text)
      assert.strictEqual(escaped, '\\' + text, `value ${JSON.stringify(text)}`)
      // the parser must see a backslash first, never one of its own punctuation marks
      assert.strictEqual(escaped[0], '\\', `value ${JSON.stringify(text)}`)
    }
  })

  test('send hands terminal-notifier an escaped title and an escaped message', async function () {
    if (process.platform !== 'darwin') this.skip()
    for (const text of [...TEXTS_THE_BINARY_MISREADS, ...TEXTS_THE_BINARY_READS_RIGHT]) {
      const { ok, calls } = await sendWithFakeExecFile({
        title: '[Plan] ' + text,
        message: text,
        metadata: {}
      })
      assert.strictEqual(ok, true, `value ${JSON.stringify(text)}`)
      assert.strictEqual(calls.length, 1, `value ${JSON.stringify(text)}`)
      assert.strictEqual(calls[0].file, '/fake/terminal-notifier')
      assert.deepStrictEqual(
        calls[0].args,
        ['-title', '\\[Plan] ' + text, '-message', '\\' + text, '-sound', 'default'],
        `value ${JSON.stringify(text)}`
      )
    }
  })

  test('send keeps the default title and escapes it as well', async function () {
    if (process.platform !== 'darwin') this.skip()
    const { calls } = await sendWithFakeExecFile({ message: '(1) first', metadata: {} })
    assert.strictEqual(calls.length, 1)
    assert.deepStrictEqual(calls[0].args.slice(0, 4), [
      '-title',
      '\\AI Intervention Agent',
      '-message',
      '\\(1) first'
    ])
  })

  test('send leaves -sound, -activate and -execute alone', async function () {
    if (process.platform !== 'darwin') this.skip()
    const { calls } = await sendWithFakeExecFile(
      { title: 'T', message: '- item', metadata: {} },
      { bundleId: 'com.example.host' }
    )
    assert.strictEqual(calls.length, 1)
    assert.deepStrictEqual(calls[0].args, [
      '-title',
      '\\T',
      '-message',
      '\\- item',
      '-sound',
      'default',
      '-activate',
      'com.example.host',
      '-execute',
      'osascript -e "tell application id \\"com.example.host\\"" -e "reopen" -e "activate" -e "end tell"'
    ])
  })

  test('the AppleScript fallback still gets the text as it was, not the escaped one', async function () {
    if (process.platform !== 'darwin') this.skip()
    const { toAppleScriptStringLiteral } = require(distPath('applescript-executor.js'))
    for (const text of ['[Plan] next steps', '"quoted" start', '\\path', '- item']) {
      const failure = Object.assign(new Error('terminal-notifier failed'), { code: 1 })
      const { ok, calls, appleScripts } = await sendWithFakeExecFile(
        { title: '(T) title', message: text, metadata: {} },
        { failWith: failure }
      )
      assert.strictEqual(ok, true, `value ${JSON.stringify(text)}`)
      assert.strictEqual(calls.length, 1)
      assert.strictEqual(appleScripts.length, 1, `value ${JSON.stringify(text)}`)
      assert.ok(
        appleScripts[0].includes(
          `display notification ${toAppleScriptStringLiteral(text)} with title ${toAppleScriptStringLiteral('(T) title')}`
        ),
        `value ${JSON.stringify(text)}: ${appleScripts[0]}`
      )
    }
  })

  // The two tests below run the real binary and post (then remove) a banner for each text, so they
  // only run when asked for: AIIA_REAL_TERMINAL_NOTIFIER=1 npm run vscode:test
  // They are what to run again after the bundled terminal-notifier is replaced by another version.
  const realBinary = process.platform === 'darwin' && process.env.AIIA_REAL_TERMINAL_NOTIFIER === '1'
  const realTest = realBinary ? test : test.skip

  function realBinaryPath() {
    return path.join(
      getExtension().extensionPath,
      'vendor',
      'terminal-notifier',
      'terminal-notifier.app',
      'Contents',
      'MacOS',
      'terminal-notifier'
    )
  }

  /** Runs the binary the way the provider does: execFile (a pipe on stdin that stays open) and a 2.5 s timeout. */
  function runBinary(bin, args) {
    return new Promise(resolve => {
      childProcess.execFile(bin, args, { timeout: 2500, encoding: 'utf8' }, (error, stdout) => {
        resolve({
          hung: !!(error && error.killed),
          status: error ? (typeof error.code === 'number' ? error.code : null) : 0,
          stdout: String(stdout || '')
        })
      })
    })
  }

  /** Posts one banner with the given -message argument and returns what the notification centre holds. */
  async function postedBanner(messageArg) {
    const bin = realBinaryPath()
    const group = `aiia-r824-test-${process.pid}`
    const { spawnSync } = childProcess
    try {
      spawnSync(bin, ['-remove', group], { input: '', timeout: 5000 })
      const posted = await runBinary(bin, [
        '-title',
        'AIIA R824 probe (ignore)',
        '-message',
        messageArg,
        '-group',
        group
      ])
      await new Promise(resolve => setTimeout(resolve, 250))
      const listed = spawnSync(bin, ['-list', group], { input: '', encoding: 'utf8', timeout: 5000 })
      const cells = (String(listed.stdout || '').split('\n')[1] || '').split('\t')
      return { hung: posted.hung, status: posted.status, message: cells.length >= 5 ? cells[3] : null }
    } finally {
      spawnSync(bin, ['-remove', group], { input: '', timeout: 5000 })
    }
  }

  realTest('the bundled binary shows every escaped text as it is, at once', async function () {
    this.timeout(300000)
    const { escapeTerminalNotifierValue } = loadProviders()
    const wrong = []
    for (const text of [...TEXTS_THE_BINARY_MISREADS, ...TEXTS_THE_BINARY_READS_RIGHT]) {
      const got = await postedBanner(escapeTerminalNotifierValue(text))
      if (got.hung || got.status !== 0 || got.message !== text) wrong.push({ text, got })
    }
    assert.deepStrictEqual(wrong, [])
  })

  realTest('the bundled binary still misreads these texts when they are not escaped', async function () {
    this.timeout(300000)
    // If this fails, a newer terminal-notifier reads them right and the escaping can go.
    const onePerKind = ['[x] done', '(1) first', '{x} y', '<think> abc', '"quoted" start', '- item one', '\\path\\n', '()']
    const readRight = []
    for (const text of onePerKind) {
      const got = await postedBanner(text)
      if (!got.hung && got.status === 0 && got.message === text) readRight.push(text)
    }
    assert.deepStrictEqual(readRight, [])
  })
})
