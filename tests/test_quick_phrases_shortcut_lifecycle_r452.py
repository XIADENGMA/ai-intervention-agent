"""Runtime checks for Quick Phrases shortcut listener lifecycle.

R131d added Alt+1..9 insertion shortcuts. R452 locks the lifecycle behavior:
public ``init()`` calls must not re-register the 9 shortcuts or add duplicate
fallback ``keydown`` listeners.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QUICK_PHRASES_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "quick_phrases.js"
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


def _quick_phrases_harness(case_js: str, *, keyboard_shortcuts: bool) -> str:
    keyboard_shortcuts_js = (
        """
        KeyboardShortcuts: {
          register(name, handler, options) {
            registerCalls.push({ name, handler, options });
          },
        },
        """
        if keyboard_shortcuts
        else ""
    )
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(QUICK_PHRASES_JS)!r}, 'utf8');

        const storage = new Map();
        const documentListeners = {{}};
        const registerCalls = [];
        const elements = {{}};

        function pushListener(bucket, type, handler) {{
          if (!bucket[type]) bucket[type] = [];
          bucket[type].push(handler);
        }}

        function createElement(tagName, id) {{
          const listeners = {{}};
          const el = {{
            id: id || '',
            tagName: String(tagName || 'div').toUpperCase(),
            children: [],
            dataset: {{}},
            attrs: {{}},
            className: '',
            disabled: false,
            files: [],
            parentNode: null,
            textContent: '',
            type: '',
            value: '',
            classList: {{
              values: [],
              add(name) {{
                this.values.push(name);
              }},
            }},
            get firstChild() {{
              return this.children.length > 0 ? this.children[0] : null;
            }},
            appendChild(child) {{
              child.parentNode = this;
              this.children.push(child);
              return child;
            }},
            removeChild(child) {{
              const idx = this.children.indexOf(child);
              if (idx !== -1) this.children.splice(idx, 1);
              child.parentNode = null;
              return child;
            }},
            setAttribute(name, value) {{
              this.attrs[name] = String(value);
            }},
            getAttribute(name) {{
              return this.attrs[name] || null;
            }},
            addEventListener(type, handler) {{
              pushListener(listeners, type, handler);
            }},
            dispatchEvent(event) {{
              for (const handler of [...(listeners[event.type] || [])]) handler(event);
              return true;
            }},
            click() {{}},
            focus() {{}},
            querySelector(selector) {{
              if (selector === '.quick-phrases-form') {{
                return this.children.find((child) => child.className === 'quick-phrases-form') || null;
              }}
              if (selector === 'input, textarea') {{
                return this.children.find((child) => child.tagName === 'INPUT' || child.tagName === 'TEXTAREA') || null;
              }}
              return null;
            }},
            __listeners: listeners,
          }};
          return el;
        }}

        [
          ['div', 'quick-phrases-container'],
          ['div', 'quick-phrases-list'],
          ['div', 'quick-phrases-form-host'],
          ['button', 'quick-phrases-add-btn'],
          ['button', 'quick-phrases-export-btn'],
          ['button', 'quick-phrases-import-btn'],
          ['input', 'quick-phrases-import-file'],
          ['textarea', 'feedback-text'],
        ].forEach(([tag, id]) => {{
          elements[id] = createElement(tag, id);
        }});

        const sandbox = {{
          Date: {{ now: () => 1700000000000 }},
          JSON,
          Math,
          Number,
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
            body: createElement('body', 'body'),
            readyState: 'complete',
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            createElement(tagName) {{
              return createElement(tagName);
            }},
            createEvent() {{
              return {{
                initEvent(type, bubbles, cancelable) {{
                  this.type = type;
                  this.bubbles = bubbles;
                  this.cancelable = cancelable;
                }},
              }};
            }},
            getElementById(id) {{
              return elements[id] || null;
            }},
          }},
          Event: function Event(type) {{
            this.type = type;
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
          setTimeout(fn) {{
            fn();
            return 1;
          }},
          __documentListeners: documentListeners,
          __elements: elements,
          __registerCalls: registerCalls,
          __storage: storage,
          {keyboard_shortcuts_js}
        }};
        sandbox.window = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_keyboard_shortcuts_register_path_is_idempotent() -> None:
    script = _quick_phrases_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        api.init();
        api.init();
        api.setupKeyboardShortcuts();

        process.stdout.write(
          JSON.stringify({
            bound: api.isKeyboardShortcutsBound(),
            registerCalls: sandbox.__registerCalls.length,
            fallbackKeydownListeners:
              (sandbox.__documentListeners.keydown || []).length,
          })
        );
        """,
        keyboard_shortcuts=True,
    )

    assert _run_node(script) == (
        '{"bound":true,"registerCalls":9,"fallbackKeydownListeners":0}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_fallback_keydown_listener_is_idempotent() -> None:
    script = _quick_phrases_harness(
        """
        const api = sandbox.AIIA_QUICK_PHRASES;
        api.init();
        api.init();
        api.setupKeyboardShortcuts();

        process.stdout.write(
          JSON.stringify({
            bound: api.isKeyboardShortcutsBound(),
            fallbackKeydownListeners:
              (sandbox.__documentListeners.keydown || []).length,
            registerCalls: sandbox.__registerCalls.length,
          })
        );
        """,
        keyboard_shortcuts=False,
    )

    assert _run_node(script) == (
        '{"bound":true,"fallbackKeydownListeners":1,"registerCalls":0}'
    )
