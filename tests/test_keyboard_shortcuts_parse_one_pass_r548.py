"""R548 regression coverage for one-pass keyboard shortcut parsing."""

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


def _keyboard_shortcuts_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(KEYBOARD_SHORTCUTS_JS)!r}, 'utf8');
        const documentListeners = {{}};
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
            querySelectorAll() {{ return []; }},
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
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const KeyboardShortcuts = sandbox.module.exports;
        {case_js}
        """
    )


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


def test_parse_shortcut_avoids_split_map_intermediate_arrays() -> None:
    body = _extract_function(_source(), "function parseShortcut(")

    assert ".split('+')" not in body
    assert '.split("+")' not in body
    assert ".map(" not in body
    assert "normalized.charCodeAt(i) !== 43" in body
    assert ".trim()" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_parse_shortcut_preserves_trim_alias_and_last_key_semantics() -> None:
    script = _keyboard_shortcuts_harness(
        """
        let calls = 0;
        KeyboardShortcuts.init();
        KeyboardShortcuts.register(' CTRL + Shift + SPACE ', () => {
          calls += 1;
        });
        KeyboardShortcuts.register('ctrl + x + enter', () => {
          calls += 10;
        });
        KeyboardShortcuts.register('ctrl+', () => {
          calls += 100;
        });
        const first = sandbox.__dispatchKeydown({
          key: ' ',
          ctrlKey: true,
          shiftKey: true,
        });
        const second = sandbox.__dispatchKeydown({
          key: 'Enter',
          ctrlKey: true,
        });
        process.stdout.write(JSON.stringify({
          calls,
          firstPrevented: first.defaultPrevented,
          secondPrevented: second.defaultPrevented,
          hasTrimmedSpaceAlias: KeyboardShortcuts.getAll().has('ctrl+shift+space'),
          hasLastKeyWins: KeyboardShortcuts.getAll().has('ctrl+enter'),
          hasTrailingBlankKey: KeyboardShortcuts.getAll().has('ctrl+'),
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "calls": 11,
        "firstPrevented": True,
        "secondPrevented": True,
        "hasTrimmedSpaceAlias": True,
        "hasLastKeyWins": True,
        "hasTrailingBlankKey": True,
    }
