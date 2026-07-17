"""R555 regression coverage for task-tab shortcut navigation."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
KEYBOARD_SHORTCUTS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard-shortcuts.js"
)


def _source() -> str:
    return KEYBOARD_SHORTCUTS_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
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
        let currentTabs = [];
        const body = {{
          tagName: 'BODY',
          isContentEditable: false,
          classList: {{ contains() {{ return false; }} }},
        }};
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
              if (!documentListeners[type]) documentListeners[type] = [];
              documentListeners[type].push(handler);
            }},
            removeEventListener(type, handler) {{
              if (!documentListeners[type]) return;
              documentListeners[type] = documentListeners[type].filter(
                (candidate) => candidate !== handler,
              );
            }},
            getElementById() {{ return null; }},
            querySelectorAll(selector) {{
              if (selector === '.task-tab:not(.hidden)') return currentTabs;
              return [];
            }},
          }},
          module: {{ exports: {{}} }},
          navigator: {{ platform: 'MacIntel' }},
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
              preventDefault() {{ this.defaultPrevented = true; }},
              stopPropagation() {{}},
            }}, init || {{}});
            for (const handler of [...(documentListeners.keydown || [])]) {{
              handler(event);
            }}
            return event;
          }},
          __setTabs(tabs) {{
            currentTabs = tabs;
          }},
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const KeyboardShortcuts = sandbox.module.exports;
        {case_js}
        """
    )


def test_task_tab_navigation_avoids_array_from_find_index() -> None:
    source = _source()
    helper_body = _extract_function(source, "function getActiveTaskTabIndex(")
    defaults_body = _extract_function(source, "registerDefaults: function")

    assert "for (let i = 0; i < tabs.length; i += 1)" in helper_body
    assert "classList.contains('active')" in helper_body
    assert "return -1;" in helper_body
    assert "Array.from(tabs).findIndex" not in defaults_body
    assert ".findIndex(" not in defaults_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_task_tab_shortcuts_preserve_wrap_and_no_active_semantics() -> None:
    script = _keyboard_shortcuts_harness(
        """
        const clicks = [];
        function makeTabs(activeIndex, count = 4) {
          return Array.from({ length: count }, (_, index) => ({
            id: `tab-${index}`,
            classList: {
              contains(name) {
                return name === 'active' && index === activeIndex;
              },
            },
            click() {
              clicks.push(index);
            },
          }));
        }

        KeyboardShortcuts.init();

        sandbox.__setTabs(makeTabs(1));
        const forward = sandbox.__dispatchKeydown({ key: 'Tab' });

        sandbox.__setTabs(makeTabs(1));
        const backward = sandbox.__dispatchKeydown({ key: 'Tab', shiftKey: true });

        sandbox.__setTabs(makeTabs(-1));
        const noActiveForward = sandbox.__dispatchKeydown({ key: 'Tab' });

        sandbox.__setTabs(makeTabs(-1));
        const noActiveBackward = sandbox.__dispatchKeydown({
          key: 'Tab',
          shiftKey: true,
        });

        sandbox.__setTabs(makeTabs(0, 1));
        const single = sandbox.__dispatchKeydown({ key: 'Tab' });

        process.stdout.write(JSON.stringify({
          clicks,
          prevented: [
            forward.defaultPrevented,
            backward.defaultPrevented,
            noActiveForward.defaultPrevented,
            noActiveBackward.defaultPrevented,
            single.defaultPrevented,
          ],
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "clicks": [2, 0, 0, 2],
        "prevented": [True, True, True, True, True],
    }
