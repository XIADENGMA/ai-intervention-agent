const assert = require('assert')
const http = require('http')
const vscode = require('vscode')

const EXTENSION_ID = 'xiadengma.ai-intervention-agent'
const MIB = 1024 * 1024

function startFakeWebUi(initial = {}) {
  const state = {
    sseMode: 'ok',
    tasksMode: 'ok',
    eventConnects: [],
    taskRequests: 0,
    hugeLineStreams: [],
    errorBodies: [],
    sseResponses: [],
    ...initial
  }
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1')
    if (url.pathname === '/api/events') {
      state.eventConnects.push(Date.now())
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive'
      })
      res.write(': connected\n\n')
      res.on('error', () => {})
      state.sseResponses.push(res)
      req.on('close', () => {
        state.sseResponses = state.sseResponses.filter(r => r !== res)
      })
      if (state.sseMode === 'flap') {
        setTimeout(() => {
          try {
            res.end()
          } catch {

          }
        }, 30)
      } else if (state.sseMode === 'huge-line') {
        const stream = { sent: 0, closed: false }
        state.hugeLineStreams.push(stream)
        const chunk = 'x'.repeat(64 * 1024)
        res.write('data: ')
        const timer = setInterval(() => {
          if (stream.closed || stream.sent >= 16 * MIB) {
            clearInterval(timer)
            return
          }
          stream.sent += chunk.length
          res.write(chunk)
        }, 5)
        req.on('close', () => {
          stream.closed = true
          clearInterval(timer)
        })
      }
      return
    }
    if (url.pathname === '/api/tasks') {
      state.taskRequests += 1
      if (state.tasksMode === 'error') {
        res.writeHead(500, { 'Content-Type': 'application/json' })
        res.end('{"error":"boom"}')
        return
      }
      if (state.tasksMode === 'error-big-body') {
        const body = { sent: 0, ended: false, closedAt: 0, startedAt: Date.now() }
        state.errorBodies.push(body)
        res.writeHead(500, { 'Content-Type': 'application/json' })
        res.write('{"error":"')
        const chunk = 'x'.repeat(64 * 1024)
        const pump = () => {
          while (!res.destroyed && body.sent < 8 * MIB) {
            body.sent += chunk.length
            if (!res.write(chunk)) {
              res.once('drain', pump)
              return
            }
          }
          if (res.destroyed) return
          body.ended = true
          res.end('"}')
        }
        res.on('error', () => {})
        res.on('close', () => {
          body.closedAt = Date.now()
        })
        pump()
        return
      }
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(
        JSON.stringify({
          success: true,
          tasks: [],
          stats: { total: 0, pending: 0, active: 0, completed: 0 }
        })
      )
      return
    }
    if (url.pathname === '/api/config') {
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ language: 'en' }))
      return
    }
    res.writeHead(404, { 'Content-Type': 'application/json' })
    res.end('{}')
  })
  return new Promise(resolve => {
    server.listen(0, '127.0.0.1', () => {
      resolve({ server, state, port: server.address().port })
    })
  })
}

async function waitFor(predicate, message, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (predicate()) return
    await new Promise(resolve => setTimeout(resolve, 25))
  }
  assert.fail(message)
}

async function withFakeWebUi(initial, body) {
  const ext = vscode.extensions.getExtension(EXTENSION_ID)
  assert.ok(ext, `Extension not found: ${EXTENSION_ID}`)
  const fake = await startFakeWebUi(initial)
  const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
  const inspected = cfg.inspect('serverUrl')
  const previous = inspected ? inspected.globalValue : undefined
  try {
    await ext.activate()
    await body(fake, cfg)
  } finally {
    await cfg.update('serverUrl', previous, vscode.ConfigurationTarget.Global)
    for (const res of fake.state.sseResponses) {
      try {
        res.destroy()
      } catch {

      }
    }
    await new Promise(resolve => {
      fake.server.close(() => resolve())
      if (typeof fake.server.closeAllConnections === 'function') {
        fake.server.closeAllConnections()
      }
    })
  }
}

suite('Extension host SSE / HTTP hardening (real extension host)', function () {
  this.timeout(60000)

  test('an SSE line that never ends is cut off at the buffer limit, then the stream reconnects', async () => {
    await withFakeWebUi({ sseMode: 'huge-line' }, async (fake, cfg) => {
      await cfg.update('serverUrl', `http://127.0.0.1:${fake.port}`, vscode.ConfigurationTarget.Global)
      await waitFor(() => fake.state.hugeLineStreams.length >= 1, 'no SSE connection was opened')
      const first = fake.state.hugeLineStreams[0]
      await waitFor(
        () => first.closed,
        'the extension host kept buffering an unterminated SSE line instead of dropping the connection'
      )
      assert.ok(
        first.sent < 4 * MIB,
        `the host accepted ${(first.sent / MIB).toFixed(1)} MiB of a single SSE line (limit is 1 MiB)`
      )
      fake.state.sseMode = 'ok'
      await waitFor(
        () => fake.state.eventConnects.length >= 2,
        'the extension host did not reconnect after dropping the hostile stream',
        8000
      )
    })
  })

  test('reconnect backoff keeps growing while the stream flaps instead of resetting on every 200', async () => {
    await withFakeWebUi({ sseMode: 'flap', tasksMode: 'error' }, async (fake, cfg) => {
      await cfg.update('serverUrl', `http://127.0.0.1:${fake.port}`, vscode.ConfigurationTarget.Global)
      await waitFor(() => fake.state.eventConnects.length >= 1, 'no SSE connection was opened')
      const startedAt = fake.state.eventConnects[0]
      await new Promise(resolve => setTimeout(resolve, 12000 - (Date.now() - startedAt)))
      const connects = fake.state.eventConnects.filter(t => t - startedAt <= 12000).length
      assert.ok(connects >= 3, `expected the host to keep retrying, saw ${connects} connects in 12 s`)
      assert.ok(
        connects <= 6,
        `a flapping stream was re-opened ${connects} times in 12 s; the backoff is being reset on every 200`
      )
    })
  })

  test('a non-OK /api/tasks response has its body cancelled instead of left open', async () => {
    await withFakeWebUi({ sseMode: 'ok', tasksMode: 'error-big-body' }, async (fake, cfg) => {
      await cfg.update('serverUrl', `http://127.0.0.1:${fake.port}`, vscode.ConfigurationTarget.Global)
      await waitFor(() => fake.state.errorBodies.length >= 1, 'the host never polled /api/tasks')
      const body = fake.state.errorBodies[0]
      await waitFor(
        () => body.closedAt > 0,
        'the host left the error response open (neither read nor cancelled)',
        5000
      )
      assert.strictEqual(body.ended, false, 'the whole error body was transferred before the host closed it')
      assert.ok(body.sent < 4 * MIB, `host let ${(body.sent / MIB).toFixed(1)} MiB of an error body through`)
      assert.ok(body.closedAt - body.startedAt < 2000, 'error body was released too slowly')
    })
  })
})
