"""P9·L5·G2 — missing-key 观测钩子。

``t(key)`` 命中不到时回显原 key 对 UI robustness 很好，但完全屏蔽
了 dev 反馈循环。三条 API 补上：
  * ``setMissingKeyHandler(fn)``——``(key, lang)`` 回调，dev tooling
    / prod telemetry 用；
  * ``setStrict(on)``——无 handler 时 ``t()`` 直接抛，dev build + 单测搭配；
  * ``getMissingKeyStats()`` / ``resetMissingKeyStats()``——key→count，
    给 dev dashboard 高亮热 key。

两份 ``i18n.js`` 都要锁合约；通过 node subprocess 跑真实 IIFE，与
``test_i18n_icu_plural.py`` 对齐。
"""

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

    def test_handler_throw_emits_console_warn(self) -> None:
        # Observability requirement (L3·G3 follow-up): when the caller's
        # missing-key handler throws AND strict=false, we must still
        # surface the error via ``console.warn`` so it shows up in the
        # devtools / host extension log. Silent swallowing hides real
        # telemetry bugs; this test pins the parity between the Web UI
        # and VSCode halves so the two copies can't drift again.
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
                    api.setMissingKeyHandler(() => {
                      throw new Error('handler-boom');
                    });
                    process.stdout.write(api.t('missing.key'));
                    """
                ).strip()
                % {"path": json.dumps(str(self.I18N_PATH))},
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "missing.key")
        # Node's ``console.warn`` writes to stderr. The runtime must
        # mention both the fault (error message) and enough context to
        # identify which handler failed.
        self.assertIn("handler-boom", proc.stderr)
        self.assertIn("missing-key handler", proc.stderr)

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
