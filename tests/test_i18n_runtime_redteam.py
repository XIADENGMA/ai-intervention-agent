"""跨特性 runtime red-team：把 Batch-1 深度加固（撇号、嵌套 ``#``、LRU、
miss-key parity）在同一个模板里交叉起来，覆盖单特性测试漏掉的组合面。

覆盖：
  R5  撇号 ∩ plural 选择 ∩ mustache 插值：``other`` 分支里 ``'#total'``
      必须保留字面，同分支末尾不带引号的 ``#`` 仍走本地化数字。
  R6  跨 locale plural 爆发（>16 个 BCP-47 tag）下 PluralRules LRU 不破防。
  BP  byte-parity 哨兵：4 个模板覆盖 {apostrophe, nested ``#``, mustache, ICU}；
      任一回归立刻让两半漂移。与 ``test_i18n_pseudo_locale`` / ``test_i18n_icu_plural``
      故意有重叠，便于 CI 同时定位「哪个特性」+「哪一半」。
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
    """跑 > PLURAL_LRU_MAX 个不同 locale 触发淘汰，返回最终 PluralRules 桶大小。"""
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


# R5：撇号 + plural + mustache 混在同模板
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

# BP：模板刻意混合所有 Batch-1 特性；任一回归都会在 byte-parity 里炸出来
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
            f"跨 locale burst 撑爆了 PluralRules LRU 上限: size={size}",
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
            "Web UI 与 VSCode i18n.js 在 byte-parity 上漂移:\n  "
            + "\n  ".join(mismatches),
        )


if __name__ == "__main__":
    unittest.main()
