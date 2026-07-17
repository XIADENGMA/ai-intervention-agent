"""R534 regression coverage for one-pass webview platform detection."""

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


def test_detect_mac_like_platform_normalizes_with_single_loop() -> None:
    body = _extract_function(_source(), "function detectMacLikePlatform(")

    assert "const haystacks = [uaDataPlatform, platform, userAgent]" in body
    assert "for (const value of haystacks)" in body
    assert "const normalized = value.toLowerCase()" in body
    assert "normalized.includes('mac')" in body
    assert "/iphone|ipad|ipod/.test(normalized)" in body
    assert ".filter(" not in body
    assert ".map(" not in body
    assert ".some(" not in body


def test_detect_mac_like_platform_preserves_platform_edges() -> None:
    script = f"""
const helpers = require({json.dumps(str(WEBVIEW_HELPERS_JS))})
const cases = [
  helpers.detectMacLikePlatform({{ platform: 'MacIntel' }}),
  helpers.detectMacLikePlatform({{ userAgentData: {{ platform: 'macOS' }} }}),
  helpers.detectMacLikePlatform({{ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)' }}),
  helpers.detectMacLikePlatform({{ platform: 'iPad' }}),
  helpers.detectMacLikePlatform({{ platform: 'Linux x86_64' }}),
  helpers.detectMacLikePlatform({{
    userAgentData: {{ platform: {{ value: 'macOS' }} }},
    platform: 42,
    userAgent: null
  }})
]
console.log(JSON.stringify(cases))
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [True, True, True, True, False, False]
