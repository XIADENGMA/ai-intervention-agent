"""ICU ``selectordinal`` 支持 + ordinal ``Intl.PluralRules`` LRU（Batch-2 H9）。

ICU MessageFormat 把序数（selectordinal，"5th"）与基数（plural，"5 items"）
分开，分别走 CLDR 的 ordinal / cardinal 规则。英语里二者不同（``plural(3)
=other`` 但 ``selectordinal(3)=few``）。主流实现（FormatJS / vue-i18n /
i18next / react-intl）全部支持；TC39 Intl.MessageFormat 草案也纳入。

合约：
  * ``_findIcuBlock`` 识别 ``selectordinal`` kind；
  * 新 ``_getPluralRulesOrdinal(lang)`` 独立 LRU（16 上限），钩子
    ``dbg.getPluralRulesOrdinalCacheSize`` / ``dbg.peekPluralRulesOrdinalKeys``；
  * ``#`` 替换同 cardinal 规则（仅 depth-0，inner-plural-safe）；
  * ``=N`` 精确匹配两种 kind 都支持；
  * 缺失命中类别回落 ``other``，再缺则返回 ``""``；
  * 无 ordinal 语法的 locale（如 zh-CN）由 CLDR 压到 ``other``。

两份 i18n.js 对同 (lang, message, n) 输出一致（``TestOrdinalByteParity``）。
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
        """英语 ordinal 标准矩阵（与 ``node -e`` 离线核对过）。"""
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
        # CLDR 对 zh-CN ordinal 一律归 other；所有值必须落在 ``第#`` 分支
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
            "ordinal / cardinal PluralRules 必须分桶",
        )

    def test_ordinal_lru_hard_cap_matches_cardinal(self) -> None:
        """与 cardinal 桶同 16 entry 上限，避免仪表盘两桶不对称。"""
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
    """同 message 同 n 两份 i18n.js 输出必须 byte-identical。对齐
    ``tests/test_i18n_runtime_redteam.py`` 在 cardinal/apostrophe/LRU 上的做法。
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
            "selectordinal 输出在 Web UI 与 VSCode i18n.js 之间漂移",
        )


if __name__ == "__main__":
    unittest.main()
