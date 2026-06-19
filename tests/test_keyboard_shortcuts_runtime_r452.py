"""Runtime checks for the shared keyboard shortcut registry.

The registry is consumed both by its own default shortcuts and by modules such
as Quick Phrases through ``window.KeyboardShortcuts``. These tests execute the
real browser bundle in a small VM harness so key normalization and global export
behavior stay aligned with actual ``keydown`` dispatch.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYBOARD_SHORTCUTS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard-shortcuts.js"
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


def _keyboard_shortcuts_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(KEYBOARD_SHORTCUTS_JS)!r}, 'utf8');

        const documentListeners = {{}};

        function pushListener(type, handler) {{
          if (!documentListeners[type]) documentListeners[type] = [];
          documentListeners[type].push(handler);
        }}

        function removeListener(type, handler) {{
          if (!documentListeners[type]) return;
          documentListeners[type] = documentListeners[type].filter(
            (candidate) => candidate !== handler,
          );
        }}

        function createElement(tagName) {{
          return {{
            tagName: String(tagName || 'div').toUpperCase(),
            isContentEditable: false,
            classList: {{
              contains() {{ return false; }},
            }},
            click() {{}},
          }};
        }}

        const body = createElement('body');

        const sandbox = {{
          Array,
          JSON,
          Map,
          Object,
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
            addEventListener(type, handler) {{
              pushListener(type, handler);
            }},
            removeEventListener(type, handler) {{
              removeListener(type, handler);
            }},
            getElementById() {{
              return null;
            }},
            querySelectorAll() {{
              return [];
            }},
          }},
          module: {{ exports: {{}} }},
          navigator: {{
            platform: 'MacIntel',
          }},
          __dispatchKeydown(init) {{
            const event = Object.assign({{
              type: 'keydown',
              key: '',
              ctrlKey: false,
              altKey: false,
              shiftKey: false,
              metaKey: false,
              target: body,
              defaultPrevented: false,
              propagationStopped: false,
              preventDefault() {{
                this.defaultPrevented = true;
              }},
              stopPropagation() {{
                this.propagationStopped = true;
              }},
            }}, init || {{}});
            for (const handler of [...(documentListeners.keydown || [])]) {{
              handler(event);
            }}
            return event;
          }},
          __documentListeners: documentListeners,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        const KeyboardShortcuts = sandbox.module.exports;

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_register_unregister_space_alias_matches_keyboard_event_key() -> None:
    script = _keyboard_shortcuts_harness(
        """
        let calls = 0;
        KeyboardShortcuts.init();
        KeyboardShortcuts.register('ctrl+space', () => {
          calls += 1;
        });

        const first = sandbox.__dispatchKeydown({ key: ' ', ctrlKey: true });
        KeyboardShortcuts.unregister('ctrl+space');
        const second = sandbox.__dispatchKeydown({ key: ' ', ctrlKey: true });

        process.stdout.write(JSON.stringify({
          calls,
          firstPrevented: first.defaultPrevented,
          secondPrevented: second.defaultPrevented,
          registeredAfterUnregister: KeyboardShortcuts.getAll().has('ctrl+space'),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "calls": 1,
        "firstPrevented": True,
        "secondPrevented": False,
        "registeredAfterUnregister": False,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_keydown_ignore_guard_handles_missing_and_non_element_targets() -> None:
    script = _keyboard_shortcuts_harness(
        """
        let calls = 0;
        KeyboardShortcuts.init();
        KeyboardShortcuts.register('ctrl+k', () => {
          calls += 1;
        });

        sandbox.__dispatchKeydown({ key: 'k', ctrlKey: true, target: null });
        sandbox.__dispatchKeydown({
          key: 'k',
          ctrlKey: true,
          target: { nodeType: 9 },
        });
        sandbox.__dispatchKeydown({
          key: 'k',
          ctrlKey: true,
          target: { tagName: 'input', isContentEditable: false },
        });

        process.stdout.write(JSON.stringify({ calls }));
        """
    )

    assert json.loads(_run_node(script)) == {"calls": 2}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_browser_global_export_matches_quick_phrases_integration_contract() -> None:
    script = _keyboard_shortcuts_harness(
        """
        process.stdout.write(JSON.stringify({
          exportedToWindow: sandbox.window.KeyboardShortcuts === KeyboardShortcuts,
          moduleExported: typeof KeyboardShortcuts.register === 'function',
          domContentLoadedListeners:
            (sandbox.__documentListeners.DOMContentLoaded || []).length,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "exportedToWindow": True,
        "moduleExported": True,
        "domContentLoadedListeners": 1,
    }
