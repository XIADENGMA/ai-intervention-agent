"""L3·G2 follow-up — bound the Intl formatter instance cache.

Background
----------
``_getIntl`` memoises ``Intl.NumberFormat`` / ``Intl.DateTimeFormat`` /
``Intl.RelativeTimeFormat`` / ``Intl.ListFormat`` instances by the triple
``(ctor, locale, JSON(options))``. Construction of an ``Intl.*`` instance
is measured in **milliseconds** on mobile Safari and low-end Android
WebViews — see the Node.js performance issue tracker — so memoisation
is genuinely necessary, but the current implementation has no upper
bound. A long-running Web UI session that chats through many distinct
``formatNumber`` option combinations (e.g. per-row currency toggles,
``maximumFractionDigits`` variations, ad-hoc style objects) would leak
instances indefinitely, and the VSCode extension host ships with no
guardrail either.

Fix contract
------------
Both ``static/js/i18n.js`` and ``packages/vscode/i18n.js`` grow a very
small LRU around ``_intlCache`` and ``_pluralRulesCache``:

    AIIA_I18N__intl_lru_max            = 50   # per-ctor cap
    AIIA_I18N__plural_rules_lru_max    = 16   # per-module cap

Eviction is classic LRU: every cache hit reshuffles the key to the tail
of an insertion-order set; on insert, if size > max, drop the head.

To make the behaviour testable without exporting internals into the
public API, we expose an ``AIIA_I18N__test`` namespace that only the
pytest harness speaks to. The real application code never reads it. The
hook is intentionally keyed to a double-underscore prefix so source
review can grep it out in one pass.

Why this file matters
---------------------
Without a test pinning the LRU size and the eviction order, a future
contributor could silently unbound the cache again — and we'd only
discover it months later from a memory profile. The test suite below
parameterises against both copies of ``i18n.js``; ``test_byte_parity``
enforces that eviction decisions match across the two halves for the
same input sequence so drift becomes a test failure, not a field bug.
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

# Must match the constants baked into both i18n.js copies. If either
# copy drifts these two numbers, the test will loudly fail rather than
# quietly accept a looser bound.
INTL_LRU_MAX = 50
PLURAL_RULES_LRU_MAX = 16


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
        api.setLang('en');
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


class _IntlLruMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    # ---- NumberFormat / DateTimeFormat / RelativeTimeFormat / ListFormat ----

    def test_intl_cache_respects_hard_cap_on_distinct_options(self) -> None:
        # Feed 2x the cap worth of truly-distinct NumberFormat option
        # triples (monotonic ``maximumFractionDigits`` so every ``i``
        # maps to a fresh cache key). The per-ctor bucket MUST NOT grow
        # past ``INTL_LRU_MAX``; if it does, we've reintroduced the
        # unbounded-cache leak.
        body = textwrap.dedent(
            f"""
            dbg.clearIntlCaches();
            for (let i = 0; i < {INTL_LRU_MAX * 2}; i++) {{
              api.formatNumber(i, {{ maximumFractionDigits: i }});
            }}
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        size = int(out.strip())
        self.assertEqual(
            size,
            INTL_LRU_MAX,
            "NumberFormat cache should saturate at exactly the LRU cap "
            f"after feeding {INTL_LRU_MAX * 2} distinct options; got {size}",
        )

    def test_intl_cache_evicts_oldest_first(self) -> None:
        # Classic LRU check:
        #   1. Fill cache with OPT_0..OPT_{max-1}.
        #   2. Touch OPT_0 (moves it to MRU tail).
        #   3. Insert OPT_max (forces eviction). With LRU, OPT_1 goes,
        #      not OPT_0.
        body = textwrap.dedent(
            f"""
            dbg.clearIntlCaches();
            for (let i = 0; i < {INTL_LRU_MAX}; i++) {{
              api.formatNumber(0, {{ maximumFractionDigits: i }});
            }}
            // Touch OPT_0 -- promotes it to MRU.
            api.formatNumber(0, {{ maximumFractionDigits: 0 }});
            // Insert fresh entry past the cap.
            api.formatNumber(0, {{ maximumFractionDigits: {INTL_LRU_MAX + 999} }});
            const keys = dbg.peekIntlCacheKeys('NumberFormat');
            const containsOpt0 = keys.some(k => k.endsWith('{{"maximumFractionDigits":0}}'));
            const containsOpt1 = keys.some(k => k.endsWith('{{"maximumFractionDigits":1}}'));
            process.stdout.write(JSON.stringify({{
              size: keys.length,
              opt0Survives: containsOpt0,
              opt1Evicted: !containsOpt1
            }}));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual(
            report["size"],
            INTL_LRU_MAX,
            f"cache size wrong after eviction: {report}",
        )
        self.assertTrue(
            report["opt0Survives"],
            "LRU reshuffle failed: OPT_0 was evicted after being touched",
        )
        self.assertTrue(
            report["opt1Evicted"],
            "LRU eviction failed: oldest non-touched entry (OPT_1) should have been dropped",
        )

    def test_intl_cache_hit_does_not_grow_bucket(self) -> None:
        # Calling the same (ctor, locale, options) triple twice must
        # reuse the cached instance, not create a second one.
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatNumber(42, { maximumFractionDigits: 2 });
            const first = dbg.getIntlCacheSize('NumberFormat');
            api.formatNumber(42, { maximumFractionDigits: 2 });
            api.formatNumber(42, { maximumFractionDigits: 2 });
            const third = dbg.getIntlCacheSize('NumberFormat');
            process.stdout.write(JSON.stringify({ first: first, third: third }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual(report["first"], 1)
        self.assertEqual(report["third"], 1)

    def test_intl_cache_is_partitioned_per_ctor(self) -> None:
        # Filling NumberFormat to capacity must not evict entries from
        # DateTimeFormat. We don't want one high-churn formatter to
        # starve the others.
        body = textwrap.dedent(
            f"""
            dbg.clearIntlCaches();
            api.formatDate(new Date(0), {{ dateStyle: 'short' }});
            for (let i = 0; i < {INTL_LRU_MAX * 2}; i++) {{
              api.formatNumber(i, {{ maximumFractionDigits: i }});
            }}
            const dtSize = dbg.getIntlCacheSize('DateTimeFormat');
            const nfSize = dbg.getIntlCacheSize('NumberFormat');
            process.stdout.write(JSON.stringify({{ dtSize, nfSize }}));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual(
            report["dtSize"],
            1,
            f"DateTimeFormat cache was touched by NumberFormat churn: {report}",
        )
        self.assertLessEqual(report["nfSize"], INTL_LRU_MAX)

    # ---- PluralRules cache (separate bucket, separate cap) ----

    def test_plural_rules_cache_respects_hard_cap(self) -> None:
        # Each distinct BCP-47 tag gets its own PluralRules instance.
        # The cache must cap at PLURAL_RULES_LRU_MAX so a hostile page
        # can't balloon memory by cycling locales.
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            const tags = [
              'en','en-US','en-GB','en-CA','en-AU',
              'zh','zh-CN','zh-TW','zh-HK','zh-SG',
              'fr','fr-FR','fr-CA','fr-CH','fr-BE',
              'de','de-DE','de-AT','de-CH',
              'es','es-ES','es-MX','es-AR','es-CL',
              'ja','ja-JP','ko','ko-KR',
              'ru','ru-RU','pt','pt-BR','pt-PT',
              'it','it-IT','nl','nl-BE','pl','tr','ar','ar-SA','he','cs','sk','hu','ro','sv','da','fi','no'
            ];
            for (const tag of tags) {
              api.setLang(tag);
              api.registerLocale(tag, { m: '{c, plural, one {# item} other {# items}}' });
              api.t('m', { c: 1 });
            }
            process.stdout.write(String(dbg.getPluralRulesCacheSize()));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        size = int(out.strip())
        self.assertLessEqual(
            size,
            PLURAL_RULES_LRU_MAX,
            f"PluralRules cache grew unbounded: size={size} > {PLURAL_RULES_LRU_MAX}",
        )

    def test_clear_helper_actually_drops_all_buckets(self) -> None:
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatNumber(1);
            api.formatDate(new Date(0));
            api.registerLocale('en', { m: '{c, plural, one {# x} other {# xs}}' });
            api.t('m', { c: 2 });
            const before = JSON.stringify({
              nf: dbg.getIntlCacheSize('NumberFormat'),
              dt: dbg.getIntlCacheSize('DateTimeFormat'),
              pr: dbg.getPluralRulesCacheSize()
            });
            dbg.clearIntlCaches();
            const after = JSON.stringify({
              nf: dbg.getIntlCacheSize('NumberFormat'),
              dt: dbg.getIntlCacheSize('DateTimeFormat'),
              pr: dbg.getPluralRulesCacheSize()
            });
            process.stdout.write(before + '|' + after);
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        before, after = out.split("|", 1)
        before_obj = json.loads(before)
        after_obj = json.loads(after)
        self.assertGreater(before_obj["nf"], 0)
        self.assertGreater(before_obj["dt"], 0)
        self.assertGreater(before_obj["pr"], 0)
        self.assertEqual(after_obj, {"nf": 0, "dt": 0, "pr": 0})


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIntlLruWebUI(_IntlLruMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIntlLruVSCode(_IntlLruMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestIntlLruByteParity(unittest.TestCase):
    """Both halves must make identical eviction decisions for the same
    input sequence, otherwise the Web UI and VSCode webview would render
    subtly different numbers (e.g. a hot locale ejected in one copy and
    retained in the other)."""

    def test_eviction_order_matches_across_halves(self) -> None:
        body = textwrap.dedent(
            f"""
            dbg.clearIntlCaches();
            for (let i = 0; i < {INTL_LRU_MAX + 10}; i++) {{
              api.formatNumber(0, {{ maximumFractionDigits: i }});
            }}
            process.stdout.write(JSON.stringify(dbg.peekIntlCacheKeys('NumberFormat')));
            """
        ).strip()
        code_w, out_w, err_w = _run_node(WEBUI_I18N, body)
        code_v, out_v, err_v = _run_node(VSCODE_I18N, body)
        self.assertEqual(code_w, 0, err_w)
        self.assertEqual(code_v, 0, err_v)
        self.assertEqual(
            json.loads(out_w),
            json.loads(out_v),
            "LRU eviction order drifted between Web UI and VSCode i18n.js",
        )


if __name__ == "__main__":
    unittest.main()
