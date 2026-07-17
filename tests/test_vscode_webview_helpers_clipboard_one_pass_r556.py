"""R556 regression coverage for allocation-light clipboard image collection."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

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


def _run_node(case_js: str) -> str:
    script = textwrap.dedent(
        f"""
        const helpers = require({json.dumps(str(WEBVIEW_HELPERS_JS))});
        {case_js}
        """
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_clipboard_collection_avoids_array_from_materialization() -> None:
    source = _source()
    helper_body = _extract_function(source, "function forEachClipboardEntry(")
    collect_body = _extract_function(source, "function collectImageFilesFromClipboard(")

    assert "Array.from(" not in helper_body
    assert "Array.from(" not in collect_body
    assert "collection[Symbol.iterator]" in helper_body
    assert "for (const entry of collection)" in helper_body
    assert "for (let i = 0; i < length; i += 1)" in helper_body
    assert "forEachClipboardEntry(clipboardData.items" in collect_body
    assert "forEachClipboardEntry(clipboardData.files" in collect_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_clipboard_items_preserve_priority_and_duplicate_suppression() -> None:
    script = """
        function file(name, type, size) {
          return { name, type, size, lastModified: 123 };
        }
        const primary = file('same.png', 'image/png', 10);
        const secondary = file('other.jpg', 'image/jpeg', 20);
        const fallback = file('fallback.png', 'image/png', 30);
        const result = helpers.collectImageFilesFromClipboard({
          items: {
            length: 5,
            0: { kind: 'string', type: 'text/plain' },
            1: { kind: 'file', type: 'text/plain', getAsFile() { return file('note.txt', 'text/plain', 5); } },
            2: { kind: 'file', type: 'image/png', getAsFile() { return primary; } },
            3: { kind: 'file', type: 'image/png', getAsFile() { return primary; } },
            4: { kind: 'file', type: 'image/jpeg', getAsFile() { return secondary; } },
          },
          files: [fallback],
        });
        process.stdout.write(JSON.stringify(result.map((entry) => entry.name)));
    """

    assert json.loads(_run_node(script)) == ["same.png", "other.jpg"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_clipboard_files_fallback_and_iterable_only_collections_still_work() -> None:
    script = """
        function file(name, type, size) {
          return { name, type, size, lastModified: 456 };
        }
        const itemImage = file('iterable.png', 'image/png', 10);
        const iterableResult = helpers.collectImageFilesFromClipboard({
          items: {
            [Symbol.iterator]: function* () {
              yield { kind: 'string', type: 'text/html' };
              yield { kind: 'file', type: 'image/png', getAsFile() { return itemImage; } };
            },
          },
          files: [],
        });

        const fallbackImage = file('fallback.jpg', 'image/jpeg', 20);
        const fallbackDuplicate = file('fallback.jpg', 'image/jpeg', 20);
        const fallbackResult = helpers.collectImageFilesFromClipboard({
          items: {
            length: 2,
            0: { kind: 'file', type: 'image/png', getAsFile() { return null; } },
            1: { kind: 'string', type: 'text/plain' },
          },
          files: {
            length: 4,
            0: undefined,
            1: file('note.txt', 'text/plain', 5),
            2: fallbackImage,
            3: fallbackDuplicate,
          },
        });

        process.stdout.write(JSON.stringify({
          iterable: iterableResult.map((entry) => entry.name),
          fallback: fallbackResult.map((entry) => entry.name),
        }));
    """

    assert json.loads(_run_node(script)) == {
        "iterable": ["iterable.png"],
        "fallback": ["fallback.jpg"],
    }
