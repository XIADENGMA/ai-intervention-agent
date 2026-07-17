"""R587 regression coverage for the settings modal focus trap loop."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)


def _source() -> str:
    return SETTINGS_JS.read_text(encoding="utf-8")


def _extract_method(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find method marker: {marker}"
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
    raise AssertionError(f"Unbalanced method body for: {marker}")


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


def test_settings_focus_trap_uses_one_pass_loop_without_filter_array() -> None:
    body = _extract_method(_source(), "_settingsFocusTrap(panel, event)")

    assert "Array.prototype.filter.call" not in body
    assert ".filter(" not in body
    assert "let first = null" in body
    assert "let last = null" in body
    assert "for (let i = 0; i < focusableCount; i += 1)" in body
    assert 'el.hasAttribute("aria-hidden")' in body
    assert "event.preventDefault()" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_settings_focus_trap_wraps_visible_edges_without_array_filter() -> None:
    method_source = _extract_method(_source(), "_settingsFocusTrap(panel, event)")
    script = textwrap.dedent(
        f"""
        const vm = require('vm');
        const sandbox = {{
          Number,
          document: {{ activeElement: null }},
        }};
        vm.createContext(sandbox);
        vm.runInContext(
          'class Harness {{ ' + {json.dumps(method_source)} + ' }}; this.Harness = Harness;',
          sandbox
        );

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
        const instance = new sandbox.Harness();

        const originalFilter = Array.prototype.filter;
        Array.prototype.filter = function filterDisabled() {{
          throw new Error('Array.prototype.filter must not be used');
        }};
        try {{
          sandbox.document.activeElement = last;
          instance._settingsFocusTrap(panel, {{
            shiftKey: false,
            preventDefault() {{ preventCalls.push('forward'); }},
          }});

          sandbox.document.activeElement = first;
          instance._settingsFocusTrap(panel, {{
            shiftKey: true,
            preventDefault() {{ preventCalls.push('backward'); }},
          }});

          useEmpty = true;
          instance._settingsFocusTrap(panel, {{
            shiftKey: false,
            preventDefault() {{ preventCalls.push('empty'); }},
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
        "selectorCount": 3,
        "selector": (
            'button:not([disabled]),[href],input:not([disabled]):not([type="hidden"]),'
            "select:not([disabled]),textarea:not([disabled]),"
            '[tabindex]:not([tabindex="-1"])'
        ),
    }
