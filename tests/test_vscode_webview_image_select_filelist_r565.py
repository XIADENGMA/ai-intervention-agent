"""R565 regression coverage for VS Code webview image FileList handling."""

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


def test_webview_image_select_passes_filelist_without_array_from_copy() -> None:
    source = _source()
    handle_body = _extract_function(source, "function handleImageSelect(")
    process_body = _extract_function(source, "async function processImages(")

    assert "Array.from(e.target.files" not in handle_body
    assert "const target = e && e.target" in handle_body
    assert "const files = target && target.files ? target.files : []" in handle_body
    assert "processImages(files)" in handle_body
    assert "if (target) target.value = ''" in handle_body
    assert "for (const file of files" not in process_body
    assert "const fileCount =" in process_body
    assert "Number.isFinite(files.length)" in process_body
    assert (
        "for (let fileIndex = 0; fileIndex < fileCount; fileIndex += 1)" in process_body
    )
    assert "files[fileIndex]" in process_body
    assert "files.item(fileIndex)" in process_body


def test_process_images_indexed_loop_accepts_filelist_like_without_iterator() -> None:
    script = textwrap.dedent(
        """
        ;(async () => {
        const processed = []

        async function processImages(files) {
          const fileCount =
            files && typeof files.length === 'number' && Number.isFinite(files.length)
              ? Math.max(0, Math.floor(files.length))
              : 0

          for (let fileIndex = 0; fileIndex < fileCount; fileIndex += 1) {
            const file =
              files[fileIndex] ||
              (files && typeof files.item === 'function' ? files.item(fileIndex) : null)
            if (!file) continue
            processed.push(file.name)
          }
        }

        function handleImageSelect(e) {
          const target = e && e.target
          const files = target && target.files ? target.files : []
          processImages(files)
          if (target) target.value = ''
        }

        const target = {
          value: 'chosen',
          files: {
            length: 4,
            0: { name: 'zero.png' },
            item(index) {
              return index === 2 ? { name: 'two.jpg' } : null
            },
          },
        }

        await handleImageSelect({ target })
        await processImages([{ name: 'array.webp' }])
        await processImages({ length: Number.POSITIVE_INFINITY, 0: { name: 'bad.png' } })

        process.stdout.write(JSON.stringify({
          processed,
          targetValue: target.value,
        }))
        })().catch((error) => {
          console.error(error)
          process.exit(1)
        })
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "processed": ["zero.png", "two.jpg", "array.webp"],
        "targetValue": "",
    }
