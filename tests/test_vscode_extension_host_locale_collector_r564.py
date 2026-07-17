"""R564 regression coverage for VS Code host locale promise collection."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_TS = REPO_ROOT / "packages" / "vscode" / "extension.ts"


def _source() -> str:
    return EXTENSION_TS.read_text(encoding="utf-8")


def _extract_block(source: str, start: int) -> str:
    open_brace = source.find("{", start)
    assert open_brace != -1, "Cannot find opening brace"
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
    raise AssertionError("Unbalanced block")


def test_extension_host_locale_loading_uses_loop_collector_not_map_callback() -> None:
    source = _source()
    helper_start = source.find("async function loadHostLocale(")
    activate_start = source.find("async function activate(")
    assert helper_start != -1
    assert activate_start != -1
    helper = _extract_block(source, helper_start)
    activate = _extract_block(source, activate_start)

    assert '["en", "zh-CN"].map' not in activate
    assert ".map(async" not in activate
    assert "const localeReads: Promise<void>[] = []" in activate
    assert 'for (const loc of ["en", "zh-CN"])' in activate
    assert "localeReads.push(loadHostLocale(localesDir, loc, hostLocales))" in activate
    assert "await Promise.all(localeReads)" in activate
    assert "fs.promises.readFile" in helper
    assert "path.join(localesDir, `${loc}.json`)" in helper
    assert "hostLocales[loc] = JSON.parse(raw)" in helper
    assert "catch" in helper


def test_extension_host_locale_collector_preserves_parallel_fail_soft_loading() -> None:
    script = textwrap.dedent(
        """
        ;(async () => {
        const path = { join: (...parts) => parts.join('/') }
        const starts = []
        const resolvers = []
        const fs = {
          promises: {
            readFile(filePath, encoding) {
              starts.push([filePath, encoding])
              return new Promise((resolve, reject) => {
                resolvers.push({ filePath, resolve, reject })
              })
            }
          }
        }

        async function loadHostLocale(localesDir, loc, hostLocales) {
          try {
            const raw = await fs.promises.readFile(
              path.join(localesDir, `${loc}.json`),
              'utf8',
            )
            if (raw) hostLocales[loc] = JSON.parse(raw)
          } catch {
            /* ignore */
          }
        }

        const hostLocales = {}
        const localeReads = []
        for (const loc of ['en', 'zh-CN']) {
          localeReads.push(loadHostLocale('/ext/locales', loc, hostLocales))
        }
        const startedBeforeAwait = starts.slice()
        resolvers[0].resolve(JSON.stringify({ statusBar: { ok: 'OK' } }))
        resolvers[1].reject(new Error('missing locale'))
        await Promise.all(localeReads)

        process.stdout.write(JSON.stringify({
          startedBeforeAwait,
          hostLocales,
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
        "startedBeforeAwait": [
            ["/ext/locales/en.json", "utf8"],
            ["/ext/locales/zh-CN.json", "utf8"],
        ],
        "hostLocales": {"en": {"statusBar": {"ok": "OK"}}},
    }
