"""R586 regression coverage for the app modal focus trap loop."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


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
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_modal_focus_trap_uses_one_pass_loop_without_filter_array() -> None:
    body = _extract_function(_source(), "function _modalFocusTrap(")

    assert "Array.prototype.filter.call" not in body
    assert ".filter(" not in body
    assert "let first = null" in body
    assert "let last = null" in body
    assert "for (let i = 0; i < focusableCount; i += 1)" in body
    assert 'el.hasAttribute("aria-hidden")' in body
    assert "event.preventDefault()" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_modal_focus_trap_wraps_visible_edges_without_array_filter() -> None:
    function_source = _extract_function(_source(), "function _modalFocusTrap(")
    script = textwrap.dedent(
        f"""
        const vm = require('vm');
        const sandbox = {{
          Number,
          document: {{ activeElement: null }},
        }};
        vm.createContext(sandbox);
        vm.runInContext({json.dumps(function_source)}, sandbox);

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
        const panel = {{
          querySelectorAll(selector) {{
            selectors.push(selector);
            return focusables;
          }},
        }};

        const originalFilter = Array.prototype.filter;
        Array.prototype.filter = function filterDisabled() {{
          throw new Error('Array.prototype.filter must not be used');
        }};
        try {{
          sandbox.document.activeElement = last;
          sandbox._modalFocusTrap(panel, {{
            key: 'Tab',
            shiftKey: false,
            preventDefault() {{ preventCalls.push('forward'); }},
          }});

          sandbox.document.activeElement = first;
          sandbox._modalFocusTrap(panel, {{
            key: 'Tab',
            shiftKey: true,
            preventDefault() {{ preventCalls.push('backward'); }},
          }});

          sandbox._modalFocusTrap(panel, {{
            key: 'Escape',
            shiftKey: false,
            preventDefault() {{ preventCalls.push('escape'); }},
          }});
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
        "selectorCount": 2,
        "selector": (
            'button:not([disabled]),[href],input:not([disabled]):not([type="hidden"]),'
            "select:not([disabled]),textarea:not([disabled]),"
            '[tabindex]:not([tabindex="-1"])'
        ),
    }
