"""Cross-feature runtime red-team — integration scenarios that cut
across the Batch-1 deepening changes (apostrophe escape, nested ``#``,
LRU cache, miss-key parity). Single-feature tests pin each behaviour
in isolation; this file pins the combinatorial surface that surfaces
only when two or three features interact on the same template.

What's covered
--------------
R5  Apostrophe escape ∩ plural selection ∩ mustache interpolation, with
    a quoted ``'#total'`` literal in a plural ``other`` branch that
    MUST survive as literal text while the unquoted trailing ``#``
    continues to receive the localised count.

R6  ``PluralRules`` LRU cap holds under a cross-locale plural burst
    (> 16 distinct BCP-47 tags). Combines the plural pipeline with the
    LRU eviction policy that bounds memory growth.

BP  Byte-parity sanity: four templates chosen so a regression in any
    of {apostrophe, nested ``#``, mustache, ICU} immediately diverges
    the two halves. This is deliberately redundant with
    ``test_i18n_pseudo_locale`` / ``test_i18n_icu_plural`` / etc. so
    when CI triages a parity drift, both the "which feature" and
    "which half" signals come from the same test module.
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


def _call_t(i18n_path: Path, template: str, params_json: str) -> str:
    script = textwrap.dedent(
        """
        globalThis.window = globalThis;
        globalThis.document = undefined;
        globalThis.navigator = { language: 'en' };
        require(%(path)s);
        const api = globalThis.AIIA_I18N;
        api.registerLocale('en', { m: %(tpl)s });
        api.setLang('en');
        process.stdout.write(api.t('m', %(params)s));
        """
    ) % {
        "path": json.dumps(str(i18n_path)),
        "tpl": json.dumps(template),
        "params": params_json,
    }
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _call_plural_burst(i18n_path: Path) -> int:
    """Exercise > PLURAL_LRU_MAX distinct locales to force eviction
    and return the final PluralRules cache size.
    """
    script = textwrap.dedent(
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
        dbg.clearIntlCaches();
        const tags = [
          'en','en-US','en-GB','zh','zh-CN','zh-TW','fr','fr-CA',
          'de','de-AT','es','es-MX','ja','ko','ru','pt','pt-BR',
          'it','nl','pl','tr','ar','he','cs','sk','hu','ro','sv',
          'da','fi','no','vi','th','uk','bg','hr','sl','lt','lv',
          'et','is'
        ];
        for (const tag of tags) {
          api.registerLocale(tag, { m: '{c, plural, one {# item} other {# items}}' });
          api.setLang(tag);
          api.t('m', { c: 1 });
        }
        process.stdout.write(String(dbg.getPluralRulesCacheSize()));
        """
    ) % {"path": json.dumps(str(i18n_path))}
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"node exited {proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return int(proc.stdout)


# R5 cases — apostrophe, plural, mustache all in one template.
R5_TEMPLATE = (
    "You have {count, plural, "
    "one {# task (don't forget!)} "
    "other {# tasks: '{#total}' = #}}"
)

R5_CASES = [
    (
        "count_one_apos_preserved",
        R5_TEMPLATE,
        '{"count":1}',
        "You have 1 task (don't forget!)",
    ),
    (
        "count_other_quoted_hash_literal",
        R5_TEMPLATE,
        '{"count":5}',
        "You have 5 tasks: {#total} = 5",
    ),
]

# BP cases — templates deliberately mix all Batch-1 features so any
# regression in one half lights up as a byte-parity failure.
BP_CASES = [
    ("greet_plain", "Hello, {{name}}!", '{"name":"Ada"}'),
    (
        "apos_and_literal_braces",
        "Don't forget: '{literal}'",
        "{}",
    ),
    (
        "nested_plural_select_plural_one",
        "{items, plural, one {{status, select, new {just added} other "
        "{{count, plural, one {# step} other {# steps}}}}} "
        "other {# items}}",
        '{"items":1,"status":"other","count":4}',
    ),
    (
        "nested_plural_outer_other",
        "{items, plural, one {{status, select, new {just added} other "
        "{{count, plural, one {# step} other {# steps}}}}} "
        "other {# items}}",
        '{"items":7}',
    ),
]


class _RedteamMixin(unittest.TestCase):
    __test__ = False
    I18N_PATH: Path

    def _run_r5(self, label: str, tpl: str, params_json: str, expected: str) -> None:
        out = _call_t(self.I18N_PATH, tpl, params_json)
        self.assertEqual(
            out, expected, f"R5 case={label!r}: got={out!r} expect={expected!r}"
        )

    def test_r6_plural_rules_cache_bounded_across_40_locales(self) -> None:
        size = _call_plural_burst(self.I18N_PATH)
        self.assertLessEqual(
            size,
            16,
            f"PluralRules LRU cap breached under cross-locale burst: size={size}",
        )


def _make_r5(label: str, tpl: str, params_json: str, expected: str):
    def _t(self: _RedteamMixin) -> None:
        self._run_r5(label, tpl, params_json, expected)

    _t.__name__ = f"test_r5_{label}"
    return _t


for _label, _tpl, _params, _expected in R5_CASES:
    setattr(
        _RedteamMixin,
        f"test_r5_{_label}",
        _make_r5(_label, _tpl, _params, _expected),
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestRedTeamWebUI(_RedteamMixin):
    __test__ = True
    I18N_PATH = WEBUI_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestRedTeamVSCode(_RedteamMixin):
    __test__ = True
    I18N_PATH = VSCODE_I18N


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestRedTeamByteParity(unittest.TestCase):
    def test_bp_all_cases_match_across_halves(self) -> None:
        mismatches: list[str] = []
        for label, tpl, params in BP_CASES:
            web = _call_t(WEBUI_I18N, tpl, params)
            vsc = _call_t(VSCODE_I18N, tpl, params)
            if web != vsc:
                mismatches.append(f"{label}: web={web!r} vsc={vsc!r}")
        self.assertFalse(
            mismatches,
            "byte-parity drift between Web UI and VSCode i18n.js:\n  "
            + "\n  ".join(mismatches),
        )


if __name__ == "__main__":
    unittest.main()
