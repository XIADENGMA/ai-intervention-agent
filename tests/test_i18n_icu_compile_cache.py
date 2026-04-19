"""ICU AST compile cache pinning (Batch-3 H12).

Why this matters
----------------
FormatJS's ``intl-messageformat`` splits work into two stages:
``@formatjs/icu-messageformat-parser`` builds a parsed AST once per
template string, then each ``format(params)`` call walks the AST.
Their docs explicitly recommend hoisting the parser result out of
hot loops, and their server-side rendering benchmark shows a 10–30×
speed-up when the AST is cached between requests.

Our in-house runtime has the same shape: ``_findIcuBlock`` +
``_parseIcuOptions`` + ``_readBalancedBlock`` are pure functions of
the raw template string, but today they re-run on every ``t()``
call. ``formatRelativeFromNow`` re-templates task lists every 30 s,
and every row issues 2–5 ``t()`` calls, so the ICU parse cost is
paid hundreds of times per minute for strings that never change.

Batch-3 H12 adds an LRU cache keyed by the **raw template string**
mapping to a compiled descriptor:

    { block: { start, open, close, argName, kind, options } | null,
      trivial: boolean }

``trivial = true`` means the template has no ICU block and
``_renderIcu`` can skip its while-loop entirely and fall through to
mustache interpolation. Non-trivial templates store one compiled
block; subsequent ``t()`` calls reuse the descriptor instead of
re-parsing the string.

Contract
--------
* Same template parsed twice → cache size stays at 1.
* Distinct templates → distinct cache entries.
* Hard LRU cap of 256 entries (matches FormatJS's default
  ``maxCacheSize``). Evicted entries re-parse on next hit.
* Cache hit must produce the same output as a cold parse.
* ``_testingClearIntlCaches()`` clears ICU compile cache too.
* Test-only introspection via ``dbg.getIcuCompileCacheSize()``.
* Web UI ↔ VSCode byte-parity on all of the above.
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
        """
    ) % {"path": json.dumps(str(i18n_path))}
    proc = subprocess.run(
        ["node", "-e", harness + "\n" + body],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


class _IcuCompileCacheMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    # ------------------------------------------------------------------
    # introspection hook exists
    # ------------------------------------------------------------------
    def test_debug_hooks_expose_getter_and_clear(self) -> None:
        body = textwrap.dedent(
            """
            process.stdout.write(JSON.stringify({
              getter: typeof dbg.getIcuCompileCacheSize,
              clear: typeof dbg.clearIntlCaches,
              peek: typeof dbg.peekIcuCompileKeys,
            }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        shape = json.loads(out)
        self.assertEqual(shape["getter"], "function")
        self.assertEqual(shape["clear"], "function")
        self.assertEqual(shape["peek"], "function")

    # ------------------------------------------------------------------
    # 1 template, N calls → 1 entry
    # ------------------------------------------------------------------
    def test_same_template_parses_once_then_hits_cache(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              msg: '{n, plural, one {# item} other {# items}}'
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            for (var i = 0; i < 8; i++) api.t('msg', { n: i });
            process.stdout.write(String(dbg.getIcuCompileCacheSize()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out), 1)

    # ------------------------------------------------------------------
    # trivial templates (no ICU block) are also cached so we don't even
    # re-run _findIcuBlock's regex scan on every t()
    # ------------------------------------------------------------------
    def test_trivial_template_is_marked_and_cached(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              hello: 'Hello {{name}}',
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            for (var i = 0; i < 4; i++) api.t('hello', { name: 'Ada' });
            process.stdout.write(String(dbg.getIcuCompileCacheSize()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out), 1)

    # ------------------------------------------------------------------
    # distinct templates → distinct entries
    # ------------------------------------------------------------------
    def test_distinct_templates_land_in_distinct_entries(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              a: '{n, plural, one {# apple} other {# apples}}',
              b: '{n, plural, one {# banana} other {# bananas}}',
              c: '{n, plural, one {# cherry} other {# cherries}}',
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            api.t('a', { n: 1 }); api.t('b', { n: 1 }); api.t('c', { n: 1 });
            process.stdout.write(String(dbg.getIcuCompileCacheSize()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out), 3)

    # ------------------------------------------------------------------
    # LRU hard cap
    # ------------------------------------------------------------------
    def test_lru_hard_cap_at_256_entries(self) -> None:
        """Push 400 distinct templates through. The cache must stay at
        or below 256 — eviction is proof the LRU is wired, not just a
        growing Map."""
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var bundle = {};
            for (var i = 0; i < 400; i++) {
              bundle['k' + i] = 'row ' + i + ' — {n, plural, one {# one-' + i
                + '} other {# many-' + i + '}}';
            }
            api.registerLocale('en', bundle);
            api.setLang('en');
            for (var j = 0; j < 400; j++) api.t('k' + j, { n: 1 });
            var size = dbg.getIcuCompileCacheSize();
            process.stdout.write(JSON.stringify({ size: size }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertLessEqual(payload["size"], 256)
        self.assertGreaterEqual(payload["size"], 200)  # must be near the cap

    # ------------------------------------------------------------------
    # cache hit produces identical output to cold parse
    # ------------------------------------------------------------------
    def test_cache_hit_produces_correct_output(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              msg: '{n, plural, one {# item} other {# items}}'
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            var cold = api.t('msg', { n: 1 });
            var hot  = api.t('msg', { n: 5 });
            var warm = api.t('msg', { n: 1 });
            process.stdout.write(JSON.stringify({ cold: cold, hot: hot, warm: warm }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["cold"], "1 item")
        self.assertEqual(payload["hot"], "5 items")
        self.assertEqual(payload["warm"], "1 item")

    def test_cache_hit_preserves_apostrophe_escape_semantics(self) -> None:
        """Cached descriptor must remember apostrophe-escaped literals
        exactly as a cold parse would emit them — otherwise two hits
        on the same template diverge."""
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              msg: "{n, plural, one {# it''s one} other {# it''s # items}}"
            });
            api.setLang('en');
            dbg.clearIntlCaches();
            var a = api.t('msg', { n: 1 });
            var b = api.t('msg', { n: 2 });
            var c = api.t('msg', { n: 1 });
            process.stdout.write(JSON.stringify({ a: a, b: b, c: c }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["a"], "1 it's one")
        self.assertEqual(payload["b"], "2 it's 2 items")
        self.assertEqual(payload["c"], "1 it's one")

    # ------------------------------------------------------------------
    # clearIntlCaches() clears ICU compile cache
    # ------------------------------------------------------------------
    def test_clear_intl_caches_also_empties_icu_compile(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', {
              msg: '{n, plural, one {# item} other {# items}}',
              hello: 'Hello {{name}}',
            });
            api.setLang('en');
            api.t('msg', { n: 1 });
            api.t('hello', { name: 'Ada' });
            var before = dbg.getIcuCompileCacheSize();
            dbg.clearIntlCaches();
            var after = dbg.getIcuCompileCacheSize();
            process.stdout.write(JSON.stringify({ before: before, after: after }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertGreaterEqual(payload["before"], 1)
        self.assertEqual(payload["after"], 0)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIcuCompileCacheWebUI(_IcuCompileCacheMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIcuCompileCacheVSCode(_IcuCompileCacheMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIcuCompileCacheByteParity(unittest.TestCase):
    """Both halves must report the same cache geometry for the same
    inputs — if Web grows an entry and VSCode doesn't, the byte-parity
    invariant is broken."""

    TEMPLATES: tuple[tuple[str, str], ...] = (
        ("t0", "Hello {{name}}"),
        ("t1", "{n, plural, one {# item} other {# items}}"),
        ("t2", "{x, select, a {A} b {B} other {O}}"),
        ("t3", "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"),
        ("t4", "trivial literal without placeholders"),
    )

    def test_size_and_keys_match_across_halves(self) -> None:
        reg = ",".join(f"{k!r}: {v!r}" for k, v in self.TEMPLATES)
        body = textwrap.dedent(
            f"""
            api.registerLocale('en', {{{reg}}});
            api.setLang('en');
            dbg.clearIntlCaches();
            for (var i = 0; i < 3; i++) {{
              api.t('t0', {{ name: 'Ada' }});
              api.t('t1', {{ n: 1 }});
              api.t('t2', {{ x: 'a' }});
              api.t('t3', {{ n: 1 }});
              api.t('t4');
            }}
            process.stdout.write(JSON.stringify({{
              size: dbg.getIcuCompileCacheSize(),
              keys: dbg.peekIcuCompileKeys().slice().sort(),
            }}));
            """
        ).strip()
        outputs: list[dict] = []
        for path in (WEBUI_I18N, VSCODE_I18N):
            code, out, err = _run_node(path, body)
            self.assertEqual(code, 0, err)
            outputs.append(json.loads(out))
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
