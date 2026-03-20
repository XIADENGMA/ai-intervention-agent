const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vscode = require('vscode')

function getExtension() {
  const ext = vscode.extensions.getExtension('xiadengma.ai-intervention-agent')
  assert.ok(ext, 'Extension not found: xiadengma.ai-intervention-agent')
  return ext
}

suite('AppleScript Executor', () => {
  test('applescript-executor.js 应随扩展发布', () => {
    const ext = getExtension()
    const executorPath = path.join(ext.extensionPath, 'applescript-executor.js')
    assert.ok(fs.existsSync(executorPath), 'Missing applescript-executor.js in extension')
  })

  test('toAppleScriptStringLiteral 应正确转义引号/反斜杠/换行', () => {
    const ext = getExtension()
    const executorPath = path.join(ext.extensionPath, 'applescript-executor.js')
    const { toAppleScriptStringLiteral } = require(executorPath)

    const lit = toAppleScriptStringLiteral('a"b\\c\nd\t')
    assert.ok(lit.startsWith('"') && lit.endsWith('"'))
    assert.ok(lit.includes('\\"'), 'should escape double quote')
    assert.ok(lit.includes('\\\\'), 'should escape backslash')
    assert.ok(lit.includes('\\n'), 'should escape newline')
    assert.ok(lit.includes('\\t'), 'should escape tab')
  })

  test('非 macOS 平台应返回 Platform not supported，且不触发执行', async () => {
    const ext = getExtension()
    const executorPath = path.join(ext.extensionPath, 'applescript-executor.js')
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
    const ext = getExtension()
    const executorPath = path.join(ext.extensionPath, 'applescript-executor.js')
    const { AppleScriptExecutor } = require(executorPath)

    const captured = { cmd: '', script: '' }
    const fakeExec = (cmd, _opts, cb) => {
      captured.cmd = cmd
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
    assert.ok(captured.cmd.includes('/usr/bin/osascript'))
    assert.ok(captured.script.includes('return "ok"'))
  })

  test('成功时应返回 stdout', async () => {
    const ext = getExtension()
    const executorPath = path.join(ext.extensionPath, 'applescript-executor.js')
    const { AppleScriptExecutor } = require(executorPath)

    const fakeExec = (_cmd, _opts, cb) => {
      const child = { stdin: { on: () => {}, end: () => {} } }
      process.nextTick(() => cb(null, 'ok\n', ''))
      return child
    }

    const executor = new AppleScriptExecutor({ platform: 'darwin', execImpl: fakeExec })
    const out = await executor.runAppleScript('return "ok"')
    assert.strictEqual(out, 'ok\n')
  })

  test('超时应映射为 APPLE_SCRIPT_TIMEOUT', async () => {
    const ext = getExtension()
    const executorPath = path.join(ext.extensionPath, 'applescript-executor.js')
    const { AppleScriptExecutor } = require(executorPath)

    const fakeExec = (_cmd, _opts, cb) => {
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
})

