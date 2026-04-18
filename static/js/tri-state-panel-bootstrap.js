/*!
 * ai-intervention-agent · Tri-state panel bootstrap (Web UI)
 *
 * Role: classic <script defer> bridge between:
 *   - `tri-state-panel-loader.js` (ES module graph that resolves the bare
 *     specifier `@aiia/tri-state-panel` via Import Maps), and
 *   - the existing classic-script runtime (app.js / state.js / i18n.js).
 *
 * Behavior:
 *   1. Creates a dedicated `content` state machine instance via
 *      `window.AIIAState.createMachine('content', 'ready')` and exposes it
 *      as `window.AIIA_CONTENT_SM` so future consumers (C10d / S2 / BM-2)
 *      can drive `loading/empty/error/ready` without inventing another
 *      source of truth.
 *   2. Waits for the ES module graph to resolve
 *      (`aiia:tri-state-panel-ready`) and instantiates the
 *      TriStatePanelController on `#aiia-tri-state-panel`, wiring
 *      `onAction` to delegate to `window.AIIA_TRI_STATE_PANEL_ACTIONS` if
 *      present (set by C10d).
 *   3. Re-runs `window.AIIA_I18N.translateDOM(rootEl)` once so the 13 newly
 *      injected `data-i18n="aiia.state.*"` strings become localized text.
 *   4. Debug / QA hatch: when `?aiia_tri_state=<state>[&aiia_tri_state_error=...
 *      &aiia_tri_state_empty=...]` is present, the bootstrap transitions
 *      the controller to the requested state. This lets E2E harnesses
 *      exercise every branch without needing real backend failures.
 *
 * Non-goals:
 *   - Does NOT replace the legacy `#no-content-container` flow (kept as-is,
 *     per §T1 v3 "additive rollout"). C10d will migrate callers.
 *   - Does NOT catch errors from the existing app.js; the panel is opt-in.
 */

;(function () {
  'use strict'

  var ROOT_SELECTOR = '#aiia-tri-state-panel'
  var READY_EVENT = 'aiia:tri-state-panel-ready'
  var FAILED_EVENT = 'aiia:tri-state-panel-failed'
  var STATE_MACHINE_GLOBAL = 'AIIA_CONTENT_SM'
  var CONTROLLER_GLOBAL = 'AIIA_TRI_STATE_PANEL_CONTROLLER'
  var ACTION_DISPATCH_GLOBAL = 'AIIA_TRI_STATE_PANEL_ACTIONS'

  var VALID_DEBUG_STATES = ['skeleton', 'loading', 'empty', 'error', 'ready']
  var VALID_DEBUG_ERROR_MODES = ['network', 'server_500', 'timeout', 'unknown']
  var VALID_DEBUG_EMPTY_MODES = ['default', 'filtered']

  function ensureStateMachine() {
    if (window[STATE_MACHINE_GLOBAL]) return window[STATE_MACHINE_GLOBAL]
    if (!window.AIIAState || typeof window.AIIAState.createMachine !== 'function') {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('[tri-state-panel] window.AIIAState missing; skipping SM init')
      }
      return null
    }
    try {
      var sm = window.AIIAState.createMachine('content', 'ready')
      window[STATE_MACHINE_GLOBAL] = sm
      return sm
    } catch (e) {
      if (typeof console !== 'undefined' && console.error) {
        console.error('[tri-state-panel] createMachine failed:', e)
      }
      return null
    }
  }

  function getDebugOverrides() {
    try {
      var params = new URLSearchParams(window.location.search)
      var state = params.get('aiia_tri_state')
      var errorMode = params.get('aiia_tri_state_error')
      var emptyMode = params.get('aiia_tri_state_empty')
      var out = {}
      if (state && VALID_DEBUG_STATES.indexOf(state) >= 0) out.state = state
      if (errorMode && VALID_DEBUG_ERROR_MODES.indexOf(errorMode) >= 0) out.errorMode = errorMode
      if (emptyMode && VALID_DEBUG_EMPTY_MODES.indexOf(emptyMode) >= 0) out.emptyMode = emptyMode
      return out
    } catch (_e) {
      return {}
    }
  }

  function translatePanel(rootEl) {
    if (!rootEl) return
    var i18n = window.AIIA_I18N
    if (i18n && typeof i18n.translateDOM === 'function') {
      try { i18n.translateDOM(rootEl) } catch (_e) { /* noop */ }
    }
  }

  function dispatchAction(action, meta) {
    var table = window[ACTION_DISPATCH_GLOBAL]
    if (table && typeof table[action] === 'function') {
      try { table[action](meta) } catch (e) {
        if (typeof console !== 'undefined' && console.error) {
          console.error('[tri-state-panel] action handler threw:', action, e)
        }
      }
      return
    }
    if (typeof console !== 'undefined' && console.info) {
      console.info('[tri-state-panel] unhandled action:', action)
    }
  }

  function mountController(pkg) {
    var rootEl = document.querySelector(ROOT_SELECTOR)
    if (!rootEl) {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('[tri-state-panel] no root element matched ' + ROOT_SELECTOR)
      }
      return
    }
    if (!pkg || typeof pkg.TriStatePanelController !== 'function') {
      if (typeof console !== 'undefined' && console.error) {
        console.error('[tri-state-panel] loader produced no constructor')
      }
      return
    }

    var sm = ensureStateMachine()
    var debug = getDebugOverrides()

    var controller
    try {
      controller = new pkg.TriStatePanelController({
        rootEl: rootEl,
        stateMachine: sm,
        onAction: dispatchAction,
        initialState: debug.state || 'ready',
        initialErrorMode: debug.errorMode || null,
        initialEmptyMode: debug.emptyMode || null
      })
    } catch (e) {
      if (typeof console !== 'undefined' && console.error) {
        console.error('[tri-state-panel] controller init failed:', e)
      }
      return
    }

    window[CONTROLLER_GLOBAL] = controller

    if (debug.state && sm) {
      try { sm.reset(debug.state) } catch (_e) { /* noop */ }
    }

    translatePanel(rootEl)

    if (typeof console !== 'undefined' && console.debug) {
      console.debug(
        '[tri-state-panel] mounted (state=' + controller.getState() +
        ', errorMode=' + controller.getErrorMode() +
        ', emptyMode=' + controller.getEmptyMode() + ')'
      )
    }
  }

  function onReady(event) {
    document.removeEventListener(READY_EVENT, onReady)
    document.removeEventListener(FAILED_EVENT, onFailed)
    mountController(event && event.detail)
  }

  function onFailed(event) {
    document.removeEventListener(READY_EVENT, onReady)
    document.removeEventListener(FAILED_EVENT, onFailed)
    if (typeof console !== 'undefined' && console.error) {
      console.error('[tri-state-panel] loader failed:', event && event.detail)
    }
  }

  function start() {
    if (window.AIIA_TRI_STATE_PANEL && typeof window.AIIA_TRI_STATE_PANEL.TriStatePanelController === 'function') {
      mountController(window.AIIA_TRI_STATE_PANEL)
      return
    }
    document.addEventListener(READY_EVENT, onReady)
    document.addEventListener(FAILED_EVENT, onFailed)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true })
  } else {
    start()
  }
})()
