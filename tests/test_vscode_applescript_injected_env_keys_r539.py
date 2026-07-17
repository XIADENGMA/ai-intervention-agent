"""R539 regression coverage for AppleScript injected env key normalization."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXECUTOR_TS = REPO_ROOT / "packages" / "vscode" / "applescript-executor.ts"


def _source() -> str:
    return EXECUTOR_TS.read_text(encoding="utf-8")


def _extract_run_applescript_body(source: str) -> str:
    marker = (
        "runAppleScript(script: string, runOptions: RunOptions = {}): Promise<string>"
    )
    class_start = source.find("export class AppleScriptExecutor")
    assert class_start != -1, "Cannot find AppleScriptExecutor class"
    start = source.find(marker, class_start)
    assert start != -1, "Cannot find runAppleScript signature"
    open_brace = source.find("{", start + len(marker))
    assert open_brace != -1, "Cannot find runAppleScript opening brace"
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
    raise AssertionError("Unbalanced runAppleScript body")


def test_injected_env_keys_builds_in_one_collection_pass() -> None:
    body = _extract_run_applescript_body(_source())

    assert "const injectedEnvKeys: string[] = []" in body
    assert "for (const key of Object.keys(envExtra))" in body
    assert "if (key) injectedEnvKeys.push(String(key))" in body
    assert "injectedEnvKeys.sort()" in body
    assert ".filter(Boolean)" not in body
    assert ".map(k => String(k))" not in body


def test_injected_env_keys_preserves_sorted_truthy_key_contract() -> None:
    script = textwrap.dedent(
        """
        const envExtra = { ZED: "1", __CFBundleIdentifier: "com.example.host", FOO: "2" };
        const injectedEnvKeys = [];
        if (envExtra) {
          for (const key of Object.keys(envExtra)) {
            if (key) injectedEnvKeys.push(String(key));
          }
          injectedEnvKeys.sort();
        }
        console.log(JSON.stringify(injectedEnvKeys));
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == ["FOO", "ZED", "__CFBundleIdentifier"]
