/*!
 * @aiia/tri-state-panel · Unified tri-state panel (skeleton/loading/empty/error/ready)
 *
 * Design (aligned with BEST_PRACTICES_PLAN.tmp.md §四 T1 and §T1 v3):
 *   - Strict guard-clause order: skeleton → loading → error → empty → ready.
 *     Only one branch is ever visible at a time; enforced via CSS [data-state]
 *     selectors (see static/css/tri-state-panel.css) so no JS race can show
 *     two branches simultaneously.
 *   - Make invalid states unrepresentable: transitions are constrained by the
 *     caller's state machine (see static/js/state.js `ContentStatus`).
 *   - A11y (aligned with docs/noise-levels.zh-CN.md): error uses
 *     role="alert"+aria-live="assertive"; all other branches use
 *     role="status"+aria-live="polite".
 *   - i18n: all user-visible strings are declared via `data-i18n` in the host
 *     HTML; this controller only toggles `data-state`/`data-empty-mode`/
 *     `data-error-mode`. Text replacement is delegated to the host's i18n
 *     module (window.AIIA_I18N on Web UI; equivalent on VSCode webview).
 *   - Zero framework dependency. Buildless ES module. Consumed via Import
 *     Maps (`@aiia/tri-state-panel`) so business code is symmetric across
 *     Web UI and VSCode webview (see templates/web_ui.html + VSCode webview).
 *
 * Source of truth lives in static/js/tri-state-panel.js. VSCode side is a
 * byte-identical copy created by scripts/package_vscode_vsix.mjs at packaging
 * time and guarded by tests/test_tri_state_panel_parity.py (sha256).
 */

const VALID_STATES = Object.freeze(['skeleton', 'loading', 'empty', 'error', 'ready'])
const ERROR_MODES = Object.freeze(['network', 'server_500', 'timeout', 'unknown'])
const EMPTY_MODES = Object.freeze(['default', 'filtered'])

const DEFAULT_STATE = 'ready'
const DEFAULT_ERROR_MODE = 'unknown'
const DEFAULT_EMPTY_MODE = 'default'

function isElement(node) {
  return !!node && typeof node === 'object' && node.nodeType === 1
}

export class TriStatePanelController {
  constructor(options) {
    const opts = options && typeof options === 'object' ? options : {}
    if (!isElement(opts.rootEl)) {
      throw new TypeError('@aiia/tri-state-panel: options.rootEl must be an Element')
    }

    this._rootEl = opts.rootEl
    this._stateMachine = opts.stateMachine || null
    this._onAction = typeof opts.onAction === 'function' ? opts.onAction : noop
    this._unsubscribe = null

    this._handleClick = this._handleClick.bind(this)
    this._rootEl.addEventListener('click', this._handleClick)

    const initialState = typeof opts.initialState === 'string' ? opts.initialState : null
    const initialErrorMode = typeof opts.initialErrorMode === 'string' ? opts.initialErrorMode : null
    const initialEmptyMode = typeof opts.initialEmptyMode === 'string' ? opts.initialEmptyMode : null

    if (initialErrorMode) this.setErrorMode(initialErrorMode)
    if (initialEmptyMode) this.setEmptyMode(initialEmptyMode)

    if (this._stateMachine && typeof this._stateMachine.onChange === 'function') {
      const self = this
      this._unsubscribe = this._stateMachine.onChange(function (_prev, next) {
        self.setState(next)
      })
      if (typeof this._stateMachine.status === 'string') {
        this.setState(this._stateMachine.status)
      }
    }

    if (initialState) {
      this.setState(initialState)
    } else if (!this._rootEl.dataset.state) {
      this.setState(DEFAULT_STATE)
    }
  }

  setState(state) {
    if (!VALID_STATES.includes(state)) return false
    const el = this._rootEl
    el.dataset.state = state
    const isError = state === 'error'
    el.setAttribute('role', isError ? 'alert' : 'status')
    el.setAttribute('aria-live', isError ? 'assertive' : 'polite')
    el.setAttribute('aria-busy', state === 'skeleton' || state === 'loading' ? 'true' : 'false')
    return true
  }

  getState() {
    return this._rootEl.dataset.state || DEFAULT_STATE
  }

  setErrorMode(mode) {
    if (!ERROR_MODES.includes(mode)) return false
    this._rootEl.dataset.errorMode = mode
    return true
  }

  getErrorMode() {
    return this._rootEl.dataset.errorMode || DEFAULT_ERROR_MODE
  }

  setEmptyMode(mode) {
    if (!EMPTY_MODES.includes(mode)) return false
    this._rootEl.dataset.emptyMode = mode
    return true
  }

  getEmptyMode() {
    return this._rootEl.dataset.emptyMode || DEFAULT_EMPTY_MODE
  }

  _handleClick(event) {
    const target = event && event.target
    if (!target || typeof target.closest !== 'function') return
    const actionEl = target.closest('[data-tsp-action]')
    if (!actionEl || !this._rootEl.contains(actionEl)) return
    const action = actionEl.getAttribute('data-tsp-action')
    if (!action) return
    try {
      this._onAction(action, { event, sourceElement: actionEl, controller: this })
    } catch (err) {
      if (typeof console !== 'undefined' && console.error) {
        console.error('@aiia/tri-state-panel onAction handler threw:', err)
      }
    }
  }

  dispose() {
    if (typeof this._unsubscribe === 'function') {
      try { this._unsubscribe() } catch (_e) { /* noop */ }
      this._unsubscribe = null
    }
    this._rootEl.removeEventListener('click', this._handleClick)
    this._onAction = noop
  }
}

function noop() { /* intentional noop */ }

export const VERSION = '1.0.0'
export const VALID_STATES_FROZEN = VALID_STATES
export const ERROR_MODES_FROZEN = ERROR_MODES
export const EMPTY_MODES_FROZEN = EMPTY_MODES
