const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vscode = require('vscode')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

/** 获取编译产物中的 applescript-executor.js 路径 */
function getExecutorPath() {
  const ext = getExtension()
  return path.join(ext.extensionPath, 'dist', 'applescript-executor.js')
}

suite('AppleScript Executor', () => {
  test('applescript-executor.js 应随扩展发布（仅 macOS）', () => {
    if (process.platform !== 'darwin') {
      // Linux/Windows CI 不打包 AppleScript 运行时，跳过
      return
    }
    const executorPath = getExecutorPath()
    assert.ok(fs.existsSync(executorPath), `Missing applescript-executor.js: ${executorPath}`)
  })

  test('toAppleScriptStringLiteral 应正确转义引号/反斜杠/换行', () => {
    const executorPath = getExecutorPath()
    const { toAppleScriptStringLiteral } = require(executorPath)

    const lit = toAppleScriptStringLiteral('a"b\\c\nd\t')
    assert.ok(lit.startsWith('"') && lit.endsWith('"'))
    assert.ok(lit.includes('\\"'), 'should escape double quote')
    assert.ok(lit.includes('\\\\'), 'should escape backslash')
    assert.ok(lit.includes('\\n'), 'should escape newline')
    assert.ok(lit.includes('\\t'), 'should escape tab')
  })

  test('非 macOS 平台应返回 Platform not supported，且不触发执行', async () => {
    const executorPath = getExecutorPath()
    const { AppleScriptExecutor } = require(executorPath)

    let execCalled = false
    const executor = new AppleScriptExecutor({
      platform: 'win32',
      execImpl: () => {
        execCalled = true
        throw new Error('should not be called')
      }
    })

    await assert.rejects(executor.runAppleScript('return "ok"'), err => {
      assert.strictEqual(err && err.message ? err.message : String(err), 'Platform not supported')
      return true
    })
    assert.strictEqual(execCalled, false)
  })

  test('stderr 非空时应作为错误抛出', async () => {
    const executorPath = getExecutorPath()
    const { AppleScriptExecutor } = require(executorPath)

    const captured = { file: '', args: null, script: '' }
    const fakeExec = (file, args, _opts, cb) => {
      captured.file = String(file || '')
      captured.args = args
      const child = {
        stdin: {
          on: () => {},
          end: data => {
            captured.script = String(data)
          }
        }
      }
      process.nextTick(() => cb(null, '', 'Some AppleScript error'))
      return child
    }

    const executor = new AppleScriptExecutor({ platform: 'darwin', execImpl: fakeExec })
    await assert.rejects(executor.runAppleScript('return "ok"'), err => {
      assert.strictEqual(err.code, 'APPLE_SCRIPT_STDERR')
      assert.ok(String(err.message).includes('Some AppleScript error'))
      return true
    })
    assert.ok(captured.file.includes('/usr/bin/osascript'))
    assert.ok(Array.isArray(captured.args) && captured.args.includes('-'))
    assert.ok(captured.script.includes('return "ok"'))
  })

  test('成功时应返回 stdout', async () => {
    const executorPath = getExecutorPath()
    const { AppleScriptExecutor } = require(executorPath)

    const fakeExec = (_file, _args, _opts, cb) => {
      const child = { stdin: { on: () => {}, end: () => {} } }
      process.nextTick(() => cb(null, 'ok\n', ''))
      return child
    }

    const executor = new AppleScriptExecutor({ platform: 'darwin', execImpl: fakeExec })
    const out = await executor.runAppleScript('return "ok"')
    assert.strictEqual(out, 'ok\n')
  })

  test('超时应映射为 APPLE_SCRIPT_TIMEOUT', async () => {
    const executorPath = getExecutorPath()
    const { AppleScriptExecutor } = require(executorPath)

    const fakeExec = (_file, _args, _opts, cb) => {
      const child = { stdin: { on: () => {}, end: () => {} } }
      const err = new Error('Command timed out')
      err.killed = true
      err.signal = 'SIGTERM'
      process.nextTick(() => cb(err, '', ''))
      return child
    }

    const executor = new AppleScriptExecutor({ platform: 'darwin', execImpl: fakeExec })
    await assert.rejects(executor.runAppleScript('return "ok"'), err => {
      assert.strictEqual(err.code, 'APPLE_SCRIPT_TIMEOUT')
      return true
    })
  })

  test('失败时应携带 details（exitCode / injectedEnvKeys / stderr 等）', async () => {
    const executorPath = getExecutorPath()
    const { AppleScriptExecutor } = require(executorPath)

    const fakeExec = (_file, _args, _opts, cb) => {
      const child = { stdin: { on: () => {}, end: () => {} } }
      const err = new Error('boom')
      err.code = 2
      process.nextTick(() => cb(err, '', 'stderr text'))
      return child
    }

    const executor = new AppleScriptExecutor({ platform: 'darwin', execImpl: fakeExec })
    await assert.rejects(
      executor.runAppleScript('return "ok"', {
        env: { __CFBundleIdentifier: 'com.example.host', FOO: '1' }
      }),
      err => {
        assert.strictEqual(err.code, 'APPLE_SCRIPT_FAILED')
        assert.ok(err.details && typeof err.details === 'object', 'should attach err.details')
        assert.strictEqual(err.details.exitCode, 2)
        assert.ok(Array.isArray(err.details.injectedEnvKeys))
        assert.ok(err.details.injectedEnvKeys.includes('__CFBundleIdentifier'))
        assert.ok(err.details.injectedEnvKeys.includes('FOO'))
        assert.ok(String(err.details.stderr || '').includes('stderr text'))
        return true
      }
    )
  })
})
