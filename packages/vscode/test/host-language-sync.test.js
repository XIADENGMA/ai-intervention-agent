const assert = require('assert')
const http = require('http')
const vscode = require('vscode')

const EXTENSION_ID = 'xiadengma.ai-intervention-agent'

function startFakeWebUi() {
  const state = {
    language: 'zh-TW',
    configRequests: 0,
    eventRequests: 0,
    sseResponses: []
  }
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1')
    if (url.pathname === '/api/events') {
      state.eventRequests += 1
      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive'
      })
      res.write(': connected\n\n')
      state.sseResponses.push(res)
      req.on('close', () => {
        state.sseResponses = state.sseResponses.filter(r => r !== res)
      })
      return
    }
    if (url.pathname === '/api/config') {
      state.configRequests += 1
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ language: state.language }))
      return
    }
    if (url.pathname === '/api/tasks') {
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

suite('Extension host language sync (real SSE)', function () {
  this.timeout(30000)

  test('host re-reads the server language when SSE connects and on config_changed', async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID)
    assert.ok(ext, `Extension not found: ${EXTENSION_ID}`)

    const fake = await startFakeWebUi()
    const cfg = vscode.workspace.getConfiguration('ai-intervention-agent')
    const inspected = cfg.inspect('serverUrl')
    const previous = inspected ? inspected.globalValue : undefined

    try {
      await ext.activate()
      await cfg.update(
        'serverUrl',
        `http://127.0.0.1:${fake.port}`,
        vscode.ConfigurationTarget.Global
      )

      await waitFor(
        () => fake.state.eventRequests >= 1,
        'the extension host never opened the SSE stream on the new serverUrl'
      )
      await waitFor(
        () => fake.state.configRequests >= 1,
        'the extension host did not re-read /api/config after the SSE stream connected ' +
          '(status bar would never follow the server language while the sidebar is closed)'
      )

      const afterConnect = fake.state.configRequests
      fake.state.language = 'en'
      assert.ok(fake.state.sseResponses.length >= 1, 'no live SSE stream to push the event on')
      for (const res of fake.state.sseResponses) {
        res.write('event: config_changed\ndata: {"hint":"changed"}\n\n')
      }
      await waitFor(
        () => fake.state.configRequests > afterConnect,
        'the extension host did not re-read /api/config after a config_changed event'
      )
    } finally {
      await cfg.update('serverUrl', previous, vscode.ConfigurationTarget.Global)
      for (const res of fake.state.sseResponses) {
        try {
          res.end()
        } catch {
          // ignore: the stream may already be closed
        }
      }
      await new Promise(resolve => {
        fake.server.close(() => resolve())
        if (typeof fake.server.closeAllConnections === 'function') {
          fake.server.closeAllConnections()
        }
      })
    }
  })
})
