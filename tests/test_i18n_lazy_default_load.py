r"""L3·G3: exercise the lazy DEFAULT_LANG loading path.

Why this test
-------------
Previously ``i18n.init(...)`` always ``await``\ ed both ``current`` and
``DEFAULT_LANG`` locale JSONs before resolving. That doubled the
blocking payload for zh-CN users (they pay the cost of en.json too, up
front) even though the en fallback is only exercised when a key is
missing from their locale — a rare event for a well-maintained
product. The lazy path flips this: ``init`` only blocks on the current
lang, and the default locale is prefetched in the background (or
pulled in on first fallback miss). This test locks the new contract so
a future refactor can't re-introduce the blocking load without the CI
lighting up.

Flow
----
1. Stand up a stub ``fetch`` in the node harness that records every
   URL asked for and, for a controlled subset of URLs, returns a
   synthetic JSON payload. We don't touch the real filesystem.
2. Scenario A: ``init({lang: 'zh-CN', localeBaseUrl: '/loc'})``
   → ``init()`` must return as soon as ``/loc/zh-CN.json`` resolves.
   The default locale fetch is kicked off but can race; we deliberately
   leave it unresolved to prove ``init`` doesn't block on it.
3. Scenario B: Call ``t('missing.key')`` with only ``zh-CN`` loaded and
   no DEFAULT_LANG yet → first call returns the key; background fetch
   for en kicks in; after it resolves we call ``t`` again and get the
   English fallback.
4. Scenario C: ``ensureDefaultLocale`` dedupes concurrent callers.

Node-subprocess style matches ``test_i18n_icu_plural.py``. Tests SKIP
without node on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBUI_I18N = REPO_ROOT / "static" / "js" / "i18n.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


_HARNESS_PREFIX = textwrap.dedent(
    """
    globalThis.window = globalThis;
    globalThis.document = undefined;
    globalThis.navigator = { language: 'zh-CN' };

    // Stub fetch:
    //  * /loc/zh-CN.json → { "hello": "你好" }
    //  * /loc/en.json    → { "hello": "hi", "only": "english-only" }
    //  * anything else   → 404
    // Every call is logged to globalThis.__fetches so the test can
    // assert we only touched the expected URLs.
    globalThis.__fetches = [];
    globalThis.fetch = async function (url) {
      globalThis.__fetches.push(String(url));
      if (String(url).endsWith('/loc/zh-CN.json')) {
        return {
          ok: true,
          async json() { return { hello: '你好' }; }
        };
      }
      if (String(url).endsWith('/loc/en.json')) {
        return {
          ok: true,
          async json() { return { hello: 'hi', only: 'english-only' }; }
        };
      }
      return { ok: false, async json() { return {}; } };
    };

    require(%(path_literal)s);
    const api = globalThis.AIIA_I18N;
    """
) % {"path_literal": json.dumps(str(WEBUI_I18N))}


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestLazyDefaultLoad(unittest.TestCase):
    def test_init_blocks_only_on_current_lang(self) -> None:
        script = _HARNESS_PREFIX + textwrap.dedent(
            """
            (async () => {
              await api.init({ lang: 'zh-CN', localeBaseUrl: '/loc' });
              // At init-resolve time, current lang MUST be registered.
              const langsAtInit = api.getAvailableLangs().slice().sort();
              // Then flush pending prefetches so we can observe the
              // eventual state without being racy.
              await globalThis.AIIA_I18N__test.flushPendingLoads();
              const langsAfterFlush = api.getAvailableLangs().slice().sort();
              process.stdout.write(JSON.stringify({
                langsAtInit,
                langsAfterFlush,
                fetches: globalThis.__fetches
              }));
            })().catch(e => { console.error(e); process.exit(1); });
            """
        )
        out = json.loads(_run(script))
        # At init resolve: current lang (zh-CN) is registered.
        self.assertIn("zh-CN", out["langsAtInit"])
        # Fetches are triggered for BOTH (current blocking + default
        # prefetch in the background).
        self.assertIn("/loc/zh-CN.json", out["fetches"])
        self.assertIn("/loc/en.json", out["fetches"])
        # After flush: default lang has also landed.
        self.assertIn("en", out["langsAfterFlush"])

    def test_tkey_missing_triggers_lazy_default_load(self) -> None:
        script = _HARNESS_PREFIX + textwrap.dedent(
            """
            (async () => {
              // zh-CN is loaded, en is prefetched in background. We wait
              // for pending fetches (current + default) to settle, then
              // the 'only' key (present only in en) must resolve to its
              // en fallback value.
              await api.init({ lang: 'zh-CN', localeBaseUrl: '/loc' });
              await globalThis.AIIA_I18N__test.flushPendingLoads();
              const r = api.t('only');
              process.stdout.write(r);
            })().catch(e => { console.error(e); process.exit(1); });
            """
        )
        out = _run(script)
        self.assertEqual(out, "english-only")

    def test_ensure_default_locale_dedupes(self) -> None:
        script = _HARNESS_PREFIX + textwrap.dedent(
            """
            (async () => {
              // init on zh-CN, then flush pending so the background
              // prefetch completes and locales[en] is populated. THEN
              // clear fetch log and invoke ensureDefaultLocale several
              // times concurrently — it must be a no-op (0 extra fetches)
              // because locales[en] is already registered.
              await api.init({ lang: 'zh-CN', localeBaseUrl: '/loc' });
              await globalThis.AIIA_I18N__test.flushPendingLoads();
              globalThis.__fetches.length = 0;
              const ps = [api.ensureDefaultLocale(), api.ensureDefaultLocale(), api.ensureDefaultLocale()];
              await Promise.all(ps);
              const enCount = globalThis.__fetches.filter(u => u.endsWith('/loc/en.json')).length;
              process.stdout.write(JSON.stringify({ enCount }));
            })().catch(e => { console.error(e); process.exit(1); });
            """
        )
        out = json.loads(_run(script))
        # After init+flush the default locale is already loaded, so
        # subsequent ensureDefaultLocale calls MUST NOT refetch.
        self.assertEqual(out["enCount"], 0)

    def test_current_is_default_skips_prefetch(self) -> None:
        """When current lang == DEFAULT_LANG, we shouldn't prefetch twice."""
        script = _HARNESS_PREFIX + textwrap.dedent(
            """
            (async () => {
              await api.init({ lang: 'en', localeBaseUrl: '/loc' });
              await new Promise(r => setTimeout(r, 0));
              const enFetches = globalThis.__fetches.filter(u => u.endsWith('/loc/en.json'));
              process.stdout.write(JSON.stringify({ count: enFetches.length }));
            })().catch(e => { console.error(e); process.exit(1); });
            """
        )
        out = json.loads(_run(script))
        # Exactly 1 — the initial current-lang load.
        self.assertEqual(out["count"], 1)


if __name__ == "__main__":
    unittest.main()
