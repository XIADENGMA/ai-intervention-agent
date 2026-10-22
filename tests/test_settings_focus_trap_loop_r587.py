"""R587 / R811: the settings panel traps Tab with the shared ``DOMSecurity.trapTabFocus``.

R587 replaced ``Array.prototype.filter`` over a NodeList by one pass in the settings panel's
own ``_settingsFocusTrap`` - the twin of the code-paste dialog's ``_modalFocusTrap`` (R586).
R811 deleted both copies; the loop now lives once, in ``dom-security.js``
(``test_app_modal_focus_trap_loop_r586.py`` runs it), and the settings keydown handler only
decides between "Escape closes the panel" and "everything else goes to the shared trap".

The Node test below drives the real handler together with the real shared function.
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
SETTINGS_JS = STATIC_JS / "settings-manager.js"
DOM_SECURITY_JS = STATIC_JS / "dom-security.js"


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


def test_settings_panel_has_no_focus_trap_of_its_own() -> None:
    source = _source()

    assert "_settingsFocusTrap" not in source
    # the loop of the trap: visibility test and its counter live in dom-security.js only
    assert "offsetParent" not in source
    assert "focusableCount" not in source


def test_settings_keydown_handler_calls_the_shared_trap() -> None:
    body = _extract_method(_source(), "\n  _attachSettingsKeydownHandler(panel) {")

    assert 'e.key === "Escape"' in body
    assert "this.hideSettings()" in body
    assert "window.DOMSecurity.trapTabFocus(panel, e)" in body
    assert 'document.addEventListener("keydown", this._settingsEscHandler)' in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_settings_keydown_handler_escape_closes_and_tab_wraps_through_the_real_trap() -> (
    None
):
    method_source = _extract_method(
        _source(), "\n  _attachSettingsKeydownHandler(panel) {"
    )
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const listeners = [];
        const sandbox = {{
          Number,
          window: {{}},
          document: {{
            activeElement: null,
            addEventListener(type, handler) {{ listeners.push({{ type, handler }}); }},
          }},
        }};
        vm.createContext(sandbox);
        vm.runInContext(fs.readFileSync({json.dumps(str(DOM_SECURITY_JS))}, 'utf8'), sandbox);
        vm.runInContext(
          'class Harness {{ ' + {json.dumps(method_source)} + ' }}; this.Harness = Harness;',
          sandbox
        );

        const log = [];
        function makeEl(id) {{
          return {{
            id,
            offsetParent: {{}},
            hasAttribute() {{ return false; }},
            focus() {{ log.push('focus:' + id); sandbox.document.activeElement = this; }},
          }};
        }}
        const first = makeEl('first');
        const last = makeEl('last');
        const list = {{ 0: first, 1: last, length: 2 }};
        const panel = {{ querySelectorAll() {{ return list; }} }};

        const instance = new sandbox.Harness();
        instance.hideSettings = () => log.push('hide');
        instance._attachSettingsKeydownHandler(panel);
        instance._attachSettingsKeydownHandler(panel); // already attached: no second listener
        const handler = listeners[0].handler;

        function key(name, shiftKey) {{
          return {{
            key: name,
            shiftKey: !!shiftKey,
            preventDefault() {{ log.push('prevent:' + name + (shiftKey ? '+shift' : '')); }},
          }};
        }}

        sandbox.document.activeElement = last;
        handler(key('Escape'));          // closes, focus untouched
        handler(key('a'));               // not Tab: ignored by the trap
        handler(key('Tab'));             // on the last control: wraps to the first
        sandbox.document.activeElement = first;
        handler(key('Tab', true));       // on the first control: wraps to the last
        sandbox.document.activeElement = first;
        handler(key('Tab'));             // moving forward from the first control: browser order

        process.stdout.write(JSON.stringify({{
          listenerCount: listeners.length,
          listenerType: listeners[0].type,
          log,
        }}));
        """
    )

    assert json.loads(_run_node(script)) == {
        "listenerCount": 1,
        "listenerType": "keydown",
        "log": [
            "hide",
            "prevent:Tab",
            "focus:first",
            "prevent:Tab+shift",
            "focus:last",
        ],
    }
