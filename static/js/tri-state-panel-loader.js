/*!
 * @aiia/tri-state-panel · ES module bootstrap loader
 *
 * Why this file exists:
 *   - The rest of the Web UI is loaded as classic <script defer> bundles; we
 *     intentionally do NOT refactor them to ES modules in T1 C10b (to avoid
 *     cascading module-graph work during the tri-state rollout).
 *   - Import Maps (see templates/web_ui.html) only take effect inside
 *     `<script type="module">` graphs. This file is the single entry point
 *     of that module graph: it imports the bare specifier
 *     `@aiia/tri-state-panel` and re-exposes the constructor on the classic
 *     global `window.AIIA_TRI_STATE_PANEL` so the classic-script bootstrap
 *     (tri-state-panel-bootstrap.js) can consume it without being an
 *     ES module itself.
 *
 * Contract:
 *   - Mounts { TriStatePanelController, VERSION, VALID_STATES_FROZEN,
 *              ERROR_MODES_FROZEN, EMPTY_MODES_FROZEN } on window.AIIA_TRI_STATE_PANEL.
 *   - Dispatches a bubbling `aiia:tri-state-panel-ready` CustomEvent on
 *     document so classic consumers can wait for the module graph to resolve
 *     (avoids a race with `defer` classic scripts).
 *   - Never throws at top level (any import failure is surfaced via console
 *     + a CustomEvent `aiia:tri-state-panel-failed` carrying the error).
 *
 * Do NOT consume this file directly from classic scripts. Use
 * `window.AIIA_TRI_STATE_PANEL` after the ready event.
 */

const READY_EVENT = 'aiia:tri-state-panel-ready'
const FAILED_EVENT = 'aiia:tri-state-panel-failed'

function publish(pkg) {
  const globalNamespace = typeof window !== 'undefined' ? window : globalThis
  globalNamespace.AIIA_TRI_STATE_PANEL = pkg
  try {
    document.dispatchEvent(new CustomEvent(READY_EVENT, { detail: pkg }))
  } catch (_e) {
    /* CustomEvent unavailable in extremely old engines; skip */
  }
}

function publishError(err) {
  if (typeof console !== 'undefined' && console.error) {
    console.error('@aiia/tri-state-panel loader failed:', err)
  }
  try {
    document.dispatchEvent(new CustomEvent(FAILED_EVENT, { detail: { error: err } }))
  } catch (_e) {
    /* noop */
  }
}

import('@aiia/tri-state-panel')
  .then(function (mod) {
    publish({
      TriStatePanelController: mod.TriStatePanelController,
      VERSION: mod.VERSION,
      VALID_STATES: mod.VALID_STATES_FROZEN,
      ERROR_MODES: mod.ERROR_MODES_FROZEN,
      EMPTY_MODES: mod.EMPTY_MODES_FROZEN
    })
  })
  .catch(publishError)
