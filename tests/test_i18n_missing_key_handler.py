"""P9·L5·G2 — missing-key observability hook.

``t(key)`` silently returning the raw key when a translation is missing
is good for robustness (the UI never goes blank) but terrible for dev
feedback loops — you only find out something's wrong when QA screams.

We added three APIs to close that loop:

- ``setMissingKeyHandler(fn)`` — fired with ``(key, lang)`` whenever a
  lookup falls through. Intended for dev tooling and prod telemetry.
- ``setStrict(on)`` — when no handler is set, this makes ``t()`` *throw*
  on miss. Pair with unit tests + dev builds.
- ``getMissingKeyStats()`` / ``resetMissingKeyStats()`` — a plain
  key → count map so a dev dashboard can surface the hot keys.

These tests pin the contract for both copies (``static/js/i18n.js`` and
``packages/vscode/i18n.js``) so the two never drift. All tests run via
a node subprocess to exercise the real IIFE module, mirroring the ICU
suite in ``test_i18n_icu_plural.py``."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = ROOT / "static" / "js" / "i18n.js"
VSCODE_I18N = ROOT / "packages" / "vscode" / "i18n.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run(i18n_path: Path, body: str) -> str:
    """Load ``i18n.js`` and execute ``body`` verbatim; return stdout."""
    harness = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: 'en' };
        require(%(path_literal)s);
        const api = globalThis.AIIA_I18N;
        api.registerLocale('en', { ok: 'hello' });
        api.setLang('en');
        """
    ) % {"path_literal": json.dumps(str(i18n_path))}
    proc = subprocess.run(
        ["node", "-e", harness + "\n" + body],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


class _MissingKeyMixin(unittest.TestCase):
    __test__ = False

    I18N_PATH: Path

    def test_default_returns_raw_key(self) -> None:
        # Default contract (unchanged from pre-L5): missing key just
        # echoes back.
        out = _run(
            self.I18N_PATH,
            "process.stdout.write(api.t('no.such.key'));",
        )
        self.assertEqual(out, "no.such.key")

    def test_handler_receives_key_and_lang(self) -> None:
        out = _run(
            self.I18N_PATH,
            textwrap.dedent(
                """
                const captured = [];
                api.setMissingKeyHandler((k, l) => captured.push([k, l]));
                api.t('no.such.key');
                api.t('also.missing');
                process.stdout.write(JSON.stringify(captured));
                """
            ).strip(),
        )
        captured = json.loads(out)
        self.assertEqual(
            captured,
            [["no.such.key", "en"], ["also.missing", "en"]],
        )

    def test_handler_suppresses_exception_by_default(self) -> None:
        # If the handler throws, we swallow (strict=false) so UI
        # resilience is preserved.
        out = _run(
            self.I18N_PATH,
            textwrap.dedent(
                """
                api.setMissingKeyHandler(() => {
                  throw new Error('boom');
                });
                const out = api.t('missing.key');
                process.stdout.write(out);
                """
            ).strip(),
        )
        self.assertEqual(out, "missing.key")

    def test_strict_mode_bubbles_exception(self) -> None:
        # Strict + throwing handler → exit 1.
        proc = subprocess.run(
            [
                "node",
                "-e",
                textwrap.dedent(
                    """
                    globalThis.window = globalThis;
                    globalThis.document = undefined;
                    globalThis.navigator = { language: 'en' };
                    require(%(path)s);
                    const api = globalThis.AIIA_I18N;
                    api.registerLocale('en', { ok: 'hello' });
                    api.setLang('en');
                    api.setStrict(true);
                    api.setMissingKeyHandler(() => {
                      throw new Error('boom');
                    });
                    api.t('no.such.key');
                    """
                ).strip()
                % {"path": json.dumps(str(self.I18N_PATH))},
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("boom", proc.stderr)

    def test_strict_mode_without_handler_throws_default_message(self) -> None:
        proc = subprocess.run(
            [
                "node",
                "-e",
                textwrap.dedent(
                    """
                    globalThis.window = globalThis;
                    globalThis.document = undefined;
                    globalThis.navigator = { language: 'en' };
                    require(%(path)s);
                    const api = globalThis.AIIA_I18N;
                    api.registerLocale('en', { ok: 'hello' });
                    api.setLang('en');
                    api.setStrict(true);
                    api.t('no.such.key');
                    """
                ).strip()
                % {"path": json.dumps(str(self.I18N_PATH))},
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing key", proc.stderr)
        self.assertIn("no.such.key", proc.stderr)

    def test_stats_counts_each_miss(self) -> None:
        out = _run(
            self.I18N_PATH,
            textwrap.dedent(
                """
                api.resetMissingKeyStats();
                api.t('missing.a');
                api.t('missing.a');
                api.t('missing.b');
                process.stdout.write(JSON.stringify(api.getMissingKeyStats()));
                """
            ).strip(),
        )
        stats = json.loads(out)
        self.assertEqual(stats, {"missing.a": 2, "missing.b": 1})

    def test_stats_reset_clears_counts(self) -> None:
        out = _run(
            self.I18N_PATH,
            textwrap.dedent(
                """
                api.t('missing.a');
                api.resetMissingKeyStats();
                process.stdout.write(JSON.stringify(api.getMissingKeyStats()));
                """
            ).strip(),
        )
        self.assertEqual(json.loads(out), {})


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestMissingKeyWebUI(_MissingKeyMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestMissingKeyVSCode(_MissingKeyMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


if __name__ == "__main__":
    unittest.main()
