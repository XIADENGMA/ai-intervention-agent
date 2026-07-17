"""R535 regression coverage for one-pass VS Code task image normalization."""

from __future__ import annotations

import json
import subprocess
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


def _extract_function_body(source: str, marker: str) -> str:
    function_source = _extract_function(source, marker)
    open_brace = function_source.find("{")
    return function_source[open_brace + 1 : -1]


def test_task_image_normalization_uses_shared_single_pass_helper() -> None:
    source = _source()
    helper = _extract_function(source, "function normalizeTaskImages(")

    assert "const normalizedImages = []" in helper
    assert "if (!Array.isArray(images)) return normalizedImages" in helper
    assert "for (const img of images)" in helper
    assert "normalizedImages.push({" in helper
    assert ".map(" not in helper
    assert ".filter(" not in helper

    for marker in (
        "function saveLocalStateForTask(",
        "function restoreLocalStateForTask(",
        "function syncImagesToTaskCache(",
        "function cacheImagesForTask(",
    ):
        body = _extract_function_body(source, marker)
        assert "normalizeTaskImages(" in body
        assert ".map(img => ({" not in body
        assert ".filter(x => x.data)" not in body


def test_normalize_task_images_preserves_cache_shape_and_edges() -> None:
    helper = _extract_function(_source(), "function normalizeTaskImages(")
    script = f"""
{helper}
const normalized = normalizeTaskImages([
  {{ name: 'one.png', data: 'data:image/png;base64,1' }},
  {{ name: '', data: 'data:image/png;base64,2' }},
  {{ name: 123, data: 456 }},
  {{ name: 'empty.png', data: '' }},
  null
])
const empty = normalizeTaskImages(null)
console.log(JSON.stringify({{ normalized, empty }}))
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload == {
        "normalized": [
            {"name": "one.png", "data": "data:image/png;base64,1"},
            {"name": "image", "data": "data:image/png;base64,2"},
            {"name": "123", "data": "456"},
        ],
        "empty": [],
    }
