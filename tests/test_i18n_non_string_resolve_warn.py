"""Warn-once observability for ``resolve`` hitting a non-string value.

Why this matters
----------------
The H3 hardening that added prototype-pollution guards also tightened
``resolve(key, lang)`` so that any traversal that ends on a non-string
(typically an object, meaning the caller aimed at a namespace instead
of a leaf) returns ``undefined``. That's the right safety default, but
it collapses two genuinely different developer mistakes into a single
"key missing" warning path:

  * ``t('aiia.foo.bar')`` where the locale file never defined
    ``aiia.foo.bar`` — the warning is actionable ("add the key").
  * ``t('aiia.foo')`` where the locale file has
    ``{ aiia: { foo: { bar: '…' } } }`` — the correct fix is to
    ``t('aiia.foo.bar')``. The current warning tells the dev to
    "add a missing key aiia.foo", so they helpfully add a duplicate
    leaf and shadow the namespace (bug).

The standard i18next fix (see ``i18next`` GH #1594 "non-string leaf")
is to emit a **separate, warn-once** diagnostic that identifies the
shape of the value the key did resolve to. Our parity contract with
the missing-key handler means we need to do the same on both the Web
UI and the VSCode webview.

Fix contract
------------
* When ``resolve(key, lang)`` reaches the last segment and finds a
  non-``string`` value (object / number / bool / null / undefined —
  i.e. anything that would make ``typeof !== 'string'`` true), record
  the miss in a **per-key-per-locale** once-set.
* First hit for a given ``(lang, key)`` pair emits
  ``console.warn('[i18n] resolved non-string: …')`` with a concrete
  hint that nested subkeys exist.
* Subsequent hits for the same pair do **not** warn (no log spam).
* Test-only introspection hooks ``dbg.getNonStringHits()`` and
  ``dbg.resetNonStringHits()`` are exposed under
  ``AIIA_I18N__test`` — kept off the public API.
* Strict mode (``setStrict(true)``) throws on non-string resolutions
  so the build catches the misuse upstream, matching the existing
  strict-mode semantics for plain missing keys.
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


def _run_node(i18n_path: Path, body: str) -> tuple[int, str, str]:
    harness = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: 'en' };
        require(%(path)s);
        const api = globalThis.AIIA_I18N;
        const dbg = globalThis.AIIA_I18N__test;
        if (!dbg) {
          process.stderr.write('missing AIIA_I18N__test hook');
          process.exit(2);
        }
        api.registerLocale('en', { aiia: { foo: { bar: 'deep' } }, plain: 'ok' });
        api.setLang('en');
        dbg.resetNonStringHits && dbg.resetNonStringHits();
        """
    ) % {"path": json.dumps(str(i18n_path))}
    proc = subprocess.run(
        ["node", "-e", harness + "\n" + body],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


class _NonStringResolveMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def test_first_hit_emits_console_warn_with_actionable_hint(self) -> None:
        body = textwrap.dedent(
            """
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            var out = api.t('aiia.foo');
            process.stdout.write(JSON.stringify({ out: out, warnings: warnings }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(
            payload["out"],
            "aiia.foo",
            "t() must still degrade to the raw key (same contract as "
            "missing-key), so UI shows something rather than 'undefined'.",
        )
        self.assertEqual(
            len(payload["warnings"]),
            1,
            "Non-string resolve must warn exactly once on first hit.",
        )
        warning = payload["warnings"][0]
        self.assertIn("[i18n]", warning)
        self.assertIn("aiia.foo", warning)
        self.assertIn("non-string", warning.lower())

    def test_repeated_hits_do_not_spam_console(self) -> None:
        body = textwrap.dedent(
            """
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            for (var i = 0; i < 5; i++) api.t('aiia.foo');
            process.stdout.write(String(warnings.length));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 1)

    def test_distinct_keys_each_warn_once(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              aiia: { foo: { bar: 'deep' }, baz: { qux: 'deeper' } }
            });
            dbg.resetNonStringHits();
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            api.t('aiia.foo'); api.t('aiia.foo');
            api.t('aiia.baz'); api.t('aiia.baz');
            process.stdout.write(String(warnings.length));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 2)

    def test_plain_missing_key_path_untouched(self) -> None:
        """The existing missing-key warning path must keep its own
        signature (``missing key``) so dashboards and log scrapers that
        already distinguish the two never see one masquerading as the
        other.
        """
        body = textwrap.dedent(
            """
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            api.t('aiia.never-defined');
            process.stdout.write(JSON.stringify(warnings));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        warnings = json.loads(out)
        joined = "\n".join(warnings).lower()
        self.assertNotIn("non-string", joined)

    def test_hits_are_introspectable_for_tests(self) -> None:
        body = textwrap.dedent(
            """
            api.t('aiia.foo');
            api.t('aiia.foo');
            process.stdout.write(JSON.stringify(dbg.getNonStringHits()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        hits = json.loads(out)
        self.assertEqual(len(hits), 1)
        entry = hits[0]
        self.assertEqual(entry["lang"], "en")
        self.assertEqual(entry["key"], "aiia.foo")
        self.assertEqual(entry["type"], "object")

    def test_strict_mode_throws_on_non_string_resolve(self) -> None:
        body = textwrap.dedent(
            """
            api.setStrict(true);
            var threw = false;
            try { api.t('aiia.foo'); }
            catch (e) { threw = (e && e.message || String(e)); }
            process.stdout.write(String(threw));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertNotEqual(out.strip(), "false")
        self.assertIn("aiia.foo", out)

    def test_reset_clears_the_once_set(self) -> None:
        body = textwrap.dedent(
            """
            var warnings = [];
            console.warn = function () {
              warnings.push(Array.from(arguments).join(' '));
            };
            api.t('aiia.foo');
            dbg.resetNonStringHits();
            api.t('aiia.foo');
            process.stdout.write(String(warnings.length));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 2)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestNonStringResolveWebUI(_NonStringResolveMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestNonStringResolveVSCode(_NonStringResolveMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


if __name__ == "__main__":
    unittest.main()
