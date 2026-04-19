"""Stable-sorted cache key for ``_intlCache`` and ``_pluralRulesCache``.

Why this matters
----------------
FormatJS's ``intl-format-cache`` package (canonical reference for the
"memoise ``new Intl.*`` instances" pattern the whole ecosystem uses)
explicitly sorts the options object's keys before JSON-stringifying.
Without that sort, two semantically-identical option objects created
with different key insertion order — e.g. ``{a:1,b:2}`` vs
``Object.assign({}, {b:2}, {a:1})``, or anything produced by spreading
an API response — produce distinct cache keys, silently doubling memory
pressure and shrinking our effective LRU budget.

The surface bug a user would hit:
    formatNumber(1, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
    formatNumber(1, { maximumFractionDigits: 2, currency: 'USD', style: 'currency' })
    // before stable-sort: two entries, cap-50 bucket halves to 25 fresh slots
    // after stable-sort:   one entry, full 50 slots available

Fix contract
------------
Both ``static/js/i18n.js`` and ``packages/vscode/i18n.js`` must:
  * Recursively sort all nested object keys when building the cache key.
  * Treat arrays as order-preserving (arrays have positional semantics
    in every Intl options shape we ship — ``formatToParts`` doesn't
    take any — so we just serialise them in the order given).
  * Produce identical stringified keys for any permutation of nested
    options, across both copies (Web UI / VSCode), so byte-parity
    holds for dashboard-quality caching invariants.

Test harness
------------
We exercise the observable effect (``dbg.getIntlCacheSize`` and
``dbg.peekIntlCacheKeys``) rather than the private ``_intlKey``
function; that keeps the test aligned with the public contract
callers actually depend on.
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
        api.registerLocale('en', {});
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


class _StableKeyMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def test_key_order_permutation_hits_same_bucket_entry(self) -> None:
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatNumber(1, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
            api.formatNumber(2, { maximumFractionDigits: 2, style: 'currency', currency: 'USD' });
            api.formatNumber(3, { currency: 'USD', maximumFractionDigits: 2, style: 'currency' });
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            int(out.strip()),
            1,
            "three semantically-identical option permutations should reuse the "
            "single cached NumberFormat; otherwise LRU starves for dupes.",
        )

    def test_nested_option_keys_are_order_agnostic(self) -> None:
        # ``Intl.DateTimeFormat`` accepts a nested ``hour12`` / ``timeStyle``
        # shape; real-world callers build these via ``Object.assign`` so the
        # key order isn't guaranteed. The cache must treat them as equal.
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatDate(new Date(0), { dateStyle: 'short', timeStyle: 'short' });
            api.formatDate(new Date(0), { timeStyle: 'short', dateStyle: 'short' });
            process.stdout.write(String(dbg.getIntlCacheSize('DateTimeFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 1)

    def test_distinct_option_values_still_occupy_distinct_entries(self) -> None:
        # Stable-sort must NOT collapse genuinely different options into one
        # key; we want dedup, not collision.
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatNumber(1, { style: 'currency', currency: 'USD' });
            api.formatNumber(1, { style: 'currency', currency: 'EUR' });
            api.formatNumber(1, { style: 'decimal' });
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 3)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestStableKeyWebUI(_StableKeyMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestStableKeyVSCode(_StableKeyMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestStableKeyByteParity(unittest.TestCase):
    """Both halves must serialise identical canonical keys so dashboards
    or CI snapshots don't diff when we compare cache dumps across the
    Web UI and the VSCode webview.
    """

    def test_canonical_cache_key_bytes_match(self) -> None:
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatNumber(1, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
            api.formatNumber(2, { maximumFractionDigits: 4, minimumIntegerDigits: 1 });
            api.formatNumber(3, { useGrouping: false, notation: 'compact' });
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
            "stable-sorted cache key bytes drifted between Web UI and VSCode i18n.js",
        )


if __name__ == "__main__":
    unittest.main()
