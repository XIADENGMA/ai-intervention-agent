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
 *              ERROR_MODES_FROZEN, EMPTY_MODES_FROZEN } on window.AIIA_TRI_STATE_PANEL
 *     on success.
 *   - Dispatches a bubbling `aiia:tri-state-panel-ready` CustomEvent on
 *     document so classic consumers can wait for the module graph to resolve
 *     (avoids a race with `defer` classic scripts).
 *   - Never throws at top level (any import failure is surfaced via console
 *     + a CustomEvent `aiia:tri-state-panel-failed` carrying the error).
 *   - On failure, also persists the error on `window.AIIA_TRI_STATE_PANEL_FAILURE`
 *     BEFORE dispatching the event, so any late listener (registered after the
 *     microtask that settled the import()) can still observe the outcome —
 *     symmetrical with the success path's `window.AIIA_TRI_STATE_PANEL` flag.
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
  const globalNamespace = typeof window !== 'undefined' ? window : globalThis
  // Persist FIRST so any late-registered listener (the classic bootstrap
  // registers its DOMContentLoaded handler AFTER this microtask in the
  // import()-rejects-synchronously path) can still observe the failure
  // via a flag read — mirrors the success path's AIIA_TRI_STATE_PANEL.
  globalNamespace.AIIA_TRI_STATE_PANEL_FAILURE =
    err instanceof Error ? err : new Error(String(err && err.message ? err.message : err || 'unknown loader failure'))
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
      VALID_STATES_FROZEN: mod.VALID_STATES_FROZEN,
      ERROR_MODES_FROZEN: mod.ERROR_MODES_FROZEN,
      EMPTY_MODES_FROZEN: mod.EMPTY_MODES_FROZEN
    })
  })
  .catch(publishError)
