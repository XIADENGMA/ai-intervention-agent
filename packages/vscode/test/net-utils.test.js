const assert = require('assert')
const { discardResponseBody } = require('../dist/net-utils')

suite('discardResponseBody', function () {
  test('cancels an unread body so the connection can be released', async () => {
    let cancelled = 0
    const resp = new Response(
      new ReadableStream({
        pull(controller) {
          controller.enqueue(new Uint8Array(1024))
        },
        cancel() {
          cancelled += 1
        }
      }),
      { status: 500 }
    )
    discardResponseBody(resp)
    for (let i = 0; i < 20 && cancelled === 0; i++) {
      await new Promise(resolve => setTimeout(resolve, 10))
    }
    assert.strictEqual(cancelled, 1)
  })

  test('tolerates responses without a body, null and malformed shapes', () => {
    assert.doesNotThrow(() => discardResponseBody(null))
    assert.doesNotThrow(() => discardResponseBody(undefined))
    assert.doesNotThrow(() => discardResponseBody({}))
    assert.doesNotThrow(() => discardResponseBody({ body: null }))
    assert.doesNotThrow(() => discardResponseBody({ body: {} }))
    assert.doesNotThrow(() => discardResponseBody(new Response(null, { status: 204 })))
  })

  test('never throws when cancel() throws synchronously or rejects', async () => {
    assert.doesNotThrow(() =>
      discardResponseBody({
        body: {
          cancel() {
            throw new Error('boom')
          }
        }
      })
    )
    let rejected = false
    discardResponseBody({
      body: {
        cancel() {
          rejected = true
          return Promise.reject(new Error('nope'))
        }
      }
    })
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.ok(rejected)
  })

  test('an already locked or consumed body does not surface an unhandled rejection', async () => {
    const unhandled = []
    const onUnhandled = reason => unhandled.push(reason)
    process.on('unhandledRejection', onUnhandled)
    try {
      const resp = new Response('hello')
      await resp.text()
      discardResponseBody(resp)
      const locked = new Response('hello')
      locked.body.getReader()
      discardResponseBody(locked)
      await new Promise(resolve => setTimeout(resolve, 30))
    } finally {
      process.off('unhandledRejection', onUnhandled)
    }
    assert.deepStrictEqual(unhandled, [])
  })
})
