"""R538 regression coverage for VS Code inline locale signature building."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_TS = REPO_ROOT / "packages" / "vscode" / "webview.ts"


def _source() -> str:
    return WEBVIEW_TS.read_text(encoding="utf-8")


def _extract_get_html_content_body(source: str) -> str:
    marker = "_getHtmlContent(webview: vscode.Webview): string"
    start = source.find(marker)
    assert start != -1, "Cannot find _getHtmlContent signature"
    open_brace = source.find("{", start)
    assert open_brace != -1, "Cannot find _getHtmlContent opening brace"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace + 1 : i]
        i += 1
    raise AssertionError("Unbalanced _getHtmlContent body")


def test_inline_locale_signature_builds_without_map_join_array() -> None:
    body = _extract_get_html_content_body(_source())

    assert "const localeNames = Object.keys(allLocales).sort();" in body
    assert 'let localeSignature = "";' in body
    assert "for (let i = 0; i < localeNames.length; i += 1)" in body
    assert 'if (i > 0) localeSignature += "|";' in body
    assert "Object.keys(allLocales[name] || {}).length" in body
    assert ".map((n) => `${n}:${Object.keys(allLocales[n] || {}).length}`)" not in body
    assert '.join("|")' not in body


def test_inline_locale_signature_preserves_sorted_name_and_key_count_contract() -> None:
    script = textwrap.dedent(
        """
        const allLocales = {
          "zh-CN": { a: 1, b: 2 },
          en: { a: 1 },
          "zh-TW": {},
        };
        const localeNames = Object.keys(allLocales).sort();
        let localeSignature = "";
        for (let i = 0; i < localeNames.length; i += 1) {
          const name = localeNames[i];
          if (i > 0) localeSignature += "|";
          localeSignature += `${name}:${Object.keys(allLocales[name] || {}).length}`;
        }
        console.log(JSON.stringify({ localeNames, localeSignature }));
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "localeNames": ["en", "zh-CN", "zh-TW"],
        "localeSignature": "en:1|zh-CN:2|zh-TW:0",
    }
