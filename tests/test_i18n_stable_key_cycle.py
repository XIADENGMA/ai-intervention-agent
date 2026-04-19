"""Cycle-safe + JSON.stringify-aligned cache key for ``_stableStringify``.

Why this matters
----------------
H1 (Batch-1.5) added ``_stableStringify`` so semantically-identical Intl
options collapse to a single LRU cache entry. That fix landed a recursive
tree walk **without** a ``WeakSet`` seen guard and **without** ``toJSON``
alignment. Three edge cases the subsequent hardening must cover:

1. **Circular Intl options.** ``Intl.NumberFormat`` / ``Intl.DateTimeFormat``
   silently ignore properties they don't know about (verified empirically
   with ``node -e``), so callers can legally pass a structure that cycles
   through an unrelated debug field (``opts.context = opts``). Our
   recursion then overflows the call stack; the ``try/catch`` inside
   ``_intlKey`` rescues the throw but dumps every cyclic caller into the
   same ``lang|?`` bucket, so **distinct cyclic options share a single
   Intl instance** — a correctness bug, not just a perf wart.

2. **Date options.** ``JSON.stringify(new Date(0))`` returns the ISO
   string because ``Date.prototype.toJSON`` exists; our current walk
   enumerates ``Object.keys(date)`` which is empty, so every Date folds
   into ``{}`` and callers that vary a Date field collide.

3. **Shape differentiation under fallback.** Even when stringify does
   legitimately fail (circular / BigInt / Symbol), distinct ``opts``
   shapes must still differ in the cache key — otherwise we leak a
   cross-caller Intl instance that mangles output.

Fix contract (for both ``static/js/i18n.js`` and ``packages/vscode/i18n.js``)
---------------------------------------------------------------------------
* ``_stableStringify`` recurses with a ``WeakSet`` seen guard; cycles
  throw a sentinel that ``_intlKey`` can identify.
* ``_stableStringify`` honours ``toJSON`` on objects that define it
  (Date, Temporal, any caller-provided serialiser), matching
  ``JSON.stringify`` semantics byte-for-byte.
* ``_intlKey`` falls back to a **shape signature** (sorted list of
  own top-level keys) when stringify fails, so distinct cyclic shapes
  never collide to ``|?``.
* Web UI and VSCode copies stay byte-parallel — same canonical key on
  identical input, covered by the byte-parity check at the bottom.
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


class _CycleMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def test_cyclic_options_do_not_crash_and_produce_a_cache_entry(self) -> None:
        """``a.self = a`` must not take the whole runtime down."""
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var a = { style: 'decimal', context: null };
            a.context = a;
            var out = api.formatNumber(1, a);
            process.stdout.write(JSON.stringify({
              out: out,
              size: dbg.getIntlCacheSize('NumberFormat'),
            }));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["out"], "1")
        self.assertEqual(payload["size"], 1)

    def test_distinct_cyclic_shapes_do_not_collide_on_question_mark(self) -> None:
        """Two cyclic opts with different top-level keys must live in
        separate cache entries; otherwise we leak a formatter across
        unrelated callers.
        """
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var a = { style: 'decimal', aSide: null };
            a.aSide = a;
            var b = { style: 'decimal', bSide: null };
            b.bSide = b;
            api.formatNumber(1, a);
            api.formatNumber(1, b);
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 2)

    def test_date_options_align_with_json_stringify_semantics(self) -> None:
        """``JSON.stringify`` calls ``toJSON`` on Date; _stableStringify
        must do the same, so two distinct Date values in an option bag
        do NOT collapse to a single empty-object key.
        """
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.formatDate(new Date(0), { dateStyle: 'short' });
            api.formatDate(new Date(0), { dateStyle: 'short' });
            api.formatNumber(1, { style: 'decimal', pinned: new Date(0) });
            api.formatNumber(1, { style: 'decimal', pinned: new Date(86400000) });
            var dateSize = dbg.getIntlCacheSize('DateTimeFormat');
            var numSize = dbg.getIntlCacheSize('NumberFormat');
            process.stdout.write(JSON.stringify([dateSize, numSize]));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            json.loads(out),
            [1, 2],
            "Date opts must dedup on identical values and split on different values.",
        )

    def test_custom_tojson_is_honoured(self) -> None:
        """Any object with a ``toJSON`` method should round-trip through
        it, matching ``JSON.stringify``.
        """
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var tag = function (label) {
              return { toJSON: function () { return 'tag:' + label; } };
            };
            api.formatNumber(1, { style: 'decimal', tag: tag('A') });
            api.formatNumber(2, { style: 'decimal', tag: tag('A') });
            api.formatNumber(3, { style: 'decimal', tag: tag('B') });
            process.stdout.write(String(dbg.getIntlCacheSize('NumberFormat')));
            """
        ).strip()
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(int(out.strip()), 2)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestCycleWebUI(_CycleMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestCycleVSCode(_CycleMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestCycleByteParity(unittest.TestCase):
    """Both halves must serialise identical canonical keys even in the
    degraded-cycle branch; otherwise a contributor debugging
    ``AIIA_I18N__test.peekIntlCacheKeys('NumberFormat')`` in Web UI and
    VSCode would see inexplicable drift.
    """

    def test_cycle_fallback_key_bytes_match(self) -> None:
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var a = { style: 'decimal', probeA: null };
            a.probeA = a;
            var b = { style: 'decimal', probeB: null };
            b.probeB = b;
            api.formatNumber(1, a);
            api.formatNumber(1, b);
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
            "cycle-fallback cache key bytes drifted between Web UI and VSCode i18n.js",
        )


if __name__ == "__main__":
    unittest.main()
