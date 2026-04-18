/*!
 * ai-intervention-agent · 统一状态机（Web UI 端）
 *
 * 设计：
 *   - Python 源头：state_machine.py（ConnectionStatus / ContentStatus / InteractionPhase）
 *   - 本文件以 IIFE 形式挂到 window.AIIAState，常量名与字符串值保持完全一致
 *   - 常量同步由 tests/test_state_machine.py 正则抓取回归护栏
 *
 * 使用：
 *   var conn = window.AIIAState.createMachine('connection', 'idle')
 *   conn.onChange(function(prev, next){ console.log(prev, '->', next) })
 *   conn.transition('connecting')
 *   conn.is('connected')       // boolean
 *   conn.status                // 当前状态字符串
 *
 * 注意：
 *   - 非法迁移会抛 InvalidTransition 异常；调用方应 try/catch 或先用 canTransition() 判断
 *   - 状态字符串是契约的一部分，不要直接拼接 UI 文案，用 i18n key 映射
 */
;(function (global) {
  'use strict'

  var ConnectionStatus = Object.freeze({
    IDLE: 'idle',
    CONNECTING: 'connecting',
    CONNECTED: 'connected',
    DISCONNECTED: 'disconnected',
    RETRYING: 'retrying',
    CLOSED: 'closed'
  })

  var ContentStatus = Object.freeze({
    SKELETON: 'skeleton',
    LOADING: 'loading',
    READY: 'ready',
    EMPTY: 'empty',
    ERROR: 'error'
  })

  var InteractionPhase = Object.freeze({
    VIEWING: 'viewing',
    COMPOSING: 'composing',
    SUBMITTING: 'submitting',
    COOLDOWN: 'cooldown'
  })

  // 合法迁移表（必须与 state_machine.py 的 TRANSITIONS 保持一致）
  var TRANSITIONS = Object.freeze({
    connection: Object.freeze({
      idle: ['connecting', 'closed'],
      connecting: ['connected', 'disconnected', 'closed'],
      connected: ['disconnected', 'closed'],
      disconnected: ['retrying', 'closed'],
      retrying: ['connecting', 'closed'],
      closed: ['idle']
    }),
    content: Object.freeze({
      skeleton: ['loading', 'ready'],
      loading: ['ready', 'empty', 'error'],
      ready: ['loading', 'empty', 'error'],
      empty: ['loading', 'ready'],
      error: ['loading', 'skeleton']
    }),
    interaction: Object.freeze({
      viewing: ['composing'],
      composing: ['viewing', 'submitting'],
      submitting: ['cooldown', 'composing'],
      cooldown: ['viewing', 'composing']
    })
  })

  function InvalidTransition(msg) {
    this.name = 'InvalidTransition'
    this.message = msg || 'invalid state transition'
  }
  InvalidTransition.prototype = Object.create(Error.prototype)
  InvalidTransition.prototype.constructor = InvalidTransition

  function createMachine(kind, initial) {
    var rules = TRANSITIONS[kind]
    if (!rules) throw new Error('AIIAState: unknown state machine ' + kind)
    if (!Object.prototype.hasOwnProperty.call(rules, initial)) {
      throw new Error('AIIAState: ' + kind + ' initial state ' + initial + ' is invalid')
    }

    var status = initial
    var listeners = []

    function canTransition(target) {
      if (target === status) return true
      var allowed = rules[status] || []
      return allowed.indexOf(target) !== -1
    }

    function transition(target) {
      if (target === status) return
      if (!canTransition(target)) {
        throw new InvalidTransition(
          kind + ': ' + status + ' -> ' + target +
          ' is not allowed; allowed: ' + JSON.stringify(rules[status] || [])
        )
      }
      var previous = status
      status = target
      for (var i = 0; i < listeners.length; i++) {
        try { listeners[i](previous, status) } catch (_) { /* noop */ }
      }
    }

    function onChange(cb) {
      if (typeof cb !== 'function') return function () {}
      listeners.push(cb)
      return function unsubscribe() {
        var idx = listeners.indexOf(cb)
        if (idx >= 0) listeners.splice(idx, 1)
      }
    }

    function is(target) {
      return status === target
    }

    function reset(to) {
      if (!Object.prototype.hasOwnProperty.call(rules, to)) {
        throw new Error('AIIAState: ' + kind + ' reset target ' + to + ' is invalid')
      }
      status = to
    }

    return Object.freeze({
      kind: kind,
      get status() { return status },
      is: is,
      canTransition: canTransition,
      transition: transition,
      onChange: onChange,
      reset: reset
    })
  }

  var api = Object.freeze({
    ConnectionStatus: ConnectionStatus,
    ContentStatus: ContentStatus,
    InteractionPhase: InteractionPhase,
    TRANSITIONS: TRANSITIONS,
    InvalidTransition: InvalidTransition,
    createMachine: createMachine
  })

  if (typeof global !== 'undefined') {
    global.AIIAState = api
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api
  }
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this))
