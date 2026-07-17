"""R543 regression coverage for allocation-light VS Code helper RGB parsing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_HELPERS_JS = REPO_ROOT / "packages" / "vscode" / "webview-helpers.js"


def _source() -> str:
    return WEBVIEW_HELPERS_JS.read_text(encoding="utf-8")


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


def test_parse_rgb_color_scans_first_three_channels_without_array_pipeline() -> None:
    body = _extract_function(_source(), "function parseRgbColor(")

    assert "const channels = []" in body
    assert "for (let i = 0; i <= raw.length && channels.length < 3; i += 1)" in body
    assert "channels.push(channel)" in body
    assert "channels.length < 3" in body
    assert ".split(" not in body
    assert ".map(" not in body
    assert ".slice(0, 3)" not in body
    assert ".some(" not in body


def test_resolve_theme_kind_preserves_rgb_luminance_edges() -> None:
    script = f"""
const helpers = require({json.dumps(str(WEBVIEW_HELPERS_JS))})

function makeDoc(backgroundColor, existingKind) {{
  const attrs = existingKind ? {{ 'data-vscode-theme-kind': existingKind }} : {{}};
  return {{
    body: {{
      classList: {{ contains() {{ return false; }} }},
    }},
    documentElement: {{
      getAttribute(name) {{ return attrs[name] || ''; }},
    }},
    defaultView: {{
      getComputedStyle() {{
        return {{ colorScheme: '', backgroundColor }};
      }},
    }},
  }};
}}

const cases = [
  helpers.resolveThemeKind(makeDoc('rgb(250, 250, 250)')),
  helpers.resolveThemeKind(makeDoc('rgba(10, 20, 30, 0.5)')),
  helpers.resolveThemeKind(makeDoc('rgb(1, 2, 3, ignored-extra-channel)')),
  helpers.resolveThemeKind(makeDoc('rgb(1, bad, 3)', 'light')),
];
console.log(JSON.stringify(cases));
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == ["light", "dark", "dark", "light"]
