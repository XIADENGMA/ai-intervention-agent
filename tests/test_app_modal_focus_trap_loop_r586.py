"""R586 / R811: the Tab focus trap of the modal dialogs, in one place.

The code-paste dialog (``app.js``) and the settings panel (``settings-manager.js``) used to
carry two identical copies of the same ~25-line loop (``_modalFocusTrap`` and
``_settingsFocusTrap``), so a fix had to be made, and tested, twice: R586 and R587 are the
same bug (``Array.prototype.filter`` over a NodeList, replaced by one pass) in two files.
R811 left one implementation, ``DOMSecurity.trapTabFocus`` in ``dom-security.js`` (loaded
before both scripts), and both dialogs call it.

This file runs the real function in Node (R586: the loop itself) and checks that the
code-paste keydown handler hands Tab to it (R811).  ``test_settings_focus_trap_loop_r587.py``
does the same for the settings panel.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js"
APP_JS = STATIC_JS / "app.js"
DOM_SECURITY_JS = STATIC_JS / "dom-security.js"

FOCUSABLE_SELECTOR = (
    'button:not([disabled]),[href],input:not([disabled]):not([type="hidden"]),'
    "select:not([disabled]),textarea:not([disabled]),"
    '[tabindex]:not([tabindex="-1"])'
)


def _extract_block(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find marker: {marker}"
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
    raise AssertionError(f"Unbalanced body for: {marker}")


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_focus_trap_uses_one_pass_loop_without_filter_array() -> None:
    body = _extract_block(
        DOM_SECURITY_JS.read_text(encoding="utf-8"), "static trapTabFocus("
    )

    assert "Array.prototype.filter.call" not in body
    assert ".filter(" not in body
    assert "let first = null" in body
    assert "let last = null" in body
    assert "for (let i = 0; i < focusableCount; i += 1)" in body
    assert "el.hasAttribute('aria-hidden')" in body
    assert "event.preventDefault()" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_focus_trap_wraps_visible_edges_without_array_filter() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const sandbox = {{
          Number,
          window: {{}},
          document: {{ activeElement: null }},
        }};
        vm.createContext(sandbox);
        vm.runInContext(fs.readFileSync({json.dumps(str(DOM_SECURITY_JS))}, 'utf8'), sandbox);
        const trap = sandbox.window.DOMSecurity.trapTabFocus;

        const focusCalls = [];
        const preventCalls = [];
        const selectors = [];

        function makeEl(id, visible, ariaHidden) {{
          return {{
            id,
            offsetParent: visible ? {{}} : null,
            hasAttribute(name) {{
              return name === 'aria-hidden' && ariaHidden;
            }},
            focus() {{
              focusCalls.push(id);
              sandbox.document.activeElement = this;
            }},
          }};
        }}

        const first = makeEl('first', true, false);
        const displayHidden = makeEl('display-hidden', false, false);
        const ariaHidden = makeEl('aria-hidden', true, true);
        const last = makeEl('last', true, false);
        const focusables = {{
          0: first,
          1: displayHidden,
          2: ariaHidden,
          3: last,
          length: 4,
        }};
        const emptyFocusables = {{ length: 0 }};
        let useEmpty = false;
        const panel = {{
          querySelectorAll(selector) {{
            selectors.push(selector);
            return useEmpty ? emptyFocusables : focusables;
          }},
        }};

        const originalFilter = Array.prototype.filter;
        Array.prototype.filter = function filterDisabled() {{
          throw new Error('Array.prototype.filter must not be used');
        }};
        try {{
          sandbox.document.activeElement = last;
          trap(panel, {{
            key: 'Tab',
            shiftKey: false,
            preventDefault() {{ preventCalls.push('forward'); }},
          }});

          sandbox.document.activeElement = first;
          trap(panel, {{
            key: 'Tab',
            shiftKey: true,
            preventDefault() {{ preventCalls.push('backward'); }},
          }});

          // not at an edge: the browser's own Tab order is left alone
          sandbox.document.activeElement = first;
          trap(panel, {{
            key: 'Tab',
            shiftKey: false,
            preventDefault() {{ preventCalls.push('inside-forward'); }},
          }});
          sandbox.document.activeElement = last;
          trap(panel, {{
            key: 'Tab',
            shiftKey: true,
            preventDefault() {{ preventCalls.push('inside-backward'); }},
          }});

          // any other key never reaches the panel
          trap(panel, {{
            key: 'Escape',
            shiftKey: false,
            preventDefault() {{ preventCalls.push('escape'); }},
          }});

          // nothing focusable: nothing to trap
          useEmpty = true;
          trap(panel, {{
            key: 'Tab',
            shiftKey: false,
            preventDefault() {{ preventCalls.push('empty'); }},
          }});
          useEmpty = false;

          // no panel / no event: nothing to do and nothing thrown
          trap(null, {{ key: 'Tab', shiftKey: false, preventDefault() {{ preventCalls.push('no-panel'); }} }});
          trap(panel, null);
        }} finally {{
          Array.prototype.filter = originalFilter;
        }}

        process.stdout.write(JSON.stringify({{
          focusCalls,
          preventCalls,
          selectorCount: selectors.length,
          selector: selectors[0],
        }}));
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "focusCalls": ["first", "last"],
        "preventCalls": ["forward", "backward"],
        # four Tab events with a panel and one with an empty panel query the list;
        # Escape, a missing panel and a missing event do not
        "selectorCount": 5,
        "selector": FOCUSABLE_SELECTOR,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_code_paste_keydown_closes_on_escape_and_hands_tab_to_the_shared_trap() -> None:
    handler = _extract_block(
        APP_JS.read_text(encoding="utf-8"), "function handleCodePasteModalKeydown("
    )
    script = textwrap.dedent(
        f"""
        const vm = require('vm');
        const calls = [];
        const panel = {{ id: 'code-paste-panel' }};
        const sandbox = {{
          window: {{
            DOMSecurity: {{
              trapTabFocus(p, e) {{ calls.push(['trap', p && p.id, e.key]); }},
            }},
          }},
          document: {{
            getElementById(id) {{ return id === 'code-paste-panel' ? panel : null; }},
          }},
          closeCodePasteModal() {{ calls.push(['close']); }},
        }};
        vm.createContext(sandbox);
        vm.runInContext({json.dumps(handler)}, sandbox);

        sandbox.handleCodePasteModalKeydown({{ key: 'Escape' }});
        sandbox.handleCodePasteModalKeydown({{ key: 'Tab', shiftKey: false }});
        sandbox.handleCodePasteModalKeydown({{ key: 'Tab', shiftKey: true }});

        process.stdout.write(JSON.stringify(calls));
        """
    )

    assert json.loads(_run_node(script)) == [
        ["close"],
        ["trap", "code-paste-panel", "Tab"],
        ["trap", "code-paste-panel", "Tab"],
    ]
