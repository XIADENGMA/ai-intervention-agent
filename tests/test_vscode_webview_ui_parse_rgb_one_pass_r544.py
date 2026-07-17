"""R544 regression coverage for allocation-light VS Code webview UI RGB parsing."""

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


def test_ui_parse_rgb_color_scans_first_three_channels_without_array_pipeline() -> None:
    body = _extract_function(_source(), "function parseRgbColor(")

    assert "const channels = []" in body
    assert "for (let i = 0; i <= raw.length && channels.length < 3; i += 1)" in body
    assert "channels.push(channel)" in body
    assert "channels.length < 3" in body
    assert ".split(" not in body
    assert ".map(" not in body
    assert "[r, g, b].every" not in body
    assert ".every(" not in body


def test_ui_parse_rgb_color_preserves_existing_edges() -> None:
    parse_body = _extract_function(_source(), "function parseRgbColor(")
    script = textwrap.dedent(
        f"""
        {parse_body}
        const cases = [
          parseRgbColor('rgb(250, 250, 250)'),
          parseRgbColor('rgba(10, 20, 30, 0.5)'),
          parseRgbColor('rgb(1, 2, 3, ignored-extra-channel)'),
          parseRgbColor('rgb(1,,3)'),
          parseRgbColor('rgb(1, bad, 3)'),
          parseRgbColor('rgb(1, 2)'),
          parseRgbColor('hsl(1, 2, 3)'),
        ];
        console.log(JSON.stringify(cases));
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [
        {"r": 250, "g": 250, "b": 250},
        {"r": 10, "g": 20, "b": 30},
        {"r": 1, "g": 2, "b": 3},
        {"r": 1, "g": 0, "b": 3},
        None,
        None,
        None,
    ]
