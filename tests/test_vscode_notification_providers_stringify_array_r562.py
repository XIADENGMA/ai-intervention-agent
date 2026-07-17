"""R562 regression coverage for VS Code notification diagnostic array stringification."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVIDERS_TS = REPO_ROOT / "packages" / "vscode" / "notification-providers.ts"


def _source() -> str:
    return PROVIDERS_TS.read_text(encoding="utf-8")


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


def test_notification_provider_diagnostics_use_shared_string_array_helper() -> None:
    source = _source()
    helper = _extract_function(source, "function stringifyArrayValues(")

    assert "args.map(String)" not in source
    assert ".map(String)" not in _extract_function(
        source,
        "_extractAppleScriptError(e: unknown): AppleScriptErrorInfo",
    )
    assert "function stringifyArrayValues(values: unknown): string[]" in source
    assert "if (!Array.isArray(values)) return []" in helper
    assert "const out: string[] = []" in helper
    assert "for (const value of values)" in helper
    assert "out.push(String(value))" in helper
    assert "return out" in helper
    assert source.count("stringifyArrayValues(args)") == 3
    assert "stringifyArrayValues(details.injectedEnvKeys)" in source


def test_stringify_array_values_preserves_string_conversion_contract() -> None:
    script = textwrap.dedent(
        """
        function stringifyArrayValues(values) {
          if (!Array.isArray(values)) return []
          const out = []
          for (const value of values) {
            out.push(String(value))
          }
          return out
        }

        process.stdout.write(JSON.stringify({
          nonArray: stringifyArrayValues({ 0: 'x', length: 1 }),
          mixed: stringifyArrayValues(['a', 2, null, undefined, true]),
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
        "nonArray": [],
        "mixed": ["a", "2", "null", "undefined", "true"],
    }
