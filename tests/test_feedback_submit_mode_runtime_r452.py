"""Runtime checks for feedback submit-mode listener lifecycle.

``feedback_submit_mode.js`` auto-initializes on load and exposes ``init()`` for
tests and future partial UI refreshes. Repeated initialization must not stack
capture-phase ``keydown`` handlers, because Enter-mode users would otherwise
submit the same feedback multiple times from one key press.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_SUBMIT_MODE_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "feedback_submit_mode.js"
)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _submit_mode_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(FEEDBACK_SUBMIT_MODE_JS)!r}, 'utf8');

        const storage = new Map();

        function createElement(tagName, name) {{
          const listeners = {{}};
          return {{
            tagName: String(tagName || 'div').toUpperCase(),
            name,
            value: '',
            disabled: false,
            clickCalls: 0,
            addCalls: [],
            removeCalls: [],
            addEventListener(type, handler, options) {{
              this.addCalls.push({{ type, handler, options }});
              listeners[type] = listeners[type] || [];
              listeners[type].push({{ handler, options }});
            }},
            removeEventListener(type, handler, options) {{
              this.removeCalls.push({{ type, handler, options }});
              listeners[type] = (listeners[type] || []).filter(
                (entry) => entry.handler !== handler || entry.options !== options,
              );
            }},
            dispatch(type, init) {{
              const event = Object.assign({{
                type,
                key: '',
                shiftKey: false,
                altKey: false,
                ctrlKey: false,
                metaKey: false,
                isComposing: false,
                keyCode: 0,
                currentTarget: this,
                defaultPrevented: false,
                preventDefault() {{
                  this.defaultPrevented = true;
                }},
              }}, init || {{}});
              for (const entry of [...(listeners[type] || [])]) {{
                entry.handler(event);
              }}
              return event;
            }},
            listenerCount(type) {{
              return (listeners[type] || []).length;
            }},
            click() {{
              this.clickCalls += 1;
            }},
            __listeners: listeners,
          }};
        }}

        let textarea = createElement('textarea', 'textarea-one');
        let select = createElement('select', 'select-one');
        let submitButton = createElement('button', 'submit');

        const sandbox = {{
          Date: {{ now: () => 1700000000000 }},
          JSON,
          Map,
          Object,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            readyState: 'complete',
            addEventListener() {{}},
            getElementById(id) {{
              if (id === 'feedback-text') return textarea;
              if (id === 'feedback-submit-mode-select') return select;
              if (id === 'submit-btn') return submitButton;
              return null;
            }},
          }},
          localStorage: {{
            getItem(key) {{
              return storage.has(key) ? storage.get(key) : null;
            }},
            setItem(key, value) {{
              storage.set(key, String(value));
            }},
            removeItem(key) {{
              storage.delete(key);
            }},
          }},
          window: null,
          __createElement: createElement,
          __getElements() {{
            return {{ textarea, select, submitButton }};
          }},
          __setElements(next) {{
            if (next.textarea) textarea = next.textarea;
            if (next.select) select = next.select;
            if (next.submitButton) submitButton = next.submitButton;
          }},
          __storage: storage,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const api = sandbox.window.AIIA_FEEDBACK_SUBMIT_MODE;

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_repeated_init_keeps_one_keydown_and_change_listener() -> None:
    script = _submit_mode_harness(
        """
        const api = sandbox.window.AIIA_FEEDBACK_SUBMIT_MODE;
        api.setMode('enter');
        const first = api.init();
        const second = api.init();

        const { textarea, select, submitButton } = sandbox.__getElements();
        const event = textarea.dispatch('keydown', { key: 'Enter' });
        select.value = 'ctrl_enter';
        select.dispatch('change');

        process.stdout.write(JSON.stringify({
          sameInterceptor: first.interceptor === second.interceptor,
          keydownAdds: textarea.addCalls.filter((entry) => entry.type === 'keydown').length,
          keydownListeners: textarea.listenerCount('keydown'),
          changeAdds: select.addCalls.filter((entry) => entry.type === 'change').length,
          changeListeners: select.listenerCount('change'),
          submitClicks: submitButton.clickCalls,
          defaultPrevented: event.defaultPrevented,
          modeAfterChange: api.getMode(),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "sameInterceptor": True,
        "keydownAdds": 1,
        "keydownListeners": 1,
        "changeAdds": 1,
        "changeListeners": 1,
        "submitClicks": 1,
        "defaultPrevented": True,
        "modeAfterChange": "ctrl_enter",
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_init_rebinds_when_textarea_or_select_dom_is_replaced() -> None:
    script = _submit_mode_harness(
        """
        const api = sandbox.window.AIIA_FEEDBACK_SUBMIT_MODE;
        api.setMode('enter');
        const oldElements = sandbox.__getElements();
        const nextTextarea = sandbox.__createElement('textarea', 'textarea-two');
        const nextSelect = sandbox.__createElement('select', 'select-two');
        sandbox.__setElements({ textarea: nextTextarea, select: nextSelect });

        const rebound = api.init();
        const event = nextTextarea.dispatch('keydown', { key: 'Enter' });
        nextSelect.value = 'ctrl_enter';
        nextSelect.dispatch('change');

        process.stdout.write(JSON.stringify({
          reboundName: rebound.interceptor.textarea.name,
          oldKeydownListeners: oldElements.textarea.listenerCount('keydown'),
          oldKeydownRemoves: oldElements.textarea.removeCalls
            .filter((entry) => entry.type === 'keydown').length,
          nextKeydownListeners: nextTextarea.listenerCount('keydown'),
          oldChangeListeners: oldElements.select.listenerCount('change'),
          oldChangeRemoves: oldElements.select.removeCalls
            .filter((entry) => entry.type === 'change').length,
          nextChangeListeners: nextSelect.listenerCount('change'),
          submitClicks: oldElements.submitButton.clickCalls,
          defaultPrevented: event.defaultPrevented,
          modeAfterChange: api.getMode(),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "reboundName": "textarea-two",
        "oldKeydownListeners": 0,
        "oldKeydownRemoves": 1,
        "nextKeydownListeners": 1,
        "oldChangeListeners": 0,
        "oldChangeRemoves": 1,
        "nextChangeListeners": 1,
        "submitClicks": 1,
        "defaultPrevented": True,
        "modeAfterChange": "ctrl_enter",
    }
