"""Runtime checks for the iOS Add-to-Home-Screen hint banner fallbacks."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IOS_A2HS_HINT_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "ios_a2hs_hint.js"
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


def _ios_a2hs_harness(case_js: str, aiia_i18n_js: str = "") -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(IOS_A2HS_HINT_JS)!r}, 'utf8');

        const storage = new Map();
        const timeouts = [];

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
          const classes = new Set();
          const el = {{
            tagName: String(tagName || 'div').toUpperCase(),
            children: [],
            parentNode: null,
            attrs: {{}},
            className: '',
            id: '',
            innerHTML: '',
            textContent: '',
            type: '',
            classList: {{
              add(name) {{
                classes.add(name);
              }},
              contains(name) {{
                return classes.has(name);
              }},
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
              if (name === 'id') this.id = String(value);
            }},
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(this.attrs, name)
                ? this.attrs[name]
                : null;
            }},
            addEventListener(type, handler) {{
              if (!listeners[type]) listeners[type] = [];
              listeners[type].push(handler);
            }},
            dispatchEvent(event) {{
              for (const handler of [...(listeners[event.type] || [])]) {{
                handler(event);
              }}
              return true;
            }},
            __classes: classes,
            __listeners: listeners,
          }};
          return el;
        }}

        const body = createElement('body');

        const sandbox = {{
          Date: {{ now: () => 1700000000000 }},
          Error,
          JSON,
          Map,
          Object,
          RegExp,
          Set,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            body,
            readyState: 'complete',
            addEventListener() {{}},
            createElement(tagName) {{
              return createElement(tagName);
            }},
            getElementById(id) {{
              return walk(body, (node) => node.id === id);
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
          matchMedia() {{
            return {{ matches: false }};
          }},
          navigator: {{
            maxTouchPoints: 5,
            platform: 'iPhone',
            standalone: false,
            userAgent:
              'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) ' +
              'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 ' +
              'Mobile/15E148 Safari/604.1',
          }},
          setTimeout(fn, delay) {{
            timeouts.push(delay);
            fn();
            return timeouts.length;
          }},
          clearTimeout() {{}},
          {textwrap.indent(aiia_i18n_js.strip(), "          ").strip()}
          i18n: {{
            t(key) {{
              return key;
            }},
          }},
          __storage: storage,
          __timeouts: timeouts,
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
def test_banner_becomes_visible_without_request_animation_frame() -> None:
    script = _ios_a2hs_harness(
        """
        const banner = sandbox.document.getElementById('ios-a2hs-hint-banner');

        process.stdout.write(
          JSON.stringify({
            exists: Boolean(banner),
            visible: banner
              ? banner.classList.contains('ios-a2hs-banner--visible')
              : false,
            timeoutDelays: sandbox.__timeouts,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "exists": True,
        "visible": True,
        "timeoutDelays": [1500, 16],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_dismiss_persists_and_removes_banner_without_element_remove() -> None:
    script = _ios_a2hs_harness(
        """
        const banner = sandbox.document.getElementById('ios-a2hs-hint-banner');
        const dismiss = sandbox.document.getElementById('ios-a2hs-hint-dismiss');
        dismiss.dispatchEvent({ type: 'click' });

        process.stdout.write(
          JSON.stringify({
            stillAttached: Boolean(
              sandbox.document.getElementById('ios-a2hs-hint-banner')
            ),
            dismissed: JSON.parse(
              sandbox.__storage.get('aiia.iosA2hsDismissed.v1')
            ),
            bannerParentAfterDismiss: banner.parentNode,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "stillAttached": False,
        "dismissed": {
            "dismissed": True,
            "dismissed_at": 1700000000000,
            "schema_version": 1,
        },
        "bannerParentAfterDismiss": None,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_banner_labels_prefer_aiia_i18n_namespace() -> None:
    script = _ios_a2hs_harness(
        """
        const banner = sandbox.document.getElementById('ios-a2hs-hint-banner');
        const title = sandbox.document.getElementById('ios-a2hs-title');
        const dismiss = sandbox.document.getElementById('ios-a2hs-hint-dismiss');

        process.stdout.write(
          JSON.stringify({
            bannerExists: Boolean(banner),
            title: title ? title.textContent : null,
            dismissTitle: dismiss ? dismiss.getAttribute('title') : null,
            dismissAria: dismiss ? dismiss.getAttribute('aria-label') : null,
          })
        );
        """,
        aiia_i18n_js="""
          AIIA_I18N: {
            t(key) {
              const labels = {
                'page.iosA2hs.title': '安装为 iOS App',
                'page.iosA2hs.desc': '点按分享，然后添加到主屏幕',
                'page.iosA2hs.dismissTitle': '关闭',
                'page.iosA2hs.dismissAriaLabel': '关闭此提示',
              };
              return labels[key] || key;
            },
          },
        """,
    )

    assert json.loads(_run_node(script)) == {
        "bannerExists": True,
        "title": "安装为 iOS App",
        "dismissTitle": "关闭",
        "dismissAria": "关闭此提示",
    }
