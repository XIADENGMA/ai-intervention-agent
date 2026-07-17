"""R567 regression coverage for VS Code webview textarea state trimming."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


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


def test_trim_textarea_contents_uses_for_in_with_own_property_guard() -> None:
    source = _source()
    body = _extract_function(source, "function trimTextareaContents(")

    assert "Object.keys(src)" not in body
    assert "for (const taskId in src)" in body
    assert "Object.prototype.hasOwnProperty.call(src, taskId)" in body
    assert "if (budget <= 0) break" in body
    assert "typeof text !== 'string' || !text" in body
    assert "text.slice(0, Math.max(0, budget))" in body


def test_trim_textarea_contents_skips_inherited_keys_and_preserves_budget_behavior() -> (
    None
):
    script = textwrap.dedent(
        """
        const UI_STATE_TEXT_LIMIT_CHARS = 6

        function trimTextareaContents(contents) {
          try {
            const src = contents && typeof contents === 'object' ? contents : {}
            const out = {}
            let budget = UI_STATE_TEXT_LIMIT_CHARS
            for (const taskId in src) {
              if (!Object.prototype.hasOwnProperty.call(src, taskId)) continue
              if (budget <= 0) break
              const text = src[taskId]
              if (typeof text !== 'string' || !text) continue
              if (text.length <= budget) {
                out[taskId] = text
                budget -= text.length
              } else {
                out[taskId] = text.slice(0, Math.max(0, budget))
                budget = 0
              }
            }
            return out
          } catch (e) {
            return {}
          }
        }

        const proto = { inheritedTask: 'SHOULD_NOT_COPY' }
        const source = Object.create(proto)
        source[2] = 'bb'
        source[1] = 'a'
        source.empty = ''
        source.notText = { value: 'skip' }
        source.later = 'cdefgh'
        source.afterBudget = 'ignored'

        Object.defineProperty(source, 'hidden', {
          enumerable: false,
          value: 'hidden',
        })

        Object.defineProperty(Object, 'keys', {
          value() {
            throw new Error('Object.keys should not be called')
          },
          configurable: true,
        })

        process.stdout.write(JSON.stringify(trimTextareaContents(source)))
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "1": "a",
        "2": "bb",
        "later": "cde",
    }
