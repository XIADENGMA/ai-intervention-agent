const assert = require('assert')
const { SSE_MAX_BUFFER_CHARS, SseBufferOverflowError, SseParser } = require('../dist/sse-parser')

function legacyParse(stream, chunkSizes) {
  const events = []
  let buffer = ''
  let pendingId = null
  let pendingType = null
  let pendingDataLines = []
  const flush = () => {
    if (pendingDataLines.length === 0 && pendingType === null && pendingId === null) return
    events.push({ id: pendingId, type: pendingType, data: pendingDataLines.join('\n') })
    pendingId = null
    pendingType = null
    pendingDataLines = []
  }
  let offset = 0
  let sizeIndex = 0
  while (offset < stream.length) {
    const size = chunkSizes[sizeIndex % chunkSizes.length]
    sizeIndex += 1
    const chunk = stream.slice(offset, offset + size)
    offset += size
    buffer += chunk
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line === '') {
        flush()
        continue
      }
      if (line.startsWith(':')) continue
      if (line.startsWith('id:')) {
        pendingId = line.slice(3).replace(/^\s+/, '')
        continue
      }
      if (line.startsWith('event:')) {
        pendingType = line.slice(6).replace(/^\s+/, '')
        continue
      }
      if (line.startsWith('data:')) {
        pendingDataLines.push(line.slice(5).replace(/^\s/, ''))
        continue
      }
    }
  }
  return events
}

function parseWith(stream, chunkSizes, maxChars) {
  const events = []
  const parser = new SseParser(ev => events.push(ev), maxChars)
  let offset = 0
  let sizeIndex = 0
  while (offset < stream.length) {
    const size = chunkSizes[sizeIndex % chunkSizes.length]
    sizeIndex += 1
    parser.push(stream.slice(offset, offset + size))
    offset += size
  }
  return events
}

function mulberry32(seed) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function randomStream(rand, eventCount) {
  const pieces = []
  const types = ['task_changed', 'heartbeat', 'config_changed', 'gap_warning', 'weird', '']
  for (let i = 0; i < eventCount; i++) {
    const kind = rand()
    if (kind < 0.12) pieces.push(': comment ' + i + '\n')
    if (kind > 0.9) pieces.push('\n')
    if (rand() < 0.7) pieces.push('id: ' + (i + 1) + '\n')
    if (rand() < 0.8) pieces.push('event:' + (rand() < 0.5 ? ' ' : '') + types[Math.floor(rand() * types.length)] + '\n')
    const dataLines = Math.floor(rand() * 4)
    for (let d = 0; d < dataLines; d++) {
      pieces.push('data:' + (rand() < 0.5 ? ' ' : '') + JSON.stringify({ n: i, d, pad: 'é'.repeat(Math.floor(rand() * 5)) }) + '\n')
    }
    if (rand() < 0.1) pieces.push('retry: 3000\n')
    pieces.push('\n')
  }
  return pieces.join('')
}

