"""R591 regression coverage for app shortcut display updates."""

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


def test_update_shortcut_display_uses_direct_setters_without_object_entries() -> None:
    source = _source()
    body = _extract_function(source, "function updateShortcutDisplay(")

    assert "Object.entries" not in body
    assert ".forEach(" not in body
    assert "const shortcuts =" not in body
    assert (
        "function setShortcutText(id, shortcut) {\n  const element = document.getElementById(id);"
        in source
    )
    assert 'setShortcutText("shortcut-submit", `${ctrlOrCmd}+Enter`)' in body
    assert 'setShortcutText("shortcut-code", `${altOrOption}+C`)' in body
    assert 'setShortcutText("shortcut-paste", `${ctrlOrCmd}+V`)' in body
    assert 'setShortcutText("shortcut-upload", `${ctrlOrCmd}+U`)' in body
    assert 'setShortcutText("shortcut-delete", "Delete")' in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_update_shortcut_display_preserves_platform_text_and_missing_skip() -> None:
    source = _source()
    function_source = "\n".join(
        [
            _extract_function(source, "function setShortcutText("),
            _extract_function(source, "function updateShortcutDisplay("),
        ]
    )
    script = textwrap.dedent(
        f"""
        const vm = require('vm');

        const elements = {{
          'shortcut-submit': {{ textContent: '' }},
          'shortcut-code': {{ textContent: '' }},
          'shortcut-paste': {{ textContent: '' }},
          'shortcut-delete': {{ textContent: '' }},
        }};
        const calls = [];
        const sandbox = {{
          Object: Object.assign(Object.create(Object), {{
            entries() {{
              throw new Error('Object.entries must not be used');
            }},
          }}),
          document: {{
            getElementById(id) {{
              calls.push(id);
              return elements[id] || null;
            }},
          }},
        }};

        vm.createContext(sandbox);
        vm.runInContext(
          {json.dumps(function_source)} + '; this.updateShortcutDisplay = updateShortcutDisplay;',
          sandbox,
        );
        sandbox.updateShortcutDisplay('mac');
        const macSnapshot = JSON.parse(JSON.stringify(elements));
        sandbox.updateShortcutDisplay('windows');

        process.stdout.write(JSON.stringify({{
          calls,
          macSnapshot,
          final: elements,
        }}));
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "calls": [
            "shortcut-submit",
            "shortcut-code",
            "shortcut-paste",
            "shortcut-upload",
            "shortcut-delete",
            "shortcut-submit",
            "shortcut-code",
            "shortcut-paste",
            "shortcut-upload",
            "shortcut-delete",
        ],
        "macSnapshot": {
            "shortcut-submit": {"textContent": "Cmd+Enter"},
            "shortcut-code": {"textContent": "Option+C"},
            "shortcut-paste": {"textContent": "Cmd+V"},
            "shortcut-delete": {"textContent": "Delete"},
        },
        "final": {
            "shortcut-submit": {"textContent": "Ctrl+Enter"},
            "shortcut-code": {"textContent": "Alt+C"},
            "shortcut-paste": {"textContent": "Ctrl+V"},
            "shortcut-delete": {"textContent": "Delete"},
        },
    }
