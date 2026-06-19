"""Runtime checks for keyboard shortcut help dialog focus fallback.

The cheatsheet dialog should prefer ``focus({ preventScroll: true })`` but
still move focus to the dialog card when an older WebView only supports plain
``focus()``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYBOARD_SHORTCUT_HELP_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard_shortcut_help.js"
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


def _kshelp_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(KEYBOARD_SHORTCUT_HELP_JS)!r}, 'utf8');

        const documentListeners = {{}};
        const focusCalls = [];
        let activeElement = null;

        function pushListener(bucket, type, handler) {{
          if (!bucket[type]) bucket[type] = [];
          bucket[type].push(handler);
        }}

        function walk(root, predicate) {{
          if (!root) return null;
          if (predicate(root)) return root;
          for (const child of root.children || []) {{
            const found = walk(child, predicate);
            if (found) return found;
          }}
          return null;
        }}

        function createElement(tagName) {{
          const listeners = {{}};
          const el = {{
            tagName: String(tagName || 'div').toUpperCase(),
            children: [],
            parentNode: null,
            attrs: {{}},
            className: '',
            id: '',
            tabIndex: 0,
            textContent: '',
            inert: false,
            isContentEditable: false,
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
              if (name === 'id') this.id = String(value);
            }},
            removeAttribute(name) {{
              delete this.attrs[name];
            }},
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(this.attrs, name)
                ? this.attrs[name]
                : null;
            }},
            addEventListener(type, handler) {{
              pushListener(listeners, type, handler);
            }},
            querySelector(selector) {{
              if (selector === '.aiia-kshelp-card') {{
                return walk(this, (node) => node.className === 'aiia-kshelp-card');
              }}
              if (selector === '.container') {{
                return walk(this, (node) => node.className === 'container');
              }}
              return null;
            }},
            focus(options) {{
              focusCalls.push({{
                className: this.className,
                mode: options ? 'options' : 'plain',
              }});
              if (options && options.preventScroll) {{
                throw new Error('focus options unsupported');
              }}
              activeElement = this;
            }},
            contains(node) {{
              for (let current = node; current; current = current.parentNode) {{
                if (current === this) return true;
              }}
              return false;
            }},
            __listeners: listeners,
          }};
          return el;
        }}

        const body = createElement('body');
        const container = createElement('div');
        container.className = 'container';
        const opener = createElement('button');
        opener.id = 'open-help';
        container.appendChild(opener);
        body.appendChild(container);
        activeElement = opener;

        const sandbox = {{
          JSON,
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
            body,
            get activeElement() {{
              return activeElement;
            }},
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            removeEventListener(type, handler) {{
              if (!documentListeners[type]) return;
              documentListeners[type] = documentListeners[type].filter(
                (candidate) => candidate !== handler,
              );
            }},
            createElement(tagName) {{
              return createElement(tagName);
            }},
            getElementById(id) {{
              return walk(body, (node) => node.id === id);
            }},
            querySelector(selector) {{
              if (selector === '.container') return container;
              return body.querySelector(selector);
            }},
            contains(node) {{
              return body.contains(node);
            }},
          }},
          AIIA_I18N: {{
            t(key) {{
              return key;
            }},
          }},
          __documentListeners: documentListeners,
          __focusCalls: focusCalls,
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
def test_show_overlay_falls_back_to_plain_focus_when_options_throw() -> None:
    script = _kshelp_harness(
        """
        const api = sandbox.AIIA_KEYBOARD_SHORTCUT_HELP;
        api.showOverlay();

        const overlay = sandbox.document.getElementById(api.OVERLAY_ID);
        const card = overlay.querySelector('.aiia-kshelp-card');

        process.stdout.write(
          JSON.stringify({
            overlayOpen: api.isOverlayOpen(),
            activeClass: sandbox.document.activeElement.className,
            cardTabIndex: card.tabIndex,
            focusCalls: sandbox.__focusCalls,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "overlayOpen": True,
        "activeClass": "aiia-kshelp-card",
        "cardTabIndex": -1,
        "focusCalls": [
            {"className": "aiia-kshelp-card", "mode": "options"},
            {"className": "aiia-kshelp-card", "mode": "plain"},
        ],
    }
