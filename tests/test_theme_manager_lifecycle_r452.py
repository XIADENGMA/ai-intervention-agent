"""Runtime checks for ``theme.js`` listener ownership.

``ThemeManager.init()`` is a public, repeatable API: tests, webview restores, or
future partial UI refreshes may call it after the automatic DOMContentLoaded
initialization. Long-lived listeners for system color-scheme changes and
cross-tab storage sync must remain single-install while the cheap UI refresh work
stays repeatable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
THEME_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "theme.js"


def _read_source() -> str:
    return THEME_JS.read_text(encoding="utf-8")


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


def _theme_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(THEME_JS)!r}, 'utf8');

        const documentListeners = [];
        const windowListeners = [];
        const mediaListeners = [];
        const legacyMediaListeners = [];
        const buttonListeners = [];
        const dispatchedEvents = [];
        const appendedHead = [];
        const htmlAttrs = {{}};
        const buttonAttrs = {{}};
        const buttonClasses = new Set();
        let storedTheme = null;

        const button = {{
          classList: {{
            toggle(name, force) {{
              if (force) buttonClasses.add(name);
              else buttonClasses.delete(name);
            }},
          }},
          addEventListener(type, handler) {{
            buttonListeners.push({{ type, handler }});
          }},
          hasAttribute(name) {{
            return Object.prototype.hasOwnProperty.call(buttonAttrs, name);
          }},
          setAttribute(name, value) {{
            buttonAttrs[name] = String(value);
          }},
        }};

        const mediaQuery = {{
          matches: false,
          addEventListener(type, handler) {{
            mediaListeners.push({{ type, handler }});
          }},
          addListener(handler) {{
            legacyMediaListeners.push(handler);
          }},
        }};

        const sandbox = {{
          Array,
          CustomEvent: function CustomEvent(type, init) {{
            return {{ type, detail: init && init.detail }};
          }},
          JSON,
          Object,
          Promise,
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
            addEventListener(type, handler) {{
              documentListeners.push({{ type, handler }});
            }},
            createElement(tag) {{
              return {{
                tagName: String(tag).toUpperCase(),
                content: '',
                name: '',
              }};
            }},
            documentElement: {{
              removeAttribute(name) {{
                delete htmlAttrs[name];
              }},
              setAttribute(name, value) {{
                htmlAttrs[name] = String(value);
              }},
            }},
            head: {{
              appendChild(el) {{
                appendedHead.push(el);
              }},
            }},
            querySelector(selector) {{
              if (selector === 'meta[name="theme-color"]') return appendedHead[0] || null;
              return null;
            }},
            querySelectorAll(selector) {{
              return selector === '.theme-toggle-btn' ? [button] : [];
            }},
          }},
          localStorage: {{
            getItem(key) {{
              return key === 'theme-preference' ? storedTheme : null;
            }},
            setItem(key, value) {{
              if (key === 'theme-preference') storedTheme = String(value);
            }},
          }},
          module: {{ exports: {{}} }},
          exports: {{}},
          window: null,
          __buttonAttrs: buttonAttrs,
          __buttonClasses: buttonClasses,
          __buttonListeners: buttonListeners,
          __dispatchedEvents: dispatchedEvents,
          __documentListeners: documentListeners,
          __htmlAttrs: htmlAttrs,
          __mediaListeners: mediaListeners,
          __setStoredTheme(value) {{
            storedTheme = value;
          }},
          __windowListeners: windowListeners,
        }};

        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.addEventListener = (type, handler) => {{
          windowListeners.push({{ type, handler }});
        }};
        sandbox.dispatchEvent = (event) => {{
          dispatchedEvents.push(event);
          return true;
        }};
        sandbox.matchMedia = () => mediaQuery;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const ThemeManager = sandbox.module.exports;

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


class TestThemeManagerLifecycleSourceContract(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read_source()

    def test_long_lived_listener_install_flags_exist(self) -> None:
        self.assertIn("systemPreferenceListenerInstalled", self.src)
        self.assertIn("storageSyncListenerInstalled", self.src)

    def test_storage_sync_uses_named_single_install_handler(self) -> None:
        self.assertIn("function handleStorageChange(event)", self.src)
        self.assertRegex(
            self.src,
            r"function\s+setupStorageSync\(\)\s*\{[\s\S]*?"
            r"if\s*\(\s*storageSyncListenerInstalled\s*\)\s*return;"
            r"[\s\S]*?window\.addEventListener\('storage',\s*handleStorageChange\)"
            r"[\s\S]*?storageSyncListenerInstalled\s*=\s*true;",
        )

    def test_system_preference_listener_is_single_install(self) -> None:
        self.assertIn("function handleSystemPreferenceChange(e)", self.src)
        self.assertRegex(
            self.src,
            r"if\s*\(\s*!\s*query\s*\|\|\s*systemPreferenceListenerInstalled\s*\)"
            r"\s*return;",
        )
        self.assertIn(
            "query.addEventListener('change', handleSystemPreferenceChange)",
            self.src,
        )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_repeated_init_installs_global_listeners_once() -> None:
    script = _theme_harness(
        """
        ThemeManager.init();
        ThemeManager.init();

        process.stdout.write(
          JSON.stringify({
            storageListeners: sandbox.__windowListeners
              .filter((entry) => entry.type === 'storage').length,
            mediaListeners: sandbox.__mediaListeners
              .filter((entry) => entry.type === 'change').length,
            buttonListeners: sandbox.__buttonListeners
              .filter((entry) => entry.type === 'click').length,
            buttonBound: sandbox.__buttonAttrs['data-theme-bound'],
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"storageListeners":1,"mediaListeners":1,'
        '"buttonListeners":1,"buttonBound":"true"}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_storage_event_still_applies_cross_tab_theme_after_repeated_init() -> None:
    script = _theme_harness(
        """
        ThemeManager.init();
        ThemeManager.init();

        const storageHandler = sandbox.__windowListeners
          .find((entry) => entry.type === 'storage').handler;
        storageHandler({ key: 'unrelated', newValue: 'light' });
        storageHandler({ key: 'theme-preference', newValue: 'invalid' });
        const before = sandbox.__htmlAttrs['data-theme'];

        storageHandler({ key: 'theme-preference', newValue: 'light' });

        process.stdout.write(
          JSON.stringify({
            before,
            after: sandbox.__htmlAttrs['data-theme'],
            currentTheme: ThemeManager.getTheme(),
            effectiveTheme: ThemeManager.getEffectiveTheme(),
            dispatchedThemeEvents: sandbox.__dispatchedEvents
              .filter((event) => event.type === 'theme-changed').length,
          })
        );
        """
    )

    assert _run_node(script) == (
        '{"before":"dark","after":"light","currentTheme":"light",'
        '"effectiveTheme":"light","dispatchedThemeEvents":3}'
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_system_preference_change_updates_auto_theme_once() -> None:
    script = _theme_harness(
        """
        ThemeManager.init();
        ThemeManager.init();

        const mediaHandler = sandbox.__mediaListeners
          .find((entry) => entry.type === 'change').handler;
        mediaHandler({ matches: true });

        process.stdout.write(
          JSON.stringify({
            listeners: sandbox.__mediaListeners.length,
            currentTheme: ThemeManager.getTheme(),
            effectiveTheme: ThemeManager.getEffectiveTheme(),
            htmlTheme: sandbox.__htmlAttrs['data-theme'],
            isLight: sandbox.__buttonClasses.has('is-light'),
            isAuto: sandbox.__buttonClasses.has('is-auto'),
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "listeners": 1,
        "currentTheme": "auto",
        "effectiveTheme": "light",
        "htmlTheme": "light",
        "isLight": True,
        "isAuto": True,
    }
