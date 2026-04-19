"""ICU ``selectordinal`` support + ordinal ``Intl.PluralRules`` LRU.

Why this matters
----------------
ICU MessageFormat distinguishes **cardinal** plurals (``{n, plural, …}``
— "5 items") from **ordinal** plurals (``{n, selectordinal, …}`` —
"5th place"). They resolve against two CLDR rule sets:

* ``Intl.PluralRules(lang)`` – cardinal
* ``Intl.PluralRules(lang, { type: 'ordinal' })`` – ordinal

English is the canonical example where the two rule sets disagree:
``plural(1)`` → ``one``, but ``selectordinal(1)`` → ``one``; ``plural(3)``
→ ``other``, ``selectordinal(3)`` → ``few``. FormatJS, vue-i18n, i18next,
and react-intl all ship ``selectordinal``; the TC39 Intl.MessageFormat
proposal includes it. Without it our runtime silently falls through to
``other`` for every ordinal, and any translator who writes
``{n, selectordinal, …}`` sees their ``one`` / ``two`` / ``few`` branches
ignored.

Fix contract
------------
* ``_findIcuBlock`` recognises ``selectordinal`` as a kind (alongside
  ``plural`` and ``select``).
* A new ``_getPluralRulesOrdinal(lang)`` lookup shares the LRU
  eviction discipline with its cardinal sibling — **16** entries cap,
  testing hooks ``dbg.getPluralRulesOrdinalCacheSize`` /
  ``dbg.peekPluralRulesOrdinalKeys`` for observability.
* ``#`` replacement inside ordinal branches uses the locale's number
  formatter, matching the cardinal contract (depth-0 only,
  inner-plural-safe).
* ``=N`` exact match stays supported for both ``plural`` and
  ``selectordinal``.
* Fallback to ``other`` when the authored message skips the resolved
  category; missing ``other`` returns ``""`` (same as cardinal).
* Non-English locales without ordinal-specific grammar (e.g. ``zh-CN``)
  collapse to the ``other`` branch via CLDR, exactly what
  ``Intl.PluralRules('zh-CN',{type:'ordinal'}).select(n)`` returns.

Parity
------
Both ``static/js/i18n.js`` and ``packages/vscode/i18n.js`` must render
identical strings for the same (lang, message, n) — covered by
``TestOrdinalByteParity``.
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

ORDINAL_EN = "{n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}}"


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


class _OrdinalMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def _render_en(self, n: int) -> str:
        body = textwrap.dedent(
            """
            api.registerLocale('en', { place: %(msg)s });
            api.setLang('en');
            process.stdout.write(api.t('place', { n: %(n)d }));
            """
        ) % {"msg": json.dumps(ORDINAL_EN), "n": n}
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        return out

    def test_en_selectordinal_suffixes_follow_cldr(self) -> None:
        """The canonical English ordinal matrix from
        ``Intl.PluralRules('en', { type: 'ordinal' })`` — verified
        out-of-band with ``node -e``:
            1→one 2→two 3→few 4→other 11→other 21→one 22→two 23→few
            101→one 111→other 121→one
        """
        cases = {
            1: "1st",
            2: "2nd",
            3: "3rd",
            4: "4th",
            11: "11th",
            12: "12th",
            13: "13th",
            21: "21st",
            22: "22nd",
            23: "23rd",
            101: "101st",
            111: "111th",
            121: "121st",
        }
        for n, expected in cases.items():
            with self.subTest(n=n):
                self.assertEqual(self._render_en(n), expected)

    def test_exact_match_beats_cldr_category(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('en', { rank: %(msg)s });
            api.setLang('en');
            process.stdout.write(api.t('rank', { n: 1 }));
            """
        ) % {
            "msg": json.dumps(
                "{n, selectordinal, "
                "=0 {unranked} "
                "=1 {champion} "
                "one {#st} "
                "two {#nd} "
                "few {#rd} "
                "other {#th}"
                "}"
            )
        }
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "champion")

    def test_zh_cn_falls_through_to_other(self) -> None:
        body = textwrap.dedent(
            """
            api.registerLocale('zh-CN', { rank: %(msg)s });
            api.setLang('zh-CN');
            var out = [];
            [1, 2, 3, 11, 21].forEach(function (n) {
              out.push(api.t('rank', { n: n }));
            });
            process.stdout.write(JSON.stringify(out));
            """
        ) % {
            "msg": json.dumps(
                "{n, selectordinal, "
                "one {#\u4e00} "
                "two {#\u4e8c} "
                "few {#\u4e09} "
                "other {\u7b2c#}"
                "}"
            )
        }
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        # CLDR gives `other` for every integer in zh-CN ordinals, so every
        # value must land on the `other` branch (`"\u7b2c#"`), not the
        # English-leaning `one` / `two` / `few` branches.
        self.assertEqual(
            json.loads(out),
            ["\u7b2c1", "\u7b2c2", "\u7b2c3", "\u7b2c11", "\u7b2c21"],
        )

    def test_ordinal_lru_is_separate_from_cardinal(self) -> None:
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            api.registerLocale('en', {
              ord: %(ord)s,
              card: %(card)s
            });
            api.setLang('en');
            api.t('ord', { n: 1 });
            api.t('card', { n: 1 });
            var card = dbg.getPluralRulesCacheSize();
            var ord = dbg.getPluralRulesOrdinalCacheSize();
            process.stdout.write(JSON.stringify([card, ord]));
            """
        ) % {
            "ord": json.dumps(ORDINAL_EN),
            "card": json.dumps("{n, plural, one {# item} other {# items}}"),
        }
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            json.loads(out),
            [1, 1],
            "ordinal and cardinal PluralRules must live in separate LRU buckets",
        )

    def test_ordinal_lru_hard_cap_matches_cardinal(self) -> None:
        """Same 16-entry cap as the cardinal cache — anything else makes
        dashboards showing both buckets inexplicably asymmetric.
        """
        body = textwrap.dedent(
            """
            dbg.clearIntlCaches();
            var msg = %(msg)s;
            api.registerLocale('en', { k: msg });
            for (var i = 0; i < 32; i++) {
              var lang = 'en-X' + i;
              api.registerLocale(lang, { k: msg });
              api.setLang(lang);
              api.t('k', { n: i });
            }
            process.stdout.write(String(dbg.getPluralRulesOrdinalCacheSize()));
            """
        ) % {"msg": json.dumps(ORDINAL_EN)}
        code, out, err = _run_node(self.I18N_PATH, body)
        self.assertEqual(code, 0, err)
        self.assertLessEqual(int(out.strip()), 16)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestOrdinalWebUI(_OrdinalMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestOrdinalVSCode(_OrdinalMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestOrdinalByteParity(unittest.TestCase):
    """Render the same message / same n on both copies; the strings must
    match byte-for-byte. This is the runtime analogue of the byte-parity
    guard tests/test_i18n_runtime_redteam.py already performs on the
    cardinal / apostrophe / LRU branches.
    """

    def test_byte_parity_en_ordinal_matrix(self) -> None:
        matrix = [1, 2, 3, 4, 11, 12, 21, 22, 23, 101, 111, 121]
        body = textwrap.dedent(
            """
            api.registerLocale('en', { k: %(msg)s });
            api.setLang('en');
            var vals = %(matrix)s;
            var out = vals.map(function (n) { return api.t('k', { n: n }); });
            process.stdout.write(JSON.stringify(out));
            """
        ) % {"msg": json.dumps(ORDINAL_EN), "matrix": json.dumps(matrix)}
        code_w, out_w, err_w = _run_node(WEBUI_I18N, body)
        code_v, out_v, err_v = _run_node(VSCODE_I18N, body)
        self.assertEqual(code_w, 0, err_w)
        self.assertEqual(code_v, 0, err_v)
        self.assertEqual(
            json.loads(out_w),
            json.loads(out_v),
            "selectordinal output drifted between Web UI and VSCode i18n.js",
        )


if __name__ == "__main__":
    unittest.main()