suite('SSE parser', function () {
  test('parses id / event / multi-line data and ignores comments', () => {
    const events = parseWith(
      ': hello\n\nid: 7\nevent: task_changed\ndata: {"a":1}\ndata: second\n\n: ping\n\nevent: heartbeat\n\n',
      [1000]
    )
    assert.deepStrictEqual(events, [
      { id: '7', type: 'task_changed', data: '{"a":1}\nsecond' },
      { id: null, type: 'heartbeat', data: '' }
    ])
  })

  test('is invariant to chunk boundaries and matches the legacy split-based parser', () => {
    const rand = mulberry32(20261019)
    for (let round = 0; round < 60; round++) {
      const stream = randomStream(rand, 40)
      const whole = legacyParse(stream, [stream.length + 1])
      for (const sizes of [[1], [2], [3, 5, 7], [64], [stream.length + 1]]) {
        assert.deepStrictEqual(parseWith(stream, sizes), whole, `round ${round} sizes ${sizes}`)
        assert.deepStrictEqual(legacyParse(stream, sizes), whole, `legacy round ${round} sizes ${sizes}`)
      }
    }
  })

  test('a line of exactly the limit is accepted, one char more overflows', () => {
    const max = 1000
    const okLine = 'data: ' + 'x'.repeat(max - 6)
    assert.strictEqual(okLine.length, max)
    const events = parseWith(okLine + '\n\n', [97], max)
    assert.strictEqual(events.length, 1)

    const parser = new SseParser(() => {}, max)
    assert.throws(
      () => {
        parser.push('data: ' + 'x'.repeat(max - 5))
        parser.push('\n')
      },
      err => err instanceof SseBufferOverflowError && err.limit === max
    )
  })

  test('an unterminated line overflows as soon as it passes the limit', () => {
    const max = 4096
    const parser = new SseParser(() => {}, max)
    let pushed = 0
    assert.throws(() => {
      for (;;) {
        parser.push('z'.repeat(512))
        pushed += 512
        assert.ok(pushed <= max + 512, 'parser kept buffering past the limit')
      }
    }, SseBufferOverflowError)
    assert.ok(pushed >= max - 512)
  })

  test('a complete over-long line inside a single chunk overflows too', () => {
    const parser = new SseParser(() => {}, 100)
    assert.throws(() => parser.push('data: ' + 'y'.repeat(500) + '\n'), SseBufferOverflowError)
  })

  test('many small data lines of one event are bounded as a whole', () => {
    const max = 1000
    const parser = new SseParser(() => {}, max)
    assert.throws(() => {
      for (let i = 0; i < 1000; i++) parser.push('data: ' + 'q'.repeat(50) + '\n')
    }, SseBufferOverflowError)
  })

  test('state is released after every event (no accumulation across events)', () => {
    const max = 1000
    const events = []
    const parser = new SseParser(ev => events.push(ev), max)
    for (let i = 0; i < 500; i++) parser.push('data: ' + 'k'.repeat(400) + '\n\n')
    assert.strictEqual(events.length, 500)
  })

  test('default limit stays at 1 MiB', () => {
    assert.strictEqual(SSE_MAX_BUFFER_CHARS, 1024 * 1024)
  })

  test('hostile 64 MiB line is rejected in linear time without buffering it', () => {
    const parser = new SseParser(() => {})
    const chunk = 'z'.repeat(64 * 1024)
    const started = process.hrtime.bigint()
    let pushedChunks = 0
    assert.throws(() => {
      parser.push('data: ')
      for (let i = 0; i < 1024; i++) {
        parser.push(chunk)
        pushedChunks += 1
      }
    }, SseBufferOverflowError)
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6
    assert.ok(pushedChunks <= SSE_MAX_BUFFER_CHARS / chunk.length + 1, `accepted ${pushedChunks} chunks`)
    assert.ok(elapsedMs < 500, `took ${elapsedMs.toFixed(1)} ms`)
  })

  test('a long unterminated line built from tiny chunks costs linear time', () => {
    const events = []
    const parser = new SseParser(ev => events.push(ev))
    const started = process.hrtime.bigint()
    parser.push('data: ')
    for (let i = 0; i < 900000; i++) parser.push('a')
    parser.push('\n\n')
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6
    assert.strictEqual(events.length, 1)
    assert.strictEqual(events[0].data.length, 900000)
    assert.ok(elapsedMs < 1000, `took ${elapsedMs.toFixed(1)} ms`)
  })

  test('a long well-formed stream of small events parses in linear time', () => {
    const events = []
    const parser = new SseParser(ev => events.push(ev))
    const frame = 'id: 1\nevent: task_changed\ndata: {"task_id":"t","new_status":"active"}\n\n'
    const chunk = frame.repeat(500)
    const started = process.hrtime.bigint()
    for (let i = 0; i < 200; i++) parser.push(chunk)
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6
    assert.strictEqual(events.length, 100000)
    assert.ok(elapsedMs < 3000, `took ${elapsedMs.toFixed(1)} ms`)
  })
})
