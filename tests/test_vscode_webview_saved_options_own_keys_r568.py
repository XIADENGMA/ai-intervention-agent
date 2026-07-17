"""R568 regression coverage for VS Code webview saved option state keys."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def test_saved_option_state_uses_for_in_with_own_property_guard() -> None:
    source = _source()
    marker = (
        "const savedState = config.task_id ? taskOptionsStates[config.task_id] : null"
    )
    start = source.find(marker)
    assert start != -1
    branch_end = source.find("} else if (isSameTask)", start)
    assert branch_end != -1
    body = source[start:branch_end]

    assert "Object.keys(savedState)" not in body
    assert "for (const k in savedState)" in body
    assert "Object.prototype.hasOwnProperty.call(savedState, k)" in body
    assert "parseInt(k, 10)" in body
    assert "savedSelections.push(n)" in body


def test_saved_option_state_skips_inherited_keys_without_object_keys_copy() -> None:
    script = textwrap.dedent(
        """
        function collectSavedSelections(savedState) {
          const savedSelections = []
          if (savedState) {
            if (Array.isArray(savedState)) {
              savedState.forEach((checked, idx) => {
                if (checked) savedSelections.push(idx)
              })
            } else if (typeof savedState === 'object') {
              for (const k in savedState) {
                if (!Object.prototype.hasOwnProperty.call(savedState, k)) continue
                if (savedState[k]) {
                  const n = parseInt(k, 10)
                  if (!Number.isNaN(n)) savedSelections.push(n)
                }
              }
            }
          }
          return savedSelections
        }

        const proto = { 7: true, inherited: true }
        const savedState = Object.create(proto)
        savedState[2] = true
        savedState[1] = false
        savedState[0] = true
        savedState.name = true
        savedState['03-extra'] = true
        Object.defineProperty(savedState, '4', {
          enumerable: false,
          value: true,
        })

        Object.defineProperty(Object, 'keys', {
          value() {
            throw new Error('Object.keys should not be called')
          },
          configurable: true,
        })

        process.stdout.write(JSON.stringify({
          objectSelections: collectSavedSelections(savedState),
          arraySelections: collectSavedSelections([true, false, true]),
        }))
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "objectSelections": [0, 2, 3],
        "arraySelections": [0, 2],
    }
