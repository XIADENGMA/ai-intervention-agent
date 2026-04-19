"""L3·G2 后续：给 Intl 实例缓存加 LRU 上限。

``_getIntl`` 按 ``(ctor, locale, JSON(options))`` 复用 ``Intl.*`` 实例（在
低端移动设备上构造成本达毫秒级，缓存必要），但原实现无上限；长会话里
多变的 ``formatNumber`` options 会持续膨胀 Web 与 VSCode host。

合约：两份 i18n.js 各自给 ``_intlCache`` / ``_pluralRulesCache`` 套 LRU：

    AIIA_I18N__intl_lru_max         = 50   # per-ctor
    AIIA_I18N__plural_rules_lru_max = 16   # per-module

命中 delete→set 挪到 tail，超出 max 删 head。

为避免把内部 state 暴给公共 API，测试用 ``AIIA_I18N__test`` 名字空间读写；
双下划线前缀方便源码审查一眼排除。

本文件锁定常量与淘汰顺序，``test_byte_parity`` 进一步保证两份决策一致，
漂移会直接挂测试而不是晚几周在内存 profile 里才现形。
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

# 必须与两份 i18n.js 内常量一致；漂移则测试必须显式失败，而不是悄悄放宽上限
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
        # 连续塞 2×cap 条不同 NumberFormat options；桶大小必须稳定在 ``INTL_LRU_MAX``
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
            f"塞 {INTL_LRU_MAX * 2} 条 options 后 NumberFormat 桶应稳定在 LRU 上限，实际 {size}",
        )

    def test_intl_cache_evicts_oldest_first(self) -> None:
        # 经典 LRU 检查：填满后 touch OPT_0 挪到 MRU，再插入新条目应淘汰 OPT_1 而非 OPT_0
        body = textwrap.dedent(
            f"""
            dbg.clearIntlCaches();
            for (let i = 0; i < {INTL_LRU_MAX}; i++) {{
              api.formatNumber(0, {{ maximumFractionDigits: i }});
            }}
            // 命中 OPT_0 挪到 MRU
            api.formatNumber(0, {{ maximumFractionDigits: 0 }});
            // 越过 cap 插新条目触发淘汰
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
            f"淘汰后桶大小异常: {report}",
        )
        self.assertTrue(
            report["opt0Survives"],
            "命中 reshuffle 失败：OPT_0 不应被淘汰",
        )
        self.assertTrue(
            report["opt1Evicted"],
            "LRU 淘汰失败：最老未命中条目 OPT_1 应被挤出",
        )

    def test_intl_cache_hit_does_not_grow_bucket(self) -> None:
        # 同 (ctor, locale, options) 二次调用必须复用，而不是再建一个实例
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
        # NumberFormat 撑爆不能挤掉 DateTimeFormat；每个 ctor 必须独立桶，避免高频 formatter 饿死其他
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
            f"NumberFormat 的 churn 污染了 DateTimeFormat 桶: {report}",
        )
        self.assertLessEqual(report["nfSize"], INTL_LRU_MAX)

    # ---- PluralRules 独立桶、独立上限 ----

    def test_plural_rules_cache_respects_hard_cap(self) -> None:
        # 每个 BCP-47 tag 一个 PluralRules 实例；上限防止恶意页面循环切 locale 撑爆内存
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
            f"PluralRules 桶失去上限: size={size} > {PLURAL_RULES_LRU_MAX}",
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
    """两份对同输入序列必须作出一致的淘汰决策；否则 Web UI 与 VSCode webview
    会给出细微不同的数字渲染（比如热门 locale 一边被淘汰、一边还在）。"""

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
            "Web UI 与 VSCode i18n.js 在 LRU 淘汰顺序上漂移",
        )


if __name__ == "__main__":
    unittest.main()
